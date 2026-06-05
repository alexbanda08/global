"""
POLYFLOW BACKTEST
Hypothesis: polymarket trade-tape flow imbalance (30s before fire)
  flow_imb = (buy_up_vol - buy_dn_vol) / (buy_up + buy_dn)
  signal = follow the flow if |flow_imb| > 0.5
Gates: favored-side vwap in [0.55,0.92], spread<=0.02 (sol 0.025), u_ok/d_ok
Cost: realistic fee = shares*0.07*vwap*(1-vwap), $0.01 tx, notional=$25
"""

import pandas as pd
import numpy as np
import sys
import os
import warnings
warnings.filterwarnings("ignore")

NOTIONAL = 25.0
FLOW_THRESH = 0.5
VWAP_LO_FAV = 0.55
VWAP_HI_FAV = 0.92
LOOKBACK_S = 30  # 30s lookback window

RESULTS_DIR = "data/v4/canonical/_results"
TRADES_DIR = "data/v4/canonical/trades_polymarket"
PRIMARY_OFFSETS = {"5m": 60, "15m": 180}


def realistic_pnl(vwap, won):
    shares = NOTIONAL / vwap
    fee = shares * 0.07 * vwap * (1 - vwap)
    if won:
        return shares - NOTIONAL - fee - 0.01
    else:
        return -NOTIONAL - fee - 0.01


def block_bootstrap_ci(pnl_arr, day_arr, n_iter=4000, seed=42):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"pnl": pnl_arr, "day": day_arr})
    days = df["day"].unique()
    if len(days) < 5:
        return np.nan
    means = []
    for _ in range(n_iter):
        sampled = rng.choice(days, size=len(days), replace=True)
        boot = df[df["day"].isin(sampled)]["pnl"].values
        means.append(boot.mean())
    return float(np.percentile(means, 2.5))


def run_cell(asset, tf, trades_df, dirscan_df, primary_offset):
    print(f"\n=== {asset.upper()} {tf} offset={primary_offset}s ===")

    ds = dirscan_df[dirscan_df["offset_s"] == primary_offset].copy()
    print(f"  Dirscan rows: {len(ds)}")
    if len(ds) == 0:
        return None

    tf_pattern = f"-{tf}-"
    tr = trades_df[trades_df["slug"].str.contains(tf_pattern, regex=False)].copy()
    print(f"  Trades rows (buy only): {len(tr)}")

    # Build per-slug lookup
    tr_by_slug = {}
    for slug, grp in tr.groupby("slug"):
        tr_by_slug[slug] = grp[["timestamp_us", "outcome", "size"]].copy()

    spread_thresh = 0.025 if asset == "sol" else 0.02

    rows = []
    for _, row in ds.iterrows():
        slug = row["slug"]
        fire_us = row["fire_us"]

        if slug not in tr_by_slug:
            continue

        slug_trades = tr_by_slug[slug]
        window_start = fire_us - LOOKBACK_S * 1_000_000
        mask = (slug_trades["timestamp_us"] <= fire_us) & (slug_trades["timestamp_us"] >= window_start)
        window = slug_trades[mask]

        if len(window) == 0:
            continue

        buy_up = window[window["outcome"] == "Up"]["size"].sum()
        buy_dn = window[window["outcome"] == "Down"]["size"].sum()
        total = buy_up + buy_dn

        if total == 0:
            continue

        flow_imb = (buy_up - buy_dn) / total

        if abs(flow_imb) < FLOW_THRESH:
            continue

        signal_side = "Up" if flow_imb > 0 else "Down"

        if signal_side == "Up":
            vwap = row["u_vwap"]
            ask0 = row["u_ask0"]
            bid0 = row["u_bid0"]
            ok = row["u_ok"]
        else:
            vwap = row["d_vwap"]
            ask0 = row["d_ask0"]
            bid0 = row["d_bid0"]
            ok = row["d_ok"]

        if not ok:
            continue
        if not (VWAP_LO_FAV <= vwap <= VWAP_HI_FAV):
            continue
        spread = ask0 - bid0
        if spread > spread_thresh:
            continue

        won = row["outcome_truth"] == signal_side
        pnl = realistic_pnl(vwap, won)

        rows.append({
            "slug": slug,
            "slot_start_s": row["slot_start_s"],
            "fire_us": fire_us,
            "signal_side": signal_side,
            "outcome_truth": row["outcome_truth"],
            "flow_imb": flow_imb,
            "u_vwap": row["u_vwap"],
            "d_vwap": row["d_vwap"],
            "vwap": vwap,
            "won": won,
            "pnl": pnl,
        })

    if len(rows) < 25:
        print(f"  Insufficient fires: {len(rows)} < 25")
        return None

    result = pd.DataFrame(rows)
    n = len(result)
    wr = result["won"].mean()
    mean_pnl = result["pnl"].mean()

    # De-vigged implied
    def get_implied(r):
        tot = r["u_vwap"] + r["d_vwap"]
        if tot == 0:
            return 0.5
        if r["signal_side"] == "Up":
            return r["u_vwap"] / tot
        else:
            return r["d_vwap"] / tot

    result["implied"] = result.apply(get_implied, axis=1)
    mean_implied = result["implied"].mean()
    wr_minus_implied = wr - mean_implied

    result["day"] = pd.to_datetime(result["slot_start_s"], unit="s", utc=True).dt.date
    ci_lo = block_bootstrap_ci(result["pnl"].values, result["day"].values, n_iter=4000)

    print(f"  n={n}, WR={wr:.3f}, implied={mean_implied:.3f}, WR-implied={wr_minus_implied:.4f}")
    print(f"  mean_pnl={mean_pnl:.4f}, block_CI_lo={ci_lo:.4f}")

    return {
        "cell": f"{asset}_{tf}",
        "n": n,
        "wr": round(wr, 4),
        "mean_implied": round(mean_implied, 4),
        "wr_minus_implied": round(wr_minus_implied, 4),
        "mean_pnl": round(mean_pnl, 4),
        "block_ci_lo": round(ci_lo, 4),
    }


# ─── MAIN ───────────────────────────────────────────────────────────────────
all_results = []

for asset in ["btc", "eth", "sol"]:
    trades_path = os.path.join(TRADES_DIR, f"{asset}.parquet")
    print(f"\nLoading trades for {asset}...")
    trades_df = pd.read_parquet(
        trades_path,
        columns=["timestamp_us", "slug", "outcome", "price", "size", "side"],
    )
    trades_df = trades_df[trades_df["side"] == "buy"].copy()
    trades_df = trades_df[trades_df["outcome"].isin(["Up", "Down"])].copy()
    print(f"  Buy trades: {len(trades_df)}")

    for tf in ["5m", "15m"]:
        dirscan_path = os.path.join(RESULTS_DIR, f"dirscan_{asset}_{tf}.parquet")
        if not os.path.exists(dirscan_path):
            print(f"  MISSING: {dirscan_path}")
            continue

        dirscan_df = pd.read_parquet(dirscan_path)
        primary_offset = PRIMARY_OFFSETS[tf]

        res = run_cell(asset, tf, trades_df, dirscan_df, primary_offset)
        if res is not None:
            all_results.append(res)

print("\n\n========== POLYFLOW RESULTS SUMMARY ==========")
if not all_results:
    print("NO PASSING CELLS")
    verdict_data = None
else:
    results_df = pd.DataFrame(all_results)
    print(results_df.to_string(index=False))

    best_idx = results_df["block_ci_lo"].idxmax()
    best = results_df.iloc[best_idx]
    print(f"\nBEST CELL: {best['cell']} n={best['n']} WR={best['wr']:.3f} "
          f"WR-implied={best['wr_minus_implied']:.4f} mean_pnl={best['mean_pnl']:.4f} "
          f"block_CI_lo={best['block_ci_lo']:.4f}")

    out_path = os.path.join(RESULTS_DIR, "wf_strathunt_polyflow.csv")
    results_df.to_csv(out_path, index=False)
    print(f"Results written to: {out_path}")
