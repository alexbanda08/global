#!/bin/bash
set -euo pipefail
cd /opt/tradingvenue
F=backend/app/controllers/polymarket_updown.py

echo "=== L1209-1330 (v3_2/v3_3 quantile branch — what makes it differ from v3?) ==="
sed -n '1209,1330p' $F

echo ""
echo "=== L1230-1500 (the actual signal computation using quantile) ==="
sed -n '1230,1500p' $F

echo ""
echo "=== env-flag helpers (v3_1_* v3_2_* gate flags) ==="
grep -n "v3_1_regime\|v3_1_live_direction\|v3_2_hour\|v3_2_macro_2of3\|v3_2_liq_quiet\|os.getenv.*V3_" $F | head -30

echo ""
echo "=== v3_2 / v3_3 gate stack post-quantile (looking for new gates) ==="
sed -n '1850,2050p' $F

echo ""
echo "=== check what makes v4 unique vs v3_1 (full grep for v4 alone) ==="
grep -n '"v4"' $F
echo ""
echo "=== check for v4-only branches (excluding v4 in tuple with others) ==="
grep -n 'strategy_mode\s*==\s*"v4"' $F

echo ""
echo "=== env vars on the deployed unit ==="
systemctl cat tradingvenue 2>/dev/null | grep -E "TV_POLY_(V3|V4)" | head -20 || true
cat /etc/tv/tv.env 2>/dev/null | grep -E "TV_POLY_(V3|V4)" | head -30 || true
