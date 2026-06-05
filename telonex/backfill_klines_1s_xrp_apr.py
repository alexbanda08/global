"""
Extend canonical klines_1s with Binance Vision 1s spot for XRP, Apr 7 -> Apr 21 2026.
Abuts existing XRP (Jan1->Apr6) -> pure append. (XRP was missed in the DOGE/BNB Apr run.)
"""
import os, time, zipfile, urllib.request, shutil
from pathlib import Path
import duckdb, datetime as dt

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\klines_1s.parquet")
RAW = Path(r"D:\bv1s_xrp")
SYM = "XRPUSDT"; COIN = "XRP"
DAYS = [f"2026-04-{d:02d}" for d in range(7, 22)]  # Apr 7..21
APR7_US = 1775520000000000      # inclusive
APR22_US = 1776816000000000     # exclusive (correct Apr 22 00:00)
BASE = "https://data.binance.vision/data/spot"
def log(m): print(f"[xrp1s] {time.strftime('%H:%M:%S')} {m}", flush=True)

def dl(url, dest, tries=6):
    if dest.exists() and dest.stat().st_size > 0: return True
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            return True
        except Exception as e:
            if "404" in str(e): return False
            log(f"  retry {i+1} {dest.name}: {e}"); time.sleep(3)
    return False

d = RAW / SYM; d.mkdir(parents=True, exist_ok=True)
log("download + extract Apr 7-21")
for day in DAYS:
    csv = d / f"{SYM}-1s-{day}.csv"
    if csv.exists() and csv.stat().st_size > 0: continue
    zf = d / f"{SYM}-1s-{day}.zip"
    if not dl(f"{BASE}/daily/klines/{SYM}/1s/{SYM}-1s-{day}.zip", zf): log(f"  MISS {day}"); continue
    try:
        with zipfile.ZipFile(zf) as z: z.extractall(d)
        zf.unlink()
    except Exception as e: log(f"  BAD ZIP {zf.name}: {e}")
log(f"{len(list(d.glob('*.csv')))} csv files ready")

con = duckdb.connect(); con.execute("PRAGMA memory_limit='8GB'")
TMP = RAW / "_parts"; TMP.mkdir(exist_ok=True)
colspec = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(12)) + "}"
src = str(d / "*.csv").replace("\\", "/"); out = str(TMP / f"{COIN}.parquet").replace("\\", "/")
con.execute(f"""
COPY (
  WITH raw AS (SELECT * FROM read_csv('{src}', header=false, columns={colspec}, ignore_errors=true)
               WHERE try_cast(c0 AS BIGINT) IS NOT NULL),
  m AS (SELECT (CASE WHEN CAST(c0 AS BIGINT) >= 1000000000000000 THEN CAST(c0 AS BIGINT) ELSE CAST(c0 AS BIGINT)*1000 END) AS tps,
               CAST(c1 AS DOUBLE) o, CAST(c2 AS DOUBLE) h, CAST(c3 AS DOUBLE) l, CAST(c4 AS DOUBLE) c,
               CAST(c5 AS DOUBLE) v, CAST(c8 AS BIGINT) n, CAST(c7 AS DOUBLE) qv FROM raw)
  SELECT 'BINANCE_SPOT_{COIN}_USDT' AS symbol_id, '1SEC' AS period_id, 'binance-vision' AS source,
         tps AS time_period_start_us, tps+999999 AS time_period_end_us,
         o AS price_open, h AS price_high, l AS price_low, c AS price_close, v AS volume_traded, n AS trades_count, qv AS quote_volume,
         CAST(NULL AS DOUBLE) AS time_open_us, CAST(NULL AS DOUBLE) AS time_close_us,
         CAST(NULL AS DOUBLE) AS taker_buy_base, CAST(NULL AS DOUBLE) AS taker_buy_quote
  FROM m WHERE tps >= {APR7_US} AND tps < {APR22_US}
) TO '{out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
""")
n,a,b=con.execute(f"SELECT count(*),min(time_period_start_us),max(time_period_start_us) FROM read_parquet('{out}')").fetchone()
dd=lambda u: dt.datetime.utcfromtimestamp(u/1e6).strftime('%Y-%m-%d %H:%M')
log(f"XRP: {n:,} rows {dd(a)} -> {dd(b)}")

existing=str(CANON).replace("\\","/"); newp=out
ovmax=con.execute(f"SELECT max(time_period_start_us) FROM read_parquet('{existing}') WHERE symbol_id='BINANCE_SPOT_XRP_USDT'").fetchone()[0]
assert ovmax < APR7_US, f"OVERLAP: existing XRP max {ovmax} >= Apr7"
order=("symbol_id,period_id,source,time_period_start_us,time_period_end_us,price_open,price_high,"
       "price_low,price_close,volume_traded,trades_count,quote_volume,time_open_us,time_close_us,"
       "taker_buy_base,taker_buy_quote")
before=con.execute(f"SELECT count(*) FROM read_parquet('{existing}')").fetchone()[0]
add=con.execute(f"SELECT count(*) FROM read_parquet('{newp}')").fetchone()[0]
tmp_out=str(CANON.with_suffix(".tmp.parquet")).replace("\\","/")
con.execute(f"COPY (SELECT {order} FROM read_parquet('{existing}') UNION ALL SELECT {order} FROM read_parquet('{newp}')) TO '{tmp_out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)")
total=con.execute(f"SELECT count(*) FROM read_parquet('{tmp_out}')").fetchone()[0]
assert total==before+add, f"mismatch {total}!={before}+{add}"
con.close(); shutil.move(tmp_out, CANON)
log(f"DONE: {before:,} -> {total:,} (+{add:,})")
