"""
V68 — Walk-forward sleeve-weight optimizer over V52's 8 underlying sleeves.

Borrowed structurally from QuantMuse's `FactorOptimizer` (scipy maximization
over a Sharpe objective), with three guardrails added against the V25/V27
overfit-trap lesson:

  1. WALK-FORWARD ONLY.  Train weights on a 18-month IS window, lock them,
     evaluate on the next 6-month OOS window. Never optimize on the full
     history.
  2. L2 REGULARIZATION toward equal-weight (lambda >= 0.5). Drives the
     optimizer toward 1/n unless evidence is strong.
  3. WEIGHT BOUNDS w_i in [0.5/n, 2/n] = [0.0625, 0.25]. No sleeve can
     go to zero (preserves diversification) and no sleeve can dominate.

8 V52 sleeves:
  CCI_ETH_4h, STF_SOL_4h, STF_AVAX_4h, LATBB_AVAX_4h    (V41 core)
  MFI_SOL, VP_LINK, SVD_AVAX, MFI_ETH                   (V52 diversifiers)

Comparison set:
  - Equal-weight (1/8 each)             baseline
  - V52 current implicit weights        champion to beat
  - V68 OPT (walk-forward optimized)    candidate

If V68 OPT clears Sharpe lift >= +0.10 vs V52 AND non-worse MDD,
it is the V69 candidate (composed with V67 L=1.75 leverage).
"""
from __future__ import annotations
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.run_v52_hl_gates import (
    V41_VARIANT_MAP, DIV_SPECS, build_v41_sleeve, build_diversifier, build_v52_hl,
)

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6

# Walk-forward windows (4h bars). Tightened for multi-fold evaluation.
# Total dataset = 5001 bars (~27mo). With 12m IS / 3m OOS = ~4 folds.
IS_BARS = int(12 * 30 * 6)    # 12 months ~= 2160 bars
OOS_BARS = int(3 * 30 * 6)    # 3 months ~= 540 bars

# Optimizer config
LAMBDA_REG = 0.5              # L2 toward equal-weight; 0.0 disables, >=0.5 strong
W_LO = 0.0625                 # 0.5/8
W_HI = 0.25                   # 2.0/8


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def headline(eq: pd.Series, label: str) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0
    return {
        "label": label,
        "sharpe": round(sh, 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 3),
        "n_bars": int(len(eq)),
    }


# ---------------------------------------------------------------------------
# Build the 8 sleeve return series
# ---------------------------------------------------------------------------

def build_eight_sleeves() -> pd.DataFrame:
    """Return DataFrame: rows=4h bars on common index, cols=8 sleeve names,
    values=per-bar simple returns."""
    print("Building 4 V41 core sleeves...")
    v41 = {}
    for s in V41_VARIANT_MAP:
        v41[s] = build_v41_sleeve(s).pct_change().fillna(0)
        print(f"  {s}: {len(v41[s])} bars, total_ret={float((1+v41[s]).prod()-1):+.3f}")

    print("Building 4 V52 diversifier sleeves...")
    div = {}
    for spec in DIV_SPECS:
        name = spec[0]
        div[name] = build_diversifier(name).pct_change().fillna(0)
        print(f"  {name}: {len(div[name])} bars, total_ret={float((1+div[name]).prod()-1):+.3f}")

    all_returns = {**v41, **div}
    sleeves = list(all_returns.keys())
    common_idx = None
    for s, r in all_returns.items():
        common_idx = r.index if common_idx is None else common_idx.intersection(r.index)
    df = pd.DataFrame({s: all_returns[s].reindex(common_idx) for s in sleeves})
    print(f"Common index: {len(df)} bars, {df.index[0]} -> {df.index[-1]}")
    return df


# ---------------------------------------------------------------------------
# Walk-forward optimizer
# ---------------------------------------------------------------------------

def neg_sharpe_l2(w: np.ndarray, R: np.ndarray, w_eq: np.ndarray, lam: float) -> float:
    """Objective: minimize ( -Sharpe + lambda * ||w - w_eq||^2 )."""
    blend = R @ w
    sd = blend.std()
    sh = (blend.mean() / sd) * np.sqrt(BPY) if sd > 1e-12 else 0.0
    penalty = lam * float(np.sum((w - w_eq) ** 2))
    return float(-sh + penalty)


def optimize_weights(R_is: np.ndarray, n: int, lam: float = LAMBDA_REG) -> np.ndarray:
    """Constraints: sum(w)=1, w_i in [W_LO, W_HI]."""
    w_eq = np.ones(n) / n
    cons = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bnds = [(W_LO, W_HI)] * n
    res = minimize(
        neg_sharpe_l2, x0=w_eq, args=(R_is, w_eq, lam),
        method="SLSQP", bounds=bnds, constraints=cons,
        options={"maxiter": 200, "ftol": 1e-8},
    )
    if not res.success:
        return w_eq
    w = res.x / res.x.sum()
    return w


def walk_forward_blend(
    sleeve_rets: pd.DataFrame,
    is_bars: int = IS_BARS,
    oos_bars: int = OOS_BARS,
    lam: float = LAMBDA_REG,
) -> tuple[pd.Series, list[dict]]:
    """Walk forward: train on [t-is_bars : t], lock weights, evaluate
    next [t : t+oos_bars]. Concatenate OOS returns. Return OOS-only equity
    + per-fold weight log."""
    n_total = len(sleeve_rets)
    sleeves = list(sleeve_rets.columns)
    n = len(sleeves)
    R = sleeve_rets.to_numpy()

    folds = []
    oos_pieces = []

    start = is_bars
    while start + oos_bars <= n_total:
        is_slice = R[start - is_bars:start, :]
        w = optimize_weights(is_slice, n, lam=lam)
        oos_slice = R[start:start + oos_bars, :]
        oos_blend = oos_slice @ w
        oos_idx = sleeve_rets.index[start:start + oos_bars]
        oos_pieces.append(pd.Series(oos_blend, index=oos_idx))

        folds.append({
            "is_start": str(sleeve_rets.index[start - is_bars]),
            "is_end": str(sleeve_rets.index[start - 1]),
            "oos_start": str(sleeve_rets.index[start]),
            "oos_end": str(sleeve_rets.index[start + oos_bars - 1]),
            "weights": {s: round(float(wi), 4) for s, wi in zip(sleeves, w)},
            "oos_total_return": round(float(np.prod(1 + oos_blend) - 1), 4),
        })
        start += oos_bars

    if not oos_pieces:
        return None, []
    oos_returns = pd.concat(oos_pieces).sort_index()
    oos_eq = (1 + oos_returns).cumprod() * 10_000.0
    return oos_eq, folds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 72)
    print("V68: Walk-forward sleeve-weight optimizer")
    print(f"Lambda L2 = {LAMBDA_REG}, weight bounds [{W_LO},{W_HI}]")
    print(f"IS = {IS_BARS} bars, OOS = {OOS_BARS} bars per fold")
    print("=" * 72)

    sleeve_rets = build_eight_sleeves()

    print("\n[1] Equal-weight baseline (1/8 each)...")
    w_eq = np.ones(len(sleeve_rets.columns)) / len(sleeve_rets.columns)
    eqw_returns = sleeve_rets.to_numpy() @ w_eq
    eqw_eq = (1 + pd.Series(eqw_returns, index=sleeve_rets.index)).cumprod() * 10_000.0
    eqw_h = headline(eqw_eq, "equal_weight")
    print(f"   {eqw_h}")

    print("\n[2] V52 current implicit blend (rebuild for honest comparison)...")
    v52_eq = build_v52_hl()
    v52_h = headline(v52_eq, "v52_current")
    print(f"   {v52_h}")

    print("\n[3] V68 walk-forward optimized blend...")
    opt_eq, folds = walk_forward_blend(sleeve_rets, IS_BARS, OOS_BARS, LAMBDA_REG)
    if opt_eq is None:
        print("   not enough data for any fold")
        return 1
    opt_h = headline(opt_eq, "v68_wf_opt")
    print(f"   {opt_h}")
    print(f"   {len(folds)} folds")

    # Show fold-by-fold weights (top-3 sleeves per fold)
    print("\n[4] Per-fold weights (top-3 by weight):")
    for f in folds:
        w = f["weights"]
        top3 = sorted(w.items(), key=lambda kv: -kv[1])[:3]
        print(f"   {f['oos_start']} -> {f['oos_end']}  "
              f"top: {', '.join(f'{k}={v:.3f}' for k,v in top3)}  "
              f"oos_ret={100*f['oos_total_return']:+.1f}%")

    # Decision gate
    print("\n[5] Decision (vs V52 current):")
    sh_lift = opt_h["sharpe"] - v52_h["sharpe"]
    mdd_ok = opt_h["mdd"] >= v52_h["mdd"]
    cagr_lift_pct = (opt_h["cagr"] - v52_h["cagr"]) * 100
    verdict = "PROMOTE" if (sh_lift >= 0.10 and mdd_ok) else \
              ("MARGINAL" if sh_lift > 0 else "NO_LIFT")
    print(f"   delta_Sharpe = {sh_lift:+.3f}")
    print(f"   delta_CAGR   = {cagr_lift_pct:+.2f} pp")
    print(f"   delta_MDD    = {(opt_h['mdd']-v52_h['mdd'])*100:+.2f} pp")
    print(f"   verdict      = {verdict}")

    # Project onto V67 L=1.75 (does V68 + V67 stack work?)
    L = 1.75
    r_opt = opt_eq.pct_change().fillna(0)
    levered = (1 + (L * r_opt).clip(lower=-0.99)).cumprod() * 10_000.0
    lev_h = headline(levered, "v68_x_v67_L1.75")
    print(f"\n[6] V68 OPT x V67 (L={L}) stack:")
    print(f"   {lev_h}")
    target_pass = (lev_h["cagr"] >= 0.60 and lev_h["mdd"] >= -0.40
                   and lev_h["sharpe"] >= 2.0)
    print(f"   target_60_50_40_pass = {target_pass}")

    out = {
        "elapsed_s": round(time.time() - t0, 1),
        "config": {"lambda": LAMBDA_REG, "w_lo": W_LO, "w_hi": W_HI,
                    "is_bars": IS_BARS, "oos_bars": OOS_BARS,
                    "n_sleeves": int(len(sleeve_rets.columns))},
        "equal_weight": eqw_h,
        "v52_current": v52_h,
        "v68_opt": opt_h,
        "v68_x_v67_L1.75": lev_h,
        "verdict_vs_v52": verdict,
        "delta_sharpe_vs_v52": round(sh_lift, 3),
        "delta_cagr_pp_vs_v52": round(cagr_lift_pct, 2),
        "folds": folds,
    }
    (OUT / "v68_sleeve_weight_opt.json").write_text(
        json.dumps(out, indent=2, default=str))
    print(f"\nElapsed: {out['elapsed_s']}s")
    print(f"Wrote {OUT/'v68_sleeve_weight_opt.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
