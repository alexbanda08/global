"""
R1 — HONEST WINDOW-SPLIT RE-TEST of the 9 optimized V52 sleeves.
================================================================

Why this exists
---------------
The V52 sleeve set + gates (FUND_Z<2, ATR_NOTOPVOL) + the new STF_BTC sleeve were
SELECTED on HL 4h data 2024-01-12 -> 2026-04-25 (see v52_v24_audit/OPTIMIZATION_RESULTS.md).
That window is in-sample by construction and cannot validate anything.

We now hold 3.3 years of HL 4h history per coin (2023-04-01 -> today), so there are
TWO windows the selection never touched:

  PRE   2023-04-01 -> 2024-01-12   (286d, before the selection window)
  IS    2024-01-12 -> 2026-04-25   (the selection window -- expect inflation)
  POST  2026-04-25 -> today        (93d, after the selection window)

A real edge must be positive in BOTH untouched windows. An artifact shows up as
"IS strong, PRE and/or POST dead".

Caveat, stated up front: the HMM regime model trains on the first 30% of the series,
which overlaps PRE. So for the V41/V45 sleeves the PRE window's *exit* parameters are
partly in-sample (entries are not). We therefore also run a regime-free arm
(--regime-free) where every sleeve uses the static EXIT_4H, making PRE fully clean.
POST is clean in both arms and is the primary verdict.

Outputs (this dir):
  r1_trades.csv        every simulated trade, tagged with its window
  r1_by_window.csv     per-sleeve x per-window metrics
  r1_pooled.csv        portfolio-pooled metrics per window
  prints a readable summary
"""
from __future__ import annotations
import sys, argparse, importlib.util
from pathlib import Path
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
from strategy_lab.strategies.v50_new_signals import (
    sig_mfi_extreme, sig_signed_vol_div, sig_volume_profile_rot,
)
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.eval.perps_simulator_adaptive_exit import REGIME_EXITS_4H
from strategy_lab.regime.hmm_adaptive import fit_regime_model


def _load_mod(rel, name):
    spec = importlib.util.spec_from_file_location(name, str(REPO / rel))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

_v30 = _load_mod("strategy_lab/run_v30_creative.py", "v30c")
_v29 = _load_mod("strategy_lab/run_v29_regime.py", "v29r")

EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)

# Exact registry copied from shadow_v52 runner (spec-true).
SLEEVES = [
    ("STF_BTC",    "BTC",  _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "V45",      "FUND_Z"),
    ("CCI_ETH",    "ETH",  _v30.sig_cci_extreme,      dict(cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14), "V41",      "FUND_Z"),
    ("STF_SOL",    "SOL",  _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "baseline", "FUND_Z"),
    ("STF_AVAX",   "AVAX", _v30.sig_supertrend_flip,  dict(st_n=10, st_mult=3.0, ema_reg=200),                       "V45",      "FUND_Z"),
    ("LATBB_AVAX", "AVAX", _v29.sig_lateral_bb_fade,  dict(bb_n=20, bb_k=2.0, adx_max=18, adx_n=14),                 "baseline", "FUND_Z"),
    ("MFI_SOL",    "SOL",  sig_mfi_extreme,           dict(lower=25, upper=75),                                      "V41",      "ATR_NOTOPVOL"),
    ("VP_LINK",    "LINK", sig_volume_profile_rot,    dict(win=60, n_bins=15),                                       "baseline", "ATR_NOTOPVOL"),
    ("SVD_AVAX",   "AVAX", sig_signed_vol_div,        dict(lookback=20, cvd_win=50),                                 "baseline", "ATR_NOTOPVOL"),
    ("MFI_ETH",    "ETH",  sig_mfi_extreme,           dict(lower=25, upper=75),                                      "baseline", "ATR_NOTOPVOL"),
]

WINDOWS = [
    ("PRE",  "2023-04-01", "2024-01-12"),
    ("IS",   "2024-01-12", "2026-04-25"),
    ("POST", "2026-04-25", "2099-01-01"),
]
# The live paper shadow started 2026-06-11 -> a pre-registered sub-slice of POST.
SHADOW_START = "2026-06-11"


# --------------------------------------------------------------- gates (spec-true)
def gate_fund_z(coin, df, z_thr=2.0):
    fund_4h = funding_per_4h_bar(coin, df.index)
    mu = fund_4h.rolling(500, min_periods=100).mean()
    sd = fund_4h.rolling(500, min_periods=100).std()
    z = (fund_4h - mu) / sd.replace(0, np.nan)
    return (z.abs() < z_thr).fillna(True)


def gate_atr_notopvol(df, atr_n=14, high_q=0.80):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([(h - l), (h - c.shift(1)).abs(), (l - c.shift(1)).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_n).mean()
    pct = atr.rolling(500, min_periods=100).rank(pct=True)
    return (pct < high_q).fillna(True)


def build_signal(sleeve, df):
    name, coin, sig_fn, params, variant, gate = sleeve
    out = sig_fn(df, **params)
    le, se = out if isinstance(out, tuple) else (out, None)
    le = le.reindex(df.index).fillna(False)
    se = se.reindex(df.index).fillna(False) if se is not None else pd.Series(False, index=df.index)
    if variant == "V45":
        vmean = df["volume"].rolling(20, min_periods=10).mean()
        active = df["volume"] > 1.1 * vmean
        le, se = le & active, se & active
    if gate == "FUND_Z":
        m = gate_fund_z(coin, df)
    elif gate == "ATR_NOTOPVOL":
        m = gate_atr_notopvol(df)
    else:
        m = pd.Series(True, index=df.index)
    return (le & m).fillna(False), (se & m).fillna(False)


# --------------------------------------------------------------- metrics
def tag_window(ts: pd.Timestamp) -> str:
    for name, a, b in WINDOWS:
        if pd.Timestamp(a, tz="UTC") <= ts < pd.Timestamp(b, tz="UTC"):
            return name
    return "?"


def metrics(sub: pd.DataFrame) -> dict:
    """ret_pct is per-trade % return on deployed cash (simulator 'ret')."""
    if len(sub) == 0:
        return dict(n=0, mean_ret=np.nan, wr=np.nan, tot=0.0, t=np.nan,
                    ex_top2=0.0, med=np.nan)
    r = sub["ret_pct"].to_numpy(float)
    p = sub["realized"].to_numpy(float)
    o = np.sort(p)[::-1]
    t = (r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    return dict(n=len(sub), mean_ret=r.mean(), wr=100.0 * (r > 0).mean(),
                tot=p.sum(), t=t, ex_top2=p.sum() - o[:2].sum(), med=float(np.median(r)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regime-free", action="store_true",
                    help="force static EXIT_4H on every sleeve (makes PRE fully clean)")
    args = ap.parse_args()
    arm = "regime_free" if args.regime_free else "spec_true"

    # cache per-coin data once
    data: dict[str, tuple[pd.DataFrame, pd.Series]] = {}
    for coin in sorted({s[1] for s in SLEEVES}):
        df = load_hl(coin, "4h")
        data[coin] = (df, funding_per_4h_bar(coin, df.index))
    print(f"[r1] arm={arm}  coins={list(data)}  "
          f"bars={len(data['BTC'][0])}  {data['BTC'][0].index.min().date()} -> {data['BTC'][0].index.max().date()}")

    rows = []
    for sleeve in SLEEVES:
        name, coin, _, _, variant, gate = sleeve
        df, fund = data[coin]
        le, se = build_signal(sleeve, df)
        if variant in ("V41", "V45") and not args.regime_free:
            _, rdf = fit_regime_model(df, train_frac=0.30, seed=42)
            trades, _ = simulate_with_funding(df, le, se, fund,
                                              regime_labels=rdf["label"],
                                              regime_exits=REGIME_EXITS_4H)
        else:
            trades, _ = simulate_with_funding(df, le, se, fund, **EXIT_4H)
        for t in trades:
            ets = df.index[t["entry_idx"]]
            rows.append(dict(sleeve=name, coin=coin, variant=variant, gate=gate,
                             entry_ts=ets, exit_ts=df.index[t["exit_idx"]],
                             window=tag_window(ets),
                             side="LONG" if t["side"] > 0 else "SHORT",
                             ret_pct=100.0 * t["ret"], realized=t["realized"],
                             reason=t["reason"], bars=t["bars"],
                             funding_cost=t["funding_cost"], regime=t.get("regime")))
        print(f"  {name:11s} {coin:5s} {variant:8s} {gate:13s} fires={int(le.sum()+se.sum()):4d} trades={len(trades):4d}")

    tr = pd.DataFrame(rows)
    tr.to_csv(HERE / f"r1_trades_{arm}.csv", index=False)

    # ---------------- per-sleeve x window
    out = []
    for name in [s[0] for s in SLEEVES]:
        for w, _, _ in WINDOWS:
            m = metrics(tr[(tr.sleeve == name) & (tr.window == w)])
            out.append(dict(sleeve=name, window=w, **m))
    bw = pd.DataFrame(out)
    bw.to_csv(HERE / f"r1_by_window_{arm}.csv", index=False)

    # ---------------- pooled
    pool = []
    for w, _, _ in WINDOWS:
        pool.append(dict(window=w, **metrics(tr[tr.window == w])))
    pool.append(dict(window="SHADOW(>=06-11)",
                     **metrics(tr[tr.entry_ts >= pd.Timestamp(SHADOW_START, tz="UTC")])))
    pl = pd.DataFrame(pool)
    pl.to_csv(HERE / f"r1_pooled_{arm}.csv", index=False)

    # ---------------- report
    def fmt(d):
        return (f"n={d['n']:4d} mean={d['mean_ret']:+7.3f}% med={d['med']:+7.3f}% "
                f"WR={d['wr']:5.1f}% t={d['t']:+5.2f} tot=${d['tot']:+9.2f} "
                f"ex-top2=${d['ex_top2']:+9.2f}")

    print(f"\n{'='*104}\nPOOLED PORTFOLIO ({arm})\n{'='*104}")
    for _, r in pl.iterrows():
        print(f"  {r['window']:16s} {fmt(r)}")

    print(f"\n{'='*104}\nPER SLEEVE  (PRE / POST are the untouched windows; IS was the selection window)\n{'='*104}")
    piv = bw.pivot(index="sleeve", columns="window", values=["n", "mean_ret", "tot"])
    print(f"{'sleeve':12s} | {'PRE n':>6s} {'PRE mean':>9s} {'PRE $':>9s} | "
          f"{'IS n':>6s} {'IS mean':>9s} {'IS $':>9s} | {'POST n':>6s} {'POST mean':>9s} {'POST $':>9s} | verdict")
    print("-" * 118)
    verdicts = {}
    for name in [s[0] for s in SLEEVES]:
        g = {w: bw[(bw.sleeve == name) & (bw.window == w)].iloc[0] for w, _, _ in WINDOWS}
        pre, is_, post = g["PRE"], g["IS"], g["POST"]
        n_ok = sum(1 for x in (pre, post) if x["n"] > 0 and x["mean_ret"] > 0)
        if pre["n"] == 0 or post["n"] == 0:
            v = "THIN"
        elif n_ok == 2:
            v = "HOLDS both OOS"
        elif n_ok == 1:
            v = "MIXED"
        else:
            v = "FAILS both OOS"
        verdicts[name] = v
        print(f"{name:12s} | {pre['n']:6.0f} {pre['mean_ret']:+9.3f} {pre['tot']:+9.1f} | "
              f"{is_['n']:6.0f} {is_['mean_ret']:+9.3f} {is_['tot']:+9.1f} | "
              f"{post['n']:6.0f} {post['mean_ret']:+9.3f} {post['tot']:+9.1f} | {v}")

    print(f"\nverdict tally: " + ", ".join(f"{v}={sum(1 for x in verdicts.values() if x==v)}"
                                          for v in sorted(set(verdicts.values()))))
    print(f"\n[r1] wrote r1_trades_{arm}.csv, r1_by_window_{arm}.csv, r1_pooled_{arm}.csv")

    # exit-reason mix per window (diagnoses the 70/92-SL problem)
    print(f"\n{'='*104}\nEXIT REASON MIX BY WINDOW\n{'='*104}")
    for w, _, _ in WINDOWS:
        s = tr[tr.window == w]
        if not len(s):
            continue
        g = s.groupby("reason").agg(n=("ret_pct", "size"), mean=("ret_pct", "mean"),
                                    tot=("realized", "sum"))
        parts = " | ".join(f"{k}: n={int(v['n'])} mean={v['mean']:+.2f}% ${v['tot']:+.0f}"
                           for k, v in g.iterrows())
        print(f"  {w:5s} {parts}")


if __name__ == "__main__":
    main()
