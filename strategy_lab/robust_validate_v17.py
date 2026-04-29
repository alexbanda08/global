"""
V17 robustness audit — 5-test validation for the ETH RangeKalman_LS winner.

Config under test:
  alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800
  TP=7.0 ATR, SL=1.5 ATR, Trail=4.5 ATR, MaxHold=48 bars
  risk_per_trade=3% of equity, leverage_cap=3x
  Fees: taker 0.00045/side, slippage 3bps

Tests:
  1. Cross-asset generalization (BTC, SOL 1h)
  2. Monte-Carlo trade-shuffle (2000 sims)
  3. Random 2-year windows (200)
  4. 5-fold disjoint time CV
  5. Parameter-epsilon grid (81 neighbours)
  6. Walk-forward: train on 2019-2023, test on 2024-2026 (honest OOS holdout)
"""
from __future__ import annotations
import itertools, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
)

FEAT = Path(__file__).resolve().parent / "features"
OUT = Path(__file__).resolve().parent / "results" / "v17" / "robust"
OUT.mkdir(parents=True, exist_ok=True)

SYMBOL = "ETHUSDT"
START, END = "2019-01-01", "2026-04-01"
FEE = 0.00045

DEFAULT = dict(alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800)
EXEC = dict(tp_atr=7.0, sl_atr=1.5, trail_atr=4.5, max_hold=48,
            risk_per_trade=0.03, leverage_cap=3.0, fee=FEE)

RNG = np.random.default_rng(42)


def _load(sym, start, end):
    df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
    df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC"))]
    return df


def _run(sym, start, end, params=None, exec_kwargs=None):
    df = _load(sym, start, end)
    if len(df) < 2000:
        return None
    p = {**DEFAULT, **(params or {})}
    ex = {**EXEC, **(exec_kwargs or {})}
    ls = sig_rangekalman(df, **p); ls = ls & ~ls.shift(1).fillna(False)
    ss = sig_rangekalman_short(df, **p); ss = ss & ~ss.shift(1).fillna(False)
    trades, eq = simulate(df, ls, short_entries=ss, **ex)
    r = metrics(f"{sym}_{start}_{end}", eq, trades)
    r["trades_raw"] = trades
    r["equity"] = eq
    return r


# ================================================================
# Test 1: cross-asset
# ================================================================
def cross_asset():
    rows = []
    tests = [
        ("ETHUSDT", "2019-01-01", "2026-04-01", True),
        ("BTCUSDT", "2019-01-01", "2026-04-01", False),
        ("SOLUSDT", "2020-09-01", "2026-04-01", False),
    ]
    for sym, s, e, is_own in tests:
        r = _run(sym, s, e)
        if r is None:
            rows.append({"sym": sym, "err": "too few bars"})
        else:
            rows.append({"sym": sym, "own": is_own, "period": f"{s}->{e}",
                         "n": r["n"], "cagr": round(r["cagr"], 3),
                         "sharpe": r["sharpe"], "dd": round(r["dd"], 3),
                         "win": r["win"], "pf": r["pf"], "avg_lev": r["avg_lev"]})
    out = pd.DataFrame(rows); out.to_csv(OUT / "01_cross_asset.csv", index=False)
    return out


# ================================================================
# Test 2: Monte-Carlo trade shuffle
# ================================================================
def mc_shuffle(n_sims=2000):
    r = _run(SYMBOL, START, END)
    rets = np.array([t["ret"] for t in r["trades_raw"]], dtype=float)
    if len(rets) < 20:
        return {"err": "too few trades"}
    real_eq = 10_000 * np.cumprod(1 + rets)
    real_final = real_eq[-1]
    real_dd = float(np.max(1 - real_eq / np.maximum.accumulate(real_eq)))
    sims_final = np.empty(n_sims); sims_dd = np.empty(n_sims)
    for i in range(n_sims):
        perm = RNG.permutation(rets)
        eq = 10_000 * np.cumprod(1 + perm)
        sims_final[i] = eq[-1]
        sims_dd[i] = np.max(1 - eq / np.maximum.accumulate(eq))
    out = {
        "real_final": float(real_final), "real_maxdd": real_dd,
        "sim_p5_final": float(np.quantile(sims_final, 0.05)),
        "sim_median_final": float(np.quantile(sims_final, 0.5)),
        "sim_p95_final": float(np.quantile(sims_final, 0.95)),
        "sim_p5_dd": float(np.quantile(sims_dd, 0.05)),
        "sim_median_dd": float(np.quantile(sims_dd, 0.5)),
        "sim_p95_dd": float(np.quantile(sims_dd, 0.95)),
        "real_final_pct": float((sims_final < real_final).mean()),
        "real_dd_pct": float((sims_dd < real_dd).mean()),
        "n_trades": int(len(rets)),
    }
    with open(OUT / "02_mc_shuffle.json", "w") as fh:
        json.dump(out, fh, indent=2)
    return out


# ================================================================
# Test 3: random 2-year windows
# ================================================================
def random_windows(n=200):
    df = _load(SYMBOL, START, END)
    rows = []
    first = df.index[0]; last = df.index[-1]
    earliest = first; latest = last - pd.Timedelta(days=730)
    rng_s = (latest - earliest).total_seconds()
    for i in range(n):
        offset = RNG.uniform(0, rng_s)
        ws = earliest + pd.Timedelta(seconds=offset)
        we = ws + pd.Timedelta(days=730)
        r = _run(SYMBOL, ws.strftime("%Y-%m-%d"), we.strftime("%Y-%m-%d"))
        if r is None: continue
        rows.append({"i": i, "start": str(ws.date()), "end": str(we.date()),
                     "n": r["n"], "cagr": round(r["cagr"], 3),
                     "sharpe": r["sharpe"], "dd": round(r["dd"], 3)})
    out = pd.DataFrame(rows); out.to_csv(OUT / "03_random_windows.csv", index=False)
    return out


# ================================================================
# Test 4: 5-fold disjoint
# ================================================================
def kfold():
    folds = [
        ("2019-01-01", "2020-07-01"),
        ("2020-07-01", "2022-01-01"),
        ("2022-01-01", "2023-07-01"),
        ("2023-07-01", "2025-01-01"),
        ("2025-01-01", "2026-04-01"),
    ]
    rows = []
    for i, (s, e) in enumerate(folds):
        r = _run(SYMBOL, s, e)
        if r is None:
            rows.append({"fold": i+1, "period": f"{s}->{e}", "err": "short"})
        else:
            rows.append({"fold": i+1, "period": f"{s}->{e}", "n": r["n"],
                         "cagr": round(r["cagr"], 3), "sharpe": r["sharpe"],
                         "dd": round(r["dd"], 3), "pf": r["pf"]})
    out = pd.DataFrame(rows); out.to_csv(OUT / "04_kfold.csv", index=False)
    return out


# ================================================================
# Test 5: parameter-epsilon grid (81 neighbours)
# ================================================================
def param_eps():
    grid = list(itertools.product(
        [0.05, 0.07, 0.09],  # alpha
        [300, 400, 500],     # rng_len
        [2.0, 2.5, 3.0],     # rng_mult
        [600, 800, 1000],    # regime_len
    ))
    rows = []
    for a, rl, rm, rg in grid:
        r = _run(SYMBOL, START, END, params={"alpha": a, "rng_len": rl,
                                             "rng_mult": rm, "regime_len": rg})
        if r is None:
            rows.append({"a": a, "rl": rl, "rm": rm, "rg": rg, "err": "short"})
        else:
            rows.append({"a": a, "rl": rl, "rm": rm, "rg": rg, "n": r["n"],
                         "cagr": round(r["cagr"], 3), "sharpe": r["sharpe"],
                         "dd": round(r["dd"], 3), "pf": r["pf"]})
    out = pd.DataFrame(rows); out.to_csv(OUT / "05_param_eps.csv", index=False)
    return out


# ================================================================
# Test 6: walk-forward OOS holdout
# ================================================================
def walk_forward():
    rows = []
    # In-sample 2019-2023, OOS 2024-2026
    r_is = _run(SYMBOL, "2019-01-01", "2024-01-01")
    r_oos = _run(SYMBOL, "2024-01-01", "2026-04-01")
    for name, r in [("IS_2019_2023", r_is), ("OOS_2024_2026", r_oos)]:
        if r is None:
            rows.append({"span": name, "err": "short"})
        else:
            rows.append({"span": name, "n": r["n"], "cagr": round(r["cagr"], 3),
                         "sharpe": r["sharpe"], "dd": round(r["dd"], 3),
                         "win": r["win"], "pf": r["pf"], "avg_lev": r["avg_lev"]})
    out = pd.DataFrame(rows); out.to_csv(OUT / "06_walk_forward.csv", index=False)
    return out


def main():
    print("=== V17 RangeKalman_LS (ETH 1h) — Robustness Audit ===\n")

    print("[1/6] Cross-asset generalization ...", flush=True)
    ca = cross_asset(); print(ca.to_string(index=False))

    print("\n[2/6] Monte-Carlo trade-shuffle (2000 sims) ...", flush=True)
    mc = mc_shuffle(2000)
    if "err" in mc:
        print(f"  SKIP: {mc['err']}")
    else:
        print(f"  real_final ${mc['real_final']:,.0f}   real_dd {mc['real_maxdd']*100:.1f}%")
        print(f"  sim_final  p5/p50/p95  ${mc['sim_p5_final']:,.0f} / ${mc['sim_median_final']:,.0f} / ${mc['sim_p95_final']:,.0f}")
        print(f"  sim_dd     p5/p50/p95  {mc['sim_p5_dd']*100:.1f}% / {mc['sim_median_dd']*100:.1f}% / {mc['sim_p95_dd']*100:.1f}%")
        print(f"  real_final vs sims: {mc['real_final_pct']*100:.0f}%")
        print(f"  real_dd    vs sims: {mc['real_dd_pct']*100:.0f}%")

    print("\n[3/6] Random 2-year windows (200) ...", flush=True)
    rw = random_windows(200)
    if len(rw):
        pos = (rw["cagr"] > 0).mean() * 100
        s05 = (rw["sharpe"] > 0.5).mean() * 100
        print(f"  {len(rw)} windows  profitable={pos:.0f}%  Sharpe>0.5={s05:.0f}%  "
              f"median Sharpe={rw['sharpe'].median():.2f}  worst DD={rw['dd'].min()*100:.1f}%")

    print("\n[4/6] 5-fold CV ...", flush=True)
    kf = kfold(); print(kf.to_string(index=False))

    print("\n[5/6] Parameter-epsilon (81 configs) ...", flush=True)
    pe = param_eps()
    ok = pe.dropna(subset=["cagr"])
    if len(ok):
        print(f"  {len(ok)} configs  profitable={((ok.cagr>0).mean())*100:.0f}%  "
              f"Sharpe in [{ok.sharpe.min():.2f},{ok.sharpe.max():.2f}]  "
              f"worst DD={ok.dd.min()*100:.1f}%")

    print("\n[6/6] Walk-forward OOS holdout ...", flush=True)
    wf = walk_forward(); print(wf.to_string(index=False))

    print(f"\nAll CSVs at {OUT}")


if __name__ == "__main__":
    sys.exit(main() or 0)
