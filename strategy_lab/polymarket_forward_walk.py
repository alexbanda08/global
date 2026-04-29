"""
polymarket_forward_walk.py — Out-of-sample (holdout) test of the ret_5m signal.

Splits the 1,896 BTC markets chronologically by resolve_unix:
  TRAIN: first 80% (oldest)
  HOLDOUT: last 20% (newest)

For each signal:
  - sig_ret5m            (parameter-free)         — works as-is on holdout
  - sig_ret5m_q20        (top/bot 20% by |ret_5m|) — threshold computed from TRAIN only
  - sig_ret5m_q10        (top/bot 10% by |ret_5m|) — threshold computed from TRAIN only

Reports: hit rate, PnL, 95% CI on TRAIN vs HOLDOUT side by side.
If holdout hit rate stays ≥56% and CI excludes zero, signal is real.

Uses S0_hold (no exit rule) — we already established stops hurt this signal.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
FEATS = HERE / "data" / "polymarket" / "btc_features_v3.csv"
OUT_MD = HERE / "reports" / "POLYMARKET_FORWARD_WALK.md"
RNG = np.random.default_rng(42)
FEE_RATE = 0.02


def pnl_per_market(row: pd.Series) -> float:
    """Hold-to-resolution PnL per $1 stake."""
    sig = int(row.signal)
    entry = float(row.entry_yes_ask if sig == 1 else row.entry_no_ask)
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return 0.0
    won = (sig == int(row.outcome_up))
    gross = (1.0 - entry) if won else -entry
    fee = (1.0 - entry) * FEE_RATE if won else 0.0
    return gross - fee


def evaluate(df: pd.DataFrame) -> dict:
    pnls = df.apply(pnl_per_market, axis=1).to_numpy()
    if len(pnls) == 0:
        return {"n": 0}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    hits = (df.signal == df.outcome_up).mean()
    return {
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit_rate": float(hits),
        "roi_per_bet_pct": float(pnls.sum() / max(len(pnls), 1) * 100),
    }


def split(df: pd.DataFrame, train_frac: float = 0.8) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = df.sort_values("strike_price")  # placeholder; we want time
    df = df.sort_values("slug").copy()  # slug ends in resolve_unix, sortable
    # Better: extract resolve_unix from slug
    df["resolve_unix"] = df.slug.str.extract(r"(\d+)$").astype(int)
    df = df.sort_values("resolve_unix").reset_index(drop=True)
    cut = int(len(df) * train_frac)
    return df.iloc[:cut].copy(), df.iloc[cut:].copy()


def make_signal(df: pd.DataFrame, kind: str, ret_thresh: float | None = None) -> pd.DataFrame:
    """Returns df with `signal` ∈ {0, 1, -1=skip} added."""
    out = df.copy()
    if kind == "all":
        out["signal"] = (out.ret_5m > 0).astype(int)
        out.loc[out.ret_5m.isna(), "signal"] = -1
    elif kind == "thresh":
        m = out.ret_5m.notna() & (out.ret_5m.abs() >= ret_thresh)
        out["signal"] = -1
        out.loc[m, "signal"] = (out.loc[m, "ret_5m"] > 0).astype(int)
    return out[out.signal != -1].copy()


def run_per_tf(df: pd.DataFrame, tf: str) -> list[dict]:
    sub = df[df.timeframe == tf].copy()
    train, holdout = split(sub, 0.8)

    # Thresholds from TRAIN ONLY
    train_abs_ret = train.ret_5m.abs().dropna()
    q20_thresh = float(train_abs_ret.quantile(0.80))
    q10_thresh = float(train_abs_ret.quantile(0.90))

    rows = []
    configs = [
        ("sig_ret5m",      "all",    None),
        ("sig_ret5m_q20",  "thresh", q20_thresh),
        ("sig_ret5m_q10",  "thresh", q10_thresh),
    ]

    for name, kind, thr in configs:
        train_signal   = make_signal(train,   kind, thr)
        holdout_signal = make_signal(holdout, kind, thr)
        train_eval     = evaluate(train_signal)
        holdout_eval   = evaluate(holdout_signal)
        rows.append({
            "timeframe": tf, "signal": name, "ret_thresh": thr,
            "train_n": train_eval["n"],   "train_hit":   train_eval.get("hit_rate"),
            "train_pnl": train_eval.get("total_pnl"),
            "train_ci_lo": train_eval.get("ci_lo"), "train_ci_hi": train_eval.get("ci_hi"),
            "train_roi_pct": train_eval.get("roi_per_bet_pct"),
            "holdout_n": holdout_eval["n"], "holdout_hit": holdout_eval.get("hit_rate"),
            "holdout_pnl": holdout_eval.get("total_pnl"),
            "holdout_ci_lo": holdout_eval.get("ci_lo"), "holdout_ci_hi": holdout_eval.get("ci_hi"),
            "holdout_roi_pct": holdout_eval.get("roi_per_bet_pct"),
        })
    return rows


def main():
    df = pd.read_csv(FEATS)
    rows = []
    for tf in ["5m", "15m"]:
        rows.extend(run_per_tf(df, tf))

    # Print + markdown
    md = ["# Forward-Walk Holdout — `sig_ret5m` family\n",
          "Chronological 80/20 split. Train = first 80% of markets by resolve_unix, "
          "Holdout = last 20%. Quantile thresholds computed on TRAIN only.\n",
          "If holdout hit% stays ≥56% and CI excludes zero, signal is **real**.\n"]
    for tf in ["5m", "15m"]:
        md.append(f"\n## {tf}\n")
        md.append("| Signal | Threshold | Train n / hit / PnL / CI / ROI | Holdout n / hit / PnL / CI / ROI |")
        md.append("|---|---|---|---|")
        for r in [r for r in rows if r["timeframe"] == tf]:
            thr_str = "—" if r["ret_thresh"] is None else f"{r['ret_thresh']*100:.3f}%"
            tr = (f"{r['train_n']} / {r['train_hit']*100:.1f}% / ${r['train_pnl']:+.2f} "
                  f"/ [${r['train_ci_lo']:+.0f},${r['train_ci_hi']:+.0f}] "
                  f"/ {r['train_roi_pct']:+.2f}%")
            ho = (f"{r['holdout_n']} / {r['holdout_hit']*100:.1f}% / ${r['holdout_pnl']:+.2f} "
                  f"/ [${r['holdout_ci_lo']:+.0f},${r['holdout_ci_hi']:+.0f}] "
                  f"/ {r['holdout_roi_pct']:+.2f}%")
            md.append(f"| {r['signal']} | {thr_str} | {tr} | {ho} |")
            print(f"{tf} {r['signal']:18s} thr={thr_str:>9s} | "
                  f"TRAIN n={r['train_n']:4d} hit={r['train_hit']*100:5.1f}% pnl=${r['train_pnl']:+.2f} "
                  f"CI=[${r['train_ci_lo']:+.0f},${r['train_ci_hi']:+.0f}] | "
                  f"HOLD n={r['holdout_n']:4d} hit={r['holdout_hit']*100:5.1f}% pnl=${r['holdout_pnl']:+.2f} "
                  f"CI=[${r['holdout_ci_lo']:+.0f},${r['holdout_ci_hi']:+.0f}]")

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_MD}")


if __name__ == "__main__":
    main()
