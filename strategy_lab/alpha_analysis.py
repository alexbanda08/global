"""
Univariate feature importance — information coefficient (IC) of every
feature vs next-bar return, for each symbol.

We also slice by regime (bull/bear) to find conditional alpha.
An |IC| > 0.02 at high bar counts is a real signal; > 0.05 is rare and strong.

Output: strategy_lab/results/alpha_ic.csv  +  printed top-20 table.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

ROOT = Path(__file__).resolve().parent.parent
FEAT_DIR = ROOT / "strategy_lab" / "features"
OUT = ROOT / "strategy_lab" / "results"
OUT.mkdir(parents=True, exist_ok=True)

FEATURE_COLS = [
    "ret_1","ret_4","ret_8",
    "atr_14","realized_vol_24",
    "wick_up_frac","wick_dn_frac",
    "sum_open_interest","sum_open_interest_value",
    "count_toptrader_long_short_ratio","sum_toptrader_long_short_ratio",
    "count_long_short_ratio","sum_taker_long_short_vol_ratio",
    "oi_pct_chg_4","oi_pct_chg_24",
    "taker_ratio_z_7d","top_trader_ls_z_7d",
    "funding_rate","funding_rate_z_30d",
    "premium_1h","premium_z_30d",
    "liq_count","liq_qty","liq_notional_usd","liq_notional_z_7d",
    "regime_bull",
]
TARGETS = ["target_ret_1", "target_ret_4"]


def ic_row(feature: pd.Series, target: pd.Series, label: str) -> dict:
    mask = feature.notna() & target.notna() & np.isfinite(feature) & np.isfinite(target)
    f = feature[mask].values
    t = target[mask].values
    n = len(f)
    if n < 500:
        return {"label": label, "n": n, "pearson": np.nan, "spearman": np.nan, "p_spearman": np.nan}
    try:
        p_r, _ = pearsonr(f, t)
        s_r, s_p = spearmanr(f, t)
    except Exception:
        return {"label": label, "n": n, "pearson": np.nan, "spearman": np.nan, "p_spearman": np.nan}
    return {"label": label, "n": n, "pearson": p_r, "spearman": s_r, "p_spearman": s_p}


def analyze(sym: str) -> pd.DataFrame:
    print(f"\n=== {sym} ===", flush=True)
    df = pd.read_parquet(FEAT_DIR / f"{sym}_15m_features.parquet")
    # Only analyze bars where all required data exists (i.e. after metrics start)
    df = df.dropna(subset=["sum_open_interest","sum_taker_long_short_vol_ratio"], how="any")
    print(f"  usable bars after drop: {len(df):,}")

    rows = []
    for tgt in TARGETS:
        if tgt not in df: continue
        for feat in FEATURE_COLS:
            if feat not in df: continue
            r = ic_row(df[feat], df[tgt], label=f"{feat}__{tgt}")
            r["feature"] = feat; r["target"] = tgt; r["regime"] = "ALL"
            rows.append(r)

        # Conditional slices — regime bull vs bear
        for name, mask in [("BULL", df["regime_bull"] == 1), ("BEAR", df["regime_bull"] == 0)]:
            sub = df[mask]
            if len(sub) < 2000: continue
            for feat in FEATURE_COLS:
                if feat not in sub: continue
                if feat == "regime_bull": continue
                r = ic_row(sub[feat], sub[tgt], label=f"{feat}__{tgt}__{name}")
                r["feature"] = feat; r["target"] = tgt; r["regime"] = name
                rows.append(r)

    df_ic = pd.DataFrame(rows)
    df_ic["abs_spearman"] = df_ic["spearman"].abs()
    return df_ic


def main():
    all_ic = []
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        ic = analyze(sym)
        ic["symbol"] = sym
        all_ic.append(ic)
    df = pd.concat(all_ic, ignore_index=True)
    df = df[["symbol","regime","target","feature","n","pearson","spearman","abs_spearman","p_spearman"]]
    df.to_csv(OUT / "alpha_ic.csv", index=False)

    print("\n\n=== TOP 20 BY |SPEARMAN| (next-bar return, ALL regime) ===")
    all_ = df[(df.regime == "ALL") & (df.target == "target_ret_1")].copy()
    top = all_.sort_values("abs_spearman", ascending=False).head(20)
    print(top.to_string(index=False,
          formatters={"pearson":"{:+.4f}".format, "spearman":"{:+.4f}".format,
                      "abs_spearman":"{:.4f}".format, "p_spearman":"{:.2e}".format}))

    print("\n=== TOP 15 IN BULL REGIME (next-bar return) ===")
    bull = df[(df.regime == "BULL") & (df.target == "target_ret_1")].copy()
    print(bull.sort_values("abs_spearman", ascending=False).head(15).to_string(index=False,
          formatters={"pearson":"{:+.4f}".format, "spearman":"{:+.4f}".format,
                      "abs_spearman":"{:.4f}".format, "p_spearman":"{:.2e}".format}))

    print("\n=== TOP 15 IN BEAR REGIME (next-bar return) ===")
    bear = df[(df.regime == "BEAR") & (df.target == "target_ret_1")].copy()
    print(bear.sort_values("abs_spearman", ascending=False).head(15).to_string(index=False,
          formatters={"pearson":"{:+.4f}".format, "spearman":"{:+.4f}".format,
                      "abs_spearman":"{:.4f}".format, "p_spearman":"{:.2e}".format}))

    print("\n=== TOP 15 BY |SPEARMAN| (4-bar forward return, ALL regime) ===")
    fwd4 = df[(df.regime == "ALL") & (df.target == "target_ret_4")].copy()
    print(fwd4.sort_values("abs_spearman", ascending=False).head(15).to_string(index=False,
          formatters={"pearson":"{:+.4f}".format, "spearman":"{:+.4f}".format,
                      "abs_spearman":"{:.4f}".format, "p_spearman":"{:.2e}".format}))


if __name__ == "__main__":
    sys.exit(main() or 0)
