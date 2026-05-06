# Stop-Loss Backtest on V3 ∪ Phase 7 Union

**Run date:** 2026-05-05
**Universe:** 534 bets (V3 prob_stack ≥ 0.65 OR Phase 7 |slope_2m| ≥ p95) where book_depth_v3_full had intra-window data
**Hypothesis tested:** Adding a stop-loss exit reduces the asymmetric loss tail (lose 102% on losing bet vs win 98% on winning bet) and improves total ROI.

## TL;DR

**The intuition was right in theory, wrong in practice. Stop-loss HURTS this strategy at every threshold tested.**

| Stop Level | Bets | Stopped | True (would-lose) | False (would-win) | Total PnL | ROI | vs no-stop |
|---|---:|---:|---:|---:|---:|---:|---:|
| **NONE** | 534 | 0 | 0 | 0 | **$62.33** | **+23.34%** | — (baseline) |
| 0.45 (tightest) | 534 | 361 | 200 | 161 | $34.61 | +12.96% | **-44%** |
| 0.40 | 534 | 336 | 200 | 136 | $34.90 | +13.07% | -44% |
| 0.30 | 534 | 281 | 197 | 84 | $41.57 | +15.57% | -33% |
| 0.20 | 534 | 239 | 192 | 47 | $46.40 | +17.38% | -26% |
| 0.10 (deepest) | 534 | 202 | 186 | 16 | $57.07 | +21.37% | **-9%** |

Even the deepest stop (0.10, only triggers if YES token bid drops to ~10c) hurts ROI by 9%.

## Why theory says stop-loss should work

The asymmetry user identified is real:
- **Win**: bet $0.50, payoff $1.00 - $0.005 fee = **+$0.495 net** (98% gain on capital risked)
- **Loss**: bet $0.50, payoff $0.00 - $0.005 fee = **-$0.505 net** (102% loss on capital risked)

If we could predict losing bets early and exit at $0.30 instead of $0:
- Loss reduced: $0.505 → $0.205 = save $0.30 per stopped bet
- Even at 70% true-stop rate, expected gain = +$0.21 per stopped bet

## Why empirical reality breaks the theory

### The killer: false stops

Polymarket BTC UpDown short-horizon markets have **thin orderbooks** and **wild mid-window swings** that don't reflect true resolution probability. A 5min market's YES token bid can drop to $0.20 mid-window even when the underlying BTC eventually fires UP and the market resolves at $1.00.

Look at the false-stop counts:

| Stop | Bets stopped | Of those, would have WON | False-stop rate |
|---|---:|---:|---:|
| 0.10 | 202 | 16 | 7.9% |
| 0.20 | 239 | 47 | 19.7% |
| 0.30 | 281 | 84 | 29.9% |
| 0.45 | 361 | 161 | **44.6%** |

At stop 0.45 (closest to our $0.50 entry), **45% of stopped bets would have eventually won**. Every false stop costs us $0.945:
- Without stop: paid $0.50, won $1.00 = +$0.495
- With stop at 0.45: paid $0.50, sold at ~$0.37 (avg) = -$0.135
- Difference: **lost $0.63 per false stop**

### True stops save less than expected

| Stop | Avg loss when stopped | Avg loss without stop |
|---|---:|---:|
| 0.10 | -$0.452 | -$0.505 (saves $0.05) |
| 0.20 | -$0.375 | -$0.505 (saves $0.13) |
| 0.30 | -$0.280 | -$0.505 (saves $0.225) |
| 0.45 | -$0.136 | -$0.505 (saves $0.37) |

The "deep" stops (0.10) save almost nothing per true stop because at $0.10 we're selling for pennies. The "shallow" stops (0.45) save more per true stop but trip many more false stops.

### The math at stop=0.10 (best stop level tested)

- 186 true stops × $0.053 saved = **+$9.86 saved**
- 16 false stops × $0.945 cost = **-$15.12 lost**
- Net: **-$5.26 vs no-stop** ✓ (matches data: $62.33 → $57.07)

## The deeper insight

**Polymarket binary prediction markets at short horizons (5min/15min) do NOT have the same mean-reverting orderbook dynamics as continuous markets (futures, options).** Mid-window price drops are dominated by:
1. Thin liquidity moments (someone hits a stale bid)
2. Tactical traders front-running expected resolution
3. Noise from leverage cascades on related crypto markets

These dynamics REVERSE quickly. The eventual resolution price (1.0 or 0.0) is determined by where BTC closes vs strike at the END of the window — not by mid-window book prices.

**Stop-loss in continuous markets** captures meaningful drawdown signals because price IS the consensus probability.

**Stop-loss in binary prediction markets** captures noise because price IS NOT the consensus probability (it's whatever thin liquidity is offering at a given second).

## What might actually work (alternative exit rules)

The simple "exit if bid < threshold" loses money. Worth testing in future:

1. **Time-conditional stop**: only stop in first 30s (early evidence stronger than mid-window noise)
2. **Velocity stop**: exit if bid drops more than $0.30 in a single bucket (fast moves more likely to be info)
3. **Cross-confirmation stop**: exit only if our signal source (V3 prob_stack or Phase 7 slope) ALSO flipped against us mid-window
4. **Asymmetric stop**: tighter stops on Phase 7-only bets (lower confidence) than V3 bets (higher confidence)
5. **Hedge instead of stop**: open offset position in NO token rather than selling YES (preserves win optionality if recovery happens)

These all need the per-bucket book + signal data we have. Each is ~1-2h backtest work.

## Recommendation

**Don't add stop-loss to V3 ∪ Phase 7 union.** Keep the current "hold to resolution" approach — it's empirically correct for short-horizon Polymarket markets.

The V3 ∪ Phase 7 union remains the deployment candidate at:
- 534 bets in 5 days
- 62.2% hit rate
- +23.3% ROI per bet on $0.50 stake
- $62.33 total PnL on $1 per bet (= $124 expected at $2/bet, $623 at $10/bet, etc.)

The asymmetric payoff is **a feature of binary prediction markets, not a bug to engineer around**. The 62.2% hit rate already overcomes the asymmetry by enough margin to be profitable.

## Files

```
strategy_lab/meta_classifier/stoploss_backtest.py            re-runnable backtest
strategy_lab/results/meta_classifier/stoploss_results.csv    9 stop levels × per-bet metrics
strategy_lab/reports/STOPLOSS_BACKTEST.md                    this file
```

## Open follow-up (worth ~1-2h work)

If user disagrees with the "don't bother" verdict, the next experiment to try is **velocity-based stop**: only exit if bid drops by ≥ $0.30 in a single 10s bucket (true info shock vs noise dip). That filters out the false-stop killer. Estimated: ~1h to backtest.

---

*End of STOPLOSS_BACKTEST.md. Honest verdict: classic stop-loss doesn't work on binary prediction markets. The asymmetric payoff is solved by hit rate (62.2% > breakeven 50.5%), not by exit rules.*
