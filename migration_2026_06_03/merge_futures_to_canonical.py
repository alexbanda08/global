"""
Merge futures delta parquets from refresh_2026_06_03/cache/ into canonical/.
For each table: read existing canonical + delta, concat, dedup on natural key, sort, atomic write.
Also creates canonical/cex_futures_book.parquet (new — first ingest, full replace).
"""
from __future__ import annotations
from pathlib import Path
import os
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
TAG = "2026_06_03"
CACHE = ROOT / "data" / "v4" / f"refresh_{TAG}" / "cache"
CANON = ROOT / "data" / "v4" / "canonical"

def log(msg): print(f"[merge-futures] {msg}", flush=True)

def atomic_write(df: pd.DataFrame, dest: Path):
    """Write to .tmp then os.replace -> atomic."""
    tmp = dest.with_suffix(".parquet.tmp")
    df.to_parquet(tmp, index=False)
    os.replace(str(tmp), str(dest))

# ── 1. cex_futures_klines ──────────────────────────────────────────────────
log("Merging cex_futures_klines...")
KEY = ["exchange", "symbol_id", "period_id", "time_period_start_us"]
canon_p = CANON / "cex_futures_klines.parquet"
delta_p = CACHE / "cex_futures_klines_delta.parquet"
old = pd.read_parquet(canon_p) if canon_p.exists() else pd.DataFrame()
new = pd.read_parquet(delta_p)
log(f"  old: {len(old):,}  delta: {len(new):,}")
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(KEY, keep="last")
c = c.sort_values(KEY).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_period_start_us.max(), unit='us', utc=True)}")
atomic_write(c, canon_p)

# ── 2. cex_futures_ticker ──────────────────────────────────────────────────
log("Merging cex_futures_ticker...")
KEY = ["exchange", "symbol_id", "time_exchange_us"]
canon_p = CANON / "cex_futures_ticker.parquet"
delta_p = CACHE / "cex_futures_ticker_delta.parquet"
old = pd.read_parquet(canon_p) if canon_p.exists() else pd.DataFrame()
new = pd.read_parquet(delta_p)
log(f"  old: {len(old):,}  delta: {len(new):,}")
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(KEY, keep="last")
c = c.sort_values(KEY).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_exchange_us.max(), unit='us', utc=True)}")
atomic_write(c, canon_p)

# ── 3. cex_futures_trades ──────────────────────────────────────────────────
log("Merging cex_futures_trades...")
# dedup on (exchange, symbol_id, time_exchange_us, trade_id) — trade_id is string
KEY_TRADES = ["exchange", "symbol_id", "time_exchange_us", "trade_id"]
canon_p = CANON / "cex_futures_trades.parquet"
delta_p = CACHE / "cex_futures_trades_delta.parquet"
old = pd.read_parquet(canon_p) if canon_p.exists() else pd.DataFrame()
new = pd.read_parquet(delta_p)
log(f"  old: {len(old):,}  delta: {len(new):,}")
# ensure trade_id is str in both
for df in [old, new]:
    if "trade_id" in df.columns:
        df["trade_id"] = df["trade_id"].astype(str)
c = pd.concat([old, new], ignore_index=True)
c = c.drop_duplicates(KEY_TRADES, keep="last")
c = c.sort_values(["exchange", "symbol_id", "time_exchange_us"]).reset_index(drop=True)
log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_exchange_us.max(), unit='us', utc=True)}")
atomic_write(c, canon_p)

# ── 4. cex_futures_liquidations ───────────────────────────────────────────
log("Merging cex_futures_liquidations...")
KEY = ["exchange", "symbol_id", "time_exchange_us"]
canon_p = CANON / "cex_futures_liquidations.parquet"
delta_p = CACHE / "cex_futures_liquidations_delta.parquet"
if delta_p.exists():
    old = pd.read_parquet(canon_p) if canon_p.exists() else pd.DataFrame()
    new = pd.read_parquet(delta_p)
    log(f"  old: {len(old):,}  delta: {len(new):,}  exchanges: {sorted(new.exchange.unique())}")
    c = pd.concat([old, new], ignore_index=True)
    # liquidations: dedup on exchange+symbol+time; if no symbol_id col fall back to exchange+time
    dedup_key = KEY if "symbol_id" in c.columns else ["exchange", "time_exchange_us"]
    c = c.drop_duplicates(dedup_key, keep="last")
    c = c.sort_values(["exchange", "time_exchange_us"]).reset_index(drop=True)
    log(f"  merged: {len(c):,}  max ts: {pd.to_datetime(c.time_exchange_us.max(), unit='us', utc=True)}")
    atomic_write(c, canon_p)
else:
    log("  delta missing, skip")

# ── 5. cex_futures_book (NEW — first ingest, full replace) ─────────────────
log("Writing cex_futures_book (new canonical table)...")
canon_p = CANON / "cex_futures_book.parquet"
src_p = CACHE / "cex_futures_book_full.parquet"
if src_p.exists():
    df = pd.read_parquet(src_p)
    log(f"  rows: {len(df):,}  exchanges: {sorted(df.exchange.unique())}")
    log(f"  span: {pd.to_datetime(df.time_exchange_us.min(), unit='us', utc=True)} -> {pd.to_datetime(df.time_exchange_us.max(), unit='us', utc=True)}")
    df = df.sort_values(["exchange", "symbol_id", "time_exchange_us"]).reset_index(drop=True)
    atomic_write(df, canon_p)
    log(f"  -> cex_futures_book.parquet ({canon_p.stat().st_size//1024//1024} MB)")
else:
    log("  cex_futures_book_full.parquet missing — skipped")

log("\n=== FINAL CANONICAL STATE (futures) ===")
for name, p, ts_col in [
    ("cex_futures_klines",       CANON/"cex_futures_klines.parquet",       "time_period_start_us"),
    ("cex_futures_ticker",       CANON/"cex_futures_ticker.parquet",       "time_exchange_us"),
    ("cex_futures_trades",       CANON/"cex_futures_trades.parquet",       "time_exchange_us"),
    ("cex_futures_liquidations", CANON/"cex_futures_liquidations.parquet", "time_exchange_us"),
    ("cex_futures_book",         CANON/"cex_futures_book.parquet",         "time_exchange_us"),
]:
    if not p.exists():
        log(f"  {name:<30s} MISSING"); continue
    df = pd.read_parquet(p, columns=[ts_col])
    log(f"  {name:<30s} {len(df):>10,} rows  max={pd.to_datetime(df[ts_col].max(), unit='us', utc=True)}")
