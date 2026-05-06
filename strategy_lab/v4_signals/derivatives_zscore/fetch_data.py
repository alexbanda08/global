"""3-year derivatives data fetcher for the Crypto Derivatives Z-Score indicator.

Pulls from Binance Vision (free, keyless, official):
  data/v4/derivatives_zscore/metrics/{symbol}.parquet  — 5min OI + LSR + taker ratios (DAILY zips only)
  data/v4/derivatives_zscore/funding/{symbol}.parquet  — 8h funding rate (MONTHLY zips, daily for current month)

NOTE: Binance Vision dropped /liquidationSnapshot/ from the catalog. Liquidations
must be sourced separately (Coinglass / VPS coinapi parquets) — handled by a
sibling fetch_liquidations.py.

Symbols: BTCUSDT, ETHUSDT, SOLUSDT (perp).
Range: 2023-05-01 → today (≈3y).
"""
from __future__ import annotations
import io
import sys
import time
import zipfile
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
OUT_BASE = ROOT / "data" / "v4" / "derivatives_zscore"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
START = date(2023, 5, 1)
END = date.today()  # exclusive of today; current-month daily catch-up handles partials

VISION = "https://data.binance.vision/data/futures/um"
UA = {"User-Agent": "derivatives-zscore-fetcher/1.0"}


def http_get(url: str, timeout: int = 60) -> bytes | None:
    """GET bytes; return None on 404, raise on other errors."""
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def read_zip_csv(zbytes: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        with z.open(z.namelist()[0]) as f:
            return pd.read_csv(f)


def months_between(a: date, b: date) -> list[tuple[int, int]]:
    """List of (year, month) inclusive of `a`, exclusive of the month containing `b` (handled separately as daily)."""
    cur = date(a.year, a.month, 1)
    end_month = date(b.year, b.month, 1)
    out = []
    while cur < end_month:
        out.append((cur.year, cur.month))
        cur = date(cur.year + (cur.month // 12), (cur.month % 12) + 1, 1)
    return out


def days_in_month(y: int, m: int, end: date) -> list[date]:
    cur = date(y, m, 1)
    nxt = date(y + (m // 12), (m % 12) + 1, 1)
    last = min(nxt, end + timedelta(days=1))
    out = []
    while cur < last:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def url_metrics_monthly(sym: str, y: int, m: int) -> str:
    return f"{VISION}/monthly/metrics/{sym}/{sym}-metrics-{y:04d}-{m:02d}.zip"


def url_metrics_daily(sym: str, d: date) -> str:
    return f"{VISION}/daily/metrics/{sym}/{sym}-metrics-{d:%Y-%m-%d}.zip"


def url_funding_monthly(sym: str, y: int, m: int) -> str:
    return f"{VISION}/monthly/fundingRate/{sym}/{sym}-fundingRate-{y:04d}-{m:02d}.zip"


def url_funding_daily(sym: str, d: date) -> str:
    return f"{VISION}/daily/fundingRate/{sym}/{sym}-fundingRate-{d:%Y-%m-%d}.zip"


def fetch_one(url: str) -> pd.DataFrame | None:
    try:
        b = http_get(url)
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} {url}", file=sys.stderr)
        return None
    if b is None:
        return None
    try:
        return read_zip_csv(b)
    except Exception as e:
        print(f"  ZIP-ERR {url}: {e}", file=sys.stderr)
        return None


def fetch_dataset(name: str, sym: str, monthly_url, daily_url, max_workers: int = 8,
                  try_monthly: bool = True) -> pd.DataFrame:
    """Pull monthly archives for full months, daily for the current (partial) month.

    If try_monthly=False, goes straight to daily for ALL days (used for `metrics`,
    which Binance Vision only publishes daily).
    """
    months = months_between(START, END)
    cur_month_days = days_in_month(END.year, END.month, END - timedelta(days=1))

    daily_fallback: list[date] = []
    dfs: list[pd.DataFrame] = []

    if try_monthly:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut2key = {ex.submit(fetch_one, monthly_url(sym, y, m)): (y, m) for (y, m) in months}
            for fut in as_completed(fut2key):
                y, m = fut2key[fut]
                df = fut.result()
                if df is None:
                    daily_fallback.extend(days_in_month(y, m, date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)))
                    continue
                dfs.append(df)
        daily_targets = sorted(set(daily_fallback + cur_month_days))
    else:
        # Daily-only datasets (metrics): pull every day in the full range.
        daily_targets = []
        for (y, m) in months:
            daily_targets.extend(days_in_month(y, m, date(y + (m // 12), (m % 12) + 1, 1) - timedelta(days=1)))
        daily_targets.extend(cur_month_days)
        daily_targets = sorted(set(daily_targets))

    if daily_targets:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            fut2date = {ex.submit(fetch_one, daily_url(sym, d)): d for d in daily_targets}
            for fut in as_completed(fut2date):
                df = fut.result()
                if df is not None:
                    dfs.append(df)

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def normalize_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "create_time" in df.columns:
        df["create_time"] = pd.to_datetime(df["create_time"], utc=True)
    return df.drop_duplicates(subset=["create_time", "symbol"]).sort_values("create_time").reset_index(drop=True)


def normalize_funding(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "calc_time" in df.columns:
        # Vision funding csv: calc_time is integer milliseconds.
        df["calc_time"] = pd.to_datetime(df["calc_time"].astype("int64"), unit="ms", utc=True)
    elif "fundingTime" in df.columns:
        df["calc_time"] = pd.to_datetime(df["fundingTime"].astype("int64"), unit="ms", utc=True)
    # Vision per-symbol files have no 'symbol' column; dedupe by time only.
    return df.drop_duplicates(subset=["calc_time"]).sort_values("calc_time").reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=SYMBOLS)
    ap.add_argument("--datasets", nargs="+", default=["metrics", "funding"],
                    choices=["metrics", "funding"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip a (symbol, dataset) pair if its parquet already exists.")
    args = ap.parse_args()

    print(f"== Range: {START} → {END}  ({len(months_between(START, END))} full months + current)")
    print(f"== Symbols: {args.symbols}")
    print(f"== Datasets: {args.datasets}")
    print(f"== Workers: {args.workers}\n")

    for sym in args.symbols:
        if "metrics" in args.datasets:
            out = OUT_BASE / "metrics" / f"{sym}.parquet"
            if args.skip_existing and out.exists():
                print(f"[{sym}] metrics: SKIP (exists, {out.stat().st_size / 1e6:.1f}MB)")
                df = None
            else:
                t0 = time.time()
                print(f"[{sym}] metrics ...")
                df = fetch_dataset("metrics", sym, url_metrics_monthly, url_metrics_daily,
                                   args.workers, try_monthly=False)
            if df is not None:
                if not df.empty:
                    df = normalize_metrics(df)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    df.to_parquet(out)
                    print(f"  {sym} metrics: {len(df):,} rows  {df['create_time'].min()} → {df['create_time'].max()}  [{time.time()-t0:.1f}s]")
                else:
                    print(f"  {sym} metrics: EMPTY")

        if "funding" in args.datasets:
            out = OUT_BASE / "funding" / f"{sym}.parquet"
            if args.skip_existing and out.exists():
                print(f"[{sym}] funding: SKIP (exists, {out.stat().st_size / 1e6:.1f}MB)")
                continue
            t0 = time.time()
            print(f"[{sym}] funding ...")
            df = fetch_dataset("funding", sym, url_funding_monthly, url_funding_daily,
                               args.workers, try_monthly=True)
            if not df.empty:
                df = normalize_funding(df)
                out.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(out)
                print(f"  {sym} funding: {len(df):,} rows  {df['calc_time'].min()} → {df['calc_time'].max()}  [{time.time()-t0:.1f}s]")
            else:
                print(f"  {sym} funding: EMPTY")



if __name__ == "__main__":
    main()
