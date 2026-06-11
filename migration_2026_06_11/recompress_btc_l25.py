"""
Recompress the two big BTC L25 parquets SNAPPY->ZSTD via pyarrow streaming (low-memory,
order-preserving — DuckDB COPY choked on these 97.9M-row wide files). tmp on D: + safe swap.
"""
from pathlib import Path
import os, time, shutil
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
C = ROOT / "data" / "v4" / "canonical"
DTMP = Path(r"D:\recompress_tmp2"); DTMP.mkdir(parents=True, exist_ok=True)
def log(m): print(f"[zstd-btc] {time.strftime('%H:%M:%S')} {m}", flush=True)

for rel in ["orderbook_l25/btc.parquet", "orderbook_l25_backfill/btc.parquet"]:
    src = C / rel
    pf = pq.ParquetFile(str(src))
    before_rows = pf.metadata.num_rows; before_sz = src.stat().st_size
    codec = pf.metadata.row_group(0).column(0).compression
    if codec == "ZSTD": log(f"{rel}: already ZSTD, skip"); continue
    tmp = DTMP / rel.replace("/", "_")
    if tmp.exists(): tmp.unlink()
    t0 = time.time()
    w = pq.ParquetWriter(str(tmp), pf.schema_arrow, compression="zstd", compression_level=9)
    for b in pf.iter_batches(batch_size=100_000):
        w.write_batch(b, row_group_size=200_000)
    w.close()
    new_rows = pq.ParquetFile(str(tmp)).metadata.num_rows; new_sz = tmp.stat().st_size
    if new_rows != before_rows or new_sz >= before_sz:
        log(f"{rel}: BAD (rows {new_rows} vs {before_rows}, sz {new_sz//1024//1024} vs {before_sz//1024//1024}) — NOT swapping"); tmp.unlink(); continue
    os.remove(src); shutil.move(str(tmp), str(src))
    log(f"{rel}: {before_sz//1024//1024}MB -> {new_sz//1024//1024}MB (saved {(before_sz-new_sz)//1024//1024}MB) rows={new_rows:,} ({time.time()-t0:.0f}s)")
shutil.rmtree(DTMP, ignore_errors=True)
log("=== BTC L25 recompress DONE ===")
