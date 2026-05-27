"""Score every cross-feature direction rule on the master panel.

PnL convention:
  - Bet UP: buy `up_shares` at `up_vwap`, payoff $1 if outcome==Up else $0
  - Bet DN: buy `dn_shares` at `dn_vwap`, payoff $1 if outcome==Down else $0
  - Fees: LegacyConfig (2% on profit; no fee on loss)
  - Fill validity: requires up_fill_ok / dn_fill_ok = True
"""
import pandas as pd
import numpy as np
import sys
import os

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
OUT_DIR = f"{ROOT}/strategy_lab/cross_feature_2026_05_26"
LEGACY_FEE = 0.02


def compute_pnl(df: pd.DataFrame, side: str) -> pd.Series:
    """Legacy 2%-on-profit fee model."""
    if side == "UP":
        shares = df["up_shares"].to_numpy(float)
        usd_in = df["up_usd"].to_numpy(float)
        won = (df["outcome"] == "Up").to_numpy(bool)
    else:  # DN
        shares = df["dn_shares"].to_numpy(float)
        usd_in = df["dn_usd"].to_numpy(float)
        won = (df["outcome"] == "Down").to_numpy(bool)
    gross = shares * 1.0 - usd_in  # if won
    pnl = np.where(
        won,
        gross - np.where(gross > 0, gross * LEGACY_FEE, 0.0),
        -usd_in,
    )
    # Invalidate where fill_ok was False
    fill_ok = (df["up_fill_ok"] if side == "UP" else df["dn_fill_ok"]).to_numpy(bool)
    pnl = np.where(fill_ok, pnl, np.nan)
    return pd.Series(pnl, index=df.index)


def score_rule(df: pd.DataFrame, mask: pd.Series, side: str) -> dict:
    """Return n, wins, WR, sum_pnl, per_trade for fires where mask is True."""
    sub = df[mask].copy()
    if len(sub) == 0:
        return dict(n=0, wins=0, WR=np.nan, sum_pnl=0.0, per_trade=np.nan)
    pnl = compute_pnl(sub, side)
    valid = pnl.notna()
    sub = sub[valid]
    pnl = pnl[valid]
    if len(sub) == 0:
        return dict(n=0, wins=0, WR=np.nan, sum_pnl=0.0, per_trade=np.nan)
    won_mask = (sub["outcome"] == "Up").to_numpy(bool) if side == "UP" \
        else (sub["outcome"] == "Down").to_numpy(bool)
    return dict(
        n=int(len(sub)),
        wins=int(won_mask.sum()),
        WR=float(won_mask.mean()),
        sum_pnl=float(pnl.sum()),
        per_trade=float(pnl.mean()),
    )


def define_rules():
    """Each rule returns a callable (df) -> {UP: mask, DN: mask}."""
    rules = {}

    # XF-A: microprice + LM statistical jump
    def xf_a(df):
        base_up = (df["mp_skew"] > 0) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["mp_skew"] < 0) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-A"] = xf_a

    # XF-B: Hawkes imbalance + microprice momentum
    def xf_b(df):
        base_up = (df["hawkes_lambda_imbalance"] > 0.3) & (df["mp_skew_change_500ms"] > 0)
        base_dn = (df["hawkes_lambda_imbalance"] < -0.3) & (df["mp_skew_change_500ms"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-B"] = xf_b

    # XF-C: DISAGREEMENT (MP UP, L1 DOWN) — bet UP. Mirror = (MP DOWN, L1 UP) bet DOWN.
    def xf_c(df):
        base_up = (df["mp_skew"] > 0) & (df["imb5_diff"] < 0)
        base_dn = (df["mp_skew"] < 0) & (df["imb5_diff"] > 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-C"] = xf_c

    # XF-D: regime trend + microprice + vol-expanding (use bb_width_60s > median proxy)
    def xf_d(df):
        # vol_expanding proxy: bb_width_60s above its rolling median per asset/tf
        # Use top-half threshold = global median
        if "bb_width_60s" not in df.columns:
            return pd.Series(False, index=df.index), pd.Series(False, index=df.index)
        med = df["bb_width_60s"].median()
        ve = df["bb_width_60s"] > med
        base_up = (df["trend_slope_30m"] > 0) & (df["mp_skew"] > 0) & ve
        base_dn = (df["trend_slope_30m"] < 0) & (df["mp_skew"] < 0) & ve
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-D"] = xf_d

    # XF-E: SMS liquidity sweep + LM statistical jump
    def xf_e(df):
        base_up = (df["liquidity_dn"] == True) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["liquidity_up"] == True) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-E"] = xf_e

    # XF-F: extreme Hawkes + LM jump same direction
    def xf_f(df):
        base_up = (df["hawkes_lambda_imbalance"] > 0.5) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["hawkes_lambda_imbalance"] < -0.5) & (df["lm_L_stat_at_fire"] >= 5.97) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-F"] = xf_f

    # XF-G: triple-confluence book pressure (mp_skew >= 0.5, hawkes_imb >= 0.3, imb5_diff >= 0.3)
    # imb5_diff scaled to ~(-1,1); 0.3 = "Up book is 30% better than Down book"
    def xf_g(df):
        base_up = (df["mp_skew"] >= 0.5) & (df["hawkes_lambda_imbalance"] >= 0.3) & (df["imb5_diff"] >= 0.3)
        base_dn = (df["mp_skew"] <= -0.5) & (df["hawkes_lambda_imbalance"] <= -0.3) & (df["imb5_diff"] <= -0.3)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-G"] = xf_g

    # DISAGREEMENT deep dive variants
    def disagr_strict_02(df):
        base_up = (df["mp_skew"] > 0) & (df["imb5_diff"] < -0.2)
        base_dn = (df["mp_skew"] < 0) & (df["imb5_diff"] > 0.2)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["DISAGR-0.2"] = disagr_strict_02

    def disagr_strict_05(df):
        base_up = (df["mp_skew"] > 0) & (df["imb5_diff"] < -0.5)
        base_dn = (df["mp_skew"] < 0) & (df["imb5_diff"] > 0.5)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["DISAGR-0.5"] = disagr_strict_05

    def disagr_hawkes_confirm(df):
        base_up = (df["mp_skew"] > 0) & (df["imb5_diff"] < 0) & (df["hawkes_lambda_imbalance"] > 0.2)
        base_dn = (df["mp_skew"] < 0) & (df["imb5_diff"] > 0) & (df["hawkes_lambda_imbalance"] < -0.2)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["DISAGR-HAWKES"] = disagr_hawkes_confirm

    # Additional double-confluence rules (less strict for sample size)
    def xf_h_mp_lm_dir(df):
        # MP-skew aligned with last-60s LM jump dir (no L threshold)
        base_up = (df["mp_skew"] > 0) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["mp_skew"] < 0) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-H"] = xf_h_mp_lm_dir

    def xf_i_mp_hawkes(df):
        # MP skew aligned with Hawkes order-flow imbalance
        base_up = (df["mp_skew"] > 0) & (df["hawkes_lambda_imbalance"] > 0.1)
        base_dn = (df["mp_skew"] < 0) & (df["hawkes_lambda_imbalance"] < -0.1)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-I"] = xf_i_mp_hawkes

    def xf_j_hawkes_lm(df):
        # Hawkes pressure + LM jump same direction
        base_up = (df["hawkes_lambda_imbalance"] > 0.2) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["hawkes_lambda_imbalance"] < -0.2) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-J"] = xf_j_hawkes_lm

    # Quadruple-stack
    def xf_k_quad_stack(df):
        base_up = (df["mp_skew"] > 0) & (df["hawkes_lambda_imbalance"] > 0.1) & \
                  (df["imb5_diff"] > 0) & (df["lm_last_jump_dir_60s"] > 0)
        base_dn = (df["mp_skew"] < 0) & (df["hawkes_lambda_imbalance"] < -0.1) & \
                  (df["imb5_diff"] < 0) & (df["lm_last_jump_dir_60s"] < 0)
        return base_up.fillna(False), base_dn.fillna(False)
    rules["XF-K"] = xf_k_quad_stack

    return rules


def main():
    df = pd.read_parquet(f"{OUT_DIR}/master.parquet")
    print(f"Master loaded: {len(df):,} rows")

    # Restrict to chainlink-resolved (outcome is Up or Down)
    df = df[df["outcome"].isin(["Up", "Down"])].copy()
    print(f"Resolved (chainlink) fires: {len(df):,}")

    rules = define_rules()

    rows = []
    for rule_name, rule_fn in rules.items():
        up_mask, dn_mask = rule_fn(df)
        # Per (asset, tf, fire_offset_s)
        for (asset, tf, off), sub in df.groupby(["asset", "tf", "fire_offset_s"]):
            sub_up = up_mask.loc[sub.index]
            sub_dn = dn_mask.loc[sub.index]
            # UP side
            r_up = score_rule(sub, sub_up, "UP")
            rows.append({
                "rule": rule_name, "side": "UP",
                "asset": asset, "tf": tf, "fire_offset_s": int(off),
                **r_up,
            })
            # DN side
            r_dn = score_rule(sub, sub_dn, "DN")
            rows.append({
                "rule": rule_name, "side": "DN",
                "asset": asset, "tf": tf, "fire_offset_s": int(off),
                **r_dn,
            })
            # BOTH sides combined (treat as one rule firing on either)
            both_pnl = pd.Series(np.nan, index=sub.index)
            up_pnl = compute_pnl(sub, "UP")
            dn_pnl = compute_pnl(sub, "DN")
            both_pnl[sub_up] = up_pnl[sub_up]
            both_pnl[sub_dn] = dn_pnl[sub_dn]
            mask_either = (sub_up | sub_dn) & both_pnl.notna()
            sub_both = sub[mask_either]
            pnl_both = both_pnl[mask_either]
            if len(sub_both) > 0:
                won_both = np.where(
                    sub_up[mask_either].values,
                    (sub_both["outcome"] == "Up").values,
                    (sub_both["outcome"] == "Down").values,
                )
                rows.append({
                    "rule": rule_name, "side": "BOTH",
                    "asset": asset, "tf": tf, "fire_offset_s": int(off),
                    "n": int(len(sub_both)),
                    "wins": int(won_both.sum()),
                    "WR": float(won_both.mean()),
                    "sum_pnl": float(pnl_both.sum()),
                    "per_trade": float(pnl_both.mean()),
                })

    out = pd.DataFrame(rows)
    out.to_csv(f"{OUT_DIR}/cross_feature_rules.csv", index=False)
    # also save to canonical _results
    out.to_csv(f"{ROOT}/data/v4/canonical/_results/cross_feature_rules.csv", index=False)
    print(f"Saved cross_feature_rules.csv ({len(out)} rows)")

    # Quick best-rules summary
    print("\n=== TOP 25 BY PER-TRADE PNL (n >= 100) ===")
    top = out[(out["n"] >= 100) & (out["WR"].notna())].sort_values("per_trade", ascending=False).head(25)
    print(top.to_string())

    print("\n=== TOP 25 BY SUM PNL (n >= 100) ===")
    top2 = out[(out["n"] >= 100) & (out["WR"].notna())].sort_values("sum_pnl", ascending=False).head(25)
    print(top2.to_string())


if __name__ == "__main__":
    main()
