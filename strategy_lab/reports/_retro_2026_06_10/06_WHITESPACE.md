# 06 — WHITESPACE: UNTRIED EDGE CLASSES for 5m/15m crypto up-down binaries (Poly + Kalshi)

**Date:** 2026-06-10
**Author role:** senior quant researcher — map where edge can *structurally* still come from, after ~10³–10⁴ tried configs.
**Method:** (a) web research on binary-option MM / short-expiry digital pricing, Poly/Kalshi microstructure, perp funding/OI/liq, cross-venue arb, event-window HFT, toxic-flow detection; cross-referenced against (b) the project's tried-and-dead list and the 05_DATA_FEE / 03_DIRECTIONAL audits.

**One-line thesis:** every *prediction* angle from the price/flow tape is dead (priced-in trap, deflation-killed). The only surviving A-grade edge is **execution** (window-open lag-taker exit-scalp). The untried whitespace is therefore almost entirely **non-prediction**: (i) the maker-rebate *circular economy* Polymarket built explicitly to pay LPs (a subsidy, not a forecast), (ii) **settlement-mechanics / oracle-determinism** in the last seconds of the window (certainty, not prediction), (iii) **cross-venue Poly↔Kalshi** structural fragmentation (law-of-one-price violations that don't converge), and (iv) **counterparty-flow / adverse-selection-avoidance** as a *maker* rather than a taker. These are different *kinds* of edge than everything that died.

---

## 1. EDGE-CLASS TAXONOMY — where can edge structurally come from?

Pricing this like a desk: in a binary up-down market there are exactly six places an edge can live. Map each to what we've tried.

| # | Edge class | Source of profit | Our status |
|---|---|---|---|
| **A. Latency / information** | You know the outcome (or the next book state) before the counterparty reprices. | **Lag-taker exit-scalp = ALIVE** (binance leads poly book 5–35s at open). **Oracle-latency snipe at T-30s = ALIVE but never backtested.** Predictive TA/ML/flow = ALL DEAD (priced-in). |
| **B. Liquidity / inventory provision** | You quote two-sided, earn the spread + **rebate income**, manage inventory; profit from uninformed flow net of toxic flow. | **Maker ENTRY = "dead" (adverse selection)** — but that conclusion PREDATES the rebate-as-income economics and never modeled the rebate. **Maker EXIT = flagged NEXT #1, untried.** Mint-and-sell rebate flow = partially understood, not deployed. **THIS CLASS IS THE BIGGEST UNTRIED WHITESPACE.** |
| **C. Settlement mechanics** | The *rules* of resolution create a deterministic or near-deterministic edge independent of forecasting. | **Oracle-determinism slug selection = real but 3–12% fill, underpowered.** Late-slot oracle snipe = wallet-decoded 87%@T-30s, NEVER backtested. **Pin/gamma dynamics near expiry = UNTRIED entirely.** |
| **D. Counterparty flow** | You identify *who* is on the other side (toxic vs uninformed) and trade accordingly — or avoid being the patsy. | VPIN/CVD/OFI as a *direction predictor* = DEAD (priced-in trap). But VPIN as a **maker shut-off / toxicity gate** (don't quote when flow is toxic) = UNTRIED. Slug-selector decode (F2) = blocked on CLOB WS tape. |
| **E. Cross-venue** | Same event priced differently across Poly/Kalshi/CEX-implied; capture the spread or the convergence. | **Poly×Kalshi deep-dip arb = ALIVE, gated on Kalshi depth.** CEX-implied-probability vs poly mid = UNTRIED as a *fair-value anchor* (only tried as direction predictor). Same-venue two-sided = dead (overround 1.02). |
| **F. Structural / behavioral** | Deadline effects, auction-like flow acceleration, fee-curve geometry, calendar/roll effects. | **Window-close flow acceleration = UNTRIED.** Fee-curve geometry (fee peaks at 50%, ~0 at extremes) as an entry filter = UNTRIED. |

**The pattern:** we have exhaustively mined class A-prediction and D-prediction (both dead). We have barely touched **B (provision-with-rebate), C (settlement mechanics beyond the one snipe), E (cross-venue fair value), and F (structural)** — and the literature says those are exactly where the *structural* edge in binary MM lives.

---

## 2. PER-CLASS DETAIL — tried? result? if untried: hypothesis / data / capacity / risk

### A. Latency / information

**A1. Window-open lag-taker exit-scalp** — TRIED, **ALIVE (A-grade, deployed).** The one real edge. Not whitespace; baseline.

**A2. Oracle-latency snipe at T-30s** — wallet-decoded 87% accurate, **NEVER backtested.** This is a class-C settlement edge really (see C1); listed here because it's a *latency* read of the same Chainlink feed that settles. **The open-source `oracle-lag-sniper` repo (JonathanPetersonn) targets exactly this on 15-min BTC/ETH/XRP/SOL** — independent confirmation the edge exists and the ~55s repricing lag is real. UNTRIED in our backtest harness. See C1.

**A3. Predictive TA / ML / order-flow direction** — TRIED, **DEAD** (coin-flip at ws_s; priced-in trap on flow; 0/415 GPU; Kronos 52.9%). Do not revisit.

**A4. Next-book-state prediction (not price, BOOK)** — **UNTRIED as distinct from A1.** A1 predicts the *underlying* leads the *token price*. A distinct edge: predict the **poly book's own next state** (imminent quote pull / refill) from the trades tape, to time the exit *fill* better. Literature: cancellation is the maker's primary toxic-flow defense ("nanosecond game"); a refill/pull is forecastable from recent take pressure. *Hypothesis:* condition the +60s exit on a book-pull-imminent signal to capture an extra few cents on the sell. *Data:* have (L25 10Hz + trades). **No new data needed.** *Capacity:* tiny (improves an existing edge, doesn't create one). *Risk:* overfitting the exit; must be DSR'd as a modification to the scalp, not a new strategy.

### B. Liquidity / inventory provision — **THE WHITESPACE**

**B1. Maker ENTRY** — TRIED, marked "dead (adverse selection)." **⚠️ THE DEATH PREDATES THE REBATE ECONOMICS.** Web research is unambiguous: as of the V2 fee schedule (Mar 30 2026), **crypto 15-min markets charge a taker fee peaking at ~3.15% at 50¢, 100% of which funds a daily maker rebate; makers pay $0 and the rebate is INCOME.** A maker filling at *flat mid with zero spread P&L is still net-positive on rebate alone.** Our maker-entry death test almost certainly modeled spread-capture-minus-adverse-selection and **never added the rebate term.** **RE-OPEN with rebate income modeled.** *Hypothesis:* at the extremes (entry near 0/100¢ where the taker fee — and thus toxic-taker pressure — is *lowest*, and where binary delta is flattest so adverse selection per fill is bounded), resting maker orders earn rebate + occasional spread and the adverse-selection bleed is small enough to be net-positive. *Data needed:* the **per-market rebate share** (crypto = 20% per docs; verify on the Polymarket account dashboard — CLAUDE.md already flags "re-validate rebate share"); **queue position** (← the structural gap: needs **Poly CLOB WS event tape**, not collected). Without queue truth, fills are optimistic (BACKTEST_VS_SHADOW_GAP §2.1 warns). *Capacity:* this is how the whale wallets make $10k–$344k/day — **large** if real, capacity = your share of executed maker liquidity per market. *Risk:* adverse selection at 50¢ (where toxic flow concentrates) is severe; binary inventory "cannot be hedged by the underlying until settlement" (Kalshi-MM paper) — inventory risk concentrates at resolution. Mitigant: quote only the *extremes* + skew on inventory + GTD-expire before window close.

**B2. Maker EXIT with taker fallback** — flagged **NEXT #1, UNTRIED.** The handoff's own top open item. The asymmetry: exit-side selection is *favorable* (you choose when your inventory leaves), unlike maker-entry where you're adversely selected on the way in. *Hypothesis:* on the exit leg of the existing lag-taker scalp, post a maker sell (earn rebate + better price); if unfilled by +Ts, cross with a taker. Converts the +60s book-sell from a fee-paying taker exit into a rebate-earning maker exit on the fraction that fills passively. *Data:* have L25 + trades; **queue position approximated** from L25 depth-ahead (imperfect without WS event tape). *Capacity:* medium — scales the existing scalp's per-trade economics, not its fire count. *Risk:* unfilled maker orders → you hold to a worse taker price or to resolution (re-introduces the priced-in trap the scalp exits to avoid). Kill if maker-fill-rate × rebate < taker-exit-cost saved.

**B3. Mint-and-sell maker rebate flow** — replicated from whale wallets, **partially understood, not deployed.** Web research now gives the missing economic piece: **the rebate is the income, not the spread.** The old `mint_and_sell_scan.py` "80% of taker fee" bug (CLAUDE.md) systematically understated this by 30–50%. *Hypothesis:* re-run the mint-and-sell scan with the **correct rebate-as-income** model (`rebate = taker_fee_pool_share × your_executed_maker_fraction`, daily pUSD). The slug-level aggregation already flips positive in the BOTH_SIDES_PARTIALS regime; the rebate may push it cleanly positive. *Data:* have; need verified rebate share. *Capacity:* large (whale-scale). *Risk:* same adverse selection + the REDEEM right-censoring bug (audit #9) that already turned one maker "edge" into −$0.41/slug — **must book expiry-losses, not just winner REDEEMs.**

**B4. Toxicity-gated quoting (quote OFF when flow is toxic)** — **UNTRIED.** The Kalshi adverse-selection paper (41.6M trades) found **one-sided order flow (VPIN) predicts maker losses in single-name markets.** We killed VPIN as a *direction* signal — but as a **maker kill-switch** it's the textbook use: *don't quote when VPIN is high.* *Hypothesis:* run B1/B2/B3 maker strategies but suppress quoting in the top-decile VPIN windows (toxic flow incoming). *Data:* have trades tape (VPIN computable). *Capacity:* multiplier on B1–B3, not standalone. *Risk:* VPIN's own lag; the toxic window may already be the profitable rebate window. Cheap to test as an overlay.

### C. Settlement mechanics

**C1. Late-slot Chainlink oracle-determinism snipe (T-30s to T-5s)** — wallet-decoded **87% accurate at T-30s, NEVER backtested.** This is the single highest-EV *untried* item with data on hand. Web research strongly corroborates: Chainlink Data Streams settle the window; the book reprices in **~55s on average**; **15–20% of windows resolve on the final-10s move**; blockchain confirmation (2–5s) caps true last-5s, so **aim T-15 to T-30s**. The `oracle-lag-sniper` repo is a live existence proof. *Hypothesis:* at T-30s read `chainlink_rtds` (1Hz, on disk) vs the window strike; if |move| > threshold (outcome near-certain), take the cheap winning token before the book fully reprices. *Data:* **all on disk** — chainlink_rtds 1Hz + L25 book + resolutions. **NO new data, NO new collection.** *Capacity:* limited by book depth at T-30s and the 3–12%-fill problem that hit oracle-determinism slug-selection — but this is a *taker* snipe (cross the book), not a maker placement, so fill is better. *Risk:* the V2 dynamic fee was *designed to kill this* (3.15% at 50¢) — BUT at T-30s with a near-certain outcome the token is far from 50¢ (cheap winner ≈ 0.7–0.9), where **the fee curve is LOW** (fee ~0 at extremes). The fee geometry actually *protects* the late snipe while killing the 50¢ latency arb. **This is the key untested insight.** Must price with the correct fee curve at the *actual* entry vwap (not 50¢).

**C2. Pin/gamma dynamics near the strike at expiry** — **UNTRIED entirely.** Binary delta → Dirac spike as t→0 with spot near strike; MM bid-ask blows out ("0DTE but worse"). *Hypothesis:* when, at T-Ns, spot is *pinned within ε of the window strike*, the poly book is maximally uncertain (≈50¢) and spreads widen — this is the *opposite* regime to C1 (no determinism). Two sub-edges: (a) **avoid** — gate the scalp/snipe OFF in pin regime (it's pure noise, the final-10s coin flip); (b) **provide** — in pin regime the spread is widest, so *maker* rebate-per-fill is highest if you can survive the gamma. *Data:* have (chainlink_rtds + L25). *Capacity:* (a) is a filter (small), (b) is dangerous (negative gamma at the spike). *Risk:* (b) is the worst inventory risk in the whole taxonomy — the Dirac-delta blowup. Test (a) the avoidance filter first; treat (b) as research-only.

**C3. Oracle-determinism slug SELECTION** — TRIED, **real but 3–12% fill, underpowered.** Not whitespace; the fill problem is the wall. C1 (late taker snipe) is the better-fill cousin.

### D. Counterparty flow

**D1. VPIN/CVD/OFI as direction** — TRIED, **DEAD** (priced-in trap, WR≠edge). Done.

**D2. VPIN as maker toxicity gate** — see B4. **UNTRIED, recommended as an overlay.**

**D3. Slug-selector decode (what F2 knows)** — blocked on **Poly CLOB WS event tape** (adds/cancels/queue), not collected. Structural gap; can't progress without forward collection (audit acquisition #2). Untriable today.

### E. Cross-venue

**E1. Poly×Kalshi deep-dip arb (sum<0.95)** — TRIED, **ALIVE (+2.7–6.6¢/set), gated on Kalshi ask-depth verification.** Web research validates the *class*: Poly/Kalshi diverge >5pp ~15–20% of the time, windows persist multi-second-to-multi-minute (vs microseconds in TradFi), and academic work (LOOP-violation paper) argues convergence is **structurally not guaranteed** — the spread is the friction. Not whitespace (already alive); just needs the depth export. **HIGH priority to unblock.**

**E2. CEX-implied probability as a fair-value anchor for the poly MID** — **UNTRIED in the form that matters.** We tried CEX→poly as a *direction predictor* (dead) and cross-exchange basis (F2, negative). But the **PolySwarm latency-arb framework** derives a **log-normal CEX-implied probability** and trades poly when poly's mid is stale vs that fair value. *Hypothesis:* compute `P(up) = Φ((ln(K/S) ...)/σ√τ)` from binance spot + realized σ at each second; when poly mid deviates > threshold from this model fair value (and the deviation is the *stale* direction, not a genuine info event), fade poly toward fair value. This is **fair-value MM, not direction prediction** — the distinction that killed the predictors. *Data:* have (1s klines + L25). *Capacity:* medium; competes with the same bots compressing this (3–5%→1–2%). *Risk:* the V2 fee at 50¢ kills the naive version; only viable away from 50¢ or as a maker (rebate-funded). Distinguish "stale" from "informed" deviation (the toxic-flow problem). Overlaps C1 near expiry.

**E3. Three-way Poly/Kalshi/CEX-binary triangulation** — **UNTRIED.** If Crypto.com / other venues run crypto binaries, a third leg tightens the no-arb box. *Data:* not collected (no third-venue feed). Low priority until E1 depth is solved.

### F. Structural / behavioral

**F1. Window-close flow acceleration (auction analogy)** — **UNTRIED.** Equity-auction literature: order submission/cancellation *accelerates* into a fixed deadline ("human behavior faced with a deadline"); some venues *randomize* the clear to defeat speed. Poly's 5m/15m windows have a **hard, non-randomized expiry** → flow should accelerate predictably into T-0. *Hypothesis:* characterize the T-30→T-0 flow/▵spread profile; the predictable late-window liquidity surge is a better *exit* window for inventory (sell into the deadline crowd) and a worse *entry* window. Pairs with C1/C2. *Data:* have (trades + L25, timestamped to window). *Capacity:* improves exit timing of existing edges. *Risk:* confounded with C1/C2; isolate the *liquidity* effect from the *determinism* effect.

**F2. Fee-curve geometry as an entry/exit filter** — **UNTRIED, near-zero cost.** The V2 taker fee peaks ~3.15% at 50¢ and → ~0 at the extremes. *Implication:* any taker entry near 50¢ pays a punitive fee; any taker entry/exit at the extremes is nearly free. **Every taker strategy should prefer extreme-priced fills.** *Hypothesis:* add a hard filter — taker-enter only when |vwap−0.5| > δ (fee-cheap zone); this *mechanically* favors the C1 late-snipe (cheap winner) and *penalizes* mid-window 50¢ scalps. *Data:* none new — it's a fee-aware re-pricing of existing backtests. *Capacity:* a filter, not a strategy. *Risk:* none — it's just pricing the actual fee correctly (audit #1 already says many backtests misprice fees). **Do this as hygiene on every other experiment.**

**F3. Perp funding/OI/liquidation-cascade short-horizon predictor** — **UNTRIED on these markets** (we have cex_futures funding/OI/liq from ~May 30, and liq from gate+okx). Literature: extreme funding + rising OI + concentrated leverage → fast-resolving liquidation cascade (minutes), often *reversing* the crowded side. *Hypothesis:* a liq-cascade in progress during a 5m/15m window is a rare *genuine-information* event where the poly book may lag the violent spot move (a class-A latency edge during a specific regime, not a TA predictor). *Data:* cex_futures_ticker (funding/OI) + liquidations, but **only since ~May 30** (audit #12) and **no pre-May-30 history** (binance_metrics dead). Thin sample. *Capacity:* rare-event, low frequency. *Risk:* (a) tiny sample → underpowered; (b) this is dangerously close to the dead "predictive flow" class — must be framed as *latency during cascade* (book lags spot) not *funding predicts direction*. Lowest-conviction of the untried set; listed for completeness.

---

## 3. RANKED TOP-8 UNTRIED EXPERIMENTS

Ranked by `(EV if real) × P(real) / effort`, conditioned on data-on-hand. Effort S/M/L. Each has a falsifiable kill-criterion.

| # | Experiment | Class | Effort | Why ranked here | KILL criterion |
|---|---|---|---|---|---|
| **1** | **Late-slot oracle-determinism TAKER snipe (T-30→T-15s), priced with the REAL fee curve at the actual extreme vwap.** Read chainlink_rtds vs strike; if outcome near-certain, take cheap winner. | C1/A2 | **S** | All data on disk (rtds 1Hz + L25 + resolutions). 87% wallet-decoded, never backtested. Fee curve *protects* it (cheap winner = low fee). Highest EV-per-effort untried item. | Net $/tr ≤ 0 after correct fee + 85ms latency + native-10Hz fill + DSR(trial-counted). Or fill-rate so low (book empty at T-30s) it's the underpowered 3–12% wall again. |
| **2** | **Re-open MAKER-ENTRY with rebate-as-income modeled, restricted to fee-cheap extremes.** The death predates the rebate economics. | B1 | **M** | Biggest structural whitespace. Rebate makes flat-mid fills net-positive per docs. But needs verified rebate share + queue approximation. | With verified rebate share + L25 depth-ahead queue proxy: per-slug net (spread + rebate − adverse-selection − expiry-loss, LOSSES BOOKED per audit #9) ≤ 0. |
| **3** | **Maker-EXIT-with-taker-fallback on the existing scalp.** Post maker sell at +Ts, cross if unfilled. | B2 | **M** | The handoff's own NEXT #1. Exit-side selection is favorable (not adversely selected). Scales the one real edge. | Maker-fill-rate × rebate-saved < taker-exit-cost; OR unfilled-hold reintroduces priced-in-trap loss. Net $/tr ≤ current taker-exit scalp. |
| **4** | **Fee-curve-geometry filter (`|vwap−0.5|>δ`) applied as hygiene across ALL taker backtests + the scalp.** | F2 | **S** | Near-zero cost; corrects a real mispricing (audit #1). Mechanically improves C1 and penalizes 50¢ noise. Should run *before/under* #1 and the scalp re-base. | N/A — it's a pricing correction, not a strategy. "Fails" only if correctly-priced fee makes an existing edge vanish (which is information, not failure). |
| **5** | **CEX-implied-probability fair-value MM (log-normal P(up) from 1s klines + realized σ), fade STALE poly-mid deviations, maker-side / extremes only.** | E2 | **M** | PolySwarm-validated framing; reframes the dead "CEX→poly direction" as fair-value (the distinction that killed predictors). | Can't separate stale-deviation from informed-deviation → trades into toxic flow; net ≤ 0 after fee; or arb already compressed below fee. |
| **6** | **VPIN maker-toxicity KILL-SWITCH overlay** on experiments 2/3/5. Suppress quoting in top-decile VPIN windows. | B4/D2 | **S** | Kalshi paper: VPIN predicts maker losses in single-name markets (these ARE single-name). Cheap overlay; multiplies any maker edge. | Gating top-decile VPIN does not improve maker net $/slug (i.e., toxic window ≈ profitable window). |
| **7** | **Pin-regime AVOIDANCE filter** (spot within ε of strike at T-Ns → gate scalp/snipe OFF) + characterize close-flow acceleration. | C2a/F1 | **S** | Pin regime = pure final-10s coin flip + widest spread; literature says avoid. Likely improves Sharpe of #1 and the scalp by cutting noise fires. | Excluding pin-regime fires does not raise CI/Sharpe of #1 or the scalp (i.e., pin fires aren't disproportionately losers). |
| **8** | **Liquidation-cascade latency window** (during a cex-futures liq cascade, poly book lags violent spot → take the lagged side). | F3/A | **L** | Genuine-info regime where the latency edge re-appears; but thin data (cex_futures since ~May 30, gate+okx liq only) and adjacent to the dead predictive-flow class. | Sample too small for DSR (n<~50 cascades in window); or net ≤ 0; or it's just the priced-in flow trap re-skinned. **Expect this to die — included for completeness, lowest conviction.** |

**Cross-cutting prerequisites (do once, benefit all):**
- **(P1)** Fix the fee model on the loser leg (audit §2 — engine_v2 overcharges losers; use winner-only `pnl_07`). **(P2)** Apply F2 fee-geometry pricing. **(P3)** Native 10Hz L25 (`subsample_1hz=False`). **(P4)** DSR with the full search counted as trials — every maker/snipe experiment goes through it (directional line's #1 lesson). **(P5)** For any maker experiment, **book expiry-losses** (audit #9 censoring) before reading any net.

---

## 4. SOURCES

Binary/digital MM & short-expiry pin/gamma:
- Digital Option Market Making on Prediction Markets — https://www.research.hangukquant.com/p/digital-option-market-making-on-prediction
- ImpliedOptions — Gamma Risk: Why Options Accelerate Near Expiration — https://impliedoptions.com/blog/gamma-risk-why-options-accelerate-near-expiration
- MenthorQ — Pin Risk around Op-Ex — https://menthorq.com/guide/pin-risk-around-op-ex/
- FlashAlpha — 0DTE Gamma Exposure & Pin Risk — https://flashalpha.com/articles/0dte-gamma-exposure-pin-risk-intraday-options-analytics
- arXiv 2510.15205 — Toward Black–Scholes for Prediction Markets: Market-Maker's Handbook — https://arxiv.org/html/2510.15205v1

Polymarket microstructure, fees & rebates:
- Polymarket Docs — Maker Rebates Program — https://docs.polymarket.com/market-makers/maker-rebates
- Polymarket Docs — Trading (skew/cancel/GTD/kill-switch) — https://docs.polymarket.com/market-makers/trading
- The Block — Polymarket adds taker fees to 15-min crypto to fund rebates — https://www.theblock.co/post/384461/
- Finance Magnates — Dynamic Fees to Curb Latency Arbitrage (fee peaks ~3.15% at 50¢) — https://www.financemagnates.com/cryptocurrency/polymarket-introduces-dynamic-fees-to-curb-latency-arbitrage-in-short-term-crypto-markets/
- StartPolymarket — Market Making: Earn the Spread (rebate-as-income) — https://startpolymarket.com/strategies/market-making/

Oracle settlement latency / snipe:
- GitHub — oracle-lag-sniper (Chainlink↔Polymarket CLOB lag, 15-min BTC/ETH/XRP/SOL) — https://github.com/JonathanPetersonn/oracle-lag-sniper
- Chainlink — Low-Latency Oracle (pull-based, pre-settlement privacy / "last look") — https://blog.chain.link/low-latency-oracle-solution/
- BlockEden — Chainlink Data Streams power Polymarket 5-min settlement — https://blockeden.xyz/forum/t/786
- Medium (Benjamin) — Edges in Polymarket 5-min crypto: last-second dynamics (~15–20% resolve on final 10s) — https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-...

Cross-venue Poly↔Kalshi arb:
- arXiv 2601.01706 — Semantic Non-Fungibility & Violations of the Law of One Price in Prediction Markets — https://arxiv.org/html/2601.01706v1
- arXiv 2604.03888 — PolySwarm: Multi-Agent LLM for Prediction Market Trading & Latency Arbitrage (log-normal CEX-implied prob) — https://arxiv.org/abs/2604.03888
- AhaSignals — Cross-Platform Arbitrage Kalshi/Polymarket (>5pp divergence 15–20% of time) — https://ahasignals.com/research/prediction-market-arbitrage-strategies/

Adverse selection / toxic flow / counterparty:
- Stanford Law — Adverse Selection in Prediction Markets: Evidence from Kalshi (41.6M trades; VPIN predicts maker losses in single-name) — https://law.stanford.edu/2026/04/21/adverse-selection-in-prediction-markets-evidence-from-kalshi/
- arXiv 2407.04510 — Unwinding Toxic Flow with Partial Information — https://arxiv.org/pdf/2407.04510
- Easley/O'Hara — Flow Toxicity and Liquidity in a High Frequency World (VPIN) — https://www.stern.nyu.edu/sites/default/files/assets/documents/con_035928.pdf
- PredictionDocs — Market Making Strategies (inventory skew, kill-switch) — https://predictiondocs.com/developers/ai-bots/market-making

Event-window / auction HFT & perp derivatives:
- arXiv 2404.18200 — Mean Field Game of High-Frequency Anticipatory Trading (Round-Tripper) — https://arxiv.org/pdf/2404.18200
- arXiv 2401.06724 — Equity auction dynamics: latent liquidity with activity acceleration — https://arxiv.org/html/2401.06724v1
- Medium/XT — Bitcoin Futures Microstructure: Liquidation Cascades, Funding Regimes, OI Signals — https://medium.com/@XT_com/bitcoin-futures-market-microstructure-...
- Gate Wiki — Funding/OI/liquidation data to predict price — https://www.gate.com/crypto-wiki/article/how-to-interpret-crypto-derivatives-market-signals-...
