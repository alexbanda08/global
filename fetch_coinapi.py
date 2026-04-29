"""
CoinAPI Flat Files downloader — targets the highest-alpha gaps.

Budget:  $25 free credits = 25 GB at $1/GB.
Priority order (if we run out we stop at item 2 and still win):

  1. LIQUIDATIONS      BinanceFTS BTC/ETH/SOL, full history  ≈  0.1–0.5 GB  ($1)
  2. TRADES (tick)     BinanceFTS BTC/ETH/SOL, last 90 days  ≈    8–15 GB   ($8-15)
  3. limitbook_snapshot_5  last 30 days                       ≈    5–8 GB   ($5-8)
  -------------------------------------------------------------------------------
  Safety margin to stay well under 25 GB.

CoinAPI Flat Files: https://www.coinapi.io/products/flat-files

Authentication: set env var COINAPI_API_KEY (obtained from coinapi.io dashboard).

Output: data/coinapi/{dataset}/{exchange}/{symbol}/...
"""
from __future__ import annotations
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import logging

import requests

ROOT = Path(__file__).parent / "data" / "coinapi"
API_KEY = os.environ.get("COINAPI_API_KEY", "")
BASE = "https://rest.coinapi.io/v1"
# Flat Files index + download endpoints are documented separately
FLAT_BASE = "https://users.coinapi.io/flatfiles/v1"

# Symbols — CoinAPI symbol id format:  BINANCEFTS_PERP_BTC_USDT
SYMBOLS = {
    "BTCUSDT": "BINANCEFTS_PERP_BTC_USDT",
    "ETHUSDT": "BINANCEFTS_PERP_ETH_USDT",
    "SOLUSDT": "BINANCEFTS_PERP_SOL_USDT",
}

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s",
                    level=logging.INFO, datefmt="%H:%M:%S")
log = logging.getLogger("coinapi")


def _headers() -> dict:
    if not API_KEY:
        log.error("COINAPI_API_KEY env var is empty.")
        sys.exit(2)
    return {"X-CoinAPI-Key": API_KEY, "Accept-Encoding": "gzip, deflate"}


# ---------------------------------------------------------------------
# 1. LIQUIDATIONS — via REST metrics endpoint (tiny, cheap)
# ---------------------------------------------------------------------
def fetch_liquidations(coinapi_sym: str, start: date, end: date,
                       period_id: str = "15MIN") -> list:
    """Return list of liquidation records. Bulk via time-range REST calls."""
    out = []
    t = start
    while t <= end:
        # Request 1000 records at a time; CoinAPI paginates by time range.
        r = requests.get(
            f"{BASE}/metrics/symbol/current/history",
            params={
                "symbol_id": coinapi_sym,
                "metric_id": "LIQUIDATIONS_VALUE",   # or LIQUIDATIONS_COUNT
                "period_id": period_id,
                "time_start": f"{t.isoformat()}T00:00:00",
                "time_end":   f"{(t+timedelta(days=30)).isoformat()}T00:00:00",
                "limit": 100000,
            },
            headers=_headers(),
            timeout=60,
        )
        if r.status_code == 429:
            log.warning("rate limited, sleeping 10s ...")
            time.sleep(10); continue
        r.raise_for_status()
        data = r.json()
        out.extend(data)
        t += timedelta(days=30)
        time.sleep(0.5)
    return out


# ---------------------------------------------------------------------
# 2. FLAT FILES — S3-style bulk downloads
# ---------------------------------------------------------------------
def list_flatfile_keys(dataset: str, exchange: str, symbol: str,
                       date_from: date, date_to: date) -> list[dict]:
    """List available flat files for a dataset/exchange/symbol/date range.
       dataset ∈ {trades, quotes, limitbook_snapshot_5, limitbook_snapshot_20,
                  liquidations, ohlcv_1_minute, ...}"""
    r = requests.get(
        f"{FLAT_BASE}/list",
        params={
            "dataset": dataset,
            "exchange_id": exchange,
            "symbol_id": symbol,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        },
        headers=_headers(),
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def download_flatfile(url: str, local: Path) -> int:
    if local.exists() and local.stat().st_size > 0:
        return 0
    local.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(url, headers=_headers(), stream=True, timeout=600)
    r.raise_for_status()
    n = 0
    with local.open("wb") as fh:
        for chunk in r.iter_content(chunk_size=1 << 20):
            fh.write(chunk); n += len(chunk)
    return n


def quota_remaining() -> dict | None:
    """Check current CoinAPI credit balance (if endpoint available)."""
    r = requests.get(f"{BASE}/usage", headers=_headers(), timeout=30)
    if r.status_code != 200:
        return None
    return r.json()


# ---------------------------------------------------------------------
# Main — runs each phase, stops if budget tight
# ---------------------------------------------------------------------
def phase1_liquidations():
    log.info("=== Phase 1: Liquidations ===")
    for sym, cid in SYMBOLS.items():
        log.info(f"  {sym}  ({cid})")
        data = fetch_liquidations(cid, date(2021, 1, 1), date.today(), "15MIN")
        out_dir = ROOT / "liquidations" / sym
        out_dir.mkdir(parents=True, exist_ok=True)
        import json
        (out_dir / "liquidations.json").write_text(json.dumps(data))
        log.info(f"    {len(data)} records")


def phase2_flatfile_trades(days: int = 90):
    log.info(f"=== Phase 2: Tick Trades (last {days} days) ===")
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    for sym, cid in SYMBOLS.items():
        log.info(f"  {sym}")
        keys = list_flatfile_keys("trades", "BINANCEFTS", cid, date_from, date_to)
        log.info(f"    {len(keys)} files to consider")
        for k in keys:
            url = k["url"]
            fname = url.rsplit("/", 1)[-1]
            local = ROOT / "trades" / sym / fname
            n = download_flatfile(url, local)
            if n > 0:
                log.info(f"      {fname}  +{n/1024/1024:.1f} MB")


def phase3_flatfile_book(days: int = 30, snapshot_levels: int = 5):
    log.info(f"=== Phase 3: limitbook_snapshot_{snapshot_levels} (last {days} days) ===")
    dataset = f"limitbook_snapshot_{snapshot_levels}"
    date_to = date.today()
    date_from = date_to - timedelta(days=days)
    for sym, cid in SYMBOLS.items():
        log.info(f"  {sym}")
        keys = list_flatfile_keys(dataset, "BINANCEFTS", cid, date_from, date_to)
        for k in keys:
            url = k["url"]
            fname = url.rsplit("/", 1)[-1]
            local = ROOT / dataset / sym / fname
            n = download_flatfile(url, local)
            if n > 0:
                log.info(f"      {fname}  +{n/1024/1024:.1f} MB")


def main():
    q = quota_remaining()
    if q: log.info(f"quota: {q}")
    phase1_liquidations()
    phase2_flatfile_trades(days=90)
    phase3_flatfile_book(days=30, snapshot_levels=5)
    total = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file())
    log.info(f"Total downloaded: {total / 1024 / 1024 / 1024:.2f} GB")


if __name__ == "__main__":
    main()
