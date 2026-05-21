# Mint-and-Sell Engine — Strategy Spec

_Target reader: TV agent. This describes what the strategy IS, why it works,
and what primitives the engine needs. Implementation architecture (file
layout, libraries, config format, observability) is TV agent's call._

---

## 1. The strategy in one paragraph

On Polymarket's binary up-down markets (BTC/ETH/SOL × 5m/15m), the sum of
the best asks on the two outcomes occasionally exceeds $1.00. This is a
microstructure mispricing: directional takers checking only one side don't
notice the opposite side has also drifted up. Anyone who can simultaneously
**mint a Up+Down pair from $1 USDC** and **post limit SELLs at both
best_asks** captures the surplus — risk-free if both fills go through,
mildly directional if only one does. We have decoded this trigger across
three wallets making **$10k–$344k/day** running this exact pattern.

---

## 2. The trigger (validated on 5,500 actual fires across 3 wallets)

```
On every L25 book update on each active up-down market:
  if best_ask(Up) + best_ask(Down) > $1.00:
     fire
```

That's it. **100% of fires** across all three profitable wallets satisfy
this condition. Median sum_asks at fire = **$1.010**. P90 = $1.020.

No directional signal. No momentum component. No oracle dependency. No
specific timing in the market lifecycle (offset from slot_start spans
40s–800s with no clustering). Pure book-state arbitrage.

### Sensible filters (not the trigger, just protective)
- Skip when spread per side > 2¢ (book is thin, fills uncertain)
- Skip when visible top-of-book size < ~5 shares (no taker depth to fill us)
- Skip when sum_asks > $1.05 (the "stale book" zone — quotes get pulled
  before takers arrive; observed fill rate drops from 41% to 17%)

### Fire frequency observed in our 21-day backtest
- BTC 5m: ~407 ops/day at $25 notional
- ETH 5m: ~383 ops/day
- SOL 5m: ~488 ops/day
- 15m markets: ~160-180 ops/day each
- Aggregate across 6 cells: **~1,800 ops/day**

---

## 3. The fire sequence (what the engine does at each fire)

```
1. CTF.splitPosition(condition_id, amount=N) on-chain
     pays N USDC → receives N Up tokens + N Down tokens

2. EIP712-sign and POST two limit SELL orders to Polymarket CLOB
     SELL N×Up   at observed best_ask(Up)
     SELL N×Down at observed best_ask(Down)

3. Wait up to ~60 seconds for fills (impatient takers crossing our quotes)

4. Per side, on fill: receive USDC = filled_shares × posted_price
                    (we're maker → receive 20% rebate on the Poly fee curve)

5. After 60s:
     both filled  → done; net profit = (sum_filled_prices - $1) × shares + rebates
     one filled   → hold remaining inventory until market resolution
     neither      → cancel both orders + CTF.mergePositions(N) to recover N USDC
```

The 60s wait window, the cooldown between fires on the same market
(~10s in observed behavior), and the inventory recovery path are operational
defaults — TV agent should tune them based on observed live fill rates.

---

## 4. Why the edge survives fees (this is the load-bearing math)

Polymarket's fee curve (from `strategy_lab/fees.py`):

```
fee_per_share = fee_rate × p × (1 - p)
fee_rate = 0.07 for crypto markets (BTC/ETH/SOL)
maker_rebate = fee_per_share × 0.20    (20% rebated to the resting-order side)
```

**The mint-and-sell operator is always the MAKER, never the taker.** Their
orders sit in the book. The directional taker who hits them pays the
standard taker fee; we collect the rebate.

### Per-opportunity math at $200 notional, sum_asks = $1.01

```
Mint 200 pairs                            cost:  $200.00
Sell 200 Up at $0.51                      cash: +$102.00
Sell 200 Down at $0.50                    cash: +$100.00
                                          gross: +$2.00
Maker rebate on Up:  200 × 0.20 × 0.07 × 0.51 × 0.49 ≈ +$0.35
Maker rebate on Down: 200 × 0.20 × 0.07 × 0.50 × 0.50 ≈ +$0.35
                                          net:   +$2.70

Probability both sides fill within 60s (measured): 40.8%
                                          EV per opportunity: +$1.10
```

Multiply by ~1,800 opportunities/day across the 6 cells → backtest predicts
**~$14k/day at $200 notional**, which brackets the observed wallets
($10k–$18k/day for two of them; the third does $344k/day at much larger
size).

### Tail risk if only one leg fills

Example: Up filled, Down did NOT.

```
Cash received                              +$102 (from Up sell)
Mint cost                                  -$200
Holding 200 Down tokens, redeems at:
   $1 if Down wins → +$200 → net +$102
   $0 if Down loses → +$0  → net -$98

At ~50% resolution probability for either side, EV ≈ +$2 — the original
edge survives. The single-side fill is a directional bet that's near-zero
EV by itself, but the mint edge nets out.
```

If NEITHER side fills: cancel both orders (free), then `CTF.mergePositions`
burns the held pair and returns $1 per pair in USDC. Lost nothing besides
gas (~$0.005 per merge on Polygon).

---

## 5. What the engine needs to be able to do

Capabilities, not implementation:

| Capability | What it does |
|---|---|
| **Real-time book state** | Read the inside of L25 on each active market with sub-second latency. The 1¢ edge evaporates in seconds when other makers compete. |
| **CTF mint** | Call `ConditionalTokens.splitPosition(USDC, parent=0, condition_id, [0b01, 0b10], amount)` at `0x4d97dcd97ec945f40cf65f87097ace5ea0476045`. |
| **CTF merge (recovery)** | `mergePositions(...)` to convert an unsold Up+Down pair back to USDC when both legs failed to fill. |
| **CTF redeem (settlement)** | `redeemPositions(...)` after market resolves to claim USDC for winning tokens we're still holding. |
| **EIP712 limit-order sign + POST** | Construct a SELL order against Polymarket CTF Exchange (`0x4bFb41d5...`), EIP712-sign, POST to `/order`. |
| **Order cancel** | DELETE order by id on `/order/<id>`. |
| **Own-fill notification** | Know within seconds when our posted SELL fills (so we can reconcile cash + decide on the other leg). |
| **Per-market inventory tracking** | Maintain (Up_balance, Down_balance) per market across the engine's lifetime. Required for the redemption step. |
| **PnL accounting** | Per market and per day: (cash_in − cash_out) + (current_inventory_value), so we can detect drawdowns. |

### Staleness — why this matters more than for most strategies

The edge is 1¢ on a $1 sum. A 1¢ stale book reading flips an apparent
profitable opportunity into an unprofitable one. We learned this with our
momo strategy: Polymarket's REST `/book` endpoint runs **$0.19–0.32 stale**
vs the WS L25 ground truth during high-vol moments
(`MOMO_REST_LAG_VS_MICROSTRUCTURE.md`).

For mint-and-sell that staleness asymmetry would either:
- Make us fire on phantom edges that have already been swept → unfilled
  inventory → recovery cost
- Make us miss real edges because the REST reading shows $0.99 while WS
  shows $1.02 → competitors get the trade

The strategy's edge depends on seeing the current book. WS subscriptions
exist for exactly this reason and are how the profitable wallets operate.
How to integrate them (which library, reconnect behavior, snapshot-after-
reconnect handling) is up to the TV agent.

---

## 6. What the engine should track and protect

These are principles, not exact thresholds — TV agent should pick numbers
that fit their observability and risk tolerance:

- **Capital cap per market**: limit how much mint inventory can sit unfilled
  per market. Recovery via `mergePositions` is always available but should
  not become routine.
- **Aggregate inventory cap**: limit total open USDC tied up across all
  markets, so a temporary fill drought doesn't lock the wallet.
- **Drawdown gates**: if intraday PnL drops below a chosen threshold, pause
  fires and let open positions resolve before resuming.
- **Order-rejection gate**: a sudden spike in CLOB rejections likely means
  signature/nonce issue → pause until diagnosed.
- **Stale-book gate**: if the engine notices book-update lag exceeds some
  threshold (e.g. last update is older than N seconds), pause fires for
  affected markets.
- **Fill-rate monitoring**: if observed joint fill rate stays well below
  ~40% for an extended window, the strategy is bleeding (cancel costs +
  inventory carry). Pause and investigate.

What level of automation around these (auto-pause vs alert-only) is the TV
agent's design choice.

---

## 7. Validating the live engine before scaling

A reasonable progression based on our backtest:

1. **Paper mode**: run the engine against live WS feeds but log decisions
   instead of submitting. Compare what it WOULD have done vs the backtest's
   1,800 ops/day baseline. Sum_asks > $1 should be 100% of would-fires.
2. **Live small**: $25 notional × 1 market for ~24h. Observed fill rate
   should land in the 35–45% range we measured. Realized PnL should track
   the backtest projection within ~15%.
3. **Live broad**: same notional across multiple markets. Watch for
   cross-market correlation in fill rates.
4. **Scale notional**: only after the small live runs validate the engine
   matches the backtest, scale notional toward the $200 level where the
   observed wallets operate.

The backtest is our reference baseline:
- $25 notional × 6 cells = ~$1,800/day realized
- $200 notional × 6 cells = ~$14,000/day realized

If live underperforms backtest by a wide margin, something in the engine
deviates from the strategy specification (most likely culprits: stale book
data, signature issues delaying order posts, or wait-window mis-sized).

---

## 8. What's in scope for this engine

✅ Mint-and-sell on Polymarket BTC/ETH/SOL up-down 5m and 15m markets
✅ Multi-market parallel operation (the profitable wallets cover ~50-100
   active markets at once)

❌ Pure market-making (the `0xeebde7a0` strategy at $344k/day combines mint-
   and-sell with continuous quoting on both bid AND ask — that's a separate
   engine, separate spec)
❌ Other prediction venues (Limitless, Opinion, Kalshi)
❌ Other Polymarket markets (sports, politics, etc.) — sized differently,
   different fee tiers, untested by our backtest

---

## 9. What we've already built (reference implementations in Python)

These are NOT for production use, but TV agent can read them to understand
the math and validate against:

| File | What |
|---|---|
| `strategy_lab/fees.py` | Polymarket fee + maker-rebate curve |
| `strategy_lab/wallet_hunt/replicate/mint_and_sell_scan.py` | Edge scanner over canonical L25 (the trigger logic in Python) |
| `strategy_lab/wallet_hunt/replicate/fill_probability.py` | Measures realized fill rate by replaying book forward from each opportunity |
| `strategy_lab/wallet_hunt/replicate/decode_triggers.py` | Extracts the trigger condition from actual wallet fires |
| `data/v4/canonical/_results/mint_and_sell_*/opportunities.parquet` | 21-day backtest output across all 6 cells |
| `strategy_lab/reports/STRATEGY_DECODED_2026_05_16.md` | The decode of the actual wallet behavior |
| `strategy_lab/reports/MINT_AND_SELL_REPLICATION_2026_05_16.md` | The backtest write-up |

---

## End of spec
