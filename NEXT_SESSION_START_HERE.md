# NEXT SESSION — Start Here

**Last update:** 2026-05-06 22:30 UTC
**Replaces previous:** 2026-05-05 18:45 UTC
**Active deploys:** momo paper (18 sleeves) on VPS3 since 2026-05-06 00:28 UTC

---

## In one sentence

**Momo paper deployed; 16h shadow shows 5m bleeding $-1/trade vs realfill $+6/trade because (a) hedge mechanism returns empty book 100% of the time on opposite side, (b) production ignores spread filter on thin SOL books, and (c) backtest had a kline-asof lookahead bug. Three fix specs ready for TV agent. L25 raw orderbook + trades pulled from VPS2; ~5.4 GB local. New strategy architecture (Cyclops-inspired Multi-Layer Confluence) speced and queued for build after 5m fix lands.**

---

## State of the world (TL;DR)

| Thing | Status |
|---|---|
| **Momo strategy deployed** (18 sleeves) | ✅ live paper since 2026-05-06 00:28 UTC |
| **Shadow vs L25 realfill 3-way comparison** | ✅ DONE — `MOMO_3WAY_COMPARISON_2026_05_06.md` |
| **TRUE same-trade matcher** (slug-by-slug) | ✅ DONE — `match_shadow.py` + `MOMO_SHADOW_MATCH_2026_05_06.md` |
| **Production controller hedge bug ROOT CAUSE found** | ✅ DONE — `VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md` |
| **TV agent fix prompt for hedge bug** (3-tier CLOB→WS→DB) | ✅ READY — `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` |
| **5m vs 15m diagnosis** + slippage decomposition | ✅ DONE — `MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md`, `MOMO_5M_FIX_PLAN_2026_05_06.md` |
| **Lookahead bug in backtest** (kline asof bar-start) | ✅ FIXED 2026-05-06 — `extended_backtest_with_robustness.py:asof()` now end-time-indexed |
| **Dynamic sizing cap spec** for SOL thin books | 🟡 SPEC IN THIS DOC §5 |
| **Multi-Layer Confluence (Cyclops) architecture** | 🟡 SPEC IN THIS DOC §6 |
| **L25 raw orderbook + trades pulled to local** (~5.4GB) | ✅ DONE 2026-05-06 |
| **Parquet cache built** (4.3 GB, fast slug-filter) | ✅ DONE — `data/v4/refresh_2026_05_06/cache/*` |
| **VPS2 → VPS3 migration scripts** (HL liq, oracle, markets, trades, OB) | ✅ READY to fire — `migration_2026_05_06/` |
| **VPS2 deprecation deadline** | 🔴 ~10 days; migration MUST run first |

---

## Critical findings this session

### 1. Production controller hedge mechanism is fully broken

**0 hedges fired** across all 18 sleeves in 215 momo resolutions over 16h.
**5 partial-bid-exits** fired (only 2.4%).
**233 hedge_skip events ALL with `book_ts=0`** (100%).

**Root cause:** `_fetch_opposite_book()` calls Polymarket CLOB HTTP `/book?token_id=...` which returns empty/error for thinly-traded opposite-side tokens. The Storedata DB fallback is **disabled** by default (`_db_fallback_enabled=False` in `paper.py:117`). Storedata has 98% ask coverage on the same markets, but the controller never reads from it.

**Fix queued:** 4-commit plan in `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`:
1. Diagnose CLOB empty-response root cause (instrumentation)
2. Fix CLOB tier-1 (likely token-id precision loss or rate-limit)
3. Add WS BookMirror as tier-2 fallback (subscribe at slot creation)
4. Enable Storedata DB fallback as tier-3 (default ON, env-overridable)

### 2. TRUE same-trade comparison: production leaves $7.30/trade on the table

For 221 of 299 shadow fires (matched to L25 raw book on the same slug+ts):

| Metric | Shadow paper | L25 realfill SAME trades | Δ |
|---|---:|---:|---:|
| Total PnL (matched) | **$+598.89** | **$+2,211.63** | **+$1,612.74** |
| Mean $/trade | $+2.71 | $+10.01 | **+$7.30** |

Realfill = same markets, same outcomes, only the EXIT POLICY simulation differs (uses canonical `book_walk_fill` against fresh L25 raw snapshot).

### 3. 5m bleeds, 15m profits — pure win-rate gap

| tf | n fires | win_rate | mean_pnl/trade | total |
|---|---:|---:|---:|---:|
| **15m** | 42 | **69.0%** | **$+11.03** | $+463 |
| **5m** | 150 | **47.3%** | **$-1.09** | $-164 |

**Hedge/sell are essentially never firing on either tf** (0 hedges, 4 partial exits across all). So the difference is purely HOLD outcome dynamics.

5m loses because:
- Short window (3 min after t+120 entry) → less directional reliability
- Thin SOL books → poor entry vwap when walking $25 deep
- Production fires on wide-spread markets that realfill correctly skips

### 4. SOL has THIN orderbooks — median L1 = $5.80

| Asset | Median L1 USD | $25 fits at L1 |
|---|---:|---:|
| BTC | $64.68 | 92% |
| ETH | $14.87 | 45% |
| **SOL** | **$5.80** | **25%** |

50% of SOL_5m markets have less than $6 of liquidity at best ask. Walking $25 forces 5+ level walks → bad vwap → entry slippage → losses.

**Fix: dynamic stake cap** (see §5 below).

### 5. Lookahead bug in backtest's kline asof — **FIXED**

`extended_backtest_with_robustness.py::asof()` was using bar-start-time indexing. For a query at `ts=t+130`, returned the close of the bar opening at `t=120` — but that bar's close is at `t=180` (50s in the future).

For 5m markets, this means buckets 25-29 (t+250..290) read the bar that closes at market resolution (t+300) — **the answer itself.** Backtest sees future prices when computing rev_bp during the last 50s of monitoring.

Effect: backtest over-estimates HEDGE/SELL trigger frequency in last 50s of 5m markets. Production correctly does NOT have this lookahead → fires hedge/sell less often.

Fix landed in `extended_backtest_with_robustness.py:asof()` 2026-05-06: end-time-indexed lookup (`time_period_end_us ≤ ts × 1e6`) guarantees the bar has CLOSED before the query timestamp.

**Re-run with strict asof on full 14d universe (2026-05-06 backtest):** dramatic regression vs prior (buggy) numbers.
- BTC_5m_HOLD: was $+14.48 (buggy) → now $+0.27/trade (strict)
- ETH_5m_HOLD: $+12.58 → $+0.97/trade
- SOL_5m_HOLD: $+11.20 → $-0.25/trade
- BTC_15m_HOLD: $+9.42 → $-1.39/trade
- All HEDGE/SELL cells negative or near-zero
- **Permutation test:** all 6 cells p > 0.4 (not statistically distinguishable from random)

The buggy backtest's profitability was largely an artifact of the lookahead. Strategy alpha needs to be re-validated.

**However:** shadow live data shows 15m sleeves making $+11/trade in production. So either:
- Production has a similar lookahead bug (need to verify `fetch_close_asof` semantics on VPS3)
- Or the strict backtest universe selection differs from production (vwap is now 0.90 vs 0.69 before — fires on different markets)

Tools:
- Bug fix: `strategy_lab/meta_classifier/extended_backtest_with_robustness.py:asof()`
- Audit script: `strategy_lab/momo_realfill/verify_lookahead_bug.py`
- Strict matcher (for shadow comparison): `strategy_lab/momo_realfill/match_shadow_strict.py`

---

## 5 · Dynamic sizing cap — implementation logic

**Goal:** stop walking thin books that hurt vwap. Take only what L1 (best ask) supports cleanly.

### Per-asset config

```python
# strategy_lab params + production controller env-driven
TV_POLY_DYNAMIC_STAKE_ENABLED = True

# Min USD on L1 below which we SKIP the trade entirely (L1 too thin to matter)
SKIP_IF_L1_USD_BELOW = {
    "btc": 5.0,    # very rarely triggered (BTC books are deep)
    "eth": 5.0,
    "sol": 3.0,    # SOL thin — skip only when truly empty
}

# Target stake we'd ideally take if liquidity is there
TARGET_STAKE = {"btc": 25.0, "eth": 25.0, "sol": 25.0}  # $25 across the board

# Walk depth tolerance: how much vwap may drift above L1 price (in bps)
# before we cap the stake
MAX_WALK_SLIP_BPS = {"btc": 200, "eth": 200, "sol": 300}  # SOL slightly looser
```

### Decision tree at entry (re-fetch own book, then):

```python
# At t+120s, after rev_2m signal fires:
own_book = await self._fetch_own_book(slot, signal_outcome)
if not own_book or not own_book.get("asks"):
    return self._audit_skip(slot, reason="no_own_book_at_entry")

ask0_p = float(own_book["asks"][0]["price"])
ask0_size = float(own_book["asks"][0]["size"])
l1_usd = ask0_p * ask0_size

# 1. Hard skip if L1 is too thin to bother
if l1_usd < SKIP_IF_L1_USD_BELOW[symbol]:
    return self._audit_skip(slot, reason="l1_usd_too_thin",
                            l1_usd=l1_usd, l1_size=ask0_size, l1_price=ask0_p)

# 2. Spread filter (existing, but enforce HERE not at signal-time)
bid0_p = float(own_book["bids"][0]["price"]) if own_book.get("bids") else 0
spread = ask0_p - bid0_p
if spread > SPREAD_FILTER[symbol]:
    return self._audit_skip(slot, reason="spread_too_wide_at_fill",
                            spread=spread, threshold=SPREAD_FILTER[symbol])

# 3. Compute the target stake we'd ideally take
target = TARGET_STAKE[symbol]

# 4. Simulate the walk to see where vwap lands
vwap_target, _, usd_filled, hit_levels, under = book_walk_fill(
    [lvl["price"] for lvl in own_book["asks"]],
    [lvl["size"]  for lvl in own_book["asks"]],
    target,
)
slip_bps_target = (vwap_target - ask0_p) / ask0_p * 10000

# 5. If walking $25 stays within slip tolerance, take full target
if slip_bps_target <= MAX_WALK_SLIP_BPS[symbol]:
    actual_stake = target
    actual_vwap = vwap_target
else:
    # Walk would slip too much. Cap stake at whatever fills at L1+L2 within tolerance.
    # Binary search the largest stake where slip <= MAX_WALK_SLIP_BPS
    actual_stake = max(
        SKIP_IF_L1_USD_BELOW[symbol],
        find_max_stake_within_slip(own_book["asks"], MAX_WALK_SLIP_BPS[symbol], ask0_p)
    )
    if actual_stake < SKIP_IF_L1_USD_BELOW[symbol]:
        return self._audit_skip(slot, reason="cant_size_within_slip_tolerance")
    actual_vwap, _, _, _, _ = book_walk_fill(
        own_book["asks_p"], own_book["asks_s"], actual_stake
    )

# 6. Place order with actual_stake
await self.executor.place_buy_order(
    token_id=slot.held_token_id,
    qty=actual_stake / actual_vwap,
    limit_px=actual_vwap * 1.01,  # 1% allowance for tick tolerance
)

# 7. Log the dynamic-sizing decision
log.info("poly_updown.dynamic_stake",
         slot=slot.slot_id, target=target, actual=actual_stake,
         l1_usd=l1_usd, ask0_p=ask0_p, vwap=actual_vwap,
         slip_bps=(actual_vwap - ask0_p) / ask0_p * 10000)
```

### Helper: find_max_stake_within_slip

```python
def find_max_stake_within_slip(
    asks: list[dict],
    max_slip_bps: float,
    l1_price: float,
    notional_step: float = 1.0,  # $1 increments
    max_test: float = 100.0,
) -> float:
    """Binary search for largest USD stake such that walking the asks gives
    a vwap within max_slip_bps of L1 price. Returns 0 if even L1's L1_size
    × L1_price exceeds tolerance.
    """
    prices = [float(a["price"]) for a in asks]
    sizes  = [float(a["size"])  for a in asks]
    lo, hi = 0.0, max_test
    best = 0.0
    while hi - lo > notional_step:
        mid = (lo + hi) / 2
        vwap, _, _, _, _ = book_walk_fill(prices, sizes, mid)
        slip = (vwap - l1_price) / l1_price * 10000 if vwap > 0 else float("inf")
        if slip <= max_slip_bps:
            best = mid
            lo = mid
        else:
            hi = mid
    return best
```

### Expected impact (per realfill estimates)

| Cell | Current $/trade | Estimated post-fix $/trade |
|---|---:|---:|
| BTC_5m | $-7.62 | $+0 to $+2 (mostly unchanged — BTC books fat) |
| ETH_5m | $+0.18 | $+3 to $+5 (smaller stake on thin moments) |
| **SOL_5m** | **$-0.06** | **$+8 to $+12** (huge win — SOL was bleeding on walks) |

### Telemetry

Every entry should log:
- `target_stake`, `actual_stake`, `was_capped` (bool)
- `l1_usd`, `l1_size`, `l1_price`
- `walk_vwap`, `walk_slip_bps`, `walk_hit_levels`
- `skip_reason` if skipped (l1_usd_too_thin / spread_too_wide / cant_size_within_slip)

Then a daily roll-up:
- % fires capped vs target
- Avg actual_stake
- Hit rate by capped/uncapped

### Validation criteria post-deploy

- After 24h: SOL_5m skip rate ≈ 25% (those that should be skipped are skipped)
- After 7d: SOL_5m mean_pnl/trade ≥ $+5 (was $-0.06)
- After 7d: avg actual_stake on SOL_5m ~$10-15 (was always $25)

---

## 6 · Multi-Layer Confluence System (Cyclops-inspired) — architecture

This is the next-gen strategy targeted AFTER the momo 5m fix lands. Speced from the comparison vs the Cyclops bot.

### Core architecture: 4 independent confirmation layers

```
                   ┌─ STRUCTURE (macro context) ─┐
                   │  - BTC trend / S+R          │
                   │  - Pattern memory (240 segs)│
                   │  - Asset return history      │
                   └─────────────────────────────┘
                              │
                   ┌─ FLOW (orderflow now) ──────┐
                   │  - CVD over 1m / 5m         │
                   │  - Aggressor ratio (taker)  │
                   │  - L25 OB imbalance         │
                   │  - Coinbase Premium (later) │
                   └─────────────────────────────┘
                              │
                   ┌─ TRIGGER (entry catalyst) ──┐
                   │  - Liquidation magnet       │
                   │  - FVG (fair value gap)     │
                   │  - OFI (order flow imbal)   │
                   └─────────────────────────────┘
                              │
                   ┌─ GUARD (final block) ───────┐
                   │  - Overextension (>0.15%)   │
                   │  - Choppiness > 0.70        │
                   │  - Fake impulse detection   │
                   │  - Extreme price (<0.35,>0.65) │
                   │  - Dead market (90s/$5)     │
                   │  - Min time-to-close ≥1min  │
                   └─────────────────────────────┘
                              │
                              ▼
                   ┌─ TIER CLASSIFIER ───────────┐
                   │  GOLD:   all 4 layers       │  fair_prob 0.72  size 2.0%
                   │  SILVER: STRUCTURE + FLOW   │  fair_prob 0.64  size 1.5%
                   │  BRONZE: FLOW + TRIGGER     │  fair_prob 0.54  size 1.0%
                   │  SKIP:   < 2 layers         │  no entry
                   └─────────────────────────────┘
```

### Build plan (4 modules)

#### Module 1: FLOW engine (uses already-pulled L25 + trades_v2)

```
strategy_lab/flow/
├── __init__.py
├── features.py           # per-(slug, 10s_bucket) compute:
│                         #   - cvd_delta, aggressor_ratio
│                         #   - imb_l1, imb_l5, imb_l10, imb_l25
│                         #   - bid_max_size_l10 (wall detection)
│                         #   - depth_l5, depth_l10, depth_l25
│                         #   - momentum (last 30s buy-vs-sell pressure)
├── build_features.py     # CLI: pre-aggregate raw → parquet (one-time)
└── join_with_signals.py  # merge FLOW with V3/momo signal data
```

**Inputs:** the parquet cache we built (`data/v4/refresh_2026_05_06/cache/`).
**Output:** `data/v4/refresh_2026_05_06/{asset}_flow_features.parquet` (~150 MB).
**Dependency:** none new; reuses `book_walk`, `polymarket_stats`, our new loaders.

#### Module 2: STRUCTURE features

- BTC trend on 1h kline + 4h kline (uptrend / downtrend / sideways)
- Support / resistance from prior-day levels (round numbers, swing highs)
- Pattern memory: at first, defer (low priority for binary 5m markets per Cyclops analysis)

```
strategy_lab/structure/
├── __init__.py
├── btc_trend.py          # rolling regression slope on 1h closes
├── sr_levels.py          # swing-high / swing-low extraction
└── regime_classifier.py  # output: TREND / SIDEWAYS / VOLATILE
```

#### Module 3: TRIGGER features

- Liquidation magnet: are large liquidations clustering nearby?
  - Use `data/v4/refresh_2026_05_06/hl_liquidations_btc_eth_sol.csv` (1.98M rows)
- FVG (Fair Value Gap): 3-candle pattern where wick gap unfilled
- OFI (Order Flow Imbalance): same as FLOW but at trigger time (last 30s)

#### Module 4: GUARD filters + tier classifier

```python
# strategy_lab/confluence/tier_classifier.py

def classify(structure_score, flow_score, trigger_active, guard_blocks):
    if any(guard_blocks):
        return "SKIP"

    s_align = structure_score >= 0.50
    f_align = flow_score >= 0.40
    t_active = bool(trigger_active)

    if s_align and f_align and t_active and structure_score >= 0.50 and flow_score >= 0.50:
        return ("GOLD", fair_prob=0.72, size_pct=0.020)
    if s_align and f_align and structure_score >= 0.30 and flow_score >= 0.40:
        return ("SILVER", fair_prob=0.64, size_pct=0.015)
    if f_align and t_active and flow_score >= 0.40:
        return ("BRONZE", fair_prob=0.54, size_pct=0.010)
    return "SKIP"
```

### Why this beats current momo

| Capability | Current (momo) | Confluence System |
|---|---|---|
| Signal axes | 1 (`ret_2m > q90`) | 4 (STRUCTURE/FLOW/TRIGGER/GUARD) |
| Hedge mechanism | Broken (zero fires) | Multi-tier (CLOB→WS→DB) — see §1 |
| Sizing | Fixed $25 (broken on thin SOL) | Tier-based + dynamic L1-cap (§5) |
| Filter quality | Loose | 4 guards + per-tier confidence threshold |
| Pattern recognition | None | (deferred) 240-segment similarity |

### Build order (recommended)

1. **Wait for momo 5m fix** to land + validate (1-2 weeks)
2. **Build FLOW engine** (module 1) — ~3-5 days, runs offline first
3. **Backtest FLOW alone** on shadow universe — validate alpha exists
4. **Add STRUCTURE features** — ~2-3 days
5. **Add TRIGGER features** — ~2-3 days
6. **Combine + tier-classify** in lab → backtest grand combo
7. **Ship to TV agent** as new sleeve mode `confluence_v1`

---

## Unfinished tasks (priority order)

### 🔴 P0 — TV agent (waiting on agent)

1. **Fix opposite-book fetch for HEDGE/SELL** — `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`
   - 4 commits: diagnose → fix CLOB → add WS BookMirror → enable Storedata fallback
   - Expected impact: hedge fire rate 0% → 90%+, recovers $2-4/trade

2. **Implement dynamic stake cap** — §5 of this doc
   - 7 code changes: re-fetch book, L1 USD gate, spread gate, walk-vwap gate, cap function, telemetry, tests
   - Expected impact: SOL_5m $-0.06 → $+8 to +$12/trade

3. **Pause 5m sleeves until fixes deploy** — operator action
   - 5m bleeding $-1/trade × ~100 fires/day = $-100/day. Pause beats bleed.

### 🟡 P1 — Migration (deadline VPS2 deprecation)

4. **Run VPS2 → VPS3 migration scripts** — `migration_2026_05_06/99_run_all.sh`
   - Migrates: HL liquidations (5M rows), oracle_prices (1.18M), markets (756 older), trades_v2 gap (2.5M), orderbook_snapshots gap (1.5M)
   - Skip: binance_liquidations (will be re-collected from non-geoblocked VPS)
   - Tonight job; ~5-7 hours. Idempotent. README in `migration_2026_05_06/00_README.md`.

5. **Verify VPS3 has parity post-migration** — re-run row-count audit

### 🟡 P1 — Lab work

6. **Build FLOW engine module** (module 1 of confluence) — §6
   - ~3-5 days; uses parquet cache already built
   - Output: per-(slug, 10s_bucket) features parquet

7. **Backtest momo with corrected (strict) asof** + L25 raw data on full Apr-May window
   - We have data; just need to swap `asof` → `asof_strict` in extended_backtest
   - Re-validate the 18-cell numbers; current backtest results overstated by $2-6/trade on HEDGE/SELL cells

8. **Investigate the slugs realfill SKIPPED that production fired on** (78 cases)
   - Did production lack the spread/L1 filter at fill time?
   - Were these all wide-spread or thin-book?
   - Per-trade table: `strategy_lab/results/meta_classifier/momo_5m_slippage_diag.csv`

### 🟢 P2 — Future work

9. **Build STRUCTURE module** (Cyclops Layer 1)
10. **Build TRIGGER module** (Cyclops Layer 3)
11. **Build GUARD filters + tier classifier** (Cyclops Layer 4 + tier logic)
12. **Investigate VPS3 collector daily 5-10% loss** on Polymarket OB — separate ticket
13. **Set up new VPS for binance liquidations** (non-geoblocked region)

---

## Critical files

### Reports
- `strategy_lab/reports/MOMO_3WAY_COMPARISON_2026_05_06.md` — shadow vs L10 vs L25 (period diff)
- `strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md` — TRUE same-trade comparison
- `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md` — hedge bug root cause
- `strategy_lab/reports/MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md` — why 5m loses
- `strategy_lab/reports/MOMO_5M_FIX_PLAN_2026_05_06.md` — 3 fixes ranked
- `strategy_lab/reports/TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` — TV agent prompt
- `strategy_lab/reports/STRATEGY_ARCHITECTURE_2026_05_06.md` — engine inventory
- `strategy_lab/reports/TRADINGVENUE_VS_CYCLOPS_2026_05_06.md` — competitor analysis
- `strategy_lab/reports/DATA_INVENTORY_2026_05_06.md` — VPS2/VPS3/local matrix

### Code (new this session)
- `strategy_lab/loaders/raw_orderbook_l25.py` — canonical L25 loader (parquet-cached)
- `strategy_lab/loaders/prebuild_l25_parquet.py` — gz CSV → parquet converter
- `strategy_lab/momo_realfill/match_shadow.py` — same-trade matcher
- `strategy_lab/momo_realfill/match_shadow_strict.py` — strict-asof variant
- `strategy_lab/momo_realfill/compare_3way.py` — shadow/realfill/backtest comparator
- `strategy_lab/momo_realfill/diagnose_5m_slippage.py` — slippage decomposer
- `strategy_lab/momo_realfill/verify_lookahead_bug.py` — kline asof audit

### Data (new this session)
- `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_orderbook_L25.parquet` — 4.3 GB total
- `data/v4/refresh_2026_05_06/cache/{btc,eth,sol}_trades.parquet` — small
- `data/v4/refresh_2026_05_06/{btc,eth,sol}_orderbook_raw_L25.csv.gz` — 3.3 GB (source for parquet)
- `data/v4/refresh_2026_05_06/{btc,eth,sol}_trades_raw.csv.gz` — 757 MB
- `data/v4/refresh_2026_05_06/markets_full.csv`, `market_resolutions_full.csv`, `binance_klines_full.csv` (refreshed)
- `data/v4/refresh_2026_05_06/hl_liquidations_btc_eth_sol.csv` — 245 MB (1.98M HL liq)
- `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv` — 299 momo fires (server-side JSON-extracted)
- `data/v4/shadow_trades_2026_05_06/momo_signal_fills.csv` — 235 entry-fill events with telemetry

### Migration (ready to fire)
- `migration_2026_05_06/00_README.md` — deployment instructions
- `migration_2026_05_06/99_run_all.sh` — orchestrator
- `migration_2026_05_06/0{1,2,3,4,5}_*.sh` — individual table migrators
- `migration_2026_05_06/local_pull.sh` — local data refresh helper

---

## Production controller signal logic (memorize this)

Production code at `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` (3133 lines on VPS3):

```python
# signal_ts = bars[-1].bar_open of just-closed strategy 5MIN bar
# = polymarket_window_start - 300s
# (one strategy_tf period BEFORE the polymarket market opens)

ws_s = int(window_start_us) // 1_000_000
btc_now = await fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', ws_s,
                                  source='binance-spot-ws')
btc_prior = await fetch_close_asof(symbol_id, '1MIN', ws_s - 300, ...)
ret_5m = math.log(btc_now / btc_prior)

# For momo: ret_2m at t+120 of market
btc_at_t120 = await fetch_close_asof(symbol_id, '1MIN', ws_s + 120, ...)
btc_at_open  = await fetch_close_asof(symbol_id, '1MIN', ws_s, ...)
ret_2m = math.log(btc_at_t120 / btc_at_open)
```

**To replicate in backtest:**
- Use `binance_klines_v2` table on VPS3 with `source='binance-spot-ws'` filter
- For polymarket_window_start = ws, use `ts_query = ws + 120` for momo, `ws - 300` for V3
- Use 1MIN bars only
- `asof` query MUST be end-time-indexed (`time_period_end_us ≤ ts_query × 1e6`) to avoid lookahead

---

## VPS access reminders

```bash
ssh -i ~/.ssh/vps2_ed25519 "root@[2605:a140:2323:6975::1]"   # collector + V1
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7                  # strategy engine + dashboard + binance-spot-ws
```

VPS2 = collector + V1 control arm (Binance collector DEAD due to geoblock since 2026-04-22).
VPS3 = strategy engine + dashboard + Binance spot collector (working — `binance-spot-ws` source).

VPS3 production controller path: `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`.
VPS3 paper executor path: `/opt/tradingvenue/backend/app/venues/polymarket/paper.py`.
VPS3 .env: `/etc/tradingvenue/.env`.

---

## Critical reminders

1. **HEDGE MECHANISM IS BROKEN.** 0 hedges fired in 16h. All HEDGE sleeves are effectively HOLD-only. Don't trust HEDGE PnL until `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` ships.
2. **5m sleeves are bleeding ($-1/trade).** Pause until dynamic-sizing fix deploys.
3. **15m sleeves are working ($+11/trade).** Keep running.
4. **Backtest kline-asof lookahead bug FIXED 2026-05-06.** Re-running showed prior numbers were overstated by $14/trade on HOLD cells (5m). Verify production controller's `fetch_close_asof` doesn't have the same bug — open question §1 below.
5. **VPS2 binance collector DEAD** — use VPS3 `binance-spot-ws` source for klines.
6. **L25 raw + trades_v2 already pulled and cached as parquet.** No need to re-pull. Parquet cache at `data/v4/refresh_2026_05_06/cache/`.
7. **VPS2 deprecation in ~10 days.** Migration scripts ready in `migration_2026_05_06/`. Run before deadline.
8. **Polymarket binary markets resolve at exact tf boundaries** (multiples of 300/900). Shadow `at` timestamp is recorded a few seconds AFTER actual resolution. Slug derivation:
   ```python
   tf_secs = 300 if tf == "5m" else 900
   ws_unix = (at_unix // tf_secs) * tf_secs - tf_secs
   slug = f"{asset}-updown-{tf}-{ws_unix}"
   ```
9. **Median SOL_5m L1 ask = $5.80.** Walking $25 stake forces 5+ level walks. Dynamic sizing cap is mandatory for SOL.
10. **Production telemetry is logged in `trading.events` table on VPS3:**
    - `kind='poly_updown_signal'` (every signal evaluation)
    - `kind='poly_updown_hedge_skip'` (every hedge attempt that failed)
    - `kind='poly_updown_resolution'` (every settled trade)
    - `data` JSON has `bar_ctx_age_ms`, `book_ts`, `fill_price`, etc.

---

## Open questions for next session

1. **Production controller's spread filter timing**: signal-time or fill-time? (Determines whether dynamic-sizing fix needs to move the spread check or just tighten threshold.)
2. **CLOB token-id encoding**: is `slot.no_token_id` stored as TEXT (preserved precision) or BIGINT (truncated)? `grep -n "no_token_id" /opt/tradingvenue/backend/app/controllers/polymarket_updown.py` on VPS3.
3. **Production's `fetch_close_asof` semantics**: does it use `time_period_start_us` or `time_period_end_us`? Lookahead bug only matters in production if it inherits this.
4. **Live trades vs paper**: confirm 0 live momo fires (only paper). Operator should verify.

---

## Quick start commands for fresh session

```bash
cd "/c/Users/alexandre bandarra/Desktop/global"

# Refresh momo shadow data
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sudo -u postgres psql -d storedata -c \"COPY (SELECT at, sleeve_id, data->>'symbol' AS symbol, data->>'tf' AS tf, data->>'signal' AS signal, data->>'outcome' AS outcome, (data->>'won')::boolean AS won, data->>'mode' AS mode, (data->>'hedged')::boolean AS hedged, COALESCE((data->>'partial_bid_exit')::boolean, false) AS partial_bid_exit, (data->>'pnl_usd')::numeric AS pnl_usd, (data->>'entry_price')::numeric AS entry_price, (data->>'entry_qty')::numeric AS entry_qty, data->>'hedge_price' AS hedge_price, data->>'condition_id' AS condition_id, data->>'price_source' AS price_source, data->>'fill_event_id' AS fill_event_id FROM trading.events WHERE kind='poly_updown_resolution' AND sleeve_id ~ 'momo' ORDER BY at) TO STDOUT WITH CSV HEADER\"" \
  > data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv

# Re-run TRUE same-trade matcher
py -X utf8 -m strategy_lab.momo_realfill.match_shadow

# Re-run 3-way comparison (shadow vs L25 realfill vs L10 backtest)
py -X utf8 -m strategy_lab.momo_realfill.compare_3way

# Re-run 5m slippage diagnosis
py -X utf8 -m strategy_lab.momo_realfill.diagnose_5m_slippage

# Verify lookahead bug
py -X utf8 -m strategy_lab.momo_realfill.verify_lookahead_bug
```

---

End of pointer doc. See specific reports for details:
- Hedge bug + fix prompt: `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`
- 5m fixes ranked: `MOMO_5M_FIX_PLAN_2026_05_06.md`
- Engine inventory: `STRATEGY_ARCHITECTURE_2026_05_06.md`
- Cyclops vs us: `TRADINGVENUE_VS_CYCLOPS_2026_05_06.md`
- Same-trade evidence: `MOMO_SHADOW_MATCH_2026_05_06.md`
