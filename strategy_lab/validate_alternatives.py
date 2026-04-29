"""
Targeted validation for alternative ETH candidates and SOL V5.

For each candidate, compute:
  * full 2018-2026 backtest
  * IS/OOS split (2018-2022 / 2023-2026)
  * 5-fold CV
  * 200 random 2-year windows  (median Sharpe, % windows positive)
Pick whichever has the smallest IS-vs-OOS Sharpe degradation + stable folds.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2
from strategy_lab.strategies_v3 import STRATEGIES_V3
from strategy_lab.strategies_v4 import STRATEGIES_V4
from strategy_lab.strategies_v5 import STRATEGIES_V5

ALL = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4, **STRATEGIES_V5}
OUT = Path(__file__).resolve().parent / "results"

RNG = np.random.default_rng(42)


def bt(strat, sym, s, e, init=10_000):
    df = engine.load(sym, "4h", s, e)
    sig = ALL[strat](df)
    return engine.run_backtest(df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig.get("short_entries"),
        short_exits=sig.get("short_exits"),
        sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
        init_cash=init, label=f"{strat}|{sym}")


def full_metrics(strat, sym):
    full = bt(strat, sym, "2018-01-01", "2026-04-01").metrics
    is_m = bt(strat, sym, "2018-01-01", "2023-01-01").metrics
    oos  = bt(strat, sym, "2023-01-01", "2026-04-01").metrics
    return full, is_m, oos


def five_fold(strat, sym):
    folds = [
        ("2018-01-01", "2019-07-01"), ("2019-07-01", "2021-01-01"),
        ("2021-01-01", "2022-07-01"), ("2022-07-01", "2024-01-01"),
        ("2024-01-01", "2026-04-01"),
    ]
    out = []
    for i, (s, e) in enumerate(folds, 1):
        try:
            m = bt(strat, sym, s, e).metrics
            out.append({"fold": i, "cagr": round(m["cagr"],3),
                        "sharpe": round(m["sharpe"],3),
                        "max_dd": round(m["max_dd"],3),
                        "trades": int(m["n_trades"])})
        except Exception as err:
            out.append({"fold": i, "error": str(err)})
    return out


def random_windows(strat, sym, n=200):
    start = pd.Timestamp("2018-01-01", tz="UTC")
    end   = pd.Timestamp("2026-04-01", tz="UTC") - pd.DateOffset(years=2)
    total = (end - start).days
    sharpes, cagrs = [], []
    for _ in range(n):
        off = RNG.integers(0, total)
        ws = (start + pd.Timedelta(days=int(off))).strftime("%Y-%m-%d")
        we = (pd.Timestamp(ws, tz="UTC") + pd.DateOffset(years=2)).strftime("%Y-%m-%d")
        try:
            m = bt(strat, sym, ws, we).metrics
            if m["n_trades"] < 5: continue
            sharpes.append(m["sharpe"]); cagrs.append(m["cagr"])
        except Exception:
            continue
    arr = np.array(sharpes)
    return dict(n=len(arr),
                sharpe_median=float(np.median(arr)),
                sharpe_p25=float(np.percentile(arr, 25)),
                sharpe_p75=float(np.percentile(arr, 75)),
                pct_positive=float((arr > 0).mean()),
                pct_gt05=float((arr > 0.5).mean()),
                cagr_median=float(np.median(cagrs)))


def run(strat, sym, label):
    print(f"\n--- {label}: {strat} on {sym} ---")
    full, ism, oos = full_metrics(strat, sym)
    sh_is, sh_oos = ism["sharpe"], oos["sharpe"]
    degrade = (sh_oos / sh_is - 1) * 100 if sh_is > 0 else float("nan")
    print(f"  FULL: CAGR {full['cagr']:+.2%}  Sharpe {full['sharpe']:.2f}  "
          f"DD {full['max_dd']:.2%}  Calmar {full['calmar']:.2f}  "
          f"Final ${full['final_equity']:,.0f}")
    print(f"  IS:   CAGR {ism['cagr']:+.2%}  Sharpe {sh_is:.2f}")
    print(f"  OOS:  CAGR {oos['cagr']:+.2%}  Sharpe {sh_oos:.2f}")
    print(f"  IS->OOS Sharpe degradation: {degrade:+.1f}%")

    folds = five_fold(strat, sym)
    profitable = sum(1 for f in folds if "error" not in f and f.get("cagr", 0) > 0)
    total = sum(1 for f in folds if "error" not in f)
    print(f"  5-fold: {profitable}/{total} profitable folds")
    for f in folds:
        if "error" in f:
            print(f"    fold {f['fold']}: ERROR {f['error']}")
        else:
            print(f"    fold {f['fold']}: CAGR {f['cagr']:+.2%}  Sh {f['sharpe']:.2f}  DD {f['max_dd']:.2%}  trades={f['trades']}")

    rw = random_windows(strat, sym, 200)
    print(f"  Random windows (n={rw['n']}): median Sh {rw['sharpe_median']:.2f}  "
          f"% positive {rw['pct_positive']*100:.1f}%  "
          f"% Sh>0.5 {rw['pct_gt05']*100:.1f}%  CAGR median {rw['cagr_median']:+.2%}")

    return dict(strat=strat, sym=sym, label=label,
                full=full, IS=ism, OOS=oos, degrade_pct=degrade,
                folds=folds, random_windows=rw)


def main():
    results = []
    # ETH alternatives
    for strat in ["V3B_adx_gate", "V3C_sma_slope", "V3E_score2of3"]:
        results.append(run(strat, "ETHUSDT", f"ETH candidate"))
    # SOL V5 check vs V2B baseline
    for strat in ["V2B_volume_breakout", "V5_vol_breakout_liqfilter"]:
        results.append(run(strat, "SOLUSDT", f"SOL candidate"))

    # Pick ETH winner by smallest abs IS->OOS degradation that is still positive
    eth_results = [r for r in results if r["sym"] == "ETHUSDT"]
    eth_winner = sorted(eth_results,
                        key=lambda r: (abs(r["degrade_pct"]), -r["full"]["calmar"]))[0]
    print(f"\n===> ETH winner: {eth_winner['strat']}  "
          f"degrade={eth_winner['degrade_pct']:+.1f}%  "
          f"Calmar={eth_winner['full']['calmar']:.2f}")

    sol_results = [r for r in results if r["sym"] == "SOLUSDT"]
    sol_winner = sorted(sol_results, key=lambda r: -r["full"]["calmar"])[0]
    print(f"===> SOL winner: {sol_winner['strat']}  "
          f"folds profitable={sum(1 for f in sol_winner['folds'] if 'error' not in f and f.get('cagr', 0) > 0)}"
          f"/{sum(1 for f in sol_winner['folds'] if 'error' not in f)}  "
          f"Calmar={sol_winner['full']['calmar']:.2f}")

    (OUT / "alt_validation.json").write_text(json.dumps(results, default=str, indent=2))


if __name__ == "__main__":
    main()
