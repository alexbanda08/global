# TV Agent Fix Spec — 3 Silent-Sleeve Bugs + 1 Dead Stub — 2026-06-01

For the TV agent (tradingvenue repo, VPS3). Three real bugs make 13 shadow sleeves never fire (they evaluate every slot but a feature/signal/feed is silently empty UPSTREAM of the gates). Plus one dead stub to kill. Evidence: `SILENT_SLEEVES_FORENSICS_MASTER_2026_06_01.md` + the 4 family reports.

**Common signature:** the sleeve logs evals/signals every slot (NOT a dispatch bug), but the placement never happens because a required input is `None`/empty when the gate reads it. The dashboard "dominant skip reason" is the first-failing gate in declaration order — it does NOT point at these bugs. Validate **feature-populated-at-eval**, not skip-reason.

---

## FIX 1 — vwap_off family: aux assembly drops the phase (5 sleeves)

**Sleeves:** `poly_updown_btc_5m_vwap_off240_m1v`, `_btc_5m_vwap_off60_f7_cross`, `_btc_5m_vwap_off90_cross`, `_eth_5m_vwap_off210_f7_m1v`, `_sol_5m_vwap_off60`.

**File:** `backend/app/strategies/polymarket/polymarket_updown.py` → `_build_signal_aux()` (~L1285-1650).

**Bug:** the method special-cases `momo` / `momo_v2` / `vwap_kelly_ensemble` / `prewindow`, then falls through to the generic v3/sniper aux dict for everything else — including `vwap_continuation`. That generic dict never sets `bar_ctx_phase`, `vwap_dev_bps`, `m1v`, `rsi`, `cross_asset_devs`. `VwapContinuationStrategy.signal()` first line:
```python
if aux.get("bar_ctx_phase") != f"t_plus_{self.offset_s}":   # None != "t_plus_240"
    return None                                              # → NONE every slot
```
So it returns NONE before any threshold/gate runs. (The audit/log path at ~L4786 reads these fields from `self._bar_ctx_active` directly — which is why the logged aux looked correct and masked the bug.)

**Fix:** add a `vwap_continuation` branch to `_build_signal_aux` that returns the live `_bar_ctx_active` fields — mirror the L4786 audit block:
```python
if strategy_kind == "vwap_continuation":
    bc = self._bar_ctx_active
    return {
        **base_aux,
        "bar_ctx_phase":   bc.phase,           # "t_plus_60" | "t_plus_90" | "t_plus_210" | "t_plus_240"
        "vwap_dev_bps":    bc.vwap_dev_bps,
        "m1v":             bc.markov_regime_w20_1m_va,
        "rsi":             bc.rsi,
        "cross_asset_devs": bc.cross_asset_devs,
    }
```
(Match the exact field names `VwapContinuationStrategy.signal()` reads + the exact `_bar_ctx_active` attribute names — confirm both before editing.)

**Verify:** after the fix, an off240 slot with `vwap_dev_bps` in [5,10] + markov bull must emit a UP signal (not NONE). Backtest expects ~112/34/45/39/13 fires per 5.75d across the 5 sleeves — confirm fires appear within hours.

---

## FIX 2 — fairedge / m5v / cvd overlays: gate features = None at eval (6 sleeves)

**Sleeves:** `shadow_poly_updown_eth_15m_sniper_m5v`, `_btc_5m_momo_v2_fairedge500`, `_btc_15m_momo_v2_fairedge500_cvd30`, `_sol_15m_sniper_fairedge500`, `_sol_5m_momo_v1_m5v`, `_sol_5m_momo_v2_cvd_macd`.

**Bug:** the overlay GATE (`fair_edge_bp ≥ 500`, `cvd_30s …`, `macd_hist …`) reads features that are computed ONLY inside `build_bar_context_t_plus_n` → `_compute_phase36_features`. But these overlays bucket their context to the momo (t+120) / momo_v2 (t+60) / bar_close builders, which **never call `_compute_phase36_features`** → `fair_edge_bp` / `cvd_30s` / `macd_hist_value` are **None at gate-eval time**. The thresholds can never clear a None. (Base signal fires fine — only the overlay gate fails.)
- Additionally: `markov_regime_w20_5m_va` is hardcoded `=None` engine-wide (loop ~L650/L864 — only the 1m regime is ever assigned). Both `m5v` (Markov-5m-vote) sleeves gate on it → doubly dead.

**Smoking gun:** `fair_edge_bp` clears 500 on 42% of `phase1_kelly` fires (works on the t_plus_n path) but is None on every overlay eval.

**Fix (two parts):**
1. **Populate phase36 features for the overlay context builders** — invoke `_compute_phase36_features` (or copy its `fair_edge_bp` / `cvd_30s` / `macd_hist_value` assignment) inside the momo / momo_v2 / bar_close builders that these overlays use, so the features are non-None when the overlay gate reads them. (Cheapest: compute them unconditionally in the shared bar-context assembly, not only in the t_plus_n path.)
2. **`markov_regime_w20_5m_va`** — either implement the 5m-window Markov regime (mirror the existing `w20_1m` computation at the 5m bar cadence) or remove the m5v sleeves' dependency on it. Until one is done, the 2 m5v sleeves cannot fire.

**Verify:** after fix, the fairedge sleeves should fire on the ~42% of base-fire slots where `fair_edge_bp ≥ 500`; confirm non-None `fair_edge_bp`/`cvd`/`macd` in the signal-event `data` JSONB.

---

## FIX 3 — CexLiquidationFeed starved: hlcascade gate TRUE 0× on all assets (2 SOL sleeves + the silent BTC v9)

**Sleeves directly:** `poly_sniper_v5_sol_5m_a2_hlcascade25k_v9`, `_sol_5m_up_a2_hlcascade15k_v9`. **Also affects** the BTC v9 hlcascade sleeves (`btc_5m_a2_hlcascade100k_v9`, `btc_5m_up_a2_hlcascade50k_v9`) which fired ~May 29 then went silent.

**Bug:** `g_a2_hl_short_cascade` reads the engine's in-process `CexLiquidationFeed`. That feed is starved:
- `bybit_liquidations_v2` + `bitget_liquidations_v2` collector tables are **EMPTY**
- okx / gate liquidation connections frequently stale-reconnecting

Result: the gate is TRUE **0 times for EVERY asset** — BTC 0/3177, ETH 0/961, SOL 0/864 evals.

**Smoking gun:** DB ground-truth (6d, buy-side) shows BTC has **56 rolling-300s windows >$100k** → the gate should have fired dozens of times → fired 0. Gate logic is fine; the live feed is empty. The BTC v9 hlcascade sleeves firing ~May 29 then going silent = **progressive collector failure** (the multi-venue feed degraded after deploy).

**Fix:**
1. **Repair the liquidation collectors** — diagnose why `bybit_liquidations_v2` / `bitget_liquidations_v2` are not being populated and why okx/gate connections are stale-reconnecting. Confirm `CexLiquidationFeed` receives live liquidation events for at least BTC/ETH.
2. **Add a feed-health alert** — if no liquidation events arrive for N minutes, emit a WARNING (so a starved feed doesn't silently zero the hlcascade sleeves again).
3. **SOL hlcascade specifically**: even with a healthy feed, SOL has only ~9 short-liqs/6d (~4 windows >$25k) = genuinely too sparse (V9 spec §2.4 already said "SOL/ETH: insufficient HL data, do not use"). **Recommend killing the 2 SOL hlcascade sleeves** regardless; the BTC ones are the viable cells once the feed is repaired.

---

## FIX 4 — SOL 5m hurst panel broken: g_hurst_reverting True 0% live vs 39% backtest (2 sleeves)

**Sleeves:** `poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7`, `poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8`.

**Bug:** `g_hurst_reverting(SOL, 5m)` (passes when hurst_60 < 0.40, mean-reversion regime) is True **0.0% live — 0 of 16,322 evals, every one of 6 days** — but **39.2% in backtest** (39,801/101,500). It is a required gate in both conjunctions → both sleeves hard-blocked → 0 fires. Every OTHER gate is healthy live (btc_trend 43.5%, btc_f7_against 22.4%, cci_extreme(SOL) 7.9%, mfi 40.7%), and backtest fires are uniform ~30/day with no dead days — so the sleeves would fire if hurst worked. Not base-rate.

**Smoking gun:** identical gate, 39% backtest vs 0% live → the live SOL 5m `hurst_60` value never drops below 0.40.

**File:** `backend/app/features/vol_hurst.py` (`hurst_60` via `_hurst_rs`, R/S method over the trailing 60 1s/5m log-returns) + how the controller feeds the SOL 5m series into the VolHurst panel.

**Likely causes to check (in order):**
1. **Stale/None/NaN** — SOL 5m hurst returns None/NaN and the gate treats non-`<0.40` as False (so it never passes). Check the panel actually emits a finite hurst_60 for (SOL, 5m) at eval time.
2. **Pinned high** — the value is computed but always ≥0.40 live (e.g. degenerate input: zero-variance or too-few bars → R/S → ~0.5; warmup never completes for SOL 5m).
3. **Wrong asset/tf wiring** — the SOL 5m hurst reads the wrong series (e.g. 1s vs aggregated 5m, or a different asset).

**Fix:** make the live SOL 5m hurst_60 reproduce the backtest distribution (39% < 0.40). Verify it receives proper SOL 5m bars + completes warmup. **Also audit ETH/BTC 5m hurst** — they may share the defect (any `g_hurst_*` 5m sleeve is at risk). After fix, both sleeves should fire ~20-30/day.

---

## KILL — btc_5m_slotend_ofi_ts_v7 (dead stub)
`g_slot_end_ofi_with` hard-returns `False` (the OFI TradeMirror subscriber was never wired) → the sleeve cannot fire by construction. Either **kill it** (its trade buffer already feeds the V9 B-gates) or wire the OFI subscriber if the slot-end-OFI signal is still wanted.

---

## Not bugs (no action — documented so they aren't re-investigated)
- **ETH/SOL 15m trstack + VL (8)** + **SOL 15m HOD v7/v8 (4)** = LOW_BASE_RATE. Gates verified correct (`g_tr_stack_full_with` passes MORE live than backtest; `g_hod_european_morning` UTC 07-11 correct). Deployed on thin n=8-12 lockboxes; 0 fires in 2.6d is an ordinary low-count outcome. **Re-audit after 7-14 days**; consider killing the ones deployed on n<20.
- **spread `0.0200_>_0.0200` log** = IEEE-754 display artifact on genuinely 2¢-wide books, not a `>`/`>=` bug. Optional determinism fix: `round(spread,4)` mirrored in `engine_v2.fill_at_book:234`.

---

## Deliverable checklist
1. FIX 1 — add `vwap_continuation` branch to `_build_signal_aux` (5 sleeves).
2. FIX 2 — populate phase36 features in overlay context builders + implement/remove `markov_regime_w20_5m_va` (6 sleeves).
3. FIX 3 — repair bybit/bitget/okx liquidation collectors + feed-health alert (2 SOL + restores BTC v9); kill the 2 SOL hlcascade sleeves.
4. FIX 4 — repair the SOL 5m hurst panel (`g_hurst_reverting` 0% live vs 39% backtest); audit ETH/BTC 5m hurst for the same defect (2 sleeves + any 5m hurst gate).
5. KILL btc_5m_slotend_ofi_ts_v7 (or wire OFI).
6. Re-audit the 12 low-base-rate 15m sleeves in 7-14d.
7. Add a unit/integration check: for every shadow sleeve, assert its gate features are non-None AND in a plausible range at eval (catch this whole bug class — None features AND pinned/degenerate values — at deploy, not weeks later).

## END
