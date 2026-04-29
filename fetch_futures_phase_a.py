"""
Phase A — Binance Vision futures data (free, no credentials).

Downloads and normalises to Parquet:
  1. metrics         daily,    2020-09 → today     (OI, long/short ratios, taker ratio)
  2. fundingRate     monthly,  full history        (funding rate per 8h)
  3. premiumIndexKlines  monthly 1h,  full history (basis / premium index)

Symbols: BTCUSDT, ETHUSDT, SOLUSDT
Bucket:  data.binance.vision  (S3 public, no auth)
Output:  data/binance/futures/{dataset}/{symbol}/parquet/year=YYYY/part.parquet

All downloads parallel (threadpool, 8 workers), idempotent skip on existing.
"""
from __future__ import annotations
import io
import logging
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent / "data" / "binance" / "futures"
BASE = "https://data.binance.vision/data/futures/um"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
WORKERS = 8
TIMEOUT = 60

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s",
                    level=logging.INFO, datefmt="%H:%M:%S")
log = logging.getLogger("phase-a")


# ----------------------------------------------------------------------
# Schemas (from binance/binance-public-data docs)
# ----------------------------------------------------------------------
METRICS_COLS = [
    "create_time", "symbol", "sum_open_interest", "sum_open_interest_value",
    "count_toptrader_long_short_ratio", "sum_toptrader_long_short_ratio",
    "count_long_short_ratio", "sum_taker_long_short_vol_ratio",
]
FUNDING_COLS = ["calc_time", "funding_interval_hours", "last_funding_rate"]
# premiumIndexKlines: same as klines schema (12 cols)
KLINE_COLS = [
    "open_time","open","high","low","close","volume",
    "close_time","quote_volume","trades",
    "taker_buy_base","taker_buy_quote","ignore",
]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _fetch(url: str) -> bytes | None:
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def _download_one(url: str, local: Path) -> int:
    """Returns bytes downloaded, 0 on skip, -1 on 404."""
    if local.exists() and local.stat().st_size > 0:
        return 0
    local.parent.mkdir(parents=True, exist_ok=True)
    try:
        blob = _fetch(url)
    except Exception as e:
        log.warning(f"err {url}: {type(e).__name__}")
        return -2
    if blob is None:
        return -1
    local.write_bytes(blob)
    return len(blob)


def _iter_months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1; y += 1


def _iter_days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ----------------------------------------------------------------------
# 1. metrics (daily)
# ----------------------------------------------------------------------
def pull_metrics_days(symbol: str, start: date, end: date) -> tuple[int, int, int]:
    """Download all missing daily metrics zips. Returns (ok, skipped, missing)."""
    ok = skipped = missing = 0
    zip_dir = ROOT / "metrics" / symbol / "zips"
    jobs = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for d in _iter_days(start, end):
            url = f"{BASE}/daily/metrics/{symbol}/{symbol}-metrics-{d}.zip"
            local = zip_dir / f"{symbol}-metrics-{d}.zip"
            jobs.append(pool.submit(_download_one, url, local))
        for f in as_completed(jobs):
            n = f.result()
            if n == 0:   skipped += 1
            elif n > 0:  ok += 1
            elif n == -1: missing += 1
    return ok, skipped, missing


def build_metrics_parquet(symbol: str) -> int:
    zips = sorted((ROOT / "metrics" / symbol / "zips").glob("*.zip"))
    if not zips: return 0
    frames = []
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                name = zf.namelist()[0]
                raw = zf.read(name)
        except zipfile.BadZipFile:
            continue
        # detect header
        first = raw[:64].split(b",",1)[0]
        header = 0 if first[:1].isalpha() else None
        df = pd.read_csv(io.BytesIO(raw),
                         names=METRICS_COLS if header is None else None,
                         header=header)
        if header == 0:
            df.columns = [c.strip() for c in df.columns]
        frames.append(df)
    if not frames: return 0
    df = pd.concat(frames, ignore_index=True)
    df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    df = df.drop_duplicates("create_time").sort_values("create_time").reset_index(drop=True)
    # partition by year
    df["year"] = df["create_time"].dt.year
    out_root = ROOT / "metrics" / symbol / "parquet"
    for yr, g in df.groupby("year"):
        d = out_root / f"year={yr}"
        d.mkdir(parents=True, exist_ok=True)
        g.drop(columns=["year"]).to_parquet(d / "part.parquet",
                                            engine="pyarrow",
                                            compression="zstd",
                                            index=False)
    return len(df)


# ----------------------------------------------------------------------
# 2. fundingRate (monthly)
# ----------------------------------------------------------------------
def pull_funding_months(symbol: str, start: date, end: date) -> tuple[int, int, int]:
    ok = skipped = missing = 0
    zip_dir = ROOT / "fundingRate" / symbol / "zips"
    jobs = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for y, m in _iter_months(start, end):
            fname = f"{symbol}-fundingRate-{y:04d}-{m:02d}.zip"
            url = f"{BASE}/monthly/fundingRate/{symbol}/{fname}"
            local = zip_dir / fname
            jobs.append(pool.submit(_download_one, url, local))
        for f in as_completed(jobs):
            n = f.result()
            if n == 0:   skipped += 1
            elif n > 0:  ok += 1
            elif n == -1: missing += 1
    return ok, skipped, missing


def build_funding_parquet(symbol: str) -> int:
    zips = sorted((ROOT / "fundingRate" / symbol / "zips").glob("*.zip"))
    if not zips: return 0
    frames = []
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                raw = zf.read(zf.namelist()[0])
        except zipfile.BadZipFile:
            continue
        first = raw[:64].split(b",",1)[0]
        header = 0 if first[:1].isalpha() else None
        df = pd.read_csv(io.BytesIO(raw),
                         names=FUNDING_COLS if header is None else None,
                         header=header)
        if header == 0:
            df.columns = [c.strip() for c in df.columns]
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    # calc_time is ms epoch
    df["calc_time"] = pd.to_datetime(df["calc_time"], unit="ms", utc=True)
    df = df.drop_duplicates("calc_time").sort_values("calc_time").reset_index(drop=True)
    out = ROOT / "fundingRate" / symbol / "parquet" / "fundingRate.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", compression="zstd", index=False)
    return len(df)


# ----------------------------------------------------------------------
# 3. premiumIndexKlines (monthly, 1h)
# ----------------------------------------------------------------------
def pull_premium_months(symbol: str, start: date, end: date, interval: str = "1h"):
    ok = skipped = missing = 0
    zip_dir = ROOT / "premiumIndexKlines" / symbol / interval / "zips"
    jobs = []
    with ThreadPoolExecutor(WORKERS) as pool:
        for y, m in _iter_months(start, end):
            fname = f"{symbol}-{interval}-{y:04d}-{m:02d}.zip"
            url = f"{BASE}/monthly/premiumIndexKlines/{symbol}/{interval}/{fname}"
            local = zip_dir / fname
            jobs.append(pool.submit(_download_one, url, local))
        for f in as_completed(jobs):
            n = f.result()
            if n == 0:   skipped += 1
            elif n > 0:  ok += 1
            elif n == -1: missing += 1
    return ok, skipped, missing


def build_premium_parquet(symbol: str, interval: str = "1h") -> int:
    zips = sorted((ROOT / "premiumIndexKlines" / symbol / interval / "zips").glob("*.zip"))
    if not zips: return 0
    frames = []
    for zp in zips:
        try:
            with zipfile.ZipFile(zp) as zf:
                raw = zf.read(zf.namelist()[0])
        except zipfile.BadZipFile:
            continue
        first = raw[:64].split(b",",1)[0]
        header = 0 if first[:1].isalpha() else None
        df = pd.read_csv(io.BytesIO(raw),
                         names=KLINE_COLS if header is None else None,
                         header=header)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    # open_time / close_time is ms (pre-2025) or µs (2025+)
    def to_ts(s):
        unit = "us" if s.iloc[0] > 10**13 else "ms"
        return pd.to_datetime(s, unit=unit, utc=True)
    df["open_time"]  = to_ts(df["open_time"])
    df["close_time"] = to_ts(df["close_time"])
    df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    df = df.drop(columns=["ignore"])
    out = ROOT / "premiumIndexKlines" / symbol / interval / "parquet" / f"premium_{interval}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, engine="pyarrow", compression="zstd", index=False)
    return len(df)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    today = date.today()
    end_month = today.replace(day=1) - timedelta(days=1)   # last complete month
    metrics_start = date(2020, 9, 1)
    funding_start = date(2019, 9, 1)
    premium_start = date(2019, 9, 1)

    t0 = time.time()
    log.info(f"Output: {ROOT}")

    for sym in SYMBOLS:
        log.info(f"=== {sym} ===")

        log.info("  metrics (daily) ...")
        ok, sk, miss = pull_metrics_days(sym, metrics_start, today - timedelta(days=1))
        n = build_metrics_parquet(sym)
        log.info(f"    zips: ok={ok} skip={sk} missing={miss}  parquet rows={n:,}")

        log.info("  fundingRate (monthly) ...")
        ok, sk, miss = pull_funding_months(sym, funding_start, end_month)
        n = build_funding_parquet(sym)
        log.info(f"    zips: ok={ok} skip={sk} missing={miss}  parquet rows={n:,}")

        log.info("  premiumIndexKlines 1h (monthly) ...")
        ok, sk, miss = pull_premium_months(sym, premium_start, end_month, "1h")
        n = build_premium_parquet(sym, "1h")
        log.info(f"    zips: ok={ok} skip={sk} missing={miss}  parquet rows={n:,}")

    size_mb = sum(p.stat().st_size for p in ROOT.rglob("*") if p.is_file()) / 1024 / 1024
    log.info(f"Done. Total disk: {size_mb:.1f} MB  in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    sys.exit(main() or 0)
