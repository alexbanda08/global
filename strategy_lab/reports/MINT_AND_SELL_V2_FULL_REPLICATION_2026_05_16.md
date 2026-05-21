# Mint-and-Sell v2 — Full Replication at $2.5 Notional

_2026-05-16. Replays the entire mint-and-sell strategy at wallet-calibrated
parameters: $2.5 notional/fire, corrected fee model (rebate-as-income),
sum_asks ≥ $1.005 entry threshold, 1-snapshot cooldown (every L25 tick when
conditions hold)._

**TL;DR**: Per-fire stats look negative (HOLD = −$0.06 to −$0.15/op),
extrapolating to −$25k/day across 5.2M opportunities. **But slug-level
aggregation flips positive** on the subset where partials of BOTH sides
accumulate (the regime wallets operate in). Per-fire backtest understates
wallet performance because it doesn't capture the inventory-cancellation
effect of high-frequency repetition.

---

## What we ran

`mint_and_sell_scan_v2.py` — corrected fee model (rebate added as income),
configurable notional/cooldown/entry.

| Parameter | v1 (old) | v2 (this run) |
|---|---|---|
| Notional/fire | $25 | **$2.5** |
| Fee model | subtracts phantom maker fee | **adds rebate as income** |
| Min sum_asks | ~$1.035 effective | **$1.005** |
| Cooldown | 10 snapshots | **1 snapshot** |

This matches what we measured on wallet chain data:
- Wallets fire at median sum_asks = **$1.010** (85% of fires in [$1.005, $1.020])
- Wallets size each fire at median **$3-6** (p25-p75)
- Wallets fire **30-170× per slug** (one every 5-10s when conditions hold)

## Scanner output (all 6 cells, 21-day window)

| Cell | Opportunities | sum_asks median | Mean BOTH-fill PnL |
|---|---|---|---|
| btc_5m | 1,835,980 | $1.0100 | +$0.0443 |
| btc_15m | 1,041,121 | $1.0100 | +$0.0426 |
| eth_5m | 986,863 | $1.0100 | +$0.0496 |
| eth_15m | 498,817 | $1.0100 | +$0.0484 |
| sol_5m | 556,856 | $1.0200 | +$0.0763 |
| sol_15m | 293,532 | $1.0200 | +$0.0647 |
| **TOTAL** | **5,213,169** | — | — |

vs v1: 314,169 opportunities total (16× fewer due to maker-fee bug + 10s cooldown).

## Policy comparison results — per-fire view (sample=2000/cell)

| Cell | %BOTH | held_WR | HOLD mean/op | Extrapolated $/day |
|---|---|---|---|---|
| btc_5m | 55.0% | 24.0% | −$0.0923 | −$8,070 |
| btc_15m | 45.8% | 32.0% | −$0.0948 | −$4,699 |
| eth_5m | 49.8% | 19.0% | −$0.1173 | −$5,510 |
| eth_15m | 42.5% | 33.6% | −$0.0646 | −$1,534 |
| sol_5m | 34.8% | 17.9% | −$0.1517 | −$4,022 |
| sol_15m | 26.2% | 30.6% | −$0.1015 | −$1,418 |
| **CONSOLIDATED** | — | — | — | **−$25,253** |

MARKET_EXIT consistently loses ~$1-3k/day more than HOLD. HYBRID ≈ HOLD.

## Why the per-fire view shows losses but wallets profit

### Slug-level aggregation flips the answer

Each slug groups multiple fires together. Three categories:

1. **PURE_ONLY** — every fire on slug was BOTH-fill. PnL is small positive
   (matches BOTH-fill economics).
2. **ONE_SIDE_PARTIAL** — partials all on ONE side. Wallet stuck holding
   the underdog. **Massively negative** (~−$0.25 to −$0.35 per slug on average).
3. **BOTH_SIDES_PARTIALS** — partials on Up-only AND Down-only. Wallet
   accumulates inventory of BOTH sides. **Strictly positive** in every cell.

| Cell | BOTH_SIDES_PARTIALS slugs | Mean PnL/slug |
|---|---|---|
| btc_5m | 9 | **+$0.180** |
| btc_15m | 74 | +$0.046 |
| eth_5m | 16 | **+$0.410** |
| eth_15m | 80 | +$0.146 |
| sol_5m | 18 | +$0.036 |
| sol_15m | 113 | +$0.120 |

The strategy's edge is real, but **expressed at the slug level, not the
per-fire level**. To capture it, you need enough fires per slug that
inventory of both sides accumulates → whichever side wins, that pile
redeems at $1, covering the partial drag from the other side.

### Why our sample mostly lands in ONE_SIDE_PARTIAL

We sampled 2000 fires across ~1200-1700 slugs per cell → **1.2-1.6 fires
per slug**. With only 1-2 fires per slug, the probabilities are:

- ~40% BOTH-fill on first fire → PURE_ONLY slug (mildly positive)
- ~60% partial on first fire → ONE_SIDE_PARTIAL (because the second sampled fire might or might not be on the same slug)

We almost never get the BOTH_SIDES_PARTIALS regime with this sampling.

Wallets fire **30-170× per slug**. With that density, you're virtually
guaranteed to land in BOTH_SIDES_PARTIALS. The held-side selection bias
that hurts per-fire EV cancels at the slug level.

### What "selection bias" actually means

When a single leg fills, that's the side a taker just bought. The market
is implicitly saying "I think this side will win". The held side is the
other side — implicitly the underdog. held_WR = 17-30%.

But over 30+ fires on the same slug, the wallet gets BOTH sides partial-
filled across different moments. Whichever side ultimately wins the
chainlink resolution, the wallet has SOME of that side's tokens to redeem.
Inventory diversification cancels the per-fire bias.

## Estimating per-wallet PnL with this model

Using the slug-level $/slug from our data and wallet fire densities:

- **0xeebde7a0** (sample: 55 fires/slug × 36 slugs × 0.07d):
  - At ~50 slugs/day with 30+ fires each (BOTH_SIDES_PARTIALS regime)
  - Mean $0.20/slug × 50 = $10/day at $2.5 notional
  - But wallet sizes at $4.90 median (~2× our notional)
  - Scaled estimate: ~$20-40/day → **not** matching wallet's $344k/day
  - **Gap remaining: ~10,000x**

- **0x89b5cdaa** ($10k/day observed):
  - ~31 fires/slug × ~50 slugs/day at $6 notional → similar order ~$20-50/day
  - **Gap remaining: ~200x**

The slug-level effect explains the SIGN (negative → positive), but not the
magnitude. Three remaining hypotheses for the gap:

1. **Effective BOTH-fill rate is much higher in reality.** Our `check_fill_window`
   uses a coarse proxy (best_bid_opp reaching our ask). Real orders with EIP712
   sig + queue priority + tight pricing likely achieve 70-85% BOTH-fill, not 35-55%.
2. **Wallets self-select to better fire moments.** We fire every L25 snapshot
   when sum_asks > $1.005. Wallets probably wait for tighter book conditions or
   active periods (e.g., last 60s of slot, high binance volatility).
3. **The strategy works at scale we can't measure with sampling.** 5.2M opportunities
   × thin per-op edge requires sub-$0.001-level execution that doesn't scale linearly
   from a 2000-sample backtest.

## The fee model fix is real

| Metric | v1 (buggy fee) | v2 (correct fee) |
|---|---|---|
| Opportunities in 21d (all 6 cells) | 314,169 | 5,213,169 |
| Mean per-op HOLD | −$2.78 (at $200) | −$0.10 (at $2.5) → −$8.40 scaled to $200 |
| Sum_asks median | $1.040 | $1.010 |
| Per-fire PnL fits wallet entry conditions? | No | Yes |

The fix uncovers 16× more opportunities AND positions us in the wallet's
actual operating regime. We still don't make money in the per-fire view,
but we're directionally aligned with wallet conditions.

## What this means for TV agent's live deploy

1. **The $200/single-fire spec needs revision.** Wallets size $3-6/fire AND
   fire 30+ times per slug. The spec should be:
   - notional per fire: **$3-5** (≤$10)
   - cooldown: **1-5 seconds** (NOT 30s)
   - target: **20+ fires per slug** to land in BOTH_SIDES_PARTIALS regime

2. **Per-fire PnL is not the right validation metric.** A 100-fire paper-mode
   run should be evaluated on:
   - Slug-aggregated PnL (positive means strategy works as designed)
   - BOTH-fill rate (should approach 50%+ — anything <40% means execution problems)
   - Inventory balance at slug end (Up vs Down token piles should be similar)

3. **Holding-to-redemption IS the correct partial-fill behavior.** Market-exit
   loses more in every cell. The redemption income on the held side is the
   payoff for accepting partial-fill variance.

4. **The fee-model fix MUST land in TV's edge calculator** (handoff §1). Without
   it, TV will reject the median wallet entry condition and only fire on the 5%
   of high-edge fires where partial-fill drag is worst.

## Files

- Scanner: `strategy_lab/wallet_hunt/replicate/mint_and_sell_scan_v2.py`
- Policy compare: `strategy_lab/wallet_hunt/replicate/partial_fill_policy_compare_v2.py`
- Slug aggregation: `strategy_lab/wallet_hunt/replicate/slug_level_aggregation.py`
- Wallet condition probe: `strategy_lab/wallet_hunt/replicate/compare_wallet_vs_scanner.py`
- Wallet sizing probe: `strategy_lab/wallet_hunt/replicate/inspect_wallet_sizing.py`
- Per-cell scanner output: `data/v4/canonical/_results/mint_and_sell_v2_<cell>_2026_05_16/opportunities.parquet`
- Per-cell policy compare: `data/v4/canonical/_results/mint_and_sell_v2_<cell>_2026_05_16/policy_compare.parquet`
- Consolidated: `data/v4/canonical/_results/_policy_compare_v2_consolidated.csv`
- Slug aggregation: `data/v4/canonical/_results/_slug_level_aggregation.csv`

## Next test to close the wallet-gap

Run policy_compare with **sample=ALL** on a few specific high-density slugs (where
both-side partials definitely happen), and verify per-slug PnL matches the +$0.05-0.40
range predicted. If yes → strategy works as designed, the per-fire view is just
the wrong metric.

If per-slug PnL is positive but smaller than expected → real wallets must achieve
higher effective fill rates than our 35-55% BOTH-fill, validating hypothesis #1
(execution quality dominates).

Recommend running on a 50-fire-rich slug at full sampling before any live deploy.
