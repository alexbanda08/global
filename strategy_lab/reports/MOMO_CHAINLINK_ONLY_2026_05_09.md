# MOMO Chainlink-Only Re-Run — drop binance-resolved markets
_Generated: 2026-05-09_

## Why this re-run
Found that 8.9% of `market_resolutions_full.csv` rows have `price_source = binance-klines-1m` (older markets backfilled before chainlink stream was live). Production resolves exclusively on Chainlink Data Streams, so backtest must match. This re-run drops the 1,759 binance-resolved markets.

## Universe filtering
- price_source distribution (full universe): chainlink-fast=12,033, chainlink=5,211, binance-klines-1m=1,759
- chainlink-only: 17,244 / 19,696 markets kept (87.5%)

## Headline (HOLD policy, chainlink-only)

| variant   | policy   |   n |   hit |   pnl_total |   pnl_mean |   avg_vwap |
|:----------|:---------|----:|------:|------------:|-----------:|-----------:|
| B0        | HOLD     | 729 | 67.08 |    -1326.53 |    -1.8197 |   0.708614 |
| G6        | HOLD     |  38 | 57.89 |     -235.92 |    -6.2083 |   0.734545 |

## Comparison: chainlink-clean vs mixed (B0/G2/G6 baseline numbers)

| Variant | n_clean | n_mixed | Δn | hit_clean | hit_mixed | Δhit pp | pnl_clean | pnl_mixed | Δpnl |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B0 | 729 | 949 | -220 | 67.08 | 87.46 | -20.38 | $-1326.53 | $+12846.33 | $-14172.86 |
| G6 | 38 | 444 | -406 | 57.89 | 90.09 | -32.20 | $-235.92 | $+8595.85 | $-8831.77 |

## 🚨 VERDICT — the prior backtest was contaminated

The chainlink-only baseline **collapsed**:
- B0: +$12,846 → **−$1,326** (Δ = **−$14,173**)
- G6: +$8,596 → **−$236** (Δ = **−$8,832**)
- Hit rate: 87.46% → 67.08% (B0), 90.09% → 57.89% (G6)
- avg_vwap_e: 0.614 → 0.708 (entries 9.4 ¢ more expensive)

This is far too large to be sample variance. The 1,759 binance-resolved markets (8.9% by row count) accounted for ~$14k of the +$12.8k headline PnL. **The previous baseline was an artifact, not real alpha.**

## Why it inflated

Two compounding effects on the binance-resolved subset:

1. **Tautological signal/outcome correlation** — those markets had the `outcome` flag derived from binance 1MIN klines. Our `ret_2m` is computed from the same binance klines. Sign of one ↔ sign of the other are not independent — so the gate's "directional accuracy" is partly self-fulfilling on this subset.

2. **Older = less liquid = wider spreads = cheaper entries** — binance-resolved markets are mostly OLDER (backfilled before Chainlink stream went live). On those older markets the Polymarket book was less efficient, so $25 walks landed closer to mid (vwap ≈ 0.61). On chainlink-resolved (newer) markets the book is tighter, vwap ≈ 0.71. Higher entry vwap raises the breakeven hit rate from 56% to 71% — pushing us from comfortably profitable to below-water.

Combined: high tautological hit × cheap entries → fake +$14k.

## What this means for production

- **Production fires on chainlink-resolved markets only.** So the chainlink-clean numbers (B0: 67% hit, −$1.83/trade) are what to expect from the strategy as deployed.
- The earlier +$13.54/trade was inflated. The other agent's `MOMO_BREAKTHROUGH_SLUG_WS_END_TIME` analysis (production live = ~52% hit rate) is closer to reality — even our chainlink-clean 67% may still be slightly inflated by the next gotcha.
- **G6 lead-lag alpha doesn't exist in chainlink-clean data.** With n=38 and 58% hit, it's noise. Don't deploy.

## Open follow-ups

1. **Re-run G2 (disagree+5bp) on chainlink-only** — it was filtered to 0 trades by an interaction with the local apply_lead_variant, need to debug.
2. **Add permutation null and walk-forward** to the chainlink-only baseline to confirm whether the −$1,326 is statistically below null or just unlucky over 17 days.
3. **Investigate whether refresh_2026_05_06 has populated price_source** somewhere we missed — the OLD refresh CSV doesn't carry it, but the original DB rows might. If yes, we could expand the chainlink-only window backwards.
4. **Audit other backtest reports** in this session that used the contaminated baseline as their reference. Anything that quoted +$12,846 needs to be re-baselined.

## Files
- `strategy_lab/meta_classifier/momo_chainlink_only.py` — the harness
- `data/v4/refresh_2026_05_09/coinbase_lead/clean_chainlink/{summary,per_trade}.csv` — outputs