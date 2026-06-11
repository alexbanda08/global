"""
L25 delta merge — pyarrow streaming (memory-light max_seen dedup), reads gz delta directly.
Writes tmp to D: (C: too tight for BTC's 8GB rewrite) then does a safe cross-drive swap:
remove canon on C: (frees space) -> move verified D: tmp -> C:. Aborts if merged < canon.
Dedup key (slug, outcome, timestamp_us); canon wins exact dups, delta supplies newer ts.
"""
from __future__ import annotations
from pathlib import Path
import os, time, gzip
import pandas as pd, pyarrow as pa, pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT_DIR = ROOT / "data" / "v4" / "canonical" / "orderbook_l25"
RAW = ROOT / "data" / "v4" / "refresh_2026_06_11" / "raw"
DTMP = Path(r"D:\refresh_tmp_2026_06_11"); DTMP.mkdir(parents=True, exist_ok=True)
def log(m): print(f"[l25] {time.strftime('%H:%M:%S')} {m}", flush=True)

TARGET_COLS = ["timestamp_us", "slug", "outcome"]
for p in ["ask_price","ask_size","bid_price","bid_size"]:
    TARGET_COLS += [f"{p}_{i}" for i in range(25)]
FIELDS = [pa.field("timestamp_us", pa.int64()), pa.field("slug", pa.string()), pa.field("outcome", pa.string())]
FIELDS += [pa.field(c, pa.float32()) for c in TARGET_COLS[3:]]
SCHEMA = pa.schema(FIELDS)
ROW_GROUP, BATCH = 200_000, 100_000

def load_delta(gz):
    df = pd.read_csv(gz, compression="gzip", usecols=lambda c: c in TARGET_COLS)
    for c in TARGET_COLS[3:]:
        if c in df.columns: df[c] = df[c].astype("float32")
    df["timestamp_us"] = df["timestamp_us"].astype("int64")
    df = df[TARGET_COLS]
    return pa.Table.from_pandas(df, schema=SCHEMA, preserve_index=False)

def project(batch):
    arrs = []
    for col in TARGET_COLS:
        a = batch.column(col); tt = SCHEMA.field(col).type
        if a.type != tt: a = a.cast(tt)
        arrs.append(a)
    return pa.RecordBatch.from_arrays(arrs, schema=SCHEMA)

def merge_asset(a):
    canon = OUT_DIR / f"{a}.parquet"
    gz = RAW / f"{a}_orderbook_L25.csv.gz"
    if not canon.exists(): log(f"  {a}: no canon, skip"); return
    if not gz.exists(): log(f"  {a}: no delta, skip"); return
    before = pq.ParquetFile(str(canon)).metadata.num_rows
    delta_tbl = load_delta(gz); log(f"  {a}: delta {delta_tbl.num_rows:,} rows loaded")
    tmp = DTMP / f"{a}.parquet"
    if tmp.exists(): tmp.unlink()
    writer = pq.ParquetWriter(str(tmp), SCHEMA, compression="zstd")
    max_seen = {}; kept = 0; t0 = time.time()
    # source 1: canon (streamed), source 2: delta (batched)
    def stream_batches():
        pf = pq.ParquetFile(str(canon))
        for b in pf.iter_batches(batch_size=BATCH, columns=TARGET_COLS): yield b
        for b in delta_tbl.to_batches(max_chunksize=BATCH): yield b
    for batch in stream_batches():
        slugs = batch.column("slug").to_pylist(); outs = batch.column("outcome").to_pylist()
        tss = batch.column("timestamp_us").to_pylist()
        keep = [False]*batch.num_rows
        for i in range(batch.num_rows):
            k = (slugs[i], outs[i]); ts = tss[i]; prev = max_seen.get(k)
            if prev is None or ts > prev: keep[i] = True; max_seen[k] = ts
        nk = sum(keep)
        if nk == 0: continue
        writer.write_batch(project(batch if nk == batch.num_rows else batch.filter(pa.array(keep))), row_group_size=ROW_GROUP)
        kept += nk
    writer.close()
    total = pq.ParquetFile(str(tmp)).metadata.num_rows
    if total != kept:
        log(f"  {a}: !!! writer/meta mismatch {kept} vs {total} — NOT swapping"); tmp.unlink(); return
    if total < before:
        log(f"  {a}: ABORT merged {total:,} < canon {before:,} — NOT swapping"); tmp.unlink(); return
    # safe cross-drive swap
    os.remove(canon)
    import shutil; shutil.move(str(tmp), str(canon))
    log(f"  {a}: {before:,} -> {total:,} (+{total-before:,}) size={canon.stat().st_size//1024//1024}MB ({time.time()-t0:.0f}s)")

for a in ["sol", "eth", "btc"]:   # btc last (biggest), after C: freed by smaller swaps
    merge_asset(a)
import shutil; shutil.rmtree(DTMP, ignore_errors=True)
log("=== L25 DONE ===")
for a in ["btc","eth","sol"]:
    d = pd.read_parquet(OUT_DIR/f"{a}.parquet", columns=["timestamp_us"])
    log(f"  {a}: {len(d):,} max={pd.to_datetime(d.timestamp_us.max(),unit='us',utc=True)}")
