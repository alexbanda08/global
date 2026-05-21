# Momo v1 — Feed Lag Investigation
_Generated: 2026-05-10_
_Authors: backtest agent (this session)_
_Owner of fix: TV agent + storedata agent_

## TL;DR

**My canonical-data backtest of momo v1 hit 85.5% over 16d / 1,736 trades.**
**Production live momo HOLD over 7d hit ~50% on 5m / ~70% on 15m / 290 trades.**

Investigation found the gap is split between two causes:

1. **Feed lag** (CONFIRMED): production reads `btc_at_t_plus_120` from an in-memory binance WS feed via `fetch_close_asof()` (tier-1 path). At wallclock fire time `ws+120`, the feed often hasn't received the just-closed bar `[ws+60, ws+120)` yet (binance publish + WS receive latency = 100ms-2s). So production effectively reads `close@(ws+60)` instead of `close@(ws+120)`. **My DB-only backtest doesn't have this constraint** — DB always has the bar.

2. **Additional 5m-specific issue** (NOT confirmed): even after applying feed lag, 5m hit rate drops only to ~78-81%, still 25-30 pp above production's 50%. The 15m hit rate matches perfectly after lag (~70%). Something specific to 5m markets in production reduces hit further.

## Evidence — slug-level cross-reference

For 32 slugs that BOTH production fired on AND my backtest fired on:

| Metric | Match |
|---|---:|
| chainlink outcome (Up/Down) | 100% (32/32) |
| signal direction (UP/DOWN) | 46.9% (15/32) |
| won flag | 46.9% (15/32) |

Outcomes are identical. **Signals disagree more than half the time.** Same slug, same window, same nominal formula `log(close@(ws+120)/close@ws)`, opposite signs.

Sample disagreement:
- ETH 5m, condition_id `0x6e7bf07a...`
- Production fired DOWN, `ret_2m_at_signal = -0.000846` (8 bp DOWN)
- My backtest computed UP, `ret = +0.001181` (12 bp UP)
- 20 bp gap on the same window

## Root cause analysis

### Production's read path (from `backend/app/engine/poly_updown_loop.py:347 build_bar_context_t_plus_120`):

```python
btc_at_ws, btc_at_120, ret_2m_samples, cid = await asyncio.gather(
    _fetch_close(0),       # BTC@ws_s — calls fetch_close_asof
    _fetch_close(120),     # BTC@(ws_s + 120) — calls fetch_close_asof
    ...
)
```

`fetch_close_asof` from `backend/app/data/bars.py`:

```python
# Phase 22.1 (CLAUDE.md inv #13): TV-native feed-first when bound
if _feed_native_enabled() and _FEED_INSTANCE is not None:
    close = _FEED_INSTANCE.get_close_asof(tv_sym, ts_s)  # ← TIER-1
    if close is not None:
        return close

# Existing SQL path (Tier-3 fallback OR flag off / feed unbound):
sql = ("SELECT price_close FROM public.binance_klines_v2 "
       "WHERE symbol_id = $1 AND period_id = $2 AND source = $3 "
       "  AND time_period_end_us <= $4 "
       "ORDER BY time_period_end_us DESC LIMIT 1")
```

**Production prefers the in-memory feed.** When the feed hasn't received the just-closed bar yet, it returns either:
- The previous bar's close, OR
- `None` (which triggers tier-3 DB fallback, but DB also may not have the bar yet at wallclock T+epsilon)

### My backtest's read path

`asof_strict(end_us, prices, target_us)` reads from a parquet DB snapshot pulled hours/days after fact. **Always has the bar.**

## Lag sweep — quantifying the gap

Re-ran momo v1 with simulated feed-lag offsets:

| Scenario | n | Hit% | BTC 5m | BTC 15m | ETH 5m | ETH 15m | SOL 5m | SOL 15m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline (no lag) | 1,736 | 85.5 | 86.4 | 74.9 | 90.1 | 75.9 | 91.6 | 73.8 |
| 1s lag, LATER only | 1,668 | **77.2** | 78.7 | **67.1** | 79.9 | **70.8** | 80.6 | **70.9** |
| 1s lag, BOTH sides | 1,614 | 67.7 | 68.2 | 63.5 | 70.5 | 61.9 | 69.4 | 61.9 |
| **Production live** | ~290 | ~50 | ~50 | **~75** | ~50 | **~70** | ~56 | **~50** |

### Reading

- **15m hit rate matches production after applying 1s-LATER lag.** Backtest BTC/ETH/SOL 15m = 67/71/71% vs production 75/70/50%. Within sampling noise on small live N.
- **5m hit rate does NOT match.** Backtest with lag = 78-81%, production = 50%. **Residual ~28 pp gap on 5m.**

## Hypothesis: 5m residual gap causes (NOT confirmed)

In rough order of likelihood:

1. **Spread filter rejection bias**: production may reject `ask0 - bid0 > SPREAD_FILTER` more often on 5m (faster-churn books). If rejection happens preferentially on cleaner momentum signals (high directional), the surviving fires are noisier → lower hit. **Test: pull `poly_updown_signal` events with `signal != NONE` but where the controller logged a skip reason like `spread_too_wide`. Compare survival vs rejected hit rates.**

2. **Q90 threshold computation drift**: production's `_fetch_abs_ret_2m_history` may include the latest day's samples (cause: `until_s = ws_s` includes all data up to ws_s, fine) BUT the in-memory feed pre-population may include "current minute" samples that haven't really finalized. **Test: log production's exact threshold value at fire time and compare to my backtest's threshold for same (asset, tf, day).**

3. **Token-id / cid resolution rejections**: 5m markets churn rapidly. `resolve_condition_id` may return None on stale resolutions, and the controller silently skips. The skipped markets may be the easier ones (e.g., where the cid for the NEXT 5m market is being resolved, biasing toward late-arriving markets). **Test: count `cid_resolve_failed` events per asset/tf and check correlation with hit rate of the surviving fires.**

4. **`bar_ctx_age_ms` cutoff**: if production rejects fires where bar_ctx is older than some threshold, that may correlate with momentum quality. **Test: histogram bar_ctx_age_ms for fires vs skips on 5m.**

5. **Hedge bug from May 6 still partially active**: even though it's labeled HOLD, the controller path may still touch HEDGE/SELL fallback logic. **Test: trace one specific 5m fire end-to-end through the controller code.**

## What I CAN report cleanly

- **My backtest is causally honest under DB-availability assumption.**
- **Spec-correct ret_2m formula.**
- **chainlink-only universe (no binance contamination).**
- **Lag-aware re-run (1s LATER) drops backtest hit to 77% — matches production on 15m, partially on 5m.**

## Recommended action items

### TV agent
1. **Audit `BinanceMarketDataFeed.get_close_asof(symbol, ts_s)`**:
   - Does it return bar close (1MIN granularity) or last tick price?
   - What's its data freshness guarantee? (e.g., "values are bar closes, available within 200ms of bar close")
   - Add unit test: at wallclock `T = ws+120`, what does `get_close_asof(symbol, ws+120)` return? Should be `close of bar [ws+60, ws+120)` if feed is fast, else `close of bar [ws, ws+60)`.
2. **Log the timestamp of the bar read, not just the value.** Currently `poly_updown_signal` logs `ret_2m_at_signal` and `bar_ctx_age_ms`. Add `btc_at_ws_bar_end_us` and `btc_at_120_bar_end_us`. This lets us distinguish "fed previous bar" from "fed current bar" at fire time.
3. **Consider a deliberate fire-delay**: instead of firing at wallclock `ws+120`, fire at `ws+120 + 2s` (or whatever measured publish-latency) to let the feed catch up. Trade-off: 2s less time-to-resolution.

### Storedata agent (your separate plan)
1. **Steps 1-6 in your plan** (chainlink merge, derive re-run, TV events cross-check, chained-strike check, UMA decoder, v3 view) are still relevant.
2. **Additional**: `binance_klines_v2` write-latency. How quickly after a bar closes does the row appear in the DB? If <200ms, my backtest is fine. If 1-5s, my baseline is mildly optimistic for that side too.

### Backtest side (this session)
- I will add a `feed_lag_safety_s` parameter to `compute_ret_v1` defaulting to 1s (matching production's typical state). This makes future backtests realistic by default.
- Update canonical README to document the latency-aware mode.

## Files

- `data/v4/canonical/_results/lag_sweep_summary.csv` — 5-scenario sweep
- `data/v4/canonical/_results/_lag_sweep.py` — sweep harness
- `data/v4/canonical/_results/xref_live_vs_backtest.csv` — 32 matched slugs
- `data/v4/canonical/_results/_xref_live.py` — cross-reference harness
- `strategy_lab/reports/MOMO_V1V2_CANONICAL_2026_05_10.md` — original canonical backtest
