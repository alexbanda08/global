"""
V23 OOS — walk-forward for every per-coin winner from v23_results.pkl.

Split: IS 2019-2023, OOS 2024-2026. Uses each coin's locked config.
Saves an augmented pickle with per-coin IS + OOS metrics and equity.
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import (
    simulate, metrics, sig_rangekalman, sig_rangekalman_short,
    sig_bbbreak, bb, atr, ema,
)
import talib

FEAT = Path(__file__).resolve().parent / "features" / "multi_tf"
RES = Path(__file__).resolve().parent / "results" / "v23"
FEE = 0.00045
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")


def _load(sym, tf):
    return pd.read_parquet(FEAT / f"{sym}_{tf}.parquet").dropna(
        subset=["open","high","low","close","volume"])


def dedupe(s): return s & ~s.shift(1).fillna(False)


def sig_bbbreak_short(df, n=120, k=2.0, regime_len=600):
    _, _, lb = bb(df["close"], n, k)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lb) & (df["close"].shift(1) >= lb.shift(1)) & pd.Series(regime_bear, index=df.index)
    return sig.fillna(False).astype(bool)


def sig_keltner_adx(df, k_n=20, k_mult=1.5, adx_min=18, regime_len=600):
    mid = ema(df["close"], k_n); at = atr(df, k_n)
    up = mid + k_mult * at
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime = df["close"].values > df["close"].rolling(regime_len).mean().values
    sig = (df["close"] > up) & (df["close"].shift(1) <= up.shift(1)) & (ax > adx_min) & regime
    return sig.fillna(False).astype(bool)


def sig_keltner_adx_short(df, k_n=20, k_mult=1.5, adx_min=18, regime_len=600):
    mid = ema(df["close"], k_n); at = atr(df, k_n)
    lo = mid - k_mult * at
    ax = talib.ADX(df["high"].values, df["low"].values, df["close"].values, 14)
    regime_bear = df["close"].values < df["close"].rolling(regime_len).mean().values
    sig = (df["close"] < lo) & (df["close"].shift(1) >= lo.shift(1)) & (ax > adx_min) & regime_bear
    return sig.fillna(False).astype(bool)


FAMILY_FN = {
    "RangeKalman_LS": (sig_rangekalman, sig_rangekalman_short),
    "BBBreak_LS":     (sig_bbbreak,     sig_bbbreak_short),
    "KeltnerADX_LS":  (sig_keltner_adx, sig_keltner_adx_short),
}


def run_slice(df, lsig, ssig, exits, risk, lev, lbl):
    tp, sl, tr, mh = exits["tp"], exits["sl"], exits["trail"], exits["mh"]
    ls = dedupe(lsig); ss = dedupe(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def verdict(r_is, r_oos):
    if r_oos["n"] < 10:
        return "insufficient OOS trades"
    if r_oos["sharpe"] <= 0:
        return "OOS LOSES"
    if r_oos["sharpe"] >= 0.5 * r_is["sharpe"]:
        return "✓ OOS holds"
    return "✗ OOS degrades"


def main():
    with open(RES / "v23_results.pkl", "rb") as f:
        data = pickle.load(f)

    augmented = {}
    summary_rows = []
    for sym, d in data.items():
        tf = d["tf"]; family = d["family"]; params = d["params"]
        df = _load(sym, tf)
        lfn, sfn = FAMILY_FN[family]

        # Signals computed on the FULL df (no leakage — features use past only)
        try:
            lsig = lfn(df, **{k: v for k, v in params.items() if k in lfn.__code__.co_varnames})
            ssig = sfn(df, **{k: v for k, v in params.items() if k in sfn.__code__.co_varnames})
        except Exception as e:
            print(f"  {sym}: signal compute failed - {e}")
            continue

        is_mask  = df.index < SPLIT
        oos_mask = df.index >= SPLIT
        n_is, n_oos = int(is_mask.sum()), int(oos_mask.sum())

        r_full, _, _ = run_slice(df, lsig, ssig, d["exits"], d["risk"], d["lev"], f"{sym}_FULL")

        if n_is >= 100:
            df_is, lsig_is, ssig_is = df[is_mask], lsig[is_mask], ssig[is_mask]
            r_is, _, eq_is = run_slice(df_is, lsig_is, ssig_is, d["exits"], d["risk"], d["lev"], f"{sym}_IS")
        else:
            r_is = {"n": 0, "cagr_net": 0.0, "sharpe": 0.0, "dd": 0.0}
            eq_is = pd.Series([10000.0], index=[df.index[0]] if len(df) else [])

        if n_oos >= 100:
            df_oos, lsig_oos, ssig_oos = df[oos_mask], lsig[oos_mask], ssig[oos_mask]
            r_oos, _, eq_oos = run_slice(df_oos, lsig_oos, ssig_oos, d["exits"], d["risk"], d["lev"], f"{sym}_OOS")
        else:
            r_oos = {"n": 0, "cagr_net": 0.0, "sharpe": 0.0, "dd": 0.0}
            eq_oos = pd.Series([10000.0], index=[df.index[-1]] if len(df) else [])

        if n_is < 100:
            v = "OOS-only history (no IS)"
        else:
            v = verdict(r_is, r_oos)
        print(f"{sym:10s}  {family:15s} @ {tf:3s}  "
              f"IS  n={r_is['n']:4d} CAGR {r_is['cagr_net']*100:+6.1f}% Sh {r_is['sharpe']:+.2f}  "
              f"OOS n={r_oos['n']:3d} CAGR {r_oos['cagr_net']*100:+6.1f}% Sh {r_oos['sharpe']:+.2f}  {v}",
              flush=True)

        augmented[sym] = {**d, "is": r_is, "oos": r_oos, "verdict": v,
                          "eq_is_idx": list(eq_is.index.astype("int64").tolist()),
                          "eq_is_val": eq_is.values.tolist(),
                          "eq_oos_idx": list(eq_oos.index.astype("int64").tolist()),
                          "eq_oos_val": eq_oos.values.tolist()}
        summary_rows.append(dict(
            sym=sym, family=family, tf=tf,
            is_n=r_is["n"], is_cagr=r_is["cagr_net"], is_sharpe=r_is["sharpe"], is_dd=r_is["dd"],
            oos_n=r_oos["n"], oos_cagr=r_oos["cagr_net"], oos_sharpe=r_oos["sharpe"], oos_dd=r_oos["dd"],
            verdict=v,
        ))

    with open(RES / "v23_results_with_oos.pkl", "wb") as f:
        pickle.dump(augmented, f)
    pd.DataFrame(summary_rows).to_csv(RES / "v23_oos_summary.csv", index=False)

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(pd.DataFrame(summary_rows).to_string(index=False))


if __name__ == "__main__":
    sys.exit(main() or 0)
