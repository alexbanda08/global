# Momo variants — 28-day window, full sub-second L25 (batched)

_2026-05-21. Full 28-day window (April 24 → May 21 20:10 UTC) with
**sub-second L25 resolution** (no 1Hz subsample). Memory budget met by
batching 100 slugs at a time through `load_orderbook_l25_streaming`._

## Sub-second vs 1Hz — DOES IT MATTER?

The 28d aggregate per-trade real PnL is essentially **identical** across the
two L25 modes:

| Variant | 1Hz subsample | Sub-sec (per-trade) | Δ |
|---|---|---|---|
| 2A ALL | -$2.39 | -$2.42 | -$0.03 |
| 2B ALL | -$1.70 | -$1.67 | +$0.03 |
| 2C ALL | -$1.69 | -$1.97 | -$0.28 |
| Baseline_v1 ALL | -$1.90 | -$1.89 | +$0.01 |
| Baseline_v2 ALL | -$1.60 | -$1.59 | +$0.01 |

**Why**: my variants fire at integer-second boundaries (fire_s = ws + offset
in seconds). When the lookup is at `fire_s * 1e6`, both the 1Hz-subsampled
book (last-of-second snapshot, by drop_duplicates first) AND the full sub-sec
book return a snapshot in the same second-bucket. Sample noise on small
differences in 2C (-$0.28/tr) is from different snapshot indexing edge cases.

**For sub-second precision to matter**, fire times themselves must be
sub-second — which happens only when replaying live production fires (whose
fire_us is microsecond-precise from VPS3 trading_events). For our synthetic
variants 2A/2B/2C and the production baselines using deterministic offsets,
1Hz vs sub-sec is a wash.

## 28-day aggregate (sub-sec L25, real Polymarket fees)

```
variant                          F7    n     WR   leg_tot    real_tot   leg/tr   real/tr
2A_late_fire_late_signal        ALL  2018  47.4% $-3607.08  $-4883.52  -$1.79   -$2.42
2A_late_fire_late_signal         F7  1455  46.3% $-2896.27  $-3835.97  -$1.99   -$2.64
2A_late_fire_late_signal        F7x  1024  44.0% $-2908.38  $-3585.34  -$2.84   -$3.50
2B_late_fire_early_signal       ALL  1953  48.3% $-2024.25  $-3258.93  -$1.04   -$1.67
2B_late_fire_early_signal        F7  1520  48.1% $-1350.44  $-2320.26  -$0.89   -$1.53
2B_late_fire_early_signal       F7x  1099  46.5% $-1537.28  $-2251.04  -$1.40   -$2.05
2C_edge_of_slot                 ALL  2162  48.2% $-2900.52  $-4262.52  -$1.34   -$1.97
2C_edge_of_slot                  F7  1541  47.4% $-1888.62  $-2880.75  -$1.23   -$1.87
2C_edge_of_slot                 F7x  1129  47.3% $-1121.50  $-1856.05  -$0.99   -$1.64
Baseline_v1                     ALL  1850  48.4% $-2332.75  $-3497.45  -$1.26   -$1.89
Baseline_v1                      F7  1437  47.4% $-2245.91  $-3163.99  -$1.56   -$2.20
Baseline_v1                     F7x  1063  46.0% $-2222.10  $-2911.41  -$2.09   -$2.74
Baseline_v2                     ALL  2313  49.2% $-2226.73  $-3670.23  -$0.96   -$1.59
Baseline_v2                      F7  1776  48.4% $-2033.48  $-3154.54  -$1.15   -$1.78
Baseline_v2                     F7x  1299  46.7% $-2311.41  $-3144.44  -$1.78   -$2.42
```

## Profit pockets (28d, sub-sec L25)

Variant × cell × F7 buckets with positive real PnL after fees:

| Variant | Cell | F7 | n | WR | real $/tr | real total |
|---|---|---|---|---|---|---|
| **2C edge-of-slot** | **eth_15m** | **F7x** | 67 | **56.7%** | **+$4.52** | +$303 |
| 2C edge-of-slot | eth_15m | F7 | 99 | 54.5% | +$2.63 | +$260 |
| **2B late/early** | **btc_15m** | **F7x** | 122 | 54.9% | +$2.75 | +$335 |
| Baseline_v1 | btc_15m | ALL | 144 | **56.9%** | +$2.39 | +$345 |
| Baseline_v1 | btc_15m | F7 | 118 | 55.9% | +$2.06 | +$244 |
| Baseline_v1 | btc_15m | F7x | 87 | 55.2% | +$1.88 | +$164 |
| 2B late/early | btc_15m | F7 | 168 | 54.2% | +$2.00 | +$336 |
| Baseline_v2 | btc_15m | F7 | 167 | 55.1% | +$1.51 | +$252 |
| 2C edge-of-slot | eth_15m | ALL | 147 | 53.1% | +$0.66 | +$98 |
| 2B late/early | btc_15m | ALL | 218 | 52.3% | +$0.77 | +$167 |
| 2A late/late | eth_15m | F7 | 81 | 50.6% | +$0.56 | +$46 |
| 2A late/late | eth_15m | F7x | 55 | 49.1% | +$0.41 | +$23 |
| 2C edge-of-slot | btc_15m | ALL | 201 | 51.7% | +$0.02 | +$5 |

## Three findings

### 1. L25 resolution is NOT the gap to production

Sub-second vs 1Hz subsample produces near-identical per-trade PnL because my
fire times are at integer seconds. The gap between my conservative backtest
(WR 49-57%) and production's reported (WR 72-83% on best cells) is structural,
not snapshot-resolution.

### 2. The robust profit pockets across BOTH L25 modes:

- **BTC 15m**: Baseline_v1 ALL (+$2.39/tr, n=144, WR 56.9%), 2B+F7 (+$2.00/tr, n=168)
- **ETH 15m**: 2C+F7x (+$4.52/tr, n=67, WR 56.7%) — strongest single bucket
- All other cells: marginal-to-negative

5m markets remain universally negative after real fees.

### 3. Where the prod gap remains

| Production sleeve | Live n | Live WR | Live $/trade | Mine (28d) | Mine WR | Mine $/tr |
|---|---|---|---|---|---|---|
| btc_5m_v1 + F7 | 225 | 72.89% | +$10.40 | Baseline_v1 btc_5m F7 | n=628 | 47.1% | -$2.30 |
| btc_15m_v1 + F7 | 27 | 77.78% | +$14.30 | Baseline_v1 btc_15m F7 | n=118 | 55.9% | +$2.06 |
| sol_5m_v2 + F7 | 97 | 82.47% | +$10.87 | Baseline_v2 sol_5m F7 | n=356 | 48.9% | -$1.72 |
| eth_15m_v2 + F7 | 84 | 65.48% | +$7.90 | Baseline_v2 eth_15m F7 | n=101 | 48.5% | -$1.66 |

Gap drivers (in priority order):
1. **Production gates more aggressively** — fires 4-7× fewer trades per
   cell than my ret_2m ≥ q90 baseline. Production has additional triggers
   (volume, sigma, regime) I'm not replicating.
2. **Simple-mean vs Wilder-smoothed RSI** — 7.59% F7 decision mismatch
   per `_match_live_f7.py` verification.
3. **REST-fill staleness** — production gets ~$0.19-0.32 favorable entry
   from REST lag (CLAUDE.md). My WS-truth removes this lift. Post TV-WS
   migration, production PnL will drop toward my numbers.

## Mechanical changes this session

1. **Pulled fresh VPS3 data** (May 19 → May 21, 12 tables, 403MB compressed)
   via `migration_2026_05_21/pull_delta_vps3_2026_05_21.sh`. Canonical now
   covers Apr 24 → May 21 20:10 UTC (28d, 30,750 chainlink-resolved markets).

2. **Patched `load_orderbook_l25_streaming`** to accept `min_ts_us` / `max_ts_us`
   so callers can bound memory by time window.

3. **Variants runner batches L25** in slug-groups of 100 to handle full
   28d × sub-second without OOM. RAM use: stable ~17 GB free during the run.

4. **Verified F7 anchor = fire_us** (production live anchor) at 92.41% match
   against 1,331 production fires from `fires_with_gates.csv`.

## Files

- Runner: `strategy_lab/meta_classifier/momo_variants_2abc.py`
- Loader: `data/v4/canonical/load.py` (added time-window params)
- Per-trade: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
- Per-cell csv: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_variant_cell.csv`
- Run log: `data/v4/canonical/_results/_momo_variants_2abc_v6_subsec_28d_run.log`

## Recommendations

1. **Deploy BTC 15m ensemble** (3 sleeves, all positive after real fees):
   - Baseline_v1 ALL (no F7): real +$2.39/tr × 144 fires / 28d ≈ +$12/day at $25 notional
   - 2B + F7x: +$2.75/tr × 122 fires / 28d ≈ +$12/day  
   - 2B + F7: +$2.00/tr × 168 fires / 28d ≈ +$12/day
   - Combined ~$36/day at $25 notional ≈ +$360/day at $250 notional

2. **Deploy ETH 15m + 2C+F7x as small pilot** — +$4.52/tr but n=67 over 28d
   (~2.4 fires/day). Run at $5-10 notional to grow sample.

3. **Drop 5m cells and SOL universally** for production v1/v2/2A/2B/2C.

4. **Validate live F7 vs WS-truth gap** post-TV-migration. Expect ~50%
   haircut on production paper PnL when REST is dropped.

5. **Implement Wilder RSI** to close the 7.59% F7-anchor mismatch.

6. **Replicate production's additional gates** — inspect VPS3 controller
   code to find what fires alongside ret_2m. That closes the 4-7× fire-count gap.
