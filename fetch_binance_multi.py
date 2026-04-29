"""
Download Binance monthly klines directly at 1h + 4h (no 1m resample).

Extension of fetch_binance.py for additional pairs. Pulls only the
timeframes we actually backtest on, keeping disk usage tiny (~5 MB/pair).

Source: https://data.binance.vision/data/spot/monthly/klines/{SYM}/{TF}/
Output: data/binance/parquet/{SYM}/{TF}/year=YYYY/part.parquet
        (same layout engine.load expects)

Idempotent: skips cached zips; rebuilds parquet only when zip count changes.
"""
from __future__ import annotations
import hashlib, io, logging, sys, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import pandas as pd
import requests

BASE = "https://data.binance.vision/data/spot/monthly/klines"
ROOT = Path(__file__).parent / "data" / "binance"
RAW  = ROOT / "raw_zips"
PARQ = ROOT / "parquet"

# New universe — extend as needed.
SYMBOLS = [
    "BNBUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "AVAXUSDT",
    "LINKUSDT",
    "ADAUSDT",
]

# Timeframes that match our validated strategies.
INTERVALS = ["15m", "1h", "4h"]

# Start far back; 404s on early months are fine (auto-skip).
START = date(2017, 1, 1)
END = date.today().replace(day=1)

MAX_WORKERS = 8
TIMEOUT = 60

COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades",
    "taker_buy_base", "taker_buy_quote", "ignore",
]

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s",
                    level=logging.INFO, datefmt="%H:%M:%S")
log = logging.getLogger("fetch-multi")


def month_iter(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) < (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            m = 1; y += 1


def url_for(sym: str, tf: str, y: int, m: int) -> str:
    return f"{BASE}/{sym}/{tf}/{sym}-{tf}-{y:04d}-{m:02d}.zip"


def fetch(url: str) -> bytes | None:
    r = requests.get(url, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


@dataclass
class MonthResult:
    symbol: str; tf: str; year: int; month: int
    status: str; rows: int = 0; note: str = ""


def download_month(sym: str, tf: str, y: int, m: int) -> MonthResult:
    zip_dir = RAW / sym / tf
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{sym}-{tf}-{y:04d}-{m:02d}.zip"

    if zip_path.exists() and zip_path.stat().st_size > 0:
        return MonthResult(sym, tf, y, m, "skipped")

    try:
        blob = fetch(url_for(sym, tf, y, m))
    except Exception as e:
        return MonthResult(sym, tf, y, m, "error", note=f"{type(e).__name__}: {e}")

    if blob is None:
        return MonthResult(sym, tf, y, m, "missing")

    zip_path.write_bytes(blob)
    # Row count (for logging).
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        for name in zf.namelist():
            if name.endswith(".csv"):
                rows = sum(1 for _ in zf.open(name))
                return MonthResult(sym, tf, y, m, "ok", rows=rows)
    return MonthResult(sym, tf, y, m, "ok")


def read_zip(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if name.endswith(".csv"):
                with zf.open(name) as fh:
                    df = pd.read_csv(fh, header=None, names=COLS)
                    return df
    raise RuntimeError(f"no csv in {path}")


def build_parquet_for_year(sym: str, tf: str, year: int) -> int:
    zips = sorted((RAW / sym / tf).glob(f"{sym}-{tf}-{year:04d}-*.zip"))
    if not zips:
        return 0
    frames = [read_zip(z) for z in zips]
    df = pd.concat(frames, ignore_index=True)

    # Binance klines sometimes have microsecond-scale timestamps after ~2023;
    # detect whether the value is ms or us.
    ts_max = int(df["open_time"].max())
    unit = "us" if ts_max > 10**15 else "ms"
    df["open_time"]  = pd.to_datetime(df["open_time"],  unit=unit, utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit=unit, utc=True)
    df = df.drop(columns=["ignore"])
    df = df.astype({
        "open":"float64","high":"float64","low":"float64",
        "close":"float64","volume":"float64",
        "quote_volume":"float64","trades":"int64",
        "taker_buy_base":"float64","taker_buy_quote":"float64",
    })
    df = df.sort_values("open_time").drop_duplicates("open_time")

    out_dir = PARQ / sym / tf / f"year={year}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "part.parquet"
    df.to_parquet(out, index=False)
    return len(df)


def main():
    tasks = []
    for sym in SYMBOLS:
        for tf in INTERVALS:
            for y, m in month_iter(START, END):
                tasks.append((sym, tf, y, m))

    log.info(f"queued {len(tasks)} month-downloads "
             f"({len(SYMBOLS)} pairs × {len(INTERVALS)} tfs)")

    ok = skipped = missing = errors = 0
    years_touched: dict[tuple[str,str], set[int]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(download_month, *t): t for t in tasks}
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            if r.status == "ok":
                ok += 1
                years_touched.setdefault((r.symbol, r.tf), set()).add(r.year)
            elif r.status == "skipped":
                skipped += 1
            elif r.status == "missing":
                missing += 1
            else:
                errors += 1
                log.warning(f"{r.symbol} {r.tf} {r.year}-{r.month:02d}: {r.note}")
            if i % 50 == 0:
                log.info(f"  progress {i}/{len(tasks)} ok={ok} skip={skipped} 404={missing} err={errors}")
    log.info(f"downloads done: ok={ok} skipped={skipped} 404={missing} errors={errors}")

    # Rebuild parquet for any (sym,tf,year) that saw new zips.
    # Also always rebuild years that have zips but no parquet yet.
    rebuild = set()
    for sym in SYMBOLS:
        for tf in INTERVALS:
            for z in (RAW / sym / tf).glob(f"{sym}-{tf}-*.zip"):
                y = int(z.stem.split("-")[-2])
                pq = PARQ / sym / tf / f"year={y}" / "part.parquet"
                if not pq.exists():
                    rebuild.add((sym, tf, y))
    rebuild.update({(s, t, y) for (s, t), ys in years_touched.items() for y in ys})

    log.info(f"rebuilding {len(rebuild)} year-parquet files")
    for sym, tf, y in sorted(rebuild):
        try:
            n = build_parquet_for_year(sym, tf, y)
            log.info(f"  parquet {sym} {tf} {y}: {n:,} rows")
        except Exception as e:
            log.error(f"  parquet {sym} {tf} {y}: {e}")

    log.info("done.")


if __name__ == "__main__":
    sys.exit(main() or 0)
