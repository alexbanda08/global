"""
THE EDITABLE SURFACE. An autoresearch agent edits ONLY this file.
Define a slug-selection / scalp candidate. `run.py` scores it via fitness.score_candidate.

Knobs:
  name          : label
  features      : list of feature names OR group names from feature_groups.json
                  groups: "indicators","clob","physics","entry"  (NEVER "path" — it leaks the label)
  model         : "xgb" | "rf" | "logit"
  entry_filter  : "broad" | "vwap055" | "d3vwap055" | "deployed"
  exit_dt       : 30 | 45 | 60 | 75 | 90   (fixed scalp exit used for the PnL label/eval)
  depth,n_est,C : model hyperparams

Goal: maximize `fitness` = lockbox gated $/tr lower-CI (must beat all-take, CI must clear 0).
Guardrails (enforced by fitness): label is scalp PnL-after-fee; bid_* path cols are forbidden;
lockbox is time-held-out; per-asset mix is reported to expose BTC-selection confounds.
"""

CANDIDATE = {
    "name": "baseline_indicators_clob_xgb",
    "features": ["indicators", "clob", "physics", "entry"],
    "model": "xgb",
    "entry_filter": "vwap055",
    "exit_dt": 45,
    "depth": 4,
    "n_est": 250,
}
