# Project context — root

**Last data refresh:** 2026-05-21 20:17 UTC. **Window:** Apr 24 → May 21 20:10 UTC (~28 days, 30,750 chainlink-resolved markets). Refresh pipeline: `migration_2026_05_21/{pull_delta_vps3_2026_05_21.sh, convert_and_merge.py, merge_to_canonical.py}` + L25 path added to `data/v4/canonical/load.py`. F7 sleeve deployment window (2026-05-20 19:57 → 2026-05-21 20:10) is now in canonical, 1,128 BTC/ETH/SOL resolutions with L25 + klines + chainlink RTDS coverage.

**Most recent session handoff:** `strategy_lab/reports/HANDOFF_2026_05_22_MOMO_F7_MARKOV.md` — 5 deploy sleeves verified at production parity (legacy 2%-on-profit fee, ws_s F7 anchor, WS-only books); 7/11 TV-spec shadow sleeves pass. Read this first for current backtest state + next steps.

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
- 🚨 **F7 RSI anchor = `ws_s = slot_start − window_s`** — VERIFIED 2026-05-21 via
  `_match_live_f7_v2.py` against 1,331 production fires from `fires_with_gates.csv`,
  using **version-aware ws_s derivation** (v1 fires at ws_s+120, v2 at ws_s+60):
    - rsi_at_ws_s:       **94.67%** match ✓ THIS IS THE ANCHOR (per source code)
    - rsi_at_fire_us:    92.41% (works for v2 because fire is only 60s from ws_s)
    - rsi_at_slot_start: 83.70% (post-fire)
  Source-of-truth: `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py`
  function `build_bar_context_t_plus_120/60`: fetches 15 closes at offsets
  `[-840, -780, ..., -60, 0]` from `ws_s`; the LAST close is at `ws_s`.
  Production RSI is **simple-mean Wilder** (NOT exponential), confirmed by source
  comment in `rsi.py`. My implementation matches.
  An earlier verifier (`_match_live_f7.py`, NOT v2) was version-unaware — subtracted
  120 from all fires; that biased v2 fires' "ws_s" by 60s and falsely concluded
  fire_us was the live anchor. The CORRECT verifier is `_match_live_f7_v2.py`.
  Post-hoc analysis scripts that join external CEX kline data to poly resolutions
  MUST anchor at ws_s (NOT at_ts of resolution events). Requires klines fresher
  than the F7 window being scored.
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
- 🚨 **Polymarket fee model used by production = 2% on profit only (winning leg)** —
  VERIFIED 2026-05-22 against 25,900 `poly_updown_resolution` events in canonical:
  - LOST trades: `pnl_usd = -entry_qty × entry_price` exactly (median diff = 0 from
    naive-no-fee). **No fee on losing leg.**
  - WON trades: `pnl_usd = entry_qty × (1 - entry_price) × 0.98` exactly (median
    diff = 0 from legacy 2%-on-profit).
  The "real curve" `0.07 × p × (1-p)` formula in `strategy_lab/fees.py` is from
  Polymarket's general docs but does NOT match what production actually charges
  on the BTC/ETH/SOL up-down crypto markets we trade — those are effectively
  on the legacy "2% on winning leg only" rule. Either `feeRate` is 0 for these
  markets, or `feesEnabled` is false at the contract level. For ANY backtest
  comparison to production shadow PnL, use `engine_v2.LegacyConfig` (2%-on-
  profit-only). Use `poly_taker_curve` only for hypothetical "what if Polymarket
  flips on real fees" analysis.
- **Maker side**: in PRINCIPLE makers pay $0 and receive a rebate as INCOME on
  every limit fill via `rebate = C × feeRate × p × (1 − p) × rebate_share`,
  but on the crypto up-down markets where production momo runs, `feeRate` is
  effectively 0 (per the 2%-on-profit-only verification above) so no rebates
  are accruing. The mint-and-sell strategy spec assumes rebates are active —
  re-validate before deploying live (check Polymarket account dashboard for
  monthly rebate payouts).
- **PnL accounting reconciliation (2026-05-22 verification)**: the "DEPRECATED FEE
  MODEL" banner on 43 historical files turns out to OVER-CORRECT. Production
  CURRENTLY uses 2%-on-profit-only (see the fee bullet above), so the old files
  were actually right about production behavior. The "real curve" rewrite that
  charges fees on both legs is a hypothetical model for if/when Polymarket
  switches their fee rules. For now: trust the legacy 2%-on-profit numbers when
  comparing to production shadow PnL.
- **Outcome truth — two sources both work**:
  - `outcome` column (chainlink-derived) — present in canonical, default.
  - `clob_winner` column (Polymarket actual settlement) — opt in via `load_resolutions(..., with_clob_winner=True)`. Cache at `data/v4/canonical/clob_resolutions_cache.parquet`. So far 300/300 agreement with chainlink on tested rows. For backtests whose payoff IS what Polymarket pays out, this is the right truth; chainlink stays as an audit channel.
- **Live-WS vs REST staleness — RESOLVED 2026-05-21**: production tradingvenue
  is on **WS-only book reads (Tier-1 WS BookMirror)** per Phase 18.6 Wave 1.
  Live logs verified 2026-05-21 22:55 UTC: every `paper.book_fetched` event has
  `source: "ws_mirror"` from `wss://ws-subscriptions-clob.polymarket.com/ws/market`.
  CLOB REST is now Tier-2 fallback (only when WS mirror is empty for a token);
  Storedata DB is Tier-3 disaster-fallback with CRITICAL alert. Historical
  REST-WS gap of $0.19-0.32 (see `MOMO_REST_LAG_VS_MICROSTRUCTURE.md`) no longer
  affects live PnL. Our canonical L25 backtests now use the same book truth as
  production — apples-to-apples comparison is possible.
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
