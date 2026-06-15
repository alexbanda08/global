# 04 — ML / Statistical-Rigor + Wallet-Hunt / Maker-Arb Audit

**Date:** 2026-06-10 · **Auditor:** quant-research retro · **Scope:** (A) ML/stat-rigor research line, (B) wallet-hunt + maker-arb lines.
**Verdict in one line:** The rigor layer matured correctly and the *current* live conclusion (exit-scalp = execution edge) rests on the strongest evidence in the project. But several GO/insight decisions were made under weaker standards than they'd need today, the famous maker-arb catch was *late* (deployed-then-reversed), and "efficient at every scale" is overclaimed — it is "efficient vs our signal set," and a specific, large class of signals was never tried.

---

## 1. Rigor timeline (evolution of statistical standards)

| Era | Dates | Standard applied | Reports |
|---|---|---|---|
| **E0 — WR / raw t-stat** | ≤ 2026-05-18 | Win-rate, raw $/tr, raw t-stat. No multiple-testing correction, no fill model on many candidates. Mint-and-sell, F2, Cyclops G1/G3/G4 decided here. | WALLET_STRATEGIES_DECODED_0517, F2_FINAL_VERDICT_0518, MINT_AND_SELL_V2_0516 |
| **E1 — 3-way split + bootstrap CI** | 2026-05-23 → 05-26 | train/val/lockbox, bootstrap CI lower>0, IS/OOS Sharpe vs shuffled null. Microstructure verdicts (VPIN, Hurst, MLOFI, micro­price, LM, TA-mega). | VPIN_HAWKES_0526, VOL_HURST_0526, MLOFI_0526, TA_INDICATORS_MEGA_0523, VBT_MEGA_SWEEP |
| **E2 — fill-realistic revalidation** | 2026-05-27 → 05-28 | engine_v2 LiveMimicConfig (0.07 fee, 85ms, L25 ask-walk, sparse-book filter). The "print≠fill" / "WR≠edge" gate. Efficient-market capstone. Maker-arb censoring reversal. | EFFICIENT_MARKET_FINDING_0528, MAKER_ARB_CENSORING_REVERSAL_0528 |
| **E3 — confound-guarded search** | 2026-06-01 → 06-03 | adversarial fill backtest of swarm ideas; asset-confound penalty in the autoresearch harness; "move-already-happened" trap formalized. | EDGE_VALIDATION_TIER1_0601, AUTORESEARCH_W1_0603, AUTORESEARCH_SEARCH_RESULTS_0603 |
| **E4 — DSR / PBO / CPCV (ml4t)** | 2026-06-04 → 06-05 | Deflated Sharpe with explicit trial count + variance sensitivity, PBO/CSCV, CPCV meta-label, disjoint-window OOS. | HANDOFF_2026_06_04_ML4T_DSR, DSR_PBO_1D_CLUSTER_0604, META_LABEL_SCALP_CPCV_0604, FAVORITE_LONGSHOT_0604, F2_BASIS_OOS_0604, SCALP_OOS_PASS_0605 |

**GO decisions that predate the rigor they'd need today:**

- **Cyclops S7 X1** — declared deploy-ready (G1+G3+G4, $1, n=36) on **2026-05-16/18**, pure E0. n=36 with a multi-gate composite that was selected over many BTC-5m sleeve combinations. Never re-passed E2 (fill model) or E4 (DSR with honest trial count). **Listed as "best paper-deploy target" in CLAUDE.md — STILL LIVE as a recommendation.** Highest-priority stale GO.
- **Mint-and-sell V2** — "edge is real, expressed at slug level" (2026-05-16, E0/E1). Per-fire negative; the positive sign comes only from the `BOTH_SIDES_PARTIALS` subset (n=9–113 slugs/cell) — a **post-hoc regime split**, never revalidated under E2 fills or DSR. Still flagged "under deep-dive / deployable" in CLAUDE.md.
- **F2 directional HOLD** — "best near-term candidate" (E0). Later (E1/E2) shown to lose broadly; the alpha is an undecodable slug-selector. Correctly downgraded, but the original "deployable insight" framing lingered weeks.
- **Microstructure sleeves** (VPIN H-A, vol/Hurst, TA-mega ribbon) — passed E1 3-way splits and were written up as "deployable," but H-A's headline was later shown contaminated by late-offset tautology (see §3). The E1 standard did not catch the priced-in problem; only E2 fills did.

**Honest reading:** every E0/E1 GO that mattered was *eventually* re-tested and downgraded, EXCEPT Cyclops S7 X1 and Mint-and-sell V2, which remain in CLAUDE.md's "deployable" block without an E2/E4 pass. Those two are the live rigor-debt.

---

## 2. Errors found (severity-ranked)

### S1 — CRITICAL: maker-arb survivorship was caught only *after* deploy framing, and the same censoring pattern is not systematically guarded elsewhere
`MAKER_ARB_CENSORING_REVERSAL_0528`. The shadow engine logs a REDEEM event only for the directional **winner** (inventory→0); losers expire silently and sit forever in `residual_open`. "Settled-only (inv=0)" counted 32 winners + 9 paired, excluded all 26 losers → **+$4.44/slug reported vs −$0.41 true**. Caught, verified, reversed. **But the fix is local** (an outcome-based `settle_residuals.py` for one sleeve family); there is no project-wide invariant that every "resolved/settled-only" filter be cross-checked against outcome truth. See §4 biases for the uncaught cousins.

### S2 — HIGH: VPIN H-A "70.6% WR / +$36,587" was published as the standout deployable before the tautology was isolated
`VPIN_HAWKES_0526` §3 headlines H-A; §7 caveat 1 then admits WR climbs monotonically with offset (59%→73% as the slot empties) because at late offsets the "Hawkes signal" is just observing the move that already resolved. The report does the right thing in §7, but the §3 framing + the "Top 5 deployable" section invite reading a priced-in artifact as alpha. This is the *same* move-already-happened mechanism later formalized in E3 — it was present, footnoted, but not yet a hard gate.

### S3 — HIGH: DSR trial-count honesty is good for the *negative* results but the *positive* (exit-scalp) DSR is effectively N≈1 on a strategy that was iterated
See §3 below — the meta-label/exit DSR is run at `k_eff=1` "pre-registered," but the underlying entry filter (`entry_vwap<0.55`), exit time (+45/+60), and δ threshold were themselves tuned across the project. The DSR re-confirms the base edge but does **not** price the search that *produced* the base edge. Mitigated by the disjoint-window OOS pass (E2-grade), so the conclusion likely survives — but the DSR "prob 1.0, significant" is not the independent proof it reads as.

### S4 — MEDIUM: Mint-and-sell positive sign rests on a post-hoc subset + a 200×–10,000× unexplained wallet-PnL gap
`MINT_AND_SELL_V2_0516`. The only positive cell is `BOTH_SIDES_PARTIALS`; the model's own extrapolation misses the target wallet PnL by 200×–10,000× and the report lists three unfalsified hypotheses for the gap. A 10,000× model-vs-reality gap is a red flag that the replication is *not* the wallet's actual mechanism, yet the line stayed "deployable."

### S5 — MEDIUM: fee-model regime change retro-invalidates a swath of pre-06-03 PnL
CLAUDE.md confirms the production fee was corrected to `0.07×p×(1−p)` winner-only on 2026-06-03, superseding the earlier "2%-on-profit." Reports priced at legacy 2% (e.g. MLOFI_0526 explicitly uses `LegacyConfig`) **overstate winning-trade PnL ~$0.36–0.43/win**. Most such reports were negative anyway (so the sign holds), but any marginal "near-pass" under legacy fees should be treated as fail until re-priced.

### S6 — LOW: "more search = worse" is reported honestly, but the search harness was still run at 3000 candidates
`AUTORESEARCH_SEARCH_RESULTS_0603` correctly concludes 800→3000 made results worse (multiple-testing) and that candidate count is the wrong lever. No error in the conclusion; minor compute waste, and a good negative.

---

## 3. DSR usage — was N counted honestly?

**Negative results: YES, honestly (exemplary).**
- `DSR_PBO_1D_CLUSTER_0604` prices the **full ~400,231 per-series search** into DSR → 0/25 survivors/asset, PBO 0.56–0.89. This is the textbook-correct application and is the strongest single piece of rigor in the project.
- 415 GPU architectures (0/415), 4.8M indicator combos, 387k scalp selectors "die under realistic-variance DSR" — all count the trial budget. Correct.

**Positive result (exit-scalp): PARTIAL / pseudo-pre-registration.**
- `META_LABEL_SCALP_CPCV_0604` runs DSR "pre-reg (k_eff=1)" and "deflated (n_trials=6)" → prob 1.0, significant. **But k_eff=1 prices only the meta-model choice, not the search that found the base edge.** The base edge's own knobs — `entry_vwap<0.55`, δ≥5/≥3, exit +45/+60, BTC≫ETH asset selection, exclude-{12,17} TOD gate — were each selected from alternatives across May–June. The honest effective-N for the *strategy* is well above 1; the DSR as run does not deflate for it.
- The report is *self-aware* about this ("this only re-confirms the base edge; the meta-model is not what makes it pass") — so it is not deception, but a reader could over-trust the "prob 1.0."
- **What actually saves the exit-scalp** is not the DSR — it is the **disjoint-window OOS** (`SCALP_OOS_PASS_0605`: Mar30–Apr21, gated CI>0 on BTC/ETH/SOL/DOGE/XRP, a window not used in the search). That is the genuine out-of-sample evidence. The DSR is corroborating, not load-bearing.
- ⚠️ DSR `variance_trials` sensitivity is explicitly flagged in the toolkit notes — the "conservative ≥4×" column is the trustworthy read, and the team says so. Good.

**RS-panel "DSR 0.24" prereg:** the `rs_panel/` dir on disk contains only `backtest/ generate.py public/` — no prereg `.md` or DSR report was found locally. The 0.24 figure is cited in the audit prompt but the artifact isn't in `reports/`. **Flag: the RS-panel DSR=0.24 claim is currently unverifiable from the report tree** — if it was a pre-registered N=1 claim, confirm the prereg lock predates the result; otherwise treat as another pseudo-prereg. Cannot adjudicate without the missing file.

---

## 4. Biases catalogue

### Lookahead
- **CAUGHT (footnoted):** VPIN H-A late-offset tautology (`VPIN_HAWKES_0526` §7.1) — offset=300 reads a resolved slot. Panel construction itself is clean (EMA causal, `fire_us−1s` lookup). The *deployment* framing of late-offset cells is the risk.
- **CAUGHT (convention-level):** the `ws_s ≠ slot_start` anchor bug (CLAUDE.md) — anchoring on slot_start inflates hit-rate 25–40pp. Codified as a hard convention with verifier `_match_live_f7_v2.py`. Strong.
- **STRUCTURALLY GUARDED:** `asof_strict`, native-10Hz L25 load, cross-token spread definition — all live-mimic conventions that prevent lookahead in fills.

### Survivorship / censoring
- **CAUGHT:** maker-arb REDEEM censoring (§S1) — the famous one. Verified, reversed.
- **POTENTIALLY UNCAUGHT — flag for follow-up:**
  1. **Wallet-PnL "HOLD PnL" and cash-PnL on cataloged wallets** use whatever positions are visible on-chain; wallets that *blew up and stopped* are not in the catalog (we hunt *profitable* wallets). The entire wallet-hunt universe is a **survivorship-selected sample of winners** — the `0xcfb103c3` "failed scalper" counter-example is the only loser studied. Any "this mechanism is profitable because N wallets do it" inference inherits selection-on-the-dependent-variable bias. Not flagged as such in the synthesis.
  2. **Relay-wallet accounting** (`0xb27bc932` dumps inventory to `0xf3cfb6a6…` which merges/redeems "off the radar of this wallet's accounting"). PnL measured on the visible wallet is **incomplete** — the redeem leg lives elsewhere. The decode acknowledges the relay but the $254k/day figure is read off a wallet whose settlement leg is not in-frame. Treat magnitudes as unverified.
  3. **Mint-and-sell `BOTH_SIDES_PARTIALS` subset** — conditioning on "slugs where both sides accumulated" is itself an ex-post survival filter on favorable inventory outcomes; not audited for whether the conditioning is achievable ex-ante.
  4. **Resolutions filtering:** canonical filters out binance-resolved rows (correct), but any analysis joining only `resolutions` (chainlink, ~12–18k markets) silently drops markets that never got a clean chainlink resolution — check that dropped markets aren't systematically the losers/disputed ones. Not seen audited.

### Selection / multiple-testing
- **CAUGHT (E4):** 400k-search DSR, 4.8M-combo PBO, autoresearch asset-confound penalty (caught a fake +$0.8/tr all-BTC gate), "more search = worse" interpretation.
- **PARTIAL (E0/E1):** microstructure "Top 5 deployable" lists, TA-mega "ribbon_agrees" gate, Cyclops gate stack — selected without trial-count deflation. The ones that mattered were later re-tested; the daily-trend MA cluster was explicitly killed.
- **pseudo-pre-registration:** exit-scalp DSR k_eff=1 (§3) — the headline pre-reg does not cover the base-edge search.

### Priced-in (information already in entry price) — the dominant structural bias
- **CAUGHT and formalized:** B1 VPIN / C4 CVD / book-depth mid-window reads (89% WR, −$0.62/tr), favorite-longshot (real in print, dies on fills), 15/16 swarm Tier-1 candidates. The "move-already-happened" / "print≠fill" / "WR≠edge" rules are the project's best original methodological output.

---

## 5. Priced-in trap — precise mechanism + which signals are doomed

**Mechanism.** Polymarket up/down resolves on Chainlink at slot end. Any feature read at fire-time `t` that is *correlated with the realized intra-window move* (poly CVD, VPIN/flow-clustering, book-depth drain, microprice tilt, even Binance momentum) is correlated with the very price change that the market maker has *already* moved the entry vwap to reflect. So: high conditional WR (you're betting the side that's winning) but the entry price already costs you the expected edge → $/tr ≈ 0 or negative after the ask-walk + fee. **WR measures "did the favored side win," $/tr measures "did you get paid more than you paid" — these decouple exactly when the signal is co-incident with priced information.**

**Structurally doomed classes (co-incident with the priced move):**
- Mid-window order-flow read off the *poly* book (VPIN, CVD, MLOFI, OBI, depth-decay) — the poly book IS the price; reading it to predict the poly price is circular.
- Binance price-technicals at `ws_s` (RSI/EMA/momentum) — `EFFICIENT_MARKET_FINDING_0528`: the poly price already integrates them; AUC≈0.51.
- Late-offset anything (the slot is over).

**NOT necessarily doomed (the whitespace — see §7):** signals that lead the priced move at a horizon the maker hasn't yet repriced, or on an instrument whose information isn't yet in the poly book: cross-venue lead-lag (Kalshi/CEX moving *before* poly), fresh liquidation cascades (forced flow not yet repriced), pre-window informed-flow that selects *which slug* before the window opens (a SELECTION target, not a within-window direction target — autoresearch W1 explicitly flags this as the untested target).

**Is "execution not prediction" fully justified?** As a statement about *our tested signal set at the within-window horizon*, yes — it's well-evidenced (efficient-market capstone + every swarm/microstructure death). As a *universal* claim ("prediction can never work here"), **no, it is overclaimed.** It was never tested at (a) the *cross-venue lead-lag* horizon with synchronized Kalshi/poly tapes, (b) the *pre-window slug-selection* horizon, or (c) on *forced/non-informed flow* (liquidations) with fresh data. The F2 wallet demonstrably has a profitable slug-*selector* we could not decode — existence proof that a prediction-shaped edge exists and is simply outside our current feature set.

---

## 6. Wallet-hunt residual value

**Was PnL measurement sound?** Partially.
- **Method is reasonable:** Alchemy `getAssetTransfers` cash PnL + `HOLD PnL` (hold-to-settlement at real 0.07 fee) as a comparator to detect scalp-vs-hold. Fee model is the canonical curve. Good.
- **Three soundness gaps:** (1) relay-wallet settlement legs are off-frame → magnitudes (esp. the $254k/$344k headline figures) are unverified; (2) the universe is survivorship-selected winners; (3) "HOLD PnL" assumes taker fills at print, which the project itself later proved unachievable (print≠fill) — so HOLD PnL on a maker wallet is the *wrong side of the trade* (efficient-market capstone makes exactly this point: "we were modeling the wrong side").

**Honest residual value of the line:**
- ✅ **Confirmed reproducible mechanism #1 — maker pair-arb at slot-open** (`WALLET_HUNT_SYNTHESIS_0529`, 6+ independent wallets). Real but it IS the mint-and-sell/maker family — and maker-entry was separately proven to die on adverse selection in the scalp context. Reproducible only with true maker fills + rebate; not via taker.
- ✅ **Confirmed reproducible mechanism #2 — Chainlink oracle snipe (late-slot)** (`WALLET_HUNT_SYNTHESIS_0529`): read RTDS in final 30–90s, ~87% accurate at T−30s before CLOB converges; rest a maker @ ~0.985. **This is the most interesting unexploited confirmed mechanism** — it is execution-flavored (maker fill near settlement) but driven by a real oracle-latency information edge, and it was NOT killed. Gated only on: resting-maker fills + a live CL RTDS WS feed. **Recommend: this is the wallet-hunt line's best residual; it deserves an E2/E4 pass it never got.**
- ❌ **F2 slug-selector** — confirmed-to-exist, confirmed-unreproducible from canonical (L25+binance+trades). Honest dead-end *until* the CLOB WS event tape + cross-venue basis exist. Residual value = it tells you a prediction edge exists you can't yet see.
- ➖ Mint-and-sell direct replication — sign-correct, magnitude-wrong by 200×–10,000×; not the real mechanism. Low residual.

**Net:** the wallet-hunt line's durable output is two confirmed *execution* mechanisms (slot-open maker pair-arb, late-slot oracle snipe) and one existence-proof of an undecoded predictive slug-selector. The oracle snipe is the under-exploited gem.

---

## 7. What was done RIGHT

- **Fill-realistic revalidation as a hard gate** (E2). "WR≠edge" and "print≠fill" are genuinely good, transferable methodology that caught every microstructure mirage. This is the project's strongest habit.
- **DSR/PBO on the negatives with honest trial counts** — pricing the 400k/4.8M search into DSR and *accepting* 0 survivors is rare discipline. Most shops would have shipped a 1.10-Sharpe MA cluster.
- **The maker-arb reversal itself** — finding, verifying (99.64% REDEEM↔chainlink agreement cross-check), and *publicly reversing a deployed conclusion* is exactly right.
- **Convention codification** — `ws_s` anchor, native-10Hz L25, cross-token spread, fee-curve correction are all written as hard rules with verifiers, preventing recurrence.
- **Disjoint-window OOS** for the surviving exit-scalp — the one positive claim is backed by genuinely held-out data, not just in-sample DSR.
- **Self-awareness in the reports** — the meta-label report says outright the meta-model adds nothing; the mint-and-sell report admits the 10,000× gap. Negative/limiting findings are not buried.

---

## 8. Signal classes NEVER tried (whitespace feed)

Ordered by plausibility of escaping the priced-in trap:

1. **Cross-venue Kalshi↔Polymarket lead-lag (synchronized tapes).** Kalshi data only arrived ~06-06; the deep-dip arb was found but gated on ask-depth. Lead-lag direction (which venue moves first on crypto up/down) has **never** been tested. If poly lags Kalshi even 1–2s, that's a prediction edge the poly maker hasn't repriced. **Highest-value whitespace.**
2. **Polymarket CLOB WS *event tape* (not aggregated L25 snapshots).** Repeatedly named as the missing data for the F2 slug-selector and for pre-window informed-flow. We have L25 snapshots; we do NOT have the raw order add/cancel/match event sequence. Queue position, fleeting-order detection, and the slug-SELECTION-before-window target all live here. W1 explicitly flags this as the untested target.
3. **Funding / OI regime conditioning.** `cex_futures_ticker` (funding_rate, open_interest, mark/index) has existed since ~06-01 across 4 exchanges × 6 perps and was used only as a few TIER-2 *gates* in the swarm (mostly untested on fills). A funding/OI *regime* model (not a within-window read) on which slugs to even play is unexplored.
4. **Liquidation cascades with FRESH data.** A1 (HL short-liq 60s) was the *only* swarm survivor as a real directional lean — but HL data was stale at May 27 and it was underpowered (t≈0.4). Forced liquidation flow is non-informed and may not be pre-priced. Re-run with current `cex_futures_liquidations` + fresh HL. **Underpowered, not dead — re-test.**
5. **Late-slot oracle-latency snipe (the wallet mechanism #2).** Confirmed in wallets, never backtested by us. Maker @ ~0.985 + live CL RTDS WS.
6. **Cross-asset / BTC-leads-alt at depth.** Seesaw / correlation-break gates were TIER-3 and barely touched; BTC microstructure leading ETH/SOL/DOGE poly slugs is untested as a *selector*.
7. **News/event-driven** — never attempted; out of current data scope but a real whitespace for the 15m horizon.
8. **Inventory/whale-wallet front-of-flow** — we cataloged the whales but never tested trading *ahead of* their known fire signatures (the F2/mempool-monitor idea from F2_FINAL_VERDICT Phase 3, never built).

**Bottom line for the whitespace report:** "efficient at every scale" is proven only for *within-window reads of our existing feature set*. The four classes that could carry a real predictive edge — cross-venue lead-lag, CLOB event-tape slug-selection, fresh forced-flow (liquidations), and the oracle-latency snipe — were either never tried or are underpowered, not refuted.

---

*Artifacts referenced: HANDOFF_2026_06_04_ML4T_DSR, MAKER_ARB_CENSORING_REVERSAL_2026_05_28, META_LABEL_SCALP_CPCV_2026_06_04, DSR_PBO_1D_CLUSTER_2026_06_04, F2_BASIS_OOS_2026_06_04, FAVORITE_LONGSHOT_2026_06_04, NEW_EDGE_RESEARCH_2026_06_01, EDGE_VALIDATION_TIER1_2026_06_01, WALLET_HUNT_SYNTHESIS_2026_05_29, WALLET_STRATEGIES_DECODED_2026_05_17, F2_FINAL_VERDICT_2026_05_18, DECODE_SYNTHESIS_2026_05_28, MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16, AUTORESEARCH_W1_FINDINGS_2026_06_03, AUTORESEARCH_SEARCH_RESULTS_2026_06_03, VPIN_HAWKES_2026_05_26, VOL_HURST_2026_05_26, MICROPRICE_2026_05_26, MLOFI_2026_05_26, LEE_MYKLAND_2026_05_26, TA_INDICATORS_MEGA_RUN_2026_05_23, VBT_MEGA_SWEEP, EFFICIENT_MARKET_FINDING_2026_05_28. RS-panel DSR=0.24 prereg artifact NOT found in reports/ — unverifiable.*
