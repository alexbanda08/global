# TV Agent — Bug Audit on Live VPS3 Sleeves

**Date issued:** 2026-05-06
**Goal:** Audit the live VPS3 strategy engine for three known bugs found in the lab. Confirm whether each is present, quantify the impact for the live sleeves currently running, and propose minimal-risk fixes.

VPS3 SSH: `ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7`

Read-only inspection first. **Do not patch anything until I confirm.** Report findings as a checklist with file:line evidence.

---

## Bug 1 — Kline asof lookahead (HIGH priority)

### Hypothesis
`backend/app/data/bars.py::fetch_close_asof` uses `time_period_start_us <= $4` (bar-OPEN-time indexed). For 1MIN klines, this returns a bar whose `price_close` is up to 60s in the FUTURE of the query timestamp. Every signal computation across all 13 strategy modes inherits this lookahead.

### Verify
1. Read `/opt/tradingvenue/backend/app/data/bars.py` lines 234–315 (both `fetch_close_asof` and `fetch_close_with_ts_asof`). Confirm the SQL still uses `time_period_start_us <= $4`.
2. Check if `binance_klines_v2` has a `time_period_end_us` column or only `time_period_start_us`:
   ```sql
   sudo -u postgres psql -d storedata -c "\d public.binance_klines_v2"
   ```
3. List every caller of `fetch_close_asof` and `fetch_close_with_ts_asof` in the codebase:
   ```
   grep -rn "fetch_close_asof\|fetch_close_with_ts_asof" /opt/tradingvenue/backend/app/
   ```
4. For each caller, identify what the query timestamp is (is it always a bar boundary, or sub-minute?) and what period_id is used (1MIN, 5MIN, etc.).

### Quantify
For one currently-running sleeve (pick `momo` since it fires at `ws+120`), compare what `fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', ws+120, source='binance-spot-ws')` returns today vs. an end-time-indexed equivalent. Pull 100 recent fires from `trading.events`:

```sql
SELECT at, sleeve_id, data->>'symbol' AS symbol,
       data->>'window_start_unix' AS ws,
       data->>'btc_at_t120' AS btc_at_t120,
       data->>'btc_at_open' AS btc_at_open
FROM trading.events
WHERE kind='poly_updown_signal' AND sleeve_id ~ 'momo'
ORDER BY at DESC LIMIT 100;
```

Then for each row, run two queries against `binance_klines_v2`:
- (current/buggy): `WHERE time_period_start_us <= (ws+120)*1e6 ORDER BY time_period_start_us DESC LIMIT 1`
- (correct/strict): `WHERE time_period_start_us + 60_000_000 <= (ws+120)*1e6 ORDER BY time_period_start_us DESC LIMIT 1`

Report: how often do these differ? When they differ, by how many bps does the resulting `ret_2m = log(btc_at_t120 / btc_at_open)` shift?

### Fix recipe (if confirmed)
Smallest possible change to `bars.py:273` and `bars.py:305`:
```sql
-- old
AND time_period_start_us <= $4
-- new  (if no end column exists; assumes 1MIN tf — see note below)
AND time_period_start_us + 60_000_000 <= $4
```

If non-1MIN periods are queried via the same function, this needs to be parameterized by period (60s for 1MIN, 300s for 5MIN, etc.) — derive from `period_id`.

If `time_period_end_us` exists on the table, prefer it directly:
```sql
AND time_period_end_us <= $4
ORDER BY time_period_end_us DESC LIMIT 1
```

**Do not deploy without dry-run on a parallel canary sleeve first.** The fix shifts every signal evaluation by up to 60s — backtested impact in the lab was a regression from $+14/trade (buggy) to $+0.27/trade (strict) on `BTC_5m_HOLD`. If the production fix matches, it will dramatically change live signal firing and PnL.

---

## Bug 2 — REST fill staleness on momo (CRITICAL for momo only)

### Hypothesis
`backend/app/venues/polymarket/paper.py` reads order book via CLOB HTTP `/book` (~1-2s documented cache, but observed at 33s on a pre-market test). On bars where Binance just printed a high-volatility move (= momo's q90 |ret_2m| gate), the REST endpoint serves a pre-absorption book while the matching engine has already absorbed the move. Paper executor walks a stale-favorable book; live taker would walk a much-flatter post-absorption book.

Cross-checked in lab against VPS2 WS L25 ground truth (parquet at `data/v4/refresh_2026_05_06/cache/`):

| bundle | fires at | mean Δ (parquet ask₀ − prod entry_price) | n |
|---|---|---:|---:|
| momo (BTC) | `ws + 120` | **+$0.24** (range +$0.00 to +$0.43) | 7 |
| sniper, v3*, v4, volume, inverse_* | `ws` (bar-close) | ±$0.04 (within noise) | 8 (1 each) |

Non-momo sleeves are fine because they fire BEFORE the absorption clock starts.

### Verify
1. Read `/opt/tradingvenue/backend/app/venues/polymarket/paper.py` lines 1-200. Confirm:
   - Primary book source = `httpx GET /book?token_id=X`
   - Cache TTL = `TV_POLY_PAPER_BOOK_CACHE_TTL` (1s)
   - DB fallback flag = `_db_fallback_enabled` (likely still `False`)
2. Read `backend/app/engine/poly_updown_loop.py` lines 600-720 (the master scheduler). Confirm the comment that `momo` dispatches at `t_plus_120` while every other mode dispatches at `bar-close`.
3. Pull the last 50 momo paper fills from `trading.events`:
   ```sql
   SELECT at, sleeve_id, data->>'condition_id' AS cid,
          data->>'fill_event_id' AS fid,
          (data->>'entry_price')::numeric AS entry_price,
          data->>'price_source' AS price_source,
          data->>'book_ts' AS book_ts
   FROM trading.events
   WHERE kind='poly_updown_resolution'
     AND sleeve_id ~ 'momo'
   ORDER BY at DESC LIMIT 50;
   ```
   Cross-reference each `book_ts` against the `at` (resolution timestamp) — what's the median age of the book at fill time?

### Fix paths (NOT urgent for non-momo)
- **For momo specifically:** add a "fresh-book" gate at fill time that rejects the order if `now - book_ts > 5_000ms`. Skip the trade rather than fill against stale data.
- **System-wide:** the existing WS migration spec (Phase 2) reads from `wss://ws-subscriptions-clob.polymarket.com/ws/market`. Reframe its purpose from "scale enabler" to "execution-correctness fix." Until WS lands, momo paper PnL is fictitious and the `TV_AGENT_LIVE_TRANSITION_SPEC.md` flip for momo must remain blocked.

### Recommendation
**Pause momo live transition.** Other sleeves (sniper, V3 family, V4, volume, inverse_*) are unaffected and can proceed under the existing transition spec.

---

## Bug 3 — Opposite-book fetch returns empty 100% on hedge (HIGH priority)

Already documented in `strategy_lab/reports/TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` (4-commit plan: diagnose → fix CLOB → add WS BookMirror → enable Storedata fallback).

### Verify state
1. Read `backend/app/controllers/polymarket_updown.py` — find `_fetch_opposite_book`. Confirm it still relies on CLOB `/book?token_id=X` for the opposite outcome.
2. Confirm `paper.py:117` still has `_db_fallback_enabled=False` by default.
3. Pull last 24h of hedge attempts:
   ```sql
   SELECT at, sleeve_id,
          data->>'reason' AS reason,
          data->>'book_ts' AS book_ts,
          data->>'opposite_token_id' AS opposite_token
   FROM trading.events
   WHERE kind='poly_updown_hedge_skip'
   ORDER BY at DESC LIMIT 100;
   ```
   Confirm the `book_ts=0` / 100% empty pattern reported in `VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md`.

If state matches, just confirm the fix plan in `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` is still appropriate. Don't deploy yet — this depends on Bug 1 outcome (if signal logic changes, hedge thresholds may need re-tuning).

---

## Additional checks while you're in there

### Source priority for klines
Read where production picks `source='okx-ws'` vs `'binance-spot-ws'` for kline reads (CONTEXT D-09 in `bars.py` docstring mentions OKX as primary because VPS2 was geo-blocked). Since VPS3 has working `binance-spot-ws`, confirm:
- Which source is currently used in `_build_signal_aux` for momo/V3/sniper?
- If it's `okx-ws`, what's the latency vs `binance-spot-ws`?

### CLOB token-id encoding
Confirm `slot.no_token_id` and `slot.yes_token_id` are stored as TEXT (not BIGINT). Polymarket token IDs are 78-digit decimals — BIGINT would silently truncate. From a Python REPL on VPS3:
```python
from sqlalchemy import inspect
# inspect a slot row from whatever table they live in
# print type(slot.no_token_id)
```
Or grep the column type:
```bash
grep -rn "no_token_id\|yes_token_id" /opt/tradingvenue/backend/app/
```

---

## Report format

For each bug, return a section with:

```
## Bug N — [name]

Status: [PRESENT | NOT PRESENT | PARTIALLY MITIGATED]
Evidence: file:line excerpts + SQL query results
Live impact: [quantified — e.g. "X% of momo fires affected, mean shift Y bps"]
Fix recommendation: [smallest safe change, or "blocked on Z"]
Risk of deploying fix today: [LOW / MEDIUM / HIGH] + reason
```

Plus a 1-paragraph executive summary at the top, and a final "What I would deploy this week vs hold" recommendation.

**Read-only audit only.** No code changes, no DB writes, no service restarts. Once I see your report I'll authorize specific fixes.

---

## Context files (already on VPS3 if they were ever shipped, otherwise pulled from git)

If helpful, these lab artifacts document the upstream investigation:
- `strategy_lab/reports/REST_LAG_AFFECTS_ALL_SHADOW_STRATEGIES.md` — revised cross-bundle audit (canonical)
- `strategy_lab/reports/MOMO_REST_LAG_VS_MICROSTRUCTURE.md` — momo-specific writeup
- `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md` — hedge-bug root cause
- `strategy_lab/reports/TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md` — Bug 3 fix plan
- `strategy_lab/reports/TV_AGENT_LIVE_TRANSITION_SPEC.md` — live transition spec (currently BLOCKED for momo)
- Lab fix commits: `24fc23a` (canonical end-time-indexed asof), `5a72e48` (propagated to 24 lab engines), `0211074` (investigation suite)
