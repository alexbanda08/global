# TV Agent: Implementation Guide — Momentum v3 (Partial-Fill Exit Variant)

**Recipient:** TV agent on VPS3 (`/opt/tradingvenue`)
**Date:** 2026-05-09
**Goal:** Deploy **18 NEW shadow sleeves** under a NEW `strategy_mode="momo_v3"`. Identical signal pipeline to `momo_v2`; only difference is **partial-fill HEDGE / SELL exits** instead of v2's effectively-full-fill semantics.
**Coexists with:** `momo` (v1) AND `momo_v2`. All three run side-by-side. Do NOT remove anything.
**A/B target:** quantify whether partial-fill HEDGE/SELL beats full-fill on the same signal pipeline. Lab backtest on 7-day window shows +$175 marginal on HEDGE, $0 on SELL — small but worth verifying live.

---

## 0 · Why momo_v3 (delta from momo_v2)

| Aspect | momo_v2 | **momo_v3** |
|---|---|---|
| Signal anchor | `(ws-60, ws+60)` | same |
| Fire offset | `ws + 60s` (`t_plus_60` phase) | same |
| Q90 threshold cache | `_RET_2M_V2_SAMPLES_CACHE` | **shared with v2** (same anchor → same samples) |
| Book source | WS via `book_mirror` | same |
| **HEDGE_HOLD on partial** | skip if `shares_h < shares_e * 0.95` | **accept any `shares_h > 0`; settle remainder at chainlink** |
| **SELL_BID on partial** | skip if `shares_s < shares_e * 0.95` | **accept any `shares_s > 0`; settle `shares_e - shares_s` at chainlink** |
| Sleeve count | 18 | 18 |

**Lab evidence** (851 live trades replayed at L25 WS books, 2026-05-08 report):

| policy | mode | fire% | pnl_total | Δ vs v2 |
|---|---|---:|---:|---:|
| HEDGE | full-fill (v2) | 43.9% | −$975 | — |
| HEDGE | partial (v3) | 46.6% | −$800 | **+$175** |
| SELL | full-fill (v2) | 46.6% | −$838 | — |
| SELL | partial (v3) | 46.6% | −$838 | $0 |
| HOLD | — | 0% | −$382 | — |

The 18 partial-only HEDGE fires concentrate on `sol_5m` (thin SOL books). PnL is mixed per cell. Worth shipping for live A/B verification because the lab dataset window happened to be a losing regime where exit policies broadly underperformed HOLD; v3 may behave differently in profitable regimes.

---

## 1 · Pre-flight

### 1a · Confirm momo_v2 is healthy
```sql
SELECT sleeve_id, COUNT(*) FROM trading.events
WHERE kind='poly_updown_resolution' AND sleeve_id LIKE '%_momo_v2_%'
  AND at > now() - interval '24 hours'
GROUP BY 1 ORDER BY 1;
```
Should show ~18 rows. If not, fix v2 first; v3 inherits its plumbing.

### 1b · Confirm `book_mirror` is serving HEDGE/SELL
```sql
-- After 24h of post-WS-patch data:
SELECT data->>'book_source' AS src, COUNT(*) FROM trading.events
WHERE kind='poly_updown_resolution' AND sleeve_id LIKE '%_momo_v2_HEDGE'
  AND at > now() - interval '24 hours' GROUP BY 1;
```
Expect to see `'ws_mirror'` (or whatever the source label is) on the majority. If still `'rest'`, fix the v2 WS wiring before v3 — v3 inherits it.

---

## 2 · Strategy class — `MomoV3Strategy`

Suggested location: `backend/app/strategies/polymarket/momo_v3.py`.

Identical signal logic to `MomoV2Strategy`. Only `name = "momo_v3"` differs. The partial-fill behavior lives in the controller's exit paths, not in the strategy class.

```python
"""MomoV3Strategy — same signal as v2, partial-fill HEDGE/SELL semantics."""
from __future__ import annotations
import math

from backend.app.strategies.polymarket.base import (
    PolymarketBinaryStrategy, SignalResult,
)


class MomoV3Strategy(PolymarketBinaryStrategy):
    """Top-10% |ret_2m| gate at ws+60s. Same as MomoV2Strategy.

    The v3 difference is in the controller's exit paths (HEDGE/SELL accept
    any positive partial fill). Strategy class is identical to v2.
    """

    name = "momo_v3"

    def signal(self, bars, config=None, aux=None) -> SignalResult:
        if aux is None:
            return "NONE"
        if aux.get("bar_ctx_phase") != "t_plus_60":
            return "NONE"
        ret_2m = aux.get("ret_2m")
        if ret_2m is None or not math.isfinite(ret_2m):
            return "NONE"
        thr = aux.get("abs_ret_2m_threshold")
        if thr is None or abs(ret_2m) < thr:
            return "NONE"
        return "UP" if ret_2m > 0 else "DOWN"


__all__ = ["MomoV3Strategy"]
```

---

## 3 · Controller changes — `polymarket_updown.py`

### 3a · Register `momo_v3` strategy mode

```python
_valid_strategy_modes = (
    "volume",
    "sniper",
    "v3", "v3_1", "v3_2", "v3_3",
    "v4",
    "momo",
    "momo_v2",
    "momo_v3",                    # NEW
    "inverse_volume_night",
    "inverse_sol_sniper",
    "inverse_sniper_down",
)
```

### 3b · Reuse `_build_signal_aux` from momo_v2

```python
elif self.strategy_mode in ("momo_v2", "momo_v3"):
    # identical aux shape — same anchor, same threshold cache
    ...
```

The `_RET_2M_V2_*` threshold cache is shared. v3 reads the same q90 thresholds.

### 3c · Partial-fill HEDGE in `_maybe_hedge`

The current production `_maybe_hedge` uses `book_walk_fill(opposite_asks, target_h_usd)` and accepts whatever fills (already partial-friendly at the walk level). The implicit "≥95% required" came from the original `exit_policy_tier1.py` lab logic; verify production doesn't have an equivalent skip.

If production already accepts any `shares_h > 0`, **no controller change is needed for HEDGE — momo_v3 = momo_v2 on HEDGE.**

If production has any of these patterns, add a v3 branch that bypasses them:

```python
# Hypothetical production gate to look for and bypass on momo_v3:
if shares_h < shares_e * 0.95 and not under_h:
    # production: re-walk to top off
    vwap_h, shares_h, usd_h, _, under_h = book_walk_fill(...)
    if shares_h < shares_e * 0.5:
        # production: skip if < 50%
        return  # ← v3 should NOT skip here
```

For v3, replace any such skip with: "log the partial fill, write `hedge_placed_partial` audit, settle remainder at chainlink."

### 3d · Partial-fill SELL in `_try_bid_exit`

`_try_bid_exit` docstring already says *"Returns True iff the sell filled (any partial counts)"* — partial is the documented behavior. **Likely no change needed; verify by reading the actual fill threshold check in the function body.**

If you find a check like:
```python
if filled_shares < entry_shares * 0.95:
    slot.status = "held_no_hedge_no_exit"
    return False
```
remove it for `momo_v3` only (gate behind `self.strategy_mode == "momo_v3"`).

### 3e · Audit-event additions

For both HEDGE and SELL on momo_v3, ALWAYS write the audit row even on partial. Add fields:
- `partial_fill: bool` (true iff `shares_filled < entry_shares * 0.95`)
- `shares_filled_pct: float` (e.g. 0.73 for 73% fill)
- `chainlink_settled_qty: numeric` (= entry_shares − shares_filled, the remainder going to chainlink)
- `chainlink_settled_pnl: numeric` (computed at resolution time)

This lets the lab analyzer cleanly separate partial from full fills in the post-deploy A/B.

---

## 4 · Sleeve registration

```python
MOMO_V3_SLEEVES = [
    ("btc", "5m",  "HOLD_ONLY"),  ("btc", "5m",  "HEDGE_HOLD"),  ("btc", "5m",  "SELL_BID"),
    ("btc", "15m", "HOLD_ONLY"),  ("btc", "15m", "HEDGE_HOLD"),  ("btc", "15m", "SELL_BID"),
    ("eth", "5m",  "HOLD_ONLY"),  ("eth", "5m",  "HEDGE_HOLD"),  ("eth", "5m",  "SELL_BID"),
    ("eth", "15m", "HOLD_ONLY"),  ("eth", "15m", "HEDGE_HOLD"),  ("eth", "15m", "SELL_BID"),
    ("sol", "5m",  "HOLD_ONLY"),  ("sol", "5m",  "HEDGE_HOLD"),  ("sol", "5m",  "SELL_BID"),
    ("sol", "15m", "HOLD_ONLY"),  ("sol", "15m", "HEDGE_HOLD"),  ("sol", "15m", "SELL_BID"),
]

for asset, tf, hp in MOMO_V3_SLEEVES:
    register(PolymarketUpDownController(
        sleeve_id=f"poly_updown_{asset}_{tf}_momo_v3_{_HEDGE_POLICY_SUFFIX[hp]}",
        symbol=asset.upper(),
        tf=tf,
        strategy_mode="momo_v3",
        hedge_policy=hp,
        notional_usd=Decimal("25"),
        mode="paper",
    ))
```

Sleeve_id pattern: `poly_updown_<sym>_<tf>_momo_v3_<HOLD|HEDGE|SELL>`.

**Total slot budget**: 18 (v1) + 18 (v2) + 18 (v3) + ~35 (others) = **89 worst case**. If sequential dispatch latency exceeds 2s on a v3 fire, parallelize per (sym, tf) — same risk as v2 spec §5.

### Note on `_HEDGE_POLICY_SUFFIX` (sleeve-id naming)

Reuse the same suffix mapping as v1/v2 — **`HOLD_ONLY → HOLD`**, **`HEDGE_HOLD → HEDGE`**, **`SELL_BID → SELL`**. The HOLD sleeve in v3 is functionally identical to v2's HOLD (no exit policy intervention) but kept for clean A/B accounting.

---

## 5 · New env vars

```bash
TV_POLY_MOMO_V3_ENABLED=true
TV_POLY_MOMO_V3_PARTIAL_FILL_HEDGE=true   # accept any positive shares_h
TV_POLY_MOMO_V3_PARTIAL_FILL_SELL=true    # accept any positive shares_s
TV_POLY_MOMO_V3_NOTIONAL_USD=25
TV_POLY_MOMO_V3_REV_BP=5                  # same as v2

# All other settings inherit from v2 (gate q90, lookback 14d, t_plus_60, etc.)
# Append to comma-list:
TV_POLY_STRATEGY_MODES=...,momo,momo_v2,momo_v3
```

---

## 6 · Audit-event schema (extension)

In addition to all existing v2 fields, momo_v3 resolutions include:

```json
{
  "sleeve_id": "poly_updown_btc_5m_momo_v3_HEDGE",
  "data": {
    "...": "all v2 fields",
    "partial_fill": true,
    "shares_filled_pct": 0.73,
    "chainlink_settled_qty": "13.5",
    "chainlink_settled_pnl": "-13.50",
    "hedge_partial_at_t_plus": 90
  }
}
```

The lab `momo_v3_shadow_analyzer.py` (parallel to existing analyzers) will compute partial-vs-full delta per cell.

---

## 7 · Validation criteria

After **7 days** of v3 paper running alongside v2:

| Pass | Conditional | Fail |
|---|---|---|
| v3 HEDGE fire rate ≥ v2 HEDGE fire rate (more fires = partial helps) | within 5% | v3 fires fewer than v2 |
| v3 HEDGE pnl/trade ≥ v2 HEDGE pnl/trade − $1 | within $0.50 | v3 worse than v2 by > $2 |
| v3 SELL fire rate = v2 SELL fire rate (lab predicts no change) | small delta | unexpected divergence |
| v3 partial-only HEDGE fires (i.e. fires v2 would have skipped) ≥ 5/day | 1-5/day | 0/day |

If after 7d v3 shows clear improvement on HEDGE → consider promoting to default and deprecating v2's full-fill behavior. If neutral or worse → kill switch and document.

---

## 8 · Concurrency / ContextVar

Same as v2 — v3 inherits the ContextVar isolation pattern. Add one unit test mirroring the v2 test:

```python
# tests/controllers/test_polymarket_updown_momo_v3.py
def test_momo_v3_bar_ctx_isolated_across_concurrent_tasks():
    # same shape as test_momo_v2_bar_ctx_isolated...
```

Plus dedicated v3 tests:

```python
def test_momo_v3_hedge_accepts_partial_fill():
    """Mock opposite-asks book with only 50% of needed shares; verify hedge fires
       and audit row reflects partial_fill=true."""
def test_momo_v3_sell_accepts_partial_fill():
    """Same shape for SELL_BID."""
def test_momo_v2_still_skips_partial():
    """Sanity: same scenario on v2 controller still skips."""
```

---

## 9 · Rollout sequence

1. **PR 1 — code only, gated on `TV_POLY_MOMO_V3_ENABLED=false`**:
   - Add `MomoV3Strategy`
   - Extend `_valid_strategy_modes`
   - Extend `_build_signal_aux` to include `momo_v3` in the v2 branch
   - Add partial-fill branches in `_maybe_hedge` and `_try_bid_exit` gated on `self.strategy_mode == "momo_v3"`
   - Add audit fields
   - Add tests
   - CI green

2. **PR 2 — flip env on VPS3**:
   ```bash
   ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
     "sed -i 's/^TV_POLY_MOMO_V3_ENABLED=.*/TV_POLY_MOMO_V3_ENABLED=true/' /etc/tv/tradingvenue.env \
      && systemctl restart tv-engine"
   ```
   First v3 fires within 5-15min on the next 5m boundary.

3. **Day 1 monitoring**:
   - All 18 v3 sleeves should appear in `trading.events` resolutions within 15min
   - At least one v3 HEDGE resolution should have `partial_fill=true` within 6h (depends on SOL_5m volatility)
   - `bar_ctx_age_ms` p95 should match v2

4. **Day 7 checkpoint** per §7.

---

## 10 · Kill switch

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_POLY_MOMO_V3_ENABLED=.*/TV_POLY_MOMO_V3_ENABLED=false/' /etc/tv/tradingvenue.env \
   && systemctl restart tv-engine"
```

To re-enable: flip back to `true` and restart. v1 and v2 are unaffected.

---

## 11 · Files affected

### New
- `backend/app/strategies/polymarket/momo_v3.py`
- `tests/controllers/test_polymarket_updown_momo_v3.py`
- `tests/strategies/test_momo_v3_strategy.py`

### Modified
- `backend/app/controllers/polymarket_updown.py`:
  - `_valid_strategy_modes` — add `"momo_v3"`
  - `_build_signal_aux` — extend the v2 branch to also match `"momo_v3"`
  - `_maybe_hedge` — add `if self.strategy_mode == "momo_v3"` branch that bypasses any 95%/50% skip and writes `partial_fill=true` audit
  - `_try_bid_exit` — same shape for SELL
  - `_audit_resolution` — emit new partial-fill fields when present
- `backend/app/engine/sleeve_registry.py` (or equivalent) — register 18 v3 sleeves
- `/etc/tv/tradingvenue.env` — new `TV_POLY_MOMO_V3_*` vars

### No changes
- `momo.py` (v1 strategy class)
- `momo_v2.py` (v2 strategy class)
- v1, v2 sleeve registrations
- `_RET_2M_V2_*` cache (v3 shares it)
- `book_mirror` (v3 reuses v2's WS subscription path)

---

## 12 · Risks

| risk | mitigation |
|---|---|
| Slot budget overflow at 89 sleeves | Measure dispatch latency on first v3 fire; parallelize per (sym, tf) if > 2s |
| Partial fill on HEDGE creates net-negative position when held loses + hedge underfills | This is real — if hedge_shares < entry_shares and held loses, hedge gross < entry cost. The chainlink settlement of the "naked" portion of held side at $0 doubles the loss. Lab backtest shows this is offset on average. Monitor cell-by-cell post-deploy. |
| `_RET_2M_V2_*` shared cache pollution if v3 has subtle aux differences | Inspect `_build_signal_aux` extension diff carefully — must produce IDENTICAL ret_2m for the same (sym, tf, ws) input. |
| Audit field schema break for downstream consumers | New fields are additive; old v1/v2 consumers ignore extras. No breakage. |

---

## 13 · Out of scope

- Live transition (still gated; see live transition spec)
- Removing v1 or v2 (we coexist for A/B)
- Changing the rev_bp threshold (5bp inherited from v2)
- Adding a hard floor on partial fill ratio (e.g. "skip if < 30%") — that's a future tuning knob if v3 underperforms

---

## 14 · Lab-side analyzer (post-deploy)

After 24h of v3 fires:

1. Pull `trading.events` filtered to `sleeve_id LIKE '%_momo_v3_%'` → save to `data/v4/shadow_trades_<date>/momo_v3_resolutions.csv`
2. New analyzer `strategy_lab/meta_classifier/momo_v3_shadow_analyzer.py` (parallel to v2's) compares:
   - v3 vs v2 HEDGE: fire rate Δ, pnl/trade Δ, partial-only fire count
   - v3 vs v2 SELL: same
   - v3 partial-fill audit field distribution (% of fires that were partial)
3. Side-by-side per-cell tables in `strategy_lab/reports/MOMO_V3_VS_V2_<date>.md`

---

*End of TV_AGENT_MOMO_V3_PARTIAL_SLEEVES_IMPLEMENTATION.md.*
