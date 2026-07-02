"""
SUM-PAIR SHORT-SIDE ARB — T3, full universe, latency-aware (2026-06-16).

Error-audit §3 T3. Paper 2508.03474 appendix H: the SHORT side (split $1 -> sell BOTH legs above $1)
is claimed "more profitable" than the long side. Prior scan (`MM_Q_AND_SHORTSIDE` TEST 2) did BTC-15m
ONLY (0.008% of time > 1.035, median cap $0.000, PARK). This extends to BTC/ETH/SOL x 5m+15m AND adds
the latency-aware capturability test the prior scan lacked.

MECHANIC (instant, direction-agnostic, no hold-to-resolution):
  mint $1 -> 1 Up + 1 Down (PositionSplit, FEE-FREE), sell BOTH at their bids. If sum_bid > 1 you receive
  > $1 for a $1 set -> profit. Both sells are TAKER fills (cross into bids) -> fee 0.07*p*(1-p)/leg.
  Per-set PnL = sum_bid_fill - 1 - 0.07*[p_up*(1-p_up) + p_dn*(1-p_dn)].  No outcome needed (flat after).
  Break-even sum_bid ~ 1.035 (taker fee on BOTH sells; HIGHER drag than the long side's winner-only 1.7%).

MODEL (causal, mirrors sumpair_arb_t1):
  per slug scan native-10Hz L25; causal first-cross of top-of-book (bid_up0 + bid_dn0) > theta;
  FILL at first snapshot >= detect + 85ms: sell N=50 sh/side into the bid ladder (sell_at_bid_partial),
  require both legs fill >= 25 sh (real depth) else skip. sum_bid_fill = vwap_bid_up + vwap_bid_dn.
  opt = fill at the detect instant (isolates the latency haircut).
  theta in {1.00, 1.02, 1.035, 1.05}; BTC/ETH/SOL x 5m/15m; 1400 slugs/cell; bootstrap CI.

PRE-REGISTERED VERDICT: short-side ALIVE on a market iff lat $/set CI>0 at theta=1.035 with non-trivial
fill-frequency. Else confirms DEAD (extends the BTC-15m PARK to all 6 markets, latency-confirmed).
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_l25_streaming, load_resolutions  # noqa: E402
from engine_v2 import sell_at_bid_partial                        # noqa: E402

RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000; N_SHARES = 50.0; FEE = 0.07
THETAS = [1.00, 1.02, 1.035, 1.05]
COINS = os.environ.get("SP_COINS", "BTC,ETH,SOL").split(",")
TFS = ["5m", "15m"]
SAMPLE = int(os.environ.get("SP_SAMPLE", "1400"))


def boot(v, nb=5000):
    v = np.asarray(v, float); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))


def bid_sum_series(up, dn):
    """asof-align both legs' top-of-book BID onto the union grid -> (ts, sum_bid0)."""
    tsu, bpu = up[0], up[3][:, 0]
    tsd, bpd = dn[0], dn[3][:, 0]
    grid = np.union1d(tsu, tsd)
    iu = np.searchsorted(tsu, grid, "right") - 1
    idd = np.searchsorted(tsd, grid, "right") - 1
    ok = (iu >= 0) & (idd >= 0)
    grid, iu, idd = grid[ok], iu[ok], idd[ok]
    s0 = bpu[iu] + bpd[idd]
    fin = np.isfinite(s0)
    return grid[fin], s0[fin]


def sell_pair(up, dn, t_fill_us):
    """Sell N_SHARES/side into both bid ladders at the snapshot asof t_fill_us.
    Returns (vwap_up, vwap_dn, ok) or None. ok = both legs fill >= half."""
    iu = int(np.searchsorted(up[0], t_fill_us, "right") - 1)
    idd = int(np.searchsorted(dn[0], t_fill_us, "right") - 1)
    if iu < 0 or idd < 0: return None
    vu, shu, _u = sell_at_bid_partial(list(up[3][iu]), list(up[4][iu]), N_SHARES)
    vd, shd, _d = sell_at_bid_partial(list(dn[3][idd]), list(dn[4][idd]), N_SHARES)
    if shu <= 0 or shd <= 0: return None
    ok = (shu >= N_SHARES * 0.5) and (shd >= N_SHARES * 0.5)
    return vu, vd, ok


def pnl_per_set(vu, vd):
    """per-set short PnL = sum_bid - 1 - taker fee on both sells."""
    return (vu + vd) - 1.0 - FEE * (vu * (1 - vu) + vd * (1 - vd))


REC = []
for coin in COINS:
    rdf = load_resolutions(assets=[coin], timeframes=TFS)
    rdf = rdf[rdf.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
    for tf in TFS:
        sl_all = sorted(rdf[rdf.timeframe == tf].slug)
        if len(sl_all) > SAMPLE:
            step = len(sl_all) / SAMPLE
            sl_all = [sl_all[int(i * step)] for i in range(SAMPLE)]
        print(f"=== {coin} {tf}: {len(sl_all)} slugs — scanning L25 (short side) ===", flush=True)
        CH = 150
        for i in range(0, len(sl_all), CH):
            chunk = set(sl_all[i:i + CH])
            books = load_orderbook_l25_streaming(coin.lower(), slugs=chunk, subsample_1hz=False)
            for slug in chunk:
                up = books.get((slug, "Up")); dn = books.get((slug, "Down"))
                if up is None or dn is None: continue
                ts, s0 = bid_sum_series(up, dn)
                if len(ts) == 0: continue
                for th in THETAS:
                    above = np.where(s0 > th)[0]
                    if len(above) == 0:
                        REC.append((coin, tf, th, slug, "no_spike", np.nan)); continue
                    t_det = ts[above[0]]
                    wo = sell_pair(up, dn, t_det)
                    wr = sell_pair(up, dn, t_det + LAT_US)
                    for tag, w in (("opt", wo), ("lat", wr)):
                        if w is None:
                            REC.append((coin, tf, th, slug, f"{tag}_nofill", np.nan)); continue
                        vu, vd, ok = w
                        REC.append((coin, tf, th, slug, tag if ok else f"{tag}_thin", pnl_per_set(vu, vd)))
            del books

A = pd.DataFrame(REC, columns=["coin", "tf", "theta", "slug", "tag", "pnl"])
A.to_parquet(RES / "sumpair_short_t3_2026_06_16.parquet")

print("\n" + "=" * 96)
print("SHORT-SIDE T3 (per-set PnL = sum_bid_fill - 1 - taker fee both legs; instant flat, no resolution)")
print(f"{'coin':<5}{'tf':>4}{'theta':>7}{'slugs':>6}{'spike%':>7}{'fill%':>6}{'lat$/set':>10}{'CI95':>20}{'opt$/set':>10}")
for coin in COINS:
    for tf in TFS:
        for th in THETAS:
            sub = A[(A.coin == coin) & (A.tf == tf) & (A.theta == th)]
            nslug = sub.slug.nunique()
            spike = sub[~sub.tag.isin(["no_spike"])].slug.nunique()
            lat = sub[sub.tag == "lat"]; opt = sub[sub.tag == "opt"]
            nfill = len(lat)
            if nfill < 5:
                print(f"{coin:<5}{tf:>4}{th:>7.3f}{nslug:>6}{100*spike/max(1,nslug):>6.1f}%{nfill:>6} (few)"); continue
            m = lat.pnl.mean(); lo, hi = boot(lat.pnl.values)
            om = opt.pnl.mean() if len(opt) >= 5 else np.nan
            print(f"{coin:<5}{tf:>4}{th:>7.3f}{nslug:>6}{100*spike/max(1,nslug):>6.1f}%{100*nfill/max(1,nslug):>5.1f}%"
                  f"{m:>+10.4f}[{lo:>+7.4f},{hi:>+7.4f}]{om:>+10.4f}")

print("\nPOOLED per theta (realistic 85ms-latency fill):")
for th in THETAS:
    lat = A[(A.theta == th) & (A.tag == "lat")]
    opt = A[(A.theta == th) & (A.tag == "opt")]
    if len(lat) < 5:
        print(f"  theta={th}: n_fill={len(lat)} (few)"); continue
    m = lat.pnl.mean(); lo, hi = boot(lat.pnl.values); om = opt.pnl.mean() if len(opt) >= 5 else float('nan')
    print(f"  theta={th:.3f}  n_fill={len(lat):5d}  lat $/set={m:+.4f} CI=[{lo:+.4f},{hi:+.4f}]  opt={om:+.4f}")
print("\nREAD: theta=1.035 is fee-breakeven. lat $/set CI>0 there on any market = short side ALIVE; else DEAD")
print("  (extends the prior BTC-15m PARK to all 6 markets, latency-confirmed).")
