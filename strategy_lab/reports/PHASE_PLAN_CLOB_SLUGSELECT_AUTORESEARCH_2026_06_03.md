# Next-Phase Plan — CLOB-tape slug-selection, exit-scalp generalization, oracle-basis, autoresearch — 2026-06-03

## 0. Hard priors (do NOT relitigate — proven this session)
- **Direction prediction at fire time is efficient-market-dead.** TA features AUC 0.51 (no info); microstructure
  features AUC 0.78 **and still lose money** (priced-in trap). Any new model that outputs "which side wins on a
  hold-to-resolution bet" will fail. **Every workstream below targets execution, relative-value, or
  tradeability — never raw direction.**
- **The one real edge = the intra-window EXIT-SCALP** (buy cheap lag-token, sell the reprice). Exit-timing ML
  already adds +$0.90/tr (lockbox CI>0). Generalizing/feeding this edge is higher-EV than hunting new direction.
- **Validation spine (non-negotiable):** ws_s anchor + asof_strict; engine_v2 10Hz fills + 0.07 winner-only fee +
  cross-token spread; metric = $/tr-after-fee with bootstrap CI>0 + permutation p (NEVER AUC/WR); purged
  walk-forward + lockbox-touched-once; live shadow ≥200 fires + CI>0 before capital.

## 1. The new data we have NOT mined (the reason this phase exists)
| source | size / coverage | what it unlocks |
|---|---|---|
| **CLOB trades tape** `trades_polymarket/{btc,eth,sol}` | BTC 42.8M / ETH 11.3M / SOL 5.0M rows, ~35.8d, per-slug per-outcome `price/size/side/trade_id/ts` | **NEVER used for modeling.** Slug-level informed-flow, trade imbalance, aggression, large-trade timing, price-impact, trade-VWAP-vs-book. The F2 slug-selector's missing piece. |
| **Live shadow/production fills** `trading.events` (5+ day sleeves) | 1.4M events, real fills + real PnL, dozens of sleeves | A real labeled OOS dataset — meta-label which LIVE conditions actually pay (not backtest). |
| **cex_futures** ticker/klines (4 exch perp) | funding_rate + open_interest + mark/index, growing (~2–7d now → weeks soon) | Spot×perp basis + funding for the oracle-lag direction angle. |
| **Years of BTC klines** `binance_vision_klines` | 1y+ OHLCV 1m–1d | Regime/vol pretraining ONLY. Will NOT crack direction (efficient). Be honest about its ceiling. |

## 2. Workstreams (priority order)

### W1 — CLOB-tape SLUG-SELECTION model ⭐ (the big unused lever)
- **Hypothesis:** the CLOB trade tape reveals *which windows are worth trading* — informed flow (early
  aggressive buys, large size, one-sided imbalance, price-impact) concentrates in a minority of slugs. This is
  tradeability/selection, NOT direction.
- **Targets (relative-value, not raw outcome):** (a) P(this slug's lag-token reprices ≥X before decay) — feeds
  the scalp; (b) which side smart-money is taking early (trade-flow imbalance in first N seconds) as a *prior*,
  combined with the entry-vwap so we only act when our prob ≠ market price.
- **Features (causal, at/around ws_s):** per-slug trade count, $volume, buy/sell size imbalance, aggressive-trade
  ratio (taker side), largest-trade size, time-to-first-large-trade, trade-VWAP vs book mid, price-impact per
  $1k, inter-trade-time, cross-token (Up vs Down) flow asymmetry.
- **Method:** XGBoost/RandomForest primary (tabular, small-n); Linear/Logistic baseline. SVR only for the
  continuous reprice-magnitude target. Purged WF + lockbox; label = scalp PnL-after-fee (selection) or
  reprice-magnitude (regression).
- **Value:** HIGH — new data, attaches to the proven scalp, and is the one path the F2 verdict said we lacked.
- **First deliverable:** `build_clob_flow_features(slug, ws_s)` + join to the scalp cache → does a slug-selector
  lift scalp $/tr on the lockbox?

### W2 — Exit-scalp GENERALIZATION (broaden the one real edge) ⭐
- **Hypothesis:** the exit-scalp is an EXIT edge — it may rescue OTHER entries that buy a cheapish token
  (momo, sniper, prewindow), not just the lag-taker. And CLOB-flow features should sharpen the exit timing.
- **Tests:** (a) apply `TIME+45/60` + the ML exit policy to momo/sniper fire universes from `trading.events`;
  (b) add CLOB-flow + the W1 slug score as features to the exit-timing model (v2 of the ML exit) — the oracle
  ceiling was +$18.5/tr so there's headroom; (c) scalp ONLY on W1-selected high-reprice slugs.
- **Method:** reuse `engine_v2` + the exit cache pipeline; XGBoost exit model v2 (path + physics + CLOB-flow + slug-score).
- **Value:** HIGH — compounds the proven edge with the new data; low marginal infra (cache pipeline exists).

### W3 — Oracle-lag / CL-basis direction signal (the one direction angle not yet proven dead)
- **Hypothesis:** Chainlink RTDS *lags* spot; the next oracle tick's direction is partly foretold by
  **Binance-spot vs cex_futures-perp basis + funding + the spot move since the last CL update**. This is a
  cross-venue lead-lag / microstructure-of-the-oracle signal, NOT price-TA on a single series.
- **Features (causal at ws_s):** chainlink-vs-binance basis, binance-spot vs perp-mark basis, funding_rate, OI
  delta, spot return since last CL tick, CL update staleness. (The lag-taker already half-does this with
  Binance-1s; this upgrades the oracle model.)
- **Method:** XGBoost; gate the bet on `model_prob − entry_vwap > margin` (relative-value, fee-aware).
- **Value:** MEDIUM — direction is mostly dead, but the *oracle-mechanics* angle (we predict the next CL print,
  not the market) is the one place a real lead-lag could survive. cex_futures needs ~2–4 more weeks of data.
- **Caveat:** if this just reproduces AUC-high/$/tr-negative, kill it fast (it's the trap again).

### W4 — Live-shadow meta-labeling (use the real fills)
- **Hypothesis:** 5+ days of real production fills (`poly_updown_resolution`) are a cleaner OOS judge than
  backtest. Meta-label which live (sleeve × hour × vwap × regime) cells actually pay, and auto-build a kill/keep
  + sizing layer (the agentic meta-allocator from the ML plan).
- **Method:** RandomForest/XGBoost on live event features; output a per-sleeve daily reweight.
- **Value:** MEDIUM — turns the 215-sleeve manual audit into a recurring automated allocator.

### W5 — RL / optimal-stopping for EXIT timing (the right home for RL)
- **Hypothesis:** "when to sell" is a sequential optimal-stopping problem → RL's natural domain (NOT direction).
- **Method:** OFFLINE/fitted-Q or a learned stopping policy on the cached 10Hz exit paths (state = current
  profit/momentum/elapsed/flow; action = hold/sell; reward = realized scalp PnL). 38d is sample-thin → keep it
  small, regularize, validate on lockbox vs the ML-exit classifier. **Do NOT do online RL on live money.**
- **Value:** MEDIUM — may beat the greedy classifier exit; bounded downside (it's still just an exit policy).

### W6 — autoresearch harness (the meta-layer that runs W1–W5 overnight)
- **Adopt Karpathy's pattern:** one editable candidate file + a fixed-budget run + a single keep/discard metric +
  an autonomous agent loop, with a human-authored `program.md`.
- **Map to us:** candidate file = a feature/gate/exit-policy definition; "5-min run" = one `engine_v2` backtest
  on the cache/fire-universe; **metric = lockbox $/tr-after-fee with bootstrap CI>0** (our fitness already
  exists); loop = agent proposes → backtest → keep iff lockbox improves AND CI excludes 0 → log → repeat. Run on
  the RTX 3060 box overnight; XGBoost `device=cuda` for fast fits.
- **Guardrails (our hard lessons baked into `program.md`):** reject any candidate that wins on WR/AUC but not
  $/tr; enforce purged-WF + lockbox; require permutation p; cap multiple-testing with deflated significance;
  auto-flag asset-confounds (Block-2b lesson). This prevents the agent from rediscovering the priced-in trap.
- **Value:** HIGH leverage — turns W1–W5 hypothesis search autonomous; this is the "run multiple times on our
  best strategies" the operator asked for, done safely.

## 3. Verdict on every method/idea you named (honest placement)
| idea / method | where it fits | priority |
|---|---|---|
| **CLOB-trade slug selection** | W1 — the headline new lever | ⭐ do first |
| **Exit-scalp on other gates + slug-selection** | W2 | ⭐ do first |
| **Oracle-lag CL-basis (Binance × futures)** | W3 | 🟡 after cex_futures matures |
| **Decision Trees / Random Forest / Linear/Logistic** | primary/baseline models in W1–W4 (tabular, small-n) | ✅ use as tooling |
| **SVR (support-vector regression)** | continuous targets only (reprice magnitude, exit time) | 🟡 baseline |
| **Reinforcement Learning** | W5 — exit-timing optimal-stopping ONLY (not direction, not online) | 🟡 bounded |
| **LSTM** | only on a genuine sequence (CLOB-trade stream, 10Hz exit path); expect XGBoost-on-features to win on 38d | ⚪ secondary/experimental |
| **MACD / Bollinger / MSW** | cheap extra features in any tabular model; BarContext already has MACD | ⚪ low novelty, include free |
| **Years of BTC klines** | regime/vol pretraining ONLY; will NOT crack direction (efficient) | ⚪ limited, honest ceiling |
| **autoresearch (Karpathy)** | W6 — the overnight meta-search harness with our lockbox fitness | ⭐ build to run W1–W5 |

## 4. Sequencing & first concrete steps
1. **W1 step 1:** build `build_clob_flow_features(slug, ws_s)` on `trades_polymarket`; join to the existing scalp
   cache; test whether a slug-flow selector lifts scalp lockbox $/tr (CI>0). ← start here, biggest new lever.
2. **W2 step 1:** add CLOB-flow + slug-score to the exit-timing model (ML-exit v2); re-measure vs fixed+45/60.
3. **W6 scaffold:** stand up the autoresearch harness (candidate file + `engine_v2` lockbox fitness + keep/discard
   loop + guardrail `program.md`) so W1/W2 feature search runs autonomously overnight on the 3060.
4. **W3 (parallel, data-gated):** start logging/accumulating cex_futures basis; revisit in ~2 weeks.
5. **W4/W5:** after W1/W2 prove the CLOB data carries signal.

## 5. Risk / discipline
- The #1 risk is the agent (or us) rediscovering the priced-in trap with fancier data. **The lockbox $/tr-after-fee
  fitness + permutation + asset-confound check are the antibodies — bake them into every run and into autoresearch's
  `program.md`.** Slug-selection must target tradeability/reprice/relative-value, never raw outcome.
- CLOB-tape is in-sample to the same 35d window as everything else → forward shadow remains the final gate.

## Source
Data peek (trades_polymarket schema/coverage), `karpathy/autoresearch` (README/How-it-works), and this session's
proven results: `SESSION_FINDINGS_2026_06_03_ML_SCALP_PHYSICS.md`, `META_LABELER_V2_MICROSTRUCTURE_2026_06_03.md`,
`EXIT_TIMING_MODEL_2026_06_03.md`, `ML_AGENTIC_PHASE_PLAN_2026_06_03.md`.
