"""
Merge L25 top-off delta into the EXISTING consolidated canonical L25.

Streams [existing canonical {asset}.parquet, new refresh_2026_05_31 delta] through
max_seen dedup + ParquetWriter (row_group_size=200_000, avoids the BTC truncation bug)
into a temp file, then atomically replaces the canonical. Preserves all history in one
file per asset.
"""
from __future__ import annotations
from pathlib import Path
import os, time
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DATA = ROOT / "data" / "v4"
OUT_DIR = DATA / "canonical" / "orderbook_l25"
DELTA_DIR = DATA / "refresh_2026_05_31" / "cache"

ROW_GROUP = 200_000
BATCH_SIZE = 100_000

TARGET_COLS = ["timestamp_us", "slug", "outcome"]
for prefix in ["ask_price", "ask_size", "bid_price", "bid_size"]:
    for i in range(25):
        TARGET_COLS.append(f"{prefix}_{i}")
TARGET_FIELDS = [pa.field("timestamp_us", pa.int64()), pa.field("slug", pa.string()),
                 pa.field("outcome", pa.string())]
for c in TARGET_COLS[3:]:
    TARGET_FIELDS.append(pa.field(c, pa.float32()))
TARGET_SCHEMA = pa.schema(TARGET_FIELDS)


def project_batch(batch):
    arrays = []
    for col in TARGET_COLS:
        if col not in batch.schema.names:
            raise ValueError(f"source missing required col {col}")
        arr = batch.column(col)
        tt = TARGET_SCHEMA.field(col).type
        if arr.type != tt:
            arr = arr.cast(tt)
        arrays.append(arr)
    return pa.RecordBatch.from_arrays(arrays, schema=TARGET_SCHEMA)


def merge_asset(asset):
    canon = OUT_DIR / f"{asset}.parquet"
    delta = DELTA_DIR / f"{asset}_orderbook_L25_topoff.parquet"
    if not canon.exists():
        print(f"  {asset}: NO canonical, skip"); return
    if not delta.exists():
        print(f"  {asset}: NO delta, skip"); return
    tmp = OUT_DIR / f"{asset}.parquet.tmp"
    if tmp.exists():
        tmp.unlink()
    sources = [("canonical", canon), ("delta", delta)]
    writer = pq.ParquetWriter(str(tmp), TARGET_SCHEMA, compression="snappy")
    max_seen = {}
    total_in = 0; total_kept = 0
    for label, src in sources:
        s0 = time.time(); s_in = 0; s_kept = 0
        pf = pq.ParquetFile(str(src))
        for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=TARGET_COLS):
            s_in += batch.num_rows
            slugs = batch.column("slug").to_pylist()
            outs = batch.column("outcome").to_pylist()
            tss = batch.column("timestamp_us").to_pylist()
            keep = [False] * batch.num_rows
            for i in range(batch.num_rows):
                k = (slugs[i], outs[i]); ts = tss[i]; prev = max_seen.get(k)
                if prev is None or ts > prev:
                    keep[i] = True; max_seen[k] = ts
            nk = sum(keep)
            if nk == 0:
                continue
            proj = project_batch(batch if nk == batch.num_rows else batch.filter(pa.array(keep)))
            writer.write_batch(proj, row_group_size=ROW_GROUP)
            s_kept += nk
        total_in += s_in; total_kept += s_kept
        print(f"  [{asset}] {label:<10s} in={s_in:>10,} kept={s_kept:>10,} skip={s_in-s_kept:>10,} ({time.time()-s0:.1f}s)", flush=True)
    writer.close()
    md = pq.ParquetFile(str(tmp)).metadata.num_rows
    if md != total_kept:
        print(f"  [{asset}] !!! MISMATCH writer={total_kept:,} parquet={md:,} — NOT replacing"); return
    os.replace(str(tmp), str(canon))
    sz = canon.stat().st_size / 1024 / 1024
    print(f"  [{asset}] OK -> {canon.name} rows={md:,} size={sz:.0f}MB  (dedup-saved {total_in-total_kept:,})", flush=True)


def main():
    print("[l25-merge] merging delta into canonical/orderbook_l25/...")
    for asset in ["sol", "eth", "btc"]:
        merge_asset(asset)
    print("\n[l25-merge] FINAL:")
    import pandas as pd
    for a in ["btc", "eth", "sol"]:
        p = OUT_DIR / f"{a}.parquet"
        d = pd.read_parquet(p, columns=["timestamp_us"])
        print(f"  {a}: {len(d):,} rows  max={pd.to_datetime(d.timestamp_us.max(), unit='us', utc=True)}")


if __name__ == "__main__":
    main()
