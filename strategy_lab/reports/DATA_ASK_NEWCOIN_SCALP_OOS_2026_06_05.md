# DATA ASK — unlock the scalp OOS on the NEW COINS (DOGE/BNB/XRP/HYPE)

**For:** storedata / canonical operator.
**Why:** the exit-scalp + time-of-day gate are now OOS-validated on BTC/ETH/SOL (Mar 30→Apr 21,
`SCALP_OOS_PASS_2026_06_05.md`). The new coins have up/down markets (`resolutions_hf`) but the **signal /
book / market windows don't overlap**, so the scalp can't be run on them yet. Each coin needs ONE specific
feed aligned to its market window.

## The scalp needs, per coin, three things overlapping in time
1. **outcomes** — `resolutions_hf` ✅ already present for all 6 coins.
2. **binance spot 1s** (the lag signal: `delta = |1s 5s-return| at slot_start`).
3. **slot-aligned book at slot_start+5s** (BBO from `load_orderbook_bbo`, or full L25).

## Current coverage vs gap (per coin)
| coin | markets (resolutions_hf) | binance 1s | BBO book | usable overlap | GAP TO FIX |
|---|---|---|---|---|---|
| BTC/ETH/SOL | to Apr 21 | Jan 1→**Jun 4** | Mar 30→Apr 21 | ✅ Mar30–Apr21 | none (done) |
| **DOGE** | **Apr 6→Apr 21** (4,190 5m/15m) | Jan 1→**Apr 6** ❌ | Mar 30→Apr 21 ✅ | ~Apr 6 only | **extend binance 1s DOGE → Apr 21** |
| **BNB** | **Apr 6→Apr 21** (4,115) | Jan 1→**Apr 6** ❌ | Mar 30→Apr 21 ✅ | ~Apr 6 only | **extend binance 1s BNB → Apr 21** |
| **XRP** | Mar 1→Apr 21 (8,993) but **0 5m/15m in Mar30–Apr6** | Jan 1→Apr 6 | Mar 30→Apr 21 | none for 5m/15m | **verify XRP 5m/15m market dates; need book+1s overlapping them** (XRP 5m/15m appear to sit pre-Mar30 where BBO doesn't reach, OR are non-5m/15m TFs) |
| **HYPE** | Apr 6→Apr 21 (4,082) | none (HL only, hourly) ❌ | Mar 30→Apr 21 ✅ | no fast signal | **need a sub-minute HYPE signal** (binance HYPE 1s if listed, else HL 1s/trade-derived; hourly HL klines too coarse) |

## Concrete asks (priority order)
1. **DOGE + BNB: backfill binance spot 1s klines for Apr 6 → Apr 21** (into `klines_1s.parquet`, symbol_ids
   `BINANCE_SPOT_DOGE_USDT` / `BINANCE_SPOT_BNB_USDT`). This alone unlocks the DOGE+BNB scalp OOS (their BBO +
   markets already cover Apr 6–21). Highest value, smallest fill.
2. **XRP: extend binance spot 1s → Apr 21** (same fix as DOGE/BNB; XRP 1s still ends Apr 6). DIAGNOSED 2026-06-05:
   XRP HAS plenty of 5m/15m markets (6554 5m + 2136 15m) and BBO covers Apr 7–21 — but the three windows don't
   overlap: markets = Mar 1–13 **+ Apr 7–21** (gap Mar 14–Apr 6); BBO = Mar 30→Apr 21; **1s ends Apr 6**. So
   Apr 7–21 has markets ✓ + BBO ✓ but no signal. Extending XRP 1s to Apr 21 makes **Apr 7–21** fully overlap →
   XRP scalp OOS runnable (~2 weeks). (Mar 1–13 is blocked: BBO starts Mar 30, and the trentmkelly L25 backfill
   there has the +80s late-start.)
3. **HYPE: provide a sub-minute HYPE price** (binance `HYPERLIQUID`/`HYPE` 1s if it exists on a listed CEX, or
   derive 1s from HL trades). Current `hyperliquid_klines` are hourly → unusable for the 5s lag.
4. (lower) Any **full-L25 aliplayer feed for Mar 30→Apr 21** would let us remove the BBO top-of-book caveat on
   the BTC/ETH/SOL OOS (currently fills at best_ask, no depth walk).

## Acceptance (what I'll run once each lands)
- DOGE/BNB: `scalp_oos_bbo_2026_06_05.py` with their window set to Apr 6→Apr 21 → expect non-zero candidate
  fires + a gated `$/tr` with CI. (Just re-add them to the WIN dict.)
- XRP: depends on your answer to #2.
- Goal: replicate the BTC/ETH/SOL OOS pass (gated vwap<0.55 CI>0) on ≥1 new coin → extends the validated
  scalp universe.

## Files / evidence
- OOS pass + new-coin blockers: `strategy_lab/reports/SCALP_OOS_PASS_2026_06_05.md`
- Inventory + timing notes: `strategy_lab/reports/NEW_DATA_INVENTORY_2026_06_05.md`
- Runner: `strategy_lab/directional/scalp_oos_bbo_2026_06_05.py` (re-add coins to `WIN` once feeds land)
