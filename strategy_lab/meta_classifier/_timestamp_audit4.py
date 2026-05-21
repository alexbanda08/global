"""Definitive slug_ws interpretation test — under both hypotheses, what matches outcome?

Per user clarification (2026-05-09):
  Production's ws_s = STRIKE timestamp (= slug_ws - window_s, the start of the window)
  slug_ws = SLOT_END = market RESOLUTION time
  Market window = [slug_ws - window_s, slug_ws]
  Outcome resolves at slug_ws based on price@slug_ws vs price@(slug_ws - window_s)

Therefore the correct anchor for ret_2m (observable at fire time = strike + 60):
  c_pre  = close@(strike - 60) = close@(slug_ws - window_s - 60)
  c_post = close@(strike + 60) = close@(slug_ws - window_s + 60)
  ret_2m = log(c_post / c_pre)   [observable at strike+60 wallclock = ws-window_s+60]

Tests:
  T1. Outcome consistency under BOTH hypotheses, separately, on the SAME markets.
       - Hypothesis A (ws=START): outcome = sign(close@(ws+window_s) - close@ws)
       - Hypothesis B (ws=END):   outcome = sign(close@ws - close@(ws-window_s))
       Whichever has substantially higher match rate is the true interpretation.

  T2. ret_2m hit rate (no gate, full universe) under each interpretation:
       - A (current/buggy): ret_2m = log(close@(ws+60)/close@(ws-60))  [LOOKAHEAD if B is true]
       - B (corrected):     ret_2m = log(close@(ws-window_s+60)/close@(ws-window_s-60))
       Production reports ~52% live hit rate. Whichever interpretation matches that is correct.

  T3. Audit_F exact replication on a fresh sample (no head(2000) bias).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

from momo_full_universe_validation import (        # noqa: E402
    load_klines, load_universe, asof_strict,
)


def main():
    print("=== DEFINITIVE slug_ws INTERPRETATION TEST ===\n")
    print("[1] Loading klines + universe...")
    klines = load_klines()
    uni = load_universe()
    print(f"    universe: {len(uni)} markets, range {uni.day.min().date()} -> {uni.day.max().date()}\n")

    # --------------------------------------------------------------------
    # T1: outcome consistency under each hypothesis (RANDOM SAMPLE, not head)
    # --------------------------------------------------------------------
    print("[T1] Outcome ↔ price-direction match rate, hypothesis A vs B")
    print("     A: ws=START, expect sign(close@(ws+window) - close@ws) ≈ outcome")
    print("     B: ws=END,   expect sign(close@ws - close@(ws-window)) ≈ outcome\n")

    sample = uni.sample(min(5000, len(uni)), random_state=0)
    n_used = 0
    a_match = 0
    b_match = 0
    a_finite = 0
    b_finite = 0
    a_ties = 0
    b_ties = 0

    # Spread out by asset
    for asset_filter in ("BTC", "ETH", "SOL"):
        sub_a = sample[sample.asset == asset_filter]
        a_ok_a = a_ok_b = 0
        a_n_a = a_n_b = 0
        for r in sub_a.itertuples(index=False):
            ws = int(r.ws)
            window_s = int(r.window_s)
            outcome = r.outcome

            # Hypothesis A: ws=start
            p_at = asof_strict(klines[asset_filter], ws)
            p_after = asof_strict(klines[asset_filter], ws + window_s)
            if (math.isfinite(p_at) and math.isfinite(p_after)
                    and p_at > 0 and p_after > 0 and abs(p_after - p_at) > 1e-9):
                derived_a = "Up" if (p_after - p_at) > 0 else "Down"
                a_n_a += 1
                if derived_a == outcome:
                    a_ok_a += 1

            # Hypothesis B: ws=end
            p_before = asof_strict(klines[asset_filter], ws - window_s)
            if (math.isfinite(p_before) and math.isfinite(p_at)
                    and p_before > 0 and p_at > 0 and abs(p_at - p_before) > 1e-9):
                derived_b = "Up" if (p_at - p_before) > 0 else "Down"
                a_n_b += 1
                if derived_b == outcome:
                    a_ok_b += 1

        pct_a = round(100 * a_ok_a / max(a_n_a, 1), 2)
        pct_b = round(100 * a_ok_b / max(a_n_b, 1), 2)
        print(f"    {asset_filter}: hypothesis A match {pct_a}% (n={a_n_a}), "
              f"hypothesis B match {pct_b}% (n={a_n_b})")
        a_match += a_ok_a; a_finite += a_n_a
        b_match += a_ok_b; b_finite += a_n_b

    pct_a = round(100 * a_match / max(a_finite, 1), 2)
    pct_b = round(100 * b_match / max(b_finite, 1), 2)
    print(f"\n    OVERALL: A={pct_a}% (n={a_finite}), B={pct_b}% (n={b_finite})")
    if pct_b > pct_a + 5:
        print("    -> hypothesis B (ws=END) is correct. My harness has LOOKAHEAD BUG.")
    elif pct_a > pct_b + 5:
        print("    -> hypothesis A (ws=START) is correct. My harness was right.")
    else:
        print("    -> ambiguous; both hypotheses give similar rates (autocorrelation suspected)")

    # --------------------------------------------------------------------
    # T2: ret_2m hit rate under each interpretation
    # --------------------------------------------------------------------
    print("\n[T2] ret_2m sign hit rate (no gate), under buggy vs corrected anchor")
    print("    BUGGY (A-style):  ret = log(close@(ws+60) / close@(ws-60))     [my current harness]")
    print("    CORRECT (B-style): ret = log(close@(ws-window+60) / close@(ws-window-60))")

    rows = []
    for r in sample.itertuples(index=False):
        ws = int(r.ws)
        window_s = int(r.window_s)
        kl = klines[r.asset]
        # Buggy
        c0_b = asof_strict(kl, ws - 60)
        c1_b = asof_strict(kl, ws + 60)
        # Corrected
        c0_c = asof_strict(kl, ws - window_s - 60)
        c1_c = asof_strict(kl, ws - window_s + 60)
        rows.append({
            "asset": r.asset, "tf": r.tf, "outcome": r.outcome,
            "ret_buggy": math.log(c1_b / c0_b) if math.isfinite(c0_b) and math.isfinite(c1_b)
                          and c0_b > 0 and c1_b > 0 else float("nan"),
            "ret_correct": math.log(c1_c / c0_c) if math.isfinite(c0_c) and math.isfinite(c1_c)
                           and c0_c > 0 and c1_c > 0 else float("nan"),
        })
    df = pd.DataFrame(rows)
    for col_name, col in [("BUGGY (ws+60 / ws-60)", "ret_buggy"),
                          ("CORRECT (strike+60 / strike-60)", "ret_correct")]:
        sub = df[df[col].notna() & (df[col] != 0)]
        if len(sub) == 0:
            print(f"    {col_name}: no valid samples")
            continue
        sub = sub.copy()
        sub["pred"] = sub[col].apply(lambda x: "Up" if x > 0 else "Down")
        sub["correct"] = (sub.pred == sub.outcome).astype(int)
        overall_hit = round(100 * sub.correct.mean(), 2)
        per_cell = sub.groupby(["asset", "tf"]).correct.mean().round(4) * 100
        print(f"\n    {col_name}: overall hit = {overall_hit}% (n={len(sub)})")
        for (a, t), v in per_cell.items():
            print(f"        {a}_{t}: {v:.2f}%")

    # --------------------------------------------------------------------
    # T3: head(2000) effect — is my prior audit_F sample biased?
    # --------------------------------------------------------------------
    print("\n[T3] Replicate prior audit_F (head 2000, NO sampling)...")
    head = uni.head(2000).copy()
    a_match = a_n = 0
    b_match = b_n = 0
    for r in head.itertuples(index=False):
        ws = int(r.ws)
        window_s = int(r.window_s)
        kl = klines[r.asset]
        outcome = r.outcome
        p_at = asof_strict(kl, ws)
        p_after = asof_strict(kl, ws + window_s)
        p_before = asof_strict(kl, ws - window_s)
        if (math.isfinite(p_at) and math.isfinite(p_after)
                and abs(p_after - p_at) > 1e-9):
            a_n += 1
            if (("Up" if (p_after - p_at) > 0 else "Down") == outcome):
                a_match += 1
        if (math.isfinite(p_at) and math.isfinite(p_before)
                and abs(p_at - p_before) > 1e-9):
            b_n += 1
            if (("Up" if (p_at - p_before) > 0 else "Down") == outcome):
                b_match += 1
    print(f"    head(2000): A={round(100*a_match/max(a_n,1),2)}% (n={a_n}), "
          f"B={round(100*b_match/max(b_n,1),2)}% (n={b_n})")


if __name__ == "__main__":
    main()
