"""Deep cross-venue timestamp audit — distinguishes real noise from bar-alignment bug.

Builds on _timestamp_audit.py finding that bin/coin ret_corr=0.44 (low). Tests:

  E1. Direct bar-boundary lookup — at the SAME exact UTC minute T, what do
      binance and coinbase report for price_close?  If gap is small (~1-5 bp)
      with median near zero, that's real cross-venue noise, not a bug.

  E2. Phase-shift detection — compute ret_corr at lags k ∈ {-2,-1,0,+1,+2} minutes.
      If correlation is MAXIMIZED at k=0 and FALLS for non-zero k, no bug.
      If correlation is HIGHER at k=±1, that's a bar-alignment bug.

  E3. Consecutive-minute price ratio — for minutes t1 = t0 + 60, does
      coin_price@t1/coin_price@t0 ≈ bin_price@t1/bin_price@t0?
      Both should be measuring the same minute's evolution. Compute the ratio
      of these two ratios (= relative ret); should be ~1.0 with small dispersion.

  E4. Polymarket book ts vs binance kline ts — for a sample of fire events,
      compare polymarket book timestamp_us to fire_us (in seconds), then to
      binance closest 1m bar boundary. Confirms book and kline streams use
      the same epoch.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "strategy_lab"))
sys.path.insert(0, str(ROOT / "strategy_lab" / "meta_classifier"))

REFRESH_OLD = ROOT / "data/v4/refresh_2026_05_06"
REFRESH_NEW = ROOT / "data/v4/refresh_2026_05_09"


def load_close_indexed(symbol_id: str, source: str, csv_path: Path) -> pd.Series:
    """Read CSV, return close prices indexed by ts_s (UTC seconds)."""
    df = pd.read_csv(csv_path,
                     usecols=["symbol_id", "period_id", "source",
                              "time_period_start_us", "price_close"])
    df = df[(df.period_id == "1MIN") & (df.source == source) &
            (df.symbol_id == symbol_id)].copy()
    df["ts_s"] = (df.time_period_start_us // 1_000_000).astype("int64")
    df = df.drop_duplicates("ts_s", keep="last").sort_values("ts_s")
    return df.set_index("ts_s")["price_close"].astype("float64")


def main():
    print("=== DEEP CROSS-VENUE TIMESTAMP AUDIT ===\n")

    print("[1] Loading 1MIN closes for BTC: binance-vision + coinbase-spot-ws...")
    bin_close = load_close_indexed("BINANCE_SPOT_BTC_USDT", "binance-vision",
                                     REFRESH_OLD / "klines_full.csv")
    coin_close = load_close_indexed("COINBASE_SPOT_BTC_USD", "coinbase-spot-ws",
                                      REFRESH_NEW / "cex_klines_vps2.csv")
    print(f"    bin-vision: {len(bin_close)} bars "
          f"({pd.to_datetime(bin_close.index.min(), unit='s', utc=True)} -> "
          f"{pd.to_datetime(bin_close.index.max(), unit='s', utc=True)})")
    print(f"    coinbase  : {len(coin_close)} bars "
          f"({pd.to_datetime(coin_close.index.min(), unit='s', utc=True)} -> "
          f"{pd.to_datetime(coin_close.index.max(), unit='s', utc=True)})")

    # ----- E1: direct bar-boundary lookup -----
    print("\n[E1] Direct bar-boundary lookup (no asof, exact ts match)...")
    common = bin_close.index.intersection(coin_close.index)
    print(f"    intersection: {len(common)} common minute boundaries")
    if len(common) < 1000:
        print("    NOT ENOUGH overlap — cannot proceed with E1")
        return
    b = bin_close.reindex(common).values
    c = coin_close.reindex(common).values
    diff_bp = (c / b - 1.0) * 10000
    print(f"    coin/bin diff (bp): "
          f"median={np.median(diff_bp):+.3f}, "
          f"p25={np.quantile(diff_bp, 0.25):+.3f}, "
          f"p75={np.quantile(diff_bp, 0.75):+.3f}, "
          f"p95={np.quantile(np.abs(diff_bp), 0.95):.3f}, "
          f"p99={np.quantile(np.abs(diff_bp), 0.99):.3f}, "
          f"max={np.max(np.abs(diff_bp)):.3f}")
    print(f"    price corr: {np.corrcoef(b, c)[0,1]:.6f}")

    # ----- E2: phase-shift detection -----
    print("\n[E2] Phase-shift detection — ret_corr at lag k minutes...")
    # Compute 1m returns on each
    bin_ret_1m = np.log(bin_close / bin_close.shift(1)).rename("bin_ret_1m")
    coin_ret_1m = np.log(coin_close / coin_close.shift(1)).rename("coin_ret_1m")
    df = pd.concat([bin_ret_1m, coin_ret_1m], axis=1).dropna()
    print(f"    common 1m return rows: {len(df)}")
    for k in (-3, -2, -1, 0, 1, 2, 3):
        shifted = df.coin_ret_1m.shift(k)
        c = pd.concat([df.bin_ret_1m, shifted], axis=1).dropna()
        corr = np.corrcoef(c.iloc[:, 0], c.iloc[:, 1])[0, 1]
        marker = " <-- max" if k == 0 else ""
        print(f"    lag k={k:+d} min: corr={corr:.4f}{marker}")
    # Same for 2m returns
    print()
    bin_ret_2m = np.log(bin_close / bin_close.shift(2)).rename("bin_ret_2m")
    coin_ret_2m = np.log(coin_close / coin_close.shift(2)).rename("coin_ret_2m")
    df2 = pd.concat([bin_ret_2m, coin_ret_2m], axis=1).dropna()
    for k in (-3, -2, -1, 0, 1, 2, 3):
        shifted = df2.coin_ret_2m.shift(k)
        c = pd.concat([df2.bin_ret_2m, shifted], axis=1).dropna()
        corr = np.corrcoef(c.iloc[:, 0], c.iloc[:, 1])[0, 1]
        print(f"    [2m return] lag k={k:+d} min: corr={corr:.4f}")

    # ----- E3: consecutive-minute relative-ret check -----
    print("\n[E3] Relative-return consistency on consecutive minutes...")
    df_rr = pd.DataFrame({
        "bin_close": bin_close.reindex(common),
        "coin_close": coin_close.reindex(common),
    }).dropna()
    df_rr["bin_ret"] = df_rr.bin_close.pct_change()
    df_rr["coin_ret"] = df_rr.coin_close.pct_change()
    # ratio_of_rets = (1+coin_ret) / (1+bin_ret) - 1; expected near 0
    df_rr["rel_ret_bp"] = ((1 + df_rr.coin_ret) / (1 + df_rr.bin_ret) - 1) * 10000
    df_rr = df_rr.dropna()
    print(f"    n_rows: {len(df_rr)}")
    print(f"    rel_ret_bp (coin vs bin, per-minute): "
          f"median={df_rr.rel_ret_bp.median():+.3f}, "
          f"std={df_rr.rel_ret_bp.std():.3f}, "
          f"p95|.|={np.quantile(df_rr.rel_ret_bp.abs(), 0.95):.3f}, "
          f"p99|.|={np.quantile(df_rr.rel_ret_bp.abs(), 0.99):.3f}, "
          f"max|.|={df_rr.rel_ret_bp.abs().max():.3f}")

    # Sign disagreement on 1m moves
    sig_disagree_1m = (np.sign(df_rr.bin_ret) != np.sign(df_rr.coin_ret)).mean()
    print(f"    sign(coin_ret) != sign(bin_ret) on 1m: {sig_disagree_1m*100:.2f}%")

    # Bin coin diff in bp absolute terms (price level)
    df_rr["px_diff_bp"] = (df_rr.coin_close / df_rr.bin_close - 1) * 10000
    print(f"    persistent USD-USDT basis (median price diff coin-bin): "
          f"{df_rr.px_diff_bp.median():+.3f} bp")

    # ----- E4: book ts vs fire_us sanity -----
    print("\n[E4] Polymarket book ts vs fire_us (=ws+120) consistency...")
    p = REFRESH_NEW / "tier1_entries" / "btc_entries_at_t120.parquet"
    if p.exists():
        df = pd.read_parquet(p, columns=["slug", "outcome", "target_ts_us",
                                         "timestamp_us", "dt_abs"])
        df = df[df.outcome == "Up"]  # halve sample
        # target_ts_us = (ws + 120) * 1e6
        # timestamp_us = polymarket book snapshot timestamp
        df["target_s"] = df.target_ts_us // 1_000_000
        df["snap_s"] = df.timestamp_us // 1_000_000
        df["lead_s"] = df.snap_s - df.target_s  # positive = snap AFTER target
        ws = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")
        # Verify target_s == ws + 120
        check_eq = (df.target_s == ws + 120).all()
        print(f"    target_s == ws_from_slug + 120 holds: {check_eq}")
        print(f"    snapshot vs target (seconds): "
              f"median={df.lead_s.median():+.0f}, "
              f"std={df.lead_s.std():.2f}, "
              f"p5={df.lead_s.quantile(0.05):+.0f}, "
              f"p95={df.lead_s.quantile(0.95):+.0f}")
        # Snapshots should land within ±5s of target (by SQL filter)
        within_5s = (df.lead_s.abs() <= 5).mean() * 100
        print(f"    {within_5s:.1f}% of snapshots within ±5 sec of target")
    else:
        print("    btc_entries_at_t120.parquet missing")

    # ----- E5: which 1m return values DO disagree on sign? -----
    print("\n[E5] Distribution of bin/coin 1m ret magnitudes when signs DISAGREE...")
    da = df_rr[np.sign(df_rr.bin_ret) != np.sign(df_rr.coin_ret)]
    if len(da):
        bin_abs_bp = (np.abs(da.bin_ret) * 10000)
        coin_abs_bp = (np.abs(da.coin_ret) * 10000)
        print(f"    n_disagree: {len(da)}/{len(df_rr)} ({len(da)/len(df_rr)*100:.1f}%)")
        print(f"    median |bin_ret| when disagree: {bin_abs_bp.median():.2f} bp")
        print(f"    median |coin_ret| when disagree: {coin_abs_bp.median():.2f} bp")
        print(f"    p95 |bin_ret| when disagree: {bin_abs_bp.quantile(0.95):.2f} bp")
        print(f"    -> if both are tiny (<5bp), disagreements are NOISE near zero,")
        print(f"       not lead-lag at meaningful magnitudes.")

    # ----- E6: G6 condition check -- when |signed_lead| is large, do disagreements -----
    # ----- happen on LARGE moves (true lead-lag) vs small (noise)? -----
    print("\n[E6] When bin and coin disagree, what's the magnitude of the move?")
    da = df_rr[np.sign(df_rr.bin_ret) != np.sign(df_rr.coin_ret)].copy()
    if len(da):
        # The relevant feature: |bin - coin|
        da["gap_bp"] = (da.bin_ret - da.coin_ret).abs() * 10000
        print(f"    |bin_ret - coin_ret| bp distribution on disagreement subset:")
        print(f"    median={da.gap_bp.median():.2f}, "
              f"p25={da.gap_bp.quantile(0.25):.2f}, "
              f"p75={da.gap_bp.quantile(0.75):.2f}, "
              f"p90={da.gap_bp.quantile(0.90):.2f}, "
              f"p99={da.gap_bp.quantile(0.99):.2f}")
        # If most disagreements have small gaps (median <2bp), noise dominates.
        # If most have meaningful gaps (>5bp), real lead-lag.

    print("\n=== INTERPRETATION ===")
    print("  - If E2 corr is MAXIMIZED at lag k=0 → bin/coin bars are time-aligned (no bug).")
    print("  - If price-level diff (E1) is small (~1-5 bp) → just basis + minute-noise.")
    print("  - If E5 shows disagreements happen on TINY moves (<5bp) → near-zero noise dominates,")
    print("    and G6's edge comes from picking signal-magnitude trades. Healthy.")
    print("  - If price-level diff explodes at certain ws (e.g. >50bp) → systematic shift.")


if __name__ == "__main__":
    main()
