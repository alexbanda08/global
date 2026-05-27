"""Diagnose markov + regime_label issue + restrict fire window to panel coverage."""
import warnings, time
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
t0 = time.time()
def log(m): print(f"[{time.time()-t0:7.1f}s] {m}", flush=True)

ROOT = r"C:/Users/alexandre bandarra/Desktop/global"

r2 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_15m_v2_fixed.parquet")
r2_sol = r2[r2.asset=='SOL']
log(f"regime_label distribution SOL: {r2_sol.regime_label.value_counts().to_dict()}")
log(f"regime_score stats: min={r2_sol.regime_score.min():.3f} max={r2_sol.regime_score.max():.3f} mean={r2_sol.regime_score.mean():.3f}")
log(f"regime_score quantiles: p10={r2_sol.regime_score.quantile(0.1):.3f} p25={r2_sol.regime_score.quantile(0.25):.3f} p50={r2_sol.regime_score.quantile(0.5):.3f} p75={r2_sol.regime_score.quantile(0.75):.3f} p90={r2_sol.regime_score.quantile(0.9):.3f}")
log(f"trend_slope_30m stats: min={r2_sol.trend_slope_30m.min():.3f} max={r2_sol.trend_slope_30m.max():.3f} mean={r2_sol.trend_slope_30m.mean():.3f}")

# Check ETH regime_label as comparison
r2_eth = r2[r2.asset=='ETH']
log(f"regime_label distribution ETH: {r2_eth.regime_label.value_counts().to_dict()}")
log(f"regime_label distribution BTC: {r2[r2.asset=='BTC'].regime_label.value_counts().to_dict()}")

# Inspect SOL regime_label values
log(f"SOL regime_label unique values: {sorted(r2_sol.regime_label.unique())}")
