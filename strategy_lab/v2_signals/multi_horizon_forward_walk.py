"""Forward-walk: multi-horizon agreement + magnitude sniper.

Apply the standard chronological 80/20 split. For each asset/tf/mag, test:
  - mag_only baseline
  - multi_horizon (all 3 returns same sign) + magnitude

Pass criteria: holdout hit ≥60%, ROI ≥+10%, train→holdout drift ≤8pp.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, chronological_split

NOTIONAL = 25.0
FEE = 0.02


def evaluate(df):
    if len(df) == 0:
        return None
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    n = len(df)
    return {
        "n": n,
        "hit_pct": round(hit.sum() / n * 100, 1),
        "total_pnl": round(pnl_after.sum(), 2),
        "roi_pct": round(pnl_after.sum() / (NOTIONAL * n) * 100, 2),
    }


def main():
    rows = []
    for asset in ASSETS:
        feats = load_features(asset).dropna(
            subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
        )
        for tf in ("5m", "15m", "ALL"):
            tf_sub = feats if tf == "ALL" else feats[feats["timeframe"] == tf]
            if len(tf_sub) < 50:
                continue
            train, holdout = chronological_split(tf_sub)

            for mag_label, mag_q in [("q5", 0.05), ("q10", 0.10), ("q15", 0.15), ("q20", 0.20)]:
                # Mag-only on train
                thr = train["ret_5m"].abs().quantile(1 - mag_q)
                tr_mag = train[train["ret_5m"].abs() >= thr]
                ho_mag = holdout[holdout["ret_5m"].abs() >= thr]
                tr_res = evaluate(tr_mag)
                ho_res = evaluate(ho_mag)
                if tr_res and ho_res and ho_res["n"] > 0:
                    rows.append({
                        "asset": asset, "tf": tf, "selector": "mag_only", "mag": mag_label,
                        "tr_n": tr_res["n"], "tr_hit": tr_res["hit_pct"], "tr_roi": tr_res["roi_pct"],
                        "ho_n": ho_res["n"], "ho_hit": ho_res["hit_pct"], "ho_roi": ho_res["roi_pct"],
                        "drift_hit_pp": round(tr_res["hit_pct"] - ho_res["hit_pct"], 1),
                    })

                # Multi-horizon
                same = lambda d: ((d["ret_5m"] > 0) & (d["ret_15m"] > 0) & (d["ret_1h"] > 0)) | \
                                 ((d["ret_5m"] < 0) & (d["ret_15m"] < 0) & (d["ret_1h"] < 0))
                tr_mh = train[same(train)]
                ho_mh = holdout[same(holdout)]
                if len(tr_mh) < 30:
                    continue
                thr_mh = tr_mh["ret_5m"].abs().quantile(1 - mag_q)
                tr_mh_mag = tr_mh[tr_mh["ret_5m"].abs() >= thr_mh]
                ho_mh_mag = ho_mh[ho_mh["ret_5m"].abs() >= thr_mh]
                tr_res = evaluate(tr_mh_mag)
                ho_res = evaluate(ho_mh_mag)
                if tr_res and ho_res and ho_res["n"] > 0:
                    rows.append({
                        "asset": asset, "tf": tf, "selector": "multi_horizon", "mag": mag_label,
                        "tr_n": tr_res["n"], "tr_hit": tr_res["hit_pct"], "tr_roi": tr_res["roi_pct"],
                        "ho_n": ho_res["n"], "ho_hit": ho_res["hit_pct"], "ho_roi": ho_res["roi_pct"],
                        "drift_hit_pp": round(tr_res["hit_pct"] - ho_res["hit_pct"], 1),
                    })

    df = pd.DataFrame(rows)
    print("=== Forward-walk: multi-horizon vs mag-only sniper ===\n")
    print(df.sort_values(["asset", "tf", "selector", "mag"]).to_string(index=False))
    print("\n=== Cells passing gate (HO hit≥60%, HO ROI≥+10%, drift≤8pp) ===")
    passed = df[(df["ho_hit"] >= 60.0) & (df["ho_roi"] >= 10.0) & (df["drift_hit_pp"].abs() <= 8.0)]
    print(passed.to_string(index=False))
    print(f"\nTotal cells: {len(df)}, passing: {len(passed)}")


if __name__ == "__main__":
    main()
