"""Convert the 5 remaining datasets to parquet, place in canonical.

Inputs: data/v4/refresh_2026_05_16/cache_extra/
Outputs:
  canonical/hyperliquid_liquidations_full.parquet     -- May 2025 -> May 2026 (5.2M rows)
  canonical/cryptocap_dominance.parquet               -- 2014 -> 2026 (40k rows)
  canonical/binance_metrics.parquet                   -- 2025 -> 2026 (315k rows)
  canonical/hyperliquid_funding.parquet               -- 2026-01-30 -> now (10k rows)
  canonical/hyperliquid_metrics.parquet               -- 2026-04-30 -> now (88k rows)
"""
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
sys.path.insert(0, str(ROOT / "migration_2026_05_12"))

from convert_tier_all_2026_05_16 import convert_simple

SRC = ROOT / "data/v4/refresh_2026_05_16/cache_extra"
CANON = ROOT / "data/v4/canonical"

convert_simple("HL liquidations FULL",  SRC / "hl_liquidations_full.csv.gz",     CANON / "hyperliquid_liquidations_full.parquet")
convert_simple("cryptocap dominance",   SRC / "cryptocap_dominance_full.csv.gz", CANON / "cryptocap_dominance.parquet")
convert_simple("binance_metrics",       SRC / "binance_metrics_full.csv.gz",     CANON / "binance_metrics.parquet")
convert_simple("HL funding",            SRC / "hl_funding_full.csv.gz",          CANON / "hyperliquid_funding.parquet")
convert_simple("HL metrics",            SRC / "hl_metrics_full.csv.gz",          CANON / "hyperliquid_metrics.parquet")

print("\n=== Done ===")
