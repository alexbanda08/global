# 03 — DIRECTIONAL hold-to-resolution research line — RETRO AUDIT (2026-06-10)

Scope: the directional (buy-and-hold-to-chainlink-resolution) up-down line. V1→V5 momo/sniper, Cyclops S7,
F7 RSI, momo_v2/HOLD/markov, the GA-evolved sniper v6/v7/v8 families (eth-5m hurst/cloud/bb; btc-15m
ema/trstack off600 down), kelly, sol_rf, fade_momo, ToD/session gates, the 215-sleeve shadow fleet
(net −$25.4k). EXCLUDES the intra-window EXIT-SCALP execution line (separate audit) except where it
contrasts the directional findings.

Verdict up front: **across the entire directional line there is no proven predictive edge that survives a
deflated test.** What survives is small, fragile, and partly an artifact of the entry-price band (cheap
contrarian zone), the ETH-5m directional stack (real but decaying IS→OOS→live), and execution-side scalp
(a different line). The fleet leaked −$25.4k mostly on −EV strategies left firing, not on bugs.

---

## 1. Timeline of the line

| Date | Milestone | Key outcome |
|---|---|---|
| Apr (pre) | V1→V5 momo/sniper evolution; Cyclops S7; F7 RSI sleeves | Cyclops S7 X1 reached G1+G3+G4 PASS (BTC-5m only, n=36). The momo line never cleanly profitable. |
| 2026-05-10 | **`ws_s` convention bug found** (`SESSION_HANDOFF_2026_05_10`) | The single biggest methodological error of the line. Backtests anchored on `slot_start` (in-window momentum) instead of `ws_s = slot_start − window_s` (pre-window). Inflated hit rate 25–40 pp (~85% bt vs ~50% live). Invalidated ~6 momo reports. Canonical loader + helpers added to lock the convention. |
| 2026-05-20 | **Walk-forward audit** (`WALKFORWARD_AUDIT_2026_05_20`) | First real rigor pass. 18+ configs, top-1 reported → checked via 4-fold WF. Lifts held (same config wins 4/4 folds), but in-sample $10.2k/day revised down to $8.3k/day OOS, ~$4.2k/day after live haircut. Engine audited causal. |
| 2026-05-21 | **V2 production bug CONFIRMED** (`CLEAN_BACKTEST_V2_BUG_CONFIRMED`) | Clean spec recompute vs production: eth_5m_v2 47% spec WR → **4.76% live**; btc_15m_v2 53% → **17.65%**. An inversion bug in production `_build_signal_aux`. 6 v2+f7 sleeves disabled. |
| 2026-05-22 | momo_v2/HOLD/markov + F7 anchor (`HANDOFF_2026_05_22`) | F7 RSI anchor corrected 3× → settled on `ws_s`. 11-sleeve gated shadow BT: 4 PASS, 4 NEGATIVE. 5 deploy sleeves at "production parity." |
| 2026-05-30 → 06-01 | **Fleet optimization sprint** (21→215 sleeves; SLEEVE_OPTIMIZATION, FULLPERIOD_*, KELLY/SOLRF, EMA_DOWN, DEPLOY_PORTFOLIO) | The core of this audit. Gate sweeps, full-period OOS persistence, hedge/exit grids, ema_down band. **All ToD/session gates fail OOS.** ETH-5m stack persists. 2 KILLs (imb5 lookahead). ema_down band [0.15,0.93]. |
| 2026-06-02 | **215-sleeve edge analysis** (`SHADOW_SLEEVE_EDGE_ANALYSIS`) | Fleet net −$25.4k. Only 4 sleeves t≥2 (+$342 total); 25 bleeders (−$19.8k). The "no proven winner" honest verdict. |
| 2026-06-03 | LAGV2 always-UP bug fixed; momo_v2 live↔shadow parity work | lagv2 fired ~100% UP regardless of signal (900/901 BTC-5m UP). |
| 2026-06-04 | **ml4t/DSR toolkit installed** (`HANDOFF_2026_06_04_ML4T_DSR`) | First time deflation (DSR/PBO/CPCV) is a first-class tool. Formal proof: only real edge is the EXIT-SCALP; all predictive directional families efficient/noise at scale. |
| 2026-06-08 | **BT-vs-live + parity forensics** (`SLEEVE_BT_VS_LIVE_AUDIT`, `V10_SHADOW_VS_LIVE_PARITY`, `SHADOW_BLEEDERS_7D`, RS-panel+DSR) | Tiered every sleeve by valid-BT status. V10 ETH shadow +$62 collapses to +$1.1 live (un-fillable fires). RS-rank: DSR 0.24 → monitor, not edge. |

---

## 2. Errors found (severity-ranked, with what was invalidated)

### CRITICAL — C1: the `ws_s` vs `slot_start` lookahead anchor (caught 2026-05-10)
Every momo/sniper backtest before this date anchored the 2-min return on `slot_start` (FIRST 2 min INSIDE
the slot) instead of `ws_s = slot_start − window_s` (the PREVIOUS slot's start = pre-window momentum).
In-window momentum is ~85% predictive by construction; pre-window is ~50%. **Inflation 25–40 pp.**
Confirmed by exact math against a production-logged `ret_2m` (eth-updown-5m-1778342700: buggy +0.001260
vs production −0.000846 exact match at ws_s−300).
**Invalidated:** `MOMO_V1V2_CANONICAL` (v1 85.5%, v2 67.5% — both inflated), `MOMO_COINBASE_LEAD` (+75%
hit), `MOMO_COINBASE_ADDALPHA`, `MOMO_CHAINLINK_ONLY` (magnitude), `EXTENDED_BACKTEST_ROBUSTNESS`, and the
"residual 5m gap" diagnosis in `MOMO_FEED_LAG_INVESTIGATION`. Qualitative verdicts (momo not profitable)
survived because the strategy was ~28 pp below breakeven anyway, but all magnitudes had to be re-derived.
Fix: locked in `load.py` (`slug_to_ws_s`, `add_ws_s`, `ret_2m_at_ws`, `fire_us = (ws_s+120)*1e6`).

### CRITICAL — C2: V2 production inversion bug (caught 2026-05-21)
Production `eth_5m_v2`/`btc_15m_v2` produced WR FAR BELOW the spec's own 47%/53% (4.76% / 17.65%). A
correctly-implemented filter on a 47% universe cannot random-sample to 5% — the comparison was actively
anti-correlated with outcome (sign flip / wrong-anchor / cross-cell aux cache collision in
`_build_signal_aux`). **Invalidated:** all 6 eth_5m_v2 / btc_15m_v2 +f7 production sleeves; disabled.
This is the live mirror of C1 — the same anchor/aux family of bug, in production code this time.

### HIGH — C3: imb5 GA-search look-ahead (the "2 KILL originals", caught 2026-05-30/31; re-confirmed 06-08)
`btc_5m_q_parent15mslope_ts_imb5_v8` and the wider `imb5` cell family: the GA `g_imb5_strong_with` gate
was evaluated with **post-fire book info**. Original projection +$6.20/tr. Causal full-period
reconstruction → **51% WR (coin-flip)**, live −$930 (n=1232). The second KILL `btc_5m_ts_mpskew_any_off30`
(off30 too late, crowd priced) −$93. **06-08 escalation:** "no valid backtest exists for ANY imb5 sleeve"
→ also kills `btc_5m_l_1hrf_imb5_ribbon_v8` / `_rf_v8`. **Invalidated:** every imb5 V8 cell's positive GA
projection.

### HIGH — C4: LAGV2 always-UP signal bug (caught 2026-06-03)
`poly_fast_taker_lagv2_*` fired ~100% UP regardless of the oracle/return signal (900/901 BTC-5m fires UP).
Live "89–98% WR" was a directional artifact during an UP regime, not edge; ≈ −$750 7-day bleed.
Compounded by C5. **Invalidated:** all pre-Jun-3 lagv2 live samples; any conclusion drawn from them.

### HIGH — C5: RF UP-bias gate mismatch in BTC-5m V8 flow sleeves (caught 2026-06-08)
Live gate-1 on `l_1hrf_imb5_rf_v8` / `_ribbon_v8` used `g_grandparent_trend_with` instead of the spec's
`g_1h_rf_with`; and the Range Filter `rf_dir` itself holds +1 for many bars after a peak → voted UP on 77%
of fires during June's BTC downtrend. Systematic wrong-direction betting. Persisted unfixed since
2026-05-29. **Invalidated:** the live performance of both high-volume BTC-5m flow sleeves (−$611 t=−4.7,
−$310 t=−2.8 in the 06-02 fleet table — these were read as "priced-in trap" but were partly this bug).

### MEDIUM — C6: ToD/session gates fit on the live window, judged on the live window (caught 06-01)
`keep_EU` (kelly), `drop_US` (sol_rf, ETH), `vsum≤1.30` — all looked great in 3–5 day live windows, all
FAILED the full-period (Apr24–May26) OOS test. kelly EU: live +$2,272 → both-half holdout H1 −$0.08/tr
(entire effect is week-21 concentration, not time-of-day). sol_rf drop_US: 59.8%→59.9% WR (no WR lift, only
exposure cut), still net-negative OOS. **Invalidated:** every session-gate "win" reported off a single live
window. (This is the recurring-decay pattern — see §3.)

### MEDIUM — C7: `btc_5m_parent15m_notrang` broken reconstruction (caught 06-01, never fixed)
The `parent_15m_not_ranging` selectivity gate is not a column in the enriched panel → 2-gate proxy
over-fires **28×** (4,926 vs 176 live) and collapses to raw momentum (50.6% WR). Its full-period verdict
AND its +$45 HEDGE_LATE finding are **unconfirmed** (live n=176 stands alone). Listed as an open gap; never
closed in this line.

### LOW — C8: in-sample new-gate sweeps on the GA training panel
The v6/v7/v8 universe panels ARE the GA training set. Sweeping new gates (`g_sms_no_liquidity_above`,
`g_mp_skew_with`, band-narrow) on those panels is IN-SAMPLE — flagged correctly in the reports as "confirm
live before deploy," but several were nonetheless specced into V10 sleeves before live confirmation. Not
invalidated, but not validated either.

### LOW — C9: shadow PnL overstated by un-fillable fires (caught 06-08)
Shadow uses a same-token bid-ask spread filter; live uses the cross-token vwap-sum spread gate. V10 ETH
shadow +$62/+$0.218/tr collapses to live +$1.1/+$0.010/tr — 56% of shadow's extra fires die on the live
wide-book gate (correctly: they're not executable), 44% on per-host feed divergence. **Every shadow-only
$/tr number in the fleet is an upper bound**, not a live expectation.

---

## 3. The recurring-decay diagnosis (Audit Q1)

**Root pattern: selection-and-judgment on the same short live window, with the GA panel used circularly.**

Two distinct mechanisms, both present:

1. **Gates selected ON the live window, then "validated" by it.** `keep_EU`/`drop_US`/`vsum` were
   discovered by sweeping logged features over the 3–5 day live shadow window, then the same window's PnL
   was cited as confirmation. The first genuinely OOS test (full-period Apr24–May26 panel) killed all of
   them. Named instances: kelly `keep_EU` (week-21 artifact, H1 −$0.08/tr); sol_rf `drop_US` (no WR lift);
   ETH `drop_US`+`vsum` (hurt full period). This is C6.

2. **The GA training panel reused as "validation" for base sleeves.** The v6/v7/v8 base sleeves were
   *selected* on the Apr24–May26 universe panels. `FULLPERIOD_PERSISTENCE` explicitly flags this: "Base-
   sleeve universe numbers = IN-SAMPLE (upper bound, not proof)." So the only true OOS for the base sleeves
   was the live window — which is exactly the window the gates were fit on. The two circularities compound:
   base sleeve is IS on the panel, gate is IS on the live window, leaving **no clean OOS** for the
   gate-on-sleeve combination. The reports caught this for the gates (good) but several base sleeves were
   still deployed on panel numbers (C8).

3. **The honest correction came late.** The phrase "live ≫ backtest is overfit-decay" in
   `HANDOFF_2026_06_01` is precisely backwards-framed: it was read as "the engine is faithful, live is just
   lower." The truer reading (confirmed 06-08) is that the **shadow/backtest numbers were inflated by
   un-fillable fires and IS gates** — live is the truth and it is ~breakeven. V10: shadow +$62 → live +$1.1.

**Was the GA training set ever reused as validation? Yes** — for base-sleeve persistence claims, and this
is the larger of the two leaks because it was less obviously circular than the gate-on-live-window case.

---

## 4. Lookahead / wrong-anchor bug history (Audit Q2)

| ID | Bug | Caught | Severity | Invalidated |
|---|---|---|---|---|
| C1 | `ws_s` = `slot_start` (should be `slot_start−window_s`) | 2026-05-10 | Critical | 6 momo reports; 25–40 pp hit-rate inflation |
| C2 | V2 production inversion (`_build_signal_aux`) | 2026-05-21 | Critical | 6 eth_5m_v2/btc_15m_v2 sleeves (47%→5% WR) |
| C3 | imb5 GA gate on post-fire book | 2026-05-30; 06-08 | High | 2 KILL sleeves + ALL imb5 V8 cells (+$6.20/tr projection was fake) |
| C4 | LAGV2 always-UP signal | 2026-06-03 | High | all pre-Jun-3 lagv2 live samples (89–98% WR was UP-regime artifact) |
| C5 | RF `rf_dir` UP-bias + wrong gate (`grandparent` vs `1h_rf`) | 2026-06-08 | High | both BTC-5m flow sleeves' live results |
| (F7) | F7 RSI anchor (corrected 3×, settled on `ws_s`, 94.67% match) | 2026-05-21/22 | Med | earlier F7 anchor verifications (`_match_live_f7.py` v1 was version-unaware) |

Engine itself audited clean (`WALKFORWARD_AUDIT` §5): `asof_strict` causal (`searchsorted(side="right")−1`),
outcome truth only read at finalize, L25 streamed in `timestamp_us` order. **The lookahead was never in the
simulator — it was always in the SIGNAL CONSTRUCTION (anchor) or the GATE SEARCH (post-fire book) or
PRODUCTION code (inversion / direction bug).** That is the through-line: 5 of 6 bugs are signal/gate/prod,
not engine.

---

## 5. Multiple testing & deflation (Audit Q3)

**Approximate count of configs evaluated across the fleet era:**
- 215 live shadow sleeves (the fleet).
- GA universes: 4 asset/tf cells × thousands of GA candidates each (v6/v7/v8 evolutionary search over
  indicator/gate combos) — the v8 "imb5 search," "hurst search," "trstack search," etc. Easily **10³–10⁴**
  evaluated configs per cell, only the argmax surfaced as a named sleeve.
- Gate sweeps: 21 sleeves × ~7 logged features × thresholds + external-feature gates → several hundred
  gate-tests; plus exit/hedge grids (SL/TP/trailing/HEDGE_LATE matrices).
- 06-04 ML sprint (adjacent but same multiple-testing universe): 4.8M indicator combos, 387k scalp
  selectors, 415 GPU architectures.

**Conservative total directional search space: thousands of named-or-evaluated configs, top handful
deployed.** With single-fire SD ≈ $25, even genuine +$1–4/tr edges sit at t≈1–2 over 5–22 day windows —
exactly the regime where multiple-testing produces false positives.

**Was deflation applied before deploys? NO — only after.** The chronology is unambiguous:
- Pre-06-04: the rigor was walk-forward (`WALKFORWARD_AUDIT`, good but not deflation), both-half holdout,
  and t-stat thresholds (t≥2). **No DSR / PBO / Bonferroni** on the GA search or the fleet. The 06-01 fleet
  was deployed/judged on raw t-stats and single-window live PnL.
- 06-04: ml4t `deflated_sharpe_ratio` / PBO(CSCV) / CPCV installed for the first time — "this is how we
  judge everything NOW (replaces hand-rolled permutation null / lockbox / Bonferroni)."
- 06-08: RS-panel strategy run through DSR → ungated Sharpe 1.52 but **DSR 0.24** (N=180); pre-registered
  N=1 gate DSR 0.94 (still misses). Same death the 387k scalp selectors got.

**Currently-deployed directional sleeves that NEVER passed a deflated test:** effectively **all of them.**
The 4 "edge" sleeves (ema_down/Kalshi, eth_5m_l_ema50_hurst, 2× trstack), the ETH-5m base family, kelly
(fe>1000), ema_down band — none were run through DSR/PBO before deploy. They passed t≥2 on a single window
or full-period persistence on the (in-sample) panel. Given the ~10³–10⁴ search space, a DSR with realistic
`variance_trials` would very likely deflate the t≈2 sleeves toward insignificance (precisely what happened
to the 387k scalp selectors and the RS panel). **No directional sleeve has a surviving deflated test as of
this audit.**

---

## 6. The 4 EDGE sleeves (t≥2) — robustness reality check (Audit Q4)

| sleeve | n | WR | vwap | $/tr | t | grade |
|---|--:|--:|--:|--:|--:|:--|
| `kalshi_..._btc_15m_ema50_ema800_off600_down` | 108 | 84.3% | 0.74 | +1.33 | 2.0 | C+ |
| `poly_..._eth_5m_l_ema50_hurst_grandparent_v8` | 183 | 71.0% | 0.63 | +0.66 | 2.2 | B− |
| `poly_..._btc_15m_ts_trstack_off600_down` | 37 | 89.2% | 0.76 | +1.29 | 2.1 | C |
| `poly_..._btc_15m_mpskew_trstack_off600_down` | 50 | 94.0% | 0.84 | +0.61 | 2.4 | C |

- **ema50_ema800_off600_down (Kalshi):** faithful spec (verified 185 fires, 100% DOWN, off600). Total only
  +$144. Its deep-dive (`EMA_DOWN_DEEPDIVE`) found the "cheap-entry edge" is **mostly luck at the extremes**
  — the real signal is the [0.15,0.93] band (contrarian zone), not the trend continuation per se. Conceptually
  this is an entry-price band finding, not a directional-prediction finding. **C+** (faithful + Kalshi-confirmed,
  but tiny total and the mechanism is band not trend).
- **eth_5m_l_ema50_hurst_grandparent_v8:** the strongest. WR decays cleanly IS 82% → OOS 73% → live 67%
  (expected, not a collapse). 06-08 live t=1.97, n=626, "hurst gate is load-bearing." BUT base sleeve was
  selected on the panel (IS), and V10 shadow +$62 → **live +$1.1** (the fire-count / fillability gap). So
  the *signal* is real-ish; the *deployable $/tr* is ~breakeven live. **B−** — best of the four, real
  directional content, but live $/tr ≈ 0 after the fillability haircut.
- **2× trstack (ts_trstack n=37, mpskew_trstack n=50):** very high WR (89–94%) but at vwap 0.76–0.84 (you
  pay for the favorite), tiny totals (+$48, +$31), and **n=37/50 — both underpowered**. All three off600/DOWN
  sleeves are conceptually the same bet (DOWN trend-continuation, late offset); the DEPLOY_PORTFOLIO doc
  itself flags them as "conceptually similar." Not independent confirmations. No valid OOS BT beyond the
  panel. **C** — could be the same DOWN-trend factor as ema_down, sliced three ways.

**Common thread / honest read:** the "4 edges" are really **2 factors** — (a) ETH-5m directional stack
(hurst-gated), and (b) BTC-15m DOWN trend-continuation at a late offset — each carrying t≈2 on small n,
neither deflated, the ETH one breakeven live after fillability. The reports' own verdict — "no proven
winner is the honest verdict" — is correct.

---

## 7. The ToD-gate paradox: directional fails, scalp passes (Audit Q5)

**Not a contradiction; it's a different mechanism, and it is defensible — with one caveat.**

- **Directional ToD gates (`keep_EU`/`drop_US`/`vsum`) failed OOS because they were pure timing overlays
  fit to a 3–5 day window with no causal mechanism** for *direction prediction*. kelly EU was 100% week-21
  concentration; sol_rf drop_US gave zero WR lift. Timing doesn't predict which way BTC moves.
- **The scalp TOD gate (exclude {12,17} UTC) passed OOS on a clean disjoint window (Mar30–Apr21, 5 coins,
  gated CI>0)** because it gates an **execution/microstructure** effect, not a direction. The scalp edge is
  "buy the lag-taker token cheap, sell on book at +60s" — a liquidity/latency phenomenon that plausibly has
  a real intraday seasonality (US-hours book behavior). It was validated on a window **physically disjoint**
  from the fit window, which the directional gates never were.

**Caveat / flag:** the scalp TOD gate ({12,17} exclude) is itself a selected pair of hours out of 24 — a
24-hour ToD sweep has the same multiple-testing exposure that killed the directional gates. It passed a
disjoint-window OOS, which is stronger than anything the directional gates had, but it has **not** been run
through DSR with the ToD search counted as trials. **Recommendation: re-run the scalp TOD gate through DSR
treating the 24-hour sweep as `n_trials`** before treating "exclude {12,17}" as load-bearing. Given the
directional ToD experience, treat any hour-of-day gate as guilty until deflation-proven. **Mildly
suspicious, not yet falsified.**

---

## 8. Preventable fraction of the −$25.4k drag (Audit Q6)

Decomposition of the fleet drag and what the later rigor rules would have caught at the start:

| Drag source | ≈ $ | Preventable by early rigor? |
|---|--:|---|
| 79 INACTIVE sleeves (stopped, never disabled) | −$7,496 | **Yes** — lifecycle rule (disable on inactivity) is config, not research. |
| 25 BLEEDERS (−EV strategies left firing) | −$19,806 | **Mostly** — most were −EV-by-design (priced-in trap at vwap 0.74–0.84, high WR/−$/tr) that a **break-even-vs-vwap** pre-deploy check + DSR would have refused to deploy. |
| imb5 lookahead sleeves (C3) | included above | **Yes** — a "no post-fire book in gate search" rule eliminates these before deploy. |
| LAGV2 / RF UP-bias (C4/C5) | ≈ −$1,500 (7d-rate family) | **Yes** — a spec-vs-live direction-balance check (is the sleeve ~50/50 UP/DOWN?) catches a 900/901-UP sleeve in one day. |
| momo/momo_v2 family | ≈ −$2,600 (7d) | **Partly** — C1/C2 anchor bugs; the corrected-anchor BT would have shown ~50% WR and refused deploy. |
| LOW_N + FLAT noise | −$554 + ~0 | No — these are just variance. |

**Estimate: ~70–85% of the −$25.4k was preventable** by rules that *already existed by 06-08 but were not
applied at deploy time*:
1. **Don't deploy on a single live window** (kills the ToD-gate false positives).
2. **No post-fire data in any gate/GA search** (kills imb5).
3. **Break-even-vs-entry-vwap pre-deploy gate** (high-WR/high-vwap = priced-in trap → −EV; kills the
   −$19.8k bleeder bucket, which is the dominant term).
4. **Direction-balance sanity check** (kills LAGV2/RF UP-bias).
5. **Lifecycle auto-disable on inactivity** (kills the −$7.5k inactive bucket).
6. **DSR before deploy, counting the GA/gate search as trials** (would have refused most t≈2 sleeves).

The irreducible drag is the LOW_N/FLAT noise (~−$0.5k) and the genuine cost of running a few real-but-tiny
edges (ema/hurst/trstack net ≈ +$0.3k, roughly washing). **The drag was a process failure (deploy-then-
audit), not a research-capability failure** — the team *found* every bug, just after capital had bled.

---

## 9. What was done RIGHT

- **`ws_s` convention was nailed and locked in code** (helpers in `load.py`, source-verified against the
  production controller, 94.67% F7 match). After 05-10 the anchor stopped being a source of bugs.
- **The engine was independently audited for lookahead and found clean** (`WALKFORWARD_AUDIT` §5) — causal
  `asof_strict`, ordered streaming, outcome read only at finalize. The team correctly localized every bug to
  signal/gate/production, not the simulator.
- **Walk-forward (4-fold, same-config-wins-all-folds) and both-half holdout** were applied consistently from
  05-20 onward, and they *did* catch the ToD-gate overfit and the in-sample trap — the reports explicitly
  name the GA panel as in-sample.
- **Production bugs were caught by clean spec-recompute vs production logs** (C2, C4, C5) — the "GROUND-TRUTH
  RULE" (verify against actual event fields / live wallet) repeatedly overturned mid-session conclusions and
  is the right discipline.
- **The honest "no proven winner" verdict** (06-02) and the late but decisive **DSR adoption** (06-04) show
  the line self-corrected toward rigor. The RS-panel DSR death (06-08) proves the new layer actually bites.
- **Fee model corrected to the operator-confirmed 0.07 winner-only curve** (06-03), re-baselining prior
  legacy-2% numbers.

---

## 10. Surviving edges + evidence-quality grade

| Edge | What it is | Grade | Why |
|---|---|:--:|---|
| **ETH-5m directional stack (l_ema50_hurst, cloud_vwap_hurstmp)** | hurst-gated 5m momentum, hold to resolution | **B−** | Real directional content; WR decays cleanly IS→OOS→live (82→73→67%); live t≈2 at large n. BUT base selected on panel (IS), live $/tr ≈ breakeven after fillability haircut, never deflated. Best in the line. |
| **BTC-15m DOWN trend-continuation (ema50_ema800_off600_down + trstack twins)** | late-offset DOWN bet when EMA stack bearish | **C+** | Faithful spec, Kalshi-confirmed, but tiny totals, the real driver is the [0.15,0.93] entry band not the trend, the 3 trstack variants are the same factor sliced thin (n=37/50), never deflated. |
| **`entry_vwap ≤ 0.70` overlay (marginal sleeves only)** | don't overpay the favorite | **B** | The one gate that genuinely generalized OOS (+0.5–0.8/tr in the untouched period). Mechanistic (priced-in trap), not timing. Apply only to marginal sleeves (hurts Calmar on winners). |
| **ema_down band [0.15,0.93]** | contrarian entry-price band | **C+** | +32% total full-period; an entry-price effect, not prediction; in-sample band-fit, needs the same band-map on other DOWN sleeves to confirm it's not curve-fit. |
| Cyclops S7 X1 (BTC-5m composite) | sleeve-coherence trigger | **C** | G1+G3+G4 PASS but n=36, BTC-5m only, does not generalize, pre-rigor-era. |
| kelly (fair_edge_bp>1000, ½-Kelly) | conviction-tier sizing | **C−** | Edge is real but week-21-concentrated; EU gate fails holdout; panel May 1–21 only. |

No directional edge reaches **A**. (The only A-grade edge in the whole project is the intra-window
EXIT-SCALP — a different, execution line.)

---

## 11. Lessons as rules

1. **Anchor every poly-updown signal on `ws_s = slot_start − window_s`. Never `slot_start`.** Verify any
   new harness against a production-logged `ret_2m` before trusting a single number. (C1)
2. **No post-fire / forward-looking data in any gate or GA fitness function.** If a gate reads the book
   after `fire_us`, its projection is fiction. Audit every GA-evolved cell for this. (C3)
3. **Selection and validation must use disjoint windows.** A gate found on the live window is NOT validated
   by that window. The GA training panel is IN-SAMPLE for the sleeves it bred. Reserve a physically
   disjoint OOS window (this is exactly why the scalp's Mar30–Apr21 test is credible and the directional
   ToD gates are not). (C6, §3)
4. **Run DSR/PBO BEFORE deploy, counting the full search (GA candidates + gate sweep + ToD hours) as
   trials.** A raw t≥2 on a single window is a coin-flip given 10³–10⁴ configs. (Q3)
5. **Pre-deploy break-even-vs-entry-vwap check.** High WR at vwap 0.74–0.84 is the priced-in trap → −EV.
   This single check would have refused the −$19.8k bleeder bucket. (Q6)
6. **Direction-balance sanity check at deploy and daily.** A sleeve firing 900/901 one direction is a bug,
   not an edge — catch it in a day, not a month. (C4/C5)
7. **Lifecycle auto-disable on inactivity / on rolling-CI breach.** −$7.5k bled from sleeves nobody turned
   off. Deploy-then-audit is the core process failure; make disable automatic. (Q6)
8. **Shadow $/tr is an upper bound, not a live expectation.** Replace the shadow same-token spread filter
   with the live cross-token vwap-sum gate before citing any shadow PnL. Trust the live wallet. (C9)
9. **Timing gates are guilty until deflation-proven.** Every ToD/session gate in the directional line died
   OOS; treat the scalp's {12,17} exclude the same way until it clears a trial-counted DSR. (Q5)
10. **Verify against actual event fields / live wallet, not spec or shadow** (GROUND-TRUTH RULE) — it
    overturned multiple mid-session conclusions and caught all 3 production bugs.
