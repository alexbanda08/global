# TV Fix Spec — SOL Poly Flow Anti-Gate

**Date:** 2026-05-27
**Target file (gate):** `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py`
**Target file (sleeves):** `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py`
**Target file (controller):** `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`
**Research source:** `strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md`

---

## 1. Background

New-gates research (2026-05-27, 5,000-fire sample across V5/V6/V7/V8 sleeves) tested Polymarket
aggressor trade flow as a gate signal. Family B — `net_flow = (UP_buys − UP_sells) − (DOWN_buys
− DOWN_sells)` in the 60s window before `fire_us` — showed strong asset-specific patterns.

**Critical SOL finding:** When Polymarket flow OPPOSES the SOL fire direction by ≥ 500 shares in
the 60s before `fire_us`, WR = **58.6%** (n=29, vs SOL baseline 77.1%, −18.49pp). This is a
high-value REJECTION signal.

Contrast: the same "contrarian" gate is a positive confirmation for ETH (+4.56pp, n=101) and
neutral for BTC (−1.04pp). The cross-asset average of +10.97pp obscures the SOL anti-signal
because BTC dominates sample size.

**Interpretation:** Polymarket sophisticated flow on SOL opposing our direction indicates informed
counterparties. When they fade us, we lose. When they agree or are quiet, our baseline edge holds.

---

## 2. Anti-Gate Definition

### 2.1 Gate function

Add to `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py` at the end of the
§3.30 / §3.31 block (after `g_vol_contracting`, before `__all__`):

```python
# =====================================================================
# §3.32 — SOL Polymarket aggressor flow REJECTION gate (TV_FIX_SOL_ANTIGATE_2026_05_27)
# =====================================================================
# Data source: TradeMirror rolling 60s trade-print history (token-keyed)
# Research: strategy_lab/reports/NEW_GATES_RESEARCH_2026_05_27.md §5
#
# Returns True when OPPOSING Polymarket aggressor flow exceeds threshold
# — this means REJECT the fire. Sleeves wire this gate inverted.
# =====================================================================

def g_poly_aggressor_anti_with(
    direction: str,
    fire_us: int,
    *,
    slug: str,
    poly_flow_mirror: Any,   # PolyFlowMirror — see §4 below
    window_s: int = 60,
    threshold_shares: int = 500,
    **_kw: Any,
) -> bool:
    """SOL anti-gate: True if opposing Polymarket aggressor flow >= threshold.

    Returns True  → fire is REJECTED (sleeve fails gate).
    Returns False → no strong opposing flow; sleeve proceeds normally.
    Returns False  on missing data (fail-open = no extra blocking).

    Logic:
        net_flow = (UP_buys - UP_sells) - (DOWN_buys - DOWN_sells)
          for the given slug in [fire_us - window_s*1e6, fire_us).
        Opposing means:
          direction=UP   → net_flow < -threshold_shares
          direction=DOWN → net_flow >  threshold_shares

    Research basis: n=29 SOL fires where this triggered → WR 58.6%
    (−18.49pp vs SOL baseline 77.1%).  Threshold $500 shares matches
    B2_REJECT_SOL recommendation in NEW_GATES_RESEARCH_2026_05_27.md §7.
    """
    if poly_flow_mirror is None:
        return False  # fail-open; no penalty when data missing
    try:
        net_flow = poly_flow_mirror.net_flow(
            slug=slug,
            before_us=fire_us,
            window_s=window_s,
        )
    except Exception:  # noqa: BLE001
        return False  # fail-open on any error
    if net_flow is None:
        return False
    if direction == "UP":
        return net_flow < -threshold_shares
    else:  # DOWN
        return net_flow > threshold_shares
```

Add `"g_poly_aggressor_anti_with"` to `__all__` at the bottom of `sniper_v5_gates.py`.

### 2.2 Gate semantics

**Anti-gate convention:** `g_poly_aggressor_anti_with` returns `True` when the fire should be
REJECTED. This is the OPPOSITE of normal gate semantics (True = pass). To wire it as a rejection
gate in a sleeve, the controller evaluation `all_pass = all_pass and ok` turns `ok=True` into
`all_pass=False`, which causes a skip. This is the correct behavior — no wrapper needed.

Pattern in `sniper_v5_sleeves.py`:

```python
GateRef(
    g_poly_aggressor_anti_with,
    (),  # static kwargs: none (window_s and threshold_shares use defaults)
    "g_poly_aggressor_anti_with",
),
```

When this gate fires (returns True), `skip_reason` in the JSONL log becomes
`"g_poly_aggressor_anti_with=False"` per the existing `_first_failing_gate` logic — but since the
semantics are inverted, add a note in `_build_gate_kwargs` so the shadow-log consumer can
interpret it: a `True` result on this specific gate IS the rejection. The JSONL entry will show
`"g_poly_aggressor_anti_with": true` in `gates_evaluated` when rejection triggered.

For clearer telemetry, add a sentinel `skip_reason` override in the controller. See §7.

---

## 3. Controller Wiring — `_build_gate_kwargs`

In `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`, add a routing entry in
`_build_gate_kwargs` (after the existing §3.31 block, before the final `return {}` fallback):

```python
# §3.32 — SOL Poly flow anti-gate
if name.startswith("g_poly_aggressor_anti_with"):
    return {
        "slug": slot.slug,
        "poly_flow_mirror": self._poly_flow_mirror,  # see §4
    }
```

Add `self._poly_flow_mirror` as a constructor parameter (see §4).

---

## 4. Data Source — PolyFlowMirror

### 4.1 Existing infrastructure

`TradeMirror` (`/opt/tradingvenue/backend/app/venues/polymarket/trade_mirror.py`) already
subscribes to Polymarket WS trade prints per token. It dispatches via a single async callback.
The maker-arb accumulator `acc_pc.py` already maintains a per-(slug, side) CVD window using this
feed. The controller uses `cvd_60s` from `BarContext` for momo CVD gates.

**However**, the sniper-v5 gate needs a synchronous, per-slug net-flow query at arbitrary
`fire_us` timestamps. No existing class exposes `net_flow(slug, before_us, window_s)` for sniper
use.

### 4.2 New class: `PolyFlowMirror`

Create `/opt/tradingvenue/backend/app/venues/polymarket/poly_flow_mirror.py`:

```python
"""PolyFlowMirror — rolling per-slug Polymarket aggressor flow aggregator.

Subscribes to TradeMirror trade-print callback. Maintains a per-slug
deque of (timestamp_us, net_delta_shares) where:
    net_delta_shares = +size  if aggressor="buy" on UP token
                     = -size  if aggressor="sell" on UP token
                     = -size  if aggressor="buy" on DOWN token
                     = +size  if aggressor="sell" on DOWN token

net_flow(slug, before_us, window_s) returns cumulative net delta in
[before_us - window_s*1e6, before_us). Pure synchronous — safe for
gate dispatch.

Memory: capped at 2000 events per slug (ring buffer via maxlen deque).
Retention window: 120s of data at ~10 trades/s per slug = ~1200 events
comfortably within cap.
"""
from __future__ import annotations

import collections
from typing import Any

class PolyFlowMirror:
    """Aggregator for per-slug Polymarket net aggressor flow."""

    def __init__(self, maxlen: int = 2000) -> None:
        # slug -> deque of (timestamp_us: int, net_delta: float)
        self._rings: dict[str, collections.deque[tuple[int, float]]] = {}
        self._maxlen = maxlen

    def register_slug(self, slug: str, token_id_up: str, token_id_dn: str) -> None:
        """Register a slug's UP/DOWN token mapping for flow attribution."""
        self._slug_to_up[slug] = token_id_up
        self._slug_to_dn[slug] = token_id_dn
        if slug not in self._rings:
            self._rings[slug] = collections.deque(maxlen=self._maxlen)

    def on_trade_print(self, tp: Any) -> None:
        """Called synchronously from TradeMirror callback. tp: TradePrint."""
        # TradePrint has: slug, side ("YES"/"NO" = UP/DOWN token),
        # size (shares), aggressor ("buy"/"sell"), timestamp_us (int μs)
        slug = tp.slug
        if slug not in self._rings:
            return
        # net_delta: positive = net UP pressure
        if tp.side == "YES":  # UP token
            delta = tp.size if tp.aggressor == "buy" else -tp.size
        else:  # DOWN token
            delta = -tp.size if tp.aggressor == "buy" else tp.size
        self._rings[slug].append((tp.timestamp_us, delta))

    def net_flow(
        self, *, slug: str, before_us: int, window_s: int = 60,
    ) -> float | None:
        """Sum net delta in [before_us - window_s*1e6, before_us).

        Returns None if slug unknown or ring is empty.
        """
        ring = self._rings.get(slug)
        if not ring:
            return None
        cutoff_us = before_us - window_s * 1_000_000
        total = 0.0
        found = False
        for ts_us, delta in ring:
            if cutoff_us <= ts_us < before_us:
                total += delta
                found = True
        return total if found else 0.0  # 0.0 = no trades = no opposing flow
```

### 4.3 Wiring in `main.py`

In the sniper-v5 boot block (around line 2287 where `PolymarketSniperV5Controller` is
instantiated):

1. Instantiate `PolyFlowMirror`:
   ```python
   from backend.app.venues.polymarket.poly_flow_mirror import PolyFlowMirror
   _poly_flow_mirror = PolyFlowMirror()
   ```

2. Register the TradeMirror callback (if `TradeMirror` is already instantiated for maker-arb,
   reuse it; otherwise instantiate one):
   ```python
   # Route trade prints to PolyFlowMirror
   _trade_mirror.set_trade_callback(_poly_flow_mirror.on_trade_print)
   # OR if maker-arb already owns the callback, daisy-chain:
   # _trade_mirror.add_trade_callback(_poly_flow_mirror.on_trade_print)
   ```

3. Pass to controller:
   ```python
   _sniper_v5_controller = PolymarketSniperV5Controller(
       panels=_sniper_v5_panels,
       book_mirror=book_mirror,
       shadow_logger=_sniper_v5_logger,
       settings=settings,
       poly_flow_mirror=_poly_flow_mirror,   # NEW
       ...
   )
   ```

4. Register slugs on slot discovery (in the slot-discovery hook already present for BookMirror
   subscriptions, add):
   ```python
   _poly_flow_mirror.register_slug(slug, token_id_up, token_id_dn)
   ```

**Note on TradeMirror callback conflict:** If maker-arb already holds the single callback slot,
`TradeMirror` needs a `add_trade_callback` fan-out. This is a one-line change to `TradeMirror`
to hold a list of callbacks instead of one. Alternative: subclass and intercept. TV to decide
based on existing maker-arb wiring.

---

## 5. Sleeve Modifications

Add the anti-gate `GateRef` to **all 20 SOL sleeves**. The gate is appended LAST in each gate
tuple (evaluated after existing gates so they short-circuit first on cheaper checks).

### Pattern

```python
# BEFORE (example — sol_5m_rf_tr_pp_mid, line 280):
gates=(
    GateRef(g_rf_strict_align, (("asset", "SOL"),), "g_rf_strict_align(SOL)"),
    GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
    GateRef(g_tr_above_pp, (("asset", "SOL"),), "g_tr_above_pp(SOL)"),
    GateRef(g_tr_partial_stack_with, (("asset", "SOL"),), "g_tr_partial_stack_with(SOL)"),
),

# AFTER:
gates=(
    GateRef(g_rf_strict_align, (("asset", "SOL"),), "g_rf_strict_align(SOL)"),
    GateRef(g_tr_above_ema200, (("asset", "SOL"),), "g_tr_above_ema200(SOL)"),
    GateRef(g_tr_above_pp, (("asset", "SOL"),), "g_tr_above_pp(SOL)"),
    GateRef(g_tr_partial_stack_with, (("asset", "SOL"),), "g_tr_partial_stack_with(SOL)"),
    GateRef(g_poly_aggressor_anti_with, (), "g_poly_aggressor_anti_with"),  # SOL anti-gate
),
```

### Complete sleeve list

| Sleeve ID (sniper_v5_sleeves.py line) | Version | TF |
|---|---|---|
| `poly_sniper_v5_sol_5m_depth_up_hod_session` (L263) | V5 #06 | 5m |
| `poly_sniper_v5_sol_5m_rf_tr_pp_mid` (L280) | V5 #07 | 5m |
| `poly_sniper_v5_sol_5m_rf_tr_partial_mid` (L297) | V5 #08 | 5m |
| `poly_sniper_v5_sol_15m_trstack_vol_ribbon_ema_mid` (L405) | V5 #15 | 15m |
| `poly_sniper_v5_sol_15m_rfaged_trstack_late` (L423) | V5 #16 | 15m |
| `poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6` (L478) | V6 | 5m |
| `poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6` (L492) | V6 | 5m |
| `poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6` (L505) | V6 | 5m |
| `poly_sniper_v5_sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6` (L583) | V6 | 15m |
| `poly_sniper_v5_sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6` (L597) | V6 | 15m |
| `poly_sniper_v5_sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6` (L611) | V6 | 15m |
| `poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7` (L715) | V7 | 5m |
| `poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7` (L727) | V7 | 5m |
| `poly_sniper_v5_sol_15m_btc_slope_pair_v7` (L754) | V7 | 15m |
| `poly_sniper_v5_sol_15m_btc_adx_btcvollow_v7` (L770) | V7 | 15m |
| `poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8` (L864) | V8 | 5m |
| `poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8` (L877) | V8 | 5m |
| `poly_sniper_v5_sol_15m_v7s5_plus_eth1h_adx_v8` (L919) | V8 | 15m |
| `poly_sniper_v5_sol_15m_v7_base_s5_slope_str_v8` (L935) | V8 | 15m |
| `poly_sniper_v5_sol_15m_v6_j_btceth_vollow_l_ethadx_v8` (L950) | V8 | 15m |

Total: **20 SOL sleeves**.

---

## 6. Rejection Semantics

`g_poly_aggressor_anti_with` returns `True` = reject. The controller gate loop:

```python
ok = bool(gate_ref.gate(direction, fire_us, **runtime_kwargs, **static_kwargs))
gates_evaluated[gate_ref.name] = ok
if not ok:
    all_pass = False
```

Wait — `True` from the anti-gate means REJECT, but the controller interprets `True` = PASS. The
gate must be written inverted: it returns `False` when opposing flow triggers (to FAIL the gate)
and `True` when safe to proceed.

**Corrected semantics:**

```python
def g_poly_aggressor_anti_with(...) -> bool:
    """Returns False (FAIL) when opposing flow >= threshold → sleeve SKIPS.
    Returns True (PASS) when flow is safe → sleeve proceeds.
    Returns True on missing data (fail-open).
    """
    ...
    if direction == "UP":
        triggered = net_flow < -threshold_shares
    else:
        triggered = net_flow > threshold_shares
    return not triggered  # False = reject, True = pass
```

When the gate returns `False` (rejection triggered):
- `all_pass = False`
- `skip_reason = "g_poly_aggressor_anti_with=False"` (via `_first_failing_gate`)
- `gates_evaluated["g_poly_aggressor_anti_with"] = False`

The name `g_poly_aggressor_anti_with=False` in `skip_reason` is self-documenting: the anti-gate
fired (opposing flow found), so we skipped.

---

## 7. Telemetry

The existing sniper-v5 JSONL log (`<UTC-date>.jsonl`) already records:
- `skip_reason: "<gate_name>=False"` when any gate fails
- `gates_evaluated: {"g_poly_aggressor_anti_with": false}` when anti-gate triggered

For targeted monitoring, add a structlog emit in the controller's gate loop when this specific
gate triggers (optional, in `polymarket_sniper_v5.py`):

```python
if gate_ref.name == "g_poly_aggressor_anti_with" and not ok:
    log.info(
        "sniper_v5.sol_anti_gate_triggered",
        sleeve_id=sleeve.sleeve_id,
        slug=slot.slug,
        direction=direction,
        fire_us=fire_us,
        skip_reason="sol_poly_flow_anti_triggered",
    )
```

This gives a dedicated `skip_reason="sol_poly_flow_anti_triggered"` in the structlog stream for
dashboard querying. The JSONL row still records `skip_reason="g_poly_aggressor_anti_with=False"`.

To query post-deploy:
```bash
jq 'select(.skip_reason == "g_poly_aggressor_anti_with=False")' /var/log/tradingvenue/sniper_v5/*.jsonl | wc -l
```

---

## 8. Acceptance Criteria

1. **All 20 SOL sleeves** have `GateRef(g_poly_aggressor_anti_with, (), "g_poly_aggressor_anti_with")`
   appended to their `gates` tuple.

2. **`g_poly_aggressor_anti_with`** exists in `sniper_v5_gates.py` and is in `__all__`.

3. **`_build_gate_kwargs`** routes `g_poly_aggressor_anti_with` to `{"slug": ..., "poly_flow_mirror": ...}`.

4. **`PolyFlowMirror`** instantiated at boot, wired to TradeMirror callback, slug-registered on
   slot discovery.

5. **JSONL** contains entries with `skip_reason: "g_poly_aggressor_anti_with=False"` appearing
   for SOL sleeves within 24h of deploy.

6. **No BTC/ETH sleeves** receive this gate (SOL only).

7. **Post-deploy SOL WR** (measured over ≥ 200 fires, ~2-3 weeks): target ≥ +5pp vs pre-deploy
   baseline. The research sample had −18.49pp on the rejected cohort (14.8% SOL fire coverage at
   $2k threshold; 29/~196 SOL fires in sample at $500). Expected WR improvement: ~3-5pp lift from
   filtering the 58.6% cohort.

---

## 9. Tests

### 9.1 Unit test — `g_poly_aggressor_anti_with`

File: `tests/strategies/polymarket/test_sol_anti_gate.py`

```python
import pytest
from unittest.mock import MagicMock

from backend.app.strategies.polymarket.sniper_v5_gates import g_poly_aggressor_anti_with

def _make_mirror(net_flow_value):
    m = MagicMock()
    m.net_flow.return_value = net_flow_value
    return m

def test_up_fire_opposing_flow_rejects():
    """net_flow = -600 (strong DOWN flow) opposing UP fire → gate returns False (reject)."""
    mirror = _make_mirror(-600.0)
    result = g_poly_aggressor_anti_with("UP", 1_000_000_000, slug="btc-up-5m-1234",
                                         poly_flow_mirror=mirror, window_s=60, threshold_shares=500)
    assert result is False  # gate fails → sleeve skips

def test_up_fire_aligned_flow_passes():
    """net_flow = +800 (UP flow) → gate returns True (pass)."""
    mirror = _make_mirror(800.0)
    result = g_poly_aggressor_anti_with("UP", 1_000_000_000, slug="btc-up-5m-1234",
                                         poly_flow_mirror=mirror)
    assert result is True

def test_down_fire_opposing_flow_rejects():
    """net_flow = +600 (UP flow) opposing DOWN fire → gate returns False (reject)."""
    mirror = _make_mirror(600.0)
    result = g_poly_aggressor_anti_with("DOWN", 1_000_000_000, slug="btc-up-5m-1234",
                                          poly_flow_mirror=mirror, threshold_shares=500)
    assert result is False

def test_below_threshold_passes():
    """net_flow = -200 opposing UP but below $500 threshold → gate passes."""
    mirror = _make_mirror(-200.0)
    result = g_poly_aggressor_anti_with("UP", 1_000_000_000, slug="btc-up-5m-1234",
                                         poly_flow_mirror=mirror, threshold_shares=500)
    assert result is True

def test_missing_mirror_fails_open():
    """poly_flow_mirror=None → gate returns True (fail-open, no blocking)."""
    result = g_poly_aggressor_anti_with("UP", 1_000_000_000, slug="btc-up-5m-1234",
                                         poly_flow_mirror=None)
    assert result is True  # fail-open

def test_mirror_exception_fails_open():
    """Mirror raises → gate returns True (fail-open)."""
    mirror = MagicMock()
    mirror.net_flow.side_effect = RuntimeError("ws dead")
    result = g_poly_aggressor_anti_with("UP", 1_000_000_000, slug="btc-up-5m-1234",
                                         poly_flow_mirror=mirror)
    assert result is True
```

### 9.2 Integration test — replay known losing SOL fire

Using a canonical SOL fire from `strategy_lab/sniper_search_2026_05_27/` where:
- SOL direction = UP
- Fire was a loss
- `trades_polymarket/sol.parquet` shows net DOWN flow ≥ 500 shares in the 60s before `fire_us`

Verify: with anti-gate active, `FireResult.skip_reason == "g_poly_aggressor_anti_with=False"`.

The research report §5 identifies 29 such events in the sample. Pick any with `outcome=0` and
`asset=SOL` where the B2 contrarian gate was True — these are the known rejects.

---

## 10. Implementation Checklist

- [ ] Add `g_poly_aggressor_anti_with` to `sniper_v5_gates.py` (after `g_vol_contracting`)
- [ ] Add to `__all__` in `sniper_v5_gates.py`
- [ ] Create `poly_flow_mirror.py` with `PolyFlowMirror` class
- [ ] Add `poly_flow_mirror` parameter to `PolymarketSniperV5Controller.__init__`
- [ ] Add routing in `_build_gate_kwargs` for `g_poly_aggressor_anti_with`
- [ ] Add optional structlog emit for `sol_poly_flow_anti_triggered` skip
- [ ] Append anti-gate `GateRef` to all 20 SOL sleeves in `sniper_v5_sleeves.py`
- [ ] Wire `PolyFlowMirror` in `main.py` boot block
- [ ] Wire TradeMirror → `PolyFlowMirror.on_trade_print` callback
- [ ] Register slugs on slot discovery
- [ ] Add unit tests
- [ ] Shadow-deploy 48h, check JSONL for `g_poly_aggressor_anti_with=False` entries
- [ ] After 200+ SOL fires, compare WR to pre-deploy baseline

---

## 11. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| TradeMirror callback fan-out conflict with maker-arb | Add `add_trade_callback` list to TradeMirror; maker-arb and PolyFlowMirror both register |
| PolyFlowMirror cold start (first 60s has no data) | Fail-open: `net_flow` returns 0.0 → gate passes → no blocking during warmup |
| SOL has thin trade volume → n=29 in research sample | Gate is fail-open on missing data; blocks only when threshold definitively exceeded |
| Threshold too sensitive ($500) vs original $2k recommendation | Research used $500 for SOL-specific analysis. Start at $500, monitor skip rate; raise to $1k if blocking >20% of SOL fires |
| Research sample covers Apr 24 – May 26 only (1 month) | Accept. The −18.49pp is a strong signal. Validate live over 2 weeks before treating as stable |
