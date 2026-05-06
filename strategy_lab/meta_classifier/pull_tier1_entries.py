"""Tier 1 pull — single snapshot per (slug, outcome) closest to t+120s.

Goal: replace the 10s-bucket entry approximation with the actual orderbook
snapshot at (microsecond) entry time, with all 25 levels of depth. This
eliminates aggregation artifacts and gives realistic fill simulation.

Strategy:
  1. Build universe CSV: all (asset, slug, outcome, target_ts_us)
  2. SCP to VPS2
  3. Run SQL: for each (slug, outcome), pick the snapshot in orderbook_snapshots_v2
     with min(abs(timestamp_us - target_ts_us)) within ±5s tolerance.
  4. SCP result back, save as parquet.

The result is ~28k rows × 100+ cols (slug, outcome, ts, 25 bid levels, 25 ask levels).
~22 MB.

Outputs:
  data/v4/tier1_entries/btc_entries_at_t120.parquet
  data/v4/tier1_entries/eth_entries_at_t120.parquet
  data/v4/tier1_entries/sol_entries_at_t120.parquet
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_02"
OUT_DIR = ROOT / "data" / "v4" / "tier1_entries"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration via env vars — never commit literal credentials.
# Required:
#   VPS2_HOST          (e.g. "root@[2605:...]")
#   VPS2_RO_PWD        (Postgres tradingvenue_ro password)
# Optional:
#   VPS2_SSH_KEY       (default: ~/.ssh/vps2_ed25519)
VPS2_HOST = os.environ.get("VPS2_HOST") or sys.exit("set VPS2_HOST env var")
VPS2_KEY = os.environ.get("VPS2_SSH_KEY") or str(Path.home() / ".ssh" / "vps2_ed25519")
VPS2_PWD = os.environ.get("VPS2_RO_PWD") or sys.exit("set VPS2_RO_PWD env var")


def build_universe_csv():
    """Build (slug, outcome, target_ts_us) lookup for all 3 assets."""
    rows = []
    for asset in ["btc", "eth", "sol"]:
        df = pd.read_csv(REFRESH / f"{asset}_markets_minimal.csv").dropna(
            subset=["window_start_unix", "outcome_up"])
        for _, r in df.iterrows():
            ws = int(r["window_start_unix"])
            target_us = (ws + 120) * 1_000_000
            for outcome in ["Up", "Down"]:
                rows.append(dict(
                    asset=asset,
                    slug=r["slug"],
                    outcome=outcome,
                    target_ts_us=target_us,
                ))
    df = pd.DataFrame(rows)
    out_path = OUT_DIR / "universe_lookup.csv"
    df.to_csv(out_path, index=False)
    print(f"[universe] wrote {out_path}  rows={len(df)}")
    return out_path


def pull_from_vps2(universe_csv: Path) -> Path:
    """SCP universe to VPS2, run SQL, SCP result back."""
    # Upload universe
    print(f"[scp] uploading universe to VPS2…")
    r = subprocess.run(
        ["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
         str(universe_csv), f"{VPS2_HOST}:/tmp/universe_lookup.csv"],
        capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"scp failed: {r.stderr}")

    # Build SQL
    sql = """
\\set ON_ERROR_STOP on

DROP TABLE IF EXISTS tmp_universe;
CREATE TEMP TABLE tmp_universe (
    asset TEXT,
    slug TEXT,
    outcome TEXT,
    target_ts_us BIGINT
);

\\copy tmp_universe(asset, slug, outcome, target_ts_us) FROM '/tmp/universe_lookup.csv' CSV HEADER

CREATE INDEX tmp_uni_slug ON tmp_universe(slug, outcome);

-- For each (slug, outcome), pick the snapshot in [target-5s, target+5s] with
-- the smallest abs distance to target. Two-step: build temp result table then \\copy.
DROP TABLE IF EXISTS tmp_tier1;
CREATE TEMP TABLE tmp_tier1 AS
WITH candidates AS (
  SELECT
    u.asset, u.slug, u.outcome, u.target_ts_us,
    o.timestamp_us,
    ABS(o.timestamp_us - u.target_ts_us) AS dt_abs,
    o.bid_price_0, o.bid_size_0, o.bid_price_1, o.bid_size_1, o.bid_price_2, o.bid_size_2,
    o.bid_price_3, o.bid_size_3, o.bid_price_4, o.bid_size_4, o.bid_price_5, o.bid_size_5,
    o.bid_price_6, o.bid_size_6, o.bid_price_7, o.bid_size_7, o.bid_price_8, o.bid_size_8,
    o.bid_price_9, o.bid_size_9, o.bid_price_10, o.bid_size_10, o.bid_price_11, o.bid_size_11,
    o.bid_price_12, o.bid_size_12, o.bid_price_13, o.bid_size_13, o.bid_price_14, o.bid_size_14,
    o.bid_price_15, o.bid_size_15, o.bid_price_16, o.bid_size_16, o.bid_price_17, o.bid_size_17,
    o.bid_price_18, o.bid_size_18, o.bid_price_19, o.bid_size_19, o.bid_price_20, o.bid_size_20,
    o.bid_price_21, o.bid_size_21, o.bid_price_22, o.bid_size_22, o.bid_price_23, o.bid_size_23,
    o.bid_price_24, o.bid_size_24,
    o.ask_price_0, o.ask_size_0, o.ask_price_1, o.ask_size_1, o.ask_price_2, o.ask_size_2,
    o.ask_price_3, o.ask_size_3, o.ask_price_4, o.ask_size_4, o.ask_price_5, o.ask_size_5,
    o.ask_price_6, o.ask_size_6, o.ask_price_7, o.ask_size_7, o.ask_price_8, o.ask_size_8,
    o.ask_price_9, o.ask_size_9, o.ask_price_10, o.ask_size_10, o.ask_price_11, o.ask_size_11,
    o.ask_price_12, o.ask_size_12, o.ask_price_13, o.ask_size_13, o.ask_price_14, o.ask_size_14,
    o.ask_price_15, o.ask_size_15, o.ask_price_16, o.ask_size_16, o.ask_price_17, o.ask_size_17,
    o.ask_price_18, o.ask_size_18, o.ask_price_19, o.ask_size_19, o.ask_price_20, o.ask_size_20,
    o.ask_price_21, o.ask_size_21, o.ask_price_22, o.ask_size_22, o.ask_price_23, o.ask_size_23,
    o.ask_price_24, o.ask_size_24
  FROM tmp_universe u
  JOIN orderbook_snapshots_v2 o
    ON o.slug = u.slug
   AND o.outcome = u.outcome
   AND o.timestamp_us BETWEEN (u.target_ts_us - 5000000) AND (u.target_ts_us + 5000000)
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY slug, outcome ORDER BY dt_abs ASC) AS rn
  FROM candidates
)
SELECT * FROM ranked WHERE rn = 1;

\\copy (SELECT * FROM tmp_tier1) TO '/tmp/tier1_entries.csv' CSV HEADER
"""
    sql_path = OUT_DIR / "pull_tier1.sql"
    sql_path.write_text(sql)

    print(f"[scp] uploading SQL…")
    subprocess.run(
        ["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
         str(sql_path), f"{VPS2_HOST}:/tmp/pull_tier1.sql"],
        capture_output=True, text=True, check=True)

    # Run psql
    print(f"[ssh] running SQL on VPS2 (this will take ~30-90s)…")
    cmd = (
        f"PGPASSWORD={VPS2_PWD} psql -h 127.0.0.1 -U tradingvenue_ro -d storedata "
        f"-f /tmp/pull_tier1.sql"
    )
    r = subprocess.run(
        ["ssh", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
         VPS2_HOST, cmd],
        capture_output=True, text=True)
    print("[ssh stdout]:", r.stdout[-300:] if r.stdout else "")
    print("[ssh stderr]:", r.stderr[-500:] if r.stderr else "")
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr}")

    # SCP result back
    out_csv = OUT_DIR / "tier1_entries_raw.csv"
    print(f"[scp] downloading result…")
    subprocess.run(
        ["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
         f"{VPS2_HOST}:/tmp/tier1_entries.csv", str(out_csv)],
        capture_output=True, text=True, check=True)

    size_mb = out_csv.stat().st_size / 1e6
    print(f"[done] wrote {out_csv}  ({size_mb:.1f} MB)")
    return out_csv


def split_by_asset(raw_csv: Path):
    """Split tier1_entries_raw.csv by asset and convert to parquet for compactness."""
    df = pd.read_csv(raw_csv)
    print(f"\n[split] total rows: {len(df)}")
    print(f"  unique slugs: {df.slug.nunique()}")
    print(f"  asset counts: {df.asset.value_counts().to_dict()}")
    print(f"  outcome counts: {df.outcome.value_counts().to_dict()}")

    # Diagnostic: how close did we get to the target ts?
    df["dt_abs_ms"] = df["dt_abs"] / 1000.0
    print(f"  dt_abs (ms) — closeness to t+120s target:")
    print(f"    min={df.dt_abs_ms.min():.1f}  median={df.dt_abs_ms.median():.1f}  "
          f"p95={df.dt_abs_ms.quantile(0.95):.1f}  max={df.dt_abs_ms.max():.1f}")

    for asset in ["btc", "eth", "sol"]:
        sub = df[df.asset == asset].copy()
        out = OUT_DIR / f"{asset}_entries_at_t120.parquet"
        sub.to_parquet(out, index=False)
        print(f"    {asset}: {len(sub)} rows -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


def main():
    universe_csv = build_universe_csv()
    raw_csv = pull_from_vps2(universe_csv)
    split_by_asset(raw_csv)


if __name__ == "__main__":
    main()
