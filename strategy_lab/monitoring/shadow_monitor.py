"""
PAT+ACC-M shadow log monitor.

Parses TV agent's `/var/log/tv/maker/acc-m_YYYY-MM-DD.csv` shadow log,
computes drift metrics vs the full-universe backtest baseline, and flags
RED/AMBER/GREEN per metric.

Schema assumed (auto-detects what's there, missing cols → "n/a"):
  ts_us | timestamp        — int micros or ISO string
  action                   — POST_BID | CANCEL | FILL | TAKE | MERGE | LOG_SLUG_COMPLETE
  trigger_reason           — post_initial_bid | cancel_displaced_3c | cancel_age_20s
                              | merge_paired_>=5 | pat_pair_cost=X.XXXX
  slug                     — btc-updown-5m-NNNNNNN
  side                     — Up | Down
  price                    — float (PAT TAKE rows have the ask)
  size                     — float (intended size)
  filled_size              — float (actual fill, optional)
  up_filled, dn_filled     — for TAKE rows if logged together
  pair_cost                — for TAKE rows if separately logged
  pnl                      — for LOG_SLUG_COMPLETE rows

Usage:
  py -3 -X utf8 strategy_lab/monitoring/shadow_monitor.py \
      --csv /path/to/acc-m_2026-05-21.csv

  # multi-day rolling
  py -3 -X utf8 strategy_lab/monitoring/shadow_monitor.py \
      --csv shadow_logs/acc-m_2026-05-19.csv \
            shadow_logs/acc-m_2026-05-20.csv \
            shadow_logs/acc-m_2026-05-21.csv

  # pull from Ireland VPS first (uses local SSH config alias `ireland`)
  bash strategy_lab/monitoring/pull_shadow_logs.sh
  py -3 -X utf8 strategy_lab/monitoring/shadow_monitor.py \
      --csv strategy_lab/monitoring/_logs/*.csv

Outputs (strategy_lab/monitoring/_out/):
  _shadow_dashboard.txt        — the table that prints to stdout
  _shadow_summary.csv          — one-row metric snapshot
  _shadow_per_slug.csv         — per-slug PnL + drift vs backtest
  _shadow_pat_fires.csv        — every PAT fire with pair_cost
  _shadow_hourly.csv           — per-hour fire-rate + PnL
  _shadow_alerts.csv           — only RED/AMBER drifts
"""
from __future__ import annotations
import argparse
import glob
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "strategy_lab" / "monitoring" / "_out"

# ---------------------------------------------------------------------------
# Backtest reference — derived from this session's full BTC 5m universe run
# Source: strategy_lab/backtests/_fast_full_btc_full_btc5m.csv (strategy=PAT+ACC-M)
# ---------------------------------------------------------------------------
BACKTEST_REF = {
    "btc_5m": {
        "fire_rate_pct": 48.8,                    # 2984 / 6110 slugs had >=1 fire
        "pat_fires_per_slug_over_all": 0.5,       # ~0.5 fires per slug avg incl. zeros
        "pat_pair_cost_mean": 0.97,               # expected mean (always < 1.00)
        "pat_pair_cost_max": 1.0,                 # hard cap, must NEVER be exceeded
        "partial_fill_rate_pct": 5.0,             # backtest assumption — bounded
        "maker_bid_fills_per_slug_avg": 15.0,     # from per-slug expected behavior
        "merges_per_slug_avg": 3.0,
        "pnl_per_slug_full_universe_mean": 7.79,
        "pnl_per_slug_firing_only_mean": 15.95,
        "pnl_per_slug_firing_only_median": 1.50,
        "win_rate_firing_pct": 75.0,
    },
}

# Tolerance + direction per metric.
#   "two_sided" — flag drift in both directions
#   "above"     — flag only when live > backtest + tol (e.g. pair_cost_max must NOT exceed)
#   "below"     — flag only when live < backtest - tol (e.g. PnL, win rate)
TOLERANCE = {
    "fire_rate_pct":                    {"tol": 15.0,  "dir": "two_sided"},
    "pat_fires_per_slug_over_all":      {"tol": 0.5,   "dir": "two_sided"},
    "pat_pair_cost_mean":               {"tol": 0.02,  "dir": "above"},      # too high = bleeding fee
    "pat_pair_cost_max":                {"tol": 0.005, "dir": "above"},      # CRITICAL — never exceed 1.00 cap
    "partial_fill_rate_pct":            {"tol": 5.0,   "dir": "above"},      # high = bad; low = good
    "maker_bid_fills_per_slug_avg":     {"tol": 10.0,  "dir": "below"},      # low fills = poor queue position
    "merges_per_slug_avg":              {"tol": 1.5,   "dir": "below"},      # low = sub-firing
    "pnl_per_slug_full_universe_mean":  {"tol": 4.0,   "dir": "below"},      # only worse-than-backtest matters
    "pnl_per_slug_firing_only_mean":    {"tol": 8.0,   "dir": "below"},
    "win_rate_firing_pct":              {"tol": 15.0,  "dir": "below"},
}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
def load_logs(paths: list[str]) -> pd.DataFrame:
    dfs = []
    for p in paths:
        path = Path(p)
        if not path.exists():
            print(f"  WARN: {p} not found, skipping", file=sys.stderr)
            continue
        df = pd.read_csv(path)
        df.columns = [c.lower().strip() for c in df.columns]
        df["_source_file"] = path.name
        dfs.append(df)
    if not dfs:
        raise SystemExit("No log files loaded")
    return pd.concat(dfs, ignore_index=True)


def parse_pat_pair_cost(reason) -> float:
    """Extract pair_cost from 'pat_pair_cost=0.9823' style strings."""
    if not isinstance(reason, str):
        return np.nan
    m = re.search(r"pat_pair_cost=([0-9]*\.?[0-9]+)", reason)
    if not m:
        return np.nan
    try:
        return float(m.group(1))
    except (ValueError, IndexError):
        return np.nan


def extract_hour_utc(df: pd.DataFrame) -> pd.Series:
    """Best-effort UTC hour extraction from ts_us or timestamp column."""
    if "ts_us" in df.columns:
        return pd.to_datetime(df["ts_us"], unit="us", utc=True).dt.hour
    if "timestamp_us" in df.columns:
        return pd.to_datetime(df["timestamp_us"], unit="us", utc=True).dt.hour
    if "timestamp" in df.columns:
        s = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        return s.dt.hour
    return pd.Series([np.nan] * len(df))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def compute_metrics(df: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (metrics, takes_df, slug_complete_df, hourly_df)."""
    if "action" not in df.columns:
        raise SystemExit("CSV missing required 'action' column")
    df["action_u"] = df["action"].astype(str).str.upper()

    posts   = df[df.action_u == "POST_BID"]
    cancels = df[df.action_u == "CANCEL"]
    fills   = df[df.action_u == "FILL"]
    takes   = df[df.action_u == "TAKE"].copy()
    merges  = df[df.action_u == "MERGE"]
    sc      = df[df.action_u.isin(["LOG_SLUG_COMPLETE", "SLUG_COMPLETE", "FINALIZE"])]

    # PAT pair_cost — from explicit column or parsed from trigger_reason
    if "trigger_reason" in takes.columns:
        takes["pair_cost_parsed"] = takes["trigger_reason"].apply(parse_pat_pair_cost)
    if "pair_cost" in takes.columns:
        takes["pair_cost_final"] = takes["pair_cost"].astype(float)
    elif "pair_cost_parsed" in takes.columns:
        takes["pair_cost_final"] = takes["pair_cost_parsed"]
    else:
        takes["pair_cost_final"] = np.nan

    slugs_all = df["slug"].dropna().unique() if "slug" in df.columns else np.array([])
    n_slugs = len(slugs_all)

    m: dict = {
        "n_log_rows": int(len(df)),
        "n_slugs_seen": int(n_slugs),
        "n_posts": int(len(posts)),
        "n_cancels": int(len(cancels)),
        "n_fills": int(len(fills)),
        "n_takes": int(len(takes)),
        "n_merges": int(len(merges)),
        "n_slug_complete": int(len(sc)),
    }

    # PAT metrics
    if not takes.empty and n_slugs > 0:
        slugs_with_take = takes["slug"].dropna().nunique() if "slug" in takes.columns else 0
        m["fire_rate_pct"] = round(slugs_with_take / n_slugs * 100, 2)
        m["pat_fires_per_slug_over_all"] = round(len(takes) / n_slugs, 3)
        pc = takes["pair_cost_final"].dropna()
        if not pc.empty:
            m["pat_pair_cost_mean"] = round(float(pc.mean()), 4)
            m["pat_pair_cost_median"] = round(float(pc.median()), 4)
            m["pat_pair_cost_max"] = round(float(pc.max()), 4)
            m["pat_pair_cost_p99"] = round(float(pc.quantile(0.99)), 4)
            m["pat_pair_cost_n"] = int(len(pc))

    # Partial-fill detection
    partial_fill_rate = np.nan
    if {"up_filled", "dn_filled"}.issubset(takes.columns):
        non_zero = takes[(takes.up_filled > 0) | (takes.dn_filled > 0)]
        partial = non_zero[non_zero.up_filled != non_zero.dn_filled]
        if len(non_zero):
            partial_fill_rate = round(len(partial) / len(non_zero) * 100, 2)
    elif "filled_size" in takes.columns and "size" in takes.columns:
        partial = takes[takes.filled_size < takes["size"] * 0.99]
        if len(takes):
            partial_fill_rate = round(len(partial) / len(takes) * 100, 2)
    m["partial_fill_rate_pct"] = partial_fill_rate

    # Maker fills per slug (proxy via FILL action; fall back to count of POST_BID)
    if not fills.empty and "slug" in fills.columns:
        m["maker_bid_fills_per_slug_avg"] = round(
            len(fills) / max(n_slugs, 1), 2)
    elif not posts.empty:
        m["maker_bid_fills_per_slug_avg"] = round(
            len(posts) / max(n_slugs, 1), 2)
    else:
        m["maker_bid_fills_per_slug_avg"] = np.nan

    # Merges per slug
    if not merges.empty and "slug" in merges.columns:
        m["merges_per_slug_avg"] = round(len(merges) / max(n_slugs, 1), 2)
    else:
        m["merges_per_slug_avg"] = np.nan

    # PnL
    if not sc.empty and "pnl" in sc.columns:
        pnl = pd.to_numeric(sc["pnl"], errors="coerce").dropna()
        if not pnl.empty:
            m["pnl_per_slug_full_universe_mean"] = round(float(pnl.mean()), 4)
            m["pnl_per_slug_median"] = round(float(pnl.median()), 4)
            m["pnl_per_slug_sum"] = round(float(pnl.sum()), 2)
            m["pnl_n_slugs_complete"] = int(len(pnl))
            # PnL on firing-only slugs
            firing_slugs = takes["slug"].dropna().unique() if not takes.empty else []
            if "slug" in sc.columns and len(firing_slugs) > 0:
                pnl_fire = pd.to_numeric(
                    sc[sc.slug.isin(firing_slugs)]["pnl"], errors="coerce").dropna()
                if not pnl_fire.empty:
                    m["pnl_per_slug_firing_only_mean"] = round(float(pnl_fire.mean()), 4)
                    m["pnl_per_slug_firing_only_median"] = round(float(pnl_fire.median()), 4)
                    m["win_rate_firing_pct"] = round(float((pnl_fire > 0).mean() * 100), 2)

    # Hourly breakdown (UTC)
    hourly_df = pd.DataFrame()
    if not takes.empty:
        takes["hour_utc"] = extract_hour_utc(takes)
        if takes["hour_utc"].notna().any():
            hourly = takes.groupby("hour_utc").agg(
                n_fires=("slug", "size"),
                n_unique_slugs=("slug", "nunique"),
                pair_cost_mean=("pair_cost_final", "mean"),
            ).reset_index()
            hourly_df = hourly

    return m, takes, sc, hourly_df


# ---------------------------------------------------------------------------
# Drift flag
# ---------------------------------------------------------------------------
def flag_drift(value, ref, tol_cfg) -> str:
    """Return GREEN/AMBER/RED based on direction-aware tolerance."""
    if value is None or pd.isna(value):
        return "n/a"
    tol = tol_cfg["tol"]
    direction = tol_cfg["dir"]
    diff = value - ref          # signed
    if direction == "above":
        # Only flag if live exceeds backtest + tol
        if diff <= tol * 0.5:
            return "GREEN"
        if diff <= tol:
            return "AMBER"
        return "RED"
    if direction == "below":
        # Only flag if live falls below backtest - tol
        if diff >= -tol * 0.5:
            return "GREEN"
        if diff >= -tol:
            return "AMBER"
        return "RED"
    # two_sided
    abs_diff = abs(diff)
    if abs_diff <= tol * 0.5:
        return "GREEN"
    if abs_diff <= tol:
        return "AMBER"
    return "RED"


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
DASHBOARD_ROWS = [
    # (label, metric_key, ref_key, tol_key)
    ("Fire rate (% of slugs with >=1 PAT)",    "fire_rate_pct",                 "fire_rate_pct",                 "fire_rate_pct"),
    ("PAT fires per slug (incl zeros)",         "pat_fires_per_slug_over_all",   "pat_fires_per_slug_over_all",  "pat_fires_per_slug_over_all"),
    ("PAT pair_cost (mean)",                    "pat_pair_cost_mean",            "pat_pair_cost_mean",           "pat_pair_cost_mean"),
    ("PAT pair_cost (max — MUST be < 1.00)",    "pat_pair_cost_max",             "pat_pair_cost_max",            "pat_pair_cost_max"),
    ("Partial-fill rate (%)",                   "partial_fill_rate_pct",         "partial_fill_rate_pct",        "partial_fill_rate_pct"),
    ("Maker BID fills per slug (avg)",          "maker_bid_fills_per_slug_avg",  "maker_bid_fills_per_slug_avg", "maker_bid_fills_per_slug_avg"),
    ("Merges per slug (avg)",                   "merges_per_slug_avg",           "merges_per_slug_avg",          "merges_per_slug_avg"),
    ("PnL/slug — all slugs (mean)",             "pnl_per_slug_full_universe_mean","pnl_per_slug_full_universe_mean","pnl_per_slug_full_universe_mean"),
    ("PnL/slug — firing only (mean)",           "pnl_per_slug_firing_only_mean", "pnl_per_slug_firing_only_mean","pnl_per_slug_firing_only_mean"),
    ("Win rate on firing slugs (%)",            "win_rate_firing_pct",           "win_rate_firing_pct",          "win_rate_firing_pct"),
]


def render_dashboard(m: dict, cell: str = "btc_5m") -> str:
    ref = BACKTEST_REF[cell]
    lines: list[str] = []
    lines.append("=" * 90)
    lines.append(f"PAT+ACC-M Shadow Monitor — cell={cell}  generated={datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 90)
    lines.append(f"  log rows: {m.get('n_log_rows', 0):,}")
    lines.append(f"  slugs seen: {m.get('n_slugs_seen', 0):,}")
    lines.append(f"  POST_BID={m.get('n_posts', 0):,}  CANCEL={m.get('n_cancels', 0):,}  "
                 f"FILL={m.get('n_fills', 0):,}  TAKE={m.get('n_takes', 0):,}  "
                 f"MERGE={m.get('n_merges', 0):,}  LOG_SLUG_COMPLETE={m.get('n_slug_complete', 0):,}")
    lines.append("")
    lines.append(f"{'Metric':<42}{'Live':>12}{'Backtest':>12}{'Drift':>10}")
    lines.append("-" * 90)
    alerts = []
    for label, mk, rk, tk in DASHBOARD_ROWS:
        live = m.get(mk, np.nan)
        ref_v = ref.get(rk, np.nan)
        tol_cfg = TOLERANCE.get(tk, {"tol": 0.0, "dir": "two_sided"})
        flag = flag_drift(live, ref_v, tol_cfg)
        if isinstance(live, float):
            live_str = f"{live:.4f}" if not pd.isna(live) else "n/a"
        else:
            live_str = str(live)
        ref_str = f"{ref_v:.4f}" if isinstance(ref_v, (int, float)) else str(ref_v)
        lines.append(f"{label:<42}{live_str:>12}{ref_str:>12}{flag:>10}")
        if flag in ("RED", "AMBER"):
            alerts.append({"metric": mk, "live": live, "backtest": ref_v,
                            "tolerance": tol_cfg["tol"], "direction": tol_cfg["dir"],
                            "flag": flag})
    lines.append("")
    if not alerts:
        lines.append("All metrics GREEN ✓  no drift detected")
    else:
        lines.append(f"Drift alerts: {sum(1 for a in alerts if a['flag']=='RED')} RED, "
                     f"{sum(1 for a in alerts if a['flag']=='AMBER')} AMBER")
        for a in alerts:
            sign = "+" if (a["live"] - a["backtest"]) > 0 else ""
            lines.append(f"  [{a['flag']:5s}] {a['metric']}: live={a['live']:.4f}  "
                         f"backtest={a['backtest']:.4f}  drift={sign}{a['live']-a['backtest']:.4f}  "
                         f"(tol ±{a['tolerance']})")
    return "\n".join(lines), alerts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", nargs="+", required=True,
                    help="One or more shadow CSV files (glob OK)")
    ap.add_argument("--cell", default="btc_5m",
                    choices=list(BACKTEST_REF.keys()))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    # Expand globs
    paths: list[str] = []
    for p in args.csv:
        if any(ch in p for ch in "*?["):
            paths.extend(sorted(glob.glob(p)))
        else:
            paths.append(p)
    if not paths:
        raise SystemExit("No CSV files matched")

    print(f"Loading {len(paths)} file(s)...")
    df = load_logs(paths)
    print(f"  {len(df):,} log rows")

    m, takes, sc, hourly = compute_metrics(df)
    dash, alerts = render_dashboard(m, args.cell)
    print(dash)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "_shadow_dashboard.txt").write_text(dash, encoding="utf-8")
    pd.DataFrame([m]).to_csv(out / "_shadow_summary.csv", index=False)
    if not sc.empty:
        cols = [c for c in ["slug", "ts_us", "timestamp", "outcome_truth",
                            "pnl", "_source_file"] if c in sc.columns]
        per_slug = sc[cols].copy()
        ref = BACKTEST_REF[args.cell]["pnl_per_slug_full_universe_mean"]
        if "pnl" in per_slug.columns:
            per_slug["pnl_drift_vs_backtest"] = (
                pd.to_numeric(per_slug["pnl"], errors="coerce") - ref)
        per_slug.to_csv(out / "_shadow_per_slug.csv", index=False)
    if not takes.empty:
        cols = [c for c in ["ts_us", "timestamp", "slug", "trigger_reason",
                            "pair_cost_final", "size", "up_filled", "dn_filled",
                            "_source_file"] if c in takes.columns]
        takes[cols].to_csv(out / "_shadow_pat_fires.csv", index=False)
    if not hourly.empty:
        hourly.to_csv(out / "_shadow_hourly.csv", index=False)
    pd.DataFrame(alerts).to_csv(out / "_shadow_alerts.csv", index=False)

    print(f"\nOutputs written to {out}/")


if __name__ == "__main__":
    main()
