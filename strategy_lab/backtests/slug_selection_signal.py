"""
Slug-selection signal — what predicts a wallet engaging a slug?

For each wallet:
  - Compare ENGAGED slugs vs UNENGAGED slugs in same window
  - Features per slug: opening sum_bids, opening sum_asks, opening spread,
    initial book depth, time of day, prior-slot direction
  - Identify which feature(s) discriminate

Output: per-wallet feature comparison + ROC-like analysis
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "strategy_lab" / "backtests"
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
from load import load_resolutions

L25_BASE = ROOT / "data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet"
L25_DELTA = ROOT / "data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet"
L25_PRE = ROOT / "data/v4/refresh_2026_05_16/cache_pre/btc_orderbook_L25_pre_apr22.parquet"


def get_open_book_per_slug(asset: str = "btc") -> pd.DataFrame:
    """Get earliest book snapshot per (slug, outcome) for asset."""
    parts = []
    for src in [L25_PRE, L25_BASE, L25_DELTA]:
        if not src.exists():
            continue
        pf = pq.ParquetFile(str(src))
        for rg_idx in range(pf.metadata.num_row_groups):
            try:
                rg = pf.read_row_group(rg_idx, columns=[
                    "timestamp_us", "slug", "outcome",
                    "bid_price_0", "bid_size_0", "ask_price_0", "ask_size_0",
                ])
            except Exception:
                continue
            df = rg.to_pandas()
            df = df[df["slug"].str.startswith(f"{asset}-updown-")]
            parts.append(df)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    # Earliest snapshot per (slug, outcome)
    df = df.sort_values("timestamp_us").drop_duplicates(["slug", "outcome"], keep="first")
    # Spread (sum_bids, sum_asks)
    return df


def per_slug_features(open_books: pd.DataFrame) -> pd.DataFrame:
    """Compute features per slug from opening books on Up + Down."""
    if open_books.empty:
        return pd.DataFrame()
    # Pivot to wide: slug -> {up_bid, up_ask, dn_bid, dn_ask, ...}
    pivot = open_books.pivot_table(
        index="slug",
        columns="outcome",
        values=["bid_price_0", "ask_price_0", "bid_size_0", "ask_size_0", "timestamp_us"],
        aggfunc="first",
    )
    pivot.columns = [f"{a}_{b.lower()}" for a, b in pivot.columns]
    pivot = pivot.reset_index()

    pivot["sum_bids"] = pivot["bid_price_0_up"] + pivot["bid_price_0_down"]
    pivot["sum_asks"] = pivot["ask_price_0_up"] + pivot["ask_price_0_down"]
    pivot["spread_up"] = pivot["ask_price_0_up"] - pivot["bid_price_0_up"]
    pivot["spread_dn"] = pivot["ask_price_0_down"] - pivot["bid_price_0_down"]
    pivot["mid_up"] = (pivot["ask_price_0_up"] + pivot["bid_price_0_up"]) / 2
    pivot["mid_dn"] = (pivot["ask_price_0_down"] + pivot["bid_price_0_down"]) / 2
    pivot["mid_diff"] = pivot["mid_up"] - pivot["mid_dn"]  # direction
    pivot["depth_up"] = pivot["bid_size_0_up"] + pivot["ask_size_0_up"]
    pivot["depth_dn"] = pivot["bid_size_0_down"] + pivot["ask_size_0_down"]

    # Slot timing from slug suffix
    pivot["slot_start_s"] = pivot["slug"].str.rsplit("-", n=1).str[-1].astype("int64")
    pivot["hour_utc"] = ((pivot["slot_start_s"] // 3600) % 24).astype(int)
    pivot["tf"] = pivot["slug"].str.extract(r"-(\d+m)-")[0]
    return pivot


def main():
    wallets = ["0x04b6d7e9", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3", "0xce25e214"]
    profile = pd.read_csv(OUT_DIR / "_wallet_profile_per_slug_agg.csv")
    profile = profile[profile["asset_sym"] == "BTC"]

    print("Computing open books for all BTC slugs...")
    open_books = get_open_book_per_slug("btc")
    features = per_slug_features(open_books)
    print(f"  features computed for {len(features)} unique BTC slugs")

    out_rows = []
    for w in wallets:
        engaged = set(profile[profile["wallet"] == w]["slug"].unique())
        if not engaged:
            continue

        # Restrict features to same time window as wallet was active
        wmin = profile[profile["wallet"] == w]["slot_start_s"].min()
        wmax = profile[profile["wallet"] == w]["slot_start_s"].max()
        in_window = features[
            (features["slot_start_s"] >= wmin) & (features["slot_start_s"] <= wmax)
        ].copy()

        in_window["engaged"] = in_window["slug"].isin(engaged)
        n_total = len(in_window)
        n_eng = in_window["engaged"].sum()
        engagement_rate = n_eng / max(n_total, 1) * 100
        print(f"\n{w}: window=[{wmin},{wmax}], engaged {n_eng}/{n_total} slugs ({engagement_rate:.1f}%)")

        # Feature comparison: engaged vs unengaged
        feat_cols = ["sum_bids", "sum_asks", "spread_up", "spread_dn", "mid_diff",
                     "depth_up", "depth_dn", "hour_utc"]
        for fc in feat_cols:
            if fc not in in_window.columns:
                continue
            eng = in_window[in_window["engaged"]][fc].dropna()
            nen = in_window[~in_window["engaged"]][fc].dropna()
            if len(eng) < 5 or len(nen) < 5:
                continue
            eng_mean = float(eng.mean())
            nen_mean = float(nen.mean())
            eng_med = float(eng.median())
            nen_med = float(nen.median())
            # T-stat-like: (m_eng - m_nen) / pooled_std
            pooled = ((eng.std()**2 / len(eng)) + (nen.std()**2 / len(nen))) ** 0.5
            if pooled > 0:
                z = (eng_mean - nen_mean) / pooled
            else:
                z = 0
            out_rows.append({
                "wallet": w, "feature": fc,
                "engagement_rate_pct": engagement_rate,
                "n_engaged": int(n_eng),
                "n_unengaged": int(n_total - n_eng),
                "eng_mean": round(eng_mean, 4),
                "nen_mean": round(nen_mean, 4),
                "eng_median": round(eng_med, 4),
                "nen_median": round(nen_med, 4),
                "diff_mean": round(eng_mean - nen_mean, 4),
                "z_score": round(z, 2),
            })

    df_out = pd.DataFrame(out_rows)
    df_out.to_csv(OUT_DIR / "_slug_selection_features.csv", index=False)

    # Print summary — strongest discriminators per wallet
    print()
    print("=" * 90)
    print("SLUG-SELECTION DISCRIMINATORS (sorted by |z| within wallet)")
    print("=" * 90)
    for w in df_out["wallet"].unique():
        sub = df_out[df_out["wallet"] == w].copy()
        sub["abs_z"] = sub["z_score"].abs()
        sub = sub.sort_values("abs_z", ascending=False)
        print(f"\n{w}:")
        cols = ["feature", "z_score", "diff_mean", "eng_mean", "nen_mean"]
        print(sub[cols].head(8).to_string(index=False))


if __name__ == "__main__":
    main()
