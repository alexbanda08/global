"""DRZ standalone direction-signal test on Polymarket up-down universe.

For each fire row in `drz_panel_{tf}.parquet` (which has DRZ state at fire_us-1s
plus filled vwap/shares for UP and DOWN sides), evaluate 4 direction rules:

  Rule A: UP   when drz_recent_RC AND drz_in_support_zone
  Rule B: DOWN when drz_recent_RE AND drz_in_resistance_zone
  Rule C: UP   when drz_in_support_zone     AND drz_zone_sup_pos_pct > 60 (buy-flow dom)
  Rule D: DOWN when drz_in_resistance_zone  AND drz_zone_res_pos_pct < 40 (sell-flow dom)

For each (asset, tf, offset_bin, rule):
  - n, wins, WR, mean_pnl, sum_pnl  (engine_v2.LegacyConfig fees, $25 notional)

Output: data/v4/canonical/_results/drz_standalone_results.csv
"""
from __future__ import annotations
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
RES = ROOT / "data" / "v4" / "canonical" / "_results"

# offset bins per timeframe (matches hybrid_gate_search.py)
OFFSET_BINS_5M = [(60, 150), (150, 240), (240, 300)]
OFFSET_BINS_15M = [(60, 240), (240, 480), (480, 840)]

# Legacy fee: 2% on winning leg profit only
LEGACY_FEE = 0.02


def legacy_pnl(vwap: float, shares: float, usd: float, won: bool) -> float:
    """LegacyConfig hold_pnl: 2% × profit when won; -usd when lost."""
    if not np.isfinite(vwap) or shares <= 0 or usd <= 0:
        return np.nan
    if won:
        gross = shares * 1.0 - usd
        return gross - (gross * LEGACY_FEE if gross > 0 else 0.0)
    return -usd


def offset_bin(off: int, tf: str) -> str | None:
    bins = OFFSET_BINS_5M if tf == "5m" else OFFSET_BINS_15M
    for lo, hi in bins:
        if lo <= off < hi:
            return f"{lo}-{hi}"
    if tf == "5m" and off == 300:
        return "240-300"
    if tf == "15m" and off == 840:
        return "480-840"
    return None


def compute_per_fire_pnl(panel: pd.DataFrame, rule_name: str,
                          direction_col: str) -> pd.DataFrame:
    """Given a panel with a binary signal column for which fires take which direction,
    compute per-fire pnl using the right side's fill cols + outcome.

    direction_col holds 'UP'/'DOWN'/None (None = abstain).
    """
    df = panel.copy()
    df["direction"] = direction_col
    df = df[df["direction"].isin(["UP", "DOWN"])].copy()
    df["won"] = ((df["direction"] == "UP") & (df["outcome"] == "Up")) | \
                ((df["direction"] == "DOWN") & (df["outcome"] == "Down"))
    # pick vwap/shares/usd by direction
    up = (df["direction"] == "UP")
    df.loc[up, "vwap"] = df.loc[up, "up_vwap"]
    df.loc[up, "shares"] = df.loc[up, "up_shares"]
    df.loc[up, "usd"] = df.loc[up, "up_usd"]
    df.loc[up, "fill_ok"] = df.loc[up, "up_fill_ok"]
    df.loc[~up, "vwap"] = df.loc[~up, "dn_vwap"]
    df.loc[~up, "shares"] = df.loc[~up, "dn_shares"]
    df.loc[~up, "usd"] = df.loc[~up, "dn_usd"]
    df.loc[~up, "fill_ok"] = df.loc[~up, "dn_fill_ok"]
    df = df[df["fill_ok"] == True].copy()
    if len(df) == 0:
        df["pnl"] = []
        df["rule"] = rule_name
        return df
    df["pnl"] = df.apply(lambda r: legacy_pnl(r["vwap"], r["shares"], r["usd"], r["won"]), axis=1)
    df = df.dropna(subset=["pnl"])
    df["rule"] = rule_name
    return df


def evaluate_panel(panel: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Apply 4 rules + baseline; produce per-fire pnl tables, then aggregate."""
    panel = panel.copy()
    panel["offset_bin"] = panel["fire_offset_s"].astype("int64").apply(lambda o: offset_bin(int(o), tf))
    panel = panel[panel["offset_bin"].notna()].copy()

    rule_dfs = []
    # Rule A: UP when recent_RC + in support
    mask_a = panel["drz_recent_RC"] & panel["drz_in_support_zone"]
    dir_a = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_a[mask_a] = "UP"
    rule_dfs.append(compute_per_fire_pnl(panel, "A_RC_at_support_UP", dir_a))

    # Rule B: DOWN when recent_RE + in resistance
    mask_b = panel["drz_recent_RE"] & panel["drz_in_resistance_zone"]
    dir_b = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_b[mask_b] = "DOWN"
    rule_dfs.append(compute_per_fire_pnl(panel, "B_RE_at_resistance_DOWN", dir_b))

    # Rule C: UP when in support + sup_pos_pct > 60
    mask_c = panel["drz_in_support_zone"] & (panel["drz_zone_sup_pos_pct"] > 60.0)
    dir_c = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_c[mask_c] = "UP"
    rule_dfs.append(compute_per_fire_pnl(panel, "C_support_buyflow_UP", dir_c))

    # Rule D: DOWN when in resistance + res_pos_pct < 40 (sell flow dominates)
    mask_d = panel["drz_in_resistance_zone"] & (panel["drz_zone_res_pos_pct"] < 40.0)
    dir_d = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_d[mask_d] = "DOWN"
    rule_dfs.append(compute_per_fire_pnl(panel, "D_resistance_sellflow_DOWN", dir_d))

    # Bonus: directional "at support -> UP" without RC requirement
    mask_e = panel["drz_in_support_zone"]
    dir_e = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_e[mask_e] = "UP"
    rule_dfs.append(compute_per_fire_pnl(panel, "E_at_support_UP", dir_e))

    # Bonus: directional "at resistance -> DOWN" without RE requirement
    mask_f = panel["drz_in_resistance_zone"]
    dir_f = pd.Series([None] * len(panel), index=panel.index, dtype="object")
    dir_f[mask_f] = "DOWN"
    rule_dfs.append(compute_per_fire_pnl(panel, "F_at_resistance_DOWN", dir_f))

    big = pd.concat(rule_dfs, ignore_index=True)
    if len(big) == 0:
        return pd.DataFrame()
    big["tf"] = tf

    # Aggregate
    agg = big.groupby(["rule", "asset", "tf", "offset_bin"]).agg(
        n=("pnl", "size"),
        wins=("won", "sum"),
        sum_pnl=("pnl", "sum"),
        mean_pnl=("pnl", "mean"),
    ).reset_index()
    agg["WR"] = agg["wins"] / agg["n"]
    agg = agg.sort_values("sum_pnl", ascending=False)
    return agg


def main():
    t0 = time.time()
    print("=" * 72); print("DRZ STANDALONE SIGNAL TEST"); print("=" * 72)

    all_rows = []
    for tf in ("5m", "15m"):
        p = pd.read_parquet(RES / f"drz_panel_{tf}.parquet")
        print(f"\n[{tf}] panel: {len(p):,}")
        agg = evaluate_panel(p, tf)
        if len(agg):
            all_rows.append(agg)

    if not all_rows:
        print("EMPTY"); return
    full = pd.concat(all_rows, ignore_index=True)
    full = full[full["n"] >= 20].sort_values("sum_pnl", ascending=False)
    out = RES / "drz_standalone_results.csv"
    full.to_csv(out, index=False)
    print(f"\nWrote {out} ({len(full)} rows)")
    pd.set_option("display.width", 240); pd.set_option("display.max_colwidth", 80)
    print("\nTop 20 by sum_pnl (n>=20):")
    print(full.head(20).to_string(index=False))

    print(f"\nDONE in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
