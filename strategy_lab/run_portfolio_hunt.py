"""
Portfolio Hunt — V28-style combinatorial search for best multi-sleeve blends.

For each cell:
  * Run canonical simulator → save equity curve + per-cell metrics
  * Persist to phase5_results/equity_curves/perps/<label>.parquet

Then:
  * Compute pairwise correlation matrix across all cells' equity returns
  * Enumerate all 2-sleeve and 3-sleeve combinations
  * For each combo, build a yearly-rebalanced equal-weight blend
  * Score the blend: Sharpe, CAGR, MaxDD, Calmar, per-year min, correlation-
    adjusted "effective N"
  * Rank top 20 portfolios by (min-year CAGR, Sharpe)

Outputs:
  docs/research/phase5_results/perps_portfolio_hunt.csv     — all combos
  docs/research/phase5_results/perps_portfolio_top.csv      — top 20
  docs/research/phase5_results/correlation_matrix.csv       — pairwise ρ
  docs/research/phase5_results/equity_curves/perps/*.parquet
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

import engine                                                # noqa: E402
from eval.perps_simulator import simulate, compute_metrics  # noqa: E402


OUT_DIR = REPO / "docs" / "research" / "phase5_results"
EQ_DIR = OUT_DIR / "equity_curves" / "perps"
EQ_DIR.mkdir(parents=True, exist_ok=True)


BARS_PER_YEAR = {"15m": 365.25*96, "30m": 365.25*48, "1h": 365.25*24,
                 "2h":  365.25*12, "4h":  365.25*6,  "1d": 365.25}
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
DEFAULT_CFG = dict(risk_per_trade=0.03, leverage_cap=3.0,
                   fee=0.00045, slip=0.0003, init_cash=10_000.0)


# Cells to test — spans families x coins
CELLS = [
    # V30 CCI_Extreme_Rev on 5 coins
    ("CCI_BTC_4h",  "run_v30_creative.py", "sig_cci_extreme", "BTCUSDT",  "4h"),
    ("CCI_ETH_4h",  "run_v30_creative.py", "sig_cci_extreme", "ETHUSDT",  "4h"),
    ("CCI_SOL_4h",  "run_v30_creative.py", "sig_cci_extreme", "SOLUSDT",  "4h"),
    ("CCI_AVAX_4h", "run_v30_creative.py", "sig_cci_extreme", "AVAXUSDT", "4h"),
    ("CCI_LINK_4h", "run_v30_creative.py", "sig_cci_extreme", "LINKUSDT", "4h"),
    # V30 SuperTrend_Flip on 5 coins
    ("STF_BTC_4h",  "run_v30_creative.py", "sig_supertrend_flip", "BTCUSDT",  "4h"),
    ("STF_ETH_4h",  "run_v30_creative.py", "sig_supertrend_flip", "ETHUSDT",  "4h"),
    ("STF_SOL_4h",  "run_v30_creative.py", "sig_supertrend_flip", "SOLUSDT",  "4h"),
    ("STF_AVAX_4h", "run_v30_creative.py", "sig_supertrend_flip", "AVAXUSDT", "4h"),
    ("STF_LINK_4h", "run_v30_creative.py", "sig_supertrend_flip", "LINKUSDT", "4h"),
    # V30 TTM_Squeeze_Pop
    ("TTM_BTC_4h",  "run_v30_creative.py", "sig_ttm_squeeze", "BTCUSDT",  "4h"),
    ("TTM_SOL_4h",  "run_v30_creative.py", "sig_ttm_squeeze", "SOLUSDT",  "4h"),
    ("TTM_AVAX_4h", "run_v30_creative.py", "sig_ttm_squeeze", "AVAXUSDT", "4h"),
    ("TTM_DOGE_4h", "run_v30_creative.py", "sig_ttm_squeeze", "DOGEUSDT", "4h"),
    # V30 VWAP_Zfade
    ("VWZ_ETH_4h",  "run_v30_creative.py", "sig_vwap_zfade", "ETHUSDT",  "4h"),
    ("VWZ_DOGE_4h", "run_v30_creative.py", "sig_vwap_zfade", "DOGEUSDT", "4h"),
    ("VWZ_INJ_4h",  "run_v30_creative.py", "sig_vwap_zfade", "LINKUSDT", "4h"),
    # V38b BBBreak (long+short — structurally different family)
    ("BB_BTC_4h",   "run_v38b_smc_mixes.py", "sig_bbbreak", "BTCUSDT",  "4h"),
    ("BB_ETH_4h",   "run_v38b_smc_mixes.py", "sig_bbbreak", "ETHUSDT",  "4h"),
    ("BB_SOL_4h",   "run_v38b_smc_mixes.py", "sig_bbbreak", "SOLUSDT",  "4h"),
    ("BB_DOGE_4h",  "run_v38b_smc_mixes.py", "sig_bbbreak", "DOGEUSDT", "4h"),
    # V34 HTF Donchian
    ("HTFD_DOGE_4h","run_v34_expand.py", "sig_htf_donchian_ls", "DOGEUSDT", "4h"),
    ("HTFD_SOL_4h", "run_v34_expand.py", "sig_htf_donchian_ls", "SOLUSDT",  "4h"),
    # V29 Lateral_BB_Fade (the "2024+ regime is lateral" winner)
    ("LATBB_ETH_4h", "run_v29_regime.py", "sig_lateral_bb_fade", "ETHUSDT",  "4h"),
    ("LATBB_SOL_4h", "run_v29_regime.py", "sig_lateral_bb_fade", "SOLUSDT",  "4h"),
    ("LATBB_BTC_4h", "run_v29_regime.py", "sig_lateral_bb_fade", "BTCUSDT",  "4h"),
    # V29 Regime_Switch
    ("REGSW_BTC_4h", "run_v29_regime.py", "sig_regime_switch", "BTCUSDT",  "4h"),
    ("REGSW_ETH_4h", "run_v29_regime.py", "sig_regime_switch", "ETHUSDT",  "4h"),
]


def _load_mod(fname: str):
    p = REPO / "strategy_lab" / fname
    spec = _il.spec_from_file_location(f"_ph_{p.stem}", p)
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


def build_one(label, fname, fn_name, sym, tf) -> tuple[pd.Series, dict] | None:
    mod = _load_mod(fname)
    fn = getattr(mod, fn_name, None)
    if fn is None:
        return None
    df = engine.load(sym, tf, start="2021-01-01", end="2026-04-24")
    try:
        long_sig, short_sig = _unpack(fn(df))
    except Exception as e:
        print(f"  {label}: signal error: {e}")
        return None
    try:
        trades, equity = simulate(df, long_sig, short_sig,
                                  **EXIT_4H, **DEFAULT_CFG)
    except Exception as e:
        print(f"  {label}: simulate error: {e}")
        return None
    bpy = BARS_PER_YEAR.get(tf, 2190.0)
    m = compute_metrics(label, equity, trades, bpy)
    return equity, m


def yearly_rebalanced_blend(equities: dict[str, pd.Series]) -> pd.Series:
    """
    Yearly-rebalanced equal-weight blend. Each sleeve gets 1/N of portfolio
    equity at the start of each calendar year; runs independently within
    the year; then re-equalized on Jan 1.
    """
    common_idx = None
    for eq in equities.values():
        if common_idx is None:
            common_idx = eq.index
        else:
            common_idx = common_idx.intersection(eq.index)
    if common_idx is None or len(common_idx) < 2:
        return pd.Series(dtype=float)
    sleeve_rets = {k: eq.reindex(common_idx).pct_change().fillna(0.0)
                   for k, eq in equities.items()}
    N = len(equities)
    port = pd.Series(1.0, index=common_idx)
    sleeve_eq = {k: pd.Series(1.0 / N, index=common_idx) for k in equities}

    current_year = common_idx[0].year
    prev_port = 1.0
    for i, ts in enumerate(common_idx):
        if ts.year != current_year:
            # Rebalance: divide prev_port equally across sleeves
            for k in equities:
                sleeve_eq[k].iloc[i-1] = prev_port / N  # set at boundary
            current_year = ts.year
        if i == 0:
            continue
        # Grow each sleeve
        for k in equities:
            prev = sleeve_eq[k].iloc[i-1]
            sleeve_eq[k].iloc[i] = prev * (1.0 + sleeve_rets[k].iloc[i])
        prev_port = sum(sleeve_eq[k].iloc[i] for k in equities)
        port.iloc[i] = prev_port
    return port


def compute_portfolio_metrics(port: pd.Series, bpy: float) -> dict:
    if len(port) < 30:
        return {"sharpe": 0.0, "cagr": 0.0, "max_dd": 0.0, "calmar": 0.0,
                "min_year_return": 0.0, "max_year_return": 0.0,
                "per_year_positive": 0, "per_year_total": 0}
    rets = port.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sharpe = (mu / sd) * np.sqrt(bpy) if sd > 0 else 0.0
    peak = port.cummax()
    mdd = float((port / peak - 1.0).min())
    yrs = (port.index[-1] - port.index[0]).total_seconds() / (365.25 * 86400)
    total = float(port.iloc[-1] / port.iloc[0]) - 1.0
    cagr = (1 + total) ** (1 / max(yrs, 1e-6)) - 1.0
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0

    yearly = []
    pos = 0
    for yr in sorted(set(port.index.year)):
        ye = port[port.index.year == yr]
        if len(ye) < 30:
            continue
        ret = float(ye.iloc[-1] / ye.iloc[0] - 1)
        yearly.append(ret)
        if ret > 0:
            pos += 1
    return {
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr, 4),
        "max_dd": round(mdd, 4),
        "calmar": round(calmar, 3),
        "min_year_return": round(min(yearly) if yearly else 0, 4),
        "max_year_return": round(max(yearly) if yearly else 0, 4),
        "per_year_positive": pos,
        "per_year_total": len(yearly),
    }


def main():
    # --- Step 1: build per-cell equity curves
    print("\n=== Step 1: backtest every cell and cache equity ===\n")
    equities: dict[str, pd.Series] = {}
    cell_metrics = []
    for label, fname, fn_name, sym, tf in CELLS:
        print(f"  {label:20s} {sym:10s} {tf} ... ", end="", flush=True)
        try:
            out = build_one(label, fname, fn_name, sym, tf)
        except Exception as e:
            print(f"ERROR: {e}")
            continue
        if out is None:
            print("skipped")
            continue
        eq, m = out
        equities[label] = eq
        cell_metrics.append({**m, "symbol": sym, "tf": tf,
                             "fn": fn_name, "module": fname})
        eq.to_frame("equity").to_parquet(EQ_DIR / f"{label}.parquet")
        print(f"n_trades={m['n_trades']} Sh={m['sharpe']:+.2f} CAGR={m['cagr']*100:+.0f}%")

    # Dump per-cell CSV
    pd.DataFrame([{k: v for k, v in m.items() if k != "per_year"}
                  for m in cell_metrics]).to_csv(
        OUT_DIR / "perps_portfolio_cells.csv", index=False)

    # --- Step 2: correlation matrix
    print("\n=== Step 2: correlation matrix ===\n")
    common_idx = None
    for eq in equities.values():
        common_idx = eq.index if common_idx is None else common_idx.intersection(eq.index)
    if common_idx is None:
        print("No cells built — abort."); return 1
    rets_df = pd.DataFrame({
        k: eq.reindex(common_idx).pct_change().fillna(0.0)
        for k, eq in equities.items()
    })
    corr = rets_df.corr()
    corr.to_csv(OUT_DIR / "perps_correlation_matrix.csv")
    # Print compact view
    with pd.option_context("display.precision", 2, "display.width", 160):
        print(corr.round(2).to_string())

    # --- Step 3: enumerate 2- and 3-sleeve blends
    print("\n=== Step 3: enumerate blends ===\n")
    labels = list(equities.keys())
    bpy = BARS_PER_YEAR["4h"]
    all_combos = []

    for size in (2, 3):
        for combo in itertools.combinations(labels, size):
            blend = {k: equities[k] for k in combo}
            try:
                port = yearly_rebalanced_blend(blend)
                if len(port) < 100:
                    continue
                m = compute_portfolio_metrics(port, bpy)
                avg_pair_corr = float(corr.loc[list(combo), list(combo)].values[
                    np.triu_indices(size, k=1)].mean())
                all_combos.append({
                    "size": size, "sleeves": " + ".join(combo),
                    "avg_pair_corr": round(avg_pair_corr, 3),
                    **m,
                })
            except Exception:
                continue

    df_combos = pd.DataFrame(all_combos)
    df_combos.to_csv(OUT_DIR / "perps_portfolio_hunt.csv", index=False)

    # Top-ranked by min_year_return then sharpe
    print(f"Total combos: {len(df_combos)}")
    ranked = df_combos.sort_values(
        ["min_year_return", "sharpe"], ascending=[False, False]
    ).head(20)
    ranked.to_csv(OUT_DIR / "perps_portfolio_top.csv", index=False)
    print("\nTop 20 by worst-year return:")
    with pd.option_context("display.precision", 3, "display.width", 200, "display.max_colwidth", 60):
        print(ranked[["sleeves", "size", "sharpe", "cagr", "max_dd",
                      "calmar", "min_year_return", "per_year_positive",
                      "avg_pair_corr"]].to_string(index=False))


if __name__ == "__main__":
    main()
