"""
V24 — Regime Router.

Build a 4-regime classifier (TREND_UP, TREND_DN, RANGE, CHOP) from
Hurst + ADX + SMA-trend, then route each bar to the right sub-strategy:

  TREND_UP  →  Donchian long-only breakout     (ride trend)
  TREND_DN  →  Donchian short-only breakout    (ride trend)
  RANGE     →  BB mean-revert long + short     (fade extremes)
  CHOP      →  flat                            (skip — no edge)

The signals for each sub-strategy are computed independently, then the
regime mask gates which ones actually fire. We sweep across 1h/2h/4h for
each coin and pick the best-scoring config.

References: ADX>25 + Hurst>0.55 = trending; ADX<20 + Hurst<0.45 = ranging
(from Volatility Regime Classifier literature).
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v24"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045
BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
         "DOGEUSDT", "INJUSDT", "SUIUSDT", "TONUSDT"]


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    return pd.read_parquet(p).dropna(subset=["open","high","low","close","volume"])


def scaled(n, tf): return max(1, int(round(n * BPH[tf])))


def dedupe(s): return s & ~s.shift(1).fillna(False)


# ---------- Regime classifier ----------

def regime_label(df: pd.DataFrame, tf: str,
                 adx_len=14, sma_fast=50, sma_slow=200,
                 adx_trend=25, adx_range=18):
    """Fast regime labeling using ADX + SMA slope. Hurst dropped for speed
    (it was ~O(n*lookback) pure Python). ADX already captures trend strength
    and SMA50 > SMA200 captures direction — that's sufficient for routing.

    Returns int: 1=TREND_UP, -1=TREND_DN, 0=RANGE, 2=CHOP."""
    sma_fast = scaled(sma_fast, tf)
    sma_slow = scaled(sma_slow, tf)

    sma50 = df["close"].rolling(sma_fast).mean()
    sma200 = df["close"].rolling(sma_slow).mean()
    adx = talib.ADX(df["high"].values, df["low"].values, df["close"].values, adx_len)
    adx_s = pd.Series(adx, index=df.index)

    trend_up = (df["close"] > sma200) & (sma50 > sma200) & (adx_s > adx_trend)
    trend_dn = (df["close"] < sma200) & (sma50 < sma200) & (adx_s > adx_trend)
    # Range: close near SMA200, low ADX
    near_sma = (df["close"] / sma200 - 1).abs() < 0.05
    range_z = (adx_s < adx_range) & near_sma

    reg = pd.Series(2, index=df.index)  # default: CHOP
    reg[range_z] = 0
    reg[trend_up] = 1
    reg[trend_dn] = -1
    return reg.astype(int)


# ---------- Sub-strategies ----------

def sig_donchian_up(df, n, regime):
    hi_break = df["high"].rolling(n).max().shift(1)
    sig = (df["close"] > hi_break) & (regime == 1)
    return sig.fillna(False).astype(bool)


def sig_donchian_dn(df, n, regime):
    lo_break = df["low"].rolling(n).min().shift(1)
    sig = (df["close"] < lo_break) & (regime == -1)
    return sig.fillna(False).astype(bool)


def sig_bb_meanrevert_long(df, n, k, regime):
    m = df["close"].rolling(n).mean()
    s = df["close"].rolling(n).std()
    lb = m - k * s
    # Fade the lower band in RANGE regime only
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & (regime == 0)
    return sig.fillna(False).astype(bool)


def sig_bb_meanrevert_short(df, n, k, regime):
    m = df["close"].rolling(n).mean()
    s = df["close"].rolling(n).std()
    ub = m + k * s
    sig = (df["close"] > ub) & (df["close"].shift(1) <= ub.shift(1)) & (regime == 0)
    return sig.fillna(False).astype(bool)


def sig_regime_combined(df, tf, donch_n, bb_n, bb_k, reg=None):
    if reg is None:
        reg = regime_label(df, tf)
    donch_n = scaled(donch_n, tf)
    bb_n = scaled(bb_n, tf)
    long = sig_donchian_up(df, donch_n, reg) | sig_bb_meanrevert_long(df, bb_n, bb_k, reg)
    short = sig_donchian_dn(df, donch_n, reg) | sig_bb_meanrevert_short(df, bb_n, bb_k, reg)
    return long, short, reg


# ---------- Sweep ----------

def run_one(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig)
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def sweep(sym):
    """Regime-router sweep across 1h/2h/4h. Regime computed once per TF."""
    best = None
    for tf in ["1h", "2h", "4h"]:
        df = _load(sym, tf)
        if df is None or len(df) < 2000: continue
        # Compute regime ONCE per (sym, tf)
        reg = regime_label(df, tf)
        reg_counts = {int(k): int(v) for k, v in reg.value_counts().to_dict().items()}
        for donch in [40, 80, 120]:
            for bb_n in [40, 80]:
                for bb_k in [2.0]:
                    try:
                        long, short, _ = sig_regime_combined(df, tf, donch, bb_n, bb_k, reg=reg)
                    except Exception:
                        continue
                    if long.sum() < 10 and short.sum() < 10: continue
                    for risk in [0.03, 0.05]:
                        for (tp, sl, tr, mh) in [
                            (10, 2.0, 6.0, scaled(60, tf)),
                            (7,  1.5, 4.5, scaled(48, tf)),
                        ]:
                            r, trades, eq = run_one(df, long, short, tp, sl, tr, mh, risk, 3.0,
                                                     f"{sym}_{tf}_REG")
                            if r["n"] < 30 or r["dd"] < -0.40: continue
                            score = r["cagr_net"] * (r["sharpe"] / 1.5)
                            if best is None or score > best["score"]:
                                best = dict(
                                    sym=sym, family="Regime_Router", tf=tf,
                                    params=dict(donch_n=donch, bb_n=bb_n, bb_k=bb_k),
                                    exits=dict(tp=tp, sl=sl, trail=tr, mh=mh),
                                    risk=risk, lev=3.0,
                                    metrics=r, trades=trades, eq=eq,
                                    regime_counts=reg_counts,
                                    score=score,
                                )
    return best


def _persist(results, path):
    light = {}
    for sym, w in results.items():
        light[sym] = {
            "sym": sym, "family": w["family"], "tf": w["tf"],
            "params": w["params"], "exits": w["exits"],
            "risk": w["risk"], "lev": w["lev"],
            "metrics": w["metrics"],
            "trades": w["trades"],
            "regime_counts": w["regime_counts"],
            "eq_index": list(w["eq"].index.astype("int64").tolist()),
            "eq_values": w["eq"].values.tolist(),
        }
    with open(path, "wb") as f:
        pickle.dump(light, f)


def main():
    results = {}
    ckpt = OUT / "v24_regime_results.pkl"
    for sym in COINS:
        print(f"\n=== {sym} — Regime Router ===", flush=True)
        try:
            b = sweep(sym)
        except Exception as e:
            print(f"  FAIL: {e}")
            continue
        if b is None:
            print(f"  NO VIABLE CONFIG")
            continue
        results[sym] = b
        m = b["metrics"]
        print(f"  {b['tf']:3s}  CAGR {m['cagr_net']*100:6.1f}%  Sh {m['sharpe']:+.2f}  "
              f"DD {m['dd']*100:+6.1f}%  n={m['n']:4d}  "
              f"p={b['params']}  regimes={b['regime_counts']}", flush=True)
        _persist(results, ckpt)

    _persist(results, ckpt)

    flat = [{"sym": s, "family": w["family"], "tf": w["tf"],
             "params": str(w["params"]), "regimes": str(w["regime_counts"]),
             **{k: v for k, v in w["metrics"].items() if k != "label"}}
            for s, w in results.items()]
    pd.DataFrame(flat).to_csv(OUT / "v24_regime_summary.csv", index=False)

    print("\n" + "=" * 80)
    print("V24 REGIME ROUTER — per-coin winners")
    print("=" * 80)
    print(pd.DataFrame(flat).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
