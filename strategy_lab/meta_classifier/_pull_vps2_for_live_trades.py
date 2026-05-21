"""Pull L25 books + klines from VPS2 covering the exact markets where live momo
v1+v2 trades fired in the last 7 days. Saves per-asset CSVs locally.

Strategy:
1. Read local momo_v1v2_live.csv to get unique (condition_id, asset, ws_unix) tuples
2. For each asset, query VPS2 orderbook_snapshots_v2 for those market_ids over each
   market's lifecycle (slug_ws-60 → slug_ws+window-60+30 = strike → resolve+30s slack)
3. Pull klines for the union time window
4. Save CSVs to data/v4/shadow_trades_2026_05_08/

Output:
  vps2_l25_btc.csv, _eth.csv, _sol.csv  -- L25 books per asset
  vps2_klines_1m.csv                    -- 1m Binance closes for all 3 assets
"""
import csv
import re
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT = ROOT / "data/v4/shadow_trades_2026_05_08"
OUT.mkdir(parents=True, exist_ok=True)

# Read live trades
trades = []
with open(OUT / "momo_v1v2_live.csv", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        trades.append(row)

# Per-asset unique markets
slug_re = re.compile(r"-(\d+)$")
markets_by_asset: dict[str, set] = {"BTC": set(), "ETH": set(), "SOL": set()}
all_ws_s = set()
for r in trades:
    asset = r["symbol"]
    cid = r["condition_id"]
    if not cid or asset not in markets_by_asset:
        continue
    markets_by_asset[asset].add(cid)
    # we'll learn ws from VPS2 slug
print(f"unique markets: BTC={len(markets_by_asset['BTC'])} ETH={len(markets_by_asset['ETH'])} SOL={len(markets_by_asset['SOL'])}")
total = sum(len(s) for s in markets_by_asset.values())
print(f"total: {total}")

# Build SQL — for each asset, pull L25 for those market_ids in last 8 days (covers all live trades)
SSH = ["ssh", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"), "-o", "ConnectTimeout=20",
       "root@[2605:a140:2323:6975::1]"]

def run_sql_to_local(sql: str, remote_path: str, local_path: Path):
    """Run psql -c \\copy on VPS2, then scp to local."""
    full = (
        "set -a; source /etc/tv/tv-ro.env 2>/dev/null; set +a; "
        "export PGPASSWORD=\"$TV_RO_PWD_PLAIN\"; "
        f"psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -c \"\\copy ({sql}) TO '{remote_path}' CSV HEADER\""
    )
    proc = subprocess.run(SSH + [full], capture_output=True, text=True, timeout=600)
    print(f"  [sql] {proc.stderr.strip()[-200:] if proc.stderr else proc.stdout.strip()[-200:]}")
    # scp
    scp = ["scp", "-i", str(Path.home() / ".ssh" / "vps2_ed25519"),
           f"root@[2605:a140:2323:6975::1]:{remote_path}", str(local_path)]
    proc2 = subprocess.run(scp, capture_output=True, text=True, timeout=600)
    if proc2.returncode != 0:
        print(f"  [scp ERROR] {proc2.stderr}")
    return local_path.exists()

# Pull L25 per asset
for asset, mkt_ids in markets_by_asset.items():
    if not mkt_ids:
        continue
    print(f"\n[{asset}] pulling L25 for {len(mkt_ids)} markets…")
    quoted = ",".join(f"'{m}'" for m in mkt_ids)
    # Pull all snapshots for these markets in window: 7 days back to now
    sql = (
        "SELECT timestamp_us, slug, market_id, asset_id, outcome, "
        + ", ".join([f"bid_price_{i}, bid_size_{i}" for i in range(25)]) + ", "
        + ", ".join([f"ask_price_{i}, ask_size_{i}" for i in range(25)])
        + f" FROM orderbook_snapshots_v2 WHERE market_id IN ({quoted}) "
        + "AND timestamp_us > extract(epoch from now() - interval '8 days')*1000000 "
        + "ORDER BY market_id, outcome_id, timestamp_us"
    )
    remote = f"/tmp/vps2_l25_{asset.lower()}.csv"
    local = OUT / f"vps2_l25_{asset.lower()}.csv"
    if run_sql_to_local(sql, remote, local):
        n = sum(1 for _ in open(local, encoding="utf-8"))
        print(f"  {asset}: {n-1} rows -> {local.name}")

# Pull klines for all 3 assets, 1m, last 8 days
print(f"\n[klines] pulling 1m Binance + OKX last 8 days…")
sql = (
    "SELECT symbol_id, time_period_start_us, price_close, source "
    "FROM binance_klines_v2 "
    "WHERE period_id='1MIN' "
    "AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT',"
    "'OKX_SPOT_BTC_USDT','OKX_SPOT_ETH_USDT','OKX_SPOT_SOL_USDT') "
    "AND time_period_start_us > extract(epoch from now() - interval '8 days')*1000000 "
    "ORDER BY symbol_id, time_period_start_us"
)
remote = "/tmp/vps2_klines_1m.csv"
local = OUT / "vps2_klines_1m.csv"
if run_sql_to_local(sql, remote, local):
    n = sum(1 for _ in open(local, encoding="utf-8"))
    print(f"  klines: {n-1} rows -> {local.name}")

print("\nDONE.")
