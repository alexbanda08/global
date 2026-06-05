"""
Backfill canonical klines_1s.parquet with Binance Vision 1s spot klines.
Scope: Jan 1 2026 -> Apr 6 2026 (abuts existing Apr 7+ data), 6 coins BTC/ETH/SOL/XRP/BNB/DOGE.
Disjoint from existing (existing = Apr 7+; XRP/BNB/DOGE entirely new) -> pure append, no dedup.

Binance Vision kline CSV (12 cols): open_time, open, high, low, close, volume, close_time,
quote_volume, trades, taker_buy_base, taker_buy_quote, ignore. 2025+ files use MICROsecond
open_time and include a header row -> handled (try_cast filter + unit autodetect).
Canonical schema leaves time_open_us/time_close_us/taker_buy_base/taker_buy_quote NULL (match existing).
"""
import os, time, zipfile, urllib.request, shutil
from pathlib import Path
import duckdb

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\klines_1s.parquet")
RAW = Path(r"D:\bv1s_raw")
COINS = ["BTC", "ETH", "SOL", "XRP", "BNB", "DOGE"]
MONTHS = ["2026-01", "2026-02", "2026-03"]
DAYS = [f"2026-04-0{d}" for d in range(1, 7)]  # Apr 1..6
JAN1_US = 1767225600000000
APR7_US = 1775520000000000  # exclusive cap (existing data starts here)
BASE = "https://data.binance.vision/data/spot"

def log(m): print(f"[bv1s] {time.strftime('%H:%M:%S')} {m}", flush=True)

def dl(url, dest, tries=4):
    if dest.exists() and dest.stat().st_size > 0: return True
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return True
        except Exception as e:
            if "404" in str(e): log(f"    404 (skip) {url}");
            if "404" in str(e): return False
            log(f"    retry {i+1} {dest.name}: {e}"); time.sleep(3)
    return False

# ---- phase 1: download + extract ----
log("=== phase 1: download + extract ===")
for coin in COINS:
    sym = f"{coin}USDT"; d = RAW / sym; d.mkdir(parents=True, exist_ok=True)
    items = [("monthly", m) for m in MONTHS] + [("daily", day) for day in DAYS]
    for kind, tag in items:
        zf = d / f"{sym}-1s-{tag}.zip"
        url = f"{BASE}/{kind}/klines/{sym}/1s/{sym}-1s-{tag}.zip"
        csv = d / f"{sym}-1s-{tag}.csv"
        if csv.exists() and csv.stat().st_size > 0: continue
        if not dl(url, zf): log(f"  MISS {sym} {tag}"); continue
        try:
            with zipfile.ZipFile(zf) as z: z.extractall(d)
            zf.unlink()  # keep only csv
        except Exception as e:
            log(f"  BAD ZIP {zf.name}: {e}")
    n = len(list(d.glob("*.csv")))
    log(f"  {sym}: {n} csv files ready")

# ---- phase 2: convert each symbol -> temp parquet ----
log("=== phase 2: convert ===")
con = duckdb.connect(); con.execute("PRAGMA memory_limit='10GB'"); con.execute("PRAGMA threads=6")
TMP = RAW / "_parts"; TMP.mkdir(exist_ok=True)
cols = {f"c{i}": "VARCHAR" for i in range(12)}
colspec = "{" + ",".join(f"'{k}':'{v}'" for k, v in cols.items()) + "}"
parts = []
for coin in COINS:
    sym = f"{coin}USDT"; src = str(RAW / sym / "*.csv").replace("\\", "/")
    if not list((RAW / sym).glob("*.csv")): log(f"  {sym}: NO csv, skip"); continue
    out = str(TMP / f"{coin}.parquet").replace("\\", "/")
    q = f"""
    COPY (
      WITH raw AS (
        SELECT * FROM read_csv('{src}', header=false, columns={colspec}, ignore_errors=true)
        WHERE try_cast(c0 AS BIGINT) IS NOT NULL
      ), m AS (
        SELECT (CASE WHEN CAST(c0 AS BIGINT) >= 1000000000000000 THEN CAST(c0 AS BIGINT) ELSE CAST(c0 AS BIGINT)*1000 END) AS tps,
               CAST(c1 AS DOUBLE) o, CAST(c2 AS DOUBLE) h, CAST(c3 AS DOUBLE) l, CAST(c4 AS DOUBLE) c,
               CAST(c5 AS DOUBLE) v, CAST(c8 AS BIGINT) n, CAST(c7 AS DOUBLE) qv
        FROM raw
      )
      SELECT 'BINANCE_SPOT_{coin}_USDT' AS symbol_id, '1SEC' AS period_id, 'binance-vision' AS source,
             tps AS time_period_start_us, tps+999999 AS time_period_end_us,
             o AS price_open, h AS price_high, l AS price_low, c AS price_close,
             v AS volume_traded, n AS trades_count, qv AS quote_volume,
             CAST(NULL AS DOUBLE) AS time_open_us, CAST(NULL AS DOUBLE) AS time_close_us,
             CAST(NULL AS DOUBLE) AS taker_buy_base, CAST(NULL AS DOUBLE) AS taker_buy_quote
      FROM m WHERE tps >= {JAN1_US} AND tps < {APR7_US}
    ) TO '{out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
    """
    con.execute(q)
    n, a, b = con.execute(f"SELECT count(*), min(time_period_start_us), max(time_period_start_us) FROM read_parquet('{out}')").fetchone()
    import datetime as dt
    def d(us): return dt.datetime.utcfromtimestamp(us/1e6).strftime('%Y-%m-%d %H:%M') if us else None
    log(f"  {coin}: {n:,} rows  {d(a)} -> {d(b)}")
    parts.append(out)

# ---- phase 3: merge (append) ----
log("=== phase 3: merge into canonical ===")
existing = str(CANON).replace("\\", "/")
newglob = str(TMP / "*.parquet").replace("\\", "/")
order = ("symbol_id,period_id,source,time_period_start_us,time_period_end_us,price_open,price_high,"
         "price_low,price_close,volume_traded,trades_count,quote_volume,time_open_us,time_close_us,"
         "taker_buy_base,taker_buy_quote")
before = con.execute(f"SELECT count(*) FROM read_parquet('{existing}')").fetchone()[0]
add = con.execute(f"SELECT count(*) FROM read_parquet('{newglob}')").fetchone()[0]
tmp_out = str(CANON.with_suffix(".tmp.parquet")).replace("\\", "/")
con.execute(f"""
COPY (
  SELECT {order} FROM read_parquet('{existing}')
  UNION ALL
  SELECT {order} FROM read_parquet('{newglob}')
) TO '{tmp_out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
""")
total = con.execute(f"SELECT count(*) FROM read_parquet('{tmp_out}')").fetchone()[0]
assert total == before + add, f"row mismatch {total} != {before}+{add}"
con.close()
shutil.move(tmp_out, CANON)
log(f"=== DONE: {before:,} -> {total:,} (+{add:,}) ===")
