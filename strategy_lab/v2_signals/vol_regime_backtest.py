"""A3 Vol-regime conditional sleeves.

Bucket each market by realized vol of BTC over the prior 1h. Test:
  - Does hit rate vary by vol regime?
  - Does the optimal signal/threshold change by regime?
  - Conditional sleeve: signal X in low vol, signal Y in high vol.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR

NOTIONAL = 25.0
FEE = 0.02


def load_btc_klines() -> pd.DataFrame:
    p = DATA_DIR / "binance" / "btc_klines_window.csv"
    k = pd.read_csv(p)
    k = k[k.period_id == "1MIN"].copy()
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    return k.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def compute_realized_vol_1h(features: pd.DataFrame, klines: pd.DataFrame) -> pd.Series:
    """Realized vol of BTC 1m log-returns over the prior 60 min, annualized."""
    closes_idx = klines["ts_s"].values
    closes_vals = klines["price_close"].astype(float).values
    out = np.full(len(features), np.nan, dtype=float)
    for i, ws in enumerate(features["window_start_unix"].values):
        ws = int(ws)
        l = np.searchsorted(closes_idx, ws - 3600)
        r = np.searchsorted(closes_idx, ws)
        if r - l < 30:
            continue
        rets = np.diff(np.log(closes_vals[l:r]))
        if len(rets) > 0:
            out[i] = np.sqrt(np.mean(rets ** 2)) * np.sqrt(525600)  # annualized
    return pd.Series(out, name="vol_1h")


def evaluate_signal(df: pd.DataFrame, predict_col: str, label: str) -> dict:
    n = len(df)
    if n == 0:
        return {}
    pred_up = df[predict_col] > 0
    pred_dn = df[predict_col] < 0
    actual_up = df["outcome_up"] == 1
    hit = ((pred_up & actual_up) | (pred_dn & ~actual_up))
    hits = hit.sum()
    cost = np.where(pred_up, df["entry_yes_ask"], df["entry_no_ask"])
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)
    pnl = shares * payoff
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    total_cost = NOTIONAL * n
    return {
        "label": label,
        "n": n,
        "hit_pct": round(hits / n * 100, 1),
        "total_pnl": round(pnl_after.sum(), 2),
        "roi_pct": round(pnl_after.sum() / total_cost * 100, 2),
    }


def main():
    btc_klines = load_btc_klines()
    rows = []

    for asset in ASSETS:
        feats = load_features(asset).dropna(subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"])
        feats["vol_1h"] = compute_realized_vol_1h(feats, btc_klines).values
        feats = feats.dropna(subset=["vol_1h"])

        # Bucket by vol terciles GLOBAL (so all assets share the same regime definition)
        # Use BTC's vol since alts trade with BTC anyway
        vol_low = feats["vol_1h"].quantile(0.33)
        vol_high = feats["vol_1h"].quantile(0.67)
        feats["vol_bucket"] = pd.cut(
            feats["vol_1h"],
            bins=[-np.inf, vol_low, vol_high, np.inf],
            labels=["low", "med", "high"]
        )

        for tf in ("5m", "15m", "ALL"):
            for vol_bucket in ("low", "med", "high", "ALL"):
                for mag_label, mag_thresh in [("all", 0.0), ("q20", 0.2), ("q10", 0.1)]:
                    sub = feats
                    if tf != "ALL":
                        sub = sub[sub["timeframe"] == tf]
                    if vol_bucket != "ALL":
                        sub = sub[sub["vol_bucket"] == vol_bucket]
                    if mag_thresh > 0:
                        thr = sub["ret_5m"].abs().quantile(1 - mag_thresh)
                        sub = sub[sub["ret_5m"].abs() >= thr]
                    if len(sub) == 0:
                        continue
                    res = evaluate_signal(sub, "ret_5m", f"{asset} {tf} vol={vol_bucket} mag={mag_label}")
                    if res:
                        res.update({
                            "asset": asset, "tf": tf, "vol_bucket": vol_bucket, "mag": mag_label,
                            "vol_lo": round(vol_low, 4), "vol_hi": round(vol_high, 4),
                        })
                        rows.append(res)

    df = pd.DataFrame(rows)
    print(f"\n=== Vol-regime stratification (sig_ret5m direction) ===")
    print("(strongest cells per asset/tf, sorted by ROI)")
    pivot = df[df["asset"] != "ALL"].sort_values("roi_pct", ascending=False).head(30)
    print(pivot[["asset", "tf", "vol_bucket", "mag", "n", "hit_pct", "roi_pct"]].to_string(index=False))

    print(f"\n=== Hit rate by vol bucket (sniper q10, ALL tfs, all assets aggregated) ===")
    aggregated = df[df["mag"] == "q10"].groupby(["vol_bucket"]).agg(
        n=("n", "sum"),
        weighted_hit=("hit_pct", "mean"),
        weighted_roi=("roi_pct", "mean"),
    ).reset_index()
    print(aggregated.to_string(index=False))


if __name__ == "__main__":
    main()
