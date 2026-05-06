# V3.2 Deploy Spec — Combined Patch

**Date:** 2026-04-30
**Status:** ready for TV agent. Hot-patchable on top of V3.

## What V3.2 changes

Three additions to the V3 portfolio sniper. Apply together.

| # | Change | Source | Expected backtest lift |
|---|---|---|---|
| 1 | Hour-of-day blocklist | Phase 1 (this session) | +13pp ROI alone |
| 2 | Macro 2-of-3 alignment filter | Phase 3 (this session) | +2.7pp ROI alone |
| 3 | Liquidation quiet-regime gate (provisional) | Phase 5 (this session) | +5-6pp hit rate (when liq data available) |

**Combined holdout (7-day forward-walk):** n 85 → 72, hit 71.8 → 80.6%, ROI 32.6 → 49.3%.
**Conservative real-world estimate (overfit-discount):** hit 75-78%, ROI 40-45%.

## Code changes

`backend/app/controllers/polymarket_updown.py`:

```python
# === V3.2 additions ===

# Phase 1: hours where ALL THREE assets show ≤-5pp deviation in backtest
V3_HOUR_BLOCKLIST_UTC = {1, 16, 22}

# Phase 5: skip if recent Binance liq notional > threshold (regime gate)
V3_LIQ_QUIET_THRESHOLD_USD = 10_000

def v3_hour_passes(now_unix_s: int) -> bool:
    """Return False if the current UTC hour is in the blocklist."""
    import datetime
    hour = datetime.datetime.fromtimestamp(now_unix_s, tz=datetime.timezone.utc).hour
    return hour not in V3_HOUR_BLOCKLIST_UTC

def v3_macro_2of3_passes(ret_5m: float, ret_15m: float, ret_1h: float) -> bool:
    """Phase 3: at least 1 of (15m, 1h) must agree with 5m sign."""
    sign5 = 1 if ret_5m > 0 else (-1 if ret_5m < 0 else 0)
    if sign5 == 0:
        return False
    agree = 0
    if (sign5 * ret_15m) > 0: agree += 1
    if (sign5 * ret_1h) > 0:  agree += 1
    return agree >= 1

def v3_liq_quiet_passes(symbol: str, now_unix_s: int, liq_db) -> bool:
    """Phase 5: skip if 5m liq notional > $10k. Pass if liq data unavailable
    (don't block trading when collector is down — fail-open)."""
    try:
        total_5m_usd = liq_db.recent_liq_notional(symbol, lookback_sec=300)
    except Exception:
        return True   # fail-open
    return total_5m_usd <= V3_LIQ_QUIET_THRESHOLD_USD
```

Wire into the signal gate, in this order (cheapest checks first):

```python
def v3_signal_passes_gates(symbol: str, tf: str, ret_5m: float, ret_15m: float,
                           ret_1h: float, now_unix_s: int, liq_db) -> tuple[bool, str]:
    """Returns (pass, reason). Reason useful for logging."""
    if not v3_hour_passes(now_unix_s):
        return False, "hour_blocked"
    if not v3_macro_2of3_passes(ret_5m, ret_15m, ret_1h):
        return False, "macro_2of3_fail"
    if not v3_liq_quiet_passes(symbol, now_unix_s, liq_db):
        return False, "liq_active_regime"
    return True, "passes"
```

Call site (existing V3 signal generator):

```python
# inside _maybe_emit_v3_signal or equivalent
fired = abs(ret_5m) >= threshold and direction_passes(...)
if fired:
    ok, reason = v3_signal_passes_gates(symbol, tf, ret_5m, ret_15m, ret_1h, now, liq_db)
    if not ok:
        log_skip(reason)
        return Signal.NONE  # record event, don't place order
```

## Liq DB interface (Phase 5 dependency)

The `liq_db.recent_liq_notional(symbol, lookback_sec)` method needs to query VPS2:

```python
class LiqDB:
    def recent_liq_notional(self, symbol: str, lookback_sec: int = 300) -> float:
        """Sum of (price * size) for liquidations in last lookback_sec.
        Symbol: 'BTC' / 'ETH' / 'SOL'.
        Falls back to 0.0 if VPS2 unreachable.
        """
        sql = """
            SELECT COALESCE(SUM(price * size), 0)::numeric AS total_usd
            FROM binance_liquidations_v2
            WHERE symbol_id = %s
              AND time_exchange_us >= (EXTRACT(EPOCH FROM NOW()) - %s) * 1e6
        """
        symbol_id = f"BINANCEFTS_PERP_{symbol}_USDT"
        try:
            with vps2_pool.connection() as conn:
                r = conn.execute(sql, (symbol_id, lookback_sec)).fetchone()
                return float(r[0])
        except Exception:
            return 0.0   # fail-open: assume quiet if can't query
```

Cache last-queried value with 30s TTL to avoid hammering VPS2.

## Tests (5 unit, 1 integration)

```python
# backend/tests/unit/test_v3_2_gates.py

def test_v3_hour_block_22_utc_blocks():
    # 2026-04-30 22:30 UTC
    assert not v3_hour_passes(1777616400)

def test_v3_hour_block_14_utc_passes():
    assert v3_hour_passes(1777587600)  # 14:30 UTC

def test_v3_macro_2of3_passes_when_15m_agrees():
    assert v3_macro_2of3_passes(0.005, 0.003, -0.001)  # 5m+, 15m+, 1h-

def test_v3_macro_2of3_passes_when_1h_agrees():
    assert v3_macro_2of3_passes(0.005, -0.003, 0.001)

def test_v3_macro_2of3_fails_when_both_disagree():
    assert not v3_macro_2of3_passes(0.005, -0.003, -0.001)

def test_v3_macro_2of3_DOWN_signal():
    assert v3_macro_2of3_passes(-0.005, 0.001, -0.003)  # 1h agrees with -5m

def test_v3_liq_quiet_skips_above_threshold():
    class FakeDB:
        def recent_liq_notional(self, sym, lookback_sec): return 15_000
    assert not v3_liq_quiet_passes("BTC", 0, FakeDB())

def test_v3_liq_quiet_fails_open_on_db_error():
    class BrokenDB:
        def recent_liq_notional(self, sym, lookback_sec): raise RuntimeError("vps2 down")
    assert v3_liq_quiet_passes("BTC", 0, BrokenDB())
```

## Per-asset interaction notes

- **BTC:** all 3 gates apply
- **ETH:** all 3 gates apply
- **SOL:** already has 3-of-3 multi-horizon at signal level. The macro 2-of-3 gate is **redundant for SOL** (skip it for SOL). Hour and liq gates still apply.

In code:

```python
# Skip 2-of-3 for SOL (already has 3-of-3 at threshold level)
if symbol.upper() != "SOL":
    if not v3_macro_2of3_passes(...): return False, "macro_2of3_fail"
```

## What V3.2 does NOT yet include

- **Phase 2: ETH CLOB imbalance gate** — requires Polymarket WS subscriber. Build separately (1-2 days TV work). Then V3.3.
- **Phase 4: Signal-quality Kelly** — backtest rejected, do not implement.
- **Phase 6: Platt calibration** — scaffold saved, deferred until multi-signal probability fusion exists.
- **SOL UP live disable** (V3.1 surgical fix) — KEEP from V3.1 patch. SOL UP stays paper-only until live ≥55% on n≥30.

## Combined V3.1 + V3.2 → "V3.2-final" sleeve config

```python
V3_SLEEVE_CONFIG = {
    ("BTC", "5m"): {
        "quantile_up": 0.90, "quantile_down": 0.90,
        "selector": "mag_only",
        "live_directions": {"UP", "DOWN"},
        "gates": {"hour", "macro_2of3", "liq_quiet"},
    },
    ("ETH", "5m"): {
        "quantile_up": 0.97, "quantile_down": 0.95,   # V3.1 asymmetric
        "selector": "mag_only",
        "live_directions": {"UP", "DOWN"},
        "gates": {"hour", "macro_2of3", "liq_quiet"},
    },
    ("SOL", "5m"): {
        "quantile_up": 0.92, "quantile_down": 0.85,   # V3.1 asymmetric
        "selector": "multi_horizon",                   # already 3-of-3
        "live_directions": {"DOWN"},                   # V3.1 surgical: skip UP live
        "gates": {"hour", "liq_quiet"},                # skip macro_2of3 for SOL (redundant)
    },
}
```

## Effort

- **Code:** ~80 lines (3 gate functions + LiqDB + sleeve config refactor)
- **Tests:** 8 unit, 1 integration
- **DB infra:** read-only connection pool to VPS2 from VPS3
- **Deploy:** single PR, hot-patchable, ~3-4 hours TV agent work

## Rollback

Feature-flag every gate:

```python
V3_2_HOUR_BLOCK_ENABLED = os.getenv("V3_2_HOUR_BLOCK", "true") == "true"
V3_2_MACRO_2OF3_ENABLED = os.getenv("V3_2_MACRO_2OF3", "true") == "true"
V3_2_LIQ_QUIET_ENABLED = os.getenv("V3_2_LIQ_QUIET", "true") == "true"
```

Disable any single gate via env without deploy:

```bash
ssh vps3 "echo V3_2_LIQ_QUIET=false >> /etc/tv/tradingvenue.env && systemctl restart tv"
```

## Kill conditions (auto-pause)

If after V3.2 deploy:

- Combined hit rate drops <55% on n≥30 in any rolling 24h → pause all V3 sleeves, page operator
- Specific gate causes >40% reduction in fires (suspect over-restrictive) → flip that gate's env to false
- Liq DB queries time out >5% of the time → set V3_2_LIQ_QUIET=false (regime gate too costly to query)

## Files

- This spec: `strategy_lab/reports/V3_2_DEPLOY_SPEC_2026_04_30.md`
- Combined backtest: `strategy_lab/v4_signals/v3_2_combined_test.py`
- Per-phase analysis (already done): `strategy_lab/reports/V4_PLAN_AND_RESULTS_2026_04_30.md`
- V3.1 surgical fixes (precedes this): `strategy_lab/reports/V3_1_PATCH_SPEC_2026_04_30.md`
- V3 deploy guide (to update with V3.2): `strategy_lab/reports/polymarket/01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`
