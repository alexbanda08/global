"""Split fresh tier1_entries_full.csv into per-asset parquets.

Run AFTER migration_2026_05_08/local_pull.sh step 7 completes.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_09"
TIER1 = REFRESH / "tier1_entries"


def main():
    src = TIER1 / "tier1_entries_full.csv"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    df = pd.read_csv(src)
    print(f"[split] rows={len(df)} slugs={df.slug.nunique()} assets={df.asset.value_counts().to_dict()}")
    if "dt_abs" in df.columns:
        df["dt_abs_ms"] = df["dt_abs"] / 1000.0
        print(f"  dt_abs ms: min={df.dt_abs_ms.min():.0f}  median={df.dt_abs_ms.median():.0f}  "
              f"p95={df.dt_abs_ms.quantile(0.95):.0f}  max={df.dt_abs_ms.max():.0f}")
    for asset in ("btc", "eth", "sol"):
        sub = df[df.asset == asset].copy()
        out = TIER1 / f"{asset}_entries_at_t120.parquet"
        sub.to_parquet(out, index=False)
        print(f"  {asset}: {len(sub)} -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
