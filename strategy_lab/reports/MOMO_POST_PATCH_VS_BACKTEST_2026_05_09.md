# Post-WS-Patch Production vs Backtest — Last 12h Comparison

**Date:** 2026-05-09 ~21:40 UTC
**Window:** 2026-05-09 11:40 → 21:35 UTC (last 12h, ~10 hours since TV agent's WS book-mirror patch landed)
**Live trades:** 223 momo v1+v2 resolutions
**Compared against:** 17-day full-universe backtest in `MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md`

## Big-picture verdict

**The WS patch is working correctly.** Fire rates jumped where expected. But the last 12h is a **losing regime** in production — every sleeve including HOLD is negative on the day. So the comparison to backtest needs careful regime context.

## 1. WS-patch verification — fire rates jumped as predicted

| sleeve | pre-patch HEDGE fire% (7d) | **post-patch HEDGE fire% (12h)** | backtest prediction (5bp) |
|---|---:|---:|---:|
| v1 HEDGE | 18.4% | **55.6%** | 14% |
| v2 HEDGE | 23.0% | **70.9%** | 14% |

| sleeve | pre-patch SELL fire% (7d) | **post-patch SELL fire% (12h)** | backtest prediction (5bp) |
|---|---:|---:|---:|
| v1 SELL | 1.7% | **10.3%** | 14% |
| v2 SELL | 1.4% | **10.3%** | 14% |

**SELL is now firing close to backtest expectation** — the patch works for SELL. The 4% gap (10.3% vs 14%) is acceptable noise on this 12h sample.

**HEDGE is firing MUCH more than predicted (55-71% vs 14%).** Two plausible causes:
1. Production rev_bp threshold is lower than 5bp (could be 3bp, where backtest predicts 21% — still much less than 55-71%)
2. Production's HEDGE retry-on-tick pattern accumulates triggers — once rev_bp opens for any tick during the holding window, HEDGE fires. My backtest uses the SAME pattern, so this shouldn't differ.

The 55-71% rate is suspicious. Worth investigating production's `_maybe_hedge` `rev_bp` env var setting: `grep TV_POLY_HEDGE_REV_BP /etc/tv/tradingvenue.env` on VPS3.

## 2. PnL comparison — production vs backtest

| sleeve | n_prod | prod pnl/trade (12h) | bt pnl/trade (17d) | gap |
|---|---:|---:|---:|---:|
| v1 HOLD | 24 | **−$6.97** | +$13.54 | −$20.51 |
| v1 HEDGE | 45 | **−$5.71** | +$10.44 | −$16.15 |
| v1 SELL | 39 | **−$4.37** | +$10.42 | −$14.79 |
| v2 HOLD | 21 | **−$6.41** | +$13.54 | −$19.95 |
| v2 HEDGE | 55 | **−$3.21** | +$10.44 | −$13.65 |
| v2 SELL | 39 | **−$1.24** | +$10.42 | −$11.65 |

**Every sleeve negative on the 12h window** — this is a losing regime sample.

**Compared regime-to-regime:**
- 17-day full universe: HOLD wins (+$13.54), HEDGE/SELL trail (+$10.42)
- 12h post-patch: HEDGE/SELL beat HOLD by $1-3/trade

This is consistent with the earlier observation: HEDGE/SELL are amplifiers — they cut losses in losing regimes and cap upside in winning regimes. The 17-day average is dominated by winning days, so HOLD wins overall. The 12h window happens to land on a losing patch.

## 3. Per-cell breakdown (post-patch 12h)

| cell | n | HOLD pnl | HEDGE pnl | SELL pnl |
|---|---:|---:|---:|---:|
| v1 BTC_15m | small | +$26.54 (n=1) | −$2.41 (n=5) | −$2.47 (n=4) |
| v1 BTC_5m  | mid | −$25.02 (n=2) | −$11.62 (n=6) | −$9.60 (n=6) |
| v1 ETH_15m | small | +$21.29 (n=1) | −$2.72 (n=5) | +$5.26 (n=5) |
| v1 ETH_5m  | mid | −$10.72 (n=10) | −$8.08 (n=13) | −$9.51 (n=12) |
| v1 SOL_15m | small | −$25.98 (n=1) | −$6.95 (n=4) | −$7.07 (n=2) |
| v1 SOL_5m  | mid | −$3.55 (n=9) | −$2.37 (n=12) | −$0.11 (n=10) |
| v2 BTC_15m | small | +$0.38 (n=2) | +$5.69 (n=4) | +$12.88 (n=2) |
| v2 BTC_5m  | mid | −$3.00 (n=9) | −$4.64 (n=18) | −$2.23 (n=19) |
| v2 ETH_15m | small | (no fires) | −$1.23 (n=3) | (no fires) |
| v2 ETH_5m  | mid | −$13.36 (n=8) | −$5.86 (n=16) | −$5.24 (n=14) |
| v2 SOL_15m | tiny | (no fires) | −$2.28 (n=3) | (no fires) |
| v2 SOL_5m  | mid | −$0.78 (n=2) | −$1.03 (n=11) | **+$10.41 (n=4)** | 

15m sample sizes are tiny (1-5 trades), so per-cell deltas are noise. The 5m cells with n≥10 show:
- v1 ETH_5m: HOLD/HEDGE/SELL all ~equally bad (−$8 to −$11)
- v2 ETH_5m: HEDGE less bad than HOLD (−$5.86 vs −$13.36)
- v2 SOL_5m: SELL much better than HOLD/HEDGE (+$10.41 vs −$1.03 / −$0.78)

## 4. What the patch DID and DIDN'T fix

### ✅ Fixed
- **SELL fire rate**: 1.7% → 10.3% (was the worst gap, now within range)
- **HEDGE fire rate**: ~3× pre-patch (whether this is "fixed" or "now over-firing" is TBD — see #1)
- **Book-source determinism**: Per the patch, `_fetch_opposite_book` and `_fetch_own_book` now route through `book_mirror.get_with_freshness()` first, with REST as fallback

### ❓ Unclear
- **HEDGE over-firing**: 55-70% is way above backtest's 14% prediction. Either prod uses a tighter rev_bp threshold, or there's a behavior difference between live tick-loop and backtest tick-loop that needs investigation.
- **Win rate**: not split out here, but the negative PnL in 12h despite ~85% predicted hit rate suggests something off (or just a bad regime).

### Not addressed by patch (won't fix)
- **Strategy regime**: HOLD's positive EV is regime-conditional. Last 12h was a losing patch. Patch doesn't change strategy direction quality, just exit-fill quality.

## 5. Reconciliation with the 17-day backtest claim

The 17-day backtest concluded "HOLD wins, drop HEDGE/SELL sleeves" because over the full window HOLD's structural EV dominates. The 12h sample contradicts that — but the 12h sample is **±100% noise** (24 trades for v1 HOLD, +/-$25 per outcome). One bad day doesn't invalidate 17-day evidence.

However, the post-patch HEDGE/SELL behavior is different from pre-patch (fire rates 3× and 6× higher). The 17-day backtest assumed backtest-like exit-policy execution; production may now diverge if the new HEDGE rate is genuinely higher than the strategy expected.

**Critical question for next 24h**: do production HEDGE/SELL fire rates and PnL stabilize to backtest expectations, or does HEDGE continue to over-fire at 55-70%?

## 6. Recommendations

1. **Don't act on the 12h sample.** Sample size is too small. The 17-day backtest stands.
2. **Verify production rev_bp threshold**: `grep -E "TV_POLY_HEDGE_REV_BP|REV_BP_THRESHOLD" /opt/tradingvenue/backend/app/controllers/polymarket_updown.py /etc/tv/tradingvenue.env` on VPS3. If it's 3bp instead of 5bp, my backtest under-predicted fire rate. Re-run backtest with prod's actual threshold.
3. **Wait 48-72h post-patch** for fire rates to stabilize. If HEDGE still fires at 55-70%, run the deeper diagnostic (per-trade comparison: backtest predicted exit vs production actual exit at the same trade).
4. **Keep all 36 sleeves running** (18 v1 + 18 v2). Don't slim to HOLD-only based on 12h data alone.
5. **Re-run this comparison at +24h, +48h, +72h** to track regime stability.

## Files
- `data/v4/shadow_trades_2026_05_09/momo_post_patch_12h.csv` — 223 production resolutions
- `strategy_lab/meta_classifier/_compare_post_patch_vs_backtest.py` — comparison engine
- `strategy_lab/reports/MOMO_FULL_UNIVERSE_VALIDATION_2026_05_09.md` — backtest baseline (17-day window)
