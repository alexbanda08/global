"""Whale wallet detection — TASK 2.

For each fire, check if any catalogued whale traded the slug in last 60s.
Source: wallet_hunt/cache/{wallet}/trades_chain_enriched.parquet (has slug + ts).

Output: whale_activity_{tf}.parquet
"""
from __future__ import annotations
import sys
import os
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# Wallet classification per CLAUDE.md + WALLET_CATALOG
WALLET_GROUPS = {
    "F1": ["0xb27bc932"],  # directional CLOB taker via F1 treasury
    "F2": ["0xa0a50783", "0x9dae874a"],  # directional CLOB taker at mispricing
    "mintsell": ["0x04b6d7e9", "0xce25e214", "0xeebde7a0"],  # mint-and-sell trio (maker)
    "other_directional": ["0x7f599984", "0x89b5cdaa", "0xcfb103c3"],
    "non_updown": ["0x3e6bfd2f", "0x0fe40e88", "0x7cde1da9", "0x7dfc8aa2"],
}

ALL_WALLETS = [w for grp in WALLET_GROUPS.values() for w in grp]


def load_wallet_trades(wallet: str) -> pd.DataFrame | None:
    base = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / wallet
    # Prefer enriched, then fills, then trades
    for fname in ["trades_chain_enriched.parquet", "fills.parquet"]:
        p = base / fname
        if p.exists():
            df = pd.read_parquet(p)
            # Standardize
            if "timestamp_us" not in df.columns:
                if "timestamp" in df.columns:
                    df["timestamp_us"] = (df["timestamp"].astype("int64") * 1_000_000)
                elif "ts_s" in df.columns:
                    df["timestamp_us"] = (df["ts_s"].astype("int64") * 1_000_000)
            if "slug" not in df.columns:
                continue
            keep = [c for c in ["timestamp_us", "slug", "outcome", "side", "side_clean", "price", "size", "usdc_notional", "usd", "wallet_is_maker", "wallet_is_taker", "is_maker"] if c in df.columns]
            df = df[keep].copy()
            df = df.dropna(subset=["timestamp_us", "slug"])
            df["wallet"] = wallet
            return df
    return None


def build_whale_table() -> pd.DataFrame:
    parts = []
    for w in ALL_WALLETS:
        df = load_wallet_trades(w)
        if df is None or len(df) == 0:
            print(f"  {w}: NO DATA", flush=True)
            continue
        # add group label
        for grp, ws in WALLET_GROUPS.items():
            if w in ws:
                df["wallet_group"] = grp
                break
        print(f"  {w}: {len(df):,} trades, slug count={df['slug'].nunique()}", flush=True)
        # Use 'side' or 'side_clean'
        if "side_clean" in df.columns and df["side_clean"].notna().any():
            df["side_s"] = df["side_clean"]
        else:
            df["side_s"] = df["side"]
        # Direction the wallet BOUGHT: BUY of outcome=Up means betting Up; SELL Up means betting Down (closing or short Up)
        # Simplification: outcome+side_s -> infer direction taken
        # For BUY Up = bullish; BUY Down = bearish; SELL Up = bearish closing; SELL Down = bullish closing
        # For mint-and-sell makers, we don't care direction strongly.
        if "usdc_notional" in df.columns:
            df["usd"] = df["usdc_notional"]
        elif "usd" in df.columns:
            pass
        else:
            df["usd"] = df["price"] * df["size"]
        df = df[["timestamp_us", "slug", "outcome", "side_s", "usd", "wallet", "wallet_group"]].dropna(subset=["timestamp_us", "slug", "outcome", "side_s"])
        parts.append(df)

    all_trades = pd.concat(parts, ignore_index=True)
    all_trades = all_trades.sort_values(["slug", "timestamp_us"]).reset_index(drop=True)
    print(f"Total whale trades: {len(all_trades):,}", flush=True)
    return all_trades


def compute_whale_activity(fires: pd.DataFrame, whale_trades: pd.DataFrame) -> pd.DataFrame:
    n = len(fires)
    fires = fires.reset_index(drop=True)
    whale_F1 = np.zeros(n, dtype=bool)
    whale_F2 = np.zeros(n, dtype=bool)
    whale_MS = np.zeros(n, dtype=bool)
    whale_unknown_large = np.zeros(n, dtype=bool)
    n_whale_trades_60s = np.zeros(n, dtype=np.int32)
    whale_up_buys_60s = np.zeros(n, dtype=np.float32)
    whale_dn_buys_60s = np.zeros(n, dtype=np.float32)

    fires_by_slug = {s: idx.tolist() for s, idx in fires.groupby("slug").groups.items()}
    whales_by_slug = whale_trades.groupby("slug", sort=False)

    for slug, grp in whales_by_slug:
        if slug not in fires_by_slug:
            continue
        ts = grp["timestamp_us"].values
        outc = grp["outcome"].values
        sd = grp["side_s"].values
        usd = grp["usd"].values
        wgrp = grp["wallet_group"].values
        idx_list = fires_by_slug[slug]
        fire_us_arr = fires.loc[idx_list, "fire_us"].values

        end_idx_arr = np.searchsorted(ts, fire_us_arr, side="left")
        start60_arr = np.searchsorted(ts, fire_us_arr - 60_000_000, side="left")

        for k, ix in enumerate(idx_list):
            e = end_idx_arr[k]
            s = start60_arr[k]
            if s >= e:
                continue
            wg = wgrp[s:e]
            o = outc[s:e]
            sw = sd[s:e]
            u = usd[s:e]
            whale_F1[ix] = ("F1" in wg)
            whale_F2[ix] = ("F2" in wg)
            whale_MS[ix] = ("mintsell" in wg)
            whale_unknown_large[ix] = (u > 100).any()
            n_whale_trades_60s[ix] = e - s
            # Direction: BUY Up or SELL Down ~= bullish
            sw_upper = np.array([str(x).upper() for x in sw])
            bull_mask = ((o == "Up") & (sw_upper == "BUY")) | ((o == "Down") & (sw_upper == "SELL"))
            bear_mask = ((o == "Up") & (sw_upper == "SELL")) | ((o == "Down") & (sw_upper == "BUY"))
            whale_up_buys_60s[ix] = u[bull_mask].sum()
            whale_dn_buys_60s[ix] = u[bear_mask].sum()

    out = fires[["asset", "slug", "tf", "fire_us", "fire_offset_s", "outcome", "ws_s"]].copy()
    out["whale_F1_active_60s"] = whale_F1
    out["whale_F2_active_60s"] = whale_F2
    out["whale_mintsell_active_60s"] = whale_MS
    out["whale_unknown_large_active_60s"] = whale_unknown_large
    out["n_whale_trades_60s"] = n_whale_trades_60s
    out["whale_up_buys_60s"] = whale_up_buys_60s
    out["whale_dn_buys_60s"] = whale_dn_buys_60s
    denom = out["whale_up_buys_60s"] + out["whale_dn_buys_60s"]
    out["whale_direction_majority"] = np.where(
        denom == 0, "none",
        np.where(out["whale_up_buys_60s"] > out["whale_dn_buys_60s"], "Up", "Down")
    )
    return out


def main():
    print("Loading whale wallets...", flush=True)
    whale_trades = build_whale_table()
    print(f"Whale trades ts range: {pd.to_datetime(whale_trades.timestamp_us.min(), unit='us')} .. {pd.to_datetime(whale_trades.timestamp_us.max(), unit='us')}", flush=True)

    PM_START_US = pd.Timestamp("2026-04-26 13:00:00").value // 1000
    PM_END_US = pd.Timestamp("2026-05-25 19:00:00").value // 1000

    for tf in ["5m", "15m"]:
        fires = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / f"hybrid_fire_universe_{tf}.parquet")
        fires = fires[(fires["fire_us"] >= PM_START_US) & (fires["fire_us"] < PM_END_US)].reset_index(drop=True)
        print(f"\n{tf} fires: {len(fires):,}", flush=True)
        r = compute_whale_activity(fires, whale_trades)
        out_path = OUT_DIR / f"whale_activity_{tf}.parquet"
        r.to_parquet(out_path, index=False)
        print(f"WROTE {out_path}  ({len(r):,} rows)", flush=True)
        # Quick stats
        for col in ["whale_F1_active_60s", "whale_F2_active_60s", "whale_mintsell_active_60s", "whale_unknown_large_active_60s"]:
            print(f"  {col}: pct={r[col].mean()*100:.2f}%", flush=True)


if __name__ == "__main__":
    main()
