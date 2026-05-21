#!/bin/bash
set -euo pipefail
cd /opt/tradingvenue
F=backend/app/controllers/polymarket_updown.py

echo "=== L1040-1100 (V3 multi-horizon + v3_1/2/3/4 gate dispatch start) ==="
sed -n '1040,1100p' $F

echo ""
echo "=== L1130-1230 (quantile dispatch by mode — THE CORE OF THE GATE) ==="
sed -n '1130,1230p' $F

echo ""
echo "=== L1580-1620 (tf != 5m branches) ==="
sed -n '1580,1620p' $F

echo ""
echo "=== L1680-1880 (post-decision audit + extras) ==="
sed -n '1680,1880p' $F

echo ""
echo "=== test file: test_v3_per_asset_spread_and_v3_3.py — what does it assert? ==="
sed -n '1,80p' backend/tests/unit/test_v3_per_asset_spread_and_v3_3.py
