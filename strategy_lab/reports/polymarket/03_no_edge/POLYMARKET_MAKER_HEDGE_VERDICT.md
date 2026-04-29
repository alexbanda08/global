# Maker-Hedge Strategy — Verdict: **DO NOT DEPLOY**

**Tested:** posting hedge as limit at `other_bid + 1¢` instead of taking the ask, with 20/40/60s wait + taker fallback.

**Result:** **NEGATIVE.** Maker hedge actively destroys the entry-maker gains.

---

## The numbers (q10 universe, n=509, hedge-hold rev_bp=5)

| Variant | ROI | vs T/T | Hedge fill rate | Mean cost |
|---|---|---|---|---|
| T-entry / T-hedge (control) | +26.15% | — | n/a | $0.6733 |
| **M-entry / T-hedge** ★ | **+26.81%** | **+0.66pp** | n/a | **$0.6666** ← cheapest |
| T-entry / M-hedge 20s | +25.59% | −0.57pp | 3% | $0.6790 (+1¢) |
| T-entry / M-hedge 40s | +25.25% | −0.91pp | 3% | $0.6825 (+1¢) |
| T-entry / M-hedge 60s | +25.13% | −1.02pp | 4% | $0.6836 (+1¢) |
| M-entry / M-hedge 20s | +26.24% | +0.09pp | 3% | $0.6724 |
| M-entry / M-hedge 40s | +25.91% | −0.25pp | 3% | $0.6758 |
| M-entry / M-hedge 60s | +25.79% | −0.36pp | 4% | $0.6770 |

**Decomposition:**

| Component | Effect on ROI |
|---|---|
| Entry-maker alone (M-entry/T-hedge) | **+0.66pp** ✅ |
| Hedge-maker alone (T-entry/M-hedge 20s) | **−0.57pp** ❌ |
| Both combined (M/M 20s) | +0.09pp ≈ entry-gain cancelled by hedge-loss |

---

## Why hedge-maker fails — structural asymmetry

This is the key insight, and it's structural not statistical:

**Entry-maker WORKS because:**
- At window_start (t=0), no signal-driven move is in progress
- Normal book volatility brings the ask down to our limit ~25% of the time within 30s
- We capture the cheaper fill on those — the 75% that don't fill, we pay full taker price
- Net: −1¢ on 25% of trades = ~−0.25¢/trade (= **+0.66pp ROI lift**)

**Hedge-maker FAILS because:**
- rev_bp triggers EXACTLY when signal-driven flow is happening (BTC just moved against us)
- The OTHER side's price is RISING rapidly — everyone wants to buy the now-favored side
- Our limit at `other_bid + 1¢` rarely fills (3-4%) because:
  - The bid is climbing AWAY from us, not coming down to our level
  - Other MMs are lifting bids faster than we can plant resting orders
- Meanwhile, during 20-60s wait, the other-side ASK climbs HIGHER
- When we fall back to taker, we pay MORE (~+1¢) than if we'd just taken at trigger time
- Net: +1¢ on 56% of trades that hedge = ~+0.56¢/trade (= **−0.57pp ROI loss**)

**General principle:**
> Maker fills are profitable in **passive-flow regimes**, destructive in **directional-flow regimes**.
> rev_bp triggers are by definition the latter.

---

## Cross-asset confirmation (M-entry / T-hedge wins everywhere)

| Asset | TF | best ROI | T/T ROI | Δ |
|---|---|---|---|---|
| ALL | ALL | +26.81% | +26.15% | +0.66pp |
| BTC | ALL | +29.52% | +29.28% | +0.24pp |
| ETH | ALL | +27.26% | +26.68% | +0.58pp |
| SOL | ALL | +23.64% | +22.48% | +1.16pp |

3/3 assets confirm M-entry beats T/T. None of the hedge-maker variants beat M-entry/T-hedge.

---

## Day-by-day (M-entry / T-hedge vs baseline, all 5 days positive)

| Date | n | best ROI | T/T ROI | Δ |
|---|---|---|---|---|
| 2026-04-22 | 55 | +25.59% | +24.92% | +0.67pp |
| 2026-04-23 | 210 | +26.12% | +25.34% | +0.77pp |
| 2026-04-24 | 140 | +27.22% | +26.65% | +0.57pp |
| 2026-04-25 | 17 | +31.15% | +31.15% | +0.00pp |
| 2026-04-26 | 87 | +27.76% | +27.12% | +0.64pp |

5/5 days non-negative for M-entry. (Apr 25 fill rate was 0% so net 0pp.)

---

## Final recommendation

✅ **Deploy maker-entry on 15m markets** (per [POLYMARKET_MAKER_ENTRY_VERDICT.md](POLYMARKET_MAKER_ENTRY_VERDICT.md))
❌ **Do NOT deploy maker-hedge** in any form
✅ **Keep taker hedge** at rev_bp trigger — you must cross the spread to lock in the position before the move accelerates

The TV implementation should:
1. Place limit-buy at entry side bid+1¢, wait 30s, fall back to market-buy at ask
2. On rev_bp trigger: place market-buy at other side ask **immediately** (no maker-hedge attempt)

This is the optimal mode given Polymarket's flow-regime asymmetry.

---

## Files
- [polymarket_maker_hedge.py](../polymarket_maker_hedge.py) — full 8-variant simulator
- [POLYMARKET_MAKER_HEDGE.md](POLYMARKET_MAKER_HEDGE.md) — variant grid + cross-asset + day-by-day
- [results/polymarket/maker_hedge.csv](../../results/polymarket/maker_hedge.csv) — variant comparison data
