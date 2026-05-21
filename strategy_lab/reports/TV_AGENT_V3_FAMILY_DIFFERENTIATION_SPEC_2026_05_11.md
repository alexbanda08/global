# TV Agent Spec — Differentiate v3 / v3_1 / v3_2 / v3_3 / v4 Sleeves

**Date:** 2026-05-11
**Target:** TV agent owning `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py`
**Severity:** Medium — not a crash, but A/B comparison is impossible because 5 "different" sleeves collapse into 2 functional classes
**Author:** strategy-lab agent (alexandre.bandarra)
**HEAD reference:** `7de7b12` on VPS3 (`fix(18.6): Fix B — _try_bid_exit retry on no_bids`)

---

## TL;DR — what we observe

For 65 shadow sleeves running on VPS3 across 14d, the v3 family produces this skip-reason matrix:

| asset | family | no_signal | wide_spread | placed | hedge | other | total |
|---|---|---:|---:|---:|---:|---:|---:|
| btc | **v3** | **1,106** | **71** | 37 | 20 | 1 | 1,235 |
| btc | **v3_1** | **1,106** | **71** | 29 | 15 | 9 | 1,230 |
| btc | **v3_2** | **1,106** | **71** | 21 | 14 | 17 | 1,229 |
| btc | **v3_3** | **1,106** | **71** | 21 | 14 | 17 | 1,229 |
| btc | **v4** | **1,106** | **71** | 19 | 13 | 19 | 1,228 |
| eth | v3 | 1,165 | 45 | 4 | 0 | 1 | 1,215 |
| eth | v3_1 | 1,176 | 36 | 2 | 0 | 1 | 1,215 |
| eth | v3_2 | 1,165 | 45 | 1 | 0 | 4 | 1,215 |
| eth | v3_3 | 1,165 | 45 | 1 | 0 | 4 | 1,215 |
| eth | v4 | 1,176 | 36 | 0 | 0 | 3 | 1,215 |

**The `no_signal` and `wide_spread` counts are byte-identical across all 5 sleeves on BTC**, and on ETH they split into two clusters: `{v3, v3_2, v3_3}` and `{v3_1, v4}`.

Byte-equality check (last 24h, after stripping `strategy_mode`/`condition_id` labels):
- **BTC: 279 of 310 minutes** all 5 sleeves emit identical payload (90%).
- **ETH: 282 of 294 minutes** all 5 sleeves emit identical payload (96%).
- SOL: 242 of 348 (70%) — SOL v3_2 is the only outlier.

---

## What the code is supposed to do

Per docstring in `polymarket_updown.py:1146`:

| mode | quantile | extra gates |
|---|---|---|
| `v3` | per-asset (BTC 0.90 / ETH 0.95 / SOL 0.85) via `V3_PER_ASSET_QUANTILE` | none |
| `v3_2` | reuses V3 base quantile (no asymmetry) | V3.2 hour + V3.2 macro_2of3 + V3.2 liq_quiet |
| `v3_3` | reuses V3 base quantile | V3.2 gates + SOL MH-AND filter (BTC/ETH unchanged from v3_2) |
| `v3_1` | direction-aware via `V3_1_PER_ASSET_QUANTILE` (tuple thr_up, thr_down) | V3.1 regime overlay + V3.1 live-direction filter |
| `v4` | direction-aware (same as v3_1) | V3.1 regime + V3.1 live-direction + V3.2 hour + V3.2 macro_2of3 + V3.2 liq_quiet |

So in code, the 5 modes SHOULD produce 5 distinct empirical patterns. Reality says they collapse into 2 classes.

---

## Root cause analysis — three independent issues

### Issue 1 — V3.1 and V3.2 audit gates produce **zero blocking audits** in 14d

The empirical skip-reason breakdown contains only `no_signal`, `wide_spread_skip`, `order_placed`, `hedge_placed`, `market_already_resolved`. The expected gate-block reasons are completely absent:

| missing skip-reason | code location | gate function |
|---|---|---|
| `regime_blocked` | L1872-1890 | `v3_1_regime_passes(direction, ret_1h)` |
| `hour_blocked` | L1899-1918 | `v3_2_hour_passes(now_unix_s)` |
| `macro_2of3_data_missing` / `macro_2of3_fail` | L1924-1962 | `v3_2_macro_2of3_passes(symbol, ret_5m, ret_15m, ret_1h)` |
| `liq_active_regime` | L1965-1984 | `v3_2_liq_quiet_passes(symbol, liq_db)` |
| `live_direction_filtered` | L1986-2010 | `v3_1_live_direction_allowed(symbol, tf, direction, live_mode)` |

Either (a) all five gates are env-flag-disabled (the helpers' "disabled gate is a no-op pass" comment at L1854 hints at this), or (b) they're enabled but pass-through 100% of the time.

**Verify by running:**
```bash
ssh root@185.190.143.7 'grep -E "TV_POLY_V3_1_|TV_POLY_V3_2_|TV_POLY_V4_" /etc/tv/tv.env /etc/tv/tv-ro.env 2>/dev/null; systemctl cat tradingvenue 2>/dev/null | grep -E "TV_POLY_V3_|TV_POLY_V4_"'
```

If output is empty → gates are at default. Default behavior needs inspection in the helper definitions (L381-457 of the controller).

### Issue 2 — `v3_1` and `v4` share their entire empirical signature

Code search:
```
1186:        elif self.strategy_mode in ("v3_1", "v4"):    # directional quantile
1872:            if self.strategy_mode in ("v3_1", "v4"):  # V3.1 regime
1986:            if self.strategy_mode in ("v3_1", "v4"):  # V3.1 live-direction
1899, 1924, 1965:  v3_2/v3_3/v4 share V3.2 gates
```

v4 = v3_1 + V3.2 gates. If V3.2 gates are disabled (Issue 1), **v4 is functionally identical to v3_1**.

There is **no v4-only branch** in the controller. `grep '"v4"' polymarket_updown.py` shows v4 only in tuple memberships, never alone.

### Issue 3 — `v3_2` and `v3_3` are identical by design on BTC/ETH

Per L1086 comment and test docstring: *"V3.3 is identical to v3_2 EXCEPT it adds the multi-horizon AND filter for SOL only (V3.2 + MH-on-SOL). BTC/ETH v3_3 are control samples — should match v3_2 behavior exactly."*

This is **intentional**. v3_3 was designed as an A/B variant against v3_2 on SOL. On BTC/ETH it's a "control sample" — identical signal output is correct.

But the user's stated intent is *"have v1 v2 v3 firing with each gate individually so I can analyze"*. That contradicts the design. The user wants v3_3 to genuinely differ from v3_2 on BTC/ETH too.

---

## What the TV agent needs to fix

Three independent fixes, each can ship separately. Prefer Fix 1 first since it unblocks the others.

### Fix 1 — Enable the V3.1 + V3.2 audit gates (highest priority)

**Where:** server env config (`/etc/tv/tv.env` or systemd unit override), no controller code change needed.

**What:** set the env vars that activate the gate helpers. Confirm the existence and exact names by reading L381-457 of `polymarket_updown.py` — likely candidates:

```
TV_POLY_V3_1_REGIME_ENABLED=true
TV_POLY_V3_1_LIVE_DIRECTION_ENABLED=true
TV_POLY_V3_2_HOUR_GATE_ENABLED=true
TV_POLY_V3_2_MACRO_2OF3_ENABLED=true
TV_POLY_V3_2_LIQ_QUIET_ENABLED=true
```

**Verification:** within 30 minutes of restart, `trading.events` should contain new audit rows with `data->>'reason'` in `{regime_blocked, hour_blocked, macro_2of3_fail, liq_active_regime, live_direction_filtered}`. Re-run the all-sleeve aggregation query (`strategy_lab/meta_classifier/_vps3_all_sleeves_table.sh`) — v3/v3_1/v3_2/v3_3/v4 should now diverge.

**Rollback:** flip env vars to `false`; helpers fall through as no-op.

### Fix 2 — Differentiate v4 from v3_1

After Fix 1, v4 will differ from v3_1 IF the V3.2 gate-stack now blocks bars (since v4 inherits both V3.1 and V3.2 gates, v3_1 only V3.1). Likely sufficient.

If users still want a *unique* v4 capability beyond "v3_1 + V3.2 gates":
- Add a new env flag `TV_POLY_V4_<SOMETHING>` documenting v4's intended addition
- Add a single `if self.strategy_mode == "v4":` branch in the controller's gate stack
- Record the spec for that addition (the current source has no v4-specific gate — v4 is purely a union of v3_1 and v3_2)

**Suggested diff** (placeholder for a real spec):
```python
# Phase 19 — v4 hyperaggressive: tightest spread filter, lowest macro threshold.
if self.strategy_mode == "v4":
    # Example: tighter spread filter for v4 only.
    if spread_pct > 0.015:
        await self._audit(symbol, tf, reason="v4_tight_spread_skip", ...)
        return
```

**Status:** awaiting product decision on what v4 should actually do.

### Fix 3 — Decide v3_3's behavior on BTC/ETH

Two options:

**Option A — keep current design (v3_3 = v3_2 on BTC/ETH, MH-AND on SOL):**
- This is documented behavior. Update operator docs / dashboard tooltip so the lab agent doesn't flag it as a bug again.
- Mark v3_3 as "SOL-only differentiator" in the sleeve registry.

**Option B — extend v3_3's multi-horizon AND filter to all assets:**
- Edit L1134: change `self.strategy_mode in ("v3_1", "v3_3", "v4")` so v3_3 always enters the SOL-MH block, AND change the SOL-only `if symbol == "SOL"` inside that block to apply to BTC/ETH as well.
- Reference: SOL_V3_FIX_SPEC_2026_05_04.md, Phase 18.3.

Recommend **Option A** — preserves the audit trail; the user can simply use a different sleeve_mode (a real v3_3b) if they want a genuinely-different gate.

---

## Test-suite updates required

Existing tests live in `backend/tests/unit/test_v3_per_asset_spread_and_v3_3.py`. After Fix 1, the tests assume gates default to no-op (pure-function tests). Add:

1. **Integration test** — boot the controller with `TV_POLY_V3_1_REGIME_ENABLED=true`, fire a bar where `ret_1h` direction conflicts with the signal direction, assert the controller emits `regime_blocked` audit + returns without placing an order.

2. **Differentiation test** — feed identical 14d sample history into 5 controllers (one per strategy_mode), fire 100 random bars, assert the 5 sleeves produce ≥3 distinct fire patterns. Add a regression for the empirical observation reported in this spec.

3. **v4 vs v3_1 unit** — after the v4 differentiator is added per Fix 2, assert that the same input bar produces different `(reason, signal)` for v4 vs v3_1 on at least one realistic scenario.

---

## Verification plan (post-fix)

After deploying Fix 1, leave the 36-sleeve shadow run for 24-48h, then re-run:

```bash
bash strategy_lab/meta_classifier/_vps3_all_sleeves_table.sh
bash strategy_lab/meta_classifier/_vps3_verify_v3_clones.sh
```

Expected result:
- BTC: distinct-payload minutes drop from 90%-identical to <30%-identical (gates produce diverging skip-reasons).
- ETH: similar drop.
- Skip-reason breakdown shows new categories present per sleeve.
- v3_1 ≠ v4 fire counts and outcomes.
- v3 ≠ v3_2 ≠ v3_3 (on cells where V3.2 gates trigger).

If post-fix the sleeves still don't diverge → Issue 1 was misdiagnosed; escalate to read each helper's env-flag defaults at L381-457.

---

## Production-state invariants

1. Do not change `momo` / `momo_v2` sleeve behavior — they're under separate Phase 3+4 investigation (see `MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md`).
2. Do not change `sniper`, `sniper_INV`, `sniper_DOWN_INV`, `volume_INV_NIGHT` — out of scope.
3. Spread filter (`_v3_spread_filter_for`) is correctly per-asset already (BTC 0.02, ETH 0.02, SOL 0.025). No change needed there for this fix.
4. Keep all 65 shadow sleeves running through the fix rollout so we have continuous A/B data.

---

## Side-finding (separate bug lead, not in this spec)

`eth_5m_momo_v2_HOLD` has 24 `qty_compute_failed` events in 7d (visible in skip-reason breakdown). This is a real implementation error — track separately.

---

## Files / scripts referenced

| path | purpose |
|---|---|
| `strategy_lab/reports/TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md` | this spec |
| `strategy_lab/reports/ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md` | initial finding |
| `strategy_lab/reports/ALL_SHADOW_SLEEVES_TABLE_2026_05_11.md` | 65-sleeve baseline table |
| `strategy_lab/meta_classifier/_vps3_diagnose_eth_v3_deep.sh` | skip-reason + spread aggregation |
| `strategy_lab/meta_classifier/_vps3_verify_v3_clones.sh` | byte-equality verifier |
| `strategy_lab/meta_classifier/_vps3_grep_strategy_mode.sh` | code-location grep |
| `strategy_lab/meta_classifier/_vps3_read_dispatcher.sh` / `_pt2.sh` | source dumps |
| `data/v4/shadow_trades_2026_05_09/all_sleeve_stats.csv` | raw per-sleeve aggregate (last 14d) |
| `/opt/tradingvenue/backend/app/controllers/polymarket_updown.py:L1042-2010` | controller code under investigation |
| `/opt/tradingvenue/backend/tests/unit/test_v3_per_asset_spread_and_v3_3.py` | existing tests |
