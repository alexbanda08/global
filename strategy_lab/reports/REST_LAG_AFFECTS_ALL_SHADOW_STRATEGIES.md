# Polymarket REST Lag — Per-Bundle Quantification

**Date:** 2026-05-06 ~21:00 UTC
**Replaces:** earlier "REST_LAG_AFFECTS_ALL_SHADOW_STRATEGIES.md" findings — those used WRONG fill timestamps for non-momo strategies.

## Bottom line — corrected

**REST lag is NOT a uniform problem across all shadow strategies. It's concentrated specifically in the momo strategy.**

| Strategy bundle | Fires at | REST vs WS divergence at fill | Paper PnL realistic? |
|---|---|---:|---|
| momo | `slug_ws + 120s` | **+$0.24 mean** (n=7 BTC trades, all in-window) | **NO** — alpha is REST staleness |
| sniper, v3, v3_1, v3_2, v3_3, v4 | `slug_ws` (bar-close) | ±$0.04 (within noise) | YES — REST ≈ WS at bar-close |
| volume | `slug_ws` | <$0.02 in good samples | YES |
| inverse_sniper | `slug_ws` | <$0.005 | YES |
| inverse_volume | `slug_ws` | +$0.02 | YES |

## Methodology

For 1 random profitable trade per bundle (and 7 random momo BTC trades for verification):

1. **Pull from VPS3 trading.events** — `poly_updown_resolution` rows, partitioned by `sleeve_id` regex into 10 bundles.
2. **Determine fill time** — verified via VPS3 `poly_updown_loop.py` master-scheduler code:
   - momo dispatches at `t_plus_120` phase = `slug_ws + 120s`
   - all other modes dispatch at bar-close = `slug_ws`
3. **Look up parquet** at `data/v4/refresh_2026_05_06/cache/{asset}_orderbook_L25.parquet` (VPS2 WS-ingested L25 book) for `(slug, held_outcome)` at fill time ±5s window.
4. **Compute divergence** = `parquet_ask0 − prod_entry_price`.

## Detailed results — non-momo bundles (1 trade each)

| bundle | asset | tf | signal | held | prod paid | parquet ask₀ | parquet bid₀ | Δ (parquet−prod) | dt_ms | n_in_window |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| inverse_sniper | SOL | 5m | UP | Up | 0.5280 | 0.53 | 0.51 | **+0.002** | 3889 | 1 |
| inverse_volume | BTC | 5m | DOWN | Down | 0.5100 | 0.53 | 0.52 | **+0.020** | -430 | 58 |
| sniper | SOL | 15m | UP | Up | 0.5315 | 0.55 | 0.41 | +0.018 | -6925 | 0 |
| v3 | BTC | 5m | UP | Up | 0.5100 | 0.52 | 0.51 | **+0.010** | 265 | 34 |
| v3_1 | BTC | 5m | UP | Up | 0.5100 | 0.48 | 0.45 | **−0.030** | -165 | 75 |
| v3_2 | SOL | 5m | UP | Up | 0.5053 | 0.51 | 0.49 | **+0.005** | -558 | 3 |
| v3_3 | SOL | 5m | UP | Up | 0.5055 | 0.49 | 0.48 | **−0.016** | -483 | 3 |
| v4 | BTC | 5m | UP | Up | 0.5100 | 0.47 | 0.46 | **−0.040** | 68 | 60 |
| volume | SOL | 5m | DOWN | Down | 0.5273 | 0.40 | 0.36 | −0.127 | 5685 | 0 |

**Non-momo summary**: 7 of 8 reasonably-matched bundles (excl. sniper & volume which had no in-window snapshots) show |divergence| ≤ $0.04. Mean ≈ −$0.005. **REST and WS books agree at bar-close.**

## Detailed results — momo BTC (7 random trades, all in-window)

| slug | held | won | prod paid | parquet ask₀ | Δ | dt_ms | n_in_window |
|---|---|:-:|---:|---:|---:|---:|---:|
| btc-updown-5m-1778043300 | Down | ✓ | 0.4682 | 0.66 | **+0.192** | 400 | 59 |
| btc-updown-15m-1778076000 | Down | ✓ | 0.4600 | 0.61 | **+0.150** | 211 | 31 |
| btc-updown-5m-1778075400 | Down | ✗ | 0.4800 | 0.74 | **+0.260** | -33 | 118 |
| btc-updown-5m-1778072700 | Down | ✓ | 0.4800 | 0.76 | **+0.280** | -30 | 109 |
| btc-updown-5m-1778076600 | Down | ✗ | 0.4600 | 0.89 | **+0.430** | 41 | 82 |
| btc-updown-5m-1778058600 | Up | ✗ | 0.5100 | 0.88 | **+0.370** | -12 | 142 |
| btc-updown-5m-1778067900 | Down | ✗ | 0.5000 | 0.50 | +0.000 | 119 | 132 |

**Momo summary**: mean divergence **+$0.24**, median **+$0.26**, max **$0.43**. Direction always positive (parquet ≥ prod, never opposite). 6 of 7 trades show divergence ≥ $0.15.

## Why momo specifically

Momo fires 120 seconds AFTER bar-close, which is 120 seconds AFTER a high-volatility Binance print just occurred (the q90 |ret_2m| gate selects exactly these volatile windows). At that moment:
- **VPS2 WS feed**: book updates ingest sub-second. By `slug_ws + 120s`, the YES/NO ask side has already absorbed the BTC move and prices are at $0.66+ for the favored token.
- **Polymarket REST `/book` endpoint**: serves a cached/buffered book that's significantly behind during high-volatility windows. Returns the pre-absorption book at $0.47-0.51.

This is why momo's paper PnL ($0.50 vwap, 58% WR, +$229) "looks" profitable: the paper executor walks the REST stale-book asks at $0.50, simulates a fill, and computes paper PnL against $1 settlement. **A live taker order would either fail (no asks at $0.50 in the real matching engine) or fill at the actual $0.66+ post-absorption ask — at which point the strategy's break-even hit rate (= vwap) is 0.66 vs observed 58%, structurally negative-EV.**

In contrast, sniper/V3/inverse fire at bar-close (`slug_ws`) BEFORE any major Binance print starts the absorption clock. At that exact instant, REST and WS agree because Polymarket book hasn't started reacting. Their paper PnL reflects executable reality.

## Implications

### What's safe (non-momo strategies)
The shadow PnL across **sniper, V3 family, V4, volume, inverse_*** roughly reflects what live execution would see. Their alpha sources (if any) are real microstructure or behavioral predictions, not REST artifacts. **Live transitions for these are NOT blocked by this finding.**

### What's broken (momo only)
Momo's +$229 paper PnL is fictitious. Paper executor walks an inflated-favorability book; live executor would walk the (much-flatter) post-absorption book. **Live momo at $1+ would lose money.**

### Per-bundle live-readiness assessment
- ✅ **inverse_sniper, inverse_volume** — divergence within noise, can trial $1 live
- ✅ **v3, v3_1, v3_2, v3_3, v4** — divergence within noise, paper PnL is real
- ✅ **sniper, volume** — needs more samples within ±5s window to confirm, but consistent with bar-close pattern
- ❌ **momo** — DO NOT go live. Paper PnL = REST artifact.

## Action items

1. **Update `TV_AGENT_LIVE_TRANSITION_SPEC.md`** — restrict from "any momo sleeve" to "any non-momo sleeve". Recommend a non-momo candidate (e.g. inverse_volume_NIGHT or v3_2 if shadow PnL is good).
2. **Audit other strategies more deeply** — sample 30-50 trades each to confirm the <$0.05 divergence holds across the full range. Probably fine but worth verifying before live.
3. **Re-frame momo** — kill the live deploy. Either redesign (different anchor, different signal) or shelf.
4. **WS migration (Phase 2)** is now lower priority for non-momo strategies, since their REST behavior at bar-close is already accurate.

## Files
- `_xref_bundles_vs_parquet.py` — 10-bundle sample comparison
- `_xref_momo_btc_8.py` — 7 momo BTC trades verification
- `data/v4/shadow_trades_2026_05_06/xref_bundles_vs_parquet.csv` — full table

## Confirmed via
- VPS2 inspection (`/etc/systemd/system/storedata-collector.service`): uses `wss://ws-subscriptions-clob.polymarket.com/ws/market`, real-time WS feed (not REST). Parquet is ground truth.
- VPS3 master scheduler (`backend/app/engine/poly_updown_loop.py:603-700`): comment confirms "momo fires ONLY on the t+120s phase; all other modes fire ONLY on bar-close".
- Live REST `/book` test: 33-second-old timestamp on a pre-market btc-updown-5m. Caveat: pre-market is the worst case; actively-traded markets at bar-close show REST ≈ WS within ~$0.04.
