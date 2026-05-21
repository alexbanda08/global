---
artifact: harness-design
phase: 16-multi-venue-cex-reference-klines
authored: 2026-05-08
target_consumer: cex_alignment_backtest.py implementer (next step)
status: design-locked-pending-user-approval
upstream: D:\Storedata\.claude\worktrees\sad-liskov-e85c94\.planning\phases\16-multi-venue-cex-reference-klines\HANDOFF-TO-BACKTEST.md
---

# CEX Alignment Backtest — Harness Design

Goal (Phase 16 §B): determine whether **multi-venue CEX kline reference** beats single-venue (binance-only) for predicting Polymarket UpDown resolutions, using L25 weighted-avg fill prices as the liquidity verdict.

## 1. Reuse vs. extend (no greenfield rewrites)

| Component | Source | Status |
|---|---|---|
| L25 walk → vwap, shares, usd, levels, underfill | `strategy_lab/book_walk.py:book_walk_fill` | reuse as-is |
| Equity-curve stats (Sharpe/Sortino/Calmar/maxDD) | `strategy_lab/polymarket_stats.py:equity_curve_stats` | reuse as-is |
| Slug-level entry+exit simulator (HOLD/HEDGE/SELL_BID) | `strategy_lab/meta_classifier/phase9_lookahead_realfills_multi.py:simulate` | reuse, parametrize candidate |
| Permutation + walk-forward skeleton | `strategy_lab/meta_classifier/extended_backtest_with_robustness.py` | reuse loops, swap signal source |
| VPS2 → local CSV pull pipeline | `migration_2026_05_06/local_pull.sh` | template; clone to `migration_2026_05_08/` |
| Tier-1 entry parquet (L25 at t+120s per slug × outcome) | `data/v4/refresh_2026_05_06/tier1_entries/{asset}_entries_at_t120.parquet` | extend window to 2026-05-08 |
| Bucket book CSV (10s buckets, levels=10, exit-monitoring) | `data/v4/refresh_2026_05_02/{asset}_book_depth_v3_full.csv` | extend window to 2026-05-08 |

The L25 entry walk is **already 25 levels** in `tier1_entries/*.parquet` (`LEVELS_T1 = 25` per `extended_backtest_with_robustness.py`). Confirms the user requirement "we are using L25 orderbook in the tests so we have a true liquidity verdict."

## 2. Data layer — `data/v4/refresh_2026_05_08/` (DUAL-VPS sync)

Architecture correction (verified 2026-05-08 23:00 UTC by row-count probe):

| Source data | Lives on | Why |
|---|---|---|
| Binance (vision + spot-ws, all periods incl 1SEC) | **VPS3** | `storedata-binance-spot-klines-live.service` runs there only; vision daily backfill richer (510k 1MIN rows back to 2025-04-27) |
| Coinbase / Kraken / OKX 1MIN+ | **VPS2** | `storedata-{coinbase,kraken,okx}-klines-live.service` run on VPS2 only |
| Polymarket resolutions / orderbook / trades / oracle | **VPS2** | primary collector |
| `trading.events` trusted paper window | **VPS3** | controller writes there |

VPS2 binance rows (binance-spot-ws stops 2026-04-29; vision stops 2026-04-28) are STALE LEFTOVERS from a defunct collector — **do not pull binance from VPS2**. VPS2's `binance-vision` daily timer is also stuck (no journal entries after 2026-04-29) but VPS3 covers via live WS, so we don't fix it for this harness.

Clone `migration_2026_05_06/local_pull.sh` → `migration_2026_05_08/local_pull.sh` (two SSH targets: `VPS2_KEY` for everything except binance, `VPS3_KEY` for binance). Fragments:

**A1. Binance (VPS3) — all 5 periods (1SEC/1MIN/5MIN/15MIN/1HRS), 30d**:
```sql
-- VPS3 storedata
SELECT symbol_id, period_id, source,
       time_period_start_us, time_period_end_us,
       price_open, price_high, price_low, price_close,
       volume_traded, trades_count, quote_volume,
       taker_buy_base, taker_buy_quote
  FROM binance_klines_v2
 WHERE symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
   AND period_id IN ('1SEC','1MIN','5MIN','15MIN','1HRS')
   AND time_period_start_us >= ((extract(epoch from now()) - 30*86400) * 1e6)::bigint
 ORDER BY symbol_id, period_id, time_period_start_us
```
Output: `binance_vps3_full.csv` (~150MB; 1SEC dominates).

**A2. Multi-venue (VPS2) — coinbase/kraken/okx, 1MIN + 5MIN + 15MIN, 30d**:
```sql
-- VPS2 storedata
SELECT symbol_id, period_id, source, time_period_start_us, time_period_end_us,
       price_open, price_high, price_low, price_close,
       volume_traded, trades_count, quote_volume
  FROM binance_klines_v2
 WHERE symbol_id IN ('COINBASE_SPOT_BTC_USD','COINBASE_SPOT_ETH_USD','COINBASE_SPOT_SOL_USD',
                     'KRAKEN_SPOT_BTC_USD','KRAKEN_SPOT_ETH_USD','KRAKEN_SPOT_SOL_USD',
                     'OKX_SPOT_BTC_USDT','OKX_SPOT_ETH_USDT','OKX_SPOT_SOL_USDT')
   AND period_id IN ('1MIN','5MIN','15MIN')
   AND time_period_start_us >= ((extract(epoch from now()) - 30*86400) * 1e6)::bigint
 ORDER BY symbol_id, period_id, time_period_start_us
```
Output: `cex_vps2_full.csv` (~80MB).

**B. Resolutions (VPS2)** — re-pull `market_resolutions_v2` UpDown 30d. Use real schema (`slot_start_us`, `slot_end_us`, NOT `end_unix` as docs claim). Output: `market_resolutions_full.csv`.

**C. Tier-1 L25 entries (VPS2) — extend window**: re-run `pull_tier1_entries.py` for `(2026-05-06, 2026-05-08]`, append-merge into existing parquet. Confirmed L25 (LEVELS_T1=25).

**D. Bucket books (VPS2) — extend window**: append `(2026-05-02, 2026-05-08]` to `{asset}_book_depth_v3_full.csv`.

**E. Polymarket trades (VPS2)** — server-side CVD aggregation (`04_trades_v2.sh`-style) for `(2026-05-06, 2026-05-08]`. Output: `{asset}_flow_trades.csv`.

**F. VPS3 trusted events** — pull `trading.events` 24-48h window for cross-check (§5). Schema confirmed: `at` (tstz), `kind` text, `sleeve_id`, `position_id`, `data` jsonb. Filter `kind IN ('order_filled','position_settled','prediction_recorded')` (or whatever the controller emits). Output: `vps3_trusted_events.csv`.
```sql
-- VPS3 storedata
SELECT at, kind, sleeve_id, position_id::text, data
  FROM trading.events
 WHERE at > NOW() - INTERVAL '48 hours'
 ORDER BY at
```

Total expected size: ~700MB (same envelope as 05_06; binance-1SEC adds bulk but compresses well to CSV).

## 3. Candidate venues + ensembles

Per `(asset, ws_s)` we compute `ret_5m_{candidate}` from the venue's 1-min closes:
```
ret_5m_{c} = log( close_{c}@ws_s / close_{c}@(ws_s − 300) )
```

Candidate set:

| ID | Sources used | Aggregation |
|---|---|---|
| `bin-vision` | binance-vision only | single |
| `bin-ws` | binance-spot-ws only | single |
| `coinbase` | coinbase-spot-ws only | single |
| `kraken` | kraken-spot-ws only | single (12h subset by default per HANDOFF Option A) |
| `okx` | okx-ws only | reference (operator excluded; we run for completeness) |
| `bin+coinbase` | bin-vision + coinbase | 0.5 / 0.5 of close → recompute log-ret |
| `bin+coinbase+kraken` | + kraken (12h subset) | 1/3 each on overlap window |
| `median3` | bin-vision, coinbase, kraken | per-ts median close |
| `q90-bin` | bin-vision | bin-vision ret with TV-style q90 threshold gate |
| `q90-ensemble` | bin+coinbase | ensemble ret, q90 gate |

Predictor: `Up if ret > 0` (or `> q90` for q90 variants); `Down` otherwise.

**Coverage handling**: when a venue has no row at `ws_s − 300` or `ws_s` (gaps, especially Kraken outside its 12h+forward window), candidate is **skipped for that ws_s**, not zero-filled. Per-candidate row counts get reported separately.

## 4. Predictor → simulator wire

For each `(candidate, asset, timeframe, ws_s) → signal ∈ {Up, Down, Skip}` we hand off to the existing `phase9_lookahead_realfills_multi.simulate(...)`:

```
simulate(row, k1m, entry_book, bucket_book, max_bucket, policy, rev_bp=5)
  - row: slug, window_start_unix, signal, outcome_up
  - k1m: 1-min closes for the BINANCE asset (drives rev_bp hedge trigger; intentionally same regardless of candidate — the trigger is asset-truth, not signal-truth)
  - entry_book: tier1_entries L25 at t+120s
  - bucket_book: 10s buckets for HEDGE/SELL_BID exit monitoring
  - policy ∈ {HOLD, HEDGE_HOLD, SELL_BID}
```

**Important invariant**: the `k1m` used for the **hedge trigger** is binance-vision (the asset truth). The `signal` direction is what changes per candidate. This isolates the alignment question (does picking a different reference change the bet?) from the hedging question (does the hedge fire correctly?).

## 5. Robustness layers

- **Permutation (1000×)**: shuffle `outcome_up` within `(asset, timeframe)`, recompute candidate PnL on shuffled labels. Spec target: `p < 0.01`. Reuse `extended_backtest_with_robustness.py` permutation loop, swap `predict_for_market(...)` to per-candidate predictor.
- **Walk-forward**: 7d-train / 1d-test rolling window, 23 forward folds across the 30d. For q90-thresholded variants, refit threshold per train window. Edge must hold across **majority** of folds, not averaged.
- **VPS3 trusted cross-check**: restrict harness to the VPS3 `trading.events` 24-48h window. Compare binance-only candidate ranking to VPS3 paper outcomes. If ranking diverges materially → harness bug, not alignment edge.

## 6. Output shape

Files written by harness:

- `strategy_lab/results/cex_alignment/headline.csv`
  - one row per `(candidate, policy, asset, timeframe)` × {n_trades, hit_rate, total_pnl, mean_pnl, sharpe, sortino, calmar, max_dd, fill_quality_pct, vwap_avg, level_avg, underfill_pct}
- `strategy_lab/results/cex_alignment/permutation.csv`
  - one row per candidate × 1000 perm seed → null PnL distribution + observed p-value
- `strategy_lab/results/cex_alignment/walkforward.csv`
  - one row per `(candidate, fold) → in-sample/out-sample PnL, threshold (if q90)`
- `strategy_lab/results/cex_alignment/per_trade_{candidate}.csv`
  - audit trail: ws_s, asset, signal, outcome, vwap_e, shares_e, usd_e, lvls_e, under_e, hedge fields, sig_won, pnl
- `strategy_lab/reports/CEX_ALIGNMENT_BACKTEST_2026_05_08.md`
  - executive summary, ranking table, robustness verdict, kraken-coverage caveat, VPS3 reproduction status

## 7. Decisions (locked) and open question

**Locked**:
- Use L25 (25 levels) entry walk via existing `tier1_entries/*.parquet` schema. Matches operator §B.4 spec.
- $25 notional, 2% fee on winning leg only, REV_BP=5, ENTRY_BUCKET=12 (t+120s) — production-faithful constants from `phase9_lookahead_realfills_multi.py`.
- Polymarket resolution = ground truth. Chainlink stream = excluded (paid).
- OKX = candidate set member (cheap to add since rows already pulled), excluded from headline ranking but included in audit table.

**Open question for user**:
- **Kraken**: HANDOFF lists Option A (use as-is, 12h+forward), B (commission `/Trades` aggregator, ~half day), C (drop). Default = A. Ask after first pass if Kraken-flavored variance dominates ranking deltas.

## 8. Implementation order (matches todo list)

1. Probe local-vs-VPS2 gap → confirm exactly what's missing locally for last 2 days.
2. `migration_2026_05_08/local_pull.sh` (clone + extend 05_06) — run, verify counts.
3. `strategy_lab/meta_classifier/cex_alignment_signals.py` — per-candidate signal generator.
4. `strategy_lab/meta_classifier/cex_alignment_backtest.py` — wire signals → phase9 simulate, emit headline CSV.
5. Add permutation + walkforward + VPS3 cross-check to backtest module.
6. Run end-to-end, generate report.

## 9. What the harness is NOT

- Not a re-implementation of any engine — phase9 simulator is reused verbatim.
- Not a Chainlink-stream comparison (excluded per operator).
- Not a sweep over notional/fee/levels — those are LOCKED to production constants. Sweeps come later if alignment edge is real.
- Not a rebuild of `book_walk_fill` — it already does the L25 weighted-avg walk correctly.
