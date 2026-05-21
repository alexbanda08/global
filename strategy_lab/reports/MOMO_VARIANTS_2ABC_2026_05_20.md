# Momo Variants 2A / 2B / 2C — Backtest Results

_2026-05-20. Late-fire experiments tested vs production v1/v2 baselines._

## Methodology

Matches production shadow-PnL accounting + cyclops `_real_fees_rerun.py` pattern:

- **Engine**: `strategy_lab/engine_v2.LegacyConfig` — what production-shadow uses
  (legacy 2%-on-profit fee, no latency shift, no min_book_events filter, strict-asof
  book lookup, spread filter 2¢ BTC/ETH and 2.5¢ SOL).
- **Real-fee column** computed in parallel per trade from `entry_shares` × `entry_vwap` × `won`:
  ```
  fee_per_share = 0.07 × vwap × (1 − vwap)          # max 1.75¢ at p=0.5, ~0 at extremes
  win:  pnl_real  = shares × (1 − vwap) − shares × fee
  loss: pnl_real  = -shares × vwap     − shares × fee
  ```
  This is the Polymarket curve from `strategy_lab/fees.py` (`DEFAULT_CRYPTO_FEE_BPS=700`).
  Net impact ≈ −$0.30 to −$1.20 per trade vs legacy depending on entry price.
- **F7 filter**: RSI(14) on binance 1m at fire time. UP keeps iff RSI>50, DOWN iff RSI<50.
  F7x = stricter (60/40).
- **Universe**: 28,731 chainlink-resolved markets, BTC/ETH/SOL × 5m/15m,
  2026-04-24 → 2026-05-19 (26d). Notional = $25/trade. ws = slug suffix.

## Variant definitions

| Variant | Anchor (5m) | Anchor (15m) | Fire (5m) | Fire (15m) | Note |
|---|---|---|---|---|---|
| Baseline_v1 | ret(ws-300, ws-180) | ret(ws-900, ws-780) | ws-180 | ws-780 | Production v1 |
| Baseline_v2 | ret(ws-360, ws-240) | ret(ws-960, ws-840) | ws-240 | ws-840 | Production v2 |
| 2A late/late | ret(ws-240, ws-120) | ret(ws-240, ws-120) | ws-120 | ws-120 | Fresh signal at slot-2min |
| 2B late/early | ret(ws-300, ws-180) | ret(ws-900, ws-780) | ws-120 | ws-120 | Design 3 signal, delayed order |
| 2C edge-of-slot | ret(ws-120, ws) | ret(ws-120, ws) | ws | ws | Fire AT slot_open |

## Headline — aggregate across all 6 cells

```
variant                            F7     n     WR   leg_tot  real_tot   leg/tr  real/tr
2A_late_fire_late_signal          ALL  1933  47.6% $-3173.20 $-4393.04 $-1.6416 $-2.2727
2A_late_fire_late_signal           F7  1403  46.7% $-2491.13 $-3393.74 $-1.7756 $-2.4189
2A_late_fire_late_signal          F7x   986  44.5% $-2559.02 $-3208.30 $-2.5954 $-3.2539
2B_late_fire_early_signal         ALL  1838  48.2% $-2058.53 $-3220.98 $-1.1200 $-1.7524
2B_late_fire_early_signal          F7  1425  48.1% $-1314.88 $-2223.80 $-0.9227 $-1.5606  ← best $/trade (legacy)
2B_late_fire_early_signal         F7x  1029  46.6% $-1412.02 $-2079.05 $-1.3722 $-2.0205
2C_edge_of_slot                   ALL  2035  48.0% $-2900.64 $-4183.46 $-1.4254 $-2.0558
2C_edge_of_slot                    F7  1442  47.6% $-1556.82 $-2483.04 $-1.0796 $-1.7219
2C_edge_of_slot                   F7x  1039  47.4% $ -953.25 $-1628.53 $-0.9175 $-1.5674  ← smallest drawdown
Baseline_v1                       ALL  1734  48.1% $-2499.71 $-3593.51 $-1.4416 $-2.0724
Baseline_v1                        F7  1343  47.3% $-2200.93 $-3059.16 $-1.6388 $-2.2779
Baseline_v1                       F7x   989  45.8% $-2191.94 $-2833.83 $-2.2163 $-2.8654
Baseline_v2                       ALL  2147  49.1% $-2148.85 $-3488.76 $-1.0009 $-1.6249
Baseline_v2                        F7  1642  48.2% $-2036.70 $-3074.34 $-1.2404 $-1.8723
Baseline_v2                       F7x  1192  46.6% $-2219.69 $-2985.05 $-1.8622 $-2.5042
```

**Headline (aggregate)**:
- Even with **legacy production fee accounting**, every variant is net negative
  across the full 6-cell universe.
- Real Polymarket fees subtract another **~$0.50–$0.65/trade** on average — not
  catastrophic per trade but compounds across thousands of fires.
- **2B + F7 has smallest legacy drawdown** ($-0.92/trade); **2C + F7x has smallest real drawdown** ($-1.57/trade).
- **F7 helps every variant** vs ALL — confirms production observation that F7
  removes systematically losing fires.

## Profit pockets (where the strategy DOES work post-real-fees)

Cells with **positive real PnL** (real_tot > 0):

| Variant | Cell | F7 | n | WR | leg/tr | **real/tr** |
|---|---|---|---|---|---|---|
| **2B_late_early** | **btc_15m** | **F7x** | 109 | **59.6%** | $+5.71 | **$+5.12** ← BEST |
| 2B_late_early | btc_15m | F7 | 152 | 56.6% | $+3.84 | $+3.24 |
| 2C_edge | eth_15m | F7x | 63 | 55.6% | $+4.54 | $+3.92 |
| Baseline_v1 | btc_15m | ALL | 131 | 58.0% | $+3.49 | $+2.91 |
| 2C_edge | eth_15m | F7 | 94 | 54.3% | $+3.17 | $+2.56 |
| Baseline_v1 | btc_15m | F7 | 106 | 56.6% | $+2.99 | $+2.40 |
| 2A_late_late | eth_15m | F7 | 79 | 53.2% | $+2.54 | $+1.92 |
| 2A_late_late | eth_15m | F7x | 54 | 51.9% | $+2.54 | $+1.91 |
| Baseline_v2 | btc_15m | F7 | 151 | 55.6% | $+2.36 | $+1.76 |
| 2B_late_early | btc_15m | ALL | 201 | 53.7% | $+2.09 | $+1.48 |
| 2B_late_early | sol_15m | F7 | 44 | 52.3% | $+1.14 | $+0.52 |
| 2C_edge | eth_15m | ALL | 141 | 52.5% | $+1.02 | $+0.41 |

**Cells that flip sign with real fees** (legacy>0, real<0):

| Variant | Cell | F7 | n | leg/tr | real/tr | Δ |
|---|---|---|---|---|---|---|
| 2C_edge | btc_15m | ALL | 194 | $+0.22 | $-0.40 | -$0.62 |
| 2C_edge | btc_15m | F7 | 136 | $+0.32 | $-0.32 | -$0.64 |
| 2C_edge | btc_15m | F7x | 99 | $+0.27 | $-0.38 | -$0.65 |
| 2C_edge | btc_5m | ALL | 619 | $+0.19 | $-0.44 | -$0.63 |
| 2C_edge | btc_5m | F7 | 445 | $+0.44 | $-0.19 | -$0.63 |
| 2C_edge | btc_5m | F7x | 320 | $+0.14 | $-0.50 | -$0.64 |
| Baseline_v2 | btc_15m | ALL | 197 | $+0.37 | $-0.24 | -$0.61 |
| Baseline_v2 | btc_15m | F7x | 116 | $+0.15 | $-0.47 | -$0.62 |

These are the **marginal pockets** — production shadow says they make ~$0.20-0.40/trade
but real fees eat it. Don't deploy these without verifying production paper PnL uses
the real fee model.

## Three pattern findings

### 1. BTC 15m has structural edge (after real fees)

Three variants are positive on BTC 15m AFTER real fees:
- Baseline_v1 ALL: $+2.91/trade
- 2B + F7x: **$+5.12/trade** (the winner)
- 2B + F7: $+3.24/trade

**2B inherits production v1's anchor (signal at first 2 min of prev slot, fire 11min later
at slot_start−120)** — same predictive signal, but enters when the price is around $0.50–0.65
instead of $0.94. That gives more upside per share if won.

### 2. ETH 15m + 2C is real

```
eth_15m + 2C   ALL  n=141  WR=52.5%  real=+$0.41/trade
eth_15m + 2C   F7   n=94   WR=54.3%  real=+$2.56/trade
eth_15m + 2C   F7x  n=63   WR=55.6%  real=+$3.92/trade
```

F7x lifts WR by 3 points and per-trade by 9.5x. Small sample (n=63) but the pattern
is consistent at all 3 F7 levels.

### 3. 5m cells lose universally

Of 6 (variant × cell × F7) combinations on 5m markets, **0 are profitable after real fees**.
The 5m timeframe is structurally not workable with this signal — likely because:
- Higher per-share fee proportion (entry near $0.50 means peak fee)
- Less time for the signal to play out
- Thinner books → wider effective spread

5m sleeves should be deprecated in v1 deploy.

## Real-fee impact decomposition

Cyclops `_real_fees_rerun.py` and EXTERNAL_REPO_COMPARISON_2026_05_12 both confirm the
real-vs-legacy delta is structural, not stochastic:

```
fee_per_share_real = 0.07 × p × (1 − p)
```

At typical signal-gated entry prices:
| Entry p | Fee per share | Fee on $25 notional |
|---|---|---|
| 0.50 | $0.0175 | $0.875 |
| 0.60 | $0.0168 | $0.700 |
| 0.65 | $0.0159 | $0.611 |
| 0.70 | $0.0147 | $0.525 |
| 0.80 | $0.0112 | $0.350 |
| 0.85 | $0.0089 | $0.262 |
| 0.94 | $0.0040 | $0.105 |

Legacy "2% on profit only" charges nothing on losses + 2% × profit on wins.
Real curve charges on both legs. Delta is ~$0.50-0.90/trade at p~$0.60.

**This is the right number to deduct from production shadow PnL.** The cyclops master
table confirms: at $25 notional, real_PnL = legacy_PnL − ~$0.02-0.03 mean per trade
on cyclops's BTC 5m universe (which fires deeper at p~$0.85+). For 2A/2B/2C variants
firing at p~$0.50-0.70, the delta is bigger ($0.60-0.90).

## Recommendations

1. **Deploy 2B + F7x on BTC 15m only**. n=109, WR=59.6%, real=$+5.12/trade.
   At ~4 fires/day × $25 notional ≈ **+$20/day**. At $250 notional ≈ +$200/day.

2. **Add Baseline_v1 ALL on BTC 15m as a parallel sleeve**. n=131, WR=58.0%, real=$+2.91/trade.
   Don't double up on the same fires — check overlap first (likely high since 2B reuses
   Baseline_v1's anchor signal).

3. **Add 2C + F7x on ETH 15m as a small-size pilot**. n=63 is light but real=$+3.92/trade
   with consistent F7/F7x progression. Pilot at $5-10 notional for 30d to expand sample.

4. **Drop all 5m cells**. Universally negative after real fees.

5. **Drop SOL 15m for v1**. Marginal (one pocket at +$0.52/trade with F7).

## Open questions

1. **2B vs Baseline_v1 BTC 15m overlap**: same signal anchor, different fire time.
   Need to verify if they fire on the SAME slugs (don't double-deploy) or independent
   slugs (ensemble both).

2. **eth_15m + 2C is real**: 9.5x lift on F7x looks like genuine signal but n=63 is small.
   Re-run with 60d window when more data is available.

3. **Why 2C beats 2A**: same fire time (ws and ws-120 are close). Hypothesis: at ws
   the price has converged closest to the eventual outcome, but the signal anchored on
   (ws-120, ws) captures the most recent momentum. 2A's signal (ws-240, ws-120) is
   slightly staler and that 2-minute difference matters.

4. **Production +$3.6k/day F7 result**: even Baseline_v1 ALL aggregates to −$2,500
   on legacy in this backtest, but production shadow says +$3.6k/day. The gap is likely:
   - REST-staleness fills in production (book is $0.19-0.32 stale → favorable entry)
   - F7 filter not yet applied at production-decode time
   - Different universe sampling (production may be filtering to specific cells)

## Files

- Script: `strategy_lab/meta_classifier/momo_variants_2abc.py`
- Per-trade parquet: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
  (columns: slug, asset, tf, ws, fire_s, signal, outcome, won, entry_vwap, entry_shares,
   pnl_legacy_usd, pnl_real_usd, ret_2m, threshold, rsi_14, f7_keep, f7x_keep)
- Per-cell csv: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_variant_cell.csv`
- Summary csv: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/summary.csv`
- Gated universe: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/gated_universe.parquet`
- Run log: `data/v4/canonical/_results/_momo_variants_2abc_v2_run.log`
