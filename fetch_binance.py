"""
Bulk download Binance monthly 1m klines from data.binance.vision.

Source: https://github.com/binance/binance-public-data
Pairs:  BTCUSDT (2017-08→), ETHUSDT (2017-08→), SOLUSDT (2020-08→)
Output: ./data/binance/
          raw_zips/{SYMBOL}/{SYMBOL}-1m-YYYY-MM.zip
          parquet/{SYMBOL}/1m/year=YYYY/part.parquet    (appended per year)

Idempotent: skips already-downloaded zips and already-written years when
the zip count for that year is unchanged.

Verifies SHA256 via the .CHECKSUM sibling file.
"""

from __future__ import annotations

import hashlib
import io
import logging
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import requests

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
BASE = "https://data.binance.vision/data/spot/monthly/klines"
ROOT = Path(__file__).parent / "data" / "binance"
RAW  = ROOT / "raw_zips"
PARQ = ROOT / "parquet"

SYMBOLS = {
    "BTCUSDT": date(2017, 8, 1),
    "ETHUSDT": date(2017, 8, 1),
    "SOLUSDT": date(2020, 8, 1),
}

# Binance publishes previous month ~1–2 days into the new month.
# We stop at first-of-current-month to stay safe.
END = date.today().replace(day=1)

INTERVAL = "1m"
MAX_WORKERS = 8
TIMEOUT = 60

# Binance kline CSV has 12 columns (docs: binance/binance-public-data).
COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(message)s",
    level=logging.INFO,
    datefmt="%H:%M:%S",
)
log = logging.getLogger("binance-fetch")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) < (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            m = 1
            y += 1


def url_for(symbol: str, y: int, m: int) -> str:
    return f"{BASE}/{symbol}/{INTERVAL}/{symbol}-{INTERVAL}-{y:04d}-{m:02d}.zip"


def fetch(url: str) -> bytes | None:
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


@dataclass
class MonthResult:
    symbol: str
    year: int
    month: int
    status: str           # "ok" | "skipped" | "missing" | "error"
    rows: int = 0
    note: str = ""


def download_month(symbol: str, y: int, m: int) -> MonthResult:
    zip_dir = RAW / symbol
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{symbol}-{INTERVAL}-{y:04d}-{m:02d}.zip"

    if zip_path.exists() and zip_path.stat().st_size > 0:
        return MonthResult(symbol, y, m, "skipped")

    url = url_for(symbol, y, m)
    try:
        blob = fetch(url)
    except Exception as e:
        return MonthResult(symbol, y, m, "error", note=f"{type(e).__name__}: {e}")

    if blob is None:
        return MonthResult(symbol, y, m, "missing", note="404")

    # Verify checksum (optional — skip on 404 for very early months).
    try:
        cs = fetch(url + ".CHECKSUM")
        if cs:
            expected = cs.decode().split()[0].strip().lower()
            actual = hashlib.sha256(blob).hexdigest().lower()
            if expected != actual:
                return MonthResult(symbol, y, m, "error",
                                   note=f"sha256 mismatch {actual[:8]}!={expected[:8]}")
    except Exception:
        pass  # checksum is best-effort

    zip_path.write_bytes(blob)
    return MonthResult(symbol, y, m, "ok")


# ----------------------------------------------------------------------
# Parquet build — one file per (symbol, year)
# ----------------------------------------------------------------------
def build_parquet_for_year(symbol: str, year: int) -> int:
    zips = sorted((RAW / symbol).glob(f"{symbol}-{INTERVAL}-{year}-*.zip"))
    if not zips:
        return 0

    out_dir = PARQ / symbol / INTERVAL / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "part.parquet"

    # Re-derive only if source zip count / newest mtime > parquet mtime.
    if out_path.exists():
        newest = max(z.stat().st_mtime for z in zips)
        if out_path.stat().st_mtime >= newest:
            return 0  # up-to-date

    frames = []
    for zp in zips:
        with zipfile.ZipFile(zp) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as fh:
                # Some 2025+ files include a header row; detect + handle.
                raw = fh.read()
        # Header detection: first cell is non-numeric if a header is present.
        first = raw[:64].split(b",", 1)[0]
        header = 0 if first[:1].isalpha() else None
        df = pd.read_csv(io.BytesIO(raw), names=COLS if header is None else None,
                         header=header)
        # Column normalization (when header row differs from our alias list).
        if header == 0:
            df.columns = [c.lower() for c in df.columns]
            # Map binance header names to our COLS
            df = df.rename(columns={
                "number_of_trades": "trades",
                "quote_asset_volume": "quote_volume",
                "taker_buy_base_asset_volume": "taker_buy_base",
                "taker_buy_quote_asset_volume": "taker_buy_quote",
            })
            df = df[COLS]
        frames.append(df)

    if not frames:
        return 0

    df = pd.concat(frames, ignore_index=True)

    # open_time/close_time are in ms (pre-2025) or µs (2025+). Normalize.
    def to_ts(s: pd.Series) -> pd.Series:
        # Heuristic: ms columns are ≤ ~2e12 up to year 2033. µs are ~1e15.
        unit = "us" if s.iloc[0] > 10**13 else "ms"
        return pd.to_datetime(s, unit=unit, utc=True)

    df["open_time"]  = to_ts(df["open_time"])
    df["close_time"] = to_ts(df["close_time"])

    num_cols = ["open", "high", "low", "close", "volume",
                "quote_volume", "taker_buy_base", "taker_buy_quote"]
    df[num_cols] = df[num_cols].astype("float64")
    df["trades"] = df["trades"].astype("int64")
    df = df.drop(columns=["ignore"])

    # Sort + dedupe + filter exactly to this year (safety against bad files).
    df = (df.sort_values("open_time")
            .drop_duplicates("open_time")
            .reset_index(drop=True))
    df = df[df["open_time"].dt.year == year]

    df.to_parquet(out_path, engine="pyarrow", compression="zstd", index=False)
    return len(df)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    PARQ.mkdir(parents=True, exist_ok=True)

    # 1) Download all months in parallel
    jobs: list[tuple[str, int, int]] = []
    for sym, start in SYMBOLS.items():
        for y, m in month_iter(start, END):
            jobs.append((sym, y, m))

    log.info("Downloading %d monthly zips (workers=%d)...", len(jobs), MAX_WORKERS)

    counts = {"ok": 0, "skipped": 0, "missing": 0, "error": 0}
    errors: list[MonthResult] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futs = [pool.submit(download_month, s, y, m) for s, y, m in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            res = fut.result()
            counts[res.status] += 1
            if res.status == "error":
                errors.append(res)
                log.warning("  err  %s %04d-%02d %s", res.symbol, res.year, res.month, res.note)
            if i % 50 == 0:
                log.info("  progress %d/%d  ok=%d skipped=%d missing=%d error=%d",
                         i, len(jobs), counts["ok"], counts["skipped"],
                         counts["missing"], counts["error"])

    log.info("Download summary: %s", counts)
    if errors:
        log.warning("%d errors. First 5: %s", len(errors),
                    [(e.symbol, e.year, e.month, e.note) for e in errors[:5]])

    # 2) Build per-(symbol, year) parquet
    log.info("Building parquet files...")
    total_rows = 0
    for sym in SYMBOLS:
        years = sorted({int(p.name.split("-")[2])
                        for p in (RAW / sym).glob(f"{sym}-*.zip")})
        for y in years:
            n = build_parquet_for_year(sym, y)
            if n:
                log.info("  %s %d → %d rows", sym, y, n)
            total_rows += n

    log.info("Done. Rows written this run: %d", total_rows)
    log.info("Data root: %s", ROOT)
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
