"""TASK 6 — F2-style replication: bet OPPOSITE the 5s book flow_imbalance.

F2 strategy per F2_FINAL_VERDICT_2026_05_18.md fires contrarian to recent flow.
Test on broader window using 5s book imbalance derived from L25.

Cheaper: use 5s PM TRADE FLOW imbalance as proxy (we have PM trades feature).
We already have pm_up_imbalance_30s. Compute pm_up_imbalance_5s.
"""
from __future__ import annotations
import sys
import gc
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"

NOTIONAL = 25.0
LEG_FEE_PCT = 0.02


def compute_pm_imbalance_5s(fires_asset: pd.DataFrame, pm: pd.DataFrame) -> pd.DataFrame:
    n = len(fires_asset)
    up_buy_5s = np.zeros(n, dtype=np.float32)
    dn_buy_5s = np.zeros(n, dtype=np.float32)
    n_trades_5s = np.zeros(n, dtype=np.int32)
    fires_asset = fires_asset.reset_index(drop=True)
    fires_by_slug = {s: idx.tolist() for s, idx in fires_asset.groupby("slug").groups.items()}
    pm_by_slug_grp = pm.groupby("slug", sort=False)
    for slug, grp in pm_by_slug_grp:
        if slug not in fires_by_slug:
            continue
        ts = grp["timestamp_us"].values
        outc = grp["outcome"].values
        sd = grp["side"].values
        nt = (grp["price"].values * grp["size"].values).astype("float32")
        idx_list = fires_by_slug[slug]
        fire_us_arr = fires_asset.loc[idx_list, "fire_us"].values
        end_idx_arr = np.searchsorted(ts, fire_us_arr, side="left")
        start5_arr = np.searchsorted(ts, fire_us_arr - 5_000_000, side="left")
        for k, ix in enumerate(idx_list):
            e = end_idx_arr[k]
            s = start5_arr[k]
            if s >= e:
                continue
            o = outc[s:e]
            sd_w = sd[s:e]
            nw = nt[s:e]
            up = (o == "Up") & (sd_w == "buy")
            dn = (o == "Down") & (sd_w == "buy")
            up_buy_5s[ix] = nw[up].sum()
            dn_buy_5s[ix] = nw[dn].sum()
            n_trades_5s[ix] = e - s
    out = fires_asset.copy()
    out["pm_up_buy_5s"] = up_buy_5s
    out["pm_dn_buy_5s"] = dn_buy_5s
    out["pm_n_trades_5s"] = n_trades_5s
    denom = out["pm_up_buy_5s"] + out["pm_dn_buy_5s"]
    out["pm_up_imbalance_5s"] = np.where(denom > 0, (out["pm_up_buy_5s"] - out["pm_dn_buy_5s"]) / denom, np.nan)
    return out


def legacy_pnl(df: pd.DataFrame, dir_col: str) -> pd.Series:
    n = len(df)
    pnl = np.zeros(n, dtype=np.float64)
    up_vwap = df["up_vwap"].values
    dn_vwap = df["dn_vwap"].values
    outcome = df["outcome"].values
    up_fill = df["up_fill_ok"].values
    dn_fill = df["dn_fill_ok"].values
    dirs = df[dir_col].values
    for i in range(n):
        d = dirs[i]
        if d == "Up":
            if not up_fill[i] or np.isnan(up_vwap[i]) or up_vwap[i] <= 0:
                continue
            shares = NOTIONAL / up_vwap[i]
            if outcome[i] == "Up":
                pnl[i] = (shares - NOTIONAL) * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
        elif d == "Down":
            if not dn_fill[i] or np.isnan(dn_vwap[i]) or dn_vwap[i] <= 0:
                continue
            shares = NOTIONAL / dn_vwap[i]
            if outcome[i] == "Down":
                pnl[i] = (shares - NOTIONAL) * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
    return pd.Series(pnl, index=df.index)


def main():
    print("Loading fires + PM trades to build 5s imbalance...", flush=True)
    parts = []
    fires_5m = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_5m.parquet")
    fires_15m = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / "hybrid_fire_universe_15m.parquet")
    PM_START_US = pd.Timestamp("2026-04-26 13:00:00").value // 1000
    PM_END_US = pd.Timestamp("2026-05-25 19:00:00").value // 1000
    fires_5m = fires_5m[(fires_5m["fire_us"] >= PM_START_US) & (fires_5m["fire_us"] < PM_END_US)].reset_index(drop=True)
    fires_15m = fires_15m[(fires_15m["fire_us"] >= PM_START_US) & (fires_15m["fire_us"] < PM_END_US)].reset_index(drop=True)

    all_parts = []
    for tf_name, fires in [("5m", fires_5m), ("15m", fires_15m)]:
        for asset in ["BTC", "ETH", "SOL"]:
            print(f"  Loading PM {asset} {tf_name}...", flush=True)
            p = ROOT / "data" / "v4" / "canonical" / "trades_polymarket" / f"{asset.lower()}.parquet"
            pm = pd.read_parquet(p, columns=["timestamp_us", "slug", "outcome", "price", "size", "side"])
            pm = pm[pm["slug"].str.contains(f"-updown-{tf_name}-")].reset_index(drop=True)
            pm = pm.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)
            fa = fires[fires["asset"] == asset].reset_index(drop=True)
            print(f"    fires {asset}: {len(fa):,}, pm {tf_name}: {len(pm):,}", flush=True)
            r = compute_pm_imbalance_5s(fa, pm)
            all_parts.append(r)
            del pm
            gc.collect()

    big = pd.concat(all_parts, ignore_index=True)
    big.to_parquet(OUT_DIR / "pm_imbalance_5s.parquet", index=False)
    print(f"WROTE pm_imbalance_5s ({len(big):,} rows)", flush=True)

    # F2-style rule: bet OPPOSITE the 5s imbalance direction
    big["dir_f2_fade"] = np.where(big["pm_up_imbalance_5s"] > 0, "Down", np.where(big["pm_up_imbalance_5s"] < 0, "Up", "none"))
    big["dir_f2_fade_strong"] = np.where(big["pm_up_imbalance_5s"] > 0.5, "Down", np.where(big["pm_up_imbalance_5s"] < -0.5, "Up", "none"))

    for col in ["dir_f2_fade", "dir_f2_fade_strong"]:
        big[f"pnl_{col}"] = legacy_pnl(big, col)

    # Segment view
    for col in ["dir_f2_fade", "dir_f2_fade_strong"]:
        placed = big[big[col].isin(["Up", "Down"])].copy()
        placed["win"] = (placed[f"pnl_{col}"] > 0).astype(int)
        grp = placed.groupby(["asset", "tf", "fire_offset_s"]).agg(
            n=("win", "size"),
            wr=("win", "mean"),
            pnl_per=(f"pnl_{col}", "mean"),
            sum_pnl=(f"pnl_{col}", "sum"),
        ).reset_index()
        grp["wr"] = grp["wr"] * 100
        grp["rule"] = col
        grp = grp[grp["n"] >= 50].sort_values("sum_pnl", ascending=False)
        print(f"\n=== TOP {col} BY SEGMENT (n>=50) ===\n", grp.head(20).to_string(index=False), flush=True)
        grp.to_csv(OUT_DIR / f"f2_replication_{col}.csv", index=False)


if __name__ == "__main__":
    main()
