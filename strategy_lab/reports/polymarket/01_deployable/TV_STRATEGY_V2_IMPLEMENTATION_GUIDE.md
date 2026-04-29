# Tradingvenue — Polymarket UpDown Strategy V2 (Hybrid Hedge) Implementation Guide

**Audience:** the Tradingvenue agent / operator implementing Phase 18.x v2.
**Purpose:** deploy a parallel "v2" shadow sleeve running the same `sig_ret5m` signal as the locked v1 strategy, but with **HYBRID exit policy** (try-hedge → fallback-sell-own-bid → last-resort-hold) AND with the four upstream bugs (#1, #6, #7, #8) fixed.
**Self-contained:** does not require reading [TV_STRATEGY_IMPLEMENTATION_GUIDE.md](TV_STRATEGY_IMPLEMENTATION_GUIDE.md) (v1) to implement. Diff against v1 is summarized in §1 for context.

**Source of validation:**
- Exit-policy: 4-policy × 3-fail-rate × 6-cell sweep on L10 book-walked realfills sim. See [HEDGE_FALLBACK_RECOMMENDATION.md](../02_analysis/HEDGE_FALLBACK_RECOMMENDATION.md).
- Bug analysis: live VPS storedata audit + source review. See [TV_STRATEGY_TEST_AND_MODIFICATIONS.md](TV_STRATEGY_TEST_AND_MODIFICATIONS.md) §3.

---

## TL;DR — what's changing in v2

| | v1 (current shadow) | **v2 (new shadow)** |
|---|---|---|
| Exit on rev_bp=5 trigger | `HEDGE_HOLD` — buy-opposite-ask, hold to resolution. If asks empty → ride to resolution unhedged. | **`HYBRID`** — try buy-opposite-ask. If fails → sell own held side at its bid. If both fail → ride to resolution. |
| `resolve_condition_id` cache TTL | 3600 s (1h) | **`tf_seconds // 2`** (150 s for 5m, 450 s for 15m). Invalidate when `resolve_unix < now`. |
| `paper.STALE_AFTER_SECONDS` | 900 s (15 min) | **30 s** (flat) |
| `paper` orderbook cache TTL | 3600 s (1h) | **10 s** |
| `place_entry_order(qty=...)` semantics | `qty` = USD notional but treated as shares in book-walk | **`qty` = USD notional, converted to shares before book-walk** |
| Hedge audit trail | Bare journalctl strings | **Structured `trading.events` rows** with slug, condition_id, token_id, book_ts, book_age_s |
| Sleeve namespace | `poly_updown_{btc,eth,sol}_{5m,15m}` | **`poly_updown_v2_{btc,eth,sol}_{5m,15m}`** (parallel) |
| Stake | $25 (production) or $1 (tiny-live) | **$25 paper, $1 tiny-live** (unchanged for parity comparability) |
| Signal | `sig_ret5m`, sniper q10/q20, volume mode | **unchanged** |
| Bring-up | Phase 18 plan | **Phase 18.x v2 — parallel to v1, A/B testable** |

**Rationale for parallel deployment, not in-place upgrade:**
- v1 keeps running on its current sleeves so we can A/B compare PnL/day, hit rate, hedge-success rate, and MaxDD between v1 (bug-affected, HEDGE_HOLD) and v2 (bug-fixed, HYBRID).
- Both sleeves consume the same signal pipeline; only the executor + exit-policy + bug-fix paths differ.
- After 7 days of parallel data, decide: promote v2 to production, retire v1, or roll back v2.

---

## 1. The four bug fixes (must ship first)

These are **global** code changes. They affect both v1 and v2 sleeves. They are correctness fixes — there is no scenario where the v1 sleeve "needs" the bug behavior.

### Bug #1 — `resolve_condition_id` cache TTL too long

**File:** `/opt/tradingvenue/backend/app/strategies/polymarket/market_mapping.py`

**Symptom:** controller fires signals on already-resolved markets because the (symbol, tf) → condition_id cache holds for 1h while a 5m market lives only 5 minutes.

**Verified on VPS (2026-04-28):** live `trading.events` shows `entry_placed` events at 17:50 UTC targeting condition_ids whose `window_start` was 17:30 UTC — 20 minutes after the market closed.

**Patch:**

```python
# market_mapping.py — line 31
# OLD:
_TTL_SECONDS = 3600  # 1 hour

# NEW:
_TTL_SECONDS_5M = 150   # 2.5 min (half the window life)
_TTL_SECONDS_15M = 450  # 7.5 min (half the window life)

def _ttl_for(tf: str) -> int:
    """Return cache TTL appropriate for the timeframe."""
    return _TTL_SECONDS_5M if tf == "5m" else _TTL_SECONDS_15M
```

Update `_cache_get` to use the per-tf TTL:

```python
def _cache_get(key: tuple[str, str], now: float) -> tuple[bool, str | None]:
    """Returns (hit, value). Hit=False means caller must query."""
    if key not in _CACHE:
        return False, None
    value, cached_at = _CACHE[key]
    symbol_lower, tf = key
    ttl = _ttl_for(tf)
    if now - cached_at >= ttl:
        del _CACHE[key]
        return False, None
    return True, value
```

**Defense-in-depth:** at the top of `resolve_condition_id`, add a sanity check that rejects any cached condition_id whose corresponding market is past `resolve_unix`:

```python
async def resolve_condition_id(pool, symbol, tf, signal_ts):
    # ... existing cache check ...
    if hit and cached:
        # Defense: ensure the cached condition_id is still active
        if not await _is_market_active(pool, cached, signal_ts):
            _CACHE.pop(key, None)  # evict stale
            hit = False
    # ... existing query ...

async def _is_market_active(pool, condition_id: str, now_ts: datetime) -> bool:
    row = await pool.fetchrow(
        "SELECT window_start_unix, resolve_unix FROM markets WHERE condition_id=$1",
        condition_id,
    )
    if row is None:
        return False
    now_s = int(now_ts.timestamp())
    return int(row["resolve_unix"]) > now_s
```

**Verification:** after deploy, query `trading.events` for last 1h:
```sql
SELECT data->>'condition_id' AS cid, e.at AT TIME ZONE 'UTC' AS at_utc,
       m.window_start_unix, m.resolve_unix,
       extract(epoch from e.at)::bigint - m.resolve_unix AS at_minus_resolve_s
FROM trading.events e
JOIN markets m ON m.condition_id = e.data->>'condition_id'
WHERE e.kind='poly_updown_signal'
  AND e.at > now() - interval '1 hour'
ORDER BY at_minus_resolve_s DESC LIMIT 10;
```
**Expected:** all rows have `at_minus_resolve_s < 0` (signals fired before market resolution). If any are positive, the bug isn't fixed.

---

### Bug #6 — `STALE_AFTER_SECONDS = 15 min` accepts dead-market snapshots

**File:** `/opt/tradingvenue/backend/app/venues/polymarket/paper.py`

**Symptom:** a 5m market resolves at t+5min. Snapshot collector stops writing for that market post-resolution. Paper executor at t+12min queries the latest snapshot, gets a 12-min-old row, finds it "fresh" (12min < 15min threshold), and "fills" at the dying-market degraded price (often 0.001 tick-min on the losing side).

**Patch:**

```python
# paper.py — line 34
# OLD:
STALE_AFTER_SECONDS = 15 * 60  # 15 minutes

# NEW:
STALE_AFTER_SECONDS = 30  # 30 seconds — tighter than any market window minimum
```

That's the entire fix. The constant is used in `_simulate` (line ~204) which already checks `now - book_ts > STALE_AFTER_SECONDS` and returns REJECTED.

**Verification:** after deploy, no `entry_placed` events should have `fill_price=0.0010` (the tick-min ghost-fill signature):
```sql
SELECT COUNT(*) FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'fill_status'='filled'
  AND data->>'fill_price'='0.0010'
  AND at > now() - interval '24 hours';
```
**Expected:** 0 rows.

---

### Bug #7 — Orderbook cache TTL = 1h

**File:** `/opt/tradingvenue/backend/app/venues/polymarket/paper.py`

**Symptom:** once `_fetch_orderbook` reads a snapshot showing `asks=[]` for a token, the result is cached for 1 hour. Every subsequent `on_tick` call (every 10s for the next 60 minutes) returns the same cached empty book — even if a fresher non-empty snapshot has been written by the collector in the meantime.

**Patch:**

```python
# paper.py — line 44 (constructor default)
# OLD:
def __init__(
    self,
    settings: PolySettings,
    pg_pool: Any | None = None,
    cache_ttl_seconds: int = 3600,
    cache_max_size: int = 256,
    slippage_bps: float = 2.0,
) -> None:

# NEW:
def __init__(
    self,
    settings: PolySettings,
    pg_pool: Any | None = None,
    cache_ttl_seconds: int = 10,   # was 3600 — short cache spares DB within one on_tick cycle, no longer
    cache_max_size: int = 256,
    slippage_bps: float = 2.0,
) -> None:
```

That's it. The cache logic at lines 128-134 is correct as-is; only the TTL constant is wrong.

**Verification:** after deploy, run an EXPLAIN ANALYZE on a `_fetch_orderbook` query timing — should be sub-10ms (it's an indexed lookup). If the increased query rate causes load issues, escalate cache_ttl to 30s, but never higher.

---

### Bug #8 — `qty=notional_usd` walks book as shares

**Files:**
- `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` (line ~567)
- `/opt/tradingvenue/backend/app/venues/polymarket/paper.py` (line ~213-225, `_simulate`)

**Symptom:** controller passes `qty=Decimal("25")` intending $25 USD notional. `_simulate` walks the book treating `25` as 25 shares. At entry_price=0.50, we acquire 25 shares for $12.50 — half the intended stake. At degraded price 0.001, we acquire 25 shares for $0.025 — 1000× under intent.

**Cleanest fix: change the `place_entry_order` API to take `notional_usd` and do the conversion once, server-side.**

```python
# paper.py — _simulate signature change
# OLD:
async def _simulate(
    self,
    *,
    token_id: int,
    qty: Decimal,                  # ambiguous
    limit_px: Decimal,
    side: str,
    sleeve_id: str,
    intent: str,
) -> OrderResult:
    # ... walks book consuming `qty` as shares

# NEW:
async def _simulate(
    self,
    *,
    token_id: int,
    notional_usd: Decimal,         # USD intent, explicit
    limit_px: Decimal,
    side: str,
    sleeve_id: str,
    intent: str,
) -> OrderResult:
    book = await self._fetch_orderbook(token_id)
    # ... staleness check unchanged ...

    # Walk book consuming USD until exhausted
    levels = book["asks"] if side == "buy" else book["bids"]
    remaining_usd = notional_usd
    filled_shares = Decimal("0")
    notional_paid = Decimal("0")
    for level in levels:
        px = Decimal(str(level.get("price", "0")))
        sz = Decimal(str(level.get("size", "0")))
        if side == "buy" and px > limit_px:
            break
        if side == "sell" and px < limit_px:
            break
        if px <= 0 or sz <= 0:
            continue
        level_notional = px * sz
        if level_notional >= remaining_usd:
            # Last level — partial consumption
            shares_here = remaining_usd / px
            filled_shares += shares_here
            notional_paid += remaining_usd
            remaining_usd = Decimal("0")
            break
        # Consume entire level
        filled_shares += sz
        notional_paid += level_notional
        remaining_usd -= level_notional

    if filled_shares == 0:
        return OrderResult(status=FillStatus.REJECTED, ..., reason="NO_LIQUIDITY_AT_LIMIT")

    avg_price = notional_paid / filled_shares
    is_partial = remaining_usd > Decimal("0.01")  # underfilled by >1¢ → partial

    return OrderResult(
        status=FillStatus.PARTIAL if is_partial else FillStatus.FILLED,
        intent=intent,
        order_id=f"paper-{sleeve_id}-{int(time.time())}",
        raw_response={
            "filled_shares": str(filled_shares),
            "intended_usd": str(notional_usd),
            "filled_usd": str(notional_paid),
            "avg_price": str(avg_price),
        },
    )
```

```python
# polymarket_updown.py — line ~567
# OLD:
result = await self.executor.place_entry_order(
    token_id=token_id,
    qty=self.notional_usd,    # AMBIGUOUS: this is USD but treated as shares
    limit_px=Decimal("0.99"),
    sleeve_id=sleeve_id,
    side="buy",
)

# NEW:
result = await self.executor.place_entry_order(
    token_id=token_id,
    notional_usd=self.notional_usd,    # explicit USD intent
    limit_px=Decimal("0.99"),
    sleeve_id=sleeve_id,
    side="buy",
)
```

**Update `place_entry_order` in both `paper.py` and `client.py`** to accept the new arg name. **Add a deprecation warning + back-compat shim if `qty=` is passed**:

```python
async def place_entry_order(
    self,
    *,
    token_id: int,
    notional_usd: Decimal | None = None,
    qty: Decimal | None = None,           # DEPRECATED back-compat
    limit_px: Decimal,
    sleeve_id: str,
    side: str,
) -> OrderResult:
    if notional_usd is None and qty is not None:
        log.warning("place_entry_order.qty_deprecated_use_notional_usd")
        notional_usd = qty
    if notional_usd is None:
        raise ValueError("place_entry_order: notional_usd required")
    return await self._simulate(
        token_id=token_id,
        notional_usd=notional_usd,
        limit_px=limit_px,
        side=side,
        sleeve_id=sleeve_id,
        intent="entry",
    )
```

**Verification:** after deploy, resolution events should show realistic dollar magnitudes. Currently a "filled" entry at price 0.49 with `entry_qty=25` gives PnL ≈ ±$12.50; post-fix it should give PnL ≈ ±$25 (twice as large, matching the intended stake):

```sql
SELECT
  data->>'fill_price' AS px,
  data->>'fill_qty' AS shares,
  data->>'pnl_usd' AS pnl,
  abs((data->>'pnl_usd')::numeric) AS abs_pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > now() - interval '24 hours'
ORDER BY at DESC LIMIT 10;
```
**Expected:** `abs_pnl` clusters around 12–13 (winning at fair entry) or 13–25 (losing at fair entry). NOT around 0.025 (ghost fills) or 12.5 (under-bet).

---

### Bug-fix wave acceptance criteria

After all four bugs ship:

```sql
-- Test 1: no signals on dead markets
SELECT COUNT(*) FROM trading.events e
JOIN markets m ON m.condition_id = e.data->>'condition_id'
WHERE e.kind='poly_updown_signal'
  AND e.at > now() - interval '6 hours'
  AND extract(epoch from e.at)::bigint > m.resolve_unix;
-- Expected: 0

-- Test 2: no tick-min ghost fills
SELECT COUNT(*) FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'fill_status'='filled'
  AND data->>'fill_price'='0.0010'
  AND at > now() - interval '6 hours';
-- Expected: 0

-- Test 3: realistic PnL magnitudes
SELECT data->>'symbol' AS sym,
       AVG(abs((data->>'pnl_usd')::numeric)) AS avg_abs_pnl,
       COUNT(*) AS n
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > now() - interval '6 hours'
GROUP BY sym;
-- Expected: avg_abs_pnl > 5 (was <1 in current data)
```

If any test fails, halt v2 deploy and re-investigate.

---

## 2. The HYBRID hedge policy (v2-only code path)

**File:** `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`

The HYBRID policy:
1. On `rev_bp=5` reversal trigger → try `place_hedge_order(opposite_token_id, ask_book)`
2. If hedge attempt rejects/empty asks → fall back to `place_exit_order(own_token_id, bid_book)` — sell our held side at its bid
3. If bid-side also fails → ride to natural resolution (last resort)

### 2.1 New executor method — `place_exit_order`

Both `PolyPaperExecutor` and `PolymarketClient` need a sell-into-own-bid method. Mirror `place_entry_order` shape but with `side="sell"` and walk the bid book instead of asks.

```python
# paper.py — add new method
async def place_exit_order(
    self,
    *,
    token_id: int,
    shares: Decimal,            # how many shares to sell (= entry_qty for full close)
    limit_px: Decimal,          # accept down to this bid price
    sleeve_id: str,
) -> OrderResult:
    """Sell `shares` of `token_id` into the bid book. Walk levels in descending price."""
    return await self._simulate_sell(
        token_id=token_id,
        shares=shares,
        limit_px=limit_px,
        sleeve_id=sleeve_id,
        intent="exit",
    )

async def _simulate_sell(
    self, *, token_id: int, shares: Decimal,
    limit_px: Decimal, sleeve_id: str, intent: str,
) -> OrderResult:
    book = await self._fetch_orderbook(token_id)
    book_ts = int(book.get("ts", 0))
    now = int(time.time())
    if book_ts == 0 or (now - book_ts) > STALE_AFTER_SECONDS:
        return OrderResult(status=FillStatus.REJECTED, intent=intent,
                           reason="STALE_ORDERBOOK", raw_response={"book_ts": book_ts})

    bids = book.get("bids", [])
    if not bids:
        return OrderResult(status=FillStatus.REJECTED, intent=intent,
                           reason="NO_BIDS", raw_response={"book_ts": book_ts})

    remaining_shares = shares
    sold_shares = Decimal("0")
    proceeds_usd = Decimal("0")
    for level in bids:  # bids must be in descending price order
        px = Decimal(str(level.get("price", "0")))
        sz = Decimal(str(level.get("size", "0")))
        if px < limit_px:
            break  # don't sell below our floor
        if px <= 0 or sz <= 0:
            continue
        take = min(remaining_shares, sz)
        sold_shares += take
        proceeds_usd += take * px
        remaining_shares -= take
        if remaining_shares <= 0:
            break

    if sold_shares == 0:
        return OrderResult(status=FillStatus.REJECTED, intent=intent,
                           reason="NO_LIQUIDITY_AT_LIMIT", raw_response={"book_ts": book_ts})

    avg_price = proceeds_usd / sold_shares
    is_partial = remaining_shares > Decimal("0.01")
    return OrderResult(
        status=FillStatus.PARTIAL if is_partial else FillStatus.FILLED,
        intent=intent,
        order_id=f"paper-{sleeve_id}-exit-{int(time.time())}",
        raw_response={
            "sold_shares": str(sold_shares),
            "intended_shares": str(shares),
            "proceeds_usd": str(proceeds_usd),
            "avg_price": str(avg_price),
        },
    )
```

**Live `PolymarketClient` equivalent:** wrap `py_clob_client_v2`'s `create_and_post_order` with `side="SELL"`. Use `limit_px = bid_price - 1*tick_size` to ensure the order crosses (we want immediate fill, not maker placement). Mirror the same `OrderResult` schema.

### 2.2 New `_fetch_own_book` helper

Already symmetric with `_fetch_opposite_book`. Add it next to that method:

```python
async def _fetch_own_book(
    self, slot: Slot, own_outcome: str
) -> dict[str, Any] | None:
    """Fetch the OWN-side orderbook (for sell-into-bid fallback)."""
    get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
    if get_for_outcome is not None:
        try:
            return await get_for_outcome(slot.condition_id, own_outcome)
        except Exception:
            pass
    token_id = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
    if token_id is None:
        return None
    try:
        return await self.executor.get_orderbook_snapshot(token_id)
    except Exception:
        return None
```

### 2.3 Replace `_maybe_hedge` with the HYBRID version

Drop-in replacement. Signature unchanged. Behavior strictly extended (HEDGE_HOLD path preserved as the first branch).

```python
HEDGE_RETRY_ATTEMPTS = 3
HEDGE_RETRY_BACKOFF_S = 0.2

async def _maybe_hedge(self, slot: Slot) -> None:
    """HYBRID hedge policy: try buy-opposite-ask → fallback sell-own-bid → hold.

    Algorithm:
        1. Reversal trigger check (unchanged).
        2. Try buy-opposite-ask up to HEDGE_RETRY_ATTEMPTS times. If success →
           slot.status = "hedged_holding". Done.
        3. If hedge fails (no asks / rejected / underfilled), try sell-own-bid:
           sell entry_qty shares of held side at limit_px = current_bid - 1*tick.
           If success → slot.status = "exited_at_bid". Done.
        4. If both fail → slot.status = "held_no_hedge_no_exit". Ride to resolution.

    All branches emit structured trading.events for audit (see §3).
    """
    if slot.btc_close_at_ws == 0 or slot.binance_symbol_id == "":
        return

    now_s = int(time.time())
    try:
        close_with_ts = await fetch_close_with_ts_asof(
            slot.binance_symbol_id, "1MIN", now_s, pool=self.pool
        )
    except Exception:
        logger.exception("poly_updown.btc_now_fetch_failed", extra={"slot": slot.slot_id})
        return

    if close_with_ts is None:
        return
    btc_now, bar_us = close_with_ts

    bar_age_s = now_s - (bar_us // 1_000_000)
    if bar_age_s > STALE_BINANCE_FEED_SECONDS:
        logger.info("poly_updown.hedge_check_skipped_stale_feed",
                    extra={"slot": slot.slot_id, "bar_age_s": bar_age_s})
        return

    bps = float(
        (Decimal(btc_now) - Decimal(slot.btc_close_at_ws))
        / Decimal(slot.btc_close_at_ws) * Decimal(10_000)
    )
    reverted = (
        (slot.signal == "UP" and bps <= -REV_BP_THRESHOLD)
        or (slot.signal == "DOWN" and bps >= REV_BP_THRESHOLD)
    )
    if not reverted:
        return

    # ---------- BRANCH 1: try hedge buy-opposite-ask ----------
    opposite_outcome = "NO" if slot.signal == "UP" else "YES"
    opposite_token = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id

    book_opp = await self._fetch_opposite_book(slot, opposite_outcome)
    if book_opp and book_opp.get("asks"):
        first_ask = book_opp["asks"][0]
        try:
            other_ask_price = Decimal(str(first_ask.get("price", "0")))
        except Exception:
            other_ask_price = Decimal("0")
        if other_ask_price > 0:
            hedge_result = await self._try_hedge_with_retries(
                slot, opposite_token, other_ask_price
            )
            if hedge_result is not None and hedge_result.status in (
                FillStatus.FILLED, FillStatus.PARTIAL
            ):
                slot.status = "hedged_holding"
                slot.hedge_other_entry_price = other_ask_price
                await self._audit(
                    slot.symbol, slot.tf,
                    reason="hedge_placed",
                    signal=slot.signal,
                    condition_id=slot.condition_id,
                    extras={
                        "policy": "HYBRID",
                        "branch": "hedge_ok",
                        "token_id": str(opposite_token),
                        "ask_price": str(other_ask_price),
                        "fill_status": str(hedge_result.status),
                        "book_ts": book_opp.get("ts", 0),
                        "book_age_s": now_s - book_opp.get("ts", 0),
                        "asks_count": len(book_opp.get("asks", [])),
                        "bids_count": len(book_opp.get("bids", [])),
                        "bps_at_trigger": bps,
                    },
                )
                logger.info("poly_updown.hedge_placed", ...)
                return

    # ---------- BRANCH 2: hedge failed, try sell own bid ----------
    own_outcome = "YES" if slot.signal == "UP" else "NO"
    own_token = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
    book_own = await self._fetch_own_book(slot, own_outcome)
    if book_own and book_own.get("bids"):
        first_bid = book_own["bids"][0]
        try:
            own_bid_price = Decimal(str(first_bid.get("price", "0")))
        except Exception:
            own_bid_price = Decimal("0")
        if own_bid_price > 0:
            # Cross the spread by 1 tick to ensure fill (not maker)
            tick = Decimal("0.001") if own_bid_price > Decimal("0.96") or own_bid_price < Decimal("0.04") else Decimal("0.01")
            sell_limit = max(own_bid_price - tick, Decimal("0.001"))
            try:
                exit_result = await self.executor.place_exit_order(
                    token_id=own_token,
                    shares=slot.entry_qty,   # close full position
                    limit_px=sell_limit,
                    sleeve_id=slot.sleeve_id,
                )
            except Exception as exc:
                logger.exception("poly_updown.exit_order_raised", extra={"slot": slot.slot_id})
                exit_result = None

            if exit_result is not None and exit_result.status in (
                FillStatus.FILLED, FillStatus.PARTIAL
            ):
                slot.status = "exited_at_bid"
                slot.exit_price = own_bid_price
                proceeds = Decimal(str(
                    exit_result.raw_response.get("proceeds_usd", "0")
                ))
                slot.exit_proceeds_usd = proceeds
                await self._audit(
                    slot.symbol, slot.tf,
                    reason="exited_at_bid",
                    signal=slot.signal,
                    condition_id=slot.condition_id,
                    extras={
                        "policy": "HYBRID",
                        "branch": "fallback_bid",
                        "token_id": str(own_token),
                        "bid_price": str(own_bid_price),
                        "shares_sold": str(slot.entry_qty),
                        "proceeds_usd": str(proceeds),
                        "fill_status": str(exit_result.status),
                        "book_ts": book_own.get("ts", 0),
                        "book_age_s": now_s - book_own.get("ts", 0),
                        "bps_at_trigger": bps,
                    },
                )
                logger.info("poly_updown.exited_at_bid", ...)
                return

    # ---------- BRANCH 3: both failed, ride to resolution ----------
    slot.status = "held_no_hedge_no_exit"
    await self._audit(
        slot.symbol, slot.tf,
        reason="hedge_and_exit_both_failed",
        signal=slot.signal,
        condition_id=slot.condition_id,
        extras={
            "policy": "HYBRID",
            "branch": "ride_to_resolution",
            "opp_token_id": str(opposite_token),
            "own_token_id": str(own_token),
            "opp_book_ts": book_opp.get("ts", 0) if book_opp else 0,
            "own_book_ts": book_own.get("ts", 0) if book_own else 0,
            "opp_asks_count": len(book_opp.get("asks", [])) if book_opp else 0,
            "own_bids_count": len(book_own.get("bids", [])) if book_own else 0,
            "bps_at_trigger": bps,
        },
    )
    logger.warning("poly_updown.hedge_and_exit_both_failed",
                   extra={"slot": slot.slot_id, "side": slot.signal})
```

### 2.4 Resolution accounting for the new exit state

The existing resolution path handles `hedged_holding` and `held_no_hedge`. Add `exited_at_bid` handling:

```python
# When the slot resolves naturally OR has been pre-resolved via bid-exit:
if slot.status == "exited_at_bid":
    # Position already closed. PnL = proceeds - cost. No on-chain redemption.
    pnl = slot.exit_proceeds_usd - (slot.entry_price * slot.entry_qty)
    # Apply any execution fees (typically 0 on Polymarket entries; check spec)
    await self._record_resolution(slot, pnl, hedged=False, exited=True)
elif slot.status == "hedged_holding":
    # Existing hedge-hold logic — both legs pay out, redeem both
    ...
else:
    # Unhedged / failed-fallback — ride to natural resolution
    ...
```

**Key:** `exited_at_bid` slots do NOT need `redeemPositions()` — the position was closed off-chain via the CLOB bid-side trade. The `RedemptionWorker` should skip these:

```python
# In RedemptionWorker._scan_and_redeem, exclude already-exited slots:
WHERE NOT EXISTS (
    SELECT 1 FROM trading.events e3
    WHERE e3.data->>'condition_id' = m.condition_id
      AND e3.kind = 'poly_updown_signal'
      AND e3.data->>'reason' = 'exited_at_bid'
)
```

---

## 3. Structured trading.events for hedge audit (M-3)

**File:** `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`

Currently `_maybe_hedge` calls `logger.warning("poly_updown.hedge_skipped_no_asks", ...)` — bare strings in journalctl. We need these as structured `trading.events` rows.

`_audit` already exists (called for `entry_placed`, `entry_rejected`). Reuse it. Add an `extras` parameter that becomes part of the `data` jsonb:

```python
# polymarket_updown.py — _audit signature change
async def _audit(
    self, symbol: str, tf: str, *,
    reason: str,
    signal: str | None,
    condition_id: str | None = None,
    error: str | None = None,
    fill_status: str | None = None,
    fill_qty: str | None = None,
    fill_price: str | None = None,
    qty_intended: str | None = None,
    limit_px: str | None = None,
    extras: dict | None = None,                # NEW
    publish_bar_processed: bool = True,
) -> None:
    """... unchanged docstring ..."""
    payload = {
        "symbol": symbol, "tf": tf, "mode": self.mode_str,
        "reason": reason,
        "signal": signal,
        "condition_id": condition_id,
        "error": error,
        "fill_status": fill_status,
        "fill_qty": fill_qty,
        "fill_price": fill_price,
        "qty_intended": qty_intended,
        "limit_px": limit_px,
    }
    if extras:
        payload.update(extras)
    payload = {k: v for k, v in payload.items() if v is not None}
    # ... existing INSERT INTO trading.events ...
```

Then every `logger.warning` / `logger.info` in `_maybe_hedge` (currently bare strings) gets a paired `await self._audit(...)` call as shown in §2.3.

**Reasons to audit:**
- `hedge_placed` — branch 1 succeeded
- `exited_at_bid` — branch 2 succeeded (HYBRID-specific)
- `hedge_and_exit_both_failed` — branch 3 — last resort
- `hedge_check_skipped_stale_feed` — Binance bar too old
- `hedge_skipped_no_asks` — branch 1 found no asks (HEDGE_HOLD legacy path)
- `hedge_failed_held` — retries exhausted
- `held_no_hedge` — for HEDGE_HOLD legacy fallback

Plus a one-time audit at slot creation: `slot_opened` with `entry_price`, `entry_qty`, `policy=HYBRID|HEDGE_HOLD`, `btc_close_at_ws`, `bar_age_at_signal`.

**Verification SQL:**

```sql
-- Counts by reason in last 24h, only for v2 sleeves
SELECT data->>'reason' AS reason, COUNT(*)
FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'symbol' IS NOT NULL
  AND sleeve_id LIKE 'poly_updown_v2_%'
  AND at > now() - interval '24 hours'
GROUP BY reason
ORDER BY count DESC;
```

**Expected pattern (after deploy):**
- `order_placed` (entries) — bulk
- `hedge_placed` — ~30–50% of opens
- `exited_at_bid` — ~5–20% of opens (when hedge fails but bid exists)
- `hedge_and_exit_both_failed` — <5% (truly thin moments)
- `entry_rejected` — only when book stale/empty (much lower rate post-bug-fix)

---

## 4. Sleeve namespace + parallel deployment

To run v2 alongside v1, register **new sleeve_ids** that don't collide. Existing v1 sleeves keep running on the old code path.

### 4.1 New sleeve definitions

```python
# In your sleeve config (wherever sleeves are registered):
V2_SLEEVES = [
    "poly_updown_v2_btc_5m",
    "poly_updown_v2_eth_5m",
    "poly_updown_v2_sol_5m",
    "poly_updown_v2_btc_15m",
    "poly_updown_v2_eth_15m",
    "poly_updown_v2_sol_15m",
]

# Each sleeve resolves to:
# - same Binance symbol (BTC/ETH/SOL spot)
# - same timeframe (5m/15m)
# - same signal (sig_ret5m + same q10/q20 quantile per tf)
# - HEDGE_POLICY="HYBRID" (vs v1's HEDGE_HOLD)
```

### 4.2 Policy gate via env var

```python
# polymarket_updown.py — controller __init__
def __init__(self, pool, executor, mode, *, notional_usd=None, tiny_live_mode=False,
             hedge_policy: str = "HEDGE_HOLD"):  # NEW
    # ...
    if hedge_policy not in ("HEDGE_HOLD", "HYBRID"):
        raise ValueError(f"unknown hedge_policy: {hedge_policy}")
    self.hedge_policy = hedge_policy

# In _maybe_hedge: branch on policy
async def _maybe_hedge(self, slot: Slot) -> None:
    if self.hedge_policy == "HYBRID":
        return await self._maybe_hedge_hybrid(slot)
    return await self._maybe_hedge_legacy(slot)  # v1 HEDGE_HOLD path
```

Keep the v1 `_maybe_hedge_legacy` body unchanged (literally the existing code). Add the new `_maybe_hedge_hybrid` as defined in §2.3.

### 4.3 Sleeve → controller binding

Where sleeve controllers are wired (typically in `tv-engine/main.py` or a sleeve-config module):

```python
controllers = []
for sleeve_id in EXISTING_SLEEVES:  # the v1 6 sleeves
    controllers.append(PolymarketUpdownController(
        pool=pool, executor=paper_executor, mode=Mode.PAPER,
        notional_usd=Decimal("25"),
        hedge_policy="HEDGE_HOLD",  # v1 — locked
        sleeve_id=sleeve_id,
    ))

for sleeve_id in V2_SLEEVES:
    controllers.append(PolymarketUpdownController(
        pool=pool, executor=paper_executor, mode=Mode.PAPER,
        notional_usd=Decimal("25"),
        hedge_policy="HYBRID",       # v2 — new
        sleeve_id=sleeve_id,
    ))
```

Both sets run on the same paper executor; they don't conflict because each slot is keyed by `(sleeve_id, condition_id, window_start_unix)`. v1 and v2 sleeves will have different `sleeve_id` → independent slots even on the same market.

---

## 5. Configuration — env var diff

Add to `/etc/tv/tradingvenue.env` (or equivalent):

```ini
# v2 shadow sleeve config
TV_POLY_V2_SLEEVES=poly_updown_v2_btc_5m,poly_updown_v2_eth_5m,poly_updown_v2_sol_5m,poly_updown_v2_btc_15m,poly_updown_v2_eth_15m,poly_updown_v2_sol_15m
TV_POLY_V2_HEDGE_POLICY=HYBRID
TV_POLY_V2_NOTIONAL_USD=25                # match v1 for parity comparison
TV_POLY_V2_TINY_LIVE_NOTIONAL=1.00        # only used if v2 goes live before v1

# Bug-fix-related env vars (NEW — global, affect both v1 and v2)
TV_POLY_CONDITION_CACHE_TTL_5M=150        # was effectively 3600
TV_POLY_CONDITION_CACHE_TTL_15M=450       # was effectively 3600
TV_POLY_PAPER_STALE_AFTER_SECONDS=30      # was 900
TV_POLY_PAPER_BOOK_CACHE_TTL=10           # was 3600

# Existing v1 config — UNCHANGED
TV_POLY_REV_BP_THRESHOLD=5
TV_POLY_STRATEGY_MODES=volume,sniper
TV_POLY_SNIPER_QUANTILE_5M=0.90
TV_POLY_SNIPER_QUANTILE_15M=0.80
TV_POLY_TINY_LIVE=true
TV_POLY_TINY_LIVE_NOTIONAL=1.00
```

If your deployment doesn't read TTLs from env, hard-code the values per the patches in §1.

---

## 6. Bring-up sequence

### 18-V2-01 — Bug fixes (1 day)

Ship #1, #6, #7, #8 to production. **No new sleeves yet** — verify the bug fixes alone improve the v1 sleeve metrics (entry rejection rate drops, no ghost fills, correct PnL magnitudes).

Acceptance:
- All 3 bug-fix verification SQL queries from §1 pass
- Existing v1 hedge-success rate rises from ~0% to ~30–50% (per implementation guide §6 parity gate)
- 24h soak

### 18-V2-02 — HYBRID code path + new executor methods (1.5 days)

Ship `place_exit_order`, `_simulate_sell`, `_fetch_own_book`, `_maybe_hedge_hybrid`, `_audit(extras=...)`, `slot.exit_*` fields. **All inactive** behind `hedge_policy="HYBRID"` flag, default off.

Tests in `backend/tests/`:
- `test_paper_place_exit_order.py`: walks bid book, returns FILLED/PARTIAL/REJECTED correctly
- `test_hybrid_hedge_path.py`: mock executor returning `asks=[]` for opposite_book, verify slot transitions to `exited_at_bid` after bid-fallback succeeds
- `test_hybrid_both_fail.py`: both opposite-asks AND own-bids empty → verify slot transitions to `held_no_hedge_no_exit`
- `test_resolution_for_exited_at_bid.py`: PnL computed from `exit_proceeds_usd - entry_cost`, no redemption call

### 18-V2-03 — Register v2 sleeves + paper smoke (½ day)

Add `V2_SLEEVES` to controller config. Wire 6 new controllers with `hedge_policy="HYBRID"`. Both v1 and v2 controllers run on the same paper executor.

Run paper mode for **24 hours**. Verify by SQL:
- `entry_placed` events on both v1 and v2 sleeve_ids
- v2 sleeves produce `hedge_placed`, `exited_at_bid`, OR `hedge_and_exit_both_failed` events
- v2 sleeves do NOT produce `hedge_skipped_no_asks` (that's v1-only legacy path)
- Compare 24h metrics:
  ```sql
  SELECT
    CASE WHEN sleeve_id LIKE '%v2%' THEN 'v2' ELSE 'v1' END AS version,
    COUNT(*) AS n_resolutions,
    AVG((data->>'pnl_usd')::numeric) AS avg_pnl,
    SUM((data->>'pnl_usd')::numeric) AS total_pnl
  FROM trading.events
  WHERE kind='poly_updown_resolution'
    AND at > now() - interval '24 hours'
  GROUP BY version;
  ```

### 18-V2-04 — 7-day parity comparison (parallel to ops)

Daily report:
- v1 vs v2: PnL/day, hit rate, hedge-trigger rate, hedge-success rate, MaxDD over rolling 7d, mean PnL/trade
- Trip wire: if v2 underperforms v1 by >5pp ROI for 3 consecutive days, halt v2.
- After 7 days clean parity (v2 ≥ v1 on key metrics), promote v2 to production sleeves and retire v1.

### 18-V2-05 — Production cutover (½ day)

Once parity gates pass for 7 days:
1. Stop registering v1 sleeve controllers.
2. Rename v2 sleeve_ids: `poly_updown_v2_*` → `poly_updown_*` (or keep v2 namespace for clarity).
3. Update existing v1 documentation pointers to v2.
4. Archive v1 `_maybe_hedge_legacy` code (keep in git history but remove from active path).

**Total Phase 18.x v2 timeline:** 4–5 days dev + 7 days parity = ~12 days end-to-end.

---

## 7. Verification gates — what "good" looks like

After each phase, these SQL queries should give the expected outputs.

### 7.1 Bug-fix gate (after 18-V2-01)

| Test | SQL | Expected |
|---|---|---|
| Signals on dead markets | `SELECT COUNT(*) FROM trading.events e JOIN markets m ON m.condition_id = e.data->>'condition_id' WHERE e.kind='poly_updown_signal' AND e.at > now() - interval '6h' AND extract(epoch from e.at)::bigint > m.resolve_unix` | **0** |
| Tick-min ghost fills | `SELECT COUNT(*) FROM trading.events WHERE kind='poly_updown_signal' AND data->>'fill_price'='0.0010' AND at > now() - interval '6h'` | **0** |
| Realistic PnL magnitudes | `SELECT AVG(abs((data->>'pnl_usd')::numeric)) FROM trading.events WHERE kind='poly_updown_resolution' AND at > now() - interval '6h'` | **>$5** (was <$1) |
| Entry fill rate | `SELECT 100.0 * sum(case when data->>'fill_status'='filled' then 1 else 0 end) / count(*) FROM trading.events WHERE kind='poly_updown_signal' AND data->>'reason' IN ('order_placed','entry_rejected') AND at > now() - interval '6h'` | **>50%** (was 18%) |

### 7.2 v2 paper-smoke gate (after 18-V2-03)

| Test | SQL | Expected |
|---|---|---|
| v2 sleeves firing | `SELECT count(*) FROM trading.events WHERE sleeve_id LIKE 'poly_updown_v2_%' AND at > now() - interval '24h'` | **>500** (signals + resolutions, depending on volume mode setup) |
| HYBRID branches active | `SELECT data->>'reason' AS r, count(*) FROM trading.events WHERE sleeve_id LIKE 'poly_updown_v2_%' AND at > now() - interval '24h' GROUP BY r` | At least: `order_placed`, `hedge_placed`, `exited_at_bid` rows present |
| No legacy log spam | `journalctl -u tv-engine --since '24 hours ago' \| grep -c 'hedge_skipped_no_asks'` | **<10/day** (was 1000s/day) |

### 7.3 7-day parity gate (after 18-V2-04)

| Metric | v1 | v2 | Pass? |
|---|---|---|---|
| Trades/day | 800–900 | 800–900 | within ±10% |
| Hit rate (volume) | 56–62% | 56–62% | within ±3pp |
| Hit rate (sniper q10 5m) | 75–85% | 75–85% | within ±3pp |
| Mean PnL/trade ($25 stake) | $3–6 | **$5–9** | v2 > v1 by >$1 |
| Hedge-success rate | 30–50% | 30–50% | within ±5pp |
| BidExit rate (v2 only) | — | 5–20% | should be non-zero |
| MaxDD over 7d ($25 stake) | $300–500 | **$100–200** | v2 < v1 by >50% |
| 7d total PnL | baseline | v2 ≥ v1 | strict |

If v2 fails any single hard gate (mean PnL/trade, MaxDD, hedge-success), halt and investigate before promoting.

---

## 8. Rollback plan

If v2 metrics degrade or break:

### Soft rollback (keep code, disable sleeves)
```ini
# In env file
TV_POLY_V2_SLEEVES=                # empty list disables all v2 sleeves
```
Restart `tv-engine`. v1 sleeves continue running. v2 code path is dormant.

### Hard rollback (remove code)
```bash
git revert <v2-commit-range>
systemctl restart tv-engine
```
Bug fixes (#1, #6, #7, #8) are correctness fixes — they should NOT be reverted even if v2 rolls back. The bug-fix commits are in their own bundle for this reason (per §6 18-V2-01 wave).

### Partial rollback (HEDGE_HOLD on v2 sleeves)
```ini
TV_POLY_V2_HEDGE_POLICY=HEDGE_HOLD   # was HYBRID
```
v2 sleeves keep running but use the legacy policy. Useful if you want to isolate whether the bug-fixes alone are sufficient (v2 sleeves will then mirror v1 modulo sleeve namespace).

---

## 9. Out of scope (defer to v3+)

| Item | Why defer |
|---|---|
| Asset-stratified stakes (BTC=$100, ETH=$50, SOL=$25) | Phase 18.x Tier 2 — wait for v2 7-day parity gate to pass first |
| Disable SOL 5m sniper sleeve | Phase 18.x Tier 2 — same reason |
| `book_skew` overlay on BTC 5m | Phase 19 — needs 14-day forward-walk validation |
| Cross-asset BTC confirmation re-test | Phase 19 |
| Switch 15m sniper q20→q10 | **Don't ship** — q20 wins on $/day at fixed stake (per [TV_STRATEGY_TEST_AND_MODIFICATIONS.md](TV_STRATEGY_TEST_AND_MODIFICATIONS.md) §3 Defer table) |
| `mergePositions()` on-chain | Already deferred in v1 §10. HYBRID supersedes hedge-hold so merge is even less relevant. |
| Multicall3 redemption batching | Volume too low to justify; revisit at production stakes |

---

## 10. Files this guide modifies

| File | Change |
|---|---|
| `backend/app/strategies/polymarket/market_mapping.py` | Bug #1 — TTL by tf + active-market check |
| `backend/app/venues/polymarket/paper.py` | Bug #6 + #7 (constants), Bug #8 (`_simulate` USD-walk), NEW `place_exit_order`+`_simulate_sell` |
| `backend/app/venues/polymarket/client.py` | Bug #8 (`place_entry_order` API), NEW `place_exit_order` live impl |
| `backend/app/controllers/polymarket_updown.py` | Bug #8 caller, NEW `_maybe_hedge_hybrid`, `_fetch_own_book`, `hedge_policy` arg, `_audit(extras=...)`, `Slot.exit_*` fields, resolution handling for `exited_at_bid` |
| `backend/app/services/redemption_worker.py` | Skip `exited_at_bid` slots in `_scan_and_redeem` query |
| `backend/app/engine/main.py` (or sleeve-registration module) | Register `V2_SLEEVES` controllers with `hedge_policy="HYBRID"` |
| `/etc/tv/tradingvenue.env` | New env vars per §5 |
| `backend/tests/unit/test_paper_place_exit_order.py` | **NEW** — bid-walk fill simulator tests |
| `backend/tests/integration/test_hybrid_hedge_path.py` | **NEW** — end-to-end HYBRID transitions |
| `backend/tests/integration/test_resolution_for_exited_at_bid.py` | **NEW** — PnL accounting for bid-exited slots |

**One Alembic migration if needed:** add `'exited_at_bid'`, `'hedge_and_exit_both_failed'`, `'slot_opened'` to `trading.event_type` enum. Likely not needed since `kind` is `text` not enum — verify in your schema.

---

## 11. Backtest reference numbers (for parity reasoning)

Source: `polymarket_hedge_fallback.py` realfills sim, $25 stake, 5,742 markets Apr 22-27, 2026.

### Per-cell HYBRID @ healthy vs current-bug-state

| Cell | HEDGE_HOLD@0% (healthy) | HEDGE_HOLD@100% (bug state) | HYBRID@0% | HYBRID@100% |
|---|---:|---:|---:|---:|
| q10 5m ALL | +34.5% / DD-$137 | +13.6% / DD-$378 | **+34.5% / DD-$137** | **+36.4% / DD-$130** |
| q10 5m BTC | +41.5% | +29.5% | +41.5% | **+42.5%** |
| q10 5m ETH | +36.5% | +15.5% | +36.5% | **+37.8%** |
| q10 5m SOL | +25.5% | **−4.1%** | +25.5% | **+28.9%** |
| q20 15m ALL | +31.4% / DD-$58 | +22.5% / DD-$324 | +31.4% / DD-$58 | **+33.4% / DD-$45** |

The HYBRID@100% column is the **worst case** — what v2 should produce in production today (before bugs are fixed). Even there it ties or beats HEDGE_HOLD@0% (the best case for v1). After bugs ship, both v1 and v2 can fire hedges normally; v2 still wins by 1–3pp ROI from skipping the second-leg fee on hedged pairs.

### Sanity check — daily PnL projection at $25 stake

| Sleeve | Trades/day | Mean PnL (HYBRID) | $/day |
|---|---:|---:|---:|
| volume_5m_btc | 221 | +$3.61 | +$799 |
| volume_5m_eth | 224 | +$3.62 | +$811 |
| volume_5m_sol | 220 | +$2.96 | +$651 |
| volume_15m_btc | 65 | +$5.67 | +$369 |
| volume_15m_eth | 66 | +$3.68 | +$243 |
| volume_15m_sol | 62 | +$3.74 | +$232 |
| sniper_5m_btc (q10) | 22 | +$10.63 | +$234 |
| sniper_5m_eth (q10) | 22 | +$9.46 | +$208 |
| sniper_5m_sol (q10) | 22 | +$7.23 | +$159 |
| sniper_15m_btc (q20) | 13 | +$8.35 | +$108 |
| sniper_15m_eth (q20) | 13 | +$8.41 | +$109 |
| sniper_15m_sol (q20) | 12 | +$6.37 | +$76 |
| **Total** | **~1,000** | | **~$3,999/day** |

Subtract a 30–50% live-execution haircut → **~$2,000–2,800/day net** at $25 flat. After Tier 2 (asset-stratified stakes, defer SOL 5m sniper), this scales toward ~$4–8K/day net.

---

**End of guide.** All values, thresholds, and ranges from validated backtest evidence with realistic L10 book-walking sim + 4-policy fallback sweep + Rank-IC validation. The implementation surface is bounded: 4 bug-fix commits + 1 HYBRID-feature commit + 1 sleeve-registration commit + tests. No new venues, no new contracts, no new on-chain calls.
