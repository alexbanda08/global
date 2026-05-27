"""V8 BUILD — extra (earlier) offsets fire universe for all 6 markets.

Extends V3 (which had canonical offsets {30, 60, 90, ..., 270} for 5m and
{60, 120, 240, ..., 840} for 15m) with EARLIER offsets that did not exist yet:
  - 5m: {0, 15, 45}
  - 15m: {0, 30, 45}

Approach: monkey-patch the v2 `build_oos_one_asset_tf` so the offset
list is overridden per call. We do this by injecting a wrapper that
swaps `offsets_5m` / `offsets_15m` via a module-level override.

Output dir: data/v4/canonical/_results/_full_window_v8_2026_05_27/
File pattern: oos_fires_{ASSET}_{TF}_v8_extra_offsets.parquet

Conventions (per CLAUDE.md, DO NOT VIOLATE):
  - ws_s = slot_start_us // 1e6 - window_s
  - LegacyConfig (2% on profit only)
  - chainlink outcome
  - L25 walk via engine_v2.fill_at_book, spread 0.02 BTC/ETH, 0.025 SOL
  - $25 notional
  - Sequential builds; gc.collect() between markets
"""
from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "data" / "v4" / "canonical"))

# ---------------------------------------------------------------------------
# Window override -- match V3 full-window span (Apr 24 -> May 26 17:30 UTC)
# ---------------------------------------------------------------------------
OOS_START_US = int(pd.Timestamp("2026-04-24T01:00:00Z").value // 1000)
OOS_END_US   = int(pd.Timestamp("2026-05-26T17:30:00Z").value // 1000)

# Monkey-patch the v2 module BEFORE we import its functions
import full_window_validation_v2 as fwv2  # noqa: E402
fwv2.OOS_START_US = OOS_START_US
fwv2.OOS_END_US = OOS_END_US

from full_window_validation_v2 import (  # noqa: E402
    ASSETS, SPREAD, NOTIONAL,
    _asof_strict, load_1s_asset, compute_features_inline,
    compute_sms_5m_for_panel, asof_join_features, asof_join_sms,
    compute_oos_gates,
)
from load import (  # noqa: E402
    load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
)
from engine_v2 import LegacyConfig, fill_at_book, hold_pnl  # noqa: E402

OUT_DIR = ROOT / "data" / "v4" / "canonical" / "_results" / "_full_window_v8_2026_05_27"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# V8 EXTRA offsets (NEW, not in V3)
V8_EXTRA_OFFSETS = {
    "5m":  [0, 15, 45],
    "15m": [0, 30, 45],
}

# All 6 markets, ordered smallest first to fail-fast
MARKETS = [
    ("SOL", "15m"),
    ("BTC", "15m"),
    ("ETH", "15m"),
    ("SOL", "5m"),
    ("BTC", "5m"),
    ("ETH", "5m"),
]


def _log(msg: str) -> None:
    ts = pd.Timestamp.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def build_oos_extra_offsets(asset: str, tf: str, klines_1m: dict,
                             offsets: list[int]) -> pd.DataFrame:
    """Copy of fwv2.build_oos_one_asset_tf, but with custom offset list.

    Same conventions: ws_s anchor, chainlink outcome, LegacyConfig fee,
    L25 walk via fill_at_book, $25 notional, asset-specific spread filter.
    """
    window_s = {"5m": 300, "15m": 900}[tf]

    _log(f"[OOS-V8] {asset} {tf}  offsets={offsets}")
    res = load_resolutions(assets=[asset], timeframes=[tf])
    res = res[res["outcome"].isin(("Up", "Down"))].copy()
    res = res[(res["slot_start_us"] >= OOS_START_US) &
              (res["slot_start_us"] <= OOS_END_US)].copy()
    if res.empty:
        return pd.DataFrame()
    res["ws_s"] = (res["slot_start_us"] // 1_000_000) - window_s
    _log(f"  resolutions: {len(res):,}")

    # Load 1s panel with warmup buffer (3h)
    buf_us = 3 * 3600 * 1_000_000
    panel_1s = load_1s_asset(asset, OOS_START_US - buf_us, OOS_END_US + 60_000_000)
    _log(f"  1s panel: {len(panel_1s):,}")
    panel_1s = compute_features_inline(panel_1s, asset)
    sms_5m = compute_sms_5m_for_panel(panel_1s) if tf == "5m" else pd.DataFrame()

    # Stream L25 once
    cfg = LegacyConfig()
    spread = SPREAD[asset]
    end_us_1m, close_1m = klines_1m[asset]
    _log(f"  streaming L25 for {len(res):,} slugs...")
    t0 = time.time()
    books = load_orderbook_l25_streaming(
        asset.lower(), slugs=set(res["slug"].tolist()),
        subsample_1hz=True,
        min_ts_us=int(res["slot_start_us"].min()) - 3600 * 1_000_000,
        max_ts_us=int(res["slot_end_us"].max()) + 3600 * 1_000_000,
    )
    _log(f"  L25 streamed in {time.time()-t0:.1f}s, {len(books)} pairs")

    rows = []
    for r in res.itertuples(index=False):
        slug = r.slug
        ss = int(r.slot_start_us)
        se = int(r.slot_end_us)
        ws_s = int(r.ws_s)
        outcome = str(r.outcome)
        strike = _asof_strict(end_us_1m, close_1m, ss)
        settle = _asof_strict(end_us_1m, close_1m, se)
        for off in offsets:
            fire_us = ss + off * 1_000_000
            for direction, oc_key in (("UP", "Up"), ("DOWN", "Down")):
                fill = fill_at_book(books, slug, oc_key, fire_us, cfg=cfg,
                                    spread_filter=spread, notional_usd=NOTIONAL)
                if fill is None:
                    continue
                won = (outcome == oc_key)
                pnl = hold_pnl(fill, won=won, cfg=cfg)
                rows.append({
                    "asset": asset, "slug": slug, "tf": tf,
                    "slot_start_us": ss, "slot_end_us": se, "ws_s": ws_s,
                    "fire_offset_s": int(off), "fire_us": fire_us,
                    "strike_price": strike, "settle_price": settle,
                    "outcome": outcome, "direction": direction,
                    "pnl_legacy_usd": float(pnl), "won": int(won),
                    "entry_vwap": fill["vwap"],
                })
    del books
    gc.collect()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    _log(f"  fires: {len(df):,}")

    # Join features at fire_us
    feat_cols = ["rf_close", "rf_dir", "rf_dir_age", "rf_band_pos",
                 "ribbon_color", "ribbon_lead_slope_bps", "ribbon_compression_bps",
                 "stoch_k_60s", "bb_pos_60s", "mfi_60s", "cci_60s",
                 "tr_above_ema50", "tr_above_ema200", "tr_above_ema800",
                 "tr_above_cloud", "tr_above_pp", "tr_within_adr",
                 "tr_in_london", "tr_in_ny", "tr_in_tokyo", "tr_active_session_count",
                 "tr_ema_stack_bull", "tr_ema_stack_bear"]
    feat_cols = [c for c in feat_cols if c in panel_1s.columns]
    df = asof_join_features(df, panel_1s, feat_cols)
    if tf == "5m" and not sms_5m.empty:
        df = asof_join_sms(df, sms_5m, tf_min=5)
    df = compute_oos_gates(df)
    _log(f"  OOS df with gates: {df.shape}")
    del panel_1s
    gc.collect()
    return df


def _summary(df: pd.DataFrame, asset: str, tf: str) -> None:
    if df is None or df.empty:
        _log(f"  WARN: {asset} {tf} empty df")
        return
    dt_min = pd.to_datetime(df["fire_us"].min(), unit="us", utc=True)
    dt_max = pd.to_datetime(df["fire_us"].max(), unit="us", utc=True)
    off_counts = df["fire_offset_s"].value_counts().sort_index()
    _log(f"  rows={len(df):,}  span=[{dt_min:%Y-%m-%d %H:%M} .. {dt_max:%Y-%m-%d %H:%M}]  "
         f"won.mean={df['won'].mean():.4f}")
    _log(f"  offsets:")
    for off, n in off_counts.items():
        _log(f"    {off}s -> {n:,}")


def main() -> int:
    t_start = time.time()
    _log("=" * 70)
    _log(f"V8 BUILD — EXTRA (earlier) offsets")
    _log(f"WINDOW: [{pd.Timestamp(OOS_START_US, unit='us', tz='UTC')} .. "
         f"{pd.Timestamp(OOS_END_US, unit='us', tz='UTC')}]")
    _log(f"OUT_DIR: {OUT_DIR}")
    _log(f"5m offsets:  {V8_EXTRA_OFFSETS['5m']}")
    _log(f"15m offsets: {V8_EXTRA_OFFSETS['15m']}")
    _log("=" * 70)

    _log("Loading 1m binance-spot-ws klines per asset...")
    klines_1m: dict[str, tuple] = {}
    for a in ASSETS:
        e, c = load_klines_asof(a, source="binance-spot-ws", period_id="1MIN")
        klines_1m[a] = (e.astype("int64"), c.astype("float64"))
        _log(f"  {a}: {len(e):,} 1m bars loaded")

    results: list[dict] = []
    failures: list[str] = []
    for asset, tf in MARKETS:
        t0 = time.time()
        _log("=" * 70)
        _log(f"BUILD {asset} {tf}  V8-extra")
        _log("=" * 70)
        offsets = V8_EXTRA_OFFSETS[tf]
        try:
            df = build_oos_extra_offsets(asset, tf, klines_1m, offsets)
        except Exception as e:
            _log(f"  ERROR building {asset} {tf}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            failures.append(f"{asset} {tf}: {e}")
            gc.collect()
            continue

        if df is None or df.empty:
            _log(f"  ERROR: empty df for {asset} {tf}")
            failures.append(f"{asset} {tf}: empty")
            gc.collect()
            continue

        out_path = OUT_DIR / f"oos_fires_{asset}_{tf}_v8_extra_offsets.parquet"
        df.to_parquet(out_path, index=False, compression="zstd")
        _log(f"  wrote {out_path.name} ({out_path.stat().st_size / 1024 / 1024:.1f} MB)")
        _summary(df, asset, tf)

        # per-offset fill-rate sanity (each new offset should have ~similar n to others)
        off_counts = df["fire_offset_s"].value_counts().sort_index().to_dict()
        results.append({
            "asset": asset, "tf": tf,
            "n_fires": len(df),
            "won_mean": float(df["won"].mean()),
            "dt_min": str(pd.to_datetime(df["fire_us"].min(), unit="us", utc=True)),
            "dt_max": str(pd.to_datetime(df["fire_us"].max(), unit="us", utc=True)),
            "offsets_present": ",".join(str(k) for k in sorted(off_counts.keys())),
            "off_counts": ",".join(f"{k}={v}" for k, v in off_counts.items()),
            "build_s": time.time() - t0,
        })

        del df
        gc.collect()

    _log("=" * 70)
    _log("DONE")
    _log("=" * 70)
    for r in results:
        _log(f"  {r['asset']:3s} {r['tf']:3s}  n={r['n_fires']:>7,}  "
             f"won={r['won_mean']:.4f}  offs={r['offsets_present']}  "
             f"build={r['build_s']/60:.1f}min")
    if failures:
        _log("FAILURES:")
        for f in failures:
            _log(f"  {f}")
    summary_df = pd.DataFrame(results)
    summary_df.to_csv(OUT_DIR / "_build_summary.csv", index=False)
    _log(f"summary -> {OUT_DIR / '_build_summary.csv'}")
    _log(f"TOTAL RUNTIME: {(time.time()-t_start)/60:.1f} min")
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())
