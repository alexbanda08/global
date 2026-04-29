"""
V22 OOS audit — walk-forward on BTC and SOL winners.

Split: train 2019-01-01 to 2023-12-31, test 2024-01-01 onwards.
Runs each winner on IS and OOS separately. A strategy whose OOS
Sharpe within 50% of IS Sharpe (and still positive) is considered
non-overfit.
"""
from __future__ import annotations
import sys, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
)

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
FEE = 0.00045


def dedupe(s): return s & ~s.shift(1).fillna(False)


def run(df, lsig, ssig, tp, sl, tr, mh, risk, lev, lbl):
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    r = metrics(lbl, eq, trades)
    return r


def audit(sym, tf, base, tp, sl, tr, mh, risk, lev, label):
    p = FEAT / f"{sym}_{tf}.parquet"
    df = pd.read_parquet(p).dropna(subset=["open", "high", "low", "close", "volume"])
    # Compute signals on full df (features use past data only — no leakage)
    lsig = sig_rangekalman(df, **base)
    ssig = sig_rangekalman_short(df, **base)

    split = pd.Timestamp("2024-01-01", tz="UTC")
    is_mask = df.index < split
    oos_mask = df.index >= split

    df_is  = df[is_mask];   lsig_is  = lsig[is_mask];   ssig_is  = ssig[is_mask]
    df_oos = df[oos_mask];  lsig_oos = lsig[oos_mask];  ssig_oos = ssig[oos_mask]

    r_full = run(df,     lsig,     ssig,     tp, sl, tr, mh, risk, lev, f"{label}_FULL")
    r_is   = run(df_is,  lsig_is,  ssig_is,  tp, sl, tr, mh, risk, lev, f"{label}_IS")
    r_oos  = run(df_oos, lsig_oos, ssig_oos, tp, sl, tr, mh, risk, lev, f"{label}_OOS")

    print(f"\n=== {label} ({sym} {tf}) ===")
    for r, tag in [(r_full, "FULL"), (r_is, " IS "), (r_oos, "OOS ")]:
        print(f"  {tag}  n={r['n']:4d}  CAGR {r['cagr_net']*100:6.1f}%  "
              f"Sh {r['sharpe']:+.2f}  DD {r['dd']*100:+6.1f}%  "
              f"Win {r['win']*100:4.1f}%  PF {r['pf']:.2f}")
    # Verdict
    if r_oos["sharpe"] > 0 and r_oos["sharpe"] >= 0.5 * r_is["sharpe"]:
        print(f"  ✓ OOS holds (Sh_oos {r_oos['sharpe']:.2f} vs Sh_is {r_is['sharpe']:.2f})")
    else:
        print(f"  ✗ OOS degrades (Sh_oos {r_oos['sharpe']:.2f} vs Sh_is {r_is['sharpe']:.2f})")
    return r_full, r_is, r_oos


def main():
    # BTC winner
    audit(
        "BTCUSDT", "2h",
        dict(alpha=0.07, rng_len=300, rng_mult=3.0, regime_len=800),
        tp=10, sl=2.0, tr=6.0, mh=60, risk=0.05, lev=3.0,
        label="BTC_V22_RK",
    )
    # SOL winner
    audit(
        "SOLUSDT", "2h",
        dict(alpha=0.09, rng_len=200, rng_mult=2.5, regime_len=400),
        tp=10, sl=2.0, tr=6.0, mh=60, risk=0.05, lev=3.0,
        label="SOL_V22_RK",
    )
    # SOL smoother alt
    audit(
        "SOLUSDT", "2h",
        dict(alpha=0.07, rng_len=250, rng_mult=3.0, regime_len=400),
        tp=10, sl=2.0, tr=6.0, mh=60, risk=0.05, lev=3.0,
        label="SOL_V22_RK_SMOOTH",
    )
    # BTC alternative safer
    audit(
        "BTCUSDT", "2h",
        dict(alpha=0.07, rng_len=250, rng_mult=3.0, regime_len=800),
        tp=10, sl=2.0, tr=6.0, mh=60, risk=0.05, lev=3.0,
        label="BTC_V22_RK_ALT",
    )


if __name__ == "__main__":
    sys.exit(main() or 0)
