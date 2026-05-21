# TV Agent Prompt — Audit ALL Strategies for `asof` Lookahead Bug

Copy/paste this entire block as the prompt for the TV agent (Claude operating VPS3 + lab).

---

## Context

A 60-second lookahead bug was just found in 7+ lab files in `strategy_lab/meta_classifier/`. The bug is in the `asof()` helper used to query 1MIN Binance klines. The buggy version is bar-START-indexed; for any query at time `ts`, it returns the close of the bar OPENING at `ts` — but that bar's close happens 60s LATER. Every kline lookup returns the price 60 seconds in the future.

For production, this means `ret_2m = log(close@(ws+120) / close@(ws))` actually computes `log(close@(ws+180) / close@(ws+60))` — a 2-min window 60 seconds later than intended. The signal becomes near-random (~50% top-decile hit rate). After fixing the lab side and rerunning with strict end-time-indexed asof, the strategy shows:
- Top-decile hit rate jumps from ~50% → 89-94% across all 6 cells
- Walkforward OOS PnL: +$14.13/trade, p=0.0000 on DIRECTION_PERM (1000 draws)

Live shadow shows momo at 58% WR — strongly consistent with production having the same buggy asof. Reference: `strategy_lab/reports/MOMO_FULL_BACKTEST_WS_2026_05_06.md`.

The same bug class likely affects ALL strategies that use kline asof for signal computation, not just momo. Sniper, V3 family, V4, volume, inverse_* all use Binance klines via similar lookups.

## Your task

Audit production code on VPS3 for the same bug class. **Diagnose only. Do not patch yet — report findings first.**

### Step 1 — locate kline asof helpers in production

```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7
cd /opt/tradingvenue
grep -rn "def fetch_close_asof\|def asof\|def fetch_close\|searchsorted" backend/ | head -30
```

Expect to find at least one of:
- `backend/app/services/klines.py` or similar
- `backend/app/data/binance_klines_v2.py` or similar
- Possibly inline in `backend/app/controllers/polymarket_updown.py`

### Step 2 — for each candidate, check the index semantics

For each helper found, capture the function body. Look for the **two telltale patterns**:

**Buggy pattern (start-indexed):**
```python
idx = ts_s.searchsorted(target_ts, side="right") - 1
# returns price_close of bar where ts_s == open time
# bar at ts_s opens at ts_s and closes at ts_s + 60
# this returns a close that is up to 60s in the FUTURE of target_ts
```

**Strict pattern (end-indexed):**
```python
end_us = (ts_s + 60).values * 1_000_000
idx = np.searchsorted(end_us, target_us, side="right") - 1
# returns price_close of bar whose close has happened by target_ts
```

Or in SQL form:
- Buggy: `WHERE time_period_start_us <= :target ORDER BY time_period_start_us DESC LIMIT 1`
- Strict: `WHERE time_period_end_us <= :target ORDER BY time_period_end_us DESC LIMIT 1`

Or BOTH bar timestamps may be used for indexing — verify the comparison key actually matches `time_period_end_us` (or `time_period_start_us + 60` for 1MIN bars).

### Step 3 — verify against real data

For one known unix timestamp where Binance had a clean print, query the helper with target `ts = X` and confirm the return value is the price at time `X` (or earlier), NEVER the price at time `X + 60`.

Test case (run on VPS3):

```sql
-- For ts_query = 1778049720 (= 2026-05-06 09:02:00 UTC)
-- Strict semantics expect: close of bar [09:01:00, 09:02:00] (ends AT 09:02:00)
-- Buggy semantics return:  close of bar [09:02:00, 09:03:00] (60s in the future)

SELECT time_period_start_us, time_period_end_us, price_close
FROM binance_klines_v2
WHERE symbol_id = 'BINANCE_SPOT_BTC_USDT'
  AND period_id = '1MIN'
  AND time_period_start_us BETWEEN 1778049600000000 AND 1778049900000000
  AND source = 'binance-spot-ws'
ORDER BY time_period_start_us;
```

You should see two adjacent bars. The strict-correct answer for `ts_query=1778049720` (= 09:02:00 UTC) is the close of the bar with `time_period_end_us = 1778049720000000` (the one ending exactly at the query time). The buggy semantics would return the close of the bar whose `time_period_start_us = 1778049720000000` (which closes at 09:03:00, in the future).

Then call the production helper:

```python
btc = await fetch_close_asof('BINANCE_SPOT_BTC_USDT', '1MIN', 1778049720, source='binance-spot-ws')
print(btc)
```

Compare to the SQL result. If `fetch_close_asof` returns the close of bar [09:02, 09:03] when asked for `ts=09:02:00`, the bug is present.

### Step 4 — search for the same bug in dependent paths

Whatever the asof helper is, find every caller. They are all suspect:

```bash
grep -rn "fetch_close_asof\|asof(" backend/ | head -40
```

For momo specifically: `backend/app/controllers/polymarket_updown.py` calls `fetch_close_asof` to compute `ret_2m`. Look for the lines where it computes `btc_at_t120` and `btc_at_open`. With buggy asof, `ret_2m` is over the wrong 2-min window.

For sniper / V3 / V4 / volume / inverse: same controller, different `_build_signal_aux` branches. They all consume `slot.btc_close_at_ws` and other kline-derived fields. Check whether their signal computation is also affected.

### Step 5 — report

Write your findings to `/opt/tradingvenue/audit_2026_05_06_asof_lookahead.md`:

1. List every kline asof helper found (file:line, function name).
2. For each: classify as **STRICT** or **BUGGY** (start-indexed) — show the actual code line that determines this.
3. List every caller of each buggy helper, with the strategy mode it affects.
4. Show the test-case verification: query value vs SQL strict value vs buggy value.
5. Estimate the impact per strategy:
   - momo: ret_2m anchor wrong by 60s → 50% top-decile (random) instead of 89%
   - sniper / V3 / V4 / volume: ret_5m or ret_15m anchor wrong by 60s → unknown impact, audit hit rates
   - inverse_*: same as their parent strategy
6. Do NOT fix anything yet. Wait for explicit go-ahead from operator.

### Step 6 — orthogonal verification via production audit data

Pull live shadow data and check whether production's hit rate matches the "buggy asof" or "strict asof" prediction:

```sql
SELECT
  CASE
    WHEN sleeve_id LIKE '%momo%' THEN 'momo'
    WHEN sleeve_id LIKE '%v4%' THEN 'v4'
    WHEN sleeve_id LIKE '%v3_3%' THEN 'v3_3'
    WHEN sleeve_id LIKE '%v3_2%' THEN 'v3_2'
    WHEN sleeve_id LIKE '%v3_1%' THEN 'v3_1'
    WHEN sleeve_id LIKE '%v3%'    THEN 'v3'
    WHEN sleeve_id LIKE '%inverse_sol%'    THEN 'inverse_sol_sniper'
    WHEN sleeve_id LIKE '%inverse_sniper%' THEN 'inverse_sniper'
    WHEN sleeve_id LIKE '%inverse_volume%' THEN 'inverse_volume'
    WHEN sleeve_id LIKE '%volume%' THEN 'volume'
    WHEN sleeve_id LIKE '%sniper%' THEN 'sniper'
    ELSE 'other'
  END AS bundle,
  data->>'tf' AS tf,
  COUNT(*) AS n,
  ROUND(AVG((data->>'won')::int)::numeric, 4) AS hit_rate
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND at > now() - interval '14 days'
GROUP BY 1, 2
ORDER BY 1, 2;
```

Expected interpretations:
- If a bundle's live hit rate ≈ 50-60%, the asof bug is likely affecting it (signal is firing on ~random selections within q90).
- If a bundle's live hit rate ≈ 80-90%, that bundle's signal pipeline is probably already strict (or the bundle's signal doesn't depend heavily on kline asof — possible for some V3 variants).

Add this table to the audit report.

## Constraints

- **DO NOT change any production code in this audit pass.** Diagnostic only.
- DO NOT restart `tv-engine` or any service.
- DO NOT modify any env file.
- The output of this task is `audit_2026_05_06_asof_lookahead.md` — nothing else.
- If you find the bug exists in production, the fix lands in a SEPARATE PR after operator review.

## Why we ask before fixing

Switching production from buggy to strict asof will retime every strategy's signal by 60 seconds. Some strategies might be implicitly relying on the buggy behavior (e.g. their backtest q90 thresholds were calibrated against buggy ret values). Fixing asof without recalibrating thresholds could cause unexpected shifts in fire frequency. Operator wants to see the audit before deciding which strategies to recalibrate vs which to flip cleanly.

## Reference materials in repo

- `strategy_lab/reports/MOMO_FULL_BACKTEST_WS_2026_05_06.md` — backtest evidence the strict version produces real alpha
- `strategy_lab/meta_classifier/extended_backtest_with_robustness.py` line 105 — example of correct strict implementation (already fixed in lab)
- `strategy_lab/meta_classifier/momo_ws_fire_offset_sweep.py` line 60 — second correct example
- `NEXT_SESSION_START_HERE.md` lines 88-115 — context on prior strict-asof rerun
