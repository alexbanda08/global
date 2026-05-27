"""
Regime-conditional gate-stack optimizer.

Goal: for each top sleeve, find the OPTIMAL gate stack PER REGIME
(trending_up / trending_dn / ranging), then assemble a state-machine
sleeve that picks the right stack at fire time.

Inputs:
  data/v4/canonical/_results/master_gate_features_v2.parquet  (77,906 fires x 37 gate cols)
  data/v4/canonical/_results/regime_panel_5m.parquet
  data/v4/canonical/_results/regime_panel_15m.parquet

Outputs:
  data/v4/canonical/_results/regime_conditional_optimal_stacks.csv
  data/v4/canonical/_results/regime_state_machine_sleeves.csv
  data/v4/canonical/_results/regime_distribution_per_sleeve.csv
  data/v4/canonical/_results/regime_gate_lift_per_regime.csv
  data/v4/canonical/_results/regime_transition_signal.csv
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT = RES

MASTER = RES / "master_gate_features_v2.parquet"
REGIME_5M = RES / "regime_panel_5m.parquet"
REGIME_15M = RES / "regime_panel_15m.parquet"

# -------- splits (UTC microseconds) --------
SPLIT_TRAIN_END = pd.Timestamp("2026-05-14 00:00", tz="UTC").value // 1000
SPLIT_VAL_END = pd.Timestamp("2026-05-21 00:00", tz="UTC").value // 1000
# train: May 01 -> May 14 (14d). val: May 14 -> May 21 (7d). lockbox: May 21 -> May 25 (~4.8d)

MIN_N_PER_REGIME = 50      # need at least 50 fires per regime to call it stable
MIN_N_STACK = 30           # minimum surviving n during greedy
DAYS_LOCKBOX = 4.8


def load_master() -> pd.DataFrame:
    df = pd.read_parquet(MASTER)
    # decompose sleeve into fam/offset/baseline_stack
    parts = df["sleeve_id"].str.split("|", expand=True)
    df["fam"] = parts[0]
    df["offset_bin_raw"] = parts[1]
    df["baseline_stack"] = parts[2]
    df["fire_us"] = df["fire_us"].astype("int64")
    # split flag
    df["split"] = np.where(
        df["fire_us"] < SPLIT_TRAIN_END, "train",
        np.where(df["fire_us"] < SPLIT_VAL_END, "val", "lockbox")
    )
    return df


def load_regime_panel() -> dict[str, pd.DataFrame]:
    out = {}
    for tf, p in [("5m", REGIME_5M), ("15m", REGIME_15M)]:
        d = pd.read_parquet(p)
        d = d.sort_values(["asset", "ts_us"]).reset_index(drop=True)
        out[tf] = d
    return out


def attach_regime(df: pd.DataFrame, regime_panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Look up regime_label per fire by (asset, ts_us asof <= fire_us / 1e6 in us).
    Regime panel ts_us is bar OPEN, so we want the bar whose close occurred BEFORE the fire.
    A 5m bar at ts_us opens at ts_us, closes at ts_us + 300_000_000.
    Causal rule: use last bar whose CLOSE <= fire_us i.e. ts_us + window <= fire_us.
    """
    out = []
    for tf, panel in regime_panels.items():
        window_us = 300_000_000 if tf == "5m" else 900_000_000
        # 'close' time of each regime bar
        panel = panel.copy()
        panel["close_us"] = panel["ts_us"] + window_us
        # for each asset, get a sorted close_us array
        for asset in ["BTC", "ETH", "SOL"]:
            sub = df[(df["asset"] == asset) & (df["tf"] == tf)]
            if sub.empty:
                continue
            pn = panel[panel["asset"] == asset].sort_values("close_us").reset_index(drop=True)
            if pn.empty:
                continue
            idx = pn["close_us"].searchsorted(sub["fire_us"].values, side="right") - 1
            idx = np.clip(idx, 0, len(pn) - 1)
            tmp = sub.copy()
            tmp["regime_label"] = pn["regime_label"].values[idx]
            tmp["regime_score"] = pn["regime_score"].values[idx]
            # previous regime (for transition signal): regime at fire_us - 300s
            prev_target = sub["fire_us"].values - 300_000_000
            pidx = pn["close_us"].searchsorted(prev_target, side="right") - 1
            pidx = np.clip(pidx, 0, len(pn) - 1)
            tmp["regime_prev_5m"] = pn["regime_label"].values[pidx]
            out.append(tmp)
    if not out:
        return pd.DataFrame()
    res = pd.concat(out, ignore_index=True)
    return res


# Gates we'll evaluate as binary filters. From master panel.
GATE_COLS = [
    "g_hurst_trending", "g_hurst_reverting",
    "g_rf_with", "g_ribbon_agrees", "g_stoch_with", "g_mfi_with", "g_cci_with",
    "g_bb_pos_with", "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_tr_above_pp", "g_tr_stack_with", "g_tr_within_adr", "g_tight_ribbon",
    "g_within_dev", "g_dev_extreme", "g_markov_with", "g_vol_expanding",
    "g_vol_contracting", "g_vol_high", "g_book_slope_steep_against",
    "g_trend_slope_with", "g_trend_slope_strong_with", "g_imb5_strong_with",
    "g_queue_top_high", "g_imb_change_with", "g_vwap_ge_50_le_85",
    "g_mp_no_extreme", "g_mp_change_with", "g_mp_skew_with",
    "g_lm_high_stat", "g_lm_extreme_against", "g_hawkes_imbalance_with",
    "g_flow_with_and_no_whale", "g_coinbase_basis_extreme_against",
    "g_hl_liq_cascade_with",
]


# ---------- choose top sleeves ----------
def pick_top_sleeves(df: pd.DataFrame, top_n: int = 7) -> pd.DataFrame:
    """
    Top sleeves are (fam, asset, offset_bin_raw) groups by sum_pnl
    with n >= 200 so per-regime splits can be stable.
    """
    g = df.groupby(["fam", "asset", "offset_bin_raw"]).agg(
        n=("won_int", "count"),
        wr=("won_int", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).reset_index()
    g = g[g["n"] >= 200].sort_values("sum_pnl", ascending=False)
    # also map a friendly name reminiscent of user's targets
    def friendly(row):
        fam = row.fam
        # s6_5m -> poly_updown_<asset>_5m_s6_hybrid_v1
        if "_5m" in fam:
            tag = fam.replace("_5m", "")
            return f"poly_updown_{row.asset.lower()}_5m_{tag}_off{row.offset_bin_raw}"
        return f"poly_updown_{row.asset.lower()}_15m_{fam}_off{row.offset_bin_raw}"
    g["sleeve_name"] = g.apply(friendly, axis=1)
    return g.head(top_n).reset_index(drop=True)


# ---------- greedy stack search ----------
def greedy_search(sub: pd.DataFrame, candidate_gates: list[str], min_n: int = MIN_N_STACK,
                  max_depth: int = 6) -> dict:
    """
    Greedy stepwise: each round pick the gate (or its inverse) that maximizes sum_pnl
    while keeping n >= min_n. Stop when no gate improves it.
    Returns dict with stack list, n, wr, mean_pnl, sum_pnl.
    Stack items: (gate_col, sign)  sign=+1 require gate==1, -1 require gate==0.
    """
    mask = np.ones(len(sub), dtype=bool)
    stack = []
    best_sum = sub["pnl_legacy_usd"].sum()
    n0 = int(mask.sum())
    wr0 = float(sub["won_int"].mean()) if n0 else 0.0
    if n0 < min_n:
        return {"stack": [], "n": n0, "wr": wr0, "mean_pnl": 0.0, "sum_pnl": 0.0}

    available = list(candidate_gates)
    while len(stack) < max_depth and available:
        best_gain = 0.0
        best_choice = None
        cur_sub = sub[mask]
        for g in available:
            vals = _gate_to_float(cur_sub[g])
            # gate == 1 (require gate true)
            m1 = vals == 1.0
            n1 = int(m1.sum())
            # gate == 0 (require gate false)
            m0 = vals == 0.0
            n0c = int(m0.sum())
            for sub_mask, sign, n_here in [(m1, +1, n1), (m0, -1, n0c)]:
                if n_here < min_n:
                    continue
                new_sum = cur_sub.loc[sub_mask, "pnl_legacy_usd"].sum()
                gain = new_sum - best_sum
                if gain > best_gain + 1e-9:
                    best_gain = gain
                    best_choice = (g, sign, sub_mask, n_here, new_sum)
        if best_choice is None:
            break
        g, sign, sub_mask, n_here, new_sum = best_choice
        # apply to global mask
        new_mask = np.zeros(len(sub), dtype=bool)
        idxs = np.where(mask)[0][sub_mask]
        new_mask[idxs] = True
        mask = new_mask
        stack.append((g, sign))
        best_sum = new_sum
        available.remove(g)

    final = sub[mask]
    n = int(len(final))
    wr = float(final["won_int"].mean()) if n else 0.0
    mean_pnl = float(final["pnl_legacy_usd"].mean()) if n else 0.0
    return {"stack": stack, "n": n, "wr": wr, "mean_pnl": mean_pnl, "sum_pnl": float(best_sum)}


def _gate_to_float(arr) -> np.ndarray:
    """Convert masked Int8/Int64/float gate cols to float ndarray (NaN preserved)."""
    if hasattr(arr, "to_numpy"):
        return arr.to_numpy(dtype="float64", na_value=np.nan)
    return np.asarray(arr, dtype="float64")


def apply_stack(sub: pd.DataFrame, stack: list[tuple]) -> pd.DataFrame:
    mask = np.ones(len(sub), dtype=bool)
    for g, sign in stack:
        v = _gate_to_float(sub[g].values if not hasattr(sub[g], "to_numpy") else sub[g])
        if sign > 0:
            mask &= (v == 1.0)
        else:
            mask &= (v == 0.0)
    return sub[mask]


def fmt_stack(stack: list[tuple]) -> str:
    return "&".join(f"{g}={'1' if s>0 else '0'}" for g, s in stack)


def bootstrap_p(values: np.ndarray, n_boot: int = 500, seed: int = 17) -> float:
    """Two-sided bootstrap p-value of mean!=0 via sign flips."""
    if len(values) == 0:
        return 1.0
    rng = np.random.default_rng(seed)
    flips = rng.choice([-1, 1], size=(n_boot, len(values)))
    boot_means = (flips * values).mean(axis=1)
    obs = float(values.mean())
    return float(np.mean(np.abs(boot_means) >= abs(obs)))


# ===================== TASK 1 — stratify regime per fire =====================
def task1_regime_distribution(df_with_regime: pd.DataFrame, top_sleeves: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in top_sleeves.iterrows():
        m = (df_with_regime["fam"] == row.fam) & (df_with_regime["asset"] == row.asset) & \
            (df_with_regime["offset_bin_raw"] == row.offset_bin_raw)
        sub = df_with_regime[m]
        if sub.empty:
            continue
        by = sub.groupby("regime_label").size()
        for reg in ["trending_up", "trending_dn", "ranging"]:
            n = int(by.get(reg, 0))
            rows.append({
                "sleeve_name": row.sleeve_name, "fam": row.fam, "asset": row.asset,
                "offset_bin": row.offset_bin_raw, "regime": reg, "n_fires": n,
                "total": int(len(sub)), "pct": round(100 * n / max(1, len(sub)), 1),
            })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "regime_distribution_per_sleeve.csv", index=False)
    return res


# ===================== TASK 2 — per-regime gate-stack optimization =====================
def task2_per_regime_optimization(df_with_regime: pd.DataFrame, top_sleeves: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, row in top_sleeves.iterrows():
        m = (df_with_regime["fam"] == row.fam) & (df_with_regime["asset"] == row.asset) & \
            (df_with_regime["offset_bin_raw"] == row.offset_bin_raw)
        sleeve_sub = df_with_regime[m].copy()
        if sleeve_sub.empty:
            continue
        for regime in ["trending_up", "trending_dn", "ranging"]:
            sub_reg = sleeve_sub[sleeve_sub["regime_label"] == regime]
            if len(sub_reg) < MIN_N_PER_REGIME:
                rows.append({
                    "sleeve_name": row.sleeve_name, "fam": row.fam, "asset": row.asset,
                    "offset_bin": row.offset_bin_raw, "regime": regime,
                    "n_baseline": len(sub_reg), "wr_baseline": float(sub_reg["won_int"].mean()) if len(sub_reg) else 0.0,
                    "sum_pnl_baseline": float(sub_reg["pnl_legacy_usd"].sum()),
                    "stack": "INSUFFICIENT_N",
                    "n_opt": 0, "wr_opt": 0.0, "mean_pnl_opt": 0.0, "sum_pnl_opt": 0.0,
                    "n_lockbox": 0, "sum_pnl_lockbox": 0.0,
                })
                continue
            # train on TRAIN portion only
            train = sub_reg[sub_reg["split"] == "train"]
            if len(train) < MIN_N_STACK * 2:
                # fall back to train+val
                train = sub_reg[sub_reg["split"].isin(["train", "val"])]
            if len(train) < MIN_N_STACK:
                continue
            res = greedy_search(train, GATE_COLS, min_n=MIN_N_STACK, max_depth=6)
            # eval on val and lockbox
            val_sub = sub_reg[sub_reg["split"] == "val"]
            lockbox_sub = sub_reg[sub_reg["split"] == "lockbox"]
            val_filtered = apply_stack(val_sub, res["stack"])
            lockbox_filtered = apply_stack(lockbox_sub, res["stack"])
            rows.append({
                "sleeve_name": row.sleeve_name, "fam": row.fam, "asset": row.asset,
                "offset_bin": row.offset_bin_raw, "regime": regime,
                "n_baseline": int(len(sub_reg)),
                "wr_baseline": float(sub_reg["won_int"].mean()),
                "sum_pnl_baseline": float(sub_reg["pnl_legacy_usd"].sum()),
                "stack": fmt_stack(res["stack"]) if res["stack"] else "EMPTY",
                "depth": len(res["stack"]),
                "n_train_opt": res["n"], "wr_train_opt": res["wr"],
                "sum_pnl_train_opt": res["sum_pnl"],
                "mean_pnl_train_opt": res["mean_pnl"],
                "n_val_opt": int(len(val_filtered)),
                "wr_val_opt": float(val_filtered["won_int"].mean()) if len(val_filtered) else 0.0,
                "sum_pnl_val_opt": float(val_filtered["pnl_legacy_usd"].sum()),
                "n_lockbox_opt": int(len(lockbox_filtered)),
                "wr_lockbox_opt": float(lockbox_filtered["won_int"].mean()) if len(lockbox_filtered) else 0.0,
                "sum_pnl_lockbox_opt": float(lockbox_filtered["pnl_legacy_usd"].sum()),
                "mean_pnl_lockbox_opt": float(lockbox_filtered["pnl_legacy_usd"].mean()) if len(lockbox_filtered) else 0.0,
            })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "regime_conditional_optimal_stacks.csv", index=False)
    return res


# ===================== TASK 3 — state-machine sleeves =====================
def task3_state_machine(df_with_regime: pd.DataFrame, top_sleeves: pd.DataFrame,
                        per_regime: pd.DataFrame) -> pd.DataFrame:
    """
    Assemble: for each sleeve, apply the per-regime stack found in TRAIN at fire time
    based on the regime label. Compare to:
      - baseline_all: original sleeve, no gating
      - trending_only: original sleeve, only fire when regime in {trending_up, trending_dn}
      - best_static_regime: original sleeve, only fire in single best regime (chosen on train)
    Report on each split (train/val/lockbox).
    """
    rows = []
    # build dict: (sleeve_name, regime) -> stack list
    stack_map = {}
    for _, r in per_regime.iterrows():
        key = (r["sleeve_name"], r["regime"])
        if isinstance(r["stack"], str) and r["stack"] not in ("INSUFFICIENT_N", "EMPTY", "", None):
            stk = []
            for part in r["stack"].split("&"):
                if "=" not in part:
                    continue
                g, s = part.rsplit("=", 1)
                stk.append((g, +1 if s == "1" else -1))
            stack_map[key] = stk
        else:
            stack_map[key] = []  # no filter

    for _, row in top_sleeves.iterrows():
        m = (df_with_regime["fam"] == row.fam) & (df_with_regime["asset"] == row.asset) & \
            (df_with_regime["offset_bin_raw"] == row.offset_bin_raw)
        sleeve_sub = df_with_regime[m].copy()
        if sleeve_sub.empty:
            continue

        # choose best_static_regime on TRAIN (single regime with best mean pnl)
        train = sleeve_sub[sleeve_sub["split"] == "train"]
        if not train.empty:
            br = train.groupby("regime_label")["pnl_legacy_usd"].agg(["count", "sum", "mean"])
            br = br[br["count"] >= MIN_N_PER_REGIME]
            best_static_regime = br["sum"].idxmax() if not br.empty else None
        else:
            best_static_regime = None

        # apply for each split
        for split in ["train", "val", "lockbox"]:
            split_sub = sleeve_sub[sleeve_sub["split"] == split]
            if split_sub.empty:
                continue

            # baseline
            baseline_n = len(split_sub)
            baseline_sum = float(split_sub["pnl_legacy_usd"].sum())
            baseline_wr = float(split_sub["won_int"].mean())
            baseline_mean = float(split_sub["pnl_legacy_usd"].mean())

            # trending_only
            mask_to = split_sub["regime_label"].isin(["trending_up", "trending_dn"])
            to_sub = split_sub[mask_to]
            to_n = len(to_sub)
            to_sum = float(to_sub["pnl_legacy_usd"].sum()) if to_n else 0.0
            to_wr = float(to_sub["won_int"].mean()) if to_n else 0.0
            to_mean = float(to_sub["pnl_legacy_usd"].mean()) if to_n else 0.0

            # best static regime
            if best_static_regime:
                bsr_sub = split_sub[split_sub["regime_label"] == best_static_regime]
            else:
                bsr_sub = split_sub.iloc[0:0]
            bsr_n = len(bsr_sub)
            bsr_sum = float(bsr_sub["pnl_legacy_usd"].sum()) if bsr_n else 0.0
            bsr_wr = float(bsr_sub["won_int"].mean()) if bsr_n else 0.0
            bsr_mean = float(bsr_sub["pnl_legacy_usd"].mean()) if bsr_n else 0.0

            # state-machine: per-regime stack
            sm_parts = []
            for regime in ["trending_up", "trending_dn", "ranging"]:
                stk = stack_map.get((row.sleeve_name, regime), [])
                sub_reg = split_sub[split_sub["regime_label"] == regime]
                kept = apply_stack(sub_reg, stk) if stk else sub_reg
                if not stk and (row.sleeve_name, regime) in stack_map:
                    # If we have no stack (INSUFFICIENT_N), drop this regime
                    if isinstance(per_regime.set_index(["sleeve_name","regime"]).at[(row.sleeve_name, regime), "stack"], str) and \
                       per_regime.set_index(["sleeve_name","regime"]).at[(row.sleeve_name, regime), "stack"] == "INSUFFICIENT_N":
                        continue
                sm_parts.append(kept)
            if sm_parts:
                sm = pd.concat(sm_parts, ignore_index=False)
            else:
                sm = split_sub.iloc[0:0]
            sm_n = len(sm)
            sm_sum = float(sm["pnl_legacy_usd"].sum()) if sm_n else 0.0
            sm_wr = float(sm["won_int"].mean()) if sm_n else 0.0
            sm_mean = float(sm["pnl_legacy_usd"].mean()) if sm_n else 0.0
            # bootstrap p on lockbox only
            p_boot = bootstrap_p(sm["pnl_legacy_usd"].values, n_boot=500) if split == "lockbox" else None

            rows.append({
                "sleeve_name": row.sleeve_name, "split": split, "best_static_regime_train": best_static_regime,
                "baseline_n": baseline_n, "baseline_wr": baseline_wr, "baseline_mean": baseline_mean, "baseline_sum": baseline_sum,
                "trending_only_n": to_n, "trending_only_wr": to_wr, "trending_only_mean": to_mean, "trending_only_sum": to_sum,
                "best_static_regime_n": bsr_n, "best_static_regime_wr": bsr_wr, "best_static_regime_mean": bsr_mean, "best_static_regime_sum": bsr_sum,
                "state_machine_n": sm_n, "state_machine_wr": sm_wr, "state_machine_mean": sm_mean, "state_machine_sum": sm_sum,
                "p_boot_lockbox": p_boot,
            })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "regime_state_machine_sleeves.csv", index=False)
    return res


# ===================== TASK 4 — cross-regime insights =====================
def task4_cross_regime_insights(df_with_regime: pd.DataFrame, top_sleeves: pd.DataFrame) -> pd.DataFrame:
    """
    For each (sleeve, regime, gate, sign), compute LIFT vs no-filter baseline of that regime.
    Then aggregate across sleeves to find universal vs regime-specific gates.
    Polarity reversal: same gate that lifts in trending but kills in ranging.
    """
    rows = []
    for _, row in top_sleeves.iterrows():
        m = (df_with_regime["fam"] == row.fam) & (df_with_regime["asset"] == row.asset) & \
            (df_with_regime["offset_bin_raw"] == row.offset_bin_raw)
        sleeve_sub = df_with_regime[m]
        if sleeve_sub.empty:
            continue
        for regime in ["trending_up", "trending_dn", "ranging"]:
            sub_reg = sleeve_sub[sleeve_sub["regime_label"] == regime]
            if len(sub_reg) < MIN_N_PER_REGIME:
                continue
            base_mean = float(sub_reg["pnl_legacy_usd"].mean())
            for g in GATE_COLS:
                v = _gate_to_float(sub_reg[g])
                for sign in (+1, -1):
                    mask = v == (1.0 if sign > 0 else 0.0)
                    n = int(mask.sum())
                    if n < MIN_N_STACK:
                        continue
                    mean_pnl = float(sub_reg.loc[mask, "pnl_legacy_usd"].mean())
                    rows.append({
                        "sleeve_name": row.sleeve_name, "asset": row.asset, "regime": regime,
                        "gate": g, "sign": sign, "n": n,
                        "wr": float(sub_reg.loc[mask, "won_int"].mean()),
                        "mean_pnl": mean_pnl, "base_mean": base_mean,
                        "lift": mean_pnl - base_mean,
                        "sum_pnl": float(sub_reg.loc[mask, "pnl_legacy_usd"].sum()),
                    })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "regime_gate_lift_per_regime.csv", index=False)
    return res


# ===================== TASK 6 — regime-transition signal =====================
def task6_regime_transition(df_with_regime: pd.DataFrame, top_sleeves: pd.DataFrame) -> pd.DataFrame:
    """
    Test: when the regime CHANGED in the last 5 minutes (regime_prev_5m != regime_label),
    does the bet do better/worse? Per sleeve.
    """
    rows = []
    for _, row in top_sleeves.iterrows():
        m = (df_with_regime["fam"] == row.fam) & (df_with_regime["asset"] == row.asset) & \
            (df_with_regime["offset_bin_raw"] == row.offset_bin_raw)
        sleeve_sub = df_with_regime[m]
        if sleeve_sub.empty:
            continue
        sleeve_sub = sleeve_sub.copy()
        sleeve_sub["transitioned"] = (sleeve_sub["regime_label"] != sleeve_sub["regime_prev_5m"])
        for trans in (False, True):
            sub = sleeve_sub[sleeve_sub["transitioned"] == trans]
            n = len(sub)
            if n < 30:
                continue
            rows.append({
                "sleeve_name": row.sleeve_name, "transitioned": trans, "n": n,
                "wr": float(sub["won_int"].mean()),
                "mean_pnl": float(sub["pnl_legacy_usd"].mean()),
                "sum_pnl": float(sub["pnl_legacy_usd"].sum()),
            })
        # also break out transition type (from -> to)
        trans_sub = sleeve_sub[sleeve_sub["transitioned"]]
        if len(trans_sub) >= 30:
            for (prev, cur), grp in trans_sub.groupby(["regime_prev_5m", "regime_label"]):
                if len(grp) < 30:
                    continue
                rows.append({
                    "sleeve_name": row.sleeve_name, "transitioned": True,
                    "transition_from": prev, "transition_to": cur,
                    "n": len(grp),
                    "wr": float(grp["won_int"].mean()),
                    "mean_pnl": float(grp["pnl_legacy_usd"].mean()),
                    "sum_pnl": float(grp["pnl_legacy_usd"].sum()),
                })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "regime_transition_signal.csv", index=False)
    return res


# ===================== main =====================
def main():
    print("[1] loading master + regime panels", flush=True)
    df = load_master()
    panels = load_regime_panel()

    print("[2] attaching regime labels (causal asof)", flush=True)
    df_r = attach_regime(df, panels)
    print(f"  attached {len(df_r):,} fires (vs {len(df):,} master) — drop = no panel cover")
    # quick sanity
    by_reg = df_r["regime_label"].value_counts()
    print("  regime_label distribution:", dict(by_reg))

    print("[3] picking top sleeves", flush=True)
    top = pick_top_sleeves(df_r, top_n=8)
    print(top[["sleeve_name", "n", "wr", "sum_pnl"]].to_string(index=False))

    print("[4] TASK 1 — regime distribution per sleeve", flush=True)
    d1 = task1_regime_distribution(df_r, top)
    print(d1.head(30).to_string(index=False))

    print("[5] TASK 2 — per-regime greedy gate stack optimization", flush=True)
    d2 = task2_per_regime_optimization(df_r, top)
    print(d2[["sleeve_name","regime","n_baseline","stack","n_lockbox_opt","wr_lockbox_opt","sum_pnl_lockbox_opt"]].to_string(index=False))

    print("[6] TASK 3 — state-machine sleeves", flush=True)
    d3 = task3_state_machine(df_r, top, d2)
    print(d3[d3["split"]=="lockbox"][["sleeve_name","baseline_n","baseline_sum","trending_only_sum","state_machine_n","state_machine_sum","p_boot_lockbox"]].to_string(index=False))

    print("[7] TASK 4 — cross-regime gate lift", flush=True)
    d4 = task4_cross_regime_insights(df_r, top)
    print(d4.head(15).to_string(index=False))

    print("[8] TASK 6 — regime-transition signal", flush=True)
    d6 = task6_regime_transition(df_r, top)
    print(d6.head(20).to_string(index=False))

    print("[done] outputs written to", OUT)


if __name__ == "__main__":
    main()
