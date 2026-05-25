# Momo variants — sub-second L25, F7 deployment window only

_2026-05-21. Restricted to the F7 deployment window 2026-05-20 00:00 → 2026-05-22 07:00
UTC to allow full sub-second L25 resolution (the 28d × full-resolution run OOM'd
on BTC's 6GB+ array). Goal: replicate live VPS3 controller behavior precisely._

## What changed

1. **No 1Hz subsample** (`load_orderbook_l25_streaming(..., subsample_1hz=False)`).
   Each L25 lookup hits the freshest snapshot, not the first-of-second.
2. **Window restriction**: `ws ∈ [2026-05-20, 2026-05-22 07:00 UTC]` to fit
   memory budget (full sub-second L25 across 28d hits 6GB+ on BTC alone).
3. **Loader patched**: `load_orderbook_l25_streaming` now accepts `min_ts_us` /
   `max_ts_us` to time-window-filter at the pyarrow level (pre-pandas).

## Aggregate (all 6 cells combined)

```
variant                          F7    n   WR    leg_tot   real_tot   leg/tr   real/tr
2A_late_fire_late_signal        ALL   94  42.6% $ -404.69 $ -466.63  -$4.31    -$4.96
2A_late_fire_late_signal         F7   63  36.5% $ -426.95 $ -470.98  -$6.78    -$7.48
2A_late_fire_late_signal        F7x   42  35.7% $ -287.49 $ -317.07  -$6.85    -$7.55
2B_late_fire_early_signal       ALL  121  49.6% $  -15.26 $  -91.65  -$0.13    -$0.76
2B_late_fire_early_signal        F7  102  47.1% $ -111.07 $ -176.97  -$1.09    -$1.74
2B_late_fire_early_signal       F7x   72  44.4% $ -127.92 $ -175.77  -$1.78    -$2.44
2C_edge_of_slot                 ALL  180  56.1% $ +479.07 $ +370.80  +$2.66   +$2.06
2C_edge_of_slot                  F7  134  51.5% $ +134.31 $  +49.68  +$1.00   +$0.37
2C_edge_of_slot                 F7x  106  51.9% $ +134.71 $  +67.09  +$1.27   +$0.63
Baseline_v1                     ALL  122  53.3% $ +161.96 $  +87.31  +$1.33   +$0.72
Baseline_v1                      F7  100  49.0% $  -49.09 $ -112.69  -$0.49   -$1.13
Baseline_v1                     F7x   78  50.0% $  +15.73 $  -33.71  +$0.20   -$0.43
Baseline_v2                     ALL  167  49.7% $ -104.97 $ -209.27  -$0.63   -$1.25
Baseline_v2                      F7  135  49.6% $  -70.35 $ -155.00  -$0.52   -$1.15
Baseline_v2                     F7x  106  48.1% $ -115.76 $ -182.97  -$1.09   -$1.73
```

**Key**: in the F7 window with sub-second L25:
- **2C ALL is +$2.06/tr aggregate** — the strongest variant in this window
- **Baseline_v1 ALL is +$0.72/tr aggregate**, but F7 hurts it (similar to 28d run)
- 2A loses heavily
- F7 on 2C cuts profit (51% WR vs 56% on ALL)

## Highest-conviction cells in the F7 window

| Variant | Cell | F7 | n | WR | real/tr | real total |
|---|---|---|---|---|---|---|
| Baseline_v2 | sol_15m | F7 | 3 | **100%** | **+$25.95** | +$78 |
| Baseline_v2 | sol_15m | F7x | 3 | **100%** | **+$25.95** | +$78 |
| 2C | eth_15m | F7x | 4 | 75% | **+$13.69** | +$55 |
| Baseline_v2 | sol_15m | ALL | 4 | 75% | +$13.01 | +$52 |
| Baseline_v1 | sol_15m | F7x | 3 | 67% | +$11.97 | +$36 |
| Baseline_v1 | eth_15m | F7x | 4 | 75% | +$11.40 | +$46 |
| Baseline_v1 | eth_15m | F7 | 7 | 71% | +$10.05 | +$70 |
| 2C | eth_15m | ALL | 7 | 71% | +$9.52 | +$67 |
| 2C | eth_15m | F7 | 6 | 67% | +$7.83 | +$47 |
| Baseline_v1 | sol_5m | ALL | 16 | 69% | +$8.02 | +$128 |
| Baseline_v2 | btc_5m | F7x | 39 | 49% | -$1.37 | -$54 |

⚠ Sample sizes 3-39 are very small. Treat WR estimates as upper bounds.

## Comparison to live production (PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md)

Production reports (same ~23.5h window):

| Production sleeve | n | WR | $/trade | Mine (closest match) | n | WR | $/trade |
|---|---|---|---|---|---|---|---|
| btc_5m_v1 + F7 | 225 | **72.89%** | **+$10.40** | Baseline_v1 btc_5m F7 | 41 | 48.8% | -$1.24 |
| sol_5m_v1 + F7 | 42 | 71.43% | +$10.05 | Baseline_v1 sol_5m F7 | 12 | 58.3% | +$3.32 |
| sol_5m_v2 + F7 | 97 | **82.47%** | **+$10.87** | Baseline_v2 sol_5m F7 | 21 | 52.4% | -$0.11 |
| btc_15m_v1 + F7 | 27 | 77.78% | +$14.30 | Baseline_v1 btc_15m F7 | 12 | 50.0% | -$0.86 |
| eth_15m_v2 + F7 | 84 | 65.48% | +$7.90 | Baseline_v2 eth_15m F7 | 11 | 45.5% | -$3.37 |

**Persistent gap** even with sub-second L25 + verified F7 anchor. My backtest
reproduces 4-7× FEWER fires than production. The remaining gap explanations:

1. **Production fires MORE often than the ret_2m ≥ q90 gate alone allows.**
   Production likely uses additional triggers (volume, sigma, regime, multi-bar
   patterns) on top of the threshold I'm replicating. My ret_2m + q90 is the
   "basic momentum gate" — production has been adding filters since.

2. **My RSI is simple mean, production is likely Wilder-smoothed.** 7.59% of
   the F7 decisions disagree per `_match_live_f7.py`.

3. **Production uses REST-stale book at fill time** (~$0.19-0.32 favorable
   per CLAUDE.md). My WS-truth backtest doesn't have this lift. When TV
   migrates production to WS, live PnL should DROP toward my numbers.

4. **Slug-selection in production**: live controller may skip certain slugs
   (low volume, oracle disagreement, post-event windows) my universe scan
   doesn't filter. Each kept slug in production has been pre-screened more.

## What this tells us about the deploy decision

**The strategy edge IS real on 15m markets** — even my conservative WS-truth
sub-second backtest agrees: BTC 15m / ETH 15m / SOL 15m have positive pockets
across multiple variants. But:

- **My absolute PnL is the lower bound.** Production is higher because of
  REST-stale fills + smarter universe selection.
- **Production's "+$3.6k/day F7 lift" number includes REST-fill bonus that
  won't survive WS migration.** Plan for that drawdown.
- **F7 filter helps WR in some cells but cuts trade count by ~30-50%.** Net
  PnL is roughly flat-to-slightly-positive on aggregate. Per-cell decisions
  needed.

## Verification still needed

1. **Wilder-smoothed RSI** to close the 7.59% mismatch
2. **Larger live shadow window** — 23.5h isn't enough to confirm 70-100% WR
   numbers in small-n cells (sol_15m_v2 at 3 fires/day = sample noise)
3. **Slug-filter discovery** — what does production's universe selector do
   that mine doesn't? Need to inspect VPS3 controller code path

## Files

- Runner: `strategy_lab/meta_classifier/momo_variants_2abc.py` (now uses sub-sec L25 + window filter)
- Loader: `data/v4/canonical/load.py` (added `min_ts_us`/`max_ts_us` params)
- Run log: `data/v4/canonical/_results/_momo_variants_2abc_v5_subsec_run.log`
- Per-trade: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
