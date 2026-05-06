# V3 Final Patch Spec — Parallel Deployment

**Date:** 2026-05-01
**Status:** ready for TV agent
**Architecture:** **NEW sleeves run in parallel.** V1, V2 sniper, V2 volume, and current V3 keep running UNCHANGED. The patched logic deploys as a new strategy mode = `v4` with new sleeve_ids `poly_updown_{asset}_5m_v4`. Both V3 and V4 run paper side-by-side; the dashboard A/B compares them.

This is a **non-destructive deployment.** No existing sleeve config is modified.

---

## Why parallel (not in-place)

Modifying the running `*_v3` sleeves would:
- Lose the V3 baseline track record (we'd never know if V3.1+V3.2 actually beat V3)
- Risk introducing bugs that affect a sleeve currently winning at 85% hit
- Force a hard cutover instead of A/B comparison

Parallel deploy:
- ✓ Old V3 keeps producing baseline numbers
- ✓ V4 runs the patched logic on the same markets at the same time
- ✓ 7-14 days of side-by-side data → unambiguous winner
- ✓ One env-var rollback if V4 misbehaves

---

## What V4 contains (V3.1 + V3.2 merged)

### From V3.1 — asymmetric quantiles + risk fix

```python
# Per-asset, per-direction magnitude quantiles.
# Replaces V3's (asset, tf): float dict with (asset, tf, direction): float.
V4_PER_ASSET_QUANTILE: dict[tuple[str, str, str], float] = {
    ("BTC", "5m", "UP"):   0.90,   # symmetric — BTC UP works
    ("BTC", "5m", "DOWN"): 0.90,
    ("ETH", "5m", "UP"):   0.97,   # tighter — ETH UP weaker than DOWN
    ("ETH", "5m", "DOWN"): 0.95,
    ("SOL", "5m", "UP"):   0.92,   # tighter + multi-horizon (live evidence: SOL UP at 7.7% hit)
    ("SOL", "5m", "DOWN"): 0.85,
}

# Live-direction allowlist (paper still fires for ongoing eval).
V4_DIRECTION_LIVE_DISABLED: dict[tuple[str, str], set[str]] = {
    ("SOL", "5m"): {"UP"},   # SOL UP loses 89% in live; paper-only until ≥55% hit on n≥30
}
```

### From V3.2 — three new gates

```python
# Hour blocklist (UTC). Hours where ALL THREE assets show ≤-5pp deviation in backtest.
V4_HOUR_BLOCKLIST_UTC = {1, 16, 22}

# Liquidity quiet regime gate (paper-only initially since liq backfill incomplete).
V4_LIQ_QUIET_THRESHOLD_USD = 10_000

# Macro alignment: at least 1 of (15m, 1h) must agree with 5m direction.
# SOL skipped since multi-horizon already enforces 3-of-3.
def v4_macro_2of3_passes(symbol: str, ret_5m: float, ret_15m: float, ret_1h: float) -> bool:
    if symbol.upper() == "SOL":
        return True   # SOL has multi-horizon at quantile level
    sign5 = 1 if ret_5m > 0 else (-1 if ret_5m < 0 else 0)
    if sign5 == 0:
        return False
    agree = 0
    if (sign5 * ret_15m) > 0: agree += 1
    if (sign5 * ret_1h) > 0:  agree += 1
    return agree >= 1

def v4_hour_passes(now_unix_s: int) -> bool:
    import datetime
    h = datetime.datetime.fromtimestamp(now_unix_s, tz=datetime.timezone.utc).hour
    return h not in V4_HOUR_BLOCKLIST_UTC

def v4_liq_quiet_passes(symbol: str, liq_db) -> bool:
    """Skip if recent Binance liq notional > threshold. Fail-open if DB unreachable."""
    try:
        total_5m = liq_db.recent_liq_notional(symbol, lookback_sec=300)
    except Exception:
        return True   # don't block trading on infra hiccup
    return total_5m <= V4_LIQ_QUIET_THRESHOLD_USD

def v4_signal_passes_gates(symbol: str, ret_5m, ret_15m, ret_1h, now_unix_s, liq_db, mode):
    """Returns (pass, reason). All gates must pass for live; paper logs but proceeds."""
    if not v4_hour_passes(now_unix_s):
        return False, "hour_blocked"
    if not v4_macro_2of3_passes(symbol, ret_5m, ret_15m, ret_1h):
        return False, "macro_2of3_fail"
    if not v4_liq_quiet_passes(symbol, liq_db):
        return False, "liq_active_regime"
    return True, "passes"
```

---

## Code changes (single PR)

### File 1: `backend/app/controllers/polymarket_updown.py`

Add a new strategy mode. Existing V3 untouched.

```python
# Top of file, alongside V3_PER_ASSET_QUANTILE:
V4_PER_ASSET_QUANTILE = {...}   # (see above)
V4_DIRECTION_LIVE_DISABLED = {...}
V4_HOUR_BLOCKLIST_UTC = {1, 16, 22}
V4_LIQ_QUIET_THRESHOLD_USD = 10_000

def _v4_quantile_for(symbol: str, tf: str, direction: str) -> float | None:
    return V4_PER_ASSET_QUANTILE.get((symbol.upper(), tf, direction))
```

In the controller's signal-fire path, add a `mode == "v4"` branch parallel to the existing `mode == "v3"` branch. Reuse the same threshold-fetcher path; only the quantile lookup + gate stack differ.

```python
if mode == "v4":
    # Determine direction from ret_5m sign at signal time
    direction = "UP" if ret_5m > 0 else "DOWN"
    q = _v4_quantile_for(symbol, tf, direction)
    if q is None:
        return Signal.NONE   # V4 doesn't apply to this cell
    threshold = float(np.quantile(samples, q))
    if abs(ret_5m) < threshold:
        return Signal.NONE

    # SOL multi-horizon (same as V3 — required for SOL only)
    if symbol.upper() == "SOL":
        same = (ret_5m > 0 and ret_15m > 0 and ret_1h > 0) or \
               (ret_5m < 0 and ret_15m < 0 and ret_1h < 0)
        if not same:
            return Signal.NONE

    # V4 gate stack
    ok, reason = v4_signal_passes_gates(symbol, ret_5m, ret_15m, ret_1h, now_unix_s, liq_db, mode)
    if not ok:
        log_skip(reason)
        return Signal.NONE

    # Live direction filter (paper still fires)
    if live_mode:
        disabled = V4_DIRECTION_LIVE_DISABLED.get((symbol.upper(), tf), set())
        if direction in disabled:
            return Signal.NONE   # log + skip

    # Emit signal with sleeve_id ending in `_v4`
    sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_v4"
    ...
```

### File 2: `backend/app/api/bots.py`

Extend `_POLY_UPDOWN_SLEEVE_IDS` tuple — add 3 V4 sleeves:

```python
_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # ... existing 15 sleeves (V1 + V2 + V3) ...
    # NEW: V4 — V3 + V3.1 patches + V3.2 gates, parallel to V3
    "poly_updown_btc_5m_v4",
    "poly_updown_eth_5m_v4",
    "poly_updown_sol_5m_v4",
)
```

### File 3: `backend/app/services/liq_db.py` (NEW)

```python
"""Read-only access to Binance liq table on VPS2 (cross-host federation)."""
import os
import asyncpg
from cachetools import TTLCache

# 30s cache to avoid hammering VPS2.
_cache: TTLCache[str, float] = TTLCache(maxsize=8, ttl=30)
_pool: asyncpg.Pool | None = None

async def init_pool():
    global _pool
    _pool = await asyncpg.create_pool(
        host=os.environ["VPS2_PG_HOST"],
        port=5432,
        user="tradingvenue_ro",
        password=os.environ["VPS2_PG_RO_PWD"],
        database="storedata",
        min_size=1, max_size=2,
    )

async def recent_liq_notional(symbol: str, lookback_sec: int = 300) -> float:
    cache_key = f"{symbol}:{lookback_sec}"
    if cache_key in _cache:
        return _cache[cache_key]
    if _pool is None: return 0.0   # fail-open
    sql = """
        SELECT COALESCE(SUM(price * size), 0)::float8
        FROM binance_liquidations_v2
        WHERE symbol_id = $1
          AND time_exchange_us >= (EXTRACT(EPOCH FROM NOW()) - $2) * 1e6
    """
    symbol_id = f"BINANCEFTS_PERP_{symbol.upper()}_USDT"
    try:
        async with _pool.acquire() as conn:
            row = await conn.fetchval(sql, symbol_id, lookback_sec)
        v = float(row or 0.0)
        _cache[cache_key] = v
        return v
    except Exception:
        return 0.0   # fail-open on DB error
```

### File 4: `frontend/app/bots/page.tsx`

Add V4 slot section (parallel to existing V3):

```typescript
const POLY_V4_SLOTS: PolySlotEntry[] = [
  { id: 'poly_updown_btc_5m_v4', underlying: 'BTC', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_eth_5m_v4', underlying: 'ETH', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_sol_5m_v4', underlying: 'SOL', windowLabel: '5m', tfSeconds: 300 },
];
```

Render in a 4th portfolio group: "V4 (V3 + patches)".

### File 5: `/etc/tv/tradingvenue.env` on VPS3

Append `,v4` to the modes:

```bash
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v4
VPS2_PG_HOST=[2605:a140:2323:6975::1]
VPS2_PG_RO_PWD=<VPS3_RO_PWD>
```

### File 6: tests

```python
# backend/tests/unit/test_v4_gates.py

def test_v4_quantile_lookup():
    assert _v4_quantile_for("BTC", "5m", "UP") == 0.90
    assert _v4_quantile_for("ETH", "5m", "UP") == 0.97
    assert _v4_quantile_for("SOL", "5m", "DOWN") == 0.85
    assert _v4_quantile_for("BTC", "15m", "UP") is None  # V4 is 5m only

def test_v4_hour_block():
    # 22 UTC blocked
    assert not v4_hour_passes(int(datetime(2026,5,1,22,0,0,tzinfo=timezone.utc).timestamp()))
    # 14 UTC passes
    assert v4_hour_passes(int(datetime(2026,5,1,14,0,0,tzinfo=timezone.utc).timestamp()))

def test_v4_macro_2of3_btc():
    assert v4_macro_2of3_passes("BTC", 0.005, 0.003, -0.001)   # 15m agrees → pass
    assert v4_macro_2of3_passes("BTC", 0.005, -0.003, 0.001)   # 1h agrees → pass
    assert not v4_macro_2of3_passes("BTC", 0.005, -0.003, -0.001)  # both disagree → fail

def test_v4_macro_2of3_sol_skipped():
    # SOL skips macro_2of3 because multi-horizon enforces 3-of-3 already
    assert v4_macro_2of3_passes("SOL", 0.005, -0.003, -0.001)  # always True for SOL

def test_v4_liq_quiet_blocks_above_threshold():
    class FakeDB:
        def recent_liq_notional(self, sym, lookback_sec): return 15_000
    assert not v4_liq_quiet_passes("BTC", FakeDB())

def test_v4_liq_quiet_fails_open():
    class BrokenDB:
        def recent_liq_notional(self, sym, lookback_sec): raise RuntimeError()
    assert v4_liq_quiet_passes("BTC", BrokenDB())

def test_v4_sol_up_disabled_in_live():
    # In live mode, SOL UP signal should be blocked at sleeve level
    assert "UP" in V4_DIRECTION_LIVE_DISABLED.get(("SOL", "5m"), set())

def test_v4_sol_up_paper_still_fires():
    # In paper mode, SOL UP fires normally (for ongoing eval)
    # ... assertion on controller path with mode="paper"
```

---

## Feature flags (rollback in seconds)

Every gate is env-toggleable:

```bash
# /etc/tv/tradingvenue.env on VPS3
V4_HOUR_BLOCK_ENABLED=true
V4_MACRO_2OF3_ENABLED=true
V4_LIQ_QUIET_ENABLED=true
V4_ASYMMETRIC_QUANTILE_ENABLED=true
V4_SOL_UP_LIVE_DISABLED=true
```

```python
# In gate functions:
if not bool(int(os.getenv("V4_HOUR_BLOCK_ENABLED", "1"))):
    return True   # bypass gate
```

To disable any single gate:

```bash
ssh vps3 "sed -i 's/V4_HOUR_BLOCK_ENABLED=true/V4_HOUR_BLOCK_ENABLED=false/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

To completely roll back V4 (revert to V3-only):

```bash
ssh vps3 "sed -i 's/STRATEGY_MODES=volume,sniper,v3,v4/STRATEGY_MODES=volume,sniper,v3/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

---

## What stays untouched

| Sleeve | Mode | Status after V4 deploy |
|---|---|---|
| `poly_updown_*_volume` (12 sleeves, V1+V2) | volume | unchanged, keep firing |
| `poly_updown_*_sniper` (6 sleeves, V2) | sniper | unchanged |
| `poly_updown_*_v3` (3 sleeves) | v3 | **unchanged — V3.0 baseline** |
| `poly_updown_*_v4` (3 sleeves, NEW) | v4 | **fires in parallel with V3** |

Total sleeves on VPS3 after V4 deploy: 6 volume + 6 sniper + 3 v3 + 3 v4 = **18 sleeves.**

---

## Expected V4 behavior in first 24h

Based on backtest of combined patches:
- Fire rate: **30-40% lower than V3** (gates filter ~25-35% of signals)
- Hit rate: **75-80%** (vs V3's 71.8% backtest baseline)
- Per-asset:
  - BTC V4: similar to V3 BTC (BTC was already symmetric)
  - ETH V4: should fire more selectively, hit rate boost expected
  - SOL V4: fires only DOWN in live; UP fires in paper for eval; expect higher hit on the DOWN fires that pass macro+liq+hour gates

If V4 fires zero in 24h: liq DB connection broken or hour-gate too aggressive. Check logs.

---

## A/B comparison after 7 days

```sql
-- Compare V3 vs V4 on same window
SELECT
  CASE WHEN sleeve_id LIKE '%_v3' THEN 'V3' ELSE 'V4' END AS variant,
  data->>'symbol' AS symbol,
  COUNT(*) AS n,
  AVG((data->>'won')::boolean::int) AS hit_rate,
  SUM((data->>'pnl_usd')::numeric) AS pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND (sleeve_id LIKE '%_v3' OR sleeve_id LIKE '%_v4')
  AND at > NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 2, 1;
```

Decision rule: V4 ships live IF AND ONLY IF V4 hit rate > V3 hit rate by ≥3pp on n≥30 per asset.

---

## Effort breakdown

| Task | Time |
|---|---|
| Code: V4 controller branch | 1.5 hr |
| Code: liq_db service | 1 hr |
| Code: bots.py + frontend page.tsx | 30 min |
| Tests | 1.5 hr |
| Env config + deploy | 30 min |
| Smoke test | 30 min |
| **Total** | **5-6 hr single PR** |

---

## Kill switches

If V4 trips ANY of these on rolling 24h:
- Hit rate <40% on n≥30 → disable mode v4 entirely
- Daily PnL < -$10 (paper) → page operator
- Fire rate >150/day per sleeve → cap, investigate
- Liq DB query timeout >5% → set `V4_LIQ_QUIET_ENABLED=false`

---

## Files

- This consolidated spec: `strategy_lab/reports/V3_FINAL_PATCH_SPEC_PARALLEL.md`
- Original V3.1 (now superseded): `strategy_lab/reports/V3_1_PATCH_SPEC_2026_04_30.md`
- Original V3.2 (now superseded): `strategy_lab/reports/V3_2_DEPLOY_SPEC_2026_04_30.md`
- Live evidence: `strategy_lab/reports/FULL_RANKING_AND_LOGIC_REVIEW_2026_05_01.md`
- Code locations: `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`, `api/bots.py`, `frontend/app/bots/page.tsx`
