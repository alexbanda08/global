"""
polymarket_backtest_v1 — First-pass Polymarket backtest.

Simulates a trading strategy on 444 resolved BTC Up/Down markets using a
signal with known accuracy (matches Kronos's measured 69.3% or variants).

Strategy: HOLD TO RESOLUTION.
  - At window_start (5m or 15m before resolve):
    - If signal == UP:   buy YES side at entry_yes_ask, pay ~0.51
    - If signal == DOWN: buy NO  side at entry_no_ask,  pay ~0.50
  - At resolve:
    - If signal matches outcome: receive 1.00 per contract (profit = 1 - entry_ask)
    - If wrong: contract worth 0 (loss = entry_ask)
  - Ignore market fees / gas for now (Polymarket takes ~2% on winnings)

Runs 10,000 Monte-Carlo simulations per accuracy level to get CI on PnL.
Outputs PnL distribution, ROI, hit rate, max DD, Sharpe.

Usage:
  py strategy_lab/polymarket_backtest_v1.py \
      --markets strategy_lab/data/polymarket/btc_markets.csv \
      --out strategy_lab/reports/POLYMARKET_BACKTEST_V1.md
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)


def load(csv: Path) -> pd.DataFrame:
    df = pd.read_csv(csv)
    # Keep only markets with full entry data and resolved outcome
    ok = df.entry_yes_ask.notna() & df.entry_no_ask.notna() & df.outcome_up.notna()
    return df[ok].reset_index(drop=True)


def simulate_signal(outcomes: np.ndarray, accuracy: float) -> np.ndarray:
    """Generate a signal with `accuracy` probability of matching each outcome."""
    n = len(outcomes)
    correct = RNG.random(n) < accuracy
    signal = np.where(correct, outcomes, 1 - outcomes)
    return signal


def bet_pnl(signal: np.ndarray, outcomes: np.ndarray,
            entry_yes_ask: np.ndarray, entry_no_ask: np.ndarray,
            fee_rate: float = 0.02) -> np.ndarray:
    """
    PnL per $1 of entry stake (so PnL is relative).
    - If signal=1 (UP): buy YES, entry cost = entry_yes_ask
    - If signal=0 (DOWN): buy NO, entry cost = entry_no_ask
    If signal matches outcome: payout = 1.0; PnL = (1 - entry) - entry*fee (on profit)
    Else: payout = 0; PnL = -entry
    """
    entry = np.where(signal == 1, entry_yes_ask, entry_no_ask)
    won = signal == outcomes
    gross_pnl = np.where(won, 1.0 - entry, -entry)
    # Fee on winnings only (Polymarket takes from profit, not stake)
    fee = np.where(won, (1.0 - entry) * fee_rate, 0.0)
    return gross_pnl - fee


def simulate_accuracy(df: pd.DataFrame, accuracy: float, n_sims: int = 10000,
                      fee_rate: float = 0.02, stake_per_bet: float = 1.0) -> dict:
    """Run n_sims Monte-Carlo trials. Each trial = bet on every market with fresh signal."""
    outcomes = df.outcome_up.astype(int).to_numpy()
    ey = df.entry_yes_ask.to_numpy()
    en = df.entry_no_ask.to_numpy()
    n_markets = len(df)

    total_pnls = np.zeros(n_sims)
    hit_rates = np.zeros(n_sims)
    max_dds = np.zeros(n_sims)
    sharpes = np.zeros(n_sims)

    for i in range(n_sims):
        signal = simulate_signal(outcomes, accuracy)
        pnl = bet_pnl(signal, outcomes, ey, en, fee_rate)
        total_pnls[i] = pnl.sum() * stake_per_bet
        hit_rates[i] = (signal == outcomes).mean()
        # Max drawdown across the cumulative curve
        cum = np.cumsum(pnl) * stake_per_bet
        peak = np.maximum.accumulate(cum)
        dd = peak - cum
        max_dds[i] = dd.max()
        # Sharpe (per-bet): mean / std * sqrt(n)
        sharpes[i] = pnl.mean() / (pnl.std() + 1e-12) * np.sqrt(n_markets)

    return {
        "accuracy": accuracy,
        "n_markets": n_markets,
        "n_sims": n_sims,
        "mean_total_pnl": float(total_pnls.mean()),
        "pnl_ci95": [float(np.quantile(total_pnls, 0.025)),
                     float(np.quantile(total_pnls, 0.975))],
        "pct_profitable_runs": float((total_pnls > 0).mean()),
        "roi_pct_per_bet": float(total_pnls.mean() / (n_markets * stake_per_bet) * 100),
        "mean_hit_rate": float(hit_rates.mean()),
        "mean_max_dd": float(max_dds.mean()),
        "mean_sharpe": float(sharpes.mean()),
    }


def simulate_skip_on_expensive(df: pd.DataFrame, accuracy: float,
                                max_entry: float, n_sims: int = 5000) -> dict:
    """Skip markets where entry_ask > max_entry. Only bet on "cheap" entries."""
    outcomes_all = df.outcome_up.astype(int).to_numpy()
    ey = df.entry_yes_ask.to_numpy()
    en = df.entry_no_ask.to_numpy()

    total_pnls = np.zeros(n_sims)
    bet_counts = np.zeros(n_sims)

    for i in range(n_sims):
        signal = simulate_signal(outcomes_all, accuracy)
        # entry_cost depends on which side we'd bet
        entry_cost = np.where(signal == 1, ey, en)
        keep = entry_cost <= max_entry
        pnl = bet_pnl(signal[keep], outcomes_all[keep], ey[keep], en[keep])
        total_pnls[i] = pnl.sum()
        bet_counts[i] = keep.sum()

    return {
        "accuracy": accuracy,
        "max_entry": max_entry,
        "mean_total_pnl": float(total_pnls.mean()),
        "pnl_ci95": [float(np.quantile(total_pnls, 0.025)),
                     float(np.quantile(total_pnls, 0.975))],
        "mean_n_bets": float(bet_counts.mean()),
        "roi_pct_per_bet": float(total_pnls.mean() / (bet_counts.mean() + 1e-12) * 100),
    }


def render(data: dict, out: Path) -> None:
    L = ["# Polymarket Backtest V1 — Hold-to-Resolution", ""]
    L.append(f"Source: `{data['source']}`")
    L.append(f"Markets: {data['n_markets']} (333 BTC 5m + 111 BTC 15m, resolved with full entry data)")
    L.append(f"Fee assumption: {data['fee_rate']:.1%} on winnings (Polymarket trading fee)")
    L.append(f"Stake per bet: $1 (scale linearly)")
    L.append("")
    L.append("## Strategy")
    L.append("")
    L.append("At each market's window-start timestamp, bet sign(signal) on the appropriate outcome")
    L.append("(buy YES if UP, buy NO if DOWN). Hold to resolution. Pay entry ask, receive $1 if correct.")
    L.append("")

    L.append("## PnL by signal accuracy (Monte-Carlo, 10k sims per row)")
    L.append("")
    L.append("| Accuracy | Mean PnL | 95% CI | ROI per bet | Profit rate | Mean DD | Sharpe |")
    L.append("|---|---|---|---|---|---|---|")
    for r in data["accuracy_results"]:
        L.append(f"| **{r['accuracy']:.0%}** | ${r['mean_total_pnl']:+.2f} | "
                 f"[${r['pnl_ci95'][0]:+.2f}, ${r['pnl_ci95'][1]:+.2f}] | "
                 f"{r['roi_pct_per_bet']:+.2f}% | "
                 f"{r['pct_profitable_runs']:.1%} | "
                 f"${r['mean_max_dd']:.2f} | "
                 f"{r['mean_sharpe']:.2f} |")
    L.append("")
    L.append("Interpretation:")
    L.append("- Each bet stakes $1. Total PnL is dollar profit across all {} bets.".format(data['n_markets']))
    L.append("- CI tells the range of outcomes across randomized signals. If CI includes negative, strategy is risky.")
    L.append("- ROI per bet = average profit per $1 bet. Comparable to per-trade edge.")
    L.append("- Profit rate = % of Monte-Carlo runs that ended profitable.")
    L.append("")

    L.append("## Entry-price filter (skip expensive markets)")
    L.append("")
    L.append("At signal accuracy 69% (measured Kronos), skip markets where the bet-side ask > threshold.")
    L.append("")
    L.append("| Max entry ask | Accuracy | Mean PnL | 95% CI | # bets | ROI/bet |")
    L.append("|---|---|---|---|---|---|")
    for r in data["entry_filter_results"]:
        L.append(f"| {r['max_entry']:.3f} | {r['accuracy']:.0%} | "
                 f"${r['mean_total_pnl']:+.2f} | "
                 f"[${r['pnl_ci95'][0]:+.2f}, ${r['pnl_ci95'][1]:+.2f}] | "
                 f"{r['mean_n_bets']:.0f} | "
                 f"{r['roi_pct_per_bet']:+.2f}% |")
    L.append("")

    L.append("## Key insights")
    L.append("")
    # Find 69% row
    r69 = next((r for r in data["accuracy_results"] if abs(r["accuracy"] - 0.69) < 0.01), None)
    r50 = next((r for r in data["accuracy_results"] if abs(r["accuracy"] - 0.50) < 0.01), None)
    if r69 and r50:
        L.append(f"- **At 50% accuracy (random signal):** mean PnL ${r50['mean_total_pnl']:+.2f} "
                 f"(essentially 0 — fees and spread eat you).")
        L.append(f"- **At 69% Kronos accuracy:** mean PnL ${r69['mean_total_pnl']:+.2f}, "
                 f"ROI {r69['roi_pct_per_bet']:+.2f}% per bet, "
                 f"profitable in {r69['pct_profitable_runs']:.1%} of Monte-Carlo runs.")
        if r69['mean_total_pnl'] > 0 and r69['pct_profitable_runs'] > 0.95:
            L.append("- **Verdict: Kronos-grade signal is clearly profitable on real Polymarket data.**")
        elif r69['mean_total_pnl'] > 0:
            L.append("- **Verdict: positive expected value but noisy.** Larger sample needed for confidence.")
        else:
            L.append("- **Verdict: not yet profitable.** Entry spread eats the edge at this accuracy level.")
    L.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fee-rate", type=float, default=0.02)
    args = ap.parse_args()

    df = load(Path(args.markets))
    print(f"Loaded {len(df)} resolved markets with entry prices")

    # Sweep accuracy levels
    accuracy_levels = [0.50, 0.55, 0.60, 0.65, 0.69, 0.72, 0.75, 0.80]
    acc_results = []
    for a in accuracy_levels:
        r = simulate_accuracy(df, a, n_sims=10000, fee_rate=args.fee_rate)
        acc_results.append(r)
        print(f"  acc={a:.0%}  mean PnL ${r['mean_total_pnl']:+7.2f}  "
              f"CI [${r['pnl_ci95'][0]:+6.2f}, ${r['pnl_ci95'][1]:+6.2f}]  "
              f"ROI {r['roi_pct_per_bet']:+5.2f}%  "
              f"profitable {r['pct_profitable_runs']:.1%}")

    # Entry filter sweep at 69% accuracy
    entry_results = []
    for max_entry in [0.60, 0.55, 0.53, 0.52, 0.51]:
        r = simulate_skip_on_expensive(df, 0.69, max_entry, n_sims=5000)
        entry_results.append(r)

    data = {
        "source": args.markets,
        "n_markets": len(df),
        "fee_rate": args.fee_rate,
        "accuracy_results": acc_results,
        "entry_filter_results": entry_results,
    }

    render(data, Path(args.out))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
