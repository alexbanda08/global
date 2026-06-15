# Edge Gap Analysis — Polymarket Crypto UP/DOWN 5m/15m
**Date:** 2026-06-09  
**Author:** Synthesis lead (cross internal INTERNAL_AUDIT × SHADOW_COVERAGE × external research)  
**Status:** Reference document — update after each major session

---

## 0. Purpose

This document maps the full explored edge space, identifies genuine gaps (approaches not yet tried
that are feasible with existing data and do not violate the learned failure rules), ranks them by
promise × feasibility × novelty, and specifies the next 3 concrete experiments.

---

## 1. Learned Failure Rules (Hard Guardrails)

Before evaluating any idea, apply these filters. Any idea violating one is a dead end in disguise.

| Rule | Pattern it kills |
|------|-----------------|
| **WR ≠ EDGE** | High win-rate → high entry vwap → fee drag kills $/tr. Always measure $/tr with 0.07-curve real fills. |
| **PRINT ≠ FILL** | Trade prints are NOT achievable. L25 ask-walk (engine_v2, $25, 85ms) is mandatory. |
| **MAKER ≠ TAKER for momentum capture** | Resting bid fills on losers (adverse selection). Rebate < selection loss. EXCEPTION: maker EXIT is favorable selection — keep testing. |
| **PRICED-IN TRAP** | Any mid-window Poly signal (CVD, VPIN, book-depth-decay, cross-token price-sum) correlates with realized move → high WR but vwap absorbs it. All Poly-native flow signals mid-window are trap-suspects. |
| **DSR DEFLATION** | ≥1k searched candidates need Deflated Sharpe Ratio with conservative n_trials. WR/Sharpe inflate with search breadth. |
| **SURVIVORSHIP / CENSORING** | Never measure PnL on "settled inv=0" or "winner-only" subsets. Count all losers. |
| **DIFFERENT-WINDOW OOS ONLY** | In-sample + DSR + shadow = necessary not sufficient. Only a clean disjoint date window is deflation-proof. |
| **THIN-BOOK UNFILLABILITY** | Measured backtest edge means nothing if live fill rate < 5%. Check fill rates first. SOL scalp = 0.5% fill at $25 = hard limit. |

---

## 2. Coverage Matrix

### 2A. By Strategy Category

| Category | Status | Notes |
|----------|--------|-------|
| **Intra-window exit-scalp (lag-taker, +60s)** | ✅ REAL, deployed | The only confirmed edge. OOS-validated 5 coins. |
| **Stop-loss on scalp (fill−0.10)** | ✅ REAL, deployed | +0.88/tr SIG, confirmed 3×. |
| **Time-of-day gate (exclude {12,17}, boost 22–02)** | ✅ REAL, deployed | OOS-confirmed, F2-confirmed, walk-forward stable. |
| **Maker EXIT with taker fallback** | ◐ PARTIAL | +$0.42/tr SIG on optimistic fill model. Queue-aware OOS needed. This is NEXT #1. |
| **Poly × Kalshi 15m deep-dip arb** | ◐ PARTIAL | +2.7–6.6¢/set CIs>0 at <0.95/<0.90 cost. Gated on Kalshi ask-DEPTH verification. |
| **Oracle-determinism settlement selector** | ◐ PARTIAL | Real, 100% win-rate fills, but 3–12% fill rate, CIs span 0. Needs forward power. |
| **TP@0.65 taker** | ❌ DEAD | Caps runners vs +60s. Disable live. |
| **Maker entry (resting bid)** | ❌ DEAD | Adverse selection: fill 0.36 won / 0.55 lost. Rebate < selection loss. |
| **Maker-arb (mint-and-sell V2)** | ❌ DEAD | Survivorship bias: −$0.41/slug uncensored. |
| **Directional momo (ret_2m, F7 RSI, V3/V4)** | ❌ DEAD | 215-sleeve fleet −$25.4k; live WR ≈49.6% = coin-flip. |
| **Lag-taker held to resolution (LAGV2)** | ❌ DEAD | OOS +$0.36/tr t=0.41 (not significant). ≥5bps inverts negative. |
| **Poly CVD / VPIN trade-flow** | ❌ DEAD | Priced-in trap: high WR, $/tr −$0.62 to −$1.03. |
| **ML meta-label (387k selectors, 61 features, CPCV)** | ❌ DEAD | Cannot beat delta_bps sort. DSR: 0/20 survive. |
| **GPU LSTM / 415 architectures** | ❌ DEAD | 0/415 beat Poly price. OOS acc ≈ 0.50. |
| **4.8M indicator VBT sweep** | ❌ DEAD | 0/25 survive DSR; PBO>0.5 on all 3 assets. |
| **Trailing / peg exit** | ❌ DEAD | Every trailing policy loses to fixed +60s significantly. Noise whipsaws stop. |
| **Mid-window re-fire / FVG** | ❌ DEAD | Two independent tests: flat/negative from ≥120s. Edge is open-only. |
| **Cross-asset lead-lag (BTC→ETH/SOL)** | ❌ DEAD | Paired diff ≈ 0; alts move with BTC in first 5s. |
| **Cross-timeframe arb (5m vs 15m Poly)** | ❌ DEAD | 15m token adjusts immediately to mid-window Binance price. |
| **Same-venue two-sided arb** | ❌ DEAD | Median sum_ask = 1.010; sub-1 cases are zero-size dust. |
| **Regime gates (vol/trend terciles)** | ❌ DEAD | Non-monotonic and fail coin-split OOS. delta_bps is sufficient. |
| **Low-vol gate** | ❌ DEAD | Fails coin-split: hurts BTC/ETH (the live deployment target). |
| **Favorite-longshot convergence** | ❌ DEAD | Real in print space; dies on L25 ask-walk fills (print≠fill). |
| **F2 trigger on broad universe** | ❌ DEAD | −$14k broad OOS; slug-selection alpha not reproducible from canonical. |
| **Funding rate / OI directional signal** | ❌ DEAD | IC<0.025, all p>0.05 on 5m. Slow-moving vs fast binary. |
| **Cross-exchange lead-lag** | ❌ DEAD | No venue leads Binance at 1m. Binance leads HL by 1s. |
| **Tick-level trailing stop** | ❌ DEAD | Every policy: worse than fixed +60, often significantly. |
| **Kalshi maker exit** | ❌ DEAD | Worse than taker. No Kalshi rebate; taker exit beats it at any threshold. |
| **Covered-call hedge / stop on directional** | ❌ DEAD | Hurts ROI at every threshold. |
| **Hawkes process intensity gate** | ❌ DEAD (mostly) | SOL 5m DISAGR-HAWKES DN = only survivor. Forward unconfirmed. |
| **Cyclops S7 composite BTC 5m** | ◐ PARTIAL | G1+G3+G4 pass (n=36, WR 80.6%). Window aging (Apr–May 2026). Does NOT generalize. |

### 2B. Shadow Coverage by Asset / Timeframe

| Asset | 5m | 15m | Fire rate | Note |
|-------|----|-----|-----------|------|
| BTC | ✅ Active (d3+control) | ✅ Active (d3+control) | High | Primary. Most resolved trades. |
| ETH | ✅ Active | ✅ Minimal fires | Medium | OOS-validated, accruing. |
| SOL | ~0 fires | ~0 fires | 0% | Oracle lag gate never triggers; thin books. |
| XRP | 0 fires | 0 fires | 0% | Same as SOL. Oracle lag absent. |
| BNB | 0 fires | 0 fires | 0% | Same. |
| DOGE | 0 fires | 0 fires | 0% | Same. |
| HYPE | No sleeve | No sleeve | N/A | No 1s data, no shadow sleeve. |

### 2C. Exit Mode Coverage

| Mode | Status |
|------|--------|
| Taker +60s (with stop) | ✅ Deployed, validated |
| Taker TP@0.65 | ❌ Disabled (non-edge) |
| Maker SELL@0.65 + taker fallback | ◐ First-pass SIG, queue-aware needed |
| Trailing/peg | ❌ Dead |
| Hold to resolution | ❌ Dead for scalp |

### 2D. Unexplored Entry Offsets in Live/Shadow

| Offset | Status |
|--------|--------|
| +5s | ✅ Deployed |
| +30/+45/+60/+90s | ❌ Backtest: dead. No live data needed. |
| Last 30s before resolution (oracle snipe) | ◐ Oracle-determinism T-30s: backtest shows 100% WR at n=9, underpowered |

---

## 3. Dead-End Classification by External Ideas

Many external research suggestions map to already-dead categories. Explicit rejection rationale:

| External Idea | Rejection Reason |
|---------------|-----------------|
| Intra-window taker-flow imbalance (Poly-native CVD) | **Priced-in trap** — this is exactly what C4 CVD and B1 VPIN tested (mid-window Poly flow). Internally confirmed dead ($/tr −$0.62 to −$1.03). Poly-native trade side from arXiv:2604.24366 has 59% directional accuracy from the feed — noise. |
| Cross-window momentum bleed (prior-window strike → next direction) | **DSR concern** — this IS the ret_2m signal family. The momo/F7-RSI sleeves already capture adjacent-window momentum. Confirmed dead at scale. Not structurally different from the ~50k-row momo sweep. Priced-in at the 5m horizon. |
| Dynamic fee curve exploitation (enter at p>0.80, lower fee) | **Thin-book unfillability** + **priced-in trap**. At p=0.80+ tokens are "decided" — that IS the oracle-determinism play already. The fill rate challenge (cheap-decided slugs are thin) is the same gating problem. Not a new idea. |
| Wash-trade/self-counterparty detection | **Requires new data** (on-chain OrderFilled with maker/taker wallet). Not in canonical. The proxy (L25 oscillation without net movement) is speculative. Low feasibility. |
| GEX options gamma exposure filter | **Requires Deribit OI data** — NOT in canonical. New data source (daily call to Deribit API). Regime-level (daily) signal applied to 5m binary markets: the slow/fast mismatch killed funding/OI already. |
| Polygon block-timing arb / settlement front-run | **New infrastructure** (mempool listener, contract interaction). Unknown whether Poly relayer processes redemptions before user-submitted txs. Speculative, lower priority than confirmed open leads. |
| Asymmetric cancel-window exploit (250ms taker delay) | **Low feasibility** — cancel-during-delay-window is explicitly prohibited by Polymarket CLOB. The cancel-lock makes this unexecutable as described. |
| Cross-window strike-anchor effect | Same as cross-window momentum above. The strike IS the prior window's close; any return-predictor at the 5m horizon is in the already-exhausted momo family. |
| Maker rebate wash baseline | **Low feasibility** (requires full on-chain trade tape). Academic observation does not translate to a tradeable gate with existing data. |
| Favorite-longshot bias (buying extreme longshots p<0.40) | **Already tested** — the favorite-longshot study (`FAVORITE_LONGSHOT_2026_06_04.md`) tested this exact regime. Execution mirage on L25 fills (print≠fill). Even re-slicing by entry_vwap < 0.35 won't change the structural ask-walk slippage problem. |
| Volume-weighted adverse selection (L25 depth VPIN) | **Valid new angle** but must be distinguished from the dead trade-flow VPIN. Cancellation-depth imbalance on L25 at levels 2–5 is a genuine gap. Feasibility = MEDIUM-HIGH. Included in ranked gap list below. |
| A-S framework / Glosten-Milgrom quoting | **No current quoting infrastructure**. Academic interest but requires building a full quoting engine first. Medium-term research, not a gap on the confirmed scalp edge path. |
| Samuelson effect / entry timing within window | **Already tested**: the per-offset sweep in `SCALP_NEW_EDGE_HUNT_2026_06_09` covered +1/+2/+3/+5/+8/+10/+15s. +5s is the robust plateau; anything later loses power. The Samuelson motivation does not reverse this empirical result. |

---

## 4. Genuine Gaps — Ranked Table

These are approaches NOT yet tried that are feasible with existing data and do NOT violate the hard rules.

| Rank | Gap Name | Category | Feasibility | Promise | Novelty | Why It Avoids the Common Traps |
|------|----------|----------|-------------|---------|---------|-------------------------------|
| 1 | **Queue-aware maker-exit + peg-to-ask trail** | Execution/fills | HIGH | HIGH | Medium | Directly extends the only real edge. Favorable selection (sells into strength). Queue model removes the key caveat of the existing +$0.42/tr result. Not a prediction — a fill-mechanic improvement. |
| 2 | **Poly × Kalshi deep-dip arb (Kalshi depth verification)** | Arbitrage | MEDIUM-HIGH | HIGH | Medium | Not directional prediction. Structural fee-asymmetry + cross-venue dip. Already CI>0. One concrete blocking step: re-export Kalshi jsonb book depth. |
| 3 | **CEX perp mark-spot basis as scalp entry gate** | Execution signal | HIGH | MEDIUM | Medium-High | Uses cex_futures_ticker (mark_price vs klines_1s spot close). Structurally independent from all prior signals (perp premium reflects levered positioning, not kline TA). Not mid-window, not Poly-native. Avoids priced-in trap by using CEX-side data as a confirming regime, not a direction predictor. |
| 4 | **Binance 1s taker OFI (taker_buy_base/total) as scalp entry gate** | Execution signal | HIGH | MEDIUM | High | klines_1s already has taker_buy_base/taker_buy_quote columns — direct OFI at 1s resolution, never extracted. This is CEX-side OFI at the ENTRY moment, not mid-window Poly flow. Avoids priced-in trap: using external (Binance) aggressor flow to confirm direction before Poly reprices. |
| 5 | **Oracle staleness / Chainlink freeze detection** | Execution snipe | HIGH | MEDIUM | High | chainlink_rtds + klines_1s: measure oracle update age at window close. When oracle is >30s stale + Binance has moved, resolution direction is predictable mechanically — not from prediction. Not tested internally. Avoids DSR trap (single pre-registered hypothesis, not searched). |
| 6 | **L25 depth-shape (level 2–5 ratio) as fill-quality filter** | Microstructure | HIGH | MEDIUM | High | L25 native 10Hz has 25 levels. We use only BBO + book-walk. The depth SHAPE (level-1/level-5 depth ratio; depth "hole" at levels 2–3) predicts fill slippage and exit quality. Avoids priced-in trap: not predicting direction, predicting fill mechanics. Novel application of Cont et al. multi-level OFI to binary prediction markets. |
| 7 | **CEX futures OI-delta and funding-sign gate on scalp** | Regime filter | MEDIUM | MEDIUM | Medium | cex_futures_ticker (funding_rate, open_interest, 4 exchanges). Window is short (May30+) but will accrue. Funding sign + OI-delta are structurally independent from all tested signals (Binance kline TA, Poly microstructure). Not a direction predictor — a regime gate that could sharpen the scalp without DSR concern (not searched). |
| 8 | **Hyperliquid liquidation cascade gate (rolling 5-min notional spike)** | Regime filter | MEDIUM-HIGH | MEDIUM | Medium | hyperliquid_liquidations_full has 5.27M rows, 1-year history. Never tested as a regime gate on the scalp. Sum(size×price) over [ws_s−300, ws_s] as a risk-off indicator. Avoids priced-in trap: liquidations are an external (CEX) event, not reading Poly flow. 1-year history gives statistical power. |
| 9 | **L25 spread trajectory (30s rolling spread-change before entry)** | Execution signal | HIGH | MEDIUM | Medium | We already compute cross-token spread at fire_us. We have NEVER used the DERIVATIVE of spread (is spread widening = maker withdrawal, or tightening = book consolidating?). A widening spread in the 30s before entry predicts a thin exit book at T+60s. Pure fill-mechanics, not directional. |
| 10 | **Chainlink RTDS oracle-vs-Binance deviation signal at ws_s** | Novel signal | HIGH | LOW-MEDIUM | High | chainlink_rtds gives the oracle price at 1Hz. The delta (chainlink_price_at_ws_s − Binance_close_at_ws_s) as a "oracle lag" measure has never been extracted as a per-window feature and tested against scalp outcomes. Different from the oracle-determinism study (which uses price vs strike); this is oracle vs spot as a lag measure. |
| 11 | **Order-book-depth VPIN (cancellation-depth imbalance at levels 1–5)** | Microstructure | MEDIUM-HIGH | LOW-MEDIUM | High | Distinct from the dead trade-flow VPIN/CVD. Rate of one-sided depth REMOVAL from L25 (not order arrivals). When UP-side ask depth drops faster than DOWN in the last 60s, it signals informed cancellation. Not priced-in (it's a cancellation signal, not a trade signal). Requires ~50k L25 windows. |
| 12 | **Pre-production L25-backfill OOS for scalp (Feb 21–Mar 24, trentmkelly)** | Validation | HIGH | LOW-MEDIUM | Low | orderbook_l25_backfill (BTC/ETH, 97.9M rows each). An independent 31-day OOS window for the scalp has NEVER been run on this data. The +80s timing gap affects entry but exit-scalp analysis (+60s post-fire) is well within the covered window. Pure validation, no new alpha — but confirms edge on a third disjoint window. |

---

## 5. Rejected External Ideas Already Covered by the Internal Dead-Ends

The following external ideas are well-motivated but re-discover existing dead-ends:

- **Perp basis mean-reversion timing** → effectively the funding/OI signal family (all IC<0.025 on 5m, dead)
- **Cross-platform Kalshi→Poly lead-lag (directional signal)** → prediction, expected efficient; no evidence cross-venue prices lag
- **Hawkes self-excitation on trade arrivals** → tested via DISAGR-HAWKES (dead except SOL 5m DN cell, forward unconfirmed)
- **Adaptive RL quoting (regime-aware two-sided MM)** → no quoting infrastructure exists; this is a multi-session build before first trade
- **Selective one-sided quoting (YES-overbet behavioral bias)** → requires verification of the YES-overbetting hypothesis in our specific markets first (testable via resolutions_hf, but lower priority than open confirmed leads)
- **Longshot spread premium (buy extreme longshots p<0.40)** → the favorite-longshot study already tested this and found print≠fill kills it
- **GTD order placement optimization** → execution infrastructure improvement (valid), not a new edge; should be implemented alongside the maker-exit A/B as a latency safeguard

---

## 6. Top 5 Gaps — Detailed Experiment Specs

### Gap #1: Queue-Aware Maker-Exit + Peg-to-Ask Trail

**Mechanism:** After taker entry (the confirmed scalp), rest a SELL limit order pegged to the current best-ask (not fixed 0.65). Trail as ask moves up. Fill = buyer lifts you = favorable exit-side selection (you sell into strength). If unfilled by T+60s, taker-cross at the bid (the existing baseline). Net improvement: sells at offer vs bid (the spread), earns 20% maker rebate, and avoids the runner-capping problem of fixed-0.65.

**Why it might survive where others died:**
- Not a direction predictor (avoids the priced-in trap and DSR concern from searched selectors)
- Maker EXIT has favorable selection — opposite of maker entry (resting bid filled by sellers = adverse; resting ask lifted by buyers = favorable when you're already holding the winning token)
- First-pass SIG already (+$0.42/tr, CI [+0.02,+0.82]) — the key caveat (optimistic fill model) is fixable with queue-aware simulation
- Has no look-ahead: only the fill-mechanics matter, no prediction involved

**Data needed:** L25 at native 10Hz (already in canonical, `orderbook_l25/{btc,eth,sol}`, Apr22–Jun8). BBO Mar30–Apr21 for OOS. Existing files: `maker_exit_sim_2026_06_06.py`, `maker_exit_by_tf_2026_06_06.py`.

**Experiment spec:**
1. Build queue-aware fill model: at each 1s step from fire_us to fire_us+60s, check if cumulative buy-volume at ≥ask_price EXCEEDS the ask-queue depth ahead of the new order. Fill only if a buyer clears the queue.
2. Peg logic: trail ask_price = min(current_ask, running_best_ask) re-evaluated at each L25 update.
3. Fallback: if unfilled at T+60s, taker-cross at bid_60.
4. Test on in-sample (Apr22–Jun8, L25), then OOS (Mar30–Apr21, BBO as ask-path proxy — note BBO is top-of-book only, so queue-depth is approximate; flag as caveat).
5. Apply DSR with n_trials=1 (single pre-registered hypothesis, no search). Bootstrap CI vs baseline.
6. If CI>0 survives: spec to TV agent as an A/B shadow sleeve (one sleeve maker-exit, one pure taker +60, same fire conditions).

**Robustness checks:** different peg offsets (0, +0.5¢, +1¢ above ask); different fallback thresholds (T+45s, T+60s); per-asset stability (BTC vs ETH must both improve or the effect is coin-specific noise).

---

### Gap #2: Poly × Kalshi Deep-Dip Arb (Kalshi Depth Verification)

**Mechanism:** When KX{A}15M + Poly {a}-updown-15m combined set-cost < $0.95, buy both. One side wins (96% settlement agreement); the winning set pays $1; net = gross gain − fees − basis risk. Already quantified: net +2.7¢/set at <0.95, +6.6¢/set at <0.90, ~200–240 opportunities/day. The blocking question is not the signal (confirmed CI>0) but execution: are the Kalshi ask depths at these dip moments large enough to fill?

**Why it might survive:**
- Structural fee-asymmetry (Kalshi CFTC-regulated taker fee vs Poly 0.07·p·(1−p) curve) creates persistent dips when one venue lags
- Not a direction predictor — just buying a complete set for less than its guaranteed payoff value
- Already CI>0 on 2.6 days of data; the edge is real, the gate is fill-depth

**Data needed:** `kalshi_orderbook.parquet` is in canonical but only captured `bid_size`; the `yes_bids`/`no_bids` jsonb columns were not exported. One SQL query to `storedata` DB on VPS3 to re-export the full depth jsonb from `kalshi_orderbook_v2` table.

**Experiment spec:**
1. SSH to VPS3; run: `SELECT window_id, ts, yes_bids, no_bids FROM kalshi_orderbook_v2 WHERE ts >= '2026-06-02' ORDER BY ts;` — export to parquet.
2. Parse jsonb depth: for each dip event (set-cost < 0.95), extract the Kalshi `yes_ask_size` and `no_ask_size` at the levels that make up the dip price.
3. Compute maximum fillable size at each dip moment (min of Kalshi available depth and Poly available depth at the respective ask prices).
4. Re-run `poly_kalshi_arb_2026_06_05.py` with fill-size-aware PnL: only count a dip if fillable ≥$5.
5. If median fillable depth ≥$5 at <0.95 threshold: execute a $0 paper depth-check (fire 10 arb orders at $1/set each, record fill rates), then a $100 live test.

**Robustness checks:** per-asset breakdown (SOL vs BTC vs ETH depth profiles differ); dip duration (sustained >3s dips are more fillable than transient flickers); TOD overlap (Kalshi is US-hours; arb depth may concentrate in US market hours = 13:30–20:00 UTC).

---

### Gap #3: CEX Perp Mark-Spot Basis as Scalp Entry Gate

**Mechanism:** At the moment of each scalp fire (ws_s + 5s), if the CEX perpetual futures mark price is significantly above spot (positive basis), it signals levered long conviction that preceded the Binance spot move. This is a confirming regime: the perp-led move is more likely to sustain into the Poly resolution window vs a spot-only move with flat perp basis. Not a direction predictor per se — a fire-quality gate that asks "is this leg supported by futures positioning?"

**Why it might survive where funding/OI directional died:**
- Funding rate as a direction predictor was IC<0.025 on slow-moving 8-hour cycles. The instantaneous mark-spot basis at the 1-second level is different — it captures real-time positioning delta, not the accumulated 8h funding bill.
- This is NOT predicting direction; it's gating an already-triggered scalp on a confirming structural signal. Even a weak signal (IC=0.05) is sufficient to gate (vs the DSR bar of being directionally predictive). The DSR concern applies to searched selectors; a single pre-registered hypothesis with an economic prior is a much lower bar.
- Structurally independent from all previously tested signals (Poly book, Binance TA klines, oracle).

**Data needed:** `cex_futures_ticker.parquet` (mark_price, indexed_price, ~69M rows, 4 exchanges, May30+) and `klines_1s.parquet` (spot close). Both in canonical. `asof_strict` join at ws_s.

**Experiment spec:**
1. For each scalp fire in the May30–Jun8 window: compute `basis_pct = (mark_price_at_ws_s - spot_close_at_ws_s) / spot_close_at_ws_s × 100` using Binance mark price from cex_futures_ticker (prefer Binance; fallback Bybit/Bitget/Gate for BTC/ETH).
2. Bin fires into quintiles by basis_pct. Compute $/tr per quintile (using existing scalp outcomes).
3. Pre-registered hypothesis: fires in the top basis quintile (strong positive basis) aligned with the scalp direction (Up signal + positive basis, OR Down signal + negative basis) outperform the bottom quintile.
4. Minimum threshold: ONLY proceed to shadow if CI>0 on the top quintile AND monotonic dose-response exists (quintile 1 < 2 < 3 < 4 < 5 in $/tr).
5. Caveat: May30–Jun8 is only 9 days; this is a design check, not a final test. Re-run after next canonical refresh (~Jun15) extends to ~25 days.

**Robustness checks:** exchange stability (Binance basis vs Bybit basis give same signal?); direction-conditional (basis aligned with direction vs anti-aligned); 5m vs 15m TF stability.

---

### Gap #4: Binance 1s Taker OFI as Scalp Entry Gate

**Mechanism:** `klines_1s.parquet` contains `taker_buy_base` and `taker_buy_quote` columns from Binance Vision — giving taker buy volume per second, never previously extracted. OFI (Order Flow Imbalance) = `(taker_buy_base / total_base) × 2 − 1` ∈ [−1, +1], where +1 = all volume was aggressive buy takers, −1 = all sell. If OFI is strongly positive in the 5s window before entry and the scalp signal says Up, this is a double confirmation. The hypothesis: OFI-aligned scalp fires have higher realized $/tr than OFI-anti-aligned fires.

**Why it might survive where Poly-native CVD died:**
- This is Binance CEX aggressor-side flow — NOT Polymarket-native flow (which reads the already-moved Poly price). CEX taker OFI captures the flow that CAUSES the Binance move, while Poly CVD/VPIN reads the Poly consequence of it.
- The priced-in trap applies to reading Poly signals mid-window (the move is IN the Poly price). Binance OFI at the open (first 5s) tells us whether the CEX move had genuine buy-aggression behind it or was a thin-order spike.
- arXiv:2602.00776 confirms OFI is the dominant feature in crypto futures microstructure prediction at 1-second resolution. Its application to Poly entry quality (not direction prediction) is unexplored.

**Data needed:** `klines_1s.parquet` (taker_buy_base, taker_buy_quote, open, close, volume — already in canonical, Jan1–Jun8 2026, 6 coins). This is the most data-ready new signal.

**Experiment spec:**
1. For each scalp fire: compute `ofi_5s = sum(taker_buy_base) / sum(total_base) × 2 − 1` over the 5 seconds from slot_start to slot_start+5s using `klines_1s`.
2. Compute direction alignment: `aligned = (scalp_direction=="Up" and ofi_5s > 0) OR (scalp_direction=="Down" and ofi_5s < 0)`.
3. Bin by `|ofi_5s|` quartile × alignment. Pre-registered: aligned high-|OFI| fires outperform anti-aligned in $/tr.
4. Apply to OOS window (Mar30–Apr21 BBO scalp outcomes) for deflation-proof validation.
5. Gate: CI>0 on top aligned quartile AND consistent across BTC/ETH. If passes: propose as a static gate (`|ofi_5s| > threshold AND aligned`).

**Robustness checks:** lookback window (3s vs 5s vs 10s); OFI threshold sensitivity (quartile vs percentile); per-asset (BTC vs ETH vs SOL if fires exist).

---

### Gap #5: Oracle Staleness / Chainlink Freeze Detection

**Mechanism:** Chainlink Data Streams update BTC/USD on two triggers: (a) 0.5% deviation, and (b) heartbeat (max ~10–30s between updates). During low-volatility consolidation periods, the oracle can carry the SAME price for 30–120s. At the exact window close timestamp, if the last Chainlink update was >30s ago AND Binance spot has drifted ≥0.1% in a direction, the oracle has NOT yet captured the drift. The Poly market prices the (stale) oracle view while the actual settlement will use the next oracle update (which will be in the direction of the Binance drift). This is a mechanical (non-predictive) edge — not predicting price movement, detecting guaranteed oracle catch-up.

**Why it might survive where "oracle determinism" struggled:**
- The oracle-determinism study (ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md) tested a different mechanism: |chainlink_price − strike| ≥ 15bp at T-60s as a "nearly decided" signal. That is about certainty of outcome given current oracle price.
- This is different: it detects when the ORACLE IS STALE and the spot has already moved. The oracle WILL catch up (that's how Chainlink works), so the direction of the upcoming settlement is predictable from Binance 1s klines, not from predicting price.
- The Protos article confirmed this mechanism was actively exploited ("oracle lag loophole") before Polymarket introduced dynamic fees (Jan 2026). Our job is to measure the residual gap post-fee.
- No mid-session search: single pre-registered hypothesis, so DSR concern is much lighter.

**Data needed:** `chainlink_rtds.parquet` (oracle price + timestamp, 10.97M rows, Apr22–Jun8), `klines_1s.parquet` (Binance 1s close at every second), `resolutions.parquet` (actual outcomes). All in canonical.

**Experiment spec:**
1. For every resolution event: find the last Chainlink RTDS update before the resolution timestamp. Compute: `staleness_s = resolution_ts − last_oracle_ts`, and `binance_drift_pct = (binance_close_at_resolution − oracle_price) / oracle_price × 100`.
2. Classify events: `stale` = staleness_s > 30 AND |drift| > 0.1%. Verify: does the Poly "cheap-but-lagging" side (side aligned with the drift) resolve correctly at higher-than-implied rates in stale windows?
3. Compute: for stale windows, what is the effective win rate of buying the drift-aligned Poly token at ask? Check if the post-dynamic-fee edge persists (Poly introduced dynamic fees in Jan 2026 to partially close this; test the residual).
4. Sample size estimate: staleness > 30s may be rare (~5–20% of resolution events in overnight/low-vol hours) — expect 500–2000 stale events across 47 days × 3 coins × 12 windows/hr × 24h.
5. Apply fee model: at these late windows (T-10s to T-30s), the entry vwap is high (0.85+) and the fee is low (0.07 × 0.85 × 0.15 = 0.89%). Net after fees only works if win rate > fee/(1−fee) × 100% ≈ high 90s%.

**Robustness checks:** time-of-day distribution (expect overnight clustering); staleness threshold sensitivity (30s vs 60s vs 90s); asset comparison (BTC oracle more frequently updated than ETH/SOL?).

---

## 7. Next 3 Experiments (Concrete Specs)

### EXPERIMENT 1 (This Week): Queue-Aware Maker-Exit Build

**Priority:** HIGHEST — directly extends the confirmed edge. Prior first-pass was SIG but needs the fill-model fix.

**Script to build:** `strategy_lab/directional/maker_exit_queue_2026_06_09.py`

**Steps:**
1. Load L25 for BTC+ETH at native 10Hz (`subsample_1hz=False`), filter to scalp fire slugs.
2. For each fire: extract L25 ask side from fire_us to fire_us+60s at each snapshot. Track: `queue_ahead` = cumulative ask size at prices ≤ peg_price BEFORE the fire (represents queue position). Fill condition: `buy_volume_at_>=peg_price > queue_ahead` in a 1s window.
3. Peg_price at each step = current best_ask from L25 snapshot (or min(current_ask, running_min_ask) to model a trailing peg).
4. Compare to baseline (taker at bid_60). Output: per-fire $/tr and aggregate CI.
5. OOS replication on Mar30–Apr21 BBO (queue-depth is top-of-book only → conservative approximation; flag explicitly).
6. If CIs>0 and coin-stable: write TV spec for shadow A/B sleeve.

**Success criteria:** CI lower bound > 0 on in-sample AND directionally positive (both BTC and ETH) on OOS BBO window. Both must hold before any live deploy.

---

### EXPERIMENT 2 (This Week): Kalshi Depth Re-Export

**Priority:** HIGH — one concrete blocking step to unlock a second validated edge ($600–$6700/day potential).

**Steps:**
1. SSH to VPS3. Query: `\copy (SELECT window_id, ts, jsonb_extract_path(yes_bids,'0','price') as ya0, jsonb_extract_path(yes_bids,'0','size') as ys0, jsonb_extract_path(no_bids,'0','price') as na0, jsonb_extract_path(no_bids,'0','size') as ns0 FROM kalshi_orderbook_v2 WHERE ts >= '2026-06-02') TO '/tmp/kalshi_depth.csv' CSV HEADER;`
2. Copy to local canonical. Re-run `poly_kalshi_arb_2026_06_05.py` with size-aware fill logic: dip event is fillable only if min(yes_ask_size, no_ask_size) ≥ $5 at the cost < 0.95 threshold.
3. If median fillable depth ≥ $5: compute revised $/day estimate. If passes: fire 10 $1/set paper orders on the next depth-verified dip event.
4. If depth is consistently < $1 at the dip moments: arb is a phantom (capacity-zero). Close the lead.

**Success criteria:** ≥50% of dip events at cost<0.95 show fillable depth ≥ $5 on at least one leg. If yes → proceed to live test.

---

### EXPERIMENT 3 (This Week): Binance 1s OFI Gate on Scalp

**Priority:** MEDIUM-HIGH — uses the most data-ready untested signal (taker_buy_base already in canonical). One session of analysis.

**Script to build:** `strategy_lab/directional/scalp_ofi_gate_2026_06_09.py`

**Steps:**
1. Load `klines_1s` for BTC+ETH, Apr22–Jun8. Compute `ofi_5s` per window: aggregate taker_buy_base and total_volume over [slot_start, slot_start+5s].
2. Load scalp outcomes (from existing backtest outputs or re-run on L25). Join on (coin, slot_start).
3. Pre-registered: fires where `ofi_5s > 0.3` AND scalp direction = Up (or ofi_5s < −0.3 and scalp direction = Down) are "OFI-aligned high conviction." Compute $/tr for aligned-high vs aligned-low vs anti-aligned.
4. Cross-validate on Mar30–Apr21 BBO OOS window (klines_1s has Jan1–Jun8 coverage, continuous, so OOS is directly usable).
5. Report: dose-response table (OFI quintile × $/tr), monotonicity check, coin-split stability.

**Success criteria:** Monotonic dose-response (top aligned quintile > all others in $/tr), CI>0 on top quintile, consistent BTC vs ETH. If passes: propose as static gate overlay on current delta_bps gate.

---

## 8. Open Leads Requiring New Data (Roadmap Items)

These are genuine gaps that cannot be tested with current canonical data:

| Lead | Data Needed | Effort | Priority |
|------|------------|--------|---------|
| F2 within-hour slug-selection decoding | Polymarket CLOB WS sub-second event tape | High (1-week infrastructure) | Medium |
| Futures funding/OI regime gate (mature) | cex_futures_ticker ≥ 30 days (have ~9 days, accruing) | Low (wait for data) | Medium — test after Jun15 refresh |
| Poly-native order flow toxicity (VPIN) | Polymarket CLOB WS trade tape at 20Hz | High (1-week infrastructure) | Medium |
| HL liquidation cascade gate (repaired) | HL feed refresh + bybit/bitget filled in | Low-medium | Low (data quality issue) |
| HYPE scalp coverage | HL S3 L2-book data (requester-pays AWS) or HL API improvement | High | Low |

---

## 9. Operational Priorities (Not Research)

These are not edge gaps — they are deployment blockers on the confirmed edge:

1. **Disable live TP@0.65 ONLY (keep stop)** — spec written (`TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md`), not yet deployed to live Ireland sleeves. BLOCKER for the 200-fire graduation gate (live fires currently test the wrong TP-active variant).
2. **Accumulate ≥200 live forward fires** — current: ~18–21 live fires (underpowered). Shadow: ~350+ on btc_5m_d3_control_v1 but real-fee CI still spans 0 at n≈80.
3. **Re-baseline shadow PnL with real sell fee** — shadow `sell_leg_fee=0.0` is optimistic by ~$0.15/tr.
4. **Oracle-determinism shadow sleeve deploy** — spec exists (ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md), TV spec not written. Needs Ireland VPS RTDS subscription confirmation.

---

## 10. Key Recurring Principles

For any new idea entering the pipeline:

1. **Execution edges first.** The scalp is an execution edge (buy cheap, sell rebound). New ideas with execution mechanisms (maker-exit, fill-quality filters) are higher priority than new prediction ideas, which face the DSR wall.

2. **Underused data as the differentiator.** The largest untapped data assets are: cex_futures_ticker (69M rows, funding+OI+mark, only 1 directional script reference), klines_1s taker columns (never extracted for OFI), chainlink_rtds staleness (used only as outcome truth), orderbook_l25 levels 2–25 shape (only BBO + walk-fill used). These are the best sources for genuinely new signals.

3. **Pre-register before searching.** The DSR graveyard (387k selectors, 4.8M indicators, 415 GPU nets) is the cost of post-hoc searching. Any new experiment must have a single mechanistically-motivated hypothesis specified BEFORE looking at outcomes.

4. **OOS from day one.** For any new positive, immediately designate a hold-out window (Mar30–Apr21 BBO is the standing OOS window for scalp experiments; use it before reporting a finding).

5. **The bottleneck is operational, not research.** The existing-data scalp space is demonstrably exhausted (SCALP_NEW_EDGE_HUNT_2026_06_09: 7 pre-registered trials, all dead). The path to more capital is: fix live TP, accumulate 200 fires, implement maker-exit A/B, verify Kalshi depth. These are execution tasks, not research tasks.

---

## 11. RESULTS — Gaps #1 and #2 executed 2026-06-09

**Gap #1 (Queue-aware maker-exit) → DEAD/NEUTRAL.** `maker_exit_queue_2026_06_09.py` (L25 native-10Hz ask-queue
+ Poly buy-trade tape; n=780 gated BTC/ETH vwap<0.55). Realistic queue model (rest behind the L25 ask depth;
buyers must clear the queue before lifting you):
- taker+60 baseline +$2.55/tr; maker queue-fixed +$2.50 (paired −0.05, CI[−0.26,+0.15] ns);
  maker peg-trail +$2.60 (paired +0.05, CI[−0.43,+0.53] ns). Same in IS/OOS; per-asset BTC −0.20 / ETH +0.50, neither sig.
- **The +$0.42/tr first-pass was a FILL-MODEL ARTIFACT** (optimistic "any buy-trade≥target fills you"). Queue position
  erases it. → Keep the validated taker +60 + stop. Maker-exit is NOT an edge. New rule confirmed: maker fill claims
  MUST model queue position, not just trade-tape touch.

**Gap #2 (Poly×Kalshi arb — Kalshi depth) → PASSED.** `poly_kalshi_arb_sizeaware_2026_06_09.py` (best-level ask depth
via complementarity). 882 matched 15m windows: 98% dip <0.95; **88% of dip quote-events fillable at ≥$5** (median
depth ~$30; 98% of dipping windows have ≥1 fillable dip). The +2.7¢/set arb has **real executable capacity, not phantom.**
→ NEXT: small depth-verified paper/live test (10×$1/set on a verified dip), then size. Caveats: best-level only;
~4% settlement-disagreement variance; short Jun2–4 matched window.

---

*Report generated: 2026-06-09. Last data window: Apr22–Jun8 2026 (~47 days). Gaps #1 (dead) + #2 (passed) executed
2026-06-09. Next: Kalshi arb live depth-test; gap #3 (1s-OFI gate) data-ready. Next review: after Jun15 refresh.*
