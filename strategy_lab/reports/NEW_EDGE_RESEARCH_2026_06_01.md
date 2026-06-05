# New-Edge Research — 5m/15m Crypto Prediction Markets — 2026-06-01

**Synthesized from 49 adversarially-verified novel edge candidates.**
Market: Polymarket binary Up/Down on BTC/ETH/SOL at 5m & 15m horizons.
Resolution: Chainlink Data Streams (strike at ws_s, settle at window-end).
Execution: Ireland VPS → London AWS CLOB, <2ms RTT, 85ms modeled latency.
Fee model (production-confirmed): `pnl_won = (1-vwap)*shares*(1 - 0.07*vwap)`, loss = `-vwap*shares`.
Backtest primitive: `engine_v2.py` with `LiveMimicConfig` (or `LegacyConfig` for production-mirror).

---

## DEDUP / MERGE NOTES

Before tiering, the following near-duplicate clusters were merged into single entries:

| Kept Entry | Merged / Absorbed |
|---|---|
| **Perp Mark-Index Basis Spike Gate** (g_basis_spike) | CEX Perp Mark-Index Basis Z-Score Spike Gate (g_basis_spike_with) — same mechanism, g_basis_spike is the concrete bitget/gate implementation; g_basis_spike_with is the abstract spec. Kept g_basis_spike as it has verified loader coverage. |
| **Multi-Scale Hawkes Perp Gate** (g_hawkes_perp_imbalance) | Hawkes trade-arrival intensity on Polymarket CLOB trades — different data sources (CEX perp vs Poly CLOB). Both kept as separate entries since data sources differ materially. |
| **HL Mark-Oracle Basis Momentum Gate** | No full merge; structurally different from CEX perp basis (HL internal mark vs oracle vs cross-exchange perp mark vs index). Kept separate. |
| **DVOL spike regime** + **IV term structure slope** + **VRP sizing** | All three require Deribit data (same new collection need). Grouped under TIER 3 "Options Vol Complex" but listed individually. |
| **Seesaw gate** + **Cross-chain negative spillover** + **Rolling BTC-ETH corr-break** + **BTC-ETH vol ratio** | All four are variants of cross-asset regime conditioning. Kept separate; flagged as a cluster. |

Net after dedup: 49 candidates → 47 distinct entries (2 full merges) + 4 cross-asset cluster members.

---

## TIER DEFINITIONS

- **TIER 1** — High mechanism plausibility + canonical data fully available + can backtest today → build/backtest next sprint.
- **TIER 2** — Promising mechanism + data mostly available or trivially collectable + pilot-window limitation only → worth building with caveats.
- **TIER 3** — Speculative mechanism OR requires new data collection (Tardis, Deribit WS, multi-week accumulation) → research queue.

**Breakeven WR reference:** At entry vwap=0.50, need WR ≥ 53.6% after 0.07 fee to break even. At vwap=0.65, need WR ≥ 56.4%.

---

## SECTION A: NEW STRATEGIES (From-Scratch Signal Lines)

These are standalone strategy concepts, not gate overlays.

### A1. HL Short-Liquidation Cascade — 60s Window (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_hl_short_liq_rolling_cascade` (60s variant) |
| **Type** | Strategy / primary gate |
| **Tier** | TIER 1 |
| **Mechanism** | Rolling 60s sum of HL "Close Short" + "Open Long" liquidation notional (price×size) ending at ws_s. Gate fires True (predict UP) when sum > threshold. Key finding: 60s window gives WR=57.9%, p=0.041 (BTC+ETH pooled, n=24,699 fires, Apr24-May27). The deployed g_a2_hl_short_cascade uses a 300s window which gives WR 49-52%, p>0.24 — not distinguishable from noise. |
| **Why edge at 5-15m** | Forced market buys from the HL liquidation engine create short-term directional momentum. The 60s window captures the tail of the impulse before it decays; the 300s window averages over the recovery. Empirically verified on canonical data with p=0.041 pooled. |
| **Data / Loaders** | `load_hyperliquid_liquidations_full(asset)` — 5.27M rows back to 2025-05-25. Filter `dir in ['Close Short','Open Long']`, `method=='market'`. Notional = `price * size`. Full overlap with resolution window Apr24-May27. `load_resolutions()` for outcomes. |
| **Backtest Sketch** | (1) Load HL liqs for BTC+ETH. (2) For each resolution slug at ws_s, compute `rolling_sum_notional` over [ws_s-W, ws_s], W in {60, 120, 240}. (3) Gate UP when sum > T, sweep T in {1k, 10k, 50k}. (4) Score via `load_resolutions()` outcome=='Up'. (5) engine_v2 LiveMimicConfig for PnL. (6) G1 permutation (10k), G3 bootstrap. PRIMARY BENCHMARK: W=60/T=10k → WR=57.9%, p=0.041 (pre-established). SOL excluded (45.2% WR, wrong direction). |
| **Notes** | OI-filter add-on (cex_futures_ticker OI) NOT feasible — HL data ends May 27, cex_futures starts May 30. Exclude from initial backtest. |
| **Sources** | HL liq gitbook; strategy_lab/reports/FUNDING_OI_2026_05_26.md; vps3_engine_snapshot_2026_06_01/strategies/polymarket/sniper_v5_gates.py (g_a2 at line 2199) |

---

### A2. Cross-CEX Liquidation Cascade Gate — Gate.io + OKX (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_liq_cascade_okxgate` |
| **Type** | Strategy / primary gate |
| **Tier** | TIER 1 |
| **Mechanism** | From `cex_futures_liquidations.parquet` (gate+okx only, 856 rows over 2.8 days): rolling 300s sell-side liquidation notional ending at ws_s. Gate UP when sell_liq_sum > $50k (forced long liquidations → overshoot → contrarian UP reversal). Gate DOWN when buy_liq_sum > $50k (forced short liq → overshoot → contrarian DOWN). Gate.io + OKX events average $28k mean, max $954k — orders of magnitude larger than HL's $419 median. 285 BTC+ETH sell ticks and 161 buy ticks above $50k in 2.8 days. |
| **Why edge at 5-15m** | Structural same as g_a2 (HL cascade, 90.7% WR n=54), but with 10-100x larger liquidation events from institutional CEX perps. Exhaustion-reversal (contrarian) formulation is the correct economic interpretation of cascade overshoot. Largest events: $954k OKX ETH, $731k OKX BTC. |
| **Data / Loaders** | `load_cex_futures_liquidations()` — columns: exchange, time_exchange_us, symbol_id, side ('sell'=long-liq, 'buy'=short-liq), notional_usd. Filter symbol_id in BTC_USDT/ETH_USDT, exchanges ['okx','gate']. Rolling sum by side at ws_s. Data: May 29 – Jun 1 (2.8 days). |
| **Backtest Sketch** | Load liq for gate+okx BTC+ETH. Sort by time_exchange_us. For each 5m/15m slug at ws_s: `sell_sum_300s = sum(notional_usd where side=='sell' and time in [ws_s-300s, ws_s])`. Gate UP = sell_sum > 50k (contrarian). Test aligned AND contrarian variants. Threshold sweep: $25k/$50k/$100k. Engine_v2 LiveMimicConfig $25 notional. G1+G3. Expected n ~40-80 per variant in 2.8d window — exploratory but effect size should be detectable if structural cascade effect holds. Cross-validate: compare with HL liq pattern on overlapping dates. |
| **Notes** | Pre-register n<50 as exploratory. Accumulate more cex_futures_liquidations daily. bybit/bitget collectors empty — gate+okx only. |
| **Sources** | https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves; https://medium.com/@XT_com/bitcoin-futures-market-microstructure-liquidation-cascades-funding-regimes-and-open-interest-978b107b4889 |

---

### A3. Seesaw / Cross-Asset Cluster (TIER 3 — Low Plausibility in Current Regime)

The four cross-asset strategies below share a common data path (klines_1s BTC+ETH+SOL) and are grouped here. All are **TIER 3** because our own BTC-ETH leadlag study shows positive spillover dominates (corr 0.87-0.89 at lag-0), which directly contradicts the seesaw premise.

| Name | Mechanism Summary | Verdict |
|---|---|---|
| Seesaw-effect fade (BTC big-move → ETH/SOL opposite-dir) | Top-quintile BTC return → bet DOWN on ETH/SOL via capital rotation | TIER 3: directly contradicted by g_cross_asset_lag_confluence (66.8% WR UP). |
| Cross-chain negative spillover (BTC/ETH surge → SOL DOWN) | BTC/ETH surge + SOL lagging → SOL DOWN bet | TIER 3: plausible mechanism, but 0-5s transmission at 1s resolution means window closes before fire. |
| Rolling BTC-ETH correlation-break regime gate | Low rolling_corr_30 = ETH/SOL idiosyncratic regime → own-asset signals cleaner | TIER 2: the regime conditioning logic is sound; cheaply testable. |
| BTC-ETH realized vol ratio gate | rv_eth/rv_btc ratio as cross-asset vol dispersion regime | TIER 2: orthogonal to g_vol_high; cheap to compute. |

The two TIER 2 cross-asset gates (correlation-break and vol-ratio) are detailed in Section C (Gates).

---

## SECTION B: NEW INDICATORS / SIGNALS

Standalone signal generators that can be used as directional predictors or gate inputs.

---

### B1. Polymarket VPIN — Bulk-Volume-Clock Informed-Flow Detector (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `poly_vpin` |
| **Type** | Indicator → gate |
| **Tier** | TIER 1 |
| **Mechanism** | Partition Polymarket CLOB trades (load_trades) into equal-USD-volume buckets of V=$200 each. For each bucket: `buy_fraction = (sum UP-side taker buys in bucket) / bucket_notional`; `VPIN_k = |2*buy_fraction - 1|`. Rolling VPIN = mean of last 20 buckets computed at ws_s from trades in prior 60s. Gate fires when VPIN > threshold AND `sign(net_up_usd - net_dn_usd) == bet_dir`. |
| **Why edge at 5-15m** | VPIN normalizes by volume buckets, making it adaptive to varying trade velocity — unlike the raw net-flow g_b1 gate which uses a fixed dollar threshold. When informed traders split a binary market position into sequential buys, they create detectable volume-clock clustering (Easley et al. 2012). The existing g_b1_poly_flow_aligned already shows +13-20pp WR lift for SOL — VPIN adds the temporal clustering dimension. |
| **Data / Loaders** | `load_trades(asset)` — confirmed: BTC 42.8M rows (Apr26-Jun1), ETH 11M, SOL 5M. Columns: timestamp_us, slug, outcome, side, price, size. Average ~962 trades/5m for BTC — sufficient for 200-USD buckets. `load_resolutions()` for outcomes. |
| **Backtest Sketch** | For each resolution slug at ws_s, filter trades to [ws_s-60s, ws_s]. Sort by timestamp_us. Bucket trades in 200-USD tranches: `bucket_total += price*size`; when bucket_total >= 200, close bucket, record buy_fraction = up_side_usd / 200. `VPIN_k = |2*buy_fraction - 1|`. Rolling mean last 20 buckets. Gate: VPIN > threshold AND sign(net_up_usd - net_dn_usd) == bet_dir. Sweep thresholds {0.25, 0.35, 0.50}. Engine_v2 LiveMimicConfig. Compare vs g_b1_poly_flow_aligned baseline. G1+G3. Run SOL first (cleanest data). |
| **Sources** | https://www.quantresearch.org/VPIN.pdf; https://arxiv.org/pdf/2510.15612 |

---

### B2. KAMA Efficiency Ratio Regime Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_kama_er_kill` / `g_kama_er_pass` |
| **Type** | Indicator → gate |
| **Tier** | TIER 1 |
| **Mechanism** | `ER_N = abs(close[t] - close[t-N]) / sum(|close[i] - close[i-1]|)` on Binance 1s bars. ER in [0,1]: high ER = directional efficiency; low ER = choppy noise. KILL variant: `ER < 0.3` → skip all momo bets. PASS variant: `ER > threshold AND sign(net displacement) agrees with direction`. Sweep N in {30, 60, 120} bars. |
| **Why edge at 5-15m** | Low-ER environments are exactly where momo signals fail: price meanders and Chainlink read at window-end is uncorrelated with ws_s direction. The KILL gate concentrates portfolio in clean directional moves. Conceptually complementary to Hurst (global, 60+ bars) but at a local, reactive 30-120s scale. Existing b1_kama_adaptive_trend.py uses ER on multi-hour perp bars — the Polymarket adaptation at 1s is structurally distinct. |
| **Data / Loaders** | `load_klines(asset, '1s')` or direct `klines_1s.parquet` pyarrow read. 14.11M rows Apr7-Jun1. ER = trivial numpy computation. No new data. |
| **Backtest Sketch** | Compute ER_N on 1s closes ending at ws_s for N in {30, 60, 120}. `g_kama_er_kill = ER_N < 0.3`. `g_kama_er_pass = ER_N > threshold AND direction-aligned`. Engine_v2 LiveMimicConfig on BTC/ETH/SOL 5m. Compare vs g_hurst_trending via G1/G3. Jaccard overlap with g_hurst_trending: if >0.80, the kill gate is redundant. Key test: does g_kama_er_kill provide additive lift over g_hurst alone? |
| **Sources** | https://pineify.app/resources/blog/kaufmans-adaptive-moving-average-indicator-tradingview-pine-script; strategy_lab/strategies/adaptive/b1_kama_adaptive_trend.py |

---

### B3. Realized Semivariance Reversal Kill Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_realized_semivariance_reversal_kill` |
| **Type** | Indicator → kill gate |
| **Tier** | TIER 1 |
| **Mechanism** | `RS+ = sum(r_i^2 for r_i > 0)`, `RS- = sum(r_i^2 for r_i < 0)` over N 1s log-returns before ws_s. `A = RS+ / (RS+ + RS-)`. Kill UP fires when `A > 0.65` (upward vol dominated → exhaustion). Kill DOWN fires when `A < 0.35`. Passes fires where direction aligns with the under-represented semivariance side. Sweep N {60, 120, 300} and threshold {0.60, 0.65, 0.70}. |
| **Why edge at 5-15m** | When RS+ >> RS- in the 60-300s before ws_s, the up-move is likely exhausted and UP is over-priced on the binary market. The KILL framing (drop over-extended fires) reduces false positive rate. Liu et al. (2023, J. Empirical Finance) confirmed RS+/RS- asymmetry predicts reversals in commodity TSMOM. Our g_lm_extreme_against uses a formal jump threshold — semivariance is a softer continuous variant. Zero existing semivariance gate confirmed by codebase grep. |
| **Data / Loaders** | `load_klines_1s(asset)` — same 300-bar window used for Hurst. 40-day window, ~21k BTC+ETH 5m fires × 300 bars = 6.3M rows: feasible. |
| **Backtest Sketch** | At each fire_us, load last N 1s log-returns before ws_s. Compute RS+ and RS-. Compute A. Kill UP when A > threshold; kill DOWN when A < (1-threshold). Sweep N and threshold. Engine_v2 LegacyConfig. Measure WR of surviving fires vs full universe. G1 permutation + G3 bootstrap. Secondary: combination with g_hurst_trending as compound filter. |
| **Sources** | https://www.sciencedirect.com/science/article/abs/pii/S0927539823000245; https://public.econ.duke.edu/~boller/Papers/SemiVar.pdf |

---

### B4. Rogers-Satchell Vol Breakout Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_gk_vol_breakout_gate` (Rogers-Satchell variant) |
| **Type** | Indicator → gate |
| **Tier** | TIER 1 |
| **Mechanism** | `RS_bar = ln(H/C)*ln(H/O) + ln(L/C)*ln(L/O)` per 1m OHLCV bar. Rolling fast window N_fast=6 bars (6min) and slow N_slow=24 bars (24min) ending at ws_s. Gate passes when `RS_fast > P75(RS_slow)` (rolling 24h distribution); blocks when `RS_fast < P25`. Captures genuine intrabar liquidation-wick volatility invisible to close-to-close RV. |
| **Why edge at 5-15m** | RS estimator is 7-8x more statistically efficient than close-to-close vol at equal data length. Large-wick 1m bars indicate liquidation cascades and institutional flow — the same signal as g_a2 but via OHLC ranges which don't depend on the partially-broken HL/CEX liq feeds. Fast/slow ratio captures breakout regime. Existing gk_sigma is computed in panels but never gated. |
| **Data / Loaders** | `load_klines(asset, '1m')` — 66,062 BTC 1m OHLCV rows (price_open, price_high, price_low, price_close) Apr14-Jun1. Need 24 bars before ws_s = 24 minutes. Trivially available. |
| **Backtest Sketch** | At ws_s for each slug, compute rolling RS_fast (N=6) and RS_slow (N=24) using Rogers-Satchell formula. Maintain 24h rolling distribution of RS_slow for percentile rank. Gate: pass when RS_fast > P75(RS_slow), block when < P25. Test BTC/ETH/SOL 5m+15m. Compare vs g_vol_high baseline. G1+G3. Also test directional RS asymmetry: does high RS_fast favor UP vs DOWN? |
| **Sources** | https://portfoliooptimizer.io/blog/range-based-volatility-estimators-overview-and-examples-of-usage/; https://www.quantshare.com/item-197-yang-zhang-extension-of-the-garman-klass-volatility-estimator |

---

### B5. Page-CUSUM Sequential Change-Point Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_cusum_direction` |
| **Type** | Indicator → gate |
| **Tier** | TIER 1 |
| **Mechanism** | One-sided Page-CUSUM on standardized Binance 1s returns within slot [slot_start-120s, ws_s]. `S_t = max(0, S_{t-1} + (z_t - k))` where `z_t = (r_t - mu_hat)/sigma_hat` (rolling 300s stats) and slack k=0.5. Dual accumulator (S_pos, S_neg). Gate = cusum_direction at first crossing AND `S_at_ws_s > h`. Sweep h {0.5, 1.0, 1.5, 2.0}. |
| **Why edge at 5-15m** | Detects the ONSET of a mean-shift in 1s returns within the slot — a sequential test that integrates evidence bar-by-bar rather than a point-in-time slope check. Lorden minimax optimality guarantees fastest detection of a change point. The intra-slot directional impulse is the core of our momo edge; CUSUM provides a statistically grounded detector of that impulse. No CUSUM code anywhere in strategy_lab (verified grep). |
| **Data / Loaders** | `load_klines(asset, '1s')` or direct klines_1s parquet. 300-bar (5min) window. Pure numpy recursive loop O(N). Full canonical window. |
| **Backtest Sketch** | For each resolution row, load 1s bars from slot_start-120s to ws_s. Run dual CUSUM (k=0.5, h in {0.5,1.0,1.5,2.0}). Gate = cusum_direction == outcome_direction AND S > h. Integrate into engine_v2. Tune h on first 20d OOS on remaining 20d. G1 permutation + G3 bootstrap. Check Jaccard overlap with g_trend_slope_strong_with — if >0.85, redundant. |
| **Sources** | https://arxiv.org/pdf/2402.04433; https://www.luxalgo.com/library/indicator/change-point-detection-cusum/ |

---

### B6. Kalman Filter Velocity Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_kalman_velocity_with` |
| **Type** | Indicator → gate |
| **Tier** | TIER 1 |
| **Mechanism** | Two-state Kalman on Binance 1s closes: state=[price_est, velocity_est]. Update: `error = close[t] - price_pred; K = P_pred/(P_pred+R); velocity_est[t] = velocity_pred + K*error`. Q=0.001, R=0.1. Gate: velocity_est > threshold_bps → UP; < -threshold → DOWN. Threshold = q75 absolute velocity per asset from training window. |
| **Why edge at 5-15m** | Minimum-variance unbiased linear estimator of instantaneous trend speed. Unlike g_trend_slope_strong_with (EMA9 slope), Kalman explicitly separates measurement noise (R) from process noise (Q), making it more robust to price spikes while more responsive to sustained directional moves. V4C Range-Kalman strategy uses it on HL perps (4h) but it was never adapted for Polymarket binary gates. |
| **Data / Loaders** | `load_klines(asset, '1s')` — 300-bar rolling window. Pure numpy recursive. Q/R sweep: Q in {0.0001, 0.001, 0.01}, R in {0.1, 0.5, 1.0}. |
| **Backtest Sketch** | Run Kalman on last 300 1s closes ending at ws_s. Extract velocity_est. Calibrate threshold at q75 |velocity| from training window (first 20d). Gate: velocity_est > threshold AND direction aligned. Stack on V5 fires. G1+G3. Compute Jaccard overlap with g_trend_slope_strong_with — if < 0.60, genuine diversification. Sweep Q/R hyperparameters. |
| **Sources** | https://www.mql5.com/en/blogs/post/760279; strategy_lab/strategies_v4.py (V4C range-kalman, HL perps only) |

---

### B7. HAR-RV Vol Surprise Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_har_rv_vol_regime` |
| **Type** | Indicator → gate |
| **Tier** | TIER 2 |
| **Mechanism** | Build HAR-RV: `RV_t = alpha + beta_5*RV_{t-5m} + beta_15*RV_{t-15m} + beta_60*RV_{t-60m}`. Expanding-window OLS calibration per asset. Surprise = `RV_actual / RV_hat`. Pass when surprise > 1.2 (vol shock above multi-scale expectation); block when < 0.8. HAR coefficients recalibrated daily. |
| **Why edge at 5-15m** | HAR-RV is the dominant benchmark for short-horizon vol forecasting. The surprise signal (actual vs multi-scale forecast) captures whether a genuine vol shock occurred beyond the heterogeneous investor consensus — not just that vol is high. A positive HAR surprise signals new regime-triggering information before the binary price has fully adjusted. Requires 60min lookback history — needs 14.11M row 1s klines. |
| **Data / Loaders** | `load_klines_1s(asset)` — 3600 bars per fire for 60min RV. Pre-build per-minute RV panel (vectorizable), then join per fire. Full canonical window available. |
| **Backtest Sketch** | Pre-build RV_5m/15m/60m per-minute panel via rolling std on 1s series. For each fire, extract components from panel. Expanding OLS for HAR coefficients (min 100 prior obs). Compute surprise. Gate pass > 1.2, block < 0.8. Sweep {1.1, 1.2, 1.5}. Engine_v2 LegacyConfig. G1+G3. Compare vs g_vol_high. |
| **Sources** | https://arxiv.org/html/2507.22409v1; https://www.sciencedirect.com/science/article/pii/S0378426624002565 |

---

### B8. Realized Quarticity / Vol-of-Vol Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_realized_quarticity_vol_of_vol` |
| **Type** | Indicator → gate |
| **Tier** | TIER 2 |
| **Mechanism** | `RQ = (n/3) * sum(r_i^4)` over 300 1s bars. `vol_of_vol_ratio = sqrt(RQ) / RV`. Rolling 24h quantile rank. Gate: pass fires where ratio_rank < 0.25 (smooth vol = cleaner signal); block where ratio_rank > 0.75 (chaotic microstructure). |
| **Why edge at 5-15m** | High vol-of-vol means variance itself is unpredictable — individual extreme returns dominate, microstructure is chaotic, and directional signals are noisy. Blocking fires in chaotic regimes concentrates the portfolio in predictable periods. Model-free, purely return-based, computationally trivial. Du (2025, J. Futures Markets) validates vol-of-vol pricing in crypto. Zero quarticity code in arsenal (confirmed grep). |
| **Data / Loaders** | Same as semivariance — `klines_1s.parquet`, 300 bars before ws_s. |
| **Backtest Sketch** | Compute RV and RQ over 300 bars. vol_of_vol_ratio = sqrt(RQ)/RV. Rolling 24h quantile rank. Pass < q25, block > q75. Engine_v2 LegacyConfig. G1+G3. Test intersection with g_hurst_trending as compound filter. Compare vs g_as_stable. |
| **Sources** | https://onlinelibrary.wiley.com/doi/10.1002/fut.70029?af=R; https://arxiv.org/html/2410.15195v2 |

---

### B9. MAMA/FAMA Adaptive Crossover Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_mama_with` |
| **Type** | Indicator → gate |
| **Tier** | TIER 2 |
| **Mechanism** | Ehlers MESA Adaptive Moving Average: Hilbert-Transform phase-based adaptive alpha (0.05–0.5). `MAMA = alpha*price + (1-alpha)*MAMA[t-1]`; `FAMA = 0.5*alpha*MAMA + ...`. Gate: MAMA > FAMA = UP; MAMA < FAMA = DOWN. Also use MAMA-FAMA spread magnitude as confidence scalar. |
| **Why edge at 5-15m** | MAMA alpha adapts to instantaneous phase change rate — less lag than fixed EMA at trend changes. At 1s Binance bars, BTC dominant cycles are ~6-20s; MAMA adapts within a 5m slot. Listed as Priority-3 in docs/research/03_ADAPTIVE_STRATEGY_CANDIDATES.md (B3) but never implemented. Key unknown: Jaccard overlap with g_ribbon_agrees. |
| **Data / Loaders** | `load_klines(asset, '1s')` — 350-bar warmup (first 50 bars unreliable). Implementable via talib.MAMA(FastLimit=0.5, SlowLimit=0.05) or manual Python. |
| **Backtest Sketch** | Compute MAMA/FAMA on last 350 1s closes. Gate: direction-aligned crossover. Stack on V5 fires. G1+G3. Compute Jaccard overlap with g_ribbon_agrees — if < 0.6, genuine diversification. |
| **Sources** | https://www.mesasoftware.com/papers/MAMA.pdf; docs/research/03_ADAPTIVE_STRATEGY_CANDIDATES.md |

---

### B10. Ehlers EACP Adaptive RSI Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_eacp_rsi_strong_with` |
| **Type** | Indicator → gate |
| **Tier** | TIER 2 |
| **Mechanism** | Roofing filter (2-pole HP cutoff=48 + Super Smoother cutoff=10) on 1s closes. Autocorrelation periodogram for lags 10-48 to find dominant cycle Dc. Adaptive RSI = RSI(Dc/2) via simple-mean Wilder. Gate: Adaptive_RSI > 60 (UP) or < 40 (DOWN). |
| **Why edge at 5-15m** | Adapts RSI lookback to current dominant cycle. Near-zero-mean roofed series reduces noise-induced false crossings. Testable on non-F7 sleeves where F7 is not already a gate. Zero EACP code in strategy_lab. |
| **Data / Loaders** | `load_klines(asset, '1s')` — 200-bar warmup. Pure numpy FFT + IIR filter. |
| **Backtest Sketch** | Implement roofing + EACP in numpy. Test as standalone and as add-on to non-F7 sleeves. G1+G3. Compare IC vs fixed F7 RSI(14). |
| **Sources** | https://www.tradingview.com/script/df3Ofxvr-Ehlers-Autocorrelation-Periodogram-Loxx/ |

---

### B11. Bipower Jump-Diffusive Regime Kill Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_jump_diffusive_regime` |
| **Type** | Indicator → kill gate |
| **Tier** | TIER 2 |
| **Mechanism** | Jump fraction `JF5 = max(RV5 - BPV5, 0) / RV5` over 300 1s bars before ws_s. `BPV5 = (pi/2) * sum(|r_t| * |r_{t-1}|)`. Kill entries when JF5 > 0.3. This is a PRIOR-SLOT regime gate — blocks entry when the preceding slot was jump-contaminated. |
| **Why edge at 5-15m** | LEE_MYKLAND_2026_05_26.md confirmed: betting against jump direction (LM-D) loses -$5 to -$16/tr — proving jump regimes produce unreliable directional signals. The prior-slot kill exploits regime persistence. Existing LM gates are same-slot detectors; this is a forward kill. Can reuse `_bipower_window()` from lee_mykland_2026_05_26/build_lm_panel.py. |
| **Data / Loaders** | `klines_1s.parquet` — same 300-bar window. BPV uses consecutive pairs. Reuse numba BPV function from LM panel. |
| **Backtest Sketch** | Compute RV5 and BPV5 per slot. JF5 ratio. Kill when > 0.3. Sweep 0.1/0.2/0.3/0.4. G1+G3. Cross-tab with g_lm_high_stat to confirm orthogonality. |
| **Sources** | https://public.econ.duke.edu/~get/browse/courses/883/Spr16/COURSE-MATERIALS/Z_Papers/BNSJFEC2004.pdf; LEE_MYKLAND_2026_05_26.md |

---

## SECTION C: NEW GATES (Overlays on Existing Sleeves)

Gates that modify when existing sleeve fires are accepted or rejected.

---

### C1. Polymarket Book Depth-Decay Ratio Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_depth_decay_ratio` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | At fire_us - 85ms: `depth_asym = sum_bid_25_levels / sum_ask_25_levels` for UP token. For UP bets: `ratio > threshold` (bids thicker = asks swept by informed buyers). For DOWN bets: invert (ask_depth / bid_depth > threshold). Restrict to late-window entries (offset_s > 60 for 5m; >120 for 15m). Sweep thresholds {1.2, 1.5, 2.0, 3.0}. |
| **Why edge at 5-15m** | arXiv:2604.24366 directly documents SF8 (depth asymmetry near resolution) on 30B Polymarket events. The raw ratio (unlike the normalized imb25) is unbounded and captures the depletion pattern: bids >> asks signals informed ask-sweeping. Existing `g_depth_250_strict` checks absolute floors; `g_imb5_strong_with` normalizes. Neither uses the cross-side total ratio. |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs=set(...), subsample_1hz=False)` — native 10Hz, Apr22-Jun1. All 25 bid/ask size levels available. Simple numpy sum per snapshot. |
| **Backtest Sketch** | At fire_us - 85ms: `bid_total = sum(bsz[0:25])`, `ask_total = sum(asz[0:25])` for UP token. For UP bets: `ratio = bid_total/ask_total`. For DOWN: `ratio = ask_total/bid_total`. Gate: ratio > threshold AND fire_offset_s > 60. Sweep thresholds. G1+G3. Also test time-interaction: ratio stronger at offset > 120s vs 60-120s? |
| **Sources** | https://arxiv.org/abs/2604.24366; arXiv:2604.24366v1 §SF8 |

---

### C2. Polymarket Pre-Resolution Depth Drain Kill Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_depth_drain_near_resolve` |
| **Type** | Kill gate |
| **Tier** | TIER 1 |
| **Mechanism** | Load L25 at timestamps fire_us, fire_us-60s, fire_us-120s (within same slug). `drain_pct = (mean_early_two_depths - depth_at_fire) / mean_early_two_depths`. KILL when drain_pct > 0.30. Directional variant: if ask-side drains disproportionately vs bid-side, signal UP. Restrict to fires at offset >= 180s from slot_start. |
| **Why edge at 5-15m** | arXiv:2604.24366 quantifies depth decay near resolution: slope=0.31, t=3.85, R2=0.22 across 30B Polymarket events. Abnormal drain above this baseline = informed maker withdrawal. KILL gate: when both sides drain, skip fire (stale/manipulated book). Complementary to g_depth_decay_ratio. Zero 'depth_drain' code in codebase (confirmed grep). |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs={slug, prev_slug}, subsample_1hz=False, min_ts_us=fire_us-200_000_000, max_ts_us=fire_us)`. Multi-slug, time-filtered load. Restrict to fires offset >= 180s to avoid cross-slug boundary issues. |
| **Backtest Sketch** | Load 3 book snapshots per fire (fire_us, -60s, -120s). Compute total L10 depth at each. drain_pct. KILL when > 0.20/0.30/0.40. Also directional: ask_drain_pct vs bid_drain_pct asymmetry. G1+G3+bootstrap. Engine_v2 LiveMimicConfig. Restrict to offset >= 180s (~65-75% of fires). |
| **Sources** | https://arxiv.org/html/2604.24366v1 (depth decay stylized fact §4.2) |

---

### C3. Fleeting-Order-Removed OBI Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_filt_obi_aligned` |
| **Type** | Gate (replacement/enhancement for g_imb5_strong_with) |
| **Tier** | TIER 1 |
| **Mechanism** | From native 10Hz L25 snapshots, flag each price level as 'fleeting' if it appears and disappears within 3 consecutive snapshots (~300ms). Compute filtered_OBI from persistent levels only. `g_filt_obi_aligned = sign(filtered_OBI at ws_s) == bet_direction AND |filtered_OBI| > 0.15`. |
| **Why edge at 5-15m** | arXiv:2507.22712 (Jul 2025) shows filtering LOB for parent-executed orders yields systematically stronger directional association. Our g_imb5_strong_with uses raw snapshot depth including HFT flickering. The filtration removes noise without new data. Main risk: Polymarket books are sparser than equity LOBs (~12-201 events/30s). Threshold calibration needed. Zero 'fleeting'/'ephemeral' code in strategy_lab. |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs=set(...), subsample_1hz=False)` — native 10Hz required for 300ms snapshot window (3 ticks). Consecutive snapshot pairs for persistence detection. |
| **Backtest Sketch** | Load L25 10Hz. For each consecutive snapshot pair, flag levels where price level size changed within 3 snapshots. Build filtered_OBI from persistent levels only. At ws_s: sign and magnitude. Test as replacement for g_imb5_strong_with on top ETH/SOL V8/V9 sleeves where imb5 appears. G1+G3. Sweep lifetime threshold (2, 3, 5 snapshots) and OBI threshold (0.10, 0.15, 0.20). |
| **Sources** | https://arxiv.org/abs/2507.22712v1; https://arxiv.org/html/2507.22712v1 |

---

### C4. Polymarket CVD Fast/Slow Divergence Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_poly_cvd_fastslowdiv` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | From load_trades(): `slow_cvd = sum(buy_usd - sell_usd) in [ws_s-300s, ws_s-30s]`; `fast_cvd = same in [ws_s-30s, ws_s]`; `fast_rate = fast_cvd * 10` (extrapolated to 300s scale). `reversal_signal = slow_cvd - fast_rate`. REVERSAL_UP: `slow_cvd < -200 AND reversal_signal < -200` (net-Down selling exhausting → bet UP). REVERSAL_DOWN: symmetric. |
| **Why edge at 5-15m** | The existing g_b1/b2/b3 use a single 60s CVD window. The fast/slow divergence (fast CVD decelerating against slow CVD trend = exhaustion) is standard in practitioner order-flow literature but absent from our gate catalog. Despite CLAUDE.md staleness note, trades_polymarket BTC has 42.8M rows (Apr26-Jun1). Contrarian flavor targets a different regime from existing aligned gates. |
| **Data / Loaders** | `load_trades(asset)` — confirmed current (BTC 42.8M Apr26-Jun1). Filter by timestamp_us within [ws_s-300s, ws_s]. Split 30s fast vs 270s slow. |
| **Backtest Sketch** | Compute slow_cvd and fast_cvd for each resolution slug. Classify REVERSAL_UP/DOWN/NEUTRAL. Threshold sweep {100, 200, 500} USD. Also test direction-flip variant: gate fires when |slow_cvd| > 200 AND sign(fast_cvd) != sign(slow_cvd). Engine_v2 LegacyConfig. G1+G3. Compare vs g_b1/b2 baselines. Asset splits: SOL likely highest coverage. |
| **Sources** | https://www.luxalgo.com/blog/cumulative-volume-delta-explained/; https://bookmap.com/blog/how-cumulative-volume-delta-transform-your-trading-strategy |

---

### C5. Session Open Momentum Burst Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_session_open_momentum` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | At ws_s, determine active session (London 07:00-08:30, NY 13:30-15:00, Asia 23:00-01:00 UTC). Compute `minutes_since_open` and `ret_from_open = log(binance_close_ws_s / binance_close_at_session_open)`. Gate: `minutes_since_open <= 90 AND |ret_from_open| >= 20bps AND sign(ret_from_open) == momo_direction`. |
| **Why edge at 5-15m** | The lag-taker study shows 00-11 UTC is the strongest time window (+$3.33/tr vs baseline). Session opens concentrate institutional flow. The gate combines TIME (proximity to open) with PRICE (commitment magnitude), reducing the look-elsewhere problem vs static HoD gates. The existing g_tr_in_active_session only checks if a session overlaps (binary flag, no distance or directional commitment). Always-fresh signal — no staleness bug. |
| **Data / Loaders** | `load_klines_asof(asset, '1m')` for Binance 1m at session_open and at ws_s. Session open timestamps computed from ws_s modulo 86400. No new data. Full 40-day window. |
| **Backtest Sketch** | For each slug, compute UTC hour/minute of ws_s. Classify session. Load 1m close at session_open_us and ws_s via asof_strict. Compute ret_from_open in bps. Gate at 10/20/30bps thresholds. Engine_v2 LiveMimicConfig. G1+G3. Compare vs g_tr_in_active_session and g_not_us_close_hours. Test each session separately. |
| **Sources** | https://www.tradingview.com/script/8mtf5mNk-Asia-Session-London-ORB-NY-Time/ |

---

### C6. HL Prior-Slot Liquidation Cascade Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_hl_liq_cascade_prior_slot` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | Rolling 5m sum of HL 'Close Short' USD notional in [ws_s - 300s, ws_s] (the PRIOR slot window). Gate UP when `close_short_sum_5m > threshold AND liq_imbalance > +0.5` where `liq_imbalance = (cs_sum - cl_sum) / (cs_sum + cl_sum + 1e-6)`. |
| **Why edge at 5-15m** | Directionally distinct from g_a2: uses ws_s (prior slot anchor) rather than fire_us (concurrent window) — fully causal leading indicator. Adds directional imbalance ratio (cs vs cl), absent from g_a2. Verified: BTC Close Short ~31,771 events in Apr22-Jun1, mean $8,635/event, ~255 qualifying BTC 5m slots at $10k threshold (2.4% coverage). FUNDING_OI_2026_05_26 baseline: $50k threshold WR 63.5%, n=85. |
| **Data / Loaders** | `hyperliquid_liquidations_full.parquet` (5.27M rows, confirmed 300,119 rows Apr22-Jun1). Notional = size * price. Searchsorted for time window. |
| **Backtest Sketch** | Load HL liqs for BTC/ETH/SOL. Sort by time_exchange_us. For each resolution row at ws_s, window = [ws_s-300s, ws_s]. Sum cs and cl notional. Compute liq_imbalance. Gate UP: cs_sum > T AND imbalance > 0.5. Sweep T {$5k, $10k, $25k, $50k, $100k}. Engine_v2 LiveMimicConfig. G1+G3. Compare to g_a2 on overlapping date range. |
| **Sources** | strategy_lab/reports/FUNDING_OI_2026_05_26.md; https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves |

---

### C7. HL Long-Liquidation Cascade Gate for ETH (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_hl_long_cascade_eth` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | HL liquidations filtered to coin='ETH', dir='Close Long'. Rolling 300s event count ending at fire_us. Gate DOWN when `count >= threshold`. Sweep {6, 8, 10, 12} events. Secondary: notional variant ($5k/$10k). ETH Close Long: 19,447 events May1-May27, 3.93 events/5m average, P90 count = 8. |
| **Why edge at 5-15m** | BTC g_a1 (long cascade → DOWN) was killed because HL events averaged $419 median — too small for any notional threshold. ETH Close Long at P90=8 events/5m gives ~619 qualifying windows (12.5% coverage) — count-based design bypasses the notional problem entirely. Mechanism: forced Close Long fills = market sells → DOWN pressure. No ETH close-long cascade gate anywhere in codebase. |
| **Data / Loaders** | `load_hyperliquid_liquidations()` filtered to coin='ETH', dir='Close Long'. 19,447 rows May1-May27. Overlaps with ETH 5m canonical resolutions. |
| **Backtest Sketch** | Filter HL liqs ETH Close Long. Count events in (fire_us-300s, fire_us]. Sweep count thresholds. Gate DOWN when count >= threshold. Engine_v2 LiveMimicConfig. G1+G3. Combine with g_hurst_reverting or g_entry_vwap_in_band for compound filter. |
| **Sources** | https://blog.amberdata.io/liquidations-in-crypto-how-to-anticipate-volatile-market-moves; strategy_lab/reports/FUNDING_OI_2026_05_26.md |

---

### C8. Polymarket Cross-Token Ask-Depth Asymmetry Gate (TIER 1)

| Field | Detail |
|---|---|
| **Name** | `g_poly_longshot_depth_premium_gate` |
| **Type** | Gate |
| **Tier** | TIER 1 |
| **Mechanism** | At fire_us, cross-token L5 ask-side depth: `depth_asym = (sum_ask_notional_UP_L5 - sum_ask_notional_DN_L5) / (sum_ask_notional_UP_L5 + sum_ask_notional_DN_L5)`. When `depth_asym < -0.30` (UP ask thinner) → bet UP; when `> +0.30` (DN ask thinner) → bet DOWN. Restrict to fires where both vwap in [0.30, 0.70]. |
| **Why edge at 5-15m** | The MICROSTRUCTURE_2026_05_26 panel computed `depth_diff = up_depth_2pct - dn_depth_2pct` but it was NEVER gated (confirmed: zero hits for 'g_depth_diff' in score_panel.py). Existing g_imb5_strong_with uses same-token bid/ask; this uses cross-token ASK-side comparison — different mechanism. Anatomy paper (2604.24366) documents depth uniformity; deviations signal informed inventory imbalance. [0.30, 0.70] restriction avoids the longshot spread-premium zone where spreads are 1300-1800bps wider. |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs=set(...), subsample_1hz=False)`. UP and DN token L5 ask_price * ask_size at fire_us. |
| **Backtest Sketch** | For each BTC/ETH/SOL fire, asof-lookup UP and DN token books at fire_us. Sum ask notional L5 for each. Compute depth_asym. Filter to vwap [0.30, 0.70]. Stratify by quintile. Engine_v2 LiveMimicConfig LegacyConfig fee. G1+G3. Cross-check independence from g_imb5_strong_with via Jaccard. Expected n ~8000-15000 fires across all asset-TF combos. |
| **Sources** | arXiv:2604.24366; strategy_lab/microstructure_2026_05_26/score_panel.py (depth_diff unused as gate) |

---

### C9. TTM Squeeze Volatility Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_ttm_squeeze_release` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | 20-bar BB (mult 2.0) and KC (mult 1.5) on Binance 1m bars at ws_s. Squeeze ON when BB inside KC for >= 3 consecutive bars. Gate fires when squeeze released within last 6 bars AND direction = sign(linear-regression momentum on 20-bar window). |
| **Why edge at 5-15m** | Existing TTM implementations are on 4h HL perps (strategy_lab/pine/). Never adapted as a Polymarket binary gate. BB-inside-KC compression then expansion is structurally non-overlapping with Hurst (long-run) or g_vol_contracting (no expansion trigger). 15m slugs better fit: 20-bar 1m = 20min of pre-window context. Limited coverage (rare events). |
| **Data / Loaders** | `load_klines(asset, '1m')` — Binance 1m OHLCV, Apr22-Jun1. 20 bars needed. No new data. |
| **Backtest Sketch** | Compute BB20 and KC20 on 1m bars at ws_s. Flag squeeze_on; count consecutive. Gate on release within sqzMaxBars=6. Direction from LR momentum. Engine_v2 LiveMimicConfig. G1+G3. Compare coverage vs g_vol_contracting to measure non-overlap. |
| **Sources** | https://www.tradingview.com/script/nqQ1DT5a-Squeeze-Momentum-Indicator-LazyBear/ |

---

### C10. Polymarket Spread Narrowing Dynamic Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_spread_narrowing_momentum` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | From L25 10Hz: `spread_mean_300s = mean spread over [ws_s-300s, ws_s]`. `spread_delta = spread_at_fire - spread_mean_300s`. Gate: `spread_delta < -threshold (spread narrowed)` AND `sign(mid_at_fire - 0.50) == bet_dir`. Threshold sweep {-0.005, -0.010, -0.020}. |
| **Why edge at 5-15m** | SF1 (longshot spread premium and its decay as consensus forms) from arXiv:2604.24366. Dynamic spread narrowing = consensus building among informed makers. Existing spread filter checks static level; this uses the time-derivative. Likely conceptual overlap with g_mp_change_with and g_mp_skew_with — check Jaccard similarity before concluding it adds unique value. |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs=set(...), subsample_1hz=False)` — spread per snapshot = `ask_price_0 - bid_price_0`. |
| **Backtest Sketch** | Retrieve L25 snapshots [ws_s-300s, fire_us]. Compute spread_mean_300s. Compute spread_delta at fire_us. Gate. G1+G3. Check Jaccard with g_mp_change_with. Inverse kill gate (spread widening) may be more useful. |
| **Sources** | https://arxiv.org/abs/2604.24366 (SF1 §3.1) |

---

### C11. LOB Spoof-Detection Kill Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_spoof_kill` |
| **Type** | Kill gate |
| **Tier** | TIER 2 |
| **Mechanism** | From L25 10Hz, detect layering-spoof signatures in the 60s before fire_us: `size_delta[t,L] > 3x rolling_mean_size at level L` AND within 10 subsequent ticks size returns to near-baseline. Count direction-aligned spoof events. KILL when `spoof_count >= 2`. |
| **Why edge at 5-15m** | 31% of large orders in crypto CLOBs could be spoofs (arXiv:2504.15908, Dec 2024). Polymarket CLOB spoofers shift g_imb5 / g_mp_skew signals — a KILL gate that invalidates microstructure signals when manipulation detected. Higher-order than any existing gate. False-positive rate is elevated with L25 snapshot data vs L3 order-level, but the large-appear / fast-disappear pattern is still detectable. Zero 'spoof', 'layering' code in codebase. |
| **Data / Loaders** | `load_orderbook_l25_streaming(asset, slugs={slug}, subsample_1hz=False, min_ts_us=fire_us-65_000_000, max_ts_us=fire_us)` — 10Hz, 60s window per fire. Size deltas from consecutive rows. |
| **Backtest Sketch** | Per-level size deltas over 60s. Spoof flag: size_delta > 3x rolling mean AND fast reversion within 10 ticks. Count direction-aligned events. KILL when count >= 2. G1+G3 on Apr22-Jun1 universe. Compute coverage (fraction killed) and WR of passed fires. |
| **Sources** | https://arxiv.org/abs/2504.15908 |

---

### C12. Rolling BTC-ETH Correlation-Break Regime Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_corr_regime_decouple` |
| **Type** | Meta-gate (regime conditioning) |
| **Tier** | TIER 2 |
| **Mechanism** | `rolling_corr_30 = Pearson(btc_1m_ret[-30:], eth_1m_ret[-30:])` at ws_s. (A) Decoupled: suppress momo fires when corr < 0.50 (high idiosyncratic). (B) Aligned: activate only when corr > 0.75 AND BTC direction agrees with ETH/SOL bet. |
| **Why edge at 5-15m** | Low-corr periods = ETH/SOL momo driven by idiosyncratic catalysts → own-asset signals more informative. High-corr = all crypto as one block, macro flow dominates → own-asset signals noisier. Rolling 30-bar Pearson on 1m klines is trivially computable. Average corr ~0.87-0.89 but cycles between 0.50 and 0.95 intraday (confirmed cross-exchange study). |
| **Data / Loaders** | `load_klines(asset, '1m')` or `load_klines_asof` for BTC, ETH, SOL. Rolling 30-bar window = 30 min lookback. |
| **Backtest Sketch** | For each ETH/SOL slug, compute rolling_corr_30 at ws_s. Partition fires into corr_hi/mid/lo terciles. Engine_v2 on existing V5-V9 sleeve universe per tercile. G1 permutation (shuffle corr tercile vs outcomes). G3 bootstrap per tercile. |
| **Sources** | strategy_lab/reports/BTC_LEAD_LAG_5M_2026_05_23.md; strategy_lab/reports/CROSS_EXCHANGE_LEADLAG_2026_05_26.md |

---

### C13. BTC-ETH Realized Vol Ratio Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_vol_ratio_eth_btc` |
| **Type** | Meta-gate (regime conditioning) |
| **Tier** | TIER 2 |
| **Mechanism** | `rv_btc_60 = std(last 60 BTC 1s log-returns)`, `rv_eth_60 = same`. `vol_ratio = rv_eth_60 / rv_btc_60`. Trailing 30-slug rolling quantile rank. (A) Mid-ratio fires (q25-q75): structural ratio = quality filter. (B) High-ratio fires (>q75): ETH-specific vol surge. Kill gate: suppress when vol_ratio > 3x historical median. |
| **Why edge at 5-15m** | High absolute ETH vol driven by BTC macro (low ratio) vs ETH-specific catalyst (high ratio) = different signal quality for ETH-specific momo. Cross-asset normalization strips macro noise from the vol regime signal. ETH structural vol ratio to BTC ~1.45 per Block Scholes. Conceptually distinct from g_vol_high (absolute own-asset vol). |
| **Data / Loaders** | `load_klines_asof(asset, '1s')` — klines_1s.parquet for BTC and ETH/SOL. Same 60-bar window. |
| **Backtest Sketch** | Compute rv_btc_60 and rv_eth_60 at each ETH/SOL fire. Rolling 30-slug quantile rank. Partition into low/mid/high terciles. Engine_v2 on V5-V9 sleeves per tercile. G1+G3. Jaccard vs g_vol_high. |
| **Sources** | https://www.blockscholes.com/research/volatility-review-january-2025; strategy_lab/reports/FUNDING_OI_2026_05_26.md |

---

### C14. HL Mark-Oracle Basis Momentum Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_hl_mark_oracle_basis` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | From hyperliquid_metrics.parquet: `basis_bps = (mark_price - oracle_price)/oracle_price * 1e4`. Rolling 2h z-score at ws_s. Gate ALIGNED: `basis_z > +1.0` for UP (mark expanding above oracle = new long pressure); `basis_z < -1.0` for DOWN. Also: `basis_momentum_5m = basis_bps(t) - basis_bps(t-5)`. |
| **Why edge at 5-15m** | HL mark vs HL oracle is a third data path distinct from: (1) inter-exchange basis (HL vs Binance spot), (2) CEX perp mark-index. Both fields update sub-minute; 17.5% of BTC bars at |z|>1.5 (real signal, not structural pin). BTC basis std=0.91bps around -4.79bps mean — information-carrying. Overlap window Apr30-May16 (hl_metrics) gives 4,292 BTC 5m slots. |
| **Data / Loaders** | `load_hyperliquid_metrics()` — hyperliquid_metrics.parquet, mark_price, oracle_price, ~1-min cadence, Apr30-May16 2026. `add_ws_s()` helper for slug join. |
| **Backtest Sketch** | For each BTC+ETH+SOL 5m+15m slug in Apr30-May16, load hl_metrics [ws_s-300s, ws_s]. Compute basis_bps; rolling 2h z-score (120 1-min bars). Gate: z > +1.0 AND momentum_5m > 0 → UP. Engine_v2 LegacyConfig. G1+G3. Also test as kill gate (basis strongly opposes direction). |
| **Sources** | https://hyperliquid.gitbook.io/hyperliquid-docs/trading/robust-price-indices |

---

### C15. HL OI Velocity 5m Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_hl_oi_vel5m` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | `oi_vel_5m = (oi(ws_s) - oi(ws_s-300s)) / oi(ws_s-300s)`. `mark_price_5m_sign = sign(mark_at_ws_s - mark_at_(ws_s-300s))`. `composite = oi_vel_5m * mark_price_5m_sign`. Gate ALIGNED when composite > +0.003 (0.3%). Kill when composite < -0.003 and opposing fire direction. |
| **Why edge at 5-15m** | 1h OI-A (pass WR 56-58%, +$1.05-1.70/fire) was one of only 4 rules with OIS_pass=True in FUNDING_OI report. The 5m velocity variant captures more timely information: fresh leveraged commitment just before window open. HL OI in BTC at 1-min cadence (Apr30-May16); 5m velocity p10=-0.05%, p90=+0.06% — 0.3% threshold = ~12% coverage. More responsive than 1h lookback. |
| **Data / Loaders** | `load_hyperliquid_metrics()` — open_interest at ~1-min for BTC/ETH/SOL, Apr30-May16. oi_vel_5m requires 5 prior bars. |
| **Backtest Sketch** | For each BTC+ETH+SOL slug in Apr30-May16 window, compute oi_vel_5m and mark_price_5m_sign. Composite. Gate. Engine_v2 LegacyConfig. G1+G3. Compare to OI-A reference (WR 56%, +$1.05). Test as additive gate on top of existing F7 RSI fires. |
| **Sources** | strategy_lab/reports/FUNDING_OI_2026_05_26.md; https://blog.amberdata.io/using-open-interest-to-gauge-participation-and-price-potential |

---

### C16. Cross-Asset HL Liquidation Confluence Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_hl_cross_cascade_confluence` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | For ETH UP bets: gate fires when `hl_liq_btc_close_short_sum_300s > btc_thresh AND hl_liq_eth_close_short_sum_300s > eth_thresh` simultaneously. Grid-search: btc in {50M, 100M, 200M, 500M}, eth in {50M, 100M, 200M, 500M}. Simultaneous cross-asset cascade = market-wide deleveraging (structurally stronger signal). |
| **Why edge at 5-15m** | g_a2 BTC cascade alone: 90.7% WR (n=54). Simultaneous BTC+ETH cascade is a subset with theoretically higher conviction — market-wide event rather than asset-specific unwind. HL data has ETH 258k Close Short rows and SOL 172k rows — sufficient for grid search. Expected joint fire rate ~3-8% based on partial correlation. |
| **Data / Loaders** | `hyperliquid_liquidations_full.parquet` — filter by coin and dir. Compute rolling 300s notional for each asset simultaneously. |
| **Backtest Sketch** | Load HL liqs for BTC, ETH, SOL. Rolling 300s sums per asset at each ws_s. Cross_cascade_up = (btc_sum > btc_thresh) AND (eth_sum > eth_thresh). Grid search thresholds. Engine_v2 on ETH UP fires. G1+G3. Note: HL data ends May27 — restrict accordingly. |
| **Sources** | strategy_lab/new_gates_research_compute.py; strategy_lab/reports/FUNDING_OI_2026_05_26.md |

---

### C17. Realized Power Low Regime Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_realized_power_low` |
| **Type** | Gate |
| **Tier** | TIER 2 |
| **Mechanism** | `RP5 = sum(|ret_1s|)` over 300 1s bars ending at ws_s (L1 variation). Gate: `rp_calm = RP5 < rolling 30-slot median RP5` (calm regime). `rp_hot = RP5 > rolling q75` (hot regime). Regime label: calm/normal/hot by rolling quantile. |
| **Why edge at 5-15m** | Realized power (L1) is jump-robust vs realized variance (L2) — Valkanov MIDAS result. No realized-power gate in arsenal (existing gates use RV²). Low RP5 → tighter Polymarket spreads → more reliable Chainlink follow-through. Same klines_1s data but different vol measure. Note: `load_klines('BTC', '1s')` returns 0 rows due to source-name mismatch — use direct pyarrow read of `klines_1s.parquet`. |
| **Data / Loaders** | Direct `pyarrow.parquet.read_table('data/v4/canonical/klines_1s/klines_1s.parquet', filters=[...])`. 14.11M rows. |
| **Backtest Sketch** | Load klines_1s.parquet direct pyarrow. Compute RP5 per fire. Rolling 30-slot quantile per (asset, tf). Gate rp_calm/rp_hot. Engine_v2 LiveMimicConfig. Sweep q25/q50/q75 threshold. Compare vs g_vol_contracting. |
| **Sources** | https://rady.ucsd.edu/_files/faculty-research/valkanov/predicting-volatility.pdf |

---

### C18. ICT Macro Kill-Zone Time Gate (TIER 2)

| Field | Detail |
|---|---|
| **Name** | `g_ict_session_macro_window` |
| **Type** | Gate (time-based) |
| **Tier** | TIER 2 |
| **Mechanism** | Fixed 5 ICT macro time windows (UTC): London Macro 06:33-07:00 and 08:03-08:30; NY AM Macro 12:50-13:10, 13:50-14:10, 14:50-15:10. ALLOW variant: fire only during windows (~10-11% coverage). KILL variant: skip during windows. 20-min resolution vs existing 1-hour HoD gates. |
| **Why edge at 5-15m** | Existing HoD gates use data-derived top-8 per-cell hours at 1-hour resolution with a known staleness bug. ICT windows are structural (session microstructure), time-invariant, staleness-free. The lag-taker study confirms London-session dominance. Pure timestamp computation — zero new data. Main risk: folklore, no peer-reviewed validation for crypto binary markets. |
| **Data / Loaders** | Pure timestamp computation on `slot_start_us` from `load_resolutions()`. No external data. |
| **Backtest Sketch** | Extract UTC hour+minute from slot_start_us. Flag ict_active per window definition. WR/EV for active vs inactive on full resolution universe. Stack on top-performing sleeves. Jaccard overlap with existing HoD gates — if > 0.7, no independent information. |
| **Sources** | https://innercircletrader.net/tutorials/ict-macro-time-based-strategy/ |

---

## SECTION D: TIER 3 — SPECULATIVE / NEW DATA REQUIRED

These require either new data collection or have insufficient data window for validation.

| # | Name | Category | Blocker | Why Worth Watching |
|---|---|---|---|---|
| D1 | Multi-Scale Hawkes Perp Gate (g_hawkes_perp_imbalance) | Gate | Only 35h of cex_futures_trades (623 BTC 5m fires). Needs 30+ day accumulation. | arXiv:2504.15908 + 2602.00776 establish multi-scale perp Hawkes as dominant directional feature. Once 30 days accumulate, this becomes TIER 1. |
| D2 | Cross-Exchange Perp CVD vs Spot CVD Divergence | Gate | 72h cex_futures_trades. Perp-leads-spot hypothesis contradicted by our own 1s leadlag study. | Mechanism plausible but requires more data and confound isolation. |
| D3 | OI Surge on Consolidation Breakout (g_oi_surge_breakout) | Gate | Only 35h cex_futures_ticker; z>2.0 OI surge events = ~6-8 BTC 5m qualifying slugs in 35h. | bybit OI at 0.9s cadence is the best live OI source we have; once 14+ days accumulate, retest. |
| D4 | Pre-Funding Window Position Flip Gate (g_prefund_flip) | Gate | 35h data → only ~40-60 qualifying slugs. Funding tests (V10A) previously failed. Chainlink spot ≠ perp mark. | Mechanism theoretically sound but practically thin and slow for 5m binary. |
| D5 | Perp Mark-Index Basis Z-Score (g_basis_spike_with / g_basis_spike) | Gate | 35h window = ~623 BTC 5m test fires. Basis is structurally negative (mean -4.2bps); z>2 means discount compressing, not premium. | bitget at 0.39s cadence is the best mark-index source. Accumulate to 14+ days, then retest as thin-coverage add-on. |
| D6 | Multi-Exchange Perp Kline Momentum Confluence | Gate | 35h cex_futures_klines (3 of 4 exchanges); 0.977+ lag-0 corr with binance = effectively redundant. | Worth running as cheap directional diagnostic; unlikely to survive G4. |
| D7 | Cross-Exchange LOB Imbalance Momentum (g_ceximb5_with) | Gate | 35h data; 1MIN kline = up to 60s lag. Likely highly correlated with existing ret_2m gate. | Build as redundancy test; if Jaccard(ceximb5, ret_2m_gate) > 0.85, discard. |
| D8 | Polymarket Hawkes Bivariate Trade-Arrival Intensity | Indicator | Avg 962 trades/5m may be too sparse for Hawkes cluster detection at 10-60s scale. MLE fitting = overfitting risk on 40 days. | Conceptually sound; lower priority vs the CEX perp Hawkes version which has 1,676 trades/5m. |
| D9 | Ehlers Fisher Transform Gate | Gate | Low: monotonic remap of 30-bar stochastic. Likely correlated with g_stoch_with already in arsenal. | Kill-gate variant (blocking extreme opposite Fisher readings) is the most defensible application. |
| D10 | DVOL Spike Regime Gate | Gate | Deribit DVOL historical data requires Tardis paid purchase for Apr22-Jun1. Free WS only for live. | Free live collector = trivially deployable. Historical backtest = ~$30-50 Tardis purchase. If collected, becomes TIER 2. |
| D11 | Short-Term Skew Directional Gate (25d Risk Reversal) | Gate | Hourly Laevitas granularity marginal for 5m; Tardis options_chain requires paid access. Horizon mismatch (weekly IV vs 5m binary). | More defensible for 15m sleeves. Worth testing on 15m universe if Laevitas free data covers Apr22-Jun1. |
| D12 | IV Term Structure Slope Regime | Indicator | Requires both Deribit DVOL (free) and Tardis options_chain ATM_7d_IV (paid). Backwardation events ~10 in 40d window. | High-conviction filter for 15m on existing momo signal. Better as a regime label than gate. |
| D13 | VRP Conditional Bet Sizing | Indicator | Requires Deribit DVOL (free live but Tardis for historical). 30d VRP changes slowly — regime not per-fire signal. | Sizing overlay rather than gate. Low implementation complexity once DVOL is collected. |
| D14 | Options OVI Put-Call Flow Gate | Gate | Tardis Deribit options trades required (paid). OVI coverage at 5m may be <30% of fires. Horizon mismatch. | Heavy put-buying kill gate is most defensible application. Hold until Tardis data available. |
| D15 | Seesaw-Effect Fade (BTC → ETH/SOL opposite) | Strategy | Directly contradicted by g_cross_asset_lag_confluence (66.8% WR aligned UP). Our own data shows positive spillover dominates. | Run as explicit falsification test; expect to confirm negative result. |
| D16 | Cross-Chain Negative Spillover (BTC/ETH surge → SOL DOWN) | Gate | BTC-SOL contemporaneous corr 0.82 means 'lagging' window may be 0-5s. Coverage may be too thin. | Softer threshold test: ret_sol < ret_btc (no 0.5x scaling). G3 bootstrap on thin n. |

---

## TOP 5 TO BACKTEST FIRST

**Rationale for prioritization:** Must have (a) canonical data available NOW, (b) novel mechanism vs existing arsenal, (c) feasible n >= 50 in available window, (d) plausible mechanism at 5-15m, (e) cheap to implement.

---

### 🥇 #1 — HL Short Liquidation Cascade 60s Window (g_hl_short_liq_rolling_cascade)

**Why first:** We already have the empirical result: WR=57.9%, p=0.041 on n=24,699 fires. This is not speculative — it's a re-parameterization of our own g_a2 gate with a 60s window replacing the deployed (non-working) 300s window. The data is canonical (HL full liqs parquet). Implementation is one numpy searchsorted change. **Impact: immediate live fix to the broken g_a2.**

**Loaders:** `load_hyperliquid_liquidations_full()`, `load_resolutions()`
**Estimated build time:** 0.5 days

---

### 🥈 #2 — Cross-CEX Liq Cascade Gate (Gate.io + OKX)

**Why second:** The structural mechanism is the same as g_a2 (which showed 90.7% WR n=54), but using CEX perp liquidation events that are 10-100x larger than HL events ($28k mean, $954k max vs HL $419 median). New data source (`cex_futures_liquidations`), first-ever use. Contrarian formulation (overshoot exhaustion) is economically correct. Data exists NOW in canonical. Exploratory but high upside.

**Loaders:** `load_cex_futures_liquidations()`, `load_resolutions()`
**Estimated build time:** 1 day

---

### 🥉 #3 — Polymarket Book Depth-Decay Ratio Gate (g_depth_decay_ratio)

**Why third:** Directly validated by arXiv:2604.24366 (30B Polymarket events). The raw bid/ask total ratio (unbounded, cross-side) is structurally distinct from g_imb5_strong_with (normalized, same-token). Only requires L25 native 10Hz data which we already load. Simple numpy sum operation. The late-window restriction (offset > 60s) makes it compatible with existing entry timing.

**Loaders:** `load_orderbook_l25_streaming(subsample_1hz=False)`
**Estimated build time:** 1 day

---

### 4th — Polymarket CVD Fast/Slow Divergence Gate (g_poly_cvd_fastslowdiv)

**Why fourth:** load_trades is confirmed current (BTC 42.8M Apr26-Jun1 despite CLAUDE.md note). The fast/slow CVD divergence (exhaustion detection) targets a different regime from existing aligned g_b1 gate — contrariant flavor. Simple window arithmetic. Full 40-day window available. Extension of our already-validated Polymarket flow signal family.

**Loaders:** `load_trades(asset)`, `load_resolutions()`
**Estimated build time:** 1 day

---

### 5th — KAMA Efficiency Ratio Kill Gate (g_kama_er_kill)

**Why fifth:** Directly targets the core weakness of momo firing in choppy/indecisive markets. ER < 0.3 = 60s of Binance price going nowhere = Chainlink settlement is a coin flip regardless of technical signal. KILL gate formulation (drop bad fires) is conservative and robust. Already used in HL perp strategy (b1_kama), adaptation to Polymarket gates is trivial. Full canonical 1s klines available.

**Loaders:** `load_klines(asset, '1s')` or direct klines_1s.parquet read
**Estimated build time:** 0.5 days

---

## DROPPED / ALREADY-HAVE APPENDIX

Entries dropped or deprioritized because they overlap structurally with the existing arsenal:

| Dropped | Reason / Existing Arsenal Overlap |
|---|---|
| Ehlers Fisher Transform Gate (standalone) | Monotonic remap of 30-bar stochastic = largely redundant with g_stoch_with (60s window). Kill-gate variant kept as low-priority test. |
| Multi-Exchange Perp Kline Momentum Confluence | Cross-exchange leadlag study confirmed lag-0 corr 0.977-0.984 for BTC — effectively same signal as existing ret_5m quantile filter. MULTIVENUE_LEADLAG_2026_05_31.md explicitly found no WR lift from HL+OKX consensus. |
| Cross-Exchange LOB Imbalance Momentum (g_ceximb5_with) | 1MIN kline frequency = 60s lag; highly correlated with existing ret_2m anchor. Build only as redundancy check. |
| Seesaw-Effect Fade (BTC top-quintile → ETH DOWN) | Directly contradicted by g_cross_asset_lag_confluence (66.8% WR SAME direction). Keep only as explicit falsification. |
| CEX Perp Mark-Index Basis Z-Score (g_basis_spike_with) | Absorbed into D5 (Tier 3 / data accumulation). 35h window insufficient. Bitget basis is structurally negative (not a premium deviation). |
| Perp Funding / Pre-Funding Gate variants | Funding tests (V10A on Binance futures, V10B on HL metrics) all failed in FUNDING_OI_2026_05_26.md. The mark-index structural gap reflects funding mechanics, not independent directional signal. |
| BTC-ETH realized cointegration residual gates | Not explicitly in the 49 candidates; our 1m data shows no stable cointegration within 5-15m windows. |

---

## SUMMARY TABLE

| # | Name | Section | Tier | Data Fit | Edge Plausibility |
|---|---|---|---|---|---|
| 1 | HL Short Liq 60s Window | A1 | TIER 1 | Full canonical | HIGH (p=0.041 confirmed) |
| 2 | Cross-CEX Liq Cascade (Gate+OKX) | A2 | TIER 1 | cex_futures_liquidations | HIGH (structural) |
| 3 | Polymarket VPIN | B1 | TIER 1 | load_trades (Apr26-Jun1) | MED |
| 4 | KAMA Efficiency Ratio Kill | B2 | TIER 1 | klines_1s | MED |
| 5 | Realized Semivariance Kill | B3 | TIER 1 | klines_1s | MED |
| 6 | Rogers-Satchell Vol Breakout | B4 | TIER 1 | klines_1m | MED |
| 7 | Page-CUSUM Sequential Gate | B5 | TIER 1 | klines_1s | MED |
| 8 | Kalman Filter Velocity | B6 | TIER 1 | klines_1s | MED |
| 9 | Depth-Decay Ratio Gate | C1 | TIER 1 | L25 native 10Hz | MED (paper-validated) |
| 10 | Pre-Resolution Depth Drain Kill | C2 | TIER 1 | L25 native 10Hz | MED (paper-validated) |
| 11 | Fleeting-Order OBI | C3 | TIER 1 | L25 native 10Hz | MED |
| 12 | Poly CVD Fast/Slow Divergence | C4 | TIER 1 | load_trades (confirmed current) | MED |
| 13 | Session Open Momentum Burst | C5 | TIER 1 | klines_1m + timestamps | MED |
| 14 | HL Prior-Slot Liq Cascade | C6 | TIER 1 | HL liqs parquet | MED |
| 15 | HL Long-Cascade ETH | C7 | TIER 1 | HL liqs parquet | MED |
| 16 | Cross-Token Ask-Depth Asymmetry | C8 | TIER 1 | L25 native 10Hz | MED |
| 17 | HAR-RV Vol Surprise | B7 | TIER 2 | klines_1s (heavy compute) | MED |
| 18 | Realized Quarticity / Vol-of-Vol | B8 | TIER 2 | klines_1s | MED |
| 19 | MAMA/FAMA Adaptive Crossover | B9 | TIER 2 | klines_1s | MED |
| 20 | EACP Adaptive RSI | B10 | TIER 2 | klines_1s | MED |
| 21 | Bipower Jump Kill Gate | B11 | TIER 2 | klines_1s | MED |
| 22 | TTM Squeeze Release | C9 | TIER 2 | klines_1m | MED |
| 23 | Spread Narrowing Dynamic | C10 | TIER 2 | L25 native 10Hz | LOW |
| 24 | LOB Spoof Kill Gate | C11 | TIER 2 | L25 native 10Hz | MED |
| 25 | Rolling BTC-ETH Corr-Break | C12 | TIER 2 | klines_1m | MED |
| 26 | BTC-ETH Vol Ratio | C13 | TIER 2 | klines_1s | MED |
| 27 | HL Mark-Oracle Basis | C14 | TIER 2 | hl_metrics (Apr30-May16) | MED |
| 28 | HL OI Velocity 5m | C15 | TIER 2 | hl_metrics (Apr30-May16) | MED |
| 29 | Cross-Asset HL Liq Confluence | C16 | TIER 2 | HL liqs (both assets) | MED |
| 30 | Realized Power Low Regime | C17 | TIER 2 | klines_1s (direct pyarrow) | MED |
| 31 | ICT Macro Kill-Zone Time | C18 | TIER 2 | timestamps only | LOW |
| D1-D16 | Various (Hawkes perp, DVOL, OVI, Seesaw, etc.) | D | TIER 3 | Requires new data / accumulation | LOW-MED |

**TIER 1 count: 16** | **TIER 2 count: 15** | **TIER 3 count: 16 (+ 2 dropped/merged)** | **Total novel: 49**

---

*Generated: 2026-06-01 | Source: 49 adversarially-verified edge candidates | Synthesizer: Claude Sonnet 4.6*
