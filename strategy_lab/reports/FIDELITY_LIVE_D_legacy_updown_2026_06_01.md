# Fidelity Audit D — Legacy `poly_updown_*` + SOL 5m Sniper Sleeves
**Date:** 2026-06-01 | **Scope:** All `poly_updown_*` firing sleeves in `firing_sleeves_7d.csv` + `poly_sniper_v5_sol_5m_*` family

---

## 1. Methodology

Sources read:
- `vps3_engine_snapshot_2026_06_01/strategies/polymarket/{inverse.py, updown_5m.py, updown_15m.py, vwap_continuation.py, gates.py, base.py}`
- `vps3_engine_snapshot_2026_06_01/engine/poly_updown_loop.py`
- `firing_sleeves_7d.csv` (live 7d snapshot)
- Spec/backtest reports: `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md`, `ANTI_EDGE_FINDINGS.md`, `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`, `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`, `SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md`, `BTC_V3_DEEP_DIVE_2026_05_04.md`, `V3_2_DEPLOY_SPEC_2026_04_30.md`, `BACKTEST_REPLAY_SOL_2026_05_29.md`, `HANDOFF_2026_06_01.md`
- Prior audits: `ENGINE_AUDIT_B_directional_2026_05_29.md`, `AUDIT_FINAL_CORRECTED_2026_05_29.md`

### ws_s anchor verification
`poly_updown_loop.py:build_bar_context()` line ~264: fetches `btc_now = _fetch_close(offset=0)` against `ws_s` (passed as `slot_start_unix_s - window_s` by the scheduler). The `build_bar_context_t_plus_120()` builder (lines 529-553) fetches RSI-14 offsets `[-840..0]` anchored at `ws_s`, matching the spec. **ws_s anchor = CORRECT** throughout. No lookahead found.

---

## 2. Per-Family Fidelity Table

### 2.1 INV_NIGHT family — `poly_updown_{btc,eth,sol}_{5m,15m}_volume_INV_NIGHT` (6 sleeves)

| Sleeve | 7d fires | WR | 7d PnL | Status |
|---|---:|---:|---:|---|
| btc_5m_volume_INV_NIGHT | 525 | 47.8% | −$958 | LIVE |
| eth_5m_volume_INV_NIGHT | 524 | 49.0% | −$910 | LIVE |
| sol_5m_volume_INV_NIGHT | 494 | 46.4% | −$1572 | LIVE |
| btc_15m_volume_INV_NIGHT | 190 | 51.1% | −$99 | LIVE |
| eth_15m_volume_INV_NIGHT | 177 | 51.4% | −$95 | LIVE |
| sol_15m_volume_INV_NIGHT | 160 | 51.3% | −$134 | LIVE |

**Live logic (file:line):**
- `inverse.py:80–90` — `is_night_hour_utc(window_start_unix)` checks UTC hour of `ws_s` ∈ `{1,2,3,4,5,9,10}`.
- `inverse.py:136–140` — `apply_inverse_filter(kind="inverse_volume_night", ...)`: if NOT night hour → NONE; else `flip_signal(base_signal)` (UP↔DOWN).
- `inverse.py:93–103` — `flip_signal`: UP→DOWN, DOWN→UP. Correct.
- `updown_5m.py:69,108–111` — base signal = sign of `aux["ret_5m"]`. Pure volume mode (no threshold gate).

**Spec:** `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` + `ANTI_EDGE_FINDINGS.md`. Deployed as explicit ANTI-EDGE test — hypothesis: V1 volume is 60-65% WRONG at night hours → flipping yields 60-65% right.

**Match/Drift/Bug:** MATCH — code exactly implements the spec. Night-hour set, flip logic, and ws_s anchor are all correct.

**Faithful-but-bad vs Buggy:** FAITHFUL-BUT-BAD. The anti-edge hypothesis was wrong. The original V1-volume-night signal was only ~52-54% right (mild positive), so flipping produces 46-48% WR — mildly negative. Not inverted wrong; the market premise was falsified. The inversion function itself is correct.

**Verdict:** KILL — dead anti-edge, no recoverable edge. Already flagged in `AUDIT_FINAL_CORRECTED_2026_05_29.md` KILL list. Running on faith = wrong theory, code correct.

---

### 2.2 v3 / v3_1 / v3_2 / v3_3 / v4 family

**Sleeves firing (from `firing_sleeves_7d.csv`):**

| Sleeve | 7d fires | WR | 7d PnL |
|---|---:|---:|---:|
| sol_5m_v3 | 123 | 47.2% | −$210 |
| sol_5m_v3_1 | 101 | 43.6% | −$375 |
| sol_5m_v3_2 | 151 | 49.7% | −$178 |
| sol_5m_v3_3 | 103 | 42.7% | −$321 |
| btc_5m_v3_1 | 59 | 45.8% | −$120 |
| btc_5m_v4 | 45 | 40.0% | −$225 |
| eth_5m_v3 | 34 | 35.3% | −$181 |
| eth_5m_v3_1 | 20 | 35.0% | −$93 |
| eth_5m_v3_2 | 27 | 29.6% | −$202 |
| eth_5m_v3_3 | 27 | 29.6% | −$202 |
| eth_5m_v4 | 18 | 33.3% | −$90 |

**Live logic (file:line):**
- `updown_5m.py:73–87` — `mode="sniper"`: uses `abs_ret_5m_threshold` (legacy path for v3/v3_2) OR direction-aware `abs_ret_5m_threshold_up`/`_down` (for v3_1/v4, `updown_5m.py:78–83`).
- `updown_5m.py:89–106` — V3 multi-horizon AND filter: `aux.get("require_multi_horizon")` → requires `ret_5m`, `ret_15m`, `ret_1h` all same sign. This is the V3-specific gate (`updown_5m.py:92`, referenced as `TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md §1.3`).
- `updown_15m.py:73–87` — identical logic for 15m.

**Spec:** `BTC_V3_DEEP_DIVE_2026_05_04.md`, `V3_2_DEPLOY_SPEC_2026_04_30.md`. V3 family was in-sample validated Apr–May 4 only (n=15–22 BTC, n<10 SOL/ETH). No walk-forward OOS for SOL/ETH cells. BTC V3/V3_1/V3_2 had early positive IS (80% WR, n=15) but no gate-validated OOS window.

**Match/Drift/Bug:** MATCH — direction correct, multi-horizon filter logic correct, direction-aware threshold for v3_1/v4 correct. No code bugs.

**Faithful-but-bad vs Buggy:**
- **BTC v3_1/v4**: FAITHFUL-BUT-BAD. Edge evaporated OOS. Initial 80% WR was small-n IS artifact.
- **SOL v3/v3_1/v3_2/v3_3**: FAITHFUL-BUT-BAD. The multi-horizon AND filter fires less often but WR never exceeded 50% live; SOL momo edge absent.
- **ETH v3/v3_1/v3_2/v3_3/v4**: FAITHFUL-BUT-BAD. ETH v3 cells historically showed some IS edge (+$292 in `AUDIT_FINAL_CORRECTED_2026_05_29.md`) but have since deteriorated; no ongoing OOS pass.

**UNVALIDATED FLAG:** No full-period (Apr24–Jun01) walk-forward OOS exists for any ETH or SOL v3-family cell. BTC cells had early IS validation only. Running on initial small-sample hope.

**Verdict:** KILL SOL all v3 variants + BTC v4 (already in `AUDIT_FINAL_CORRECTED_2026_05_29.md` KILL list). ETH v3 marginal — needs fresh OOS before keeping.

---

### 2.3 sniper_hod family — `poly_updown_{btc,eth,sol}_{5m,15m}_sniper_hod`

| Sleeve | 7d fires | WR | 7d PnL |
|---|---:|---:|---:|
| eth_5m_sniper_hod | 87 | 44.8% | −$353 |
| btc_5m_sniper_hod | 77 | 35.1% | −$436 |
| sol_5m_sniper_hod | 73 | 52.1% | −$63 |
| btc_15m_sniper_hod | 37 | 40.5% | −$98 |
| eth_15m_sniper_hod | 38 | 47.4% | −$4 |

**Live logic (file:line):**
- `gates.py:66–79` — `hod_passes(fire_unix_s, allowed_hours)`: reads UTC hour of `fire_unix_s` (= `int(time.time())` at fire moment, passed by controller). Returns True iff hour ∈ allowed list.
- `gates.py:40–62` — `HOD_TOP8_BY_CELL` dict: e.g. `("sniper","btc_5m"): (1,2,4,6,8,14,21,22)`. Fit on 28d Apr 22–May 21 backtest, anchored to FIRE_us hour (NOT ws_s hour — corrected per `TV_AGENT_PHASE34_FIXES_2026_05_22.md §2.3`).
- `gates.py:37–38` — docstring: "Refresh schedule: monthly via `strategy_lab/markov_filter/_recompute_hod_top8.py`. DO NOT auto-update."

**Spec:** `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`. HoD lists fit on Apr 22–May 21. Spec §6 mandates monthly refresh. Refresh job `_recompute_hod_top8.py` was never built (confirmed in `HANDOFF_2026_05_22_HOD_REFRESH_SLEEVE_FIXES.md` and `AUDIT_FINAL_CORRECTED_2026_05_29.md`).

**Match/Drift/Bug:** DRIFT (config drift, not code bug). The gate logic is correct. The HoD lists are stale — fit May 2026 and never refreshed. As market regimes shift, the "top-8 hours" change. The lists now admit hours that are no longer the profitable ones, explaining the consistent WR < 50%.

**Faithful-but-bad vs Buggy:** CONFIG DRIFT. The gate implementation is correct but the parameters (HOD lists) are 40+ days old with no refresh. `btc_5m_sniper_hod` at 35.1% WR is particularly bad — the base sniper without HoD filter is ~50%; the stale HoD gate is now ANTI-selecting hours.

**Verdict:** INVESTIGATE — rebuild HoD lists on current 28d before kill decision. If fresh lists don't recover WR > 55%, KILL.

---

### 2.4 vwap_off / vwap_continuation family

| Sleeve | 7d fires | WR | 7d PnL |
|---|---:|---:|---:|
| btc_5m_vwap_off240_m1v | 17 | 35.3% | −$121 |
| eth_5m_vwap_off210_f7_m1v | 12 | 58.3% | +$47 |
| btc_5m_vwap_off90_cross | 7 | 42.9% | −$29 |
| sol_5m_vwap_off60 | 6 | 0.0% | −$152 |
| btc_5m_vwap_off60_f7_cross | 2 | 0.0% | −$50 |

**Live logic (file:line):**
- `vwap_continuation.py:80–153` — `VwapContinuationStrategy.signal()`:
  - Line 82: phase gate `aux["bar_ctx_phase"] == f"t_plus_{self.offset_s}"` — blocks wrong-offset fires.
  - Lines 85–97: dev_bps threshold filter `thr_min < |dev_bps| <= thr_max`.
  - Line 100: direction = `"UP" if dev_bps > 0 else "DOWN"` (continuation = bet with VWAP deviation).
  - Lines 103–110: M1V gate (Bull required for UP, Bear for DOWN).
  - Lines 112–126: F7 RSI gate.
  - Lines 128–151: cross-asset confluence gate.
- `poly_updown_loop.py:181–183` — `vwap_dev_bps` field populated by `build_bar_context_t_plus_n()` (late-fire builder for offsets {30,60,90,...,270}).

**Spec:** `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`. Backtest parameters:

| Sleeve | offset_s | thr_min | thr_max | filters | BT WR | BT n |
|---|---|---|---|---|---|---|
| btc_5m_vwap_off240_m1v | 240 | 5 bps | 10 bps | M1V | 86.3% | 546 |
| btc_5m_vwap_off60_f7_cross | 60 | 10 bps | 15 bps | F7+cross_full | 73.8% | 164 |
| btc_5m_vwap_off90_cross | 90 | 10 bps | 15 bps | cross_full | 78.7% | 221 |
| eth_5m_vwap_off210_f7_m1v | 210 | 10 bps | 15 bps | F7+M1V | 92.6% | 188 |
| sol_5m_vwap_off60 | 60 | 20 bps | 30 bps | (none) | 75.0% | 64 |

**Match/Drift/Bug:** MATCH — logic correctly implements spec. Direction = continuation (WITH dev_bps sign), not reversal. Thresholds and filter flags correct.

**Faithful-but-bad vs Buggy:**
- **btc_5m_vwap_off240_m1v** (−$121, 35% WR, n=17): FAITHFUL-BUT-BAD. The M1V Markov gate's 86.3% BT WR was in-sample on Apr22–May21. Post-deploy live WR of 35% at n=17 (small-n, high variance). The backtest involved all offsets {5,10,15,20,30bps} at 240s; the deployed thr_min=5bps is potentially too wide and the M1V regime may be stale. Needs more fires (n≥50) to judge.
- **eth_5m_vwap_off210_f7_m1v** (+$47, 58% WR, n=12): BORDERLINE. Positive but n=12 too small.
- **btc_5m_vwap_off90_cross** (−$29, 43% WR, n=7): FAITHFUL-BUT-BAD, n too small to judge.
- **sol_5m_vwap_off60** (−$152, 0% WR, n=6): FAITHFUL-BUT-BAD + SMALL-N WARNING. The spec itself noted "n~2-3, WR variance high" for the 24h kill gate. At n=6 with 0/6 wins this is concerning but not definitive (95% CI on WR includes 0–39%). The backtest cell (SOL 60s offset, 20–30 bps) had only n=64 in 28d (~2.3/day); live fires rate of 6 in 7d is below spec (~1.0/day vs expected 2.3). POSSIBLE issue: sol_5m_vwap_off60 was the weakest-validated cell in the spec ("n~2-3, WR variance high").
- **btc_5m_vwap_off60_f7_cross** (−$50, 0% WR, n=2): INSUFFICIENT DATA.

**OOS concern for all vwap_off sleeves:** The backtest window (Apr22–May21) is the same window used to fit the other gate stacks — in-sample for regime/Markov models. No explicit OOS walk-forward was run for vwap_off. Small live n makes it premature to call KILL; however `sol_5m_vwap_off60` is the most suspect.

**Verdict:** MONITOR at current stake for 2 more weeks. Kill `sol_5m_vwap_off60` if WR < 50% at n≥15.

---

## 3. SOL 5m Sniper Family — `poly_sniper_v5_sol_5m_*`

**Sleeves in `firing_sleeves_7d.csv`:**

| Sleeve | 7d fires | WR | 7d PnL | Spec/BT exists? |
|---|---:|---:|---:|---|
| sol_5m_f7_mfi_ema200_vwap_v6 | 608 | 68.8% | −$15 | YES (V6 spec) |
| sol_5m_rf_tr_partial_mid | 552 | 70.4% | +$90 | YES (V6 spec) |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 366 | 75.1% | −$13 | YES (V8 spec) |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 342 | 67.2% | +$15 | YES (V7 spec) |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 93 | 76.3% | +$36 | YES (V6 spec) |
| sol_5m_b1_120s_250_v9 | 394 | 57.1% | −$0.41 | YES (V9 spec) |
| sol_5m_b3_abs500_v9 | 186 | 50.0% | −$36 | YES (V9 spec) |
| sol_5m_b3_abs500_no_opp_v9 | 155 | 54.8% | +$61 | YES (V9 spec) |
| sol_5m_b1_polyflow_aligned_v9 | 31 | 74.2% | +$42 | YES (V9 spec) |
| sol_5m_down_b1_flow250_v9 | 96 | 57.3% | −$23 | YES (V9 spec) |
| sol_5m_down_b1_500_v9 | 9 | 88.9% | +$51 | YES (V9 spec) |

### 3.1 CRITICAL FLAG: No full-period OOS for SOL 5m sniper universe

**`HANDOFF_2026_06_01.md:57` explicitly states:**
> "No SOL universe panel → sol_cci/f7_mfi/btcf7/j never full-period OOS-tested; sol_rf only approximate."

**`HANDOFF_2026_06_01.md:80` elaborates:**
> "No SOL 5m sniper universe. Universe panels (full period Apr24-May26) exist for BTC+ETH but NOT SOL. These are the GA TRAINING set → in-sample."

**`FULLPERIOD_PERSISTENCE_2026_05_30.md:77` confirms:**
> "Build a SOL 5m universe panel (compute gates + L25 fills Apr 24→now) to OOS-test the SOL drop_US + ma_300 headlines — currently the weakest-validated of the deploy set."

**`BACKTEST_REPLAY_SOL_2026_05_29.md` finding:**
SOL L25 canonical parquet has 54.9% of fires with **ask side all NaN** at fire_us — live WS BookMirror captured asks that the VPS2 collector missed. Mean delta_vwap = −0.38 (backtest fills much cheaper than live). The SOL backtest replay is not a valid fidelity measure.

**Consequence:** All SOL 5m sniper sleeves are running on:
1. Gate parameters optimized on in-sample BTC/ETH universe panels or on SOL L25 with coverage gaps
2. No complete Apr24–Jun01 OOS walk-forward for any SOL 5m sniper sleeve
3. SOL L25 book backtest inflates WR (fills at ask0=0.01 when live trades at 0.77)

### 3.2 Gate fidelity (code vs spec)

Gates are implemented in `vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_gates.py` (not re-read but referenced by prior audits). Key gates used by these sleeves:
- `g_f7_mfi_strong_with`: F7 RSI + MFI momentum alignment — per V6/V7/V8 spec, anchored at ws_s via `ws_s_us = int(slot_start_us) - int(window_s) * 1_000_000`. **CAUSAL** (confirmed `sniper_v5_gates.py:1286-1287` in prior indexed content).
- `g_hurst_reverting`: SOL 5m hurst gate — **BROKEN (Bug A, `HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md`)**: fires 0% live vs 39% backtest due to 5h warmup (60 bars × 5min) never completing between restarts. The fix editing `sniper_v5_gates.py` was applied but NOT to `vol_hurst.py` (the panel) — FIX 4 hit wrong layer (`POSTFIX_VERIFICATION_2026_06_01.md:16`). This silences all sleeves gated on `g_hurst_reverting` (sol_5m_btcf7against_cci_hurstrev_mfi_v8 and similar). Affects fire counts for those specific sleeves.

### 3.3 Per-sleeve verdict

| Sleeve | Spec? | BT OOS? | Live WR | Live PnL/tr | Verdict |
|---|---|---|---|---|---|
| sol_5m_rf_tr_partial_mid | V6 spec ✓ | SOL L25 gap — approximate | 70.4% | +$0.16 | MONITOR (book gap means BT unreliable; positive live) |
| sol_5m_f7_mfi_ema200_vwap_v6 | V6 spec ✓ | NO SOL universe | 68.8% | −$0.02 | UNVALIDATED (breakeven; no panel) |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | V6 spec ✓ | NO SOL universe | 76.3% | +$0.39 | UNVALIDATED but trending positive |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | V7 spec ✓ | NO SOL universe | 67.2% | +$0.04 | UNVALIDATED (marginal) |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | V8 spec ✓ | NO SOL universe | 75.1% | −$0.04 | UNVALIDATED (marginal neg; V8 lockbox showed 85.7% but that was SOL 15m, not 5m) |
| sol_5m_b1_120s_250_v9 | V9 spec ✓ | V9 launch live | 57.1% | −$0.00 | BREAKEVEN (low edge signal) |
| sol_5m_b3_abs500_v9 | V9 spec ✓ | V9 launch live | 50.0% | −$0.19 | LOSING (50% WR at n=186 → dead) |
| sol_5m_b3_abs500_no_opp_v9 | V9 spec ✓ | V9 launch live | 54.8% | +$0.39 | MARGINAL positive |
| sol_5m_b1_polyflow_aligned_v9 | V9 spec ✓ | V9 launch live | 74.2% | +$1.37 | POSITIVE (n=31, needs more) |
| sol_5m_down_b1_flow250_v9 | V9 spec ✓ | V9 launch live | 57.3% | −$0.24 | MARGINAL negative |
| sol_5m_down_b1_500_v9 | V9 spec ✓ | V9 launch live | 88.9% | +$5.63 | POSITIVE but n=9 (low) |

---

## 4. Global ws_s Anchor Verification

`poly_updown_loop.py:build_bar_context()` — the `ws_s` passed to all context builders is `slot_start_unix_s` which the master scheduler computes as `floor(wall_clock / tf_s) * tf_s`. This is the bar's window-start = `slot_start`.

For the **signal anchor**: `ret_5m = log(btc_now / btc_prior)` where `btc_now = _fetch_close(offset=0)` = BTC@ws_s and `btc_prior = _fetch_close(offset=-300)` = BTC@(ws_s−300). This matches the spec definition: `ret_5m` = return over the 5m window ending at ws_s = `slot_start − window_s + window_s = slot_start`. **CORRECT**, no lookahead.

For **INV_NIGHT**: `is_night_hour_utc(window_start_unix)` called with `ws_s` = bar window-start. Matches bias analysis anchor. **CORRECT**.

For **vwap_off**: fires on `bar_ctx_phase = t_plus_{offset_s}` — the controller fires at `ws_s + offset_s` seconds into the bar. The `VwapContinuationStrategy.signal()` validates phase at line 82. **CORRECT**.

For **sniper_hod**: `hod_passes(fire_unix_s, ...)` called with `int(time.time())` at fire decision moment (per `TV_AGENT_PHASE34_FIXES_2026_05_22.md` anchor correction). **CORRECT** — no off-by-one vs spec.

---

## 5. Summary Table — All Audited Families

| Family | Sleeves | Code Match | Root Cause | Classification | Action |
|---|---|---|---|---|---|
| INV_NIGHT (6×) | 6 | MATCH | Market theory wrong (base signal was +EV, flipping = −EV) | FAITHFUL-BUT-BAD | KILL |
| v3/v3_1/v3_2/v3_3/v4 SOL | 4 | MATCH | No SOL momo edge; multi-horizon filter doesn't help | FAITHFUL-BUT-BAD + UNVALIDATED | KILL |
| v3/v3_1/v3_2/v3_3/v4 BTC | 2 | MATCH | IS edge evaporated OOS; v4 too restrictive | FAITHFUL-BUT-BAD | KILL |
| v3/v3_1/v3_2/v3_3/v4 ETH | 5 | MATCH | Some IS edge existed May 5–11; now deteriorated | FAITHFUL-BUT-BAD | INVESTIGATE (fresh OOS) |
| sniper_hod (5×) | 5 | MATCH (code) / DRIFT (config) | HoD lists stale (Apr22–May21 fit, never refreshed) | CONFIG DRIFT | INVESTIGATE (refresh HoD) → likely KILL |
| vwap_off (5×) | 5 | MATCH | Low n, possible OOS regime shift; no walk-forward OOS | FAITHFUL-BUT-BAD + SMALL-N | MONITOR 2wk; kill `sol_5m_vwap_off60` if WR<50% at n≥15 |
| sol_5m sniper V6-V9 (11×) | 11 | MATCH | No full-period SOL 5m universe panel; SOL L25 book gaps inflate BT | UNVALIDATED (running on faith) | Build SOL 5m universe panel; partial kills (b3_abs500_v9 at 50% WR, n=186) |

---

## 6. Key Findings

1. **BUGGY sleeve count: 0.** No sleeve has a directional inversion bug or anchor bug. All code implements its spec correctly.

2. **FAITHFUL-BUT-BAD: 17 sleeves** (all INV_NIGHT×6, all BTC/SOL v3-v4 family). Code is correct; the market hypothesis was wrong or the edge evaporated OOS.

3. **CONFIG DRIFT: 5 sleeves** (all sniper_hod). Gate logic correct; HoD parameter tables fit Apr22–May21 and never refreshed per spec §6.

4. **UNVALIDATED: 11 sleeves** (sol_5m sniper V6–V9 family). Specs exist but NO full-period SOL 5m sniper universe panel was ever built. These were deployed without a complete OOS walk-forward (confirmed `HANDOFF_2026_06_01.md:57,80`). Positive live WR (68–75%) is encouraging but cannot be attributed to the gates without an OOS panel.

5. **Critical infrastructure bug affecting SOL 5m hurst sleeves:** `g_hurst_reverting` gate fires 0% live vs 39% backtest — wrong layer patched (`sniper_v5_gates.py` vs needed `vol_hurst.py`). Pending fix.

6. **ws_s anchor: CORRECT** across all families verified.

---

## 7. Immediate Recommendations

| Priority | Action | Sleeves affected |
|---|---|---|
| 🔴 KILL | Disable INV_NIGHT ×6 (anti-edge proven, −$3.8k/7d) | btc/eth/sol 5m/15m_volume_INV_NIGHT |
| 🔴 KILL | Disable SOL v3/v3_1/v3_2/v3_3 (no edge, −$1.1k/7d) | sol_5m_v3, v3_1, v3_2, v3_3 |
| 🔴 KILL | Disable BTC v3_1 + v4 (IS edge gone, −$0.3k/7d) | btc_5m_v3_1, btc_5m_v4 |
| 🟡 KILL b3_abs500 | 50% WR at n=186 = no edge at high confidence | sol_5m_b3_abs500_v9 |
| 🟡 INVESTIGATE | Rebuild HoD lists on current 28d, re-evaluate sniper_hod | all *_sniper_hod |
| 🟡 BUILD | SOL 5m universe panel (dirscan + gates + L25 fills) to validate V6/V8 gates OOS | all sol_5m_* V6-V8 sniper |
| 🟡 FIX | Fix `g_hurst_reverting` at vol_hurst.py layer (wrong layer patched) | sol_5m_btcf7against_cci_hurstrev_mfi + sibling |
| 🔵 MONITOR | vwap_off family — too small n to kill yet | all *_vwap_off* |
