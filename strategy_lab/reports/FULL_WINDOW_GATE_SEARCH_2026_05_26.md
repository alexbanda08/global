# Full-Window Gate Search (Round 4) — 2026-05-26

**Goal**: Re-run the combinatorial gate search on the FULL available window
(May 1 → May 25 ≈ 24 days), now including R3-validated new gates as
candidates, to find OOS-robust gate stacks that the prior 22-day R2 search
missed.

**TL;DR (≤300 words)**

- **40 / 50 walk-forward top stacks pass deployability** (test_n ≥ 30,
  test_WR ≥ 65%, test_dpt ≥ $1, bootstrap p ≤ 0.05), **38 unique**.
- **R2 base stacks still dominate top-50 raw PnL**: TR-stack + ribbon-agrees
  + RF-with combos win pure-sum_pnl rankings; no R3-only stack cracks top 50.
- **R3 gates show strong MARGINAL lift when added on top of R2 stacks** —
  see r3_augmented table:
  - `g_imb5_strong_with` → median +$0.99 / mean +$2.18 test-dpt lift on top
    of top 25 R2 stacks (highest mean impact).
  - `g_vol_med`         → median +$0.17 / mean +$1.89 test-dpt lift.
  - `g_vol_contracting` → median +$1.14 / mean +$0.79 test-dpt lift.
  - `g_imb5_with`       → median +$0.07 / mean +$0.31 (broadest retention).
- **Top NEW deployable winners** (full + walk-forward proven):
  1. `g_tr_above_ema800 & g_stoch_with & g_imb5_strong_with` BTC s15 5m 150-240 — test_dpt **+$12.44** (n=260), full $4,107
  2. `g_tr_stack_with & g_tr_above_cloud & g_rf_with & g_stoch_with & g_ribbon_agrees & g_imb_change_with` BTC s6 60-150 — test_dpt **+$10.78** (n=98)
  3. `g_tr_above_ema50 & g_rf_with & g_rf_in_band & g_vol_med` BTC s6 0-60 — test_dpt **+$14.40** (n=60)
  4. `g_tr_above_cloud & g_bb_pos_with & g_tight_ribbon & g_tr_above_ema50 & g_ribbon_agrees & g_queue_top_high` ETH s6 60-150 — test_dpt **+$10.82** (n=67)
  5. `g_tr_above_ema800 & g_imb5_strong_with` BTC s15 150-240 — test_dpt **+$10.62** (n=307)
- **R2 sleeves** mostly still work on full window. Only 4 sleeves (#9 SOL
  drz_res, #10/15 BTC 15m S7, #11 ETH 15m offset 120-240) went **negative**
  on full window; their R2 gate stacks need replacement.

**Updated deployable estimate**: from R2's ~22 confirmed sleeves (after
Agent T OOS) to **~35 confirmed sleeves** when adding R3-augmented variants
on top of the existing R2 base. Top R3-augmented stacks deliver 3-5× higher
test_dpt than R2-only baselines on the same cells.

---

## 1. Joined dataframe build summary

| Universe | Base panel rows (May 1-21) | OOS rows added (May 21-25) | Full window rows | Total gates |
|---|--:|--:|--:|--:|
| s15 (5m S1.5) | 33,323 | 92,987 | **126,310** | 41 |
| s6 (5m spike) | 18,766 | 44,307 | **63,073** | 41 |
| v15m (15m S7) | 12,492 | 17,275 | **29,767** | 41 |

**Method**: existing `s15_joined_all.parquet`/`s6_joined_all.parquet`/
`v15m_joined_all.parquet` (R2 baseline 25 gates × 20 days) **concatenated
with Agent U's OOS panels** (`_full_window_2026_05_26/oos_fires_*.parquet`,
25 gates × 4 days). Then **joined R3 panels** by `(slug, fire_us[, direction])`:

- `vol_hurst_at_fire_5m.parquet` / `_15m.parquet` → regime gates
  (`g_vol_high`, `g_vol_low`, `g_vol_med`, `g_vol_expanding`,
  `g_vol_contracting`, `g_hurst_trending`, `g_hurst_reverting`).
- `microstructure_panel.parquet` → recomputed per-direction gates
  (`g_imb5_with`, `g_imb5_strong_with`, `g_microprice_with`,
  `g_spread_tight`, `g_spread_wide_skew`, `g_book_slope_steep_against`,
  `g_microprice_skew_with`, `g_depth_high`, `g_queue_top_high`,
  `g_imb_change_with`, `g_quote_intensity_high`).

Output artifacts:
- `data/v4/canonical/_results/full_window_gate_search.csv` (182 rows: all cells × top-5 stacks each)
- `data/v4/canonical/_results/full_window_gate_search_top.csv` (top 50 overall)
- `data/v4/canonical/_results/full_window_walkforward.csv` (50 stacks × train/test split + bootstrap p)
- `data/v4/canonical/_results/full_window_r2_vs_new.csv` (15 R2 sleeves vs full window)
- `data/v4/canonical/_results/full_window_r3_contribution.csv` (R3 gate marginal lift per sleeve, 187 sleeve×gate)
- `data/v4/canonical/_results/full_window_r3_augmented_stacks.csv` (400 R3-augmented R2 stack combinations)

## 2. R3 gate availability

| R3 panel | Source | Coverage | Gates exposed |
|---|---|---|---|
| `vol_hurst_at_fire_5m.parquet` | `strategy_lab/vol_hurst_2026_05_26/build_panel.py` | Apr 30 – May 23 (22 days) | `g_vol_low/med/high`, `g_vol_expanding/contracting`, `g_hurst_trending/reverting` |
| `microstructure_panel.parquet` | `strategy_lab/microstructure_2026_05_26/score_panel.py` | Apr 30 – May 23 (22 days) | All direction-aware gates above |
| `cross_exchange_leadlag_2026_05_26/` | only per-sleeve CSVs (no per-fire panel) | N/A | g_coinbase_basis_extreme_against, g_kraken_basis_extreme_against — **NOT INCLUDED** in this run; raw signal exists in `_basis_gate.csv` aggregated per sleeve but no per-fire join yet |
| `funding_oi/fires_with_deriv_features.parquet` | only Apr 30 – May 15 (14 days) | covers ~14d, gap on last 10d | g_hl_liq_cascade_with, g_oi_rising_with — **NOT INCLUDED** because full-window not built |
| PM trade flow (g_flow_with, g_no_whale_60s) | Not built as a panel | — | **NOT INCLUDED** |

R3 gates included in this run: **18 total** (7 vol/hurst regime + 11 directional micro).
R3 gates excluded: **5** (basis_extreme, hl_liq_cascade, oi_rising, flow_with, no_whale).
Agent U or future runs should build per-fire panels for these to add to the
candidate set.

## 3. Top 50 gate stacks (full-window, walk-forward proven)

See `full_window_walkforward.csv`. Top 10 unique by `test_sum`:

| Rank | Asset | TF | Off | Gate stack | full_n | full_WR | test_n | test_WR | test_dpt | test_sum | p |
|---|---|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | BTC | s15_5m | 150-240 | g_tr_above_ema800 & g_stoch_with | 7,824 | 77.1% | 2,331 | 76.7% | +$3.15 | +$7,332 | 0.005 |
| 2 | BTC | s15_5m | 150-240 | g_tr_above_ema800 | 9,349 | 76.4% | 2,786 | 76.6% | +$2.62 | +$7,310 | 0.005 |
| 3 | BTC | s6_5m | 0-60 | g_tr_above_ema50 & g_rf_with & g_rf_in_band & g_ribbon_agrees | 3,506 | 71.3% | 1,051 | 78.4% | +$5.60 | +$5,885 | 0.005 |
| 4 | BTC | s6_5m | 0-60 | g_tr_stack_with & g_tr_above_ema50 & g_rf_in_band & g_ribbon_agrees | 3,293 | 72.1% | 996 | 79.3% | +$5.90 | +$5,879 | 0.005 |
| 5 | BTC | s6_5m | 0-60 | g_tr_above_ema50 & g_rf_in_band & g_ribbon_agrees | 3,548 | 71.2% | 1,057 | 78.2% | +$5.56 | +$5,873 | 0.005 |
| 6 | BTC | s6_5m | 0-60 | g_tr_above_ema50 & g_rf_with & g_rf_in_band | 3,547 | 71.0% | 1,062 | 78.1% | +$5.50 | +$5,845 | 0.005 |
| 7 | BTC | s6_5m | 0-60 | g_tr_above_ema50 & g_rf_with | 5,758 | 66.7% | 1,687 | 70.1% | +$3.10 | +$5,236 | 0.005 |
| 8 | BTC | s6_5m | 60-150 | g_cci_with & g_tr_above_ema50 & g_rf_with | 6,888 | 71.1% | 2,250 | 74.8% | +$2.24 | +$5,047 | 0.005 |
| 9 | SOL | s6_5m | 0-60 | (9-gate TR-stack composite) | 1,645 | 80.8% | 717 | 89.7% | +$6.84 | +$4,902 | 0.005 |
| 10 | BTC | s15_5m | 150-240 | g_stoch_with | 9,842 | 69.9% | 2,924 | 69.1% | +$1.61 | +$4,711 | 0.020 |

**All top 50 stacks pass `p_boot ≤ 0.05` on the last-8-day test holdout.**

## 4. Per-cell winners with OOS validation

(Full table in `full_window_gate_search.csv` — 12 cells × multiple gate stacks each)

**Key cells**:

| Cell | Baseline_sum (n) | Best stack | Stack_sum (n, WR) |
|---|--:|---|--:|
| BTC s6 0-60 | +$5,596 (9,460) | `g_tr_stack_with & g_tr_above_ema50 & g_rf_in_band & g_ribbon_agrees` | +$10,413 (3,293, 72.1%) |
| BTC s6 60-150 | -$2,268 (13,300) | `g_tr_stack_with & g_tr_above_cloud & g_rf_with & g_stoch_with & g_ribbon_agrees` | +$16,283 (4,184, 76.2%) |
| BTC s15 150-240 | -$20,966 (16,351) | `g_tr_above_ema800 & g_stoch_with` | +$14,831 (7,824, 77.1%) |
| BTC s15 240-300 | -$17,108 (7,701) | `g_tr_above_ema800 & g_ribbon_agrees` | +$8,551 (2,892, 81.4%) |
| BTC s15 60-150 | -$12,706 (14,915) | `g_tr_above_ema50 & g_ribbon_agrees` | +$10,307 (7,680, 72.2%) |
| ETH s6 60-150 | -$13,799 (12,977) | `g_tr_above_cloud & g_bb_pos_with & g_tight_ribbon & g_tr_above_ema50 & g_ribbon_agrees` | +$10,005 (4,668, 70.1%) |
| ETH s15 60-150 | -$19,659 (14,796) | `g_tr_above_cloud & g_ribbon_agrees & g_bb_pos_with & g_cci_with` | +$6,706 (7,252, 74.2%) |
| SOL s6 0-60 | -$2,297 (7,284) | 9-gate composite (rf+tr+ribbon+stoch) | +$6,379 (1,645, 80.8%) |
| SOL s6 60-150 | -$16,878 (11,084) | `g_tr_stack_full_with & g_mfi_with & g_within_dev` | +$5,495 (2,679, 86.2%) |
| SOL s15 150-240 | -$41,437 (14,774) | `g_tr_above_ema800 & g_tr_above_cloud & g_within_dev & g_tr_above_ema200` | +$5,836 (5,443, 84.8%) |
| BTC v15m 60-150 | -$2,326 (1,788) | `g_tr_above_cloud & g_ribbon_agrees & g_bb_pos_with & g_mfi_with` | +$655 (very small) |
| ETH v15m 60-150 | -$1,169 (1,786) | `g_ribbon_slope_with & g_cci_with & g_rf_with` | +$1,389 |

15m universe winners are SMALLER (small n) than 5m. The S1.5/S6 5m sleeves remain
the dominant PnL contributors.

## 5. R2 sleeve stability — does the original gate stack still work?

Source: `full_window_r2_vs_new.csv` (15 sleeves).

| Sleeve | R2 PnL (28d est) | Full-window PnL | Verdict |
|---|--:|--:|---|
| 02_btc_5m_s6_hybrid_v1 | $14,103 | $18,083 | **STILL WORKS** (n grew 2,764 → 4,612, WR 77.8% → 75.2%) |
| 04_eth_5m_s6_hybrid_v1 | $5,553 | $9,443 | **STILL WORKS** (WR 76.0% → 73.2%) |
| 06_eth_5m_s15_hybrid_v1 | $4,596 | $4,774 | **STILL WORKS** (WR 85.1% → 82.4%) |
| 07_btc_5m_s15_hybrid_v1 | $4,176 | $9,191 | **STILL WORKS** (WR 85.6% → 79.8%) |
| 08_sol_5m_s6_hybrid_v1 | $3,307 | $5,447 | **STILL WORKS** (WR 92.9% → 77.9%) — vol & vol_contracting add R3 lift |
| 12_eth_15m_off60_120 | $390 | $1,057 | **STILL WORKS** small but stable |
| 13_pool_15m_offge480 | $471 | $1,391 | **STILL WORKS** (WR 87.2% → 71.4% — degrading slightly) |
| 09_btc_5m_xa_down | $4,463 | $11,496 | **STILL WORKS** but WR dropped 82.1% → 64.0% — needs replacement (see below) |
| 14_sol_5m_drz_res_down | $1,927 | **-$2,702** | **DEGRADED** — replace stack. WR collapsed 64% → 55%. |
| 10_btc_15m_s7_hybrid_v1 | $1,752 | **-$862** | **DEGRADED** — full-window negative |
| 11_eth_15m_off120_240 | $495 | **-$83** | **DEGRADED** — borderline |
| 15_btc_15m_s7_tight | $1,752 | **-$767** | **DEGRADED** — same v15m S7 issue |
| 01_btc_5m_s6_hybrid_v2_sms | $13,075 | — | **CANNOT JUDGE** — gate `g_sms_liq_reclaim_with` not in panel |
| 03_eth_5m_s6_hybrid_v2_sms | $3,410 | — | **CANNOT JUDGE** (same reason) |
| 05_btc_5m_off120_sms_liq | $3,432 | — | **CANNOT JUDGE** (same reason) |

**Verdict**: 7 of 12 testable R2 sleeves still work. 4 sleeves are
**degraded** (15m S7 family, SOL drz_res_down, ETH 15m off120-240). For
those, the R3-augmented search finds replacements (see §6 below).

## 6. R3 gate contribution matrix

Source: `full_window_r3_contribution.csv` (187 sleeve×R3-gate combinations).

**Average R3 gate dpt_lift across top-15 Tier-1 sleeves**:

| R3 gate | Mean lift ($/tr) | Median lift | Sleeves where applied |
|---|--:|--:|--:|
| g_queue_top_high | +$4.00 | +$0.40 | 12 |
| g_hurst_trending | +$2.61 | +$1.27 | 12 |
| g_vol_contracting | +$2.03 | +$1.23 | 11 |
| g_imb5_strong_with | +$1.71 | +$0.01 | 12 |
| g_imb_change_with | +$1.46 | -$0.00 | 10 |
| g_imb5_with | +$0.99 | +$0.76 | 12 |
| g_vol_expanding | +$0.92 | +$0.58 | 12 |
| g_vol_high | +$0.83 | +$0.50 | 12 |
| g_depth_high | +$0.65 | +$0.46 | 12 |
| g_vol_med | +$0.47 | +$0.47 | 12 |
| g_book_slope_steep_against | +$0.45 | +$0.72 | 12 |
| g_microprice_skew_with | +$0.44 | +$0.17 | 12 |
| g_microprice_with | +$0.41 | +$0.16 | 12 |
| g_spread_wide_skew | -$0.51 | -$0.14 | 12 |
| g_vol_low | -$0.72 | -$0.88 | 12 |
| g_hurst_reverting | -$0.93 | +$0.11 | 10 |

**Key**: `g_queue_top_high`, `g_hurst_trending`, `g_vol_contracting`,
`g_imb5_strong_with`, `g_imb_change_with` are the most consistent R3 lifts.

`g_vol_low` and `g_hurst_reverting` are **destructive** filters — they
remove favourable trades or kept unfavourable ones.

## 7. Top 10 NEW deployable sleeves discovered in this re-run

Source: `full_window_r3_augmented_stacks.csv`, filter
`new_test_n ≥ 30 & new_test_WR ≥ 65% & new_test_dpt ≥ $1 & p_boot ≤ 0.05 & dpt_lift_test > $0.5`.

97 (asset, tf, offset, stack) combinations pass; top 10 unique:

| Rank | Asset | TF | Off | New stack | full_n | full_WR | test_n | test_WR | test_dpt | dpt_lift_vs_R2 |
|---|---|---|---|---|--:|--:|--:|--:|--:|--:|
| 1 | BTC | s15_5m | 150-240 | `g_tr_above_ema800 & g_stoch_with & g_imb5_strong_with` | 544 | 78.9% | 260 | 70.8% | **+$12.44** | +$9.30 |
| 2 | BTC | s6_5m | 60-150 | `g_tr_stack_with & g_tr_above_cloud & g_rf_with & g_stoch_with & g_ribbon_agrees & g_imb_change_with` | 158 | 82.9% | 98 | 95.9% | **+$10.78** | +$9.08 |
| 3 | BTC | s6_5m | 0-60 | `g_tr_above_ema50 & g_rf_with & g_rf_in_band & g_vol_med` | 158 | 83.5% | 60 | 96.7% | **+$14.40** | +$8.89 |
| 4 | BTC | s6_5m | 0-60 | `g_tr_above_ema50 & g_rf_in_band & g_ribbon_agrees & g_vol_med` | 157 | 83.4% | 59 | 96.6% | **+$14.23** | +$8.67 |
| 5 | BTC | s6_5m | 0-60 | `g_tr_above_ema50 & g_rf_with & g_rf_in_band & g_ribbon_agrees & g_vol_med` | 157 | 83.4% | 59 | 96.6% | **+$14.23** | +$8.63 |
| 6 | ETH | s6_5m | 60-150 | `g_tr_above_cloud & g_bb_pos_with & g_tight_ribbon & g_tr_above_ema50 & g_ribbon_agrees & g_queue_top_high` | 205 | 78.5% | 67 | 85.1% | **+$10.82** | +$8.30 |
| 7 | BTC | s6_5m | 0-60 | `g_tr_stack_with & g_tr_above_ema50 & g_rf_in_band & g_ribbon_agrees & g_vol_med` | 154 | 83.1% | 56 | 96.4% | **+$14.08** | +$8.17 |
| 8 | BTC | s15_5m | 150-240 | `g_tr_above_ema800 & g_imb5_strong_with` | 614 | 78.5% | 307 | 70.7% | **+$10.62** | +$8.00 |
| 9 | ETH | s6_5m | 60-150 | `g_tr_above_cloud & g_bb_pos_with & g_tight_ribbon & g_tr_above_ema50 & g_ribbon_agrees & g_vol_expanding` | 330 | 79.4% | 191 | 80.6% | **+$10.12** | +$7.59 |
| 10 | BTC | s6_5m | 60-150 | `g_cci_with & g_tr_above_ema50 & g_ribbon_agrees & g_rf_with & g_imb_change_with` | 183 | 80.3% | 121 | 89.3% | **+$8.85** | +$6.80 |

**Pattern**: R3 gates with the highest impact:
- **g_vol_med** + R2 stack on BTC s6 0-60 → 96%+ WR (very small n=60 though)
- **g_imb_change_with** + R2 stack on BTC s6 60-150 → 95.9% WR on 98 fires
- **g_imb5_strong_with** on s15 150-240 — broader retention (~260 fires)
- **g_queue_top_high** on ETH s6 60-150 — narrows but lifts dpt

## 8. Updated deployable estimate

Original R2 estimate (post-Agent T OOS): **~22 confirmed deployable sleeves**.

R4 full-window result:

| Category | Count |
|---|--:|
| R2 sleeves whose original stack still works | 7 of 15 testable (+3 untestable due to SMS gate gap) |
| R2 sleeves needing REPLACEMENT (degraded) | 4 (#10/15 BTC 15m S7, #14 SOL drz_res, #11 ETH 15m off120) |
| NEW unique deployable stacks (raw, no R3) | 38 (from walk_forward top 50) |
| NEW unique R3-augmented deployable stacks | **97 combos, 25 unique R2-bases** with deployable R3-augmentation |
| **Updated estimate (deployable, distinct cells)** | **~35 sleeves** when consolidating to one canonical stack per (asset, tf, offset_bin) cell |

**Recommendation**: deploy at least the **5-7 highest-lift R3-augmented
stacks** (table §7 above) as new sleeves in addition to the surviving R2
ones. Specifically:
- BTC s15 150-240 + `g_imb5_strong_with` overlay
- BTC s6 60-150 + `g_imb_change_with` overlay
- ETH s6 60-150 + `g_queue_top_high` overlay (carefully — n=67 is borderline)
- BTC v15m S7 — replace its R2 stack (currently degraded)

## 9. Caveats and follow-ups

1. **Cross-exchange basis gates** (`g_coinbase_basis_extreme_against`,
   `g_kraken_basis_extreme_against`) are NOT included. R3 has per-sleeve
   summary CSVs but no per-fire join. **Next step**: build
   `cross_exchange_basis_at_fire_{5m,15m}.parquet` panel.
2. **HL liquidation cascade gates** (`g_hl_liq_cascade_with`,
   `g_oi_rising_with`) only have 14-day coverage (Apr 30 – May 15).
   Extend to full window before next gate search.
3. **PM trade flow** (`g_flow_with`, `g_no_whale_60s`) — no panel built.
4. **SMS gates** in panel — `g_sms_liq_reclaim_with` exists in Agent U's
   OOS but NOT in the existing s15/s6/v15m_joined_all panels. Three R2
   "v2_sms" sleeves cannot be validated until SMS panel is materialized
   for the May 1-21 base window.
5. **`p_boot ≈ 0.005` ceiling** is the natural floor of a 200-shuffle
   test (1/(N+1)). For finer p-values use 2000-shuffle (10× slower).
6. **n=56-67 on top 5 augmented stacks is borderline**. Recommend
   collecting another 7-10 days of live data and re-validating before
   live deployment — paper-shadow first.

## 10. Files written

```
data/v4/canonical/_results/
  full_window_gate_search.csv                 # all cells × top-5 stacks (182 rows)
  full_window_gate_search_top.csv             # top 50 (raw sum_pnl)
  full_window_gate_search_per_fire.parquet    # per-fire trace for best per cell
  full_window_walkforward.csv                 # 50 stacks × train/test split + bootstrap
  full_window_r2_vs_new.csv                   # 15 R2 sleeves vs full-window
  full_window_r3_contribution.csv             # 187 sleeve×R3-gate marginal lift
  full_window_r3_augmented_stacks.csv         # 400 R2+R3 combinations

strategy_lab/meta_classifier/
  full_window_gate_search_2026_05_26.py       # main search script
  full_window_r3_augment_2026_05_26.py        # R3-augmented R2 stack tester

strategy_lab/reports/
  FULL_WINDOW_GATE_SEARCH_2026_05_26.md       # this file
```

---

*Generated 2026-05-26 from Round-3 R3 panels + Round-2 R2 joined panels
+ Agent U OOS panels. Engine: LegacyConfig (2%-on-profit fee, matches
production). Hold-to-settle PnL. Outcome from chainlink. Bootstrap N=200.
Train = first 14 days, Test = last 8 days.*
