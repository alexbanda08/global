# Next Session — Start Here (2026-05-20)

_Replaces NEXT_SESSION_PICKUP_2026_05_19.md. This is a full context dump for restarting cold._

---

## TL;DR (90 seconds)

This session went from "deploy 3 strategies (ACC-M, ACC-H, MAS) at $200" to "**only PAT+ACC-M HYBRID is actually profitable on the full universe — and that's because wallets pick profitable slugs we don't know how to pick**."

Key results:
1. **Built fast bulk backtest** that runs the full 8,146-slug BTC universe in ~8 minutes (vs 11h with old per-slug loader)
2. **Validated current specs against the full universe**:
   - PAT+ACC-M HYBRID = **+$7.79/slug** (only winner)
   - ACC-M alone = **-$2.48/slug** at sz=20 (LOSER, scales worse with size)
   - MAS = **+$0.01/slug** (flat)
   - ACC-H V3f = **-$6.84/slug** (LOSER, V3f decode was wrong)
3. **Identified the missing alpha**: wallets have a slug-selection signal we haven't decoded. Without it, ACC-M alone loses money.
4. **Wrote final TV agent change-list** (`TV_AGENT_CHANGES_2026_05_19.md`) — 3 modifications + 2 new shadow sleeves, all in shadow mode.

**Next session goal**: decode how the wallets select which slugs to trade. That's the missing alpha.

---

## What we built this session

### Reports (in `strategy_lab/reports/`)

In chronological order — each refines the previous:

| File | Purpose |
|---|---|
| `LB_API_DEEPDIVE_2026_05_19.md` | LB-API endpoint discovery + 16-wallet reconciliation + leaderboard |
| `STRATEGY_AUDIT_VS_LB_API_2026_05_19.md` | First audit (superseded — mixed in stranger wallets) |
| `STRATEGY_AUDIT_REFS_ONLY_2026_05_19.md` | Refs-only audit |
| `DATA_FIDELITY_VS_VPS3_2026_05_19.md` | Verified local data = VPS3 at max resolution |
| `ACC_PC_BACKTEST_2026_05_19.md` | Initial ACC-PC backtest (50 slugs) |
| `OVERNIGHT_WALLET_VS_BACKTEST_2026_05_19.md` | 213-slug overnight analysis |
| `MORNING_READ_2026_05_19.md` | TL;DR after overnight |
| `STRATEGY_REVISION_2026_05_19.md` | First revised strategy plan |
| `TV_DEPLOY_SPEC_ACC_M_REV_2026_05_19.md` | ACC-M REV spec |
| `TV_DEPLOY_SPEC_MAS_REV_2026_05_19.md` | MAS REV spec |
| `TV_DEPLOY_SPEC_ACC_PC_2026_05_19.md` | ACC-PC spec |
| `TV_DEPLOY_SPEC_ACC_H_SHADOW_2026_05_19.md` | ACC-H shadow-only spec |
| `TV_DEPLOY_SPEC_PAT_ACCM_HYBRID_2026_05_19.md` | PAT+ACC-M HYBRID spec |
| `PAT_FINDINGS_2026_05_19.md` | PAT-specific findings (87 slugs) |
| `TV_AGENT_IMPLEMENTATION_DELTAS_2026_05_19.md` | Master change-list for TV |
| `README_TV_AGENT_HANDOFF_REV_2026_05_19.md` | Updated README entry |
| **`TV_AGENT_CHANGES_2026_05_19.md`** | **FINAL doc to hand TV agent (shadow-only)** |
| `STRATEGY_UNDERSTANDING_TIMELINE_2026_05_19.md` | Evolution of understanding |
| **`FULL_UNIVERSE_BACKTEST_2026_05_19.md`** | **Definitive full-universe results** |

### Scripts (in `strategy_lab/`)

LB-API + wallet analysis (`strategy_lab/wallet_hunt/`):

| Script | What it does |
|---|---|
| `lb_api_probe.py` | First smoke test of LB-API endpoints |
| `lb_api_resolve_and_test.py` | Resolve short → full wallet addresses |
| `lb_api_resolve_missing.py` | Fallback resolution from parquets |
| `lb_api_canonical.py` | Canonical LB-API sweep on known wallets |
| `lb_api_leaderboards.py` | Pull top-50 leaderboards (profit + volume × 4 windows) |
| `lb_api_classify_new.py` | Classify new wallets by market focus |
| `lb_api_counterparty_miner.py` | Mine counterparties from trades_chain (31,881 found) |
| `lb_api_deepdive_v2.py` | v2 with correct slug regex |
| `lb_api_deepdive_v3.py` | v3 with slug+outcome paired detection (canonical) |
| `lb_api_refs_only.py` | Refs-only deep-dive |
| `lb_api_historical_check.py` | Daily activity bucketing |

Backtest engines (`strategy_lab/backtests/`):

| Script | What it does | Speed |
|---|---|---|
| `wallet_profiler.py` | Per-slug behavior across all wallets (uses fills.parquet) | ~30s |
| `wallet_true_pnl.py` | Proper PnL with rebates/fees + mint inference | ~10s |
| `order_refresh_analysis.py` | Order ladder + fills/order analysis | ~10s |
| `slug_selection_signal.py` | Feature discrimination per (wallet, feature) | ~30s |
| `time_of_day_analysis.py` | Hourly + offset distributions | ~10s |
| `decode_89b5_winner.py` | Deep decode of biggest winner ($248/slug) | ~5s |
| `acc_pc_backtest.py` | Initial ACC-PC simulator (slow, per-slug) | 5s/slug |
| `multi_strat_backtest.py` | Multi-strategy comparison (slow) | 5s/slug |
| `fast_full_backtest.py` | **Fast bulk-filter engine — USE THIS** | 71s for 6110 slugs |
| `_verify_no_subsample.py` | Verifies no 1Hz subsampling | quick |

---

## All engines — how to run them

Run all from `C:\Users\alexandre bandarra\Desktop\global` (the project root). Always use `py -3 -X utf8`.

### Wallet profiler (per-slug behavior + maker/taker ratio + paired%)

```bash
py -3 -X utf8 strategy_lab/backtests/wallet_profiler.py
# Outputs:
#   strategy_lab/backtests/_wallet_profile_per_slug.csv
#   strategy_lab/backtests/_wallet_profile_per_slug_agg.csv
#   strategy_lab/backtests/_wallet_profile_summary.csv
```

### True PnL per wallet (with rebates + fees + mint inference)

```bash
py -3 -X utf8 strategy_lab/backtests/wallet_true_pnl.py
# Outputs:
#   strategy_lab/backtests/_wallet_true_pnl_per_slug.csv
#   strategy_lab/backtests/_wallet_true_pnl_summary.csv
```

### Slug-selection signal mining (THIS IS WHAT NEXT SESSION FOCUSES ON)

```bash
py -3 -X utf8 strategy_lab/backtests/slug_selection_signal.py
# Outputs:
#   strategy_lab/backtests/_slug_selection_features.csv
# Shows: for each wallet, which features (sum_bids, sum_asks, depth_up, depth_dn,
#        spread, mid_diff, hour_utc) discriminate engaged vs unengaged slugs.
```

### Time-of-day analysis

```bash
py -3 -X utf8 strategy_lab/backtests/time_of_day_analysis.py
# Outputs:
#   strategy_lab/backtests/_time_of_day_hourly.csv
#   strategy_lab/backtests/_time_of_day_offset.csv
```

### Order refresh pattern

```bash
py -3 -X utf8 strategy_lab/backtests/order_refresh_analysis.py
# Prints stdout: per-wallet order counts + fills/order + size quantiles
```

### LB-API canonical sweep (re-pulls leaderboard + known wallets)

```bash
py -3 -X utf8 strategy_lab/wallet_hunt/lb_api_canonical.py
py -3 -X utf8 strategy_lab/wallet_hunt/lb_api_leaderboards.py
py -3 -X utf8 strategy_lab/wallet_hunt/lb_api_counterparty_miner.py
py -3 -X utf8 strategy_lab/wallet_hunt/lb_api_deepdive_v3.py
```

### Multi-strat backtest (per-wallet, slow but flexible)

```bash
py -3 -X utf8 strategy_lab/backtests/multi_strat_backtest.py \
    --slugs-from-csv strategy_lab/backtests/_wallet_profile_per_slug_agg.csv \
    --wallet-filter 0xeebde7a0 \
    --max-slugs 50 \
    --sweep-mode pat \
    --out-suffix my_run

# sweep-mode options:
#   default — 5 strategies (ACC-M, ACC-M-lift1c, ACC-PC, ACC-H, MAS)
#   size    — 11 size variants (POST_SIZE 5/10/20/50 + imb tweaks + MAS sizes)
#   big     — 10 bigger variants (sz=20/50/100/200 + MAS-pre30/100/200/500)
#   pat     — 10 PAT variants
```

### Fast full-universe backtest (USE THIS FOR FULL-WINDOW RUNS)

```bash
# BTC 5m (6110 slugs, ~71s per strategy)
py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py \
    --asset btc --tfs 5m --max-slugs 0 \
    --strategies "ACC-M-sz5,ACC-M-sz20,ACC-M-sz50,ACC-M-sz100,PAT+ACC-M,MAS,ACC-PC" \
    --out-suffix full_btc5m

# BTC 15m (2036 slugs, ~25s per strategy)
py -3 -X utf8 strategy_lab/backtests/fast_full_backtest.py \
    --asset btc --tfs 15m --max-slugs 0 \
    --strategies "ACC-M-sz20,PAT+ACC-M,MAS" \
    --out-suffix full_btc15m

# ETH or SOL — same syntax, --asset eth|sol
# Subset via --max-slugs N — uses evenly-spaced sample
```

NO 1Hz subsampling — reads raw parquets, sees all sub-second events (verified: dt p50 = 33-74 ms, 96-98% sub-second).

---

## Current strategy state (after this session)

### TV agent has been given: `TV_AGENT_CHANGES_2026_05_19.md`

5 strategies, all in **shadow mode** for engine validation:

1. **PAT+ACC-M HYBRID** — modified ACC-M with PAT taker overlay
   - POST_SIZE=20, max_imbalance=10, abs_max_inv=100
   - PAT trigger: market-buy both sides when `ask_up + ask_dn + 2×fee < $1.00`
   - PAT params: take_size=20, max_pair_cost=1.00, min_s_between=5, max_per_slug=10
   - Backtest (full BTC universe): **+$7.79/slug avg**

2. **MAS REV** — original MAS reduced to 2 cells
   - btc_5m + btc_15m only (was 6 cells)
   - $30 pre-mint per slug
   - Backtest: **+$0.01/slug** (flat, data collection)

3. **ACC-H** — keep V3f composite taker, add per-rule logging
   - 4 rules: Discount-capture + Sharp-drop + Early-slot + Buy-pressure
   - Log every check (fires + skips) to attribute per-rule PnL
   - Backtest: **-$6.84/slug** (loses money) — likely needs refinement or to be dropped

4. **ACC-PC** (new shadow sleeve) — reactive pair-completion taker
   - Inherits ACC-M, fires only when imbalanced
   - PC params: max_pair_cost=0.97, min_time=30s, CVD>0 filter
   - **BUG NOTED**: produced identical numbers to ACC-M-sz20 in fast_full_backtest — PC taker not firing. Needs debug.

5. **PAT-SHADOW** (new shadow sleeve) — pure PAT with permissive thresholds
   - No maker side (POST_SIZE=0)
   - max_pair_cost=1.02 (more permissive than live PAT+ACC-M's 1.00)
   - Research/data only

---

## Wallet patterns we decoded

### 5 reference wallets in the catalog (all 16 in `cache/_addr_map.json`)

| Wallet | Pseudonym | LB 30d $/day | Pattern | Chain decode |
|---|---|---|---|---|
| `0x04b6d7e9` | (anon) | $2,038 | **MAS** (98% SELL maker, 100% paired_buy in chain) | 54k fills, BTC 5m+15m |
| `0xb27bc932` | (anon) | $1,740 | **PURE PAIR ARB MAKER** scale-up version | 100% paired |
| `0xeebde7a0` | Bonereaper | $6,047 | **HYBRID** (56% maker / 44% taker, mixed) | $99.8M cumulative |
| `0x89b5cdaa` | ohanism | $4,258 | **DIRECTIONAL MAS** (100% SELL, 41% paired = single-side focus) | 100% maker |
| `0xcfb103c3` | xuanxuan008 | $2,560 | **PAT** (90% taker, 99.8% paired) | $12.6M vol |

### Slug-selection signals (already discovered, NEEDS DEEPER ANALYSIS)

From `_slug_selection_features.csv` z-scores (engaged vs un-engaged slugs in wallet's active window):

| Wallet | Engagement % | Strongest discriminator | z-score |
|---|---|---|---|
| `0xcfb103c3` | 65.6% | **depth (thin-book bias)** | **-17.86** |
| `0x89b5cdaa` | 76.3% | depth (thin-book) | -2.53 |
| `0xce25e214` | 42.4% | depth (thick-book) | +5.75 |
| `0x04b6d7e9` | 55.7% | hour_utc | +6.60 |
| `0xeebde7a0` | 96.4% | sum_asks (wide-spread) | +1.31 |

**These are the partial signals.** Not enough to fully replicate wallet picks. The next session goal is to decode them deeper.

---

## Critical findings to carry forward

### 1. PAT+ACC-M HYBRID is the only validated profitable strategy on full universe

213-slug wallet-selected sample said ACC-M alone works. Full-universe (8,146 slugs) says **ACC-M alone loses money**. Only PAT+ACC-M HYBRID is positive. The PAT overlay is doing all the lifting.

### 2. Wallets have slug-selection alpha — that's the missing edge

Reference wallets engage 42-96% of slugs and ACC-M IS profitable on their engaged slugs. We engage every slug and ACC-M LOSES. The selection is the difference.

### 3. ACC-M maker base is fee-bleed without selection

On random slugs, ACC-M:
- Posts BIDs both sides when sum_bids < $1 (26% of universe)
- Gets some fills
- Ends with leftover on losing side ~50% of slugs
- Leftover-burn > merge-profit + rebates → net negative

### 4. ACC-H V3f is unverified

V3f composite taker (4 rules) was decoded from Bonereaper's chain at 78.9% coverage, 1.37× lift. Our backtest says it loses -$6.84/slug. **One of these is wrong.** Shadow data will tell.

### 5. LB-API public endpoint exists

`http://lb-api.polymarket.com/profit?window={1d,7d,30d,all}` — returns top 50 by profit. Public, no auth. Use for daily monitoring of competitor activity.

### 6. Local data = VPS3 collector output (max resolution)

Verified: dt p50 = 33-74ms between snapshots, 96-98% sub-second intervals. Schema matches VPS3's `orderbook_snapshots_v2` table. No subsampling in `fast_full_backtest.py` (reads raw parquets via `pq.ParquetFile.read_row_group()`).

### 7. Three "loser" wallets are actually winners

`0xce25e214`, `0xcfb103c3`, `0x7dfc8aa2` were labeled losers in earlier pickup. LB-API shows them all profitable ($2.2k-$4.6k/day). Pickup mis-classified.

### 8. PnL projections were 50-170x overstated

Pickup claims `$254k/day` for `0xb27bc932`. LB-API actual: $1.7k/day. The pickup chain decode extrapolated short hot-streak windows.

---

## Bugs / unfinished work

1. **ACC-PC PC-taker doesn't fire in `fast_full_backtest.py`** — produces identical numbers to ACC-M-sz20. Probably CVD window not being populated (only populated on trade events, may not have time to accumulate before PC trigger checks). Investigate in next session.

2. **Per-rule ACC-H V3f logging not yet implemented** — needs to be added so we can attribute per-rule PnL in shadow mode.

3. **ETH and SOL full-universe runs not done yet** — same backtest engine, ~5 min each. Run as confirmation that PAT+ACC-M HYBRID works cross-asset.

---

## Next session focus: decode slug-selection

User said: **"next session we will go to try to find how the wallets select the slugs they will trade in"**

This is the missing alpha. If we can predict which slugs the wallets engage, we can apply ACC-M only on those slugs and capture the +$2k/day reference wallets make.

### Hypotheses to test

For each (wallet, slug) pair where we have data:
1. Does the slug have wide spread at open? → wallet engages
2. Does the slug have thin/thick book? → wallet engages
3. Is `sum_bids` low at open? (= more room for ACC-M edge)
4. Is `sum_asks` high at open? (= more room for MAS edge)
5. Is it a specific time of day?
6. Is it a specific asset (BTC vs ETH vs SOL)?
7. Is it a specific timeframe (5m vs 15m)?
8. Did binance move strongly in the prior 60s/120s? (volatility filter)
9. Is the slot_start "round" UTC time? (e.g., on the hour vs in-between)
10. Was the prior slug profitable for the wallet?

### Approach

1. Build per-slug feature table for ALL BTC 5m + 15m slugs in window:
   - Opening book features: sum_bids, sum_asks, spread_up/dn, depth_up/dn, mid_diff
   - Time features: hour_utc, weekday, minute_into_hour
   - Binance features: vol_60s, vol_120s, ret_60s, ret_120s leading into slot
   - Slug features: tf (5m/15m), asset (BTC/ETH/SOL), slot_offset_in_hour

2. For each wallet, build engagement label per slug (engaged=1, not-engaged=0)

3. Train binary classifier (logistic regression / xgboost) per wallet:
   - Find which features best discriminate engaged vs not-engaged
   - AUC > 0.6 = signal exists

4. Compare classifiers across wallets:
   - Common features → universal selection signal
   - Wallet-specific features → wallet-specific alpha

5. Validate: run ACC-M on slugs the classifier predicts engaged-by-{wallet}. Does PnL match wallet's actual?

### Existing data to use

- `_slug_selection_features.csv` — has z-scores per wallet per feature
- `_wallet_profile_per_slug_agg.csv` — per-slug engagement record per wallet
- `_fast_full_btc_full_btc5m.csv` — strategy PnL per slug
- `_fast_full_btc_full_btc15m.csv` — same for 15m

### Suggested first commands

```bash
# Start by deeply analyzing the slug-selection features
py -3 -X utf8 strategy_lab/backtests/slug_selection_signal.py

# Build per-slug feature table (NEW SCRIPT TO WRITE)
# Should output: _per_slug_features.csv with all features for every slug

# Train per-wallet classifier (NEW SCRIPT TO WRITE)
# Should output: classifier weights + AUC per wallet

# Run ACC-M backtest filtered to predicted-engaged slugs
# Should output: per-wallet PnL on classifier-selected slugs
```

---

## Quick reference

### Wallet addresses

```
0x04b6d7e9930cf9e493c5e6ef24b496294f95594c8  # MAS-pattern ref
0xb27bc932bf8110d8f78e55da7d5f0497a18b5b82   # scale ref
0xeebde7a0e019a63e6b476eb425505b7b3e6eba30   # HYBRID (Bonereaper)
0x89b5cdaaa4866c1e738406712012a630b4078beb   # directional MAS (ohanism)
0xcfb103c37c0234f524c632d964ed31f117b5f694   # PAT (xuanxuan008)
0xce25e214d5cfe4f459cf67f08df581885aae7fdc   # mixed taker
0x7dfc8aa22f2d4d6f9cbf55cf86682a4d2477f54e   # CramSchoolClub01
```

### Key data files

```
data/v4/canonical/load.py                                       # Canonical loaders
data/v4/canonical/resolutions_from_rtds.parquet                 # Chainlink resolution truth
data/v4/refresh_2026_05_06/cache/btc_orderbook_L25.parquet      # BTC L25 baseline
data/v4/refresh_2026_05_16/cache/btc_orderbook_L25_delta.parquet # BTC L25 delta
data/v4/canonical/trades_polymarket/btc.parquet                 # BTC trades
strategy_lab/wallet_hunt/cache/<short>/fills.parquet            # Per-wallet enriched fills
strategy_lab/wallet_hunt/cache/_addr_map.json                   # short → full addr
```

### Polymarket contract addresses (unchanged)

```
USDC.e         = 0x2791bca1f2de4661ed88a30c99a7a9449aa84174
CTF            = 0x4d97dcd97ec945f40cf65f87097ace5ea0476045
CLOB Matcher   = 0xe111180000d2663c0091e4f400237545b87b996b
NegRiskAdapter = 0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296
```

### Critical conventions (UNCHANGED from prior sessions)

1. UTC microseconds for `*_us` columns; never localize
2. `ws_s = slug_suffix - window_s` (PREVIOUS slot start, not slug suffix)
3. Outcome = chainlink RTDS (never derive from binance)
4. `asof_strict` for causal lookups
5. L25 walk via `book_walk_fill` for production-matching fills
6. Real Polymarket fees: `0.07 × p × (1-p)` per share (taker)
   Maker rebate: `0.20 × 0.07 × p × (1-p)` per share
7. Polymarket CLOB hosted **AWS eu-west-2 (London)** — Ireland VPS optimal
8. CLOB minimum order: **5 shares per side**, $0.01 price tick
9. Currency on-chain: **USDC.e** (`0x2791bca1...`), Polymarket UI calls it pUSD

---

## Recommended starting prompt for next session

```
Read NEXT_SESSION_PICKUP_2026_05_20.md first.

We're decoding how the reference wallets select which slugs to trade.
Build a per-slug feature table for all BTC slugs in the canonical window,
then train per-wallet classifiers to predict engagement. The hypothesis is
that the wallets' edge over our ACC-M backtest comes from picking
profitable slugs — if we can decode their selection signal, we can apply
ACC-M only on those slugs and capture +$2-6k/day.

Already known: 0xcfb103c3 strongly selects thin-book slugs (z=-17.86 on depth).
0xce25e214 selects thick-book slugs (+5.75). Others have weaker signals.

The full set of feature/wallet z-scores is in
strategy_lab/backtests/_slug_selection_features.csv. Start there.
```

---

## What stays the same (don't redo)

- All infrastructure work from `TV_AGENT_DEPLOYMENT_PLAN_2026_05_18.md`
- Ireland VPS setup, BookMirror, PolymarketClient
- Cancel rules (3¢ / 20s)
- Performance requirements P1-P10
- Fees module (`strategy_lab/fees.py`)
- Canonical data loaders (`data/v4/canonical/load.py`)

## What to hand TV agent (still)

The single doc: **`strategy_lab/reports/TV_AGENT_CHANGES_2026_05_19.md`**

It contains: 3 modifications to existing strategies (ACC-M, MAS, ACC-H) + 2 new shadow sleeves (ACC-PC, PAT-SHADOW). All in shadow mode, no live capital. Goal: engine validation + bug catching for 7+ days.

---

_End of context dump. Total session output: 19 reports, 17 scripts, 30+ data files. Ready to resume._
