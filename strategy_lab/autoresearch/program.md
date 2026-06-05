# autoresearch — program.md (agent instructions)

You are an autonomous strategy-research agent. Your job: **find a slug-selection / scalp candidate that
maximizes `fitness`** by editing ONE file — `candidate.py` — then running `python run.py`, reading the
result, keeping or discarding, and repeating. You wake the operator with a `history.jsonl` of experiments
and (hopefully) a better edge.

## The loop
1. Edit `candidate.py` (the `CANDIDATE` dict only).
2. `python run.py` → prints metrics, appends to `history.jsonl`, tells you NEW BEST or kept.
3. Keep the change if `fitness` improved AND the KEEP conditions below hold; else revert and try another.
4. Repeat. Log your reasoning per iteration.

## The metric (single source of truth) — `fitness`
`fitness` = the **lockbox gated $/tr lower-CI** (conservative), where:
- **label = scalp PnL-after-fee** (0.015 round-trip) — NOT outcome, NOT win-rate, NOT AUC. (WR≠edge here.)
- **lockbox** = last 25% of fires by time, never trained on (purged).
- gated = fires the model selects (calibrated P(scalp-wins) > a dev-chosen threshold).
- a candidate must BEAT all-take (`all_dpt`) and its `gated_ci` must exclude 0.

## KEEP a candidate only if ALL hold
- `gated_ci[0] > 0` (lower bound excludes 0).
- `lift > 0` (gated beats all-take on the lockbox).
- `asset_confound == false` (a gate that keeps >90% one asset is just selecting BTC — the fitness already
  applies a −3 penalty, but do not be fooled by a raw `gated_dpt` that comes from an all-BTC gate).
- `gated_n >= 30` (enough lockbox fires to trust).

## What is DEAD (do not waste iterations — proven this session)
- Predicting **direction / which side wins** from any feature at fire time → efficient-market priced-in
  (microstructure AUC 0.78 still LOSES money). The label here is scalp PnL, NOT direction — keep it that way.
- Maximizing WR/AUC. High WR = the priced-in trap. Only $/tr-after-fee with CI>0 counts.
- Asset-confounded gates (all-BTC). The mix is reported and penalized.

## The knobs in `candidate.py`
- `features`: any of the groups `"indicators"` (37 TA: SAR, ADX, SuperTrend, ATR, Stoch, RSI, WILLR, OBV, CMF,
  EMV, StdDev, Keltner, BBands, MACD, CCI, EMA-stack, returns...), `"clob"` (22 CLOB-tape flow: trade
  imbalance, aggression, size, vwap, up-vs-dn flow, impact — pre & early windows), `"physics"`, `"entry"`.
  Or list individual feature names. `"path"`/`bid_*` are FORBIDDEN (they leak the label).
- `model`: `"xgb"` | `"rf"` | `"logit"`.
- `entry_filter`: `"broad"` | `"vwap055"` | `"d3vwap055"` | `"deployed"`.
- `exit_dt`: 30|45|60|75|90.
- `depth`,`n_est`,`C`.

## Ideas worth trying (operator backlog)
- CLOB-flow subsets only (does a specific flow feature select?), per-asset models, different exit_dt per cell,
  regression on reprice magnitude (extend fitness), interaction of CLOB imbalance × physics dist, the
  oracle-basis features (add via a new builder), momo/sniper fire universes (swap the fire file).
- New features: add a builder under `_data/`, extend `build_master_features.py`, re-run, then reference the
  new group/columns here.

## Data
`_data/master_features.parquet` (2533 fires × 105 cols), `_data/feature_groups.json`. Rebuild via
`build_indicator_panel.py` → `build_clob_flow.py` → `build_master_features.py`.

## Current state (seed)
Baseline `indicators+clob+physics+entry` on `vwap055` lifts only +$0.29/tr over all-take (within noise).
The biggest raw "lifts" (indicators_only, rf) are ASSET-CONFOUNDS (gate→all-BTC) and are penalized. CLOB-flow
ALONE does not select (negative lift). **Open problem: find a feature combination whose lift is real
(CI>0, mixed assets, beats all-take).** If none exists, the honest finding is that the scalp edge lives in
the entry filter + exit timing, not in slug-selection from these features.
