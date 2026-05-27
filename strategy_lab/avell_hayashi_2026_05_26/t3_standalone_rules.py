"""TASK 3 — Standalone AS / HY rule tests.

AS rules (per (asset, tf, offset, rule)):
  AS-A: SKIP fires when as_uncertainty_norm > 2  (we report PnL of the EXCLUDED set vs INCLUDED set)
  AS-B: bet WITH 30s return direction when as_uncertainty_norm < 0.5 (stable; momentum reliable)
  AS-C: bet UP when as_skew > 0 AND close_fire > vwap_slot

HY rules:
  HY-A: SKIP — HY showed no venue leads binance at peak; per the analysis below,
        no actionable lead/lag exists. We instead report a "HY-coinbase-WITH"
        rule using coinbase 1m return sign as the direction picker, but this is
        a CONTEMPORANEOUS (not leading) signal — it functions more as
        cross-confirmation than as a lead.

Outputs: standalone_rules_results.csv
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))
from load import load_klines  # noqa: E402

OUT_DIR = os.path.join(ROOT, "strategy_lab", "avell_hayashi_2026_05_26")
RES_DIR = os.path.join(ROOT, "data", "v4", "canonical", "_results")

ASSETS = ("BTC", "ETH", "SOL")


def stats_block(df: pd.DataFrame, pnl_col: str = "pnl") -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": np.nan}
    pnl = df[pnl_col].to_numpy()
    pnl = pnl[np.isfinite(pnl)]
    if len(pnl) == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": np.nan}
    wins = (pnl > 0).sum()
    return {
        "n": int(len(pnl)),
        "wr": float(wins / len(pnl)),
        "dpt": float(pnl.mean()),
        "sum": float(pnl.sum()),
    }


def main() -> None:
    t0 = time.time()
    print("[T3] loading AS panel...", flush=True)
    asp = pd.read_parquet(os.path.join(RES_DIR, "as_panel.parquet"))
    print(f"  {len(asp):,} rows t={time.time()-t0:.1f}s")

    # Add a "BOTH-side" pick: long whichever side is firing per rule. For
    # standalone PnL we evaluate UP and DOWN separately, plus pick-the-better.
    asp["fire_offset_s"] = (asp["slot_end_us"] - asp["fire_us"]) // 1_000_000
    # offset bucket
    def offset_bucket(s):
        try:
            s = int(s)
        except Exception:
            return "x"
        if s <= 60: return "0_60"
        if s <= 120: return "60_120"
        if s <= 180: return "120_180"
        if s <= 240: return "180_240"
        if s <= 360: return "240_360"
        if s <= 600: return "360_600"
        return "600plus"
    asp["off_bucket"] = asp["fire_offset_s"].apply(offset_bucket)

    # Pre-compute coinbase 1m direction-at-fire (HY rule)
    # Load coinbase 1m closes and lookup sign of ret_1m at fire_us. Use only when available.
    print("[T3] loading coinbase 1m for HY rule...", flush=True)
    cb_lookup = {}
    for a in ASSETS:
        try:
            v = load_klines(a, source="coinbase-spot-ws", period_id="1MIN")
            if v.empty:
                continue
            v = v.sort_values("time_period_start_us").drop_duplicates("time_period_start_us").reset_index(drop=True)
            end_us = v["time_period_start_us"].to_numpy() + 60_000_000
            close = v["price_close"].astype(np.float64).to_numpy()
            lr = np.concatenate([[np.nan], np.diff(np.log(close))])
            cb_lookup[a] = (end_us, lr)
        except Exception as e:
            print(f"  {a} coinbase load failed: {e}")
    print(f"  loaded coinbase for {list(cb_lookup.keys())}")

    cb_sign = np.full(len(asp), np.nan)
    cb_lr_at_fire = np.full(len(asp), np.nan)
    for a in ASSETS:
        if a not in cb_lookup: continue
        end_us, lr = cb_lookup[a]
        mask = asp["asset"].to_numpy() == a
        rows = np.where(mask)[0]
        fu = asp.loc[rows, "fire_us"].to_numpy()
        idx = np.searchsorted(end_us, fu, side="right") - 1
        valid = idx >= 0
        v = np.full(rows.size, np.nan)
        v[valid] = lr[idx[valid]]
        cb_lr_at_fire[rows] = v
        cb_sign[rows] = np.sign(v)
    asp["cb_lr_1m"] = cb_lr_at_fire
    asp["cb_sign"] = cb_sign

    # ret_30s sign at fire from vol_hurst panel (also has g_rv_with from agent R)
    print("[T3] loading vol_hurst panels for ret_30s sign...", flush=True)
    vh5 = pd.read_parquet(os.path.join(RES_DIR, "vol_hurst_at_fire_5m.parquet"),
                          columns=["asset","tf","slug","fire_us","ret_30s","ret_30s_sign"])
    vh15 = pd.read_parquet(os.path.join(RES_DIR, "vol_hurst_at_fire_15m.parquet"),
                          columns=["asset","tf","slug","fire_us","ret_30s","ret_30s_sign"])
    vh = pd.concat([vh5, vh15], ignore_index=True)
    asp = asp.merge(vh[["asset","tf","slug","fire_us","ret_30s","ret_30s_sign"]],
                    on=["asset","tf","slug","fire_us"], how="left")
    print(f"  ret_30s merged t={time.time()-t0:.1f}s")

    # Define rule masks
    print("[T3] evaluating rules...", flush=True)
    results = []

    for (asset, tf), grp in asp.groupby(["asset", "tf"]):
        if len(grp) == 0: continue

        # ---- Rule AS-A: SKIP when as_uncertainty_norm > 2 ----
        # Compare INCLUDED (norm <= 2) vs EXCLUDED (norm > 2)
        # PnL = pnl_legacy_up (we evaluate UP direction as illustrative; also DOWN+BOTH)
        for direction, pnl_col in [("UP","pnl_legacy_up"), ("DOWN","pnl_legacy_dn")]:
            inc = grp[grp["as_uncertainty_norm_24h"] <= 2.0]
            exc = grp[grp["as_uncertainty_norm_24h"] > 2.0]
            s_inc = stats_block(inc, pnl_col)
            s_exc = stats_block(exc, pnl_col)
            for label, s in [(f"AS-A_kept_{direction}", s_inc), (f"AS-A_skipped_{direction}", s_exc)]:
                results.append({"asset": asset, "tf": tf, "rule": label, **s})

        # ---- Rule AS-B: bet WITH 30s return direction when norm < 0.5 ----
        stable = grp[grp["as_uncertainty_norm_24h"] < 0.5].copy()
        # If ret_30s_sign>0 → bet UP, else bet DOWN. Compute PnL accordingly.
        pnl_with = np.where(
            stable["ret_30s_sign"].fillna(0).to_numpy() > 0,
            stable["pnl_legacy_up"].to_numpy(),
            np.where(stable["ret_30s_sign"].fillna(0).to_numpy() < 0,
                     stable["pnl_legacy_dn"].to_numpy(), np.nan),
        )
        s_b = stats_block(pd.DataFrame({"pnl": pnl_with}))
        results.append({"asset": asset, "tf": tf, "rule": "AS-B_with_30s", **s_b})

        # ---- Rule AS-C: bet UP when as_skew > 0 AND close_fire > vwap_slot ----
        mask = (grp["as_skew"].fillna(-1) > 0) & (grp["close_fire"] > grp["vwap_slot"])
        sub = grp[mask]
        s_c = stats_block(sub, "pnl_legacy_up")
        results.append({"asset": asset, "tf": tf, "rule": "AS-C_skew_UP", **s_c})

        # ---- Rule HY-A: bet WITH coinbase 1m direction (CONTEMPORANEOUS only, not lead) ----
        hy_mask = grp["cb_sign"].fillna(0) != 0
        hy_sub = grp[hy_mask].copy()
        pnl_hy = np.where(
            hy_sub["cb_sign"].to_numpy() > 0,
            hy_sub["pnl_legacy_up"].to_numpy(),
            hy_sub["pnl_legacy_dn"].to_numpy(),
        )
        s_hy = stats_block(pd.DataFrame({"pnl": pnl_hy}))
        results.append({"asset": asset, "tf": tf, "rule": "HY-A_cb_with", **s_hy})

        # offset-bucketed AS-B
        for ob in ["0_60","60_120","120_180","180_240","240_360"]:
            sub_ob = grp[(grp["off_bucket"] == ob) & (grp["as_uncertainty_norm_24h"] < 0.5)]
            if len(sub_ob) < 30: continue
            pnl = np.where(
                sub_ob["ret_30s_sign"].fillna(0).to_numpy() > 0,
                sub_ob["pnl_legacy_up"].to_numpy(),
                np.where(sub_ob["ret_30s_sign"].fillna(0).to_numpy() < 0,
                         sub_ob["pnl_legacy_dn"].to_numpy(), np.nan),
            )
            s_ob = stats_block(pd.DataFrame({"pnl": pnl}))
            results.append({"asset": asset, "tf": tf, "rule": f"AS-B_with_30s_off_{ob}", **s_ob})

        # offset-bucketed HY-A
        for ob in ["0_60","60_120","120_180","180_240","240_360"]:
            sub_ob = grp[(grp["off_bucket"] == ob) & (grp["cb_sign"].fillna(0) != 0)]
            if len(sub_ob) < 30: continue
            pnl = np.where(
                sub_ob["cb_sign"].to_numpy() > 0,
                sub_ob["pnl_legacy_up"].to_numpy(),
                sub_ob["pnl_legacy_dn"].to_numpy(),
            )
            s_ob = stats_block(pd.DataFrame({"pnl": pnl}))
            results.append({"asset": asset, "tf": tf, "rule": f"HY-A_cb_with_off_{ob}", **s_ob})

    res = pd.DataFrame(results)
    out = os.path.join(OUT_DIR, "standalone_rules_results.csv")
    res.to_csv(out, index=False)
    print(f"\n[T3] saved {out} ({len(res)} rows) t={time.time()-t0:.1f}s")
    # Print top rules by per-trade
    res_valid = res[res["n"] >= 100].sort_values("dpt", ascending=False)
    print("\nTop 25 standalone rules (n>=100, by $/tr):")
    print(res_valid.head(25).to_string(index=False))
    print("\nBottom 10 (worst):")
    print(res_valid.tail(10).to_string(index=False))


if __name__ == "__main__":
    main()
