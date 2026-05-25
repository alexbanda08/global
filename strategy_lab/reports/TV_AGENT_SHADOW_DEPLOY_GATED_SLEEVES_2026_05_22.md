# TV Agent — Shadow deploy spec: 11 gated sleeves (HoD + MTF + Markov)

**Type:** Implementation spec
**Mode:** Shadow paper (default)
**Owner:** TV agent
**Scope:** Add 11 new sleeves that wrap existing momo / momo_v2 / sniper controllers with additional filter gates. **No core strategy code changes.** Gates run AFTER the existing strategy `signal()` returns UP/DOWN, BEFORE the order placement.

---

## 1. Sleeves to create (11 total)

Each new sleeve is a SHADOW companion to an existing controller, identified by an added suffix. The base controller's `signal()` must remain unchanged — the new gate is applied on top.

| # | sleeve_id (HOLD/HEDGE/SELL × 11) | base controller | gate stack |
|--:|---|---|---|
| 1 | `poly_updown_sol_5m_sniper_hod` | sniper SOL 5m | HoD-Top8 |
| 2 | `poly_updown_eth_15m_sniper_hod_m5va` | sniper ETH 15m | HoD-Top8 ∩ Markov(w20, bar=5m, vol-adaptive) |
| 3 | `poly_updown_btc_15m_momo_hod` | momo (v1) BTC 15m | HoD-Top8 |
| 4 | `poly_updown_btc_15m_sniper_hod` | sniper BTC 15m | HoD-Top8 |
| 5 | `poly_updown_btc_5m_sniper_hod` | sniper BTC 5m | HoD-Top8 |
| 6 | `poly_updown_btc_5m_momo_v2_hod_mtf` | momo_v2 BTC 5m | HoD-Top8 ∩ MTF2 |
| 7 | `poly_updown_btc_15m_momo_v2_hod` | momo_v2 BTC 15m | HoD-Top8 |
| 8 | `poly_updown_sol_5m_momo_v2_hod` | momo_v2 SOL 5m | HoD-Top8 |
| 9 | `poly_updown_eth_15m_momo_v2_hod` | momo_v2 ETH 15m | HoD-Top8 |
| 10 | `poly_updown_sol_15m_momo_v2_hod` | momo_v2 SOL 15m | HoD-Top8 |
| 11 | `poly_updown_eth_5m_sniper_hod` | sniper ETH 5m | HoD-Top8 |

Each sleeve has 3 policy variants (HOLD / HEDGE / SELL), same as existing sleeves. Total new sleeve_ids = 11 × 3 = 33.

Naming convention used in the suffix:
- `_hod` = HoD-Top8 only
- `_hod_mtf` = HoD-Top8 ∩ MTF2
- `_hod_m5va` = HoD-Top8 ∩ Markov(w20×5m×vol-adaptive)

These suffixes must be parseable for downstream analytics SQL (`REGEXP_REPLACE(sleeve_id, '_(hod|hod_mtf|hod_m5va)(_HOLD|_HEDGE|_SELL)?$', '')`).

---

## 2. Gate definitions (the only NEW code)

Implement in new file: `backend/app/strategies/polymarket/gates.py`. Pure helpers, no IO, no state. Same invariants as `f7_gate.py` (CLAUDE.md inv #4).

### 2.1 Hour-of-Day gate

```python
from typing import Iterable

def hod_passes(fire_unix_s: int, allowed_hours: Iterable[int]) -> bool:
    """Return True if UTC hour of fire timestamp is in allowed_hours.

    fire_unix_s: seconds since epoch of the controller fire decision time.
    allowed_hours: iterable of ints in [0, 23]. Must be UTC hours.
    """
    from datetime import UTC, datetime
    hour = datetime.fromtimestamp(int(fire_unix_s), tz=UTC).hour
    return hour in set(allowed_hours)
```

Per-cell allowed hours (lock these in config; do not recompute live):

```python
# UTC hours, 0-indexed (00:00-00:59 UTC = 0, 23:00-23:59 UTC = 23).
# Source: 28-day backtest (Apr 22 - May 21), top 8 hours by sum$ per (strategy, cell).
# Refresh schedule: re-derive monthly (see Section 6).
HOD_TOP8_BY_CELL: dict[tuple[str, str], list[int]] = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo",    "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],    # momo = v1
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}
```

### 2.2 Multi-Timeframe confluence (MTF2) gate

```python
import math

def mtf2_passes(signal: str, ret_15m: float, ret_1h: float) -> bool:
    """Return True if both binance 15m and 1h returns match the signal direction.

    signal: "UP" | "DOWN" | other (other always returns True — gate is no-op).
    ret_15m: log(BTC@fire_us / BTC@(fire_us - 900s)). NaN → False.
    ret_1h:  log(BTC@fire_us / BTC@(fire_us - 3600s)). NaN → False.

    The 15m and 1h closes MUST come from the same binance-spot-ws kline source
    as the existing momo signal pipeline (no source mismatch).
    """
    if signal not in ("UP", "DOWN"):
        return True
    if not (math.isfinite(ret_15m) and math.isfinite(ret_1h)):
        return False
    if signal == "UP":
        return ret_15m > 0 and ret_1h > 0
    return ret_15m < 0 and ret_1h < 0
```

Aux fields the controller must populate (in addition to existing aux):

```python
aux["ret_15m_for_mtf"] = float        # log(close@fire_us / close@(fire_us-900s)), NaN if missing
aux["ret_1h_for_mtf"]  = float        # log(close@fire_us / close@(fire_us-3600s)), NaN if missing
```

Where to compute: `poly_updown_loop.py::build_bar_context_t_plus_60` and `build_bar_context_t_plus_120` already fetch binance closes. Add two more `_fetch_close` calls offset −840 and −3540 (relative to ws_s for momo, slot_start for sniper) and stash on BarContext as `ret_15m_for_mtf` / `ret_1h_for_mtf`. For sniper which fires at `slot_start`, anchor at `slot_start`.

### 2.3 Markov regime gate (w20 × 5m × vol-adaptive)

```python
import math
import numpy as np

def markov_passes(signal: str, regime: int) -> bool:
    """regime: 0 = Bear, 1 = Sideways, 2 = Bull. -1 = warmup/unknown → False."""
    if signal == "UP":   return regime == 2
    if signal == "DOWN": return regime == 0
    return True
```

The regime label is computed in a NEW module: `backend/app/strategies/polymarket/markov.py`. Pure functions only, no IO:

```python
def label_regime_vol_adaptive(
    closes_window: np.ndarray,         # length window_bars + 1, ending at current bar close
    rolling_returns_14d: np.ndarray,   # |log returns| over prior 14d at same window_bars span
) -> int:
    """Return Bear=0, Sideways=1, Bull=2 for the current bar.

    closes_window: most recent window_bars+1 1m or 5m closes (chronological).
    rolling_returns_14d: signed log returns over the prior 14 days, same window_bars span.

    Algorithm:
      ret = log(closes_window[-1] / closes_window[0])
      q33, q66 = quantile of rolling_returns_14d at [1/3, 2/3]
      if ret < q33: Bear
      elif ret > q66: Bull
      else Sideways

    Returns -1 if rolling_returns_14d has fewer than 100 finite samples (warmup).
    """
    if len(rolling_returns_14d) < 100:
        return -1
    valid = rolling_returns_14d[np.isfinite(rolling_returns_14d)]
    if len(valid) < 100:
        return -1
    if not (math.isfinite(closes_window[0]) and math.isfinite(closes_window[-1])
            and closes_window[0] > 0):
        return -1
    ret = math.log(closes_window[-1] / closes_window[0])
    q33, q66 = np.quantile(valid, [1/3, 2/3])
    if ret < q33:  return 0
    if ret > q66:  return 2
    return 1
```

**For `_hod_m5va` only** (sleeve #2): Markov parameters:
- `window_bars = 20`
- `bar_minutes = 5` (use binance-spot-ws 5MIN closes)
- `lookback_days = 14`
- `quantiles = (1/3, 2/3)` (vol-adaptive tertiles)

Closes source: binance-spot-ws 5MIN klines from `BinanceMarketDataFeed`. The rolling 14d window of past returns can be computed inline at fire time (cheap: ~4032 5m bars × 1 quantile call ≈ <5ms).

Add aux field:

```python
aux["markov_regime_w20_5m_va"] = int    # -1, 0, 1, or 2
```

---

## 3. Wiring the gates into the controller

### 3.1 Controller branch (existing controller, minimal change)

In `polymarket_updown.py::_decide_entry_action` (or whatever the call site is — the place that calls `strategy.signal()` and then proceeds to placement), AFTER the strategy returns UP/DOWN AND BEFORE qty_compute / token_id resolution:

```python
from backend.app.strategies.polymarket.gates import (
    HOD_TOP8_BY_CELL, hod_passes, mtf2_passes, markov_passes,
)

# After: signal = strategy.signal(bars, config, aux)
# (signal is "UP" | "DOWN" | "NONE")
if signal == "NONE":
    return  # existing behavior

# NEW gate stack (only for the new shadow sleeves)
if self._gate_stack:                       # list[str] from sleeve config
    cell_key = (self._gate_cell_strategy,  # e.g. "sniper" / "momo" / "momo_v2"
                f"{symbol.lower()}_{tf}")  # e.g. "btc_15m"
    for gate_name in self._gate_stack:
        if gate_name == "hod":
            allowed = HOD_TOP8_BY_CELL.get(cell_key, [])
            if not hod_passes(int(time.time()), allowed):    # use fire decision time
                await self._audit(symbol, tf,
                                  reason="gate_hod_skip",
                                  signal=signal,
                                  condition_id=condition_id,
                                  payload={"hour": datetime.fromtimestamp(int(time.time()), UTC).hour,
                                           "allowed": list(allowed)})
                return
        elif gate_name == "mtf2":
            r15 = aux.get("ret_15m_for_mtf", float("nan"))
            r1h = aux.get("ret_1h_for_mtf", float("nan"))
            if not mtf2_passes(signal, r15, r1h):
                await self._audit(symbol, tf,
                                  reason="gate_mtf2_skip",
                                  signal=signal,
                                  condition_id=condition_id,
                                  payload={"ret_15m": r15, "ret_1h": r1h})
                return
        elif gate_name == "m5va":
            regime = aux.get("markov_regime_w20_5m_va", -1)
            if not markov_passes(signal, regime):
                await self._audit(symbol, tf,
                                  reason="gate_markov_skip",
                                  signal=signal,
                                  condition_id=condition_id,
                                  payload={"regime": regime})
                return
        else:
            # Unknown gate name — fail-open (do not block) but emit warning log.
            logger.warning("poly_updown.unknown_gate",
                           extra={"gate": gate_name, "sleeve_id": self.sleeve_id})

# (existing flow continues — qty_compute, token_id, place_entry_order, etc.)
```

### 3.2 Per-sleeve config schema

In whatever config format the controller already reads (env var / yaml / table), add per-shadow-sleeve entries:

```yaml
# Example: backend/app/configs/poly_updown_shadow_sleeves.yaml
shadow_sleeves:
  - sleeve_id: poly_updown_sol_5m_sniper_hod
    base_strategy: sniper
    asset: SOL
    tf: 5m
    gate_stack: [hod]
    gate_cell_strategy: sniper       # used to look up HOD_TOP8_BY_CELL
    paper_only: true                  # SHADOW MODE — never live

  - sleeve_id: poly_updown_eth_15m_sniper_hod_m5va
    base_strategy: sniper
    asset: ETH
    tf: 15m
    gate_stack: [hod, m5va]
    gate_cell_strategy: sniper
    paper_only: true

  - sleeve_id: poly_updown_btc_15m_momo_hod
    base_strategy: momo               # v1
    asset: BTC
    tf: 15m
    gate_stack: [hod]
    gate_cell_strategy: momo
    paper_only: true

  - sleeve_id: poly_updown_btc_15m_sniper_hod
    base_strategy: sniper
    asset: BTC
    tf: 15m
    gate_stack: [hod]
    gate_cell_strategy: sniper
    paper_only: true

  - sleeve_id: poly_updown_btc_5m_sniper_hod
    base_strategy: sniper
    asset: BTC
    tf: 5m
    gate_stack: [hod]
    gate_cell_strategy: sniper
    paper_only: true

  - sleeve_id: poly_updown_btc_5m_momo_v2_hod_mtf
    base_strategy: momo_v2
    asset: BTC
    tf: 5m
    gate_stack: [hod, mtf2]
    gate_cell_strategy: momo_v2
    paper_only: true

  - sleeve_id: poly_updown_btc_15m_momo_v2_hod
    base_strategy: momo_v2
    asset: BTC
    tf: 15m
    gate_stack: [hod]
    gate_cell_strategy: momo_v2
    paper_only: true

  - sleeve_id: poly_updown_sol_5m_momo_v2_hod
    base_strategy: momo_v2
    asset: SOL
    tf: 5m
    gate_stack: [hod]
    gate_cell_strategy: momo_v2
    paper_only: true

  - sleeve_id: poly_updown_eth_15m_momo_v2_hod
    base_strategy: momo_v2
    asset: ETH
    tf: 15m
    gate_stack: [hod]
    gate_cell_strategy: momo_v2
    paper_only: true

  - sleeve_id: poly_updown_sol_15m_momo_v2_hod
    base_strategy: momo_v2
    asset: SOL
    tf: 15m
    gate_stack: [hod]
    gate_cell_strategy: momo_v2
    paper_only: true

  - sleeve_id: poly_updown_eth_5m_sniper_hod
    base_strategy: sniper
    asset: ETH
    tf: 5m
    gate_stack: [hod]
    gate_cell_strategy: sniper
    paper_only: true
```

Each shadow sleeve runs in parallel with its base sleeve. The base sleeve continues firing normally with whatever existing F7 config it has; the shadow sleeve fires a SUBSET of base fires plus the gate stack.

### 3.3 Required aux additions per gate

| Gate | New aux fields | Computed in |
|---|---|---|
| `hod` | (none — uses controller clock) | controller branch directly |
| `mtf2` | `ret_15m_for_mtf` (float), `ret_1h_for_mtf` (float) | `build_bar_context_t_plus_*` |
| `m5va` | `markov_regime_w20_5m_va` (int) | `build_bar_context_t_plus_*` |

For `mtf2`: extend `BarContext` builders to fetch 1MIN binance closes at offsets −840 and −3540 (relative to `ws_s` for momo, `slot_start` for sniper), compute the two log returns, populate the aux fields. Use `BinanceMarketDataFeed.get_close_asof` if available; else `fetch_close_asof` (same path momo already uses).

For `m5va`: implement a new method `_fetch_markov_regime_w20_5m_va` on the controller. Pulls 21 most recent 5MIN closes (window_bars + 1) and 14 days of prior 5MIN |log returns|, calls `markov.label_regime_vol_adaptive`. Result cached per `(symbol, ws_s, variant)` to avoid recompute across HOLD/HEDGE/SELL clones.

---

## 4. Audit row payload

Each shadow sleeve emits `trading.events kind='poly_updown_signal'` rows with **additional payload fields** when the gate decides:

```json
{
  "reason": "order_placed" | "gate_hod_skip" | "gate_mtf2_skip" | "gate_markov_skip",
  "signal": "UP" | "DOWN",
  "gate_stack": ["hod", "mtf2"],
  "gate_decisions": {
    "hod":  {"pass": true, "hour": 14, "allowed_set": [0,3,10,11,12,13,14,15]},
    "mtf2": {"pass": true, "ret_15m": 0.0012, "ret_1h": 0.0045},
    "m5va": {"pass": null}
  },
  // existing fields stay the same: symbol, tf, condition_id, ret_2m_at_signal, etc.
}
```

For early-exit on a gate, only the gates that ran (up to and including the failing one) appear in `gate_decisions`. Downstream gates are recorded as `null` or absent.

---

## 5. Verification

### 5.1 Sanity SQL (1h after deploy)

```sql
-- Confirm each shadow sleeve is emitting events
SELECT sleeve_id, COUNT(*) AS n,
       SUM(CASE WHEN data->>'reason'='order_placed' THEN 1 ELSE 0 END) AS placed,
       SUM(CASE WHEN data->>'reason'='gate_hod_skip' THEN 1 ELSE 0 END) AS hod_skip,
       SUM(CASE WHEN data->>'reason'='gate_mtf2_skip' THEN 1 ELSE 0 END) AS mtf2_skip,
       SUM(CASE WHEN data->>'reason'='gate_markov_skip' THEN 1 ELSE 0 END) AS m5va_skip
FROM trading.events
WHERE kind='poly_updown_signal'
  AND sleeve_id LIKE 'poly_updown_%_hod%'
  AND at >= NOW() - INTERVAL '1 hour'
GROUP BY sleeve_id
ORDER BY sleeve_id;
```

Each sleeve_id should appear with at least 1 row within 1h of deploy (assuming the base sleeve fired in that window).

### 5.2 Per-cell WR after 7d shadow

```sql
SELECT REGEXP_REPLACE(sleeve_id, '_(HOLD|HEDGE|SELL)$', '') AS sleeve_group,
       COUNT(*) AS n,
       ROUND(AVG((data->>'won')::bool::int) * 100, 2) AS wr_pct,
       ROUND(SUM((data->>'pnl_usd')::numeric), 2) AS sum_pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND sleeve_id LIKE 'poly_updown_%_hod%'
  AND at >= NOW() - INTERVAL '7 days'
GROUP BY sleeve_group
ORDER BY sum_pnl DESC;
```

### 5.3 Hour distribution per sleeve

```sql
-- Confirms the gate is admitting fires only from allowed hours
SELECT REGEXP_REPLACE(sleeve_id, '_(HOLD|HEDGE|SELL)$', '') AS sleeve_group,
       EXTRACT(hour FROM at AT TIME ZONE 'UTC') AS utc_hour,
       COUNT(*) AS n_placed
FROM trading.events
WHERE kind='poly_updown_signal'
  AND data->>'reason'='order_placed'
  AND sleeve_id LIKE 'poly_updown_%_hod%'
  AND at >= NOW() - INTERVAL '24 hours'
GROUP BY sleeve_group, utc_hour
ORDER BY sleeve_group, utc_hour;
```

For each sleeve, `utc_hour` values should be a SUBSET of the configured `HOD_TOP8_BY_CELL[(strategy, cell)]` list.

---

## 6. Monthly hot-hour refresh

The `HOD_TOP8_BY_CELL` lists are derived from 28 days of backtest data. They drift with macro regime (US session shifts, CPI weeks, etc.). Refresh on a monthly cadence:

1. On the 1st of each month, run the analysis script (lives in strategy_lab): `python strategy_lab/markov_filter/_recompute_hod_top8.py --window-days 28`
2. The script:
   - Pulls last 28 days of `trading.events` (chainlink-resolved) per cell
   - Computes sum$ per (cell, hour)
   - Outputs new top-8 lists per cell
   - **Compares to current `HOD_TOP8_BY_CELL`**: if any cell's set changes by ≥3 hours, flag for human review before applying
   - Writes a PR/diff to update the constant in `gates.py`
3. Operator reviews + merges; auto-deploy via CI.

Don't auto-update without a human review — bad-month outliers could corrupt the list.

---

## 7. Hard constraints / invariants

- **All 11 sleeves are paper-only at deploy** (`paper_only: true`). Promotion to live requires the 7d shadow validation (Section 5.2) to show WR + $/tr within 25 % of the spec's expected ranges.
- Gates must NOT change the underlying strategy's `signal()` output — they are pure pre-placement filters. Existing sleeves keep behaving identically.
- Gate evaluations are **pure functions** (CLAUDE.md inv #4): no IO inside gate functions; the controller is responsible for populating aux from the BarContext.
- Audit row payload must include `gate_stack` AND `gate_decisions` for every fire AND every skip, so downstream analytics can see what each gate did.
- HoD uses UTC. **No local time, ever.** Anchor to `int(time.time())` at the controller fire decision moment.
- MTF2 ret values come from the SAME binance-spot-ws source as the existing momo signal (no source mismatch).
- Markov regime uses binance-spot-ws 5MIN. NO chainlink (would add latency without consistent edge per backtest).

---

## 8. Files to add / modify

| File | Action |
|---|---|
| `backend/app/strategies/polymarket/gates.py` | NEW. Three gate functions + `HOD_TOP8_BY_CELL` constant. |
| `backend/app/strategies/polymarket/markov.py` | NEW. `label_regime_vol_adaptive` pure helper. |
| `backend/app/controllers/polymarket_updown.py` | MODIFY. Add `self._gate_stack` + `self._gate_cell_strategy` to `__init__`; wire gate block AFTER `strategy.signal()` BEFORE qty_compute. |
| `backend/app/engine/poly_updown_loop.py` | MODIFY. Extend `BarContext` with `ret_15m_for_mtf`, `ret_1h_for_mtf`, `markov_regime_w20_5m_va`. Populate in builders (only when at least one shadow sleeve in that cell needs them). |
| `backend/app/engine/main.py` or sleeve config loader | MODIFY. Read `shadow_sleeves` YAML / table, instantiate 11 shadow controllers in addition to existing ones. |
| `backend/app/configs/poly_updown_shadow_sleeves.yaml` | NEW. 11 shadow sleeve definitions. |
| Migrations | None — `trading.events.data` is jsonb; new payload fields slot in. |

---

## 9. Out of scope (do NOT do)

- Do NOT modify `_compute_qty_shares`, `_resolve_token_id`, or any post-placement code path.
- Do NOT modify `MomoStrategy.signal()`, `MomoV2Strategy.signal()`, `Updown5mStrategy.signal()`, or `f7_passes()`. The new gates run AFTER these, not inside them.
- Do NOT enable any sleeve in live mode at deploy.
- Do NOT extend gates to existing sleeves (the 11 are SHADOW companions; existing sleeves keep their F7 / no-filter behavior).
- Do NOT auto-refresh `HOD_TOP8_BY_CELL` without operator review.

---

## 10. Promotion checklist (after 7d shadow)

For each shadow sleeve, before promoting to a primary sleeve (live mode):

- [ ] 7-day shadow window has produced ≥ 30 placed fires
- [ ] Shadow WR within 25 % of the spec's expected (see Section 11 table)
- [ ] Shadow $/trade within 25 % of expected
- [ ] No `gate_*_skip` reasons account for > 80 % of all decisions (suggests gate is too tight)
- [ ] Hour distribution of admitted fires matches the allowed_hours set exactly
- [ ] No `qty_compute_failed` rate > 80 % (would suggest book-quality issue independent of gate)

---

## 11. Expected performance ranges (for sanity check, NOT a deploy criterion)

These numbers come from a 28-day backtest with walk-forward validation. Actual shadow performance may vary ±25 %. Use as sanity gates only.

| sleeve | expected n / week | expected WR | expected $/trade |
|---|--:|--:|--:|
| sniper sol_5m _hod | ~65 | 65-70 % | +$6 to +$10 |
| sniper eth_15m _hod_m5va | ~25 | 70-80 % | +$10 to +$16 |
| momo btc_15m _hod (v1) | ~20 | 70-85 % | +$10 to +$16 |
| sniper btc_15m _hod | ~100 | 55-62 % | +$3 to +$5 |
| sniper btc_5m _hod | ~110 | 55-60 % | +$2 to +$4 |
| momo_v2 btc_5m _hod_mtf | ~60 | 58-65 % | +$3 to +$6 |
| momo_v2 btc_15m _hod | ~35 | 65-72 % | +$6 to +$9 |
| momo_v2 sol_5m _hod | ~50 | 58-65 % | +$3 to +$6 |
| momo_v2 eth_15m _hod | ~25 | 65-72 % | +$6 to +$10 |
| momo_v2 sol_15m _hod | ~18 | 65-75 % | +$6 to +$10 |
| sniper eth_5m _hod | ~80 | 50-58 % | +$0 to +$3 |

(Note: "per week" assumes the production engine fires at the same rate it does today; if production fire counts change, scale these proportionally.)

---

## 12. Rollback

If any shadow sleeve shows aggregate WR < 40 % or sum$ < −$200 over 7 days:

1. Set `paper_only: true` (already default — confirm).
2. Set `enabled: false` in YAML config.
3. Hot-reload or restart engine.
4. File issue against the spec — gate may need re-derivation or removal.

Rollback is FAST because no live capital is committed in shadow mode.

---

## 13. Summary checklist for TV agent

- [ ] Create `gates.py` with `hod_passes`, `mtf2_passes`, `markov_passes`, `HOD_TOP8_BY_CELL`.
- [ ] Create `markov.py` with `label_regime_vol_adaptive`.
- [ ] Modify `polymarket_updown.py` to add `_gate_stack` / `_gate_cell_strategy` to __init__ + wire gate block at fire decision time.
- [ ] Modify `poly_updown_loop.py` BarContext + builders to populate the 3 new aux fields.
- [ ] Create `poly_updown_shadow_sleeves.yaml` with 11 entries.
- [ ] Wire sleeve config loader to instantiate shadow controllers.
- [ ] Deploy to VPS3 (paper mode only).
- [ ] Run verification SQL (Section 5.1) at 1h after deploy.
- [ ] Pull 7d numbers and compare to expected ranges (Section 11).
- [ ] Schedule monthly HoD refresh (Section 6).
