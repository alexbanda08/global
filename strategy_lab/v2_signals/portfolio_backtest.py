"""Portfolio combination — best per-asset cells in parallel sleeves.

Per asset, pick the forward-walk-validated cell from sig_search results:
  BTC: 5m mag_only q10
  ETH: 5m mag_only q5
  SOL: 5m mag_only q15

Combine into 3 sleeves running in parallel. Compute:
  - Combined daily PnL (sum of sleeve PnLs per resolution-day)
  - Combined hit rate (markets where SOMEONE in the portfolio fired)
  - Combined Sharpe / max DD
  - Per-sleeve contribution
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, chronological_split

NOTIONAL = 25.0
FEE = 0.02

# Per-asset best cells from forward_walk results
# Multi-sleeve: each (asset, tf) is its own sleeve
BEST_CELLS = {
    "btc_5m":     {"asset": "btc", "tf": "5m",  "mag": 0.10, "selector": "mag_only"},
    "btc_15m":    {"asset": "btc", "tf": "15m", "mag": 0.10, "selector": "mag_only"},
    "eth_5m_q5":  {"asset": "eth", "tf": "5m",  "mag": 0.05, "selector": "mag_only"},
    "eth_5m_mh5": {"asset": "eth", "tf": "5m",  "mag": 0.05, "selector": "multi_horizon"},
    "eth_15m":    {"asset": "eth", "tf": "15m", "mag": 0.20, "selector": "mag_only"},
    "sol_5m":     {"asset": "sol", "tf": "5m",  "mag": 0.15, "selector": "mag_only"},
    "sol_5m_mh":  {"asset": "sol", "tf": "5m",  "mag": 0.15, "selector": "multi_horizon"},
    "sol_15m":    {"asset": "sol", "tf": "15m", "mag": 0.20, "selector": "mag_only"},
}


def apply_filter(df, mag, selector):
    if selector == "multi_horizon":
        same = ((df["ret_5m"] > 0) & (df["ret_15m"] > 0) & (df["ret_1h"] > 0)) | \
               ((df["ret_5m"] < 0) & (df["ret_15m"] < 0) & (df["ret_1h"] < 0))
        df = df[same]
    if mag > 0 and len(df) > 0:
        thr = df["ret_5m"].abs().quantile(1 - mag)
        df = df[df["ret_5m"].abs() >= thr]
    return df


def evaluate_pnl(df):
    if len(df) == 0:
        return df.assign(pnl_after=0.0)
    pred_up = df["ret_5m"] > 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (~pred_up & ~actual_up))
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    out = df.copy()
    out["hit"] = hit
    out["pnl_after"] = pnl_after
    return out


def run_per_asset_sleeve(asset, cell):
    feats = load_features(asset).dropna(
        subset=["outcome_up", "ret_5m", "ret_15m", "ret_1h", "entry_yes_ask", "entry_no_ask"]
    )
    feats = feats[feats["timeframe"] == cell["tf"]] if cell["tf"] != "ALL" else feats
    if len(feats) == 0:
        return pd.DataFrame()
    train, holdout = chronological_split(feats)
    # Filter on train's threshold to avoid look-ahead
    if cell["selector"] == "multi_horizon":
        same_tr = ((train["ret_5m"] > 0) & (train["ret_15m"] > 0) & (train["ret_1h"] > 0)) | \
                  ((train["ret_5m"] < 0) & (train["ret_15m"] < 0) & (train["ret_1h"] < 0))
        train_mh = train[same_tr]
        thr = train_mh["ret_5m"].abs().quantile(1 - cell["mag"])
    else:
        thr = train["ret_5m"].abs().quantile(1 - cell["mag"])

    # Apply same filter to both
    if cell["selector"] == "multi_horizon":
        same_full = lambda d: ((d["ret_5m"] > 0) & (d["ret_15m"] > 0) & (d["ret_1h"] > 0)) | \
                              ((d["ret_5m"] < 0) & (d["ret_15m"] < 0) & (d["ret_1h"] < 0))
        train_f = train[same_full(train)]
        holdout_f = holdout[same_full(holdout)]
    else:
        train_f = train
        holdout_f = holdout

    train_filtered = train_f[train_f["ret_5m"].abs() >= thr]
    holdout_filtered = holdout_f[holdout_f["ret_5m"].abs() >= thr]

    train_eval = evaluate_pnl(train_filtered)
    holdout_eval = evaluate_pnl(holdout_filtered)
    train_eval["sleeve"] = asset
    train_eval["split"] = "train"
    holdout_eval["sleeve"] = asset
    holdout_eval["split"] = "holdout"
    return pd.concat([train_eval, holdout_eval], ignore_index=True)


def main():
    sleeves = []
    for sleeve_name, cell in BEST_CELLS.items():
        sl = run_per_asset_sleeve(cell["asset"], cell)
        if not sl.empty:
            sl = sl.copy()
            sl["sleeve"] = sleeve_name
            sleeves.append(sl)
    full = pd.concat(sleeves, ignore_index=True)
    full["window_start_dt"] = pd.to_datetime(full["window_start_unix"], unit="s")

    print("=== Per-sleeve summary (train | holdout) ===")
    for split in ["train", "holdout"]:
        print(f"\n--- {split} ---")
        s = full[full["split"] == split].groupby("sleeve").agg(
            n=("pnl_after", "count"),
            hit_pct=("hit", lambda x: round(x.sum() / len(x) * 100, 1) if len(x) else 0),
            total_pnl=("pnl_after", "sum"),
            roi_pct=("pnl_after", lambda p: round(p.sum() / (NOTIONAL * len(p)) * 100, 2) if len(p) else 0),
        ).reset_index()
        print(s.to_string(index=False))

    print("\n=== Combined portfolio (sum across sleeves) ===")
    for split in ["train", "holdout"]:
        sub = full[full["split"] == split]
        n = len(sub)
        if n == 0:
            continue
        total = sub["pnl_after"].sum()
        cost = NOTIONAL * n
        # Daily aggregation
        sub2 = sub.copy()
        sub2["day"] = sub2["window_start_dt"].dt.date
        daily = sub2.groupby("day")["pnl_after"].sum()
        sharpe = daily.mean() / daily.std() * np.sqrt(252) if daily.std() > 0 else 0
        cum = daily.cumsum()
        max_dd = (cum - cum.cummax()).min()
        print(f"\n{split}: n={n}, total_pnl=${total:.2f}, cost=${cost:.0f}, "
              f"ROI={total/cost*100:.2f}%, daily_sharpe={sharpe:.2f}, max_dd=${max_dd:.2f}")
        print(f"  daily PnL: mean=${daily.mean():.2f}, std=${daily.std():.2f}, "
              f"days={len(daily)}, neg_days={(daily < 0).sum()}")


if __name__ == "__main__":
    main()
