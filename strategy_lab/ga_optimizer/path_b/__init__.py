"""
Path B: GA learns filter rules on PRODUCTION-FIRED events.

Universe = the ~13,601 live fires in trading_events_30d.
Each fire has: sleeve_id, signal, outcome, entry_price, pnl, timestamp.
Each individual = action map keyed by (sleeve_family, signal, hour_bucket, dow_group).
Action ∈ {KEEP, INVERT, SKIP}.

Why this avoids overfit:
  - Training data IS what production actually fired (no backtest simulation).
  - INVERT economics computed against the SAME-side entry_price (approximation
    1 - entry_price + spread, conservative).
  - Fitness = actual PnL achievable by applying actions to the production fire-set.
  - Time-split held-out (last 5 days) replicates real deploy conditions.
"""
