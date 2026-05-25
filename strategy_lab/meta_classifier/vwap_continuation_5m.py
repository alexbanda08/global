"""Late-fire VWAP momentum continuation — proper L25 fills.

INVERTED from the v1 fade test: the v1 found that betting AGAINST a binance
VWAP extension is wrong (WR 7-22%); betting WITH the extension hits WR
78-96% on outcome basis. v2 uses real engine_v2.fill_at_book to get the
actual entry vwap, computes $/tr.

Strategy:
  At t = ws_s + fire_offset (offset ∈ {30, 60, 90, 120, 150, 180, 210, 240, 270} sec):
    Compute dev_bps = 10_000 · log(binance_close_now / VWAP_15m_anchored).
    If dev_bps > +thr → bet UP (momentum continues UP). thr ∈ {5,10,15,20,30,50}.
    If dev_bps < -thr → bet DOWN.

Output:
  data/v4/canonical/_results/vwap_continuation_5m.csv
  strategy_lab/reports/VWAP_CONTINUATION_5M_2026_05_23.md
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
OUT_CSV = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m.csv"
OUT_PT = ROOT / "data" / "v4" / "canonical" / "_results" / "vwap_continuation_5m_per_fire.parquet"
OUT_MD = ROOT / "strategy_lab" / "reports" / "VWAP_CONTINUATION_5M_2026_05_23.md"

ANCHOR_WINDOW_S = 15 * 60
FIRE_OFFSETS_S = (30, 60, 90, 120, 150, 180, 210, 240, 270)
SLOT_WINDOW_S = 300
THRESHES_BPS = (5, 10, 15, 20, 30, 50)
SPREAD_FILTER = {"BTC": 0.02, "ETH": 0.02, "SOL": 0.025}

SYM_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def asof_idx(ts: np.ndarray, target_us: int) -> int:
    i = int(np.searchsorted(ts, target_us, side="right")) - 1
    if i < 0 or i >= len(ts):
        return -1
    return i


def build_per_asset(df_1s: pd.DataFrame) -> dict:
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
                            tmp["cum_px_vol"].values / tmp["cum_vol"].values,
                            np.nan)
        log_close = np.log(np.where(close > 0, close, np.nan))
        log_ret = np.diff(log_close, prepend=np.nan)
        sigma_per_sqrt_sec = pd.Series(log_ret).rolling(900, min_periods=300).std().values

        out[asset] = {
            "ts_us": ts_us, "close": close,
            "vwap_15m": vwap, "sigma_per_sqrt_sec": sigma_per_sqrt_sec,
        }
        print(f"  {asset}: 1s rows={len(ts_us):,}  valid VWAP={int(np.isfinite(vwap).sum()):,}")
    return out


def main() -> int:
    print("[1] loading 1s binance...")
    df_1s = pd.read_parquet(KL1S)
    print(f"    {len(df_1s):,} rows")

    print("[2] building per-asset VWAP + sigma...")
    arrs = build_per_asset(df_1s)
    min_ts = min(arrs[a]["ts_us"][0] for a in arrs)
    max_ts = max(arrs[a]["ts_us"][-1] for a in arrs)

    print("[3] loading 5m chainlink resolutions...")
    res = load_resolutions()
    res = res.rename(columns={"ticker": "asset", "timeframe": "tf"})
    res = res[(res.asset.isin(("BTC", "ETH", "SOL"))) & (res.tf == "5m")].copy()
    res = res[(res.slot_start_us >= min_ts) & (res.slot_start_us <= max_ts)].copy()
    res["slot_start_s"] = (res.slot_start_us // 1_000_000).astype("int64")
    res["slot_end_s"] = (res.slot_end_us // 1_000_000).astype("int64")
    print(f"    {len(res):,} 5m slugs")

    # Generate candidates per (slug, offset, thr). Bet WITH extension.
    print("[4] generating candidates...")
    rows = []
    for asset in ("BTC", "ETH", "SOL"):
        sub = res[res.asset == asset]
        a = arrs[asset]
        ts_us = a["ts_us"]
        close = a["close"]
        vwap_15m = a["vwap_15m"]
        sigma = a["sigma_per_sqrt_sec"]
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
                i = asof_idx(ts_us, fire_us)
                if i < 0:
                    continue
                s_now = float(close[i])
                vw = float(vwap_15m[i])
                sig = float(sigma[i])
                if not (math.isfinite(s_now) and math.isfinite(vw) and vw > 0):
                    continue
                dev_bps = 10000.0 * math.log(s_now / vw)
                # Pick the maximum threshold this fire qualifies under (inclusive)
                # so each fire is recorded once per direction with its tier.
                if dev_bps > 0:
                    direction = "UP"  # bet UP (momentum continues)
                else:
                    direction = "DOWN"
                rows.append((slug, asset, fire_s, fire_us, off, s_now, vw, sig,
                             dev_bps, direction, outcome, slot_end_s - fire_s))
    cands = pd.DataFrame(rows, columns=[
        "slug", "asset", "fire_s", "fire_us", "fire_offset_s",
        "s_now", "vwap_15m", "sigma_per_sqrt_sec", "dev_bps",
        "direction", "outcome", "tau_sec",
    ])
    print(f"    {len(cands):,} candidate fires (dev_bps != 0)")
    print(f"    by direction × asset × offset distribution:")
    print(cands.groupby(["asset", "direction"]).size().to_string())

    # Filter to the qualifying fires (|dev_bps| > 5bps as global floor)
    cands = cands[cands.dev_bps.abs() > 5].copy()
    print(f"    {len(cands):,} after |dev_bps|>5 floor")

    # Load L25 books per asset, only for slugs we care about.
    print("[5] loading L25 books per asset (1Hz subsample)...")
    books_idx: dict = {}
    for asset in ("BTC", "ETH", "SOL"):
        slugs_asset = set(cands[cands.asset == asset]["slug"].unique())
        if not slugs_asset:
            continue
        print(f"    {asset}: loading {len(slugs_asset):,} slugs...")
        try:
            asset_books = load_orderbook_l25_streaming(asset, slugs=slugs_asset, subsample_1hz=True)
            books_idx.update(asset_books)
            print(f"      loaded {len(asset_books):,} (slug, outcome) keys")
        except Exception as e:
            print(f"      [ERROR] {asset}: {e}")
    print(f"    total books_idx keys: {len(books_idx):,}")

    # Run fills via engine_v2
    print("[6] running L25 fills via engine_v2.LegacyConfig...")
    cfg = LegacyConfig()
    entry_vwap = np.full(len(cands), np.nan)
    pnl_legacy = np.full(len(cands), np.nan)
    won_arr = np.zeros(len(cands), dtype=bool)
    cands = cands.reset_index(drop=True)
    for idx, r in cands.iterrows():
        # Bet direction: 'UP' → buy Up token, 'DOWN' → buy Down token
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
        # Won?
        won = (r.outcome == "Up") if r.direction == "UP" else (r.outcome == "Down")
        pnl = hold_pnl(fill, won=won, cfg=cfg)
        entry_vwap[idx] = float(fill["vwap"])
        pnl_legacy[idx] = float(pnl)
        won_arr[idx] = bool(won)
    cands["entry_vwap"] = entry_vwap
    cands["pnl_legacy_usd"] = pnl_legacy
    cands["won"] = won_arr
    filled = cands[cands.pnl_legacy_usd.notna()].copy()
    print(f"    {len(filled):,} / {len(cands):,} fires filled successfully")

    OUT_PT.parent.mkdir(parents=True, exist_ok=True)
    filled.to_parquet(OUT_PT, index=False, compression="zstd")
    print(f"    wrote {OUT_PT}")

    # Aggregate per (asset, fire_offset, dev_bin)
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
    g = g.sort_values(["asset", "fire_offset_s", "dev_tier"]).reset_index(drop=True)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    g.to_csv(OUT_CSV, index=False)
    print(f"    wrote {OUT_CSV}")

    # Print summary
    deploy = g[(g.n >= 30) & (g.wr >= 0.60)].copy().sort_values("wr", ascending=False)
    print(f"\n--- Deployable (n>=30, WR>=60%): {len(deploy)} configs ---")
    if len(deploy) > 0:
        print(deploy.head(30).to_string(index=False))
    print(f"\n--- All (n>=30) configs sorted by WR ---")
    print(g[g.n >= 30].sort_values("wr", ascending=False).head(40).to_string(index=False))

    # Markdown report
    md = []
    md.append(f"# VWAP momentum continuation — 5m markets ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')})")
    md.append("")
    md.append("Strategy: at fire_offset_s into a 5m slot, observe binance close vs the 15m-anchored VWAP. ")
    md.append("If dev_bps > thr → bet UP (continuation). If dev_bps < -thr → bet DOWN.")
    md.append("**Uses engine_v2.LegacyConfig fills via L25 book walks. $25 notional. 2%-on-profit fee.**")
    md.append("")
    md.append("## Deployable (n>=30, WR>=60%)")
    md.append("")
    if len(deploy) > 0:
        md.append(deploy.to_markdown(index=False))
    else:
        md.append("**NONE** — no config qualified.")
    md.append("")
    md.append("## All (n>=30) configs by WR")
    md.append("")
    md.append(g[g.n >= 30].sort_values("wr", ascending=False).head(60).to_markdown(index=False))
    md.append("")
    md.append(f"_data: `data/v4/canonical/_results/vwap_continuation_5m.csv`_  ")
    md.append(f"_per-fire parquet: `data/v4/canonical/_results/vwap_continuation_5m_per_fire.parquet`_  ")
    md.append(f"_script: `strategy_lab/meta_classifier/vwap_continuation_5m.py`_")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(f"\nReport: {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
