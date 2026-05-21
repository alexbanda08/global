# Wallet 0xb27bc932 — Last-Day Decode

_2026-05-20. Wallet `0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82`.
Pipeline: fetch_alchemy → cash_pnl → custom deep-dive (no decoder.py
slug-based fires_decoded because this wallet uses different counterparties
than the mint-and-sell wallets)._

## TL;DR — what this wallet is doing

**0xb27bc932 is a pure-TAKER directional buyer, NOT a maker bot.** Different
strategy class from the mint-and-sell wallets we previously decoded.

| Metric | Value |
|---|---|
| Window | 12.67h (2026-05-20 02:05 → 14:45 UTC) |
| Total transfers | 4,740 (2,365 pUSD + 2,375 ERC1155) |
| BUY fills (via matcher) | **1,722** ($12,091 spent) |
| BUY fills (other counterparties) | ~120 ($895 spent) |
| SELL fills (any) | **0** |
| Mint (splitPosition) | **0** |
| Merge/Redeem | **0** (positions all settled = $0 open) |
| Unique markets touched | 33 |
| **Net cash PnL** | **−$500.45** |
| **Open positions value** | **$0** (all settled in-window) |
| **Total PnL** | **−$504.67** (−$952/day extrapolated) |

## Strategy fingerprint vs known patterns

| Signal | b27 last 24h | Mint-and-sell wallets | Pair-accumulator | Verdict |
|---|---|---|---|---|
| % SELL fills | **0%** | ~99% | ~0% | NOT M&S |
| % BUY fills | **100%** | ~1% | ~96% | matches pair-accumulator OR pure taker |
| Mints (splitPosition) | **0** | many | rare | NOT M&S |
| Counterparty mix | matcher 95%+ direct buys | matcher SELL fills | matcher BUY fills | TAKER pattern |
| Held inventory | $0 (all settled) | rotates rapidly | accumulates | NOT accumulator |
| Capital flow | 1 deposit ($12,485 from pUSD bridge) | rotates capital | rotates capital | TAKER topping up |
| **Strategy class** | **Aggressive directional taker** | maker | accumulator | **NEW: TAKER** |

## What the data shows mechanically

### BUY fill counterparties

Almost all fills are direct matcher trades:
- **1,722 fills** via matcher `0xe111180000d2663c0091e4f400237545b87b996b` (Polymarket CLOB matcher)
- ~120 small fills via other counterparties (likely fragmented order matching from CLOB)
- **ZERO** fills via SELL side
- **ZERO** mints (splitPosition / 0x4d97...)
- **ZERO** burns (mergePositions / redeemPositions visible in this window — positions resolved out-of-band)

### Price distribution of BUYs

| Price bucket | n | $ spent | % of capital |
|---|---|---|---|
| 0.5-1¢ | 22 | $13 | 0.1% |
| 1-2¢ | 24 | $5 | 0.04% |
| 2-5¢ | 100 | $50 | 0.4% |
| 5-10¢ | 279 | $188 | 1.6% |
| 10-20¢ | 272 | $559 | 4.6% |
| 20-40¢ | 230 | $626 | 5.2% |
| 40-60¢ | 207 | $1,557 | 12.9% |
| 60-80¢ | 286 | $2,536 | 21.0% |
| **80-100¢** | **302** | **$6,558** | **54.2%** |

**Critical observation: 75%+ of capital deployed at prices ≥60¢ — they're betting on
EXPECTED WINNERS, not lottery tickets.** This is NOT a value-buy strategy. It's
a high-conviction taker that pays the ask for likely-winners.

### Sizing distribution

- Median per-trade: **$2.30**
- p25: $0.55
- p75: $7.12
- Max: **$454.01** (single big bet)
- Total: $12,091 spread across 1,722 fills

Small per-fill (suggests they're hitting tiny CLOB asks repeatedly across many
markets) but with occasional large bets.

### Timing — burst-y

Almost all activity (**1,947 / 1,963 TXs**) concentrated in a **38-minute window**:
`2026-05-20 13:21:07 → 13:59:25 UTC`

Outside that window: 2 transfers at 02:05 UTC, 2 at 06:00, 2 at 11:20. Sparse.

This is NOT a 24/7 maker bot. It's an event-driven taker that fires hard during
specific moments — likely during high-volatility binance prints when 5m/15m
markets become predictable.

### Why open positions = $0

cash_pnl queried the Polymarket `/positions` API → got 0 open positions.

Combined with no merge/redeem TXs in the window, this means: **all 1,722 BUYs
from the 13:21-13:59 burst resolved and settled BEFORE we queried at ~14:45 UTC.**

That fits perfectly with 5m and 15m up-down markets:
- BUY at 13:30 in a 5m market → settles at 13:35 (or next aligned 5m)
- BUY at 13:30 in a 15m market → settles at 13:45 or 14:00
- By 14:45, everything has settled and been auto-redeemed

The wallet is using Polymarket's **deposit-wallet flow with pUSD** (POLY_1271
signature type) — this auto-settles winning positions to pUSD balance without
explicit `redeemPositions` calls. That's why we don't see burns/redeems in
the chain transfer data even though the wallet clearly closed positions.

## PnL accounting reconciliation

```
pUSD SENT to matcher:        $12,985.82  (all BUY fills + fees)
pUSD RECEIVED from 0x0:      $12,485.37  (resolution payouts via pUSD bridge)
pUSD SENT to other addresses: $4.22       (gas + tiny ops)

NET = -$504.67
```

The "$12,485 from 0x0" is the pUSD bridge / CTF settlement mechanism crediting
the wallet for winning tokens. It's NOT a deposit — it's the realized payout
from the 1,722 BUYs settling.

So the wallet spent $12,985 buying tokens and got back $12,485 from winners.
**Hit rate at ~96% breakeven, but lost the spread + fees → −$500.**

## What this means

### This wallet is NOT a candidate to mimic

Three reasons:

1. **It loses money.** −$952/day extrapolated. Doesn't matter how interesting
   the pattern is — copying a losing strategy is anti-edge.

2. **Different strategy class.** Pure taker, not maker. The mint-and-sell
   strategy we're building exploits sum_asks > $1 from the MAKER side
   (capturing the surplus when the book is mispriced). This wallet does the
   OPPOSITE — paying full ask to enter directional bets.

3. **Burst timing suggests momentum-following.** Activity concentrated in a
   38-min window aligns with binance volatility events triggering up-down
   market repricing. This wallet is probably trying to ride binance momentum
   into short-form market resolutions — but the spread + fee cost on takes is
   killing them.

### What IS interesting about this wallet

1. **High-conviction sizing on 80-100¢ outcomes.** $6,558 of $12,091 (54%) deployed
   at prices ≥80¢. They have STRONG opinions about which side wins. If their
   read is right ~96% of the time as the data shows (-$500/12k = -4.2% loss
   to "near-breakeven"), the strategy is *almost* viable — they just lose to fees.

2. **The 38-minute burst pattern** is worth correlating with binance prints. Did
   BTC have a big move during 13:21-13:59 UTC today? If so, this wallet's
   "edge" might be reacting to specific binance events. We could re-examine
   their PnL on days where they DID profit.

3. **They use pUSD (new collateral)** — POLY_1271 deposit wallet flow.
   This is the same setup recommended in our spec for the live bot. Validates
   the flow works end-to-end at high frequency.

### A note on counterparty `0xf3cfb6a6`

Wallet sent 26 ERC1155 transfers to `0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0`
across 13 TXs (2 transfers per TX). That address is also in our wallet cache
(decoded 2026-05-18). It might be:
- A linked "operations" wallet for the same operator
- A specialized contract that handles redemption/settlement
- A separate bot for a different leg of a paired strategy

Worth a follow-up decode if the user wants to trace cross-wallet activity.

## Files

- Cache: `strategy_lab/wallet_hunt/cache/0xb27bc932/`
  - `alchemy_transfers.parquet` — 4,740 rows (last 13h)
- Analysis: `strategy_lab/wallet_hunt/_analyze_b27_deep.py`
- Cash PnL summary: `strategy_lab/wallet_hunt/cache/_cash_pnl_summary.csv`

## Conclusion

0xb27bc932 is a **losing directional taker** running in a burst pattern around
volatility events. **Not a candidate to copy.** Fundamentally different strategy
from the mint-and-sell maker bots we're building toward.

The four profitable wallets we found earlier (0xeebde7a0 $344k/d, 0x04b6d7e9
$212k/d, 0x89b5cdaa $10k/d, 0xf7f0b0b1 $281/d) remain the right reference set
for our deploy.
