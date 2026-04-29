"""
V54: Pure price-action signal scan.

Tests sig_pivot_break / sig_pivot_break_retest / sig_inside_bar_break across
ETH, SOL, AVAX, LINK, BTC on 4h with canonical EXIT_4H. Reports per-coin Sharpe,
trade count, WR, and correlation vs V52 reference equity (if available).

Run:  python -m strategy_lab.run_v54_priceaction
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from strategy_lab.util.hl_data import load_hl
from strategy_lab.eval.perps_simulator import simulate as sim_canonical, compute_metrics
from strategy_lab.strategies.v54_priceaction import (
    sig_pivot_break, sig_pivot_break_retest, sig_inside_bar_break,
)

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)


COINS = ["BTC", "ETH", "SOL", "AVAX", "LINK"]
EXIT_4H = dict(tp_atr=10.0, sl_atr=2.0, trail_atr=6.0, max_hold=60)


def run_one(df, long_sig, short_sig, label):
    trades, eq = sim_canonical(
        df, long_sig, short_sig,
        risk_per_trade=0.03, leverage_cap=4.0, **EXIT_4H,
    )
    m = compute_metrics(label, eq, trades, bars_per_year=6 * 365)
    return m, eq, trades


def correlation(eq_a: pd.Series, eq_b: pd.Series) -> float:
    a = eq_a.pct_change().dropna()
    b = eq_b.pct_change().dropna()
    j = a.index.intersection(b.index)
    if len(j) < 50:
        return float("nan")
    return float(a.loc[j].corr(b.loc[j]))


def maybe_load_v52_eq():
    """Build a V52-PROXY equity = CCI_ETH on canonical EXIT_4H.
    CCI_ETH is V52's biggest sleeve (~60% of base). Corr vs proxy is a tight
    upper bound on corr vs full V52, so |rho_proxy| <= 0.30 -> safely diversifying.
    """
    try:
        from strategy_lab.run_v30_creative import sig_cci_extreme
        df = load_hl("ETH", "4h")
        cl, _ = sig_cci_extreme(df)
        _, eq = sim_canonical(
            df, cl, pd.Series(False, index=df.index),
            risk_per_trade=0.03, leverage_cap=4.0, **EXIT_4H,
        )
        return eq
    except Exception as e:
        print(f"[V52 proxy] could not build: {e}")
        return None


def main():
    print("=" * 70)
    print("V54: Pure Price-Action Signal Scan")
    print("=" * 70)

    v52_eq = maybe_load_v52_eq()
    if v52_eq is not None:
        print(f"\n[V52 ref] loaded: {len(v52_eq)} bars  {v52_eq.index[0]} -> {v52_eq.index[-1]}")
    else:
        print("\n[V52 ref] not found; correlation vs V52 will be skipped.")

    SIGNALS = [
        ("pivot_break",        lambda df: sig_pivot_break(df)),
        ("pivot_break_retest", lambda df: sig_pivot_break_retest(df)),
        ("inside_bar_break",   lambda df: sig_inside_bar_break(df)),
    ]

    rows = []
    eq_store: dict[str, pd.Series] = {}

    for sym in COINS:
        df = load_hl(sym, "4h")
        print(f"\n>>> {sym} 4h  ({len(df)} bars)")
        for sname, sfn in SIGNALS:
            ls, ss = sfn(df)
            for side_name, l, s in [("long", ls, pd.Series(False, index=df.index)),
                                     ("short", pd.Series(False, index=df.index), ss),
                                     ("both", ls, ss)]:
                lbl = f"{sname}_{side_name}_{sym}"
                m, eq, trades = run_one(df, l, s, lbl)
                if m["n_trades"] < 5:
                    continue
                eq_store[lbl] = eq
                rho = correlation(eq, v52_eq) if v52_eq is not None else float("nan")
                row = {
                    "label":   lbl,
                    "n":       int(m["n_trades"]),
                    "wr":      round(float(m["winrate"]), 3) if "winrate" in m else None,
                    "sharpe":  round(float(m["sharpe"]), 3),
                    "cagr":    round(float(m["cagr"]) * 100, 2),
                    "mdd":     round(float(m.get("max_dd", 0)) * 100, 2),
                    "calmar":  round(float(m.get("calmar", 0)), 3),
                    "rho_v52": round(rho, 3) if not np.isnan(rho) else None,
                }
                rows.append(row)
                print(f"   {lbl:<32}  n={row['n']:>3}  Sh={row['sharpe']:>5.2f}  "
                      f"CAGR={row['cagr']:>6.2f}%  MDD={row['mdd']:>6.2f}%  "
                      f"WR={row['wr']}  rho_v52={row['rho_v52']}")

    # rank by Sharpe
    rows.sort(key=lambda r: r["sharpe"], reverse=True)
    print("\n" + "=" * 70)
    print("TOP 10 BY SHARPE")
    print("=" * 70)
    for r in rows[:10]:
        print(f"  {r['label']:<34}  Sh={r['sharpe']:>5.2f}  CAGR={r['cagr']:>6.2f}%  "
              f"MDD={r['mdd']:>6.2f}%  rho_v52={r['rho_v52']}")

    # Promotion-grade filter (against V52 spec):
    promo = [r for r in rows
             if r["sharpe"] >= 0.8
             and (r["rho_v52"] is None or abs(r["rho_v52"]) <= 0.30)
             and r["n"] >= 30]
    print(f"\nPROMO CANDIDATES (Sh>=0.8, |rho_v52|<=0.20, n>=30): {len(promo)}")
    for r in promo:
        print(f"  {r['label']:<34}  Sh={r['sharpe']:>5.2f}  rho_v52={r['rho_v52']}  n={r['n']}")

    summary = {
        "all_results": rows,
        "promo_candidates": promo,
        "n_total": len(rows),
        "n_promo": len(promo),
        "v52_ref_loaded": v52_eq is not None,
    }
    out_path = OUT / "v54_priceaction_scan.json"
    out_path.write_text(json.dumps(summary, indent=2, default=str))
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
