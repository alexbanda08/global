"""
FAIR-VALUE-GAP (FVG) continuous-entry scalp  —  2026-06-09  (THREAD H1)

THESIS: the whole project edge = "the poly book LAGS the binance feed". The deployed lag-taker
captures that ONLY at the window open (+5s, |5s binance return|>=3bps). The prior session proved
the naive mid-window re-fire is DEAD (open-concentrated). The principled generalization: at ANY
second t in the window, the binance price implies a DIGITAL probability the window settles Up:
    strike      = binance close at slot_start            (up/down strike = window-open price)
    price_t     = binance close at t
    sigma       = std of 1s log-returns, trailing 300s   (causal, per-second vol)
    tau         = (slot_end - t) seconds remaining
    implied_p_up = Phi( ln(price_t/strike) / (sigma*sqrt(tau)) )       # driftless digital
    gap         = implied_p_up - poly_p_up                              # poly mis-pricing
If gap >> 0, poly underprices Up -> BUY Up (cheap, will catch up). gap << 0 -> BUY Down.
This is the lag-taker generalized to remaining-time scaling -> evaluable mid-window. If a
threshold |gap|>=g produces $/tr>0 CI>0 at offsets BEYOND the open, we have a real mid-window scalp
(also Kalshi-viable: Kalshi book is live+deep mid-window).

PRE-REGISTERED TRIAL SET (for DSR/deflation across the whole session):
  H1 (this script): FVG entry, threshold sweep {0.04,0.06,0.08,0.10,0.12}, vol-lookback {180,300},
                    one entry per window (FIRST offset where |gap|>=thr), exit SELL book +60s.
  H2: cross-asset lead-lag (separate script).  H3: late-window deterministic (separate script).
Windows: BBO Mar30-Apr21 = SEARCH (disjoint from the Apr22-Jun deploy search).  L25 Apr22-Jun8 = OOS.

FILL MODEL (apples-to-apples with the validated scalp_oos_bbo): entry $25 at lead best_ask asof
t+85ms (top-of-book, size-capped, spread<=0.05); exit SELL lead best_bid asof t+60s (clamp slot_end);
fee 0.015 round-trip on the 0.07 winner-only proxy. BBO=top-of-book (no L25 walk) -> entry optimistic.

OUTPUT: _results/scalp_fvg_grid_2026_06_09{TAG}.parquet  (one row per (window,offset) grid eval).
"""
import sys, os, warnings, math
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"
RES   = ROOT / "strategy_lab/directional/_results"

SPREAD = 0.05; STAKE = 25.0; LAT_US = 85_000; VOL_LB = int(os.environ.get("FVG_VOLLB", "300"))
EXIT_S = 60
COINS  = os.environ.get("FVG_COINS", "BTC,ETH,SOL").split(",")
TFS    = os.environ.get("FVG_TFS", "15m,5m").split(",")
WIN    = (os.environ.get("FVG_W0", "2026-03-30"), os.environ.get("FVG_W1", "2026-04-21"))
TAG    = os.environ.get("FVG_TAG", "")
TF_SEC = {"5m": 300, "15m": 900}
# offset grid per tf: leave room for the +60s exit before slot_end
GRID = {"15m": list(range(5, 781, 30)), "5m": list(range(5, 241, 20))}
_erf = np.vectorize(math.erf)
def Phi(x): return 0.5 * (1.0 + _erf(np.asarray(x, float) / math.sqrt(2.0)))

def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    ts = df.time_period_start_us.values.astype("int64"); px = df.price_close.values.astype(float)
    return ts, px
def asof_idx(ts, t):  # index of last bar at-or-before t
    return np.searchsorted(ts, t, "right") - 1
def bpnl(sell, ev, sh): return (sell - ev) * sh - 0.015 * sh * (ev * (1 - ev) + sell * (1 - sell))

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []

def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    idx = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[idx].mean(1), [2.5, 97.5]))
def cell(v):
    v = np.asarray(v)
    if len(v) < 5: return f"n={len(v):4d} (few)"
    t = v.mean() / v.std(ddof=1) * np.sqrt(len(v)) if v.std() > 0 else np.nan; lo, hi = boot(v)
    return f"n={len(v):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] won={(v>0).mean():.2f}"
outp = RES / f"scalp_fvg_grid_2026_06_09{TAG}.parquet"

for coin in COINS:
    ts_k, px_k = klines(coin); lpx = np.log(px_k)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d):
            print(f"{coin} {tf}: no slugs", flush=True); continue
        wsec = TF_SEC[tf]; offs = GRID[tf]
        print(f"\n=== {coin} {tf}: {len(d)} windows, {len(offs)} offsets/window ===", flush=True)
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
                si = asof_idx(ts_k, ss)
                if si < VOL_LB + 5:  continue
                strike = px_k[si]
                if not (strike > 0): continue
                up = bk.get((r.slug, "Up")); dn = bk.get((r.slug, "Down"))
                if up is None or dn is None: continue
                # binance 5s return at slot open (the deployed lag signal, for comparison)
                d5 = (px_k[asof_idx(ts_k, ss + 5_000_000)] / strike - 1.0) * 1e4
                for off in offs:
                    t = ss + off * 1_000_000
                    ti = asof_idx(ts_k, t)
                    if ti < VOL_LB or ti >= len(px_k): continue
                    tau = wsec - off
                    if tau < EXIT_S + 5: continue
                    sigma = np.std(np.diff(lpx[ti - VOL_LB:ti + 1]))     # per-second vol, causal
                    if not (sigma > 0): continue
                    price_t = px_k[ti]
                    z = math.log(price_t / strike) / (sigma * math.sqrt(tau))
                    imp_up = float(Phi(z))
                    # poly p_up from both tokens (avg of up-mid and 1-dn-mid when available)
                    def book_at(arr, when):
                        tt, ask, bid, asz, bsz = arr
                        j = np.searchsorted(tt, when, "right") - 1
                        if j < 0 or j >= len(tt): return None
                        return ask[j], bid[j], asz[j], bsz[j]
                    bu = book_at(up, t + LAT_US); bd = book_at(dn, t + LAT_US)
                    if bu is None or bd is None: continue
                    ua, ub, uasz, ubsz = bu; da, db_, dasz, dbsz = bd
                    polyup = []
                    if np.isfinite(ua) and np.isfinite(ub): polyup.append((ua + ub) / 2)
                    if np.isfinite(da) and np.isfinite(db_): polyup.append(1 - (da + db_) / 2)
                    if not polyup: continue
                    poly_p_up = float(np.mean(polyup))
                    gap = imp_up - poly_p_up
                    dirn = "Up" if gap > 0 else "Down"
                    # entry on chosen dir at its ask; exit that dir's bid +60
                    arr = up if dirn == "Up" else dn
                    ask_t, bid_t, asz_t, _bsz = (ua, ub, uasz, ubsz) if dirn == "Up" else (da, db_, dasz, dbsz)
                    if not (np.isfinite(ask_t) and np.isfinite(bid_t)) or (ask_t - bid_t) > SPREAD: continue
                    shares = min(STAKE / ask_t, asz_t)
                    if shares * ask_t < STAKE * 0.5: continue
                    ext = min(t + EXIT_S * 1_000_000, send)
                    bx = book_at(arr, ext)
                    won = (r.outcome == dirn)
                    sell = bx[1] if (bx is not None and np.isfinite(bx[1])) else (1.0 if won else 0.0)
                    hour = (t // 1_000_000 % 86_400) // 3600
                    ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, t_us=t, hour=hour,
                                     strike=strike, price_t=price_t, sigma_bps=sigma * 1e4, tau=tau,
                                     imp_up=imp_up, poly_p_up=poly_p_up, gap=gap, abs_gap=abs(gap),
                                     dirn=dirn, ev=ask_t, sell=sell, shares=shares, won=won,
                                     pnl60=bpnl(sell, ask_t, shares), d5_bps=d5))
            del bbo, bk
        # ---- CHECKPOINT: save accumulated rows + per-coin-tf quick stat (flushed) ----
        F = pd.DataFrame(ROWS)
        F.to_parquet(outp)
        ct = F[(F.coin == coin) & (F.tf == tf)]
        q8 = ct[ct.abs_gap >= 0.08].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first") if len(ct) else ct
        print(f"  [ckpt] {coin} {tf}: grid_rows={len(ct)}  |gap|>=.08 firstcross {cell(q8.pnl60.values) if len(q8) else 'n=0'}", flush=True)

F = pd.DataFrame(ROWS)
F.to_parquet(outp)
print(f"\nsaved {len(F)} grid rows -> {outp.name}")

print(f"\n===== FVG first-cross (1 entry/window) — pooled {'+'.join(COINS)} {'+'.join(TFS)}, vol_lb={VOL_LB} =====")
for thr in [0.04, 0.06, 0.08, 0.10, 0.12]:
    q = F[F.abs_gap >= thr].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first")
    sub = q; offmean = sub.off.mean() if len(sub) else np.nan
    print(f"  |gap|>={thr:.2f}  {cell(sub.pnl60.values)}  mean_off={offmean:.0f}s  mid_frac(off>=120)={ (sub.off>=120).mean() if len(sub) else float('nan'):.2f}")
print("\n  -- |gap|>=0.08 split open(+5..60) vs mid(>=120) --")
q = F[F.abs_gap >= 0.08].sort_values(["slug", "off"]).drop_duplicates("slug", keep="first")
print(f"     OPEN  off<120 {cell(q[q.off < 120].pnl60.values)}")
print(f"     MID   off>=120 {cell(q[q.off >= 120].pnl60.values)}")
print("\nREAD: if MID (off>=120) $/tr>0 CI>0 at some threshold -> real mid-window FVG scalp. Else edge stays open-only.")
print("CAVEAT: BBO top-of-book fill (optimistic). This is SEARCH window; OOS on L25 Apr22-Jun8 if it passes.")
