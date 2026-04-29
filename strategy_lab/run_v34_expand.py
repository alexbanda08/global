"""
V34 — Portfolio expansion round.

Three focused phases:
  A. BBBreak_LS on uncovered coins (LINK, AVAX, INJ, TON) — extend V23's cleanest family
  B. HTF_Donchian on uncovered coins (LINK, AVAX, INJ, TON, SUI) — extend V27
  C. Multi-pair ratio mean-reversion (SOL/ETH, DOGE/BTC, SUI/ETH, LINK/ETH, DOGE/SOL)
     — denser sweep than V33's ETHBTC, targeting plateau region

Small trial counts (~500 configs) so DSR bar is reachable.
"""
from __future__ import annotations
import sys, pickle, warnings, time, itertools
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd
import talib

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics, atr, ema, bb
from strategy_lab.run_v23_all_coins import sig_bbbreak_short
from strategy_lab.run_v27_swing import sig_htf_donchian
from strategy_lab.run_v16_1h_hunt import sig_bbbreak

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v34"
OUT.mkdir(parents=True, exist_ok=True)

FEE = 0.00045
SINCE = pd.Timestamp("2020-01-01", tz="UTC")

BPH = {"15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
def scaled(n, tf): return max(1, int(round(n * BPH[tf])))


def _load(sym, tf):
    p = FEAT / f"{sym}_{tf}.parquet"
    if not p.exists(): return None
    df = pd.read_parquet(p).dropna(subset=["open","high","low","close","volume"])
    return df[df.index >= SINCE]


def sig_bbbreak_ls(df, n, k, regime_len):
    ls = sig_bbbreak(df, n, k, regime_len)
    ss = sig_bbbreak_short(df, n, k, regime_len)
    return ls, ss


def sig_htf_donchian_ls(df, donch_n=20, ema_reg=200):
    # v27 already returns (long, short) tuple
    ls, ss = sig_htf_donchian(df, donch_n, ema_reg)
    return ls, ss


def sig_pair_ratio_revert(df_base, df_other, z_lookback=100, z_thr=2.0):
    """Trade df_base based on z-score of df_base/df_other ratio."""
    common = df_base.index.intersection(df_other.index)
    ratio = df_base.loc[common, "close"] / df_other.loc[common, "close"]
    mu = ratio.rolling(z_lookback).mean()
    sd = ratio.rolling(z_lookback).std()
    z = (ratio - mu) / sd.replace(0, np.nan)
    long_edge = (z > -z_thr) & (z.shift(1) <= -z_thr)
    short_edge = (z < z_thr) & (z.shift(1) >= z_thr)
    ls = long_edge.reindex(df_base.index).fillna(False).astype(bool)
    ss = short_edge.reindex(df_base.index).fillna(False).astype(bool)
    return ls, ss


# Exits
EXITS_4H = [
    dict(tp=10.0, sl=2.0, trail=6.0, mh=30),
    dict(tp=7.0, sl=1.5, trail=4.5, mh=12),
]
EXITS_1H = [
    dict(tp=10.0, sl=2.0, trail=6.0, mh=120),
    dict(tp=7.0, sl=1.5, trail=4.5, mh=48),
]
RISKS = [0.03, 0.05]
LEV = 3.0


def sweep_family(family, sym, tf, df, extras=None, grid=None, exits=EXITS_4H):
    best = None
    n_tried = 0
    for combo in itertools.product(*[grid[k] for k in grid]):
        params = dict(zip(grid.keys(), combo))
        try:
            if family == "BBBreak_LS":
                # Scale lengths for TF
                p = dict(params)
                p["regime_len"] = scaled(p["regime_len"], tf)
                p["n"] = scaled(p["n"], tf)
                ls, ss = sig_bbbreak_ls(df, **p)
            elif family == "HTF_Donchian":
                ls, ss = sig_htf_donchian_ls(df, **params)
            elif family == "Pair_Ratio":
                other_df = extras
                ls, ss = sig_pair_ratio_revert(df, other_df, **params)
            else:
                continue
        except Exception:
            continue
        for ex in exits:
            for risk in RISKS:
                n_tried += 1
                tr, eq = simulate(df, ls, ss,
                                  tp_atr=ex["tp"], sl_atr=ex["sl"],
                                  trail_atr=ex["trail"], max_hold=ex["mh"],
                                  risk_per_trade=risk, leverage_cap=LEV, fee=FEE)
                m = metrics(f"{sym}_{family}_{tf}", eq, tr)
                if m["n"] < 30 or m["dd"] < -0.45: continue
                score = m["cagr_net"] * max(0.01, m["sharpe"] / 1.5)
                rec = dict(m, sym=sym, family=family, tf=tf, params=params,
                           exits=ex, risk=risk, lev=LEV, score=score)
                if best is None or rec["score"] > best["score"]:
                    best = rec
    return best, n_tried


def main():
    t0 = time.time()
    results = {}
    total_tried = 0

    # ----- Phase A: BBBreak_LS on uncovered coins -----
    print(f"\n{'='*70}\nPHASE A: V23 BBBreak_LS extension\n{'='*70}")
    bb_grid = {"n": [45, 90, 180], "k": [1.5, 2.0, 2.5], "regime_len": [150, 300, 600]}
    for sym in ("LINKUSDT", "AVAXUSDT", "INJUSDT", "TONUSDT"):
        df = _load(sym, "4h")
        if df is None or len(df) < 500: continue
        best, n = sweep_family("BBBreak_LS", sym, "4h", df, grid=bb_grid, exits=EXITS_4H)
        total_tried += n
        if best:
            key = f"{sym}_BBBreak_LS_4h"
            results[key] = best
            print(f"[{time.time()-t0:5.1f}s] {key:40s} CAGR={best['cagr_net']*100:+6.1f}% "
                  f"Sh={best['sharpe']:+.2f} n={best['n']:3d} DD={best['dd']*100:+.1f}%")

    # ----- Phase B: HTF_Donchian on uncovered coins -----
    print(f"\n{'='*70}\nPHASE B: V27 HTF_Donchian extension\n{'='*70}")
    dc_grid = {"donch_n": [10, 20, 30, 40], "ema_reg": [100, 200]}
    for sym in ("LINKUSDT", "AVAXUSDT", "INJUSDT", "TONUSDT", "SUIUSDT"):
        df = _load(sym, "4h")
        if df is None or len(df) < 500: continue
        best, n = sweep_family("HTF_Donchian", sym, "4h", df, grid=dc_grid, exits=EXITS_4H)
        total_tried += n
        if best:
            key = f"{sym}_HTF_Donchian_4h"
            results[key] = best
            print(f"[{time.time()-t0:5.1f}s] {key:40s} CAGR={best['cagr_net']*100:+6.1f}% "
                  f"Sh={best['sharpe']:+.2f} n={best['n']:3d} DD={best['dd']*100:+.1f}%")

    # ----- Phase C: Pair Ratio Revert -----
    print(f"\n{'='*70}\nPHASE C: Multi-pair ratio mean-reversion\n{'='*70}")
    pairs = [
        ("SOLUSDT", "ETHUSDT"),
        ("DOGEUSDT", "BTCUSDT"),
        ("SUIUSDT", "ETHUSDT"),
        ("LINKUSDT", "ETHUSDT"),
        ("DOGEUSDT", "SOLUSDT"),
        ("AVAXUSDT", "ETHUSDT"),
        ("INJUSDT", "ETHUSDT"),
    ]
    pair_grid = {"z_lookback": [50, 100, 200], "z_thr": [1.5, 2.0, 2.5, 3.0]}
    for base, other in pairs:
        for tf in ("1h", "4h"):
            df = _load(base, tf)
            other_df = _load(other, tf)
            if df is None or other_df is None: continue
            ex_list = EXITS_4H if tf == "4h" else EXITS_1H
            best, n = sweep_family("Pair_Ratio", base, tf, df,
                                    extras=other_df, grid=pair_grid, exits=ex_list)
            total_tried += n
            if best:
                key = f"{base}_{other}_PairRatio_{tf}"
                best["other_sym"] = other
                results[key] = best
                print(f"[{time.time()-t0:5.1f}s] {key:40s} CAGR={best['cagr_net']*100:+6.1f}% "
                      f"Sh={best['sharpe']:+.2f} n={best['n']:3d} DD={best['dd']*100:+.1f}%")

    print(f"\nTotal tried: {total_tried} configs in {time.time()-t0:.1f}s")
    print(f"Winners: {len(results)}")
    with open(OUT / "v34_sweep_results.pkl", "wb") as f:
        pickle.dump(results, f)
    print(f"Saved: {OUT/'v34_sweep_results.pkl'}")

    # Print top 20 by score
    sorted_w = sorted(results.items(), key=lambda x: -x[1]["score"])
    print(f"\nTop 20 by score:")
    for i, (k, w) in enumerate(sorted_w[:20]):
        print(f"  {i+1:2d}. {k:45s} CAGR={w['cagr_net']*100:+6.1f}%  Sh={w['sharpe']:+.2f}  n={w['n']:3d}")


if __name__ == "__main__":
    main()
