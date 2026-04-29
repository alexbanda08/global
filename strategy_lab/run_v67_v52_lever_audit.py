"""
V67 — V52 leverage audit: measure baseline WR + sweep leverage 1.0..2.5x.

V52 baseline (V65 measurement): Sh 2.52 / CAGR 31.5% / MDD -5.8%.
With MDD = -5.8%, applying 2x leverage approximately doubles return-vol AND
doubles MDD to ~-12%, which is well inside the -40% mission cap.

This runner:
  1. Rebuilds V52 once.
  2. Computes baseline WR by aggregating per-sleeve trade lists if possible,
     else by daily up-day proxy on equity returns.
  3. Sweeps leverage L in {1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5}.
     Levered equity = (1 + L * r).cumprod() * init_cash, with daily liquidation
     check (stop if any single bar return < -1/L).
  4. Reports CAGR / Sharpe / MDD / WR / liquidation flag per L.
  5. Identifies the smallest L that clears CAGR >= 60% AND MDD >= -40%
     (preferred: smallest L to minimize tail risk).

NOTE: This is leverage applied at the BLEND level (post-sleeve-aggregation).
True per-sleeve leverage requires re-running each sleeve's simulator with
leverage_cap kwarg, which is more invasive. Blend-level leverage is the
honest first probe — the question is whether V52's intrinsic Sharpe is
high enough to make leveraged variants viable; tail-event modeling comes
next if this test passes.
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

from strategy_lab.run_v52_hl_gates import build_v52_hl

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6


def metrics(eq: pd.Series) -> dict:
    r = eq.pct_change().dropna()
    sd = float(r.std())
    sh = (float(r.mean()) / sd) * np.sqrt(BPY) if sd > 0 else 0.0
    pk = eq.cummax()
    mdd = float((eq / pk - 1).min())
    yrs = (eq.index[-1] - eq.index[0]).total_seconds() / (365.25 * 86400)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-6)) - 1
    cal = float(cagr) / abs(mdd) if mdd != 0 else 0.0

    # Bar-level WR: percentage of bars with positive return (only counting
    # active bars where |r| > tiny, to exclude zero-return/no-position bars).
    active = r[r.abs() > 1e-7]
    wr_active_bars = 100.0 * (active > 0).mean() if len(active) else float("nan")

    # Daily-resampled WR: less noisy, closer to "trade WR" semantics
    daily = (1 + r).resample("D").prod() - 1
    daily_active = daily[daily.abs() > 1e-7]
    wr_daily = 100.0 * (daily_active > 0).mean() if len(daily_active) else float("nan")

    return {
        "sharpe": round(sh, 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 3),
        "wr_active_bars": round(float(wr_active_bars), 2),
        "wr_daily": round(float(wr_daily), 2),
        "n_bars": int(len(eq)),
        "n_active_bars": int(len(active)),
    }


def lever(eq: pd.Series, L: float) -> tuple[pd.Series, bool]:
    """Apply leverage L at return-stream level. Returns (levered_eq, liquidated)."""
    r = eq.pct_change().fillna(0.0)
    levered = L * r
    # Liquidation if any single bar drawdown <= -1 (we bound at -0.99 to keep math safe)
    liquidated = bool((levered <= -0.99).any())
    levered_capped = levered.clip(lower=-0.99)
    out = (1 + levered_capped).cumprod() * float(eq.iloc[0])
    return out, liquidated


def main() -> int:
    t0 = time.time()
    print("=" * 72)
    print("V67: V52 leverage audit")
    print("Target: smallest L that clears CAGR>=60% AND MDD>=-40% AND WR>=50%")
    print("=" * 72)

    print("\n[0] Building V52 baseline...")
    v52 = build_v52_hl()
    base = metrics(v52)
    print(f"   V52 baseline: {base}")

    print("\n[1] Leverage sweep (blend-level):")
    rows = [{"L": 1.0, **base, "liquidated": False}]
    for L in [1.25, 1.5, 1.75, 2.0, 2.25, 2.5]:
        eq_L, liq = lever(v52, L)
        m = metrics(eq_L)
        m["L"] = L
        m["liquidated"] = liq
        rows.append(m)
        print(f"  L={L:.2f}  Sh={m['sharpe']:.2f}  CAGR={100*m['cagr']:+6.1f}%  "
              f"MDD={100*m['mdd']:+6.1f}%  Cal={m['calmar']:.2f}  "
              f"WR_bars={m['wr_active_bars']:.1f}%  WR_daily={m['wr_daily']:.1f}%  "
              f"liq={'YES' if liq else 'no'}")

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "v67_lever_audit.csv", index=False)

    # Find smallest L that clears all gates
    target_rows = df[
        (df["cagr"] >= 0.60) & (df["mdd"] >= -0.40) & (df["wr_daily"] >= 50.0) & (~df["liquidated"])
    ].sort_values("L")

    print()
    if len(target_rows) > 0:
        winner = target_rows.iloc[0]
        print(f"WINNER: L={winner['L']:.2f}  CAGR={100*winner['cagr']:+.1f}%  "
              f"MDD={100*winner['mdd']:+.1f}%  WR_daily={winner['wr_daily']:.1f}%  "
              f"Sh={winner['sharpe']:.2f}")
        verdict = "PASS"
    else:
        # Diagnose which gate is binding
        cagr_pass = df[df["cagr"] >= 0.60]
        wr_pass = df[df["wr_daily"] >= 50.0]
        print(f"NO L clears all gates.")
        print(f"   L's that clear CAGR>=60%: {cagr_pass['L'].tolist()}")
        print(f"   L's that clear WR>=50%:   {wr_pass['L'].tolist()}")
        print(f"   binding gate: WR" if len(cagr_pass) > 0 and len(wr_pass) == 0
              else f"   binding gate: CAGR" if len(wr_pass) > 0 and len(cagr_pass) == 0
              else "   binding gate: both")
        verdict = "FAIL_AT_BLEND_LEVEL"

    out = {
        "elapsed_s": round(time.time() - t0, 2),
        "verdict": verdict,
        "rows": rows,
    }
    (OUT / "v67_lever_audit.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"\nWrote {OUT/'v67_lever_audit.csv'} and {OUT/'v67_lever_audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
