# Strategy Spec — MAS (Mint-And-Sell maker)

_2026-05-18. Standalone deployment spec for the mint-and-sell-as-maker
strategy. This is our **V3 invention** — does not perfectly match any
decoded wallet, but the backtest is strongly profitable._

---

## TL;DR

**Mechanism**: Mint Up+Down pairs upfront, post limit SELL orders at
`best_ask` on both sides, wait for takers to lift them, collect cash +
maker rebates, redeem leftover inventory at slug end.

**Edge source**: `sum_asks − $1` per pair sold + 20% maker rebate per fill.
Typical: ~$0.01-0.02 per pair sold + ~$0.007 rebate = **~$0.02 per pair**.

**Backtest projection** (V3 trade-driven simulator):
- $50 pre-mint × 6 cells = **+$1,016/day**
- $200 pre-mint × 6 cells = **+$6,027/day**
- $500 pre-mint × 6 cells = +$15,339/day (held-side bias risk)

**Capital efficient because**: USDC recycles per fill (cash from sells immediately re-available for next slug). Mint cost is one-time per slug.

---

## Decoded wallet that runs anything like this?

**None of our decoded wallets actually do this.** The 3 "mint-and-sell" wallets we initially identified (0x89b5cdaa, 0x04b6d7e9, 0xeebde7a0) turned out to be MAKER-BID + TAKER-BUY accumulators (the ACC strategy), not mint-and-sell.

MAS is our invention based on the structural mispricing `sum_asks > $1`. It's not "copy a wallet" — it's "be the OTHER side of the trade from the accumulator wallets".

---

## Lifecycle per slug

```
T=0 (slug starts)
  IF cell is enabled AND we have capital for pre_mint:
    Call CTF.splitPosition(amount=pre_mint_usdc)
      → wallet pays N USDC.e
      → wallet receives N Up tokens + N Down tokens
    Inventory: up=N, dn=N
    
T=1...slug_end-buffer (loop)
  ON every L25 update:
    IF sum_asks >= min_sum_asks AND spread_up <= max_spread AND spread_dn <= max_spread:
      Cancel old orders if best_ask moved more than tick_threshold
      Post limit SELL Up at best_ask_up, size=min(post_size, remaining_up)
      Post limit SELL Down at best_ask_dn, size=min(post_size, remaining_dn)
  
  ON every order fill (someone took our ask):
    cash += fill_shares × fill_price
    rebates += fill_shares × maker_rebate(fill_price)
    inv -= fill_shares
    
T=slug_end-buffer (just before close)
  Cancel all open orders
  
T=slug_end+settlement_buffer (after chainlink resolves)
  Call CTF.redeemPositions(condition_id)
    → wallet receives N × $1 for winning_side tokens
    → losing_side tokens worth $0
  
PnL = cash + rebates + redemption - mint_cost
```

---

## Parameters

```python
MAS_CONFIG = {
    # Cell selection
    "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
    
    # Per-slug capital
    "pre_mint_usdc": 30,            # Test scale; production 100-500
    
    # Posting rules
    "post_size_shares": 5,          # Polymarket CLOB minimum
    "min_sum_asks": 1.005,          # Only post when edge exists
    "max_spread_per_leg": 0.05,     # Don't post on illiquid wide books
    "repost_threshold_cents": 1,    # Cancel + repost when book moves > 1c
    
    # Timing
    "fill_wait_s": 60,              # GTC orders, but track for diagnostics
    "cancel_buffer_s": 30,          # Cancel orders this many sec before slug end
    
    # Risk
    "min_post_inventory": 5,        # Stop posting if remaining < CLOB min
    "max_concurrent_slugs_per_cell": 2,
}
```

---

## Capital requirements

| Pre-mint | Per-slug capital | Cells | Concurrent | Total deployed |
|---|---|---|---|---|
| $30 | $30 | 6 | 2 each | $360 max |
| $100 | $100 | 6 | 2 each | $1,200 max |
| $200 | $200 | 6 | 2 each | $2,400 max |

Note: USDC recycles per slug (5-15 min cycles). Effective bankroll requirement is much lower than peak deployed.

---

## Expected daily PnL by scale

Based on V3 trade-driven simulator (mid-rank 100 slugs, all 6 cells):

| pre_mint | sol_5m | sol_15m | btc_5m | btc_15m | eth_5m | eth_15m | TOTAL $/day |
|---|---|---|---|---|---|---|---|
| $30 | $80 | $14 | $20 | $9 | $11 | $11 | **~$144** |
| $50 | $441 | $70 | $189 | $57 | $158 | $101 | **$1,016** |
| $100 | $1,398 | $103 | $351 | $106 | $308 | $32 | **$2,299** |
| $200 | $3,429 | $523 | $717 | $164 | $1,019 | $176 | **$6,027** |

(Note: $30 numbers extrapolated from $5/$10/$20 sweep; saturation kicks in around $20.)

---

## Risk model

### What can go wrong

1. **Held-side selection bias**: when one leg fills and the other doesn't, we hold the "loser" 60-70% of the time (selection bias). Mitigation: keep pre_mint small (≤ $200) so inventory always clears.

2. **Wide-book traps**: if spread > 5¢ per leg, fills happen at bad prices. Mitigation: `max_spread_per_leg` filter.

3. **Queue position**: our small 5-share orders sit behind larger maker queues. Fill rate may be 20-50% of optimistic projection. Mitigation: shadow mode to measure actual fill rate.

4. **Stale book data**: if our L25 feed lags, we post at outdated prices. Mitigation: post-and-quickly-cancel on book moves, use WS not REST.

5. **Mint TX cost**: each `splitPosition` is ~150k gas (~$0.003 on Polygon). Negligible at our scale but adds up if we mint per-slug.

### What kills the strategy entirely

- Polymarket fee model changes (currently 7% taker, 20% rebate to makers)
- Adapter/CTF migration to new contract (would need code update)
- Disabled outcome markets (no more BTC/ETH/SOL 5m/15m up-down)

---

## Comparison to wallet-mimicked strategy (ACC)

| | MAS (this spec) | ACC (wallet-mimic) |
|---|---|---|
| Pre-mint required | YES ($30-200/slug) | NO ($0 upfront) |
| Order side | Limit SELL at best_ask | Limit BID at best_bid |
| Capital direction | Net SHORT inventory (sell tokens) | Net LONG inventory (buy tokens) |
| Edge per pair | ~$0.02 | ~$0.18 |
| Mints? | YES, once per slug | NO |
| Merges? | NO (just redeem at slug end) | YES (continuous mid-slug) |
| Backtest validated | ✅ V3 backtest | TBD (need new simulator) |
| Wallet exists doing this? | NONE in our cache | 3 confirmed wallets |
| Simplicity | Medium | High (no mint needed) |
| Daily PnL ceiling | ~$15k at $500 pre-mint | $344k seen in wild |

---

## Files for MAS

| File | Purpose |
|---|---|
| `strategy_lab/wallet_hunt/replicate/v3_wallet_trade_driven.py` | The validated backtest simulator |
| `strategy_lab/reports/MINT_AND_SELL_V3_PROFITABLE_2026_05_18.md` | Full backtest results |
| `strategy_lab/reports/MINT_AND_SELL_V3_TEST_DEPLOY_SPEC_2026_05_18.md` | Original test deploy spec |
| `strategy_lab/strategies/base.py` | StrategyBase interface |
| `strategy_lab/strategies/mas.py` | (to build) MAS implementation |

---

## To deploy MAS in shadow

1. Build `strategy_lab/strategies/mas.py` implementing `StrategyBase`
2. Add to shadow runner with `cells=[...]` config
3. Wire to VPS3 L25 + trade WS feeds
4. Log decisions to `shadow_mas_<date>.csv`
5. Compare realized fills vs simulated

After 48h shadow: if realized PnL/slug matches simulator within 30%, promote to live at $30 pre-mint.

---

## To deploy MAS LIVE

Once shadow passes:
1. Start at $30 pre-mint × 1 cell (sol_5m — highest backtest $/slug)
2. Run for 24h
3. If PnL matches projection: scale to all 6 cells
4. After 7 days: increase to $100 pre-mint
5. After 14 days: $200 if no drawdown

Maximum recommended: $200 pre-mint (above this, held-side bias risk grows).
