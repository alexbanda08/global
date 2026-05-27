"""TASK 6 — walk-forward validation for top QR-gated sleeves.

Splits 28d window into ~20d train / 8d test. For each top sleeve+QR-gate
combination, computes train WR/dpt, test WR/dpt, and a 1k bootstrap
confidence interval on test $/tr.

Inputs: qr_gate_overlay_top.csv + joined_all parquets

Outputs:
  data/v4/canonical/_results/qr_walk_forward.csv
"""
from __future__ import annotations
import sys, time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
QR5 = RES / "qr_panel_5m.parquet"
QR15 = RES / "qr_panel_15m.parquet"
S15 = RES / "s15_joined_all.parquet"
S6 = RES / "s6_joined_all.parquet"
V15M = RES / "v15m_joined_all.parquet"
TOP = RES / "hybrid_gate_search_top.csv"
QR_TOP = RES / "qr_gate_overlay_top.csv"

OUT = RES / "qr_walk_forward.csv"

# 28d window split: train Apr 30 → May 19 (20d), test May 19 → May 22 (8d cap)
# But our data is Apr 24 → May 25; use the canonical 28d window
TRAIN_END_US = 1779494400000000 - int(8 * 86400 * 1_000_000)  # 8d before window end


def overlay_qr(joined: pd.DataFrame, qr_panel: pd.DataFrame) -> pd.DataFrame:
    joined = joined.copy()
    joined["_lookup_us"] = joined["fire_us"].astype("int64") - 1
    qr_cols = ["ribbon_state", "market_regime", "market_health",
               "signal_confidence", "volume_ratio"]
    parts = []
    for asset in ("BTC", "ETH", "SOL"):
        j_a = joined[joined.asset == asset].sort_values("_lookup_us").reset_index(drop=True)
        q_a = qr_panel[qr_panel.asset == asset].sort_values("bar_close_us").reset_index(drop=True)
        q_ren = q_a.rename(columns={c: f"qr_{c}" for c in qr_cols})
        q_ren = q_ren[["bar_close_us"] + [f"qr_{c}" for c in qr_cols]]
        merged = pd.merge_asof(
            j_a, q_ren,
            left_on="_lookup_us", right_on="bar_close_us",
            direction="backward",
            tolerance=20 * 60 * 1_000_000,
        )
        parts.append(merged)
    out = pd.concat(parts, ignore_index=True)
    out = out.drop(columns=["_lookup_us"])
    # add QR gates
    dir_up = out["direction"] == "UP"
    dir_dn = out["direction"] == "DOWN"
    def g(cond): return cond.fillna(False).astype("int8").values
    out["g_qr_state_with"] = g(
        ((out["qr_ribbon_state"] >= 1) & dir_up) | ((out["qr_ribbon_state"] <= -1) & dir_dn)
    )
    out["g_qr_state_strong_with"] = g(
        ((out["qr_ribbon_state"] == 2) & dir_up) | ((out["qr_ribbon_state"] == -2) & dir_dn)
    )
    out["g_qr_trending"] = g(out["qr_market_regime"] == 1)
    out["g_qr_high_health"] = g(out["qr_market_health"] > 70)
    out["g_qr_high_conf"] = g(out["qr_signal_confidence"] > 4)
    out["g_qr_top_conf"] = g(out["qr_signal_confidence"] > 6)
    out["g_qr_volume_strong"] = g(out["qr_volume_ratio"] > 1.3)
    return out


def offset_bin(off: int, tf: str) -> str:
    if tf in ("s15", "s6", "5m"):
        if off <= 90: return "30-90"
        if off <= 150: return "60-150"
        if off <= 210: return "120-210"
        return "180-270"
    else:
        if off <= 240: return "60-240"
        if off <= 480: return "240-480"
        if off <= 720: return "480-720"
        return "720-840"


def apply_gates(df: pd.DataFrame, gates: list[str]) -> pd.DataFrame:
    mask = pd.Series([True]*len(df), index=df.index)
    for g in gates:
        if g not in df.columns:
            return df.iloc[0:0]
        mask &= (df[g] == 1)
    return df[mask].copy()


def normalize_offset_bin_filter(df: pd.DataFrame, tf_label: str, offset_bin_str: str) -> pd.DataFrame:
    if "fire_offset_s" not in df.columns:
        return df
    fam = "5m" if tf_label in ("s15", "s6") else "15m"
    df = df.copy()
    df["_ofb"] = df["fire_offset_s"].astype(int).apply(lambda o: offset_bin(o, fam))
    return df[df["_ofb"] == offset_bin_str].drop(columns=["_ofb"])


def bootstrap_ci(values: np.ndarray, n_boot=1000, alpha=0.05) -> tuple:
    if len(values) < 10:
        return (np.nan, np.nan)
    rng = np.random.default_rng(42)
    means = np.empty(n_boot)
    n = len(values)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        means[i] = values[idx].mean()
    return float(np.quantile(means, alpha/2)), float(np.quantile(means, 1-alpha/2))


def main():
    t0 = time.time()
    print("[1] loading...")
    qr5 = pd.read_parquet(QR5)
    qr15 = pd.read_parquet(QR15)
    top = pd.read_csv(TOP)
    top = top.sort_values("sum_pnl", ascending=False).drop_duplicates(
        subset=["asset", "tf", "offset_bin", "gate_stack"]
    ).head(10).reset_index(drop=True)
    qr_top = pd.read_csv(QR_TOP)
    qr_top = qr_top.sort_values("delta_dpt", ascending=False).head(20).reset_index(drop=True)
    print(f"  top hybrid sleeves: {len(top)}  qr_top lifts: {len(qr_top)}")

    s15 = pd.read_parquet(S15)
    s6 = pd.read_parquet(S6)
    v15m = pd.read_parquet(V15M)
    s15q = overlay_qr(s15, qr5)
    s6q = overlay_qr(s6, qr5)
    v15mq = overlay_qr(v15m, qr15)
    sources = {"s15_5m": s15q, "s6_5m": s6q, "v15m": v15mq}

    print(f"[2] train cutoff: fire_us < {TRAIN_END_US}  ({pd.Timestamp(TRAIN_END_US, unit='us')} UTC)")

    # Build combos: each hybrid top sleeve + each QR-overlay variant (no-QR + add 1 QR gate)
    QR_GATES_TO_TRY = [
        None,  # baseline (no QR addition)
        "g_qr_state_with", "g_qr_state_strong_with", "g_qr_trending",
        "g_qr_high_health", "g_qr_high_conf", "g_qr_top_conf",
        "g_qr_volume_strong",
    ]
    rows = []
    for idx, sleeve in top.iterrows():
        tf = str(sleeve["tf"]); asset = str(sleeve["asset"])
        offset_bin_str = str(sleeve["offset_bin"]); stack = str(sleeve["gate_stack"])
        if tf not in sources:
            continue
        sub = sources[tf]
        sub = sub[sub.asset == asset]
        sub = normalize_offset_bin_filter(sub, tf.split("_")[0], offset_bin_str)
        base_gates = stack.split("&")
        for add_qr in QR_GATES_TO_TRY:
            gates = list(base_gates)
            if add_qr is not None:
                gates.append(add_qr)
            filt = apply_gates(sub, gates)
            if len(filt) == 0:
                continue
            train = filt[filt["fire_us"] < TRAIN_END_US]
            test = filt[filt["fire_us"] >= TRAIN_END_US]
            ntr, nte = len(train), len(test)
            if ntr < 20 or nte < 5:
                continue
            wr_tr = train["won"].mean(); wr_te = test["won"].mean()
            dpt_tr = train["pnl_legacy_usd"].mean(); dpt_te = test["pnl_legacy_usd"].mean()
            sum_tr = train["pnl_legacy_usd"].sum(); sum_te = test["pnl_legacy_usd"].sum()
            ci_lo, ci_hi = bootstrap_ci(test["pnl_legacy_usd"].values)
            # PASS if test_dpt > 0 AND ci_lo > 0
            passed = bool(dpt_te > 0 and ci_lo > 0)
            rows.append({
                "rank": idx + 1, "asset": asset, "tf": tf, "offset_bin": offset_bin_str,
                "base_stack": stack[:80] + ("..." if len(stack) > 80 else ""),
                "added_qr_gate": str(add_qr),
                "n_train": ntr, "WR_train": wr_tr, "dpt_train": dpt_tr, "sum_train": sum_tr,
                "n_test":  nte, "WR_test":  wr_te, "dpt_test":  dpt_te, "sum_test":  sum_te,
                "ci_lo": ci_lo, "ci_hi": ci_hi, "passed": passed,
            })

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\n[3] wrote {OUT.name} ({len(out)} rows)")
    n_pass = int(out["passed"].sum())
    print(f"\nPASS: {n_pass}/{len(out)}  ({100*n_pass/max(len(out),1):.1f}%)")
    print(f"\nTop 25 by test dpt (passed only):")
    pcols = ["rank","asset","tf","offset_bin","added_qr_gate",
             "n_train","WR_train","dpt_train",
             "n_test","WR_test","dpt_test","ci_lo","ci_hi","passed"]
    show = out[out.passed].sort_values("dpt_test", ascending=False)
    print(show[pcols].head(25).to_string(index=False))

    print(f"\nDONE in {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
