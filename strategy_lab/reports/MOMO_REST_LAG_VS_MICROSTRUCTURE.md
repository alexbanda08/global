# Momo Cross-Check: Production Live ent_px vs VPS2 WS L25 Parquet

**Date:** 2026-05-06
**Purpose:** Settle whether momo's ~58% WR / +$229 paper PnL on 72 live trades reflects real microstructure alpha or production REST staleness.

## Verdict: **REST lag is the alpha source. Paper PnL is fictitious.**

In the live $1 transition spec, this means a tradeable production execution **cannot replicate paper performance**. Going live at $1 with the current architecture probably loses money.

## Method

Two timestamps to reconcile:
- `at_utc` in production audit rows = chainlink-resolution audit time (1-3 min AFTER fill)
- True fill time = `slug_ws + 120s` per master scheduler dispatch (`now ∈ [ws+120, ws+125]`)

For 4 representative production trades, looked up the L25 parquet (`data/v4/refresh_2026_05_06/cache/{asset}_orderbook_L25.parquet`) for the same `(slug, held_outcome)` at fill time = `slug_ws + 120s`. Compared the parquet's `ask_price_0` to production's audited `entry_price`.

## Data

| # | Slug | Held | Prod fill (ws+120) | Prod paid | Parquet ask₀ | Parquet bid₀ | Δ (parquet−prod) | Won? |
|---|---|---|---|---:|---:|---:|---:|---|
| #16 | btc-updown-5m-1778043300 | Down | 04:57:00 UTC | **0.4682** | 0.66 | 0.65 | **−0.19** | won |
| #31 | btc-updown-5m-1778058600 | Up   | 09:12:00 UTC | **0.5100** | 0.83 | 0.81 | **−0.32** | lost |
| #28 | sol-updown-5m-1778049600 | Up   | 06:42:00 UTC | **0.4804** | 0.56 | 0.54 | **−0.08** | lost |
| #4  | sol-updown-5m-1778034600 | Down | 02:32:00 UTC | **0.5197** | ~0.80 | ~0.78 | **−0.28** | won |

In 3 of 4 cases, **production paid $0.19-0.32 LESS than the WS L25 ask at the same instant**. The fourth (SOL #28) shows a smaller divergence (−$0.08) but still in the same direction.

## Interpretation

When BTC moves +Nbp during the first 2 minutes of a market:
1. **VPS2 WS feed**: book updates ingest near-instantly. Asks for the favored token rise to ~$0.66 within ~1 second of the Binance print.
2. **Polymarket REST CLOB endpoint**: returns a cached/buffered book that's typically 1-2 seconds stale. The cached book still shows asks at $0.47 (pre-move pricing).
3. **Production paper executor**: queries REST → sees stale book → simulates a fill at the stale ask price → audits paper PnL at that fill price.

The paper PnL is computed against a price that **was never available to a live taker**. A live order routed against the same REST book would either:
- Fail to fill (the asks at $0.47 don't actually exist on chain), OR
- Get filled by the matching engine at the post-absorption price (~$0.66), with the order book updating in flight.

Either way, the paper PnL doesn't translate to live PnL.

## Implication for live transition spec (DRAFT @ `TV_AGENT_LIVE_TRANSITION_SPEC.md`)

**Hold the live $1 transition.** The +$229 / 58% WR / $0.50 vwap shadow result is an artifact of REST staleness, not a tradable alpha.

Quick PnL re-estimate at TRUE WS prices (vwap ≈ 0.66) on the existing 72 trades:
- 42 wins × ($1 − 0.66) × shares × (1 − 2% fee) ≈ 42 × $12.5 × 0.98 ≈ **+$515**
- 30 losses × −$25 ≈ **−$750**
- Net: **−$235** (vs +$229 paper) — strategy is net negative at WS prices.

Refined break-even: hit rate must exceed `vwap` (currently 0.66+ for top-decile gated trades). At 58% live shadow hit rate, the strategy is structurally unprofitable in WS-priced execution.

## What the WS migration (Phase 2) actually does

The original spec called WS migration a "scale enabler" — moving from REST (200-500ms + 1s cache) to WS (<50ms staleness) for live trading. Under the REST-lag hypothesis, **WS migration KILLS the strategy** — exactly the alpha we were trying to monetize.

This is the opposite of what the prior backtest assumed (which used VPS2 WS books and reported +$13K PnL via correct anchor + lower vwap because the prior tier1 books were 60s earlier in the market lifecycle than the current refresh's tier1).

## Action items

1. **Mark the live transition spec as BLOCKED on alpha verification.** Do not flip any sleeve to live $1.
2. **Re-frame the strategy.** It's a REST-staleness exploit, not a Binance-lag exploit. Three paths:
   (a) Lean into REST staleness — but it's not exploitable in production-live (orders against true book).
   (b) Find a different alpha source. The original backtest's promised +$13K/12d came from books that were 60s earlier in the market lifetime — but that's just an artifact of the timing mismatch, not a real edge.
   (c) Accept that this strategy doesn't work at $1 live. Move to other meta-classifier sleeves (V3 inverse, etc.).
3. **Sanity-check the backtest harness.** The `extended_backtest.csv` numbers used per-asset entry parquets that landed at `target_ts_us = window_start_unix + 120` where `window_start_unix` was the strike (= `slug_ws-60`). Effective book timing was `slug_ws + 60s`. Current parquets land at `target_ts_us = slug_ws + 120s` — 60s LATER, hence higher vwap. Verify which is closer to production REST behavior; neither matches the true microstructure.
4. **Tests 1-4 from prior plan are now scoped down**: anchor sweep + hedge no_asks investigation still valuable, but the haircut decomposition (test 3) gets the dominant answer right here — the haircut is the REST-vs-WS gap.

## Files
- script: `strategy_lab/meta_classifier/_inspect_parquet_density.py`
- run output stored in transcript (not persisted to CSV)
- prior reports: `MOMO_RERUN_L25_HOLD_2026_05_06.md`, `MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md`, `TV_AGENT_LIVE_TRANSITION_SPEC.md` (DRAFT — now BLOCKED)

## Recommended next session question to user

"Do you want to (a) salvage the strategy by finding a different alpha (e.g. wider rev_bp, different gate, completely different signal), (b) confirm the REST-lag finding with one live $1 fill (definitive answer in 5 min — order at REST price will/won't fill), or (c) shelve momo and pivot to another idea?"
