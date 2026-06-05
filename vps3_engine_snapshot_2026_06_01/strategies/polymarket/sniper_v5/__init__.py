"""Phase 35 — Polymarket sniper-v5 shadow suite.

16 paper-only sleeves firing at slot_start_us + offset_s * 1_000_000
(NOT at the bar boundary) per
``global/strategy_lab/reports/SHADOW_DEPLOY_SPEC_2026_05_27.md``.

Sub-modules:
    - gates: 30+ pure gate functions (Plan 35-11)
    - sleeves: 16 sleeve definitions (Plan 35-12)
    - shadow_log: AsyncJsonlShadowLogger (Plan 35-03)

This package is a marker only — concrete modules live as siblings of
this directory (``sniper_v5_gates.py``, ``sniper_v5_sleeves.py``,
``sniper_v5_thresholds.py``, ``sniper_v5_shadow_log.py``) to mirror
the Phase 30 maker-arb layout. The package marker exists so future
refactors can pull modules INTO the namespace without an import dance.

CLAUDE.md inv #4: every gate function MUST be pure (zero IO, zero
network). CLAUDE.md inv #13: every panel read MUST go through the
TV-native feeds in ``backend/app/features/`` — NEVER through Storedata.
"""
