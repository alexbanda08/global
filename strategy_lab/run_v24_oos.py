"""
V24 OOS — walk-forward for each V24 family's per-coin winner.
Split: IS 2020-2023, OOS 2024-2026.
"""
from __future__ import annotations
import sys, pickle, warnings
warnings.filterwarnings("ignore")
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from strategy_lab.run_v16_1h_hunt import simulate, metrics

from strategy_lab.run_v24_15m_scalp import (
    _load as load_15m, sig_orb, sig_vwap_band, sig_rsi_bb, sig_st_dual, dedupe as d15,
)
from strategy_lab.run_v24_regime_router import (
    _load as load_mtf, regime_label, sig_regime_combined, dedupe as dR, scaled,
)

RES = Path(__file__).resolve().parent / "results" / "v24"
FEE = 0.00045
SPLIT = pd.Timestamp("2024-01-01", tz="UTC")


def run_slice(df, lsig, ssig, exits, risk, lev, lbl):
    tp, sl, tr, mh = exits["tp"], exits["sl"], exits["trail"], exits["mh"]
    ls = dR(lsig); ss = dR(ssig) if ssig is not None else None
    trades, eq = simulate(df, ls, short_entries=ss,
                          tp_atr=tp, sl_atr=sl, trail_atr=tr, max_hold=mh,
                          risk_per_trade=risk, leverage_cap=lev, fee=FEE)
    return metrics(lbl, eq, trades), trades, eq


def verdict(r_is, r_oos):
    if r_oos["n"] < 10: return "insufficient OOS trades"
    if r_oos["sharpe"] <= 0: return "OOS LOSES"
    if r_oos["sharpe"] >= 0.5 * max(0.1, r_is["sharpe"]): return "✓ OOS holds"
    return "✗ OOS degrades"


def _sig_for(sym, d, df):
    fam = d["family"]; p = d["params"]
    if fam == "RSIBB_15m":
        return sig_rsi_bb(df, p["rsi_n"], p["rsi_lo"], p["rsi_hi"],
                           p["bb_n"], p["bb_k"], p["regime_len"])
    if fam == "ORB_15m":
        return sig_orb(df, p["open_bars"], p["vol_mult"])
    if fam.startswith("VWAP_"):
        return sig_vwap_band(df, p["band_n"], p["band_k"], p["mode"])
    if fam == "STDUAL_15m":
        return sig_st_dual(df, p["n_fast"], p["m_fast"], p["n_slow"], p["m_slow"])
    if fam == "Regime_Router":
        # Recompute regime fresh for the slice
        long, short, _ = sig_regime_combined(df, d["tf"], p["donch_n"], p["bb_n"], p["bb_k"])
        return long, short
    raise ValueError(fam)


def audit(results_pkl: Path, loader, label: str):
    if not results_pkl.exists():
        print(f"[skip] {results_pkl.name} not found")
        return []
    with open(results_pkl, "rb") as f:
        data = pickle.load(f)
    rows = []
    print(f"\n{'='*80}\n{label} — Walk-forward OOS (split 2024-01-01)\n{'='*80}")
    for sym, d in data.items():
        tf = d["tf"]
        df = loader(sym, tf)
        if df is None or len(df) < 2000:
            print(f"  {sym}: data missing"); continue
        try:
            lsig, ssig = _sig_for(sym, d, df)
        except Exception as e:
            print(f"  {sym}: signal compute failed — {e}"); continue

        is_mask = df.index < SPLIT
        oos_mask = df.index >= SPLIT
        n_is, n_oos = int(is_mask.sum()), int(oos_mask.sum())

        if n_is >= 100:
            r_is, _, _ = run_slice(df[is_mask], lsig[is_mask], ssig[is_mask],
                                    d["exits"], d["risk"], d["lev"], f"{sym}_IS")
        else:
            r_is = {"n": 0, "cagr_net": 0.0, "sharpe": 0.0, "dd": 0.0}
        if n_oos >= 100:
            r_oos, _, _ = run_slice(df[oos_mask], lsig[oos_mask], ssig[oos_mask],
                                     d["exits"], d["risk"], d["lev"], f"{sym}_OOS")
        else:
            r_oos = {"n": 0, "cagr_net": 0.0, "sharpe": 0.0, "dd": 0.0}

        v = "OOS-only history (no IS)" if n_is < 100 else verdict(r_is, r_oos)
        print(f"  {sym:10s}  {d['family']:18s} @ {tf:3s}  "
              f"IS  n={r_is['n']:4d} C {r_is['cagr_net']*100:+6.1f}% Sh {r_is['sharpe']:+.2f}  "
              f"OOS n={r_oos['n']:3d} C {r_oos['cagr_net']*100:+6.1f}% Sh {r_oos['sharpe']:+.2f}  {v}",
              flush=True)
        rows.append(dict(sym=sym, family=d["family"], tf=tf,
                         is_n=r_is["n"], is_cagr=r_is["cagr_net"], is_sharpe=r_is["sharpe"],
                         oos_n=r_oos["n"], oos_cagr=r_oos["cagr_net"], oos_sharpe=r_oos["sharpe"],
                         verdict=v))
    return rows


def main():
    rows = []
    rows += audit(RES / "v24_15m_results.pkl", load_15m, "V24 15m SCALP")
    rows += audit(RES / "v24_regime_results.pkl", load_mtf, "V24 REGIME ROUTER")
    if rows:
        pd.DataFrame(rows).to_csv(RES / "v24_oos_summary.csv", index=False)
        print(f"\nSaved OOS summary: {RES/'v24_oos_summary.csv'}")


if __name__ == "__main__":
    sys.exit(main() or 0)
