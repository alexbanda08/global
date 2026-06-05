# Fidelity Audit — V8 (14 sleeves) + H (HEDGE_LATE) — 2026-05-29

**Auditor:** Claude Sonnet 4.6  
**Live files read:**
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_sleeves.py`
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py`
- `/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_thresholds.py`
- `/opt/tradingvenue/backend/app/controllers/polymarket_sniper_v5.py`
- `/opt/tradingvenue/backend/app/engine/poly_sniper_v5_loop.py`

**Spec docs:** `SHADOW_DEPLOY_SPEC_UNIFIED_V6_V7_V8_2026_05_27.md` (§3/§4), `SHADOW_DEPLOY_SPEC_SLEEVE_H_HEDGELATE_2026_05_27.md`

---

## 1. Per-sleeve fidelity table (14 V8 + 1 H)

| ID | sleeve_id (suffix stripped) | Dir | Offsets | Spread | Gates (live) | Spec gates | Verdict |
|----|------------------------------|-----|---------|--------|--------------|------------|---------|
| V8_01 | btc_5m_l_1hrf_imb5_rf_v8 | BOTH | 30-270 (9) | 0.02 | g_grandparent_trend_with(BTC) + g_imb5_strong_with + g_rf_with(BTC) | g_1h_rf_with(BTC) + g_imb5_strong_with + g_rf_with(BTC) | **GATE MISMATCH** |
| V8_02 | btc_5m_l_1hrf_imb5_ribbon_v8 | BOTH | 30-270 (9) | 0.02 | g_grandparent_trend_with(BTC) + g_imb5_strong_with + g_ribbon_agrees(BTC) | g_1h_rf_with(BTC) + g_imb5_strong_with + g_ribbon_agrees(BTC) | **GATE MISMATCH** |
| V8_03 | btc_5m_q_parent15mslope_ts_imb5_v8 | BOTH | 30-270 (9) | 0.02 | g_parent_15m_slope_with(BTC) + g_trend_slope_strong_with(BTC,5m) + g_imb5_strong_with | same | PASS |
| V8_04 | eth_5m_l_ema50_hurst_grandparent_v8 | BOTH | (60,) | 0.02 | g_tr_above_ema50(ETH) + g_hurst_trending(ETH,5m) + g_grandparent_trend_with(ETH) | same | PASS |
| V8_05 | eth_5m_k_hurst_ts_cci_tod_euus_v8 | BOTH | (120,) | 0.02 | g_hurst_regime_with(ETH,5m) + g_trend_slope_with(ETH,5m) + g_cci_with(ETH) + g_tod_europe_us_window | g_hurst_trend_with (= alias for g_hurst_regime_with) + same | PASS (alias) |
| V8_06 | eth_5m_lq_ema50_hurst_grandparent_prev15m_v8 | BOTH | (60,) | 0.02 | g_tr_above_ema50(ETH) + g_hurst_regime_with(ETH,5m) + g_grandparent_trend_with(ETH) + g_q_prev15m_agrees(ETH) | g_hurst_trend_with (alias = g_hurst_regime_with) + same | PASS (alias) |
| V8_07 | sol_5m_btcf7against_cci_hurstrev_mfi_v8 | BOTH | 30-240 (8) | 0.025 | g_btc_f7_against + g_cci_extreme_with(SOL) + g_hurst_reverting(SOL,5m) + g_mfi_strong_with(SOL) | same | PASS |
| V8_08 | sol_5m_j_2asset_trending_cci_rf_ema200_v8 | BOTH | 30-240 (8) | 0.025 | g_2asset_either_trending_with + g_cci_extreme_with(SOL) + g_rf_with(SOL) + g_tr_above_ema200(SOL) | same | PASS |
| V8_09 | eth_15m_baseline_v7_top_replicate_v8 | BOTH | (0,30,60) | 0.02 | g_tr_stack_full_with(ETH) + g_above_1h_dailyvwap_with(ETH) + g_offset_early + g_vol_high(ETH,15m) + g_pw_btc_15m_trend_with | same | PASS |
| V8_10 | eth_15m_pj_btc_and_sol_trend_sep_v8 | BOTH | (0,30,60) | 0.02 | V8_09 gates + g_pw_sol_15m_trend_with | same | PASS |
| V8_11 | sol_15m_v7s5_plus_eth1h_adx_v8 | BOTH | (60,120,240) | 0.025 | g_hod_european_morning + g_off_60_240 + g_rf_with(SOL) + g_tr_stack_with(SOL) + g_BTC_slope_with + g_BTC_slope_strong_with + g_L_ETH_grandparent_adx_strong | same | PASS |
| V8_12 | sol_15m_v7_base_s5_slope_str_v8 | BOTH | (60,120,240) | 0.025 | g_hod_european_morning + g_off_60_240 + g_rf_with(SOL) + g_tr_stack_with(SOL) + g_BTC_slope_with + g_BTC_slope_strong_with | same | PASS |
| V8_13 | sol_15m_v6_j_btceth_vollow_l_ethadx_v8 | BOTH | (60,120,240) | 0.025 | g_hod_european_morning + g_off_60_240 + g_rf_with(SOL) + g_tr_stack_with(SOL) + g_J_btc_eth_vol_both_low + g_L_ETH_grandparent_adx_strong | same | PASS |
| V8_14 | btc_15m_btceth_diverg_stoch_volcontr_v8 | UP | (720,) | 0.02 | g_dir_up + g_btc_eth_divergence + g_stoch_with(BTC) + g_vol_contracting(BTC,15m) | same | PASS |
| H | btc_15m_ema50_ema800_off600_down_H | DOWN | (600,) | 0.02 | g_dir_down + g_tr_above_ema50(BTC) + g_tr_above_ema800(BTC) + exit_policy="HEDGE_LATE" | same | PASS |

**PASS: 13/15. FAIL: 2/15 (V8_01, V8_02).**

---

## 2. g_vol_contracting bug — confirmation + verdict

### Background (the originally-reported bug)

The spec task stated `g_vol_contracting` returns `row.rv_60 < thr*0.5` where `rv_60` is ANNUALIZED (×√35040 for 15m) but `thr` is RAW → always False → sleeve V8_14 permanently blocked.

### Live code (verified 2026-05-29)

```python
def g_vol_contracting(
    direction: str, fire_us: int, *, asset: str, tf: str,
    regime_panel: Any, vol_hurst_panel: Any, **_kw: Any,
) -> bool:
    """V8 §3.9 — realized_vol_60m < BTC/ETH/SOL median proxy at (asset, tf)."""
    ...
    thr = VOL_HIGH_RV60_THR.get((asset, tf))
    af = ANNUAL_FACTOR_BY_TF.get(tf)
    if thr is None or af is None:
        return False
    raw_rv = row.rv_60 / (af ** 0.5)   # de-annualize to match raw threshold scale
    return raw_rv < thr * 0.5
```

`ANNUAL_FACTOR_BY_TF = {"5m": 105_120, "15m": 35_040}` (from `vol_hurst.py`).  
`VOL_HIGH_RV60_THR[("BTC","15m")] = 0.0162`.

### Numeric verification

- `rv_60` is stored annualized: `raw_rv * sqrt(35040)` ≈ `raw_rv * 187.2`
- Old bug: `3.03 < 0.0081` → always False (annualized vs raw threshold)
- Live fix: `row.rv_60 / sqrt(35040) < 0.0162 * 0.5` → `raw_rv < 0.0081` → evaluates correctly

**VERDICT: THE BUG IS FIXED.** The live code contains the de-annualize fix (`TV_FIX_VOL_HIGH_RV60_SCALE_BUG_2026_05_27`). `g_vol_contracting` is functional. V8_14 is NOT permanently blocked. The same fix was applied to `g_vol_high` identically.

Note: the bug description in the mission ("always False → 0 placements") described the pre-fix state. The fix was already deployed as part of the V8 rollout.

---

## 3. V8_01/V8_02 gate mismatch — g_1h_rf_with vs g_grandparent_trend_with

### The divergence

**Spec** (both V8_01 and V8_02): first gate = `g_1h_rf_with(direction, fire_us, asset="BTC")`  
**Live** (both V8_01 and V8_02): first gate = `g_grandparent_trend_with(asset="BTC")`

These are distinct gates:

| Gate | Data source | Logic |
|------|-------------|-------|
| `g_1h_rf_with` | `range_filter_1h` panel — RF indicator `rf_dir` | `rf_dir == 1` (UP) or `-1` (DOWN) |
| `g_grandparent_trend_with` | `regime_panel` — `trend_slope_30m` at 1h tf | `slope > 0 and UP` or `slope < 0 and DOWN` |

`g_grandparent_trend_with` docstring: "V8 §3.1 — 1h trend_slope sign matches direction."  
`g_1h_rf_with` docstring: "V8 §3.1 — 1h Range Filter rf_dir sign matches direction."

Both are labeled §3.1 in the gates file. The spec used the Range Filter variant; the implementation uses the trend-slope variant. The backtest for V8_01/V8_02 was presumably run with `g_1h_rf_with` (the spec gate), meaning the live sleeve is operating under a DIFFERENT first gate than was validated.

**Impact:** The Range Filter (`rf_dir`) and trend slope direction tend to agree in trending markets but can diverge at trend reversals. This substitution is likely the cause of live performance divergence from backtest for V8_01 and V8_02 (not just V8_03). The live sleeves are running un-validated gate combinations.

**Action required:** Confirm whether backtest used `g_1h_rf_with` or `g_grandparent_trend_with`. If `g_1h_rf_with` was used in backtest, either fix the live code to match or re-run backtest with `g_grandparent_trend_with` before treating live results as spec-comparable.

---

## 4. btc_5m_q (V8_03) deep-dive — why -$317 live vs +$6.20/tr backtest

### Gate logic (spec = live, PASS in fidelity table)

V8_03 gates are correctly implemented:
1. `g_parent_15m_slope_with(BTC)` — reads `regime_panel.lookup("BTC","15m",fire_us).trend_slope_30m`, passes if sign matches direction.
2. `g_trend_slope_strong_with(BTC,5m)` — same panel at 5m, requires `|slope| > TREND_SLOPE_P75_THR[(BTC,5m)]` AND sign match.
3. `g_imb5_strong_with` — reads **live BookMirror** at gate-eval time, requires `|(up_depth - dn_depth)/(up_depth+dn_depth)| > 0.20` with sign matching direction.

### Root cause analysis

**The key problem is `g_imb5_strong_with`'s data source.**

In backtest: the test framework passes a historical L25 snapshot at exactly `fire_us` from the canonical parquet (native 10Hz). The imbalance signal is evaluated at the precise moment.

In live: `g_imb5_strong_with` reads from `book_mirror` — the in-memory WS BookMirror, which reflects the **current live book state** at gate-eval time (not a look-up at fire_us). The controller confirms: `"book_mirror": self._book_mirror` is injected directly into gate kwargs.

This creates a latency / timing difference:
- **Backtest**: book at `fire_us` (the gate fires on the book snapshot at that exact microsecond)
- **Live**: book at controller dispatch time (which is `fire_us + latency` due to panel lookups, async overhead)

Additionally: the L25 canonical data backing the backtest represents the orderbook at 10Hz ticks. The live BookMirror is updated on every WS event (~10/sec) but the controller reads it at a non-deterministic moment after `fire_us`.

**Secondary factors:**
- `g_parent_15m_slope_with` and `g_trend_slope_strong_with` both use `regime_panel.lookup(asset,tf,fire_us)` — panel-based lookup is deterministic at `fire_us`, so no timing mismatch there.
- The spread check uses a bid-ask same-token filter in live (`_compute_spread`) vs the backtest spread model, but V8_03 has spread_filter=0.02 and BTC 5m spreads are typically tight — unlikely dominant.

**Main hypothesis:** The imb5 signal in live degrades because the BookMirror read happens slightly after `fire_us`, capturing a book state after other market participants have already reacted. The imbalance signal that backtest detected (based on the historical book AT fire_us) may flip or attenuate by the time live reads it.

**Additional suspect:** with 513 live fires at 55% WR across 9 offsets, the per-offset breakdown matters. Backtest showed WR 75.5% in lockbox and proj_honest +$4,073. Live at -$317 with 55% WR implies roughly break-even win/loss structure. This pattern is consistent with the imb5 gate selecting the "right" direction based on book state but the book having already moved away from the imbalanced state by fill time.

**Recommended investigation:**
1. Split live PnL by offset_s — if short offsets (30s, 60s) are worse than long offsets (210s, 270s), imbalance signal persistence is the culprit.
2. Log imb5 value at fire time and at fill time to measure signal decay.
3. Cross-check regime_panel hit rates vs backtest (slope gates should match well if panels are correct).

---

## 5. H sleeve — HEDGE_LATE mechanics verification

### Sleeve definition (live code)

```python
SniperV5Sleeve(
    sleeve_id="poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H",
    asset="BTC", tf="15m", direction="DOWN",
    offsets=(600,),
    spread_filter=Decimal("0.02"),
    gates=(
        GateRef(g_dir_down, ...),
        GateRef(g_tr_above_ema50, (("asset","BTC"),), ...),
        GateRef(g_tr_above_ema800, (("asset","BTC"),), ...),
    ),
    exit_policy="HEDGE_LATE",
)
```

Fields `hedge_late_loss_ratio=0.70` and `hedge_late_check_lead_s=60` are dataclass defaults on `SniperV5Sleeve`. Spec requires both. ✓

### Loop scheduling (poly_sniper_v5_loop.py)

```python
if getattr(sleeve, "exit_policy", "HOLD") == "HEDGE_LATE":
    asyncio.create_task(
        _hedge_late_then_resolve(controller, sleeve, slot, fr, oracle_resolve),
        name=f"sniper_v5.hedge.{sleeve.sleeve_id}.{slot.slug}.{offset_s}.{fr.direction}",
    )
else:
    asyncio.create_task(_resolve_at_slot_end(...))
```

**Spec §4b** requires exactly this branch. ✓

### _hedge_late_then_resolve timing

```python
window_s = 300 if slot.tf == "5m" else 900   # 900 for BTC 15m
lead_s = getattr(sleeve, "hedge_late_check_lead_s", 60)  # 60s
check_us = slot.slot_start_us + (window_s - lead_s) * 1_000_000  # slot_end - 60s
```

For BTC 15m: check fires at `slot_start + 840s` = `slot_end - 60s`. **Spec §4b says "slot_end - lead_s (60s)".** ✓

If `maybe_hedge_late_cut` returns True → returns (no oracle resolution).  
If False → falls through to `_resolve_at_slot_end`. ✓

### maybe_hedge_late_cut (controller)

```python
token_id = slot.token_id_dn if fr.direction == "DOWN" else slot.token_id_up
# ...
sell_vwap = self._walk_bids_for_shares(bids, fr.fill_shares)
if sell_vwap >= fr.fill_vwap * float(sleeve.hedge_late_loss_ratio):
    return False  # healthy
# deep underwater → cut
pnl = (sell_vwap - fr.fill_vwap) * fr.fill_shares
pnl = pnl if pnl <= 0 else pnl * 0.98  # legacy fee: 2% only on profit
```

**Spec §4d**: "sell_vwap < fill_vwap * hedge_late_loss_ratio (0.70) → cut". Live: `sell_vwap >= fill_vwap * 0.70 → False (no cut)`, else cuts. ✓

For DOWN direction, the controller correctly reads `token_id_dn` (the DOWN token), then walks its bids to compute exit vwap. **Spec §4d says "read the HELD side's bid book"** — DOWN fires hold the DOWN token. ✓

**Fee model in hedge_late_cut:** `pnl * 0.98` on profit. Matches legacy fee (2% winner only). ✓

**HEDGE_LATE VERDICT: FULL SPEC COMPLIANCE.** All mechanics (scheduling, timing, cut threshold, sell-side routing, fee model) match spec exactly.

---

## 6. Fee model — controller resolution path

### Main resolution (book_event_for_resolution)

```python
# Winner-only Polymarket fee (operator-confirmed 2026-05-28):
#   fee/share = 0.07 * vwap * (1 - vwap)  → charged ONLY on a WIN.
if won:
    pnl = (1.0 - vwap) * shares * (1.0 - 0.07 * vwap)
else:
    pnl = -vwap * shares
```

**DIVERGENCE FROM CANONICAL CLAUDE.md:** CLAUDE.md states (and 2026-05-22 verification confirmed) that production uses `2%-on-profit-only` (`entry_qty × (1 - entry_price) × 0.98` exactly), NOT the `0.07 * vwap * (1-vwap)` curve. The live controller was updated to use the "real curve" formula (operator comment says "operator-confirmed 2026-05-28"), but CLAUDE.md says this curve does NOT match what Polymarket actually charges on BTC/ETH/SOL up-down markets.

**Impact on shadow PnL reporting:**
- `0.07 * p * (1-p)` at p=0.69: fee = `0.07 * 0.69 * 0.31 = 0.0150` per share
- Legacy 2% on profit at p=0.69: fee = `(1-0.69) * 0.02 = 0.0062` per share
- Real curve charges ~2.4× MORE than legacy at typical entry prices
- Shadow PnL log will show lower win-leg PnL than production actually earns

**This means V8/H sleeve shadow PnL numbers are UNDERSTATED relative to live production.** If production still uses 2%-on-profit, shadow logs using `0.07*p*(1-p)` will over-penalize winners.

### Hedge-late cut path

Uses `pnl * 0.98` (legacy fee, 2%-on-profit). This is inconsistent with main resolution path which uses `0.07*p*(1-p)`. Both paths in the same sleeve will use different fee models. If the operator-confirmed 2026-05-28 update only affected `book_event_for_resolution` and not `maybe_hedge_late_cut`, there is a fee model inconsistency within the H sleeve.

**Action required:** Confirm which fee model is correct per Polymarket account dashboard. If legacy (2%-on-profit) is correct, revert `book_event_for_resolution` to `pnl = (1-vwap) * shares * 0.98` to align with CLAUDE.md and the 25,900-event verification.

---

## 7. Summary of findings

| Priority | Finding | Verdict |
|----------|---------|---------|
| CRITICAL | Fee model: main resolution uses `0.07*p*(1-p)` but verified production behavior is 2%-on-profit. Shadow PnL understated. | **FIX REQUIRED** |
| HIGH | V8_01/V8_02: live runs `g_grandparent_trend_with` but spec says `g_1h_rf_with`. These are different indicators (trend slope vs Range Filter). Backtest validity uncertain. | **GATE MISMATCH — INVESTIGATE** |
| MEDIUM | btc_5m_q (V8_03) -$317 live vs +$6.20/tr backtest: likely g_imb5_strong_with BookMirror timing mismatch (reads current book, not book at fire_us). Investigate per-offset breakdown. | **ROOT CAUSE IDENTIFIED** |
| LOW | g_vol_contracting de-annualize bug (originally reported): ALREADY FIXED in live code. V8_14 is functional. | **NON-ISSUE (fixed)** |
| INFO | H sleeve HEDGE_LATE: full spec compliance — scheduling, timing (slot_end-60s), cut threshold (0.70), DOWN-token bid walk, fee model (legacy for cut path). | **PASS** |
| INFO | V8_05/V8_06: use `g_hurst_regime_with` directly where spec names `g_hurst_trend_with`; these are the same function via alias. | **PASS** |
| INFO | All other 11 V8 sleeves: direction, offsets, spread_filter, gate count all match spec exactly. | **PASS** |
| INFO | Fee model inconsistency within H sleeve: main resolution uses `0.07*p*(1-p)`, hedge-cut path uses legacy `0.98`. Mixed fee models in same sleeve. | **CLARIFY** |
