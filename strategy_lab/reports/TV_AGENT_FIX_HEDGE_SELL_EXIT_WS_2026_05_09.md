# TV Agent: Fix HEDGE/SELL Exit-Side Book Fetches (WS, Not REST)

**Recipient:** TV agent on VPS3 (`/opt/tradingvenue`)
**Date:** 2026-05-09
**Severity:** HIGH — recovers an estimated **+$1,075/week** in PnL across momo v1 + v2 sleeves
**Read-only audit + targeted fix.** Do NOT touch entry-side code (already on WS). Targeting `_maybe_hedge` + `_maybe_sell_at_bid` only.

## Background — what we found in the lab

For each of 851 live momo v1+v2 resolutions in the last 7 days, we replayed the on_tick exit-policy logic against VPS2 WS L25 books at the same instant and compared to the actual production outcome.

Diagnostic results (full report: `strategy_lab/reports/MOMO_LIVE_VS_BACKTEST_2026_05_08.md`):

| | n | prod fires | bt predicts | gap |
|---|---:|---:|---:|---:|
| HEDGE (v1+v2) | 282 | 52 (18.4%) | 135 (47.9%) | 83 missed |
| **SELL (v1+v2)** | **287** | **5 (1.7%)** | **137 (47.7%)** | **132 missed** |

**rev_bp gate IS opening** in ~50% of trades (matches backtest expectations exactly — no anchor mismatch). **L1 book IS available** at 92%+ of gate-open instants per VPS2 WS data. Yet production still doesn't fire the exit in 236 of those 569 cases.

Root cause: the production controller's `_maybe_hedge` and `_maybe_sell_at_bid` paths fetch the book via `executor.get_orderbook_snapshot(token_id)` which still routes to REST CLOB (1-2s+ cache). When the WS feed shows liquidity, REST cache returns `book_ts=0` / empty. Production logs `poly_updown_hedge_skip` events with `reason='no_asks'` (~250 in the same 7d window), confirming REST cache misses while WS would have served valid books.

Why SELL is worse than HEDGE: HEDGE retries every on_tick (~10s), eventually hitting a fresh REST cache window. SELL doesn't retry — first sell-bid attempt sees empty book, falls through to chainlink, and the trade is lost.

## Pre-flight checks

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7
cd /opt/tradingvenue
```

### Confirm the asymmetry: entry-book on WS, exit-book on REST

Search for the on_tick book-fetch sites:
```bash
grep -nE "_maybe_hedge|_maybe_sell_at_bid|_fetch_opposite_book|get_orderbook_snapshot" \
  backend/app/controllers/polymarket_updown.py | head -20
```

Expect to find at least:
- `_fetch_opposite_book` calls `executor.get_orderbook_snapshot(opposite_token_id)` (HEDGE path)
- `_maybe_sell_at_bid` calls `_try_bid_exit` which also calls `executor.get_orderbook_snapshot(own_token_id)` (SELL path)

Now check the executor:
```bash
grep -nE "def get_orderbook_snapshot|def get_book|httpx|websocket|ws_book" \
  backend/app/venues/polymarket/*.py
```

If `get_orderbook_snapshot` still uses `httpx.get` to `/book?token_id=X` — that's the REST path. Even if entry-side `BarContext.book_snapshot_yes/no` was migrated to WS, the on_tick exit path is independent and probably still on REST.

### Verify with live data

```sql
-- Count hedge_skip events with book_ts=0 (REST cache miss) in last 24h
SELECT
  sleeve_id,
  data->>'reason' AS reason,
  data->>'book_ts' AS book_ts,
  COUNT(*) AS n
FROM trading.events
WHERE kind='poly_updown_hedge_skip'
  AND (sleeve_id LIKE '%_momo_%' OR sleeve_id LIKE '%_momo_v2_%')
  AND at > now() - interval '24 hours'
  AND data->>'book_ts' = '0'
GROUP BY 1, 2, 3
ORDER BY n DESC
LIMIT 30;
```

Each of these `book_ts=0` events is a REST cache miss while VPS2 WS data shows the book had liquidity.

## Fix 1 — Wire on_tick book fetches to WS

The WS subscription that already serves the entry-side `BarContext.book_snapshot_yes/no` should also serve the on_tick reads. Easiest path: expose a thin async accessor on the venue client (or wherever the WS state is held) that returns the latest in-memory snapshot for a given `token_id`, with the freshness it received.

### Sketch — new accessor

```python
# backend/app/venues/polymarket/ws_book_mirror.py  (or wherever the WS layer is now)

class PolymarketBookMirror:
    """In-memory mirror of WS-fed orderbook snapshots, keyed by token_id."""

    def __init__(self):
        self._books: dict[str, dict] = {}      # token_id -> {ts, bids, asks}
        self._lock = asyncio.Lock()

    async def update(self, token_id: str, snapshot: dict) -> None:
        async with self._lock:
            self._books[token_id] = snapshot   # snapshot has ts, bids, asks

    async def get(self, token_id: str) -> dict | None:
        """Return the latest WS snapshot for token_id, or None if not subscribed."""
        async with self._lock:
            return self._books.get(token_id)

    async def get_with_freshness(self, token_id: str, max_age_ms: int = 1000) -> dict | None:
        """Return snapshot only if its ts is within max_age_ms; else None."""
        snap = await self.get(token_id)
        if snap is None:
            return None
        age_ms = (time.time() * 1000) - int(snap.get("ts", 0))
        return snap if age_ms <= max_age_ms else None
```

### Sketch — controller swap

In `_fetch_opposite_book` (HEDGE path):
```python
async def _fetch_opposite_book(self, slot, opposite_outcome):
    opposite_token_id = await self._resolve_token_id(slot.condition_id, opposite_outcome)
    if opposite_token_id is None:
        return None
    # NEW: try WS mirror first (sub-50ms freshness)
    book = await self.book_mirror.get_with_freshness(opposite_token_id, max_age_ms=1000)
    if book is not None:
        return book
    # FALLBACK: existing REST path (kept as safety net)
    return await self.executor.get_orderbook_snapshot(opposite_token_id)
```

In `_try_bid_exit` (SELL path):
```python
async def _try_bid_exit(self, slot, bps, prior_branch):
    own_token_id = slot.yes_token_id if slot.signal == "UP" else slot.no_token_id
    # NEW: try WS mirror first
    book_own = await self.book_mirror.get_with_freshness(own_token_id, max_age_ms=1000)
    if book_own is None:
        book_own = await self.executor.get_orderbook_snapshot(own_token_id)
    # ... rest unchanged
```

### Subscription scope

Each open slot's two token_ids (yes + no) need to be subscribed for the slot's full holding window. Hook into the slot lifecycle:

```python
# When a slot is opened:
await self.book_mirror.subscribe(slot.yes_token_id)
await self.book_mirror.subscribe(slot.no_token_id)

# When a slot resolves or is pruned:
await self.book_mirror.unsubscribe(slot.yes_token_id)  # only if no other slot holds it
await self.book_mirror.unsubscribe(slot.no_token_id)
```

Reuse subscription dedup if the WS client doesn't already do it.

## Fix 2 — SELL retry on initial book-empty (independent of WS migration timing)

Even after Fix 1, transient WS gaps will happen. SELL should mirror HEDGE's retry pattern.

### Current behavior (`_maybe_sell_at_bid` → `_try_bid_exit`)

```python
# pseudo
async def _maybe_sell_at_bid(self, slot):
    if not reverted:
        return
    # one-shot:
    book = await self._fetch_own_book(slot)
    if not book or not book.get("bids"):
        await self._audit_hedge_skip(slot, reason="hedge_and_exit_both_failed")
        return
    # walk bids and exit ...
```

### Proposed behavior — retry on next 1-3 ticks

```python
async def _maybe_sell_at_bid(self, slot):
    if not reverted:
        return
    # Mark the slot as "sell-pending" with a retry budget.
    # The on_tick loop revisits and retries the bid-exit until either:
    #   - book becomes available and exit fires
    #   - retry budget exhausted (e.g. 3 ticks = 30s)
    #   - resolution time reached
    if not hasattr(slot, "_sell_pending_retries_left"):
        slot._sell_pending_retries_left = 3
    book = await self._fetch_own_book(slot)
    if not book or not book.get("bids"):
        slot._sell_pending_retries_left -= 1
        if slot._sell_pending_retries_left <= 0:
            await self._audit_hedge_skip(slot, reason="hedge_and_exit_both_failed_max_retries")
            slot._sell_pending = False
        return  # try again next tick
    # walk bids and exit
    ...
```

The HEDGE path already retries through the on_tick cadence (we've observed up to 6 retries on stuck SOL_15m positions). Make SELL match.

## Fix 3 — Audit logging

For post-fix A/B comparison, add these fields to existing event types:

### `poly_updown_resolution` (already partial)
- `book_source` — `'ws'` | `'rest'` | `'ws_then_rest'` (which path was used at the exit moment)
- `exit_book_age_ms` — age of the book snapshot used at exit decision time

### `poly_updown_hedge_skip`
- Already has `book_ts`, but it's `0` for REST cache misses. Add:
  - `book_source` — same as above
  - `ws_subscribed` — bool, was the token_id subscribed at all? Catches subscription-leak bugs.

These let us run a regression query post-deploy: "across last 24h, what % of HEDGE/SELL fires used WS vs REST, and what's the success rate of each".

## Validation criteria — 24h after deploy

| metric | current | target |
|---|---:|---:|
| HEDGE fire rate (across all momo v1+v2 HEDGE sleeves) | 18.4% | ≥ 35% |
| SELL fire rate (across all momo v1+v2 SELL sleeves) | 1.7% | ≥ 25% |
| `book_ts=0` in `hedge_skip` events | ~250/week | < 30/week |
| Net PnL across momo v2 sleeves over 24h | varies | ≥ +$30/day baseline lift |

If after 24h SELL fire rate is still < 10%, Fix 1 didn't take or WS subscription has a bug. Roll back Fix 1, keep Fix 2.

## Rollout

1. **PR 1** — code only, gated on `TV_POLY_HEDGE_SELL_USE_WS=false` env flag (default off):
   - Add `PolymarketBookMirror` class
   - Hook controller to call it as Fix 1 sketch
   - Add Fix 2 retry logic on SELL
   - Add Fix 3 audit fields
   - Unit tests for both paths

2. **PR 2** — flip env on VPS3:
   ```bash
   sed -i 's/^TV_POLY_HEDGE_SELL_USE_WS=.*/TV_POLY_HEDGE_SELL_USE_WS=true/' /etc/tv/tradingvenue.env
   systemctl restart tv-engine
   ```

3. **Monitor** the validation queries above for 24h.

## Kill switch

Same env flag: `TV_POLY_HEDGE_SELL_USE_WS=false` + `systemctl restart tv-engine` reverts to REST-only path. The existing REST executor stays unchanged so this is a clean toggle.

## Files affected

### Modified
- `backend/app/controllers/polymarket_updown.py` — `_fetch_opposite_book`, `_try_bid_exit`, `_maybe_sell_at_bid`
- `backend/app/venues/polymarket/__init__.py` (or wherever the executor is wired) — pass `book_mirror` into controller construction
- `/etc/tv/tradingvenue.env` — add `TV_POLY_HEDGE_SELL_USE_WS` flag

### New
- `backend/app/venues/polymarket/ws_book_mirror.py` (if not already present from the WS migration)
- `tests/controllers/test_polymarket_updown_ws_exit.py` — Fix 1 + Fix 2 unit tests

### No changes
- Entry-side code (already on WS — confirmed via lab xref)
- momo_v2 strategy class
- Sleeve registrations

## Reference data on this laptop

- 851 live trades cross-referenced: `data/v4/shadow_trades_2026_05_08/momo_v1v2_live.csv`
- L25 books at exit time: `data/v4/shadow_trades_2026_05_08/vps2_l25_{btc,eth,sol}.csv`
- Per-trade diagnosis (gate open + book available + actual exit): `data/v4/shadow_trades_2026_05_08/momo_live_vs_backtest_per_trade.csv`
- Diagnostic engine: `strategy_lab/meta_classifier/momo_live_vs_backtest_diagnose.py`
