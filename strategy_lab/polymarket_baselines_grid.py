"""
polymarket_baselines_grid.py — Run the strategy grid (S0..S7) on the new ~1,897 BTC
sample using only zero-cost baseline signals (no Kronos required).

Baselines:
  always_up    — always bet UP
  always_down  — always bet DOWN
  random       — coin flip (sanity)
  market_with  — bet whichever side is MORE expensive at window_start (trust market)
  market_anti  — bet whichever side is CHEAPER (lean against market)
  momentum     — bet UP if prior chainlink return >0, else DOWN
                 (uses strike[N] - strike[N-1] within timeframe, sorted by resolve_unix)

For each baseline + timeframe, run S0 hold + S2 stop ∈ {0.40, 0.35, 0.30} +
S3 (target+stop) {0.55+0.40, 0.60+0.35, 0.70+0.35} + S1 target {0.55, 0.60}.

Outputs: reports/POLYMARKET_BASELINES_GRID.md with a sorted summary table
+ results/polymarket/baselines_grid.csv with the full grid.

Usage:
  python strategy_lab/polymarket_baselines_grid.py
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MARKETS = HERE / "data" / "polymarket" / "btc_markets_v3.csv"
TRAJ    = HERE / "data" / "polymarket" / "btc_trajectories_v3.csv"
OUT_CSV = HERE / "results" / "polymarket" / "baselines_grid.csv"
OUT_MD  = HERE / "reports" / "POLYMARKET_BASELINES_GRID.md"
RNG = np.random.default_rng(42)
FEE_RATE = 0.02


# ----------------------- data loading -----------------------
def load_markets() -> pd.DataFrame:
    m = pd.read_csv(MARKETS)
    m = m[m.entry_yes_ask.notna() & m.entry_no_ask.notna() & m.outcome_up.notna()].copy()
    m["outcome_up"] = m.outcome_up.astype(int)
    return m


def load_trajectories() -> pd.DataFrame:
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
    return up.merge(dn, on=["slug", "bucket_10s"], how="outer").sort_values(
        ["slug", "bucket_10s"])


# ----------------------- signals -----------------------
def add_baselines(m: pd.DataFrame) -> pd.DataFrame:
    """Adds signal columns: signal_<baseline> ∈ {0=DOWN, 1=UP}."""
    m = m.sort_values(["timeframe", "resolve_unix"]).copy()
    m["signal_always_up"]   = 1
    m["signal_always_down"] = 0
    m["signal_random"]      = RNG.integers(0, 2, size=len(m))
    # Market_with: bet on the MORE expensive side (higher implied prob)
    m["signal_market_with"] = (m.entry_yes_ask <= m.entry_no_ask).astype(int)  # cheaper YES means UP-side priced cheaper, market favors DOWN... wait
    # Re-derive cleanly: P(UP) ≈ 1 - entry_no_ask (we'd buy YES at ask, paying entry_yes_ask).
    # The "cheap" side is the one LESS likely to win per the market. Bet WITH market = bet on side that's LESS cheap.
    # If entry_yes_ask > entry_no_ask  → YES side priced higher → market thinks UP more likely → signal=1
    m["signal_market_with"] = (m.entry_yes_ask >  m.entry_no_ask).astype(int)
    m["signal_market_anti"] = 1 - m["signal_market_with"]
    # Momentum: prior chainlink return within timeframe
    m["prior_strike"] = m.groupby("timeframe")["strike_price"].shift(1)
    m["prior_ret"] = (m.strike_price - m.prior_strike) / m.prior_strike
    m["signal_momentum"] = (m.prior_ret > 0).astype(int)
    # Mark momentum NaN rows so we can exclude them downstream
    m.loc[m.prior_ret.isna(), "signal_momentum"] = -1
    return m


# ----------------------- exit simulation -----------------------
def simulate(row: pd.Series, traj_g: pd.DataFrame,
             target: float | None, stop: float | None) -> dict:
    """One market exit sim; PnL per $1 stake."""
    signal = int(row.signal)
    if signal == 1:
        entry = float(row.entry_yes_ask)
        col_min, col_max, col_last = "up_bid_min", "up_bid_max", "up_bid_last"
    else:
        entry = float(row.entry_no_ask)
        col_min, col_max, col_last = "dn_bid_min", "dn_bid_max", "dn_bid_last"
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return {"pnl": 0.0, "exit": "no_entry"}

    exit_price = None
    exit_reason = "held"
    for _, b in traj_g.iterrows():
        bid_min = b[col_min]
        bid_max = b[col_max]
        if stop is not None and pd.notna(bid_min) and bid_min <= stop:
            exit_price = stop
            exit_reason = "stop"
            break
        if target is not None and pd.notna(bid_max) and bid_max >= target:
            exit_price = target
            exit_reason = "target"
            break

    if exit_price is None:
        won = (signal == int(row.outcome_up))
        gross = (1.0 - entry) if won else -entry
        fee = (1.0 - entry) * FEE_RATE if won else 0.0
        return {"pnl": gross - fee, "exit": "resolution"}
    return {"pnl": exit_price - entry, "exit": exit_reason}


def run_strategy(markets: pd.DataFrame, traj_by_slug: dict[str, pd.DataFrame],
                 baseline: str, target: float | None, stop: float | None) -> dict:
    df = markets.copy()
    df["signal"] = df[f"signal_{baseline}"]
    df = df[df.signal != -1]  # drop NaN momentum rows
    pnls = []
    for _, row in df.iterrows():
        traj_g = traj_by_slug.get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        res = simulate(row, traj_g, target, stop)
        pnls.append(res["pnl"])
    pnls = np.array(pnls)
    if len(pnls) == 0:
        return {"baseline": baseline, "n": 0}
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    return {
        "baseline": baseline,
        "target": target, "stop": stop,
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "mean_pnl": float(pnls.mean()),
        "win_rate": float((pnls > 0).mean()),
        "roi_pct": float(pnls.sum() / max(np.abs(pnls).sum(), 1e-9) * 100),
    }


# ----------------------- driver -----------------------
def main():
    markets = add_baselines(load_markets())
    traj    = load_trajectories()
    traj_by_slug = {slug: g for slug, g in traj.groupby("slug")}
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)

    baselines = ["always_up", "always_down", "random",
                 "market_with", "market_anti", "momentum"]
    strategies = [
        # (target, stop, label)
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
        sub = markets[markets.timeframe == tf]
        for baseline in baselines:
            for target, stop, lbl in strategies:
                r = run_strategy(sub, traj_by_slug, baseline, target, stop)
                r["timeframe"] = tf
                r["strategy"] = lbl
                rows.append(r)
                print(f"{tf} {baseline:14s} {lbl:10s} → "
                      f"n={r.get('n',0):4d} pnl={r.get('total_pnl',0):+.2f} "
                      f"win={r.get('win_rate',0)*100:.1f}%")

    df = pd.DataFrame(rows)
    df = df[["timeframe", "baseline", "strategy", "n",
             "total_pnl", "ci_lo", "ci_hi", "win_rate", "mean_pnl", "roi_pct"]]
    df.to_csv(OUT_CSV, index=False)

    # Markdown report
    md = ["# Polymarket Baselines × Exit Grid — BTC Up/Down (Apr 22-27)\n",
          f"Sample: {len(markets)} BTC markets ({(markets.timeframe=='5m').sum()}× 5m + "
          f"{(markets.timeframe=='15m').sum()}× 15m). Fee: 2% on winnings. "
          f"Bootstrap n=2000 for 95% CIs.\n"]
    for tf in ["5m", "15m"]:
        sub = df[df.timeframe == tf].sort_values("total_pnl", ascending=False)
        md.append(f"\n## {tf} — top 10 strategy×baseline by total PnL\n")
        md.append("| Baseline | Strategy | n | PnL | 95% CI | Win% |")
        md.append("|---|---|---|---|---|---|")
        for _, r in sub.head(10).iterrows():
            md.append(
                f"| {r.baseline} | {r.strategy} | {r.n} | "
                f"${r.total_pnl:+.2f} | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] | "
                f"{r.win_rate*100:.1f}% |"
            )
        md.append(f"\n## {tf} — bottom 5 (sanity check)\n")
        md.append("| Baseline | Strategy | n | PnL | 95% CI | Win% |")
        md.append("|---|---|---|---|---|---|")
        for _, r in sub.tail(5).iterrows():
            md.append(
                f"| {r.baseline} | {r.strategy} | {r.n} | "
                f"${r.total_pnl:+.2f} | [${r.ci_lo:+.0f}, ${r.ci_hi:+.0f}] | "
                f"{r.win_rate*100:.1f}% |"
            )

    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {OUT_CSV} and {OUT_MD}")


if __name__ == "__main__":
    main()
