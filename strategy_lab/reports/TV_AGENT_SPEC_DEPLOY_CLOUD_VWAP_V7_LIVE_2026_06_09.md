# TV-AGENT SPEC — Deploy `cloud_vwap_hurstmp_v7` LIVE ($1) on Ireland (2026-06-09)

**Goal:** promote `poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7` to LIVE ($1/entry) on the
Ireland engine, alongside the existing live `..._grandparent_v8`. Minimal config change —
the sleeve already exists in the roster and runs shadow.

## Why this sleeve (selection evidence)
ETH-5m sleeve comparison, shadow OOS (May29→Jun09, production gates, fee 0.07 verified
identical to backtest accounting). `cloud_vwap_hurstmp_v7` is the single best candidate:
- **DSR 0.94** — the ONLY ETH-5m candidate whose OOS edge survives deflation for 25 trials.
- **Most outlier-robust:** only 10% of PnL from top-2 trades; $/tr stays **+0.333** (shadow $5)
  after removing the 2 biggest winners (vs hlcascade −0.152, tr200 +0.060 = contaminated).
- Bootstrap CI95 on $/tr excludes 0: [+0.06, +0.68] ($5 stake).
- **$1-stake economics (after $0.011/trade tx):** NET **+0.062/tr**, robust-NET +0.056/tr,
  ~58 trades/day → ~+$3.6/day. The edge per trade comfortably covers the tx cost.
- Diversifies from v8: ~50% of its slugs are its own (v8∩vwap = 307 of ~654).

Full analysis: `migration_2026_06_08/{find_diversifier,diversifier_robust,best_triple_proper}.py`,
`eth5m_full_period_proper_2026_06_09.py`. Sleeve def (gates): `g_tr_above_cloud(ETH)` +
`g_entry_vwap_in_band` + `g_hurst_mp_trend_with(ETH)`, BOTH, offset 60, spread 0.02.

## The change (Ireland only)
File `/etc/tv/tradingvenue.env` — append the sleeve_id to the live allowlist:
```
# before:
TV_POLY_SNIPER_V5_LIVE_ALLOWLIST=poly_sniper_v5_btc_15m_ema50_ema800_off600_down,poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8,shadow_scalp_exit_btc_5m_d3_v1,shadow_scalp_exit_btc_15m_d3_v1,shadow_scalp_momalign_btc_5m_v1
# after (add the last id):
TV_POLY_SNIPER_V5_LIVE_ALLOWLIST=...,shadow_scalp_momalign_btc_5m_v1,poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7
```
No other change. `TV_POLY_SNIPER_V5_LIVE_ENABLED=true` and
`TV_POLY_SNIPER_V5_LIVE_NOTIONAL_USD=1.0` already set; the sleeve has no notional override so
it inherits the $1 global stake (same as v8). Hard cap `SNIPER_V5_LIVE_MAX_NOTIONAL=$2` still applies.

### Apply
```bash
ssh vps_ireland
cp /etc/tv/tradingvenue.env /etc/tv/tradingvenue.env.bak_predeploy_cloudvwap_20260609
# edit the line, append the sleeve id
systemctl restart tv-engine
```

## Verify (within ~30 min)
- New live fires appear: `trading.events` where `sleeve_id='poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_LIVE'`
  and `kind='poly_updown_resolution'` (the `_LIVE` suffix = real money).
- `entry_qty`/`placed_size_usd` ≈ $1; `fill_method='live'`.
- Shadow twin (`..._cloud_vwap_hurstmp_v7`, no _LIVE) keeps running for A/B.

## Graduation / monitoring (judge by LIVE wallet, not shadow)
- Accrue **≥100 live fires**, then judge by the live wallet $/tr + bootstrap CI (NOT shadow).
- Expect live < shadow (wide-book execution gap — same as v8: shadow +0.27 → live ~breakeven).
  Pass bar: live $/tr CI95 lower bound > 0 (net of the $0.011 tx) over n≥100.
- Watch the per-host feed divergence + the cross-token wide-book rejects (documented for v8).

## Kill-switch / rollback
- Remove the sleeve_id from the allowlist + `systemctl restart tv-engine` (or restore the .bak).
- Reversible instantly; tiny notional ($1, max $2).

## Notes
- Real-money change on the TV-agent-owned Ireland engine — apply via this spec, not ad-hoc.
- Do NOT add a 3rd live sleeve yet: at $1 stake the $0.011 tx cost kills thin-edge/high-volume
  sleeves (e.g. `ema50_parent15m` net ≈ +0.0005/tr after outliers+tx). Only `cloud_vwap_v7`
  (and the existing v8) clear the cost robustly. Re-evaluate after ≥100 live fires.
