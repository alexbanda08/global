# Strategy Hunt — Polymarket BTC Up/Down — 2026-04-27

End-to-end pass after the metadata backfill. Combines:
1. Fresh extract on the 5-day, 1,897-market BTC universe.
2. Zero-cost baseline grid (108 cells: 6 baselines × 9 strategies × 2 timeframes).
3. Idea mining from 7 open-source bots in the same domain.

## 1. New universe — what we now have

| | 5m | 15m |
|---|---|---|
| Resolved markets | 1,423 | 474 |
| Avg trajectory snapshots | 2,963 | 1,734 |
| Avg entry yes-ask | 0.510 | 0.510 |
| Avg abs BTC move per window | **0.063%** | **0.110%** |
| UP rate | 50.5% | 47.7% (sample noise) |

Both `btc_markets_v3.csv` (1,896 rows, 25 columns) and `btc_trajectories_v3.csv` (158k rows, 15 columns) are in `strategy_lab/data/polymarket/`. New columns vs prior extract: `strike_price`, `settlement_price`, `abs_move_pct` (Chainlink ground truth, no Binance lookup needed).

**The number that matters:** the typical 5m BTC move is **0.063%** on a ~$77k price = ~$48. That's the expected magnitude we're trying to predict the sign of, in 5 minutes. This is razor thin and explains why every signal-free strategy lives at break-even.

## 2. Baselines × Exit Grid — full results

Sample 1,896 markets, fee 2% on winnings, bootstrap n=2000 for 95% CIs.

### 5m — best 6 cells

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| market_anti | S2_stop=0.40 | 1,422 | **+$2.75** | [-$11, +$17] | 18.6% |
| momentum (chainlink) | S2_stop=0.40 | 1,383 | -$1.06 | [-$17, +$15] | 20.2% |
| market_anti | S2_stop=0.35 | 1,422 | -$3.75 | [-$22, +$14] | 20.0% |
| momentum | S2_stop=0.35 | 1,383 | -$5.11 | [-$25, +$14] | 23.4% |
| always_down | S2_stop=0.40 | 1,422 | -$5.58 | [-$22, +$11] | 20.8% |
| market_anti | S3_t=0.70 s=0.35 | 1,422 | -$8.51 | [-$20, +$3] | 33.8% |

### 15m — best 6 cells

| Baseline | Strategy | n | PnL | 95% CI | Win% |
|---|---|---|---|---|---|
| always_down | S0_hold | 474 | **+$6.89** | [-$14, +$26] | 52.3% |
| always_down | S2_stop=0.35 | 474 | +$5.35 | [-$6, +$17] | 25.9% |
| always_down | S2_stop=0.30 | 474 | +$4.99 | [-$9, +$19] | 31.0% |
| random | S0_hold | 474 | +$2.98 | [-$18, +$24] | 51.9% |
| market_anti | S3_t=0.70 s=0.35 | 474 | +$1.62 | [-$5, +$9] | 33.5% |
| momentum | S2_stop=0.30 | 457 | +$1.03 | [-$12, +$14] | 26.5% |

### Verdict

- **No cell has a 95% CI that excludes zero.** Every "winner" is within sampling noise.
- **`market_with` (trust market consensus) is consistently the worst** across both timeframes — confirming the orderbook is well-calibrated; betting the more-expensive side just pays the spread.
- **`always_down` topping 15m is a sample artifact.** UP rate was 47.7% over 5 days. `random` baseline came right behind it (+$2.98) — same effect, different label. With another month of data we expect 50/50 and that "edge" disappears.
- **`momentum` (Chainlink prior return) is no better than `random`.** The autocorrelation of 5m/15m BTC returns is essentially zero; sign of the last bar is not predictive of the next. (5m momentum n=1,383 because the first market in each timeframe has no prior bar.)
- **Wide stops (0.35–0.40) help everyone, slightly.** Confirms the prior finding that the asymmetric shape of `(target=0.4, stop=0.4) → CI tightens` works as risk reshaping, not edge generation.

**Bottom line: with no exogenous signal, nothing beats fees + spread on this market.** Edge has to come from data the orderbook hasn't priced in yet.

Full grid → `results/polymarket/baselines_grid.csv`. Pretty report → `reports/POLYMARKET_BASELINES_GRID.md`.

## 3. Open-source bots — what's worth stealing

Indexed all 7 repos into the knowledge base. Source labels are in parentheses for follow-up `ctx_search`.

### 3.1 The dominant thesis: latency arbitrage Binance → Chainlink → Polymarket

Four of the seven repos converge on the same edge:

> **Polymarket settles via Chainlink Data Streams. Chainlink aggregates exchanges (~4–12s lag vs Binance). Binance prints the move first. Watch Binance, predict Chainlink, trade Polymarket.**

Sources: `0xLanister/polymarket-5-15min-printer-bot`, `HorseDev77/polymarket_5-15-arb-bot`, `building_cyclops_style_bot.md` (already in the repo), and partial in `suislanchez`.

This matches our `building_cyclops_style_bot.md` design doc and is the single highest-conviction direction. **It's also the only one for which we already have all the data**: `binance_klines_v2` in the VPS DB is pulled from CoinAPI which has direct Binance feeds, and we have Chainlink settlement times in `market_resolutions_v2`. We can compute the empirical lag and test the strategy without any new infrastructure — just a query and a backtest.

### 3.2 `suislanchez/polymarket-kalshi-weather-bot` — most polished, has measured PnL

The README claims "highest profits $1.8k". Their **BTC 5-min Strategy 1** uses an explicit composite signal:
- **RSI** on 1m candles
- **Multi-TF momentum**: 1m, 5m, 15m windows
- **VWAP deviation**
- **SMA crossover**
- **Market skew** (orderbook bid/ask size imbalance)
- Weighted composite → trade if `|model_prob - market_prob| > 2%`
- **Fractional Kelly 0.15**, capped 5% of bankroll, $75 per trade
- **Brier score** tracking for calibration

This is the most actionable single specification. We could implement this 1:1 against our 1,897-market sample in a day:
- BTC 1m candles → RSI/SMA/momentum from `binance_klines_v2` (1MIN, period 2026-01-22 → 2026-04-24).
- VWAP from same table (price × volume / volume cumulated).
- Market skew from our `bid_size_0` / `ask_size_0` snapshot columns at window_start.
- Composite weights to be fit; start equal-weight, optimize on 70% of sample, validate on 30%.

### 3.3 `PolyBullLabs/polymarket-5-15-1h-arb-bot` — strategy menu (idea bank)

Three shipped bots:
- **`btc-binary-VWAP-Momentum-bot`** — late-window entry: trade WITH side that's above VWAP and has positive momentum. Same intuition as suislanchez but without microstructure.
- **`up-down-spread-bot` (Meridian)** — late-window, follow side with confidence (ask-skew) above threshold + spread filter. Rolling stop / flip-stop before expiry.
- **`5min-15min-PTB-bot`** — compare spot BTC vs Polymarket "price-to-beat" (PTB); trigger when time + spread + implied probability align.

Plus a catalog of 20+ strategy *ideas* (READMEs in 4 languages — Chinese has more detail):
1. **1¢ buy** — ultra-cheap odds when book dislocates; tail-event lottery, hard caps.
2. **99¢ sniper** — buy near-certainty asks just before resolution if outcome is effectively settled but liquidity still exists; the inverse tail.
3. **Low-side dual reversion** — bet both underdog sides when prices are compressed (mean-reversion on the binary).
4. **Pre-order placement** — limits *before* the active window to shape queue position.
5. **Cross-market hedge** — link 5m and 15m markets covering the same window for spread/arbitrage.
6. **Martingale / anti-martingale @ ~45¢** — regime-gated only; high blowup risk.
7. **Fibonacci-based grid** — for the binary payoff geometry.
8. **Dump-hedge** — detect sharp BTC dump, leg in, hedge other side when combined cost clears threshold.
9. **MACD + RSI + VWAP composite** — same family as suislanchez, sharper indicator stack.

Most of these are recipe-level, not back-tested. Useful as **menu items to score and prioritize** rather than to copy.

### 3.4 `ThinkEnigmatic/polymarket-bot-arena` — meta-architecture

Runs 4 competing bots with online learning (Bayesian weight updates per resolved trade). No specific edge — but the **arena pattern** is a useful frame: rather than picking one strategy, run 4 in parallel, weight by recent performance, retire losers. Useful once we have ≥2 candidate signals.

### 3.5 `weiuou/polymarket_15minupdown_monitor` — data only

Just a Gamma API scraper + CSV plotter. Nothing tradable. Skip.

### 3.6 `HorseDev77/polymarket_5-15-arb-bot` — JS port of the latency-arb thesis

Same idea as `0xLanister`, JS implementation. The `BEAT_PRICE_FIX.md` doc likely explains their PTB threshold tuning. Worth a 30-minute read; not worth porting.

### 3.7 `PolyScripts/polymarket-arbitrage-trading-bot-pack-5min-15min-kalshi` — marketing-stuffed README

The repo name is a keyword stuffing experiment. Code is shallow. Skip.

## 4. Recommended next phase

Three concrete experiments, in priority order. None is the "build the live bot" step — these are *find an edge first*.

### Experiment 1 — Empirical Binance → Chainlink lag

**Goal:** Quantify the latency-arb thesis on our own 5-day sample before committing to it.

**Method:**
1. Cross-join `market_resolutions_v2` (Chainlink settle prices, 1,897 BTC markets) with `binance_klines_v2` (1MIN BTCUSDT close).
2. For each market, compute *Binance-leads* signal at `window_start + Δ` for Δ ∈ {30, 60, 90, 120s}: `sign(binance_close[window_start+Δ] - strike_price)`.
3. Backtest as a 1-feature signal through the existing exit grid.

**Cost:** half a day of work, all data on hand. **Win condition:** any Δ produces a hit-rate ≥56% with CI excluding 53% (break-even).

### Experiment 2 — Microstructure composite (suislanchez recipe)

**Goal:** Reproduce their "Strategy 1" specification on our data.

**Method:**
1. Build a `features.py` that, for each of 1,897 markets at `window_start`, computes:
   - RSI(14) on 1m bars
   - Momentum(1m, 5m, 15m) — log returns
   - VWAP deviation: `(close - vwap_15m) / vwap_15m`
   - SMA crossover: `sign(sma_5 - sma_20)`
   - Book skew: `(bid_size_0 - ask_size_0) / (bid_size_0 + ask_size_0)` from snapshot
2. Equal-weighted composite → signal.
3. Run through exit grid with `|edge| > 2%` filter (S6 family).

**Cost:** 1–2 days. **Win condition:** same as #1.

### Experiment 3 — "Late-window only" filter on Experiment 1 or 2

**Goal:** Test PolyBullLabs' insight that the first 60–80% of the window is noise; only the last 60s carries signal.

**Method:** S5 time-entry filter — only enter at `bucket >= N` where N skips the early window. Combine with Exp 1 or 2's signal.

**Cost:** trivial — already supported by the grid framework (S5 family).

## 5. What we are NOT doing (and why)

- **Re-running Kronos on the new universe.** The April model already failed OOD by 2.5% accuracy (52.9% Apr vs 60% Jan-Mar fit). Retraining isn't free (~hours on the D: GPU) and the prior failure was structural — patching it without a different feature stack just relearns the same overfit.
- **Building live execution.** That's the other project. We stay in backtest land until we have a signal whose 95% CI clears break-even on a hold-out.
- **NautilusTrader / heavy frameworks.** Our pandas grid runner is fine for the entire signal-search phase.

## 6. Files produced this session

- `polymarket_extract_markets_v3.sql` — driven by `market_resolutions_v2`, exports markets CSV with strike/settle.
- `polymarket_extract_trajectories_v3.sql` — same driver, exports 158k trajectory rows.
- `data/polymarket/btc_markets_v3.csv` (594 KB, 1,896 rows).
- `data/polymarket/btc_trajectories_v3.csv` (18.5 MB, 158k rows).
- `polymarket_baselines_grid.py` — runner.
- `results/polymarket/baselines_grid.csv` — 108-cell grid.
- `reports/POLYMARKET_BASELINES_GRID.md` — pretty grid report.
- `reports/STRATEGY_HUNT_2026_04_27.md` — this document.
- `reports/VPS_DATA_INVENTORY.md` — updated with post-backfill numbers.

## 7. Knowledge base source labels (for follow-up `ctx_search`)

- `aulekator/Polymarket-BTC-15-Minute-Trading-Bot — repo root`
- `suislanchez/polymarket-kalshi-weather-bot`
- `ThinkEnigmatic/polymarket-bot-arena`
- `PolyBullLabs/polymarket-5-15-1h-arb-bot`
- `PolyScripts/polymarket-arb-pack-5-15-kalshi`
- `0xLanister/polymarket-5-15min-printer-bot`
- `weiuou/polymarket_15minupdown_monitor`
- `HorseDev77/polymarket_5-15-arb-bot`
