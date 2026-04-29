# 33 — New Strategy Vectors (External Research, 2025–2026)

**Date:** 2026-04-27
**Author:** Claude (research pass)
**Scope:** Identify strategy / regime / signal-family vectors not yet exploited in the V52→V64 book. Each vector is sourced, scoped against existing artifacts, and given a priority + expected diversification value.

---

## Where the book stands today

**Champion: V52** — Sharpe 3.04, CAGR +42.7%, MDD −7.4%, Calmar 5.74. Eight sleeves: CCI, STF, LATBB, MFI Extreme, Volume Profile Rotation, Signed-Volume Divergence, VWAP Band Fade, Inside-Bar Break (V58 add).
**V64** in deployment planning today (target Sh 2.50, CAGR +57%, MDD −10%).
**Stated next vector** (V61 close-out): **funding-rate signals (Vector 4)** — never executed.

**Already saturated families:** trend (Donchian / BB-Break / RangeKalman / Keltner+ADX / KAMA / FRAMA / MAMA / EMA-cross), mean-rev (BB scalp, RSI-2 / Connors), regime detection (ADX+slope ensemble, GMM, Hurst — BOCPD/wavelets explicitly skipped), inside-bar break, multi-tf confluence, HTF×LTF pullback, meta-labeled Donchian.
**Tested and rejected/deprecated:** ICT Order Block (lookahead bug), TTM Squeeze, VWAP Fade family (raw), SMC sweeps, V61 z-score pairs (alpha fail).
**Researched but never built:** OFI / VPIN / Kyle's λ (Archetype F), cointegration pairs (G1) / OU index-minus (G2), funding-rate plays (V19 partial).

The gap pattern is clear: the entire **derivatives-microstructure** column (funding, basis, OI, VPIN, cross-venue) and the **alt-data / on-chain** column are under-exploited despite explicit candidate specs in `03_ADAPTIVE_STRATEGY_CANDIDATES.md`.

---

## Vector 1 — Funding-Rate Carry & Dispersion (Priority 1)

**Hypothesis.** Perpetual-funding payments are a structurally different return stream from price-direction edges. Two flavours worth testing:

- **Cross-venue funding dispersion.** Hyperliquid uses 1h funding intervals with a 4%/hr cap; Binance uses 8h intervals with smaller caps. Same coin can show +0.04% on HL vs +0.01% on Binance — long Binance / short HL captures the ~33%-annualised spread delta-neutral. H1 2025: documented ~15–16% annualised pre-leverage on SOL and AVAX (long HL / short BitMEX), ~25–30% at 2–3× leverage.
- **Funding-extreme directional fade.** When perp funding hits the historical 95th-percentile (longs over-paid) and OI is rising, a short-funded fade ahead of the next funding payment has measurable edge. This is the V19 thread, never validated.

**Research hooks.**
- arxiv 2506.08573 (Jun 2025) — funding rate is path-dependent (8h average), critical for honest backtests.
- ScienceDirect 2025 CEX/DEX backtest — open-source GitHub repo, Binance + BitMEX + ApolloX + Drift; reports 12–25% annualised Sharpe 3–6, MDD <5%.
- BIS Working Paper 1087 — academic foundation for "crypto carry."

**Concrete proposals.**
1. **`sig_funding_z_fade`** — z-score per-coin perp funding vs. trailing 30d distribution. Long when z < −2 (shorts over-paying), short when z > +2 ahead of next funding tick. Time-stop = 1 funding period. Tested coin-by-coin.
2. **`overlay_funding_carry_HL_vs_BNC`** — daily snapshot of funding-rate spread (HL 1h × 8 vs Binance 8h) per coin. When spread > 5 bps post-fees, open delta-neutral pair, exit at convergence or 7-day TTL. This is **incremental capacity** outside the directional book.

**Why this fits the book.** Zero correlation with V52's price-action sleeves. Dollar-neutral version doesn't compete for the directional risk budget.
**Complexity:** M. Needs Binance + HL funding history (already in `data/binance/` and `data/hyperliquid/`).
**Decision gate:** OOS Sharpe ≥ 1.0 net of round-trip 9 bps fees + borrow on the spot leg.

---

## Vector 2 — Open-Interest × Funding Confluence (Priority 1)

**Hypothesis.** OI alone is noisy. The published 2025 evidence is that **OI × funding sign × price-direction triplets** carry information:
- Rising OI + price up + funding rising → leveraged longs piling on → squeeze risk on any retrace.
- Rising OI + price down + funding negative → short build-up → bounce probability after the next 8h funding tick.
- Falling OI during a sharp move → forced de-risking, often a bottom-tick.

**Research hooks.**
- ScienceDirect Oct 2025 — *Bitcoin wild moves: order flow toxicity and price jumps* — VPIN predicts jumps; positive serial correlation in jump size; time-zone & day-of-week effects.
- ScienceDirect 2023 — speculative retail net-short positioning is pro-cyclical and predicts crypto returns.
- Gate Wiki 2025/2026 — practitioner triplet rules for OI/funding/liquidations.

**Concrete proposal.**
- **`sig_oi_funding_triplet`** — Boolean signal:
  - **Long-fade** when (price 24h-return < −5%) ∧ (OI 24h-Δ < −10%) ∧ (funding < −0.02%/8h).
  - **Short-fade** when (price 24h-return > +5%) ∧ (OI 24h-Δ > +10%) ∧ (funding > +0.05%/8h).
  Time-stop 16 bars (4h TF) or +1.5 ATR; structural stop at 4 ATR.

**Why this fits.** Signed-Volume Divergence (V52 sleeve) is conceptually adjacent but uses on-exchange volume only. OI/funding adds the *leveraged-positioning* layer, which isn't captured anywhere in the current book.
**Complexity:** M. OI data is in `fetch_futures_phase_a.py`/`fetch_coinapi.py`.
**Expected ρ to V52 proxy:** ≤ 0.20.

---

## Vector 3 — Liquidation-Cascade Reversal (Priority 2)

**Hypothesis.** Forced-liquidation flush events overshoot fair value; statistical mean-reversion edge in the 1–6h window after the cascade. The Oct 10–11 2025 cascade ($19B OI wiped in 36h on Trump tariff news) is the canonical post-event case; SSRN 2026 abstract Zeeshan Ali documents the microstructure.

**Research hooks.**
- SSRN 5611392 — anatomy of the Oct 2025 cascade.
- Concretum / dev.to — "Jump Mean-Reversion (JMR)" specifies k-sigma intraday spike detection with z-score sizing.
- Amberdata / Coinmetro — cluster-of-liquidations as leading indicator.

**Concrete proposal.**
- **`sig_liq_cascade_revert`** — fire on any 1h bar where (ret < −μ − 3σ) ∧ (liquidation-volume z > +2.5). Enter at next-bar open in opposite direction, tiered TP at 0.5σ / 1.0σ, time-stop = 6 bars. Position size scaled inversely with z (no fixed stop — time-only exits, per the published JMR risk-management lesson).
- **Hard veto:** macro-news bar (FOMC / CPI / tariff announcement window). Cascades inside a structural-news window have a very different forward distribution and should be skipped.

**Why this fits.** V52 doesn't have a pure event-driven mean-rev sleeve. The forecast-window is short (≤ 6h on 1h TF) so it doesn't compete with the swing book. Negative correlation to inside-bar break sleeves expected.
**Complexity:** M-L. Requires liquidation feed (Coinglass / CoinAPI). Already partly fetched in `fetch_coinapi_liq.py`.
**Decision gate:** OOS Sharpe ≥ 0.7, ρ to V52 ≤ 0.10, hit-rate ≥ 55%.

---

## Vector 4 — Volatility Risk Premium on DVOL (Priority 2)

**Hypothesis.** BTC implied vol (DVOL) has run consistently above 30d realized vol; the spread is a harvestable risk premium. Single peer-reviewed Wiley 2025 paper (vol-of-vol pricing) confirms VRP is structural in crypto, not just an equity phenomenon.

**Research hooks.**
- Deribit DVOL futures (live since Mar 2023) — pure vega instrument, no delta entanglement.
- arxiv / GitHub `pi-mis/btc-dvol-strategy` — open-source eVRP+term-structure systematic implementation, derived from Zarattini, Mele & Aziz 2025 ("The Volatility Edge", S&P 500 → BTC adaptation).

**Concrete proposal.**
- **`overlay_vrp_short_dvol`** — when (DVOL − 30d-RV) > 95th-percentile of trailing 365d, open short-DVOL futures sized to 0.5% portfolio-vol per leg. Exit at mean-revert or vol spike (kill at DVOL +50% in 24h).

**Why this fits.** Pure cross-asset diversifier — non-directional, uncorrelated to the entire price-action book by construction. Adds capacity without competing for directional budget.
**Complexity:** L. Requires Deribit account (or paper-trade against archived DVOL series). New venue, new data feed.
**Decision gate:** Forward-MC OOS Sharpe ≥ 0.8 net of Deribit fees; tail-risk capped at −5% per leg via stop-on-DVOL-jump.

---

## Vector 5 — Time-of-Day / Session-Anchored Overlays (Priority 1, low cost)

**Hypothesis.** Session effects in crypto are persistent and have *strengthened* post-2020 with institutional entry. Two published 2025 effects:
- **Monday-Asia-Open trend effect** (Zarattini et al. SFI 25-80) — Bitcoin intraday trend strategy delivers Sharpe ~1.6 gross, with returns concentrated Sun 7pm ET → Mon 24h. Effect is much stronger post-2020.
- **"Tea-time" peak** (Review of Quantitative Finance & Accounting) — volume / vol / illiquidity peak ~16–17 UTC across 38 exchanges and 1,940 pairs.
- **Asian-session drift-down** ("US pump, Asia dump") — average hourly Asia session returns negative, US session +0.25%/hr in 2019–2021, persisting in form post-2020.

**Concrete proposals.**
1. **`gate_session_trend`** — bias V52 trend sleeves long-only between Sun 23:00 UTC and Mon 23:00 UTC (Monday-Asia window); reduce sizing by 50% during Asian session (00:00–07:00 UTC) on long-side trend signals.
2. **`sig_teatime_volexp`** — pre-position into expected vol expansion at 15:30 UTC; exit at 17:30 UTC. Pairs naturally with the inside-bar-break sleeve which depends on volatility expansion.
3. **`gate_macro_event_pause`** — flatten / refuse new entries 30 min before and after FOMC / CPI / NFP / known tariff windows. Reduces tail risk at near-zero alpha cost.

**Why this fits.** All three are *gates / overlays* on existing sleeves, not new strategies — minimal new code, immediate test in the gates harness (`run_v59_v58_gates.py` style). Already documented to lift Sharpe in similar setups (V58/V59 trail-tighten lessons).
**Complexity:** S. Pure timestamp filters.
**Expected lift:** +0.1–0.2 Sharpe, MDD compression of 10–20% in the gated sleeves.

---

## Vector 6 — Stablecoin-Flow Liquidity Tide (Priority 3, slow-moving)

**Hypothesis.** Since the Jan-2024 ETF launch, classic on-chain whale signals have decayed; the surviving on-chain alpha is in **stablecoin supply expansion + exchange-stablecoin-balance**. This is a *low-frequency directional regime gate*, not a trade signal.

**Research hooks.**
- Glassnode / CryptoQuant 2025 reports — stablecoin expansion is the fastest on-chain reaction, typically within hours of ETF flow shifts.
- BIS WP 1270 (2025) — stablecoins and safe-asset prices.
- CryptoSlate / CoinDCX 2026 — combined ETF + stablecoin-supply rule has the strongest historical correlation to multi-week BTC moves.

**Concrete proposal.**
- **`gate_liquidity_tide`** — daily flag computed from (stablecoin-cap 7d-Δ, ETF flow 7d-Δ). When both negative → reduce trend sleeve sizing 30%; when both positive → permit full sizing. *Don't* add as a fresh signal; use it strictly as a regime risk-budget gate.

**Why this fits.** V52's directional sleeves are already calibrated; this just modulates exposure during macro-liquidity drains (the Aug-Nov 2025 period that produced the worst 2-month drawdown since mid-2022 would have been flagged early).
**Complexity:** M. Requires Glassnode / CryptoQuant API or a free tier of CoinGecko stablecoin-cap series. Daily granularity; no need for tick data.
**Decision gate:** Backtest must show MDD compression with ≤ 10% CAGR cost.

---

## Vector 7 — VPIN Order-Flow Toxicity (Priority 2)

**Hypothesis.** VPIN spikes precede volatility expansion — predictive of *that a move is coming*, not direction. Best deployed as a **regime exit / risk-off filter**, not as a long/short signal — exactly the spec from Archetype-F Method 2 in `03_ADAPTIVE_STRATEGY_CANDIDATES.md` that was never built.

**Research hooks.**
- ScienceDirect Oct 2025 — Kitvanitphasu et al., VPIN ↔ BTC price jumps, VAR model, time-zone & day-of-week effects. Peer-reviewed validation of VPIN's transferability to crypto.
- Easley, López de Prado, O'Hara — original VPIN.
- Buildix Trade 2026 — practitioner thresholds: VPIN > 0.55 = elevated, > 0.70 = extreme. Specific Hyperliquid implementation notes (no designated MM → toxic flow visible faster).

**Concrete proposal.**
- **`gate_vpin_volatility_off`** — compute volume-bucketed VPIN per coin from trade ticks (already collected by `fetch_coinapi_ticks.py`). When VPIN > 0.55 sustained 3+ buckets → tighten trail multipliers by 0.65 on open positions, refuse new entries until VPIN < 0.40. Pairs naturally with the V58 trail-tighten lesson.

**Why this fits.** Doesn't introduce a new directional bet; it's a *risk-off gate* that fires on the same regime transitions that historically trigger inside-bar-break drawdowns.
**Complexity:** L. VPIN is sensitive to bucket-volume sizing, BVC vs raw maker-taker tag. Requires careful no-leak validation.
**Decision gate:** ≥ 30% reduction in MDD on V52 sleeves when gated, with ≤ 15% CAGR cost.

---

## Vector 8 — Cross-Sectional Momentum + Vol Scaling (Priority 3)

**Hypothesis.** Two competing strands of 2025 academic evidence:
- *Liu et al. (2020) / Drogen-Hoffstein-Otte (SSRN)* — short-term cross-sectional momentum (1–4 week formation) on a coin universe captures real returns.
- *Springer 2025 / ScienceDirect Jul 2025 (Sadaqat-Butt rebuttal)* — naive equity-style momentum loses money in crypto; the **vol-managed Barroso-Santa-Clara overlay** is what makes it work; momentum crashes are absent in crypto vs equities.

The book has tested this in piecemeal fashion (V14 cross-sectional, V17 pairs) but never with the **full vol-scaled WML methodology** on the 9-coin universe.

**Concrete proposal.**
- **`overlay_xsm_vol_scaled`** — weekly rebalance: rank 9 coins on 2-week cumulative return; long top quintile / short bottom quintile, value-weighted, leverage normalized to constant target volatility (Moskowitz 2012 spec). Hold 1 week.

**Why this fits.** The current book's diversification is *signal-family* diversification on per-coin sleeves; XSM is *cross-sectional* diversification, structurally different. Even with modest Sh 0.5–0.8 (realistic post-cost), the negative ρ to single-coin price-action is the value.
**Complexity:** M. Needs walk-forward at the portfolio level, not per-coin.
**Caveat:** with 9 coins, "quintiles" become "long top 2 / short bottom 2" — small basket, fragile. May need to expand universe.
**Decision gate:** Net-of-cost OOS Sharpe ≥ 0.6, ρ to V52 proxy ≤ 0.15.

---

## Vector 9 — RL/Bandit Meta-Allocator Over Existing Sleeves (Priority 4, exploratory)

**Hypothesis.** V52 currently equal-weights its 8 sleeves. The 2025 FinRL literature (arxiv 2511.12120 ensemble paper, Wiley Sep 2025 dynamic-regime allocator) shows meaningful Sharpe lift when sleeve weights are dynamically allocated by a meta-policy keyed on regime features.

**Concrete proposal.**
- **`meta_alloc_bandit`** — a non-stationary contextual bandit (LinUCB or EXP3.S) over the 8 V52 sleeves, context = (directional regime label from study 24, realized-vol decile, VPIN decile, funding decile). Weights re-allocated weekly. Walk-forward train/test mandatory; restrict action space to ±25% of equal-weight to bound damage from overfitting.

**Why this fits.** Doesn't introduce signal-level overfitting risk because the underlying sleeves are already validated; it only modulates already-good edges. Expected lift is modest (Sh 3.04 → 3.3?) but free given the sleeves exist.
**Complexity:** L. Bandit infra, walk-forward harness, stability tests. Don't ship until 6 months of paper-trade history exists.
**Decision gate:** OOS Sharpe lift ≥ 0.2 and MDD non-worse vs equal-weight baseline.

---

## What I'm explicitly NOT proposing

- **More trend-family parameter sweeps** — saturation evidence from V58/V60 is conclusive (uniform monotone degradation when tightening).
- **Re-enabling deprecated families** (V26 OB, V25 SUI MTFConf) — failed on structural grounds, not market conditions.
- **TTM Squeeze, raw VWAP Fade, raw SMC** — explicitly tested and rejected.
- **BOCPD / wavelets / hmmlearn** — verdict in `02_REGIME_LAYER_RESEARCH.md` was correct; current ADX-EMA ensemble + directional regime classifier is sufficient.
- **More pairs / cointegration sweeps** — V61 closed this out: spread mean-reverts but the alpha-after-cost is too thin.

---

## Recommended sprint order

| # | Vector | Priority | Complexity | Expected lift | Sleeve type |
|---|---|---|---|---|---|
| 5 | Time-of-day gates | 1 | S | Sh +0.1–0.2 | Overlay on existing |
| 1 | Funding-rate carry + dispersion | 1 | M | New uncorrelated stream, Sh ~1.0+ | Net-new sleeve |
| 2 | OI × funding triplet | 1 | M | Sh ~0.7+, ρ < 0.20 | Net-new sleeve |
| 3 | Liquidation-cascade revert | 2 | M-L | Sh ~0.7, ρ < 0.10 | Net-new sleeve |
| 7 | VPIN risk-off gate | 2 | L | MDD −30% on existing | Gate |
| 4 | DVOL VRP | 2 | L | Sh ~0.8, full diversifier | New venue |
| 6 | Stablecoin liquidity tide | 3 | M | MDD compression, slow | Gate |
| 8 | XSM vol-scaled overlay | 3 | M | Sh ~0.6, ρ < 0.15 | Cross-sectional |
| 9 | RL/bandit meta-allocator | 4 | L | Sh +0.2 vs equal-weight | Meta layer |

**Quickest win-rate path:** Vector 5 (1 day), then Vector 1 (1 week, funding data already on disk), then Vector 2 (1 week, OI data fetched). These three could plausibly add a fresh uncorrelated income stream + a measurable Sharpe lift to V64 before any new market data acquisition is needed.

---

## Sources

### Funding-rate / basis arbitrage
- [ScienceDirect 2025 — Risk and Return Profiles of Funding Rate Arbitrage on CEX and DEX](https://www.sciencedirect.com/science/article/pii/S2096720925000818)
- [arxiv 2506.08573 — Designing funding rates for perpetual futures (Jun 2025)](https://arxiv.org/abs/2506.08573)
- [BIS Working Paper 1087 — Crypto carry](https://www.bis.org/publ/work1087.pdf)
- [BSIC — Perpetual Future Arbitrage Mechanics](https://bsic.it/perpetual-complexity-an-introduction-to-perpetual-future-arbitrage-mechanics-part-1/)
- [Pi2 Network — Arbitrage Opportunities in Perpetual DEXs](https://blog.pi2.network/arbitrage-opportunities-in-perpetual-dexs-a-systematic-analysis/)
- [BitMEX — Harvest Funding Payments on Hyperliquid](https://www.bitmex.com/blog/harvest-funding-payments-on-hyperliquid)

### OI / order-flow / VPIN
- [ScienceDirect Oct 2025 — Bitcoin wild moves: order flow toxicity and price jumps (Kitvanitphasu et al.)](https://www.sciencedirect.com/science/article/pii/S0275531925004192)
- [ScienceDirect 2023 — Predictability of crypto returns: trading behavior](https://www.sciencedirect.com/science/article/abs/pii/S2214635023000266)
- [Buildix Trade — VPIN flow toxicity for crypto traders](https://www.buildix.trade/blog/what-is-vpin-flow-toxicity-crypto-trading)
- [Gate Wiki Dec 2025 — Derivatives signals: funding, OI, liquidations](https://web3.gate.com/crypto-wiki/article/how-do-derivatives-market-signals-predict-crypto-market-trends-funding-rates-open-interest-and-liquidation-data-in-2025-20251222)
- [Tradelink.pro — Funding rate + open interest squeeze setups](https://tradelink.pro/blog/funding-rate-open-interest/)

### Liquidation cascade reversal
- [SSRN 5611392 — Anatomy of the Oct 10–11 2025 Crypto Liquidation Cascade](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5611392)
- [Concretum / dev.to — Intraday Volatility Jump Mean-Reversion for BTC](https://dev.to/ayratmurtazin/intraday-volatility-jump-mean-reversion-trading-strategy-for-btc-usd-in-python-44lf)
- [Amberdata — Liquidations: anticipating volatile market moves](https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves)

### Volatility risk premium / DVOL
- [Deribit Insights — DVOL methodology](https://insights.deribit.com/exchange-updates/dvol-deribit-implied-volatility-index/)
- [GitHub — pi-mis/btc-dvol-strategy (eVRP systematic)](https://github.com/pi-mis/btc-dvol-strategy)
- [Wiley Journal of Futures Markets 2025 — VOV risk premium pricing](https://onlinelibrary.wiley.com/doi/10.1002/fut.70029)

### Session / time-of-day
- [Concretum — Seasonality in Bitcoin Intraday Trend Trading (SFI 25-80)](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
- [Springer RQFA — Crypto trades at tea time: intraday evidence](https://link.springer.com/article/10.1007/s11156-024-01304-1)
- [ScienceDirect — Intraday and daily dynamics of cryptocurrency](https://www.sciencedirect.com/science/article/pii/S1059056024006506)

### Cross-sectional momentum
- [Springer 2025 — Cryptocurrency momentum has (not) its moments (vol-managed)](https://link.springer.com/article/10.1007/s11408-025-00474-9)
- [ScienceDirect Jul 2025 — Crypto market risk-managed momentum strategies](https://www.sciencedirect.com/science/article/abs/pii/S1544612325011377)
- [SSRN — Han, Kang & Ryu, TS & XS Momentum in Crypto](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4675565)

### Stablecoin flows / on-chain
- [BIS WP 1270 — Stablecoins and safe asset prices](https://www.bis.org/publ/work1270.pdf)
- [Glassnode Insights — Digital asset market intelligence](https://insights.glassnode.com/)
- [BeInCrypto — On-chain signals for 2026](https://beincrypto.com/dune-on-chain-signals-crypto-2026/)
- [CryptoSlate — The 5 signals that really move Bitcoin now](https://cryptoslate.com/the-5-signals-that-really-move-bitcoin-now-and-how-they-hit-your-portfolio/)

### RL / bandit meta-allocators
- [arxiv 2511.12120 — Deep RL Ensemble Strategy for Trading](https://arxiv.org/abs/2511.12120)
- [arxiv 2504.02281 — FinRL Contests benchmark](https://arxiv.org/abs/2504.02281)
- [Wiley AI Engineering 2025 — FinRL Data-Driven Agents](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/aie2.12004)
- [arxiv 2512.10913 — Systematic review of RL in finance 2017–2025](https://arxiv.org/abs/2512.10913)

### BOCPD / change-point (kept for completeness — verdict unchanged)
- [arxiv 2307.02375 — Online Learning of Order Flow with BOCPD](https://arxiv.org/abs/2307.02375)
- [Matrix-profile-enhanced BOCPD (OSQF 2025)](https://www.osqf.org/archive/2025/MasoudNeshastehriz.pdf)
