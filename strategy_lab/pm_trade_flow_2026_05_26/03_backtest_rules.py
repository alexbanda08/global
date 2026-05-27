"""TASK 3+4 — Standalone rules PM-A..PM-G and gate-overlay tests.

For each fire, we have:
- pm_flow_features (TASK 1): up_imbalance_30s, up_imbalance_60s, volume_total_30s, etc.
- whale_activity (TASK 2): whale_F1/F2/MS, whale_direction_majority
- hybrid_fire_universe (input): up_vwap, dn_vwap, outcome (chainlink)

Use LegacyConfig (2% on profit only, $25 notional).
Compute pnl_per_trade for both UP and DOWN bets, then rules pick direction.
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
LEG_FEE_PCT = 0.02  # 2% on profit only (winning leg)


def legacy_pnl(bet_dir: pd.Series, fires: pd.DataFrame) -> pd.Series:
    """Compute LegacyConfig PnL given direction bet 'Up'/'Down'/'none'.

    Buy at vwap, hold to expiry. Win = outcome matches.
    PnL_win = NOTIONAL * (1 - vwap) * (1 - LEG_FEE_PCT)
    PnL_lose = -NOTIONAL  # 2% of 0 = 0 fee
    Wait - actually it's 2% of profit. So profit_net = profit_gross * 0.98.
    profit_gross_per_share = 1 - vwap on win
    """
    # Pre-compute up and down outcomes
    up_won = (fires["outcome"] == "Up")
    dn_won = (fires["outcome"] == "Down")
    up_vwap = fires["up_vwap"].values
    dn_vwap = fires["dn_vwap"].values

    pnl = np.zeros(len(fires), dtype=np.float64)
    bd = bet_dir.values
    up_fill = fires["up_fill_ok"].values
    dn_fill = fires["dn_fill_ok"].values

    # Bet Up:
    bet_up = (bd == "Up")
    bet_dn = (bd == "Down")
    # shares = NOTIONAL / vwap
    # Win: payoff = shares * 1.0; profit = shares - NOTIONAL = NOTIONAL*(1/vwap - 1) = NOTIONAL*(1-vwap)/vwap
    # After 2% fee: profit_net = profit * 0.98
    # Lose: -NOTIONAL
    for i in range(len(fires)):
        if bd[i] == "Up":
            if not up_fill[i] or up_vwap[i] <= 0 or np.isnan(up_vwap[i]):
                continue
            shares = NOTIONAL / up_vwap[i]
            if up_won.iloc[i]:
                profit_gross = shares - NOTIONAL  # value at expiry = shares * 1.0
                pnl[i] = profit_gross * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
        elif bd[i] == "Down":
            if not dn_fill[i] or dn_vwap[i] <= 0 or np.isnan(dn_vwap[i]):
                continue
            shares = NOTIONAL / dn_vwap[i]
            if dn_won.iloc[i]:
                profit_gross = shares - NOTIONAL
                pnl[i] = profit_gross * (1 - LEG_FEE_PCT)
            else:
                pnl[i] = -NOTIONAL
        # else 'none' = no bet, pnl=0 (skip)
    return pd.Series(pnl, index=fires.index)


def summarize(pnl: pd.Series, bet_dir: pd.Series, outcome: pd.Series, label: str) -> dict:
    placed = bet_dir.isin(["Up", "Down"])
    n_placed = int(placed.sum())
    if n_placed == 0:
        return {"label": label, "n": 0, "wr": np.nan, "pnl_per": np.nan, "sum_pnl": 0.0}
    pn = pnl[placed]
    wins = (pn > 0).sum()
    return {
        "label": label,
        "n": n_placed,
        "wr": wins / n_placed * 100,
        "pnl_per": float(pn.mean()),
        "sum_pnl": float(pn.sum()),
    }


def per_segment_summary(pnl: pd.Series, bet_dir: pd.Series, fires: pd.DataFrame, rule: str) -> pd.DataFrame:
    df = fires.copy()
    df["pnl"] = pnl
    df["bet_dir"] = bet_dir
    placed = df[df["bet_dir"].isin(["Up", "Down"])].copy()
    if len(placed) == 0:
        return pd.DataFrame()
    placed["win"] = (placed["pnl"] > 0).astype(int)
    grp = placed.groupby(["asset", "tf", "fire_offset_s"]).agg(
        n=("pnl", "size"),
        wr=("win", "mean"),
        pnl_per=("pnl", "mean"),
        sum_pnl=("pnl", "sum"),
    ).reset_index()
    grp["wr"] = grp["wr"] * 100
    grp["rule"] = rule
    return grp


def main():
    print("Loading data...", flush=True)
    # Load fires (with up_vwap, dn_vwap, outcome, fills)
    parts = []
    for tf in ["5m", "15m"]:
        f = pd.read_parquet(ROOT / "data" / "v4" / "canonical" / "_results" / f"hybrid_fire_universe_{tf}.parquet")
        parts.append(f)
    fires_all = pd.concat(parts, ignore_index=True)
    PM_START_US = pd.Timestamp("2026-04-26 13:00:00").value // 1000
    PM_END_US = pd.Timestamp("2026-05-25 19:00:00").value // 1000
    fires_all = fires_all[(fires_all["fire_us"] >= PM_START_US) & (fires_all["fire_us"] < PM_END_US)].reset_index(drop=True)
    print(f"fires in window: {len(fires_all):,}", flush=True)

    # Load features
    f5 = pd.read_parquet(OUT_DIR / "pm_flow_features_5m.parquet")
    f15 = pd.read_parquet(OUT_DIR / "pm_flow_features_15m.parquet")
    feats = pd.concat([f5, f15], ignore_index=True)
    w5 = pd.read_parquet(OUT_DIR / "whale_activity_5m.parquet")
    w15 = pd.read_parquet(OUT_DIR / "whale_activity_15m.parquet")
    whales = pd.concat([w5, w15], ignore_index=True)

    print(f"feats: {len(feats):,}  whales: {len(whales):,}", flush=True)

    # Merge
    join_keys = ["asset", "slug", "tf", "fire_us", "fire_offset_s"]
    df = fires_all.merge(feats[join_keys + ["pm_up_imbalance_30s", "pm_up_imbalance_60s", "pm_volume_total_30s", "pm_volume_total_60s", "pm_trade_count_30s", "pm_avg_trade_size_30s", "pm_up_buy_30s", "pm_dn_buy_30s"]], on=join_keys, how="left")
    df = df.merge(whales[join_keys + ["whale_F1_active_60s", "whale_F2_active_60s", "whale_mintsell_active_60s", "whale_unknown_large_active_60s", "whale_direction_majority", "whale_up_buys_60s", "whale_dn_buys_60s"]], on=join_keys, how="left")
    print(f"df after merge: {len(df):,}  has_imb_30s: {df['pm_up_imbalance_30s'].notna().sum():,}", flush=True)

    # Median 30s volume per (asset, tf, offset) for spike detection
    vol_med = df.groupby(["asset", "tf", "fire_offset_s"])["pm_volume_total_30s"].median().reset_index()
    vol_med.columns = ["asset", "tf", "fire_offset_s", "pm_volume_30s_median"]
    df = df.merge(vol_med, on=["asset", "tf", "fire_offset_s"], how="left")
    df["pm_volume_spike"] = (df["pm_volume_total_30s"] > 3 * df["pm_volume_30s_median"]).astype(int)

    # Book imbalance for PM-F: use up_ask0/dn_ask0 from fires
    # bigger sum_asks means more shares available = better for that side. Use mid prices.
    # Simpler proxy: (up_bid0 + dn_ask0 - 1) sign — if up_bid+dn_ask > 1 then book favors Up.
    df["book_favors_up"] = ((df["up_bid0"] + df["dn_ask0"]) > 1.0).astype(int)

    # Rule definitions
    # PM-A: follow 30s imbalance (bet Up if imb_30s > 0, Down if < 0)
    df["dir_pmA"] = np.where(df["pm_up_imbalance_30s"] > 0.0, "Up", np.where(df["pm_up_imbalance_30s"] < 0.0, "Down", "none"))
    # Strong version: |imb| > 0.3
    df["dir_pmA_strong"] = np.where(df["pm_up_imbalance_30s"] > 0.3, "Up", np.where(df["pm_up_imbalance_30s"] < -0.3, "Down", "none"))
    # PM-B: fade 30s imbalance
    df["dir_pmB"] = np.where(df["pm_up_imbalance_30s"] > 0.0, "Down", np.where(df["pm_up_imbalance_30s"] < 0.0, "Up", "none"))
    df["dir_pmB_strong"] = np.where(df["pm_up_imbalance_30s"] > 0.3, "Down", np.where(df["pm_up_imbalance_30s"] < -0.3, "Up", "none"))
    # PM-C: follow whale majority
    df["dir_pmC"] = np.where(df["whale_direction_majority"] == "Up", "Up", np.where(df["whale_direction_majority"] == "Down", "Down", "none"))
    # PM-D: fade whale majority
    df["dir_pmD"] = np.where(df["whale_direction_majority"] == "Up", "Down", np.where(df["whale_direction_majority"] == "Down", "Up", "none"))
    # PM-E: Up when volume spike AND strong up flow
    df["dir_pmE"] = np.where((df["pm_volume_spike"] == 1) & (df["pm_up_imbalance_30s"] > 0.6), "Up",
                              np.where((df["pm_volume_spike"] == 1) & (df["pm_up_imbalance_30s"] < -0.6), "Down", "none"))
    # PM-F: book favors Up AND PM flow net Down  (smart money diverges from retail)
    df["dir_pmF"] = np.where(
        (df["book_favors_up"] == 1) & (df["pm_up_imbalance_30s"] < -0.3),
        "Up",
        np.where((df["book_favors_up"] == 0) & (df["pm_up_imbalance_30s"] > 0.3), "Down", "none")
    )
    # PM-G: mint-sell footprint -> bet AGAINST whale inventory direction (their inventory side they want to dump)
    # mint-and-sell makers POST limits at ~$0.50 on both sides. If their inventory has built up on Up side (whale_up_buys > whale_dn_buys), they want price to settle Down — so we bet Down.
    df["dir_pmG"] = np.where(
        df["whale_mintsell_active_60s"] == True,
        np.where(df["whale_up_buys_60s"] > df["whale_dn_buys_60s"], "Down", "Up"),
        "none"
    )

    # Compute PnL for all rules
    rules = ["pmA", "pmA_strong", "pmB", "pmB_strong", "pmC", "pmD", "pmE", "pmF", "pmG"]
    summaries = []
    seg_summaries = []
    for r in rules:
        col = f"dir_{r}"
        if col not in df.columns:
            continue
        pnl = legacy_pnl(df[col], df)
        df[f"pnl_{r}"] = pnl
        summaries.append(summarize(pnl, df[col], df["outcome"], r))
        seg_summaries.append(per_segment_summary(pnl, df[col], df, r))

    overall = pd.DataFrame(summaries)
    print("\n=== STANDALONE RULE OVERALL ===\n", overall.to_string(index=False), flush=True)
    overall.to_csv(OUT_DIR / "standalone_rule_overall.csv", index=False)

    if seg_summaries:
        seg = pd.concat([s for s in seg_summaries if len(s) > 0], ignore_index=True)
        seg = seg[seg["n"] >= 50].sort_values("sum_pnl", ascending=False)
        print("\n=== TOP STANDALONE BY SEGMENT (n>=50) ===\n", seg.head(40).to_string(index=False), flush=True)
        seg.to_csv(OUT_DIR / "standalone_rule_by_segment.csv", index=False)

    # Save enriched dataframe for downstream
    df.to_parquet(OUT_DIR / "fires_with_pm_features.parquet", index=False)
    print(f"\nWROTE fires_with_pm_features.parquet ({len(df):,} rows)", flush=True)


if __name__ == "__main__":
    main()
