# EEBDE7A0 — TAKER (Market-Buy) Trigger Decoded
**Wallet:** `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`
**Date:** 2026-05-18
**Window:** Apr 24 – May 15 (6.12d on-chain history, 547,545 OrderFilled events)
**Focus:** BTC 5m up-down markets (1,341 unique slugs)
**Artifacts:**
- `strategy_lab/wallet_hunt/decode_eebde7a0_taker_trigger.py` (v1)
- `strategy_lab/wallet_hunt/decode_eebde7a0_taker_v2.py` (cost-basis pair-arb)
- `strategy_lab/wallet_hunt/decode_eebde7a0_taker_v3.py` (bucket analysis)
- `strategy_lab/wallet_hunt/decode_eebde7a0_taker_v4_control.py` (control test)
- `strategy_lab/wallet_hunt/cache/0xeebde7a0_taker_decode/enriched_taker_fires_v2.parquet`

---

## TL;DR

The taker (market-buy) trigger is **discount capture** — specifically:
> Buy when **best ask ≤ $0.50** AND **ask has dropped > 5¢ from rolling 60-second median**.

Inventory state (rebalance hypothesis A) and pair-arb on book asks both **failed control tests**.
Binance momentum match is at noise (52% all, 51% on filtered) — **not the trigger**.

Calibrated rule captures ~33% of taker fires with **1.48x lift** vs random non-fire moments.
The remaining 67% appear to be smaller-discount opportunistic takes — the wallet fires often
on partial discounts too, rather than waiting for deep dips.

---

## 1. Maker vs taker breakdown

| Class                  | n         | Notes |
|------------------------|-----------|-------|
| Total OrderFilled      | 547,545   | 6.12d, all assets |
| BTC 5m subset          | 313,997   | filtered to BTC up-down 5m |
| Sane prices (0 < p ≤ 1)| 220,608   | 4% rows have buggy raw decode (NEG_RISK / split) |
| Wallet MAKER (passive SELL) | 77,906  | wallet posts ASK, taker hits it |
| Wallet TAKER (aggressive BUY) | 142,702 | wallet hits someone's ASK |

**Important semantic note:** for this wallet, ALL maker fires are `side=SELL` (ASKS posted) and
ALL taker fires are `side=BUY` (asks hit). The wallet never posts BIDS and never sells as taker.
This is the **classic mint-and-sell-then-buyback** signature.

---

## 2. Hypothesis A — REBALANCE: FAILED

| Metric                                              | Fire rate | Control rate | Lift |
|-----------------------------------------------------|-----------|--------------|------|
| `inv_other_before > 0.5` (other side already long)  | 74.5%     | 78.7%        | 0.95x|
| `inv_own_before < -0.5` (bought side SHORT)         | 15.6%     | 18.8%        | 0.83x|
| `inv_own < inv_other` (under-weighted bought side)  | 41.8%     | ~41%         | ~1.0x|

**Verdict:** All three are at-or-below baseline. The wallet is ALWAYS long both sides as a
consequence of mint-and-sell mechanics, so "other side is long" is not informative. The wallet
is NOT firing to rebalance — control samples show identical inventory state distributions.

---

## 3. Hypothesis B — DISCOUNT CAPTURE: CONFIRMED

| Metric                              | Fire rate | Control rate | Lift  |
|-------------------------------------|-----------|--------------|-------|
| `ask_drop_60s > 3c`                 | 47.7%     | 36.0%        | 1.32x |
| `ask_drop_60s > 5c`                 | 38.2%     | 27.8%        | 1.37x |
| `own_best_ask < $0.50`              | 55.7%     | 48.0%        | 1.16x |
| `own_best_ask < $0.40`              | 42.8%     | 37.1%        | 1.15x |
| `own_best_ask<0.50 AND drop>3c`     | 40.2%     | 28.5%        | **1.41x** |
| `own_best_ask<0.50 AND drop>5c`     | 33.1%     | 22.4%        | **1.48x** |

| Feature           | Fire median | Control median |
|-------------------|-------------|----------------|
| own_best_ask      | **0.46**    | 0.51           |
| ask_drop_from_60s | **+2.0¢**   | 0.0¢           |
| take_price        | $0.334      | n/a (no trade) |
| pair_ask_sum      | $1.010      | $1.010 (no diff)|

**Pair-arb on book asks: NOT the trigger.** `pair_ask_sum` median is $1.010 across BOTH
fires and controls — book never crosses into arb territory (< $1). So the wallet is NOT chasing
risk-free book-arb. They're capturing **directional discounts on cheap sides**.

---

## 4. Hypothesis C — MOMENTUM FOLLOWING: NOT THE TRIGGER

| Filter                       | n     | Binance match rate |
|------------------------------|-------|--------------------|
| All taker fires              | 1,798 | 51.8% (noise)      |
| `|ret_60s| > 0.05%`          | 358   | 51.1%              |
| `|ret_60s| > 0.1%`           | 65    | 50.8%              |

Match rate at noise (50%). **Binance direction is independent of which outcome they market-buy.**
They buy whichever side became cheap, regardless of underlying spot.

---

## 5. Pair-effective-cost test (B' variant): WEAK SIGNAL

We tested whether wallet fires when `take_price + cost_basis_other_side < $1` (locks
in +EV pair). Control test verdict:

| Metric                       | Fire rate | Control rate | Lift |
|------------------------------|-----------|--------------|------|
| `pair_eff_at_ask < $0.95`    | 42.7%     | 37.9%        | 1.13x |
| `pair_eff_at_ask < $0.90`    | 38.0%     | 33.8%        | 1.12x |
| `pair_eff<0.95 AND inv_other>0.5` | 42.5% | 37.6%      | 1.13x |

Pair-eff is a **consequence** of mint-and-sell economics (median pair_eff ≈ $0.69 at fires
because they've already sold one side at ~0.5), but it doesn't differentiate fire moments
from control moments well. **Discount on the bought-side ASK is the dominant signal.**

---

## 6. Detected primary trigger

> **DISCOUNT-CAPTURE on either side, with bias to sides priced below 50¢ that have
> dropped ≥3-5¢ in the last minute.**

Inventory and pair-arb are red herrings — they look correlated because mint-and-sell wallets
are always long both legs, but they don't predict fire timing.

---

## 7. Recommended decision tree for shadow runner

```python
# Decoded TAKER trigger for 0xeebde7a0...
# Calibrated thresholds from 1798 fires + 1401 controls, BTC 5m, 6d history.

MIN_ASK_DROP_60S = 0.03   # cents; required drop from rolling 60s best-ask median
MAX_OWN_ASK      = 0.50   # cents; don't take if side already expensive
TAKE_SIZE_USD    = 2.00   # median fire notional ≈ $1.9, p95 ≈ $14
MAX_NOTIONAL_USD = 15.0   # hard cap

def should_market_buy(slug: str, outcome: str, book_now, book_history_60s):
    """Returns (action, side, notional) or None.

    book_now      = {'best_ask': float, 'best_bid': float} for `outcome`
    book_history_60s = list of best_ask snapshots in past 60s (incl. now)
    """
    own_ask = book_now['best_ask']
    if own_ask >= MAX_OWN_ASK:
        return None   # side too expensive

    # rolling-60s median of best ask
    asks_60s = [s for s in book_history_60s if s and s > 0]
    if len(asks_60s) < 3:
        return None
    med_ask = sorted(asks_60s)[len(asks_60s) // 2]
    drop    = med_ask - own_ask

    if drop < MIN_ASK_DROP_60S:
        return None   # no discount

    # Scale notional with discount magnitude (more cheap -> bigger take)
    if drop >= 0.05:
        notional = min(MAX_NOTIONAL_USD, TAKE_SIZE_USD * 3)
    elif drop >= 0.03:
        notional = TAKE_SIZE_USD * 1.5
    else:
        notional = TAKE_SIZE_USD

    return ('BUY_TAKER', outcome, notional)
```

### Tighter variant (1.48x-lift rule, smaller coverage):
```python
if own_ask < 0.50 and (med_ask - own_ask) > 0.05:
    fire(outcome, notional=$2)
```
Coverage ≈ 33% of their fires; lift = 1.48x.

### Looser variant (recommended for shadow runner):
```python
if (med_ask - own_ask) > 0.03:
    fire(outcome, notional=$2)
```
Coverage ≈ 48% of their fires; lift = 1.32x. **Higher recall, still strong precision.**

---

## 8. Calibrated parameters

| Parameter              | Value     | Source                              |
|------------------------|-----------|-------------------------------------|
| `MIN_ASK_DROP_60S`     | **3¢**    | 47.7% fire rate, 36% ctrl, lift 1.32|
| `MAX_OWN_ASK`          | **$0.50** | 55.7% of fires below this           |
| `TAKE_SIZE_USD` median | **$1.88** | median notional of decoded fires    |
| `TAKE_SIZE_USD` p95    | **$13.65**| upper end for high-discount fires   |
| Take-size cap          | **$15**   | 95th percentile, avoids tail outliers|
| 60s-median window      | **60 s**  | works well; 5s also tested (similar)|
| Time-in-slot bias      | none      | fires distributed evenly 30s..280s after slot start |

---

## 9. Sample size & significance

- 2,000 taker fires sampled (uniform random from 97k fires in top-density slugs)
- 1,798 enriched with book context (10% miss = no L25 snapshot in slug)
- 1,401 matched control samples (same slugs, random offsets)
- L25 books loaded at full microsecond resolution

**Wilson 95% CI on 1.48x lift:** 33.1% vs 22.4% on n≈1400 each → p < 0.001 (Z ≈ 6.4).
Significantly different distributions → trigger is real.

---

## 10. Caveats

1. **Sub-second timing is unmeasured.** L25 microsecond books were used, but the wallet's
   on-chain `timestamp` is at 1s resolution. Real take decision likely uses 100ms-level
   book reading.
2. **NEG_RISK splits / merges (~4% of rows)** were filtered out as "buggy prices >1" — wallet
   may use these for inventory operations, but they don't appear to be the trigger mechanism.
3. **We did NOT test pre-fire trades-tape signals** (e.g., recent SELL volume from other
   takers in the same outcome). That could push lift higher.
4. **Slot-time bias is mild but present**: 21% of fires are in first 60s, 34% in last 120s.
   No reason to gate by offset.
5. **Sampled slugs are TOP-DENSITY** (most taker activity). Coverage on sparse slugs may
   look different.

---

## 11. Next steps

- Encode the loose variant (`MIN_ASK_DROP_60S=3c`) into shadow runner.
- Run shadow on live VPS3 vs production momo controller for 24h, log overlap.
- Compare PnL with real Polymarket fee model (`0.07 × p × (1-p)`).
- Investigate the 67% of fires NOT captured by the rule — may be triggered by trades-tape
  signal we haven't decoded.
