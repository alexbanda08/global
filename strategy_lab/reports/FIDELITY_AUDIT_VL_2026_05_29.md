# Fidelity Audit — VL Spread-Loose Variants — 2026-05-29

**Source of truth:**
- Live: `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py` (VPS3, read-only)
- Controller: `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py` (VPS3)
- Spec: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md` §4

**Constants confirmed:**
- `_SPREAD_VL_ETH = Decimal("0.025")` (line 181)
- `_SPREAD_VL_SOL_15M = Decimal("0.030")` (line 182)

---

## 1. Per-VL Fidelity Table

| # | VL sleeve_id (short) | Parent | spread_filter spec | spread_filter live | Gates identical to parent? | Verdict |
|---|----------------------|--------|-------------------|--------------------|---------------------------|---------|
| 1 | eth_5m_k_hurst_ts_cci_tod_euus_v8_vL | v8 (line 858) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 4 gates: hurst_regime_with, trend_slope_with, cci_with, tod_europe_us_window; offsets=(120,) | PASS |
| 2 | eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL | v8 (line 871) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 4 gates: tr_above_ema50, hurst_regime_with, grandparent_trend_with, q_prev15m_agrees; offsets=(60,) | PASS |
| 3 | eth_5m_ema50_hurst_parent15mrang_v7_vL | v7 (line 696) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 3 gates: tr_above_ema50, hurst_trending, parent15m_ranging; offsets=(60,) | PASS |
| 4 | eth_5m_cloud_ribbon_mp_hurst_v6_vL | v6 (line 459) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 4 gates: tr_above_cloud, ribbon_agrees, mp_skew_with, hurst_trending; offsets=(60,) | PASS |
| 5 | eth_5m_v6c3_parent15mrang_v7_vL | v7 (line 708) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 5 gates: tr_above_cloud, ribbon_agrees, mp_skew_with, hurst_trending, parent15m_ranging; offsets=(60,) | PASS |
| 6 | eth_5m_bb_mp_hurst_band_v6_vL | v6 (line 485) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 4 gates: bb_pos_with, mp_skew_with, hurst_trending, entry_vwap_in_band; offsets=(60,) | PASS |
| 7 | eth_5m_cloud_vwap_hurstmp_v7_vL | v7 (line 684) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 3 gates: tr_above_cloud, entry_vwap_in_band, hurst_mp_trend_with; offsets=(60,) | PASS |
| 8 | eth_15m_trstack_vwap_vol_offearly_vL | V5 (line 388) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 4 gates: tr_stack_full_with, above_1h_dailyvwap_with, offset_early, vol_high(ETH,15m); offsets=(0,30,60) | PASS |
| 9 | eth_15m_trstack_vwap_vol_offearly_band_v6_vL | v6 (line 538) | 0.025 | `_SPREAD_VL_ETH` = 0.025 | Y — 5 gates: tr_stack_full_with, above_1h_dailyvwap_with, offset_early, vol_high(ETH,15m), entry_vwap_in_30_70; offsets=(0,30,60) | PASS |
| 10 | sol_15m_trstack_vol_ribbon_ema_mid_vL | V5 (line 425) | 0.030 | `_SPREAD_VL_SOL_15M` = 0.030 | Y — 5 gates: tr_stack_full_with, vol_high(SOL,15m), ribbon_agrees, tr_above_ema200, tr_above_ema800; offsets=(120,180,240) | PASS |
| 11 | sol_15m_rfaged_trstack_late_vL | V5 (line 443) | 0.030 | `_SPREAD_VL_SOL_15M` = 0.030 | Y — 3 gates: rf_aged, tr_stack_full_with, tr_stack_with; offsets=(480,600,720,840); notional_usd_override=5.0 preserved | PASS |

---

## 2. Bugs Found

**None.** Zero gate/offset/direction/flag differences detected across all 11 VL sleeves vs their parents. Every VL sleeve differs from its parent in exactly two ways: `sleeve_id` (appended `_vL`) and `spread_filter` (loosened to `_SPREAD_VL_ETH` or `_SPREAD_VL_SOL_15M`).

---

## 3. Controller — spread_filter Per-Sleeve Confirmation

Controller `polymarket_sniper_v5.py` line 334:
```python
sf = float(sleeve.spread_filter)
if spread is not None and spread > sf:
    ...skip_reason=f"spread_bidask_too_wide_{spread:.4f}_>_{sf:.4f}"
```
`sleeve.spread_filter` is read per-instance at evaluation time. VL sleeves pass their `_SPREAD_VL_ETH`/`_SPREAD_VL_SOL_15M` constant into this path. Controller honors per-sleeve spread_filter correctly.

---

## 4. Notes / Inherited Bugs

**VL_08 inherits g_vol_high rv_60 scale bug from its V5 parent** (`eth_15m_trstack_vwap_vol_offearly`). This is a parent-level defect, not a VL-specific issue. VL_08 is a faithful copy — the bug is correctly inherited. Same applies to VL_09 which inherits from the v6 parent that also uses `g_vol_high(ETH,15m)`.

**SOL 15m spread_filter naming**: the constant is `_SPREAD_VL_SOL_15M` (not `_SPREAD_VL_SOL`). Both SOL VL sleeves use this constant correctly.

---

## 5. Audit Summary

All 11 VL sleeves pass fidelity check. No bugs. Each is an exact copy of its parent with only `sleeve_id` and `spread_filter` changed, matching the spec precisely.
