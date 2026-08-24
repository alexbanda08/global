"""
R5 — EXIT STRUCTURE on the validated STF + VP breadth portfolio.
================================================================

The shadow ledger's exit mix is the loudest symptom in the whole system:
70 of 92 closed paper trades hit the stop (-2.41% mean), 10 took profit (+18.4%),
12 timed out (+6.8%). EXIT_4H is tp 10 ATR / sl 2 ATR / trail 6 ATR / max_hold 60 —
a very tight stop paired with a very distant target. That is a deliberate
positive-skew design, but nobody has tested whether 2 ATR is the right stop.

Protocol (chosen to be hard to fool):
  1. Grid the exits on LONG_OOS (untouched, pre-2024-03) across the R4-validated
     families (STF, VP) x 10 coins.
  2. Rank on LONG_OOS, then report EVERY variant's HL_ERA result too. If the
     ranking does not transfer, the grid is noise and we keep the incumbent.
  3. Judge the incumbent EXIT_4H against the grid. Only adopt a change that is
     better in BOTH windows, otherwise keep the incumbent (do-nothing default).

Outputs: r5_exit_grid.csv
"""
from __future__ import annotations
import sys, glob, itertools, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from strategy_lab.strategies.v50_new_signals import sig_volume_profile_rot
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from _r2_long_history import gate_atr_notopvol
from _r4_family_universe import COINS, load_4h, SPLIT


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")

FAMILIES = {
    "STF": (_v30.sig_supertrend_flip, dict(st_n=10, st_mult=3.0, ema_reg=200)),
    "VP":  (sig_volume_profile_rot,   dict(win=60, n_bins=15)),
}
INCUMBENT = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

SL_GRID    = [1.5, 2.0, 2.5, 3.0, 4.0]
TRAIL_GRID = [4.0, 6.0, 8.0, None]
HOLD_GRID  = [30, 60, 90]
TP_GRID    = [10.0]          # tp is far away and rarely binding; probed separately below
TP_PROBE   = [6.0, 10.0, 15.0]


def stats(sub: pd.DataFrame) -> dict:
    if not len(sub):
        return dict(n=0, mean=np.nan, wr=np.nan, t=np.nan, tot=0.0, ex_top2=0.0)
    r = sub.ret_pct.to_numpy(float); p = sub.realized.to_numpy(float)
    o = np.sort(p)[::-1]
    t = (r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    return dict(n=len(r), mean=r.mean(), wr=100 * (r > 0).mean(), t=t,
                tot=p.sum(), ex_top2=p.sum() - o[:2].sum())


def main():
    # precompute signals once per (family, coin) — the grid only changes exits
    sig_cache = {}
    data = {}
    for c in COINS:
        df = load_4h(c)
        g = gate_atr_notopvol(df)
        data[c] = (df, pd.Series(0.0, index=df.index))
        for fam, (fn, params) in FAMILIES.items():
            out = fn(df, **params)
            le, se = out if isinstance(out, tuple) else (out, None)
            le = le.reindex(df.index).fillna(False) & g
            se = (se.reindex(df.index).fillna(False) & g) if se is not None \
                else pd.Series(False, index=df.index)
            sig_cache[(fam, c)] = (le, se)
    print(f"[r5] signals cached for {len(sig_cache)} (family, coin) cells")

    combos = [dict(tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh)
              for sl, tr, mh, tp in itertools.product(SL_GRID, TRAIL_GRID, HOLD_GRID, TP_GRID)]
    combos += [dict(tp_atr=tp, sl_atr=INCUMBENT["sl_atr"], trail_atr=INCUMBENT["trail_atr"],
                    max_hold=INCUMBENT["max_hold"]) for tp in TP_PROBE if tp != 10.0]
    print(f"[r5] {len(combos)} exit variants x {len(sig_cache)} cells = {len(combos)*len(sig_cache)} sims")

    rows = []
    for ci, cfg in enumerate(combos, 1):
        recs = []
        for (fam, c), (le, se) in sig_cache.items():
            df, fund = data[c]
            trades, _ = simulate_with_funding(df, le, se, fund, **cfg)
            for t in trades:
                ets = df.index[t["entry_idx"]]
                recs.append(dict(window="LONG_OOS" if ets < SPLIT else "HL_ERA",
                                 ret_pct=100 * t["ret"], realized=t["realized"], reason=t["reason"]))
        d = pd.DataFrame(recs)
        lo = stats(d[d.window == "LONG_OOS"]); he = stats(d[d.window == "HL_ERA"])
        sl_share = 100.0 * (d[d.window == "LONG_OOS"].reason == "SL").mean() if len(d) else np.nan
        is_inc = all(cfg[k] == INCUMBENT[k] for k in INCUMBENT)
        rows.append(dict(**{k: ("None" if v is None else v) for k, v in cfg.items()},
                         incumbent=is_inc, sl_share_pct=round(sl_share, 1),
                         lo_n=lo["n"], lo_mean=lo["mean"], lo_t=lo["t"], lo_ex_top2=lo["ex_top2"],
                         he_n=he["n"], he_mean=he["mean"], he_t=he["t"]))
        if ci % 12 == 0:
            print(f"  ...{ci}/{len(combos)}")

    g = pd.DataFrame(rows).sort_values("lo_mean", ascending=False)
    g.to_csv(HERE / "r5_exit_grid.csv", index=False)

    inc = g[g.incumbent].iloc[0]
    print(f"\n{'='*118}\nINCUMBENT  tp={inc.tp_atr} sl={inc.sl_atr} trail={inc.trail_atr} hold={inc.max_hold}")
    print(f"  LONG_OOS n={inc.lo_n} mean={inc.lo_mean:+.3f}% t={inc.lo_t:+.2f}  |  "
          f"HL_ERA n={inc.he_n} mean={inc.he_mean:+.3f}% t={inc.he_t:+.2f}  |  SL share={inc.sl_share_pct}%")
    print(f"  incumbent rank on LONG_OOS: {list(g.index).index(inc.name)+1} of {len(g)}")

    print(f"\n{'='*118}\nTOP 12 BY LONG_OOS  (does the ranking transfer to HL_ERA?)\n{'='*118}")
    print(f"{'tp':>5s} {'sl':>5s} {'trail':>6s} {'hold':>5s} {'SL%':>6s} | "
          f"{'LO n':>6s} {'LO mean':>8s} {'LO t':>6s} {'LO ex2$':>10s} | {'HE n':>6s} {'HE mean':>8s} {'HE t':>6s} | inc")
    print("-" * 118)
    for _, r in g.head(12).iterrows():
        print(f"{r.tp_atr:>5} {r.sl_atr:>5} {str(r.trail_atr):>6} {r.max_hold:>5} {r.sl_share_pct:>6} | "
              f"{r.lo_n:>6.0f} {r.lo_mean:>+8.3f} {r.lo_t:>+6.2f} {r.lo_ex_top2:>+10.0f} | "
              f"{r.he_n:>6.0f} {r.he_mean:>+8.3f} {r.he_t:>+6.2f} | {'<= INCUMBENT' if r.incumbent else ''}")

    # transfer check: rank correlation LONG_OOS -> HL_ERA
    sub = g.dropna(subset=["lo_mean", "he_mean"])
    rho = sub.lo_mean.corr(sub.he_mean, method="spearman")
    print(f"\nrank transfer LONG_OOS -> HL_ERA: spearman rho = {rho:+.3f}  "
          f"({'grid is informative' if rho > 0.3 else 'grid ranking does NOT transfer -> treat as noise, keep incumbent'})")

    # marginal effect of each knob (average over the rest) — more stable than the argmax
    print(f"\n{'='*70}\nMARGINAL EFFECT OF EACH KNOB (mean over all other settings)\n{'='*70}")
    for knob in ("sl_atr", "trail_atr", "max_hold"):
        agg = g.groupby(knob).agg(lo=("lo_mean", "mean"), he=("he_mean", "mean"),
                                  slshare=("sl_share_pct", "mean"), n=("lo_n", "mean")).round(3)
        print(f"\n  {knob}:"); print(agg.to_string())

    best = g.iloc[0]
    both_better = (best.lo_mean > inc.lo_mean) and (best.he_mean > inc.he_mean)
    print(f"\n{'='*70}\nDECISION\n{'='*70}")
    print(f"  best-on-LONG_OOS: tp={best.tp_atr} sl={best.sl_atr} trail={best.trail_atr} hold={best.max_hold}")
    print(f"    LO {best.lo_mean:+.3f}% (inc {inc.lo_mean:+.3f}) | HE {best.he_mean:+.3f}% (inc {inc.he_mean:+.3f})")
    print(f"  better in BOTH windows than incumbent? {both_better}")
    print(f"  -> {'ADOPT' if both_better else 'KEEP INCUMBENT (no variant wins both windows)'}")
    print("\n[r5] wrote r5_exit_grid.csv")


if __name__ == "__main__":
    main()
