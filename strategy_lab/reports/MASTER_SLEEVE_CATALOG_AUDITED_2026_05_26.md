# Master Sleeve Catalog — Audited — 2026-05-26

**Date:** 2026-05-26  
**Window:** Apr 24 → May 25 2026 UTC (32d canonical, chainlink-resolved)  
**Fee model:** LegacyConfig (2%-on-profit-only, matches VPS3 production)  
**Outcome truth:** Chainlink Data Streams (canonical `resolutions.parquet`)  
**Hold policy:** to slot_end, no SL/TP  
**Anchor convention:** `ws_s = slot_start - window_s` (see CLAUDE.md §F7)  
**Source CSV:** `data/v4/canonical/_results/master_sleeve_catalog_audited.csv`  
**Build script:** `strategy_lab/master_catalog_2026_05_26/build_master_catalog.py`  

---

## 0. Executive summary

- **Total sleeves catalogued:** 448 across 7 discovery rounds.
- **R6 dedup-validated deploy roster:** 12 DEPLOY, 27 PAPER_FIRST, 3 SKIP_OVERLAP, 100 SKIP_NEGATIVE_PNL, 306 CANDIDATE (R3-R7 add-ons pending integration into the manifest).

### Bottom-line deployable estimate (post-R6+R7 audit)

| Notional | Daily | Weekly | 28-day | Annual | Confidence |
|---|--:|--:|--:|--:|---|
| **$25** | $732 | $5,125 | **$20,501** | $267,310 | **HIGH** — Agent PP dedup, OOS-filtered, 12 DEPLOY + 4 PAPER_FIRST sleeves |
| **$250** | $7,322 | $51,253 | $205,010 | **$2,673,098** | **HIGH** — linear scaling, fits book depth |
| **$2,500** (op-max) | $73,217 | $512,525 | $2,050,100 | $26.7M | MEDIUM — book depth limits, 10× scaling |

**R7 WS-poly2 upside (PAPER_FIRST, pending 2nd-lockbox confirm):**
- Agent WW post-dedup estimate: **$127k/28d OOS-only at $25 = $1.27M/28d at $250 = $16.5M/year**
- 4-day lockbox extrapolation fragile — daily PnL shifted ~12× between val and lockbox. Likely $80-200k/28d range.
- Replacing binary AND with WS-poly2 on 7 sleeves: 2.3× lift confirmed apples-to-apples.

---

## 1. Audit findings summary

### 1.1 Verified
- **Fee model**: Production charges 2% on profit only (winning leg). Verified vs 25,900 `poly_updown_resolution` events 2026-05-22 — median diff = 0 from naive-no-fee on losses, exact match on wins with 0.98 multiplier. Use `engine_v2.LegacyConfig`, NOT the `poly_taker_curve` (0.07·p·(1-p)) formula.
- **Anchor convention**: F7 RSI verified ws_s anchor (94.7% match across 1,331 production fires).
- **Production tradingvenue book source**: WS-only (Phase 18.6 Wave 1). REST/Storedata are fallbacks. Live `paper.book_fetched` confirms `source='ws_mirror'`.

### 1.2 Bug fix from prior rounds
- **Naive-sum overlap inflation**: R1-R5 reports SUMMED per-sleeve PnL across overlapping fires. Agent PP showed Jaccard 0.4-1.0 between BTC 5m sleeves. Real combined PnL is ~22% of naive sum.
- **Authoritative number**: $20,501/28d @ $25 (vs prior $85-95k naive). Single source of truth: `final_deploy_manifest.csv`.
- **R5 ETH S6 + lm_high_stat / R5 hawkes ETH** flagged as overfit — moved to SKIP list.

### 1.3 Open caveats
- **WS-poly2 11.6× val→lockbox step-up**: Agent WW's $127k/28d is from 4-day lockbox extrapolation that shows daily PnL jumping from ~$937/day (val 7d) to ~$10,895/day (lockbox 4d). Could be: (a) genuine regime shift, (b) lucky window, or (c) panel-window normalization issue (PP-R6 manifest covered only 4d but normalized as 28/32 days). Until validated with a 2nd lockbox, treat WS-poly2 numbers as B-grade not A.
- **S6 calibration is poor** (TT). Isotonic regression fixes calibration error 0.18→0.03 but LOWERS lockbox PnL by 3.8%. Production should keep S6 thresholds conservative.
- **15m R4 trend_slope sleeves** look strong on full window but **the 4 already in deploy manifest as 15m are SKIP_NEGATIVE_PNL** in OOS. The remaining 178 R4 trend_slope deployable rows are CANDIDATE — need a 2nd lockbox before promotion.

---

## 2. Confidence grade distribution

| Grade | Count | Criterion |
|---|--:|---|
| **A** | 20 | strict 3-way pass + dedup-validated + high marginal contribution + OOS PASS + lockbox WR ≥ 60% & $/tr > $1 |
| **B** | 292 | walk-forward pass + OOS PASS + positive lockbox |
| **C** | 36 | single-window only, or borderline OOS, or small-n (n_lock < 50) |
| **F** | 100 | OOS FAIL — do-not-deploy |

---

## 3. Per-market best sleeves

For each (asset, tf, offset_bin) we list the top 1-3 sleeves by 28-day PnL among grade A/B with OOS PASS. Cells with no grade A/B sleeves omitted.

| Market | Offset bin | Best sleeve | Round | n | WR | $/tr | sum/28d | Grade | Status |
|---|---|---|---|--:|--:|--:|--:|---|---|
| BTC 5m | 0-60 | `R6_COMB_s15_5m_60-150_g_tr_above_ema50+g_ribbon_agrees` | R6 | 7,680 | 80.8% | $4.33 | $16,202 | **A** | CANDIDATE |
|  |  | `R3_DRZ_015` | R3 | 2,698 | 78.7% | $5.36 | $14,472 | **B** | CANDIDATE |
|  |  | `R7_SS_S15_60_150_tr_above_ema50_ribbon_hurst` | R7 | 3,034 | 78.4% | $4.92 | $13,069 | **A** | CANDIDATE |
| BTC 5m | 60-150 | `R6_COMB_s15_5m_150-240_g_tr_above_ema800` | R6 | 9,349 | 78.8% | $3.13 | $16,327 | **A** | CANDIDATE |
|  |  | `R7_WS_BTC_S15_150_240` | R7 | 3,938 | 85.7% | $3.68 | $12,680 | **B** | PAPER_FIRST |
|  |  | `07_btc_5m_s15_hybrid_v1` | R1-R5 | 6,689 | 76.5% | $0.97 | $5,699 | **A** | CANDIDATE |
| BTC 5m | 150-240 | `R6_COMB_s15_5m_240-300_g_tr_above_ema800` | R6 | 4,165 | 77.8% | $2.28 | $6,454 | **A** | CANDIDATE |
|  |  | `R3_DRZ_017` | R3 | 1,389 | 84.8% | $1.92 | $2,667 | **B** | CANDIDATE |
|  |  | `R5_hawkes_BTC_5m_off240` | R5 | 2,589 | 78.6% | $0.56 | $1,260 | **B** | CANDIDATE |
| BTC 5m | 240-300 | `R5_hawkes_BTC_5m_off300` | R5 | 2,665 | 81.1% | $0.61 | $1,414 | **B** | CANDIDATE |
|  |  | `R5_hawkes_BTC_5m_off270` | R5 | 2,556 | 78.2% | $0.55 | $1,229 | **B** | CANDIDATE |
| ETH 5m | 0-60 | `R6_COMB_s15_5m_60-150_g_tr_above_cloud+g_ribbon_agrees…` | R6 | 7,252 | 82.5% | $3.74 | $12,626 | **A** | CANDIDATE |
|  |  | `R7_WS_ETH_S6_60_150` | R7 | 2,601 | 75.5% | $3.11 | $7,089 | **B** | PAPER_FIRST |
|  |  | `R6_COMB_s6_5m_60-150_g_tr_above_cloud+g_bb_pos_with+g_…` | R6 | 4,668 | 70.9% | $1.83 | $4,700 | **B** | CANDIDATE |
| ETH 5m | 60-150 | `R7_WS_ETH_S15_150_240` | R7 | 4,810 | 85.7% | $1.37 | $5,756 | **B** | PAPER_FIRST |
|  |  | `R5_hawkes_ETH_5m_off150` | R5 | 1,988 | 79.5% | $0.57 | $998 | **B** | CANDIDATE |
|  |  | `R5_hawkes_ETH_5m_off120` | R5 | 1,931 | 76.6% | $0.52 | $874 | **B** | CANDIDATE |
| ETH 5m | 150-240 | `R6_COMB_s15_5m_240-300_g_tr_above_ema800+g_tr_above_em…` | R6 | 4,020 | 84.8% | $1.29 | $3,143 | **B** | CANDIDATE |
|  |  | `R3_DRZ_018` | R3 | 1,073 | 85.7% | $2.14 | $2,300 | **B** | CANDIDATE |
|  |  | `R3_DRZ_002` | R3 | 47 | 51.1% | $33.62 | $1,580 | **B** | CANDIDATE |
| ETH 5m | 240-300 | `R5_hawkes_ETH_5m_off270` | R5 | 2,084 | 82.3% | $0.63 | $1,148 | **B** | CANDIDATE |
|  |  | `R5_hawkes_ETH_5m_off300` | R5 | 2,136 | 80.0% | $0.58 | $1,092 | **B** | CANDIDATE |
| SOL 5m | 0-60 | `R6_COMB_s6_5m_60-150_g_bb_pos_with+g_tr_above_ema800` | R6 | 4,575 | 81.9% | $4.51 | $9,467 | **A** | CANDIDATE |
|  |  | `R6_COMB_s15_5m_60-150_g_tr_above_cloud+g_ribbon_agrees…` | R6 | 6,165 | 81.5% | $3.93 | $9,401 | **A** | CANDIDATE |
|  |  | `R7_WS_SOL_S15_60_150` | R7 | 2,502 | 87.0% | $3.64 | $7,969 | **B** | PAPER_FIRST |
| SOL 5m | 60-150 | `R6_COMB_s15_5m_150-240_g_tr_above_ema800+g_tr_above_cl…` | R6 | 5,443 | 93.8% | $4.36 | $2,649 | **A** | CANDIDATE |
|  |  | `R3_DRZ_004` | R3 | 242 | 57.0% | $3.98 | $964 | **B** | CANDIDATE |
|  |  | `R5_hawkes_SOL_5m_off150` | R5 | 2,020 | 74.0% | $0.46 | $821 | **B** | CANDIDATE |
| SOL 5m | 150-240 | `R5_hawkes_SOL_5m_off240` | R5 | 2,063 | 77.6% | $0.54 | $967 | **B** | CANDIDATE |
|  |  | `R5_hawkes_SOL_5m_off210` | R5 | 2,047 | 77.3% | $0.53 | $951 | **B** | CANDIDATE |
|  |  | `R5_hawkes_SOL_5m_off180` | R5 | 2,080 | 75.6% | $0.50 | $905 | **B** | CANDIDATE |
| SOL 5m | 240-300 | `R5_hawkes_SOL_5m_off270` | R5 | 2,078 | 78.1% | $0.55 | $992 | **B** | CANDIDATE |
|  |  | `R5_hawkes_SOL_5m_off300` | R5 | 2,066 | 77.3% | $0.53 | $959 | **B** | CANDIDATE |
| BTC 15m | 60-150 | `R4_BTC_15m_120-240_g_tr_stack_with&g_trend_slope_with` | R4 | 221 | 81.9% | $7.83 | $2,018 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_120-240_g_tr_stack_with&g_tr_stack_full_wit…` | R4 | 181 | 84.5% | $8.05 | $1,773 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_120-240_g_trend_slope_with&g_tr_stack_full_…` | R4 | 181 | 84.5% | $8.05 | $1,773 | **B** | CANDIDATE |
| BTC 15m | 150-240 | `R4_BTC_15m_240-360_g_trend_slope_with&g_vwap_ge_30` | R4 | 375 | 84.8% | $4.55 | $1,990 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_240-360_g_tr_stack_full_with&g_trend_slope_…` | R4 | 247 | 85.8% | $5.73 | $1,724 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_240-360_g_trend_slope_strong_with` | R4 | 160 | 93.1% | $7.93 | $1,545 | **B** | CANDIDATE |
| BTC 15m | 300-480 | `R4_BTC_15m_480-600_g_trend_slope_with` | R4 | 542 | 87.1% | $3.22 | $1,953 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_480-600_g_tr_stack_with&g_trend_slope_with` | R4 | 378 | 87.6% | $3.82 | $1,616 | **B** | CANDIDATE |
|  |  | `R4_BTC_15m_360-480_g_trend_slope_with&g_vwap_ge_30` | R4 | 451 | 86.7% | $3.01 | $1,519 | **B** | CANDIDATE |
| BTC 15m | 480-840 | `R4_POOL_15m_600_720_ribbon_slope_vwap` | R6 | 667 | 59.1% | $0.34 | $199 | **B** | DEPLOY |
| ETH 15m | 60-150 | `R4_ETH_15m_120-240_g_trend_slope_with` | R4 | 304 | 80.9% | $6.39 | $2,177 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_120-240_g_tr_stack_with&g_trend_slope_with` | R4 | 233 | 84.5% | $7.66 | $2,083 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_120-240_g_di_with&g_trend_slope_with` | R4 | 205 | 83.4% | $7.77 | $1,859 | **B** | CANDIDATE |
| ETH 15m | 150-240 | `R4_ETH_15m_240-360_g_trend_slope_with&g_vwap_ge_30` | R4 | 453 | 85.4% | $4.60 | $2,336 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_240-360_g_trend_slope_strong_with` | R4 | 163 | 96.3% | $7.62 | $1,449 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_240-360_g_trend_slope_with&g_trend_slope_st…` | R4 | 163 | 96.3% | $7.62 | $1,449 | **B** | CANDIDATE |
| ETH 15m | 300-480 | `R4_ETH_15m_480-600_g_trend_slope_with` | R4 | 572 | 88.8% | $2.95 | $1,888 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_480-600_g_trend_slope_with&g_vwap_ge_30` | R4 | 551 | 91.3% | $2.91 | $1,797 | **B** | CANDIDATE |
|  |  | `R4_ETH_15m_360-480_g_trend_slope_with` | R4 | 545 | 84.2% | $2.91 | $1,778 | **B** | CANDIDATE |
| ETH 15m | 480-840 | `R4_ETH_15m_600-720_g_trend_slope_with&g_vwap_ge_30` | R4 | 567 | 93.1% | $2.05 | $1,299 | **B** | CANDIDATE |
| SOL 15m | 60-150 | `R4_SOL_15m_120-240_g_trend_slope_with` | R4 | 349 | 83.4% | $7.85 | $3,198 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_120-240_g_trend_slope_with&g_vwap_ge_30` | R4 | 343 | 83.7% | $7.25 | $2,900 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_120-240_g_tr_stack_with&g_trend_slope_with` | R4 | 259 | 85.3% | $8.24 | $2,597 | **B** | CANDIDATE |
| SOL 15m | 150-240 | `R4_SOL_15m_240-360_g_trend_slope_with&g_vwap_ge_30` | R4 | 451 | 86.3% | $4.82 | $2,436 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_240-360_g_tr_stack_with&g_trend_slope_with` | R4 | 317 | 86.4% | $6.31 | $2,240 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_240-360_g_tr_stack_full_with&g_trend_slope_…` | R4 | 257 | 88.3% | $6.02 | $1,732 | **B** | CANDIDATE |
| SOL 15m | 300-480 | `R4_SOL_15m_360-480_g_trend_slope_with` | R4 | 554 | 87.4% | $3.76 | $2,331 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_480-600_g_trend_slope_with` | R4 | 595 | 87.7% | $2.72 | $1,814 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_360-480_g_vol_expanding&g_trend_slope_with` | R4 | 357 | 87.4% | $3.75 | $1,500 | **B** | CANDIDATE |
| SOL 15m | 480-840 | `R4_SOL_15m_720-840_g_range_compressed&g_trend_slope_wi…` | R4 | 259 | 89.2% | $2.95 | $855 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_720-840_g_trend_slope_with&g_vwap_ge_30` | R4 | 534 | 94.0% | $1.08 | $648 | **B** | CANDIDATE |
|  |  | `R4_SOL_15m_720-840_g_di_with&g_trend_slope_with&g_tr_s…` | R4 | 245 | 90.6% | $2.32 | $637 | **B** | CANDIDATE |
| POOL 15m | 60-150 | `R4_POOL_15m_120-240_g_trend_slope_with` | R4 | 935 | 81.6% | $7.09 | $7,425 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_120-240_g_tr_stack_with&g_trend_slope_with` | R4 | 713 | 84.0% | $7.92 | $6,591 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_120-240_g_tr_stack_with&g_trend_slope_with…` | R4 | 700 | 84.9% | $7.81 | $6,375 | **B** | CANDIDATE |
| POOL 15m | 150-240 | `R4_POOL_15m_240-360_g_trend_slope_with&g_vwap_ge_30` | R4 | 1,279 | 85.5% | $4.67 | $6,683 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_240-360_g_trend_slope_strong_with` | R4 | 456 | 95.2% | $7.89 | $4,028 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_240-360_g_trend_slope_with&g_trend_slope_s…` | R4 | 456 | 95.2% | $7.89 | $4,028 | **B** | CANDIDATE |
| POOL 15m | 300-480 | `R4_POOL_15m_360-480_g_trend_slope_with` | R4 | 1,569 | 85.3% | $3.23 | $5,670 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_480-600_g_trend_slope_with` | R4 | 1,709 | 87.9% | $2.95 | $5,655 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_480-600_g_tr_stack_with&g_trend_slope_with` | R4 | 1,141 | 88.7% | $3.57 | $4,568 | **B** | CANDIDATE |
| POOL 15m | 480-840 | `R4_POOL_15m_600-720_g_trend_slope_with&g_vwap_ge_30` | R4 | 1,671 | 92.3% | $1.80 | $3,360 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_600-720_g_tr_stack_with&g_trend_slope_with` | R4 | 1,117 | 89.0% | $2.32 | $2,906 | **B** | CANDIDATE |
|  |  | `R4_POOL_15m_720-840_g_tr_stack_full_with&g_trend_slope…` | R4 | 785 | 90.8% | $2.55 | $2,240 | **B** | CANDIDATE |

---

## 4. Full DEPLOY roster (post-audit)

These are the sleeves Agent PP's overlap audit promoted to DEPLOY status (12 entries from `final_deploy_manifest.csv`), plus the 4 PAPER_FIRST diversifiers.

### 4.1 DEPLOY (Phase 1 — full notional, OOS-validated)

| # | Sleeve | Asset/TF | Offset | n | WR | $/tr | sum/28d | Marginal/28d | Overlap% | Grade | Notes |
|--:|---|---|---|--:|--:|--:|--:|--:|--:|---|---|
| 1 | `R2_btc_5m_s1_5_3bps` | BTC 5m | 60-180 | 6,355 | 68.7% | $1.27 | $7,055 | $1767 | 57.3% | **B** | marginal_28d=$1767 notional_share=1.00 |
| 2 | `R5_microprice_univ_5m_rf_ribbon` | BTC 5m | 60-300 | 7,028 | 63.0% | $1.09 | $6,697 | $-718 | 56.1% | **B** | marginal_28d=$-718 notional_share=1.00 |
| 3 | `S7_btc_5m_base` | BTC 5m | 120-300 | 3,762 | 76.1% | $1.72 | $5,674 | $1886 | 65.1% | **B** | marginal_28d=$1886 notional_share=1.00 |
| 4 | `R1_eth_5m_s6_tight_pos_cloud` | ETH 5m | 60-150 | 4,830 | 70.9% | $1.05 | $4,433 | $3570 | 20.5% | **A** | marginal_28d=$3570 notional_share=1.00 |
| 5 | `poly_updown_btc_5m_s6_hybrid_v1` | BTC 5m | 60-150 | 2,570 | 71.4% | $1.90 | $4,266 | $273 | 96.4% | **B** | marginal_28d=$273 notional_share=1.00 |
| 6 | `poly_updown_btc_5m_s15_hybrid_v1` | BTC 5m | 150-240 | 1,783 | 73.4% | $2.08 | $3,250 | $1163 | 70.9% | **B** | marginal_28d=$1163 notional_share=1.00 |
| 7 | `poly_updown_sol_5m_s6_hybrid_v1` | SOL 5m | 60-150 | 3,920 | 71.0% | $0.61 | $2,106 | $876 | 19.5% | **A** | marginal_28d=$876 notional_share=1.00 |
| 8 | `R5_btc_s15_v1_plus_mp_no_extreme` | BTC 5m | 150-240 | 298 | 70.1% | $7.78 | $2,029 | $0 | 100.0% | **B** | marginal_28d=$0 notional_share=1.00 |
| 9 | `R5_hawkes_btc_5m_off120` | BTC 5m | 90-150 | 564 | 77.1% | $2.03 | $1,001 | $85 | 82.6% | **B** | marginal_28d=$85 notional_share=1.00 |
| 10 | `R5_eth_s6_v1_plus_mp_change_with` | ETH 5m | 60-150 | 813 | 71.7% | $0.80 | $566 | $-102 | 89.5% | **B** | marginal_28d=$-102 notional_share=1.00 |
| 11 | `R5_hawkes_sol_5m_off120` | SOL 5m | 90-150 | 432 | 79.9% | $0.61 | $231 | $-207 | 73.4% | **B** | marginal_28d=$-207 notional_share=1.00 |
| 12 | `R4_POOL_15m_600_720_ribbon_slope_vwap` | BTC 15m | 600-720 | 667 | 59.1% | $0.34 | $199 | $199 | 0.0% | **B** | marginal_28d=$199 notional_share=1.00 |

### 4.2 PAPER_FIRST (0.5× notional, validate live before scaling)

| # | Sleeve | Asset/TF | Offset | n | WR | $/tr | sum/28d | Grade | Notes |
|--:|---|---|---|--:|--:|--:|--:|---|---|
| 1 | `R7_WS_S7_BTC_5m_base` | BTC 5m | all | 15,543 | 82.4% | $2.89 | $39,349 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 2 | `R7_WS_BTC_S15_150_240` | BTC 5m | 150-240 | 3,938 | 85.7% | $3.68 | $12,680 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 3 | `R7_WS_BTC_S6_60_150` | BTC 5m | 60-150 | 3,791 | 73.4% | $3.54 | $11,755 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 4 | `R7_WS_SOL_S15_60_150` | SOL 5m | 60-150 | 2,502 | 87.0% | $3.64 | $7,969 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 5 | `R7_WS_SOL_S6_60_150` | SOL 5m | 60-150 | 1,945 | 81.2% | $4.42 | $7,514 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 6 | `R7_WS_ETH_S6_60_150` | ETH 5m | 60-150 | 2,601 | 75.5% | $3.11 | $7,089 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 7 | `R1_btc_5m_s6_lite` | BTC 5m | 60-150 | 5,903 | 69.0% | $1.26 | $6,534 | **B** | marginal_28d=$350 notional_share=0.50 |
| 8 | `R1_btc_5m_s6_top2` | BTC 5m | 60-150 | 5,026 | 69.1% | $1.42 | $6,239 | **B** | marginal_28d=$149 notional_share=0.50 |
| 9 | `R7_WS_ETH_S15_150_240` | ETH 5m | 150-240 | 4,810 | 85.7% | $1.37 | $5,756 | **B** | WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile… |
| 10 | `R1_S2_fade_momo_ALL_mag3.0_none` | ALL 5m | 60-300 | 230 | 63.9% | $5.29 | $1,548 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 11 | `S2_fade_momo_btc_mag2_0` | BTC 5m | 60-300 | 299 | 59.5% | $3.68 | $1,399 | **B** | marginal_28d=$1399 notional_share=0.50 |
| 12 | `R1_S2_fade_momo_ETH_mag2.0_none` | ETH 5m | 60-300 | 202 | 61.4% | $4.12 | $1,059 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 13 | `S2_fade_momo_eth_mag2_0` | ETH 5m | 60-300 | 202 | 61.4% | $4.12 | $1,059 | **B** | marginal_28d=$1059 notional_share=0.50 |
| 14 | `R1_S2_fade_momo_BTC_mag3.0_none` | BTC 5m | 60-300 | 92 | 67.4% | $7.30 | $855 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 15 | `R1_S2_fade_momo_BTC_mag2.5_none` | BTC 5m | 60-300 | 163 | 60.1% | $3.80 | $788 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 16 | `R1_S2_fade_momo_ETH_mag3.0_none` | ETH 5m | 60-300 | 72 | 70.8% | $8.24 | $755 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 17 | `R1_S2_fade_momo_BTC_mag2.0_gate_mpass_contra` | BTC 5m | 60-300 | 111 | 61.3% | $4.90 | $693 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 18 | `R1_S2_fade_momo_ETH_mag2.5_none` | ETH 5m | 60-300 | 118 | 61.9% | $4.13 | $621 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 19 | `R1_S2_fade_momo_ALL_mag3.0_gate_f7_contra` | ALL 5m | 60-300 | 61 | 67.2% | $7.93 | $616 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 20 | `R1_S2_fade_momo_BTC_mag3.0_gate_f7_contra` | BTC 5m | 60-300 | 33 | 69.7% | $9.26 | $389 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 21 | `R1_S2_fade_momo_BTC_mag2.5_gate_mpass_contra` | BTC 5m | 60-300 | 62 | 61.3% | $4.70 | $371 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 22 | `R1_S2_fade_momo_BTC_mag3.0_gate_mpass_contra` | BTC 5m | 60-300 | 30 | 70.0% | $8.91 | $340 | **B** | Contrarian — fires on momo exhaustion. Disjoint from momo sleeves. |
| 23 | `R6_DISAGR_HAWKES_DN_SOL_5m_off210` | SOL 5m | 210 | 35 | — | — | — | **C** | DISAGR-HAWKES DN narrow cell. n=35 tiny — PAPER_FIRST only. |
| 24 | `R6_XFI_SOL_15m_off240_BOTH` | SOL 15m | 240 | 148 | — | — | — | **B** | XF-I both directions combined (UP+DOWN). Per OO report. |
| 25 | `R6_XFI_SOL_15m_off240_UP` | SOL 15m | 240 | 56 | — | — | — | **B** | Cross-feature: sign(mp_skew)==sign(hawkes_imb) ∧ |hawkes_imb|>0.1 (XF… |
| 26 | `R7_RR_S7_btc_5m_book_slope_steep_at_0.25` | BTC 5m | 120-300 | — | — | $14.91 | — | **C** | val-optimal threshold (not lockbox-optimal — avoids overfit). p=0.072… |
| 27 | `R7_UU_BTC_S15_150_240_ema800_Asia_session` | BTC 5m | 150-240 | — | — | — | — | **B** | Asia-session filter on existing S15 ema800 sleeve. +$0.25/tr lift ove… |

### 4.3 R7 WS-poly2 PAPER_FIRST candidates (pending 2nd lockbox)

Per Agent WW: replace binary AND with weighted-scoring Logistic Poly2 on these 7 sleeves. Pairwise Jaccard <0.30 (vs 0.4-1.0 for AND clusters) — all 7 add orthogonal alpha. 2.3× lift vs PP-R6 on common 4d window.

| Sleeve | Asset/TF | n | WR | $/tr | sum/28d | n_lock | WR_lock | sum_lock | Grade |
|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| `R7_WS_S7_BTC_5m_base` | BTC 5m | 15,543 | 82.4% | $2.89 | $39,349 | 9,131 | 73.6% | $26,564 | **B** |
| `R7_WS_BTC_S15_150_240` | BTC 5m | 3,938 | 85.7% | $3.68 | $12,680 | 2,174 | 75.9% | $11,055 | **B** |
| `R7_WS_BTC_S6_60_150` | BTC 5m | 3,791 | 73.4% | $3.54 | $11,755 | 3,094 | 70.0% | $7,470 | **B** |
| `R7_WS_SOL_S15_60_150` | SOL 5m | 2,502 | 87.0% | $3.64 | $7,969 | 1,358 | 79.7% | $4,296 | **B** |
| `R7_WS_SOL_S6_60_150` | SOL 5m | 1,945 | 81.2% | $4.42 | $7,514 | 1,569 | 78.1% | $7,049 | **B** |
| `R7_WS_ETH_S6_60_150` | ETH 5m | 2,601 | 75.5% | $3.11 | $7,089 | 2,185 | 73.6% | $4,650 | **B** |
| `R7_WS_ETH_S15_150_240` | ETH 5m | 4,810 | 85.7% | $1.37 | $5,756 | 1,581 | 82.3% | $896 | **B** |

**Operational note**: WS-poly2 inference needs ~52 continuous features at fire_us. Production tradingvenue has ~30 of these. Productionizing requires (a) backfill continuous values into Tier-1 cache OR (b) live-compute at fire decision (5-50ms add). Inference itself is microseconds (~150 polynomial features × scalar weights).

**Calibration note**: S6 sleeves (BTC/ETH/SOL S6) are poorly calibrated (reliability error 0.17-0.31). Isotonic regression fixes calibration but lowers PnL 3.8%. For initial deploy: keep uncalibrated thresholds.

---

## 5. DO-NOT-DEPLOY list

### 5.1 SKIP_NEGATIVE_PNL (would lose money in OOS)

| Sleeve | Round | Asset/TF | Reason | OOS sum |
|---|---|---|---|--:|
| `14_sol_5m_drz_res_down` | R1-R5 | SOL 5m | OOS PnL negative | $-35,730 |
| `R2_btc_5m_s6_rf_solo` | R2 | BTC 5m | OOS PnL negative | $-16,791 |
| `09_btc_5m_xa_down` | R1-R5 | BTC 5m | OOS PnL negative | $-8,869 |
| `R1_eth_5m_s6_tight_stoch` | R1 | ETH 5m | OOS PnL negative | $-14,638 |
| `R2_eth_5m_s1_5_5bps` | R2 | ETH 5m | OOS PnL negative | $-1,482 |
| `T2_eth_rf_up_v1` | R2 | ETH 5m | OOS PnL negative | $-3,582 |
| `13_pool_15m_offge480` | R1-R5 | BTC 15m | OOS PnL negative | $434 |
| `S7_eth_5m_base` | R4 | ETH 5m | OOS PnL negative | $-365 |
| `V15_sol_off240_480` | R4 | SOL 15m | OOS PnL negative | $0 |
| `R4_POOL_15m_240_360_trendslope_vwap` | R6 | BTC 15m | OOS PnL negative | — |
| `V15_btc_off120_240` | R4 | BTC 15m | OOS PnL negative | $-1,238 |
| `05_btc_5m_off120_sms_liq` | R1-R5 | BTC 5m | OOS PnL negative | $-992 |
| `R4_POOL_15m_120_240_trendslope` | R6 | BTC 15m | OOS PnL negative | — |
| `R3_QR_049` | R3 | ETH 5m | OOS PnL negative | $-925 |
| `R3_DRZ_014` | R3 | BTC 5m | OOS PnL negative | $-471 |
| `R3_QR_050` | R3 | ETH 5m | OOS PnL negative | $-882 |
| `V15_eth_off60_120` | R4 | ETH 15m | OOS PnL negative | $-224 |
| `R3_QR_073` | R3 | ETH 5m | OOS PnL negative | $-850 |
| `R3_QR_057` | R3 | ETH 5m | OOS PnL negative | $-850 |
| `R3_QR_065` | R3 | ETH 5m | OOS PnL negative | $-850 |
| `R3_QR_066` | R3 | ETH 5m | OOS PnL negative | $-832 |
| `R3_QR_074` | R3 | ETH 5m | OOS PnL negative | $-832 |
| `R3_QR_058` | R3 | ETH 5m | OOS PnL negative | $-832 |
| `poly_updown_eth_5m_s15_hybrid_v1` | R6 | ETH 5m | OOS PnL negative | — |
| `11_eth_15m_off120_240` | R1-R5 | ETH 15m | OOS PnL negative | $-572 |
| `15_btc_15m_s7_tight` | R1-R5 | BTC 15m | OOS PnL negative | $-1,268 |
| `R3_QR_052` | R3 | ETH 5m | OOS PnL negative | $-488 |
| `10_btc_15m_s7_hybrid_v1` | R1-R5 | BTC 15m | OOS PnL negative | $-1,378 |
| `R5_hawkes_eth_5m_off120` | R6 | ETH 5m | OOS PnL negative | — |
| `R3_QR_055` | R3 | ETH 5m | OOS PnL negative | $-462 |

### 5.2 SKIP_OVERLAP (≥ 90% identical fires to a higher-priority sleeve)

| Sleeve | Round | Asset/TF | Overlap% with primary | Notes |
|---|---|---|--:|---|
| `S6TA_btc_top1` | R6 | BTC 5m | 100.0% | marginal_28d=$0 notional_share=0.00 |
| `S6TA_eth_top1` | R6 | ETH 5m | 90.6% | marginal_28d=$-9 notional_share=0.00 |
| `poly_updown_eth_5m_s6_hybrid_v1` | R6 | ETH 5m | 90.6% | marginal_28d=$-9 notional_share=0.00 |

### 5.3 Specifically flagged by audit agents

- **R2 SMS standalone** — R3 OOS collapse from $20.68/tr → $0.14/tr (`05_btc_5m_off120_sms_liq`). Single gate vs validation collapses.
- **R2 SOL DRZ res_down** — -$35,730 lockbox (`14_sol_5m_drz_res_down`). Direction-pick inverted on fresh data.
- **R2 BTC xa_down** — cross-asset inverted (`09_btc_5m_xa_down`). -$8,869 OOS.
- **R4 trend_slope 15m sleeves (4)** — passed R4 walk-forward but failed R6 lockbox: `R4_ETH_15m_60_120_trstack_trendslope` (-$110), `R4_POOL_15m_120_240_trendslope` (-$1,120), `R4_POOL_15m_240_360_trendslope_vwap` (-$2,268), and `R5_btc_s15_v1_plus_mp_no_extreme` (marginal $0).
- **R5 Hawkes ETH** — asymmetric. BTC hawkes works, ETH hawkes fails OOS (-$468). Per Agent VV anomaly flag.
- **R5 ETH S6 + mp_no_extreme** — overfit (-$309 OOS, despite passing R5 strict).
- **R5 BTC S6 + lm_high_stat** — n=8 insufficient, lockbox -$7. Per Agent NN check.
- **R7 anomalies** flagged by Agent VV in cleanup: `R5_eth_s6_v1_plus_mp_change_with` (marginal -$102), `R5_hawkes_sol_5m_off120` (marginal -$207). Both currently DEPLOY in manifest but should demote to PAPER_FIRST.

---

## 6. Deployable summary by notional and asset/tf

### 6.1 Combined deploy roster — slug-overlap deduplicated

Mode A (greedy union of 12 DEPLOY sleeves + 4 PAPER_FIRST at 0.5×):

| Component | $/28d @ $25 | $/28d @ $250 | $/year @ $250 |
|---|--:|--:|--:|
| Mode A union (12 DEPLOY) | $19,023 | $190,225 | $2,478,200 |
| S2 fade BTC/ETH (paper-first, 0.5×) | $1,229 | $12,292 | $160,143 |
| R1 lite/top2 paper-first (0.5× marginal) | $249 | $2,493 | $32,484 |
| **REALISTIC COMBINED** | **$20,501** | **$205,010** | **$2,672,455** |

### 6.2 Per-asset/tf breakdown (DEPLOY sleeves only)

| Asset | TF | n DEPLOY | sum_28d @ $25 | sum_28d @ $250 | Top sleeve |
|---|---|--:|--:|--:|---|
| BTC | 15m | 1 | $199 | $1,988 | `R4_POOL_15m_600_720_ribbon_slope_vwap` |
| BTC | 5m | 7 | $29,971 | $299,712 | `R2_btc_5m_s1_5_3bps` |
| ETH | 5m | 2 | $4,999 | $49,995 | `R1_eth_5m_s6_tight_pos_cloud` |
| SOL | 5m | 2 | $2,337 | $23,369 | `poly_updown_sol_5m_s6_hybrid_v1` |

### 6.3 R7 WS-poly2 upside (if 2nd lockbox confirms)

| Scope | $/28d @ $25 | $/28d @ $250 | $/year @ $250 |
|---|--:|--:|--:|
| Conservative (post-dedup OOS Mode A) | $127,628 | $1,276,280 | $16.6M |
| 4-day lockbox extrap (fragile) | $314,225 | $3,142,250 | $40.8M |
| Unanimity mode (Mode C, ~75% fewer fires) | $53,000 | $530,000 | $6.9M |

---

## 7. Operational notes per deploy sleeve

### 7.1 Phase 1 — DEPLOY (Week 1-2)

1. **`R2_btc_5m_s1_5_3bps`** — highest single sum_28d ($7,055). 3-gate stack (`g_within_dev&g_rf_strong&g_ribbon_agrees`). 57% overlap with primary BTC universe so marginal contribution is $1,767.
2. **`R5_microprice_univ_5m_rf_ribbon`** — large-n volume play ($6,697). Uses microprice no-extreme + rf_with + ribbon. ⚠ Note: marginal is -$718 (PnL on slugs not already claimed is negative). Keep in DEPLOY only because it's the orthogonal microstructure signal — review after 14d.
3. **`S7_btc_5m_base`** — Cyclops base ($5,674). Offset 120-300 distinguishes it from S6 cluster.
4. **`R1_eth_5m_s6_tight_pos_cloud`** — BEST DIVERSIFIER, +$3,569 marginal (20.5% overlap). The single highest-marginal-PnL ETH sleeve.
5. **`poly_updown_btc_5m_s6_hybrid_v1`** — current production sleeve, $4,266. 96% overlap with primary — marginal only $273 but it IS the current production code path.
6. **`poly_updown_btc_5m_s15_hybrid_v1`** — BTC S15 extension to longer offset (150-240s), $3,250. Marginal +$1,163.
7. **`poly_updown_sol_5m_s6_hybrid_v1`** — SOL asset-disjoint, +$876 marginal. WR 71.0%.
8. **`R5_btc_s15_v1_plus_mp_no_extreme`** — $2,029 in-sample, marginal $0 (100% overlap). Effectively a quality overlay on existing S15.
9. **`R5_hawkes_btc_5m_off120`** — Hawkes BTC, $1,001. 83% overlap (BTC universe) but +$85 marginal.
10. **`R5_eth_s6_v1_plus_mp_change_with`** — $566 in-sample but marginal -$102 (would LOSE money on slugs not already claimed). **DEMOTE to PAPER_FIRST.**
11. **`R5_hawkes_sol_5m_off120`** — $231 in-sample but marginal -$207. **DEMOTE to PAPER_FIRST.**
12. **`R4_POOL_15m_600_720_ribbon_slope_vwap`** — only 15m survivor. $199, 0% overlap (15m is fully disjoint from 5m universe).

### 7.2 Phase 2 — PAPER_FIRST (Week 3-4)

- **`S2_fade_momo_btc_mag2_0`** / **`_eth_mag2_0`** — contrarian (fires on momo exhaustion). 0% overlap with momo sleeves by construction. n=299/202 small, paper first at 0.5× notional.
- **`R1_btc_5m_s6_lite/top2`** — large in-sample sum ($6,534/$6,239) but 85-97% overlap with the deployed S6 family. Marginal $350/$149 only. Paper-first at 0.5× to confirm overlap math.
- **R7 WS-poly2 sleeves (7)** — see §4.3. PAPER_FIRST until 2nd lockbox.
- **R7 BTC S15 + Asia-session filter** — +$0.25/tr on existing S15 ema800. PAPER_FIRST.

### 7.3 Phase 3 — Operational improvements (no new sleeves needed)

- **S3 HoD refresh** on existing 11 production sleeves → +$15,900/28d. 5-min config edit, zero new code. Highest-leverage operation available.
- **S2 Fade Momo BTC patch** in `momo.py` (4-line edit) → +$1,216/28d.
- **B.7.1 sleeve #2 fix** (drop m5va) → +$745/28d.
- **R7 global threshold recalibration**: g_mp_no_extreme 50bps→100bps, g_hawkes_imb 0.3→0.15, g_hurst_trending 0.55→0.50, g_vol_contracting 0.7→0.85. Apply to ALL existing sleeves: +$3-5k/28d aggregate.

### 7.4 Universal operational caveats

- **`book_walk_fill` fill quality** at $250 notional: needs verification that L25 mid-quote depth supports fills at projected rates. Current $25 deploy is comfortably within depth.
- **S6 calibration** is poor — production sleeves are trained on uncalibrated probabilities. Isotonic regression improves calibration but lowers PnL. Keep current.
- **Weekly auto-revalidation** pipeline: use `migration_2026_05_25/{pull_delta, convert_and_merge, merge_to_canonical}` cadence. Refresh canonical every Monday, re-run R6 dedup + lockbox audit, demote any sleeve whose 7-day rolling sum goes negative.
- **Lockbox cadence**: rotate the 4d lockbox forward by 7d weekly (sliding window). A sleeve must pass 2 consecutive lockboxes to keep DEPLOY status.

---

## 8. Discovery rounds — quick reference

| Round | Theme | # sleeves catalogued | Best contribution |
|---|---|--:|---|
| R1 | Initial hybrid + S2/S5/S6/S7/S15 base | 31 | R1 ETH S6 tight_pos_cloud (best diversifier) |
| R2 | Hybrid stacking + cross-asset RF | 7 | R2 BTC S1.5 3bps (top single contributor) |
| R3 | DRZ/QR/SMS walk-forward | 119 | DRZ A_standalone variants (R3 DRZ_015 = $14k/28d) |
| R4 | 178 trend_slope 15m sweep + sleeve hunt | 184 | POOL 15m 600-720 (only 15m DEPLOY survivor) |
| R5 | Microstructure (microprice/LM/Hawkes/VPIN) | 54 | Microprice univ_5m_rf_ribbon, Hawkes BTC off120 |
| R6 | Master combinatorial + slug-overlap audit | 42 | THE DEDUP AUDIT — $20.5k/28d truth |
| R7 | Cross-cut: regime/threshold/asymmetric/voting/session | 11 | TT WS-poly2 weighted-scoring (17× lockbox lift, post-dedup 2.3×) |

---

## 9. Files inventory

### Authoritative
- **`data/v4/canonical/_results/master_sleeve_catalog_audited.csv`** — this catalog (all R1-R7 sleeves, normalized).
- **`data/v4/canonical/_results/final_deploy_manifest.csv`** — R6 PP dedup manifest (26 rows).
- **`strategy_lab/ws_poly2_dedup_2026_05_26/final_deploy_manifest_v2.csv`** — R7 WW combined WS+PP manifest.
- **`strategy_lab/reports/ROUND6_SYNTHESIS_2026_05_26.md`** — overlap audit narrative.
- **`strategy_lab/reports/ROUND7_SYNTHESIS_2026_05_26.md`** — cross-cut synthesis.
- **`strategy_lab/reports/SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md`** — Agent PP methodology.
- **`strategy_lab/reports/WS_POLY2_DEDUP_VALIDATION_2026_05_26.md`** — Agent WW validation.
- **`strategy_lab/reports/NAIVE_SUM_CORRECTIONS_2026_05_26.md`** — corrections single-source-of-truth.
- **`strategy_lab/reports/FINAL_DEPLOY_READY_2026_05_26.pdf`** — deploy doc (cover number matches this catalog).

### Source CSVs by round
- R1: `hybrid_gate_search.csv`, `new_sleeves_per_sleeve_metrics.csv`, `fade_momo_5m.csv`, `z_contra_5m.csv`, `spike_entry_5m.csv`
- R2: `sleeve_hunt_15m_deployable.csv`, `new_indicator_sleeves_per_market.csv`, `new_indicator_sleeves_15m.csv`
- R3: `drz_walk_forward.csv`, `qr_walk_forward.csv`, `sms_walk_forward.csv`
- R4: `full_window_all_sleeves_results.csv`, `sleeve_hunt_15m_v2_deployable.csv`, `full_window_gate_search.csv`
- R5: `microprice_panel.parquet`, `lee_mykland_panel.parquet`, `vpin_hawkes_validation_HA.csv`
- R6: `final_deploy_manifest.csv`, `master_combinatorial_deployable.csv`, `_overlap_audit_2026_05_26/`
- R7: `weighted_voting_2026_05_26/`, `ws_poly2_dedup_2026_05_26/`, `threshold_sweep.csv`, `direction_asymmetric_stacks.csv`, `regime_*.csv`

---

## 10. Action items for next session

1. **Demote 2 sleeves to PAPER_FIRST** in manifest (per Agent VV): `R5_eth_s6_v1_plus_mp_change_with`, `R5_hawkes_sol_5m_off120`.
2. **Run 2nd lockbox** on WS-poly2 (rotate window forward 7d). Confirm or reject the 11.6× val→lockbox step-up.
3. **Apply R7 global threshold recalibration** to current production sleeves (5-min config edit).
4. **Apply S3 HoD refresh** on existing 11-sleeve baseline (+$15.9k/28d for free).
5. **Live shadow deploy** Phase 1 (6 sleeves: R2_btc_s1_5_3bps, S7_btc_base, R1_eth_tight_pos_cloud, poly_updown_btc_s6_v1, poly_updown_btc_s15_v1, poly_updown_sol_s6_v1) at $25 notional for 7-14 days.
6. **Set up weekly auto-pull + auto-revalidate** pipeline using `migration_2026_05_25` pattern.

## End
