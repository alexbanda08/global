"""Operator-write endpoints for sleeve bots (Phase 17, Plan 02).

Four routes — pause, resume, set tier, set dollar size — all guarded by
``require_operator_cookie`` (Phase 17 cookie JWT). Each endpoint:

1. Computes the next bar boundary for the sleeve (CLAUDE.md inv #12).
2. Writes a ``trading.events(kind='operator_action', actor='operator')``
   audit row BEFORE returning (no race with restart).
3. Returns an ack DTO with ``applied_at`` = next bar boundary.

CLAUDE.md inv #11 — AGGRESSIVE tier code-locked at TWO layers:

- **Schema layer** (Pydantic): ``TierLiteral`` excludes ``AGGRESSIVE``;
  body ``{"tier": "AGGRESSIVE"}`` returns 422.
- **Runtime layer** (this module): if a request bypasses Pydantic (e.g.
  case variation, malformed but past schema), the handler hard-asserts
  ``HTTPException(403, "TierEscalationForbidden")``.

CLAUDE.md inv #12 — operator writes that affect strategy state apply at
NEXT bar boundary, never mid-bar. The ``_next_bar_boundary`` helper
returns the bar wake time for the sleeve TF; tests assert it is strictly
in the future relative to call time.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.auth import require_operator_cookie
from backend.app.api.models import (
    BotPauseAck,
    BotResumeAck,
    PolyUpdownSleeveState,
    SizeChangeAck,
    SizeChangeReq,
    TierChangeAck,
    TierChangeReq,
)
from backend.app.engine.sleeve_timeframes import SLEEVE_TIMEFRAMES

# Phase 18.1 dashboard: canonical sleeve_id values for the GET state aggregation.
# Mirrors backend/app/controllers/polymarket_updown.py::_audit
# and backend/app/engine/poly_updown_loop.py::SUPPORTED_SYMBOLS.
#
# 2026-04-30: per-mode sleeve_id separation. Each strategy_mode (volume,
# sniper, v3) writes its own suffixed sleeve_id so the dashboard can A/B/C
# the three modes side-by-side without ambiguity.
#   V1 Volume: 6 sleeves × {btc,eth,sol} × {5m,15m} → `..._volume`
#   V2 Sniper: 6 sleeves × {btc,eth,sol} × {5m,15m} → `..._sniper`
#   V3:        3 sleeves × {btc,eth,sol} × 5m only  → `..._v3`
# Phase 18.2 added 9 V3 patches (V3.1 + V3.2 + V4 — 3 sleeves each).
# Phase 18.3 added 3 V3.3 sleeves (V3.2 + multi-horizon for SOL A/B test).
# Phase 18.4 — 8 INVERSE sleeves (6 volume_INV_NIGHT + 1 sol sniper_INV
# + 1 eth sniper_DOWN_INV; paper-only). Surfaced on the dashboard ONLY when
# ``TV_INVERSE_SLEEVES_ENABLED=true`` so the dashboard list mirrors the
# actual registration set in engine/main.py — when the flag is off the
# inverse cards stay hidden (no controllers registered → no rows ever).
# Total: 27 base + 8 inverse = 35 when flag on; 27 when off.
_BASE_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # V1 Volume — every signal fires
    "poly_updown_btc_5m_volume",
    "poly_updown_eth_5m_volume",
    "poly_updown_sol_5m_volume",
    "poly_updown_btc_15m_volume",
    "poly_updown_eth_15m_volume",
    "poly_updown_sol_15m_volume",
    # V2 Sniper — q90/q80 threshold-gated
    "poly_updown_btc_5m_sniper",
    "poly_updown_eth_5m_sniper",
    "poly_updown_sol_5m_sniper",
    "poly_updown_btc_15m_sniper",
    "poly_updown_eth_15m_sniper",
    "poly_updown_sol_15m_sniper",
    # V3 — per-asset tuned portfolio (BTC q90 / ETH q95 / SOL q85 + multi-horizon)
    "poly_updown_btc_5m_v3",
    "poly_updown_eth_5m_v3",
    "poly_updown_sol_5m_v3",
    # Phase 18.2 V3.1 — asymmetric per-direction quantile + soft regime overlay
    # + SOL UP live-disable (paper-only)
    "poly_updown_btc_5m_v3_1",
    "poly_updown_eth_5m_v3_1",
    "poly_updown_sol_5m_v3_1",
    # Phase 18.2 V3.2 — V3 + hour blocklist {1,16,22 UTC} + macro 2-of-3
    # + liq-quiet gate (<$10k 5-min Binance liq notional)
    "poly_updown_btc_5m_v3_2",
    "poly_updown_eth_5m_v3_2",
    "poly_updown_sol_5m_v3_2",
    # Phase 18.2 V4 — V3.1 + V3.2 stacked
    "poly_updown_btc_5m_v4",
    "poly_updown_eth_5m_v4",
    "poly_updown_sol_5m_v4",
    # Phase 18.3 V3.3 — V3.2 + multi-horizon AND filter for SOL only.
    # A/B test against V3.2 SOL to decide whether multi-horizon adds quality
    # or just culls trades. BTC/ETH v3_3 are control samples (should match
    # v3_2 BTC/ETH exactly). Per SOL_V3_FIX_SPEC_2026_05_04 §"Decision protocol".
    "poly_updown_btc_5m_v3_3",
    "poly_updown_eth_5m_v3_3",
    "poly_updown_sol_5m_v3_3",
)

# Phase 18.4 — inverse sleeve_ids gated by TV_INVERSE_SLEEVES_ENABLED.
# Spec: 6× volume_INV_NIGHT (BTC/ETH/SOL × 5m/15m, gated to UTC hours
# {1-5,9,10}) + 1× sol_5m_sniper_INV (full flip) + 1×
# eth_5m_sniper_DOWN_INV (DOWN-only flip). Mirrors engine/main.py's
# flag-gated controller registration block — when off, no inverse
# controllers are constructed so the dashboard MUST hide the cards.
_INVERSE_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_btc_5m_volume_INV_NIGHT",
    "poly_updown_eth_5m_volume_INV_NIGHT",
    "poly_updown_sol_5m_volume_INV_NIGHT",
    "poly_updown_btc_15m_volume_INV_NIGHT",
    "poly_updown_eth_15m_volume_INV_NIGHT",
    "poly_updown_sol_15m_volume_INV_NIGHT",
    "poly_updown_sol_5m_sniper_INV",
    "poly_updown_eth_5m_sniper_DOWN_INV",
)

# Phase 18.5 — momo sleeves gated by TV_POLY_MOMO_ENABLED. Engine spawns
# N controllers (one per hedge_policy listed in TV_POLY_MOMO_HEDGE_POLICIES)
# when TV_POLY_MOMO_ENABLED=true, each writing its policy-suffixed
# sleeve_id from controllers/polymarket_updown.py::_audit. Up to 18 total.
# Suffix uppercase HOLD/HEDGE/SELL matches _HEDGE_POLICY_SUFFIX map.
# Phase 18.6 W0 (2026-05-06): split into per-policy tuples so the
# dashboard mirrors engine/main.py's per-policy gating. Default policy
# set is HOLD_ONLY only — HEDGE/SELL disabled until Phase 18.6 Wave 2
# PASS (TV-native WS BookMirror validated). Re-enable via
# TV_POLY_MOMO_HEDGE_POLICIES=HOLD_ONLY,HEDGE_HOLD,SELL_BID.
_MOMO_HOLD_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_btc_5m_momo_HOLD",
    "poly_updown_eth_5m_momo_HOLD",
    "poly_updown_sol_5m_momo_HOLD",
    "poly_updown_btc_15m_momo_HOLD",
    "poly_updown_eth_15m_momo_HOLD",
    "poly_updown_sol_15m_momo_HOLD",
)
_MOMO_HEDGE_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_btc_5m_momo_HEDGE",
    "poly_updown_eth_5m_momo_HEDGE",
    "poly_updown_sol_5m_momo_HEDGE",
    "poly_updown_btc_15m_momo_HEDGE",
    "poly_updown_eth_15m_momo_HEDGE",
    "poly_updown_sol_15m_momo_HEDGE",
)
_MOMO_SELL_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_btc_5m_momo_SELL",
    "poly_updown_eth_5m_momo_SELL",
    "poly_updown_sol_5m_momo_SELL",
    "poly_updown_btc_15m_momo_SELL",
    "poly_updown_eth_15m_momo_SELL",
    "poly_updown_sol_15m_momo_SELL",
)
# Maintained for back-compat — anything outside this module that imports
# the union should still work. New code reads the per-policy tuples.
_MOMO_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    _MOMO_HOLD_SLEEVE_IDS + _MOMO_HEDGE_SLEEVE_IDS + _MOMO_SELL_SLEEVE_IDS
)

# 2026-05-20 F7 RSI filter (TV_AGENT_F7_RSI_FILTER_SPEC). Per-policy
# tuples for the _f7-suffixed sleeve variants that the controller now
# writes when `self._f7_filter_mode != "off"` (default for momo/momo_v2).
# Dashboard appends these alongside the baselines so the operator sees
# both pre-F7 frozen history AND post-F7 live cards side-by-side.
_MOMO_HOLD_F7_SLEEVE_IDS: tuple[str, ...] = tuple(
    f"{sid}_f7" for sid in _MOMO_HOLD_SLEEVE_IDS
)
_MOMO_HEDGE_F7_SLEEVE_IDS: tuple[str, ...] = tuple(
    f"{sid}_f7" for sid in _MOMO_HEDGE_SLEEVE_IDS
)
_MOMO_SELL_F7_SLEEVE_IDS: tuple[str, ...] = tuple(
    f"{sid}_f7" for sid in _MOMO_SELL_SLEEVE_IDS
)

_MOMO_POLICY_TO_SLEEVES: dict[str, tuple[str, ...]] = {
    "HOLD_ONLY": _MOMO_HOLD_SLEEVE_IDS,
    "HEDGE_HOLD": _MOMO_HEDGE_SLEEVE_IDS,
    "SELL_BID": _MOMO_SELL_SLEEVE_IDS,
}

# 2026-05-20 F7 RSI filter — parallel policy → _f7-sleeves map.
_MOMO_POLICY_TO_F7_SLEEVES: dict[str, tuple[str, ...]] = {
    "HOLD_ONLY": _MOMO_HOLD_F7_SLEEVE_IDS,
    "HEDGE_HOLD": _MOMO_HEDGE_F7_SLEEVE_IDS,
    "SELL_BID": _MOMO_SELL_F7_SLEEVE_IDS,
}

# Phase 18.5+ — momo_v2 sleeves gated by TV_POLY_MOMO_V2_ENABLED.
# Engine spawns all 3 policies × 6 (sym, tf) = 18 sleeves whenever the
# flag is true (per spec §6 — single master switch, no per-policy CSV
# gate, distinct from v1 momo's W0 per-policy convention). Coexists
# with the v1 momo cards on the dashboard.
_MOMO_V2_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # HOLD policy (6)
    "poly_updown_btc_5m_momo_v2_HOLD",
    "poly_updown_eth_5m_momo_v2_HOLD",
    "poly_updown_sol_5m_momo_v2_HOLD",
    "poly_updown_btc_15m_momo_v2_HOLD",
    "poly_updown_eth_15m_momo_v2_HOLD",
    "poly_updown_sol_15m_momo_v2_HOLD",
    # HEDGE policy (6)
    "poly_updown_btc_5m_momo_v2_HEDGE",
    "poly_updown_eth_5m_momo_v2_HEDGE",
    "poly_updown_sol_5m_momo_v2_HEDGE",
    "poly_updown_btc_15m_momo_v2_HEDGE",
    "poly_updown_eth_15m_momo_v2_HEDGE",
    "poly_updown_sol_15m_momo_v2_HEDGE",
    # SELL policy (6)
    "poly_updown_btc_5m_momo_v2_SELL",
    "poly_updown_eth_5m_momo_v2_SELL",
    "poly_updown_sol_5m_momo_v2_SELL",
    "poly_updown_btc_15m_momo_v2_SELL",
    "poly_updown_eth_15m_momo_v2_SELL",
    "poly_updown_sol_15m_momo_v2_SELL",
)

# 2026-05-20 F7 RSI filter — _f7-suffixed momo_v2 variants for dashboard.
_MOMO_V2_F7_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = tuple(
    f"{sid}_f7" for sid in _MOMO_V2_POLY_UPDOWN_SLEEVE_IDS
)


# Phase 34 — Shadow gated sleeves (TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22).
# 11 INDEPENDENT sleeve_ids, NOT split by hedge_policy (operator directive
# 2026-05-22). Mirror of the _SHADOW_GATED_SLEEVES_SPEC list in engine/main.py
# (1 controller per sleeve_id). Engine + dashboard MUST stay aligned: if
# either side sees TV_POLY_SHADOW_GATED_ENABLED true and the other doesn't,
# dashboard shows phantom cards or hides real ones.
_SHADOW_GATED_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_sol_5m_sniper_hod",
    # 2026-05-22 fix: renamed from _m5va suffix (m5va gate dropped per spec).
    "poly_updown_eth_15m_sniper_hod",
    "poly_updown_btc_15m_momo_hod",
    "poly_updown_btc_15m_sniper_hod",
    "poly_updown_btc_5m_sniper_hod",
    "poly_updown_btc_5m_momo_v2_hod_mtf",
    "poly_updown_btc_15m_momo_v2_hod",
    "poly_updown_sol_5m_momo_v2_hod",
    "poly_updown_eth_15m_momo_v2_hod",
    "poly_updown_sol_15m_momo_v2_hod",
    "poly_updown_eth_5m_sniper_hod",
)


# Phase 36 — Shadow9 sleeves (3 paper-only sleeve_ids). All fire across
# BTC/ETH/SOL under a single sleeve_id per spec. Mirror of
# _SHADOW9_SLEEVES_SPEC in engine/main.py. Gated on TV_POLY_SHADOW9_ENABLED.
_SHADOW9_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    "shadow_poly_updown_ALL_5m_phase1_kelly",
    "shadow_poly_updown_ALL_5m_phase1_kelly_fe1000_V10",
    "shadow_poly_updown_ALL_5m_S3_prewindow",
    "shadow_poly_updown_ALL_15m_S4_prewindow",
)

# Phase 36b — Shadow9 fade companions + overlay filters (12 sleeve_ids).
# 6 fade (Sleeves #2-7) + 6 overlay (spec Bonus). Mirror of
# _SHADOW9_FADE_OVERLAY_SPEC in engine/main.py. Gated on
# TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED.
_SHADOW9_FADE_OVERLAY_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # 6 FADE companions
    "shadow_poly_updown_btc_5m_fade_momo_v2",
    "shadow_poly_updown_btc_5m_fade_sniper",
    "shadow_poly_updown_eth_15m_fade_sniper",
    "shadow_poly_updown_sol_5m_fade_sniper",
    "shadow_poly_updown_sol_5m_fade_momo_v2",
    "shadow_poly_updown_sol_15m_fade_momo_v2",
    # 6 OVERLAY filters
    "shadow_poly_updown_eth_15m_sniper_m5v",
    "shadow_poly_updown_btc_5m_momo_v2_fairedge500",
    "shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30",
    "shadow_poly_updown_sol_15m_sniper_fairedge500",
    "shadow_poly_updown_sol_5m_momo_v1_m5v",
    "shadow_poly_updown_sol_5m_momo_v2_cvd_macd",
)


# Phase 35 — VWAP continuation sleeves (5 paper-only sleeve_ids).
# Mirror of _VWAP_CONT_SLEEVES_SPEC in engine/main.py. Gated on
# TV_POLY_VWAP_CONT_ENABLED (same flag as engine registration). Dashboard
# only renders these when the engine spawned them — keep flags aligned.
_VWAP_CONT_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    "poly_updown_btc_5m_vwap_off240_m1v",
    "poly_updown_btc_5m_vwap_off60_f7_cross",
    "poly_updown_btc_5m_vwap_off90_cross",
    "poly_updown_eth_5m_vwap_off210_f7_m1v",
    "poly_updown_sol_5m_vwap_off60",
)


# Phase 35-12 + V6/V7/V8 (2026-05-27) — sniper-v5 paper sleeves.
# Single-source-of-truth import from the sleeves module instead of a
# hardcoded mirror — the prior literal tuple was only the 16 V5 sleeves
# and silently dropped the V6/V7/V8 IDs from the dashboard manifest.
# Importing here keeps bots.py and the live SNIPER_V5_SLEEVES tuple in
# permanent lockstep. Gate is still TV_POLY_SNIPER_V5_ENABLED — when the
# engine flag is OFF, the controller isn't spawned and no fires flow;
# when ON, all 56 IDs surface as IDLE cards until fires arrive.
from backend.app.strategies.polymarket.sniper_v5_sleeves import (
    SNIPER_V5_SLEEVE_IDS as _SNIPER_V5_POLY_UPDOWN_SLEEVE_IDS,
)


# Phase 33 (D-01) — Deprecation list. Sleeve_ids listed in TV_POLY_DEPRECATED_SLEEVES
# (CSV) are hard-disabled: skipped at controller registration AND filtered from the
# active sleeve_id tuple returned to the manifest. Frontend surfaces them in a
# separate collapsed "Deprecated" section with [DEPRECATED] chip + grayed body.
# Read once at module import — same lifetime contract as _POLY_UPDOWN_SLEEVE_IDS.
# Rollback: remove a sleeve_id from the CSV + restart tv-engine + tv-api.
_DEPRECATED_POLY_UPDOWN_SLEEVE_IDS: frozenset[str] = frozenset(
    s.strip()
    for s in os.environ.get("TV_POLY_DEPRECATED_SLEEVES", "").split(",")
    if s.strip()
)


def _resolve_poly_updown_sleeve_ids() -> tuple[str, ...]:
    """Return the active sleeve_id set, gating inverse + momo + momo_v2 on env flags.

    Read at module import time. tv-api / FastAPI start AFTER the env
    file (``/etc/tv/tradingvenue.env``) is loaded by systemd, so the
    flag value is stable for the lifetime of the process — same
    contract as engine/main.py's flag-gated registration blocks.

    Phase 18.6 W0: momo sleeves are now per-policy gated. Default
    HOLD_ONLY only; HEDGE_HOLD + SELL_BID surface only when explicitly
    listed in TV_POLY_MOMO_HEDGE_POLICIES (mirrors engine/main.py).

    Phase 18.5+: momo_v2 uses single-master-switch (TV_POLY_MOMO_V2_ENABLED) —
    when on, all 18 sleeves surface. Mirrors engine/main.py's "always
    spawn all 3 policies" rule for v2.

    2026-05-14 — strategy-mode-aware filter: when ``TV_POLY_STRATEGY_MODES``
    excludes ``volume`` (deprecated on VPS3 2026-05-08), drop the 6 base
    volume sleeves AND the 6 volume_INV_NIGHT inverse sleeves from the
    dashboard. They were producing only ``no_signal`` events and showing
    as SILENT chip — operator-confusing noise. Re-enable by adding
    ``volume`` back to ``TV_POLY_STRATEGY_MODES``.

    2026-05-15 — Phase 27 Ireland live-only mode: when
    ``TV_DASHBOARD_LIVE_MIRRORS_ONLY=true``, the dashboard manifest is
    restricted to the live-mirror allowlist (``TV_POLY_LIVE_ALLOWLIST``).
    Ireland VPS runs zero paper controllers, so surfacing the base 21
    paper sleeves as "shadow" cards is operator-confusing noise. Also
    unconditionally unions the allowlist into the manifest so allowlisted
    sleeves whose paper-mode flag is off (e.g. momo + momo_v2 on Ireland)
    are still visible to the Live filter.
    """
    # Phase 27 Ireland: live-mirror-only dashboard. Skip all paper-mode
    # gating and return just the allowlist.
    if os.getenv("TV_DASHBOARD_LIVE_MIRRORS_ONLY", "false").lower() == "true":
        raw_allow = os.getenv("TV_POLY_LIVE_ALLOWLIST", "").strip()
        if not raw_allow:
            return ()
        allowlist_sids = tuple(
            s.strip() for s in raw_allow.split(",") if s.strip()
        )
        # 2026-05-20 F7 — when F7 mode != "off" (default for momo+momo_v2),
        # the live-mirror controllers now write `<base>_f7_LIVE` sleeve_ids
        # (the controller's _f7_suffix combined with the live-mirror
        # _LIVE suffix). Allowlist itself stays in its base form (the
        # spawn parser expects it). Swap base momo/momo_v2 entries with
        # their _f7 variants so the dashboard surfaces ONLY the post-F7
        # live cards. Pre-F7 audit rows still live in trading.events for
        # forensic SQL but don't render as cards (operator-confusing noise).
        # To restore baselines, set TV_POLY_F7_FILTER_MODE=off (also turns
        # off the gate in the controller — keep aligned across both).
        _f7_env_l = os.getenv("TV_POLY_F7_FILTER_MODE", "").strip().lower()
        _f7_active_l = _f7_env_l in ("", "basic", "extreme")
        if _f7_active_l:
            f7_swapped: list[str] = []
            for sid in allowlist_sids:
                # Only momo + momo_v2 sleeves get F7. Heuristic: look for
                # the `_momo_` infix (covers both momo + momo_v2 since
                # the v2 form is `..._momo_v2_...`).
                if "_momo_" in sid:
                    f7_swapped.append(f"{sid}_f7")
                else:
                    f7_swapped.append(sid)
            return tuple(f7_swapped)
        return allowlist_sids

    # When TV_POLY_STRATEGY_MODES is set explicitly AND excludes "volume",
    # drop the deprecated volume + volume_INV_NIGHT sleeves so they don't
    # show as SILENT on the dashboard. Empty env keeps everything
    # (back-compat with tests + early-stage deploys).
    raw_modes = os.getenv("TV_POLY_STRATEGY_MODES", "").strip()
    if raw_modes:
        active_modes = {m.strip().lower() for m in raw_modes.split(",") if m.strip()}
        volume_active = "volume" in active_modes
    else:
        # Unset → permissive: treat all strategies as active (matches the
        # pre-2026-05-08 default before volume was deprecated on VPS3).
        volume_active = True

    sleeves: tuple[str, ...]
    if volume_active:
        sleeves = _BASE_POLY_UPDOWN_SLEEVE_IDS
    else:
        # Drop poly_updown_{sym}_{tf}_volume — deprecated strategy.
        sleeves = tuple(
            sid for sid in _BASE_POLY_UPDOWN_SLEEVE_IDS
            if not sid.endswith("_volume")
        )

    if os.getenv("TV_INVERSE_SLEEVES_ENABLED", "false").lower() == "true":
        inverse = _INVERSE_POLY_UPDOWN_SLEEVE_IDS
        if not volume_active:
            # inverse_volume_night depends on the volume signal stream;
            # without it the 6 volume_INV_NIGHT sleeves are perma-FLAT.
            inverse = tuple(
                sid for sid in inverse
                if "_volume_INV_NIGHT" not in sid
            )
        sleeves = sleeves + inverse
    # 2026-05-20 F7 — when F7 mode != "off" (the controller default for
    # momo + momo_v2), REPLACE the baseline momo + momo_v2 tuples with
    # the _f7 variants. Baseline cards are deprecated post-F7-deploy:
    # they no longer get new data (controller writes _f7 sleeve_ids now)
    # and surfacing them as stale cards alongside the live _f7 cards
    # was operator-confusing noise. Frozen baseline history still lives
    # in `trading.events` + `trading.events_archive` for forensic SQL;
    # the dashboard manifest only carries the live _f7 set.
    # To restore baseline cards (e.g. for a side-by-side A/B view), set
    # `TV_POLY_F7_FILTER_MODE=off` (also turns off the gate in the
    # controller — keep these aligned across env + restart for both).
    _f7_env = os.getenv("TV_POLY_F7_FILTER_MODE", "").strip().lower()
    if _f7_env == "off":
        _f7_active = False
    elif _f7_env in ("basic", "extreme"):
        _f7_active = True
    else:
        # Default: F7 active on momo+momo_v2 (matches controller default).
        _f7_active = True

    if os.getenv("TV_POLY_MOMO_ENABLED", "false").lower() == "true":
        momo_policies_csv = os.getenv(
            "TV_POLY_MOMO_HEDGE_POLICIES", "HOLD_ONLY"
        )
        active_policies = tuple(
            p.strip().upper()
            for p in momo_policies_csv.split(",")
            if p.strip()
        )
        for policy in active_policies:
            if _f7_active:
                # Deprecated baseline tuple hidden; only _f7 surfaces.
                sleeves = sleeves + _MOMO_POLICY_TO_F7_SLEEVES.get(policy, ())
            else:
                sleeves = sleeves + _MOMO_POLICY_TO_SLEEVES.get(policy, ())
    if os.getenv("TV_POLY_MOMO_V2_ENABLED", "false").lower() == "true":
        if _f7_active:
            sleeves = sleeves + _MOMO_V2_F7_POLY_UPDOWN_SLEEVE_IDS
        else:
            sleeves = sleeves + _MOMO_V2_POLY_UPDOWN_SLEEVE_IDS

    # Phase 34 — Shadow gated sleeves (HoD / MTF / Markov). Union the 11
    # shadow sleeve_ids when TV_POLY_SHADOW_GATED_ENABLED=true. Engine spawns
    # them as separate paper-only controllers (see engine/main.py
    # _SHADOW_GATED_SLEEVES_SPEC). The dashboard surfaces them as cards so
    # the operator can watch each gate stack's WR + $/trade vs the baseline.
    if os.getenv("TV_POLY_SHADOW_GATED_ENABLED", "false").lower() == "true":
        existing_shadow = set(sleeves)
        added_shadow = tuple(
            sid for sid in _SHADOW_GATED_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing_shadow
        )
        sleeves = sleeves + added_shadow

    # Phase 35 — VWAP continuation sleeves. Same flag-gated union pattern.
    if os.getenv("TV_POLY_VWAP_CONT_ENABLED", "false").lower() == "true":
        existing_vwap = set(sleeves)
        added_vwap = tuple(
            sid for sid in _VWAP_CONT_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing_vwap
        )
        sleeves = sleeves + added_vwap

    # Phase 35-12 — Sniper-v5 16 paper sleeves. Gated on TV_POLY_SNIPER_V5_ENABLED.
    # Mirrors engine/main.py's Phase 35-12 spawn block — when the engine flag
    # is OFF, the controller isn't constructed and no fire events flow; the
    # dashboard surfaces the cards only when this flag is ON.
    if os.getenv("TV_POLY_SNIPER_V5_ENABLED", "false").lower() == "true":
        existing_sniper_v5 = set(sleeves)
        added_sniper_v5 = tuple(
            sid for sid in _SNIPER_V5_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing_sniper_v5
        )
        sleeves = sleeves + added_sniper_v5

    # Phase 36 — Shadow9 sleeves. Same gated-union pattern as Phase 35.
    if os.getenv("TV_POLY_SHADOW9_ENABLED", "false").lower() == "true":
        existing_s9 = set(sleeves)
        added_s9 = tuple(
            sid for sid in _SHADOW9_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing_s9
        )
        sleeves = sleeves + added_s9

    # Phase 36b — Shadow9 fade + overlay sleeves.
    if os.getenv("TV_POLY_SHADOW9_FADE_OVERLAY_ENABLED", "false").lower() == "true":
        existing_s9b = set(sleeves)
        added_s9b = tuple(
            sid for sid in _SHADOW9_FADE_OVERLAY_POLY_UPDOWN_SLEEVE_IDS
            if sid not in existing_s9b
        )
        sleeves = sleeves + added_s9b

    # Always union with live-mirror allowlist so any allowlisted sleeve is
    # visible in the dashboard manifest even when its paper-mode flag is
    # off (Phase 27 — momo / momo_v2 may be paper-disabled on a host but
    # still have live mirrors running). Dedup while preserving order.
    raw_allow = os.getenv("TV_POLY_LIVE_ALLOWLIST", "").strip()
    if raw_allow:
        existing = set(sleeves)
        added = tuple(
            s.strip()
            for s in raw_allow.split(",")
            if s.strip() and s.strip() not in existing
        )
        sleeves = sleeves + added

    # Phase 29 D-02: old poly_mint_sell_* shadow sleeves removed.
    # Phase 29 v2 D-23 (Plan 29-16): mint-and-sell v2 sleeves gated on
    # ``TV_POLY_MINT_SELL_V2_ENABLED``. Mirrors engine/main.py's lifespan
    # SlotScheduler-spawn block (Plan 29-15) — when the engine spawns 6
    # cells, the dashboard must surface 6 sleeve cards.
    #
    # ``TV_POLY_MINT_SELL_V2_MODE`` ∈ {"paper", "live"} chooses the suffix:
    #   paper → ``poly_mint_sell_v2_{cell}_paper`` (e.g. ``btc_5m_paper``)
    #   live  → ``poly_mint_sell_v2_{cell}_live``  (e.g. ``btc_5m_live``)
    # The suffix locks against D-20 (sleeve_id format in slot_cycle.py).
    #
    # ``TV_POLY_MINT_SELL_V2_CELLS`` CSV defaults to the 6-cell default set;
    # operator can narrow (e.g. ``btc_5m`` only) for Phase 1 paper canary
    # or Phase 2 single-slug live ramp (D-33 / D-34 / D-35).
    if os.getenv("TV_POLY_MINT_SELL_V2_ENABLED", "false").lower() == "true":
        mode = os.getenv("TV_POLY_MINT_SELL_V2_MODE", "paper").lower()
        cells_csv = os.getenv(
            "TV_POLY_MINT_SELL_V2_CELLS",
            "btc_15m,btc_5m,eth_15m,eth_5m,sol_15m,sol_5m",
        )
        suffix = "_paper" if mode == "paper" else "_live"
        existing = set(sleeves)
        for cell in cells_csv.split(","):
            cell = cell.strip()
            if not cell or "_" not in cell:
                continue
            sid = f"poly_mint_sell_v2_{cell}{suffix}"
            if sid not in existing:
                sleeves = sleeves + (sid,)
                existing.add(sid)

    # Phase 33 (D-05) — Strip deprecated sleeve_ids from the active set.
    # The deprecated set is operator-controlled via TV_POLY_DEPRECATED_SLEEVES
    # CSV. These sleeves are NOT registered as controllers and NOT included
    # in the active dashboard grid. Frontend surfaces them in a separate
    # collapsed "Deprecated" section using the SleeveManifestEntry.deprecated
    # field (set in engine/sleeve_manifest.py from the same env var).
    if _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS:
        sleeves = tuple(
            sid for sid in sleeves
            if sid not in _DEPRECATED_POLY_UPDOWN_SLEEVE_IDS
        )

    return sleeves


def _resolve_live_mirror_allowlist() -> frozenset[str]:
    """Return the set of sleeve_ids that have a Phase 26.3 live mirror.

    Sourced from ``TV_POLY_LIVE_ALLOWLIST`` (CSV). Empty when no
    live mirrors configured. Read once at module import — same
    lifetime contract as ``_POLY_UPDOWN_SLEEVE_IDS``. Exposed to
    the frontend via the batch stats endpoint so the dashboard's
    Live/Shadow filter pills can target sleeves with active
    live-mirror twins (2026-05-14 operator request).
    """
    raw = os.getenv("TV_POLY_LIVE_ALLOWLIST", "").strip()
    if not raw:
        return frozenset()
    return frozenset(s.strip() for s in raw.split(",") if s.strip())


_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = _resolve_poly_updown_sleeve_ids()
_LIVE_MIRROR_ALLOWLIST: frozenset[str] = _resolve_live_mirror_allowlist()

logger = logging.getLogger(__name__)
router = APIRouter(tags=["bots"])


# ---------------------------------------------------------------------------
# Dependency registry
# ---------------------------------------------------------------------------


class _BotsDeps:
    pool: Any = None
    bar_engine: Any = None


_deps = _BotsDeps()


def register_bots_dependencies(*, pool: Any, bar_engine: Any) -> None:
    """Bind runtime deps. Called from tv-api lifespan + tests."""
    _deps.pool = pool
    _deps.bar_engine = bar_engine


def _reset_bots_dependencies_for_tests() -> None:
    _deps.pool = None
    _deps.bar_engine = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _next_bar_boundary(sleeve_id: str) -> datetime:
    """Return next bar boundary for the sleeve's TF (CLAUDE.md inv #12).

    Priority:

    1. ``bar_engine.next_bar_for(sleeve_id)`` — authoritative when the engine
       is wired into tv-api (currently a future composition step).
    2. ``SLEEVE_TIMEFRAMES`` registry — used by tv-api today (bar_engine=None).
       Floor-and-add formula on UTC epoch seconds, strictly future.
    3. Top-of-next-minute fallback — only when ``sleeve_id`` is unknown to
       the registry (safe conservative default; preserves prior behavior for
       sleeves not yet in SLEEVE_TIMEFRAMES).
    """
    if _deps.bar_engine is not None and hasattr(_deps.bar_engine, "next_bar_for"):
        try:
            return _deps.bar_engine.next_bar_for(sleeve_id)
        except Exception:
            logger.exception(
                "bots.next_bar_lookup_failed",
                extra={"event": "bots.next_bar_lookup_failed", "sleeve_id": sleeve_id},
            )

    tf = SLEEVE_TIMEFRAMES.get(sleeve_id)
    if tf is not None:
        now_ts = datetime.now(UTC).timestamp()
        # ``tf - now_ts % tf`` ⇒ delta to NEXT boundary, strictly > 0 even if
        # we are exactly on a boundary (ensures result > now per inv #12).
        next_ts = now_ts + (tf - now_ts % tf)
        return datetime.fromtimestamp(next_ts, tz=UTC)

    # Unknown sleeve — floor to next minute (safe conservative default).
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    return now + timedelta(minutes=1)


async def _audit(payload: dict[str, Any]) -> None:
    """Insert ``trading.events(kind='operator_action')`` row.

    Called BEFORE the handler returns its ack so a crash between audit
    and return still leaves a record. If the pool is not registered we
    raise 503 — operator writes without audit are a CLAUDE.md inv #11
    spirit violation.
    """
    if _deps.pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="bots dependencies not registered",
        )
    async with _deps.pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO trading.events (at, kind, data) "
            "VALUES (now(), 'operator_action', $1::jsonb)",
            json.dumps(payload),
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/bots/{sleeve_id}/pause", response_model=BotPauseAck)
async def pause_sleeve(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> BotPauseAck:
    now = datetime.now(UTC)
    applied_at = _next_bar_boundary(sleeve_id)
    payload = {
        "action": "pause",
        "sleeve_id": sleeve_id,
        "actor": "operator",
        "applied_at": applied_at.isoformat(),
    }
    await _audit(payload)
    logger.info(
        "bots.paused",
        extra={
            "event": "bots.paused",
            "sleeve_id": sleeve_id,
            "applied_at": applied_at.isoformat(),
        },
    )
    return BotPauseAck(at=now, sleeve_id=sleeve_id, applied_at=applied_at)


@router.post("/bots/{sleeve_id}/resume", response_model=BotResumeAck)
async def resume_sleeve(
    sleeve_id: str,
    _: None = Depends(require_operator_cookie),
) -> BotResumeAck:
    now = datetime.now(UTC)
    applied_at = _next_bar_boundary(sleeve_id)
    payload = {
        "action": "resume",
        "sleeve_id": sleeve_id,
        "actor": "operator",
        "applied_at": applied_at.isoformat(),
    }
    await _audit(payload)
    logger.info(
        "bots.resumed",
        extra={
            "event": "bots.resumed",
            "sleeve_id": sleeve_id,
            "applied_at": applied_at.isoformat(),
        },
    )
    return BotResumeAck(at=now, sleeve_id=sleeve_id, applied_at=applied_at)


@router.post("/bots/{sleeve_id}/tier", response_model=TierChangeAck)
async def set_tier(
    sleeve_id: str,
    body: TierChangeReq,
    _: None = Depends(require_operator_cookie),
) -> TierChangeAck:
    """Change sleeve risk tier. AGGRESSIVE blocked at BOTH layers.

    - Pydantic ``TierLiteral`` rejects AGGRESSIVE at 422.
    - Runtime defense-in-depth: case-fold compare against ``AGGRESSIVE``
      raises 403 ``TierEscalationForbidden`` (CLAUDE.md inv #11).
    """
    if body.tier.upper() == "AGGRESSIVE":
        # Cannot reach here via the typed body, but if a future refactor
        # weakens the schema this hard-assert keeps inv #11 intact.
        logger.warning(
            "bots.aggressive_rejected",
            extra={"event": "bots.aggressive_rejected", "sleeve_id": sleeve_id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="TierEscalationForbidden",
        )
    now = datetime.now(UTC)
    applied_at = _next_bar_boundary(sleeve_id)
    payload = {
        "action": "tier",
        "sleeve_id": sleeve_id,
        "tier": body.tier,
        "actor": "operator",
        "applied_at": applied_at.isoformat(),
    }
    await _audit(payload)
    logger.info(
        "bots.tier_changed",
        extra={
            "event": "bots.tier_changed",
            "sleeve_id": sleeve_id,
            "tier": body.tier,
            "applied_at": applied_at.isoformat(),
        },
    )
    return TierChangeAck(at=now, sleeve_id=sleeve_id, tier=body.tier, applied_at=applied_at)


@router.post("/bots/{sleeve_id}/size", response_model=SizeChangeAck)
async def set_size(
    sleeve_id: str,
    body: SizeChangeReq,
    _: None = Depends(require_operator_cookie),
) -> SizeChangeAck:
    """Change sleeve dollar size. ``dollar_size`` ∈ (0, 50000] (Pydantic)."""
    now = datetime.now(UTC)
    applied_at = _next_bar_boundary(sleeve_id)
    payload = {
        "action": "size",
        "sleeve_id": sleeve_id,
        "dollar_size": body.dollar_size,
        "actor": "operator",
        "applied_at": applied_at.isoformat(),
    }
    await _audit(payload)
    logger.info(
        "bots.size_changed",
        extra={
            "event": "bots.size_changed",
            "sleeve_id": sleeve_id,
            "dollar_size": body.dollar_size,
            "applied_at": applied_at.isoformat(),
        },
    )
    return SizeChangeAck(
        at=now,
        sleeve_id=sleeve_id,
        dollar_size=body.dollar_size,
        applied_at=applied_at,
    )


@router.get(
    "/bots/poly_updown/state",
    response_model=list[PolyUpdownSleeveState],
)
async def get_poly_updown_state(
    _: None = Depends(require_operator_cookie),
) -> list[PolyUpdownSleeveState]:
    """Return 24h aggregated state for all 6 Polymarket Updown sleeves.

    Reads ``trading.events`` filtered to ``kind='poly_updown_signal'`` over
    the last 24 hours, grouped by sleeve_id. Always returns 6 rows — sleeves
    with no events get ``last_signal=None``, ``fill_count_24h=0``, etc.
    Initial seed for the /bots dashboard; live updates flow over WS via the
    ``bar_processed`` and ``fill`` event kinds emitted by the controller.
    """
    if _deps.pool is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="bots dependencies not registered",
        )

    # Two parallel aggregations — signal/fill activity and resolver payouts.
    # Kept separate (instead of one mega-query) for readability + because
    # they can independently fail without losing the other dimension.
    signal_sql = (
        "SELECT "
        "  sleeve_id, "
        "  COUNT(*) FILTER (WHERE data->>'reason' = 'order_placed' "
        "                     AND data->>'fill_status' = 'filled')::int AS fill_count_24h, "
        "  COUNT(*) FILTER (WHERE data->>'reason' = 'entry_rejected' "
        "                     OR data->>'fill_status' = 'rejected')::int AS reject_count_24h, "
        "  MAX(at) FILTER (WHERE data->>'reason' = 'order_placed' "
        "                    AND data->>'fill_status' = 'filled') AS last_fill_at, "
        "  (array_agg(data->>'signal' ORDER BY at DESC))[1] AS last_signal, "
        "  MAX(at) AS last_at, "
        "  (array_agg(data->>'reason' ORDER BY at DESC))[1] AS last_reason "
        "FROM trading.events "
        "WHERE sleeve_id = ANY($1::text[]) "
        "  AND kind = 'poly_updown_signal' "
        "  AND at >= now() - interval '24 hours' "
        "GROUP BY sleeve_id"
    )
    # Phase 18.1 resolver payouts — sourced from chainlink-resolved outcomes
    # via public.market_resolutions_v2 (see poly_updown_resolver.py).
    # data->>'won' is text 'true'/'false' (jsonb bool serialized).
    # data->>'pnl_usd' is text containing a decimal — sum via numeric cast.
    #
    # D-24 (Phase 29 v2, Plan 29-16): include poly_mint_sell_v2_resolution
    # rows so the 6 v2 sleeves surface ``wins_24h`` / ``losses_24h`` /
    # ``realized_pnl_24h_usd`` on the dashboard. Both kinds share the same
    # JSON shape ({won: bool, pnl_usd: decimal-as-string}) per D-22, so
    # the existing aggregation logic works unchanged — only the WHERE-clause
    # ``kind`` filter widens.
    #
    # NOTE: ``signal_sql`` (above) still reads only ``poly_updown_signal`` —
    # v2 sleeve cards will show ``fill_count_24h=0`` / ``reject_count_24h=0``
    # on the dashboard until a v2.1 follow-up adds a parallel branch reading
    # ``poly_mint_sell_v2_post`` + ``_fill``. The pragmatic v2.0 priority is
    # the win-rate / PnL cards (resolution_sql); fill counts are
    # informational-only on this view.
    # TV_FIX_DASHBOARD_2026_05_27 — sniper-v5 (V5/V6/V7/V8) resolutions live
    # under ``kind='poly_updown_signal'`` with ``event_type='sleeve_fire_resolved'``
    # and don't carry a ``won`` field — derive it from
    # ``outcome.lower() == direction.lower()`` so the dashboard shows real
    # wins/losses on those sleeves. Synthetic fills (fill_method='synthetic')
    # are excluded from primary wins/losses count.
    resolution_sql = (
        "SELECT "
        "  sleeve_id, "
        "  COUNT(*) FILTER ( "
        "    WHERE (data->>'won') = 'true' "
        "       OR ( "
        "         (data->>'event_type') = 'sleeve_fire_resolved' "
        "         AND (data->>'fill_method') IS DISTINCT FROM 'synthetic' "
        "         AND LOWER(data->>'outcome') = LOWER(data->>'direction') "
        "       ) "
        "  )::int AS wins_24h, "
        "  COUNT(*) FILTER ( "
        "    WHERE (data->>'won') = 'false' "
        "       OR ( "
        "         (data->>'event_type') = 'sleeve_fire_resolved' "
        "         AND (data->>'fill_method') IS DISTINCT FROM 'synthetic' "
        "         AND data->>'outcome' IS NOT NULL "
        "         AND data->>'direction' IS NOT NULL "
        "         AND LOWER(data->>'outcome') <> LOWER(data->>'direction') "
        "       ) "
        "  )::int AS losses_24h, "
        "  COUNT(*) FILTER (WHERE data->>'hedged' = 'true')::int AS hedged_count_24h, "
        "  COALESCE(SUM( "
        "    CASE "
        "      WHEN (data->>'fill_method') = 'synthetic' THEN 0 "
        "      ELSE (data->>'pnl_usd')::numeric "
        "    END "
        "  ), 0)::float8 AS realized_pnl_24h_usd, "
        "  MAX(at) AS last_resolved_at "
        "FROM trading.events "
        "WHERE sleeve_id = ANY($1::text[]) "
        "  AND ( "
        "    kind IN ('poly_updown_resolution', 'poly_mint_sell_v2_resolution') "
        "    OR (kind = 'poly_updown_signal' "
        "        AND data->>'event_type' = 'sleeve_fire_resolved') "
        "  ) "
        "  AND at >= now() - interval '24 hours' "
        "GROUP BY sleeve_id"
    )

    # Phase 18.1: third aggregation — hedge skip events promoted to
    # trading.events (kind='poly_updown_hedge_skip') for dashboard surfacing.
    hedge_skip_sql = (
        "SELECT sleeve_id, COUNT(*)::int AS hedge_skip_count_24h "
        "FROM trading.events "
        "WHERE sleeve_id = ANY($1::text[]) "
        "  AND kind = 'poly_updown_hedge_skip' "
        "  AND at >= now() - interval '24 hours' "
        "GROUP BY sleeve_id"
    )

    async with _deps.pool.acquire() as conn:
        signal_rows = await conn.fetch(signal_sql, list(_POLY_UPDOWN_SLEEVE_IDS))
        resolution_rows = await conn.fetch(resolution_sql, list(_POLY_UPDOWN_SLEEVE_IDS))
        hedge_skip_rows = await conn.fetch(hedge_skip_sql, list(_POLY_UPDOWN_SLEEVE_IDS))

    by_signal: dict[str, dict[str, Any]] = {r["sleeve_id"]: dict(r) for r in signal_rows}
    by_resolution: dict[str, dict[str, Any]] = {r["sleeve_id"]: dict(r) for r in resolution_rows}
    by_hedge_skip: dict[str, int] = {
        r["sleeve_id"]: int(r["hedge_skip_count_24h"]) for r in hedge_skip_rows
    }

    out: list[PolyUpdownSleeveState] = []
    for sleeve_id in _POLY_UPDOWN_SLEEVE_IDS:
        s = by_signal.get(sleeve_id)
        rr = by_resolution.get(sleeve_id)
        hedge_skip_count_24h = by_hedge_skip.get(sleeve_id, 0)

        if s is None and rr is None and hedge_skip_count_24h == 0:
            out.append(
                PolyUpdownSleeveState(
                    sleeve_id=sleeve_id,
                    last_signal=None,
                    last_at=None,
                    last_reason=None,
                    fill_count_24h=0,
                    reject_count_24h=0,
                    last_fill_at=None,
                )
            )
            continue

        if s is not None:
            raw_signal = s.get("last_signal")
            # Coerce unexpected signal vocabulary to None — schema enforces the literal.
            last_signal = raw_signal if raw_signal in ("UP", "DOWN", "NONE") else None
            last_at = s.get("last_at")
            last_reason = s.get("last_reason")
            fill_count_24h = int(s.get("fill_count_24h") or 0)
            reject_count_24h = int(s.get("reject_count_24h") or 0)
            last_fill_at = s.get("last_fill_at")
        else:
            last_signal = None
            last_at = None
            last_reason = None
            fill_count_24h = 0
            reject_count_24h = 0
            last_fill_at = None

        if rr is not None:
            wins_24h = int(rr.get("wins_24h") or 0)
            losses_24h = int(rr.get("losses_24h") or 0)
            hedged_count_24h = int(rr.get("hedged_count_24h") or 0)
            realized_pnl_24h_usd = float(rr.get("realized_pnl_24h_usd") or 0.0)
            last_resolved_at = rr.get("last_resolved_at")
        else:
            wins_24h = 0
            losses_24h = 0
            hedged_count_24h = 0
            realized_pnl_24h_usd = 0.0
            last_resolved_at = None

        out.append(
            PolyUpdownSleeveState(
                sleeve_id=sleeve_id,
                last_signal=last_signal,
                last_at=last_at,
                last_reason=last_reason,
                fill_count_24h=fill_count_24h,
                reject_count_24h=reject_count_24h,
                last_fill_at=last_fill_at,
                wins_24h=wins_24h,
                losses_24h=losses_24h,
                realized_pnl_24h_usd=realized_pnl_24h_usd,
                last_resolved_at=last_resolved_at,
                hedged_count_24h=hedged_count_24h,
                hedge_skip_count_24h=hedge_skip_count_24h,
            )
        )
    return out


__all__ = [
    "_POLY_UPDOWN_SLEEVE_IDS",
    "_reset_bots_dependencies_for_tests",
    "get_poly_updown_state",
    "pause_sleeve",
    "register_bots_dependencies",
    "resume_sleeve",
    "router",
    "set_size",
    "set_tier",
]
