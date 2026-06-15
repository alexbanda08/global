"""
Hyperliquid refresh merge — full-replace each canonical HL parquet from the VPS3 gz snapshot
(klines/liquidations_full/funding/metrics = full; trades = 32d rolling). DuckDB coerces each
gz to the existing canonical schema (by name) and writes ZSTD. Guards: never replace with fewer
rows than the gz produced, and (for full mirrors) abort if the new file is smaller than canon.
"""
from __future__ import annotations
from pathlib import Path
import os, time
import duckdb

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
C = ROOT / "data" / "v4" / "canonical"
RAW = ROOT / "data" / "v4" / "refresh_hl_2026_06_15" / "raw"
def log(m): print(f"[hl] {time.strftime('%H:%M:%S')} {m}", flush=True)

con = duckdb.connect(); con.execute("PRAGMA threads=4"); con.execute("PRAGMA memory_limit='8GB'")
con.execute("PRAGMA temp_directory='D:/hl_tmp'"); con.execute("PRAGMA preserve_insertion_order=false")

def schema(p):
    return [(r[0], r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{str(p).replace(chr(92),'/')}')").fetchall()]
def gz_cols(gz):
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{gz}', header=true, all_varchar=true, sample_size=-1)").fetchall()}

def replace_from_gz(canon_rel, gz_name, rolling=False):
    canon = C / canon_rel; gz = RAW / gz_name
    if not gz.exists(): log(f"  {canon_rel}: NO gz, skip"); return
    if not canon.exists(): log(f"  {canon_rel}: NO canon, skip"); return
    sch = schema(canon); gzf = str(gz).replace(chr(92), "/"); dcols = gz_cols(gzf)
    parts = []
    for name, typ in sch:
        q = f'"{name}"'
        parts.append(f"TRY_CAST(NULLIF({q},'') AS {typ}) AS {q}" if name in dcols else f"CAST(NULL AS {typ}) AS {q}")
    sel = f"SELECT {', '.join(parts)} FROM read_csv('{gzf}', header=true, all_varchar=true, sample_size=-1)"
    before = con.execute(f"SELECT count(*) FROM read_parquet('{str(canon).replace(chr(92),'/')}')").fetchone()[0]
    tmp = canon.with_suffix(".tmp.parquet"); tmpf = str(tmp).replace(chr(92), "/")
    con.execute(f"COPY ({sel}) TO '{tmpf}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE 500000)")
    total = con.execute(f"SELECT count(*) FROM read_parquet('{tmpf}')").fetchone()[0]
    # full mirrors must never shrink; rolling (trades) is allowed to differ
    if total == 0 or (not rolling and total < before):
        os.remove(tmp); raise SystemExit(f"ABORT {canon_rel}: total {total:,} (before {before:,}) — canon untouched")
    os.replace(tmpf, str(canon))
    log(f"  {canon_rel}: {before:,} -> {total:,} ({'rolling' if rolling else 'full'})")

log("=== HL merge ===")
replace_from_gz("hyperliquid_klines.parquet",            "hyperliquid_klines.csv.gz")
replace_from_gz("hyperliquid_liquidations_full.parquet", "hyperliquid_liquidations.csv.gz")
replace_from_gz("hyperliquid_funding.parquet",           "hyperliquid_funding.csv.gz")
replace_from_gz("hyperliquid_metrics.parquet",           "hyperliquid_metrics.csv.gz")
replace_from_gz("hyperliquid_trades_30d.parquet",        "hyperliquid_trades.csv.gz", rolling=True)
con.close()
import shutil; shutil.rmtree("D:/hl_tmp", ignore_errors=True)
log("=== HL merge DONE ===")
