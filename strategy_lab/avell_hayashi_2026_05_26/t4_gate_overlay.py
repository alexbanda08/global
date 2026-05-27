"""TASK 4 — AS + HY as binary gates on top 15 sleeves.

Gates:
  g_as_stable        = as_uncertainty_norm < 1
  g_as_unstable_skip = as_uncertainty_norm <= 2  (KEEP fires below 2; skip > 2)
  g_hy_xchg_with     = (coinbase 1m sign matches sleeve direction)  [no actual lead, just confirmation]
  g_overlap_low_vol  = (as_uncertainty_norm < 1) — proxy for "AS is essentially measuring vol regime"

Apply each gate (and pairs) to top 15 sleeves' filtered universe; report:
  base_n / base_wr / base_dpt | gated_n / gated_wr / gated_dpt | lift

Output: gate_overlay_results.csv
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = r"C:\Users\alexandre bandarra\Desktop\global"
sys.path.insert(0, os.path.join(ROOT, "data", "v4", "canonical"))

RES_DIR = os.path.join(ROOT, "data", "v4", "canonical", "_results")
OUT_DIR = os.path.join(ROOT, "strategy_lab", "avell_hayashi_2026_05_26")


SLEEVES = [
    # (sleeve_id, asset, tf, base, off_lo, off_hi, gates, direction_pick)
    ("01_btc_5m_s6_hybrid_v2_sms",  "BTC", "5m", "s6",  60, 150,
     ["g_cci_with","g_stoch_with","g_rf_with","g_tr_above_ema50","g_ribbon_agrees","g_sms_liq_reclaim_with"], "BOTH"),
    ("02_btc_5m_s6_hybrid_v1",      "BTC", "5m", "s6",  60, 150,
     ["g_cci_with","g_stoch_with","g_rf_with","g_tr_above_ema50","g_ribbon_agrees"], "BOTH"),
    ("03_eth_5m_s6_hybrid_v2_sms",  "ETH", "5m", "s6",  60, 150,
     ["g_cci_with","g_bb_pos_with","g_ribbon_agrees","g_sms_liq_reclaim_with"], "BOTH"),
    ("04_eth_5m_s6_hybrid_v1",      "ETH", "5m", "s6",  60, 150,
     ["g_cci_with","g_bb_pos_with","g_ribbon_agrees"], "BOTH"),
    ("05_btc_5m_off120_sms_liq",    "BTC", "5m", "s6",  120, 120,
     ["g_sms_liq_reclaim_with"], "BOTH"),
    ("06_eth_5m_s15_hybrid_v1",     "ETH", "5m", "s15", 150, 240,
     ["g_ribbon_agrees","g_tr_above_ema200","g_stoch_with","g_bb_pos_with","g_cci_with"], "BOTH"),
    ("07_btc_5m_s15_hybrid_v1",     "BTC", "5m", "s15", 150, 240,
     ["g_tr_above_pp","g_ribbon_agrees","g_stoch_with","g_tight_ribbon"], "BOTH"),
    ("08_sol_5m_s6_hybrid_v1",      "SOL", "5m", "s6",  60, 150,
     ["g_mfi_with","g_bb_pos_with","g_ribbon_agrees"], "BOTH"),
    ("09_btc_5m_xa_down",           "BTC", "5m", "s6",  60, 300,
     ["g_rf_with"], "DOWN"),
    ("10_btc_15m_s7_hybrid_v1",     "BTC", "15m", "v15m", 480, 840,
     ["g_tr_above_ema200","g_stoch_with"], "BOTH"),
    ("11_eth_15m_off120_240",       "ETH", "15m", "v15m", 120, 240,
     ["g_cci_with","g_tr_above_pp","g_tr_above_ema200"], "BOTH"),
    ("12_eth_15m_off60_120",        "ETH", "15m", "v15m",  60, 120,
     ["g_rf_aged","g_ribbon_agrees"], "BOTH"),
    ("13_pool_15m_offge480",        "BTC", "15m", "v15m", 480, 840,
     ["g_rf_in_band"], "BOTH"),
    ("14_sol_5m_drz_res_down",      "SOL", "5m", "s6",   60, 300,
     ["g_tr_above_pp"], "DOWN"),
    ("15_btc_15m_s7_tight",         "BTC", "15m", "v15m", 480, 840,
     ["g_tr_above_ema200","g_stoch_with","g_tight_ribbon"], "BOTH"),
]


def load_joined(base: str) -> pd.DataFrame:
    """Load _joined_all (has all g_* gates) and merge sms features from _with_sms."""
    j = pd.read_parquet(os.path.join(RES_DIR, f"{base}_joined_all.parquet"))
    sms_path = os.path.join(RES_DIR, f"{base}_with_sms.parquet")
    if os.path.exists(sms_path):
        s = pd.read_parquet(sms_path)
        # merge sms-specific cols on (slug, fire_us, direction)
        key_cols = ["slug","fire_us","direction"] if "direction" in s.columns else ["slug","fire_us"]
        # cols to bring
        sms_cols = [c for c in ("liquidity_up","liquidity_dn","bos_buy","bos_sell",
                                "choch_buy","choch_sell","cvd_sign","trend_5m","trend_15m") if c in s.columns]
        if sms_cols:
            s = s[key_cols + sms_cols].drop_duplicates(key_cols)
            j = j.merge(s, on=key_cols, how="left", suffixes=("", "_sms"))
    return j


def add_g_sms_liq_reclaim_with(df: pd.DataFrame) -> pd.DataFrame:
    """Replicate the sms gate: liquidity_up>0 if direction=Up, liquidity_dn>0 if direction=Down."""
    if "liquidity_up" not in df.columns or "liquidity_dn" not in df.columns:
        df["g_sms_liq_reclaim_with"] = 0
        return df
    out = np.zeros(len(df), dtype=np.int8)
    d = df["direction"].astype(str).str.upper().to_numpy()
    lu = pd.to_numeric(df["liquidity_up"], errors="coerce").fillna(0).to_numpy()
    ld = pd.to_numeric(df["liquidity_dn"], errors="coerce").fillna(0).to_numpy()
    out[(d == "UP") & (lu > 0)] = 1
    out[(d == "DOWN") & (ld > 0)] = 1
    df["g_sms_liq_reclaim_with"] = out
    return df


def stats(pnl: np.ndarray) -> tuple[int, float, float, float]:
    pnl = pnl[np.isfinite(pnl)]
    n = len(pnl)
    if n == 0:
        return 0, np.nan, np.nan, np.nan
    wins = (pnl > 0).sum()
    return n, float(wins/n), float(pnl.mean()), float(pnl.sum())


def main() -> None:
    t0 = time.time()
    print("[T4] loading AS panel...", flush=True)
    asp = pd.read_parquet(os.path.join(RES_DIR, "as_panel.parquet"),
                          columns=["asset","tf","slug","fire_us","as_uncertainty_norm_24h","as_skew","close_fire","vwap_slot"])
    # Build a fast lookup
    asp["key"] = asp["asset"] + "|" + asp["tf"] + "|" + asp["slug"] + "|" + asp["fire_us"].astype(str)
    as_map = asp.drop_duplicates("key").set_index("key")
    print(f"  AS rows={len(asp):,} unique-keys={len(as_map):,} t={time.time()-t0:.1f}s")

    # Coinbase sign per (asset, fire_us)
    print("[T4] loading coinbase 1m for HY rule...", flush=True)
    from load import load_klines
    cb_lookup = {}
    for a in ("BTC","ETH","SOL"):
        try:
            v = load_klines(a, source="coinbase-spot-ws", period_id="1MIN")
            if v.empty: continue
            v = v.sort_values("time_period_start_us").drop_duplicates("time_period_start_us").reset_index(drop=True)
            end_us = v["time_period_start_us"].to_numpy() + 60_000_000
            close = v["price_close"].astype(np.float64).to_numpy()
            lr = np.concatenate([[np.nan], np.diff(np.log(close))])
            cb_lookup[a] = (end_us, lr)
        except Exception as e:
            print(f"  {a}: {e}")

    # Pre-load joined panels
    bases = {}
    for base in ("s6","s15","v15m"):
        bases[base] = load_joined(base)
        bases[base] = add_g_sms_liq_reclaim_with(bases[base])
        print(f"  {base}: {bases[base].shape}")

    out_rows = []
    for sleeve in SLEEVES:
        sid, asset, tf, base, off_lo, off_hi, gates, dir_pick = sleeve
        df = bases[base]
        # Filter to asset + offset
        sub = df[
            (df["asset"] == asset)
            & (df["fire_offset_s"] >= off_lo)
            & (df["fire_offset_s"] <= off_hi)
        ].copy()
        # Apply gates
        for g in gates:
            if g not in sub.columns:
                print(f"  [{sid}] WARN: gate {g} not in {base}, skip")
                continue
            sub = sub[sub[g].fillna(0).astype(int) == 1]
        # Direction filter — handle both Up/UP variants
        if dir_pick != "BOTH":
            sub = sub[sub["direction"].str.upper() == dir_pick.upper()]
        n_base = len(sub)
        if n_base == 0:
            print(f"  [{sid}] empty after filter")
            continue
        # Add AS features by key
        # First find slug col
        slug_col = "slug" if "slug" in sub.columns else "slug_id"
        sub["_key"] = (
            sub["asset"].astype(str) + "|" + tf + "|"
            + sub[slug_col].astype(str) + "|" + sub["fire_us"].astype(np.int64).astype(str)
        )
        sub["as_norm"] = sub["_key"].map(as_map["as_uncertainty_norm_24h"])
        sub["as_skew"] = sub["_key"].map(as_map["as_skew"])
        sub["close_fire"] = sub["_key"].map(as_map["close_fire"])
        sub["vwap_slot"] = sub["_key"].map(as_map["vwap_slot"])

        # Add coinbase sign by asset/fire_us asof
        cb_sign = np.full(len(sub), np.nan)
        a = sub["asset"].iloc[0]
        if a in cb_lookup:
            end_us, lr = cb_lookup[a]
            fu = sub["fire_us"].astype(np.int64).to_numpy()
            idx = np.searchsorted(end_us, fu, side="right") - 1
            ok = idx >= 0
            sgn = np.full(len(sub), np.nan)
            sgn[ok] = np.sign(lr[idx[ok]])
            cb_sign = sgn
        sub["cb_sign"] = cb_sign

        # Base stats
        bpnl = sub["pnl_legacy_usd"].to_numpy()
        bn, bwr, bdpt, bsum = stats(bpnl)

        # Apply each gate
        d_up = sub["direction"].str.upper() == "UP"
        d_dn = sub["direction"].str.upper() == "DOWN"
        gates_to_test = [
            ("g_as_stable", sub["as_norm"] < 1.0),
            ("g_as_norm_lt_05", sub["as_norm"] < 0.5),
            ("g_as_unstable_skip", sub["as_norm"] <= 2.0),
            ("g_as_norm_lt_15", sub["as_norm"] < 1.5),
            ("g_hy_cb_with_dir",
                (d_up & (sub["cb_sign"] > 0)) | (d_dn & (sub["cb_sign"] < 0))),
            ("g_as_stable_AND_hy_with",
                (sub["as_norm"] < 1.0)
                & ((d_up & (sub["cb_sign"] > 0)) | (d_dn & (sub["cb_sign"] < 0)))),
        ]
        for gname, mask in gates_to_test:
            mask = mask.fillna(False)
            gp = sub.loc[mask, "pnl_legacy_usd"].to_numpy()
            gn, gwr, gdpt, gsum = stats(gp)
            out_rows.append({
                "sleeve_id": sid, "asset": asset, "tf": tf,
                "gate": gname,
                "base_n": bn, "base_wr": bwr, "base_dpt": bdpt, "base_sum": bsum,
                "gated_n": gn, "gated_wr": gwr, "gated_dpt": gdpt, "gated_sum": gsum,
                "dpt_lift": (gdpt - bdpt) if np.isfinite(gdpt) and np.isfinite(bdpt) else np.nan,
                "wr_lift": (gwr - bwr) if np.isfinite(gwr) and np.isfinite(bwr) else np.nan,
                "n_retained_pct": (gn / bn * 100) if bn > 0 else np.nan,
            })

    out = pd.DataFrame(out_rows)
    out_path = os.path.join(OUT_DIR, "gate_overlay_results.csv")
    out.to_csv(out_path, index=False)
    print(f"\n[T4] saved {out_path} ({len(out)} rows) t={time.time()-t0:.1f}s")

    # Summarize: per gate, mean & median dpt_lift, count of positive lifts
    print("\n=== Gate lift summary (across 15 sleeves) ===")
    for gname, grp in out.groupby("gate"):
        valid = grp[grp["gated_n"] >= 30]
        if len(valid) == 0: continue
        pos = (valid["dpt_lift"] > 0).sum()
        print(f"  {gname:30s} n_sleeves={len(valid)} pos_lift={pos}/{len(valid)} "
              f"mean_dpt_lift={valid['dpt_lift'].mean():+.2f} "
              f"median_dpt_lift={valid['dpt_lift'].median():+.2f} "
              f"retain_p50={valid['n_retained_pct'].median():.0f}%")


if __name__ == "__main__":
    main()
