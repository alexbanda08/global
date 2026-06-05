# Phase-A re-validation — 6 cross-feature survivors through engine_v2 — 2026-06-03

Full-window fires (Apr24→May25), native 10Hz L25, 85ms latency, min_book_events=25, spread_filter=0.02. Hold-to-resolution directional bet.

Fees: **win07** = 0.07×p×(1−p) winner-only (production truth, CLAUDE.md). **livemimic** = 0.07 both-leg (conservative). **legacy** = 2%-on-profit (original study).

| survivor | n_fire | n_fill | fill% | WR | vwap | legacy $/tr | win07 $/tr | win07 t | win07 CI | livemimic $/tr | LM CI | orig lockbox | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| XF-J  BTC 5m  @180 BOTH | 450 | 371 | 0.824 | 84.4 | 0.822 | +1.486 | +1.38 | 1.56 | [-0.283,+3.17] | +1.284 | [-0.365,+3.119] | n=41 87.8% +$6.98 | 🔴 DEAD |
| DISAGR SOL 5m @210 DN | 264 | 128 | 0.485 | 95.3 | 0.874 | +3.791 | +3.696 | 2.84 | [+1.42,+6.487] | +3.672 | [+1.419,+6.389] | n=35 100.0% +$6.54 | ✅ SURVIVES (both fees) |
| XF-I  SOL 15m @240 UP | 408 | 100 | 0.245 | 66.0 | 0.674 | -0.539 | -0.679 | -0.32 | [-4.697,+3.639] | -0.948 | [-5.129,+3.33] | n=56 78.6% +$6.31 | 🔴 DEAD |
| XF-I  SOL 15m @240 BOTH | 690 | 168 | 0.243 | 69.0 | 0.688 | -0.592 | -0.741 | -0.5 | [-3.641,+2.204] | -0.993 | [-3.896,+2.065] | n=105 72.4% +$4.09 | 🔴 DEAD |
| XF-I  BTC 5m  @150 UP | 1190 | 1082 | 0.909 | 72.7 | 0.717 | +0.307 | +0.169 | 0.26 | [-1.066,+1.459] | -0.044 | [-1.294,+1.309] | n=198 76.8% +$3.56 | 🔴 DEAD |
| XF-I  BTC 5m  @150 BOTH | 2503 | 2257 | 0.902 | 72.0 | 0.715 | +0.152 | +0.013 | 0.03 | [-0.822,+0.918] | -0.201 | [-1.065,+0.675] | n=419 74.0% +$2.32 | 🔴 DEAD |

## Notes
- n_fire here = FULL-window fires (vs the original 4-day lockbox n). engine_v2 test gets max power.
- A survivor must clear win07 CI>0. ✅ also clears the harsh both-leg fee.
- The original lockbox $/tr used LegacyConfig (2%-on-profit) + 1Hz books → compare the `legacy $/tr` column to `orig lockbox` to isolate the 10Hz/latency/fill effect from the fee effect.

## VERDICT — 1 of 6 survives production fills (with caveats); the headline high-n ones are DEAD

**Bottom line: 5/6 die when re-filled through engine_v2. The original lockbox numbers were inflated by
(a) the 2%-on-profit fee and (b) 1Hz-subsampled book fills — exactly the two artifacts CLAUDE.md warns about.**

1. **DISAGR-HAWKES SOL 5m @210 DN — ✅ the only survivor.** win07 +$3.70/tr, t=2.84, bootstrap CI
   [+1.42, +6.49] EXCLUDES 0, and survives even the harsh both-leg fee. **BUT three caveats before any
   capital:**
   - **Fill rate only 48.5%** (128/264). Half the signal's fires can't be filled at $25 within a 2¢ spread on
     thin SOL-5m books. **Fill-selection bias is live:** if the 52% unfillable fires are disproportionately
     losers OR winners, the realized edge shifts. Must check the won-rate of the *unfilled* set.
   - **vwap 0.874, WR 95.3%** — deep-favorite. Breakeven WR ≈87.4%; it clears by ~8pp, so the edge is real
     *if the 95.3% holds out-of-sample*, but deep-favorite WR is fragile (one bad streak erases many wins).
   - **n=128** filled — still thin. Needs forward accumulation.

2. **XF-J BTC 5m @180 BOTH — 🟡 promising but underpowered (not dead).** win07 +$1.38/tr but t=1.56,
   CI [−0.28, +3.17] includes 0. vwap 0.82, WR 84.4% (breakeven ~82%, ~2pp surplus). Watchlist; accumulate.

3. **XF-I family (BTC 5m @150 n=2257/1082, SOL 15m @240) — 🔴 DEAD.** These were the *highest-confidence*
   survivors by lockbox-n (419/198), advertised +$2.32–3.56/tr. Under production fills they collapse to
   **+$0.01 to +$0.17/tr, t≈0, CI straddling 0.** The SOL-15m cells also have a brutal **24% fill rate**.
   This is the priced-in-trap + fee-overstatement pattern: high WR (72%), high vwap (0.715), ~zero $/tr.

### What this means for the ML plan
- **Do NOT build the ML phase on the XF-I cells.** They are fee/fill artifacts.
- **DISAGR-HAWKES (mp_skew<0 ∧ imb5_diff>0 ∧ hawkes_imb<−0.2)** is the one feature combination that carried
  real $/tr through production fills → it is a **legitimate feature for the P1 meta-labeler** and a candidate
  **shadow sleeve** (SOL 5m DN), pending the fill-selection check + forward fires.
- **Fill rate is now a first-class feature/gate.** Any ML signal must be scored on *fillable* fires only, and
  fill rate itself predicts live tradability. The 1Hz study completely hid this.

### Immediate follow-ups
1. Check won-rate of the **unfilled** DISAGR-HAWKES fires (is the 48% fill rate selection-biased?).
2. If clean → stand up `shadow_disagr_hawkes_sol_5m_dn` as a paper sleeve; begin ≥200-fire forward accrual.
3. Feed `mp_skew`, `imb5_diff`, `hawkes_lambda_imbalance`, **and fill-rate/spread** into the P1 feature store.

## FILL-SELECTION CHECK (follow-up #1) — DISAGR-HAWKES is NOT selection-biased; the filter helps

Ran `fill_selection_check_2026_06_03.py` on all 264 DN fires, classifying each fire's fill outcome + reason:

| fill outcome | n | WR | med spread | med book events |
|---|--:|--:|--:|--:|
| **FILLED** | 128 | **95.3%** | 0.010 | 52 |
| wide_spread (>2¢, rejected) | 112 | 73.2% | 0.035 | 55 |
| few_book_events (<25) | 24 | 87.5% | — | 21 |

- **FILLED WR 95.3% vs UNFILLED WR 75.7%, t=4.73, p<0.001.** The unfilled fires **WIN LESS**, not more.
- **Interpretation: the 2¢ spread filter is a benign (beneficial) quality gate** — it rejects the
  wide-spread fires (73% WR, and at 3.5¢ spread the entry vwap would be even richer → likely unprofitable
  anyway) and **keeps the tight-book winners**. The 48% fill rate is NOT a mirage that drops winners; the
  fillable subset is the *better* subset. ✅ This removes the main caveat.
- **Remaining caveats unchanged:** deep-favorite vwap (0.87) → fragile to a bad streak; n=128 filled; this is
  the rule-discovery window (Apr24→May25), so forward OOS is still required.

### Updated verdict for DISAGR-HAWKES SOL 5m DN
**Graduates to (a) a shadow-sleeve candidate and (b) a confirmed feature for the P1 meta-labeler.** It is the
single signal from the entire cross-feature study that survives production fills AND a clean fill-selection
test. Deploy as `shadow_disagr_hawkes_sol_5m_dn` (paper, $25, 2¢ spread gate) and accumulate ≥200 forward
fires + bootstrap CI>0 before any real capital — the same graduation bar as the exit-scalp.