# TV Agent Task — Fix opposite-book fetch (3-tier: CLOB → WS → Storedata)

**Priority:** P0 (production controller has been firing zero hedges for ≥ 16h)
**Generated:** 2026-05-06
**Source diagnosis:** `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md`
**Source matched-trade evidence:** `strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md`

---

## 1 · Problem statement

Across all 18 momo sleeves deployed at 2026-05-06 00:28 UTC, in the first 16h of paper trading:
- **0 hedges fired** out of 215 resolutions
- **5 partial-bid-exits fired** out of 215 (2.4%)
- **233 `poly_updown_hedge_skip` events**, ALL with `data.book_ts = 0` and `data.reason = "no_asks"`

Independent simulator (`strategy_lab/momo_realfill/match_shadow.py`) re-ran the EXACT SAME 221 markets shadow fired on, reading the orderbook from the L25 raw snapshots Storedata captured. **Realfill found 99.8% feasibility for both HEDGE and SELL** — opposite-side asks were present at the rev_bp trigger time in essentially every case.

**Per-trade gap quantified:**
- Shadow live: $+2.71 / trade
- Realfill on same trades: $+10.01 / trade
- **$+7.30 / trade left on the table** = $+1,612 over those 221 trades = ~$2,400/day at current fire rate

The strategy is generating real alpha; the controller is failing to capture it because HEDGE never fires. The book IS there — we're just not seeing it.

## 2 · Root cause (verified end-to-end)

### 2.1 — The skip path

`backend/app/controllers/polymarket_updown.py:2512`
```python
book = await self._fetch_opposite_book(slot, opposite_outcome)
if not book or not book.get("asks"):
    book_ts = int(book.get("ts", 0)) if book else 0
    await self._audit_hedge_skip(
        slot, reason="no_asks", bps=bps, book_ts=book_ts, ...
    )
```

Verified on VPS3:
```sql
SELECT COUNT(*) FILTER (WHERE (data->>'book_ts')::int = 0) AS zero,
       COUNT(*) AS total
FROM trading.events
WHERE kind='poly_updown_hedge_skip' AND sleeve_id ~ 'momo';
-- Result: zero=233, total=233 (100% empty)
```

### 2.2 — The fetch path returns empty

`backend/app/venues/polymarket/paper.py:236` `_fetch_orderbook()`:
```python
# Primary: CLOB /book HTTP.
if clob_attempted:
    book = await self._fetch_clob_orderbook(token_id)

# Fallback: Storedata snapshot (DISABLED by default in production).
if book is None and self._pool is not None:
    if not clob_attempted or self._db_fallback_enabled:
        book = await self._fetch_storedata_orderbook(token_id)

if book is None:
    return {"bids": [], "asks": [], "ts": 0}    # ← THE EMPTY BOOK
```

Result: every hedge attempt → CLOB returns empty/error → no fallback → controller emits empty book → "no_asks" skip → `held_no_hedge`.

### 2.3 — Storedata HAS the book CLOB lacked

For one verified hedge_skip case (slug `sol-updown-5m-1778058000`, opposite=Down/outcome_id=1, skip ts 2026-05-06 09:01:08 UTC):

```sql
SELECT to_timestamp(timestamp_us/1e6) AS ts,
       outcome_id, ask_price_0, ask_size_0, bid_price_0
FROM orderbook_snapshots_v2
WHERE slug='sol-updown-5m-1778058000'
  AND outcome_id = 1
  AND timestamp_us BETWEEN 1778058038000000 AND 1778058088000000
ORDER BY timestamp_us;

-- 10 snapshots in the 30s window before/around the skip:
-- 09:00:38 UTC: ask=$0.74 size=55, bid=$0.59
-- 09:00:39 UTC: ask=$0.64 size=15, bid=$0.59
-- 09:00:41 UTC: ask=$0.73 size=5,  bid=$0.64
-- ...etc, 98% of snapshots had valid ask_price_0 ∈ (0,1).
```

Storedata captured the asks via WebSocket. CLOB HTTP returned empty for the same token at the same wall-clock time.

## 3 · Required fix — 3-tier fallback (Tier-1 fix in CLOB itself)

The right architecture is **not** "Storedata as fallback for a buggy CLOB read." It is:

```
Tier 1: CLOB /book HTTP   ← FIX THIS so it actually returns asks (2.x)
Tier 2: Polymarket WS book mirror   ← NEW: subscribe at slot-creation time (3.x)
Tier 3: Storedata DB snapshots   ← LAST RESORT, time-bounded (4.x)
```

Each tier is independently invoked; we use the freshest non-empty book.

### Why this order

| Tier | Latency | Coverage | Stability | Cost |
|---|---|---|---|---|
| CLOB HTTP | ~50ms RTT | Should be 100% — when it works | Inconsistent on thin tokens | Per-call HTTP |
| Polymarket WS | < 50ms (local cache) | 100% if subscribed | Live, no rate limit | One sub per slot lifetime |
| Storedata DB | < 5ms (loopback) | 98% (verified) | Up to 30s stale | Free |

We currently have only Tier 1 enabled, and Tier 1 is broken for the opposite-side use case. Tier 2 is the right primary; Tier 3 is the safety net.

---

## 4 · Implementation plan — 4 commits

### Commit 1 — DIAGNOSE: instrument the CLOB fetch failure mode

**Purpose:** before we add fallbacks, document exactly *why* CLOB returns empty for opposite tokens. Could be:
- (a) Token actually has no resting orders at the moment (real empty book → fallback is correct)
- (b) CLOB endpoint format is wrong (we're hitting it with a bad token_id encoding)
- (c) CLOB endpoint returns 200 with `{"error": "..."}` for thin tokens (Polymarket-specific quirk)
- (d) HTTP timeouts or rate limits (transient)

**File:** `backend/app/venues/polymarket/paper.py` `_fetch_clob_orderbook()` (line ~270)

Add detailed structured logging on the empty path:
```python
# After the CLOB response is parsed:
if not isinstance(raw, dict) or "error" in raw:
    log.info(
        "paper.clob_book_unknown_token_or_error",
        token_id=str(token_id),
        err=str(raw.get("error")) if isinstance(raw, dict) else None,
        raw_keys=list(raw.keys()) if isinstance(raw, dict) else None,
        raw_preview=str(raw)[:200],
    )
    return None

# When we successfully parse but bids/asks are empty:
if not raw.get("bids") and not raw.get("asks"):
    log.info(
        "paper.clob_book_empty_response",
        token_id=str(token_id),
        market=raw.get("market"),
        asset_id=raw.get("asset_id"),
        timestamp=raw.get("timestamp"),
        full_response=str(raw)[:500],
    )
```

**Tests to add:**
```python
async def test_clob_empty_response_logs_full_payload(caplog):
    """When CLOB returns 200 with {} or {asks:[],bids:[]}, log enough to
    reverse-engineer the cause."""
```

**Commit message:**
```
chore(poly): instrument CLOB empty-response path

Phase 18.3 OPPOSITE_BOOK_FIX commit 1/4 — DIAGNOSIS.

The hedge mechanism is failing because _fetch_clob_orderbook returns
None (or a book with empty asks) for opposite-side tokens. Before
adding fallback layers, we need ground truth on what CLOB is actually
returning.

Adds structured logs at:
- "error" key path (already-handled but truncated logging)
- empty-bids-and-asks path (new)
- full raw response preview (200 chars) on both paths

After this lands and runs in shadow for 1h, we'll have data to choose
between (a) "book is genuinely empty, fallback to WS/DB is correct"
vs (b) "CLOB endpoint behavior bug, fix the request directly".

Refs:
  strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md
```

### Commit 2 — FIX TIER 1: make the CLOB read robust

After commit 1 has run for ~1h, you'll have the actual CLOB response shape. Then fix it directly:

**Common fix paths (pick whichever the diagnosis shows):**

**Case A — wrong token_id encoding:**
Polymarket CLOB token IDs are 78-char decimal strings stored as `bigint`. We may be sending them wrong. Verify by curl:
```bash
curl 'https://clob.polymarket.com/book?token_id=105993996...821848915797'
# Compare with what _fetch_clob_orderbook actually sends.
```

If wrong: cast to string explicitly, no scientific notation, no Python int conversion that loses precision.

**Case B — CLOB returns separate UP/DOWN books and we're querying wrong side:**
Each Polymarket binary market has TWO tokens: yes_token_id and no_token_id. The opposite-side token IS the right query — but the CLOB might require a different endpoint or different params for binary markets.

Look at: how Polymarket's official py-clob-client-v2 fetches orderbook (already in our deps). Use the SDK directly:

```python
from py_clob_client.client import ClobClient
# vs raw httpx — the SDK may know about binary-market quirks
```

**Case C — CLOB endpoint returns book on a different field name:**
e.g., it might return `{"orders": {...}}` instead of `{"bids":[],"asks":[]}` for some market types.

**Case D — rate-limit / 429:**
If we're hitting opposite-side books on every slot tick, we may be over-rate. Add a per-token cooldown.

**Files:**
- `backend/app/venues/polymarket/paper.py` `_fetch_clob_orderbook()` — fix the request/parse
- `backend/app/venues/polymarket/client.py` `get_orderbook_snapshot()` — same fix in non-paper path

**Tests to add:**
```python
async def test_clob_fetch_handles_binary_market_token():
    """Use a real Polymarket binary-market token_id (fixture). Verify
    we get back asks and bids, not empty."""

async def test_clob_fetch_returns_none_only_on_actual_empty_book():
    """A real-empty book (token with no resting orders) should still
    return {"bids":[],"asks":[],"ts":<now>} — NOT None — so the caller
    can distinguish 'no liquidity right now' from 'fetch failed'."""
```

**Commit message:**
```
fix(poly): correct CLOB /book request for binary-market opposite tokens

Phase 18.3 OPPOSITE_BOOK_FIX commit 2/4 — FIX TIER 1.

After commit 1's instrumentation showed [PASTE THE ROOT CAUSE FROM
THE LOGS], CLOB now correctly returns the opposite-side book for
binary markets.

Before: 100% empty responses for thinly-traded NO/YES sides
After:  [N]% non-empty (verify in shadow for 1h post-deploy)

Refs:
  strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md
```

### Commit 3 — ADD TIER 2: WS-driven opposite-book mirror

Even with a working CLOB, hedge decisions happen every 10s. HTTP RTT + Polymarket rate limits make pure-CLOB tight. Subscribe to the opposite-side WebSocket book stream the moment a slot opens, maintain a local mirror, and use that for hedge ticks.

**File 1:** `backend/app/venues/polymarket/market_data.py`

Add a `BookMirror` class that:
- Holds `dict[token_id, {bids, asks, ts}]`
- Has `subscribe(token_id)` and `unsubscribe(token_id)` methods
- Receives WS `book` and `price_change` messages, updates the dict
- Exposes `get(token_id) -> dict | None` (None = not subscribed; empty book = subscribed but no liquidity)

```python
class BookMirror:
    """Live L1-L25 book mirror via Polymarket WS book channel.

    One WS connection, multiplexed across all subscribed token_ids.
    Each subscribe call adds a token to the WS subscription message.

    Latency: < 10ms from Polymarket maker action to local mirror update
    Memory:  ~5KB per token (25 levels × 2 sides × ~100 bytes)

    Lifecycle: subscribe at slot creation, unsubscribe at slot resolution.
    """
    async def subscribe(self, token_id: str) -> None: ...
    async def unsubscribe(self, token_id: str) -> None: ...
    def get(self, token_id: str) -> dict | None:
        """Return current book, or None if not subscribed."""
```

**File 2:** `backend/app/venues/polymarket/paper.py`

Plumb `BookMirror` into `PolyPaperExecutor` constructor and use it in `_fetch_orderbook`:

```python
async def _fetch_orderbook(self, token_id: int) -> dict:
    # Tier 1: CLOB
    book = await self._fetch_clob_orderbook(token_id) if self._http else None

    # Tier 2: WS mirror (new)
    if book is None and self._book_mirror is not None:
        ws_book = self._book_mirror.get(str(token_id))
        if ws_book and (ws_book["asks"] or ws_book["bids"]):
            book = ws_book

    # Tier 3: Storedata fallback
    if book is None and self._pool is not None and self._db_fallback_enabled:
        book = await self._fetch_storedata_orderbook(token_id)

    return book or {"bids": [], "asks": [], "ts": 0}
```

**File 3:** `backend/app/controllers/polymarket_updown.py`

When a slot opens (already happens in `_open_slot` or similar), call:
```python
await self.book_mirror.subscribe(slot.no_token_id)  # if signal=UP, mirror NO
await self.book_mirror.subscribe(slot.yes_token_id)  # if signal=DOWN, mirror YES
```

When slot resolves: unsubscribe.

**Tests to add:**
```python
async def test_book_mirror_subscribe_then_get_returns_live_book():
    # mock WS publishes book updates, mirror sees them
    ...

async def test_paper_executor_uses_ws_mirror_when_clob_empty():
    # CLOB returns None, mirror has fresh book → executor returns mirror book
    ...
```

**Commit message:**
```
feat(poly): WS-driven opposite-book mirror as Tier 2 fallback

Phase 18.3 OPPOSITE_BOOK_FIX commit 3/4 — ADD TIER 2.

Even with a working CLOB (commit 2), hedge decisions happen every 10s
across many slots. HTTP RTT + Polymarket rate limits make pure-CLOB
tight under load. This commit adds a WS-driven local book mirror.

Architecture:
  Tier 1: CLOB HTTP /book (commit 2) — primary
  Tier 2: WS BookMirror (this commit) — fallback when CLOB transient
  Tier 3: Storedata snapshots (commit 4) — last resort

BookMirror subscribes to opposite-side tokens at slot creation,
maintains a local dict of {bids, asks, ts}, used by paper executor
when CLOB returns empty/None. Latency < 10ms, no rate limits.

Refs:
  strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md
```

### Commit 4 — ADD TIER 3: Storedata fallback (gated, last resort)

Default ON, but only used when both CLOB and WS mirror return empty/stale. Time-bounded to `STALE_AFTER_SECONDS`.

**File:** `backend/app/venues/polymarket/paper.py`

```python
def __init__(
    self,
    *,
    db_fallback_enabled: bool = True,  # was False
    ...
):
```

Update the inline doc:
```python
# Phase 18.3 OPPOSITE_BOOK_FIX: 3-tier fetch architecture.
#   Tier 1 (primary): CLOB HTTP /book
#   Tier 2 (fallback): WS BookMirror — < 10ms, no rate limits
#   Tier 3 (last resort): Storedata snapshots — up to 30s stale
# Storedata fallback is ON by default. Cost-benefit: 1-30s slippage
# on a hedge fill is dramatically less than missing the hedge entirely
# (verified 2026-05-06: 0 hedges fired in 215 resolutions while
# realfill on the same trades found 99.8% feasibility).
# Operator opt-out: TV_POLY_PAPER_DB_FALLBACK=false in env.
```

**Engine wiring:** `backend/app/engine/main.py`
```python
import os
db_fallback = os.getenv("TV_POLY_PAPER_DB_FALLBACK", "true").lower() in ("true", "1", "yes")
executor = PolyPaperExecutor(
    ...,
    db_fallback_enabled=db_fallback,
    book_mirror=book_mirror,  # from commit 3
)
```

**.env.example:**
```
# Polymarket paper executor: when both CLOB and WS BookMirror return
# empty for an opposite-side token, fall back to Storedata's WS-captured
# L25 snapshots (< 30s stale). Default true. Set false to disable.
TV_POLY_PAPER_DB_FALLBACK=true
```

**Tests:**
```python
async def test_three_tier_fallback_clob_empty_ws_empty_db_has_book():
    """All 3 tiers wired. CLOB→empty. WS mirror→empty. DB→has book.
    Executor returns DB book."""
    ...

async def test_three_tier_clob_ok_ws_skipped_db_skipped():
    """CLOB returns book. Tiers 2 and 3 not consulted."""
    ...
```

Add a structured log in `_fetch_orderbook` indicating which tier answered:
```python
log.info(
    "paper.book_fetched",
    token_id=str(token_id),
    source=tier_used,  # "clob" | "ws_mirror" | "storedata"
    age_s=now - ts,
)
```

And extend the audit payload in `polymarket_updown.py:2517`:
```python
await self._audit_hedge_skip(
    slot,
    reason="no_asks",
    book_ts=book_ts,
    book_age_s=...,
    book_source=book.get("_source") if book else None,  # NEW
    opposite_outcome=opposite_outcome,
)
```

**Commit message:**
```
feat(poly): Storedata DB fallback as Tier 3 (default on, env-overridable)

Phase 18.3 OPPOSITE_BOOK_FIX commit 4/4 — ADD TIER 3.

Closes the 3-tier architecture started in commits 2 + 3:
  Tier 1 (primary): CLOB HTTP — fixed in commit 2
  Tier 2 (fallback): WS BookMirror — added in commit 3
  Tier 3 (last resort): Storedata snapshots — this commit

Flips db_fallback_enabled default to True, wires TV_POLY_PAPER_DB_FALLBACK
env override, adds book_source telemetry to track which tier answered.

Production deploy:
- Set TV_POLY_PAPER_DB_FALLBACK=true in /etc/tradingvenue/.env
- Restart tv-engine
- Verify hedge fire rate climbs from 0% toward 30%+ within 24h

Refs:
  strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md
  strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md
```

---

## 5 · Validation criteria (post-deploy)

### 5.1 — within 1 hour
```sql
SELECT
  data->>'book_source' AS tier_used,
  COUNT(*) AS n,
  COUNT(*) FILTER (WHERE (data->>'book_ts')::int > 0) AS with_real_book
FROM trading.events
WHERE kind IN ('poly_updown_hedge_skip', 'poly_updown_resolution')
  AND sleeve_id ~ 'momo'
  AND at >= now() - interval '1 hour'
GROUP BY 1 ORDER BY 2 DESC;
```
- Pass: at least one tier other than `null` appears
- Pass: `with_real_book / n > 0.7`

### 5.2 — within 24 hours
```sql
SELECT sleeve_id,
       COUNT(*) FILTER (WHERE data->>'hedged' = 'true') AS hedged,
       COUNT(*) FILTER (WHERE data->>'partial_bid_exit' = 'true') AS partial_exit,
       COUNT(*) AS total
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND sleeve_id ~ 'momo'
  AND at >= now() - interval '24 hours'
GROUP BY sleeve_id ORDER BY 1;
```
- Pass: ≥ 6 of 18 sleeves have `hedged + partial_exit > 0`
- Pass: total exit-fire rate ≥ 30% on HEDGE/SELL sleeves (was ~3%)

### 5.3 — within 7 days
- Re-run `match_shadow.py` (in `strategy_lab/momo_realfill/`) on the new 7-day window
- Δ between shadow $/trade and realfill $/trade should drop from $7.30 toward < $2

### 5.4 — Tier-source distribution sanity
After 24h running, the `book_source` distribution across hedge events should look like:
- Tier 1 (CLOB): expected 70-90% if CLOB fix is good
- Tier 2 (WS mirror): expected 10-25% (catches CLOB transients)
- Tier 3 (Storedata): expected < 5% (only when both upstream sources fail)

If Tier 3 dominates → upstream is broken, Tier 2 not subscribed correctly, or CLOB bug not fully fixed. Alert.

## 6 · Rollback procedure

Each commit can be reverted independently:
- Commit 4: `TV_POLY_PAPER_DB_FALLBACK=false` (env-only, no revert needed)
- Commit 3: Revert WS subscription wiring; controller falls back to Tier 1+3
- Commit 2: Revert CLOB fix; controller relies entirely on Tier 2+3
- Commit 1: Logging only, safe to leave even on rollback

If hedge fire rate spikes anomalously (e.g., > 80% within 1h) and fills look weird:
```bash
# Disable fallbacks but keep CLOB
echo "TV_POLY_PAPER_DB_FALLBACK=false" >> /etc/tradingvenue/.env
# Disable WS mirror via constructor flag
# (would need a TV_POLY_BOOK_MIRROR=false too — add this flag in commit 3)
sudo systemctl restart tv-engine
```

## 7 · Files / locations summary

| Item | Location |
|---|---|
| Production controller | `backend/app/controllers/polymarket_updown.py` (3133 LOC) |
| Paper executor | `backend/app/venues/polymarket/paper.py` |
| Live client | `backend/app/venues/polymarket/client.py` (commit 2 mirrors here) |
| Market data / WS | `backend/app/venues/polymarket/market_data.py` (commit 3 adds BookMirror) |
| Engine wiring | `backend/app/engine/main.py` |
| Env file (VPS3) | `/etc/tradingvenue/.env` |
| New unit tests | `backend/tests/unit/test_paper_orderbook_3tier.py` |
| Investigation report | `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md` |
| Same-trade evidence | `strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md` |

## 8 · Out of scope (separate tickets)

- Entry-side slippage on 5m (production HOLD baseline still under-performs realfill HOLD by ~$13/trade on SOL_5m). Likely a different mechanism — entry book staleness vs CLOB pricing at fill time. Expected to mostly resolve once Tier 2 is also used for ENTRY (currently entry uses tier1 only).
- `STALE_AFTER_SECONDS = 30` may be too aggressive for thin opposite-side tokens. After 7 days of 3-tier data, revisit whether to widen to 60s for Tier 3 specifically.
- Duplicate hedge_skip events (5× same skip in 50s) — controller's tick loop polls and gets the same empty result; once fix lands, those will stop. Worth a follow-up to dedup audit events anyway.
