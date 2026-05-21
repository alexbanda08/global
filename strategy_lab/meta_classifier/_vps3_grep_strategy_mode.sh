#!/bin/bash
# Find where strategy_mode is read/dispatched in the production controller.
set -euo pipefail
cd /opt/tradingvenue || exit 1

echo "=== git HEAD ==="
git rev-parse HEAD 2>&1 | head -1
git log -1 --oneline 2>&1 | head -1
echo ""

echo "=== files containing 'strategy_mode' ==="
grep -rln 'strategy_mode' --include='*.py' backend/ 2>/dev/null

echo ""
echo "=== files containing v3_1 or v3_2 or v3_3 or v4 (sleeve mode names) ==="
grep -rln -E '"v3_1"|"v3_2"|"v3_3"|"v4"|strategy_mode.*v3|strategy_mode.*v4' --include='*.py' --include='*.yaml' --include='*.toml' backend/ 2>/dev/null

echo ""
echo "=== top 5 files by strategy_mode mentions ==="
grep -rl 'strategy_mode' --include='*.py' backend/ 2>/dev/null | while read f; do
  count=$(grep -c 'strategy_mode' "$f")
  echo "$count $f"
done | sort -rn | head -5

echo ""
echo "=== where strategy_mode appears (file:line context) ==="
grep -rn 'strategy_mode' --include='*.py' backend/ 2>/dev/null | head -60
