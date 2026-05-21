"""CEX alignment — candidate-venue signal generator (Phase 16 §B).

Reads:
  data/v4/refresh_2026_05_09/binance_klines_vps3.csv  (binance from VPS3)
  data/v4/refresh_2026_05_09/cex_klines_vps2.csv      (coinbase/kraken/okx from VPS2)
  data/v4/refresh_2026_05_09/market_resolutions_full.csv  (universe ground truth)

Builds, per market (asset, slug, window_start_unix):
  - candidate close price at ws_s and ws_s-300 (and ws_s-900 for 15m markets)
  - ret_5m / ret_15m per candidate venue + ensembles
  - signal direction (Up if ret > 0, Down otherwise; or > q90 for q90 candidates)

Candidate registry:
  bin-vision    : binance-vision close
  bin-ws        : binance-spot-ws close
  coinbase      : coinbase-spot-ws close
  kraken        : kraken-spot-ws close (12h+forward subset by default)
  okx           : okx-ws close (audit only)
  bin+coinbase  : 0.5*bin-vision + 0.5*coinbase
  bin+coin+krak : 1/3 each (overlap window only)
  median3       : per-ts median of bin-vision, coinbase, kraken
  q90-bin       : bin-vision ret with q90 threshold gate
  q90-ensemble  : bin+coinbase ret with q90 threshold gate

Output: pandas DataFrame columns:
  asset, slug, timeframe, window_start_unix, outcome_up,
  signal_<candidate>  (1=Up, 0=Down, -1=Skip), ret_<candidate>
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_09"

ASSET_VENUES = {
    "btc": {
        "binance": "BINANCE_SPOT_BTC_USDT",
        "coinbase": "COINBASE_SPOT_BTC_USD",
        "kraken":   "KRAKEN_SPOT_BTC_USD",
        "okx":      "OKX_SPOT_BTC_USDT",
    },
    "eth": {
        "binance": "BINANCE_SPOT_ETH_USDT",
        "coinbase": "COINBASE_SPOT_ETH_USD",
        "kraken":   "KRAKEN_SPOT_ETH_USD",
        "okx":      "OKX_SPOT_ETH_USDT",
    },
    "sol": {
        "binance": "BINANCE_SPOT_SOL_USDT",
        "coinbase": "COINBASE_SPOT_SOL_USD",
        "kraken":   "KRAKEN_SPOT_SOL_USD",
        "okx":      "OKX_SPOT_SOL_USDT",
    },
}

UPDOWN_RE = re.compile(r"^(btc|eth|sol)-updown-(5m|15m)-(\d+)$")


def load_klines() -> dict[tuple[str, str, str], pd.Series]:
    """Return dict[(asset, venue, source_tag)] -> Series indexed by ts_s, value=close.

    Note: bin-vision and bin-ws share asset+venue=binance but differ by source.
    """
    bin_df = pd.read_csv(REFRESH / "binance_klines_vps3.csv",
                         usecols=["symbol_id", "period_id", "source",
                                  "time_period_start_us", "price_close"])
    cex_df = pd.read_csv(REFRESH / "cex_klines_vps2.csv",
                         usecols=["symbol_id", "period_id", "source",
                                  "time_period_start_us", "price_close"])
    df = pd.concat([bin_df, cex_df], ignore_index=True)
    df = df[df["period_id"] == "1MIN"].copy()
    df["ts_s"] = (df["time_period_start_us"] // 1_000_000).astype("int64")

    out: dict[tuple[str, str, str], pd.Series] = {}
    for asset, venues in ASSET_VENUES.items():
        for venue, sym in venues.items():
            sub = df[df["symbol_id"] == sym]
            for source_tag, src_df in sub.groupby("source"):
                series = (src_df.drop_duplicates(subset=["ts_s"], keep="last")
                                 .set_index("ts_s")["price_close"]
                                 .astype(float)
                                 .sort_index())
                out[(asset, venue, source_tag)] = series
    return out


def load_universe() -> pd.DataFrame:
    """Load market_resolutions_v2 → derive (asset, slug, timeframe, window_start_unix, outcome_up)."""
    df = pd.read_csv(REFRESH / "market_resolutions_full.csv")
    parts = df["slug"].str.extract(UPDOWN_RE.pattern)
    df["asset"] = parts[0]
    df["timeframe"] = parts[1]
    df["window_start_unix"] = pd.to_numeric(parts[2], errors="coerce")
    df = df.dropna(subset=["asset", "timeframe", "window_start_unix"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    df["outcome_up"] = (df["outcome"].str.lower() == "up").astype(int)
    return df[["asset", "slug", "timeframe", "window_start_unix", "outcome_up"]]


def asof_close(series: pd.Series, ts_s: int, max_lag_s: int = 60) -> float:
    """Return close at-or-before ts_s, NaN if no row within max_lag_s."""
    if series.empty:
        return float("nan")
    idx = series.index.searchsorted(ts_s, side="right") - 1
    if idx < 0:
        return float("nan")
    found_ts = series.index[idx]
    if ts_s - found_ts > max_lag_s:
        return float("nan")
    return float(series.iloc[idx])


# --- candidate definitions --------------------------------------------------

CANDIDATES = [
    "bin-vision", "bin-ws", "coinbase", "kraken", "okx",
    "bin+coinbase", "bin+coin+krak", "median3",
    "q90-bin", "q90-ensemble",
]


def col_safe(candidate: str) -> str:
    """Map candidate name → valid Python identifier suffix for column access via itertuples."""
    return candidate.replace("-", "_").replace("+", "_")


def candidate_close(asset: str, ts_s: int, candidate: str,
                    klines: dict[tuple[str, str, str], pd.Series]) -> float:
    """Return the candidate's close price at ts_s (NaN if any required source is missing)."""

    def get(venue: str, source_tag: str) -> float:
        s = klines.get((asset, venue, source_tag))
        return float("nan") if s is None else asof_close(s, ts_s)

    if candidate == "bin-vision":
        return get("binance", "binance-vision")
    if candidate == "bin-ws":
        return get("binance", "binance-spot-ws")
    if candidate == "coinbase":
        return get("coinbase", "coinbase-spot-ws")
    if candidate == "kraken":
        return get("kraken", "kraken-spot-ws")
    if candidate == "okx":
        return get("okx", "okx-ws")
    if candidate in ("bin+coinbase", "q90-ensemble"):
        a = get("binance", "binance-vision")
        b = get("coinbase", "coinbase-spot-ws")
        if not (np.isfinite(a) and np.isfinite(b)):
            return float("nan")
        return 0.5 * a + 0.5 * b
    if candidate == "bin+coin+krak":
        a = get("binance", "binance-vision")
        b = get("coinbase", "coinbase-spot-ws")
        c = get("kraken", "kraken-spot-ws")
        if not (np.isfinite(a) and np.isfinite(b) and np.isfinite(c)):
            return float("nan")
        return (a + b + c) / 3.0
    if candidate == "median3":
        a = get("binance", "binance-vision")
        b = get("coinbase", "coinbase-spot-ws")
        c = get("kraken", "kraken-spot-ws")
        vals = [v for v in (a, b, c) if np.isfinite(v)]
        if len(vals) < 2:
            return float("nan")
        return float(np.median(vals))
    if candidate == "q90-bin":
        return get("binance", "binance-vision")
    raise ValueError(f"unknown candidate {candidate!r}")


def compute_signals(universe: pd.DataFrame,
                    klines: dict[tuple[str, str, str], pd.Series],
                    candidates: Iterable[str] = CANDIDATES,
                    q90_window_s: int = 7 * 86400,
                    ) -> pd.DataFrame:
    """For each (market, candidate), compute ret + signal direction.

    For 5m markets: ret = log(close@ws / close@ws-300)
    For 15m markets: ret = log(close@ws / close@ws-900)

    Returns wide DataFrame with one row per market, columns:
      ret_<cand>, signal_<cand>  (1=Up, 0=Down, -1=Skip when ret missing)
    """
    universe = universe.copy().sort_values("window_start_unix").reset_index(drop=True)

    # Pre-compute returns per candidate
    for cand in candidates:
        rets = np.full(len(universe), np.nan, dtype=float)
        for i, row in enumerate(universe.itertuples(index=False)):
            ws = int(row.window_start_unix)
            lookback_s = 300 if row.timeframe == "5m" else 900
            c_now = candidate_close(row.asset, ws, cand, klines)
            c_back = candidate_close(row.asset, ws - lookback_s, cand, klines)
            if not (np.isfinite(c_now) and np.isfinite(c_back) and c_back > 0):
                continue
            rets[i] = float(np.log(c_now / c_back))
        universe[f"ret_{col_safe(cand)}"] = rets

        if cand.startswith("q90-"):
            # Trailing-window q90 |ret| threshold gate, refit per row from prior 7d
            sig = np.full(len(universe), -1, dtype=int)
            ws_arr = universe["window_start_unix"].values
            for i in range(len(universe)):
                if not np.isfinite(rets[i]):
                    continue
                lo = ws_arr[i] - q90_window_s
                mask = (ws_arr < ws_arr[i]) & (ws_arr >= lo) & (universe["asset"] == universe["asset"].iat[i])
                prior = rets[mask.values]
                prior = prior[np.isfinite(prior)]
                if len(prior) < 50:
                    continue
                thr = float(np.quantile(np.abs(prior), 0.90))
                if abs(rets[i]) < thr:
                    continue  # below gate → Skip
                sig[i] = 1 if rets[i] > 0 else 0
            universe[f"signal_{col_safe(cand)}"] = sig
        else:
            sig = np.where(np.isfinite(rets),
                           np.where(rets > 0, 1, 0),
                           -1)
            universe[f"signal_{col_safe(cand)}"] = sig.astype(int)  # type: ignore[union-attr]

    return universe


def coverage_report(df: pd.DataFrame, candidates: Iterable[str] = CANDIDATES) -> pd.DataFrame:
    """Per-candidate Skip-rate per asset/timeframe."""
    rows = []
    for cand in candidates:
        col = f"signal_{col_safe(cand)}"
        for (asset, tf), sub in df.groupby(["asset", "timeframe"]):
            n = len(sub)
            n_skip = (sub[col] == -1).sum()
            n_up = (sub[col] == 1).sum()
            n_down = (sub[col] == 0).sum()
            rows.append({"candidate": cand, "asset": asset, "timeframe": tf,
                         "n": int(n), "skip": int(n_skip),
                         "up": int(n_up), "down": int(n_down),
                         "coverage_pct": round(100 * (1 - n_skip / n), 2) if n else 0.0})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    print("Loading klines...")
    klines = load_klines()
    print(f"  loaded {len(klines)} (asset,venue,source) series")
    for k, s in sorted(klines.items()):
        print(f"    {k}: rows={len(s):>6}, range="
              f"{pd.to_datetime(s.index.min(), unit='s', utc=True)}"
              f" -> {pd.to_datetime(s.index.max(), unit='s', utc=True)}")

    print("\nLoading universe...")
    universe = load_universe()
    print(f"  {len(universe)} markets ({universe['timeframe'].value_counts().to_dict()})")

    print("\nComputing signals for all candidates...")
    df = compute_signals(universe, klines)

    print("\nCoverage:")
    print(coverage_report(df).to_string(index=False))

    out = REFRESH / "cex_alignment_signals.parquet"
    df.to_parquet(out, index=False)
    print(f"\nWrote {out} ({len(df)} rows)")
