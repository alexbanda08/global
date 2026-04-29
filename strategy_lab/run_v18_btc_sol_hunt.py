"""
V18 — BTC & SOL 1h hunt.

Goal: find configs that clear 55% CAGR and DD >= -40% on BTC and SOL
under realistic TAKER fees (0.045% / side), with risk-per-trade sizing
and leverage cap <= 3x.

Signal families tested:
  * RangeKalman L/S            (V16 winner on ETH — tested here on BTC/SOL)
  * Donchian L/S               (V15)
  * BB breakout L/S            (V15)
  * SuperTrend-ADX             (V15)
  * Keltner-ADX                (V15)
  * MTF momentum (1d+4h+1h)    (V15)
  * TrendRider L/S             (V16, SuperTrend flip)

Sweep structure (two-pass):
  Pass 1: each signal family runs its default params with a small exit grid
          (TP, SL, Trail, MaxHold) at 3% risk, 3x lev cap, taker fees.
  Pass 2: for the top-3 family/exit combos per asset, re-sweep the signal
          params around their defaults.
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
    sig_bbbreak, sig_mtf, sig_trend_rider_long, sig_trend_rider_short,
)

ROOT = Path(__file__).resolve().parent.parent
FEAT = ROOT / "strategy_lab" / "features"
OUT = ROOT / "strategy_lab" / "results" / "v18"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045           # realistic taker / side
RISK_DEFAULT = 0.03
LEV_DEFAULT  = 3.0


# ============================================================
# Extra signal families not exported from v16 — re-implement
# ============================================================
def sig_donchian_long(df, n=55, regime_len=600):
    up = donchian_up(df["high"], n).values
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values > up) & regime
    return pd.Series(sig, index=df.index).fillna(False).astype(bool)


def sig_donchian_short(df, n=55, regime_len=600):
    dn = donchian_dn(df["low"], n).values
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"].values < dn) & regime_bear
    return pd.Series(sig, index=df.index).fillna(False).astype(bool)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_supertrend_adx(df, st_n=10, st_mult=3.0, adx_min=20, regime_len=600):
    tr = supertrend(df, st_n, st_mult)
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    tr_prev = np.roll(tr, 1)
    sig = (tr == 1) & (tr_prev == -1) & (ax > adx_min) & regime
    return pd.Series(sig, index=df.index)


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


# ============================================================
# Signal registry: (name, long_fn, short_fn_or_None, default_params)
# ============================================================
SIGNALS = {
    "RangeKalman_LS":    (sig_rangekalman, sig_rangekalman_short,
                          dict(alpha=0.07, rng_len=400, rng_mult=2.5, regime_len=800)),
    "Donchian_LS":       (sig_donchian_long, sig_donchian_short,
                          dict(n=55, regime_len=600)),
    "BBBreak_LS":        (sig_bbbreak, sig_bbbreak_short,
                          dict(n=120, k=2.0, regime_len=600)),
    "Keltner_ADX_LS":    (sig_keltner_adx, sig_keltner_adx_short,
                          dict(k_n=20, k_mult=1.5, adx_min=18, regime_len=600)),
    "SuperTrend_ADX_L":  (sig_supertrend_adx, None,
                          dict(st_n=10, st_mult=3.0, adx_min=20, regime_len=600)),
    "MTF_L":             (sig_mtf, None,
                          dict(don_n=24, d_ema=200, h4_ema=50)),
    "TrendRider_LS":     (sig_trend_rider_long, sig_trend_rider_short,
                          dict(st_n=14, st_mult=3.0, regime_len=600)),
}


def _dedupe(sig):
    """Remove back-to-back True values so we only take the first bar of each cluster."""
    return sig & ~sig.shift(1).fillna(False)


def _load(sym, start="2019-01-01", end="2026-04-01"):
    df = pd.read_parquet(FEAT / f"{sym}_1h_features.parquet")
    df = df.dropna(subset=["open", "high", "low", "close", "volume"]).copy()
    df = df[(df.index >= pd.Timestamp(start, tz="UTC")) & (df.index < pd.Timestamp(end, tz="UTC"))]
    return df


def run_one(df, name, long_fn, short_fn, params, tp, sl, trail, mh,
            risk=RISK_DEFAULT, lev=LEV_DEFAULT, fee=FEE):
    ls = _dedupe(long_fn(df, **params))
    ss = _dedupe(short_fn(df, **params)) if short_fn else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=trail, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=fee)
    r = metrics(f"{name}_tp{tp}_sl{sl}_tr{trail}_mh{mh}_r{risk}", eq, trades)
    r.update({"signal": name, "tp": tp, "sl": sl, "trail": trail, "mh": mh,
              "risk": risk, "lev": lev})
    return r


# ============================================================
# Pass 1: exit grid × all signal families × default params
# ============================================================
EXIT_GRID_P1 = [
    {"tp": tp, "sl": sl, "trail": tr, "mh": mh}
    for tp in [5.0, 7.0]
    for sl in [1.5, 2.0]
    for tr in [3.5, 4.5]
    for mh in [48, 72]
]


def pass1(df, sym):
    rows = []
    t0 = time.time()
    for sig_name, (lfn, sfn, params) in SIGNALS.items():
        for exits in EXIT_GRID_P1:
            try:
                r = run_one(df, sig_name, lfn, sfn, params,
                            exits["tp"], exits["sl"], exits["trail"], exits["mh"])
                r["asset"] = sym
                rows.append(r)
            except Exception as e:
                rows.append({"asset": sym, "signal": sig_name, **exits, "err": str(e)[:100]})
    print(f"  {sym} pass1: {len(rows)} runs in {time.time()-t0:.1f}s", flush=True)
    return rows


# ============================================================
# Pass 2: sweep signal params for top-N signal families
# ============================================================
PARAM_SWEEPS = {
    "RangeKalman_LS": [
        {"alpha": a, "rng_len": rl, "rng_mult": rm, "regime_len": rg}
        for a in [0.05, 0.07, 0.09]
        for rl in [300, 400, 500]
        for rm in [2.0, 2.5, 3.0]
        for rg in [600, 800, 1000]
    ],
    "Donchian_LS": [
        {"n": n, "regime_len": rg}
        for n in [30, 55, 90, 120]
        for rg in [300, 600, 900]
    ],
    "BBBreak_LS": [
        {"n": n, "k": k, "regime_len": rg}
        for n in [60, 120, 200]
        for k in [1.5, 2.0, 2.5]
        for rg in [300, 600, 900]
    ],
    "Keltner_ADX_LS": [
        {"k_n": kn, "k_mult": km, "adx_min": am, "regime_len": rg}
        for kn in [14, 20, 30]
        for km in [1.0, 1.5, 2.0]
        for am in [15, 20, 25]
        for rg in [300, 600]
    ],
    "SuperTrend_ADX_L": [
        {"st_n": sn, "st_mult": sm, "adx_min": am, "regime_len": rg}
        for sn in [7, 10, 14]
        for sm in [2.0, 3.0, 4.0]
        for am in [15, 20, 25]
        for rg in [300, 600]
    ],
    "MTF_L": [
        {"don_n": dn, "d_ema": de, "h4_ema": he}
        for dn in [12, 24, 48]
        for de in [100, 200]
        for he in [25, 50, 100]
    ],
    "TrendRider_LS": [
        {"st_n": sn, "st_mult": sm, "regime_len": rg}
        for sn in [7, 14, 21]
        for sm in [2.0, 3.0, 4.0]
        for rg in [300, 600, 900]
    ],
}


def pass2(df, sym, top_exits_per_sig):
    """For each signal family that had at least one decent pass-1 result,
    sweep its params using the best exit found in pass 1 for that family."""
    rows = []
    t0 = time.time()
    for sig_name, best_exit in top_exits_per_sig.items():
        if sig_name not in PARAM_SWEEPS:
            continue
        lfn, sfn, _ = SIGNALS[sig_name]
        pgrid = PARAM_SWEEPS[sig_name]
        print(f"    {sym} pass2 {sig_name}: {len(pgrid)} param combos with best exit {best_exit}",
              flush=True)
        for params in pgrid:
            try:
                r = run_one(df, sig_name, lfn, sfn, params,
                            best_exit["tp"], best_exit["sl"], best_exit["trail"], best_exit["mh"])
                r["asset"] = sym
                r["params_str"] = ",".join(f"{k}={v}" for k, v in params.items())
                rows.append(r)
            except Exception as e:
                pass
    print(f"  {sym} pass2: {len(rows)} runs in {time.time()-t0:.1f}s", flush=True)
    return rows


# ============================================================
# Main
# ============================================================
def hunt_one_asset(sym, start="2019-01-01", end="2026-04-01"):
    print(f"\n=== Hunting {sym} ({start} -> {end}) ===", flush=True)
    df = _load(sym, start, end)
    print(f"  bars: {len(df):,}", flush=True)
    if len(df) < 2000:
        print("  SKIP: too few bars"); return None

    p1 = pass1(df, sym)
    p1_df = pd.DataFrame(p1)
    # Filter clean (no error) results
    p1_ok = p1_df.dropna(subset=["cagr"]).copy() if "cagr" in p1_df.columns else p1_df.copy()
    # Per-signal best exit by cagr_net (with DD cap)
    top_exits_per_sig = {}
    for sig_name in SIGNALS.keys():
        sub = p1_ok[(p1_ok["signal"] == sig_name) & (p1_ok["dd"] >= -0.40)]
        if len(sub) == 0:
            sub = p1_ok[p1_ok["signal"] == sig_name]
        if len(sub):
            best = sub.sort_values("cagr_net", ascending=False).iloc[0]
            top_exits_per_sig[sig_name] = {"tp": float(best["tp"]), "sl": float(best["sl"]),
                                            "trail": float(best["trail"]), "mh": int(best["mh"])}

    p2 = pass2(df, sym, top_exits_per_sig)
    all_rows = p1 + p2
    out = pd.DataFrame(all_rows)
    out.to_csv(OUT / f"v18_{sym}_results.csv", index=False)
    return out


def main():
    btc = hunt_one_asset("BTCUSDT", "2019-01-01", "2026-04-01")
    sol = hunt_one_asset("SOLUSDT", "2020-09-01", "2026-04-01")

    cols = ["signal", "params_str", "tp", "sl", "trail", "mh", "risk", "lev",
            "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev", "exposure"]

    for label, df in [("BTC", btc), ("SOL", sol)]:
        print(f"\n=== {label}: top configs under taker fees (DD >= -40%) ===")
        if df is None or "cagr" not in df.columns:
            print("  no results"); continue
        ok = df.dropna(subset=["cagr"])
        filt = ok[(ok["dd"] >= -0.40) & (ok["cagr_net"] >= 0.55)]
        if len(filt) == 0:
            filt = ok[(ok["dd"] >= -0.40)].sort_values("cagr_net", ascending=False).head(10)
            print(f"  [no configs hit 55% CAGR cap; showing top 10 under DD cap]")
        else:
            print(f"  {len(filt)} configs clear 55% CAGR & -40% DD")
        for col in cols:
            if col not in filt.columns: filt[col] = None
        top = filt.sort_values("cagr_net", ascending=False).head(10)
        print(top[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
