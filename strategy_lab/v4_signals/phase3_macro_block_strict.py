"""Phase 3 — Stricter macro alignment block.

Cyclops BTC_MACRO_BLOCK: 15m + 30m + 1h + 4h aligned + strength >= 0.50.
Our V3.1 has soft regime filter (±0.5%). Test stricter formulation.

We have ret_5m, ret_15m, ret_1h in features. No ret_4h. Improvise with ret_1h proxy.

Variants tested:
  A: 3-of-3 (5m, 15m, 1h aligned with signal direction)
  B: 3-of-3 + strength: ALL three abs > 0.005 (any TF strongly directional)
  C: 2-of-3 (relaxed)
  D: V3.1 baseline soft regime ±0.5%
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, chronological_split

NOTIONAL = 25.0; FEE = 0.02; SLIP = 0.05

V3_CELLS = {
    "btc_5m_q10":          {"asset": "btc", "tf": "5m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":           {"asset": "eth", "tf": "5m", "mag": 0.05, "selector": "mag_only"},
    "sol_5m_q15_multi":    {"asset": "sol", "tf": "5m", "mag": 0.15, "selector": "multi_horizon"},
}


def evaluate_pnl(df, slip):
    if len(df) == 0: return df.assign(pnl_after=0.0, hit=False)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    cost = np.clip(cost + slip, 0.01, 0.99)
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    out = df.copy()
    out["hit"] = hit
    out["pnl_after"] = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out["direction"] = np.where(pred_up, "UP", "DOWN")
    return out


def macro_filter(df: pd.DataFrame, mode: str, threshold: float = 0.005) -> pd.DataFrame:
    """Apply macro alignment filter. Direction inferred from ret_5m sign."""
    pred_up = df["ret_5m"] > 0
    if mode == "none":
        return df
    if mode == "soft_regime":
        # V3.1 baseline: skip UP if ret_1h < -0.5%; skip DOWN if ret_1h > +0.5%
        ok_up = pred_up & (df["ret_1h"] >= -threshold)
        ok_down = (~pred_up) & (df["ret_1h"] <= threshold)
        return df[ok_up | ok_down]
    if mode == "all_aligned":
        # 3-of-3 (5m + 15m + 1h all same sign as signal)
        same = ((pred_up) & (df["ret_15m"] > 0) & (df["ret_1h"] > 0)) | \
               ((~pred_up) & (df["ret_15m"] < 0) & (df["ret_1h"] < 0))
        return df[same]
    if mode == "all_aligned_strength":
        # 3-of-3 + each abs > threshold
        same = ((pred_up) & (df["ret_15m"] > threshold) & (df["ret_1h"] > threshold)) | \
               ((~pred_up) & (df["ret_15m"] < -threshold) & (df["ret_1h"] < -threshold))
        return df[same]
    if mode == "two_of_three":
        # at least 2 of (15m, 1h) align (5m always aligned by definition)
        sign_15m = np.sign(df["ret_15m"])
        sign_1h = np.sign(df["ret_1h"])
        sign_5m = np.sign(df["ret_5m"])
        agreed = ((sign_15m == sign_5m).astype(int) + (sign_1h == sign_5m).astype(int))
        return df[agreed >= 1]
    raise ValueError(mode)


def run_sleeve(name, cell, macro_mode="none", thr=0.005):
    feats = load_features(cell["asset"]).dropna(
        subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
    )
    feats = feats[feats["timeframe"] == cell["tf"]]
    train, holdout = chronological_split(feats)

    if cell["selector"] == "multi_horizon":
        same_tr = ((train["ret_5m"] > 0) & (train["ret_15m"] > 0) & (train["ret_1h"] > 0)) | \
                  ((train["ret_5m"] < 0) & (train["ret_15m"] < 0) & (train["ret_1h"] < 0))
        same_ho = ((holdout["ret_5m"] > 0) & (holdout["ret_15m"] > 0) & (holdout["ret_1h"] > 0)) | \
                  ((holdout["ret_5m"] < 0) & (holdout["ret_15m"] < 0) & (holdout["ret_1h"] < 0))
        train_f, holdout_f = train[same_tr], holdout[same_ho]
        thr_q = train_f["ret_5m"].abs().quantile(1 - cell["mag"])
    else:
        train_f, holdout_f = train, holdout
        thr_q = train_f["ret_5m"].abs().quantile(1 - cell["mag"])

    train_fired = train_f[train_f["ret_5m"].abs() >= thr_q]
    holdout_fired = holdout_f[holdout_f["ret_5m"].abs() >= thr_q]

    train_fired = macro_filter(train_fired, macro_mode, thr)
    holdout_fired = macro_filter(holdout_fired, macro_mode, thr)

    tr = evaluate_pnl(train_fired, SLIP); tr["split"] = "train"
    ho = evaluate_pnl(holdout_fired, SLIP); ho["split"] = "holdout"
    out = pd.concat([tr, ho], ignore_index=True)
    out["sleeve"] = name
    return out


def summary(df, label):
    n = len(df); hit = df["hit"].mean() if n else 0
    pnl = df["pnl_after"].sum()
    notional = n * NOTIONAL
    roi = pnl / notional * 100 if notional else 0
    return f"{label:<28} n={n:>4d} hit={hit*100:5.1f}% pnl=${pnl:>+8.2f} roi={roi:+6.2f}%"


def main():
    variants = [
        ("none (V3 baseline)",                   "none",                  0.0),
        ("V3.1 soft_regime ±0.5%",               "soft_regime",           0.005),
        ("Strict ±0.2%",                          "soft_regime",           0.002),
        ("3-of-3 aligned (any strength)",        "all_aligned",           0.0),
        ("3-of-3 aligned + strength 0.005",      "all_aligned_strength",  0.005),
        ("3-of-3 aligned + strength 0.002",      "all_aligned_strength",  0.002),
        ("2-of-3 relaxed",                        "two_of_three",          0.0),
    ]
    for label, mode, thr in variants:
        print(f"\n{'='*78}")
        print(f"{label}  (NOTIONAL=${NOTIONAL}, slip={SLIP*100}pp)")
        print(f"{'='*78}")
        all_rows = []
        for name, cell in V3_CELLS.items():
            d = run_sleeve(name, cell, mode, thr)
            all_rows.append(d)
            ho = d[d["split"] == "holdout"]
            print(f"  {summary(ho, name + ' [HO]')}")
        combined = pd.concat(all_rows, ignore_index=True)
        ho_c = combined[combined["split"] == "holdout"]
        tr_c = combined[combined["split"] == "train"]
        print(f"  --- COMBINED ---")
        print(f"  {summary(tr_c, 'PORTFOLIO [TRAIN]')}")
        print(f"  {summary(ho_c, 'PORTFOLIO [HO]')}")


if __name__ == "__main__":
    main()
