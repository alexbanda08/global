"""V8 Topic 3 — 1h grandparent regime cascade.

Test the gate stack 5m_fire + 15m_parent_aligned + 1h_grandparent_aligned.

g_grandparent_1h_trend_with(direction, fire_us, asset):
  ts = asof_bar_end(asset, "1h", fire_us - 1_000_000)
  label = regime_panel_1h[asset].regime_label at ts
  return (label == "trending_up" and direction == "UP") or
         (label == "trending_dn" and direction == "DOWN")

g_parent_15m_trend_with: same on regime_panel_15m_v2_fixed (already wired into V6/V7)

Test on BTC 5m primarily (per brief). Also report ETH 5m, SOL 5m, ETH 15m.

Cascade lifts:
  - baseline_all
  - g_5m_aligned (RF + slope agrees)
  - g_5m + g_15m_parent
  - g_5m + g_15m + g_1h_grandparent
  - g_15m + g_1h only (no 5m gate; pure 15m+1h cascade)
  - g_1h only

Output:
  _v8_research/topic3_grandparent_cascade.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT_DIR = ROOT / "strategy_lab" / "sniper_search_2026_05_27" / "_v8_research"
OUT_DIR.mkdir(exist_ok=True, parents=True)

BASE = ROOT / "data" / "v4" / "canonical" / "_results"
FBASE = BASE / "_full_window_v3_2026_05_27"


def load_regime_panels():
    """Returns dict[(asset, tf)] = sorted arrays (ts_us, regime_label, trend_slope_30m)."""
    panels = {}
    for tf, fname in [("5m", "regime_panel_5m_v2_fixed.parquet"),
                       ("15m", "regime_panel_15m_v2_fixed.parquet"),
                       ("1h", "regime_panel_1h.parquet")]:
        df = pd.read_parquet(BASE / fname, columns=["asset", "ts_us", "regime_label", "trend_slope_30m"])
        for a in ["BTC", "ETH", "SOL"]:
            sub = df[df.asset == a].sort_values("ts_us")
            panels[(a, tf)] = {
                "ts": sub["ts_us"].values.astype(np.int64),
                "label": sub["regime_label"].values.astype(object),
                "slope": sub["trend_slope_30m"].values.astype(np.float32),
            }
    return panels


def asof_label(panel, fire_us_arr: np.ndarray) -> np.ndarray:
    """Return asof regime_label at fire_us-1s. NaN-string for no-prior."""
    ts = panel["ts"]
    lab = panel["label"]
    out = np.empty(len(fire_us_arr), dtype=object)
    for i, fus in enumerate(fire_us_arr):
        target = int(fus) - 1_000_000
        idx = np.searchsorted(ts, target, side="right") - 1
        out[i] = lab[idx] if idx >= 0 else "missing"
    return out


def asof_slope_sign(panel, fire_us_arr: np.ndarray) -> np.ndarray:
    ts = panel["ts"]
    sl = panel["slope"]
    out = np.zeros(len(fire_us_arr), dtype=np.int8)
    for i, fus in enumerate(fire_us_arr):
        target = int(fus) - 1_000_000
        idx = np.searchsorted(ts, target, side="right") - 1
        if idx < 0: continue
        s = float(sl[idx])
        if not np.isfinite(s) or s == 0: continue
        out[i] = 1 if s > 0 else -1
    return out


def gate_trend_with(label_arr: np.ndarray, direction_arr: np.ndarray) -> np.ndarray:
    """label == trending_up AND direction == UP, OR label == trending_dn AND direction == DOWN."""
    is_up = direction_arr == 1
    is_dn = direction_arr == -1
    return (
        ((label_arr == "trending_up") & is_up) |
        ((label_arr == "trending_dn") & is_dn)
    )


def gate_slope_with(slope_sign: np.ndarray, direction_arr: np.ndarray) -> np.ndarray:
    return slope_sign == direction_arr


def summarize(label: str, mask: np.ndarray, fires_df: pd.DataFrame) -> dict:
    sub = fires_df[mask]
    if len(sub) == 0:
        return {"label": label, "n": 0, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0}
    return {
        "label": label,
        "n": int(len(sub)),
        "wr": float(sub["won"].mean()),
        "dpt": float(sub["pnl_legacy_usd"].mean()),
        "tot_pnl": float(sub["pnl_legacy_usd"].sum()),
    }


def run_market(market: str, panels: dict) -> list[dict]:
    asset, tf = market.split("_")
    fpath = FBASE / f"oos_fires_{asset}_{tf}_v3_fixed.parquet"
    fires = pd.read_parquet(fpath)
    fires = fires[fires.fire_us > 0].sort_values("fire_us").reset_index(drop=True)
    n0 = len(fires)
    print(f"[{market}] n={n0:,}", flush=True)

    fire_us_arr = fires["fire_us"].values.astype(np.int64)
    direction = np.where(fires["direction"].values == "UP", 1, -1).astype(np.int8)

    # 5m, 15m, 1h labels and slope signs for THIS asset
    lab_5m  = asof_label(panels[(asset, "5m")],  fire_us_arr)
    lab_15m = asof_label(panels[(asset, "15m")], fire_us_arr)
    lab_1h  = asof_label(panels[(asset, "1h")],  fire_us_arr)
    sl_5m   = asof_slope_sign(panels[(asset, "5m")],  fire_us_arr)
    sl_15m  = asof_slope_sign(panels[(asset, "15m")], fire_us_arr)
    sl_1h   = asof_slope_sign(panels[(asset, "1h")],  fire_us_arr)

    g_5m  = gate_trend_with(lab_5m, direction)
    g_15m = gate_trend_with(lab_15m, direction)
    g_1h  = gate_trend_with(lab_1h, direction)
    s_5m  = gate_slope_with(sl_5m, direction)
    s_15m = gate_slope_with(sl_15m, direction)
    s_1h  = gate_slope_with(sl_1h, direction)

    # rf_dir gate for the asset (use fire's embedded rf_dir col)
    rf_with = np.zeros(len(fires), dtype=bool)
    rf_with[(fires["rf_dir"].values == 1)  & (direction == 1)] = True
    rf_with[(fires["rf_dir"].values == -1) & (direction == -1)] = True

    out = []
    out.append({"market": market, **summarize("baseline_all", np.ones(n0, dtype=bool), fires)})

    # Single layers
    out.append({"market": market, **summarize("g_5m_trend_with",  g_5m,  fires)})
    out.append({"market": market, **summarize("g_15m_trend_with", g_15m, fires)})
    out.append({"market": market, **summarize("g_1h_trend_with",  g_1h,  fires)})
    out.append({"market": market, **summarize("s_5m_slope_with",  s_5m,  fires)})
    out.append({"market": market, **summarize("s_15m_slope_with", s_15m, fires)})
    out.append({"market": market, **summarize("s_1h_slope_with",  s_1h,  fires)})

    # Cascades
    out.append({"market": market, **summarize("cascade_15m+1h_trend_with",
                                                g_15m & g_1h, fires)})
    out.append({"market": market, **summarize("cascade_5m+15m_trend_with",
                                                g_5m & g_15m, fires)})
    out.append({"market": market, **summarize("cascade_5m+15m+1h_trend_with",
                                                g_5m & g_15m & g_1h, fires)})
    out.append({"market": market, **summarize("cascade_15m+1h_slope_with",
                                                s_15m & s_1h, fires)})
    out.append({"market": market, **summarize("cascade_5m+15m+1h_slope_with",
                                                s_5m & s_15m & s_1h, fires)})
    out.append({"market": market, **summarize("rf+1h_grandparent",
                                                rf_with & g_1h, fires)})
    out.append({"market": market, **summarize("rf+15m+1h_grandparent",
                                                rf_with & g_15m & g_1h, fires)})
    out.append({"market": market, **summarize("rf+slope_1h",
                                                rf_with & s_1h, fires)})
    out.append({"market": market, **summarize("rf+slope_15m+slope_1h",
                                                rf_with & s_15m & s_1h, fires)})

    # Diagnostic: just 1h aligned
    out.append({"market": market, "label": "diag_1h_label_distribution_at_fires",
                "n": n0, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0})
    for lab in ["trending_up", "trending_dn", "ranging", "missing"]:
        c = int(np.sum(lab_1h == lab))
        out.append({"market": market, "label": f"  diag_1h_label={lab}",
                    "n": c, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0})

    return out


def main():
    panels = load_regime_panels()
    for k, v in panels.items():
        print(f"  panel {k}: {len(v['ts'])} rows", flush=True)

    all_rows = []
    for market in ["BTC_5m", "ETH_5m", "SOL_5m", "BTC_15m", "ETH_15m", "SOL_15m"]:
        all_rows.extend(run_market(market, panels))

    df = pd.DataFrame(all_rows)
    # Lift vs baseline per market
    rows = []
    for m, sub in df.groupby("market", sort=False):
        base = sub[sub.label == "baseline_all"].iloc[0]
        for _, r in sub.iterrows():
            row = r.to_dict()
            if pd.isna(r["wr"]) or r["n"] == 0:
                row["wr_lift_pp"] = np.nan
                row["dpt_lift"] = np.nan
                row["pct_universe"] = r["n"] / base["n"] if base["n"] else 0
            else:
                row["wr_lift_pp"] = (r["wr"] - base["wr"]) * 100
                row["dpt_lift"] = (r["dpt"] - base["dpt"])
                row["pct_universe"] = r["n"] / base["n"]
            rows.append(row)
    out = pd.DataFrame(rows)
    out.to_csv(OUT_DIR / "topic3_grandparent_cascade.csv", index=False)
    print()
    print("=== Topic 3 — Grandparent 1h cascade ===")
    pd.set_option("display.max_rows", 300)
    pd.set_option("display.width", 220)
    print(out[["market", "label", "n", "wr", "dpt", "wr_lift_pp", "dpt_lift", "pct_universe"]].to_string(index=False))
    print(f"\nWrote: {OUT_DIR/'topic3_grandparent_cascade.csv'}", flush=True)


if __name__ == "__main__":
    main()
