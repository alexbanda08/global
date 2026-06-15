#!/bin/bash
# Probe VPS3 for hyperliquid_* tables: row count + max timestamp.
for t in $(sudo -u postgres psql -d storedata -tAc "SELECT tablename FROM pg_tables WHERE tablename LIKE 'hyperliquid%' ORDER BY tablename"); do
  echo "=== $t ==="
  # find a timestamp-ish column
  col=$(sudo -u postgres psql -d storedata -tAc "SELECT column_name FROM information_schema.columns WHERE table_name='$t' AND (column_name LIKE '%_us' OR column_name LIKE '%time%') ORDER BY ordinal_position LIMIT 1")
  if [ -n "$col" ]; then
    sudo -u postgres psql -d storedata -tAc "SELECT count(*), max($col) FROM $t"
    echo "  (ts col: $col)"
  else
    sudo -u postgres psql -d storedata -tAc "SELECT count(*) FROM $t"
    echo "  (no ts col)"
  fi
done
