"""
Sample VPIN + Hawkes features at fire_us - 1s (causal) for every fire in 5m & 15m universes.
Outputs: data/v4/canonical/_results/vpin_hawkes_at_fires.parquet
"""
import pandas as pd
import numpy as np

VPIN = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_panel.parquet"
HAWKES = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hawkes_panel.parquet"
FIRES_5M = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hybrid_fire_universe_5m.parquet"
FIRES_15M = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hybrid_fire_universe_15m.parquet"
OUT = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_hawkes_at_fires.parquet"


def asof_lookup(target_ts_us: np.ndarray, panel_ts: np.ndarray, panel_vals: dict) -> dict:
    """For each target, find last panel row at-or-before target. Returns dict of arrays."""
    idx = np.searchsorted(panel_ts, target_ts_us, side="right") - 1
    out = {}
    for k, v in panel_vals.items():
        out_arr = np.full(len(target_ts_us), np.nan, dtype=v.dtype if v.dtype != np.int8 else np.float32)
        valid = idx >= 0
        out_arr[valid] = v[idx[valid]]
        out[k] = out_arr
    return out


def hawkes_rolling_mean(panel_ts: np.ndarray, lam_tot: np.ndarray) -> np.ndarray:
    """Rolling mean of lam_total over 3600s for burst comparison at fire time."""
    return pd.Series(lam_tot).rolling(3600, min_periods=600).mean().to_numpy()


def main():
    print("loading VPIN panel")
    vpin = pd.read_parquet(VPIN)
    print("loading Hawkes panel")
    hawk = pd.read_parquet(HAWKES)
    print("loading fire universes")
    f5 = pd.read_parquet(FIRES_5M)
    f5["src_tf"] = "5m"
    f15 = pd.read_parquet(FIRES_15M)
    f15["src_tf"] = "15m"
    fires = pd.concat([f5, f15], ignore_index=True)
    print(f"  total fires: {len(fires):,}")

    # Causal target: fire_us - 1 second
    fires["target_us"] = fires["fire_us"].astype(np.int64) - 1_000_000

    panels = []
    for asset in ["BTC", "ETH", "SOL"]:
        sub_f = fires[fires["asset"] == asset].copy()
        if len(sub_f) == 0: continue
        sub_v = vpin[vpin["asset"] == asset].sort_values("ts_us").reset_index(drop=True)
        sub_h = hawk[hawk["asset"] == asset].sort_values("ts_us").reset_index(drop=True)
        print(f"\n[{asset}] fires={len(sub_f):,}  vpin_rows={len(sub_v):,} hawkes_rows={len(sub_h):,}")

        # Sort fires by target_us, keep original index for re-merge
        sub_f = sub_f.sort_values("target_us").reset_index(drop=False).rename(columns={"index": "orig_idx"})
        tgt = sub_f["target_us"].to_numpy()

        # VPIN lookup
        vt = sub_v["ts_us"].to_numpy()
        v_out = asof_lookup(tgt, vt, {
            "vpin_value": sub_v["vpin_value"].to_numpy(),
            "vpin_zscore": sub_v["vpin_zscore"].to_numpy(),
        })

        # Hawkes lookup + recent_burst at fire time
        ht = sub_h["ts_us"].to_numpy()
        lam_tot = sub_h["lambda_total"].to_numpy()
        lam_imb = sub_h["lambda_imbalance"].to_numpy()
        # Compute rolling mean of lam_total to flag burst at fire time
        lam_tot_roll = hawkes_rolling_mean(ht, lam_tot)
        h_out = asof_lookup(tgt, ht, {
            "hawkes_lambda_total": lam_tot,
            "hawkes_lambda_imbalance": lam_imb,
            "hawkes_lam_total_roll": lam_tot_roll,
        })

        for k, v in v_out.items(): sub_f[k] = v
        for k, v in h_out.items(): sub_f[k] = v
        sub_f["hawkes_recent_burst"] = (sub_f["hawkes_lambda_total"] > 1.5 * sub_f["hawkes_lam_total_roll"]).astype(np.int8)
        panels.append(sub_f)

    out = pd.concat(panels, ignore_index=True).sort_values("orig_idx").drop(columns=["orig_idx"])
    # keep needed cols only
    keep = ["asset","slug","tf","fire_offset_s","fire_us","outcome",
            "vpin_value","vpin_zscore",
            "hawkes_lambda_total","hawkes_lambda_imbalance","hawkes_recent_burst",
            "ret_2m_at_ws","vwap_since_open_bps"]
    out = out[[c for c in keep if c in out.columns]]
    print(f"\nwriting: {out.shape} -> {OUT}")
    out.to_parquet(OUT, index=False)

    print("\nFeature coverage (non-nan %):")
    for c in out.columns:
        nn = out[c].notna().mean()
        print(f"  {c}: {nn*100:.1f}%")
    print("\nBy asset/tf:")
    print(out.groupby(["asset","tf"]).agg(n=("fire_us","size"), vpin_q90=("vpin_zscore", lambda x: x.quantile(0.9)),
        burst_pct=("hawkes_recent_burst","mean")).to_string())


if __name__ == "__main__":
    main()
