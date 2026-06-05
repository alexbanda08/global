"""
Task 4 — strip epoch-0 (1970-01-01) rows from canonical_bbo_trades (aliplayer ticks with
timestamp_ms=0). Rewrite each file atomically, keeping only timestamp_us > 2025-01-01.
"""
import duckdb, glob, os, time
from pathlib import Path
THRESH = 1735689600000000  # 2025-01-01 UTC in us
TR = Path(r"D:\global_data\canonical_bbo_trades")
def log(m): print(f"[fix1970] {time.strftime('%H:%M:%S')} {m}", flush=True)
con = duckdb.connect(); con.execute("PRAGMA memory_limit='8GB'")
for p in sorted(TR.glob("*.parquet")):
    pp = str(p).replace("\\", "/"); coin = p.stem
    before, bad = con.execute(f"SELECT count(*), sum(CASE WHEN timestamp_us<={THRESH} THEN 1 ELSE 0 END) FROM read_parquet('{pp}')").fetchone()
    if not bad:
        log(f"{coin}: clean ({before:,} rows) — skip"); continue
    tmp = str(p.with_suffix(".tmp.parquet")).replace("\\", "/")
    con.execute(f"COPY (SELECT * FROM read_parquet('{pp}') WHERE timestamp_us > {THRESH}) TO '{tmp}' (FORMAT parquet, COMPRESSION snappy)")
    after = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
    assert after == before - bad, f"{coin}: row mismatch {after} != {before}-{bad}"
    os.replace(tmp, p)
    log(f"{coin}: {before:,} -> {after:,} (dropped {bad:,})")
log("=== DONE ===")
