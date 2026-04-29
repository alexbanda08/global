"""
V63: Portfolio-level leverage sweep on V52.

Hypothesis: V52 already has Sharpe 2.52 and MDD -5.8%. Multiplying per-bar
returns by leverage L scales BOTH price-PnL AND funding cost by L (since
position = L * equity), so it's a mathematically clean leverage operation.

Target: highest leverage where MDD stays <= -20% AND Sharpe stays >= 2.0
(modest Sharpe degradation acceptable due to vol-drag at high L).

Sweep: L in [1.0, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00, 3.50]

Note on practical limits: Hyperliquid allows up to 50x on BTC/ETH but funding
amplifies linearly with size. V52 internal leverage_cap is 4.0 per sleeve;
portfolio leverage of 2x means each sleeve sees ~8x effective leverage on
its capital, well above HL caps for some alts. This script is a SCREEN —
the winning L still needs to be re-validated in a simulator-level rebuild
with proper sleeve-cap respect.

Output:
  - leverage_sweep table (Sharpe, CAGR, MDD, Calmar, Sh_lci, Cal_lci per L)
  - hits_target row(s): CAGR >= 50% AND MDD >= -20%
"""
from __future__ import annotations
import json, sys, time, warnings
from pathlib import Path
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.run_v52_hl_gates import build_v52_hl
from strategy_lab.run_leverage_audit import verdict_8gate

OUT = REPO / "docs/research/phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6


def headline(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    if sd == 0:
        return {"sharpe": 0, "cagr_pct": 0, "mdd_pct": 0, "calmar": 0}
    sh = (float(r.mean()) / sd) * np.sqrt(BPY)
    pk = eq.cummax(); mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = cagr / abs(mdd) if mdd != 0 else 0
    return {"sharpe": round(sh, 3), "cagr_pct": round(float(cagr) * 100, 2),
            "mdd_pct": round(mdd * 100, 2), "calmar": round(float(cal), 3)}


def lever(v52_eq: pd.Series, L: float) -> pd.Series:
    r = v52_eq.pct_change().fillna(0) * L
    # Cap any single-bar loss at -99% so we don't go negative on extreme L
    r = r.clip(lower=-0.99)
    return (1 + r).cumprod() * 10_000.0


def main():
    t0 = time.time()
    print("=" * 72)
    print("V63: Portfolio-level leverage sweep on V52")
    print("=" * 72)

    print("\n[1] Building V52 baseline (1x)...")
    v52 = build_v52_hl()
    h_base = headline(v52)
    print(f"   V52 (1x): {h_base}")

    LEVERS = [1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00, 3.50]
    rows = []
    print(f"\n[2] Leverage sweep (L = {LEVERS})...")
    for L in LEVERS:
        eq_L = lever(v52, L)
        h = headline(eq_L)
        gates = verdict_8gate(eq_L)
        sh_lci = float(gates["gates"]["bootstrap_sharpe_lowerCI_gt_0.5"]["value"])
        cal_lci = float(gates["gates"]["bootstrap_calmar_lowerCI_gt_1.0"]["value"])
        mdd_wci = float(gates["gates"]["bootstrap_mdd_worstCI_gt_neg30pct"]["value"])
        wf_eff = float(gates["gates"]["walk_forward_efficiency_gt_0.5"]["value"])
        passed = sum(1 for g in gates["gates"].values() if g["pass"] is True)
        row = {"L": L, **h,
               "sharpe_lowerCI": round(sh_lci, 3),
               "calmar_lowerCI": round(cal_lci, 3),
               "mdd_worstCI": round(mdd_wci, 3),
               "wf_efficiency": round(wf_eff, 3),
               "gates_passed_1_6": passed}
        rows.append(row)
        hit = "TARGET" if (h["cagr_pct"] >= 50 and h["mdd_pct"] >= -20) else ""
        print(f"   L={L:>4.2f}  Sh={h['sharpe']:>5.2f}  CAGR={h['cagr_pct']:>6.2f}%  "
              f"MDD={h['mdd_pct']:>+7.2f}%  Cal={h['calmar']:>5.2f}  "
              f"Sh_lci={sh_lci:>+5.2f}  Cal_lci={cal_lci:>+5.2f}  g/6={passed}  {hit}")

    # Find target hits
    target = [r for r in rows if r["cagr_pct"] >= 50 and r["mdd_pct"] >= -20]
    print(f"\n[3] Target hits (CAGR>=50% AND MDD>=-20%): {len(target)}")
    if target:
        # Pick the lowest L that hits target (most conservative)
        winner = min(target, key=lambda r: r["L"])
        print(f"\n*** WINNER: L={winner['L']} ***")
        print(f"    Sharpe = {winner['sharpe']:.3f}")
        print(f"    CAGR   = {winner['cagr_pct']:+.2f}%")
        print(f"    MDD    = {winner['mdd_pct']:+.2f}%")
        print(f"    Calmar = {winner['calmar']:.2f}")
        print(f"    Bootstrap Sharpe lower-CI = {winner['sharpe_lowerCI']:+.3f}")
        print(f"    Bootstrap Calmar lower-CI = {winner['calmar_lowerCI']:+.3f}")
        print(f"    Bootstrap MDD worst-CI    = {winner['mdd_worstCI']:+.3f}")
        print(f"    Walk-forward efficiency   = {winner['wf_efficiency']:.3f}")
        print(f"    Gates 1-6 passed          = {winner['gates_passed_1_6']}/6")

    out = OUT / "v63_leverage_sweep.json"
    out.write_text(json.dumps({"v52_baseline": h_base, "rows": rows,
                                "target_hits": target}, indent=2, default=str))
    print(f"\nWrote: {out}")
    print(f"Total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
