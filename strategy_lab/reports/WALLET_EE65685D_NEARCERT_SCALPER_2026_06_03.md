# Wallet decode — 0xee65685d (near-certain up-down scalper) — 2026-06-03

`0xee65685de42f8de9a03b4c53ee77d56a20d2cfc9`. The most promising wallet decoded — runs an EXECUTION edge we
might actually be able to replicate.

## Headline (lb-api truth)
| metric | value |
|---|---|
| lifetime profit | **+$177,037** |
| 30d / 7d | **+$27,658 / +$27,658** (currently very active) |
| **lifetime volume** | **$33,924,790** (~0.52% margin) |
| 30d volume | $2,671,868 |
| activity | TRADE 3500 + REDEEM 3500 (both **capped** → feed = recent slice only) + MAKER_REBATE 54 |
| feed slice | 2026-04-06 → 2026-06-03 |

⚠️ Per-market $ from the tape is truncation garbage (buys/redeems mismatched at the 3500 cap). Anchor on lb-api.

## Strategy = high-freq "buy the near-certain favorite late, hold to resolution"
- **100% crypto up-down**, all BUY, **hold-to-resolution** (0 sells, 3500 redeems). Up 1809 / Down 1691 → no
  directional bias. Multi-asset: btc 1714 / eth 648 / xrp 379 / sol 318 / doge 199 / bnb 144. tf: 5m 2882 /
  15m 494 / 4h 26.
- **Bimodal entry — two sub-strategies:**
  | entry price | fills | $ notional | role |
  |---|--:|--:|---|
  | ≤2¢ | 1383 | $3.5k | longshot lottery tickets ($0.6 each) |
  | 2–5¢ | 980 | $0.9k | longshot tickets |
  | 20–50¢ | 374 | $9.5k | occasional mid |
  | **≥98¢** | **652** | **$133.8k (90% of capital)** | **the money-maker** |
- **The edge:** buy the **near-certain side at 98–100¢ late in the window**, when the outcome is nearly
  decided but the price hasn't fully converged to 1.00 → win the last 1–2¢. High volume × tiny edge = $177k.
- Mostly **taker** (rebate on only 1.5% of fills) — NOT a maker. Only 12% of markets have both sides → not arb.

## Why this is different from every prior wallet
1. **It's an EXECUTION edge** (grab the 98¢ ask before convergence), the class our strategy-map says the
   profitable wallets use — but unlike maker-queue/relay wallets, **this one we can attempt**: it's a taker
   hitting visible asks, and we have fast Polymarket execution + the Ireland VPS.
2. It empirically harvests the **favorite-longshot bias** the deep-research just flagged (favorites
   underpriced) — concrete proof the bias is tradeable on crypto up-down.
3. It's the **BUY-side mirror of our EXIT-SCALP** edge (both monetize convergence).

## The fee math (why it's razor-thin and needs scale + speed)
Polymarket winner-only fee at p=0.98: win pnl = qty·(1−0.98)·(1−0.07·0.98) = qty·0.0186; loss = −qty·0.98.
Break-even WR = 0.98 / (0.98+0.0186) = **98.1%**. So buying at 0.98 only profits if realized WR > 98.1% — which
requires (a) buying only when the favorite is genuinely ~99%+ (late, clearly winning), and (b) grabbing the
ask before it converges. That's an execution race; the wallet wins it at $34M scale.

## ⇒ TESTABLE & POTENTIALLY DEPLOYABLE (the action item)
Hypothesis: **"buy the up/down token when its L25 price ≥ θ (≈0.97–0.99) with < T seconds remaining and the
underlying clearly past strike, hold to resolution."** Backtest on our data:
- L25 books (native 10Hz) for the near-certain ask availability + depth at the moment.
- binance 1s for "clearly winning" (spot vs strike with little time left).
- chainlink resolutions for outcome.
- engine_v2 with the 0.07 winner-only fee.
Measure: realized WR at each entry-price/time-left bucket, net $/trade after fee, fill availability (is there
enough 98¢ ask depth to size?), and capacity. If WR > 98.1% net-positive in a real bucket → this is a live
candidate (we have the execution infra). KEY RISK: the backtest fill model is optimistic on grabbing the
98¢ ask (our recurring caveat) — validate ask depth/latency carefully.

## Risk model: NAKED — no stop-loss, no hedge (verified)
0 sells ever → never cuts a loser. The 70 both-sided markets are NOT defensive hedges: second-leg buys are
mostly cheap (median 6¢ — the longshot-ticket substrategy) or adds to the already-winning 0.99 side; only a
few are ~0.49+0.49 sub-$1 straddle locks. When a 98¢ near-cert reverses (~1% tail) it **eats the full
−0.98 loss**. Survives on ~99% WR × volume. (Selling a collapsing near-cert token mid-reversal gets an awful
fill — likely why it doesn't even try.)

## ⛔ BACKTEST VERDICT — the rule does NOT replicate (it loses)
Built `backtest_nearcert.py`: buy the up/down token when its L25 ask ≥ θ (book-walk a $50 fill), hold to
resolution, real costs (winner-only `0.07·p·(1−p)`/share + **$0.01 flat tx/trade**), naked. Swept θ ∈
{0.95–0.99} × time-left cap {600..20s}, native-10Hz L25.

| cell | sample | WR @θ0.98 | breakeven WR | $/trade |
|---|--:|--:|--:|--:|
| BTC 15m | 543/6d | 96.8–99.0% | 99.0% | −$0.17 to −$0.66 |
| BTC 5m | 1640/6d | 98.0% | 99.0% | −$0.75 |
| SOL 15m | 543/6d | 98.8% | 99.0% | −$0.16 (≈BE) |
| ETH 15m | 406/**6d** | **100.0%** | 98.8% | **+$0.58** ← regime luck |
| **ETH 15m** | 2488/**30d** | **96.7%** | 99.0% | **−$1.47** ← OOS kills it |

**Realized WR is consistently BELOW the entry price (≈breakeven WR) in every cell with enough sample.** The
market prices the near-cert favorite **fairly-to-rich**; the ~3% reversal isn't covered by the 1–2¢ win + tx.
The ETH-15m "+$0.58" was a 6-day window with zero reversals — over 30 days it's −$1.47/tr (−$2.6k).
**Favorite-longshot bias does NOT show here.** The simple "buy near-cert favorite, hold" rule is a LOSER.

⇒ **The wallet's +$177k is NOT a copyable rule.** It must come from **fill-quality / ask-selection** (picking
off specific underpriced asks at sub-second speed — buying the 0.97 ask when true prob is 0.99, which our
"buy any ask ≥θ" model averaging 0.989 cannot capture), maker rebates, the longshot tickets, and/or the
xrp/doge/bnb/4h markets we can't backtest. Same lesson as every profitable wallet: **the edge is EXECUTION /
fill-selection, not a liftable signal.** A stop wouldn't help — the base rule is already net-negative and the
losses are un-stoppable full reversals.

## Registry
`0xee65685d` — kept as WATCH (intel: real $34M-vol execution wallet) but **NOT** a deployable rule for us.

## Artifacts
- `strategy_lab/wallet_hunt/backtest_nearcert.py` (the backtest), `decode_ee65685d.py`, `cache/_ee65_per_market.csv`.

## Artifacts
- `strategy_lab/wallet_hunt/decode_ee65685d.py`, `cache/_ee65_per_market.csv`.
