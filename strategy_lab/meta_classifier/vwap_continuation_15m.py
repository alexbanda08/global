"""VWAP continuation extended to 15m markets.

Same logic as `vwap_continuation_5m.py` but applied to 15m chainlink-resolved
markets. Fire offsets scaled proportionally: 60, 120, 240, 360, 480, 600, 720,
840 sec into the 15m (900s) slot. dev_bps thresholds same as 5m (5-50bps).
"""
from __future__ import annotations

import math
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

KL1S = ROOT / "data" / "v4" / "canonical" / "klines_1s" / "binance_1s_28d.parquet"
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_15m.csv"
OUT_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_15m_per_fire.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "VWAP_CONTINUATION_15M_2026_05_23.md"

ANCHOR_WINDOW_S = 15 * 60
FIRE_OFFSETS_S = (60, 120, 240, 360, 480, 600, 720, 840)
SLOT_WINDOW_S = 900
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def asof_idx(ts, target_us):
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(ts):
        return -1
    return i


def build_per_asset(df_1s):
    df_1s = df_1s.sort_values(["symbol_id", "time_period_start_us", "source"])
    df_1s = df_1s.drop_duplicates(["symbol_id", "time_period_start_us"], keep="last")
    df_1s["asset"] = df_1s["symbol_id"].map(SYM_MAP)
    out = {}
    for asset in ("BTC", "ETH", "SOL"):
        sub = df_1s[df_1s["asset"] == asset].copy().sort_values("time_period_start_us").reset_index(drop=True)
        ts_us = sub["time_period_start_us"].values.astype("int64")
        close = sub["price_close"].values.astype("float64")
        vol = sub["volume_traded"].fillna(0).values.astype("float64")
        bucket_us = (ts_us // (ANCHOR_WINDOW_S * 1_000_000)) * (ANCHOR_WINDOW_S * 1_000_000)
        tmp = pd.DataFrame({"bucket": bucket_us, "px_vol": close * vol, "vol": vol})
        tmp["cum_px_vol"] = tmp.groupby("bucket")["px_vol"].cumsum()
        tmp["cum_vol"] = tmp.groupby("bucket")["vol"].cumsum()
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = np.where(tmp["cum_vol"].values > 0,
                            tmp["cum_px_vol"].values / tmp["cum_vol"].values, np.nan)
        out[asset] = {"ts_us": ts_us, "close": close, "vwap_15m": vwap}
        print(f"  {asset}: rows={len(ts_us):,}")
    return out


def main():
    print("[1] loading 1s binance...")
    df_1s = pd.read_parquet(KL1S)
    print(f"    {len(df_1s):,} rows")

    print("[2] per-asset VWAP...")
    arrs = build_per_asset(df_1s)
    min_ts = min(arrs[a]["ts_us"][0] for a in arrs)
    max_ts = max(arrs[a]["ts_us"][-1] for a in arrs)

    print("[3] loading 15m chainlink slugs...")
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[(res.asset.isin(("BTC", "ETH", "SOL"))) & (res.tf == "15m")].copy()
    res = res[(res.slot_start_us >= min_ts) & (res.slot_start_us <= max_ts)].copy()
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"] = (res.slot_end_us // 1_000_000).astype("int64")
    print(f"    {len(res):,} 15m slugs")

    print("[4] generating candidates...")
    rows = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = res[res.asset == asset]
        a = arrs[asset]
        for _, r in sub.iterrows():
            slot_start_s = int(r.slot_start_s)
            slot_end_s = int(r.slot_end_s)
            outcome = str(r.outcome)
            slug = r.slug
            for off in FIRE_OFFSETS_S:
                fire_s = slot_start_s + off
                if fire_s >= slot_end_s:
                    continue
                fire_us = fire_s * 1_000_000
                i = asof_idx(a["ts_us"], fire_us)
                if i < 0:
                    continue
                s_now = float(a["close"][i])
                vw = float(a["vwap_15m"][i])
                if not (math.isfinite(s_now) and math.isfinite(vw) and vw > 0):
                    continue
                dev_bps = 10000.0 * math.log(s_now / vw)
                direction = "UP" if dev_bps > 0 else "DOWN"
                rows.append((slug, asset, fire_s, fire_us, off, s_now, vw,
                             dev_bps, direction, outcome, slot_end_s - fire_s))
    cands = pd.DataFrame(rows, columns=[
        "slug", "asset", "fire_s", "fire_us", "fire_offset_s",
        "s_now", "vwap_15m", "dev_bps", "direction", "outcome", "tau_sec",
    ])
    cands = cands[cands.dev_bps.abs() > 5].copy()
    print(f"    {len(cands):,} candidates after |dev|>5bps floor")

    print("[5] loading L25 books...")
    books_idx = {}
    for asset in ("BTC", "ETH", "SOL"):
        slugs_a = set(cands[cands.asset == asset]["slug"].unique())
        if not slugs_a:
            continue
        print(f"    {asset}: {len(slugs_a)} slugs...")
        try:
            ab = load_orderbook_l25_streaming(asset, slugs=slugs_a, subsample_1hz=True)
            books_idx.update(ab)
            print(f"      loaded {len(ab)} keys")
        except Exception as e:
            print(f"      ERROR: {e}")

    print("[6] filling via engine_v2...")
    cfg = LegacyConfig()
    pnl = np.full(len(cands), np.nan)
    won = np.zeros(len(cands), dtype=bool)
    entry = np.full(len(cands), np.nan)
    cands = cands.reset_index(drop=True)
    for i, r in cands.iterrows():
        outcome_to_fill = "Up" if r.direction == "UP" else "Down"
        try:
            f = fill_at_book(books_idx, r.slug, outcome_to_fill, int(r.fire_us),
                             cfg=cfg, spread_filter=SPREAD_FILTER[r.asset])
        except Exception:
            f = None
        if f is None:
            continue
        w = (r.outcome == "Up") if r.direction == "UP" else (r.outcome == "Down")
        pnl[i] = hold_pnl(f, won=w, cfg=cfg)
        won[i] = w
        entry[i] = float(f["vwap"])
    cands["entry_vwap"] = entry
    cands["pnl_legacy_usd"] = pnl
    cands["won"] = won
    filled = cands[cands.pnl_legacy_usd.notna()].copy()
    print(f"    {len(filled):,} / {len(cands):,} fills successful")

    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    filled.to_parquet(OUT_PT, index=False, compression="zstd")

    print("[7] aggregating...")
    bins = [5, 10, 15, 20, 30, 50, 1e9]
    labels = ["5-10bps", "10-15bps", "15-20bps", "20-30bps", "30-50bps", ">50bps"]
    filled["dev_tier"] = pd.cut(filled.dev_bps.abs(), bins=bins, labels=labels)
    g = filled.groupby(["asset", "fire_offset_s", "dev_tier"], observed=True).agg(
        n=("won", "count"), wr=("won", "mean"),
        avg_pnl=("pnl_legacy_usd", "mean"),
        sum_pnl=("pnl_legacy_usd", "sum"),
        avg_entry=("entry_vwap", "mean"),
    ).round(3).reset_index()
    g.to_csv(OUT_CSV, index=False)

    dep = g[(g.n >= 30) & (g.wr >= 0.60) & (g.avg_pnl > 0)].copy().sort_values("sum_pnl", ascending=False)
    print(f"\n--- Deployable (n>=30, WR>=60%, $/tr>0): {len(dep)} configs ---")
    print(dep.head(30).to_string(index=False))

    ultra = g[(g.n >= 100) & (g.wr >= 0.70) & (g.avg_pnl >= 1.0)].copy().sort_values("sum_pnl", ascending=False)
    print(f"\n--- ULTRA-STRICT (n>=100, WR>=70%, $/tr>=$1): {len(ultra)} configs ---")
    print(ultra.head(20).to_string(index=False))

    md = []
    md.append(f"# VWAP continuation — 15m markets ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("Same strategy as `vwap_continuation_5m.py`, applied to 15m markets. Fire offsets 60-840s into 900s slot.")
    md.append("")
    md.append("## Deployable (n>=30, WR>=60%, $/tr > 0)")
    md.append("")
    if len(dep) > 0:
        md.append(dep.head(40).to_markdown(index=False))
    else:
        md.append("NONE")
    md.append("")
    md.append("## Ultra-strict (n>=100, WR>=70%, $/tr>=$1)")
    md.append("")
    if len(ultra) > 0:
        md.append(ultra.head(20).to_markdown(index=False))
    else:
        md.append("NONE")
    md.append("")
    md.append(f"_data: `{OUT_CSV.relative_to(ROOT)}`_  ")
    md.append(f"_per-fire: `{OUT_PT.relative_to(ROOT)}`_")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"Report: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
