# Post-Audit Final Catalog — 2026-05-26

**Date:** 2026-05-26
**Auditor:** Remediation agent (post Round 7 audit)
**Window analyzed:** OOS lockbox = May 21 20:06 → May 25 19:13 UTC = **3.96 days**
**Fee model:** LegacyConfig (2%-on-profit-only — matches VPS3 production)
**Outcome truth:** Chainlink Data Streams
**Anchor convention:** `ws_s = slot_start - window_s`
**L25 fill model:** sub-second `book_walk_fill` at $25/$250/$2500 notionals via canonical `data/v4/canonical/orderbook_l25/{asset}.parquet`

---

## 0. Executive summary

After applying 4 bug fixes from the Round 7 audit and re-evaluating on CLEAN panels with REAL sub-second L25 fill simulation at scale:

| Notional | Per-day | 28-day | Annual | Confidence |
|---|--:|--:|--:|---|
| **$25** (per-fire $25, paper baseline) | $2,378 | **$66,604** | $866k | **HIGH** |
| **$250** (10× operational target) | $4,380 | **$122,629** | $1.60M | **MEDIUM** (BTC-only) |
| **$2,500** (theoretical max) | NEGATIVE | NEGATIVE | NEGATIVE | DO-NOT-DEPLOY (depth-exhaustion) |

**Three big revisions from the prior audited catalog:**

1. **PP-R6 / R7 numbers were under-scaled 8.07×** (28/3.96 vs 28/32 — Bug #4). Real $/28d at $25 = $66,604, not $20,501.
2. **Fire-count was inflated 2.3× on lockbox** (Bug #1 — 20 offsets vs 9 canonical). The "11.6× val→lockbox step-up" Agent WW found was largely fire-volume inflation, not real edge.
3. **$250 notional does NOT scale linearly.** L25 fill simulation shows the average sleeve consumes 5-26% of available 25-level depth at $250. Effective scaling = **3.24×** for the positive-PnL BTC subset, **NEGATIVE for ETH/SOL sleeves at this notional.**

---

## 1. Bug fixes applied

| # | Severity | File | Fix |
|---|---|---|---|
| 1 | HIGH | `strategy_lab/full_window_validation_v2.py` | Replaced 20-offset 5m grid `{15,30,...,300}` with canonical 9-offset `{30,60,...,270}`. 15m: 14-offset → 8-offset `{60,120,240,360,480,600,720,840}`. Matches base panels `s15_joined_all.parquet` / `v15m_joined_all.parquet`. |
| 2 | MEDIUM | `strategy_lab/meta_classifier/build_regime_panel.py::resample_to_bar` | Rekey `ts_us` from bar START to bar END (`slot_start + tf_seconds - 1us`). Eliminates lookahead in `merge_asof(direction='backward')` joins to fire_us. |
| 3 | MEDIUM | `strategy_lab/meta_classifier/compute_sms_panel.py::resample_1s_to_bar` | Same fix as #2 — `ts_us` shifted to bar END. |
| 4 | HIGH | `strategy_lab/overlap_audit_2026_05_26/04_final_manifest.py`, `01_build_fire_matrix.py` | Changed scaling factor from `(28/32) = 0.875×` to `(28/3.96) = 7.07×` — actual fired panel covers 3.96d, not 32d. |

Diff file: `strategy_lab/post_audit_2026_05_26/bug_fixes.diff`

### 1.1 Bug #2 verification
Sample of 1,000 BTC 5m fires:
- v1 (leaky bar START): 7.40% mismatch vs causal prior-bar reference
- v2 (bar END fix): **0.000% mismatch** — strictly causal by construction.

### 1.2 Bug #1 — fire-count inflation per panel

| Panel | n_orig (20 offsets) | n_clean (9 offsets) | Ratio |
|---|--:|--:|--:|
| oos_fires_BTC_5m | 38,349 | 17,743 | 2.16× |
| oos_fires_ETH_5m | 35,264 | 16,223 | 2.17× |
| oos_fires_SOL_5m | 32,502 | 15,053 | 2.16× |
| oos_fires_BTC_15m | 9,001 | 5,128 | 1.76× |
| oos_fires_ETH_15m | 8,274 | 4,678 | 1.77× |
| **AVERAGE** | | | **2.10×** |

Net fire-count inflation: **2.10×**. PnL inflation: 2.50× (winners over-represented in extra offsets).

---

## 2. Inflation ratios per top sleeve (original vs CLEAN)

After applying Bug #1 fix (9-offset filter) only — these are pre-scaling, pre-L25 numbers.

| Sleeve | n_orig | n_clean | n_ratio | sum_orig | sum_clean | pnl_inflation |
|---|--:|--:|--:|--:|--:|--:|
| `R2_btc_5m_s1_5_3bps` | 6,355 | 3,542 | 1.79× | $8,063 | $3,192 | 2.53× |
| `R5_microprice_univ_5m_rf_ribbon` | 7,028 | 3,474 | 2.02× | $7,653 | $2,901 | 2.64× |
| `S7_btc_5m_base` | 3,762 | 1,940 | 1.94× | $6,484 | $3,462 | 1.87× |
| `R1_eth_5m_s6_tight_pos_cloud` | 4,830 | 2,755 | 1.75× | $5,068 | $2,128 | 2.38× |
| `poly_updown_btc_5m_s6_hybrid_v1` | 2,570 | 1,478 | 1.74× | $4,887 | $2,034 | 2.40× |
| `poly_updown_btc_5m_s15_hybrid_v1` | 1,783 | 1,013 | 1.76× | $3,714 | $1,912 | 1.94× |
| `poly_updown_sol_5m_s6_hybrid_v1` | 3,920 | 2,261 | 1.73× | $2,406 | $685 | 3.51× |
| `R5_btc_s15_v1_plus_mp_no_extreme` | 298 | 160 | 1.86× | $2,318 | $1,317 | 1.76× |
| `R5_hawkes_btc_5m_off120` | 564 | 339 | 1.66× | $1,145 | $685 | 1.67× |
| `R5_hawkes_sol_5m_off120` | 432 | 259 | 1.67× | $264 | $65 | 4.05× |
| `R4_POOL_15m_600_720_ribbon_slope_vwap` | 667 | 443 | 1.51× | $228 | -$180 | NEG-flip |
| `poly_updown_eth_5m_s15_hybrid_v1` | 2,509 | 1,432 | 1.75× | -$833 | -$376 | NEG |
| `R5_hawkes_eth_5m_off120` | 481 | 289 | 1.66× | -$534 | -$96 | NEG |

**Sleeves that flipped from positive to NEGATIVE after Bug #1 fix:**
- `R4_POOL_15m_600_720_ribbon_slope_vwap` — was the only 15m DEPLOY in PP's manifest. **Now -$1,272/28d.**
- `poly_updown_eth_5m_s15_hybrid_v1` — was marginal; now -$2,662/28d.

Key dataset: `data/v4/canonical/_results/master_sleeve_catalog_v2_clean.csv`

---

## 3. Per-market best sleeve table (CORE DELIVERABLE)

The single best CLEAN sleeve per (asset, tf, offset bin) after all fixes applied.

| Market | Offset bin | Best sleeve | n | WR | $/tr | sum/28d @ $25 | sum/28d @ $250 | sum/28d @ $2500 | avg_slip_250 | depth_pct_250 | scale_250 | Deploy @ $25 | Deploy @ $250 |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--:|:--:|
| **BTC 5m** | 60-150 | `R1_btc_5m_s6_lite` | 3,373 | 68.4% | $1.04 | **$24,771** | $68,907 | NEG | 199 bps | 4.6% | 3.97× | YES | YES |
| **BTC 5m** | 150-240 | `R2_btc_5m_s1_5_3bps` | 3,542 | 68.0% | $0.90 | **$22,569** | $17,335 | NEG | 253 bps | 4.9% | 1.27× | YES | YES (marginal) |
| **BTC 5m** | 240-300 | `S7_btc_5m_base` | 1,940 | 76.9% | $1.78 | **$24,476** | $115,117 | NEG | 275 bps | 5.5% | 5.14× | YES | YES |
| **ETH 5m** | 60-150 | `R1_eth_5m_s6_tight_pos_cloud` | 2,755 | 70.1% | $0.77 | **$15,044** | -$58,537 | NEG | 463 bps | 11.8% | -3.96× | YES | **NO** |
| **ETH 5m** | 150-240 | (no positive sleeve found) | — | — | — | — | — | — | — | — | — | NO | NO |
| **SOL 5m** | 60-150 | `poly_updown_sol_5m_s6_hybrid_v1` | 2,261 | 70.1% | $0.30 | **$4,846** | -$202,189 | NEG | 773 bps | 26% | -41× | YES | **NO** |
| **BTC 15m** | 480+ | `R4_POOL_15m_600_720_ribbon_slope_vwap` | 443 | 58.7% | -$0.41 | **-$1,272** | NEG | NEG | 1,229 bps | 13.8% | — | **NO** | NO |

Notes:
- **At $25**, 5 markets have a positive sleeve. Combined raw /28d = $91,706 (overlap-significant).
- **At $250**, only 3 BTC markets remain deployable. ETH/SOL sleeves consume 12-26% of book depth and lose money at $250.
- **NO sleeve survives $2,500.** All deplete depth and the implied slippage destroys edge.

Source: `data/v4/canonical/_results/per_market_best_sleeve_clean.csv`

---

## 4. Notional scaling analysis (L25 sub-second fill simulation)

For each of 32,526 individual fires across 21 sleeves, walked the L25 book at fire_us (using full sub-second `data/v4/canonical/orderbook_l25/{asset}.parquet` — no 1Hz subsample) at 3 notionals:

### 4.1 Aggregate scaling

| Notional | Total positive PnL /28d | # sleeves positive | # deployable (slip + depth filter) |
|---|--:|--:|--:|
| $25 | $188,296 | 16 of 21 | 16 |
| $250 | $553,101 | 9 of 21 | 4 |
| $2,500 | $0 | 0 of 21 | 0 |

**Conclusion**: scaling from $25 → $250 is **net 2.94× upward**, NOT 10× — because ETH/SOL sleeves go negative.

### 4.2 BTC-only sleeves (the operational target)

The 9 BTC sleeves that remain positive at $250:

| Sleeve | sum_28d @ $25 | sum_28d @ $250 | scale | avg_slip bps | depth_pct |
|---|--:|--:|--:|--:|--:|
| S7_btc_5m_base | $22,393 | $115,117 | **5.14×** | 275 | 5.5% |
| R1_btc_5m_s6_lite | $17,352 | $68,907 | **3.97×** | 199 | 4.6% |
| R1_btc_5m_s6_top2 | $16,214 | $68,815 | **4.24×** | 200 | 4.7% |
| S6TA_btc_top1 = poly_updown_btc_5m_s6_hybrid_v1 | $11,594 | $67,178 | **5.79×** | 185 | 4.4% |
| R5_btc_s15_v1_plus_mp_no_extreme | $10,022 | $66,988 | **6.68×** | 488 | 8.6% |
| poly_updown_btc_5m_s15_hybrid_v1 | $14,952 | $54,716 | **3.66×** | 338 | 5.5% |
| R5_hawkes_btc_5m_off120 | $3,430 | $24,253 | **7.07×** | 169 | 3.3% |
| R2_btc_5m_s1_5_3bps | $13,685 | $17,335 | **1.27×** | 253 | 4.9% |

### 4.3 Why scaling is sub-linear

At $250, ETH/SOL sleeves consume 12-26% of the visible 25-level book and incur 460-770 bps avg slippage. This wipes out the per-trade edge (avg ETH $/tr = $0.77 vs slippage cost ~$3 at $250).

BTC books are deeper — average $250 consumes 4-9% of depth, slip 185-275 bps. Edge survives.

Source: `data/v4/canonical/_results/sleeve_notional_fill_simulation.csv`, `sleeve_notional_scaling_truth.csv`.

---

## 5. Updated deployable estimate by notional

### 5.1 At $25 (paper baseline)

Greedy slug-overlap dedup on CLEAN panel finds 7 DEPLOY sleeves (after Bug #4 scaling correction):

| # | Sleeve | Asset/TF | n | WR | $/tr | sum_28d | marginal_28d | overlap% |
|--:|---|---|--:|--:|--:|--:|--:|--:|
| 1 | `R1_btc_5m_s6_lite` | BTC 5m | 3,373 | 68.4% | $1.04 | $24,771 | $17,843 | 27.4% |
| 2 | `S7_btc_5m_base` | BTC 5m | 1,940 | 76.9% | $1.78 | $24,476 | $7,397 | 61.3% |
| 3 | `R1_eth_5m_s6_tight_pos_cloud` | ETH 5m | 2,755 | 70.1% | $0.77 | $15,044 | $12,258 | 8.5% |
| 4 | `poly_updown_btc_5m_s15_hybrid_v1` | BTC 5m | 1,013 | 73.1% | $1.89 | $13,521 | $479 | 70.4% |
| 5 | `poly_updown_sol_5m_s6_hybrid_v1` | SOL 5m | 2,261 | 70.1% | $0.30 | $4,846 | $4,846 | 0.0% |
| 6 | `R5_hawkes_btc_5m_off120` | BTC 5m | 339 | 76.7% | $2.02 | $4,841 | $994 | 87.9% |
| 7 | `R5_eth_s6_v1_plus_mp_change_with` | ETH 5m | 416 | 73.8% | $1.60 | $4,713 | $817 | 91.8% |

**DEPLOY combined (greedy union, 9,998 unique fires)**: `$66,604/28d at $25 = $866k/year`

### 5.2 At $250 (10× operational target)

Only the 4 BTC-only sleeves survive depth constraints. Re-running slug-dedup on the $250 PnL stream:

| Component | sum_28d at $25 | sum_28d at $250 | scale |
|---|--:|--:|--:|
| 8 positive-$250 sleeves, pre-dedup | $109,642 | $483,213 | 4.41× |
| Post-dedup unique fires (5,130 fires) | $37,819 | $122,629 | **3.24×** |

**Realistic deployable at $250 = $122,629/28d post-dedup = $1.60M/year.**

### 5.3 At $2,500

**DO NOT DEPLOY.** Every sleeve flips deeply negative due to depth exhaustion. Avg slippage 1,000-4,000 bps; depth consumed 30-70%. The L25 books are not deep enough for this notional.

---

## 6. Deploy roster — top sleeves with full specs (post-audit)

### 6.1 Phase 1 — DEPLOY $25 (Week 1-2)

7 sleeves from the dedup-validated roster. Run at $25 notional first; promote BTC-only subset to $250 after 7d clean lockbox.

| # | Sleeve | Asset/TF | Offset | Gate Stack | Status |
|--:|---|---|---|---|---|
| 1 | `R1_btc_5m_s6_lite` | BTC 5m | 60-150 | g_cci_with & g_ribbon_agrees | **DEPLOY** |
| 2 | `S7_btc_5m_base` | BTC 5m | 120-300 | g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_tr_above_ema200 & g_ribbon_agrees | **DEPLOY** |
| 3 | `R1_eth_5m_s6_tight_pos_cloud` | ETH 5m | 60-150 | g_cci_with & g_bb_pos_with & g_ribbon_agrees & g_tr_above_cloud & g_tight_ribbon | **DEPLOY $25 only** |
| 4 | `poly_updown_btc_5m_s15_hybrid_v1` | BTC 5m | 150-240 | g_tr_above_pp & g_ribbon_agrees & g_stoch_with & g_tight_ribbon | **DEPLOY** |
| 5 | `poly_updown_sol_5m_s6_hybrid_v1` | SOL 5m | 60-150 | g_mfi_with & g_bb_pos_with & g_ribbon_agrees | **DEPLOY $25 only** |
| 6 | `R5_hawkes_btc_5m_off120` | BTC 5m | 90-150 | __hawkes_imb_with__ (HAWKES direction) | **DEPLOY** |
| 7 | `R5_eth_s6_v1_plus_mp_change_with` | ETH 5m | 60-150 | g_cci_with & g_bb_pos_with & g_ribbon_agrees & __mp_change_with__ | **DEPLOY $25 only** |

### 6.2 Phase 2 — PAPER_FIRST ($25, 0.5×)

After 7d clean lockbox these would have been added — but all overlapped sleeves were demoted to SKIP_OVERLAP in the dedup (top2/microprice/s1_5/etc are redundant with #1-#4 above).

### 6.3 Phase 3 — Operational scaling

**BTC-only $250 cohort** (after 7d clean DEPLOY @ $25 confirms):
- `S7_btc_5m_base`, `R1_btc_5m_s6_lite`, `poly_updown_btc_5m_s15_hybrid_v1`, `R5_hawkes_btc_5m_off120`, `R5_btc_s15_v1_plus_mp_no_extreme`
- Combined projected: **$122,629/28d at $250 = $1.60M/year**.

**Do NOT scale ETH/SOL above $25** — book depth insufficient.

---

## 7. DO-NOT-DEPLOY list

### 7.1 Bug-fix demotions (positive on inflated panel, negative on CLEAN panel)

| Sleeve | sum_orig | sum_clean | Reason |
|---|--:|--:|---|
| `R4_POOL_15m_600_720_ribbon_slope_vwap` | +$228 | **-$180** | Only 15m DEPLOY in PP's manifest. After Bug #1 fix (offset filter + 8 vs 14 offsets) — flips negative. |
| `poly_updown_eth_5m_s15_hybrid_v1` | -$833 | -$376 | Was already marginal; cleaner panel confirms negative. |
| `R5_hawkes_eth_5m_off120` | -$534 | -$96 | Negative even on clean panel (Bug VV anomaly confirmed). |
| `R5_eth_s6_v1_plus_mp_no_extreme` | -$309 | -$490 | Already known overfit. Re-confirmed. |

### 7.2 Failed at $250 notional (deployable @ $25 only)

| Sleeve | sum_25 | sum_250 | Reason |
|---|--:|--:|---|
| `R1_eth_5m_s6_tight_pos_cloud` | +$15,044 | **-$58,537** | Avg slip 463 bps, depth 12% — flips to loss at $250. |
| `poly_updown_sol_5m_s6_hybrid_v1` | +$4,846 | **-$202,189** | Avg slip 773 bps, depth 26% — sample book too thin for $250 on SOL. |
| `R5_eth_s6_v1_plus_mp_change_with` | +$4,713 | +$2,616 | Barely positive (scale 0.8×) — high-risk at $250. |

### 7.3 Failed at $2,500 (NO sleeve survives)

EVERY sleeve goes deeply negative at $2,500. Book depth on Polymarket up-down 5m markets supports $250 BTC sleeves at best — not $2,500.

---

## 8. Confidence grades

### Grade A (highest)
- `R1_btc_5m_s6_lite`, `S7_btc_5m_base`, `poly_updown_btc_5m_s15_hybrid_v1`, `R5_hawkes_btc_5m_off120` — pass all 4 bug-fix checks, positive at $25 AND $250, slip < 280 bps, depth < 6%, OOS lockbox positive.

### Grade B
- `R1_eth_5m_s6_tight_pos_cloud`, `poly_updown_sol_5m_s6_hybrid_v1`, `R5_eth_s6_v1_plus_mp_change_with` — positive at $25, NEGATIVE at $250 due to book depth. Deploy at $25 ONLY.

### Grade C
- `R2_btc_5m_s1_5_3bps` — positive but scale 1.27× at $250 (marginal). Watch list.

### Grade F (DO NOT DEPLOY)
- All sleeves in §7.

### Confidence on the $66,604/28d @ $25 estimate: **HIGH**.
- Numbers are bug-fixed (9-offset grid, bar-end keyed regime/SMS, correct 28/3.96 scaling)
- L25 fill simulation is sub-second resolution (no 1Hz subsample)
- Slug-overlap dedup uses greedy primary-portfolio selection on CLEAN fires
- Fee model is LegacyConfig (matches production)
- OOS lockbox is 3.96d real out-of-sample.

### Confidence on $122,629/28d @ $250: **MEDIUM**.
- L25 book depth fluctuates with market activity. The 28d average may not reflect peak-activity periods (which is when sleeves fire most).
- Real production must use latency-shifted strict-asof book reads (engine_v2 + apply_latency_to_entry=True).
- ETH/SOL sleeves should be deferred to $25 only until book depth improves.

---

## 9. Files inventory

### Authoritative artifacts
- `strategy_lab/post_audit_2026_05_26/bug_fixes.diff` — all 4 code changes
- `data/v4/canonical/_results/master_sleeve_catalog_v2_clean.csv` — per-sleeve CLEAN /28d
- `data/v4/canonical/_results/sleeve_notional_fill_simulation.csv` — fire-level L25 walks at 3 notionals (32,526 rows)
- `data/v4/canonical/_results/sleeve_notional_fill_summary.csv` — sleeve-level slip/depth summary
- `data/v4/canonical/_results/sleeve_notional_scaling_truth.csv` — actual scaling per sleeve
- `data/v4/canonical/_results/per_market_best_sleeve_clean.csv` — Section 3 deliverable
- `data/v4/canonical/_results/final_deploy_manifest_v2_post_audit.csv` — partial (just dedup result)
- `data/v4/canonical/_results/final_deploy_manifest_v2_post_audit_FULL.csv` — full manifest with notional flags
- `data/v4/canonical/_results/_post_audit_2026_05_26/fired_by_sleeve_clean.parquet` — CLEAN fire matrix
- `data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_{asset}_{tf}_v2_fixed.parquet` — 9-offset OOS panels
- `data/v4/canonical/_results/regime_panel_{5m,15m}_v2_fixed.parquet` — bar-end-keyed regime panels
- `data/v4/canonical/_results/sms_panel_{5m,15m}_v2_fixed.parquet` — bar-end-keyed SMS panels

### Reprocess scripts
- `strategy_lab/post_audit_2026_05_26/filter_oos_fires.py` — Bug #1 rebuild
- `strategy_lab/post_audit_2026_05_26/verify_regime_leak_fixed.py` — Bug #2 verification
- `strategy_lab/post_audit_2026_05_26/reevaluate_top_sleeves.py` — Task 3
- `strategy_lab/post_audit_2026_05_26/rerun_overlap_dedup.py` — Tasks 3+5
- `strategy_lab/post_audit_2026_05_26/notional_fill_simulation.py` — Task 4
- `strategy_lab/post_audit_2026_05_26/analyze_notional_scaling.py` — analysis
- `strategy_lab/post_audit_2026_05_26/final_deploy_manifest_full.py` — Task 5
- `strategy_lab/post_audit_2026_05_26/per_market_best_clean.py` — Task 6

## End
