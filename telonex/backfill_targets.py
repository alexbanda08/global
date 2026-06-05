"""Demonstrate catalog value: list pre-Apr-22 BTC/ETH/SOL up-or-down backfill targets. Zero API cost."""
from pathlib import Path
import pandas as pd
pd.set_option("display.width", 220); pd.set_option("display.max_colwidth", 44)

df = pd.read_parquet(r"C:\Users\alexandre bandarra\Desktop\global\telonex\samples\markets_catalog.parquet")
s = df["slug"].astype(str)

# crypto up/down with L25 book coverage, that START before our canonical (2026-04-22)
ud = df[s.str.contains("up-or-down", case=False, na=False)].copy()
uds = ud["slug"].astype(str)
crypto = ud[uds.str.contains("bitcoin|ethereum|solana|^btc-|^eth-|^sol-", case=False, na=False, regex=True)].copy()
has_l25 = crypto[crypto["book_snapshot_25_from"].notna() & (crypto["book_snapshot_25_from"] != "")].copy()
pre = has_l25[has_l25["book_snapshot_25_from"] < "2026-04-22"].copy()

print(f"crypto up/down WITH L25 book data: {len(has_l25):,}")
print(f"  of those, starting BEFORE 2026-04-22 (backfill candidates): {len(pre):,}")
print(f"  L25 date span available: {has_l25['book_snapshot_25_from'].min()} -> {has_l25['book_snapshot_25_to'].max()}")

# how many download-days would a full pre-Apr-22 backfill cost (book_snapshot_25 only)?
def daycount(a, b):
    try: return (pd.Timestamp(b) - pd.Timestamp(a)).days + 1
    except: return 0
pre["dl_days"] = [daycount(a, b) for a, b in zip(pre["book_snapshot_25_from"], pre["book_snapshot_25_to"])]
print(f"\n  total book_snapshot_25 file-days pre-Apr-22 = {int(pre['dl_days'].sum()):,} downloads (1 channel)")
print(f"  (× trades+quotes+onchain_fills if you want those too)")

# 15m epoch style specifically (closest to our canonical)
ep15 = pre[pre["slug"].astype(str).str.contains("-up-or-down-15m-", na=False)]
print(f"\n  epoch 15m pre-Apr-22 markets: {len(ep15):,}")

print("\n=== sample backfill targets (what you'd feed the downloader) ===")
cols = ["slug","outcome_0","book_snapshot_25_from","book_snapshot_25_to","onchain_fills_from","status"]
print(pre.sort_values("book_snapshot_25_from")[cols].head(15).to_string(index=False))
