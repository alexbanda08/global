"""
VPIN (Volume-Synchronized Probability of Informed Trading) panel on binance 1s.
Equal-volume bucketing using taker_buy_base as buy-vol proxy.

For each asset:
  - bucket_size = total_daily_volume / 50  (~50 buckets/day)
  - per bucket: |buy_vol - sell_vol| / total_vol
  - VPIN = rolling mean over last 50 buckets
  - At each 1s bar -> last-completed bucket value
Outputs: data/v4/canonical/_results/vpin_panel.parquet
"""
import sys
import pandas as pd
import numpy as np
from pathlib import Path

PARQ = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/klines_1s/binance_1s_28d.parquet"
OUT = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/vpin_panel.parquet"

WINDOW_BUCKETS = 50          # VPIN rolling window
BUCKETS_PER_DAY = 50         # target ~50 buckets/day

ASSET_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}


def vpin_for_asset(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    df = df.sort_values("time_period_start_us").reset_index(drop=True)
    vol = df["volume_traded"].to_numpy()
    buy = df["taker_buy_base"].to_numpy()
    sell = vol - buy
    ts = df["time_period_start_us"].to_numpy()

    # Choose bucket size from MEDIAN daily volume so it adapts per asset.
    daily_vol = vol.sum() / max(1, (ts.max() - ts.min()) / (86400 * 1e6))
    bucket_size = daily_vol / BUCKETS_PER_DAY
    print(f"  {asset}: daily_vol={daily_vol:,.2f}  bucket_size={bucket_size:,.4f}")

    # Walk forward forming equal-volume buckets.
    cur_vol = 0.0
    cur_buy = 0.0
    cur_sell = 0.0
    bucket_ratios = []   # |B-S|/T per bucket
    bucket_buy_pct = []  # B/T per bucket
    bucket_end_ts = []   # last ts_us included in bucket
    # bar_bucket_idx[i] = idx of LAST COMPLETED bucket strictly before bar i
    bar_bucket_idx = np.full(len(df), -1, dtype=np.int64)

    completed = 0
    for i in range(len(df)):
        v = vol[i]; b = buy[i]; s = sell[i]
        # At BAR i we know bucket index already completed BEFORE adding this bar
        bar_bucket_idx[i] = completed - 1
        # Now add bar i's flow
        cur_vol += v; cur_buy += b; cur_sell += s
        while cur_vol >= bucket_size and bucket_size > 0:
            # Take exactly bucket_size off the front (proportional split if overshoot)
            ratio = bucket_size / cur_vol
            take_buy = cur_buy * ratio
            take_sell = cur_sell * ratio
            tot = take_buy + take_sell
            br = abs(take_buy - take_sell) / tot if tot > 0 else 0.0
            bucket_ratios.append(br)
            bucket_buy_pct.append(take_buy / tot if tot > 0 else 0.5)
            bucket_end_ts.append(ts[i])
            cur_buy -= take_buy
            cur_sell -= take_sell
            cur_vol -= bucket_size
            completed += 1

    n_buckets = len(bucket_ratios)
    print(f"  {asset}: completed buckets = {n_buckets}")
    if n_buckets == 0:
        return pd.DataFrame()

    # VPIN per bucket = rolling mean of last WINDOW_BUCKETS bucket ratios.
    br = np.array(bucket_ratios)
    vpin_per_bucket = pd.Series(br).rolling(WINDOW_BUCKETS, min_periods=10).mean().to_numpy()

    # Cumulative mean+std for z-score (causal, expanding window)
    cm = pd.Series(vpin_per_bucket).expanding(min_periods=50).mean().to_numpy()
    cs = pd.Series(vpin_per_bucket).expanding(min_periods=50).std().to_numpy()
    z_per_bucket = (vpin_per_bucket - cm) / np.where(cs > 0, cs, 1.0)

    # Sample at each bar i: vpin/z = value of bar_bucket_idx[i]
    vpin_bar = np.full(len(df), np.nan)
    z_bar = np.full(len(df), np.nan)
    buy_pct_bar = np.full(len(df), np.nan)
    for i, idx in enumerate(bar_bucket_idx):
        if idx >= 0 and idx < n_buckets:
            vpin_bar[i] = vpin_per_bucket[idx]
            z_bar[i] = z_per_bucket[idx]
            buy_pct_bar[i] = bucket_buy_pct[idx]

    out = pd.DataFrame({
        "asset": asset,
        "ts_us": ts,
        "vpin_value": vpin_bar,
        "vpin_zscore": z_bar,
        "current_bucket_buy_pct": buy_pct_bar,
    })
    return out


def main():
    cols = ["symbol_id", "time_period_start_us", "volume_traded", "taker_buy_base"]
    print(f"loading {PARQ}")
    df = pd.read_parquet(PARQ, columns=cols)
    print(f"loaded {len(df):,} rows")

    panels = []
    for sym, asset in ASSET_MAP.items():
        sub = df[df["symbol_id"] == sym]
        print(f"\n[{asset}] {len(sub):,} 1s bars")
        out = vpin_for_asset(sub, asset)
        if len(out) > 0:
            panels.append(out)

    if not panels:
        sys.exit("no panels produced")
    full = pd.concat(panels, ignore_index=True)
    print(f"\nwriting panel: {full.shape} -> {OUT}")
    full.to_parquet(OUT, index=False)
    print("done")
    # quick stats
    print("\nVPIN distribution per asset:")
    print(full.groupby("asset")["vpin_value"].describe(percentiles=[.5, .9, .95, .99]).to_string())


if __name__ == "__main__":
    main()
