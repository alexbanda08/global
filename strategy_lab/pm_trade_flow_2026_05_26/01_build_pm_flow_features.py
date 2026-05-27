"""PM trade flow features at fire_us — TASK 1.

For each fire in hybrid_fire_universe (5m+15m), compute PM trade flow stats
in last 30s and last 60s windows BEFORE fire_us (strict-causal).

Output: pm_flow_features_{tf}.parquet next to this script.
"""
from __future__ import annotations
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"
OUT_DIR.mkdir(exist_ok=True, parents=True)


def load_pm_trades_asset(asset_lower: str) -> pd.DataFrame:
    """Load PM trades for one asset. Returns df sorted by timestamp_us."""
    p = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset_lower}.parquet"
    df = pd.read_parquet(p, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"])
    df["notional_usd"] = df["price"] * df["size"]
    df = df.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)
    return df


def compute_flow_for_fires(fires: pd.DataFrame, pm_trades: pd.DataFrame, asset: str) -> pd.DataFrame:
    """For each fire, compute 30s and 60s flow windows. Strict-causal (ts < fire_us)."""
    # Restrict pm_trades to this asset's slugs
    asset_prefix = f"{asset.lower()}-updown-"
    pm = pm_trades[pm_trades["slug"].str.startswith(asset_prefix)].copy()
    # Group by slug for fast filter
    pm = pm.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)
    # Build slug -> array indices
    slug_to_ts = {}
    slug_to_outcome = {}
    slug_to_side = {}
    slug_to_notional = {}
    for slug, grp in pm.groupby("slug", sort=False):
        slug_to_ts[slug] = grp["timestamp_us"].values
        slug_to_outcome[slug] = grp["outcome"].values
        slug_to_side[slug] = grp["side"].values
        slug_to_notional[slug] = grp["notional_usd"].values

    fires_asset = fires[fires["asset"] == asset].reset_index(drop=True)

    n = len(fires_asset)
    pm_up_buy_30s = np.zeros(n)
    pm_dn_buy_30s = np.zeros(n)
    pm_up_buy_60s = np.zeros(n)
    pm_dn_buy_60s = np.zeros(n)
    pm_up_sell_30s = np.zeros(n)
    pm_dn_sell_30s = np.zeros(n)
    pm_trade_count_30s = np.zeros(n, dtype=int)
    pm_trade_count_60s = np.zeros(n, dtype=int)
    pm_volume_total_30s = np.zeros(n)
    pm_volume_total_60s = np.zeros(n)
    pm_up_vwap_30s = np.full(n, np.nan)
    pm_dn_vwap_30s = np.full(n, np.nan)

    for i, row in fires_asset.iterrows():
        slug = row["slug"]
        fire_us = row["fire_us"]
        if slug not in slug_to_ts:
            continue
        ts = slug_to_ts[slug]
        # Strict causal: timestamp_us < fire_us
        end_idx = np.searchsorted(ts, fire_us, side="left")
        if end_idx == 0:
            continue
        # 30s window
        t30 = fire_us - 30_000_000
        t60 = fire_us - 60_000_000
        start30 = np.searchsorted(ts, t30, side="left")
        start60 = np.searchsorted(ts, t60, side="left")

        if start30 < end_idx:
            out30 = slug_to_outcome[slug][start30:end_idx]
            sd30 = slug_to_side[slug][start30:end_idx]
            nt30 = slug_to_notional[slug][start30:end_idx]

            up_buy_mask = (out30 == "Up") & (sd30 == "buy")
            dn_buy_mask = (out30 == "Down") & (sd30 == "buy")
            up_sell_mask = (out30 == "Up") & (sd30 == "sell")
            dn_sell_mask = (out30 == "Down") & (sd30 == "sell")

            pm_up_buy_30s[i] = nt30[up_buy_mask].sum()
            pm_dn_buy_30s[i] = nt30[dn_buy_mask].sum()
            pm_up_sell_30s[i] = nt30[up_sell_mask].sum()
            pm_dn_sell_30s[i] = nt30[dn_sell_mask].sum()
            pm_trade_count_30s[i] = end_idx - start30
            pm_volume_total_30s[i] = nt30.sum()

            up_size_30 = (out30 == "Up").astype(float) * nt30
            dn_size_30 = (out30 == "Down").astype(float) * nt30
            if (out30 == "Up").any():
                up_idx = np.where(out30 == "Up")[0]
                up_n_30 = nt30[up_idx].sum()
                if up_n_30 > 0:
                    pm_up_vwap_30s[i] = (
                        pm.iloc[slug_to_ts.__contains__(slug) and 0]["price"]  # placeholder
                    )

        if start60 < end_idx:
            out60 = slug_to_outcome[slug][start60:end_idx]
            sd60 = slug_to_side[slug][start60:end_idx]
            nt60 = slug_to_notional[slug][start60:end_idx]

            up_buy60 = (out60 == "Up") & (sd60 == "buy")
            dn_buy60 = (out60 == "Down") & (sd60 == "buy")
            pm_up_buy_60s[i] = nt60[up_buy60].sum()
            pm_dn_buy_60s[i] = nt60[dn_buy60].sum()
            pm_trade_count_60s[i] = end_idx - start60
            pm_volume_total_60s[i] = nt60.sum()

    out = fires_asset[["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome", "ws_s"]].copy()
    out["pm_up_buy_30s"] = pm_up_buy_30s
    out["pm_dn_buy_30s"] = pm_dn_buy_30s
    out["pm_up_sell_30s"] = pm_up_sell_30s
    out["pm_dn_sell_30s"] = pm_dn_sell_30s
    out["pm_up_buy_60s"] = pm_up_buy_60s
    out["pm_dn_buy_60s"] = pm_dn_buy_60s
    out["pm_trade_count_30s"] = pm_trade_count_30s
    out["pm_trade_count_60s"] = pm_trade_count_60s
    out["pm_volume_total_30s"] = pm_volume_total_30s
    out["pm_volume_total_60s"] = pm_volume_total_60s

    denom30 = out["pm_up_buy_30s"] + out["pm_dn_buy_30s"]
    denom60 = out["pm_up_buy_60s"] + out["pm_dn_buy_60s"]
    out["pm_up_imbalance_30s"] = np.where(denom30 > 0, (out["pm_up_buy_30s"] - out["pm_dn_buy_30s"]) / denom30, np.nan)
    out["pm_up_imbalance_60s"] = np.where(denom60 > 0, (out["pm_up_buy_60s"] - out["pm_dn_buy_60s"]) / denom60, np.nan)
    out["pm_avg_trade_size_30s"] = np.where(out["pm_trade_count_30s"] > 0, out["pm_volume_total_30s"] / out["pm_trade_count_30s"], np.nan)

    return out


def main():
    print("Loading fire universes...", flush=True)
    fires_5m = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet")
    fires_15m = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_15m.parquet")
    print(f"  5m: {len(fires_5m):,}  15m: {len(fires_15m):,}")

    # Restrict to overlap with PM trades availability: Apr 26 → May 25
    PM_START_US = pd.Timestamp("2026-04-26 13:00:00").value // 1000  # us
    PM_END_US = pd.Timestamp("2026-05-25 19:00:00").value // 1000

    for fname, fires in [("5m", fires_5m), ("15m", fires_15m)]:
        fires_in_window = fires[(fires["fire_us"] >= PM_START_US) & (fires["fire_us"] < PM_END_US)].copy()
        print(f"{fname}: {len(fires_in_window):,} in window", flush=True)

        results = []
        for asset in ["BTC", "ETH", "SOL"]:
            print(f"  loading PM trades {asset}...", flush=True)
            pm = load_pm_trades_asset(asset.lower())
            print(f"    pm rows: {len(pm):,}", flush=True)
            print(f"  computing features for {asset}...", flush=True)
            r = compute_flow_for_fires(fires_in_window, pm, asset)
            print(f"    -> {len(r):,} rows", flush=True)
            results.append(r)
            del pm

        out = pd.concat(results, ignore_index=True)
        out_path = OUT_DIR / f"pm_flow_features_{fname}.parquet"
        out.to_parquet(out_path, index=False)
        print(f"WROTE {out_path}  ({len(out):,} rows)", flush=True)


if __name__ == "__main__":
    main()
