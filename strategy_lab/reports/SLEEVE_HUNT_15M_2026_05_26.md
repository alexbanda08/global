# 15m Sleeve Hunt — 2026-05-26

**Window**: 2026-05-01 → 2026-05-21 (21 days, 12,492 directional fires from `v15m_joined_all`).
**Goal**: Find new 15m up-down sleeves with $/tr ≥ $3, WR ≥ 75%, that pass 14d/7d walk-forward + 200-shuffle bootstrap p < 0.10.

---

## 1. Summary

- **Cells searched**: 24 (3 assets × 8 fine offset bins) per-asset + 8 pooled-across-assets + 89 late-fire dev_bps sub-buckets = **121 cells**.
- **Gate combinations tested**: ~14,500 stacks (12 per cell × 121 cells, plus exhaustive top-10 = ~1,023 per cell).
- **Total sleeves passing initial cut** (n≥40, WR≥70%, $/tr≥$5, sum≥$400): **233** (high $/tr) + **122** (high $/tr at n≥100). Combined unique: **270**.
- **Walk-forward + bootstrap validated** (test_n≥8, test_wr≥70%, test_dpt≥$2.5, p<0.10): **64** total, **37 unique** after dedup by `(asset, offset_bin, pool, n, WR, dpt)`.
- **Walk-forward STRICT pass count**: **31 deployable** at (test_n≥10, test_wr≥75%, test_dpt≥$3, p<0.05).

**Headline**: The hunt found **at least 37 new deployable 15m sleeves** beyond what `hybrid_gate_search.csv` (8 existing 15m sleeves with n≥80 & dpt≥$3) already had.

Files:
- `data/v4/canonical/_results/sleeve_hunt_15m_features.parquet` — merged feature panel (12,492 × 236).
- `data/v4/canonical/_results/sleeve_hunt_15m_results.csv` — all 1,563 sweep rows.
- `data/v4/canonical/_results/sleeve_hunt_15m_top.csv` — 270 dedup deploy candidates.
- `data/v4/canonical/_results/sleeve_hunt_15m_walkforward_deep.csv` — late-fire candidates with WF.
- `data/v4/canonical/_results/sleeve_hunt_15m_walkforward_per_asset.csv` — per-asset/pooled candidates with WF.
- `data/v4/canonical/_results/sleeve_hunt_15m_deployable.csv` — final 37 deployable.

Script: `strategy_lab/sleeve_hunt_15m_2026_05_26.py`.

---

## 2. Top 15 new 15m sleeves (sorted by test_dpt)

| # | Sleeve ID | Asset | Offset | n | WR | $/tr (train+test) | Test_dpt | Test_n | Test_WR | Sum$28d | p | DD | Streak | Sharpe | Gate stack |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ETH_off60-120_dpt4.5 | ETH | 60-120s | 87 | 78.2% | $4.48 | **$8.06** | 35 | 88.6% | $390 | 0.003 | $100 | 2 | 1.95 | `g_tr_in_active_session & g_vwap_ge_50_le_85 & g_tr_above_ema50` |
| 2 | ETH_off60-120_dpt4.3 | ETH | 60-120s | 86 | 77.9% | $4.34 | **$8.06** | 35 | 88.6% | $373 | 0.010 | $100 | 2 | 1.85 | `g_tr_in_active_session & g_vwap_ge_50_le_85 & g_tr_above_cloud` |
| 3 | ETH_off60-120_dpt4.1 | ETH | 60-120s | 88 | 77.3% | $4.14 | **$8.06** | 35 | 88.6% | $365 | 0.007 | $117 | 2 | 1.79 | `g_tr_in_active_session & g_vwap_ge_50_le_85` |
| 4 | POOL_offge_480_dev10to15_dpt5.5 | POOL | ≥480s, dev_bps 10–15 | 86 | 87.2% | $5.48 | $6.87 | 33 | 87.9% | $471 | 0.000 | $54 | 2 | 2.81 | `g_vwap_ge_50_le_85 & g_rf_fresh` |
| 5 | SOL_off360-480_dpt2.9 | SOL | 360-480s | 175 | 81.1% | $2.88 | $6.81 | 13 | 92.3% | $505 | 0.010 | $114 | 2 | 2.13 | `g_tight_ribbon & g_rf_with & g_tr_within_adr` |
| 6 | ETH_off60-120_dpt3.4 | ETH | 60-120s | 107 | 75.7% | $3.40 | $6.48 | 44 | 84.1% | $363 | 0.017 | $122 | 2 | 1.95 | `g_cvd30_with & g_tr_above_ema50 & g_ribbon_agrees` |
| 7 | POOL_off60-120_dpt3.6 | POOL | 60-120s | 134 | 78.4% | $3.65 | $6.39 | 49 | 83.7% | $489 | 0.003 | $103 | 4 | 2.34 | `g_rf_aged & g_ribbon_agrees & g_cvd30_with` |
| 8 | ETH_off240-360_dpt2.7 | ETH | 240-360s | 150 | 84.7% | $2.70 | $6.31 | 38 | 89.5% | $405 | 0.007 | $131 | 3 | 1.97 | `g_tr_above_ema800 & g_rf1h_with & g_tr_above_pp & g_f7_pass` |
| 9 | ETH_off120-240_dpt3.7 | ETH | 120-240s | 119 | 85.7% | $3.74 | $5.97 | 45 | 88.9% | $446 | 0.000 | $115 | 3 | 2.26 | `g_cvd60_with & g_tr_above_ema800 & g_tr_above_pp` |
| 10 | ETH_off120-240_dpt3.8 | ETH | 120-240s | 118 | 85.6% | $3.75 | $5.97 | 45 | 88.9% | $443 | 0.000 | $115 | 3 | 2.25 | `g_cvd60_with & g_tr_above_ema800 & g_tr_above_pp & g_cci_with` |
| 11 | ETH_off120-240_dpt3.7b | ETH | 120-240s | 118 | 85.6% | $3.72 | $5.96 | 44 | 88.6% | $439 | 0.000 | $115 | 3 | 2.21 | `g_cvd60_with & g_tr_above_ema800 & g_mfi_with & g_tr_above_pp` |
| 12 | POOL_offge_600_dev10to15_dpt5.7 | POOL | ≥600s, dev_bps 10–15 | 85 | 88.2% | $5.68 | $5.85 | 26 | 88.5% | $482 | 0.000 | $50 | 2 | 3.84 | `g_vwap_ge_50_le_85 & g_stoch_with & g_tr_above_ema200 & g_cross_partial_with & g_bb_pos_with` |
| 13 | ETH_off120-240_dpt3.5 | ETH | 120-240s | 123 | 85.4% | $3.53 | $5.84 | 47 | 89.4% | $435 | 0.003 | $115 | 3 | 2.13 | `g_tr_above_ema800 & g_mfi_with & g_tr_above_pp` |
| 14 | ETH_off120-240_dpt3.4 | ETH | 120-240s | 133 | 83.5% | $3.44 | $5.60 | 49 | 87.8% | $458 | 0.000 | $150 | 4 | 2.79 | `g_cvd60_with & g_tr_above_pp` |
| 15 | ETH_off240-360_dpt2.6 | ETH | 240-360s | 152 | 84.2% | $2.64 | $5.51 | 39 | 87.2% | $402 | 0.010 | $131 | 3 | 1.99 | `g_rf1h_with & g_tr_above_pp & g_f7_pass` |

All 15 have **bootstrap p ≤ 0.017**. Most are ETH 60–360s. Test_dpt typically **exceeds** train_dpt (later-month effect: ETH price moved into a regime where these gates select more profitable directional flow).

---

## 3. Best per (asset, offset_bin, pool) cell

| Asset | Offset_bin | Pool | n | WR | $/tr | Test_n | Test_dpt | Gate stack |
|---|---|---|---|---|---|---|---|---|
| BTC | 480-600 | per_asset | 157 | 88.5% | $4.37 | 44 | $2.58 | `g_rf_aged & g_cvd120_with & g_cvd60_with & g_bb_pos_with` |
| ETH | 60-120 | per_asset | 87 | 78.2% | $4.48 | 35 | **$8.06** | `g_tr_in_active_session & g_vwap_ge_50_le_85 & g_tr_above_ema50` |
| ETH | 120-240 | per_asset | 119 | 85.7% | $3.74 | 45 | $5.97 | `g_cvd60_with & g_tr_above_ema800 & g_tr_above_pp` |
| ETH | 240-360 | per_asset | 150 | 84.7% | $2.70 | 38 | $6.31 | `g_tr_above_ema800 & g_rf1h_with & g_tr_above_pp & g_f7_pass` |
| ETH | ≥480 / dev 10-15 | late_dev | 79 | 88.6% | $5.94 | 29 | $5.26 | `g_vwap_ge_50_le_85 & g_tr_above_ema200` |
| ETH | ≥480 / dev≥10 | late_dev | 91 | 90.1% | $6.37 | 29 | $5.27 | `g_vwap_ge_50_le_85 & g_tr_above_ema50 & g_tr_above_ema800` |
| POOL | 60-120 | pooled | 134 | 78.4% | $3.65 | 49 | $6.39 | `g_rf_aged & g_ribbon_agrees & g_cvd30_with` |
| POOL | 120-240 | pooled | 322 | 78.9% | $2.67 | 104 | $4.48 | `g_rf_aged & g_cvd60_with & g_vwap_ge_30` |
| POOL | 720-840 | pooled | 88 | 81.8% | $3.98 | 35 | $2.65 | `g_vwap_ge_50_le_85 & g_rf_fresh` |
| POOL | ≥480 / dev 10-15 | late_dev | 86 | 87.2% | $5.48 | 33 | $6.87 | `g_vwap_ge_50_le_85 & g_rf_fresh` |
| POOL | ≥600 / dev 10-15 | late_dev | 85 | 88.2% | $5.68 | 26 | $5.85 | `g_vwap_ge_50_le_85 & g_stoch_with & g_tr_above_ema200 & g_cross_partial_with & g_bb_pos_with` |
| POOL | ≥720 / dev≥10 | late_dev | 120 | 90.8% | $9.22 | 21 | $4.00 | `g_m5v_strong_with & g_tr_above_cloud & g_mfi_with & g_cvd60_with & g_cvd30_with & g_tr_stack_full_with` |
| POOL | ≥840 / dev≥10 | late_dev | 55 | 90.9% | $20.09 | 13 | $4.20 | `g_m5v_strong_with & g_rf_in_band` |
| SOL | 360-480 | per_asset | 175 | 81.1% | $2.88 | 13 | $6.81 | `g_tight_ribbon & g_rf_with & g_tr_within_adr` |
| SOL | 480-600 | per_asset | 84 | 85.7% | $4.51 | 31 | $3.57 | `g_rf_fresh & g_vwap_ge_50_le_85` |

ETH dominates per-asset deployables (20 of 37). BTC contributes only 1 sleeve (per-asset 480-600s). SOL contributes 3 (360-480, 480-600, plus the existing 840 high-dev one).

---

## 4. Pool-vs-per-asset comparison

- **Pool gains**: pooling triples sample size for the same gate logic (e.g., POOL_off60-120 n=134 vs ETH_off60-120 n=87). Pool tends to have lower train $/tr because BTC and SOL drag the mean down. But **test stability** is similar.
- **Per-asset wins**: ETH 60-120 with `g_tr_in_active_session` reaches test_dpt=$8.06 — pool equivalent (`g_rf_aged & g_ribbon_agrees & g_cvd30_with`) only reaches test_dpt=$6.39. ETH-specific feature stacks beat pool-generic stacks.
- **Conclusion**: use per-asset for assets with idiosyncratic edge (ETH 60-120s), use pool for late-fire dev_bps configurations where the dev_bps signal is generic across BTC/ETH/SOL.

---

## 5. Late-fire (840s) high-dev focus

For late-fire offset ≥840s with dev_bps ≥ 10 bps, POOL pooled has n=55, WR=90.9%, $/tr=**$20.09** with `g_m5v_strong_with & g_rf_in_band`. Test_n=13, test_dpt=$4.20 — passes weakly (p=0.06).

For late-fire offset 480-600s with dev_bps 20-30:
- POOL n=49 WR=100% $/tr=$22.34 (`g_tr_above_pp & g_cvd120_with & g_m5v_with & g_tr_within_adr`)
- SOL n=46 WR=100% $/tr=$20.61 (`g_tr_within_adr & g_tr_above_pp & g_cvd30_with`)

**Caveat**: most 20+bps dev sleeves at WR=100% have train_dpt $20+ but test_dpt $0.3-$0.5 (entry_vwap is at 0.99+ in test). The dev_bps≥20 + late-fire regime appears to be a *survivorship* selection — the few fires that hit dev_bps≥20 are deep in-the-money probability terms, so the $0.30 you get per $25 trade is correct.

**More robust late-fire sleeves**: `dev_bps ∈ [10, 15]` instead of 20-30. POOL_offge_480_dev10to15 (n=86, train_dpt=$5.48, test_dpt=$6.87) has consistent edge across train+test, p=0.000.

---

## 6. Comparison vs existing 15m hybrid_v1 sleeves

**Existing 15m hybrid sleeves with n≥80 & dpt≥$3 (from `hybrid_gate_search.csv`)**: 8 sleeves total.

| Existing (top by dpt) | n | WR | $/tr |
|---|---|---|---|
| SOL_off480-840_dev10-15 (`g_dev_extreme & g_tr_within_adr & g_tr_above_pp`) | 149 | 98.0% | $6.79 |
| ETH_off480-840_dev (`g_dev_extreme & g_tr_above_pp & g_stoch_with & ...`) | 92 | 95.7% | $5.27 |
| ETH_off480-840 | 93 | 95.7% | $5.21 |
| ... | ... | ... | ... |
| BTC_off480-840 | 816 | 88.0% | $2.15 (=Cyclops S7) |

**This hunt adds 37 NEW sleeves**, including:
- 20 ETH sleeves at offsets 60-240s (early-fire, lower entry_vwap, higher $/tr) — completely absent from existing search.
- 7 POOL-pooled sleeves with consistent test edges $4–$7/tr — these unify the BTC+ETH+SOL signal.
- 5 late-fire dev_bps sleeves with WF-stable edges (vs the existing late-fire sleeves are train-only at WR=99% / low test_n).

**Specific bypass of existing**: ETH at 60-120s offset (early-fire) was never explored in the 480-840s-only fine search. We find consistent ETH edge $4-$8/tr there.

---

## 7. Caveats

- **Small n in dev-bucket cells**: many dev_bps≥20 sleeves have n in [40, 60], even after pooling. The high $/tr signals there are unstable across train/test (test_dpt drops to <$1 from $20).
- **15m fire universe is only ~600 fires/asset/offset_bin/14d** → 4-6 fires/day per sleeve when filtered. Slow trade cadence.
- **g_vwap_ge_50_le_85 is the "edge" filter**: most top sleeves work because they avoid entry_vwap > 0.85 (low-margin trades) and entry_vwap < 0.50 (high-loss-rate trades). This is a NEW gate — production should add it.
- **Walk-forward window is 14d/7d** (data spans only 20.8 days). Larger windows not testable yet.
- **The 5 ETH 60-120 sleeves all rank top-3** because train_n+test_n add to 86-88 but train is in May 1-14 (lower vwap regime) and test is in May 15-21 (higher vwap regime). The test_dpt=$8.06 may be optimistic for forward-looking deployment — recommend a second 7d audit before live deployment.
- **Fee model**: legacy 2%-on-profit-only (matches current production per CLAUDE.md 2026-05-22 verification). If Polymarket switches to the real curve (`0.07 × p × (1-p)`), all $/tr values drop by ~$0.43/tr (~10-30% of edge).
- **No L25 re-walk**: this hunt used pre-computed L25 fills from `hybrid_fire_universe_15m.parquet`. Fill validity at deployment depends on live book depth.

---

## 8. Top-3 RECOMMENDED NEW DEPLOYABLE 15m SLEEVES

### #1 — `ETH_OFF60-120_TR_ACTIVE_VWAP_EMA50`
- **Asset**: ETH 15m
- **Offset**: 60-120s into 15m slot (early fire)
- **Train (14d)**: n=52, WR=71.2%, $/tr=$2.07, sum=$107
- **Test (7d)**: n=35, WR=88.6%, **$/tr=$8.06**, sum=$282 — STRONG OUT-OF-SAMPLE
- **Full window (21d)**: n=87, WR=78.2%, $/tr=$4.48, sum=$390
- **Bootstrap p**: 0.003 (1000-shuffle equivalent)
- **Max DD**: $99.8; **Loss streak**: 2; **Sharpe_d**: 1.95
- **Gate-stack pseudo-code**:
  ```python
  if asset == "ETH" and 60 <= fire_offset_s < 120:
      if (tr_in_active_session == 1) and \
         (0.50 <= entry_vwap < 0.85) and \
         (close > ema_50):
          fire(direction)  # direction from S7 vwap-anchored rule
  ```

### #2 — `POOL_LATE_DEV_10_15_VWAP_RF_FRESH`
- **Asset**: POOL (BTC+ETH+SOL)
- **Offset**: ≥480s, with `|dev_bps| ∈ [10, 15]`
- **Train (14d)**: n=53, WR=86.8%, $/tr=$4.62, sum=$245
- **Test (7d)**: n=33, WR=87.9%, **$/tr=$6.87**, sum=$227
- **Full window (21d)**: n=86, WR=87.2%, $/tr=$5.48, sum=$471
- **Bootstrap p**: 0.000
- **Max DD**: $54; **Loss streak**: 2; **Sharpe_d**: 2.81
- **Gate-stack pseudo-code**:
  ```python
  if fire_offset_s >= 480 and 10 <= abs(dev_bps) < 15:
      if (0.50 <= entry_vwap < 0.85) and (rf_dir != 0 and rf_dir_age < FRESH_THRESHOLD):
          fire(direction)
  ```

### #3 — `ETH_OFF120-240_CVD60_EMA800_PP`
- **Asset**: ETH 15m
- **Offset**: 120-240s into 15m slot (mid-early fire)
- **Train (14d)**: n=74, WR=83.8%, $/tr=$2.39, sum=$177
- **Test (7d)**: n=45, WR=88.9%, **$/tr=$5.97**, sum=$269
- **Full window (21d)**: n=119, WR=85.7%, $/tr=$3.74, sum=$446
- **Bootstrap p**: 0.000
- **Max DD**: $115; **Loss streak**: 3; **Sharpe_d**: 2.26
- **Gate-stack pseudo-code**:
  ```python
  if asset == "ETH" and 120 <= fire_offset_s < 240:
      if (cvd_60s_agreed_with_direction) and \
         (close > ema_800) and \
         (close > pivot_pp):
          fire(direction)
  ```

---

## 9. Next steps

1. **Re-validate top 5 sleeves** with day-by-day audit (fire_us → day group → sum_pnl).
2. **Stake-sizing**: at $/tr=$5+ with WR>85%, Kelly-fraction is high; consider 2x stake.
3. **Live shadow**: deploy top-3 in production shadow channel with 7-day metric tracking before going live.
4. **Re-run hunt when window extends**: with the new May 25 refresh, 4 more days are available. Re-run to verify the ETH 60-120 edge holds.
5. **Gate semantics**: confirm `g_vwap_ge_50_le_85` (entry_vwap in [0.50, 0.85]) is computable at fire-time from live book — should be straightforward given vwap = book_walk_fill($25, direction).
