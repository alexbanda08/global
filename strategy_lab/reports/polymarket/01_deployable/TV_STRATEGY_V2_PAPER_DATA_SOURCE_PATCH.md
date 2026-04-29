# V2 Paper Executor — Live-CLOB Data Source Patch

**Audience:** TV agent on VPS3.
**Purpose:** fix the data-source mismatch where the V2 paper executor reads stale `orderbook_snapshots_v2` rows instead of the live Polymarket CLOB. This makes paper fills behave like production fills (real book at decision-time), eliminating backtest-vs-shadow divergence caused by the storedata writer lag.

**Supersedes:** §5 (paper.py executor) of [TV_STRATEGY_V2_VPS3_IMPLEMENTATION_GUIDE.md](TV_STRATEGY_V2_VPS3_IMPLEMENTATION_GUIDE.md). Everything else in that guide stays as-is.

---

## 1. Problem

Paper executor's `_fetch_orderbook(token_id)` reads:

```sql
SELECT timestamp_us, bid_price_0..9, bid_size_0..9, ask_price_0..9, ask_size_0..9
FROM public.orderbook_snapshots_v2
WHERE exchange='polymarket' AND asset_id=$1
ORDER BY timestamp_us DESC LIMIT 1
```

The storedata collector writes snapshots in batches with **~1–2s lag (typical) up to 5–10s under load**. Consequences:

- Paper fill `avg_price` reflects the book ~1.5s ago, not the book at decision time. Live production has no such lag — orders see the book at submission moment.
- Hedge `_maybe_hedge` reads a stale book, decides hedge ask is empty/thin, but the live book at that instant has asks. False `hedge_skipped_no_asks`.
- Inversely: stale book may show asks that are gone by the time a real order would arrive. False `hedge_placed`.
- Net: shadow PnL diverges from what production would have realized. The whole point of paper-mode (predict production behavior) is broken.

**The fix is to bypass the DB entirely for paper-mode book reads.** Use the live Polymarket CLOB.

---

## 2. Architecture change

### Before

```
Polymarket WS → storedata-collector → orderbook_snapshots_v2 (DB) ← TV paper.py → simulated fill
                                       ↑ ~1-2s lag                  ↑
                                                                  uses stale book
```

### After

```
Polymarket CLOB (REST or WS) → TV paper.py → simulated fill
                               ↑ live book at request time
```

The simulator logic (book-walking USD-notional consumption) is unchanged. Only the data source changes from DB query to live CLOB call.

---

## 3. Implementation

Replace `_fetch_orderbook` in `backend/app/venues/polymarket/paper.py`:

```python
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.constants import POLYGON

class PolyPaperExecutor:
    def __init__(
        self,
        settings: PolySettings,
        clob_client: ClobClient | None = None,   # NEW — live CLOB read client
        pg_pool: Any | None = None,              # kept only as fallback when explicitly enabled
        cache_ttl_seconds: int = 1,              # 1s — single on_tick cycle, no longer
        cache_max_size: int = 256,
        slippage_bps: float = 2.0,
        rest_timeout_s: float = 2.0,
        rest_retry_attempts: int = 2,
    ) -> None:
        self.settings = settings
        self._clob = clob_client or self._build_read_only_clob(settings)
        self._pool = pg_pool                     # only used if TV_POLY_PAPER_DB_FALLBACK=true
        self._ttl = cache_ttl_seconds
        self._max = cache_max_size
        self._slippage_bps = slippage_bps
        self._rest_timeout_s = rest_timeout_s
        self._rest_retry_attempts = rest_retry_attempts
        self._cache: OrderedDict[int, tuple[float, dict]] = OrderedDict()

    @staticmethod
    def _build_read_only_clob(settings: PolySettings) -> ClobClient:
        """Construct a read-only CLOB client. No private key needed for orderbook GETs."""
        return ClobClient(
            host=settings.clob_host,             # e.g. "https://clob.polymarket.com"
            chain_id=POLYGON,
            # No key/funder — read-only endpoints don't require auth
        )

    async def _fetch_orderbook(self, token_id: int) -> dict:
        """Fetch live orderbook for `token_id` directly from Polymarket CLOB.

        Returns a dict with 'bids', 'asks', 'ts' keyed identically to before so the
        rest of the simulator is unchanged. 'ts' is the timestamp at which we
        received the response (proxy for book-state-at-decision-time, since the
        live API serves the current book).
        """
        now = time.time()

        # Tiny cache: only spares duplicate calls within a single on_tick cycle.
        # TTL=1s means at most ~one cached read across the ~10s tick interval.
        if token_id in self._cache:
            ts, cached = self._cache[token_id]
            if now - ts < self._ttl:
                self._cache.move_to_end(token_id)
                return cached
            del self._cache[token_id]

        # Live REST call to CLOB. Wrapped in retry for transient 5xx/timeout.
        last_exc: Exception | None = None
        for attempt in range(self._rest_retry_attempts + 1):
            try:
                # py_clob_client_v2 is sync — wrap in to_thread to avoid blocking event loop
                resp = await asyncio.wait_for(
                    asyncio.to_thread(self._clob.get_order_book, str(token_id)),
                    timeout=self._rest_timeout_s,
                )
                book = self._normalize_clob_response(resp, ts_s=int(now))
                break
            except (asyncio.TimeoutError, Exception) as exc:
                last_exc = exc
                if attempt < self._rest_retry_attempts:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                # All retries exhausted
                log.warning("paper.clob_orderbook_fetch_failed",
                            token_id=str(token_id), error=str(exc))
                # Optional fallback to DB if explicitly enabled (debug only)
                if os.environ.get("TV_POLY_PAPER_DB_FALLBACK") == "true" and self._pool:
                    return await self._fetch_orderbook_from_db(token_id)
                # Default: return empty book → caller treats as "no liquidity"
                return {"bids": [], "asks": [], "ts": 0}

        self._cache[token_id] = (now, book)
        self._cache.move_to_end(token_id)
        while len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return book

    @staticmethod
    def _normalize_clob_response(resp: Any, ts_s: int) -> dict:
        """Convert py_clob_client_v2 OrderBookSummary to our internal dict shape.

        py_clob_client_v2.get_order_book returns an OrderBookSummary with:
          .bids: list[OrderSummary] each with .price, .size (strings)
          .asks: list[OrderSummary] each with .price, .size (strings)
        Bids are descending by price; asks ascending. We keep the same ordering.
        """
        def _level_list(side):
            out = []
            for level in side or []:
                px = getattr(level, "price", None)
                sz = getattr(level, "size", None)
                if px is None or sz is None:
                    continue
                try:
                    if float(px) <= 0 or float(sz) <= 0:
                        continue
                except (ValueError, TypeError):
                    continue
                out.append({"price": str(px), "size": str(sz)})
            return out

        return {
            "bids": _level_list(getattr(resp, "bids", [])),
            "asks": _level_list(getattr(resp, "asks", [])),
            "ts":   ts_s,
        }

    async def _fetch_orderbook_from_db(self, token_id: int) -> dict:
        """Legacy DB fallback. Only invoked when TV_POLY_PAPER_DB_FALLBACK=true.
        Kept for emergency rollback / debugging. NOT the production path.
        """
        # ... existing DB query body ...
```

**Everything else in `paper.py` (`_simulate`, `_simulate_sell`, `place_entry_order`, `place_exit_order`) is unchanged.** Only the source of `book` changes.

---

## 4. Configuration changes

In `/etc/tv/tradingvenue.env` on VPS3:

```ini
# Polymarket CLOB host (read-only path; no private key needed for GET /book)
TV_POLY_CLOB_HOST=https://clob.polymarket.com

# Paper executor — live-CLOB data source
TV_POLY_PAPER_BOOK_CACHE_TTL=1                # was 10 — drop further; live book is the source of truth
TV_POLY_PAPER_REST_TIMEOUT_S=2.0
TV_POLY_PAPER_REST_RETRY_ATTEMPTS=2

# Emergency fallback — only enable for debugging when CLOB API has an outage
TV_POLY_PAPER_DB_FALLBACK=false
```

`TV_POLY_PAPER_STALE_AFTER_SECONDS=30` is now **mostly inactive** because `book.ts` is set to `now()` on each live fetch — the staleness check at `_simulate` line ~204 will basically always pass. Keep the constant in code as a safety net (e.g. if a future change re-enables the DB path), but it shouldn't fire in normal operation.

---

## 5. Wiring into the controller

`PolymarketUpdownController` constructs the paper executor in dependency-injection style. Pass the CLOB client through:

```python
# In tv-engine/main.py (or wherever controllers are wired):
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.constants import POLYGON

# Build a read-only CLOB client once, share across all 12 controllers
clob_read = ClobClient(
    host=os.environ["TV_POLY_CLOB_HOST"],
    chain_id=POLYGON,
    # No key — read-only
)

paper_executor = PolyPaperExecutor(
    settings=poly_settings,
    clob_client=clob_read,
    pg_pool=pool,                 # kept for fallback only
    cache_ttl_seconds=int(os.environ.get("TV_POLY_PAPER_BOOK_CACHE_TTL", "1")),
    rest_timeout_s=float(os.environ.get("TV_POLY_PAPER_REST_TIMEOUT_S", "2.0")),
    rest_retry_attempts=int(os.environ.get("TV_POLY_PAPER_REST_RETRY_ATTEMPTS", "2")),
)
```

The same `clob_read` instance can also serve `_fetch_opposite_book` and `_fetch_own_book` in the controller — those currently delegate to `executor.get_orderbook_snapshot(token_id)`, which now hits the live CLOB.

---

## 6. Rate-limit math

Each open Slot generates:
- 1 hedge-tick book read every 10s → 360 reads/hour per slot

At the production target of ~60 concurrent open slots:
- 60 × 360 = **21,600 reads/hour** = **6 reads/sec average**, ~12/sec at peak when many ticks fire simultaneously.

Plus signal-time reads at each market `window_start`:
- ~860 markets/day across 6 sleeves volume mode = ~36/hour entry attempts → ~1 read/min average.

Polymarket CLOB free-tier limits are typically 100 RPS / IP. **We're at ~12% utilization at peak.** Comfortable.

If rate limits become an issue:
- Bump cache TTL to 2–3s (still vastly better than the DB path)
- Switch to WebSocket subscription on `book` channel (Phase 19)
- Run a dedicated ratelimit-aware queue with per-token coalescing

---

## 7. Verification — confirm the fix landed

After deploy, run on VPS3:

```sql
-- 1. Compare what paper executor "saw" vs what the snapshot writer wrote
-- The book_age_s field in audit events should drop from ~1-2s mean to <100ms.
SELECT
  AVG((data->>'book_age_s')::numeric) AS avg_book_age_s,
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY (data->>'book_age_s')::numeric) AS median,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY (data->>'book_age_s')::numeric) AS p95,
  COUNT(*) AS n
FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'book_age_s' IS NOT NULL
  AND at > now() - interval '6 hours';
-- Expected after patch: median ≈ 0–1, p95 < 5. (Was: median ≈ 1–2, p95 ≈ 8+.)

-- 2. hedge_skipped_no_asks rate should drop further (already low post-bug-fix)
SELECT
  COUNT(*) FILTER (WHERE data->>'reason' = 'hedge_skipped_no_asks') AS no_asks,
  COUNT(*) FILTER (WHERE data->>'reason' = 'hedge_placed') AS placed,
  COUNT(*) FILTER (WHERE data->>'reason' = 'exited_at_bid') AS bid_exits,
  COUNT(*) AS total_hedge_decisions
FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'reason' IN ('hedge_placed','hedge_skipped_no_asks','exited_at_bid','hedge_and_exit_both_failed')
  AND at > now() - interval '24 hours';
-- Expected: no_asks / total < 2%. Most failures (if any) should be exited_at_bid (bid was alive).

-- 3. CLOB fetch failure rate
-- Track via journalctl since these are warnings:
-- journalctl -u tv-engine --since '1 hour ago' | grep -c 'paper.clob_orderbook_fetch_failed'
-- Expected: < 10/hour. If >50/hour, REST timeouts are too aggressive — bump rest_timeout_s.
```

---

## 8. What this does NOT change

- **Live mode** (`PolymarketClient`) was already calling the CLOB directly — no change.
- **Storedata collector** keeps writing `orderbook_snapshots_v2` — used for backtest data + analytics. Just no longer in the paper-fill path.
- **Strategy logic** (signal, sniper threshold, hedge trigger, HYBRID exit branches) — unchanged.
- **Resolution accounting** — unchanged.
- **Redemption worker** — unchanged.

---

## 9. Rollback

If the live-CLOB path has issues (rate limits, API outage, latency spikes):

```ini
# Re-enable DB fallback (paper executor uses orderbook_snapshots_v2 again)
TV_POLY_PAPER_DB_FALLBACK=true
```

Restart `tv-engine`. Paper-mode will revert to the DB path (lagged but functional). Investigate CLOB issue, fix, then flip back to `false`.

This is a safety valve, not a long-term mode. Daily metrics will show the lag-induced divergence resurface immediately.

---

## 10. Files modified

| File | Change |
|---|---|
| `backend/app/venues/polymarket/paper.py` | `_fetch_orderbook` → live CLOB; new `_normalize_clob_response`, `_fetch_orderbook_from_db` (fallback); `__init__` adds `clob_client` arg |
| `backend/app/venues/polymarket/settings.py` | Add `clob_host` field (or env-driven default) |
| `backend/app/engine/main.py` (sleeve registration) | Pass `clob_client=ClobClient(host=...)` to `PolyPaperExecutor(...)` |
| `/etc/tv/tradingvenue.env` | New keys per §4; remove or lower `TV_POLY_PAPER_BOOK_CACHE_TTL` |

No new tests needed beyond updating any existing `test_paper_*` tests to mock `ClobClient.get_order_book` instead of the DB pool.

---

## 11. Why this matters for shadow→production parity

The whole purpose of running V2 in paper shadow mode is to predict what production live behavior will be. With the DB path, paper sees a book that's already 1-2s stale — production never does. So:

- A trade that paper accepts (because the stale book showed asks) might fail in live (asks gone).
- A trade that paper rejects (stale book showed empty asks) might succeed in live (asks present).
- Hedge decisions diverge similarly.

After this patch, paper sees the same book live would see. The only remaining gap is **execution time** (real orders take ~50–200ms to land; paper "fills" instantly off the snapshot). That gap is small and roughly symmetric — not the systematic bias the DB path introduces.

**Net effect:** post-patch, V2 shadow PnL becomes a credible forecast of V2 live PnL within the normal noise band. Pre-patch, it's contaminated by lag-driven false signals on both sides.

---

**End of patch.** ~50 LOC change in `paper.py` + 5 lines wiring. Should ship in a single commit. After deploy, the verification SQL in §7 should show book_age_s dropping by ~10-100× within an hour.
