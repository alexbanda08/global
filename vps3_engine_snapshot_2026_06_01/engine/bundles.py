"""Bundle config loader (Phase 23 · D-19/D-20/D-21).

Bundle = group of same-venue sleeves sharing a single ``total_size_usd`` budget.
Bundle changes require restart per CLAUDE invariant #12 (no mid-bar mutation);
the YAML file is read on every ``/sleeves`` and ``/bundles`` request, but the
tv-engine itself reads the live config at boot and reconciles on the next bar
boundary — never mid-bar.

Source of truth: ``/etc/tv/bundles.yaml`` mode 0640 root:tv (installed by
``infra/bootstrap.sh``'s ``_install_bundles_yaml``).

Schema (D-21):
    bundles:
      - bundle_id: <str>          # unique identifier
        venue: HL | POLY          # D-20 — cross-venue forbidden
        total_size_usd: <float>   # bundle-level dollar budget
        paused: <bool>            # if true, all member sleeves run in shadow
        sleeve_ids: [<str>, ...]  # non-empty list of canonical sleeve_id strings

Validation (raises ``ValueError`` on failure):
    - All five fields present per entry
    - ``venue`` ∈ {"HL", "POLY"}      (D-20)
    - ``sleeve_ids`` is a non-empty list

CLAUDE invariant #13 — read-only Storedata: this loader touches only the
local YAML file. It does NOT query ``public.*`` (Storedata) or ``trading.*``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REQUIRED_FIELDS: tuple[str, ...] = (
    "bundle_id",
    "venue",
    "total_size_usd",
    "paused",
    "sleeve_ids",
)
ALLOWED_VENUES: frozenset[str] = frozenset({"HL", "POLY"})


@dataclass(frozen=True)
class Bundle:
    """Validated bundle record. Immutable per dataclass(frozen=True)."""

    bundle_id: str
    venue: str  # 'HL' | 'POLY' (D-20)
    total_size_usd: float
    paused: bool
    sleeve_ids: tuple[str, ...]


def load_bundles(path: str = "/etc/tv/bundles.yaml") -> list[Bundle]:
    """Load + validate bundle config.

    Hand-editable; restart required to apply changes (CLAUDE inv #12).

    Args:
        path: filesystem path to the bundles YAML file. Default
              ``/etc/tv/bundles.yaml`` matches D-19 install location.

    Returns:
        List of validated ``Bundle`` records. Empty list if the YAML file
        contains no ``bundles:`` key or an empty list.

    Raises:
        FileNotFoundError: ``path`` does not exist.
        ValueError: schema validation failed (missing field, bad venue,
                    empty sleeve_ids list, etc.). The error message names
                    the offending bundle_id (or '<unknown>' if missing).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"bundles config not found: {path}")
    with p.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    raw_bundles = raw.get("bundles", []) or []
    out: list[Bundle] = []
    for b in raw_bundles:
        if not isinstance(b, dict):
            raise ValueError(
                f"bundle entry must be a dict, got {type(b).__name__}"
            )
        for field in REQUIRED_FIELDS:
            if field not in b:
                raise ValueError(
                    f"bundle {b.get('bundle_id', '<unknown>')} missing {field}"
                )
        if b["venue"] not in ALLOWED_VENUES:
            raise ValueError(
                f"bundle {b['bundle_id']} venue must be HL|POLY (D-20), "
                f"got {b['venue']!r}"
            )
        if not isinstance(b["sleeve_ids"], list) or len(b["sleeve_ids"]) == 0:
            raise ValueError(
                f"bundle {b['bundle_id']} sleeve_ids must be non-empty list"
            )
        out.append(
            Bundle(
                bundle_id=str(b["bundle_id"]),
                venue=str(b["venue"]),
                total_size_usd=float(b["total_size_usd"]),
                paused=bool(b["paused"]),
                sleeve_ids=tuple(str(s) for s in b["sleeve_ids"]),
            )
        )
    return out


def find_bundle_for_sleeve(
    bundles: list[Bundle], sleeve_id: str
) -> Bundle | None:
    """Return the bundle containing ``sleeve_id``, or ``None`` if unbundled."""
    for b in bundles:
        if sleeve_id in b.sleeve_ids:
            return b
    return None


__all__ = [
    "ALLOWED_VENUES",
    "Bundle",
    "REQUIRED_FIELDS",
    "find_bundle_for_sleeve",
    "load_bundles",
]
