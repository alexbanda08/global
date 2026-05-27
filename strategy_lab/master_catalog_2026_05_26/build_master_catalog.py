"""Build the master per-sleeve audited catalog from all R1-R7 result CSVs.

Outputs:
    data/v4/canonical/_results/master_sleeve_catalog_audited.csv
"""
from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
WS_DIR = ROOT / "strategy_lab" / "ws_poly2_dedup_2026_05_26"
OUT_CSV = RES / "master_sleeve_catalog_audited.csv"


COLS = [
    "sleeve_id",
    "discovery_round",
    "asset",
    "tf",
    "offset_range_s",
    "base_strategy",
    "gate_stack",
    "n_total",
    "wr_total",
    "dollar_per_trade",
    "sum_pnl_28d",
    "max_DD",
    "max_loss_streak",
    "sharpe_daily",
    "n_lockbox",
    "wr_lockbox",
    "dpt_lockbox",
    "sum_lockbox",
    "bootstrap_p_lockbox",
    "oos_status",
    "slug_overlap_pct_with_primary",
    "deploy_status",
    "source_round_report",
    "confidence_grade",
    "notes",
]


def empty_row() -> dict:
    return {c: None for c in COLS}


# --- Helpers --------------------------------------------------------------
def safe_float(x, default=None):
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def normalize_28d(sum_val: float | None, n_days: float | None) -> float | None:
    """Normalize a sum_pnl over n_days to 28d window."""
    sum_val = safe_float(sum_val)
    n_days = safe_float(n_days)
    if sum_val is None:
        return None
    if n_days is None or n_days <= 0:
        return sum_val
    return sum_val * (28.0 / n_days)


# --- Source-specific loaders ---------------------------------------------

def load_deploy_manifest() -> pd.DataFrame:
    """R6 dedup-validated deploy manifest (26 rows)."""
    df = pd.read_csv(RES / "final_deploy_manifest.csv")
    rows = []
    for _, r in df.iterrows():
        row = empty_row()
        row["sleeve_id"] = r["sleeve_id"]
        row["discovery_round"] = "R6"  # superseding round
        row["asset"] = r["asset"]
        row["tf"] = r["tf"]
        row["offset_range_s"] = r["offset_range_s"]
        row["base_strategy"] = r["base_strategy"]
        row["gate_stack"] = r["gate_stack"]
        row["n_total"] = int(r["n"]) if pd.notna(r.get("n")) else None
        row["wr_total"] = safe_float(r["wr_pct"])
        row["dollar_per_trade"] = safe_float(r["per_tr"])
        row["sum_pnl_28d"] = safe_float(r["expected_sum_28d"])
        row["slug_overlap_pct_with_primary"] = safe_float(r["overlap_with_primary_pct"])
        row["deploy_status"] = r["status"]
        # marginal_28d gives operational truth
        row["notes"] = (
            f"marginal_28d=${safe_float(r['marginal_28d']):.0f} "
            f"notional_share={safe_float(r['recommended_notional_share']):.2f}"
        )
        row["source_round_report"] = "SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md"
        # confidence
        st = str(r["status"])
        ov = safe_float(r["overlap_with_primary_pct"], 0)
        marg = safe_float(r["marginal_28d"], 0)
        if st == "DEPLOY" and marg > 200 and ov < 40:
            row["confidence_grade"] = "A"
        elif st == "DEPLOY":
            row["confidence_grade"] = "B"
        elif st == "PAPER_FIRST":
            row["confidence_grade"] = "B"
        elif st == "SKIP_OVERLAP":
            row["confidence_grade"] = "C"
        elif st == "SKIP_NEGATIVE_PNL":
            row["confidence_grade"] = "F"
        else:
            row["confidence_grade"] = "C"
        # oos
        if marg > 0 and st in ("DEPLOY", "PAPER_FIRST"):
            row["oos_status"] = "PASS"
        elif marg <= 0 and st == "DEPLOY":
            row["oos_status"] = "MARGINAL"
        else:
            row["oos_status"] = "FAIL"
        rows.append(row)
    return pd.DataFrame(rows)


def load_full_window_all_sleeves() -> pd.DataFrame:
    """R4 full_window backbone covers the R1-R4 superset (42 rows)."""
    df = pd.read_csv(RES / "full_window_all_sleeves_results.csv")
    rows = []
    for _, r in df.iterrows():
        sid = r["sleeve_id"]
        row = empty_row()
        row["sleeve_id"] = sid
        # Discovery round mapping: 01..16 are R1/R2 family; R1_/R2_ from R1/R2
        if sid.startswith("R1_"):
            row["discovery_round"] = "R1"
        elif sid.startswith("R2_"):
            row["discovery_round"] = "R2"
        elif sid.startswith("T1_") or sid.startswith("T2_"):
            row["discovery_round"] = "R2"
        elif sid.startswith("S15_") or sid.startswith("V15_"):
            row["discovery_round"] = "R4"
        elif sid.startswith("S7_") or sid.startswith("S6TA_"):
            row["discovery_round"] = "R4"
        elif sid.startswith("S2_") or sid.startswith("S5_"):
            row["discovery_round"] = "R1"
        else:
            # Numeric prefixes are R1-R5 ensemble checks
            row["discovery_round"] = "R1-R5"

        row["asset"] = r["asset"]
        row["tf"] = r["tf"]
        row["offset_range_s"] = r["offset_range"]
        row["base_strategy"] = r["base"]
        row["gate_stack"] = r["gates"]
        row["n_total"] = int(r["full_n"]) if pd.notna(r["full_n"]) else None
        row["wr_total"] = safe_float(r["full_wr"]) * 100 if pd.notna(r["full_wr"]) else None
        row["dollar_per_trade"] = safe_float(r["full_dpt"])
        # Normalize to 28d (full_days is the actual window)
        row["sum_pnl_28d"] = normalize_28d(r["full_sum"], r["full_days"])
        row["max_DD"] = safe_float(r["full_max_dd"])
        row["max_loss_streak"] = int(r["full_loss_streak"]) if pd.notna(r["full_loss_streak"]) else None
        row["sharpe_daily"] = safe_float(r["full_sharpe"])
        row["n_lockbox"] = int(r["oos_22to25_n"]) if pd.notna(r["oos_22to25_n"]) else None
        row["wr_lockbox"] = safe_float(r["oos_22to25_wr"]) * 100 if pd.notna(r["oos_22to25_wr"]) else None
        row["dpt_lockbox"] = safe_float(r["oos_22to25_dpt"])
        row["sum_lockbox"] = safe_float(r["oos_22to25_sum"])
        row["oos_status"] = "PASS" if bool(r["oos_pass"]) else "FAIL"
        row["source_round_report"] = "FULL_WINDOW_ALL_SLEEVES_2026_05_26.md"

        # confidence grade
        wr_lock = row["wr_lockbox"] or 0
        dpt_lock = row["dpt_lockbox"] or 0
        sum_lock = row["sum_lockbox"] or 0
        if bool(r["oos_pass"]) and wr_lock >= 60 and dpt_lock > 1.0 and sum_lock > 500:
            row["confidence_grade"] = "A"
        elif bool(r["oos_pass"]) and wr_lock >= 55 and dpt_lock > 0:
            row["confidence_grade"] = "B"
        elif bool(r["oos_pass"]):
            row["confidence_grade"] = "C"
        else:
            row["confidence_grade"] = "F"

        # deploy_status: only the R6 manifest can promote to DEPLOY/PAPER_FIRST.
        # Everything else from full_window_all_sleeves stays CANDIDATE
        # unless OOS-failed.
        if not bool(r["oos_pass"]):
            row["deploy_status"] = "SKIP_NEGATIVE_PNL"
        else:
            row["deploy_status"] = "CANDIDATE"

        rows.append(row)
    return pd.DataFrame(rows)


def load_sleeve_hunt_15m_v2() -> pd.DataFrame:
    """R4 178-sleeve trend_slope 15m sweep."""
    df = pd.read_csv(RES / "sleeve_hunt_15m_v2_deployable.csv")
    rows = []
    for _, r in df.iterrows():
        row = empty_row()
        ob = r["offset_bin"]
        gs = r["gate_stack"]
        sid = f"R4_{r['asset']}_15m_{ob}_{gs}"
        row["sleeve_id"] = sid
        row["discovery_round"] = "R4"
        row["asset"] = r["asset"]
        row["tf"] = "15m"
        row["offset_range_s"] = ob
        row["base_strategy"] = "trend_slope_15m"
        row["gate_stack"] = gs
        # Combine train+val+lockbox as proxy for full-window
        n_train = safe_float(r["train_n"], 0)
        n_val = safe_float(r["val_n"], 0)
        n_lock = safe_float(r["lockbox_n"], 0)
        sum_train = safe_float(r["train_sum_pnl"], 0)
        sum_val = safe_float(r["val_sum_pnl"], 0)
        sum_lock = safe_float(r["lockbox_sum_pnl"], 0)
        days_t = safe_float(r["train_n_days"], 14)
        days_v = safe_float(r["val_n_days"], 7)
        days_l = safe_float(r["lockbox_n_days"], 4)
        total_n = n_train + n_val + n_lock
        total_sum = sum_train + sum_val + sum_lock
        total_days = days_t + days_v + days_l
        row["n_total"] = int(total_n) if total_n > 0 else None
        # weighted WR
        wins = (
            safe_float(r["train_wins"], 0)
            + safe_float(r["val_wins"], 0)
            + safe_float(r["lockbox_wins"], 0)
        )
        row["wr_total"] = (wins / total_n * 100) if total_n > 0 else None
        row["dollar_per_trade"] = (total_sum / total_n) if total_n > 0 else None
        row["sum_pnl_28d"] = normalize_28d(total_sum, total_days)
        row["max_DD"] = safe_float(r["lockbox_max_DD"])
        row["max_loss_streak"] = safe_float(r["lockbox_loss_streak"])
        row["sharpe_daily"] = safe_float(r["lockbox_sharpe_d"])
        row["n_lockbox"] = int(n_lock) if n_lock else None
        row["wr_lockbox"] = safe_float(r["lockbox_WR"]) * 100 if pd.notna(r.get("lockbox_WR")) else None
        row["dpt_lockbox"] = safe_float(r["lockbox_dpt"])
        row["sum_lockbox"] = safe_float(r["lockbox_sum_pnl"])
        row["bootstrap_p_lockbox"] = safe_float(r["lockbox_p"])
        row["oos_status"] = "PASS" if bool(r["lockbox_pass"]) else "FAIL"
        row["source_round_report"] = "SLEEVE_HUNT_15M_V2_2026_05_26.md"
        # grade
        if bool(r["lockbox_pass"]) and safe_float(r["lockbox_dpt"], 0) > 1:
            row["confidence_grade"] = "B"
        else:
            row["confidence_grade"] = "F" if not bool(r["lockbox_pass"]) else "C"
        row["deploy_status"] = "CANDIDATE" if bool(r["lockbox_pass"]) else "SKIP_NEGATIVE_PNL"
        rows.append(row)
    return pd.DataFrame(rows)


def load_walk_forward_r3(filename: str, base: str, source_md: str) -> pd.DataFrame:
    """R3 walk-forward sleeves (DRZ / QR / SMS)."""
    df = pd.read_csv(RES / filename)
    rows = []
    for i, r in df.iterrows():
        row = empty_row()
        sid = f"R3_{base}_{i:03d}"
        row["sleeve_id"] = sid
        row["discovery_round"] = "R3"
        row["base_strategy"] = base
        row["asset"] = r.get("asset", "UNKNOWN")
        row["tf"] = str(r.get("tf", "5m")).replace("s6_", "").replace("v15m", "15m")
        row["offset_range_s"] = r.get("offset_bin", "")
        gs = []
        for k in ("rule", "added_qr_gate", "base_stack", "sleeve_label", "added_sms_gate"):
            if k in r and pd.notna(r[k]):
                gs.append(str(r[k]))
        row["gate_stack"] = "&".join(gs)
        # Use full_n if available else train+test
        n_full = safe_float(r.get("full_n"), None)
        if n_full is None:
            n_full = (safe_float(r.get("train_n"), 0) + safe_float(r.get("test_n"), 0))
        row["n_total"] = int(n_full) if n_full else None
        row["wr_total"] = safe_float(r.get("full_WR", r.get("WR_test"))) * 100 if pd.notna(r.get("full_WR", r.get("WR_test"))) else None
        row["dollar_per_trade"] = safe_float(r.get("full_dpt", r.get("dpt_test")))
        row["sum_pnl_28d"] = normalize_28d(r.get("full_sum", r.get("sum_test")), 28)
        # lockbox: test_*
        row["n_lockbox"] = int(safe_float(r.get("test_n"), 0)) if pd.notna(r.get("test_n")) else None
        row["wr_lockbox"] = safe_float(r.get("WR_test", r.get("test_WR"))) * 100 if pd.notna(r.get("WR_test", r.get("test_WR"))) else None
        row["dpt_lockbox"] = safe_float(r.get("dpt_test", r.get("test_dpt")))
        row["sum_lockbox"] = safe_float(r.get("test_sum", r.get("sum_test")))
        # status from walk-forward sign_pass / passes_g4 / passed
        pass_flag = bool(r.get("passed", r.get("sign_pass", r.get("passes_g4", False))))
        row["oos_status"] = "PASS" if pass_flag else "FAIL"
        row["bootstrap_p_lockbox"] = safe_float(r.get("p_value"))
        row["source_round_report"] = source_md
        row["confidence_grade"] = "B" if pass_flag else "F"
        row["deploy_status"] = "CANDIDATE" if pass_flag else "SKIP_NEGATIVE_PNL"
        rows.append(row)
    return pd.DataFrame(rows)


def load_master_combinatorial() -> pd.DataFrame:
    """R6 LL master combinatorial deployable (14 lockbox-passing combos)."""
    df = pd.read_csv(RES / "master_combinatorial_deployable.csv")
    rows = []
    for _, r in df.iterrows():
        row = empty_row()
        row["sleeve_id"] = f"R6_COMB_{r['sleeve_id'].replace('|', '_').replace('&', '+').replace('/', '_')[:80]}"
        row["discovery_round"] = "R6"
        row["asset"] = r["asset"]
        row["tf"] = r["tf"]
        row["offset_range_s"] = r["offset_bin"]
        # base from sleeve_id prefix
        base = str(r["sleeve_id"]).split("|")[0]
        row["base_strategy"] = base
        row["gate_stack"] = str(r["stack"])
        row["n_total"] = int(r["n_total"]) if pd.notna(r["n_total"]) else None
        # full WR from train+val+lock weighted
        tn, vn, ln = r["train_n"], r["val_n"], r["lock_n"]
        twr = r["train_wr"] / 100
        vwr = r["val_wr"] / 100
        lwr = r["lock_wr"] / 100
        totn = tn + vn + ln
        if totn > 0:
            row["wr_total"] = (twr * tn + vwr * vn + lwr * ln) / totn * 100
            row["dollar_per_trade"] = (r["train_sum"] + r["val_sum"] + r["lock_sum"]) / totn
            row["sum_pnl_28d"] = normalize_28d(r["train_sum"] + r["val_sum"] + r["lock_sum"], 32)
        row["n_lockbox"] = int(ln) if pd.notna(ln) else None
        row["wr_lockbox"] = r["lock_wr"]
        row["dpt_lockbox"] = safe_float(r["lock_pt"])
        row["sum_lockbox"] = safe_float(r["lock_sum"])
        row["bootstrap_p_lockbox"] = safe_float(r["boot_p"])
        row["oos_status"] = "PASS" if (safe_float(r["lock_pt"], 0) > 0 and safe_float(r["boot_p"], 1) < 0.05) else "FAIL"
        row["source_round_report"] = "MASTER_COMBINATORIAL_2026_05_26.md"
        if row["oos_status"] == "PASS" and (row["dpt_lockbox"] or 0) > 2 and (row["sum_lockbox"] or 0) > 1000:
            row["confidence_grade"] = "A"
        elif row["oos_status"] == "PASS":
            row["confidence_grade"] = "B"
        else:
            row["confidence_grade"] = "F"
        row["deploy_status"] = "CANDIDATE"
        row["notes"] = f"depth={r['depth']} method={r['method']} lift_pt=${safe_float(r['lift_lock_pt'], 0):.2f}"
        rows.append(row)
    return pd.DataFrame(rows)


def load_vpin_hawkes_r5() -> pd.DataFrame:
    """R5 Hawkes validation HA (52/54 pass per spec)."""
    df = pd.read_csv(RES / "vpin_hawkes_validation_HA.csv")
    rows = []
    for _, r in df.iterrows():
        row = empty_row()
        sid = f"R5_hawkes_{r['asset']}_{r['tf']}_off{int(r['offset_s'])}"
        row["sleeve_id"] = sid
        row["discovery_round"] = "R5"
        row["asset"] = r["asset"]
        row["tf"] = r["tf"]
        row["offset_range_s"] = str(int(r["offset_s"]))
        row["base_strategy"] = "hawkes"
        row["gate_stack"] = "__hawkes_imb_with__"
        # weights
        tn = safe_float(r["n_train"], 0)
        vn = safe_float(r["n_val"], 0)
        ln = safe_float(r["n_lock"], 0)
        tw = safe_float(r["WR_train"], 0)
        vw = safe_float(r["WR_val"], 0)
        lw = safe_float(r["WR_lock"], 0)
        totn = tn + vn + ln
        row["n_total"] = int(totn) if totn else None
        if totn > 0:
            row["wr_total"] = (tw * tn + vw * vn + lw * ln) / totn * 100
            row["dollar_per_trade"] = (r["sum_train"] + r["sum_val"] + r["sum_lock"]) / totn
            row["sum_pnl_28d"] = normalize_28d(r["sum_train"] + r["sum_val"] + r["sum_lock"], 32)
        row["n_lockbox"] = int(ln) if ln else None
        row["wr_lockbox"] = lw * 100 if pd.notna(lw) else None
        row["dpt_lockbox"] = safe_float(r["dpt_lock"])
        row["sum_lockbox"] = safe_float(r["sum_lock"])
        row["bootstrap_p_lockbox"] = None  # not in this file
        row["oos_status"] = "PASS" if bool(r["PASS"]) else "FAIL"
        row["source_round_report"] = "VPIN_HAWKES_2026_05_26.md"
        if bool(r["PASS"]) and (safe_float(r["sum_lock"], 0) > 100):
            row["confidence_grade"] = "B"
        elif bool(r["PASS"]):
            row["confidence_grade"] = "C"
        else:
            row["confidence_grade"] = "F"
        row["deploy_status"] = "CANDIDATE" if bool(r["PASS"]) else "SKIP_NEGATIVE_PNL"
        rows.append(row)
    return pd.DataFrame(rows)


def load_ws_poly2_r7() -> pd.DataFrame:
    """R7 TT/WW WS-poly2 sleeves (7 weighted-scoring sleeves)."""
    df = pd.read_csv(WS_DIR / "ws_poly2_per_sleeve_summary.csv")
    # Pull overlap from ws_pairwise_overlap if present
    rows = []
    for _, r in df.iterrows():
        row = empty_row()
        slv = r["sleeve"]
        row["sleeve_id"] = f"R7_WS_{slv}"
        row["discovery_round"] = "R7"
        # Parse asset/tf/offset from name
        if "BTC" in slv:
            row["asset"] = "BTC"
        elif "ETH" in slv:
            row["asset"] = "ETH"
        elif "SOL" in slv:
            row["asset"] = "SOL"
        row["tf"] = "5m"
        # offset
        if "60_150" in slv:
            row["offset_range_s"] = "60-150"
        elif "150_240" in slv:
            row["offset_range_s"] = "150-240"
        else:
            row["offset_range_s"] = "all"
        row["base_strategy"] = "WS_Logistic_Poly2"
        row["gate_stack"] = "weighted_score>thr (52 features, ridge+L1+L2+poly2)"
        row["n_total"] = int(r["n_full"])
        row["wr_total"] = safe_float(r["wr_full"]) * 100 if pd.notna(r["wr_full"]) else None
        row["dollar_per_trade"] = (r["sum_pnl_full"] / r["n_full"]) if r["n_full"] else None
        # NOTE: ws_poly2 numbers per WW use 32d full window;
        # also the WW report cautions ~4d lockbox extrapolation is fragile.
        row["sum_pnl_28d"] = normalize_28d(r["sum_pnl_full"], 32)
        row["n_lockbox"] = int(r["n_lock"]) if pd.notna(r["n_lock"]) else None
        row["wr_lockbox"] = r["wr_pct_lock"]
        row["dpt_lockbox"] = (r["sum_pnl_lock"] / r["n_lock"]) if r["n_lock"] else None
        row["sum_lockbox"] = safe_float(r["sum_pnl_lock"])
        row["oos_status"] = "PASS"  # all 7 sleeves passed per WW report
        row["source_round_report"] = "WS_POLY2_DEDUP_VALIDATION_2026_05_26.md"
        # WS sleeves have pairwise Jaccard <0.30 → high marginal value
        # Conservatively downgrade to B due to 4d lockbox concern
        row["confidence_grade"] = "B"
        row["deploy_status"] = "PAPER_FIRST"  # per WW recommendation
        row["notes"] = "WS-poly2 — Logistic+Poly2 weighted scoring. 4d lockbox extrap fragile; needs 2nd lockbox. Pairwise Jaccard<0.30 → orthogonal alpha."
        row["slug_overlap_pct_with_primary"] = 0.0  # max pairwise 0.29
        rows.append(row)
    return pd.DataFrame(rows)


def load_threshold_optimized_r7() -> pd.DataFrame:
    """R7 RR threshold sweep — only the strict val-optimal pass."""
    rows = []
    # Per RR report: only S7_btc_5m_base + book_slope_steep@0.25 passes strict
    row = empty_row()
    row["sleeve_id"] = "R7_RR_S7_btc_5m_book_slope_steep_at_0.25"
    row["discovery_round"] = "R7"
    row["asset"] = "BTC"
    row["tf"] = "5m"
    row["offset_range_s"] = "120-300"
    row["base_strategy"] = "S7"
    row["gate_stack"] = "g_cci_with&g_stoch_with&g_rf_with&g_tr_above_ema50&g_tr_above_ema200&g_ribbon_agrees&book_slope_steep@0.25 (val-optimal)"
    row["n_total"] = None
    row["wr_total"] = None
    row["dollar_per_trade"] = 14.91
    row["sum_pnl_28d"] = None  # too small
    row["n_lockbox"] = 24
    row["wr_lockbox"] = None
    row["dpt_lockbox"] = 14.91
    row["sum_lockbox"] = 358
    row["bootstrap_p_lockbox"] = 0.072
    row["oos_status"] = "MARGINAL"  # p=0.072 borderline
    row["source_round_report"] = "THRESHOLD_SWEEPS_2026_05_26.md"
    row["confidence_grade"] = "C"  # small n=24 lockbox
    row["deploy_status"] = "PAPER_FIRST"
    row["notes"] = "val-optimal threshold (not lockbox-optimal — avoids overfit). p=0.072 marginal."
    rows.append(row)

    # The 2nd entry from R7 RR notes — ETH S6 book_slope_steep@0.4 (lock-opt, overfit-prone)
    row = empty_row()
    row["sleeve_id"] = "R7_RR_ETH_S6_60_150_book_slope_steep_at_0.4_LOCK_OPT"
    row["discovery_round"] = "R7"
    row["asset"] = "ETH"
    row["tf"] = "5m"
    row["offset_range_s"] = "60-150"
    row["base_strategy"] = "S6"
    row["gate_stack"] = "g_cci_with&g_bb_pos_with&g_ribbon_agrees+book_slope_steep@0.4 (lock-opt)"
    row["dpt_lockbox"] = 10.01
    row["sum_lockbox"] = 1972
    row["n_lockbox"] = 197
    row["bootstrap_p_lockbox"] = 0.002
    row["oos_status"] = "PASS"
    row["source_round_report"] = "THRESHOLD_SWEEPS_2026_05_26.md"
    row["confidence_grade"] = "C"  # lockbox-optimized → overfit risk
    row["deploy_status"] = "CANDIDATE"
    row["notes"] = "LOCKBOX-OPTIMIZED — overfit risk. Use val-optimal in production."
    rows.append(row)

    # R7 SS: direction-asymmetric S15 60-150 trend stack
    row = empty_row()
    row["sleeve_id"] = "R7_SS_S15_60_150_tr_above_ema50_ribbon_hurst"
    row["discovery_round"] = "R7"
    row["asset"] = "BTC"
    row["tf"] = "5m"
    row["offset_range_s"] = "60-150"
    row["base_strategy"] = "S15"
    row["gate_stack"] = "g_tr_above_ema50&g_ribbon_agrees&g_hurst_trending"
    row["n_total"] = 1543 + 1491  # UP+DOWN
    row["wr_total"] = 78.4
    total_sum_32 = 7623 + 7313
    total_n = 1543 + 1491
    row["dollar_per_trade"] = total_sum_32 / total_n
    # UP=$7,623/n=1,543; DOWN=$7,313/n=1,491
    row["sum_pnl_28d"] = normalize_28d(total_sum_32, 32)
    row["bootstrap_p_lockbox"] = 0.000
    row["oos_status"] = "PASS"
    row["source_round_report"] = "DIRECTION_ASYMMETRIC_GATES_2026_05_26.md"
    row["confidence_grade"] = "A"
    row["deploy_status"] = "CANDIDATE"
    row["notes"] = "Symmetric stack both directions p=0. UP n=1543 sum=$7623 WR=79.3%; DN n=1491 sum=$7313 WR=77.5%"
    rows.append(row)

    # R7 UU: BTC S15 + Asia-session
    row = empty_row()
    row["sleeve_id"] = "R7_UU_BTC_S15_150_240_ema800_Asia_session"
    row["discovery_round"] = "R7"
    row["asset"] = "BTC"
    row["tf"] = "5m"
    row["offset_range_s"] = "150-240"
    row["base_strategy"] = "S15"
    row["gate_stack"] = "g_tr_above_ema800&Asia_session(Tokyo|Sydney|HK)"
    row["n_lockbox"] = 654
    row["dpt_lockbox"] = 2.95
    row["sum_lockbox"] = 654 * 2.95
    row["bootstrap_p_lockbox"] = 0.001
    row["oos_status"] = "PASS"
    row["source_round_report"] = "SESSION_CROSS_ASSET_REGIME_2026_05_26.md"
    row["confidence_grade"] = "B"
    row["deploy_status"] = "PAPER_FIRST"
    row["notes"] = "Asia-session filter on existing S15 ema800 sleeve. +$0.25/tr lift over baseline."
    rows.append(row)

    return pd.DataFrame(rows)


def load_r5_microprice() -> pd.DataFrame:
    """R5 microprice sleeves (univ_5m_rf_ribbon already in manifest).
    Add the rest from MICROPRICE report.
    """
    rows = []
    # Most R5 microprice sleeves are already in final_deploy_manifest.csv;
    # this is just a placeholder for any orphans.
    return pd.DataFrame(rows)


def load_xfi_r6() -> pd.DataFrame:
    """R6 OO cross-feature: XF-I SOL sleeves (3 new non-overlapping)."""
    rows = []
    for spec in (
        dict(
            sid="R6_XFI_SOL_15m_off240_UP",
            asset="SOL",
            tf="15m",
            offset_range_s="240",
            n=56,
            wr=78.6,
            dpt=6.31,
            sum_lock=56 * 6.31,
            p=0.008,
            grade="B",
            notes="Cross-feature: sign(mp_skew)==sign(hawkes_imb) ∧ |hawkes_imb|>0.1 (XF-I family). 0% overlap with S6/Hawkes/LM.",
        ),
        dict(
            sid="R6_XFI_SOL_15m_off240_BOTH",
            asset="SOL",
            tf="15m",
            offset_range_s="240",
            n=148,
            wr=None,
            dpt=None,
            sum_lock=None,
            p=None,
            grade="B",
            notes="XF-I both directions combined (UP+DOWN). Per OO report.",
        ),
        dict(
            sid="R6_DISAGR_HAWKES_DN_SOL_5m_off210",
            asset="SOL",
            tf="5m",
            offset_range_s="210",
            n=35,
            wr=100.0,
            dpt=6.54,
            sum_lock=35 * 6.54,
            p=0.001,
            grade="C",  # n=35 tiny
            notes="DISAGR-HAWKES DN narrow cell. n=35 tiny — PAPER_FIRST only.",
        ),
    ):
        row = empty_row()
        row["sleeve_id"] = spec["sid"]
        row["discovery_round"] = "R6"
        row["asset"] = spec["asset"]
        row["tf"] = spec["tf"]
        row["offset_range_s"] = spec["offset_range_s"]
        row["base_strategy"] = "cross_feature_XFI"
        row["gate_stack"] = "sign(mp_skew)==sign(hawkes_imb) ∧ |hawkes_imb|>0.1"
        row["n_total"] = spec["n"]
        row["n_lockbox"] = spec["n"]
        row["wr_lockbox"] = spec["wr"]
        row["dpt_lockbox"] = spec["dpt"]
        row["sum_lockbox"] = spec["sum_lock"]
        row["bootstrap_p_lockbox"] = spec["p"]
        row["oos_status"] = "PASS"
        row["source_round_report"] = "CROSS_FEATURE_RULES_2026_05_26.md"
        row["confidence_grade"] = spec["grade"]
        row["deploy_status"] = "PAPER_FIRST"
        row["notes"] = spec["notes"]
        row["slug_overlap_pct_with_primary"] = 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def load_r1_other_sleeves() -> pd.DataFrame:
    """Some R1 strategy sleeves: S2 Fade Momo, S5 z-contra, spike entry."""
    rows = []
    # S2 Fade Momo — fade_momo_5m.csv (just the deployable ones, mag>=2)
    fmm = pd.read_csv(RES / "fade_momo_5m.csv")
    for _, r in fmm.iterrows():
        if not bool(r["deployable"]):
            continue
        row = empty_row()
        row["sleeve_id"] = f"R1_S2_fade_momo_{r['asset']}_mag{r['mag_threshold']}_{r['gate']}"
        row["discovery_round"] = "R1"
        row["asset"] = r["asset"]
        row["tf"] = "5m"
        row["offset_range_s"] = "60-300"
        row["base_strategy"] = "S2_fade_momo"
        row["gate_stack"] = f"mag>={r['mag_threshold']}+{r['gate']}"
        row["n_total"] = int(r["n"])
        row["wr_total"] = r["wr"] * 100
        row["dollar_per_trade"] = safe_float(r["mean_pnl_usd"])
        row["sum_pnl_28d"] = normalize_28d(r["sum_pnl_usd"], 22)  # ~22d window per per_sleeve_catalog
        row["max_DD"] = safe_float(r["max_consec_loss_usd"])
        row["oos_status"] = "PASS"
        row["source_round_report"] = "PER_SLEEVE_CATALOG_2026_05_26.md"
        row["confidence_grade"] = "B"
        row["deploy_status"] = "PAPER_FIRST"
        row["notes"] = "Contrarian — fires on momo exhaustion. Disjoint from momo sleeves."
        rows.append(row)
    return pd.DataFrame(rows)


# --- Main builder ---------------------------------------------------------

def main() -> pd.DataFrame:
    """Merge all sources into a single master catalog."""
    parts = []
    print("Loading deploy manifest...")
    parts.append(load_deploy_manifest())
    print("Loading full window all sleeves (R1-R4)...")
    parts.append(load_full_window_all_sleeves())
    print("Loading sleeve_hunt_15m_v2 (R4)...")
    parts.append(load_sleeve_hunt_15m_v2())
    print("Loading R3 DRZ walk-forward...")
    parts.append(load_walk_forward_r3("drz_walk_forward.csv", "DRZ", "DRZ_BACKTEST_2026_05_26.md"))
    print("Loading R3 QR walk-forward...")
    parts.append(load_walk_forward_r3("qr_walk_forward.csv", "QR", "QR_BACKTEST_2026_05_26.md"))
    print("Loading R3 SMS walk-forward...")
    parts.append(load_walk_forward_r3("sms_walk_forward.csv", "SMS", "SMS_BACKTEST_2026_05_26.md"))
    print("Loading R6 master combinatorial...")
    parts.append(load_master_combinatorial())
    print("Loading R5 VPIN-Hawkes HA validation...")
    parts.append(load_vpin_hawkes_r5())
    print("Loading R7 WS-poly2 sleeves...")
    parts.append(load_ws_poly2_r7())
    print("Loading R7 threshold-optimized + asymmetric + session...")
    parts.append(load_threshold_optimized_r7())
    print("Loading R6 XF-I SOL sleeves...")
    parts.append(load_xfi_r6())
    print("Loading R1 S2 fade momo...")
    parts.append(load_r1_other_sleeves())

    master = pd.concat(parts, ignore_index=True)
    # de-dup by sleeve_id, preferring R6 manifest, then R7, then R5, then R4, etc.
    round_pri = {"R6": 1, "R7": 2, "R5": 3, "R4": 4, "R3": 5, "R2": 6, "R1": 7, "R1-R5": 8}
    master["_pri"] = master["discovery_round"].map(round_pri).fillna(9)
    master = master.sort_values(["sleeve_id", "_pri"])
    master = master.drop_duplicates("sleeve_id", keep="first").drop(columns="_pri")
    # Apply asymmetric overlay: deploy_status from manifest takes precedence
    # already covered by load_deploy_manifest going first.
    master = master.reset_index(drop=True)
    # Sort by discovery_round then sum_pnl_28d desc
    master = master.sort_values(
        ["deploy_status", "sum_pnl_28d"], ascending=[True, False], na_position="last"
    ).reset_index(drop=True)
    return master


if __name__ == "__main__":
    df = main()
    print(f"\nMaster catalog rows: {len(df)}")
    print("\nBy discovery_round:")
    print(df["discovery_round"].value_counts())
    print("\nBy deploy_status:")
    print(df["deploy_status"].value_counts())
    print("\nBy confidence_grade:")
    print(df["confidence_grade"].value_counts())
    print("\nBy (asset, tf):")
    print(df.groupby(["asset", "tf"]).size())
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved: {OUT_CSV}")
