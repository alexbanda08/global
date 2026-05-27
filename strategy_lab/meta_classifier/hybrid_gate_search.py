"""Hybrid gate search — greedy + exhaustive AND-conjunction across RF + TR + TA + Markov.

Per (asset, fire_tf, offset_bin), runs:
  1. Greedy stepwise: add gate that maximizes sum_pnl with n >= MIN_N.
  2. Top-10-from-greedy then exhaustive 2^10 = 1023 subsets via gate_search().
  3. Records top-5 stacks per cell by sum_pnl.

Outputs:
  data/v4/canonical/_results/hybrid_gate_search.csv
  data/v4/canonical/_results/hybrid_gate_search_per_fire.parquet
  data/v4/canonical/_results/hybrid_gate_search_top.csv  (top-50 overall by sum_pnl)
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"
from hybrid_backtest import gate_search, walk_forward_split, _summarize  # type: ignore

MIN_N = 30
TOP_K = 50

# Drop gates that are too sparse or too saturated (uninformative AND filter).
DROP_GATES = {"g_rf_strong"}  # near-0 count

# offset bins per timeframe
OFFSET_BINS_5M = [(60, 150), (150, 240), (240, 300)]
OFFSET_BINS_15M = [(60, 240), (240, 480), (480, 840)]


def offset_bin_label_5m(off: int) -> str | None:
    for lo, hi in OFFSET_BINS_5M:
        if lo <= off < hi:
            return f"{lo}-{hi}"
    if off == 300:
        return "240-300"
    return None


def offset_bin_label_15m(off: int) -> str | None:
    for lo, hi in OFFSET_BINS_15M:
        if lo <= off < hi:
            return f"{lo}-{hi}"
    if off == 840:
        return "480-840"
    return None


def greedy_stack(df: pd.DataFrame, candidates: list[str], pnl_col: str = "pnl_legacy_usd",
                 min_n: int = MIN_N) -> tuple[list[str], dict]:
    """Greedy stepwise: start empty, add gate that maximizes sum_pnl × WR."""
    chosen: list[str] = []
    remaining = list(candidates)
    pnl_arr = df[pnl_col].astype("float64").values
    mask = np.ones(len(df), dtype=bool)
    best_summary = {
        "n": int(mask.sum()),
        "wins": int((pnl_arr[mask] > 0).sum()),
        "sum_pnl": float(pnl_arr[mask].sum()),
    }
    while remaining:
        best_gate = None
        best_score = -1e18
        best_new_summary = None
        for g in remaining:
            m_g = df[g].fillna(False).astype(bool).values
            m_new = mask & m_g
            n_new = int(m_new.sum())
            if n_new < min_n:
                continue
            pnl_new = pnl_arr[m_new]
            wins = int((pnl_new > 0).sum())
            sum_pnl = float(pnl_new.sum())
            wr = wins / n_new
            score = sum_pnl * wr   # objective: high $$ + high accuracy
            if score > best_score:
                best_score = score
                best_gate = g
                best_new_summary = {"n": n_new, "wins": wins, "sum_pnl": sum_pnl}
        if best_gate is None:
            break
        # only accept if sum_pnl strictly improved
        if best_new_summary["sum_pnl"] <= best_summary["sum_pnl"]:
            break
        chosen.append(best_gate)
        remaining.remove(best_gate)
        mask &= df[best_gate].fillna(False).astype(bool).values
        best_summary = best_new_summary
    return chosen, best_summary


def cell_summary(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> dict:
    """Headline stats for a cell. NaN-safe."""
    n = len(df)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": float("nan"), "sum_pnl": 0.0, "dpt": float("nan")}
    pnl = df[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    return {
        "n": n, "wins": wins, "WR": wins / n,
        "sum_pnl": float(pnl.sum()), "dpt": float(pnl.mean()),
    }


def max_dd_from_pnl(pnl_series: np.ndarray) -> float:
    if len(pnl_series) == 0:
        return 0.0
    cum = np.cumsum(pnl_series)
    peak = np.maximum.accumulate(cum)
    return float((peak - cum).max())


def sharpe_per_day(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> float:
    if len(df) < 2:
        return float("nan")
    day = pd.to_datetime(df["fire_us"], unit="us", utc=True).dt.floor("D")
    daily = df.assign(_day=day).groupby("_day")[pnl_col].sum()
    if daily.shape[0] < 2:
        return float("nan")
    mu = float(daily.mean()); sig = float(daily.std(ddof=1))
    if sig <= 0:
        return float("nan")
    return mu / sig * np.sqrt(daily.shape[0])


def run_per_cell(df: pd.DataFrame, candidates: list[str], cell_label: dict,
                 pnl_col: str = "pnl_legacy_usd") -> list[dict]:
    """For one (asset, tf, offset_bin) cell, return list of result rows."""
    rows = []
    # baseline (no gates)
    base = cell_summary(df, pnl_col)
    base.update(cell_label)
    base["gate_stack"] = "(baseline)"
    base["k"] = 0
    base["max_DD"] = max_dd_from_pnl(df.sort_values("fire_us")[pnl_col].values)
    base["sharpe_d"] = sharpe_per_day(df, pnl_col)
    rows.append(base)

    if len(df) < MIN_N * 2 or not candidates:
        return rows

    # Greedy stack
    chosen, _ = greedy_stack(df, candidates, pnl_col=pnl_col, min_n=MIN_N)
    if chosen:
        mask = np.ones(len(df), dtype=bool)
        for g in chosen:
            mask &= df[g].fillna(False).astype(bool).values
        sub = df.iloc[mask]
        s = cell_summary(sub, pnl_col); s.update(cell_label)
        s["gate_stack"] = "&".join(chosen)
        s["k"] = len(chosen)
        s["max_DD"] = max_dd_from_pnl(sub.sort_values("fire_us")[pnl_col].values)
        s["sharpe_d"] = sharpe_per_day(sub, pnl_col)
        s["search_type"] = "greedy"
        rows.append(s)

    # Exhaustive top-10 from greedy ranking — i.e. select 10 gates with highest single-gate sum_pnl
    # then 2^10 exhaustive
    single_results = []
    for g in candidates:
        m = df[g].fillna(False).astype(bool).values
        n_g = int(m.sum())
        if n_g < MIN_N:
            continue
        pnl_sub = df[pnl_col].astype("float64").values[m]
        single_results.append((g, n_g, int((pnl_sub > 0).sum()) / n_g, float(pnl_sub.sum())))
    # sort by sum_pnl
    single_results.sort(key=lambda x: -x[3])
    top10_gates = [r[0] for r in single_results[:10]]

    if len(top10_gates) >= 2:
        try:
            gs = gate_search(df, top10_gates, pnl_col=pnl_col, min_n=MIN_N, top_k=5)
        except Exception as e:
            print(f"  gate_search FAILED for {cell_label}: {e}")
            gs = pd.DataFrame()
        if len(gs):
            for _, r in gs.iterrows():
                cols = r["gates"].split("&")
                mask = np.ones(len(df), dtype=bool)
                for g in cols:
                    mask &= df[g].fillna(False).astype(bool).values
                sub = df.iloc[mask]
                row = cell_summary(sub, pnl_col); row.update(cell_label)
                row["gate_stack"] = r["gates"]
                row["k"] = int(r["k"])
                row["max_DD"] = max_dd_from_pnl(sub.sort_values("fire_us")[pnl_col].values)
                row["sharpe_d"] = sharpe_per_day(sub, pnl_col)
                row["search_type"] = "exhaustive_top10"
                rows.append(row)

    return rows


def main():
    print("=" * 72)
    print("HYBRID GATE SEARCH — greedy + exhaustive top-10 AND-conjunctions per cell")
    print("=" * 72)
    t0 = time.time()

    # Load joined frames
    print("\nLoading joined frames...")
    frames = {
        "s15_5m":  pd.read_parquet(RES / "s15_joined_all.parquet"),
        "v15m_15m": pd.read_parquet(RES / "v15m_joined_all.parquet"),
        "s6_5m":   pd.read_parquet(RES / "s6_joined_all.parquet"),
    }
    for k, df in frames.items():
        print(f"  {k}: {df.shape}, won={df['won'].mean():.3f}, sum_pnl={df['pnl_legacy_usd'].sum():.2f}")

    all_rows = []
    per_fire_best = []  # store per-fire records for the best stack per cell

    for ftf_label, df in frames.items():
        # gate candidates for this frame
        candidates = sorted([c for c in df.columns if c.startswith("g_") and c not in DROP_GATES])
        # drop gates with zero ones in THIS frame
        candidates = [c for c in candidates if df[c].sum() > 0]
        print(f"\n=== {ftf_label}: {len(candidates)} gate candidates ===")
        print(f"    {candidates}")

        # split by asset × offset_bin
        offset_fn = offset_bin_label_5m if ftf_label != "v15m_15m" else offset_bin_label_15m
        df = df.copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(offset_fn)
        df = df[df["offset_bin"].notna()].copy()

        for asset in ("BTC", "ETH", "SOL"):
            for ob in sorted(df["offset_bin"].unique()):
                sub = df[(df.asset == asset) & (df.offset_bin == ob)]
                if len(sub) < MIN_N * 2:
                    print(f"  {asset} {ob}: n={len(sub)} too few — skip")
                    continue
                label = {"asset": asset, "tf": ftf_label, "offset_bin": ob}
                rows = run_per_cell(sub, candidates, label)
                all_rows.extend(rows)
                # store per-fire records for the best (highest sum_pnl) non-baseline row
                non_base = [r for r in rows if r["gate_stack"] != "(baseline)"]
                if non_base:
                    best = max(non_base, key=lambda r: r["sum_pnl"])
                    cols_in_stack = best["gate_stack"].split("&")
                    mask = np.ones(len(sub), dtype=bool)
                    for g in cols_in_stack:
                        mask &= sub[g].fillna(False).astype(bool).values
                    pf = sub.iloc[mask][["slug", "asset", "fire_us", "fire_offset_s",
                                          "direction", "outcome", "won", "pnl_legacy_usd"]].copy()
                    pf["tf"] = ftf_label
                    pf["offset_bin"] = ob
                    pf["gate_stack"] = best["gate_stack"]
                    per_fire_best.append(pf)
                print(f"  {asset} {ob}: n={len(sub)} baseline_sum={cell_summary(sub)['sum_pnl']:+.1f}  "
                      f"-> best stack '{(non_base[0]['gate_stack'] if non_base else 'n/a')[:60]}' "
                      f"sum={(non_base[0]['sum_pnl'] if non_base else 0.0):+.1f}")

    # Save full table
    out_csv = RES / "hybrid_gate_search.csv"
    df_all = pd.DataFrame(all_rows)
    df_all = df_all.sort_values(["tf", "asset", "offset_bin", "sum_pnl"],
                                ascending=[True, True, True, False])
    df_all.to_csv(out_csv, index=False)
    print(f"\nWrote {out_csv} ({len(df_all):,} rows)")

    # top-50 overall (excluding baselines)
    top = df_all[df_all["gate_stack"] != "(baseline)"].sort_values("sum_pnl", ascending=False).head(50)
    top.to_csv(RES / "hybrid_gate_search_top.csv", index=False)
    print(f"Wrote {RES / 'hybrid_gate_search_top.csv'} (top 50)")

    # per-fire best
    if per_fire_best:
        pf_all = pd.concat(per_fire_best, ignore_index=True)
        pf_all.to_parquet(RES / "hybrid_gate_search_per_fire.parquet", index=False, compression="zstd")
        print(f"Wrote {RES / 'hybrid_gate_search_per_fire.parquet'} ({len(pf_all):,} fires)")

    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
