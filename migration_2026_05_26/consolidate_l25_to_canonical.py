"""
Stream-consolidate L25 source parquets into canonical/orderbook_l25/{asset}.parquet.

Sources have TWO different schemas (a 104-col "minimal" set used by cache_pre +
refresh_2026_05_16/cache, and a 109-col "full" set used by everything else with
different column ORDER and a dictionary-typed `outcome`). We project every batch
onto a unified 103-col target schema (the columns load_orderbook_l25_streaming
actually uses):
  timestamp_us:int64, slug:string, outcome:string,
  ask_price_0..24:float32, ask_size_0..24:float32,
  bid_price_0..24:float32, bid_size_0..24:float32

Dedup: maintain max_seen[(slug, outcome)] -> ts_us. Keep rows where ts > max_seen.
Sources are processed earliest-first.

Output: data/v4/canonical/orderbook_l25/{btc,eth,sol}.parquet
Streamed via ParquetWriter with row_group_size=200_000 to avoid the truncation
bug seen with concat_tables → write_table on the BTC file in an earlier attempt.
"""
from __future__ import annotations
from pathlib import Path
import time
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DATA = ROOT / "data" / "v4"
OUT_DIR = DATA / "canonical" / "orderbook_l25"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ("refresh_2026_05_16/cache_pre",  "_orderbook_L25_pre_apr22.parquet"),
    ("refresh_2026_05_06/cache",      "_orderbook_L25.parquet"),
    ("refresh_2026_05_16/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_19/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_21/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_25/cache",      "_orderbook_L25_delta.parquet"),
    ("refresh_2026_05_26/cache",      "_orderbook_L25_topoff.parquet"),
]

ROW_GROUP = 200_000
BATCH_SIZE = 100_000

# Target unified schema (103 cols)
TARGET_COLS = ["timestamp_us", "slug", "outcome"]
for prefix in ["ask_price", "ask_size", "bid_price", "bid_size"]:
    for i in range(25):
        TARGET_COLS.append(f"{prefix}_{i}")

TARGET_FIELDS = [
    pa.field("timestamp_us", pa.int64()),
    pa.field("slug", pa.string()),
    pa.field("outcome", pa.string()),
]
for c in TARGET_COLS[3:]:
    TARGET_FIELDS.append(pa.field(c, pa.float32()))
TARGET_SCHEMA = pa.schema(TARGET_FIELDS)


def project_batch(batch: pa.RecordBatch) -> pa.RecordBatch:
    """Project a batch onto TARGET_SCHEMA, casting types as needed."""
    arrays = []
    for col in TARGET_COLS:
        if col not in batch.schema.names:
            raise ValueError(f"source missing required col {col}")
        arr = batch.column(col)
        # Cast dictionary -> string and width-adjust numerics if needed
        target_type = TARGET_SCHEMA.field(col).type
        if arr.type != target_type:
            arr = arr.cast(target_type)
        arrays.append(arr)
    return pa.RecordBatch.from_arrays(arrays, schema=TARGET_SCHEMA)


def t(label):
    print(f"\n[{time.strftime('%H:%M:%S')}] {label}", flush=True)


def consolidate_asset(asset: str):
    out_path = OUT_DIR / f"{asset}.parquet"
    if out_path.exists():
        print(f"  {asset}: {out_path.name} exists, removing for clean write")
        out_path.unlink()

    sources_present = []
    for subdir, suffix in SOURCES:
        p = DATA / subdir.split("/")[0] / subdir.split("/")[1] / f"{asset}{suffix}"
        if p.exists():
            sources_present.append((subdir, p))

    if not sources_present:
        print(f"  {asset}: NO SOURCES, skip")
        return None

    writer = pq.ParquetWriter(str(out_path), TARGET_SCHEMA, compression="snappy")

    max_seen: dict[tuple[str, str], int] = {}
    total_in = 0
    total_kept = 0

    for subdir, src_path in sources_present:
        src_t0 = time.time()
        src_in = 0
        src_kept = 0
        pf = pq.ParquetFile(str(src_path))
        # Only read TARGET_COLS columns from source -> faster + lower mem
        for batch in pf.iter_batches(batch_size=BATCH_SIZE, columns=TARGET_COLS):
            src_in += batch.num_rows

            # Dedup keys
            slugs = batch.column("slug").to_pylist()
            outcomes = batch.column("outcome").to_pylist()  # already cast on read? not yet — we cast in project
            tss = batch.column("timestamp_us").to_pylist()

            keep_mask_py = [False] * batch.num_rows
            for i in range(batch.num_rows):
                k = (slugs[i], outcomes[i])
                ts = tss[i]
                prev = max_seen.get(k)
                if prev is None or ts > prev:
                    keep_mask_py[i] = True
                    max_seen[k] = ts

            n_kept = sum(keep_mask_py)
            if n_kept == 0:
                continue
            if n_kept == batch.num_rows:
                projected = project_batch(batch)
            else:
                mask = pa.array(keep_mask_py)
                projected = project_batch(batch.filter(mask))
            writer.write_batch(projected, row_group_size=ROW_GROUP)
            src_kept += n_kept

        total_in += src_in
        total_kept += src_kept
        print(f"  [{asset}] {subdir:<35s} in={src_in:>10,}  kept={src_kept:>10,}  skipped={src_in-src_kept:>10,}  ({time.time()-src_t0:.1f}s)")

    writer.close()

    # Verify
    pf_out = pq.ParquetFile(str(out_path))
    md_rows = pf_out.metadata.num_rows
    sz = out_path.stat().st_size / 1024 / 1024
    print(f"  [{asset}] CONSOLIDATED -> {out_path.name}")
    print(f"  [{asset}] writer kept: {total_kept:,}  parquet metadata rows: {md_rows:,}  row groups: {pf_out.metadata.num_row_groups}  size: {sz:.0f} MB")
    if md_rows != total_kept:
        print(f"  [{asset}] !!! ROW COUNT MISMATCH !!! writer={total_kept:,} parquet={md_rows:,}")
    else:
        print(f"  [{asset}] OK: counts match")
    return {"asset": asset, "total_in": total_in, "total_kept": total_kept, "md_rows": md_rows, "size_mb": sz}


def main():
    t("Consolidating L25 -> canonical/orderbook_l25/...")
    results = []
    for asset in ["sol", "eth", "btc"]:
        r = consolidate_asset(asset)
        if r:
            results.append(r)
    t("=== SUMMARY ===")
    for r in results:
        print(f"  {r['asset']:>4s}: {r['md_rows']:>11,} rows ({r['size_mb']:>6.0f} MB)  in={r['total_in']:>11,}  dedup-saved={r['total_in']-r['total_kept']:>10,}")


if __name__ == "__main__":
    main()
