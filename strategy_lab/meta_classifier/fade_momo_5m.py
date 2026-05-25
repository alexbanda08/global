"""Fade-momo 5m study.

Hypothesis: when momo's |ret_2m| is extreme (mag_ratio >> 1), the move is
exhaustion. Fade the signal (buy opposite token) → fade WR ≈ 100% − momo WR.

Inputs:
  - per_trade_markov.parquet (Baseline_v1+v2, 5m only, with mpass+rsi columns)
  - L25 books via canonical/load.py (asset-batched)

Outputs:
  - data/v4/canonical/_results/fade_momo_5m.csv (per-(asset, threshold, gate))
  - strategy_lab/reports/FADE_MOMO_5M_2026_05_23.md
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:/Users/alexandre bandarra/Desktop/global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402
from load import load_orderbook_l25_streaming  # noqa: E402


PER_TRADE = ROOT / "data" / "v4" / "canonical" / "_results" / "momo_variants_2abc_2026_05_20" / "per_trade_markov.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "fade_momo_5m.csv"
OUT_REPORT = ROOT / "strategy_lab" / "reports" / "FADE_MOMO_5M_2026_05_23.md"

SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}
NOTIONAL = 25.0  # match engine default; sleeve uses 25 USD
MAG_THRESHOLDS = [1.5, 2.0, 2.5, 3.0]
ASSETS = ["BTC", "ETH", "SOL"]


def load_fires() -> pd.DataFrame:
    print("[1] load per_trade_markov.parquet", flush=True)
    df = pd.read_parquet(PER_TRADE)
    df = df[(df.variant.isin(["Baseline_v1", "Baseline_v2"])) & (df.tf == "5m")].copy()
    df["mag_ratio"] = df["ret_2m"].abs() / df["threshold"]
    # Fade-side definitions:
    df["fade_signal"] = np.where(df["signal"] == "UP", "DOWN", "UP")
    df["fade_outcome_to_fill"] = np.where(df["fade_signal"] == "DOWN", "Down", "Up")
    df["fade_won"] = np.where(
        df["fade_signal"] == "DOWN",
        df["outcome"] == "Down",
        df["outcome"] == "Up",
    )
    # Original (momo) won, for direct comparison.
    df["fwd_won"] = df["won"].astype(bool)
    # Gate semantics (gates contradict ORIGINAL momo signal):
    df["gate_f7_contra"] = (
        ((df["signal"] == "UP") & (df["rsi_14"] < 50.0))
        | ((df["signal"] == "DOWN") & (df["rsi_14"] > 50.0))
    )
    # M1V regime: 0=Bear, 1=Neutral, 2=Bull.
    rg = df["regime_w20_1m_voladaptive"]
    df["gate_m1v_contra"] = (
        ((df["signal"] == "UP") & (rg == 0))
        | ((df["signal"] == "DOWN") & (rg == 2))
    )
    # mpass_w20_1m_voladaptive: True if regime AGREES with original signal.
    # Inverted: False → regime disagrees → consider fade.
    df["gate_mpass_contra"] = ~df["mpass_w20_1m_voladaptive"].astype(bool)
    print(f"    fires: {len(df)}  by asset: {df.groupby('asset').size().to_dict()}", flush=True)
    return df


def fill_one_asset(df_asset: pd.DataFrame, asset: str, cfg) -> pd.DataFrame:
    """For all fires in df_asset, run fade fill_at_book + hold_pnl.

    Returns df_asset with new cols: fade_fill_ok, fade_pnl_legacy_usd, fade_entry_vwap.
    """
    if df_asset.empty:
        return df_asset
    slugs = set(df_asset["slug"].unique().tolist())
    print(f"  [{asset}] load L25 streaming for {len(slugs)} slugs ...", flush=True)
    t0 = time.time()
    # Bound time window: min/max fire_s gives us a tight ts window.
    fire_us_arr = df_asset["fire_s"].astype("int64").to_numpy() * 1_000_000
    min_ts = int(fire_us_arr.min()) - 60_000_000  # 60s pad before
    max_ts = int(fire_us_arr.max()) + 30_000_000  # 30s pad after (fade is taker, no exit lookup)
    books = load_orderbook_l25_streaming(
        asset.lower(), slugs=slugs, subsample_1hz=True,
        min_ts_us=min_ts, max_ts_us=max_ts,
    )
    print(f"  [{asset}] L25 loaded: {len(books)} streams in {time.time()-t0:.1f}s", flush=True)
    spread = SPREAD_FILTER[asset]
    rows = []
    n_filled = 0
    n_total = 0
    for r in df_asset.itertuples(index=False):
        n_total += 1
        fire_us = int(r.fire_s) * 1_000_000
        fill = fill_at_book(
            books, r.slug, outcome=r.fade_outcome_to_fill,
            fire_us=fire_us, cfg=cfg, notional_usd=NOTIONAL,
            spread_filter=spread,
        )
        if fill is None:
            rows.append((False, float("nan"), float("nan"), float("nan")))
            continue
        pnl = hold_pnl(fill, won=bool(r.fade_won), cfg=cfg)
        rows.append((True, float(pnl), float(fill["vwap"]), float(fill["shares"])))
        n_filled += 1
    print(f"  [{asset}] filled {n_filled}/{n_total} ({100*n_filled/max(n_total,1):.1f}%)", flush=True)
    df2 = df_asset.copy()
    df2["fade_fill_ok"], df2["fade_pnl_legacy_usd"], df2["fade_entry_vwap"], df2["fade_shares"] = zip(*rows)
    return df2


def summarize_cell(sub: pd.DataFrame, key: dict) -> dict:
    f = sub[sub["fade_fill_ok"]].copy()
    n = int(len(f))
    if n == 0:
        return {**key, "n": 0, "n_filled": 0, "wr": float("nan"),
                "mean_pnl_usd": float("nan"), "sum_pnl_usd": 0.0,
                "max_consec_loss_usd": 0.0,
                "fwd_wr_same_cell": float("nan"),
                "fwd_n_same_cell": int(len(sub))}
    pnl = f["fade_pnl_legacy_usd"].to_numpy(dtype=np.float64)
    wins = f["fade_won"].astype(bool).to_numpy()
    # Max consecutive loss: running sum drawdown of pnl in fire order (sorted by fire_s).
    order = f.sort_values("fire_s")
    cum = order["fade_pnl_legacy_usd"].cumsum().to_numpy()
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    max_dd = float(dd.min()) if len(dd) else 0.0
    # Forward WR comparison in same cell.
    fwd_wr = float(sub["fwd_won"].mean())
    return {
        **key,
        "n": n,
        "n_filled": n,
        "wr": float(wins.mean()),
        "mean_pnl_usd": float(pnl.mean()),
        "sum_pnl_usd": float(pnl.sum()),
        "max_consec_loss_usd": max_dd,
        "fwd_wr_same_cell": fwd_wr,
        "fwd_n_same_cell": int(len(sub)),
    }


def run():
    cfg = LegacyConfig()
    df = load_fires()

    # Run fill_at_book ONCE per asset over the union of fires we'll use.
    # (mag_ratio>1.5 covers all thresholds; smaller filters in summary phase.)
    big_mask = df["mag_ratio"] > 1.5
    print(f"[2] universe for L25 fills (mag_ratio>1.5): n={int(big_mask.sum())}", flush=True)

    filled_parts = []
    for asset in ASSETS:
        sub = df[big_mask & (df["asset"] == asset)]
        if sub.empty:
            print(f"  [{asset}] empty after threshold filter, skipping", flush=True)
            continue
        df_with = fill_one_asset(sub, asset, cfg)
        filled_parts.append(df_with)
    if not filled_parts:
        print("[fatal] no fills computed", flush=True)
        return

    filled = pd.concat(filled_parts, ignore_index=True)
    print(f"[3] fills computed: total rows={len(filled)} filled={int(filled['fade_fill_ok'].sum())}", flush=True)

    # ---- Build per-cell summaries ----
    summaries = []

    # Baseline (no gate): per (asset, mag_threshold)
    for asset in ASSETS:
        for mt in MAG_THRESHOLDS:
            sub = filled[(filled.asset == asset) & (filled.mag_ratio > mt)]
            summaries.append(summarize_cell(sub, {
                "asset": asset, "mag_threshold": mt, "gate": "none",
            }))
        # All-assets pooled for context
    for mt in MAG_THRESHOLDS:
        sub = filled[filled.mag_ratio > mt]
        summaries.append(summarize_cell(sub, {
            "asset": "ALL", "mag_threshold": mt, "gate": "none",
        }))

    # With gates (each gate AND fade) — keep mag_ratio>1.5 as base (most fires)
    GATES = ["gate_f7_contra", "gate_m1v_contra", "gate_mpass_contra"]
    for asset in ASSETS:
        for mt in MAG_THRESHOLDS:
            for g in GATES:
                sub = filled[(filled.asset == asset) & (filled.mag_ratio > mt) & (filled[g])]
                summaries.append(summarize_cell(sub, {
                    "asset": asset, "mag_threshold": mt, "gate": g,
                }))
    for mt in MAG_THRESHOLDS:
        for g in GATES:
            sub = filled[(filled.mag_ratio > mt) & (filled[g])]
            summaries.append(summarize_cell(sub, {
                "asset": "ALL", "mag_threshold": mt, "gate": g,
            }))

    # Stacked gate: f7_contra AND mpass_contra (strongest "both disagree" signal)
    for asset in ASSETS + ["ALL"]:
        for mt in MAG_THRESHOLDS:
            base = filled if asset == "ALL" else filled[filled.asset == asset]
            sub = base[(base.mag_ratio > mt) & (base.gate_f7_contra) & (base.gate_mpass_contra)]
            summaries.append(summarize_cell(sub, {
                "asset": asset, "mag_threshold": mt, "gate": "f7+mpass_contra",
            }))

    summary = pd.DataFrame(summaries)
    summary["deployable"] = (summary["wr"] >= 0.60) & (summary["n"] >= 30)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT_CSV, index=False)
    print(f"[4] wrote {OUT_CSV} ({len(summary)} rows)", flush=True)
    print(f"[5] deployable cells: {int(summary['deployable'].sum())}", flush=True)

    # ---- Build the markdown report ----
    write_report(filled, summary)
    print(f"[6] wrote {OUT_REPORT}", flush=True)


def _fmt_pct(x):
    return f"{100*x:5.1f}%" if isinstance(x, float) and not np.isnan(x) else "  n/a"


def _fmt_usd(x):
    if isinstance(x, float) and np.isnan(x):
        return "   n/a"
    return f"{x:+7.3f}"


def write_report(filled: pd.DataFrame, summary: pd.DataFrame):
    OUT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    L = lines.append

    L("# FADE-MOMO 5m study — 2026-05-23\n")
    L("**Hypothesis**: when momo's |ret_2m| is extreme (mag_ratio >> 1), the")
    L("move is exhausted. FADE the signal (buy opposite token) → fade WR ≈ 100%")
    L("− momo WR. Confirm or refute on Baseline_v1+v2 5m fires using L25 book")
    L("walks, LegacyConfig (2%-on-profit), $25 notional, spread filters")
    L("BTC/ETH 0.02 SOL 0.025.\n")
    L("Data window: same as per_trade_markov (Apr 24 → May 21 ~28d). Fires used:")
    L(f"all Baseline_v1+v2 5m fires with mag_ratio>1.5 — pre-fill n={len(filled)},")
    L(f"post-fill n={int(filled['fade_fill_ok'].sum())} ({100*filled['fade_fill_ok'].mean():.1f}% fill rate).")
    L("\n---\n")

    # Headline
    dep = summary[summary["deployable"]].sort_values(["wr", "n"], ascending=[False, False])
    if dep.empty:
        L("## Headline: NONE deployable\n")
        L("No (asset, mag_threshold, gate) cell achieves WR ≥ 60% AND n ≥ 30")
        L("after proper opposite-side L25 fills + spread filter.\n")
    else:
        L("## Headline: DEPLOYABLE cells\n")
        L("| asset | mag>x | gate | n | WR | $/tr | sum$ | max_dd$ | fwd_WR_same_cell |")
        L("|---|---|---|---:|---:|---:|---:|---:|---:|")
        for r in dep.itertuples(index=False):
            L(f"| {r.asset} | {r.mag_threshold} | {r.gate} | {r.n} | {_fmt_pct(r.wr)} "
              f"| {_fmt_usd(r.mean_pnl_usd)} | {_fmt_usd(r.sum_pnl_usd)} "
              f"| {_fmt_usd(r.max_consec_loss_usd)} | {_fmt_pct(r.fwd_wr_same_cell)} |")
        L("")

    # Baseline (no gate) by asset
    L("\n## Baseline fade (no gate)\n")
    L("Fade WR vs forward momo WR (same fires, same cell).\n")
    L("| asset | mag>x | n | fade_WR | fwd_WR | fade $/tr | fade sum$ | max_dd$ |")
    L("|---|---|---:|---:|---:|---:|---:|---:|")
    base = summary[summary.gate == "none"].sort_values(["asset", "mag_threshold"])
    for r in base.itertuples(index=False):
        L(f"| {r.asset} | {r.mag_threshold} | {r.n} | {_fmt_pct(r.wr)} | "
          f"{_fmt_pct(r.fwd_wr_same_cell)} | {_fmt_usd(r.mean_pnl_usd)} | "
          f"{_fmt_usd(r.sum_pnl_usd)} | {_fmt_usd(r.max_consec_loss_usd)} |")

    # Per-gate extension
    L("\n## Fade + gate extensions\n")
    L("Each gate adds an AND filter that the gate's signal CONTRADICTS the original momo direction.\n")
    L("| asset | mag>x | gate | n | fade_WR | fwd_WR | $/tr | sum$ | max_dd$ |")
    L("|---|---|---|---:|---:|---:|---:|---:|---:|")
    gated = summary[summary.gate != "none"].sort_values(["asset", "mag_threshold", "gate"])
    for r in gated.itertuples(index=False):
        L(f"| {r.asset} | {r.mag_threshold} | {r.gate} | {r.n} | {_fmt_pct(r.wr)} "
          f"| {_fmt_pct(r.fwd_wr_same_cell)} | {_fmt_usd(r.mean_pnl_usd)} | "
          f"{_fmt_usd(r.sum_pnl_usd)} | {_fmt_usd(r.max_consec_loss_usd)} |")

    # Direct comparison at the exact tiers in the brief
    L("\n## Forward vs Fade WR by mag_ratio tier (pooled BTC/ETH/SOL)\n")
    bins = [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 5.0), (5.0, 100.0)]
    L("| tier | n (filled) | fwd_WR | fade_WR | sum_fade$ | mean_fade$ |")
    L("|---|---:|---:|---:|---:|---:|")
    for lo, hi in bins:
        sub = filled[(filled.mag_ratio > lo) & (filled.mag_ratio <= hi) & filled.fade_fill_ok]
        if sub.empty:
            L(f"| ({lo}, {hi}] | 0 | n/a | n/a | n/a | n/a |")
            continue
        fwd_wr = float(sub.fwd_won.mean())
        fade_wr = float(sub.fade_won.mean())
        sm = float(sub.fade_pnl_legacy_usd.sum())
        mn = float(sub.fade_pnl_legacy_usd.mean())
        L(f"| ({lo}, {hi}] | {len(sub)} | {_fmt_pct(fwd_wr)} | {_fmt_pct(fade_wr)} | "
          f"{_fmt_usd(sm)} | {_fmt_usd(mn)} |")

    L("\n## Sample size notes\n")
    small_cells = summary[(summary.gate != "none") & (summary.n > 0) & (summary.n < 100)]
    if not small_cells.empty:
        L(f"- {len(small_cells)} gated cells have n<100; treat WR as suggestive only.")
    big_dep = summary[(summary.deployable) & (summary.n >= 100)]
    L(f"- {len(big_dep)} cells meet both WR≥60% AND n≥100 (robust deployable).")
    L("- Universe pre-fill ~3,456 fires (Baseline_v1+v2, 5m). With mag_ratio>1.5")
    L(f"  filter and L25 fill: {int(filled['fade_fill_ok'].sum())} filled fires available.\n")

    L("---\n")
    L("**Files**:")
    L(f"- Per-cell CSV: `{OUT_CSV.relative_to(ROOT).as_posix()}`")
    L(f"- Script: `strategy_lab/meta_classifier/fade_momo_5m.py`")
    L(f"- Engine: LegacyConfig (2%-on-profit, matches production shadow PnL)")
    L(f"- Fill primitive: `engine_v2.fill_at_book` + `hold_pnl` with $25 notional\n")

    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    run()
