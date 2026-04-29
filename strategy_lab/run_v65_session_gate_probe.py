"""
V65 — Session-gate probe on V52 champion (Vector 5 in 33_NEW_STRATEGY_VECTORS.md).

This is a *cheap* probe, not a fresh sweep. It rebuilds V52 once via the
existing build_v52_hl() entry point, then applies session masks at the
equity-return level and reports headline metrics for each variant.

Six variants tested:

  baseline               : pure V52 (control)
  monday_asia_only       : equity returns kept only inside Sun23–Mon23 UTC
  ex_asia_session        : Asian session (00–07 UTC) returns dampened to 50%
  ex_weekend_chop        : Weekend chop (Sat all-day + Sun pre-23) dampened 50%
  teatime_only           : equity returns kept only inside 15–18 UTC
  combined_v1            : ex_asia_session AND ex_weekend_chop (multiplicative)

DECISION GATE for promoting a variant to V65 candidate:
  - Sharpe lift >= +0.10 vs baseline, AND
  - MDD non-worse vs baseline, AND
  - bar coverage >= 50% (don't ship a regime where we trade 5% of the time).

If `combined_v1` clears, V65 candidate is "V52 with session gates applied
at the sleeve level". Promotion to gates 1-10 happens in a follow-up runner.
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
from strategy_lab.strategies.session_gates import (
    monday_asia_open,
    asian_session,
    weekend_chop,
    teatime_volexp,
)

OUT = REPO / "docs" / "research" / "phase5_results"
OUT.mkdir(parents=True, exist_ok=True)
BPY = 365.25 * 6  # 4h bars/year


# ---------------------------------------------------------------------------
# Metrics (mirrors run_v59_v58_gates.headline)
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
    return {
        "label": label,
        "sharpe": round(sh, 3),
        "cagr": round(float(cagr), 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 3),
        "n_bars": int(len(eq)),
    }


# ---------------------------------------------------------------------------
# Gate application
# ---------------------------------------------------------------------------

def apply_keep_mask(eq: pd.Series, keep: pd.Series) -> pd.Series:
    """Keep returns where mask True; zero them otherwise. Rebuild equity."""
    r = eq.pct_change().fillna(0.0)
    keep = keep.reindex(eq.index).fillna(False)
    r_gated = r.where(keep, 0.0)
    return (1 + r_gated).cumprod() * float(eq.iloc[0])


def apply_dampen_mask(eq: pd.Series, dampen: pd.Series, factor: float = 0.5) -> pd.Series:
    """Multiply returns by `factor` where mask True; leave others alone."""
    r = eq.pct_change().fillna(0.0)
    dampen = dampen.reindex(eq.index).fillna(False)
    r_dampened = r.where(~dampen, r * factor)
    return (1 + r_dampened).cumprod() * float(eq.iloc[0])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    t0 = time.time()
    print("=" * 72)
    print("V65: Session-gate probe on V52 champion")
    print("=" * 72)

    print("\n[0] Building V52 baseline...")
    v52 = build_v52_hl()
    base = headline(v52, "baseline")
    print(f"   {base}")

    idx = v52.index

    # Coverage diagnostics (sanity)
    print("\n[1] Mask coverage (% of bars):")
    masks = {
        "monday_asia_open": monday_asia_open(idx),
        "asian_session": asian_session(idx),
        "weekend_chop": weekend_chop(idx),
        "teatime_volexp": teatime_volexp(idx),
    }
    for name, m in masks.items():
        cov = 100.0 * m.sum() / len(m)
        print(f"   {name:20s} {cov:5.1f}%")

    # Variants
    print("\n[2] Variant equity headlines:")
    variants = {}

    eq_v1 = apply_keep_mask(v52, masks["monday_asia_open"])
    variants["monday_asia_only"] = headline(eq_v1, "monday_asia_only")

    eq_v2 = apply_dampen_mask(v52, masks["asian_session"], factor=0.5)
    variants["ex_asia_session"] = headline(eq_v2, "ex_asia_session")

    eq_v3 = apply_dampen_mask(v52, masks["weekend_chop"], factor=0.5)
    variants["ex_weekend_chop"] = headline(eq_v3, "ex_weekend_chop")

    eq_v4 = apply_keep_mask(v52, masks["teatime_volexp"])
    variants["teatime_only"] = headline(eq_v4, "teatime_only")

    # combined_v1: dampen asia session AND weekend chop (multiplicatively)
    asia_or_chop = masks["asian_session"] | masks["weekend_chop"]
    eq_v5 = apply_dampen_mask(v52, asia_or_chop, factor=0.5)
    variants["combined_asia_chop"] = headline(eq_v5, "combined_asia_chop")

    rows = [base] + list(variants.values())
    df = pd.DataFrame(rows).set_index("label")
    print(df.to_string())

    # Decision check
    print("\n[3] Decision gate vs baseline (Sharpe >= +0.10 AND MDD non-worse):")
    promoted = []
    for label, m in variants.items():
        sh_lift = m["sharpe"] - base["sharpe"]
        mdd_ok = m["mdd"] >= base["mdd"]  # less-negative is better
        verdict = "PROMOTE" if (sh_lift >= 0.10 and mdd_ok) else "no"
        print(f"   {label:25s}  ΔSh={sh_lift:+.3f}  ΔMDD={m['mdd']-base['mdd']:+.4f}  -> {verdict}")
        if verdict == "PROMOTE":
            promoted.append(label)

    out = {
        "baseline": base,
        "variants": variants,
        "promoted": promoted,
        "elapsed_s": round(time.time() - t0, 2),
    }
    out_path = OUT / "v65_session_gate_probe.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\n[4] Wrote {out_path}")
    print(f"    Elapsed: {out['elapsed_s']:.1f}s")
    print(f"    Promoted variants: {promoted or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
