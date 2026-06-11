"""
Efficient canonical refresh merge (DuckDB streaming, reads .gz deltas directly).
Replaces the pandas full-load merges (merge_nonl25 + merge_futures) which rewrote
multi-GB files in RAM (the 1-2h cost). DuckDB streams + spills to D:, ~10-20x faster.

Per append-only table: coerce delta(.gz) -> canon schema, UNION canon, dedup via
window (keep canon on exact dup / delta on newer), sort, stream to tmp, atomic replace.
L25 tmp goes to D: (C: too tight for the 8GB BTC rewrite) with a safe cross-drive swap.
Full-replace tables (resolutions, trading_events) just rewrite from the gz.
resolutions_from_rtds rebuilt via a vectorized DuckDB asof join.

Run AFTER the 3 pull_*.sh have produced data/v4/refresh_2026_06_11/raw/*.csv.gz.
"""
from __future__ import annotations
from pathlib import Path
import os, time, shutil
import duckdb

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
CANON = ROOT / "data" / "v4" / "canonical"
RAW = ROOT / "data" / "v4" / "refresh_2026_06_11" / "raw"
DTMP = Path(r"D:\refresh_tmp_2026_06_11"); DTMP.mkdir(parents=True, exist_ok=True)
def log(m): print(f"[merge] {time.strftime('%H:%M:%S')} {m}", flush=True)

con = duckdb.connect()
con.execute("PRAGMA threads=6")
con.execute("PRAGMA memory_limit='14GB'")
con.execute("PRAGMA preserve_insertion_order=false")  # enable external (spilling) sort for big tables
con.execute(f"PRAGMA temp_directory='{str(DTMP).replace(chr(92),'/')}'")
con.execute("PRAGMA max_temp_directory_size='80GB'")

def schema(p):
    return [(r[0], r[1]) for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{str(p).replace(chr(92),'/')}')").fetchall()]

def gz_cols(gz):
    return {r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_csv('{gz}', header=true, all_varchar=true, sample_size=-1)").fetchall()}

def coerce_select(sch, gz, dcols, where="", literals=None):
    literals = literals or {}
    parts = []
    for name, typ in sch:
        q = f'"{name}"'
        if name in literals: parts.append(f"{literals[name]} AS {q}")
        elif name in dcols:  parts.append(f"TRY_CAST(NULLIF({q},'') AS {typ}) AS {q}")
        else:                parts.append(f"CAST(NULL AS {typ}) AS {q}")
    sql = f"SELECT {', '.join(parts)} FROM read_csv('{gz}', header=true, all_varchar=true, sample_size=-1)"
    if where: sql += f" WHERE {where}"
    return sql

def merge_table(name, canon_p, gz, keys, sort_cols, where="", on_d=False, delta_select=None):
    # Memory-light append: ANTI JOIN canon against the (small) delta on the dedup key to drop
    # superseded rows, then UNION the delta. No global sort (loaders sort on read) -> no OOM.
    canon_p = Path(canon_p)
    if not canon_p.exists(): log(f"  {name}: NO canon, skip"); return
    sch = schema(canon_p); cols = [c[0] for c in sch]
    keys = [k for k in keys if k in cols]
    cp = str(canon_p).replace(chr(92), "/")
    if delta_select is None:
        gzf = str(gz).replace(chr(92), "/")
        if not Path(gz).exists(): log(f"  {name}: NO delta gz, skip"); return
        delta_select = coerce_select(sch, gzf, gz_cols(gzf), where)
    collist = ", ".join(f'"{c}"' for c in cols)
    con.execute(f"CREATE OR REPLACE TEMP TABLE _delta AS SELECT {collist} FROM ({delta_select})")
    ndelta = con.execute("SELECT count(*) FROM _delta").fetchone()[0]
    if ndelta == 0: log(f"  {name}: delta empty, skip"); return
    joincond = " AND ".join(f'c."{k}" = d."{k}"' for k in keys)
    c_cols = ", ".join(f'c."{x}"' for x in cols)
    tmp = (DTMP / f"{name.replace('/','_')}.parquet") if on_d else canon_p.with_suffix(".tmp.parquet")
    tmpf = str(tmp).replace(chr(92), "/")
    before = con.execute(f"SELECT count(*) FROM read_parquet('{cp}')").fetchone()[0]
    last_ts = sort_cols[-1]
    t0 = time.time()
    con.execute(f"""
    COPY (
      SELECT {c_cols} FROM read_parquet('{cp}') c ANTI JOIN _delta d ON {joincond}
      UNION ALL BY NAME
      SELECT {collist} FROM _delta
    ) TO '{tmpf}' (FORMAT parquet, COMPRESSION snappy, ROW_GROUP_SIZE 500000)
    """)
    sort_cols = [last_ts]  # only need the ts col for the max() report below
    total = con.execute(f"SELECT count(*) FROM read_parquet('{tmpf}')").fetchone()[0]
    mx = con.execute(f'SELECT max("{sort_cols[-1]}") FROM read_parquet(\'{tmpf}\')').fetchone()[0]
    # SAFETY: append/grow tables must never shrink. Abort (keep canon intact) if they do.
    if total < before:
        os.remove(tmpf) if Path(tmpf).exists() else None
        raise SystemExit(f"ABORT {name}: merged {total:,} < before {before:,} — canon untouched, investigate")
    if on_d:  # cross-drive safe swap: remove canon (frees C:), then move D: tmp -> C:
        os.remove(canon_p); shutil.move(tmpf, str(canon_p))
    else:
        os.replace(tmpf, str(canon_p))
    log(f"  {name}: {before:,} -> {total:,} (+{total-before:,}) max={mx} ({time.time()-t0:.0f}s)")

# ---------------- non-L25 append tables ----------------
log("=== non-L25 ===")
merge_table("klines_1m", CANON/"klines_1m.parquet", RAW/"binance_klines_delta.csv.gz",
            ["symbol_id","period_id","source","time_period_start_us"],
            ["symbol_id","period_id","source","time_period_start_us"])
merge_table("klines_1s", CANON/"klines_1s.parquet", RAW/"binance_klines_1sec_delta.csv.gz",
            ["symbol_id","source","time_period_start_us"], ["symbol_id","time_period_start_us"])
merge_table("chainlink_rtds", CANON/"chainlink_rtds.parquet", RAW/"oracle_prices_delta.csv.gz",
            ["symbol_id","timestamp_us"], ["symbol_id","timestamp_us"],
            where="source ILIKE '%chainlink%'")
for a in ["btc","eth","sol"]:
    merge_table(f"trades/{a}", CANON/"trades_polymarket"/f"{a}.parquet", RAW/f"{a}_trades_delta.csv.gz",
                ["trade_id"] if True else [], ["slug","timestamp_us"])

# trades fallback: tables without trade_id -> handled by key filter; ensure key valid
# (trade_id exists in trades_v2; merge_table filters keys to existing cols.)

# ---------------- full-replace tables ----------------
log("=== full-replace ===")
def full_replace(name, canon_p, gz, sort_col, where=""):
    canon_p = Path(canon_p); sch = schema(canon_p)
    sel = coerce_select(sch, str(gz).replace(chr(92),"/"), gz_cols(str(gz).replace(chr(92),"/")), where)
    tmp = canon_p.with_suffix(".tmp.parquet"); tmpf=str(tmp).replace(chr(92),"/")
    con.execute(f'COPY (SELECT * FROM ({sel}) ORDER BY "{sort_col}") TO \'{tmpf}\' (FORMAT parquet, COMPRESSION snappy)')
    n=con.execute(f"SELECT count(*) FROM read_parquet('{tmpf}')").fetchone()[0]
    os.replace(tmpf, str(canon_p)); log(f"  {name}: {n:,} rows (replaced)")
full_replace("resolutions", CANON/"resolutions.parquet", RAW/"market_resolutions_full.csv.gz", "slot_start_us")
full_replace("trading_events_30d", CANON/"trading_events_30d.parquet", RAW/"trading_events_30d.csv.gz", "at")

# ---------------- futures ----------------
log("=== futures ===")
merge_table("cex_futures_klines", CANON/"cex_futures_klines.parquet", RAW/"cex_futures_klines.csv.gz",
            ["exchange","symbol_id","period_id","time_period_start_us"],
            ["exchange","symbol_id","period_id","time_period_start_us"])
merge_table("cex_futures_ticker", CANON/"cex_futures_ticker.parquet", RAW/"cex_futures_ticker.csv.gz",
            ["exchange","symbol_id","time_exchange_us"], ["exchange","symbol_id","time_exchange_us"])
merge_table("cex_futures_trades", CANON/"cex_futures_trades.parquet", RAW/"cex_futures_trades.csv.gz",
            ["exchange","symbol_id","time_exchange_us","trade_id","side","price","size"], ["time_exchange_us"])
# liquidations: gate+okx gz, tag exchange literal, union -> single delta select
liq_sch = schema(CANON/"cex_futures_liquidations.parquet")
liq_parts = []
for ex in ["gate","okx"]:
    gz = RAW/f"{ex}_liquidations.csv.gz"
    if gz.exists():
        gzf=str(gz).replace(chr(92),"/")
        liq_parts.append(coerce_select(liq_sch, gzf, gz_cols(gzf), literals={"exchange": f"'{ex}'"}))
if liq_parts:
    merge_table("cex_futures_liquidations", CANON/"cex_futures_liquidations.parquet", None,
                ["exchange","time_exchange_us","symbol_id","side","price","size"], ["time_exchange_us"],
                delta_select=" UNION ALL BY NAME ".join(f"({p})" for p in liq_parts))

# ---------------- L25 handled separately (pyarrow streaming, see l25_merge_safe.py) ----------------
log("=== L25 skipped here -> run l25_merge_safe.py (pyarrow streaming, memory-light) ===")

# ---------------- rebuild resolutions_from_rtds (vectorized asof) ----------------
log("=== rebuild resolutions_from_rtds ===")
res=str(CANON/"resolutions.parquet").replace(chr(92),"/"); cl=str(CANON/"chainlink_rtds.parquet").replace(chr(92),"/")
tmp=str((CANON/"resolutions_from_rtds.tmp.parquet")).replace(chr(92),"/")
con.execute(f"""
COPY (
  WITH r AS (SELECT market_id,slug,ticker,timeframe,slot_start_us,slot_end_us, upper(ticker) tk
             FROM read_parquet('{res}') WHERE regexp_matches(slug,'^(btc|eth|sol)-updown-')),
  c AS (SELECT symbol_id, timestamp_us, price_value FROM read_parquet('{cl}')
        WHERE symbol_id IN ('CHAINLINK_BTC_USD','CHAINLINK_ETH_USD','CHAINLINK_SOL_USD')),
  strike AS (SELECT r.*, c.price_value sp, c.timestamp_us sts FROM r ASOF JOIN c
             ON c.symbol_id='CHAINLINK_'||r.tk||'_USD' AND c.timestamp_us <= r.slot_start_us),
  reb AS (SELECT s.*, c2.price_value lp, c2.timestamp_us lts FROM strike s ASOF JOIN c c2
           ON c2.symbol_id='CHAINLINK_'||s.tk||'_USD' AND c2.timestamp_us <= s.slot_end_us)
  SELECT market_id, slug, ticker, timeframe, slot_start_us, slot_end_us,
         CASE WHEN lp-sp > 0 THEN 'Up' ELSE 'Down' END outcome,
         sp strike_price, slot_start_us strike_ts_us, lp settlement_price, slot_end_us settle_ts_us,
         (lp-sp) delta_price, 'chainlink-rtds-local' price_source
  FROM reb
  WHERE sp IS NOT NULL AND lp IS NOT NULL AND (slot_start_us - sts) <= 60000000
        AND (slot_end_us - lts) <= 60000000 AND abs(lp-sp) > 1e-9
  ORDER BY slot_start_us
) TO '{tmp}' (FORMAT parquet, COMPRESSION snappy)
""")
n=con.execute(f"SELECT count(*) FROM read_parquet('{tmp}')").fetchone()[0]
os.replace(tmp, str(CANON/"resolutions_from_rtds.parquet")); log(f"  resolutions_from_rtds: {n:,} rows")

con.close()
# cleanup D: temp
shutil.rmtree(DTMP, ignore_errors=True)
log("=== MERGE DONE ===")
