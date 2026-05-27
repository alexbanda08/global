"""Standalone MA Ribbon strategy — 5m chainlink-resolved up/down markets.

Strategy:
  At t = slot_start + offset_s (offset ∈ {30,60,...,270}), look up the ribbon
  features for the asset's 1s ta_indicators row at-or-before t. Fire based on
  ribbon state ALONE (no momo / no VWAP dep).

Rules:
  R1 — Pure Color Trend:
        color==1 (lime) & alignment_pct >= 85 → UP
        color==3 (red)  & alignment_pct <= 15 → DOWN

  R2 — Lead vs Ref + Slope:
        lead_vs_ref_bps >  5 & lead_slope_bps > 0 → UP
        lead_vs_ref_bps < -5 & lead_slope_bps < 0 → DOWN

  R3 — Expanded Ribbon Continuation (param THR_EXPAND ∈ {5, 10, 15}):
        compression_bps > THR & color==1 → UP
        compression_bps > THR & color==3 → DOWN

  R4 — Compressed Ribbon Breakout:
        compression_bps < 2 & lead_slope_bps > 0 → UP
        compression_bps < 2 & lead_slope_bps < 0 → DOWN

Fill: engine_v2.LegacyConfig at L25 books, $25 notional, spread_filter per asset.
Hold to slot_end_us. PnL = hold_pnl(fill, won, cfg=legacy).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))
sys.path.insert(0, str(ROOT / "strategy_lab"))

from load import load_resolutions, load_orderbook_l25_streaming  # noqa: E402
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

TA_PARQ = ROOT / "data" / "v4" / "canonical" / "_results" / "ta_indicators_1s.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "ma_ribbon_strategy_5m.csv"
OUT_PT  = ROOT / "data" / "v4" / "canonical" / "_results" / "ma_ribbon_strategy_5m_per_fire.parquet"
OUT_MD  = ROOT / "strategy_lab" / "reports" / "MA_RIBBON_STRATEGY_5M_2026_05_23.md"
S15_PARQ = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"

FIRE_OFFSETS_S = (30, 60, 90, 120, 150, 180, 210, 240, 270)
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}


def asof_idx(ts: np.ndarray, target_us: int) -> int:
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(ts):
        return -1
    return i


def load_ribbon() -> dict:
    """Load ta_indicators_1s.parquet, split by asset, return arrays for fast asof."""
    print("[1] loading ta_indicators_1s...")
    cols = [
        "asset", "ts_us",
        "ribbon_color", "ribbon_alignment_pct", "ribbon_compression_bps",
        "ribbon_lead_slope_bps", "ribbon_lead_vs_ref_bps",
    ]
    df = pd.read_parquet(TA_PARQ, columns=cols)
    print(f"    {len(df):,} rows")
    out = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df[df.asset == asset].sort_values("ts_us").drop_duplicates("ts_us", keep="last")
        sub = sub.reset_index(drop=True)
        out[asset] = {
            "ts_us":            sub["ts_us"].values.astype("int64"),
            "color":            sub["ribbon_color"].values.astype("int8"),
            "alignment_pct":    sub["ribbon_alignment_pct"].values.astype("float32"),
            "compression_bps":  sub["ribbon_compression_bps"].values.astype("float32"),
            "lead_slope_bps":   sub["ribbon_lead_slope_bps"].values.astype("float32"),
            "lead_vs_ref_bps":  sub["ribbon_lead_vs_ref_bps"].values.astype("float32"),
        }
        nfin = int(np.isfinite(out[asset]["alignment_pct"]).sum())
        print(f"  {asset}: 1s rows={len(out[asset]['ts_us']):,}  valid_alignment={nfin:,}")
    return out


def gen_signals(asset_arr: dict, slot_rows: pd.DataFrame) -> list:
    """For each (slug, offset), look up ribbon features and emit one row per
    rule that fires. Returns list of tuples."""
    ts_us = asset_arr["ts_us"]
    color = asset_arr["color"]
    align = asset_arr["alignment_pct"]
    compr = asset_arr["compression_bps"]
    slope = asset_arr["lead_slope_bps"]
    leadr = asset_arr["lead_vs_ref_bps"]
    rows = []
    for _, r in slot_rows.iterrows():
        slot_start_s = int(r.slot_start_s)
        slot_end_s   = int(r.slot_end_s)
        outcome      = str(r.outcome)
        slug         = r.slug
        asset        = r.asset
        for off in FIRE_OFFSETS_S:
            fire_s = slot_start_s + off
            if fire_s >= slot_end_s:
                continue
            fire_us = fire_s * 1_000_000
            i = asof_idx(ts_us, fire_us)
            if i < 0:
                continue
            c  = int(color[i])
            al = float(align[i])
            cp = float(compr[i])
            sl = float(slope[i])
            lr = float(leadr[i])
            if not (np.isfinite(al) and np.isfinite(cp) and np.isfinite(sl) and np.isfinite(lr)):
                continue
            tau = slot_end_s - fire_s

            # R1 — pure color trend
            if c == 1 and al >= 85:
                rows.append((slug, asset, fire_s, fire_us, off, "R1", "default",
                             c, al, cp, sl, lr, "UP", outcome, tau))
            elif c == 3 and al <= 15:
                rows.append((slug, asset, fire_s, fire_us, off, "R1", "default",
                             c, al, cp, sl, lr, "DOWN", outcome, tau))

            # R2 — lead vs ref + slope
            if lr > 5 and sl > 0:
                rows.append((slug, asset, fire_s, fire_us, off, "R2", "default",
                             c, al, cp, sl, lr, "UP", outcome, tau))
            elif lr < -5 and sl < 0:
                rows.append((slug, asset, fire_s, fire_us, off, "R2", "default",
                             c, al, cp, sl, lr, "DOWN", outcome, tau))

            # R3 — expanded ribbon continuation, sweep THR ∈ {5,10,15}
            for thr in (5, 10, 15):
                if cp > thr and c == 1:
                    rows.append((slug, asset, fire_s, fire_us, off, "R3", f"thr{thr}",
                                 c, al, cp, sl, lr, "UP", outcome, tau))
                elif cp > thr and c == 3:
                    rows.append((slug, asset, fire_s, fire_us, off, "R3", f"thr{thr}",
                                 c, al, cp, sl, lr, "DOWN", outcome, tau))

            # R4 — compressed breakout
            if cp < 2 and sl > 0:
                rows.append((slug, asset, fire_s, fire_us, off, "R4", "default",
                             c, al, cp, sl, lr, "UP", outcome, tau))
            elif cp < 2 and sl < 0:
                rows.append((slug, asset, fire_s, fire_us, off, "R4", "default",
                             c, al, cp, sl, lr, "DOWN", outcome, tau))
    return rows


def main() -> int:
    asset_arrs = load_ribbon()
    min_ts = min(asset_arrs[a]["ts_us"][0]  for a in asset_arrs)
    max_ts = max(asset_arrs[a]["ts_us"][-1] for a in asset_arrs)

    print("[2] loading 5m chainlink resolutions...")
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[(res.asset.isin(("BTC", "ETH", "SOL"))) & (res.tf == "5m")].copy()
    res = res[(res.slot_start_us >= min_ts) & (res.slot_start_us <= max_ts)].copy()
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"]   = (res.slot_end_us   // 1_000_000).astype("int64")
    print(f"    {len(res):,} 5m slugs in TA window")

    print("[3] generating ribbon signals (4 rules × 9 offsets)...")
    all_rows = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = res[res.asset == asset]
        rows = gen_signals(asset_arrs[asset], sub)
        all_rows.extend(rows)
        print(f"  {asset}: {len(rows):,} signal-fires across all rules")
    cols = ["slug", "asset", "fire_s", "fire_us", "fire_offset_s", "rule", "param",
            "color", "alignment_pct", "compression_bps", "lead_slope_bps", "lead_vs_ref_bps",
            "direction", "outcome", "tau_sec"]
    cands = pd.DataFrame(all_rows, columns=cols)
    print(f"  total signal-fires: {len(cands):,}")
    print("  by (rule, asset):")
    print(cands.groupby(["rule", "asset"]).size().to_string())

    if cands.empty:
        print("NO SIGNAL FIRES — exit")
        return 1

    # Load L25 books per asset (only for slugs we'll need)
    print("[4] loading L25 books per asset (1Hz subsample)...")
    books_idx: dict = {}
    for asset in ("BTC", "ETH", "SOL"):
        slugs_asset = set(cands[cands.asset == asset]["slug"].unique())
        if not slugs_asset:
            continue
        print(f"  {asset}: loading {len(slugs_asset):,} slugs...")
        try:
            ab = load_orderbook_l25_streaming(asset, slugs=slugs_asset, subsample_1hz=True)
            books_idx.update(ab)
            print(f"      loaded {len(ab):,} (slug, outcome) keys")
        except Exception as e:
            print(f"      [ERROR] {asset}: {e}")
    print(f"  total books_idx keys: {len(books_idx):,}")

    # Distinct (slug, fire_us, direction) — many rules will share the same
    # actual market trade. Fill once per distinct entry, then merge back.
    print("[5] de-duplicating to (slug, fire_us, direction) fill keys...")
    cfg = LegacyConfig()
    fill_keys = cands[["slug", "asset", "fire_us", "direction", "outcome"]].drop_duplicates()
    fill_keys = fill_keys.reset_index(drop=True)
    print(f"  {len(fill_keys):,} distinct fills")

    print("[6] running L25 fills via engine_v2.LegacyConfig...")
    entry_vwap = np.full(len(fill_keys), np.nan)
    pnl_arr    = np.full(len(fill_keys), np.nan)
    won_arr    = np.zeros(len(fill_keys), dtype=bool)
    for idx, r in fill_keys.iterrows():
        outcome_to_fill = "Up" if r.direction == "UP" else "Down"
        try:
            fill = fill_at_book(
                books_idx, r.slug, outcome_to_fill, int(r.fire_us),
                cfg=cfg, spread_filter=SPREAD_FILTER[r.asset],
            )
        except Exception:
            fill = None
        if fill is None:
            continue
        won = (r.outcome == "Up") if r.direction == "UP" else (r.outcome == "Down")
        pnl = hold_pnl(fill, won=won, cfg=cfg)
        entry_vwap[idx] = float(fill["vwap"])
        pnl_arr[idx]    = float(pnl)
        won_arr[idx]    = bool(won)
        if (idx + 1) % 5000 == 0:
            print(f"    {idx+1:,}/{len(fill_keys):,}")
    fill_keys["entry_vwap"]     = entry_vwap
    fill_keys["pnl_legacy_usd"] = pnl_arr
    fill_keys["won"]            = won_arr
    print(f"  filled: {int(np.isfinite(pnl_arr).sum()):,}/{len(fill_keys):,}")

    # Merge back into cands
    cands = cands.merge(
        fill_keys[["slug", "fire_us", "direction", "entry_vwap", "pnl_legacy_usd", "won"]],
        on=["slug", "fire_us", "direction"], how="left",
    )
    filled = cands[cands.pnl_legacy_usd.notna()].copy()
    print(f"  filled signal-fires: {len(filled):,}")

    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    filled.to_parquet(OUT_PT, index=False, compression="zstd")
    print(f"  wrote {OUT_PT}")

    # Aggregate per (rule, param, asset, fire_offset_s, direction)
    print("[7] aggregating per (rule, param, asset, offset, direction)...")
    g = filled.groupby(["rule", "param", "asset", "fire_offset_s", "direction"], observed=True).agg(
        n=("won", "count"),
        wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
        avg_entry=("entry_vwap", "mean"),
    ).round(4).reset_index()
    g = g.sort_values(["rule", "param", "asset", "fire_offset_s", "direction"]).reset_index(drop=True)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    g.to_csv(OUT_CSV, index=False)
    print(f"  wrote {OUT_CSV}")

    # Also aggregate per (rule, param, asset, offset) — agnostic to direction
    g_da = filled.groupby(["rule", "param", "asset", "fire_offset_s"], observed=True).agg(
        n=("won", "count"),
        wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).round(4).reset_index()
    g_da = g_da.sort_values(["rule", "param", "asset", "fire_offset_s"]).reset_index(drop=True)

    # And per (rule, param) alone
    g_r = filled.groupby(["rule", "param"], observed=True).agg(
        n=("won", "count"),
        wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
    ).round(4).reset_index().sort_values("avg_pnl", ascending=False)

    # Headline: any deployable?
    deploy_da = g_da[(g_da.n >= 30) & (g_da.wr >= 0.60) & (g_da.avg_pnl > 0)].copy()
    deploy_da = deploy_da.sort_values("avg_pnl", ascending=False)
    deploy_dir = g[(g.n >= 30) & (g.wr >= 0.60) & (g.avg_pnl > 0)].copy()
    deploy_dir = deploy_dir.sort_values("avg_pnl", ascending=False)

    # Overlap analysis with S1.5 (VWAP continuation 5m)
    print("[8] overlap with S1.5 (vwap_continuation_5m)...")
    overlap_md = ""
    try:
        s15 = pd.read_parquet(S15_PARQ)
        # S1.5 fires are slugs where dev_bps > thr → bet
        # Compute overlap on the (slug, fire_us, direction) level
        s15_keys = s15[["slug", "fire_us", "direction"]].drop_duplicates()
        s15_keys["s15_fires"] = 1
        my = filled[["slug", "fire_us", "direction", "rule", "param"]]
        joined = my.merge(s15_keys, on=["slug", "fire_us", "direction"], how="left")
        # Per rule: fraction overlapping with S1.5
        ov = joined.groupby(["rule", "param"]).agg(
            n_ribbon=("rule", "size"),
            n_overlap_s15=("s15_fires", "sum"),
        ).reset_index()
        ov["overlap_pct"] = (ov.n_overlap_s15 / ov.n_ribbon * 100).round(1)
        print(ov.to_string(index=False))
        overlap_md = ov.to_markdown(index=False)
    except Exception as e:
        print(f"  [overlap ERROR] {e}")
        overlap_md = f"_overlap unavailable: {e}_"

    # Headline
    print("\n=== HEADLINE ===")
    print(f"Total filled signal-fires: {len(filled):,}")
    print(f"Deployable (n>=30, WR>=60%, avg_pnl>0) — by (rule,param,asset,offset): {len(deploy_da)}")
    print(f"Deployable (n>=30, WR>=60%, avg_pnl>0) — by (rule,param,asset,offset,direction): {len(deploy_dir)}")
    print("\n--- per-rule headline (all data combined) ---")
    print(g_r.to_string(index=False))
    if len(deploy_da) > 0:
        print("\n--- TOP 10 (rule,param,asset,offset) deployable configs ---")
        print(deploy_da.head(10).to_string(index=False))

    # Markdown report
    md = []
    md.append(f"# MA Ribbon strategy — 5m markets ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("## Setup")
    md.append("")
    md.append("Standalone MA Ribbon strategy on 5m chainlink-resolved crypto up/down markets.")
    md.append("At t = slot_start + offset_s for offset ∈ {30,60,...,270}, look up the ribbon")
    md.append("features (color, alignment_pct, compression_bps, lead_slope_bps, lead_vs_ref_bps)")
    md.append("at the 1s `ta_indicators_1s.parquet` row at-or-before t, and fire based on rules R1–R4.")
    md.append("")
    md.append("Fills: `engine_v2.LegacyConfig` (2%-on-profit fee), $25 notional, L25 book walk.")
    md.append("Spread filter: BTC 0.02, ETH 0.02, SOL 0.025.")
    md.append("")
    md.append("**Rules tested:**")
    md.append("- R1 — color==1 & alignment>=85 → UP / color==3 & alignment<=15 → DOWN")
    md.append("- R2 — lead_vs_ref>5 & slope>0 → UP / lead_vs_ref<-5 & slope<0 → DOWN")
    md.append("- R3 — compression>THR & color==1 → UP / color==3 → DOWN (THR ∈ {5,10,15})")
    md.append("- R4 — compression<2 & slope>0 → UP / slope<0 → DOWN")
    md.append("")
    md.append("## Headline")
    md.append("")
    n_dep = len(deploy_da)
    if n_dep == 0:
        md.append("**Does the standalone MA Ribbon strategy work?  → NO.**")
        md.append("")
        md.append(f"Zero (rule,param,asset,offset) cells with n≥30, WR≥60%, avg_pnl>0.")
    else:
        md.append(f"**Does the standalone MA Ribbon strategy work?  → YES (conditionally).**")
        md.append("")
        md.append(f"{n_dep} (rule,param,asset,offset) cells with n≥30, WR≥60%, avg_pnl>0.")
    md.append("")
    md.append(f"Total signal-fires (after gen): {len(cands):,}; filled (L25): {len(filled):,}")
    md.append("")
    md.append("## Per-rule headline (all assets, offsets, directions)")
    md.append("")
    md.append(g_r.to_markdown(index=False))
    md.append("")
    md.append("## Top 10 deployable configs (n≥30, WR≥60%, avg_pnl>0)")
    md.append("")
    if n_dep == 0:
        md.append("_None._")
    else:
        md.append(deploy_da.head(10).to_markdown(index=False))
    md.append("")
    md.append("## Top 10 deployable configs (with direction)")
    md.append("")
    if len(deploy_dir) == 0:
        md.append("_None._")
    else:
        md.append(deploy_dir.head(10).to_markdown(index=False))
    md.append("")
    md.append("## All (n≥30) configs by avg_pnl (top 40)")
    md.append("")
    md.append(g_da[g_da.n >= 30].sort_values("avg_pnl", ascending=False).head(40).to_markdown(index=False))
    md.append("")
    md.append("## Overlap with S1.5 (VWAP continuation 5m)")
    md.append("")
    md.append("Fraction of MA-Ribbon fires that also appear in S1.5's `vwap_continuation_5m_per_fire.parquet`")
    md.append("(matched on slug + fire_us + direction).")
    md.append("")
    md.append(overlap_md)
    md.append("")
    md.append(f"_data: `{OUT_CSV.relative_to(ROOT)}`_  ")
    md.append(f"_per-fire parquet: `{OUT_PT.relative_to(ROOT)}`_  ")
    md.append(f"_script: `strategy_lab/meta_classifier/ma_ribbon_strategy_5m.py`_")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
