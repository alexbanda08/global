# TV Agent Implementation Spec — `confluence_silver_v1`

**Recipient:** TV agent (Claude operating `/opt/tradingvenue` on VPS3 = `185.190.143.7`)
**Author:** Strategy lab (laptop)
**Date:** 2026-05-07
**Status:** PAPER-ONLY until promotion criteria met (§9)

## Changelog

- **2026-05-07 v1.1** — Drop ETH_15m (validation under sign-aligned classifier showed it destroys alpha; full universe loses with 98.3% confidence — see `SILVER_VALIDATION_FINAL_2026_05_07.md`). Add 4 Cyclops infra mandates: (1) timed risk pause (`RISK_PAUSE_MODE=hard`), (2) tier-flow-through to position dict, (3) SKIP on feature exception (no fallback), (4) clean startup with no aggregated state cache. Tighter promotion criteria. SOL-only.
- **2026-05-07 v1.0** — Initial spec (SOL+ETH_15m).

---

## Same-signal lesson (read before implementing)

> **Cyclops 2026-05 update:** the original Cyclops bot lifted live WR from **55% → 68%** on the SAME signal stack — the gain came from infrastructure discipline, not strategy changes. The 4 fixes (timed risk pause, tier-flow-through, skip-on-vote-exception, clean startup) are MANDATORY in this spec for the same reason. The strategy is already validated; the question is whether our infra executes it faithfully. See `CYCLOPS_UPDATE_COMPARISON_2026_05_07.md` for the full comparison.

---

## 1. Executive Summary

- **What it does:** Adds a second-opinion filter on top of existing momo signal. Before placing a momo buy, it computes two independent confirmation scores — FLOW (order-book + trade pressure) and STRUCTURE (BTC trend + S/R proximity + regime) — and only fires if both agree with the momo direction at SILVER tier thresholds (sign-aligned with held side).
- **Why:** Backtest on Apr–May 2026 universe (1605 momo fires) shows SOL SILVER hit 100% (n=8, mean +$4.08/trade, total +$32.62) vs baseline momo SOL -$0.40/trade. SILVER is a rare high-conviction subset that turns SOL's negative-edge baseline into a positive sub-strategy.
- **Why SOL only (NOT BTC/ETH):** Under signed-alignment validation, ETH_15m and BTC SILVER LOSE money. Full-universe SILVER (BTC+ETH+SOL) loses with 98.3% confidence in bootstrap CI. Only SOL holds up — likely because baseline momo SOL is already a negative-edge cell (anti-edge inversion territory) where struct+flow alignment catches the rare directional wins.
- **Expected edge (SOL only):** SOL_5m SILVER ≈ +$3.5/trade, SOL_15m SILVER ≈ +$5/trade, ~17 picks/30d → ~11 fills/30d after spread filter. **Breakeven hit rate is 86.0%** — only 1pp cushion under regression to baseline. Sample underpowered (n=8 over 14 days) — paper phase accumulates n≥80 + ≥5 observed losses before any live transition.
- **Excluded cells:** BTC_5m, BTC_15m, ETH_5m, ETH_15m — SILVER showed no positive edge on those; hard-exclude via env flag, not just config.
- **Coexistence:** runs alongside all 18 baseline momo sleeves. Does NOT replace them. Both fire independently on the same markets.

---

## 2. Sleeve Config

### 2a. Sleeve ID Naming

Two sleeves, SOL only. Exit policy is HOLD (no hedge/sell for paper phase).

```
poly_updown_sol_5m_confluence_silver_v1
poly_updown_sol_15m_confluence_silver_v1
```

Pattern: `poly_updown_{asset}_{tf}_confluence_silver_v1`. ETH_15m removed in v1.1; do not add it back without re-validation.

### 2b. Environment Variables

Add to `/etc/tradingvenue/.env`. Existing momo vars are unchanged.

```bash
# ── Master enable (single toggle to kill both sleeves) ───────────────────────
TV_POLY_CONFLUENCE_SILVER_ENABLED=true

# ── Per-cell enables (surgical pause without restart) ────────────────────────
TV_POLY_CONFLUENCE_SILVER_SOL_5M_ENABLED=true
TV_POLY_CONFLUENCE_SILVER_SOL_15M_ENABLED=true

# ── Explicitly excluded cells (hard block — do not enable these) ─────────────
# BTC_5M, BTC_15M, ETH_5M, ETH_15M are excluded; no env var for them by design.
# ETH_15M was excluded in v1.1 after sign-aligned validation showed negative edge.

# ── Tier thresholds (mirror tier_classifier.py constants; change here if re-tuning) ──
TV_POLY_CONFLUENCE_SILVER_STRUCT_MIN=0.30
TV_POLY_CONFLUENCE_SILVER_FLOW_MIN=0.40

# ── Sizing ───────────────────────────────────────────────────────────────────
TV_POLY_CONFLUENCE_SILVER_SIZE_PCT=0.015   # 1.5% of bankroll (Cyclops SILVER)
TV_POLY_CONFLUENCE_SILVER_BANKROLL_USD=1250  # set to actual paper bankroll
TV_POLY_CONFLUENCE_SILVER_NOTIONAL_USD=18.75 # = 0.015 * 1250; pre-computed for clarity

# ── Dynamic L1 cap (reuses momo_v2 per-asset params; share the same config) ──
TV_POLY_DYNAMIC_STAKE_ENABLED=true          # already set for momo; verify still true
# SOL L1 skip threshold: SKIP_IF_L1_USD_BELOW["sol"] = 3.0 (from momo code)
# SOL max walk slip: MAX_WALK_SLIP_BPS["sol"] = 300

# ── Max concurrent positions ─────────────────────────────────────────────────
TV_POLY_CONFLUENCE_SILVER_MAX_CONCURRENT=2  # 1 per cell; 2 total across SOL_5m + SOL_15m

# ── Data freshness gates (reject stale book/kline before firing) ─────────────
TV_POLY_CONFLUENCE_SILVER_OB_STALE_MAX_S=60   # Polymarket OB snapshot max age seconds
TV_POLY_CONFLUENCE_SILVER_KLINE_STALE_MAX_S=60 # Binance kline max age seconds

# ── Risk pause (Cyclops mandate #1: hard pause on DD/daily-loss with timer) ──
CONFLUENCE_RISK_PAUSE_MODE=hard          # hard | soft | off; default hard
CONFLUENCE_RISK_PAUSE_MIN=15             # minutes — hold pause after trigger
CONFLUENCE_DAILY_LOSS_LIMIT_PCT=2.0      # % of bankroll
CONFLUENCE_MAX_DRAWDOWN_PCT=5.0          # % from session peak
# `off` is for debugging only and MUST never be set in production .env without
# operator approval logged in the deploy ticket.

# ── Register new strategy mode ───────────────────────────────────────────────
# Append to comma-list (do NOT replace existing entries):
TV_POLY_STRATEGY_MODES=...,momo,momo_v2,confluence_silver_v1
```

### 2c. Kill-Switch (Revert to Baseline Momo Within 60 Seconds)

```bash
# On VPS3 — disable confluence sleeve without touching momo:
sed -i 's/TV_POLY_CONFLUENCE_SILVER_ENABLED=true/TV_POLY_CONFLUENCE_SILVER_ENABLED=false/' \
    /etc/tradingvenue/.env
systemctl reload tradingvenue   # hot-reload if supported; else:
systemctl restart tradingvenue
```

Baseline momo continues firing. Confluence trades already open remain open until resolution (no forced exit).

---

## 3. Signal Flow

One evaluation per market slot, fired at `ws + 120s` (same dispatch phase as baseline momo `t_plus_120`).

```python
# ── Step 1: Momo gate (identical to baseline momo) ───────────────────────────
ws_s = window_start_unix          # int seconds
btc_at_t120 = fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', ws_s + 120,
                                 source='binance-spot-ws')  # end-time-indexed
btc_at_open  = fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', ws_s,
                                 source='binance-spot-ws')
ret_2m = log(btc_at_t120 / btc_at_open)

if abs(ret_2m) < abs_ret_2m_threshold:   # rolling 14d q90 of |ret_2m|
    log_skip(reason='momo_gate_miss'); return

signal_dir = 'Up' if ret_2m > 0 else 'Down'  # 1 = Up, 0 = Down

# ── Step 2: Check master + per-cell enable flags ─────────────────────────────
if not TV_POLY_CONFLUENCE_SILVER_ENABLED: return
if not TV_POLY_CONFLUENCE_SILVER_{ASSET}_{TF}_ENABLED: return

# ── Step 3: Compute FLOW score at ws + 120s ──────────────────────────────────
query_ts_us = (ws_s + 120) * 1_000_000

ob_rows = query_orderbook_snapshots_v2(
    slug=slug, side=signal_dir,    # only the held-side book
    ts_us_le=query_ts_us,          # strict asof: latest snapshot ≤ query_ts_us
    limit=1,                       # most recent row only
)
if not ob_rows or ob_rows[0].timestamp_us < query_ts_us - OB_STALE_MAX_S * 1e6:
    log_skip(reason='ob_stale'); return

trade_rows = query_trades_v2(
    slug=slug, side=signal_dir,
    ts_us_window=(query_ts_us - 60_000_000, query_ts_us)  # last 60s of trades
)

# Pure functions from features.py (no I/O):
bp, bs, ap, as_ = _book_arrays_from_row(ob_rows[0])
book_feats = compute_book_features(bp, bs, ap, as_)
trade_feats = compute_trade_features(trade_rows, query_ts_us, signal_dir)
flow_score  = compute_flow_score(book_feats, trade_feats)

# Direction alignment: flow_score > 0 means bid pressure (favors Up).
# If signal_dir == 'Down', negate flow_score before threshold comparison.
aligned_flow = flow_score if signal_dir == 'Up' else -flow_score

# ── Step 4: Compute STRUCTURE score at ws ────────────────────────────────────
# STRUCTURE is side-agnostic (one value per ws_unix). Sign encodes market bias.
struct_score = lookup_struct_score_cache(slug=slug, ws_unix=ws_s)
# cache = pre-rolled parquet refreshed every 15m by background job (see §4)
# If cache miss or kline lag > KLINE_STALE_MAX_S: log_skip('struct_stale')

# Direction alignment: struct_score > 0 = uptrend conditions.
aligned_struct = struct_score if signal_dir == 'Up' else -struct_score

# ── Step 5: GUARD blocks ─────────────────────────────────────────────────────
guard_blocks = []
entry_price = ob_rows[0].asks[0].price   # L1 ask

if entry_price < 0.35 or entry_price > 0.65:
    guard_blocks.append('guard_extreme_price')
elapsed_s = ws_s + 120 - slot.market_open_unix  # seconds since market open
btc_move_usd = abs(btc_at_t120 - btc_at_open) * btc_price_usd
if elapsed_s < 90 and btc_move_usd < 5:
    guard_blocks.append('guard_dead_market')
if slot.remaining_seconds < 60:
    guard_blocks.append('guard_min_time_to_close')
# guard_counter_trend and guard_choppiness: defer to Phase 2 GUARD module;
# for v1 paper only implement guard_extreme_price + guard_min_time_to_close

# ── Step 6: Tier classifier ──────────────────────────────────────────────────
from Tradingvenue.backend.app.features.tier_classifier import classify
from Tradingvenue.backend.app.features.tier_classifier import (
    SILVER_STRUCT_MIN,   # 0.30
    SILVER_FLOW_MIN,     # 0.40
)

tier_result = classify(
    structure_score=aligned_struct,
    flow_score=aligned_flow,
    trigger_active=None,   # TRIGGER layer not built; None → SILVER still fires
    guard_blocks=guard_blocks,
)
# NOTE: passing trigger_active=None still allows SILVER because SILVER does NOT
# require trigger. The classify() function only skips on None for missing_features
# when structure_score or flow_score is None. If both scores are valid, SILVER
# fires without trigger. Confirm this behavior in tier_classifier.py line 64:
#   "if structure_score is None or flow_score is None or trigger_active is None"
# → trigger_active=None WILL cause a SKIP. Therefore: pass trigger_active=True
# unconditionally for v1 (TRIGGER layer deferred — treat as always-fired).
tier_result = classify(
    structure_score=aligned_struct,
    flow_score=aligned_flow,
    trigger_active=True,   # deferred; treated as always-passed in v1
    guard_blocks=guard_blocks,
)

if tier_result['tier'] != 'SILVER':
    log_event(kind='poly_updown_confluence_signal',
              data={**signal_ctx, 'tier': tier_result['tier'],
                    'skip_reasons': tier_result['skip_reasons']})
    return  # SKIP

# ── Step 7: Dynamic L1 cap → compute actual stake ────────────────────────────
target_stake = BANKROLL_USD * SILVER_SIZE_PCT   # e.g. 1250 * 0.015 = $18.75

own_book = fetch_own_book(slug, signal_dir)     # re-fetch at entry time
actual_stake, dynamic_cap_applied, skip_reason = find_max_stake_within_slip(
    own_book['asks'],
    max_slip_bps=MAX_WALK_SLIP_BPS[asset],      # sol=300, eth=200
    l1_skip_usd=SKIP_IF_L1_USD_BELOW[asset],   # sol=3.0, eth=5.0
    target_usd=target_stake,
)
if actual_stake is None:
    log_event(kind='poly_updown_confluence_signal',
              data={**signal_ctx, 'tier': 'SKIP', 'skip_reasons': [skip_reason]})
    return

# ── Step 8: Place paper buy ──────────────────────────────────────────────────
vwap = book_walk_vwap(own_book['asks'], actual_stake)
await paper_executor.place_buy(
    token_id=slot.held_token_id,
    qty=actual_stake / vwap,
    limit_px=vwap * 1.01,
    sleeve_id=f'poly_updown_{asset}_{tf}_confluence_silver_v1',
    paper=True,
)

# ── Step 9: Log entry event ──────────────────────────────────────────────────
log_event(kind='poly_updown_confluence_signal', data=build_signal_event(...))
```

**Key behavioral difference from GOLD:** SILVER does not require `trigger_active=True` in the real classifier. For v1, we pass `trigger_active=True` unconditionally so the `missing_features` guard doesn't block. When TRIGGER is built (future), change to actual trigger result.

### 3a. Cyclops Mandate — SKIP on feature exception (NO FALLBACK)

If FLOW or STRUCTURE compute throws ANY exception — DB timeout, OB lag, missing kline, type error, parquet read error, anything — the sleeve MUST skip the market evaluation. **DO NOT fall back to baseline momo. DO NOT use stale features. DO NOT use heuristic defaults.** The Cyclops author identified this exact pattern as costing 8-12 negative-EV trades per day on their bot.

```python
# Wrap each layer compute in a top-level try/except. On exception:
try:
    aux['flow_score'] = await _compute_flow_score_online(slug, signal_dir, ws_s)
except Exception as e:
    log_event(kind='poly_updown_confluence_skip',
              data={'slug': slug, 'sleeve': sleeve_id,
                    'skip_reason': 'feature_exception',
                    'layer': 'flow',
                    'exception_type': type(e).__name__,
                    'exception_msg': str(e)[:200]})
    return  # SKIP — do NOT fire the confluence sleeve

try:
    aux['struct_score'] = _get_struct_score_from_cache(asset, ws_s)
except Exception as e:
    log_event(kind='poly_updown_confluence_skip',
              data={'slug': slug, 'sleeve': sleeve_id,
                    'skip_reason': 'feature_exception',
                    'layer': 'structure',
                    'exception_type': type(e).__name__,
                    'exception_msg': str(e)[:200]})
    return  # SKIP
```

A None or stale value (kline lag > 60s, OB stale > 60s, cache miss) is also a SKIP, distinct from `feature_exception`:

```python
if aux['struct_score'] is None or struct_cache_age_s > KLINE_STALE_MAX_S:
    log_event(kind='poly_updown_confluence_skip',
              data={'slug': slug, 'sleeve': sleeve_id,
                    'skip_reason': 'struct_stale_or_missing'})
    return
```

**Critical:** the baseline momo sleeve continues to fire normally; only the confluence sleeve skips. The two sleeves are independent.

### 3b. Cyclops Mandate — Tier flows through to position dict

When the order fills and the slot/position object is built, the `tier` field MUST be copied from the signal. The Cyclops author's bot was managing every trade as `UNKNOWN` because the position dict didn't carry the tier — exit rules ran on the wrong logic and MICRO trades that should close early were held to expiry.

```python
# REQUIRED:
position = {
    'sleeve_id':         sleeve_id,
    'tier':              sig.get('tier', 'UNKNOWN'),  # copy from signal
    'fair_prob':         sig.get('fair_prob'),
    'min_edge_required': sig.get('min_edge_required', 0.015),
    'flow_score':        sig.get('flow_score'),
    'struct_score':      sig.get('struct_score'),
    # ... all other fields
}
# DO NOT silently default to UNKNOWN — log an error if tier is missing.
if position['tier'] == 'UNKNOWN':
    log_event(kind='poly_updown_confluence_error',
              data={'slug': slug, 'sleeve': sleeve_id,
                    'error': 'tier_missing_in_signal'})
```

For `confluence_silver_v1` v1, all entries are tier='SILVER' by construction (SKIP/GOLD/BRONZE never fire — see §3 step 6 for tier_result usage). UNKNOWN should never appear; if it does, that's a bug in the dispatch wiring.

---

## 4. Production Data Sources

All tables are on VPS3 PostgreSQL, database `storedata`.

### 4a. FLOW Features

| Feature | Source table | Key columns | Query logic |
|---|---|---|---|
| `flow_imb_l1..l25` | `orderbook_snapshots_v2` | `slug`, `side`, `timestamp_us`, `bids_json`, `asks_json` | `SELECT * FROM orderbook_snapshots_v2 WHERE slug=$1 AND side=$2 AND timestamp_us <= $3 ORDER BY timestamp_us DESC LIMIT 1` |
| `flow_cvd_1m`, `flow_cvd_5m` | `trades_v2` | `slug`, `side`, `timestamp_us`, `price`, `size`, `aggressor_side` | `SELECT * FROM trades_v2 WHERE slug=$1 AND side=$2 AND timestamp_us BETWEEN $3-60e6 AND $3` |
| `flow_aggressor_ratio_30s` | `trades_v2` | same | same query, window = last 30s |
| `flow_momentum_30s` | `trades_v2` | `price` | `first(price)` and `last(price)` in 30s window |
| `flow_depth_l5/l10/l25_usd` | `orderbook_snapshots_v2` | `asks_json` L1-L25 levels | computed from same OB snapshot row |

The production controller already has helpers for both tables (used in existing momo). Reuse `_fetch_ob_snapshot(slug, side, ts_us)` and `_fetch_trades(slug, side, start_us, end_us)` from `polymarket_updown.py`.

Freshness gate: reject if `timestamp_us < (ws_s + 120) * 1e6 - OB_STALE_MAX_S * 1e6`.

Lag check on deploy:
```sql
SELECT max(now() - to_timestamp(timestamp_us / 1e6)) AS lag
FROM orderbook_snapshots_v2 WHERE slug LIKE 'sol-%';
```
Should be < 60s. Alert if > 120s.

### 4b. STRUCTURE Features — Pre-Computed Parquet Cache

STRUCTURE computation is CPU-bound (240 min of 1h kline regression per call). Compute offline on a rolling schedule; cache to fast-lookup storage.

| Feature | Source table | Key columns | Notes |
|---|---|---|---|
| `struct_btc_trend_1h_slope` | `binance_klines_v2` | `symbol_id='BINANCE_SPOT_BTC_USDT'`, `timeframe='1MIN'`, `source='binance-spot-ws'`, `time_period_end_us` | 60-bar window; `compute_trend_slopes(btc_kline, ws_unix_arr, minutes_1h=60)` |
| `struct_btc_trend_4h_slope` | `binance_klines_v2` | same | 240-bar window; `compute_trend_slopes(..., minutes_4h=240)` |
| `struct_dist_to_resistance_bps` | `binance_klines_v2` | per-asset 1MIN closes | `extract_swings(kline, window=2)` on prior 5d; `nearest_distance_bps(swings, ws_unix, lookback_days=5)` |
| `struct_dist_to_support_bps` | `binance_klines_v2` | same | same |
| `struct_regime` | derived | slope_1h + realized_vol_1h | `classify_regime_series(slope_arr, vol_arr, hysteresis_bars=5)` → `DEFAULT_HYSTERESIS_BARS=5` |
| `struct_score` | derived | all above | `_compute_struct_score(slope_1h, dist_resist, dist_support, regimes)` |

`struct_score` composite formula (from `build_structure.py::_compute_struct_score`):
```
score = clip(
    0.5 * sign(slope_1h)
    + 0.3 * (dist_support - dist_resistance) / max_dist_normalization
    + 0.2 * regime_factor(regime),   # volatile=-0.3, sideways=0.0, trend=+0.3
    -1.0, +1.0
)
```

**Online approach recommendation (open question §11-A):** Pre-roll a parquet shard every 15 minutes from a background cron job on VPS3. Serve struct_score via a lightweight dict lookup keyed by `(asset, ws_unix_bucket)`. The controller reads from this cache dict at signal time (sub-millisecond). Background job re-runs `build_structure.py` with `--incremental --lookback 6h` flag every 15m.

Query for freshness of kline feed (must be < 60s lag):
```sql
SELECT now() - to_timestamp(time_period_end_us / 1e6) AS kline_lag
FROM binance_klines_v2
WHERE symbol_id='BINANCE_SPOT_BTC_USDT' AND timeframe='1MIN'
  AND source='binance-spot-ws'
ORDER BY time_period_end_us DESC LIMIT 1;
```

---

## 5. Implementation Files

All paths relative to `/opt/tradingvenue/` on VPS3.

| New File | What Goes In It |
|---|---|
| `backend/app/strategies/polymarket/confluence_silver_v1.py` | `ConfluenceSilverV1Strategy` class; reads `aux['flow_score']`, `aux['struct_score']`, `aux['tier']` populated by the controller at `t_plus_120` dispatch; calls `classify()` and returns `SignalResult`; implements the per-cell enable-flag check and guard blocks listed in §3. Mirrors shape of `momo_v2.py` (same base class `PolymarketBinaryStrategy`). |
| `backend/app/features/flow_score.py` | Online version of `strategy_lab/confluence/flow/features.py`. Exports: `compute_book_features(bp, bs, ap, as_) -> dict`, `compute_trade_features(trades_df, query_ts_us, outcome_side) -> dict`, `compute_flow_score(book_features, trade_features) -> float`. Constants: `_FLOW_WEIGHTS = {"imb_l5": 0.30, "cvd_1m_norm": 0.25, "aggressor_centered": 0.20, "momentum_30s_norm": 0.15, "imb_l10": 0.10}`, `_CVD_CAP_USD = 5000.0`, `_MOMENTUM_CAP = 0.02`. Copy 1:1 from lab file; no logic changes. |
| `backend/app/features/struct_score.py` | Cache loader for pre-rolled STRUCTURE parquet. Exports: `load_struct_cache(parquet_path) -> dict[(asset, ws_unix_bucket), float]`, `get_struct_score(cache, asset, ws_unix) -> float | None`. The `ws_unix_bucket` is rounded to the nearest 15m boundary. Also exports `refresh_struct_cache(kline_df, universe_ws_list) -> dict` wrapping `build_structure._compute_struct_score` for the background cron job. |
| `backend/app/features/tier_classifier.py` | Mirror of `strategy_lab/confluence/tier_classifier.py` 1:1. Exports: `classify(structure_score, flow_score, trigger_active, guard_blocks=()) -> TierResult`, `stake_usd(tier_result, bankroll_usd) -> float`. Constants: `SILVER_STRUCT_MIN=0.30`, `SILVER_FLOW_MIN=0.40`, `SILVER_SIZE_PCT=0.015`, `SILVER_FAIR_PROB=0.64`. Do not modify — changes must be mirrored from the lab file. |

### Controller Changes (in `polymarket_updown.py`)

In the `t_plus_120` dispatch block, after the momo ret_2m computation and BEFORE placing the momo order, insert confluence evaluation for the 3 enabled cells:

```python
if TV_POLY_CONFLUENCE_SILVER_ENABLED and asset in ('sol', 'eth') and tf in ('15m',) \
        or (asset == 'sol' and tf == '5m'):
    aux['flow_score']  = await _compute_flow_score_online(slug, signal_dir, ws_s)
    aux['struct_score'] = _get_struct_score_from_cache(asset, ws_s)
    aux['tier'] = classify(
        structure_score=_align(aux['struct_score'], signal_dir),
        flow_score=_align(aux['flow_score'], signal_dir),
        trigger_active=True,   # TRIGGER deferred
        guard_blocks=_compute_guards(slot, entry_price, btc_move_usd, elapsed_s),
    )
```

The confluence sleeve fires its own independent order (separate `sleeve_id`). It does NOT suppress or modify the baseline momo order.

---

## 6. Telemetry Contract

All events logged to `trading.events` table on VPS3 (same Postgres, same table as existing `poly_updown_signal`).

### 6a. Entry Event

```json
{
  "kind": "poly_updown_confluence_signal",
  "at": "<ISO8601 UTC>",
  "data": {
    "sleeve_id": "poly_updown_sol_5m_confluence_silver_v1",
    "slug": "sol-updown-5m-1746576000",
    "symbol": "SOL",
    "tf": "5m",
    "ws_unix": 1746576000,
    "signal_dir": "Up",
    "ret_2m": 0.00312,
    "abs_ret_2m_threshold": 0.00280,

    "flow_imb_l1": 0.42,
    "flow_imb_l5": 0.38,
    "flow_imb_l10": 0.31,
    "flow_imb_l25": 0.27,
    "flow_bid_max_size_l10_usd": 142.5,
    "flow_depth_l5_usd": 87.3,
    "flow_depth_l10_usd": 210.0,
    "flow_depth_l25_usd": 480.0,
    "flow_cvd_1m": 3200.0,
    "flow_cvd_5m": 8100.0,
    "flow_aggressor_ratio_30s": 0.71,
    "flow_momentum_30s": 0.0041,
    "flow_score": 0.47,
    "flow_score_aligned": 0.47,

    "struct_btc_trend_1h_slope": 0.00021,
    "struct_btc_trend_4h_slope": 0.00008,
    "struct_dist_to_resistance_bps": 85.0,
    "struct_dist_to_support_bps": 210.0,
    "struct_regime": "trend",
    "struct_score": 0.34,
    "struct_score_aligned": 0.34,

    "tier": "SILVER",
    "fair_prob": 0.64,
    "skip_reasons": [],

    "guard_extreme_price_fired": false,
    "guard_dead_market_fired": false,
    "guard_min_time_to_close_fired": false,

    "target_stake_usd": 18.75,
    "actual_stake_usd": 16.20,
    "dynamic_cap_applied": true,
    "l1_usd": 18.4,
    "l1_size": 120.5,
    "l1_price": 0.613,
    "walk_vwap": 0.618,
    "walk_slip_bps": 82,

    "entry_price": 0.618,
    "entry_qty": 26.2,
    "mode": "paper",
    "ob_snapshot_age_ms": 340,
    "struct_cache_age_s": 480
  }
}
```

### 6b. Resolution Event

```json
{
  "kind": "poly_updown_confluence_resolution",
  "at": "<ISO8601 UTC>",
  "data": {
    "sleeve_id": "poly_updown_sol_5m_confluence_silver_v1",
    "slug": "sol-updown-5m-1746576000",
    "tier": "SILVER",
    "pnl_usd": 9.84,
    "hit": true,
    "entry_price": 0.618,
    "exit_price": 1.00,
    "hold_duration_s": 120,
    "was_paper": true,
    "dynamic_cap_applied": true,
    "actual_stake_usd": 16.20
  }
}
```

### 6c. Skip Event (Cyclops mandate — full visibility into what the sleeve filtered)

```json
{
  "kind": "poly_updown_confluence_skip",
  "at": "<ISO8601 UTC>",
  "data": {
    "sleeve_id": "poly_updown_sol_5m_confluence_silver_v1",
    "slug": "sol-updown-5m-1746576000",
    "skip_reason": "feature_exception | feature_stale | tier_skip | risk_paused | dynamic_cap_failed | l1_too_thin | spread_too_wide",
    "layer": "flow | structure | classifier | risk | sizing",
    "exception_type": "<class name if exception>",
    "exception_msg": "<truncated to 200 chars if exception>",
    "tier": "SKIP | GOLD | BRONZE",
    "skip_reasons_inner": ["guard_extreme_price", "missing_features"],
    "flow_score": 0.18,
    "struct_score": -0.05
  }
}
```

Every code path that does not fire MUST emit a skip event. The operator must be able to answer "why did this market not fire?" by querying `kind='poly_updown_confluence_skip'`.

### 6d. Risk-Pause Event (Cyclops mandate)

```json
{
  "kind": "poly_updown_confluence_risk_pause",
  "at": "<ISO8601 UTC>",
  "data": {
    "trigger": "max_drawdown | daily_loss",
    "current_value_pct": 5.4,
    "threshold_pct": 5.0,
    "pause_until_unix": 1746579600,
    "pause_min": 15,
    "mode": "hard"
  }
}
```

A single pause event covers all 2 sleeves (master kill). Resume is auto on timer expiry — no resume event; query `pause_until_unix < now()` to determine current state.

### 6e. Tier-Missing Error Event (Cyclops mandate — should never happen, but log if it does)

```json
{
  "kind": "poly_updown_confluence_error",
  "at": "<ISO8601 UTC>",
  "data": {
    "error": "tier_missing_in_signal | feature_compute_returned_none",
    "sleeve_id": "...",
    "slug": "...",
    "context": "..."
  }
}
```

---

## 6f. Session State Hygiene (Cyclops mandate)

**FORBIDDEN persistence files** for this sleeve:
- `confluence_silver_state.json` — would cache aggregated metrics
- `confluence_silver_session.json` — would persist win streak, rolling WR
- `confluence_silver_decisions.csv` — would persist recent decision history
- Any file under `/var/lib/tradingvenue/confluence_silver_*` other than per-trade audit logs

**REQUIRED behavior:**
- On controller restart, the sleeve initializes with **zero** in-memory state for KPIs.
- All KPIs (hit rate, mean P&L, win streak, rolling WR, recent decision history) are recomputed live from `trading.events` queries on demand. Never persist aggregated derived metrics to disk.
- The single source of truth is `trading.events` — every entry/skip/resolution event is logged there. KPIs are pure functions of the event log.
- This is the Cyclops fix #4: their bot bled stale `session_stats.json` data across restarts; for 2-3 hours after each restart it anchored on history that no longer applied.

If the controller code currently has a `_load_session_stats()` or similar function for any other sleeve, the confluence sleeve MUST opt out and not call it. Use a clean per-restart KPI snapshot computed from events.

---

## 7. Dashboards / Queries

Pin these to the VPS3 Postgres dashboard (or Grafana if connected).

### Q1 — Per-day per-cell: fires, hit rate, mean PnL, sum PnL

```sql
SELECT
  DATE_TRUNC('day', at) AS day,
  data->>'symbol'   AS symbol,
  data->>'tf'       AS tf,
  COUNT(*)          AS n_fires,
  ROUND(AVG((data->>'hit')::boolean::int) * 100, 1) AS hit_pct,
  ROUND(AVG((data->>'pnl_usd')::numeric), 2)        AS mean_pnl,
  ROUND(SUM((data->>'pnl_usd')::numeric), 2)        AS sum_pnl
FROM trading.events
WHERE kind = 'poly_updown_confluence_resolution'
  AND sleeve_id LIKE '%confluence_silver_v1'
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 2, 3;
```

### Q2 — Skip reason breakdown (what filtered potential trades)

```sql
SELECT
  UNNEST(ARRAY(SELECT json_array_elements_text(data->'skip_reasons'))) AS skip_reason,
  COUNT(*) AS n
FROM trading.events
WHERE kind = 'poly_updown_confluence_signal'
  AND sleeve_id LIKE '%confluence_silver_v1'
  AND data->>'tier' = 'SKIP'
  AND at > now() - interval '7 days'
GROUP BY 1
ORDER BY 2 DESC;
```

### Q3 — Tier breakdown (SILVER vs SKIP rate)

```sql
SELECT
  data->>'symbol' AS symbol,
  data->>'tf'     AS tf,
  data->>'tier'   AS tier,
  COUNT(*)        AS n,
  ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (PARTITION BY data->>'symbol', data->>'tf'), 1) AS pct
FROM trading.events
WHERE kind = 'poly_updown_confluence_signal'
  AND sleeve_id LIKE '%confluence_silver_v1'
  AND at > now() - interval '7 days'
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;
```

### Q4 — Dynamic cap frequency and impact

```sql
SELECT
  data->>'symbol'                        AS symbol,
  COUNT(*)                               AS n_fires,
  SUM(CASE WHEN (data->>'dynamic_cap_applied')::boolean THEN 1 ELSE 0 END) AS n_capped,
  ROUND(AVG((data->>'target_stake_usd')::numeric), 2) AS avg_target,
  ROUND(AVG((data->>'actual_stake_usd')::numeric), 2) AS avg_actual
FROM trading.events
WHERE kind = 'poly_updown_confluence_signal'
  AND sleeve_id LIKE '%confluence_silver_v1'
  AND data->>'tier' = 'SILVER'
  AND at > now() - interval '7 days'
GROUP BY 1;
```

### Q5 — Weekly rolling hit-rate vs baseline momo (same cells)

```sql
SELECT
  DATE_TRUNC('week', r.at) AS week,
  r.data->>'symbol'        AS symbol,
  r.data->>'tf'            AS tf,
  'confluence_silver'      AS strategy,
  COUNT(*)                 AS n,
  ROUND(AVG((r.data->>'hit')::boolean::int) * 100, 1) AS hit_pct,
  ROUND(AVG((r.data->>'pnl_usd')::numeric), 2) AS mean_pnl
FROM trading.events r
WHERE r.kind = 'poly_updown_confluence_resolution'
  AND r.sleeve_id LIKE '%confluence_silver_v1'
GROUP BY 1, 2, 3, 4
UNION ALL
SELECT
  DATE_TRUNC('week', r.at),
  r.data->>'symbol', r.data->>'tf', 'momo_baseline',
  COUNT(*),
  ROUND(AVG((r.data->>'hit')::boolean::int) * 100, 1),
  ROUND(AVG((r.data->>'pnl_usd')::numeric), 2)
FROM trading.events r
WHERE r.kind = 'poly_updown_resolution'
  AND r.sleeve_id LIKE 'poly_updown_%_momo_HOLD'
  AND r.data->>'symbol' IN ('SOL', 'ETH')
  AND r.data->>'tf' IN ('5m', '15m')
GROUP BY 1, 2, 3, 4
ORDER BY 1 DESC, 2, 3, 4;
```

---

## 8. Pre-Deploy Checklist

Operator must verify all before flipping `TV_POLY_CONFLUENCE_SILVER_ENABLED=true`.

| # | Check | Command / Verification |
|---|---|---|
| 1 | HL liquidations collector running | `systemctl status storedata-hyperliquid-events-live.service` → active (running) |
| 2 | Polymarket OB collector lag < 60s | Run Q-lag query in §4a. Alert if > 60s, block if > 120s. |
| 3 | Binance kline collector lag < 60s | Run kline lag query in §4b. Alert if > 60s. |
| 4 | Baseline momo sleeves healthy | Run 1b query from `TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md`; must show ≥18 sleeves active in last 24h. |
| 5 | STRUCTURE cache pre-seeded | `ls -lh /opt/tradingvenue/data/struct_cache/latest.parquet` — must exist and be < 30m old. |
| 6 | STRUCTURE background job registered | `crontab -l \| grep build_structure` — must show `*/15 * * * *` entry. |
| 7 | `tier_classifier.py` on VPS3 matches lab | `md5sum /opt/tradingvenue/backend/app/features/tier_classifier.py` vs lab version. Must match. |
| 8 | `TV_POLY_DYNAMIC_STAKE_ENABLED=true` | `grep TV_POLY_DYNAMIC_STAKE_ENABLED /etc/tradingvenue/.env` |
| 9 | No existing momo infra broken | Zero 5xx errors in last 1h: `grep ERROR /var/log/tradingvenue/app.log \| wc -l` → 0. |
| 10 | 24h dry-run complete | Run `TV_POLY_CONFLUENCE_SILVER_ENABLED=true` with `mode=paper` on staging (if VPS3 staging exists) OR shadow-log only for 24h on prod with no order placement before first real paper fire. |

---

## 9. Promotion Criteria (Paper → Live)

Do not promote any cell to live until **all** criteria met for that cell independently.

**v1.1 update:** ETH_15m removed; criteria below apply to SOL_5m and SOL_15m only. Tightened per Cyclops infra lessons + breakeven-sensitivity finding (breakeven hit rate = 86%, only 1pp above baseline).

| Criterion | SOL_5m | SOL_15m |
|---|---|---|
| Minimum paper duration | 6+ weeks continuous | 6+ weeks |
| Minimum n per cell | ≥ 80 SILVER fires | ≥ 80 |
| At least one observed loss | required (so G1 perm test becomes informative) | required |
| Walk-forward windows positive | ≥ 6 of last 8 windows (rolling 5d/2d) | ≥ 6/8 |
| Bootstrap 95% CI lower bound | > +$1/trade | > +$1/trade |
| Live hit rate (after n≥80) | ≥ 88% (1pp above breakeven for safety margin) | ≥ 88% |
| Mean $/trade (paper) | ≥ +$2.00 | ≥ +$2.00 |
| Max drawdown | ≤ 25% of allocated bankroll | same |
| vs baseline momo (same cell) | No stat-sig regression (permutation p > 0.05) | same |
| Dynamic cap frequency | < 50% of fires capped to ≤ 50% of target | same |
| Risk pause not triggered in last 7 days | required | required |

Run weekly stat comparison query (Q5 above). If confluence hit rate drops below baseline momo hit rate with p < 0.05 on a rolling 4-week window, flag for review before promoting.

**Capital ramp post-promotion (per cell, independent):**
- Week 1-2 live: 0.5% × bankroll per trade
- Week 3-4 live: 1.0% if hit rate ≥ 90% so far
- Week 5+ live: 1.5% if all metrics hold

Promotion means: change `mode=paper` to `mode=live` for that cell's sleeve, with size_pct ramp above. Keep other cells in paper until they individually clear criteria. Demotion (live → paper) triggers automatically if any of the above 11 criteria regress below threshold for 2 consecutive weeks.

---

## 10. Rollback Plan

**Target: disable confluence_silver_v1 and revert to baseline momo within 60 seconds.**

### Option A — Master kill (preferred, sub-10s)

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/TV_POLY_CONFLUENCE_SILVER_ENABLED=true/TV_POLY_CONFLUENCE_SILVER_ENABLED=false/' \
   /etc/tradingvenue/.env && systemctl reload tradingvenue"
```

Effect: confluence_silver_v1 sleeves stop evaluating new signals immediately. Existing open positions run to natural resolution. Baseline momo continues unaffected.

### Option B — Per-cell surgical kill (keep 2 cells running, pause 1)

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/TV_POLY_CONFLUENCE_SILVER_SOL_5M_ENABLED=true/TV_POLY_CONFLUENCE_SILVER_SOL_5M_ENABLED=false/' \
   /etc/tradingvenue/.env && systemctl reload tradingvenue"
```

### Option C — Emergency full stop (all strategies, nuclear)

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 "systemctl stop tradingvenue"
```

No new orders placed. Open paper positions orphaned until manual resolution (they are paper — no real capital at risk).

### Rollback Decision Triggers

Initiate rollback immediately if any of:
- Hit rate drops below 70% over any rolling 20-trade window
- Two consecutive losing days (sum PnL negative both days)
- STRUCTURE cache goes stale > 2h (background job failure)
- OB collector lag exceeds 120s for > 30 minutes
- Any bug causing confluence sleeve to fire on excluded cells (BTC_5m, BTC_15m, ETH_5m, ETH_15m)
- `kind='poly_updown_confluence_error'` events appear with `error='tier_missing_in_signal'` (Cyclops mandate #2 violation)
- `feature_exception_skip` rate exceeds 5% of evaluations over any 1-hour window (signals upstream data layer failure)
- Risk pause fires more than once per 24h period (signals model regression or universe shift)

### Rail Wiring (Cyclops mandate — verify before deploy)

The existing 11-rail framework in `Tradingvenue/backend/app/engine/rails/` MUST explicitly enumerate `confluence_silver_v1` sleeves in their target lists. Verify each of the following rails handles confluence sleeves:

| Rail | Path | What it must do for confluence |
|---|---|---|
| `rail_01_per_position_sl.py` | per-position stop-loss | confluence positions are paper; SL is informational, not actuated |
| `rail_03_portfolio_dd_15.py` | 15% portfolio DD | include confluence paper PnL in aggregate DD calc; does NOT pause sleeve (separate trigger) |
| `rail_04_portfolio_dd_25.py` | 25% portfolio DD | same |
| `rail_05_portfolio_dd_30_kill.py` | 30% portfolio DD kill | confluence sleeves auto-stop when this fires |
| `rail_07_exchange_outage.py` | Polymarket outage | confluence sleeves pause same as momo |
| `rail_11_abs_day_loss.py` | absolute day loss limit | include confluence paper PnL |

Plus the sleeve-internal pause logic (per §2 env vars `CONFLUENCE_RISK_PAUSE_MODE`, etc.) is a separate timed pause specific to this sleeve. Both must coexist — rails are external safety; the internal `_check_risk()` is inline circuit-breaker.

```python
# Required structure inside confluence_silver_v1 strategy class:
def _check_risk(self) -> bool:
    """Cyclops mandate: timed hard pause on DD/daily-loss. Default mode=hard.
    Inline circuit-breaker — runs BEFORE every classify() call.
    """
    mode = os.getenv("CONFLUENCE_RISK_PAUSE_MODE", "hard").lower()
    if mode == "off":
        return True

    now = time.time()
    if self._risk_paused_until > now:
        return False  # still paused

    dd_pct = self._compute_session_drawdown_pct()
    daily_loss_pct = self._compute_day_pnl_pct()
    pause_min = int(os.getenv("CONFLUENCE_RISK_PAUSE_MIN", "15"))
    max_dd = float(os.getenv("CONFLUENCE_MAX_DRAWDOWN_PCT", "5.0"))
    daily_lim = float(os.getenv("CONFLUENCE_DAILY_LOSS_LIMIT_PCT", "2.0"))

    if dd_pct >= max_dd:
        if mode == "hard":
            self._risk_paused_until = now + pause_min * 60
            log_event(kind='poly_updown_confluence_risk_pause', data={
                'trigger': 'max_drawdown',
                'current_value_pct': dd_pct,
                'threshold_pct': max_dd,
                'pause_until_unix': int(self._risk_paused_until),
                'pause_min': pause_min,
                'mode': mode,
            })
            return False

    if daily_loss_pct <= -daily_lim:
        if mode == "hard":
            self._risk_paused_until = now + pause_min * 60
            log_event(kind='poly_updown_confluence_risk_pause', data={
                'trigger': 'daily_loss',
                'current_value_pct': daily_loss_pct,
                'threshold_pct': -daily_lim,
                'pause_until_unix': int(self._risk_paused_until),
                'pause_min': pause_min,
                'mode': mode,
            })
            return False
    return True
```

The pause holds for `CONFLUENCE_RISK_PAUSE_MIN` minutes — the sleeve cannot resume mid-drawdown just because the market ticked back. This is Cyclops fix #1.

---

## 11. Open Questions for TV Agent / Operator

| # | Question | Recommended Approach | Action Required |
|---|---|---|---|
| A | **STRUCTURE online compute strategy**: pre-roll parquet every 15m vs. live in-controller computation? | Pre-roll parquet (§4b recommendation). Live computation requires 240-bar 1MIN kline fetch + OLS regression per signal — adds ~50ms latency, fragile under DB load. Background cron is more robust. | Operator confirms; TV agent implements cron job. |
| B | **`trigger_active=True` bypass**: passing unconditional `True` to `classify()` means SILVER also matches GOLD conditions when both scores ≥ 0.50. Need to verify this is intentional. In practice: GOLD requires `trigger_active AND score≥0.50 AND struct≥0.50` — since we pass `True`, any trade with both scores ≥ 0.50 will be classified GOLD, not SILVER, and will **not fire** (confluence_silver_v1 only fires SILVER). This is correct — GOLD tier is intentionally excluded from v1 (larger size, requires more validation). Confirm. | No change needed if GOLD exclusion is intentional. | Operator confirms GOLD skips are expected behavior in logs. |
| C | **`guard_counter_trend` and `guard_choppiness`**: not implemented in v1 (Phase 2 GUARD module deferred). These guards exist in `schema.py` but have no online implementation yet. Treat as `False` (not blocking) in v1. | Acceptable for paper; adds noise but doesn't break the signal. Build in Phase 2 before promotion. | TV agent leaves these guards unimplemented; notes in code. |
| D | **STRUCTURE cache path on VPS3**: where to write the rolling parquet? Suggest `/opt/tradingvenue/data/struct_cache/latest.parquet`. Operator must ensure this path exists and has write permission for the `tradingvenue` service user. | `mkdir -p /opt/tradingvenue/data/struct_cache && chown tradingvenue:tradingvenue /opt/tradingvenue/data/struct_cache` | Operator creates directory. |
| E | **Polymarket OB collector daily 5-10% loss**: known issue (from NEXT_SESSION_START_HERE critical reminders). Some snapshots may be missing for certain slugs. If OB coverage < 80% of expected snapshots for a given slug, the `ob_stale` skip rate will be elevated. Monitor Q2 skip_reason breakdown for `ob_stale` in first week. | No fix yet; monitor and tune `OB_STALE_MAX_S` if needed. | Operator monitors; TV agent logs `ob_snapshot_age_ms` in every event. |
| F | **`fetch_close_asof` lookahead bug status in production**: §4 of NEXT_SESSION_START_HERE flags this as an open question — does production use `time_period_end_us` or `time_period_start_us`? If production has the old lookahead bug, confluence threshold calibration will be slightly off. | Verify: `grep -n "time_period_end_us\|searchsorted" /opt/tradingvenue/backend/app/data/bars.py`. Must show `end_us`. | TV agent checks before deploy. STOP if `start_us` only. |
| G | **MICRO tier — should we add it?** (Cyclops 2026-05 update introduced MICRO tier.) Lab backtest `MICRO_TIER_BACKTEST_2026_05_07.md` showed MICRO adds n=30 trades at +$1.02 mean (p=0.42, CI [-$2.37, +$3.91]) — positive but indistinguishable from noise. MICRO_strict variant LOSES money (n=149, -$0.97/trade). 50% of MICRO trades co-occur with SILVER days. | **Keep SILVER-only for v1.** Revisit MICRO post-paper after 2+ more weeks of SILVER samples accumulate. | TV agent does NOT implement MICRO in v1. |
| H | **Tier-driven exit policies — HOLD vs HEDGE vs SELL?** Lab backtest `SILVER_EXIT_POLICY_BACKTEST_2026_05_07.md` swept HEDGE/SELL × rev_bp ∈ {2,3,5,8,10}. **Result: HOLD wins unambiguously.** SILVER+HOLD = 100% hit, +$4.08/trade. Every HEDGE/SELL variant drops to 87.5% hit and ~+$3.98/trade — engine fires exit on exactly 1 of 8 trades regardless of rev_bp. The shadow $7.30/trade gap is the production hedge bug, not exit-policy choice. | **Keep HOLD for v1.** | TV agent ships HOLD only; do not add HEDGE/SELL paths to confluence sleeve. |
| I | **Cyclops infra mandates already incorporated** (v1.1): timed risk pause, tier-flow-through to position dict, SKIP-on-feature-exception, clean startup. See §3a, §3b, §6f, and `_check_risk()` block in §10. Confirm each is implemented. | Per spec §3a/§3b/§6f/§10. | TV agent acknowledges all 4 in deploy ticket. |

---

## 12. Reference Data + Reproduction

### Lab Files (this repo, laptop)

| File | Purpose |
|---|---|
| `strategy_lab/confluence/schema.py` | Feature column contracts, `TierResult`, `SKIP` constant |
| `strategy_lab/confluence/tier_classifier.py` | `classify()` function + all threshold constants; mirror 1:1 to production |
| `strategy_lab/confluence/flow/features.py` | FLOW compute functions; mirror 1:1 to `backend/app/features/flow_score.py` |
| `strategy_lab/confluence/structure/btc_trend.py` | `compute_trend_slopes()`, `rolling_slope_norm()`, `realized_vol_1h()` |
| `strategy_lab/confluence/structure/sr_levels.py` | `extract_swings()`, `nearest_distance_bps()`, `compute_distances_for_universe()` |
| `strategy_lab/confluence/structure/regime_classifier.py` | `classify_regime_series()`, `regime_factor()`, `DEFAULT_HYSTERESIS_BARS=5` |
| `strategy_lab/confluence/structure/build_structure.py` | `_compute_struct_score()` composite formula; use as reference for `struct_score.py` |
| `strategy_lab/confluence/feature_join.py` | `enrich_universe()`, `apply_classifier()` — offline batch pipeline; reference only |
| `strategy_lab/reports/CONFLUENCE_VERDICT_2026_05_07.md` | Backtest results justifying SILVER tier and cell selection |
| `strategy_lab/reports/TV_AGENT_MOMO_V2_SLEEVES_IMPLEMENTATION.md` | Existing momo_v2 spec; follow same patterns for env vars, sleeve IDs, base class |

### VPS3 Files (production server)

| Path | Purpose |
|---|---|
| `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` | Production controller (3133 lines); reference for `fetch_close_asof`, OB helpers, `t_plus_120` dispatch block |
| `/opt/tradingvenue/backend/app/venues/polymarket/paper.py` | Paper executor; confluence sleeve uses `paper=True` |
| `/opt/tradingvenue/backend/app/strategies/polymarket/momo_v2.py` | Shape/base class to mirror for `confluence_silver_v1.py` |
| `/etc/tradingvenue/.env` | Env var file; append new confluence vars here |
| `/opt/tradingvenue/data/struct_cache/latest.parquet` | STRUCTURE feature cache (to create) |

### VPS3 Postgres Tables

| Table | Schema | Used by |
|---|---|---|
| `trading.events` | `(at, kind, sleeve_id, data jsonb)` | All telemetry reads/writes |
| `storedata.orderbook_snapshots_v2` | `(slug, side, timestamp_us, bids_json, asks_json, ...)` | FLOW book features |
| `storedata.trades_v2` | `(slug, side, timestamp_us, price, size, aggressor_side)` | FLOW trade features |
| `storedata.binance_klines_v2` | `(symbol_id, timeframe, source, time_period_end_us, price_close, ...)` | STRUCTURE slopes; source='binance-spot-ws' |

### Backtest Reproduction (local)

```bash
# On laptop, reproduce SILVER cell results:
cd "C:\Users\alexandre bandarra\Desktop\global"
py -X utf8 -m strategy_lab.confluence.run_struct_flow_backtest      # struct+flow sign-aligned
py -X utf8 -m strategy_lab.confluence.validate_silver_alpha         # 5-gate validation, SOL only
py -X utf8 -m strategy_lab.confluence.silver_overview               # period/density/expectancy
# Outputs:
#   strategy_lab/results/meta_classifier/struct_flow_backtest.csv
#   strategy_lab/results/meta_classifier/silver_validation.json
#   strategy_lab/results/meta_classifier/silver_per_trade.csv
#   strategy_lab/results/meta_classifier/silver_overview.json
```
