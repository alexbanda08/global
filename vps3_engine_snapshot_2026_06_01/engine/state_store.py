"""Atomic Pydantic-state file persistence (Phase 9, Task 4 · STRAT-HL-08).

``AtomicStateStore[T]`` is a generic tmp-write + fsync + os.replace store
for any frozen Pydantic v2 model. Used by ``HyperliquidXsmController`` to
persist ``XSMState`` across weekly rebalances.

Atomic-write pattern (canonical — do NOT invent variations):

1. ``open(tmp, 'wb')`` — write serialized JSON bytes.
2. ``os.fsync(fd)`` — flush page cache to disk.
3. ``os.replace(tmp, target)`` — atomic rename on POSIX (same filesystem).

Crash-recovery semantics:

* If ``path`` exists and parses → return the state.
* If ``path`` is missing → return ``None`` (caller constructs fresh state).
* If ``path`` is corrupt (truncated JSON, bad schema, OS error) →
  return ``None`` (fail-safe). A sibling ``.tmp`` file left over from a
  crashed save is ignored — only ``path`` is read.

The fail-safe-to-None behavior trades a tiny chance of amnesia for
guaranteed availability: the XSM controller reconstructs a fresh state
and emits ``trading.events(kind='xsm_state_reset')`` when this happens
(see Phase 9 Task 5).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ValidationError


class AtomicStateStore[T: BaseModel]:
    """Generic atomic file store for frozen Pydantic models.

    Parameters
    ----------
    path:
        Target JSON file. Parent directories are created on ``save`` if
        they don't already exist.
    model:
        The Pydantic class used to validate loaded JSON. Must be a
        ``BaseModel`` subclass exposing ``model_validate_json`` /
        ``model_dump_json``.
    """

    def __init__(self, path: Path, model: type[T]) -> None:
        self.path = path
        self.model = model

    def load(self) -> T | None:
        """Load state from ``path`` or return ``None`` on miss/corruption.

        Returning ``None`` (instead of raising) is deliberate: callers
        should fall back to a fresh state and emit a single ``kind='state_reset'``
        audit event. See module docstring.
        """
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
            return self.model.model_validate_json(raw)
        except (json.JSONDecodeError, ValidationError, OSError, ValueError):
            return None

    def save(self, state: T) -> None:
        """Atomically persist ``state``.

        Tmp-write + fsync + ``os.replace`` ensures the on-disk ``path``
        file is never partially-written: either it reflects the previous
        state (if the crash occurred before rename) or the new state
        (if after). There is no intermediate state.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        data = state.model_dump_json()

        # Write + fsync the tmp file descriptor BEFORE the rename. Using
        # low-level open() lets us guarantee fsync on the data — write_text
        # closes the file without fsync on some platforms.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)

        # Atomic rename on POSIX (same filesystem). On Windows, os.replace
        # is also atomic per the stdlib docs — it silently overwrites.
        os.replace(tmp, self.path)


__all__ = ["AtomicStateStore"]
