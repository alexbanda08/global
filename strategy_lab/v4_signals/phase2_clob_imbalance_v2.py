"""Phase 2 — CLOB Imbalance v2 (Cyclops formulation).

Cyclops computes:
  imbalance = (up_vol - down_vol) / (up_vol + down_vol)
  where:
    up_vol = total $ pushed into UP token (buy YES + sell NO)
    down_vol = total $ pushed into DOWN (buy NO + sell YES)
  Filter: only fire when |imbalance| > 0.20.

Our flow_v3 CSV has columns: slug, outcome, taker_side, n_trades, total_size
(aggregated over the entire market window — not 2-min rolling).

Test: does aggregated CLOB imbalance predict outcome_up? If yes, the live 2-min
version (which we'd build with WS feed) is plausibly stronger. If null, the
Cyclops formulation isn't different enough from our V2 prob_c null result.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import spearmanr, binomtest

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "strategy_lab" / "data" / "polymarket"
ASSETS = ["btc", "eth", "sol"]


def build_imbalance(asset: str) -> pd.DataFrame:
    flow = pd.read_csv(PM / f"{asset}_flow_v3.csv")
    # Pivot: per slug, sum total_size by (outcome, taker_side)
    pivot = (
        flow.groupby(["slug", "outcome", "taker_side"])["total_size"].sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    # Pivot the (outcome, taker_side) into 4 columns per slug
    df = (
        flow.assign(key=flow["outcome"].str.cat(flow["taker_side"], sep="_"))
        .groupby(["slug", "key"])["total_size"].sum()
        .unstack(fill_value=0)
        .reset_index()
    )
    # Ensure all 4 columns exist (lowercase taker_side)
    for k in ["Up_buy", "Up_sell", "Down_buy", "Down_sell"]:
        if k not in df.columns:
            df[k] = 0.0
    # Bullish = bought UP shares + sold DOWN shares
    df["bull_vol"] = df["Up_buy"] + df["Down_sell"]
    df["bear_vol"] = df["Down_buy"] + df["Up_sell"]
    df["total_vol"] = df["bull_vol"] + df["bear_vol"]
    df["imbalance"] = np.where(
        df["total_vol"] > 0,
        (df["bull_vol"] - df["bear_vol"]) / df["total_vol"],
        np.nan,
    )
    df["abs_imbalance"] = df["imbalance"].abs()
    return df[["slug", "bull_vol", "bear_vol", "total_vol", "imbalance", "abs_imbalance"]]


def join_to_features(asset: str) -> pd.DataFrame:
    feats = pd.read_csv(PM / f"{asset}_features_v3.csv")
    feats = feats.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"])
    feats = feats[feats["timeframe"] == "5m"].copy()
    imb = build_imbalance(asset)
    df = feats.merge(imb, on="slug", how="inner")
    df["asset"] = asset
    return df


def report(df, label, threshold=0.20):
    print(f"\n=== {label} (n={len(df)}) ===")
    sub = df.dropna(subset=["imbalance"])
    print(f"  total_vol stats: mean=${sub['total_vol'].mean():.0f}  median=${sub['total_vol'].median():.0f}  p10=${sub['total_vol'].quantile(0.10):.0f}")
    print(f"  imbalance stats: mean={sub['imbalance'].mean():+.4f}  std={sub['imbalance'].std():.4f}")

    # Spearman IC: imbalance vs outcome_up
    rho, p = spearmanr(sub["imbalance"], sub["outcome_up"])
    sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else " "))
    print(f"  IC(imbalance vs outcome_up): rho={rho:+.4f}  p={p:.4g}  {sig}")

    # Cyclops gate test: when |imbalance| > 0.20, predict sign(imbalance)
    fired = sub[sub["abs_imbalance"] >= threshold].copy()
    fired["pred_up"] = fired["imbalance"] > 0
    fired["hit"] = ((fired["pred_up"]) & (fired["outcome_up"] == 1)) | \
                   ((~fired["pred_up"]) & (fired["outcome_up"] == 0))
    if len(fired) > 0:
        try:
            test = binomtest(int(fired["hit"].sum()), len(fired), p=0.5)
            p_h = test.pvalue
        except Exception:
            p_h = 1.0
        sig_h = "***" if p_h < 0.001 else ("**" if p_h < 0.01 else ("*" if p_h < 0.05 else " "))
        print(f"  Cyclops gate (|imb|>={threshold}): n={len(fired)}  hit={fired['hit'].mean():.4f}  p_vs_50%={p_h:.4g}  {sig_h}")

    # Decile-style: top vs bottom
    if len(sub) >= 100:
        q90 = sub["imbalance"].quantile(0.90)
        q10 = sub["imbalance"].quantile(0.10)
        top = sub[sub["imbalance"] >= q90]
        bot = sub[sub["imbalance"] <= q10]
        print(f"  Top decile (imb >= {q90:+.3f}): n={len(top)}  UP_rate={top['outcome_up'].mean():.4f}")
        print(f"  Bot decile (imb <= {q10:+.3f}): n={len(bot)}  UP_rate={bot['outcome_up'].mean():.4f}")


def report_v3_overlay(df, asset, label):
    """Test: does CLOB imbalance gate IMPROVE V3 sniper hit rate?"""
    cells = {"btc": 0.10, "eth": 0.05, "sol": 0.15}
    sub = df.dropna(subset=["ret_5m", "imbalance"]).copy()
    if len(sub) < 100: return
    thr = sub["ret_5m"].abs().quantile(1 - cells[asset])
    fired = sub[sub["ret_5m"].abs() >= thr].copy()
    fired["pred_up"] = fired["ret_5m"] > 0
    fired["hit"] = ((fired["pred_up"]) & (fired["outcome_up"] == 1)) | \
                   ((~fired["pred_up"]) & (fired["outcome_up"] == 0))

    base_hit = fired["hit"].mean()
    print(f"\n  -- V3 {asset.upper()} overlay test ({label}) --")
    print(f"    V3 baseline:               n={len(fired)}  hit={base_hit:.4f}")

    # CLOB imbalance ALIGNED with V3 direction
    aligned = fired[
        ((fired["pred_up"]) & (fired["imbalance"] > 0.05))
        | ((~fired["pred_up"]) & (fired["imbalance"] < -0.05))
    ]
    misaligned = fired[
        ((fired["pred_up"]) & (fired["imbalance"] < -0.05))
        | ((~fired["pred_up"]) & (fired["imbalance"] > 0.05))
    ]
    neutral = fired[fired["abs_imbalance"] < 0.05]

    for label2, s in [("CLOB aligned (>0.05)", aligned), ("CLOB misaligned (<-0.05)", misaligned), ("CLOB neutral (|x|<0.05)", neutral)]:
        if len(s) >= 5:
            print(f"    {label2:<28} n={len(s):>3d}  hit={s['hit'].mean():.4f}  delta={(s['hit'].mean()-base_hit)*100:+.1f}pp")


def main():
    pooled = pd.concat([join_to_features(a) for a in ASSETS], ignore_index=True)
    print(f"Pooled: {len(pooled)} markets across BTC/ETH/SOL")

    report(pooled, "ALL ASSETS pooled (5m)")

    for a in ASSETS:
        sub = pooled[pooled["asset"] == a]
        report(sub, f"{a.upper()} only")

    print("\n\n=== V3 OVERLAY TEST: does CLOB imbalance gate IMPROVE V3 hit rate? ===")
    for a in ASSETS:
        sub = pooled[pooled["asset"] == a]
        report_v3_overlay(sub, a, "5m")


if __name__ == "__main__":
    main()
