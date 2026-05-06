"""Polymarket-style EV backtest on classifier OOS predictions.

For each daily prediction `p_up`:
  - If p_up > 0.5 + threshold: bet UP at implied market price p_market
  - If p_up < 0.5 - threshold: bet DOWN at implied market price p_market
  - Else: pass (no bet)

We don't have historical Polymarket prices, so we model p_market as:
  Option A (conservative): always 0.50 (50/50 market) — pure model edge
  Option B (realistic): assume Polymarket prices our prediction; we pay
     spread = 2-3% on each bet

We compute EV per bet at thresholds {0.55, 0.58, 0.60, 0.65}.

Polymarket payout convention:
  Bet $1 on UP at price p_m → if UP wins, get $1 (profit $1 - $1×p_m / p_m =
  (1 - p_m) / p_m on $1 staked at price p_m). To simplify we work with the
  shares notation: pay p_m for a YES share that pays $1 if YES wins.
  EV per $1 = p_us × ($1 - p_m) - (1 - p_us) × p_m  (when betting YES)
            = p_us - p_m   (the linear form, before spread)

So under "fair" pricing (p_m = 0.5), EV = p_us - 0.5. Add spread of `s`
(say 0.015 each side) → effective p_m = 0.5 + s when betting UP, so:
  EV_up = p_us - (0.5 + s)
  EV_down = (1 - p_us) - (0.5 + s) = 0.5 - p_us - s

We bet whichever side has positive EV given threshold confidence.

Output:
    polymarket_results.csv  per-asset, per-threshold:
      n_bets, win_rate, avg_ev_per_bet, total_ev, sharpe_of_ev
    Plus a per-asset bet log.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "strategy_lab" / "reports" / "regime_classifier"


def backtest_polymarket(
    pred: pd.DataFrame,
    p_market_assumption: float = 0.50,
    spread: float = 0.015,
    thresholds: tuple[float, ...] = (0.05, 0.08, 0.10, 0.15),
    bet_size: float = 1.0,  # $1 per bet
) -> pd.DataFrame:
    """For each threshold τ, simulate placing $bet_size on whichever side has
    p_us further than τ from 0.50.

    Returns DataFrame: threshold, n_bets, win_rate, avg_pnl, total_pnl, ev_sharpe.
    """
    rows = []
    for tau in thresholds:
        bets = pred.copy()
        bets["side"] = 0
        bets.loc[bets["p_up"] > p_market_assumption + tau, "side"] = 1
        bets.loc[bets["p_up"] < p_market_assumption - tau, "side"] = -1
        bets = bets[bets["side"] != 0].copy()
        if len(bets) == 0:
            rows.append({"threshold": tau, "n_bets": 0, "win_rate": 0.0,
                         "avg_pnl": 0.0, "total_pnl": 0.0, "ev_sharpe": 0.0})
            continue
        # Effective entry price after spread
        bets["p_paid"] = np.where(bets["side"] == 1, p_market_assumption + spread,
                                  p_market_assumption + spread)  # spread on either side
        # Outcome: 1 if won (predicted side matches y), 0 else
        bets["won"] = (((bets["side"] == 1) & (bets["y"] == 1)) |
                       ((bets["side"] == -1) & (bets["y"] == 0))).astype(int)
        # PnL per $1 stake at p_paid:
        # If win: receive 1, paid p_paid → profit = (1 - p_paid) * (bet_size / p_paid)
        # If lose: lose stake → -bet_size
        # Simplified: payout is binary 1 vs 0 share, stake = $bet_size buys (bet_size / p_paid) shares.
        # PnL = won * (bet_size / p_paid) * 1 - bet_size  if won  (profit)
        #     = -bet_size                               if lost
        bets["pnl"] = np.where(
            bets["won"] == 1,
            bet_size / bets["p_paid"] - bet_size,
            -bet_size,
        )
        rows.append({
            "threshold": tau,
            "n_bets": len(bets),
            "win_rate": float(bets["won"].mean()),
            "avg_pnl": float(bets["pnl"].mean()),
            "total_pnl": float(bets["pnl"].sum()),
            "ev_sharpe": float(bets["pnl"].mean() / bets["pnl"].std()) if bets["pnl"].std() > 0 else 0.0,
        })
    return pd.DataFrame(rows)


def calibration_table(pred: pd.DataFrame, n_bins: int = 10) -> pd.DataFrame:
    """Reliability diagram data: bin p_up into deciles, report empirical UP rate."""
    bins = pd.cut(pred["p_up"], np.linspace(0, 1, n_bins + 1), include_lowest=True)
    out = pred.groupby(bins, observed=True).agg(
        n=("y", "size"),
        avg_p_up=("p_up", "mean"),
        empirical_up_rate=("y", "mean"),
    ).reset_index()
    out["bin"] = out["p_up"].astype(str)
    return out[["bin", "n", "avg_p_up", "empirical_up_rate"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    ap.add_argument("--spread", type=float, default=0.015)
    ap.add_argument("--p-market", type=float, default=0.50,
                    help="assumed Polymarket fair price (0.50 = no info)")
    args = ap.parse_args()

    all_rows = []
    for sym in args.symbols:
        pred_path = OUT / f"predictions_{sym}.parquet"
        if not pred_path.exists():
            print(f"{sym}: missing predictions, skip")
            continue
        pred = pd.read_parquet(pred_path)
        print(f"\n══════════ {sym} — Polymarket EV ══════════")
        print(f"  n_oos={len(pred)}  base_rate={pred['y'].mean()*100:.2f}%  "
              f"oos_acc={((pred['p_up']>0.5).astype(int)==pred['y']).mean()*100:.2f}%")

        df = backtest_polymarket(pred, p_market_assumption=args.p_market, spread=args.spread)
        print(df.to_string(index=False))
        df["symbol"] = sym
        all_rows.append(df)

        # Calibration
        cal = calibration_table(pred, n_bins=10)
        cal.to_csv(OUT / f"calibration_{sym}.csv", index=False)
        print(f"\n  CALIBRATION ({sym}):")
        print(cal.to_string(index=False))

    if all_rows:
        agg = pd.concat(all_rows, ignore_index=True)
        agg.to_csv(OUT / "polymarket_results.csv", index=False)
        print(f"\nSaved: {OUT/'polymarket_results.csv'}")


if __name__ == "__main__":
    main()
