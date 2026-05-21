# Strategy Catalog — Mint-and-Sell Family (2026-05-18)

_Living document. Each strategy is isolated as a separate trading module
for shadow + live deployment. Goal: shadow ALL strategies to validate
engine, then pick 1-2 best for live deploy._

---

## Strategy archetypes decoded from chain data

| Code | Source Wallet | Daily PnL | Style | Status |
|---|---|---|---|---|
| **MAS-A** | `0x89b5cdaa` | $10k | BROAD maker (all 6 cells, small per slug) | Decoded ✅ |
| **MAS-B** | `0x04b6d7e9` | $212k | DEEP maker (BTC only, big per slug) | Decoded ✅ |
| **MAS-C** | `0xeebde7a0` | $344k | HYBRID maker+taker (BTC+ETH) | Maker decoded ✅, taker IN PROGRESS |
| **MAS-D** | `0xd44e2993` | unknown | Big undecoded counter-maker | IN PROGRESS |

---

## Strategy MAS-A — Broad maker mint-and-sell

### Signature
- 100% maker (limit SELL only)
- All 6 cells (BTC/ETH/SOL × 5m/15m), heavy on BTC 5m
- 588 slugs/day coverage (~⅔ of all markets)
- Median 10 fills/slug
- Median 166 shares/slug = ~$83 USDC sold per side
- Median pre-mint cost: ~$166/slug
- Pre-mint to support max fill rate: $1,344 (p75)

### Mechanics
```python
# At slug start:
mint_pairs = small_amount  # $30-150 USDC
splitPosition(mint_pairs)  # 1 mint TX

# Every L25 tick where sum_asks > $1.005:
post_limit_sell(side="Up",   price=best_ask_up, size=min(5, remaining_up))
post_limit_sell(side="Down", price=best_ask_dn, size=min(5, remaining_dn))
# Cancel + repost when book moves

# At slug end:
redeem(winning_side_remaining)  # leftover redemption
```

### V3 backtest results (matches this archetype)
- $30 pre-mint × 6 cells projects **+$240/day** at test scale
- Scaling to $200 → +$6,027/day
- Scaling to $1,000 (close to wallet) → +$30k/day at this archetype's edge

### Risk
- Held-side selection bias at high pre-mint (leftover loses on average)
- Need queue position — slow execution = fewer fills

### Status
- Backtested ✅ (V3 trade-driven simulator)
- Ready for shadow mode

---

## Strategy MAS-B — Deep maker mint-and-sell

### Signature
- 100% maker (limit SELL only)
- BTC only (BTC 5m + BTC 15m)
- 163 slugs/day (more selective)
- Median 198 fills/slug (much denser)
- Median 4,634 shares/slug
- Median $20,259 USDC per slug (deep capital)
- $12.85M daily volume

### Mechanics
Same as MAS-A but:
- Pre-mint much larger ($5,000-20,000 per slug)
- Cell selection: BTC only (where deepest liquidity)
- Tolerates higher fire density (200/slug = 1 every ~1.5s during slug)

### Why selective?
- BTC has 5-10x more taker volume than ETH/SOL
- BTC 5m has most slugs (5887 over 21d)
- Deep pre-mint requires deep taker demand to clear

### Capital efficiency vs MAS-A
- Same edge per pair sold (~$0.01-0.02 spread + rebate)
- Edge × volume = MAS-B captures 20x more dollars per slug
- ROC is similar (~10-20%/day per slug)

### Status
- Backtested ✅ (V3 backtest extrapolates to ~$50/slug at $200 pre-mint, $200+/slug at wallet scale)
- Ready for shadow mode if we accept higher capital requirement

---

## Strategy MAS-C — Hybrid maker + taker

### Signature
- 50% maker / 50% taker fires
- BTC heavy (88%) + some ETH
- 588 slugs/day coverage
- $4,411 USDC per slug median
- $95.7M daily volume
- $344k/day PnL (biggest of the 3 decoded)

### Maker side
Same as MAS-A/B: post SELLs at best_ask when sum_asks > $1
- Median 50 fills/slug @ avg $0.99/share

### Taker side (the differentiator)
Market-BUYs when one side's ask drops below fair value
- Median 103 fills/slug
- Median size: 7 shares/fill
- **Avg buy price: $0.726** (way below $0.50 fair → deep discount captured)

### Trigger for taker fires (DECODE IN PROGRESS by Agent 1)
TBD — likely:
- One side's ask dropped sharply (mid-slug ask collapse)
- Binance price moved strongly in opposite direction
- Sum_asks DROPPED below $1.005 (other makers panic-sold)

### Status
- Maker side: backtested ✅
- Taker side: trigger decoding in progress
- Will be ready for shadow once taker trigger is locked

---

## Strategy MAS-D — 15m-only broad maker (decoded ✅)

`0xd44e2993` turned out to be the SMALLEST of the four (counter-maker rank-#1 was a fragmentation artifact, not real volume).

### Signature
- 100% maker (limit SELL only) — pure mint-and-sell
- **15-MIN ONLY** (zero 5m exposure — UNIQUE among the 4 makers)
- Broad: BTC + ETH + SOL
- ~176 active slugs/day (15m markets cycle slower)
- Median **$13.53 USDC per slug** (TINY scale)
- Median size per fill: **1.5 shares** (much smaller than CLOB min!?)
- ~81% two-sided slugs (posts both Up + Down)
- Daily volume: ~$5.8k observed, true probably $15-30k
- Sells in LOW price band (median price $0.27)

### How it compares
| Wallet | $/day | $/slug | Cells | Timeframes |
|---|---|---|---|---|
| 0xeebde7a0 | $344k | $4,411 | BTC+ETH | 5m + 15m |
| 0x04b6d7e9 | $212k | $20,259 | BTC | 5m + 15m |
| 0x89b5cdaa | $10k | $299 | All 6 | 5m + 15m |
| **0xd44e2993** | **~$15-30k** | **$13.53** | All 6 | **15m only** |

### Verdict
- Same archetype as MAS-A (broad maker) — just **smaller + 15m-only**
- **NOT worth a separate strategy module** — would be MAS-A with a `tf_filter=["15m"]` config flag
- DROP as a separate strategy. Note the 15m-only insight for MAS-A: could test if 15m-only is more profitable than mixed

Full report: `strategy_lab/reports/WALLET_DECODE_0xd44e2993_2026_05_18.md`

---

## Shadow mode — running ALL strategies in parallel

### Goal
- Validate that the engine fires correctly per strategy spec
- Measure realized fill rate vs simulated fill rate
- Compare strategies on the same live data window (apples to apples)
- Pick the 1-2 best for LIVE deploy

### Setup (to be implemented)
Per strategy, log decisions to a separate `shadow_<strategy_code>.csv`:

```csv
ts_us, slug, asset, tf, action, side, price, size, sum_asks, fill_within_60s, actual_fill_px, actual_fill_size, projected_pnl
```

Run on VPS3 with the live WS feed. Each strategy is its own decision loop.
NO orders submitted (shadow only).

After 48h:
- Compute realized $/slug per strategy
- Pick winner(s) by Sharpe + total PnL
- Promote to live with $30-200 per slug starting capital

### Strategy isolation
Each strategy gets its own Python module:

```
strategy_lab/strategies/
├── __init__.py
├── base.py             # StrategyBase interface (on_l25, on_trade, on_slug_end)
├── mas_a_broad.py      # Pure maker, all 6 cells, $30-150 pre-mint
├── mas_b_deep.py       # Pure maker, BTC only, $1-20k pre-mint
├── mas_c_hybrid.py     # Maker + taker, BTC+ETH, $2-5k pre-mint
└── mas_d_*.py          # TBD after decode
```

Each can be enabled independently via config:

```python
SHADOW_CONFIG = {
    "strategies": ["MAS-A", "MAS-B", "MAS-C", "MAS-D"],
    "cells_per_strategy": {
        "MAS-A": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
        "MAS-B": ["btc_5m", "btc_15m"],
        "MAS-C": ["btc_5m", "btc_15m", "eth_5m", "eth_15m"],
    },
    "shadow_only": True,  # set False for live
    "max_concurrent_slugs_per_strategy": 5,
}
```

### Live promotion criteria
After 48h shadow:
- realized $/slug > $0 in p25 (positive in 75% of slugs)
- realized fill rate ≥ 50% of simulated
- daily PnL > $50 projection

If 2+ strategies pass, run BOTH live with separate capital pools.

---

## Open questions

1. **Capital allocation**: if we run 4 strategies × 6 cells × $30-200 each = ?
2. **Strategy correlation**: do MAS-A and MAS-C cannibalize each other?
3. **VPS3 capacity**: can the engine handle 4 strategy decision loops + 12 cells = 48+ concurrent contexts?
4. **Order rate limits**: Polymarket CLOB likely has per-second limits — does running 4 strategies bust them?

---

## Next steps

1. Wait for Agent 1 (taker trigger decode) + Agent 2 (0xd44e2993 decode) — both running
2. Append findings to this doc
3. Decide go/no-go on each strategy
4. Build the shadow framework
5. Deploy shadow on VPS3 for 48h
6. Pick live winners

