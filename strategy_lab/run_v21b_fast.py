"""
V21b — Fast targeted tune for BTC/SOL. Smaller grid, save results as we go.
"""
from __future__ import annotations
import sys, itertools, time, csv
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, atr, ema, kalman_ema, supertrend,
    donchian_up, donchian_dn, bb,
    sig_rangekalman, sig_rangekalman_short,
    sig_bbbreak, sig_trend_rider_long, sig_trend_rider_short,
)

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v21"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
BPH = {"1h": 1, "2h": 0.5, "4h": 0.25, "6h": 1/6, "8h": 0.125}


def _load(sym, tf):
    if tf in ("1h", "2h", "4h"):
        p = FEAT / f"{sym}_{tf}.parquet"
        if not p.exists(): return None
        return pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])
    # resample
    p1h = FEAT / f"{sym}_1h.parquet"
    df = pd.read_parquet(p1h)
    df = df.resample(tf).agg({"open": "first", "high": "max",
                              "low": "min", "close": "last",
                              "volume": "sum"}).dropna()
    return df


def scaled(n, tf):
    return max(1, int(round(n * BPH[tf])))


def dedupe(sig):
    return sig & ~sig.shift(1).fillna(False)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


SIGNALS = {
    "RangeKalman_LS": (sig_rangekalman, sig_rangekalman_short,
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800}),
    "BBBreak_LS": (sig_bbbreak, sig_bbbreak_short,
        {"n": 120, "k": 2.0, "regime_len": 600}),
}

# Also sweep signal-param variants for the winner family
RK_PARAM_VARIANTS = [
    {"alpha": a, "rng_len": rl, "rng_mult": rm, "regime_len": rg}
    for a in [0.05, 0.07, 0.09]
    for rl in [300, 400, 500]
    for rm in [2.0, 2.5, 3.0]
    for rg in [600, 800]
]
BB_PARAM_VARIANTS = [
    {"n": n, "k": k, "regime_len": rg}
    for n in [80, 120, 180]
    for k in [1.5, 2.0, 2.5]
    for rg in [300, 600, 900]
]


def scale_params(p, tf):
    return {k: (scaled(v, tf) if k in ("rng_len", "regime_len", "n") else v) for k, v in p.items()}


def one_run(df, tf, sig_name, lfn, sfn, params, tp, sl, trail, mh_bars, risk, lev):
    p = scale_params(params, tf)
    need = max(p.get("rng_len", 0), p.get("regime_len", 0), p.get("n", 0)) + 100
    if len(df) < need:
        return None
    try:
        ls = dedupe(lfn(df, **{k: v for k, v in p.items() if k in lfn.__code__.co_varnames}))
        ss = dedupe(sfn(df, **{k: v for k, v in p.items() if k in sfn.__code__.co_varnames})) if sfn else None
        trades, eq = simulate(df, ls, short_entries=ss,
                              tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh_bars,
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
        r = metrics(f"{sig_name}", eq, trades)
        r.update({"signal": sig_name, "tp": tp, "sl": sl, "trail": trail,
                  "mh": mh_bars, "risk": risk, "lev": lev, "params": str(p)})
        return r
    except Exception as e:
        return None


def hunt(sym, tfs):
    rows = []
    t0 = time.time()
    # Tighter exit/risk grids
    exits = [
        (7.0, 1.5, 4.5, 48), (7.0, 2.0, 4.5, 48), (5.0, 2.0, 3.5, 72),
        (10.0, 2.0, 6.0, 120), (7.0, 1.5, 4.5, 72), (5.0, 1.5, 3.5, 48),
    ]
    rl_grid = [(0.03, 3.0), (0.05, 3.0), (0.07, 3.0), (0.05, 5.0)]

    # Pass 1: default params, all exit × risk × tf
    for tf in tfs:
        df = _load(sym, tf)
        if df is None or len(df) < 3000:
            print(f"  {sym} {tf}: too short"); continue
        for sig_name, (lfn, sfn, defaults) in SIGNALS.items():
            for (tp, sl, trail, mh1h) in exits:
                mh = scaled(mh1h, tf)
                for (risk, lev) in rl_grid:
                    r = one_run(df, tf, sig_name, lfn, sfn, defaults, tp, sl, trail, mh, risk, lev)
                    if r is None: continue
                    r["asset"] = sym; r["tf"] = tf
                    rows.append(r)
                    if r.get("cagr_net", 0) >= 0.55 and r.get("dd", 0) >= -0.40 and r.get("n", 0) >= 30:
                        print(f"  HIT  {sym} {tf:3s} {sig_name:16s} tp{tp} sl{sl} tr{trail} mh{mh1h} r{risk} lev{lev}  "
                              f"CAGR {r['cagr_net']*100:6.1f}%  Sh {r['sharpe']:.2f}  DD {r['dd']*100:5.1f}%  n={r['n']}",
                              flush=True)
        print(f"  {sym} {tf} pass1 done ({time.time()-t0:.0f}s, {len(rows)} rows)", flush=True)

    # Pass 2: for each family, find best (tf, exit, risk) and sweep params
    df_p1 = pd.DataFrame(rows)
    for sig_name in SIGNALS:
        sub = df_p1[(df_p1["signal"] == sig_name) & (df_p1["dd"] >= -0.40) & (df_p1["n"] >= 30)]
        if not len(sub): continue
        best = sub.sort_values("cagr_net", ascending=False).iloc[0]
        tf = best["tf"]; tp = best["tp"]; sl = best["sl"]; trail = best["trail"]
        mh = best["mh"]; risk = best["risk"]; lev = best["lev"]
        print(f"  {sym} pass2 {sig_name}: best @{tf} tp{tp} sl{sl} tr{trail} mh{mh} r{risk} lev{lev} "
              f"CAGR {best['cagr_net']*100:.1f}%", flush=True)
        variants = RK_PARAM_VARIANTS if sig_name == "RangeKalman_LS" else BB_PARAM_VARIANTS
        lfn, sfn, _ = SIGNALS[sig_name]
        df = _load(sym, tf)
        for pv in variants:
            r = one_run(df, tf, sig_name, lfn, sfn, pv, tp, sl, trail, mh, risk, lev)
            if r is None: continue
            r["asset"] = sym; r["tf"] = tf
            rows.append(r)
            if r.get("cagr_net", 0) >= 0.55 and r.get("dd", 0) >= -0.40 and r.get("n", 0) >= 30:
                print(f"  HIT  {sym} {tf:3s} {sig_name:16s} {pv}  "
                      f"CAGR {r['cagr_net']*100:6.1f}%  Sh {r['sharpe']:.2f}  DD {r['dd']*100:5.1f}%  n={r['n']}",
                      flush=True)
    return rows


def main():
    all_rows = []
    print("=== BTC ===", flush=True)
    all_rows.extend(hunt("BTCUSDT", ["2h", "4h", "6h", "8h"]))
    print("\n=== SOL ===", flush=True)
    all_rows.extend(hunt("SOLUSDT", ["1h", "2h", "4h", "6h"]))

    out = pd.DataFrame(all_rows)
    out.to_csv(OUT / "v21b_results.csv", index=False)

    cols = ["asset", "tf", "signal", "tp", "sl", "trail", "mh", "risk", "lev",
            "params", "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev"]

    for sym in ["BTCUSDT", "SOLUSDT"]:
        print("\n" + "=" * 90)
        print(f"{sym}: top configs (cagr_net >= 55%, dd >= -40%, n >= 30)")
        print("=" * 90)
        ok = out[(out["asset"] == sym) & (out["cagr_net"] >= 0.55) &
                 (out["dd"] >= -0.40) & (out["n"] >= 30)]
        if len(ok):
            print(ok.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))
        else:
            sub = out[(out["asset"] == sym) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
            top = sub.sort_values("cagr_net", ascending=False).head(10)
            print(f"  NONE hit 55% — top 10 under DD cap:")
            print(top[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
