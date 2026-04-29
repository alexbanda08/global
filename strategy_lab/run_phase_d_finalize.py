"""
Phase D finalization — add the cells unblocked by Phase C, drop flat-equity
SMC cells from the pool, rerun the portfolio hunt over the consolidated set.
"""
from __future__ import annotations

import contextlib
import importlib.util as _il
import io
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

import engine                                              # noqa: E402
from eval.perps_simulator import simulate, compute_metrics # noqa: E402

EQ_DIR = REPO / "docs" / "research" / "phase5_results" / "equity_curves" / "perps"
OUT_DIR = REPO / "docs" / "research" / "phase5_results"

BPY = 365.25 * 6
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
EXIT_2H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=120)
EXIT_1H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=5.0, max_hold=72)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)


# New cells unlocked by Phase C
NEW_CELLS = [
    # SUI via V30 family
    ("CCI_SUI_4h", "run_v30_creative.py", "sig_cci_extreme",       "SUIUSDT",  "4h", "2023-06-01", "4h"),
    ("STF_SUI_4h", "run_v30_creative.py", "sig_supertrend_flip",   "SUIUSDT",  "4h", "2023-06-01", "4h"),
    ("TTM_SUI_4h", "run_v30_creative.py", "sig_ttm_squeeze",       "SUIUSDT",  "4h", "2023-06-01", "4h"),
    ("BB_SUI_4h",  "run_v38b_smc_mixes.py", "sig_bbbreak",         "SUIUSDT",  "4h", "2023-06-01", "4h"),
    ("HTFD_SUI_4h","run_v34_expand.py",   "sig_htf_donchian_ls",   "SUIUSDT",  "4h", "2023-06-01", "4h"),
    ("LATBB_SUI_4h","run_v29_regime.py",  "sig_lateral_bb_fade",   "SUIUSDT",  "4h", "2023-06-01", "4h"),

    # TON via V30 family (short history — only 2024-08 onward)
    ("CCI_TON_4h", "run_v30_creative.py", "sig_cci_extreme",       "TONUSDT",  "4h", "2024-08-08", "4h"),
    ("STF_TON_4h", "run_v30_creative.py", "sig_supertrend_flip",   "TONUSDT",  "4h", "2024-08-08", "4h"),
    ("BB_TON_4h",  "run_v38b_smc_mixes.py", "sig_bbbreak",         "TONUSDT",  "4h", "2024-08-08", "4h"),

    # V22 Range Kalman (now enabled by 2h resample)
    ("RK_BTC_2h",  "strategies_v4.py", "v4c_range_kalman", "BTCUSDT", "2h", "2021-01-01", "2h"),
    ("RK_ETH_1h",  "strategies_v4.py", "v4c_range_kalman", "ETHUSDT", "1h", "2021-01-01", "1h"),
    ("RK_SOL_2h",  "strategies_v4.py", "v4c_range_kalman", "SOLUSDT", "2h", "2021-01-01", "2h"),
]


def _load_mod(fname):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_pd_{p.stem}", p)
    mod = _il.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        spec.loader.exec_module(mod)
    return mod


def _unpack(out):
    if isinstance(out, tuple) and len(out) == 2:
        return out[0], out[1]
    if isinstance(out, dict):
        return out.get("entries") or out.get("long_entries"), out.get("short_entries")
    raise TypeError


def build_cell(label, fname, fn_name, sym, tf, start, tf_key):
    fn = getattr(_load_mod(fname), fn_name, None)
    if fn is None:
        return None, f"{fn_name} not found in {fname}"
    try:
        df = engine.load(sym, tf, start=start, end="2026-04-24")
    except Exception as e:
        return None, f"load({sym},{tf}): {e}"
    if len(df) < 500:
        return None, f"data too short ({len(df)} bars)"
    try:
        long_sig, short_sig = _unpack(fn(df))
    except Exception as e:
        return None, f"signal: {e}"
    try:
        exit_cfg = {"4h": EXIT_4H, "2h": EXIT_2H, "1h": EXIT_1H}.get(tf_key, EXIT_4H)
        _, eq = simulate(df, long_sig, short_sig, **exit_cfg, **DEFAULT_CFG)
    except Exception as e:
        return None, f"simulate: {e}"
    return eq, None


def main():
    # Step 1: add new cells to pool
    print("=== Building new cells ===\n")
    added = 0
    for label, fname, fn_name, sym, tf, start, tf_key in NEW_CELLS:
        print(f"  {label:18s} {sym:10s} {tf}  ...  ", end="", flush=True)
        eq, err = build_cell(label, fname, fn_name, sym, tf, start, tf_key)
        if err:
            print(f"SKIP: {err}")
            continue
        eq.to_frame("equity").to_parquet(EQ_DIR / f"{label}.parquet")
        added += 1
        print(f"OK ({len(eq)} bars)")

    print(f"\nAdded {added}/{len(NEW_CELLS)} new cells")

    # Step 2: Load ALL equity curves; drop flat (near-zero variance) ones
    print("\n=== Loading pool and filtering flat cells ===\n")
    all_paths = sorted(EQ_DIR.glob("*.parquet"))
    curves = {}
    skipped_flat = []
    for p in all_paths:
        eq = pd.read_parquet(p)["equity"]
        rets = eq.pct_change().dropna()
        if rets.std() < 1e-6 or (rets == 0).mean() > 0.99:
            skipped_flat.append(p.stem)
            continue
        curves[p.stem] = eq

    print(f"Total equity curves: {len(all_paths)}")
    print(f"Flat (dropped): {len(skipped_flat)}")
    print(f"Active pool: {len(curves)}")
    if skipped_flat:
        print(f"  dropped: {', '.join(skipped_flat[:10])}{' ...' if len(skipped_flat) > 10 else ''}")

    # Step 3: align, build returns, compute correlation
    common = None
    for eq in curves.values():
        common = eq.index if common is None else common.intersection(eq.index)
    if len(common) < 500:
        print(f"common window too short: {len(common)} bars"); return

    rets = pd.DataFrame({k: curves[k].reindex(common).pct_change().fillna(0)
                         for k in sorted(curves)})
    print(f"\nCommon window: {rets.index[0].date()} -> {rets.index[-1].date()} ({len(rets)} bars)")

    corr = rets.corr()
    corr.round(3).to_csv(OUT_DIR / "perps_correlation_matrix_v2.csv")

    # Step 4: enumerate 2- and 3-sleeve combos (skip 4-sleeve for turnaround speed)
    print("\n=== Enumerating blends ===\n")
    labels = sorted(curves.keys())
    all_rows = []
    for size in (2, 3, 4):
        combos = list(itertools.combinations(labels, size))
        print(f"  {size}-sleeve combos: {len(combos)}")
        for combo in combos:
            sub = rets[list(combo)]
            port_rets = sub.mean(axis=1)
            port_eq = (1.0 + port_rets).cumprod()
            if len(port_eq) < 30:
                continue
            mu, sd = float(port_rets.mean()), float(port_rets.std())
            sh = (mu / sd) * np.sqrt(BPY) if sd > 0 else 0.0
            peak = port_eq.cummax()
            mdd = float((port_eq / peak - 1.0).min())
            yrs = (port_eq.index[-1] - port_eq.index[0]).total_seconds() / (365.25 * 86400)
            total = float(port_eq.iloc[-1] / port_eq.iloc[0] - 1)
            cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
            cal = cagr / abs(mdd) if mdd != 0 else 0.0
            yearly = {}
            pos = 0
            for yr in sorted(set(port_eq.index.year)):
                ye = port_eq[port_eq.index.year == yr]
                if len(ye) < 30:
                    continue
                r = float(ye.iloc[-1] / ye.iloc[0] - 1)
                yearly[yr] = r
                if r > 0:
                    pos += 1
            sub_corr = corr.loc[list(combo), list(combo)].values
            avg_corr = float(sub_corr[np.triu_indices(size, k=1)].mean())
            all_rows.append({
                "size": size,
                "sleeves": " + ".join(combo),
                "sharpe": round(sh, 3),
                "cagr": round(cagr, 4),
                "max_dd": round(mdd, 4),
                "calmar": round(cal, 3),
                "min_yr": round(min(yearly.values()) if yearly else 0, 4),
                "pos_yrs": pos,
                "n_yrs": len(yearly),
                "avg_pair_corr": round(avg_corr, 3),
            })
    df = pd.DataFrame(all_rows)
    df.to_csv(OUT_DIR / "perps_portfolio_hunt_v2.csv", index=False)
    print(f"\nTotal combos scored: {len(df)}")

    # Top by min_yr then sharpe
    ranked = df.sort_values(["min_yr", "sharpe"], ascending=[False, False]).head(30)
    ranked.to_csv(OUT_DIR / "perps_portfolio_top_v2.csv", index=False)

    print("\n=== TOP 30 by min-year return (expanded pool) ===\n")
    with pd.option_context("display.width", 220, "display.max_colwidth", 90):
        print(ranked.to_string(index=False))

    top_sh = df.sort_values("sharpe", ascending=False).head(15)
    print("\n=== TOP 15 by Sharpe ===\n")
    with pd.option_context("display.width", 220, "display.max_colwidth", 90):
        print(top_sh.to_string(index=False))


if __name__ == "__main__":
    main()
