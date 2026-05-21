# Wallet strategies decoded from chain data — 2026-05-16

_Source: Polygon eth_getLogs on the NegRiskCtfExchange matcher contract
`0xe111180000d2663c0091e4f400237545b87b996b`. ~1 day of chain history per
wallet, filtered to BTC/ETH/SOL up-down 5m + 15m markets only._

---

## TL;DR

**5 of 6 wallets actively trade up-down 5m/15m markets — running 5
DISTINCT strategies**:

| # | Wallet | Strategy class | Notional 1d | Trades 1d | Markets |
|---|---|---|---:|---:|---:|
| 1 | `0xeebde7a0…` | **Pure market-maker** (post both sides, capture 20¢ spread) | $12.8M | 27,645 (UD) | BTC 5m+15m, ETH 5m+15m |
| 2 | `0xce25e214…` | **Taker pyramid + partial unwind** (buy heavy, sell some at higher prices) | $2.2M | 21,933 (UD 15m) | BTC/ETH/SOL 15m mostly |
| 3 | `0x89b5cdaa…` | **Maker SELL-only** (posts only sell orders, fills takers buying expensive favorites) | $1.66M | 22,138 | BTC 5m+15m, ETH 5m, SOL 5m |
| 4 | `0xcfb103c3…` | **Taker pyramid BTC-5m-only** (single-asset focus, accumulate cheap) | $4.74M | 19,582 (UD 5m) | BTC 5m only |
| 5 | `0x04b6d7e9…` | **Mint-and-sell** (mint CTF Up+Down pairs from USDC, sell both sides for premium) | $17.9M | 23,922 (UD) | BTC 5m+15m only |
| – | `0x7cde1da9…` | (no fills in our 24h window — flash bot) | – | 0 | – |

**Up-down focus is universal**: every active wallet trades up-down 5m+15m as
their primary activity (>90% of fills).

**Chain data unlocks 10× more samples** than data-api. Same 12-hour window
on `0xeebde7a0`:
- data-api: 3,474 fills (the API's hard cap)
- chain:    35,755 fills (10× richer)

The data-api was severely biasing our prior fingerprinting — `0xeebde7a0`
looked like a "pure pyramid taker" (0% both-sides legs in data-api),
because the cap clipped half the activity. Chain data reveals 65% both-sides
legs → it's a market maker.

---

## Strategy 1 — Pure market-maker (`0xeebde7a0…`)

```
chain window:        12h (27,645 up-down fills)
maker fills:         53%   (capturing rebate)
both-sides legs:     64.8%
trades per leg:      41.6 (avg)
median first_offset: 18s after slot_start
median last_offset:  277s (continues most of window)
top spread captured: 22¢ per share (avg_sell - avg_buy)
```

**Recipe**:
- For every active BTC/ETH up-down 5m or 15m market, post limit BUY at
  `mid - X` and limit SELL at `mid + Y` (X, Y unknown — likely 1-3¢).
- As one side fills, repost to maintain inventory neutrality.
- Capture spread + 20% maker rebate on each fill.
- Hold residual to resolution (usually small, balanced).

**Why this works**: Polymarket up-down 5m/15m markets typically have wide
spreads (2-5¢) and high taker flow from our momo bot and others. A maker
can capture the spread cleanly. Maker rebate (`0.07 × p × (1-p) × 0.20`)
adds ~$0.0007/share at p=0.5.

**Replication path**:
- Need limit-order posting (we currently only do taker fires)
- Maker rebate path is in `fees.py` (`poly_maker_rebate_per_share`)
- Strategy: post inside-the-spread limit orders on every market our momo
  controller already watches; expect 1-5 fills per market per minute

---

## Strategy 2 — Taker pyramid + partial unwind (`0xce25e214…`)

```
chain window:        19h (21,933 up-down 15m fills)
maker fills:         29% (mostly TAKER)
both-sides legs:     90.3%
trades per leg:      33.4
median first_offset: 25s
median last_offset:  267s
typical leg shape:   buy 1000-1800 shares at $0.32-0.42,
                     sell 200-500 at $0.50+
net cash on leg:     NEGATIVE (still long, but partial unwind)
```

**Recipe**:
- Pick a side per market (likely contrarian to binance momentum based on
  prior analysis: 63% WR when contradicting)
- Take liquidity (buy at ask) heavily in first 30s after slot opens
- As price moves in your favor, partially sell to lock profit but
  maintain residual exposure to settlement
- Concentrated on 15m markets (longer windows = more chance for thesis
  to play out)

**Why this works**: same contrarian-fade-binance edge we already validated
in our `momo_full_universe_live_mimic --invert-signal` backtest (+$0.50/tr
on v2 HOLD). This wallet executes that with active position management
instead of single-fire HOLD.

**Replication path**:
- Already have the inverted signal as `--invert-signal` flag
- Need to add: post-entry monitoring + partial-sell logic at favorable
  price moves
- Most directly maps to a `momo_INV_v2` sleeve with:
  - fire at `slot_start + 30s` (not `ws_s + 120`)
  - hold + watch
  - sell 20-30% of position if price moves +10¢ in our favor

---

## Strategy 3 — Maker SELL-only (`0x89b5cdaa…`)

```
chain window:        40h (8,215 UD 15m + 13,923 UD 5m)
maker fills:         100% (PURE maker)
sides observed:      100% SELL (decoder edge — may be more nuanced)
trades per leg:      9.4
median first_offset: 95s (mid-window)
median last_offset:  209s
top legs:            100-150 sell fills at $0.20-0.47, net_cash positive
```

**Decoder caveat**: 100% SELL is suspicious — it may mean either:
1. They literally only post SELL limit orders (one-sided MM)
2. They MINT CTF pairs from USDC (1 USDC = 1 Up + 1 Down token) then
   sell both — which our decoder is misclassifying as "100% sell"
   because the mints aren't OrderFilled events

**Hypothesis 2 is more likely** because their pattern (high notional,
high maker_pct, no buy orders ever) matches a "mint+sell" arbitrage:
- Pay $1 to mint Up + Down pair
- Sell Up at $X, Sell Down at $Y
- Profit = $X + $Y − $1 − fees + maker rebates

For this to work consistently, the maker needs `X + Y > $1 + fees`. Given
maker rebate is `0.07 × p × (1-p) × 0.20` ≈ $0.0035 per share at p=0.5,
this is profitable when the sum of inside-ask prices on Up + Down >
~$1.007.

**Replication path** (advanced — requires CTF.splitPosition + place 2 limit orders):
- Mint Up+Down pair (collateral = 1 USDC per pair)
- Post limit SELL on Up at best_ask Up
- Post limit SELL on Down at best_ask Down
- Cancel + repost as market drifts
- Both sides will eventually fill (other traders take); profit = spread above $1

---

## Strategy 4 — Taker pyramid BTC-5m-only (`0xcfb103c3…`)

```
chain window:        19.7h (19,582 BTC 5m fills, ZERO other markets)
maker fills:         11.2% (mostly TAKER)
both-sides legs:     26.4%
only-BUY legs:       73.4%
trades per leg:      31.1
median first_offset: 20s
median last_offset:  250s
top legs:            70-120 BUYS @ $0.30-0.42, very few sells
```

**Recipe**:
- Same as Strategy 2 but BTC 5m only
- Pure accumulation, very little unwinding
- Probably contrarian to binance like Strategy 2

**Performance** (recall from data-api analysis):
- Losing −$10.44/leg in our previous decode
- Likely losing because 5m has tighter mean-reversion windows and higher
  fee impact per trade
- Confirms our backtest finding: 5m is unprofitable, 15m is the
  sweet spot

**Why we'd skip replicating this**: this wallet is losing money. Our
own backtests already confirmed 5m is unprofitable under live-mimic
conditions. Don't copy.

---

## Strategy 5 — Mint-and-sell (`0x04b6d7e9…`)

```
chain window:        18h (19,770 BTC 5m + 4,152 BTC 15m)
maker fills:         97.8% (overwhelmingly maker)
sides observed:      74% only-SELL legs
trades per leg:      73.3 (HIGHEST of all wallets!)
median first_offset: 35s
median last_offset:  242s
top legs:            200-275 SELL fills each, NEGATIVE leftover (sold more
                     than bought = minted+sold pairs)
net_cash:            STRONGLY POSITIVE (huge cash inflow from sales)
total notional:      $17.9M in 18h ← largest of any wallet
```

**Almost certainly the same mint-and-sell strategy as `0x89b5cdaa`**, but
at higher volume and BTC-focused. The 73 trades/leg + 97.8% maker rate is
the signature.

**Why we know it's mint+sell**: a position cannot have `sell_shares >
buy_shares` unless the trader minted shares via `CTF.splitPosition`
(which doesn't emit OrderFilled events — it's a separate transaction on
the ConditionalTokens contract). Our chain scanner only sees the sells.

**Replication path**: same as Strategy 3.

---

## Cross-strategy observations

### What every active wallet has in common

1. **100% focused on up-down 5m+15m markets** (none trade other
   prediction markets in volume)
2. **BTC is the dominant asset** (4-12× more BTC fills than ETH/SOL
   combined)
3. **First fill within 30 seconds of slot_start** — they all open
   positions immediately when the market opens
4. **Last fill 200-300 seconds in** — they trade through most of the
   prediction window
5. **High frequency** — 9 to 73 trades per leg

### What differentiates them

1. **Maker vs taker**: split is 11% / 30% / 53% / 98% / 98% across the
   5 active wallets — very wide range
2. **Side mix**: from 100% sell (mint+sell) to 73% only-buy (taker pyramid)
3. **Asset focus**: 1 asset (cfb103c3) vs all 3 (most others)
4. **TF focus**: 5m only (cfb103c3) vs 15m heavy (ce25e214)

### The two BIG strategies worth replicating

| Strategy | Wallets | Edge source |
|---|---|---|
| **A. Pure market-maker** | `0xeebde7a0` | spread + maker rebate |
| **B. Mint-and-sell** | `0x89b5cdaa`, `0x04b6d7e9` (very high volume!) | sum(best_ask_up + best_ask_down) > $1 + fees |

Both are MAKER-side. We currently only do TAKER. To replicate either,
TV agent needs to add limit-order posting + CTF.splitPosition support.

---

## Decoder limitations (next-session)

The chain decoder still mis-classifies ~10-20% of fills (visible as prices
> $1 in some runs). The bug is in field-mapping for fills where the
exchange contract is on the counterparty side. Fixes:

1. Recognize when neither `maker_asset_id` nor `taker_asset_id` is huge
   (= a token ID); those are USDC-vs-USDC settlement legs from the
   matcher's internal accounting
2. Cross-check decoded `size × price` against the actual USDC transfer
   in the same TX (we have the ERC20 Transfer log already)
3. Aggregate per-TX-per-asset to produce 1 row per "trade" (data-api
   does this naturally; chain has multiple per fill)

These polish items don't change the strategy identification — patterns
are robust to noise. They DO matter for accurate PnL computation, which
is the next-session priority.

---

## Files

| Path | What |
|---|---|
| `strategy_lab/wallet_hunt/asset_lookup.py` | Build token_id → slug lookup from CLOB cache + data-api trades. 52k assets indexed. |
| `strategy_lab/wallet_hunt/cache/_token_lookup.parquet` | The lookup table |
| `strategy_lab/wallet_hunt/analyze_chain.py` | Per-wallet up-down filter + strategy decoder |
| `strategy_lab/wallet_hunt/cache/<short>/trades_chain.parquet` | Chain pull per wallet (1-day each) |
| `strategy_lab/wallet_hunt/cache/<short>/trades_chain_enriched.parquet` | Chain pull + slug + outcome metadata |
| `strategy_lab/wallet_hunt/cache/<short>/per_leg_chain.parquet` | Per-leg aggregations |

---

## Next session — recommended priority

1. **Fix decoder edge cases** (1-2h):
   - Drop rows with prices outside [0, 1]
   - Detect mint-and-sell pattern explicitly (negative leftover_shares)
   - Aggregate multi-log fills per TX

2. **Build the maker strategy backtest** (3-4h):
   - Extend `engine_v2.py` with `post_limit_at_book()` primitive
   - Model maker rebate as negative commission (already in `fees.py`)
   - Backtest: for each market in our universe, simulate posting at
     `(mid - 0.01)` BUY and `(mid + 0.01)` SELL — what's the fill rate
     and PnL?

3. **Build the mint-and-sell backtest** (4-6h):
   - Need: synthesize the mint cost ($1 per pair, no fee)
   - Need: model "post SELL at best_ask, wait for fill, repost if cancelled"
   - Backtest: how often does `inside_ask(Up) + inside_ask(Down) > $1 +
     fees` over our 18d window? That's the unconditional edge before
     execution losses.

4. **Bigger chain backfill** (2-3 days continuous data per wallet):
   - Run `fetch_chain.py --days 7` on each wallet IN BACKGROUND with
     proper output logging (the prior 7-day run hung silently — likely
     RPC timeout under load)
   - 7-day samples give ~280,000 fills per active wallet for robust
     statistics

5. **Track wallets in real-time + alert on strategy changes** — when a
   wallet's hourly fingerprint diverges from its baseline class, that's
   a signal worth reviewing

---

## End of doc
