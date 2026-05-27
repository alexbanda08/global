# TV Fix Spec — Synthetic-Fill Placeholder Bug — 2026-05-27

> # 🛑 SUPERSEDED — DO NOT IMPLEMENT THIS DOC
> This fix has been **replaced** by a broader normalization spec:
> **[TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27.md](./TV_FIX_UNIFY_BOOK_READ_PATH_2026_05_27.md)**
>
> The new spec covers the same synthetic-fill problem AND aligns sniper_v5
> (V5/V6/V7/V8 + future sleeves) with the production momo's 3-tier book-read
> path. Implement the unified doc instead — it's a cleaner architectural fix
> that delivers all the same benefits.
>
> This doc is kept for reference but should NOT be implemented standalone.

**PRIORITY**: HIGH — synthetic fires pollute live WR / PnL with non-tradeable trades. Operator cannot trust live stats for stake-ramp decisions.

**SCOPE**: `polymarket_sniper_v5.py` controller, specifically `_simulate_l25_walk` (lines 610-654) and its callers.

**FOUND BY**: live verification 2026-05-27 — sleeve `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` produced a "win" with `l25_book_snapshot.up_vwap=None` (UP book completely empty) but `fill_vwap=0.5` (a placeholder). The +$4.90 PnL was computed against a fictional fill.

---

## The bug

`_simulate_l25_walk` in `polymarket_sniper_v5.py` lines 610-654 has **three fallback paths** that return a placeholder fill instead of refusing to fire:

```python
def _simulate_l25_walk(
    self, token_id: str, notional_usd: float,
) -> tuple[float, float, float]:
    """Simulate a buy-side L25 walk. Returns (vwap, shares, latency_ms)."""
    book = self._book_mirror.get(token_id) if self._book_mirror else None
    if not book:
        # FALLBACK 1: BookMirror returned nothing
        return 0.5, notional_usd / 0.5, 0.0
    asks = book.get("asks") or []
    if not asks:
        # FALLBACK 2: book has no asks (buy side empty)
        return 0.5, notional_usd / 0.5, 0.0
    spent_usd = 0.0
    spent_shares = 0.0
    for lvl in asks[:25]:
        ...
    if spent_shares <= 0:
        # FALLBACK 3: couldn't fill anything (all levels invalid)
        return 0.5, notional_usd / 0.5, 0.0
    vwap = spent_usd / spent_shares
    return vwap, spent_shares, 0.0
```

All 3 fallbacks return `(0.5, notional_usd / 0.5, 0.0)` → at $5 stake produces `fill_vwap=0.5, fill_shares=10.0`.

### Why this is dangerous

The controller treats the synthetic fill identically to a real fill:
- Emits `sleeve_fire_placed` event with `all_gates_passed=True, fill_vwap=0.5`
- Schedules resolution at slot_end
- On resolve, computes PnL as if we actually filled at 0.5
- Records the result in shadow stats — operator believes it's a real trade

In **live (non-paper) trading**, you cannot fill an order on an empty book. The synthetic win is **impossible to reproduce** when real money is on the line.

---

## Live evidence from production today (2026-05-27)

Today's V5 deploy placed 7 fires. **2 of 7 (28.6%)** were synthetic:

| Sleeve | Direction | Book up_vwap | Book up_depth | fill_vwap | fill_shares | Synthetic? |
|---|---|---:|---:|---:|---:|:-:|
| btc_15m_ema800_ribslp_hawkes_off840_v6 | UP | **None** | **$0.00** | **0.5** | **10.0** | ⚠ YES |
| sol_5m_rf_tr_partial_mid | UP | 0.953 | $3,124 | 0.77 | 6.49 | No |
| sol_5m_rf_tr_partial_mid | DOWN | 0.840 | $1,828 | 0.352 | 14.21 | No |
| sol_5m_rf_tr_partial_mid | UP | 0.980 | $1,952 | 0.92 | 5.43 | No |
| btc_15m_ema800_ribslp_hawkes_off840_v6 | DOWN | 0.291 | $1,985 | 0.822 | 6.08 | No |
| sol_5m_rf_tr_partial_mid | UP | 0.820 | $991 | 0.69 | 7.25 | No |
| eth_5m_ema200_vwap_regimerang_xa3_v7 | UP | 0.907 | $7,932 | 0.75 | 6.67 | No |

**Synthetic fingerprint**: `fill_vwap == 0.5` AND `fill_shares == 10.0` AND book snapshot for the buy side is `None` / `0.0`.

The synthetic fire resolved to "Up" matching direction "UP" → recorded as +$4.90 win. Without the fix, it inflates the BTC 15m sleeve's WR/PnL artificially.

---

## Frequency analysis from today's 6,538 evals

`sleeve_fire_eval` events with the BUY-SIDE book empty (where the controller would have placed a synthetic if all gates passed):

| Asset/TF family | Total evals | Buy-side book missing | Rate |
|---|---:|---:|---:|
| BTC 15m sleeves | ~256 | ~12-22 (UP missing 2, DOWN missing 0; some only_up/only_dn) | ~5-9% |
| BTC 5m sleeves | ~1,800 | ~120 (mixed only_up/only_dn) | ~7% |
| ETH 5m sleeves | ~1,400 | varies | low |
| SOL 5m sleeves | ~2,500 | low | low |

About **5-10% of buy-side-eligible fires** would be synthetic if gates passed. With low placement rate (7/6,538 today), 2 synthetic out of 7 placed is consistent.

After the spread filter fix lands ([TV_FIX_SPREAD_FILTER_2026_05_27.md](./TV_FIX_SPREAD_FILTER_2026_05_27.md)) and placement rate jumps to ~70-80%, synthetic-fire count will rise proportionally → must fix this before placements scale up.

---

## Fix — 3 options, recommendation = Option B

### Option A — Hard reject empty-book fires (strictest)
Change `_simulate_l25_walk` to return `None` instead of synthetic placeholder. Caller skips the fire entirely with `skip_reason="empty_book_buy_side"`.

**Pros**: zero synthetic fires in stats, matches what live trading would do
**Cons**: loses the "what would have happened if we COULD fill" signal

### Option B — Mark synthetic fires distinctly (RECOMMENDED)
Place the synthetic fire BUT flag it with a new `fill_method` field. Dashboard + analysis tools can filter / segregate.

**Pros**: keeps audit trail, lets us reason about post-hoc "what if book were deeper", excludes from primary WR/PnL
**Cons**: requires schema change + dashboard support

### Option C — Status quo + warn
Keep synthetic fires but log a WARNING on every synthetic placement. No schema change.

**Pros**: minimal code change
**Cons**: doesn't solve the polluted-stats problem; ops has to manually filter

---

## Recommended fix (Option B) — implementation

### Change 1 — `_simulate_l25_walk` signature

```python
def _simulate_l25_walk(
    self, token_id: str, notional_usd: float,
) -> tuple[float, float, float, str]:
    """Simulate a buy-side L25 walk. Returns (vwap, shares, latency_ms, fill_method).

    fill_method:
        "l25_walk"  -> real walk on populated asks
        "synthetic" -> book empty or unwalkable, vwap=0.5 placeholder
    """
    book = self._book_mirror.get(token_id) if self._book_mirror else None
    if not book:
        return 0.5, notional_usd / 0.5, 0.0, "synthetic"
    asks = book.get("asks") or []
    if not asks:
        return 0.5, notional_usd / 0.5, 0.0, "synthetic"
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
        return 0.5, notional_usd / 0.5, 0.0, "synthetic"
    vwap = spent_usd / spent_shares
    return vwap, spent_shares, 0.0, "l25_walk"
```

### Change 2 — caller (around line 330)

```python
# OLD:
fill_vwap, fill_shares, fill_latency = self._simulate_l25_walk(token_id, float(notional))

# NEW:
fill_vwap, fill_shares, fill_latency, fill_method = self._simulate_l25_walk(token_id, float(notional))
```

### Change 3 — `FireResult` dataclass

Add `fill_method` field:
```python
@dataclass(slots=True)
class FireResult:
    sleeve_id: str
    direction: str
    all_gates_passed: bool
    ...
    fill_vwap: float | None
    fill_shares: float | None
    fill_latency_ms: float | None
    fill_method: str | None = None    # NEW: "l25_walk" or "synthetic"
    ...
```

### Change 4 — Shadow log §7 schema

In the JSONL emit code, add `fill_method` to the row:
```python
log_row = {
    "event_type": "sleeve_fire_placed" | "sleeve_fire_resolved" | "sleeve_fire_eval",
    ...
    "fill_vwap": fr.fill_vwap,
    "fill_shares": fr.fill_shares,
    "fill_latency_ms": fr.fill_latency_ms,
    "fill_method": fr.fill_method,   # NEW
    ...
}
```

### Change 5 — controller decision policy (optional, ramping)

Add a config flag `reject_synthetic_fills: bool = False`. When True:
```python
if fill_method == "synthetic":
    return FireResult(
        all_gates_passed=False,
        skip_reason="empty_book_buy_side_synthetic_rejected",
        ...
    )
```

Operator can toggle this per ramp phase:
- Phase 1 ($5 stake): keep synthetic fires logged for analysis (flag=False)
- Phase 2 ($25 stake) onward: reject synthetic fires (flag=True) so live stats are clean

---

## Dashboard impact (see companion doc)

The dashboard fix doc [TV_FIX_DASHBOARD_2026_05_27.md](./TV_FIX_DASHBOARD_2026_05_27.md) needs to:
1. Read `fill_method` field when computing primary WR/PnL — exclude `synthetic` from primary stats
2. Show synthetic fires in a separate "Audit" view with a clear marker (e.g., "🔬 synthetic — would not fill live")
3. Display both: "Real-walk WR: X%" and "Including-synthetic WR: Y%" — operator sees the gap

---

## Tests

### Unit test — synthetic detection
```python
def test_simulate_l25_walk_empty_book_returns_synthetic():
    """When BookMirror has no book for token_id, fall back to synthetic placeholder."""
    controller = make_test_controller(book_mirror_returns=None)
    vwap, shares, latency, method = controller._simulate_l25_walk("0xabc", 5.0)
    assert vwap == 0.5
    assert shares == 10.0
    assert method == "synthetic"

def test_simulate_l25_walk_no_asks_returns_synthetic():
    controller = make_test_controller(book_mirror_returns={"asks": []})
    _, _, _, method = controller._simulate_l25_walk("0xabc", 5.0)
    assert method == "synthetic"

def test_simulate_l25_walk_real_book_returns_l25_walk():
    controller = make_test_controller(book_mirror_returns={
        "asks": [{"price": "0.7", "size": "10"}, {"price": "0.72", "size": "5"}],
    })
    vwap, shares, _, method = controller._simulate_l25_walk("0xabc", 5.0)
    assert 0.7 <= vwap < 0.72
    assert shares > 0
    assert method == "l25_walk"
```

### Integration test — replay yesterday's JSONL
Replay today's 7 placed fires through the fixed controller. Expect:
- 2 fires get `fill_method="synthetic"` (the BTC 15m fire 1, and any other empty-book fires)
- 5 fires get `fill_method="l25_walk"`
- All `fill_vwap` / `fill_shares` values match the original log exactly (the math is unchanged, only the new field is added)

---

## Acceptance criteria

1. ✅ JSONL `sleeve_fire_placed` and `sleeve_fire_resolved` events have a new `fill_method` field
2. ✅ Synthetic fires have `fill_method="synthetic"`, real walks have `fill_method="l25_walk"`
3. ✅ Existing `fill_vwap` / `fill_shares` math unchanged (no regression on real fills)
4. ✅ Dashboard excludes `synthetic` from primary WR/PnL after also implementing dashboard fix
5. ✅ Operator can toggle `reject_synthetic_fills` config flag to disable synthetic fires entirely when stake ramps to $25+

---

## Rollout order with related fixes

1. **First**: TV finishes V6/V7/V8 implementation (current work)
2. **Second**: apply spread filter fix ([TV_FIX_SPREAD_FILTER_2026_05_27.md](./TV_FIX_SPREAD_FILTER_2026_05_27.md)) — unblocks placements
3. **Third**: apply THIS synthetic-fill fix — adds `fill_method` field BEFORE placement rate scales up (so the influx of new placed fires is already tagged)
4. **Fourth**: apply dashboard fix ([TV_FIX_DASHBOARD_2026_05_27.md](./TV_FIX_DASHBOARD_2026_05_27.md)) — uses the new field for clean WR/PnL/entry-price display
5. **Fifth**: 7-14d shadow validation period with $5 stake
6. **Sixth**: enable `reject_synthetic_fills=True` + ramp stake to $25

---

## END
