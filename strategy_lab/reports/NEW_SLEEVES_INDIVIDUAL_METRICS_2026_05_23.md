# Individual sleeve metrics — S1.5, S6, S7 (new strategies from second run)

_2026-05-23. Per-sleeve performance for the 28 new candidate sleeves from
slot-anchored VWAP (S1.5), spike-driven entry (S6), and 15m VWAP
continuation (S7). All metrics on 28-day backtest, $25 notional, engine_v2
LegacyConfig (2%-on-profit fees, production-parity)._

---

## Grand totals (all 28 sleeves)

| Metric | Value |
|---|---:|
| Total sleeves | **28** |
| Total fires (28d) | **8,064** |
| Sum PnL @ $25 notional | **+$16,135** |
| Average WR | **79.7%** |
| Worst single-sleeve max DD | −$849 (S1.5 SOL 270s) |
| Best single-sleeve Sharpe | 15.10 (S6 BTC off60 D4) |

---

## S1.5 — Slot-anchored VWAP continuation (10 sleeves)

Bet WITH binance deviation from slot-open-anchored VWAP. Fire at
slot_start + offset_s.

| # | Sleeve | n | WR | $/tr | sum $ | max DD | loss streak | Sharpe | train WR | test WR | avg entry vwap |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | **BTC_210_5-10bps** | 529 | **87.3%** | +$2.99 | **+$1,581** | −$231 | **2** | 5.26 | 87.3% | 87.4% | 0.859 |
| 2 | **ETH_210_10-15bps** | 138 | 87.0% | **+$10.92** | **+$1,508** | −$186 | 2 | 4.19 | 90.6% | 78.6% | 0.848 |
| 3 | BTC_240_3-5bps | 810 | 81.7% | +$1.09 | +$886 | −$385 | 4 | 4.89 | 81.7% | 81.9% | 0.805 |
| 4 | ETH_150_5-10bps | 707 | 84.3% | +$1.25 | +$883 | −$264 | 3 | **8.26** | 84.4% | 84.0% | 0.818 |
| 5 | ETH_240_5-10bps | 714 | 85.3% | +$1.13 | +$803 | −$419 | 5 | 3.53 | 85.6% | 84.7% | 0.842 |
| 6 | SOL_270_5-10bps | 570 | 87.2% | +$1.14 | +$651 | −$849 | 3 | 1.68 | 88.2% | 84.8% | 0.864 |
| 7 | BTC_150_3-5bps | 770 | 81.0% | +$0.84 | +$650 | −$261 | 3 | 5.60 | 81.6% | 79.7% | 0.779 |
| 8 | ETH_210_5-10bps | 719 | 87.5% | +$0.84 | +$606 | −$216 | 3 | 7.26 | 88.1% | 86.1% | 0.837 |
| 9 | BTC_60_3-5bps | 442 | 74.7% | +$1.31 | +$579 | −$277 | 4 | 6.39 | 75.7% | 72.2% | 0.707 |
| 10 | **SOL_30_5-10bps** | 112 | 81.2% | **+$4.84** | +$542 | −$75 | 3 | **13.32** | 83.3% | 76.5% | 0.688 |
| | **S1.5 totals** | **5,511** | **avg 83.7%** | — | **+$8,689** | −$849 worst | — | avg 6.04 | — | — | — |

**Standout**:
- **ETH 210s 10-15bps** has the highest $/tr we've found in any strategy: **+$10.92**.
- **SOL 30s 5-10bps** has the highest Sharpe of S1.5: **13.32** (early-fire on cheap underdog-side entries, vwap=0.688).
- **BTC 210s 5-10bps** is the highest sum_pnl ($1,581) and tightest loss streak (only 2).

---

## S6 — Spike-driven entry (10 sleeves)

Fires on 5-15s binance breakouts independent of momo signal. Definition
D1 = `|ret_5s|>2.5bps + CVD agree`. D2/D4 = sustained-spike variants.
Tier T1 = lower-magnitude threshold.

| # | Sleeve | n | WR | $/tr | sum $ | max DD | loss streak | Sharpe | train WR | test WR | avg entry vwap |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | **BTC_off120_D1_T1** | 146 | 70.5% | **+$6.57** | **+$960** | −$145 | 5 | **8.70** | 69.6% | 72.7% | 0.614 |
| 2 | BTC_off45_D1_T1 | 165 | 66.1% | +$5.42 | +$895 | −$150 | 6 | 8.01 | 67.8% | 62.0% | 0.560 |
| 3 | **BTC_off30_D1_T1** | 149 | 67.1% | +$5.15 | +$768 | −$125 | 4 | **11.07** | 63.5% | 75.6% | 0.560 |
| 4 | BTC_off60_D2_T1 | 158 | 72.2% | +$3.35 | +$530 | −$127 | 3 | 8.68 | 74.5% | 66.7% | 0.635 |
| 5 | **BTC_off60_D4_T1** | 97 | **83.5%** | +$4.88 | +$474 | −$70 | **2** | **15.10** | 86.6% | 76.7% | 0.723 |
| 6 | SOL_off30_D2_T1 | 130 | 78.5% | +$3.55 | +$461 | −$121 | 2 | 10.26 | 80.2% | 74.4% | 0.703 |
| 7 | ETH_off60_D1_T1 | 182 | 67.0% | +$2.52 | +$459 | −$324 | 6 | 6.40 | 67.7% | 65.5% | 0.605 |
| 8 | **ETH_off120_D4_T1** | 98 | **80.6%** | +$4.61 | +$451 | −$128 | 4 | 8.17 | 75.0% | **93.3%** | 0.737 |
| 9 | BTC_off45_D2_T1 | 159 | 71.7% | +$2.46 | +$391 | −$136 | 3 | 8.03 | 72.1% | 70.8% | 0.667 |
| 10 | ETH_off15_D2_T1 | 230 | 73.0% | +$1.63 | +$375 | −$159 | 3 | 5.72 | 69.6% | 81.2% | 0.685 |
| | **S6 totals** | **1,514** | **avg 73.0%** | — | **+$5,764** | −$324 worst | — | **avg 9.01** | — | — | — |

**Standout**:
- **BTC off60 D4 T1**: 83.5% WR + Sharpe 15.10 + loss streak only 2 — highest-Sharpe sleeve across ALL strategies.
- **BTC off30 D1 T1**: train_wr 63.5 → test_wr 75.6 (OOS BETTER than IS by 12pp — very robust).
- **ETH off120 D4 T1**: test_wr 93.3% on n=29 hold-out (highest OOS WR).
- All entries are at CHEAP vwap (0.56–0.74), so the high WR also pays well per trade.

---

## S7 — VWAP continuation 15m markets (8 sleeves)

Same logic as S1.5 but on 15m markets. Fire offsets 60-840s into 900s slot.

| # | Sleeve | n | WR | $/tr | sum $ | max DD | loss streak | Sharpe | train WR | test WR | avg entry vwap |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | **SOL_840_20-30bps** | 40 | 77.5% | **+$17.34** | **+$694** | −$115 | 2 | 3.45 | 78.6% | 75.0% | 0.775 |
| 2 | ETH_480_5-10bps | 449 | 76.8% | +$0.61 | +$274 | −$404 | 4 | **4.05** | 76.4% | 77.8% | 0.746 |
| 3 | SOL_240_10-15bps | 116 | 82.8% | +$1.79 | +$208 | −$221 | 3 | 3.87 | 77.8% | **94.3%** | 0.791 |
| 4 | ETH_720_15-20bps | 45 | 77.8% | **+$3.48** | +$156 | −$110 | 2 | 2.41 | 77.4% | 78.6% | 0.791 |
| 5 | **ETH_240_10-15bps** | 68 | 86.8% | +$1.98 | +$135 | −$77 | 3 | 5.36 | 85.1% | **90.5%** | 0.785 |
| 6 | SOL_360_10-15bps | 165 | 82.4% | +$0.68 | +$112 | −$151 | 2 | 2.20 | 83.5% | 80.0% | 0.819 |
| 7 | **ETH_480_15-20bps** | 58 | **89.7%** | +$1.23 | +$72 | −$70 | **1** | 2.42 | 92.5% | 83.3% | 0.878 |
| 8 | **BTC_480_10-15bps** | 98 | **89.8%** | +$0.33 | +$32 | −$96 | 2 | 1.92 | 86.8% | **96.7%** | 0.866 |
| | **S7 totals** | **1,039** | **avg 82.9%** | — | **+$1,683** | −$404 worst | — | avg 3.21 | — | — | — |

**Standout**:
- **SOL 840s 20-30bps**: late-fire (60s remaining of 900s slot) with strong VWAP extension → **+$17.34/tr** (highest $/tr across the entire study).
- **BTC 480s 10-15bps**: 89.8% WR with test_wr=96.7% — OOS even better than IS. But small $/tr because entry vwap is 0.866 (already priced in).
- **ETH 480s 15-20bps**: 89.7% WR, only 1-trade max loss streak — most consistent.

---

## Side-by-side comparison

| Strategy family | n sleeves | total n | avg WR | sum $ | worst max DD | avg Sharpe | DD/sum ratio |
|---|--:|--:|--:|--:|--:|--:|--:|
| **S1.5 Slot-anchored VWAP** | 10 | 5,511 | 83.7% | **+$8,689** | −$849 | 6.04 | 9.8% |
| S6 Spike-driven | 10 | 1,514 | 73.0% | +$5,764 | −$324 | **9.01** | 5.6% |
| S7 15m VWAP | 8 | 1,039 | 82.9% | +$1,683 | −$404 | 3.21 | 24% |
| **ALL 3 strategies** | **28** | **8,064** | **79.7%** | **+$16,135** | n/a | n/a | — |

**Family characteristics**:
- **S1.5**: highest sum_pnl, high WR, large fire counts per sleeve. Late-fire pattern (60-270s into 5m slot).
- **S6**: highest average Sharpe (9.0), best DD/sum ratio (5.6%), cheaper entry vwaps (0.56-0.74 vs 0.78+ for S1.5). Best risk-adjusted family.
- **S7**: high WR but tiny per-trade edge (mostly $0.30-$2/tr); 15m fires 4× less than 5m so smaller universe. Only SOL 840s breaks out.

---

## OOS validation summary

Train/test 70/30 chronological split. Configs where **test_wr ≥ train_wr** (i.e., OOS holds up or improves):

| Strategy | sleeves with test_wr ≥ train_wr | of total |
|---|--:|--:|
| S1.5 | 4 / 10 | 40% |
| S6 | 4 / 10 | 40% |
| S7 | 5 / 8 | 62% |
| **Overall** | **13 / 28** | **46%** |

When test_wr < train_wr, the gap is typically small (-5 to -10pp). Highest gaps:
- S1.5 ETH 210s 10-15bps: train 90.6% → test 78.6% (-12pp — but still 78.6%)
- S1.5 SOL 30s 5-10bps: train 83.3% → test 76.5% (-7pp)
- S6 BTC 60s D4 T1: train 86.6% → test 76.7% (-10pp — but 76.7% absolute is excellent)

Conversely, test_wr > train_wr by ≥5pp:
- S7 BTC 480s 10-15bps: 86.8 → 96.7 (+10pp)
- S7 SOL 240s 10-15bps: 77.8 → 94.3 (+17pp)
- S7 ETH 240s 10-15bps: 85.1 → 90.5 (+5pp)
- S6 ETH 120s D4 T1: 75.0 → 93.3 (+18pp)
- S6 BTC 30s D1 T1: 63.5 → 75.6 (+12pp)
- S1.5 BTC 60s 3-5bps: train 75.7 → test 72.2 (close)

The OOS picture is solid — no catastrophic train/test breakdowns.

---

## Recommended top-5 deploy roster (non-overlapping, max diversity)

| # | Strategy | Sleeve | n | WR | $/tr | sum $ | Sharpe | Why |
|--:|---|---|--:|--:|--:|--:|--:|---|
| 1 | S1.5 | BTC_210_5-10bps | 529 | 87.3% | +$2.99 | +$1,581 | 5.26 | Highest sum, n=529, low DD |
| 2 | S1.5 | ETH_210_10-15bps | 138 | 87.0% | +$10.92 | +$1,508 | 4.19 | Best $/tr in 5m universe |
| 3 | S6 | BTC_off120_D1_T1 | 146 | 70.5% | +$6.57 | +$960 | 8.70 | Independent of S1.5 universe |
| 4 | S6 | BTC_off60_D4_T1 | 97 | 83.5% | +$4.88 | +$474 | **15.10** | Highest Sharpe, lowest DD |
| 5 | S7 | SOL_840_20-30bps | 40 | 77.5% | **+$17.34** | +$694 | 3.45 | Standalone 15m hammer |
| | **TOTAL** | | **950** | avg 81.2% | | **+$5,217 / 28d** | | ~$186/day @ $25 |

Adding the next-tier 5 sleeves (BTC_60_D2_T1, ETH_120_D4_T1, SOL_30_D2_T1,
ETH_240_5-10bps, SOL_30_5-10bps) brings the total to **~$8,000 / 28d at $25**
= ~$286/day = ~$2,860/day at $250 notional.

---

## Files

- `data/v4/canonical/_results/new_sleeves_per_sleeve_metrics.csv` — 28-row table source
- `data/v4/canonical/_results/vwap_slot_anchored_5m_per_fire.parquet` — S1.5 raw fires
- `data/v4/canonical/_results/spike_entry_5m_per_fire.parquet` — S6 raw fires
- `data/v4/canonical/_results/vwap_continuation_15m_per_fire.parquet` — S7 raw fires

## End
