"""
W3 discovery-strategy builder.

For each (asset, TF), take the top-3 features from W3_feature_importance.csv,
build a simple z-score-threshold trigger strategy, backtest with hl_engine,
and apply G1-G6 validation:

  G1 = n >= 30 trades and p-value < 0.05 on win rate vs base rate
  G3 = total_pnl > 0
  G4 = label-shuffle baseline (already done in W3_train_ml.py)
  G6 = Monte Carlo bootstrap — resample with replacement 1000 times, report
       fraction of bootstrap means > 0

Discovery rule:
  z_score = (feature - rolling_mean_30d) / rolling_std_30d
  LONG when z > +1.5
  SHORT when z < -1.5
  Exit: time_stop after `hold_bars` bars (e.g., 3 bars for 1h, 12 for 5m)

Outputs:
  W3_discovery_strategies.csv      — per (asset, TF, feature) backtest result
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

from scipy import stats as sps

REPO = Path(__file__).resolve().parents[3]
PANELS_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "panels"
OUT_DIR = REPO / "strategy_lab" / "hl_research_2026_05_26" / "wave2"
FUNDING_DIR = REPO / "data" / "hyperliquid" / "funding"

sys.path.insert(0, str(REPO))
from strategy_lab.hl_research_2026_05_26.hl_engine import (
    HyperliquidConfig, run_backtest,
)

ASSETS = ["BTC", "ETH", "SOL"]
TFS = ["5m", "15m", "1h", "4h"]

TF_BAR_US = {
    "5m": 5 * 60 * 1_000_000,
    "15m": 15 * 60 * 1_000_000,
    "1h": 3600 * 1_000_000,
    "4h": 4 * 3600 * 1_000_000,
}
# Rolling-window length for z-score (~30 days worth of bars)
TF_ROLLWIN = {"5m": 30 * 24 * 12, "15m": 30 * 24 * 4, "1h": 30 * 24, "4h": 30 * 6}
# Hold horizon in bars (~12h for 5m, ~12h for 15m, 3h for 1h, 4h for 4h)
TF_HOLDBARS = {"5m": 12 * 12, "15m": 12 * 4, "1h": 3, "4h": 1}


def load_funding(asset: str) -> pd.DataFrame:
    """Load HL funding parquet for an asset. Returns empty df if missing."""
    pq = FUNDING_DIR / f"{asset}_funding.parquet"
    if not pq.exists():
        # Return synthetic empty
        return pd.DataFrame(columns=["funding_rate", "funding_time_us"])
    f = pd.read_parquet(pq)
    if f.index.name is None and not isinstance(f.index, pd.DatetimeIndex):
        f.index = pd.to_datetime(f.index, utc=True)
    return f


def klines_from_panel(df: pd.DataFrame) -> pd.DataFrame:
    """Extract klines (open_time, OHLCV) for the engine."""
    kl = df[["open_time", "open", "high", "low", "close", "volume"]].copy()
    # convert open_time to us
    ts = pd.to_datetime(kl["open_time"], utc=True)
    kl["open_time_us"] = (ts.astype("int64") // 1_000).astype("int64")
    return kl.sort_values("open_time_us").reset_index(drop=True)


def build_zscore_signals(
    df: pd.DataFrame, feature: str, tf: str,
    z_long: float = +1.5, z_short: float = -1.5,
    hold_bars: int | None = None,
    sign: int = +1,
) -> pd.DataFrame:
    """Generate LONG/SHORT signals when z-score breaches threshold.

    `sign=+1` (momentum/trend-follow): z>+1.5 → LONG, z<-1.5 → SHORT.
    `sign=-1` (mean-reversion/fade)  : z>+1.5 → SHORT, z<-1.5 → LONG.

    Returns df with columns signal_us, direction, exit_us.
    """
    if feature not in df.columns:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])
    if hold_bars is None:
        hold_bars = TF_HOLDBARS[tf]
    bar_us = TF_BAR_US[tf]
    rollwin = TF_ROLLWIN[tf]

    x = df[feature].astype(float)
    if x.isna().mean() > 0.5:
        return pd.DataFrame(columns=["signal_us", "direction", "exit_us"])

    mu = x.rolling(rollwin, min_periods=max(50, rollwin // 4)).mean()
    sd = x.rolling(rollwin, min_periods=max(50, rollwin // 4)).std()
    z = (x - mu) / sd.replace(0, np.nan)

    ts = pd.to_datetime(df["open_time"], utc=True)
    us = (ts.astype("int64") // 1_000).astype("int64").to_numpy()

    long_mask = (z > z_long).to_numpy()
    short_mask = (z < z_short).to_numpy()

    long_dir = "LONG" if sign > 0 else "SHORT"
    short_dir = "SHORT" if sign > 0 else "LONG"

    signals: list[dict] = []
    for i, (lm, sm) in enumerate(zip(long_mask, short_mask)):
        if lm:
            signals.append({
                "signal_us": int(us[i]), "direction": long_dir,
                "exit_us": int(us[i]) + hold_bars * bar_us,
            })
        elif sm:
            signals.append({
                "signal_us": int(us[i]), "direction": short_dir,
                "exit_us": int(us[i]) + hold_bars * bar_us,
            })
    return pd.DataFrame(signals)


def g1_pvalue(n_wins: int, n_trades: int, base_rate: float = 0.5) -> float:
    """Two-sided binomial test: are wins different from base_rate?"""
    if n_trades < 1:
        return float("nan")
    return float(sps.binomtest(n_wins, n_trades, p=base_rate).pvalue)


def g6_bootstrap_pnl(trades_pnl: np.ndarray, n_resamples: int = 1000,
                     rng_seed: int = 42) -> tuple[float, float, float]:
    """Monte Carlo bootstrap of mean PnL. Returns (frac_positive, ci_lo, ci_hi)."""
    n = len(trades_pnl)
    if n < 10:
        return float("nan"), float("nan"), float("nan")
    rng = np.random.default_rng(rng_seed)
    boot_means = np.empty(n_resamples)
    for k in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        boot_means[k] = trades_pnl[idx].mean()
    frac_pos = float((boot_means > 0).mean())
    ci_lo = float(np.quantile(boot_means, 0.025))
    ci_hi = float(np.quantile(boot_means, 0.975))
    return frac_pos, ci_lo, ci_hi


def run_discovery(asset: str, tf: str, top_features: list[str]) -> list[dict]:
    """Backtest z-score triggers for each of top_features. Tests BOTH momentum
    (sign=+1) and mean-reversion (sign=-1); keeps the better-performing one.
    Returns list of result dicts."""
    pq = PANELS_DIR / f"hl_panel_{asset}_{tf}.parquet"
    if not pq.exists():
        return []
    df = pd.read_parquet(pq).sort_values("open_time").reset_index(drop=True)

    # Trim to last 3 years to keep test fast and out-of-distribution recent
    cutoff = df["open_time"].max() - pd.DateOffset(years=3)
    df = df.loc[df["open_time"] >= cutoff].reset_index(drop=True)

    klines = klines_from_panel(df)
    funding = load_funding(asset)

    cfg = HyperliquidConfig()
    rows = []

    for feat in top_features:
        for sgn, sgn_name in [(+1, "trend"), (-1, "fade")]:
            sigs = build_zscore_signals(df, feat, tf, sign=sgn)
            if len(sigs) < 10:
                rows.append({
                    "asset": asset, "tf": tf, "feature": feat, "sign": sgn_name,
                    "n_signals": int(len(sigs)),
                    "skipped_reason": "too_few_signals",
                })
                continue
            try:
                trades, stats = run_backtest(
                    klines, funding, sigs, asset,
                    notional_usd=250.0, leverage=1.0, cfg=cfg,
                )
            except Exception as e:
                rows.append({
                    "asset": asset, "tf": tf, "feature": feat, "sign": sgn_name,
                    "n_signals": int(len(sigs)),
                    "skipped_reason": f"backtest_failed:{e}",
                })
                continue
            n = stats["n_trades"]
            wins = stats["n_wins"]
            pnl_arr = trades["pnl_net_usd"].to_numpy() if n > 0 else np.array([0.0])
            p_g1 = g1_pvalue(wins, n, 0.5) if n > 0 else float("nan")
            frac_pos, ci_lo, ci_hi = g6_bootstrap_pnl(pnl_arr) if n >= 10 else (float("nan"),) * 3
            row = {
                "asset": asset, "tf": tf, "feature": feat, "sign": sgn_name,
                "n_signals": int(len(sigs)),
                "n_trades": n, "n_wins": wins,
                "win_rate": stats["win_rate"],
                "total_pnl_usd": stats["total_pnl_usd"],
                "avg_pnl_usd": stats["avg_pnl_usd"],
                "sharpe": stats["sharpe"],
                "max_dd_usd": stats["max_dd_usd"],
                "avg_funding_paid": stats["avg_funding_paid"],
                "avg_fees_paid": stats["avg_fees_paid"],
                "avg_bars_held": stats["avg_bars_held"],
                "g1_pvalue": p_g1,
                "g1_pass": (n >= 30) and (p_g1 < 0.05) if not np.isnan(p_g1) else False,
                "g3_pass": stats["total_pnl_usd"] > 0,
                "g6_frac_positive": frac_pos,
                "g6_ci_lo": ci_lo,
                "g6_ci_hi": ci_hi,
                "g6_pass": (frac_pos > 0.95) if not np.isnan(frac_pos) else False,
            }
            rows.append(row)
    return rows


def main():
    imp_path = OUT_DIR / "W3_feature_importance.csv"
    if not imp_path.exists():
        print(f"ERROR: {imp_path} not found. Run W3_train_ml.py first.")
        sys.exit(1)
    imp = pd.read_csv(imp_path)

    all_rows = []
    for asset in ASSETS:
        for tf in TFS:
            sub = imp.loc[(imp["asset"] == asset) & (imp["tf"] == tf)] \
                     .sort_values("mean_importance", ascending=False).head(3)
            top_features = sub["feature"].tolist()
            if not top_features:
                continue
            print(f"\n=== {asset} {tf} | top features: {top_features} ===")
            res = run_discovery(asset, tf, top_features)
            for r in res:
                print(f"  {r.get('feature','?')}: n_trades={r.get('n_trades','-')} "
                      f"win_rate={r.get('win_rate','-')} "
                      f"pnl=${r.get('total_pnl_usd','-')} "
                      f"g1={r.get('g1_pass','-')} g3={r.get('g3_pass','-')} g6={r.get('g6_pass','-')}")
            all_rows.extend(res)

    out = pd.DataFrame(all_rows)
    out.to_csv(OUT_DIR / "W3_discovery_strategies.csv", index=False)
    print(f"\nWrote {len(out)} rows -> W3_discovery_strategies.csv")

    # Filter passing strategies (G1+G3 at minimum)
    if len(out) and "g1_pass" in out.columns:
        passing = out.loc[
            (out["g1_pass"] == True) & (out["g3_pass"] == True)
        ].sort_values("total_pnl_usd", ascending=False)
        print(f"\nPassing G1+G3: {len(passing)}")
        if len(passing):
            print(passing[["asset", "tf", "feature", "n_trades", "win_rate",
                          "total_pnl_usd", "g1_pvalue", "g6_frac_positive"]].to_string())


if __name__ == "__main__":
    main()
