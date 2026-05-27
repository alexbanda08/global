"""V8 Topic 2 — Time-of-Day systematic specialization.

For each market (BTC/ETH/SOL × 5m/15m), partition v3 fires into 4 TOD buckets:
  asia_morning      [0,7) UTC
  european_morning  [7,13) UTC
  us_afternoon      [13,19) UTC
  us_evening        [19,24) UTC

For each (market, TOD) cell, compute baseline WR + ungated $/tr.

For each V7-known "winner" stack (using existing gates in v3 fires for portability),
recompute metrics per TOD bucket to find specialization.

V7-derived candidate stacks (using only v3-embedded gate cols):
  S1: g_rf_with==1
  S2: g_rf_with==1 AND g_tr_above_ema200==1
  S3: g_rf_with==1 AND g_trend_slope_with==1 AND g_hurst_trending==1  (need to derive from regime_panel)
  S4: g_rf_with==1 AND g_tr_above_ema200==1 AND g_mfi_with==1
  S5: g_rf_with==1 AND g_tr_above_ema200==1 AND g_ribbon_agrees==1

Also: per-market TOD-only test (no other gates) — does baseline shift by TOD?

Output:
  _v8_research/topic2_tod_baseline.csv  (per market×TOD baseline)
  _v8_research/topic2_tod_stacks.csv    (per market×TOD×stack metrics)
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

TOD_BUCKETS = {
    "asia_morning":     list(range(0, 7)),
    "european_morning": list(range(7, 13)),
    "us_afternoon":     list(range(13, 19)),
    "us_evening":       list(range(19, 24)),
}

# Stacks expressed as boolean predicates on v3 fire df
def stack_S1(df):
    return df["g_rf_with"] == 1

def stack_S2(df):
    return (df["g_rf_with"] == 1) & (df["g_tr_above_ema200"] == 1)

def stack_S3(df):
    # rf + tr_above_ema200 + ribbon_agrees
    return (df["g_rf_with"] == 1) & (df["g_tr_above_ema200"] == 1) & (df["g_ribbon_agrees"] == 1)

def stack_S4(df):
    return (df["g_rf_with"] == 1) & (df["g_tr_above_ema200"] == 1) & (df["g_mfi_with"] == 1)

def stack_S5(df):
    return (df["g_rf_with"] == 1) & (df["g_tr_above_ema200"] == 1) & (df["g_tr_above_ema800"] == 1)

def stack_S6_dev_filter(df):
    return (df["g_rf_with"] == 1) & (df["g_within_dev"] == 1)

def stack_S7_rf_fresh(df):
    return (df["g_rf_with"] == 1) & (df["g_rf_fresh"] == 1)

def stack_S8_session(df):
    return (df["g_rf_with"] == 1) & (df["g_tr_in_active_session"] == 1)


STACKS = {
    "S1_rf_only":          stack_S1,
    "S2_rf+ema200":        stack_S2,
    "S3_rf+ema200+ribbon": stack_S3,
    "S4_rf+ema200+mfi":    stack_S4,
    "S5_rf+ema200+ema800": stack_S5,
    "S6_rf+within_dev":    stack_S6_dev_filter,
    "S7_rf+fresh":         stack_S7_rf_fresh,
    "S8_rf+active_sess":   stack_S8_session,
}


def add_tod_col(df: pd.DataFrame) -> pd.DataFrame:
    """Add hour_utc and tod_bucket columns."""
    df = df.copy()
    df["hour_utc"] = ((df["fire_us"] // 1_000_000) % 86400 // 3600).astype(int)
    bucket = pd.Series("unk", index=df.index)
    for name, hours in TOD_BUCKETS.items():
        bucket[df["hour_utc"].isin(hours)] = name
    df["tod_bucket"] = bucket
    return df


def summarize(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0, "wr": np.nan, "dpt": np.nan, "tot_pnl": 0.0,
                "n_wins": 0, "n_losses": 0}
    return {
        "n": len(df),
        "wr": float(df["won"].mean()),
        "dpt": float(df["pnl_legacy_usd"].mean()),
        "tot_pnl": float(df["pnl_legacy_usd"].sum()),
        "n_wins": int(df["won"].sum()),
        "n_losses": int(len(df) - df["won"].sum()),
    }


def main():
    baseline_rows = []
    stack_rows = []

    for asset, tf in [("BTC", "5m"), ("ETH", "5m"), ("SOL", "5m"),
                      ("BTC", "15m"), ("ETH", "15m"), ("SOL", "15m")]:
        market = f"{asset}_{tf}"
        fpath = FBASE / f"oos_fires_{asset}_{tf}_v3_fixed.parquet"
        fires = pd.read_parquet(fpath)
        fires = fires[fires.fire_us > 0]
        fires = add_tod_col(fires)
        days = (fires.fire_us.max() - fires.fire_us.min()) / 86400 / 1e6
        print(f"[{market}] n={len(fires):,} days={days:.2f}", flush=True)

        # Whole-market baseline
        base_s = summarize(fires)
        base_s.update({"market": market, "tod": "ALL", "stack": "baseline_all"})
        baseline_rows.append(base_s)

        # Per-TOD baseline
        for tod, hrs in TOD_BUCKETS.items():
            sub = fires[fires.tod_bucket == tod]
            s = summarize(sub)
            s.update({"market": market, "tod": tod, "stack": "baseline_tod"})
            baseline_rows.append(s)

        # Per-stack overall + per-TOD
        for sname, sfunc in STACKS.items():
            try:
                mask = sfunc(fires)
            except KeyError as e:
                print(f"  skip {sname}: missing col {e}", flush=True)
                continue
            sub = fires[mask]
            # Overall stack
            s = summarize(sub)
            s.update({"market": market, "tod": "ALL", "stack": sname})
            stack_rows.append(s)
            # Per-TOD
            for tod, hrs in TOD_BUCKETS.items():
                sub2 = sub[sub.tod_bucket == tod]
                s = summarize(sub2)
                s.update({"market": market, "tod": tod, "stack": sname})
                stack_rows.append(s)

    base_df = pd.DataFrame(baseline_rows)
    stack_df = pd.DataFrame(stack_rows)

    # Compute TOD lift vs ALL-baseline for each stack
    # For each (market, stack): get wr_ALL; for each tod bucket find wr lift vs ALL stack version
    stack_df["dpt"] = stack_df["dpt"].astype(float)
    stack_df["wr"] = stack_df["wr"].astype(float)
    # Per (market, stack) — extract ALL row
    all_rows = stack_df[stack_df.tod == "ALL"][["market", "stack", "wr", "dpt", "n"]].rename(
        columns={"wr": "wr_all", "dpt": "dpt_all", "n": "n_all"})
    sd = stack_df.merge(all_rows, on=["market", "stack"], how="left")
    sd["wr_lift_pp"] = (sd["wr"] - sd["wr_all"]) * 100
    sd["dpt_lift"]   = (sd["dpt"] - sd["dpt_all"])
    sd["tod_share"]  = sd["n"] / sd["n_all"]

    # Same for baseline: wr lift of each TOD vs market ALL
    bd = base_df[base_df.tod == "ALL"][["market", "wr", "dpt", "n"]].rename(
        columns={"wr": "wr_all", "dpt": "dpt_all", "n": "n_all"})
    base_df2 = base_df.merge(bd, on="market", how="left")
    base_df2["wr_lift_pp"] = (base_df2["wr"] - base_df2["wr_all"]) * 100
    base_df2["dpt_lift"]   = (base_df2["dpt"] - base_df2["dpt_all"])
    base_df2["tod_share"]  = base_df2["n"] / base_df2["n_all"]

    base_df2.to_csv(OUT_DIR / "topic2_tod_baseline.csv", index=False)
    sd.to_csv(OUT_DIR / "topic2_tod_stacks.csv", index=False)

    # ---- Concentration analysis: stacks where 1 TOD has >2x dpt vs ALL stack version ----
    print("\n=== Per-market TOD baseline (no gating) ===")
    pd.set_option("display.max_rows", 200)
    pd.set_option("display.width", 220)
    print(base_df2[base_df2.tod != "ALL"][["market", "tod", "n", "wr", "dpt", "wr_lift_pp", "dpt_lift"]].to_string(index=False))

    print("\n=== Stack concentration — TOD-specialized opportunities ===")
    # Filter: tod != ALL, n >= 50, wr_lift_pp > 1.0 OR (dpt > 0 and dpt_lift > 1.0)
    cand = sd[(sd.tod != "ALL") & (sd.n >= 50) &
              ((sd.wr_lift_pp > 1.0) | (sd.dpt_lift > 1.0))].sort_values(
        ["market", "stack", "wr_lift_pp"], ascending=[True, True, False])
    print(cand[["market", "stack", "tod", "n", "wr", "dpt", "wr_lift_pp", "dpt_lift", "tod_share"]].to_string(index=False))
    print(f"\nWrote: {OUT_DIR/'topic2_tod_baseline.csv'}, {OUT_DIR/'topic2_tod_stacks.csv'}", flush=True)


if __name__ == "__main__":
    main()
