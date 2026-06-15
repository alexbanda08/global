# Awesome-Systematic-Trading — Tooling Review for OUR Project

**Date:** 2026-06-11
**Source list:** [wangzhe3224/awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading) (`Readme.md` + `crypto_focus.md`, master, fetched 2026-06-11)
**Filter lens:** Poly/Kalshi crypto UP-DOWN binary scalp (validated edge = execution-shaped book-lag) + 5 open tooling threads + new HYPERLIQUID perps expansion.
**Stack we already have (do NOT duplicate):** Py3.14, pandas/numpy/pyarrow, **vectorbt**, **ml4t (DSR/PBO/CPCV — López de Prado)**, torch+CUDA, custom live-mimic Poly fill engine, custom event-driven harnesses, postgres event store, live FastAPI engine on 2 VPSes.

**Threads (referenced by number below):**
1. MAKER w/ rebate-as-income → needs **queue-aware OB backtest** (queue position, fill prob, adverse selection)
2. Late-slot Chainlink **oracle-latency** snipe
3. **Poly×Kalshi cross-venue arb** (2-leg simultaneous fills)
4. **Microstructure analytics** (VPIN as maker-toxicity kill-switch — NOT as signal; signal-VPIN already killed)
5. **HYPERLIQUID perps** (funding, liquidation cascades, basis, MM)

---

## (1) TOP RECOMMENDATIONS

| Repo | What it gives us | Thread | Maturity | Effort | Verdict |
|---|---|---|---|---|---|
| **[hftbacktest](https://github.com/nkaz001/hftbacktest)** (nkaz001) | Tick-by-tick L2/L3 backtest w/ **queue position + fill-probability + feed/order latency** models; rebate fee models; **ships a Hyperliquid example** | **1, 5** | High (active, Py+Rust, Numba, docs) | **M** | **ADOPT** |
| **[hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)** (official) | Official HL REST+WS; `basic_adding.py` MM template; order/position mgmt | **5** | High (official, v0.22, 1.4k★) | **S** | **ADOPT** |
| **[pmxt](https://github.com/pmxt-dev/pmxt)** (*not in list — surfaced via search*) | "**CCXT for prediction markets**" — unified Poly+Kalshi+Limitless order API, one interface | **3** | Med (new, MCP-native) | **S/M** | **TRIAL** |
| **[oracle3](https://github.com/YichengYang-Ethan/oracle3)** (+[SSRN paper](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6468338)) | Kalshi/Poly arb agent; **Wang-Transform** pricing calibrated on 291k contracts; 8 constraint-arb strategies; 633 tests, Apache-2.0 | **3, ideas** | Med (research-grade, tested) | **M** (mine, don't adopt whole) | **TRIAL** |
| **[Jon-Becker/prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis)** (*via search*) | **Largest public Poly+Kalshi market+trade dataset** + collection/analysis framework | **3, 2** | Med | **S** | **TRIAL** (data, cross-validate vs our canonical) |
| **[The Microprice](https://github.com/sstoikov/microprice)** (Stoikov) | Reference impl of microprice fair-value estimator from OB state | **1, 2** | Low (paper code, stable) | **S** | **TRIAL** |
| **[Cryptofeed](https://github.com/bmoscon/cryptofeed)** (bmoscon) | Async multi-exchange WS L2/trade/funding/liq normalizer | **5** | High (mature) | **S** | **TRIAL** (only if we add more live CEX feeds) |
| **[nautilus_trader](https://github.com/nautechsystems/nautilus_trader)** | Rust-core event engine; v1.224 added **backtest queue_position heuristic**; v1.226 added **native HL adapter** | 1, 5 | Very high (22k★, biweekly) | **L** | **SKIP** (watch) — LGPL-3.0 + full re-platform, overlaps our harness |
| **[pykalshi](https://github.com/ArshKA/kalshi-client)** | Kalshi client: WS streaming, local OB mgmt, pandas, retries/rate-limit | 3 | Med | **S** | **SKIP-unless** (we have Kalshi canonical already; adopt only if we go live-Kalshi) |
| **[Parsec / parsec-mcp](https://github.com/parsecular/parsec-mcp)** | Multi-venue PM data+exec+stream, one API key (Poly/Kalshi/Opinion/Limitless/PredictFun) | 3 | Med (closed API, paid) | S | **SKIP** (paid/closed; pmxt is OSS equiv) |

**Effort key:** S = days, M = 1–2 weeks integ, L = re-platform.

---

## (2) PER-CATEGORY SWEEP (so nothing missed)

- **General purpose (40):** Mostly generic equities/futures event-backtesters (backtrader, bt, zipline, vnpy, QuantConnect/Lean, pysystemtrade, lumibot…). We have vectorbt + custom harness → **all SKIP** except **hftbacktest** (queue-aware, the one genuine gap) and **flashalpha-fill-simulator** (options-spread fill sim — wrong asset, SKIP). vectorbt itself is in the list = we already run it.
- **Crypto currency focus (15):** Trading bots (Freqtrade, Jesse, OctoBot, MyCryptoBot) + Rust exchange clients + **Hummingbot**. All retail TA bots → **SKIP**. Hummingbot = the one MM framework worth a note (see Ideas); has an HL connector but heavyweight → **SKIP for us** (our edge isn't classic AS-MM, and hftbacktest covers the research side better).
- **ML / RL (2):** TradingGym, Deep-Q trading-bot. Prediction-shaped, toy → **SKIP** (we formally killed ML-prediction under DSR).
- **Alpha → General Alpha (11):** TA strategy zoos (RSI/Bollinger/MACD/pairs/trend). Generic, equities → **SKIP** (we killed generic TA + 4.8M combos).
- **Alpha → Expression-based (6):** WorldQuant-operator alpha gens (torchquantum, OpenAlpha, AlphaGen, Genetic-Alpha). Formulaic equities-XS alpha → **SKIP** (cross-sectional, not 2-token binary).
- **Alpha → Orderbook (1):** **The Microprice** → **TRIAL** (only genuinely OB-microstructure item in Alpha).
- **Arbitrage (Crypto) (3):** Blackbird/bitcoin-arbitrage/R2 — spot cross-exchange, stale → **SKIP**.
- **crypto_focus.md (27):** Perp/funding items: **perp-arbitrageur** (Perp-Protocol↔FTX, FTX dead → SKIP), **FTX+4-exchange funding scanner** (FTX dead → SKIP), **DDEX Liquidation Bot** (Go, on-chain DDEX, wrong venue → SKIP but concept = liq-cascade, see Ideas), **K/Krypto-trading-bot** (C++ HFT MM → SKIP), **polymarket-whales** / **PolyMind** (alert toys → SKIP). Net: funding/liq repos here are FTX-era dead; HL coverage comes from search, not this file.
- **Basic Components / Computation / Perf / Profilers:** numpy/pandas/numba/polars accelerators. We have these → **SKIP all**.
- **Analytic → Metrics/Indicators/Pricing/TimeSeries:** TA-Lib-likes + QuantLib pricers. **SKIP** (generic TA we killed; option pricers irrelevant to binary scalp).
- **Analytic → Risk (3):** pyfolio (tearsheets — minor nice-to-have, SKIP), curistat/System-R (closed MCP SaaS → SKIP).
- **Analytic → Optimization (7):** PyPortfolioOpt/Riskfolio/cvxportfolio/skfolio/Deepdow. Portfolio-weight allocators → **SKIP** (we run one edge, not a portfolio; revisit only if we run a HL multi-sleeve book).
- **Visualization / MessageQueues / Databases:** infra we already have (postgres) → **SKIP**.
- **Data Source → Crypto (10):** Cryptofeed (**TRIAL**), Orderflow (footprint candles, TS → SKIP), **Sharpe API** (funding/arb/options REST+MCP — free tier, possible quick funding-rate cross-check → note), CoinPaprika/DexPaprika (low-res → SKIP), Microverse (L2 from 21 ex, free WS — possible HL-adjacent feed → note), rest are AI-forecast SaaS → SKIP.
- **Data Source → Prediction Markets (5):** **Parsec** (paid, SKIP), pykalshi (**conditional**), ProfitPlay/TBD/PolyMind (toys → SKIP). *Search-surfaced extras worth more than the listed ones:* **pmxt**, **prediction-market-analysis** (above).
- **Data → Alternative (6):** SEC/13F/Congress trackers → **SKIP** (equities alt-data, irrelevant).
- **Broker APIs (8):** IB/TD/etc. → **SKIP** (explicitly not needed).
- **AI-Powered Systems (15):** Mostly LLM-agent/self-evolving-strategy SaaS (AI-Hedge-Fund, FinRL, QLib, FinGPT, FinClaw…). Prediction/agent hype → **SKIP**. Exceptions surfaced for ideas: **oracle3** (Kalshi/Poly arb, real paper → TRIAL), **Eterna** (HL perp MCP, closed → SKIP), **VARRD** (event-study validator — we have ml4t/DSR → SKIP).
- **Resources → Research/Books/Blogs/Courses:** AFML (López de Prado — we already run its ml4t toolkit), ML4T (Jansen), Carver Systematic Trading. **Already internalized** → see Ideas for the 2 papers worth re-reading.
- **Quant Shops / Relevant Projects:** JaneStreet/Man/TwoSigma/DESHAW/HRT blogs (good reading, no code we need) + meta-lists. The meta-list **[Awesome-Prediction-Market-Tools](https://github.com/aarora4/Awesome-Prediction-Market-Tools)** (search-surfaced) is the single best follow-on index for thread 3 → **bookmark**.

---

## (3) ADOPT / TRIAL DETAIL

### ADOPT — hftbacktest (nkaz001)
- **What:** Full-tick L2/L3 replay backtester explicitly modeling **order queue position**, **probabilistic fill** (e.g. `SquareProbQueueModel`), and **feed + order latency** separately; configurable rebate/fee models (built on Binance 0.005% MM rebate examples); Py (Numba) + Rust; ships **Bybit + Hyperliquid + MEXC** example strategies incl. "Market Making with Alpha — Order Book Imbalance" and "Queue-Based MM in Large-Tick Assets".
- **Why it beats ours:** Our custom live-mimic engine models latency + Poly fees + sparse-book filter but is **taker-fill only** — it has **no queue-position / fill-probability model**. Thread 1 (maker rebate-as-income) is *unanswerable* without exactly this: you cannot estimate maker fill prob or adverse selection from a taker fill engine. This is the missing primitive.
- **First use-case:** Port our Poly L25 book tape into hftbacktest's L2 feed format; run the maker-exit-with-taker-fallback test (NEXT #1 in handoff) with a real queue model to get fill-prob + adverse-selection numbers, instead of assuming fills. Then reuse the *same* engine for HL MM research (thread 5) since the HL example already exists.
- **Risks:** Data-format adapter is the work (our parquet L25 → its feed schema); "large-tick" assumptions differ for $0–1 binary tokens (tick = $0.01 = 1% — actually *helps*, binary books ARE large-tick); Numba/Rust build on Py3.14 needs a smoke test (we already proved torch/vectorbt/ml4t on 3.14, but verify hftbacktest wheels).

### ADOPT — hyperliquid-python-sdk (official)
- **What:** Official HL REST+WS SDK; order placement/cancel, positions, funding, `basic_adding.py` MM example (posts at ±0.3% of BBO, cancel/replace on drift).
- **Why it beats ours:** We have HL *data* (klines+liqs) but **no execution path** to HL. This is the canonical, maintained one (1.4k★, official) — don't hand-roll. CCXT's `ccxt/hyperliquid-python` is the alternative and adds `fetch_funding_rate_history/fetch_funding_rates` — pull those funding methods from CCXT even if we trade via the official SDK.
- **First use-case:** Stand up a HL **testnet** paper sleeve mirroring our shadow-fleet pattern: funding-rate carry probe on BTC/ETH/SOL perps, judged by live wallet (per our ground-truth rule). Feeds thread 5.
- **Risks:** Third-party HL MM bots in the wild embed dev-fees / are unvetted — use the **official** SDK only. Wallet/key handling on the VPSes (Arbitrum signer) is a new opsec surface.

### TRIAL — pmxt ("CCXT for prediction markets")
- **What:** Unified order API across Polymarket + Kalshi (+Limitless), single interface; positioned as drop-in for the Dome API; MCP-native but has a normal SDK.
- **Why it beats ours:** Thread 3 needs **simultaneous 2-leg fills across Poly and Kalshi**. A single normalized order interface removes the per-venue auth/orderbook divergence that otherwise doubles our execution code. We already have Kalshi *data* canonical; pmxt is about the *execution* leg.
- **First use-case:** Prototype the deep-dip set-cost arb (set-cost<0.95 → +2.7¢/set, already measured in our Kalshi work) as a 2-leg pmxt order, measure real fill latency/slippage between venues on testnet/small live.
- **Risks:** New project, thin track record — verify it actually does atomic-ish 2-leg (it won't be truly atomic across two venues; leg risk is real). Confirm it exposes **ask-depth** (our Kalshi arb is GATED on unverified Kalshi ask-depth — pmxt must surface full book, not BBO).

### TRIAL — oracle3 + Yang (2026) SSRN paper
- **What:** Apache-2.0 autonomous Kalshi/Poly/Solana agent built on the **Wang Transform** pricing model: market price `p_mkt = Φ(Φ⁻¹(p*) + λ)`, a one-param exponential tilt of a latent Gaussian factor, calibrated λ̂=0.183 on 291k resolved contracts. 8 constraint-arb strategies (cointegration spread, lead-lag, fair-value divergence, premium decay), Kelly sizing, 633 tests.
- **Why it's worth mining (not adopting whole):** It's a *prediction*-shaped agent — our DSR work says don't trust those. BUT the **Wang-Transform risk-premium framing is a pricing lens we have NOT tried**: it says the binary price is the true prob *tilted* by a market risk-premium λ, and it *derives* favorite-longshot bias as a corollary. We logged favorite-longshot as "dead" — but that was as a naive *signal*; the Wang tilt reframes it as a *fee/edge curve*, which could matter for the maker fair-value (thread 1) and for our `entry_vwap<0.55` cheap-token selection.
- **First use-case:** Re-run our own resolved-contract history through the Wang λ calibration; check whether the lagging-token mispricing we exploit is partially the λ tilt vs pure book-lag — sharpens the entry filter. Read the SSRN paper before touching code.
- **Risks:** Don't deploy its agent. Its "premium decay" / "lead-lag" overlap things we already killed (cross-asset lead-lag dead) — treat as idea source, validate everything under our DSR/CPCV gate.

### TRIAL — Jon-Becker/prediction-market-analysis
- **What:** Collection+analysis framework with the **largest publicly available Poly+Kalshi market & trade dataset**.
- **Why:** Free OOS cross-check / window-extension for thread 3 and for the different-window OOS the handoff wants (`validate_oos.py`). Our aliplayer BBO is frozen at Apr 21; this could fill gaps or cross-validate settlement.
- **First use-case:** Diff its Kalshi settlement labels vs our canonical resolutions (we have 96% Poly×Kalshi settlement agreement — independent dataset confirms or breaks that).
- **Risks:** Schema/labeling provenance unknown — treat as audit channel, not ground truth (our ground-truth rule).

### TRIAL — The Microprice (Stoikov)
- **What:** Reference estimator of fair price from OB imbalance + spread state (the Stoikov microprice).
- **Why:** Thread 1/2 — a principled fair-value anchor for maker quoting and for *measuring* the book-lag (microprice on the leading venue vs lagging Poly token). Cleaner than our ad-hoc `entry_vwap`.
- **First use-case:** Compute microprice on the Binance feed at window open; quantify lag-to-Poly in microprice terms (vs raw close) to see if it tightens the <$0.55 entry trigger.
- **Risks:** It's research code, not a library — port the formula, don't depend on the repo.

### TRIAL — Cryptofeed (bmoscon)
- **What:** Mature async normalizer for many exchanges' WS L2/trades/**funding/open-interest/liquidations**.
- **Why:** If thread 5 expands live data beyond our current 4-exchange CEX futures collectors, Cryptofeed gives funding/OI/liq feeds out-of-the-box incl. an HL feed.
- **First use-case:** Only if we add live HL/CEX feeds — replace bespoke collectors for funding+liq.
- **Risks:** We already have canonical CEX futures (funding/OI/liq) → low marginal value *now*; adopt only when going live on HL feeds.

---

## (4) HYPERLIQUID SECTION (everything usable for HL perps)

The curated list itself is **thin on HL** (only oblique mentions: Agent Gateway HL price API, Eterna closed MCP). The usable HL stack comes from the list's adjacency + targeted search:

| Tool | Use | Verdict |
|---|---|---|
| **[hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk)** (official) | Execution: orders/positions/funding + `basic_adding.py` MM template | **ADOPT** |
| **[ccxt/hyperliquid-python](https://github.com/ccxt/hyperliquid-python)** | `fetch_funding_rate(s)` / `_history` for funding strategies | **ADOPT (funding methods)** |
| **[hftbacktest](https://github.com/nkaz001/hftbacktest)** — HL example | Queue-aware MM **backtest** on HL L2 | **ADOPT** (same engine as thread 1) |
| **[nautilus_trader](https://github.com/nautechsystems/nautilus_trader)** v1.226+ | Native HL adapter + queue_position backtest | **WATCH** (LGPL, heavy) |
| **[Cryptofeed](https://github.com/bmoscon/cryptofeed)** | Live HL funding/OI/liq WS feed | **TRIAL** (when live) |
| **[rustjesty/hyperliquid-drift-arbitrage-bot](https://github.com/rustjesty/hyperliquid-drift-arbitrage-bot)** (search) | Reference: Drift↔HL **funding-rate market-neutral** arb (nets fees+slippage, hedged) | **MINE** (read for funding-arb structure; Py3.12, unvetted) |
| **[Hummingbot](https://github.com/CoinAlpha/hummingbot)** HL connector | Production AS-style MM if we want turnkey | **SKIP** (heavy; not our edge shape) |
| Eterna / Agent Gateway / Sharpe API | Closed/SaaS HL price/MM endpoints | **SKIP** (closed) |

**HL recommendation:** official SDK (exec) + CCXT funding methods + hftbacktest HL example (research) is the complete OSS path. Funding-carry and basis are research threads; for **liquidation cascades** there is *no list repo* — we already have the better asset (4-exchange + HL liq data in canonical). Build the cascade study in-house on canonical; the DDEX liq-bot concept is the only liq reference and it's wrong-venue.

---

## (5) IDEAS MINED (concepts we haven't tried, fit binary 5m/15m or HL perps)

Cross-checked against our killed list (VPIN-as-signal ✗, generic TA ✗, ML-prediction ✗, mid-window scalp ✗, cross-asset lead-lag ✗, naive favorite-longshot ✗):

1. **Wang-Transform risk-premium pricing** (oracle3 / Yang 2026 SSRN). NEW lens: binary price = true prob *tilted* by market risk-premium λ; derives favorite-longshot as a *structural fee curve*, not a signal. Fit: re-frame our cheap-token (`<$0.55`) edge — is part of it the λ tilt vs pure book-lag? Could sharpen entry filter + give a principled maker fair-value (thread 1). **Not previously tried as a pricing model.** ✅ worth a spike.
2. **Microprice as lag metric** (Stoikov). Measure Binance-lead vs Poly-lag in *microprice* space (imbalance-aware fair value) rather than raw close — tighter, theory-backed version of our existing edge. ✅
3. **Queue-position fill-probability modeling** (hftbacktest). Not a strategy idea but the missing *measurement* that turns thread 1 (maker rebate-as-income) from speculation into a testable edge — incl. **adverse-selection** quantification, which is the real maker killer. ✅ this is the highest-value idea-tool.
4. **Order-book-imbalance MM-with-alpha** (hftbacktest example notebook + Microprice). OBI as a *maker quoting skew* (not a directional signal) — different from the killed VPIN-signal. On binary books at window open, OBI may predict short-horizon fill direction → adverse-selection-aware quoting. ✅ test under DSR.
5. **Funding-rate carry, market-neutral hedged** (rustjesty Drift↔HL bot structure; CCXT funding history). Standard but new-to-us: long the lower-projected-funding venue / short higher, net of fees+slippage. Fit thread 5; we have 4-exchange funding/OI canonical to backtest it offline before any live. ✅
6. **Premium-decay lifecycle** (oracle3). Binary contracts have a predictable premium decay toward resolution — overlaps our intra-window exit timing (+60s sell). Worth checking if a *decay curve* beats our fixed +60s exit. ⚠️ partial overlap with known edge; low-priority confirm.

**Explicitly NOT worth re-trying** (list surfaced but we already killed): FinRL/QLib/FinGPT RL-prediction, expression-based formulaic alpha (cross-sectional, wrong shape), generic TA strategy zoos, triangular/spot arb, VPIN-as-signal.

---

## Bottom line
The list is ~95% irrelevant (equities platforms, retail TA bots, LLM-agent SaaS, dead FTX-era arb). The dense value is exactly **3 items + 3 search-adjacent**: hftbacktest (the one true gap-filler — queue-aware OB backtest, doubles as HL research), the official HL SDK (our missing exec path), and pmxt/oracle3/prediction-market-analysis for the Poly×Kalshi thread. Wang-Transform pricing is the single most interesting *new idea*.
