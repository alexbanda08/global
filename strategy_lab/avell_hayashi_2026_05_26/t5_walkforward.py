"""TASK 5 — Strict 3-way validation: train/val/lockbox + 200-shuffle bootstrap.

Window: Apr 24 -> May 25 (~32 days).
  train: first 20d  (Apr 24 -> May 14)
  val:   next  7d   (May 14 -> May 21)
  lockbox: final 5d (May 21 -> May 25)

Builds a UNIFIED panel: prefix + joined-REF + OOS = full 32d coverage.

For each (sleeve_id, gate) combo, score per-split WR / $/tr / sum_pnl + 200-shuffle
bootstrap CI on dpt.

Output: walkforward_results.csv
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
FW_DIR = os.path.join(RES_DIR, "_full_window_2026_05_26")

# Window boundaries (UTC seconds)
T_TRAIN_END = int(pd.Timestamp("2026-05-14T00:00:00Z").value // 1_000_000_000)
T_VAL_END = int(pd.Timestamp("2026-05-21T00:00:00Z").value // 1_000_000_000)
T_LOCKBOX_END = int(pd.Timestamp("2026-05-25T19:15:00Z").value // 1_000_000_000)


def stats(pnl: np.ndarray) -> tuple[int, float, float, float]:
    pnl = pnl[np.isfinite(pnl)]
    n = len(pnl)
    if n == 0:
        return 0, np.nan, np.nan, np.nan
    return n, float((pnl > 0).mean()), float(pnl.mean()), float(pnl.sum())


def bootstrap_dpt_ci(pnl: np.ndarray, n_boot: int = 200, alpha: float = 0.05) -> tuple[float, float]:
    pnl = pnl[np.isfinite(pnl)]
    n = len(pnl)
    if n < 10:
        return np.nan, np.nan
    rng = np.random.default_rng(42)
    samples = rng.choice(pnl, size=(n_boot, n), replace=True)
    means = samples.mean(axis=1)
    lo = float(np.quantile(means, alpha / 2))
    hi = float(np.quantile(means, 1 - alpha / 2))
    return lo, hi


SLEEVES = [
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

# All gates that may be referenced
ALL_GATES = sorted({
    g for s in SLEEVES for g in s[6]
} | {"g_sms_liq_reclaim_with","g_within_dev","g_dev_extreme"})


def add_g_sms_liq_reclaim_with(df: pd.DataFrame) -> pd.DataFrame:
    if "g_sms_liq_reclaim_with" in df.columns:
        # already there (OOS / prefix)
        return df
    if "liquidity_up" not in df.columns or "liquidity_dn" not in df.columns:
        df["g_sms_liq_reclaim_with"] = 0; return df
    out = np.zeros(len(df), dtype=np.int8)
    d = df["direction"].astype(str).str.upper().to_numpy()
    lu = pd.to_numeric(df["liquidity_up"], errors="coerce").fillna(0).to_numpy()
    ld = pd.to_numeric(df["liquidity_dn"], errors="coerce").fillna(0).to_numpy()
    out[(d == "UP") & (lu > 0)] = 1
    out[(d == "DOWN") & (ld > 0)] = 1
    df["g_sms_liq_reclaim_with"] = out
    return df


def build_unified_panel(asset: str, tf: str) -> pd.DataFrame:
    """Unify prefix + joined-REF + OOS for one (asset, tf).

    All three have the same fundamental schema (slug, fire_us, direction,
    pnl_legacy_usd, all gates). REF (s6/s15/v15m) is the in-sample joined
    panel; we add SMS liquidity from with_sms files.
    """
    parts = []

    # Prefix
    pref = pd.read_parquet(os.path.join(FW_DIR, "prefix_fires.parquet"))
    pref = pref[(pref["asset"] == asset) & (pref["tf"] == tf)].copy()
    pref = add_g_sms_liq_reclaim_with(pref)
    pref["__src"] = "prefix"
    parts.append(pref)

    # REF (joined panel)
    # 5m → s6 / s15 ; 15m → v15m. We want the same gates available, so use s6 for 5m UP/DOWN.
    base = "s6" if tf == "5m" else "v15m"
    ref = pd.read_parquet(os.path.join(RES_DIR, f"{base}_joined_all.parquet"))
    ref = ref[ref["asset"] == asset].copy()
    # Merge sms liquidity
    sms_path = os.path.join(RES_DIR, f"{base}_with_sms.parquet")
    if os.path.exists(sms_path):
        s = pd.read_parquet(sms_path)
        sms_cols = [c for c in ("liquidity_up","liquidity_dn") if c in s.columns]
        if sms_cols:
            kc = ["slug","fire_us","direction"]
            s = s[kc + sms_cols].drop_duplicates(kc)
            ref = ref.merge(s, on=kc, how="left", suffixes=("",""))
    ref = add_g_sms_liq_reclaim_with(ref)
    ref["__src"] = "ref"
    parts.append(ref)

    # ALSO s15 for 5m sleeves (S7 family)
    if tf == "5m":
        s15 = pd.read_parquet(os.path.join(RES_DIR, "s15_joined_all.parquet"))
        s15 = s15[s15["asset"] == asset].copy()
        sms_p = os.path.join(RES_DIR, "s15_with_sms.parquet")
        if os.path.exists(sms_p):
            s = pd.read_parquet(sms_p)
            sms_cols = [c for c in ("liquidity_up","liquidity_dn") if c in s.columns]
            if sms_cols:
                kc = ["slug","fire_us","direction"]
                s = s[kc + sms_cols].drop_duplicates(kc)
                s15 = s15.merge(s, on=kc, how="left", suffixes=("",""))
        s15 = add_g_sms_liq_reclaim_with(s15)
        s15["__src"] = "ref_s15"
        parts.append(s15)

    # OOS
    oos_path = os.path.join(FW_DIR, f"oos_fires_{asset}_{tf}.parquet")
    if os.path.exists(oos_path):
        oos = pd.read_parquet(oos_path)
        oos = add_g_sms_liq_reclaim_with(oos)
        oos["__src"] = "oos"
        parts.append(oos)

    # Concat - keep only common cols (gate / pnl / id keys)
    common_cols = set.intersection(*[set(p.columns) for p in parts])
    must_have = {"slug","fire_us","direction","pnl_legacy_usd","asset","fire_offset_s"}
    if not must_have.issubset(common_cols):
        print(f"  WARN: {asset} {tf} missing must-have cols: {must_have - common_cols}")
    keep = list(common_cols)
    df = pd.concat([p[keep] for p in parts], ignore_index=True)
    # Dedupe on (slug, fire_us, direction)
    df = df.drop_duplicates(["slug","fire_us","direction"], keep="first")
    return df


def main() -> None:
    t0 = time.time()
    print("[T5] loading AS panel + coinbase 1m...", flush=True)
    asp = pd.read_parquet(os.path.join(RES_DIR, "as_panel.parquet"),
                          columns=["asset","tf","slug","fire_us","as_uncertainty_norm_24h"])
    asp["key"] = asp["asset"] + "|" + asp["tf"] + "|" + asp["slug"] + "|" + asp["fire_us"].astype(str)
    as_map = asp.drop_duplicates("key").set_index("key")["as_uncertainty_norm_24h"]

    from load import load_klines
    cb_lookup = {}
    for a in ("BTC","ETH","SOL"):
        v = load_klines(a, source="coinbase-spot-ws", period_id="1MIN")
        if v.empty: continue
        v = v.sort_values("time_period_start_us").drop_duplicates("time_period_start_us").reset_index(drop=True)
        end_us = v["time_period_start_us"].to_numpy() + 60_000_000
        close = v["price_close"].astype(np.float64).to_numpy()
        lr = np.concatenate([[np.nan], np.diff(np.log(close))])
        cb_lookup[a] = (end_us, lr)

    # Build unified panels
    print("[T5] building unified panels...", flush=True)
    panels = {}
    for asset in ("BTC","ETH","SOL"):
        for tf in ("5m","15m"):
            panels[(asset, tf)] = build_unified_panel(asset, tf)
            n = len(panels[(asset, tf)])
            # Time range
            fu = panels[(asset, tf)]["fire_us"].astype(np.int64)
            if n > 0:
                t_min = pd.to_datetime(fu.min(), unit="us")
                t_max = pd.to_datetime(fu.max(), unit="us")
                print(f"  {asset} {tf}: n={n:,}  {t_min} -> {t_max}")

    candidate_gates = [
        ("none",                  lambda d: pd.Series([True]*len(d), index=d.index)),
        ("g_as_stable",           lambda d: d["as_norm"] < 1.0),
        ("g_as_norm_lt_05",       lambda d: d["as_norm"] < 0.5),
        ("g_as_unstable_skip",    lambda d: d["as_norm"] <= 2.0),
        ("g_as_norm_lt_15",       lambda d: d["as_norm"] < 1.5),
        ("g_hy_cb_with_dir",      lambda d:
            ((d["direction"].str.upper() == "UP") & (d["cb_sign"] > 0))
            | ((d["direction"].str.upper() == "DOWN") & (d["cb_sign"] < 0))),
        ("g_as_stable_AND_hy_with", lambda d:
            (d["as_norm"] < 1.0) & (
                ((d["direction"].str.upper() == "UP") & (d["cb_sign"] > 0))
                | ((d["direction"].str.upper() == "DOWN") & (d["cb_sign"] < 0))
            )),
    ]

    out_rows = []
    for sleeve in SLEEVES:
        sid, asset, tf, _, off_lo, off_hi, gates, dir_pick = sleeve
        df = panels[(asset, tf)]
        sub = df[
            (df["fire_offset_s"] >= off_lo)
            & (df["fire_offset_s"] <= off_hi)
        ].copy()
        for g in gates:
            if g not in sub.columns:
                continue
            sub = sub[sub[g].fillna(0).astype(int) == 1]
        if dir_pick != "BOTH":
            sub = sub[sub["direction"].str.upper() == dir_pick.upper()]
        if len(sub) == 0:
            print(f"  [{sid}] empty after filter"); continue
        # Add AS norm
        sub["_key"] = (sub["asset"].astype(str) + "|" + tf + "|"
                       + sub["slug"].astype(str) + "|" + sub["fire_us"].astype(np.int64).astype(str))
        sub["as_norm"] = sub["_key"].map(as_map)
        # CB sign
        cb_sign = np.full(len(sub), np.nan)
        if asset in cb_lookup:
            end_us, lr = cb_lookup[asset]
            fu = sub["fire_us"].astype(np.int64).to_numpy()
            idx = np.searchsorted(end_us, fu, side="right") - 1
            ok = idx >= 0
            v = np.full(len(sub), np.nan)
            v[ok] = np.sign(lr[idx[ok]])
            cb_sign = v
        sub["cb_sign"] = cb_sign

        # Split by time
        fire_s = (sub["fire_us"].astype(np.int64) // 1_000_000).to_numpy()
        train_mask = fire_s < T_TRAIN_END
        val_mask = (fire_s >= T_TRAIN_END) & (fire_s < T_VAL_END)
        lockbox_mask = (fire_s >= T_VAL_END) & (fire_s < T_LOCKBOX_END)
        print(f"  [{sid}] n_total={len(sub)} n_train={train_mask.sum()} "
              f"n_val={val_mask.sum()} n_lockbox={lockbox_mask.sum()}")

        for gname, gfn in candidate_gates:
            mask = gfn(sub).fillna(False).to_numpy()
            for split_name, smask in [("train", train_mask), ("val", val_mask), ("lockbox", lockbox_mask)]:
                final_mask = mask & smask
                pnl = sub.loc[final_mask, "pnl_legacy_usd"].to_numpy()
                n, wr, dpt, sumv = stats(pnl)
                lo, hi = bootstrap_dpt_ci(pnl, n_boot=200)
                out_rows.append({
                    "sleeve_id": sid, "gate": gname, "split": split_name,
                    "n": n, "wr": wr, "dpt": dpt, "sum": sumv,
                    "dpt_ci95_lo": lo, "dpt_ci95_hi": hi,
                })

    res = pd.DataFrame(out_rows)
    out_path = os.path.join(OUT_DIR, "walkforward_results.csv")
    res.to_csv(out_path, index=False)
    print(f"\n[T5] saved {out_path} ({len(res)} rows) t={time.time()-t0:.1f}s")

    # Pivot for analysis
    piv = res.pivot_table(index=["sleeve_id","gate"], columns="split",
                           values=["n","wr","dpt"], aggfunc="first")
    piv.columns = [f"{a}_{b}" for a,b in piv.columns]
    piv = piv.reset_index()

    # Base lookup (none-gate)
    base = res[res["gate"] == "none"]
    base_pivot = base.pivot_table(index="sleeve_id", columns="split", values="dpt", aggfunc="first")
    base_pivot.columns = [f"base_dpt_{c}" for c in base_pivot.columns]
    base_pivot = base_pivot.reset_index()
    piv = piv.merge(base_pivot, on="sleeve_id", how="left")
    for split in ("train","val","lockbox"):
        piv[f"dpt_lift_{split}"] = piv[f"dpt_{split}"] - piv[f"base_dpt_{split}"]

    # Save pivot
    piv.to_csv(os.path.join(OUT_DIR, "walkforward_pivot.csv"), index=False)

    # Strict passers: gate != none, lockbox n>=30, train/val/lockbox dpt > 0, lockbox dpt > base
    passers = piv[
        (piv["gate"] != "none")
        & (piv["n_lockbox"] >= 30)
        & (piv["dpt_lockbox"] > 0)
        & (piv["dpt_val"] > 0)
        & (piv["dpt_train"] > 0)
        & (piv["dpt_lift_lockbox"] > 0)
    ].sort_values("dpt_lift_lockbox", ascending=False)
    print(f"\n=== Strict 3-way passers (train>0 AND val>0 AND lockbox>0 AND lift_lockbox>0): {len(passers)} ===")
    if len(passers) > 0:
        print(passers[["sleeve_id","gate","n_train","dpt_train","n_val","dpt_val",
                        "n_lockbox","dpt_lockbox","dpt_lift_lockbox"]].to_string(index=False))

    # Looser pass: lockbox dpt > 0 AND lockbox n>=30
    loose = piv[
        (piv["gate"] != "none")
        & (piv["n_lockbox"] >= 30)
        & (piv["dpt_lockbox"] > 0)
    ].sort_values("dpt_lockbox", ascending=False).head(20)
    print(f"\n=== Loose lockbox pass (top 20 by dpt_lockbox, n>=30) ===")
    if len(loose) > 0:
        print(loose[["sleeve_id","gate","n_train","dpt_train","n_val","dpt_val",
                     "n_lockbox","dpt_lockbox","dpt_lift_lockbox"]].to_string(index=False))


if __name__ == "__main__":
    main()
