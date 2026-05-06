# VPS2 → VPS3 Migration — 2026-05-06

**Purpose:** complete the partial migration before VPS2 deprecation (~10 days).
**Strategy:** ON CONFLICT DO NOTHING via SSH tunnel. Idempotent. Safe to re-run.
**Skipped:** `binance_liquidations_v2` (will be re-collected from non-geoblocked VPS).

## Pre-flight checklist (run on VPS2 before starting)

```bash
# 1. Verify SSH key from VPS2 → VPS3 works
ssh -i /root/.ssh/vps2_to_vps3 root@185.190.143.7 'echo OK'

# 2. Get VPS3 postgres password (from /etc/storedata/.env or wherever it lives on VPS3)
#    Save it as VPS3_PGPASSWORD env var
export VPS3_PGPASSWORD='<paste from VPS3 /etc/storedata/.env>'

# 3. Get VPS2 postgres password
export PGPASSWORD='<paste from VPS2 /etc/storedata/.env>'

# 4. Test tunnel works
ssh -i /root/.ssh/vps2_to_vps3 -L 5433:127.0.0.1:5432 -N -f \
    -o ServerAliveInterval=30 root@185.190.143.7
PGPASSWORD=$VPS3_PGPASSWORD psql -h 127.0.0.1 -p 5433 -U postgres -d storedata -c 'SELECT 1;'
```

## Execution order (run in sequence; each is idempotent)

| # | Script | Table | Rows | Estimated time | Priority |
|---|---|---|---:|---|---|
| 1 | `01_hl_liquidations.sh` | hyperliquid_liquidations_v2 | ~5.0M | 1-2 hr | P0 |
| 2 | `02_oracle_prices.sh` | oracle_prices_v2 | ~1.18M | 30 min | P0 |
| 3 | `03_markets.sh` | markets | ~756 rows | 1 min | P0 |
| 4 | `04_trades_v2.sh` | trades_v2 | ~2.5M | 1-2 hr | P1 |
| 5 | `05_orderbook_snapshots.sh` | orderbook_snapshots_v2 | ~1.5M | 2-3 hr | P1 |
| - | `99_run_all.sh` | (orchestrator) | all | ~5-7 hr total | — |

## How to fire all of them tonight

```bash
# On VPS2:
cd /tmp
# scp the migration_2026_05_06/ folder up first:
# (run from local) scp -i ~/.ssh/vps2_ed25519 -r "/c/Users/alexandre bandarra/Desktop/global/migration_2026_05_06" "root@[2605:a140:2323:6975::1]:/tmp/"

cd /tmp/migration_2026_05_06
chmod +x *.sh

# Set env vars
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=postgres PGDATABASE=storedata
export PGPASSWORD='<vps2 pw>'
export VPS3_HOST=127.0.0.1 VPS3_PORT=5433 VPS3_PGUSER=postgres VPS3_PGDATABASE=storedata
export VPS3_PGPASSWORD='<vps3 pw>'

# Start SSH tunnel
ssh -i /root/.ssh/vps2_to_vps3 -L 5433:127.0.0.1:5432 -N -f \
    -o ServerAliveInterval=30 root@185.190.143.7

# Run everything in background; output to log file
nohup ./99_run_all.sh > migration_$(date +%Y%m%d_%H%M%S).log 2>&1 &
echo $! > /tmp/migration.pid
disown

# Tail the log to confirm progress
tail -f migration_*.log
```

In the morning:
```bash
# Check it finished
cat /tmp/migration.pid && ps -p $(cat /tmp/migration.pid) || echo "Done"
grep -i "ERROR\|FAILED\|done\|finished" migration_*.log
```

## What each script does

Each script:
1. Opens a PIPED pg_dump from VPS2 → psql to VPS3
2. The dump is COPY-format, fed via stdin to a temporary table on VPS3
3. Then `INSERT INTO target SELECT * FROM tmp ON CONFLICT DO NOTHING`
4. DROP temp table
5. Reports rows-before / rows-after count

This handles BOTH:
- (a) The historical gaps from incomplete prior migration
- (b) The daily 5-10% live collector loss (where VPS3 missing rows scattered through every day)

PKs/uniques absorb existing rows automatically.

## Rollback

If anything goes wrong, the only effect is "extra rows on VPS3 that weren't there before." There's nothing destructive. To roll back a specific table you'd `DELETE FROM <table> WHERE ...` based on whatever range you want to remove — but no script here deletes or modifies existing rows.

## Files in this directory

- `00_README.md` (this file)
- `01_hl_liquidations.sh`
- `02_oracle_prices.sh`
- `03_markets.sh`
- `04_trades_v2.sh`
- `05_orderbook_snapshots.sh`
- `99_run_all.sh`
- `local_pull.sh` — separate script for pulling missing data to local (run AFTER migration)
