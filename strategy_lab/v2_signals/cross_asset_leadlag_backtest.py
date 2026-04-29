"""A2 Cross-asset lead-lag.

Hypothesis: BTC moves lead ETH/SOL on seconds-to-minutes horizons. For each
ETH/SOL UpDown market, predict the outcome from BTC's ret_5m at window_start
(NOT the alt's own ret_5m). If BTC is a leading indicator, hit rate > 50%
on alt markets.

Stratify by:
  - BTC ret_5m magnitude (q10/q20/all)
  - timeframe (5m / 15m)

Compare to baselines:
  - alt's own ret_5m sign  (the existing sig_ret5m)
  - random 50/50

Output: per-cell hit rate / ROI / sample size.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results" / "polymarket"

NOTIONAL = 25.0
FEE = 0.02  # 2% on profit (existing engines' convention)


def load_btc_klines_1m() -> pd.DataFrame:
    p = DATA_DIR / "binance" / "btc_klines_window.csv"
    k = pd.read_csv(p)
    k = k[k.period_id == "1MIN"].copy()
    k["ts_s"] = (k.time_period_start_us // 1_000_000).astype(int)
    return k.sort_values("ts_s").reset_index(drop=True)[["ts_s", "price_close"]]


def compute_btc_ret_5m(features: pd.DataFrame, btc_klines: pd.DataFrame) -> pd.Series:
    """For each market window_start_unix, compute BTC ret_5m = ln(close_t / close_{t-300})."""
    closes_idx = btc_klines["ts_s"].values
    closes_vals = btc_klines["price_close"].astype(float).values
    out = np.full(len(features), np.nan, dtype=float)
    for i, ws in enumerate(features["window_start_unix"].values):
        ws = int(ws)
        r = np.searchsorted(closes_idx, ws)
        l = np.searchsorted(closes_idx, ws - 300)
        if r > 0 and l > 0:
            r_idx = r - 1
            l_idx = l - 1
            if 0 <= l_idx < len(closes_vals) and 0 <= r_idx < len(closes_vals):
                c_now = closes_vals[r_idx]
                c_prior = closes_vals[l_idx]
                if c_now > 0 and c_prior > 0:
                    out[i] = np.log(c_now / c_prior)
    return pd.Series(out, name="btc_ret_5m")


def evaluate(df: pd.DataFrame, label: str) -> dict:
    n = len(df)
    if n == 0 or "predicted_up" not in df.columns:
        return {}
    actual_up = df["outcome_up"] == 1
    pred_up = df["predicted_up"] == 1
    pred_dn = df["predicted_up"] == 0
    hit = ((pred_up & actual_up) | (pred_dn & ~actual_up))
    hits = hit.sum()
    # Approximate ROI per market: bet $25 at entry_yes_ask if pred up, entry_no_ask if pred down
    ent_up = df["entry_yes_ask"]
    ent_dn = df["entry_no_ask"]
    cost = np.where(pred_up, ent_up, ent_dn)  # cost per share
    shares = NOTIONAL / cost
    payoff = np.where(hit, 1.0 - cost, -cost)  # net per share
    pnl = shares * payoff
    # Apply 2% fee on positive PnL only
    pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)
    pnl_total = pnl_after.sum()
    cost_total = (NOTIONAL * np.ones(len(df))).sum()
    return {
        "label": label,
        "n": n,
        "hits": hits,
        "hit_pct": round(hits / n * 100, 1),
        "total_pnl": round(pnl_total, 2),
        "roi_pct": round(pnl_total / cost_total * 100, 2),
        "avg_pnl": round(pnl_total / n, 2),
    }


def main():
    btc_klines = load_btc_klines_1m()

    # For each non-BTC asset, compute BTC's ret_5m at the alt's window_start
    rows = []
    for alt in ("eth", "sol"):
        feats = load_features(alt)
        feats = feats.dropna(subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"])
        feats["btc_ret_5m"] = compute_btc_ret_5m(feats, btc_klines).values
        feats = feats.dropna(subset=["btc_ret_5m"]).copy()

        # === Strategy 1: predict from BTC ret_5m sign ===
        feats_btc = feats.copy()
        feats_btc["predicted_up"] = (feats_btc["btc_ret_5m"] > 0).astype(int)
        # Filter when BTC didn't move
        feats_btc = feats_btc[feats_btc["btc_ret_5m"] != 0]

        # === Strategy 2: predict from alt's own ret_5m sign (baseline) ===
        feats_own = feats.copy()
        feats_own["predicted_up"] = (feats_own["ret_5m"] > 0).astype(int)

        # === Strategy 3: only fire when BTC AND own agree ===
        feats_agree = feats.copy()
        same_sign = (feats_agree["btc_ret_5m"] * feats_agree["ret_5m"]) > 0
        feats_agree = feats_agree[same_sign].copy()
        feats_agree["predicted_up"] = (feats_agree["ret_5m"] > 0).astype(int)

        for tf in ("5m", "15m", "ALL"):
            for label_strategy, src in [
                ("BTC-leader", feats_btc),
                ("own-ret5m", feats_own),
                ("BTC-and-own-agree", feats_agree),
            ]:
                sub = src
                if tf != "ALL":
                    sub = sub[sub["timeframe"] == tf]
                # Magnitude buckets
                for mag_label, mag_filter in [
                    ("all", None),
                    ("q20", lambda d: d[d["btc_ret_5m"].abs() >= d["btc_ret_5m"].abs().quantile(0.80)]),
                    ("q10", lambda d: d[d["btc_ret_5m"].abs() >= d["btc_ret_5m"].abs().quantile(0.90)]),
                ]:
                    sub_m = sub if mag_filter is None else mag_filter(sub)
                    res = evaluate(sub_m, f"{alt} {tf} {mag_label} {label_strategy}")
                    if res:
                        res.update({"asset": alt, "tf": tf, "mag": mag_label, "strategy": label_strategy})
                        rows.append(res)

    df = pd.DataFrame(rows)
    out = RESULTS / "cross_asset_leadlag_backtest.csv"
    df.to_csv(out, index=False)
    print(f"Wrote {out}")
    print(f"\n=== Cross-asset results ===")
    print(df.to_string(index=False))
    print(f"\n=== Top 15 by ROI ===")
    print(df.nlargest(15, "roi_pct").to_string(index=False))


if __name__ == "__main__":
    main()
