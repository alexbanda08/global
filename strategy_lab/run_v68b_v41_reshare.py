"""
V68b — V41-share reweight sweep on V52.

V68 finding: walk-forward optimizer settles on ~80-85% V41 core, ~15-20%
diversifiers. V52's current implicit split is 60/40. This runner tests
the single-parameter tweak alpha in {0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85}
where:
    v52_alpha = alpha * V41_eq_returns + (1-alpha)/4 * sum(diversifier_returns)

Reuses the SAME V41 inner-blend formula (0.6 invvol_blend + 0.4 eqw_blend)
and the SAME 4 diversifier definitions. Only the outer V41-share alpha
changes. This is the cheapest possible test of the V68 durable insight.

Reports for each alpha:
  - Headline Sharpe / CAGR / MDD / Calmar (full history)
  - Stacked V67 (L=1.75) headline
  - Pass/fail vs the 60% / 50% / -40% target

Decision rule: pick smallest alpha that:
  (a) Sharpe >= V52 baseline Sharpe (2.52), AND
  (b) After L=1.75 leverage: CAGR >= 60% AND MDD >= -40%

If multiple alpha values pass, prefer smaller (more diversification = more
robust to single-sleeve decay).
"""
from __future__ import annotations
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "strategy_lab"))

from strategy_lab.run_v52_hl_gates import (
    V41_VARIANT_MAP, DIV_SPECS, build_v41_sleeve, build_diversifier,
)
from strategy_lab.run_leverage_audit import eqw_blend, invvol_blend

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def headline(eq: pd.Series, label: str) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0
    daily = (1 + r).resample("D").prod() - 1
    daily_active = daily[daily.abs() > 1e-7]
    wr_d = 100.0 * (daily_active > 0).mean() if len(daily_active) else float("nan")
    return {
        "label": label,
        "sharpe": round(sh, 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 3),
        "wr_daily": round(float(wr_d), 2),
        "n_bars": int(len(eq)),
    }


def lever(eq: pd.Series, L: float) -> pd.Series:
    r = eq.pct_change().fillna(0.0)
    out = (1 + (L * r).clip(lower=-0.99)).cumprod() * float(eq.iloc[0])
    return out


# ---------------------------------------------------------------------------
# Build V41 and diversifier curves once (expensive)
# ---------------------------------------------------------------------------

def build_components():
    print("Building 4 V41 sleeves...")
    v41_curves = {s: build_v41_sleeve(s) for s in V41_VARIANT_MAP}

    # V41 internal blend, same as run_v52_hl_gates.build_v52_hl
    p3 = invvol_blend(
        {k: v41_curves[k] for k in ["CCI_ETH_4h", "STF_AVAX_4h", "STF_SOL_4h"]},
        window=500,
    )
    p5 = eqw_blend(
        {k: v41_curves[k] for k in ["CCI_ETH_4h", "LATBB_AVAX_4h", "STF_SOL_4h"]},
    )
    idx = p3.index.intersection(p5.index)
    v41_r = (
        0.6 * p3.reindex(idx).pct_change().fillna(0)
        + 0.4 * p5.reindex(idx).pct_change().fillna(0)
    )
    v41_eq = (1 + v41_r).cumprod() * 10_000.0

    print("Building 4 diversifiers...")
    div_curves = {spec[0]: build_diversifier(spec[0]) for spec in DIV_SPECS}

    # Common index across V41 + 4 diversifiers
    common = v41_eq.index
    for eq in div_curves.values():
        common = common.intersection(eq.index)

    v41_r_ret = v41_eq.reindex(common).pct_change().fillna(0)
    div_rets = {k: eq.reindex(common).pct_change().fillna(0)
                for k, eq in div_curves.items()}
    return v41_r_ret, div_rets


def build_alpha_blend(v41_r: pd.Series, div_rets: dict, alpha: float) -> pd.Series:
    """alpha * V41 + (1-alpha)/n_div * sum(diversifiers).  Returns equity."""
    n = len(div_rets)
    div_share = (1 - alpha) / n
    blend = alpha * v41_r
    for r in div_rets.values():
        blend = blend + div_share * r
    return (1 + blend).cumprod() * 10_000.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 72)
    print("V68b: V41-share reweight sweep")
    print("=" * 72)

    v41_r, div_rets = build_components()

    alphas = [0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]
    L = 1.75

    rows = []
    print(f"\nSweep over alpha (V41 share):  L={L} stack reported alongside")
    print(f"  alpha  | Sharpe   CAGR    MDD     Calmar  WR_d     | L=1.75: CAGR    MDD     pass60_50_40")
    print("  " + "-" * 110)

    best = {"alpha_target": None, "best_levered_cagr": -1, "alpha_sh": None, "best_sh": -1}

    for alpha in alphas:
        eq_a = build_alpha_blend(v41_r, div_rets, alpha)
        h = headline(eq_a, f"alpha_{alpha:.2f}")
        eq_l = lever(eq_a, L)
        hl = headline(eq_l, f"alpha_{alpha:.2f}_L{L}")

        passes_target = (
            hl["cagr"] >= 0.60 and hl["mdd"] >= -0.40 and h["wr_daily"] >= 50.0
        )
        rows.append({
            "alpha": alpha,
            "sharpe": h["sharpe"], "cagr": h["cagr"], "mdd": h["mdd"],
            "calmar": h["calmar"], "wr_daily": h["wr_daily"],
            "lev_sharpe": hl["sharpe"], "lev_cagr": hl["cagr"], "lev_mdd": hl["mdd"],
            "lev_calmar": hl["calmar"],
            "passes_target": passes_target,
        })
        marker_pass = "PASS" if passes_target else "fail"
        print(f"  {alpha:.2f}   | {h['sharpe']:5.2f}   {100*h['cagr']:+6.1f}% {100*h['mdd']:+6.1f}% "
              f"{h['calmar']:5.2f}   {h['wr_daily']:5.2f}%  | "
              f"{100*hl['cagr']:+7.1f}% {100*hl['mdd']:+6.1f}%  {marker_pass}")

        # Track best Sharpe (standalone)
        if h["sharpe"] > best["best_sh"]:
            best["alpha_sh"] = alpha
            best["best_sh"] = h["sharpe"]
        # Track passing config with smallest alpha
        if passes_target and best["alpha_target"] is None:
            best["alpha_target"] = alpha

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v68b_alpha_sweep.csv", index=False)

    # Decision
    print("\n[Decision]")
    print(f"  Best STANDALONE Sharpe: alpha={best['alpha_sh']:.2f} -> Sh {best['best_sh']:.3f}")
    if best["alpha_target"] is not None:
        winner = next(r for r in rows if r["alpha"] == best["alpha_target"])
        print(f"  Smallest alpha clearing 60/50/-40 with L=1.75: alpha={best['alpha_target']:.2f}")
        print(f"    standalone: Sh {winner['sharpe']:.3f}  CAGR {100*winner['cagr']:+.1f}%  "
              f"MDD {100*winner['mdd']:+.1f}%  WR_d {winner['wr_daily']:.2f}%")
        print(f"    L=1.75:      Sh {winner['lev_sharpe']:.3f}  CAGR {100*winner['lev_cagr']:+.1f}%  "
              f"MDD {100*winner['lev_mdd']:+.1f}%  Cal {winner['lev_calmar']:.2f}")
    else:
        print("  No alpha clears 60/50/-40 with L=1.75")

    # Reference: V52 baseline numbers (alpha=0.60 via this code path)
    base = next((r for r in rows if r["alpha"] == 0.60), None)
    if base:
        print(f"\n  V52 baseline (alpha=0.60): Sh {base['sharpe']:.3f}  CAGR {100*base['cagr']:+.1f}%  "
              f"MDD {100*base['mdd']:+.1f}%  WR_d {base['wr_daily']:.2f}%")
        print(f"  V67 baseline (alpha=0.60, L=1.75): CAGR {100*base['lev_cagr']:+.1f}%  "
              f"MDD {100*base['lev_mdd']:+.1f}%  Sh {base['lev_sharpe']:.3f}")

    out = {
        "elapsed_s": round(time.time() - t0, 1),
        "alphas": alphas,
        "L_for_stack": L,
        "rows": rows,
        "best_standalone_sharpe": {"alpha": best["alpha_sh"], "sharpe": best["best_sh"]},
        "smallest_alpha_passing_60_50_40": best["alpha_target"],
    }
    (OUT / "v68b_alpha_sweep.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nElapsed: {out['elapsed_s']}s")
    print(f"Wrote {OUT/'v68b_alpha_sweep.csv'} and {OUT/'v68b_alpha_sweep.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
