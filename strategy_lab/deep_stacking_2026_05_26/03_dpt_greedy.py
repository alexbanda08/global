"""Deep stacking — alternate greedy: maximize $/tr instead of sum_pnl.

This is the "hybrid_v3-style" build that PRIORITIZES PER-TRADE QUALITY.
Acceptance: dpt must strictly improve AND n >= MIN_N=30.
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

SLEEVES = [
    ("BTC_S6_60_150", "deep_stack_panel_s6.parquet", "BTC", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_stoch_with", "g_rf_with", "g_tr_above_ema50", "g_ribbon_agrees"]),
    ("ETH_S6_60_150", "deep_stack_panel_s6.parquet", "ETH", "5m", [60, 90, 120, 150],
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("SOL_S6_60_150", "deep_stack_panel_s6.parquet", "SOL", "5m", [60, 90, 120, 150],
     ["g_mfi_with", "g_within_dev", "g_bb_pos_with", "g_ribbon_agrees"]),
    ("BTC_S15_150_240", "deep_stack_panel_s15.parquet", "BTC", "5m", [150, 180, 210, 240],
     ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon"]),
    ("ETH_S15_150_240", "deep_stack_panel_s15.parquet", "ETH", "5m", [150, 180, 210, 240],
     ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with", "g_bb_pos_with", "g_cci_with"]),
    ("S7_btc_5m_base", "deep_stack_panel_v15m.parquet", "BTC", "15m", [480, 600, 720, 840],
     ["g_tr_stack_full_with", "g_tr_above_ema800", "g_ribbon_agrees", "g_tight_ribbon",
      "g_stoch_with", "g_tr_above_ema200"]),
]

R3R5_GATES = [
    "g_r5_mp_no_extreme", "g_r5_mp_change_with", "g_r5_mp_skew_with",
    "g_r5_lm_high_stat", "g_r5_lm_recent_jump_with",
    "g_r5_hawkes_imbalance_with", "g_r5_as_low_uncert",
    "g_r3_vol_expanding", "g_r3_vol_contracting",
    "g_r3_vol_high", "g_r3_vol_med",
    "g_r3_hurst_trending",
    "g_r3_imb5_with", "g_r3_imb5_strong_with",
    "g_r3_queue_top_high", "g_r3_imb_change_with",
    "g_r3_book_slope_steep_against",
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def apply_stack(df, gates):
    m = np.ones(len(df), dtype=bool)
    for g in gates:
        m &= (df[g] == 1)
    return m


def cell_stats(sub):
    n = len(sub)
    if n == 0:
        return {"n": 0, "sum_pnl": 0.0, "dpt": 0.0, "WR": 0.0}
    return {
        "n": n,
        "sum_pnl": float(sub.pnl_legacy_usd.sum()),
        "dpt": float(sub.pnl_legacy_usd.mean()),
        "WR": float(sub.won.mean()),
    }


def greedy_add(universe, current_stack, candidates, objective="dpt", min_n=30):
    cur_mask = apply_stack(universe, current_stack)
    cur = cell_stats(universe[cur_mask])

    best_gate = None
    best_score = cur[objective] if objective in cur else -1e18
    best_stats = None
    for g in candidates:
        if g in current_stack:
            continue
        new_mask = cur_mask & (universe[g].values == 1)
        if new_mask.sum() < min_n:
            continue
        sub = universe[new_mask]
        st = cell_stats(sub)
        score = st[objective] if objective in st else -1e18
        if score > best_score:
            best_score = score
            best_gate = g
            best_stats = st
    return best_gate, best_stats, cur


def run(sleeve_name, fp, asset, tf, offs, v1_gates, objective="dpt"):
    log(f"=== {sleeve_name}  [obj={objective}] ===")
    df = pd.read_parquet(RES / fp)
    mask = (df.asset == asset) & (df.fire_offset_s.isin(offs))
    if "tf" in df.columns:
        mask &= (df.tf == tf)
    universe = df[mask].copy()
    log(f"  universe: {len(universe):,}")

    rows = []
    # baseline (no gates)
    st = cell_stats(universe)
    rows.append({"sleeve": sleeve_name, "k": 0, "added_gate": "(baseline)", "stack": "", **st})

    # hybrid_v1
    cur_stack = list(v1_gates)
    st = cell_stats(universe[apply_stack(universe, cur_stack)])
    rows.append({"sleeve": sleeve_name, "k": len(cur_stack), "added_gate": "(hybrid_v1)",
                 "stack": " & ".join(cur_stack), **st})
    log(f"  hybrid_v1: n={st['n']}, sum=${st['sum_pnl']:.0f}, dpt=${st['dpt']:.3f}, WR={st['WR']*100:.1f}%")

    k = len(cur_stack)
    for step in range(15):
        gate, st_new, st_cur = greedy_add(universe, cur_stack, R3R5_GATES, objective=objective)
        if gate is None:
            log(f"  k={k+1}: no improvement at obj={objective}, stop")
            break
        cur_stack.append(gate)
        k += 1
        rows.append({"sleeve": sleeve_name, "k": k, "added_gate": gate,
                     "stack": " & ".join(cur_stack), **st_new})
        log(f"  k={k}: +{gate}  -> n={st_new['n']}, sum=${st_new['sum_pnl']:.0f}, "
            f"dpt=${st_new['dpt']:.3f}, WR={st_new['WR']*100:.1f}%")
    return pd.DataFrame(rows)


def main():
    log("=" * 72)
    log("DEEP STACKING by dpt — diminishing returns curves")
    log("=" * 72)
    all_rows = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        rows = run(name, fp, asset, tf, offs, v1_gates, objective="dpt")
        all_rows.append(rows)
    out = pd.concat(all_rows, ignore_index=True)
    out.to_csv(RES / "deep_stack_results_dpt_objective.csv", index=False)
    log(f"wrote deep_stack_results_dpt_objective.csv ({len(out)} rows)")


if __name__ == "__main__":
    main()
