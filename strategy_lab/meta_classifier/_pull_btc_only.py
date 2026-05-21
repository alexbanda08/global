"""Retry BTC L25 pull from VPS2 — write SQL to remote file then execute via psql -f."""
import csv
import subprocess
from pathlib import Path

ROOT = Path(r"C:\Users\alexandre bandarra\Desktop\global")
OUT = ROOT / "data/v4/shadow_trades_2026_05_08"

# Get BTC condition_ids
btc_ids = set()
with open(OUT / "momo_v1v2_live.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["symbol"] == "BTC" and row["condition_id"]:
            btc_ids.add(row["condition_id"])
print(f"BTC markets: {len(btc_ids)}")

# Build SQL file locally
sql_local = OUT / "_pull_btc_l25.sql"
quoted = ",".join(f"'{m}'" for m in btc_ids)
# \copy is a single-line meta-command — keep entire statement on one line.
sql_text = (
    "\\copy (SELECT timestamp_us, slug, market_id, asset_id, outcome, "
    + ", ".join([f"bid_price_{i}, bid_size_{i}" for i in range(25)]) + ", "
    + ", ".join([f"ask_price_{i}, ask_size_{i}" for i in range(25)])
    + f" FROM orderbook_snapshots_v2 WHERE market_id IN ({quoted}) "
    + "AND timestamp_us > extract(epoch from now() - interval '8 days')*1000000 "
    + "ORDER BY market_id, outcome_id, timestamp_us) TO '/tmp/vps2_l25_btc.csv' CSV HEADER\n"
)
sql_local.write_text(sql_text, encoding="utf-8")
print(f"SQL bytes: {len(sql_text)}")

SSH_KEY = str(Path.home() / ".ssh" / "vps2_ed25519")
HOST = "root@[2605:a140:2323:6975::1]"

# scp SQL to remote
print("uploading SQL…")
proc = subprocess.run(
    ["scp", "-i", SSH_KEY, str(sql_local), f"{HOST}:/tmp/_pull_btc_l25.sql"],
    capture_output=True, text=True, timeout=60
)
if proc.returncode != 0:
    print(f"scp upload error: {proc.stderr}"); raise SystemExit(1)

# Execute via psql -f
print("executing on VPS2…")
proc = subprocess.run(
    ["ssh", "-i", SSH_KEY, "-o", "ConnectTimeout=20", HOST,
     "set -a; source /etc/tv/tv-ro.env 2>/dev/null; set +a; "
     "export PGPASSWORD=\"$TV_RO_PWD_PLAIN\"; "
     "psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -f /tmp/_pull_btc_l25.sql; "
     "wc -l /tmp/vps2_l25_btc.csv"],
    capture_output=True, text=True, timeout=600
)
print(f"stdout tail: {proc.stdout[-300:]}")
print(f"stderr tail: {proc.stderr[-300:]}")

# Pull back to local
print("scp back…")
proc = subprocess.run(
    ["scp", "-i", SSH_KEY, f"{HOST}:/tmp/vps2_l25_btc.csv", str(OUT / "vps2_l25_btc.csv")],
    capture_output=True, text=True, timeout=600
)
if proc.returncode == 0:
    n = sum(1 for _ in open(OUT / "vps2_l25_btc.csv", encoding="utf-8"))
    print(f"BTC: {n-1} rows -> vps2_l25_btc.csv")
else:
    print(f"scp pull err: {proc.stderr}")
