# S2 Covered-Call Backtest — Results

**Date:** 2026-04-29
**Status:** Complete. **Verdict: no consistent edge in the structure as designed.** ETH 15m q10 the only positive standout (+9% ROI, n=69 — too thin to ship).

---

## Method

For every resolved Polymarket UpDown market (n=8,189), simulate:

```
Long  BTC perp at strike_price, leverage L, notional $25
Short YES on Polymarket  = buy NO at entry_no_ask, $25 notional → shares = $25/no_ask
Hold both legs to slot_end (the binary resolution).

PnL_perp = L × (settle/strike − 1) × notional_perp    (clamped to −$25 if liquidated)
PnL_no   = shares × ((1 − outcome_up) − entry_no_ask)
PnL_total = PnL_perp + PnL_no
```

Liquidation: position wiped if `L × |spot_pct| ≥ 100%`. Approximation — uses settle price as worst case (real intra-window peak is unobserved).

Parameter sweep:
- Leverage: {1, 2, 5, 10, 30, 60}
- Sizing: `matched` (perp notional = $25) | `delta1` (perp notional = $25 × (1−no_ask))
- Filter: all markets | top 10% by `|ret_5m|`
- Stratification: per (asset, timeframe), plus ALL aggregations

Code: `strategy_lab/v2_signals/covered_call_backtest.py`. Output: `results/polymarket/covered_call_backtest.csv`.

---

## Results

### All-asset, all-timeframe, q10 filter — best per leverage

| L | size_mode | n | hit % | ROI % | Sharpe | Max DD | Liq % |
|---|---|---|---|---|---|---|---|
| 1× | matched | 819 | 50.9 | 0.71 | 0.22 | -$715 | 0.0 |
| 1× | delta1 | 819 | 50.9 | **0.95** | 0.22 | -$715 | 0.0 |
| 2× | delta1 | 819 | 50.9 | 0.95 | 0.22 | -$715 | 0.0 |
| 5× | delta1 | 819 | 50.9 | 0.94 | 0.22 | -$714 | 0.0 |
| 10× | delta1 | 819 | 50.9 | 0.91 | 0.21 | -$714 | 0.0 |
| 30× | delta1 | 819 | 50.9 | 0.82 | 0.20 | -$712 | 0.0 |
| 60× | delta1 | 819 | 50.9 | 0.69 | 0.17 | -$715 | 0.1 |

**Leverage adds nothing.** 1× and 60× are within 30 bps. ROI is mediocre at ~1%. Sharpe ~0.22 — flat.

### Top 6 standout cells (cherry-picked by ROI)

| L | size | filter | asset | tf | n | hit % | ROI % | Sharpe |
|---|---|---|---|---|---|---|---|---|
| 1× | delta1 | q10 | **eth** | **15m** | 69 | 56.5 | **+8.78** | 2.04 |
| 2× | delta1 | q10 | eth | 15m | 69 | 56.5 | +8.76 | 2.04 |
| ... | ... | ... | ... | ... | ... | ... | ... | ... |
| 60× | matched | q10 | eth | 15m | 69 | 55.1 | +5.06 | 1.75 |
| 1× | delta1 | q10 | btc | 5m | 206 | 51.9 | +3.56 | 0.82 |

ETH 15m q10 cluster at 8.7-8.8% ROI is real-but-thin (n=69, 7 days). All other (asset, tf) cells are near-zero.

---

## Why no edge

The structure is **delta-neutral by construction** — long perp and short YES point in opposite directions. Net exposure to BTC price is approximately zero, leaving only:

1. **Premium income from the NO leg** = `(1 − no_ask) × shares` if NO wins, `−no_ask × shares` if NO loses. Expected value per share = `(1 − no_ask) × P(down) − no_ask × P(up)`.

2. **Carry on the perp** — basis between perp and spot, funding cost. We didn't model funding; in practice it's a small additional drag.

In equilibrium, `no_ask ≈ 1 − P(up)` because Polymarket pricing is competitive. Expected NO leg PnL ≈ 0. Expected perp PnL ≈ 0. Total expected PnL ≈ 0 × shares. **The covered-call structure has no inherent edge — it's a fairly-priced offset.**

The +0.7-1% ROI we observe is residual: NO is slightly mispriced (`no_ask` averages ~$0.50 with hit rate ~51%, giving the buyer a ~0.5 pp expected edge per market). On 819 markets that compounds to noticeable PnL, but it's tiny per market and easily wiped by spread costs not modeled here.

---

## Where the original covered-call premise broke down

The user's original idea: "long crypto perp + collect premium from short binary, like a real covered call. Use 60x leverage on the perp because we're in 15m markets."

The flaw: a real covered call works because:
- Stock has positive expected return (drift)
- Call premium is over-priced relative to the stock's actual vol (vol-risk premium)

For Polymarket UpDown:
- BTC perp has near-zero expected return on 5/15-min horizons (drift is dominated by noise)
- Binary "premium" is a competitive market price — no consistent over-pricing

So the analogy doesn't transfer. Without a vol-risk premium, the structure doesn't generate.

---

## What WOULD be promising — signal-conditional variant (not built)

The flat result above is the AVERAGE. There's likely meaningful asymmetry conditional on `ret_5m`:

- When `ret_5m > 0` and price just moved UP, retail may be aggressively buying YES → `no_ask` may be discounted (under-priced NO). Buy NO + long perp = long the move + bet against immediate continuation.
- When `ret_5m > 0` and `no_ask > 0.5`: market is BIDDING UP no while spot moved up. Mispriced. Strong buy NO.

A conditional version: only enter when `(no_ask < 1 − P_predicted(up))`, where `P_predicted` comes from realized vol (similar to Signal B in the killed V2 stack). That'd be a *vol-arb-with-perp-cover* — different beast.

Out of scope for S2. Worth revisiting if S1's gap analysis turns up venues for this.

---

## Decision

**Don't deploy the covered-call as a sleeve.** Per-market ROI ~1% is not enough to overcome live-execution friction (spread, fees, slippage we didn't model). The ETH 15m q10 cell (+9% ROI, n=69) is a thin anomaly — would not survive forward-walk.

The recalibrated `sig_ret5m` sniper q10 (no perp leg) remains the deployable winner per `docs/FINDINGS_2026_04_29.md`.

What we learned that matters:
- **Leverage doesn't help** on a delta-neutral structure. Don't bother re-testing 60× on similar ideas — the leg ratios matter, not the leg sizes.
- **Without vol-risk premium, the option-writer analogy fails.** Future structures should target conditional mispricings, not steady-state premium harvesting.

Moving to A1 (maker-on-both-sides spread provision) next, which DOES have an edge thesis (collecting Polymarket's actual bid-ask spread directly).
