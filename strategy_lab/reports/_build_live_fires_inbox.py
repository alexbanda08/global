"""Build per-sleeve realized-PnL summary report from live_fires_normalized.csv.

Writes:
  strategy_lab/reports/_live_fires_inbox.md (<=200 lines)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
INPUT = ROOT / "data" / "v4" / "canonical" / "_results" / "live_fires_normalized.csv"
OUT = ROOT / "strategy_lab" / "reports" / "_live_fires_inbox.md"


def fmt_us_to_iso(us: float) -> str:
    if pd.isna(us):
        return "NaT"
    return pd.Timestamp(int(us), unit="us", tz="UTC").strftime("%Y-%m-%d %H:%M UTC")


def main() -> None:
    df = pd.read_csv(INPUT, low_memory=False)
    df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce")
    df["at_us"] = pd.to_numeric(df["at_us"], errors="coerce")
    df["won"] = df["won"].map(lambda v: True if str(v).lower() in ("true", "1", "1.0") else (False if str(v).lower() in ("false", "0", "0.0") else None))
    df["date"] = pd.to_datetime(df["at_us"], unit="us", utc=True, errors="coerce").dt.date

    # Coverage
    min_at = df["at_us"].min()
    max_at = df["at_us"].max()
    n_fires = len(df)
    n_res = df["pnl_usd"].notna().sum()
    match_pct = (n_res / n_fires) * 100 if n_fires else 0.0
    dt_range_days = (max_at - min_at) / 1e6 / 86400 if pd.notna(min_at) and pd.notna(max_at) else float("nan")

    # Per-sleeve table
    g = df.dropna(subset=["pnl_usd"]).groupby("sleeve_id")
    summary = pd.DataFrame({
        "n": g.size(),
        "n_won": g.apply(lambda x: x["won"].fillna(False).sum(), include_groups=False),
        "wr_pct": g.apply(lambda x: 100 * x["won"].fillna(False).mean(), include_groups=False),
        "sum_pnl": g["pnl_usd"].sum(),
        "per_trade": g["pnl_usd"].mean(),
        "first_at": g["at_us"].min(),
        "last_at": g["at_us"].max(),
        "days_traded": g["date"].nunique(),
    }).reset_index()
    summary["days_span"] = (summary["last_at"] - summary["first_at"]) / 1e6 / 86400
    summary["per_day"] = summary["sum_pnl"] / summary["days_span"].clip(lower=1/24)  # min 1h
    summary = summary.sort_values("sum_pnl", ascending=False).reset_index(drop=True)

    # Per-strategy bucket
    bucket = df.dropna(subset=["pnl_usd"]).groupby("strategy")
    by_strategy = pd.DataFrame({
        "n": bucket.size(),
        "wr_pct": bucket.apply(lambda x: 100 * x["won"].fillna(False).mean(), include_groups=False),
        "sum_pnl": bucket["pnl_usd"].sum(),
        "per_trade": bucket["pnl_usd"].mean(),
    }).reset_index().sort_values("sum_pnl", ascending=False)

    # F7 mode breakdown (within momo_v2 fires)
    momo_df = df[df["strategy"].isin(["momo_v1", "momo_v2"])].dropna(subset=["pnl_usd"]).copy()
    f7g = momo_df.groupby(["strategy", "f7_mode"])
    by_f7 = pd.DataFrame({
        "n": f7g.size(),
        "wr_pct": f7g.apply(lambda x: 100 * x["won"].fillna(False).mean(), include_groups=False),
        "sum_pnl": f7g["pnl_usd"].sum(),
        "per_trade": f7g["pnl_usd"].mean(),
    }).reset_index().sort_values("sum_pnl", ascending=False)

    # Top / bottom
    top10 = summary.head(15)
    bot10 = summary.sort_values("sum_pnl").head(15)

    # Data-issue checks
    n_no_slug = df["slug"].isna().sum()
    n_no_ws = df["ws_s"].isna().sum()
    n_no_pnl = df["pnl_usd"].isna().sum()
    sleeves_no_pnl = df[df["pnl_usd"].isna()]["sleeve_id"].value_counts().head(5)

    # Compose markdown
    lines: list[str] = []
    lines.append("# Live shadow / paper / production fires — inbox")
    lines.append("")
    lines.append(f"_Built from `data/v4/canonical/_results/live_fires_normalized.csv` (this session)._")
    lines.append("")
    lines.append("## Coverage")
    lines.append("")
    lines.append(f"- Source A: `data/v4/canonical/trading_events_30d.parquet` (production `trading.events` from VPS3, 30d).")
    lines.append(f"- Source B: `migration_ireland_shadow_2026_05_21/maker_csvs/pat-shadow_2026-05-2{{0,1}}.csv` (Ireland shadow, May 20-21).")
    lines.append(f"- Source C: `data/v4/canonical/resolutions_from_rtds.parquet` (condition_id -> slug map).")
    lines.append("")
    lines.append(f"- Date range: **{fmt_us_to_iso(min_at)} -> {fmt_us_to_iso(max_at)}** ({dt_range_days:.1f} days).")
    lines.append(f"- Total fires: **{n_fires:,}**")
    lines.append(f"- With resolved PnL: **{n_res:,} ({match_pct:.1f}%)**")
    lines.append(f"- WON / LOST (where set): **{int(df['won'].fillna(False).sum()):,}** / **{int((~df['won'].fillna(True)).sum()):,}**")
    lines.append("")
    lines.append("Fires per source type:")
    src_counts = df.groupby("strategy").size().sort_values(ascending=False)
    for k, v in src_counts.items():
        lines.append(f"  - `{k}`: {v:,}")
    lines.append("")
    lines.append("## Per-strategy bucket")
    lines.append("")
    lines.append("| strategy | n | WR% | sum_pnl ($) | per_trade ($) |")
    lines.append("|---|---:|---:|---:|---:|")
    for _, r in by_strategy.iterrows():
        lines.append(f"| {r['strategy']} | {int(r['n']):,} | {r['wr_pct']:.1f} | {r['sum_pnl']:+.2f} | {r['per_trade']:+.3f} |")
    lines.append("")
    lines.append("## F7 filter mode breakdown (momo only)")
    lines.append("")
    lines.append("| strategy | f7_mode | n | WR% | sum_pnl ($) | per_trade ($) |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for _, r in by_f7.iterrows():
        lines.append(f"| {r['strategy']} | {r['f7_mode']} | {int(r['n']):,} | {r['wr_pct']:.1f} | {r['sum_pnl']:+.2f} | {r['per_trade']:+.3f} |")
    lines.append("")
    lines.append("## Top 15 sleeves by sum_pnl")
    lines.append("")
    lines.append("| sleeve_id | n | WR% | sum_pnl ($) | per_trade ($) | days | $/day |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for _, r in top10.iterrows():
        lines.append(f"| `{r['sleeve_id']}` | {int(r['n']):,} | {r['wr_pct']:.1f} | {r['sum_pnl']:+.2f} | {r['per_trade']:+.3f} | {int(r['days_traded'])} | {r['per_day']:+.2f} |")
    lines.append("")
    lines.append("## Bottom 15 sleeves by sum_pnl")
    lines.append("")
    lines.append("| sleeve_id | n | WR% | sum_pnl ($) | per_trade ($) | days | $/day |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for _, r in bot10.iterrows():
        lines.append(f"| `{r['sleeve_id']}` | {int(r['n']):,} | {r['wr_pct']:.1f} | {r['sum_pnl']:+.2f} | {r['per_trade']:+.3f} | {int(r['days_traded'])} | {r['per_day']:+.2f} |")
    lines.append("")
    # Verdict (clearly earning / clearly losing)
    earners = summary[(summary["sum_pnl"] > 50) & (summary["n"] >= 20)].sort_values("sum_pnl", ascending=False)
    losers = summary[(summary["sum_pnl"] < -50) & (summary["n"] >= 20)].sort_values("sum_pnl")
    lines.append("## Verdict — what's working / what's bleeding")
    lines.append("")
    lines.append(f"_Threshold: |sum_pnl| > $50 and n >= 20 fires._")
    lines.append("")
    lines.append(f"### EARNING ({len(earners)} sleeves)")
    lines.append("")
    for _, r in earners.head(20).iterrows():
        lines.append(f"- `{r['sleeve_id']}` — **{r['sum_pnl']:+.2f}** over {int(r['n'])} fires, WR {r['wr_pct']:.1f}%, {r['per_trade']:+.3f}/trade, {r['per_day']:+.2f}/day")
    lines.append("")
    lines.append(f"### LOSING ({len(losers)} sleeves)")
    lines.append("")
    for _, r in losers.head(20).iterrows():
        lines.append(f"- `{r['sleeve_id']}` — **{r['sum_pnl']:+.2f}** over {int(r['n'])} fires, WR {r['wr_pct']:.1f}%, {r['per_trade']:+.3f}/trade, {r['per_day']:+.2f}/day")
    lines.append("")
    lines.append("## Data issues / caveats")
    lines.append("")
    lines.append(f"- `slug` is missing for **{n_no_slug:,}** rows ({n_no_slug/n_fires*100:.1f}%). Mostly from `pat-shadow` and `mint_sell v2 fire` records where slug couldn't be resolved (mint_sell v2 fire data lacks slug; mint_sell *resolution* does carry one).")
    lines.append(f"- `ws_s` missing for **{n_no_ws:,}** rows (same root cause as slug).")
    lines.append(f"- `pnl_usd` missing for **{n_no_pnl:,}** rows — these are fired signals whose resolution event never wrote `fill_event_id` (the 1,533-row gap is mainly `poly_mint_sell_v2_*_paper` v2-fires that match `poly_mint_sell_resolution` rows only by `fire_event_id`; matched where possible).")
    lines.append("- Top unresolved sleeves:")
    for s, c in sleeves_no_pnl.items():
        lines.append(f"  - `{s}`: {c:,} fires without pnl_usd")
    lines.append("- Mint_sell v2 fires have `vwap=NaN` and `usd=NaN` because the v2 fire payload only carries `desired_*_qty` / `desired_*_px` (quote intent, not realized fill). Their realized PnL comes from the `poly_mint_sell_resolution` join on `fire_event_id`.")
    lines.append("- `won` in pat-shadow rows is derived as `pnl_final > 0` (heuristic), not from a settlement event.")
    lines.append("- Production fee model used in these resolutions = **2% on profit (winning leg only)** — verified 2026-05-22 against 25,900 resolutions. Same as `engine_v2.LegacyConfig`. The `0.07 * p * (1-p)` real-curve in `strategy_lab/fees.py` does NOT match production for these markets.")
    lines.append(f"- Other shadow caches inspected but NOT included in this CSV (older than 7 days or aggregate-only): `data/v4/canonical/_results/shadow_11_sleeves_{{backtest,v2}}.csv` (these are BACKTEST aggregate summaries, not per-fire); `shadow_logs/`, `shadow_logs_l25/` (May 18 snapshots).")

    # Write file
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f">> wrote {OUT} ({len(lines)} lines)")
    # Print headline numbers
    print()
    print("=== headline numbers ===")
    print(f"total fires:          {n_fires:,}")
    print(f"with resolved PnL:    {n_res:,} ({match_pct:.1f}%)")
    print(f"date span:            {dt_range_days:.1f} days")
    print()
    print("BY STRATEGY:")
    print(by_strategy.to_string(index=False))
    print()
    print("TOP 10 EARNING SLEEVES:")
    print(summary.head(10)[["sleeve_id","n","wr_pct","sum_pnl","per_trade","per_day"]].to_string(index=False))
    print()
    print("BOTTOM 10 LOSING SLEEVES:")
    print(summary.tail(10)[["sleeve_id","n","wr_pct","sum_pnl","per_trade","per_day"]].to_string(index=False))


if __name__ == "__main__":
    main()
