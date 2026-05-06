# Momo Shadow Match — TRUE Same-Trade Comparison

**Generated:** 2026-05-06

## TL;DR — production controller is leaving ~$7/trade on the table

For 221 of 299 shadow live fires (May 6 ~16h, 72 unique markets), the L25 realfill engine re-simulates each EXACT same market+direction+outcome.

| Metric | Shadow (paper) | L25 realfill SAME trades | Δ |
|---|---:|---:|---:|
| Total PnL (matched) | **$+598.89** | **$+2,211.63** | **+$1,612.74** |
| Mean $/trade | $+2.71 | $+10.01 | **+$7.30** |
| Trades matched | 221 | 221 | — |

**The realfill simulator says momo is making 4× what production is capturing on the same markets.**

### Worst gaps (shadow vs realfill on same markets)

| Cell | shadow $/trade | realfill $/trade | Δ_$/trade | rf_hold | rf_hedge | rf_sell |
|---|---:|---:|---:|---:|---:|---:|
| **SOL_5m_HOLD** | $+0.92 | **$+14.17** | **−$13.25** | 19 | 0 | 0 |
| **SOL_5m_SELL** | $+2.82 | **$+15.61** | **−$12.79** | 16 | 0 | 1 |
| **SOL_5m_HEDGE** | $+0.92 | **$+12.56** | **−$11.64** | 16 | 3 | 0 |
| ETH_5m_SELL | $+2.30 | $+4.04 | −$1.74 | 12 | 0 | 8 |
| ETH_5m_HEDGE | $+2.16 | $+3.87 | −$1.71 | 14 | 6 | 0 |
| ETH_15m_SELL | $+16.71 | $+20.07 | −$3.36 | 9 | 0 | 4 |
| BTC_15m_SELL | $+9.23 | $+8.24 | +$1.00 ✓ | 4 | 0 | 1 |
| BTC_15m_HEDGE | $+9.92 | $+11.93 | −$2.01 | 5 | 1 | 0 |
| BTC_5m_HEDGE | $-2.66 | $+3.60 | **−$6.26** | 6 | 5 | 0 |
| BTC_5m_SELL | $-3.03 | $+1.26 | −$4.29 | 7 | 0 | 4 |
| **BTC_5m_HOLD** | $-2.66 | $-0.59 | −$2.07 | 11 | 0 | 0 |
| SOL_15m_HEDGE ✓ | $+9.98 | $+14.70 | −$4.72 | 4 | 3 | 0 |
| SOL_15m_SELL ✓ | $+10.84 | $+14.83 | −$3.99 | 4 | 0 | 3 |

### Diagnosis

**Pattern**: realfill HOLD baseline is HIGHER than shadow on the same markets — meaning **production is paying worse entry vwaps than realfill simulates**. This is **book staleness penalty**: by the time the production controller commits to fill, prices have moved against it.

Specifically for SOL 5m: realfill hold baseline is $+14.17/trade, shadow is $+0.92/trade — **$13.25/trade gap on a strategy that just holds to resolution.** This is purely entry-price slippage between the controller's book observation and the actual fill.

### Action items

1. 🔴 **Investigate SOL 5m entry slippage** — biggest gap, $-12 to -$13/trade. Compare controller's book-cache age vs realfill `snap_p95` (8 sec for SOL).
2. 🔴 **Investigate BTC 5m**: shadow LOSES $2-3/trade, realfill is FLAT ($+1/trade) — need to find why production is performing worse than no-strategy.
3. ✅ **15m sleeves match expectations**: BTC_15m_HOLD shadow +$9.92 vs realfill +$12.80 → only ~$2.90 friction. Production controller works fine here.
4. **Same-trade Δ = $1,613 over 16h** = $2,420/day expected friction. If kept paper-trading at this rate, 30 days of bleed ≈ $72k.

---


**Method:** for each shadow live fire on May 6 (~16h post-deploy), re-simulate the EXACT SAME (slug, outcome, ts) against the L25 raw orderbook captured by VPS2. Same market, same direction, same outcome — only the EXIT POLICY simulation differs. Compares the production controller's actual fill/hedge/sell vs what the realfill engine would have done with the canonical book_walk_fill simulator.

**Matched:** 221 / 299 shadow fires re-simulated successfully
**Skipped:** 78 (no L25 book at entry, spread filter, thin book)

## Headline

- Shadow live total (matched fires only): **$+598.89**
- L25 realfill SAME trades: **$+2211.63**
- Δ (realfill − shadow): **$+1612.74** (+7.297 / trade)

## Per-cell — same-trade comparison

| Cell | n | sh_pnl | rf_pnl | Δ | sh_$/trade | rf_$/trade | Δ_$/trade | rf_hold | rf_hedge | rf_sell |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_15m_HEDGE | 6 | $+29.75 | $+71.56 | $-6.68 | $+9.917 | $+11.926 | $-2.228 | 5 | 1 | 0 |
| BTC_15m_HOLD | 6 | $+29.75 | $+76.79 | $-6.68 | $+9.917 | $+12.798 | $-2.228 | 6 | 0 | 0 |
| BTC_15m_SELL | 5 | $+27.68 | $+41.19 | $-34.55 | $+9.226 | $+8.238 | $-11.518 | 4 | 0 | 1 |
| BTC_5m_HEDGE | 11 | $-18.59 | $+39.56 | $+16.43 | $-2.656 | $+3.597 | $+2.347 | 6 | 5 | 0 |
| BTC_5m_HOLD | 11 | $-18.59 | $-6.49 | $-36.66 | $-2.656 | $-0.590 | $-5.237 | 11 | 0 | 0 |
| BTC_5m_SELL | 11 | $-21.20 | $+13.81 | $-9.45 | $-3.028 | $+1.256 | $-1.350 | 7 | 0 | 4 |
| ETH_15m_HEDGE | 11 | $+93.13 | $+195.86 | $-5.91 | $+15.522 | $+17.806 | $-0.984 | 7 | 4 | 0 |
| ETH_15m_HOLD | 11 | $+93.13 | $+216.90 | $+8.65 | $+15.522 | $+19.718 | $+1.442 | 11 | 0 | 0 |
| ETH_15m_SELL | 13 | $+116.94 | $+260.86 | $-16.96 | $+16.706 | $+20.066 | $-2.423 | 9 | 0 | 4 |
| ETH_5m_HEDGE | 20 | $+28.02 | $+77.41 | $-66.20 | $+2.155 | $+3.870 | $-5.092 | 14 | 6 | 0 |
| ETH_5m_HOLD | 20 | $+28.02 | $+68.21 | $-79.84 | $+2.155 | $+3.410 | $-6.142 | 20 | 0 | 0 |
| ETH_5m_SELL | 20 | $+29.84 | $+80.72 | $-93.18 | $+2.296 | $+4.036 | $-7.168 | 12 | 0 | 8 |
| SOL_15m_HEDGE | 7 | $+39.93 | $+102.91 | $+13.61 | $+9.983 | $+14.702 | $+3.401 | 4 | 3 | 0 |
| SOL_15m_HOLD | 7 | $+39.93 | $+95.30 | $+0.88 | $+9.983 | $+13.614 | $+0.219 | 7 | 0 | 0 |
| SOL_15m_SELL | 7 | $+43.36 | $+103.82 | $+11.03 | $+10.841 | $+14.831 | $+2.757 | 4 | 0 | 3 |
| SOL_5m_HEDGE | 19 | $+11.97 | $+238.60 | $-54.33 | $+0.921 | $+12.558 | $-4.179 | 16 | 3 | 0 |
| SOL_5m_HOLD | 19 | $+11.97 | $+269.19 | $-41.38 | $+0.921 | $+14.168 | $-3.183 | 19 | 0 | 0 |
| SOL_5m_SELL | 17 | $+33.84 | $+265.45 | $-62.67 | $+2.820 | $+15.615 | $-5.222 | 16 | 0 | 1 |

## Interpretation

- **Δ ≈ 0**: production controller is matching realfill simulation. Strategy healthy.
- **Δ > 0**: realfill BEATS production — production has friction (slippage, missed exits, stale book at decision). Quantifies the friction.
- **Δ < 0**: production BEATS realfill — production luck OR realfill is too pessimistic.

## Files

- Per-trade matched: `strategy_lab\results\meta_classifier\momo_shadow_match.csv`
- Summary: `strategy_lab/results/meta_classifier/momo_shadow_match_summary.csv`
- Shadow source: `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv`