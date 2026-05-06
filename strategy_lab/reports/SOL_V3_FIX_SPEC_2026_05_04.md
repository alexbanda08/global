# SOL V3 Fix + V3.3 A/B Sleeve Spec

**Date:** 2026-05-04 (revised — A/B sleeve approach)
**Status:** Ready for TV agent
**Trigger:** TV agent's `V3_FAMILY_AUDIT` (2026-05-04) confirmed SOL V3 / V3.1 / V4 fire 0 orders not due to bug, but due to:
  - SOL Polymarket UpDown 5m books have spread ≥ 2% essentially always (median 4-6%, never below 2.02% across 184 wide_spread_skip events).
  - `V3_SPREAD_FILTER_PCT = 0.02` is BTC-calibrated; structurally too tight for SOL.
  - V3 / V3.1 / V4 SOL also carry multi-horizon AND filter, sampling fewer bars; none of those rare ≤2%-spread bars happened to coincide.

Companion data: `strategy_lab/reports/V3_BACKTEST_FINDINGS_2026_05_04.md` (backtest with all gates: chronological CV, permutation, bootstrap, stop-loss, tail risk).

---

## TL;DR — Two-part change

This PR ships **two independent changes** that together restore SOL coverage AND set up an A/B test for multi-horizon's value:

1. **Fix A — per-asset spread filter** (ships immediately, all SOL V3-family sleeves benefit). Single helper + env config.
2. **NEW v3_3 sleeve — SOL-only A/B test sleeve** = V3.2 logic + multi-horizon for SOL. Paper-only for 7 days. Compares directly against V3.2 (which has no multi-horizon) to settle whether multi-horizon adds quality or just culls trades.

After 7 days, compare V3.2 vs V3.3 SOL hit rates side-by-side. Decision rule:
- V3.3 hit% ≥ V3.2 hit% + 3pp on n≥30 → multi-horizon helps; promote V3.3 to live, retire V3.2 SOL OR apply MH to V3.2.
- V3.3 hit% ≤ V3.2 hit% − 3pp → multi-horizon hurts; keep status quo, drop the V3.3 experiment.
- Within ±3pp → MH is neutral; keep status quo (avoid unnecessary code).

This avoids the irreversible decision the original "Fix B" (apply MH to V3.2 in production) would have forced.

---

## Backtest evidence behind this design

Backtest on 7-day partial window (`phase7_validation_v3.py`):

| Variant | SOL fires | Hit% | PnL ($1 stake) |
|---|---:|---:|---:|
| Current production (uniform 0.02 spread, MH on for V3 base) | 20 | 55.0% | +$1.81 |
| **Fix A only (SOL=0.025, MH on for V3 base)** ⭐ | 23 (+15%) | 60.9% (+5.9pp) | +$4.79 (+165%) |
| Fix A + drop MH | 34 (+70%) | 61.8% | +$7.27 |

Backtest weakly suggests multi-horizon culls profitable trades. But sample is small (23 vs 34 trades, 7-day window). Don't make a permanent design change off this. **Run V3.3 A/B for 7 days of live shadow data → decide with bigger sample.**

---

## Fix A — Per-asset spread filter

### Problem

`backend/app/controllers/polymarket_updown.py` line 172:
```python
V3_SPREAD_FILTER_PCT = 0.02   # 2% — applied uniformly to all assets
```

SOL Polymarket UpDown 5m markets have median spread 4-6%, minimum observed 2.02%. The 2% threshold blocks essentially every SOL signal.

### Solution

Replace constant with per-asset dict + env-driven overrides:

```python
# polymarket_updown.py — replace single constant
V3_SPREAD_FILTER_PCT_DEFAULT = {
    "BTC": 0.02,
    "ETH": 0.02,
    "SOL": 0.025,    # SOL median spread is 4-6%; 2.5% catches tightest 5-10%
}

def _v3_spread_filter_for(symbol: str) -> float:
    """Per-asset spread filter, env-overridable.

    Env var: TV_POLY_V3_SPREAD_FILTER_<ASSET>=0.0XX
    """
    sym = symbol.upper()
    env_key = f"TV_POLY_V3_SPREAD_FILTER_{sym}"
    env_val = os.environ.get(env_key)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            pass
    return V3_SPREAD_FILTER_PCT_DEFAULT.get(sym, 0.02)
```

Replace existing usage at line 172 area:
```python
# OLD:
if (entry_yes_ask - entry_yes_bid) > V3_SPREAD_FILTER_PCT:
    audit("wide_spread_skip", ...)
    return Signal.NONE

# NEW:
spread_filter = _v3_spread_filter_for(symbol)
if (entry_yes_ask - entry_yes_bid) > spread_filter:
    audit("wide_spread_skip", reason=f"spread>{spread_filter}")
    return Signal.NONE
```

### Env config (VPS3)

```bash
# /etc/tv/tradingvenue.env
TV_POLY_V3_SPREAD_FILTER_BTC=0.02
TV_POLY_V3_SPREAD_FILTER_ETH=0.02
TV_POLY_V3_SPREAD_FILTER_SOL=0.025
```

Operator-tunable: if SOL fires too few or too many, adjust `_SOL` to 0.022 or 0.030.

### Expected impact

After Fix A ships, SOL V3-family sleeves come alive:
- `poly_updown_sol_5m_v3` (V3 base, has MH): 5-15 fires/day
- `poly_updown_sol_5m_v3_1` (V3.1, asymmetric q + MH): 1-3 fires/day
- `poly_updown_sol_5m_v3_2` (V3.2, gates only, NO MH): 5-15 fires/day  ← still no MH
- `poly_updown_sol_5m_v4` (V4, V3.1 + V3.2 stacked, has MH): 0-1 fires/day

BTC/ETH unaffected.

---

## V3.3 — NEW A/B sleeve (SOL only, paper-only initial deploy)

### Purpose

Resolve the multi-horizon question with live shadow data instead of permanently committing to "with MH" or "without MH" for V3.2 SOL.

V3.3 SOL = V3.2 logic + multi-horizon requirement. Run alongside V3.2 (no MH) for direct A/B.

### Logic

```python
# polymarket_updown.py — add new mode branch parallel to v3_2
elif mode == "v3_3":
    # IDENTICAL to v3_2 except multi-horizon required for SOL
    # (so V3.3 BTC == V3.2 BTC, V3.3 ETH == V3.2 ETH; the difference is SOL only)
    aux["use_v3_quantile"]    = True
    aux["use_hour_blocklist"] = True
    aux["use_macro_2of3"]     = True
    aux["use_liq_quiet"]      = True
    if (sym_upper, tf) in V3_REQUIRE_MULTI_HORIZON:
        aux["require_multi_horizon"] = True       # ← THE ONLY DIFFERENCE FROM v3_2
    sleeve_id = f"poly_updown_{symbol.lower()}_{tf}_v3_3"
```

### Sleeve registration (`backend/app/api/bots.py`)

```python
_POLY_UPDOWN_SLEEVE_IDS: tuple[str, ...] = (
    # ... existing 24 sleeves (V1 + V2 + V3 + V3.1 + V3.2 + V4) ...

    # NEW: V3.3 — V3.2 + multi-horizon (SOL only meaningfully different)
    # We add all 3 assets for symmetry but BTC/ETH should match V3.2 exactly.
    "poly_updown_btc_5m_v3_3",     # control — should match v3_2 BTC perfectly
    "poly_updown_eth_5m_v3_3",     # control — should match v3_2 ETH perfectly
    "poly_updown_sol_5m_v3_3",     # ⭐ EXPERIMENTAL — A/B against v3_2 SOL
)
```

The BTC/ETH v3_3 sleeves are control samples — they SHOULD fire identically to v3_2 (no MH applies). If they don't, there's a bug in the v3_3 branch.

### Frontend (`frontend/app/bots/page.tsx`)

```typescript
const POLY_V3_3_SLOTS: PolySlotEntry[] = [
  { id: 'poly_updown_btc_5m_v3_3', underlying: 'BTC', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_eth_5m_v3_3', underlying: 'ETH', windowLabel: '5m', tfSeconds: 300 },
  { id: 'poly_updown_sol_5m_v3_3', underlying: 'SOL', windowLabel: '5m', tfSeconds: 300 },
];
```

Display label: "V3.3 (V3.2 + MH on SOL)".

### Env config (VPS3)

```bash
# /etc/tv/tradingvenue.env

# Activate v3_3 mode (paper-only via the live-disabled mechanism inherited from V3.1)
TV_POLY_STRATEGY_MODES=volume,sniper,v3,v3_1,v3_2,v3_3,v4

# v3_3 enabled + paper only (NO live trades — operator-controlled flag)
V3_3_ENABLED=true
V3_3_LIVE_DISABLED=true
```

### Code branch in controller for paper-only enforcement

```python
# polymarket_updown.py — at signal-fire path
if self.strategy_mode == "v3_3" and live_mode and os.environ.get("V3_3_LIVE_DISABLED", "true") == "true":
    audit("v3_3_paper_only", ...)
    return Signal.NONE
```

(Paper events still record in `trading.events`, so dashboard + analysis still work.)

---

## Decision protocol (after 7 days)

Run this query daily:

```sql
SELECT
  CASE
    WHEN sleeve_id LIKE '%_v3_2' THEN 'V3.2 (no MH)'
    WHEN sleeve_id LIKE '%_v3_3' THEN 'V3.3 (with MH)'
  END AS variant,
  data->>'symbol' AS symbol,
  COUNT(*) AS n,
  AVG((data->>'won')::boolean::int) AS hit_rate,
  ROUND(SUM((data->>'pnl_usd')::numeric), 2) AS pnl
FROM trading.events
WHERE kind='poly_updown_resolution'
  AND sleeve_id ~ '_(v3_2|v3_3)$'
  AND data->>'symbol' = 'SOL'
  AND at > NOW() - INTERVAL '7 days'
GROUP BY 1, 2 ORDER BY 1;
```

**Decision rule** (require n≥30 SOL fires per variant):

| V3.3 SOL hit% vs V3.2 SOL hit% | Action |
|---|---|
| V3.3 ≥ V3.2 + 3pp | **Adopt MH** — apply Fix B permanently to V3.2 SOL; retire V3.3 sleeve. |
| V3.3 ≤ V3.2 − 3pp | **Reject MH** — keep V3.2 as-is; ALSO drop MH from V3 base / V3.1 / V4 SOL (those are losing money to MH culling). |
| Within ±3pp | **Neutral** — keep status quo (V3.2 keeps no-MH, V3 base / V3.1 / V4 keep MH). Retire V3.3. |

**Validation control:** BTC and ETH v3_3 stats MUST match v3_2 stats exactly (zero meaningful difference). If they diverge, there's a bug.

---

## Combined deployment

### Code changes summary

| File | Change | Lines |
|---|---|---:|
| `polymarket_updown.py` | Add `V3_SPREAD_FILTER_PCT_DEFAULT` dict | +6 |
| `polymarket_updown.py` | Add `_v3_spread_filter_for()` helper | +14 |
| `polymarket_updown.py` | Replace constant usage with helper call | -1 +1 |
| `polymarket_updown.py` | Add `v3_3` mode branch (V3.2 + MH for SOL) | +12 |
| `polymarket_updown.py` | Paper-only gate for v3_3 | +4 |
| `bots.py` | Add 3 v3_3 sleeve_ids | +5 |
| `frontend/app/bots/page.tsx` | Add `POLY_V3_3_SLOTS` array + dashboard section | +12 |
| `/etc/tv/tradingvenue.env` (VPS3) | Add 3 spread-filter env vars + 2 v3_3 env vars | +5 |

Total: ~58 line diff, single PR.

### Tests (`backend/tests/unit/test_v3_per_asset_spread_and_v3_3.py`)

```python
# Fix A tests
def test_default_spread_filter_per_asset():
    assert _v3_spread_filter_for("BTC") == 0.02
    assert _v3_spread_filter_for("ETH") == 0.02
    assert _v3_spread_filter_for("SOL") == 0.025

def test_spread_filter_env_override(monkeypatch):
    monkeypatch.setenv("TV_POLY_V3_SPREAD_FILTER_SOL", "0.030")
    assert _v3_spread_filter_for("SOL") == 0.030

def test_spread_filter_unknown_asset_default():
    assert _v3_spread_filter_for("BNB") == 0.02

def test_v3_sol_fires_on_25bp_spread():
    # SOL with bid=0.50, ask=0.522 (2.2% spread) should pass with new filter
    ctrl = make_controller(strategy_mode="v3", symbol="SOL", tf="5m")
    ctrl.evaluate(yes_bid=0.50, yes_ask=0.522, ret_5m=0.005, ...)
    assert ctrl.audit_kind != "wide_spread_skip"

def test_v3_btc_still_blocks_25bp_spread():
    # BTC with same 2.2% spread should still skip (BTC=0.02 unchanged)
    ctrl = make_controller(strategy_mode="v3", symbol="BTC", tf="5m")
    ctrl.evaluate(yes_bid=0.50, yes_ask=0.522, ret_5m=0.005, ...)
    assert ctrl.audit_kind == "wide_spread_skip"

# V3.3 tests
def test_v3_3_sol_requires_multi_horizon():
    # V3.3 SOL: ret_5m=+0.5%, ret_15m=+0.3%, ret_1h=-0.5% → SHOULD SKIP (ret_1h disagrees)
    ctrl = make_controller(strategy_mode="v3_3", symbol="SOL", tf="5m")
    ctrl.evaluate(ret_5m=0.005, ret_15m=0.003, ret_1h=-0.005, ...)
    assert ctrl.signal == Signal.NONE  # multi-horizon blocked

def test_v3_3_sol_passes_multi_horizon_aligned():
    # V3.3 SOL: all 3 horizons agree → SHOULD FIRE (modulo other gates)
    ctrl = make_controller(strategy_mode="v3_3", symbol="SOL", tf="5m")
    ctrl.evaluate(ret_5m=0.005, ret_15m=0.003, ret_1h=0.005, ...)
    assert ctrl.aux.get("require_multi_horizon") is True

def test_v3_3_btc_does_not_apply_multi_horizon():
    # V3.3 BTC should match V3.2 BTC exactly (BTC not in V3_REQUIRE_MULTI_HORIZON)
    ctrl = make_controller(strategy_mode="v3_3", symbol="BTC", tf="5m")
    ctrl.evaluate(ret_5m=0.005, ret_15m=-0.003, ret_1h=-0.005, ...)
    # Should NOT be blocked by MH (BTC doesn't have MH)
    assert ctrl.aux.get("require_multi_horizon") is None or False

def test_v3_3_paper_only_in_live_mode(monkeypatch):
    monkeypatch.setenv("V3_3_LIVE_DISABLED", "true")
    ctrl = make_controller(strategy_mode="v3_3", symbol="SOL", tf="5m", live_mode=True)
    ctrl.evaluate(...)
    assert ctrl.audit_kind == "v3_3_paper_only"

def test_v3_3_paper_only_off_in_paper_mode():
    # V3_3_LIVE_DISABLED only blocks live mode
    ctrl = make_controller(strategy_mode="v3_3", symbol="SOL", tf="5m", live_mode=False)
    ctrl.evaluate(...)
    assert ctrl.audit_kind != "v3_3_paper_only"
```

### Rollout

1. Deploy code change with feature flags off:
   ```bash
   TV_POLY_V3_SPREAD_FILTER_SOL=0.02   # match BTC/ETH initially — no behavior change
   V3_3_ENABLED=false                  # V3.3 sleeves don't fire yet
   ```
2. Verify no regression on BTC/ETH V3 fire rates over 24h.
3. Flip Fix A:
   ```bash
   TV_POLY_V3_SPREAD_FILTER_SOL=0.025
   systemctl restart tv-engine
   ```
4. After SOL V3-family fire rates stabilize (24-48h), enable V3.3:
   ```bash
   V3_3_ENABLED=true
   V3_3_LIVE_DISABLED=true
   systemctl restart tv-engine
   ```
5. Monitor V3.2 vs V3.3 SOL daily. Decision after 7 days per protocol above.

### Kill conditions

**Fix A:**
- SOL V3 hit rate <55% on n≥30 → tighten spread filter to 0.022 or rollback.
- SOL V3 fires >50/day → spread too loose, tighten.

**V3.3 (paper-only):**
- BTC v3_3 ≠ BTC v3_2 by more than n_diff>1 over 24h → bug, disable V3.3.
- After 7 days, decide per protocol above.

---

## Effort estimate

| Task | Effort |
|---|---|
| Code: Fix A (helper + per-asset dict) | 30 min |
| Code: V3.3 mode branch + paper-only gate | 1 hr |
| Code: bots.py + frontend page.tsx (3 new sleeve entries + dashboard section) | 1 hr |
| Tests: 9 unit tests (Fix A + V3.3) | 1.5 hr |
| Env config + rollout | 1 hr |
| Smoke test all sleeves fire correctly | 30 min |
| **Total** | **~5.5 hr** |

(About 4 hr more than Fix A alone — paying for the experimental sleeve infrastructure.)

---

## Why ship V3.3 instead of just Fix B?

**Fix B (apply MH to V3.2 in production, no A/B)** would have permanently changed V3.2 behavior based on backtest evidence we admit is small-sample (7-day window, n=23 vs n=34). Backtest says "drop MH" — but backtest also overfits.

**V3.3 as paper-only A/B** lets us collect 7 days of FRESH live data with the actual decision context (regime + book conditions of NEXT week, not last week). Decision becomes evidence-based and reversible (just set `V3_3_ENABLED=false`).

It's also 3-4 hours more work — but for a permanent strategy decision, that's a small price.

---

## Files

- This spec: `strategy_lab/reports/SOL_V3_FIX_SPEC_2026_05_04.md`
- Backtest evidence: `strategy_lab/reports/V3_BACKTEST_FINDINGS_2026_05_04.md`
- Companion V5 LATE spec (rejected after validation): `strategy_lab/reports/V5_LATE_ENTRY_SPEC_2026_05_04.md`
- V5 validation findings (why V5 was rejected): `strategy_lab/reports/PHASE7_VALIDATION_FINDINGS_2026_05_04.md`
- TV agent audit (root cause): provided by user 2026-05-04 (in conversation log)
- V3 patch deploy spec: `strategy_lab/reports/V3_PATCH_OPTION_B_SPEC.md`
- BTC V3 deep dive: `strategy_lab/reports/BTC_V3_DEEP_DIVE_2026_05_04.md`
