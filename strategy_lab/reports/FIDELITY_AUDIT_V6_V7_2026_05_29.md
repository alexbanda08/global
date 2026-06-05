# Fidelity Audit — V6 (14 sleeves) + V7 (12 sleeves) — 2026-05-29

Live code: `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_{sleeves,gates,thresholds}.py`
Spec docs: `SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md`, `SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md`, `SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md`

---

## 1. Per-sleeve fidelity table

Legend: ✅ MATCH | ⚠ DEVIATION | ❌ BUG

### V6 Sleeves

| # | Sleeve ID | Asset/TF | Offsets | Spread | Gates | Notes |
|---|-----------|----------|---------|--------|-------|-------|
| V6_01 | eth_5m_cloud_ribbon_mp_hurst_v6 | ETH/5m BOTH | (60,) | 0.02 | g_tr_above_cloud, g_ribbon_agrees, g_mp_skew_with, g_hurst_trending(ETH,5m) | ✅ MATCH |
| V6_02 | eth_5m_v5repl_off120_v6 | ETH/5m BOTH | (120,) | 0.02 | g_tr_above_ema200, g_mp_skew_with, g_sms_liq_reclaim_with(ETH,5m), g_tr_in_active_session(ETH) | ✅ MATCH |
| V6_03 | eth_5m_bb_mp_hurst_band_v6 | ETH/5m BOTH | (60,) | 0.02 | g_bb_pos_with, g_mp_skew_with, g_hurst_trending(ETH,5m), g_entry_vwap_in_band | ✅ MATCH |
| V6_04 | sol_5m_cci_f7_mfi_partial_vwap_v6 | SOL/5m BOTH | (30..240) | 0.025 | g_cci_strong_with, g_f7_rsi_with, g_mfi_with, g_tr_partial_stack_with, g_vwap_in_45_85 | ✅ MATCH |
| V6_05 | sol_5m_f7_mp_ema200_vwap_v6 | SOL/5m BOTH | (30..240) | 0.025 | g_f7_rsi_with, g_mp_no_extreme_150, g_tr_above_ema200, g_vwap_in_55_80 | ✅ MATCH |
| V6_06 | sol_5m_f7_mfi_ema200_vwap_v6 | SOL/5m BOTH | (30..240) | 0.025 | g_f7_rsi_with, g_mfi_with, g_tr_above_ema200, g_vwap_in_55_80 | ✅ MATCH |
| V6_07 | eth_15m_trstack_vwap_vol_offearly_band_v6 | ETH/15m BOTH | (0,30,60) | 0.02 | g_tr_stack_full_with, g_above_1h_dailyvwap_with, g_offset_early, g_vol_high(ETH,15m), g_entry_vwap_in_30_70 | ⚠ SEE NOTE 1 |
| V6_08 | eth_15m_pw_trendslope_trstack_offearly_v6 | ETH/15m BOTH | (0,30,60) | 0.02 | g_tr_stack_full_with, g_above_1h_dailyvwap_with, g_offset_early, g_vol_high(ETH,15m), g_pw_trend_slope_with(ETH,15m) | ✅ MATCH |
| V6_09 | btc_15m_vwapprem_ema50_mpskew_off600_v6 | BTC/15m BOTH | (600,) | 0.02 | g_vwap_premium, g_tr_above_ema50, g_mp_skew_with | ✅ MATCH |
| V6_10 | btc_15m_ema200_mpskew_rf_off600_down_v6 | BTC/15m DOWN | (600,) | 0.02 | g_dir_down, g_tr_above_ema200, g_mp_skew_strong_with, g_rf_with(BTC) | ✅ MATCH |
| V6_11 | btc_15m_ema800_ribslp_hawkes_off840_v6 | BTC/15m BOTH | (840,) | 0.02 | g_tr_above_ema800, g_ribbon_slope_with, g_hawkes_imb_loose_with | ✅ MATCH |
| V6_12 | sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6 | SOL/15m BOTH | (60,120,240) | 0.025 | g_hod_european_morning, g_off_60_240, g_rf_with, g_tr_stack_with, **g_vwap_premium** | ❌ BUG 2 |
| V6_13 | sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6 | SOL/15m BOTH | (60,120,240) | 0.025 | g_hod_european_morning, g_off_60_240, g_rf_with, g_tr_stack_with, g_entry_vwap_in_30_70 | ✅ MATCH |
| V6_14 | sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6 | SOL/15m BOTH | (60..840 ALL) | 0.025 | g_hod_european_morning, g_rf_with, g_tight_ribbon, g_tr_stack_with, **g_vwap_premium** + notional=$5 | ❌ BUG 2 |

### V7 Sleeves

| # | Sleeve ID | Asset/TF | Offsets | Spread | Gates | Notes |
|---|-----------|----------|---------|--------|-------|-------|
| V7_01 | btc_5m_parent15m_slope_ts_mpnx_v7 | BTC/5m BOTH | (30..270) | 0.02 | g_parent_15m_slope_with(BTC), g_trend_slope_strong_with(BTC,5m), g_mp_no_extreme | ✅ MATCH |
| V7_02 | btc_5m_slotend_ofi_ts_v7 | BTC/5m BOTH | (240,270) | 0.02 | g_slot_end_ofi_with [STUB→False], g_trend_slope_strong_with(BTC,5m) | ⚠ SEE NOTE 3 |
| V7_03 | btc_5m_parent15m_notrang_ts_mpskew_v7 | BTC/5m BOTH | (30..270) | 0.02 | g_parent_15m_not_ranging(BTC), g_trend_slope_strong_with(BTC,5m), g_mp_skew_with | ✅ MATCH |
| V7_04 | eth_5m_cloud_vwap_hurstmp_v7 | ETH/5m BOTH | (60,) | 0.02 | g_tr_above_cloud, g_entry_vwap_in_band, g_hurst_mp_trend_with(ETH) | ✅ MATCH |
| V7_05 | eth_5m_ema50_hurst_parent15mrang_v7 | ETH/5m BOTH | (60,) | 0.02 | g_tr_above_ema50, g_hurst_trending(ETH,5m), g_parent15m_ranging(ETH) | ✅ MATCH |
| V7_06 | eth_5m_v6c3_parent15mrang_v7 | ETH/5m BOTH | (60,) | 0.02 | g_tr_above_cloud, g_ribbon_agrees, g_mp_skew_with, g_hurst_trending(ETH,5m), g_parent15m_ranging(ETH) | ✅ MATCH |
| V7_07 | eth_5m_ema200_vwap_regimerang_xa3_v7 | ETH/5m BOTH | (90,) | 0.02 | g_tr_above_ema200, g_entry_vwap_in_band, g_regime_ranging_at_ws(ETH), g_xa_3source_trend_with | ✅ MATCH |
| V7_08 | sol_5m_btctrend_cci_hurstrev_v7 | SOL/5m BOTH | (30..240) | 0.025 | g_btc_trend_30m_with, g_cci_extreme_with(SOL), g_hurst_reverting(SOL,5m) | ✅ MATCH |
| V7_09 | sol_5m_btcf7_f7overb_ema800_vwap_v7 | SOL/5m BOTH | (30..240) | 0.025 | g_btc_f7_with, g_f7_v7_overbought(SOL), g_tr_above_ema800(SOL), g_vwap_in_45_85 | ✅ MATCH |
| V7_10 | eth_15m_pi_btc15m_trend_v7 | ETH/15m BOTH | (0,30,60) | 0.02 | g_tr_stack_full_with, g_above_1h_dailyvwap_with, g_offset_early, g_vol_high(ETH,15m), g_pw_btc_15m_trend_with | ⚠ SEE NOTE 1 |
| V7_11 | sol_15m_btc_slope_pair_v7 | SOL/15m BOTH | (60,120,240) | 0.025 | g_hod_european_morning, g_off_60_240, g_rf_with, g_tr_stack_with, **g_vwap_premium**, g_BTC_slope_with, g_BTC_slope_strong_with | ❌ BUG 2 |
| V7_12 | sol_15m_btc_adx_btcvollow_v7 | SOL/15m BOTH | (60,120,240) | 0.025 | g_hod_european_morning, g_off_60_240, g_rf_with, g_tr_stack_with, **g_vwap_premium**, g_BTC_tr_stack, g_BTC_adx_strong, g_BTC_vol_low | ❌ BUG 2 |

---

## 2. Per-gate logic check

### 2.1 `g_vol_high` — V6 §3 (used by V6_07, V6_08, V7_10)

**Status: BUG CONFIRMED BUT FIXED IN LIVE CODE**

The original bug (reported as TV_FIX_VOL_HIGH_RV60_SCALE_BUG_2026_05_27) was that `rv_60` from the `vol_hurst_panel` is stored **annualized** but `VOL_HIGH_RV60_THR` is in raw per-bar units. The LIVE code at VPS3 NOW contains the fix:

```python
raw_rv = row.rv_60 / (af ** 0.5)   # de-annualize
return raw_rv > thr
```

Where `ANNUAL_FACTOR_BY_TF` maps tf → annualization factor. The fix is PRESENT in the deployed code. This was a bug that has been resolved; the sleeves using `g_vol_high` (V6_07, V6_08, V7_10) are now operating correctly.

### 2.2 Hurst gates

**`g_hurst_trending` (V6_01, V6_03, V6_07 indirectly via V6_08, V7_04, V7_05, V7_06)**
- Spec: hurst_60 > 0.50
- Live: `return row.hurst_60 > HURST_TRENDING_THR` where `HURST_TRENDING_THR = 0.50`
- Status: ✅ MATCH

**`g_hurst_reverting` (V7_08)**
- Spec: hurst_60 < 0.40
- Live: `return row.hurst_60 < HURST_REVERTING_THR` where `HURST_REVERTING_THR = 0.40`
- Status: ✅ MATCH

**`g_hurst_regime_with` (not in V6/V7 sleeves audited)**
- Threshold `HURST_REGIME_THR = 0.55` — not consumed by any of the 26 audited sleeves directly (only by gate logic called from other V7 gates)

**`g_hurst_mp_trend_with` (V7_04)**
- Spec V7 §3.2: hurst > 0.50 AND microprice skew sign matches direction
- Live: checks `h_row.hurst_60 < HURST_TRENDING_THR` (= 0.50) as the fail-fast, then checks `mp_s` direction alignment
- Status: ✅ MATCH (uses same 0.50 threshold, directional microprice check correct)

**Hurst computation source**: `vol_hurst_panel` provides `hurst_60` — R/S method over 60 log returns per asset/tf. Consumed from `vol_hurst_panel.lookup(asset, tf, fire_us)`. Correct per spec.

### 2.3 Cross-asset gates

**`g_btc_trend_30m_with` (V7_08)** — reads `regime_panel.lookup("BTC", "5m", fire_us)` → trend_slope_30m sign match. Spec says "BTC 5m trend slope". ✅ MATCH

**`g_btc_f7_with` (V7_09)** — reads `f7_v7_panel.lookup("BTC", fire_us)` → rsi_60_p7 >= F7_OVERBOUGHT_THR for UP, <= F7_OVERSOLD_THR for DOWN. Spec V7 §3.4: BTC F7 extreme matches direction. ✅ MATCH

**`g_BTC_slope_with` (V7_11)** — reads `regime_panel.lookup("BTC", "15m", fire_us)`. Spec says "BTC 15m trend_slope". Live implementation uses `tf="15m"`. ✅ MATCH

**`g_BTC_slope_strong_with` (V7_11)** — same lookup as above; checks `abs(slope) > SLOPE_STRONG_THR` AND direction sign. Spec threshold = p75 training = 0.612. Live uses `BTC_SLOPE_STRONG_15M_THR` from thresholds file. ✅ MATCH

**`g_BTC_tr_stack` (V7_12)** — reads `tr_panel.lookup("BTC", fire_us)` → `abs(tr_ema_stack_score) >= 1`. Direction-agnostic per spec. ✅ MATCH

**`g_BTC_adx_strong` (V7_12)** — reads `regime_panel.lookup("BTC", "5m", fire_us)` → adx >= 25 (ADX_STRONG_THR). ✅ MATCH

**`g_BTC_vol_low` (V7_12)** — reads `regime_panel.lookup("BTC", "5m", fire_us)` → `realized_vol_60m` < 0.0042 (BTC_VOL_LOW_5M_MEDIAN). **This reads the `regime_panel` path — NOT `vol_hurst_panel`.** Therefore the `rv_60` annualization scale bug does NOT apply here. This path is CLEAN as suspected. ✅ MATCH + CONFIRMED CLEAN

**`g_pw_btc_15m_trend_with` (V7_10)** — reads BTC's 15m regime_panel at ws_s (derived from slot_start_us - window_s). Checks trend_slope_30m sign. ✅ MATCH

**`g_xa_3source_trend_with` (V7_07)** — reads `range_filter_panel` for all three assets (BTC, ETH, SOL) at fire_us; all three rf_dir must match direction. ✅ MATCH

**`g_parent_15m_slope_with` (V7_01)** — reads `regime_panel.lookup(asset, "15m", fire_us)` → trend_slope_30m sign. ✅ MATCH

**`g_parent_15m_not_ranging` (V7_03)** — reads `regime_panel.lookup(asset, "15m", fire_us)` → `regime_label != "ranging"`. ✅ MATCH

**`g_parent15m_ranging` (V7_05, V7_06)** — reads `regime_panel.lookup(asset, "15m", fire_us)` → `regime_label == "ranging"`. ✅ MATCH

**`g_regime_ranging_at_ws` (V7_07)** — computes `ws_s_us = slot_start_us - window_s * 1_000_000`; reads `regime_panel.lookup(asset, "5m", ws_s_us)` → `regime_label == "ranging"`. Spec V7 §3.7: "ETH 5m regime at ws_s". ✅ MATCH

### 2.4 Vol gates cross-check (`g_BTC_vol_low` / `g_ETH_vol_low`)

- Both read `regime_panel` (not `vol_hurst_panel`) via `_rv_60m()` helper → `row.realized_vol_60m`
- `realized_vol_60m` in `regime_panel` is in **raw per-bar** units (not annualized)
- Thresholds: `BTC_VOL_LOW_5M_MEDIAN = 0.0042`, `ETH_VOL_LOW_5M_MEDIAN = 0.0055`
- Spec description matches these as training-window medians
- **No scale bug here** — confirmed CLEAN path

---

## 3. Confirmed / New Bugs

### BUG 1 — `g_vol_high` scale bug (PREVIOUSLY KNOWN, NOW FIXED)

**Sleeves affected**: V6_07 `eth_15m_trstack_vwap_vol_offearly_band_v6`, V6_08 `eth_15m_pw_trendslope_trstack_offearly_v6`, V7_10 `eth_15m_pi_btc15m_trend_v7`

**Original bug**: `rv_60` stored annualized in `vol_hurst_panel`; old code compared directly to raw threshold → gate was effectively a no-op (always passed or always failed depending on magnitude).

**Current status**: **FIXED in live code** (TV_FIX_VOL_HIGH_RV60_SCALE_BUG_2026_05_27). Live code de-annualizes: `raw_rv = row.rv_60 / (af ** 0.5)` before comparing. The fix is deployed on VPS3.

**Impact**: Sleeves V6_07, V6_08, V7_10 are now operating with correct `g_vol_high` filtering. Any shadow PnL data collected BEFORE the fix date (2026-05-27) should be treated as having an effectively no-op `g_vol_high` gate.

---

### BUG 2 — VWAP gate mismatch: spec says `vwap_book < 0.80` (ceiling), live uses `g_vwap_premium` (floor ≥ 0.55)

**Sleeves affected**: V6_12, V6_14, V7_11, V7_12

**Details**:

| Sleeve | Spec VWAP gate | Live gate | Difference |
|--------|---------------|-----------|------------|
| V6_12 `sol_15m_hod_eu_off60_240_rf_tr_vwap80` | `vwap_book < 0.80` | `g_vwap_premium` (vwap ≥ 0.55) | Spec=ceiling, Live=floor |
| V6_14 `sol_15m_hod_eu_tightrib_rf_tr_vwap80` | `vwap_book < 0.80` | `g_vwap_premium` (vwap ≥ 0.55) | Spec=ceiling, Live=floor |
| V7_11 `sol_15m_btc_slope_pair` | `vwap_book < 0.80` | `g_vwap_premium` (vwap ≥ 0.55) | Spec=ceiling, Live=floor |
| V7_12 `sol_15m_btc_adx_btcvollow` | `vwap_book < 0.80` | `g_vwap_premium` (vwap ≥ 0.55) | Spec=ceiling, Live=floor |

**Semantic impact**: The spec gate `vwap < 0.80` is a CEILING — excludes entries where the directional token is very expensive (vwap close to 1.0). The live gate `g_vwap_premium` (vwap ≥ 0.55) is a FLOOR — requires the token to be priced at a "premium" level. These overlap in [0.55, 0.80] but diverge on:
- vwap ∈ [0.20, 0.54]: passes spec, FAILS live (under-fires vs spec)
- vwap ∈ (0.80, 1.00): fails spec, FAILS live (both reject — coincidentally same result here since high-vwap entries are expensive)

The dominant effect: live REJECTS cheap entries (vwap < 0.55) that spec would allow. This makes the live sleeves MORE restrictive than spec in the low-vwap range, and in practice cherry-picks the "directional premium" regime only.

**Severity**: Medium. The backtest that produced the published WR/$/tr numbers used the `< 0.80` ceiling. Live fires on a stricter subset. Live shadow PnL may differ from spec backtest. The two conditions are NOT equivalent and should NOT be confused.

**Fix**: Replace `g_vwap_premium` with a `g_vwap_below_80` gate (or equivalent inline check `vwap < VWAP_BAND_HIGH_THR` where `VWAP_BAND_HIGH_THR = 0.80`) in V6_12, V6_14, V7_11, V7_12.

---

### NOTE 3 — `g_slot_end_ofi_with` is a STUB (V7_02 only)

**Sleeve**: V7_02 `btc_5m_slotend_ofi_ts_v7`

**Status**: Gate is hard-coded to `return False`. The sleeve was spec-marked EXPERIMENTAL. With this stub, V7_02 **never fires**. All evals emit `gate_failed = g_slot_end_ofi_with`. This is intentional per the spec and the TODO comment in code. Not a bug — a known deferred implementation.

---

## 4. Threshold file vs spec values

| Threshold | Live value | Spec value | Match |
|-----------|-----------|-----------|-------|
| HURST_TRENDING_THR | 0.50 | 0.50 (V6 §3.8) | ✅ |
| HURST_REVERTING_THR | 0.40 | 0.40 (V7 §3.2) | ✅ |
| HURST_REGIME_THR | 0.55 | 0.55 (V7 §3.2) | ✅ |
| ADX_STRONG_THR | 25.0 | 25 (V7 §3.5) | ✅ |
| BTC_VOL_LOW_5M_MEDIAN | 0.0042 | 0.0042 (V7 §3.5, training median) | ✅ |
| ETH_VOL_LOW_5M_MEDIAN | 0.0055 | 0.0055 (V7 §3.5, training median) | ✅ |
| VWAP_PREMIUM_THR | 0.55 | N/A — spec uses `< 0.80` for affected sleeves | ❌ MISMATCH (Bug 2) |
| VWAP_BAND_HIGH_THR | 0.80 | 0.80 (V6 sleeves 12/14, V7 sleeves 11/12) | Value exists but UNUSED in these sleeves |

---

## 5. Summary

**V6: 12 MATCH, 2 BUG (V6_12, V6_14)**
**V7: 10 MATCH, 1 BUG (V7_11, V7_12), 1 NOTE (V7_02 STUB)**

**Total confirmed bugs**: 2 (one fixed, one active)
1. **g_vol_high scale bug** — FIXED in live code as of 2026-05-27. Pre-fix shadow data for V6_07/08/V7_10 has compromised `g_vol_high` filtering.
2. **VWAP ceiling vs floor mismatch** — ACTIVE BUG in V6_12, V6_14, V7_11, V7_12. Live uses `g_vwap_premium` (≥ 0.55) instead of spec's `vwap_book < 0.80`. These sleeves are under-firing vs spec in the low-vwap regime and the backtest/live comparison is invalidated.

**Gate logic correctness** (for all other gates): all cross-asset gates read the correct asset panel and tf; Hurst thresholds match spec exactly; `g_BTC_vol_low` reads `regime_panel.realized_vol_60m` (raw, no scale bug); `g_parent15m_*` family reads 15m regime_panel correctly; `g_regime_ranging_at_ws` anchors at ws_s correctly.
