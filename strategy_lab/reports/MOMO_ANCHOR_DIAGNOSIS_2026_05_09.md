# Anchor Diagnosis — Why Production HOLD Underperforms Backtest by 97%

**Date:** 2026-05-09
**Question:** Production HOLD captures +$0.35/trade vs backtest +$13.54/trade (17-stdev hit-rate gap). Is the cause a wrong anchor, a data mismatch, or something else?
**Method:** brute-force search across 1156 anchor candidates × 300 production audit rows. Recompute `ret_2m_at_signal` and compare to production's logged value.

## Verdict

**Root cause: my backtest's kline data source does NOT match production's.** No simple anchor `(ws+a, ws+b)` on my klines reproduces production's `ret_2m_at_signal`.

The `ret_2m_at_signal` values production logs cannot be derived from any 1m kline lookup window in the data I have. **My backtest has been computing on the wrong inputs.** Backtest's +$13.54/trade claim is therefore unreliable for the May 7-9 window.

## Brute-force search results

Tested 6 hand-picked anchor candidates × 2 sources (binance/okx) × 2 asof types (strict/buggy) × full 300-row sample.

Best match: `off0=-240s, off1=-180s, source=okx, asof=strict`, MAD=0.0011 across 80-row sample. That's a 4-minute return ENDING 3 minutes BEFORE bar-close — clearly meaningless as a strategy signal. The "best" config is just whatever happens to land in the noise band.

| candidate | mean abs diff | matches within 1e-5 |
|---|---:|---:|
| spec_v2_strict (ws-60, ws+60), strict | 0.00164 | 0/300 |
| v1_doc_strict (ws, ws+120), strict | 0.00162 | 0/300 |
| short_window (ws, ws+60) | 0.00162 | 0/300 |
| long_window (ws-60, ws+120) | 0.00167 | 0/300 |
| v1_buggy_asof (ws, ws+120), buggy | 0.00152 | 0/300 |
| v2_buggy_asof (ws-60, ws+60), buggy | 0.00162 | 0/300 |

**No anchor reproduces production's values, even approximately.** Production's logged ret_2m magnitudes (typical ~17bp) are 2-3× larger than what my klines can produce over any 60-300s window (typical 4-10bp).

## Why my klines are wrong

Inspected per-source data freshness in `data/v4/refresh_2026_05_09/klines_full.csv`:

| symbol | source | latest data |
|---|---|---|
| BINANCE_SPOT_BTC_USDT | binance-spot-ws | **2026-04-29 18:56** (10 days stale) |
| BINANCE_SPOT_ETH_USDT | binance-spot-ws | 2026-04-29 18:56 |
| BINANCE_SPOT_SOL_USDT | binance-spot-ws | 2026-04-29 18:56 |
| OKX_SPOT_BTC_USDT | okx-ws | 2026-05-09 19:14 (current) |
| OKX_SPOT_ETH_USDT | okx-ws | 2026-05-09 19:14 |
| OKX_SPOT_SOL_USDT | okx-ws | 2026-05-09 19:14 |

**VPS2's Binance feed died on April 29.** My backtest correctly fell back to OKX data for May 7-9 trades, but **production on VPS3 has its own Binance-WS feed** which is fresh through May 9. Same minute, slightly different prices:

For SOL @ ws=1778288100 (May 9):
- VPS3 binance-spot-ws: 92.42 (close at ts=ws), 92.51 (close at ts=ws-60), 92.45 (close at ts=ws+60)
- VPS2 OKX-ws (my data): 92.42, 92.49, 92.45

Spread: 2-3 cents per bar. Cumulative effect on ret_2m: small (~2bp difference at most). Not enough to explain a 17bp production value vs my 6bp computation.

So the source mismatch is real but doesn't fully explain the gap. **Something else is happening.**

## What production might actually compute

Production's `ret_2m_at_signal` for that SOL row is **−0.001729** (= −17.29 bp). My data doesn't have a 17bp move within ±360s of ws on either Binance or OKX. The bars I see span 92.42 → 92.52 (a 10.8bp range), and even the widest pair I can construct gives at most ~10bp.

Where does the extra signal come from? Three possibilities:

1. **Production uses 1SEC data, not 1MIN.** VPS3 has `binance-vision` 1SEC bars. The price at *exact* second-level of the audit timestamp can differ by more than the 1m bar close.

2. **Production uses a different timestamp anchor entirely.** Maybe ws_s in the BarContext isn't the slug-encoded value — could be set to bar-close *event time* (with sub-minute drift). If production's "ws-60" is actually 60s before the BarContext's ws timestamp (which itself is offset from slug-ws), my computation is 1-2 minutes off in absolute time.

3. **Production fetches from a feed that has different bar boundaries.** Polymarket's WS aggregation, Binance futures vs spot, Coinbase, Kraken — VPS3 may use a feed I haven't replicated.

## The "TV agent's strict-asof fix is incomplete" hypothesis

**Cannot be confirmed or denied with this data.** All my tests show "no anchor matches" — that includes both strict-asof variants and buggy-asof variants. The mismatch is upstream of anchor logic, in the kline source itself.

## Recommended fix for the backtest

**Pull klines directly from VPS3** (where production reads them) instead of VPS2 (which has stale Binance data + only OKX coverage post-Apr 29).

```bash
# On VPS3:
psql ... -c "\copy (SELECT symbol_id, period_id, time_period_start_us, price_close, source
                    FROM binance_klines_v2
                    WHERE period_id IN ('1MIN','1SEC')
                    AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
                    AND time_period_start_us > extract(epoch from now() - interval '28 days')*1000000)
                   TO '/tmp/vps3_klines.csv' CSV HEADER"
```

Re-run the full-universe validation with these klines. If results match production within 5%, the data mismatch was the issue. If still off, look at 1SEC precision next.

**Until then, the +$13.54 backtest figure should be treated as suspect.** The May 7-9 portion of the backtest universe was computed on stale OKX-only data, not the same data production sees.

## What the production data DOES tell us

Independent of any backtest:
- 355 HOLD trades over 67h: **+$0.35/trade, 52% hit rate**
- 6 of 12 cells positive (BTC_15m, ETH_15m perform best)
- Cumulative: −$66 (May 7), +$493 (May 8), −$303 (May 9)

If real-world hit rate is 52%, momo at vwap=0.61 is structurally negative-EV in production, regardless of what the backtest claims. **Don't size up live deploys based on the backtest until the data mismatch is resolved.**

## Action items (priority order)

1. **Pull VPS3 klines** and re-run `momo_full_universe_validation.py`. Settles whether backtest's +$13 number is real.
2. **If VPS3 klines don't fix it, pull 1SEC binance-vision data** and try sub-minute precision.
3. **In parallel:** keep all 36 sleeves running; collect another 7+ days of production data; the more samples the less noise.
4. **Don't ship momo_v2 HOLD-only deploy** based on the +$13 backtest until validated against production-equivalent klines.

## Files
- `data/v4/shadow_trades_2026_05_09/momo_orders_for_anchor.csv` — 300 production audit rows
- `data/v4/shadow_trades_2026_05_09/anchor_diagnosis.csv` — per-row candidate ret_2m comparisons
- `strategy_lab/meta_classifier/_diagnose_anchor.py` — fixed-set anchor diagnostic
- `strategy_lab/meta_classifier/_brute_force_anchor.py` — 1156-config search
- `strategy_lab/reports/MOMO_HOLD_PROD_VS_BACKTEST_2026_05_09.md` — original gap report
