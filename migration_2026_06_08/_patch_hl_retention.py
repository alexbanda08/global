"""Patch engine HL retention to be PER-TABLE instead of one blanket cutoff.

Why (found 2026-07-27): the HL sleeve cards on the production dashboard were stuck
FLAT forever. Root cause was not the API and not the signal code — it was data depth.
`hl_retention` deletes every HL table older than TV_HL_DATA_RETENTION_DAYS (default 7),
so engine.hl_bars held only 42 rows at tf='4h'. The V52 signals need EMA(200) = 200
bars, the ATR_NOTOPVOL gate needs a 500-bar percentile rank, and the HMM regime model
refuses to fit under 200 training bars. With 42 bars every signal degrades to flat.

Fix: keep the indicator inputs long, keep the fat tables short.
  hl_bars    -> 400 days at tf in (1h, 4h, 1d); 15m still pruned at the default
  hl_funding -> 400 days (tiny: 24 kB today)
  everything else unchanged at the default 7 days, because hl_trades is 426 MB and
  hl_asset_ctx is 304 MB per 7 days and the box has 34 GB free.

Idempotent + compile-checked, with a .bak and automatic rollback on syntax error.
Run on vps3:  sudo -u tv /opt/tradingvenue/.venv/bin/python /tmp/_patch_hl_retention.py
"""
from __future__ import annotations
import py_compile, shutil, sys, time
from pathlib import Path

TARGET = Path("/opt/tradingvenue/backend/app/data/hl_retention.py")
MARK = "_LONG_RETENTION_TABLES"

ANCHOR = '''_SWEEP_HOUR_UTC = 3  # 03:00 UTC daily
'''

INSERT = '''
# --- per-table retention override (2026-07-27) ---------------------------------
# Indicator inputs need history; the fat tape tables do not. hl_bars at tf='4h' was
# being pruned to 42 rows by the blanket 7-day cutoff, which silently flattened every
# V52 sleeve signal (EMA200 needs 200 bars, the ATR gate needs a 500-bar rank, and the
# HMM regime fit refuses under 200 training bars). hl_trades (426 MB/7d) and
# hl_asset_ctx (304 MB/7d) must stay on the short default.
_LONG_RETENTION_DAYS = 400
_LONG_RETENTION_TABLES: dict[str, tuple[str, ...] | None] = {
    # table -> tuple of tf values to keep long, or None to keep the whole table long
    "hl_bars": ("1h", "4h", "1d"),   # 15m keeps the short default
    "hl_funding": None,
}

'''

OLD_SWEEP = '''    n = now or datetime.now(UTC)
    cutoff_us = int((n - timedelta(days=retention_days)).timestamp() * 1_000_000)
    results: dict[str, str] = {}
    async with pool.acquire() as conn:
        for table, ts_col in _TABLE_TS_COLS:
            status = await conn.execute(
                f"DELETE FROM engine.{table} WHERE {ts_col} < $1",
                cutoff_us,
            )
            results[table] = status
            log.info(
                "hl_retention.table_swept",
                table=table, ts_col=ts_col, cutoff_us=cutoff_us,
                result=status,
            )
    return results
'''

NEW_SWEEP = '''    n = now or datetime.now(UTC)
    cutoff_us = int((n - timedelta(days=retention_days)).timestamp() * 1_000_000)
    long_cutoff_us = int((n - timedelta(days=_LONG_RETENTION_DAYS)).timestamp() * 1_000_000)
    results: dict[str, str] = {}
    async with pool.acquire() as conn:
        for table, ts_col in _TABLE_TS_COLS:
            if table in _LONG_RETENTION_TABLES:
                tfs = _LONG_RETENTION_TABLES[table]
                if tfs is None:
                    # whole table keeps the long horizon
                    status = await conn.execute(
                        f"DELETE FROM engine.{table} WHERE {ts_col} < $1",
                        long_cutoff_us,
                    )
                else:
                    # protected tfs keep the long horizon, the rest keep the default
                    status = await conn.execute(
                        f"DELETE FROM engine.{table} "
                        f"WHERE ({ts_col} < $1 AND tf = ANY($3::text[])) "
                        f"   OR ({ts_col} < $2 AND NOT (tf = ANY($3::text[])))",
                        long_cutoff_us, cutoff_us, list(tfs),
                    )
                effective = f"long={_LONG_RETENTION_DAYS}d tfs={tfs}"
            else:
                status = await conn.execute(
                    f"DELETE FROM engine.{table} WHERE {ts_col} < $1",
                    cutoff_us,
                )
                effective = f"default={retention_days}d"
            results[table] = status
            log.info(
                "hl_retention.table_swept",
                table=table, ts_col=ts_col, cutoff_us=cutoff_us,
                retention=effective, result=status,
            )
    return results
'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if MARK in src:
        print("[patch] already applied — no-op")
        return 0
    if src.count(ANCHOR) != 1:
        print(f"[patch] ABORT: anchor count {src.count(ANCHOR)} != 1")
        return 2
    if src.count(OLD_SWEEP) != 1:
        print(f"[patch] ABORT: sweep body count {src.count(OLD_SWEEP)} != 1")
        return 2

    bak = TARGET.with_suffix(f".py.bak-hlret-{int(time.time())}")
    shutil.copy2(TARGET, bak)
    out = src.replace(ANCHOR, ANCHOR + INSERT, 1).replace(OLD_SWEEP, NEW_SWEEP, 1)
    TARGET.write_text(out, encoding="utf-8")
    try:
        py_compile.compile(str(TARGET), doraise=True)
    except py_compile.PyCompileError as e:
        shutil.copy2(bak, TARGET)
        print(f"[patch] ROLLED BACK — compile failed: {e}")
        return 3
    print(f"[patch] applied OK (backup {bak.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
