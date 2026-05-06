"""compare_3way — compare backtest L10 vs realfill L25 vs shadow live for momo sleeves.

Inputs:
    data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv   (live fires from VPS3)
    strategy_lab/results/meta_classifier/extended_backtest.csv     (L10 backtest cells)
    strategy_lab/results/meta_classifier/momo_realfill_validation.csv (L25 realfill cells)
    strategy_lab/results/meta_classifier/momo_realfill_pertrade.csv (L25 per-trade — needed
        to filter to the same window-start range as the shadow period)

Strategy:
    1. Load shadow resolutions; derive (asset, tf, exit, ws_unix) per row.
    2. Find shadow's window-start range [ws_min, ws_max].
    3. From per-trade L25 realfill, filter to fires with ws ∈ [ws_min, ws_max].
       This is the SAME-WINDOW realfill subset.
    4. Aggregate per (asset, tf, exit) and emit the 3-way table:
         Shadow:    n / hit% / pnl_total / pnl_mean
         L25 same-window: same metrics
         L10 full-period (cell totals from extended_backtest.csv) — the original spec target
       and also L10 same-window if computable.

Output:
    strategy_lab/results/meta_classifier/momo_3way_compare.csv
    strategy_lab/reports/MOMO_3WAY_COMPARISON_2026_05_06.md
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
SHADOW = ROOT / "data" / "v4" / "shadow_trades_2026_05_06" / "momo_resolutions_fresh.csv"
BT_CELLS = ROOT / "strategy_lab" / "results" / "meta_classifier" / "extended_backtest.csv"
RF_CELLS = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_realfill_validation.csv"
RF_PERTRADE = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_realfill_pertrade.csv"

OUT_CSV = ROOT / "strategy_lab" / "results" / "meta_classifier" / "momo_3way_compare.csv"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "MOMO_3WAY_COMPARISON_2026_05_06.md"

SLEEVE_RE = re.compile(r"poly_updown_(btc|eth|sol)_(5m|15m)_momo_(HOLD|HEDGE|SELL)$")
SLUG_RE = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def parse_sleeve(sid: str):
    m = SLEEVE_RE.match(sid)
    if not m:
        return None
    return m.group(1).upper(), m.group(2), m.group(3)


def load_shadow() -> pd.DataFrame:
    df = pd.read_csv(SHADOW)
    # Postgres exports booleans as 't'/'f' — convert
    for col in ("won", "hedged", "partial_bid_exit"):
        if col in df.columns and df[col].dtype == object:
            df[col] = df[col].map({"t": True, "f": False}).astype(bool)
    # Postgres numeric → string in CSV — coerce to float
    for col in ("pnl_usd", "entry_price", "entry_qty", "hedge_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df["asset"] = df["sleeve_id"].apply(lambda s: parse_sleeve(s)[0] if parse_sleeve(s) else None)
    df["timeframe"] = df["sleeve_id"].apply(lambda s: parse_sleeve(s)[1] if parse_sleeve(s) else None)
    df["exit"] = df["sleeve_id"].apply(lambda s: parse_sleeve(s)[2] if parse_sleeve(s) else None)
    df = df.dropna(subset=["asset", "timeframe", "exit"]).copy()
    # Each shadow row carries a fill_event_id and ts. We want the underlying market's
    # window_start_unix. We don't have it directly in the resolution event — but we
    # can derive from the at timestamp: a 5m market resolves at ws+300s, so
    # ws ≈ at_unix − 300. For 15m, ws ≈ at_unix − 900. Approximate but adequate
    # for a window range filter.
    df["at_unix"] = pd.to_datetime(df["at"], format="mixed", utc=True).astype("int64") // 1_000_000_000
    df["ws_approx"] = df["at_unix"] - df["timeframe"].map({"5m": 300, "15m": 900})
    return df


def load_realfill_pertrade() -> pd.DataFrame:
    df = pd.read_csv(RF_PERTRADE)
    # Existing columns: asset, slug, ws_s, tf, signal, outcome_up, policy, exit_reason,
    #                   pnl, cost, vwap_e, n_rev_triggers, hedge_feasible, sell_feasible
    # Standardize asset and tf casing
    df["asset"] = df["asset"].str.upper()
    df["timeframe"] = df["tf"]
    df["exit"] = df["policy"]  # HOLD / HEDGE / SELL
    return df


def load_bt_cells() -> pd.DataFrame:
    df = pd.read_csv(BT_CELLS)
    parts = df["label"].str.split("_", expand=True)
    df["asset"] = parts[0]
    df["timeframe"] = parts[1]
    df["exit"] = parts[2]
    return df


def load_rf_cells() -> pd.DataFrame:
    df = pd.read_csv(RF_CELLS)
    parts = df["label"].str.split("_", expand=True)
    df["asset"] = parts[0]
    df["timeframe"] = parts[1]
    df["exit"] = parts[2]
    return df


def aggregate(df: pd.DataFrame, pnl_col: str, won_col: str | None = None) -> pd.DataFrame:
    """Aggregate per (asset, tf, exit). For shadow, won is from `won` boolean.
    For realfill per-trade, derived from sign(pnl)."""
    grouped = df.groupby(["asset", "timeframe", "exit"])
    rows = []
    for (asset, tf, ex), g in grouped:
        n = len(g)
        if won_col is not None:
            wins = int(g[won_col].sum())
        else:
            wins = int((g[pnl_col] > 0).sum())
        rows.append({
            "asset": asset, "timeframe": tf, "exit": ex,
            "n": n, "wins": wins,
            "hit": wins / n if n else 0.0,
            "pnl_total": float(g[pnl_col].sum()),
            "pnl_mean": float(g[pnl_col].mean()) if n else 0.0,
        })
    return pd.DataFrame(rows)


def main():
    print("[1] loading shadow…")
    shadow = load_shadow()
    print(f"    shadow: {len(shadow)} fires; ws_approx ∈ "
          f"[{shadow['ws_approx'].min()}, {shadow['ws_approx'].max()}]")
    ws_min = int(shadow["ws_approx"].min()) - 60
    ws_max = int(shadow["ws_approx"].max()) + 60

    print("[2] loading realfill per-trade…")
    rf_pt = load_realfill_pertrade()
    print(f"    realfill per-trade: {len(rf_pt)} rows; ws_s ∈ "
          f"[{rf_pt['ws_s'].min()}, {rf_pt['ws_s'].max()}]")

    # NOTE: backtest data ends ~May 4 (refresh_2026_05_02 cutoff), shadow starts
    # May 6 deploy → NO window overlap. Compare per-trade distributions instead.
    rf_window = rf_pt[(rf_pt["ws_s"] >= ws_min) & (rf_pt["ws_s"] <= ws_max)].copy()
    print(f"    realfill same-window subset: {len(rf_window)} rows "
          f"({'no overlap — comparing distributions' if len(rf_window) == 0 else 'overlap'})")

    print("[3] loading L10 cells (extended_backtest.csv)…")
    bt = load_bt_cells()

    print("[4] loading L25 cells (momo_realfill_validation.csv)…")
    rf_full = load_rf_cells()

    # Aggregate
    agg_shadow = aggregate(shadow, pnl_col="pnl_usd", won_col="won")
    agg_rf_window = aggregate(rf_window, pnl_col="pnl") if len(rf_window) > 0 else pd.DataFrame(
        columns=["asset", "timeframe", "exit", "n", "wins", "hit", "pnl_total", "pnl_mean"])

    # Merge into 3-way table
    print("[5] merging 3-way table…")
    cells = []
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            for ex in ("HOLD", "HEDGE", "SELL"):
                row: dict = {"cell": f"{asset}_{tf}_{ex}", "asset": asset, "tf": tf, "exit": ex}
                # Shadow
                m = (agg_shadow["asset"] == asset) & (agg_shadow["timeframe"] == tf) & (agg_shadow["exit"] == ex)
                if m.any():
                    s = agg_shadow[m].iloc[0]
                    row.update({
                        "shadow_n": int(s["n"]),
                        "shadow_hit": float(s["hit"]),
                        "shadow_pnl_total": float(s["pnl_total"]),
                        "shadow_pnl_mean": float(s["pnl_mean"]),
                    })
                # L25 realfill (same window)
                m = (agg_rf_window["asset"] == asset) & (agg_rf_window["timeframe"] == tf) & (agg_rf_window["exit"] == ex)
                if m.any():
                    s = agg_rf_window[m].iloc[0]
                    row.update({
                        "rf_window_n": int(s["n"]),
                        "rf_window_hit": float(s["hit"]),
                        "rf_window_pnl_total": float(s["pnl_total"]),
                        "rf_window_pnl_mean": float(s["pnl_mean"]),
                    })
                # L25 realfill (full)
                m = (rf_full["asset"] == asset) & (rf_full["timeframe"] == tf) & (rf_full["exit"] == ex)
                if m.any():
                    s = rf_full[m].iloc[0]
                    row.update({
                        "rf_full_n": int(s["n"]),
                        "rf_full_hit": float(s["hit"]),
                        "rf_full_pnl_total": float(s["pnl_total"]),
                        "rf_full_pnl_mean": float(s["pnl_mean"]),
                    })
                # L10 backtest (full)
                m = (bt["asset"] == asset) & (bt["timeframe"] == tf) & (bt["exit"] == ex)
                if m.any():
                    s = bt[m].iloc[0]
                    row.update({
                        "bt_full_n": int(s["n"]),
                        "bt_full_hit": float(s["hit"]),
                        "bt_full_pnl_total": float(s["pnl_total"]),
                        "bt_full_pnl_mean": float(s["pnl_mean"]),
                    })
                cells.append(row)

    out = pd.DataFrame(cells)
    out.to_csv(OUT_CSV, index=False)
    print(f"    [csv] → {OUT_CSV}")

    # Print + report
    print("\n[6] 3-way comparison:\n")
    cols = ["cell",
            "shadow_n", "shadow_hit", "shadow_pnl_total", "shadow_pnl_mean",
            "rf_full_n", "rf_full_hit", "rf_full_pnl_mean",
            "bt_full_n", "bt_full_hit", "bt_full_pnl_mean"]
    avail_cols = [c for c in cols if c in out.columns]
    print(out[avail_cols].to_string(index=False))

    write_report(out, ws_min, ws_max, len(shadow), len(rf_window))


def write_report(df: pd.DataFrame, ws_min: int, ws_max: int,
                 n_shadow: int, n_rf_window: int) -> None:
    L: list[str] = []
    L.append("# Momo 3-Way Comparison — Backtest L10 vs Realfill L25 vs Shadow Live\n")
    L.append("**Generated:** 2026-05-06\n")

    from datetime import datetime, timezone
    ws_min_dt = datetime.fromtimestamp(ws_min, tz=timezone.utc).isoformat()
    ws_max_dt = datetime.fromtimestamp(ws_max, tz=timezone.utc).isoformat()
    L.append(f"**Shadow window:** {ws_min_dt} → {ws_max_dt} UTC")
    L.append(f"**Shadow fires:** {n_shadow} live resolutions across 18 sleeves\n")
    L.append("**Important:** the L25 realfill backtest was built on the Apr 22 → May 4 data window "
             "(refresh_2026_05_02 cutoff). Shadow trading started May 6. **No time-window overlap** — "
             "comparison is between PER-TRADE DISTRIBUTIONS (mean PnL, hit rate per cell), not direct "
             "same-trade matches.\n")

    L.append("## Three data sources\n")
    L.append("| Source | Window | n | Fill model |")
    L.append("|---|---|---:|---|")
    L.append(f"| **Shadow live** | May 6 deploy ~19h | {n_shadow} | Production controller (paper mode) |")
    L.append("| **L25 realfill (full)** | Apr 22 – May 4 | 3597 | Snapshot-precise L25 raw book |")
    L.append("| **L10 backtest (full)** | Apr 22 – May 4 | 3678 | 10s-bucketed L10 book |")
    L.append("")

    L.append("## Cell-level — per-trade distribution comparison\n")
    L.append("Compares mean PnL/trade and hit rate. If shadow $/trade ≈ realfill $/trade, the live "
             "strategy is matching backtest expectations; gaps signal production friction or sample "
             "variance.\n")
    L.append("| Cell | shadow n | sh_hit% | sh $/trade | rf_full n | rf_hit% | rf $/trade | bt_full n | bt_hit% | bt $/trade | Δ (sh−rf) | shadow_total |")
    L.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in df.iterrows():
        sn = r.get("shadow_n"); shit = r.get("shadow_hit"); sm = r.get("shadow_pnl_mean"); spnl = r.get("shadow_pnl_total")
        rn = r.get("rf_full_n"); rhit = r.get("rf_full_hit"); rm = r.get("rf_full_pnl_mean")
        bn = r.get("bt_full_n"); bhit = r.get("bt_full_hit"); bm = r.get("bt_full_pnl_mean")
        delta = (sm - rm) if pd.notna(sm) and pd.notna(rm) else None
        L.append(
            f"| {r['cell']} | "
            f"{int(sn) if pd.notna(sn) else '—'} | {f'{shit*100:.1f}' if pd.notna(shit) else '—'} | "
            f"{f'${sm:+.3f}' if pd.notna(sm) else '—'} | "
            f"{int(rn) if pd.notna(rn) else '—'} | {f'{rhit*100:.1f}' if pd.notna(rhit) else '—'} | "
            f"{f'${rm:+.3f}' if pd.notna(rm) else '—'} | "
            f"{int(bn) if pd.notna(bn) else '—'} | {f'{bhit*100:.1f}' if pd.notna(bhit) else '—'} | "
            f"{f'${bm:+.3f}' if pd.notna(bm) else '—'} | "
            f"{f'${delta:+.3f}' if delta is not None else '—'} | "
            f"{f'${spnl:+.2f}' if pd.notna(spnl) else '—'} |"
        )
    L.append("")

    # Per-asset rollups
    L.append("## Per (asset, tf) — shadow live\n")
    L.append("| Asset_TF | sh_n | sh_total_pnl | sh_$/trade | rf_$/trade | bt_$/trade | "
             "production_extrapolated_30d (sh_total × 30d/19h) |")
    L.append("|---|---:|---:|---:|---:|---:|---:|")
    for asset in ("BTC", "ETH", "SOL"):
        for tf in ("5m", "15m"):
            sub = df[(df["asset"] == asset) & (df["tf"] == tf)]
            if sub.empty:
                continue
            sh_n = sub["shadow_n"].sum() if "shadow_n" in sub.columns else 0
            sh_total = sub["shadow_pnl_total"].sum() if "shadow_pnl_total" in sub.columns else 0
            sh_pt = sh_total / sh_n if sh_n else 0
            rf_pt = (sub["rf_full_pnl_total"].sum() / sub["rf_full_n"].sum()) if sub["rf_full_n"].sum() else 0
            bt_pt = (sub["bt_full_pnl_total"].sum() / sub["bt_full_n"].sum()) if sub["bt_full_n"].sum() else 0
            extrapolated = sh_total * (30 * 24 / 19)  # 30d expected PnL given current rate
            L.append(
                f"| {asset}_{tf} | {int(sh_n)} | ${sh_total:+.2f} | ${sh_pt:+.3f} | "
                f"${rf_pt:+.3f} | ${bt_pt:+.3f} | ${extrapolated:+.2f} |"
            )
    L.append("")

    # Headlines
    sh_total_all = df["shadow_pnl_total"].sum() if "shadow_pnl_total" in df.columns else 0
    sh_n_all = df["shadow_n"].sum() if "shadow_n" in df.columns else 0
    sh_per_trade = sh_total_all / sh_n_all if sh_n_all else 0
    rf_total_all = df["rf_full_pnl_total"].sum() if "rf_full_pnl_total" in df.columns else 0
    rf_n_all = df["rf_full_n"].sum() if "rf_full_n" in df.columns else 0
    rf_per_trade = rf_total_all / rf_n_all if rf_n_all else 0
    bt_total_all = df["bt_full_pnl_total"].sum() if "bt_full_pnl_total" in df.columns else 0
    bt_n_all = df["bt_full_n"].sum() if "bt_full_n" in df.columns else 0
    bt_per_trade = bt_total_all / bt_n_all if bt_n_all else 0

    L.append("## Headline\n")
    L.append(f"- **Shadow live**: {int(sh_n_all)} fires, total ${sh_total_all:+.2f}, "
             f"**${sh_per_trade:+.3f} / trade**")
    L.append(f"- **L25 realfill (Apr-May)**: {int(rf_n_all)} fires, total ${rf_total_all:+.2f}, "
             f"**${rf_per_trade:+.3f} / trade**")
    L.append(f"- **L10 backtest (Apr-May)**: {int(bt_n_all)} fires, total ${bt_total_all:+.2f}, "
             f"**${bt_per_trade:+.3f} / trade**")
    L.append(f"- Per-trade Δ (shadow − realfill): **${sh_per_trade - rf_per_trade:+.3f}**")
    L.append(f"- Per-trade Δ (shadow − backtest):  **${sh_per_trade - bt_per_trade:+.3f}**")
    L.append("")

    L.append("## Interpretation\n")
    L.append("- **Shadow $/trade ≥ realfill $/trade**: production is meeting or beating realfill — strategy is healthy.")
    L.append("- **Shadow $/trade < realfill $/trade by < 30%**: small-sample variance, watch.")
    L.append("- **Shadow $/trade << realfill $/trade**: production friction (slippage, missed fills, "
             "latency, controller cache rot). Investigate per-cell.")
    L.append("- **Shadow hit% < realfill hit%**: likely directional alpha decay or regime shift between "
             "Apr-May backtest period and May 6 live period.\n")

    L.append("## Files\n")
    L.append(f"- 3-way table: `{OUT_CSV.relative_to(ROOT)}`")
    L.append(f"- Shadow: `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv`")
    L.append(f"- L25 realfill: `strategy_lab/results/meta_classifier/momo_realfill_validation.csv`")
    L.append(f"- L10 backtest: `strategy_lab/results/meta_classifier/extended_backtest.csv`")

    OUT_MD.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[md] → {OUT_MD}")


if __name__ == "__main__":
    main()
