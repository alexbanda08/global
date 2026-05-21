# Partial-Fill HEDGE/SELL Backtest vs Live Momo v1+v2

**Date:** 2026-05-09
**Hypothesis tested:** "Production HEDGE/SELL only fire if FULL position liquidity is available; partial fills should improve PnL."
**Verdict:** **Hypothesis disproven for SELL, marginal for HEDGE.** The L25 bid/ask books almost always have ≥95% of needed liquidity in this window, so partial-friendly only helps in 18 of 569 trades (~3%). Partial recovers ~$175/week on HEDGE, $0 on SELL.

The big picture: partial-fill is NOT what's blocking SELL/HEDGE in production. Something else is.

## Test setup

- 851 live momo v1+v2 resolutions from VPS3 (last 7 days)
- For each trade, replay ENTRY + (HEDGE | SELL) using strict-asof Binance + VPS2 WS L25 books
- Compare two modes:
  - **`require_full`**: skip exit if `shares_filled < shares_e * 0.95` (current production-like behavior)
  - **`partial_friendly`**: accept any positive fill; settle remainder at chainlink

## Per-policy results (across all 6 cells × v1/v2)

| policy | mode | n_simulated | n_fired | fire% | pnl_total | pnl/trade |
|---|---|---:|---:|---:|---:|---:|
| HEDGE | require_full | 674 | 296 | 43.9% | **−$975** | −$1.45 |
| HEDGE | partial_friendly | 674 | 314 | 46.6% | **−$800** | −$1.19 |
| SELL | require_full | 674 | 314 | 46.6% | **−$838** | −$1.24 |
| SELL | partial_friendly | 674 | 314 | 46.6% | **−$838** | −$1.24 |
| HOLD | n/a | 674 | 0 | 0% | **−$382** | −$0.57 |

**Key reads:**
- HEDGE partial − HEDGE require_full = +$175 (delta from 18 newly-firing partial trades)
- SELL partial = SELL require_full **exactly** — i.e. SELL's bid book in this window always had ≥95% of needed shares whenever the rev_bp gate triggered. The full-vs-partial knob does nothing on SELL.
- HOLD beats both HEDGE and SELL on this window. The exit policies are amplifiers and hurt during a losing regime.

## Per-cell HEDGE pnl_total (partial_friendly minus require_full)

| asset | tf | v1 (Δ) | v2 (Δ) | comment |
|---|---|---:|---:|---|
| BTC | 15m | $0 | $0 | no partial-only fires |
| BTC | 5m | $0 | $0 | no partial-only fires |
| ETH | 15m | $0 | $0 | no partial-only fires |
| ETH | 5m | $0 | $0 | no partial-only fires |
| SOL | 15m | $0 | $0 | no partial-only fires |
| **SOL** | **5m** | **−$94** | **+$269** | the only cell where partial matters |

The 18 partial-only fires concentrate in `sol_5m` — both v1 and v2 — because SOL 5m books are thin and `shares_h < shares_e * 0.95` triggers the require_full skip. Partial-friendly fires those, with mixed PnL: v1 loses $94, v2 gains $269. Net of the two: +$175.

## What this rules out

- **"Production demands full-fill liquidity"** → ruled out for SELL (own-side bid books always have ≥95% liquidity at L25 when the gate opens). Marginal effect on HEDGE (only 18 trades).
- **"Bid books are missing"** → ruled out (SELL backtest fires 46.6% = matches the rev_bp gate-open rate; book is always present when gate opens).

## What's still on the table

Production SELL fires only **5 / 287 (1.7%)** while backtest fires **46.6%** with the SAME books. The 132-trade gap is NOT explained by partial-fill semantics. Most likely causes (ordered by likelihood):

1. **The new WS book mirror isn't actually serving `_try_bid_exit`.** TV agent added `book_mirror.py` and set `TV_POLY_BOOK_MIRROR=true`, but the SELL path's `_fetch_own_book` may still route to REST. The diagnostic for this:

   ```sql
   -- Look for book_source field in resolution events post-deploy
   SELECT data->>'book_source' AS src,
          data->>'partial_bid_exit' AS exited,
          COUNT(*) FROM trading.events
   WHERE kind='poly_updown_resolution'
     AND sleeve_id LIKE '%_momo%_SELL'
     AND at > now() - interval '24 hours'
   GROUP BY 1, 2 ORDER BY 1, 2;
   ```

   If `book_source` is NULL or `'rest'` for the SELL sleeves, WS isn't reaching the exit path.

2. **SELL has no retry** in production. `_try_bid_exit` is one-shot per rev_bp trigger event. If the WS-mirror snapshot at that exact tick happens to be empty/stale, SELL falls through to chainlink. HEDGE doesn't have this issue because it retries every 10s tick.

3. **Token-id resolution race.** `_try_bid_exit` resolves `own_token = slot.yes_token_id if signal=="UP" else slot.no_token_id`. If those fields aren't populated until AFTER the rev_bp gate first triggers, the first-tick attempt fails on `own_token=None` and only subsequent ticks have the resolved token. Bug 18.2 was supposedly fixed (lines 3380-3430 in current code show the resolve-and-cache pattern), but worth re-checking it actually populates correctly.

## Recommendation

1. **Verify with logs/DB which book source `_try_bid_exit` used.** Run the SQL above on VPS3. If WS isn't reaching SELL, that's the bug.
2. **Add retry to SELL** even if WS is wired. Mirror HEDGE's retry pattern. The SELL gap is consistent with one-shot semantics getting unlucky on transient book gaps.
3. **Skip the partial-fill change** — backtest shows it doesn't move the needle.

## Files
- script: `strategy_lab/meta_classifier/momo_partial_fill_backtest.py`
- per-trade output: `data/v4/shadow_trades_2026_05_08/momo_partial_fill_per_trade.csv`
- input data: `data/v4/shadow_trades_2026_05_08/momo_v1v2_live.csv`, `vps2_l25_*.csv`, `vps2_klines_1m.csv`
