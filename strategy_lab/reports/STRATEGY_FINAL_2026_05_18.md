# FINAL Strategy Decision — 2026-05-18

_Complete picture after taxonomy + relay decode. This supersedes earlier
catalog versions._

---

## What we now KNOW with 100% certainty

All 4 decoded wallets (`0x89b5cdaa`, `0x04b6d7e9`, `0xeebde7a0`, `0xf7f0b0b1`) follow the SAME core pattern with minor variations:

```
                  THE WINNING PATTERN

  ┌─────────────────────────────────────────────────────────┐
  │                                                         │
  │   1. POST LIMIT BIDS at best_bid_up + best_bid_dn       │
  │      (no minting; just USDC.e in wallet backs the bids) │
  │                                                         │
  │   2. WAIT for takers to SELL into our bids              │
  │      → receive Up tokens at $0.X, Down tokens at $0.Y   │
  │      → average pair cost = $0.X + $0.Y < $1.00          │
  │                                                         │
  │   3. (optional) When ask drops below fair → market BUY  │
  │                                                         │
  │   4. Once paired_inventory ≥ threshold:                 │
  │      Send Up+Down pairs to NegRiskAdapter (0xf3cfb6a6)  │
  │      → relay merges, returns USDC.e ($1 per pair)       │
  │                                                         │
  │   5. Recycled USDC.e → back to Step 1                   │
  │                                                         │
  │   6. At slug end: redeemPositions for any leftover      │
  │                                                         │
  └─────────────────────────────────────────────────────────┘

  EDGE per cycle: $1 − (avg_buy_price × 2) ≈ $0.05-$0.20
  CAPITAL: $47k seed in 0x04b6d7e9 → 280× rotation/day → $212k/day
```

## Two strategies to shadow (both should run in parallel)

### Strategy 1: **ACC** (Accumulator) — the proven money-maker

**Source**: Direct copy of 0x04b6d7e9 (cleanest template, $212k/day).

**Mechanism**:
- Post limit BIDs at best_bid on both sides
- Accumulate paired Up+Down
- Merge via NegRiskAdapter every ~336s
- Recycle USDC.e

**Validated by**: 3 wallets making $10k-$344k/day

**Edge per pair**: ~$0.18 ($1 − ~$0.82 avg pair cost)

**Test config**:
```python
ACC_TEST = {
    "cells": ["btc_5m", "btc_15m"],     # Start BTC-only like 0x04b6d7e9
    "wallet_seed_usdc": 50,
    "post_size_shares": 5,              # CLOB minimum
    "max_bid_price": 0.50,              # Only bid below parity
    "min_bid_price": 0.05,              # Skip extreme outcomes
    "merge_threshold_pairs": 5,         # Merge when 5+ paired
    "merge_offset_s": 336,              # Match wallet timing exactly
    "stop_posting_offset_s": 270,       # Stop posting 30s before slug close
}
```

**Expected $/day**: $25 (test) → $700 ($250 seed) → $1,875 ($500 seed)

### Strategy 2: **MAS** (Mint-And-Sell) — our V3 invention

**Source**: V3 backtest (NO wallet does this — we'd be filling the wallets' bids).

**Mechanism**:
- Mint pairs upfront via `splitPosition`
- Post limit ASKS at best_ask on both sides
- Wait for takers to lift
- Redeem leftover

**Validated by**: V3 trade-driven simulator, NOT by any wallet

**Edge per pair**: ~$0.02 (sum_asks − $1 + maker rebate)

**Why also run this**: It's the MIRROR side of ACC. When V3 sells at $0.51 to a taker, that taker may be 0x04b6d7e9 buying at our ask. We complement, not compete.

**Test config**:
```python
MAS_TEST = {
    "cells": ["btc_5m", "btc_15m", "eth_5m", "eth_15m", "sol_5m", "sol_15m"],
    "pre_mint_usdc": 30,                # Per slug
    "post_size_shares": 5,
    "min_sum_asks": 1.005,
    "max_spread_per_leg": 0.05,
}
```

**Expected $/day**: $144 (test) → $1,016 ($50 pre-mint) → $2,299 ($100 pre-mint)

---

## Why run BOTH in shadow

| | ACC | MAS |
|---|---|---|
| **Source** | Real wallet (verified) | Our backtest invention |
| **Edge/pair** | ~$0.18 | ~$0.02 |
| **Capital required** | $50-500 wallet | $30-200 pre-mint per slug |
| **Mints required** | NO | YES |
| **Risk** | Low (capital recycles, leftover is small) | Medium (held-side bias on partials) |
| **Capital recycles** | Continuously (every ~336s) | Per slug (5-15 min) |
| **PnL ceiling** | $344k/day (seen in wild) | $15k/day (V3 backtest) |

**Shadow both** to:
1. Validate our engine fires correctly (different code paths)
2. Compare realized vs simulated fill rates per strategy
3. Pick winner(s) for live with confidence
4. Hedge against one strategy degrading (if competition increases on one side)

---

## Shadow deployment plan (TODAY)

### 1. Build the simulators

- ACC simulator: `strategy_lab/wallet_hunt/replicate/acc_simulator.py`
  - Drives signals from trades parquet (taker SELLs hit our bids)
  - Tracks paired inventory, simulates merges at the ~336s marker
  - Validates against 0x04b6d7e9's actual fills

- MAS simulator: already exists at `strategy_lab/wallet_hunt/replicate/v3_wallet_trade_driven.py`

### 2. Implement strategy modules

- `strategy_lab/strategies/base.py` (DONE)
- `strategy_lab/strategies/acc.py` (TODO)
- `strategy_lab/strategies/mas.py` (TODO)

### 3. Wire shadow runner

- `strategy_lab/strategies/shadow_runner.py` (TODO)
  - Subscribe to L25 WS feed (from VPS3)
  - Subscribe to trades WS feed
  - Subscribe to chainlink resolution events
  - For each strategy module: dispatch L25/trade/binance events
  - Log every Decision to `shadow_<strategy>_<date>.csv`
  - Compute realized PnL per slug at slug end

### 4. Deploy on VPS3

- Cron / systemd service running shadow_runner.py
- 48h shadow validation
- Daily reports comparing realized vs simulated

### 5. Live promotion

After 48h shadow:
- IF realized $/slug > $0.50 AND realized fill rate > 50% of simulated:
  - Enable live trading flag
  - Start at $50 ACC + $30 MAS pre-mint
  - Monitor for 24h
  - Scale if successful

---

## Critical implementation details (from chain decode)

### Timing rules (from 0x04b6d7e9 and others)

| Action | Offset window | Rationale |
|---|---|---|
| Post first bids | 0-30s after slot_start | Get good queue position |
| Continue posting | 30-270s | Active accumulation |
| Stop posting | 270-300s | Don't get stuck with last-minute fills |
| Send pairs to relay | ~336s (= 36s into next slot) | After previous slot resolves |

### Order specifications (CLOB rules)

- **Minimum size**: 5 shares per side
- **Price increment**: $0.01 (1¢)
- **Order type**: GTC (good-til-cancelled), or PostOnly to avoid being a taker
- **Cancel + repost**: when book moves > $0.01 from our limit price

### Contract addresses (Polygon mainnet)

```python
USDC_ADDR        = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"  # Bridged USDC.e
PUSD_WRAPPER     = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"  # Polymarket's pUSD wrapper
CTF              = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"  # ConditionalTokensFramework
CLOB_MATCHER     = "0xe111180000d2663c0091e4f400237545b87b996b"  # Polymarket Exchange v2
NEGRISKADAPTER   = "0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0"  # Auto-merger relay
```

### Fee model (verified)

```
Taker fee:     0.07 × p × (1−p) per share
Maker rebate:  0.20 × taker_fee  (we get this when our maker order fills)
```

At p=$0.50 (mid-market): fee = $0.0175/share, rebate = $0.0035/share.

### Capital sizing math

For ACC to mimic 0x04b6d7e9 at 1/100th scale:
- Seed: $470 USDC.e
- Velocity: 280×/day
- Volume: $130k/day
- PnL at 1.6% edge: $2,080/day

For testing safely:
- Seed: $50 USDC.e
- Conservative velocity: 50×/day (early stages, lower fill rate)
- Volume: $2,500/day
- PnL at 1% edge: $25/day

---

## What to NOT do

- ❌ **Do NOT post ASKS in ACC** — wallets never do this
- ❌ **Do NOT mint in ACC** — no `splitPosition`; just hold USDC.e
- ❌ **Do NOT market-sell** — exit always via merge
- ❌ **Do NOT use direct `mergePositions`** — use NegRiskAdapter relay route
- ❌ **Do NOT chase fills past 270s offset** — book closes in 30s, merge phase starts
- ❌ **Do NOT scale beyond test until 48h shadow passes**

---

## Open questions for VPS3 wiring

1. **WS subscription**: Polymarket's CLOB WS feed for L25 books + trades?
2. **Chainlink resolution events**: how do we get the slug outcome to trigger redeem?
3. **Order signing**: EIP-712 signature for Polymarket CLOB — need wallet key on VPS3
4. **Rate limits**: Polymarket has order-rate caps; might need throttling at 100+ posts/min
5. **Failsafe**: kill switch if drawdown > $X in 1h

---

## Next concrete steps

1. **Build ACC backtest simulator** to validate against 0x04b6d7e9 (1-2h)
2. **Build `strategies/acc.py` + `strategies/mas.py`** modules (1-2h)
3. **Build `shadow_runner.py`** with WS subscriptions (3-4h)
4. **Test shadow runner locally** with mock data (1h)
5. **Deploy to VPS3** for 48h shadow run
6. **Daily diff vs simulator** to validate engine
7. **Promote to live** at $50+30 capital
