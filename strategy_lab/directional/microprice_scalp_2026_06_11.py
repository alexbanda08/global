"""
STOIKOV MICROPRICE on the open exit-scalp  —  2026-06-11
Microprice = size-weighted fair value: P_micro = (ask_size*bid + bid_size*ask) / (bid_size + ask_size)
(more resting BID volume pushes fair value toward the ask). At fire time (+5s) on the LEAD token's book:
  tilt = micro - mid.  ALIGNED  = book pressure already points the binance way (book partially adjusted)
                       OPPOSED = book pressure points away (book NOT yet adjusted -> more reprice left?)
HYPOTHESIS (principled version of the dead naive token-lag gate): scalp $/tr is larger when the book has
NOT yet adjusted (opposed/neutral tilt). If ALIGNED is just as good, microprice adds nothing.
Corrected harness (scalp_fill_lib: staleness, size carry-forward, held-to-resolution, ALL/CLEAN).
Window: BBO Mar30-Apr21 (burned for deflation — this is FEATURE EXPLORATION; any positive needs live confirm).
Discipline: tercile buckets + time-split + per-coin consistency. Sizes: carried (size==0 artifact-aware).
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell, resolve_size
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000
COINS = os.environ.get("MP_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("MP_TFS", "15m,5m").split(",")
WIN = ("2026-03-30", "2026-04-21")

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, len(v) - 1)], np.nan)

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
for coin in COINS:
    be, bc = klines(coin)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): continue
        ss = d.slot_start_us.values
        ret = asof(be, bc, ss + 5_000_000) / asof(be, bc, ss) - 1.0
        d = d.assign(fire_us=ss + 5_000_000, ret=ret, delta_bps=np.abs(ret) * 1e4,
                     lead=np.where(ret > 0, "Up", "Down"))
        d = d[np.isfinite(d.ret) & (d.delta_bps >= 3.0)].reset_index(drop=True)
        print(f"=== {coin} {tf}: {len(d)} candidates ===", flush=True)
        slugs = d.slug.tolist(); B = 120
        for i in range(0, len(slugs), B):
            chunk = d.iloc[i:i + B]
            cmin = int(chunk.fire_us.min()) - 2_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
            bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
            bk = {}
            for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
                g = g.sort_values("timestamp_us")
                bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                                g.best_bid_size.values.astype(float))
            for _, r in chunk.iterrows():
                key = (r.slug, r.lead)
                if key not in bk: continue
                ts, ask, bid, asz, bsz = bk[key]
                fire = int(r.fire_us); send = int(r.slot_end_us)
                ef = entry_fill(ts, ask, asz, fire + LAT_US, STAKE, SPREAD, bid)
                if ef is None: continue
                je = ef["entry_idx"]
                a0, b0 = ask[je], bid[je]
                if a0 >= 0.55: continue
                # microprice with artifact-aware sizes
                sa, _ = resolve_size(ts, asz, je); sb, _ = resolve_size(ts, bsz, je)
                if not (np.isfinite(sa) and np.isfinite(sb)) or (sa + sb) <= 0 or not np.isfinite(a0 + b0):
                    continue
                mid = (a0 + b0) / 2.0
                micro = (sa * b0 + sb * a0) / (sa + sb)
                tilt = micro - mid                      # >0 = book pressure UP on the lead token
                spr = max(a0 - b0, 1e-4)
                tiltn = tilt / spr                      # normalized [-0.5,+0.5]
                won = (r.ret > 0) == (r.outcome == "Up")
                xf = exit_fill(ts, bid, bsz, je, min(fire + 60_000_000, send), ef["shares"], ef["ev"], won)
                pnl = xf["pnl"]
                ROWS.append(dict(coin=coin, tf=tf, fire_us=fire, ev=ef["ev"], won=won, pnl60=pnl,
                                 frac_held=xf["frac_held"], delta=r.delta_bps, tiltn=tiltn,
                                 imb=sb / (sa + sb)))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / "microprice_scalp_2026_06_11.parquet")
        print(f"  [ckpt] rows={len(F)}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / "microprice_scalp_2026_06_11.parquet")
print(f"\nsaved {len(F)} fires (gated <0.55)")
C = F[F.frac_held == 0]   # CLEAN subset
print(f"CLEAN n={len(C)}")
print("\n===== MICROPRICE TILT (normalized, lead-token book) vs scalp $/tr — CLEAN =====")
print("  tiltn>0 = book pressure ALREADY points the binance way (aligned).")
q = C.tiltn.quantile([1/3, 2/3]).values
for lab, sel in [("OPPOSED (low)", C.tiltn <= q[0]), ("NEUTRAL", (C.tiltn > q[0]) & (C.tiltn <= q[1])),
                 ("ALIGNED (high)", C.tiltn > q[1])]:
    print(f"  {lab:14s} {cell(C[sel].pnl60.values)}")
print("\n  -- sign buckets --")
for lab, sel in [("tilt<-0.05", C.tiltn < -0.05), ("|tilt|<=0.05", C.tiltn.abs() <= 0.05), ("tilt>+0.05", C.tiltn > 0.05)]:
    print(f"  {lab:14s} {cell(C[sel].pnl60.values)}")
print("\n===== time-split consistency (gate must hold on both halves) =====")
med = C.fire_us.median()
for half, sel in [("H1", C.fire_us <= med), ("H2", C.fire_us > med)]:
    h = C[sel]; qq = h.tiltn.quantile([1/3, 2/3]).values
    print(f"  {half} OPPOSED {cell(h[h.tiltn <= qq[0]].pnl60.values)} | ALIGNED {cell(h[h.tiltn > qq[1]].pnl60.values)}")
print("\n===== per-coin (OPPOSED tercile vs ALL) =====")
for c_ in C.coin.unique():
    h = C[C.coin == c_]; qq = h.tiltn.quantile([1/3]).values
    print(f"  {c_}: ALL {cell(h.pnl60.values)} | OPPOSED {cell(h[h.tiltn <= qq[0]].pnl60.values)}")
print("\nREAD: microprice adds value only if one tilt bucket beats ALL consistently (both halves, most coins).")
print("CAVEAT: burned search window — feature exploration only; any winner needs live confirmation.")
