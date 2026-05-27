"""Compare each cross-feature rule's performance to its same (asset, tf, offset_s)
counterpart in V7, H-A, LM-E.

Output: comparison table showing additive vs redundant.
"""
import pandas as pd
import numpy as np

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT_DIR = f"{ROOT}/strategy_lab/cross_feature_2026_05_26"


def main():
    # H-A from vpin_hawkes_standalone
    ha = pd.read_csv(f"{ROOT}/data/v4/canonical/_results/vpin_hawkes_standalone.csv")
    ha = ha[(ha["rule"] == "H-A") & (ha["set"] == "bet")].copy()
    ha["per_trade"] = ha["dollar_per_trade"]
    ha = ha.rename(columns={"WR": "ha_WR", "per_trade": "ha_per_trade", "n": "ha_n", "sum_pnl": "ha_sum"})
    ha_key = ha[["asset", "tf", "offset_s", "ha_n", "ha_WR", "ha_per_trade", "ha_sum"]]
    ha_key = ha_key.rename(columns={"offset_s": "fire_offset_s"})

    # LM standalone
    lm = pd.read_csv(f"{ROOT}/data/v4/canonical/_results/lm_standalone_rules.csv")
    lm = lm[lm["rule"] == "LM-A"].copy()
    lm = lm.rename(columns={"wr_pct": "lm_WR_pct", "per_tr_usd": "lm_per_trade",
                            "n": "lm_n", "sum_pnl_usd": "lm_sum"})
    lm_key = lm[["asset", "tf", "fire_offset_s", "lm_n", "lm_WR_pct", "lm_per_trade", "lm_sum"]]
    lm_key["lm_WR"] = lm_key["lm_WR_pct"] / 100.0

    # cross-feature rules
    cf = pd.read_csv(f"{OUT_DIR}/cross_feature_rules.csv")
    # Pick the top per (asset, tf, fire_offset_s, rule, side) -> already there
    # Join
    cf = cf.merge(ha_key, on=["asset", "tf", "fire_offset_s"], how="left")
    cf = cf.merge(lm_key[["asset", "tf", "fire_offset_s", "lm_n", "lm_WR", "lm_per_trade", "lm_sum"]],
                  on=["asset", "tf", "fire_offset_s"], how="left")

    cf["edge_vs_HA_per_trade"] = cf["per_trade"] - cf["ha_per_trade"]
    cf["edge_vs_LM_per_trade"] = cf["per_trade"] - cf["lm_per_trade"]
    # If cf per_trade > HA + 0.1 AND > LM + 0.1 it's clearly additive on $/tr
    cf["additive_per_trade"] = (
        (cf["edge_vs_HA_per_trade"] > 0.1) &
        (cf["edge_vs_LM_per_trade"] > 0.1) &
        (cf["n"] >= 100) & (cf["WR"] >= 0.55) & (cf["per_trade"] > 0.5)
    )

    cf.to_csv(f"{OUT_DIR}/comparison_to_existing.csv", index=False)

    # Top additive
    print("\n=== TOP CROSS-FEATURE RULES BEATING H-A AND LM-A (n>=100, WR>=55%, $/tr>+$0.5) ===")
    top = cf[cf["additive_per_trade"]].sort_values("per_trade", ascending=False).head(20)
    cols = ["rule", "side", "asset", "tf", "fire_offset_s", "n", "WR", "per_trade",
            "ha_per_trade", "lm_per_trade", "edge_vs_HA_per_trade", "edge_vs_LM_per_trade"]
    print(top[cols].to_string())


if __name__ == "__main__":
    main()
