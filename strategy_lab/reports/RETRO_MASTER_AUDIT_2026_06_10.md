# MASTER RETROSPECTIVE AUDIT — everything tried in the 5m/15m up-down markets — 2026-06-10

**Scope:** ~2.5 months, 696 reports, ~60 script dirs, 215-sleeve live/shadow fleet, every gate/indicator/backtest/
rigor-test run against Polymarket+Kalshi crypto up-down 5m/15m (BTC/ETH/SOL focus). Produced by a 6-agent audit
(catalog, scalp line, directional line, ML/rigor line, data/fill/fee infra, external whitespace research).
**Detail sections:** `_retro_2026_06_10/01_CATALOG.md … 06_WHITESPACE.md` — this file is the synthesis.

---

## A. WHAT WE TRIED (compressed map — full catalog in 01)

| Line | Verdict | Status |
|---|---|---|
| V1→V5 momo/sniper evolution, Cyclops, F7, momo_v2/markov | mostly decayed live; engine faithful | fleet pruned |
| GA sniper v6/v7/v8 (ETH 5m hurst/cloud/bb), ema_down band, trstack | 4 "edge" sleeves t≈2 — **never deflated** | live, evidence grade B/C |
| Session/ToD gates for direction (keep_EU, drop_US, vsum) | all failed first disjoint OOS | dead |
| Wallet-hunt: ~50 wallets decoded; mint-and-sell replicated; F2 slug-selector | mechanism IDs real; F2 unreproducible | residual: oracle-snipe (§E) |
| Maker-arb / mint-and-sell V2 | **+$4.44/slug was survivorship bias** → −$0.41 to −$3.63 | dead as tested (but see §E rebate re-open) |
| Indicator sweeps: TA mega-run, VBT, VWAP family, VPIN/Hawkes, Hurst, microprice, MLOFI, Lee-Mykland, 4.8M combos | coin-flip vs oracle; high-WR ones = priced-in trap | dead |
| ML: GPU LSTM/deep nets (0/415), Kronos (52.9%), meta-label CPCV, 387k selectors (0/20 DSR) | prediction is efficient at our signal set | dead |
| Lag-taker hold-to-resolution | OOS-weak (+$0.36 unseen) | superseded by exit-scalp |
| **Exit-SCALP (open lag-taker, sell +60s, stop on)** | the one validated edge | **live $1 + shadow; see §C caveats** |
| Scalp extensions: mid-window, FVG, cross-asset, regime, trailing, two-sided arb, low-vol | all dead under controls (7 trials, 06-09) | closed |
| Poly×Kalshi deep-dip arb (sum<0.95 → +2.7–6.6¢/set) | real in data; blocked on Kalshi ask-depth | **open lead** |
| Cross-timeframe arb, favorite-longshot, liquidity-inversion, oracle-determinism selector | efficient / dies on fills / underpowered | dead/parked |

## B. WHAT WE DID RIGHT
1. **The engine audited clean every time** — every live-vs-backtest divergence traced to signal construction or data, never the fill engine. Live/shadow parity forensics (06-02/06-08) were exemplary.
2. **We caught our own worst errors**: maker-arb REDEEM censoring (survivorship), ws_s anchor lookahead (25–40pp), LAGV2 always-UP, V2 inversion, sleeve PnL double-count. The GROUND-TRUTH RULE exists because we enforced it.
3. **Honest negative rigor**: the 387k-selector DSR (0/20), 4.8M-combo PBO, 0/415 GPU sweep counted trials honestly and killed seductive candidates. WR≠edge / print≠fill / priced-in-trap are now institutional knowledge.
4. **Canonical single-source data discipline** + conventions doc prevented an entire class of silent contamination after the binance-resolution bug (+$14k phantom) was caught.
5. **The one surviving edge is execution-shaped, not prediction-shaped** — consistent with binary-market microstructure reality.

## C. WHAT WE DID WRONG (severity-ranked, consolidated from 02–05)

**🔴 C1. Outcome leaks into the scalp exit price (live lookahead bug, found in this audit).**
`sell = bid[jx] if valid else (1.0 if won else 0.0)` — when the book is missing at +60s the *resolved outcome*
substitutes the exit price. Present in `scalp_oos_bbo_2026_06_05.py:82` and propagated into the stop/maker-exit
scripts. Inflates winners, deepens loser baseline → **the stop's +0.88/tr magnitude is tainted** (direction
probably right per `_stop_decompose.py` ex-fallback numbers; magnitude must be re-measured). Re-run required.

**🔴 C2. The "clean OOS" window (Mar30–Apr21) is burned.** Sold as a one-shot deflation gate (SCALP_OOS_PASS),
then re-read ≥6× (5-coin extension, TOD gate, maker-exit, FVG, regime, trailing, knob-reopt — the 06-09 session
explicitly used it as the *search* substrate). It is now in-sample. **No genuine untouched OOS window currently
exists for the scalp.**

**🔴 C3. Deflation was never applied before deploys.** DSR/PBO arrived 06-04; the fleet (215 sleeves) was deployed
and judged on raw t-stats over single windows with a 10³–10⁴ config search space behind them. Result: −$25.4k
shadow drag, **~70–85% preventable** by rules that existed by the end (priced-in-trap check alone refuses the
−$19.8k bleeder bucket). No currently-deployed directional sleeve has a surviving deflated test.

**🔴 C4. The scalp's own DSR is pseudo-pre-registered.** k_eff=1 priced only the meta-model choice; the base knobs
(0.55 band, +60, δ, coins, TOD) were tuned across sessions. The thing that actually saved the scalp was the
disjoint-window OOS — which C2 just burned. Combined with C1, **the deployed edge's true effect size is uncertain;
plausibly ~⅓ of the +$2–5/tr headline** (C1 + no-bid-size-check + top-of-book optimism stack).

**🟠 C5. Sell-leg fill realism**: exit takes full size at best_bid, no depth check, while reports themselves name
thin-book exit slippage as the dominant tail loss (worst-5% ≈ −$19–23). Entry is size-capped; exit is not.

**🟠 C6. engine_v2 fee bug (conservative direction)**: loser branch double-charges the entry fee (~$0.87/losing
trade) vs live $0-on-losers. Anything that *passed* LiveMimic is safe; marginal *failures* deserve re-check.
`min_book_events` silently disabled pre-05-30 → pre-05-30 LiveMimic results need re-base.

**🟠 C7. Stale GO claims still in CLAUDE.md**: Cyclops S7 X1 (n=36, never re-passed modern fill/fee/DSR) and
Mint-and-sell V2 (sign flips on a post-hoc subset; 200×–10,000× wallet-PnL gap unexplained) read as deploy-ready.

**🟠 C8. Selection-on-judgment-window was the recurring process failure** behind every "live ≫ backtest" decay:
gates fit on 3–5-day live windows and validated on the same window; GA panels reused as validation for sleeves
they bred. Plus deploy-then-audit ordering bled real shadow capital before checks ran.

**🟡 C9. resolutions_hf slot-timing offset — ❌ REFUTED 2026-06-10** (`_retro_2026_06_10/FIX_A2_RESTIMING.md`):
verified against slug-suffix ground truth + a binance outcome-agreement sweep (peaks exactly at 0s for ALL
source/tf groups) — **the timing is correct.** The Feb21–Mar24 L25 books genuinely start ~+75s (median) into the
window (p10–p90 = 47–108s) → **the +5s open-scalp can NEVER be tested on Feb–Mar** (data-availability ceiling, not
a fixable label bug). Consequence: **no fresh offline OOS window exists at all** — the live ≥200-fire forward test
is the ONLY remaining true OOS for the scalp. The earlier "Feb–Mar negative" stays unusable (confounded re-anchor).

**🟡 C10. Pipeline risk**: delete-source-after-merge under 97% disk; one interrupted L25 atomic replace = unrecoverable.

## D. TRUST TABLE (what to believe today)

| Claim | Trust | Why |
|---|---|---|
| Open exit-scalp edge EXISTS (direction) | HIGH | permutation p=0, multi-coin, mechanism-grounded, live spec-true |
| Its MAGNITUDE (+$2–5/tr) | LOW | C1+C2+C5 stack optimistic; expect ~⅓ until re-measured |
| Stop ON (+0.88/tr) | direction MEDIUM, magnitude LOW | C1 taints fallback fires; re-run ex-fallback |
| TP@0.65 anti-edge; +60 optimal vs trailing/TP | HIGH | paired tests, conservative direction |
| TOD gate {12,17} | MEDIUM | passed "OOS" pre-burn; owes trial-counted DSR on the 24h sweep |
| 4 directional "edge" sleeves | LOW-MEDIUM | never deflated; ETH one ≈ breakeven live after fill haircut |
| All the deaths (ML, indicators, mid-window, etc.) | HIGH | negative results used honest trial counting |
| Poly×Kalshi arb numbers | MEDIUM | real in data, short sample, depth unverified |

## E. PATH FORWARD (ranked; effort S/M/L; each with kill-criteria)

**E1 (S, do first). Repair the validation foundation. — STATUS UPDATE 2026-06-10:**
(a) ✅ DONE — corrected harness built (`scalp_fill_lib_2026_06_10.py` + `*_fixed_2026_06_10.py` runners): no
outcome-as-price fallback (missing quote → position held to resolution, faithful to live), 120s staleness guard,
size handling with the artifact-aware policy (BBO size==0 = collector artifact ~47% of rows, treated as unknown
with carry-forward), ALL vs CLEAN dual reporting. (b) ❌ REFUTED — see C9: timing was correct, Feb–Mar books start
+75s → no fresh offline window exists. (c→) therefore the re-validation = re-run on Mar30–Apr21 with the corrected
harness (measures the BUG DELTA, not fresh OOS) + **the live ≥200-fire forward test is the only true OOS left**.
(d) stop re-measured inside the corrected runner (paired stop-ON−OFF). Results: `BUGFIX_RERUN_RESULTS_2026_06_10.md`.

**E2 (S). Late-slot Chainlink oracle-latency snipe — best untried idea, all data on disk.**
Wallet-decoded 87% accurate at T−30s; open-source precedent exists; the new V2 dynamic fee (~3.15% peak at 50¢,
≈0 at extremes) kills mid-window latency arb but leaves the cheap-winner late snipe nearly fee-free. Backtest vs
RTDS 1Hz + L25. Kill: fills<2% or $/tr CI≤0 after fees at realistic latency.

**E3 (M). Re-open MAKER with rebate-as-income.** The "maker entry = adverse selection = dead" verdict predates the
Mar-30 rebate program (100% of taker fees → daily maker rebate). Our death-test never added the rebate term.
Model: rebate share verification on the account dashboard first, queue-position proxy, **expiry losses booked**
(the C-survivorship lesson). Combine with the still-pending maker-exit-with-taker-fallback (+$0.42/tr first pass).
Kill: rebate share <10% or net CI≤0 with queue-aware fills.

**E4 (S). Kalshi ask-depth re-export** → deep-dip arb go/no-go. Already specced; make-or-break on one query.

**E5 (S). Hygiene overlays + debt cleanup.** Fee-geometry filter (|vwap−0.5| preference) on every taker strategy;
VPIN as maker *toxicity kill-switch* (not entry signal — that's the trap); annotate CLAUDE.md's Cyclops/mint-sell
GO claims as rigor-stale (C7); add the pipeline free-space guard (C10); re-rank any sleeve decision still based on
raw `events.pnl_usd`.

**E6 (M). Pre-window slug-selection from the CLOB WS event tape** — start COLLECTING the tape now (adds/cancels/
queue); the undecoded F2 alpha lives there. No backtest possible until ~3 weeks of tape exists.

**E7 (M). Fresh forced-flow/liquidation cascades** — refresh HL liqs + use cex_futures liqs (now 4 exchanges);
the A1 candidate was real-but-stale. Funding/OI regime becomes testable as cex_futures accrues.

**E8 (process, permanent).** New rules: (i) every OOS window is single-read — log reads in the report header;
(ii) no deploy without trial-counted DSR + priced-in-trap check + fill-haircut sim; (iii) audit-then-deploy, never
the reverse; (iv) magnitude claims require the corrected harness (C1/C5 class bugs checked by a standard lint).

## F. ONE-PARAGRAPH VERDICT
We ran a genuinely impressive breadth of research and built rare assets (canonical data, live-mimic engine,
parity-audited fleet, institutional rules) — and the central conclusion (execution edges exist, prediction edges
don't at our signal set) is right. But the audit found the validation foundation under the ONE live edge has two
real cracks (outcome-leak fallback; burned OOS window) and the fleet era burned ~$25k learning process lessons
that now exist as rules. The next session should NOT hunt new strategies first — it should execute E1 (repair +
fresh-window re-validation), then E2–E4 which are cheap, data-ready, and mechanism-grounded. The edge-hunting
whitespace is real but narrow: settlement mechanics, maker rebates, counterparty flow — not more indicators.
