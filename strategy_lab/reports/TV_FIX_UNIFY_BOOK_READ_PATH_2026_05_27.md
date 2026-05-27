# TV Spec — Unify Book-Read Path Across ALL Strategies (Global Normalization) — 2026-05-27

**PRIORITY**: HIGH — supersedes [TV_FIX_SYNTHETIC_FILLS_2026_05_27.md](./TV_FIX_SYNTHETIC_FILLS_2026_05_27.md). Same problem, more durable fix that also covers future sleeves.

**SCOPE**: All TradingVenue strategies that read Polymarket orderbooks. Standardize on the 3-tier book-read primitive currently used by the production momo controller.

**FOUND BY**: 2026-05-27 live verification — sniper_v5 controller reads `self._book_mirror.get(token_id)` directly and creates synthetic 0.5-vwap/10-share fills when the WS mirror is empty. The production momo controller (`poly_updown_loop.py`) uses `paper.get_orderbook_snapshot` which has a 3-tier WS → CLOB → Storedata fallback and never produces synthetic fills.

---

## The architectural divergence

Live evidence from `tv-engine.service` (today, 17:25-17:28 UTC):

```json
{"sleeve_id":"poly_updown_sol_5m_momo_HOLD_f7","won":true,"pnl_usd":"23.30",
 "event":"poly_updown_resolver.resolved"}
{"token_id":"...","source":"ws_mirror","has_asks":true,"has_bids":true,
 "event":"paper.book_fetched"}
{"token_id":"...","source":"clob","has_asks":true,"has_bids":true,
 "event":"paper.book_fetched"}     ← Tier-2 fallback firing when WS empty
```

Momo writes the `won` field directly + uses Tier-1/Tier-2 reads. Sniper_v5 today:

```json
{"sleeve_id":"poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6",
 "fill_vwap":0.5,"fill_shares":10.0,
 "l25_book_snapshot":{"up_vwap":null,"up_depth_usd":0.0,...},
 "outcome":"Up","pnl_usd":4.9}
```

Sniper_v5 placed a fire and recorded a win — but the UP book was empty. No CLOB fallback was attempted. The "win" is fictional.

### Side-by-side

| Aspect | momo (production) | sniper_v5 (current) |
|---|---|---|
| Book primitive | `paper.get_orderbook_snapshot(token_id)` | `self._book_mirror.get(token_id)` |
| Tier 1 (WS) | YES (in-memory <10ms) | YES |
| Tier 2 (CLOB HTTP) | YES (~50ms fallback) | **NO** |
| Tier 3 (Storedata) | YES (with critical alert) | **NO** |
| Empty-book behavior | Skip fire | Place synthetic `vwap=0.5, shares=10` |
| `book_source` in log | YES (`"source": "ws_mirror"` etc.) | **NO** |
| `won` field in resolution | YES (direct boolean) | **NO** (must derive) |

### Why momo is the canonical pattern

Per CLAUDE.md (TV root-level), Phase 18.6 Wave 1 landed 2026-05-21:
> Production tradingvenue is on **WS-only book reads (Tier-1 WS BookMirror)** per Phase 18.6 Wave 1. Live logs verified 2026-05-21 22:55 UTC: every `paper.book_fetched` event has `source: "ws_mirror"`. CLOB REST is now Tier-2 fallback (only when WS mirror is empty for a token); Storedata DB is Tier-3 disaster-fallback with CRITICAL alert.

This is the LOAD-BEARING architecture. Sniper_v5 must align.

---

## Mandate (going forward)

**Every strategy / controller that reads a Polymarket orderbook MUST use `paper.get_orderbook_snapshot(token_id)`** (or an equivalent shared primitive that goes through the same 3-tier dispatcher).

Direct reads of `self._book_mirror.get(token_id)` are **PROHIBITED** in new code. Existing direct reads (sniper_v5) must be migrated as part of this spec.

This applies to:
- ✅ `polymarket_sniper_v5.py` — current V5/V6/V7/V8 sleeves (MUST migrate)
- ✅ Any future sniper_v9+, sniper_v10+ controllers (MUST use)
- ✅ Any new strategy that uses Polymarket orderbooks (MUST use)
- ✅ `poly_updown_loop.py` — momo (already compliant, leave alone)
- ✅ `poly_maker_loop.py` — maker (audit; if already compliant, leave alone)

---

## Changes — concrete patch

### Change 1 — Inject `book_snapshot_fn` into `PolymarketSniperV5Controller`

File: `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`

Current constructor takes `book_mirror`. Replace with a callable that does the full 3-tier read:

```python
from collections.abc import Awaitable, Callable

class PolymarketSniperV5Controller:
    def __init__(
        self,
        *,
        panels: dict[str, Any],
        # OLD: book_mirror: BookMirror,
        # NEW:
        book_snapshot_fn: Callable[[int], Awaitable[dict]],
        shadow_logger: AsyncJsonlShadowLogger,
        settings: Settings,
        read_pool: Optional[Pool] = None,
        alert_service: Optional[AlertService] = None,
    ) -> None:
        ...
        self._book_snapshot_fn = book_snapshot_fn
        # ... rest of __init__ unchanged
```

At the engine main.py instantiation site (around line 2243):

```python
# OLD:
_sniper_v5_controller = PolymarketSniperV5Controller(
    panels=_sniper_v5_panels,
    book_mirror=paper.book_mirror,
    ...
)

# NEW:
_sniper_v5_controller = PolymarketSniperV5Controller(
    panels=_sniper_v5_panels,
    book_snapshot_fn=paper.get_orderbook_snapshot,   # bound method, 3-tier
    ...
)
```

### Change 2 — Rewrite `_simulate_l25_walk` (lines 610-654)

```python
async def _simulate_l25_walk(
    self, token_id: str, notional_usd: float,
) -> tuple[float, float, float, str] | None:
    """Walk asks for `notional_usd` using the canonical 3-tier book primitive.

    Returns (vwap, shares, latency_ms, book_source) on success, or None when
    no tier produced a tradeable book (caller must skip the fire with
    skip_reason="empty_book_all_tiers_failed").

    book_source is one of: "ws_mirror" | "clob" | "storedata" | "empty"
        - "empty" should not occur on success path; if returned, treat as None.
    """
    try:
        book = await self._book_snapshot_fn(int(token_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "sniper_v5.book_fetch_failed",
            token_id=token_id, error=str(exc),
        )
        return None

    book_source = str(book.get("_source", "empty"))
    if book_source == "empty" or book.get("_stale"):
        return None  # All 3 tiers failed or returned stale book

    asks = book.get("asks") or []
    if not asks:
        return None  # Tier returned book but no asks — can't buy

    spent_usd = 0.0
    spent_shares = 0.0
    for lvl in asks[:25]:
        try:
            price = float(lvl["price"])
            size = float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        lvl_notional = price * size
        remaining = notional_usd - spent_usd
        if lvl_notional >= remaining:
            shares_here = remaining / price
            spent_usd += shares_here * price
            spent_shares += shares_here
            break
        else:
            spent_usd += lvl_notional
            spent_shares += size

    if spent_shares <= 0:
        return None  # asks existed but couldn't accumulate any fill

    vwap = spent_usd / spent_shares
    return vwap, spent_shares, 0.0, book_source
```

**Behavioral change**: synthetic `(0.5, notional/0.5, 0.0)` placeholder is GONE. When book is empty/stale on all 3 tiers, returns `None` → controller skips the fire.

### Change 3 — Rewrite `_compute_l25_vwap_and_depth` (used by `_build_l25_snapshot`)

This is the spread-check pathway. Currently it walks the same `self._book_mirror` directly. Migrate to the same primitive:

```python
async def _compute_l25_vwap_and_depth(
    self, token_id: str, notional_usd: float = 25.0,
) -> tuple[float | None, float, str]:
    """Compute (vwap, total_depth_usd, book_source) for the buy-side L25 snapshot.

    Returns (None, 0.0, "empty") when no tier has a book. Caller surfaces
    this as the spread filter's `None`-spread skip path.
    """
    try:
        book = await self._book_snapshot_fn(int(token_id))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "sniper_v5.l25_snapshot_failed",
            token_id=token_id, error=str(exc),
        )
        return None, 0.0, "empty"

    book_source = str(book.get("_source", "empty"))
    if book_source == "empty" or book.get("_stale"):
        return None, 0.0, book_source

    asks = book.get("asks") or []
    if not asks:
        return None, 0.0, book_source

    spent_usd, spent_shares = 0.0, 0.0
    total_depth = 0.0
    for lvl in asks[:25]:
        try:
            price = float(lvl["price"])
            size = float(lvl["size"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or size <= 0:
            continue
        total_depth += price * size
        if spent_usd < notional_usd:
            remaining = notional_usd - spent_usd
            lvl_notional = price * size
            if lvl_notional >= remaining:
                spent_usd += remaining
                spent_shares += remaining / price
            else:
                spent_usd += lvl_notional
                spent_shares += size

    vwap = spent_usd / spent_shares if spent_shares > 0 else None
    return vwap, total_depth, book_source
```

### Change 4 — `_build_l25_snapshot` propagates source

```python
async def _build_l25_snapshot(
    self, up_token_id: str, dn_token_id: str,
) -> L25BookSnapshot:
    up_vwap, up_depth, up_src = await self._compute_l25_vwap_and_depth(up_token_id)
    dn_vwap, dn_depth, dn_src = await self._compute_l25_vwap_and_depth(dn_token_id)
    return L25BookSnapshot(
        up_vwap=up_vwap, dn_vwap=dn_vwap,
        up_depth_usd=up_depth, dn_depth_usd=dn_depth,
        up_book_source=up_src, dn_book_source=dn_src,    # NEW
    )
```

Add fields to `L25BookSnapshot`:

```python
@dataclass(slots=True)
class L25BookSnapshot:
    up_vwap: float | None = None
    dn_vwap: float | None = None
    up_depth_usd: float = 0.0
    dn_depth_usd: float = 0.0
    up_book_source: str = "empty"     # NEW: "ws_mirror" | "clob" | "storedata" | "empty"
    dn_book_source: str = "empty"     # NEW
```

### Change 5 — `FireResult` adds `book_source` + `won`

```python
@dataclass(slots=True)
class FireResult:
    sleeve_id: str
    direction: str
    all_gates_passed: bool
    skip_reason: str | None
    fill_vwap: float | None
    fill_shares: float | None
    fill_latency_ms: float | None
    placed_size_usd: float | None
    intended_size_usd: float
    book_source: str | None = None   # NEW: source of the book used for this fire's fill
    won: bool | None = None          # NEW: filled at resolve time
    l25_book_snapshot: L25BookSnapshot | None = None
    ...
```

### Change 6 — `eval_sleeve_fire` skip when all-tiers-empty

Currently the controller calls `_simulate_l25_walk(token_id, notional)`. After the fix, that returns `None` when no tier has a book. Add explicit skip:

```python
# Inside eval_sleeve_fire, after gates pass + sparse-book filter pass:
walk_result = await self._simulate_l25_walk(token_id, float(notional))
if walk_result is None:
    return FireResult(
        sleeve_id=sleeve.sleeve_id,
        direction=direction,
        all_gates_passed=False,
        skip_reason="empty_book_all_tiers_failed",
        fill_vwap=None,
        fill_shares=None,
        fill_latency_ms=None,
        placed_size_usd=None,
        intended_size_usd=float(notional),
        book_source="empty",
        l25_book_snapshot=l25_snap,
    )
fill_vwap, fill_shares, fill_latency, book_source = walk_result
# ... emit sleeve_fire_placed with all fields
```

### Change 7 — Shadow log §7 schema additions

Update `sniper_v5_shadow_log.py` to emit:

```python
log_row = {
    "event_type": event_type,
    "sleeve_id": fr.sleeve_id,
    ...
    "fill_vwap": fr.fill_vwap,
    "fill_shares": fr.fill_shares,
    "fill_latency_ms": fr.fill_latency_ms,
    "placed_size_usd": fr.placed_size_usd,
    "intended_size_usd": fr.intended_size_usd,
    "book_source": fr.book_source,           # NEW
    "won": fr.won,                            # NEW (only on sleeve_fire_resolved)
    "l25_book_snapshot": {
        "up_vwap": fr.l25_book_snapshot.up_vwap,
        "dn_vwap": fr.l25_book_snapshot.dn_vwap,
        "up_depth_usd": fr.l25_book_snapshot.up_depth_usd,
        "dn_depth_usd": fr.l25_book_snapshot.dn_depth_usd,
        "up_book_source": fr.l25_book_snapshot.up_book_source,   # NEW
        "dn_book_source": fr.l25_book_snapshot.dn_book_source,   # NEW
    },
    "outcome": fr.outcome,
    "pnl_usd": fr.pnl_usd,
    ...
}
```

### Change 8 — Populate `won` on resolution

In `book_event_for_resolution` (the method called after slot resolves):

```python
def book_event_for_resolution(self, sleeve, slot, fr, slot_end_us, outcome):
    if outcome is not None and fr.direction is not None:
        fr.won = outcome.strip().lower() == fr.direction.strip().lower()
    else:
        fr.won = None
    fr.outcome = outcome
    fr.pnl_usd = self._compute_pnl(fr, outcome)
    # emit sleeve_fire_resolved with won field
```

---

## Spread-filter fix lives here too

The original spread fix from [TV_FIX_SPREAD_FILTER_2026_05_27.md](./TV_FIX_SPREAD_FILTER_2026_05_27.md) is COMPATIBLE with this change — both share the same `_compute_l25_vwap_and_depth` rewrite. Apply both together:

In `_compute_l25_vwap_and_depth`, also expose `ap[0]` / `bp[0]` so the same-token bid-ask spread filter (per the spread doc) can be computed:

```python
# Inside the rewritten _compute_l25_vwap_and_depth:
ask0 = float(asks[0]["price"]) if asks else None
bids = book.get("bids") or []
bid0 = float(bids[0]["price"]) if bids else None
return (vwap, total_depth, book_source, ask0, bid0)
```

Update `L25BookSnapshot` to carry `up_ask0`, `up_bid0`, `dn_ask0`, `dn_bid0`. Then `_compute_spread(snap, direction)` uses `ask0 - bid0` per the spread-fix doc.

---

## Acceptance criteria

1. ✅ Grep for `self._book_mirror.get` in `polymarket_sniper_v5.py` returns ZERO matches after migration
2. ✅ Every `sleeve_fire_placed` event in JSONL has a `book_source ∈ {"ws_mirror", "clob", "storedata"}` (never `"empty"`)
3. ✅ Every `sleeve_fire_resolved` event has a `won` boolean field
4. ✅ Every `l25_book_snapshot` object has `up_book_source` and `dn_book_source` fields
5. ✅ Zero placed fires have `fill_vwap == 0.5 AND fill_shares == 10.0 AND book_source == "empty"` (the old synthetic fingerprint)
6. ✅ `paper.book_fetched` log events appear in `tv-engine.service` journal for sniper_v5 token IDs (proves the shared primitive is being used)
7. ✅ Unit test `test_simulate_l25_walk_all_tiers_empty_returns_none` passes
8. ✅ Integration test: replay today's empty-book sniper_v5 evals → expect Tier-2 (CLOB) to provide the book → fires place with real vwap, not 0.5 synthetic

---

## Tests

### Unit test
```python
async def test_simulate_l25_walk_uses_three_tier_path(controller, mock_paper):
    mock_paper.get_orderbook_snapshot.return_value = {
        "asks": [{"price": "0.72", "size": "20"}],
        "bids": [{"price": "0.70", "size": "15"}],
        "_source": "clob",  # WS empty, CLOB returned
    }
    result = await controller._simulate_l25_walk("0xabc", notional_usd=5.0)
    assert result is not None
    vwap, shares, latency_ms, book_source = result
    assert 0.71 <= vwap <= 0.72
    assert shares > 0
    assert book_source == "clob"

async def test_simulate_l25_walk_all_tiers_empty_returns_none(controller, mock_paper):
    mock_paper.get_orderbook_snapshot.return_value = {
        "bids": [], "asks": [], "ts": 0, "_source": "empty",
    }
    result = await controller._simulate_l25_walk("0xabc", notional_usd=5.0)
    assert result is None     # No synthetic — caller skips the fire
```

### Integration test
Use the BTC 15m sleeve fire from today's JSONL that had `up_vwap=None`. Replay through the fixed controller. Two outcomes possible:
- CLOB has a book → fire places with `book_source="clob"` and a real vwap (NOT 0.5)
- CLOB also empty → fire SKIPS with `skip_reason="empty_book_all_tiers_failed"`

Either way: no synthetic 0.5-vwap/10-share row in the new JSONL.

---

## Rollout order

This spec supersedes the previous synthetic-fills fix doc.

1. **First** (current): TV finishes V6/V7/V8 sleeve implementation
2. **Second**: TV applies THIS unified book-read fix to sniper_v5 controller (covers V5/V6/V7/V8 simultaneously since they share the controller)
3. **Third**: TV applies [spread filter fix](./TV_FIX_SPREAD_FILTER_2026_05_27.md) — easy now that L25BookSnapshot already carries `ask0`/`bid0` from Change 5 here
4. **Fourth**: TV applies [dashboard fix](./TV_FIX_DASHBOARD_2026_05_27.md) — uses new `book_source` + `won` + `placed_size_usd` fields
5. **Fifth**: 7-14d shadow validation at $5 stake on the now-clean data
6. **Sixth**: Ramp stake to $25 (operator decision based on validation metrics)

---

## What this fix delivers (operator-facing)

Once deployed:
- ✅ Every V5/V6/V7/V8 sleeve fire uses the same WS→CLOB→Storedata path as momo
- ✅ Zero fictional / synthetic fills polluting WR / PnL stats
- ✅ `book_source` field shows which tier answered (operator can quantify WS staleness vs CLOB usage)
- ✅ `won` field directly available — dashboard doesn't have to derive it
- ✅ Storedata Tier-3 critical alerts fire if WS+CLOB both fail (operator gets paged)
- ✅ Future sleeves (V9+) inherit this resilient architecture by construction — no per-version drift

---

## What this fix does NOT cover

- Backtest engine `strategy_lab/engine_v2.py` — separate problem. Backtest still uses 1Hz-subsampled L25 on disk. The spread-fix and CLAUDE.md update already address that.
- Maker strategy book reads — separate audit needed (presumed compliant since `poly_maker_loop.py` likely uses paper executor too, but verify before declaring done).
- Latency modeling — production has ~85ms latency from decision → fill (per CLAUDE.md). The fix above does NOT add latency modeling to paper-mode sniper_v5; that's a separate `apply_latency` config flag.

---

## Files referenced

Production code (VPS3):
- `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py` — primary target
- `/opt/tradingvenue/backend/app/venues/polymarket/paper.py` — `get_orderbook_snapshot` source (lines 214-260) + `_fetch_orderbook` 3-tier dispatcher (lines 260-345)
- `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py` — momo reference implementation (uses the right path already)
- `/opt/tradingvenue/backend/app/engine/main.py` — instantiation site for sniper_v5 controller (~line 2243)
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py` — all 56 sleeve definitions (V5+V6+V7+V8) — NO CHANGES NEEDED, controller change is sufficient

Spec doc cross-references:
- [TV_FIX_SPREAD_FILTER_2026_05_27.md](./TV_FIX_SPREAD_FILTER_2026_05_27.md) — spread metric (apply together)
- [TV_FIX_DASHBOARD_2026_05_27.md](./TV_FIX_DASHBOARD_2026_05_27.md) — dashboard reads new fields
- [TV_FIX_SYNTHETIC_FILLS_2026_05_27.md](./TV_FIX_SYNTHETIC_FILLS_2026_05_27.md) — **SUPERSEDED by this doc**

---

## END
