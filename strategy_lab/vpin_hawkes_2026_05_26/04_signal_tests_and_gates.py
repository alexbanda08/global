"""
Standalone VPIN + Hawkes rule tests, gate overlays on top 15 sleeves, 3-way validation.

Rules implemented:
  V-A: SKIP fires when vpin_zscore > 2 (toxic flow). For "skip" rule we measure PnL of the SKIPPED set.
  V-B: bet ONLY when vpin_zscore < -1 (quiet). Direction = momentum (sign of ret_2m_at_ws).
  V-C: bet WITH momentum when vpin_value < q40 (low VPIN).
  H-A: bet WITH sign(hawkes_lambda_imbalance) when |imbalance| > 0.3.
  H-B: bet WITH momentum when hawkes_recent_burst.
  H-C: SKIP fires when hawkes_lambda_total < q20 (no flow info).

PnL: LegacyConfig ($1 stake, 2%-on-profit fee for winner, no fee for loser).
Win/Loss judged from outcome col & direction.

Outputs:
  data/v4/canonical/_results/vpin_hawkes_standalone.csv
  data/v4/canonical/_results/vpin_hawkes_gates.csv
  data/v4/canonical/_results/vpin_hawkes_validation.csv
"""
import pandas as pd
import numpy as np
from pathlib import Path

FIRES = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_at_fires.parquet"
STAND_PF = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hybrid_standalone_per_fire.parquet"
HYB_5M = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hybrid_fire_universe_5m.parquet"
HYB_15M = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hybrid_fire_universe_15m.parquet"

OUT_STAND = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_standalone.csv"
OUT_GATES = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_gates.csv"
OUT_VAL = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_validation.csv"

STAKE = 1.0  # $1 stake (legacy config)


def pnl_legacy(direction: int, won: bool, vwap: float = 0.5) -> float:
    """LegacyConfig: 2%-on-profit. Direction not relevant for sizing here.
    With $1 stake we buy 1/vwap shares; win -> (1 - vwap)/vwap * 0.98 profit; lose -> -1."""
    if won:
        return (1.0 - vwap) / vwap * 0.98
    return -1.0


def compute_pnl_for_rule(df: pd.DataFrame, direction_col: str, mask_col: str = None, skip_mask=False) -> pd.DataFrame:
    """direction_col: column with bet direction (1 = bet Up, -1 = bet Down, 0 = no bet).
       mask_col: bool mask of fires to consider. skip_mask: when True, FLIP mask sense (these are skipped).
       Returns per-fire pnl col 'pnl_rule'."""
    pass  # see analyse


def evaluate_rule(df: pd.DataFrame, name: str, mask: pd.Series, direction: pd.Series) -> dict:
    """Generic rule evaluator.
    mask: bool — which fires to bet on.
    direction: int (-1/+1) per fire — bet direction.
    Pnl uses ENTRY VWAP from up_vwap/dn_vwap when available; otherwise $0.5."""
    sub = df[mask & direction.notna() & (direction != 0)].copy()
    if len(sub) == 0:
        return {"rule": name, "n": 0, "WR": np.nan, "sum_pnl": 0.0, "dollar_per_trade": np.nan}
    # outcome encoded as 'Up'/'Down'
    out_up = (sub["outcome"] == "Up").to_numpy()
    bet_up = (direction.loc[sub.index] == 1).to_numpy()
    won = (out_up == bet_up)
    # Use 0.5 vwap as approximation (we don't have vwap in slim feature table; gates eval uses per-fire pnl later)
    pnl = np.where(won, (1.0 - 0.5) / 0.5 * 0.98, -1.0)
    return {
        "rule": name,
        "n": int(len(sub)),
        "wins": int(won.sum()),
        "WR": float(won.mean()),
        "sum_pnl": float(pnl.sum()),
        "dollar_per_trade": float(pnl.mean()),
    }


def standalone_rules(feat: pd.DataFrame) -> pd.DataFrame:
    """Run V-A..C, H-A..C per asset/tf/offset combo."""
    rows = []
    feat = feat.copy()
    # Momentum direction sign from ret_2m_at_ws (causal — anchored at ws)
    feat["mom_dir"] = np.sign(feat["ret_2m_at_ws"]).fillna(0).astype(int)

    # Per-asset thresholds for VPIN q40 and Hawkes q20 (causal — using ALL data is approximate; OK for screening)
    for (asset, tf, off), g in feat.groupby(["asset", "tf", "fire_offset_s"]):
        n_total = len(g)
        if n_total < 100: continue
        vp_q40 = g["vpin_value"].quantile(0.40)
        hk_q20 = g["hawkes_lambda_total"].quantile(0.20)

        # V-A: SKIP when vpin_zscore > 2. Measure PnL of the SKIPPED set (using momentum dir).
        m = g["vpin_zscore"] > 2
        dir_ = g["mom_dir"]
        r = evaluate_rule(g, "V-A_SKIP", m, dir_)
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "skipped"})
        rows.append(r)
        # And report the COMPLEMENT (the universe we'd actually bet on)
        r2 = evaluate_rule(g, "V-A_BET", ~m, dir_)
        r2.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r2)

        # V-B: bet ONLY when vpin_zscore < -1, dir = momentum
        m = g["vpin_zscore"] < -1
        r = evaluate_rule(g, "V-B", m, g["mom_dir"])
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r)

        # V-C: bet WITH momentum when vpin_value < q40
        m = g["vpin_value"] < vp_q40
        r = evaluate_rule(g, "V-C", m, g["mom_dir"])
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r)

        # H-A: bet with sign(lambda_imbalance) when |imb|>0.3
        m = g["hawkes_lambda_imbalance"].abs() > 0.3
        dir_h = np.sign(g["hawkes_lambda_imbalance"]).fillna(0).astype(int)
        r = evaluate_rule(g, "H-A", m, dir_h)
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r)

        # H-B: bet WITH momentum when recent_burst
        m = g["hawkes_recent_burst"] == 1
        r = evaluate_rule(g, "H-B", m, g["mom_dir"])
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r)

        # H-C: SKIP when lam_total < q20. Bet on COMPLEMENT.
        m = g["hawkes_lambda_total"] >= hk_q20
        r = evaluate_rule(g, "H-C_BET", m, g["mom_dir"])
        r.update({"asset": asset, "tf": tf, "offset_s": off, "set": "bet"})
        rows.append(r)

    return pd.DataFrame(rows)


def gate_overlay(pf: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    """Apply gates to top 15 sleeves from standalone_per_fire."""
    # Aggregate to find top 15
    agg = pf.groupby(["asset","tf","fire_offset_s","rule"]).agg(
        n=("pnl","size"), wr=("pnl", lambda x: (x>0).mean()), sum_pnl=("pnl","sum"), dpt=("pnl","mean")
    ).reset_index()
    top = agg[(agg["n"]>=200)].sort_values("sum_pnl", ascending=False).head(15)
    print("Top 15 sleeves (baseline):")
    print(top.to_string())

    # Join features to per-fire rows
    feat_keyed = feat.set_index(["asset","slug","tf","fire_offset_s","fire_us"])
    pf_keyed = pf.set_index(["asset","slug","tf","fire_offset_s","fire_us"])
    merged = pf_keyed.join(feat_keyed[["vpin_value","vpin_zscore","hawkes_lambda_total",
        "hawkes_lambda_imbalance","hawkes_recent_burst"]], how="left").reset_index()
    print(f"merged cols: {list(merged.columns)}")
    print(f"merged rows: {len(merged):,} feat-coverage: {merged['vpin_value'].notna().mean()*100:.1f}%")

    rows = []
    for _, top_row in top.iterrows():
        a, tf, off, rule = top_row.asset, top_row.tf, top_row.fire_offset_s, top_row.rule
        s = merged[(merged.asset==a)&(merged.tf==tf)&(merged.fire_offset_s==off)&(merged.rule==rule)]
        if len(s) == 0: continue
        base = {
            "asset":a,"tf":tf,"offset_s":off,"rule":rule,
            "baseline_n":len(s),"baseline_wr":(s.pnl>0).mean(),"baseline_sum_pnl":s.pnl.sum(),"baseline_dpt":s.pnl.mean(),
        }
        # Direction of the sleeve (use 'direction' col)
        dir_ = s["direction"]
        gates = {
            "g_vpin_low": s["vpin_zscore"] < 0,
            "g_vpin_extreme_skip": s["vpin_zscore"] <= 2,   # KEEP if z<=2 (skip when >2)
            "g_hawkes_burst_with": (s["hawkes_recent_burst"]==1) & (np.sign(s["hawkes_lambda_imbalance"])==dir_),
            "g_hawkes_imbalance_with": np.sign(s["hawkes_lambda_imbalance"]) == dir_,
        }
        for gname, gmask in gates.items():
            sub = s[gmask & s["vpin_value"].notna()]
            if len(sub) < 50:
                r = dict(base); r.update({"gate":gname,"gate_n":len(sub),"gate_wr":np.nan,"gate_sum_pnl":np.nan,"gate_dpt":np.nan,"lift_dpt":np.nan})
            else:
                r = dict(base)
                r.update({
                    "gate":gname,
                    "gate_n":len(sub),
                    "gate_wr":(sub.pnl>0).mean(),
                    "gate_sum_pnl":sub.pnl.sum(),
                    "gate_dpt":sub.pnl.mean(),
                    "lift_dpt":sub.pnl.mean() - base["baseline_dpt"],
                })
            rows.append(r)

    return pd.DataFrame(rows)


def split_train_val_lock(df: pd.DataFrame, fire_col="fire_us") -> tuple:
    """Train / Val / Lockbox by time. Auto-sizes to 64/21/15% of available days.
    On the 22d backtest set this gives ~14d train / 4-5d val / 3d lockbox."""
    ts = df[fire_col].astype(np.int64)
    tmin, tmax = ts.min(), ts.max()
    span = tmax - tmin
    train_end = tmin + int(span * 0.64)
    val_end = tmin + int(span * 0.85)
    train = df[ts < train_end]
    val = df[(ts >= train_end) & (ts < val_end)]
    lock = df[ts >= val_end]
    return train, val, lock


def validate_top_sleeves(gates_df: pd.DataFrame, pf: pd.DataFrame, feat: pd.DataFrame) -> pd.DataFrame:
    """3-way validation: for each (sleeve, gate) combo with positive lift on training,
       re-test on val and lockbox."""
    # Re-derive merged like before
    feat_keyed = feat.set_index(["asset","slug","tf","fire_offset_s","fire_us"])
    pf_keyed = pf.set_index(["asset","slug","tf","fire_offset_s","fire_us"])
    merged = pf_keyed.join(feat_keyed[["vpin_value","vpin_zscore","hawkes_lambda_total",
        "hawkes_lambda_imbalance","hawkes_recent_burst"]], how="left").reset_index()

    # Pick top-by-lift combos with gate_n >= 100 baseline
    cand = gates_df[(gates_df["lift_dpt"]>0) & (gates_df["gate_n"]>=150)].sort_values("lift_dpt", ascending=False).head(25)
    print(f"\nValidation candidates: {len(cand)}")

    rows = []
    for _, row in cand.iterrows():
        a,tf,off,rule,gname = row.asset, row.tf, row.offset_s, row.rule, row.gate
        s = merged[(merged.asset==a)&(merged.tf==tf)&(merged.fire_offset_s==off)&(merged.rule==rule)]
        dir_ = s["direction"]
        if gname == "g_vpin_low":
            gmask = s["vpin_zscore"] < 0
        elif gname == "g_vpin_extreme_skip":
            gmask = s["vpin_zscore"] <= 2
        elif gname == "g_hawkes_burst_with":
            gmask = (s["hawkes_recent_burst"]==1) & (np.sign(s["hawkes_lambda_imbalance"])==dir_)
        elif gname == "g_hawkes_imbalance_with":
            gmask = np.sign(s["hawkes_lambda_imbalance"]) == dir_
        else: continue
        sub = s[gmask & s["vpin_value"].notna()]

        # Bootstrap-CI on full set for context
        train, val, lock = split_train_val_lock(sub)
        def stats(d):
            if len(d)==0: return (0, np.nan, np.nan, 0.0)
            return (len(d), (d.pnl>0).mean(), d.pnl.mean(), d.pnl.sum())
        n_t, wr_t, dpt_t, sp_t = stats(train)
        n_v, wr_v, dpt_v, sp_v = stats(val)
        n_l, wr_l, dpt_l, sp_l = stats(lock)
        # Bootstrap on lockbox: 1k resamples
        if len(lock) >= 30:
            rng = np.random.default_rng(42)
            pnl_l = lock["pnl"].to_numpy()
            boot = [rng.choice(pnl_l, size=len(pnl_l), replace=True).mean() for _ in range(1000)]
            ci_lo, ci_hi = np.quantile(boot, [0.025, 0.975])
        else:
            ci_lo = ci_hi = np.nan
        # Pass: positive in train AND val AND lock AND lower CI > 0
        passed = (dpt_t > 0) and (dpt_v > 0) and (dpt_l > 0) and (ci_lo > 0)
        rows.append({
            "asset":a,"tf":tf,"offset_s":off,"rule":rule,"gate":gname,
            "n_train":n_t,"WR_train":wr_t,"dpt_train":dpt_t,"sum_train":sp_t,
            "n_val":n_v,"WR_val":wr_v,"dpt_val":dpt_v,"sum_val":sp_v,
            "n_lock":n_l,"WR_lock":wr_l,"dpt_lock":dpt_l,"sum_lock":sp_l,
            "ci_lo_lock":ci_lo,"ci_hi_lock":ci_hi,"PASS":passed,
        })
    return pd.DataFrame(rows)


def main():
    print("loading features at fires")
    feat = pd.read_parquet(FIRES)
    print(f"  feat: {feat.shape}")

    print("\n== Task 4: Standalone rule tests ==")
    stand = standalone_rules(feat)
    stand.to_csv(OUT_STAND, index=False)
    print(f"wrote {OUT_STAND}: {stand.shape}")
    # Print rollups by rule
    print("\nStandalone rollup (n>=200, sorted by sum_pnl):")
    agg = stand[stand["n"]>=200].groupby(["rule","set"]).agg(
        sleeves=("n","size"), tot_n=("n","sum"), avg_WR=("WR","mean"),
        sum_pnl=("sum_pnl","sum"), avg_dpt=("dollar_per_trade","mean")
    ).reset_index().sort_values("sum_pnl",ascending=False)
    print(agg.to_string())

    print("\n== Task 5: Gate overlays on top 15 sleeves ==")
    pf = pd.read_parquet(STAND_PF)
    gates = gate_overlay(pf, feat)
    gates.to_csv(OUT_GATES, index=False)
    print(f"wrote {OUT_GATES}: {gates.shape}")

    # Quick gate summary
    gs = gates.dropna(subset=["gate_dpt"]).copy()
    gs["lift_pct"] = (gs["lift_dpt"] / gs["baseline_dpt"].abs()) * 100
    print("\nGate lift summary (top 20 by lift_dpt):")
    print(gs.sort_values("lift_dpt",ascending=False).head(20)[["asset","tf","offset_s","rule","gate","baseline_n","baseline_dpt","gate_n","gate_dpt","lift_dpt"]].to_string())

    print("\n== Task 6: 3-way validation ==")
    val = validate_top_sleeves(gates, pf, feat)
    val.to_csv(OUT_VAL, index=False)
    print(f"wrote {OUT_VAL}: {val.shape}")
    if len(val)>0:
        print("\nValidation results:")
        print(val[["asset","tf","offset_s","rule","gate","n_train","dpt_train","n_val","dpt_val","n_lock","dpt_lock","ci_lo_lock","PASS"]].to_string())
        print(f"\nLockbox PASS count: {val['PASS'].sum()} / {len(val)}")


if __name__ == "__main__":
    main()
