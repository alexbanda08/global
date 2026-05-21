"""Build FLOW features parquet from cached L25 + trades parquets.

Outputs:
  data/v4/refresh_2026_05_06/cache/{asset}_flow_features.parquet
  data/v4/refresh_2026_05_06/cache/all_flow_features.parquet  (BTC + ETH + SOL concat)

Schema of output:
  slug                   (string)
  asset                  (string)  btc/eth/sol
  outcome                (string)  Up/Down — the side these features describe
  window_start_unix      (int64)
  query_ts_us            (int64)   = (ws_unix + 120) * 1e6
  flow_*  (13 cols, see schema.FLOW_FEATURE_COLS)

Usage:
  py -X utf8 -m strategy_lab.confluence.flow.build_features --asset btc
  py -X utf8 -m strategy_lab.confluence.flow.build_features --asset all  (default)

For each asset:
  1. Load universe slugs (resolved markets) for that asset.
  2. Stream the L25 parquet by row group; group rows by (slug, outcome).
  3. For each (slug, outcome), compute features at ws+120 and emit one row.
  4. Stream trades parquet similarly, providing the trade slice.

Memory budget: row-group iteration keeps us under ~500 MB peak.
"""
from __future__ import annotations

import argparse
import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

from strategy_lab.confluence.flow.features import compute_all_for_slug_side
from strategy_lab.confluence.schema import FLOW_FEATURE_COLS

CACHE_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06" / "cache"
REFRESH_DIR = ROOT / "data" / "v4" / "refresh_2026_05_06"

OB_COLS_KEEP = (
    ["timestamp_us", "slug", "outcome"]
    + [f"bid_price_{i}" for i in range(25)]
    + [f"bid_size_{i}"  for i in range(25)]
    + [f"ask_price_{i}" for i in range(25)]
    + [f"ask_size_{i}"  for i in range(25)]
)
TR_COLS_KEEP = ["timestamp_us", "slug", "outcome", "price", "size", "side"]


def _parse_ws_unix(slug: str) -> int | None:
    parts = slug.rsplit("-", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _load_slug_universe(asset: str) -> set[str]:
    df = pd.read_csv(REFRESH_DIR / "market_resolutions_full.csv", usecols=["slug"])
    mask = df["slug"].str.startswith(f"{asset}-updown-")
    return set(df.loc[mask, "slug"].tolist())


SLUG_BATCH_SIZE = 300   # smaller batches → smaller peak RAM


def _stream_grouped_batch(
    parquet_path: Path,
    columns: list[str],
    slugs_keep: set[str],
    log_prefix: str,
) -> dict[tuple[str, str], pd.DataFrame]:
    """Read a parquet by row group, filter to slugs_keep at the ARROW level
    (avoids decoding unmatched rows to pandas), group by (slug, outcome).

    Memory pattern: the unfiltered row group lives as an Arrow Table briefly,
    is filtered to a small subset, the small subset is converted to pandas,
    and the original Table is dropped + gc.collect()ed before the next group.
    """
    pf = pq.ParquetFile(parquet_path)
    n_rg = pf.metadata.num_row_groups
    slugs_arrow = pa.array(list(slugs_keep), type=pa.string())

    chunks_by_key: dict[tuple[str, str], list[pd.DataFrame]] = {}
    for rg in range(n_rg):
        tbl = pf.read_row_group(rg, columns=columns)
        # Arrow-level filter — only keeps matching rows in memory
        mask = pc.is_in(tbl.column("slug"), value_set=slugs_arrow)
        tbl_filt = tbl.filter(mask)
        # Drop the big unfiltered Table immediately
        del tbl
        if tbl_filt.num_rows == 0:
            del tbl_filt
            continue
        df = tbl_filt.to_pandas()
        del tbl_filt
        df["outcome"] = df["outcome"].astype(str)
        for (slug, outcome), grp in df.groupby(["slug", "outcome"], sort=False):
            chunks_by_key.setdefault((slug, outcome), []).append(grp)
        del df
        # Force release of arrow-decoded buffers between row groups
        if (rg + 1) % 5 == 0:
            gc.collect()

    out: dict[tuple[str, str], pd.DataFrame] = {}
    for key, chunks in chunks_by_key.items():
        merged = pd.concat(chunks, ignore_index=True) if len(chunks) > 1 else chunks[0]
        merged = merged.sort_values("timestamp_us").reset_index(drop=True)
        out[key] = merged
    chunks_by_key.clear()
    gc.collect()
    return out


def _batches(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def build_for_asset(asset: str, slug_limit: int | None = None) -> Path:
    print(f"\n=== Building FLOW features for {asset.upper()} ===")
    slugs_all = sorted(_load_slug_universe(asset))
    if not slugs_all:
        raise SystemExit(f"no slugs found for asset={asset!r}")
    if slug_limit:
        slugs_all = slugs_all[:slug_limit]
        print(f"[{asset}] DEV MODE: limited to first {slug_limit} slugs")
    print(f"[{asset}] universe: {len(slugs_all):,} slugs (batching {SLUG_BATCH_SIZE}/pass)")

    ob_path  = CACHE_DIR / f"{asset}_orderbook_L25.parquet"
    tr_path  = CACHE_DIR / f"{asset}_trades.parquet"
    out_path = CACHE_DIR / f"{asset}_flow_features.parquet"

    if not ob_path.exists():
        raise SystemExit(f"missing {ob_path}")
    if not tr_path.exists():
        raise SystemExit(f"missing {tr_path}")

    rows_out: list[dict] = []
    t0 = time.time()
    n_batches = (len(slugs_all) + SLUG_BATCH_SIZE - 1) // SLUG_BATCH_SIZE
    for batch_idx, batch in enumerate(_batches(slugs_all, SLUG_BATCH_SIZE), start=1):
        bset = set(batch)
        bt = time.time()
        ob_groups = _stream_grouped_batch(ob_path, OB_COLS_KEEP, bset, f"{asset}/OB[{batch_idx}/{n_batches}]")
        tr_groups = _stream_grouped_batch(tr_path, TR_COLS_KEEP, bset, f"{asset}/TR[{batch_idx}/{n_batches}]")

        for (slug, outcome), ob_df in ob_groups.items():
            ws_unix = _parse_ws_unix(slug)
            if ws_unix is None:
                continue
            tr_df = tr_groups.get((slug, outcome), pd.DataFrame())
            feats = compute_all_for_slug_side(
                ob_df_slug_side=ob_df,
                trades_df_slug_side=tr_df,
                ws_unix=ws_unix,
                outcome_side=outcome,
            )
            if feats is None:
                continue
            rows_out.append({
                "slug": slug,
                "asset": asset,
                "outcome": outcome,
                "window_start_unix": ws_unix,
                "query_ts_us": (ws_unix + 120) * 1_000_000,
                **feats,
            })

        # Free batch memory before next iteration
        del ob_groups, tr_groups
        gc.collect()
        elapsed = time.time() - t0
        b_elapsed = time.time() - bt
        print(f"[{asset}] batch {batch_idx}/{n_batches}: {len(rows_out):,} rows accumulated  "
              f"(batch {b_elapsed:.1f}s / total {elapsed:.1f}s)", flush=True)

    if not rows_out:
        raise SystemExit(f"[{asset}] no features computed — check inputs")

    df_out = pd.DataFrame(rows_out)
    expected_cols = ["slug", "asset", "outcome", "window_start_unix", "query_ts_us"] + list(FLOW_FEATURE_COLS)
    df_out = df_out[expected_cols]
    df_out.to_parquet(out_path, engine="pyarrow", index=False)

    print(f"[{asset}] wrote {out_path} ({len(df_out):,} rows, {out_path.stat().st_size/1e6:.1f} MB)")
    print(f"[{asset}] feature stats:")
    print(df_out[list(FLOW_FEATURE_COLS)].describe().to_string())
    return out_path


def merge_all(assets: list[str]) -> Path:
    paths = [CACHE_DIR / f"{a}_flow_features.parquet" for a in assets]
    dfs = [pd.read_parquet(p) for p in paths if p.exists()]
    if not dfs:
        raise SystemExit("no per-asset parquets to merge")
    merged = pd.concat(dfs, ignore_index=True)
    out_path = CACHE_DIR / "all_flow_features.parquet"
    merged.to_parquet(out_path, engine="pyarrow", index=False)
    print(f"\n[merge] wrote {out_path} ({len(merged):,} rows)")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["btc", "eth", "sol", "all"])
    ap.add_argument("--slug-limit", type=int, default=None,
                    help="DEV: cap slugs per asset (smoke-test the pipeline)")
    args = ap.parse_args()
    assets = ["btc", "eth", "sol"] if args.asset == "all" else [args.asset]
    for a in assets:
        build_for_asset(a, slug_limit=args.slug_limit)
    if len(assets) > 1 and not args.slug_limit:
        merge_all(assets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
