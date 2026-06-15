"""
CROSS-ASSET LEAD-LAG scalp  —  2026-06-09  (THREAD H2)

THESIS: BTC leads ETH/SOL. The follower's OWN binance feed already drives its poly book (the deployed
lag-taker). But BTC moves FIRST; if the follower's poly book lags BTC even more than it lags its own
feed, a BTC-conditioned entry buys a doubly-lagged token. Test at the OPEN (where lags live; mid-window
proven dead in scalp_fvg). Variants vs the OWN-signal baseline:
  OWN        : lead=sign(own 5s ret), gate |own|>=3bps         (deployed lag-taker, baseline)
  BTC        : lead=sign(btc 5s ret), gate |btc|>=THR          (leader-only)
  CONFLUENCE : btc & own agree AND both>=THR                   (filtered)
  BTC_LEADS  : |btc|>=THR AND |own|<LEADGAP (own hasn't moved) (pure lead-lag: bet follower follows BTC)
Entry follower poly lead-token @ ask (t+85ms, size-capped, spread<=.05, $25); exit SELL bid +60s.
won=(outcome==lead). Cheap gate ev<0.55. Offsets {5,15,30,45,60} (does BTC-lead extend the window?).
SEARCH window: BBO Mar30-Apr21 (disjoint). OOS on L25 Apr22-Jun8 if it beats OWN with CI>0.
PRE-REGISTERED (DSR): 2 followers x 2 tf x 4 variants x THR{3,5,8} x 5 offsets — count for deflation.
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000; LEADGAP = 2.0
FOLLOWERS = os.environ.get("XA_COINS", "ETH,SOL").split(",")
TFS = os.environ.get("XA_TFS", "15m,5m").split(",")
OFFS = [5, 15, 30, 45, 60]
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("XA_TAG", "")

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def asof(ts, v, t):
    i = np.searchsorted(ts, t, "right") - 1; return v[np.clip(i, 0, len(v) - 1)] if i >= 0 else np.nan
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))
def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def cell(v):
    v = np.asarray(v)
    if len(v) < 5: return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={(v>0).mean():.2f}"

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
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float))
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
                        ts, ask, bid, asz = bk[key]
                        je = np.searchsorted(ts, t + LAT_US, "right") - 1
                        if je < 0 or je >= len(ts): continue
                        a0, b0, s0 = ask[je], bid[je], asz[je]
                        if not (np.isfinite(a0) and np.isfinite(b0)) or (a0 - b0) > SPREAD: continue
                        sh = min(STAKE / a0, s0)
                        if sh * a0 < STAKE * 0.5: continue
                        ext = min(t + 60_000_000, send)
                        jx = np.searchsorted(ts, ext, "right") - 1
                        won = (r.outcome == lead)
                        sell = bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
                        ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, variant=variant,
                                         btc_bps=btc_r, own_bps=own_r, ev=a0, won=won,
                                         pnl60=bpnl(sell, a0, sh), absbtc=abs(btc_r), absown=abs(own_r)))
            del bbo, bk
        F = pd.DataFrame(ROWS)
        F.to_parquet(RES / f"scalp_xasset_2026_06_09{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf} rows so far={len(F)}", flush=True)

F = pd.DataFrame(ROWS)
F.to_parquet(RES / f"scalp_xasset_2026_06_09{TAG}.parquet")
print(f"\nsaved {len(F)} rows")
print("\n===== VARIANT x OFFSET (cheap ev<0.55, |signal|>=3) =====")
for (coin, tf), g in F.groupby(["coin", "tf"]):
    print(f"\n## {coin} {tf}")
    for variant in ["OWN", "BTC", "CONFL", "BTCLEAD"]:
        for off in OFFS:
            s = g[(g.variant == variant) & (g.off == off) & (g.ev < 0.55)]
            if len(s) >= 5:
                print(f"  {variant:8s} +{off:3d}s  {cell(s.pnl60.values)}")
        print()
print("READ: BTC/CONFL/BTCLEAD only beats OWN if a cell's $/tr exceeds the OWN cell at same off AND CI>0.")
print("CAVEAT: BBO top-of-book (optimistic); SEARCH window. OOS on L25 if a variant wins.")
