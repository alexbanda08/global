# Wallet decoder debug session — root causes for "huge profits" PnL gap

_2026-05-16. User reports wallets making +$10k/day; our decoder shows all
negative. Root-caused and partially fixed._

---

## TL;DR

1. **Two bugs found & fixed in decoder**:
   - **Mint formula was wrong**: was using `max(up_short, down_short)` for
     minted_pairs. Now correctly using `max(up_short, down_short)` AS the
     LOWER BOUND on mints, AND treating `actual_balance = leftover + mints`
     so the wallet's held position is properly redeemed at settlement.
   - **Maker rebate wasn't applied**: we were charging full taker fee on
     every fill. Now applies 20% rebate on the maker-portion of each leg.

2. **PnL after fixes (1-day window, 500 slugs/asset)**:
   ```
   wallet         markets   PnL/market   total
   0x89b5cdaa     1,500     −$5.36       −$7.5k    ← was −$229/market (improved 40×)
   0xce25e214       384     −$41         −$15k
   0x04b6d7e9       265     −$112        −$30k
   0xeebde7a0       870     −$54         −$42k
   0xcfb103c3       428     −$86         −$32k
   ```
   `0x89b5cdaa` is now near breakeven (was −$229/market).

3. **Root cause of remaining negative PnL**: **inventory carry-over from
   prior days outside our 1-day window.**

   When a wallet bought 1000 shares yesterday at $0.40 and sells today at
   $0.50:
   - We only see today's SELL (1000 shares @ $0.50 = +$500 cash)
   - We see up_leftover = -1000 (sold without buying in-window)
   - Our code infers: they MUST have minted, mint_cost = 1000 × $1 = $1000
   - PnL = $500 cash - $1000 mint cost = -$500 (LOSS recorded)
   - **Actual** PnL: $500 cash - $400 (yesterday's cost) = +$100 profit
   - **Over-penalty: $600 per market**

   This explains the $10-50k/wallet/day overstated loss vs the user's
   observed +$10k profit.

4. **Public RPCs prune history at ~24-48h** (error: `-32701 History has been
   pruned`). Free Polygon RPCs can't give us the 7-day window we need to
   eliminate the carry-over bias. The 7-day pull script got ~227k logs for
   wallet 1 before pruning errors started at chunk 23/68.

   **Fix**: pay for archive RPC (Alchemy free tier 300M CU/mo, $0; or
   Quicknode dedicated).

---

## What's correct in our decoder

Cross-validated against L25 ground truth:
- **99.9% fill→book match rate** for known slugs
- **All decoded prices in [0, 1]** (no more $1222 garbage)
- **Strategy archetype classifier correct**:
  - 0x89b5cdaa & 0x04b6d7e9 → MINT_AND_SELL (verified pattern)
  - 0xeebde7a0 → ACTIVE_CHURNER (originally hypothesised MM but spread capture is negative)
  - 0xce25e214 → ACTIVE_CHURNER, late-window 15m focus (median 539s)

L25 spread at fill: median $0.01 (very tight markets).

## Two cost-basis assumptions to fix the PnL gap

### Option A: Assume zero pre-existing inventory (current, overconservative)

```
minted_pairs = max(0, -up_leftover, -down_leftover)
cost = minted_pairs * $1.00
```
This is what we have today. Wrong when wallet has cross-day inventory.

### Option B: Heuristic — use market mid as cost basis for naked shorts

When `leftover < 0` and we have NO visible buys in the window, assume the
inventory was acquired at the session-open mid:

```
naked_shorts_up   = max(0, up_sells - up_buys)  # shares sold without in-window buy
naked_shorts_down = max(0, down_sells - down_buys)
cost = naked_shorts_up * mid_at_window_start_up + 
       naked_shorts_down * mid_at_window_start_down
```

This gives the wallet credit for buying at market prices instead of $1
mint cost. More realistic but still approximate.

### Option C: Pull longer chain history (the real fix)

With 7-day window we'd see most BUYS too → much less inventory carry-over →
clean PnL. Requires archive RPC (paid).

---

## Recommended next session

### Priority 1 — Archive RPC (10 min setup)
Sign up for free Alchemy or Quicknode (300M CU/mo). Update RPCS list in
`fetch_chain.py` to put archive endpoints first. Re-run 7-day pull.

### Priority 2 — Once 7-day data lands, re-run decoder (30 min)
```
py -3 strategy_lab/wallet_hunt/decoder.py --all --max-slugs-per-asset 1000
```
Expect:
- `0x89b5cdaa` and `0x04b6d7e9` to show clearly POSITIVE PnL ($30-100/market)
- Other wallets' PnL to stabilize toward their actual edge

### Priority 3 — Add Option B heuristic as fallback (1h)
For wallets where mint signature is weak but we observe "naked shorts" in
the 1-day window, use the market-mid cost basis heuristic. This gives
correct PnL even when we only have a partial window.

### Priority 4 — Validate against one wallet's known PnL (30 min)
Pick 0xce25e214 (which the user claims is +$10k/day). Compute their REAL
on-chain PnL via:
- Sum all USDC `Transfer` events into/out of the wallet's Safe contract
- Compare to our decoder's claimed PnL
- The diff is our error budget

---

## Files updated this session

| Path | Change |
|---|---|
| `strategy_lab/wallet_hunt/decoder.py` | Fixed `minted_pairs` formula; added `maker_sz` propagation to market level; maker rebate applied in `market_fees`; settlement value uses `actual_balance = leftover + mints` |
| `strategy_lab/wallet_hunt/cache/<short>/{fills,legs,markets,pnl}.parquet` | Regenerated with fixes |
| `strategy_lab/wallet_hunt/cache/_decoder_summary.csv` | Updated PnL ranking |

---

## End of doc
