# DEBUG FINDINGS — All Shadow Sleeves (Live vs Spec vs Backtest) — 2026-05-29

> ⚠️ **PARTIALLY SUPERSEDED — read `AUDIT_FINAL_CORRECTED_2026_05_29.md` first.**
> 3 corrections: (1) **Bug 1 RETRACTED** — the 0.07·p·(1−p) fee curve is CORRECT, not a bug (our backtests using legacy 2% were the wrong ones). (2) **Bug 8 INV_NIGHT moot** — already deprecated/hidden, historical not active. (3) HEDGE/SELL sleeves already deprecated. Bugs 2/3/4 (btc_5m_q, V8_01/02 gate, vwap80) remain valid. V9 is live+working on multi-venue liqs.

Consolidated debug document from the full 132-sleeve audit. Every bug/mismatch found across 8 agent investigations, with code locations, severity, affected sleeves, root cause, fix, and status.

For TV agent: items marked 🔴 ACTIVE need code fixes. Items ✅ FIXED are confirmed already-deployed (listed for completeness). Items ⚠/ℹ are investigations / benign.

---

## BUG 1 — Fee model split-brain [🔴 ACTIVE · HIGH · SYSTEMIC]

**Affects:** ALL 132 sleeves (both sniper_v5 AND momo/updown controllers).

**Finding:** Resolution PnL uses the Polymarket taker curve `0.07·p·(1−p)` (winner-only) instead of the production-verified legacy `2%-on-profit`.
- sniper_v5 HOLD path: `pnl_won = (1-vwap)·shares·(1 − 0.07·vwap)` — labeled "operator-confirmed 2026-05-28"
- sniper_v5 HEDGE_LATE path: `pnl·0.98` (legacy) — INCONSISTENT with HOLD path
- momo resolver (`slot_resolution_pnl` / `apply_resolution_fee`): also `0.07·p·(1−p)` winner-only

**Why it's a bug:** CLAUDE.md documents a 25,900-event verification that production BTC/ETH/SOL up-down markets charge legacy **2%-on-profit only** (`pnl_won = (1-vwap)·shares·0.98`, no fee on losers). The 0.07 curve **overstates fees ~2.4× at p=0.69** (~$0.34/win), so all shadow PnL is **understated** (conservative direction, but wrong + internally inconsistent).

**Code locations:**
- `controllers/polymarket_sniper_v5.py` — `book_event_for_resolution` (HOLD) vs `maybe_hedge_late_cut` (hedge)
- momo: `slot_resolution_pnl` / `apply_resolution_fee` (poly_updown path)

**Fix:** Switch BOTH controllers' resolution PnL to legacy 2%-on-profit (`engine_v2.LegacyConfig` semantics). Make HOLD and HEDGE paths consistent. If operator intends to model the curve as a "future Polymarket fee" hypothetical, gate it behind a config flag defaulting OFF.

**Impact on this audit:** backtest comparisons used the LIVE fee model per-family to isolate non-fee divergences, so this bug does NOT invalidate the fidelity findings — but it does mean live shadow PnL is not the true production-fee PnL.

---

## BUG 2 — btc_5m_q_parent15mslope_ts_imb5_v8 over-optimistic backtest [🔴 KILL · HIGH]

**Affects:** `poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8` (1 sleeve).

**Finding:** Live −$352 (520 fires, 68% WR). Original V8 backtest projected **+$6.20/tr**. Canonical replay of live's actual fires = **−$0.43/tr** (387 fresh-book fires: live≈bt within 0.003 vwap, −$0.027/tr).

**Root cause:** The sleeve is genuinely loss-making. The original +$6.20 projection was a **false positive** — most likely the V8 search harness evaluated `g_imb5_strong_with` (order-book imbalance) with look-ahead (imbalance computed with information not available at fire time), selecting winning fires that don't generalize. Live reads imbalance from the BookMirror at dispatch (causal) → real signal decay.

**Verification:** replay re-fill at fire_us reproduces the live loss → not a fill/fee artifact. Fidelity audit confirmed gates deployed per spec → not a gate-wiring bug. The sleeve's edge simply doesn't exist out-of-sample.

**Fix:** KILL the sleeve. Audit the V8 search harness's imbalance gate for look-ahead before trusting other imb5-based projections.

---

## BUG 3 — V8_01 / V8_02 gate mismatch [🔴 ACTIVE · HIGH]

**Affects:** `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8`, `poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8`.

**Finding:** Spec's first gate = `g_1h_rf_with` (1h Range Filter `rf_dir` indicator). Live's first gate = `g_grandparent_trend_with` (1h `trend_slope_30m` sign). Distinct functions → the live sleeves run an **un-validated gate combination**; backtest numbers (validated with `g_1h_rf_with`) don't describe live behavior.

**Live status:** both currently positive but LOW_N (n=20/19, 85%/84% WR) — small sample, can't conclude.

**Code location:** `strategies/polymarket/sniper_v5_sleeves.py` — the two V8 sleeve definitions; first `GateRef`.

**Fix:** Replace `g_grandparent_trend_with` with `g_1h_rf_with` per spec, OR re-validate the sleeve as-built with `g_grandparent_trend_with` and update the spec. Pick one source of truth.

---

## BUG 4 — vwap80 gate semantic flip [🔴 ACTIVE · HIGH]

**Affects:** 4 SOL 15m sleeves — `sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6`, `sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6`, `sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6` (V6), and V7_11/V7_12 equivalents.

**Finding:**
- Spec: `vwap_book < 0.80` (ceiling — exclude overpriced entries)
- Live: `g_vwap_premium` = `vwap ≥ 0.55` (floor — require premium entries)
- Overlap in [0.55, 0.80] but live **rejects low-vwap entries (0.20–0.54)** that spec/backtest allow. Different fire population → live ≠ backtest.

**Live status:** net losers (tightrib −$22 on 9 fires, others −$3/−$5 LOW_N), consistent with the wrong gate admitting worse entries.

**Code location:** `strategies/polymarket/sniper_v5_gates.py` — `g_vwap_premium` used where spec wants a `vwap < 0.80` ceiling gate; the 4 sleeve defs in `sniper_v5_sleeves.py`.

**Fix:** Implement a `g_vwap_ceiling_80` gate (`vwap < 0.80`) and swap it into the 4 sleeves, OR re-validate with the floor semantics + update spec.

---

## BUG 5 — rv_60 scale (vol_high / vol_contracting) [✅ FIXED]

**Affects:** `g_vol_high` (10 sleeves incl. eth_15m_trstack_vwap_vol_offearly, sol_15m_trstack_vol_ribbon), `g_vol_contracting` (btc_15m_btceth_diverg_stoch_volcontr_v8).

**Was:** panel annualized `rv_60 = rv·√AF` (×324 for 5m / ×187 for 15m) but `VOL_HIGH_RV60_THR` is raw scale → `g_vol_high` always-True (no-op), `g_vol_contracting` always-False (permanent block, 0 fires).

**Status:** ✅ FIXED in live — `raw_rv = row.rv_60 / √AF` before threshold compare (TV_FIX_VOL_HIGH_RV60_SCALE_BUG applied). btc_15m_btceth_diverg fires post-fix. **Caveat:** pre-fix shadow data for those sleeves is contaminated (vol filter was inert).

---

## BUG 6 — Synthetic-fill 0.5 placeholder [✅ FIXED]

**Was:** `_simulate_l25_walk` returned `(0.5, notional/0.5)` placeholder when BookMirror empty → fictional fills polluting WR/PnL (28% of placed fires on 2026-05-27).

**Status:** ✅ FIXED — all book reads route through `paper.get_orderbook_snapshot` (3-tier WS→CLOB→Storedata). Placeholder path eliminated. Matches the unified book-read spec.

---

## BUG 7 — Spread metric cross-token [✅ FIXED]

**Was:** `_compute_spread` used cross-token `abs(up_vwap − (1−dn_vwap))` (failed 99%+ of fires) instead of same-token bid-ask.

**Status:** ✅ FIXED — now `ask0 − bid0` via `_sniper_spread.compute_spread` (matches engine_v2:234). Cross-token logged as `cross_spread_old` for audit.

---

## BUG 8 — INV_NIGHT dead anti-edge [🔴 KILL · per-spec, not a code bug]

**Affects:** 6 sleeves — `{btc,eth,sol}_5m_volume_INV_NIGHT` + 15m variants. Combined ≈ **−$3,647**.

**Finding:** Per-spec anti-edge EXPERIMENT (`inverse.py`): flips the raw V1-volume signal during night hours {1,2,3,4,5,9,10} UTC, betting the original is 60-65% wrong. Live falsifies the premise — flipped WR ≈44% ⇒ original was ~56% right ⇒ flipping loses. The raw `volume` mode also has **no quality gate** (fires every night bar).

**Status:** faithful to spec, but the hypothesis is dead. **KILL all 6.**

---

## BUG 9 — HoD top-8 lists stale [⚠ INVESTIGATE · MED]

**Affects:** all `*_hod` / `*_sniper_hod` / `momo_hod` sleeves (~10).

**Finding:** Hour-of-Day specialization relies on monthly-refreshed "top-8 hours" lists. The monthly refresh job was **never built** → sleeves run on stale (initial) HoD lists. Can't fairly judge HoD sleeves until refreshed. Most sniper_hod are bleeding (btc15m −$287, btc5m −$267) — likely kill, but confirm post-refresh.

**Fix:** Build the monthly HoD recompute job, refresh lists, re-evaluate.

---

## BUG 10 — Minor / benign [ℹ]

- **Kelly override not reset to None** after use (`shadow9`) — latent foot-gun, benign today.
- **F7 boundary** uses `<=`/`>=` skipping exact RSI=50 — per-spec, negligible.
- **V7_02 `btc_5m_slotend_ofi_ts_v7`** — `g_slot_end_ofi_with` hard-returns False (OFI subscriber not wired) → 0 fires. Intentional experimental stub, not a blocker.
- **chainlink/CLOB outcome disagreement** — 1 slug (`btc-updown-15m-1779921000`, −6 BPS on strike). Edge-case, not systematic (outcome match 98-100% elsewhere).

---

## DATA / INFRA LIMITATIONS (not sleeve bugs, but block full validation)

### L-1 — SOL canonical L25 too sparse [⚠]
SOL `orderbook_l25/sol.parquet` (586 MB, 11× thinner than BTC) has **55% NaN ask-side** snapshots — the VPS2 collector frequently recorded empty asks. Only ~2.8% of SOL fires are price-comparable in backtest. **SOL sniper fill fidelity is unverifiable from canonical.** Outcomes are valid (98-100% match). Densify the SOL book archive for future validation.

### L-2 — 1s-trade features absent from canonical [⚠]
`fair_edge_bp`, `cvd`, `macd`, `vwap_dev` (1-second trade-derived) are not in canonical for the shadow window. Blocks backtest of the **highest-value live winner** (`shadow_phase1_kelly` +$1,900) + both prewindow sleeves + fade family. Add these to the canonical pipeline.

### L-3 — L25 tail gap [ℹ]
Canonical L25 ends May 29 10:01 (BTC) / 13:13 (ETH/SOL); live window runs to 16:41. Last 3-6h of fires uncomparable. Minor.

### L-4 — Mid-window fix contamination [ℹ]
Bugs 5/6/7 were fixed DURING the shadow window (engine restarted repeatedly). Pre-fix fires are contaminated. For clean validation, use only post-last-fix live data, or re-baseline after 48h of all-fixes-deployed running.

---

## PRIORITY FIX ORDER FOR TV

1. **Fee split-brain (Bug 1)** — affects every sleeve's reported PnL. Align both controllers to legacy 2%-on-profit, make HOLD/HEDGE consistent.
2. **vwap80 flip (Bug 4)** + **V8_01/02 gate (Bug 3)** — active gate mismatches running un-validated combos.
3. **KILL list** — btc_5m_q (Bug 2), INV_NIGHT ×6 (Bug 8), fade ×5, sniper_hod (pending Bug 9 refresh), BTC/SOL v3/v4. Removes ≈ −$6k/window bleed.
4. **Build HoD monthly refresh (Bug 9)** then re-judge *_hod.
5. **Data infra (L-1, L-2)** — densify SOL L25, add 1s-trade features to canonical.

## END
