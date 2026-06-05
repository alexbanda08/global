"""
BACKTEST-REPLAY vs LIVE — SOL sleeves
Replays every sleeve_fire_resolved from live_fires_SOL.csv through
canonical L25 books at the exact fire_us using LegacyConfig (2%-on-profit).

Usage: C:/Python314/python.exe strategy_lab/replay_sol_backtest.py
Outputs: strategy_lab/reports/BACKTEST_REPLAY_SOL_2026_05_29.md
         strategy_lab/reports/replay_sol.csv
"""

import sys, os
import pandas as pd
import numpy as np
from collections import defaultdict

REPO = "C:/Users/alexandre bandarra/Desktop/global"
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "data/v4/canonical"))

from load import load_orderbook_l25_streaming, load_resolutions
from strategy_lab.engine_v2 import LegacyConfig, fill_at_book, hold_pnl

# ── Constants ────────────────────────────────────────────────────────────────
CANONICAL_MAX_L25_US = 1780060460001000   # 2026-05-29 13:14:20 UTC
CANONICAL_MAX_RES_US = 1780060200000000   # 2026-05-29 13:10:00 UTC
CFG = LegacyConfig()
# override notional to match per-fire placed_size_usd (live uses 5 USD not 25)
# We pass notional_usd per call instead

INPUT_CSV  = os.path.join(REPO, "strategy_lab/live_fires_SOL.csv")
OUT_DIR    = os.path.join(REPO, "strategy_lab/reports")
OUT_MD     = os.path.join(OUT_DIR, "BACKTEST_REPLAY_SOL_2026_05_29.md")
OUT_CSV    = os.path.join(OUT_DIR, "replay_sol.csv")

# ── Load live fires ───────────────────────────────────────────────────────────
print("[1/6] Loading live_fires_SOL.csv ...")
df_all = pd.read_csv(INPUT_CSV)
fires  = df_all[df_all["event_type"] == "sleeve_fire_resolved"].copy()
fires  = fires.reset_index(drop=True)
print(f"  resolved fires: {len(fires)}")

# Derive 'won' for rows where it is NaN (early rows; use pnl sign as proxy)
fires["won_clean"] = fires["won"].map({"True": True, "False": False, True: True, False: False})
mask_nan_won = fires["won_clean"].isna()
fires.loc[mask_nan_won, "won_clean"] = fires.loc[mask_nan_won, "pnl_usd"] > 0
fires["won_clean"] = fires["won_clean"].astype(bool)

# Partition: within canonical vs no_data
fires["in_canonical"] = fires["fire_us"] <= CANONICAL_MAX_L25_US
fires_within = fires[fires["in_canonical"]].copy()
fires_nodata = fires[~fires["in_canonical"]].copy()
print(f"  within canonical: {len(fires_within)}  no_data: {len(fires_nodata)}")

# ── Load L25 books for all SOL slugs in canonical window ─────────────────────
print("[2/6] Loading canonical L25 books (subsample_1hz=False) ...")
sol_slugs = set(fires_within["slug"].unique())
print(f"  unique slugs to load: {len(sol_slugs)}")
books = load_orderbook_l25_streaming(
    "sol",
    slugs=sol_slugs,
    subsample_1hz=False,
    max_ts_us=CANONICAL_MAX_L25_US,
)
print(f"  book keys loaded: {len(books)}")

# ── Load resolutions for outcome truth ───────────────────────────────────────
print("[3/6] Loading canonical resolutions ...")
res = load_resolutions()
sol_res = res[res["ticker"] == "SOL"].set_index("slug")
print(f"  SOL resolutions: {len(sol_res)}")

# ── Per-fire replay ───────────────────────────────────────────────────────────
print("[4/6] Replaying fires ...")

rows = []
for _, fire in fires_within.iterrows():
    slug       = fire["slug"]
    direction  = fire["direction"]          # "UP" or "DOWN"
    fire_us    = int(fire["fire_us"])
    live_vwap  = float(fire["fill_vwap"])
    live_shares= float(fire["fill_shares"])
    placed_usd = float(fire["placed_size_usd"])
    live_pnl   = float(fire["pnl_usd"])
    live_won   = bool(fire["won_clean"])
    sleeve     = fire["sleeve_id"]
    live_outcome = str(fire["outcome"])

    # Canonical outcome from resolutions
    canon_outcome = None
    if slug in sol_res.index:
        canon_outcome = str(sol_res.loc[slug, "outcome"])

    # outcome = direction token passed to fill_at_book
    direction_cap = direction.capitalize()  # "Up" or "Down"

    # backtest fill
    bt_fill = fill_at_book(
        books,
        slug,
        direction_cap,
        fire_us,
        cfg=CFG,
        notional_usd=placed_usd,
    )

    row = {
        "sleeve_id":      sleeve,
        "slug":           slug,
        "fire_us":        fire_us,
        "direction":      direction,
        "live_vwap":      live_vwap,
        "live_shares":    live_shares,
        "placed_usd":     placed_usd,
        "live_won":       live_won,
        "live_pnl":       live_pnl,
        "live_outcome":   live_outcome,
        "canon_outcome":  canon_outcome,
        "bt_vwap":        None,
        "bt_shares":      None,
        "bt_pnl":         None,
        "outcome_match":  None,
        "fill_status":    "ok",
        "delta_vwap":     None,
    }

    if bt_fill is None:
        row["fill_status"] = "no_fill"
        rows.append(row)
        continue

    bt_vwap   = bt_fill["vwap"]
    bt_shares = bt_fill["shares"]

    # outcome for PnL: use canonical if available, else live
    bt_won = live_won  # default to live outcome
    outcome_match = None
    if canon_outcome is not None:
        # canonical outcome is "Up" / "Down"
        # live_outcome in CSV is "Up" / "Down" (same)
        outcome_match = (canon_outcome == live_outcome)
        bt_won = (canon_outcome == direction_cap)

    bt_pnl = hold_pnl(bt_fill, won=bt_won, cfg=CFG)

    row.update({
        "bt_vwap":       bt_vwap,
        "bt_shares":     bt_shares,
        "bt_pnl":        bt_pnl,
        "outcome_match": outcome_match,
        "delta_vwap":    bt_vwap - live_vwap,
    })
    rows.append(row)

detail_df = pd.DataFrame(rows)
print(f"  rows processed: {len(detail_df)}")

# ── Per-sleeve aggregation ────────────────────────────────────────────────────
print("[5/6] Aggregating per sleeve ...")

# Add no_data rows (placeholder)
nodata_rows = []
for _, fire in fires_nodata.iterrows():
    nodata_rows.append({
        "sleeve_id":     fire["sleeve_id"],
        "slug":          fire["slug"],
        "fire_us":       int(fire["fire_us"]),
        "direction":     fire["direction"],
        "live_vwap":     float(fire["fill_vwap"]),
        "live_shares":   float(fire["fill_shares"]),
        "placed_usd":    float(fire["placed_size_usd"]),
        "live_won":      bool(fire["won_clean"]) if not pd.isna(fire["won_clean"]) else None,
        "live_pnl":      float(fire["pnl_usd"]),
        "live_outcome":  str(fire["outcome"]),
        "canon_outcome": None,
        "bt_vwap":       None,
        "bt_shares":     None,
        "bt_pnl":        None,
        "outcome_match": None,
        "fill_status":   "no_data",
        "delta_vwap":    None,
    })

all_rows_df = pd.concat([detail_df, pd.DataFrame(nodata_rows)], ignore_index=True) if nodata_rows else detail_df
# Save detail CSV
all_rows_df.to_csv(OUT_CSV, index=False)
print(f"  detail CSV saved: {OUT_CSV}")

# Build sleeve-level summary
sleeve_agg = []
all_sleeves = sorted(fires["sleeve_id"].unique())

for sleeve in all_sleeves:
    sl_all   = fires[fires["sleeve_id"] == sleeve]
    sl_within = detail_df[detail_df["sleeve_id"] == sleeve]
    sl_nodata = fires_nodata[fires_nodata["sleeve_id"] == sleeve]

    n_resolved   = len(sl_all)
    n_no_data    = len(sl_nodata)
    n_compared   = len(sl_within)

    # live metrics (all resolved)
    live_won_arr = sl_all["won_clean"]
    live_wr      = live_won_arr.mean() if len(live_won_arr) > 0 else float("nan")
    live_pnl_tot = sl_all["pnl_usd"].sum()
    live_pnl_tr  = sl_all["pnl_usd"].mean()

    # bt metrics (within-canonical only, has fill)
    sl_filled    = sl_within[sl_within["fill_status"] == "ok"]
    n_bt_filled  = len(sl_filled)

    if n_bt_filled > 0:
        bt_wr      = sl_filled["bt_pnl"].apply(lambda x: x > 0).mean()
        bt_pnl_tot = sl_filled["bt_pnl"].sum()
        bt_pnl_tr  = sl_filled["bt_pnl"].mean()
        mean_dvwap = sl_filled["delta_vwap"].abs().mean()
        outcome_match_pct = (sl_filled["outcome_match"].sum() / sl_filled["outcome_match"].notna().sum() * 100
                             if sl_filled["outcome_match"].notna().sum() > 0 else float("nan"))
    else:
        bt_wr = bt_pnl_tot = bt_pnl_tr = mean_dvwap = outcome_match_pct = float("nan")

    n_nofill = len(sl_within[sl_within["fill_status"] == "no_fill"])

    # Flags
    flags = []
    if n_resolved < 20:
        flags.append("LOW_N")
    if not np.isnan(mean_dvwap) and mean_dvwap > 0.02:
        flags.append("FILL_DIVERGE")
    if not np.isnan(outcome_match_pct) and outcome_match_pct < 98.0:
        flags.append("OUTCOME_MISMATCH")
    if not np.isnan(bt_pnl_tr) and not np.isnan(live_pnl_tr) and abs(bt_pnl_tr - live_pnl_tr) > 0.50:
        flags.append("PNL_DIVERGE")

    sleeve_agg.append({
        "sleeve_id":         sleeve,
        "n_resolved":        n_resolved,
        "n_compared":        n_compared,
        "n_no_data":         n_no_data,
        "n_no_fill":         n_nofill,
        "live_WR":           round(live_wr * 100, 1),
        "bt_WR":             round(bt_wr * 100, 1) if not np.isnan(bt_wr) else float("nan"),
        "live_$/tr":         round(live_pnl_tr, 3),
        "bt_$/tr":           round(bt_pnl_tr, 3) if not np.isnan(bt_pnl_tr) else float("nan"),
        "mean_dvwap":         round(mean_dvwap, 4) if not np.isnan(mean_dvwap) else float("nan"),
        "outcome_match%":    round(outcome_match_pct, 1) if not np.isnan(outcome_match_pct) else float("nan"),
        "live_totPnL":       round(live_pnl_tot, 2),
        "bt_totPnL":         round(bt_pnl_tot, 2) if not np.isnan(bt_pnl_tot) else float("nan"),
        "flags":             "|".join(flags) if flags else "",
    })

agg_df = pd.DataFrame(sleeve_agg)

# ── Build Markdown report ─────────────────────────────────────────────────────
print("[6/6] Writing report ...")

def fmt(v, decimals=3):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{decimals}f}"

total_n_resolved = len(fires)
total_within     = len(fires_within)
total_nodata     = len(fires_nodata)
total_nofill     = len(detail_df[detail_df["fill_status"] == "no_fill"])
total_compared   = len(detail_df[detail_df["fill_status"] == "ok"])
live_tot_pnl     = fires["pnl_usd"].sum()
bt_tot_pnl_filled= detail_df[detail_df["fill_status"]=="ok"]["bt_pnl"].sum()
global_live_wr   = fires["won_clean"].mean() * 100
bt_ok = detail_df[detail_df["fill_status"]=="ok"]
global_bt_wr     = (bt_ok["bt_pnl"] > 0).mean() * 100 if len(bt_ok) > 0 else float("nan")
mean_abs_dvwap   = bt_ok["delta_vwap"].abs().mean() if len(bt_ok) > 0 else float("nan")

# table header
col_headers = ["sleeve_id","n_res","n_cmp","n_nodata","live_WR","bt_WR",
               "live_$/tr","bt_$/tr","mean_dvwap","out_match%","live_$tot","bt_$tot","flags"]
col_widths  = [55, 6, 6, 8, 8, 6, 9, 9, 11, 11, 10, 9, 30]

def row_fmt(vals):
    parts = []
    for v, w in zip(vals, col_widths):
        parts.append(str(v)[:w].ljust(w))
    return "| " + " | ".join(parts) + " |"

hdr  = row_fmt(col_headers)
sep  = "| " + " | ".join(["-"*w for w in col_widths]) + " |"

table_rows = []
for _, r in agg_df.iterrows():
    vals = [
        r["sleeve_id"],
        int(r["n_resolved"]),
        int(r["n_compared"]),
        int(r["n_no_data"]),
        fmt(r["live_WR"], 1) + "%",
        fmt(r["bt_WR"], 1) + "%" if not np.isnan(r["bt_WR"]) else "—",
        fmt(r["live_$/tr"]),
        fmt(r["bt_$/tr"]) if not np.isnan(r["bt_$/tr"]) else "—",
        fmt(r["mean_dvwap"], 4) if not np.isnan(r["mean_dvwap"]) else "—",
        fmt(r["outcome_match%"], 1) + "%" if not np.isnan(r["outcome_match%"]) else "—",
        fmt(r["live_totPnL"]),
        fmt(r["bt_totPnL"]) if not np.isnan(r["bt_totPnL"]) else "—",
        r["flags"],
    ]
    table_rows.append(row_fmt(vals))

md_lines = [
    "# BACKTEST-REPLAY vs LIVE — SOL Sleeves",
    "",
    f"**Generated:** 2026-05-29  |  **Source:** `strategy_lab/live_fires_SOL.csv`",
    "",
    "## Summary",
    "",
    f"| Metric | Value |",
    f"|--------|-------|",
    f"| Total resolved fires | {total_n_resolved} |",
    f"| Within canonical window (fire_us ≤ L25 max) | {total_within} |",
    f"| NO_DATA (fire_us > 2026-05-29 13:14 UTC) | {total_nodata} |",
    f"| bt fill OK | {total_compared} |",
    f"| bt no_fill (book absent/stale) | {total_nofill} |",
    f"| Canonical L25 max ts | 2026-05-29 13:14:20 UTC |",
    f"| Canonical resolutions max | 2026-05-29 13:10:00 UTC |",
    "",
    f"| Global metric | Live | Backtest |",
    f"|---------------|------|----------|",
    f"| Win rate | {global_live_wr:.1f}% | {global_bt_wr:.1f}% |",
    f"| Total PnL (filled subset) | ${live_tot_pnl:.2f} (all) / ${fires[fires['in_canonical']]['pnl_usd'].sum():.2f} (canonical) | ${bt_tot_pnl_filled:.2f} |",
    f"| Mean |Δfill_vwap| | — | {mean_abs_dvwap:.4f} |",
    "",
    "## Notes on fee model",
    "",
    "Backtest uses `LegacyConfig` (2%-on-profit-only, no entry fee, 0ms latency).",
    "This matches production fee model verified 2026-05-22.",
    "Live fires have `placed_size_usd` which replaces the default 25 USD notional per fill.",
    "",
    "## Per-sleeve fidelity table",
    "",
    "**Flags:** `FILL_DIVERGE` (mean_dvwap>0.02), `OUTCOME_MISMATCH` (<98%), `PNL_DIVERGE` (|delta_$/tr|>0.50), `LOW_N` (<20).",
    "",
    hdr,
    sep,
]
for tr in table_rows:
    md_lines.append(tr)

# Special sleeve deep-dives
vwap80_sleeves = [s for s in all_sleeves if "vwap80" in s or "vwap30_70" in s]
partial_mid    = [s for s in all_sleeves if "partial_mid" in s]
v9_sleeves     = [s for s in all_sleeves if "_v9" in s]

md_lines += [
    "",
    "## Special sleeve deep-dives",
    "",
    "### 15m vwap80 gate-bug sleeves (KNOWN: live vwap≥0.55 floor vs spec vwap<0.80 ceiling)",
    "",
]
for s in vwap80_sleeves:
    r = agg_df[agg_df["sleeve_id"]==s]
    if len(r):
        r = r.iloc[0]
        md_lines.append(f"- **{s}**: n={int(r['n_resolved'])}, live_WR={r['live_WR']:.1f}%, "
                        f"live_tot=${r['live_totPnL']:.2f}, no_data={int(r['n_no_data'])}")

md_lines += [
    "",
    "### sol_5m_rf_tr_partial_mid (biggest SOL winner, live +$84)",
    "",
]
for s in partial_mid:
    r = agg_df[agg_df["sleeve_id"]==s]
    if len(r):
        r = r.iloc[0]
        dvwap_val = r["mean_dvwap"]
        bt_wr_str  = "—" if np.isnan(r["bt_WR"]) else f"{r['bt_WR']:.1f}%"
        bt_tot_str = "—" if np.isnan(r["bt_totPnL"]) else f"${r['bt_totPnL']:.2f}"
        dv_str     = "—" if np.isnan(dvwap_val) else f"{dvwap_val:.4f}"
        md_lines.append(
            f"- **{s}**: n_res={int(r['n_resolved'])}, n_cmp={int(r['n_compared'])}, "
            f"n_no_data={int(r['n_no_data'])}, live_WR={r['live_WR']:.1f}%, "
            f"bt_WR={bt_wr_str}, live_tot=${r['live_totPnL']:.2f}, "
            f"bt_tot={bt_tot_str}, mean_dvwap={dv_str}, flags={r['flags']}"
        )

md_lines += [
    "",
    "### V9 SOL sleeves (b1/b3, many silent)",
    "",
]
for s in v9_sleeves:
    r = agg_df[agg_df["sleeve_id"]==s]
    if len(r):
        r = r.iloc[0]
        md_lines.append(f"- **{s}**: n_res={int(r['n_resolved'])}, no_data={int(r['n_no_data'])}, "
                        f"live_tot=${r['live_totPnL']:.2f}, flags={r['flags']}")

md_lines += [
    "",
    "## Detail CSV",
    "",
    f"Per-fire detail: `strategy_lab/reports/replay_sol.csv` ({len(all_rows_df)} rows)",
    "Columns: sleeve_id, slug, fire_us, direction, live_vwap, live_shares, placed_usd,",
    "live_won, live_pnl, live_outcome, canon_outcome, bt_vwap, bt_shares, bt_pnl,",
    "outcome_match, fill_status, delta_vwap",
    "",
]

with open(OUT_MD, "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print(f"  report saved: {OUT_MD}")
print("\nDone.")

# Print quick summary to stdout
print("\n=== QUICK SUMMARY ===")
print(agg_df[["sleeve_id","n_resolved","n_compared","n_no_data","live_WR",
              "bt_WR","live_$/tr","bt_$/tr","mean_dvwap","live_totPnL","bt_totPnL","flags"]].to_string(index=False))
