"""
Task 1 — append aliplayer markets.resolution (all 7 coins, incl BNB/DOGE/HYPE) to
canonical/resolutions_hf.parquet. Dedup by slug, KEEP existing (bmoney-real > aliplayer).
Reports outcome agreement on the overlap as a cross-check.
"""
import duckdb, shutil, time
from pathlib import Path

RES = Path(r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\resolutions_hf.parquet")
ALI = Path(r"D:\aliplayer_hf\data\markets.parquet")
def log(m): print(f"[res] {time.strftime('%H:%M:%S')} {m}", flush=True)

con = duckdb.connect()
res = str(RES).replace("\\", "/"); ali = str(ALI).replace("\\", "/")

# aliplayer resolved -> canonical resolution schema.
# Derive slug canonically from end_ts-window (slug col is human-readable for 1h/4h).
# Verified for 5m/15m: end_ts - window == slug-suffix epoch == slot_start.
con.execute(f"""
CREATE TABLE ali AS
WITH base AS (
  SELECT lower(crypto) AS coin, upper(crypto) AS ticker,
         CASE timeframe WHEN '5-minute' THEN '5m' WHEN '15-minute' THEN '15m'
                        WHEN '1-hour' THEN '1h' WHEN '4-hour' THEN '4h' ELSE timeframe END AS tf,
         CASE timeframe WHEN '5-minute' THEN 300 WHEN '15-minute' THEN 900
                        WHEN '1-hour' THEN 3600 WHEN '4-hour' THEN 14400 END AS win,
         CAST(end_ts AS BIGINT) AS end_ts, resolution
  FROM read_parquet('{ali}')
  WHERE resolution >= 0
)
SELECT coin||'-updown-'||tf||'-'||CAST(end_ts-win AS VARCHAR) AS slug,
       ticker, tf AS timeframe,
       (end_ts-win)*1000000 AS slot_start_us,
       end_ts*1000000 AS slot_end_us,
       CASE resolution WHEN 1 THEN 'Up' WHEN 0 THEN 'Down' END AS outcome,
       'aliplayer1-real' AS source,
       'aliplayer-markets' AS price_source
FROM base
""")
con.execute("CREATE TABLE ali_d AS SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY slug ORDER BY slot_end_us DESC) rn FROM ali) WHERE rn=1")
n_ali = con.execute("SELECT count(*) FROM ali_d").fetchone()[0]
log(f"aliplayer resolved (dedup slug): {n_ali:,}")

con.execute(f"CREATE TABLE ex AS SELECT * FROM read_parquet('{res}')")
n_ex = con.execute("SELECT count(*) FROM ex").fetchone()[0]
log(f"existing resolutions_hf: {n_ex:,}")

# overlap agreement cross-check
ov = con.execute("""
SELECT count(*) n,
       coalesce(sum(CASE WHEN e.outcome=a.outcome THEN 1 ELSE 0 END),0) agree
FROM ex e JOIN ali_d a USING(slug)""").fetchone()
log(f"OVERLAP: {ov[0]:,} slugs, agree {ov[1]:,} ({(ov[1]/ov[0]*100) if ov[0] else 0:.2f}%)")
if ov[0] and ov[1] != ov[0]:
    log("  --- disagreements (existing vs aliplayer) ---")
    for r in con.execute("""SELECT e.slug,e.outcome,e.source,a.outcome FROM ex e JOIN ali_d a USING(slug)
                            WHERE e.outcome<>a.outcome LIMIT 20""").fetchall(): log(f"    {r}")

# new aliplayer slugs not already present -> append; keep existing for overlap
con.execute("CREATE TABLE new_ali AS SELECT slug,ticker,timeframe,slot_start_us,slot_end_us,outcome,source,price_source FROM ali_d WHERE slug NOT IN (SELECT slug FROM ex)")
n_new = con.execute("SELECT count(*) FROM new_ali").fetchone()[0]
log(f"new aliplayer slugs to append: {n_new:,}")
log("  new by coin:")
for r in con.execute("SELECT split_part(slug,'-',1) c, count(*) FROM new_ali GROUP BY 1 ORDER BY 2 DESC").fetchall(): log(f"    {r}")

# write merged atomically
tmp = str(RES.with_suffix(".tmp.parquet")).replace("\\", "/")
con.execute(f"""
COPY (
  SELECT slug,ticker,timeframe,slot_start_us,slot_end_us,outcome,source,price_source FROM ex
  UNION ALL
  SELECT slug,ticker,timeframe,slot_start_us,slot_end_us,outcome,source,price_source FROM new_ali
) TO '{tmp}' (FORMAT parquet, COMPRESSION snappy)
""")
tot = con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
con.close()
shutil.move(tmp, RES)
log(f"=== WROTE resolutions_hf.parquet: {tot:,} rows (was {n_ex:,}, +{n_new:,}) ===")

# final per-coin
con = duckdb.connect()
log("final per-coin:")
for r in con.execute(f"SELECT split_part(slug,'-',1) c, count(*) FROM read_parquet('{res}') GROUP BY 1 ORDER BY 2 DESC").fetchall(): log(f"    {r}")
log("final per-source:")
for r in con.execute(f"SELECT source, count(*) FROM read_parquet('{res}') GROUP BY 1 ORDER BY 2 DESC").fetchall(): log(f"    {r}")
