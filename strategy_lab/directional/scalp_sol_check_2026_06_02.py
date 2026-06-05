"""Quick SOL exit-scalp check — is the scalp dead (thin books) or alive on SOL? Bounded L25."""
import sys, math
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical")); sys.path.insert(0, str(ROOT / "strategy_lab"))
from load import load_orderbook_l25_streaming
from engine_v2 import LiveMimicConfig, find_book_strict, sell_at_bid_partial
FIRES = ROOT / "strategy_lab" / "lag_taker_fires_oos_2026_06_01.parquet"
FEE = 0.07; LAT = 85_000; rng = np.random.default_rng(20260602)
F = pd.read_parquet(FIRES); F = F[(F.asset == "SOL") & (F.delta_bps >= 3)].copy()
print(f"SOL fires delta>=3: {len(F)}")
cfg = LiveMimicConfig()
recs = []
import time; t0 = time.time()
books = load_orderbook_l25_streaming("sol", slugs=set(F.slug.values), subsample_1hz=False)
print(f"L25 loaded t={time.time()-t0:.0f}s")
for _, r in F.iterrows():
    bk = find_book_strict(books, r.slug, r.direction, int(r.fire_us) + 60_000_000 + LAT, max_staleness_us=cfg.max_book_staleness_us)
    ex = np.nan
    if bk is not None and len(bk.get("bp", [])):
        vw, fsh, _ = sell_at_bid_partial(np.asarray(bk["bp"], float), np.asarray(bk["bsz"], float), float(r.shares))
        if fsh > 0: ex = vw
    recs.append(dict(entry=float(r.entry_vwap), ex=ex, sh=float(r.shares), won=bool(r.won), dbps=float(r.delta_bps)))
D = pd.DataFrame(recs)


def hold(ev, sh, won): return (1 - ev) * sh * (1 - FEE * ev) if won else -ev * sh
def scalp(ev, ex, sh, won, fl):
    if not np.isfinite(ex): return hold(ev, sh, won)
    rt = (ex - ev) * sh
    if fl > 0: rt -= (fl * ev * (1 - ev) + fl * ex * (1 - ex)) * sh
    return rt
def st(x):
    x = np.asarray(x, float); n = len(x); m = x.mean(); se = x.std(ddof=1) / np.sqrt(n) if n > 1 else 0
    return m, (m / se if se else np.nan), n
def ci(x, B=6000):
    x = np.asarray(x, float); n = len(x)
    return tuple(np.percentile(x[rng.integers(0, n, (B, n))].mean(axis=1), [2.5, 97.5])) if n >= 5 else (np.nan, np.nan)

print(f"\nSOL exit+60s scalp, reached-bid={np.isfinite(D.ex).mean()*100:.0f}%")
for lab, sub in [("SOL δ≥3 all", D), ("SOL δ≥3 vwap<0.55", D[D.entry < 0.55]), ("SOL δ≥5 vwap<0.55", D[(D.dbps >= 5) & (D.entry < 0.55)])]:
    if len(sub) < 5: print(f"  {lab}: n={len(sub)} too few"); continue
    for fl, fn in [(0.0, "fee0"), (FEE, "fee.07")]:
        s = np.array([scalp(r.entry, r.ex, r.sh, r.won, fl) for _, r in sub.iterrows()])
        m, t, n = st(s); lo, hi = ci(s)
        print(f"  {lab:<22} {fn:<7} n={n:>4} $/tr={m:+.3f} t={t:.2f} CI[{lo:+.2f},{hi:+.2f}]")
