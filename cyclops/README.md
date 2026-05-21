# Cyclops Clone

Greenfield 3-axis (Trend / Levels / Momentum) + conflict-filter strategy for Polymarket BTC binary 5m markets.

**Spec:** `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md`
**Architectural source:** `strategy_lab/reports/CYCLOPS_ARCHITECTURE_DEEP_DIVE_2026_05_16.md` §§19-22

## What this is

A clean-room copy of Gustafssonkotte's Cyclops architecture: ask three independent yes/no questions per market, hard-skip when they disagree, fire when they coherently agree. No averaging, no weighted voter, no tier table, no "fair probability" lookup, no Kelly-with-edge — those are exactly what Cyclops deleted on May 11.

## Phase status

| Phase | Status |
|---|---|
| P0 — Skeleton + conventions + ws_s test | done (19 tests) |
| P1 — Three axes (no filter) | done (16 tests) |
| P2 — Conflict filter | done (38 tests) |
| P2 — Backtest runner + first PnL | done — raw 3-axis: G1 FAIL (-$2.06/tr) |
| P3 — Vwap guard + momentum-hard-filter | done — G1 PASS (+$1.50/tr) |
| P3 — Hours/reentry/blowoff guards | done (19 tests). ob_manipulation deferred |
| P4 — Risk manager | done (9 tests). Wired; never trips at $10k bankroll |
| P5 — Validation battery | done (7 tests). G3 PASS (p=0.022); G4 FAIL (small n) |
| P6 — Decision: ship or stop | open |

The package lives at the project root as `cyclops/` (not nested under
`strategy_lab/`) — it's a greenfield side-project.

## Quick start

```bash
# Step 0 — Verify environment (REQUIRED before any backtest)
py -3 -X utf8 data/v4/canonical/_test_ws_s.py
# Must print: === ALL CHECKS PASSED ===

# Run cyclops tests
py -3 -X utf8 -m pytest cyclops/tests/ -v
```

## Layout

```
cyclops/
├── conventions.py         constants + paths (single source of truth)
├── data_io.py             thin wrappers over data/v4/canonical/load.py
├── axes/                  trend.py / levels.py / momentum.py
├── filters/               conflict.py + 4 pre-flight guards
├── sizing/                fixed.py (Phase 1), confidence_scaled.py (Phase 2)
├── risk/                  drawdown_manager.py
├── backtest/              runner.py
├── validate/              permutation / walkforward / bootstrap
├── telemetry/             event schema
└── tests/                 pytest tests
```

## Critical conventions (inherited from CLAUDE.md)

1. UTC microseconds for all `*_us` timestamps; never localize
2. `ws_s = slug_suffix - window_s` (the PREVIOUS slot's start, NOT the slug suffix)
3. Chainlink for outcomes, binance for signals
4. `asof_strict` for causal lookups
5. L25 walk via `book_walk_fill(ask_p, ask_s, $25)` is the production fill model
6. Fee = 2% on profit only (winning leg) — legacy shortcut, Phase 1

## Kill criteria

- P2 G1 fails (mean PnL ≤ 0 on 21d BTC 5m) → **STOP**, do not iterate
- P5 G3 fails (perm p > 0.10) → **STOP**, not statistically distinguishable
- Fire rate < 3% even after threshold relaxation → strategy doesn't fit universe

The whole point is to NOT iterate complexity. If the simple version fails, stop.
