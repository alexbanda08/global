"""TASK 6/7 — Manual vs ML comparison + stacked ensemble on lockbox.

Loads:
  - ML lockbox predictions (data/v4/canonical/_results/ml_lightgbm/lockbox_predictions.parquet)
  - Manual gate per-fire panel  (s6/s15/v15m _joined_drz)
Applies top manual hybrid-search gate stacks on LOCKBOX (May 21 - May 25) and
compares vs ML-thresholded sleeves. Also constructs a weighted stack:
   stack_score = w_ml * (P_up_ml - 0.5)  +  w_manual * (manual_gate_pass ? 1 : -1)
where the gate "side" is BTC ETH SOL directional sleeve.
"""

import os, sys, json, datetime as dt
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(ROOT, "data", "v4", "canonical", "_results")
ML_OUT  = os.path.join(RESULTS, "ml_lightgbm")

# canonical-fee LegacyConfig math (2%-on-profit on winning leg, full loss on losing leg)
FEE_RATE = 0.02


def pnl_from_fill(fill_vwap, won):
    # $1 stake.  Winning leg: (1/vwap - 1) * (1 - fee).  Losing: -1.
    if fill_vwap <= 0 or pd.isna(fill_vwap):
        return np.nan
    if won:
        return (1.0 / fill_vwap - 1.0) * (1.0 - FEE_RATE)
    return -1.0


def bootstrap_p(per_trade, n_shuffles=200):
    if len(per_trade) == 0:
        return float("nan")
    x = np.array(per_trade, dtype=float)
    obs = x.mean()
    rng = np.random.default_rng(42)
    ge = 0
    for _ in range(n_shuffles):
        signs = rng.choice([1, -1], size=len(x))
        s = (x * signs).mean()
        if abs(s) >= abs(obs):
            ge += 1
    return ge / n_shuffles


# Top manual gate stacks from hybrid_walk_forward + full_window_gate_search,
# chosen as "the best manual sleeves to test on the SAME lockbox the ML sees".
# direction = the bet side at fire (from the original sleeve def — momo always bets the
# side that ret_2m_at_ws agrees with).
MANUAL_SLEEVES = [
    # BTC 5m
    {"label": "BTC_5m_S6_hybrid_v1",
     "panel": "s6_joined_drz", "asset": "BTC", "offset_bin": (60, 150),
     "gates": ["g_cci_with", "g_stoch_with", "g_tr_above_ema50", "g_rf_with"]},
    # ETH 5m S6 best
    {"label": "ETH_5m_S6_hybrid_top",
     "panel": "s6_joined_drz", "asset": "ETH", "offset_bin": (60, 150),
     "gates": ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"]},
    # ETH 5m S6 + tight ribbon
    {"label": "ETH_5m_S6_tight_ribbon",
     "panel": "s6_joined_drz", "asset": "ETH", "offset_bin": (60, 150),
     "gates": ["g_tight_ribbon", "g_stoch_with"]},
    # SOL 5m S15
    {"label": "SOL_5m_S15_above_ema",
     "panel": "s15_joined_drz", "asset": "SOL", "offset_bin": (60, 150),
     "gates": ["g_tr_above_ema800", "g_tr_above_cloud", "g_tr_above_ema200"]},
    # ETH 15m
    {"label": "ETH_15m_v15m_ribbon",
     "panel": "v15m_joined_drz", "asset": "ETH", "offset_bin": (150, 240),
     "gates": ["g_ribbon_agrees", "g_tr_above_ema200", "g_cci_with"]},
    # BTC 15m
    {"label": "BTC_15m_v15m_pp_ribbon",
     "panel": "v15m_joined_drz", "asset": "BTC", "offset_bin": (150, 240),
     "gates": ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with", "g_tight_ribbon"]},
]

VAL_END_US = int(dt.datetime(2026, 5, 21, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1_000_000)
TRAIN_END_US = int(dt.datetime(2026, 5, 14, 0, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1_000_000)


def load_panel_with_fills(panel_name: str) -> pd.DataFrame:
    """Load a manual-gate per-fire panel.

    The s6_joined_drz / s15_joined_drz / v15m_joined_drz panels already have
    `direction`, `outcome`, `won`, `entry_vwap`, `pnl_legacy_usd`.
    """
    p = pd.read_parquet(os.path.join(RESULTS, f"{panel_name}.parquet"))
    needed = {"asset", "slug", "fire_offset_s", "fire_us", "outcome",
              "direction", "won", "entry_vwap", "pnl_legacy_usd"}
    miss = needed - set(p.columns)
    if miss:
        raise ValueError(f"{panel_name} missing cols: {miss}")
    return p


def apply_manual_sleeve(sl: dict) -> dict:
    p = load_panel_with_fills(sl["panel"])
    # Filter to asset, offset bin
    a, b = sl["offset_bin"]
    sub = p[(p["asset"] == sl["asset"]) & (p["fire_offset_s"].between(a, b))].copy()
    # Apply gates — they must ALL be 1
    miss_gates = [g for g in sl["gates"] if g not in sub.columns]
    if miss_gates:
        return {"label": sl["label"], "error": f"missing gates: {miss_gates}"}
    mask = np.ones(len(sub), dtype=bool)
    for g in sl["gates"]:
        mask &= (sub[g] == 1)
    sub = sub[mask].copy()

    # pnl_legacy_usd is at $25 notional. Normalize to $1 stake for apples-to-apples with ML.
    sub["pnl"] = sub["pnl_legacy_usd"] / 25.0
    sub = sub.dropna(subset=["pnl"])
    # Direction is UPPER-cased; normalize so stacker join works
    sub["direction"] = sub["direction"].str.title()

    # Splits
    train = sub[sub["fire_us"] < TRAIN_END_US]
    val   = sub[(sub["fire_us"] >= TRAIN_END_US) & (sub["fire_us"] < VAL_END_US)]
    lock  = sub[sub["fire_us"] >= VAL_END_US]

    def metrics(df, name):
        if len(df) == 0:
            return {f"{name}_n": 0, f"{name}_wr": 0, f"{name}_sum": 0, f"{name}_dpt": 0, f"{name}_p": float("nan")}
        return {
            f"{name}_n": len(df),
            f"{name}_wr": float(df["won"].mean()),
            f"{name}_sum": float(df["pnl"].sum()),
            f"{name}_dpt": float(df["pnl"].mean()),
            f"{name}_p": bootstrap_p(df["pnl"].values),
        }

    m_train = metrics(train, "train")
    m_val   = metrics(val, "val")
    m_lock  = metrics(lock, "lock")

    # Also return per-fire lockbox predictions for stacking
    lock_pred = lock[["asset", "slug", "fire_us", "fire_offset_s", "direction", "outcome", "won", "pnl"]].copy()
    lock_pred["sleeve"] = sl["label"]

    return {"label": sl["label"], **m_train, **m_val, **m_lock, "lock_pred": lock_pred}


def manual_vs_ml_summary():
    rows = []
    lock_preds_manual = []
    for sl in MANUAL_SLEEVES:
        r = apply_manual_sleeve(sl)
        if "error" in r:
            print(f"{sl['label']}: ERROR — {r['error']}")
            continue
        if "lock_pred" in r:
            lock_preds_manual.append(r.pop("lock_pred"))
        rows.append(r)
    df = pd.DataFrame(rows)
    cols = ["label", "train_n", "train_wr", "train_dpt", "val_n", "val_wr", "val_dpt", "lock_n", "lock_wr", "lock_sum", "lock_dpt", "lock_p"]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]
    print("\n=== MANUAL SLEEVES ON LOCKBOX ===")
    print(df.to_string(index=False))
    df.to_csv(os.path.join(ML_OUT, "manual_sleeves_lockbox.csv"), index=False)

    # Combined per-fire manual lockbox predictions
    manual_lock = pd.concat(lock_preds_manual, ignore_index=True) if lock_preds_manual else pd.DataFrame()
    if not manual_lock.empty:
        manual_lock.to_parquet(os.path.join(ML_OUT, "manual_lockbox_preds.parquet"))
    return df, manual_lock


def stacked_ensemble(manual_lock: pd.DataFrame):
    """Build weighted stack: take fires that BOTH ML(p_up_iso > 0.55) AND manual sleeve flag agree on direction.

    Stack rule:  fire only if both ML and manual say SAME side, otherwise abstain.
    """
    ml = pd.read_parquet(os.path.join(ML_OUT, "lockbox_predictions.parquet"))
    # Filter to BTC/ETH 5m (the most meaningful comparison)
    out_rows = []
    for asset_tf in ["BTC_5m", "ETH_5m", "SOL_5m", "BTC_15m", "ETH_15m", "SOL_15m"]:
        asset, tf = asset_tf.split("_")
        ml_sub = ml[ml["model"] == asset_tf].copy()
        if ml_sub.empty:
            continue
        # ML direction from isotonic-prob
        ml_sub["ml_dir"] = np.where(ml_sub["p_up_iso"] > 0.55, "Up",
                          np.where(ml_sub["p_up_iso"] < 0.45, "Down", ""))
        ml_sub = ml_sub[ml_sub["ml_dir"] != ""]

        # ML standalone PnL on lockbox
        ml_sub["fill_vwap"] = np.where(ml_sub["ml_dir"] == "Up", ml_sub["up_vwap"], ml_sub["dn_vwap"])
        ml_sub = ml_sub[ml_sub["fill_vwap"] > 0]
        ml_sub["won"] = (ml_sub["ml_dir"] == ml_sub["outcome"]).astype(int)
        ml_sub["pnl"] = ml_sub.apply(lambda r: pnl_from_fill(r["fill_vwap"], bool(r["won"])), axis=1)
        ml_n = len(ml_sub)
        ml_pnl = ml_sub["pnl"].sum()
        ml_wr  = ml_sub["won"].mean() if ml_n else 0

        # Manual sleeves for this market: gather all manual fires for this asset/tf
        manual_sub = manual_lock[manual_lock["asset"] == asset].copy()
        if tf == "5m":
            manual_sub = manual_sub[manual_sub["fire_offset_s"].between(60, 150)]
        else:
            manual_sub = manual_sub[manual_sub["fire_offset_s"].between(150, 240)]
        manual_n = len(manual_sub)
        manual_pnl = manual_sub["pnl"].sum()
        manual_wr  = manual_sub["won"].mean() if manual_n else 0

        # Stack: keep fires where BOTH agree on slug+side
        if manual_n > 0:
            agree = manual_sub.merge(
                ml_sub[["asset", "slug", "fire_offset_s", "ml_dir"]],
                on=["asset", "slug", "fire_offset_s"], how="inner",
            )
            agree = agree[agree["direction"] == agree["ml_dir"]]
            stack_n = len(agree)
            stack_pnl = agree["pnl"].sum() if stack_n else 0
            stack_wr  = agree["won"].mean() if stack_n else 0
            stack_dpt = stack_pnl / stack_n if stack_n else 0
            stack_p   = bootstrap_p(agree["pnl"].values) if stack_n else float("nan")
        else:
            stack_n = 0; stack_pnl = 0; stack_wr = 0; stack_dpt = 0; stack_p = float("nan")

        out_rows.append({
            "market": asset_tf,
            "ml_n": ml_n, "ml_wr": round(ml_wr, 4), "ml_sum": round(ml_pnl, 2),
            "ml_dpt": round(ml_pnl / ml_n, 5) if ml_n else 0,
            "manual_n": manual_n, "manual_wr": round(manual_wr, 4), "manual_sum": round(manual_pnl, 2),
            "manual_dpt": round(manual_pnl / manual_n, 5) if manual_n else 0,
            "stack_n": stack_n, "stack_wr": round(stack_wr, 4), "stack_sum": round(stack_pnl, 2),
            "stack_dpt": round(stack_dpt, 5), "stack_boot_p": round(stack_p, 3) if stack_p == stack_p else "nan",
        })
    df = pd.DataFrame(out_rows)
    print("\n=== STACK COMPARISON (ML vs MANUAL vs INTERSECTION) ===")
    print(df.to_string(index=False))
    df.to_csv(os.path.join(ML_OUT, "stacker_lockbox.csv"), index=False)
    return df


if __name__ == "__main__":
    manual_df, manual_lock = manual_vs_ml_summary()
    stack_df = stacked_ensemble(manual_lock)
