# EXIT-SCALP Methodology Audit — 2026-06-10

**Auditor:** senior-quant retro. **Subject:** the project's one validated edge — intra-window exit-scalp
(buy the lag-taker token at slot_start+5s if `entry_vwap<0.55`, sell on the book at +60s).
**Sources read:** `INTRADAY_SCALP_RESEARCH_2026_06_02`, `SCALP_VALIDATION_2026_06_02`,
`HANDOFF_2026_06_03_SCALP_DEPLOY`, `SCALP_DYNAMIC_EXIT_2026_06_04`, `META_LABEL_SCALP_CPCV_2026_06_04`,
`SCALP_OOS_PASS_2026_06_05`, `SLUG_SELECTION_RESULTS_2026_06_05`, `MAKER_EXIT_SIM_2026_06_06`,
`SCALP_LIVE_AUDIT_2026_06_06`, `SCALP_NEW_EDGE_HUNT_2026_06_09`; scripts `scalp_oos_bbo_2026_06_05.py`,
`scalp_exit_validation_2026_06_02.py`, `scalp_rigor_full_2026_06_02.py`, `maker_exit_by_tf_2026_06_06.py`,
`_stop_decompose.py`; memory `project_scalp_exit_config`.

---

## Verdict summary (per audit question)

| # | Question | Verdict |
|---|---|---|
| 1 | Lookahead in signal/fill/exit timestamps | **MOSTLY SOUND, one real leak** — entry/exit timing is causal; the **exit-fallback `(1.0 if won else 0.0)` injects the outcome** when the book is missing/clamped. Contaminates a non-trivial tail. |
| 2 | Fill realism (BBO top-of-book, sell leg) | **FLAWED (optimistic)** — SELL leg does **NOT** check `bid_size`; assumes full size at `best_bid`. Entry is size-capped but exit is not. |
| 3 | Fee model (0.015 round-trip proxy) | **OPTIMISTIC but defensible** — sits below the realistic ~$0-buy + ~1.5-2% winner-sell band; not the failure mode. |
| 4 | Selection / OOS burn | **FLAWED — OOS window is now BURNED.** Mar30–Apr21 was re-read ≥6× (5-coin, TOD gate, maker-exit, FVG, regime, trailing, knob-reopt). It is no longer a clean deflation gate. |
| 5 | Survivorship / book coverage | **MODERATE RISK, partly unquantified** — "fill only if book exists" (~45% fill) + the `won`-fallback could correlate missing-book with outcome. Not directly tested. |
| 6 | Stop/TP contradiction | **RESOLVED correctly in direction, but the +0.88/tr magnitude is LOOKAHEAD-TAINTED** — the stop's loser-benefit rides on `won`-forced `b60=0` fires. Keep-stop is probably right; the number is not trustworthy. |
| 7 | Forward-OOS gap vs search estimate | **OPEN / UNRECONCILED** — offline forward window was flat-negative; no report reconciles live shadow $/tr against the +$1.7–2.5 search estimate with CI. Graduation gate (≥200 live fires + live-wallet CI) NOT met. |

**Bottom line:** the edge is *probably real* (the open-only lag→reprice mechanism is coherent, permutation
p=0, the gate lift replicates), but **every headline number is optimistically biased** by 2-3 stacked
effects (no exit-size cap, outcome-fallback, burned OOS, optimistic stop fill). The true deployable edge is
materially smaller than the +$2–5/tr reported, and the only honest remaining gate is **live forward wallet PnL**.

---

## Errors found (severity-ranked)

### 🔴 SEV-1 — Outcome (`won`) leaks into the exit price via the fallback branch
`scalp_oos_bbo_2026_06_05.py:82`:
```python
sell = bid[jx] if (0 <= jx < len(ts) and np.isfinite(bid[jx])) else (1.0 if won else 0.0)
```
Same pattern in `maker_exit_by_tf_2026_06_06.py:36`, `_stop_decompose.py:19`, `scalp_rigor_full` hold-fallback.
When the book is missing at the +60s exit (no BBO snapshot, or clamp-to-slot_end lands past coverage), the
code substitutes the **resolved outcome**: winners sell at 1.0, losers at 0.0. This is forward-looking — at
+60s you do not yet know `won`. Effect: it **inflates winners and (for the stop) deepens the loser baseline
that the stop then "rescues."** Min `pnl60` = −$24.76 (≈ −full stake) confirms a population of `sell≈0`
fallback fires. The fallback is defensible for the *hold* branch only (hold genuinely runs to settlement);
it is NOT defensible inside a +60s mid-window exit. **Must re-run dropping (or neutrally pricing, e.g. at
last-known bid) the fallback fires and report how the gated $/tr and CI move.**

### 🔴 SEV-1 — OOS window (Mar30–Apr21) is burned by repeated re-use
`SCALP_OOS_PASS_2026_06_05` frames Mar30–Apr21 as *the* clean disjoint deflation gate. But the same window
+ same `scalp_oos_bbo_fires_*.parquet` fires were subsequently mined for: 5-coin extension (BTC/ETH/SOL +
DOGE/XRP/BNB), the **time-of-day gate** (22–02 boost, exclude {12,17}), **maker-exit OOS** (`MAKER_EXIT_SIM`
says "confirm OOS on Mar30–Apr21"), **FVG / cross-asset / regime / trailing / knob-reopt** (`SCALP_NEW_EDGE_HUNT`
§7 explicitly states "anything that passed search would get an L25 Apr22–Jun OOS gate" — i.e. it is treating
Mar30–Apr21 as the *search* substrate now). Counting conservatively, the window has been read **≥6 times**
with selection happening against it. The deflation property (the whole point of DSR) requires the OOS be
touched **once**. It is now an in-sample window. **The genuine different-window deflation gate no longer
exists in the current data; a fresh untouched window is required.**

### 🟠 SEV-2 — SELL leg ignores `best_bid_size` (exit fill is optimistic)
`scalp_oos_bbo_2026_06_05.py`: entry caps size at `best_ask_size` (`shares = min(STAKE/a0, s0)`), but the
exit takes `sell = bid[jx]` with **no `best_bid_size` cap**. The deployed live engine walks the bid ladder
(`sell_at_bid_partial`) and on a thin book gets a worse vwap. `SCALP_VALIDATION_2026_06_02` §4 already
identified thin-book exit slippage as the dominant tail-loss driver (worst-5% ≈ −$19 to −$23) — yet the OOS
fill model assumes full size at the top bid. This biases gated $/tr **up** and understates left-tail risk.
The report's own caveat ("BBO top-of-book → entry slightly optimistic") names the entry but **misses that
the more material optimism is on the exit**.

### 🟠 SEV-2 — Stop's +$0.88/tr is computed on a lookahead-tainted, optimistic-fill baseline
`maker_exit_by_tf_2026_06_06.py` and `_stop_decompose.py`: the stop fires when `min(bid_30,45,60) ≤ ev−0.10`
and is then priced as a **taker-sell exactly at `stop_lvl`** (slip=0 default; the deployed +0.88 cites the
optimistic fill). But (a) the `taker60` baseline it is compared against uses the `won`-fallback `b60`, so the
loser baseline is artificially −full-stake on fallback fires, making the stop look like it rescues more than
it does; (b) live the stop is a taker-cross into a *falling thin book*, not a clean fill at `stop_lvl`. The
script's own slippage sweep shows the edge **survives ≤3c, dies at 6c** — and the memory itself flags "stop
MAGNITUDE not direction" as open. So the **keep-stop decision is plausibly correct, but +0.88/tr is not a
trustworthy number.** `_stop_decompose.py` exists precisely because someone already suspected the
fallback-dependence — its `EXCLUDING fallback fires` re-estimate is the number to trust, not the headline.

### 🟡 SEV-3 — Fee proxy 0.015 round-trip is optimistic vs the worst realistic case
`bpnl = (sell−ev)*sh − 0.015*sh*(ev(1−ev)+sell(1−sell))`. CLAUDE.md production truth = **0-fee buy leg +
winner-only `0.07·p·(1−p)` sell leg**. At p≈0.6 the per-leg `0.07` term is ~0.0168, so charging 0.015 on
**both** legs (incl. the buy, which is actually free) is a rough wash, not a clear over- or under-charge. The
honest stress case (`scalp_rigor_full`, `FEE07` both legs) is reported elsewhere and the gated cell survives
it, so fees are **not** the binding risk. Flagging only because the 0.015 proxy is presented as "matches the
cache pnl_at" without re-deriving against the operator-confirmed winner-only curve.

### 🟡 SEV-3 — `resolutions_hf` / BBO coverage survivorship not directly tested
Fill rate is ~45%. The unfilled 55% are dropped, and the `won`-fallback handles missing-at-exit. Neither
report tests whether **missing-book correlates with outcome or with regime** (e.g. fast-move slugs where the
MM pulls the book are exactly the slugs that resolve directionally). If book-absence is outcome-correlated,
both the fire-set and the fallback are biased. This is plausible given the lag mechanism literally depends on
MM book staleness. **Untested; should be.**

---

## What was done RIGHT

- **Causal signal anchor.** `delta_bps` = |binance 1s return over [slot_start, slot_start+5s]|, fire at
  +5s+85ms latency. The 1s-kline `asof` (`searchsorted(...,'right')−1`) is correctly causal; no future bar
  leaks into the signal. Latency modeled.
- **Direction permutation (Gate 5)** is a genuine, hard test: lag-side +$0.96 vs opposite −$4.52, perm
  p=0.0000. This is the strongest single piece of evidence the edge is real and not a sign artifact.
- **The priced-in-trap discipline.** The whole research line correctly distinguishes WR≠edge (B1/C4 traps),
  and the exit-scalp's thesis (sell the reprice, don't hold into the priced-in resolution) is mechanistically
  honest. HOLD→resolution +$0.14 vs sell-on-book +$5.56 cleanly isolates execution as the edge.
- **ML meta-label correctly came back NEGATIVE** (`META_LABEL_SCALP_CPCV`): they did NOT overfit a model on
  top; `delta_bps` is the sufficient statistic, and they accepted the null instead of forcing a model into
  the live path. Rare and correct.
- **Exit timing was stress-tested honestly** — trailing/peg/TP all tested and rejected vs fixed +60 with
  paired bootstrap; the oracle peak-sell was correctly labeled untradeable rather than booked as edge.
- **`_stop_decompose.py` itself** — the team built the exact tool to expose the fallback-dependence of the
  stop. That instinct is right; the audit's only complaint is that its "excluding fallback" number, not the
  headline +0.88, should be the cited authority.
- **Multi-coin independence** — BTC/ETH/SOL/DOGE/XRP each clear gated CI>0 *independently*; cross-coin
  replication is real evidence even though the *window* is shared.

---

## Residual risks before scaling capital

1. **The headline $/tr is stacked-optimistic.** No-exit-size-cap + `won`-fallback + burned-OOS + optimistic
   stop fill all push the same direction. A defensible point estimate after de-biasing is plausibly
   **+$0.5–1.5/tr gated**, not +$2–5. Size as if the edge is ~⅓ of the headline.
2. **No clean different-window OOS remains.** Mar30–Apr21 is spent. Real deflation now requires a *new*
   untouched window (the operator's 6-month API w/ books+trades+klines) — until then, treat the strategy as
   in-sample-only no matter how many gates it "passed."
3. **Live forward gate UNMET.** The stated bar (≥200 live forward fires + live-wallet CI>0) has not landed
   (~16 live fires on Ireland, shadow `sell_leg_fee=0.0` overstates shadow PnL per `SCALP_LIVE_AUDIT`). The
   offline forward window was *flat-negative*; this is the single most important unresolved signal and it
   points the wrong way.
4. **Thin-book exit tail.** Worst-5% ≈ −$19–23 (near full stake), driven by exit-book liquidity. The OOS
   model doesn't reproduce it (no bid-size cap), so the realized live left tail will be **worse** than any
   backtest distribution shown.
5. **Stop slippage is the live make-or-break.** Edge survives ≤3c stop slip, dies at 6c. Live = taker-cross
   a falling thin book — the regime where slippage is *largest*. Unmeasured.
6. **Book-absence survivorship** could bias both the fire-set and the fallback in the edge's favor; untested.

---

## Concrete re-tests recommended (priority order)

1. **Kill the `won` fallback.** Re-run `scalp_oos_bbo_2026_06_05.py` with missing-exit fires either dropped
   or priced at last-known bid (never at `1.0/0.0`). Report Δ(gated $/tr, CI) per coin. This is one line and
   it tells you how much of the edge is lookahead. **Do this first.**
2. **Add a `best_bid_size` cap + bid-ladder walk on the SELL leg** (mirror the entry size-cap; or load L25
   for the OOS window if an aliplayer full-depth feed exists). Re-estimate gated $/tr and the left tail.
3. **Re-cite the stop on the de-biased baseline.** Take `_stop_decompose.py`'s "stop−taker EXCLUDING
   fallback fires" CI as the authoritative stop magnitude; re-run with slip ∈ {0,3,6c} on a real falling-book
   model. Update `project_scalp_exit_config` with the corrected number (or "direction-only, magnitude TBD").
4. **Reserve a genuinely fresh OOS window.** Pull a window never touched by any scalp analysis (the operator
   6-month API), pre-register the gated cell + exit + TOD gate, run **once**, report. No iterating on it.
5. **Test book-absence vs outcome.** On the OOS fires, regress `book_present_at_exit` (and at-fire) on `won`
   / `delta_bps` / hour. If missingness is outcome-correlated, the fire-set is survivorship-biased — quantify.
6. **Reconcile live vs estimate.** Once shadow `sell_leg_fee` is corrected, compute live-wallet $/tr with
   bootstrap CI and explicitly compare to the +$1.7–2.5 search estimate. State pass/fail against the ≥200-fire
   gate. This reconciliation does not currently exist in any report.
