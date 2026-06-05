"""
EXP2 (causal redo): does scalp edge concentrate in slugs with high CROSS-TOKEN price-sum deviation
measured AT fire (not +30s, which was lookahead)? Deviation = (up_ask0 + dn_ask0) - 1 at fire_us.
Mechanism (research): price-sum != 1 flags book dislocation/mispricing. Test if it RANKS scalp $/tr causally
and is NOT just a proxy for delta_bps (the lag we already use).
"""
import sys, warnings
from pathlib import Path
import numpy as np, pandas as pd
warnings.filterwarnings("ignore"); np.random.seed(0)
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data/v4/canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, fill_at_book
cfg = LiveMimicConfig()

m = pd.read_parquet(ROOT / "strategy_lab/autoresearch/_data/master_features.parquet")
g = m[(m.asset.isin(["BTC", "ETH"])) & (m.entry_vwap < 0.55)].copy()
g = g.dropna(subset=["fire_us"]).reset_index(drop=True)
print(f"gated fires: {len(g)}")

recs = []
for a in ["BTC", "ETH"]:
    ga = g[g.asset == a]; slugs = ga.slug.tolist(); B = 250
    for i in range(0, len(slugs), B):
        chunk = set(slugs[i:i+B])
        books = load_orderbook_l25_streaming(a.lower(), slugs=chunk, subsample_1hz=False)
        for _, r in ga[ga.slug.isin(chunk)].iterrows():
            fu = int(r.fire_us)
            up = fill_at_book(books, r.slug, "Up", fu, cfg=cfg, side="buy", spread_filter=1.0, notional_usd=25.0)
            dn = fill_at_book(books, r.slug, "Down", fu, cfg=cfg, side="buy", spread_filter=1.0, notional_usd=25.0)
            if up is None or dn is None: continue
            psum = up["ask0"] + dn["ask0"]                 # at-fire cross-token sum (best asks)
            psum_vwap = up["vwap"] + dn["vwap"]            # $25-walked both sides (live-style)
            recs.append(dict(slug=r.slug, asset=a, pnl60=r.pnl60, delta_bps=r.delta_bps,
                             psum_ask=psum, psum_vwap=psum_vwap, dev_ask=abs(psum - 1), dev_vwap=abs(psum_vwap - 1)))
        del books
R = pd.DataFrame(recs)
R.to_parquet(ROOT / "strategy_lab/autoresearch/_data/exp2_xtoken_2026_06_05.parquet")
print(f"evaluated {len(R)}  psum_ask mean={R.psum_ask.mean():.3f}  psum_vwap mean={R.psum_vwap.mean():.3f}")
print(f"corr(dev_ask, delta_bps)={np.corrcoef(R.dev_ask, R.delta_bps)[0,1]:+.3f}  "
      f"corr(dev_ask, pnl60)={np.corrcoef(R.dev_ask, R.pnl60)[0,1]:+.3f}")

def boot(v, nb=4000):
    v = np.asarray(v)
    if len(v) < 5: return (np.nan, np.nan)
    i = np.random.randint(0, len(v), (nb, len(v))); return tuple(np.percentile(v[i].mean(1), [2.5, 97.5]))
def show(col):
    R["q"] = pd.qcut(R[col].rank(method="first"), 4, labels=["Q1_tight", "Q2", "Q3", "Q4_wide"])
    print(f"\n-- scalp pnl60 by {col} quartile (causal, at-fire) --")
    for q, d in R.groupby("q", observed=True):
        v = d.pnl60.values; t = v.mean()/v.std(ddof=1)*np.sqrt(len(v)) if v.std() > 0 else np.nan
        lo, hi = boot(v)
        print(f"  {q:9s} n={len(d):4d} $/tr={v.mean():+.3f} t={t:+.2f} CI=[{lo:+.3f},{hi:+.3f}] mean_dev={d[col].mean():.3f} mean_delta={d.delta_bps.mean():.1f}")
show("dev_ask"); show("dev_vwap")
# control: is it just delta_bps? double-sort
print("\n-- within delta>=5, by dev_ask median split (is xtoken edge ON TOP of delta?) --")
hi5 = R[R.delta_bps >= 5]
if len(hi5) > 20:
    md = hi5.dev_ask.median()
    for lab, d in [("dev<med", hi5[hi5.dev_ask < md]), ("dev>=med", hi5[hi5.dev_ask >= md])]:
        v = d.pnl60.values; lo, hi = boot(v)
        print(f"  {lab:9s} n={len(d):4d} $/tr={v.mean():+.3f} CI=[{lo:+.3f},{hi:+.3f}]")
print("\nREAD: real selector if Q4_wide >> base WITH CI>0 AND it adds edge within delta>=5 (not just a delta proxy).")
