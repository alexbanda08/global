# Exit Policy Comparison — HOLD vs HEDGE vs SELL

_Generated: 2026-05-05_

## Why this exists

VPS3 shadow shows **0 hedges fired in 190 V3 paper trades** despite `TV_POLY_HEDGE_POLICY=HEDGE_HOLD`. Production V3 paper effectively runs `HOLD-to-resolution` because BarEngine `on_tick` wiring is incomplete (open in TV agent backlog).

Question: instead of hedging (BUY opposite-side YES/NO at ASK), what if we SELL the held position at BID when the signal fails? SELL is simpler to wire (no opposite-side book needed) and may be what's deployable today.

## Where the hedge logic came from

Copied from `polymarket_signal_grid_realfills.py` lines 116-145 — the canonical UpDown engine that produced the published v2 numbers. The trigger is:
```python
bp = (binance_now - binance_at_entry) / binance_at_entry * 10000
reverted = (sig==1 and bp <= -rev_bp) or (sig==0 and bp >= rev_bp)
```
Default `rev_bp=5` (= REV_BP_THRESHOLD in `polymarket_updown_PROD_2026_05_05.py`).

## Policies

| ID | Trigger | Action |
|---|---|---|
| HOLD            | never            | hold to $1/$0 settlement |
| HEDGE_REVERT_5  | rev ≥ 5bp        | BUY opposite side @ ASK (canonical) |
| SELL_REVERT_5   | rev ≥ 5bp        | SELL held @ BID |
| SELL_REVERT_8   | rev ≥ 8bp        | SELL held @ BID (looser trigger) |
| SELL_FLOOR_040  | bid ≤ 0.40       | SELL held @ BID |
| SELL_FLOOR_035  | bid ≤ 0.35       | SELL held @ BID |
| SELL_TRAIL_10   | bid drops 10% from peak | SELL held @ BID |
| SELL_TRAIL_15   | bid drops 15% from peak | SELL held @ BID |

All policies: $25 stake, top-10 ASK book walk for entry, BID book walk for SELL exit, 2% taker on profit only, BTC spread filter ≤ 0.02. Settlement on hold = $1/$0.

## Results

| Signal × Policy | n | hit% | total PnL | mean PnL | std | min PnL | max PnL | hold | hedge | sell | Sharpe |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V3_BTC5m | HOLD | 248 | 68.1% | $+1766.93 | $+7.1247 | $22.86 | $-25.00 | $+54.53 | 248 | 0 | 0 | +35.22 |
| V3_BTC5m | HEDGE_REVERT_5 | 248 | 70.6% | $+2012.23 | $+8.1138 | $19.58 | $-25.00 | $+54.53 | 183 | 65 | 0 | +46.82 |
| V3_BTC5m | SELL_REVERT_5 | 248 | 70.6% | $+2035.98 | $+8.2096 | $19.54 | $-25.00 | $+54.53 | 183 | 0 | 65 | +47.48 |
| V3_BTC5m | SELL_REVERT_8 | 248 | 67.3% | $+1830.12 | $+7.3795 | $21.36 | $-25.00 | $+54.53 | 211 | 0 | 37 | +39.04 |
| V3_BTC5m | SELL_FLOOR_040 | 248 | 43.5% | $+858.23 | $+3.4606 | $14.31 | $-24.53 | $+40.53 | 100 | 0 | 148 | +27.32 |
| V3_BTC5m | SELL_FLOOR_035 | 248 | 48.0% | $+1079.28 | $+4.3519 | $15.99 | $-25.00 | $+40.53 | 118 | 0 | 130 | +30.76 |
| V3_BTC5m | SELL_TRAIL_10 | 248 | 46.0% | $+380.55 | $+1.5345 | $8.22 | $-24.50 | $+38.32 | 15 | 0 | 233 | +21.09 |
| V3_BTC5m | SELL_TRAIL_15 | 248 | 44.0% | $+507.71 | $+2.0472 | $9.82 | $-24.50 | $+38.32 | 37 | 0 | 211 | +23.55 |
| BTC_only_5m | HOLD | 274 | 89.1% | $+3053.98 | $+11.1459 | $75.48 | $-25.00 | $+1200.50 | 274 | 0 | 0 | +13.43 |
| BTC_only_5m | HEDGE_REVERT_5 | 274 | 89.4% | $+3431.73 | $+12.5246 | $74.98 | $-25.00 | $+1200.50 | 197 | 77 | 0 | +15.19 |
| BTC_only_5m | SELL_REVERT_5 | 274 | 89.8% | $+3444.26 | $+12.5703 | $74.97 | $-25.00 | $+1200.50 | 197 | 0 | 77 | +15.25 |
| BTC_only_5m | SELL_REVERT_8 | 274 | 91.2% | $+3348.78 | $+12.2218 | $75.13 | $-25.00 | $+1200.50 | 246 | 0 | 28 | +14.79 |
| BTC_only_5m | SELL_FLOOR_040 | 274 | 79.6% | $+938.01 | $+3.4234 | $12.42 | $-25.00 | $+62.31 | 216 | 0 | 58 | +25.06 |
| BTC_only_5m | SELL_FLOOR_035 | 274 | 79.9% | $+1000.25 | $+3.6505 | $13.06 | $-25.00 | $+62.31 | 219 | 0 | 55 | +25.42 |
| BTC_only_5m | SELL_TRAIL_10 | 274 | 69.0% | $+1297.07 | $+4.7338 | $23.27 | $-22.37 | $+309.40 | 144 | 0 | 130 | +18.50 |
| BTC_only_5m | SELL_TRAIL_15 | 274 | 71.9% | $+1359.31 | $+4.9610 | $23.87 | $-24.64 | $+309.40 | 166 | 0 | 108 | +18.90 |

## Best policy per signal

### V3_BTC5m

- **Best total PnL**: SELL_REVERT_5 → $+2035.98 (70.6% hit)
- **Best Sharpe**:    SELL_REVERT_5 → Sharpe +47.48 ($+2035.98)
- vs HOLD baseline: best policy delivers **$+269.05** more than hold-to-resolution
- → **SELL exit beats HOLD** by $269.05. Consider deploying.

### BTC_only_5m

- **Best total PnL**: SELL_REVERT_5 → $+3444.26 (89.8% hit)
- **Best Sharpe**:    SELL_FLOOR_035 → Sharpe +25.42 ($+1000.25)
- vs HOLD baseline: best policy delivers **$+390.28** more than hold-to-resolution
- → **SELL exit beats HOLD** by $390.28. Consider deploying.
