"""
Multi-faceted overfitting / robustness validation.

Checks for each candidate winner:
  1. Cross-asset generalization — does the strategy work on the OTHER two
     assets it wasn't picked for?  Curve-fit strategies die here.
  2. Monte-Carlo trade-shuffle — shuffle trade returns 1,000× and look at
     the distribution of MaxDD and final equity.  Narrow distribution + real
     MaxDD near the 95th percentile = overfit.  Wide distribution + real
     MaxDD near the median = robust.
  3. Random-window resampling — evaluate on 200 random 2-year windows.
     Stable Sharpe > 0.5 in the majority → real edge.
  4. Purged k-fold cross-validation — 5 disjoint 1.5-year folds.
     Consistent positive returns across folds = not regime-specific.
  5. Parameter-ε robustness — ± one step on each parameter of the winner;
     if a tiny bump collapses the strategy we are fitting noise.

Output: robust_validation.csv + robust_validation.json  +  printed summary.
"""
from __future__ import annotations
import itertools
import json
import numpy as np
import pandas as pd
from pathlib import Path
from strategy_lab import engine
from strategy_lab.strategies_v2 import STRATEGIES_V2, volume_breakout_v2
from strategy_lab.strategies_v3 import STRATEGIES_V3, v3b_adx
from strategy_lab.strategies_v4 import STRATEGIES_V4, v4c_range_kalman

ALL = {**STRATEGIES_V2, **STRATEGIES_V3, **STRATEGIES_V4}
OUT = Path(__file__).resolve().parent / "results"

WINNERS = {
    "BTCUSDT": ("V4C_range_kalman",    "4h"),
    "ETHUSDT": ("V3B_adx_gate",        "4h"),
    "SOLUSDT": ("V2B_volume_breakout", "4h"),
}
TF = "4h"
START, END = "2018-01-01", "2026-04-01"
INIT = 10_000.0
ALL_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

RNG = np.random.default_rng(42)


def _run(strat, sym, start, end, init=INIT, params=None):
    df = engine.load(sym, TF, start, end)
    sig = ALL[strat](df, **(params or {}))
    res = engine.run_backtest(df,
        entries=sig["entries"], exits=sig["exits"],
        short_entries=sig.get("short_entries"),
        short_exits=sig.get("short_exits"),
        sl_stop=sig.get("sl_stop"), tsl_stop=sig.get("tsl_stop"),
        init_cash=init, label=f"{strat}|{sym}")
    return res


# ---------------------------------------------------------------------
# 1. Cross-asset generalization
# ---------------------------------------------------------------------
def cross_asset():
    rows = []
    for picked_sym, (strat, _) in WINNERS.items():
        for test_sym in ALL_SYMBOLS:
            try:
                res = _run(strat, test_sym, START, END)
                m = res.metrics
                rows.append({
                    "winner_for":     picked_sym,
                    "strategy":       strat,
                    "tested_on":      test_sym,
                    "is_own":         picked_sym == test_sym,
                    "cagr":           round(m["cagr"],     3),
                    "sharpe":         round(m["sharpe"],   3),
                    "calmar":         round(m["calmar"],   3),
                    "max_dd":         round(m["max_dd"],   3),
                    "trades":         int(m["n_trades"]),
                    "final":          round(m["final_equity"], 0),
                })
            except Exception as e:
                rows.append({"winner_for": picked_sym, "strategy": strat,
                             "tested_on": test_sym, "error": str(e)})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "robust_01_cross_asset.csv", index=False)
    return df


# ---------------------------------------------------------------------
# 2. Monte-Carlo trade shuffle
# ---------------------------------------------------------------------
def mc_shuffle(n_sims: int = 1000):
    results = {}
    for sym, (strat, _) in WINNERS.items():
        res = _run(strat, sym, START, END)
        trades = res.pf.trades.records_readable
        if len(trades) < 10:
            continue
        # Use "Return" column (fractional trade return)
        rets = trades["Return"].values.astype(float)
        real_final = INIT * float(np.prod(1 + rets))
        real_dd = _equity_maxdd(INIT * np.cumprod(1 + rets))

        sim_finals = []
        sim_dds    = []
        for _ in range(n_sims):
            shuffled = RNG.permutation(rets)
            eq = INIT * np.cumprod(1 + shuffled)
            sim_finals.append(eq[-1])
            sim_dds.append(_equity_maxdd(eq))

        sim_finals = np.array(sim_finals)
        sim_dds    = np.array(sim_dds)
        results[sym] = {
            "strategy":       strat,
            "n_trades":       int(len(rets)),
            "real_final":     round(real_final, 0),
            "real_maxdd":     round(real_dd, 4),
            "sim_median_final": round(float(np.median(sim_finals)), 0),
            "sim_p5_final":     round(float(np.percentile(sim_finals, 5)), 0),
            "sim_p95_final":    round(float(np.percentile(sim_finals, 95)), 0),
            "sim_median_dd":    round(float(np.median(sim_dds)), 4),
            "sim_p5_dd":        round(float(np.percentile(sim_dds, 5)), 4),
            "sim_p95_dd":       round(float(np.percentile(sim_dds, 95)), 4),
        }
    (OUT / "robust_02_mc_shuffle.json").write_text(json.dumps(results, indent=2))
    return results


def _equity_maxdd(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1
    return float(dd.min())


# ---------------------------------------------------------------------
# 3. Random-window resampling — 200 × (random start, 2-year window)
# ---------------------------------------------------------------------
def random_windows(n_windows: int = 200):
    rows = []
    start_ts = pd.Timestamp(START, tz="UTC")
    end_ts   = pd.Timestamp(END, tz="UTC") - pd.DateOffset(years=2)
    total_days = (end_ts - start_ts).days
    for sym, (strat, _) in WINNERS.items():
        sharpes, cagrs, dds = [], [], []
        for _ in range(n_windows):
            offset = RNG.integers(0, max(total_days, 1))
            w_start = (start_ts + pd.Timedelta(days=int(offset))).strftime("%Y-%m-%d")
            w_end   = (pd.Timestamp(w_start, tz="UTC") + pd.DateOffset(years=2)).strftime("%Y-%m-%d")
            try:
                res = _run(strat, sym, w_start, w_end)
                m = res.metrics
                if m["n_trades"] < 5:
                    continue
                sharpes.append(m["sharpe"])
                cagrs.append(m["cagr"])
                dds.append(m["max_dd"])
            except Exception:
                continue
        rows.append({
            "symbol": sym, "strategy": strat,
            "n_windows":      len(sharpes),
            "sharpe_median":  round(float(np.median(sharpes)), 3),
            "sharpe_p25":     round(float(np.percentile(sharpes, 25)), 3),
            "sharpe_p75":     round(float(np.percentile(sharpes, 75)), 3),
            "pct_windows_sharpe_gt0": round(float((np.array(sharpes) > 0).mean()), 3),
            "pct_windows_sharpe_gt05":round(float((np.array(sharpes) > 0.5).mean()), 3),
            "cagr_median":    round(float(np.median(cagrs)), 3),
            "dd_median":      round(float(np.median(dds)), 3),
            "dd_worst":       round(float(np.min(dds)), 3),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "robust_03_random_windows.csv", index=False)
    return df


# ---------------------------------------------------------------------
# 4. Purged k-fold (5 disjoint ~1.5-year folds)
# ---------------------------------------------------------------------
def kfold():
    # 5 non-overlapping segments covering 2018-01 -> 2026-04
    folds = [
        ("2018-01-01", "2019-07-01"),
        ("2019-07-01", "2021-01-01"),
        ("2021-01-01", "2022-07-01"),
        ("2022-07-01", "2024-01-01"),
        ("2024-01-01", "2026-04-01"),
    ]
    rows = []
    for sym, (strat, _) in WINNERS.items():
        for i, (s, e) in enumerate(folds):
            try:
                res = _run(strat, sym, s, e)
                m = res.metrics
                rows.append({
                    "symbol":    sym, "strategy": strat,
                    "fold":      i+1,
                    "period":    f"{s} -> {e}",
                    "cagr":      round(m["cagr"],   3),
                    "sharpe":    round(m["sharpe"], 3),
                    "max_dd":    round(m["max_dd"], 3),
                    "trades":    int(m["n_trades"]),
                    "final":     round(m["final_equity"], 0),
                    "bh_return": round(m["bh_return"], 3),
                })
            except Exception as err:
                rows.append({"symbol": sym, "strategy": strat, "fold": i+1,
                             "period": f"{s} -> {e}", "error": str(err)})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "robust_04_kfold.csv", index=False)
    return df


# ---------------------------------------------------------------------
# 5. Parameter-ε robustness
# ---------------------------------------------------------------------
def param_epsilon():
    rows = []
    # BTC — V4C_range_kalman
    btc_grid = list(itertools.product(
        [0.03, 0.05, 0.07],   # kalman_alpha
        [80, 100, 120],       # range_len
        [2.0, 2.5, 3.0],      # range_mult
        [150, 200, 250],      # regime_len
    ))
    for a, rlen, rmult, reg in btc_grid:
        try:
            res = _run("V4C_range_kalman", "BTCUSDT", START, END,
                       params=dict(kalman_alpha=a, range_len=rlen,
                                   range_mult=rmult, regime_len=reg))
            m = res.metrics
            rows.append({"symbol":"BTCUSDT","strategy":"V4C_range_kalman",
                         "params":f"a={a},rlen={rlen},mult={rmult},reg={reg}",
                         "cagr":round(m["cagr"],3), "sharpe":round(m["sharpe"],3),
                         "max_dd":round(m["max_dd"],3), "calmar":round(m["calmar"],3),
                         "trades":int(m["n_trades"])})
        except Exception as e:
            pass

    # ETH — V3B_adx_gate  (params: adx_min, regime_len, vol_mult, don_len)
    eth_grid = list(itertools.product(
        [18, 20, 22, 25],     # adx_min
        [120, 150, 180],      # regime_len
        [1.2, 1.3, 1.5],      # vol_mult
        [20, 30, 40],         # don_len
    ))
    for adx, reg, vm, dl in eth_grid:
        try:
            res = _run("V3B_adx_gate", "ETHUSDT", START, END,
                       params=dict(adx_min=adx, regime_len=reg,
                                   vol_mult=vm, don_len=dl))
            m = res.metrics
            rows.append({"symbol":"ETHUSDT","strategy":"V3B_adx_gate",
                         "params":f"adx={adx},reg={reg},vm={vm},dl={dl}",
                         "cagr":round(m["cagr"],3), "sharpe":round(m["sharpe"],3),
                         "max_dd":round(m["max_dd"],3), "calmar":round(m["calmar"],3),
                         "trades":int(m["n_trades"])})
        except Exception:
            pass

    # SOL — V2B_volume_breakout  (params: don_len, vol_mult, regime_len, tsl_atr)
    sol_grid = list(itertools.product(
        [20, 25, 30, 35],     # don_len
        [1.2, 1.3, 1.5],      # vol_mult
        [120, 150, 180, 200], # regime_len
        [3.5, 4.0, 4.5, 5.0], # tsl_atr
    ))
    for dl, vm, reg, t in sol_grid:
        try:
            res = _run("V2B_volume_breakout", "SOLUSDT", START, END,
                       params=dict(don_len=dl, vol_mult=vm,
                                   regime_len=reg, tsl_atr=t))
            m = res.metrics
            rows.append({"symbol":"SOLUSDT","strategy":"V2B_volume_breakout",
                         "params":f"dl={dl},vm={vm},reg={reg},t={t}",
                         "cagr":round(m["cagr"],3), "sharpe":round(m["sharpe"],3),
                         "max_dd":round(m["max_dd"],3), "calmar":round(m["calmar"],3),
                         "trades":int(m["n_trades"])})
        except Exception:
            pass

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "robust_05_param_eps.csv", index=False)
    return df


# ---------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------
def main():
    print("1) Cross-asset generalization ...")
    ca = cross_asset()
    print("\n=== CROSS-ASSET ===")
    print(ca.to_string(index=False))

    print("\n2) Monte-Carlo trade shuffle (1,000 sims/asset) ...")
    mc = mc_shuffle(1000)
    print("\n=== MC SHUFFLE ===")
    for sym, r in mc.items():
        print(f"  {sym}  real ${r['real_final']:,.0f}  DD {r['real_maxdd']*100:.1f}%   "
              f"| sim final p5/p50/p95 ${r['sim_p5_final']:,.0f} / "
              f"${r['sim_median_final']:,.0f} / ${r['sim_p95_final']:,.0f}   "
              f"DD p5/p50/p95 {r['sim_p5_dd']*100:.1f}% / "
              f"{r['sim_median_dd']*100:.1f}% / {r['sim_p95_dd']*100:.1f}%")

    print("\n3) Random 2-yr windows (200) ...")
    rw = random_windows(200)
    print(rw.to_string(index=False))

    print("\n4) 5-fold cross-validation ...")
    kf = kfold()
    print(kf.to_string(index=False))

    print("\n5) Parameter-epsilon grid ...")
    pe = param_epsilon()
    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        sub = pe[pe["symbol"] == sym]
        if len(sub) == 0: continue
        print(f"\n  {sym}:  configs={len(sub)}   "
              f"sharpe ∈ [{sub.sharpe.min():.2f}, {sub.sharpe.max():.2f}]   "
              f"calmar ∈ [{sub.calmar.min():.2f}, {sub.calmar.max():.2f}]   "
              f"dd worst {sub.max_dd.min()*100:.1f}%   "
              f"profitable={(sub.cagr > 0).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
