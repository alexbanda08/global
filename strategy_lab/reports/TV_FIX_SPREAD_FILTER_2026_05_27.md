# TV Fix Spec — Sniper Spread Filter Mismatch (ALL VERSIONS V5/V6/V7/V8) — 2026-05-27

**PRIORITY**: HIGH — apply during or right after V6+V7+V8 sleeve implementation.

**SCOPE**: ALL controller versions. The bug is in one function (`_compute_spread`) in the only existing controller (`polymarket_sniper_v5.py` as of 2026-05-27). When you create V6/V7/V8 controllers, you MUST NOT copy the buggy `abs(up_vwap - (1 - dn_vwap))` formula. Best practice: extract `_compute_spread` to a shared utility module so all version-specific controllers inherit ONE definition.

**SEVERITY**: HIGH — V5 deployment had **0 placements in 1,184 evaluations today (0.0%)** because of this divergence. V6/V7/V8 will hit the same problem the moment they activate — they all share the spread filter concept since the spec sets `spread_filter` per sleeve in §0/§6 of all 4 deploy spec docs.

---

## Scope clarification

✅ **Applies to**:
- `polymarket_sniper_v5.py` (currently exists, deployed, 0 placements due to this bug)
- ANY V6/V7/V8 controller TV is about to create (don't copy-paste the buggy formula)
- ANY future round (V9+) controllers

✅ **Does NOT apply to**:
- `poly_updown_loop.py` (production momo controller — separate code path, separate spread logic if any)
- `poly_maker_loop.py` (mint-and-sell maker — different model entirely)
- V52 strategy files in `controllers/v52/` (legacy)

✅ **Test scope**: re-validate ALL sleeves from V5 + V6 + V7 + V8 spec docs. They all assume the same spread filter (same-token bid-ask, NOT cross-token arb).

---

## Recommended approach: extract to shared utility (DRY)

Create `/opt/tradingvenue/backend/app/controllers/_sniper_spread.py`:
```python
"""Shared spread filter logic for ALL sniper controllers (V5, V6, V7, V8, future).

CRITICAL: this is the SAME spread metric used by backtest engine_v2.fill_at_book
(strategy_lab/engine_v2.py:234). Live and backtest must produce the same accept/reject
decision for the same (slug, fire_us, direction) input — otherwise live PnL won't
match backtest projections.

History (2026-05-27): the original `_compute_spread` in polymarket_sniper_v5.py used
`abs(up_vwap - (1 - dn_vwap))` (cross-token arb consistency) which diverged from
backtest. 1,184 evals → 0 placements due to median cross-spread of 31% on real
books. Replaced by this same-token bid-ask formula matching backtest.
"""
from typing import Protocol

class L25SnapshotLike(Protocol):
    up_ask0: float | None
    up_bid0: float | None
    dn_ask0: float | None
    dn_bid0: float | None

def compute_spread(snap: L25SnapshotLike, direction: str) -> float | None:
    """Same-token best-ask minus best-bid on the side being bought.

    Identical formula to backtest engine_v2.fill_at_book (line 234):
        spread = ask0 - bid0
    where ask0, bid0 are top-of-book on the SAME token being bought (UP if
    direction=UP, DOWN if direction=DOWN).
    """
    if direction == "UP":
        ask0, bid0 = snap.up_ask0, snap.up_bid0
    else:
        ask0, bid0 = snap.dn_ask0, snap.dn_bid0
    if ask0 is None or bid0 is None:
        return None
    return ask0 - bid0
```

Then every controller (V5, V6, V7, V8, etc.) imports and uses it:
```python
from backend.app.controllers._sniper_spread import compute_spread

# inside eval_sleeve_fire():
spread = compute_spread(l25_snap, direction)
sf = float(sleeve.spread_filter)
if spread is not None and spread > sf:
    skip_reason = f"spread_bidask_too_wide_{spread:.4f}_>_{sf:.4f}"
    ...
```

This way the bug literally cannot recur in future versions — there's ONE definition.

---

## Problem

The live controller `_compute_spread` and the backtest engine `fill_at_book` use DIFFERENT definitions of "spread":

### Live (current — incorrect per spec intent)
File: `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`
Lines 508-516:
```python
@staticmethod
def _compute_spread(snap: L25BookSnapshot) -> float | None:
    """Spread = abs(up_vwap - (1 - dn_vwap)). None if either side missing.

    Polymarket binary markets have up + dn ≈ 1.0 in fair pricing; spread
    deviation = book-imbalance proxy used by spec §0 spread filter.
    """
    if snap.up_vwap is None or snap.dn_vwap is None:
        return None
    return abs(snap.up_vwap - (1.0 - snap.dn_vwap))
```

This is a **cross-token arbitrage** check: how much does the UP token vwap deviate from `1 - DOWN token vwap`. For an arb-free market this is 0; on thin books with wide bid-ask the L25-walked vwaps on both UP and DOWN land at high prices and sum to > 1.0.

### Backtest (correct per spec — source of truth)
File: `strategy_lab/engine_v2.py:234`
```python
ask0 = float(ap[0]) if (len(ap) and math.isfinite(ap[0])) else float("nan")
bid0 = float(bp[0]) if (len(bp) and math.isfinite(bp[0])) else float("nan")
if spread_filter is not None and math.isfinite(ask0) and math.isfinite(bid0):
    if (ask0 - bid0) > spread_filter:
        return None
```

This is a **same-token bid-ask** spread on the buy side. Standard liquidity check used throughout all V5-V8 backtest research.

### Why this matters

In production (verified 2026-05-27 from `/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl`):
- 1,184 evals had complete L25 book snapshots
- `up_vwap + dn_vwap` sum distribution: min=1.075, **median=1.31**, max=1.97
- 0/1184 (0.0%) passed the cross-token spread filter
- 83.3% had cross-spread > 0.20

If we changed the filter to backtest's same-token bid-ask definition, expected placement rate jumps to the same ~30-50% that the backtest research assumed.

---

## Fix

### Change 1 — `L25BookSnapshot` dataclass (add fields)

File: `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`

Locate the `L25BookSnapshot` dataclass (around line 90):
```python
@dataclass(slots=True)
class L25BookSnapshot:
    """L25-derived per-direction VWAP/depth snapshot used for spread + placement."""
    up_vwap: float | None = None
    dn_vwap: float | None = None
    up_depth_usd: float = 0.0
    dn_depth_usd: float = 0.0
```

**ADD** these fields:
```python
@dataclass(slots=True)
class L25BookSnapshot:
    """L25-derived per-direction VWAP/depth snapshot used for spread + placement."""
    up_vwap: float | None = None
    dn_vwap: float | None = None
    up_depth_usd: float = 0.0
    dn_depth_usd: float = 0.0
    # NEW: top-of-book for same-token bid-ask spread filter (matches backtest engine_v2)
    up_ask0: float | None = None
    up_bid0: float | None = None
    dn_ask0: float | None = None
    dn_bid0: float | None = None
```

### Change 2 — Populate the new fields in `_build_l25_snapshot`

Locate `_compute_l25_vwap_and_depth` (called at line 476-477) and `_build_l25_snapshot` constructor (line 479). Currently:
```python
up_vwap, up_depth = self._compute_l25_vwap_and_depth(up_book)
dn_vwap, dn_depth = self._compute_l25_vwap_and_depth(dn_book)
return L25BookSnapshot(
    up_vwap=up_vwap, dn_vwap=dn_vwap,
    up_depth_usd=up_depth, dn_depth_usd=dn_depth,
)
```

**CHANGE** to:
```python
up_vwap, up_depth = self._compute_l25_vwap_and_depth(up_book)
dn_vwap, dn_depth = self._compute_l25_vwap_and_depth(dn_book)
# Top-of-book extraction for same-token bid-ask spread filter
up_ask0 = up_book["ap"][0] if up_book and len(up_book["ap"]) else None
up_bid0 = up_book["bp"][0] if up_book and len(up_book["bp"]) else None
dn_ask0 = dn_book["ap"][0] if dn_book and len(dn_book["ap"]) else None
dn_bid0 = dn_book["bp"][0] if dn_book and len(dn_book["bp"]) else None
return L25BookSnapshot(
    up_vwap=up_vwap, dn_vwap=dn_vwap,
    up_depth_usd=up_depth, dn_depth_usd=dn_depth,
    up_ask0=up_ask0, up_bid0=up_bid0,
    dn_ask0=dn_ask0, dn_bid0=dn_bid0,
)
```

(Adapt the dict access pattern — `ap`/`bp` field names — to whatever the live `up_book`/`dn_book` shape is. Check `_compute_l25_vwap_and_depth` for the actual L25 structure.)

### Change 3 — Replace `_compute_spread` body

```python
@staticmethod
def _compute_spread(snap: L25BookSnapshot, direction: str) -> float | None:
    """Spread = same-token best-ask minus best-bid on the side being bought.

    Matches backtest engine_v2.fill_at_book line 234 exactly.
    Earlier (pre-2026-05-27) version used cross-token arb check
    `abs(up_vwap - (1 - dn_vwap))` which diverged from backtest and
    blocked 100% of fires on thin-inside books.

    Returns None if either ask0 or bid0 is missing on the chosen side.
    """
    if direction == "UP":
        ask0, bid0 = snap.up_ask0, snap.up_bid0
    else:
        ask0, bid0 = snap.dn_ask0, snap.dn_bid0
    if ask0 is None or bid0 is None:
        return None
    return ask0 - bid0
```

### Change 4 — Update the call site (around line 248)

Current:
```python
spread = self._compute_spread(l25_snap)
sf = float(sleeve.spread_filter)
if spread is not None and spread > sf:
    ...
```

**CHANGE** to pass `direction`:
```python
spread = self._compute_spread(l25_snap, direction)
sf = float(sleeve.spread_filter)
if spread is not None and spread > sf:
    ...
```

### Change 5 — Update shadow log §7 schema

In `_emit_shadow_log_event` or wherever the JSONL row is built, the snapshot fields `up_ask0`, `up_bid0`, `dn_ask0`, `dn_bid0` should be included so we have full audit trail. Replace:
```python
"l25_book_snapshot": {
    "up_vwap": fr.l25_book_snapshot.up_vwap,
    "dn_vwap": fr.l25_book_snapshot.dn_vwap,
    "up_depth_usd": ...,
    "dn_depth_usd": ...,
}
```

With:
```python
"l25_book_snapshot": {
    "up_vwap": fr.l25_book_snapshot.up_vwap,
    "dn_vwap": fr.l25_book_snapshot.dn_vwap,
    "up_depth_usd": fr.l25_book_snapshot.up_depth_usd,
    "dn_depth_usd": fr.l25_book_snapshot.dn_depth_usd,
    "up_ask0": fr.l25_book_snapshot.up_ask0,
    "up_bid0": fr.l25_book_snapshot.up_bid0,
    "dn_ask0": fr.l25_book_snapshot.dn_ask0,
    "dn_bid0": fr.l25_book_snapshot.dn_bid0,
    "cross_spread_old": (
        abs(fr.l25_book_snapshot.up_vwap - (1.0 - fr.l25_book_snapshot.dn_vwap))
        if (fr.l25_book_snapshot.up_vwap is not None
            and fr.l25_book_snapshot.dn_vwap is not None)
        else None
    ),
}
```

Keep `cross_spread_old` (the OLD metric value) in the log for historical comparison. This lets us re-analyze "what would the old filter have done" without needing source code archaeology.

### Change 6 — Update skip_reason text

Old:
```python
skip_reason=f"spread_too_wide_{spread:.4f}_>_{sf:.4f}"
```

New (clarifies which spread):
```python
skip_reason=f"spread_bidask_too_wide_{spread:.4f}_>_{sf:.4f}"
```

(So historical jsonl with `spread_too_wide_` are clearly distinguishable from post-fix `spread_bidask_too_wide_`.)

---

## Tests

### Unit test (add to `backend/tests/controllers/test_polymarket_sniper_v5.py`)

```python
def test_compute_spread_uses_same_token_bid_ask():
    """Spread filter must use bid-ask on side being bought, not cross-token arb."""
    snap = L25BookSnapshot(
        up_vwap=0.55, dn_vwap=0.55,    # walks to 0.55 each
        up_ask0=0.51, up_bid0=0.49,    # tight bid-ask on UP
        dn_ask0=0.51, dn_bid0=0.49,    # tight bid-ask on DOWN
    )
    # OLD cross-token spread = abs(0.55 - (1 - 0.55)) = 0.10 → would BLOCK at 0.02 filter
    # NEW same-token bid-ask = 0.51 - 0.49 = 0.02 → just at 0.02 filter (boundary)
    assert controller._compute_spread(snap, "UP") == pytest.approx(0.02, abs=1e-6)
    assert controller._compute_spread(snap, "DOWN") == pytest.approx(0.02, abs=1e-6)
```

### Integration test — re-eval on yesterday's blocked fires

After fix, replay the 1,184 evals from `/var/log/tradingvenue/sniper_v5/2026-05-27.jsonl` against the new logic:
- Expected: 30-50% pass spread filter (matching backtest assumption)
- Verify per-sleeve: no sleeve has 0 fires (sanity)
- Verify sleeve 06 (the only UP-only sleeve) still respects `g_depth_250_strict`

---

## Acceptance criteria

1. ✅ `pytest backend/tests/controllers/test_polymarket_sniper_v5.py` passes (new test included)
2. ✅ V5 live engine restart shows non-zero `sleeve_fire_placed` events within first hour
3. ✅ Shadow log JSONL includes `up_ask0`, `up_bid0`, `dn_ask0`, `dn_bid0`, `cross_spread_old` fields
4. ✅ Skip reason text changed from `spread_too_wide_` to `spread_bidask_too_wide_`
5. ✅ No change to V6/V7/V8 sleeve definitions (those keep firing as defined; the fix only changes which fires actually place)

---

## Rollout

1. **Phase 1**: apply changes 1-6 to `polymarket_sniper_v5.py`
2. **Phase 2**: deploy to VPS3, monitor first hour of V5+V6+V7+V8 placements
3. **Phase 3**: if placement rate matches backtest (~30-50% of evals), keep stake at $5 for 7d shadow validation
4. **Phase 4**: if 7d shadow WR/PnL matches backtest within ±20%, ramp stake to $25

If placement rate is STILL near zero after fix, dig deeper:
- Sparse-book filter (`min_book_events=25` in last 60s) may be the next blocker
- Check `book_event_count` deque in controller — log how many events are tracked per slug at fire_us

---

## Context for TV agent

- This bug was found via live verification on 2026-05-27 after V5 deployment
- Backtest engine `strategy_lab/engine_v2.py` is the canonical reference for what live should match
- All V6/V7/V8 sleeve specs assume the same spread filter as V5 — so this one fix unblocks the entire roster
- After this fix, V6/V7/V8 sleeves will start placing fires alongside V5
- Operator approved running ALL versions in shadow simultaneously for live comparison

DO NOT touch sleeve definitions, gate logic, or controller flow. Only change the spread filter calc + supporting snapshot fields + logging schema.

---

## END
