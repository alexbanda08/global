"""
V20 — Big hunt across multiple timeframes and multiple assets.

Assets (9): BTC, ETH, SOL, LINK, AVAX, DOGE, INJ, SUI, TON
Timeframes (5): 15m, 30m, 1h, 2h, 4h
Signals: RangeKalman_LS, Donchian_LS, BBBreak_LS, Keltner_ADX_LS, TrendRider_LS

Strategy: fast Pass-1 with one V17-style exit config at each TF, pick promising
(asset, tf, signal) triples, then finer tune.

Key insight: TF-scale signal params so rolling windows have the same wall-clock
meaning across TFs.
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
OUT = Path(__file__).resolve().parent / "results" / "v20"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
RISK = 0.03
LEV = 3.0

ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
          "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]
TFS = ["15m", "30m", "1h", "2h", "4h"]

# bars-per-hour multiplier: number of 'tf bars' per 1h
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}


def _load(sym, tf):
    df = pd.read_parquet(FEAT / f"{sym}_{tf}.parquet")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    return df


def scaled(n, tf):
    """Scale a bar count defined at 1h to the target TF."""
    return max(1, int(round(n * BPH[tf])))


def dedupe(sig):
    return sig & ~sig.shift(1).fillna(False)


# Extra signal families needed
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


# Signal registry. `params_at_1h` are the defaults used for 1h; scaled for other TFs.
SIGNALS = {
    "RangeKalman_LS": (sig_rangekalman, sig_rangekalman_short,
        {"alpha": 0.07, "rng_len": 400, "rng_mult": 2.5, "regime_len": 800}),
    "Donchian_LS": (sig_donchian_long, sig_donchian_short,
        {"n": 55, "regime_len": 600}),
    "BBBreak_LS": (sig_bbbreak, sig_bbbreak_short,
        {"n": 120, "k": 2.0, "regime_len": 600}),
    "Keltner_ADX_LS": (sig_keltner_adx, sig_keltner_adx_short,
        {"k_n": 20, "k_mult": 1.5, "adx_min": 18, "regime_len": 600}),
    "TrendRider_LS": (sig_trend_rider_long, sig_trend_rider_short,
        {"st_n": 14, "st_mult": 3.0, "regime_len": 600}),
}


def scale_params(p, tf):
    """Scale bar-length parameters."""
    s = {}
    for k, v in p.items():
        if k in ("rng_len", "regime_len", "n"):
            s[k] = scaled(v, tf)
        else:
            s[k] = v
    return s


# Exit configs tuned to the V17 archetype (tight SL, wide TP) + one balanced
EXIT_CONFIGS = [
    {"tp": 7.0, "sl": 1.5, "trail": 4.5, "mh_1h": 48, "label": "V17tight"},
    {"tp": 5.0, "sl": 2.0, "trail": 3.5, "mh_1h": 72, "label": "balanced"},
]


def run_combo(sym, tf, sig_name, long_fn, short_fn, params, exit_cfg):
    df = _load(sym, tf)
    if len(df) < 3000:
        return None
    p = scale_params(params, tf)
    # min bars check
    need = max(p.get("rng_len", 0), p.get("regime_len", 0), p.get("n", 0)) + 100
    if len(df) < need:
        return None
    mh = scaled(exit_cfg["mh_1h"], tf)
    try:
        ls = dedupe(long_fn(df, **{k: v for k, v in p.items() if k in long_fn.__code__.co_varnames}))
        ss = None
        if short_fn:
            ss_params = {k: v for k, v in p.items() if k in short_fn.__code__.co_varnames}
            ss = dedupe(short_fn(df, **ss_params))
        trades, eq = simulate(df, ls, short_entries=ss,
                              tp_atr=exit_cfg["tp"], sl_atr=exit_cfg["sl"],
                              trail_atr=exit_cfg["trail"], max_hold=mh,
                              risk_per_trade=RISK, leverage_cap=LEV, fee=FEE)
        r = metrics(f"{sym}_{tf}_{sig_name}_{exit_cfg['label']}", eq, trades)
        r.update({"asset": sym, "tf": tf, "signal": sig_name,
                  "exit": exit_cfg["label"], "tp": exit_cfg["tp"],
                  "sl": exit_cfg["sl"], "trail": exit_cfg["trail"], "mh": mh})
        return r
    except Exception as e:
        return {"asset": sym, "tf": tf, "signal": sig_name,
                "exit": exit_cfg["label"], "err": str(e)[:80]}


def main():
    rows = []
    t0 = time.time()
    total = len(ASSETS) * len(TFS) * len(SIGNALS) * len(EXIT_CONFIGS)
    print(f"Running {total} combos ...", flush=True)
    i = 0
    for sym in ASSETS:
        for tf in TFS:
            for sig_name, (lfn, sfn, params) in SIGNALS.items():
                for ec in EXIT_CONFIGS:
                    i += 1
                    r = run_combo(sym, tf, sig_name, lfn, sfn, params, ec)
                    if r is None:
                        continue
                    rows.append(r)
                    if r.get("cagr_net", 0) >= 0.55 and r.get("dd", 0) >= -0.40 and r.get("n", 0) >= 30:
                        print(f"  [{i}/{total}] {sym:8s} {tf:3s} {sig_name:16s} {ec['label']:9s}  "
                              f"CAGR {r['cagr_net']*100:6.1f}%  Sh {r['sharpe']:.2f}  "
                              f"DD {r['dd']*100:6.1f}%  n={r['n']}", flush=True)
            if i % 20 == 0:
                print(f"  progress: {i}/{total} ({time.time()-t0:.0f}s)", flush=True)
    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v20_results.csv", index=False)

    cols = ["asset", "tf", "signal", "exit", "n", "cagr", "cagr_net",
            "sharpe", "dd", "win", "pf", "avg_lev"]

    # Per-asset best
    print("\n" + "=" * 80)
    print("BEST CONFIG PER ASSET (cagr_net >= 55%, dd >= -40%, n >= 30)")
    print("=" * 80)
    ok = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
    for sym in ASSETS:
        sub = ok[ok["asset"] == sym]
        if len(sub):
            best = sub.sort_values("cagr_net", ascending=False).head(5)
            print(f"\n{sym}:")
            print(best[cols].to_string(index=False))
        else:
            sub_all = out[(out["asset"] == sym) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
            if len(sub_all):
                best = sub_all.sort_values("cagr_net", ascending=False).head(3)
                print(f"\n{sym} (none at 55% — top 3 under DD cap):")
                print(best[cols].to_string(index=False))
            else:
                print(f"\n{sym}: no valid runs")

    print(f"\nTotal runtime: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main() or 0)
