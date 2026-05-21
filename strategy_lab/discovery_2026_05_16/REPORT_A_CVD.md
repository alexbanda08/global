# Report A — CVD strategies on Polymarket Up/Down

**Date:** 2026-05-16
**Scripts:** `strat_A1_cvd_5m.py`, `strat_A2_cvd_15m_late.py`
**CSVs:** `_A1_per_asset_threshold.csv`, `_A1_combined.csv`, `_A2_per_asset_threshold.csv`, `_A2_combined.csv`

## Hypothesis

Polymarket CLOB trade-flow direction (signed aggressor notional, BUY=+, SELL=-) on the Up-side asset_id leaks information about settlement.

- **A1 (5m, production anchor):** observe CVD in `[ws_s, ws_s+120s]`, fire at `ws_s+120`. Window = PREVIOUS slot's first 2 min.
- **A2 (15m, LATE entry):** observe CVD over `[slot_start, entry_us]` (full) or `[entry_us-300, entry_us]` (last5). Fire 60s or 180s before slot_end.

Signal: UP if cvd > +T, DOWN if cvd < -T, SKIP otherwise.

## Setup notes

- Universe: BTC/ETH/SOL — 5m=6,110 markets; 15m=2,036 each.
- **Bug found:** `side` column in `trades_polymarket/*.parquet` is **lowercase** (`buy`/`sell`), not `BUY`/`SELL`. Pre-fix CVDs were 100% negative. Fixed by `.str.upper()`.
- PnL model: flat-0.5 entry. Win=+$24.50 (2% fee on profit). Lose=-$25.

## A1 — 5m production anchor results (corrected)

Combined (all 3 assets):

| T    | n_fires | hit_rate | pnl ($) |
|---:|---:|---:|---:|
|    0 | 10217 | 0.500 |  -2431 |
|   50 |  3570 | 0.519 |  +2424 |
|  100 |  2014 | 0.515 |   +982 |
|  200 |   958 | 0.526 |   +998 |
|  500 |   255 | 0.529 |   +307 |
| 1000 |    92 | 0.544 |   +175 |

Per-asset highlights: BTC T=1000 hits 0.546 on n=88; ETH T=100 hits 0.544 on n=294; SOL T=50 hits 0.548 on n=210. CVD heavily right-skewed (BUY-dominated tape) — DOWN fires rare.

## A2 — 15m late entry results

Combined sweep (all 3 assets):

| off | mode | T | n_fires | hit | pnl ($) |
|---:|---|---:|---:|---:|---:|
| 60  | last5 |  100 | 4040 | 0.602 | +19335 |
| 60  | last5 |  500 | 3070 | **0.724** | **+33289** |
| 60  | last5 | 1000 | 2475 | 0.776 | +33215 |
| 60  | last5 | 5000 |  925 | **0.885** | +17416 |
| 60  | full  | 1000 | 3813 | 0.602 | +18327 |
| 60  | full  | 5000 | 1795 | 0.675 | +15070 |
| 180 | last5 |  500 | 2899 | 0.672 | +23902 |
| 180 | last5 | 1000 | 2159 | 0.729 | +23938 |
| 180 | last5 | 5000 |  725 | 0.894 | +13951 |

Per asset, last5 / off=60 (best regime): BTC T=5000 hit 0.870 on n=808; ETH T=1000 hit 0.830 on n=837; SOL T=1000 hit 0.968 on n=434.

**Top configuration with n_fires ≥ 200:** `entry_off_s=60, obs_mode=last5, T=5000` → hit 88.5% on 925 fires, +$17,416 flat-0.5.

## No-lookahead verification

```
A1 (fire at ws_s+120):
  BTC btc-updown-5m-1777290900  fire_us=1777290720000000  max_trade_ts_us=1777290698000000  OK (gap 22s)
  BTC btc-updown-5m-1777291200  fire_us=1777291020000000  max_trade_ts_us=1777290988000000  OK (gap 32s)
  BTC btc-updown-5m-1777291500  fire_us=1777291320000000  max_trade_ts_us=1777291292000000  OK (gap 28s)

A2 (fire at slot_end-60s):
  BTC btc-updown-15m-1777290300  entry_us=1777291140000000  slot_end=1777291200000000
    max_trade_ts_us=1777291138000000  OK (gap 2s, 62s before slot_end)
```

All trades used have `timestamp_us < entry_us`. No leak.

## Honest verdict

**A1: NULL.** 5m production-anchor CVD. T=50 combined: 51.9% on 3,570 fires (~$2.4k flat-0.5). At ±1.6pp σ — borderline. Prior-2-min flow doesn't predict next-slot direction.

**A2: INCONCLUSIVE (strong-looking but suspect).** 88.5% hit at T=5000/last5/off=60 looks like alpha BUT the entry-price assumption is fantasy. By minute 14 of a 15m market, spot has moved, CLOB on Up-side is priced at $0.85+, high CVD just means "Up is winning, everyone knows." Buying YES at $0.85 wins ~$0.15/share not $0.50/share. Real edge per trade ≈ +$0.75 not +$24.50 — flat-0.5 PnL **inflates by 5-10×**. The $33k pnl at T=500/last5/60 likely becomes ~$1-3k with real L25 fills.

## Recommendation

1. Re-run A2 with `engine_v2.fill_at_book` + real Polymarket fee curve (`0.07*p*(1-p)` per share) at `entry_us`.
2. Baseline against `signal_from_mid = UP if ask_0 < 0.5 else DOWN` at same `entry_us`. If mid alone hits 85%+, CVD adds nothing.
3. Permutation test (1000 sign-flip draws) before sizing claim.
4. Drop A1.

If A2 still beats the mid-only baseline by >1pp hit rate after real fills → alpha candidate. If not → NULL.
