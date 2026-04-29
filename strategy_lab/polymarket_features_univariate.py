"""
polymarket_features_univariate.py — Test each feature's predictive power
on outcome_up.

For each feature × timeframe (5m, 15m):
  1. Sign test: bet UP if feature > 0, hit rate vs 50%/53% break-even
  2. Decile test: hit rate of betting UP in top decile vs bottom decile
  3. Correlation: pearson(feature, outcome_up)

Output: reports/POLYMARKET_FEATURES_UNIVARIATE.md sorted by abs(top-bottom).
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
FEATS = HERE / "data" / "polymarket" / "btc_features_v3.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_FEATURES_UNIVARIATE.md"

FEATURES = [
    "ret_5m", "ret_15m", "ret_1h",
    "oi_delta_5m", "oi_delta_15m", "oi_delta_1h", "oiv_delta_5m",
    "ls_count", "ls_count_delta_5m",
    "ls_top_count", "ls_top_sum", "smart_minus_retail",
    "taker_ratio", "taker_delta_5m",
    "book_skew",
]


def sign_test(feat: pd.Series, y: pd.Series) -> dict:
    """Bet UP if feat > 0, DOWN if feat < 0. Skip feat == 0."""
    mask = feat.notna() & (feat != 0)
    f = feat[mask]
    yy = y[mask]
    pred_up = (f > 0).astype(int)
    hit = (pred_up == yy).mean()
    n = len(f)
    se = np.sqrt(0.25 / n) if n > 0 else float("nan")
    z = (hit - 0.5) / se if n > 0 else 0
    return {"sign_n": n, "sign_hit": hit, "sign_z": z}


def decile_test(feat: pd.Series, y: pd.Series, q: float = 0.2) -> dict:
    """Top q vs bottom q quintile/decile, hit rate of betting UP in top."""
    mask = feat.notna()
    f = feat[mask]
    yy = y[mask]
    if len(f) < 50:
        return {"top_n": 0, "top_hit": float("nan"),
                "bot_n": 0, "bot_hit": float("nan"),
                "spread": float("nan")}
    hi_thresh = f.quantile(1 - q)
    lo_thresh = f.quantile(q)
    top_mask = f >= hi_thresh
    bot_mask = f <= lo_thresh
    # In top quintile, bet UP. Hit if outcome=UP.
    top_hit = yy[top_mask].mean()
    # In bottom quintile, bet DOWN. Hit if outcome=DOWN, i.e. (1 - mean(yy[bot]))
    bot_hit = 1.0 - yy[bot_mask].mean()
    return {
        "top_n": int(top_mask.sum()),
        "top_hit": float(top_hit),
        "bot_n": int(bot_mask.sum()),
        "bot_hit": float(bot_hit),
        "spread": float((top_hit - (1 - bot_hit))),
    }


def correlation(feat: pd.Series, y: pd.Series) -> dict:
    mask = feat.notna()
    if mask.sum() < 50:
        return {"corr": float("nan"), "p": float("nan")}
    r, p = stats.pointbiserialr(y[mask], feat[mask])
    return {"corr": float(r), "p": float(p)}


def analyze(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    sub = df[df.timeframe == tf]
    y = sub.outcome_up
    rows = []
    for col in FEATURES:
        if col not in sub.columns:
            continue
        feat = sub[col]
        r = {"feature": col, **sign_test(feat, y), **decile_test(feat, y), **correlation(feat, y)}
        rows.append(r)
    return pd.DataFrame(rows).sort_values("top_hit", ascending=False)


def fmt_table(df: pd.DataFrame, tf: str) -> str:
    lines = [
        f"\n## {tf} — features sorted by top-quintile hit rate (n={int(df.iloc[0].top_n) if len(df)>0 else 0} per quintile)\n",
        "| Feature | Sign-test n | Sign hit% | Top-Q hit% | Bot-Q hit% (DOWN) | Pearson r | p |",
        "|---|---|---|---|---|---|---|"
    ]
    for _, r in df.iterrows():
        lines.append(
            f"| {r['feature']} | {int(r['sign_n'])} | "
            f"{r['sign_hit']*100:5.1f} | "
            f"{r['top_hit']*100:5.1f} | "
            f"{r['bot_hit']*100:5.1f} | "
            f"{r['corr']:+.3f} | {r['p']:.3f} |"
        )
    return "\n".join(lines)


def main():
    df = pd.read_csv(FEATS)
    md = ["# Univariate Feature Analysis — BTC Up/Down (Apr 22-27)\n",
          f"Sample: {len(df)} markets ({(df.timeframe=='5m').sum()}× 5m + "
          f"{(df.timeframe=='15m').sum()}× 15m).\n",
          "Break-even hit rate ≈ **53%** (fees + spread). "
          "Sign-test z>2 ≈ 5% significance. Top-quintile = top 20% by feature value, "
          "we'd bet UP. Bot-quintile flipped to DOWN-betting hit rate.\n"]
    for tf in ["5m", "15m"]:
        out = analyze(df, tf)
        md.append(fmt_table(out, tf))
        print(f"\n{tf} — top 5 features by top-quintile hit%:")
        print(out.head(8)[["feature","top_n","top_hit","bot_hit","corr","p"]].to_string(index=False))
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
