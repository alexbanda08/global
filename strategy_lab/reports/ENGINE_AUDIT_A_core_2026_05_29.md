# ENGINE AUDIT A — core fill/cost engine
**Date:** 2026-05-30  
**Scope:** `strategy_lab/engine_v2.py`, `strategy_lab/fees.py`, `strategy_lab/latency.py`, `strategy_lab/book_walk.py`

---

## 1. LOOK-AHEAD / ASOF CORRECTNESS

**Result: CLEAN**

- `find_book_strict` (engine_v2.py:143): uses `np.searchsorted(ts, target_us, side="right") - 1`.  
  `side="right"` returns the first index strictly greater than `target_us`; subtracting 1 gives the
  last index with `ts[i] <= target_us`. Correct — never a future snapshot.
- `fill_at_book` (engine_v2.py:219-222): when `apply_latency_to_entry=True`, computes
  `lookup_us = fire_us + latency_ms * 1000`. This shifts the lookup LATER in time (worse fill,
  realistic). The shift never goes backwards.
- No outcome or settlement data touches `fill_at_book` or `find_book_strict`. The `won` flag is
  only passed at `hold_pnl` / `sell_pnl` call time, well after the fill is computed.

---

## 2. FEE MODEL

**Result: CLEAN (no bugs in logic; one dead-code observation)**

### 2a. `fees.py` formula
`poly_taker_fee_per_share(p) = feeRate * p * (1-p)` with `DEFAULT_CRYPTO_FEE_BPS = 700`
(feeRate = 0.07). Formula correct. At p=0.69: fee = 0.07 * 0.69 * 0.31 = $0.01496/share.

### 2b. `fill_at_book` fee_in (engine_v2.py:245-246)
Entry fee computed correctly via poly_taker_fee_per_share when fee_model="poly_taker_curve".
Set to 0.0 for legacy model.

### 2c. `hold_pnl` (engine_v2.py:258-280)
- poly_taker_curve: WIN = gross - fee_in; LOSS = -usd_in - fee_in. Fee on BOTH legs. Correct.
- legacy_2pct_on_profit: WIN = gross - gross*0.02; LOSS = -usd_in. No fee on loss. Matches
  CLAUDE.md production verification (2026-05-22, 25,900 events).

### 2d. `sell_pnl` (engine_v2.py:298-317)
- poly_taker_curve: charges fee_in (entry) + fee_out (exit). Both legs charged. Correct.
- legacy: fee only if profit > 0 on combined round-trip. Matches legacy expectation.

### 2e. `fill_commission_usd` (engine_v2.py:172-193)
**Dead code** — defined but never called by hold_pnl or sell_pnl. Both functions inline their
own fee logic. Not a correctness bug (logic is duplicated, not wrong), but creates maintenance
risk of divergence. Filed as technical debt; not fixed here to avoid breaking any external
callers that might import it directly.

### 2f. Production vs stress-test clarification
Per CLAUDE.md (2026-05-22): production crypto-updown markets charge ONLY 2%-on-profit
(feeRate effectively 0). `LegacyConfig` is the correct production-parity model.
`poly_taker_curve` (LiveMimicConfig / RealisticConfig) is a conservative stress test
for if/when Polymarket enforces the full fee schedule.

---

## 3. BOOK_WALK

**Result: CLEAN**

`book_walk_fill` (book_walk.py:18-73):
- Walks ask levels in order from level 0 for `side='buy'`. Correct — caller must pass ask
  levels sorted ascending.
- Stops when `remaining_usd <= EPSILON`. No overshoot.
- Flags `underfilled=True` when book exhausts before notional met.
- Hard-breaks on `p <= 0 or p >= 1` (line 53-55) — Polymarket invariant enforced.
- Returns `(0.0, 0.0, 0.0, hit, True)` if total_shares <= EPSILON — no divide-by-zero.
- No lookahead; no mid-price fills. Operates purely on the passed levels array.

`fill_at_book` rejects fills where `shares <= 0 or (under and usd < notional * 0.5)` (line 242).
Partial fills up to 50% of notional are allowed; below that → None.

---

## 4. BUG: `min_book_events` NOT ENFORCED (FIXED)

**File:** `engine_v2.py`  
**Severity:** Medium — silently drops a real filter, inflates placement count in live-mimic/realistic mode.

`EngineConfig.min_book_events` is declared (line 87), set to 25 in `LiveMimicConfig` (line 117),
but `fill_at_book` never called `book_event_count` to enforce it. Every market passed through
regardless of how sparse its book was.

**Fix applied (engine_v2.py, after line 222):** before `find_book_strict`, count events in a
120s window ending at `lookup_us`. If `n_events < cfg.min_book_events`, return None.
The 120s window covers one full slot duration (the natural event density period).

---

## 5. BUG: `sell_pnl_partial` IMPORT ALIAS MISSING (FIXED)

**File:** `engine_v2.py`  
**Severity:** Low-to-Medium — `ImportError` for any caller doing
`from engine_v2 import sell_pnl_partial` (referenced in module docstring line 19 and
in `strategy_lab/reports/HANDOFF_*` usage examples).

The function `sell_pnl_partial` was never defined; only `sell_pnl` + `sell_at_bid_partial`
existed as separate primitives.

**Fix applied:** added `sell_pnl_partial` as a convenience wrapper that does the book lookup,
bid-side walk, and `sell_pnl` call in one shot. Backward-compatible.

---

## 6. ADDED: `tx_cost_usd` + `RealisticConfig`

### 6a. `tx_cost_usd: float = 0.0` added to `EngineConfig`
Subtracted per trade leg:
- `hold_pnl`: `-tx` once (entry order only; settlement/redemption is passive).
- `sell_pnl`: `-2 * tx` (entry order + sell order both touch chain).
LegacyConfig and LiveMimicConfig both default to `tx_cost_usd=0.0` — no behavior change.

### 6b. `RealisticConfig` added
```python
@dataclass(frozen=True)
class RealisticConfig(EngineConfig):
    name: str = "realistic"
    fee_model: str = "poly_taker_curve"   # HIGH fee (stress, NOT production reality)
    latency_ms: float = 85.0
    apply_latency_to_entry: bool = True
    apply_latency_to_exit: bool = True
    min_book_events: int = 25
    tx_cost_usd: float = 0.01             # ~1 cent gas/execution per trade leg
```

Docstring explicitly warns: production crypto-updown ACTUALLY uses 2%-on-profit.
`poly_taker_curve` here is a deliberate stress test.

---

## 7. SMOKE TEST RESULTS (vwap=0.69, hit=48.1%)

```
EV at vwap=0.69, hit=48.1% (corrected momo number)
  legacy:     $-7.6955/trade  (production reality: 2%-on-profit)
  live_mimic: $-8.1298/trade  (poly_taker_curve, no tx cost)
  realistic:  $-8.1398/trade  (poly_taker_curve + $0.01 tx)
  delta lm-legacy:   $-0.4343/trade  <- real fee cost
  delta real-legacy: $-0.4443/trade  <- fee + tx cost
  delta real-lm:     $-0.0100/trade  <- pure tx cost ($0.01)
```

Note: all three configs are negative EV at 48.1% hit / p=0.69. This is expected — breakeven
requires ~70.5% hit rate at p=0.69 with poly_taker_curve (see `fees.py:breakeven_hit_rate`).
The delta between legacy and realistic is -$0.44/trade, or about 1.8% of notional additional drag.
The tx_cost alone (-$0.01) is small relative to the fee delta (-$0.43).

---

## 8. VERDICT

Core engine is sound after fixes. Two bugs patched:
1. `min_book_events` filter silently bypassed — now enforced in `fill_at_book`.
2. `sell_pnl_partial` alias missing — now implemented.

No look-ahead, no outcome leak, no fill-at-mid optimism. Fee models correctly segregated:
LegacyConfig = production reality; RealisticConfig = conservative stress.
