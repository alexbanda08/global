# A1 Maker-on-Both-Sides — Results

**Date:** 2026-04-29
**Status:** Complete. **Verdict: deeply unprofitable due to adverse selection.** Best cell ROI -5.4%.

---

## Method

Quote a maker BUY on BOTH YES and NO at start of each market window:
```
yes_quote = yes_bid_0 + tick      (skip if >= ask, i.e. spread too tight)
no_quote  = no_bid_0  + tick

For each subsequent 10s bucket:
  yes_filled if any later yes_ask <= yes_quote
  no_filled  if any later no_ask  <= no_quote

At slot_end:
  yes_pnl = (1 if outcome=Up else 0 - yes_quote) × ($25 / yes_quote)
  no_pnl  = (1 if outcome=Down else 0 - no_quote) × ($25 / no_quote)
```

Sweep tick ∈ {0.01, 0.02}. Aggregate per (asset, tf) and fill-pattern bucket
{none, yes_only, no_only, both}.

---

## Key result

| Tick | Asset | TF | n_fired | fire % | fill_none | one_side | both | ROI % | hit % (fired) |
|---|---|---|---|---|---|---|---|---|---|
| 0.01 | ETH | 15m | 149 | 28.3 | 378 | 23 | 126 | -6.94 | 39.6 |
| 0.01 | ALL | ALL | 2,108 | 29.6 | 5,018 | 558 | 1,550 | **-14.19** | 32.8 |
| 0.02 | ETH | 15m | 55 | 10.4 | 472 | 8 | 47 | -5.40 | 40.0 |
| 0.02 | ALL | ALL | 945 | 13.3 | 6,181 | 265 | 680 | -15.59 | 29.2 |

Every cell is negative. Best (least bad): ETH 15m at tick=0.02, ROI -5.4%.

---

## What's actually happening — adverse selection

Decompose by fill pattern (across all 7,126 markets, tick=0.01):

| Pattern | n | mean PnL | total PnL |
|---|---|---|---|
| none (no fills) | 5,018 | $0.00 | $0 |
| **both sides filled** | **2,230** | **+$0.28** | **+$619** |
| one side only | 4,896 | (very negative) | ~ -$13,594 |

When both sides fill we MAKE money (+$0.28/market on $50 capital = +0.56% per market). The price rebounded enough for both quotes to be hit during the window.

When only ONE side fills we LOSE big. The price moved AWAY from one side before hitting our quote, and we only got the side that was about to lose. Hit rate when fired = 32% — well below random.

This is textbook **adverse selection**: market-makers get filled on the side that's about to be wrong. Without queue priority or skill at quote sizing, we lose money quoting against retail flow.

---

## Could "only fire on both fills" work?

If we could magically restrict to both-fill markets, ROI would be +0.55% (+$619 / $111.5k cost). Tiny but positive.

Operationally infeasible: the second fill happens later in the window. To "only honor when both fill" we'd need:
1. Place YES quote at t=0.
2. Wait for first fill (e.g. YES filled at t=30s).
3. Now committed long YES.
4. Place NO quote at t=30s. Hope it fills before slot_end.
5. If NO doesn't fill: stuck with one-sided position → we became a directional taker.

The gating cost of waiting for both fills converts our maker quotes into stale market-takers. The +0.55% expected edge evaporates.

A real solution would need:
- Quote on whichever side has the wider spread (1-leg directional)
- Cancel the quote if not filled within 60s
- Repeat across the window

That's a different paradigm — passive maker-then-taker hybrid. Future work.

---

## Caveats / approximations

1. **Fill detection is conservative**: `ask <= quote` at any 10s bucket. Real fills happen between snapshots — would slightly increase fill rate, slightly worsen adverse selection.
2. **No queue position**: assumes FIFO at our level. If many makers cluster at `bid_0 + 0.01`, our chance of being filled drops.
3. **Fees**: not modeled. Polymarket maker fees were 0% historically — verify before live.
4. **Crossing spread**: skip-quote if our quote ≥ best ask. Reduces fire rate but is realistic (Polymarket REST may reject crossing limits).

---

## Decision

**Don't ship.** Maker-on-both-sides has negative EV at every quoted leverage on this 7-day sample. Adverse selection is the dominant cost.

Could be revisited as part of a hybrid (maker-then-taker) strategy with active quote management — but that's a substantial new design, not a +1-day backtest.

Moving to A2 (cross-asset lead-lag) next.
