"""Post-process lag_taker_fires: BTC+ETH (drop SOL) recommended-config cells + IS/OOS."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
F = pd.read_parquet(ROOT / "strategy_lab" / "lag_taker_fires_2026_05_29.parquet")
IS_CUTOFF = int(pd.Timestamp("2026-05-18", tz="UTC").timestamp())


def stat(x):
    x = np.asarray(x, float)
    n = len(x)
    if n < 2:
        return np.nan, np.nan
    m = x.mean()
    se = x.std(ddof=1) / np.sqrt(n)
    return m, (m / se if se else np.nan)


def maxdd(p):
    c = np.cumsum(p)
    return float((c - np.maximum.accumulate(c)).min()) if len(p) else 0.0


def summ(g, label):
    p = g.pnl.to_numpy()
    m, t = stat(p)
    return dict(cfg=label, n=len(g), wr=round(100 * g.won.mean(), 1),
                vwap=round(g.entry_vwap.mean(), 3), per_tr=round(m, 3),
                total=round(p.sum(), 1), maxdd=round(maxdd(p), 1), t=round(t, 2))


print("=== RECOMMENDED CONFIG SWEEP — BTC+ETH only (drop SOL), 15m+5m vs 15m-only ===")
rows = []
for thr in [2.0, 3.0, 5.0]:
    base = F[(F.delta_bps >= thr) & (F.asset.isin(["BTC", "ETH"]))]
    rows.append(summ(base, f"BTC+ETH all-tf >={thr}bps"))
    rows.append(summ(base[base.tf == "15m"], f"BTC+ETH 15m   >={thr}bps"))
    rows.append(summ(base[base.tf == "5m"], f"BTC+ETH 5m    >={thr}bps"))
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== BTC+ETH >=3bps  IS vs OOS ===")
g = F[(F.delta_bps >= 3.0) & (F.asset.isin(["BTC", "ETH"]))]
rows = [summ(g[g.slot_start < IS_CUTOFF], "IS"), summ(g[g.slot_start >= IS_CUTOFF], "OOS")]
print(pd.DataFrame(rows).to_string(index=False))

print("\n=== BTC+ETH >=3bps, drop 18-23 UTC (worst ToD) ===")
g2 = g[~g.hour.between(18, 23)]
print(pd.DataFrame([summ(g2, "BTC+ETH >=3bps ex-18-23UTC"),
                    summ(g2[g2.slot_start >= IS_CUTOFF], "  OOS only")]).to_string(index=False))
print("POSTPROC_DONE")
