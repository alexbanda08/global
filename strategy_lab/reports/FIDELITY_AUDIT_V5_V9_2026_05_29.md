# Fidelity Audit — V5 (16 sleeves) + V9 (10 sleeves) — 2026-05-29

Auditor: Claude agent (read-only VPS3 + local spec docs)
Sources:
- Live: `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py` (78 total `SniperV5Sleeve` entries)
- Live: `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py`
- Live: `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_thresholds.py`
- Live: `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`
- Spec V5: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_2026_05_27.md`
- Spec V9: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md`

---

## 1. Per-sleeve fidelity table

### V5 sleeves (16)

| # | sleeve_id (suffix) | Spec gates | Live gates | asset/tf/dir/offsets/spread | MATCH? | Notes |
|---|---|---|---|---|---|---|
| 01 | btc_5m_ts_mpskew_s6_0_60 | g_trend_slope_strong_with(BTC,5m), g_mp_skew_with | SAME | BTC/5m/BOTH/30/0.02, s6_precondition=True | **MATCH** | |
| 02 | btc_5m_ts_mpskew_any_off30 | g_trend_slope_strong_with(BTC,5m), g_mp_skew_with | SAME | BTC/5m/BOTH/30/0.02 | **MATCH** | |
| 03 | eth_5m_tr200_mp_sms_active_off120 | g_tr_above_ema200(ETH), g_mp_skew_with, g_sms_liq_reclaim_with(ETH,5m), g_tr_in_active_session(ETH) | SAME | ETH/5m/BOTH/120/0.02 | **MATCH** | |
| 04 | eth_5m_tr200_mp_mpnx_sms_off120 | g_tr_above_ema200(ETH), g_mp_skew_with, g_mp_no_extreme, g_sms_liq_reclaim_with(ETH,5m) | SAME | ETH/5m/BOTH/120/0.02 | **MATCH** | |
| 05 | eth_5m_cloud_mp_sms_active_off120 | g_tr_above_cloud(ETH), g_mp_skew_with, g_sms_liq_reclaim_with(ETH,5m), g_tr_in_active_session(ETH) | SAME | ETH/5m/BOTH/120/0.02 | **MATCH** | |
| 06 | sol_5m_depth_up_hod_session | g_depth_250_strict, g_dir_up, g_hod_us_afternoon, g_tr_in_active_session(SOL) | SAME | SOL/5m/UP/30,60,90/0.025 | **MATCH** | |
| 07 | sol_5m_rf_tr_pp_mid | g_rf_strict_align(SOL), g_tr_above_ema200(SOL), g_tr_above_pp(SOL), g_tr_partial_stack_with(SOL) | SAME | SOL/5m/BOTH/90,120,150,180/0.025 | **MATCH** | |
| 08 | sol_5m_rf_tr_partial_mid | g_rf_strict_align(SOL), g_tr_partial_stack_with(SOL) | SAME | SOL/5m/BOTH/90,120,150,180/0.025 | **MATCH** | |
| 09 | btc_15m_ts_trstack_off600_down | g_dir_down, g_tr_stack_full_with(BTC), g_trend_slope_with(BTC,15m) | SAME | BTC/15m/DOWN/600/0.02 | **MATCH** | |
| 10 | btc_15m_regime_trstack_off480_up | g_dir_up, g_regime_stack_with(BTC,15m), g_tr_stack_full_with(BTC) | SAME | BTC/15m/UP/480/0.02 | **MATCH** | |
| 11 | btc_15m_mpskew_trstack_off600_down | g_dir_down, g_mp_skew_strong_with, g_tr_stack_full_with(BTC) | SAME | BTC/15m/DOWN/600/0.02 | **MATCH** | |
| 12 | btc_15m_ema50_ema800_off600_down | g_dir_down, g_tr_above_ema50(BTC), g_tr_above_ema800(BTC) | SAME | BTC/15m/DOWN/600/0.02 | **MATCH** | |
| 13 | eth_15m_trstack_vwap_vol_offearly | g_tr_stack_full_with(ETH), g_above_1h_dailyvwap_with(ETH), g_offset_early, g_vol_high(ETH,15m) | SAME | ETH/15m/BOTH/0,30,60/0.02 | **MATCH** | g_vol_high FIXED (see Bug 1) |
| 14 | eth_15m_trstack_vwap_offearly | g_tr_stack_full_with(ETH), g_offset_early, g_above_1h_dailyvwap_with(ETH) | SAME | ETH/15m/BOTH/0,30,60/0.02 | **MATCH** | |
| 15 | sol_15m_trstack_vol_ribbon_ema_mid | g_tr_stack_full_with(SOL), g_vol_high(SOL,15m), g_ribbon_agrees(SOL), g_tr_above_ema200(SOL), g_tr_above_ema800(SOL) | SAME | SOL/15m/BOTH/120,180,240/0.025 | **MATCH** | g_vol_high FIXED (see Bug 1) |
| 16 | sol_15m_rfaged_trstack_late | g_rf_aged(SOL), g_tr_stack_full_with(SOL), g_tr_stack_with(SOL) | SAME | SOL/15m/BOTH/480,600,720,840/0.025, notional_usd_override=$5 | **MATCH** | |

**V5 result: 16/16 MATCH** (gates, thresholds, offsets, spread_filter, s6_precondition, notional_usd_override all correct)

---

### V9 sleeves (10)

| # | sleeve_id (suffix) | Spec gates | Live gates | MATCH? | Notes |
|---|---|---|---|---|---|
| V9_01 | btc_5m_a2_hlcascade100k_v9 | g_a2_hl_short_cascade(BTC,300s,100k) | SAME | **MATCH** | |
| V9_02 | btc_5m_up_a2_hlcascade50k_v9 | g_a2_hl_short_cascade(BTC,300s,50k), g_dir_up | SAME | **MATCH** | |
| V9_03 | btc_5m_down_b2_contrarian2k_v9 | g_b2_poly_flow_contrarian(DOWN,60s,2000), g_dir_down | SAME | **MATCH** | |
| V9_04 | btc_5m_up_b2_contrarian2k_v9 | g_b2_poly_flow_contrarian(UP,60s,2000), g_dir_up | SAME | **MATCH** | |
| V9_05 | sol_5m_b1_polyflow_aligned_v9 | g_b1_poly_flow_aligned(SOL,60s,500) | SAME | **MATCH** | direction=BOTH, offsets=30,60,90 |
| V9_06 | sol_5m_down_b1_500_v9 | g_b1_poly_flow_aligned(SOL,DOWN,60s,500), g_dir_down | SAME | **MATCH** | |
| V9_07 | sol_5m_down_b1_flow250_v9 | g_b1_poly_flow_aligned(SOL,DOWN,60s,250), g_dir_down | SAME | **MATCH** | |
| V9_08 | sol_5m_b3_abs500_v9 | g_b3_poly_flow_abs(60s,500) | SAME | **MATCH** | direction=BOTH |
| V9_09 | sol_5m_b1_120s_250_v9 | g_b1_poly_flow_aligned(SOL,120s,250) | SAME | **MATCH** | direction=BOTH |
| V9_10 | sol_5m_b3_abs500_no_opp_v9 | g_b3_poly_flow_abs(60s,500), NOT g_b2_poly_flow_contrarian(60s,500) | g_b3_poly_flow_abs(60s,500), g_b2_poly_flow_NOT_opposing(60s,500) | **MATCH** | Spec says NOT-wrapper; live implements via `g_b2_poly_flow_NOT_opposing` helper — semantically identical. Correct. |

**V9 result: 10/10 MATCH** (all gates, thresholds, offsets, spread_filter correct)

---

## 2. Per-gate logic check

### V5 core gates

| Gate | Live impl | Spec | Match? |
|---|---|---|---|
| g_trend_slope_strong_with | Lookup panel; True iff slope > TREND_SLOPE_P75_THR[(asset,tf)]. Values: BTC/5m=0.385, ETH/5m=0.398, SOL/5m=0.412, BTC/15m=0.612 | Same | MATCH |
| g_mp_skew_with | Microprice skew aligned with direction, threshold = MP_SKEW_BPS_THR | Per spec §3.3 | MATCH |
| g_tr_above_ema200/50/800/cloud/pp | Asset EMA comparisons via panel lookup | Per spec §3.5 | MATCH |
| g_rf_strict_align | Range filter direction alignment, stricter than g_rf_with | Per spec §3.4 | MATCH |
| g_rf_aged | RF present + age > RF_AGED_MIN_S | Per spec §3.4 | MATCH |
| g_depth_250_strict | Depth > DEPTH_250_STRICT_OTHER_MIN_USD; sleeve 06 only | Per spec §3.1 | MATCH |
| g_hod_us_afternoon | fire_us in HOD_US_AFTERNOON_UTC window | Per spec §3.12 | MATCH |
| g_regime_stack_with | Regime trending at ws_s + TR stack | Per spec §3.2 | MATCH |
| g_above_1h_dailyvwap_with | Asset above 1h daily VWAP | Per spec §3.10 | MATCH |
| g_offset_early | offset_s <= OFFSET_EARLY_MAX_S | Per spec §3.12 | MATCH |
| **g_vol_high** | `raw_rv = row.rv_60 / sqrt(ANNUAL_FACTOR_BY_TF[tf])` then `raw_rv > VOL_HIGH_RV60_THR[(asset,tf)]` | Spec says rv_60 threshold comparison | **MATCH (fixed)** — see Bug 1 |
| **g_vol_contracting** | `raw_rv = row.rv_60 / sqrt(ANNUAL_FACTOR_BY_TF[tf])` then `raw_rv < thr * 0.5` | Spec §3.9/V8§3.9 | **MATCH (fixed)** — see Bug 1 |
| g_ribbon_agrees | Ribbon direction alignment | Per spec §3.6 | MATCH |
| g_tr_stack_full_with / g_tr_stack_with | TR stack full/partial alignment | Per spec §3.5 | MATCH |
| g_tr_partial_stack_with | Partial stack condition | Per spec §3.5 | MATCH |
| g_sms_liq_reclaim_with | SMS liquidity reclaim | Per spec §3.8 | MATCH |
| g_tr_in_active_session | Active trading session time filter | Per spec §3.5 | MATCH |
| g_mp_no_extreme | Microprice not extreme beyond threshold | Per spec §3.3 | MATCH |
| g_tr_above_cloud | TR above Ichimoku cloud | Per spec §3.5 | MATCH |
| g_mp_skew_strong_with | Stronger microprice skew threshold | Per spec §3.3 | MATCH |
| g_trend_slope_with | Slope > threshold (weaker than _strong_with) | Per spec §3.2 | MATCH |
| g_dir_up / g_dir_down | direction == "UP" / "DOWN" | Per spec §3.12 | MATCH |
| g_tr_above_pp | TR above pivot point | Per spec §3.5 | MATCH |

### V9 new gates

| Gate | Live impl | Spec §2 | Match? |
|---|---|---|---|
| g_b1_poly_flow_aligned | Net flow on OUR direction side in window_s > thresh_shares. Defensive: returns False on missing data. | B1: aligned flow > thresh_shares in window | MATCH |
| g_b2_poly_flow_contrarian | Net OPPOSING flow > thresh_shares (contrarian = positive for BTC). | B2: opposing flow > thresh | MATCH |
| g_b2_poly_flow_NOT_opposing | NOT variant: opposing flow < thresh_shares (used for V9_10 SOL). | B2-NOT for SOL anti-signal | MATCH |
| g_b3_poly_flow_abs | |net_up| + |net_dn| > thresh_shares (direction-agnostic). | B3: absolute flow > thresh | MATCH |
| g_a2_hl_short_cascade | sum(notional) for asset_coin in window_s > thresh_usd; pre-filtered for Close Short + Open Long market fills. Defensive on missing data. | A2: HL short liquidation cascade; sum > thresh_usd | MATCH |

---

## 3. Bug status

### Bug 1 — g_vol_high / g_vol_contracting rv_60 scale bug
**STATUS: FIXED** in live code (TV_FIX_VOL_HIGH_RV60_SCALE_BUG_2026_05_27)

Prior behavior (still referenced in CLAUDE.md): panel stores `rv_60` annualized (`rv * sqrt(AF)` where AF=105120 for 5m, 35040 for 15m). The gate compared the annualized rv_60 directly against the RAW-scale threshold (e.g., 0.0203 for ETH 15m). At any real annualized rv_60 value (~2–5), this is always > 0.02 → `g_vol_high` was always-True (no-op filter) and `g_vol_contracting` always-False (permanent block).

**Live code now (confirmed):**
```python
raw_rv = row.rv_60 / (af ** 0.5)   # de-annualize: 3.80 / 187.2 → 0.0203
return raw_rv > thr                  # 0.0203 > 0.0203 → correct threshold behavior
```
Both `g_vol_high` and `g_vol_contracting` now de-annualize before comparison. The fix is present for all 6 (asset, tf) pairs.

**Affected sleeves (now corrected):**
- V5 sleeve 13: `eth_15m_trstack_vwap_vol_offearly` (g_vol_high was always-pass → gate was transparent)
- V5 sleeve 15: `sol_15m_trstack_vol_ribbon_ema_mid` (same)
- Multiple V6/V7/V8 sleeves using g_vol_high(ETH,15m) or g_vol_contracting(BTC,15m)

### Bug 2 — Synthetic-fill placeholder (0.5 vwap)
**STATUS: FIXED** in live code (TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27)

Prior behavior: `_simulate_l25_walk` returned `(0.5, n/0.5)` placeholder when book was empty.

**Live code now:** All controller fill/snapshot reads (`_simulate_l25_walk`, `_compute_l25_vwap_and_depth`, `_top_of_book`) route through `book_snapshot_fn = paper.get_orderbook_snapshot` — the canonical 3-tier WS→CLOB→Storedata dispatcher. Confirmed in controller constructor comment: _"This eliminates the synthetic 0.5-vwap placeholder path."_ Production engine wiring passes `book_snapshot_fn=paper.get_orderbook_snapshot`.

### Bug 3 — Spread metric: cross-token vs same-token
**STATUS: FIXED** in live code (2026-05-27)

Prior behavior (caused 0/1184 placements on V5 live): `_compute_spread` returned `abs(up_vwap - (1 - dn_vwap))` (cross-token arb proxy). On thin books this always exceeded any sleeve's spread_filter.

**Live code now:** `_compute_spread` delegates to `_sniper_spread.compute_spread` which returns same-token `ask0 - bid0` on the side being bought (matching `engine_v2.fill_at_book` line 234). Quote from docstring: _"The same-token bid-ask form below matches the backtest assumption and produces the expected 30-50% placement rate."_

### Bug 4 — Fee model: legacy 2%-on-profit vs winner-only poly_taker_curve
**STATUS: MISMATCH — NEW BUG FOUND** (see §4 below)

---

## 4. Fee model finding

**Spec says:** `fee_model = legacy_2pct_profit` → `pnl_won = (1.0 - vwap) * shares * 0.98`

(Both V5 spec §6 and V9 spec §1 explicitly specify `legacy_2pct_profit`.)

**Live controller HOLD-to-resolve path (lines 455–462):**
```python
# Winner-only Polymarket fee (operator-confirmed 2026-05-28):
#   fee/share = 0.07 * vwap * (1 - vwap)  → charged ONLY on a WIN.
#   net win = profit - fee = (1-vwap)*shares*(1 - 0.07*vwap)
if won:
    pnl = (1.0 - vwap) * shares * (1.0 - 0.07 * vwap)
else:
    pnl = -vwap * shares
```

**Live controller HEDGE_LATE path (lines 519–521):**
```python
# Legacy fee model (spec §3): loss leg untaxed; 2% only on profit.
pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
pnl = pnl if pnl <= 0 else pnl * 0.98
```

**Divergence:** The HOLD-to-resolve path uses the `poly_taker_curve` formula (`(1 - 0.07 * vwap)`), NOT legacy 2%. The HEDGE_LATE path uses legacy 0.98. These are inconsistent with each other AND with the spec.

**Numeric impact at vwap=0.65:**
- Spec / HEDGE_LATE legacy: `pnl_won = 0.35 * 0.98 = 0.3430` per share
- Live HOLD path (poly_taker): `pnl_won = 0.35 * (1 - 0.07*0.65) = 0.3341` per share
- Delta: ~2.7% lower PnL per winning trade on the HOLD path vs spec expectation

The comment in the controller says this was an "operator-confirmed 2026-05-28" change after verifying with Polymarket. However, CLAUDE.md (canonical project memory) confirms that production currently uses 2%-on-profit-only for BTC/ETH/SOL markets (`feeRate` effectively 0), so the new curve in the HOLD path charges MORE than Polymarket actually charges in production. This means the live shadow PnL log will show LOWER profits than actual production would.

**Recommendation:** Reconcile fee model. If Polymarket crypto updown markets still charge 0.07*vwap, use poly_taker everywhere. If legacy 2% is still production behavior, revert to 0.98 in the HOLD path and fix HEDGE_LATE to match. Do NOT have two different fee models in the same controller.

---

## 5. Spread metric finding

**Live:** `_compute_spread` → `_sniper_spread.compute_spread(snap, direction)` → same-token `ask0 - bid0` on the direction side being bought.

This matches `engine_v2.fill_at_book` line 234 (confirmed). The prior cross-token metric (`abs(up_vwap - (1 - dn_vwap))`) is logged as `cross_spread_old` for audit comparison. Bug 3 is fully resolved.

---

## 6. Additional findings

### NEW BUG 5 — Fee model inconsistency in HEDGE_LATE vs HOLD paths

Documented above in §4. The HOLD resolution path uses `poly_taker_curve(0.07*vwap)` while HEDGE_LATE uses `legacy_2pct(0.98)`. Both should use the same model. This is a correctness defect in the shadow PnL accounting for all HOLD-exit sleeves.

### Note on V9 gate data dependency

V9 gates (B1/B2/B3/A2) are defensively boot-safe: when `v9_data_store` is None (Polymarket trades / HL liquidation parquets not loaded on VPS3), all V9 gates return False and those 10 sleeves stay silent. The operator note in the controller: _"Operator must populate /opt/tradingvenue/data/v4/canonical/ before V9 sleeves start firing."_ This is expected behavior, not a bug, but V9 sleeves will produce zero fires until data is present.

### Total sleeve count

Live `sniper_v5_sleeves.py` contains **78 `SniperV5Sleeve` entries**: 16 V5 + 14 V6 + 7 V7 + 14 V8 + 10 V9 + 11 VL + 1 HEDGE_LATE A/B variant = 73 (plus any remaining out of count). The 16 V5 and 10 V9 sleeves under audit are confirmed present with correct IDs.

---

## Summary

| Metric | Result |
|---|---|
| V5 sleeves fully faithful to spec | **16 / 16** |
| V9 sleeves fully faithful to spec | **10 / 10** |
| Known Bug 1 (g_vol_high scale) | **FIXED** |
| Known Bug 2 (synthetic fill placeholder) | **FIXED** |
| Known Bug 3 (spread cross-token) | **FIXED** |
| Known Bug 4 (fee model) | **MISMATCH** — live HOLD path uses poly_taker_curve(0.07*vwap), spec says legacy_2pct; HEDGE_LATE uses legacy. Inconsistency introduced 2026-05-28 per operator comment. Shadow PnL for HOLD sleeves is understated vs legacy spec. |
| New Bug 5 | HOLD path vs HEDGE_LATE path use DIFFERENT fee models within same controller. |
