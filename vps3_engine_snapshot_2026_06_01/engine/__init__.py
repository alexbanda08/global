"""BarEngine package — UTC bar-boundary scheduler for sleeve dispatch.

Phase 7 populates this package with:

* ``bar_engine`` — the asyncio-driven scheduler (single long-running coroutine;
  NOT cron / apscheduler / systemd timer per CLAUDE.md invariant).
* ``models`` — Pydantic + dataclass shapes for ``engine.bar_runs`` rows and
  in-memory sleeve registrations.

Public surface re-exported here for import ergonomics.
"""
from backend.app.engine.bar_engine import BarEngine
from backend.app.engine.models import BarRun, SleeveRegistration

__all__ = ["BarEngine", "BarRun", "SleeveRegistration"]
