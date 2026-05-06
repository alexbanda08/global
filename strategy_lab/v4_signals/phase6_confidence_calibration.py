"""Phase 6 — Confidence calibration via Platt scaling.

Cyclops formulation:
  predicted_p = our model's claimed probability of UP
  actual_WR = realized win rate within prediction bucket
  Fit: actual_WR = a * predicted_p + b
  Bound: a in [0.5, 2.0], b in [-0.15, 0.15]
  Recalibrate every N trades.

For our V3:
  predicted_p = derived from (signal_strength_ratio, magnitude direction).
  We map fire decision to a soft probability:
    p_up = 0.5 + 0.5 * tanh(2 * (signal_ratio - 1.0))   if pred_up
    p_up = 1 - that                                        if pred_down

Then bucket by p_up, compute realized hit rate, fit Platt coefs.

This file produces the calibration table — used at runtime to adjust the
model's confidence output. If model says 70% but actual is 55%, downweight.
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from pathlib import Path
from strategy_lab.v2_signals.common import load_features, chronological_split

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "v4" / "calibration"
OUT.mkdir(parents=True, exist_ok=True)

V3_CELLS = {
    "btc_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}

BUCKETS = [(0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70),
           (0.70, 0.75), (0.75, 0.80), (0.80, 0.85), (0.85, 1.00)]
MIN_TRADES_PER_BUCKET = 5


def signal_to_prob(signal_ratio: np.ndarray, pred_up: np.ndarray) -> np.ndarray:
    """Map signal strength to predicted probability of UP outcome.
    Conservative: scales with how far above threshold the magnitude is.
    """
    p_correct = 0.5 + 0.5 * np.tanh(1.5 * (signal_ratio - 1.0))
    p_correct = np.clip(p_correct, 0.50, 0.92)
    return np.where(pred_up, p_correct, 1 - p_correct)


def collect_predictions(name: str, cell: dict) -> pd.DataFrame:
    feats = load_features(cell["asset"]).dropna(
        subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
    )
    feats = feats[feats["timeframe"] == cell["tf"]]
    train, holdout = chronological_split(feats)

    if cell["selector"] == "multi_horizon":
        same = ((feats["ret_5m"] > 0) & (feats["ret_15m"] > 0) & (feats["ret_1h"] > 0)) | \
               ((feats["ret_5m"] < 0) & (feats["ret_15m"] < 0) & (feats["ret_1h"] < 0))
        full_f = feats[same]
        thr = train[((train["ret_5m"] > 0) & (train["ret_15m"] > 0) & (train["ret_1h"] > 0)) | \
                    ((train["ret_5m"] < 0) & (train["ret_15m"] < 0) & (train["ret_1h"] < 0))]["ret_5m"].abs().quantile(1 - cell["mag"])
    else:
        full_f = feats
        thr = train["ret_5m"].abs().quantile(1 - cell["mag"])

    fired = full_f[full_f["ret_5m"].abs() >= thr].copy()
    fired["signal_ratio"] = fired["ret_5m"].abs() / thr
    fired["pred_up"] = fired["ret_5m"] > 0
    fired["predicted_p_up"] = signal_to_prob(
        fired["signal_ratio"].to_numpy(), fired["pred_up"].to_numpy()
    )
    fired["sleeve"] = name
    return fired


def fit_platt(predicted: np.ndarray, actual: np.ndarray) -> tuple[float, float, dict]:
    """Weighted linear regression: actual_WR ~ a * predicted + b. Returns (a, b, diagnostics)."""
    bucket_data = []
    for lo, hi in BUCKETS:
        mask = (predicted >= lo) & (predicted < hi)
        if mask.sum() < MIN_TRADES_PER_BUCKET:
            continue
        p_mid = (lo + hi) / 2.0
        a_realized = actual[mask].mean()
        n = mask.sum()
        bucket_data.append({"p_mid": p_mid, "actual": a_realized, "n": n})
    if len(bucket_data) < 3:
        return 1.0, 0.0, {"error": "insufficient buckets", "n_buckets": len(bucket_data)}

    df = pd.DataFrame(bucket_data)
    weights = df["n"] / df["n"].sum()
    x_mean = (weights * df["p_mid"]).sum()
    y_mean = (weights * df["actual"]).sum()
    cov = (weights * (df["p_mid"] - x_mean) * (df["actual"] - y_mean)).sum()
    var = (weights * (df["p_mid"] - x_mean) ** 2).sum()

    a = float(np.clip(cov / var, 0.5, 2.0)) if var > 1e-9 else 1.0
    b = float(np.clip(y_mean - a * x_mean, -0.15, 0.15))

    diag = {
        "buckets": bucket_data,
        "a": a, "b": b, "var": float(var), "cov": float(cov),
        "x_mean": float(x_mean), "y_mean": float(y_mean),
        "n_total": int(df["n"].sum()),
    }
    return a, b, diag


def main():
    all_preds = []
    for name, cell in V3_CELLS.items():
        df = collect_predictions(name, cell)
        all_preds.append(df)

    combined = pd.concat(all_preds, ignore_index=True)
    print(f"Collected {len(combined)} V3 fires across 3 sleeves\n")

    # Per-sleeve calibration
    out_table = {}
    for name, cell in V3_CELLS.items():
        sub = combined[combined["sleeve"] == name]
        # actual outcome from fire's perspective: did pred_up match outcome_up?
        sub_arr_pred = sub["predicted_p_up"].to_numpy()
        sub_arr_actual = sub["outcome_up"].to_numpy()  # actual UP rate
        a, b, diag = fit_platt(sub_arr_pred, sub_arr_actual)
        print(f"== {name} ==")
        print(f"  n={len(sub)}  Platt fit: actual = {a:.3f} * predicted + {b:+.4f}")
        for bd in diag.get("buckets", []):
            print(f"    bucket [{bd['p_mid']:.3f}]: n={bd['n']:>3d}  actual_WR={bd['actual']:.3f}")
        out_table[name] = {"a": a, "b": b, "n": len(sub),
                           "buckets": diag.get("buckets", [])}

    # Pooled calibration
    all_pred = combined["predicted_p_up"].to_numpy()
    all_actual = combined["outcome_up"].to_numpy()
    a_p, b_p, diag_p = fit_platt(all_pred, all_actual)
    print(f"\n== POOLED ==")
    print(f"  n={len(combined)}  Platt fit: actual = {a_p:.3f} * predicted + {b_p:+.4f}")
    for bd in diag_p.get("buckets", []):
        print(f"    bucket [{bd['p_mid']:.3f}]: n={bd['n']:>3d}  actual_WR={bd['actual']:.3f}")
    out_table["pooled"] = {"a": a_p, "b": b_p, "n": len(combined),
                           "buckets": diag_p.get("buckets", [])}

    # Save
    cal_path = OUT / "platt_v1.json"
    cal_path.write_text(json.dumps(out_table, indent=2, default=float))
    print(f"\nSaved -> {cal_path.relative_to(ROOT)}")
    print("\nUsage at runtime: corrected_p = a * raw_p + b, clipped to [0.50, 0.99]")


if __name__ == "__main__":
    main()
