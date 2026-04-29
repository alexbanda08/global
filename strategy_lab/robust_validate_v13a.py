"""
5-test robustness audit — ETH V13A Range Kalman at 1h.

Mirrors strategy_lab/robust_validate.py (for the 4h winners) but targets the
V13A candidate: v13_range_kalman, ETH 1h, default params
(alpha=0.05, rng_len=400, rng_mult=2.5, regime_len=800) with
ATR stop/target wrap (tp_atr=5.0, sl_atr=2.0, trail_atr=3.5, max_hold=72).

Tests:
  1. Cross-asset generalization (BTC, SOL 1h)
  2. Monte-Carlo trade-shuffle (1,000 sims)
  3. Random 2-year windows (200)
  4. Purged k-fold (5 folds)
  5. Parameter-epsilon grid

Outputs under strategy_lab/results/v13a/*.csv + prints a final PASS/FAIL-style summary.
"""
from __future__ import annotations
import itertools, json
from pathlib import Path
import numpy as np
import pandas as pd

from strategy_lab import engine
from strategy_lab.run_v13_trend_1h import (
    v13_range_kalman, simulate, report, INIT,
)

TF = "1h"
SYMBOL = "ETHUSDT"
START, END = "2019-01-01", "2026-04-01"
TP, SL, TRAIL, MAX_HOLD = 5.0, 2.0, 3.5, 72

DEFAULT_PARAMS = dict(alpha=0.05, rng_len=400, rng_mult=2.5,
                      regime_len=800, trail_atr=3.5, atr_len=14)

OUT = Path(__file__).resolve().parent / "results" / "v13a"
OUT.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(42)


# ---------------------------------------------------------------------
def _prep(sym: str, start: str, end: str) -> pd.DataFrame:
    df = engine.load(sym, TF, start, end)
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
    return df


def _run(sym: str, start: str, end: str, params: dict | None = None):
    df = _prep(sym, start, end)
    if len(df) < 2_000:
        raise RuntimeError(f"not enough bars: {len(df)}")
    p = {**DEFAULT_PARAMS, **(params or {})}
    sig = v13_range_kalman(df, **p)
    sig = sig & ~sig.shift(1).fillna(False)
    trades, eq = simulate(df, sig, tp_atr=TP, sl_atr=SL, trail_atr=TRAIL,
                          max_hold=MAX_HOLD)
    r = report(f"{sym}_V13A", eq, trades)
    r["trades_raw"] = trades
    r["equity"] = eq
    return r


# ---------------------------------------------------------------------
# 1) Cross-asset generalization
# ---------------------------------------------------------------------
def cross_asset() -> pd.DataFrame:
    rows = []
    # SOL 1h only has data from 2020-08 — use a common safe start
    tests = [
        ("ETHUSDT", "2019-01-01", "2026-04-01", True),
        ("BTCUSDT", "2019-01-01", "2026-04-01", False),
        ("SOLUSDT", "2020-09-01", "2026-04-01", False),
    ]
    for sym, s, e, is_own in tests:
        try:
            r = _run(sym, s, e)
            rows.append({
                "symbol":   sym,
                "is_own":   is_own,
                "period":   f"{s} -> {e}",
                "trades":   int(r["n"]),
                "final":    round(r["final"], 0),
                "cagr":     round(r["cagr"], 3),
                "sharpe":   round(r["sharpe"], 3),
                "dd":       round(r["dd"], 3),
                "win":      round(r["win"], 3),
                "pf":       round(r["pf"], 3),
            })
        except Exception as err:
            rows.append({"symbol": sym, "is_own": is_own, "error": str(err)})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "01_cross_asset.csv", index=False)
    return df


# ---------------------------------------------------------------------
# 2) Monte-Carlo trade-shuffle
# ---------------------------------------------------------------------
def mc_shuffle(n_sims: int = 1_000) -> dict:
    r = _run(SYMBOL, START, END)
    trades = r["trades_raw"]
    if len(trades) < 10:
        return {"error": "too few trades for MC"}
    rets = np.array([t["ret"] for t in trades], dtype=float)
    real_final = INIT * np.prod(1 + rets)
    real_eq = INIT * np.cumprod(1 + rets)
    real_dd = float(np.max(1 - real_eq / np.maximum.accumulate(real_eq)))

    sims_final, sims_dd = [], []
    for _ in range(n_sims):
        perm = RNG.permutation(rets)
        eq = INIT * np.cumprod(1 + perm)
        sims_final.append(eq[-1])
        dd = np.max(1 - eq / np.maximum.accumulate(eq))
        sims_dd.append(dd)
    arr_f = np.array(sims_final); arr_d = np.array(sims_dd)

    out = {
        "real_final":       float(real_final),
        "real_maxdd":       real_dd,
        "sim_p5_final":     float(np.quantile(arr_f,  0.05)),
        "sim_median_final": float(np.quantile(arr_f,  0.50)),
        "sim_p95_final":    float(np.quantile(arr_f,  0.95)),
        "sim_p5_dd":        float(np.quantile(arr_d,  0.05)),
        "sim_median_dd":    float(np.quantile(arr_d,  0.50)),
        "sim_p95_dd":       float(np.quantile(arr_d,  0.95)),
        "real_final_pct":   float((arr_f < real_final).mean()),
        "real_dd_pct":      float((arr_d < real_dd).mean()),
        "n_trades":         int(len(rets)),
    }
    with open(OUT / "02_mc_shuffle.json", "w") as fh:
        json.dump(out, fh, indent=2)
    return out


# ---------------------------------------------------------------------
# 3) Random 2-year windows
# ---------------------------------------------------------------------
def random_windows(n_windows: int = 200) -> pd.DataFrame:
    df = _prep(SYMBOL, START, END)
    # Precompute signal once on full series (signals are causal)
    sig_full = v13_range_kalman(df, **DEFAULT_PARAMS)
    sig_full = sig_full & ~sig_full.shift(1).fillna(False)

    idx = df.index
    first = idx[0]; last = idx[-1]
    window = pd.Timedelta(days=730)
    earliest_start = first
    latest_start = last - window
    rng_s = (latest_start - earliest_start).total_seconds()
    rows = []
    for i in range(n_windows):
        offset_s = RNG.uniform(0, rng_s)
        ws = earliest_start + pd.Timedelta(seconds=offset_s)
        we = ws + window
        sub = df[(df.index >= ws) & (df.index < we)]
        if len(sub) < 2_000:
            continue
        sub_sig = sig_full.loc[sub.index]
        trades, eq = simulate(sub, sub_sig, tp_atr=TP, sl_atr=SL,
                              trail_atr=TRAIL, max_hold=MAX_HOLD)
        r = report(f"rw{i}", eq, trades)
        rows.append({
            "i":        i,
            "start":    str(ws.date()),
            "end":      str(we.date()),
            "trades":   r["n"],
            "cagr":     round(r["cagr"], 3),
            "sharpe":   round(r["sharpe"], 3),
            "dd":       round(r["dd"], 3),
            "final":    round(r["final"], 0),
        })
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "03_random_windows.csv", index=False)
    return out


# ---------------------------------------------------------------------
# 4) 5-fold cross-validation
# ---------------------------------------------------------------------
def kfold() -> pd.DataFrame:
    folds = [
        ("2019-01-01", "2020-07-01"),
        ("2020-07-01", "2022-01-01"),
        ("2022-01-01", "2023-07-01"),
        ("2023-07-01", "2025-01-01"),
        ("2025-01-01", "2026-04-01"),
    ]
    rows = []
    for i, (s, e) in enumerate(folds):
        try:
            r = _run(SYMBOL, s, e)
            rows.append({
                "fold":     i + 1,
                "period":   f"{s} -> {e}",
                "trades":   r["n"],
                "cagr":     round(r["cagr"], 3),
                "sharpe":   round(r["sharpe"], 3),
                "dd":       round(r["dd"], 3),
                "final":    round(r["final"], 0),
            })
        except Exception as err:
            rows.append({"fold": i+1, "period": f"{s} -> {e}", "error": str(err)})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "04_kfold.csv", index=False)
    return out


# ---------------------------------------------------------------------
# 5) Parameter-epsilon grid
# ---------------------------------------------------------------------
def param_epsilon() -> pd.DataFrame:
    grid = list(itertools.product(
        [0.03, 0.05, 0.07],       # alpha
        [300, 400, 500],          # rng_len
        [2.0, 2.5, 3.0],          # rng_mult
        [600, 800, 1000],         # regime_len
    ))
    rows = []
    for a, rl, rm, rg in grid:
        try:
            r = _run(SYMBOL, START, END,
                     params=dict(alpha=a, rng_len=rl, rng_mult=rm, regime_len=rg))
            rows.append({
                "params":   f"a={a},rl={rl},rm={rm},rg={rg}",
                "trades":   r["n"],
                "cagr":     round(r["cagr"], 3),
                "sharpe":   round(r["sharpe"], 3),
                "dd":       round(r["dd"], 3),
                "pf":       round(r["pf"], 3),
                "final":    round(r["final"], 0),
            })
        except Exception as err:
            rows.append({"params": f"a={a},rl={rl},rm={rm},rg={rg}", "error": str(err)})
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "05_param_eps.csv", index=False)
    return out


# ---------------------------------------------------------------------
def main():
    print("=== V13A (ETH 1h, Range Kalman) — Robustness Audit ===", flush=True)

    print("\n[1/5] Cross-asset generalization ...", flush=True)
    ca = cross_asset()
    print(ca.to_string(index=False))

    print("\n[2/5] Monte-Carlo trade-shuffle (1,000 sims) ...", flush=True)
    mc = mc_shuffle(1_000)
    if "error" in mc:
        print(f"  SKIP: {mc['error']}")
    else:
        print(f"  real final ${mc['real_final']:,.0f}   "
              f"DD {mc['real_maxdd']*100:.1f}%")
        print(f"  sim final p5/p50/p95  "
              f"${mc['sim_p5_final']:,.0f} / ${mc['sim_median_final']:,.0f} / ${mc['sim_p95_final']:,.0f}")
        print(f"  sim DD    p5/p50/p95  "
              f"{mc['sim_p5_dd']*100:.1f}% / {mc['sim_median_dd']*100:.1f}% / {mc['sim_p95_dd']*100:.1f}%")
        print(f"  real_final quantile vs sims: {mc['real_final_pct']*100:.0f}%")
        print(f"  real_dd    quantile vs sims: {mc['real_dd_pct']*100:.0f}%")

    print("\n[3/5] Random 2-year windows (200) ...", flush=True)
    rw = random_windows(200)
    if len(rw):
        pos = (rw["cagr"] > 0).mean() * 100
        stable = (rw["sharpe"] > 0.5).mean() * 100
        print(f"  windows={len(rw)}   profitable={pos:.0f}%   "
              f"sharpe>0.5={stable:.0f}%   "
              f"median sharpe={rw['sharpe'].median():.2f}   "
              f"worst DD={rw['dd'].min()*100:.1f}%")

    print("\n[4/5] 5-fold cross-validation ...", flush=True)
    kf = kfold()
    print(kf.to_string(index=False))

    print("\n[5/5] Parameter-epsilon grid ...", flush=True)
    pe = param_epsilon()
    sub = pe[~pe.get("cagr").isna()] if "cagr" in pe.columns else pe
    if len(sub):
        print(f"  configs={len(sub)}   "
              f"sharpe ∈ [{sub.sharpe.min():.2f}, {sub.sharpe.max():.2f}]   "
              f"dd worst {sub.dd.min()*100:.1f}%   "
              f"profitable={(sub.cagr > 0).mean()*100:.0f}%")

    print("\nAll CSVs under:", OUT)
    print("\nVerdict heuristic:")
    print("  PASS if:  cross-asset avg sharpe > 0 on 2/3 symbols,")
    print("            MC real_final_pct > 50% (beats random shuffle),")
    print("            random_windows profitable > 60%,")
    print("            k-fold cagr > 0 on >= 3/5 folds,")
    print("            param-eps profitable% > 70%.")


if __name__ == "__main__":
    main()
