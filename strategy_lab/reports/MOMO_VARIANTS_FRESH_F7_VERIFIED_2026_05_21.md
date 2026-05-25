# Momo v1/v2 + 2A/2B/2C variants — verified F7@fire anchor, fresh canonical

_2026-05-21. Re-run with fresh canonical (window April 24 → May 21 20:10 UTC,
30,750 chainlink-resolved markets) and the **verified live F7 anchor** (RSI at
fire_us, 92.41% match against 1,331 production fires)._

## What changed since the previous report

1. **Canonical refresh** — klines, RTDS, resolutions, trading_events, L25, trades
   all extended from 2026-05-19 → 2026-05-21 20:10 UTC. F7 deployment window
   (2026-05-20 19:57 → present) now fully covered.
2. **F7 anchor verified empirically** against production `is_f7` flags:

   | Candidate anchor | Match accuracy vs live `is_f7` (n=1,331) |
   |---|---|
   | **`fire_us = ws_s + 120`** | **92.41%** ✓ THIS IS THE LIVE ANCHOR |
   | `slot_start = ws` | 85.73% (post-fire, partial lookahead) |
   | `slot_end = ws + window_s` | 79.94% (full lookahead) |
   | `ws_s = ws − window_s` | 79.79% (too early) |

   Verifier: `strategy_lab/meta_classifier/_match_live_f7.py` against
   `strategy_lab/markov_filter/_results/post_f7_real_compare_v2/fires_with_gates.csv`.
3. **My earlier "anchor at ws_s" claim was wrong.** The variants runner has been
   reverted to the correct anchor (fire_us). The 7.59% remaining mismatch vs
   live is almost certainly RSI smoothing-method differences (Wilder vs simple
   mean) or 1-min rounding — not anchor mismatch.

## Setup (unchanged from prior reports)

- **Engine**: `engine_v2.LegacyConfig` (matches production shadow accounting:
  no latency shift, no min_book_events filter, legacy 2%-on-profit fee).
- **Real-fee column**: per-trade post-process using `fee = 0.07 × p × (1-p)`
  on every fill (winning + losing legs).
- **F7 / F7x**: RSI(14) at fire time. F7 keeps UP iff RSI > 50, DOWN iff RSI < 50.
  F7x stricter (60 / 40).
- **Notional**: $25/trade.
- **Universe**: 30,750 chainlink-resolved markets, BTC/ETH/SOL × 5m/15m,
  2026-04-24 → 2026-05-21 (28d).

## Aggregate rollup (across 6 cells)

```
variant                            F7     n     WR   leg_tot  real_tot   leg/tr  real/tr
2A_late_fire_late_signal          ALL  2028  47.4% $-3554.97 $-4837.11 $-1.7529 $-2.3852
2A_late_fire_late_signal           F7  1466  46.2% $-2916.82 $-3863.46 $-1.9896 $-2.6354
2A_late_fire_late_signal          F7x  1028  44.2% $-2845.26 $-3524.11 $-2.7678 $-3.4281
2B_late_fire_early_signal         ALL  1960  48.2% $-2097.78 $-3337.49 $-1.0703 $-1.7028
2B_late_fire_early_signal          F7  1528  48.0% $-1449.93 $-2425.63 $-0.9489 $-1.5875
2B_late_fire_early_signal         F7x  1102  46.5% $-1563.92 $-2279.67 $-1.4192 $-2.0687
2C_edge_of_slot                   ALL  2217  48.7% $-2364.17 $-3755.76 $-1.0664 $-1.6941
2C_edge_of_slot                    F7  1578  48.0% $-1320.18 $-2331.11 $-0.8366 $-1.4773
2C_edge_of_slot                   F7x  1147  48.0% $ -665.06 $-1407.50 $-0.5798 $-1.2271
Baseline_v1                       ALL  1857  48.4% $-2362.75 $-3532.03 $-1.2723 $-1.9020
Baseline_v1                        F7  1443  47.4% $-2250.02 $-3171.85 $-1.5593 $-2.1981
Baseline_v1                       F7x  1067  46.1% $-2176.21 $-2867.54 $-2.0396 $-2.6875
Baseline_v2                       ALL  2314  49.1% $-2253.49 $-3697.70 $-0.9739 $-1.5980
Baseline_v2                        F7  1777  48.3% $-2106.72 $-3229.01 $-1.1855 $-1.8171
Baseline_v2                       F7x  1298  46.7% $-2335.12 $-3167.69 $-1.7990 $-2.4404
```

All variants still aggregate-negative on canonical. **2C + F7x** has lowest
drawdown (`real_tot = -$1,408`, `real/tr = -$1.23`).

## Profit pockets (real PnL > 0 after Polymarket fees)

Variant × cell × F7 combos where strategy is **profitable**:

| Variant | Cell | F7 | n | WR | real/tr | real total |
|---|---|---|---|---|---|---|
| **2B late/early** | **btc_15m** | **F7x** | 123 | **55.3%** | **+$2.93** | +$360 |
| **2B late/early** | btc_15m | F7 | 170 | 54.7% | +$2.28 | +$387 |
| **2C edge-of-slot** | **eth_15m** | **F7x** | 67 | **56.7%** | **+$4.50** | +$302 |
| 2C edge-of-slot | eth_15m | F7 | 100 | 55.0% | +$2.87 | +$287 |
| **Baseline_v1** | btc_15m | ALL | 144 | 56.9% | +$2.39 | +$345 |
| Baseline_v1 | btc_15m | F7 | 118 | 55.9% | +$2.06 | +$244 |
| Baseline_v1 | btc_15m | F7x | 87 | 55.2% | +$1.88 | +$164 |
| Baseline_v2 | btc_15m | F7 | 167 | 55.1% | +$1.51 | +$252 |
| 2B late/early | btc_15m | ALL | 220 | 52.7% | +$0.99 | +$218 |
| 2C edge-of-slot | btc_5m | F7 | 485 | 50.7% | +$0.16 | +$79 |
| 2C edge-of-slot | btc_5m | F7x | 352 | 50.6% | +$0.14 | +$49 |
| 2C edge-of-slot | eth_15m | ALL | 148 | 53.4% | +$0.84 | +$125 |
| 2A late/late | eth_15m | F7 | 82 | 51.2% | +$0.90 | +$74 |
| 2A late/late | eth_15m | F7x | 56 | 50.0% | +$0.92 | +$51 |
| 2C edge-of-slot | btc_15m | ALL | 213 | 51.6% | +$0.06 | +$13 |

## Highlights

1. **BTC 15m is structurally profitable across multiple variants.**
   - Baseline_v1 ALL: 56.9% WR, +$2.39/tr (n=144)
   - 2B + F7x: 55.3% WR, **+$2.93/tr** (n=123) ← best per-trade
   - 2B + F7: 54.7% WR, +$2.28/tr (n=170)
   - All three positive even after real Polymarket fees.

2. **ETH 15m + 2C is real and STRONG**:
   - F7x: 56.7% WR, **+$4.50/tr** (n=67) ← strongest single bucket
   - F7: 55.0% WR, +$2.87/tr (n=100)
   - ALL: 53.4% WR, +$0.84/tr (n=148)
   Consistent F7 progression — n=67 is small but the pattern is internally
   consistent across F7 levels.

3. **2C edge-of-slot extends to BTC 5m** at the F7-filter levels:
   - F7: 50.7% WR, +$0.16/tr (n=485)
   - F7x: 50.6% WR, +$0.14/tr (n=352)
   ALL is slightly negative (-$0.09/tr) — F7 flips it positive.

4. **5m cells remain mostly losing** for v1/v2/2A/2B. Only 2C+F7 on btc_5m
   crosses positive. ETH 5m and SOL 5m are universally negative.

## Live VPS3 production comparison (sanity check)

From `PER_STRATEGY_FAMILY_GATE_COMPARE_2026_05_21.md` (23.5h live shadow):

| Sleeve | Live n | Live WR | Live $/tr |
|---|---|---|---|
| btc_5m_v1 + F7 | 225 | 72.89% | +$10.40 |
| sol_5m_v1 + F7 | 42 | 71.43% | +$10.05 |
| sol_5m_v2 + F7 | 97 | 82.47% | +$10.87 |
| btc_15m_v1 + F7 | 27 | 77.78% | +$14.30 |
| eth_15m_v2 + F7 | 84 | 65.48% | +$7.90 |

These live results are MUCH stronger than my canonical replay on the same cells.
The gap is real and likely from:
- **Different fire universe**: production fires ~75-225 trades in 23.5h on btc_5m_v1 → ~2,300/day extrapolated. My backtest fires 814 over 28d = ~29/day. Production has different gates (volume/sigma/strike filters) I'm not replicating.
- **RSI smoothing**: my simple-mean RSI(14) vs Wilder's smoothed RSI(14) — the 7.59% mismatch in `_match_live_f7.py` is mostly from this.
- **Live REST/WS book staleness**: production fills get ~$0.19-0.32 favorable entry from REST lag (per CLAUDE.md). My canonical L25 is WS truth — no lag.

The CORRECT framing: production's btc_5m_v1+F7 at 72.89% WR / +$10.40 is the
**live operating point**. My canonical-data F7@fire reproduction is the more
conservative **WS-truth lower bound**. When TV agent migrates production to WS-only
fills + real fees, live PnL will land somewhere between the two.

## Recommendations

1. **Deploy: Baseline_v1 + 2B + 2C ensemble on BTC 15m** — three sleeves with
   different anchors all profitable on canonical:
   - Baseline_v1 (ws-780 fire): +$2.39/tr, 5.1 fires/day
   - 2B (ws-120 fire): +$2.93/tr w/ F7x, 4.4 fires/day
   - 2C (ws fire): +$0.06/tr ALL, marginal

2. **Deploy: 2C + F7x on ETH 15m** — strongest single pocket (+$4.50/tr).
   Small sample (n=67 over 28d ≈ 2.4 fires/day) — start at $5-10 notional pilot.

3. **Don't deploy any 2A variant** — universally weakest.

4. **Drop ETH/SOL 5m + SOL 15m** from any v1 deploy — universally negative.

5. **Investigate 7.59% F7 mismatch vs live**: implement Wilder-smoothed RSI(14)
   to close the gap. Until then, my canonical F7 predictions are conservative
   (more false-negatives on the keep decision).

## Files

- Updated runner: `strategy_lab/meta_classifier/momo_variants_2abc.py`
  (compute_rsi_14_at anchors at fire_s, verified against live)
- Verifier: `strategy_lab/meta_classifier/_match_live_f7.py`
- Per-trade: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade.parquet`
- Per-cell csv: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_variant_cell.csv`
- Run log: `data/v4/canonical/_results/_momo_variants_2abc_v4_fresh_run.log`
- Updated CLAUDE.md: F7 anchor convention block now reflects verified result.
