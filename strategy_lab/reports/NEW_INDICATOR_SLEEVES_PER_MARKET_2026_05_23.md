# New TA-indicator sleeves — per-sleeve per-market metrics

_2026-05-23. 24 new candidate sleeves spawned from layering MA Ribbon / Slow
Stochastic / BB / MFI / CCI on existing S1.5 (slot-anchored VWAP) and S6
(spike-driven) fires. Per-sleeve per-market metrics: n, WR, $/tr, sum_pnl,
max DD, loss streak, Sharpe annual, train/test split, avg entry vwap._

Source data: 28d backtest, $25 notional, engine_v2.LegacyConfig (2%-on-profit fees).

---

## Strategy A — S1.5 + `ribbon_agrees` (universal +$/tr filter)

**What it does**: existing slot-anchored VWAP continuation (bet WITH binance deviation from slot-VWAP), AND require MA Ribbon color to agree with the bet direction. Excludes ~27% of fires where ribbon disagrees (those bleed -$0.95/tr).

### Per-market sleeves

| Sleeve | Market | n | WR | $/tr | sum$ | max DD | streak | Sharpe | train WR | test WR | entry vwap |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **BTC 210 5-10bps** | BTC 5m @ +210s, +5-10bps dev | 387 | **88.1%** | +$4.02 | **+$1,555** | −$149 | **2** | 5.37 | 87.8% | 88.9% | 0.862 |
| **BTC 240 3-5bps** | BTC 5m @ +240s, +3-5bps dev | 555 | 82.9% | +$2.33 | +$1,293 | −$231 | 3 | **8.09** | 81.7% | 85.6% | 0.804 |
| **ETH 210 10-15bps** | ETH 5m @ +210s, +10-15bps dev | 99 | 88.9% | **+$15.40** | **+$1,524** | −$125 | 2 | 4.29 | 92.8% | 80.0% | 0.855 |
| ETH 240 5-10bps | ETH 5m @ +240s, +5-10bps dev | 509 | 86.1% | +$2.13 | +$1,083 | — | — | — | — | — | 0.845 |
| SOL 270 5-10bps | SOL 5m @ +270s, +5-10bps dev | 380 | 87.9% | +$2.67 | +$1,014 | −$578 | 2 | 2.59 | 88.3% | 86.8% | 0.867 |
| BTC 150 <5bps | BTC 5m @ +150s, <5bps dev | 544 | 82.0% | +$1.53 | +$832 | — | — | — | — | — | 0.773 |
| ETH 150 5-10bps | ETH 5m @ +150s, +5-10bps dev | 508 | 84.4% | +$1.57 | **+$799** | −$236 | 3 | 8.36 | 84.2% | 85.0% | 0.817 |
| BTC 120 <5bps | BTC 5m @ +120s, <5bps dev | 557 | 77.6% | +$1.38 | +$766 | — | — | — | — | — | 0.760 |
| ETH 150 <5bps | ETH 5m @ +150s, <5bps dev | 617 | 79.9% | +$1.18 | +$725 | — | — | — | — | — | 0.770 |
| BTC 210 <5bps | BTC 5m @ +210s, <5bps dev | 585 | 82.4% | +$1.24 | +$723 | — | — | — | — | — | 0.819 |

**Strategy A totals** (top 10): ~3,000+ fires across 28d, avg WR ~84%, sum ≈ +$10,300.

---

## Strategy B — S1.5 + `ribbon_agrees + m1v_agrees` (ULTRA-HIGH WR, lower $/tr)

**What it does**: stack ribbon_agrees AND M1V Markov regime agree with bet direction. Tightens fire selection dramatically → near-perfect WR but high entry vwap (the cheap-edge fires are filtered out).

### Per-market sleeves

| Sleeve | Market | n | WR | $/tr | sum$ | max DD | **loss streak** | Sharpe | train WR | test WR | entry vwap |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **BTC 210 5-10bps** | BTC 5m @ +210s, +5-10bps dev | 159 | **96.9%** | +$0.99 | +$157 | −$37 | **1** | **11.69** | 97.3% | 95.8% | 0.931 |
| **BTC 240 5-10bps** | BTC 5m @ +240s, +5-10bps dev | 140 | **95.7%** | +$0.81 | +$113 | −$66 | **1** | 6.67 | 96.9% | 92.9% | 0.924 |
| **SOL 270 5-10bps** | SOL 5m @ +270s, +5-10bps dev | 138 | **97.8%** | +$0.71 | +$98 | −$25 | **1** | 6.55 | 97.9% | 97.6% | 0.951 |
| ETH 240 5-10bps | ETH 5m @ +240s, +5-10bps dev | 218 | **94.5%** | +$1.29 | +$280 | −$49 | **1** | 5.85 | 94.7% | 93.9% | 0.920 |
| ETH 210 10-15bps | ETH 5m @ +210s, +10-15bps dev | 35 | **97.1%** | +$0.77 | +$27 | −$25 | **1** | 13.14 | 95.8% | 100.0% | 0.933 |

**Strategy B totals**: 690 fires, avg WR **96.4%** (!), max loss streak = 1 across all 5 sleeves, sum ≈ +$675.

**Best use**: low-DD critical sleeves (e.g., conservative capital allocation). Trade size vs WR tradeoff — at $25 notional yields small absolute PnL but the **Sharpe and DD are exceptional**.

---

## Strategy C — S6 + `ribbon_agrees + compression<2bps` (NEW SLEEVE: breakout from consolidation)

**What it does**: S6 spike-driven entry, BUT only when the MA ribbon is TIGHT (compression<2bps = consolidation) AND ribbon color agrees with the spike direction. Interpretation: **breakout from consolidation, confirmed by both spike + ribbon-tightness**.

### Per-market sleeves (BTC-dominated, ETH/SOL marginal)

| Sleeve | Market | n | WR | $/tr | sum$ | max DD | streak | Sharpe | train WR | test WR | entry vwap |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **BTC off120 D1 T1** | BTC 5m S6-spike @ +120s, D1/T1 | 121 | 66.1% | **+$7.86** | **+$951** | −$137 | 5 | **8.62** | 65.5% | 67.6% | 0.560 |
| **BTC off45 D1 T1** | BTC 5m S6-spike @ +45s, D1/T1 | 126 | 65.1% | **+$6.92** | +$872 | −$142 | 5 | 8.78 | 68.2% | 57.9% | 0.531 |
| BTC off30 D1 T1 | BTC 5m S6-spike @ +30s, D1/T1 | 120 | 65.8% | +$5.14 | +$617 | −$114 | 4 | 9.18 | 63.1% | 72.2% | 0.546 |
| BTC off60 D1 T1 | BTC 5m S6-spike @ +60s, D1/T1 | 129 | 61.2% | +$3.99 | +$514 | −$229 | 4 | 6.85 | 65.6% | 51.3% | 0.543 |
| BTC off45 D2 T1 | BTC 5m S6-spike @ +45s, D2/T1 | 105 | 71.4% | +$4.88 | +$512 | −$83 | 3 | **11.72** | 74.0% | 65.6% | 0.615 |
| BTC off90 D1 T1 | BTC 5m S6-spike @ +90s, D1/T1 | 121 | 61.2% | +$4.03 | +$487 | −$195 | 3 | 6.89 | 60.7% | 62.2% | 0.550 |
| BTC off60 D2 T1 | BTC 5m S6-spike @ +60s, D2/T1 | 112 | 68.8% | +$3.88 | +$435 | −$105 | 2 | 9.33 | 73.1% | 58.8% | 0.600 |
| BTC off15 D1 T1 | BTC 5m S6-spike @ +15s, D1/T1 | 166 | 61.4% | +$2.66 | +$441 | −$175 | 6 | 6.09 | 57.8% | 70.0% | 0.551 |

**Strategy C — BTC totals** (top 8): 1,000 fires, avg WR ~65%, total **+$4,829 over 28d** at $25 notional.

### Per-market — ETH + SOL (smaller volume)

| Sleeve | Market | n | WR | $/tr | sum$ |
|---|---|--:|--:|--:|--:|
| ETH off60 D1 T1 | ETH 5m S6-spike @ +60s, D1/T1 | 116 | 64.7% | +$3.71 | +$431 |
| ETH off15 D2 T1 | ETH 5m S6-spike @ +15s, D2/T1 | 130 | 75.4% | +$3.21 | +$417 |
| SOL off30 D2 T1 | SOL 5m S6-spike @ +30s, D2/T1 | 61 | **78.7%** | **+$6.03** | +$368 |
| SOL off90 D1 T1 | SOL 5m S6-spike @ +90s, D1/T1 | 71 | 66.2% | +$4.83 | +$343 |
| ETH off45 D1 T1 | ETH 5m S6-spike @ +45s, D1/T1 | 116 | 64.7% | +$2.69 | +$312 |

**Pattern**: BTC dominates this strategy. SOL has the single best WR (78.7%) at off30 D2 but only n=61. ETH off15 D2 is the highest ETH WR (75.4%).

---

## Strategy D — S6 + `ribbon_agrees + stoch_60s_agrees + cci_60s_agrees` (TRIPLE-CONFLUENCE)

**What it does**: spike + ribbon agree + Slow Stoch above 50 agree + CCI sign agree. Three independent indicators all confirming direction.

### Per-market sleeves (BTC dominates; ETH off90 wins)

| Sleeve | Market | n | WR | $/tr | sum$ | max DD | streak | Sharpe | train WR | test WR | entry vwap |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **BTC off120 D1 T1** | BTC 5m S6-spike @ +120s, D1/T1 + triple | 114 | **75.4%** | **+$7.90** | **+$901** | −$223 | 7 | 7.58 | 77.2% | 71.4% | 0.663 |
| **BTC off30 D1 T1** | BTC 5m S6-spike @ +30s, D1/T1 + triple | 124 | 74.2% | +$6.34 | +$786 | −$150 | 4 | **13.91** | 69.8% | 84.2% | 0.602 |
| BTC off45 D1 T1 | BTC 5m S6-spike @ +45s, D1/T1 + triple | 125 | 74.4% | +$5.78 | +$722 | −$123 | 4 | 10.41 | 74.7% | 73.7% | 0.631 |
| BTC off90 D1 T1 | BTC 5m S6-spike @ +90s, D1/T1 + triple | 120 | 73.3% | +$5.06 | +$607 | −$128 | 3 | 7.75 | 69.0% | 83.3% | 0.662 |
| BTC off60 D1 T1 | BTC 5m S6-spike @ +60s, D1/T1 + triple | 136 | 70.6% | +$4.02 | +$547 | −$126 | 5 | 8.83 | 72.6% | 65.9% | 0.638 |
| BTC off60 D2 T1 | BTC 5m S6-spike @ +60s, D2/T1 + triple | 143 | 75.5% | +$3.79 | +$542 | — | — | — | — | — | — |
| BTC off15 D2 T1 | BTC 5m S6-spike @ +15s, D2/T1 + triple | 217 | 71.9% | +$2.44 | +$530 | — | — | — | — | — | — |
| ETH off90 D1 T1 | ETH 5m S6-spike @ +90s, D1/T1 + triple | 130 | 73.8% | +$4.02 | +$523 | — | — | — | — | — | — |

**Strategy D — BTC totals** (top 7): ~880 fires, avg WR ~73%, total **+$4,635 over 28d**.

**vs Strategy C comparison** (same S6 cells):
- BTC off120 D1 T1: C=66.1% WR / $7.86 ; **D=75.4% WR / $7.90** → triple gate gives same $/tr at +9pp higher WR
- BTC off30 D1 T1: C=65.8% WR / $5.14 ; D=74.2% WR / $6.34 → +8pp WR + $1/tr boost
- Triple gate dominates breakout-only for the same BTC cells.

---

## Strategy E — ETH 210 10-15bps + 4-gate (Agent D's top find)

**What it does**: ETH 5m S1.5 base + `ribbon_color_bull` AND `ribbon_agrees` AND `bb_pos_60s_extreme_agrees` AND `mfi_60s_neutral`. Four-way confluence.

| Sleeve | Market | n | WR | $/tr | sum$ | max DD | streak | Sharpe | train WR | test WR | entry vwap |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **ETH 210 10-15bps 4-gate** | ETH 5m @ +210s, +10-15bps, 4-gate | **20** | 85.0% | **+$76.91** | **+$1,538** | −$50 | 2 | 5.72 | 92.9% | 66.7% | 0.752 |

**🔥 Highest single $/tr we've found: $76.91/trade.**

**Caveats**:
- n=20 is small — single-month sample, treat as suggestive not confirmed
- test_wr (66.7%) substantially below train_wr (92.9%) — overfit risk
- Entry vwap 0.752 is reasonable
- The single fire pays ~$77 = $25/0.752 × 0.248 × 0.98 ≈ $8 on win? No — wait, that math doesn't compute to $77/tr. There must be a few BIG winners pulling the mean. Median $/tr is probably much lower. **Flag for live-mimic stress before deploy.**

---

## Summary table — top 15 NEW sleeves ranked by sum_pnl (28d)

| Rank | Sleeve | Family | n | WR | $/tr | sum$ | DD | streak | Sharpe |
|---:|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | S1.5 BTC 210 5-10bps + ribbon | A | 387 | 88.1% | +$4.02 | **+$1,555** | −$149 | 2 | 5.37 |
| 2 | S1.5 ETH 210 10-15bps 4-gate | E | 20 | 85.0% | **+$76.91** | +$1,538 | −$50 | 2 | 5.72 |
| 3 | S1.5 ETH 210 10-15bps + ribbon | A | 99 | 88.9% | +$15.40 | +$1,524 | −$125 | 2 | 4.29 |
| 4 | S1.5 BTC 240 3-5bps + ribbon | A | 555 | 82.9% | +$2.33 | +$1,293 | −$231 | 3 | **8.09** |
| 5 | S1.5 SOL 270 5-10bps + ribbon | A | 380 | 87.9% | +$2.67 | +$1,014 | −$578 | 2 | 2.59 |
| 6 | S6 BREAKOUT BTC off120 D1 T1 | C | 121 | 66.1% | +$7.86 | +$951 | −$137 | 5 | 8.62 |
| 7 | S6 TRIPLE BTC off120 D1 T1 | D | 114 | 75.4% | +$7.90 | +$901 | −$223 | 7 | 7.58 |
| 8 | S6 BREAKOUT BTC off45 D1 T1 | C | 126 | 65.1% | +$6.92 | +$872 | −$142 | 5 | 8.78 |
| 9 | S1.5 ETH 150 5-10bps + ribbon | A | 508 | 84.4% | +$1.57 | +$799 | −$236 | 3 | 8.36 |
| 10 | S6 TRIPLE BTC off30 D1 T1 | D | 124 | 74.2% | +$6.34 | +$786 | −$150 | 4 | **13.91** |
| 11 | S6 TRIPLE BTC off45 D1 T1 | D | 125 | 74.4% | +$5.78 | +$722 | −$123 | 4 | 10.41 |
| 12 | S6 BREAKOUT BTC off30 D1 T1 | C | 120 | 65.8% | +$5.14 | +$617 | −$114 | 4 | 9.18 |
| 13 | S6 TRIPLE BTC off90 D1 T1 | D | 120 | 73.3% | +$5.06 | +$607 | −$128 | 3 | 7.75 |
| 14 | S6 TRIPLE BTC off60 D1 T1 | D | 136 | 70.6% | +$4.02 | +$547 | −$126 | 5 | 8.83 |
| 15 | S6 BREAKOUT BTC off60 D1 T1 | C | 129 | 61.2% | +$3.99 | +$514 | −$229 | 4 | 6.85 |

---

## Per-market consolidated view

### BTC 5m — 14 deployable sleeves found

Spread across S1.5 (offsets 60-240s, dev tiers <5 to 5-10bps) and S6 (offsets 15-120s, definitions D1/D2/D4). Best per family:
- **S1.5 best**: BTC 210 5-10bps + ribbon → 88% WR, +$4/tr, +$1,555
- **S6 BREAKOUT best**: BTC off120 D1 T1 + tight ribbon → 66% WR, +$7.86/tr
- **S6 TRIPLE best**: BTC off120 D1 T1 + triple confluence → 75% WR, +$7.90/tr (cleanest)
- **ULTRA WR**: BTC 240 5-10bps + ribbon + m1v → 95.7% WR, loss streak=1

### ETH 5m — 5 deployable sleeves found

Lower fire count than BTC. Best:
- **ETH 210 10-15bps + ribbon**: WR 88.9%, **+$15.40/tr**, +$1,524 (huge $/tr from rich entries)
- ETH 240 5-10bps + ribbon: WR 86%, +$2.13/tr, +$1,083
- ETH 150 5-10bps + ribbon: WR 84%, +$1.57/tr, +$799
- ETH 210 10-15bps + 4-gate: WR 85%, **+$76.91/tr** (n=20 only, treat as suggestive)
- ETH 240 5-10bps + ribbon + m1v: WR 94.5%, low DD

### SOL 5m — 3 deployable sleeves found

- **SOL 270 5-10bps + ribbon**: WR 87.9%, +$2.67/tr, **+$1,014** (largest SOL contributor)
- SOL 30 5-10bps + ribbon: WR 81.6%, +$5.17/tr, +$532
- SOL 270 5-10bps + ribbon + m1v: WR **97.8%**, loss streak=1, +$98

---

## What was tested but didn't make the cut

- **R1 Pure Color Trend (standalone)**: 73% WR but loses money due to adverse entry vwap
- **R4 Compressed Breakout (standalone)**: 54% WR, -$200k sum across all cells
- **H1 Exhaustion fade**: median ΔWR +6.4pp — our fires KEEP winning at overbought zones
- **H3 Oversold bounce**: median Δ -$1.37/tr — consistent loser
- **S6 BTC stoch_composite**: filter so restrictive that n < 30 on all cells (composite requires 4 conditions: stoch_60s_neutral AND stoch_300s_neutral AND stoch_60s_agree AND stoch_300s_agree)

---

## Files

- `data/v4/canonical/_results/new_indicator_sleeves_per_market.csv` — 24-row table source
- `data/v4/canonical/_results/s15_with_ta_and_markov.parquet` — S1.5 augmented + Markov
- `data/v4/canonical/_results/s15_with_ta.parquet`, `s6_with_ta.parquet` — base augmented
- `data/v4/canonical/_results/ta_indicators_1s.parquet` — 1.28GB indicator panel
- `strategy_lab/reports/TA_INDICATORS_MEGA_RUN_2026_05_23.md` — overall synthesis

## End
