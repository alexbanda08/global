"""Phase 1 — Hour-of-day filter analysis.

Cyclops claim: peak hours 14/17/18 UTC, troughs 22/01/02/07/19 UTC, weekends bad.
Our test: does this pattern replicate on our (now 9-day) backtest data?

Approach:
1. Combine existing 7d features CSVs + new 2d resolutions (joined to local Binance klines or skipped if missing).
2. For each market, compute hour_of_day from window_start_unix.
3. Group by (hour, asset, day_of_week), compute:
   - n markets, baseline UP rate
   - hit rate of V3 magnitude gate (when fired)
4. Report: do specific hours show >5pp deviation from baseline?
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parents[2]
PM = ROOT / "strategy_lab" / "data" / "polymarket"
REFRESH = ROOT / "data" / "v4" / "refresh_2026_04_30"


def load_existing(asset: str) -> pd.DataFrame:
    df = pd.read_csv(PM / f"{asset}_features_v3.csv")
    df = df.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"])
    df = df[df["timeframe"] == "5m"].copy()
    df["asset"] = asset
    return df


def load_extended_resolutions() -> pd.DataFrame:
    df = pd.read_csv(REFRESH / "mr_extended.csv")
    # ticker like "BTC", "ETH", "SOL"
    df["window_start_unix"] = (df["slot_start_us"] / 1e6).astype("int64")
    df["asset"] = df["ticker"].str.lower()
    df["outcome_up"] = (df["outcome"] == "Up").astype(int)
    df = df[df["timeframe"] == "5m"].copy()
    return df[["asset", "window_start_unix", "outcome_up", "outcome", "timeframe"]]


def hour_of_day(unix_s: pd.Series) -> pd.Series:
    return pd.to_datetime(unix_s, unit="s", utc=True).dt.hour


def day_of_week(unix_s: pd.Series) -> pd.Series:
    """Mon=0 ... Sun=6"""
    return pd.to_datetime(unix_s, unit="s", utc=True).dt.dayofweek


def report_hour_pattern(df: pd.DataFrame, label: str, baseline=0.5):
    print(f"\n=== {label} ===")
    df = df.copy()
    df["hour"] = hour_of_day(df["window_start_unix"])
    df["dow"] = day_of_week(df["window_start_unix"])
    print(f"  Total markets: {len(df)}, baseline UP rate: {df['outcome_up'].mean():.4f}")
    print(f"  Window: {pd.to_datetime(df['window_start_unix'].min(), unit='s', utc=True)}"
          f" -> {pd.to_datetime(df['window_start_unix'].max(), unit='s', utc=True)}")
    print()
    print(f"  Hour | n     | UP_rate | dev_pp | sig")
    print(f"  -----|-------|---------|--------|----")
    rows = []
    for h in range(24):
        sub = df[df["hour"] == h]
        if len(sub) < 10:
            continue
        up_rate = sub["outcome_up"].mean()
        dev_pp = (up_rate - baseline) * 100
        # binomial test vs baseline
        try:
            test = binomtest(int(sub["outcome_up"].sum()), len(sub), p=baseline)
            p = test.pvalue
        except Exception:
            p = 1.0
        sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else " "))
        print(f"  {h:>4d} | {len(sub):>5d} | {up_rate:.4f}  | {dev_pp:+5.1f}  | {sig}")
        rows.append({"hour": h, "n": len(sub), "up_rate": up_rate, "dev_pp": dev_pp, "p": p})
    return pd.DataFrame(rows)


def report_dow_pattern(df: pd.DataFrame, label: str, baseline=0.5):
    print(f"\n=== {label} (day of week) ===")
    df = df.copy()
    df["dow"] = day_of_week(df["window_start_unix"])
    days = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    print(f"  Day | n     | UP_rate | dev_pp")
    print(f"  ----|-------|---------|-------")
    for d in range(7):
        sub = df[df["dow"] == d]
        if len(sub) == 0:
            continue
        up_rate = sub["outcome_up"].mean()
        dev_pp = (up_rate - baseline) * 100
        print(f"  {days[d]} | {len(sub):>5d} | {up_rate:.4f}  | {dev_pp:+5.1f}")


def report_v3_gated(df: pd.DataFrame, label: str, asset: str):
    """Only markets that V3 sniper would have fired on (above per-asset quantile)."""
    print(f"\n=== {label} V3-GATED ({asset}) ===")
    if "ret_5m" not in df.columns:
        print("  ret_5m unavailable for this dataset (skipped)")
        return
    df = df.dropna(subset=["ret_5m"]).copy()
    cells = {"btc": 0.10, "eth": 0.05, "sol": 0.15}
    sub = df[df["asset"] == asset]
    if len(sub) < 50:
        print(f"  not enough data (n={len(sub)})")
        return
    thr = sub["ret_5m"].abs().quantile(1 - cells[asset])
    fired = sub[sub["ret_5m"].abs() >= thr].copy()
    fired["pred_up"] = fired["ret_5m"] > 0
    fired["hit"] = ((fired["pred_up"]) & (fired["outcome_up"] == 1)) | \
                   ((~fired["pred_up"]) & (fired["outcome_up"] == 0))
    fired["hour"] = hour_of_day(fired["window_start_unix"])
    base_hit = fired["hit"].mean()
    print(f"  threshold={thr:.5f}  fires={len(fired)}  baseline_V3_hit={base_hit:.4f}")
    print(f"  Hour | n   | hit    | dev_pp")
    for h in range(24):
        s = fired[fired["hour"] == h]
        if len(s) < 5:
            continue
        hit = s["hit"].mean()
        dev = (hit - base_hit) * 100
        flag = "<<<" if dev < -10 else (">>>" if dev > 10 else "")
        print(f"  {h:>4d} | {len(s):>3d} | {hit:.3f}  | {dev:+5.1f}  {flag}")


def main():
    # Load everything
    existing = pd.concat([load_existing(a) for a in ["btc", "eth", "sol"]], ignore_index=True)
    extended = load_extended_resolutions()

    # Combined unconditional dataset
    common_cols = ["asset", "window_start_unix", "outcome_up"]
    combined = pd.concat([
        existing[common_cols],
        extended[common_cols],
    ], ignore_index=True).drop_duplicates(subset=["asset", "window_start_unix"])

    print(f"Existing: {len(existing)}, Extended new: {len(extended)}, Combined unique: {len(combined)}")

    # --- Test 1: unconditional UP rate by hour (all assets, all data) ---
    report_hour_pattern(combined, "ALL ASSETS, ALL MARKETS (baseline UP rate by hour)")

    # --- Test 2: per-asset by hour ---
    for a in ["btc", "eth", "sol"]:
        sub = combined[combined["asset"] == a]
        report_hour_pattern(sub, f"{a.upper()} markets by hour")

    # --- Test 3: day of week ---
    report_dow_pattern(combined, "ALL ASSETS")

    # --- Test 4: V3-gated hour patterns (uses ret_5m, so existing only) ---
    for a in ["btc", "eth", "sol"]:
        report_v3_gated(existing, "Existing 7d data", a)


if __name__ == "__main__":
    main()
