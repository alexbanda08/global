"""Build master cross-feature dataframe at (asset, slug, tf, fire_us, fire_offset_s).

Joins:
  - fire universe (outcome + fill info)
  - microprice panel (mp_skew, mp_skew_change_500ms, mp_imbalance)
  - LM at fires (lm_L_stat_at_fire, lm_last_jump_dir_60s, lm_has_jump_60s)
  - VPIN/Hawkes at fires (hawkes_lambda_imbalance, hawkes_lambda_total, hawkes_recent_burst)
  - Microstructure (imb5_diff, up_imb5, dn_imb5, up_microprice, dn_microprice)
  - Regime panel (sampled at ws_s): trend_slope_30m, atr_14, bb_width_60s
  - SMS panel (sampled at ws_s): liquidity_up, liquidity_dn, trend_strength_raw

Output: strategy_lab/cross_feature_2026_05_26/master.parquet
"""
import pandas as pd
import numpy as np
import sys
import os

ROOT = "C:/Users/alexandre bandarra/Desktop/global"
sys.path.insert(0, ROOT)

OUT_DIR = f"{ROOT}/strategy_lab/cross_feature_2026_05_26"
os.makedirs(OUT_DIR, exist_ok=True)


def join_microprice(fires: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for asset in ["BTC", "ETH", "SOL"]:
        path = f"{ROOT}/strategy_lab/microprice_2026_05_26/micro_price_panel_{asset.lower()}.parquet"
        df = pd.read_parquet(path, columns=[
            "asset", "slug", "tf", "fire_us", "fire_offset_s",
            "mp_skew", "mp_skew_change_500ms", "mp_imbalance",
            "mp_weighted_skew", "mp_up_dev_bps", "mp_dn_dev_bps"
        ])
        parts.append(df)
    mp = pd.concat(parts, ignore_index=True)
    print(f"microprice merged rows: {len(mp):,}")
    return fires.merge(mp, on=["asset", "slug", "tf", "fire_us", "fire_offset_s"], how="left")


def join_lm(fires: pd.DataFrame) -> pd.DataFrame:
    lm5 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/lm_at_fires_5m.parquet", columns=[
        "asset", "slug", "tf", "fire_us", "fire_offset_s",
        "lm_L_stat_at_fire", "lm_last_jump_dir_60s", "lm_has_jump_60s",
        "lm_last_jump_dir_30s", "lm_has_jump_30s",
        "lm_n_jumps_in_last_300s",
    ])
    lm15 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/lm_at_fires_15m.parquet", columns=[
        "asset", "slug", "tf", "fire_us", "fire_offset_s",
        "lm_L_stat_at_fire", "lm_last_jump_dir_60s", "lm_has_jump_60s",
        "lm_last_jump_dir_30s", "lm_has_jump_30s",
        "lm_n_jumps_in_last_300s",
    ])
    lm = pd.concat([lm5, lm15], ignore_index=True)
    print(f"lm merged rows: {len(lm):,}")
    return fires.merge(lm, on=["asset", "slug", "tf", "fire_us", "fire_offset_s"], how="left")


def join_hawkes(fires: pd.DataFrame) -> pd.DataFrame:
    hk = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/vpin_hawkes_at_fires.parquet", columns=[
        "asset", "slug", "tf", "fire_us", "fire_offset_s",
        "vpin_value", "vpin_zscore",
        "hawkes_lambda_total", "hawkes_lambda_imbalance", "hawkes_recent_burst",
    ])
    print(f"hawkes merged rows: {len(hk):,}")
    return fires.merge(hk, on=["asset", "slug", "tf", "fire_us", "fire_offset_s"], how="left")


def join_microstructure(fires: pd.DataFrame) -> pd.DataFrame:
    parts = []
    for asset in ["BTC", "ETH", "SOL"]:
        path = f"{ROOT}/strategy_lab/microstructure_2026_05_26/micro_panel_{asset.lower()}.parquet"
        df = pd.read_parquet(path, columns=[
            "asset", "slug", "tf", "fire_us", "fire_offset_s",
            "up_imb1", "up_imb5", "dn_imb1", "dn_imb5", "imb5_diff",
            "up_micro_dev_bps", "dn_micro_dev_bps",
        ])
        parts.append(df)
    mst = pd.concat(parts, ignore_index=True)
    print(f"microstructure merged rows: {len(mst):,}")
    return fires.merge(mst, on=["asset", "slug", "tf", "fire_us", "fire_offset_s"], how="left")


def join_regime_sms(fires: pd.DataFrame) -> pd.DataFrame:
    """Asof-join regime + sms panels into fires on (asset, tf, ws_s)."""
    target_cols = ["trend_slope_30m", "bb_width_60s", "realized_vol_60m",
                   "regime_label", "regime_score", "adx_14",
                   "liquidity_up", "liquidity_dn", "trend_strength_raw",
                   "cvd_sign", "system_confidence"]
    for c in target_cols:
        if c not in fires.columns:
            fires[c] = pd.NA

    # Build per-tf merged regime+sms tables
    pieces = []
    for tf in ["5m", "15m"]:
        rg = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/regime_panel_{tf}.parquet", columns=[
            "asset", "tf", "ts_s",
            "trend_slope_30m", "bb_width_60s", "realized_vol_60m",
            "regime_label", "regime_score", "adx_14",
        ])
        sm = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/sms_panel_{tf}.parquet", columns=[
            "asset", "ts_us",
            "liquidity_up", "liquidity_dn", "trend_strength_raw",
            "cvd_sign", "system_confidence",
        ])
        sm["ts_s"] = (sm["ts_us"] // 1_000_000).astype("int64")
        sm = sm.drop(columns=["ts_us"])
        sm["tf"] = tf
        merged = rg.merge(sm, on=["asset", "tf", "ts_s"], how="outer")
        pieces.append(merged)
        print(f"regime+sms {tf} merged rows: {len(merged):,}")

    # Asof per (asset, tf)
    out_parts = []
    for tf in ["5m", "15m"]:
        rgsm = pieces[0] if tf == "5m" else pieces[1]
        for asset in ["BTC", "ETH", "SOL"]:
            sub = fires[(fires["tf"] == tf) & (fires["asset"] == asset)].copy()
            if sub.empty:
                continue
            ra = rgsm[rgsm["asset"] == asset].sort_values("ts_s")
            if ra.empty:
                out_parts.append(sub)
                continue
            sub = sub.sort_values("ws_s")
            cols_drop = [c for c in ["asset", "tf"] if c in ra.columns]
            joined = pd.merge_asof(
                sub.drop(columns=target_cols, errors="ignore"),
                ra.drop(columns=cols_drop),
                left_on="ws_s", right_on="ts_s",
                direction="backward",
                allow_exact_matches=True,
                tolerance=3600,
            )
            out_parts.append(joined)
    out = pd.concat(out_parts, ignore_index=True)
    print(f"After regime+sms asof: {len(out):,}")
    return out


def main():
    fires5 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/hybrid_fire_universe_5m.parquet")
    fires15 = pd.read_parquet(f"{ROOT}/data/v4/canonical/_results/hybrid_fire_universe_15m.parquet")
    fires = pd.concat([fires5, fires15], ignore_index=True)
    print(f"fire universe combined rows: {len(fires):,}")

    fires = join_microprice(fires)
    fires = join_lm(fires)
    fires = join_hawkes(fires)
    fires = join_microstructure(fires)
    fires = join_regime_sms(fires)

    # Save
    out_path = f"{OUT_DIR}/master.parquet"
    fires.to_parquet(out_path, index=False)
    print(f"Saved master to {out_path}")
    print(f"Final rows: {len(fires):,}, cols: {len(fires.columns)}")
    print(f"Per (asset, tf):")
    print(fires.groupby(["asset", "tf"]).size())

    # Coverage of key features
    print("\nFeature coverage (non-null %):")
    for c in ["mp_skew", "lm_L_stat_at_fire", "lm_last_jump_dir_60s",
              "hawkes_lambda_imbalance", "imb5_diff",
              "trend_slope_30m", "liquidity_up", "liquidity_dn"]:
        if c in fires.columns:
            print(f"  {c}: {fires[c].notna().mean()*100:.1f}%")


if __name__ == "__main__":
    main()
