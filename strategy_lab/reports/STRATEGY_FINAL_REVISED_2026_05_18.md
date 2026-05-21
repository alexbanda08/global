# FINAL Strategy Decision (REVISED with imbalance analysis) — 2026-05-18

_Imbalance analysis revealed the 3 "maker" wallets are doing 3 different
strategies. This doc supersedes earlier versions._

---

## Imbalance discovery (the missing piece)

Per-slug analysis of Up vs Down inventory accumulation:

| Wallet | $/day | Paired% (median) | Imbalance % (median) | Real strategy |
|---|---|---|---|---|
| **0x04b6d7e9** | $212k | **92%** | **8%** | **PURE PAIR ARB** ✅ |
| 0xeebde7a0 | $344k | 50% | 50% | HYBRID arb + DIRECTIONAL |
| 0x89b5cdaa | $10k | 0% | 100% | PURE DIRECTIONAL BUYER |

**Only 0x04b6d7e9 runs the strategy we thought** (post bids on both sides, accumulate equally, merge for $1 arb).

The other two are betting on direction:
- 0xeebde7a0 hedges with paired arb but also bets directionally on ~50% of inventory
- 0x89b5cdaa is purely directional (not a maker pair arb at all)

---

## Implications for our deploy

### Strategies that need NO alpha (safe to deploy)

1. **ACC-M** (Pure Pair Arb) — mimics 0x04b6d7e9
   - Post BIDs on both Up + Down
   - Strict balance discipline: keep imbalance < 10%
   - Merge paired inventory via NegRiskAdapter
   - Edge: 0.5-1.6% per pair (real, verified)
   - Test $/day at $50 seed: ~$25-50

2. **MAS** (Mint-And-Sell) — our V3 invention
   - Mint pairs, post ASKs at sum_asks > $1
   - Wait for takers to lift
   - Held-side bias risk (managed by small pre-mint)
   - Edge: ~$0.02/pair + maker rebate
   - Test $/day at $30 pre-mint × 6 cells: ~$144

### Strategies that need DIRECTIONAL alpha (skip for now)

3. ~~**ACC-H**~~ (Hybrid) — would mimic 0xeebde7a0
   - Half their PnL is directional bets we can't replicate
   - Skip until we have a directional signal layer

4. ~~**DIR**~~ — would mimic 0x89b5cdaa
   - Pure directional, $10k/day
   - Skip until alpha source identified

---

## Final shadow deploy plan

```python
SHADOW_DEPLOY = {
    "strategies_enabled": {
        "ACC-M": {
            "cells": ["btc_5m", "btc_15m"],  # start where 0x04b6d7e9 operates
            "seed_usdc": 50,
            "max_imbalance_shares": 5,        # tight discipline
            "post_size_shares": 5,
        },
        "MAS": {
            "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
            "pre_mint_per_slug_usdc": 30,
            "post_size_shares": 5,
        },
    },
    "total_wallet_seed_usdc": 230,  # $50 ACC-M + $180 MAS (6 cells × $30)
    "shadow_only": True,
    "duration_hours": 48,
}
```

---

## What to ship to TV agent

3 specs in `strategy_lab/reports/`:

1. **TV_AGENT_SPEC_ACC_M_2026_05_18.md** ✅ Deploy this in shadow
2. **TV_AGENT_SPEC_MAS_2026_05_18.md** ✅ Deploy this in shadow
3. **TV_AGENT_SPEC_ACC_H_2026_05_18.md** ⚠️ DO NOT deploy — requires alpha layer

Each spec has:
- Full state machine
- All decision rules with code
- Configuration parameters (with calibrated defaults)
- Per-slug fire-count expectations
- Risk controls
- Shadow logging requirements
- Promotion criteria
- Implementation checklist for TV agent

---

## Critical implementation rules (apply to BOTH deploy strategies)

1. **Inventory balance is non-negotiable** for ACC-M:
   - `MAX_IMBALANCE_SHARES = 5` (calibrated from 0x04b6d7e9's 8% discipline)
   - Stop posting heavy side when violated
   - Hard cap `ABSOLUTE_MAX_INVENTORY = 50`

2. **Merge route** — use NegRiskAdapter `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0`
   - All decoded wallets use this
   - Auto-merges paired tokens, credits USDC.e in same tx
   - Cheaper than direct `CTF.mergePositions`

3. **Currency on-chain is USDC.e** `0x2791bca1...` (Polymarket calls it pUSD in UI)

4. **Timing pattern** (from chain decode, consistent across all 3 wallets):
   - 0-220s: accumulation (post bids, wait for fills)
   - ~336s: merge (relay does it)
   - Stop posting at 270s offset for 5m slugs

5. **CLOB minimum order: 5 shares per side** ($2.50 notional at avg $0.50)

---

## Live promotion criteria

After 48h shadow, promote IF:

**For ACC-M**:
- Mean realized $/slug > $0 (any positive)
- Median realized $/slug > $0 (>50% positive slugs)
- Realized fill rate > 30% of optimistic simulator
- Max 24h drawdown < $25
- No more than 2 slugs with >25% imbalance (discipline check)

**For MAS**:
- Mean realized $/slug > $0.10
- Median realized $/slug > $0
- No more than 3 consecutive losing slugs per cell
- Max 24h drawdown < $30

If pass: enable live, $50 ACC-M + $180 MAS, start with BTC 5m only for ACC-M, all 6 cells for MAS.

---

## Files cleaned up & ready for TV agent

| File | Purpose |
|---|---|
| `strategy_lab/reports/TV_AGENT_SPEC_ACC_M_2026_05_18.md` | **DEPLOY** ACC-M spec |
| `strategy_lab/reports/TV_AGENT_SPEC_MAS_2026_05_18.md` | **DEPLOY** MAS spec |
| `strategy_lab/reports/TV_AGENT_SPEC_ACC_H_2026_05_18.md` | Reference only (needs alpha) |
| `strategy_lab/reports/STRATEGY_FINAL_REVISED_2026_05_18.md` | This doc (overview) |
| `strategy_lab/reports/WALLET_TX_TAXONOMY_2026_05_18.md` | Background — transaction taxonomy |
| `strategy_lab/reports/RELAY_WALLET_DECODE_0xf3cfb6a6_2026_05_18.md` | Background — relay = NegRiskAdapter |
| `strategy_lab/wallet_hunt/replicate/acc_simulator.py` | Backtest reference for ACC-M |
| `strategy_lab/wallet_hunt/replicate/v3_wallet_trade_driven.py` | Backtest reference for MAS |
