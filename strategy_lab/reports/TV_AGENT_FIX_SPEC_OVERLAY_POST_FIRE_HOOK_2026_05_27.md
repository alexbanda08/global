# Spec — clean overlay-filter refactor (Option C: post-fire hook)

_Replaces the current overlay shadow controllers with a single post-fire hook that mirrors production fires under the shadow sleeve_id when the extra gate passes. Eliminates the wrapped-base_strategy-returns-NONE bug from `IDLE_SLEEVES_DIAGNOSIS_2026_05_27.md` § Group 2._

## Goal

After production parent emits a `poly_updown_signal` event for a sleeve like `poly_updown_eth_15m_sniper_hod` with `signal = UP/DOWN`:

1. **For each overlay configured against that parent sleeve_id**, evaluate the overlay's gate against the SAME `BarContext` that produced the parent fire.
2. **If the gate passes**, write a mirror `poly_updown_signal` event under the shadow sleeve_id (e.g. `shadow_poly_updown_eth_15m_sniper_m5v`) with the SAME direction, slug, ts, condition_id, and place a paper-mode order via the existing paper executor.
3. **If the gate fails**, write a single optional `poly_updown_overlay_skipped` audit event (low-volume — only one per parent fire, not per heartbeat). Do not write a `no_signal` heartbeat.

End state: overlay sleeves carry **real fires only**, count `~15–25 % of parent fire count` per sleeve (matching backtest selectivity).

## Architecture

```
[ production controller for parent sleeve, e.g. sniper_hod ]
   on_bar_close()
     ↓
   base_strategy.signal() → UP / DOWN
     ↓
   build_bar_context_*()    ← features (fair_edge_bp, markov_regime_w20_5m_va, ...) live here
     ↓
   emit("poly_updown_signal", sleeve_id="poly_updown_eth_15m_sniper_hod",
        data={ signal:"UP", slug, vwap, shares, fair_edge_bp, ... })
     ↓                                    ┐
   place order via paper executor          │
     ↓                                    │
   ───────── NEW HOOK BOUNDARY ─────────   │
     ↓                                    │
   for ovl in OVERLAY_HOOKS["poly_updown_eth_15m_sniper_hod"]:
     if ovl.gate_passes(direction, bar_ctx):
       emit("poly_updown_signal", sleeve_id=ovl.shadow_sleeve_id,
            data={ signal:<same direction>, slug, vwap, shares, ...,
                   parent_event_id, gate_kind, gate_decisions })
       paper_exec_mirror.place(...)
     else:
       (optional) emit("poly_updown_overlay_skipped", sleeve_id=ovl.shadow_sleeve_id,
                       data={ slug, parent_event_id, gate_kind, gate_decisions })
```

No standalone shadow controller for overlay sleeves. No separate `OverlayFilterStrategy.signal()` call path. Production controller emits its fire, then synchronously (or via an in-process task) runs the overlay hook.

## Components

### 1. `OverlayHook` — pure-function gate evaluator

New module: `backend/app/strategies/polymarket/overlay_hooks.py`.

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Callable

from backend.app.engine.poly_updown_loop import BarContext

GateKind = Literal[
    "m5v_pass",
    "m1v_AND_m5v",
    "fairedge500",
    "fairedge500_cvd30",
    "cvd_macd",
]


@dataclass(frozen=True)
class OverlayHook:
    """Single post-fire mirror rule.

    Subscribes to one parent sleeve_id. When the parent fires UP/DOWN,
    evaluates the gate predicate against the same BarContext. If the gate
    passes, the engine writes a mirror event under shadow_sleeve_id.
    """
    parent_sleeve_id: str
    shadow_sleeve_id: str
    gate_kind: GateKind
    # Optional override; default = derived from gate_kind
    regime_field: str = "markov_regime_w20_5m_va"

    def gate_passes(self, direction: str, bctx: BarContext) -> tuple[bool, dict]:
        """Evaluate the gate. Returns (passes, decisions_dict).

        decisions_dict is logged for audit. Must contain only scalars / strings.
        """
        d: dict = {"gate_kind": self.gate_kind, "direction": direction}

        # --- m5v_pass / m1v_AND_m5v: Markov regime agrees with direction ---
        if self.gate_kind in ("m5v_pass", "m1v_AND_m5v"):
            m5v = getattr(bctx, "markov_regime_w20_5m_va", None)
            d["m5v_regime"] = m5v
            m5v_ok = (
                (direction == "UP"   and m5v == 2)
                or (direction == "DOWN" and m5v == 0)
            )
            if self.gate_kind == "m5v_pass":
                d["m5v_pass"] = m5v_ok
                return m5v_ok, d
            # m1v_AND_m5v
            m1v = getattr(bctx, "markov_regime_w20_1m_va", None)
            d["m1v_regime"] = m1v
            m1v_ok = (
                (direction == "UP"   and m1v == 2)
                or (direction == "DOWN" and m1v == 0)
            )
            d["m5v_pass"] = m5v_ok
            d["m1v_pass"] = m1v_ok
            return (m5v_ok and m1v_ok), d

        # --- fair_edge gates ---
        if self.gate_kind in ("fairedge500", "fairedge500_cvd30"):
            fe_up = getattr(bctx, "fair_edge_bp_up", None)
            fe_dn = getattr(bctx, "fair_edge_bp_down", None)
            fe = fe_up if direction == "UP" else fe_dn
            d["fair_edge_bp"] = fe
            if fe is None:
                d["reason"] = "fair_edge_unavailable"
                return False, d
            fe_ok = fe > 500
            d["fairedge500"] = fe_ok
            if self.gate_kind == "fairedge500":
                return fe_ok, d
            # fairedge500_cvd30
            cvd_30s = getattr(bctx, "cvd_30s", None)
            d["cvd_30s"] = cvd_30s
            if cvd_30s is None:
                d["reason"] = "cvd_unavailable"
                return False, d
            cvd_ok = (
                (direction == "UP"   and cvd_30s > 0)
                or (direction == "DOWN" and cvd_30s < 0)
            )
            d["cvd_agree_30s"] = cvd_ok
            return (fe_ok and cvd_ok), d

        # --- cvd_macd ---
        if self.gate_kind == "cvd_macd":
            cvd_30s = getattr(bctx, "cvd_30s", None)
            macd = getattr(bctx, "macd_hist", None)
            d["cvd_30s"] = cvd_30s
            d["macd_hist"] = macd
            if cvd_30s is None or macd is None:
                d["reason"] = "cvd_or_macd_unavailable"
                return False, d
            cvd_ok = (
                (direction == "UP"   and cvd_30s > 0)
                or (direction == "DOWN" and cvd_30s < 0)
            )
            macd_ok = (
                (direction == "UP"   and macd > 0)
                or (direction == "DOWN" and macd < 0)
            )
            d["cvd_agree_30s"] = cvd_ok
            d["macd_agree"] = macd_ok
            return (cvd_ok and macd_ok), d

        raise ValueError(f"unknown gate_kind: {self.gate_kind}")


# Configured at engine boot from env / spec.
# parent_sleeve_id → list[OverlayHook]   (allows multiple overlays per parent)
OVERLAY_HOOKS: dict[str, list[OverlayHook]] = {}


def register_overlay_hook(hook: OverlayHook) -> None:
    OVERLAY_HOOKS.setdefault(hook.parent_sleeve_id, []).append(hook)


def get_overlay_hooks_for(parent_sleeve_id: str) -> list[OverlayHook]:
    return OVERLAY_HOOKS.get(parent_sleeve_id, [])
```

### 2. Engine-boot registration

New file: `backend/app/strategies/polymarket/_overlay_hook_spec.py`:

```python
from .overlay_hooks import OverlayHook, register_overlay_hook


# 6 overlays — mirror of the deprecated _SHADOW9_FADE_OVERLAY_POLY_UPDOWN_SLEEVE_IDS
# Order: parent_sleeve_id, shadow_sleeve_id, gate_kind
_OVERLAY_HOOKS = (
    # 1. m5v pass on eth 15m sniper (strict winner from backtest)
    (
        "poly_updown_eth_15m_sniper_hod",
        "shadow_poly_updown_eth_15m_sniper_m5v",
        "m5v_pass",
    ),
    # 2. fair_edge > 500 on btc 5m momo_v2 — biggest sample
    (
        "poly_updown_btc_5m_momo_v2_HOLD_f7",
        "shadow_poly_updown_btc_5m_momo_v2_fairedge500",
        "fairedge500",
    ),
    # 3. fair_edge > 500 + cvd_30s on btc 15m momo_v2
    (
        "poly_updown_btc_15m_momo_v2_HOLD_f7",
        "shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30",
        "fairedge500_cvd30",
    ),
    # 4. fair_edge > 500 on sol 15m sniper
    (
        "poly_updown_sol_15m_sniper_hod",
        "shadow_poly_updown_sol_15m_sniper_fairedge500",
        "fairedge500",
    ),
    # 5. m5v pass on sol 5m momo_v1
    (
        "poly_updown_sol_5m_momo_HOLD_f7",
        "shadow_poly_updown_sol_5m_momo_v1_m5v",
        "m5v_pass",
    ),
    # 6. cvd + macd on sol 5m momo_v2
    (
        "poly_updown_sol_5m_momo_v2_HOLD_f7",
        "shadow_poly_updown_sol_5m_momo_v2_cvd_macd",
        "cvd_macd",
    ),
)


def register_all_overlay_hooks() -> None:
    """Called once at engine boot (engine/main.py lifespan)."""
    for parent_sid, shadow_sid, gate_kind in _OVERLAY_HOOKS:
        register_overlay_hook(
            OverlayHook(
                parent_sleeve_id=parent_sid,
                shadow_sleeve_id=shadow_sid,
                gate_kind=gate_kind,
            )
        )
```

Hooked into `engine/main.py` lifespan:

```python
from backend.app.strategies.polymarket._overlay_hook_spec import register_all_overlay_hooks
...
async def lifespan(app):
    ...
    if os.getenv("TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED", "false").lower() == "true":
        register_all_overlay_hooks()
    ...
```

(Reuses the existing env flag — no new flag needed.)

### 3. Fire-emit hook in the controller

Insert into `backend/app/controllers/polymarket_updown.py`, immediately AFTER the production audit-write of a `poly_updown_signal` event. Look for the line that writes the `INSERT INTO trading.events` (the `_audit_write` method), right after the production order is placed.

```python
# Existing production audit write:
await self._audit_write(
    kind="poly_updown_signal",
    sleeve_id=self.sleeve_id,
    data={
        "signal": direction,
        "slug": slug,
        "vwap": vwap,
        "shares": shares,
        "fair_edge_bp": getattr(bctx, "fair_edge_bp_up" if direction == "UP" else "fair_edge_bp_down", None),
        # ... existing fields ...
    },
)
parent_event_id = ...  # capture if _audit_write returns event_id

# ── NEW: overlay hook ─────────────────────────────────────────────────────
if direction in ("UP", "DOWN"):
    from backend.app.strategies.polymarket.overlay_hooks import get_overlay_hooks_for

    for ovl in get_overlay_hooks_for(self.sleeve_id):
        try:
            passes, decisions = ovl.gate_passes(direction, bctx)
        except Exception:
            logger.exception(
                "overlay_hook.gate_eval_failed",
                parent_sleeve_id=self.sleeve_id,
                shadow_sleeve_id=ovl.shadow_sleeve_id,
                gate_kind=ovl.gate_kind,
            )
            continue

        if passes:
            # Mirror the fire under the shadow sleeve_id.
            await self._audit_write(
                kind="poly_updown_signal",
                sleeve_id=ovl.shadow_sleeve_id,
                data={
                    **<copy of production event data>,
                    "parent_event_id": parent_event_id,
                    "parent_sleeve_id": self.sleeve_id,
                    "gate_kind": ovl.gate_kind,
                    "gate_decisions": decisions,
                    "strategy_mode": f"overlay_{ovl.gate_kind}",
                    "mode": "paper",
                },
            )
            # Place a SHADOW paper order via the shadow paper executor.
            await self._shadow_paper_exec.place(
                sleeve_id=ovl.shadow_sleeve_id,
                slug=slug, direction=direction,
                stake_usd=25.0,
            )
        else:
            # Low-volume audit event: 1 per gate miss, NOT per slot.
            await self._audit_write(
                kind="poly_updown_overlay_skipped",
                sleeve_id=ovl.shadow_sleeve_id,
                data={
                    "parent_event_id": parent_event_id,
                    "parent_sleeve_id": self.sleeve_id,
                    "gate_kind": ovl.gate_kind,
                    "gate_decisions": decisions,
                    "direction": direction,
                    "slug": slug,
                },
            )
```

The `_shadow_paper_exec` is a new instance of the existing `PolyPaperExecutor`. Constructed once at engine boot with `mode="paper"`. The same executor handles all 6 overlay shadow sleeves (each fire passes its own `sleeve_id`).

### 4. Resolution handling

No code change needed. The existing `poly_updown_resolution` writer is keyed on `(slug, sleeve_id)`. When the parent's slot resolves, the resolver iterates all `poly_updown_signal` events with that slug — production AND shadow — and writes one `poly_updown_resolution` per `(slug, sleeve_id)` tuple. Shadow resolutions then appear automatically.

Verify: `backend/app/services/poly_resolution_writer.py` (or equivalent) `SELECT DISTINCT sleeve_id FROM trading.events WHERE kind='poly_updown_signal' AND slug=$1` — should pick up shadow_sleeve_ids without change.

### 5. Deprecate the existing overlay shadow controllers

Remove the 6 overlay shadow controllers from the spawn list. They currently emit 271-817 heartbeats per sleeve per 3 days for no benefit.

In `backend/app/engine/main.py`, find where overlay sleeves get controllers spawned (currently part of the `shadow9_fade_overlay_registered` event group). Skip the OverlayFilterStrategy controllers — only spawn the FadeCompanionStrategy controllers for the FADE sleeves.

In `backend/app/api/bots.py`, the `_SHADOW9_FADE_OVERLAY_POLY_UPDOWN_SLEEVE_IDS` tuple stays as-is so the dashboard knows about them. The overlay sleeve_ids are still registered for display + chart purposes.

In `backend/app/strategies/polymarket/shadow9.py`, mark `OverlayFilterStrategy` `@deprecated` but keep it in the file for at least one release in case any other code paths reference it.

## Required BarContext fields (verify all present)

From `backend/app/engine/poly_updown_loop.py:164-216`:

| field on BarContext | populated by | used by gate |
|---|---|---|
| `markov_regime_w20_5m_va: int \| None` | Phase 34 m1va builder + 5m variant | `m5v_pass`, `m1v_AND_m5v` |
| `markov_regime_w20_1m_va: int \| None` | Phase 34 m1va builder | `m1v_AND_m5v` |
| `fair_edge_bp_up: float \| None` | Phase 36 builder line 1196 | `fairedge500`, `fairedge500_cvd30` |
| `fair_edge_bp_down: float \| None` | Phase 36 builder | `fairedge500`, `fairedge500_cvd30` |
| `cvd_30s: float \| None` | Phase 36 builder (1s feed) | `fairedge500_cvd30`, `cvd_macd` |
| `macd_hist: float \| None` | Phase 36 builder | `cvd_macd` |

If the production sniper/momo controllers DON'T currently call the Phase 36 builder (they use their own legacy `build_bar_context_t_plus_120` etc.), the Phase 36 features won't be on bctx. Two paths:

**A. Switch parent controllers to also call Phase 36 builder.** Cleanest. Add Phase 36 feature population to `build_bar_context_t_plus_120` so the production sniper_hod gets `fair_edge_bp_up/down`, `cvd_30s`, `macd_hist` populated on every fire.

**B. Build a side-car Phase 36 BarContext in the hook itself**, separately from the production one. Run `_compute_phase36_features(sym, ws_s)` synchronously inside the hook. Adds latency but avoids touching parent controllers.

**Recommendation: A**. The Phase 36 features are already computable from `feed.vwap_store` / `feed._bars` (in-memory, no IO). Adding ~5 lines to `build_bar_context_t_plus_120` to populate them is cheaper than running them again in the hook for every parent fire.

Verify which path the existing parents use:

```bash
ssh vps3
grep -n 'build_bar_context_t_plus' /opt/tradingvenue/backend/app/controllers/polymarket_updown.py | head -20
```

If sniper_hod uses `build_bar_context_t_plus_120` (line 411 in `poly_updown_loop.py`), patch that builder to also populate `fair_edge_bp_up/down`, `cvd_30s`, `macd_hist`.

## DB schema — event payload contract

### `kind = 'poly_updown_signal'` (mirror fire)

```json
{
  "tf": "15m",
  "mode": "paper",
  "signal": "UP",
  "slug": "eth-updown-15m-1779799200",
  "symbol": "ETH",
  "vwap": 0.62,
  "shares": 40.3,
  "fair_edge_bp": 1247,
  "cvd_30s": 1234567.89,
  "macd_hist": 0.42,
  "markov_regime_w20_5m_va": 2,
  "parent_event_id": "<uuid of production fire>",
  "parent_sleeve_id": "poly_updown_eth_15m_sniper_hod",
  "gate_kind": "m5v_pass",
  "gate_decisions": {"m5v_regime": 2, "m5v_pass": true},
  "strategy_mode": "overlay_m5v_pass"
}
```

### `kind = 'poly_updown_overlay_skipped'` (optional audit)

```json
{
  "slug": "...", "direction": "UP",
  "parent_event_id": "...", "parent_sleeve_id": "...",
  "gate_kind": "fairedge500_cvd30",
  "gate_decisions": {"fair_edge_bp": 320, "fairedge500": false, "cvd_30s": null, "reason": "fair_edge_too_low"}
}
```

Use a NEW `kind` so dashboards / aggregators can filter these out by default. Should not contaminate the `poly_updown_signal` event count.

## Acceptance criteria

| # | check | how |
|---|---|---|
| 1 | All 6 overlay shadows emit only mirror fires (no heartbeats) | `SELECT data->>'signal', COUNT(*) FROM trading.events WHERE sleeve_id LIKE 'shadow_%' AND sleeve_id NOT LIKE '%_fade_%' AND kind='poly_updown_signal' GROUP BY 1` → only `UP/DOWN` rows. No `NONE` rows. |
| 2 | Mirror fire-rate ≈ 15–25 % of parent | `n_overlay_fires / n_parent_fires` per pair must be ≥ 0.10 and ≤ 0.40 over 12 h (with parent having ≥ 30 fires). |
| 3 | Mirror direction = parent direction 100 % of the time | Join shadow fires to parent fires by `parent_event_id`. `same_dir = same_dir + same_dir`. |
| 4 | Resolutions arrive automatically | After parent slot resolves, `SELECT COUNT(*) FROM trading.events WHERE sleeve_id = 'shadow_*' AND kind='poly_updown_resolution'` must equal `COUNT(poly_updown_signal)` for that sleeve. |
| 5 | `poly_updown_overlay_skipped` count = parent_fires − overlay_fires | Confirms every parent fire was evaluated. |
| 6 | No standalone overlay controller heartbeats | `SELECT COUNT(*) FROM trading.events WHERE sleeve_id LIKE 'shadow_%' AND data->>'reason'='no_signal'` → only FADE sleeves should appear (overlay sleeves should be zero). |

## Migration plan

1. **Day 0**: Ship the new module + hook code + registration. Engine restart. Old overlay shadow controllers still exist but are disabled by env flag flip.
2. **Day 0 + 12 h**: Verify acceptance criteria 1-3 on a 12 h sample.
3. **Day 1**: Verify acceptance criteria 4-6.
4. **Day 7**: Drop `OverlayFilterStrategy` class entirely if no regressions.

## Files to touch (final list)

| file | change | LOC |
|---|---|---|
| `backend/app/strategies/polymarket/overlay_hooks.py` | **NEW** — OverlayHook + registry | ~150 |
| `backend/app/strategies/polymarket/_overlay_hook_spec.py` | **NEW** — 6-hook config | ~50 |
| `backend/app/engine/main.py` | add `register_all_overlay_hooks()` call in lifespan | ~5 |
| `backend/app/controllers/polymarket_updown.py` | add post-fire hook block after audit-write | ~40 |
| `backend/app/engine/poly_updown_loop.py:411 build_bar_context_t_plus_120` | populate `fair_edge_bp_up/down`, `cvd_30s`, `macd_hist` on parent BarContext | ~15 |
| `backend/app/engine/main.py` (overlay spawn block) | remove the 6 OverlayFilterStrategy controllers | ~15 (delete) |
| `backend/app/strategies/polymarket/shadow9.py` | mark `OverlayFilterStrategy` deprecated | ~3 |

Total: **~280 new lines, ~30 deleted, 4 files touched + 2 new files**.

## Why this is the right architecture

1. **DRY** — overlay is a 1-line gate predicate, not a wrapped-controller. No duplicate signal logic.
2. **Always-correct direction** — mirror reads parent direction directly, can never diverge.
3. **Single source of truth for BarContext** — production builder runs once per slot, shadow reuses it.
4. **No state-isolation bugs** — overlay has zero internal state. Just a frozen dataclass with a `gate_passes()` method.
5. **Trivially testable** — `OverlayHook.gate_passes(direction, bctx)` is a pure function. Unit-test each gate_kind with synthetic BarContexts.
6. **Easy to add new gates** — register a new `OverlayHook` in `_overlay_hook_spec.py`, no other code changes.
7. **Symmetric with FADE design** — FADE companions also hook into parent fires. Architecture becomes consistent: **shadow sleeves never have their own controllers, they're always hooks**.

## Side benefit — fixes the deferred ETH 15m FADE bug too

The Bug 2 deferred case (`shadow_poly_updown_eth_15m_fade_sniper` 50% wrong direction) can use the same architecture. Replace the FadeCompanionStrategy controller with a FadeHook in the same module:

```python
@dataclass(frozen=True)
class FadeHook:
    parent_sleeve_id: str
    shadow_sleeve_id: str
    cell_key: str   # for HOD lookup

    def should_fade(self, direction: str, bctx, fire_unix_s: int) -> tuple[bool, str, dict]:
        # If parent already passes HOD + M5V → don't fade
        # Else → return opposite direction
        ...
```

This guarantees direction is OPPOSITE of parent (no more 50/50 random). Same registration pattern.

(Out of scope for this spec, but worth noting for the follow-up refactor.)

## Files

- This spec: `strategy_lab/reports/TV_AGENT_FIX_SPEC_OVERLAY_POST_FIRE_HOOK_2026_05_27.md`
- Bug diagnosis: `strategy_lab/reports/IDLE_SLEEVES_DIAGNOSIS_2026_05_27.md`
- Prior Phase 36 audit / implementation: `strategy_lab/reports/TV_AGENT_FIX_SPEC_PHASE36_BUGS_2026_05_26.md`
- Original 9-sleeve deploy spec: `strategy_lab/reports/SHADOW_DEPLOY_SPEC_9_NEW_SLEEVES_2026_05_24.md`
