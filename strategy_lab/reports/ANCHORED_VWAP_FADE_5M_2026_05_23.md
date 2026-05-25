# Anchored 15m VWAP fade — 5m markets (2026-05-23 03:10 UTC)

NEW STRATEGY — independent of momo. Fire when binance has deviated significantly from the start-of-15m-bucket anchored VWAP; bet on mean reversion to VWAP. Multiple fire offsets within the 5m slot, multiple deviation thresholds.

**SIMPLIFIED**: this first-pass uses outcome-only WR (no L25 fill replay). $/trade not computed; use WR + n only.

## Deployable configs (n>=30, WR>=60%)

**NONE** — no anchored-VWAP-fade configuration hit 60% WR with n>=30 on this 28d sample.

## All cells × thresholds (n>=30)

| asset   |   fire_offset_s |   thr_bps | direction             |   n |        wr |   wr_pct |
|:--------|----------------:|----------:|:----------------------|----:|----------:|---------:|
| SOL     |              60 |        30 | bet_DOWN_after_UP_ext |  31 | 0.225806  |    22.58 |
| SOL     |              90 |        30 | bet_DOWN_after_UP_ext |  35 | 0.171429  |    17.14 |
| SOL     |             120 |        30 | bet_DOWN_after_UP_ext |  37 | 0.135135  |    13.51 |
| SOL     |             150 |        30 | bet_DOWN_after_UP_ext |  37 | 0.0810811 |     8.11 |
| SOL     |             180 |        30 | bet_DOWN_after_UP_ext |  39 | 0.0769231 |     7.69 |

## Method note
- VWAP = cum_sum(close·vol) / cum_sum(vol) within each 15m UTC bucket (anchored at bucket start).
- dev_bps = 10000 · log(close_now / vwap_15m). Positive = price above VWAP.
- Fade rule: if dev_bps > thr → BET DOWN; if < -thr → BET UP.
- 6 fire offsets × 5 thresholds × 2 directions × 3 assets = candidate space.
- Win condition: outcome matches the bet direction at slot close.

_data: `data/v4/canonical/_results/anchored_vwap_fade_5m.csv`_
_script: `strategy_lab/meta_classifier/anchored_vwap_fade_5m.py`_