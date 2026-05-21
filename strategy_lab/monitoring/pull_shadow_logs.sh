#!/usr/bin/env bash
# Pull PAT+ACC-M shadow logs from Ireland VPS to local cache for monitor analysis.
#
# Prereq: SSH alias `ireland` configured in ~/.ssh/config pointing at the
# TV agent's host (the Ireland VPS where TradingVenue runs).
#
# Usage:
#   bash strategy_lab/monitoring/pull_shadow_logs.sh
#   bash strategy_lab/monitoring/pull_shadow_logs.sh --since 2026-05-19
#   bash strategy_lab/monitoring/pull_shadow_logs.sh --host my-ireland-alias
#
# Output: strategy_lab/monitoring/_logs/acc-m_*.csv (and pat-shadow_*.csv if present)
set -euo pipefail

HOST="${TV_HOST:-ireland}"
REMOTE_DIR="${TV_LOG_DIR:-/var/log/tv/maker}"
LOCAL_DIR="$(dirname "$0")/_logs"
SINCE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --host)  HOST="$2"; shift 2 ;;
        --remote-dir) REMOTE_DIR="$2"; shift 2 ;;
        --since) SINCE="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--host SSHALIAS] [--remote-dir PATH] [--since YYYY-MM-DD]"
            exit 0 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$LOCAL_DIR"

echo "Pulling from ${HOST}:${REMOTE_DIR}/ -> ${LOCAL_DIR}/"

if [[ -n "$SINCE" ]]; then
    # Only files modified on/after $SINCE
    REMOTE_FILES=$(ssh "$HOST" "find $REMOTE_DIR -name 'acc-m_*.csv' -newermt '$SINCE'")
    if [[ -z "$REMOTE_FILES" ]]; then
        echo "  no files since $SINCE"; exit 0
    fi
    while IFS= read -r f; do
        scp "${HOST}:${f}" "$LOCAL_DIR/"
    done <<< "$REMOTE_FILES"
else
    scp "${HOST}:${REMOTE_DIR}/acc-m_*.csv" "$LOCAL_DIR/" 2>/dev/null || \
        echo "  WARN: no acc-m_*.csv files found on ${HOST}"
    scp "${HOST}:${REMOTE_DIR}/pat-shadow_*.csv" "$LOCAL_DIR/" 2>/dev/null || true
fi

echo
echo "Local files:"
ls -la "$LOCAL_DIR/"
echo
echo "Next: py -3 -X utf8 strategy_lab/monitoring/shadow_monitor.py \\"
echo "          --csv $LOCAL_DIR/acc-m_*.csv"
