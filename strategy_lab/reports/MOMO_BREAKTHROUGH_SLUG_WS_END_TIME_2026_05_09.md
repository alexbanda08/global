# BREAKTHROUGH — Slug-ws is END time, NOT bar-close. The Backtest Was Anchored Wrong.

**Date:** 2026-05-09 ~22:30 UTC
**Severity:** **CRITICAL — invalidates the 17-day backtest's universe filter and ret_2m anchor.**
**Question we set out to answer:** Why does production HOLD (+$0.35/trade, 52% hit) underperform backtest (+$13.54/trade, 85% hit) by 97%?
**What we found:** my backtest anchored ret_2m at the wrong absolute timestamps because I assumed slug-ws is the bar-close moment. **It's actually the resolution/end time.** Production fires roughly **240 seconds BEFORE** slug-ws for 5m markets, not 60-120 seconds AFTER.

## The discovery

### Step 1 — Audit timestamp doesn't match my "fire at ws+60" assumption

For sample row `poly_updown_sol_5m_momo_v2_HEDGE`, ws=`1778339700`:
- audit `at` = 2026-05-09 17:11:08 +02 = **15:11:08 UTC** = unix 1778339468
- slug ws = 1778339700 = **15:15:00 UTC**

**audit `at` is 232 seconds BEFORE slug-ws.** Yet production's stated dispatch is "now ∈ [ws+60, ws+125]" — i.e., AFTER ws.

This is impossible if ws is bar-close. The only reconciliation: **slug-ws is the END (resolution) of the 5m market**, and production fires at `ws - 240` = strike+60 = "t+60 of market lifetime".

```
                                      slug-ws
                                         │
   ──────────────┬──────────┬──────────┬─┘
            ws-300       ws-240      ws-180         ws (RESOLUTION)
            STRIKE      FIRE @ 15:11   ...
              t=0        t+60         t+120       t+300
```

### Step 2 — Anchor (ws-180, ws+120) reproduces production EXACTLY for one row

Different sample: `poly_updown_sol_5m_momo_v2_*` at ws=1778343300, production logged `ret_2m_at_signal = +0.001720`.

VPS3 binance-spot-ws SOL closes around that ws:
| ts_s | offset | close |
|---|---|---|
| 1778343000 | ws-300 | 93.08 |
| 1778343060 | ws-240 | 93.05 |
| 1778343120 | ws-180 | 93.06 |
| 1778343180 | ws-120 | 93.08 |
| 1778343240 | ws-60 | 93.07 |
| 1778343300 | ws | 93.15 |
| 1778343360 | ws+60 | 93.21 |
| 1778343420 | ws+120 | **93.22** |

Test pairs that give +0.001720:
- log(93.22 / 93.06) = log(close@(ws+120) / close@(ws-180)) = **+0.001719** ✓ (4-decimal match)
- log(93.21 / 93.05) = log(close@(ws+60) / close@(ws-240)) = +0.001721 ✓ (also matches)

**Both candidate anchors span 5 minutes** (300s). One of them must be the actual production semantic.

If slug-ws is END time and fire is at `ws-240`:
- (fire-60, fire+60) = (ws-300, ws-180) → log(93.06/93.08) = -0.000215 ✗ NO
- (fire+0, fire+300) = (ws-240, ws+60) → log(93.21/93.05) = +0.001721 ✓ YES

So one consistent interpretation: **production fires at ws-240, ret_2m = log(close@(fire+300) / close@fire) = log(close@(market_end-strike+60) / close@strike+60)**. That's a 5-minute return computed AT bar-close timing of the v2 dispatch boundary.

But it's labeled "ret_2m" so really 5min named 2min. Possibly a documentation/labeling drift in production code.

### Step 3 — Some rows can't be reproduced from spot klines AT ALL

Sample `poly_updown_sol_5m_momo_v2_HEDGE` at ws=1778339700 has logged `ret_2m_at_signal = -0.001620` (NEGATIVE).

VPS3 spot data at same window shows:
- BTC: 80240 → 80368 (UP)
- ETH: 2301 → 2306 (UP)
- SOL: 92.44 → 92.69 (UP)

**All three assets trended UP, but production logged a NEGATIVE ret_2m.** Sign disagreement that no anchor or asset choice can fix.

Possible explanations (need verification):
1. Production has a sign-flip bug
2. Production reads from a different feed (perp vs spot? Polymarket book mid?)
3. The audit timestamp `at` is not the actual fire time — there's a queue/retry mechanism that decouples audit-write-time from fire-time. The "ret_2m_at_signal" might be from an EARLIER attempt window.

### Step 4 — Why my backtest produced inflated +$13.54/trade

My backtest's flow:
1. Universe = 9618 markets resolved (BTC/ETH/SOL × 5m/15m)
2. For each market with slug-ws=`X`, compute `ret_2m = log(close@(X+60) / close@(X-60))`
3. Apply q90 gate per (asset, tf, day) — rolling 14d
4. Simulate HOLD/HEDGE/SELL based on signal direction vs outcome
5. Outcome was taken from production's resolution table

**The bug:** my "ret_2m" was the price move during the 2 minutes RIGHT AT MARKET RESOLUTION (since slug-ws is the END). That's the post-market-close move which has obvious lookahead leakage:
- Just before market resolves, the binary outcome is essentially settled
- Asset price in those final 2 minutes is highly correlated with the resolution outcome
- My q90 gate selected markets where the asset moved a lot RIGHT BEFORE RESOLUTION
- Those markets' resolution direction is trivially predictable from that move
- **85% backtest hit rate is largely artifactual leakage**, not real momo alpha

This explains why production sees ~52% hit rate (no leakage available — production fires WAY before resolution): **production's environment doesn't have access to the leaked information my backtest exploited**.

### Step 5 — What's the REAL production anchor

Need more samples + brute force. From the one row that matched cleanly (ws=1778343300):
- Anchor (ws-240, ws+60) gave +17.21bp matching production's +17.20bp
- But ws=1778339700 row can't be matched by any spot kline anchor

So either:
- The first match was coincidental and production uses something more complex
- Or production has bugs that intermittently produce unparseable values

**Cannot conclude the anchor formula from 2 samples.** Need to brute-force ALL 300 audit rows against VPS3 binance-spot-ws klines (which is the data production reads), find the formula that maximizes matches.

## Implications

### 1. The 17-day backtest's +$13.54/trade is bogus

The q90 universe filter selected markets via post-resolution lookahead. Re-running with the correct anchor will likely show:
- Real top-decile hit rate: 50-70% (not 85%)
- Real PnL/trade: probably $-2 to +$5 (not +$13.54)
- HEDGE/SELL might actually beat HOLD (the 7-day exit-policy exploration was on a NON-leaky window so its results may have been correct)

### 2. The "HOLD wins, drop HEDGE/SELL" recommendation in the prior report is WRONG

That recommendation was based on the leaky backtest. Once the anchor is fixed, HEDGE_3bp / STOP_HEDGE_0.5x might actually be the best choices — matching the 7-day exit-policy exploration's earlier finding that I dismissed as "small-sample regime artifact".

### 3. Production might be working correctly

The 52% hit rate on production HOLD is consistent with a pure-momentum strategy at q90 |ret_2m| gate WITHOUT lookahead. Real momentum gates typically deliver 55-65% hit rate. Production's number is below that, suggesting either:
- The q90 gate isn't selecting correctly (maybe uses production's anchor which has no real signal at fire time)
- OR momentum isn't a great signal in the current regime

### 4. The "97% haircut from backtest to live" was the BACKTEST'S overstatement

Not a production execution problem. The strategy might be near-flat in reality.

## What needs to happen next

### Phase 1 (1 hour) — confirm slug-ws semantics
1. Pull 50 audit `at` timestamps for 5m vs 15m markets
2. Compute `at - ws` for each
3. Verify: 5m fires at ws-240 ± 5s, 15m fires at ws-840 ± 5s (i.e., t+60 of market lifetime)
4. If consistent, slug-ws IS the END time

### Phase 2 (2 hours) — find the actual production anchor
1. Pull VPS3 `binance-spot-ws` 1MIN klines for last 7 days × BTC/ETH/SOL (~30K rows, ~1 MB)
2. For each of 300 production audit rows, compute log(close@(t1)/close@(t0)) for ALL 17×17 anchor combinations
3. Find the (off0, off1) pair minimizing residual across the full 300-row sample
4. If residual < 1e-6 on >90% of rows, that's the anchor

### Phase 3 (1 hour) — rebuild backtest universe with correct anchor
1. Update `momo_full_universe_validation.py` to use the discovered anchor
2. Re-run on the 17-day window
3. Compare new backtest results to production HOLD's +$0.35/trade
4. If gap < 30%, backtest is now reliable. If still big gap, dig further.

### Phase 4 (1 hour) — re-evaluate exit-policy variants
1. Run the 15-variant sweep with correct anchor
2. The "HOLD wins" conclusion may flip
3. If HEDGE_3bp or STOP_HEDGE_0.5x wins, write deploy spec for momo_v3 sleeves with that variant

## Action items today

1. **Don't ship anything new** until Phase 1-3 complete.
2. **Don't slim production sleeves** based on the broken backtest's "HOLD wins" claim.
3. **Continue collecting production data** — every additional day of HOLD/HEDGE/SELL data on the existing 36 sleeves makes the eventual production-vs-corrected-backtest comparison stronger.

## Files
- `data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv` — 300 audit rows
- `strategy_lab/meta_classifier/_diagnose_anchor.py`, `_brute_force_anchor.py` — diagnostic scripts
- `strategy_lab/reports/MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md` — **NOW INVALIDATED** by this finding
- `strategy_lab/reports/MOMO_HOLD_PROD_VS_BACKTEST_2026_05_09.md`, `MOMO_ANCHOR_DIAGNOSIS_2026_05_09.md` — earlier diagnostic steps that led here
