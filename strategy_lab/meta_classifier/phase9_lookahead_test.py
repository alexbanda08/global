"""Phase 9 lookahead validation.

Concern: poly_tfi_2m is computed from Polymarket trades in [window_start, ws+120s].
For 5m markets that's 40% of the market lifetime — the strong 77.7% top-5% hit
rate may be a self-prediction (Polymarket trade flow in the first 2m mostly
reflects what BTC already did in those same 2m, which the YES/NO settlement
also reflects).

Test: regress outcome_up on [poly_tfi_2m, btc_ret_2m] where btc_ret_2m is
BTC's actual return over the SAME [t, t+120s] window. If poly_tfi_2m's
coefficient survives controlling for btc_ret_2m, it's novel alpha. If it
collapses, Phase 9 is just an indirect BTC-momentum readout.

Outputs:
  strategy_lab/results/meta_classifier/phase9_lookahead_results.csv
  strategy_lab/reports/PHASE9_LOOKAHEAD_VALIDATION.md
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.linear_model import LogisticRegression

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
P9_PARQUET = ROOT / "strategy_lab" / "data" / "meta_classifier" / "btc_trade_flow_v1.parquet"
UNIVERSE = ROOT / "data" / "v4" / "refresh_2026_05_02" / "btc_markets_minimal.csv"
BTC_1M = ROOT / "data" / "v4" / "refresh_2026_05_02" / "binance_spot_1min_full.csv"
OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "phase9_lookahead_results.csv"
REPORT = ROOT / "strategy_lab" / "reports" / "PHASE9_LOOKAHEAD_VALIDATION.md"


def load_btc_1m() -> dict[int, float]:
    """Return dict ts_unix_sec -> price_close. CoinAPI bar at start=t closes at t+60s."""
    df = pd.read_csv(BTC_1M)
    df = df[df["symbol_id"] == "BINANCE_SPOT_BTC_USDT"].copy()
    df["ts"] = (df["time_period_start_us"] // 1_000_000).astype("int64")
    return dict(zip(df["ts"].values, df["price_close"].values))


def attach_btc_return(df: pd.DataFrame, prices: dict[int, float]) -> pd.DataFrame:
    """Add btc_ret_2m = log(close@(ws+120) / close@ws) using 1m bars.
    close@ws = price_close of bar starting at ws-60s.
    close@(ws+120) = price_close of bar starting at ws+60s.
    """
    p0 = []
    p2 = []
    p5 = []
    for ws in df["window_start_unix"].values:
        ws = int(ws)
        p0.append(prices.get(ws - 60))            # close at t=0
        p2.append(prices.get(ws + 60))            # close at t=120s
        p5.append(prices.get(ws + 240))           # close at t=300s (5m)
    df = df.copy()
    df["btc_p0"] = p0
    df["btc_p2"] = p2
    df["btc_p5"] = p5
    df["btc_ret_2m"] = np.log(df["btc_p2"] / df["btc_p0"])
    df["btc_ret_5m"] = np.log(df["btc_p5"] / df["btc_p0"])
    return df


def ols_3coef(y: np.ndarray, X: np.ndarray, names: list[str]) -> dict:
    """OLS with t-stats. y is 0/1 outcome (linear probability model)."""
    Xc = np.column_stack([np.ones(len(X)), X])
    n, k = Xc.shape
    beta, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    yhat = Xc @ beta
    resid = y - yhat
    sigma2 = float(resid @ resid / (n - k))
    XtX_inv = np.linalg.inv(Xc.T @ Xc)
    se = np.sqrt(np.diag(XtX_inv) * sigma2)
    t = beta / se
    # two-sided p via normal approx (n large)
    from scipy.stats import t as tdist
    p = 2 * (1 - tdist.cdf(np.abs(t), df=n - k))
    out = {"n": n, "r2": 1 - resid.var() / y.var()}
    for i, name in enumerate(["intercept"] + names):
        out[f"{name}_coef"] = float(beta[i])
        out[f"{name}_se"] = float(se[i])
        out[f"{name}_t"] = float(t[i])
        out[f"{name}_p"] = float(p[i])
    return out


def logit_fit(y: np.ndarray, X: np.ndarray, names: list[str]) -> dict:
    """Logistic regression with bootstrap SE. Features standardized to z-scores
    so coefficients are comparable across features with different scales."""
    rng = np.random.default_rng(42)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(sd == 0, 1.0, sd)
    Xz = (X - mu) / sd
    lr = LogisticRegression(max_iter=5000, C=1e6, fit_intercept=True, solver="lbfgs").fit(Xz, y)
    coefs_boot = []
    n = len(y)
    for _ in range(500):
        idx = rng.integers(0, n, n)
        try:
            lrb = LogisticRegression(max_iter=2000, C=1e6, fit_intercept=True, solver="lbfgs").fit(Xz[idx], y[idx])
            coefs_boot.append(np.concatenate([[lrb.intercept_[0]], lrb.coef_[0]]))
        except Exception:
            continue
    coefs_boot = np.array(coefs_boot)
    se = coefs_boot.std(axis=0)
    coefs = np.concatenate([[lr.intercept_[0]], lr.coef_[0]])
    z = coefs / np.where(se == 0, 1e-12, se)
    from scipy.stats import norm
    p = 2 * (1 - norm.cdf(np.abs(z)))
    yhat = lr.predict_proba(Xz)[:, 1]
    out = {
        "n": n,
        "logloss": float(-np.mean(y * np.log(yhat + 1e-12) + (1 - y) * np.log(1 - yhat + 1e-12))),
        "_note": "coefficients on standardized features (1 SD change in feature)",
    }
    for i, name in enumerate(["intercept"] + names):
        out[f"{name}_coef"] = float(coefs[i])
        out[f"{name}_se"] = float(se[i])
        out[f"{name}_z"] = float(z[i])
        out[f"{name}_p"] = float(p[i])
    return out


def fmt_ols(res: dict) -> str:
    parts = [f"n={res['n']}, R²={res['r2']:.4f}"]
    for k in res:
        if k.endswith("_coef") and not k.startswith("intercept"):
            name = k[:-5]
            parts.append(f"  {name}: β={res[name+'_coef']:+.4f}  SE={res[name+'_se']:.4f}  t={res[name+'_t']:+.2f}  p={res[name+'_p']:.2e}")
    return "\n".join(parts)


def fmt_logit(res: dict) -> str:
    parts = [f"n={res['n']}, logloss={res['logloss']:.4f}"]
    for k in res:
        if k.endswith("_coef") and not k.startswith("intercept"):
            name = k[:-5]
            parts.append(f"  {name}: β={res[name+'_coef']:+.4f}  SE={res[name+'_se']:.4f}  z={res[name+'_z']:+.2f}  p={res[name+'_p']:.2e}")
    return "\n".join(parts)


def top_pct_analysis(df: pd.DataFrame, label: str) -> str:
    """Hit-rate analysis at top 5% |poly_tfi_2m|, conditional on btc_ret_2m sign."""
    sub = df.dropna(subset=["poly_tfi_2m", "btc_ret_2m", "outcome_up"]).copy()
    if len(sub) < 50:
        return f"\n{label}: n={len(sub)} too small\n"
    thr = sub["poly_tfi_2m"].abs().quantile(0.95)
    fired = sub[sub["poly_tfi_2m"].abs() >= thr].copy()
    pred = (fired["poly_tfi_2m"] > 0).astype(int).values
    truth = fired["outcome_up"].astype(int).values
    hit_overall = (pred == truth).mean()

    # Agreement: predict UP & btc_ret_2m > 0, OR predict DOWN & btc_ret_2m < 0
    btc_pos = fired["btc_ret_2m"].values > 0
    agree = (pred == 1) & btc_pos | (pred == 0) & ~btc_pos
    disagree = ~agree
    n_agree = agree.sum()
    n_dis = disagree.sum()
    hit_agree = (pred[agree] == truth[agree]).mean() if n_agree > 0 else float("nan")
    hit_dis = (pred[disagree] == truth[disagree]).mean() if n_dis > 0 else float("nan")

    # Hit rate of btc_ret_2m sign alone
    btc_pred = (fired["btc_ret_2m"] > 0).astype(int).values
    hit_btc = (btc_pred == truth).mean()

    out = [
        f"\n### Top-5% |poly_tfi_2m| — {label}\n",
        f"- n_fired = {len(fired)}",
        f"- hit (poly_tfi_2m sign): {hit_overall:.1%}",
        f"- hit (btc_ret_2m sign):  {hit_btc:.1%}",
        f"- when both signs agree:  {hit_agree:.1%} (n={n_agree})",
        f"- when signs disagree:    {hit_dis:.1%} (n={n_dis})",
    ]
    if n_agree > 0 and n_dis > 0:
        # If agree=high and disagree~50%, BTC is doing all the work.
        # If both agree and disagree are well above 50%, poly_tfi_2m has independent info.
        if hit_dis < 0.55:
            out.append("  → in the disagreement subset, poly_tfi_2m loses to BTC: poly_tfi_2m alone is near coin-flip when BTC contradicts it")
        else:
            out.append("  → poly_tfi_2m holds up even when BTC disagrees: novel info present")
    return "\n".join(out)


def main():
    print("Loading...")
    p9 = pd.read_parquet(P9_PARQUET)
    uni = pd.read_csv(UNIVERSE)[["slug", "outcome_up"]].dropna()
    uni["outcome_up"] = uni["outcome_up"].astype(int)
    df = p9.merge(uni, on="slug", how="inner")

    prices = load_btc_1m()
    print(f"  P9 features:    {len(p9)}")
    print(f"  with outcome:   {len(df)}")
    print(f"  BTC 1m bars:    {len(prices)}")

    df = attach_btc_return(df, prices)
    df_active = df[df["poly_trade_count_2m"] >= 1].dropna(subset=["btc_ret_2m"]).copy()
    print(f"  active+btc_ok:  {len(df_active)}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df_active.to_csv(OUT_CSV, index=False)
    print(f"  wrote {OUT_CSV}")

    lines = [
        "# Phase 9 — Lookahead Validation\n",
        "_Generated: 2026-05-05_\n",
        "## Hypothesis\n",
        "Phase 9's `poly_tfi_2m` (Polymarket trade-flow imbalance over the first 2 minutes",
        "of the market) showed +53.5% ROI / 77.7% hit on top 5%. For 5m markets, that 2m",
        "window is **40% of the market lifetime**. Concern: `poly_tfi_2m` may mostly reflect",
        "BTC's actual return in those same 2 minutes, which the eventual settlement also",
        "reflects.\n",
        "## Test\n",
        "Add `btc_ret_2m = log(close@t+120s / close@t)` from Binance 1m bars. Then check",
        "whether `poly_tfi_2m`'s coefficient survives controlling for `btc_ret_2m` in a",
        "joint regression on `outcome_up`.\n",
        "## Data\n",
        f"- Phase 9 features: {len(p9)} markets ({(p9['timeframe']=='5m').sum()} 5m, {(p9['timeframe']=='15m').sum()} 15m)",
        f"- After joining outcome + ≥1 trade in 2m + BTC bars present: **{len(df_active)}** markets",
        f"- BTC 1m source: `{BTC_1M.relative_to(ROOT)}` ({len(prices)} bars)\n",
    ]

    # --- Stage 1: correlations ---
    sub = df_active.dropna(subset=["poly_tfi_2m", "btc_ret_2m"])
    pr = sub["poly_tfi_2m"].corr(sub["btc_ret_2m"])
    sr, sp = spearmanr(sub["poly_tfi_2m"], sub["btc_ret_2m"])
    lines += [
        "## 1. Direct correlation: poly_tfi_2m vs btc_ret_2m\n",
        f"- Pearson r:  **{pr:+.4f}**",
        f"- Spearman ρ: {sr:+.4f} (p={sp:.2e})",
        f"- n = {len(sub)}",
    ]
    if abs(pr) < 0.3:
        lines.append("\n→ Weak correlation: `poly_tfi_2m` is **NOT** mechanically tied to BTC return. Phase 9 is largely independent info.\n")
    elif abs(pr) < 0.6:
        lines.append("\n→ Moderate correlation: `poly_tfi_2m` partially reflects BTC, but has its own variation.\n")
    else:
        lines.append("\n→ Strong correlation: `poly_tfi_2m` is **largely** a BTC-momentum proxy. Lookahead concern likely confirmed.\n")

    # --- Stage 2: regressions on full sample ---
    def run_block(d: pd.DataFrame, label: str) -> list[str]:
        d = d.dropna(subset=["poly_tfi_2m", "btc_ret_2m", "outcome_up"]).copy()
        y = d["outcome_up"].astype(int).values
        x_tfi = d[["poly_tfi_2m"]].values
        x_btc = d[["btc_ret_2m"]].values
        x_both = d[["poly_tfi_2m", "btc_ret_2m"]].values

        ols_tfi = ols_3coef(y, x_tfi, ["poly_tfi_2m"])
        ols_btc = ols_3coef(y, x_btc, ["btc_ret_2m"])
        ols_both = ols_3coef(y, x_both, ["poly_tfi_2m", "btc_ret_2m"])

        log_tfi = logit_fit(y, x_tfi, ["poly_tfi_2m"])
        log_btc = logit_fit(y, x_btc, ["btc_ret_2m"])
        log_both = logit_fit(y, x_both, ["poly_tfi_2m", "btc_ret_2m"])

        b = [
            f"\n## Regressions — {label} (n={len(d)})\n",
            "### Linear probability model (OLS on 0/1 outcome)\n",
            "**Univariate poly_tfi_2m:**",
            "```",
            fmt_ols(ols_tfi),
            "```",
            "**Univariate btc_ret_2m:**",
            "```",
            fmt_ols(ols_btc),
            "```",
            "**Joint (CONTROLLING FOR BTC RETURN):**",
            "```",
            fmt_ols(ols_both),
            "```",
            "### Logistic regression\n",
            "**Univariate poly_tfi_2m:**",
            "```",
            fmt_logit(log_tfi),
            "```",
            "**Univariate btc_ret_2m:**",
            "```",
            fmt_logit(log_btc),
            "```",
            "**Joint (CONTROLLING FOR BTC RETURN):**",
            "```",
            fmt_logit(log_both),
            "```",
        ]
        # Verdict per slice
        univ = log_tfi["poly_tfi_2m_coef"]
        joint = log_both["poly_tfi_2m_coef"]
        joint_p = log_both["poly_tfi_2m_p"]
        ratio = joint / univ if univ != 0 else float("nan")
        b.append(f"\n**Coefficient survival**: joint/univariate = {ratio:.2f}× (1.0 = unchanged, 0 = killed by control)")
        b.append(f"**poly_tfi_2m p-value in joint**: {joint_p:.2e}")
        if joint_p < 0.01 and ratio > 0.5:
            b.append("→ **Survives**: poly_tfi_2m has independent predictive power beyond BTC return.")
        elif joint_p < 0.05:
            b.append("→ **Marginal**: poly_tfi_2m loses much of its strength but still has some signal.")
        else:
            b.append("→ **Killed**: poly_tfi_2m is largely a BTC-momentum readout.")
        return b

    lines += run_block(df_active, "ALL active")
    lines += run_block(df_active[df_active["timeframe"] == "5m"], "5m markets only (40% lookahead window)")
    lines += run_block(df_active[df_active["timeframe"] == "15m"], "15m markets only (13% lookahead window)")

    # --- Stage 3: top-5% gate analysis ---
    lines.append("\n## 3. Top-5% gate (the actual deploy threshold)\n")
    lines.append(top_pct_analysis(df_active, "ALL active"))
    lines.append(top_pct_analysis(df_active[df_active["timeframe"] == "5m"], "5m markets"))
    lines.append(top_pct_analysis(df_active[df_active["timeframe"] == "15m"], "15m markets"))

    # --- Final verdict ---
    sub = df_active.dropna(subset=["poly_tfi_2m", "btc_ret_2m", "outcome_up"]).copy()
    y_all = sub["outcome_up"].astype(int).values
    x_both_all = sub[["poly_tfi_2m", "btc_ret_2m"]].values
    log_both_all = logit_fit(y_all, x_both_all, ["poly_tfi_2m", "btc_ret_2m"])

    sub5 = sub[sub["timeframe"] == "5m"]
    sub15 = sub[sub["timeframe"] == "15m"]
    log_5m = logit_fit(sub5["outcome_up"].values, sub5[["poly_tfi_2m", "btc_ret_2m"]].values, ["poly_tfi_2m", "btc_ret_2m"])
    log_15m = logit_fit(sub15["outcome_up"].values, sub15[["poly_tfi_2m", "btc_ret_2m"]].values, ["poly_tfi_2m", "btc_ret_2m"])

    p_all = log_both_all["poly_tfi_2m_p"]
    p_5m = log_5m["poly_tfi_2m_p"]
    p_15m = log_15m["poly_tfi_2m_p"]

    lines += [
        "\n---\n",
        "## VERDICT\n",
        f"| Slice | n | poly_tfi_2m β (joint) | btc_ret_2m β (joint) | p (poly_tfi_2m) |",
        f"|---|---|---|---|---|",
        f"| ALL  | {log_both_all['n']} | {log_both_all['poly_tfi_2m_coef']:+.3f} | {log_both_all['btc_ret_2m_coef']:+.3f} | **{p_all:.2e}** |",
        f"| 5m   | {log_5m['n']} | {log_5m['poly_tfi_2m_coef']:+.3f} | {log_5m['btc_ret_2m_coef']:+.3f} | **{p_5m:.2e}** |",
        f"| 15m  | {log_15m['n']} | {log_15m['poly_tfi_2m_coef']:+.3f} | {log_15m['btc_ret_2m_coef']:+.3f} | **{p_15m:.2e}** |",
        "",
    ]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nWrote report: {REPORT}")
    print(f"poly_tfi_2m p-value (joint, ALL): {p_all:.2e}")
    print(f"poly_tfi_2m p-value (joint, 5m):  {p_5m:.2e}")
    print(f"poly_tfi_2m p-value (joint, 15m): {p_15m:.2e}")
    print(f"Pearson r (poly_tfi_2m, btc_ret_2m): {pr:+.4f}")


if __name__ == "__main__":
    main()
