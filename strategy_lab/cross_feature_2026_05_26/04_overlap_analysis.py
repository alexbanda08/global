"""Slug-overlap analysis: do deployable rules fire on the same slugs as BTC S6,
H-A (R5 Hawkes winner), and LM-E (R5 Lee-Mykland winner)?

A "genuinely novel" rule should have < 60% slug overlap with existing top sleeves.
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


def get_baseline_fire_slugs():
    """Return dict of baseline_name -> set of slugs that the baseline 'fires' on."""
    baselines = {}

    # S6 BTC 5m
    s6 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/s6_joined_all.parquet")
    s6 = s6[s6["slug"].str.contains("-5m-")]
    baselines["S6_BTC_5m"] = set(s6[s6["asset"] == "BTC"]["slug"].unique())
    baselines["S6_ETH_5m"] = set(s6[s6["asset"] == "ETH"]["slug"].unique())
    baselines["S6_SOL_5m"] = set(s6[s6["asset"] == "SOL"]["slug"].unique())

    # H-A R5 winner (vpin_hawkes_at_fires + H-A rule)
    hk = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/vpin_hawkes_at_fires.parquet")
    # H-A rule defn: from gate_overlay / standalone in vpin_hawkes — extract by looking at source
    # Without exact source, approximate using lambda_imbalance threshold = sign-of-lambda
    ha_up = hk[(hk["hawkes_lambda_imbalance"] > 0.3)]
    ha_dn = hk[(hk["hawkes_lambda_imbalance"] < -0.3)]
    baselines["HA_BTC_5m"] = set(ha_up[(ha_up["asset"] == "BTC") & (ha_up["tf"] == "5m")]["slug"].unique()) | \
                              set(ha_dn[(ha_dn["asset"] == "BTC") & (ha_dn["tf"] == "5m")]["slug"].unique())

    # LM-E winner: L_stat at fire >= 5.97
    lm = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/lm_at_fires_5m.parquet")
    lm_hit = lm[lm["lm_L_stat_at_fire"] >= 5.97]
    baselines["LME_BTC_5m"] = set(lm_hit[(lm_hit["asset"] == "BTC") & (lm_hit["tf"] == "5m")]["slug"].unique())
    baselines["LME_ETH_5m"] = set(lm_hit[(lm_hit["asset"] == "ETH") & (lm_hit["tf"] == "5m")]["slug"].unique())
    baselines["LME_SOL_5m"] = set(lm_hit[(lm_hit["asset"] == "SOL") & (lm_hit["tf"] == "5m")]["slug"].unique())

    return baselines


def main():
    # Load master + deployable rules
    df = pd.read_parquet(f"{OUT_DIR}/master.parquet")
    df = df[df["outcome"].isin(["Up", "Down"])].copy()
    val = pd.read_csv(f"{OUT_DIR}/three_way_validation.csv")
    val = val[val["deployable"] == True].copy()
    if val.empty:
        print("No deployable rules to analyze")
        return

    rules = define_rules()
    baselines = get_baseline_fire_slugs()

    # For each deployable rule, compute its firing slugs and Jaccard / overlap with baselines
    overlaps = []
    for _, r in val.iterrows():
        rule_name, side, asset, tf, off = r["rule"], r["side"], r["asset"], r["tf"], int(r["fire_offset_s"])
        rfn = rules[rule_name]
        sub = df[(df["asset"] == asset) & (df["tf"] == tf) & (df["fire_offset_s"] == off)]
        up_mask, dn_mask = rfn(sub)
        if side == "UP":
            fire_slugs = set(sub[up_mask]["slug"].unique())
        elif side == "DN":
            fire_slugs = set(sub[dn_mask]["slug"].unique())
        else:
            fire_slugs = set(sub[(up_mask | dn_mask)]["slug"].unique())
        row = {"rule": rule_name, "side": side, "asset": asset, "tf": tf, "fire_offset_s": off,
               "n_slugs": len(fire_slugs)}
        for bl_name, bl_slugs in baselines.items():
            inter = fire_slugs & bl_slugs
            row[f"overlap_{bl_name}_pct"] = (len(inter) / len(fire_slugs) * 100) if fire_slugs else 0.0
        overlaps.append(row)

    out = pd.DataFrame(overlaps)
    out.to_csv(f"{OUT_DIR}/overlap_with_baselines.csv", index=False)
    print(f"Saved overlap_with_baselines.csv ({len(out)} rows)")
    print()
    print(out.to_string())


if __name__ == "__main__":
    main()
