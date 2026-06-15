"""
SUM-PAIR ARB T1 — atomic taker buy-both-hold, PRE-REGISTERED (2026-06-13).

The owed test (ce25 §8 DEPLOY-NO-pending). Paper 2508.03474 "Market Rebalancing Arbitrage" (long).
Strategy: when ask_up + ask_dn < threshold, buy BOTH legs (equal shares), HOLD to resolution.
One leg pays $1 regardless of direction -> per-pair PnL = 1 - sum_ask_fill - winner_fee. Direction-AGNOSTIC
(no adverse selection for the HELD atomic pair: you get $1 either way).

THE CRUX TESTED HERE: dips are sub-second transients (LEG2: legs reprice -0.9 lockstep). Can you actually
HIT one after 85ms detection->fill latency, with real depth on BOTH legs?

MODEL (causal, no look-ahead):
  - per slug, scan native-10Hz L25, top-of-book sum0(t) = ask_up0(t) + ask_dn0(t) (asof-aligned 1s grid).
  - DETECT: first t where sum0(t) < theta. (causal first-cross, NOT the min -> no look-ahead.)
  - FILL: first snapshot >= t + 85ms. Walk $STAKE on BOTH legs' asks at that snapshot (real depth).
    require both legs fill >= STAKE*0.5 (real depth) else SKIP (counts as "dip not capturable").
  - sum_ask_fill = vwap_up + vwap_dn at the fill snapshot (this is what you ACTUALLY pay -> the latency haircut).
  - OUTCOME: true chainlink resolution (load_resolutions). winner leg pays $1.
  - FEE: winner-only 0.07*p_win*(1-p_win), p_win = winning leg entry vwap. loser leg $0 fee.
  - per-pair PnL (1 share each) = 1 - sum_ask_fill - 0.07*p_win*(1-p_win).
  - ALSO report a NO-LATENCY optimistic fill (at detect snapshot) to isolate the latency haircut.

Thresholds: theta in {0.99,0.98,0.97,0.96,0.95}. Stake $25. Coins BTC/ETH/SOL (L25 depth), 5m+15m.
Metrics per coin/tf/theta: n_dip (slugs crossing theta), n_filled (depth ok post-latency), per-pair PnL
mean + slug-block-equivalent (1 entry/slug already), bootstrap CI, capacity $. NOT conditioned on outcome.
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_l25_streaming, load_resolutions   # noqa: E402
from book_walk import book_walk_fill                              # noqa: E402

RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000; STAKE = 25.0
THETAS = [0.99, 0.98, 0.97, 0.96, 0.95]
COINS = os.environ.get("SP_COINS", "BTC,ETH,SOL").split(",")
TFS = ["5m", "15m"]
SAMPLE = int(os.environ.get("SP_SAMPLE", "1400"))   # slugs per coin/tf (statistical power; bounds runtime)
WIN_S = {"5m": 300, "15m": 900}


def boot(v, nb=5000):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))


def topbook_sum_series(up, dn):
    """asof-align both legs' top-of-book ask onto the union ts grid -> (ts, sum0, idx_up, idx_dn)."""
    tsu, apu = up[0], up[1][:, 0]
    tsd, apd = dn[0], dn[1][:, 0]
    grid = np.union1d(tsu, tsd)
    iu = np.searchsorted(tsu, grid, "right") - 1
    idd = np.searchsorted(tsd, grid, "right") - 1
    ok = (iu >= 0) & (idd >= 0)
    grid, iu, idd = grid[ok], iu[ok], idd[ok]
    su = apu[iu]; sd = apd[idd]
    s0 = su + sd
    fin = np.isfinite(s0)
    return grid[fin], s0[fin], iu[fin], idd[fin]


def walk_pair(up, dn, t_fill_us):
    """Walk $STAKE on each leg's asks at the snapshot asof t_fill_us. Returns (vwap_u,vwap_d,ok) or None."""
    iu = int(np.searchsorted(up[0], t_fill_us, "right") - 1)
    idd = int(np.searchsorted(dn[0], t_fill_us, "right") - 1)
    if iu < 0 or idd < 0: return None
    vu, shu, usu, _l, undu = book_walk_fill(list(up[1][iu]), list(up[2][iu]), STAKE, side="buy")
    vd, shd, usd, _l, undd = book_walk_fill(list(dn[1][idd]), list(dn[2][idd]), STAKE, side="buy")
    if shu <= 0 or shd <= 0: return None
    ok = (usu >= STAKE * 0.5) and (usd >= STAKE * 0.5)   # real depth on BOTH legs
    return vu, vd, ok


REC = []
for coin in COINS:
    rdf = load_resolutions(assets=[coin], timeframes=TFS)
    rdf = rdf[rdf.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
    truth = dict(zip(rdf.slug, rdf.outcome))
    for tf in TFS:
        sl_all = sorted([s for s in rdf[rdf.timeframe == tf].slug])
        if len(sl_all) > SAMPLE:
            step = len(sl_all) / SAMPLE
            sl_all = [sl_all[int(i * step)] for i in range(SAMPLE)]
        print(f"=== {coin} {tf}: {len(sl_all)} slugs sampled — scanning L25 ===", flush=True)
        CH = 150
        for i in range(0, len(sl_all), CH):
            chunk = set(sl_all[i:i + CH])
            books = load_orderbook_l25_streaming(coin.lower(), slugs=chunk, subsample_1hz=False)
            for slug in chunk:
                up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
                if up is None or dn is None or slug not in truth: continue
                ts, s0, _iu, _id = topbook_sum_series(up, dn)
                if len(ts) == 0: continue
                won_up = truth[slug] == "Up"
                ss_us = int(slug.rsplit("-", 1)[1]) * 1_000_000
                for th in THETAS:
                    below = np.where(s0 < th)[0]
                    if len(below) == 0:
                        REC.append((coin, tf, th, slug, "no_dip", np.nan, np.nan, np.nan)); continue
                    t_det = ts[below[0]]
                    # optimistic (no-latency) fill at detect snapshot
                    wo = walk_pair(up, dn, t_det)
                    # realistic: first snapshot >= t_det + LAT
                    wr = walk_pair(up, dn, t_det + LAT_US)
                    for tag, w in (("opt", wo), ("lat", wr)):
                        if w is None:
                            REC.append((coin, tf, th, slug, f"{tag}_nofill", np.nan, np.nan, np.nan)); continue
                        vu, vd, ok = w
                        sumf = vu + vd
                        p_win = vu if won_up else vd
                        pnl = 1.0 - sumf - 0.07 * p_win * (1 - p_win)
                        REC.append((coin, tf, th, slug, tag if ok else f"{tag}_thin", sumf, pnl, p_win))
            del books

A = pd.DataFrame(REC, columns=["coin", "tf", "theta", "slug", "tag", "sum_fill", "pnl", "p_win"])
A.to_parquet(RES / "sumpair_arb_t1_2026_06_13.parquet")

print("\n" + "=" * 100)
print("SUM-PAIR ARB T1 RESULTS (per-pair PnL, $ per 1-share pair; true resolution; winner-only fee)")
print(f"{'coin':<5}{'tf':>4}{'theta':>6}{'slugs':>6}{'dip%':>6}{'fill%':>6}{'lat$/pair':>10}{'CI95':>20}{'opt$/pair':>10}{'capDay':>8}")
for coin in COINS:
    for tf in TFS:
        for th in THETAS:
            sub = A[(A.coin == coin) & (A.tf == tf) & (A.theta == th)]
            nslug = sub.slug.nunique()
            dip = sub[~sub.tag.isin(["no_dip"])].slug.nunique()
            lat = sub[sub.tag == "lat"]; opt = sub[sub.tag == "opt"]
            nfill = len(lat)
            if nfill < 5:
                print(f"{coin:<5}{tf:>4}{th:>6.2f}{nslug:>6}{100*dip/max(1,nslug):>5.0f}%{nfill:>6} (few)"); continue
            m = lat.pnl.mean(); lo, hi = boot(lat.pnl.values)
            om = opt.pnl.mean() if len(opt) >= 5 else np.nan
            # capacity/day: assume ~ (#5m slots=288/day, 15m=96/day); fills/day ~ fill-rate * slots
            slots_day = 288 if tf == "5m" else 96
            fday = (nfill / max(1, nslug)) * slots_day
            capday = m * fday
            print(f"{coin:<5}{tf:>4}{th:>6.2f}{nslug:>6}{100*dip/max(1,nslug):>5.0f}%{100*nfill/max(1,nslug):>5.0f}%"
                  f"{m:>+10.4f}[{lo:>+7.4f},{hi:>+7.4f}]{om:>+10.4f}{capday:>+8.1f}")

print("\nPOOLED (all coins/tf) per theta, realistic 85ms-latency fill:")
for th in THETAS:
    lat = A[(A.theta == th) & (A.tag == "lat")]
    if len(lat) < 5: print(f"  theta={th}: n={len(lat)} (few)"); continue
    m = lat.pnl.mean(); lo, hi = boot(lat.pnl.values)
    opt = A[(A.theta == th) & (A.tag == "opt")]
    om = opt.pnl.mean()
    print(f"  theta={th:.2f}  n_fill={len(lat):5d}  lat $/pair={m:+.4f} CI=[{lo:+.4f},{hi:+.4f}]  "
          f"opt $/pair={om:+.4f}  latency_haircut={om-m:+.4f}")
print("\nREAD: lat $/pair = realistic (must survive 85ms). opt = optimistic (fill at detect instant).")
print("  If lat $/pair CI<=0 across thetas -> dips don't survive latency -> atomic arb DEAD (as taker).")
print("  fill% = slugs where dip had real depth on BOTH legs post-latency. dip% = slugs crossing theta.")
