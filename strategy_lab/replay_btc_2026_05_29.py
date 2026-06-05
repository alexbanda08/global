"""
Backtest-replay vs live — BTC sleeves.
Compares canonical L25 replay fill+PnL to what live shadow mode logged.
Output: strategy_lab/reports/BACKTEST_REPLAY_BTC_2026_05_29.md + replay_btc.csv
"""
from __future__ import annotations
import sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

import pandas as pd
import numpy as np
import pyarrow.parquet as pq

from load import load_orderbook_l25_streaming, load_resolutions
from book_walk import book_walk_fill

# ── constants ────────────────────────────────────────────────────────────────
NOTIONAL = 5.0           # all live fires used $5
LEGACY_FEE = 0.02        # 2% on profit only (verified vs production)
MAX_STALENESS_US = 60_000_000  # 60 s

# ── load fires ───────────────────────────────────────────────────────────────
fires_path = ROOT / "strategy_lab" / "live_fires_BTC.csv"
fires = pd.read_csv(fires_path)
placed  = fires[fires.event_type == "sleeve_fire_placed"].copy()
resolved = fires[fires.event_type == "sleeve_fire_resolved"].copy()

# Match resolved rows to their placed fire_us (earliest placed with same fill)
placed_key = placed[["sleeve_id","slug","direction","fill_vwap","fill_shares","fire_us"]].copy()
placed_key = placed_key.sort_values("fire_us")
placed_key = placed_key.drop_duplicates(
    ["sleeve_id","slug","direction","fill_vwap","fill_shares"], keep="first"
)
df = resolved.merge(
    placed_key.rename(columns={"fire_us": "placed_fire_us"}),
    on=["sleeve_id","slug","direction","fill_vwap","fill_shares"],
    how="left"
)
assert df.placed_fire_us.isna().sum() == 0, "unmatched placed rows"

# ── L25 max timestamp ────────────────────────────────────────────────────────
l25_path = ROOT / "data" / "v4" / "canonical" / "orderbook_l25" / "btc.parquet"
pf = pq.ParquetFile(str(l25_path))
ng = pf.metadata.num_row_groups
l25_max_us = int(pf.read_row_group(ng - 1, columns=["timestamp_us"]).to_pandas().timestamp_us.max())
print(f"L25 max_us: {l25_max_us} ({pd.Timestamp(l25_max_us, unit='us', tz='UTC')})")

# ── partition into in-range / no-data ────────────────────────────────────────
df["_in_range"] = df.placed_fire_us <= l25_max_us
in_range_df = df[df["_in_range"]].copy()
no_data_df  = df[~df["_in_range"]].copy()
print(f"Total resolved: {len(df)} | in_range: {len(in_range_df)} | no_data: {len(no_data_df)}")

# ── canonical resolutions for outcome truth ───────────────────────────────────
res = load_resolutions()
res_map = dict(zip(res.slug, res.outcome))   # slug → canonical outcome

# ── load L25 — only slugs in-range ──────────────────────────────────────────
slugs_needed = set(in_range_df.slug.unique())
print(f"Loading L25 for {len(slugs_needed)} slugs (native 10 Hz) ...")
# Bound time window to fire range + staleness buffer
t_min = int(in_range_df.placed_fire_us.min()) - MAX_STALENESS_US
t_max = int(in_range_df.placed_fire_us.max()) + 1_000_000  # 1s buffer
books = load_orderbook_l25_streaming(
    "btc",
    slugs=slugs_needed,
    subsample_1hz=False,  # MANDATORY
    min_ts_us=t_min,
    max_ts_us=t_max,
)
print(f"Loaded {len(books)} (slug, outcome) book series")

# ── strict-asof book lookup ───────────────────────────────────────────────────
def find_book(books: dict, slug: str, outcome: str, target_us: int):
    rec = books.get((slug, outcome))
    if rec is None:
        return None
    ts, ap, asz, bp, bsz = rec
    if len(ts) == 0:
        return None
    pos = int(np.searchsorted(ts, int(target_us), side="right"))
    if pos == 0:
        return None
    i = pos - 1
    dt = int(target_us) - int(ts[i])
    if dt > MAX_STALENESS_US:
        return None
    return {"ap": ap[i], "asz": asz[i], "bp": bp[i], "bsz": bsz[i], "dt_us": dt}


# ── legacy PnL (matching production 2%-on-profit-only) ───────────────────────
def legacy_pnl(vwap: float, shares: float, won: bool) -> float:
    usd_in = vwap * shares
    if won:
        gross = shares - usd_in
        return gross * (1 - LEGACY_FEE) if gross > 0 else gross
    return -usd_in


# ── per-row replay ────────────────────────────────────────────────────────────
rows = []
for _, r in in_range_df.iterrows():
    slug = r["slug"]
    direction = r["direction"]       # "UP" or "DOWN"
    fire_us = int(r["placed_fire_us"])
    live_vwap = float(r["fill_vwap"])
    live_shares = float(r["fill_shares"])
    live_pnl = float(r["pnl_usd"]) if pd.notna(r["pnl_usd"]) else None
    live_outcome = r["outcome"] if pd.notna(r["outcome"]) else None
    live_won_raw = r["won"]
    exit_type = r["exit_type"] if pd.notna(r["exit_type"]) else "hold_to_resolve"

    # Buy side token = direction
    buy_side = direction.capitalize()   # "Up" or "Down"

    # Canonical outcome
    canon_outcome = res_map.get(slug)

    # L25 book lookup
    book = find_book(books, slug, buy_side, fire_us)
    if book is None:
        bt_vwap = bt_shares = bt_pnl = None
        fill_status = "NO_BOOK"
    else:
        ap = book["ap"]
        asz = book["asz"]
        bt_vwap, bt_shares, bt_usd, hit_levels, underfilled = book_walk_fill(
            ap, asz, NOTIONAL
        )
        if bt_shares <= 0 or underfilled:
            bt_vwap = bt_shares = bt_pnl = None
            fill_status = "UNDERFILLED"
        else:
            fill_status = "OK"
            # PnL using canonical outcome + legacy fee model
            if canon_outcome is not None:
                bt_won = (canon_outcome == buy_side)
                bt_pnl = legacy_pnl(bt_vwap, bt_shares, bt_won)
            else:
                bt_pnl = None

    # Live won flag
    if pd.notna(live_won_raw):
        live_won = bool(live_won_raw)
    elif live_outcome is not None:
        live_won = (live_outcome == buy_side)
    else:
        live_won = None

    # Live pnl (re-derive if NaN using legacy fee for consistency)
    if live_pnl is None and live_won is not None:
        live_pnl = legacy_pnl(live_vwap, live_shares, live_won)

    rows.append({
        "sleeve_id": r["sleeve_id"],
        "slug": slug,
        "direction": direction,
        "placed_fire_us": fire_us,
        "live_vwap": live_vwap,
        "live_shares": live_shares,
        "live_outcome": live_outcome,
        "live_won": live_won,
        "live_pnl": live_pnl,
        "canon_outcome": canon_outcome,
        "bt_vwap": bt_vwap,
        "bt_shares": bt_shares,
        "bt_pnl": bt_pnl,
        "fill_status": fill_status,
        "book_dt_us": book["dt_us"] if book else None,
    })

replay_df = pd.DataFrame(rows)
print(f"Replay rows: {len(replay_df)}")
print("fill_status:", replay_df.fill_status.value_counts().to_dict())

# ── per-sleeve aggregation ────────────────────────────────────────────────────
sleeve_rows = []
sleeves = sorted(df.sleeve_id.unique())

for sl in sleeves:
    # All resolved
    sl_all = df[df.sleeve_id == sl]
    n_resolved = len(sl_all)
    n_no_data = len(sl_all[~sl_all["_in_range"]])

    # Replay rows
    sl_rp = replay_df[replay_df.sleeve_id == sl].copy()
    n_compared = len(sl_rp[sl_rp.fill_status == "OK"])

    if n_compared == 0:
        sleeve_rows.append({
            "sleeve_id": sl,
            "n_resolved_live": n_resolved,
            "n_compared": n_compared,
            "n_no_data": n_no_data,
            "live_WR": None,
            "bt_WR": None,
            "live_dtr": None,
            "bt_dtr": None,
            "mean_abs_fill_delta": None,
            "outcome_match_pct": None,
            "live_totPnL": sl_all.pnl_usd.sum() if sl_all.pnl_usd.notna().any() else None,
            "bt_totPnL": None,
            "flags": "LOW_N",
        })
        continue

    ok = sl_rp[sl_rp.fill_status == "OK"].copy()

    # Live metrics (on rows with canonical fill)
    live_wins = ok.live_won.sum() if ok.live_won.notna().any() else 0
    live_total = ok.live_won.notna().sum()
    live_wr = live_wins / live_total if live_total > 0 else None

    # BT metrics (canon outcome)
    ok_canon = ok[ok.canon_outcome.notna()].copy()
    bt_wins = 0
    bt_total = 0
    for _, row in ok_canon.iterrows():
        buy_side = row["direction"].capitalize()
        if row["canon_outcome"] == buy_side:
            bt_wins += 1
        bt_total += 1
    bt_wr = bt_wins / bt_total if bt_total > 0 else None

    # Outcome match
    outcome_cmp = ok[ok.live_outcome.notna() & ok.canon_outcome.notna()].copy()
    if len(outcome_cmp):
        outcome_match_pct = (outcome_cmp.live_outcome == outcome_cmp.canon_outcome).mean() * 100
    else:
        outcome_match_pct = None

    # Fill delta
    fill_delta_abs = (ok.live_vwap - ok.bt_vwap).abs().mean()

    # PnL totals
    live_tot = ok.live_pnl.sum() if ok.live_pnl.notna().any() else None
    bt_tot = ok.bt_pnl.sum() if ok.bt_pnl.notna().any() else None
    live_dtr = live_tot / n_compared if (live_tot is not None and n_compared > 0) else None
    bt_dtr = bt_tot / n_compared if (bt_tot is not None and n_compared > 0) else None

    # Flags
    flags = []
    if n_compared < 20:
        flags.append("LOW_N")
    if fill_delta_abs > 0.02:
        flags.append("FILL_DIVERGE")
    if outcome_match_pct is not None and outcome_match_pct < 98.0:
        flags.append("OUTCOME_MISMATCH")
    if live_dtr is not None and bt_dtr is not None and abs(live_dtr - bt_dtr) > 0.50:
        flags.append("PNL_DIVERGE")

    sleeve_rows.append({
        "sleeve_id": sl,
        "n_resolved_live": n_resolved,
        "n_compared": n_compared,
        "n_no_data": n_no_data,
        "live_WR": round(live_wr * 100, 1) if live_wr is not None else None,
        "bt_WR": round(bt_wr * 100, 1) if bt_wr is not None else None,
        "live_dtr": round(live_dtr, 4) if live_dtr is not None else None,
        "bt_dtr": round(bt_dtr, 4) if bt_dtr is not None else None,
        "mean_abs_fill_delta": round(fill_delta_abs, 4),
        "outcome_match_pct": round(outcome_match_pct, 1) if outcome_match_pct is not None else None,
        "live_totPnL": round(live_tot, 2) if live_tot is not None else None,
        "bt_totPnL": round(bt_tot, 2) if bt_tot is not None else None,
        "flags": "|".join(flags) if flags else "OK",
    })

summary_df = pd.DataFrame(sleeve_rows)

# ── save CSV ─────────────────────────────────────────────────────────────────
out_dir = ROOT / "strategy_lab" / "reports"
out_dir.mkdir(exist_ok=True)
csv_path = out_dir / "replay_btc.csv"
replay_df.to_csv(csv_path, index=False)
print(f"Saved replay_btc.csv ({len(replay_df)} rows)")

# ── print summary table ───────────────────────────────────────────────────────
print("\n=== PER-SLEEVE FIDELITY TABLE ===")
pd.set_option("display.max_colwidth", 60)
pd.set_option("display.width", 200)
print(summary_df.to_string(index=False))

# Save to variable for report generation
summary_df.to_csv("/tmp/replay_summary.csv", index=False)
replay_df.to_csv("/tmp/replay_full.csv", index=False)
print("\nIntermediate results saved to /tmp/replay_summary.csv + /tmp/replay_full.csv")
