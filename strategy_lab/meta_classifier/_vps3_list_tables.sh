#!/bin/bash
# List storedata tables for momo discovery.
set -euo pipefail
set -a; source /etc/tv/tv-ro.env; set +a
export PGPASSWORD="$TV_RO_PWD_PLAIN"

psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -tA <<'SQL'
SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('public', 'trading')
ORDER BY table_schema, table_name;
SQL
