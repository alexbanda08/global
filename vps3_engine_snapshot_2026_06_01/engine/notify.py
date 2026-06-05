"""Cross-process event bus helper — pg_notify emit for tv-engine.

Wraps Postgres LISTEN/NOTIFY for the ``tv_events`` channel. tv-api opens
a dedicated LISTEN connection (see ``backend/app/api/event_bus.py``) and
fans events out to ws_terminal subscribers.

Invariants:

- **CLAUDE.md inv #10** — secrets / credentials must NEVER appear in NOTIFY
  payloads. Callers are responsible for building payload dicts that do
  not include keys, env, or DSN values.
- **8000-byte cap** — Postgres caps NOTIFY at 8000 bytes. Oversized
  payloads are reduced to a ``{row_id, table, truncated}`` reference;
  ws_terminal resolves the full row via ``pool.acquire() → SELECT FROM
  <table> WHERE id = $1``.
- **Best-effort emit** — exceptions raised by ``conn.execute`` are caught
  and logged. A failed NOTIFY must NOT crash tv-engine.
- **Ordering — emit after INSERT commits.** Callers MUST call
  ``notify_event`` AFTER the surrounding INSERT statement's transaction
  has committed. Reason: oversized payloads degrade to a ``{row_id,
  table}`` reference; a subscriber that resolves via a SELECT before the
  INSERT commits will miss the row. Postgres NOTIFY semantics also
  drop the notification on ROLLBACK, which is why this helper does NOT
  issue any BEGIN/COMMIT side-calls of its own — it executes a single
  ``SELECT pg_notify(...)`` on the connection the caller passes in.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_CHANNEL = "tv_events"
_MAX_PAYLOAD_BYTES = 8000

# Channel + envelope overhead headroom — keeps the full NOTIFY message
# (channel name + JSON envelope wrapping) under the 8000-byte cap even
# when the inner payload is exactly _MAX_PAYLOAD_BYTES - _OVERHEAD bytes.
_OVERHEAD = 200

_NOTIFY_SQL = """
SELECT pg_notify($1, json_build_object(
    'v',       1,
    'kind',    $2::text,
    'ts',      to_char(now() at time zone 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"'),
    'payload', $3::jsonb
)::text)
""".strip()


async def notify_event(
    conn: Any,
    *,
    kind: str,
    payload: dict[str, Any],
) -> None:
    """Emit a ``pg_notify`` on the ``tv_events`` channel.

    Parameters
    ----------
    conn:
        An asyncpg connection (or anything with an awaitable ``.execute``).
        The caller is responsible for the surrounding transaction; the
        emit is a single statement and does not issue its own COMMIT.
    kind:
        One of: ``fill``, ``pnl_snapshot``, ``rail_fire``, ``kill_triggered``,
        ``kill_complete``, ``keepalive_tick``, ``keepalive_expired``,
        ``supervisor_event``.
    payload:
        Event-specific dict. Must NOT contain secrets / credentials. If
        the JSON-encoded payload would exceed roughly 7800 bytes, it is
        reduced to a ``{row_id, table, truncated}`` reference. Callers
        that want this fallback to work should include ``id`` and
        ``_table`` keys.
    """
    try:
        payload_text = json.dumps(payload, default=str)
        if len(payload_text.encode("utf-8")) + _OVERHEAD > _MAX_PAYLOAD_BYTES:
            row_id = payload.get("id")
            table = payload.get("_table")
            if row_id is None:
                log.warning(
                    "notify.payload_oversized_no_id",
                    kind=kind,
                    size=len(payload_text),
                )
            payload = {
                "row_id": row_id,
                "table": table,
                "truncated": True,
            }
            payload_text = json.dumps(payload, default=str)
        await conn.execute(_NOTIFY_SQL, _CHANNEL, kind, payload_text)
    except Exception:
        log.exception("notify.emit_failed", kind=kind)


__all__ = ["notify_event"]
