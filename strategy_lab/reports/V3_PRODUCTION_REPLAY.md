# V3 Production Replay — Backtest vs Live Shadow

_Generated: 2026-05-05_

## Why a new backtest?

The earlier `v3_btc_union_realfills.py` made TWO production-fidelity errors that the VPS3 shadow data exposed:

1. **Entry timing**: previous run used `entry_bucket = 12` (t+120s). Wrong for V3 — V3 fires at Binance bar close, which is bucket 0 of the new Polymarket market.
2. **Hedge frequency**: previous run assumed `rev_bp=5` triggered ~60+ hedges in V3-BTC. Live shadow shows **0 hedges in 190 V3 trades** (4 days). Production HEDGE_HOLD policy almost never triggers in 5m markets because `prob_stack` doesn't correlate with same-window Binance reversion.
3. Also missing: **production spread filter** `TV_POLY_V3_SPREAD_FILTER_BTC=0.02` (skip if ask_0 - bid_0 > 2¢).

## VPS3 production config (verified)

```
TV_POLY_HEDGE_POLICY=HEDGE_HOLD
TV_POLY_V3_SPREAD_FILTER_BTC=0.02
TV_POLY_V3_SPREAD_FILTER_ETH=0.02
TV_POLY_V3_SPREAD_FILTER_SOL=0.025
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v3_3,v4
```

## Backtest variants on V3 BTC fires (Apr 22 → Apr 29)

V3 features have 2734 BTC markets; V3 fires (prob_stack confidence ≥ 0.65): 330 markets.

| Variant | n | hit% | avg vwap_e | total PnL | mean PnL | hedged | spread_skipped |
|---|---:|---:|---:|---:|---:|---:|---:|
| A. PRODUCTION (entry@0 + spread≤0.02 + hedge_hold) | 248 | 62.1% | $0.5313 | $+1440.79 | $+5.8097 | 52 | 43 |
| B. PRODUCTION-NO-HEDGE (entry@0 + spread≤0.02 + hold-to-resolution) | 248 | 68.1% | $0.5313 | $+1766.93 | $+7.1247 | 0 | 43 |
| C. PREVIOUS BACKTEST (entry@0 unchanged, no spread filter, hedge ON) | 291 | 59.1% | $0.5351 | $+1276.66 | $+4.3871 | 63 | 0 |
| D. NO-FILTER NO-HEDGE (entry@0, no spread filter, hold-to-resolution) | 291 | 65.3% | $0.5351 | $+1602.89 | $+5.5082 | 0 | 0 |

## VPS3 shadow `poly_updown_btc_5m_v3` (base V3, BTC only, Apr 30 → May 5)

- n: 56
- hit: 57.1%
- total PnL: $+146.50
- mean PnL: $+2.6161 / trade
- avg entry price: $0.5121
- hedged: 0

## Reconciliation

| Metric | Variant B (production-no-hedge) backtest | Shadow `btc_5m_v3` |
|---|---:|---:|
| n              | 248      | 56 |
| hit            | 68.1% | 57.1% |
| avg vwap entry | $0.5313      | $0.5121 |
| total PnL      | $+1766.93     | $+146.50 |
| mean PnL       | $+7.1247      | $+2.6161 |
| hedged         | 0      | 0 |

*Different time windows*: backtest uses Apr 22-29 (V3 features available), shadow uses Apr 30-May 5. If V3's edge is stable, mean PnL should be in the same ballpark.

→ **Shadow UNDERPERFORMS Variant B by $4.51/trade**. Forward-walk degradation; investigate.