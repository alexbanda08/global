"""
MID-WINDOW lag-taker POC — CORRECTED EXIT MODEL (2026-06-10). Fixed clone of scalp_midwindow_2026_06_07.py.
Exit via scalp_fill_lib_2026_06_10.exit_fill (size-capped bid, staleness guard, no outcome-leak; remainder held).
Every cell reports ALL + CLEAN (frac_held==0). Env: MW_COINS, MW_TAG, MW_LIMIT.
"""
import sys, warnings, os
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("MW_COINS", "BTC,ETH").split(",")
LIMIT = int(os.environ.get("MW_LIMIT", "0"))
OFFSETS = [5, 120, 240, 360, 480, 600, 720]
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("MW_TAG", "")


def unified_1s(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1; return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"]) & (res.timeframe == "15m")].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
ALL = []
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
for coin in COINS:
    d = res[(res.ticker == coin) & (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
    if not len(d): print(f"{coin}: no slugs"); continue
    if LIMIT > 0: d = d.iloc[:LIMIT]
    be, bc = unified_1s(coin)
    print(f"\n=== {coin} 15m OOS {WIN[0]}..{WIN[1]}: {len(d)} slots, offsets={OFFSETS} ===", flush=True)
    slugs = d.slug.tolist(); B = 120
    for i in range(0, len(slugs), B):
        chunk = d.iloc[i:i + B]
        cmin = int(chunk.slot_start_us.min()) - 2_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
        bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
        bk = {}
        for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
            g = g.sort_values("timestamp_us")
            bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                            g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                            g.best_bid_size.values.astype(float))
        for _, r in chunk.iterrows():
            ss = int(r.slot_start_us); send = int(r.slot_end_us)
            for off in OFFSETS:
                t = ss + off * 1_000_000
                rt = asof(be, bc, t) / asof(be, bc, t - 5_000_000) - 1.0
                if not np.isfinite(rt): continue
                db = abs(rt) * 1e4
                if db < 3.0: continue
                lead = "Up" if rt > 0 else "Down"
                key = (r.slug, lead)
                if key not in bk: continue
                ts, ask, bid, asz, bsz = bk[key]
                ent = entry_fill(ts, ask, asz, t + LAT_US, STAKE, SPREAD, bid)
                if ent is None: continue
                ev = ent["ev"]; sh = ent["shares"]; eidx = ent["entry_idx"]; b0 = ent["b0"]; a0 = ent["a0"]
                ext = min(t + 60_000_000, send)
                won = (rt > 0) == (r.outcome == "Up")
                ef = exit_fill(ts, bid, bsz, eidx, ext, sh, ev, won)
                # token-lag gate (unchanged): lead token mid change over [t-5s,t]
                jp = np.searchsorted(ts, t - 5_000_000 + LAT_US, "right") - 1
                mid_now = (a0 + b0) / 2.0
                mid_prev = (ask[jp] + bid[jp]) / 2.0 if (0 <= jp < len(ts) and np.isfinite(ask[jp]) and np.isfinite(bid[jp])) else np.nan
                tok_chg = mid_now - mid_prev
                lagging = np.isfinite(tok_chg) and (tok_chg <= 0.005)
                ALL.append(dict(coin=coin, off=off, ev=ev, delta=db, won=won, pnl60=ef["pnl"],
                                frac_held=ef["frac_held"], held_full=ef["held_full"],
                                tok_chg=tok_chg, lagging=bool(lagging)))
        del bbo, bk
A = pd.DataFrame(ALL)
A.to_parquet(RES / f"scalp_midwindow_fixed_2026_06_10{TAG}.parquet")


def line(sub):
    if len(sub) < 5: return f"n={len(sub):4d} (few)"
    return f"{cell(sub.pnl60.values)} won={sub.won.mean():.2f}"


def dual(sub):
    return f"ALL {line(sub)} | CLEAN {line(sub[sub.frac_held == 0])}"


print(f"\n===== $/tr BY OFFSET (pooled {'+'.join(COINS)}, 15m) =====")
for off in OFFSETS:
    s = A[A.off == off]; g = s[s.ev < 0.55]
    print(f"  +{off:4d}s  filled: {dual(s)}")
    print(f"  {'':6s}  gated:  {dual(g)}")
print("\n  -- gated & delta>=5 by offset --")
for off in OFFSETS:
    g = A[(A.off == off) & (A.ev < 0.55) & (A.delta >= 5)]
    print(f"  +{off:4d}s  {dual(g)}")
print("\n  -- TOKEN-LAG gate by offset --")
for off in OFFSETS:
    g = A[(A.off == off) & (A.lagging)]
    print(f"  +{off:4d}s  {dual(g)}")
print("\n  -- MID-WINDOW pooled (off>=120) lag-gated vs not --")
mid = A[A.off >= 120]
print(f"  all mid            {dual(mid)}")
print(f"  mid lagging        {dual(mid[mid.lagging])}")
print(f"  mid NOT lagging    {dual(mid[~mid.lagging])}")
print(f"  mid lagging&<0.55  {dual(mid[mid.lagging & (mid.ev < 0.55)])}")
print("\nREAD: mid-window offsets (>=120) $/tr>0 CI>0 -> lag edge persists mid-window. CAVEAT: BBO top-of-book.")
