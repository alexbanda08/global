"""
V22 — BTC-only final push to 55% CAGR.

Ideas to try:
  * Higher risk (7%, 10%, 15%) at 3x lev cap
  * Long-only variant (BTC has been a 5-yr bull — shorts may drag)
  * Combined signals: RangeKalman OR BBBreak (more trades)
  * Longer TFs: 6h, 8h, 12h, 1d
  * Tighter regime filter (higher SMA period)
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, atr, ema, kalman_ema,
    donchian_up, donchian_dn, bb,
    sig_rangekalman, sig_rangekalman_short,
    sig_bbbreak,
)

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v22"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
BPH = {"1h": 1, "2h": 0.5, "4h": 0.25, "6h": 1/6, "8h": 0.125, "12h": 1/12, "1d": 1/24}
SYM = "BTCUSDT"


def _load(tf):
    if tf in ("1h", "2h", "4h"):
        p = FEAT / f"{SYM}_{tf}.parquet"
        if not p.exists(): return None
        return pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])
    p1h = FEAT / f"{SYM}_1h.parquet"
    df = pd.read_parquet(p1h)
    df = df.resample(tf).agg({"open": "first", "high": "max",
                              "low": "min", "close": "last",
                              "volume": "sum"}).dropna()
    return df


def scaled(n, tf): return max(1, int(round(n * BPH[tf])))


def dedupe(s): return s & ~s.shift(1).fillna(False)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_combo_long(df, rk_params, bb_params):
    """OR-combine RangeKalman long and BBBreak long — more trades."""
    rk = sig_rangekalman(df, **rk_params)
    bbb = sig_bbbreak(df, **bb_params)
    return (rk.fillna(False) | bbb.fillna(False)).astype(bool)


def sig_combo_short(df, rk_params, bb_params):
    rk = sig_rangekalman_short(df, **rk_params)
    bbb = sig_bbbreak_short(df, **bb_params)
    return (rk.fillna(False) | bbb.fillna(False)).astype(bool)


def run(df, tf, variant, long_sig, short_sig, tp, sl, trail, mh1h, risk, lev):
    mh = scaled(mh1h, tf)
    try:
        ls = dedupe(long_sig)
        ss = dedupe(short_sig) if short_sig is not None else None
        trades, eq = simulate(df, ls, short_entries=ss,
                              tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh,
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
        r = metrics(variant, eq, trades)
        r.update({"tf": tf, "variant": variant, "tp": tp, "sl": sl, "trail": trail,
                  "mh": mh, "risk": risk, "lev": lev})
        return r
    except Exception as e:
        return None


def main():
    rows = []
    t0 = time.time()

    # RangeKalman parameter variants (1h-scale, will be scaled to tf)
    rk_variants = [
        {"alpha": a, "rng_len": rl, "rng_mult": rm, "regime_len": rg}
        for a in [0.05, 0.07, 0.09]
        for rl in [200, 300, 400, 500]
        for rm in [2.0, 2.5, 3.0]
        for rg in [400, 600, 800, 1200]
    ]
    bb_variants = [
        {"n": n, "k": k, "regime_len": rg}
        for n in [80, 120, 180]
        for k in [1.5, 2.0, 2.5]
        for rg in [600, 900, 1200]
    ]
    exits = [(tp, sl, tr, mh)
             for tp in [7.0, 10.0]
             for sl in [1.5, 2.0]
             for tr in [4.5, 6.0]
             for mh in [48, 72, 120]]
    rls = [(0.05, 3.0), (0.07, 3.0), (0.10, 3.0), (0.07, 5.0), (0.10, 5.0)]

    for tf in ["2h", "4h", "6h", "8h"]:
        df = _load(tf)
        if df is None or len(df) < 3000: continue
        print(f"\n--- BTC {tf} ({len(df)} bars) ---", flush=True)

        # Pre-compute all RK & BB signals once per (tf, params)
        rk_long = {}; rk_short = {}
        for rk in rk_variants:
            s = {k: (scaled(v, tf) if k in ("rng_len", "regime_len") else v) for k, v in rk.items()}
            key = tuple(s.items())
            if len(df) < max(s["rng_len"], s["regime_len"]) + 50: continue
            rk_long[key] = sig_rangekalman(df, **s)
            rk_short[key] = sig_rangekalman_short(df, **s)

        bb_long = {}; bb_short = {}
        for bv in bb_variants:
            s = {k: (scaled(v, tf) if k in ("n", "regime_len") else v) for k, v in bv.items()}
            key = tuple(s.items())
            if len(df) < max(s["n"], s["regime_len"]) + 50: continue
            bb_long[key] = sig_bbbreak(df, **s)
            bb_short[key] = sig_bbbreak_short(df, **s)

        # ---- Variant 1: pure RangeKalman L+S, higher risk ----
        for rk_key in list(rk_long.keys())[:54]:  # top half of RK variants
            rk_long_sig = rk_long[rk_key]; rk_short_sig = rk_short[rk_key]
            for (tp, sl, tr, mh) in exits[:12]:  # trim
                for (risk, lev) in rls:
                    r = run(df, tf, "RK_LS", rk_long_sig, rk_short_sig, tp, sl, tr, mh, risk, lev)
                    if r is None: continue
                    r["params"] = f"RK:{dict(rk_key)}"
                    rows.append(r)
                    if r.get("cagr_net", 0) >= 0.55 and r.get("dd", 0) >= -0.40 and r.get("n", 0) >= 30:
                        print(f"  HIT RK_LS {tf} tp{tp} sl{sl} tr{tr} mh{mh} r{risk} lev{lev}  "
                              f"CAGR {r['cagr_net']*100:.1f}%  Sh {r['sharpe']:.2f}  DD {r['dd']*100:.1f}%  "
                              f"n={r['n']}  p={dict(rk_key)}", flush=True)

        # ---- Variant 2: RK long-only (BTC bull bias) ----
        for rk_key in list(rk_long.keys())[:54]:
            for (tp, sl, tr, mh) in exits:
                for (risk, lev) in rls:
                    r = run(df, tf, "RK_L_only", rk_long[rk_key], None, tp, sl, tr, mh, risk, lev)
                    if r is None: continue
                    r["params"] = f"RK:{dict(rk_key)}"
                    rows.append(r)
                    if r.get("cagr_net", 0) >= 0.55 and r.get("dd", 0) >= -0.40 and r.get("n", 0) >= 30:
                        print(f"  HIT RK_L_only {tf} tp{tp} sl{sl} tr{tr} mh{mh} r{risk} lev{lev}  "
                              f"CAGR {r['cagr_net']*100:.1f}%  Sh {r['sharpe']:.2f}  DD {r['dd']*100:.1f}%  "
                              f"n={r['n']}  p={dict(rk_key)}", flush=True)

        print(f"  {tf} done  {len(rows)} rows ({time.time()-t0:.0f}s)", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v22_btc_results.csv", index=False)

    cols = ["tf", "variant", "tp", "sl", "trail", "mh", "risk", "lev",
            "params", "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev"]

    print("\n" + "=" * 80)
    print("BTC: top configs (cagr_net >= 55%, dd >= -40%, n >= 30)")
    print("=" * 80)
    ok = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
    if len(ok):
        print(ok.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))
    else:
        sub = out[(out["dd"] >= -0.40) & (out["n"] >= 30)]
        print("NONE hit 55% — top 15 under DD cap:")
        print(sub.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
