"""Build PM trade flow features for 15m only — write per-asset to save memory."""
from __future__ import annotations
import sys
import gc
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"
OUT_DIR.mkdir(exist_ok=True, parents=True)


def load_pm_trades_asset(asset_lower: str) -> pd.DataFrame:
    p = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset_lower}.parquet"
    # only columns we need - reduces memory significantly
    df = pd.read_parquet(p, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"])
    df["notional_usd"] = (df["price"] * df["size"]).astype("float32")
    df = df.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)
    return df


def compute_flow_for_fires_optimized(fires_asset: pd.DataFrame, pm: pd.DataFrame) -> pd.DataFrame:
    """Vectorized over slugs."""
    n = len(fires_asset)
    pm_up_buy_30s = np.zeros(n, dtype=np.float32)
    pm_dn_buy_30s = np.zeros(n, dtype=np.float32)
    pm_up_sell_30s = np.zeros(n, dtype=np.float32)
    pm_dn_sell_30s = np.zeros(n, dtype=np.float32)
    pm_up_buy_60s = np.zeros(n, dtype=np.float32)
    pm_dn_buy_60s = np.zeros(n, dtype=np.float32)
    pm_trade_count_30s = np.zeros(n, dtype=np.int32)
    pm_trade_count_60s = np.zeros(n, dtype=np.int32)
    pm_volume_total_30s = np.zeros(n, dtype=np.float32)
    pm_volume_total_60s = np.zeros(n, dtype=np.float32)

    # Group fires by slug
    fires_asset = fires_asset.reset_index(drop=True)
    fires_by_slug = {s: idx.tolist() for s, idx in fires_asset.groupby("slug").groups.items()}

    pm_by_slug_grp = pm.groupby("slug", sort=False)

    for slug, grp in pm_by_slug_grp:
        if slug not in fires_by_slug:
            continue
        ts = grp["timestamp_us"].values
        outc = grp["outcome"].values
        sd = grp["side"].values
        nt = grp["notional_usd"].values
        idx_list = fires_by_slug[slug]
        fire_us_arr = fires_asset.loc[idx_list, "fire_us"].values

        end_idx_arr = np.searchsorted(ts, fire_us_arr, side="left")
        start30_arr = np.searchsorted(ts, fire_us_arr - 30_000_000, side="left")
        start60_arr = np.searchsorted(ts, fire_us_arr - 60_000_000, side="left")

        for k, ix in enumerate(idx_list):
            e = end_idx_arr[k]
            s30 = start30_arr[k]
            s60 = start60_arr[k]
            if s30 < e:
                o = outc[s30:e]
                sd_w = sd[s30:e]
                nw = nt[s30:e]
                up = (o == "Up")
                dn = (o == "Down")
                bu = (sd_w == "buy")
                se = (sd_w == "sell")
                pm_up_buy_30s[ix] = nw[up & bu].sum()
                pm_dn_buy_30s[ix] = nw[dn & bu].sum()
                pm_up_sell_30s[ix] = nw[up & se].sum()
                pm_dn_sell_30s[ix] = nw[dn & se].sum()
                pm_trade_count_30s[ix] = e - s30
                pm_volume_total_30s[ix] = nw.sum()
            if s60 < e:
                o = outc[s60:e]
                sd_w = sd[s60:e]
                nw = nt[s60:e]
                up = (o == "Up")
                dn = (o == "Down")
                bu = (sd_w == "buy")
                pm_up_buy_60s[ix] = nw[up & bu].sum()
                pm_dn_buy_60s[ix] = nw[dn & bu].sum()
                pm_trade_count_60s[ix] = e - s60
                pm_volume_total_60s[ix] = nw.sum()

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
    fires_15m = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_15m.parquet")
    PM_START_US = pd.Timestamp("2026-04-26 13:00:00").value // 1000
    PM_END_US = pd.Timestamp("2026-05-25 19:00:00").value // 1000
    fires_15m = fires_15m[(fires_15m["fire_us"] >= PM_START_US) & (fires_15m["fire_us"] < PM_END_US)].copy()
    print(f"15m fires in window: {len(fires_15m):,}", flush=True)

    results = []
    for asset in ["BTC", "ETH", "SOL"]:
        print(f"  Loading PM trades {asset}...", flush=True)
        pm = load_pm_trades_asset(asset.lower())
        # Filter to relevant slugs only (drastically reduces working set)
        asset_prefix = f"{asset.lower()}-updown-"
        pm = pm[pm["slug"].str.startswith(asset_prefix)]
        # Also restrict to 15m slugs since that's all we need
        pm15 = pm[pm["slug"].str.contains("-15m-")].reset_index(drop=True)
        del pm
        gc.collect()
        print(f"    15m-only pm rows: {len(pm15):,}", flush=True)
        fa = fires_15m[fires_15m["asset"] == asset].reset_index(drop=True)
        print(f"    fires for {asset}: {len(fa):,}", flush=True)
        r = compute_flow_for_fires_optimized(fa, pm15)
        print(f"    -> {len(r):,} rows", flush=True)
        results.append(r)
        del pm15
        gc.collect()

    out = pd.concat(results, ignore_index=True)
    out_path = OUT_DIR / "pm_flow_features_15m.parquet"
    out.to_parquet(out_path, index=False)
    print(f"WROTE {out_path}  ({len(out):,} rows)", flush=True)


if __name__ == "__main__":
    main()
