# Session Handoff — `ws_s` convention bug + canonical dataset
_Generated: 2026-05-10 (end of investigation session)_
_Target reader: next-session strategy/backtest agent_
_Status: ROOT CAUSE CONFIRMED. No more diagnosis needed. Ready to ship corrected backtests._

---

## TL;DR (read this first)

1. **Canonical dataset is built and works.** All backtests must read from
   `data/v4/canonical/load.py`. Schema, conventions, build script, README all in
   `data/v4/canonical/`. Total ~5.9 GB on disk.

2. **`market_resolutions_v2` was contaminated by ~9% binance-resolved markets**
   (`price_source = binance-klines-1m`). Canonical filters them out. Storedata
   agent owns the upstream fix (their 6-step plan).

3. **A previously-undetected lookahead bug** in EVERY backtest in this repo
   was found and quantified:

   - **Production momo controller** uses `ws_s = slot_start_us/1e6 − window_s`
     (i.e., the PREVIOUS slot's start). Production fires at `ws_s + 120` of
     the PRIOR slot — observing the trailing 2 min BEFORE the new slot opens.
   - **All my backtests** (and most existing scripts in `strategy_lab/`) used
     `ws_s = slot_start_us/1e6` (the LITERAL slot start). This observes the
     FIRST 2 min INSIDE the slot — strongly correlated with the 5-min outcome
     by construction → inflated hit rate.

   Empirical proof: ETH 5m, slug `eth-updown-5m-1778342700`. Production logged
   `ret_2m_at_signal = -0.000846`. With buggy ws_s: backtest computes
   `+0.001260`. With corrected ws_s: backtest computes `-0.000846` (matches
   12 decimals).

   Hit-rate impact (16-day chainlink-only universe):
   - Buggy: **85.5%** overall, 86–92% on 5m
   - Corrected: **48.1%** overall, 45–50% on 5m
   - Production live (7d): ~50% on 5m

4. **The momo strategy as deployed is structurally unprofitable at observed
   fills.** Hit ~48–50% with avg vwap ~0.69 → breakeven needs ~77% hit. The
   strategy is ~28 pp below breakeven. Production's recent positive PnL
   (May 8 +$623) was variance, not edge.

5. **Action for next session**: rewrite all existing backtest harnesses to
   use the corrected `ws_s = slot_start − window_s`. Re-run, regenerate
   reports. Then decide what to do with momo (deprecate? gate harder? new
   anchor?).

---

## Project state — what's on disk, what works

### Canonical dataset (`data/v4/canonical/`)

```
data/v4/canonical/
├── README.md                            ← read this for schema + conventions
├── build.py                             ← rebuild script (re-pulls VPS2+VPS3)
├── load.py                              ← unified API for all sessions
├── resolutions.parquet                  ← chainlink-only union (1.9 MB)
├── resolutions_from_rtds.parquet        ← locally re-derived (1.4 MB, 99.79%
│                                          match w/ upstream)
├── klines_1m.parquet                    ← VPS3 binance + VPS2 cex (19 MB)
├── chainlink_rtds.parquet               ← 2.75 M rows of 1Hz RTDS (48 MB)
├── orderbook_l25/{btc,eth,sol}.parquet  ← Polymarket L25 (3.8 GB / 831 MB / 346 MB)
│                                          (currently corrupt — load.py reads
│                                          from refresh_2026_05_06/cache + 05_09
│                                          delta directly, see Notes below)
├── trades_polymarket/{btc,eth,sol}.parquet  ← from refresh_2026_05_06 cache
├── tier1_entries_at_t120/{btc,eth,sol}.parquet  ← REBUILT against chainlink-only
└── _results/                            ← backtest outputs from this session
    ├── b0_g6_per_trade_*.csv
    ├── b0_g6_summary.csv
    ├── coverage.csv
    ├── lag_sweep_summary.csv
    ├── momo_v1v2_per_trade_*.csv
    ├── momo_v1v2_summary.csv
    ├── momo_v1_correct_ws_per_trade.csv  ← THE GOOD ONE (781 trades, 48% hit)
    ├── momo_v1_correct_ws_per_cell.csv
    ├── xref_live_vs_backtest.csv
    └── _xref_live.py + _lag_sweep.py + _momo_v1_correct_ws.py + ...
```

### Top-level project context

- `CLAUDE.md` (root) — points all agents to canonical
- `NEXT_SESSION_START_HERE.md` (root) — has DATA SOURCE section pointing to canonical

### The deprecated dirs

- `data/v4/refresh_2026_05_02/` (417 MB) — bucket books, deprecated 10-level
- `data/v4/refresh_2026_05_06/` (9.8 GB) — raw L25, trades parquet caches.
  **Still needed** by canonical load (BTC L25 source).
- `data/v4/refresh_2026_05_09/` (1.7 GB) — L25 delta, klines.
  **Still needed** by canonical load (May 6→9 delta for L25).

Each has a `_DEPRECATED.md` marker. Don't delete until all 30+ scripts under
`strategy_lab/` have migrated to canonical.

---

## The two bugs found this session (read in order)

### Bug 1: binance-resolved contamination (FIXED in canonical)

`market_resolutions_v2` on VPS2/VPS3 has a `price_source` column. Values:
- `chainlink-fast` (12,033 rows) — current production source
- `chainlink` (5,211 rows) — earlier transition source
- `binance-klines-1m` (1,759 rows) — **older markets backfilled before chainlink
  stream went live; uses binance 1m kline data to derive Up/Down outcome**
- `(empty)` (714 rows) — pending/unresolved

When my (or any) backtest reads the `outcome` flag for `binance-klines-1m` rows,
it gets a flag that is **tautologically correlated with binance signals** because
both signal AND outcome come from binance klines. This inflated baseline PnL by
~$14k in the prior `MOMO_CHAINLINK_ONLY` analysis.

Production resolution writer: `derive_market_strikes.py` on VPS3 (NOT
`resolutions_fast.py`). Logic per docstring:

```
Source priority per row:
  1. oracle_prices_v2 (Chainlink Data Streams) — for slot_start_us at or after
     our oracle start. Within ±30 s window.
  2. binance_klines_v2 1MIN — fallback for markets older than our oracle, OR
     when chainlink stream has gaps within 30s.
```

The fallback is **still actively writing** binance-resolved rows on VPS3
(newest at `2026-05-09 22:10`). Storedata agent's plan addresses this.

**Canonical filter**: `load_resolutions(source="upstream")` keeps only rows with
`price_source ∈ {chainlink-fast, chainlink}`. Drops the 1,759 + 714 = 2,473 bad
rows. Net: 18,192 chainlink-only markets kept.

**Even better**: `load_resolutions(source="rtds")` (the DEFAULT) re-derives
outcomes from local `chainlink_rtds.parquet` directly. 12,522 markets covered
(window: 2026-04-28 18:40 → 2026-05-09 23:35), 99.79% match with upstream.

### Bug 2: my backtest's `ws_s` lookahead (the ACTUAL big bug)

**The smoking gun**, confirmed by direct math against production's logged value:

For `eth-updown-5m-1778342700` (5m market, slot 18:05–18:10 CEST):

```
VPS3 binance-spot-ws ETH 1MIN bars (real DB rows):
  bar [17:59, 18:00) end_us=1778342400  close=2317.63
  bar [18:00, 18:01) end_us=1778342460  close=2316.66
  bar [18:01, 18:02) end_us=1778342520  close=2315.67
  bar [18:04, 18:05) end_us=1778342700  close=2317.25
  bar [18:06, 18:07) end_us=1778342820  close=2320.17

Production logged:
  ret_2m_at_signal = -0.000846049302619721

My buggy backtest (ws_s = slot_start = 1778342700):
  log(close@(ws_s+120) / close@ws_s) = log(2320.17 / 2317.25) = +0.001260

Production-correct backtest (ws_s = slot_start - 300 = 1778342400):
  log(close@(ws_s+120) / close@ws_s) = log(2315.67 / 2317.63) = -0.000846  ← EXACT match
```

**Production's `ws_s` is the PREVIOUS slot's start, not the current slot's start.**

This means production fires at "t+120 of ws_s" = previous_slot_start + 120s
= 3 minutes BEFORE the current slot opens (for 5m markets). It observes 2 minutes
of pre-window asset momentum and bets on the upcoming slot's outcome.

This is the strike-chain convention: settlement of slot N = strike of slot N+1,
so the trailing 2 min of slot N's price action gives info about slot N+1's
direction. **Pre-window momentum signal**, weak predictive power → ~50% hit.

My backtest used `ws_s = slot_start`, observing the FIRST 2 minutes INSIDE the
slot. **In-window momentum signal**, strong predictive power by construction →
~85% hit. Inflated.

### Hit-rate confirmation (16-day chainlink-only universe)

| | Buggy backtest | **Corrected** | Production (7d live) |
|---|---:|---:|---:|
| n | 1,736 | **781** | ~290 |
| Overall hit% | 85.5 | **48.1** | ~50 |
| BTC 5m | 86.4 | **48.3** | ~50 |
| ETH 5m | 90.1 | **44.9** | ~50 |
| SOL 5m | 91.6 | **49.6** | ~56 |
| BTC 15m | 74.9 | 57.5 | 75 |
| ETH 15m | 75.9 | 40.0 | 70 |
| SOL 15m | 73.8 | 50.0 | 50 |

**The corrected backtest matches production hit rates within sample noise.**

The 15m results have small N (4-40 trades) so the per-cell numbers are noisy,
but overall hit collapses from 85.5% → 48.1% — exactly what production sees.

---

## What every backtest harness in this repo got wrong

Every script under `strategy_lab/meta_classifier/` and most under
`strategy_lab/confluence/` and `strategy_lab/momo_realfill/` does some variant
of:

```python
# WRONG — observes inside the prediction window
df["ws"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64")  # = slot_start
ret_2m = log(close@(ws + 120) / close@ws)
```

**The fix is uniform**:

```python
# CORRECT — matches production's pre-window momentum
df["window_s"] = df.tf.map({"5m": 300, "15m": 900})
df["ws_s"] = df.slug.str.extract(r"-(\d+)$")[0].astype("int64") - df["window_s"]
ret_2m = log(close@(ws_s + 120) / close@ws_s)

# Fire time also shifts:
fire_us = (ws_s + 120) * 1_000_000
# = (slot_start - window + 120) * 1_000_000
# = for 5m: 3 min BEFORE slot opens (slot_start - 180s)
# = for 15m: 13 min BEFORE slot opens (slot_start - 780s)
```

**Important**: `simulate_hedge` / `simulate_sell_bid` exit-monitoring tick
windows must also use `ws_s` (the corrected value), NOT slot_start. The exit
ticks scan from `fire_us` to `slot_end_us`, but `slot_end_us = slug_start +
window` regardless (resolution time IS the slug). So:

```python
# Exit policies still resolve at slot_end_us (slug-derived)
resolve_us = (slug_start + 0) * 1_000_000  # actually slot_end is slug_start + 0 for some interpretations — check market_resolutions_v2
# IMPORTANT: market_resolutions_v2 has both slot_start_us and slot_end_us columns.
# slot_start_us = slug_start (slug suffix * 1e6). slot_end_us = slot_start + window.
# Outcome resolves on price@slot_end_us vs price@slot_start_us.
```

Wait — the corrected `ws_s` is BEFORE the slot. The slot still resolves at
`slot_end_us = slug_start + window`. Hedge tick windows go from `fire_us` (=
ws_s + 120 = slug_start - window + 120 — for 5m this is slug_start - 180)
through to `slot_end_us`. That's a 3 + 5 = 8 minute hedge window for 5m.

Also: tier1 entry book. Production fires at `ws_s + 120` and looks up book at
that wallclock. For 5m: 3 min BEFORE slot opens. **Polymarket book at that
moment is for the OPENING slot (slug_start)** since polymarket markets open
~5-10 min ahead of their slot_start to allow pre-trading. Verify this with
the `tier1_entries_at_t120/` parquet column `dt_abs` — it captures the offset
between requested target and actual book snapshot found.

---

## Reports that need correction

These all have INFLATED hit rates / PnL because of the buggy ws_s:

1. `MOMO_V1V2_CANONICAL_2026_05_10.md` — v1 hit 85.5%, v2 hit 67.5%. Both inflated.
2. `MOMO_FEED_LAG_INVESTIGATION_2026_05_10.md` — partial diagnosis (correct that
   feed lag explains 15m, wrong about residual 5m gap source — actual cause is
   ws_s convention, NOT spread filter / cid resolution / threshold drift).
3. `MOMO_CHAINLINK_ONLY_2026_05_09.md` — claims B0 baseline ~−$1.3k. Unsure if
   inflated; depends on what ws_s the analysis used.
4. `MOMO_COINBASE_LEAD_2026_05_09.md` — G6 claims +75% hit. Almost certainly
   inflated; using ws_s = slot_start.
5. `MOMO_COINBASE_ADDALPHA_2026_05_09.md` — same.
6. `EXTENDED_BACKTEST_ROBUSTNESS.md` and earlier momo runs — all use buggy ws_s.

Their VERDICTS (none of those strategies were profitable in clean form either)
likely still hold qualitatively, since the strategy is ~28 pp below breakeven.
But magnitudes need re-deriving.

---

## What to do next session (priority order)

### 1. Lock the convention in code [30 min]

Update `data/v4/canonical/load.py` to add a helper:

```python
def slug_to_ws_s(slug: str, timeframe: str) -> int:
    """Return production's ws_s = slot_start - window. This is the timestamp
    used for ret_2m anchoring and fire-time scheduling — NOT the slot_start."""
    slot_start = int(slug.rsplit('-', 1)[1])
    window_s = {"5m": 300, "15m": 900}[timeframe]
    return slot_start - window_s
```

Update `CLAUDE.md` (root) and `data/v4/canonical/README.md` with a prominent
warning:

```
🚨 CRITICAL CONVENTION: ws_s ≠ slot_start

For all momo / signal computations:
   ws_s = slug_suffix - window_s   (production controller convention)
        = slot_start_us/1e6 - window_s
   ret_2m = log(close@(ws_s+120) / close@ws_s)
   fire_us = (ws_s + 120) * 1_000_000

ws_s is the PREVIOUS slot's start. Production observes 2 min of pre-window
momentum to bet on the upcoming slot's outcome.

If you anchor at slot_start instead of ws_s, you observe the first 2 min
INSIDE the prediction window — that's lookahead. Hit rate inflates 25-40 pp.
```

### 2. Rewrite the buggy backtests [2-4 h]

Take this template (`data/v4/canonical/_results/_momo_v1_correct_ws.py` is the
working reference) and apply to:

- `momo_full_universe_validation.py` — main full-universe runner
- `momo_coinbase_lead.py` — coinbase G-variants
- `momo_coinbase_addalpha.py` — coinbase F/E variants
- `momo_chainlink_only.py` — chainlink-only baseline
- `extended_backtest_with_robustness.py` — older multi-strategy sweep

Run each, write CSVs to `data/v4/canonical/_results/`, regenerate reports.

### 3. Verify with cross-reference vs production [30 min]

Re-run `_xref_live.py` against the corrected backtests. Should now show:
- Signal direction match: 90%+ (was 46.9%)
- Hit rate match: within 5 pp (was 35 pp gap)

### 4. Update prior reports with addendum [1 h]

Add a "RETROACTIVE CORRECTION" section at the top of each affected report
with the corrected numbers. Don't delete original — leave for transparency.

### 5. New questions opened by the corrected results

a) **Does the strategy have ANY edge at production-realistic ws_s?** Corrected
   hit ~48-50% with vwap ~0.69 → losing. Could a tighter gate (q95? q99?) push
   hit toward 77% breakeven? Test with threshold sweep on corrected backtest.

b) **Coinbase variants** (G2/G3/G6 lead-lag) — were the +6 pp hit improvements
   real, or also inflated by ws_s lookahead? Need re-run.

c) **15m markets** — corrected backtest shows BTC 15m hit 57.5% (small N=40),
   production live 75% (N=12, also small). Either could be variance.
   Need more data before concluding 15m has edge.

d) **Production positive PnL on May 8** (+$623, 58% hit) — was that genuine
   alpha (regime / book mispricing) or just variance? Run permutation test
   on production's 290 live trades.

---

## Code snippets you'll need

### Confirm canonical works

```bash
cd /c/Users/alexandre\ bandarra/Desktop/global
PYTHONIOENCODING=utf-8 python -X utf8 data/v4/canonical/_sanity.py
# Should print: === ALL CHECKS PASSED ===
```

### Correct ws_s template

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (load_resolutions, load_klines_asof, load_orderbook_l25_streaming,
                   asof_strict)
from book_walk import book_walk_fill   # strategy_lab/

# Universe
res = load_resolutions(source="upstream")  # chainlink-only filter applied
res["window_s"] = res.timeframe.map({"5m": 300, "15m": 900})
res["slug_start_s"] = res.slot_start_us // 1_000_000
res["ws_s"] = res.slug_start_s - res.window_s   # ← THE FIX

# Klines
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")

# ret_2m, anchored on ws_s (NOT slug_start)
def ret_2m(ws_s):
    c0 = asof_strict(end_us, prices, ws_s * 1_000_000)
    c1 = asof_strict(end_us, prices, (ws_s + 120) * 1_000_000)
    return math.log(c1/c0) if c0 > 0 and c1 > 0 else float("nan")

# Fire time — same anchor
fire_us = (ws_s + 120) * 1_000_000

# L25 entry book lookup
books = load_orderbook_l25_streaming("btc", slugs={...})
book = find_book(books, slug, held, fire_us)
```

### Production sleeve PnL pull (for cross-check)

```bash
ssh -i "/c/Users/alexandre bandarra/.ssh/vps3_ed25519" root@185.190.143.7 \
  "sudo -u postgres psql -d storedata -A -F'|' -t -c \
  \"SELECT sleeve_id, COUNT(*) AS n,
           ROUND(100.0 * SUM(CASE WHEN (data->>'won')::bool THEN 1 ELSE 0 END) / COUNT(*), 2) AS hit_pct,
           ROUND(SUM((data->>'pnl_usd')::numeric)::numeric, 2) AS pnl_total,
           ROUND(AVG((data->>'pnl_usd')::numeric)::numeric, 4) AS pnl_mean
     FROM trading.events
    WHERE kind = 'poly_updown_resolution'
      AND sleeve_id LIKE '%momo%'
      AND at > NOW() - INTERVAL '7 days'
    GROUP BY sleeve_id
    ORDER BY pnl_total DESC;\""
```

### Quick math verification (anyone can re-run)

```python
import math
# eth-updown-5m-1778342700 — production logged ret_2m_at_signal = -0.000846049302619721

# DB binance-spot-ws ETH 1MIN bars at and around ws=1778342700:
# bar [17:59, 18:00) close = 2317.63   ← end_us = 1778342400 = ws_s_PROD = slug_start - 300
# bar [18:01, 18:02) close = 2315.67   ← end_us = 1778342520 = ws_s_PROD + 120

# Production interpretation:
prod = math.log(2315.67 / 2317.63)
print(f"prod ret_2m = {prod:.18f}")
# prod ret_2m = -0.000846059...  ← matches production logged value!

# Buggy interpretation:
buggy = math.log(2320.17 / 2317.25)  # close@18:07 / close@18:05
print(f"buggy ret_2m = {buggy:.18f}")
# buggy ret_2m = +0.001259898... ← way off, opposite sign
```

---

## Key files to read in next session

| File | Why |
|---|---|
| `CLAUDE.md` (root) | Read first — entry point for any agent |
| `data/v4/canonical/README.md` | Schema, conventions, refresh procedure |
| `data/v4/canonical/load.py` | Load API to use for all backtests |
| `data/v4/canonical/build.py` | Refresh script (run weekly or per-need) |
| `strategy_lab/reports/MOMO_FEED_LAG_INVESTIGATION_2026_05_10.md` | Earlier (partial) diagnosis — superseded by THIS doc |
| `data/v4/canonical/_results/_momo_v1_correct_ws.py` | The working corrected backtest — copy this template |
| `data/v4/canonical/_results/_xref_live.py` | Cross-reference live vs backtest harness |
| `data/v4/canonical/_results/momo_v1_correct_ws_per_cell.csv` | Final corrected per-cell results |
| `/opt/tradingvenue/backend/app/engine/poly_updown_loop.py` (VPS3) | Production controller — `build_bar_context_t_plus_120` is the source of truth for ws_s convention |

---

## Open issues delegated to other agents

### Storedata agent (their existing 6-step plan)

1. VPS2 → VPS3 chainlink merge for 04-24→04-28 (~5 min, recovers ~4k VPS3 rows)
2. Re-run derive on both VPSs (~5 min, confirms no Binance contamination)
3. Locate TV trading.events, cross-check vs our chainlink rows (~30 min)
4. Implement chained-strike check (Step 3) (~1 h)
5. UMA on-chain decoder spike (~2 h)
6. Unified `market_resolutions_v3` view with confidence column (~1 h)

### TV agent / production controller

1. Audit `BinanceMarketDataFeed.get_close_asof(symbol, ts_s)` semantics —
   confirm it returns 1MIN bar close, not last tick. (Earlier hypothesis
   was that this caused part of the gap; corrected `ws_s` analysis suggests
   feed-vs-DB is NOT the main issue, but worth verifying anyway.)
2. **More importantly**: now that we know the strategy is structurally below
   breakeven (~50% hit at vwap 0.69, breakeven ~77%), decide whether to:
   - Tighten gate (q95 / q99 instead of q90)
   - Add additional filters (e.g., spread-z, depth-imbalance)
   - Deprecate momo and try a different anchor
   - Use a structurally different strategy (mean-reversion?)
3. Fix corrupt canonical orderbook_l25/btc.parquet (the file produced by
   `build.py --step orderbook` is truncated/corrupt for BTC; load.py works
   around by reading sources directly).

---

## Numbers cheat-sheet (memorize these)

| Metric | Value | Notes |
|---|---:|---|
| Total chainlink-resolved markets in canonical | 18,192 | over Apr 24 → May 9 |
| Total in chainlink_rtds-derived (locally) | 12,522 | Apr 28 18:40 → May 9 (RTDS window limit) |
| Production momo HOLD 7d trades | ~290 | net +$259 / +$0.89 per trade |
| Production momo HOLD May 8 PnL | +$623 | the lucky day |
| Production momo HOLD May 9 PnL | −$361 | losing |
| Production hit rate (5m, 7d) | ~50% | momo HOLD only |
| Production hit rate (15m, 7d) | ~70% | momo HOLD only |
| Buggy backtest v1 hit rate | 85.5% | LOOKAHEAD via wrong ws_s |
| Corrected backtest v1 hit rate | 48.1% | matches production |
| avg_vwap (entry) | ~0.69 | corrected backtest, similar live |
| Breakeven hit at vwap 0.69 | ~77% | (1 / (1 + 0.31×0.98)) |
| Margin below breakeven | ~28 pp | hit 48% vs needed 77% |

---

## End of handoff

Next session: start by reading this file in full, confirm canonical works
(run `_sanity.py`), then begin rewriting backtests with corrected ws_s.

If anything is unclear, the empirical proof in the "Bug 2" section can be
re-derived from VPS3 in 5 minutes. The math is exact (12 decimal places).
