"""Entry-timing variants — does delaying entry into the window improve hit rate?

Hypothesis: at window_start the price is volatile (post-Polymarket-resolution
flow). Waiting 30-60s lets the book stabilize. We may pay a worse entry but
get better signal-to-noise.

For each market, look at the book trajectory at buckets {0, 3, 6, 9, 12} (i.e.
0s, 30s, 60s, 90s, 120s into the window). Recompute:
  - signal direction = sign(ret_5m_at_that_bucket) -- approximated by holding original ret_5m
    (we don't have intra-window Binance ret here cheaply; using the OG signal as proxy)
  - entry price at bucket B's ask
  - hold to resolution, payoff vs resolution outcome

Output: hit rate / ROI per (asset, tf, entry_delay_bucket, mag_filter).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab.v2_signals.common import load_features, ASSETS, DATA_DIR

NOTIONAL = 25.0
FEE = 0.02


def load_book(asset: str) -> pd.DataFrame:
    p = DATA_DIR / "polymarket" / f"{asset}_book_depth_v3.csv"
    return pd.read_csv(p, usecols=["slug", "bucket_10s", "outcome", "ask_price_0", "bid_price_0"])


def main():
    rows = []
    for asset in ASSETS:
        feats = load_features(asset).dropna(subset=["outcome_up", "ret_5m", "entry_yes_ask", "entry_no_ask"])
        book = load_book(asset)

        for delay_bucket in [0, 3, 6, 9, 12]:  # 0s, 30s, 60s, 90s, 120s
            # Get YES & NO ask at the delay bucket per slug
            sub_b = book[book["bucket_10s"] == delay_bucket]
            yes_ask = sub_b[sub_b["outcome"] == "Up"].set_index("slug")["ask_price_0"]
            no_ask = sub_b[sub_b["outcome"] == "Down"].set_index("slug")["ask_price_0"]

            # Apply magnitude filter q10
            for mag_label, mag_q in [("all", 0.0), ("q20", 0.20), ("q10", 0.10)]:
                fsub = feats.copy()
                if mag_q > 0:
                    thr = fsub["ret_5m"].abs().quantile(1 - mag_q)
                    fsub = fsub[fsub["ret_5m"].abs() >= thr]

                # Predict: sign of ret_5m
                pred_up = fsub["ret_5m"] > 0
                pred_dn = fsub["ret_5m"] < 0

                # Entry price at the delay bucket
                fsub["entry_at_delay"] = np.where(
                    pred_up,
                    fsub["slug"].map(yes_ask),
                    fsub["slug"].map(no_ask),
                )
                valid = fsub[fsub["entry_at_delay"].notna() & (fsub["entry_at_delay"] > 0) & (fsub["entry_at_delay"] < 1)]
                if len(valid) == 0:
                    continue

                actual_up = valid["outcome_up"] == 1
                v_pred_up = valid["ret_5m"] > 0
                hit = ((v_pred_up & actual_up) | (~v_pred_up & ~actual_up))

                cost = valid["entry_at_delay"].values
                shares = NOTIONAL / cost
                payoff = np.where(hit, 1.0 - cost, -cost)
                pnl = shares * payoff
                pnl_after = np.where(pnl > 0, pnl * (1 - FEE), pnl)

                for tf_filter in ("5m", "15m", "ALL"):
                    if tf_filter == "ALL":
                        idx = np.ones(len(valid), dtype=bool)
                    else:
                        idx = (valid["timeframe"] == tf_filter).values
                    if idx.sum() == 0:
                        continue
                    rows.append({
                        "asset": asset,
                        "tf": tf_filter,
                        "delay_s": delay_bucket * 10,
                        "mag": mag_label,
                        "n": int(idx.sum()),
                        "hit_pct": round(hit.values[idx].mean() * 100, 1),
                        "roi_pct": round(pnl_after[idx].sum() / (NOTIONAL * idx.sum()) * 100, 2),
                        "avg_entry_price": round(cost[idx].mean(), 4),
                    })

    df = pd.DataFrame(rows)
    print(f"\n=== Entry timing × mag for sig_ret5m hold-to-resolution ===")
    # Best per (asset, tf, mag)
    print(f"\n--- BTC q10 sweep across delays ---")
    print(df[(df["asset"] == "btc") & (df["mag"] == "q10")].to_string(index=False))
    print(f"\n--- BTC ALL mag, delay sweep ---")
    print(df[(df["asset"] == "btc") & (df["tf"] == "ALL")].to_string(index=False))

    print(f"\n=== Top 20 cells by ROI ===")
    print(df.nlargest(20, "roi_pct").to_string(index=False))


if __name__ == "__main__":
    main()
