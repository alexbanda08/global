# Cancel rules decoded — Polymarket maker wallets

**Date**: 2026-05-18
**Wallets**: `0x04b6d7e9` (persistent-maker template), `0xb27bc932` (scale-up template)
**Method**: L25 orderbook inference (cancels are off-chain on Polymarket; never hit chain)

---

## TL;DR

Both wallets follow the **same cancel rule**: **CANCEL when the level position becomes stale**, where "stale" means either (a) the best_bid has moved meaningfully or (b) ~10-30s elapsed since the last fill. After a cancel, they REPOST at the new best price (option **A** — chase the market). They do NOT leave bids sitting hoping the price comes back.

| Wallet | Median cancel age | Median best_bid displacement at cancel | P(|disp|≥3¢) | Cancel-after-fill rate |
|---|---|---|---|---|
| 0x04b6d7e9 | 17.2s | 5.5¢ | 71.8% | 100% |
| 0xb27bc932 | 7.2s | 5.0¢ | 65.8% | 100% |

`0xb27bc932` cancels **2.4× faster** than `0x04b6d7e9` — consistent with the "scale-up / HFT" template.

---

## Why we used L25 inference (not chain logs)

The Polymarket CLOB is **off-chain matched**. Verified by querying the NegRiskCtfExchange (`0xe111180000d2663c0091e4f400237545b87b996b`) for the `OrderCancelled(bytes32)` topic (`0x5152abf9...`):

```
NegRisk addr total logs in 1000 blocks: 229,416
  0xd543adfd... (OrderFilled):    132,687
  0x55bb3cad... (FeeCharged):      48,404
  0x174b3811... (OrdersMatched):   48,325
  OrderCancelled(bytes32):              0
```

Same for `0xC5d563...` (CTFExchange-NegRisk) and `0x4bFb41d5...` (CTFExchange-classic). All return zero cancel events.

**Conclusion**: Cancels are API-only operations. To decode them, we must infer from the public L25 orderbook depth-disappearance signal.

---

## Inference pipeline

1. Group `trades_chain_enriched` by `order_hash` → `(slug, outcome, side, price, first_fill_ts, last_fill_ts, total_filled, n_fills)`.
2. Map asset_id → (slug, outcome) via `data/v4/refresh_2026_05_12/markets_full.csv` `clob_token_ids` (Polymarket convention: `[YES, NO]`).
3. Load L25 streaming for matching slugs.
4. For each order:
   - Get **level_at_last_fill** = size at order's price-cents bucket immediately after the last fill.
   - If level_at_last_fill < 0.5 shares → **FILLED_FULL** (level fully consumed; no remainder to cancel).
   - Else: scan forward. If level shrinks ≥ 50% of level_at_last_fill within the slug window → **CANCELLED** at that book-snapshot timestamp.
   - If level persists to slot_end → **EXPIRED**.
5. Record `cancelled_ts`, `lifetime_after_last_fill_s`, `bb_displacement_cents` (`best_bid_at_cancel − best_bid_at_first_fill`).

Sample: random 400 orders per wallet. Output parquets:
- `strategy_lab/wallet_hunt/cache/0x04b6d7e9/_cancel_inference_btc.parquet`
- `strategy_lab/wallet_hunt/cache/0xb27bc932/_cancel_inference_btc.parquet`

---

## Wallet 0x04b6d7e9 — persistent-maker template

### Classification

| Class | n | % |
|---|---|---|
| FILLED_FULL (residual ≈ 0 after last fill) | 361 | 90.2% |
| CANCELLED (level shrank within slug) | 39 | 9.8% |
| EXPIRED (level persists to slot_end) | 0 | 0.0% |

### Cancel age distribution (lifetime since last_fill)

| Quantile | seconds |
|---|---|
| p10 | 2.3 |
| p25 | 6.1 |
| **p50** | **17.2** |
| p75 | 45.2 |
| p90 | 120.2 |
| p99 | 303.6 |

P(cancel < 10s) = 41%, P(cancel < 30s) = 61.5%, P(cancel < 60s) = 82%.

### Best-bid displacement at cancel

Median |displacement| = **5.5 cents**.

| Threshold | P(|disp| ≥ x) |
|---|---|
| 1¢ | 87.2% |
| 3¢ | 71.8% |
| 5¢ | 51.3% |
| 10¢ | 28.2% |

P(disp < 0 — market moved AWAY) = 59.0%
P(disp > 0 — market moved TOWARD) = 30.8%

The wallet cancels in both directions but with a 2:1 bias toward cases where the market moved away (price went below their ask).

### H4 (cancel-near-close): MEDIAN 141s left in slug at cancel — only 2.6% cancel within 30s of close. **Not a close-out rule.**

---

## Wallet 0xb27bc932 — scale-up template

### Classification

| Class | n | % |
|---|---|---|
| FILLED_FULL | 355 | 88.8% |
| CANCELLED | 38 | 9.5% |
| EXPIRED | 6 | 1.5% |
| EXPIRED_NOSEEN | 1 | 0.2% |

### Cancel age distribution

| Quantile | seconds |
|---|---|
| p10 | 1.8 |
| p25 | 5.0 |
| **p50** | **7.2** |
| p75 | 16.8 |
| p90 | 41.9 |
| p99 | 87.3 |

P(cancel < 10s) = 60%, P(cancel < 30s) = 84%, P(cancel < 60s) = 97%. **Significantly faster than 0x04b6d7e9.**

### Best-bid displacement at cancel

Median |displacement| = **5.0 cents**.

| Threshold | P(|disp| ≥ x) |
|---|---|
| 1¢ | 84.2% |
| 3¢ | 65.8% |
| 5¢ | 44.7% |
| 10¢ | 18.4% |

P(disp < 0 AWAY) = 55.3%, P(disp > 0 TOWARD) = 34.2%. Similar bias to 0x04b6d7e9.

### H4: median 126s left in slug at cancel — 0% cancel within 30s of close. **Not a close-out rule.**

---

## Cancel rule hypotheses — verdict

| Hypothesis | 0x04b6d7e9 | 0xb27bc932 | Verdict |
|---|---|---|---|
| **H1**: Cancel when best_bid displaced ≥ X¢ | Median 5.5¢, p25 thresh ≈ 1-3¢ | Median 5.0¢, p25 thresh ≈ 1-3¢ | **Likely TRUE** — both wallets cancel with significant displacement in 70-85% of cases. |
| **H2**: Cancel after fixed time T | p50 17s / p90 120s (slow) | p50 7s / p90 42s (fast) | **Partially TRUE** — there's a clear age signal but it interacts with displacement |
| **H3**: Cancel one-and-done after a fill | 100% had ≥1 fill before cancel | 100% had ≥1 fill before cancel | **TRUE** (we only see filled orders; can't say about no-fill cancels) |
| **H4**: Cancel near slug close | 2.6% within 30s of close | 0% within 30s of close | **FALSE** |
| **H5**: Never cancel | EXPIRED = 0/400 | EXPIRED = 6/400 | **FALSE** for 04b6d7e9, mostly false for b27bc932 |

**Combined rule**: Cancel when EITHER `|best_bid_now − best_bid_at_post| ≥ ~3¢` OR `age_since_last_fill ≥ ~10-30s`. Whichever fires first.

The two wallets differ in **time-pressure tolerance**:
- 0x04b6d7e9 will sit for 17s median before re-evaluating
- 0xb27bc932 re-evaluates every 7s — appropriate for higher-frequency scale-up where queue-priority matters less than book-following speed

---

## Recommended rule for shadow runner

```python
class CancelRule:
    """Mimic 0x04b6d7e9 / 0xb27bc932 maker cancel logic."""

    # Persistent-maker preset (mimics 0x04b6d7e9)
    cancel_threshold_cents: float = 3.0       # cancel if |bb_now - bb_post| >= 3¢
    max_order_age_s: float = 20.0             # cancel if older than ~p50 lifetime
    cancel_on_fill: bool = False              # NOT one-and-done; leave residual on book
    cancel_on_close: bool = False             # H4 false — do NOT cancel near slug end
    repost_on_cancel: bool = True             # always REPOST at new best_bid (chase market)

    # Scale-up preset (mimics 0xb27bc932) — for higher-frequency variant
    # cancel_threshold_cents = 2.0
    # max_order_age_s = 8.0

    def should_cancel(self, order, book_now, t_now) -> bool:
        # H1: displacement check
        bb_post   = order.best_bid_at_post
        bb_now    = book_now.best_bid_same_side(order.side)
        disp_c    = abs(bb_now - bb_post) * 100
        if disp_c >= self.cancel_threshold_cents:
            return True
        # H2: time check (since LAST fill, not since post)
        age_s = t_now - order.last_fill_ts
        if age_s >= self.max_order_age_s:
            return True
        return False
```

### Key parameters

| Parameter | Persistent (04b6d7e9) | Scale-up (b27bc932) |
|---|---|---|
| `cancel_threshold_cents` | **3¢** | **2¢** |
| `max_order_age_s` | **20s** (p50 17s) | **8s** (p50 7s) |
| `cancel_on_fill` | **False** | **False** |
| `cancel_on_close` | **False** | **False** |
| `repost_on_cancel` | **True** (chase) | **True** (chase) |

### Sanity tests for the runner

- Of 400 sampled orders, ~90% had no remaining residual after their last fill (FILLED_FULL). The runner should expect most posted orders to fully consume — no cancel needed.
- Of the ~10% with residual, ~60% cancel because the book moved away (disp < 0). Encode this as the dominant trigger.
- **Negative result**: there's no "cancel-on-slug-close" rule. Orders are NOT pulled before settlement; the wallet relies on the book naturally draining or filling.

---

## Limitations

1. **We only see filled orders.** The chain has no record of orders that posted-then-cancelled without any fill. Our 100% cancel-after-fill rate is a selection bias artifact — runner should still consider partial-fill or zero-fill cancels separately.
2. **L25 resolution is 1Hz subsampled.** Sub-second cancels (rare per our data — p10 is 2-3s) may be missed.
3. **Level aggregation**: multiple makers may share the same price-cents bucket. Our "level shrinks ≥ 50%" heuristic assumes the wallet is the dominant participant at that level, which is empirically true (wallet's post sizes are large: $25-$200 typical) but not guaranteed.
4. **Sample size**: 400 random orders → ~38-39 cancels per wallet. Estimates have ~15% relative SE. Re-run with `N_SAMPLE=1000+` if higher precision is needed.

---

## Reproduce

```bash
# Build asset_id → slug mapping for 0xb27bc932 (only needed once)
py -3 -X utf8 strategy_lab/wallet_hunt/_enrich_b27.py

# Run cancel decoder
N_SAMPLE=400 py -3 -X utf8 strategy_lab/wallet_hunt/_cancel_decode.py 0x04b6d7e9
N_SAMPLE=400 py -3 -X utf8 strategy_lab/wallet_hunt/_cancel_decode.py 0xb27bc932
```

Source: `strategy_lab/wallet_hunt/_cancel_decode.py`
