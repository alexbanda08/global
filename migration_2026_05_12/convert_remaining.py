"""Convert only the 2 failed items: hl_liquidations_30d + trading.events 30d."""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "migration_2026_05_12"))

from convert_tier_all_2026_05_16 import convert_simple, V3_SRC, CANON

convert_simple("HL liqs 30d", V3_SRC / "hl_liquidations_30d.csv.gz", CANON / "hyperliquid_liquidations_30d.parquet")
convert_simple("trading.events 30d", V3_SRC / "trading_events_30d.csv.gz", CANON / "trading_events_30d.parquet")
print("\n=== remaining done ===")
