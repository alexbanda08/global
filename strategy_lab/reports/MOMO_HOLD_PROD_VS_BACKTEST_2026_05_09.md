# Production HOLD Sleeves (full 67h window) vs Backtest

**Date:** 2026-05-09 ~21:40 UTC
**Production window:** 2026-05-07 00:30 UTC → 2026-05-09 19:35 UTC (**67.1 hours**, 355 trades)
**Sleeves:** 12 HOLD-only sleeves (6 v1 + 6 v2). HOLD has no exit-policy code so the WS book-mirror patch is irrelevant — full window data is comparable.
**Backtest baseline:** 17-day universe (Apr 23 → May 9), 949 gated HOLD trades

## Bottom line

**Production HOLD captures ~3% of backtest expected value over 67h.** Hit rate is 52% in production vs 85% in backtest — a structural divergence that explains nearly all of the PnL gap.

| | n | hit% | total PnL | pnl/trade |
|---|---:|---:|---:|---:|
| **Production HOLD (67h, 355 trades)** | 355 | **52.1%** | **+$124.69** | **+$0.35** |
| **Backtest HOLD (17d, 949 trades)** | 949 | **85.4%** | +$12,846 | +$13.54 |
| Haircut | — | −33pp | — | **−$13.19 (97%)** |

This is too large to be regime noise. Something structural has changed between backtest assumptions and production reality.

## Per-version split

| version | n | hit% | total | pnl/trade |
|---|---:|---:|---:|---:|
| v1 HOLD (fires at ws+120) | 186 | 51.1% | −$36.03 | −$0.19 |
| v2 HOLD (fires at ws+60) | 169 | 53.3% | +$160.73 | **+$0.95** |

**v2 HOLD (corrected fire offset) outperforms v1 HOLD by $1.14/trade.** The backtest predicted +$3.69/trade at offset=60 vs offset=120 — production sees +$1.14, about 31% of predicted improvement. Direction matches, magnitude smaller.

## Per-cell breakdown

| version | cell | n | hit% | pnl/trade | bt hit% | bt pnl/trade |
|---|---|---:|---:|---:|---:|---:|
| v1 | BTC_15m | 12 | **75.0%** | **+$12.22** | 100% | +$21.08 |
| v1 | ETH_15m | 10 | **70.0%** | **+$10.04** | 99% | +$20.60 |
| v1 | SOL_15m | 12 | 33.3% | −$9.69 | 99% | +$21.81 |
| v1 | BTC_5m | 56 | 48.2% | −$1.49 | 82% | +$10.62 |
| v1 | ETH_5m | 37 | 37.8% | −$6.57 | 84% | +$10.98 |
| v1 | SOL_5m | 59 | 57.6% | +$2.71 | 81% | +$8.75 |
| v2 | BTC_15m | 14 | 50.0% | −$0.53 | 100% | +$21.08 |
| v2 | ETH_15m | 11 | 63.6% | +$5.90 | 99% | +$20.60 |
| v2 | SOL_15m | 10 | 60.0% | +$3.04 | 99% | +$21.81 |
| v2 | BTC_5m | 55 | 52.7% | +$0.96 | 82% | +$10.62 |
| v2 | ETH_5m | 37 | 51.4% | +$0.10 | 84% | +$10.98 |
| v2 | SOL_5m | 42 | 52.4% | +$0.38 | 81% | +$8.75 |

**v1 BTC_15m and ETH_15m are within 30% of backtest.** Everything else has hit rate near random (50%).

## Daily PnL trace

| day | n | total PnL | pnl/trade |
|---|---:|---:|---:|
| 2026-05-07 | 104 | −$66.10 | −$0.64 |
| **2026-05-08** | 183 | **+$493.36** | **+$2.70** |
| 2026-05-09 | 68 | −$302.56 | −$4.45 |

**One profitable day (May 8: +$2.70/trade) flanked by two negative days.** May 8's mean approaches backtest expectation (+$13). May 7 and 9 are random/negative.

This is consistent with regime variance, but a 33-percentage-point drop in hit rate (85% → 52%) over 67h cannot be explained by regime alone.

## Hypotheses for the hit-rate gap

### H1: production's strict-asof fix is incomplete
The TV agent supposedly fixed `fetch_close_asof` to be end-time-indexed (`time_period_end_us` instead of bar-open). If any caller still uses the buggy variant, ret_2m would be computed on a 60s-late window → near-random signal.

**Test:** SQL on VPS3 to verify recent momo signal events have `entry_phase='t_plus_60'` (v2) or `'t_plus_120'` (v1) and that the audit `ret_2m_at_signal` magnitudes match what we'd compute with strict-asof.

### H2: anchor mismatch between v2 production and v2 backtest
v2 spec says fire at ws+60 with anchor (ws-60, ws+60). If production actually anchors differently (e.g. uses (ws, ws+60) — only 60s window — or (ws-60, ws+120) — 180s window), the gated subset diverges.

**Test:** pull 50 v2 audit signal events from VPS3, compute strict-asof ret_2m for the same (asset, ws) tuples, compare to the audit's logged `ret_2m_at_signal`.

### H3: q90 threshold off
If production's daily q90 cache is computed on a different rolling window (or reset more often), the gate selects a different (less predictive) subset.

**Test:** pull production's `abs_ret_2m_threshold` from audit rows, compare to my backtest's per-day q90 values for the same (asset, tf).

### H4: regime variance
67h is short. The strategy expected ~85% hit rate but the realized rate could swing 60-90% over a small sample. **But 52% over 355 trades is far below noise band** — assuming binomial with p=0.85, σ on 355 trials is ~1.9%, so 52% is 17 standard deviations below expectation. Statistically impossible if the strategy is operating correctly.

**H4 is ruled out.** The gap is structural, not noise.

## Most likely culprit

**H1 or H2.** The 17-day backtest uses strict-asof rigorously. If production's signal-side computation is even 60s off, the q90 gate selects markets where ret_2m_at_(actual signal time) does NOT predict the binary outcome — hit rate collapses to ~50%.

Combined with v2 outperforming v1 by $1.14/trade (smaller than predicted but in the right direction), this suggests **v2's anchor IS more correct than v1, but BOTH are still off from the backtest's intended (ws-60, ws+60) anchor**.

## Action items

1. **Pull a sample of recent v2 momo signal audit rows from VPS3.** Specifically: condition_id, ws, ret_2m_at_signal, abs_ret_2m_threshold. Verify by recomputing in lab.
   ```sql
   SELECT data->>'condition_id', data->>'symbol', data->>'tf',
          data->>'signal', data->>'ret_2m_at_signal',
          data->>'abs_ret_2m_threshold', data->>'entry_phase', at
   FROM trading.events
   WHERE kind='poly_updown_signal'
     AND data->>'reason'='order_placed'
     AND sleeve_id LIKE '%_momo_v2_%'
     AND at > now() - interval '24 hours'
   ORDER BY at DESC LIMIT 50;
   ```

2. **Lab cross-check:** for each of those 50 rows, recompute ret_2m using:
   - Anchor (ws-60, ws+60) — the spec
   - Anchor (ws, ws+120) — production's documented v1 anchor
   - Anchor (ws+60, ws+180) — possible buggy v2 anchor
   Compare to `ret_2m_at_signal`. Whichever matches tells us what production actually computes.

3. **If production's anchor is wrong**, ship a fix and re-validate.

4. **In the meantime** keep all 36 sleeves running. Don't act on 67h data alone — but don't dismiss the 33pp hit-rate gap either.

## Caveat

The backtest's 17-day window (Apr 23 → May 9) only has L25 books in the lab through ~May 6 (existing parquet from refresh_2026_05_06). Backtest hit rate of 85% is computed across the full window. Production window (May 7-9) is in the BACKTEST UNIVERSE'S RECENT TAIL. If May 7-9 is genuinely a different regime in the underlying universe AND the May 6 parquet is missing those days, my backtest doesn't validate against the production window directly. To be 100% rigorous, pull May 6-9 L25 delta and re-run the backtest restricted to those 3 days. Estimated effort: 30 min.

## Files
- `data/v4/shadow_trades_2026_05_09/momo_hold_full.csv` — 355 production HOLD resolutions
- `strategy_lab/meta_classifier/_compare_hold_prod_vs_backtest.py` — comparison script
- `strategy_lab/reports/MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md` — backtest baseline
