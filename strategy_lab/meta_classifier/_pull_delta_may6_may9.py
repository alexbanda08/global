"""Pull May 6 → May 9 delta data from VPS2 + VPS3 to extend refresh_2026_05_06.

Saves to data/v4/refresh_2026_05_09/:
  markets_full.csv
  market_resolutions_full.csv
  klines_full.csv
  cache/{btc,eth,sol}_orderbook_L25.parquet  (May 6 onward only — combine with old at runtime)
"""
import csv
import io
import subprocess
from pathlib import Path

import pandas as pd

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
NEW_DIR = ROOT / "data/v4/refresh_2026_05_09"
NEW_DIR.mkdir(parents=True, exist_ok=True)
(NEW_DIR / "cache").mkdir(parents=True, exist_ok=True)

VPS2_KEY = str(Path.home() / ".ssh" / "vps2_ed25519")
VPS3_KEY = str(Path.home() / ".ssh" / "vps3_ed25519")
VPS2_HOST = "root@[2605:a140:2323:6975::1]"
VPS3_HOST = "root@185.190.143.7"


def ssh_copy(host: str, key: str, sql: str, remote_path: str, local_path: Path):
    """Run psql -c \\copy on remote, then scp the resulting file back."""
    full_cmd = (
        "set -a; source /etc/tv/tv-ro.env 2>/dev/null; set +a; "
        "export PGPASSWORD=\"$TV_RO_PWD_PLAIN\"; "
        f"psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -c \"{sql}\""
    )
    proc = subprocess.run(
        ["ssh", "-i", key, "-o", "ConnectTimeout=30", host, full_cmd],
        capture_output=True, text=True, timeout=900
    )
    if proc.returncode != 0:
        print(f"    [ssh err] {proc.stderr[-200:]}")
        return False
    # tail of stdout shows COPY <count> if successful
    print(f"    [ssh ok] {proc.stdout.strip()[-200:]}")
    proc2 = subprocess.run(
        ["scp", "-i", key, f"{host}:{remote_path}", str(local_path)],
        capture_output=True, text=True, timeout=600
    )
    if proc2.returncode != 0:
        print(f"    [scp err] {proc2.stderr[-200:]}")
        return False
    return True


# ---------- VPS3: markets + resolutions ----------
print("[vps3] markets...")
sql_m = (
    "\\copy (SELECT slug, market_id, condition_id, ticker, timeframe, outcome, status, "
    "       resolved_at, created_at "
    "       FROM public.markets WHERE created_at > now() - interval '28 days') "
    "       TO '/tmp/delta_markets.csv' CSV HEADER"
)
ssh_copy(VPS3_HOST, VPS3_KEY, sql_m, "/tmp/delta_markets.csv", NEW_DIR / "markets_full.csv")

print("[vps3] resolutions...")
sql_r = (
    "\\copy (SELECT slug, outcome, recorded_at, source FROM public.market_resolutions_v2 "
    "       WHERE recorded_at > now() - interval '28 days') "
    "       TO '/tmp/delta_resolutions.csv' CSV HEADER"
)
ssh_copy(VPS3_HOST, VPS3_KEY, sql_r, "/tmp/delta_resolutions.csv", NEW_DIR / "market_resolutions_full.csv")

# ---------- VPS2: klines + L25 ----------
print("[vps2] klines (1m, last 28 days)...")
sql_k = (
    "\\copy (SELECT symbol_id, period_id, time_period_start_us, price_close, source "
    "       FROM binance_klines_v2 "
    "       WHERE period_id='1MIN' "
    "       AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT',"
    "                         'OKX_SPOT_BTC_USDT','OKX_SPOT_ETH_USDT','OKX_SPOT_SOL_USDT') "
    "       AND time_period_start_us > extract(epoch from now() - interval '28 days')*1000000) "
    "       TO '/tmp/delta_klines.csv' CSV HEADER"
)
ssh_copy(VPS2_HOST, VPS2_KEY, sql_k, "/tmp/delta_klines.csv", NEW_DIR / "klines_full.csv")

# Per-asset L25 — pull May 6 onward only (the delta vs existing refresh_2026_05_06)
DELTA_START_US = 1778083200_000_000  # 2026-05-06 12:00 UTC in microseconds (BIGINT literal)
for asset in ("btc", "eth", "sol"):
    print(f"[vps2] L25 delta for {asset}...")
    cols_levels = ", ".join([f"bid_price_{i}, bid_size_{i}" for i in range(25)] +
                             [f"ask_price_{i}, ask_size_{i}" for i in range(25)])
    sql_l25 = (
        f"\\copy (SELECT timestamp_us, slug, market_id, asset_id, outcome, {cols_levels} "
        f"        FROM orderbook_snapshots_v2 "
        f"        WHERE slug LIKE '{asset}-updown-%' "
        f"        AND timestamp_us > {DELTA_START_US}::bigint) "
        f"        TO '/tmp/delta_l25_{asset}.csv' CSV HEADER"
    )
    csv_path = NEW_DIR / f"{asset}_orderbook_L25_delta.csv"
    if not ssh_copy(VPS2_HOST, VPS2_KEY, sql_l25, f"/tmp/delta_l25_{asset}.csv", csv_path):
        continue
    # Convert to parquet (compress, faster downstream load)
    print(f"    converting {asset} to parquet...")
    chunks = []
    for chunk in pd.read_csv(csv_path, chunksize=200_000, low_memory=False):
        chunks.append(chunk)
    df = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
    parquet_path = NEW_DIR / "cache" / f"{asset}_orderbook_L25_delta.parquet"
    df.to_parquet(parquet_path, index=False, compression="snappy")
    print(f"    {asset}: {len(df)} rows -> {parquet_path.name}")
    csv_path.unlink()  # cleanup CSV

print("\nDone. Delta data in:", NEW_DIR)
