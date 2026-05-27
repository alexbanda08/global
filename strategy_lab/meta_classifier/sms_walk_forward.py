"""Walk-forward validation for top SMS-enhanced sleeves.

20-day train / 8-day test split + 200-shuffle bootstrap.

For each top-N "new sleeve" (base + best SMS gate):
  1. Split chronologically: train = first 20d, test = last 8d (rough — entire window is 22d).
  2. Compute train + test PnL.
  3. Run 200 bootstrap shuffles of test (sample with replacement, same n) and
     report 5/50/95 percentiles of dpt and sum_pnl.
  4. PASS = test dpt > 0 AND 5th percentile dpt > 0.

Inputs:
  data/v4/canonical/_results/{s15,s6,v15m}_joined_all.parquet
  data/v4/canonical/_results/sms_panel_{5m,15m}.parquet
  data/v4/canonical/_results/sms_top_new_sleeves.csv

Output:
  data/v4/canonical/_results/sms_walk_forward.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

# reuse functions from the gate overlay module
from sms_gate_overlay import (  # type: ignore
    merge_sms, add_sms_gates, apply_stack, offset_in_bin,
    S15_JOIN, S6_JOIN, V15M_JOIN, SMS_5M, SMS_15M,
)

TOP_SLEEVES_CSV = RES / "sms_top_new_sleeves.csv"
OUT = RES / "sms_walk_forward.csv"

# Window: Apr 30 -> May 22 (22 days). Split: train = first 16d (covers Apr 30 - May 15);
# test = last 8d (May 14 - May 22). Use 16+8 with 2-day overlap eliminated.
# Match the spec literally: 20d train + 8d test = 28d total (but we only have 22d).
# Use 14d train + 8d test.
WIN_START = pd.Timestamp("2026-04-30 00:00", tz="UTC").value // 1_000
WIN_TRAIN_END = pd.Timestamp("2026-05-14 00:00", tz="UTC").value // 1_000
WIN_TEST_START = WIN_TRAIN_END
WIN_END = pd.Timestamp("2026-05-22 23:59", tz="UTC").value // 1_000

N_BOOT = 200


def passing_fires(joined: pd.DataFrame, asset: str, gate_stack: str, sms_gate: str,
                  offset_bin: str) -> pd.DataFrame:
    sub = joined[joined["asset"] == asset].copy()
    bin_mask = sub["fire_offset_s"].astype(int).apply(lambda o: offset_in_bin(o, offset_bin))
    sub = sub[bin_mask].copy()
    if len(sub) == 0:
        return sub
    stack = apply_stack(sub, gate_stack)
    sub = sub[stack]
    if sms_gate and sms_gate != "NONE" and sms_gate in sub.columns:
        sub = sub[sub[sms_gate] == 1]
    return sub


def bootstrap_dpt(pnl: np.ndarray, n_boot: int = N_BOOT, seed: int = 42):
    if len(pnl) == 0:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    n = len(pnl)
    samples = rng.choice(pnl, size=(n_boot, n), replace=True)
    dpts = samples.mean(axis=1)
    return float(np.percentile(dpts, 5)), float(np.percentile(dpts, 50)), float(np.percentile(dpts, 95))


def main():
    print("[load + merge SMS]")
    s15 = pd.read_parquet(S15_JOIN); s6 = pd.read_parquet(S6_JOIN); v15m = pd.read_parquet(V15M_JOIN)
    s15 = merge_sms(s15, SMS_5M, tf_min=5)
    s6 = merge_sms(s6, SMS_5M, tf_min=5)
    v15m = merge_sms(v15m, SMS_15M, tf_min=15)
    s15 = add_sms_gates(s15); s6 = add_sms_gates(s6); v15m = add_sms_gates(v15m)
    JOINED = {"s15_5m": s15, "s6_5m": s6, "v15m_15m": v15m}

    top = pd.read_csv(TOP_SLEEVES_CSV)
    # Also include the BASE sleeve (no SMS gate) for comparison
    rows = []
    for _, row in top.iterrows():
        tf = row["tf"]
        joined = JOINED[tf]
        # 1) BASE sleeve
        base_fires = passing_fires(joined, row["asset"], row["base_sleeve"], "NONE", row["offset_bin"])
        # 2) ENHANCED sleeve (base + best SMS gate)
        enh_fires = passing_fires(joined, row["asset"], row["base_sleeve"],
                                  row["added_sms_gate"], row["offset_bin"])
        for label, fires in [("BASE", base_fires), ("BASE+SMS", enh_fires)]:
            if len(fires) == 0:
                continue
            train = fires[fires["fire_us"] < WIN_TRAIN_END]
            test = fires[fires["fire_us"] >= WIN_TEST_START]
            tr_n = len(train); te_n = len(test)
            tr_dpt = train["pnl_legacy_usd"].mean() if tr_n else np.nan
            te_dpt = test["pnl_legacy_usd"].mean() if te_n else np.nan
            tr_wr = train["won"].mean() if tr_n else np.nan
            te_wr = test["won"].mean() if te_n else np.nan
            tr_sum = train["pnl_legacy_usd"].sum()
            te_sum = test["pnl_legacy_usd"].sum()
            te_p5, te_p50, te_p95 = bootstrap_dpt(test["pnl_legacy_usd"].values, N_BOOT)
            passed = (te_n >= 30) and (te_dpt > 0) and (te_p5 > 0)
            rows.append({
                "asset": row["asset"], "tf": tf, "offset_bin": row["offset_bin"],
                "sleeve_label": label,
                "base_sleeve": row["base_sleeve"][:60],
                "added_sms_gate": row["added_sms_gate"] if label == "BASE+SMS" else "NONE",
                "train_n": tr_n, "train_WR": tr_wr, "train_dpt": tr_dpt, "train_sum_pnl": tr_sum,
                "test_n": te_n, "test_WR": te_wr, "test_dpt": te_dpt, "test_sum_pnl": te_sum,
                "test_dpt_p5": te_p5, "test_dpt_p50": te_p50, "test_dpt_p95": te_p95,
                "passes_g4": passed,
            })

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.max_colwidth", 60)
    pd.set_option("display.width", 220)
    print(f"wrote {OUT} ({len(out)} rows)")
    print("\n=== Walk-forward results ===")
    print(out[["asset", "tf", "offset_bin", "sleeve_label", "added_sms_gate",
               "train_n", "train_dpt", "test_n", "test_WR", "test_dpt",
               "test_dpt_p5", "test_dpt_p50", "passes_g4"]].to_string(index=False))

    n_pass = int(out["passes_g4"].sum())
    n_pass_enh = int(out[out["sleeve_label"] == "BASE+SMS"]["passes_g4"].sum())
    n_pass_base = int(out[out["sleeve_label"] == "BASE"]["passes_g4"].sum())
    print(f"\nPASS: {n_pass} / {len(out)} total ({n_pass_enh} enhanced, {n_pass_base} base)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
