# Fidelity Audit — Live sniper_v5 sleeves vs spec/backtest (2026-06-01)

**Auditor:** Claude Sonnet 4.6  
**Snapshot:** `vps3_engine_snapshot_2026_06_01/`  
**Live files read:**
- `strategies/polymarket/sniper_v5_sleeves.py` (1667 lines)
- `strategies/polymarket/sniper_v5_gates.py` (79905 B)
- `strategies/polymarket/sniper_v5_thresholds.py`
- `strategies/kalshi/sniper_kalshi_sleeves.py`
- `firing_sleeves_7d.csv`

**Spec/backtest docs read:**
- `TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md`
- `TV_AGENT_SPEC_EMA_DOWN_V10_2026_06_01.md`
- `EMA_DOWN_DEEPDIVE_2026_06_01.md`
- `SLEEVE_OPTIMIZATION_2026_05_30.md`
- `FULLPERIOD_PERSISTENCE_2026_05_30.md`
- `FIDELITY_AUDIT_V6_V7_2026_05_29.md`
- `FIDELITY_AUDIT_V8_H_2026_05_29.md`
- `FIDELITY_AUDIT_VL_2026_05_29.md`

---

## 1. Per-sleeve fidelity table — TARGET SLEEVES

| # | sleeve_id | Live file:line | Live gate stack | Spec/backtest gate stack | MATCH/DRIFT/BUG | Note |
|---|-----------|---------------|-----------------|--------------------------|-----------------|------|
| ETH_01 | `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` | sleeves.py:874 | `g_tr_above_ema50(ETH) + g_hurst_trending(ETH,5m) + g_grandparent_trend_with(ETH)` | same | **MATCH** | offset=60, spread=0.02, BOTH. Live 7d: n=157, WR=0.745, +$156 ✅ |
| ETH_02 | `poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6` | sleeves.py:513 | `g_bb_pos_with(ETH) + g_mp_skew_with + g_hurst_trending(ETH,5m) + g_entry_vwap_in_band` | same | **MATCH** | offset=60, spread=0.02, BOTH. band=[0.20,0.80] per thresholds.py:105-106. Live: n=228, WR=0.706, +$80 ✅ |
| ETH_03 | `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6` | sleeves.py:487 | `g_tr_above_cloud(ETH) + g_ribbon_agrees(ETH) + g_mp_skew_with + g_hurst_trending(ETH,5m)` | same | **MATCH** | offset=60, spread=0.02, BOTH. Live: n=173, WR=0.734, +$43 ✅ |
| ETH_04 | `poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7` | sleeves.py:712 | `g_tr_above_cloud(ETH) + g_entry_vwap_in_band + g_hurst_mp_trend_with(ETH)` | same | **MATCH** | offset=60, spread=0.02, BOTH. band=[0.20,0.80]. Live: n=191, WR=0.696, +$50 ✅ |
| ETH_05 | `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6_vL` | sleeves.py:1074 | same gates as ETH_03, spread=0.025 (`_SPREAD_VL_ETH`) | same | **MATCH** | Prior VL audit 2026-05-29: PASS. Live: n=202, WR=0.733, +$44 ✅ |
| ETH_06 | `poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL` | sleeves.py:1101 | same gates as ETH_02, spread=0.025 | same | **MATCH** | Prior VL audit PASS. Live: n=261, WR=0.697, +$77 ✅ |
| ETH_07 | `poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL` | sleeves.py:1114 | same gates as ETH_04, spread=0.025 | same | **MATCH** | Prior VL audit PASS. Live: n=220, WR=0.686, +$41 ✅ |
| BTC_01 | `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` | sleeves.py:404 | `g_dir_down + g_tr_above_ema50(BTC) + g_tr_above_ema800(BTC)` | same | **MATCH** | offset=600, spread=0.02, DOWN. Live: n=120, WR=0.815, +$172 ✅ |
| BTC_02 | `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H` | sleeves.py:1404 | same gates + `exit_policy="HEDGE_LATE"` | same | **MATCH** | hedge_late_loss_ratio=0.70, hedge_late_check_lead_s=60 (dataclass defaults). Live: n=101, WR=0.920, +$152 ✅ |
| BTC_03 | `kalshi_sniper_btc_15m_ema50_ema800_off600_down` | kalshi/sniper_kalshi_sleeves.py:58 | `g_dir_down + g_tr_above_ema50(BTC) + g_tr_above_ema800(BTC)` | 1:1 port of BTC_01 | **MATCH** | offset=600, spread=0.02, DOWN. Mirrors Poly exactly. Live: n=91, WR=0.846, +$145 ✅ |
| BTC_04 | `kalshi_sniper_btc_15m_ema50_ema800_off600_down_H` | kalshi/sniper_kalshi_sleeves.py:97 | same as BTC_03 + `exit_policy="HEDGE_LATE"` | same | **MATCH** | Live: n=65, WR=0.846, +$113 ✅ |
| BTC_05 | `poly_sniper_v5_btc_15m_vwapprem_ema50_mpskew_off600_v6` | sleeves.py:594 | `g_vwap_premium + g_tr_above_ema50(BTC) + g_mp_skew_with` | same | **MATCH** | BOTH direction (not DOWN). `g_vwap_premium` = entry_vwap >= 0.55 (thresholds.py:113). Live: n=129, WR=0.899, +$47 ✅ |
| BTC_06 | `poly_sniper_v5_btc_15m_mpskew_trstack_off600_down` | sleeves.py:392 | `g_dir_down + g_mp_skew_strong_with + g_tr_stack_full_with(BTC)` | same | **MATCH** | offset=600, spread=0.02, DOWN. `mp_skew_strong` threshold=50bps. Live: n=42, WR=0.952, +$30 ✅ |
| BTC_07 | `poly_sniper_v5_btc_15m_ts_trstack_off600_down` | sleeves.py:360 | `g_dir_down + g_tr_stack_full_with(BTC) + g_trend_slope_with(BTC,15m)` | same | **MATCH** | offset=600, spread=0.02, DOWN. Live: n=33, WR=0.909, +$51 ✅ |
| BTC_08 | `poly_sniper_v5_btc_15m_ema200_mpskew_rf_off600_down_v6` | sleeves.py:606 | `g_dir_down + g_tr_above_ema200(BTC) + g_mp_skew_strong_with + g_rf_with(BTC)` | same | **MATCH** | offset=600, spread=0.02, DOWN. Live: n=56, WR=0.875, +$17 ✅ |
| BTC_09 | `poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8` **[KILL]** | sleeves.py:862 | `g_parent_15m_slope_with(BTC) + g_trend_slope_strong_with(BTC,5m) + g_imb5_strong_with` | same | **MATCH — but KILL** | Gate stack faithful to spec. Spec target was wrong (V8 imb5 look-ahead). Live: n=2371, WR=0.687, +$26 (look-ahead artifact in shadow). Opt report: KILL. |
| BTC_10 | `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8` | sleeves.py:838 | `g_grandparent_trend_with(BTC) + g_imb5_strong_with + g_rf_with(BTC)` | **spec: `g_1h_rf_with(BTC)`** + imb5 + rf | **BUG** ← known | Gate 1 mismatch: live uses `grandparent_trend_with` (1h slope direction) instead of `g_1h_rf_with` (1h Range Filter rf_dir). Documented in FIDELITY_AUDIT_V8_H_2026_05_29.md §3. Live: n=1638, WR=0.722, −$632 (net loss; imb5 look-ahead + wrong gate 1). Opt: SALVAGE with `cross_spread≤0.22`. |
| BTC_11 | `poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8` | sleeves.py:850 | `g_grandparent_trend_with(BTC) + g_imb5_strong_with + g_ribbon_agrees(BTC)` | **spec: `g_1h_rf_with(BTC)`** + imb5 + ribbon | **BUG** ← known | Same gate-1 mismatch as BTC_10. Live: n=1299, WR=0.751, −$364. Same action: SALVAGE gated. |
| BTC_12 | `poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7` | sleeves.py:700 | `g_parent_15m_not_ranging(BTC) + g_trend_slope_strong_with(BTC,5m) + g_mp_skew_with` | same | **MATCH — over-fire note** | Gate stack faithful. BOTH + offsets=(30..270, 9 offsets). Live: n=983, WR=0.732, −$110. Prior handoff flagged as "28× over-fire bug" — the `g_parent_15m_not_ranging` gate rarely blocks (regime is non-ranging most of the time), so 9 offsets × BOTH yield ~983 fires/7d. NOT a missing-gate bug — the gate exists and is wired. It's a volume/selectivity issue, not a coding error. Opt: `evcap≤0.80 + vsum≤1.30` gating needed. |
| BTC_13 | `poly_sniper_v5_btc_5m_ts_mpskew_any_off30` **[KILL]** | sleeves.py:237 | `g_trend_slope_strong_with(BTC,5m) + g_mp_skew_with` | same | **MATCH — but KILL** | offset=(30,) only, BOTH. Gate stack faithful. Live: n=274, WR=0.577, −$107. Opt: KILL — no gate stack recovers positive EV. |
| V10_01 | `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_V10` | sleeves.py:1614 | `g_tr_above_ema50(ETH) + g_hurst_trending(ETH,5m) + g_grandparent_trend_with(ETH) + g_sms_no_liquidity_above(ETH,5m)` | v8 parent + `g_sms_no_liquidity_above` | **MATCH** | Spec (TV_AGENT_SPEC_V10_SLEEVES_2026_05_31.md) prescribes exactly this. Just started firing — not in 7d top list (deployed ~Jun 1). |
| V10_02 | `poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_V10` | sleeves.py:1628 | `g_tr_above_cloud(ETH) + g_ribbon_agrees(ETH) + g_mp_skew_with + g_hurst_trending(ETH,5m) + g_tr_above_pp(ETH)` | v6 parent + `g_tr_above_pp` | **MATCH** | Spec prescribes exactly this. |
| V10_03 | `poly_sniper_v5_eth_5m_bb_mp_hurst_band_V10` | sleeves.py:1644 | `g_bb_pos_with(ETH) + g_mp_skew_with + g_hurst_trending(ETH,5m) + g_entry_vwap_in_band_narrow` | v6 parent with `g_entry_vwap_in_band` replaced by `g_entry_vwap_in_band_narrow` | **MATCH** | `g_entry_vwap_in_band_narrow` = [0.15, 0.55] (thresholds.py:115-116). Spec says [0.15, 0.55] via `lab universe 01_build_universe_v6.py:260`. Live 7d: n=3, just started. |
| V10_BTC | `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_V10` | — | **NOT IN SNAPSHOT** | spec `TV_AGENT_SPEC_EMA_DOWN_V10_2026_06_01.md` requires this sleeve + `_H_V10` + 2 kalshi twins | **MISSING** | 4 sleeves specified but 0 created. EMA_DOWN_V10 band=[0.15, 0.93/0.95] not yet live. Also: `g_entry_vwap_band(lo, hi)` parameterized form does not exist in gates.py (only fixed `g_entry_vwap_in_band_narrow`=[0.15,0.55]); a new gate function is needed for the [0.15, 0.93] bound. |

---

## 2. Threshold drift check

| Threshold | Live value (thresholds.py) | Spec/backtest value | Match? |
|-----------|--------------------------|---------------------|--------|
| `HURST_TRENDING_THR` | 0.50 | V6 spec §3.8: 0.50 | ✅ |
| `HURST_REGIME_THR` | 0.55 | V7 spec §3.2: 0.55 | ✅ |
| `HURST_REVERTING_THR` | 0.40 | V7 spec §3.2: 0.40 | ✅ |
| `VWAP_BAND_LOW/HIGH` | 0.20 / 0.80 | V6 §3.13: [0.20, 0.80] | ✅ |
| `VWAP_NARROW_LOW/HIGH` | 0.15 / 0.55 | V10 lab universe: [0.15, 0.55] | ✅ |
| `VWAP_PREMIUM_THR` | 0.55 | V6 §3.13: 0.55 | ✅ |
| `BB_POS_UP_THR / DN_THR` | 0.55 / 0.45 | V6 §3.6 | ✅ |
| `MP_SKEW_STRONG_BPS_THR` | 50.0 bps | spec: 50 bps | ✅ |
| `GRANDPARENT_SLOPE_STRONG_THR` | 0.85 | V8 §3.1: 0.85 | ✅ |
| `IMB5_STRONG_THR` | 0.20 | spec: 0.20 | ✅ |
| `OFFSET_EARLY_MAX_S` | 60 | spec: 60 | ✅ |
| `RF_AGED_MIN_S` | 60 | spec: 60 | ✅ |
| EMA periods (50/200/800) | Wired via gate names; panel-computed | spec names match | ✅ (name-level) |
| off600 offsets | `offsets=(600,)` in all BTC 15m DOWN sleeves | spec: fire at t+600s | ✅ |
| ema_down V10 band [0.15, 0.93] | **NOT IMPLEMENTED** | EMA_DOWN_V10 spec: [0.15, 0.93/0.95] | ❌ MISSING |

---

## 3. BUG/DRIFT inventory

### BUG-1 (persistent): `btc_5m_l_1hrf_imb5_rf_v8` and `btc_5m_l_1hrf_imb5_ribbon_v8` — gate 1 mismatch
- **Live:** `g_grandparent_trend_with(BTC)` — 1h `trend_slope` direction match
- **Spec:** `g_1h_rf_with(BTC)` — 1h Range Filter `rf_dir` direction match
- `g_1h_rf_with` EXISTS in gates.py (line ~1732) and is distinct from `g_grandparent_trend_with`
- First flagged in `FIDELITY_AUDIT_V8_H_2026_05_29.md §3`. **NOT FIXED** as of this snapshot.
- **Impact:** These two sleeves are operating with an un-validated gate substitute. The backtest for V8_01/V8_02 used `g_1h_rf_with`; live uses trend-slope. Also confounded by the `g_imb5_strong_with` look-ahead bug (see BUG-2).
- **Action:** Fix to `g_1h_rf_with` OR re-run backtest with `g_grandparent_trend_with` before treating live as spec-comparable.

### BUG-2 (root cause for KILL verdict): `g_imb5_strong_with` look-ahead in V8 GA search
- `g_imb5_strong_with` itself is correctly implemented (current book-mirror depth imbalance, causal at fire_us).
- The bug was in the **GA search process** that produced the `btc_5m_*_imb5_*_v8` universe: book snapshot was not strictly asof at fire_us during construction. Gate evaluated with post-fire book state → inflated backtest WR. Documented in `SLEEVE_OPTIMIZATION_2026_05_30.md §3`.
- Affects V8_01, V8_02, V8_03. Live replay confirms the loss (V8_03 live −$930, V8_01 −$632, V8_02 −$364).
- **Action:** KILL V8_01–V8_03. Salvage gated V8_02 only if `cross_spread≤0.22` OOS confirms.

### MISSING-1: `btc_15m_ema50_ema800_off600_down_V10` family — not deployed
- Spec (`TV_AGENT_SPEC_EMA_DOWN_V10_2026_06_01.md`) calls for 4 new sleeves:
  1. `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_V10`
  2. `poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H_V10`
  3. `kalshi_sniper_btc_15m_ema50_ema800_off600_down_V10`
  4. `kalshi_sniper_btc_15m_ema50_ema800_off600_down_H_V10`
- **None present** in the live snapshot (grepped both `sniper_v5_sleeves.py` and `sniper_kalshi_sleeves.py`).
- Also the required gate `g_entry_vwap_band(0.15, 0.93)` does not exist in gates.py. The closest is `g_entry_vwap_in_band_narrow` = [0.15, 0.55] which is wrong for this sleeve (the EMA_DOWN V10 band is [0.15, 0.93/0.95]).
- **Operator decision** (from spec §0): Kalshi = V10 live, Poly = parent keeps + shadow V10. But the snapshot predates this deploy or it was not yet committed.

### MISSING-2: `g_entry_vwap_band` parameterized gate absent
- The EMA_DOWN_V10 spec calls for `g_entry_vwap_band(0.15, 0.95)` as a parameterized gate. No such function exists in gates.py. All existing band gates are fixed-value constants (e.g., `_NARROW`=[0.15,0.55], `_BAND`=[0.20,0.80]).
- A new gate function or a parametric form is required before the 4 V10 EMA_DOWN sleeves can be implemented.

### NOTE-1 (not a bug): `btc_5m_parent15m_notrang_ts_mpskew_v7` over-fire pattern
- Prior handoff described as "28×-over-fire bug." This is NOT a missing gate — `g_parent_15m_not_ranging(BTC)` is correctly wired (sleeves.py:705). The high fire rate (983 fires in 7d) is because `parent_15m_not_ranging` passes whenever the 15m regime label ≠ "ranging," which is most of the time. Combined with 9 offsets × BOTH direction = 18 evaluations per slug, the sleeve fires on nearly every slug.
- This is a **selectivity issue**, not a code bug. The gate stack matches the spec. The spec/backtest simply over-estimated how rarely this regime occurs. Opt report verdict: `evcap≤0.80 + vsum≤1.30` gate needed; KILL or replace with a tighter regime gate.

---

## 4. ETH-5m-hurst family faithfulness summary

All 7 ETH-5m hurst-family sleeves in scope are faithfully reproduced:

| sleeve | key hurst gate | threshold | direction | offset | spread | verdict |
|--------|---------------|-----------|-----------|--------|--------|---------|
| `l_ema50_hurst_grandparent_v8` | `g_hurst_trending(ETH,5m)` | hurst_60>0.50 | BOTH | 60 | 0.02 | ✅ MATCH |
| `bb_mp_hurst_band_v6` | `g_hurst_trending(ETH,5m)` | hurst_60>0.50 | BOTH | 60 | 0.02 | ✅ MATCH |
| `cloud_ribbon_mp_hurst_v6` | `g_hurst_trending(ETH,5m)` | hurst_60>0.50 | BOTH | 60 | 0.02 | ✅ MATCH |
| `cloud_vwap_hurstmp_v7` | `g_hurst_mp_trend_with(ETH)` | hurst_60>0.50 + mp skew sign | BOTH | 60 | 0.02 | ✅ MATCH |
| `..._v6_vL` (3 sleeves) | same as parent | same | same | same | 0.025 | ✅ MATCH |
| `l_ema50_hurst_grandparent_V10` | parent + `g_sms_no_liquidity_above` | — | BOTH | 60 | 0.02 | ✅ MATCH |
| `cloud_ribbon_mp_hurst_V10` | parent + `g_tr_above_pp` | — | BOTH | 60 | 0.02 | ✅ MATCH |
| `bb_mp_hurst_band_V10` | `g_entry_vwap_in_band_narrow` replaces wide band | [0.15,0.55] | BOTH | 60 | 0.02 | ✅ MATCH |

Key gate semantics verified: `g_hurst_trending` = hurst_60 > 0.50 (direction-independent; thresholds.py:96); `g_hurst_regime_with` = hurst_60 > 0.55 AND trend_slope sign matches (thresholds.py:98). Both referenced correctly — the V8 grandparent sleeve uses `g_hurst_trending` (CORRECT per its backtest), not `g_hurst_regime_with`.

---

## 5. BTC-15m DOWN family faithfulness summary

| sleeve | gates | direction | offset | spread | verdict |
|--------|-------|-----------|--------|--------|---------|
| `ema50_ema800_off600_down` | dir_down + ema50 + ema800 | DOWN | 600 | 0.02 | ✅ MATCH |
| `..._down_H` | same + HEDGE_LATE | DOWN | 600 | 0.02 | ✅ MATCH |
| `kalshi_..._down` | 1:1 port — dir_down + ema50 + ema800 | DOWN | 600 | 0.02 | ✅ MATCH |
| `kalshi_..._down_H` | same + HEDGE_LATE | DOWN | 600 | 0.02 | ✅ MATCH |
| `btc_15m_ema50_ema800_off600_down_V10` | **NOT IN SNAPSHOT** | DOWN | 600 | — | ❌ MISSING |
| `vwapprem_ema50_mpskew_off600_v6` | vwap_premium + ema50 + mp_skew; BOTH not DOWN | BOTH | 600 | 0.02 | ✅ MATCH |
| `mpskew_trstack_off600_down` | dir_down + mp_skew_strong + tr_stack_full | DOWN | 600 | 0.02 | ✅ MATCH |
| `ts_trstack_off600_down` | dir_down + tr_stack_full + trend_slope | DOWN | 600 | 0.02 | ✅ MATCH |
| `ema200_mpskew_rf_off600_down_v6` | dir_down + ema200 + mp_skew_strong + rf | DOWN | 600 | 0.02 | ✅ MATCH |

Note: `btc_15m_vwapprem_ema50_mpskew_off600_v6` is BOTH direction (not DOWN-only), which matches the V6 spec. Do not confuse with the DOWN family.

---

## 6. BTC-5m family faithfulness summary

| sleeve | gates | verdict |
|--------|-------|---------|
| `q_parent15mslope_ts_imb5_v8` | parent_15m_slope + ts_strong + imb5 | ✅ MATCH (faithful to spec, but KILL for look-ahead) |
| `l_1hrf_imb5_rf_v8` | **grandparent_trend** (live) vs **1h_rf** (spec) + imb5 + rf | ❌ BUG-1 |
| `l_1hrf_imb5_ribbon_v8` | **grandparent_trend** (live) vs **1h_rf** (spec) + imb5 + ribbon | ❌ BUG-1 |
| `parent15m_notrang_ts_mpskew_v7` | parent_15m_not_ranging + ts_strong + mp_skew | ✅ MATCH (but over-fire / negative EV — NOTE-1) |
| `ts_mpskew_any_off30` | ts_strong + mp_skew, offset=30 | ✅ MATCH (but KILL) |

---

## 7. Verdict counts

| Category | Count |
|----------|-------|
| MATCH (gate stack faithful to spec) | 21 |
| BUG (gate mismatch vs spec) | 2 (BUG-1: V8_01, V8_02 — `g_1h_rf_with` → `g_grandparent_trend_with`) |
| MISSING (spec calls for sleeve not yet in live) | 4 (EMA_DOWN V10 family) |
| MATCH but KILL (gate stack correct; underlying backtest invalid) | 2 (q_parent15mslope imb5, ts_mpskew_any_off30) |
| MATCH but over-fire (correct gates; high volume from low-selectivity gate) | 1 (btc_5m_parent15m_notrang_ts_mpskew_v7) |

**Total target sleeves audited: 26 (22 poly + 4 kalshi)**

---

## 8. Immediate action items

1. **BUG-1** (persistent since 2026-05-29): Fix `btc_5m_l_1hrf_imb5_rf_v8` and `btc_5m_l_1hrf_imb5_ribbon_v8` gate 1 from `g_grandparent_trend_with` → `g_1h_rf_with`. Or confirm backtest used `g_grandparent_trend_with` and treat the spec as stale. Current live losses: −$632 and −$364 respectively.
2. **MISSING-1**: Implement 4 `btc_15m_ema50_ema800_off600_down_V10` sleeves per `TV_AGENT_SPEC_EMA_DOWN_V10_2026_06_01.md`. Requires MISSING-2 first.
3. **MISSING-2**: Add `g_entry_vwap_band(lo, hi)` parameterized gate to gates.py (or a named `g_entry_vwap_in_band_ema_down` = [0.15, 0.93]) before V10 EMA_DOWN sleeves can be wired.
4. **KILL**: Disable `poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8` and `poly_sniper_v5_btc_5m_ts_mpskew_any_off30` — shadow losses are real (look-ahead artifact; no gate stack recovers positive EV).
5. **MONITOR**: `btc_5m_parent15m_notrang_ts_mpskew_v7` — gate is correctly wired but over-fires; apply `evcap≤0.80 + vsum≤1.30` or replace with stricter regime gate.
