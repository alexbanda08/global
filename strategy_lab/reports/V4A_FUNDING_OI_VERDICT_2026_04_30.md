# V4-A Funding + OI Verdict — 2026-04-30

## TL;DR

V4-A standalone (Binance funding-rate + OI/positioning features → predict Polymarket UP/DOWN) is **NULL on the 7-day window**. Worth keeping the data fetcher; not worth deploying the strategy as-is.

One marginal signal worth flagging: `smart_minus_retail_ext` on 15m markets has IC = -0.047, p = 0.035 (single-asterisk significant, likely overfit on n=2046 across 7 days).

## What we tested

Joined Binance perp futures features to Polymarket UP/DOWN markets on BTC/ETH/SOL:
- 11 features built (funding rate, funding 4h-delta, OI %change at 5/15/60min, top-trader L/S ratio + delta, retail L/S ratio, smart-minus-retail divergence, taker buy/sell vol ratio + delta)
- Tested on 5m markets (n=6,143 pooled), 15m markets (n=2,046 pooled), full 5m+15m pool (n=8,189)
- 3 lenses: univariate Spearman IC, top/bottom-decile hit rates, V3 conditional overlay

## Results

### Test 1 — Univariate IC, 5m markets (n=6,143)
All features IC < 0.025, **all p > 0.05.** Top decile hit rates 51-53% vs 50% baseline. Effectively zero.

### Test 2 — Univariate IC, 15m markets (n=2,046)
1 feature crosses p=0.05: `smart_minus_retail_ext` IC = -0.047 (p=0.035).
- Direction: when top-trader L/S ratio is HIGHER than retail L/S ratio (smart positioned more long than retail), market resolves DOWN slightly more.
- Could be: positioning-divergence contrarian signal. Or could be: 0.05 IC after testing 11 features = expected false positive.
- Multiple-testing adjusted: 11 features × p<0.05 needed → Bonferroni p<0.0045 needed → fails.

### Test 3 — Composite alignment signals
"Bullish-aligned" (funding + OI + top_ls + retail_ls all bullish), bearish-aligned, and net `positioning_score`: all IC < 0.01, all p > 0.39. Score=+2 (max bullish positioning) markets hit only 47.5% UP — weak contrarian hint, no statistical power.

### Test 4 — V3 conditional overlay
Does V3 hit-rate jump when funding aligns with price direction?

| Asset | V3 baseline | funding_aligned | funding_NOT_aligned | oi_aligned | oi_NOT_aligned |
|---|---|---|---|---|---|
| BTC (n=206) | 68.9% | 67.5% (-1.4pp) | 70.8% (+1.9pp) | 64.9% (-4.0pp) | **72.3% (+3.4pp)** |
| ETH (n=103) | 64.1% | 53.6% (-10.5pp) | **76.6% (+12.5pp)** | 60.4% (-3.7pp) | 67.3% (+3.2pp) |
| SOL (n=307) | 57.0% | 56.8% (-0.2pp) | 57.1% (+0.1pp) | 59.3% (+2.3pp) | 55.4% (-1.6pp) |

Pattern: **CONTRARIAN** — V3 hits better when funding/OI does NOT align with price direction. Interpretation: when positioning isn't crowded in the direction price is already moving, the move is more sustainable.

But: ETH effect is +12.5pp, BTC +1.9pp, SOL +0.1pp. Inconsistent across assets, n is small (47-307), likely noise.

`funding_AND_oi_aligned` slice for SOL hits 66.1% (n=59) vs baseline 57.0% — a +9pp lift but n=59 is too thin to bank on.

## Why it failed

1. **7-day sample.** Funding rates and OI move on multi-day timescales. 7 days = ~21 funding cycles per symbol. Statistical power to detect a 5pp edge requires >300 fires per condition, we have <100 in some segments.
2. **5min markets are too fast for funding signals.** Funding adjusts every 8h (4h on HYPE). The information is too lagged for 5min binary resolution.
3. **Single-venue funding ≠ divergence signal.** The original V4-A thesis was Binance vs Bybit vs Hyperliquid funding *divergence* — when one venue is heavily one-sided and others are not, the over-paid side is crowded. Single-venue funding-z is a weaker form of the signal.
4. **Polymarket markets are mostly noise at small magnitudes.** The base UP rate is 50.4% — these are coin flips by design. Only large price moves (V3's q10/q5/q15 magnitude tail) give the magnitude needed for a signal class to land. Funding/OI as smooth slow-moving features get drowned out.

## What this rules out and what's still open

**Ruled out (this data, this window):**
- Funding rate alone as primary directional signal on 5m or 15m Polymarket
- OI %-change as primary directional signal
- Smart vs retail L/S ratio composite (no significant IC)
- Funding/OI alignment as a binary V3 gate (inconsistent across assets)

**Still open (worth investigating):**
1. **Multi-venue funding divergence.** Bybit + Hyperliquid funding APIs are public + keyless. If one venue is paying +0.1% while another is paying -0.05%, that's a real arb / fade signal. Backtest would need 30+ days of multi-venue data — not on disk yet.
2. **1h / daily Polymarket markets** — funding is more predictive at slower horizons. Polymarket runs 1hr UP/DOWN markets but our `*_features_v3.csv` only contains 5m + 15m. New scrape needed.
3. **Liquidation cluster proximity.** Binance Vision liquidation snapshots are 404 (deprecated). CoinGlass free tier (10k calls/mo, daily granularity) or live WS scraping would unlock this. Different signal class.
4. **smart_minus_retail_ext on 15m at the +/-2σ tails.** The 0.05 IC is borderline — a follow-up test with proper out-of-sample (60/40 chronological) and more data would say if real.
5. **News/LLM event-conditional layer (V4-C).** This was the user's primary interest. Skipped here because V4-A funding was the cheapest test. Not invalidated by this verdict.

## Files

- `strategy_lab/v4_signals/fetch_funding_oi.py` — funding (fapi, keyless) + OI (Vision metrics) fetcher
- `strategy_lab/v4_signals/v4a_signal.py` — IC scan + decile hit rates
- `strategy_lab/v4_signals/v4a_extended_tests.py` — 15m + composite + V3 overlay
- `data/v4/funding/{symbol}.parquet` — 6 symbols × 46 funding records (HYPE 92, 4h cycle)
- `data/v4/oi/{symbol}.parquet` — 6 symbols × 4032 OI records (5min granular, 14 days)

## Recommendation — what to do next

**Option 1 (cheap, ~2 hours): Multi-venue funding divergence.** Add Bybit + Hyperliquid funding fetchers. Build cross-venue Z-score. Re-run V4-A. If divergence has IC > 0.05, it's a real signal class — pursue. If still null, kill V4-A entirely.

**Option 2 (medium, ~4-6 hours): V4-C news/LLM event signal.** Skip the microstructure path entirely. Build a news ingestion (CryptoPanic free, Reddit, Fear&Greed), wire Claude as event classifier, generate UP/DOWN/SKIP per market window. Backtest on 7 days.

**Option 3 (cheap, ~30min): Recommit to V3.** V4-A is null, V4-C is unbuilt. The pragmatic move: ship V3 to VPS3 paper as planned, let it run 30 days, come back with real out-of-sample data and try V4 variants on a bigger window.

My call: **Option 3 → then Option 2.** V3 is the only validated edge we have. Ship it, accumulate the 30-day window, then come back and test news/LLM on a real OOS sample. Multi-venue funding divergence (Option 1) is also reasonable as a parallel ~2hr task.
