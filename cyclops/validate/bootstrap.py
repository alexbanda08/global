"""G4: bootstrap confidence interval on mean per-trade PnL.

Resamples the fired-trade PnL vector with replacement N times. The 95% CI on
the mean is the 2.5%-97.5% quantile band of the bootstrap distribution. We
PASS if the lower bound > 0 (the observed positive edge is unlikely to be a
small-sample artifact).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd


def bootstrap_mean_ci(
    fired: pd.DataFrame,
    n_boot: int = 10_000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Dict:
    if fired.empty:
        return {"n_trades": 0, "observed_mean_pnl": float("nan"),
                "ci_lower": float("nan"), "ci_upper": float("nan"),
                "n_boot": n_boot}
    pnl = fired["pnl_usd"].values.astype("float64")
    n = pnl.size
    observed = float(pnl.mean())

    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    samples = pnl[idx]
    boot_means = samples.mean(axis=1)
    lo = float(np.quantile(boot_means, alpha / 2))
    hi = float(np.quantile(boot_means, 1 - alpha / 2))
    return {
        "n_trades": int(n),
        "observed_mean_pnl": observed,
        "ci_lower": lo,
        "ci_upper": hi,
        "n_boot": int(n_boot),
        "alpha": float(alpha),
        "frac_negative_draws": float((boot_means <= 0).mean()),
    }


def _verdict(ci_lower: float) -> str:
    if np.isnan(ci_lower):
        return "no_trades"
    return "PASS" if ci_lower > 0 else "FAIL"


def main():
    ap = argparse.ArgumentParser(description="Cyclops G4 bootstrap CI")
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--n", type=int, default=10_000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    fired = df[df["fired"] == True].copy()
    result = bootstrap_mean_ci(fired, n_boot=args.n, seed=args.seed, alpha=args.alpha)
    result["csv"] = str(args.csv)
    result["verdict"] = _verdict(result["ci_lower"])

    out_path = args.out or args.csv.with_suffix(".bootstrap.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))

    print(f"[boot]  n_trades={result['n_trades']}  "
          f"observed=${result['observed_mean_pnl']:+.4f}")
    print(f"[boot]  CI [{1-result['alpha']:.0%}]: "
          f"${result['ci_lower']:+.4f} .. ${result['ci_upper']:+.4f}")
    print(f"[boot]  P(mean ≤ 0) = {result['frac_negative_draws']:.4f}  "
          f"-> [{result['verdict']}]  (N={result['n_boot']})")
    print(f"[boot]  wrote {out_path}")


if __name__ == "__main__":
    main()
