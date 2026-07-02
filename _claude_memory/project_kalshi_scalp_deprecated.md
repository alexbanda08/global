---
name: project_kalshi_scalp_deprecated
description: "CORRECTED — Kalshi early-book \"+30s wall\" was an observability artifact (subscribe-late), NOT missing liquidity. Pre-subscribe fixes it."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9be1f863-0eda-42c2-be82-3471b9558d8d
---

⚠️ **CORRECTED 2026-06-09.** The earlier claim ("no Kalshi book until +30s → scalp/early
sleeves untradeable on Kalshi") was WRONG — it was an **observability artifact**, not missing
liquidity.

**What's true:** Kalshi 15m order books have real depth from **~+10-20s** into the window
(validated on `kalshi_orderbook.parquet`: median `yes_bid_size` 239 @ +10-30s, 340 @ +30-60s;
100% of markets quoted). Our old data only "showed" first quote at median +38s because the
collector **subscribed to `orderbook_delta` AFTER the market opened** and missed the warmup.

**The fix (operator discovery, being implemented by the data agent 2026-06-09):**
`GET /markets?series_ticker={series}&status=unopened` returns upcoming markets BEFORE they open
(public, no auth — status initialized/unopened). Subscribe the next window's `orderbook_delta`
BEFORE open → book is warm at open → you see the +5-30s book.

**Implications once pre-subscribed Kalshi book is collected:**
- Early-offset 15m sleeves become Kalshi-tradeable. Top candidate: ETH 15m "offearly" family
  (offset 30) — `eth_15m_trstack_vwap_offearly` (n=235, WR 61%, robust) and the higher-WR
  small-n variants (band_v6 WR 73%, +1.3/tr — needs more n + DSR).
- Possibly revives the deprecated Kalshi 15m scalp (fires +5s) — but +5s sample is thin (4
  markets); solid liquidity starts ~+20-30s.
- NEXT: with the new pre-subscribed book, validate the ETH offearly fill (price/spread/depth)
  at +30s on the real Kalshi book before deploying.

Already live on Kalshi (going well): the BTC 15m off600 favorite (`btc_15m_ema50_ema800_off600_down`).
Validation: `migration_2026_06_08/kalshi_book_timeline.py`. Related: [[project_scalp_exit_config]].
