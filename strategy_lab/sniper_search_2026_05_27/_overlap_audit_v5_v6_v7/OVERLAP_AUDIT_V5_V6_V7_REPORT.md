# V5 + V6 + V7 Sleeve Overlap Audit Report

**Generated:** 2026-05-27  
**Data window:** Apr 24 – May 26, 2026 (33 days, full window v3 fires)  
**Sleeves registered:** 58 (16 V5 + 14 V6 + 28 V7)  
**Sleeves reproduced (n≥5 fires):** 55  
**Sleeves unreproducible (missing gate columns):** 3

## Methodology

1. **Panel selection per market.** For each (asset, tf), used the richest V7 panel as the gate source. V7 panels are supersets of V3/V6 gate columns:
   - BTC 5m: `strategy_lab/sniper_search_2026_05_27/btc_5m_v7/_sandbox/universe_v7.parquet`
   - BTC 15m: `data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet`
   - ETH 5m: `data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet`
   - ETH 15m: `strategy_lab/sniper_search_2026_05_27/eth_15m_v7/eth_15m_enriched_v7.parquet`
   - SOL 5m: `strategy_lab/sniper_search_2026_05_27/sol_5m_v7/_panel_sol_5m_v7.parquet`
   - SOL 15m: `strategy_lab/sniper_search_2026_05_27/sol_15m_v7/sol_15m_v7_universe.parquet`

2. **Gate stack application.** For each sleeve, all listed gate columns must equal 1. Offset filter then direction filter applied. PnL column `pnl_legacy_usd` (per panel, $25 stake, 2%-on-profit fee).

3. **Pairwise overlap.** For each pair, computed:
   - `jaccard_fire` = |A∩B| / |A∪B| on (slug, fire_us, direction) tuples
   - `jaccard_slug` = |slugs(A)∩slugs(B)| / |slugs(A)∪slugs(B)|
   - `cov_smaller` = |A∩B| / min(|A|, |B|) — how much of the smaller sleeve is contained in the larger one

4. **Redundancy classification.** A pair is REDUNDANT if `jaccard_fire >= 0.50` OR `cov_smaller >= 0.85`. Connected components form clusters. Within each cluster, the kept sleeve maximizes `sum_28d_proj + 100 * dpt_usd`.

5. **Caveat — pnl scale.** The legacy fee on a $25 stake at vwap=0.6 winning leg pays ~$8 net; at vwap=0.05 (lottery-long) the same $25 stake returns ~$1163 if won. PnL totals here include those outlier wins. They are real backtest outcomes but should be treated cautiously for sizing decisions.

## 0. Summary

- **25 clusters** identified across 55 sleeves (9 clusters with ≥2 sleeves are redundant).
- **25 kept sleeves** after dedup (down from 55).
- **28d const-$25 PnL projection:**
    - Raw sum (no dedup): **$62,009**
    - Deduped sum: **$41,423**
    - Reduction from dedup: **$20,586 (33.2%)**

Per-version contribution to deduped 28d PnL:
- **V7**: $29,436
- **V5**: $7,509
- **V6**: $4,479

## 1. Top 20 highest-overlap pairs (FIRE-level Jaccard)

| # | Sleeve A | Sleeve B | n_a | n_b | Jaccard_fire | cov_smaller | inter |
|---|----------|----------|----:|----:|-------------:|------------:|------:|
| 1 | SOL_15M_V7_S5_BTC_SLOPE_STR | SOL_15M_V7_S5_BTC_SLOPE_STR_V2 | 104 | 104 | 1.000 | 1.000 | 104 |
| 2 | BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6 | BTC_15M_V7_BASELINE | 526 | 526 | 1.000 | 1.000 | 526 |
| 3 | ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5 | ETH_5M_V5_REPL_OFF120_V6 | 120 | 120 | 1.000 | 1.000 | 120 |
| 4 | BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5 | BTC_5M_TS_MPSKEW_S6_0_60_V5 | 144 | 144 | 1.000 | 1.000 | 144 |
| 5 | ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5 | ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5 | 124 | 120 | 0.968 | 1.000 | 120 |
| 6 | ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5 | ETH_5M_V5_REPL_OFF120_V6 | 124 | 120 | 0.968 | 1.000 | 120 |
| 7 | ETH_5M_BB_MP_HURST_BAND_V6 | ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP | 162 | 163 | 0.946 | 0.975 | 158 |
| 8 | ETH_15M_V7_PG_VOL_EXTREME_CORE | ETH_15M_V7_PG_VOL_EXTREME_TS | 37 | 35 | 0.946 | 1.000 | 35 |
| 9 | SOL_5M_V7_S4_CCI_F7_OVERSOLD_MFI_STOCH | SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT | 673 | 725 | 0.928 | 1.000 | 673 |
| 10 | ETH_5M_CLOUD_RIBBON_MP_HURST_V6 | ETH_5M_V7_C3_V6C3_PARENT_RANGING | 481 | 437 | 0.909 | 1.000 | 437 |
| 11 | ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6 | ETH_15M_V7_PI_S1_TS_AND_BTC_15M | 63 | 57 | 0.905 | 1.000 | 57 |
| 12 | ETH_15M_V7_PI_S1_BTC_15M_TREND | ETH_15M_V7_PI_S1_TS_AND_BTC_15M | 64 | 57 | 0.891 | 1.000 | 57 |
| 13 | ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6 | ETH_15M_V7_PG_RV_ABOVE_MED | 63 | 56 | 0.889 | 1.000 | 56 |
| 14 | ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5 | ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6 | 107 | 90 | 0.841 | 1.000 | 90 |
| 15 | SOL_15M_V7_S1_BTC_ADX_VOLLOW | SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2 | 40 | 42 | 0.822 | 0.925 | 37 |
| 16 | ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6 | ETH_15M_V7_PI_S1_BTC_15M_TREND | 63 | 64 | 0.814 | 0.905 | 57 |
| 17 | ETH_15M_V7_PG_RV_ABOVE_MED | ETH_15M_V7_PI_S1_TS_AND_BTC_15M | 56 | 57 | 0.794 | 0.893 | 50 |
| 18 | SOL_5M_F7_MFI_EMA200_VWAP_V6 | SOL_5M_F7_MP_EMA200_VWAP_V6 | 144 | 189 | 0.743 | 0.986 | 142 |
| 19 | ETH_15M_V7_PG_RV_ABOVE_MED | ETH_15M_V7_PI_S1_BTC_15M_TREND | 56 | 64 | 0.714 | 0.893 | 50 |
| 20 | ETH_15M_V7_PG_RV_ABOVE_MED | ETH_15M_V7_PG_VOL_EXTREME_TS | 56 | 35 | 0.625 | 1.000 | 35 |

**Top 3 most overlapping pairs across versions:**
1. `SOL_15M_V7_S5_BTC_SLOPE_STR` ↔ `SOL_15M_V7_S5_BTC_SLOPE_STR_V2` — J_fire=1.000, cov_smaller=1.000
2. `BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6` ↔ `BTC_15M_V7_BASELINE` — J_fire=1.000, cov_smaller=1.000
3. `ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5` ↔ `ETH_5M_V5_REPL_OFF120_V6` — J_fire=1.000, cov_smaller=1.000

## 2. Redundancy clusters (size ≥ 2)

### Cluster 0 — BTC 15m (5 sleeves)
**KEEP**: `BTC_15M_EMA50_EMA800_OFF600_DOWN_V5` (V5, n=917, WR=76.3%, $/tr=$1.07, 28d=$832)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V5 | `BTC_15M_EMA50_EMA800_OFF600_DOWN_V5` | 917 | 76.3 | $1.07 | $832 |
| drop | V5 | `BTC_15M_MPSKEW_TRSTACK_OFF600_DOWN_V5` | 258 | 88.4 | $1.76 | $385 |
| drop | V5 | `BTC_15M_TS_TRSTACK_OFF600_DOWN_V5` | 198 | 89.4 | $1.88 | $316 |
| drop | V6 | `BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6` | 526 | 65.4 | $-0.53 | $-238 |
| drop | V7 | `BTC_15M_V7_BASELINE` | 526 | 65.4 | $-0.53 | $-238 |

### Cluster 2 — BTC 5m (2 sleeves)
**KEEP**: `BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5` (V5, n=357, WR=90.2%, $/tr=$11.50, 28d=$3482)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V5 | `BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5` | 357 | 90.2 | $11.50 | $3482 |
| drop | V5 | `BTC_5M_TS_MPSKEW_S6_0_60_V5` | 357 | 90.2 | $11.50 | $3482 |

### Cluster 3 — ETH 15m (9 sleeves)
**KEEP**: `ETH_15M_TRSTACK_VWAP_OFFEARLY_V5` (V5, n=467, WR=67.9%, $/tr=$3.10, 28d=$1229)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V5 | `ETH_15M_TRSTACK_VWAP_OFFEARLY_V5` | 467 | 67.9 | $3.10 | $1229 |
| drop | V7 | `ETH_15M_V7_PI_S1_BTC_15M_TREND` | 64 | 82.8 | $9.52 | $517 |
| drop | V7 | `ETH_15M_V7_PI_S1_TS_AND_BTC_15M` | 57 | 82.5 | $9.43 | $456 |
| drop | V5 | `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5` | 107 | 78.5 | $7.32 | $664 |
| drop | V6 | `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6` | 90 | 74.4 | $7.62 | $582 |
| drop | V7 | `ETH_15M_V7_PG_RV_ABOVE_MED` | 56 | 82.1 | $9.00 | $427 |
| drop | V6 | `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6` | 63 | 81.0 | $8.61 | $460 |
| drop | V7 | `ETH_15M_V7_PG_VOL_EXTREME_CORE` | 37 | 86.5 | $8.89 | $279 |
| drop | V7 | `ETH_15M_V7_PG_VOL_EXTREME_TS` | 35 | 85.7 | $8.60 | $255 |

### Cluster 4 — ETH 5m (3 sleeves)
**KEEP**: `ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5` (V5, n=124, WR=85.5%, $/tr=$3.74, 28d=$393)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V5 | `ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5` | 124 | 85.5 | $3.74 | $393 |
| drop | V5 | `ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5` | 120 | 87.5 | $3.59 | $366 |
| drop | V6 | `ETH_5M_V5_REPL_OFF120_V6` | 120 | 87.5 | $3.59 | $366 |

### Cluster 9 — SOL 5m (2 sleeves)
**KEEP**: `SOL_5M_RF_TR_PP_MID_V5` (V5, n=126, WR=84.1%, $/tr=$4.00, 28d=$427)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V5 | `SOL_5M_RF_TR_PP_MID_V5` | 126 | 84.1 | $4.00 | $427 |
| drop | V5 | `SOL_5M_RF_TR_PARTIAL_MID_V5` | 207 | 79.2 | $1.67 | $294 |

### Cluster 12 — ETH 5m (6 sleeves)
**KEEP**: `ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING` (V7, n=748, WR=79.4%, $/tr=$3.89, 28d=$2467)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V7 | `ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING` | 748 | 79.4 | $3.89 | $2467 |
| drop | V6 | `ETH_5M_BB_MP_HURST_BAND_V6` | 162 | 74.1 | $9.86 | $1356 |
| drop | V6 | `ETH_5M_CLOUD_RIBBON_MP_HURST_V6` | 481 | 81.7 | $4.60 | $1878 |
| drop | V7 | `ETH_5M_V7_C3_V6C3_PARENT_RANGING` | 437 | 81.9 | $4.90 | $1816 |
| drop | V7 | `ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP` | 163 | 72.4 | $9.15 | $1265 |
| drop | V7 | `ETH_5M_V7_C5_CLOUD_HURST_VWAP_PARENT` | 265 | 67.9 | $6.70 | $1507 |

### Cluster 13 — SOL 15m (7 sleeves)
**KEEP**: `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6` (V6, n=749, WR=79.7%, $/tr=$2.20, 28d=$1399)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V6 | `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6` | 749 | 79.7 | $2.20 | $1399 |
| drop | V6 | `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6` | 336 | 72.9 | $2.73 | $779 |
| drop | V7 | `SOL_15M_V7_S3_XADX_ETHVOLLOW` | 52 | 80.8 | $6.23 | $275 |
| drop | V7 | `SOL_15M_V7_S5_BTC_SLOPE_STR_V2` | 104 | 78.8 | $4.58 | $404 |
| drop | V7 | `SOL_15M_V7_S5_BTC_SLOPE_STR` | 104 | 78.8 | $4.58 | $404 |
| drop | V7 | `SOL_15M_V7_S1_BTC_ADX_VOLLOW` | 40 | 82.5 | $6.30 | $214 |
| drop | V7 | `SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2` | 42 | 81.0 | $5.88 | $210 |

### Cluster 14 — SOL 5m (3 sleeves)
**KEEP**: `SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6` (V6, n=183, WR=82.0%, $/tr=$3.76, 28d=$584)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V6 | `SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6` | 183 | 82.0 | $3.76 | $584 |
| drop | V6 | `SOL_5M_F7_MP_EMA200_VWAP_V6` | 189 | 79.9 | $3.65 | $585 |
| drop | V6 | `SOL_5M_F7_MFI_EMA200_VWAP_V6` | 144 | 80.6 | $3.68 | $450 |

### Cluster 24 — SOL 5m (2 sleeves)
**KEEP**: `SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT` (V7, n=725, WR=79.9%, $/tr=$1.82, 28d=$1121)

| keep? | version | sleeve_id | n | WR% | $/tr | 28d proj |
|-------|---------|-----------|--:|----:|-----:|---------:|
| **KEEP** | V7 | `SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT` | 725 | 79.9 | $1.82 | $1121 |
| drop | V7 | `SOL_5M_V7_S4_CCI_F7_OVERSOLD_MFI_STOCH` | 673 | 79.5 | $1.88 | $1072 |

## 3. Per-market overlap summary

| Market | Total sleeves | Clusters | Multi-sleeve clusters | Singletons | After-dedup count |
|--------|--------------:|---------:|----------------------:|-----------:|------------------:|
| BTC 15m | 8 | 4 | 1 | 3 | 4 |
| BTC 5m | 7 | 6 | 1 | 5 | 6 |
| ETH 15m | 9 | 1 | 1 | 0 | 1 |
| ETH 5m | 11 | 4 | 2 | 2 | 4 |
| SOL 15m | 9 | 3 | 1 | 2 | 3 |
| SOL 5m | 11 | 7 | 3 | 4 | 7 |

## 4. V6 in-shadow compatibility analysis

For each V6 sleeve currently in shadow deploy, the table lists how many V7 sleeves would DUPLICATE (jaccard≥0.5 or cov≥0.85), partially overlap (0.30 ≤ J < 0.50), or be COMPATIBLE (J < 0.30) on the same market.

| V6 sleeve | market | n | 28d proj | duplicates_v7 | partials_v7 | compatible_v7 |
|-----------|--------|--:|---------:|--------------:|------------:|--------------:|
| `BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6` | BTC 15m | 526 | $-238 | 1 | 0 | 0 |
| `BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6` | BTC 15m | 353 | $2106 | 0 | 0 | 1 |
| `BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6` | BTC 15m | 359 | $390 | 0 | 0 | 1 |
| `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6` | ETH 15m | 63 | $460 | 5 | 0 | 0 |
| `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6` | ETH 15m | 90 | $582 | 2 | 1 | 2 |
| `ETH_5M_BB_MP_HURST_BAND_V6` | ETH 5m | 162 | $1356 | 4 | 0 | 1 |
| `ETH_5M_CLOUD_RIBBON_MP_HURST_V6` | ETH 5m | 481 | $1878 | 3 | 0 | 2 |
| `ETH_5M_V5_REPL_OFF120_V6` | ETH 5m | 120 | $366 | 0 | 0 | 5 |
| `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6` | SOL 15m | 336 | $779 | 5 | 0 | 0 |
| `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6` | SOL 15m | 749 | $1399 | 5 | 0 | 0 |
| `SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6` | SOL 5m | 183 | $584 | 0 | 0 | 5 |
| `SOL_5M_F7_MFI_EMA200_VWAP_V6` | SOL 5m | 144 | $450 | 0 | 0 | 5 |
| `SOL_5M_F7_MP_EMA200_VWAP_V6` | SOL 5m | 189 | $585 | 0 | 0 | 5 |

### V6 sleeves SAFE to keep alongside V7 additions (no V7 duplicates)

- `BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6` (BTC 15m, n=353, 28d=$2106)
- `BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6` (BTC 15m, n=359, 28d=$390)
- `ETH_5M_V5_REPL_OFF120_V6` (ETH 5m, n=120, 28d=$366)
- `SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6` (SOL 5m, n=183, 28d=$584)
- `SOL_5M_F7_MFI_EMA200_VWAP_V6` (SOL 5m, n=144, 28d=$450)
- `SOL_5M_F7_MP_EMA200_VWAP_V6` (SOL 5m, n=189, 28d=$585)

### V6 sleeves with V7 DUPLICATES (must coordinate to avoid double-counting)

- `BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6` (BTC 15m, n=526, 28d=$-238)
    - DUPLICATE: BTC_15M_V7_BASELINE (J=1.00, cov=1.00)
- `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6` (ETH 15m, n=63, 28d=$460)
    - DUPLICATE: ETH_15M_V7_PG_RV_ABOVE_MED (J=0.89, cov=1.00)
    - DUPLICATE: ETH_15M_V7_PG_VOL_EXTREME_CORE (J=0.54, cov=0.95)
    - DUPLICATE: ETH_15M_V7_PG_VOL_EXTREME_TS (J=0.56, cov=1.00)
    - DUPLICATE: ETH_15M_V7_PI_S1_BTC_15M_TREND (J=0.81, cov=0.90)
    - DUPLICATE: ETH_15M_V7_PI_S1_TS_AND_BTC_15M (J=0.90, cov=1.00)
- `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6` (ETH 15m, n=90, 28d=$582)
    - DUPLICATE: ETH_15M_V7_PI_S1_BTC_15M_TREND (J=0.57, cov=0.88)
    - DUPLICATE: ETH_15M_V7_PI_S1_TS_AND_BTC_15M (J=0.52, cov=0.88)
- `ETH_5M_BB_MP_HURST_BAND_V6` (ETH 5m, n=162, 28d=$1356)
    - DUPLICATE: ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP (J=0.95, cov=0.98)
    - DUPLICATE: ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING (J=0.19, cov=0.91)
    - DUPLICATE: ETH_5M_V7_C3_V6C3_PARENT_RANGING (J=0.32, cov=0.89)
    - DUPLICATE: ETH_5M_V7_C5_CLOUD_HURST_VWAP_PARENT (J=0.52, cov=0.90)
- `ETH_5M_CLOUD_RIBBON_MP_HURST_V6` (ETH 5m, n=481, 28d=$1878)
    - DUPLICATE: ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP (J=0.32, cov=0.96)
    - DUPLICATE: ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING (J=0.55, cov=0.90)
    - DUPLICATE: ETH_5M_V7_C3_V6C3_PARENT_RANGING (J=0.91, cov=1.00)
- `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6` (SOL 15m, n=336, 28d=$779)
    - DUPLICATE: SOL_15M_V7_S1_BTC_ADX_VOLLOW (J=0.12, cov=1.00)
    - DUPLICATE: SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2 (J=0.12, cov=1.00)
    - DUPLICATE: SOL_15M_V7_S3_XADX_ETHVOLLOW (J=0.15, cov=1.00)
    - DUPLICATE: SOL_15M_V7_S5_BTC_SLOPE_STR (J=0.31, cov=1.00)
    - DUPLICATE: SOL_15M_V7_S5_BTC_SLOPE_STR_V2 (J=0.31, cov=1.00)
- `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6` (SOL 15m, n=749, 28d=$1399)
    - DUPLICATE: SOL_15M_V7_S1_BTC_ADX_VOLLOW (J=0.05, cov=0.90)
    - DUPLICATE: SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2 (J=0.05, cov=0.90)
    - DUPLICATE: SOL_15M_V7_S3_XADX_ETHVOLLOW (J=0.07, cov=0.94)
    - DUPLICATE: SOL_15M_V7_S5_BTC_SLOPE_STR (J=0.12, cov=0.89)
    - DUPLICATE: SOL_15M_V7_S5_BTC_SLOPE_STR_V2 (J=0.12, cov=0.89)

## 5. V7 sleeves that are REDUNDANT with already-shadowed V6

- `ETH_15M_V7_PI_S1_BTC_15M_TREND` — duplicates `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6`, `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`
- `ETH_15M_V7_PI_S1_TS_AND_BTC_15M` — duplicates `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6`, `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`
- `ETH_15M_V7_PG_RV_ABOVE_MED` — duplicates `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6`, `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`
- `ETH_15M_V7_PG_VOL_EXTREME_CORE` — duplicates `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6`, `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`
- `ETH_15M_V7_PG_VOL_EXTREME_TS` — duplicates `ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6`, `ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`
- `SOL_15M_V7_S3_XADX_ETHVOLLOW` — duplicates `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6`, `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6`
- `SOL_15M_V7_S5_BTC_SLOPE_STR_V2` — duplicates `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6`, `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6`
- `SOL_15M_V7_S5_BTC_SLOPE_STR` — duplicates `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6`, `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6`
- `SOL_15M_V7_S1_BTC_ADX_VOLLOW` — duplicates `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6`, `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6`
- `SOL_15M_V7_S1_BTC_ADX_VOLLOW_V2` — duplicates `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6`, `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6`
- `ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING` — duplicates `ETH_5M_BB_MP_HURST_BAND_V6`, `ETH_5M_CLOUD_RIBBON_MP_HURST_V6`
- `ETH_5M_V7_C3_V6C3_PARENT_RANGING` — duplicates `ETH_5M_BB_MP_HURST_BAND_V6`, `ETH_5M_CLOUD_RIBBON_MP_HURST_V6`
- `ETH_5M_V7_C1_CLOUD_VWAP_HURST_MP` — duplicates `ETH_5M_BB_MP_HURST_BAND_V6`, `ETH_5M_CLOUD_RIBBON_MP_HURST_V6`
- `ETH_5M_V7_C5_CLOUD_HURST_VWAP_PARENT` — duplicates `ETH_5M_BB_MP_HURST_BAND_V6`, `ETH_5M_CLOUD_RIBBON_MP_HURST_V6`
- `BTC_15M_V7_BASELINE` — duplicates `BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6`

**Total V7 sleeves redundant with shadowed V6: 15**

## 6. Recommended final roster (after dedup)

Total kept sleeves: **25**  
Combined 28d const-$25 PnL: **$41,423**

Per-version count:
- V5: 10 sleeves
- V6: 4 sleeves
- V7: 11 sleeves

Full final roster (sorted by version+market+sleeve):

| version | sleeve_id | asset | tf | n | WR% | $/tr | 28d proj |
|---------|-----------|-------|----|--:|----:|-----:|---------:|
| V5 | `BTC_15M_EMA50_EMA800_OFF600_DOWN_V5` | BTC | 15m | 917 | 76.3 | $1.07 | $832 |
| V5 | `BTC_15M_REGIME_TRSTACK_OFF480_UP_V5` | BTC | 15m | 212 | 84.0 | $1.89 | $340 |
| V5 | `BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5` | BTC | 5m | 357 | 90.2 | $11.50 | $3482 |
| V5 | `ETH_15M_TRSTACK_VWAP_OFFEARLY_V5` | ETH | 15m | 467 | 67.9 | $3.10 | $1229 |
| V5 | `ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5` | ETH | 5m | 124 | 85.5 | $3.74 | $393 |
| V5 | `ETH_5M_TR200_MP_MPNX_SMS_OFF120_V5` | ETH | 5m | 16 | 75.0 | $3.47 | $47 |
| V5 | `SOL_15M_RFAGED_TRSTACK_LATE_V5` | SOL | 15m | 297 | 85.5 | $0.91 | $230 |
| V5 | `SOL_15M_TRSTACK_VOL_RIBBON_EMA_MID_V5` | SOL | 15m | 103 | 73.8 | $2.52 | $220 |
| V5 | `SOL_5M_DEPTH_UP_HOD_SESSION_V5` | SOL | 5m | 90 | 91.1 | $4.03 | $308 |
| V5 | `SOL_5M_RF_TR_PP_MID_V5` | SOL | 5m | 126 | 84.1 | $4.00 | $427 |
| V6 | `BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6` | BTC | 15m | 353 | 73.4 | $7.03 | $2106 |
| V6 | `BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6` | BTC | 15m | 359 | 69.6 | $1.28 | $390 |
| V6 | `SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6` | SOL | 15m | 749 | 79.7 | $2.20 | $1399 |
| V6 | `SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6` | SOL | 5m | 183 | 82.0 | $3.76 | $584 |
| V7 | `BTC_5M_V7_T1_PARENT15M_REGIME` | BTC | 5m | 712 | 86.1 | $5.51 | $3331 |
| V7 | `BTC_5M_V7_T2_PARENT15M_SLOPE` | BTC | 5m | 557 | 79.0 | $8.67 | $4100 |
| V7 | `BTC_5M_V7_T3_OFI_TS` | BTC | 5m | 689 | 94.6 | $2.82 | $1651 |
| V7 | `BTC_5M_V7_T4_HURST_TS_HAWKES` | BTC | 5m | 1414 | 92.4 | $4.66 | $5588 |
| V7 | `BTC_5M_V7_T5_PARENT15M_NOTRANGING_MPSKEW` | BTC | 5m | 343 | 93.6 | $9.37 | $2726 |
| V7 | `ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING` | ETH | 5m | 748 | 79.4 | $3.89 | $2467 |
| V7 | `ETH_5M_V7_C4_XA_3SOURCE_PARENT_RANGING` | ETH | 5m | 105 | 72.4 | $9.52 | $849 |
| V7 | `SOL_5M_V7_S1_BTC_TREND_CCI_HURST_REV` | SOL | 5m | 661 | 72.6 | $4.70 | $2634 |
| V7 | `SOL_5M_V7_S2_BTC_F7_OVERBOUGHT_EMA800_VWAP` | SOL | 5m | 1068 | 72.5 | $2.05 | $1855 |
| V7 | `SOL_5M_V7_S3_BTC_F7_AGAINST_CCI_HURST_REV` | SOL | 5m | 882 | 72.8 | $4.16 | $3114 |
| V7 | `SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT` | SOL | 5m | 725 | 79.9 | $1.82 | $1121 |

## 7. Unreproducible sleeves (excluded from audit)

- `SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP30_70_V6` — missing gates: ['g_entry_vwap_in_30_70']
- `BTC_15M_V7_PLUS_ETH_SLOPE` — missing gates: ['g_eth_slope_with']
- `BTC_15M_V7_PLUS_PARENT_1H_RANGING` — missing gates: ['g_parent_1h_ranging']

## 8. Output files

- `sleeve_registry.csv` — all 58 sleeves defined
- `sleeve_summary.csv` — per-sleeve aggregate (n, WR, $/tr, 28d proj)
- `fired_by_sleeve.parquet` — per-fire records (18,270 fires)
- `sleeve_fire_matrix.parquet` — wide matrix (rows = unique fires, cols = sleeves)
- `pairwise_overlap_jaccard.csv` — long-form pairwise overlap (1540 pairs)
- `pairwise_jaccard_fire.csv` — NxN wide matrix
- `pairwise_jaccard_slug.csv` — NxN wide matrix
- `heatmap_jaccard_fire.png` / `heatmap_jaccard_slug.png` — visual heatmaps
- `redundancy_clusters.csv` — cluster assignments + kept/dropped flag
- `deploy_compatibility.csv` — V6-in-shadow compatibility analysis
- `final_roster.csv` — recommended deploy roster (25 sleeves)
- `unreproducible_sleeves.csv` — sleeves excluded from audit (3 sleeves)

---
END OF REPORT