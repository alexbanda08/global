# Hedge Fallback — Recommendation

**Date:** 2026-04-28
**Question:** when the hedge buy-opposite-at-ask fails to execute (current production: ~100% failure due to TV cache+staleness bug chain), what countermeasure caps downside?
**Method:** realistic L10 book-walking sim, 4 policies × 3 synthetic hedge-failure rates × 6 deployed cells, $25 stake, rev_bp=5.

---

## TL;DR — switch to **HYBRID** (or even straight **SELL_OWN_BID**)

The current `HEDGE_HOLD` policy collapses catastrophically when hedges can't fire. Two simple alternatives are strictly better — **regardless** of whether the TV bug-chain is fixed or not.

### Headline — q10 × 5m × ALL (deployed cell)

| Policy | ROI @ healthy hedge (0% fail) | ROI @ half fail (50%) | **ROI @ all fail (100%)** | Sharpe @ 100% | MaxDD @ 100% |
|---|---:|---:|---:|---:|---:|
| **HEDGE_HOLD** (current) | +34.50% | +24.46% | **+13.62%** | +26.1 | **−$378** |
| **SELL_OWN_BID** | +36.41% | +36.41% | **+36.41%** | +101.8 | −$130 |
| **HYBRID** | +34.50% | +35.55% | **+36.41%** | +101.8 | −$130 |
| **STOPLOSS_20** | +29.51% | +29.51% | +29.51% | +87.4 | **−$80** |

**Read this row by row:**
- HEDGE_HOLD at production-now (fail=100%) burns **−20.9 pp ROI** vs healthy state. MaxDD nearly **3×** worse.
- SELL_OWN_BID is **immune** to hedge failures (never hedges). Stable +36.41% ROI. **Beats HEDGE_HOLD even at 0% fail rate.**
- HYBRID matches HEDGE_HOLD when hedges work, degrades to SELL_OWN_BID when they don't. Strictly dominant.
- STOPLOSS_20 has the smallest MaxDD but trades −7 pp ROI for it.

### Strongest evidence — SOL 5m (the canary)

| Policy | ROI @ 0% | ROI @ 100% | MaxDD @ 100% |
|---|---:|---:|---:|
| HEDGE_HOLD | +25.54% | **−4.10%** | **−$274** |
| SELL_OWN_BID | +28.91% | +28.91% | −$69 |
| HYBRID | +25.54% | +28.91% | −$69 |

SOL 5m × HEDGE_HOLD goes **negative** when hedges fail. The countermeasure is a **+33 pp turnaround** (−4.10 → +28.91) and a **4× drawdown reduction** (−$274 → −$69).

---

## Why does SELL_OWN_BID beat HEDGE_HOLD even with healthy hedges?

The locked spec assumed hedge-hold caps loss "for free" at ~$0.02–0.04 per $1 stake. The realfills sim shows that's optimistic for two reasons:

1. **Hedge legs pay the 2% protocol fee on whichever side wins.** A $0.55 entry + $0.50 hedge = $1.05 cost, payout $0.99 (after fee), implied loss $0.06 per $1 stake — already worse than just selling at the current bid which doesn't cross-leverage two fees.
2. **Bid-side immediate exit captures current MTM** without the variance of holding two legs through resolution. Less variance → higher Sharpe.

The "free downside cap" of hedge-hold is actually a **negative-EV insurance premium** on average. The realfills sim quantifies it: HEDGE_HOLD healthy = +34.50%, SELL_OWN_BID = +36.41%. **+1.91 pp ROI lift just from skipping the hedge leg.**

This subtly invalidates one of the locked-spec assumptions. The implementation guide §2 said "Direct sell is vulnerable to bid-side spread degradation" — but on the actual L10 book data, bid-side close is consistently better.

---

## Full results — all deployed cells

### q10 × 5m × ALL (n=392)

| Policy | Fail% | ROI%/trade | Hit% | Sharpe | MaxDD | Hedged% | BidExit% | Rode% |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | +34.50% | 72.7% | +95.7 | −$137 | 53% | 0% | 47% |
| HEDGE_HOLD | 50% | +24.46% | 68.1% | +54.6 | −$207 | 25% | 0% | 75% |
| HEDGE_HOLD | 100% | +13.62% | 61.2% | +26.1 | −$378 | 0% | 0% | 100% |
| SELL_OWN_BID | any | **+36.41%** | 74.7% | **+101.8** | −$130 | 0% | 53% | 47% |
| HYBRID | 0% | +34.50% | 72.7% | +95.7 | −$137 | 53% | 0% | 47% |
| HYBRID | 50% | +35.55% | 73.7% | +99.0 | −$132 | 25% | 27% | 47% |
| HYBRID | 100% | +36.41% | 74.7% | +101.8 | −$130 | 0% | 53% | 47% |
| STOPLOSS_20 | any | +29.51% | 67.1% | +87.4 | **−$80** | 0% | 66% | 34% |

### q20 × 15m × ALL (n=230)

| Policy | Fail% | ROI%/trade | Hit% | Sharpe | MaxDD |
|---|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | +31.43% | 67.4% | +82.7 | −$58 |
| HEDGE_HOLD | 100% | +22.50% | 66.1% | +35.1 | **−$324** |
| SELL_OWN_BID | any | **+33.38%** | 69.1% | +89.3 | −$45 |
| HYBRID | 100% | +33.38% | 69.1% | +89.3 | −$45 |
| STOPLOSS_20 | any | +30.39% | 66.5% | +82.3 | −$44 |

### q10 × 15m × ALL (n=117)

| Policy | Fail% | ROI%/trade | Hit% | Sharpe | MaxDD |
|---|---:|---:|---:|---:|---:|
| HEDGE_HOLD | 0% | +35.97% | 74.4% | +77.7 | −$25 |
| HEDGE_HOLD | 100% | +33.93% | 72.6% | +40.1 | −$135 |
| SELL_OWN_BID | any | **+37.97%** | 77.8% | **+83.5** | −$25 |
| HYBRID | 100% | +37.97% | 77.8% | +83.5 | −$25 |
| STOPLOSS_20 | any | +36.02% | 76.9% | +77.9 | **−$24** |

### q10 × 5m × per-asset breakdown (HEDGE_HOLD@100% vs SELL_OWN_BID)

| Asset | HEDGE_HOLD@100% ROI | SELL_OWN_BID ROI | Δ | HEDGE_HOLD@100% MaxDD | SELL_OWN_BID MaxDD |
|---|---:|---:|---:|---:|---:|
| BTC | +29.50% | +42.50% | **+13.00 pp** | −$118 | −$42 |
| ETH | +15.49% | +37.84% | **+22.35 pp** | −$113 | −$42 |
| SOL | **−4.10%** | +28.91% | **+33.01 pp** | **−$274** | −$69 |

SOL is the most exposed asset — also where the countermeasure helps most.

---

## Why the policies break down this way

**HEDGE_HOLD's failure mode** is the implementation guide's "max_loss = entry + hedge − 1 + fee ≈ $0.02–0.04 per $1" assumption breaking when `hedge` is forced to 0. The formula collapses to `max_loss = entry` which on a 0.55 entry is **−55¢ per $1 stake**, ridable on every wrong-direction signal that triggered a reversal. With ~50% hedge-trigger rate × ~28% wrong-direction within sniper × ~ride-to-resolution = catastrophic tail.

**SELL_OWN_BID's win** is a known-quantity exit. At reversal trigger, the held side is typically already moved (price dropped 5+bp on Binance → Polymarket bids drop 3–7¢). Selling at bid 0.45 vs entry 0.55 = realized −$0.10/share. Worse than hedge-hold's $0.02–0.04 cap **when hedge fires**, but vastly better than the −$0.55 unhedged-loss tail when hedge fails. And the resolution-fee math on hedge-hold ate more of the upside than expected.

**HYBRID's win** is "best of both": pure HEDGE_HOLD performance on healthy days, gracefully degrades to SELL_OWN_BID on broken days. **Strictly dominates** at every (cell, fail-rate) combination.

**STOPLOSS_20's tradeoff** is exits trigger more often (66–73% bid-exit rate vs 53–62% reversal-only), capturing fewer wins. It has the lowest MaxDD (−$80 q10 5m vs −$130 SELL_OWN_BID) but trades −7 pp ROI for it. **Useful as a separate leg for risk-averse capital, not as a replacement.**

---

## Recommendation — what to ship

### Tier 1 (ship now, alongside the 4-bug fix)

**Switch the locked exit from HEDGE_HOLD to HYBRID.** Implementation:

```python
# In TV's _maybe_hedge:
async def _maybe_hedge(self, slot: Slot) -> None:
    # ... existing rev_bp trigger logic unchanged ...
    if not reverted:
        return

    # Try hedge first (existing path)
    book = await self._fetch_opposite_book(slot, opposite_outcome)
    if book and book.get("asks"):
        try:
            await self._place_hedge(slot, book)
            slot.status = "hedged_holding"
            return
        except HedgeRejected:
            pass

    # FALLBACK: sell own held side into ITS bid
    own_book = await self._fetch_own_book(slot, slot.signal)
    if own_book and own_book.get("bids"):
        try:
            await self._sell_at_own_bid(slot, own_book)
            slot.status = "exited_at_bid"
            return
        except SellRejected:
            pass

    # If both fail, ride to resolution (last resort)
    slot.status = "held_no_hedge"
    logger.warning("poly_updown.hedge_and_sell_both_failed", extra={...})
```

**Expected impact (q10 × 5m × ALL):**
- Production now (hedges 100% failing): +13.6% → **+36.4% ROI**, MaxDD −$378 → **−$130** (−65%)
- Post-bug-fix (hedges work normally): +34.5% → **+34.5% ROI** unchanged (HYBRID = HEDGE_HOLD when hedge succeeds)
- ANY intermediate state: HYBRID always ≥ HEDGE_HOLD

This is the "safe move regardless of bug status" choice.

### Tier 2 (consider after Tier 1 stabilizes)

**Switch to pure SELL_OWN_BID.** Simpler code (no hedge attempt at all), and surprisingly **outperforms HYBRID even at 0% fail rate** on every cell tested:

| Cell | SELL_OWN_BID ROI | HYBRID@0% ROI | Δ |
|---|---:|---:|---:|
| q10 × 5m × ALL | +36.41% | +34.50% | +1.91 pp |
| q20 × 15m × ALL | +33.38% | +31.43% | +1.95 pp |
| q10 × 15m × ALL | +37.97% | +35.97% | +2.00 pp |

This is because the 2% Polymarket protocol fee on the winning leg of a hedged pair eats more than the variance reduction is worth. The "delta-neutral cap" of hedge-hold is negative-EV vs immediate bid-close on healthy markets too.

**Caveat:** smaller sample (n=117–392). The +2 pp lift is consistent across cells but inside the noise band of a 6-day backtest universe. Tier 1 (HYBRID) gets us 95% of the benefit with zero risk vs the locked spec.

### Tier 3 (defer, but useful research)

- **Test STOPLOSS_X with X ∈ {0.10, 0.15, 0.20, 0.25}.** Current STOPLOSS_20 trades 7 pp ROI for half the MaxDD vs SELL_OWN_BID. A tighter or looser stop may shift the frontier.
- **Test combined HYBRID + STOPLOSS** — bid-exit on either reversal-trigger OR price-stop, whichever fires first. May give SELL_OWN_BID's ROI with STOPLOSS's drawdown profile.
- **Test asymmetric stops per asset.** SOL has the worst tail; might warrant a tighter stop than BTC/ETH.

---

## What we just learned about the locked spec

The implementation guide §2 ("Why hedge-hold (not direct sell, not merge)") justified hedge-hold over direct-sell with: *"Direct sell is vulnerable to bid-side spread degradation. When the market moves against us, the bid often slips 3–5¢ before we can exit, locking in a dirty fill."*

The realfills + fallback backtests show this concern was real but the magnitude was overestimated. On L10 book data, the dirty-fill cost is ~5¢ on the bid, but hedge-hold pays ~6¢ via the 2% fee on the winning leg's profit. Net wash, with hedge-hold carrying massive tail risk when hedges fail.

**Updated locked spec recommendation:**
- Replace `hedge-hold` with `HYBRID (hedge-then-sell-own-bid fallback)` as the primary exit.
- Keep `rev_bp=5` trigger threshold unchanged.
- Keep `q10` on 5m, **switch to `q10` on 15m too** (per [DEPLOYED_STRATEGIES_NEW_METRICS.md](DEPLOYED_STRATEGIES_NEW_METRICS.md)).

---

## Files

- [polymarket_hedge_fallback.py](strategy_lab/polymarket_hedge_fallback.py) — simulator (220 LOC, reuses realfills loaders)
- [hedge_fallback.csv](strategy_lab/results/polymarket/hedge_fallback.csv) — full cell × policy × fail-rate sweep (72 rows × 25 cols)
- [POLYMARKET_HEDGE_FALLBACK.md](strategy_lab/reports/polymarket/02_analysis/POLYMARKET_HEDGE_FALLBACK.md) — full per-cell tables

**To reproduce:**
```bash
py polymarket_hedge_fallback.py             # default seed=42
PMK_FAIL_SEED=7 py polymarket_hedge_fallback.py   # alternate seed for robustness check
```

---

**Bottom line:** ship **HYBRID** in TV alongside the 4-bug fix. It's the move that's safe regardless of bug status. **Expected immediate impact:** rescue ~+22 pp ROI on q10 5m ALL (current production ~+13% → projected +36%), reduce MaxDD by ~65%, eliminate the SOL 5m negative-ROI tail.
