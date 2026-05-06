# Strategy Architecture — Reuse-First Build Plan

**Date:** 2026-05-06
**Goal:** Validate Momo HEDGE/SELL exits against real L25 orderbook, then build FLOW engine on top of pulled raw data — without duplicating any existing infrastructure.

---

## 1. Existing engines inventory (don't rebuild these)

After scanning `strategy_lab/` (~40 polymarket files, ~20 backtest scripts, ~15 reports last 10 days), the **canonical reusable building blocks** are:

| # | Module | Role | Status |
|---|---|---|---|
| 1 | `book_walk.py::book_walk_fill` | Orderbook fill simulator (vwap, filled_shares, hit_levels, underfilled) | ✅ canonical, used by every realfill backtest |
| 2 | `polymarket_stats.py::equity_curve_stats` | Sharpe / Sortino / Calmar / MaxDD on PnL series | ✅ canonical |
| 3 | `polymarket_signal_grid_realfills.py` (loaders) | `load_features`, `load_trajectories`, `load_book_depth`, `load_klines_1m`, `asof_close`, `add_q10_signal`, `add_q20_signal` | ✅ canonical loaders/signals |
| 4 | `polymarket_hedge_fallback.py` | 4 exit policies: HEDGE_HOLD / SELL_OWN_BID / HYBRID / STOPLOSS_20 | ✅ matches momo's 3 policies + STOPLOSS |
| 5 | `meta_classifier/extended_backtest_with_robustness.py::simulate_with_policy` | Momo backtest core: 18 cells × 3 exit policies, `_try_hedge`, `_resolve_pnl` | ✅ THIS is the momo backtest |
| 6 | `meta_classifier/phase9_lookahead_realfills_multi.py` | Production-faithful engine with audit (book-walk fidelity verification) | ✅ canonical |
| 7 | `polymarket_realfills_validate.py` | A/B harness: baseline vs realistic on same universe, notional ladder | ✅ template for momo validation |
| 8 | `meta_classifier/permutation_strict.py` | 1000-draw permutation test for significance | ✅ |
| 9 | `engine.py::BacktestResult` | vectorbt wrapper for non-Polymarket signals (HL perp strategies) | ✅ |
| 10 | `polymarket_realfills_dashboard.py` | HTML dashboard generator | ✅ |
| 11 | 4 × `meta_classifier/exit_policy_*.py` | Exit-policy A/B variants | ✅ |
| 12 | `meta_classifier/momo_shadow_vs_backtest.py` | Shadow-vs-backtest comparison (already running) | ✅ |
| 13 | `meta_classifier/v3_production_replay.py` | Replay V3 production decisions | ✅ |
| 14 | `v4_signals/phase7_clob_imbalance_momentum.py` | Phase 7 OB imbalance momentum signal | ✅ |
| 15 | `v4_signals/phase7_validation_v3_full.py` | Production-faithful V3 backtest framework | ✅ |
| 16 | `v4_signals/phase9_polymarket_trade_flow.py` | Phase 9 trade-flow imbalance | ✅ partial (BTC only — needs ETH/SOL) |
| 17 | `meta_classifier/extended_backtest.csv` | Latest momo backtest results — 18 cells with hit / pnl_total / pnl_mean | ✅ data we'll validate against |
| 18 | `meta_classifier/anti_edge_analyzer.py` | Anti-edge detection / inversion testing | ✅ |
| 19 | `meta_classifier/combined_gate_v2.py` | V3 + Phase 7 UNION strategy | ✅ |
| 20 | `meta_classifier/v3_btc_union_realfills.py` | UNION with realistic fills | ✅ |

**Plus 30+ older `polymarket_*.py` research scripts** (forward walks, signal grids, baselines) — keep as-is for reference, don't extend.

## 2. The single hard limitation that drives new work

**ALL existing book loaders use L10:** `LEVELS = 10` constant in `polymarket_hedge_fallback.py`, `phase9_lookahead_realfills_multi.py`, `polymarket_realfills_validate.py`, etc. They read `bid_price_0..bid_price_9` from the bucketed CSV.

**We just pulled L25 RAW** (every snapshot, levels 0-24 both sides). The new data exposes:
- The **L10-25 levels** for liquidity matching beyond top-of-book
- Every individual snapshot (160+ per minute on busy markets) instead of 1-per-10s aggregate

→ **One new loader unlocks everything else.** All other modules drop in.

## 3. New modules required (3 files, ~600 LOC total)

### 3a. `strategy_lab/loaders/raw_orderbook_l25.py` (NEW, ~150 LOC)

```python
"""Load raw L25 orderbook + trades from the 2026-05-06 raw pull (gzip CSV)."""

LEVELS = 25  # ← bumped from L10

def load_orderbook_l25_raw(asset: str) -> pd.DataFrame:
    """Streams {asset}_orderbook_raw_L25.csv.gz, returns full 109-col DataFrame.
    Index: (slug, outcome_id, timestamp_us) for asof lookups.
    Memory tip: chunk-read for BTC (28M rows ~6 GB in pandas)."""
    ...

def load_trades_raw(asset: str) -> pd.DataFrame:
    """Streams {asset}_trades_raw.csv.gz, returns trade prints."""
    ...

def book_at(orderbook_df, slug, outcome_id, ts_us, side='ask') -> tuple[list, list]:
    """asof lookup at exact timestamp. Returns (prices_25, sizes_25) for the
    side requested. Latest row with ts <= ts_us. None entries for missing levels.
    Caller passes to existing book_walk.book_walk_fill() unchanged."""
    ...
```

**Critical:** the return signature `(prices, sizes)` matches `book_walk_fill` exactly → existing code reuses unchanged.

### 3b. `strategy_lab/momo_realfill/validate_with_real_book.py` (NEW, ~250 LOC)

THE ANSWER TO THE USER'S QUESTION. Re-runs the 18 momo backtest cells against real L25 book + real trades.

```python
"""For each momo fire (from extended_backtest.csv → tier1_entries):
  1. Look up real entry_bucket=12 timestamp (t+120s into market)
  2. From real L25 book at that snap: walk own-side asks for $25 entry
  3. During market window (12 ≤ bucket < end), at each rev_bp ≥ 5 trigger:
     - For HEDGE: check opposite-side asks present AND book_walk_fill achieves
       >= 95% of target shares. Record fill_price, hit_levels, underfilled.
     - For SELL: check own-side bid >= entry_vwap - rev_bp_threshold AND
       walking own bids fills entry_qty fully.
  4. Compute realfill_pnl. Compare to backtest_pnl from extended_backtest.csv.
  5. Aggregate per (asset, tf, exit_policy):
     - liquidity_pct: % of fires where exit was actually feasible
     - mean_slippage_bps: avg fill cost vs the L1 quote
     - realfill_pnl_total vs backtest_pnl_total
     - n_underfilled: # cases where book ran out

REUSES:
  book_walk.book_walk_fill
  polymarket_stats.equity_curve_stats
  extended_backtest_with_robustness.{simulate_with_policy, _resolve_pnl, _try_hedge}
  loaders.raw_orderbook_l25.{load_orderbook_l25_raw, load_trades_raw, book_at}

OUTPUTS:
  strategy_lab/results/meta_classifier/momo_realfill_validation.csv
  strategy_lab/reports/MOMO_REALFILL_VALIDATION_2026_05_06.md
"""
```

This is the **first build target**. Answers: "Would HEDGE / SELL have liquidity in real book?"

### 3c. `strategy_lab/flow/` package (NEW, ~200 LOC across 3 files)

After momo validation lands.

```
strategy_lab/flow/
├── __init__.py
├── features.py       # per-bucket: CVD_delta, aggressor_ratio, imb_l5/l10/l25, walls
├── build_features.py # CLI: pre-aggregate raw → parquet (one-time)
└── join_with_signals.py  # Merge FLOW features with V3/momo decision tables
```

Output: `data/v4/refresh_2026_05_06/{asset}_flow_features.parquet` — drop into existing backtests as additional `aux["flow_*"]` features.

## 4. NO new files for these (use existing)

| Need | Use existing |
|---|---|
| Backtest fill simulator | `book_walk.book_walk_fill` |
| Equity curve stats | `polymarket_stats.equity_curve_stats` |
| Permutation significance | `meta_classifier/permutation_strict.py` |
| Signal generators (V3/q10/q20) | `polymarket_signal_grid_realfills.add_q10_signal` |
| Momo signal | `extended_backtest_with_robustness.py` (already runs) |
| Exit policies | `polymarket_hedge_fallback.py` + `extended_backtest_with_robustness.simulate_with_policy` |
| HL liquidations Layer 3 trigger | `data/v4/refresh_2026_05_06/hl_liquidations_btc_eth_sol.csv` (just pulled) |
| Pattern memory (Cyclops L1) | DEFER — not high ROI for binary 5m markets |
| Multi-exchange OB | DEFER — no collector |

## 5. End-to-end flow with the new pieces

```
                                               ┌──────────────────────────┐
       data/v4/refresh_2026_05_06/             │   loaders/               │
       ├── btc_orderbook_raw_L25.csv.gz   ───→ │   raw_orderbook_l25.py   │
       ├── eth_orderbook_raw_L25.csv.gz   ───→ │   (NEW, ~150 LOC)        │
       ├── sol_orderbook_raw_L25.csv.gz   ───→ │   load_orderbook_l25_raw │
       ├── *_trades_raw.csv.gz            ───→ │   load_trades_raw        │
       ├── markets_full.csv                    │   book_at(slug, ts)      │
       ├── market_resolutions_full.csv         └──────────┬───────────────┘
       ├── binance_klines_full.csv                        │
       ├── oracle_prices_full.csv                         ▼
       └── hl_liquidations_btc_eth_sol.csv     ┌──────────────────────────┐
                                               │  Momo backtest cells     │
       results/meta_classifier/                │  (extended_backtest.csv) │
       └── extended_backtest.csv ────────────→ └──────────┬───────────────┘
                                                          │
                                                          ▼
       ┌─────────────────────────────────────────────────────────────────┐
       │  momo_realfill/validate_with_real_book.py    (NEW, ~250 LOC)    │
       │                                                                  │
       │  Reuses (no duplication):                                        │
       │   book_walk.book_walk_fill                                       │
       │   polymarket_stats.equity_curve_stats                            │
       │   extended_backtest_with_robustness.simulate_with_policy         │
       │   extended_backtest_with_robustness._try_hedge                   │
       │   extended_backtest_with_robustness._resolve_pnl                 │
       │                                                                  │
       │  Adds: real-book lookups via raw_orderbook_l25.book_at()         │
       │  Adds: liquidity_feasibility(exit_policy, slug, ts) check        │
       └─────────────┬────────────────────────────────────────────────────┘
                     │
                     ▼
       MOMO_REALFILL_VALIDATION_2026_05_06.md
       per-cell:
         - n_fires
         - hedge_feasible_pct (real book had opposite asks at trigger ts)
         - sell_feasible_pct  (own bid above entry - rev_bp at trigger ts)
         - mean_slippage_bps  (real-fill vwap vs midmark at trigger ts)
         - realfill_pnl_total vs backtest_pnl_total
         - delta_pnl_pct
```

## 6. Build order (decisions for you)

| # | Task | LOC | Time | Output |
|---|---|---:|---:|---|
| 1 | `loaders/raw_orderbook_l25.py` | 150 | 2-3 hr | New canonical loader |
| 2 | `momo_realfill/validate_with_real_book.py` | 250 | 4-6 hr | Answer to "would HEDGE/SELL fire with liquidity?" |
| 3 | Run + report `MOMO_REALFILL_VALIDATION_2026_05_06.md` | — | 1 hr | The decision doc |
| 4 | (optional) `flow/{features,build_features,join}.py` | 200 | 4-6 hr | FLOW engine for next-gen strategy |

**Total to get the momo validation answer: ~1 day. ~400 new LOC. Zero duplication.**

## 7. Open architectural questions

1. **L25 raw vs the older bucketed L10 trajectories** — do we keep `*_book_depth_v3_full.csv` (L10, 10s buckets) for the OLD backtests still in use, while new code reads raw L25? Recommended: **yes**, leave existing data files alone, new modules read from the L25 gz pull.

2. **Does momo backtest need live feature timestamps from `tier1_entries/*.parquet` (microsecond precision)?** Yes — the `extended_backtest.csv` was built using those microsecond entries. The realfill validation must use the SAME timestamps when looking up the L25 book.

3. **What is the canonical exit-trigger anchor for SELL_BID?** Per `MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md` the production code uses bar-close anchor (which barely fires); backtest uses entry-price anchor. The realfill validation must replicate **the production version** so we can tell if the production setup is broken or if the underlying alpha just doesn't have liquidity.

4. **Skip threshold for thin books** — `phase9_lookahead_realfills_multi.py` already has thin-book skip logic. Use the same (don't reinvent).

## 8. Files referenced

**New code targets:**
- `strategy_lab/loaders/raw_orderbook_l25.py` (to be created)
- `strategy_lab/momo_realfill/validate_with_real_book.py` (to be created)
- `strategy_lab/flow/{features,build_features,join_with_signals}.py` (deferred)

**Reused (existing canonical):**
- `strategy_lab/book_walk.py`
- `strategy_lab/polymarket_stats.py`
- `strategy_lab/polymarket_signal_grid_realfills.py`
- `strategy_lab/polymarket_hedge_fallback.py`
- `strategy_lab/meta_classifier/extended_backtest_with_robustness.py`
- `strategy_lab/meta_classifier/phase9_lookahead_realfills_multi.py`
- `strategy_lab/meta_classifier/permutation_strict.py`

**Data inputs:**
- `data/v4/refresh_2026_05_06/{btc,eth,sol}_orderbook_raw_L25.csv.gz`
- `data/v4/refresh_2026_05_06/{btc,eth,sol}_trades_raw.csv.gz`
- `strategy_lab/results/meta_classifier/extended_backtest.csv`
- `data/v4/refresh_2026_05_06/tier1_entries/*.parquet`

**Companion reports:**
- `MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md` (production failure mode)
- `MOMO_SHADOW_VS_BACKTEST_2026_05_06.md` (shadow vs backtest)
- `EXTENDED_BACKTEST_ROBUSTNESS.md` (backtest source)
- `TRADINGVENUE_VS_CYCLOPS_2026_05_06.md` (next-gen architecture goal)
