"""Pull tier1 entries for the FULL extended universe (15,370 markets, Apr 22 -> May 6).

Same as pull_tier1_entries.py but uses the fresh market_resolutions_full.csv
(direct from VPS2) instead of the local 4673-market csv. Outputs split by asset
into refresh_2026_05_06/.
"""
from __future__ import annotations
import os
import sys
import subprocess
from pathlib import Path
import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
REFRESH = ROOT / "data" / "v4" / "refresh_2026_05_06"
OUT_DIR = REFRESH / "tier1_entries"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Configuration via env vars — never commit literal credentials.
VPS2_HOST = os.environ.get("VPS2_HOST") or sys.exit("set VPS2_HOST env var")
VPS2_KEY = os.environ.get("VPS2_SSH_KEY") or str(Path.home() / ".ssh" / "vps2_ed25519")
VPS2_PWD = os.environ.get("VPS2_RO_PWD") or sys.exit("set VPS2_RO_PWD env var")


def build_universe_csv():
    src = REFRESH / "market_resolutions_full.csv"
    df = pd.read_csv(src)
    df["asset"] = df["slug"].str.extract(r'^(btc|eth|sol)-updown-')[0]
    df = df.dropna(subset=["asset", "window_start_unix", "outcome_up"]).copy()
    df["window_start_unix"] = df["window_start_unix"].astype("int64")
    rows = []
    for _, r in df.iterrows():
        target_us = (int(r["window_start_unix"]) + 120) * 1_000_000
        for outcome in ("Up", "Down"):
            rows.append(dict(
                asset=r["asset"], slug=r["slug"], outcome=outcome,
                target_ts_us=target_us,
            ))
    out = pd.DataFrame(rows)
    p = OUT_DIR / "universe_lookup.csv"
    out.to_csv(p, index=False)
    print(f"[universe] wrote {p}  rows={len(out)} markets={df.shape[0]}")
    return p


def pull(universe_csv: Path) -> Path:
    print("[scp] uploading universe…")
    subprocess.run(["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
                    str(universe_csv), f"{VPS2_HOST}:/tmp/universe_lookup_full.csv"],
                   check=True, capture_output=True, text=True)

    sql = """
\\set ON_ERROR_STOP on

DROP TABLE IF EXISTS tmp_universe;
CREATE TEMP TABLE tmp_universe (
    asset TEXT, slug TEXT, outcome TEXT, target_ts_us BIGINT
);
\\copy tmp_universe(asset, slug, outcome, target_ts_us) FROM '/tmp/universe_lookup_full.csv' CSV HEADER
CREATE INDEX tmp_uni_slug ON tmp_universe(slug, outcome);

DROP TABLE IF EXISTS tmp_tier1;
CREATE TEMP TABLE tmp_tier1 AS
WITH candidates AS (
  SELECT u.asset, u.slug, u.outcome, u.target_ts_us, o.timestamp_us,
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
    ON o.slug = u.slug AND o.outcome = u.outcome
   AND o.timestamp_us BETWEEN (u.target_ts_us - 5000000) AND (u.target_ts_us + 5000000)
),
ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY slug, outcome ORDER BY dt_abs ASC) AS rn
  FROM candidates
)
SELECT * FROM ranked WHERE rn = 1;

\\copy (SELECT * FROM tmp_tier1) TO '/tmp/tier1_entries_full.csv' CSV HEADER
"""
    sql_path = OUT_DIR / "pull_tier1_full.sql"
    sql_path.write_text(sql)
    subprocess.run(["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
                    str(sql_path), f"{VPS2_HOST}:/tmp/pull_tier1_full.sql"],
                   check=True, capture_output=True, text=True)

    print("[ssh] running SQL on VPS2 (~60-180s)…")
    cmd = (f"PGPASSWORD={VPS2_PWD} psql -h 127.0.0.1 -U tradingvenue_ro -d storedata "
           f"-f /tmp/pull_tier1_full.sql")
    r = subprocess.run(["ssh", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
                        VPS2_HOST, cmd], capture_output=True, text=True)
    print("[ssh stdout]:", r.stdout[-300:])
    print("[ssh stderr]:", r.stderr[-300:])

    out_csv = OUT_DIR / "tier1_entries_full.csv"
    print("[scp] downloading…")
    subprocess.run(["scp", "-i", VPS2_KEY, "-o", "StrictHostKeyChecking=no",
                    f"{VPS2_HOST}:/tmp/tier1_entries_full.csv", str(out_csv)],
                   check=True, capture_output=True, text=True)
    print(f"[done] {out_csv}  ({out_csv.stat().st_size/1e6:.1f} MB)")
    return out_csv


def split_by_asset(raw_csv: Path):
    df = pd.read_csv(raw_csv)
    print(f"\n[split] rows={len(df)}  slugs={df.slug.nunique()}  asset={df.asset.value_counts().to_dict()}")
    df["dt_abs_ms"] = df["dt_abs"] / 1000.0
    print(f"  dt_abs ms: min={df.dt_abs_ms.min():.0f}  median={df.dt_abs_ms.median():.0f}  "
          f"p95={df.dt_abs_ms.quantile(0.95):.0f}  max={df.dt_abs_ms.max():.0f}")
    for asset in ("btc", "eth", "sol"):
        sub = df[df.asset == asset].copy()
        out = OUT_DIR / f"{asset}_entries_at_t120.parquet"
        sub.to_parquet(out, index=False)
        print(f"  {asset}: {len(sub)} -> {out.name} ({out.stat().st_size/1e6:.1f} MB)")


def main():
    u = build_universe_csv()
    raw = pull(u)
    split_by_asset(raw)


if __name__ == "__main__":
    main()
