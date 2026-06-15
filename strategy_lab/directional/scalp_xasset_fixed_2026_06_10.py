"""
CROSS-ASSET LEAD-LAG scalp — CORRECTED EXIT MODEL (2026-06-10). Fixed clone of scalp_xasset_2026_06_09.py.
Exit via scalp_fill_lib_2026_06_10.exit_fill (size-capped bid, staleness guard, no outcome-leak; remainder held).
Every cell reports ALL + CLEAN (frac_held==0). Env: XA_COINS/XA_TFS/XA_TAG/XA_LIMIT.
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import entry_fill, exit_fill, boot, cell
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000; LEADGAP = 2.0
FOLLOWERS = os.environ.get("XA_COINS", "ETH,SOL").split(",")
TFS = os.environ.get("XA_TFS", "15m,5m").split(",")
OFFS = [5, 15, 30, 45, 60]
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("XA_TAG", ""); LIMIT = int(os.environ.get("XA_LIMIT", "0"))


def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)


def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1; return v[np.clip(i, 0, len(v) - 1)] if i >= 0 else np.nan


res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
btc_ts, btc_px = klines("BTC")
ROWS = []
for coin in FOLLOWERS:
    own_ts, own_px = klines(coin)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): print(f"{coin} {tf}: none", flush=True); continue
        if LIMIT > 0: d = d.iloc[:LIMIT]
        print(f"\n=== {coin} {tf}: {len(d)} windows ===", flush=True)
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
                for off in OFFS:
                    t = ss + off * 1_000_000
                    btc_r = (asof(btc_ts, btc_px, t) / asof(btc_ts, btc_px, ss) - 1.0) * 1e4
                    own_r = (asof(own_ts, own_px, t) / asof(own_ts, own_px, ss) - 1.0) * 1e4
                    if not (np.isfinite(btc_r) and np.isfinite(own_r)): continue
                    for variant, lead_r, ok in [
                        ("OWN", own_r, abs(own_r) >= 3.0),
                        ("BTC", btc_r, abs(btc_r) >= 3.0),
                        ("CONFL", btc_r, (np.sign(btc_r) == np.sign(own_r)) and abs(btc_r) >= 3.0 and abs(own_r) >= 3.0),
                        ("BTCLEAD", btc_r, abs(btc_r) >= 3.0 and abs(own_r) < LEADGAP),
                    ]:
                        if not ok: continue
                        lead = "Up" if lead_r > 0 else "Down"
                        key = (r.slug, lead)
                        if key not in bk: continue
                        ts, ask, bid, asz, bsz = bk[key]
                        ent = entry_fill(ts, ask, asz, t + LAT_US, STAKE, SPREAD, bid)
                        if ent is None: continue
                        ev = ent["ev"]; sh = ent["shares"]; eidx = ent["entry_idx"]
                        ext = min(t + 60_000_000, send)
                        won = (r.outcome == lead)
                        ef = exit_fill(ts, bid, bsz, eidx, ext, sh, ev, won)
                        ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, variant=variant,
                                         btc_bps=btc_r, own_bps=own_r, ev=ev, won=won, pnl60=ef["pnl"],
                                         frac_held=ef["frac_held"], held_full=ef["held_full"],
                                         absbtc=abs(btc_r), absown=abs(own_r)))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_xasset_fixed_2026_06_10{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf} rows so far={len(F)}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_xasset_fixed_2026_06_10{TAG}.parquet")
print(f"\nsaved {len(F)} rows")


def dual(sub):
    if len(sub) < 5: return f"n={len(sub):4d}(few)"
    return f"ALL {cell(sub.pnl60.values)} | CLEAN {cell(sub[sub.frac_held == 0].pnl60.values)}"


print("\n===== VARIANT x OFFSET (cheap ev<0.55, |signal|>=3) =====")
for (coin, tf), g in F.groupby(["coin", "tf"]):
    print(f"\n## {coin} {tf}")
    for variant in ["OWN", "BTC", "CONFL", "BTCLEAD"]:
        for off in OFFS:
            s = g[(g.variant == variant) & (g.off == off) & (g.ev < 0.55)]
            if len(s) >= 5:
                print(f"  {variant:8s} +{off:3d}s  {dual(s)}")
        print()
print("READ: BTC/CONFL/BTCLEAD beats OWN only if a cell's $/tr exceeds the OWN cell at same off AND CI>0.")
print("CAVEAT: BBO top-of-book (optimistic); SEARCH window. OOS on L25 if a variant wins.")
