# Momo Exit-Policy Variant Exploration

**Date:** 2026-05-09
**Goal:** Find a momo exit-policy variant that beats HOLD on the live 7-day window. Test rev_bp thresholds, time-forced exits, profit-take, stop-loss (Polymarket-side), and combos.
**Data:** 228 unique deduped fires from the 851-row live momo v1+v2 trade log; replayed against L25 WS books and 1m Binance klines (strict asof, partial-fill enabled).

## Bottom line

**Every uniform variant loses money on this window.** The strategy is in a losing regime — what differs is HOW MUCH each variant loses. Top 5 variants vs HOLD baseline:

| rank | variant | fire% | pnl_total | Δ vs HOLD |
|---:|---|---:|---:|---:|
| 1 | **HEDGE_3bp** | 52.6% | **−$336** | **+$200** |
| 2 | HYBRID_3bp | 52.6% | −$336 | +$200 |
| 3 | **STOP_HEDGE_0.5x** | 48.7% | **−$341** | **+$196** |
| 4 | SELL_3bp | 52.6% | −$345 | +$191 |
| 5 | STOP_SELL_0.5x | 48.7% | −$346 | +$190 |
| ... | | | | |
| n | HOLD_baseline | 0% | −$536 | (baseline) |

The two newly-promising mechanisms uncovered:

### 1. **Lower rev_bp threshold (3bp instead of 5bp)** beats higher
- 3bp: −$336 (HEDGE), −$345 (SELL)
- 5bp: −$452 (HEDGE), −$464 (SELL)
- 10bp: −$766 (HEDGE), −$780 (SELL)
- 15bp: −$697 (HEDGE), −$706 (SELL)

Higher thresholds fire less but **on much worse trades** — when Binance reverses 10+ bp, the trade is usually already a write-off and the exit captures less.

### 2. **STOP exits triggered by Polymarket-side bid drop** (not Binance reversal)
- STOP_HEDGE_0.5x = "if our held-side bid drops to 50% of entry vwap, fire the hedge" → **−$341**
- STOP_SELL_0.5x = "if bid drops to 50%, sell out at whatever price" → **−$346**

Both rank in top 5. Polymarket-bid is a better leading indicator of trade death than Binance reversal: the book moves first, Binance follows. This deserves a dedicated sleeve test.

## What clearly DOES NOT work

| variant family | result | reason |
|---|---|---|
| TIME_*_t60, t120 | among the worst (−$700 to −$840) | Fires too early, before alpha has played out. Pure cost. |
| Profit-take SELL (1.05x, 1.10x, 1.20x, 1.30x) | mediocre (−$444 to −$716) | Captures small profits but caps upside on the 90% win-and-settle path. The strategy makes its money on $1 chainlink settlement, not Polymarket overshoots. |
| TIME_*_t240 | bad (−$563/-$564) | Firing 60s before resolution is the worst-of-both-worlds: no alpha left, but added book-walk slippage. |
| HEDGE_15bp, SELL_15bp | bad (−$696/-$706) | Fires too rarely on already-doomed trades. |

## Per-cell winners (best variant by cell)

⚠ Sample sizes 7-50 trades per cell — high noise. Per-cell winners are exploratory, not statistically robust.

| cell | best variant | pnl |
|---|---|---:|
| SOL_5m (v1) | SELL_15bp | **+$159** |
| SOL_5m (v2) | HOLD_baseline | +$150 |
| ETH_15m (v2) | STOP_SELL_0.5x | +$74 |
| SOL_15m (v2) | STOP_SELL_0.5x | +$60 |
| ETH_15m (v1) | STOP_SELL_0.5x | +$57 |
| BTC_5m (v2) | SELL_3bp | +$50 |
| BTC_15m (v1) | COMBO_HEDGE_RevOrStop | +$46 |
| BTC_15m (v2) | TIME_SELL_t240 | +$34 |
| SOL_15m (v1) | STOP_SELL_0.7x | +$22 |
| BTC_5m (v1) | SELL_3bp | +$0 |
| ETH_5m (v2) | COMBO_AllExits | −$25 |
| ETH_5m (v1) | SELL_7bp | −$28 |

If you cherry-pick per-cell winners (high overfit risk on this window), total = **+$598** vs uniform HEDGE_3bp **−$336** vs HOLD **−$536**.

The most consistent per-cell signal is **STOP_SELL_0.5x** — wins on 3 cells (ETH_15m × 2, SOL_15m × 1) and never finishes worst. Suggests the "Polymarket bid below half entry → exit" rule has cross-cell stability.

## Mechanism explanation: why STOP_SELL_0.5x works

When we bought YES at 0.61 and the bid drops to 0.30 a minute later, two things are true:
1. The Polymarket book is pricing the YES side as a loser (book-side leading indicator)
2. The Binance asset has likely reversed direction substantially

If we wait for chainlink, we get $0 (loss = entry cost). If we SELL at the 0.30 bid for partial recovery, we lock in some payout. Even though it's a partial loss, it's better than $0.

This is a **bid-side trail-stop**, not a Binance-anchored revert. Different mechanism from the production rev_bp logic.

## Three new strategy variants worth shipping for live A/B

Each is independent — could ship one or all three.

### Variant A — `momo_v3_lower_threshold`
- Same as `momo_v2` but `rev_bp = 3` instead of 5
- Expected delta: +$200/week vs current v2 (lab estimate, noisy)
- Risk: fires more often, more book-walk fees on losers
- Code change: 1 env var per cell or 1 module-level constant

### Variant B — `momo_v3_bid_stop`
- New trigger family: SELL/HEDGE when own_bid_top < entry_vwap × 0.5
- Independent of Binance rev_bp (book-side leading indicator)
- Expected delta: +$196/week vs HOLD on this window
- Risk: cheap-bid noise on illiquid markets could trigger spurious exits
- Code change: new on_tick branch in `_maybe_hedge` / `_maybe_sell_at_bid` that reads own-side book each tick

### Variant C — `momo_v3_combo`
- Compound trigger: rev_bp(5bp) **OR** bid_stop(0.5x) **OR** profit_take(1.10x) → fire HEDGE
- Most aggressive variant; highest fire rate
- Expected delta: −$370 (better than HOLD −$536 but worse than pure A or B)
- Risk: composite triggers harder to reason about; over-trading on noise

**Recommended priority: ship Variant B first.** STOP_SELL_0.5x and STOP_HEDGE_0.5x are top-3 ranked variants AND show consistency across cells. The mechanism is novel (book-side leading indicator vs current Binance-anchored rev_bp) and worth testing in live.

Variant A is a safe tweak (just lower a threshold).

Variant C is too complex for a first A/B and underperforms A and B.

## Caveats

- **7-day window with ~38 trades/cell average.** Statistical power is low. The per-cell winners table shouldn't drive shipping decisions on its own.
- **Losing regime.** All variants lose. We're choosing the LEAST-bad option. A profitable regime might rank variants differently — STOP_SELL_0.5x might miss winners.
- **Backtest assumes WS-fresh book at each tick.** Real production has whatever staleness the WS mirror provides. STOP variant requires fetching own-side book every tick (10s); ensure subscription is alive throughout the holding window.
- **Partial-fill enabled in all variants.** Earlier finding: partial-fill itself only matters on 18 SOL_5m trades. Most of the gain in this analysis comes from trigger choice, not fill semantics.

## Next steps

1. **Run walk-forward** on a longer window (May 1 → May 9) to validate the variant ranking is stable, not regime-dependent.
2. **Backtest on a profitable historical window** (April 22 → April 30 had +$13K HOLD pnl) to see if STOP_SELL_0.5x still ranks top — or if it eats winners.
3. **If both walk-forward and profitable-regime tests confirm Variant B**: write the v3-bid-stop sleeve spec and ship 18 sleeves to TV agent.
4. If Variant B is regime-fragile: drop the idea, settle for Variant A's smaller but more robust gain.

## Files
- `strategy_lab/meta_classifier/momo_exit_policy_explore.py` — sweep engine
- `data/v4/shadow_trades_2026_05_08/momo_exit_policy_explore_per_trade.csv` — 7980 rows
- `data/v4/shadow_trades_2026_05_08/momo_exit_policy_explore_summary.csv` — per-variant totals
