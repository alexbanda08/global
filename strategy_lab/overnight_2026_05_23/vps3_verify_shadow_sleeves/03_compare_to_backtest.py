"""03_compare_to_backtest.py — runs locally AFTER VPS3 trading_events refresh.

For each of the 9 new shadow sleeves, compares:
  - observed live: fire count, WR, sum_pnl, per_trade (from trading_events_30d.parquet)
  - backtest expectation: same metrics from the panels
  - divergence flags

Run AFTER:
  bash migration_2026_05_2x/pull_delta_vps3_<TAG>.sh   # refreshes trading_events_30d.parquet
  py strategy_lab/overnight_2026_05_23/vps3_verify_shadow_sleeves/03_compare_to_backtest.py
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
EVENTS = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"
OUT = ROOT / "data" / "v4" / "canonical" / "_results" / "shadow_sleeves_vs_backtest.csv"

EXPECTED = {
    # sleeve_id : (fires_per_day, WR_pct, per_trade_$, sum_per_day_$)
    "shadow_poly_updown_ALL_5m_phase1_kelly":      (167, 84.4, 5.50, 927.0),
    "shadow_poly_updown_btc_5m_fade_momo_v2":      (35,  51.9, 0.86,  22.0),
    "shadow_poly_updown_btc_5m_fade_sniper":       (30,  53.0, 0.80,  18.0),
    "shadow_poly_updown_eth_15m_fade_sniper":      (15,  52.6, 1.02,  12.0),
    "shadow_poly_updown_sol_5m_fade_sniper":       (17,  50.8, 0.45,   6.0),
    "shadow_poly_updown_sol_5m_fade_momo_v2":      (17,  50.1, 0.55,   7.0),
    "shadow_poly_updown_sol_15m_fade_momo_v2":     ( 4,  52.4, 1.88,   6.0),
    "shadow_poly_updown_ALL_5m_S3_prewindow":      (95,  52.8, 0.83,  78.0),
    "shadow_poly_updown_ALL_15m_S4_prewindow":     (11,  54.6, 2.26,  25.0),
}


def parse_data(s):
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return {}
    try:
        return json.loads(s) if isinstance(s, str) else s
    except Exception:
        return {}


def main():
    if not EVENTS.exists():
        print(f"FATAL: {EVENTS} not found. Run the delta-pull script first.")
        return
    print(f"[load] {EVENTS}")
    d = pd.read_parquet(EVENTS)
    d["at_ts"] = pd.to_datetime(d["at"], utc=True, format="mixed")
    latest = d["at_ts"].max()
    today = pd.Timestamp.utcnow().tz_convert("UTC")
    staleness_days = (today - latest).days
    print(f"  rows {len(d):,}, latest event {latest}, staleness {staleness_days} days")
    if staleness_days >= 1:
        print(f"  ⚠  data is {staleness_days} days behind — re-run pull script before trusting "
              f"this comparison.")

    # Find shadow fires
    shadow_pref = d[d["sleeve_id"].astype(str).str.startswith("shadow_", na=False)].copy()
    if shadow_pref.empty:
        print()
        print("  ⚠  NO shadow_* sleeve_ids found in trading.events.")
        print("     Either:")
        print("       a) the 9 sleeves were never registered on VPS3,")
        print("       b) the pull is too stale to include them, or")
        print("       c) they were registered under a different naming convention.")
        print("     Run 02_grep_source_check.sh on VPS3 to disambiguate.")
        return

    print(f"  found {len(shadow_pref):,} events under shadow_* prefix")
    # Parse JSON data column for each row to extract fire/resolution fields
    shadow_pref["_d"] = shadow_pref["data"].apply(parse_data)

    fires = shadow_pref[shadow_pref["kind"].str.contains("signal", na=False)].copy()
    resols = shadow_pref[shadow_pref["kind"] == "poly_updown_resolution"].copy()

    # Per-sleeve scorecard
    rows = []
    days_covered = max(1.0, (latest - shadow_pref["at_ts"].min()).total_seconds() / 86400.0)
    for sid, (exp_fpd, exp_wr, exp_pt, exp_spd) in EXPECTED.items():
        ssub = fires[fires["sleeve_id"] == sid]
        n = len(ssub)
        live_fpd = n / days_covered if days_covered > 0 else 0
        # match to resolutions
        slugs_fired = ssub["_d"].apply(lambda x: x.get("slug")).dropna().unique()
        r_match = resols[resols["sleeve_id"] == sid]
        # extract won/pnl from resolution `_d`
        if not r_match.empty:
            r_match = r_match.copy()
            r_match["pnl"] = r_match["_d"].apply(lambda x: float(x.get("pnl_usd", 0))
                                                  if isinstance(x.get("pnl_usd"), (int, float, str))
                                                  and str(x.get("pnl_usd")) not in ("nan", "") else 0.0)
            r_match["won"] = r_match["_d"].apply(lambda x: bool(x.get("won", False)))
            sum_pnl = float(r_match["pnl"].sum())
            wr_live = float(r_match["won"].mean()) * 100 if len(r_match) > 0 else 0
            per_tr = sum_pnl / len(r_match) if len(r_match) > 0 else 0
        else:
            sum_pnl = 0; wr_live = 0; per_tr = 0
        spd_live = sum_pnl / days_covered if days_covered > 0 else 0
        rows.append({
            "sleeve": sid,
            "days_covered": round(days_covered, 1),
            "fires_obs": n,
            "fires_per_day_obs": round(live_fpd, 1),
            "fires_per_day_exp": exp_fpd,
            "fires_dev_pct": round((live_fpd/exp_fpd - 1) * 100, 1) if exp_fpd > 0 else None,
            "wr_pct_obs": round(wr_live, 2),
            "wr_pct_exp": exp_wr,
            "wr_dev_pp": round(wr_live - exp_wr, 2),
            "per_tr_obs": round(per_tr, 3),
            "per_tr_exp": exp_pt,
            "sum_per_day_obs": round(spd_live, 2),
            "sum_per_day_exp": exp_spd,
            "verdict": (
                "MISSING"      if n == 0 else
                "LOW_FIRES"    if live_fpd < 0.5 * exp_fpd else
                "HIGH_FIRES"   if live_fpd > 2.0 * exp_fpd else
                "WR_LOW"       if wr_live < exp_wr - 8 else
                "WR_HIGH"      if wr_live > exp_wr + 8 else
                "PNL_LOW"      if spd_live < 0.5 * exp_spd else
                "OK"
            ),
        })
    out = pd.DataFrame(rows).sort_values("sleeve")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    pd.set_option("display.max_columns", None); pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 50)
    print()
    print(out.to_string(index=False))
    print()
    print(f"[write] {OUT}")
    # Highlight verdicts
    missing = out[out["verdict"] == "MISSING"]
    if not missing.empty:
        print()
        print(f"⚠  {len(missing)} sleeve(s) MISSING (zero events):")
        for s in missing["sleeve"]: print(f"   - {s}")
    not_ok = out[out["verdict"] != "OK"]
    if not_ok.empty:
        print()
        print("✓ all sleeves within expected ranges")


if __name__ == "__main__":
    main()
