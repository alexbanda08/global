"""Phase 16 BACKUP-07 — 5-min position snapshot writer (sibling asyncio task).

Per RESEARCH.md Q4 + Q5:
- Atomic write via tmp+fsync+os.replace (POSIX atomic on same FS).
- Sibling asyncio task in `_amain`, NOT bolted onto BarEngine wake/eval
  (avoids race with CLAUDE.md invariant #12 trader-write boundary +
  preserves bar-close 3-5s wait per invariant #3).
- 300s monotonic cadence, 48h retention via prune.
- SIGKILL mid-write leaves a `.snap-tmp*` orphan; engine boot calls
  `sweep_temp_files()` to clean.
- Snapshot payload schema: D-11 verbatim.

REQ-ID: BACKUP-07.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol

import structlog

logger = structlog.get_logger(__name__)


# ---- Public constants ------------------------------------------------------

SNAPSHOT_INTERVAL_SECONDS: int = 300  # BACKUP-07: every 5 minutes
PRUNE_RETENTION_SECONDS_DEFAULT: int = 48 * 3600  # BACKUP-07: 48h pruner
TEMP_PREFIX = ".snap-tmp"  # leftover sweep target


# ---- Atomic file write -----------------------------------------------------


def atomic_write(path: Path, data: bytes) -> None:
    """Atomically write `data` to `path`.

    Contract:
      - Caller MUST ensure `path.parent` exists. Fail-loud otherwise.
      - Temp file lives in same directory as target (cross-FS rename is
        NOT atomic on ext4 — RESEARCH §Q4).
      - Fsync THEN rename: a power-loss leaves either old-or-new, never
        a 0-byte file.
    """
    parent = path.parent
    if not parent.exists():
        # Match Path.write_bytes loud failure on missing parent.
        raise FileNotFoundError(f"snapshot dir does not exist: {parent}")
    # NamedTemporaryFile with delete=False: we manage rename ourselves.
    with NamedTemporaryFile(
        mode="wb",
        dir=parent,
        prefix=TEMP_PREFIX + "-",
        delete=False,
    ) as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            os.fsync(tmp.fileno())
        except OSError:
            # Some filesystems (Windows tmpfs in CI) refuse fsync;
            # tolerate but log — the rename is still atomic-on-rename.
            logger.debug("snapshot_writer.fsync_unsupported", path=str(path))
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, path)


def sweep_temp_files(snapshot_dir: Path) -> None:
    """Remove `.snap-tmp*` orphans left by SIGKILL mid-write. Boot-time only."""
    if not snapshot_dir.exists():
        return
    for entry in snapshot_dir.iterdir():
        if entry.name.startswith(TEMP_PREFIX) and entry.is_file():
            try:
                entry.unlink()
            except OSError as e:
                logger.warning(
                    "snapshot_writer.sweep_unlink_failed",
                    path=str(entry),
                    err=str(e),
                )


# ---- Snapshot capture (D-11 schema) ----------------------------------------


class _VenueClientLike(Protocol):
    async def get_user_state(self) -> Any: ...


def _decimal_to_str(d: Decimal | float | int | str) -> str:
    """Stringify so JSON doesn't lose Decimal precision."""
    if isinstance(d, Decimal):
        return format(d, "f")
    return str(d)


async def _capture_one_venue(name: str, client: _VenueClientLike) -> list[dict[str, Any]]:
    """Capture positions from one venue. Errors → empty list + log."""
    try:
        state = await client.get_user_state()
    except Exception as e:  # noqa: BLE001 — we log + degrade
        logger.warning("snapshot_writer.venue_failed", venue=name, err=str(e))
        return []
    out: list[dict[str, Any]] = []
    positions = getattr(state, "positions", None) or []
    for p in positions:
        size = getattr(p, "size", Decimal(0))
        if isinstance(size, str):
            size = Decimal(size)
        if size == 0:
            # HL flat residuals (size==0) are not real positions.
            continue
        side = "long" if size > 0 else "short"
        out.append({
            "symbol": getattr(p, "coin", None) or getattr(p, "symbol", "UNKNOWN"),
            "side": side,
            "qty": _decimal_to_str(abs(size)),
        })
    return out


async def capture_snapshot(
    *,
    venues: dict[str, _VenueClientLike],
) -> dict[str, Any]:
    """Build the D-11 snapshot payload from registered venue clients."""
    venues_payload: dict[str, list[dict[str, Any]]] = {}
    for name, client in venues.items():
        venues_payload[name] = await _capture_one_venue(name, client)
    return {
        "ts": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "engine_pid": os.getpid(),
        "venues": venues_payload,
    }


# ---- Pruner ---------------------------------------------------------------


def prune_old_snapshots(snapshot_dir: Path, *, retention_seconds: int) -> None:
    """Delete `*.json` snapshots older than retention. Walks JSON only —
    leftover `.snap-tmp*` files are handled by `sweep_temp_files`."""
    if not snapshot_dir.exists():
        return
    cutoff = datetime.now(tz=UTC).timestamp() - retention_seconds
    for entry in snapshot_dir.glob("*.json"):
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError as e:
            logger.warning(
                "snapshot_writer.prune_failed",
                path=str(entry),
                err=str(e),
            )


# ---- Public sibling task ---------------------------------------------------


def _ts_filename(now: datetime) -> str:
    """ISO timestamp filename with `:` → `-` for Windows-safe paths."""
    iso = now.isoformat().replace("+00:00", "Z")
    # Replace ':' in HH:MM:SS only — date hyphens unchanged.
    # ISO produces "2026-04-26T15:42:00.123456Z"; strip microseconds.
    if "." in iso:
        head, tail = iso.split(".", 1)
        # Re-attach trailing 'Z'
        z_suffix = "Z" if tail.endswith("Z") else ""
        iso = head + z_suffix
    return iso.replace(":", "-") + ".json"


async def run(
    *,
    venue_clients: dict[str, _VenueClientLike],
    snapshot_dir: Path,
    stop: asyncio.Event,
    interval_seconds: float = SNAPSHOT_INTERVAL_SECONDS,
    retention_seconds: int = PRUNE_RETENTION_SECONDS_DEFAULT,
) -> None:
    """Run the snapshot loop until `stop` is set.

    Spawned via `tg.create_task(run(...))` in `engine.main._amain`.
    Sibling to BarEngine — does NOT participate in bar wake/evaluate.
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    sweep_temp_files(snapshot_dir)  # one-shot orphan cleanup at boot
    logger.info(
        "snapshot_writer.started",
        dir=str(snapshot_dir),
        interval_s=interval_seconds,
        retention_s=retention_seconds,
        venues=list(venue_clients),
    )
    try:
        while not stop.is_set():
            try:
                payload = await capture_snapshot(venues=venue_clients)
                fname = _ts_filename(datetime.now(tz=UTC))
                target = snapshot_dir / fname
                atomic_write(target, json.dumps(payload, indent=2).encode("utf-8"))
                prune_old_snapshots(snapshot_dir, retention_seconds=retention_seconds)
                logger.debug("snapshot_writer.wrote", file=str(target))
            except Exception as e:  # noqa: BLE001 — never crash the loop
                logger.error("snapshot_writer.tick_failed", err=str(e))
            # Wait for either stop or interval, whichever first.
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
                # If we got here, stop was set.
                break
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        logger.info("snapshot_writer.cancelled")
        raise
    finally:
        logger.info("snapshot_writer.stopped")


__all__ = [
    "PRUNE_RETENTION_SECONDS_DEFAULT",
    "SNAPSHOT_INTERVAL_SECONDS",
    "TEMP_PREFIX",
    "atomic_write",
    "capture_snapshot",
    "prune_old_snapshots",
    "run",
    "sweep_temp_files",
]
