#!/bin/bash
# VPS3 source-code presence check for the 9 new shadow sleeves.
# Run ON VPS3: `bash 02_grep_source_check.sh` from the tradingvenue repo root.

cd /opt/tradingvenue/backend || { echo "ERR: not in /opt/tradingvenue/backend"; exit 1; }

echo '======================================================================='
echo ' 9 specced shadow sleeve_ids — appearance in source'
echo '======================================================================='
for sid in \
    'shadow_poly_updown_ALL_5m_phase1_kelly' \
    'shadow_poly_updown_btc_5m_fade_momo_v2' \
    'shadow_poly_updown_btc_5m_fade_sniper' \
    'shadow_poly_updown_eth_15m_fade_sniper' \
    'shadow_poly_updown_sol_5m_fade_sniper' \
    'shadow_poly_updown_sol_5m_fade_momo_v2' \
    'shadow_poly_updown_sol_15m_fade_momo_v2' \
    'shadow_poly_updown_ALL_5m_S3_prewindow' \
    'shadow_poly_updown_ALL_15m_S4_prewindow'; do
    n=$(grep -rIc "$sid" app/ 2>/dev/null | grep -v ':0$' | wc -l)
    files=$(grep -rIl "$sid" app/ 2>/dev/null | head -3 | tr '\n' ' ')
    if [ "$n" -gt 0 ]; then
        printf "  ✓ %-55s in %d file(s): %s\n" "$sid" "$n" "$files"
    else
        printf "  ✗ %-55s NOT FOUND in source\n" "$sid"
    fi
done

echo
echo '======================================================================='
echo ' New features that must be published — appearance in source'
echo '======================================================================='
for feat in 'fair_up' 'fair_edge_bp' 'cvd_30s' 'cvd_60s' 'macd_hist' \
            'rvol_30_300' 'imb5' 'm1v_regime' 'm5v_regime' 'kelly_mult'; do
    n=$(grep -rIc "$feat" app/engine/ app/venues/polymarket/ 2>/dev/null | grep -v ':0$' | wc -l)
    if [ "$n" -gt 0 ]; then
        printf "  ✓ %-25s in %d file(s)\n" "$feat" "$n"
    else
        printf "  ✗ %-25s NOT FOUND in engine/polymarket source\n" "$feat"
    fi
done

echo
echo '======================================================================='
echo ' Sleeve-registration call sites (where do new sleeves get added?)'
echo '======================================================================='
grep -rn 'register_poly_updown\|_SHADOW_GATED_SLEEVES_SPEC\|SHADOW_SLEEVES_SPEC\|register_sleeve' \
    app/api/bots.py app/engine/ app/venues/polymarket/ 2>/dev/null | head -30

echo
echo '======================================================================='
echo ' Recent git log on engine + polymarket dirs (last 7 days)'
echo '======================================================================='
git log --since='7 days ago' --oneline -- app/engine/ app/venues/polymarket/ 2>/dev/null | head -20

echo
echo '======================================================================='
echo ' Env var check: shadow gates enabled?'
echo '======================================================================='
grep -h 'TV_POLY_SHADOW' /etc/tradingvenue/*.env /opt/tradingvenue/.env 2>/dev/null
echo

echo '======================================================================='
echo ' Running engine process — recently restarted?'
echo '======================================================================='
systemctl status tv-engine --no-pager 2>&1 | head -6
