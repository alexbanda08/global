# V3 Patch — Option B (Full Parallel A/B/C/D)

**Date:** 2026-05-01
**Status:** ready for TV agent
**Architecture:** **3 NEW sleeve sets running in parallel** alongside existing V3. Each variant tests one specific patch combination so we can attribute the effect directly.

---

## The 4-way comparison

After deploy, dashboard shows 12 V3-family sleeves total (4 variants × 3 assets):

| Sleeve | Logic | Sleeve_id pattern |
|---|---|---|
| **V3** (current, untouched) | base V3 — q90/q95/q85, multi-h on SOL | `poly_updown_{asset}_5m_v3` |
| **V3.1 only** (NEW) | V3 + asymmetric per-direction quantiles + SOL UP live-disable + soft regime ±0.5% | `poly_updown_{asset}_5m_v3_1` |
| **V3.2 only** (NEW) | V3 + hour blocklist + macro 2-of-3 + liq quiet gate | `poly_updown_{asset}_5m_v3_2` |
| **V4** (NEW, combined) | V3 + V3.1 + V3.2 stacked | `poly_updown_{asset}_5m_v4` |

Each variant evaluates every 5-min Polymarket market independently. Fire decisions are isolated — running in parallel doesn't reduce any individual sleeve's sample.

---

## Per-variant logic

### V3.1 (asymmetric quantiles + risk fix)

```python
# Per-direction quantile (replaces V3's per-asset-only)
V3_1_PER_ASSET_QUANTILE = {
    ("BTC", "5m", "UP"):   0.90,   # symmetric, no change
    ("BTC", "5m", "DOWN"): 0.90,
    ("ETH", "5m", "UP"):   0.97,   # tighter than V3 (was 0.95)
    ("ETH", "5m", "DOWN"): 0.95,   # unchanged
    ("SOL", "5m", "UP"):   0.92,   # tighter than V3 (was 0.85)
    ("SOL", "5m", "DOWN"): 0.85,   # unchanged (paired with multi-horizon)
}

# Live direction filter (paper still fires for ongoing eval)
V3_1_LIVE_DIRECTIONS = {
    ("SOL", "5m"): {"DOWN"},   # SOL UP paper-only until ≥55% hit on n≥30
}

# Soft regime overlay
V3_1_REGIME_THRESHOLD = 0.005
def v3_1_regime_passes(direction, ret_1h):
    if direction == "UP":   return ret_1h >= -V3_1_REGIME_THRESHOLD
    if direction == "DOWN": return ret_1h <= V3_1_REGIME_THRESHOLD
    return True
```

**SOL multi-horizon and BTC quantile inherited from V3 unchanged.**

### V3.2 (gate stack only — quantiles same as V3)

```python
# V3.2 uses base V3 quantiles. Adds 3 gates.

V3_2_HOUR_BLOCKLIST_UTC = {1, 16, 22}
V3_2_LIQ_QUIET_THRESHOLD_USD = 10_000

def v3_2_hour_passes(now_unix_s):
    h = pd.Timestamp(now_unix_s, unit='s', tz='UTC').hour
    return h not in V3_2_HOUR_BLOCKLIST_UTC

def v3_2_macro_2of3_passes(symbol, ret_5m, ret_15m, ret_1h):
    if symbol.upper() == "SOL":
        return True   # SOL has multi-horizon; this gate is redundant
    sign5 = 1 if ret_5m > 0 else -1
    agree = ((sign5 * ret_15m) > 0) + ((sign5 * ret_1h) > 0)
    return agree >= 1

def v3_2_liq_quiet_passes(symbol, liq_db):
    try:
        return liq_db.recent_liq_notional(symbol, 300) <= V3_2_LIQ_QUIET_THRESHOLD_USD
    except Exception:
        return True   # fail-open
```

### V4 (combined)

V4 is V3 + V3.1 + V3.2 applied in sequence. Order in the controller:

```python
# 1. V3.1 quantile lookup (asymmetric per-direction)
direction = "UP" if ret_5m > 0 else "DOWN"
q = V3_1_PER_ASSET_QUANTILE.get((symbol, tf, direction))
if abs(ret_5m) < np.quantile(samples, q): return Signal.NONE

# 2. SOL multi-horizon (inherited from V3)
if symbol == "SOL" and not multi_horizon_aligned: return Signal.NONE

# 3. V3.1 soft regime overlay
if not v3_1_regime_passes(direction, ret_1h): return Signal.NONE

# 4. V3.2 hour gate
if not v3_2_hour_passes(now): return Signal.NONE

# 5. V3.2 macro 2-of-3
if not v3_2_macro_2of3_passes(symbol, ret_5m, ret_15m, ret_1h): return Signal.NONE

# 6. V3.2 liq quiet
if not v3_2_liq_quiet_passes(symbol, liq_db): return Signal.NONE

# 7. V3.1 live direction filter (only blocks LIVE; paper still fires)
if live_mode and direction not in V3_1_LIVE_DIRECTIONS.get((symbol, tf), {"UP", "DOWN"}):
    return Signal.NONE

# Emit signal -> sleeve_id="poly_updown_{symbol}_5m_v4"
```

---

## Code changes (single PR)

### 0. **NOTIONAL CHANGE: $25 → $1** (affects ALL sleeves)

Current state: `polymarket_updown.py:74` has hard-coded `NOTIONAL_PER_SLOT_USD = Decimal("25")` with an enforcement assertion at line 285 that rejects any override.

**Why change:** paper trades at $25 don't reflect what live $1 trades will do. Cost-per-share fixed (0.51), so PnL scales linearly — but variance, fill capacity, and slippage profile all differ at smaller size. Paper at $1 gives true parity with planned live launch.

**Change:**

```python
# line 74 — replace hard-coded constant with env-driven default
import os
NOTIONAL_PER_SLOT_USD = Decimal(os.getenv("TV_POLY_NOTIONAL_USD", "1"))   # was "25"
```

Loosen the enforcement assertion at line 285 — accept any value matching the env config (still reject silent overrides):

```python
# line 285 — was: any override raises. Now: only override raises if differs from configured.
if notional_usd is not None and notional_usd != NOTIONAL_PER_SLOT_USD:
    raise ValueError(
        f"D-04: notional fixed at {NOTIONAL_PER_SLOT_USD} per env "
        f"TV_POLY_NOTIONAL_USD; got override={notional_usd}"
    )
```

Set on both VPS:

```bash
# /etc/tv/tradingvenue.env on VPS2 + VPS3
TV_POLY_NOTIONAL_USD=1
```

**Impact:** all 30 sleeves (existing V1/V2/V3 + new V3.1/V3.2/V4 variants) fire at $1 notional. Paper PnL becomes 1/25th of current rate but signal quality (hit rate) is unchanged — the metric you care about is the SAME.

**To restore $25 anytime:** `TV_POLY_NOTIONAL_USD=25 && systemctl restart tv-engine`.

### 1. `backend/app/controllers/polymarket_updown.py`

Add 3 new strategy modes alongside existing v3:

```python
# At module top, alongside V3_PER_ASSET_QUANTILE:
V3_1_PER_ASSET_QUANTILE = {...}
V3_1_LIVE_DIRECTIONS = {...}
V3_1_REGIME_THRESHOLD = 0.005

V3_2_HOUR_BLOCKLIST_UTC = {1, 16, 22}
V3_2_LIQ_QUIET_THRESHOLD_USD = 10_000

# Helper functions: v3_1_regime_passes, v3_2_hour_passes, etc.
```

In the controller signal-fire path, add 3 new mode branches parallel to existing `v3`:

```python
elif mode == "v3_1":
    # V3 quantile (use V3_1 lookup) + soft regime + live-direction filter
    # NO hour/macro/liq gates
    ...
    sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_v3_1"

elif mode == "v3_2":
    # Base V3 quantile + hour + macro_2of3 + liq_quiet
    # NO asymmetric quantile, NO live-direction filter, NO regime overlay
    ...
    sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_v3_2"

elif mode == "v4":
    # Everything: V3.1 quantiles + V3.1 regime + V3.2 gates + V3.1 live filter
    ...
    sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_v4"
```

### 2. `backend/app/services/liq_db.py` (NEW)

Cross-host async pool to VPS2 for liquidation queries. (Same as Option A spec — needed by both V3.2 and V4.)

```python
import os, asyncpg
from cachetools import TTLCache

_pool: asyncpg.Pool | None = None
_cache: TTLCache = TTLCache(maxsize=8, ttl=30)

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
    if cache_key in _cache: return _cache[cache_key]
    if _pool is None: return 0.0
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
        return 0.0
```

### 3. `backend/app/api/bots.py`

Extend `_POLY_UPDOWN_SLEEVE_IDS`:

```python
_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # ... existing 15 sleeves (V1 + V2 + V3) ...

    # NEW: V3.1 — asymmetric quantiles + regime overlay + SOL UP live-disable
    "poly_updown_btc_5m_v3_1",
    "poly_updown_eth_5m_v3_1",
    "poly_updown_sol_5m_v3_1",

    # NEW: V3.2 — gate stack on top of base V3
    "poly_updown_btc_5m_v3_2",
    "poly_updown_eth_5m_v3_2",
    "poly_updown_sol_5m_v3_2",

    # NEW: V4 — V3.1 + V3.2 combined
    "poly_updown_btc_5m_v4",
    "poly_updown_eth_5m_v4",
    "poly_updown_sol_5m_v4",
)
```

### 4. `frontend/app/bots/page.tsx`

Add 3 new slot arrays + 3 new portfolio groups (or one combined "V3 patches" group):

```typescript
const POLY_V3_1_SLOTS: PolySlotEntry[] = [
  { id: 'poly_updown_btc_5m_v3_1', underlying: 'BTC', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_eth_5m_v3_1', underlying: 'ETH', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_sol_5m_v3_1', underlying: 'SOL', windowLabel: '5m', tfSeconds: 300 },
];

const POLY_V3_2_SLOTS: PolySlotEntry[] = [
  { id: 'poly_updown_btc_5m_v3_2', underlying: 'BTC', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_eth_5m_v3_2', underlying: 'ETH', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_sol_5m_v3_2', underlying: 'SOL', windowLabel: '5m', tfSeconds: 300 },
];

const POLY_V4_SLOTS: PolySlotEntry[] = [
  { id: 'poly_updown_btc_5m_v4', underlying: 'BTC', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_eth_5m_v4', underlying: 'ETH', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_sol_5m_v4', underlying: 'SOL', windowLabel: '5m', tfSeconds: 300 },
];
```

### 5. `/etc/tv/tradingvenue.env` on VPS3

```bash
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v4
VPS2_PG_HOST=[2605:a140:2323:6975::1]
VPS2_PG_RO_PWD=<VPS3_RO_PWD>
```

### 6. Tests (`backend/tests/unit/test_v3_patches.py`)

```python
def test_v3_1_asymmetric_quantile():
    assert _v3_1_quantile_for("ETH", "5m", "UP") == 0.97
    assert _v3_1_quantile_for("SOL", "5m", "UP") == 0.92
    assert _v3_1_quantile_for("SOL", "5m", "DOWN") == 0.85

def test_v3_1_regime_blocks_up_in_strong_downtrend():
    assert not v3_1_regime_passes("UP", -0.01)   # 1h trend -1% → block UP
    assert v3_1_regime_passes("UP", 0.005)       # 1h trend +0.5% → pass

def test_v3_2_hour_blocks():
    # 22 UTC blocked
    assert not v3_2_hour_passes(int(datetime(2026,5,1,22,0,tzinfo=timezone.utc).timestamp()))
    # 14 UTC passes
    assert v3_2_hour_passes(int(datetime(2026,5,1,14,0,tzinfo=timezone.utc).timestamp()))

def test_v3_2_macro_skip_for_sol():
    # SOL skips macro_2of3 (multi-horizon already enforces 3-of-3)
    assert v3_2_macro_2of3_passes("SOL", 0.005, -0.003, -0.001)

def test_v3_2_liq_quiet_fails_open():
    class BrokenDB:
        async def recent_liq_notional(self, sym, sec): raise RuntimeError()
    assert v3_2_liq_quiet_passes("BTC", BrokenDB())

def test_v4_stacks_all_filters():
    # V4 applies V3.1 quantile AND V3.2 gates AND live filter
    # Verify by mocking each gate and checking final pass requires all True
    ...

def test_v3_1_sol_up_live_disabled():
    assert "UP" not in V3_1_LIVE_DIRECTIONS.get(("SOL", "5m"), {"UP","DOWN"})
```

---

## Feature flags (per-variant + per-gate, full granularity)

```bash
# /etc/tv/tradingvenue.env on VPS3

# Master switches per variant
V3_1_ENABLED=true
V3_2_ENABLED=true
V4_ENABLED=true

# V3.2 gates (apply to v3_2 + v4 sleeves)
V3_2_HOUR_BLOCK_ENABLED=true
V3_2_MACRO_2OF3_ENABLED=true
V3_2_LIQ_QUIET_ENABLED=true

# V3.1 components (apply to v3_1 + v4 sleeves)
V3_1_ASYMMETRIC_QUANTILE_ENABLED=true
V3_1_REGIME_OVERLAY_ENABLED=true
V3_1_SOL_UP_LIVE_DISABLED=true
```

Disable an entire variant:

```bash
ssh vps3 "sed -i 's/V3_1_ENABLED=true/V3_1_ENABLED=false/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

Disable a single gate (affects v3_2 and v4 simultaneously):

```bash
ssh vps3 "sed -i 's/V3_2_LIQ_QUIET_ENABLED=true/V3_2_LIQ_QUIET_ENABLED=false/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

Roll back EVERYTHING (back to current V3 + V2 + V1):

```bash
ssh vps3 "sed -i 's/STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v4/STRATEGY_MODES=volume,sniper,v3/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

---

## Final dashboard layout

After deploy, 30 sleeves total:

| Group | Sleeves | Status |
|---|---|---|
| V1 volume (VPS2) | 6 | unchanged |
| V2 volume (VPS3) | 6 | unchanged |
| V2 sniper (VPS3) | 6 | unchanged |
| **V3 baseline (VPS3)** | **3** | **untouched** |
| **V3.1 only (NEW)** | **3** | NEW |
| **V3.2 only (NEW)** | **3** | NEW |
| **V4 = V3.1+V3.2 (NEW)** | **3** | NEW |

---

## Expected behavior in first 24h

| Variant | Expected fire rate vs V3 | Expected hit rate vs V3 |
|---|---|---|
| V3 baseline | 100% (n=85 over 7d backtest) | 71.8% baseline |
| V3.1 | ~85% (tighter ETH/SOL UP) | small lift on ETH/SOL UP fires |
| V3.2 | ~70% (3 gates filter ~30%) | bigger lift, +5-8pp |
| V4 | ~60% (compound) | biggest lift, +8-12pp |

If V3.1 fires zero or V4 fires <5/day → check liq_db connection or hour gate too aggressive.

---

## A/B comparison query (after 7 days)

```sql
SELECT
  CASE
    WHEN sleeve_id LIKE '%_v3' THEN 'V3'
    WHEN sleeve_id LIKE '%_v3_1' THEN 'V3.1'
    WHEN sleeve_id LIKE '%_v3_2' THEN 'V3.2'
    WHEN sleeve_id LIKE '%_v4' THEN 'V4'
  END AS variant,
  data->>'symbol' AS symbol,
  COUNT(*) AS n,
  AVG((data->>'won')::boolean::int) AS hit_rate,
  ROUND(SUM((data->>'pnl_usd')::numeric), 2) AS pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND sleeve_id ~ '_(v3|v3_1|v3_2|v4)$'
  AND at > NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 2, 1;
```

**Decision logic:**
- V3.1 ships live IF: SOL UP avoidance lifts SOL hit rate ≥10pp (vs V3 SOL)
- V3.2 ships live IF: combined hit rate ≥75% on n≥50 (vs V3's 71.8%)
- V4 ships live IF: V4 hit rate > both V3.1 and V3.2 individually by ≥3pp on n≥30

If V4 doesn't beat its components, ship the better single one.

---

## Effort breakdown

| Task | Time |
|---|---|
| Code: 3 new mode branches in controller | 2 hr |
| Code: liq_db service | 1 hr |
| Code: bots.py + frontend page.tsx (9 new sleeve entries + 3 dashboard sections) | 1 hr |
| Tests | 2 hr |
| Env config + deploy | 30 min |
| Smoke test all 9 new sleeves fire | 30 min |
| **Total** | **7 hr single PR** |

About 1.5 hr more than Option A — but you get the full attribution matrix.

---

## Files

- This Option B spec: `strategy_lab/reports/V3_PATCH_OPTION_B_SPEC.md`
- Original V3.1: `strategy_lab/reports/V3_1_PATCH_SPEC_2026_04_30.md`
- Original V3.2: `strategy_lab/reports/V3_2_DEPLOY_SPEC_2026_04_30.md`
- Option A (combined only — superseded): `strategy_lab/reports/V3_FINAL_PATCH_SPEC_PARALLEL.md`
- Live evidence: `strategy_lab/reports/FULL_RANKING_AND_LOGIC_REVIEW_2026_05_01.md`
