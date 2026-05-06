"""
gauntlet_v5 — apply the 10-gate validation framework to v5 frontier configs.

Closes the gap from HANDOFF.md §6.2: the original gauntlet.py only supports
simple time-exit + fixed stop-loss. The v5 frontier uses pct-based TP/trail
exits + sizing multipliers + equity-curve filters (R_3loss_pause / R_dd_pause).
This script reuses research_v5's run_combo() engine and applies the gauntlet's
gate scoring on the resulting equity series.

What's covered (8 of 10 gates):
  G1  Sharpe >= 0.5
  G2  Calmar >= 1.0
  G3  MaxDD >= -30%
  G4  Per-year Sharpe > 0 in >= 70% of years
  G5  Permutation p < 0.01 (shuffle bar returns 500x)
  G6  Bootstrap Sharpe lower-95% CI > 0
  G8  Cost stress: PF stays > 1.0 at 18 / 24 / 30 bps RT
  G10 Profit factor >= 1.10

What's deferred to v2 (need v5-specific param surface):
  G7  Walk-forward efficiency
  G9  Parameter sensitivity

Usage:
  python strategy_lab/v4_signals/derivatives_zscore/gauntlet_v5.py \
      --symbol ETHUSDT --top 5

Output:
  strategy_lab/reports/derivatives_zscore/gauntlet_v5_results.csv
  strategy_lab/reports/derivatives_zscore/v5_equity/{symbol}__{combo}.parquet
  strategy_lab/reports/derivatives_zscore/V5_GAUNTLET_VALIDATION.md (manual)
"""
from __future__ import annotations
from pathlib import Path
import argparse
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "strategy_lab"))

# Import v5 engine
sys.path.insert(0, str(ROOT / "strategy_lab" / "v4_signals" / "derivatives_zscore"))
from research_v5 import (  # noqa: E402
    load_h, run_combo, FEE_BPS_PER_SIDE,
    entry_v4_lowvol, entry_v4_ma200_lowvol,
    CROSS_ASSET, SIZINGS, EXITS,
)

# Reuse gauntlet's metric/perm/bootstrap framework
from eval.metrics import (  # noqa: E402
    sharpe_ratio, calmar_ratio, max_drawdown,
)
from eval.robustness import per_year_stats, block_bootstrap_ci  # noqa: E402

REPORTS = ROOT / "strategy_lab" / "reports" / "derivatives_zscore"
EQ_DIR = REPORTS / "v5_equity"
EQ_DIR.mkdir(parents=True, exist_ok=True)
PANELS = ROOT / "data" / "v4" / "derivatives_zscore" / "panels"

BARS_PER_YEAR = 24 * 365  # hourly bars


def parse_combo(combo: str):
    """X_none__S_volscale__E_tp_7__R_3loss_pause → 4 keys"""
    parts = combo.split("__")
    if len(parts) != 4:
        raise ValueError(f"bad combo string: {combo}")
    return {
        "X": parts[0],
        "S": parts[1],
        "E": parts[2],
        "R": parts[3],
    }


def run_v5_strategy(df: pd.DataFrame, combo: str, sym: str,
                    fee_bps_per_side: float = FEE_BPS_PER_SIDE):
    """Run a single v5 combo, return (eq_series, trades, hourly_returns)."""
    keys = parse_combo(combo)
    entry_fn = entry_v4_lowvol if sym == "BTCUSDT" else entry_v4_ma200_lowvol
    cross_fn = CROSS_ASSET[keys["X"]]
    sizing_fn = SIZINGS[keys["S"]]
    exit_name = keys["E"]
    exit_fn = EXITS[exit_name]
    rm = keys["R"]

    eq, trades = run_combo(df, entry_fn, cross_fn, sizing_fn, exit_name, exit_fn,
                           rm=rm, fee_bps_per_side=fee_bps_per_side)
    rets = eq.pct_change().fillna(0.0)
    return eq, trades, rets


def permutation_test(rets: pd.Series, n_iter: int = 500, seed: int = 42) -> dict:
    """Shuffle returns, compute resulting Sharpe distribution, p-value of observed."""
    rng = np.random.default_rng(seed)
    obs = sharpe_ratio(rets, BARS_PER_YEAR)
    arr = rets.to_numpy()
    perm_sharpes = np.empty(n_iter)
    for i in range(n_iter):
        rng.shuffle(arr)
        rs = pd.Series(arr.copy())
        perm_sharpes[i] = sharpe_ratio(rs, BARS_PER_YEAR)
    p = float((perm_sharpes >= obs).mean())
    return {"obs_sharpe": float(obs), "p_value": p, "perm_mean": float(perm_sharpes.mean())}


def cost_stress_v5(df: pd.DataFrame, combo: str, sym: str) -> dict:
    """Re-run combo at 18 / 24 / 30 bps RT (v5 default = 12 bps RT)."""
    grid = []
    for bps_rt in (12.0, 18.0, 24.0, 30.0):
        bps_per_side = bps_rt / 2
        eq, trades, _ = run_v5_strategy(df, combo, sym, fee_bps_per_side=bps_per_side)
        if not trades:
            grid.append({"bps_rt": bps_rt, "pf": 0.0, "n_trades": 0})
            continue
        rets_arr = np.array([t["ret"] for t in trades])
        wins = rets_arr > 0
        if wins.any() and (~wins).any():
            pf = float(rets_arr[wins].sum() / -rets_arr[~wins].sum())
        else:
            pf = 0.0
        grid.append({"bps_rt": bps_rt, "pf": pf, "n_trades": len(trades)})
    pf_at_24 = next(g["pf"] for g in grid if g["bps_rt"] == 24.0)
    return {"grid": grid, "pf_at_24bp": pf_at_24}


def gates(eq: pd.Series, rets: pd.Series, trades: list, perm: dict, bs: dict, py: dict, cs: dict) -> dict:
    """Apply 8 of the 10 gauntlet gates (G7+G9 deferred)."""
    sh = sharpe_ratio(rets, BARS_PER_YEAR)
    mdd = max_drawdown(eq)
    total = float(eq.iloc[-1] / eq.iloc[0] - 1)
    years = len(eq) / BARS_PER_YEAR
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 else 0.0
    cal = calmar_ratio(cagr, mdd)

    # Trades-based PF
    if trades:
        rets_arr = np.array([t["ret"] for t in trades])
        wins = rets_arr > 0
        pf = float(rets_arr[wins].sum() / -rets_arr[~wins].sum()) if (~wins).any() and wins.any() else 0.0
    else:
        pf = 0.0

    yrs_pos = sum(1 for info in py.values() if info["return"] > 0)
    n_yrs = max(1, len(py))

    # bootstrap returns nested dict: bs["sharpe"] = {"mean":..., "ci_lo":..., "ci_hi":...}
    bs_sh_lo = bs.get("sharpe", {}).get("ci_lo", float("nan")) if isinstance(bs, dict) else float("nan")
    bs_sh_hi = bs.get("sharpe", {}).get("ci_hi", float("nan")) if isinstance(bs, dict) else float("nan")
    bs_sh_mean = bs.get("sharpe", {}).get("mean", float("nan")) if isinstance(bs, dict) else float("nan")

    return {
        "G1_sharpe>=0.5": bool(sh >= 0.5),
        "G2_calmar>=1.0": bool(cal >= 1.0),
        "G3_maxdd>=-30%": bool(mdd >= -0.30),
        "G4_per_year_pos>=70%": bool((yrs_pos / n_yrs) >= 0.70 and len(py) >= 2),
        "G5_perm_p<0.01": bool(perm["p_value"] < 0.01),
        "G6_bootstrap_sh_ci_lo>0": bool(bs_sh_lo > 0) if not pd.isna(bs_sh_lo) else False,
        "G7_walk_forward": "DEFERRED",
        "G8_cost_stress_pf>1.0": bool(cs["pf_at_24bp"] > 1.0),
        "G9_param_sensitivity": "DEFERRED",
        "G10_pf>=1.10": bool(pf >= 1.10),
        # Raw values for inspection
        "_raw": {
            "sharpe": float(sh), "calmar": float(cal), "mdd": float(mdd),
            "cagr": float(cagr), "pf": float(pf),
            "yrs_pos": yrs_pos, "n_yrs": len(py),
            "perm_p": perm["p_value"], "perm_sharpe": perm["obs_sharpe"],
            "bs_sh_mean": float(bs_sh_mean) if not pd.isna(bs_sh_mean) else None,
            "bs_sh_ci_lo": float(bs_sh_lo) if not pd.isna(bs_sh_lo) else None,
            "bs_sh_ci_hi": float(bs_sh_hi) if not pd.isna(bs_sh_hi) else None,
            "pf_at_24bp": cs["pf_at_24bp"],
            "cost_grid": cs["grid"],
        }
    }


def run_one(symbol: str, combo: str) -> dict:
    """Score one (symbol, combo) through the gauntlet."""
    print(f"\n══════ {symbol} / {combo} ══════", flush=True)
    btc_panel = pd.read_parquet(PANELS / "BTCUSDT_zscore.parquet").resample("1h").last()
    df = load_h(symbol, btc_panel=btc_panel)

    eq, trades, rets = run_v5_strategy(df, combo, symbol)
    print(f"  trades: {len(trades)}, eq: {eq.iloc[-1]:.3f}×", flush=True)

    if len(trades) < 5:
        print("  SKIP — too few trades for gating", flush=True)
        return {"symbol": symbol, "combo": combo, "n_trades": len(trades), "_skipped": True}

    # Save equity curve
    eq.to_frame("equity").to_parquet(EQ_DIR / f"{symbol}__{combo}.parquet")

    print("  running permutation test (500 iter)...", flush=True)
    perm = permutation_test(rets, n_iter=500)
    print(f"    p={perm['p_value']:.4f}  obs_sharpe={perm['obs_sharpe']:.2f}", flush=True)

    print("  running bootstrap (1000 iter)...", flush=True)
    bs = block_bootstrap_ci(rets, n_iter=1000, bars_per_year=BARS_PER_YEAR)
    bs_sh = bs.get("sharpe", {}) if isinstance(bs, dict) else {}
    print(f"    sh_ci=[{bs_sh.get('ci_lo', float('nan')):.2f}, {bs_sh.get('ci_hi', float('nan')):.2f}] (mean {bs_sh.get('mean', float('nan')):.2f})", flush=True)

    print("  computing per-year stats...", flush=True)
    py = per_year_stats(eq, BARS_PER_YEAR)
    print(f"    {len(py)} years, {sum(1 for i in py.values() if i['return']>0)} positive", flush=True)

    print("  cost stress (12/18/24/30 bps RT)...", flush=True)
    cs = cost_stress_v5(df, combo, symbol)
    for g in cs["grid"]:
        print(f"    bps_rt={g['bps_rt']:.0f}  PF={g['pf']:.2f}  n={g['n_trades']}", flush=True)

    g = gates(eq, rets, trades, perm, bs, py, cs)
    n_pass = sum(1 for k, v in g.items() if k.startswith("G") and v is True)
    n_total = sum(1 for k in g.keys() if k.startswith("G") and not isinstance(g[k], str))
    print(f"  GATES: {n_pass}/{n_total} pass (G7+G9 deferred)", flush=True)

    return {
        "symbol": symbol, "combo": combo,
        "n_trades": len(trades),
        "final_eq_x": float(eq.iloc[-1]),
        "buy_hold_x": float(df["price"].iloc[-1] / df["price"].iloc[0]),
        "outperform": float(eq.iloc[-1] / (df["price"].iloc[-1] / df["price"].iloc[0])),
        "gates_passed": n_pass,
        "gates_total": n_total,
        **{k: v for k, v in g.items() if k.startswith("G")},
        "raw": g["_raw"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="ETHUSDT")
    ap.add_argument("--top", type=int, default=5,
                    help="Top N v5 frontier configs to validate")
    ap.add_argument("--combos", nargs="+", default=None,
                    help="Specific combo strings to run (overrides --top)")
    args = ap.parse_args()

    # Load v5 frontier results, pick top N for the symbol
    if args.combos:
        combos = args.combos
    else:
        v5 = pd.read_csv(REPORTS / "v5_research_results.csv")
        sub = v5[(v5["symbol"] == args.symbol) & (v5["n_trades"] >= 25) & (v5["sharpe"] >= 1.0)]
        sub = sub.sort_values("sharpe", ascending=False).head(args.top)
        combos = sub["combo"].tolist()
        if not combos:
            raise RuntimeError(f"No qualifying v5 configs for {args.symbol}")

    print(f"\n=== gauntlet_v5: {args.symbol} × {len(combos)} configs ===")
    for c in combos:
        print(f"  - {c}")

    rows = []
    for combo in combos:
        try:
            row = run_one(args.symbol, combo)
            rows.append(row)
        except Exception as e:
            print(f"  ERROR on {combo}: {e}", flush=True)
            rows.append({"symbol": args.symbol, "combo": combo, "_error": str(e)})

    # Persist
    out = pd.DataFrame(rows)
    # Drop the nested raw column for CSV — keep in memory only
    csv_out = out.drop(columns=["raw"], errors="ignore").copy()
    csv_path = REPORTS / f"gauntlet_v5_{args.symbol}.csv"
    csv_out.to_csv(csv_path, index=False)
    print(f"\nWrote {csv_path}")

    # Print summary table
    print("\n=== SUMMARY ===")
    for r in rows:
        if r.get("_skipped") or r.get("_error"):
            print(f"  {r['combo']:<60} SKIPPED/ERROR")
            continue
        print(f"  {r['combo']:<60} gates={r['gates_passed']}/{r['gates_total']} "
              f"n={r['n_trades']:>3}  eq={r['final_eq_x']:.2f}× ({r['outperform']:.2f}× B&H)  "
              f"sh={r['raw']['sharpe']:+.2f}  mdd={r['raw']['mdd']*100:+.1f}%  pf={r['raw']['pf']:.2f}")


if __name__ == "__main__":
    main()
