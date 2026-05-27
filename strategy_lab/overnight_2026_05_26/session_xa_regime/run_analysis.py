"""
Session x Cross-Asset Regime stratification for top 7 sleeves.

Conventions:
- Sessions derived from UTC hour: London 07-16, NY 13-21, Tokyo 00-06, HK 01-08,
  Frankfurt 06-15, Sydney 22-05 (wraps), EU Brinks 07-08, US Brinks 13-14,
  weekend Sat-Sun, overlap London+NY 13-16. (per spec)
- Cross-asset regime: at each fire_us, look up BTC/ETH/SOL regime_label from
  regime_panel_5m.parquet (causal asof <= fire_us).
- Fee model: LegacyConfig (2% on winning leg only, $0 on losing leg).
- Three-way split by fire_date: train 2026-05-01..05-20 (20d), val 05-21..05-25
  (5d) -- actually spec says train 20d / val 7d / lockbox 5d, but data spans
  ~25d only. We use: train first 20d, val next 4d, lockbox last calendar day.
  (Adjust dynamically based on actual range.)

Outputs:
- session_xa_regime_metrics.csv (per-sleeve session, xa-regime, combined cells)
- session_distribution_per_sleeve.csv
- per_sleeve_session_metrics.csv
- per_sleeve_xa_regime_metrics.csv
- session_xa_combined_top.csv
- conditional_sleeves_lockbox.csv
"""
import os
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path("C:/Users/alexandre bandarra/Desktop/global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"
OUT = ROOT / "strategy_lab" / "overnight_2026_05_26" / "session_xa_regime"
OUT.mkdir(parents=True, exist_ok=True)

# ---- Load master gate panel (per-fire features, sleeve_id, won, pnl_legacy_usd) ----
mg = pd.read_parquet(RES / "master_gate_features_v2.parquet")
print(f"[load] master_gate_features_v2: {mg.shape}", flush=True)

# Ensure won_int
if "won_int" not in mg.columns:
    mg["won_int"] = mg["won"].astype(int)

# ---- Derive UTC hour from fire_us ----
mg["fire_ts"] = pd.to_datetime(mg["fire_us"], unit="us", utc=True)
mg["utc_hour"] = mg["fire_ts"].dt.hour
mg["dow"] = mg["fire_ts"].dt.dayofweek  # 0=Mon..6=Sun

# Session flags per spec
def in_range(h, lo, hi):
    return (h >= lo) & (h < hi)

mg["s_london"]    = in_range(mg["utc_hour"], 7, 16)
mg["s_ny"]        = in_range(mg["utc_hour"], 13, 21)
mg["s_tokyo"]     = in_range(mg["utc_hour"], 0, 6)
mg["s_hk"]        = in_range(mg["utc_hour"], 1, 8)
mg["s_frankfurt"] = in_range(mg["utc_hour"], 6, 15)
mg["s_sydney"]    = (mg["utc_hour"] >= 22) | (mg["utc_hour"] < 5)
mg["s_eu_brinks"] = in_range(mg["utc_hour"], 7, 8)
mg["s_us_brinks"] = in_range(mg["utc_hour"], 13, 14)
mg["s_overlap"]   = in_range(mg["utc_hour"], 13, 16)
mg["s_weekend"]   = mg["dow"].isin([5, 6])
mg["s_none"]      = ~(mg["s_london"] | mg["s_ny"] | mg["s_tokyo"] | mg["s_hk"])
SESSIONS = ["all", "london", "ny", "tokyo", "hk", "frankfurt", "sydney",
            "eu_brinks", "us_brinks", "overlap", "weekend"]

# ---- Load regime panels and build cross-asset regime lookup ----
r5 = pd.read_parquet(RES / "regime_panel_5m.parquet")
r15 = pd.read_parquet(RES / "regime_panel_15m.parquet")

# Build per-asset asof index: for each asset, sort by ts_us ascending,
# then for each fire_us look up most recent regime_label.
def build_regime_asof(panel: pd.DataFrame, asset: str) -> pd.DataFrame:
    sub = panel[panel["asset"] == asset][["ts_us", "regime_label"]].copy()
    sub = sub.sort_values("ts_us").reset_index(drop=True)
    return sub

regimes_5m = {a: build_regime_asof(r5, a) for a in ["BTC", "ETH", "SOL"]}
regimes_15m = {a: build_regime_asof(r15, a) for a in ["BTC", "ETH", "SOL"]}


def asof_regime(fire_us_arr: np.ndarray, panel_df: pd.DataFrame) -> np.ndarray:
    """
    For each fire_us, return regime_label of the most recent panel bar with
    ts_us <= fire_us. searchsorted with side='right' gives insertion index, then -1.
    """
    ts = panel_df["ts_us"].to_numpy()
    lab = panel_df["regime_label"].to_numpy()
    idx = np.searchsorted(ts, fire_us_arr, side="right") - 1
    mask = idx >= 0
    out = np.full(len(fire_us_arr), "unknown", dtype=object)
    out[mask] = lab[idx[mask]]
    return out


# Per-fire: lookup BTC/ETH/SOL regime from the timeframe matching the fire's tf
def lookup_xa_regimes(df: pd.DataFrame) -> pd.DataFrame:
    res = df.copy()
    for asset in ["BTC", "ETH", "SOL"]:
        col_5m = f"reg_{asset.lower()}"
        # Use 5m regime panel for all fires (5m is more granular and we have it for all)
        res[col_5m] = asof_regime(res["fire_us"].to_numpy(), regimes_5m[asset])
    return res


mg = lookup_xa_regimes(mg)
print(f"[regime] cross-asset regimes joined", flush=True)

# Build a single combined cross-asset regime token
def xa_combo(row):
    t = (row["reg_btc"], row["reg_eth"], row["reg_sol"])
    # all_up / all_dn / all_ranging
    if t == ("trending_up",) * 3:
        return "all_up"
    if t == ("trending_dn",) * 3:
        return "all_dn"
    if t == ("ranging",) * 3:
        return "all_ranging"
    # btc trending, others ranging
    btc, eth, sol = t
    if btc.startswith("trending") and eth == "ranging" and sol == "ranging":
        return f"btc_{'up' if btc=='trending_up' else 'dn'}_only"
    if eth.startswith("trending") and btc == "ranging" and sol == "ranging":
        return f"eth_{'up' if eth=='trending_up' else 'dn'}_only"
    if sol.startswith("trending") and btc == "ranging" and eth == "ranging":
        return f"sol_{'up' if sol=='trending_up' else 'dn'}_only"
    ups = sum(x == "trending_up" for x in t)
    dns = sum(x == "trending_dn" for x in t)
    if ups >= 2 and dns == 0:
        return "mostly_up"
    if dns >= 2 and ups == 0:
        return "mostly_dn"
    if ups >= 1 and dns >= 1:
        return "mixed_updn"
    return "other"


mg["xa_combo"] = mg.apply(xa_combo, axis=1)
print(f"[xa_combo] distribution:\n{mg['xa_combo'].value_counts().to_string()}", flush=True)

# ---- Identify top 7 sleeves from master_combinatorial_deployable ----
mc = pd.read_csv(RES / "master_combinatorial_deployable.csv")
mc = mc.sort_values("n_total", ascending=False).reset_index(drop=True)
TOP7 = mc.head(7)[["sleeve_id", "asset", "tf"]].to_dict(orient="records")
print(f"[top7] {len(TOP7)} sleeves identified", flush=True)
for r in TOP7:
    print(f"  - {r['asset']:3s} {r['tf']:3s} | {r['sleeve_id']}", flush=True)

# Filter master gate to only the fires belonging to top7 sleeves
def matches_top7(row):
    return any(row["sleeve_id"] == t["sleeve_id"] and row["asset"] == t["asset"] for t in TOP7)


mg_top = mg[mg.apply(matches_top7, axis=1)].copy()
print(f"[filter] fires for top7 sleeves: {len(mg_top)}", flush=True)


# ---- Aggregator: WR, $/tr, sum, n for a slice ----
def metrics(d: pd.DataFrame) -> dict:
    if len(d) == 0:
        return {"n": 0, "wr": np.nan, "pt": np.nan, "sum": 0.0}
    return {
        "n": int(len(d)),
        "wr": 100.0 * d["won_int"].mean(),
        "pt": float(d["pnl_legacy_usd"].mean()),
        "sum": float(d["pnl_legacy_usd"].sum()),
    }


# ---- TASK 1: Session distribution per sleeve ----
sess_dist_rows = []
sess_metrics_rows = []
xa_metrics_rows = []
combined_rows = []

for t in TOP7:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)]
    n_all = len(d)
    # distribution
    row = {"sleeve_id": sid, "asset": asset, "tf": t["tf"], "n_total": n_all}
    for name, col in [
        ("london", "s_london"), ("ny", "s_ny"), ("tokyo", "s_tokyo"),
        ("hk", "s_hk"), ("frankfurt", "s_frankfurt"), ("sydney", "s_sydney"),
        ("eu_brinks", "s_eu_brinks"), ("us_brinks", "s_us_brinks"),
        ("overlap", "s_overlap"), ("weekend", "s_weekend"),
    ]:
        n = int(d[col].sum())
        row[f"n_{name}"] = n
        row[f"pct_{name}"] = 100.0 * n / n_all if n_all else 0.0
    sess_dist_rows.append(row)

    # TASK 2: per-(sleeve, session) metrics
    sm = {"sleeve_id": sid, "asset": asset, **{f"all_{k}": v for k, v in metrics(d).items()}}
    for name, col in [
        ("london", "s_london"), ("ny", "s_ny"), ("tokyo", "s_tokyo"),
        ("hk", "s_hk"), ("frankfurt", "s_frankfurt"), ("sydney", "s_sydney"),
        ("eu_brinks", "s_eu_brinks"), ("us_brinks", "s_us_brinks"),
        ("overlap", "s_overlap"), ("weekend", "s_weekend"),
    ]:
        m = metrics(d[d[col]])
        for k, v in m.items():
            sm[f"{name}_{k}"] = v
    sess_metrics_rows.append(sm)

    # TASK 5: per-(sleeve, xa-regime) metrics
    xa = {"sleeve_id": sid, "asset": asset}
    for combo in ["all_up", "all_dn", "all_ranging", "mostly_up", "mostly_dn",
                  "mixed_updn", "btc_up_only", "btc_dn_only",
                  "eth_up_only", "eth_dn_only", "sol_up_only", "sol_dn_only", "other"]:
        m = metrics(d[d["xa_combo"] == combo])
        for k, v in m.items():
            xa[f"{combo}_{k}"] = v
    xa_metrics_rows.append(xa)

    # TASK 6: combined session x xa-regime for top 3 only
sess_dist = pd.DataFrame(sess_dist_rows)
sess_metrics = pd.DataFrame(sess_metrics_rows)
xa_metrics = pd.DataFrame(xa_metrics_rows)

sess_dist.to_csv(OUT / "session_distribution_per_sleeve.csv", index=False)
sess_metrics.to_csv(OUT / "per_sleeve_session_metrics.csv", index=False)
xa_metrics.to_csv(OUT / "per_sleeve_xa_regime_metrics.csv", index=False)
print(f"[task1-2-5] wrote distribution + per-session + per-xa metrics", flush=True)

# ---- TASK 6: combined (session x xa-regime) for top 3 sleeves ----
TOP3 = TOP7[:3]
SESS_LABELS = [
    ("london", "s_london"), ("ny", "s_ny"), ("tokyo", "s_tokyo"),
    ("hk", "s_hk"), ("frankfurt", "s_frankfurt"), ("sydney", "s_sydney"),
    ("weekend", "s_weekend"), ("overlap", "s_overlap"),
]
XA_LABELS = ["all_up", "all_dn", "all_ranging", "mostly_up", "mostly_dn",
             "mixed_updn", "btc_up_only", "btc_dn_only",
             "eth_up_only", "eth_dn_only", "sol_up_only", "sol_dn_only"]

for t in TOP3:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)]
    base = metrics(d)
    for sname, scol in SESS_LABELS:
        for xa in XA_LABELS:
            sub = d[d[scol] & (d["xa_combo"] == xa)]
            m = metrics(sub)
            combined_rows.append({
                "sleeve_id": sid, "asset": asset,
                "session": sname, "xa_combo": xa,
                "n": m["n"], "wr": m["wr"], "pt": m["pt"], "sum": m["sum"],
                "baseline_n": base["n"], "baseline_wr": base["wr"], "baseline_pt": base["pt"],
                "lift_pt": (m["pt"] - base["pt"]) if not np.isnan(m["pt"]) else np.nan,
            })

combined = pd.DataFrame(combined_rows)
combined.to_csv(OUT / "session_xa_combined_top3.csv", index=False)
print(f"[task6] wrote combined session x xa-regime for top3 ({len(combined)} cells)", flush=True)

# ---- TASK 3: Session-aware variants ----
# For each sleeve, find best session(s) where edge > baseline,
# and worst session(s) to exclude.
sess_variant_rows = []
for t in TOP7:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)]
    base = metrics(d)
    # find best single-session filter (n >= 30, pt > baseline)
    best_inc = None
    for sname, scol in SESS_LABELS:
        sub = d[d[scol]]
        m = metrics(sub)
        if m["n"] >= 30 and m["pt"] > base["pt"]:
            if best_inc is None or m["sum"] > best_inc["sum"]:
                best_inc = {**m, "name": sname, "filter": "include"}
    # find worst-session-exclude
    best_exc = None
    for sname, scol in SESS_LABELS:
        sub = d[~d[scol]]
        m = metrics(sub)
        if m["n"] >= 30 and m["pt"] > base["pt"]:
            if best_exc is None or m["pt"] > best_exc["pt"]:
                best_exc = {**m, "name": sname, "filter": "exclude"}
    sess_variant_rows.append({
        "sleeve_id": sid, "asset": asset,
        "base_n": base["n"], "base_wr": base["wr"], "base_pt": base["pt"], "base_sum": base["sum"],
        "best_session_in": best_inc["name"] if best_inc else None,
        "best_session_in_n": best_inc["n"] if best_inc else None,
        "best_session_in_wr": best_inc["wr"] if best_inc else None,
        "best_session_in_pt": best_inc["pt"] if best_inc else None,
        "best_session_in_sum": best_inc["sum"] if best_inc else None,
        "best_session_exc": best_exc["name"] if best_exc else None,
        "best_session_exc_n": best_exc["n"] if best_exc else None,
        "best_session_exc_wr": best_exc["wr"] if best_exc else None,
        "best_session_exc_pt": best_exc["pt"] if best_exc else None,
        "best_session_exc_sum": best_exc["sum"] if best_exc else None,
    })
pd.DataFrame(sess_variant_rows).to_csv(OUT / "session_variants.csv", index=False)
print(f"[task3] wrote session variants", flush=True)

# ---- TASK 4: Cross-asset regime distribution ----
xa_dist = mg_top["xa_combo"].value_counts().reset_index()
xa_dist.columns = ["xa_combo", "n_fires"]
xa_dist.to_csv(OUT / "xa_regime_distribution.csv", index=False)
print(f"[task4] xa-regime distribution:\n{xa_dist.to_string(index=False)}", flush=True)

# ---- TASK 7: Conditional sleeves (session x xa-regime profitable cells) ----
# For each sleeve, find profitable (session, xa) combos with n >= 30 and pt > 0.
# Build a sleeve variant that fires only on those combos.
conditional_rows = []
for t in TOP7:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)]
    base = metrics(d)
    # Build all (session, xa) cells
    cells = []
    for sname, scol in SESS_LABELS:
        for xa in XA_LABELS:
            sub = d[d[scol] & (d["xa_combo"] == xa)]
            m = metrics(sub)
            if m["n"] >= 30 and m["pt"] > 0:
                cells.append({"session": sname, "xa": xa, "n": m["n"], "wr": m["wr"], "pt": m["pt"], "sum": m["sum"]})
    cells = sorted(cells, key=lambda c: c["sum"], reverse=True)[:5]
    if not cells:
        continue
    # build mask = OR over the chosen cells
    mask = pd.Series(False, index=d.index)
    for c in cells:
        scol = dict(SESS_LABELS)[c["session"]]
        mask |= (d[scol] & (d["xa_combo"] == c["xa"]))
    var = d[mask]
    m_var = metrics(var)
    conditional_rows.append({
        "sleeve_id": sid, "asset": asset,
        "base_n": base["n"], "base_wr": base["wr"], "base_pt": base["pt"], "base_sum": base["sum"],
        "cells_used": "; ".join(f"{c['session']}/{c['xa']}(n={c['n']})" for c in cells),
        "var_n": m_var["n"], "var_wr": m_var["wr"], "var_pt": m_var["pt"], "var_sum": m_var["sum"],
        "lift_pt": m_var["pt"] - base["pt"],
    })
pd.DataFrame(conditional_rows).to_csv(OUT / "conditional_sleeves.csv", index=False)
print(f"[task7] wrote conditional sleeves", flush=True)

# ---- TASK 8: Strict 3-way validation ----
# Date histogram is heavily skewed (May 22-25 has ~50% of fires due to feature
# panel build timing). Split by fire_date but adjust quantiles to ensure both
# train and lock get adequate samples. Train = first 60% of FIRES (chronologically),
# val = next 20%, lock = last 20%. This balances signal/test sizes despite uneven
# daily fire counts.
mg_top["fire_date_d"] = mg_top["fire_ts"].dt.floor("D")
# Compute per-sleeve fire quantile splits so each sleeve gets ~same train/val/lock
# proportion (avoids the case where a sleeve sees 95% of its fires in the lock window).
# We use a global quantile across all top-7 fires combined.
fire_ts_sorted = mg_top["fire_ts"].sort_values().to_numpy()
n = len(fire_ts_sorted)
train_end = pd.Timestamp(fire_ts_sorted[int(n * 0.60)])
val_end = pd.Timestamp(fire_ts_sorted[int(n * 0.80)])
print(f"[task8] fire-quantile split: train < {train_end} | val < {val_end} | lock >= {val_end}", flush=True)

def split_mask(d):
    return (
        d["fire_ts"] < train_end,
        (d["fire_ts"] >= train_end) & (d["fire_ts"] < val_end),
        d["fire_ts"] >= val_end,
    )


val_rows = []
rng = np.random.default_rng(42)


def boot_p(d_lock_pt_series, n_boot=500):
    """Bootstrap p-value: H0 = mean(pt) <= 0. Returns prob(mean<=0)."""
    arr = d_lock_pt_series.to_numpy()
    if len(arr) < 10:
        return np.nan
    n = len(arr)
    means = np.empty(n_boot)
    for i in range(n_boot):
        sample = arr[rng.integers(0, n, n)]
        means[i] = sample.mean()
    return float((means <= 0).mean())


def evaluate_variant(d, variant_name, build_mask_fn):
    """For one variant (session-only, xa-only, or combined), apply train/val/lock split."""
    tr_mask, va_mask, lk_mask = split_mask(d)
    d_tr = d[tr_mask]
    d_va = d[va_mask]
    d_lk = d[lk_mask]
    base_lk = metrics(d_lk)
    # Mine on TRAIN
    train_cells = build_mask_fn(d_tr)
    if not train_cells:
        return {
            "variant": variant_name, "train_n": 0, "val_n": 0, "lock_n": 0,
            "train_pt": np.nan, "val_pt": np.nan, "lock_pt": np.nan,
            "base_lock_pt": base_lk["pt"], "lift_lock_pt": np.nan,
            "lock_boot_p": np.nan, "passes_lock": False,
            "cells": "(none qualified on train)",
        }

    def apply_cells(dfx):
        mask = pd.Series(False, index=dfx.index)
        for c in train_cells:
            if "session" in c and "xa" in c:
                scol = dict(SESS_LABELS)[c["session"]]
                mask |= (dfx[scol] & (dfx["xa_combo"] == c["xa"]))
            elif "session" in c:
                scol = dict(SESS_LABELS)[c["session"]]
                mask |= dfx[scol]
            elif "xa" in c:
                mask |= (dfx["xa_combo"] == c["xa"])
        return dfx[mask]

    tr_v = apply_cells(d_tr)
    va_v = apply_cells(d_va)
    lk_v = apply_cells(d_lk)
    m_tr, m_va, m_lk = metrics(tr_v), metrics(va_v), metrics(lk_v)
    p = boot_p(lk_v["pnl_legacy_usd"]) if m_lk["n"] >= 10 else np.nan
    return {
        "variant": variant_name,
        "train_n": m_tr["n"], "train_wr": m_tr["wr"], "train_pt": m_tr["pt"], "train_sum": m_tr["sum"],
        "val_n": m_va["n"], "val_wr": m_va["wr"], "val_pt": m_va["pt"], "val_sum": m_va["sum"],
        "lock_n": m_lk["n"], "lock_wr": m_lk["wr"], "lock_pt": m_lk["pt"], "lock_sum": m_lk["sum"],
        "base_lock_n": base_lk["n"], "base_lock_pt": base_lk["pt"],
        "lift_lock_pt": (m_lk["pt"] - base_lk["pt"]) if not np.isnan(m_lk["pt"]) else np.nan,
        "lock_boot_p": p,
        "passes_lock": (not np.isnan(p)) and (p < 0.05) and m_lk["pt"] > 0 and m_lk["pt"] > base_lk["pt"],
        "cells": "; ".join(repr(c) for c in train_cells),
    }


def mine_combined_cells(d_tr):
    """Combined session x xa cells, n>=30, top-5 by pt"""
    cells = []
    for sname, scol in SESS_LABELS:
        for xa in XA_LABELS:
            sub = d_tr[d_tr[scol] & (d_tr["xa_combo"] == xa)]
            m = metrics(sub)
            if m["n"] >= 30 and m["pt"] > 0:
                cells.append({"session": sname, "xa": xa, "n": m["n"], "pt": m["pt"]})
    return sorted(cells, key=lambda c: c["pt"], reverse=True)[:5]


def mine_session_only(d_tr):
    """Session-only filter, n>=100, top by pt above baseline"""
    base = metrics(d_tr)
    cells = []
    for sname, scol in SESS_LABELS:
        sub = d_tr[d_tr[scol]]
        m = metrics(sub)
        if m["n"] >= 100 and m["pt"] > base["pt"]:
            cells.append({"session": sname, "n": m["n"], "pt": m["pt"]})
    return sorted(cells, key=lambda c: c["pt"], reverse=True)[:3]


def mine_xa_only(d_tr):
    """Cross-asset-regime-only filter, n>=100, top by pt above baseline"""
    base = metrics(d_tr)
    cells = []
    for xa in XA_LABELS:
        sub = d_tr[d_tr["xa_combo"] == xa]
        m = metrics(sub)
        if m["n"] >= 100 and m["pt"] > base["pt"]:
            cells.append({"xa": xa, "n": m["n"], "pt": m["pt"]})
    return sorted(cells, key=lambda c: c["pt"], reverse=True)[:3]


for t in TOP7:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)].copy()
    for variant_name, builder in [
        ("combined_sess_xa", mine_combined_cells),
        ("session_only", mine_session_only),
        ("xa_only", mine_xa_only),
    ]:
        row = evaluate_variant(d, variant_name, builder)
        row["sleeve_id"] = sid
        row["asset"] = asset
        val_rows.append(row)

three_way = pd.DataFrame(val_rows)
three_way.to_csv(OUT / "three_way_validation.csv", index=False)
print(f"[task8] wrote three-way validation. passes_lock counts: {three_way['passes_lock'].sum() if 'passes_lock' in three_way else 0}", flush=True)

# ---- Consolidated session_xa_regime_metrics.csv per the spec ----
# Merge: per-sleeve x per-session x per-xa-regime breakdown
all_rows = []
for t in TOP7:
    sid, asset = t["sleeve_id"], t["asset"]
    d = mg_top[(mg_top["sleeve_id"] == sid) & (mg_top["asset"] == asset)]
    base = metrics(d)
    # Per-session
    for sname, scol in [("all", None)] + SESS_LABELS:
        sub = d if scol is None else d[d[scol]]
        m = metrics(sub)
        all_rows.append({
            "sleeve_id": sid, "asset": asset, "session": sname, "xa_combo": "all",
            "n": m["n"], "wr": m["wr"], "pt": m["pt"], "sum": m["sum"],
            "base_n": base["n"], "base_pt": base["pt"], "lift_pt": (m["pt"] - base["pt"]) if not np.isnan(m["pt"]) else np.nan,
        })
    # Per-xa-regime
    for xa in ["all"] + XA_LABELS:
        sub = d if xa == "all" else d[d["xa_combo"] == xa]
        m = metrics(sub)
        all_rows.append({
            "sleeve_id": sid, "asset": asset, "session": "all", "xa_combo": xa,
            "n": m["n"], "wr": m["wr"], "pt": m["pt"], "sum": m["sum"],
            "base_n": base["n"], "base_pt": base["pt"], "lift_pt": (m["pt"] - base["pt"]) if not np.isnan(m["pt"]) else np.nan,
        })
    # Combined for top3 only
    if t in TOP3:
        for sname, scol in SESS_LABELS:
            for xa in XA_LABELS:
                sub = d[d[scol] & (d["xa_combo"] == xa)]
                m = metrics(sub)
                all_rows.append({
                    "sleeve_id": sid, "asset": asset, "session": sname, "xa_combo": xa,
                    "n": m["n"], "wr": m["wr"], "pt": m["pt"], "sum": m["sum"],
                    "base_n": base["n"], "base_pt": base["pt"], "lift_pt": (m["pt"] - base["pt"]) if not np.isnan(m["pt"]) else np.nan,
                })

combined_metrics = pd.DataFrame(all_rows)
combined_metrics_path = RES / "session_xa_regime_metrics.csv"
combined_metrics.to_csv(combined_metrics_path, index=False)
print(f"[final] wrote {combined_metrics_path}", flush=True)

print(f"[done] all outputs in {OUT}", flush=True)
