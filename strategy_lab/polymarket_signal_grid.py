"""
polymarket_signal_grid.py — Run the strategy grid using REAL signals
discovered in the univariate analysis.

Signals tested (sign(feature) → UP/DOWN, optionally with a confidence filter
that skips middle markets):

  sig_ret5m            — bet sign(ret_5m) on every market (no filter)
  sig_ret5m_q20        — bet only top/bot 20% by |ret_5m|
  sig_ret5m_q10        — bet only top/bot 10% by |ret_5m|
  sig_ret5m_thr_25bps  — bet only when |ret_5m| > 25 bps (0.25%)
  sig_smartretail_q20  — bet sign(smart_minus_retail) top/bot 20%
  sig_combo_q20        — agree(ret_5m, smart_minus_retail) at 20% threshold

For each (timeframe, signal, exit_rule) cell:
  1,422 5m markets, 474 15m markets through the existing exit rules
  (S0 hold, S2 stop, S3 target+stop) with 2% fee on winnings.

Output:
  results/polymarket/signal_grid.csv
  reports/POLYMARKET_SIGNAL_GRID.md
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FEATS = HERE / "data" / "polymarket" / "btc_features_v3.csv"
TRAJ  = HERE / "data" / "polymarket" / "btc_trajectories_v3.csv"
OUT_CSV = HERE / "results" / "polymarket" / "signal_grid.csv"
OUT_MD  = HERE / "reports"  / "POLYMARKET_SIGNAL_GRID.md"
RNG = np.random.default_rng(42)
FEE_RATE = 0.02


def load_traj_by_slug() -> dict[str, pd.DataFrame]:
    t = pd.read_csv(TRAJ)
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first": "up_bid_first", "bid_last": "up_bid_last",
        "bid_min":   "up_bid_min",   "bid_max":  "up_bid_max",
        "ask_first": "up_ask_first", "ask_last": "up_ask_last",
    })[["slug", "bucket_10s", "up_bid_first", "up_bid_last", "up_bid_min", "up_bid_max",
        "up_ask_first", "up_ask_last"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first": "dn_bid_first", "bid_last": "dn_bid_last",
        "bid_min":   "dn_bid_min",   "bid_max":  "dn_bid_max",
        "ask_first": "dn_ask_first", "ask_last": "dn_ask_last",
    })[["slug", "bucket_10s", "dn_bid_first", "dn_bid_last", "dn_bid_min", "dn_bid_max",
        "dn_ask_first", "dn_ask_last"]]
    merged = up.merge(dn, on=["slug", "bucket_10s"], how="outer").sort_values(
        ["slug", "bucket_10s"])
    return {slug: g for slug, g in merged.groupby("slug")}


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["sig_ret5m"] = (df.ret_5m > 0).astype(int)
    df.loc[df.ret_5m.isna(), "sig_ret5m"] = -1

    # Quantile filters (per timeframe)
    df["sig_ret5m_q20"] = -1
    df["sig_ret5m_q10"] = -1
    df["sig_ret5m_thr_25bps"] = -1
    df["sig_smartretail_q20"] = -1
    df["sig_combo_q20"] = -1
    for tf in ["5m", "15m"]:
        m = df.timeframe == tf
        ret = df.loc[m, "ret_5m"].abs()
        q20 = ret.quantile(0.80)
        q10 = ret.quantile(0.90)
        df.loc[m & (ret >= q20), "sig_ret5m_q20"] = (df.loc[m & (ret >= q20), "ret_5m"] > 0).astype(int)
        df.loc[m & (ret >= q10), "sig_ret5m_q10"] = (df.loc[m & (ret >= q10), "ret_5m"] > 0).astype(int)
        df.loc[m & (ret >= 0.0025), "sig_ret5m_thr_25bps"] = (df.loc[m & (ret >= 0.0025), "ret_5m"] > 0).astype(int)

        sr = df.loc[m, "smart_minus_retail"]
        sr_lo, sr_hi = sr.quantile(0.20), sr.quantile(0.80)
        sr_extreme = m & ((df.smart_minus_retail >= sr_hi) | (df.smart_minus_retail <= sr_lo))
        df.loc[sr_extreme, "sig_smartretail_q20"] = (df.loc[sr_extreme, "smart_minus_retail"] > 0).astype(int)

        # Combo: only trade when ret_5m_q20 fires AND smart_minus_retail agrees in direction
        agree_mask = (
            (df.sig_ret5m_q20 == 1) & (df.smart_minus_retail > df.smart_minus_retail.median())
        ) | (
            (df.sig_ret5m_q20 == 0) & (df.smart_minus_retail < df.smart_minus_retail.median())
        )
        agree_in_tf = m & agree_mask
        df.loc[agree_in_tf, "sig_combo_q20"] = df.loc[agree_in_tf, "sig_ret5m_q20"]

    return df


def simulate(row: pd.Series, traj_g: pd.DataFrame,
             target: float | None, stop: float | None) -> float:
    sig = int(row.signal)
    if sig == 1:
        entry = float(row.entry_yes_ask)
        col_min, col_max = "up_bid_min", "up_bid_max"
    else:
        entry = float(row.entry_no_ask)
        col_min, col_max = "dn_bid_min", "dn_bid_max"
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return 0.0
    exit_price = None
    for _, b in traj_g.iterrows():
        if stop is not None and pd.notna(b[col_min]) and b[col_min] <= stop:
            exit_price = stop
            break
        if target is not None and pd.notna(b[col_max]) and b[col_max] >= target:
            exit_price = target
            break
    if exit_price is None:
        won = (sig == int(row.outcome_up))
        gross = (1.0 - entry) if won else -entry
        fee = (1.0 - entry) * FEE_RATE if won else 0.0
        return gross - fee
    return exit_price - entry


def run(df: pd.DataFrame, traj_by_slug: dict, signal_col: str,
        target: float | None, stop: float | None) -> dict:
    sub = df[df[signal_col] != -1].copy()
    sub["signal"] = sub[signal_col]
    pnls = []
    for _, row in sub.iterrows():
        traj_g = traj_by_slug.get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        pnls.append(simulate(row, traj_g, target, stop))
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return {"n": 0, "total_pnl": 0.0, "ci_lo": 0.0, "ci_hi": 0.0,
                "win_rate": float("nan")}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    return {
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "win_rate": float((pnls > 0).mean()),
        "mean_pnl": float(pnls.mean()),
    }


def main():
    df = pd.read_csv(FEATS)
    df = add_signals(df)
    traj_by_slug = load_traj_by_slug()
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    signals = ["sig_ret5m", "sig_ret5m_q20", "sig_ret5m_q10",
               "sig_ret5m_thr_25bps", "sig_smartretail_q20", "sig_combo_q20"]
    strategies = [
        (None, None,  "S0_hold"),
        (None, 0.40, "S2_stop40"),
        (None, 0.35, "S2_stop35"),
        (None, 0.30, "S2_stop30"),
        (0.55, None, "S1_tgt55"),
        (0.60, None, "S1_tgt60"),
        (0.70, 0.35, "S3_t70s35"),
        (0.60, 0.35, "S3_t60s35"),
        (0.55, 0.40, "S3_t55s40"),
    ]

    rows = []
    for tf in ["5m", "15m"]:
        sub = df[df.timeframe == tf]
        for sig_col in signals:
            for target, stop, lbl in strategies:
                r = run(sub, traj_by_slug, sig_col, target, stop)
                r["timeframe"] = tf
                r["signal"] = sig_col
                r["strategy"] = lbl
                rows.append(r)
                print(f"{tf} {sig_col:24s} {lbl:10s} → "
                      f"n={r['n']:4d} pnl={r['total_pnl']:+7.2f} "
                      f"CI=[{r['ci_lo']:+5.0f},{r['ci_hi']:+5.0f}] win={r['win_rate']*100:5.1f}%")

    out = pd.DataFrame(rows)[
        ["timeframe", "signal", "strategy", "n", "total_pnl", "ci_lo", "ci_hi",
         "win_rate", "mean_pnl"]
    ]
    out.to_csv(OUT_CSV, index=False)

    md = ["# Polymarket Real-Signal × Exit Grid — BTC Up/Down (Apr 22-27)\n",
          "Signals derived from Binance microstructure (ret_5m, smart_minus_retail) "
          "via VPS `binance_klines_v2` + `binance_metrics_v2`. "
          "Fee 2% on winnings. Bootstrap n=2000.\n"]

    for tf in ["5m", "15m"]:
        sub = out[out.timeframe == tf].sort_values("total_pnl", ascending=False)
        md.append(f"\n## {tf} — top 12 cells by PnL\n")
        md.append("| Signal | Strategy | n | PnL | 95% CI | Win% |")
        md.append("|---|---|---|---|---|---|")
        for _, r in sub.head(12).iterrows():
            md.append(
                f"| {r['signal']} | {r['strategy']} | {int(r['n'])} | "
                f"${r['total_pnl']:+.2f} | "
                f"[${r['ci_lo']:+.0f}, ${r['ci_hi']:+.0f}] | "
                f"{r['win_rate']*100:.1f}% |"
            )

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV} and {OUT_MD}")


if __name__ == "__main__":
    main()
