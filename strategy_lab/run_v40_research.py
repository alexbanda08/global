"""
V40 ADAPTIVE RESEARCH RUNNER
============================
Tests regime-adaptive strategies on multiple TFs across 4 coins, using:
  * Forward-only HMM regime classifier (no look-ahead; BIC-selected K)
  * TP1/TP2 partial-exit simulator
  * Canonical single-exit simulator (for comparison)

Matrix:
  coins:       ETH, AVAX, SOL, DOGE
  timeframes:  4h (primary), 1h and 8h for top variants
  strategies:  CCI-adaptive, ST-adaptive, Regime-Switcher
  exit:        canonical (single-exit) AND TP1/TP2
  benchmark:   baseline CCI / ST at static params

Writes:
  docs/research/phase5_results/v40_research_grid.csv
  docs/research/phase5_results/v40_regime_diagnostics.json
"""
from __future__ import annotations
import json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from strategy_lab.engine import load as load_data
from strategy_lab.eval.perps_simulator import simulate as simulate_canonical, FEE_DEFAULT
from strategy_lab.eval.perps_simulator_tp12 import simulate_tp12
from strategy_lab.regime.hmm_adaptive import fit_regime_model, build_features
from strategy_lab.strategies.adaptive.v40_regime_adaptive import (
    sig_v40_cci_adaptive, sig_v40_st_adaptive, sig_v40_switcher,
)

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)

TF_BPY = {"1h": 24 * 365.25, "4h": 6 * 365.25, "8h": 3 * 365.25}
COINS = ["ETHUSDT", "AVAXUSDT", "SOLUSDT", "DOGEUSDT"]
TFS_PRIMARY = ["4h"]
TFS_FULL    = ["1h", "4h", "8h"]

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)
EXIT_1H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=240)
EXIT_8H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=30)
EXITS = {"1h": EXIT_1H, "4h": EXIT_4H, "8h": EXIT_8H}

TP12_4H = dict(tp1_atr=3.0, tp2_atr=10.0, tp1_frac=0.5,
               sl_atr=2.0, trail_atr=6.0, tight_trail_atr=2.5, max_hold=60)


# ----------------------------------------------------------- metrics
def metrics(eq: pd.Series, trades: list[dict], bpy: float) -> dict:
    n = len(trades)
    if n < 2 or len(eq) < 30:
        return {"n": n, "sharpe": 0, "cagr": 0, "mdd": 0, "calmar": 0,
                "win_rate": 0, "min_yr": 0, "pos_yrs": 0, "avg_hold": 0, "pf": 0}
    rets = eq.pct_change().dropna()
    mu, sd = float(rets.mean()), float(rets.std())
    sh = (mu/sd) * np.sqrt(bpy) if sd > 0 else 0
    pk = eq.cummax(); mdd = float((eq/pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    total = float(eq.iloc[-1]/eq.iloc[0] - 1)
    cagr = (1 + total) ** (1/max(yrs,1e-6)) - 1
    cal = cagr/abs(mdd) if mdd != 0 else 0
    wins = [t for t in trades if t.get("ret", 0) > 0]
    losses = [t for t in trades if t.get("ret", 0) <= 0]
    wr = len(wins)/n if n > 0 else 0
    pf = abs(sum(t["ret"] for t in wins)/sum(t["ret"] for t in losses)) if losses else 0
    avg_hold = float(np.mean([t["bars"] for t in trades])) if trades else 0
    yearly = {}
    for yr in sorted(set(eq.index.year)):
        e = eq[eq.index.year == yr]
        if len(e) >= 30:
            yearly[int(yr)] = float(e.iloc[-1]/e.iloc[0] - 1)
    min_yr = min(yearly.values()) if yearly else 0
    pos_yrs = sum(1 for r in yearly.values() if r > 0)
    return {"n": n, "sharpe": round(sh, 2), "cagr": round(cagr, 3),
            "mdd": round(mdd, 3), "calmar": round(cal, 2),
            "win_rate": round(wr, 3), "min_yr": round(min_yr, 3),
            "pos_yrs": pos_yrs, "total_yrs": len(yearly),
            "avg_hold": round(avg_hold, 1), "pf": round(pf, 2)}


# ----------------------------------------------------------- runner
def run_one(symbol: str, tf: str, strategy: str, exit_style: str,
            regime_model_cache: dict | None = None):
    df = load_data(symbol, tf, start="2021-01-01", end="2026-03-31")
    # Fit regime model (cached per coin/tf)
    key = f"{symbol}:{tf}"
    if regime_model_cache is not None and key in regime_model_cache:
        model, regime_df = regime_model_cache[key]
    else:
        model, regime_df = fit_regime_model(df, train_frac=0.30, seed=42, verbose=False)
        if regime_model_cache is not None:
            regime_model_cache[key] = (model, regime_df)

    # Build signals
    if strategy == "cci_adaptive":
        le, se = sig_v40_cci_adaptive(df, regime_df)
    elif strategy == "st_adaptive":
        le, se = sig_v40_st_adaptive(df, regime_df)
    elif strategy == "switcher":
        le, se = sig_v40_switcher(df, regime_df)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    # Simulate with selected exit
    bpy = TF_BPY[tf]
    if exit_style == "canonical":
        trades, eq = simulate_canonical(df, le, se, **EXITS[tf])
    elif exit_style == "tp12":
        trades, eq = simulate_tp12(df, le, se,
                                    **{**TP12_4H,
                                       "max_hold": EXITS[tf]["max_hold"]})
    else:
        raise ValueError(f"Unknown exit: {exit_style}")

    return metrics(eq, trades, bpy), model


# ----------------------------------------------------------- grid
def run_grid(coins, tfs, strategies, exit_styles):
    rows = []
    cache: dict = {}
    model_diag: dict = {}
    t0 = time.time()
    for sym in coins:
        for tf in tfs:
            try:
                # cache model
                df = load_data(sym, tf, start="2021-01-01", end="2026-03-31")
                _ = build_features(df)   # sanity warm
                model, regime_df = fit_regime_model(df, train_frac=0.30, seed=42)
                cache[f"{sym}:{tf}"] = (model, regime_df)
                model_diag[f"{sym}:{tf}"] = {
                    "best_k": model.best_k,
                    "bic_table": model.bic_table,
                    "verification": model.verification,
                    "regime_vol_scores": model.regime_vol_score,
                    "regime_distribution": regime_df["label"].value_counts().to_dict(),
                }
            except Exception as e:
                print(f"[regime fit] FAIL {sym}:{tf} -> {e}")
                continue

            for strat in strategies:
                for ex in exit_styles:
                    try:
                        m, _ = run_one(sym, tf, strat, ex, regime_model_cache=cache)
                        rows.append({
                            "symbol": sym, "tf": tf, "strategy": strat, "exit": ex,
                            "best_k": model.best_k,
                            **m,
                        })
                        print(f"  {sym} {tf} {strat:14s} {ex:10s}  "
                              f"n={m['n']:4d} WR={m['win_rate']*100:5.1f}% "
                              f"Sharpe={m['sharpe']:5.2f} CAGR={m['cagr']*100:6.1f}% "
                              f"MDD={m['mdd']*100:6.1f}% Cal={m['calmar']}")
                    except Exception as e:
                        print(f"  FAIL {sym}:{tf}:{strat}:{ex} -> {type(e).__name__}: {e}")
                        continue

    df_out = pd.DataFrame(rows)
    df_out.to_csv(OUT / "v40_research_grid.csv", index=False)
    with open(OUT / "v40_regime_diagnostics.json", "w") as f:
        json.dump(model_diag, f, indent=2, default=str)
    print(f"\n[grid] {len(rows)} runs in {time.time()-t0:.1f}s")
    return df_out, model_diag


# ----------------------------------------------------------- main
def main():
    print("=" * 70)
    print("V40 ADAPTIVE RESEARCH — regime-adaptive strategies")
    print("=" * 70)

    # Phase 1: 4h primary scan
    print("\n--- Phase 1: 4h grid (all coins, all strategies, both exits) ---")
    df1, diag = run_grid(
        coins=COINS,
        tfs=["4h"],
        strategies=["cci_adaptive", "st_adaptive", "switcher"],
        exit_styles=["canonical", "tp12"],
    )

    # Phase 2: Extend winners to 1h, 8h
    print("\n--- Phase 2: 1h + 8h scan (top variants only) ---")
    if len(df1) == 0 or "sharpe" not in df1.columns:
        print("  Phase 1 produced no rows — aborting.")
        return
    top = df1[df1["sharpe"] >= 1.0].sort_values("sharpe", ascending=False)
    if len(top) == 0:
        print("  No 4h variants with Sharpe >= 1.0 — skipping multi-TF scan")
        df2 = pd.DataFrame()
    else:
        coins_top = top["symbol"].unique().tolist()[:3]
        strats_top = top["strategy"].unique().tolist()
        exits_top = top["exit"].unique().tolist()
        print(f"  Extending: coins={coins_top} strategies={strats_top} exits={exits_top}")
        df2, diag2 = run_grid(
            coins=coins_top,
            tfs=["1h", "8h"],
            strategies=strats_top,
            exit_styles=exits_top,
        )
        diag.update(diag2)

    # Compile final grid
    full = pd.concat([df1, df2], ignore_index=True) if len(df2) else df1
    full.to_csv(OUT / "v40_research_grid.csv", index=False)
    with open(OUT / "v40_regime_diagnostics.json", "w") as f:
        json.dump(diag, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("TOP 15 V40 VARIANTS (by Sharpe, filtered pos_yrs>=5)")
    print("=" * 70)
    top15 = (full[(full["pos_yrs"] >= 5) & (full["n"] >= 20)]
             .sort_values(["sharpe", "calmar"], ascending=False)
             .head(15))
    print(top15[["symbol", "tf", "strategy", "exit", "n", "win_rate",
                  "sharpe", "cagr", "mdd", "calmar", "pos_yrs", "avg_hold", "pf"]]
          .to_string(index=False))

    print("\nRegime diagnostics (first 4 models):")
    for key in list(diag.keys())[:4]:
        d = diag[key]
        print(f"  {key}: K*={d['best_k']}, "
              f"no_leak={d['verification']['no_leak_assertion']}, "
              f"train_end={d['verification']['train_end_date'][:10]}, "
              f"regimes={d['regime_distribution']}")

    print(f"\nSaved grid -> {OUT}/v40_research_grid.csv")
    print(f"Saved diag -> {OUT}/v40_regime_diagnostics.json")


if __name__ == "__main__":
    main()
