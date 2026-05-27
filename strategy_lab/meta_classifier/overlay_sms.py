"""Overlay SMS panel onto per-fire parquets via merge_asof.

Produces augmented parquets that match the SMS chart-TF state at the time of fire:
  s15_with_sms.parquet  — S1.5 5m fires + SMS 5m panel (chart-TF = 5m)
  s6_with_sms.parquet   — S6  5m fires + SMS 5m panel
  v15m_with_sms.parquet — V15M 15m fires + SMS 15m panel

The SMS panel `ts_us` = bar START. To be causal (bar must have CLOSED), we shift
the fire's lookup ts back by exactly one bar (so the merge_asof picks up the
last-completed bar, never the in-progress one).
"""
from __future__ import annotations
import sys, time
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RES = ROOT / "data" / "v4" / "canonical" / "_results"

SMS_5M = RES / "sms_panel_5m.parquet"
SMS_15M = RES / "sms_panel_15m.parquet"

S15_IN = RES / "s15_with_ta_and_markov.parquet"
S6_IN = RES / "s6_with_ta.parquet"
V15M_IN = RES / "v15m_with_ta_and_markov.parquet"

S15_OUT = RES / "s15_with_sms.parquet"
S6_OUT = RES / "s6_with_sms.parquet"
V15M_OUT = RES / "v15m_with_sms.parquet"

SMS_COLS = [
    "pivot_high", "pivot_low",
    "last_high", "last_low", "last_high_prev", "last_low_prev",
    "bos_buy", "bos_sell", "choch_buy", "choch_sell",
    "bars_since_bos_buy", "bars_since_bos_sell",
    "bars_since_choch_buy", "bars_since_choch_sell",
    "rsi_14", "rsi_bullish_div", "rsi_bearish_div",
    "cvd", "cvd_level", "cvd_sign",
    "liquidity_up", "liquidity_dn",
    "trend_1m", "trend_5m", "trend_15m", "trend_30m", "trend_1h", "trend_4h", "trend_d",
    "trend_strength_raw", "trend_strength_pct", "system_confidence",
]


def overlay(fires_path, panel_path, out_path, name, tf_min):
    print(f"\n[{name}]")
    t0 = time.time()
    fires = pd.read_parquet(fires_path)
    panel = pd.read_parquet(panel_path)
    # Drop SMS columns that may already exist (e.g. rsi_14 in s6 file)
    drop_existing = [c for c in SMS_COLS if c in fires.columns]
    if drop_existing:
        print(f"  dropping pre-existing cols (will be replaced by SMS panel values): {drop_existing}")
        fires = fires.drop(columns=drop_existing)
    bar_us = tf_min * 60 * 1_000_000

    out_parts = []
    for asset in ("BTC", "ETH", "SOL"):
        f_a = fires[fires.asset == asset].copy()
        p_a = panel[panel.asset == asset][["ts_us"] + SMS_COLS].copy()
        if len(f_a) == 0:
            continue
        # Causal merge: at fire_us, the most recent bar that CLOSED is the bar whose start
        # is <= (fire_us - bar_us). i.e. lookup_us = fire_us - bar_us.
        f_a["lookup_us"] = f_a["fire_us"].astype("int64") - bar_us
        f_a = f_a.sort_values("lookup_us")
        p_a = p_a.sort_values("ts_us")
        # merge_asof: 'backward' direction picks the largest ts_us <= lookup_us
        merged = pd.merge_asof(
            f_a,
            p_a.rename(columns={"ts_us": "panel_ts_us"}),
            left_on="lookup_us",
            right_on="panel_ts_us",
            direction="backward",
            tolerance=2 * bar_us,  # within 2 bars
        )
        out_parts.append(merged)
        nn = merged["bos_buy"].notna().sum()
        print(f"  {asset}: {len(f_a):,} fires, {nn:,} with SMS panel data")

    aug = pd.concat(out_parts, ignore_index=True)
    aug.to_parquet(out_path, index=False, compression="zstd")
    print(f"  wrote {out_path} ({len(aug):,} rows) in {time.time()-t0:.1f}s")
    return aug


def main():
    overlay(S15_IN, SMS_5M, S15_OUT, "S1.5 5m", tf_min=5)
    overlay(S6_IN, SMS_5M, S6_OUT, "S6 5m", tf_min=5)
    overlay(V15M_IN, SMS_15M, V15M_OUT, "V15M 15m", tf_min=15)

    print("\n[sanity] sample S1.5 row with SMS:")
    aug = pd.read_parquet(S15_OUT)
    print(aug[["asset", "fire_us", "direction", "won", "pnl_legacy_usd",
               "bos_buy", "bos_sell", "choch_buy", "choch_sell",
               "trend_strength_raw", "system_confidence", "cvd_sign", "cvd_level",
               "rsi_bullish_div", "rsi_bearish_div", "liquidity_up", "liquidity_dn"]].iloc[1000:1005].to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
