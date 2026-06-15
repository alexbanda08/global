"""
SAME-VENUE TWO-SIDED ARB scan  —  2026-06-09  (THREAD Z, different MECHANISM — not directional, not lag)
If at a causal snapshot up_ask + dn_ask < 1, buy 1 share of EACH -> exactly one pays $1 -> riskless
profit = 1 - up_ask - dn_ask - fee(winner). Fee winner-only ~0.07*p*(1-p) (<=0.0175). So net>0 iff
sum_ask < ~0.98. The handoff flagged "cross-token price-sum" dead only as a SIGNAL (lookahead artifact from
unsynced snapshots); here we use CAUSAL asof on each token at a common t (the real live book each side shows)
and measure: how often sum_ask<1 with executable SIZE on both legs, and the net-of-fee $ available.
Also report the SELL side (up_bid+dn_bid>1 = mint-and-sell territory, needs inventory).
Grid every 10s (5m) / 20s (15m). BTC/ETH/SOL 15m+5m, BBO Mar30-Apr21.
"""
import sys, os, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_orderbook_bbo
CANON = ROOT / "data/v4/canonical"; RES = ROOT / "strategy_lab/directional/_results"
LAT_US = 85_000
COINS = os.environ.get("AR_COINS", "BTC,ETH,SOL").split(",")
TFS = os.environ.get("AR_TFS", "15m,5m").split(",")
WIN = ("2026-03-30", "2026-04-21"); TAG = os.environ.get("AR_TAG", "")
GRID = {"5m": list(range(5, 291, 10)), "15m": list(range(5, 881, 20))}

res = pd.read_parquet(CANON / "resolutions_hf.parquet")
res = res[res.outcome.isin(["Up", "Down"])].drop_duplicates("slug")
BCOLS = ["timestamp_us", "slug", "outcome", "best_bid", "best_ask", "best_bid_size", "best_ask_size"]
lo_ts = pd.Timestamp(WIN[0], tz="UTC").value // 1000; hi_ts = pd.Timestamp(WIN[1], tz="UTC").value // 1000
ROWS = []
for coin in COINS:
    for tf in TFS:
        d = res[(res.ticker == coin) & (res.timeframe == tf) &
                (res.slot_start_us >= lo_ts) & (res.slot_start_us <= hi_ts)].copy()
        if not len(d): print(f"{coin} {tf}: none", flush=True); continue
        offs = GRID[tf]
        print(f"\n=== {coin} {tf}: {len(d)} windows x {len(offs)} grid ===", flush=True)
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
                up = bk.get((r.slug, "Up")); dn = bk.get((r.slug, "Down"))
                if up is None or dn is None: continue
                ss = int(r.slot_start_us)
                def at(arr, when):
                    tt, ask, bid, asz, bsz = arr
                    j = np.searchsorted(tt, when, "right") - 1
                    if j < 0 or j >= len(tt): return None
                    return ask[j], bid[j], asz[j], bsz[j]
                for off in offs:
                    t = ss + off * 1_000_000 + LAT_US
                    u = at(up, t); dd = at(dn, t)
                    if u is None or dd is None: continue
                    ua, ub, uasz, ubsz = u; da, db, dasz, dbsz = dd
                    if not (np.isfinite(ua) and np.isfinite(da) and np.isfinite(ub) and np.isfinite(db)): continue
                    sum_ask = ua + da; sum_bid = ub + db
                    ROWS.append(dict(coin=coin, tf=tf, slug=r.slug, off=off, sum_ask=sum_ask, sum_bid=sum_bid,
                                     ua=ua, da=da, buy_size=min(uasz, dasz), sell_size=min(ubsz, dbsz)))
            del bbo, bk
        F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_twosided_2026_06_09{TAG}.parquet")
        print(f"  [ckpt] {coin} {tf}: snaps={len(F[(F.coin==coin)&(F.tf==tf)])}", flush=True)

F = pd.DataFrame(ROWS); F.to_parquet(RES / f"scalp_twosided_2026_06_09{TAG}.parquet")
print(f"\nsaved {len(F)} snapshots")
print("\n===== BUY-BOTH ARB (sum_ask) distribution =====")
print(F.sum_ask.describe(percentiles=[.01, .05, .25, .5]).to_string())
for thr in [1.00, 0.99, 0.98, 0.95, 0.90]:
    s = F[F.sum_ask < thr]
    fr = len(s) / len(F)
    execu = s[s.buy_size * s.ua >= 5]  # at least ~$5 fillable on the thinner leg (rough)
    print(f"  sum_ask<{thr:.2f}: {len(s):6d} snaps ({fr:6.3%})  with>=~$5 size: {len(execu):5d}  "
          f"median buy_size(sh)={s.buy_size.median() if len(s) else float('nan'):.0f}  "
          f"mean net=1-sum-fee={ (1 - s.sum_ask - 0.0175).mean() if len(s) else float('nan'):+.3f}")
print("\n===== SELL-BOTH (sum_bid>1 = mint&sell, needs inventory) =====")
for thr in [1.00, 1.02, 1.05]:
    s = F[F.sum_bid > thr]
    print(f"  sum_bid>{thr:.2f}: {len(s):6d} ({len(s)/len(F):6.3%})  median sell_size(sh)={s.sell_size.median() if len(s) else float('nan'):.0f}")
print("\nREAD: a real same-venue arb exists iff sum_ask<0.98 occurs with executable size at a CAUSAL snapshot.")
print("If <0.98 is ~0% or only at dust size -> efficiently priced (expected). CAVEAT: BBO top-of-book size only.")
