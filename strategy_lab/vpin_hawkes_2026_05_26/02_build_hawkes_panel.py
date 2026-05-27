"""
Hawkes process intensity panel — EWMA approximation for speed.

Approach (per CLAUDE.md guidance: simpler proxy is acceptable):
  - Treat each 1s bar as a candidate event.
  - Mark BUY event if buy_vol > 0.6*total, SELL event if buy_vol < 0.4*total, neutral else.
  - Hawkes intensity = mu + sum over past 300s of alpha * exp(-beta * dt)
  - Approximate as EXPONENTIAL MOVING AVERAGE of event indicator:
      lambda_buy(t)  = decay * lambda_buy(t-1)  + (1-decay) * is_buy_event(t)
      lambda_sell(t) = decay * lambda_sell(t-1) + (1-decay) * is_sell_event(t)
    decay chosen so half-life ~= 60s (so 300s lookback ~ 5 half-lives).
  - This is the EXACT closed-form solution of a 1-step exponential Hawkes kernel
    with self-excitation alpha=(1-decay), decay-rate beta, baseline implicit in EMA.
  - We also weight each event by its trade intensity (trades_count) to recover
    volume/burst character.

Outputs: data/v4/canonical/_results/hawkes_panel.parquet
Cols: asset, ts_us, lambda_buy, lambda_sell, lambda_total, lambda_imbalance, recent_burst
"""
import pandas as pd
import numpy as np
import math

PARQ = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/klines_1s/binance_1s_28d.parquet"
OUT = "C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/hawkes_panel.parquet"

ASSET_MAP = {
    "BINANCE_SPOT_BTC_USDT": "BTC",
    "BINANCE_SPOT_ETH_USDT": "ETH",
    "BINANCE_SPOT_SOL_USDT": "SOL",
}

# Half-life 60s -> decay = exp(ln(0.5)/60)
HALF_LIFE_S = 60
DECAY = math.exp(math.log(0.5) / HALF_LIFE_S)

# Burst detection: rolling mean of lambda_total over BURST_WINDOW seconds.
BURST_WINDOW = 3600   # 1 hour smoothing
BURST_MULT = 1.5


def hawkes_for_asset(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    df = df.sort_values("time_period_start_us").reset_index(drop=True)
    ts = df["time_period_start_us"].to_numpy()
    vol = df["volume_traded"].to_numpy()
    buy = df["taker_buy_base"].to_numpy()
    trades = df["trades_count"].to_numpy().astype(float)

    # Per-bar event flags
    pct_buy = np.where(vol > 0, buy / vol, 0.5)
    is_buy = (pct_buy > 0.6).astype(float)
    is_sell = (pct_buy < 0.4).astype(float)

    # Weight each event by trade-count (clipped to avoid huge spikes)
    w = np.clip(trades, 0, np.quantile(trades[trades > 0], 0.99) if (trades > 0).any() else 1.0)
    # Normalize so the typical event has weight ~1
    typical = np.median(w[w > 0]) if (w > 0).any() else 1.0
    if typical > 0:
        w = w / typical

    buy_event = is_buy * w
    sell_event = is_sell * w

    # EMA Hawkes intensities (vectorized via for loop is fine — 1.8M ops/asset)
    lam_buy = np.zeros(len(df))
    lam_sell = np.zeros(len(df))
    lb = 0.0
    ls = 0.0
    for i in range(len(df)):
        lb = DECAY * lb + (1.0 - DECAY) * buy_event[i]
        ls = DECAY * ls + (1.0 - DECAY) * sell_event[i]
        lam_buy[i] = lb
        lam_sell[i] = ls

    lam_tot = lam_buy + lam_sell
    lam_imb = np.where(lam_tot > 0, (lam_buy - lam_sell) / lam_tot, 0.0)

    # Rolling mean of lambda_total over BURST_WINDOW for burst detection.
    lam_tot_ser = pd.Series(lam_tot)
    lam_tot_mean = lam_tot_ser.rolling(BURST_WINDOW, min_periods=600).mean().to_numpy()
    recent_burst = (lam_tot > BURST_MULT * lam_tot_mean).astype(np.int8)

    return pd.DataFrame({
        "asset": asset,
        "ts_us": ts,
        "lambda_buy": lam_buy.astype(np.float32),
        "lambda_sell": lam_sell.astype(np.float32),
        "lambda_total": lam_tot.astype(np.float32),
        "lambda_imbalance": lam_imb.astype(np.float32),
        "recent_burst": recent_burst,
    })


def main():
    cols = ["symbol_id", "time_period_start_us", "volume_traded", "taker_buy_base", "trades_count"]
    print(f"loading {PARQ}")
    df = pd.read_parquet(PARQ, columns=cols)
    print(f"loaded {len(df):,} rows, decay={DECAY:.6f} half-life={HALF_LIFE_S}s")

    panels = []
    for sym, asset in ASSET_MAP.items():
        sub = df[df["symbol_id"] == sym]
        print(f"\n[{asset}] {len(sub):,} 1s bars")
        out = hawkes_for_asset(sub, asset)
        print(f"  lam_total median={np.nanmedian(out.lambda_total):.4f} q95={np.nanquantile(out.lambda_total,0.95):.4f}")
        print(f"  burst frac={out.recent_burst.mean():.3f}")
        panels.append(out)

    full = pd.concat(panels, ignore_index=True)
    print(f"\nwriting panel: {full.shape} -> {OUT}")
    full.to_parquet(OUT, index=False)
    print("done")


if __name__ == "__main__":
    main()
