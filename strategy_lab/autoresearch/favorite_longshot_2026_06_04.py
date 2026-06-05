"""
Favorite-longshot calibration on Polymarket up/down — the clean full-window test.

From F2 fade follow-up: a faint "favorite wins more than priced" tilt appeared but was underpowered.
Here we test it directly on the WHOLE trade tape (BTC+ETH+SOL, ~43 days): every BUY trade = pay price p
now, receive $1 iff that token wins (causal — outcome resolves later). Calibrate realized win-rate vs
price; compute actual 0.07 winner-only PnL per price bucket; then SLUG-BLOCK bootstrap (resample slugs,
not trades — the outcome is one event per slug) + DSR on the best tradeable bucket.

per-share PnL (stake = 1 share): won -> (1-p)*(1-0.07p) ; lost -> -p.   EV/share>0 = profitable bucket.
"""
import sys, warnings
import numpy as np, pandas as pd
warnings.filterwarnings("ignore")
sys.path.insert(0, r"data\v4\canonical")
from load import load_trades, load_resolutions
from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio_from_statistics
np.random.seed(0)

def pnl_share(win, p):
    return np.where(win, (1 - p) * (1 - 0.07 * p), -p)

def slug_block_boot(df, nb=3000):
    """Resample SLUGS with replacement; mean per-share PnL. Returns (mean, ci_lo, ci_hi)."""
    slugs = df.slug.values
    uniq, inv = np.unique(slugs, return_inverse=True)
    # precompute per-slug sum and count of pnl
    s = pd.DataFrame({"slug_i": inv, "pnl": df.pnl.values}).groupby("slug_i").agg(["sum", "count"])
    ssum = s[("pnl", "sum")].values; scnt = s[("pnl", "count")].values
    nS = len(uniq); means = np.empty(nb)
    for b in range(nb):
        idx = np.random.randint(0, nS, nS)
        means[b] = ssum[idx].sum() / scnt[idx].sum()
    return df.pnl.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)

rows_all = []
for asset in ["btc", "eth", "sol"]:
    t = load_trades(asset)
    r = load_resolutions(assets=[asset.upper()])
    win_map = dict(zip(r.slug, r.outcome))
    end_map = dict(zip(r.slug, r.slot_end_us))
    t = t[t.side == "buy"].copy()
    t["winner"] = t.slug.map(win_map)
    t = t[t.winner.notna()].copy()
    t["win"] = (t.outcome == t.winner).astype(int)
    t["ttl_s"] = (t.slug.map(end_map).astype("float64") - t.timestamp_us) / 1e6  # seconds to settlement
    p = t.price.values.astype(float)
    t["pnl"] = pnl_share(t.win.values.astype(bool), p)
    n_slug = t.slug.nunique()
    print(f"\n===== {asset.upper()}  buy-trades on resolved slugs: {len(t):,}  slugs: {n_slug:,} =====")
    print(f"overall: mean_price={p.mean():.4f} realized_wr={t.win.mean():.4f} EV/share={t.pnl.mean():+.5f}")
    # calibration by price bucket
    edges = np.array([0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.001])
    t["bk"] = pd.cut(t.price, edges, right=False)
    g = t.groupby("bk", observed=True).agg(n=("win", "size"), price=("price", "mean"),
                                           wr=("win", "mean"), ev=("pnl", "mean"))
    g["edge_vs_price"] = g.wr - g.price
    print(g.round(4).to_string())
    rows_all.append((asset, t[["slug", "pnl", "win", "price", "ttl_s"]]))

# pooled tradeable test: buy FAVORITES (price>=0.6) across all assets, slug-block bootstrap + DSR
print("\n================ TRADEABLE TEST: buy favorites (price>=0.60), hold to resolution ================")
for label, lo, hi in [("longshots p<0.40", 0.0, 0.40), ("mid 0.40-0.60", 0.40, 0.60),
                      ("favorites p>=0.60", 0.60, 1.0), ("strong fav p>=0.75", 0.75, 1.0)]:
    parts = []
    for asset, t in rows_all:
        parts.append(t[(t.price >= lo) & (t.price < hi)][["slug", "pnl", "win", "price"]])
    d = pd.concat(parts, ignore_index=True)
    if len(d) < 50:
        print(f"{label:22s} n_trades={len(d)} (few)"); continue
    mean, clo, chi = slug_block_boot(d)
    sh = d.pnl.mean() / d.pnl.std()
    nslug = d.slug.nunique()
    dsr = deflated_sharpe_ratio_from_statistics(observed_sharpe=sh, n_samples=nslug, n_trials=4,
                                                variance_trials=0.04, frequency="daily", periods_per_year=365)
    print(f"{label:22s} n_tr={len(d):>9,} slugs={nslug:>6,} wr={d.win.mean():.4f} price={d.price.mean():.4f} "
          f"EV/sh={mean:+.5f} slugCI=[{clo:+.5f},{chi:+.5f}] DSRp={dsr.probability:.3f} sig={dsr.is_significant}")
# is the strong-favorite edge concentrated in the final seconds (untradeable turnover)?
print("\n================ strong favorites (p>=0.75): edge vs TIME-TO-SETTLEMENT ================")
allfav = pd.concat([t[t.price >= 0.75] for _, t in rows_all], ignore_index=True)
ttlb = [0, 15, 30, 60, 120, 300, 1e9]
allfav["tb"] = pd.cut(allfav.ttl_s, ttlb, right=False)
for tb, d in allfav.groupby("tb", observed=True):
    if len(d) < 50: continue
    mean, clo, chi = slug_block_boot(d)
    print(f"ttl[{str(tb):14s}] n_tr={len(d):>9,} slugs={d.slug.nunique():>6,} wr={d.win.mean():.4f} "
          f"price={d.price.mean():.4f} EV/sh={mean:+.5f} slugCI=[{clo:+.5f},{chi:+.5f}]")
print("\nREAD: if EV/share>0 with slug-CI>0 persists at ttl>=60-120s, the favorite edge is genuinely tradeable")
print("      (not just last-second near-certain fills). If it lives only at ttl<30s, it is turnover-untradeable.")
