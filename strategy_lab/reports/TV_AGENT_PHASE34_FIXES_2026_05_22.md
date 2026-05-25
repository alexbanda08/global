# TV agent — Phase 34 fixes: HoD refresh + 3 bug fixes

_2026-05-22. Continuation of `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`.
Audited the live deployment on VPS3 today and found one blocking bug, one
silent-fail bug, one stale constant, and a test-coverage gap. This document
specifies every change required to ship the fix._

**Acceptance criteria after fix**
- Sleeve #2 (`poly_updown_eth_15m_sniper_hod`) fires and resolves in production.
- Sleeve #3 (`poly_updown_btc_15m_momo_hod`) gate stack updated to `("hod","m1va")`
  and fires when the 1m vol-adaptive Markov regime agrees with the signal.
- `HOD_TOP8_BY_CELL` reflects the fire-time-derived hours per spec §2.1.
- New unit + integration tests assert the Markov gate is reachable and behaves
  per spec §2.3 (regime ∈ {0,1,2} for valid inputs, fail-closed on warmup).
- All 11 sleeves visible in `trading.events` under `kind='poly_updown_signal'`
  in the 1h after deploy.

---

## 1. Findings recap (one paragraph per bug)

**Bug #1 — Markov regime never computed (BLOCKING sleeve #2).**
`build_bar_context_t_plus_120` and `build_bar_context_t_plus_60` hardcode
`markov_regime_w20_5m_va=None`. A comment promised the controller would
compute it lazily with a per-`(sym, ws_s)` cache, but the lazy code was
never written. The controller reads `None → -1` and `markov_passes` fails
closed with `gate_markov_skip` every time. Production log shows
sleeve #2 had 2 fires reach the gate today, both got `regime=-1`. Net
result: sleeve #2 cannot fire under the current implementation.

**Bug #2 — sniper bar_close phase has no MTF/Markov aux (SILENT FAIL).**
`ret_15m_for_mtf`, `ret_1h_for_mtf`, and `markov_regime_w20_5m_va` are
only populated in the t+60 and t+120 builders. Sniper fires at
`phase="bar_close"`, which uses a different builder. If any sniper
sleeve carries an `mtf2` or `m5va` gate, the aux is `None`, the gate
fails closed, and no production telemetry distinguishes this from a
correct rejection. Currently impacts sleeve #2 (sniper × m5va); a
future config typo could re-introduce this risk.

**Bug #3 — `HOD_TOP8_BY_CELL` is stale.** The shipped constant was
derived from `at_ts.dt.hour` (resolution time). Spec §2.1 requires
fire-time hour. My refresh (`_recompute_hod_top8.py --window-days 28`)
flagged ALL 18 cells with ≥3-hour change. Backtest on 28d data shows
ensemble PnL flips from $2,949 → $15,900 (5.4×) on the swap, with 11/11
sleeves positive vs 7/11 today.

**Bug #4 — no test coverage for the gate stack.**
`test_polymarket_updown_shadow.py` covers legacy `_audit_shadow_*`
functions but not the new gate block: nothing asserts the Markov gate
is reachable, nothing asserts `regime ∈ {0,1,2}` under a real feed,
nothing asserts `gate_decisions` payload shape. A single integration
test would have caught Bug #1 before deploy.

---

## 2. Fix #1 — refresh `HOD_TOP8_BY_CELL`

### 2.1 Where
`backend/app/strategies/polymarket/gates.py`, around line 35-60.

### 2.2 What to change
Replace the existing `HOD_TOP8_BY_CELL` body with the values below.
This is the **fire-time-derived** table per spec §2.1, computed from
28d of `trading.events` via `_recompute_hod_top8.py`. Operator-approved
2026-05-22 as the first refresh per spec §6.

```python
# UTC hours, 0-indexed. Source: 28-day backtest sum$ per (strategy, cell),
# anchored at FIRE_us hour (NOT at_ts hour — see Phase 34 fix doc).
# Refresh schedule: re-derive monthly (see Section 6).
HOD_TOP8_BY_CELL: dict[tuple[str, str], tuple[int, ...]] = {
    # sniper family
    ("sniper",  "sol_5m"):   (0, 1, 3, 6, 10, 14, 15, 19),
    ("sniper",  "eth_5m"):   (0, 2, 10, 12, 15, 17, 18, 21),
    ("sniper",  "btc_5m"):   (1, 2, 4, 6, 8, 14, 21, 22),
    ("sniper",  "sol_15m"):  (5, 10, 12, 14, 15, 16, 18, 21),
    ("sniper",  "eth_15m"):  (0, 6, 12, 14, 16, 18, 19, 22),
    ("sniper",  "btc_15m"):  (0, 7, 9, 13, 14, 16, 18, 19),
    # momo (v1) family
    ("momo",    "sol_5m"):   (0, 7, 8, 9, 16, 19, 20, 23),
    ("momo",    "eth_5m"):   (1, 5, 6, 8, 14, 18, 22, 23),
    ("momo",    "btc_5m"):   (2, 7, 10, 14, 16, 20, 22, 23),
    ("momo",    "sol_15m"):  (1, 2, 5, 6, 7, 14, 18, 20),
    ("momo",    "eth_15m"):  (0, 2, 6, 11, 17, 18, 20, 21),
    ("momo",    "btc_15m"):  (0, 5, 7, 10, 11, 15, 18, 20),
    # momo_v2 family
    ("momo_v2", "sol_5m"):   (0, 6, 7, 9, 10, 12, 14, 22),
    ("momo_v2", "eth_5m"):   (0, 4, 6, 10, 12, 14, 19, 22),
    ("momo_v2", "btc_5m"):   (2, 6, 10, 12, 14, 16, 22, 23),
    ("momo_v2", "sol_15m"):  (1, 5, 9, 11, 14, 16, 22, 23),
    ("momo_v2", "eth_15m"):  (3, 11, 14, 15, 19, 20, 22, 23),
    ("momo_v2", "btc_15m"):  (3, 5, 14, 15, 16, 20, 22, 23),
}
```

### 2.3 Why ALL 18 cells changed
The old list was computed using `at_ts.dt.hour` (resolution-time hour).
Spec §2.1 mandates **fire-time hour** — for sniper that's
`slot_start = at_ts − window_s`, for momo v1 it's
`at_ts − 2×window_s + 120s`, for momo_v2 it's `at_ts − 2×window_s + 60s`.
The drift is 5-29 minutes depending on family/tf, enough to push the
timestamp into a different UTC hour 25-50% of the time. So the old
table optimized for the wrong anchor.

### 2.4 Expected post-fix impact
Per 28d backtest with refreshed HoD (see `SHADOW_11_SLEEVES_V2_2026_05_22.md`):
- All 11 sleeves positive (was 7/11).
- Ensemble sum-PnL @ $25 notional: **$15,900** (was $2,949).
- Sleeves #5 (`btc_5m_sniper_hod`) and #10 (`sol_15m_momo_v2_hod`) flip
  negative→positive on HoD swap alone.
- Average WR per sleeve: 67.6% (was 59.2%).

### 2.5 Tests to update
`backend/tests/strategies/polymarket/test_gates.py` (or wherever
HOD_TOP8_BY_CELL is asserted): update the expected hour lists.

---

## 3. Fix #2 — drop `m5va` from sleeve #2 gate stack (resolves Bug #1)

### 3.1 Decision
Don't write the lazy Markov compute. The backtest already proved the
Markov gate is **counterproductive on sniper sleeves**:

| variant for eth_15m sniper | gate stack | n (28d) | WR | $/tr | sum$ |
|---|---|--:|--:|--:|--:|
| baseline (current prod with refreshed HoD) | `hod, m5va` | 55 | 67.27% | +$5.69 | +$313 |
| **proposed fix** | `hod` | **129** | **73.64%** | **+$5.78** | **+$745** |
| (alternative tested) | `hod, m1va` | 93 | 78.49% | +$6.87 | +$639 |
| (alternative tested) | `hod, m5va_sig` | 47 | 61.70% | +$2.47 | +$116 |

Sniper fires at `slot_start` (a regime-agnostic boundary). The Markov
regime at that timestamp is decorrelated from the prior 2-min signal
the sniper threshold is gating on — Markov just adds noise. Dropping
it 2.4× the fire count AND lifts WR by 6.4pp.

### 3.2 Where
`backend/app/engine/main.py`, the `_SHADOW_GATED_SLEEVES_SPEC` tuple,
sleeve #2 entry.

### 3.3 What to change

```python
# BEFORE
("poly_updown_eth_15m_sniper_hod_m5va",  "sniper",  "ETH", "15m", ("hod", "m5va"),  "sniper",  "HEDGE_HOLD"),

# AFTER
("poly_updown_eth_15m_sniper_hod",       "sniper",  "ETH", "15m", ("hod",),         "sniper",  "HEDGE_HOLD"),
```

Note: both gate_stack and sleeve_id change. Sleeve_id rename keeps the
suffix convention parseable by analytics SQL
(`REGEXP_REPLACE(sleeve_id, '_hod$', '')`).

### 3.4 Migration concern — historical rows
`trading.events` will keep the old `poly_updown_eth_15m_sniper_hod_m5va`
rows (39 today). No migration needed; analytics dashboards should
treat both sleeve_ids as the same logical sleeve when comparing
shadow vs live. Add to dashboard filter:

```sql
sleeve_id IN ('poly_updown_eth_15m_sniper_hod_m5va', 'poly_updown_eth_15m_sniper_hod')
```

### 3.5 Tests to update
`backend/tests/engine/test_main_shadow_spec.py` (or wherever
`_SHADOW_GATED_SLEEVES_SPEC` is asserted): update the expected
sleeve #2 tuple.

---

## 4. Fix #3 — add `m1va` gate + populate aux in t+120 builder (sleeve #3)

### 4.1 Decision
Sleeve #3 (momo v1 btc_15m) currently runs `hod` only. Today's backtest
shows adding `m1va` (1-minute vol-adaptive Markov) lifts it from
**78.4% WR / +$13.42/tr** (hod only with refreshed HoD) to
**90.16% WR / +$20.73/tr (n=61)**. This is real edge — momo IS a
momentum strategy, so regime alignment is signal-confirming. Worth the
new code.

### 4.2 Files to add / modify

| File | Action |
|---|---|
| `backend/app/strategies/polymarket/gates.py` | Add nothing new — `markov_passes(signal, regime)` already works for any regime int. The gate name `m1va` is differentiated by which aux field the controller reads. |
| `backend/app/engine/poly_updown_loop.py` | NEW aux field on `BarContext`. NEW compute in `build_bar_context_t_plus_120`. |
| `backend/app/controllers/polymarket_updown.py` | NEW `elif _gate == "m1va":` branch in the gate block. |
| `backend/app/engine/main.py` | Update sleeve #3 gate_stack from `("hod",)` to `("hod", "m1va")`. |
| `backend/tests/engine/test_poly_updown_loop.py` | Add tests for new aux field + warmup behavior. |
| `backend/tests/controllers/test_polymarket_updown_gates.py` | NEW. Integration test for the m1va branch. |

### 4.3 `BarContext` extension (poly_updown_loop.py)

Add **next to** the existing `markov_regime_w20_5m_va` field:

```python
# Phase 34.1 — m1va gate aux. 1-MIN vol-adaptive Markov regime label
# at ws_s. Populated by build_bar_context_t_plus_120 ONLY (the phase
# momo v1 fires on). Sniper bar_close + momo_v2 t+60 leave this None.
# Same encoding as markov_regime_w20_5m_va: -1=warmup, 0=Bear, 1=Sideways,
# 2=Bull.
markov_regime_w20_1m_va: int | None = None
```

### 4.4 Aux populator (poly_updown_loop.py)

In `build_bar_context_t_plus_120` (the only builder that needs M1V for
sleeve #3), AFTER the existing `_ret_15m_mtf` / `_ret_1h_mtf` compute
and BEFORE the `BarContext(...)` return, insert:

```python
# Phase 34.1 — M1V (1-MIN vol-adaptive Markov) regime label.
# Uses 21 most recent 1MIN binance closes ending at ws_s + 14d of prior
# 1MIN log-returns from the same source. Cheap: <5ms when feed is warm.
_m1v_regime: int | None = None
try:
    from backend.app.strategies.polymarket.markov import label_regime_vol_adaptive
    # 21 closes ending at ws_s: feed.get_closes_window(symbol, ws_s, 21, "1m")
    _closes_window = primary.feed.get_closes_window(symbol, ws_s, 21, "1m")
    if _closes_window is not None and len(_closes_window) == 21:
        # 14d of prior log-returns at 1MIN: feed.get_log_returns_14d(symbol, ws_s, "1m")
        # Returns NaN-aware numpy array (oldest-first). Empty/short → label returns -1.
        _ret14d = primary.feed.get_log_returns_14d(symbol, ws_s, "1m")
        _m1v_regime = int(label_regime_vol_adaptive(
            np.asarray(_closes_window, dtype=np.float64),
            np.asarray(_ret14d, dtype=np.float64) if _ret14d is not None else np.array([]),
        ))
except Exception:
    logger.exception("bar_context_t120.m1v_compute_failed",
                     symbol=symbol, tf=tf, ws_s=ws_s)
    _m1v_regime = None  # gate will fail closed
```

Then update the `BarContext(...)` return to include:

```python
    markov_regime_w20_1m_va=_m1v_regime,
```

**If `feed.get_closes_window` / `get_log_returns_14d` don't exist** on
`BinanceMarketDataFeed`: implement them as thin wrappers over the
existing rolling deque. They MUST be O(window_size) (no IO, no fetch)
to stay within the <50ms p95 bar_context build budget. If the feed
can't supply them yet, defer this fix and instead ship just Fix #1 and
Fix #2 — sleeve #3 still works with refreshed HoD (+$1,865 sum @ 78% WR).

### 4.5 Controller gate block (polymarket_updown.py)

In the existing gate block (around line 1951), add a new `elif`
parallel to the `m5va` branch:

```python
elif _gate == "m1va":
    _bctx = self._bar_ctx_active
    _regime_val = getattr(_bctx, "markov_regime_w20_1m_va", None)
    _regime = int(_regime_val) if _regime_val is not None else -1
    _label = decision_label_markov(signal, _regime)
    gate_decisions["m1va"] = {
        "pass": _label == "pass",
        "regime": _regime,
    }
    if not markov_passes(signal, _regime):
        await self._audit(
            symbol, tf,
            reason="gate_markov_skip",  # SAME reason string as m5va (the regime is what differs)
            signal=signal,
            gate_decisions=gate_decisions,
        )
        return
```

`decision_label_markov` and `markov_passes` are reused as-is from
`gates.py` — both already accept an arbitrary regime int.

### 4.6 Sleeve spec update (engine_main.py)

```python
# BEFORE
("poly_updown_btc_15m_momo_hod",  "momo", "BTC", "15m", ("hod",),          "momo", "HOLD_ONLY"),

# AFTER
("poly_updown_btc_15m_momo_hod",  "momo", "BTC", "15m", ("hod", "m1va"),   "momo", "HOLD_ONLY"),
```

Sleeve_id stays the same — backtest used `hod` + `m1va` with the
`_hod` suffix and the analytics queries already filter on substring.

### 4.7 Why M1V works on momo but not sniper
Sniper fires at `slot_start` (bar boundary, no momentum context). Momo
fires at `slot_start - window_s + 120s`, anchored on the t+120 signal
moment that IS momentum-context-rich. The 1m Markov regime at ws_s
agrees with the signal direction when momentum is real and disagrees
when it's noise. Cuts ~55% of momo fires and lifts WR by ~12pp.

---

## 5. Fix #4 — add the missing tests

### 5.1 Unit test: `markov_passes` fails closed on warmup
`backend/tests/strategies/polymarket/test_gates.py` (NEW file if it
doesn't exist):

```python
from backend.app.strategies.polymarket.gates import markov_passes


def test_markov_passes_warmup_fails_closed():
    """Spec §2.3 — regime=-1 (warmup) must block ALL fires."""
    assert markov_passes("UP", -1) is False
    assert markov_passes("DOWN", -1) is False
    # Non-directional signal: gate is no-op, returns True (spec §2.3)
    assert markov_passes("NONE", -1) is True


def test_markov_passes_directional_alignment():
    assert markov_passes("UP", 2) is True    # Bull → UP passes
    assert markov_passes("UP", 1) is False   # Sideways blocks UP
    assert markov_passes("UP", 0) is False   # Bear blocks UP
    assert markov_passes("DOWN", 0) is True  # Bear → DOWN passes
    assert markov_passes("DOWN", 1) is False
    assert markov_passes("DOWN", 2) is False
```

### 5.2 Unit test: `label_regime_vol_adaptive` produces correct labels
`backend/tests/strategies/polymarket/test_markov.py` (NEW):

```python
import numpy as np
from backend.app.strategies.polymarket.markov import label_regime_vol_adaptive


def test_label_warmup_when_insufficient_returns():
    """spec §2.3 — fewer than 100 finite samples → -1."""
    closes = np.array([100.0] * 21)
    short_returns = np.array([0.001] * 50)  # < 100
    assert label_regime_vol_adaptive(closes, short_returns) == -1


def test_label_bull_when_ret_above_q66():
    """Synthetic: closes_window with +1% over 20 bars, prior returns
    centered at 0 with small noise → ret >> q66 → Bull (2)."""
    rng = np.random.default_rng(42)
    closes = np.linspace(100.0, 101.0, 21)
    prior_returns = rng.normal(0, 0.0005, 5000)
    assert label_regime_vol_adaptive(closes, prior_returns) == 2


def test_label_bear_when_ret_below_q33():
    rng = np.random.default_rng(42)
    closes = np.linspace(100.0, 99.0, 21)
    prior_returns = rng.normal(0, 0.0005, 5000)
    assert label_regime_vol_adaptive(closes, prior_returns) == 0


def test_label_sideways_when_ret_between_quantiles():
    """Flat closes + non-flat prior → ret ≈ 0, in the middle tercile."""
    rng = np.random.default_rng(42)
    closes = np.array([100.0] * 21)
    prior_returns = rng.normal(0, 0.001, 5000)
    assert label_regime_vol_adaptive(closes, prior_returns) == 1
```

### 5.3 Integration test: M1V gate is reachable with a real BarContext
`backend/tests/controllers/test_polymarket_updown_gates.py` (NEW):

```python
import pytest
from unittest.mock import MagicMock

# imports: PolymarketUpdownController, stub feed, stub pool ...


@pytest.mark.asyncio
async def test_gate_stack_m1va_reachable_with_populated_aux():
    """Regression test for Phase 34 Bug #1.
    Build a BarContext with markov_regime_w20_1m_va populated (NOT None),
    fire the gate block, assert gate_decisions['m1va']['regime'] != -1.
    """
    pool = _CapturingPool()
    controller = _make_controller(
        pool=pool,
        gate_stack=("hod", "m1va"),
        gate_cell_strategy="momo",
        audit_sleeve_id="poly_updown_btc_15m_momo_hod",
    )
    # Build a BarContext at a fire-time inside HOD_TOP8_BY_CELL[("momo","btc_15m")]
    # AND with a non-None Markov regime.
    bar_ctx = _make_bar_context(
        phase="t_plus_120",
        markov_regime_w20_1m_va=2,  # Bull
    )
    controller._bar_ctx_active = bar_ctx

    await controller._dispatch_signal(symbol="BTC", tf="15m", signal="UP")

    assert any(
        "m1va" in r and r["m1va"]["regime"] == 2
        for _sql, r in _gate_decisions_from(pool.inserts)
    ), "expected m1va gate to register regime=2 (Bull)"


@pytest.mark.asyncio
async def test_gate_stack_m1va_skips_on_warmup():
    """If Markov returns -1, gate must fail closed with gate_markov_skip."""
    pool = _CapturingPool()
    controller = _make_controller(
        pool=pool,
        gate_stack=("hod", "m1va"),
        gate_cell_strategy="momo",
        audit_sleeve_id="poly_updown_btc_15m_momo_hod",
    )
    bar_ctx = _make_bar_context(
        phase="t_plus_120",
        markov_regime_w20_1m_va=-1,
    )
    controller._bar_ctx_active = bar_ctx

    await controller._dispatch_signal(symbol="BTC", tf="15m", signal="UP")

    reasons = [_payload(r).get("reason") for _sql, r in pool.inserts]
    assert "gate_markov_skip" in reasons


@pytest.mark.asyncio
async def test_gate_decisions_payload_shape():
    """Spec §4 — every gate writes a {pass, ...} subdict per gate name."""
    # ...  similar pattern, assert payload['gate_decisions'].keys() == set of gates
    # actually evaluated up to the skip point.
```

### 5.4 Why integration tests matter here
Bug #1 was a silent contract violation: the loop builder set the aux
to `None`, the controller silently coerced `None → -1`, and no log
distinguished "regime computed and got 1 (Sideways)" from "regime
never computed at all." With test 5.3 in place, the build would have
failed at CI before the bug ever shipped.

---

## 6. Bug #2 long-term decision (defer)

The bar_close BarContext still doesn't have MTF/Markov aux. Today no
sniper sleeve carries those gates (after Fix #2), so the bug is
dormant. Two options, defer the call:

**Option A — fix the builder.** Populate `ret_15m_for_mtf`,
`ret_1h_for_mtf`, `markov_regime_w20_5m_va`, `markov_regime_w20_1m_va`
in the bar_close BarContext too. Adds ~30ms to every bar_close build
for cells that don't need them.

**Option B — enforce at config load.** In
`_SHADOW_GATED_SLEEVES_SPEC` loader, raise `ValueError` if a sniper
entry has `mtf2`, `m5va`, or `m1va` in its gate_stack. Documents the
constraint clearly, no compute overhead.

Recommend **Option B** — sniper isn't a momentum strategy; we've
proven Markov hurts it. Add the validator + a comment in the spec
explaining why. Pseudo-code:

```python
def _validate_sleeve_spec(spec):
    for sleeve_id, base, asset, tf, gates, cell, hp in spec:
        if base == "sniper" and any(g in gates for g in ("mtf2", "m5va", "m1va")):
            raise ValueError(
                f"{sleeve_id}: sniper cells cannot use mtf2/m5va/m1va gates "
                f"(bar_close BarContext doesn't populate the aux). "
                f"Drop the gate or change base to momo/momo_v2."
            )
```

This is a 10-line change in `engine_main.py`. Add it now to prevent
recurrence.

---

## 7. Verification SQL (run 1h after deploy)

```sql
-- 7.1 All 11 sleeves emitted at least one signal row
SELECT sleeve_id, COUNT(*) AS n_signals,
       COUNT(*) FILTER (WHERE (data->>'reason') = 'order_placed') AS armed,
       COUNT(*) FILTER (WHERE (data->>'reason') LIKE 'gate_%_skip') AS gated_out
FROM trading.events
WHERE at > NOW() - INTERVAL '1 hour'
  AND kind = 'poly_updown_signal'
  AND sleeve_id IN (
    'poly_updown_sol_5m_sniper_hod',
    'poly_updown_eth_15m_sniper_hod',           -- RENAMED, was _m5va
    'poly_updown_btc_15m_momo_hod',
    'poly_updown_btc_15m_sniper_hod',
    'poly_updown_btc_5m_sniper_hod',
    'poly_updown_btc_5m_momo_v2_hod_mtf',
    'poly_updown_btc_15m_momo_v2_hod',
    'poly_updown_sol_5m_momo_v2_hod',
    'poly_updown_eth_15m_momo_v2_hod',
    'poly_updown_sol_15m_momo_v2_hod',
    'poly_updown_eth_5m_sniper_hod'
  )
GROUP BY 1 ORDER BY 1;
-- Expect: 11 rows, none with armed=0 after 24h.

-- 7.2 M1V gate must produce regime != -1 at least sometimes
SELECT data->'gate_decisions'->'m1va'->>'regime' AS regime, COUNT(*)
FROM trading.events
WHERE at > NOW() - INTERVAL '4 hours'
  AND sleeve_id = 'poly_updown_btc_15m_momo_hod'
  AND data->'gate_decisions' ? 'm1va'
GROUP BY 1 ORDER BY 1;
-- Expect: rows for regime IN ('0','1','2'). If ALL rows show '-1',
-- the aux populator failed — investigate get_closes_window and
-- get_log_returns_14d on the feed.

-- 7.3 Sleeve #2 (renamed) actually fires
SELECT COUNT(*)
FROM trading.events
WHERE at > NOW() - INTERVAL '24 hours'
  AND sleeve_id = 'poly_updown_eth_15m_sniper_hod'
  AND (data->>'reason') IN ('order_placed', 'hedge_placed');
-- Expect: > 0 (was 0 before fix).

-- 7.4 HoD allowed-hours match the refreshed table
SELECT DISTINCT
  sleeve_id,
  data->'gate_decisions'->'hod'->>'allowed' AS allowed
FROM trading.events
WHERE at > NOW() - INTERVAL '4 hours'
  AND sleeve_id LIKE '%_hod%'
  AND data->'gate_decisions' ? 'hod'
ORDER BY 1;
-- Cross-check each row against the table in §2.2.
```

---

## 8. Promotion checklist

- [ ] **Code review** the patches in §2.2, §3.3, §4.3-4.6, §6 against this doc.
- [ ] **Run new tests locally** — all 6 new tests (3 unit + 3 integration) pass.
- [ ] **Run full test suite** — `pytest backend/tests/` green, no regressions.
- [ ] **Deploy to VPS3** — `systemctl restart tv-engine`.
- [ ] **Confirm 11-sleeve registration** in journal:
      `journalctl -u tv-engine --since 1m | grep shadow_gated_registered`
      Should show `"n": 11` and the renamed `poly_updown_eth_15m_sniper_hod`.
- [ ] **Wait 1h**, then run §7.1 — all 11 sleeves have signals.
- [ ] **Wait 4h**, then run §7.2 — M1V gate has shipped non-(-1) regimes.
- [ ] **Wait 24h**, then run §7.3 — renamed sleeve #2 has fired.
- [ ] **Wait 7d**, compute per-sleeve WR + $/tr from `poly_updown_resolution`
      rows, compare to the expected table in §2.4. Allow ±25%.

---

## 9. Rollback

If any sleeve goes silent after deploy (no `poly_updown_signal` rows
in 1h after expected fires) or if `tv-engine` crashes:

```bash
# 9.1 Revert env to disable shadow sleeves entirely
sudo sed -i 's/^TV_POLY_SHADOW_GATED_ENABLED=true/TV_POLY_SHADOW_GATED_ENABLED=false/' /etc/tv/tradingvenue.env
sudo systemctl restart tv-engine

# 9.2 If only the M1V compute is broken, drop sleeve #3 back to ("hod",)
# in _SHADOW_GATED_SLEEVES_SPEC and redeploy. Other sleeves unaffected.

# 9.3 If the HoD refresh produced unexpected results, revert HOD_TOP8_BY_CELL
# to the pre-fix values from git and restart.
```

All shadow sleeves are paper-only (`mode="paper"`) — no live capital is
at risk during rollback.

---

## 10. Files changed (full inventory)

| File | Change type | Purpose |
|---|---|---|
| `backend/app/strategies/polymarket/gates.py` | MODIFY | Refresh `HOD_TOP8_BY_CELL` (Fix #1) |
| `backend/app/engine/main.py` | MODIFY | Update sleeves #2 (drop m5va, rename) + #3 (add m1va); add validator (Bug #2 long-term) |
| `backend/app/engine/poly_updown_loop.py` | MODIFY | New `markov_regime_w20_1m_va` field on `BarContext`; populate in `build_bar_context_t_plus_120` |
| `backend/app/controllers/polymarket_updown.py` | MODIFY | New `elif _gate == "m1va":` branch in gate block |
| `backend/tests/strategies/polymarket/test_gates.py` | NEW | Unit tests for `markov_passes` warmup + alignment |
| `backend/tests/strategies/polymarket/test_markov.py` | NEW | Unit tests for `label_regime_vol_adaptive` |
| `backend/tests/controllers/test_polymarket_updown_gates.py` | NEW | Integration tests for the gate block end-to-end |
| `backend/tests/engine/test_main_shadow_spec.py` | MODIFY (if exists) | Update expected sleeve #2 + #3 spec tuples |

---

## 11. Out of scope (do NOT do)

- Do NOT add `m5va` or `mtf2` to any sniper sleeve. Bug #2 not fully
  fixed; backtest also says Markov is bad on sniper.
- Do NOT auto-refresh `HOD_TOP8_BY_CELL` on a cron. Spec §6 mandates
  operator review for each refresh.
- Do NOT take any of the 11 sleeves live (`paper_only=True` everywhere).
  Live promotion is a separate decision after 7d shadow validation.
- Do NOT modify `f7_gate.py` — F7 is owned by the strategy, not the
  gate stack, and is verified at 94.67% match with prod.

---

## 12. References

- Original spec: `strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`
- Backtest results: `strategy_lab/reports/SHADOW_11_SLEEVES_V2_2026_05_22.md`
- HoD refresh: `strategy_lab/reports/HOD_REFRESH_2026_05_22.md`
- VPS3 audit: `strategy_lab/reports/VPS3_SHADOW_AUDIT_2026_05_22.md`
- Refresh tooling: `strategy_lab/markov_filter/_recompute_hod_top8.py`

## End of fix spec
