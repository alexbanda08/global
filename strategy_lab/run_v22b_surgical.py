"""
V22b — Surgical BTC tune. Start from the 47.6% CAGR / -36% DD config and
push risk slightly higher + try signal-param tweaks to close the ~7% gap.
"""
from __future__ import annotations
import sys, time, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
    sig_bbbreak, bb,
)

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
OUT = Path(__file__).resolve().parent / "results" / "v22"
OUT.mkdir(parents=True, exist_ok=True)
FEE = 0.00045
SYM = "BTCUSDT"


def _load(tf):
    p = FEAT / f"{SYM}_{tf}.parquet"
    return pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])


def dedupe(s): return s & ~s.shift(1).fillna(False)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def run(df, tf, lbl, lsig, ssig, tp, sl, tr, mh, risk, lev):
    ls = dedupe(lsig)
    ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    r = metrics(lbl, eq, trades)
    r.update({"tf": tf, "lbl": lbl, "tp": tp, "sl": sl, "trail": tr, "mh": mh,
              "risk": risk, "lev": lev})
    return r


def main():
    rows = []
    # Start from best V21 BTC config: 2h, alpha=0.07, rng_len=200 (scaled from 400 at 1h), rng_mult=2.5, regime_len=400
    # Exits: tp=10, sl=2, tr=6, mh=60 (at 2h bars = 120h)
    # Risk was 3% → CAGR 47.6%, DD -36%. Push risk to 4-5%.
    df2h = _load("2h")
    df4h = _load("4h")

    # --- 1) Push risk on the V21 BTC winner ---
    base = dict(alpha=0.07, rng_len=200, rng_mult=2.5, regime_len=400)
    ls_sig = sig_rangekalman(df2h, **base)
    ss_sig = sig_rangekalman_short(df2h, **base)
    for (risk, lev) in [(0.035, 3.0), (0.04, 3.0), (0.045, 3.0), (0.05, 3.0), (0.045, 5.0)]:
        for (tp, sl, tr, mh) in [(10, 2.0, 6.0, 60), (10, 2.0, 6.0, 48), (10, 2.0, 6.0, 72),
                                  (10, 2.5, 6.0, 60), (8, 2.0, 5.0, 60), (10, 1.8, 5.5, 60)]:
            r = run(df2h, "2h", f"RK_LS_{base}", ls_sig, ss_sig, tp, sl, tr, mh, risk, lev)
            r["params"] = str(base); rows.append(r)

    # Param sweep at the best config
    print("--- pass 1: param sweep at 2h, tp=10/sl=2/trail=6/mh=60, risk=0.045 ---", flush=True)
    exits_fixed = (10.0, 2.0, 6.0, 60)
    for alpha in [0.05, 0.06, 0.07, 0.08, 0.09]:
        for rl in [150, 200, 250, 300]:
            for rm in [2.0, 2.5, 3.0]:
                for rg in [300, 400, 600, 800]:
                    if len(df2h) < max(rl, rg) + 50: continue
                    p = dict(alpha=alpha, rng_len=rl, rng_mult=rm, regime_len=rg)
                    lsig = sig_rangekalman(df2h, **p)
                    ssig = sig_rangekalman_short(df2h, **p)
                    for risk in [0.04, 0.05]:
                        r = run(df2h, "2h", f"RK_LS_sweep", lsig, ssig,
                                *exits_fixed, risk, 3.0)
                        r["params"] = str(p); rows.append(r)
                        if r["cagr_net"] >= 0.55 and r["dd"] >= -0.40 and r["n"] >= 30:
                            print(f"  HIT  r={risk}  {p}  CAGR {r['cagr_net']*100:.1f}%  Sh {r['sharpe']:.2f}  "
                                  f"DD {r['dd']*100:.1f}%  n={r['n']}", flush=True)

    # --- 2) Combine RK + BB (OR'd signals) on BTC 2h ---
    print("\n--- pass 2: RK OR BB combined signals ---", flush=True)
    for rk_p in [dict(alpha=0.07, rng_len=200, rng_mult=2.5, regime_len=400),
                 dict(alpha=0.09, rng_len=200, rng_mult=2.5, regime_len=400),
                 dict(alpha=0.07, rng_len=250, rng_mult=3.0, regime_len=600)]:
        for bb_p in [dict(n=60, k=2.0, regime_len=300),
                     dict(n=90, k=2.0, regime_len=400),
                     dict(n=120, k=2.0, regime_len=600)]:
            rk_l = sig_rangekalman(df2h, **rk_p)
            rk_s = sig_rangekalman_short(df2h, **rk_p)
            bb_l = sig_bbbreak(df2h, **bb_p)
            bb_s = sig_bbbreak_short(df2h, **bb_p)
            lsig = (rk_l.fillna(False) | bb_l.fillna(False)).astype(bool)
            ssig = (rk_s.fillna(False) | bb_s.fillna(False)).astype(bool)
            for risk in [0.03, 0.04, 0.05]:
                r = run(df2h, "2h", "RK_OR_BB", lsig, ssig, 10.0, 2.0, 6.0, 60, risk, 3.0)
                r["params"] = f"RK={rk_p}, BB={bb_p}"; rows.append(r)
                if r["cagr_net"] >= 0.55 and r["dd"] >= -0.40 and r["n"] >= 30:
                    print(f"  HIT COMBO r={risk}  RK={rk_p} BB={bb_p}  "
                          f"CAGR {r['cagr_net']*100:.1f}%  Sh {r['sharpe']:.2f}  DD {r['dd']*100:.1f}%  "
                          f"n={r['n']}", flush=True)

    # --- 3) Long-only variant on 4h ---
    print("\n--- pass 3: long-only on 4h ---", flush=True)
    base4h = dict(alpha=0.07, rng_len=100, rng_mult=2.5, regime_len=200)
    for alpha in [0.05, 0.07, 0.09]:
        for rl in [75, 100, 150, 200]:
            for rm in [2.0, 2.5, 3.0]:
                for rg in [150, 200, 300]:
                    if len(df4h) < max(rl, rg) + 50: continue
                    p = dict(alpha=alpha, rng_len=rl, rng_mult=rm, regime_len=rg)
                    lsig = sig_rangekalman(df4h, **p)
                    for risk in [0.05, 0.07]:
                        r = run(df4h, "4h", "RK_L_only", lsig, None, 10.0, 2.0, 6.0, 30, risk, 3.0)
                        r["params"] = str(p); rows.append(r)
                        if r["cagr_net"] >= 0.55 and r["dd"] >= -0.40 and r["n"] >= 30:
                            print(f"  HIT L-only 4h r={risk}  {p}  "
                                  f"CAGR {r['cagr_net']*100:.1f}%  Sh {r['sharpe']:.2f}  "
                                  f"DD {r['dd']*100:.1f}%  n={r['n']}", flush=True)

    out = pd.DataFrame(rows)
    out.to_csv(OUT / "v22b_btc.csv", index=False)
    print(f"\nTotal runs: {len(out)}")

    cols = ["tf", "lbl", "tp", "sl", "trail", "mh", "risk", "lev", "params",
            "n", "cagr", "cagr_net", "sharpe", "dd", "win", "pf", "avg_lev"]

    print("\n=== BTC: top 15 configs clearing 55% CAGR, DD >= -40% ===")
    ok = out[(out["cagr_net"] >= 0.55) & (out["dd"] >= -0.40) & (out["n"] >= 30)]
    if len(ok):
        print(ok.sort_values("cagr_net", ascending=False).head(15)[cols].to_string(index=False))
    else:
        sub = out[(out["dd"] >= -0.40) & (out["n"] >= 30)]
        print("NONE hit 55% — top 10:")
        print(sub.sort_values("cagr_net", ascending=False).head(10)[cols].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
