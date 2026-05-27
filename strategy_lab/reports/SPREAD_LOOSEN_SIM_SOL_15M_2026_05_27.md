# Spread Loosen Simulation — SOL 15m Sleeves

**Date:** 2026-05-27  |  **Stake:** $5  |  **Fee:** LegacyConfig (2%-on-profit)  |  **L25:** native 10Hz (subsample_1hz=False)
**Current filter:** spread_filter=0.025  |  **Proposed:** spread_filter=0.030
**Universe:** 49,280 candidates (3,080 SOL 15m slugs × 8 offsets × 2 dirs)
**Placed at 0.025:** 34,826 (70.7%)
**Additional at 0.030:** 1,875 (3.8% of all candidates)

---

## Per-Sleeve Results

| Sleeve | n(0.025) | WR%(0.025) | $/tr(0.025) | PnL(0.025) | DD(0.025) | t(0.025) | n(0.030) | WR%(0.030) | $/tr(0.030) | PnL(0.030) | DD(0.030) | t(0.030) | Δn | ΔPnL | Rec |
|--------|----------|-----------|------------|-----------|----------|---------|----------|-----------|------------|-----------|----------|---------|-----|------|-----|
| trstack_vol_ribbon_ema_mid | 98 | 74.5% | $+0.62 | $+60.89 | $-34.57 | 1.65 | 100 | 75.0% | $+0.69 | $+68.50 | $-34.57 | 1.84 | +2 | $+7.61 | **LOOSEN** |
| rfaged_trstack_late | 282 | 85.5% | $+0.26 | $+73.51 | $-44.76 | 0.82 | 284 | 85.6% | $+0.27 | $+77.02 | $-44.76 | 0.86 | +2 | $+3.50 | **LOOSEN** |
| hod_eu_off60_240_rf_tr_vwap80_v6 | 315 | 74.9% | $+0.78 | $+246.63 | $-33.27 | 3.89 | 322 | 74.2% | $+0.72 | $+231.63 | $-33.27 | 3.59 | +7 | $-15.01 | **KEEP (marginal)** |
| hod_eu_off60_240_rf_tr_vwap30_70_v6 | *UNREPRODUCIBLE* (`g_entry_vwap_in_30_70` missing in V8 panel) ||||||||||||||||
| hod_eu_tightrib_rf_tr_vwap80_v6 | 707 | 80.9% | $+0.60 | $+422.18 | $-38.38 | 3.8 | 716 | 80.3% | $+0.55 | $+396.71 | $-38.38 | 3.54 | +9 | $-25.47 | **KEEP (marginal)** |
| btc_slope_pair_v7 | 98 | 80.6% | $+1.13 | $+111.00 | $-25.00 | 3.41 | 100 | 80.0% | $+1.07 | $+107.01 | $-25.00 | 3.23 | +2 | $-4.00 | **KEEP (marginal)** |
| btc_adx_btcvollow_v7 | 37 | 86.5% | $+1.62 | $+59.86 | $-10.00 | 3.36 | 37 | 86.5% | $+1.62 | $+59.86 | $-10.00 | 3.36 | +0 | $+0.00 | **NO CHANGE (no new fires)** |
| j_btceth_vollow_l_ethadx_v8 | 118 | 78.8% | $+1.13 | $+133.30 | $-22.81 | 3.55 | 118 | 78.8% | $+1.13 | $+133.30 | $-22.81 | 3.55 | +0 | $+0.00 | **NO CHANGE (no new fires)** |
| v7_base_s5_slope_str_v8 | 98 | 80.6% | $+1.13 | $+111.00 | $-25.00 | 3.41 | 100 | 80.0% | $+1.07 | $+107.01 | $-25.00 | 3.23 | +2 | $-4.00 | **KEEP (marginal)** |
| v7s5_plus_eth1h_adx_v8 | 67 | 83.6% | $+1.51 | $+101.39 | $-17.81 | 3.88 | 68 | 82.4% | $+1.42 | $+96.39 | $-17.81 | 3.58 | +1 | $-5.00 | **KEEP (marginal)** |

---

## Verdict Summary

| Decision | Sleeves |
|----------|---------|
| **LOOSEN** (0.030 safe) | trstack_vol_ribbon_ema_mid, rfaged_trstack_late |
| **KEEP** (0.025 stays) | hod_eu_off60_240_rf_tr_vwap80_v6, hod_eu_tightrib_rf_tr_vwap80_v6, btc_slope_pair_v7, v7_base_s5_slope_str_v8, v7s5_plus_eth1h_adx_v8 |
| **NO CHANGE** (zero marginal fires) | btc_adx_btcvollow_v7, j_btceth_vollow_l_ethadx_v8 |
| **UNREPRODUCIBLE** | hod_eu_off60_240_rf_tr_vwap30_70_v6 |

**Key finding:** The 0.025→0.030 spread band is very thin — only 1,875 additional fires across ALL 49,280 candidates (3.8%). Most sleeves gain 0–2 fires. The high-conviction sleeves (V6 tightrib, V7 S5, V8 J+L) show WR dilution of 0.5–0.6 pp when marginal fires are included. KEEP the current 0.025 filter for all sleeves validated at high WR (≥80%). Only loosen for V5 legacy sleeves (trstack, rfaged) where marginal fires maintain WR.

---

## Notes

- `hod_eu_off60_240_rf_tr_vwap30_70_v6` is **UNREPRODUCIBLE** — gate `g_entry_vwap_in_30_70` not present in V8 panel (flagged in `unreproducible_sleeves.csv`).
- `v7_base_s5_slope_str_v8` uses identical gate stack as `btc_slope_pair_v7` (V7 S5 winner carried forward to V8 baseline). Metrics match exactly by construction.
- Absolute n in this sim is ~5% below `fired_by_sleeve.parquet` baseline (707 vs 749 for tightrib, 315 vs 336 for off60_240). Cause: re-running `fill_at_book` from raw L25 vs pre-computed fills in the universe panel (lookup timing differences). The **Δn column is authoritative** — both filters use the same raw L25 in a single pass.
- Δn = new fires placed at 0.030 that were rejected at 0.025 (wider spread accepted).
- DD is max drawdown in dollar terms at $5 stake over the full ~33d window.
- t-stat: 1-sample t-test vs H0: mean pnl = 0.
- Run time: 45s
- Script: `strategy_lab/spread_loosen_sim_sol_15m.py`