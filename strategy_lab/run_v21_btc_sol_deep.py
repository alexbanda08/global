"""
V21 — Deep tune specifically for BTC and SOL.

V20 findings for these two:
  BTC 4h RangeKalman V17tight:  CAGR 21.5%, DD -26.8%, Sharpe 0.89, avg_lev 1.46
  SOL 2h RangeKalman balanced:  CAGR 29.4%, DD -29.9%, Sharpe 1.08, avg_lev 0.74
  SOL 2h RangeKalman V17tight:  CAGR 27.7%, DD -27.2%, Sharpe 0.85, avg_lev 0.97

Both have HEADROOM on DD (well under -40% cap) and low avg leverage (<2x).
Hypothesis: push risk_per_trade higher + lev_cap higher to convert that
headroom into CAGR. Also sweep signal params + longer TFs (6h, 8h, 12h, 1d).
"""
from __future__ import annotations
import sys, itertools, time
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

# Scale helper: 1h-bar param count to target TF
BPH = {"1h": 1, "2h": 0.5, "4h": 0.25, "6h": 1/6, "8h": 0.125, "12h": 1/12, "1d": 1/24}


def _load(sym, tf):
    if tf in ("1h", "2h", "4h", "15m", "30m"):
        p = FEAT / f"{sym}_{tf}.parquet"
    else:
        # Resample on the fly from 1h
        p1h = FEAT / f"{sym}_1h.parquet"
        if not p1h.exists(): return None
        df = pd.read_parquet(p1h)
        alias = {"6h": "6h", "8h": "8h", "12h": "12h", "1d": "1d"}[tf]
        df = df.resample(alias).agg({"open": "first", "high": "max",
                                     "low": "min", "close": "last",
                                     "volume": "sum"}).dropna()
        return df
    if not p.exists(): return None
    return pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])


def scaled(n, tf):
    return max(1, int(round(n * BPH[tf])))


def dedupe(sig):
    return sig & ~sig.shift(1).fillna(False)


def sig_donchian_long(df, n=55, regime_len=600):
    up = donchian_up(df["high"], n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    return pd.Series((df["close"].values > up) & regime, index=df.index).fillna(False)


def sig_donchian_short(df, n=55, regime_len=600):
    dn = donchian_dn(df["low"], n).values
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    return pd.Series((df["close"].values < dn) & regime_bear, index=df.index).fillna(False)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_keltner_adx(df, k_n=20, k_mult=1.5, adx_min=18, regime_len=600):
    mid = ema(df["close"], k_n)
    at = atr(df, k_n)
    up = mid + k_mult * at
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"] > up) & (df["close"].shift(1) <= up.shift(1)) & (ax > adx_min) & regime
    return sig.fillna(False).astype(bool)


def sig_keltner_adx_short(df, k_n=20, k_mult=1.5, adx_min=18, regime_len=600):
    mid = ema(df["close"], k_n)
    at = atr(df, k_n)
    lo = mid - k_mult * at
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lo) & (df["close"].shift(1) >= lo.shift(1)) & (ax > adx_min) & regime_bear
    return sig.fillna(False).astype(bool)


SIGNALS = {
    "RangeKalman_LS": (sig_rangekalman, sig_rangekalman_short,
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800}),
    "BBBreak_LS": (sig_bbbreak, sig_bbbreak_short,
        {"n": 120, "k": 2.0, "regime_len": 600}),
    "Donchian_LS": (sig_donchian_long, sig_donchian_short,
        {"n": 55, "regime_len": 600}),
    "Keltner_ADX_LS": (sig_keltner_adx, sig_keltner_adx_short,
        {"k_n": 20, "k_mult": 1.5, "adx_min": 18, "regime_len": 600}),
    "TrendRider_LS": (sig_trend_rider_long, sig_trend_rider_short,
        {"st_n": 14, "st_mult": 3.0, "regime_len": 600}),
}


def scale_params(p, tf):
    s = {}
    for k, v in p.items():
        s[k] = scaled(v, tf) if k in ("rng_len", "regime_len", "n") else v
    return s


def run_combo(sym, tf, sig_name, long_fn, short_fn, params,
              tp, sl, trail, mh_bars, risk, lev):
    df = _load(sym, tf)
    if df is None or len(df) < 3000:
        return None
    p = scale_params(params, tf)
    need = max(p.get("rng_len", 0), p.get("regime_len", 0), p.get("n", 0)) + 100
    if len(df) < need:
        return None
    try:
        ls = dedupe(long_fn(df, **{k: v for k, v in p.items() if k in long_fn.__code__.co_varnames}))
        ss = None
        if short_fn:
            ss = dedupe(short_fn(df, **{k: v for k, v in p.items() if k in short_fn.__code__.co_varnames}))
        trades, eq = simulate(df, ls, short_entries=ss,
                              tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh_bars,
                              risk_per_trade=risk, leverage_cap=lev, fee=FEE)
        r = metrics(f"{sym}_{tf}_{sig_name}", eq, trades)
        r.update({"asset": sym, "tf": tf, "signal": sig_name,
                  "tp": tp, "sl": sl, "trail": trail, "mh": mh_bars,
                  "risk": risk, "lev": lev, "params": str(p)})
        return r
    except Exception as e:
        return None


def hunt(sym, tfs):
    rows = []
    t0 = time.time()
    exit_grid = [
        {"tp": tp, "sl": sl, "trail": tr, "mh_1h": mh}
        for tp in [5.0, 7.0, 10.0]
        for sl in [1.5, 2.0, 2.5]
        for tr in [3.5, 4.5, 6.0]
        for mh in [48, 72, 120]
    ]
    risk_lev_grid = [(0.03, 3.0), (0.05, 3.0), (0.07, 3.0), (0.05, 5.0), (0.10, 3.0)]
    for tf in tfs:
        for sig_name, (lfn, sfn, params) in SIGNALS.items():
            for ex in exit_grid:
                mh_bars = scaled(ex["mh_1h"], tf)
                for (risk, lev) in risk_lev_grid:
                    r = run_combo(sym, tf, sig_name, lfn, sfn, params,
                                  ex["tp"], ex["sl"], ex["trail"], mh_bars,
                                  risk, lev)
                    if r is None: continue
                    rows.append(r)
        print(f"  {sym} {tf}: {len(rows)} total so far ({time.time()-t0:.0f}s)", flush=True)
    return rows


def main():
    all_rows = []
    # BTC: focus on 2h/4h/6h/8h/12h/1d
    print("=== BTC deep tune ===", flush=True)
    btc = hunt("BTCUSDT", ["2h", "4h", "6h", "8h", "12h"])
    all_rows.extend(btc)

    # SOL: focus on 1h/2h/4h/6h/8h
    print("\n=== SOL deep tune ===", flush=True)
    sol = hunt("SOLUSDT", ["1h", "2h", "4h", "6h", "8h"])
    all_rows.extend(sol)

    out = pd.DataFrame(all_rows)
    out.to_csv(OUT / "v21_results.csv", index=False)

    cols = ["asset", "tf", "signal", "tp", "sl", "trail", "mh", "risk", "lev",
            "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev"]

    for sym in ["BTCUSDT", "SOLUSDT"]:
        print("\n" + "=" * 80)
        print(f"{sym}: top configs (cagr_net >= 55%, dd >= -40%, n >= 30)")
        print("=" * 80)
        ok = out[(out["asset"] == sym) & (out["cagr_net"] >= 0.55) &
                 (out["dd"] >= -0.40) & (out["n"] >= 30)]
        if len(ok):
            print(ok.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))
        else:
            sub = out[(out["asset"] == sym) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
            top = sub.sort_values("cagr_net", ascending=False).head(10)
            print(f"  NONE hit 55% — top 10 under DD cap:")
            print(top[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
