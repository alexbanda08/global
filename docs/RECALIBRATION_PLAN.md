# Recalibration Plan — V2 HYBRID + Sniper Re-validation

**Date:** 2026-04-29
**Inputs:** 7+ days fresh data on VPS2 + ~24h live shadow tape on VPS2 (V1) and VPS3 (V2).
**Goal:** find the calibration that makes the live shadow PnL match (or beat) the backtest, before any further deploy.

---

## 1. What we have for recalibration (snapshot 2026-04-29 20:48 UTC+02)

### VPS2 — `2605:a140:2323:6975::1` (collector source-of-truth)

| Table | Rows | Window | Notes |
|---|---|---|---|
| `orderbook_snapshots_v2` | **19,161,341** | 2026-04-22 → 2026-04-29 (**7.17 days**) | 8,395 markets, L21 books each side |
| `market_resolutions_v2` | **8,206** (6,154 5m + 2,052 15m) | same | 99% have `strike_price` + `settlement_price` |
| `trades_v2` (Polymarket prints) | **8,052,526** | same | actual taker/maker fills — fill-realism validator |
| `binance_klines_v2` (`source=binance-vision`) | full year @ 1m/5m/15m/1h/4h/1d | 2025-04-27 → 2026-04-27 | Vision-backfilled spot |
| `trading.events` (V1 shadow) | 681 signals + 655 resolutions | 2026-04-27 → 2026-04-29 | ~2 days of V1 HEDGE_HOLD live tape |

### VPS3 — `185.190.143.7` (V2 shadow)

| Table | Rows | Window | Notes |
|---|---|---|---|
| `trading.events` (V2 shadow) | 1,594 signals + 607 resolutions + 299 hedge_skip | 2026-04-29 01:05 → 20:46 (**~20h**) | V2 HYBRID, every market filled via volume mode |
| `binance_klines_v2` (`source=binance-spot-ws`) | growing live | from 2026-04-28 20:53 | the feed V2 actually uses for `ret_5m` |

### Per-asset, per-tf Polymarket UpDown markets on VPS2

| Asset | 5m markets | 15m markets |
|---|---|---|
| BTC | 2,084 | 716 |
| ETH | 2,082 | 715 |
| SOL | 2,083 | 715 |

Sample size for q90 quantile estimation per (asset, tf): ample — std error on q90 with 700 samples is <1 percentile. Sniper threshold can be reliably calibrated.

---

## 2. The three calibration questions to answer

### Q1. What threshold for the HYBRID reversal trigger eliminates the noise-bleed?
Live evidence: 5 bp is too tight — strategy exits at bid on noise reversals, locking ~5% spread loss per trade. Need to find the threshold where the trigger actually predicts a losing position rather than a transient tick.

**Method:**
- For each resolved market on VPS2, replay every 1m close from window-start to window-end.
- For thresholds {5, 10, 15, 20, 25, 35, 50, 100} bp: simulate the HYBRID exit (try buy-opposite, fallback sell-bid).
- Score: total ROI net of fees + spread; hit rate on bid-exit branch.
- Plot ROI vs threshold per (asset, tf). Pick the elbow.

**Hypothesis:** optimum is in 20–35 bp range, not 5.

### Q2. Does the volume-mode "60% hit rate" survive realistic fill prices?
Live evidence: avg fill at $0.52 (taker ask), backtest may have assumed mid. At $0.52 + 50% hit = -$0.01/share (negative EV). Need to check whether actual top-of-book asks at signal-fire time match what the backtest assumed.

**Method:**
- For each volume-mode signal in the historical 8,200-market pool: compute actual `ask_0` at fire-time from `orderbook_snapshots_v2`.
- Compare to whatever fill-price assumption the V2 backtest used.
- Recompute volume-mode hit-rate × payoff − ask-fill-cost. Bucket by (asset, tf).

**Hypothesis:** volume mode is structurally negative-EV at taker pricing. Either kill it or move to maker entry (`polymarket_maker_entry.py` template exists in `strategy_lab/`).

### Q3. Does the sniper q90/q80 edge survive?
Live evidence: zero — backfill not landed yet. Backtest claim: 81%/91% hit. We can simulate this on the 7.17 days of VPS2 data without waiting for the backfill.

**Method:**
- Compute `ret_5m` per resolved market using VPS2 `binance-vision` 1m closes (proxy for `binance-spot-ws`).
- Per (asset, tf): take rolling 14-day q90 / q80 over the historical sample. Where the day-1 lookback is incomplete, use expanding window.
- Filter to entries where |ret_5m| ≥ threshold. Compute hit rate + ROI at actual top-of-book ask.
- Compare to backtest's 81%/91%. If it holds: ship. If it drops to 60%: backtest leaked.

---

## 3. Extraction plan — get the data into a recalibration-friendly shape

Run on VPS2 directly (the box has the data, we don't need to move 19M rows over the wire). Output: parquet under `/opt/storedata/exports/recalibration_2026_04_29/`. Then `scp` parquet to local for analysis, or `psql -c COPY` directly.

### 3.1 Datasets to extract

| File | Source | Schema |
|---|---|---|
| `markets.parquet` | `orderbook_snapshots_v2 + market_resolutions_v2 join` | `market_id, slug, asset, tf, slot_start_us, slot_end_us, strike_price, settlement_price, outcome, resolution_source` — one row per resolved UpDown market |
| `book_snapshots.parquet` | `orderbook_snapshots_v2` | `market_id, outcome (Up/Down), timestamp_us, bid_price_0..14, bid_size_0..14, ask_price_0..14, ask_size_0..14` — top 15 levels each side, partitioned by date |
| `binance_1m.parquet` | `binance_klines_v2 WHERE source='binance-vision' AND period_id='1MIN'` | `symbol_id, time_period_start_us, price_open/high/low/close, volume_traded` — 1m closes for ret_5m computation |
| `trades.parquet` | `trades_v2 WHERE timestamp_us BETWEEN window` | `market_id, timestamp_us, side, price, size, taker` — for fill realism validation |
| `vps3_shadow_tape.parquet` | VPS3 `trading.events WHERE kind LIKE 'poly_updown%'` | flatten payload jsonb to columns; one row per event; the live ground truth |
| `vps2_shadow_tape.parquet` | VPS2 same | V1 baseline for A/B |

### 3.2 Volume estimate
Books are the heavy one: 19M snapshots × ~15 cols × 8 bytes ≈ 2.5 GB raw, ~600 MB parquet (zstd). Trades 8M × ~6 cols ≈ 400 MB parquet. Total ~1.5 GB.

### 3.3 Pull procedure
```bash
# on VPS2
mkdir -p /opt/storedata/exports/recalibration_2026_04_29
cd /opt/storedata/exports/recalibration_2026_04_29

PGPASSWORD=$TV_RO_PWD_PLAIN psql -h 127.0.0.1 -U tradingvenue_ro -d storedata \
  -c "\copy (SELECT mr.*,
                    CASE WHEN mr.slug ILIKE 'btc%' THEN 'BTC' WHEN mr.slug ILIKE 'eth%' THEN 'ETH' ELSE 'SOL' END AS asset
             FROM market_resolutions_v2 mr) TO 'markets.csv' CSV HEADER"
# repeat for book_snapshots, binance_1m, trades — one COPY per dataset, partition books by day
```
Convert CSV → parquet locally (or use `pgcopy_to_parquet`). Pull to local with rsync.

---

## 4. Recalibration scripts — minimum viable

```
strategy_lab/
  recalibrate_v2/
    01_load_data.py         # parquet → polars dataframes
    02_replay_engine.py     # given (market, threshold, fill_policy) → outcome
    03_threshold_sweep.py   # Q1 — sweep 5..100 bp × 6 sleeves → ROI table
    04_fill_realism.py      # Q2 — compare backtest assumed fills to actual top-of-book + actual trades_v2
    05_sniper_walkforward.py# Q3 — rolling 14d threshold, q90/q80, hit-rate by sleeve
    06_compare_live.py      # join replay output to vps3_shadow_tape; row-level reconciliation
    report.md               # findings + recommended config
```

Each script outputs to `strategy_lab/reports/polymarket/03_recalibration_2026_04_29/`.

---

## 5. Decision gates — what we need to see to ship

1. **Threshold sweep (Q1) shows a positive-ROI elbow** ≥ +5% on at least 4 of 6 sleeves, vs the −15% to −30% live numbers at 5 bp.
2. **Fill realism check (Q2) confirms or denies** that volume-mode EV is recoverable under maker entry. If maker fills capture ≥40% of attempts at midpoint, volume mode is salvageable.
3. **Sniper walk-forward (Q3) holds ≥70% hit** on the 7.17-day sample (slack from backtest's 81% to allow paper→live drift).
4. **Live reconciliation (Q6)** — replay sim's predicted outcomes for VPS3's 607 resolutions match within 5% absolute hit rate. If the sim overpredicts by >5pp the backtest is broken, not the threshold.

If any of (1–4) fails, the strategy doesn't ship and we stop ramping anything.

---

## 6. Out of scope (explicit)

- The TV agent is fixing VPS3-side issues (env flips, code patches). Not our job.
- No Binance backfill for VPS3 in this plan — that unblocks live sniper, but the recalibration runs against VPS2's `binance-vision` source which is fuller anyway.
- No new strategies (the synthetic-covered-call doc is on hold). Recalibrate what exists first.
