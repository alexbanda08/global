"""Full-window gate search (Round-4) — combine R2 base gates + R3 winners.

Pipeline:
  1. Load existing s15/s6/v15m joined panels (R2 baseline gates, May 1 - May 21).
  2. Load Agent U OOS panel (BOTH directions, May 21 - May 25) and re-join the
     direction signal from S1.5/S6/v15m universes to get matching direction rows.
  3. Concat into full-window (slug, fire_us, direction) rows.
  4. Add R3 panels:
     - vol_hurst regime gates (g_vol_high, g_vol_low, g_vol_med, g_vol_expanding,
       g_vol_contracting, g_hurst_trending, g_hurst_reverting, g_rv_with)
     - microstructure directional gates (g_imb5_with, g_microprice_with,
       g_spread_tight, g_spread_wide_skew, g_book_slope_steep_against,
       g_microprice_skew_with, g_depth_high, g_queue_top_high, g_imb_change_with,
       g_imb5_strong_with, g_quote_intensity_high)
  5. Run gate_search per (asset, tf, offset_bin).
  6. Train/test split with bootstrap p-values.
  7. Compare R2 sleeve gate stacks vs new winners.
  8. R3 marginal contribution analysis.

Outputs:
  data/v4/canonical/_results/full_window_gate_search.csv     (all cells)
  data/v4/canonical/_results/full_window_gate_search_top.csv (top 50)
  data/v4/canonical/_results/full_window_walkforward.csv     (train/test+bootstrap)
  data/v4/canonical/_results/full_window_r2_vs_new.csv       (R2 sleeves vs new)
  data/v4/canonical/_results/full_window_r3_contribution.csv (R3 gate lift per sleeve)
  strategy_lab/reports/FULL_WINDOW_GATE_SEARCH_2026_05_26.md
"""
from __future__ import annotations
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"
FULL = RES / "_full_window_2026_05_26"
from hybrid_backtest import gate_search, walk_forward_split  # type: ignore

MIN_N = 30
TOP_K = 50
BOOTSTRAP_N = 200
RNG = np.random.default_rng(42)

OFFSET_BINS_5M = [(0, 60), (60, 150), (150, 240), (240, 300)]
OFFSET_BINS_15M = [(0, 240), (240, 480), (480, 900)]

R2_BASE_GATES = [
    "g_rf_with", "g_rf_fresh", "g_rf_aged", "g_rf_in_band",
    "g_tr_stack_with", "g_tr_stack_full_with", "g_tr_above_cloud",
    "g_tr_within_adr", "g_tr_in_active_session", "g_tr_above_pp",
    "g_tr_above_ema50", "g_tr_above_ema200", "g_tr_above_ema800",
    "g_ribbon_agrees", "g_ribbon_slope_with", "g_tight_ribbon",
    "g_bb_pos_with", "g_stoch_with", "g_mfi_with", "g_cci_with",
    "g_within_dev", "g_dev_extreme",
]

R3_VOL_GATES = [
    "g_vol_high", "g_vol_low", "g_vol_med", "g_vol_expanding",
    "g_vol_contracting", "g_hurst_trending", "g_hurst_reverting",
]

R3_MICRO_GATES = [
    "g_imb5_with", "g_microprice_with", "g_spread_tight",
    "g_spread_wide_skew", "g_book_slope_steep_against",
    "g_microprice_skew_with", "g_depth_high", "g_queue_top_high",
    "g_imb_change_with", "g_imb5_strong_with",
]


# ---------------------------------------------------------------------------
# 1) Build R3 micro gates from panel (panel has up_* / dn_* features only)
# ---------------------------------------------------------------------------
def build_r3_micro_gates(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute direction-aware microstructure gates per (slug, fire_us, direction).

    Output: DataFrame indexed by ['slug', 'fire_us', 'direction'] with bool gate cols.
    """
    p = panel.copy()
    # Build two universes (UP / DN) then concat
    out_up = pd.DataFrame({
        "slug": p["slug"], "fire_us": p["fire_us"],
        "direction": "UP",
        "g_imb5_with": (p.up_imb5 > 0).astype("int8"),
        "g_imb5_strong_with": (p.up_imb5 > 0.3).astype("int8"),
        "g_microprice_with": (p.up_micro_dev_bps > 0).astype("int8"),
        "g_spread_tight": ((p.up_spread_bps < 200) & (p.dn_spread_bps < 200)).astype("int8"),
        "g_spread_wide_skew": (p.up_spread_bps < p.dn_spread_bps).astype("int8"),
        "g_quote_intensity_high": ((p.up_quote_intensity_5s > 20) | (p.dn_quote_intensity_5s > 20)).astype("int8"),
        "g_book_slope_steep_against": (p.up_ask_slope.abs() < 0.0001).astype("int8"),
        "g_microprice_skew_with": ((p.up_micro_dev_bps > 0) & (p.dn_micro_dev_bps < 0)).astype("int8"),
        "g_queue_top_high": (p.up_queue_top_bid > 0.1).astype("int8"),
        "g_imb_change_with": (p.up_imb5_change_500ms > 0).astype("int8"),
    })
    depth_sum = p.up_depth_2pct.fillna(0) + p.dn_depth_2pct.fillna(0)
    depth_med = float(depth_sum.median())
    out_up["g_depth_high"] = (depth_sum > depth_med).astype("int8")

    out_dn = pd.DataFrame({
        "slug": p["slug"], "fire_us": p["fire_us"],
        "direction": "DOWN",
        "g_imb5_with": (p.up_imb5 < 0).astype("int8"),
        "g_imb5_strong_with": (p.up_imb5 < -0.3).astype("int8"),
        "g_microprice_with": (p.dn_micro_dev_bps > 0).astype("int8"),
        "g_spread_tight": ((p.up_spread_bps < 200) & (p.dn_spread_bps < 200)).astype("int8"),
        "g_spread_wide_skew": (p.dn_spread_bps < p.up_spread_bps).astype("int8"),
        "g_quote_intensity_high": ((p.up_quote_intensity_5s > 20) | (p.dn_quote_intensity_5s > 20)).astype("int8"),
        "g_book_slope_steep_against": (p.dn_ask_slope.abs() < 0.0001).astype("int8"),
        "g_microprice_skew_with": ((p.up_micro_dev_bps < 0) & (p.dn_micro_dev_bps > 0)).astype("int8"),
        "g_queue_top_high": (p.dn_queue_top_bid > 0.1).astype("int8"),
        "g_imb_change_with": (p.dn_imb5_change_500ms > 0).astype("int8"),
    })
    out_dn["g_depth_high"] = (depth_sum > depth_med).astype("int8")

    out = pd.concat([out_up, out_dn], ignore_index=True)
    return out


# ---------------------------------------------------------------------------
# 2) Build OOS slice matching the s15/s6/v15m direction logic
# ---------------------------------------------------------------------------
def build_oos_panels() -> dict:
    """Load Agent U OOS panels, pick direction per universe spec.

    Returns dict: tf_label -> DataFrame matching s15/s6/v15m schema.
    Agent U OOS already has both UP and DOWN per fire — we pick the one
    that matches the original universe's signal logic.

    For now we LEAVE BOTH directions — the gate_search treats direction
    semantics through g_*_with gates already. We slice off the appropriate
    fire_offset_s to match S1.5 (60-270 5m), S6 (15-120 5m), v15m (60-840).
    """
    paths = {
        "BTC_5m": FULL / "oos_fires_BTC_5m.parquet",
        "ETH_5m": FULL / "oos_fires_ETH_5m.parquet",
        "SOL_5m": FULL / "oos_fires_SOL_5m.parquet",
        "BTC_15m": FULL / "oos_fires_BTC_15m.parquet",
        "ETH_15m": FULL / "oos_fires_ETH_15m.parquet",
    }
    out = {}
    for k, p in paths.items():
        if not p.exists():
            print(f"  OOS missing: {k}")
            continue
        df = pd.read_parquet(p)
        out[k] = df
        print(f"  OOS {k}: {df.shape}, fire_us {pd.to_datetime(df.fire_us.min(),unit='us',utc=True).date()}..{pd.to_datetime(df.fire_us.max(),unit='us',utc=True).date()}")
    return out


# ---------------------------------------------------------------------------
# 3) Load R3 panels and prepare merge keys
# ---------------------------------------------------------------------------
def load_r3_panels() -> dict:
    """Load vol/hurst and microstructure panels."""
    out = {}

    vh_5m = pd.read_parquet(RES / "vol_hurst_at_fire_5m.parquet")
    vh_15m = pd.read_parquet(RES / "vol_hurst_at_fire_15m.parquet")
    # Merge keys (slug, fire_us). Both directions get the same regime values.
    for c in R3_VOL_GATES:
        if c in vh_5m.columns:
            vh_5m[c] = vh_5m[c].fillna(0).astype("int8")
        if c in vh_15m.columns:
            vh_15m[c] = vh_15m[c].fillna(0).astype("int8")
    out["vh_5m"] = vh_5m
    out["vh_15m"] = vh_15m
    print(f"  vh_5m: {vh_5m.shape}")
    print(f"  vh_15m: {vh_15m.shape}")

    # microstructure
    mp = pd.read_parquet(RES / "microstructure_panel.parquet")
    micro_5m = mp[mp.tf == "5m"].copy()
    micro_15m = mp[mp.tf == "15m"].copy()
    print(f"  micro_5m: {micro_5m.shape}, micro_15m: {micro_15m.shape}")
    out["mp_5m_gates"] = build_r3_micro_gates(micro_5m)
    out["mp_15m_gates"] = build_r3_micro_gates(micro_15m)
    print(f"  mp_5m_gates: {out['mp_5m_gates'].shape}")
    print(f"  mp_15m_gates: {out['mp_15m_gates'].shape}")
    return out


# ---------------------------------------------------------------------------
# 4) Concat R2 panel + OOS, then merge R3 gates
# ---------------------------------------------------------------------------
def merge_r3(df: pd.DataFrame, r3: dict, tf: str) -> pd.DataFrame:
    """Merge R3 gates into joined panel df. Both regime gates and directional micro gates."""
    vh_key = "vh_5m" if tf == "5m" else "vh_15m"
    mp_key = "mp_5m_gates" if tf == "5m" else "mp_15m_gates"

    vh = r3[vh_key][["slug", "fire_us"] + [c for c in R3_VOL_GATES if c in r3[vh_key].columns]].drop_duplicates(["slug", "fire_us"])
    mp_g = r3[mp_key]

    out = df.merge(vh, on=["slug", "fire_us"], how="left")
    # Direction-aware micro gates
    out = out.merge(mp_g, on=["slug", "fire_us", "direction"], how="left")

    # fill missing gate vals with 0
    for c in R3_VOL_GATES + R3_MICRO_GATES:
        if c in out.columns:
            out[c] = out[c].fillna(0).astype("int8")
    return out


def build_full_window_for_universe(ftf_label: str, r3: dict) -> pd.DataFrame:
    """Concat existing R2-window panel + OOS holdout, add R3 gates."""
    if ftf_label == "s15_5m":
        base_panel = RES / "s15_joined_all.parquet"
        oos_paths = [FULL / "oos_fires_BTC_5m.parquet",
                     FULL / "oos_fires_ETH_5m.parquet",
                     FULL / "oos_fires_SOL_5m.parquet"]
        # S1.5 fire offsets: 30..270
        valid_offsets = list(range(30, 271, 15)) + list(range(30, 271, 30))
        tf = "5m"
    elif ftf_label == "s6_5m":
        base_panel = RES / "s6_joined_all.parquet"
        oos_paths = [FULL / "oos_fires_BTC_5m.parquet",
                     FULL / "oos_fires_ETH_5m.parquet",
                     FULL / "oos_fires_SOL_5m.parquet"]
        # S6 fire offsets: 15..120
        valid_offsets = [15, 30, 45, 60, 75, 90, 105, 120]
        tf = "5m"
    elif ftf_label == "v15m_15m":
        base_panel = RES / "v15m_joined_all.parquet"
        oos_paths = [FULL / "oos_fires_BTC_15m.parquet",
                     FULL / "oos_fires_ETH_15m.parquet"]
        # 15m offsets 60..840
        valid_offsets = list(range(60, 841, 60))
        tf = "15m"
    else:
        raise ValueError(ftf_label)

    base = pd.read_parquet(base_panel)
    base["_src"] = "base"

    # Load OOS, filter to relevant fire_offsets
    oos_list = []
    for p in oos_paths:
        if not p.exists(): continue
        df = pd.read_parquet(p)
        df = df[df["fire_offset_s"].isin(valid_offsets)].copy()
        df["_src"] = "oos"
        oos_list.append(df)
    oos = pd.concat(oos_list, ignore_index=True) if oos_list else pd.DataFrame()
    if len(oos):
        print(f"  [{ftf_label}] base={len(base):,} oos={len(oos):,}")
    else:
        print(f"  [{ftf_label}] base={len(base):,} oos=empty")

    # Align columns: base has direction+pnl+won; oos has both directions per fire
    common_cols = ["asset", "slug", "fire_us", "direction", "outcome", "won",
                   "pnl_legacy_usd", "fire_offset_s", "_src"]
    g_cols_both = sorted(set(base.columns) & set(oos.columns) if len(oos) else base.columns)
    gate_cols = [c for c in g_cols_both if c.startswith("g_")]
    keep = list(set(common_cols + gate_cols) & set(base.columns))
    base_keep = base[keep].copy() if all(c in base.columns for c in common_cols) else base
    # ensure types
    base_keep["won"] = base_keep["won"].astype(bool) if "won" in base_keep.columns else False

    if len(oos):
        oos_keep = oos[[c for c in keep if c in oos.columns]].copy()
        oos_keep["won"] = oos_keep["won"].astype(bool)
        # Align dtypes
        full = pd.concat([base_keep, oos_keep], ignore_index=True, sort=False)
    else:
        full = base_keep

    # Add R3 gates by merge
    full = merge_r3(full, r3, tf)
    print(f"  [{ftf_label}] full window: {len(full):,} rows, gates: {len([c for c in full.columns if c.startswith('g_')])}")
    return full


# ---------------------------------------------------------------------------
# 5) Gate search machinery (using existing harness)
# ---------------------------------------------------------------------------
def offset_bin_label(off: int, tf: str) -> str | None:
    bins = OFFSET_BINS_5M if tf == "5m" else OFFSET_BINS_15M
    for lo, hi in bins:
        if lo <= off < hi:
            return f"{lo}-{hi}"
    if tf == "5m" and off == 300:
        return "240-300"
    if tf == "15m" and off == 840:
        return "480-900"
    return None


def cell_summary(df: pd.DataFrame, pnl_col: str = "pnl_legacy_usd") -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "wins": 0, "WR": float("nan"), "sum_pnl": 0.0, "dpt": float("nan")}
    pnl = df[pnl_col].astype("float64").values
    wins = int((pnl > 0).sum())
    return {"n": n, "wins": wins, "WR": wins / n,
            "sum_pnl": float(pnl.sum()), "dpt": float(pnl.mean())}


def greedy_stack(df: pd.DataFrame, candidates: list[str], pnl_col: str,
                  min_n: int = MIN_N) -> list[str]:
    chosen = []
    remaining = list(candidates)
    pnl_arr = df[pnl_col].astype("float64").values
    mask = np.ones(len(df), dtype=bool)
    cur_sum = float(pnl_arr[mask].sum())
    while remaining:
        best_g, best_sum = None, cur_sum
        for g in remaining:
            mg = df[g].fillna(False).astype(bool).values
            mn = mask & mg
            n_new = int(mn.sum())
            if n_new < min_n: continue
            s = float(pnl_arr[mn].sum())
            wr_factor = (pnl_arr[mn] > 0).mean()
            score = s * wr_factor
            if score > best_sum * (max((pnl_arr[mask] > 0).mean(), 0.4) if cur_sum > 0 else 0.5):
                # Improvement criterion: strictly higher sum*wr score
                best_g = g
                best_sum = score / max(wr_factor, 0.1)
        if best_g is None: break
        # update
        mask &= df[best_g].fillna(False).astype(bool).values
        cur_sum = float(pnl_arr[mask].sum())
        chosen.append(best_g)
        remaining.remove(best_g)
    return chosen


def run_per_cell(df: pd.DataFrame, candidates: list[str], cell_label: dict,
                  pnl_col: str = "pnl_legacy_usd") -> list[dict]:
    rows = []
    base = cell_summary(df, pnl_col); base.update(cell_label)
    base["gate_stack"] = "(baseline)"; base["k"] = 0
    rows.append(base)
    if len(df) < MIN_N * 2 or not candidates:
        return rows

    # Greedy
    chosen = greedy_stack(df, candidates, pnl_col, min_n=MIN_N)
    if chosen:
        mask = np.ones(len(df), dtype=bool)
        for g in chosen:
            mask &= df[g].fillna(False).astype(bool).values
        s = cell_summary(df.iloc[mask], pnl_col); s.update(cell_label)
        s["gate_stack"] = "&".join(chosen); s["k"] = len(chosen)
        s["search_type"] = "greedy"
        rows.append(s)

    # Exhaustive top-10 from single-gate ranking
    single_results = []
    pnl_arr = df[pnl_col].astype("float64").values
    for g in candidates:
        m = df[g].fillna(False).astype(bool).values
        n_g = int(m.sum())
        if n_g < MIN_N: continue
        sub = pnl_arr[m]
        single_results.append((g, n_g, float(sub.sum()), int((sub > 0).sum()) / n_g))
    single_results.sort(key=lambda x: -x[2])
    top10 = [r[0] for r in single_results[:10]]

    if len(top10) >= 2:
        try:
            gs = gate_search(df, top10, pnl_col=pnl_col, min_n=MIN_N, top_k=5)
        except Exception as e:
            print(f"  gate_search err: {e}")
            gs = pd.DataFrame()
        if len(gs):
            for _, r in gs.iterrows():
                cols = r["gates"].split("&")
                mask = np.ones(len(df), dtype=bool)
                for g in cols:
                    mask &= df[g].fillna(False).astype(bool).values
                s = cell_summary(df.iloc[mask], pnl_col); s.update(cell_label)
                s["gate_stack"] = r["gates"]; s["k"] = int(r["k"])
                s["search_type"] = "exhaustive_top10"
                rows.append(s)
    return rows


# ---------------------------------------------------------------------------
# 6) Walk-forward + bootstrap
# ---------------------------------------------------------------------------
def bootstrap_pvalue(pnl: np.ndarray, n_boot: int = BOOTSTRAP_N) -> float:
    """Probability mean(pnl_shuffled with random signs) >= mean(pnl)."""
    if len(pnl) < 10:
        return float("nan")
    obs = float(pnl.mean())
    if obs <= 0:
        return float("nan")
    n = len(pnl)
    higher = 0
    for _ in range(n_boot):
        signs = RNG.choice([-1, 1], size=n)
        sim = pnl * signs
        if sim.mean() >= obs:
            higher += 1
    return (higher + 1) / (n_boot + 1)


def walk_forward_eval(df: pd.DataFrame, gate_stack: str,
                       train_days: int = 14, test_days: int = 8,
                       pnl_col: str = "pnl_legacy_usd") -> dict:
    """Apply gate_stack to train+test split. Bootstrap p on test."""
    gates = gate_stack.split("&")
    mask = np.ones(len(df), dtype=bool)
    for g in gates:
        if g not in df.columns: return {}
        mask &= df[g].fillna(False).astype(bool).values
    sub = df.iloc[mask].copy().sort_values("fire_us")
    if len(sub) < MIN_N: return {}
    tr, te = walk_forward_split(sub, train_days=train_days, test_days=test_days)
    out = {}
    for name, x in [("train", tr), ("test", te)]:
        if len(x) == 0:
            out[f"{name}_n"] = 0
            continue
        pnl = x[pnl_col].astype("float64").values
        wins = int((pnl > 0).sum())
        out[f"{name}_n"] = len(pnl)
        out[f"{name}_WR"] = wins / len(pnl)
        out[f"{name}_dpt"] = float(pnl.mean())
        out[f"{name}_sum"] = float(pnl.sum())
        if name == "test":
            out["test_pboot"] = bootstrap_pvalue(pnl)
    return out


# ---------------------------------------------------------------------------
# 7) Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 72)
    print("FULL-WINDOW GATE SEARCH — R2 base + R3 winners — Round 4")
    print("=" * 72)
    t0 = time.time()

    print("\n[1] loading R3 panels...")
    r3 = load_r3_panels()

    print("\n[2] building full-window panels per universe...")
    panels = {}
    for tf_label in ["s15_5m", "s6_5m", "v15m_15m"]:
        try:
            panels[tf_label] = build_full_window_for_universe(tf_label, r3)
        except Exception as e:
            print(f"  ERROR building {tf_label}: {e}")
            import traceback; traceback.print_exc()

    print("\n[3] running gate_search per cell...")
    all_rows = []
    per_fire_best = []

    for ftf_label, df in panels.items():
        # Determine candidate gate set
        all_gate_cols = [c for c in df.columns if c.startswith("g_")]
        candidates = sorted(set(all_gate_cols))
        # Drop super-sparse gates
        candidates = [c for c in candidates if df[c].sum() >= MIN_N]
        print(f"\n=== {ftf_label}: {len(candidates)} candidate gates ===")

        tf = "5m" if "5m" in ftf_label else "15m"
        df = df.copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(lambda o: offset_bin_label(o, tf))
        df = df[df["offset_bin"].notna()].copy()

        for asset in ("BTC", "ETH", "SOL"):
            for ob in sorted(df["offset_bin"].unique()):
                sub = df[(df.asset == asset) & (df.offset_bin == ob)]
                if len(sub) < MIN_N * 2:
                    continue
                label = {"asset": asset, "tf": ftf_label, "offset_bin": ob}
                rows = run_per_cell(sub, candidates, label)
                all_rows.extend(rows)
                non_base = [r for r in rows if r["gate_stack"] != "(baseline)"]
                if non_base:
                    best = max(non_base, key=lambda r: r["sum_pnl"])
                    cols_in_stack = best["gate_stack"].split("&")
                    mask = np.ones(len(sub), dtype=bool)
                    for g in cols_in_stack:
                        mask &= sub[g].fillna(False).astype(bool).values
                    pf = sub.iloc[mask][["slug","asset","fire_us","fire_offset_s",
                                          "direction","outcome","won","pnl_legacy_usd"]].copy()
                    pf["tf"] = ftf_label; pf["offset_bin"] = ob
                    pf["gate_stack"] = best["gate_stack"]
                    per_fire_best.append(pf)
                print(f"  {asset} {ob}: n={len(sub):,}  baseline_sum={cell_summary(sub)['sum_pnl']:+.1f}  "
                      f"best='{(non_base[0]['gate_stack'] if non_base else 'n/a')[:60]}' "
                      f"sum={(non_base[0]['sum_pnl'] if non_base else 0.0):+.1f}")

    print(f"\n[4] saving per-cell + top-50...")
    df_all = pd.DataFrame(all_rows)
    df_all = df_all.sort_values(["tf","asset","offset_bin","sum_pnl"],
                                 ascending=[True,True,True,False])
    out_csv = RES / "full_window_gate_search.csv"
    df_all.to_csv(out_csv, index=False)
    print(f"  wrote {out_csv} ({len(df_all):,} rows)")

    top = df_all[df_all["gate_stack"] != "(baseline)"].sort_values("sum_pnl", ascending=False).head(50)
    top.to_csv(RES / "full_window_gate_search_top.csv", index=False)
    print(f"  wrote top 50")

    if per_fire_best:
        pf_all = pd.concat(per_fire_best, ignore_index=True)
        pf_all.to_parquet(RES / "full_window_gate_search_per_fire.parquet",
                           index=False, compression="zstd")

    # Walk-forward on top 50 (Task 4)
    print(f"\n[5] walk-forward + bootstrap on top {min(50, len(top))} stacks...")
    wf_rows = []
    for _, r in top.iterrows():
        ftf = r["tf"]
        if ftf not in panels: continue
        df = panels[ftf]
        tf = "5m" if "5m" in ftf else "15m"
        df = df.copy()
        df["offset_bin"] = df["fire_offset_s"].astype("int64").apply(lambda o: offset_bin_label(o, tf))
        sub = df[(df.asset == r["asset"]) & (df.offset_bin == r["offset_bin"])]
        wf = walk_forward_eval(sub, r["gate_stack"], train_days=14, test_days=8)
        row = {"asset": r["asset"], "tf": ftf, "offset_bin": r["offset_bin"],
               "gate_stack": r["gate_stack"], "full_n": r["n"], "full_sum": r["sum_pnl"],
               "full_WR": r["WR"]}
        row.update(wf)
        wf_rows.append(row)
    wf_df = pd.DataFrame(wf_rows)
    wf_df.to_csv(RES / "full_window_walkforward.csv", index=False)
    print(f"  wrote walk-forward results ({len(wf_df)} stacks)")
    deployable = wf_df[
        (wf_df.get("test_n", 0) >= MIN_N)
        & (wf_df.get("test_WR", 0) >= 0.65)
        & (wf_df.get("test_dpt", 0) >= 1.0)
        & (wf_df.get("test_pboot", 1.0) <= 0.05)
    ] if len(wf_df) else pd.DataFrame()
    print(f"  DEPLOYABLE (test_n>=30, test_WR>=65%, test_dpt>=$1, p<=0.05): {len(deployable)}")

    # Task 5: R2 vs new
    print(f"\n[6] R2 sleeve comparison...")
    r2_sleeves = pd.read_csv(FULL / "sleeve_full_window_validation.csv")
    r2_vs_new = []
    for _, r in r2_sleeves.iterrows():
        sleeve = r["sleeve_id"]
        gate_stack = r["gate_stack"]
        if pd.isna(gate_stack): continue
        # try this stack on full-window
        ftf_map = {"s6": "s6_5m", "s15": "s15_5m", "v15m": "v15m_15m"}
        base_label = r["base"]
        ftf = ftf_map.get(base_label)
        if ftf not in panels: continue
        df = panels[ftf]
        tf = "5m" if "5m" in ftf else "15m"
        # parse offset range
        try:
            off_lo, off_hi = map(int, r["offset_range"].split("-"))
        except Exception:
            off_lo, off_hi = 0, 1000
        sub = df[(df.asset == r["asset"]) & (df.fire_offset_s >= off_lo) & (df.fire_offset_s <= off_hi)]
        gates = gate_stack.split("&")
        # missing gate fix
        missing = [g for g in gates if g not in sub.columns]
        if missing:
            r2_vs_new.append({"sleeve_id": sleeve, "missing_gates": ",".join(missing),
                              "note": "skipped — gate not in panel"})
            continue
        mask = np.ones(len(sub), dtype=bool)
        for g in gates:
            mask &= sub[g].fillna(False).astype(bool).values
        passed = sub.iloc[mask].copy()
        if len(passed) == 0:
            r2_vs_new.append({"sleeve_id": sleeve, "note": "no rows passed"})
            continue
        if r["direction_pick"] == "UP":
            passed = passed[passed.direction == "UP"]
        elif r["direction_pick"] == "DOWN":
            passed = passed[passed.direction == "DOWN"]
        pnl = passed["pnl_legacy_usd"].astype("float64").values
        n = len(pnl); wins = int((pnl > 0).sum())
        wr = wins / n if n else 0.0
        wf = walk_forward_eval(passed, "", train_days=14, test_days=8)  # no gates, just split
        row_out = {
            "sleeve_id": sleeve, "asset": r["asset"], "tf": r["tf"],
            "r2_n": r["ref_n_doc"], "r2_WR": r["ref_wr_doc"], "r2_dpt": r["ref_dpt_doc"], "r2_sum": r["ref_sum_doc"],
            "full_n": n, "full_WR": wr, "full_dpt": float(pnl.mean()) if n else 0.0,
            "full_sum": float(pnl.sum()),
        }
        row_out.update(wf)
        r2_vs_new.append(row_out)
    r2_df = pd.DataFrame(r2_vs_new)
    r2_df.to_csv(RES / "full_window_r2_vs_new.csv", index=False)
    print(f"  wrote R2 sleeve comparison ({len(r2_df)} sleeves)")

    # Task 6: R3 marginal contribution
    print(f"\n[7] R3 gate marginal contribution per Tier-1 sleeve...")
    contrib = []
    R3_ALL = R3_VOL_GATES + R3_MICRO_GATES
    for _, r in r2_sleeves.head(15).iterrows():
        sleeve = r["sleeve_id"]
        ftf_map = {"s6": "s6_5m", "s15": "s15_5m", "v15m": "v15m_15m"}
        ftf = ftf_map.get(r["base"])
        if ftf not in panels: continue
        df = panels[ftf]
        try:
            off_lo, off_hi = map(int, r["offset_range"].split("-"))
        except Exception:
            off_lo, off_hi = 0, 1000
        sub = df[(df.asset == r["asset"]) & (df.fire_offset_s >= off_lo) & (df.fire_offset_s <= off_hi)]
        gates = r["gate_stack"].split("&")
        miss = [g for g in gates if g not in sub.columns]
        if miss: continue
        mask = np.ones(len(sub), dtype=bool)
        for g in gates: mask &= sub[g].fillna(False).astype(bool).values
        base_sub = sub.iloc[mask].copy()
        if r["direction_pick"] == "UP":
            base_sub = base_sub[base_sub.direction == "UP"]
        elif r["direction_pick"] == "DOWN":
            base_sub = base_sub[base_sub.direction == "DOWN"]
        if len(base_sub) < MIN_N: continue
        base_dpt = base_sub["pnl_legacy_usd"].mean()
        base_n = len(base_sub)
        base_sum = base_sub["pnl_legacy_usd"].sum()
        base_wr = (base_sub["pnl_legacy_usd"] > 0).mean()
        for r3_gate in R3_ALL:
            if r3_gate not in base_sub.columns: continue
            m_r3 = base_sub[r3_gate].fillna(False).astype(bool).values
            if m_r3.sum() < MIN_N: continue
            with_r3 = base_sub[m_r3]
            n2 = len(with_r3); wr2 = (with_r3["pnl_legacy_usd"] > 0).mean()
            dpt2 = with_r3["pnl_legacy_usd"].mean(); sum2 = with_r3["pnl_legacy_usd"].sum()
            contrib.append({
                "sleeve_id": sleeve, "r3_gate": r3_gate,
                "base_n": base_n, "base_WR": base_wr, "base_dpt": base_dpt, "base_sum": base_sum,
                "with_n": n2, "with_WR": wr2, "with_dpt": dpt2, "with_sum": sum2,
                "wr_lift_pp": (wr2 - base_wr) * 100,
                "dpt_lift": dpt2 - base_dpt,
                "retention_pct": n2 / base_n * 100,
            })
    contrib_df = pd.DataFrame(contrib)
    if len(contrib_df):
        contrib_df = contrib_df.sort_values("dpt_lift", ascending=False)
    contrib_df.to_csv(RES / "full_window_r3_contribution.csv", index=False)
    print(f"  wrote R3 contribution matrix ({len(contrib_df)} sleeve×gate)")

    print(f"\n[done] {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
