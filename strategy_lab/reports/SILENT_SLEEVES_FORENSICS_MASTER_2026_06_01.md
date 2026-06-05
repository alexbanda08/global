# Silent Shadow Sleeves — Master Forensics — 2026-06-01

Why 31 live shadow sleeves never fired since inception. Consolidates 4 family investigations + the JSONL/DB triage. **None are dispatch/wiring failures — every sleeve evaluates every slot.** Splits into 3 real bugs (13 sleeves), 1 dead stub, 12 low-base-rate, 2 suspect.

Family reports: `SILENT_FORENSICS_{VWAP,15M_TRSTACK,CROSSASSET_HOD,FAIREDGE_HLCASCADE}_2026_06_01.md`.

---

## 0. Verdict table (all 31)

| Family | n | Verdict | Actionable |
|---|--:|---|---|
| **vwap_off** | 5 | 🔴 **BUG** — aux wiring | FIX 1 |
| **fairedge / m5v / cvd overlays** | 6 | 🔴 **BUG** — feature not computed at gate time | FIX 2 |
| **SOL hlcascade v9** | 2 | 🔴 **BUG** — liquidation feed starved (+ SOL low base) | FIX 3 |
| **sol_5m cross-asset (v7/v8)** | 2 | 🔴 **BUG** — SOL 5m hurst panel broken (g_hurst_reverting 0% live vs 39% backtest) | FIX 4 |
| btc_5m_slotend_ofi_ts_v7 | 1 | ⚫ **DEAD_STUB** — OFI never wired | KILL or wire |
| ETH/SOL 15m trstack (+VL) | 8 | 🟢 LOW_BASE_RATE — premature deploy, gates correct | wait / de-prioritize |
| SOL 15m HOD v7/v8 | 4 | 🟢 LOW_BASE_RATE | wait |
| **TOTAL** | **28** unique (+3 overlap) | **15 BUG** · 1 stub · 12 base-rate | **4 fixes** + 1 kill |

---

## 1. 🔴 BUG 1 — vwap_off family (5 sleeves): aux wiring drops the phase, signal()→NONE every slot

**Sleeves:** btc_5m_vwap_off240_m1v, btc_5m_vwap_off60_f7_cross, btc_5m_vwap_off90_cross, eth_5m_vwap_off210_f7_m1v, sol_5m_vwap_off60.

**Root cause:** `polymarket_updown.py:_build_signal_aux()` (L1285-1650) special-cases momo / momo_v2 / vwap_kelly_ensemble / prewindow, then **falls through to the generic v3/sniper aux builder** for everything else. `VwapContinuationStrategy` gets that generic dict, which never sets `bar_ctx_phase = "t_plus_{offset}"` (nor `vwap_dev_bps`/`m1v`/`rsi`/`cross_asset_devs`). The strategy's FIRST line: `if aux.get("bar_ctx_phase") != "t_plus_240": return None` → `None != "t_plus_240"` → **returns NONE every slot, before any threshold/gate runs.**

**Smoking gun:** a recorded off240 slot with `vwap_dev_bps=9.645` (in 5-10 band, dev>0→UP) + `markov_regime_w20_1m_va=2` (bull→UP) + no other gate → MUST fire UP → logged `signal=NONE`. 374 band-passing off240 slots, 0 fires.

**Why it looked healthy:** the audit/log payload (L4786) reads vwap fields from a SEPARATE path (`self._bar_ctx_active`), so logged aux is correct — masking that `signal()` never received it.

**Spec trap:** `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md §7` said the aux fields "flow through (no-op)" — they don't.

**Impact:** backtest expected ~112/34/45/39/13 fires in 5.75d → got 0.

**FIX 1:** add a `vwap_continuation` branch to `_build_signal_aux` returning `bar_ctx_phase = self._bar_ctx_active.phase` + the 4 vwap fields (`vwap_dev_bps`, `m1v`, `rsi`, `cross_asset_devs`) from `_bar_ctx_active` — mirror the L4786 audit block.

---

## 2. 🔴 BUG 2 — fairedge/m5v/cvd overlays (6 sleeves): gate features = None at eval

**Sleeves:** eth_15m_sniper_m5v, btc_5m_momo_v2_fairedge500, btc_15m_momo_v2_fairedge500_cvd30, sol_15m_sniper_fairedge500, sol_5m_momo_v1_m5v, sol_5m_momo_v2_cvd_macd.

**Root cause:** the base strategies fire heavily (momo_v2 HOLD UP=120/DOWN=136, sniper_hod 100s) — so the overlays return NONE because the **overlay GATE fails, not the base signal.** The gate features (`fair_edge_bp`, `cvd_30s`, `macd_hist_value`) are computed **only** by `build_bar_context_t_plus_n` (the vwap/prewindow controllers). The overlays bucket to momo(t+120) / momo_v2(t+60) / bar_close context builders, which **never call `_compute_phase36_features`** → those features are **None at gate-eval time**. The `≥500` / cvd / macd thresholds are moot — you can't clear a threshold on a None.
- `markov_regime_w20_5m_va` is **hardcoded `=None` engine-wide** (loop L650/864; only the 1m regime exists) → both `m5v` sleeves are **doubly dead.**

**Smoking gun:** `fair_edge_bp` clears 500 on **42% of phase1_kelly fires** (proving the feature works on the t_plus_n path) but is **None on every overlay eval** (wrong context builder). `markov_regime_w20_5m_va` only ever assigned None.

**FIX 2:** route the overlay sleeves through (or additionally invoke) `_compute_phase36_features` in their context builder so `fair_edge_bp`/`cvd_30s`/`macd_hist_value` are populated at gate time; implement (or stop gating on) `markov_regime_w20_5m_va` (currently never computed).

---

## 3. 🔴 BUG 3 — SOL hlcascade v9 (2 sleeves): liquidation feed starved

**Sleeves:** sol_5m_a2_hlcascade25k_v9, sol_5m_up_a2_hlcascade15k_v9.

**Root cause:** the `g_a2_hl_short_cascade` gate reads the engine's in-process `CexLiquidationFeed`, which is **starved**: `bybit_liquidations_v2` + `bitget_liquidations_v2` tables are EMPTY, okx/gate connections frequently stale-reconnecting. So the gate is **TRUE 0 times for EVERY asset** — BTC 0/3177, ETH 0/961, SOL 0/864.

**Smoking gun:** DB ground-truth (6d, buy-side) shows **BTC has 56 rolling-300s windows >$100k** → the gate should fire dozens of times → fired 0. Proves the gate logic is fine but the live feed is empty.
- **Reconciliation note:** the BTC v9 hlcascade sleeves DID fire ~May 29 (n=6, +$3-7). The feed has degraded SINCE (bybit/bitget collectors stopped populating). So this bug is **recent / progressive** — verify the collector health, not just the gate.
- SOL separately has only ~9 short-liqs / 6d (~4 windows >$25k) = genuinely **LOW_BASE_RATE even with a healthy feed** (V9 spec §2.4 already said "SOL/ETH: insufficient HL data, do not use").

**FIX 3:** repair the multi-venue liquidation collectors (bybit_liquidations_v2 / bitget_liquidations_v2 empty; okx/gate stale) feeding `CexLiquidationFeed`. The SOL hlcascade sleeves should likely be killed regardless (insufficient SOL liq base rate per spec).

---

## 4. ⚫ DEAD_STUB — btc_5m_slotend_ofi_ts_v7
`g_slot_end_ofi_with` hard-returns False (OFI TradeMirror subscriber never wired). Cannot fire by construction. **KILL** (its trade buffer already feeds the V9 B-gates) or wire the OFI subscriber.

---

## 5. 🟢 LOW_BASE_RATE — 12 sleeves (NO bug; gates verified correct)

**ETH/SOL 15m trstack + VL (8):** `g_tr_stack_full_with` is CORRECT (live passes ~41% vs backtest 16% — MORE permissive live). It only *looked* like the blocker because the log reports the first-failing gate in declaration order (it's gate #0). Backtest density 1.5-3 fires/day (some deployed on n=8-12 lockboxes) → ~2-5 raw expected in 2.6d, gutted by spread + sparse-book + the $150 `g_book_supports_stake` veto on thin 15m books → **0 is an ordinary low-count outcome.**

**SOL 15m HOD v7/v8 (4):** `g_hod_european_morning` correct (UTC 07-11, 5h/day, pure epoch math). 1.7-3.2 fires/day backtest → Poisson P(0)≈0.02-1% in 2.6d (borderline but plausible).

**Action:** none — wait for more days, or de-prioritize. Re-audit after 7-14d. These were deployed on thin backtest evidence.

**Also a triage artifact worth noting:** the dashboard/log "dominant skip" = first-False gate in declaration order, NOT the true bottleneck. Don't read it as "this gate is too strict" without checking pass-rate.

---

## 6. 🔴 BUG 4 — sol_5m cross-asset (2 sleeves): SOL 5m hurst panel broken (RESOLVED from SUSPECT)
**sol_5m_btctrend_cci_hurstrev_v7, sol_5m_btcf7against_cci_hurstrev_mfi_v8.** SETTLED via live per-gate True-rate + backtest clustering (`SUSPECT_SOL5M_TIMESTAMP_CHECK_2026_06_01.md`).

**Root cause:** `g_hurst_reverting(SOL,5m)` is True **0.0% live (0 / 16,322 evals, every one of 6 days)** but **39.2% in backtest** (39,801/101,500). It's a required gate in BOTH conjunctions → both sleeves hard-blocked → 0 fires. All other gates healthy (live: btc_trend 43.5%, btc_f7_against 22.4%, cci_extreme(SOL) 7.9%, mfi 40.7%). So it's the **SOL 5m hurst panel**, not CCI.

**Why not base-rate:** backtest fires are UNIFORM ~30/day (661 v7 / 650 v8 fires, no dead days, median 31-32/day) — matches the projected ~20/day. The sleeves WOULD fire live if hurst worked.

**Smoking gun:** same gate 39% backtest / 0% live → the live SOL 5m hurst feed returns a value that never satisfies `<0.40` (stale/None/NaN, mis-thresholded, or wrong asset/tf wiring).

**FIX 4:** inspect the live SOL 5m hurst panel (VolHurst `hurst_60` for SOL at 5m) for stale/None/NaN or a value pinned above 0.40. Likely affects ANY SOL-5m sleeve gating on `g_hurst_reverting` / `g_hurst_*`. Verify the hurst computation receives SOL 5m bars (not empty/zero-variance → NaN→clamp). Check ETH/BTC 5m hurst too (may share the defect).

---

## 7. Fix priority for TV
1. **FIX 1 — vwap aux branch** (5 sleeves, ~230 fires/wk expected) — add `vwap_continuation` case to `_build_signal_aux`.
2. **FIX 2 — overlay feature wiring** (6 sleeves) — populate phase36 features in the overlay context builders; fix/remove `markov_regime_w20_5m_va` gating.
3. **FIX 3 — liquidation collectors** (bybit/bitget empty, okx stale) — repair the CexLiquidationFeed; also affects the BTC v9 hlcascade sleeves that have gone silent since ~May 29.
4. **KILL** btc_5m_slotend_ofi_ts_v7 (or wire OFI).
5. **De-prioritize / re-audit-in-2wk** the 12 low-base-rate 15m sleeves; consider killing the ones deployed on n<20 lockboxes.
6. **1 follow-up check**: backtest-fire-timestamp clustering for the 2 SUSPECT sol_5m sleeves.

## 8. Cross-cutting lesson
The dashboard "dominant skip reason" is the **first-failing gate in declaration order**, not the binding constraint — it misled the initial triage (made correct-but-rare gates look like bugs). The REAL bugs (vwap aux, overlay features, liq feed) were invisible at the skip-reason level because the signal/feature was silently None/empty UPSTREAM of the gates. Validate feature-populated-at-eval, not just skip-reason, when a sleeve is silent.

## END
