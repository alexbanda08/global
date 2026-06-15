"""
SYNTHETIC-BOOK SCALP A/B (2026-06-12) — tests the "6 edges" technique-2 (buy YES == sell NO).

Thesis: when the LEAD (wanted) token's ask is missing or its spread is too wide, the bot
currently SKIPS the fire ("book empty"). But going long the lead is mechanically identical to
SELLING the opposite token: a long-lead share can be acquired at  (1 - bid_opp)  by minting a
$1 set and dumping the opp leg into opp's bid. So the EFFECTIVE best ask for the lead =
  min( ask_lead , 1 - bid_opp )
and the effective best bid (for the +60s exit) =
  max( bid_lead , 1 - ask_opp ).

We A/B on the SAME candidate fires, clean disjoint OOS window (Mar30-Apr21, aliplayer BBO):

  ARM A (baseline)  : lead-only ladder, spread gate on lead (a0-b0)<=0.05.  == current engine.
  ARM B (synth)     : combined lead+opp ladder, spread gate on the EFFECTIVE best ask/bid.
                      Can fire when the lead alone could NOT (missing ask / wide spread).

Reported: per-coin + pooled, gated ev<0.55:
  - fill / skip counts each arm
  - mean entry vwap (price improvement)
  - $/tr, t, bootstrap CI each arm
  - **B-ONLY rescued fires** (A skipped, B filled) standalone $/tr  <- the crux:
    are the books the market "refused to give" actually profitable, or junk?

Fills/fees/exit faithful to scalp_fill_lib_2026_06_10 (resolve_size deep-fill artifact sizes,
0.015 round-trip fee proxy on sold lot, winner-only 0.07 held-to-resolution valuation, 120s
price-staleness guard, +60s time-sell clamped to slot_end). NO outcome-leak fallback.
"""
import os, sys, warnings
from pathlib import Path
import numpy as np, pandas as pd

warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo                              # noqa: E402
from scalp_fill_lib_2026_06_10 import resolve_size, bpnl, held_value, STALE_US  # noqa: E402

CANON = ROOT / "data/v4/canonical"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("OOS_COINS", "BTC,ETH,SOL,DOGE,XRP,BNB").split(",")
_FULL = ("2026-03-30", "2026-04-21"); _NEW = ("2026-04-06", "2026-04-21")
WIN = {"BTC": _FULL, "ETH": _FULL, "SOL": _FULL, "DOGE": _NEW, "BNB": _NEW, "XRP": ("2026-04-07", "2026-04-21")}
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet",
                         columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)])
    df = df.sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    # CAUSAL FIX 2026-06-13: index on bar END (start+1s) so asof returns the close KNOWN by t
    # (bar-START indexing = ~1s lookahead). A/B conclusion is asof-invariant (both arms share fires).
    starts = df.time_period_start_us.values.astype("int64")
    return starts + 1_000_000, df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


def boot(v, nb=5000):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v)))
    return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))


def cell(v):
    v = np.asarray(v); v = v[np.isfinite(v)]
    if len(v) < 5: return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan
    lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}]"


def walk_buy(levels, stake):
    """levels: list of (price, size). size may be inf (deep). Returns (vwap, shares) or None."""
    lv = sorted([(p, s) for p, s in levels if np.isfinite(p) and 0 < p < 1], key=lambda x: x[0])
    rem = stake; sh = 0.0; cost = 0.0
    for p, s in lv:
        max_sh = rem / p
        take = max_sh if not np.isfinite(s) else min(max_sh, s)
        if take <= 0: continue
        sh += take; cost += take * p; rem -= take * p
        if rem <= 1e-9: break
    if sh <= 0: return None
    return cost / sh, sh


def walk_sell(levels, shares):
    """levels: list of (price, size) — sell best (highest) price first. Returns (sold_sh, usd, vwap)."""
    lv = sorted([(p, s) for p, s in levels if np.isfinite(p) and 0 < p < 1], key=lambda x: -x[0])
    rem = shares; usd = 0.0; sold = 0.0
    for p, s in lv:
        take = rem if not np.isfinite(s) else min(rem, s)
        if take <= 0: continue
        usd += take * p; sold += take; rem -= take
        if rem <= 1e-9: break
    if sold <= 0: return 0.0, 0.0, np.nan
    return sold, usd, usd / sold


def side_snap(rec, lookup_us):
    """asof index + the (price,size) at lookup for one (slug,outcome) record. Returns dict or None."""
    if rec is None: return None
    ts, ask, bid, asz, bsz = rec
    j = int(np.searchsorted(ts, lookup_us, "right") - 1)
    if j < 0 or j >= len(ts): return None
    return dict(ts=ts, ask=ask, bid=bid, asz=asz, bsz=bsz, j=j,
                a=float(ask[j]), b=float(bid[j]))


def entry(lead, opp, lookup_us, synth):
    """Build entry ladder. synth=False -> lead only. Returns (vwap, shares, eff_ask, eff_bid) or None."""
    if lead is None: return None
    levels = []
    eff_ask = np.inf; eff_bid = -np.inf
    if np.isfinite(lead["a"]) and 0 < lead["a"] < 1:
        s, _ = resolve_size(lead["ts"], lead["asz"], lead["j"])
        levels.append((lead["a"], s)); eff_ask = min(eff_ask, lead["a"])
    if np.isfinite(lead["b"]): eff_bid = max(eff_bid, lead["b"])
    if synth and opp is not None:
        if np.isfinite(opp["b"]) and 0 < opp["b"] < 1:          # sell opp bid -> long lead at 1-bid_opp
            s, _ = resolve_size(opp["ts"], opp["bsz"], opp["j"])
            sa = 1.0 - opp["b"]; levels.append((sa, s)); eff_ask = min(eff_ask, sa)
        if np.isfinite(opp["a"]) and 0 < opp["a"] < 1:          # synthetic lead bid = 1-ask_opp (for spread)
            eff_bid = max(eff_bid, 1.0 - opp["a"])
    if not levels or not np.isfinite(eff_ask) or not np.isfinite(eff_bid): return None
    if round(eff_ask - eff_bid, 4) > SPREAD: return None
    w = walk_buy(levels, STAKE)
    if w is None: return None
    vwap, shares = w
    if shares * vwap < STAKE * 0.5: return None                 # underfill rule (kept)
    return vwap, shares, eff_ask, eff_bid


def exit_pnl(lead, opp, ext_us, entry_idx_lead, entry_idx_opp, shares, ev, won, synth):
    """+60s sell across combined bid ladder; remainder held to resolution. Faithful to lib."""
    levels = []
    # lead bid leg
    jx = int(np.searchsorted(lead["ts"], ext_us, "right") - 1)
    if jx >= entry_idx_lead and 0 <= jx < len(lead["ts"]) and np.isfinite(lead["bid"][jx]) \
            and (ext_us - lead["ts"][jx]) <= STALE_US:
        s, _ = resolve_size(lead["ts"], lead["bsz"], jx)
        levels.append((float(lead["bid"][jx]), s))
    # synth bid leg = sell lead == buy opp ask + merge -> receive 1-ask_opp
    if synth and opp is not None:
        ox = int(np.searchsorted(opp["ts"], ext_us, "right") - 1)
        if ox >= entry_idx_opp and 0 <= ox < len(opp["ts"]) and np.isfinite(opp["ask"][ox]) \
                and (ext_us - opp["ts"][ox]) <= STALE_US and 0 < opp["ask"][ox] < 1:
            s, _ = resolve_size(opp["ts"], opp["asz"], ox)
            levels.append((1.0 - float(opp["ask"][ox]), s))
    if not levels:                                              # no valid quote -> hold whole position
        return held_value(shares, ev, won)
    sold, _usd, svwap = walk_sell(levels, shares)
    rem = shares - sold
    pnl_sold = bpnl(svwap, ev, sold) if sold > 0 else 0.0
    return pnl_sold + held_value(rem, ev, won)


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & res.timeframe.isin(["5m", "15m"])].drop_duplicates("slug")
POOL = {a: {"A": [], "B": [], "Bonly": [], "dev": []} for a in ["all"]}  # dev = ev_A-ev_B on shared

for coin in COINS:
    lo = pd.Timestamp(WIN[coin][0], tz="UTC").value // 1000
    hi = pd.Timestamp(WIN[coin][1], tz="UTC").value // 1000
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo) & (res.slot_start_us <= hi)].copy()
    if not len(d):
        print(f"\n=== {coin}: no slugs ==="); continue
    be, bc = unified_1s(coin)
    ss = d.slot_start_us.values
    ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
    d = d.assign(fire_us=ss + 5_000_000, slot_end=d.slot_end_us.values, ret=ret,
                 delta_bps=np.abs(ret) * 1e4, lead=np.where(ret > 0, "Up", "Down"))
    d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
    print(f"\n=== {coin} OOS {WIN[coin][0]}..{WIN[coin][1]}: candidates(delta>=3) = {len(d)} ===", flush=True)

    A_pnl = []; B_pnl = []; Bonly = []; dev = []
    nA = nB = nfill_overlap = 0
    slugs = d.slug.tolist(); CH = 120
    for i in range(0, len(slugs), CH):
        chunk = d.iloc[i:i + CH]
        cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end.max()) + 2_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                            g.best_bid_size.values.astype(float))
        for _, r in chunk.iterrows():
            lead_oc = r.lead; opp_oc = "Down" if lead_oc == "Up" else "Up"
            rec_l = bk.get((r.slug, lead_oc)); rec_o = bk.get((r.slug, opp_oc))
            if rec_l is None: continue
            look = int(r.fire_us) + LAT_US
            lead = side_snap(rec_l, look); opp = side_snap(rec_o, look)
            if lead is None: continue
            won = (r.ret > 0) == (r.outcome == "Up")
            ext = min(int(r.fire_us) + 60_000_000, int(r.slot_end))

            eA = entry(lead, opp, look, synth=False)
            eB = entry(lead, opp, look, synth=True)
            gate = lambda ev: ev < 0.55                          # noqa: E731

            pA = None
            if eA is not None and gate(eA[0]):
                pA = exit_pnl(lead, opp, ext, lead["j"], (opp["j"] if opp else -1),
                              eA[1], eA[0], won, synth=False)
                A_pnl.append(pA); nA += 1
            pB = None
            if eB is not None and gate(eB[0]):
                pB = exit_pnl(lead, opp, ext, lead["j"], (opp["j"] if opp else -1),
                              eB[1], eB[0], won, synth=True)
                B_pnl.append(pB); nB += 1
            if pA is not None and pB is not None:
                dev.append(eA[0] - eB[0]); nfill_overlap += 1
            if pA is None and pB is not None:                    # rescued by synthetic
                Bonly.append(pB)
        del bbo, bk

    POOL["all"]["A"] += A_pnl; POOL["all"]["B"] += B_pnl
    POOL["all"]["Bonly"] += Bonly; POOL["all"]["dev"] += dev
    skipA = 1 - nA / max(1, len(d)); skipB = 1 - nB / max(1, len(d))
    print(f"  filled gated: A={nA} (skip {skipA:.0%})  B={nB} (skip {skipB:.0%})  rescued(B-only)={len(Bonly)}")
    print(f"  A {cell(A_pnl)}")
    print(f"  B {cell(B_pnl)}")
    if len(Bonly) >= 5:
        print(f"  B-only rescued       {cell(Bonly)}")
    else:
        print(f"  B-only rescued       n={len(Bonly)} (few)")
    if dev:
        print(f"  mean(ev_A - ev_B) on {nfill_overlap} shared = {np.mean(dev):+.4f}  (>0 => synth cheaper)")

print("\n" + "=" * 78)
print("POOLED (all coins, gated ev<0.55)")
print(f"  A (baseline lead-only)   {cell(POOL['all']['A'])}")
print(f"  B (synthetic combined)   {cell(POOL['all']['B'])}")
print(f"  B-only rescued fires     {cell(POOL['all']['Bonly'])}")
if POOL['all']['dev']:
    dv = np.array(POOL['all']['dev'])
    print(f"  mean(ev_A-ev_B) shared   {dv.mean():+.4f}  (n={len(dv)}; >0 => synth got cheaper entry)")
print("\nVERDICT keys:")
print("  - B $/tr CI still > 0  AND  B-only rescued $/tr CI > 0  => synthetic depth = free edge, ADOPT.")
print("  - B-only rescued $/tr <= 0 (drags pooled)              => rescued books are junk, KEEP lead-only.")
print("  - mean(ev_A-ev_B) ~ 0 and rescued ~ 0                  => technique-2 inert on this tape, NO-OP.")
