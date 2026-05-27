"""TASK 5+6 — Wallet catalog directional accuracy + F2-style replication.

For each whale wallet, look at their trades during a fire's slug window,
infer their direction bet, and check whether they were right at expiry.

Then test F2-style rule: bet OPPOSITE the 5s book flow_imbalance direction.
"""
from __future__ import annotations
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "strategy_lab" / "pm_trade_flow_2026_05_26"

NOTIONAL = 25.0
LEG_FEE_PCT = 0.02


def main():
    print("=== WALLET CATALOG DIRECTIONAL ACCURACY ===", flush=True)
    # For each wallet, get trades, derive direction bet per trade, find slot outcome.
    # We need slug -> outcome from canonical resolutions.
    sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
    from load import load_resolutions
    res = load_resolutions()
    print(f"resolutions: {len(res):,}", flush=True)
    # Filter to outcome != null
    res = res[res["outcome"].isin(["Up", "Down"])][["slug", "outcome"]].drop_duplicates(subset=["slug"])
    print(f"resolved: {len(res):,}", flush=True)

    rows = []
    for w in ["0xb27bc932", "0x04b6d7e9", "0xce25e214", "0xeebde7a0", "0x89b5cdaa", "0xcfb103c3"]:
        for fname in ["trades_chain_enriched.parquet", "fills.parquet"]:
            p = ROOT / "strategy_lab" / "wallet_hunt" / "cache" / w / fname
            if p.exists():
                df = pd.read_parquet(p)
                break
        else:
            continue
        if "slug" not in df.columns:
            continue
        if "side_clean" in df.columns:
            df["side_s"] = df["side_clean"]
        else:
            df["side_s"] = df["side"]
        if "usdc_notional" in df.columns:
            df["usd"] = df["usdc_notional"]
        elif "usd" in df.columns:
            pass
        else:
            df["usd"] = df["price"] * df["size"]
        df = df.dropna(subset=["slug", "outcome", "side_s"])
        df["side_s"] = df["side_s"].astype(str).str.upper()
        # Direction bet: BUY Up or SELL Down = bullish; BUY Down or SELL Up = bearish
        df["wallet_dir"] = np.where(
            ((df["outcome"] == "Up") & (df["side_s"] == "BUY")) | ((df["outcome"] == "Down") & (df["side_s"] == "SELL")),
            "Up",
            np.where(
                ((df["outcome"] == "Down") & (df["side_s"] == "BUY")) | ((df["outcome"] == "Up") & (df["side_s"] == "SELL")),
                "Down", "none"
            )
        )
        # Aggregate per slug: which direction did wallet bet more $?
        agg = df.groupby("slug").apply(lambda g: pd.Series({
            "up_usd": g.loc[g["wallet_dir"] == "Up", "usd"].sum(),
            "dn_usd": g.loc[g["wallet_dir"] == "Down", "usd"].sum(),
            "total_usd": g["usd"].sum(),
        })).reset_index()
        agg["wallet_bet"] = np.where(agg["up_usd"] > agg["dn_usd"], "Up", np.where(agg["dn_usd"] > agg["up_usd"], "Down", "none"))
        # Join outcome
        agg = agg.merge(res, on="slug", how="left")
        placed = agg[agg["wallet_bet"].isin(["Up", "Down"]) & agg["outcome"].notna()].copy()
        if len(placed) == 0:
            continue
        placed["correct"] = (placed["wallet_bet"] == placed["outcome"]).astype(int)
        n = len(placed)
        wr = placed["correct"].mean() * 100
        rows.append({
            "wallet": w,
            "n_slugs": n,
            "win_rate": wr,
            "total_usd": placed["total_usd"].sum(),
            "median_usd_per_slug": placed["total_usd"].median(),
        })
        print(f"  {w}: n={n}, WR={wr:.1f}%, total_usd=${placed['total_usd'].sum():,.0f}", flush=True)

    wal = pd.DataFrame(rows)
    wal.to_csv(OUT_DIR / "wallet_accuracy.csv", index=False)
    print("\n", wal.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
