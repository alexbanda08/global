"""
Local data-fidelity probe.

Checks:
  1. Schema of raw orderbook L25 parquets: column count, naming convention,
     does it match VPS3's 109-flat layout?
  2. Has both timestamp_us AND local_timestamp_us (=> can measure latency)?
  3. Event-based (one row per book change) or downsampled?
  4. Row counts + dt distribution for a sample BTC 5m slug.
  5. Same for trades_polymarket.

Output: prints to stdout, no file writes.
"""
from __future__ import annotations
import pyarrow.parquet as pq
import pandas as pd
import numpy as np
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")

RAW_BOOK_SOURCES = [
    ROOT / "data/v4/refresh_2026_05_16/cache_pre/btc_orderbook_L25_pre_apr22.parquet",
    ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet",
    ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet",
]

TRADES_SOURCE = ROOT / "data/v4/canonical/trades_polymarket/btc.parquet"


def schema_report(parquet_path: Path):
    if not parquet_path.exists():
        print(f"  MISSING: {parquet_path}")
        return None
    pf = pq.ParquetFile(str(parquet_path))
    schema = pf.schema_arrow
    cols = [f.name for f in schema]
    print(f"\n=== {parquet_path.name}")
    print(f"  rows total: {pf.metadata.num_rows:,}")
    print(f"  cols total: {len(cols)}")
    print(f"  row groups: {pf.metadata.num_row_groups}")
    # Field categorization
    ts_cols = [c for c in cols if "timestamp" in c.lower() or "_us" in c or c == "ts"]
    id_cols = [c for c in cols if c in ("slug", "outcome", "outcome_id",
                                          "market_id", "asset_id", "exchange",
                                          "source", "ticker", "timeframe")]
    bid_p = [c for c in cols if c.startswith("bid_price_")]
    bid_s = [c for c in cols if c.startswith("bid_size_")]
    ask_p = [c for c in cols if c.startswith("ask_price_")]
    ask_s = [c for c in cols if c.startswith("ask_size_")]
    other = [c for c in cols if c not in (ts_cols + id_cols + bid_p + bid_s + ask_p + ask_s)]
    print(f"  ts cols: {ts_cols}")
    print(f"  id cols: {id_cols}")
    print(f"  bid_price levels: {len(bid_p)}  (0..{max([int(c.split('_')[-1]) for c in bid_p], default=-1)})")
    print(f"  bid_size  levels: {len(bid_s)}")
    print(f"  ask_price levels: {len(ask_p)}")
    print(f"  ask_size  levels: {len(ask_s)}")
    print(f"  has local_timestamp_us: {'local_timestamp_us' in cols}")
    print(f"  has exchange ts vs local ts: {('timestamp_us' in cols) and ('local_timestamp_us' in cols)}")
    if other:
        print(f"  other cols: {other[:10]}{' ...' if len(other) > 10 else ''}")
    return cols


def slug_density_report(parquet_path: Path, sample_slugs: list[str] | None = None):
    """For one sample slug per source, count rows + dt distribution."""
    if not parquet_path.exists():
        return
    print(f"\n=== density: {parquet_path.name}")
    pf = pq.ParquetFile(str(parquet_path))
    # Get a sample of distinct slugs from first row group
    rg0 = pf.read_row_group(0, columns=["slug", "timestamp_us", "outcome"])
    df_rg = rg0.to_pandas()
    slugs_seen = df_rg["slug"].value_counts().head(5).index.tolist()
    if not slugs_seen:
        print("  no slugs in first row group")
        return
    print(f"  top 5 slugs in first row group: {slugs_seen}")

    # Pick the slug with most rows
    target_slug = slugs_seen[0]
    n_rows = (df_rg["slug"] == target_slug).sum()
    print(f"  picked slug: {target_slug}  ({n_rows} rows in first row group)")

    # Read ALL rows for this slug from all row groups (filtered)
    import pyarrow as pa
    import pyarrow.compute as pc
    target_arr = pa.array([target_slug])

    all_dfs = []
    for rg_idx in range(pf.metadata.num_row_groups):
        rg = pf.read_row_group(rg_idx, columns=["slug", "timestamp_us", "outcome",
                                                  "bid_price_0", "bid_size_0",
                                                  "ask_price_0", "ask_size_0"])
        mask = pc.is_in(rg.column("slug"), value_set=target_arr)
        if pc.sum(mask).as_py() == 0:
            continue
        rg = rg.filter(mask)
        all_dfs.append(rg.to_pandas())

    if not all_dfs:
        print("  no data")
        return

    df = pd.concat(all_dfs, ignore_index=True).sort_values("timestamp_us")
    print(f"\n  --- full-window stats for slug {target_slug} ---")
    for outcome in df["outcome"].unique():
        sub = df[df["outcome"] == outcome].copy()
        if len(sub) < 2:
            continue
        sub["dt_us"] = sub["timestamp_us"].diff()
        dt_ms = sub["dt_us"].dropna() / 1000  # us -> ms
        t0 = int(sub["timestamp_us"].min())
        t1 = int(sub["timestamp_us"].max())
        span_s = (t1 - t0) / 1_000_000
        print(f"\n  outcome={outcome}  rows={len(sub):,}  span={span_s:.0f}s")
        print(f"    rate: {len(sub)/max(span_s,1):.1f} snapshots/s")
        print(f"    dt_ms: p10={dt_ms.quantile(0.10):.1f}  p25={dt_ms.quantile(0.25):.1f}  "
              f"p50={dt_ms.median():.1f}  p75={dt_ms.quantile(0.75):.1f}  "
              f"p90={dt_ms.quantile(0.90):.1f}  p99={dt_ms.quantile(0.99):.1f}  "
              f"max={dt_ms.max():.0f}")
        # How many sub-second updates?
        n_sub_1s = (dt_ms < 1000).sum()
        pct_sub_1s = n_sub_1s / len(dt_ms) * 100
        print(f"    sub-second updates: {n_sub_1s}/{len(dt_ms)} = {pct_sub_1s:.1f}%")
        # Best bid/ask change rate
        bb_chg = (sub["bid_price_0"].diff().abs() > 0).sum()
        ba_chg = (sub["ask_price_0"].diff().abs() > 0).sum()
        print(f"    best_bid changes: {bb_chg}/{len(sub)} = {bb_chg/len(sub)*100:.1f}%")
        print(f"    best_ask changes: {ba_chg}/{len(sub)} = {ba_chg/len(sub)*100:.1f}%")


def main():
    print("=" * 80)
    print("LOCAL DATA FIDELITY PROBE")
    print("=" * 80)

    print("\n>>> ORDERBOOK L25 PARQUETS")
    for src in RAW_BOOK_SOURCES:
        cols = schema_report(src)

    print("\n>>> TRADES")
    schema_report(TRADES_SOURCE)

    print("\n>>> DENSITY ANALYSIS (one sample slug per source)")
    for src in RAW_BOOK_SOURCES:
        if src.exists():
            slug_density_report(src)
            break  # one is enough for now

    # Also check trades density on a sample slug
    if TRADES_SOURCE.exists():
        print("\n>>> TRADES density (first 5 slugs)")
        df_tr = pd.read_parquet(TRADES_SOURCE)
        print(f"  total trades rows: {len(df_tr):,}")
        print(f"  cols: {list(df_tr.columns)}")
        if "slug" in df_tr.columns and "timestamp_us" in df_tr.columns:
            top_slugs = df_tr["slug"].value_counts().head(5)
            print(f"  top 5 slugs:")
            for s, n in top_slugs.items():
                sub = df_tr[df_tr["slug"] == s].sort_values("timestamp_us")
                t0 = int(sub["timestamp_us"].min())
                t1 = int(sub["timestamp_us"].max())
                span_s = (t1 - t0) / 1_000_000
                print(f"    {s}: {n} trades, span {span_s:.0f}s, rate {n/max(span_s,1):.2f}/s")


if __name__ == "__main__":
    main()
