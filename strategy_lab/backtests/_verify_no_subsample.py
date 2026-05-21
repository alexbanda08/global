"""
Verify fast_full_backtest sees ALL events (no 1Hz subsampling).

Pick 5 random BTC 5m slugs, count events per slug and look at dt distribution.
If we're getting ~1 event/sec → SUBSAMPLED.
If we're getting sub-second dt → FULL RESOLUTION.
"""
from pathlib import Path
import sys
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "data/v4/canonical"))
from load import load_resolutions

L25_FILES = [
    ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet",
    ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet",
]

res = load_resolutions(assets=["BTC"], timeframes=["5m"])
sample_slugs = res.sort_values("slot_start_us").iloc[::1000]["slug"].head(5).tolist()
print(f"Sample slugs: {sample_slugs}")

slug_set = pa.array(sample_slugs)

per_slug = {}
for src in L25_FILES:
    pf = pq.ParquetFile(str(src))
    for rg_idx in range(pf.metadata.num_row_groups):
        rg = pf.read_row_group(rg_idx, columns=["timestamp_us", "slug", "outcome"])
        mask = pc.is_in(rg.column("slug"), value_set=slug_set)
        if pc.sum(mask).as_py() == 0:
            continue
        rg = rg.filter(mask)
        df = rg.to_pandas()
        for slug, grp in df.groupby("slug"):
            for oc, sub in grp.groupby("outcome"):
                key = (slug, oc)
                if key not in per_slug:
                    per_slug[key] = []
                per_slug[key].extend(sub["timestamp_us"].tolist())

print("\nEvent stats per (slug, outcome):")
print(f"{'slug':<32} {'outcome':<8} {'n_events':>10} {'dt_p50_ms':>10} {'dt_p99_ms':>10} {'sub_sec%':>10}")
for (slug, oc), tss in per_slug.items():
    tss = sorted(set(tss))
    if len(tss) < 2:
        continue
    diffs_us = np.diff(tss)
    diffs_ms = diffs_us / 1000
    sub_sec_pct = (diffs_ms < 1000).sum() / len(diffs_ms) * 100
    p50 = np.percentile(diffs_ms, 50)
    p99 = np.percentile(diffs_ms, 99)
    slot_s = int(slug.rsplit("-", 1)[1])
    print(f"{slug:<32} {oc:<8} {len(tss):>10,} {p50:>10.1f} {p99:>10.1f} {sub_sec_pct:>9.1f}%")
