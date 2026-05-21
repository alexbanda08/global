"""Build TRIGGER features parquet.

Output:
  data/v4/refresh_2026_05_06/cache/all_trigger_features.parquet

Schema (one row per (slug, asset, outcome, window_start_unix)):
  slug                            (string)
  asset                           (string) btc/eth/sol
  outcome                         (string) 'Up' / 'Down'
  window_start_unix               (int64)
  query_ts_us                     (int64) = (ws_unix + 120) * 1e6
  trig_liq_magnet_active          (bool)
  trig_liq_magnet_distance_bps    (float, NaN when not active)
  trig_fvg_active                 (bool)
  trig_fvg_side                   (string: 'up' / 'down' / None)
  trig_ofi_30s                    (float, [-1, +1])
  trigger_active                  (bool — composite)

Strict no-lookahead: every feature at query_ts = ws+120 uses ONLY data with
ts <= query_ts.

trigger_active = True iff ALL of:
  - liq_magnet_active
  - |ofi_30s| >= 0.50 AND sign aligns with held outcome (positive<->Up)
  (FVG dropped — too saturated; strict AND-of-2 requirement)

Build pattern mirrors flow/build_features.py — Arrow-level slug filter on the
trades parquet, batched per asset to keep peak RAM bounded.

Usage:
  py -X utf8 -m strategy_lab.confluence.trigger.build_trigger --asset all
  py -X utf8 -m strategy_lab.confluence.trigger.build_trigger --smoke
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

from strategy_lab.confluence.schema import TRIGGER_FEATURE_COLS
from strategy_lab.confluence.trigger.fvg import compute_fvg
from strategy_lab.confluence.trigger.liq_magnet import (
    LIQ_RADIUS_USD,
    LOOKBACK_S as LIQ_LOOKBACK_S,
    compute_liq_magnet,
    filter_liq_window,
)
from strategy_lab.confluence.trigger.ofi import compute_ofi_30s

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_06"
CACHE_DIR = REFRESH_NEW / "cache"
LIQ_CSV = REFRESH_NEW / "hl_liquidations_btc_eth_sol.csv"
KLINES_CSV = REFRESH_NEW / "klines_full.csv"
OUT_PARQUET = CACHE_DIR / "all_trigger_features.parquet"

ASSET_BINANCE = {
    "btc": "BINANCE_SPOT_BTC_USDT",
    "eth": "BINANCE_SPOT_ETH_USDT",
    "sol": "BINANCE_SPOT_SOL_USDT",
}
ASSET_OKX = {
    "btc": "OKX_SPOT_BTC_USDT",
    "eth": "OKX_SPOT_ETH_USDT",
    "sol": "OKX_SPOT_SOL_USDT",
}

# Asset-coin mapping for HL liquidations file (coin column uses upper-case)
ASSET_TO_COIN = {"btc": "BTC", "eth": "ETH", "sol": "SOL"}

SLUG_BATCH_SIZE = 300
TR_COLS_KEEP = ["timestamp_us", "slug", "outcome", "size", "side"]

# Composite-trigger threshold (tightened: AND-of-2, OFI raised to 0.50)
OFI_TRIGGER_ABS = 0.50


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    """Mirror of extended_backtest_with_robustness.load_universe()."""
    df = pd.read_csv(REFRESH_NEW / "market_resolutions_full.csv")
    if "window_start_unix" not in df.columns or "outcome_up" not in df.columns:
        parts = df["slug"].str.split("-", n=3, expand=True)
        df["asset"] = parts[0]
        df["timeframe"] = parts[2]
        df["window_start_unix"] = pd.to_numeric(parts[3], errors="coerce")
        df["outcome_up"] = (df["outcome"].str.lower() == "up").astype(int)
    df = df.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    df["asset"] = df["slug"].str.extract(r"^(btc|eth|sol)-updown-")[0]
    df = df.dropna(subset=["asset"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    df["outcome_up"] = df["outcome_up"].astype(int)
    return df


def load_klines_1m_per_asset() -> dict[str, pd.DataFrame]:
    """Return per-asset 1MIN klines (ts_s, price_high, price_low, price_close).
    Binance preferred, OKX fallback (mirrors extended_backtest.load_klines).
    """
    df = pd.read_csv(
        KLINES_CSV,
        usecols=[
            "symbol_id",
            "period_id",
            "time_period_start_us",
            "price_high",
            "price_low",
            "price_close",
        ],
    )
    df = df[df["period_id"] == "1MIN"].copy()
    df["ts_s"] = (df["time_period_start_us"] // 1_000_000).astype("int64")
    out: dict[str, pd.DataFrame] = {}
    for asset in ("btc", "eth", "sol"):
        bin_sym = ASSET_BINANCE[asset]
        okx_sym = ASSET_OKX[asset]
        bin_sub = df[df.symbol_id == bin_sym][
            ["ts_s", "price_high", "price_low", "price_close"]
        ].copy()
        okx_sub = df[df.symbol_id == okx_sym][
            ["ts_s", "price_high", "price_low", "price_close"]
        ].copy()
        bin_sub["src"] = "binance"
        okx_sub["src"] = "okx"
        comb = pd.concat([bin_sub, okx_sub], ignore_index=True)
        comb = comb.sort_values(["ts_s", "src"]).drop_duplicates("ts_s", keep="first")
        comb = comb.sort_values("ts_s").reset_index(drop=True)
        out[asset] = comb[["ts_s", "price_high", "price_low", "price_close"]]
        print(
            f"[klines/{asset}] {len(out[asset]):,} 1m bars "
            f"range {pd.to_datetime(out[asset].ts_s.min(), unit='s')} -> "
            f"{pd.to_datetime(out[asset].ts_s.max(), unit='s')}",
            flush=True,
        )
    return out


def load_liquidations_per_asset(chunksize: int = 500_000) -> dict[str, pd.DataFrame]:
    """Stream the 245 MB HL liquidations CSV in chunks; keep only liquidation
    events (dir starts with 'Liquidated'); split per asset.

    Returns {'btc': DataFrame[time_exchange_us, price] sorted asc, 'eth': ..., 'sol': ...}.
    """
    print(f"[liq] streaming {LIQ_CSV.name}...", flush=True)
    # The hyperliquid_liquidations_v2 table on VPS3 is filtered to liquidations
    # only AT INSERTION TIME by both the s3-fills backfill collector
    # (`fill.liquidation` sub-object check) and the live HLP-userEvents WS
    # collector (`dir LIKE 'Liquid%' OR liquidation key present`).
    # Post-Feb 2026 the dir field is sometimes HLP-vault perspective
    # ('Open Long' / 'Close Short') because HL changed the WS payload format,
    # but the row IS still a liquidation — the trader is on the OPPOSITE side
    # of the dir label.
    # → accept EVERY row in the file (no dir filter).
    keep_cols = ["coin", "price", "time_exchange_us"]
    chunks: dict[str, list[pd.DataFrame]] = {"btc": [], "eth": [], "sol": []}
    n_total = 0
    n_kept = 0
    for chunk in pd.read_csv(LIQ_CSV, usecols=keep_cols, chunksize=chunksize):
        n_total += len(chunk)
        chunk = chunk[["coin", "price", "time_exchange_us"]]
        if chunk.empty:
            continue
        for asset, coin_label in ASSET_TO_COIN.items():
            sub = chunk[chunk["coin"] == coin_label]
            if not sub.empty:
                chunks[asset].append(sub[["time_exchange_us", "price"]].copy())
        n_kept += len(chunk)

    out: dict[str, pd.DataFrame] = {}
    for asset, parts in chunks.items():
        if not parts:
            out[asset] = pd.DataFrame(columns=["time_exchange_us", "price"])
            continue
        df = pd.concat(parts, ignore_index=True)
        df["time_exchange_us"] = df["time_exchange_us"].astype("int64")
        df["price"] = df["price"].astype("float64")
        df = df.sort_values("time_exchange_us").reset_index(drop=True)
        out[asset] = df
        print(
            f"[liq/{asset}] {len(df):,} liquidations  "
            f"range {pd.to_datetime(df.time_exchange_us.min(), unit='us')} -> "
            f"{pd.to_datetime(df.time_exchange_us.max(), unit='us')}",
            flush=True,
        )
    print(f"[liq] scanned {n_total:,} rows, kept {n_kept:,} liquidations", flush=True)
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_ws_unix(slug: str) -> int | None:
    parts = slug.rsplit("-", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _close_asof(k1m: pd.DataFrame, query_ts_s: int) -> float:
    """End-time-indexed asof: returns price_close of the most recent 1MIN bar
    whose CLOSE TIME (= ts_s + 60) is <= query_ts_s. Matches the strict
    asof in extended_backtest_with_robustness.asof().
    """
    if k1m is None or k1m.empty:
        return float("nan")
    end_s = (k1m["ts_s"].astype("int64") + 60).values
    idx = int(np.searchsorted(end_s, int(query_ts_s), side="right")) - 1
    if idx < 0:
        return float("nan")
    return float(k1m["price_close"].iloc[idx])


def _slug_window_liqs(liq_arr_ts: np.ndarray, liq_arr_px: np.ndarray, query_ts_us: int) -> np.ndarray:
    """Return liquidation prices within (query_ts - 60min, query_ts]."""
    if liq_arr_ts.size == 0:
        return np.empty(0, dtype=float)
    lo_us = query_ts_us - LIQ_LOOKBACK_S * 1_000_000
    # Use binary search since liq_arr_ts is sorted ascending
    lo_idx = int(np.searchsorted(liq_arr_ts, lo_us, side="right"))
    hi_idx = int(np.searchsorted(liq_arr_ts, query_ts_us, side="right"))
    if lo_idx >= hi_idx:
        return np.empty(0, dtype=float)
    return liq_arr_px[lo_idx:hi_idx]


def _kline_window(k1m: pd.DataFrame, query_ts_s: int, lookback_min: int = 30) -> pd.DataFrame:
    """Slice 1m klines for [query_ts - lookback_min*60, query_ts]. Used by FVG."""
    if k1m is None or k1m.empty:
        return k1m
    lo_s = int(query_ts_s) - lookback_min * 60
    ts_s_arr = k1m["ts_s"].values
    mask = (ts_s_arr >= lo_s) & (ts_s_arr <= int(query_ts_s))
    return k1m.loc[mask].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Trades grouping (Arrow-level filter; mirror flow/build_features pattern)
# ---------------------------------------------------------------------------

def _stream_trades_grouped_batch(
    parquet_path: Path,
    slugs_keep: set[str],
) -> dict[tuple[str, str], pd.DataFrame]:
    """Read trades parquet by row group, keep only rows whose slug is in
    `slugs_keep`, group by (slug, outcome). Each group is sorted by timestamp_us."""
    pf = pq.ParquetFile(parquet_path)
    n_rg = pf.metadata.num_row_groups
    slugs_arrow = pa.array(list(slugs_keep), type=pa.string())

    chunks_by_key: dict[tuple[str, str], list[pd.DataFrame]] = {}
    for rg in range(n_rg):
        tbl = pf.read_row_group(rg, columns=TR_COLS_KEEP)
        mask = pc.is_in(tbl.column("slug"), value_set=slugs_arrow)
        tbl_filt = tbl.filter(mask)
        del tbl
        if tbl_filt.num_rows == 0:
            del tbl_filt
            continue
        df = tbl_filt.to_pandas()
        del tbl_filt
        df["outcome"] = df["outcome"].astype(str)
        df["side"] = df["side"].astype(str)
        for (slug, outcome), grp in df.groupby(["slug", "outcome"], sort=False):
            chunks_by_key.setdefault((slug, outcome), []).append(grp)
        del df
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


# ---------------------------------------------------------------------------
# Per-row computation
# ---------------------------------------------------------------------------

def _compute_row(
    slug: str,
    asset: str,
    outcome: str,
    ws_unix: int,
    k1m: pd.DataFrame,
    liq_ts_arr: np.ndarray,
    liq_px_arr: np.ndarray,
    trades_df_side: pd.DataFrame,
) -> dict:
    """Compute the trigger feature row for one (slug, asset, outcome, ws_unix)."""
    query_ts_s = int(ws_unix) + 120
    query_ts_us = query_ts_s * 1_000_000

    # Liquidation magnet (vs Binance close at query_ts)
    current_px = _close_asof(k1m, query_ts_s)
    liq_window_px = _slug_window_liqs(liq_ts_arr, liq_px_arr, query_ts_us)
    liq_active, liq_dist_bps = compute_liq_magnet(liq_window_px, current_px, asset)

    # FVG (3-bar pattern over 30m of 1m klines)
    fvg_window = _kline_window(k1m, query_ts_s, lookback_min=30)
    fvg_active, fvg_side = compute_fvg(fvg_window, query_ts_s, lookback_min=30)

    # OFI over 30s on the held side's trade stream
    ofi = compute_ofi_30s(trades_df_side, query_ts_us)

    # Composite trigger_active — strict AND-of-2:
    #   liq_magnet_active AND (|ofi_30s| >= 0.50 AND ofi sign aligned with held side)
    # FVG dropped (saturated at 96%, adds no information).
    held_up = outcome.lower() == "up"
    ofi_aligned = abs(ofi) >= OFI_TRIGGER_ABS and (
        (ofi > 0 and held_up) or (ofi < 0 and not held_up)
    )
    trigger_active = bool(liq_active and ofi_aligned)

    return {
        "slug": slug,
        "asset": asset,
        "outcome": outcome,
        "window_start_unix": int(ws_unix),
        "query_ts_us": query_ts_us,
        "trig_liq_magnet_active": bool(liq_active),
        "trig_liq_magnet_distance_bps": float(liq_dist_bps) if liq_active else float("nan"),
        "trig_fvg_active": bool(fvg_active),
        "trig_fvg_side": fvg_side if fvg_active else None,
        "trig_ofi_30s": float(ofi),
        "trigger_active": trigger_active,
    }


def _batches(items: list, n: int):
    for i in range(0, len(items), n):
        yield items[i : i + n]


# ---------------------------------------------------------------------------
# Main per-asset build
# ---------------------------------------------------------------------------

def build_for_asset(
    asset: str,
    universe: pd.DataFrame,
    klines: dict[str, pd.DataFrame],
    liqs: dict[str, pd.DataFrame],
    slug_limit: int | None = None,
) -> pd.DataFrame:
    print(f"\n=== Building TRIGGER features for {asset.upper()} ===", flush=True)
    uni_a = universe[universe["asset"] == asset].copy()
    slugs_all = sorted(uni_a["slug"].unique().tolist())
    if not slugs_all:
        print(f"[{asset}] no slugs found, skipping", flush=True)
        return pd.DataFrame()
    if slug_limit:
        slugs_all = slugs_all[:slug_limit]
        print(f"[{asset}] SMOKE: limited to first {slug_limit} slugs", flush=True)
    print(
        f"[{asset}] universe: {len(slugs_all):,} slugs (batching {SLUG_BATCH_SIZE}/pass)",
        flush=True,
    )

    tr_path = CACHE_DIR / f"{asset}_trades.parquet"
    if not tr_path.exists():
        raise SystemExit(f"missing {tr_path}")

    k1m = klines[asset]
    liq_df = liqs[asset]
    liq_ts_arr = liq_df["time_exchange_us"].values.astype("int64") if not liq_df.empty else np.empty(0, dtype="int64")
    liq_px_arr = liq_df["price"].values.astype("float64") if not liq_df.empty else np.empty(0, dtype="float64")

    rows_out: list[dict] = []
    t0 = time.time()
    n_batches = (len(slugs_all) + SLUG_BATCH_SIZE - 1) // SLUG_BATCH_SIZE
    for batch_idx, batch in enumerate(_batches(slugs_all, SLUG_BATCH_SIZE), start=1):
        bset = set(batch)
        bt = time.time()
        tr_groups = _stream_trades_grouped_batch(tr_path, bset)

        # Universe rows for this batch (one per (slug, outcome))
        uni_b = uni_a[uni_a["slug"].isin(bset)]
        # Each market has Up + Down resolutions in market_resolutions_full,
        # but the held side is whichever outcome the trade prints clustered
        # around. We emit one row per (slug, outcome) the trades parquet has.
        keys_seen: set[tuple[str, str]] = set()
        for (slug, outcome) in tr_groups.keys():
            ws_unix = _parse_ws_unix(slug)
            if ws_unix is None:
                continue
            keys_seen.add((slug, outcome))
            row = _compute_row(
                slug=slug,
                asset=asset,
                outcome=outcome,
                ws_unix=ws_unix,
                k1m=k1m,
                liq_ts_arr=liq_ts_arr,
                liq_px_arr=liq_px_arr,
                trades_df_side=tr_groups[(slug, outcome)],
            )
            rows_out.append(row)

        # For (slug, outcome) pairs in universe but with NO trades: still
        # emit a row (OFI=0, FVG/liq still computable). This keeps the
        # parquet symmetric with FLOW.
        for _, urow in uni_b.iterrows():
            slug = urow["slug"]
            outcome = "Up" if urow["outcome_up"] == 1 else "Down"
            if (slug, outcome) in keys_seen:
                continue
            ws_unix = int(urow["window_start_unix"])
            row = _compute_row(
                slug=slug,
                asset=asset,
                outcome=outcome,
                ws_unix=ws_unix,
                k1m=k1m,
                liq_ts_arr=liq_ts_arr,
                liq_px_arr=liq_px_arr,
                trades_df_side=pd.DataFrame(columns=TR_COLS_KEEP),
            )
            rows_out.append(row)

        del tr_groups
        gc.collect()
        elapsed = time.time() - t0
        b_elapsed = time.time() - bt
        print(
            f"[{asset}] batch {batch_idx}/{n_batches}: {len(rows_out):,} rows "
            f"(batch {b_elapsed:.1f}s / total {elapsed:.1f}s)",
            flush=True,
        )

    if not rows_out:
        print(f"[{asset}] no rows produced", flush=True)
        return pd.DataFrame()

    df_out = pd.DataFrame(rows_out)
    expected_cols = [
        "slug",
        "asset",
        "outcome",
        "window_start_unix",
        "query_ts_us",
    ] + list(TRIGGER_FEATURE_COLS)
    df_out = df_out[expected_cols]
    return df_out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="all", choices=["btc", "eth", "sol", "all"])
    ap.add_argument(
        "--smoke",
        action="store_true",
        help="DEV: cap to first 100 slugs per asset for a fast pipeline check",
    )
    ap.add_argument(
        "--slug-limit",
        type=int,
        default=None,
        help="DEV: cap slugs per asset (overrides --smoke if both set)",
    )
    args = ap.parse_args()

    slug_limit = args.slug_limit
    if args.smoke and slug_limit is None:
        slug_limit = 100

    assets = ["btc", "eth", "sol"] if args.asset == "all" else [args.asset]

    universe = load_universe()
    universe = universe[universe["asset"].isin(assets)]
    print(f"[universe] {len(universe):,} rows for assets={assets}", flush=True)

    klines = load_klines_1m_per_asset()
    liqs = load_liquidations_per_asset()

    parts: list[pd.DataFrame] = []
    for a in assets:
        df_a = build_for_asset(
            asset=a,
            universe=universe,
            klines=klines,
            liqs=liqs,
            slug_limit=slug_limit,
        )
        if not df_a.empty:
            parts.append(df_a)

    if not parts:
        raise SystemExit("no rows built")

    merged = pd.concat(parts, ignore_index=True)
    out_path = OUT_PARQUET
    if slug_limit:
        out_path = CACHE_DIR / f"all_trigger_features.smoke{slug_limit}.parquet"
    merged.to_parquet(out_path, engine="pyarrow", index=False)

    print(
        f"\n[merge] wrote {out_path} ({len(merged):,} rows, "
        f"{out_path.stat().st_size / 1e6:.1f} MB)",
        flush=True,
    )
    print("[stats] head:\n" + merged.head(3).to_string(), flush=True)
    print("\n[stats] feature describe:", flush=True)
    desc_cols = [
        "trig_liq_magnet_active",
        "trig_liq_magnet_distance_bps",
        "trig_fvg_active",
        "trig_ofi_30s",
        "trigger_active",
    ]
    print(merged[desc_cols].describe(include="all").to_string(), flush=True)
    print(
        f"\n[stats] trigger_active rate: {merged['trigger_active'].mean():.4f}  "
        f"liq_magnet rate: {merged['trig_liq_magnet_active'].mean():.4f}  "
        f"fvg rate: {merged['trig_fvg_active'].mean():.4f}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
