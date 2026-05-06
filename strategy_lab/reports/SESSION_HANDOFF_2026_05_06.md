# Session Handoff — 2026-05-06 (momo strategy: design → deploy → first trades)

**Last touched:** 2026-05-06 ~02:00 UTC
**Owner:** alexandre.bandarra (laptop) + TV agent (VPS3 ops)
**Replaces:** SESSION_HANDOFF_2026_05_05.md (kept as historical reference)

**State in one line:** **18 momo sleeves DEPLOYED on VPS3 in shadow mode (Phase 18.5). Concurrency bug found + fixed (ContextVar isolation). First trades firing. Two-day shadow validation underway. If passes → $1 live trades on a single sleeve.**

---

## 🚨 NEXT SESSION — START HERE

### Priority 0 — Pull first 24h of momo shadow data + score against backtest

Approximate target time: **2026-05-07 00:30 UTC** (24h after deploy at 00:28 UTC May 6).

```bash
# Set env vars first (see .env.example)
set -a && source .env && set +a

# Pull all momo trades from VPS3
bash strategy_lab/meta_classifier/refresh_and_analyze.sh

# Or directly:
ssh -i $VPS3_SSH_KEY $VPS3_HOST "PGPASSWORD=$VPS3_TV_PWD psql -h 127.0.0.1 -U tradingvenue -d storedata -c \"\\copy (SELECT sleeve_id, at, data FROM trading.events WHERE kind='poly_updown_resolution' AND sleeve_id LIKE 'poly_updown_%_momo_%' ORDER BY at) TO '/tmp/momo_resolutions_24h.csv' CSV HEADER\""

scp -i $VPS3_SSH_KEY $VPS3_HOST:/tmp/momo_resolutions_24h.csv data/v4/shadow_trades_2026_05_07/momo_resolutions_24h.csv
```

Then write a `momo_shadow_vs_backtest.py` that:
1. Parses the JSON `data` blob
2. Aggregates per (asset, tf, exit_policy) — should be 18 cells
3. Compares to backtest (extended_backtest.csv) — pass/fail per spec §7

### Priority 1 — Validate the bug fix is holding

Confirm at +24h:
- All FILLED rows have populated `entry_phase`, `ret_2m_at_signal`, `abs_ret_2m_threshold`, `bar_ctx_age_ms` fields
- `bar_ctx_age_ms` p95 < 25ms (backtest target was <50ms)
- HOLD vs HEDGE vs SELL begin to differentiate (especially on 15m markets where the rev_bp window is 13min, plenty of time)

### Priority 2 — Pass/fail decision per spec §7

After **2 days** (target 2026-05-08):

| Metric | PASS | FAIL |
|---|---|---|
| Total fires across 18 sleeves | ≥ 100 | < 60 |
| Combined paper PnL | ≥ +$800 | < +$200 |
| Cells profitable | ≥ 4 of 6 | ≤ 2 of 6 |
| BTC_5m hit rate | ≥ 75% (vs backtest 89%) | < 65% |
| Worst (cell, exit) PnL | > -$300 | < -$500 |

If PASS → write `TV_AGENT_LIVE_TRANSITION_SPEC.md` for $1 live trading on `btc_5m_momo_SELL` (highest backtest Sharpe). Stage rollout: 1 live sleeve first, monitor 24h, then enable rest.

### Priority 3 — Plan WS migration (Phase 2)

Production currently uses REST CLOB book fetches. For live trading at scale, need WS subscription. Mirror `venues/hyperliquid/client.py` pattern. Target: <50ms book staleness vs current ~200-500ms + 1s cache. Endpoint: `wss://ws-subscriptions-clob.polymarket.com/ws/market`.

---

## What we built today (2026-05-06)

### 1. The momo strategy — formal definition

```
For each Polymarket BTC/ETH/SOL UpDown market:
  At t + 120s after market opens:
    asset_ret_2m = log( BinanceSpot_close@(ws+120s) / BinanceSpot_close@(ws+0s) )
    Threshold = rolling-14d q90 of |asset_ret_2m| per (asset, tf), daily-cached
    If |asset_ret_2m| < threshold:           SKIP
    If (ask_0 − bid_0) > spread_filter:      SKIP
    If asset_ret_2m > 0:                     buy YES at t+120s ASK
    If asset_ret_2m < 0:                     buy NO at t+120s ASK
    Entry: book-walked top-25 ASK levels for $25 notional
    Exit: HOLD | HEDGE_HOLD | SELL_BID (depending on sleeve variant)
```

**Alpha thesis:** Polymarket's CLOB lags Binance by ~30-120s after a sharp BTC move. We bet in BTC's just-completed direction while Polymarket book is still mispricing. Sometimes the book is so stale we get $0.02 fills on YES tokens that settle at $1 (50× returns on 1.7% of trades).

### 2. Headline backtest — extended dataset (15,370 markets, Apr 22 → May 6)

| Cell | n | hit% | HOLD | HEDGE | SELL | avg vwap |
|---|---:|---:|---:|---:|---:|---:|
| BTC 5m | 325 | 89.2% | $+4,705 | $+5,127 | $+5,141 | $0.694 |
| BTC 15m | 108 | 82.4% | $+1,017 | $+1,006 | $+1,022 | $0.629 |
| ETH 5m | 294 | 92.2% | $+3,700 | $+3,850 | $+3,863 | $0.728 |
| ETH 15m | 101 | 74.3% | $+549 | $+797 | $+816 | $0.650 |
| SOL 5m | 252 | 89.3% | $+2,821 | $+3,236 | $+3,257 | $0.732 |
| SOL 15m | 71 | 84.5% | $+688 | $+640 | $+650 | $0.687 |
| **TOTAL** | **1,151** | — | **$+13,481** | **$+14,656** | **$+14,752** | — |

### 3. Robustness — strict permutation tests

**DIRECTION_PERM** (keep gate fires, randomize sign): tests "is sign of asset_ret_2m informative?"
**GATE_PERM** (random 10% of universe with sign logic): tests "does top-10% gate select better markets?"

| Cell | observed | DIR p-value | GATE p-value |
|---|---:|---:|---:|
| BTC 5m | $+4,705 | **0.0000** *** | **0.0000** *** |
| BTC 15m | $+1,017 | **0.0000** *** | **0.0170** * |
| ETH 5m | $+3,700 | **0.0000** *** | **0.0000** *** |
| ETH 15m | $+549 | **0.0100** ** | 0.1360 ns |
| SOL 5m | $+2,821 | **0.0000** *** | **0.0000** *** |
| SOL 15m | $+688 | **0.0000** *** | **0.0050** ** |

**6/6 cells significant on DIRECTION**, **5/6 on GATE**. Strategy alpha is statistically real on both axes.

### 4. Walkforward — out-of-sample stability

Rolling 7d train / 1d test, refit q90 per window. Combined OOS PnL: **$+5,097** across all 6 cells. **Every cell profitable OOS.** No regime collapse.

### 5. PnL audit — $1,200 outliers are real

Pulled raw VPS2 orderbook snapshots around the biggest outlier (`btc-updown-5m-1776903300`, +$1,200 win). Confirmed: book genuinely had **$0.02 × 3,400+ shares** of YES token at level 0, persistent for 3+ seconds (~16 snapshots/sec). The fill was real, not a backtest artifact. BTC trajectory: dipped −34bp at t=60s (book overcorrected), bounced +31bp by t=120s (signal fires UP, book hasn't repriced), settled +65bp UP. Classic Polymarket-lag exploit.

### 6. Production deployment (Phase 18.5)

**TV agent shipped 18 momo sleeves at 00:28:58 UTC May 6** per `TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md`:

| # | Implementation choice | Reason |
|---|---|---|
| Q1 | **Option C** (10s-tick window detect `now ∈ [ws+120, ws+125]`) | Restart-safe, no lingering asyncio.sleep tasks |
| Q2 | Per-controller `hedge_policy` arg, fallback to module env | Cleaner than 3 separate envs |
| Q3 | New `_maybe_sell_at_bid` is thin wrapper that delegates to existing `_try_bid_exit` | `place_exit_order(side='sell')` already exists in PolyPaperExecutor (paper.py:164, client.py:214) |
| Q4 | BarContext extended with 4 optional fields (`phase`, `btc_at_t_plus_120`, `abs_ret_2m_samples`, `abs_ret_2m_threshold`) | Backward-compat (defaults), same pattern as V3's `btc_15m_prior` addition |
| Q5 | Slot budget — 18 momo + 35 existing = 53 worst-case | OK, sequential dispatch |
| Q6 | Parallel `_RET_2M_SAMPLES_CACHE` keyed by `(symbol_id, tf, day)` | Same daily-eviction property as `_SAMPLES_CACHE` |

### 7. Concurrency bug — found + fixed (the V4-subset bug, again, in disguise)

**Symptom:** in the very first SOL momo trade, all 3 policies (HOLD/HEDGE/SELL) entered identically, lost $25.60, and FILLED audit rows missed `entry_phase`, `ret_2m_at_signal`, etc. NONE rows had them.

**Root cause:** master scheduler dispatches 3 momo controllers × 3 symbols = 9 concurrent tasks via `asyncio.gather`. For ONE controller, three tasks shared `self._bar_ctx_active` (plain instance attribute). Race: task A sets ctx_a, awaits; task B clobbers with ctx_b; task A resumes seeing wrong/None context; late-stage `_audit` reads `self._bar_ctx_active` → sees None → conditional fields dropped.

**Fix:** module-level `ContextVar[BarContext | None]` + property accessor + Token-based reset:
```python
_BAR_CTX_ACTIVE: ContextVar[BarContext | None] = ContextVar("_bar_ctx_active", default=None)

# In on_bar_close:
_token = _BAR_CTX_ACTIVE.set(bar_ctx)
try:
    await self._on_bar_close_impl(symbol, tf, bars)
finally:
    _BAR_CTX_ACTIVE.reset(_token)
```

ContextVar is task-isolated — each asyncio task gets its own snapshot. Eliminates the clobber regardless of await chain length.

**Tests added:** `tests/controllers/test_polymarket_updown_momo.py:test_bar_ctx_active_isolated_across_concurrent_tasks` — 3 concurrent tasks with distinct values, yields scheduler twice, asserts each task reads its own value. Passes with fix; would fail with plain attribute.

**Live confirmation:** 27/27 post-fix audit rows have all 4 enrichment fields populated. `bar_ctx_age_ms` range: 1-7ms (well below the <50ms p95 spec target). FILLED rows haven't yet appeared post-fix (waiting on q90 trigger).

This is the same class of bug as the V4-subset hierarchy issue from May 5 — both were races caused by per-controller state in a shared-controller-instance dispatch model. Phase 24 master scheduler + ContextVar should now eliminate this whole bug class.

### 8. Real-time data flow — verified

Production currently fetches:
- **Klines**: `fetch_close_asof()` from `binance_klines_v2` table on VPS3 (Binance WS ingest, ms latency)
- **CLOB books**: `executor.get_orderbook_snapshot(token_id)` direct REST call to Polymarket CLOB API (~200-500ms)
- **Spreads**: pre-computed per BarContext from live book

Cache: `_SAMPLES_CACHE` (sniper threshold samples, daily) + `_RET_2M_SAMPLES_CACHE` (momo q90 samples, daily). Books NOT cached — fetched fresh per BarContext. The Phase 24 master scheduler builds ONE shared BarContext per (symbol, tf, ws_s) — eliminates redundant fetches.

**Note:** the bar-close BarContext has a stale book by t+120s. Momo's `build_bar_context_t_plus_120` re-fetches the live book at t+120s — confirmed working in deploy.

---

## Files created / modified today

### Code (new)
```
strategy_lab/meta_classifier/pull_tier1_entries.py        sanitized version (env vars)
strategy_lab/meta_classifier/pull_tier1_full.py           extended-universe pull
strategy_lab/meta_classifier/exit_policy_comparison.py    HOLD/HEDGE/SELL on V3+BTC_only
strategy_lab/meta_classifier/exit_policy_multi_asset.py   3 assets × 2 tfs × 8 policies
strategy_lab/meta_classifier/exit_policy_tier1.py         microsecond entries
strategy_lab/meta_classifier/extended_backtest_with_robustness.py  full dataset + perm + walkforward
strategy_lab/meta_classifier/permutation_strict.py        DIRECTION_PERM + GATE_PERM
strategy_lab/meta_classifier/pnl_audit.py                 outlier verification
strategy_lab/meta_classifier/v3_btc_union_realfills.py    V3∪BTC union with realfills
strategy_lab/meta_classifier/v3_production_replay.py      mirror VPS3 production exactly
strategy_lab/meta_classifier/v3_shadow_vs_backtest.py     shadow trade analyzer
```

### Reports (new)
```
strategy_lab/reports/STRATEGY_LOGIC_AND_DATA_GAP.md             strategy logic explainer + 25-level vs 10-level data gap
strategy_lab/reports/EXIT_POLICY_COMPARISON.md                  HOLD/HEDGE/SELL comparison
strategy_lab/reports/EXIT_POLICY_MULTI_ASSET.md                 multi-asset multi-tf
strategy_lab/reports/EXIT_POLICY_TIER1.md                       microsecond-precise entries
strategy_lab/reports/EXTENDED_BACKTEST_ROBUSTNESS.md            ⭐ headline + permutation + walkforward
strategy_lab/reports/PHASE9_LOOKAHEAD_REALFILLS_MULTI.md        BTC/ETH/SOL P9 audit
strategy_lab/reports/PHASE9_LOOKAHEAD_REALFILLS.md              P9 with real fills
strategy_lab/reports/PHASE9_LOOKAHEAD_ENGINE.md                 P9 engine-faithful
strategy_lab/reports/PHASE9_LOOKAHEAD_VALIDATION.md             P9 lookahead test
strategy_lab/reports/PNL_AUDIT.md                               outlier verification
strategy_lab/reports/V3_BTC_UNION_REALFILLS.md                  V3 ∪ BTC_only
strategy_lab/reports/V3_PRODUCTION_REPLAY.md                    mirror VPS3 V3 exactly
strategy_lab/reports/V3_SHADOW_VS_BACKTEST.md                   shadow vs backtest
strategy_lab/reports/TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md    ⭐ THE 18-sleeve deployment spec
strategy_lab/reports/SESSION_HANDOFF_2026_05_06.md              this file
```

### Data (new — under .gitignore due to size)
```
data/v4/refresh_2026_05_06/market_resolutions_full.csv    15,370 markets, Apr 22 → May 6
data/v4/refresh_2026_05_06/klines_full.csv                73,189 1m bars (BTC/ETH/SOL × Binance/OKX)
data/v4/refresh_2026_05_06/tier1_entries/btc_entries_at_t120.parquet   10,042 microsecond entries
data/v4/refresh_2026_05_06/tier1_entries/eth_entries_at_t120.parquet   9,836 entries
data/v4/refresh_2026_05_06/tier1_entries/sol_entries_at_t120.parquet   8,822 entries
data/v4/tier1_entries/btc_entries_at_t120.parquet         older (Apr 22 → May 4) version
data/v4/tier1_entries/eth_entries_at_t120.parquet
data/v4/tier1_entries/sol_entries_at_t120.parquet
strategy_lab/results/meta_classifier/extended_backtest.csv             18 row headline
strategy_lab/results/meta_classifier/permutation_results.csv           degenerate test (kept)
strategy_lab/results/meta_classifier/permutation_strict_results.csv    correct DIRECTION + GATE tests
strategy_lab/results/meta_classifier/walkforward_results.csv           OOS per cell
strategy_lab/results/meta_classifier/exit_policy_tier1.csv             multi-asset/tf × 3 policies
strategy_lab/results/meta_classifier/pnl_audit_per_trade.csv           per-trade dump
strategy_lab/results/meta_classifier/v3_shadow_vs_backtest.csv         shadow analyzer output
```

### Git history
- **Commit f49cb00**: massive multi-session bundle (286 files, +58,086 / −40 lines) — momo strategy + tier1 + robustness + multi-session catch-up
- **Commit 70b4b01**: security hygiene — hardened .gitignore + added .env.example template

Both pushed to `https://github.com/alexbanda08/global` on `main`.

---

## VPS access — credentials NOW VIA ENV VARS (no more literals)

```bash
# Required env vars (see .env.example for template)
export VPS2_HOST='root@[2605:a140:2323:6975::1]'
export VPS2_RO_PWD='<from /etc/tv/tv-ro.env on VPS2>'
export VPS3_HOST='root@185.190.143.7'
export VPS3_TV_PWD='<from /etc/tv/tradingvenue.env or psql .pgpass>'
export VPS3_RO_PWD='<from /etc/tv/tv-ro.env on VPS3>'

# SSH keys (defaults in .env.example)
export VPS2_SSH_KEY="$HOME/.ssh/vps2_ed25519"
export VPS3_SSH_KEY="$HOME/.ssh/vps3_ed25519"

# Then source and run
set -a && source .env && set +a
py strategy_lab/meta_classifier/pull_tier1_full.py
bash strategy_lab/meta_classifier/refresh_and_analyze.sh
```

To get the actual password values (do this once locally, never commit them):
```bash
ssh ... "cat /etc/tv/tv-ro.env | grep TV_RO_PWD_PLAIN"   # both VPSes
ssh root@185.190.143.7 "grep tradingvenue /etc/tv/tradingvenue.env | head -3"  # VPS3 write user
```

---

## Open / Unfinished items

### Critical (will validate or kill momo deploy)
1. **Pull +24h momo data** — first scheduled at 2026-05-07 00:30 UTC. Pass/fail decision per spec §7.
2. **Confirm bug fix on FILLED row** — first momo FILL after 02:00 UTC May 6 should have all 4 enrichment fields. NONE rows already pass (27/27).
3. **Pass/fail at +48h** (2026-05-08 00:30 UTC) — if combined PnL > +$800 across 18 sleeves, prep $1 live.

### Active (auto-running, no action)
4. **TV inverse sleeves** (deployed May 5 16:59 UTC) — running ~28h. Check at +48h (May 7 16:59) and +14d.
5. **18 momo sleeves** (deployed May 6 00:28 UTC) — running.

### Watchlist
6. **WS migration spec** (Phase 2) — required before live trading at scale. Mirror Hyperliquid pattern.
7. **D-04 invariant** ($25 hardcoded) — will need per-controller notional override for $1 live testing. Code change required before live.
8. **Kill `btc_5m_v3_3`** — losing money in shadow per May 5 audit (-$54.38 on 8 trades).
9. **Kill `sol_*_v3` family** — bleeding heavily (-$390/-$103/-$158 across variants per May 5). Inverse sleeves should profit from this.

### Deferred
10. **GATE_PERM not significant for ETH 15m** (p=0.136). Sample size n=101 may be too thin. Re-test after more data accumulates.
11. **Phase 9 (TFI)** — dominated by BTC_only (BTC has alpha; P9 doesn't add). Drop from union. Already proven in `PHASE9_LOOKAHEAD_REALFILLS_MULTI.md`.
12. **Re-aggregate book_depth_v3_full.csv** for Apr 22-May 6 (existing covers Apr 22-May 4). 1-day gap doesn't materially affect backtest but worth noting.
13. **Per-asset Kronos retraining** — Kronos closed (importance = 0). Not pursuing.

---

## Quick-start commands for next session

```bash
# 0. Set env (after creating .env from .env.example)
set -a && source .env && set +a

# 1. Pull fresh momo trades from VPS3
ssh -i $VPS3_SSH_KEY $VPS3_HOST "PGPASSWORD=$VPS3_TV_PWD psql -h 127.0.0.1 -U tradingvenue -d storedata -t -c \"SELECT sleeve_id, COUNT(*) FROM trading.events WHERE kind='poly_updown_resolution' AND sleeve_id LIKE 'poly_updown_%_momo_%' GROUP BY sleeve_id ORDER BY sleeve_id\""

# 2. Pull full audit data for analysis
ssh -i $VPS3_SSH_KEY $VPS3_HOST "PGPASSWORD=$VPS3_TV_PWD psql -h 127.0.0.1 -U tradingvenue -d storedata -c \"\\copy (SELECT sleeve_id, at, data FROM trading.events WHERE kind='poly_updown_resolution' AND sleeve_id LIKE 'poly_updown_%_momo_%' ORDER BY at) TO '/tmp/momo_resolutions.csv' CSV HEADER\""
mkdir -p data/v4/shadow_trades_$(date +%Y_%m_%d)
scp -i $VPS3_SSH_KEY $VPS3_HOST:/tmp/momo_resolutions.csv data/v4/shadow_trades_$(date +%Y_%m_%d)/momo_resolutions.csv

# 3. Write momo_shadow_vs_backtest.py and run

# 4. If pass-criteria met → write TV_AGENT_LIVE_TRANSITION_SPEC.md for $1 live trading
```

## Suggested first message to next session

> Pick up from `strategy_lab/reports/SESSION_HANDOFF_2026_05_06.md`. 18 momo sleeves deployed on VPS3 at 00:28 UTC May 6. Pull all `poly_updown_%_momo_%` resolutions from `trading.events` since deploy, aggregate per (asset, tf, exit), compare to backtest in `EXTENDED_BACKTEST_ROBUSTNESS.md`. Verify the ContextVar bug fix held: first FILL row should have populated entry_phase + ret_2m_at_signal + abs_ret_2m_threshold + bar_ctx_age_ms. Score against pass criteria in `TV_AGENT_MOMO_SLEEVES_IMPLEMENTATION.md` §7. If pass at +24h or +48h → start prepping $1 live transition spec.

---

*End of SESSION_HANDOFF_2026_05_06.md. Open items: validate momo shadow against backtest, confirm bug fix on FILL rows, plan WS migration before live.*
