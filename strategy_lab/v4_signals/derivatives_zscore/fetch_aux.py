"""Auxiliary data for the Crypto Derivatives Z-Score indicator.

Pulls:
  data/v4/derivatives_zscore/spot/{COINBASE,BINANCE}-BTC.parquet  — 1y BTC spot bars (1m)
  data/v4/derivatives_zscore/stables/dominance.parquet            — stablecoin market caps + dominance %

Coinbase: GET /products/BTC-USD/candles  (free, no auth, max 300 candles per request)
Binance:  GET /api/v3/klines               (used for the matched BINANCE leg of cb_premium)
CoinGecko: /coins/{id}/market_chart?vs_currency=usd&days=...  (free tier, 30+ rpm)

NOTE: 3y of 1m candles = ~1.6M bars / asset. Coinbase rate-limits hard at 1m granularity;
     we use 1h bars for the cb_premium z-score (TV indicator EMAs the premium anyway, so
     1h is plenty for the 21-bar Z window — equivalent to 21h ≈ 1d look-back).
"""
from __future__ import annotations
import time
import json
import urllib.request
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT_BASE = ROOT / "data" / "v4" / "derivatives_zscore"
OUT_SPOT = OUT_BASE / "spot"
OUT_STABLES = OUT_BASE / "stables"
OUT_SPOT.mkdir(parents=True, exist_ok=True)
OUT_STABLES.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "derivatives-zscore-aux/1.0"}


def http_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


# ────────────────────────────────────────────────────────────
#  Coinbase + Binance spot (for cb_premium)
# ────────────────────────────────────────────────────────────

def fetch_coinbase_1h(start_iso: str, end_iso: str) -> pd.DataFrame:
    """Coinbase Advanced Trade public candles. 3600s granularity, max 300 candles per call."""
    rows = []
    start = datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc)
    cur = start
    chunk = timedelta(hours=300)  # 300 hours per call
    while cur < end:
        nxt = min(cur + chunk, end)
        url = (f"https://api.exchange.coinbase.com/products/BTC-USD/candles"
               f"?granularity=3600&start={cur.isoformat()}&end={nxt.isoformat()}")
        try:
            data = http_json(url)
        except Exception as e:
            print(f"  coinbase {cur.date()}: {e}")
            time.sleep(2)
            continue
        rows.extend(data)  # [time, low, high, open, close, volume]
        cur = nxt
        time.sleep(0.25)  # avoid 429
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["time", "low", "high", "open", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="s", utc=True)
    return df.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def fetch_binance_1h(start_iso: str, end_iso: str, symbol: str = "BTCUSDT") -> pd.DataFrame:
    """Binance spot 1h klines for any symbol. Max 1000 per call."""
    rows = []
    start_ms = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    cur = start_ms
    while cur < end_ms:
        url = (f"https://api.binance.com/api/v3/klines"
               f"?symbol={symbol}&interval=1h&startTime={cur}&endTime={end_ms}&limit=1000")
        try:
            data = http_json(url)
        except Exception as e:
            print(f"  binance {datetime.utcfromtimestamp(cur/1000)}: {e}")
            time.sleep(2)
            continue
        if not data:
            break
        rows.extend(data)
        last = int(data[-1][0])
        if last <= cur:
            break
        cur = last + 1
        time.sleep(0.1)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=[
        "time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "_ignore",
    ])
    df["time"] = pd.to_datetime(df["time"].astype("int64"), unit="ms", utc=True)
    df["close"] = df["close"].astype(float)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    return df[["time", "open", "high", "low", "close", "volume"]].sort_values("time").reset_index(drop=True)


# ────────────────────────────────────────────────────────────
#  DefiLlama stablecoin market caps (free, no auth, full history)
# ────────────────────────────────────────────────────────────

# DefiLlama stablecoin IDs — discovered via /stablecoins endpoint.
STABLE_COINS = {
    "USDT":  1,    # Tether
    "USDC":  2,    # USD Coin
    "DAI":   5,    # Dai
    "FDUSD": 119,  # First Digital USD
    "USDE":  146,  # Ethena USDe
    "PYUSD": 120,  # PayPal USD
    "RLUSD": 250,  # Ripple USD
    "USDS":  209,  # Sky Dollar (what the Pine indicator calls "USDS2")
}


def fetch_dl_stablecoin(coin_id: int) -> pd.DataFrame:
    """DefiLlama daily peggedUSD circulating market cap series for one stablecoin."""
    url = f"https://stablecoins.llama.fi/stablecoincharts/all?stablecoin={coin_id}"
    data = http_json(url, timeout=45)
    if not data:
        return pd.DataFrame()
    rows = []
    for d in data:
        try:
            ts = int(d["date"])
            cap = d.get("totalCirculatingUSD", {}).get("peggedUSD")
            if cap is None:
                continue
            rows.append((ts, float(cap)))
        except Exception:
            continue
    df = pd.DataFrame(rows, columns=["ts", "market_cap"])
    df["time"] = pd.to_datetime(df["ts"], unit="s", utc=True)
    return df[["time", "market_cap"]].drop_duplicates("time").sort_values("time").reset_index(drop=True)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--only", nargs="+", choices=["coinbase", "binance", "stables"],
                    default=["coinbase", "binance", "stables"])
    args = ap.parse_args()

    start = "2023-05-01"
    end = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

    if "coinbase" in args.only:
        out = OUT_SPOT / "COINBASE-BTC-1h.parquet"
        if args.skip_existing and out.exists():
            print(f"== Coinbase: SKIP (exists {out.stat().st_size/1e6:.1f}MB)")
        else:
            print(f"== Coinbase BTC-USD 1h: {start} → {end}")
            cb = fetch_coinbase_1h(start, end)
            if not cb.empty:
                cb.to_parquet(out)
                print(f"  Coinbase: {len(cb):,} bars  {cb['time'].min()} → {cb['time'].max()}")
            else:
                print("  Coinbase: EMPTY")

    if "binance" in args.only:
        for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tag = sym.replace("USDT", "")
            out = OUT_SPOT / f"BINANCE-{tag}-1h.parquet"
            if args.skip_existing and out.exists():
                print(f"== Binance {tag}: SKIP (exists {out.stat().st_size/1e6:.1f}MB)")
                continue
            print(f"\n== Binance {sym} spot 1h: {start} → {end}")
            bn = fetch_binance_1h(start, end, symbol=sym)
            if not bn.empty:
                bn.to_parquet(out)
                print(f"  Binance {tag}: {len(bn):,} bars  {bn['time'].min()} → {bn['time'].max()}")
            else:
                print(f"  Binance {tag}: EMPTY")

    if "stables" not in args.only:
        return

    print(f"\n== Stablecoin market caps via DefiLlama (daily, full history)")
    rows = []
    for tag, coin_id in STABLE_COINS.items():
        try:
            df = fetch_dl_stablecoin(coin_id)
            if df.empty:
                print(f"  {tag}: empty")
                continue
            df["tag"] = tag
            rows.append(df)
            print(f"  {tag} (id={coin_id}): {len(df):,} daily points  {df['time'].min().date()} → {df['time'].max().date()}")
        except Exception as e:
            print(f"  {tag}: {type(e).__name__} {e}")
        time.sleep(0.5)
    if rows:
        out = pd.concat(rows, ignore_index=True)
        out.to_parquet(OUT_STABLES / "market_caps.parquet")
        print(f"  → wrote {len(out):,} rows to stables/market_caps.parquet")


if __name__ == "__main__":
    main()
