"""Monthly HoD-Top-8 refresh script.

Pulls the last N days of resolved trading.events from VPS3, recomputes the
per-cell top-8 UTC hours by sum$, compares to the currently-shipped
HOD_TOP8_BY_CELL constant, and flags cells where the set changes by ≥3
hours for operator review.

Usage:
    python strategy_lab/markov_filter/monthly_hod_refresh.py --window-days 28

Outputs (under strategy_lab/markov_filter/_results/hod_refresh/<run_date>/):
    new_hod_top8.json        — proposed new HoD set per cell
    diff_vs_current.json     — symmetric diff per cell + flag count
    refresh_report.md        — human-readable summary
    flagged_cells.json       — subset needing human review

EXIT CODES:
    0 — refresh complete, no cells flagged for review
    1 — at least one cell flagged for review (≥3 hour change)
    2 — script error (e.g. couldn't reach VPS3)

Schedule via cron on the 1st of each month at 04:00 UTC:
    0 4 1 * * cd /path/to/global && python strategy_lab/markov_filter/monthly_hod_refresh.py >> /var/log/hod_refresh.log 2>&1
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

# ----------------------------------------------------------------------------
# CURRENT shipped HOD_TOP8_BY_CELL — must match
# backend/app/strategies/polymarket/gates.py on VPS3.
# When the operator updates the shipped constant, update this dict too.
# ----------------------------------------------------------------------------
CURRENT_HOD_TOP8: dict[tuple[str, str], list[int]] = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo",    "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],   # momo = v1
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}

FLAG_THRESHOLD_HOURS = 3        # if symmetric diff >= 3 hours → flag for review
MIN_FIRES_PER_CELL  = 100      # cells with fewer than this in window → skip refresh
MIN_FIRES_PER_HOUR  = 5         # hours with fewer fires than this → ineligible


def pull_resolutions_from_vps3(window_days: int) -> pd.DataFrame:
    """Pull the last `window_days` of resolved poly_updown events from VPS3."""
    sql = f"""
SELECT
  sleeve_id,
  at,
  (data->>'won')::bool::int AS won,
  (data->>'pnl_usd')::numeric AS pnl_usd,
  data->>'signal' AS signal
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND at >= NOW() - INTERVAL '{int(window_days)} days'
  AND sleeve_id LIKE 'poly_updown_%'
  AND data->>'outcome' IN ('Up','Down')
"""
    cmd = [
        "ssh", "vps3",
        f"export PGPASSWORD=BGTVaTumsfxlYy1I961sINinHLetqqKj && "
        f"psql -h 127.0.0.1 -U postgres -d storedata "
        f"-F ',' --no-align --tuples-only -c \"COPY ({sql.strip()}) "
        f"TO STDOUT WITH (FORMAT csv, HEADER true)\""
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=180)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"VPS3 SQL fetch failed: {e.stderr}")
    from io import StringIO
    df = pd.read_csv(StringIO(out.stdout))
    return df


def classify_sleeve(sleeve_id: str) -> tuple[str, str] | None:
    """Map a sleeve_id to (strategy_key, cell_key) for HOD lookup, or None to skip."""
    base = (sleeve_id
            .replace("_HOLD", "")
            .replace("_HEDGE", "")
            .replace("_SELL", "")
            .replace("_f7", "")
            .replace("_hod_mtf", "")
            .replace("_hod_m5va", "")
            .replace("_hod", ""))
    base = base.replace("poly_updown_", "")
    # Examples: btc_15m_momo_v2, sniper_btc_15m -> just parse the tail
    if "_momo_v2_" in base or base.endswith("_momo_v2"):
        s = "momo_v2"; base = base.replace("_momo_v2", "")
    elif "_momo" in base or base.endswith("_momo"):
        s = "momo";    base = base.replace("_momo", "")
    elif "_sniper" in base:
        # exclude inverse variants
        if "_INV" in base: return None
        s = "sniper";  base = base.replace("_sniper", "")
    else:
        return None
    # Now `base` looks like "btc_15m" or "btc_5m" (after strip)
    base = base.strip("_")
    if base not in ("btc_5m","btc_15m","eth_5m","eth_15m","sol_5m","sol_15m"):
        return None
    return (s, base)


def compute_new_top8(df: pd.DataFrame) -> tuple[dict, dict]:
    """Compute per-(strategy, cell) per-hour sum$ and pick top-8 by sum_pnl."""
    df["at_ts"] = pd.to_datetime(df["at"], utc=True, format="mixed")
    df["hour"] = df["at_ts"].dt.hour
    df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
    cls = df["sleeve_id"].apply(classify_sleeve)
    df["strategy"] = cls.apply(lambda x: x[0] if x else None)
    df["cell"]     = cls.apply(lambda x: x[1] if x else None)
    df = df.dropna(subset=["strategy","cell","pnl_usd"])

    new_top8: dict = {}
    per_cell_stats: dict = {}
    for (strat, cell), g in df.groupby(["strategy", "cell"]):
        if len(g) < MIN_FIRES_PER_CELL:
            per_cell_stats[f"{strat}/{cell}"] = {
                "n": len(g), "status": "SKIP_too_few_fires", "kept_current": True
            }
            continue
        hr = g.groupby("hour").agg(n=("won","size"),
                                   wr=("won","mean"),
                                   sum_pnl=("pnl_usd","sum")).reset_index()
        hr = hr[hr["n"] >= MIN_FIRES_PER_HOUR]
        if len(hr) < 8:
            per_cell_stats[f"{strat}/{cell}"] = {
                "n": len(g), "status": "SKIP_too_few_hour_buckets", "kept_current": True
            }
            continue
        top8 = hr.sort_values("sum_pnl", ascending=False).head(8)["hour"].tolist()
        new_top8[(strat, cell)] = sorted(top8)
        per_cell_stats[f"{strat}/{cell}"] = {
            "n": len(g), "status": "OK", "top8": sorted(top8),
            "covered_fires": int(hr[hr["hour"].isin(top8)]["n"].sum()),
            "top8_sum_pnl": float(hr[hr["hour"].isin(top8)]["sum_pnl"].sum()),
        }
    return new_top8, per_cell_stats


def diff_against_current(new_top8: dict) -> tuple[dict, list]:
    """Symmetric diff per cell, return both the diff and list of flagged cells."""
    diffs = {}
    flagged = []
    for k, current in CURRENT_HOD_TOP8.items():
        new = new_top8.get(k)
        if new is None:
            diffs[f"{k[0]}/{k[1]}"] = {"status": "NO_NEW_DATA", "current": current}
            continue
        added = sorted(set(new) - set(current))
        removed = sorted(set(current) - set(new))
        change_size = len(added) + len(removed)   # symmetric diff size
        diffs[f"{k[0]}/{k[1]}"] = {
            "current": current,
            "new": new,
            "added": added,
            "removed": removed,
            "change_size": change_size,
            "flagged_for_review": change_size >= FLAG_THRESHOLD_HOURS,
        }
        if change_size >= FLAG_THRESHOLD_HOURS:
            flagged.append(f"{k[0]}/{k[1]}")
    # Also report any new cells not in CURRENT_HOD_TOP8 (would be "new sleeve")
    for k in new_top8:
        if k not in CURRENT_HOD_TOP8:
            diffs[f"{k[0]}/{k[1]}"] = {"status": "NEW_CELL_NOT_IN_CURRENT_CONFIG",
                                        "new": new_top8[k]}
    return diffs, flagged


def write_report(out_dir: Path, new_top8, per_cell_stats, diffs, flagged,
                 window_days: int, total_fires: int):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "new_hod_top8.json").write_text(json.dumps(
        {f"{k[0]}/{k[1]}": v for k, v in new_top8.items()}, indent=2))
    (out_dir / "diff_vs_current.json").write_text(json.dumps(diffs, indent=2))
    (out_dir / "flagged_cells.json").write_text(json.dumps(flagged, indent=2))

    md = []
    md.append(f"# HoD-Top-8 monthly refresh — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    md.append("")
    md.append(f"- Window: last **{window_days} days** of trading.events")
    md.append(f"- Total resolved fires across all sleeves: **{total_fires:,}**")
    md.append(f"- Cells flagged for review (symmetric diff ≥ {FLAG_THRESHOLD_HOURS} hours): **{len(flagged)}**")
    md.append("")
    md.append("## Per-cell diff")
    md.append("")
    md.append("| cell | n | status | current | new | added | removed | flagged |")
    md.append("|---|--:|---|---|---|---|---|:--:|")
    for cell_key, d in diffs.items():
        n = per_cell_stats.get(cell_key, {}).get("n", "?")
        if d.get("status") == "NEW_CELL_NOT_IN_CURRENT_CONFIG":
            md.append(f"| {cell_key} | {n} | NEW | — | {d['new']} | — | — | — |")
            continue
        if d.get("status") == "NO_NEW_DATA":
            md.append(f"| {cell_key} | {n} | NO_DATA | {d['current']} | — | — | — | — |")
            continue
        flag = "🚩" if d.get("flagged_for_review") else ""
        md.append(f"| {cell_key} | {n} | OK | {d['current']} | {d['new']} | "
                  f"{d['added'] or '—'} | {d['removed'] or '—'} | {flag} |")
    md.append("")
    md.append("## Flagged cells (require human review before applying)")
    md.append("")
    if not flagged:
        md.append("✅ None — no cell changed by ≥ 3 hours. Safe to auto-apply.")
    else:
        for cell_key in flagged:
            d = diffs[cell_key]
            md.append(f"### {cell_key}")
            md.append(f"- Current: `{d['current']}`")
            md.append(f"- New:     `{d['new']}`")
            md.append(f"- Added hours: `{d['added']}`  Removed: `{d['removed']}`  Change size: `{d['change_size']}`")
            md.append("")
    md.append("## Next step")
    if not flagged:
        md.append(f"- Auto-update is SAFE. Apply the new dict to `backend/app/strategies/polymarket/gates.py::HOD_TOP8_BY_CELL` and redeploy.")
    else:
        md.append(f"- DO NOT auto-apply. Open a PR with the new dict and review each flagged cell. "
                  f"Common causes of large diffs: regime change, holiday/CPI distortion, "
                  f"new sleeve still in warmup.")
    md.append("")
    md.append("## Proposed new HOD_TOP8_BY_CELL (Python dict, paste into gates.py)")
    md.append("")
    md.append("```python")
    md.append("HOD_TOP8_BY_CELL: dict[tuple[str, str], list[int]] = {")
    for k, v in sorted(new_top8.items()):
        md.append(f"    ({k[0]!r:>10}, {k[1]!r:>10}): {v},")
    md.append("}")
    md.append("```")

    (out_dir / "refresh_report.md").write_text("\n".join(md))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=28,
                        help="Days of trading.events history to use (default: 28).")
    parser.add_argument("--no-vps3", action="store_true",
                        help="Skip VPS3 pull; expect local CSV at "
                             "strategy_lab/markov_filter/_vps3_pull/recent_resolutions.csv")
    args = parser.parse_args()

    run_date = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    out_dir = Path("strategy_lab/markov_filter/_results/hod_refresh") / run_date
    print(f"[1] Refreshing HoD-Top-8 over last {args.window_days}d (out: {out_dir})")

    if args.no_vps3:
        local = Path("strategy_lab/markov_filter/_vps3_pull/recent_resolutions.csv")
        df = pd.read_csv(local)
    else:
        print("[2] Pulling resolutions from VPS3...")
        try:
            df = pull_resolutions_from_vps3(args.window_days)
        except Exception as e:
            print(f"   ERROR: {e}", file=sys.stderr); sys.exit(2)
    print(f"   {len(df):,} resolved fires loaded")

    print("[3] Computing new top-8 per cell...")
    new_top8, per_cell_stats = compute_new_top8(df)
    print(f"   {len(new_top8)} cells computed (others lacked sample size)")

    print("[4] Diffing against currently-shipped HOD_TOP8_BY_CELL...")
    diffs, flagged = diff_against_current(new_top8)
    print(f"   Cells flagged: {len(flagged)} {flagged}")

    write_report(out_dir, new_top8, per_cell_stats, diffs, flagged,
                 args.window_days, len(df))
    print(f"\nReport: {out_dir/'refresh_report.md'}")

    sys.exit(1 if flagged else 0)


if __name__ == "__main__":
    main()
