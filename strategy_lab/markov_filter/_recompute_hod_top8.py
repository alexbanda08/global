"""Recompute HoD-Top-8 per (strategy, cell) from 28d trading events.

Per spec section 6 of `TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md`:

    "On the 1st of each month, run the analysis script (lives in strategy_lab):
     python strategy_lab/markov_filter/_recompute_hod_top8.py --window-days 28"

The script:
  1. Loads `data/v4/canonical/trading_events_30d.parquet` (chainlink-resolved,
     production legacy 2%-on-profit PnL).
  2. For each base sleeve (momo, momo_v2, sniper) × asset × tf, derives fire_us
     from at_ts + window_s using the same family-specific offsets the shadow
     backtest uses.
  3. Aggregates sum(pnl_usd) per (fam, cell, fire_hour).
  4. Picks top 8 hours per cell.
  5. Diffs vs current HOD_TOP8_BY_CELL (from the shadow spec).
  6. Flags cells where the set changes by >= 3 hours (per spec).
  7. Writes JSON outputs + a human-readable markdown report.

OUTPUTS:
  strategy_lab/markov_filter/_results/hod_refresh/<run_date>/new_hod_top8.json
  strategy_lab/markov_filter/_results/hod_refresh/<run_date>/diff_vs_current.json
  strategy_lab/markov_filter/_results/hod_refresh/<run_date>/per_cell_hour_table.csv
  strategy_lab/reports/HOD_REFRESH_<run_date>.md

EXIT CODES:
  0 - refresh complete, no cells flagged for review
  1 - at least one cell flagged for review (>= 3 hour change)
  2 - script error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
EV = ROOT / "data" / "v4" / "canonical" / "trading_events_30d.parquet"

# Currently shipped HOD_TOP8_BY_CELL from
# strategy_lab/reports/TV_AGENT_SHADOW_DEPLOY_GATED_SLEEVES_2026_05_22.md §2.1
# (also embedded in shadow_11_sleeves_backtest.py).
CURRENT_HOD_TOP8_BY_CELL: dict[tuple[str, str], list[int]] = {
    ("sniper",  "sol_5m"):  [0, 1, 2, 4, 8, 15, 19, 23],
    ("sniper",  "eth_15m"): [0, 6, 7, 9, 13, 14, 19, 22],
    ("momo",    "btc_15m"): [0, 1, 3, 5, 9, 14, 16, 20],
    ("sniper",  "btc_15m"): [0, 3, 10, 11, 12, 13, 14, 15],
    ("sniper",  "btc_5m"):  [0, 1, 3, 5, 12, 15, 19, 21],
    ("momo_v2", "btc_5m"):  [0, 2, 5, 6, 10, 12, 21, 23],
    ("momo_v2", "btc_15m"): [1, 11, 12, 16, 18, 20, 21, 22],
    ("momo_v2", "sol_5m"):  [4, 5, 6, 8, 10, 12, 14, 17],
    ("momo_v2", "eth_15m"): [0, 5, 8, 12, 16, 17, 20, 22],
    ("momo_v2", "sol_15m"): [1, 2, 5, 12, 13, 16, 17, 21],
    ("sniper",  "eth_5m"):  [0, 2, 11, 13, 14, 17, 20, 21],
}


def classify_family(sleeve_id: str) -> str:
    if not isinstance(sleeve_id, str):
        return "unknown"
    s = sleeve_id.replace("poly_updown_", "")
    for suf in ("_HOLD", "_HEDGE", "_SELL"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    if any(tok in s for tok in ("_f7", "_hod", "_INV", "_DOWN_INV", "_NIGHT")):
        return "modified"
    if "momo_v2" in s:
        return "momo_v2"
    if s.endswith("_momo") or "_momo_" in s:
        return "momo"
    if s.endswith("_sniper") or "_sniper_" in s:
        return "sniper"
    return "other"


def parse_payload(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s)
    except Exception:
        return {}


def load_events(window_days: int) -> pd.DataFrame:
    print(f"[1] loading {EV.name}...")
    df = pd.read_parquet(EV)
    df = df[df.kind == "poly_updown_resolution"].copy()
    df["at_ts"] = pd.to_datetime(df["at"], utc=True, format="mixed", errors="coerce")
    df = df[df.at_ts.notna()].copy()

    df["p"] = df.data.apply(parse_payload)
    df["symbol"] = df.p.apply(lambda d: d.get("symbol"))
    df["tf"] = df.p.apply(lambda d: d.get("tf"))
    df["pnl_usd"] = pd.to_numeric(df.p.apply(lambda d: d.get("pnl_usd")), errors="coerce")
    df["won"] = df.p.apply(lambda d: bool(d.get("won")))
    df["fam"] = df.sleeve_id.apply(classify_family)

    df = df[
        df.fam.isin(("momo", "momo_v2", "sniper"))
        & df.symbol.isin(("BTC", "ETH", "SOL"))
        & df.tf.isin(("5m", "15m"))
        & df.pnl_usd.notna()
    ].copy()

    # window_days clamp from MAX(at_ts)
    max_ts = df.at_ts.max()
    cutoff = max_ts - pd.Timedelta(days=window_days)
    df = df[df.at_ts >= cutoff].copy()

    # Derive fire_s — see shadow_11_sleeves_backtest.py logic
    # at_ts = slot_end. slot_start = at_ts - window_s.
    # momo v1: fire = slot_start - window_s + 120 = at_ts - 2*window_s + 120
    # momo_v2: fire = slot_start - window_s +  60 = at_ts - 2*window_s + 60
    # sniper:  fire = slot_start = at_ts - window_s
    df["window_s"] = df.tf.map({"5m": 300, "15m": 900}).astype("int64")
    at_s = (df.at_ts.astype("int64") // 1_000_000_000).astype("int64")
    fire_s = np.where(
        df.fam.values == "momo",
        at_s - 2 * df.window_s.values + 120,
        np.where(
            df.fam.values == "momo_v2",
            at_s - 2 * df.window_s.values + 60,
            at_s - df.window_s.values,
        ),
    )
    df["fire_s"] = fire_s
    df["fire_ts"] = pd.to_datetime(df.fire_s, unit="s", utc=True)
    df["fire_hour"] = df.fire_ts.dt.hour
    df["at_hour"] = df.at_ts.dt.hour
    df["cell"] = df.symbol.str.lower() + "_" + df.tf

    print(f"    {len(df):,} resolved fires after {window_days}d window clamp")
    print(f"    span: {df.at_ts.min()} -> {df.at_ts.max()}")
    return df


def compute_top8_per_cell(df: pd.DataFrame, hour_col: str = "fire_hour") -> dict:
    """Return {(fam, cell): [hours sorted asc top 8]}."""
    grp = (
        df.groupby(["fam", "cell", hour_col])
        .agg(n=("pnl_usd", "size"), sum_pnl=("pnl_usd", "sum"), wr=("won", "mean"))
        .reset_index()
    )
    top8: dict[tuple[str, str], list[int]] = {}
    for (fam, cell), sub in grp.groupby(["fam", "cell"]):
        ranked = sub.sort_values("sum_pnl", ascending=False).head(8)
        top8[(fam, cell)] = sorted(int(h) for h in ranked[hour_col].values)
    return top8, grp


def diff_against_current(
    new_top8: dict[tuple[str, str], list[int]],
    current_top8: dict[tuple[str, str], list[int]],
) -> dict:
    diffs: dict[str, dict] = {}
    flagged: list[tuple[str, str]] = []
    for key in sorted(set(new_top8) | set(current_top8)):
        new = set(new_top8.get(key, []))
        old = set(current_top8.get(key, []))
        added = sorted(new - old)
        removed = sorted(old - new)
        change_size = max(len(added), len(removed))
        diffs[f"{key[0]}__{key[1]}"] = dict(
            new=sorted(new),
            old=sorted(old),
            added=added,
            removed=removed,
            change_size=int(change_size),
            flagged=change_size >= 3,
        )
        if change_size >= 3:
            flagged.append(key)
    return {"per_cell": diffs, "flagged": [list(k) for k in flagged]}


def write_report(
    out_md: Path,
    window_days: int,
    df: pd.DataFrame,
    new_top8_fire: dict,
    new_top8_at: dict,
    diff_fire: dict,
    grp_fire: pd.DataFrame,
    grp_at: pd.DataFrame,
    failing_sleeve_cells: list[tuple[str, str]],
) -> None:
    md: list[str] = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    md.append(f"# HoD-Top-8 refresh - {now}")
    md.append("")
    md.append(f"- Window: last **{window_days} days** of trading_events_30d.parquet")
    md.append(f"- Total resolved fires: **{len(df):,}**")
    md.append(f"- Span: {df.at_ts.min()} -> {df.at_ts.max()}")
    md.append(f"- Cells flagged (>=3 hour change vs current): "
              f"**{len(diff_fire['flagged'])}**")
    md.append("")
    md.append("## Per-cell diff (using FIRE_us hour, per spec §2.1)")
    md.append("")
    md.append("| Cell | Current | New (refreshed) | Added | Removed | Change | Flag |")
    md.append("|---|---|---|---|---|--:|:--:|")
    for key, d in sorted(diff_fire["per_cell"].items()):
        flag = "FLAG" if d["flagged"] else "."
        md.append(f"| `{key}` | {d['old']} | {d['new']} | {d['added']} | "
                  f"{d['removed']} | {d['change_size']} | {flag} |")
    md.append("")
    md.append("## Focus: failing shadow sleeves (#2, #3, #5, #10)")
    md.append("")
    md.append("Per HANDOFF_2026_05_22_MOMO_F7_MARKOV.md, these sleeves underperformed "
              "the expected ranges in the 11-sleeve shadow backtest. Refreshed HoD "
              "is the leading proposed fix.")
    md.append("")
    md.append("| Sleeve | (fam, cell) | Old hours | New hours | Symmetric diff |")
    md.append("|---|---|---|---|---|")
    for sid, key in failing_sleeve_cells:
        s_key = f"{key[0]}__{key[1]}"
        d = diff_fire["per_cell"].get(s_key, {})
        if d:
            sym_diff = sorted(set(d["added"]) | set(d["removed"]))
            md.append(f"| #{sid} | `{key}` | {d['old']} | {d['new']} | {sym_diff} |")
    md.append("")
    md.append("## Hour ranking detail (fire_hour) - failing sleeves only")
    md.append("")
    for sid, key in failing_sleeve_cells:
        sub = grp_fire[(grp_fire.fam == key[0]) & (grp_fire.cell == key[1])].copy()
        if sub.empty:
            continue
        sub = sub.sort_values("sum_pnl", ascending=False)
        sub["wr_pct"] = (sub.wr * 100).round(2)
        sub["sum_pnl"] = sub.sum_pnl.round(2)
        md.append(f"### Sleeve #{sid}: `{key[0]}` × `{key[1]}`")
        md.append("")
        md.append("| Hour (fire_us) | n | WR% | sum_pnl |")
        md.append("|--:|--:|--:|--:|")
        for _, r in sub.iterrows():
            md.append(f"| {int(r.fire_hour)} | {int(r.n)} | {r.wr_pct} | ${r.sum_pnl} |")
        md.append("")
    md.append("## Proposed new HOD_TOP8_BY_CELL (paste into gates.py)")
    md.append("")
    md.append("```python")
    md.append("HOD_TOP8_BY_CELL: dict[tuple[str, str], list[int]] = {")
    for k, v in sorted(new_top8_fire.items()):
        md.append(f"    ({k[0]!r:>10}, {k[1]!r:>10}): {v},")
    md.append("}")
    md.append("```")
    md.append("")
    md.append("## Sanity: at_ts (resolution-time) ranking for diff against original")
    md.append("")
    md.append("(The original shadow_11_sleeves_backtest.py used at_ts hour. "
              "The spec mandates fire_us hour. Reporting both for traceability.)")
    md.append("")
    md.append("| Cell | fire_us top8 | at_ts top8 | equal? |")
    md.append("|---|---|---|:--:|")
    for k in sorted(new_top8_fire):
        f8 = new_top8_fire[k]
        a8 = sorted(new_top8_at.get(k, []))
        eq = "yes" if set(f8) == set(a8) else "no"
        md.append(f"| `{k}` | {f8} | {a8} | {eq} |")
    md.append("")
    md.append(f"_generated by `strategy_lab/markov_filter/_recompute_hod_top8.py "
              f"--window-days {window_days}`_")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(md), encoding="utf-8")
    print(f"    report: {out_md}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--window-days", type=int, default=28)
    args = parser.parse_args()

    df = load_events(args.window_days)

    print(f"[2] computing top-8 hours per (fam, cell) using fire_us hour...")
    new_top8_fire, grp_fire = compute_top8_per_cell(df, hour_col="fire_hour")
    print(f"    cells: {len(new_top8_fire)}")

    print(f"[3] computing top-8 hours using at_ts hour (legacy comparison)...")
    new_top8_at, grp_at = compute_top8_per_cell(df, hour_col="at_hour")

    print(f"[4] diffing vs current HOD_TOP8_BY_CELL (fire_us hour, per spec)...")
    diff_fire = diff_against_current(new_top8_fire, CURRENT_HOD_TOP8_BY_CELL)
    n_flagged = len(diff_fire["flagged"])
    print(f"    cells flagged (>=3 hour change): {n_flagged}")

    run_date = datetime.now(timezone.utc).strftime("%Y_%m_%d")
    out_dir = ROOT / "strategy_lab" / "markov_filter" / "_results" / "hod_refresh" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON-friendly key encoding
    json_top8 = {f"{k[0]}__{k[1]}": v for k, v in new_top8_fire.items()}
    json_top8_at = {f"{k[0]}__{k[1]}": v for k, v in new_top8_at.items()}
    json_current = {f"{k[0]}__{k[1]}": v for k, v in CURRENT_HOD_TOP8_BY_CELL.items()}

    (out_dir / "new_hod_top8.json").write_text(json.dumps(json_top8, indent=2))
    (out_dir / "new_hod_top8_at_ts.json").write_text(json.dumps(json_top8_at, indent=2))
    (out_dir / "current_hod_top8.json").write_text(json.dumps(json_current, indent=2))
    (out_dir / "diff_vs_current.json").write_text(json.dumps(diff_fire, indent=2))
    grp_fire.to_csv(out_dir / "per_cell_hour_table_fire.csv", index=False)
    grp_at.to_csv(out_dir / "per_cell_hour_table_at_ts.csv", index=False)

    print(f"[5] writing report...")
    failing_sleeve_cells = [
        (2,  ("sniper",  "eth_15m")),
        (3,  ("momo",    "btc_15m")),
        (5,  ("sniper",  "btc_5m")),
        (10, ("momo_v2", "sol_15m")),
    ]
    report_path = (
        ROOT / "strategy_lab" / "reports" / f"HOD_REFRESH_{run_date}.md"
    )
    write_report(
        report_path,
        args.window_days,
        df,
        new_top8_fire,
        new_top8_at,
        diff_fire,
        grp_fire,
        grp_at,
        failing_sleeve_cells,
    )

    print(f"\nSaved outputs to: {out_dir}")
    print(f"Report:           {report_path}")
    print()
    print(f"Failing-sleeve diffs (focus cells):")
    for sid, key in failing_sleeve_cells:
        s_key = f"{key[0]}__{key[1]}"
        d = diff_fire["per_cell"].get(s_key, {})
        if d:
            print(f"  #{sid:>2}  {key[0]:<8} {key[1]:<8}  "
                  f"old={d['old']}  new={d['new']}  "
                  f"sym_diff={sorted(set(d['added']) | set(d['removed']))}")

    return 1 if n_flagged > 0 else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {e}", file=sys.stderr)
        sys.exit(2)
