# TV Fix Spec — Sniper Dashboard Display Bugs — 2026-05-27

**PRIORITY**: MEDIUM — operator can't read live performance correctly. Wrong WR/ROI/entry-price misleads ramp-up decisions.

**SCOPE**: TradingVenue dashboard (frontend/API) that reads `/var/log/tradingvenue/sniper_v5/*.jsonl` and renders the sniper sleeve table + recent-trades view.

**FOUND BY**: live verification 2026-05-27 — operator noticed sleeve `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` showing WR=0 + ROI=490% + missing entry price, while underlying log data was correct.

---

## Issue 1 — WR shows 0% on winning fires

### Symptom
Sleeve `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` fired UP, outcome resolved Up, PnL +$4.90 → dashboard shows **WR = 0%**.

### Root cause
JSONL `sleeve_fire_resolved` event has these fields:
```json
{
  "outcome": "Up",
  "direction": "UP",
  "pnl_usd": 4.9
}
```
There is **NO `won` boolean field** in the schema. Dashboard is likely looking for `won` and defaulting missing → False.

### Schema (verified from production JSONL today)
Fields present in `sleeve_fire_resolved`:
```
all_gates_passed, asset, condition_id, direction, event_type, fill_latency_ms,
fill_shares, fill_vwap, fire_offset_s, fire_us, gates_evaluated,
intended_size_usd, l25_book_snapshot, outcome, placed_size_usd, pnl_usd,
resolution_source, skip_reason, sleeve_id, slot_start_us, tf, ws_s
```
No `won`. No `pnl_pct`. No `is_win`.

### Fix
Dashboard must compute `won` from existing fields:
```python
def is_win(event: dict) -> bool:
    """A fire wins when the resolved outcome matches the fired direction."""
    outcome = (event.get("outcome") or "").strip().lower()
    direction = (event.get("direction") or "").strip().lower()
    # outcome is "Up" or "Down" (capitalized in production)
    # direction is "UP" or "DOWN" (uppercase in production)
    return outcome == direction
```

WR aggregation:
```python
wins = sum(1 for e in resolved_events if is_win(e))
wr_pct = (wins / len(resolved_events)) * 100 if resolved_events else None
```

### Verification
For `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` today:
- 2 resolved fires
- Fire 1: direction=UP, outcome=Up → WIN
- Fire 2: direction=DOWN, outcome=Down → WIN
- Expected WR = 100% (2/2)

---

## Issue 2 — ROI shows 490% instead of 98%

### Symptom
Sleeve `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` fire 1: PnL=$4.90, stake=$5 → dashboard shows **ROI = 490%**.

### Root cause
$4.90 / $5 = 98%. But $4.90 / $1 = 490%. Dashboard is dividing by **$1** (hardcoded) instead of `placed_size_usd`.

The 5× ratio is consistent — dashboard is treating each fire as a $1-stake event regardless of `intended_size_usd` / `placed_size_usd`.

### Fix
ROI per-fire:
```python
def compute_roi_pct(event: dict) -> float | None:
    stake = event.get("placed_size_usd") or event.get("intended_size_usd")
    pnl = event.get("pnl_usd")
    if stake is None or stake <= 0 or pnl is None:
        return None
    return (pnl / stake) * 100
```

Aggregate ROI:
```python
def compute_aggregate_roi(resolved: list[dict]) -> float | None:
    """Sum-of-PnL / sum-of-stake — NOT average of per-fire ROI."""
    total_stake = sum(e.get("placed_size_usd") or 0 for e in resolved)
    total_pnl = sum(e.get("pnl_usd") or 0 for e in resolved)
    if total_stake <= 0:
        return None
    return (total_pnl / total_stake) * 100
```

### Verification
For the BTC 15m fire 1: PnL=$4.90, placed_size_usd=$5 → ROI = (4.9/5)*100 = **98%** ✓

---

## Issue 3 — "Recent trades" view doesn't show entry price for some fires

### Symptom
For some recent fires the entry-price column is blank/missing. Other sleeves with healthy books show entry price correctly.

### Root cause
Dashboard is reading the entry price from `l25_book_snapshot.up_vwap` (or `dn_vwap`) — **the SNAPSHOT of the book at fire time**, NOT the **actual fill price**.

On synthetic fills (see [TV_FIX_SYNTHETIC_FILLS_2026_05_27.md](./TV_FIX_SYNTHETIC_FILLS_2026_05_27.md)), the book snapshot has `up_vwap=None` because the UP token book was empty. But the controller still placed the fire with a placeholder `fill_vwap=0.5`.

The correct entry-price field is **`fill_vwap`** — it's always populated when the fire was placed (`event_type=sleeve_fire_placed` or `sleeve_fire_resolved`).

### Verification from production JSONL today
Sleeve `poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6` fire 1:
- `fill_vwap: 0.5` ← entry price (always populated)
- `l25_book_snapshot.up_vwap: None` ← snapshot of book before fill (empty here)
- `l25_book_snapshot.dn_vwap: 0.0695` ← snapshot of DOWN book (populated)

Dashboard probably reads `l25_book_snapshot.up_vwap` for entry display → empty → no price shown.

### Fix
Read `fill_vwap` for entry price, not `l25_book_snapshot.*_vwap`:
```python
def get_entry_price(event: dict) -> float | None:
    """Entry price = where the fill actually happened.

    Always use fill_vwap (populated whenever event_type is sleeve_fire_placed
    or sleeve_fire_resolved). The l25_book_snapshot fields are the BOOK STATE
    at fire time — they go None when the book was empty on that side, but
    fill_vwap is always set for placed fires (may be a synthetic placeholder
    of 0.5 — see TV_FIX_SYNTHETIC_FILLS for that issue).
    """
    return event.get("fill_vwap")
```

Recent-trades column mapping should be:
| Display column | JSONL field | Notes |
|---|---|---|
| Slug | `slug` | — |
| Sleeve | `sleeve_id` | strip `poly_sniper_v5_` prefix for compactness |
| Direction | `direction` | UP / DOWN |
| Entry price | `fill_vwap` | NOT `l25_book_snapshot.up_vwap` |
| Shares | `fill_shares` | derived: `placed_size_usd / fill_vwap` |
| Stake | `placed_size_usd` | NOT 1.0 |
| Outcome | `outcome` | Up / Down |
| WIN/LOSS | derived: `outcome.lower() == direction.lower()` | NOT a stored field |
| PnL | `pnl_usd` | as-is |
| ROI | derived: `pnl_usd / placed_size_usd * 100` | NOT `pnl_usd / 1` |

---

## Issue 4 — "Random stake sizes" perception

### Operator-reported symptom
"Fires didn't use the $25 stake, they were random numbers."

### Audit finding from production JSONL today
- ALL 6,550 events have `intended_size_usd = 5.0` (uniform — NOT random)
- ALL 7 placed fires have `placed_size_usd = 5.0` (uniform — NOT random)
- Operator is correctly at **$5 ramp-start** (not $25 spec stake — operator chose to ramp from $5 before scaling up)

### Likely cause of the perception
Dashboard is probably displaying `fill_shares` as if it were the stake. `fill_shares = placed_size_usd / fill_vwap`, so for $5 stake:
- fill_vwap=0.50 → fill_shares=10.00
- fill_vwap=0.77 → fill_shares=6.49
- fill_vwap=0.92 → fill_shares=5.43
- fill_vwap=0.69 → fill_shares=7.25
- fill_vwap=0.82 → fill_shares=6.08

These look "random" (varying decimal numbers) but they are deterministic = $5 / fill_vwap. **The actual stake is uniformly $5.**

### Fix
Dashboard should display **`placed_size_usd`** in the stake column, not `fill_shares`. Add `fill_shares` as a separate column labeled "Shares" if useful for ops, but the primary $ stake field is `placed_size_usd`.

```python
{
  "stake_usd": event["placed_size_usd"],        # $5 — uniform across all fires
  "shares": event["fill_shares"],               # 5/fill_vwap — derived
  "fill_vwap": event["fill_vwap"],              # entry price
}
```

---

## Combined dashboard table — correct rendering for the BTC 15m fire 1

Using JSONL data verbatim:
```json
{
  "sleeve_id": "poly_sniper_v5_btc_15m_ema800_ribslp_hawkes_off840_v6",
  "slug": "btc-updown-15m-1779892200",
  "direction": "UP",
  "fill_vwap": 0.5,
  "fill_shares": 10.0,
  "intended_size_usd": 5.0,
  "placed_size_usd": 5.0,
  "outcome": "Up",
  "pnl_usd": 4.9
}
```

Should render as:
| Sleeve | Slug | Dir | Entry | Shares | Stake | Outcome | Win? | PnL | ROI |
|---|---|---|---|---:|---:|---|:-:|---:|---:|
| btc_15m_ema800_ribslp_hawkes_off840_v6 | btc-updown-15m-1779892200 | UP | 0.50 | 10.00 | $5.00 | Up | ✓ | +$4.90 | 98% |

---

## Acceptance criteria

1. ✅ Dashboard WR for the BTC 15m sleeve shows 100% (2 wins out of 2)
2. ✅ Dashboard ROI for fire 1 shows 98%, not 490%
3. ✅ Dashboard "recent trades" view shows `fill_vwap` as entry price (0.5 for synthetic, real walk price for others)
4. ✅ Dashboard stake column shows $5.00 uniformly (not the variable `fill_shares` numbers)
5. ✅ Aggregate ROI computed as `sum(pnl_usd) / sum(placed_size_usd)`, not average-of-per-fire-ratios

---

## Cross-reference

See companion fix doc [TV_FIX_SYNTHETIC_FILLS_2026_05_27.md](./TV_FIX_SYNTHETIC_FILLS_2026_05_27.md) for the **upstream** issue:
- Why some fires have empty book snapshots (`up_vwap=None`)
- Why the controller places a synthetic fill at `fill_vwap=0.5` when the book is empty
- Whether to keep those synthetic fires in stats at all (recommendation: mark them and exclude from primary WR/PnL, keep as audit trail)

Once the synthetic-fill fix lands, dashboard issue 3 becomes simpler — but reading `fill_vwap` is still the right pattern regardless.

---

## END
