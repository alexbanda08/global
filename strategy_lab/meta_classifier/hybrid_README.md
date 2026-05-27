# Hybrid sleeve scaffolding (Range Filter DW + Traders Reality)

Scaffolding to test combinations of new indicators (Range Filter DW + Traders
Reality stack) on the canonical chainlink-resolved 5m / 15m up-down universe.

## Data flow

```
                              (parallel agents)
                                     |
data/v4/canonical/                   |
  resolutions_from_rtds.parquet ─┐   |
  klines_1s/binance_1s_28d.parquet   |
  klines_1m.parquet              │   v
  refresh_*/cache/*_L25.parquet  │   data/v4/canonical/_results/
                                 │     range_filter_1s.parquet    (agent A)
                                 │     traders_reality_1s.parquet (agent B)
                                 │     ta_indicators_1s.parquet   (existing)
                                 │     prod_q90_calibration/hourly_thresholds.parquet
                                 v
                  ┌──────────────────────────────┐
                  │ hybrid_fire_universe_build.py│  (this scaffold)
                  └────────────┬─────────────────┘
                               │
                               v
       data/v4/canonical/_results/
         hybrid_fire_universe_5m.parquet
         hybrid_fire_universe_15m.parquet
                               │
                               v
                  ┌──────────────────────────────┐
                  │ hybrid_feature_join.py       │
                  └────────────┬─────────────────┘
                               │
                               v
       data/v4/canonical/_results/
         hybrid_features_5m.parquet
         hybrid_features_15m.parquet
                               │
                               v
                  ┌──────────────────────────────┐
                  │ hybrid_backtest.py           │
                  │   run_hybrid_backtest(...)   │
                  │   walk_forward_split(...)    │
                  │   gate_search(...)           │
                  └──────────────────────────────┘
```

## Files

| Path | Status | Purpose |
|------|--------|---------|
| `strategy_lab/meta_classifier/hybrid_fire_universe_build.py` | scaffold | One-shot build of the fire-universe parquet (no agent deps). |
| `strategy_lab/meta_classifier/hybrid_feature_join.py` | scaffold | Asof-joins RF + TR + TA + F7-RSI + Markov regime onto the fire universe. |
| `strategy_lab/meta_classifier/hybrid_backtest.py` | scaffold | Pure-function harness: `run_hybrid_backtest`, `walk_forward_split`, `gate_search`. |
| `data/v4/canonical/_results/hybrid_fire_universe_5m.parquet` | output | Fires × fills (5m, all offsets). |
| `data/v4/canonical/_results/hybrid_fire_universe_15m.parquet` | output | Fires × fills (15m, all offsets). |
| `data/v4/canonical/_results/hybrid_features_5m.parquet` | output (post-agents) | Universe + joined feature columns. |
| `data/v4/canonical/_results/hybrid_features_15m.parquet` | output (post-agents) | Universe + joined feature columns. |

## Schema — `hybrid_fire_universe_{tf}.parquet`

One row per `(asset, slug, fire_offset_s)`.

| Column | Type | Notes |
|--------|------|-------|
| `asset` | str | 'BTC'/'ETH'/'SOL' |
| `slug` | str | canonical Polymarket slug |
| `tf` | str | '5m' or '15m' |
| `slot_start_us` | int64 | UTC microseconds |
| `slot_end_us` | int64 | slot_start + window_s |
| `ws_s` | int64 | **production anchor** = slug_suffix_s - window_s |
| `fire_offset_s` | int | one of {30..300} for 5m, {60..840} for 15m |
| `fire_us` | int64 | `(slot_start_us + fire_offset_s*1e6)` |
| `strike_price` | float | binance close at slot_start (signal source) |
| `settle_price` | float | binance close at slot_end |
| `outcome` | str | 'Up' or 'Down' (chainlink-derived) |
| `up_ask0`, `dn_ask0` | float | best ask at fire (None if no book) |
| `up_bid0`, `dn_bid0` | float | best bid at fire |
| `up_vwap`, `dn_vwap` | float | L25 walk vwap for $25 notional |
| `up_shares`, `dn_shares` | float | shares purchased |
| `up_usd`, `dn_usd` | float | usd notional spent |
| `up_fill_ok`, `dn_fill_ok` | bool | True if `fill_at_book` returned a valid fill (passes spread filter + min book staleness) |
| `vwap_since_open_bps` | float | binance VWAP-since-slot-open dev, bps |
| `mag_ratio` | float | `|ret_2m_at_ws| / prod_q90` (production-mimic) |

Notes:
- L25 fills use `engine_v2.fill_at_book` with `LegacyConfig()` (2%-on-profit fee
  model — matches production per CLAUDE.md 2026-05-22 reconciliation).
- Spread filter: 0.02 for BTC/ETH, 0.025 for SOL.
- `mag_ratio` is computed via the hourly `prod_q90` from
  `_results/prod_q90_calibration/hourly_thresholds.parquet` (lookback 14d,
  hourly anchors). Rows where no q90 is available yet leave `mag_ratio = NaN`.

## Schema — `hybrid_features_{tf}.parquet`

= fire-universe columns ∪ joined feature columns.

| Source | Prefix | Examples |
|--------|--------|---------|
| `ta_indicators_1s.parquet` | (none) | `ema_5..ema_100`, `ribbon_*`, `stoch_*`, `bb_*`, `mfi_*`, `cci_*` |
| `range_filter_1s.parquet` | `rf_` | (per agent A schema — TBD) |
| `traders_reality_1s.parquet` | `tr_` | (per agent B schema — TBD) |
| F7 RSI computed inline | (none) | `f7_rsi_at_ws` — anchored at `ws_s`, NOT fire_us |
| Markov M1V snapshot | (none) | `regime_w20_*_*`, `pass_w20_*_*` |

Asof-join semantics: `direction='backward'`, `tolerance=30s` per asset on
`fire_us` vs panel `ts_us`. If a panel hasn't covered the slot yet, that row's
joined columns are NaN — never silently pulled from a stale snapshot.

## Backtest harness usage

```python
import pandas as pd
import sys
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global")
from strategy_lab.meta_classifier.hybrid_backtest import (
    run_hybrid_backtest, walk_forward_split, gate_search,
)
from strategy_lab.engine_v2 import LegacyConfig

fu = pd.read_parquet(r"data\v4\canonical\_results\hybrid_features_5m.parquet")

def rule(r):
    if not (pd.notna(r.get("mag_ratio")) and r.get("mag_ratio", 0) >= 1.0):
        return None
    if pd.notna(r.get("f7_rsi_at_ws")):
        if r["f7_rsi_at_ws"] > 55: return "UP"
        if r["f7_rsi_at_ws"] < 45: return "DOWN"
    return None

train, test = walk_forward_split(fu, train_days=20, test_days=8)
res_test = run_hybrid_backtest(test, None, rule, LegacyConfig(), name="f7_test_oos")
print(res_test["summary"])

# Gate search example — try every 2^K AND-conjunction of boolean cols.
fu["g_ribbon_up"]  = (fu["ribbon_color"] == 1).astype("int8")
fu["g_stoch_low"]  = (fu["stoch_k_60s"] < 30).astype("int8")
fu["g_rsi_ok"]     = (fu["f7_rsi_at_ws"] > 50).astype("int8")
# (caller is responsible for adding a `pnl` column to fu — usually from a
# previous run_hybrid_backtest output that you merge back onto fu by slug)
# top = gate_search(fu_with_pnl, ["g_ribbon_up", "g_stoch_low", "g_rsi_ok"])
```

## Critical conventions (REPEATED FROM CLAUDE.md — DO NOT FORGET)

- **Anchor on `ws_s`, NOT `slot_start`** for F7 RSI and any momo-style ret_2m
  feature. Anchoring on `slot_start` inflates backtest hit-rate by 25–40 pp.
- **Fee model**: `LegacyConfig()` (2%-on-profit-only). Verified against 25,900
  production resolutions on 2026-05-22 — this matches what production
  actually charges for crypto up-down markets, despite the docs claiming a
  fancier `0.07 × p × (1-p)` curve.
- **Outcome truth** = `outcome` column from `load_resolutions()` (chainlink-derived).
- **Books are 1Hz subsampled** by `load_orderbook_l25_streaming(subsample_1hz=True)`
  to bound RAM. We pre-cache fills here so backtests never hit the 2.7GB BTC
  L25 parquet again.

## Open dependencies (waiting on parallel agents)

- `data/v4/canonical/_results/range_filter_1s.parquet` — agent A output. Until
  this exists, `hybrid_feature_join.py` will print "panel missing" and skip
  the RF join (no error). Backtest harness still runs without RF columns.
- `data/v4/canonical/_results/traders_reality_1s.parquet` — agent B output. Same.

Once either panel lands, just re-run `python strategy_lab/meta_classifier/hybrid_feature_join.py`
to refresh `hybrid_features_{5m,15m}.parquet`. No rebuild of the fire universe
needed.
