"""
Audit data/v4/ for duplicates between canonical/ and refresh_*/cache/.
Classify every parquet/csv into:
  CANONICAL          — in canonical/, authoritative
  DUPLICATE_OF_CANON — in refresh_*/, but the data is now in canonical
  UNIQUE_NEED_KEEP   — in refresh_*/, NOT in canonical (special)
  STALE              — in canonical/, but very old + has fresher equivalent
"""
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
DATA = ROOT / "data" / "v4"

def size_mb(p): return p.stat().st_size / 1024 / 1024

# 1. Inventory canonical
print("=" * 80)
print("CANONICAL contents")
print("=" * 80)
canon_files = sorted((DATA / "canonical").rglob("*.parquet"))
canon_total = 0
for p in canon_files:
    rel = p.relative_to(DATA / "canonical")
    sz = size_mb(p)
    canon_total += sz
    print(f"  {str(rel):<55s} {sz:>9.1f} MB")
print(f"  {'TOTAL':<55s} {canon_total:>9.1f} MB")

# Other canonical files (non-parquet)
print("\nNon-parquet in canonical/:")
for p in sorted((DATA / "canonical").rglob("*")):
    if p.is_file() and p.suffix != ".parquet":
        rel = p.relative_to(DATA / "canonical")
        print(f"  {str(rel):<55s} {size_mb(p):>9.1f} MB  ({p.suffix})")

# 2. Inventory each refresh
print("\n" + "=" * 80)
print("REFRESH dirs (everything here is potentially redundant)")
print("=" * 80)
refresh_total = 0
for refresh_dir in sorted((DATA).glob("refresh_*")):
    if not refresh_dir.is_dir(): continue
    dir_total = 0
    files = sorted(refresh_dir.rglob("*"))
    files = [f for f in files if f.is_file()]
    print(f"\n{refresh_dir.name}/")
    for f in files:
        rel = f.relative_to(refresh_dir)
        sz = size_mb(f)
        dir_total += sz
        flag = ""
        if "_orderbook_L25" in f.name:
            flag = "  [REDUNDANT: consolidated in canonical/orderbook_l25/]"
        elif any(s in f.name for s in ["binance_klines","oracle_prices","_trades_delta","market_resolutions","trading_events","hyperliquid_"]):
            flag = "  [REDUNDANT: merged into canonical/]"
        elif f.suffix == ".gz":
            flag = "  [raw — already converted]"
        elif f.suffix in [".sh", ".py", ".sql"]:
            flag = "  [script — KEEP]"
        print(f"  {str(rel):<55s} {sz:>9.1f} MB{flag}")
    refresh_total += dir_total
    print(f"  -- {refresh_dir.name} total: {dir_total:>9.1f} MB")

print(f"\n=== GRAND TOTAL ===")
print(f"  canonical/  : {canon_total:>9.1f} MB")
print(f"  refresh_*/  : {refresh_total:>9.1f} MB")
print(f"  combined    : {canon_total+refresh_total:>9.1f} MB")
