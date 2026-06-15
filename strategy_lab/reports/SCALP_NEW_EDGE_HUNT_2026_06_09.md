# Scalp Deep-Dive — New-Edge Hunt (mid-window / FVG / cross-asset / regime / trailing / arb) — 2026-06-09

> ## ☀️ MORNING SUMMARY (read first)
> Ran **7 pre-registered trials** overnight (3 in the day session + 4 autonomous). **Zero new deployable edges.**
> The open exit-scalp is the only edge and it is **fully optimized already** (entry +5 s, `delta_bps` sizer with
> δ≥5 the high-quality band, exit +60 s, `entry_vwap<0.55`, exclude dead hours). Everything else died under proper
> controls:
> | # | trial | verdict |
> |---|---|---|
> | 1 | mid-window naive re-fire | DEAD (open-only) |
> | 2 | **fair-value-gap (principled mid-window)** | DEAD — anti-signal mid-window |
> | 3 | cross-asset lead-lag (BTC→ETH/SOL) | DEAD — paired diff ≈0 (95 % correlated) |
> | 4 | regime gates (vol/trend) | nothing beats `delta_bps` |
> | 5 | **tick-level trailing exit** | DEAD — fixed +60 beats whole trailing family; peak untradeable |
> | 6 | entry-offset + delta-band knobs | reconfirm only (+5 s, δ≥5) — no improvement |
> | 7 | same-venue two-sided arb | DEAD — book overround ~1.02, sub-1 cases are dust |
> | 7b| low-vol gate (proper OOS) | DEAD as a gate — fails the coin-split, *hurts* BTC/ETH |
>
> **Takeaway:** the existing-data scalp space is efficient. **Stop researching the scalp; the bottleneck is
> operational** (ship disable-**TP-only** [TP@0.65 is the non-edge; the **stop@(fill−0.10) is validated edge,
> +0.88/tr SIG — KEEP it**], the maker-exit A/B, and accumulate ≥200 live forward fires — the real
> graduation gate). **New edges now require NEW data, not more backtesting:** (a) verify **Kalshi ask-depth** to
> unlock the deep-dip Poly×Kalshi arb (the one open *positive* lead, +2.7–6.6 ¢/set); (b) the Poly **CLOB WS trade
> tape** for slug-selection (don't have it); (c) **futures funding/OI regime** once `cex_futures` accrues >1 window
> (only May30+ today). Details per trial below.

---

# Scalp Deep-Dive — New-Edge Hunt (mid-window / FVG / cross-asset / regime) — 2026-06-09

**Operator directive:** fresh view of the scalp — find a **different gate**, a **different entry type**, and a
**mid-window / 1-min-inside** scalp on BTC/ETH/SOL up-down 5m+15m. DSR/CPCV/walk-forward/plateau from the start.

**One line:** Ran 3 substantive new trials + reconfirmed a 4th. **All four died under proper controls.** The
intra-window edge is **structurally open-only (~first 5–35 s)**: every generalization away from the window-open
lag-taker (mid-window re-fire, a principled fair-value-gap signal, cross-asset lead-lag, regime gates) is flat or an
**anti-signal**. The deployed open scalp (`entry_vwap<0.55`, lag-taker, sell +60 s) is reconfirmed and remains the
only edge. **No new deployable strategy. Stop hunting mid-window/cross-asset — both are now closed with evidence.**

---

## 0. Context — what was already exhausted (don't re-run)
Deployed edge = **window-open exit-scalp**: buy the lag-taker token (side binance moved in first 5 s) when cheap
(`entry_vwap<0.55`), gated `delta_bps≥3/5`, **sell on the book at +60 s**. OOS-validated 5 coins; `delta_bps` is the
sufficient statistic (ML can't beat it); **TP@0.65 hurt (caps runners) — but the stop@(fill−0.10) IS edge (+0.88/tr
SIG, validated 3×, keep it)**; +60 s is the exit-timing optimum.
**Prior unhandoffed session (06-07/06-08)** had already scaffolded two POCs with **no report** — I recovered their
results: `scalp_midwindow_2026_06_07.py` (naive mid-window re-fire) and `scalp_regime_gate_2026_06_08.py` (vol/trend
terciles). Both were inconclusive/negative and never written up. This session finishes and supersedes them.

**Search substrate:** aliplayer BBO `Mar 30 → Apr 21` (`load_orderbook_bbo`, slot-aligned, disjoint from the
Apr22–Jun deploy search), 1 s binance klines. Fill model identical to the validated `scalp_oos_bbo_2026_06_05.py`
(entry $25 @ best_ask t+85 ms, size-capped, spread≤0.05; exit SELL best_bid +60 s; fee 0.015 round-trip).
**CAVEAT:** BBO = top-of-book → entry slightly optimistic (no L25 depth walk). Anything that *passed* search would
get an L25 `Apr22–Jun8` OOS gate; nothing passed, so no OOS was warranted.

---

## 1. TRIAL — Mid-window naive re-fire (recovered from prior POC) → **DEAD**
Fire the SAME lag signal at an offset grid {5,120,…,720} s instead of only +5 s. Pooled BTC+ETH 15m, gated `<0.55`:

| offset | gated $/tr (t) | verdict |
|---|---|---|
| +5 s | **+1.84 (2.71)** | the deployed open scalp |
| +120 s | +3.55 (2.10) CI[+0.48,+7.07] | flicker, wide CI, n=43 |
| +240→720 s | noise → negative (+480 s −4.46) | dead |
| pooled off≥120 | **+0.25 (0.38)** | flat |

The edge does not survive past the open. (Reproduces the priced-in-trap thesis.)

## 2. TRIAL — Fair-Value-Gap (FVG) continuous entry → **DEAD mid-window (anti-signal)** ⭐ main new trial
The principled generalization: at any second *t*, binance implies a **driftless digital probability** the window
settles Up — `imp_up = Φ( ln(price_t/strike) / (σ·√τ) )`, strike = price@slot_start, σ = 1 s-logret std (trailing
300 s, causal), τ = seconds remaining. Enter the side where `gap = imp_up − poly_p_up` is large (poly under-pricing
it); sell +60 s. This recovers the lag-taker at the open AND is evaluable mid-window → the cleanest test of "is
there a mid-window dislocation." Threshold/offset/vol-lookback swept; `scalp_fvg_2026_06_09.py`.

**Result (cheap-gated, |gap|≥0.08):**

| coin-tf | +5 s (open) | mid-window (off≥120) |
|---|---|---|
| ETH 15m | +0.51 (CI spans 0) | **negative**, −2 to −3 @ t≤−2.5 |
| ETH 5m | +1.17 (CI spans 0) | negative (−1.9 to −2.0) |
| SOL 15m | **+2.29 (3.38) CI[+0.98,+3.61]** | **strongly negative** (−2 to −4.7, t=−3 to −6) |
| SOL 5m | (open weak +) | negative |

- The FVG recovers the **open** edge only (SOL 15m +5 s = the existing open scalp). The per-offset map is a
  **plateau test and it FAILS**: only the open spikes; everything ≥120 s is negative, often significant.
- **First-cross-among-mid-offsets is an anti-signal** (t = −4 to −6 pooled). Mechanism: by ≥120 s the poly book has
  fully absorbed the binance level; a residual "gap" is stale-σ miscalibration or the book correctly pricing
  mean-reversion the driftless digital ignores — **not a lag**. The only positive mid cells are the illiquid last
  ~30 s (+725 s ETH `+14.5` but CI[−0.9,+34], n≈60 = noise; matches the known "oracle-determinism = underpowered").

**Verdict: there is NO mid-window / 1-min-inside lag scalp.** Two independent signals (naive re-fire + principled
FVG) agree. The edge is open-only.

## 3. TRIAL — Cross-asset lead-lag (BTC leads ETH/SOL) → **DEAD** (paired-controlled)
BTC drives alts; does the follower's poly book lag BTC more than its own feed? Variants at the open vs the OWN
baseline: BTC (fire on BTC's direction), CONFL (both agree), BTCLEAD (own flat, bet it follows BTC).
`scalp_xasset_2026_06_09.py`, ETH+SOL 15m+5m.

- ETH alone *looked* like a win: BTC +$2.18 (t 2.42) > OWN +$1.44 (t 2.03). **But SOL reversed it** (BTC +$1.40 <
  OWN +$2.04).
- **Pooled: OWN +$1.77 ≈ BTC +$1.79** (identical). **Paired on shared slugs: diff(BTC−OWN) = −0.04, CI[−0.12, 0.00]**
  — BTC is not better, marginally worse.
- **Root cause:** `sign(BTC) ≠ sign(own)` only **4.8 %** of fires → BTC and the follower move together in the first
  5 s, so "fire on BTC" ≈ "fire on own." The leader adds no tradeable information. **BTCLEAD** (pure lead-lag) is
  noise/negative (ETH −$4.5 @ +60 s, t=−2.9).

**Verdict: cross-asset conditioning adds nothing** — alts are too correlated to BTC at 5 s for the leader to lead.

## 4. RECONFIRM — Regime gates (finishes the prior POC) → **nothing new beats `delta_bps`**
Pooled 6-coin OOS gated fires (1303), terciles + train/test split:
- **Realized vol:** low +$1.28 > mid +$0.84 > **high +$0.67** (counter-intuitive: hi-vol is WORSE). hi-vol gate
  **fails train/test** (TRAIN +0.60 / TEST +0.49, both < baseline +0.93). Low-vol is the only regime with a pulse →
  **monitor candidate, not yet OOS-robust.**
- `|trend|` non-monotonic (MID best) → not a gate. **`delta_bps`** monotonic, holds train+test — but that is the
  known sizer, not new. `lowVol/hiTrend` cross = best cell (+$1.83) but untested OOS.

---

## 5. The one positive (reconfirmation, not new): the OPEN scalp
Pooled ETH+SOL, **+5 s, OWN signal, cheap-gated**: **+$1.77/tr, t=3.96, CI[+0.89,+2.65]** (n=326). SOL 15m strongest
(+$2.04, t=3.55). This is the deployed edge, re-validated on the disjoint BBO window from a clean re-derivation.

## 6. Rigor / DSR framing
~**> 60 distinct cells** were evaluated this session (4 coin-tf × {FVG threshold×offset, 4 xasset variants×5
offsets, regime terciles}). Under that multiplicity, **zero new positive cells survive**: the FVG/regime positives
are the already-known open-scalp cells, and the one apparent new winner (ETH cross-asset) is killed by its **paired
control** and by SOL. The plateau test (FVG per-offset map) shows **no plateau** away from the open. No result
clears a deflated bar because no new result clears even the *naive* in-sample bar. Consistent with the project's
standing result that selection/prediction is efficient at every scale; only the **execution** edge (open exit-scalp)
is real.

## 7. Recommendation
- **Close mid-window and cross-asset** — both are now evidenced dead; do not re-scaffold (the prior session burned a
  cycle re-deriving mid-window with no handoff). The edge is open-only by mechanism.
- **Keep the deployed open exit-scalp as-is.** The live priorities are unchanged and operational, not research:
  ship the **disable-TP-only** fix (TP@0.65 is the non-edge — proven 3×; the **stop@(fill−0.10) IS validated edge,
  +0.88/tr SIG → KEEP it**, per `project_scalp_exit_config` memory, which supersedes the stale 06-06
  "disable TP+stop" phrasing), the **maker-exit** A/B, and accumulate **≥200 live forward fires** (the real
  graduation gate). NOTE: this session's trailing-exit test (§8) is about *trailing* stops vs fixed-+60 timing — it
  does NOT bear on the validated fixed stop-loss.
- **UPDATE (overnight):** both of those "remaining threads" were then tested and **also died** — the tick-level
  trailing exit loses to fixed +60 (§8), and the low-vol gate fails the coin-split / hurts BTC+ETH (§11). There is
  **no remaining existing-data research thread.** New edges require **new data**: (a) verify **Kalshi ask-depth**
  to unlock the deep-dip **Poly×Kalshi arb** (the one open positive lead); (b) the Poly **CLOB WS trade tape** for
  slug-selection; (c) **futures funding/OI** regime once `cex_futures` spans >1 scalp window.

## Files
- `strategy_lab/directional/scalp_fvg_2026_06_09.py` + `fvg_analyze_2026_06_09.py` → `_results/scalp_fvg_grid_2026_06_09.parquet` (ETH+SOL; BTC run aborted — verdict already airtight on 4 coin-tfs)
- `strategy_lab/directional/scalp_xasset_2026_06_09.py` → `_results/scalp_xasset_2026_06_09.parquet`
- Recovered POCs: `scalp_midwindow_2026_06_07.py` (`_results/scalp_midwindow_2026_06_07.parquet`), `scalp_regime_gate_2026_06_08.py`
- Logs: `_results/{fvg,xasset}_run_2026_06_09.log`

---

# OVERNIGHT CONTINUATION (autonomous, 2026-06-09) — additional trials

Operator left it running overnight to "continue until you find new optimal strategies." Additional
pre-registered trials below. Running tally of new deployable edges: **0** (see each verdict).

## 8. TRIAL A — Tick-level trailing / peg EXIT (the flagged "future work") → **DEAD** ⭐
`SCALP_DYNAMIC_EXIT_2026_06_04` flagged that the bid PATH-MAX (~0.84, oracle peak-sell +$18/tr) is a transient
spike a fixed-time exit misses, and proposed a tick-level trailing stop as future work. Tested it on the ~200 Hz
event-driven BBO bid path (disjoint window), with policies evaluated on **both a 5 s poll grid (live-realistic —
the engine polls the exit every ~5 s) and a 1 s grid (optimistic)**. Trailing = sell when bid ≤ (running-max
since entry) − X; plus arm-then-trail variants. `scalp_trailing_exit_2026_06_09.py` (n=395 cheap fires).

| exit policy | pooled $/tr (t) | paired vs FIXED_60 |
|---|---|---|
| **FIXED_60 (deployed)** | **+1.92 (4.83)** | — |
| FIXED_45 / FIXED_90 | +1.70 / +2.06 | ≈0 (tied, as known) |
| 5s_trail_.02 | +1.16 | worse |
| 5s_trail_.05 | +0.11 | **−1.82 (t=−2.99)** |
| 5s_trail_.08 | −1.26 | **−3.26 (t=−4.77)** |
| 5s_arm.05_trail.05 | −0.04 | −2.04 (t=−3.01) |
| 1s_trail_.05 | −5.0 | **−7.01 (t=−8.71)** |
| PEAK_oracle (untradeable) | **+16.96 (34.1)** | +15.0 |

**Every realizable trailing/peg policy loses to fixed +60, significantly, on every grid.** The 1 s grid is *worse*
than 5 s — a tight stop on a noisy bid path whipsaws out before the reprice. The oracle peak headroom is real
(+$17) but **genuinely untradeable**: any stop loose enough to avoid whipsaw gives the spike back; any stop tight
enough to lock it gets stopped out by noise first. Fixed +60 captures the *average* reprice (~0.59) and dominates.
**Verdict: exit refinement is closed — fixed +60 is robustly optimal vs the entire trailing family. Confirms the
dynamic-exit study's suspicion with a real trailing simulation.** (No L25 OOS needed — failed search decisively.)

## 9. TRIAL B — Open-scalp knob re-optimization (entry offset + delta band) → reconfirm, no new edge
Plateau-tested two knobs on the disjoint window. `scalp_entry_opt_2026_06_09.py` (pooled ETH+SOL; BTC aborted for
the higher-value Z scan — verdict clear).

**(1) Entry offset (signal = binance return over [slot_start, slot_start+off]):**
| +1s | +2s | +3s | **+5s** | +8s | +10s | +15s |
|---|---|---|---|---|---|---|
| +3.27 (n133) | +0.83 | +1.41 | **+1.77 (3.96)** | +0.51 | −0.08 | −0.11 |
+1s spikes high but its neighbor +2s collapses → **non-robust spike (fails plateau), small-n, extreme 1s moves**;
+3/+5s form the robust plateau, decaying after (lag dissipates). **+5s confirmed near-optimal; no improvement.**

**(2) Delta band at +5s (clean monotonic plateau):**
| [3,∞) | [4,12] | **[5,12]** | [5,∞) | [8,∞) |
|---|---|---|---|---|
| +1.77 (n326) | +2.11 | **+3.41 (4.07, n84)** | +3.42 | +4.56 (n32) |
Higher δ-floor → higher $/tr, monotonic, every CI>0. **δ≥5 ≈ 2× $/tr of δ≥3** for ¼ the volume — reconfirms
`delta_bps` as the sizer (deployed already splits δ≥3@$5 / δ≥5@$25). The "12 cap" is nearly irrelevant in this
window (≤8 fires exceed it). **No new knob; the deployed operating point is right.**

## 10. TRIAL Z — Same-venue two-sided arb (different mechanism) → **DEAD (efficiently priced)**
Not directional/lag: if a *causal* snapshot has `up_ask + dn_ask < 1`, buy both → exactly one pays $1 → riskless.
`scalp_twosided_arb_2026_06_09.py`, causal asof on each token (the real live book each side shows).
- `sum_ask` median **1.010**, mean 1.022 (the book overround/spread) → buying both costs >$1.
- `sum_ask < 1.00`: only **0.04 %** of snapshots, and **all at zero executable size** — stale/dust single-tick
  artifacts (confirms the handoff's "cross-token price-sum = lookahead artifact" — they are NOT fillable arbs).
- `sum_bid` max 1.009 → can't mint-and-sell both for >$1 at size either.
**Verdict: efficient. No same-venue arb.** (The real cross-venue dip arb is Poly×**Kalshi**, gated on Kalshi depth.)

## 11. TRIAL C — Low realized-vol gate, proper OOS → **DEAD as a deployable gate**
The one regime lever with a pulse (POC terciles LOW +1.28 > MID +0.84 > HIGH +0.67). Tested the LOW-vol gate (the
deployable direction the POC never isolated) with two splits; `scalp_lowvol_gate_2026_06_09.py`:
- **Time-split:** holds — TRAIN lowVol +1.54 / TEST lowVol +1.14, both beat baseline, CI>0. ✓
- **Coin-split (train BTC+ETH, test SOL):** **FAILS on BTC+ETH** — lowVol +0.77 < baseline +0.90, and hi-vol +1.02
  is *better* there. The pooled low-vol effect is carried by thin alts (SOL/DOGE/XRP, CIs span 0).
**Verdict: coin-inconsistent; a low-vol gate would HURT the live BTC/ETH deployment. Monitor, not a gate** — same
fate as every other regime lever. `delta_bps` remains the only robust selector.
