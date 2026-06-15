"""
LATE-SLOT ORACLE-DETERMINISM SNIPE  —  2026-06-11  (E2, priority-upgraded by the Wang late-window premium)

MECHANISM: late in the window (T-30..T-10s) the outcome is increasingly determined (price would need a move
larger than remaining-time vol allows), but the book lags: Wang calibration on 52M production trades shows
late-window prices sit ~1-3c BELOW fair (lam_late=+0.033 vs +0.007 early). A decoded whale does this at 87%
accuracy. The V2 fee curve 0.07*p*(1-p) is tiny at extreme p (~0.3c at 0.95). Strategy: at T-X, z-score the
move, buy the FAVORED token at ask if it's cheap vs Wang-fair, hold ~X s to resolution.

PRE-REGISTERED PRIMARY CELL: T-30s, |z|>=2.0, ask<=0.95, fair-ask>=0.02. Everything else = exploratory sweep
(multiplicity noted). LENSES: entry condition uses Wang-fair margin; microprice tilt bucketed on primary cell.

Window: BBO Mar30-Apr21, 6 coins (BTC/ETH/SOL/XRP/DOGE/BNB) x {5m,15m}. Signal price = binance 1s (settlement
is chainlink -> basis noise; flagged). sigma = std 1s logret 300s causal. Fill: top-of-book ask, size carry
(artifact-aware), spread<=0.10 late (books tight late; cap wide books). PnL winner-only 0.07 curve, $25 stake.
"""
import sys, os, math, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab/directional"))
from load import load_orderbook_bbo
from scalp_fill_lib_2026_06_10 import resolve_size, boot, cell
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
STAKE = 25.0; LAT_US = 85_000; VOL_LB = 300; SPREAD_LATE = 0.10
A_LATE, B_LATE = 0.0329, 1.0444     # Wang late-window fit (wang_transform_2026_06_11)
COINS = os.environ.get("OS_COINS", "BTC,ETH,SOL,XRP,DOGE,BNB").split(",")
TFS = os.environ.get("OS_TFS", "15m,5m").split(",")
OFFS = [30, 15]                      # seconds BEFORE slot_end
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("OS_TAG", "")
from scipy.stats import norm

def wang_fair(p): return float(norm.cdf(A_LATE + B_LATE * norm.ppf(np.clip(p, 0.01, 0.99))))
def klines(coin):
    sym = f"BINANCE_SPOT_{coin.upper()}_USDT"
    df = pd.read_parquet(CANON / "klines_1s.parquet", columns=["symbol_id", "time_period_start_us", "price_close"],
                         filters=[("symbol_id", "==", sym)]).sort_values("time_period_start_us").drop_duplicates("time_period_start_us")
    return df.time_period_start_us.values.astype("int64"), df.price_close.values.astype(float)
def pnl07(won, ask, sh):
    return sh * (1 - ask) * (1 - 0.07 * ask) if won else -sh * ask

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
for coin in COINS:
    try: ts_k, px_k = klines(coin)
    except Exception as e: print(f"{coin}: no klines ({e})", flush=True); continue
    lpx = np.log(px_k)
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): print(f"{coin} {tf}: no slugs", flush=True); continue
        print(f"=== {coin} {tf}: {len(d)} windows ===", flush=True)
        slugs = d.slug.tolist(); B = 150
        for i in range(0, len(slugs), B):
            chunk = d.iloc[i:i + B]
            cmin = int(chunk.slot_end_us.min()) - 70_000_000; cmax = int(chunk.slot_end_us.max()) + 2_000_000
            try:
                bbo = load_orderbook_bbo(coin, slugs=set(chunk.slug), min_ts_us=cmin, max_ts_us=cmax, columns=BCOLS)
            except Exception as e:
                print(f"  bbo load fail: {e}", flush=True); continue
            bk = {}
            for (sl, oc), g in bbo.groupby(["slug", "outcome"]):
                g = g.sort_values("timestamp_us")
                bk[(sl, oc)] = (g.timestamp_us.values.astype("int64"), g.best_ask.values.astype(float),
                                g.best_bid.values.astype(float), g.best_ask_size.values.astype(float),
                                g.best_bid_size.values.astype(float))
            for _, r in chunk.iterrows():
                ss = int(r.slot_start_us); send = int(r.slot_end_us)
                si = np.searchsorted(ts_k, ss, "right") - 1
                if si < VOL_LB + 5: continue
                strike = px_k[si]
                if not strike > 0: continue
                for off in OFFS:
                    t = send - off * 1_000_000
                    ti = np.searchsorted(ts_k, t, "right") - 1
                    if ti < VOL_LB or ti >= len(px_k): continue
                    sigma = np.std(np.diff(lpx[ti - VOL_LB:ti + 1]))
                    if not sigma > 0: continue
                    z = math.log(px_k[ti] / strike) / (sigma * math.sqrt(off))
                    dirn = "Up" if z > 0 else "Down"
                    arr = bk.get((r.slug, dirn))
                    if arr is None: continue
                    tt, ask, bid, asz, bsz = arr
                    je = np.searchsorted(tt, t + LAT_US, "right") - 1
                    if je < 0 or je >= len(tt): continue
                    # price staleness guard 30s (late books update fast)
                    if (t + LAT_US - tt[je]) > 30_000_000: continue
                    a0, b0 = ask[je], bid[je]
                    if not (np.isfinite(a0) and np.isfinite(b0)) or round(float(a0 - b0), 4) > SPREAD_LATE: continue
                    sa, _ = resolve_size(tt, asz, je); sb, _ = resolve_size(tt, bsz, je)
                    sh = min(STAKE / a0, sa)
                    if sh * a0 < STAKE * 0.5: continue
                    won = (r.outcome == dirn)
                    fair = wang_fair(norm.cdf(abs(z)))      # Wang-tilted determinism prob
                    mid = (a0 + b0) / 2
                    micro = (sa * b0 + sb * a0) / (sa + sb) if (sa + sb) > 0 else mid
                    tiltn = (micro - mid) / max(a0 - b0, 1e-4)
                    ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, z=abs(z), dirn=dirn,
                                     ask=a0, fair=fair, margin=fair - a0, won=won,
                                     pnl=pnl07(won, a0, sh), tiltn=tiltn,
                                     hour=(t // 1_000_000 % 86_400) // 3600))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"oracle_snipe_2026_06_11{TAG}.parquet")
        print(f"  [ckpt] total rows={len(F)}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"oracle_snipe_2026_06_11{TAG}.parquet")
print(f"\nsaved {len(F)} candidate evals")

print("\n##### PRIMARY (pre-registered): T-30s, |z|>=2.0, ask<=0.95, margin>=0.02 #####")
P = F[(F.off == 30) & (F.z >= 2.0) & (F.ask <= 0.95) & (F.margin >= 0.02)]
print(f"  POOLED  {cell(P.pnl.values)}  WR={P.won.mean() if len(P) else float('nan'):.3f}")
for (c, tf), g in P.groupby(["coin", "tf"]):
    print(f"  {c} {tf}: {cell(g.pnl.values)}  WR={g.won.mean():.3f}")

print("\n##### EXPLORATORY SWEEP (multiplicity! deflate before believing) #####")
for off in OFFS:
    for zthr in [1.5, 2.0, 3.0]:
        for cap in [0.93, 0.97]:
            s = F[(F.off == off) & (F.z >= zthr) & (F.ask <= cap) & (F.margin >= 0.02)]
            if len(s) >= 10:
                print(f"  T-{off}s z>={zthr} ask<={cap}: {cell(s.pnl.values)} WR={s.won.mean():.3f}")
print("\n  -- margin requirement ablation (T-30, z>=2, ask<=0.95) --")
for m in [0.0, 0.01, 0.02, 0.04]:
    s = F[(F.off == 30) & (F.z >= 2.0) & (F.ask <= 0.95) & (F.margin >= m)]
    if len(s) >= 10: print(f"  margin>={m:.2f}: {cell(s.pnl.values)} WR={s.won.mean():.3f}")
print("\n  -- MICROPRICE tilt on primary cell --")
if len(P) >= 30:
    q = P.tiltn.quantile([1/3, 2/3]).values
    for lab, sel in [("OPPOSED", P.tiltn <= q[0]), ("NEUTRAL", (P.tiltn > q[0]) & (P.tiltn <= q[1])), ("ALIGNED", P.tiltn > q[1])]:
        print(f"  {lab:8s} {cell(P[sel].pnl.values)}")
print("\n  -- time-split (primary cell) --")
if len(P) >= 20:
    med = P.slug.map(lambda s: int(s.rsplit('-', 1)[1])).median()
    h1 = P[P.slug.map(lambda s: int(s.rsplit('-', 1)[1])) <= med]; h2 = P[P.slug.map(lambda s: int(s.rsplit('-', 1)[1])) > med]
    print(f"  H1 {cell(h1.pnl.values)} | H2 {cell(h2.pnl.values)}")
print("\nREAD: edge real iff PRIMARY cell $/tr>0 CI>0 pooled AND holds the time-split. CAVEATS: binance-vs-chainlink")
print("settlement basis noise; BBO top-of-book; fills at extreme asks may be thin (size carry-aware but verify live).")
