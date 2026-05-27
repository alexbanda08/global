"""3-way validation: train (20d) / val (7d) / lockbox (5d) + 500-shuffle bootstrap.

Deployable: lockbox n >= 30 AND WR >= 65% AND $/tr >= +$1 AND p <= 0.05.
"""
import pandas as pd
import numpy as np
import sys
import os

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT_DIR = f"{ROOT}/strategy_lab/cross_feature_2026_05_26"
sys.path.insert(0, OUT_DIR)
from importlib.util import spec_from_file_location, module_from_spec
_spec = spec_from_file_location("score_rules", f"{OUT_DIR}/02_score_rules.py")
_score_mod = module_from_spec(_spec)
_spec.loader.exec_module(_score_mod)
define_rules = _score_mod.define_rules
compute_pnl = _score_mod.compute_pnl


WINDOW_START_US = 1777593600 * 1_000_000  # Apr 24 2026 (rough; actual window from data)


def pnl_for_rule(df, rule_fn):
    """Apply rule to df. Returns DataFrame (fire row + side + pnl) for fires that fired."""
    up_mask, dn_mask = rule_fn(df)
    up_pnl = compute_pnl(df, "UP")
    dn_pnl = compute_pnl(df, "DN")
    parts = []
    if up_mask.any():
        sub = df[up_mask].copy()
        sub["bet_side"] = "UP"
        sub["pnl"] = up_pnl[up_mask].values
        sub["won"] = (sub["outcome"] == "Up").astype(int)
        parts.append(sub[["asset", "tf", "fire_offset_s", "slug", "fire_us", "fire_offset_s", "bet_side", "won", "pnl"]])
    if dn_mask.any():
        sub = df[dn_mask].copy()
        sub["bet_side"] = "DN"
        sub["pnl"] = dn_pnl[dn_mask].values
        sub["won"] = (sub["outcome"] == "Down").astype(int)
        parts.append(sub[["asset", "tf", "fire_offset_s", "slug", "fire_us", "fire_offset_s", "bet_side", "won", "pnl"]])
    if not parts:
        return pd.DataFrame()
    out = pd.concat(parts, ignore_index=True)
    out = out.dropna(subset=["pnl"])
    return out


def bootstrap_pvalue(pnl_arr, n_shuffles=500, seed=42):
    """One-sided p-value for mean(pnl) > 0 via per-trade sign-flip."""
    if len(pnl_arr) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    obs = pnl_arr.mean()
    signs = rng.choice([-1, 1], size=(n_shuffles, len(pnl_arr)))
    shuffled_means = (signs * pnl_arr).mean(axis=1)
    p = (shuffled_means >= obs).mean()
    return float(p)


def main():
    df = pd.read_parquet(f"{OUT_DIR}/master.parquet")
    df = df[df["outcome"].isin(["Up", "Down"])].copy()

    # Time-based split: sort by fire_us
    df = df.sort_values("fire_us").reset_index(drop=True)
    t_min, t_max = int(df["fire_us"].min()), int(df["fire_us"].max())
    span_us = t_max - t_min
    print(f"Window: {pd.Timestamp(t_min, unit='us', tz='UTC')} -> {pd.Timestamp(t_max, unit='us', tz='UTC')} (span={span_us/86400/1e6:.1f} days)")

    # Splits: train 14d / val 5d / lockbox 4d (total ~23d — actual fire universe span)
    day_us = 86400_000_000
    split_train_us = t_min + 14 * day_us
    split_val_us = t_min + 19 * day_us
    train = df[df["fire_us"] < split_train_us].copy()
    val = df[(df["fire_us"] >= split_train_us) & (df["fire_us"] < split_val_us)].copy()
    lockbox = df[df["fire_us"] >= split_val_us].copy()
    print(f"train rows={len(train):,}, val rows={len(val):,}, lockbox rows={len(lockbox):,}")

    rules = define_rules()
    out_rows = []

    # Also test per (asset, tf, fire_offset_s) — find best configs first using TRAIN
    # Take CSV of top configs already computed
    full_results = pd.read_csv(f"{OUT_DIR}/cross_feature_rules.csv")
    # Filter to deployable-candidate rows: n >= 100 AND WR >= 0.55 AND per_trade > 0.5
    cands = full_results[
        (full_results["n"] >= 100) &
        (full_results["WR"] >= 0.55) &
        (full_results["per_trade"] > 0.5)
    ].copy()
    print(f"\n{len(cands)} candidate configs from full-window screen (n>=100, WR>=55%, $/tr>+$0.5)")

    # For each candidate config, apply rule on TRAIN/VAL/LOCKBOX
    for _, cand in cands.iterrows():
        rule_name, side, asset, tf, off = cand["rule"], cand["side"], cand["asset"], cand["tf"], int(cand["fire_offset_s"])
        rfn = rules[rule_name]
        result_row = dict(rule=rule_name, side=side, asset=asset, tf=tf, fire_offset_s=off,
                          full_n=int(cand["n"]), full_WR=float(cand["WR"]), full_per_trade=float(cand["per_trade"]))
        for set_name, sdf in [("train", train), ("val", val), ("lockbox", lockbox)]:
            sub = sdf[(sdf["asset"] == asset) & (sdf["tf"] == tf) & (sdf["fire_offset_s"] == off)]
            if sub.empty:
                result_row[f"{set_name}_n"] = 0
                result_row[f"{set_name}_WR"] = np.nan
                result_row[f"{set_name}_per_trade"] = np.nan
                continue
            up_mask, dn_mask = rfn(sub)
            up_pnl = compute_pnl(sub, "UP")
            dn_pnl = compute_pnl(sub, "DN")
            if side == "UP":
                mask, pnl = up_mask, up_pnl
                won = (sub["outcome"] == "Up").astype(int)
            elif side == "DN":
                mask, pnl = dn_mask, dn_pnl
                won = (sub["outcome"] == "Down").astype(int)
            else:  # BOTH
                pnl = pd.Series(np.nan, index=sub.index)
                pnl[up_mask] = up_pnl[up_mask]
                pnl[dn_mask] = dn_pnl[dn_mask]
                won_up = (sub["outcome"] == "Up").astype(int)
                won_dn = (sub["outcome"] == "Down").astype(int)
                won = pd.Series(np.nan, index=sub.index)
                won[up_mask] = won_up[up_mask]
                won[dn_mask] = won_dn[dn_mask]
                mask = (up_mask | dn_mask)
            mask = mask & pnl.notna()
            n_fired = int(mask.sum())
            result_row[f"{set_name}_n"] = n_fired
            if n_fired > 0:
                pnl_vals = pnl[mask].to_numpy(float)
                won_vals = won[mask].to_numpy(int)
                result_row[f"{set_name}_WR"] = float(won_vals.mean())
                result_row[f"{set_name}_per_trade"] = float(pnl_vals.mean())
                result_row[f"{set_name}_sum_pnl"] = float(pnl_vals.sum())
                if set_name == "lockbox":
                    result_row["lockbox_pvalue"] = bootstrap_pvalue(pnl_vals, 500)
            else:
                result_row[f"{set_name}_WR"] = np.nan
                result_row[f"{set_name}_per_trade"] = np.nan
                result_row[f"{set_name}_sum_pnl"] = 0.0
        # Deployable check (use explicit None check — 0 is falsy in Python so `x or default` is buggy when x==0)
        lb_n = result_row.get("lockbox_n", 0) or 0
        lb_wr = result_row.get("lockbox_WR")
        lb_pt = result_row.get("lockbox_per_trade")
        lb_pv = result_row.get("lockbox_pvalue")
        result_row["deployable"] = (
            lb_n >= 30 and
            lb_wr is not None and not pd.isna(lb_wr) and lb_wr >= 0.65 and
            lb_pt is not None and not pd.isna(lb_pt) and lb_pt >= 1.0 and
            lb_pv is not None and not pd.isna(lb_pv) and lb_pv <= 0.05
        )
        out_rows.append(result_row)

    df_out = pd.DataFrame(out_rows)
    df_out = df_out.sort_values(["deployable", "lockbox_per_trade"], ascending=[False, False])
    df_out.to_csv(f"{OUT_DIR}/three_way_validation.csv", index=False)
    df_out.to_csv(f"{ROOT}/data/v4/canonical/_results/cross_feature_three_way_validation.csv", index=False)
    print(f"\nSaved three_way_validation.csv ({len(df_out)} rows)")

    n_deployable = int(df_out["deployable"].sum())
    print(f"DEPLOYABLE: {n_deployable}")
    if n_deployable > 0:
        print("\n=== DEPLOYABLE RULES ===")
        cols = ["rule", "side", "asset", "tf", "fire_offset_s",
                "full_n", "full_WR", "full_per_trade",
                "train_n", "train_WR", "train_per_trade",
                "val_n", "val_WR", "val_per_trade",
                "lockbox_n", "lockbox_WR", "lockbox_per_trade", "lockbox_pvalue"]
        print(df_out[df_out["deployable"]][cols].to_string())
    else:
        # Print near-deployable
        print("\n=== TOP 20 NEAR-DEPLOYABLE (sorted by lockbox per-trade) ===")
        cols = ["rule", "side", "asset", "tf", "fire_offset_s",
                "lockbox_n", "lockbox_WR", "lockbox_per_trade"]
        if "lockbox_pvalue" in df_out.columns:
            cols.append("lockbox_pvalue")
        nd = df_out.dropna(subset=["lockbox_per_trade"]).sort_values("lockbox_per_trade", ascending=False).head(20)
        print(nd[cols].to_string())


if __name__ == "__main__":
    main()
