"""Sanity check: ml4t imports + master_features label/feature layout for the meta-label pipeline."""
import sys, json
print("PY", sys.version.split()[0])
oks = {}
for name, imp in [
    ("engineer", "from ml4t.engineer import compute_features, FeatureCatalog"),
    ("labeling", "from ml4t.engineer.labeling import meta_labels, apply_meta_model, calculate_sample_weights, sequential_bootstrap"),
    ("dsr", "from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import deflated_sharpe_ratio, deflated_sharpe_ratio_from_statistics"),
    ("pbo", "from ml4t.diagnostic.evaluation.stats.backtest_overfitting import compute_pbo"),
    ("cpcv_api", "from ml4t.diagnostic.api import CombinatorialCV, ValidatedCrossValidation"),
    ("core", "from ml4t.diagnostic.core import apply_purging_and_embargo"),
]:
    try:
        exec(imp); oks[name] = "OK"
    except Exception as e:
        oks[name] = f"FAIL {type(e).__name__}: {e}"
print(json.dumps(oks, indent=1))

import pandas as pd
m = pd.read_parquet(r"strategy_lab\autoresearch\_data\master_features.parquet")
print("master rows", len(m), "cols", len(m.columns))
print("assets", m.asset.value_counts().to_dict())
print("tf", m.tf.value_counts().to_dict() if "tf" in m.columns else "NA")
for c in ["pnl45", "pnl60", "reprice45", "y_scalp_pos", "entry_vwap", "delta_bps", "won", "fire_us", "ws_s", "shares", "segment"]:
    print("  ", c, "OK" if c in m.columns else "MISSING")
D = m[(m.delta_bps >= 5) & (m.entry_vwap < 0.55)]
print("d5/v055 cell n", len(D))
print("pnl45 mean all", round(m.pnl45.mean(), 4), "cell", round(D.pnl45.mean(), 4))
print("pnl60 mean all", round(m.pnl60.mean(), 4), "cell", round(D.pnl60.mean(), 4))
print("won rate cell", round(D.won.mean(), 4),
      "y_scalp_pos rate", round(D.y_scalp_pos.mean(), 4) if "y_scalp_pos" in D.columns else "NA")
print("cell by asset", D.asset.value_counts().to_dict())
print("cell by segment", D.segment.value_counts().to_dict() if "segment" in D.columns else "NA")
# time span
print("fire_us span days", round((m.fire_us.max() - m.fire_us.min()) / 1e6 / 86400, 1))
