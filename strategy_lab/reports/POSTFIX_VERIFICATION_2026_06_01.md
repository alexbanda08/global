# Post-Fix Verification — Silent Sleeves — 2026-06-01

TV deployed the 4 fixes (uncommitted working-tree edits; engine restarted 09:50 UTC, n_sleeves=90). Verified ~2h post-restart. **Code for all 4 landed, but only FIX 1 demonstrably works; FIX 4 and FIX 3 did NOT.**

Note: 2h is a SHORT window — low-rate sleeves can't be fully confirmed yet. Verdicts below mark CONFIRMED vs PENDING vs FAILED on the evidence available.

---

## Scorecard

| Fix | Sleeves | Code landed? | Gate/signal works now? | Verdict |
|---|--:|:--:|---|---|
| **FIX 1 vwap aux** | 5 | ✅ (`vwap_continuation` branch @ controller L1049) | ✅ **btc_5m_vwap_off240_m1v PLACED** (11:50); all 5 evaluating | ✅ **FIXED** |
| **FIX 2 fairedge/m5v feat** | 6 | ✅ (7 phase36/fair_edge refs) | all 6 evaluating (9-27 signals); 0 placements in 2h | 🟡 **PENDING** (rare ≥500; m5v uncertain) |
| **FIX 3 liq feed** | 2 SOL +BTC v9 | ✅ (cex_liq_feed edited) | ❌ **bybit+bitget tables STILL 0 rows**; only okx(660)/gate(224) feed; cascade gate 0% (btc 0/28, sol 0/12) | ❌ **STILL IMPAIRED** |
| **FIX 4 SOL 5m hurst** | 2 | ⚠ edited `sniper_v5_gates.py` but NOT `vol_hurst.py` (the panel) | ❌ **g_hurst_reverting still 0/224** | ❌ **FAILED — wrong layer** |

---

## Detail

### ✅ FIX 1 — vwap_off (5 sleeves) — WORKS
- `vwap_continuation` branch now in `controllers/polymarket_updown.py` (L1049 + L1316 comment confirming the bar_ctx_phase/momo pattern).
- **Proof**: `poly_updown_btc_5m_vwap_off240_m1v` PLACED 1 fire (10:50→11:50). The phase-gate-NONE bug is gone.
- Other 4 (off60_f7_cross, off90_cross, eth off210, sol off60): evaluating (26-27 signals each), 0 placements yet — expected; their f7_cross/m1v gates fire less often. Will accumulate.
- **Will fire: all 5** (1 confirmed, 4 will follow at their natural rate ~6-20/day each).

### 🟡 FIX 2 — fairedge/m5v/cvd (6 sleeves) — PENDING
- phase36 features now wired (7 refs). All 6 evaluate (signals 9-27 each).
- **0 placements in 2h** — `fair_edge_bp ≥ 500` is rare (clears on ~42% of base-fire slots, AND needs a base fire, in a 2h window → few chances). Inconclusive yet.
- **Risk**: the 2 `m5v` sleeves (eth_15m_sniper_m5v, sol_5m_momo_v1_m5v) gate on `markov_regime_w20_5m_va` which FIX 2 was supposed to implement-or-remove — unconfirmed it's now computed. If still None, those 2 stay dead.
- **Likely fire: 4 fairedge/cvd** (give 24-48h to confirm). **Uncertain: 2 m5v.**

### ❌ FIX 3 — hlcascade (2 SOL + BTC v9) — STILL IMPAIRED
- `cex_liq_feed.started` logs `exchanges: okx,bybit,gate,bitget`, but the collector tables show **bybit=0, bitget=0** rows; only **okx=660, gate=224** populated (max ts ~10:34 UTC, so okx/gate ARE live).
- The 2 biggest perp liq venues (bybit, bitget) are STILL down → aggregate liq notional missing ~50-70% → the $50-100k cascade thresholds rarely hit. Gate still 0% post-fix (btc 0/28, sol 0/12 in 2h — partly a quiet window, partly missing volume).
- **Will fire: probably not reliably.** BTC v9 may catch an occasional okx/gate-only cascade; the **2 SOL hlcascade won't** (SOL liq genuinely too sparse — V9 spec §2.4 already said exclude SOL). **Fix incomplete — repair bybit/bitget collectors.**

### ❌ FIX 4 — SOL 5m hurst (2 sleeves) — FAILED (wrong layer)
- TV edited `sniper_v5_gates.py` (the GATE) but **NOT `vol_hurst.py` (the PANEL)** that produces `hurst_60`.
- **g_hurst_reverting still True 0/224** post-restart (other gates healthy: btc_trend 85, cci 14, btc_f7_against 55, mfi 64). The panel still feeds a hurst value that never drops below 0.40 for SOL 5m.
- **Will fire: NO.** The root cause (panel emits None/pinned/degenerate hurst_60 for SOL 5m) is untouched. **Re-do FIX 4 at the panel layer** (`vol_hurst.py` — verify SOL 5m hurst_60 is finite + reproduces the backtest 39%-<0.40 distribution; check warmup/zero-variance→NaN handling).

---

## Bottom line — how many of the 15 bug-sleeves fire now

| Bucket | n | Sleeves |
|---|--:|---|
| ✅ **Firing now (fixed)** | **5** | vwap_off ×5 (1 placed, 4 will follow) |
| 🟡 **Likely (confirm in 24-48h)** | **4** | fairedge/cvd ×4 |
| ⚠ **Uncertain** | **2** | m5v ×2 (markov_5m dependency) |
| ❌ **Still broken (fix failed/incomplete)** | **4** | sol_5m hurst ×2 (wrong layer) + sol hlcascade ×2 (feed half-dead) |
| (BTC v9 hlcascade) | — | impaired — may fire occasionally on okx/gate |

Plus the **12 low-base-rate** sleeves (never bugs) fire slowly over time, and **btc_5m_slotend_ofi** dead stub (not addressed — kill).

## Still-open actions for TV
1. **Redo FIX 4 at the panel** — `vol_hurst.py` SOL 5m hurst_60 (gate edit didn't help; still 0%).
2. **Finish FIX 3** — repair bybit + bitget liquidation collectors (tables empty); the gate can't fire on okx/gate alone.
3. **Confirm FIX 2 m5v** — is `markov_regime_w20_5m_va` actually computed now, or still None?
4. Commit the working-tree fixes (currently uncommitted — risk of loss on a bad restart).
5. Re-verify all in 24-48h (2h is too short for the low-rate cells).

## END
