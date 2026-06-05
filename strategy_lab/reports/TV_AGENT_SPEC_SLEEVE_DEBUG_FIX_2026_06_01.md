# TV-Agent Spec — sniper-v5 live-loss debug: fixes + restart protocol (2026-06-01)

**Audience:** the tradingvenue engine agent (Ireland VPS, `/opt/tradingvenue`).
**Supersedes** `SLEEVE_DEBUG_ROOTCAUSE_2026_06_01.md` (which wrongly blamed a fire-timing bug) and the
sub-agent's `SLEEVE_DEBUG_LIVE_VS_SHADOW_*.md` (which wrongly said "no live fills"). Both were wrong;
this is the verified picture.

## Sleeves in scope
- `poly_sniper_v5_btc_15m_ema50_ema800_off600_down` (LIVE id `..._LIVE`)
- `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` (LIVE id `..._LIVE`)
Both currently STOPPED (`TV_POLY_SNIPER_V5_LIVE_ENABLED=false`, env backed up `.bak_20260601_233548`).

## Verified facts (evidence)
- Live IS losing (real Polymarket fills, `$1` notional): btc_LIVE n=9 WR 55.6% **−$3.39**; eth_LIVE n=16 WR
  50% **−$5.01** (from `trading.events` kind `poly_updown_resolution`, sleeve_id ending `_LIVE`, `pnl_usd`).
- **Fire timing is CORRECT.** `sleeve_fire_placed` events show `(fire_us − slot_start_us)/1e6 = 600` (btc) /
  `60` (eth). The strategy fires at the configured offset. (Loop `_fire_at_offset` line 145:
  `fire_us = slot.slot_start_us + offset_s*1e6` — correct.)
- VPS3 SHADOW fires off=600 too and shows WR 80%/72% (n=109/173) at median entry ~0.81.
- Live off=600 fills span **0.26–0.97** (incl. underdog DOWN @ 0.26) → WR ~base rate → net negative.

## Root cause = NOT a code bug in firing. It is (a) a logging defect + (b) the strategy being priced-out at real fills.

### (a) Logging defect — `fire_us` mislabeled in the RESOLVED event (REAL bug, cosmetic)
`controllers/polymarket_sniper_v5.py` resolution path (`_resolve_at_slot_end` → ~line 813, also ~959/1036)
calls `_build_event(sleeve, slot, slot_end_us, fr.offset_s, fr)` — it passes **`slot_end_us` into the
`fire_us` parameter** of `_build_event`. So `sleeve_fire_resolved` rows record `fire_us = slot_end`
(= slot_start + window), NOT the real fire time. This makes `(fire_us − slot_start)/1e6` read 900/300
(slot end) and **falsely looks like a timing bug**. It also corrupts any downstream PnL/timing analytics.
**FIX:** in the resolved event, keep `fire_us` = the real fire time (store `fr.fire_us` on the FireResult at
placement and reuse it), and add a SEPARATE field `resolved_at_us` (= slot_end_us) for the resolution
timestamp. Do not overload `fire_us`.

### (b) The strategy is priced-out at live fills (NOT fixable by code)
The DOWN gate is `close < ema_50 AND close < ema_800` where ema_50/ema_800 are **50-second / 800-second**
EMAs on Binance 1s — i.e. "price is in a short-term dip." But the slug resolves on **price vs the strike**
(the price 600s earlier). A short-term dip is only weakly related to "below strike," so the signal fires
DOWN even when DOWN is the UNFAVORED side (the 0.26 fills). At real off=600 fills the strategy transacts
across the whole price range and wins ≈ the base rate → net negative after fees. The shadow/backtest's
80%/72% WR @ ~0.81 came from the **canonical-L25 walk fill model being more favorable than the live taker
fill** (± small-sample: live n=9/16, gap only p≈0.06–0.09). This matches `EFFICIENT_MARKET_FINDING_2026_05_28`:
no reproducible directional edge; backtest/shadow hid it behind an optimistic fill model.

## What is NOT wrong (ruled out — don't chase)
- Fire timing (off=600 confirmed). EMA gates (match spec, all true). Binance feed (healthy live WS, seeded,
  no stale/gap). Fee/notional ($1, taker at ask, latency 0).

## RESTART SPEC (honest)
**Do NOT restart these expecting the shadow's +27%/+15% — the live truth is breakeven-to-negative.** Restart
ONLY to gather decisive data on the fill gap, with these guardrails:

1. **Fix (a)** — the `fire_us` resolved-event mislabel (above). Required so analytics are trustworthy.
2. **Add fill-divergence instrumentation.** On every live fire, log BOTH:
   - `live_fill_vwap` (the actual Polymarket taker fill), and
   - `model_fill_vwap` (what `_simulate_l25_walk` / the canonical-L25 model would have given for the same
     slug at the same fire_us).
   Persist both in the resolved event. This DIRECTLY measures whether the shadow fill model is optimistic
   (the prime suspect for the 80%→55% WR gap). One number settles "real edge vs fill artifact."
3. **Re-enable LIVE** at `$1` notional only: `TV_POLY_SNIPER_V5_LIVE_ENABLED=true`, restart tv-engine.
4. **Kill-switch:** auto-suspend the sleeve if, over a rolling 50 resolved live fires, `WR < de-vigged
   entry-implied prob` (i.e. it isn't even beating the price it pays). Also keep a hard −$50 cumulative stop.
5. **Decision gate:** after n≥100 live fires, compare `live_fill_vwap` vs `model_fill_vwap` and live WR vs
   entry-implied. If live WR ≤ entry-implied and live fills are systematically worse than model → confirmed
   priced-out / fill-artifact → retire the directional sleeves. If live WR > entry-implied with n≥100 →
   genuine edge, size up cautiously.

## Restart commands (operator, after fixes deployed)
```
# on Ireland, after the code fixes are deployed + tested:
sudo sed -i 's/^TV_POLY_SNIPER_V5_LIVE_ENABLED=false/TV_POLY_SNIPER_V5_LIVE_ENABLED=true/' /etc/tv/tradingvenue.env
sudo systemctl restart tv-engine
# verify: resolved events now show (fire_us - slot_start)/1e6 == 600/60, and live_fill_vwap + model_fill_vwap both logged.
```

## Bottom line
There is no "make it win" bug fix — the directional edge is a fill-model artifact, and the live wallet is
the truth. The only real code bug is the cosmetic `fire_us` mislabel. Restart only to MEASURE the fill gap
(instrumentation + kill-switch), at $1, not to chase the shadow PnL.
