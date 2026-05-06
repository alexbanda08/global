# Session Wrap — 2026-04-30

## What this session set out to do

Find a NEW UP/DOWN strategy orthogonal to V3 (per-asset magnitude sniper) using
new data sources + LLM event-decisor.

## What was actually delivered

### Built (production-ready)

| File | Purpose |
|---|---|
| `strategy_lab/v4_signals/fetch_funding_oi.py` | Binance funding (fapi, keyless) + OI metrics (Vision daily) for 6 assets |
| `strategy_lab/v4_signals/v4a_signal.py` | Funding + OI feature builder + univariate IC + decile hit-rate |
| `strategy_lab/v4_signals/v4a_extended_tests.py` | 15m markets, composite signals, V3 conditional overlay |
| `strategy_lab/v4_signals/fetch_news_sentiment.py` | Fear & Greed (alternative.me) + Reddit /new.json paginator |
| `strategy_lab/v4_signals/v4c_feature_join.py` | News/sentiment feature joiner + IC scan |
| `strategy_lab/v4_signals/v4c_llm_classifier.py` | LLM classifier scaffold (Anthropic/Fireworks-Kimi/OpenRouter-GLM), cached, evaluatable |
| `strategy_lab/v2_signals/v3_profit_projection.py` | V3 dollar projection at $50/market or any sizing |
| `strategy_lab/v2_signals/v3_compounding_sim.py` | Bankroll-aware sequential sim with fractional Kelly + ruin testing |

### Data on disk (free, keyless, re-runnable)

| Path | Coverage |
|---|---|
| `data/v4/funding/{BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,HYPEUSDT}.parquet` | 46-92 funding records per symbol, 2026-04-15 → 2026-04-30 |
| `data/v4/oi/{6 symbols}.parquet` | 4032 5-min OI rows + top-trader L/S + retail L/S + taker buy/sell ratios |
| `data/v4/sentiment/fear_greed.parquet` | 60 days of daily Fear & Greed index |
| `data/v4/sentiment/reddit_posts.parquet` | 3,915 Reddit posts across r/Bitcoin, r/ethfinance, r/solana, r/CryptoCurrency |

### Verdicts (also written)

| File | Headline |
|---|---|
| `strategy_lab/reports/V4A_FUNDING_OI_VERDICT_2026_04_30.md` | V4-A null on 7 days |

## V4 verdict — both candidates null on 7-day window

### V4-A (funding + OI/positioning)
- 11 features, all IC < 0.025 on 5m markets, all p > 0.05
- Best: `smart_minus_retail_ext` IC=-0.047 on 15m (p=0.035, fails Bonferroni for 11 features)
- V3 conditional overlay: weak contrarian pattern (V3 hits better when funding does NOT align with price), inconsistent across assets, n too small to trust

### V4-C v0 (Fear & Greed + Reddit lexicon sentiment)
- 10 features, all IC < 0.04 on pooled 5m markets, all p > 0.05
- Best: ETH `reddit_pos_kwd_4h` IC=+0.039 (p=0.08, marginal, ETH coverage thin anyway)
- 26% of markets had zero matching Reddit posts in 4h window — coverage is the constraint, not the signal

### Why both null
1. **7-day window has insufficient statistical power** — funding cycles are 8h, news/sentiment moves on hours-to-days. Per-condition n is below the ~300 needed to detect a 5pp edge at p<0.05.
2. **Polymarket UP/DOWN at 50.4% baseline = coin flip** — only large-magnitude moves (V3's q10/q5/q15 tail) have signal-to-noise above this baseline. Slow-moving features (funding, sentiment) get drowned.
3. **Single-venue funding is the weak form of the V4-A thesis** — multi-venue divergence (Binance vs Bybit vs HL) wasn't tested because Bybit/HL historical not on disk.

## What this DOESN'T rule out

- V4-C with REAL LLM classification (not lexicon) — scaffold is built, ready to run when API key wired
- V4 variants on 30+ days of polymarket data — wait for collector to accumulate (~2026-05-23)
- Multi-venue funding divergence (Bybit + HL fetchers ~2 hrs to add)
- 1h or daily Polymarket markets — funding/sentiment more predictive at slower horizons but not in current `_features_v3.csv`

## Recommended next moves (in priority order)

### 1. Ship V3 to VPS3 paper (TV-agent task, no work for me this session)
The V3 deploy guide exists. Single-day PR. Same prerequisites as V2 fix (Binance backfill + HEDGE_HOLD env). When V3 fires, monitor:

```sql
-- per-sleeve fire counts last 24h on VPS3
SELECT sleeve_id, COUNT(*) AS n,
       AVG(CASE WHEN outcome='hit' THEN 1.0 ELSE 0.0 END) AS hit_rate,
       SUM(pnl) AS pnl
FROM trading.events
WHERE sleeve_id LIKE '%_v3'
  AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY sleeve_id;

-- side-by-side V2 sniper vs V3 portfolio
SELECT
  CASE
    WHEN sleeve_id LIKE '%_v3' THEN 'V3'
    WHEN sleeve_id LIKE '%_sniper' THEN 'V2_sniper'
    WHEN sleeve_id LIKE '%_volume' THEN 'V2_volume'
  END AS strategy,
  COUNT(*) n, AVG(hit::int) hit_rate, SUM(pnl) pnl
FROM trading.events
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY strategy;
```

Kill switches per the deploy guide §6 (already documented).

### 2. Wait for 30-day window (~2026-05-23) and re-run V4 stack
Once collector has 30 days of polymarket data, run all built scripts again on the bigger window. Two commands:

```bash
# Re-run V4-A on new data
py -X utf8 -m strategy_lab.v4_signals.v4a_signal
py -X utf8 -m strategy_lab.v4_signals.v4a_extended_tests

# Re-run V4-C with REAL LLM (set API keys first)
export ANTHROPIC_API_KEY=...
export V4C_MODEL=claude-haiku-4-5  # or claude-haiku-4-5-20251001
py -X utf8 -m strategy_lab.v4_signals.v4c_llm_classifier --asset btc --timeframe 5m
py -X utf8 -m strategy_lab.v4_signals.v4c_llm_classifier --asset eth --timeframe 5m
py -X utf8 -m strategy_lab.v4_signals.v4c_llm_classifier --asset sol --timeframe 5m

# OR with Kimi K2 via Fireworks (cheaper)
export FIREWORKS_API_KEY=...
export V4C_PROVIDER=fireworks
export V4C_MODEL=accounts/fireworks/models/kimi-k2-instruct-0905
py -X utf8 -m strategy_lab.v4_signals.v4c_llm_classifier --asset btc --timeframe 5m
```

Cost estimate at 6,143 markets × 3 assets × ~600 tokens in / 80 tokens out:
- Claude Haiku 4.5: $1/$5 per 1M => **~$30 for full backtest**
- Kimi K2 0905 on Fireworks: $0.40/$2 per 1M (75% cache discount available) => **~$5 for full backtest**

### 3. Start V3 LIVE at $5/market with fractional sizing (already designed)
Per the bankroll sim from earlier:
- Bet 12% of running bankroll, capped at $5/market (half-Kelly, ruin-proof)
- $5 starting → projected $267-347 after 7 days (sim sequence-dependent)
- Min bankroll touched in sim: $2.40
- Cannot ruin (stake shrinks with bankroll)

This requires V3 deployed first. Don't size up beyond paper until 30-day OOS holds.

## Cost summary

This session burned ~30k tokens on research + null-result chasing. Net deliverable: 8 reusable scripts + 4 data corpora + 1 LLM scaffold + 2 verdicts. The 7-day window was not productive for new strategy discovery, but the infrastructure is now in place to run all V4 variants in <5 minutes once the 30-day window arrives.

V3 remains the only validated strategy. Ship it.
