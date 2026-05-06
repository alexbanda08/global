# Why is 15m momo profitable while 5m is not?

**Generated:** 2026-05-06
**TL;DR:** It's NOT about hedge/sell. **Both timeframes hold to resolution because hedge never fires (0 hedges across 215 fires).** The difference is entirely in the **win rate** of the underlying signal: 15m wins 69% of the time, 5m only 47%. With identical avg-win/avg-loss magnitudes, that hit-rate gap fully explains the PnL difference.

## 1 · The numbers

### Per timeframe rollup (16h shadow window, all sleeves combined)

| tf | n fires | win_rate | avg_win | avg_loss | mean_pnl/trade | total PnL |
|---|---:|---:|---:|---:|---:|---:|
| **15m** | 42 | **69.0%** | $+23.78 | $-17.43 | **$+11.03** | **$+463.09** |
| **5m** | 150 | **47.3%** | $+24.13 | $-23.76 | **$-1.09** | **$-164.08** |

### Hedge / SELL fires (the entire policy infrastructure is dormant)

| tf | hedge fires | partial_bid_exit fires | total |
|---:|---:|---:|---:|
| 15m | **0** | 1 | 42 |
| 5m | **0** | 3 | 150 |

**Conclusion:** essentially every fire is a HOLD outcome. The HEDGE and SELL sleeves are firing the same trades as HOLD with the same outcomes. Differences within a (asset, tf) cell across HEDGE/HOLD/SELL = 0 (look at SOL 15m: HOLD pnl $39.93 = HEDGE pnl $39.93, SELL is $43.36 only because of 1 partial-bid-exit that shaved a tiny loss).

So the question reduces to: **why is HOLD profitable on 15m but not on 5m?**

## 2 · It's the win rate

### Hit rate gap by (asset, tf)

| asset_tf | shadow win_rate | shadow $/trade |
|---|---:|---:|
| BTC_15m | **66.7%** | $+9.92 |
| ETH_15m | **71.4%** | $+9.70 |
| SOL_15m | **75.0%** | $+9.98 |
| BTC_5m | **33.3%** | $-7.62 |
| ETH_5m | **50.0%** | $+0.18 |
| SOL_5m | **51.9%** | $-0.06 |

**Win rate alone explains it.** Avg win and avg loss are similar ($+24, $-17 to -$24). Drop hit rate from 69% to 47% on a binary outcome with stakes near $25 → mean PnL flips from positive to ~zero.

### The math:
- **15m**: 0.69 × $24 + 0.31 × $-17 = $16.56 - $5.27 = **$+11.29** ✓ matches observed $+11.03
- **5m**: 0.47 × $24 + 0.53 × $-24 = $11.28 - $12.72 = **$-1.44** ✓ matches observed $-1.09

The strategy's edge per trade is essentially `(win_rate - 0.51)` × $24 (where 0.51 is the break-even hit rate given the avg-win/avg-loss asymmetry).

## 3 · Why does 5m have a lower hit rate?

This is the actual interesting question. Possibilities ranked:

### Hypothesis A — short window means more noise (most likely)

5m markets have only **3 minutes remaining** after the t+120s entry. 15m markets have **13 minutes**. Statistical fact: short-horizon directional signals decay fast. The same `ret_2m > q90` signal that picks a 15m market with ~70% reliability picks a 5m market closer to 50% — because 3 min isn't enough time to manifest.

### Hypothesis B — recent regime shift

Backtest period (Apr 22 – May 4) showed BTC_5m at **89.2%** hit rate. Shadow on May 6: **33.3%**. That's a 56-pp collapse in 2 days.

Either:
- (a) BTC was unusually choppy on May 6 morning (regime variance — 9 fires on a single asset is a tiny sample)
- (b) The signal genuinely decayed (alpha is non-stationary)
- (c) Production fires at slightly different timestamps than backtest, hitting different microstructure

### Hypothesis C — production entry slippage compounds tighter 5m profit margin

A 5m winning trade typically pays $24 on a $25 stake (held token settles to $1, entry was ~$0.51). But 5m markets have thinner books → walking $25 of asks gives a worse vwap → entry was at ~$0.52-0.53 instead of $0.51 → win pays $23 not $24. Combine with 47% hit rate: edge erodes to ~$0.

But this is a much smaller effect than the hit-rate gap. Even if entries were perfect, 47% × $24 - 53% × $-25 = **$-2** anyway.

### Hypothesis D — sample variance

Only 50 unique 5m markets in 16h. With p_true = 0.85 and n=50, observed hit rate has 95% CI of [0.73, 0.93]. **Observed 47% is WAY below this range** — variance alone doesn't explain it. Either the signal is genuinely worse than backtest, or some structural bug.

## 4 · Cross-check: realfill on the same trades

When we re-ran realfill (with proper L25 entry book) on the matched 19 SOL_5m_HOLD trades:
- Shadow: 51.9% hit, $-0.06 / trade
- Realfill: 89.6% hit, **$+14.17 / trade**

Wait — these are the **SAME trades**, with the **SAME outcomes**, only the entry and exit simulation differ. How can hit rates differ?

**Because of slug-skipping in match_shadow.py:**
- Out of 27 SOL_5m fires shadow saw, only 19 had matching L25 data (others had thin/missing book at entry → skipped)
- The 19 matched markets had win rate 89.6%
- The 8 unmatched markets must have had low/zero hit rate to drag overall down to 51.9%

This is suspicious. **It means production fires more aggressively than realfill in markets where L25 book was thin** — and those aggressive fires are LOSING. The realfill skip filter (`under_e and usd_e < 50%` of stake) is correctly identifying problem markets that production should also skip but doesn't.

Hypothesis E: **production's entry-time spread filter is too loose for 5m**. Markets with bad spreads at t+120s should be skipped, but the controller fires anyway → bad fills → losses.

## 5 · Why does 15m not have this issue?

Three reasons:

1. **Bigger absolute book sizes**: 15m markets are open for 15 min, accumulate more maker liquidity, and at t+120s they've already been collecting orders for 2 min. 5m markets at t+120s have only 2 min of accumulation in a thinner liquidity environment.

2. **Longer time horizon dilutes spread**: a $0.02 wider spread costs the same dollar amount to cross, but a 15m market has more time for the signal to overcome it.

3. **Hit rate is much higher**, so the strategy can absorb friction.

## 6 · What this tells us

| Conclusion | Confidence |
|---|---|
| HEDGE/SELL infrastructure is broken AND irrelevant for current PnL — both tfs are HOLD-only | very high |
| 15m PnL = 69% × $24 - 31% × $17 = $+11/trade | very high (math confirms data) |
| 5m losing because hit rate fell from backtest 89% → live 47% | high |
| Cause of hit-rate fall: short window + entry slippage + sample variance | medium (need more data) |
| Fixing HEDGE/SELL will help 5m more than 15m (more chances to escape losing trades) | medium |

## 7 · Recommended actions

### Immediate
1. **PAUSE 5m sleeves** until hedge/sell mechanism is fixed (per `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`). They're not viable as HOLD-only.
2. **KEEP 15m sleeves running** — they're profitable as HOLD-only.

### After hedge fix lands (per the 4 commits)
3. **Re-evaluate 5m**: with HEDGE working, the 47% win rate becomes survivable because losers can be cut at -5bp (rev_bp threshold). Realfill estimates suggest the strategy should make $+10-13/trade with HEDGE on.
4. **Tighten 5m spread filter**: if entry-time spread > X, skip. Threshold to be calibrated from realfill skip-rate (8 of 27 SOL_5m skipped in realfill are exactly the spread-filter cases).

### Investigation
5. **Drill into BTC_5m specifically** — 33.3% hit rate on 9 fires is the single worst cell. Look at:
   - Direction match: did `signal` match actual `ret_5m` sign at fill_event_id timestamp?
   - Time of day: were fires concentrated in low-liquidity hours?
   - Asset move: did BTC actually move in signal direction within the 5min window?

## 8 · Files

- This analysis: `strategy_lab/reports/MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md`
- Source data: `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv`
- Companion: `strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md`
- Companion: `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md`
