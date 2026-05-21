"""Build STRUCTURE features parquet from cached klines + universe.

Output: data/v4/refresh_2026_05_06/cache/all_structure_features.parquet
Schema (one row per (slug, asset, window_start_unix)):
  slug                              (string)
  asset                             (string) btc/eth/sol
  window_start_unix                 (int64)
  struct_btc_trend_1h_slope         (float)
  struct_btc_trend_4h_slope         (float)
  struct_dist_to_resistance_bps     (float)
  struct_dist_to_support_bps        (float)
  struct_regime                     (string) 'trend' | 'sideways' | 'volatile'
  struct_score                      (float, [-1, +1])

Strict no-lookahead: every feature at ws_unix uses ONLY data with bar
end-time <= ws_unix (mirrors extended_backtest.asof()).

struct_score is SIDE-AGNOSTIC (one value per (slug, ws_unix)) — the classifier
sees the same struct_score regardless of held side. Misalignment vs signal is
the classifier's responsibility (s_align threshold).

Usage:
  py -X utf8 -m strategy_lab.confluence.structure.build_structure
  py -X utf8 -m strategy_lab.confluence.structure.build_structure --smoke
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT))

from strategy_lab.confluence.schema import STRUCTURE_FEATURE_COLS
from strategy_lab.confluence.structure.btc_trend import (
    compute_trend_slopes,
    realized_vol_1h,
    rolling_slope_norm,
    _idx_le,
)
from strategy_lab.confluence.structure.regime_classifier import (
    classify_regime_series,
    regime_factor,
    DEFAULT_HYSTERESIS_BARS,
    DEFAULT_SLOPE_THRESH,
    DEFAULT_VOL_THRESH,
)
from strategy_lab.confluence.structure.sr_levels import (
    compute_distances_for_universe,
    extract_swings,
)

# ---------------------------------------------------------------------------
# Paths (mirror extended_backtest_with_robustness)
# ---------------------------------------------------------------------------

REFRESH_NEW = ROOT / "data" / "v4" / "refresh_2026_05_06"
CACHE_DIR = REFRESH_NEW / "cache"

ASSET_BINANCE = {
    "btc": "BINANCE_SPOT_BTC_USDT",
    "eth": "BINANCE_SPOT_ETH_USDT",
    "sol": "BINANCE_SPOT_SOL_USDT",
}
ASSET_OKX = {
    "btc": "OKX_SPOT_BTC_USDT",
    "eth": "OKX_SPOT_ETH_USDT",
    "sol": "OKX_SPOT_SOL_USDT",
}

OUT_PARQUET = CACHE_DIR / "all_structure_features.parquet"


# ---------------------------------------------------------------------------
# Loaders (parallel to extended_backtest_with_robustness.load_*)
# ---------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    """Mirror of extended_backtest_with_robustness.load_universe()."""
    df = pd.read_csv(REFRESH_NEW / "market_resolutions_full.csv")
    if "window_start_unix" not in df.columns or "outcome_up" not in df.columns:
        parts = df["slug"].str.split("-", n=3, expand=True)
        df["asset"] = parts[0]
        df["timeframe"] = parts[2]
        df["window_start_unix"] = pd.to_numeric(parts[3], errors="coerce")
        df["outcome_up"] = (df["outcome"].str.lower() == "up").astype(int)
    df = df.dropna(subset=["window_start_unix", "outcome_up"]).copy()
    df["asset"] = df["slug"].str.extract(r"^(btc|eth|sol)-updown-")[0]
    df = df.dropna(subset=["asset"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    df["outcome_up"] = df["outcome_up"].astype(int)
    df["timeframe"] = df["timeframe"].str.lower()
    return df


def load_klines() -> dict[str, pd.DataFrame]:
    """Combined Binance + OKX feeds per asset; Binance preferred, OKX fallback.

    Returns: {'btc': DataFrame[ts_s, price_close], 'eth': ..., 'sol': ...}
    """
    df = pd.read_csv(REFRESH_NEW / "klines_full.csv")
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    out = {}
    for asset in ("btc", "eth", "sol"):
        bin_sym = ASSET_BINANCE[asset]
        okx_sym = ASSET_OKX[asset]
        bin_sub = df[df.symbol_id == bin_sym][["ts_s", "price_close"]].copy()
        okx_sub = df[df.symbol_id == okx_sym][["ts_s", "price_close"]].copy()
        bin_sub["src"] = "binance"
        okx_sub["src"] = "okx"
        combined = pd.concat([bin_sub, okx_sub], ignore_index=True)
        combined = combined.sort_values(["ts_s", "src"]).drop_duplicates(
            "ts_s", keep="first"
        )
        combined = combined.sort_values("ts_s").reset_index(drop=True)
        out[asset] = combined[["ts_s", "price_close"]]
        print(
            f"[klines/{asset}] {len(out[asset]):,} bars  "
            f"range {pd.to_datetime(out[asset].ts_s.min(), unit='s')} -> "
            f"{pd.to_datetime(out[asset].ts_s.max(), unit='s')}",
            flush=True,
        )
    return out


# ---------------------------------------------------------------------------
# Feature computation core
# ---------------------------------------------------------------------------

def _compute_per_minute_regime(
    btc_kline: pd.DataFrame,
    ws_arr: np.ndarray,
    vol_thresh: float = DEFAULT_VOL_THRESH,
    slope_thresh: float = DEFAULT_SLOPE_THRESH,
    hysteresis: int = DEFAULT_HYSTERESIS_BARS,
) -> np.ndarray:
    """Compute regime labels at each ws in `ws_arr` (sorted ascending).

    For hysteresis we need a continuous time-ordered sequence of raw labels.
    We process ws_arr (sorted) directly — the gap between successive ws may
    be irregular, but hysteresis "5 bars" means 5 successive markets in
    chronological order, which is the right granularity for confluence.
    """
    n = ws_arr.size
    slopes = np.full(n, np.nan, dtype=float)
    vols = np.full(n, np.nan, dtype=float)

    ts_s = btc_kline["ts_s"].to_numpy(dtype="int64")
    closes = btc_kline["price_close"].to_numpy(dtype=float)

    for i, ws in enumerate(ws_arr):
        idx = _idx_le(ts_s, int(ws))
        if idx < 0:
            continue
        lo = max(0, idx - 60 + 1)
        if idx - lo + 1 >= 5:
            slopes[i] = rolling_slope_norm(closes[lo : idx + 1])
        vols[i] = realized_vol_1h(btc_kline, int(ws), minutes=60)

    return classify_regime_series(
        slopes,
        vols,
        vol_thresh=vol_thresh,
        slope_thresh=slope_thresh,
        hysteresis_bars=hysteresis,
    )


def _compute_struct_score(
    slope_1h: np.ndarray,
    dist_resist: np.ndarray,
    dist_support: np.ndarray,
    regimes: np.ndarray,
) -> np.ndarray:
    """Side-agnostic composite score in [-1, +1].

    score = clip(0.5*sign(slope_1h)
                 + 0.3*(dist_r - dist_s)/max_dist
                 + 0.2*regime_factor, -1, 1)

    where regime_factor in {-0.3, 0.0, +0.3} for volatile/sideways/trend.

    Positive = up-trend with room to rally.
    Negative = down-trend or already at resistance.
    """
    n = slope_1h.size
    score = np.zeros(n, dtype=float)

    # Slope sign component
    slope_finite = np.isfinite(slope_1h)
    score[slope_finite] += 0.5 * np.sign(slope_1h[slope_finite])

    # S/R balance component (only where both finite)
    both = np.isfinite(dist_resist) & np.isfinite(dist_support)
    if both.any():
        max_d = np.maximum(dist_resist[both], dist_support[both])
        # Avoid div-by-zero
        safe = max_d > 0
        idxs = np.where(both)[0][safe]
        max_d = max_d[safe]
        sr_term = (dist_resist[idxs] - dist_support[idxs]) / max_d
        score[idxs] += 0.3 * sr_term

    # Regime contribution
    rf = np.array([regime_factor(r) for r in regimes], dtype=float)
    score += 0.2 * (rf / 0.3)  # normalize so trend contributes +0.2, volatile -0.2

    return np.clip(score, -1.0, 1.0)


def build_structure_features(
    universe: pd.DataFrame,
    klines: dict[str, pd.DataFrame],
    swing_window_bars: int = 30,
    sr_lookback_days: int = 5,
    vol_thresh: float = DEFAULT_VOL_THRESH,
    slope_thresh: float = DEFAULT_SLOPE_THRESH,
    hysteresis: int = DEFAULT_HYSTERESIS_BARS,
) -> pd.DataFrame:
    """Compute STRUCTURE features per (slug, asset, window_start_unix).

    Returns DataFrame matching schema.STRUCTURE_FEATURE_COLS.
    """
    # Deduplicate to one row per (slug, asset, ws_unix) — STRUCTURE is
    # asset-level macro; same value for both Up/Down sides of a market.
    keys = (
        universe[["slug", "asset", "window_start_unix"]]
        .drop_duplicates(subset=["slug"])
        .reset_index(drop=True)
    )
    # Sort chronologically for hysteresis
    keys = keys.sort_values("window_start_unix").reset_index(drop=True)

    btc_kline = klines["btc"]
    print(
        f"[build] {len(keys):,} unique markets; computing trend on BTC kline "
        f"({len(btc_kline):,} bars)",
        flush=True,
    )

    # 1) BTC trend slopes (1h, 4h) — same for every asset (BTC = macro driver)
    t0 = time.time()
    ws_arr = keys["window_start_unix"].to_numpy(dtype="int64")
    slope_1h, slope_4h = compute_trend_slopes(btc_kline, ws_arr)
    print(f"[build] trend slopes done in {time.time()-t0:.1f}s", flush=True)

    # 2) Regime classification (uses BTC vol + 1h slope), with hysteresis
    t0 = time.time()
    regimes = _compute_per_minute_regime(
        btc_kline,
        ws_arr,
        vol_thresh=vol_thresh,
        slope_thresh=slope_thresh,
        hysteresis=hysteresis,
    )
    print(f"[build] regime classification done in {time.time()-t0:.1f}s", flush=True)

    # 3) S/R distances — per-asset since each asset has its own swings
    dist_r_full = np.full(len(keys), np.nan, dtype=float)
    dist_s_full = np.full(len(keys), np.nan, dtype=float)

    for asset in ("btc", "eth", "sol"):
        t0 = time.time()
        kl = klines[asset]
        swings = extract_swings(kl, window_bars=swing_window_bars)
        n_sw = len(swings)
        mask = (keys["asset"] == asset).to_numpy()
        ws_sub = keys.loc[mask, "window_start_unix"].to_numpy(dtype="int64")
        dr, ds = compute_distances_for_universe(
            swings, kl, ws_sub, lookback_days=sr_lookback_days
        )
        dist_r_full[mask] = dr
        dist_s_full[mask] = ds
        print(
            f"[build/{asset}] swings={n_sw:,}, slugs={mask.sum():,}, "
            f"S/R distances done in {time.time()-t0:.1f}s",
            flush=True,
        )

    # 4) Composite score
    score = _compute_struct_score(slope_1h, dist_r_full, dist_s_full, regimes)

    out = pd.DataFrame({
        "slug": keys["slug"].values,
        "asset": keys["asset"].values,
        "window_start_unix": keys["window_start_unix"].values,
        "struct_btc_trend_1h_slope": slope_1h,
        "struct_btc_trend_4h_slope": slope_4h,
        "struct_dist_to_resistance_bps": dist_r_full,
        "struct_dist_to_support_bps": dist_s_full,
        "struct_regime": regimes.astype(str),
        "struct_score": score,
    })

    # Verify schema match
    expected = ["slug", "asset", "window_start_unix"] + list(STRUCTURE_FEATURE_COLS)
    assert list(out.columns) == expected, (
        f"column mismatch: have {list(out.columns)}, expect {expected}"
    )
    return out


# ---------------------------------------------------------------------------
# CLI + smoke test
# ---------------------------------------------------------------------------

def _print_stats(df: pd.DataFrame) -> None:
    cols_num = [c for c in STRUCTURE_FEATURE_COLS if c != "struct_regime"]
    print("\n[stats] numerical feature describe:")
    print(df[cols_num].describe().to_string())
    print("\n[stats] regime distribution:")
    print(df["struct_regime"].value_counts(dropna=False).to_string())
    print(f"\n[stats] total rows: {len(df):,}")
    print(f"[stats] coverage:")
    for c in STRUCTURE_FEATURE_COLS:
        if c == "struct_regime":
            n_set = (df[c].astype(str).str.len() > 0).sum()
        else:
            n_set = df[c].notna().sum()
        print(f"  {c}: {n_set/len(df):.1%}  ({n_set:,}/{len(df):,})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="DEV: limit to 100 slugs for fast pipeline test")
    ap.add_argument("--limit", type=int, default=None,
                    help="DEV: cap to first N (chronologically sorted) slugs")
    ap.add_argument("--out", type=str, default=str(OUT_PARQUET),
                    help="output parquet path")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    t_start = time.time()
    universe = load_universe()
    print(f"[load] universe rows: {len(universe):,}", flush=True)

    if args.smoke:
        # Take 100 unique markets evenly spread across assets and time
        unique_keys = (
            universe[["slug", "asset", "window_start_unix"]]
            .drop_duplicates(subset=["slug"])
            .sort_values("window_start_unix")
        )
        smoke = unique_keys.groupby("asset").head(40).head(100)
        keep_slugs = set(smoke["slug"])
        universe = universe[universe["slug"].isin(keep_slugs)].copy()
        print(f"[smoke] limited to {len(keep_slugs)} unique markets", flush=True)
    elif args.limit:
        unique_keys = (
            universe[["slug", "asset", "window_start_unix"]]
            .drop_duplicates(subset=["slug"])
            .sort_values("window_start_unix")
            .head(args.limit)
        )
        universe = universe[universe["slug"].isin(set(unique_keys["slug"]))].copy()
        print(f"[limit] limited to {args.limit} unique markets", flush=True)

    klines = load_klines()
    df = build_structure_features(universe, klines)
    df.to_parquet(out_path, engine="pyarrow", index=False)
    print(
        f"\n[write] {out_path} "
        f"({len(df):,} rows, {out_path.stat().st_size/1e6:.1f} MB)",
        flush=True,
    )
    _print_stats(df)
    print(f"\n[done] elapsed {time.time()-t_start:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
