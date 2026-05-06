# Dashboard Diagnosis — Why You Don't See My Numbers

**Date:** 2026-05-01
**Symptom:** dashboard shows zeros / empty cards even though VPS2 + VPS3 are firing 3,102 paper resolutions in 1.38 days

## Three independent issues

### 🔴 BUG 1 — `trading.portfolio_snapshot` table is missing on VPS3

The dashboard's main top-line cards (total equity, day P&L, realized, unrealized) come from `/portfolio/summary` API endpoint:

```python
# /opt/tradingvenue/backend/app/api/portfolio.py:71
"SELECT COALESCE(SUM(equity), 0)::float8 AS total_equity, ..."
"FROM trading.portfolio_snapshot "
"WHERE at = (SELECT MAX(at) FROM trading.portfolio_snapshot)"
```

**Verified on VPS3:**
```
ERROR:  relation "trading.portfolio_snapshot" does not exist
```

**Effect:** every top-line card returns 0 or 500 error. The "your numbers" you expect to see (cumulative PnL, realized) **literally cannot render** — the table doesn't exist.

The equity curve at `/portfolio/equity` is also broken (same table).

**Fix options:**
1. Create the table + populate it from a periodic job that aggregates `trading.events` (kind=`poly_updown_resolution`)
2. Rewrite `/portfolio/summary` to compute live from `trading.events` (no snapshot table needed)

Option 2 is simpler — replace the SQL with:

```sql
SELECT
  COALESCE(SUM((data->>'pnl_usd')::numeric), 0)::float8 AS realized_pnl,
  COALESCE(SUM((data->>'pnl_usd')::numeric)
           FILTER (WHERE at >= NOW() - INTERVAL '24 hours'), 0)::float8 AS day_pnl,
  COALESCE(SUM((data->>'pnl_usd')::numeric), 0)::float8 AS total_equity,
  0.0::float8 AS unrealized_pnl
FROM trading.events
WHERE kind = 'poly_updown_resolution';
```

### 🔴 BUG 2 — VPS3 dashboard cannot see VPS2 V1 fires

The TV API on VPS3 (port 8000) queries only the LOCAL Postgres at `127.0.0.1:5432` via the asyncpg pool. VPS2's `trading.events` table is on a separate Postgres on VPS2 — completely invisible to the VPS3 dashboard.

**Concrete effect:**

| Sleeve | Fires actually happening on... | Dashboard sees... |
|---|---|---|
| `poly_updown_btc_5m_volume` | **VPS2 + VPS3 both (V1 + V2)** | only VPS3's V2 portion (n=386) |
| `poly_updown_*_volume` (all 6) | **V1 on VPS2 (1,420 fires), V2 on VPS3 (1,466 fires)** | only V2 (1,466) |
| `*_sniper` | VPS3 only | VPS3 (works) |
| `*_v3` | VPS3 only | VPS3 (works) |

V1 control arm — **1,420 fires over 1.38 days on VPS2 — totally absent from the dashboard.**

**Why this matters:** the user said "I'm not seeing the strategy firing" → that may be specifically the V1 arm on VPS2.

**Fix options:**
1. Run a second TV API instance on VPS2 (separate dashboard for V1)
2. Add a cross-host federation layer: VPS3 API queries VPS2 via SSH tunnel or direct Postgres connection (read-only role exists: `tradingvenue_ro` / `<VPS3_RO_PWD>`)
3. Replicate VPS2 events into VPS3 (logical replication or periodic dump)

Option 2 is fastest — add a second connection pool in `_deps` pointing to VPS2 and union results in the bots/state and portfolio endpoints. ~50 lines of code.

### 🟡 BUG 3 — `trading.positions` schema mismatch

`/positions` endpoint expects `opened_at`, `closed_at` columns. Actual table doesn't have them:

```
ERROR:  column "opened_at" does not exist
```

This is less impactful because paper-mode strategies don't track positions in the standard sense — they fire-and-forget on Polymarket binary resolution. But if the dashboard renders position cards, they'll be empty.

## What IS working

The `/bots/poly_updown/state` endpoint **is correct** and returns data for all 15 sleeves on VPS3. The frontend at `/opt/tradingvenue/frontend/app/bots/page.tsx` correctly registers all 15 sleeve IDs (POLY_V1_SLOTS + POLY_V2_SLOTS + POLY_V3_SLOTS). So:

- ✅ V2 sniper sleeves (sniper rows) should show data
- ✅ V3 sleeves (v3 rows) should show data
- ✅ V2 volume sleeves (volume rows) should show data
- ❌ V1 volume sleeves: same sleeve_id as V2 volume — dashboard sees only V2 numbers, NOT the V1 control arm
- ❌ Top-line summary cards: BROKEN (table missing)

If the user is looking at the **bots page**, V2/V3 cards should show numbers. If they look at the **portfolio summary**, everything is zero.

## Live API verification

Endpoint `/health` works:
```json
{"status":"ok","version":"0.1.0","git":"836d7ae23d0d","uptime":123108.93}
```

Endpoints `/bots/poly_updown/state` and `/portfolio/summary` require the operator session cookie. With cookie:
- `/bots/poly_updown/state` → returns 15 entries ✓
- `/portfolio/summary` → returns 500 error from missing table ✗

## Recommended fix order

1. **Fix BUG 1 first** (rewrite `/portfolio/summary` to compute from events) — restores top-line cards. ~20 lines, 30 min.
2. **Fix BUG 2** (cross-host federation for V1 visibility) — restores V1 control arm. ~50 lines, 1-2 hours.
3. **Fix BUG 3** (positions schema) — only matters if you want position cards. Lower priority.

After fix 1+2, dashboard will display:
- Real-time PnL per sleeve (15 sleeves)
- Aggregate equity / day P&L
- V1 control arm visible alongside V2 / V3 test arms

## What you should ask the TV agent

> The dashboard portfolio summary endpoint queries `trading.portfolio_snapshot` which doesn't exist. Replace the SQL in `/opt/tradingvenue/backend/app/api/portfolio.py` with a direct aggregation over `trading.events` filtered to `kind='poly_updown_resolution'`. Also wire a second connection pool to VPS2's `tradingvenue_ro` and union V1 fires into the `/bots/poly_updown/state` results so the V1 control arm becomes visible.

## Files

- This diagnosis: `strategy_lab/reports/DASHBOARD_DIAGNOSIS_2026_05_01.md`
- API code on VPS3: `/opt/tradingvenue/backend/app/api/portfolio.py`, `bots.py`, `positions.py`
- Frontend: `/opt/tradingvenue/frontend/app/bots/page.tsx`
- VPS2 read-only credentials: in `/etc/tv/tv-ro.env` (`tradingvenue_ro` / pwd shown above)
