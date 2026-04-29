"""
polymarket_signal_grid_v2.py — Cross-asset signal grid with:
  • Merge-aware exits (sell-direct OR buy-other-side+merge, whichever is better)
  • Binance-reversal trailing exit (lock profits when Binance reverts mid-window)

Datasets:
  data/polymarket/{btc,eth,sol}_features_v3.csv
  data/polymarket/{btc,eth,sol}_trajectories_v3.csv
  data/binance/{btc,eth,sol}_klines_window.csv

Tested signal: sig_ret5m_q20 (top/bot 20% by |ret_5m|, computed per asset+timeframe).

Exit rules tested:
  E0  hold-to-resolution
  E1  S2_stop35 direct (sell own bid only)
  E2  S2_stop35 merge-aware (better of bid OR 1-other_ask)
  E3  Binance-reversal @ 25 bps (close window early if BTC reverses 25bp from entry)
  E4  Binance-reversal @ 50 bps
  E5  E3 + merge-aware bid lookup at exit bucket
  E6  E4 + merge-aware bid lookup

Output:
  results/polymarket/signal_grid_v2.csv
  reports/POLYMARKET_SIGNAL_GRID_V2.md
"""
from __future__ import annotations
import os
import pickle
import tempfile
from pathlib import Path
import numpy as np
import pandas as pd

from polymarket_stats import equity_curve_stats

HERE = Path(__file__).resolve().parent
RNG = np.random.default_rng(42)
FEE_RATE = 0.02
ASSETS = ["btc", "eth", "sol"]


# --------------- data loaders ---------------
def load_features(asset: str) -> pd.DataFrame:
    df = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_features_v3.csv")
    df["asset"] = asset
    return df


def load_trajectories(asset: str) -> dict[str, pd.DataFrame]:
    t = pd.read_csv(HERE / "data" / "polymarket" / f"{asset}_trajectories_v3.csv")
    up = t[t.outcome == "Up"].rename(columns={
        "bid_first":"up_bid_first","bid_last":"up_bid_last",
        "bid_min":"up_bid_min","bid_max":"up_bid_max",
        "ask_first":"up_ask_first","ask_last":"up_ask_last",
        "ask_min":"up_ask_min","ask_max":"up_ask_max",
    })[["slug","bucket_10s","window_start_unix",
        "up_bid_first","up_bid_last","up_bid_min","up_bid_max",
        "up_ask_first","up_ask_last","up_ask_min","up_ask_max"]]
    dn = t[t.outcome == "Down"].rename(columns={
        "bid_first":"dn_bid_first","bid_last":"dn_bid_last",
        "bid_min":"dn_bid_min","bid_max":"dn_bid_max",
        "ask_first":"dn_ask_first","ask_last":"dn_ask_last",
        "ask_min":"dn_ask_min","ask_max":"dn_ask_max",
    })[["slug","bucket_10s",
        "dn_bid_first","dn_bid_last","dn_bid_min","dn_bid_max",
        "dn_ask_first","dn_ask_last","dn_ask_min","dn_ask_max"]]
    merged = up.merge(dn, on=["slug","bucket_10s"], how="outer").sort_values(["slug","bucket_10s"])
    return {slug: g.reset_index(drop=True) for slug, g in merged.groupby("slug")}


def load_klines_1m(asset: str) -> pd.DataFrame:
    k = pd.read_csv(HERE / "data" / "binance" / f"{asset}_klines_window.csv")
    k1m = k[k.period_id == "1MIN"].copy()
    k1m["ts_s"] = (k1m.time_period_start_us // 1_000_000).astype(int)
    return k1m.sort_values("ts_s").reset_index(drop=True)[["ts_s","price_close"]]


def asof_close(k1m: pd.DataFrame, ts: int) -> float:
    idx = k1m.ts_s.searchsorted(ts, side="right") - 1
    if idx < 0:
        return float("nan")
    return float(k1m.price_close.iloc[idx])


# --------------- exit math ---------------
def best_exit_in_bucket(b, side: int, merge_aware: bool) -> float:
    """Highest exit value attainable inside a 10s bucket. side: 1=YES held, 0=NO held."""
    if side == 1:
        bid_max = b["up_bid_max"]
        ask_min = b["dn_ask_min"]
    else:
        bid_max = b["dn_bid_max"]
        ask_min = b["up_ask_min"]
    direct = bid_max if pd.notna(bid_max) else float("-inf")
    if not merge_aware:
        return float(direct) if np.isfinite(direct) else float("nan")
    merge = (1.0 - ask_min) if pd.notna(ask_min) else float("-inf")
    out = max(direct, merge)
    return float(out) if np.isfinite(out) else float("nan")


def worst_exit_in_bucket(b, side: int, merge_aware: bool) -> float:
    """Lowest exit value attainable inside a 10s bucket."""
    if side == 1:
        bid_min = b["up_bid_min"]
        ask_max = b["dn_ask_max"]
    else:
        bid_min = b["dn_bid_min"]
        ask_max = b["up_ask_max"]
    direct = bid_min if pd.notna(bid_min) else float("inf")
    if not merge_aware:
        return float(direct) if np.isfinite(direct) else float("nan")
    merge = (1.0 - ask_max) if pd.notna(ask_max) else float("inf")
    out = max(direct, merge)  # position value = better of two routes
    return float(out) if np.isfinite(out) else float("nan")


# --------------- single-market simulator ---------------
def simulate_market(row: pd.Series, traj_g: pd.DataFrame, k1m: pd.DataFrame,
                    target: float | None, stop: float | None,
                    rev_bp: int | None, merge_aware: bool,
                    hedge_hold: bool = False) -> float:
    """Per-$1 stake PnL.

    If `hedge_hold` is True, a Binance-reversal trigger does NOT exit the
    position. Instead, it BUYS the opposite side at the current bucket's
    other-side ask and HOLDS both legs to natural resolution. Total payout
    at resolution = $1 minus 2% protocol fee on the winning leg.
    """
    sig = int(row.signal)
    if sig == 1:
        entry = float(row.entry_yes_ask)
    else:
        entry = float(row.entry_no_ask)
    if not np.isfinite(entry) or entry <= 0 or entry >= 1:
        return 0.0

    ws = int(row.window_start_unix)
    btc_at_ws = asof_close(k1m, ws)

    exit_price = None
    hedge_other_entry = None  # set when hedge_hold triggers
    for _, b in traj_g.iterrows():
        bucket = int(b.bucket_10s)
        if bucket < 0:
            continue
        # Stop check (worst-case in bucket)
        if stop is not None:
            worst = worst_exit_in_bucket(b, sig, merge_aware)
            if np.isfinite(worst) and worst <= stop:
                exit_price = stop
                break
        # Target check (best-case in bucket)
        if target is not None:
            best = best_exit_in_bucket(b, sig, merge_aware)
            if np.isfinite(best) and best >= target:
                exit_price = target
                break
        # Binance-reversal check
        if rev_bp is not None and np.isfinite(btc_at_ws):
            ts_in_bucket = ws + bucket * 10
            btc_now = asof_close(k1m, ts_in_bucket)
            if np.isfinite(btc_now):
                bp = (btc_now - btc_at_ws) / btc_at_ws * 10000  # signed bps from window_start
                # If signal was UP (sig=1), reversal = BTC dropped relative to ws
                # If signal was DOWN (sig=0), reversal = BTC rose
                reverted = (sig == 1 and bp <= -rev_bp) or (sig == 0 and bp >= rev_bp)
                if reverted:
                    if hedge_hold:
                        # Buy the OPPOSITE side at its ask in this bucket; hold both legs to resolution.
                        other_ask_col = "dn_ask_min" if sig == 1 else "up_ask_min"
                        other_ask = b[other_ask_col]
                        if pd.notna(other_ask) and 0 < other_ask < 1:
                            hedge_other_entry = float(other_ask)
                            break
                        # If no other-side ask available, fall back to mid sell at bid
                        exit_now = best_exit_in_bucket(b, sig, merge_aware=False)
                        exit_price = max(0.01, min(0.99, float(exit_now))) if np.isfinite(exit_now) else entry
                        break
                    else:
                        exit_now = best_exit_in_bucket(b, sig, merge_aware)
                        if not np.isfinite(exit_now):
                            exit_now = entry
                        exit_price = max(0.01, min(0.99, float(exit_now)))
                        break

    # Resolve P&L:
    if hedge_other_entry is not None:
        # Hold both legs to resolution. Total cost basis: entry + hedge_other_entry.
        # At resolution: $1.00 from winning leg minus 2% protocol fee on its (1 - leg_entry) profit.
        outcome = int(row.outcome_up)
        sig_won = (sig == outcome)
        if sig_won:
            # Our held side wins → we get $1 on that leg, $0 on hedge leg.
            payout = 1.0 - (1.0 - entry) * FEE_RATE
        else:
            # Hedge side wins → we get $1 on hedge leg, $0 on our side.
            payout = 1.0 - (1.0 - hedge_other_entry) * FEE_RATE
        return payout - entry - hedge_other_entry

    if exit_price is None:
        won = (sig == int(row.outcome_up))
        gross = (1.0 - entry) if won else -entry
        fee = (1.0 - entry) * FEE_RATE if won else 0.0
        return gross - fee
    return exit_price - entry


# --------------- driver ---------------
def add_q20_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            ret = df.loc[m, "ret_5m"].abs()
            q20 = ret.quantile(0.80)
            sel = m & (df.ret_5m.abs() >= q20) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def add_q10_signal(df: pd.DataFrame) -> pd.DataFrame:
    """Top 10% by |ret_5m| per (asset, timeframe). Locked baseline for 5m markets."""
    df = df.copy()
    df["signal"] = -1
    for asset in df.asset.unique():
        for tf in df.timeframe.unique():
            m = (df.asset == asset) & (df.timeframe == tf)
            ret = df.loc[m, "ret_5m"].abs()
            q10 = ret.quantile(0.90)
            sel = m & (df.ret_5m.abs() >= q10) & df.ret_5m.notna()
            df.loc[sel, "signal"] = (df.loc[sel, "ret_5m"] > 0).astype(int)
    return df[df.signal != -1].copy()


def add_full_signal(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["signal"] = (df.ret_5m > 0).astype(int)
    df.loc[df.ret_5m.isna(), "signal"] = -1
    return df[df.signal != -1].copy()


def run(df: pd.DataFrame, traj_by_asset: dict, k1m_by_asset: dict,
        target, stop, rev_bp, merge_aware, hedge_hold: bool = False) -> dict:
    pnls = []
    ws_list = []
    for _, row in df.iterrows():
        traj_g = traj_by_asset[row.asset].get(row.slug)
        if traj_g is None or traj_g.empty:
            continue
        k1m = k1m_by_asset[row.asset]
        pnls.append(simulate_market(row, traj_g, k1m, target, stop, rev_bp, merge_aware, hedge_hold))
        ws_list.append(int(row.window_start_unix))
    pnls = np.array(pnls)
    ws_arr = np.array(ws_list, dtype=float) if ws_list else None
    if len(pnls) == 0:
        empty = {"n":0,"total_pnl":0.0,"ci_lo":0.0,"ci_hi":0.0,"hit":float("nan"),"roi_pct":float("nan")}
        empty.update({k: float("nan") for k in
                      ("sharpe","sortino","calmar","max_dd","mean_pnl","std_pnl")})
        empty["longest_dd_run"] = 0
        return empty
    boot = RNG.choice(pnls, size=(2000, len(pnls)), replace=True).sum(axis=1)
    eq = equity_curve_stats(pnls, trade_timestamps=ws_arr)
    return {
        "n": len(pnls),
        "total_pnl": float(pnls.sum()),
        "ci_lo": float(np.quantile(boot, 0.025)),
        "ci_hi": float(np.quantile(boot, 0.975)),
        "hit": float((pnls > 0).mean()),
        "roi_pct": float(pnls.sum() / max(len(pnls),1) * 100),
        "sharpe": eq["sharpe"],
        "sortino": eq["sortino"],
        "calmar": eq["calmar"],
        "max_dd": eq["max_dd"],
        "longest_dd_run": eq["longest_dd_run"],
        "mean_pnl": eq["mean_pnl"],
        "std_pnl": eq["std_pnl"],
    }


# --------------- parallel execution scaffolding ---------------
# AlphaPurify-inspired pattern: pickle the immutable read-only data ONCE to a tempfile,
# each worker lazy-loads it into a module-global cache on first task call.
# Eliminates per-task pickle overhead. ~8x speedup on 8-core boxes.

_WORKER_CACHE: dict = {}


def _ensure_worker_data(data_path: str) -> tuple[dict, dict]:
    """Lazy-load (traj_by_asset, k1m_by_asset) once per worker process."""
    if data_path not in _WORKER_CACHE:
        with open(data_path, "rb") as f:
            _WORKER_CACHE[data_path] = pickle.load(f)
    return _WORKER_CACHE[data_path]


def _run_cell_lazy(data_path: str, ssub: pd.DataFrame, tgt, stp, rev, merge, hedge,
                   meta: dict) -> dict:
    """Worker entry-point. Loads shared data on first call, then runs cell."""
    traj_by_asset, k1m_by_asset = _ensure_worker_data(data_path)
    r = run(ssub, traj_by_asset, k1m_by_asset, tgt, stp, rev, merge, hedge)
    r.update(meta)
    return r


def main():
    print("Loading data...")
    feats = pd.concat([load_features(a) for a in ASSETS], ignore_index=True)
    traj_by_asset = {a: load_trajectories(a) for a in ASSETS}
    k1m_by_asset  = {a: load_klines_1m(a)   for a in ASSETS}

    # Build signal universes (per asset+tf thresholds)
    feats_q10  = add_q10_signal(feats)
    feats_q20  = add_q20_signal(feats)
    feats_full = add_full_signal(feats)
    print(f"q10: {len(feats_q10)} markets ({(feats_q10.timeframe=='5m').sum()}× 5m + {(feats_q10.timeframe=='15m').sum()}× 15m)")
    print(f"q20: {len(feats_q20)} markets ({(feats_q20.timeframe=='5m').sum()}× 5m + {(feats_q20.timeframe=='15m').sum()}× 15m)")
    print(f"full: {len(feats_full)} markets")

    # Define exit rules: (label, target, stop, rev_bp, merge_aware, hedge_hold)
    rules = [
        ("E0_hold",                None,  None,  None, False, False),
        ("E1_stop35_direct",       None,  0.35,  None, False, False),
        ("E2_stop35_merge",        None,  0.35,  None, True,  False),
        ("E3_rev25",               None,  None,  25,   False, False),
        ("E4_rev50",               None,  None,  50,   False, False),
        ("E5_rev25_merge",         None,  None,  25,   True,  False),
        ("E6_rev50_merge",         None,  None,  50,   True,  False),
        ("E7_rev25_stop35_merge",  None,  0.35,  25,   True,  False),
        ("E8_rev25_hedgehold",     None,  None,  25,   False, True),
        ("E9_rev50_hedgehold",     None,  None,  50,   False, True),
        ("E10_rev15_hedgehold",    None,  None,  15,   False, True),
    ]

    # Build cell task list
    tasks = []
    for sig_label, sig_df in [("q10", feats_q10), ("q20", feats_q20), ("full", feats_full)]:
        for tf in ["5m", "15m"]:
            sub = sig_df[sig_df.timeframe == tf]
            for asset_filter in [None, "btc", "eth", "sol"]:
                ssub = sub if asset_filter is None else sub[sub.asset == asset_filter]
                if len(ssub) == 0:
                    continue
                asset_lbl = asset_filter or "ALL"
                for rule_lbl, tgt, stp, rev, merge, hedge in rules:
                    meta = {"signal": sig_label, "timeframe": tf, "asset": asset_lbl, "rule": rule_lbl}
                    tasks.append((ssub, tgt, stp, rev, merge, hedge, meta))

    # Parallel execution. Set PMK_NJOBS=1 to disable parallelism (debugging).
    n_jobs = int(os.environ.get("PMK_NJOBS", "-1"))
    rows = []
    if n_jobs == 1:
        print(f"Running {len(tasks)} cells single-threaded (PMK_NJOBS=1)...")
        for (ssub, tgt, stp, rev, merge, hedge, meta) in tasks:
            r = run(ssub, traj_by_asset, k1m_by_asset, tgt, stp, rev, merge, hedge)
            r.update(meta)
            rows.append(r)
            print(f"{meta['signal']:4s} {meta['timeframe']} {meta['asset']:3s} {meta['rule']:24s} → "
                  f"n={r['n']:4d} pnl=${r['total_pnl']:+7.2f} "
                  f"hit={r['hit']*100:5.1f}% roi={r['roi_pct']:+.2f}% "
                  f"sharpe={r.get('sharpe', float('nan')):+.2f} maxDD=${r.get('max_dd', float('nan')):.2f}")
    else:
        from joblib import Parallel, delayed
        print(f"Running {len(tasks)} cells in parallel (n_jobs={n_jobs})...")
        with tempfile.TemporaryDirectory(prefix="pmk_grid_") as tmpdir:
            data_path = os.path.join(tmpdir, "shared.pkl")
            with open(data_path, "wb") as f:
                pickle.dump((traj_by_asset, k1m_by_asset), f, protocol=pickle.HIGHEST_PROTOCOL)
            print(f"  shared data pickled to {data_path} ({os.path.getsize(data_path)/1e6:.1f} MB)")
            rows = Parallel(n_jobs=n_jobs, backend="loky", verbose=5)(
                delayed(_run_cell_lazy)(data_path, ssub, tgt, stp, rev, merge, hedge, meta)
                for (ssub, tgt, stp, rev, merge, hedge, meta) in tasks
            )
        # Print summary after all workers complete
        for r in rows:
            print(f"{r['signal']:4s} {r['timeframe']} {r['asset']:3s} {r['rule']:24s} → "
                  f"n={r['n']:4d} pnl=${r['total_pnl']:+7.2f} "
                  f"hit={r['hit']*100:5.1f}% roi={r['roi_pct']:+.2f}% "
                  f"sharpe={r.get('sharpe', float('nan')):+.2f} maxDD=${r.get('max_dd', float('nan')):.2f}")

    cols = ["signal","timeframe","asset","rule","n","total_pnl","ci_lo","ci_hi","hit","roi_pct",
            "sharpe","sortino","calmar","max_dd","longest_dd_run","mean_pnl","std_pnl"]
    df = pd.DataFrame(rows)[cols]
    out_csv = HERE / "results" / "polymarket" / "signal_grid_v2.csv"
    out_md  = HERE / "reports"  / "POLYMARKET_SIGNAL_GRID_V2.md"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)

    md = ["# Polymarket Cross-Asset × Merge-Aware × Reversal Grid — Apr 22-27\n",
          "Universe: BTC + ETH + SOL Up/Down markets (5,742 total). Signal: `sig_ret5m`. "
          "Exits include merge-aware variants (sell direct OR buy-other+merge) and Binance-reversal "
          "trailing (close early if BTC moves against signal by N bps). Fee 2% on winnings. Bootstrap n=2000. "
          "Sharpe/Sortino/MaxDD computed on chronologically-sorted equity curve, annualized via inferred trades/year.\n"]
    for sig_label in ["q10", "q20", "full"]:
        for tf in ["5m", "15m"]:
            sub = df[(df.signal == sig_label) & (df.timeframe == tf)].sort_values("total_pnl", ascending=False)
            md.append(f"\n## {sig_label} signal — {tf} — top 12 cells\n")
            md.append("| Asset | Rule | n | PnL | 95% CI | Hit% | ROI/bet | Sharpe | Sortino | MaxDD | DDrun |")
            md.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for _, r in sub.head(12).iterrows():
                md.append(
                    f"| {r['asset']} | {r['rule']} | {int(r['n'])} | "
                    f"${r['total_pnl']:+.2f} | "
                    f"[${r['ci_lo']:+.0f}, ${r['ci_hi']:+.0f}] | "
                    f"{r['hit']*100:.1f}% | {r['roi_pct']:+.2f}% | "
                    f"{r['sharpe']:+.2f} | {r['sortino']:+.2f} | "
                    f"${r['max_dd']:.2f} | {int(r['longest_dd_run'])} |"
                )
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote {out_csv} and {out_md}")


if __name__ == "__main__":
    main()
