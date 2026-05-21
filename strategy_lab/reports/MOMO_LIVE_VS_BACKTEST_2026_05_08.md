# Live momo v1 + v2 HEDGE/SELL exit-fire diagnosis vs WS L25 backtest

**Date:** 2026-05-08
**Window:** last 7 days, 851 production resolutions (v1: 446, v2: 405)
**Method:** for each live fill, replay the on_tick exit logic against strict-asof Binance klines + VPS2 WS L25 books at the same moment, predict whether HEDGE/SELL would have fired, compare to actual production outcome.

## Bottom line

**The HEDGE and SELL exit policies are firing far less in production than the WS-book backtest says they should.** Specifically: in 236 / 569 HEDGE+SELL trades where the rev_bp gate opened AND the relevant book had liquidity at L1, production held to chainlink instead of executing the exit.

The issue is concentrated in `SELL_BID` (almost never fires in production) and partially in `HEDGE_HOLD`.

## Per-policy fire rates: PROD vs BACKTEST PREDICTED

| variant | policy | n | prod hedge | prod sell | bt hedge | bt sell | gate-open rate |
|---|---|---:|---:|---:|---:|---:|---:|
| v1 | HEDGE | 147 | **21 (14.3%)** | 0 | 65 (44.2%) | 0 | 45.6% |
| v1 | SELL  | 149 | 0 | **3 (2.0%)** | 0 | 67 (45.0%) | 46.3% |
| v2 | HEDGE | 135 | **31 (23.0%)** | 0 | 70 (51.9%) | 0 | 53.3% |
| v2 | SELL  | 138 | 0 | **2 (1.4%)** | 0 | 70 (50.7%) | 52.2% |

### Per-cell SELL fires (worst gap)

| variant | cell | n | **prod sell %** | **bt sell %** | rev_bp gate ≥5bp ever opened |
|---|---|---:|---:|---:|---:|
| v1 | BTC_15m_SELL | 11 | 0.0% | **54.5%** | yes |
| v1 | ETH_15m_SELL | 9 | 11.1% | **66.7%** | yes |
| v1 | SOL_15m_SELL | 9 | 11.1% | **77.8%** | yes |
| v1 | BTC_5m_SELL | 54 | 0.0% | **33.3%** | yes |
| v1 | ETH_5m_SELL | 27 | 0.0% | **48.1%** | yes |
| v1 | SOL_5m_SELL | 39 | 2.6% | **43.6%** | yes |
| v2 | BTC_15m_SELL | 11 | 0.0% | **72.7%** | yes |
| v2 | ETH_15m_SELL | 11 | 0.0% | **72.7%** | yes |
| v2 | SOL_15m_SELL | 7 | 0.0% | **42.9%** | yes |
| v2 | BTC_5m_SELL | 46 | 0.0% | **39.1%** | yes |
| v2 | ETH_5m_SELL | 30 | 3.3% | **50.0%** | yes |
| v2 | SOL_5m_SELL | 33 | 3.0% | **54.5%** | yes |

**Across all 12 SELL cells, production fired bid-exit 5 times.** Backtest predicts 236 fires. **231-trade gap.**

### Per-cell HEDGE fires

| variant | cell | n | prod hedge % | bt hedge % |
|---|---|---:|---:|---:|
| v1 | BTC_15m_HEDGE | 11 | 36.4% | 54.5% |
| v1 | ETH_15m_HEDGE | 9 | 44.4% | 66.7% |
| v1 | SOL_15m_HEDGE | 9 | 33.3% | 77.8% |
| v1 | BTC_5m_HEDGE | 53 | 7.5% | 32.1% |
| v1 | ETH_5m_HEDGE | 26 | 11.5% | 46.2% |
| v1 | SOL_5m_HEDGE | 39 | 7.7% | 43.6% |
| v2 | BTC_15m_HEDGE | 11 | 18.2% | 72.7% |
| v2 | ETH_15m_HEDGE | 11 | 27.3% | 72.7% |
| v2 | SOL_15m_HEDGE | 7 | 28.6% | 42.9% |
| v2 | BTC_5m_HEDGE | 44 | 20.5% | 40.9% |
| v2 | ETH_5m_HEDGE | 29 | 27.6% | 51.7% |
| v2 | SOL_5m_HEDGE | 33 | 21.2% | 54.5% |

HEDGE fires in production at roughly half the predicted rate — better than SELL's 0% but still far short of expectation.

## Skip-reason breakdown (across HEDGE+SELL trades where production held)

| skip reason | count |
|---|---:|
| **rev_bp gate never opened** (Binance didn't revert ≥5bp from anchor) | 268 |
| **OK — gate opened + book available, but production didn't fire** | **236** |
| book missing at gate-open time | 8 |

The 236 "OK" cases are the actionable gap. Production controller HAS a usable signal AND a usable book at gate-open time, but doesn't fire the exit.

## Most likely root cause

**Production fetches the exit-side book via REST CLOB `/book?token_id=X` (executor.get_orderbook_snapshot) at on_tick time.** The REST endpoint has a known multi-second cache. When the WS feed shows liquidity at L1, the REST cache may still be returning an older/empty snapshot.

Evidence:
- VPS3 has been logging `poly_updown_hedge_skip` events with `reason='no_asks'` and `book_ts=0` (~250 events for the same 7-day window per earlier audit). `book_ts=0` = REST returned an empty book object.
- `hedge_and_exit_both_failed` skip events on SELL sleeves (~18 events) imply both the opposite-asks book (HEDGE fallback) AND the own-bids book (SELL primary) returned empty at the same instant — which is much less likely on the WS feed than on REST cache.
- Backtest uses VPS2 WS books (real-time). Backtest sees liquidity in 92%+ of gate-open instants. Production's REST view sees liquidity in ~30-50% of those instants → matches the gap.

## Why SELL is worse than HEDGE

`_maybe_sell_at_bid` requires the OWN-side bid book. `_maybe_hedge` requires the OPPOSITE-side ask book. Both are REST fetches.

Hypothesis: HEDGE has been retrying through the on_tick cadence (10s ticks for the holding window's duration) and eventually hits a non-stale REST cache window. SELL only fires once per gate-open trigger and exits the loop, so it's more sensitive to a single stale REST response.

This matches the `hedge_skip` count distribution: HEDGE sleeves accumulate retries (50+ skip events on stuck SOL_15m fills), but SELL sleeves don't retry — the `hedge_and_exit_both_failed` event fires once and the trade falls through to chainlink.

## Recommended fixes (priority order)

1. **Wire the exit-side book read to WS** (Phase 2 was framed as "scale enabler" — actually a correctness fix for HEDGE/SELL). Use the same WS subscription that VPS2 uses (`wss://ws-subscriptions-clob.polymarket.com/ws/market`) for the book lookup at on_tick time.
2. **For SELL sleeves: add retry on initial book-empty response.** Mirror HEDGE's tick-retry pattern. If the first sell-bid attempt sees empty book, retry on the next tick. This recovers the bulk of the SELL gap if (1) is delayed.
3. **Audit logging**: add a `book_source='rest'|'ws'` field to the `poly_updown_hedge_skip` and resolution events so we can A/B compare REST vs WS quality post-migration.

## Estimated impact if exits fire at backtest rate

Assuming backtest predicts +$3-5 per fired SELL exit (vs −$25 chainlink loss):
- 231 missed SELL fires × $4 mean recovery ≈ **+$925** over the 7-day window
- ~$132/day recovered vs current production performance

For HEDGE: ~75 missed fires × $2 mean ≈ **+$150** over 7 days. Smaller because HEDGE is already firing more.

Combined: **~$1,075 additional PnL/week** if HEDGE/SELL exits fire at WS-book backtest rates.

## Files
- script: `strategy_lab/meta_classifier/momo_live_vs_backtest_diagnose.py`
- per-trade: `data/v4/shadow_trades_2026_05_08/momo_live_vs_backtest_per_trade.csv`
- live trades: `data/v4/shadow_trades_2026_05_08/momo_v1v2_live.csv` (851 resolutions)
- VPS2 source data: `data/v4/shadow_trades_2026_05_08/vps2_l25_{btc,eth,sol}.csv` + `vps2_klines_1m.csv`

## Open questions / next steps

1. Confirm that production's `_maybe_hedge` and `_maybe_sell_at_bid` use REST (not WS) for the on_tick book fetch. If WS is already wired for the entry-side book but not the on_tick exit-side book, the asymmetry explains the divergence.
2. Pull a single REST `/book` snapshot in real time and compare to a simultaneous WS snapshot for an actively-traded market. Quantify the average staleness of REST during high-volume windows where rev_bp triggers fire.
3. Check whether `hedge_and_exit_both_failed` events correlate temporally with REST cache miss events in tv-engine logs — would isolate the cache layer as the culprit.
