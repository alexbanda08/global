"""
Recompress big SNAPPY canonical parquets -> ZSTD to reclaim C: space (lossless; loaders
auto-detect codec). DuckDB streaming scan->write preserves row order (L25 needs it for the
next max_seen merge). BTC L25 (8GB) writes tmp to D: + cross-drive safe swap; rest tmp on C:.
Verifies row count == before AND the new file is actually smaller before replacing.
"""
from __future__ import annotations
from pathlib import Path
import os, time, shutil
import duckdb
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
C = ROOT / "data" / "v4" / "canonical"
DTMP = Path(r"D:\recompress_tmp"); DTMP.mkdir(parents=True, exist_ok=True)
def log(m): print(f"[zstd] {time.strftime('%H:%M:%S')} {m}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=4")
con.execute("PRAGMA memory_limit='8GB'")
con.execute(f"PRAGMA temp_directory='{str(DTMP).replace(chr(92),'/')}'")
# preserve_insertion_order stays TRUE (default) -> output row order == input

# (relpath, row_group_size, tmp_on_d) — smallest first so C: frees progressively; btc L25 last on D:
FILES = [
    ("chainlink_rtds.parquet", 500_000, False),
    ("trading_events_30d.parquet", 500_000, False),
    ("trades_polymarket_hf/eth.parquet", 500_000, False),
    ("trades_polymarket_hf/btc.parquet", 500_000, False),
    ("hyperliquid_liquidations_full.parquet", 500_000, False),
    ("hyperliquid_trades_30d.parquet", 500_000, False),
    ("trades_polymarket/sol.parquet", 500_000, False),
    ("trades_polymarket/eth.parquet", 500_000, False),
    ("orderbook_l25/sol.parquet", 200_000, False),
    ("cex_futures_trades.parquet", 500_000, False),
    ("cex_futures_ticker.parquet", 500_000, False),
    ("trades_polymarket/btc.parquet", 500_000, False),
    ("orderbook_l25/eth.parquet", 200_000, False),
    ("klines_1s.parquet", 500_000, False),
    ("orderbook_l25_backfill/eth.parquet", 200_000, False),
    ("orderbook_l25_backfill/btc.parquet", 200_000, False),
    ("orderbook_l25/btc.parquet", 200_000, True),   # 8GB -> tmp on D:, swap
]

def recompress(rel, rg, on_d):
    src = C / rel
    if not src.exists(): log(f"  {rel}: missing, skip"); return
    cur_codec = pq.ParquetFile(str(src)).metadata.row_group(0).column(0).compression
    before_rows = pq.ParquetFile(str(src)).metadata.num_rows
    before_sz = src.stat().st_size
    if cur_codec == "ZSTD": log(f"  {rel}: already ZSTD, skip"); return
    tmp = (DTMP / rel.replace("/", "_")) if on_d else src.with_suffix(".zst.tmp.parquet")
    tmpf = str(tmp).replace(chr(92), "/"); srcf = str(src).replace(chr(92), "/")
    t0 = time.time()
    con.execute(f"COPY (SELECT * FROM read_parquet('{srcf}')) TO '{tmpf}' (FORMAT parquet, COMPRESSION zstd, ROW_GROUP_SIZE {rg})")
    new_rows = pq.ParquetFile(str(tmp)).metadata.num_rows
    new_sz = tmp.stat().st_size
    if new_rows != before_rows:
        log(f"  {rel}: ROW MISMATCH {new_rows} != {before_rows} — NOT replacing"); os.remove(tmp); return
    if new_sz >= before_sz:
        log(f"  {rel}: zstd not smaller ({new_sz//1024//1024} >= {before_sz//1024//1024}MB) — keep snappy"); os.remove(tmp); return
    if on_d:
        os.remove(src); shutil.move(tmpf, str(src))
    else:
        os.replace(tmpf, str(src))
    log(f"  {rel}: {before_sz//1024//1024}MB -> {new_sz//1024//1024}MB (saved {(before_sz-new_sz)//1024//1024}MB) rows={new_rows:,} ({time.time()-t0:.0f}s)")

saved0 = None
for rel, rg, on_d in FILES:
    recompress(rel, rg, on_d)
con.close()
shutil.rmtree(DTMP, ignore_errors=True)
log("=== RECOMPRESS DONE ===")
