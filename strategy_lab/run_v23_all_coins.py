"""
V23 — Run winner signal families against ALL coins (BTC, ETH, SOL, LINK,
AVAX, DOGE, INJ, SUI, TON). For each coin, pick the best config from a
small grid search across TFs. Save equity curves + trades + metrics so
the PDF report can chart everything.
"""
from __future__ import annotations
import sys, warnings, pickle
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
    sig_bbbreak, bb, atr, ema,
)
import talib

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v23"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045
BPH = {"1h": 1, "2h": 0.5, "4h": 0.25}

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
         "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    return pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])


def dedupe(s): return s & ~s.shift(1).fillna(False)


def scaled(n, tf): return max(1, int(round(n * BPH[tf])))


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


def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig)
    ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    r = metrics(lbl, eq, trades)
    return r, trades, eq


# Strategy families with param sweeps
def sweep_rk(sym):
    """RangeKalman L+S sweep across 1h/2h/4h."""
    best = None
    for tf in ["1h", "2h", "4h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue
        for alpha in [0.05, 0.07, 0.09]:
            for rl_1h in [200, 300, 400]:
                for rm in [2.0, 2.5, 3.0]:
                    for rg_1h in [400, 600, 800]:
                        rl = scaled(rl_1h, tf); rg = scaled(rg_1h, tf)
                        if len(df) < max(rl, rg) + 100: continue
                        params = dict(alpha=alpha, rng_len=rl, rng_mult=rm, regime_len=rg)
                        try:
                            lsig = sig_rangekalman(df, **params)
                            ssig = sig_rangekalman_short(df, **params)
                        except Exception: continue
                        for risk in [0.03, 0.05]:
                            for (tp, sl, tr, mh) in [(10, 2.0, 6.0, scaled(120, tf)),
                                                      (7, 1.5, 4.5, scaled(48, tf))]:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_RK")
                                if r["n"] < 30 or r["dd"] < -0.40: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)  # reward CAGR + Sharpe
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="RangeKalman_LS", tf=tf,
                                                params=params, exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0,
                                                metrics=r, trades=trades, eq=eq,
                                                score=score)
    return best


def sweep_bb(sym):
    """BBBreak L+S sweep across 1h/2h/4h."""
    best = None
    for tf in ["1h", "2h", "4h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue
        for n_1h in [60, 90, 120, 180]:
            for k in [1.5, 2.0, 2.5]:
                for rg_1h in [300, 600, 900]:
                    n = scaled(n_1h, tf); rg = scaled(rg_1h, tf)
                    if len(df) < max(n, rg) + 100: continue
                    params = dict(n=n, k=k, regime_len=rg)
                    try:
                        lsig = sig_bbbreak(df, **params)
                        ssig = sig_bbbreak_short(df, **params)
                    except Exception: continue
                    for risk in [0.03, 0.05]:
                        for (tp, sl, tr, mh) in [(10, 2.0, 6.0, scaled(120, tf)),
                                                  (7, 1.5, 4.5, scaled(48, tf))]:
                            r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                    f"{sym}_{tf}_BB")
                            if r["n"] < 30 or r["dd"] < -0.40: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(sym=sym, family="BBBreak_LS", tf=tf,
                                            params=params, exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                            risk=risk, lev=3.0,
                                            metrics=r, trades=trades, eq=eq, score=score)
    return best


def sweep_keltner(sym):
    """Keltner+ADX L+S sweep across 1h/2h/4h."""
    best = None
    for tf in ["1h", "2h", "4h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue
        for k_n in [15, 20, 30]:
            for k_mult in [1.0, 1.5, 2.0]:
                for adx_min in [15, 18, 22]:
                    for rg_1h in [300, 600]:
                        rg = scaled(rg_1h, tf)
                        if len(df) < rg + 100: continue
                        params = dict(k_n=k_n, k_mult=k_mult, adx_min=adx_min, regime_len=rg)
                        try:
                            lsig = sig_keltner_adx(df, **params)
                            ssig = sig_keltner_adx_short(df, **params)
                        except Exception: continue
                        for risk in [0.03, 0.05]:
                            for (tp, sl, tr, mh) in [(5, 2.0, 3.5, scaled(72, tf)),
                                                      (7, 1.5, 4.5, scaled(48, tf))]:
                                r, trades, eq = run_one(df, lsig, ssig, tp, sl, tr, mh, risk, 3.0,
                                                        f"{sym}_{tf}_KEL")
                                if r["n"] < 30 or r["dd"] < -0.40: continue
                                score = r["cagr_net"] * (r["sharpe"] / 1.5)
                                if best is None or score > best["score"]:
                                    best = dict(sym=sym, family="KeltnerADX_LS", tf=tf,
                                                params=params, exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                                risk=risk, lev=3.0,
                                                metrics=r, trades=trades, eq=eq, score=score)
    return best


def main():
    results = {}
    for sym in COINS:
        print(f"\n=== {sym} ===", flush=True)
        candidates = []
        for sweep_fn, name in [(sweep_rk, "RK"), (sweep_bb, "BB"), (sweep_keltner, "KEL")]:
            try:
                b = sweep_fn(sym)
                if b is not None:
                    candidates.append(b)
                    m = b["metrics"]
                    print(f"  {name:3s}  {b['tf']:3s}  CAGR {m['cagr_net']*100:6.1f}%  "
                          f"Sh {m['sharpe']:+.2f}  DD {m['dd']*100:+6.1f}%  n={m['n']:4d}  "
                          f"p={b['params']}", flush=True)
            except Exception as e:
                print(f"  {name} FAILED: {e}")
        if not candidates:
            print(f"  NO VIABLE CONFIG for {sym}")
            continue
        winner = max(candidates, key=lambda c: c["score"])
        results[sym] = winner
        m = winner["metrics"]
        print(f"  → WINNER: {winner['family']} @ {winner['tf']}  "
              f"CAGR {m['cagr_net']*100:.1f}%  Sh {m['sharpe']:.2f}  DD {m['dd']*100:.1f}%", flush=True)

    # Save everything (with pickle for trades/eq, csv for flat metrics)
    with open(OUT / "v23_results.pkl", "wb") as f:
        # Store a lighter dict (eq as list, trades as list of dicts)
        light = {}
        for sym, w in results.items():
            light[sym] = {
                "sym": sym, "family": w["family"], "tf": w["tf"],
                "params": w["params"], "exits": w["exits"],
                "risk": w["risk"], "lev": w["lev"],
                "metrics": w["metrics"],
                "trades": w["trades"],
                "eq_index": list(w["eq"].index.astype("int64").tolist()),
                "eq_values": w["eq"].values.tolist(),
            }
        pickle.dump(light, f)

    flat = []
    for sym, w in results.items():
        m = w["metrics"]
        flat.append(dict(
            sym=sym, family=w["family"], tf=w["tf"],
            params=str(w["params"]), exits=str(w["exits"]),
            risk=w["risk"], lev=w["lev"],
            **{k: v for k, v in m.items() if k not in ("label",)},
        ))
    pd.DataFrame(flat).to_csv(OUT / "v23_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("FINAL PER-COIN WINNERS")
    print("=" * 80)
    print(pd.DataFrame(flat).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
