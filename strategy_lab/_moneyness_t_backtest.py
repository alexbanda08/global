"""
moneyness_t backtest
Signal: z = px_vs_strike_bps / sqrt(max(window_s - offset_s, 1))
Fire UP if z > +thr, DOWN if z < -thr
Sweep thr over [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
"""

import sys, os, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

CELLS = [
    ("btc", "5m",  300),
    ("btc", "15m", 900),
    ("eth", "5m",  300),
    ("eth", "15m", 900),
    ("sol", "5m",  300),
    ("sol", "15m", 900),
]

PRIMARY_OFFSET = {300: 60, 900: 180}
SPREAD_MAX = {"btc": 0.02, "eth": 0.02, "sol": 0.025}
NOTIONAL = 25.0
THR_SWEEP = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
N_BOOT = 4000
SEED = 42

BASE = r"C:\Users\alexandre bandarra\Desktop\global"
RESULTS_DIR = os.path.join(BASE, "data", "v4", "canonical", "_results")


def realistic_pnl(vwap, won, notional=NOTIONAL):
    shares = notional / vwap
    fee = shares * 0.07 * vwap * (1 - vwap)
    if won:
        return shares - notional - fee - 0.01
    else:
        return -notional - fee - 0.01


def block_bootstrap_ci(pnl_series, day_series, n_iter=N_BOOT, seed=SEED):
    rng = np.random.default_rng(seed)
    days = np.array(sorted(day_series.unique()))
    n_days = len(days)
    means = []
    for _ in range(n_iter):
        sampled_days = rng.choice(days, size=n_days, replace=True)
        samples = []
        for d in sampled_days:
            mask = day_series == d
            samples.append(pnl_series[mask].values)
        boot_pnl = np.concatenate(samples)
        means.append(boot_pnl.mean())
    return float(np.percentile(means, 2.5))


def run_cell(asset, tf, window_s):
    path = os.path.join(RESULTS_DIR, f"dirscan_{asset}_{tf}.parquet")
    df = pd.read_parquet(path)

    # Use primary offset
    offset = PRIMARY_OFFSET[window_s]
    df = df[df["offset_s"] == offset].copy()

    spread_max = SPREAD_MAX[asset]

    # Compute z signal
    time_left = max(window_s - offset, 1)
    df["z"] = df["px_vs_strike_bps"] / np.sqrt(time_left)

    # UTC day for block bootstrap
    df["utc_day"] = (df["slot_start_s"] // 86400).astype(int)

    best = None

    for thr in THR_SWEEP:
        # UP fires: z > +thr, buy Up side
        up_mask = (
            (df["z"] > thr)
            & df["u_ok"]
            & df["u_vwap"].between(0.55, 0.92)
            & ((df["u_ask0"] - df["u_bid0"]) <= spread_max)
            & df["px_vs_strike_bps"].notna()
        )
        # DOWN fires: z < -thr, buy Down side
        dn_mask = (
            (df["z"] < -thr)
            & df["d_ok"]
            & df["d_vwap"].between(0.55, 0.92)
            & ((df["d_ask0"] - df["d_bid0"]) <= spread_max)
            & df["px_vs_strike_bps"].notna()
        )

        rows = []
        for mask, side, vwap_col, outcome_val in [
            (up_mask, "Up", "u_vwap", "Up"),
            (dn_mask, "Down", "d_vwap", "Down"),
        ]:
            sub = df[mask].copy()
            if len(sub) == 0:
                continue
            sub["won"] = sub["outcome_truth"] == outcome_val
            sub["vwap"] = sub[vwap_col]
            sub["pnl"] = sub.apply(lambda r: realistic_pnl(r["vwap"], r["won"]), axis=1)
            # implied prob de-vigged
            sub["implied"] = sub["u_vwap"] / (sub["u_vwap"] + sub["d_vwap"]) if side == "Up" else sub["d_vwap"] / (sub["u_vwap"] + sub["d_vwap"])
            rows.append(sub[["pnl", "won", "implied", "utc_day"]])

        if not rows:
            continue

        combined = pd.concat(rows, ignore_index=True)
        n = len(combined)
        if n < 25:
            continue

        wr = combined["won"].mean()
        mean_pnl = combined["pnl"].mean()
        mean_implied = combined["implied"].mean()
        wr_minus_implied = wr - mean_implied

        ci_lo = block_bootstrap_ci(combined["pnl"], combined["utc_day"])

        passes = int(mean_pnl > 0) + int(wr_minus_implied > 0) + int(ci_lo > 0)

        candidate = {
            "asset": asset,
            "tf": tf,
            "thr": thr,
            "n": n,
            "wr": wr,
            "mean_pnl": mean_pnl,
            "wr_minus_implied": wr_minus_implied,
            "block_ci_lo": ci_lo,
            "passes": passes,
            "mean_implied": mean_implied,
        }

        if best is None or passes > best["passes"] or (passes == best["passes"] and mean_pnl > best["mean_pnl"]):
            best = candidate

    return best


all_results = []
for asset, tf, window_s in CELLS:
    print(f"Running {asset}_{tf}...", flush=True)
    result = run_cell(asset, tf, window_s)
    if result is not None:
        all_results.append(result)
        print(f"  thr={result['thr']:.1f} n={result['n']} wr={result['wr']:.3f} "
              f"mean_pnl={result['mean_pnl']:.4f} wr_minus_impl={result['wr_minus_implied']:.4f} "
              f"ci_lo={result['block_ci_lo']:.4f} passes={result['passes']}")
    else:
        print(f"  No qualifying threshold found (n<25 or no valid rows)")

# Find overall best cell
if all_results:
    best_overall = max(all_results, key=lambda r: (r["passes"], r["mean_pnl"]))
    print(f"\nBest cell: {best_overall['asset']}_{best_overall['tf']} thr={best_overall['thr']}")
    print(f"  n={best_overall['n']} wr={best_overall['wr']:.4f} mean_pnl={best_overall['mean_pnl']:.4f}")
    print(f"  wr_minus_implied={best_overall['wr_minus_implied']:.4f} block_ci_lo={best_overall['block_ci_lo']:.4f}")
    print(f"  passes (out of 3): {best_overall['passes']}")

    # Determine verdict
    p = best_overall["passes"]
    if p == 3:
        verdict = "PASS"
    elif p == 2:
        verdict = "WEAK"
    else:
        verdict = "FAIL"
    print(f"  verdict: {verdict}")

    # Write CSV
    out_path = os.path.join(RESULTS_DIR, "wf_strathunt_moneyness_t.csv")
    row = {
        "hypothesis": "moneyness_t",
        "best_cell": f"{best_overall['asset']}_{best_overall['tf']}",
        "thr": best_overall["thr"],
        "n": best_overall["n"],
        "wr": round(best_overall["wr"], 4),
        "wr_minus_implied": round(best_overall["wr_minus_implied"], 4),
        "block_ci_lo": round(best_overall["block_ci_lo"], 4),
        "mean_pnl_realistic": round(best_overall["mean_pnl"], 4),
        "verdict": verdict,
        "note": f"z=px_vs_strike/sqrt(window-offset); primary_offset={PRIMARY_OFFSET}; all_cells={[(r['asset']+'_'+r['tf'], r['passes']) for r in all_results]}",
    }
    pd.DataFrame([row]).to_csv(out_path, index=False)
    print(f"\nResults written to {out_path}")
else:
    print("No results found across all cells.")
