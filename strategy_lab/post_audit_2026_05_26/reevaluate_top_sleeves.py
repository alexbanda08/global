"""TASK 3: Re-run top sleeves on CLEAN (v2_fixed) panels.

Reads:
  - data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_{asset}_{tf}_v2_fixed.parquet
    (9-offset 5m / 8-offset 15m — Bug #1 fixed)

For each top sleeve from MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26 (per-market top + DEPLOY roster),
applies the same gate stack to the CLEAN panel and computes:
  - n_lockbox_clean, WR_lockbox_clean, $/tr_lockbox_clean
  - sum_lockbox_clean (4d), scaled to /28d via 28/3.96
  - inflation_ratio = orig_lockbox_pnl / clean_lockbox_pnl

Output:
  data/v4/canonical/_results/master_sleeve_catalog_v2_clean.csv
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
from typing import Tuple
import pandas as pd
import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
FW = RES / "_full_window_2026_05_26"

LOCKBOX_DAYS = 3.96
SCALE_28D = 28.0 / LOCKBOX_DAYS  # = 7.07x

# Sleeve registry: (sleeve_id, asset, tf, off_lo, off_hi, gate_stack_list, direction_pick)
# Pulled from MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md sections 3 + 4
TOP_SLEEVES = [
    # 12 DEPLOY (from manifest)
    ("R2_btc_5m_s1_5_3bps", "BTC", "5m", 60, 180,
     ["g_within_dev", "g_rf_strong", "g_ribbon_agrees"], "BOTH"),
    ("R5_microprice_univ_5m_rf_ribbon", "UNIV", "5m", 60, 300,
     ["__mp_no_extreme__", "g_rf_with", "g_ribbon_agrees"], "BOTH"),
    ("S7_btc_5m_base", "BTC", "5m", 120, 300,
     ["g_cci_with", "g_stoch_with", "g_rf_with",
      "g_tr_above_ema50", "g_tr_above_ema200", "g_ribbon_agrees"], "BOTH"),
    ("R1_eth_5m_s6_tight_pos_cloud", "ETH", "5m", 60, 150,
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees",
      "g_tr_above_cloud", "g_tight_ribbon"], "BOTH"),
    ("poly_updown_btc_5m_s6_hybrid_v1", "BTC", "5m", 60, 150,
     ["g_cci_with", "g_stoch_with", "g_rf_with",
      "g_tr_above_ema50", "g_ribbon_agrees"], "BOTH"),
    ("poly_updown_btc_5m_s15_hybrid_v1", "BTC", "5m", 150, 240,
     ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with",
      "g_tight_ribbon"], "BOTH"),
    ("poly_updown_sol_5m_s6_hybrid_v1", "SOL", "5m", 60, 150,
     ["g_mfi_with", "g_bb_pos_with", "g_ribbon_agrees"], "BOTH"),
    ("R5_btc_s15_v1_plus_mp_no_extreme", "BTC", "5m", 150, 240,
     ["g_tr_above_pp", "g_ribbon_agrees", "g_stoch_with",
      "g_tight_ribbon", "__mp_no_extreme__"], "BOTH"),
    ("R5_hawkes_btc_5m_off120", "BTC", "5m", 90, 150,
     ["__hawkes_imb_with__"], "HAWKES"),
    ("R5_eth_s6_v1_plus_mp_change_with", "ETH", "5m", 60, 150,
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees",
      "__mp_change_with__"], "BOTH"),
    ("R5_hawkes_sol_5m_off120", "SOL", "5m", 90, 150,
     ["__hawkes_imb_with__"], "HAWKES"),
    ("R4_POOL_15m_600_720_ribbon_slope_vwap", "BTC", "15m", 600, 720,
     ["g_ribbon_agrees", "g_rf_strong", "g_within_dev"], "BOTH"),
    # PAPER_FIRST candidates (top by sum_28d) — R1 lite/top2 + S2 fade
    ("R1_btc_5m_s6_lite", "BTC", "5m", 60, 150,
     ["g_cci_with", "g_ribbon_agrees"], "BOTH"),
    ("R1_btc_5m_s6_top2", "BTC", "5m", 60, 150,
     ["g_cci_with", "g_rf_with", "g_ribbon_agrees"], "BOTH"),
    # Per-market section 3 leaders that map to oos_fires base gates
    ("S6TA_btc_top1", "BTC", "5m", 60, 150,
     ["g_cci_with", "g_stoch_with", "g_rf_with",
      "g_tr_above_ema50", "g_ribbon_agrees"], "BOTH"),
    ("S6TA_eth_top1", "ETH", "5m", 60, 150,
     ["g_cci_with", "g_bb_pos_with", "g_ribbon_agrees"], "BOTH"),
    # ETH S15
    ("poly_updown_eth_5m_s15_hybrid_v1", "ETH", "5m", 150, 240,
     ["g_ribbon_agrees", "g_tr_above_ema200", "g_stoch_with",
      "g_bb_pos_with", "g_cci_with"], "BOTH"),
    # R5 Hawkes ETH (deploy negative — confirm)
    ("R5_hawkes_eth_5m_off120", "ETH", "5m", 90, 150,
     ["__hawkes_imb_with__"], "HAWKES"),
    # ETH S6 + LM high stat (R5)
    ("R5_btc_s6_v1_plus_lm_high_stat", "BTC", "5m", 60, 150,
     ["g_cci_with", "g_stoch_with", "g_rf_with",
      "g_tr_above_ema50", "g_ribbon_agrees", "__lm_high_stat__"], "BOTH"),
    # S2 fade BTC/ETH
    ("S2_btc_fade", "BTC", "5m", 120, 300,
     ["g_dev_extreme", "g_ribbon_agrees"], "BOTH"),
]


# Load CLEAN panels (v2_fixed = 9-offset 5m, 8-offset 15m)
def load_clean_panels() -> dict:
    panels = {}
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            p = FW / f"oos_fires_{asset}_{tf}_v2_fixed.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                for g in [c for c in df.columns if c.startswith("g_")]:
                    df[g] = pd.to_numeric(df[g], errors="coerce").fillna(0).astype(int)
                panels[(asset, tf)] = df
                print(f"  loaded {asset} {tf}: {len(df):,} rows")
    return panels


def load_orig_panels() -> dict:
    panels = {}
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            p = FW / f"oos_fires_{asset}_{tf}.parquet"
            if p.exists():
                df = pd.read_parquet(p)
                for g in [c for c in df.columns if c.startswith("g_")]:
                    df[g] = pd.to_numeric(df[g], errors="coerce").fillna(0).astype(int)
                panels[(asset, tf)] = df
    return panels


def apply_gate_stack(df: pd.DataFrame, off_lo: int, off_hi: int,
                     gates: list, direction_pick: str,
                     overlays: dict | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    mask = (df["fire_offset_s"] >= off_lo) & (df["fire_offset_s"] <= off_hi)
    df = df[mask].copy()
    if df.empty:
        return df
    core = [g for g in gates if not g.startswith("__")]
    overs = [g for g in gates if g.startswith("__")]
    m = pd.Series(True, index=df.index)
    for g in core:
        if g not in df.columns:
            m &= False
        else:
            m &= (df[g] == 1)
    df = df[m].copy()
    if df.empty:
        return df

    if overlays is not None:
        mp = overlays.get("mp")
        hk = overlays.get("hk")
        lm = overlays.get("lm")
        for og in overs:
            if og == "__mp_no_extreme__" and mp is not None:
                df = df.merge(mp[["slug", "fire_us", "g_mp_no_extreme"]],
                              on=["slug", "fire_us"], how="left")
                df = df[df["g_mp_no_extreme"] == 1]
            elif og == "__mp_change_with__" and mp is not None:
                df = df.merge(mp[["slug", "fire_us", "mp_change_sign"]],
                              on=["slug", "fire_us"], how="left")
                dir_num = df["direction"].map({"UP": 1, "DOWN": -1}).fillna(0).astype(int)
                df = df[df["mp_change_sign"] == dir_num]
            elif og == "__lm_high_stat__" and lm is not None:
                df = df.merge(lm[["slug", "fire_us", "g_lm_high_stat"]],
                              on=["slug", "fire_us"], how="left")
                df = df[df["g_lm_high_stat"] == 1]
            elif og == "__hawkes_imb_with__" and hk is not None:
                asset_lc = df["asset"].iloc[0] if len(df) else None
                hk_a = hk[hk["asset"] == asset_lc].sort_values("ts_us")
                if len(hk_a) == 0:
                    df = df.iloc[0:0]
                    continue
                df = df.sort_values("fire_us")
                df = pd.merge_asof(
                    df, hk_a[["ts_us", "lambda_imbalance"]],
                    left_on="fire_us", right_on="ts_us",
                    direction="backward", tolerance=10_000_000,
                )
                df = df.dropna(subset=["lambda_imbalance"])
                df = df[df["lambda_imbalance"].abs() > 0.3]
                hawkes_dir = np.where(df["lambda_imbalance"] > 0, "UP", "DOWN")
                df = df[df["direction"] == hawkes_dir]

    if direction_pick == "UP":
        df = df[df["direction"] == "UP"]
    elif direction_pick == "DOWN":
        df = df[df["direction"] == "DOWN"]
    return df


def stats_of(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "sum": 0.0}
    return {
        "n": n,
        "wr": float(df["won"].mean()),
        "dpt": float(df["pnl_legacy_usd"].mean()),
        "sum": float(df["pnl_legacy_usd"].sum()),
    }


def main():
    print("Loading clean panels (v2_fixed)…")
    panels_clean = load_clean_panels()
    print("Loading original panels…")
    panels_orig = load_orig_panels()

    # Load overlay data (microprice, hawkes, lm)
    mp = pd.read_parquet(RES / "microprice_panel.parquet")[
        ["asset", "slug", "tf", "fire_us", "fire_offset_s", "mp_skew",
         "mp_weighted_skew", "mp_up_dev_change_500ms"]].copy()
    mp["g_mp_no_extreme"] = (mp["mp_skew"].abs() < 50).astype(int)
    mp["mp_change_sign"] = np.sign(mp["mp_up_dev_change_500ms"]).fillna(0).astype(int)

    hk = pd.read_parquet(RES / "hawkes_panel.parquet")
    hk = hk.sort_values(["asset", "ts_us"]).reset_index(drop=True)

    lm = pd.read_parquet(RES / "lm_at_fires_5m.parquet")[
        ["asset", "slug", "fire_us", "fire_offset_s", "lm_L_stat_at_fire"]].copy()
    lm["g_lm_high_stat"] = (lm["lm_L_stat_at_fire"] > 5.97).fillna(False).astype(int)
    overlays = {"mp": mp, "hk": hk, "lm": lm}

    rows = []
    for (sid, asset, tf, lo, hi, gates, dpick) in TOP_SLEEVES:
        # CLEAN panel
        if asset == "UNIV":
            df_c = pd.concat([panels_clean.get((a, tf), pd.DataFrame()) for a in ("BTC", "ETH", "SOL")],
                             ignore_index=True)
            df_o = pd.concat([panels_orig.get((a, tf), pd.DataFrame()) for a in ("BTC", "ETH", "SOL")],
                             ignore_index=True)
        else:
            df_c = panels_clean.get((asset, tf), pd.DataFrame())
            df_o = panels_orig.get((asset, tf), pd.DataFrame())

        sub_c = apply_gate_stack(df_c, lo, hi, gates, dpick, overlays)
        sub_o = apply_gate_stack(df_o, lo, hi, gates, dpick, overlays)
        s_c = stats_of(sub_c)
        s_o = stats_of(sub_o)
        # Inflation
        n_inflation = s_o["n"] / max(s_c["n"], 1)
        pnl_inflation = s_o["sum"] / max(s_c["sum"], 1e-9)
        rows.append({
            "sleeve_id": sid,
            "asset": asset, "tf": tf,
            "off_lo": lo, "off_hi": hi,
            "gate_stack": "&".join(gates),
            "direction_pick": dpick,
            # ORIGINAL (20-offset) numbers
            "n_orig": s_o["n"], "WR_orig": s_o["wr"],
            "dpt_orig": s_o["dpt"], "sum_orig": s_o["sum"],
            "sum_28d_orig_wrong_scaling": s_o["sum"] * (28.0 / 32.0),
            "sum_28d_orig_correct_scaling": s_o["sum"] * SCALE_28D,
            # CLEAN (9-offset) numbers
            "n_clean": s_c["n"], "WR_clean": s_c["wr"],
            "dpt_clean": s_c["dpt"], "sum_clean": s_c["sum"],
            "sum_28d_clean": s_c["sum"] * SCALE_28D,
            # Inflation
            "n_inflation_ratio": n_inflation,
            "pnl_inflation_ratio": pnl_inflation,
        })
        print(f"  {sid:50s}  n_orig={s_o['n']:5d} -> n_clean={s_c['n']:5d}  "
              f"WR {s_o['wr']:.3f}->{s_c['wr']:.3f}  "
              f"$/tr {s_o['dpt']:6.2f}->{s_c['dpt']:6.2f}  "
              f"sum_clean=${s_c['sum']:9.0f}  /28d=${s_c['sum']*SCALE_28D:9.0f}  "
              f"infl={pnl_inflation:.2f}x")

    df = pd.DataFrame(rows)
    out = RES / "master_sleeve_catalog_v2_clean.csv"
    df.to_csv(out, index=False)
    print(f"\nwrote {out}")
    print()
    print("=== SUMMARY: top 10 by clean /28d ===")
    print(df.sort_values("sum_28d_clean", ascending=False).head(10)[
        ["sleeve_id", "asset", "tf", "n_clean", "WR_clean", "dpt_clean",
         "sum_28d_clean", "pnl_inflation_ratio"]].to_string(index=False))


if __name__ == "__main__":
    main()
