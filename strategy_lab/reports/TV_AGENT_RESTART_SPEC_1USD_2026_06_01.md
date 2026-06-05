# TV-Agent Spec — RESTART the 2 sniper sleeves LIVE @ $1 (2026-06-01)

**Operator decision:** restart to gather more live n (sample so far is tiny: btc n=9, eth n=16). Edge is NOT
expected to replicate the shadow PnL — this is a measured data-collection run at $1. Full diagnosis:
`TV_AGENT_SPEC_SLEEVE_DEBUG_FIX_2026_06_01.md`.

## Sleeves (already on the live allowlist, already $1 notional)
- `poly_sniper_v5_btc_15m_ema50_ema800_off600_down`
- `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8`
Current Ireland env (verified): `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST` = both; `TV_POLY_SNIPER_V5_LIVE_NOTIONAL_USD=1.0`;
`TV_POLY_SNIPER_V5_LIVE_ENABLED=false` (we stopped them). Env backup: `/etc/tv/tradingvenue.env.bak_20260601_233548`.

## Confirmed NOT broken (do not "fix" before restart)
- Fire timing is correct: `sleeve_fire_placed` events show `(fire_us − slot_start_us)/1e6 = 600` (btc) / `60` (eth).
- EMA gates match spec; Binance feed is healthy; fee/notional correct. **No code change is required to restart safely.**

## REQUIRED before restart (1 small fix)
**Fix the `fire_us` mislabel in the resolved event** so the dashboard/analytics stop showing false timing
(this is what produced the misleading "−$5.29 / 900s" reads). In `controllers/polymarket_sniper_v5.py`, the
resolution path (`_resolve_at_slot_end`, ~line 813; also ~959/1036) calls
`_build_event(sleeve, slot, slot_end_us, fr.offset_s, fr)` — it passes `slot_end_us` into the `fire_us`
parameter. Change so the resolved event keeps `fire_us` = the real fire time (persist `fr.fire_us` at
placement and reuse it) and add a separate field `resolved_at_us = slot_end_us`. Cosmetic but load-bearing
for trusting the live numbers.

## STRONGLY RECOMMENDED (the reason to restart at all)
Add **fill-divergence logging**: on each live fire, record BOTH in the resolved event —
- `live_fill_vwap` = the actual Polymarket taker fill (already logged as `fill_vwap`), and
- `model_fill_vwap` = what `_simulate_l25_walk` (the shadow/canonical model) would give for the SAME slug at
  the SAME fire_us.
This single comparison settles whether the shadow's higher WR is a fill-model artifact (prime suspect) or real.

## SAFETY (add a kill-switch)
Auto-suspend a sleeve (add to `_auto_suspended`) when, over a rolling 50 resolved LIVE fires,
`WR < de-vigged entry-implied prob` (i.e. it's not even beating the price it pays). Hard stop: cumulative
live PnL ≤ −$50 → suspend both. Surface a CRITICAL alert on suspend.

## RESTART (operator commands, Ireland)
```bash
# 1) (after the fire_us fix + instrumentation are deployed & tested)
# 2) re-enable live (notional already $1, allowlist already set):
sudo sed -i 's/^TV_POLY_SNIPER_V5_LIVE_ENABLED=false/TV_POLY_SNIPER_V5_LIVE_ENABLED=true/' /etc/tv/tradingvenue.env
grep TV_POLY_SNIPER_V5_LIVE /etc/tv/tradingvenue.env     # confirm: ENABLED=true, NOTIONAL_USD=1.0, allowlist=both
sudo systemctl restart tv-engine
sleep 6 && systemctl is-active tv-engine
```

## VERIFY after restart
1. Engine active; boot log clean.
2. First live fires show `(fire_us − slot_start_us)/1e6 == 600` (btc) / `60` (eth) — NOT 900/300.
3. `placed_size_usd = 1.0` on live placements.
4. Resolved events carry both `live_fill_vwap` and `model_fill_vwap`.
5. Kill-switch armed (rolling-50 WR-vs-implied + −$50 hard stop).

## DECISION GATE
After n≥100 live fires per sleeve: compare `live_fill_vwap` vs `model_fill_vwap`, and live WR vs entry-implied.
- live WR ≤ entry-implied AND live fills worse than model → confirmed priced-out / fill-artifact → retire.
- live WR > entry-implied at n≥100 → genuine edge → size up cautiously.

## MINIMAL VERSION (if the agent must restart NOW, before the fixes)
The two env lines (`LIVE_ENABLED=true` + restart) are sufficient to restart at $1 — the strategy fires
correctly. But WITHOUT the `fire_us` fix + instrumentation + kill-switch you'll be flying blind again on
misleading dashboards. Strongly prefer doing the 3 items above first.
