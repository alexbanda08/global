# Project context — root

**Last data refresh:** 2026-05-15. **Window:** Apr 24 → May 15 02:55 UTC (21 days, 23,553 chainlink-resolved markets). See `strategy_lab/reports/DATA_INVENTORY_2026_05_15.md` for the full inventory + next-session quick-start.

---

## 🚀 Currently deployable strategies (2026-05-18)

Three strategy lines are in different states. **DO NOT confuse versions:**

### ✅ Deploy-ready

**1. Cyclops S7 X1 — BTC 5m sleeve-active composite**
- Location: `cyclops/` package (full code) + `cyclops/PAPER_DEPLOY_SPEC.md`
- Spec: `strategy_lab/reports/CYCLOPS_CLONE_SPEC_2026_05_16.md` + `cyclops/README.md`
- Triggers when: Cyclops S7 fires (trend+levels coherent, momentum abstain, vwap≥0.30) AND any VPS3 BTC 5m sleeve also fired on same slug.
- Validated: **G1+G3+G4 PASS** at $1 stake on 21d (n=36, WR 80.6%, +$0.244/trade, p=0.002, G4 lower CI=+$0.022 with real fees).
- BTC 5m only — does NOT generalize to ETH/SOL or 15m.
- Best paper-deploy target right now. See [`cyclops/_results/MASTER_TABLE_REAL_FEES.txt`](cyclops/_results/MASTER_TABLE_REAL_FEES.txt).

**2. Mint-and-sell maker V2** (under deep-dive next session)
- Spec: `strategy_lab/reports/MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md`
- Implementation spec: `strategy_lab/reports/MINT_AND_SELL_IMPLEMENTATION_SPEC_V1.md` (now 1,479 lines — §8.5/8.6/8.7 added 2026-05-17 cover worked-example, mid-slug MTM, and a drop-in `PaperLedger` reference class).
- 🚨 **V1 has known flaws** — do NOT deploy `MINT_AND_SELL_LIVE_SPEC_2026_05_16.md` (legacy 2%-fee model; wrong fee math).
- V2 uses corrected fee curve (`0.07 × p × (1-p)` + maker rebate as income), $2.5 notional, $1.005 sum_asks entry.
- Per-fire view is breakeven-to-slightly-negative; **slug-level aggregation flips positive** in the BOTH_SIDES_PARTIALS regime (n=9-113 slugs per cell, mean +$0.04 to +$0.41/slug).
- Polymarket CLOB **hosted on AWS eu-west-2 (London)** — Ireland VPS is near-optimal RTT (<2ms). US East = 130ms (uncompetitive). Verified 2026-05-17.
- Backtest engines: `strategy_lab/wallet_hunt/replicate/{mint_and_sell_scan_v2.py, partial_fill_policy_compare_v2.py, slug_level_aggregation.py}`.

### ⏸ Validated insights, not auto-deployable

**3. F2 cluster (0xa0a50783 + 0x9dae874a)** — directional CLOB taker, $5,900/day per wallet
- Decoded fully in `strategy_lab/reports/F2_FINAL_VERDICT_2026_05_18.md`
- Found: 86% WR config exists on F2's 102 slugs (n=449, FOLLOW + cherry-pick filters). But the trigger formula loses -$14k on the broad 21d universe — F2 has a slug-selection signal we cannot reverse-engineer from canonical data.
- Direction picker IS reproducible: F2 fires contrarian to recent 5s flow_imbalance (12% Up-pick when buyers favored Up).
- Time-of-day pattern: 22:00-02:00 UTC + 9-10 UTC, AVOIDS 12-21 UTC (US hours).
- **Gap**: requires Polymarket CLOB WS event tape + cross-exchange basis to decode the slug-selector. Data-collection roadmap in §5 of the verdict report. Not deployable until those are built.

### 🔬 Background research available

- 9-wallet catalog: `strategy_lab/reports/WALLET_CATALOG_2026_05_17.md` + `WALLET_STRATEGIES_DECODED_2026_05_17.md`
- F1 treasury (`0xf70da97812cb96acdf810712aa562db8dfa3dbef`) seeded 4+ strategy variants including the $254k/day HFT scalper `0xb27bc932` (uses relay wallet `0xf3cfb6a6...` for inventory exit — needs decode).
- Master catalog: `strategy_lab/wallet_hunt/cache/_master_catalog.csv`

---

## ⚠️ READ THIS FIRST: canonical dataset

**All backtests / analyses must read data through `data/v4/canonical/load.py`.**

Stop using `data/v4/refresh_2026_05_*` directly — those have inconsistent schemas, mixed
binance/chainlink-resolved outcomes, and led to multiple session bugs (the `binance-klines-1m`
contamination that inflated baseline PnL by ~$14k, the slug-ws semantic confusion, etc.).

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (
    load_resolutions,           # chainlink-only, ~12-18k markets
    load_klines, load_klines_asof,
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,   # filter by slugs to bound memory
    load_tier1_entries,
    load_trades, asof_strict,
)
```

See `data/v4/canonical/README.md` for full schema, conventions, and refresh instructions.

## Conventions agents must respect

- **Timestamps are UTC microseconds** (`*_us` cols, `slot_start_us`, `timestamp_us`). Seconds-suffix `*_s` columns are also UTC. Never localize, never CET.
- **Slug suffix** (`int(slug.rsplit('-',1)[1])`) = the slot's `slot_start` in seconds. **NOT `ws_s`.** It IS the strike-read time / window start for outcome resolution.
- 🚨 **`ws_s` ≠ `slot_start`** (production controller's signal anchor — see
  `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`).
  Production anchors `ret_2m` and `fire_us` on `ws_s = slot_start - window_s`
  (the **PREVIOUS** slot's start). Use the helpers in `data/v4/canonical/load.py`:
  `slug_to_ws_s(slug, tf)`, `add_ws_s(df)`, `ret_2m_at_ws(end_us, prices, ws_s)`,
  and `fire_us = (ws_s + 120) * 1_000_000`. Anchoring on `slot_start` instead =
  lookahead → backtest hit rate inflates 25–40 pp (~85% vs ~50% live).
- 🚨 **F7 RSI in POST-HOC ANALYSIS scripts**: anchor at the same time the LIVE
  controller sampled it, NOT at the resolution event's `at_ts`. The previous
  agent's analysis script (`strategy_lab/meta_classifier/momo_12cells_f7.py:36`)
  set `ws_s = at_ts // 1e9` where `at_ts` is the resolution event time (= slot_end);
  re-scoring shadow trades with RSI at slot_end gives fake 80-99% WR on the
  cells where the bet outcome already moved binance enough to swing RSI sign
  (v1 sol_15m showed 69/70 wins, near-perfect, under that anchor). LIVE F7 PnL
  on VPS3 IS REAL (chainlink-resolved fills); only the post-hoc re-scoring is
  inflated. For ANY post-hoc filter recomputation that joins external CEX kline
  data to poly resolutions, sample RSI at the LIVE fire time (`fire_us = ws_s + 120`),
  not at `at_ts` of the resolution event. Verify via the
  `strategy_lab/meta_classifier/_verify_f7_anchor.py` pattern: re-score the same
  shadow under multiple anchor choices and compare to the live `is_f7` flag from
  `strategy_lab/markov_filter/_results/post_f7_real_compare_v2/fires_with_gates.csv`.
  Note: this verification requires klines fresher than the F7 sleeve deployment
  date — pull fresh canonical klines if `data/v4/canonical/_klines.parquet` ends
  before the F7 window you're scoring.
- **Outcome resolution = Chainlink Data Streams.** Never derive Up/Down from binance close. Either use `outcome` flag from canonical resolutions (already chainlink-derived) or compute from `chainlink_rtds.parquet` strike vs settlement.
- **Binance is the SIGNAL source**, matching production momo controller. Coinbase / Kraken / OKX are alternative venues for ablation tests.
- **`asof_strict(end_us, prices, target_us)`** returns close of bar that ENDED at-or-before `target_us`. Causal. Use this for all kline lookups.
- **L25 entry walk** is the production fill model. `book_walk_fill(prices, sizes, $25)` from `strategy_lab/book_walk.py`.
- 🚨 **Use `engine_v2.py` for any NEW backtest** — single live-mimic primitive that combines latency + real Polymarket fees + sparse-book filter + strict-asof book lookup. Don't roll your own anymore.
  ```python
  from strategy_lab.engine_v2 import LiveMimicConfig, fill_at_book, hold_pnl, sell_pnl
  cfg = LiveMimicConfig()        # canonical Polymarket fee curve + 85ms latency + min_book_events=25
  # cfg = LegacyConfig()         # backward-compat: 2%-on-profit, 0ms latency
  fill = fill_at_book(books_idx, slug, "Up", fire_us, cfg=cfg, spread_filter=0.02)
  pnl  = hold_pnl(fill, won=won, cfg=cfg)
  ```
  Real Polymarket fee at vwap=0.69, 48% hit costs ~$0.43/trade extra vs legacy. See `strategy_lab/reports/HANDOFF_2026_05_16_LIVE_MIMIC_GAPS.md` and `strategy_lab/engine_v2.py` smoke output.
- 🚨 **Polymarket fee formula** (canonical — `strategy_lab/fees.py`):
  ```
  fee = C × feeRate × p × (1 − p)
  ```
  where `C` = shares filled, `p` = fill price ∈ [0,1], `feeRate` is a
  per-market constant from Gamma's `feeSchedule.rate`. For crypto up-down
  (BTC/ETH/SOL 5m/15m): `feeRate = 0.07` (700 bps). The fee is NOT a flat
  7% — at p=0.5 the effective rate is 1.75% of share value; at p=0.85 it's
  1.05%. Always look up feeRate from market metadata for non-crypto venues
  (`feerate_for_market_bps(bps)` in fees.py).
- **Maker side**: makers pay $0 in fees and RECEIVE a rebate as INCOME on
  every limit fill:
  ```
  rebate = C × feeRate × p × (1 − p) × rebate_share
  rebate_share = 0.20  (crypto) | 0.25 (other fee-enabled)
  ```
- **Legacy 2%-on-profit fee model is WRONG.** 43 historical files
  (`polymarket_*.py`, `data/v4/canonical/_*.py`, `meta_classifier/*.py`,
  `discovery_2026_05_16/*.py`, `cyclops/conventions.py`,
  `ga_optimizer/path_b/{events,full_window_analysis,validate_tier_a_realfill}.py`)
  have been flagged with a `DEPRECATED FEE MODEL` banner. Their PnL
  numbers are historical artifacts only — re-run via `engine_v2.fill_at_book`
  + `fees.poly_fee_usd` before quoting any number forward.
- **Outcome truth — two sources both work**:
  - `outcome` column (chainlink-derived) — present in canonical, default.
  - `clob_winner` column (Polymarket actual settlement) — opt in via `load_resolutions(..., with_clob_winner=True)`. Cache at `data/v4/canonical/clob_resolutions_cache.parquet`. So far 300/300 agreement with chainlink on tested rows. For backtests whose payoff IS what Polymarket pays out, this is the right truth; chainlink stays as an audit channel.
- **Live-WS vs REST staleness**: production momo fires at `slug_ws+120s` right after a high-vol binance print; Polymarket REST `/book` lags VPS2 WS L25 by **$0.19-0.32** at that moment. Our backtest already uses WS truth — TV agent must migrate production to WS to match. Sniper / v3 / v4 / inverse / volume sleeves fire at bar-close, REST-WS gap <$0.04 — safe to deploy live. See `strategy_lab/reports/MOMO_REST_LAG_VS_MICROSTRUCTURE.md`.
- 🔬 **Wallet-strategy decoder is built** — pulls full chain history for any Polymarket wallet via Alchemy `getAssetTransfers`, computes cash PnL + open positions, decodes trigger conditions by joining each fire to L25 book / binance klines / chainlink RTDS at the exact second. See `strategy_lab/wallet_hunt/` and **`strategy_lab/reports/HANDOFF_WALLET_DECODER_2026_05_16.md`** for usage. Already decoded: **mint-and-sell strategy** is the trigger behind all 3 profitable up-down wallets we've found so far ($10k–$344k/day, identical signature). The live-deploy spec is at `strategy_lab/reports/MINT_AND_SELL_LIVE_SPEC_2026_05_16.md`.
- 🚨 **`mint_and_sell_scan.py` legacy bug**: treated maker fee as "80% of taker fee" instead of `fee=$0 + rebate income`. PnL estimates from that scanner are understated ~30-50%. Use the canonical formula above. Fix pending.

## Repo layout (top-level dirs of interest)

- `data/v4/canonical/` ← **read from here** (6.6 GB, Apr 22 - May 15)
- `data/v4/refresh_2026_05_12/` ← latest pull, scratch CSVs (3.5 GB)
- `data/v4/refresh_2026_05_06/` ← L25 baseline cache, referenced by build.py (9.8 GB, kept for rebuilds)
- `strategy_lab/` ← all backtests + analysis scripts
- `strategy_lab/reports/DATA_INVENTORY_2026_05_15.md` ← **next-session quick-start + full inventory**
- `migration_2026_05_12/local_pull.sh` ← dual-VPS pull script (latest)
- `migration_2026_05_12/pull_l25_vps3.sh` ← L25 history pull
- `.planning/phases/` ← phase artifacts (gsd-style)

### Stale / known-issue data sources
- `data/v4/canonical/trades_polymarket/` ← **STALE Apr 22 - May 6** (no fresh delta puller yet). If strategy uses trades, limit window accordingly.

## Active data infrastructure

- VPS2 (Contabo IPv6): polymarket collector (orderbook, trades, resolutions), coinbase/kraken/okx klines
- VPS3 (185.190.143.7): tradingvenue engine + binance klines (live spot-ws + vision history) + chainlink RTDS oracle + production `trading.events`
- Resolution-engine fix is owned by **storedata agent** (their plan: VPS2/VPS3 chainlink merge, derive re-run, TV events cross-check, chained-strike check, UMA decoder, unified v3 view). Until that lands, canonical filters out binance-resolved rows.
