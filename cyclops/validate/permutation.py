"""G3: outcome-shuffle permutation test.

Null hypothesis: our `direction` choice is uncorrelated with `outcome_truth`.
Under the null, the realized outcomes attached to each fired trade are
exchangeable — shuffling them across the fired set produces a representative
draw from the null distribution.

For each draw:
  - permuted_outcome[i] = shuffle(outcome_truth)[i]
  - won_null[i]         = (direction[i] == permuted_outcome[i])
  - pnl_null[i]         = settle_legacy(won_null[i], shares[i], stake[i])

p_value = P(mean_pnl_null >= observed_mean_pnl).

Reads the per-trade CSV produced by `cyclops.backtest.runner`. Writes a
JSON report next to it. CLI: `python -m cyclops.validate.permutation --csv ...`
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd

from ..backtest.settlement import settle_legacy
from ..conventions import FEE_RATE


def _settle_vector(won: np.ndarray, shares: np.ndarray, stake: np.ndarray,
                    fee_rate: float) -> np.ndarray:
    """Vectorized version of settle_legacy on numpy arrays."""
    # Win payoff: profit = shares - stake; if positive, take 2% fee.
    payoff = shares - stake
    win_pnl = np.where(payoff > 0, payoff * (1 - fee_rate), payoff)
    loss_pnl = -stake
    return np.where(won, win_pnl, loss_pnl)


def permutation_test(
    fired: pd.DataFrame,
    n_permutations: int = 1000,
    seed: int = 42,
    fee_rate: float = FEE_RATE,
) -> Dict:
    """Run the outcome-shuffle permutation test.

    Expects `fired` to contain columns: direction, outcome_truth, shares,
    stake_usd, pnl_usd.
    """
    if fired.empty:
        return {"n_trades": 0, "observed_mean_pnl": float("nan"),
                "p_value": float("nan"), "n_permutations": n_permutations}

    direction = fired["direction"].values.astype("<U4")
    outcome = fired["outcome_truth"].values.astype("<U4")
    shares = fired["shares"].values.astype("float64")
    stake = fired["stake_usd"].values.astype("float64")
    observed_pnl = fired["pnl_usd"].values.astype("float64")
    observed_mean = float(observed_pnl.mean())

    rng = np.random.default_rng(seed)
    n = len(fired)
    null_means = np.empty(n_permutations, dtype="float64")
    for i in range(n_permutations):
        perm = rng.permutation(outcome)
        won_null = (direction == perm)
        pnl_null = _settle_vector(won_null, shares, stake, fee_rate)
        null_means[i] = pnl_null.mean()

    p_value = float((null_means >= observed_mean).sum() + 1) / float(n_permutations + 1)
    return {
        "n_trades": int(n),
        "observed_mean_pnl": observed_mean,
        "observed_total_pnl": float(observed_pnl.sum()),
        "observed_wr": float((direction == outcome).mean()),
        "p_value": p_value,
        "n_permutations": int(n_permutations),
        "null_mean": float(null_means.mean()),
        "null_std": float(null_means.std()),
        "null_q05": float(np.quantile(null_means, 0.05)),
        "null_q95": float(np.quantile(null_means, 0.95)),
        "null_q99": float(np.quantile(null_means, 0.99)),
    }


def _verdict(p_value: float, alpha: float = 0.05) -> str:
    if np.isnan(p_value):
        return "no_trades"
    return "PASS" if p_value < alpha else "FAIL"


def main():
    ap = argparse.ArgumentParser(description="Cyclops G3 permutation test")
    ap.add_argument("--csv", required=True, type=Path,
                    help="per-trade CSV produced by cyclops.backtest.runner")
    ap.add_argument("--n", type=int, default=1000,
                    help="number of permutations (default 1000)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--fee", type=float, default=FEE_RATE)
    ap.add_argument("--out", type=Path, default=None,
                    help="JSON output path (default: <csv>.permutation.json)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    fired = df[df["fired"] == True].copy()
    result = permutation_test(fired, n_permutations=args.n, seed=args.seed,
                              fee_rate=args.fee)
    result["csv"] = str(args.csv)
    result["verdict"] = _verdict(result["p_value"])

    out_path = args.out or args.csv.with_suffix(".permutation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"[perm]  n_trades={result['n_trades']}  "
          f"observed_mean=${result['observed_mean_pnl']:+.4f}  "
          f"observed_wr={result['observed_wr']:.3f}")
    print(f"[perm]  null_mean=${result['null_mean']:+.4f}  "
          f"null_std=${result['null_std']:.4f}  "
          f"null_q95=${result['null_q95']:+.4f}  "
          f"null_q99=${result['null_q99']:+.4f}")
    print(f"[perm]  p_value={result['p_value']:.4f}  -> [{result['verdict']}]  "
          f"(N={result['n_permutations']})")
    print(f"[perm]  wrote {out_path}")


if __name__ == "__main__":
    main()
