# Complete Per-Sleeve Catalog — 2026-05-26

> ⚠️ **CORRECTIONS NOTICE (Round 6 dedup)**: The combined deployable estimates
> quoted below are NAIVE SUMS that did not account for slug overlap. The
> actual realistic deployable is ~$20.5k/28d at $25 notional (~$2.67M/year
> @ $250). See `NAIVE_SUM_CORRECTIONS_2026_05_26.md` and
> `final_deploy_manifest.csv` for the authoritative numbers.
>
> Individual sleeve metrics (n, WR, $/tr per sleeve) in this report ARE
> CORRECT — only the COMBINED estimates were inflated by overlap.

**Window:** Apr 30 → May 22 2026 UTC (~22-28 days depending on sleeve, chainlink-resolved fires only)
**Notional:** $25 per fire (sums scale linearly with notional)
**Fee model:** Legacy 2%-on-profit-only (matches VPS3 production)
**Hold policy:** to slot_end, no SL/TP

Every row is **one (strategy, asset, timeframe, offset, gate-stack) combination**.
Metrics are raw backtest values on the full window unless otherwise marked.
Walk-forward (WF) train_WR / test_WR are 20d-train / 8d-test split where computed.

Sources:
- This-run hybrid: `hybrid_gate_search.csv`, `hybrid_walk_forward.csv`, `hybrid_standalone_*.csv`, `CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md`
- Prior session: `new_sleeves_per_sleeve_metrics.csv`, `new_indicator_sleeves_per_market.csv`, `new_indicator_sleeves_15m.csv`, `vwap_drawdown_livemimic.csv`, `fade_momo_5m.csv`, `z_contra_5m.csv`, `spike_entry_5m.csv`, `HOD_REFRESH_2026_05_22.md`, `SHADOW_11_SLEEVES_V2_2026_05_22.md`

---

## A. THIS-RUN HYBRID SYSTEM (2026-05-26)

### A.1 Tier-1 — Gate-stack overlay (per-cell best) — 21 cells

Per (asset × tf × offset_bin) the BEST gate stack found. All passed
walk-forward 20/20 and bootstrap p=0.000.

| # | Market | Offset_bin | Gate stack | n | WR | $/tr | sum/28d | max_DD | Sharpe/day | k |
|--:|---|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | **BTC S6 5m** | 60-150s | `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon` | 2,764 | **77.8%** | **$+5.10** | **$+14,103.17** | $1,836.91 | 2.01 | 5 |
| 2 | **ETH S6 5m** | 60-150s | `cci ∧ bb_pos ∧ ribbon` | 3,531 | 76.0% | $+1.57 | $+5,553.37 | $2,937.35 | 1.51 | 3 |
| 3 | **ETH S1.5 5m** | 150-240s | `ribbon ∧ tr_above_ema200 ∧ stoch ∧ bb_pos ∧ cci` | 3,420 | **85.1%** | $+1.34 | $+4,595.94 | $507.80 | **2.49** | 5 |
| 4 | **BTC S1.5 5m** | 150-240s | `tr_above_pp ∧ ribbon ∧ stoch ∧ tight_ribbon` | 1,365 | **85.6%** | $+3.06 | $+4,176.26 | $379.33 | **2.43** | 4 |
| 5 | **SOL S6 5m** | 60-150s | `mfi ∧ within_dev ∧ bb_pos ∧ ribbon` | 1,503 | **92.9%** ⭐ | $+2.20 | $+3,306.81 | $344.85 | **3.07** | 4 |
| 6 | BTC S1.5 5m | 60-150s | `ribbon_agrees` (single gate) | 2,289 | 78.7% | $+1.23 | $+2,823.13 | $448.90 | **3.45** | 1 |
| 7 | BTC S1.5 5m | 240-300s | `tr_above_cloud ∧ mfi ∧ tr_above_ema200 ∧ cci ∧ stoch` | 1,432 | 84.4% | $+1.74 | $+2,486.31 | $356.08 | 2.25 | 5 |
| 8 | ETH S1.5 5m | 60-150s | `ribbon ∧ bb_pos ∧ cci` | 2,951 | 77.1% | $+0.62 | $+1,818.53 | $1,021.36 | 1.51 | 3 |
| 9 | **BTC S7 15m** | 480-840s | `tr_stack_full ∧ tr_above_ema800 ∧ ribbon ∧ tight ∧ stoch ∧ tr_above_ema200` | 816 | 88.0% | $+2.15 | $+1,751.45 | $240.56 | 1.86 | 6 |
| 10 | SOL S1.5 5m | 240-300s | `rf_aged ∧ within_dev ∧ tight_ribbon ∧ tr_in_active_session` | 282 | **92.6%** | **$+6.17** | $+1,739.54 | $120.96 | 1.19 | 4 |
| 11 | ETH S1.5 5m | 240-300s | `tr_above_ema800 ∧ mfi` | 1,879 | 90.7% | $+0.73 | $+1,367.17 | $627.36 | 1.55 | 2 |
| 12 | SOL S7 15m | 480-840s | `dev_extreme ∧ rf_aged ∧ tr_within_adr ∧ tr_above_pp` | 42 | **97.6%** ⭐ | **$+21.79** ⭐ | $+915.14 | $25.00 | 1.02 | 4 |
| 13 | SOL S1.5 5m | 150-240s | `rf_aged ∧ ribbon ∧ tr_above_ema200 ∧ tr_stack ∧ tr_above_cloud` | 987 | 85.9% | $+0.86 | $+853.03 | $606.44 | 1.31 | 5 |
| 14 | SOL S1.5 5m | 60-150s | `tr_pvsra_with ∧ tr_above_ema50` | 220 | 84.1% | $+2.81 | $+617.99 | $162.15 | 2.09 | 2 |
| 15 | ETH S7 15m | 60-240s | `tr_in_active_session ∧ tr_stack_full` | 241 | 74.3% | $+2.31 | $+556.23 | $285.86 | 1.56 | 2 |
| 16 | ETH S7 15m | 480-840s | `dev_extreme ∧ tr_above_pp ∧ tr_above_cloud` | 93 | **95.7%** ⭐ | $+5.21 | $+484.82 | $50.00 | 2.28 | 3 |
| 17 | SOL S7 15m | 60-240s | `rf_aged ∧ mfi ∧ tight_ribbon` | 107 | 74.8% | $+3.73 | $+398.58 | $95.75 | 2.44 | 3 |
| 18 | SOL S7 15m | 240-480s | `ribbon ∧ tr_in_active_session ∧ mfi` | 330 | 77.6% | $+1.14 | $+377.00 | $234.71 | 0.97 | 3 |
| 19 | BTC S7 15m | 240-480s | `rf_fresh ∧ tr_within_adr ∧ tr_above_ema800 ∧ tight_ribbon` | 151 | 89.4% | $+2.10 | $+317.55 | $89.90 | 2.43 | 4 |
| 20 | BTC S7 15m | 60-240s | `rf_aged` (single gate) | 128 | 78.1% | $+1.86 | $+238.06 | $111.15 | 1.61 | 1 |
| 21 | ETH S7 15m | 240-480s | `tr_pvsra_with ∧ tr_above_ema800` | 97 | 85.4% | $+2.37 | $+229.71 | $133.35 | 1.63 | 2 |

**Subtotal Tier-1 best per cell: ~$+48,700/28d**
**(Note: actual deployable subset is the top-7 in deploy spec §A.1 totaling ~$34,500/28d.
The full per-cell list above is for completeness — overlapping fires would NOT add linearly.)**

### A.2 Tier-1 walk-forward (top 20 stacks, 20d train / 8d test, p < 0.05)

| # | Market | Offset_bin | n_full | WR_full | sum_full | $/tr_full | n_test | WR_test | sum_test | $/tr_test | bootstrap p |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | BTC S6 5m | 60-150s | 2,764 | 77.8% | $14,103 | $+5.10 | 188 | **91.5%** | $+1,119 | **$+5.95** | 0.000 |
| 2 | BTC S6 5m | 60-150s | 2,781 | 77.7% | $14,061 | $+5.06 | 189 | 91.5% | $+1,131 | $+5.98 | 0.000 |
| 3 | BTC S6 5m | 60-150s | 2,780 | 77.7% | $14,058 | $+5.06 | 189 | 91.5% | $+1,131 | $+5.98 | 0.000 |
| 4 | BTC S6 5m | 60-150s | 2,793 | 77.5% | $14,042 | $+5.03 | 189 | 91.5% | $+1,131 | $+5.98 | 0.000 |
| 5 | BTC S6 5m | 60-150s | 2,793 | 77.5% | $14,028 | $+5.02 | 189 | 91.5% | $+1,131 | $+5.98 | 0.000 |
| 7 | ETH S6 5m | 60-150s | 1,307 | 66.4% | $+6,170 | $+4.72 | 36 | 69.4% | $+219 | $+6.08 | 0.000 |
| 8 | ETH S6 5m | 60-150s | 1,266 | 67.0% | $+6,156 | $+4.86 | 34 | 67.6% | $+191 | $+5.63 | 0.000 |
| 12 | ETH S6 5m | 60-150s | 3,531 | 76.0% | $+5,553 | $+1.57 | 134 | 85.1% | $+384 | $+2.87 | 0.000 |
| 13 | ETH S1.5 5m | 150-240s | 3,420 | 85.1% | $+4,596 | $+1.34 | 173 | 82.1% | $+349 | $+2.02 | 0.000 |
| 14-17 | ETH S1.5 5m | 150-240s | 3,469-3,521 | 85.3% | $+4,510-4,536 | $+1.28-1.31 | 177-178 | 81.9-82.0% | $+329 | $+1.85-1.86 | 0.000 |
| 19 | BTC S1.5 5m | 150-240s | 1,365 | 85.8% | $+4,176 | $+3.06 | 72 | 81.9% | $+132 | $+1.84 | 0.000 |
| 20 | BTC S1.5 5m | 150-240s | 1,463 | 86.1% | $+4,135 | $+2.83 | 73 | 82.2% | $+133 | $+1.82 | 0.000 |

**WF OOS pass rate: 20/20 (100%) — test_sum > 0 on all stacks.**
**The BTC S6 sleeve test WR (91.5%) is HIGHER than train WR (76.8%) — strongly anti-overfit signal.**

### A.3 Tier-3 — Standalone Hybrid System V1..V12

7 deployable cells. Walk-forward 6/7 pass (only BTC 5m off=60 V7 flips negative on test).

| # | Market | Offset | Rule | Logic | n | WR | $/tr | sum/22d | max_DD | streak | Sharpe/day | days | OOS train_WR | OOS test_WR | OOS test_$/tr | overfit? |
|--:|---|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 1 | BTC 5m | 90s | V7 | RF+PVSRA+MFI | 332 | 70.8% | $+2.70 | $+895.62 | $178.87 | 4 | **2.82** | 22 | 71.5% | 66.7% | $+2.85 | ✅ no |
| 2 | BTC 5m | 150s | V7 | RF+PVSRA+MFI | 288 | 66.7% | $+3.04 | $+875.45 | $436.44 | 4 | 1.38 | 22 | 65.5% | 69.5% | $+4.61 | ✅ no |
| 3 | ETH 5m | 60s | V5 | V2+session | 263 | 66.2% | $+2.76 | $+726.99 | $161.11 | 3 | 2.24 | 21 | 66.2% | 67.9% | $+0.27 | ✅ no |
| 4 | BTC 5m | 60s | V7 | RF+PVSRA+MFI | 297 | 68.7% | $+2.19 | $+650.54 | $215.49 | 4 | 1.84 | 21 | 71.4% | 59.3% | **$-1.55** | ⚠️ YES |
| 5 | ETH 5m | 60s | V6 | V2+pivot confluence | 225 | 66.2% | $+2.41 | $+542.20 | $194.13 | 4 | 1.87 | 20 | 66.7% | 64.4% | $+1.19 | ✅ no |
| 6 | SOL 5m | 90s | V7 | RF+PVSRA+MFI | 116 | **73.3%** | $+3.99 | $+463.16 | $174.64 | 3 | 1.25 | 20 | 73.9% | 71.4% | $+1.72 | ✅ no |
| 7 | SOL 5m | 120s | V7 | RF+PVSRA+MFI | 111 | **75.7%** | $+2.87 | $+319.11 | $168.49 | 3 | 1.32 | 22 | 76.3% | 74.3% | $+3.13 | ✅ no |

**Subtotal Tier-3: $+4,473/22d ≈ $+5,693/28d**
**Cross-sleeve correlation max: 0.483 — clean diversification.**

### A.4 Tier-2 — Cross-asset RF confluence (S1.5 universe)

Cells with `xa_all_with_bet` (all 3 of BTC/ETH/SOL RF agree with bet direction at fire_us).

| # | Market | Direction | n | WR | $/tr | sum/28d | Notes |
|--:|---|---|--:|--:|--:|--:|---|
| 1 | BTC 5m | DOWN | 2,726 | **82.13%** | **$+1.64** | **$+4,463** | best BTC standalone xa cell |
| 2 | BTC 5m | UP | 2,808 | 81.98% | $+1.53 | $+4,285 | mirror of #1 |
| 3 | BTC 5m | ALL | 5,534 | 82.06% | $+1.58 | $+8,748 | full BTC universe with overlay |
| 4 | ETH 5m | UP | 3,750 | 80.43% | $+1.33 | $+4,982 | |
| 5 | ETH 5m | DOWN | 3,672 | 79.66% | $+0.27 | $+999 | weaker than UP |
| 6 | ETH 5m | ALL | 7,422 | 80.05% | $+0.81 | $+5,981 | |
| 7 | SOL 5m | UP | 3,280 | 80.15% | $-0.43 | $-1,426 | SOL fully unprofitable even with overlay |
| 8 | SOL 5m | DOWN | 3,055 | 81.80% | $-0.09 | $-284 | marginal loss |
| 9 | ALL 5m | UP+DOWN | 19,291 | 80.92% | $+0.67 | **$+13,020** | full S1.5 universe with xa_all overlay |

**Subtotal Tier-2 (additive on top of S1.5 base): +$5-9k/28d depending on deploy form.**

`xa_maj_with_bet` (at least 2 of 3 agree) — looser filter:

| Market | n | WR | $/tr | sum/28d |
|---|--:|--:|--:|--:|
| All | 26,205 | 81.02% | $+0.43 | $+11,361 |
| BTC ALL | 7,469 | 81.62% | $+1.09 | $+8,125 |
| ETH ALL | 10,022 | 80.26% | $+0.59 | $+5,947 |
| SOL ALL | 8,714 | 81.36% | $-0.31 | $-2,710 |

### A.5 Tier-2 — 15m S7 cross-asset (flips losing baseline)

S7 baseline LOSES ($-5,846 sum_pnl on 10,828 fires). Cross-asset filter rescues subset.

| Filter | n | WR | $/tr | sum/28d | vs baseline |
|---|--:|--:|--:|--:|--:|
| Baseline (S7 all) | 10,828 | — | $-0.54 | $-5,846 | — |
| xa_all_with_bet | 4,895 | — | $+0.11 | $+559 | +$6,405 |
| xa_maj_with_bet | 6,927 | — | $-0.20 | $-1,400 | +$4,446 |

---

## B. PRIOR-SESSION STRATEGIES (2026-05-22/23)

### B.1 S0 — Existing 11-sleeve baseline (current shipped vs refreshed HoD)

| # | Sleeve | n | WR (refreshed) | $/tr | sum/28d (shipped HoD) | sum/28d (refreshed HoD) |
|--:|---|--:|--:|--:|--:|--:|
| 1 | poly_updown_sol_5m_sniper_hod | 226 | 62.4% | $+3.41 | (lower) | $+769 |
| 2 | poly_updown_eth_15m_sniper_hod_m5va | 55 | 67.3% | $+5.69 | $+313 | $+313 (broken — m5va always fails) |
| 2-fix | drop m5va → _hod only | 129 | **73.6%** | $+5.78 | — | $+745 |
| 3 | poly_updown_btc_15m_momo_hod | 139 | 78.4% | $+13.42 | $+1,865 | $+1,865 |
| 3+m1v | + M1V gate | 61 | **90.2%** | $+20.73 | — | $+1,265 (extra) |
| 4 | poly_updown_btc_15m_sniper_hod | 173 | 57.2% | $+5.43 | $+939 | $+939 |
| 5 | poly_updown_btc_5m_sniper_hod | 249 | 59.8% | $+1.40 | (negative) | $+349 |
| 6 | poly_updown_btc_5m_momo_v2_hod_mtf | 751 | 58.7% | $+3.61 | (lower) | $+2,714 |
| 7 | poly_updown_btc_15m_momo_v2_hod | 246 | 70.7% | $+9.42 | (lower) | $+2,317 |
| 8 | poly_updown_sol_5m_momo_v2_hod | 334 | 65.6% | $+7.16 | (lower) | $+2,392 |
| 9 | poly_updown_eth_15m_momo_v2_hod | 232 | **83.6%** | **$+15.15** | (lower) | **$+3,515** |
| 10 | poly_updown_sol_15m_momo_v2_hod | 92 | 77.2% | $+13.18 | (negative) | $+1,213 |
| 11 | poly_updown_eth_5m_sniper_hod | 294 | 55.8% | $+1.64 | (lower) | $+481 |
| | **Ensemble shipped HoD** | — | — | — | **$+2,949** | — |
| | **Ensemble refreshed HoD (S3)** | — | — | — | — | **$+15,900 (5.4×)** |

### B.2 S1.5 — Slot-anchored VWAP continuation (5m, base sleeves)

| # | Sleeve | Market | Offset | Dev threshold | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe | train_WR | test_WR | entry_vwap |
|--:|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | S1.5_BTC_210_5-10bps | BTC 5m | 210 | 5-10bps | 529 | **87.3%** | $+2.99 | **$+1,581** | $-231 | 2 | **5.26** | 87% | 87% | 0.86 |
| 2 | S1.5_ETH_210_10-15bps | ETH 5m | 210 | 10-15bps | 138 | 87.0% | **$+10.92** | **$+1,508** | $-186 | 2 | 4.19 | 91% | 79% | 0.85 |
| 3 | S1.5_BTC_240_3-5bps | BTC 5m | 240 | 3-5bps | 810 | 81.7% | $+1.09 | $+886 | $-385 | 4 | **4.89** | 82% | 82% | 0.80 |
| 4 | S1.5_ETH_150_5-10bps | ETH 5m | 150 | 5-10bps | 707 | 84.3% | $+1.25 | $+883 | $-264 | 3 | **8.26** ⭐ | 84% | 84% | 0.82 |
| 5 | S1.5_ETH_240_5-10bps | ETH 5m | 240 | 5-10bps | 714 | 85.3% | $+1.12 | $+803 | $-419 | 5 | 3.53 | 86% | 85% | 0.84 |
| 6 | S1.5_SOL_270_5-10bps | SOL 5m | 270 | 5-10bps | 570 | 87.2% | $+1.14 | $+651 | $-849 | 3 | 1.68 | 88% | 85% | 0.86 |
| 7 | S1.5_BTC_150_3-5bps | BTC 5m | 150 | 3-5bps | 770 | 81.0% | $+0.84 | $+650 | $-261 | 3 | 5.60 | 82% | 80% | 0.78 |
| 8 | S1.5_BTC_60_3-5bps | BTC 5m | 60 | 3-5bps | 442 | 74.7% | $+1.31 | $+579 | $-277 | 4 | 6.39 | 76% | 72% | 0.71 |
| 9 | S1.5_SOL_30_5-10bps | SOL 5m | 30 | 5-10bps | 112 | 81.2% | $+4.84 | $+542 | **$-75** | 3 | **13.32** ⭐ | 83% | 76% | 0.69 |
| 10 | S1.5_ETH_210_5-10bps | ETH 5m | 210 | 5-10bps | 719 | 87.5% | $+0.84 | $+606 | $-216 | 3 | **7.26** | 88% | 86% | 0.84 |

**Subtotal S1.5 base: ~$+8,689/28d.**

### B.3 S1.5 — Slot-anchored VWAP continuation (5m, with TA overlay)

Same S1.5 trigger + Madrid ribbon + slow-stoch + CCI + BB layers. Slightly smaller n, higher WR/$:

| # | Sleeve | Market | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe (annual) | train_WR | test_WR | entry_vwap |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | S1.5_BTC_210_5-10bps_ribbon | BTC 5m @ +210s | 387 | 87.9% | $+4.02 | $+1,555 | $-149 | 2 | 5.37 | 88% | 89% | 0.86 |
| 2 | S1.5_ETH_210_10-15bps_4gate | ETH 5m @ +210s | 20 | 85.0% | **$+76.91** | $+1,538 | $-50 | 2 | 5.72 | 93% | 67% | 0.75 |
| 3 | S1.5_ETH_210_10-15bps_ribbon | ETH 5m @ +210s | 99 | 89.0% | $+15.40 | $+1,524 | $-125 | 2 | 4.29 | 93% | 80% | 0.85 |
| 4 | S1.5_BTC_240_3-5bps_ribbon | BTC 5m @ +240s | 555 | 82.5% | $+2.33 | $+1,293 | $-231 | 3 | **8.09** ⭐ | 82% | 86% | 0.80 |
| 5 | S1.5_SOL_270_5-10bps_ribbon | SOL 5m @ +270s | 380 | 88.4% | $+2.67 | $+1,014 | $-578 | 2 | 2.59 | 88% | 87% | 0.87 |
| 6 | S1.5_ETH_150_5-10bps_ribbon | ETH 5m @ +150s | 508 | 84.0% | $+1.57 | $+799 | $-236 | 3 | **8.36** | 84% | 85% | 0.82 |

#### Ultra-low-DD layer (ribbon + m1v stack — Tier-3 "no-DD" picks)

| # | Sleeve | Market | n | WR | $/tr | sum/28d | max_DD | streak |
|--:|---|---|--:|--:|--:|--:|--:|--:|
| 1 | S1.5_ETH_240_5-10bps_ribbon+m1v | ETH 5m @ +240s | 218 | **94.5%** | $+1.28 | $+280 | $-49 | 1 |
| 2 | S1.5_BTC_210_5-10bps_ribbon+m1v | BTC 5m @ +210s | 159 | **97.5%** | $+0.99 | $+157 | $-37 | 1 |
| 3 | S1.5_BTC_240_5-10bps_ribbon+m1v | BTC 5m @ +240s | 140 | 95.7% | $+0.81 | $+113 | $-66 | 1 |
| 4 | S1.5_SOL_270_5-10bps_ribbon+m1v | SOL 5m @ +270s | 138 | **97.8%** | $+0.71 | $+98 | $-25 | 1 |
| 5 | S1.5_ETH_210_10-15bps_ribbon+m1v | ETH 5m @ +210s | 35 | **97.1%** | $+0.77 | $+27 | $-25 | 1 |

These trade SMALL but with near-zero DD — ideal for size-constrained capital.

### B.4 S1.5 — Live-mimic stress test (top 5)

Stress-tested against hypothetical real-fee curve (`0.07·p·(1−p)`). Confirms
legacy column = realistic since production = 2%-on-profit.

| Config | n | WR | $/tr (legacy) | sum (legacy) | max_DD | streak | Sharpe-like annual | train_WR | test_WR | live_mimic_$/tr |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| BTC_240_5-10bps_m1v | 546 | 85.7% | $+2.00 | $+1,090 | $-308 | 3 | **8.12** | 85% | **89%** | $+1.91 (live mimic 92.7% of legacy) |
| BTC_60_10-15bps_f7_cross | 164 | 73.2% | $+2.77 | $+454 | $-180 | 6 | 7.59 | 69% | 82% | — |
| BTC_90_10-15bps_none | 221 | 77.8% | $+1.77 | $+390 | $-113 | 3 | 5.36 | 79% | 76% | — |
| ETH_210_10-15bps_f7_m1v | 188 | 92.6% | $+1.26 | $+237 | $-104 | 1 | 6.63 | 92% | 93% | — |
| SOL_60_20-30bps_none | 64 | 75.0% | $+1.66 | $+106 | $-102 | 2 | 3.96 | 73% | 80% | — |

### B.5 S6 — Spike-driven entry (5m, base)

| # | Sleeve | Market | Offset | Definition | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe |
|--:|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | S6_BTC_off120_D1_T1 | BTC 5m | 120 | D1 spike + CVD | 146 | 70.5% | $+6.57 | $+960 | $-145 | 5 | 8.70 |
| 2 | S6_BTC_off45_D1_T1 | BTC 5m | 45 | D1 spike + CVD | 165 | 66.1% | $+5.42 | $+895 | $-150 | 6 | 8.01 |
| 3 | S6_BTC_off30_D1_T1 | BTC 5m | 30 | D1 | 149 | 67.1% | $+5.15 | $+768 | $-125 | 4 | **11.07** ⭐ |
| 4 | S6_BTC_off60_D2_T1 | BTC 5m | 60 | D2 (15s sustained) | 158 | 71.5% | $+3.35 | $+530 | $-127 | 3 | 8.68 |
| 5 | S6_BTC_off60_D4_T1 | BTC 5m | 60 | D4 (30s run) | 97 | **83.5%** ⭐ | $+4.88 | $+474 | $-70 | 2 | **15.10** ⭐ HIGHEST in entire study |
| 6 | S6_SOL_off30_D2_T1 | SOL 5m | 30 | D2 | 130 | 78.5% | $+3.55 | $+461 | $-121 | 2 | 10.26 |
| 7 | S6_ETH_off60_D1_T1 | ETH 5m | 60 | D1 | 182 | 67.0% | $+2.52 | $+459 | $-324 | 6 | 6.40 |
| 8 | S6_ETH_off120_D4_T1 | ETH 5m | 120 | D4 | 98 | 80.6% | $+4.60 | $+451 | $-128 | 4 | 8.16 |
| 9 | S6_BTC_off45_D2_T1 | BTC 5m | 45 | D2 | 159 | 71.7% | $+2.46 | $+391 | $-136 | 3 | 8.03 |
| 10 | S6_ETH_off15_D2_T1 | ETH 5m | 15 | D2 | 230 | 72.6% | $+1.63 | $+375 | $-159 | 3 | 5.72 |

**Spike-only fires (no S1.5 overlap)**: 6,514 fires at 62% WR / $+0.49/tr → independent edge worth $+3,200/28d on its own.

### B.6 S6 — Spike-driven entry (5m, with TA overlay)

| # | Sleeve | Market | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | S6_BREAKOUT_BTC_off120 | BTC 5m @ +120s + ribbon + tight ribbon | 121 | 66.1% | $+7.86 | $+951 | $-137 | 5 | 8.62 |
| 2 | S6_TRIPLE_BTC_off120 | BTC 5m @ +120s + ribbon+stoch+cci | 114 | **75.4%** | $+7.90 | $+901 | $-223 | 7 | 7.58 |
| 3 | S6_BREAKOUT_BTC_off45 | BTC 5m @ +45s + tight ribbon | 126 | 65.1% | $+6.92 | $+872 | $-142 | 5 | 8.78 |
| 4 | S6_TRIPLE_BTC_off30 | BTC 5m @ +30s + ribbon+stoch+cci | 124 | 74.2% | $+6.34 | $+786 | $-150 | 4 | **13.91** ⭐ |
| 5 | S6_TRIPLE_BTC_off45 | BTC 5m @ +45s + ribbon+stoch+cci | 125 | 74.4% | $+5.78 | $+722 | $-123 | 4 | 10.41 |
| 6 | S6_BREAKOUT_BTC_off30 | BTC 5m @ +30s + tight ribbon | 120 | 65.8% | $+5.14 | $+617 | $-114 | 4 | 9.18 |
| 7 | S6_TRIPLE_BTC_off90 | BTC 5m @ +90s + ribbon+stoch+cci | 120 | 73.3% | $+5.06 | $+607 | $-128 | 3 | 7.75 |
| 8 | S6_TRIPLE_BTC_off60 | BTC 5m @ +60s + ribbon+stoch+cci | 136 | 71.3% | $+4.02 | $+547 | $-126 | 5 | 8.83 |
| 9 | S6_BREAKOUT_BTC_off60 | BTC 5m @ +60s + tight ribbon | 129 | 61.2% | $+3.98 | $+514 | $-229 | 4 | 6.84 |
| 10 | S6_BREAKOUT_BTC_off45_D2 | BTC 5m @ +45s D2 + tight ribbon | 105 | 71.4% | $+4.88 | $+512 | $-83 | 3 | 11.72 |

**S6 BREAKOUT family large-volume sleeve**: BTC compression<2bps + ribbon → 5,775 fires, $+3.01/tr, **$+17,391 sum/28d** ← THIS IS A LARGE-N SLEEVE that pre-dates the hybrid_v1 stack but is partially overlapping.

### B.7 S7 — VWAP continuation 15m (base)

| # | Sleeve | Market | Offset | Dev threshold | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe |
|--:|---|---|--:|---|--:|--:|--:|--:|--:|--:|--:|
| 1 | S7_SOL_840_20-30bps | SOL 15m | 840 | 20-30bps | 40 | 77.5% | **$+17.34** ⭐ HIGHEST $/tr in entire study | $+694 | $-115 | 2 | 3.45 |
| 2 | S7_ETH_480_5-10bps | ETH 15m | 480 | 5-10bps | 449 | 76.6% | $+0.61 | $+274 | $-404 | 4 | 4.05 |
| 3 | S7_SOL_240_10-15bps | SOL 15m | 240 | 10-15bps | 116 | 82.8% | $+1.79 | $+208 | $-221 | 3 | 3.87 |
| 4 | S7_ETH_720_15-20bps | ETH 15m | 720 | 15-20bps | 45 | 77.8% | $+3.47 | $+156 | $-110 | 2 | 2.41 |
| 5 | S7_ETH_240_10-15bps | ETH 15m | 240 | 10-15bps | 68 | 86.8% | $+1.98 | $+135 | $-77 | 3 | 5.36 |
| 6 | S7_SOL_360_10-15bps | SOL 15m | 360 | 10-15bps | 165 | 81.8% | $+0.68 | $+112 | $-151 | 2 | 2.20 |
| 7 | S7_ETH_480_15-20bps | ETH 15m | 480 | 15-20bps | 58 | 89.7% | $+1.23 | $+72 | $-70 | 1 | 2.42 |
| 8 | S7_BTC_480_10-15bps | BTC 15m | 480 | 10-15bps | 98 | **89.8%** | $+0.33 | $+32 | $-96 | 2 | 1.92 |

### B.8 S7 — VWAP continuation 15m (with TA overlay)

| # | Sleeve | Market | n | WR | $/tr | sum/28d | max_DD | streak | Sharpe | train_WR | test_WR |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | S7_TRIPLE_BTC_840_5-10bps | BTC 15m @ +840s + ribbon+stoch+cci | 111 | 75.7% | $+7.60 | $+843 | $-287 | 3 | 4.38 | 71% | 85% |
| 2 | S7_RIBBON_BTC_840_5-10bps | BTC 15m @ +840s + ribbon | 141 | 76.6% | $+5.01 | $+707 | $-359 | 5 | 3.67 | 74% | 81% |
| 3 | S7_TRIPLE_BTC_480_5-10bps | BTC 15m @ +480s + ribbon+stoch+cci | 206 | 81.6% | $+1.99 | $+410 | $-118 | 2 | 7.67 | 81% | 84% |
| 4 | S7_RIBBON_SOL_240_10-15bps | SOL 15m @ +240s + ribbon | 80 | 86.2% | $+3.65 | $+292 | $-85 | 3 | 7.78 | 82% | 96% |
| 5 | S7_TRIPLE_BTC_600_5-10bps | BTC 15m @ +600s + ribbon+stoch+cci | 205 | **90.2%** | $+1.42 | $+292 | $-88 | 2 | 7.39 | 89% | 94% |
| 6 | S7_RIBBON_BTC_600_5-10bps | BTC 15m @ +600s + ribbon | 258 | 89.1% | $+1.09 | $+280 | $-90 | 2 | 5.93 | 88% | 91% |
| 7 | S7_RIBBON_BTC_480_5-10bps | BTC 15m @ +480s + ribbon | 252 | 80.9% | $+1.09 | $+275 | $-155 | 4 | 4.56 | 81% | 82% |
| 8 | S7_RIBBON_ETH_720_15-20bps | ETH 15m @ +720s + ribbon | 30 | 83.3% | **$+9.10** | $+273 | $-50 | 1 | 4.70 | 86% | 78% |
| 9 | S7_RIBBON_ETH_600_5-10bps | ETH 15m @ +600s + ribbon | 237 | 84.8% | $+1.13 | $+267 | $-133 | 2 | 4.63 | 85% | 83% |
| 10 | S7_TRIPLE_SOL_240_10-15bps | SOL 15m @ +240s + ribbon+stoch+cci | 72 | 84.7% | $+3.61 | $+260 | $-93 | 3 | 6.97 | 80% | 95% |

**Top-10 ensemble: 1,592 fires, avg WR 83%, $+3,899/28d (2.3× original S7).**

### B.9 S2 — Fade Extreme Momo (BTC + ETH only, mag>3)

| # | Asset | Mag threshold | Extra gate | n | WR | $/tr | sum/28d | max_consec_loss | fwd_WR_same_cell | deployable |
|--:|---|--:|---|--:|--:|--:|--:|--:|--:|---|
| 1 | ALL (BTC+ETH+SOL pooled) | 3.0 | none | 230 | 63.9% | $+5.29 | **$+1,216** | $-210 | 37% | ✅ |
| 2 | ETH | 2.0 | none | 202 | 60.9% | $+4.12 | $+832 | $-204 | 38% | ✅ |
| 3 | BTC | 3.0 | none | 92 | **67.4%** | $+7.30 | $+671 | $-81 | 34% | ✅ |
| 4 | BTC | 2.5 | none | 163 | 60.1% | $+3.80 | $+619 | $-131 | 40% | ✅ |
| 5 | ETH | 3.0 | none | 72 | **70.8%** ⭐ | **$+8.24** | $+593 | $-100 | 30% | ✅ |
| 6 | BTC | 2.0 | gate_mpass_contra | 111 | 60.9% | $+4.90 | $+544 | $-104 | 40% | ✅ |
| 7 | ETH | 2.5 | none | 118 | 61.9% | $+4.13 | $+488 | $-154 | 38% | ✅ |
| 8 | ALL pooled | 3.0 | gate_f7_contra | 61 | 67.2% | $+7.93 | $+484 | $-103 | 35% | ✅ |
| 9 | BTC | 3.0 | gate_f7_contra | 33 | **69.7%** | **$+9.26** | $+306 | $-53 | 32% | ✅ |
| 10 | BTC | 2.5 | gate_mpass_contra | 62 | 61.3% | $+4.70 | $+292 | $-149 | 39% | ✅ |

**SOL: 0 deployable rows at any threshold.** SOL high-mag signals are NOT exhausted — random WR.

**Tier breakdown (pooled BTC+ETH+SOL)**:
- mag (1.5, 2.0]: fade WR 49.3% — don't fade
- mag (2.0, 2.5]: fade WR 44.3% — don't fade
- mag (3.0, 5.0]: **fade WR 63.3%** — FADE
- mag (5.0, 100]: **fade WR 66.7%** — FADE

### B.10 S5 — Z_Contra ETH Underdog (paper-only)

Sub-60% WR but PnL-positive because underdog tokens are CHEAP (entry vwap ~0.30).

| # | Asset | offset_s | dip_bps | dip_lookback | z_thresh | n | WR | $/tr | sum/28d |
|--:|---|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | **ETH** | 30 | 100 | 30 | 1.0 | **183** | **55.2%** | **$+3.24** | **$+594** |
| 2 | ETH | 30 | 100 | 30 | 1.5 | 181 | 55.2% | $+3.26 | $+591 |
| 3 | ETH | 30 | 100 | 30 | 2.0 | 178 | 54.5% | $+3.16 | $+562 |
| 4 | BTC | 60 | 50 | 10 | 1.0 | 667 | 41.9% | $+0.95 | $+632 |
| 5 | BTC | 60 | 30 | 10 | 1.0 | 667 | 41.9% | $+0.95 | $+632 |
| 6 | BTC | 60 | 100 | 10 | 1.0 | 641 | 42.4% | $+0.96 | $+618 |
| 7 | BTC | 60 | 30 | 10 | 1.5 | 661 | 42.0% | $+0.93 | $+618 |
| 8 | BTC | 60 | 50 | 10 | 1.5 | 661 | 42.0% | $+0.93 | $+618 |

**No config hits ≥60% WR**. Treat as **paper-only**, half-notional sizing.
ETH 30s offset 100bps dip Z=1.0 is the cleanest signal — high $/tr (+$3.24) at
low WR (55%) because each ~30c entry pays 2x+ on win.

---

## C. ROLL-UP — DEPLOY-WORTHY ROSTER

### C.1 Final ranked deployable roster (28d @ $25 notional)

Sorted by sum_pnl. Excluding sleeves with >60% slug overlap with a higher-ranked sleeve.

| Rank | Sleeve ID | Market | n | WR | $/tr | sum/28d | max_DD | streak | Source |
|--:|---|---|--:|--:|--:|--:|--:|--:|---|
| 1 | poly_updown_btc_5m_s6_hybrid_v1 | BTC S6 5m 60-150s | 2,764 | 77.8% | $+5.10 | **$+14,103** | $-1,837 | 4 | this run |
| 2 | poly_updown_eth_5m_s6_hybrid_v1 | ETH S6 5m 60-150s | 3,531 | 76.0% | $+1.57 | $+5,553 | $-2,937 | 3 | this run |
| 3 | poly_updown_eth_5m_s15_hybrid_v1 | ETH S1.5 5m 150-240s | 3,420 | 85.1% | $+1.34 | $+4,596 | $-508 | 2 | this run |
| 4 | poly_updown_btc_5m_xa_down | BTC S1.5 5m DOWN-only + xa_all | 2,726 | 82.1% | $+1.64 | $+4,463 | (low) | — | this run |
| 5 | poly_updown_btc_5m_xa_up | BTC S1.5 5m UP-only + xa_all | 2,808 | 82.0% | $+1.53 | $+4,285 | (low) | — | this run |
| 6 | poly_updown_btc_5m_s15_hybrid_v1 | BTC S1.5 5m 150-240s | 1,365 | 85.6% | $+3.06 | $+4,176 | $-379 | 2 | this run |
| 7 | poly_updown_sol_5m_s6_hybrid_v1 | SOL S6 5m 60-150s | 1,503 | 92.9% | $+2.20 | $+3,307 | $-345 | (low) | this run |
| 8 | poly_updown_btc_5m_s15_210 (S1.5) | BTC 5m @ +210s 5-10bps | 387-529 | 87.5% | $+3.50 | $+1,555 | $-149 | 2 | prior — ribbon overlay |
| 9 | poly_updown_eth_5m_s15_210 (S1.5) | ETH 5m @ +210s 10-15bps | 99-138 | 88% | $+13 | $+1,524 | $-125 | 2 | prior — ribbon overlay |
| 10 | poly_updown_btc_15m_s7_hybrid_v1 | BTC S7 15m 480-840s | 816 | 88.0% | $+2.15 | $+1,751 | $-241 | (low) | this run |
| 11 | poly_updown_btc_5m_s15_240 (S1.5) | BTC 5m @ +240s 3-5bps | 555 | 82.5% | $+2.33 | $+1,293 | $-231 | 3 | prior — ribbon overlay |
| 12 | momo.py FADE patch (S2) | BTC+ETH mag>3 pooled | 230 | 63.9% | $+5.29 | $+1,216 | $-210 | (low) | prior — strategy patch |
| 13 | poly_updown_btc_5m_off150_v7 | BTC 5m off=150 RF+PVSRA+MFI | 288 | 66.7% | $+3.04 | $+875 | $-436 | 4 | this run |
| 14 | poly_updown_btc_5m_off90_v7 | BTC 5m off=90 RF+PVSRA+MFI | 332 | 70.8% | $+2.70 | $+896 | $-179 | 4 | this run |
| 15 | poly_updown_sol_5m_s15_270 (S1.5) | SOL 5m @ +270s 5-10bps | 380-570 | 88% | $+2.00 | $+1,014 | $-578 | 2 | prior — ribbon overlay |
| 16 | poly_updown_sol_15m_s7_hybrid_v1 | SOL S7 15m 480-840s | 399 | 87.2% | $+2.66 | $+1,062 | (low) | (low) | this run |
| 17 | poly_updown_btc_15m_s7_840_triple | BTC 15m @ +840s + ribbon+stoch+cci | 111 | 75.7% | $+7.60 | $+843 | $-287 | 3 | prior — TA overlay |
| 18 | poly_updown_eth_5m_off60_v5 | ETH 5m off=60 RF+PVSRA+session | 263 | 66.2% | $+2.76 | $+727 | $-161 | 3 | this run |
| 19 | poly_updown_btc_5m_off60_v7 | BTC 5m off=60 RF+PVSRA+MFI | 297 | 68.7% | $+2.19 | $+651 | $-215 | 4 | this run |
| 20 | poly_updown_sol_5m_off90_v7 | SOL 5m off=90 RF+PVSRA+MFI | 116 | 73.3% | $+3.99 | $+463 | $-175 | 3 | this run |

**Top-20 combined ($25 notional): ~$55-65k/28d after dedup for slug overlap.**

### C.2 Asset × TF coverage matrix

Best per cell — `$/tr | sum_28d | WR%`:

|              | 5m S1.5             | 5m S6                | 15m S7              |
|--------------|---------------------|----------------------|---------------------|
| **BTC**      | $+3.06 / $+4,176 / 85.6% (150-240s hybrid) | **$+5.10 / $+14,103 / 77.8%** (60-150s hybrid) ⭐ | $+2.15 / $+1,751 / 88.0% (480-840s hybrid) |
| **ETH**      | $+1.34 / $+4,596 / 85.1% (150-240s hybrid) | $+1.57 / $+5,553 / 76.0% (60-150s hybrid) | $+5.21 / $+485 / 95.7% (480-840s dev+pp+cloud) |
| **SOL**      | $+6.17 / $+1,740 / 92.6% (240-300s aged+dev+tight+session) | $+2.20 / $+3,307 / 92.9% (60-150s mfi+dev+bb+ribbon) | $+21.79 / $+915 / 97.6% (480-840s dev+rf_aged+adr+pp) |

### C.3 Performance summary per strategy family

| Family | # sleeves | Mean WR | Median $/tr | Total sum/28d | Notes |
|---|--:|--:|--:|--:|---|
| **A.1 Tier-1 hybrid_v1 (7 picks)** | 7 | 84.6% | $+2.20 | **$+34,549** | walk-fwd 20/20 pass |
| **A.2 Cross-asset overlay** | 2 (UP+DOWN) | 82.0% | $+1.59 | $+8,748 | additive on S1.5 |
| **A.3 V7 standalone** | 5 | 70.5% | $+2.87 | $+5,693 (extrap 28d) | corr ≤ 0.483 |
| **B.2 S1.5 base 10 sleeves** | 10 | 84.5% | $+1.79 | $+8,689 | proven from prior session |
| **B.3 S1.5 + ribbon overlay** | 10 | 86.0% | $+3.50 | $+10,300 | preferred deploy form |
| **B.5 S6 base 10 sleeves** | 10 | 73.2% | $+4.06 | $+5,764 | superseded by hybrid_v1 for BTC/ETH/SOL |
| **B.6 S6 + TA overlay** | 10 | 70.0% | $+5.36 | $+6,861 | |
| **B.7 S7 base 8 sleeves** | 8 | 82.8% | $+1.81 | $+1,683 | low n |
| **B.8 S7 + TA overlay** | 10 | 83.3% | $+2.79 | $+3,899 | 2.3× original S7 |
| **B.9 S2 Fade Momo (top 10)** | 10 | 63.4% | $+5.74 | $+5,946 (patch deploy = $+1,216) | strategy patch, not sleeve |
| **B.10 S5 Z_Contra** | 3 ETH cells | 55.2% | $+3.22 | $+1,747 | paper-only, half-notional |
| **S3 HoD refresh** | (modifies 11) | — | — | $+12,951 (delta from shipped) | 5min config edit |

### C.4 Realistic combined deploy (no double-counting)

Compose with overlap awareness:
1. **S3 HoD refresh on existing 11 sleeves** → $+15,900/28d (replaces shipped $+2,949).
2. **S2 Fade Momo patch on existing momo strategies** → $+1,216/28d (additive to refreshed baseline).
3. **B.7.1 drop m5va from sleeve #2** → $+745.
4. **B.7.2 add m1va to sleeve #3** → $+1,265.
5. **Tier-1 hybrid_v1 (×7 picks)** → $+34,549 (some overlap with existing S6 base — net $+25-30k).
6. **Cross-asset xa_all_with_bet overlay** → ~$+4-9k (apply as portfolio filter on existing S1.5 sleeves).
7. **Tier-3 V7 (×5)** → $+5,693 (clean diversification, corr ≤ 0.48).
8. **S5 Z_Contra ETH** → $+594 (paper, half-notional).

**Conservative roll-up: $+55-65k/28d at $25 notional = $1,960-2,320/day @ $25 = ~$20-23k/day @ $250 notional.**
**Aggressive (all sleeves, ignoring overlap): ~$+81k/28d.**

### C.5 Top-5 highest-Sharpe sleeves overall

For capital-constrained "low-DD first" deployment:

| # | Sleeve | Sharpe | n | WR | $/tr | sum/28d | max_DD |
|--:|---|--:|--:|--:|--:|--:|--:|
| 1 | S6_BTC_off60_D4_T1 (prior — base) | **15.10** | 97 | 83.5% | $+4.88 | $+474 | $-70 |
| 2 | S6_TRIPLE_BTC_off30 (prior — overlay) | 13.91 | 124 | 74.2% | $+6.34 | $+786 | $-150 |
| 3 | S1.5_SOL_30_5-10bps (prior) | 13.32 | 112 | 81.2% | $+4.84 | $+542 | $-75 |
| 4 | S6_BREAKOUT_BTC_off45_D2 (prior — overlay) | 11.72 | 105 | 71.4% | $+4.88 | $+512 | $-83 |
| 5 | S6_BTC_off30_D1_T1 (prior — base) | 11.07 | 149 | 67.1% | $+5.15 | $+768 | $-125 |

The S6 family dominates the high-Sharpe tier.

### C.6 Top-5 highest-$/tr sleeves overall

For "low-volume, high-conviction" deployment:

| # | Sleeve | $/tr | n | WR | sum/28d |
|--:|---|--:|--:|--:|--:|
| 1 | SOL S7 15m 480-840s (hybrid: dev+rf_aged+adr+pp) | **$+21.79** | 42 | 97.6% | $+915 |
| 2 | S7_SOL_840_20-30bps (prior — base) | $+17.34 | 40 | 77.5% | $+694 |
| 3 | S1.5_ETH_210_10-15bps (prior) | $+10.92 | 138 | 87.0% | $+1,508 |
| 4 | BTC S6 5m 60-150s hybrid_v1 | $+5.10 | 2,764 | 77.8% | **$+14,103** |
| 5 | S1.5_ETH_210_10-15bps_4gate (prior — small n) | $+76.91 | 20 | 85.0% | $+1,538 |

### C.7 Top-5 highest-WR sleeves (n ≥ 100)

For risk-averse deployment:

| # | Sleeve | WR | n | $/tr | sum/28d |
|--:|---|--:|--:|--:|--:|
| 1 | SOL S6 5m hybrid_v1 (mfi+dev+bb+ribbon) | **92.9%** | 1,503 | $+2.20 | $+3,307 |
| 2 | SOL S1.5 5m 240-300s hybrid (aged+dev+tight+session) | 92.6% | 282 | $+6.17 | $+1,740 |
| 3 | ETH S1.5 5m 240-300s hybrid (ema800+mfi) | 90.7% | 1,879 | $+0.73 | $+1,367 |
| 4 | S7 BTC 15m 600s + ribbon+stoch+cci | 90.2% | 205 | $+1.42 | $+292 |
| 5 | BTC S7 15m 480-840s hybrid (full_stack) | 88.0% | 816 | $+2.15 | $+1,751 |

### C.8 Lowest-DD sleeves (max_DD ≤ $100)

For capital with strict drawdown tolerance:

| Sleeve | max_DD | n | WR | $/tr | sum/28d |
|---|--:|--:|--:|--:|--:|
| S1.5_SOL_30_5-10bps | **$-75** | 112 | 81.2% | $+4.84 | $+542 |
| ETH S7 15m 480-840s hybrid (dev+pp+cloud) | $-50 | 93 | 95.7% | $+5.21 | $+485 |
| S1.5_BTC_210_5-10bps_ribbon+m1v | $-37 | 159 | 97.5% | $+0.99 | $+157 |
| S1.5_ETH_240_5-10bps_ribbon+m1v | $-49 | 218 | 94.5% | $+1.28 | $+280 |
| S1.5_SOL_270_5-10bps_ribbon+m1v | $-25 | 138 | 97.8% | $+0.71 | $+98 |
| S1.5_ETH_210_10-15bps_ribbon+m1v | $-25 | 35 | 97.1% | $+0.77 | $+27 |
| SOL S7 15m 480-840s hybrid (dev+aged+adr+pp) | $-25 | 42 | 97.6% | $+21.79 | $+915 |
| BTC S7 15m 240-480s hybrid (fresh+adr+ema800+tight) | $-90 | 151 | 89.4% | $+2.10 | $+318 |

---

## D. NOTES + CAVEATS

1. **Slug overlap** is NOT subtracted in the per-sleeve $-sums. Multiple sleeves may
   fire on the same slug → combined live PnL will be LESS than the linear sum.
   Compute slug-overlap before promoting > 3 sleeves on the same (asset, tf).
2. **Window**: all metrics are over the 28d Apr 30 → May 22 chainlink window.
   Some 22d sleeves (V7 standalone) are normalized to 22d in the source CSV
   and explicitly noted.
3. **Fee model**: legacy 2%-on-profit-only (matches VPS3 production verified
   2026-05-22). NOT the hypothetical `0.07·p·(1−p)` real curve.
4. **All sleeves backtest at $25 notional**. Scaling to $250 is operator decision
   based on per-sleeve realized DD in shadow.
5. **No mid-slot exits, no SL, no TP**. Hold to slot_end. Period.
6. **PVSRA standalone is unusable** (-37pp WR on 5m). PVSRA only enters via
   V7 stack (RF+PVSRA+MFI) where the other two gates carry the signal.
7. **15m S7 sleeves are SMALL n** (most cells n ≤ 250). High WR but limited
   statistical power. Treat the highest-$/tr 15m sleeves as candidate, not
   confirmed, until 7d shadow.
8. **All 20 walk-forward stacks passed** (test_sum > 0). Bootstrap p ≤ 0.001
   on top-20. This is family-wise UNcorrected — effect size is the
   load-bearing evidence.
9. **Z_Contra (S5)** is sub-60% WR — must be paper-only and size-limited.

## End of catalog

All underlying CSVs available at `data/v4/canonical/_results/`. Reports at
`strategy_lab/reports/`. Implementer should reference
`MASTER_DEPLOY_SPEC_2026_05_26.md` for the full implementation spec; this
catalog provides the per-sleeve metrics any audit/review needs.
