"""V8 Topic 1 — 2-asset and 3-asset confluence ensembles.

For BTC 5m fires, for each fire compute the joint signal from BTC + ETH + SOL using
their RF direction (rf_dir at fire_us-1s), regime_panel_5m_v2_fixed trend_slope_30m
(at fire_us-1s, asof bar END), and microprice (asof at fire_us). For each test asset
we declare a per-asset directional signal:

  per_asset_sig(asset, fire_us):
    rf  = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)
    ts  = trend_slope_30m on regime_panel_5m_v2_fixed asof (fire_us - 1_000_000)
    sig = +1 if (rf == 1 and ts > 0) else -1 if (rf == -1 and ts < 0) else 0

Microprice is per-slug (target slug only), so we don't use it as a cross-asset signal —
it's already a per-fire feature. For confluence we use rf + slope only (both available
for any asset at any timestamp).

Then we test:
  - 2-asset confluence: BTC + ETH agree (SOL ignored). Direction == that sign.
  - 2-asset confluence: BTC + SOL agree.
  - 2-asset confluence: ETH + SOL agree (irrelevant for ETH target — see below).
  - 3-asset unanimity: all 3 agree on same direction.

For each gate, compute:
  - n fires
  - WR (won mean)
  - $/tr (pnl_legacy_usd mean)
  - vs baseline

Baseline = direction-matching fires (the trivial "WR is the outcome match rate ~50%").

Test on BTC 5m as primary (per brief), but also report ETH 5m and SOL 5m briefly.

Output:
  _v8_research/topic1_confluence_btc5m.csv
  _v8_research/topic1_confluence_summary.csv
"""
from __future__ import annotations

import sys
from pathlib import Path
from bisect import bisect_right

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT_DIR = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "_v8_research"
OUT_DIR.mkdir(exist_ok=True, parents=True)

BASE = ROOT / "data" / "v4" / "canonical" / "_results"
FBASE = BASE / "_full_window_v3_2026_05_27"


def load_per_asset_signal_panels():
    """Returns dict[asset] = dict('rf_ts_us' -> sorted np.array, 'rf_dir' -> np.array,
                                 'trend_ts_us' -> sorted np.array, 'trend_slope' -> np.array).
    Per-asset, used for asof-strict join.
    """
    rf = pd.read_parquet(BASE / "range_filter_1s.parquet", columns=["asset", "ts_us", "rf_dir"])
    rp5 = pd.read_parquet(BASE / "regime_panel_5m_v2_fixed.parquet",
                          columns=["asset", "ts_us", "trend_slope_30m"])
    out = {}
    for a in ["BTC", "ETH", "SOL"]:
        rf_a = rf[rf.asset == a].sort_values("ts_us")
        rp_a = rp5[rp5.asset == a].sort_values("ts_us")
        out[a] = {
            "rf_ts": rf_a["ts_us"].values.astype(np.int64),
            "rf_dir": rf_a["rf_dir"].values.astype(np.int8),
            "trend_ts": rp_a["ts_us"].values.astype(np.int64),
            "trend_slope": rp_a["trend_slope_30m"].values.astype(np.float32),
        }
    return out


def per_asset_sig(asset_panel, fire_us_arr: np.ndarray) -> np.ndarray:
    """For each fire_us, return signed signal (+1/-1/0) for this asset.

    Signal = +1 iff rf_dir==1 AND trend_slope>0; -1 iff rf_dir==-1 AND trend_slope<0; else 0.
    Both panels asof at (fire_us - 1_000_000) — strict bar-END backward asof.
    """
    rf_ts = asset_panel["rf_ts"]
    rf_dir = asset_panel["rf_dir"]
    trend_ts = asset_panel["trend_ts"]
    trend_sl = asset_panel["trend_slope"]
    out = np.zeros(len(fire_us_arr), dtype=np.int8)
    for i, fus in enumerate(fire_us_arr):
        target = int(fus) - 1_000_000
        # rf_dir asof
        idx_rf = np.searchsorted(rf_ts, target, side="right") - 1
        if idx_rf < 0: continue
        rd = int(rf_dir[idx_rf])
        # trend_slope asof
        idx_tr = np.searchsorted(trend_ts, target, side="right") - 1
        if idx_tr < 0: continue
        ts = float(trend_sl[idx_tr])
        if not np.isfinite(ts): continue
        if rd == 1 and ts > 0: out[i] = 1
        elif rd == -1 and ts < 0: out[i] = -1
    return out


def per_asset_sig_rf_only(asset_panel, fire_us_arr: np.ndarray) -> np.ndarray:
    """Pure RF direction at fire_us-1s, per asset."""
    rf_ts = asset_panel["rf_ts"]
    rf_dir = asset_panel["rf_dir"]
    out = np.zeros(len(fire_us_arr), dtype=np.int8)
    for i, fus in enumerate(fire_us_arr):
        target = int(fus) - 1_000_000
        idx_rf = np.searchsorted(rf_ts, target, side="right") - 1
        if idx_rf < 0: continue
        out[i] = int(rf_dir[idx_rf])
    return out


def per_asset_sig_slope_only(asset_panel, fire_us_arr: np.ndarray) -> np.ndarray:
    """Pure trend_slope sign."""
    trend_ts = asset_panel["trend_ts"]
    trend_sl = asset_panel["trend_slope"]
    out = np.zeros(len(fire_us_arr), dtype=np.int8)
    for i, fus in enumerate(fire_us_arr):
        target = int(fus) - 1_000_000
        idx_tr = np.searchsorted(trend_ts, target, side="right") - 1
        if idx_tr < 0: continue
        ts = float(trend_sl[idx_tr])
        if not np.isfinite(ts) or ts == 0: continue
        out[i] = 1 if ts > 0 else -1
    return out


def summarize(label: str, df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"label": label, "n": 0, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0}
    return {
        "label": label,
        "n": len(df),
        "wr": float(df["won"].mean()),
        "dpt": float(df["pnl_legacy_usd"].mean()),
        "tot_pnl": float(df["pnl_legacy_usd"].sum()),
    }


def run_market(market: str, panels: dict, target_asset: str) -> list[dict]:
    """For a (target_asset, tf) market — measure confluence gates.

    `market` = e.g. 'BTC_5m'. `target_asset` = e.g. 'BTC'.
    Companions = other 2 assets.
    """
    asset, tf = market.split("_")
    fpath = FBASE / f"oos_fires_{asset}_{tf}_v3_fixed.parquet"
    fires = pd.read_parquet(fpath)
    fires = fires[fires.fire_us > 0].copy()
    fires = fires.sort_values("fire_us").reset_index(drop=True)
    n0 = len(fires)
    print(f"[{market}] fires loaded: {n0:,}", flush=True)

    fire_us_arr = fires["fire_us"].values.astype(np.int64)

    # Compute per-asset signals for ALL 3 assets (combined: rf AND slope must agree)
    sigs = {}
    for a in ["BTC", "ETH", "SOL"]:
        sigs[a] = per_asset_sig(panels[a], fire_us_arr)
    # Also pure-rf and pure-slope variants for diagnostic
    sigs_rf = {a: per_asset_sig_rf_only(panels[a], fire_us_arr) for a in ["BTC", "ETH", "SOL"]}
    sigs_sl = {a: per_asset_sig_slope_only(panels[a], fire_us_arr) for a in ["BTC", "ETH", "SOL"]}

    # Direction as numeric: UP=+1 DOWN=-1
    direction = np.where(fires["direction"].values == "UP", 1, -1).astype(np.int8)
    won = fires["won"].values.astype(np.int8)
    pnl = fires["pnl_legacy_usd"].values.astype(np.float64)

    fires_n = fires.copy()
    fires_n["dir_num"] = direction
    for a in ["BTC", "ETH", "SOL"]:
        fires_n[f"sig_combined_{a}"] = sigs[a]
        fires_n[f"sig_rf_{a}"] = sigs_rf[a]
        fires_n[f"sig_slope_{a}"] = sigs_sl[a]

    results = []
    # Baseline
    results.append({"market": market, **summarize("baseline_all", fires_n)})

    # Companion definitions
    others = [a for a in ["BTC", "ETH", "SOL"] if a != target_asset]
    a1, a2 = others
    print(f"  target={target_asset}, companions={others}", flush=True)

    # ---- Variant A: RF-only confluence (lighter signal) ----
    # 3-asset RF unanimity
    mask = (
        (sigs_rf[target_asset] == direction) &
        (sigs_rf[a1] == direction) &
        (sigs_rf[a2] == direction)
    )
    results.append({"market": market, **summarize(f"rf_only_3asset_unanimity", fires_n[mask])})

    # 2-asset RF (target + a1 agree)
    mask = (sigs_rf[target_asset] == direction) & (sigs_rf[a1] == direction)
    results.append({"market": market, **summarize(f"rf_only_2asset_{target_asset}+{a1}", fires_n[mask])})
    mask = (sigs_rf[target_asset] == direction) & (sigs_rf[a2] == direction)
    results.append({"market": market, **summarize(f"rf_only_2asset_{target_asset}+{a2}", fires_n[mask])})

    # Companions only (excluding target itself — pure cross-asset)
    mask = (sigs_rf[a1] == direction) & (sigs_rf[a2] == direction)
    results.append({"market": market, **summarize(f"rf_only_companions_{a1}+{a2}", fires_n[mask])})

    # ---- Variant B: slope-only confluence ----
    mask = (
        (sigs_sl[target_asset] == direction) &
        (sigs_sl[a1] == direction) &
        (sigs_sl[a2] == direction)
    )
    results.append({"market": market, **summarize(f"slope_only_3asset_unanimity", fires_n[mask])})

    mask = (sigs_sl[a1] == direction) & (sigs_sl[a2] == direction)
    results.append({"market": market, **summarize(f"slope_only_companions_{a1}+{a2}", fires_n[mask])})

    # ---- Variant C: combined RF+slope confluence ----
    mask = (
        (sigs[target_asset] == direction) &
        (sigs[a1] == direction) &
        (sigs[a2] == direction)
    )
    results.append({"market": market, **summarize(f"combined_3asset_unanimity", fires_n[mask])})

    mask = (sigs[target_asset] == direction) & (sigs[a1] == direction)
    results.append({"market": market, **summarize(f"combined_2asset_{target_asset}+{a1}", fires_n[mask])})

    mask = (sigs[target_asset] == direction) & (sigs[a2] == direction)
    results.append({"market": market, **summarize(f"combined_2asset_{target_asset}+{a2}", fires_n[mask])})

    mask = (sigs[a1] == direction) & (sigs[a2] == direction)
    results.append({"market": market, **summarize(f"combined_companions_{a1}+{a2}", fires_n[mask])})

    # ---- Variant D: any-2-of-3 (relaxed unanimity) ----
    sig_sum = sigs[target_asset] + sigs[a1] + sigs[a2]
    # majority vote = matches direction if 2 or 3 of 3 agree
    mask = (
        ((sig_sum == 3) & (direction == 1)) |
        ((sig_sum == -3) & (direction == -1))
    )
    results.append({"market": market, **summarize(f"combined_3asset_unanimous_signed", fires_n[mask])})
    mask = (
        ((sig_sum >= 2) & (direction == 1)) |
        ((sig_sum <= -2) & (direction == -1))
    )
    results.append({"market": market, **summarize(f"combined_2of3_majority", fires_n[mask])})

    # ---- Diagnostic: rate of unanimity events ----
    n_combined_all = int(np.sum(
        ((sig_sum == 3) | (sig_sum == -3))
    ))
    results.append({"market": market, "label": "diag_n_unanimous_events_either_dir",
                    "n": n_combined_all, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0})

    return results


def main():
    print("Loading per-asset signal panels...", flush=True)
    panels = load_per_asset_signal_panels()
    for a, p in panels.items():
        print(f"  {a}: rf rows={len(p['rf_ts']):,}, regime rows={len(p['trend_ts']):,}", flush=True)

    all_rows = []
    # Markets requested in brief: start with BTC 5m. Extend.
    for market, target in [("BTC_5m", "BTC"), ("ETH_5m", "ETH"), ("SOL_5m", "SOL"),
                            ("BTC_15m", "BTC"), ("ETH_15m", "ETH"), ("SOL_15m", "SOL")]:
        rows = run_market(market, panels, target)
        all_rows.extend(rows)

    df = pd.DataFrame(all_rows)
    # Compute lift vs baseline per market
    out = []
    for market, sub in df.groupby("market", sort=False):
        base = sub[sub.label == "baseline_all"].iloc[0]
        for _, r in sub.iterrows():
            row = r.to_dict()
            if r["label"] == "baseline_all":
                row["wr_lift_pp"] = 0.0
                row["dpt_lift"] = 0.0
                row["pct_universe"] = 1.0
            else:
                row["wr_lift_pp"] = (r["wr"] - base["wr"]) * 100 if r["n"] > 0 else np.nan
                row["dpt_lift"] = (r["dpt"] - base["dpt"]) if r["n"] > 0 else np.nan
                row["pct_universe"] = r["n"] / base["n"] if base["n"] else 0.0
            out.append(row)
    df_out = pd.DataFrame(out)
    df_out.to_csv(OUT_DIR / "topic1_confluence_summary.csv", index=False)
    print()
    print("=== Topic 1 Confluence — summary ===")
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.width", 200)
    print(df_out[["market", "label", "n", "wr", "dpt", "wr_lift_pp", "dpt_lift", "pct_universe"]].to_string(index=False))
    print(f"\nWrote: {OUT_DIR / 'topic1_confluence_summary.csv'}", flush=True)


if __name__ == "__main__":
    main()
