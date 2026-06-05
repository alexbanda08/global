"""
Fix: the prior DOGE/BNB Apr run used a wrong cap (Apr 19 instead of Apr 22) so only Apr 7-18
landed. CSVs for Apr 19-21 are already downloaded in D:\bv1s_raw2. Re-convert the Apr 19-21
window [Apr19 00:00, Apr22 00:00) and append (existing canon now ends Apr 18 23:59 -> disjoint).
"""
import shutil
from pathlib import Path
import duckdb, datetime as dt

CANON = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\klines_1s.parquet")
RAW = Path(r"D:\bv1s_raw2")
COINS = ["DOGE", "BNB"]
APR19_US = 1776556800000000   # inclusive start (the missing 3 days)
APR22_US = 1776816000000000   # exclusive cap (correct Apr 22 00:00)
def log(m): print(f"[fix1921] {dt.datetime.now().strftime('%H:%M:%S')} {m}", flush=True)

con = duckdb.connect(); con.execute("PRAGMA memory_limit='8GB'")
TMP = RAW / "_parts1921"; TMP.mkdir(exist_ok=True)
colspec = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(12)) + "}"
for coin in COINS:
    src = str(RAW / f"{coin}USDT" / "*.csv").replace("\\", "/")
    out = str(TMP / f"{coin}.parquet").replace("\\", "/")
    con.execute(f"""
    COPY (
      WITH raw AS (SELECT * FROM read_csv('{src}', header=false, columns={colspec}, ignore_errors=true)
                   WHERE try_cast(c0 AS BIGINT) IS NOT NULL),
      m AS (SELECT (CASE WHEN CAST(c0 AS BIGINT) >= 1000000000000000 THEN CAST(c0 AS BIGINT) ELSE CAST(c0 AS BIGINT)*1000 END) AS tps,
                   CAST(c1 AS DOUBLE) o, CAST(c2 AS DOUBLE) h, CAST(c3 AS DOUBLE) l, CAST(c4 AS DOUBLE) c,
                   CAST(c5 AS DOUBLE) v, CAST(c8 AS BIGINT) n, CAST(c7 AS DOUBLE) qv FROM raw)
      SELECT 'BINANCE_SPOT_{coin}_USDT' AS symbol_id, '1SEC' AS period_id, 'binance-vision' AS source,
             tps AS time_period_start_us, tps+999999 AS time_period_end_us,
             o price_open, h price_high, l price_low, c price_close, v volume_traded, n trades_count, qv quote_volume,
             CAST(NULL AS DOUBLE) time_open_us, CAST(NULL AS DOUBLE) time_close_us,
             CAST(NULL AS DOUBLE) taker_buy_base, CAST(NULL AS DOUBLE) taker_buy_quote
      FROM m WHERE tps >= {APR19_US} AND tps < {APR22_US}
    ) TO '{out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
    """)
    n,a,b=con.execute(f"SELECT count(*),min(time_period_start_us),max(time_period_start_us) FROM read_parquet('{out}')").fetchone()
    dd=lambda u: dt.datetime.utcfromtimestamp(u/1e6).strftime('%Y-%m-%d %H:%M')
    log(f"{coin}: {n:,} rows {dd(a)} -> {dd(b)}")

# guard: ensure no overlap with existing (existing DOGE/BNB must end < Apr19)
existing=str(CANON).replace("\\","/"); newglob=str(TMP/"*.parquet").replace("\\","/")
ovmax=con.execute(f"SELECT max(time_period_start_us) FROM read_parquet('{existing}') WHERE symbol_id IN ('BINANCE_SPOT_DOGE_USDT','BINANCE_SPOT_BNB_USDT')").fetchone()[0]
assert ovmax < APR19_US, f"OVERLAP RISK: existing DOGE/BNB max {ovmax} >= Apr19 {APR19_US}"
order=("symbol_id,period_id,source,time_period_start_us,time_period_end_us,price_open,price_high,"
       "price_low,price_close,volume_traded,trades_count,quote_volume,time_open_us,time_close_us,"
       "taker_buy_base,taker_buy_quote")
before=con.execute(f"SELECT count(*) FROM read_parquet('{existing}')").fetchone()[0]
add=con.execute(f"SELECT count(*) FROM read_parquet('{newglob}')").fetchone()[0]
tmp_out=str(CANON.with_suffix(".tmp.parquet")).replace("\\","/")
con.execute(f"COPY (SELECT {order} FROM read_parquet('{existing}') UNION ALL SELECT {order} FROM read_parquet('{newglob}')) TO '{tmp_out}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)")
total=con.execute(f"SELECT count(*) FROM read_parquet('{tmp_out}')").fetchone()[0]
assert total==before+add, f"mismatch {total}!={before}+{add}"
con.close(); shutil.move(tmp_out, CANON)
log(f"DONE: {before:,} -> {total:,} (+{add:,})")
