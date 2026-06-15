# Range-Filter gate UP-bias audit + fleet scan (2026-06-08)

**Trigger:** `poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8` (spec `direction="BOTH"`, trend-follower) bet 80% UP over
Jun 1–8 while BTC fell −13.7% (1h-trend UP only 33% of the time). Suspected lagv2-style directional bias.

## Verdict: NOT a code bug — the Range Filter INDICATOR lags in reversals
Gates are symmetric (`sniper_v5_gates.py`): `g_rf_with`:353, `g_1h_rf_with`:1879, `g_ribbon_agrees`:573,
`g_imb5_strong_with`:2058 — each picks direction correctly, no UP-default fallback (returns False on None).
Root cause = `range_filter_*.py` `rf_dir` hold rule: `>prev→+1; <prev→−1; else HOLD prior`. After a long uptrend,
`rf_dir` stays +1 and flips DOWN only on a threshold crossing (many bars). During the Jun reversal the BTC RF was
UP 77% of the time vs true 1h-trend UP 33%. Lagging-indicator bullish-hold bias, not a sign error.

## Fleet scan (signal-field bet direction, l25_walk fills, Jun1–8; trend from klines Jun1–4)
BTC trend_up=33%, ETH=38.5%, SOL=36.5%.
| sleeve | asset | up_frac | trend_up | mismatch | gate | note |
|---|---|---|---|---|---|---|
| **btc_5m_l_1hrf_imb5_rf_v8** | BTC | 0.77 | 0.33 | **+0.44** | g_1h_rf_with+g_rf_with | ⚠️ ACTIVE 1331 fills |
| btc_5m_l_1hrf_imb5_ribbon_v8 | BTC | 0.77 | 0.33 | +0.44 | g_1h_rf_with+g_ribbon | deprecated 2026-06-08 |
| sol_15m hod_eu_*_rf_tr_* (×3) | SOL | 0.51–0.67 | 0.37 | +0.14 to +0.30 | g_rf_with | mild (small n) |
| sol_5m_j_2asset_*_rf_ema200_v8 | SOL | 0.43 | 0.37 | +0.06 | g_rf_with | mild; also negative $/tr recently |
| eth_5m_cloud_ribbon_* | ETH | 0.29–0.49 | 0.39 | ±0.10 | g_ribbon_agrees | ✅ tracks (ribbon faster than RF) |
| controls (no RF): btc parent15m_slope | BTC | 0.47 | 0.33 | +0.14 | none | ✅ far better than RF |
| controls: eth hurst/trstack, sol f7 | ETH/SOL | 0.34–0.45 | 0.37–0.39 | ±0.06 | none | ✅ track trend |
(DOWN-only sleeves ema50_ema800_off600_down / ema200_mpskew_rf_off600_down show 0% UP by design — not a bug.)

## Conclusions
- **RF-gate-specific, worst on BTC.** The two BTC `imb5` sleeves (+0.44) are the offenders; SOL RF sleeves mildly
  affected; ribbon (ETH) + non-RF sleeves track the trend fine. NOT fleet-wide.
- **`btc_5m_l_1hrf_imb5_rf_v8` is still ACTIVE** and betting UP into downtrends → deprecate (the ribbon twin already
  was). This vindicates excluding the imb5 sleeves from the deploy candidates (they were on the STRATEGY_MAP trap list).
- **The RF "edge" is regime-fragile**: fine in trends, bleeds on reversals. Any RF sleeve needs a faster-trend
  confirmation gate (e.g. parent-15m-slope) or RF must be replaced with a faster-flipping trend signal.

## Recommended actions
1. **Deprecate `poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8`** (active, +0.44 mismatch, betting UP in a downtrend).
2. **Add a faster-trend confirmation gate** to all `g_rf_with`/`g_1h_rf_with` sleeves (require parent-15m-slope OR
   ribbon to agree with RF) — so a stale RF UP-hold can't fire UP when faster signals say DOWN. OR replace the RF
   hold rule with a faster flip.
3. **Re-audit RF sleeves on a TRENDING window** to confirm the edge exists when RF isn't lagging (separate the
   indicator-lag failure from a true no-edge).
4. Judge on the dashboard dedup metric (`[[project_sleeve_pnl_metric]]`).
