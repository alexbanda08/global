# Momo Re-run on 2026-05-06 dataset — HOLD baseline (25-level entry books)

**Generated:** 2026-05-06
**Inputs:** `data/v4/refresh_2026_05_06/{markets_full, market_resolutions_full, klines_full, tier1_entries/*.parquet}.csv`
**Strategy:** momo top-q90 |ret_2m| gate → 25-level ASK walk for $25 → HOLD to chainlink. 2% fee on profit.

## ⚠️ Two material findings — read before drawing conclusions

### Finding 1 — Production's `ret_2m` anchor is wrong by 60 seconds

The `market_resolutions_full.csv` schema changed: previously had `window_start_unix` + `outcome_up`; now only `slug` + `outcome` (Up/Down).

Sanity-tested (`_sanity_outcome.py`): outcome aligns 95.8% with anchor `(slug_ws-60 → slug_ws+window-60)`. Strike is at `slug_ws-60`, NOT `slug_ws`. Slug-ws sits 1 minute INTO the market.

That means the prior backtest (`extended_backtest.csv`) was effectively computing `ret_2m = log(close@(strike+120) / close@strike)` because its `window_start_unix` column was the strike time = `slug_ws-60`. **The new dataset doesn't expose this — you have to subtract 60 from `slug_ws`** to get the equivalent anchor.

Hit rate at q90 gate top-decile, by anchor:

| Anchor (BTC_5m) | top-decile hit% | matches prior backtest? |
|---|---:|---|
| `(slug_ws → slug_ws+120)` (= what production currently does) | **50%** | ❌ random |
| `(slug_ws-60 → slug_ws+60)` (= prior backtest semantics) | **89%** | ✅ matches |

Production's `MomoStrategy._build_signal_aux` documents `ret_2m = log(close@ws+120 / close@ws)` using `slot.btc_close_at_ws = BTC@(slug_ws)`. Per the empirical test, **this is the wrong anchor**. Switching to `(slug_ws-60 → slug_ws+60)` could lift live hit rate from 58% → 89%.

### Finding 2 — Even with correct anchor, vwap is too high to print money

With anchor fixed:

| cell | n | wins | hit% | pnl_total | pnl_mean | avg_vwap |
|---|---:|---:|---:|---:|---:|---:|
| BTC_5m | 184 | 163 | 88.6% | −$129.62 | −$0.70 | **0.911** |
| BTC_15m | 63 | 45 | 71.4% | −$170.57 | −$2.71 | **0.785** |
| ETH_5m | 143 | 133 | 93.0% | +$22.23 | +$0.16 | 0.924 |
| ETH_15m | 54 | 44 | 81.5% | +$24.16 | +$0.45 | 0.803 |
| SOL_5m | 118 | 110 | 93.2% | −$23.85 | −$0.20 | 0.938 |
| SOL_15m | 45 | 35 | 77.8% | −$44.26 | −$0.98 | 0.810 |
| **TOTAL** | **607** | **530** | **87.3%** | **−$321.93** | — | — |

Break-even hurdle: `hit% > vwap`. With vwap=0.91, you need >91% hit to make money. Most cells are at hit=88-93% — borderline.

Compare to **prior backtest** (extended_backtest.csv): BTC_5m vwap=0.694, +$4,705 over 325 trades. Same dataset (same tier1 parquets), same anchor (matched), but **vwap is much lower in prior backtest**.

**Root cause investigation needed.** Two hypotheses:

(a) **Different entry-book timing.** Tier1 in this refresh has `target_ts_us = slug_ws+120s`. Maybe prior backtest used an OLDER tier1 with target=strike+120s=`slug_ws+60s` (60s earlier — book hadn't absorbed yet). The 60s of additional book-absorption explains vwap drift from 0.69 → 0.91.

(b) **Production REST lag is the alpha source, not Binance lag.** Production fetches book via REST → 1-2s stale book reflecting pre-absorption prices (vwap=0.50). VPS2 WS-ingested L25 books are real-time → already absorbed (vwap=0.91). If true, the alpha exists ONLY in REST-stale fetches and Phase-2 WS migration would KILL the strategy.

Production live shadow data shows entries at vwap 0.46-0.55 → consistent with (b) and rules out (a) as the only explanation.

## What to do next

Before running tests 1-4 from the prior plan, **decide the anchor question**:

1. Pull two production trade slugs (e.g. trade #16 BTC_5m DOWN at 05:01:14 UTC, ent_px=0.4682) and find the corresponding tier1 entry book row in `btc_entries_at_t120.parquet`. If the parquet's `ask0` for the Down outcome at that slug ≠ 0.4682, then VPS2 books are **systematically different** from REST books at same timestamp → confirms hypothesis (b) → strategy alpha is REST-lag.

2. Check `dt_abs` percentiles per asset: median 91ms BTC, 462ms ETH, 810ms SOL. Books are within ~1s of target, NOT systematically late.

3. If hypothesis (b) is confirmed, the entire research pipeline should use REST-style book snapshots, not VPS2 WS books. The 25-level WS books are the WRONG dataset for backtesting this strategy.

## Pipeline counts (current run)

- universe (resolved markets, BTC/ETH/SOL × 5m/15m): 9618
- with finite ret_2m: 9618
- below q90 gate (14d trailing): 7830
- skipped (no entry book / spread / thin / no thresh): 481
- **fires: 607**

## Files
- script: `strategy_lab/meta_classifier/momo_rerun_l25_hold.py`
- per-trade: `strategy_lab/results/meta_classifier/momo_rerun_l25_hold_per_trade.csv`
- aggregated: `strategy_lab/results/meta_classifier/momo_rerun_l25_hold.csv`
- sanity scripts: `_sanity_outcome.py`, `_sanity_gate.py`, `_sanity_vwap.py`

## Recommended next step

Resolve hypothesis (b) before running tests 1-4. If alpha is REST-lag-driven, all four tests need redesign (they assume WS-precision is "better" — it's actually different). If alpha is real microstructure, then proceed with WS L25 streaming.

Quick test: cross-reference 5 production live trade slugs against tier1 parquet `ask0` at same `(slug, outcome)` key. Match within $0.05 → microstructure real. Diverge by $0.30+ → REST-lag alpha.
