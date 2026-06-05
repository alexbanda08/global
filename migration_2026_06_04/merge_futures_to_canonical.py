"""
Append cross-exchange futures DELTA (refresh_2026_06_04/raw/*.csv.gz) into the
existing canonical futures parquets, with dedup. Incremental top-off (canonical
already has the 2026-06-01 first ingest).

Dedup keys:
  klines  -> (exchange, symbol_id, period_id, time_period_start_us)
  ticker  -> (exchange, symbol_id, time_exchange_us)
  trades  -> (exchange, symbol_id, time_exchange_us, trade_id, side, price, size)
  liqs    -> (exchange, time_exchange_us, symbol_id, side, price, size)
"""
from __future__ import annotations
from pathlib import Path
import time
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
RAW = ROOT / "data" / "v4" / "refresh_2026_06_04" / "raw"
CANON = ROOT / "data" / "v4" / "canonical"

def log(msg): print(f"[fut-merge] {msg}", flush=True)


def merge_one(canon_name, raw_name, ts_col, dedup_keys, read_kwargs=None, add_exchange=None):
    cp = CANON / canon_name
    rp = RAW / raw_name
    if not rp.exists():
        log(f"  {canon_name}: NO delta gz, skip"); return
    new = pd.read_csv(rp, compression="gzip", **(read_kwargs or {}))
    if add_exchange:
        new.insert(0, "exchange", add_exchange)
    if len(new) == 0:
        log(f"  {canon_name}: delta empty, skip"); return
    old = pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    log(f"  {canon_name}: old={len(old):,}  new={len(new):,}")
    if len(old):
        # align object dtypes to avoid concat warnings/mismatch
        for col in [c for c in old.columns if old[c].dtype == 'object']:
            old[col] = old[col].astype(str)
            if col in new.columns:
                new[col] = new[col].astype(str)
        c = pd.concat([old, new], ignore_index=True)
        keys = [k for k in dedup_keys if k in c.columns]
        c = c.drop_duplicates(keys, keep="last")
    else:
        c = new
    c = c.sort_values(ts_col).reset_index(drop=True)
    c.to_parquet(cp, index=False)
    log(f"    -> {canon_name}: {len(c):,} rows  max={pd.to_datetime(c[ts_col].max(), unit='us', utc=True)}")


def main():
    t0 = time.time()
    log("Appending futures deltas into canonical...")

    merge_one("cex_futures_klines.parquet", "cex_futures_klines.csv.gz",
              "time_period_start_us",
              ["exchange","symbol_id","period_id","time_period_start_us"])

    merge_one("cex_futures_ticker.parquet", "cex_futures_ticker.csv.gz",
              "time_exchange_us",
              ["exchange","symbol_id","time_exchange_us"])

    merge_one("cex_futures_trades.parquet", "cex_futures_trades.csv.gz",
              "time_exchange_us",
              ["exchange","symbol_id","time_exchange_us","trade_id","side","price","size"],
              read_kwargs={"dtype": {"trade_id": "string", "raw_symbol": "string"}})

    # liquidations: gate + okx separate gz, tag exchange, then dedup combined
    cp = CANON / "cex_futures_liquidations.parquet"
    old = pd.read_parquet(cp) if cp.exists() else pd.DataFrame()
    parts = []
    for ex in ["gate", "okx"]:
        rp = RAW / f"{ex}_liquidations.csv.gz"
        if not rp.exists():
            continue
        d = pd.read_csv(rp, compression="gzip", dtype={"raw_symbol": "string"})
        if len(d) == 0:
            continue
        d.insert(0, "exchange", ex)
        parts.append(d)
    if parts:
        new = pd.concat(parts, ignore_index=True)
        log(f"  cex_futures_liquidations: old={len(old):,}  new={len(new):,}")
        if len(old):
            c = pd.concat([old, new], ignore_index=True)
            keys = [k for k in ["exchange","time_exchange_us","symbol_id","side","price","size"] if k in c.columns]
            c = c.drop_duplicates(keys, keep="last")
        else:
            c = new
        c = c.sort_values("time_exchange_us").reset_index(drop=True)
        c.to_parquet(cp, index=False)
        log(f"    -> cex_futures_liquidations: {len(c):,} rows ({sorted(c.exchange.unique())})")
    else:
        log("  cex_futures_liquidations: no new rows")

    log(f"\n=== FUTURES MERGE DONE ({time.time()-t0:.1f}s) ===")
    for n, tc in [("cex_futures_klines","time_period_start_us"),
                  ("cex_futures_ticker","time_exchange_us"),
                  ("cex_futures_trades","time_exchange_us"),
                  ("cex_futures_liquidations","time_exchange_us")]:
        p = CANON / f"{n}.parquet"
        d = pd.read_parquet(p, columns=[tc])
        log(f"  {n:<28s} {len(d):>10,} rows  max={pd.to_datetime(d[tc].max(), unit='us', utc=True)}")


if __name__ == "__main__":
    main()
