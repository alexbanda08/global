"""Phase 16 OPS-02 — pre-deploy bar-boundary helper.

Generalises ``scripts/pre_deploy_check.sh`` from a single hard-coded
``5m`` boundary check to a registry-driven enumeration of every active
sleeve's timeframe.

Sources of truth:
- HL: ``backend.app.engine.main._HL_CONTROLLERS`` — each controller
  exposes ``.symbols`` + ``.timeframes`` (Phase 6/7.1 wiring).
- Poly: ``backend.app.portfolio._REGISTERED_POLY_CONTROLLERS`` — each
  controller's ``.slots()`` returns ``[(sym, tf), ...]`` (Phase 15).
- Default fallback when both registries are empty (e.g. CI / pre-deploy
  invocation with no engine boot): ``{5m, 15m, 4h, 1w}`` — the v0.1
  sleeve set (V52 4h + Poly updown 5m+15m + V24-XSM 1w).

CLI surface (consumed by the bash script):

    python -m backend.app.engine.preflight enumerate_tfs
        → prints space-separated TFs to stdout (e.g. "4h 5m 15m 1w").

    python -m backend.app.engine.preflight nearest_boundary_seconds 5m,15m,4h
        → prints a single integer (seconds-to-nearest-boundary across all
        listed TFs) to stdout. Used by the bash script's `< 60` refusal.

REQ-ID: OPS-02.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Iterable

# Default fallback: v0.1 sleeve set per RESEARCH §⚠ deviation #3.
_DEFAULT_FALLBACK_TFS: tuple[str, ...] = ("5m", "15m", "4h", "1w")


# ---------------------------------------------------------------------------
# TF parsing
# ---------------------------------------------------------------------------


_UNIT_SECONDS: dict[str, int] = {
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 7 * 86400,
}


def _tf_to_seconds(tf: str) -> int:
    """Parse a timeframe string like ``5m`` / ``4h`` / ``1d`` / ``1w`` to seconds.

    Raises ``ValueError`` on unknown units so the bash script surfaces a
    loud error rather than silently mis-computing a boundary.
    """
    if not tf or len(tf) < 2:
        raise ValueError(f"invalid timeframe: {tf!r}")
    unit = tf[-1].lower()
    if unit not in _UNIT_SECONDS:
        raise ValueError(f"unknown TF unit {unit!r} in {tf!r}")
    try:
        n = int(tf[:-1])
    except ValueError as e:
        raise ValueError(f"non-integer count in TF {tf!r}") from e
    if n <= 0:
        raise ValueError(f"non-positive count in TF {tf!r}")
    return n * _UNIT_SECONDS[unit]


# ---------------------------------------------------------------------------
# Registry enumeration
# ---------------------------------------------------------------------------


def _enumerate_hl_tfs() -> list[str]:
    """Pull TFs from registered HL controllers; tolerate import-time loops."""
    try:
        from backend.app.engine import main as engine_main
    except Exception:
        return []
    out: list[str] = []
    for controller in getattr(engine_main, "_HL_CONTROLLERS", []) or []:
        tfs = getattr(controller, "timeframes", None) or []
        for tf in tfs:
            if isinstance(tf, str):
                out.append(tf)
    return out


def _enumerate_poly_tfs() -> list[str]:
    """Pull TFs from registered Poly updown controllers via .slots()."""
    try:
        from backend.app import portfolio as poly_reg
    except Exception:
        return []
    out: list[str] = []
    for controller in getattr(poly_reg, "_REGISTERED_POLY_CONTROLLERS", []) or []:
        slots_fn = getattr(controller, "slots", None)
        if not callable(slots_fn):
            continue
        try:
            for entry in slots_fn():
                if isinstance(entry, (tuple, list)) and len(entry) >= 2:
                    tf = entry[1]
                    if isinstance(tf, str):
                        out.append(tf)
        except Exception:
            # A malformed controller MUST not break the preflight check.
            continue
    return out


def enumerate_tfs() -> list[str]:
    """Return the deduped, sorted list of active sleeve TFs.

    Falls back to the v0.1 default set when both registries are empty.
    Sorting is alphabetical on the raw string for stable CI snapshots
    (NOT seconds — operators read the bash output and 4h/5m/15m/1w
    alphabetical ordering is just as legible as numeric).
    """
    seen: set[str] = set()
    for tf in (*_enumerate_hl_tfs(), *_enumerate_poly_tfs()):
        seen.add(tf)
    if not seen:
        seen.update(_DEFAULT_FALLBACK_TFS)
    return sorted(seen)


# ---------------------------------------------------------------------------
# Boundary math
# ---------------------------------------------------------------------------


def _distance_to_nearest_for_tf(tf_secs: int, now_epoch: int) -> int:
    """For one TF: min of (seconds-since-past-boundary, seconds-until-next)."""
    since_past = now_epoch % tf_secs
    until_next = tf_secs - since_past
    if until_next == tf_secs:  # exactly on a boundary
        until_next = 0
    return min(since_past, until_next)


def nearest_boundary_seconds(
    tfs: Iterable[str],
    *,
    now: datetime | None = None,
) -> int:
    """Return the minimum distance (in seconds) from ``now`` to any boundary
    of any TF in ``tfs``. ``now`` defaults to ``datetime.now(UTC)``.

    Used by ``scripts/pre_deploy_check.sh``: refuses deploy when this
    value is ``< 60`` (per OPS-02 + PITFALLS §1.2).
    """
    if now is None:
        now = datetime.now(tz=UTC)
    now_epoch = int(now.timestamp())
    best = None
    for tf in tfs:
        secs = _tf_to_seconds(tf)
        d = _distance_to_nearest_for_tf(secs, now_epoch)
        if best is None or d < best:
            best = d
    return best if best is not None else 0


# ---------------------------------------------------------------------------
# CLI entry — `python -m backend.app.engine.preflight <subcommand>`
# ---------------------------------------------------------------------------


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(
            "usage: python -m backend.app.engine.preflight {enumerate_tfs|nearest_boundary_seconds <tfs_csv>}",
            file=sys.stderr,
        )
        return 2
    sub = argv[0]
    if sub == "enumerate_tfs":
        tfs = enumerate_tfs()
        print(" ".join(tfs))
        return 0
    if sub == "nearest_boundary_seconds":
        if len(argv) < 2:
            print(
                "missing TF list (comma-separated, e.g. '5m,15m,4h')",
                file=sys.stderr,
            )
            return 2
        tfs = [t.strip() for t in argv[1].split(",") if t.strip()]
        try:
            d = nearest_boundary_seconds(tfs)
        except ValueError as e:
            print(f"preflight error: {e}", file=sys.stderr)
            return 2
        print(d)
        return 0
    print(f"unknown subcommand: {sub}", file=sys.stderr)
    return 2


def main() -> None:
    raise SystemExit(_cli(sys.argv[1:]))


if __name__ == "__main__":
    main()


__all__ = [
    "enumerate_tfs",
    "main",
    "nearest_boundary_seconds",
]
