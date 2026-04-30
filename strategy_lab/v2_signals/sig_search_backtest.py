"""Signal search — magnitude thresholds + multi-feature signal combinations.

We've established sniper q10 works on ret_5m. Now sweep:
  1. Magnitude: q5 (top 5%), q15, q20, q25, q33, q50 — find optimal selectivity
  2. Multi-horizon AND: fire only when ret_5m AND ret_15m AND ret_1h all agree
  3. Per asset: identify best (mag, multi) per asset

For each cell: hit rate, ROI on $25 buy held to resolution, n.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS

NOTIONAL = 25.0
FEE = 0.02

MAGNITUDE_QUANTILES = {
    "q5": 0.05, "q10": 0.10, "q15": 0.15, "q20": 0.20,
    "q25": 0.25, "q33": 0.33, "q50": 0.50,
}


def evaluate(df, predict_col):
    pred_up = df[predict_col] > 0
    pred_dn = df[predict_col] < 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (pred_dn & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    n = len(df)
    return n, hit.sum(), pnl_after.sum()


def main():
    rows = []
    for asset in ASSETS:
        feats = load_features(asset).dropna(
            subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
        )

        # Two selectivity strategies:
        # A) Magnitude on |ret_5m| alone
        # B) Multi-horizon agreement (all 3 same sign) + magnitude on ret_5m
        for tf in ("5m", "15m", "ALL"):
            sub = feats if tf == "ALL" else feats[feats["timeframe"] == tf]
            if len(sub) == 0:
                continue

            for mag_label, mag_q in MAGNITUDE_QUANTILES.items():
                # A: magnitude only
                thr = sub["ret_5m"].abs().quantile(1 - mag_q)
                a_sub = sub[sub["ret_5m"].abs() >= thr]
                if len(a_sub) > 0:
                    n, h, p = evaluate(a_sub, "ret_5m")
                    rows.append({
                        "asset": asset, "tf": tf, "selector": "mag_only", "mag": mag_label,
                        "n": n, "hit_pct": round(h / n * 100, 1),
                        "total_pnl": round(p, 2),
                        "roi_pct": round(p / (NOTIONAL * n) * 100, 2),
                    })

                # B: multi-horizon agreement filter, then magnitude
                same_sign = (
                    (sub["ret_5m"] > 0) & (sub["ret_15m"] > 0) & (sub["ret_1h"] > 0)
                ) | (
                    (sub["ret_5m"] < 0) & (sub["ret_15m"] < 0) & (sub["ret_1h"] < 0)
                )
                multi_sub = sub[same_sign]
                if len(multi_sub) == 0:
                    continue
                # Apply magnitude on this subset
                thr_m = multi_sub["ret_5m"].abs().quantile(1 - mag_q) if len(multi_sub) > 5 else 0
                b_sub = multi_sub[multi_sub["ret_5m"].abs() >= thr_m]
                if len(b_sub) > 0:
                    n, h, p = evaluate(b_sub, "ret_5m")
                    rows.append({
                        "asset": asset, "tf": tf, "selector": "multi_horizon", "mag": mag_label,
                        "n": n, "hit_pct": round(h / n * 100, 1),
                        "total_pnl": round(p, 2),
                        "roi_pct": round(p / (NOTIONAL * n) * 100, 2),
                    })

    df = pd.DataFrame(rows)

    print("=== Magnitude sweep, sig_ret5m, hold to resolution ===")
    print("\n--- per asset (tf=ALL) ---")
    pivot = df[(df["tf"] == "ALL") & (df["selector"] == "mag_only")]
    print(pivot[["asset", "mag", "n", "hit_pct", "roi_pct"]].to_string(index=False))

    print("\n--- multi-horizon agreement (tf=ALL) ---")
    multi = df[(df["tf"] == "ALL") & (df["selector"] == "multi_horizon")]
    print(multi[["asset", "mag", "n", "hit_pct", "roi_pct"]].to_string(index=False))

    print("\n=== Top 20 cells overall by ROI (any asset/tf/selector) ===")
    print(df.nlargest(20, "roi_pct").to_string(index=False))

    print("\n=== Best mag per (asset, tf, selector) ===")
    best = df.loc[df.groupby(["asset", "tf", "selector"])["roi_pct"].idxmax()]
    print(best.sort_values(["asset", "tf"]).to_string(index=False))


if __name__ == "__main__":
    main()
