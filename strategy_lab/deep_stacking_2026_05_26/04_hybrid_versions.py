"""Compute hybrid_v2/v3/v4/v5 — the BEST single/pair/triple/quad R3+R5 additions on top of hybrid_v1.

For each sleeve, exhaustively search:
  - v2 = hybrid_v1 + 1 R3+R5 gate (best by sum_pnl, AND n>=30)
  - v3 = v1 + 2 R3+R5 gates (best pair)
  - v4 = v1 + 3
  - v5 = v1 + 4

Also for each best vN, run 3-way validation + 500-shuffle bootstrap.
"""
from __future__ import annotations
import sys, time, itertools
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

MIN_N = 30
MAX_K_EXHAUSTIVE = 3  # exhaustive up to 3 added gates (~17^3 = 4913 combos per sleeve)


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
    return {"n": n, "sum_pnl": float(sub.pnl_legacy_usd.sum()),
            "dpt": float(sub.pnl_legacy_usd.mean()),
            "WR": float(sub.won.mean())}


def three_way_split_validation(universe, stack: list[str]):
    m = apply_stack(universe, stack)
    sub = universe[m].sort_values("fire_us").reset_index(drop=True)
    if len(sub) < 30:
        return None
    n = len(sub)
    n_tr = int(n * 0.67)
    n_vl = int(n * 0.17)
    train = sub.iloc[:n_tr]
    val = sub.iloc[n_tr:n_tr + n_vl]
    lock = sub.iloc[n_tr + n_vl:]
    if len(lock) < 5:
        return None

    rng = np.random.default_rng(42)
    full_pnl = sub.pnl_legacy_usd.values
    actual = float(lock.pnl_legacy_usd.mean())
    null_dpts = np.empty(500)
    for i in range(500):
        sample = rng.choice(full_pnl, size=len(lock), replace=True)
        null_dpts[i] = float(sample.mean())
    boot_p = float(np.mean(null_dpts >= actual))

    return {
        "n_total": n,
        "n_train": len(train), "dpt_train": float(train.pnl_legacy_usd.mean()),
        "sum_train": float(train.pnl_legacy_usd.sum()), "wr_train": float(train.won.mean()),
        "n_val": len(val), "dpt_val": float(val.pnl_legacy_usd.mean()) if len(val) else 0.0,
        "sum_val": float(val.pnl_legacy_usd.sum()) if len(val) else 0.0,
        "wr_val": float(val.won.mean()) if len(val) else 0.0,
        "n_lockbox": len(lock), "dpt_lockbox": actual,
        "sum_lockbox": float(lock.pnl_legacy_usd.sum()), "wr_lockbox": float(lock.won.mean()),
        "boot_p": boot_p,
        "lockbox_pass": bool(lock.pnl_legacy_usd.sum() > 0 and lock.won.mean() >= 0.55 and boot_p <= 0.10 and len(lock) >= 20),
    }


def exhaustive_combos(universe, base_gates, candidates, k_max, min_n):
    """For each k in 1..k_max, exhaustively find best k-tuple of added gates by sum_pnl."""
    results = []  # list of dicts
    base_mask = apply_stack(universe, base_gates)
    base_stats = cell_stats(universe[base_mask])
    results.append({
        "added_count": 0, "added": "", "n": base_stats["n"],
        "sum_pnl": base_stats["sum_pnl"], "dpt": base_stats["dpt"], "WR": base_stats["WR"]
    })
    for k in range(1, k_max + 1):
        best = None
        for combo in itertools.combinations(candidates, k):
            m = base_mask.copy()
            for g in combo:
                m &= (universe[g].values == 1)
            n = int(m.sum())
            if n < min_n:
                continue
            sub = universe[m]
            sp = float(sub.pnl_legacy_usd.sum())
            if best is None or sp > best["sum_pnl"]:
                best = {"added_count": k, "added": " & ".join(combo),
                        "n": n, "sum_pnl": sp,
                        "dpt": float(sub.pnl_legacy_usd.mean()),
                        "WR": float(sub.won.mean())}
        if best is not None:
            results.append(best)
        else:
            results.append({"added_count": k, "added": "(no_valid_combo)",
                            "n": 0, "sum_pnl": 0.0, "dpt": 0.0, "WR": 0.0})
    return results


def main():
    log("=" * 72)
    log("HYBRID v2/v3/v4 — exhaustive single/pair/triple R3+R5 adds on top of hybrid_v1")
    log("=" * 72)
    all_rows = []
    val_rows = []
    for (name, fp, asset, tf, offs, v1_gates) in SLEEVES:
        log(f"\n=== {name} ===")
        df = pd.read_parquet(RES / fp)
        mask = (df.asset == asset) & (df.fire_offset_s.isin(offs))
        if "tf" in df.columns:
            mask &= (df.tf == tf)
        universe = df[mask].copy()
        log(f"  universe: {len(universe):,}")

        combos = exhaustive_combos(universe, v1_gates, R3R5_GATES, MAX_K_EXHAUSTIVE, MIN_N)
        for r in combos:
            r["sleeve"] = name
            r["base_gates"] = " & ".join(v1_gates)
            r["k_total"] = len(v1_gates) + r["added_count"]
            all_rows.append(r)
            label = "v1" if r["added_count"] == 0 else f"v{r['added_count']+1}"
            log(f"  {label}: added '{r['added']}' n={r['n']}, sum=${r['sum_pnl']:.0f}, "
                f"dpt=${r['dpt']:.3f}, WR={r['WR']*100:.1f}%")

            # 3-way validation
            full_stack = list(v1_gates) + r["added"].split(" & ") if r["added"] else list(v1_gates)
            full_stack = [g for g in full_stack if g]
            v = three_way_split_validation(universe, full_stack)
            if v is not None:
                val = {"sleeve": name, "version": label, "stack": " & ".join(full_stack),
                       "added": r["added"], "k_total": len(full_stack), **v}
                val_rows.append(val)
                log(f"    3-way: n_lk={v['n_lockbox']}, dpt_lk=${v['dpt_lockbox']:.3f}, "
                    f"sum_lk=${v['sum_lockbox']:.0f}, WR_lk={v['wr_lockbox']*100:.1f}%, "
                    f"p={v['boot_p']:.3f}, pass={v['lockbox_pass']}")

    out = pd.DataFrame(all_rows)
    out.to_csv(RES / "deep_stack_hybrid_versions.csv", index=False)
    log(f"\nwrote deep_stack_hybrid_versions.csv ({len(out)} rows)")

    val_df = pd.DataFrame(val_rows)
    val_df.to_csv(RES / "deep_stack_hybrid_versions_3way.csv", index=False)
    log(f"wrote deep_stack_hybrid_versions_3way.csv ({len(val_df)} rows)")


if __name__ == "__main__":
    main()
