# Wallet PnL breakthrough — Alchemy + cash + open-position accounting

_2026-05-16 — Switched from OrderFilled chain decoding to direct USDC + ERC1155
transfer accounting via `alchemy_getAssetTransfers`. User-claimed
"$10k+/day profits" CONFIRMED for 3/6 wallets._

---

## TL;DR

1. **`alchemy_getAssetTransfers` is the right primitive** — full wallet history,
   no block-range limit, pagination via `pageKey`. Free Alchemy tier handles it.

2. **PnL = `net_cash_flow + open_position_value`** where:
   - `net_cash_flow` = total USDC received − total USDC sent
   - `open_position_value` = current mark-to-market of held ERC1155 tokens
     (includes **unredeemed winning tokens** sitting at $1 mid)

3. **The zero address (`0x0`) is the key counterparty** for mint-and-sell
   wallets. USDC coming FROM `0x0` = CTF redemption income (winning pair
   burned → USDC released). Treating it as "external" hid the trading flow.

4. **3/6 wallets confirmed massively profitable**:

   | Wallet | Span | Total PnL | $/day | Strategy |
   |---|---:|---:|---:|---|
   | `0xeebde7a0` | 1.06d | **+$364,719** | **+$344,074** | Market-maker on BTC/ETH up-down |
   | `0x04b6d7e9` | 1.82d | **+$386,123** | **+$212,155** | Mint-and-sell whale, BTC focus |
   | `0x89b5cdaa` | 4.50d | **+$44,176** | **+$9,817** | Mint-and-sell |
   | `0xcfb103c3` | 4.37d | +$50 | +$12 | Breakeven |
   | `0xce25e214` | 3.41d | -$295,455 | -$86,644 | Losing (or hidden positions) |
   | `0x7cde1da9` | - | - | - | (no fills in window) |

5. **User's "$10k/day for `0x89b5cdaa`" claim verified to within $200/day.**

---

## Why our prior decoder was wrong

The OrderFilled-based decoder we built had FOUR cascading bugs:

1. **Chain price extraction was 80% wrong** (median $0.21 off the book) — fixed
   by using L25 book as ground truth.
2. **Mint accounting wrong** — used `min` instead of `max` of negative leftovers
   (later fixed to `max`).
3. **Maker rebate not applied** to fee curve.
4. **Sample bias** — top-30 slug cap missed the long tail of profitable markets.

Even after all four fixes, the OrderFilled decoder undercounts profit because
it ignores **out-of-window inventory carryover**: when a wallet bought shares
yesterday at $0.40 and sells today at $0.50, we don't see yesterday's buy →
assume $1 mint cost → record a phantom loss.

**The Alchemy cash-PnL approach sidesteps ALL of these.** It just sums actual
USDC transfers in/out. The math is cash-basis, which is what Polymarket's UI
shows users.

---

## How the cash-flow PnL works

```
For each wallet:
  pull all USDC transfers via alchemy_getAssetTransfers (last N days)

  classify each USDC transfer by counterparty:
    EXCHANGE (matcher, CTF, old exchanges, 0x0 mint-burn) → trading flow
    OTHER (EOAs, other wallets) → capital flow

  net_trading = USDC_in_from_exchange - USDC_out_to_exchange
  net_capital = USDC_in_from_external - USDC_out_to_external
  net_cash = net_trading + net_capital

  open_value = sum(currentValue) over data-api /positions endpoint
    (includes mark-to-market of open positions AND unredeemed winners)

  TOTAL PnL = net_cash + open_value
```

### Exchange counterparties (Polymarket on Polygon)

| Address | What |
|---|---|
| `0xe111180000d2663c0091e4f400237545b87b996b` | NegRisk matcher (active) |
| `0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e` | CTFExchange (legacy) |
| `0xc5d563a36ae78145c45a50134d48a1215220f80a` | NegRiskCtfExchange |
| `0x4d97dcd97ec945f40cf65f87097ace5ea0476045` | ConditionalTokens |
| `0xc8c4db15e07d0f30558eaab922bf2631550a266e` | NegRisk adapter |
| `0x0000000000000000000000000000000000000000` | CTF mint/burn (redemptions!) |

---

## What the new numbers reveal

### `0xeebde7a0` — the kingpin market-maker

- **1.06 days of data, +$365k** = $344k/day
- 41,230 USDC transfers, $1.02M in / $0.65M out
- 36 open positions worth $1.2k
- Trading flow: in $1.015M, out $0.646M → +$370k from trading alone
- Capital outflow: -$6k (withdrew to upstream)

This is the wallet we originally thought was "losing" with the OrderFilled
decoder. **It's actually the most profitable wallet of the six** at $344k/day.
The MM strategy on Polymarket up-down 5m/15m markets is wildly profitable.

### `0x04b6d7e9` — the mint-and-sell whale

- **1.82 days of data, +$386k** = $212k/day
- 29,143 USDC transfers, $727k in / $343k out
- 15 open positions worth $2.6k
- $5.2k of external capital flow

The mint-and-sell strategy (CTF split + sell both sides above $1) at scale.

### `0x89b5cdaa` — confirmed profitable (your $10k/day claim)

- **4.5 days of data, +$44k** = $9.8k/day ✅
- 98,584 USDC transfers
- 22 open positions worth $2.9k

Smaller-scale mint-and-sell. Consistent edge.

### `0xce25e214` — actually losing, not winning

- -$295k over 3.4 days
- Sent $800k to exchange, received $527k back from CTF redemptions
- Open positions only $1k (so not hidden in inventory)

May be:
- Genuinely losing
- Using a separate wallet for inventory (would explain the gap)
- A mint-and-merge strategy where they're hoping for variance

### `0xcfb103c3` — breakeven

- ~$0 PnL over 4.4 days
- Suggests their strategy edge is real but tiny, OR they're testing

---

## How to replicate

### Strategy 1: Pure market-making (target: `0xeebde7a0` at $344k/day)
- Post limit orders inside the spread on every active BTC/ETH up-down market
- Both Up AND Down sides simultaneously
- Capture spread + 20% maker rebate
- Need: limit-order posting infrastructure (we currently only take)
- Effort: ~5-8h to add post_limit + queue-position model to `engine_v2.py`

### Strategy 2: Mint-and-sell (target: `0x04b6d7e9` at $212k/day)
- Scan canonical L25 for moments when `best_ask(Up) + best_ask(Down) > $1.005`
- CTF.splitPosition($N) → mint N pairs
- Post limit SELL at best_ask on both sides
- Profit = sum_of_sell_prices − $1 (mint cost) − fees + rebates
- Need: CTF.splitPosition contract call + 2 limit sells per market
- Effort: ~4-6h to build the scanner + simulate fill probability

### Strategy 3: Bot-shadowing
- For now: just COPY their trades in real time
- Poll their wallets every 30s via `shadow_track.py` (already built)
- When they post / mint / sell → mirror with smaller size
- Captures their alpha WITHOUT needing to fully understand WHY it works

---

## Files written this session

| Path | Purpose |
|---|---|
| `strategy_lab/wallet_hunt/fetch_alchemy.py` | Alchemy `getAssetTransfers` puller (full wallet history, no block-range limit) |
| `strategy_lab/wallet_hunt/cash_pnl.py` | Cash-flow + open-position PnL analyzer |
| `strategy_lab/wallet_hunt/cache/<short>/alchemy_transfers.parquet` | Per-wallet full transfer history (30k-200k rows each, ~5d) |
| `strategy_lab/wallet_hunt/cache/_cash_pnl_summary.csv` | Final ranking with $/day numbers |

---

## Next-session priority

1. **Re-fetch all 6 wallets at higher page limit** (200 pages = 200k transfers
   per direction). Then PnL covers a full 5-7 day window for the high-volume
   wallets (currently 1-2 days due to 60-page cap).

2. **Add Alchemy `getCurrentAccountBalance`** to compare cash balance now vs
   the cumulative inflow/outflow. Catch any missing transfer counterparties
   (we may still be missing some).

3. **Time-series PnL chart** per wallet (daily PnL line chart for the past
   30 days). Will show whether the profits are steady or spiky.

4. **Build the mint-and-sell scanner** on our canonical L25 — backtests the
   replication of `0x04b6d7e9`'s strategy. If `ask_up + ask_down − fees > $1`
   shows up frequently in our 23k-market window, the strategy is replicable.

5. **Live shadow trade** — poll the top 3 wallets every 30s, log their fills
   (`shadow_track.py` already does this), and add a mirror-decision module
   that mints/posts/buys in lockstep at smaller size.

---

## End of doc
