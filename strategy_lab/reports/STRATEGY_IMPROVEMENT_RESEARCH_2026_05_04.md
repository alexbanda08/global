# Strategy Improvement Research — 2026-05-04

## Scope

1. Inventory: what engines + data we already have.
2. Web research: state-of-the-art short-horizon crypto direction signals + Polymarket-specific edges.
3. Gap analysis: what we have vs what literature says works.
4. Ranked candidate improvements (top 3) for implementation.
5. SOL V3 fix proposal (per TV agent's audit).

---

## 1. Inventory

### Engines (44 Python scripts)

**v4_signals/ (21 scripts):**
| Script | Purpose | Status |
|---|---|---|
| phase1_hour_of_day.py | Hour blocklist (UTC {1,16,22}) | shipped to V3.2 |
| phase2_clob_imbalance_v2.py | Polymarket CLOB imbalance (ETH IC=+0.082) | partial — never live |
| phase3_macro_block_strict.py | Macro 2-of-3 alignment | shipped to V3.2 |
| phase4_signal_quality_kelly.py | Kelly sizing | reference only |
| phase5_liq_feed.py | Binance liq quiet gate ($10k) | shipped (disabled live) |
| phase6_confidence_calibration.py | Platt scaling | scaffold, deferred |
| v4a_signal.py + v4a_extended_tests.py | Funding/OI features | REJECTED (V4A_FUNDING_OI_VERDICT) |
| v4c_feature_join.py + v4c_llm_classifier.py | LLM event-decisor | scaffold, deferred |
| derivatives_zscore/ | derivative z-score features | unclear status |
| fetch_funding_oi.py + fetch_news_sentiment.py | Data pulls | utility |
| sizing_analysis.py | Liquidity caps | reference |
| per_sleeve_detail / shadow_*  / v1_v2_v3_results / v3_2_combined_test | Analysis tools | reference |

**v2_signals/ (19 scripts):**
| Script | Purpose |
|---|---|
| build_signal_a/b/c + build_stack | V2 signal stack (prob_a/b/c + meta) |
| portfolio_gauntlet (20K LOC) | Portfolio search |
| covered_call / maker_both_sides / cross_asset_leadlag / vol_regime / multi_horizon_forward_walk / entry_timing / exit_variants | Various backtests |
| v3_compounding_sim + v3_profit_projection | Bankroll sim |
| sim_vs_live_recon | Live reconciliation |

**strategy_lab root (40+ scripts):**
- `polymarket_build_features.py` (the V3 feature builder)
- `polymarket_signal_grid_realfills.py` (book-walked fills)
- `polymarket_extract_*.sql` (8 SQL extractors)
- `kronos_*.py` (transformer scaffold — Kronos model on Polymarket)
- Many `build_*.py` PDF/dashboard generators

### Data assets

**Local (`strategy_lab/data/polymarket/` — 336 MB):**
- `{btc,eth,sol}_book_depth_v3.csv` (~85-92 MB each, top-10 each side, 10s buckets) — STALE 2026-04-29 19:30 UTC
- `{btc,eth,sol}_trajectories_v3.csv` (~22-26 MB each, first/last/min/max bids+asks per bucket)
- `{btc,eth,sol}_features_v3.csv` (~1.1 MB each, 1 row per slug, ~17 features)
- `{btc,eth,sol}_markets_v3.csv` (~830 KB each, market-level metadata)
- `{btc,eth,sol}_flow_v3.csv` (~100-200 KB each)

**Local (`data/v4/`):**
- `funding/{6 syms}.parquet` — Binance funding history
- `oi/{6 syms}.parquet` — Binance OI 5min metrics
- `sentiment/` — F&G + Reddit posts
- `calibration/platt_v1.json` — Platt scaling coefs
- `refresh_2026_05_02/mr_extended.csv` — fresh resolutions through 2026-05-01 16:00 UTC (5,379 rows)
- `shadow_trades_2026_05_02/{vps2,vps3}.csv` — fresh paper trades through 2026-05-04 17:31 UTC (10,378 rows)

**VPS2 collector (TimescaleDB hypertables, top 25 chunks ≈ 75 GB):**
- `orderbook_snapshots_v2` — 11.7M rows since 2026-04-27 (top-21 each side, all polymarket UpDown)
- `market_resolutions_v2` — 5,379+ resolutions
- `binance_klines_v2` — 1y of 1m/5m/15m/1h/4h/1d for BTC/ETH/SOL
- `binance_liquidations_v2` — only 5 days
- `binance_metrics_v2` — OI + L/S + taker ratios
- `binance_funding_rate_v2` — funding history
- `hyperliquid_liquidations_v2` — 12 months HL liq, all major coins
- `hyperliquid_trades_v2` — HL trade prints
- `hyperliquid_funding_v2` + `hyperliquid_klines_v2` + `hyperliquid_metrics_v2`
- `trades_v2` — 6.4M Polymarket trade prints
- `oracle_prices_v2` — Chainlink-style oracle feed
- `onchain_fills_v2` — On-chain Polymarket fills
- `cryptocap_dominance_v2` — Total market cap dominance feed
- `liquidations_v2` — generic table (?)

**Critical gap:** we do NOT have `binance_orderbook_v2` (no Binance LOB). All our crypto-side OFI/microstructure work would need Binance trades_v2 + the polymarket book.

---

## 2. Web research findings (state-of-the-art)

### Top signals validated by academic literature

| Rank | Signal | Source | Strength |
|---|---|---|---|
| 1 | **Order Flow Imbalance (OFI)** | Cont/Kukanov/Stoikov 2014; arXiv 2602.00776 (CatBoost SHAP top feature across BTC/LTC/ETC/ENJ/ROSE) | near-linear with short-horizon returns |
| 2 | **VWAP-to-mid deviations** | arXiv 2602.00776 SHAP analysis | asymmetric, microstructure reversion |
| 3 | **Multi-level depth imbalance** | arXiv 2506.05764 | cumulative depth imbalance precedes mid-price moves |
| 4 | **Trade Flow Imbalance (TFI)** | Markwick blog; multiple papers | `(buy_vol - sell_vol)/total_trades` complement to OFI |
| 5 | **Imbalance momentum (1st/2nd derivative)** | DeepLOB literature | rate-of-change of imbalance is itself predictive |
| 6 | **Realized vol + Garman-Klass vol** | MDPI 2025 framework | regime tagger more than directional signal |
| 7 | **Hawkes point process on order arrivals** | arXiv 2312.16190 | confirms base imbalance value, marginal lift |
| 8 | **Kronos / DeepLOB transformer** | arXiv 2506.05764 | "better inputs > deeper models" — not the headline win |

### Polymarket-specific edges

| Edge | Evidence | Notes |
|---|---|---|
| **Oracle latency** | Chainlink updates BTC every ~10-30s; resolution uses snapshot at exact end → 2-5s exploitable lag | Hard to monetize without sub-second infra |
| **Last-second dynamics** | 15-20% of 5m periods resolve based on final-10s movements | Argues for late-entry strategies |
| **Polymarket OWN orderbook imbalance** | Generic prediction-market OFI literature | We have the data (orderbook_snapshots_v2, top-21 levels) |
| **Cross-platform arbitrage** | $40M extracted Polymarket→Kalshi 2024-2025 (arXiv 2508.03474) | Out of scope: we're Polymarket-only |
| **Confidence-thresholded execution** | MDPI 2025: 82.68% direction accuracy at 11.99% market coverage | Highly applicable to our quantile filtering |

### Key academic insight

> "Order flow at the daily horizon may include uninformed traders... Aggregating order flow over one week mitigates the effect of market microstructure noise. **This implies that at very short horizons (like 5 minutes), microstructure noise is significant and requires careful denoising.**"

We're trading 5-minute horizons → we are deep in the noise regime. This validates why our signals are weak and argues for **(a) signal aggregation across multiple weak features into an ensemble, and (b) confidence-threshold execution.**

---

## 3. Gap analysis — what we have vs what works

| Signal class | Have? | Tested? | Works? |
|---|---|---|---|
| Polymarket CLOB imbalance (static) | yes (orderbook_snapshots_v2) | yes (phase2) | partial — ETH only IC=+0.082 |
| **Polymarket CLOB imbalance MOMENTUM** | yes (data) | **no** | **gap** |
| Polymarket multi-level depth imbalance (top-21 cumulative) | yes (data) | **no** (only top-10 used) | **gap** |
| Binance trade flow imbalance | partial (trades_v2 on VPS2) | **no** | **gap** |
| Binance OFI (order book) | **NO LOB DATA** | n/a | data gap |
| VWAP-to-mid deviation (Polymarket) | yes (data) | **no** | **gap** |
| Realized vol regime gate | yes (klines) | partial (vol_regime_backtest) | unclear |
| Funding/OI features | yes (parquet) | yes (v4a) | REJECTED |
| LLM event-decisor | scaffold | no | deferred |
| Confidence-thresholded execution | no | no | **major gap** — only quantile-thresholded today |
| Multi-asset universal model | no (per-asset only) | no | **gap** — literature says feature importance is universal |
| Hawkes point process | no | no | low priority |
| Cross-platform arbitrage (Kalshi) | no | no | out of scope |

**Three biggest leverage gaps:**
1. **Polymarket CLOB imbalance MOMENTUM** — same data, ~30 min implementation, builds directly on Phase 2.
2. **Binance trade flow imbalance from trades_v2** — we have 6.4M Polymarket trades but probably also Binance trades; need to confirm.
3. **Confidence-thresholded execution / meta-classifier** — combine V3 quantile + Phase 2 imbalance + (new) momentum into a calibrated probability, fire only when p̂ > 0.60.

---

## 4. Top 3 candidate improvements (ranked)

### #1 — **Polymarket CLOB Imbalance Momentum** (PHASE 7)

**Hypothesis:** Static CLOB imbalance has weak edge (Phase 2 IC=+0.082 ETH only). The DERIVATIVE of imbalance (2-min slope) should be stronger because it captures the rate of book-pressure buildup, not the static state.

**Implementation:**
```python
# At signal time t, compute:
imb_t = (sum_bid_size_top5 - sum_ask_size_top5) / (sum_bid_size_top5 + sum_ask_size_top5)
imb_slope_2m = (imb_t - imb_{t-2min}) / 120  # imbalance change per second
imb_slope_5m = (imb_t - imb_{t-5min}) / 300

# Features per (slug, signal_time): imb_t, imb_slope_2m, imb_slope_5m
# Backtest: IC against outcome_up, per asset, per direction
```

**Data needed:** book_depth_v3 CSVs we already have (just refresh to 2026-05-04). 5380 markets × 30 buckets = 161K rows of orderbook samples for derivative computation.

**Expected effort:** 4 hours (build features + IC backtest + regime check).
**Risk:** Low — pure feature engineering on existing data.
**Expected lift:** +5-10pp hit rate on top decile if literature transfers.

### #2 — **Confidence-Thresholded Meta-Classifier** (PHASE 8)

**Hypothesis:** V3 quantile + V3.2 gates + Phase 2 imbalance + new imbalance-momentum are weak alone but uncorrelated. A logistic regression / XGBoost meta-classifier on these features should give a calibrated win-probability. Fire only when p̂ > 0.60 (or 0.65 for live).

**Implementation:**
```python
# Features per market signal: ret_5m, ret_15m, ret_1h, |ret_5m| quantile,
# clob_imb_t, clob_imb_slope_2m, hour_of_day, in_macro_2of3, asset_dummy,
# realized_vol_15m, taker_buy_ratio_5m
#
# Target: outcome_up (binary)
# Model: XGBoost binary classifier, time-series CV (3-fold rolling)
# Calibration: isotonic regression on validation fold
# Trade rule: fire if p_pred > THRESHOLD; choose THRESHOLD on validation set to maximize EV
```

**Data needed:** all features we already have + new imbalance momentum + outcomes from `mr_extended.csv`.

**Expected effort:** 1 day (feature join + XGBoost training + calibration + backtest).
**Risk:** Medium — overfitting risk on small sample (5,379 resolutions); needs proper time-series CV.
**Expected lift:** Per MDPI 2025 framework, **+30pp accuracy** at 12% market coverage. For our case probably +5-10pp at ~30% coverage.

### #3 — **Polymarket Trade Flow Imbalance** (PHASE 9)

**Hypothesis:** Imbalance of buy-YES vs buy-NO trades on Polymarket itself (not just the orderbook) reveals informed flow. We have 6.4M `trades_v2` rows on VPS2.

**Implementation:**
```python
# At signal time t, in last 2-min window:
poly_tfi_2m = (sum_buy_yes_volume - sum_buy_no_volume) / total_volume
poly_tfi_5m = same over 5min
poly_trade_count_2m = N trades in 2min (proxy for activity)

# Use as features in meta-classifier (#2) OR as standalone gate
```

**Data needed:** `trades_v2` table on VPS2 — pull join to market_resolutions_v2 by slug.

**Expected effort:** 4-6 hours (extract trades + compute features + backtest).
**Risk:** Medium — Polymarket trade frequency uneven, could be sparse for specific 2-min windows.
**Expected lift:** Cited in arXiv 2602.00776 as top-3 SHAP feature for crypto — should transfer to prediction markets.

### Also worth doing (quick wins)

- **Multi-asset universal model** — train ONE classifier on BTC+ETH+SOL combined data (per literature, features are universal). Better generalization on small samples.
- **Realized volatility gate** — only fire when 15m realized vol is in middle quantile (avoid both dead and chaotic regimes).
- **Refresh book_depth CSVs** — already have SQL, just need to run delta extract (~10 min).

---

## 5. SOL V3 family fix (per TV agent audit)

TV agent confirmed: SOL V3/V3.1/V4 fire 0 orders because:
1. SOL Polymarket UpDown 5m books have spread ≥ 2% essentially always (median 4-6%).
2. `V3_SPREAD_FILTER_PCT = 0.02` is BTC-calibrated; structurally too tight for SOL.
3. SOL V3/V3.1/V4 carry multi-horizon AND filter, sampling fewer bars; none happen to be ≤2%-spread.

**Concern A** — V3.2 SOL is paradoxically the LEAST selective (no multi-horizon, macro_2of3 short-circuits true, liq_quiet off, hour-block only 3/24h).

**Concern B** — V3 spread filter at 2% kills SOL entirely.

### Fix proposal

**Two surgical changes (both required for SOL coverage):**

#### Fix A: per-asset spread filter

```python
# polymarket_updown.py — replace single constant with dict
V3_SPREAD_FILTER_PCT = {
    "BTC": 0.02,
    "ETH": 0.02,
    "SOL": 0.025,  # SOL median spread is 4-6%, but 2.5% catches the tightest 5-10% of bars
}

def _v3_spread_filter_for(symbol: str) -> float:
    return V3_SPREAD_FILTER_PCT.get(symbol.upper(), 0.02)
```

Set via env: `TV_POLY_V3_SPREAD_FILTER_SOL=0.025` to make it operator-tunable.

**Expected effect:** SOL V3 fires from 0/day → maybe 5-15/day. Live PnL TBD — backtest first.

#### Fix B: add multi-horizon to V3.2 SOL (restore parity with V3 base)

```python
# polymarket_updown.py line 744 area — extend to v3_2 too
if self.strategy_mode in ("v3_1", "v3_2", "v4") and (sym_upper, tf) in V3_REQUIRE_MULTI_HORIZON:
    aux["require_multi_horizon"] = True
```

**Expected effect:** SOL v3_2 fires drop from 5/1.5d to 0-2/1.5d (matches the other variants). Hit rate likely improves on the few that survive (multi-horizon is a quality filter).

#### Alternative to Fix A: drop SOL from V3 family entirely

Per TV agent: "Accept SOL is BTC-portfolio-only (V3 base BTC is the only working V3-family sleeve right now)."

This is the safer path if you're not ready to widen the spread filter and rebackest. Just remove SOL from the V3 sleeve set; keep `sol_5m_sniper`/`sol_15m_sniper`/`sol_5m_volume`/`sol_15m_volume` as before.

**Recommendation:** Do BOTH Fix A AND Fix B — gives SOL coverage on V3-family, with multi-horizon as quality filter so V3.2 doesn't degrade. Backtest the per-asset spread filter on the extended polymarket window (5,379 markets) before live.

---

## 6. Proposed action sequence (estimated effort)

| # | Task | Effort | Output |
|---|---|---|---|
| 1 | Refresh polymarket book_depth/trajectories/markets to 2026-05-04 | 30 min | refreshed CSVs |
| 2 | Implement Phase 7 — CLOB imbalance momentum + IC backtest | 4 hr | `phase7_clob_imbalance_momentum.py` + report |
| 3 | Pull Polymarket trades_v2 from VPS2 + build TFI features | 2 hr | `data/v4/poly_trades_2026_05_04/` + feature CSV |
| 4 | Implement Phase 8 — XGBoost meta-classifier with calibration + backtest | 1 day | `phase8_meta_classifier.py` + report |
| 5 | Implement SOL V3 fix (per-asset spread filter + V3.2 multi-horizon) | 1 hr controller code + 2 hr backtest validation | code patch + spec for TV agent |
| 6 | Update NEXT_SESSION_START_HERE pointer doc | 30 min | doc |

**Total:** ~2.5 days of focused work for full Phase 7+8 + SOL fix.

**Quickest path to value:** Steps 1+2+5 in parallel (~5 hours total) gets us a new signal tested AND SOL coverage restored. Step 4 (meta-classifier) is the bigger swing — requires careful CV and calibration, defer until Phase 7 + new data is in.

---

## Sources

- [Cryptocurrency Microstructure (arXiv 2602.00776)](https://arxiv.org/html/2602.00776v1) — CatBoost + SHAP, BTC/LTC/ETC/ENJ/ROSE
- [Microstructural Dynamics in Crypto LOBs (arXiv 2506.05764)](https://arxiv.org/html/2506.05764v2) — DeepLOB benchmarks; "better inputs > deeper models"
- [Order Flow Image Representation (arXiv 2304.02472)](https://arxiv.org/html/2304.02472v2) — short-term volatility forecasting
- [Confidence-Threshold Framework (MDPI 15/20/11145)](https://www.mdpi.com/2076-3417/15/20/11145) — 82.68% accuracy at 11.99% market coverage
- [Order Flow and Cryptocurrency Returns (ScienceDirect)](https://www.sciencedirect.com/science/article/pii/S1386418126000029) — order flow has permanent effect on returns
- [Order Flow Imbalance HFT walkthrough (Dean Markwick)](https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html) — practical implementation
- [Mathematical Execution Behind Prediction Market Alpha (substack)](https://navnoorbawa.substack.com/p/the-mathematical-execution-behind) — OBI explains 65% of short-interval price variance
- [Polymarket 5-min crypto market edges (Medium / Benjamin-Cup)](https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196) — last-second dynamics, oracle latency
- [Hawkes-based crypto forecasting (arXiv 2312.16190)](https://arxiv.org/html/2312.16190v1) — base imbalance as candidate regressor
- [Price Impact of OBI in Crypto (Towards Data Science)](https://towardsdatascience.com/price-impact-of-order-book-imbalance-in-cryptocurrency-markets-bf39695246f6/)
