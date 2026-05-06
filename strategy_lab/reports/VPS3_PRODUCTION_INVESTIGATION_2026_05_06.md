# Production Controller Investigation — VPS3
**Generated:** 2026-05-06
**Scope:** root-cause why momo HEDGE policy has fired ZERO hedges in 215 resolutions, while realfill simulation predicted 99.8% feasibility on the same markets.

## TL;DR — root cause identified

**The production controller's `_fetch_opposite_book()` returns empty 100% of the time** (`book_ts=0`, all 233 hedge_skip events). Reason: it queries Polymarket CLOB HTTP `/book` for the opposite-side token, which returns empty/error for thinly-traded sides, AND the **Storedata DB fallback is disabled by default** (`_db_fallback_enabled=False`).

Storedata HAS the data — verified directly: for the example slug `sol-updown-5m-1778058000` outcome=Down, **89 snapshots over 3hrs with 98% ask coverage** (asks at $0.70-$0.78 with sizes 5-55 right when controller said "no_asks").

**The controller intentionally rejects fresh L25 data from Storedata and prefers a CLOB endpoint that doesn't have it.**

## Evidence chain

### 1. ZERO hedges across all 18 momo sleeves (215 resolutions, 16h)

| Sleeve | resolutions | hedged | partial_exit | exit_fire% |
|---|---:|---:|---:|---:|
| `poly_updown_sol_15m_momo_SELL` | 6 | 0 | 2 | 33.3% |
| `poly_updown_sol_5m_momo_SELL` | 30 | 0 | 3 | 10.0% |
| ALL OTHER 16 SLEEVES | 174 | **0** | **0** | **0%** |

Realfill on same markets: 99.8% feasibility for both HEDGE and SELL.

### 2. All 233 hedge_skip events have `book_ts=0`

```
SELECT COUNT(*) FILTER (book_ts=0) FROM hedge_skip events
→ 233 of 233 (100%)
```

Every hedge attempt returned with empty book object.

### 3. The controller code path

`controllers/polymarket_updown.py:2512` — controller calls `_fetch_opposite_book()`.

`controllers/polymarket_updown.py:2676` `_fetch_opposite_book()`:
```python
get_for_outcome = getattr(self.executor, "get_orderbook_for_outcome", None)
if get_for_outcome is not None:
    try:
        return await get_for_outcome(slot.condition_id, opposite_outcome)
    except Exception:
        pass

token_id = slot.no_token_id if slot.signal == "UP" else slot.yes_token_id
return await self.executor.get_orderbook_snapshot(token_id)
```

`venues/polymarket/paper.py:191` `get_orderbook_snapshot()`:
```python
book = await self._fetch_orderbook(token_id)
ts = int(book.get("ts", 0) or 0)
now = int(time.time())
if ts == 0 or (now - ts) > STALE_AFTER_SECONDS:  # 30s
    return {"bids": [], "asks": [], "ts": 0, "_stale": True}
return book
```

`venues/polymarket/paper.py:236` `_fetch_orderbook()`:
```python
# Primary: CLOB /book HTTP.
if clob_attempted:
    book = await self._fetch_clob_orderbook(token_id)

# Fallback: Storedata snapshot.
# Phase 18.2 V2 PAPER_DATA_SOURCE_PATCH §1: when CLOB is the primary
# source (production wiring), the DB fallback default is OFF.
if book is None and self._pool is not None:
    if not clob_attempted or self._db_fallback_enabled:
        book = await self._fetch_storedata_orderbook(token_id)

if book is None:
    return {"bids": [], "asks": [], "ts": 0}  # ← THIS IS WHAT FIRES
```

### 4. `_db_fallback_enabled` default is False, no env override

`venues/polymarket/paper.py:117`:
```python
self._db_fallback_enabled = db_fallback_enabled
# Comment: opt-in via TV_POLY_PAPER_DB_FALLBACK=true (engine wires)
```

VPS3 `/etc/tradingvenue/.env` contains NO `TV_POLY_PAPER_DB_FALLBACK` variable.

### 5. Storedata HAS the data (verified for one hedge_skip case)

Slug `sol-updown-5m-1778058000`, outcome=Down (NO side):
- **89 snapshots** between 08:06–11:03 UTC+2
- **98% with valid ask_price_0** ∈ (0, 1)
- At 11:00:38 UTC+2: ask0=$0.74 size=55, ask1=$0.64 size=15
- Controller skipped at 11:01:08–11:01:49 with "no_asks" → meanwhile asks $0.70-$0.78 size 5-55 visible in storedata

## Why the patch was applied (Phase 18.2 V2)

Comment in `paper.py`:
> "When CLOB is the primary source (production wiring), the DB fallback default is OFF — a CLOB transient should produce an empty book (caller treats as 'no liquidity') rather than silently reading 1-30s stale snapshots."

Intent: prefer fresh CLOB over stale Storedata.
Reality: CLOB is empty for opposite-side tokens, so we get NEITHER fresh nor stale data. Just nothing.

## The economics

| Source | What we'd get | Implication |
|---|---|---|
| CLOB `/book` (current) | Empty for thin opposite tokens | 0% hedge fire rate |
| Storedata fallback (disabled) | Up to 30s stale, but 98% has asks | ~99% hedge fire rate (per realfill) |
| Disabled rationale | Avoid 1-30s slippage on stale book | Loses entire hedge mechanism |

**The 1-30s slippage cost is dramatically less than the cost of NEVER hedging.** Realfill estimates we're losing $7.30/trade on average, $1,613 over 16 hours.

## Fix options

### Option A — flip the env flag (~5 min, instant)
```bash
echo "TV_POLY_PAPER_DB_FALLBACK=true" >> /etc/tradingvenue/.env
sudo systemctl restart tv-engine
```

After restart: opposite-side book queries fall back to Storedata when CLOB is empty. Should restore ~99% hedge fire rate within minutes.

### Option B — change the default to `True` (code change, deploy)

In `venues/polymarket/paper.py` constructor:
```python
db_fallback_enabled: bool = True,  # was False
```

This is the right long-term fix; A is the right immediate fix.

### Option C — use Storedata as PRIMARY for opposite-side (controller change)

When fetching opposite-side specifically (vs own-side at entry), prefer Storedata since the L25 WebSocket capture has better coverage than CLOB on thin tokens.

**Recommended sequence:**
1. **NOW**: Option A — set env flag, restart engine. Watch for hedge/sell events to start firing.
2. **+24h**: validate hedge fire rate ≥ 90% on next 100 fires.
3. **+1 week**: implement Option B + C, ship cleanly.

## Verification queries (run after fix)

```sql
-- After fix, no_asks events should drop dramatically:
SELECT
  COUNT(*) FILTER (WHERE at >= now() - interval '24 hours') AS skips_last_24h,
  COUNT(*) FILTER (WHERE at >= now() - interval '24 hours' AND (data->>'book_ts')::int > 0) AS with_real_book
FROM trading.events
WHERE kind = 'poly_updown_hedge_skip' AND sleeve_id ~ 'momo';

-- Hedge fire count should jump:
SELECT
  sleeve_id,
  COUNT(*) FILTER (WHERE data->>'hedged' = 'true') AS hedged,
  COUNT(*) FILTER (WHERE data->>'partial_bid_exit' = 'true') AS partial_exit,
  COUNT(*) AS total
FROM trading.events
WHERE kind = 'poly_updown_resolution' AND sleeve_id ~ 'momo'
  AND at >= now() - interval '24 hours'
GROUP BY sleeve_id ORDER BY 1;
```

## Telemetry comparisons (production vs realfill)

| Metric | Production | L25 realfill | Gap |
|---|---:|---:|---:|
| Hedges fired | 0 of 215 (0%) | ~99% feasible | full mechanism |
| Sells fired | 5 of 215 (2.4%) | ~99% feasible | most sells missing |
| Total PnL (matched) | $+598.89 | $+2,211.63 | $+1,612.74 left |
| $/trade | $+2.71 | $+10.01 | $+7.30 / trade |

## Files referenced

- Controller: `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py` (3133 lines)
- Paper executor: `/opt/tradingvenue/backend/app/venues/polymarket/paper.py`
- Investigation report (this file): `strategy_lab/reports/VPS3_PRODUCTION_INVESTIGATION_2026_05_06.md`
- Companion: `strategy_lab/reports/MOMO_SHADOW_MATCH_2026_05_06.md` (same-trade comparison)
- Companion: `strategy_lab/reports/MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md` (earlier analysis)
