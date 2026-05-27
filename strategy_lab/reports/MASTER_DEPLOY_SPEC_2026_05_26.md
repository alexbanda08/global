# Master Strategy Deploy Spec — 2026-05-26

> ⚠️ **CORRECTIONS NOTICE (Round 6 dedup)**: The combined deployable estimates
> quoted below are NAIVE SUMS that did not account for slug overlap. The
> actual realistic deployable is ~$20.5k/28d at $25 notional (~$2.67M/year
> @ $250). See `NAIVE_SUM_CORRECTIONS_2026_05_26.md` and
> `final_deploy_manifest.csv` for the authoritative numbers.
>
> Individual sleeve metrics (n, WR, $/tr per sleeve) in this report ARE
> CORRECT — only the COMBINED estimates were inflated by overlap.

**Purpose**: implementation spec for ALL backtest-validated strategies discovered
in sessions **2026-05-22/23 (handoff)** and **2026-05-25/26 (hybrid system)**.
Target implementer: TV-agent on VPS3 (`/opt/tradingvenue/backend/`).

**Format**: each strategy has a trigger pseudocode, entry mechanics, expected
metrics, walk-forward status, required features, sleeve registration, and
audit verification.

**Conventions** (per `CLAUDE.md`):
- All timestamps UTC microseconds (`*_us`)
- `ws_s = slot_start − window_s` (production controller anchor — NOT slot_start)
- F7 RSI = Wilder simple-mean (NOT exponential), anchored at `ws_s`
- Outcome from Chainlink RTDS (`outcome` column)
- L25 entry walk via `engine_v2.fill_at_book` with `spread_filter=0.02` (BTC/ETH) or `0.025` (SOL)
- Fee model: **2%-on-profit-only** (LegacyConfig) — matches production
- Hold to slot_end; NO mid-slot exits, NO SL, NO TP on shadow sleeves
- All new sleeves start `mode="paper"` until operator approves promotion
- Window for backtest metrics quoted below: Apr 30 → May 22 2026 (~28d)

---

## Table of contents

**Part A — NEW from hybrid system run (2026-05-26)**
- A.1 Tier-1 gate-stack overlay sleeves (×7) — biggest $
- A.2 Cross-asset RF confluence overlay
- A.3 Tier-3 standalone hybrid V7 cells (×5)
- A.4 Required feature panels (RF, TR) — one-time builds
- A.5 Per-fire gate column computation

**Part B — From prior handoff (2026-05-22/23)**
- B.1 S3 — HoD refresh (free win, immediate)
- B.2 S2 — Fade Extreme Momo (BTC + ETH, mag>3)
- B.3 S1.5 — Slot-anchored VWAP continuation (5m, ×10 sleeves)
- B.4 S6 — Spike-driven entry with CVD (5m, ×8 sleeves)
- B.5 S7 — VWAP continuation 15m with TA overlay (×5 sleeves)
- B.6 S5 — Z_Contra ETH Underdog (paper-only initially)
- B.7 Phase 34 fixes (sleeve #2 drop m5va, sleeve #3 add m1va, fee verification)

**Part C — Cross-cutting**
- C.1 Audit row schema (gate_decisions)
- C.2 Verification SQL templates
- C.3 Promotion checklist
- C.4 Rollback procedure

---

# PART A — NEW STRATEGIES FROM HYBRID SYSTEM RUN (2026-05-26)

## A.0 Origin — what was tested

The TradingView "Hybrid System" (Range Filter [DW] + Traders Reality Main)
was ported to Python and overlaid onto our existing per-fire datasets.
**Result**: the iconic PVSRA vector-candle signal does NOT carry edge on
binary 5m/15m windows, but the Traders Reality EMA stack + pivot levels DO,
and **cross-asset RF confluence** is a free PnL booster. See
`HYBRID_SYSTEM_FINAL_2026_05_26.md` for full investigation.

Walk-forward validation (20d train / 8d test) + bootstrap (200 shuffles)
applied to all top-50 stacks. **20/20 pass rate, p=0.000 on top 7 sleeves**.

---

## A.1 Tier-1 — Gate-stack overlay sleeves (×7)

These are NEW gate stacks that overlay on EXISTING base sleeve fire universes
(S6 spike, S15 = S1.5 5m, V15m = S7 15m). They are *additional* sleeves to
register on VPS3 alongside the current 11 shadow sleeves.

### A.1.1 `poly_updown_btc_5m_s6_hybrid_v1` ⭐ HEADLINE SLEEVE

**Backtest**: n=2,764 fires, **WR 77.8%, $/tr +$5.10, sum +$14,103/28d**, test WR 91.5%, max_DD +$1,836, max_streak 4, Sharpe 2.01, bootstrap p=0.000.

**Base fires**: S6 spike-entry universe (`s6_joined_all.parquet`). Same
trigger conditions as the original S6 sleeve `poly_updown_btc_5m_s6_*` —
re-implement the spike detection per `SPIKE_ENTRY_5M_2026_05_23.md` §3.

**Asset/TF/offset**: BTC, 5m, offset_s ∈ [60, 150] (i.e. fire 60-150s into the 5m slot).

**Gate stack** (ALL must be TRUE at fire_us; bet direction = the S6 picked direction):

```python
def passes_btc_5m_s6_hybrid_v1(ctx) -> bool:
    return (
        g_cci_with(ctx)               # cci_60s > 0 if direction='UP' else < 0
        and g_stoch_with(ctx)          # stoch_k_60s > 50 if 'UP' else < 50
        and g_rf_with(ctx)             # rf_dir == +1 if 'UP' else -1
        and g_tr_above_ema50(ctx)      # close > tr_ema_50 if 'UP' else <
        and g_ribbon_agrees(ctx)       # ribbon_color in {1,4} if 'UP' else {2,3}
    )
```

**Required features at fire_us**:
- `cci_60s` (from TA panel)
- `stoch_k_60s` (from TA panel)
- `rf_dir`, `rf_close` (from RF panel, see A.4)
- `tr_ema_50`, `close` (from TR panel + binance 1s)
- `ribbon_color` (from TA panel — already deployed)

**Entry**: L25 walk for $25 notional via `engine_v2.fill_at_book(books_idx, slug, direction, fire_us, cfg=LegacyConfig(), spread_filter=0.02)`. Hold to slot_end. Settle from chainlink.

**Sleeve registration** (engine_main.py `_SHADOW_GATED_SLEEVES_SPEC` pattern):
```python
{
    "sleeve_id": "poly_updown_btc_5m_s6_hybrid_v1",
    "asset": "BTCUSDT",
    "window_s": 300,
    "phase": "bar_close",  # S6 spike phase
    "fire_offset_range_s": (60, 150),
    "base_strategy": "s6_spike",
    "gate_stack": ["cci_with", "stoch_with", "rf_with", "tr_above_ema50", "ribbon_agrees"],
    "mode": "paper",
    "notional_usd": 25.0,
    "spread_filter": 0.02,
}
```

### A.1.2 `poly_updown_eth_5m_s6_hybrid_v1`

**Backtest**: n=3,531, WR 76.0%, $/tr +$1.57, sum +$5,553/28d, test WR 85.1%, max_DD +$2,937, Sharpe 1.51, p=0.000.

**Asset/TF/offset**: ETH, 5m, offset_s ∈ [60, 150].

**Gate stack**:
```python
def passes_eth_5m_s6_hybrid_v1(ctx) -> bool:
    return g_cci_with(ctx) and g_bb_pos_with(ctx) and g_ribbon_agrees(ctx)
```

Required features: `cci_60s`, `bb_pos_60s`, `ribbon_color`. (No RF/TR needed
on this cell — ribbon already captures the trend filter for ETH.)

### A.1.3 `poly_updown_sol_5m_s6_hybrid_v1` — HIGHEST WR

**Backtest**: n=1,503, **WR 92.9%**, $/tr +$2.20, sum +$3,307/28d, test WR n/a but bootstrap p=0.000.

**Asset/TF/offset**: SOL, 5m, offset_s ∈ [60, 150]. **`spread_filter=0.025`** for SOL.

**Gate stack**:
```python
def passes_sol_5m_s6_hybrid_v1(ctx) -> bool:
    return g_mfi_with(ctx) and g_within_dev(ctx) and g_bb_pos_with(ctx) and g_ribbon_agrees(ctx)
```

Required features: `mfi_60s`, `dev_bps_vwap` (slot-anchored VWAP deviation, from `vwap_slot_anchored` store — see B.3), `bb_pos_60s`, `ribbon_color`.

### A.1.4 `poly_updown_btc_5m_s15_hybrid_v1`

**Backtest**: n=1,365, WR 85.6%, $/tr +$3.06, sum +$4,176/28d, test WR 81.9%, p=0.000.

**Asset/TF/offset**: BTC, 5m, offset_s ∈ [150, 240] (mid-slot fires only).

**Base fires**: S1.5 slot-anchored-VWAP fires (`s15_joined_all.parquet`). See B.3.

**Gate stack**:
```python
def passes_btc_5m_s15_hybrid_v1(ctx) -> bool:
    return (
        g_tr_above_pp(ctx)            # close > today's pivot if UP, < if DOWN
        and g_ribbon_agrees(ctx)
        and g_stoch_with(ctx)
        and g_tight_ribbon(ctx)        # ribbon_compression_bps < 2
    )
```

Required features: `tr_pivot_pp` (from TR panel, daily pivot from prior-day H/L/C), `ribbon_color`, `stoch_k_60s`, `ribbon_compression_bps`.

### A.1.5 `poly_updown_eth_5m_s15_hybrid_v1`

**Backtest**: n=3,420, WR 85.1%, $/tr +$1.34, sum +$4,596/28d, test WR 82.1%, p=0.000.

**Asset/TF/offset**: ETH, 5m, offset_s ∈ [150, 240].

**Base fires**: S1.5.

**Gate stack**:
```python
def passes_eth_5m_s15_hybrid_v1(ctx) -> bool:
    return (
        g_ribbon_agrees(ctx)
        and g_tr_above_ema200(ctx)    # close > tr_ema_200 if UP, < if DOWN
        and g_stoch_with(ctx)
        and g_bb_pos_with(ctx)
        and g_cci_with(ctx)
    )
```

Required features: ribbon_color, tr_ema_200, stoch_k_60s, bb_pos_60s, cci_60s.

### A.1.6 `poly_updown_btc_15m_s7_hybrid_v1`

**Backtest**: n=816, WR 88.0%, $/tr +$2.15, sum +$1,752/28d, test WR (15m OOS limited), p=0.000.

**Asset/TF/offset**: BTC, 15m, offset_s ∈ [480, 840] (late-slot fires only).

**Base fires**: S7 = VWAP continuation 15m (`v15m_joined_all.parquet`). See B.5.

**Gate stack**:
```python
def passes_btc_15m_s7_hybrid_v1(ctx) -> bool:
    return (
        g_tr_stack_full_with(ctx)     # tr_ema_stack_score == +2 if UP, == -2 if DOWN
        and g_tr_above_ema800(ctx)
        and g_ribbon_agrees(ctx)
        and g_tight_ribbon(ctx)
        and g_stoch_with(ctx)
        and g_tr_above_ema200(ctx)
    )
```

Required features: tr_ema_stack_score (computed from tr_ema_{5,13,50,200,800}), tr_ema_800, ribbon_color, ribbon_compression_bps, stoch_k_60s, tr_ema_200.

**Note**: this is the **only S7 (15m) cell that flips from losing-baseline to positive**. Baseline S7 15m loses $-13,546 across all cells. This sleeve makes it +$1,752.

### A.1.7 `poly_updown_sol_15m_s7_hybrid_v1`

**Backtest**: n=399, WR 87.2%, $/tr +$2.66, sum +$1,062/28d, p=0.000.

**Asset/TF/offset**: SOL, 15m, offset_s ∈ [480, 840]. `spread_filter=0.025`.

**Gate stack**:
```python
def passes_sol_15m_s7_hybrid_v1(ctx) -> bool:
    return (
        g_tr_within_adr(ctx)          # 0 < adr_pos < 1 (price between adr_low and adr_high)
        and g_tr_above_pp(ctx)
        and g_ribbon_agrees(ctx)
    )
```

Required features: tr_adr_high, tr_adr_low (daily ADR — see A.4), tr_pivot_pp, ribbon_color.

### A.1.8 Tier-1 expected combined uplift

If all 7 Tier-1 sleeves are deployed:

| Sleeve | sum/28d |
|---|--:|
| btc_5m_s6_hybrid_v1 | $+14,103 |
| eth_5m_s6_hybrid_v1 | $+5,553 |
| sol_5m_s6_hybrid_v1 | $+3,307 |
| btc_5m_s15_hybrid_v1 | $+4,176 |
| eth_5m_s15_hybrid_v1 | $+4,596 |
| btc_15m_s7_hybrid_v1 | $+1,752 |
| sol_15m_s7_hybrid_v1 | $+1,062 |
| **Subtotal Tier 1** | **$+34,549** |

At $25 notional ≈ **$1,234/day**. At $250 notional ≈ **$12,340/day**.

**Sleeve overlap caveat**: BTC/ETH S6 cells use the SAME spike fires as base.
Different gate stacks → partially overlapping fires. Compute slug-overlap
before promoting to live (next steps §C.3).

---

## A.2 Tier-2 — Cross-asset RF confluence overlay

### A.2.1 `poly_updown_btc_5m_xa_down`

**Backtest**: n=2,726, WR 82.1%, $/tr +$1.64, sum +$4,463/28d.

**Mechanism**: NOT a WR booster — confluence cells have entry_vwap closer to
0.5, so the SAME 81% WR delivers 2× the $-per-trade. Best-in-class for BTC DOWN.

**Asset/TF/offset**: BTC, 5m, all S1.5 offsets [30, 300]s.

**Base fires**: S1.5 universe.

**Gate stack**:
```python
def passes_btc_5m_xa_down(ctx) -> bool:
    # Bet direction is FIXED = "DOWN" for this sleeve (asymmetric)
    if ctx.direction != "DOWN":
        return False
    # All three assets' Range Filter must agree DOWN at fire_us
    btc_rf = lookup_rf_dir("BTCUSDT", ctx.fire_us)
    eth_rf = lookup_rf_dir("ETHUSDT", ctx.fire_us)
    sol_rf = lookup_rf_dir("SOLUSDT", ctx.fire_us)
    return btc_rf == -1 and eth_rf == -1 and sol_rf == -1
```

Required features: RF panel for ALL THREE assets at fire_us (causal — use last fully-closed 1s bar).

**Implementation note**: this is a portfolio-level filter, not a per-asset
gate. Implementer needs to subscribe to all 3 binance 1s feeds and maintain
a cross-asset RF state cache. The existing `BinanceWsCollector` already
collects all three — add an in-memory `RangeFilterState` per asset.

### A.2.2 `poly_updown_btc_5m_xa_up`

**Backtest**: n=2,808, WR 82.0%, $/tr +$1.53, sum +$4,285/28d.

Mirror of A.2.1 for UP direction. Same logic with `+1` everywhere.

### A.2.3 Tier-2 as PORTFOLIO OVERLAY (preferred)

Alternative deploy: instead of standalone xa sleeves, add
`g_xa_all_with_bet` as an AND gate on EXISTING Tier-1 sleeves. Re-backtest
the combined stacks first.

Expected Tier-2 standalone uplift: ~$+8,700/28d (BTC UP + DOWN combined,
n=5,534 fires).

---

## A.3 Tier-3 — Standalone Hybrid V7 cells (×5)

**Logic**: V7 = `RF dir agrees ∧ PVSRA color agrees ∧ MFI agrees with direction`.
This is the only Hybrid System rule that produced multiple deployable cells in
standalone backtest (6/7 walk-forward pass, max corr 0.483). Smaller $/sleeve
but **clean diversification from Tier 1**.

### A.3.1 `poly_updown_btc_5m_off90_v7`

**Backtest**: n=332, WR 70.8%, $/tr +$2.70, sum +$895/22d ≈ $+1,138/28d, Sharpe 2.82.

**Asset/TF/offset**: BTC, 5m, offset_s = 90 (exact, narrow fire window).

**Trigger**:
```python
def fire_btc_5m_off90_v7(ctx) -> Optional[str]:
    # Bet direction selected by the rule, not preset
    rf = ctx.rf_dir
    pvsra = ctx.tr_pvsra  # int code: 3=climax_bull, 2=rising_bull, 0=regular, -2=rising_bear, -3=climax_bear
    mfi = ctx.mfi_60s

    if rf == +1 and pvsra in (2, 3) and mfi > 50:
        return "UP"
    if rf == -1 and pvsra in (-2, -3) and mfi < 50:
        return "DOWN"
    return None
```

Required features: rf_dir, tr_pvsra (1s — see A.4 panel), mfi_60s.

**Entry/exit**: same as other sleeves (L25 walk, $25 notional, hold to slot_end).

### A.3.2 `poly_updown_btc_5m_off150_v7`

Same V7 trigger, offset_s = 150. n=288, WR 66.7%, $/tr +$3.04, sum +$875/22d.

### A.3.3 `poly_updown_btc_5m_off60_v7`

V7 at offset_s = 60. n=297, WR 68.7%, $/tr +$2.19, sum +$651/22d.

### A.3.4 `poly_updown_sol_5m_off90_v7`

V7 on SOL at offset_s = 90. n=116, WR 73.3%, $/tr +$3.99, sum +$463/22d. `spread_filter=0.025`.

### A.3.5 `poly_updown_sol_5m_off120_v7`

V7 on SOL at offset_s = 120. n=111, **WR 75.7%**, $/tr +$2.87, sum +$319/22d.

### A.3.6 Tier-3 subtotal

~$+3,200/28d combined. Lower confidence per sleeve due to small n (111-332)
but excellent Sharpe + diversification.

---

## A.4 Feature panels — one-time builds

### A.4.1 Range Filter [DW] state (NEW)

**Code reference**: `strategy_lab/meta_classifier/compute_range_filter.py` (offline
batch builder, ~30s per asset). For production, port the algorithm to streaming.

**Algorithm** (port from Pine v4, faithful):

```python
import numba
import numpy as np

@numba.njit(cache=True)
def range_filter_streaming(closes: np.ndarray, n: int = 14, qty: float = 2.618, sn: int = 27):
    """
    Inputs:
      closes: 1d float64 array of 1s close prices (one asset, time-ordered)
      n: range period (default 14)
      qty: range multiplier (default 2.618)
      sn: smoothing period for the range (default 27; or 1 to disable)

    Returns:
      rf_close, rf_hi, rf_lo, rf_r, rf_dir (int8: +1, 0, -1), rf_dir_age (int32)
    """
    L = closes.shape[0]
    abs_diff = np.zeros(L)
    for i in range(1, L):
        abs_diff[i] = abs(closes[i] - closes[i-1])

    # AC = Cond_EMA(abs_diff, 1, n) — basic EMA
    alpha_n = 2.0 / (n + 1)
    AC = np.zeros(L)
    AC[0] = abs_diff[0]
    for i in range(1, L):
        AC[i] = AC[i-1] + alpha_n * (abs_diff[i] - AC[i-1])

    rng_unsmoothed = qty * AC

    # Smoothed range = EMA(rng_unsmoothed, sn)
    alpha_s = 2.0 / (sn + 1)
    rng_smooth = np.zeros(L)
    rng_smooth[0] = rng_unsmoothed[0]
    for i in range(1, L):
        rng_smooth[i] = rng_smooth[i-1] + alpha_s * (rng_unsmoothed[i] - rng_smooth[i-1])
    r = rng_smooth  # if sn == 1, this equals rng_unsmoothed

    # Type 1 filter (Pine default)
    rfilt = np.zeros(L)
    rfilt[0] = closes[0]
    for i in range(1, L):
        prev = rfilt[i-1]
        h = closes[i]   # movement_source = Close, so h = l = close
        l_ = closes[i]
        if h - r[i] > prev:
            rfilt[i] = h - r[i]
        elif l_ + r[i] < prev:
            rfilt[i] = l_ + r[i]
        else:
            rfilt[i] = prev

    rf_hi = rfilt + r
    rf_lo = rfilt - r

    rf_dir = np.zeros(L, dtype=np.int8)
    rf_dir[0] = 0
    last_dir = 0
    rf_dir_age = np.zeros(L, dtype=np.int32)
    for i in range(1, L):
        if rfilt[i] > rfilt[i-1]:
            last_dir = 1
            rf_dir_age[i] = 0 if rf_dir[i-1] != 1 else rf_dir_age[i-1] + 1
        elif rfilt[i] < rfilt[i-1]:
            last_dir = -1
            rf_dir_age[i] = 0 if rf_dir[i-1] != -1 else rf_dir_age[i-1] + 1
        else:
            rf_dir_age[i] = rf_dir_age[i-1] + 1
        rf_dir[i] = last_dir

    return rfilt, rf_hi, rf_lo, r, rf_dir, rf_dir_age
```

**Production deployment**:
- Subscribe to binance 1s WS feed (BTC, ETH, SOL — already collected)
- Maintain rolling RF state per asset in memory
- Update on each 1s bar close: `rf_state[asset].update(close_1s)` → returns
  `rf_dir, rf_close, rf_dir_age`
- Expose getter for controller: `rf_state[asset].snapshot(at_us)` returns the
  state at-or-before `at_us` (causal)
- Persist last-N seconds of state to recover on restart

**Parameter choice (verified 2026-05-26)**:
- Default: `n=14, qty=2.618, sn=27` (matches our backtest panel)
- Best-performing: `n=14, qty=2.618, sn=1` (no smoothing — +5.93pp wr_delta on S6 vs default +1.75pp). Net $ impact is small because S6 picker is already ~96% RF-aligned. **Use sn=27 to match backtest exactly**; sn=1 is a config-only tune that can be A/B'd later.

### A.4.2 Traders Reality features (NEW)

**Code reference**: `strategy_lab/meta_classifier/compute_traders_reality.py`,
`overlay_traders_reality.py`.

Required columns at each `fire_us` (computed on 1s binance closes, causal):

**EMAs** (use `ewm(span=N, adjust=False)` semantics — alpha = 2/(N+1)):
- `tr_ema_5`, `tr_ema_13`, `tr_ema_50`, `tr_ema_200`, `tr_ema_800`
- `tr_ema_stack_score` (int -2..+2):
  ```python
  def ema_stack_score(e5, e13, e50, e200, e800):
      pairs = [
          (e5 > e13, e5 < e13),
          (e13 > e50, e13 < e50),
          (e50 > e200, e50 < e200),
          (e200 > e800, e200 < e800),
      ]
      bull_run = 0  # consecutive bull pairs from start
      for b, _ in pairs:
          if b: bull_run += 1
          else: break
      bear_run = 0
      for _, br in pairs:
          if br: bear_run += 1
          else: break
      return min(bull_run - bear_run, 2) if bull_run >= bear_run else max(bull_run - bear_run, -2)
  ```
  Score == +2 means full bull stack (5>13>50>200>800); -2 means full bear.

**50-EMA cloud**:
- `tr_ema_50_cloud_size = stdev(close, 100) / 4` (rolling stdev over last 100s)
- `tr_ema_50_cloud_upper = tr_ema_50 + cloud_size`
- `tr_ema_50_cloud_lower = tr_ema_50 - cloud_size`
- `tr_cloud_pos = (close - cloud_lower) / (cloud_upper - cloud_lower)` (can exceed [0,1])

**PVSRA (1s — for V7 only)** — see `compute_traders_reality.py` for exact thresholds:
- `tr_pvsra` int code: 3=climax_bull, 2=rising_bull, 0=regular, -2=rising_bear, -3=climax_bear, 1=absorption (rare)
- Thresholds: `climax = vol >= 2.0 * sma(vol, 10) OR (spread*vol) >= rolling_max(spread*vol, 10)`; `rising = vol >= 1.5 * sma(vol, 10)`

**⚠️ PVSRA caveat**: 5m PVSRA is anti-edge (-37pp WR standalone, see
`RF_PARAM_SWEEP_PVSRA5M_2026_05_25.md`). Use 1s PVSRA only and only as part
of the V7 stack — never as standalone direction signal or veto gate.

**Daily pivot (from prior-day H/L/C, binance daily candles)**:
- `tr_dayHigh`, `tr_dayLow`, `tr_dayClose` (prior complete UTC day)
- `tr_pivot_pp = (tr_dayHigh + tr_dayLow + tr_dayClose) / 3`
- `tr_pivot_r1 = 2*pp - dayLow`, `tr_pivot_s1 = 2*pp - dayHigh`
- (R2/R3/S2/S3 + M0-M5 also computed, but not used by Tier-1 sleeves)

**ADR (14 prior complete days)**:
- `tr_adr = mean(dayHigh - dayLow) over last 14 complete days`
- `tr_adr_high = today_dayOpen + tr_adr` (Daily Open variant — static within day)
- `tr_adr_low = today_dayOpen - tr_adr`
- `tr_adr_pos = (close - tr_adr_low) / (tr_adr_high - tr_adr_low)` (can exceed [0,1])

**Sessions** (UTC, no DST):
- `tr_in_london` = hour ∈ [7, 16]
- `tr_in_ny` = hour ∈ [13, 21]
- `tr_in_tokyo` = hour ∈ [0, 6]
- `tr_eu_brinks` = hour == 7 (08-09 UTC)
- `tr_us_brinks` = hour ∈ [13, 14] (14-15 UTC)

**Production deployment**:
- EMAs computed in `MaRibbonStore` (already exists on VPS3 for the ribbon)
  — extend to compute the 5/13/50/200/800 ladder (NOT just 5-100 like ribbon).
- Daily pivots / ADR computed once per UTC midnight from binance daily klines.
  Cache in a `DailyAnchorStore` keyed on (asset, date).
- Session flags: trivial — derive from `datetime.utcnow().hour`.
- PVSRA: maintain rolling 10-second window of (volume, spread*volume). Update
  on each 1s WS bar close.

### A.4.3 Cross-asset RF state cache (for A.2)

Maintain `Dict[asset, RangeFilterState]` for {BTC, ETH, SOL}. On each WS 1s
bar from any asset, update its RF state. Controller queries
`xa_state.snapshot(at_us)` → `{"BTC": +1, "ETH": +1, "SOL": -1}`.

Persist to disk (e.g., one-line append to a `xa_rf_state.jsonl`) for restart
recovery — RF is sticky on direction, so last-known state is usable.

---

## A.5 Per-fire gate column computation

All Tier-1 gate functions take a `BarContext` with these fields populated at
`fire_us`. Reference implementation in
`strategy_lab/meta_classifier/hybrid_join_and_gates.py`.

```python
def g_rf_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.rf_dir == +1
    return ctx.rf_dir == -1

def g_rf_fresh(ctx) -> bool:
    return g_rf_with(ctx) and ctx.rf_dir_age <= 30  # flipped within last 30s

def g_rf_aged(ctx) -> bool:
    return g_rf_with(ctx) and ctx.rf_dir_age > 60   # established trend

def g_ribbon_agrees(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.ribbon_color in (1, 4)   # lime, green
    return ctx.ribbon_color in (2, 3)       # maroon, red

def g_bb_pos_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.bb_pos_60s > 0.5
    return ctx.bb_pos_60s < 0.5

def g_stoch_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.stoch_k_60s > 50
    return ctx.stoch_k_60s < 50

def g_mfi_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.mfi_60s > 50
    return ctx.mfi_60s < 50

def g_cci_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.cci_60s > 0
    return ctx.cci_60s < 0

def g_within_dev(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.dev_bps_vwap > 5
    return ctx.dev_bps_vwap < -5

def g_tr_above_ema50(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.close > ctx.tr_ema_50
    return ctx.close < ctx.tr_ema_50

def g_tr_above_ema200(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.close > ctx.tr_ema_200
    return ctx.close < ctx.tr_ema_200

def g_tr_above_ema800(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.close > ctx.tr_ema_800
    return ctx.close < ctx.tr_ema_800

def g_tr_above_pp(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.close > ctx.tr_pivot_pp
    return ctx.close < ctx.tr_pivot_pp

def g_tr_above_cloud(ctx) -> bool:
    # tr_cloud_pos > 1 → close above upper cloud (bull); < 0 → below lower (bear)
    if ctx.direction == "UP":
        return ctx.tr_cloud_pos > 1.0
    return ctx.tr_cloud_pos < 0.0

def g_tr_stack_full_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.tr_ema_stack_score == +2
    return ctx.tr_ema_stack_score == -2

def g_tr_stack_with(ctx) -> bool:
    if ctx.direction == "UP":
        return ctx.tr_ema_stack_score >= +1
    return ctx.tr_ema_stack_score <= -1

def g_tr_within_adr(ctx) -> bool:
    return 0.0 < ctx.tr_adr_pos < 1.0

def g_tr_in_active_session(ctx) -> bool:
    return ctx.tr_in_london or ctx.tr_in_ny or ctx.tr_eu_brinks or ctx.tr_us_brinks

def g_tight_ribbon(ctx) -> bool:
    return ctx.ribbon_compression_bps < 2.0

def g_markov_with(ctx) -> bool:
    # M1V regime: 0=BEAR, 1=NEUTRAL, 2=BULL (per markov_filter spec)
    if ctx.direction == "UP":
        return ctx.markov_m1v_va == 2
    return ctx.markov_m1v_va == 0
```

**Causal anchor for ALL features**: lookup uses the LAST 1s bar with
`ts_us <= fire_us - 1_000_000` (i.e., one full second before fire_us, so the
bar is closed). For daily aggregates (pivot, ADR): use prior complete UTC day.

---

# PART B — STRATEGIES FROM PRIOR HANDOFF (2026-05-22/23)

## B.1 S3 — HoD refresh ⭐ FREE WIN

**Status**: NOT YET DEPLOYED. Operator review pending per Phase 34 spec §6.

**What**: the shipped `HOD_TOP8_BY_CELL` constant in `backend/app/engine/gates.py`
was derived from `at_ts.dt.hour` (resolution time hour). The spec mandates
**fire-time hour** (`fire_us` UTC hour). Re-deriving with the correct anchor
flips ALL 18 cells.

**Effect on existing 11-sleeve ensemble (refresh-only, no other changes)**:

| Metric | Current shipped | Refreshed |
|---|--:|--:|
| Ensemble PnL 28d @ $25 | $2,949 | **$15,900 (5.4×)** |
| Positive sleeves | 7/11 | 11/11 |
| Sleeves flipping +ve | — | sleeve #5 (sniper btc_5m), #10 (momo_v2 sol_15m) |

**Files**:
- Refreshed constants: `strategy_lab/markov_filter/_results/hod_refresh/2026_05_22/new_hod_top8.json`
- Recompute script: `strategy_lab/markov_filter/_recompute_hod_top8.py`
- Comparison: `SHADOW_11_SLEEVES_V2_2026_05_22.md`
- Fix spec: `TV_AGENT_PHASE34_FIXES_2026_05_22.md` §2

**Implementation**: copy JSON into `gates.py::HOD_TOP8_BY_CELL`, restart all
poly_updown sleeves. 5min operator edit. Per spec §2.5, update the 2 existing
unit tests in `test_gates.py` that assert specific HoD values.

**Risk**: low. Same gate logic, different lookup table. Rollback = revert
constants.

---

## B.2 S2 — Fade Extreme Momo (BTC + ETH only, mag>3) ⭐ FREE PATCH

**Status**: 4-line strategy patch, NOT YET DEPLOYED.

**Trigger** (modify `momo.py` strategy on VPS3):

```python
# Inside momo strategy fire logic, AFTER computing ret_2m and base_direction:
mag_ratio = abs(ret_2m) / momo_threshold
base_direction = "UP" if ret_2m > 0 else "DOWN"
asset = ctx.asset  # BTCUSDT, ETHUSDT, SOLUSDT

# NEW: fade extreme moves on BTC + ETH (NOT SOL)
if mag_ratio > 3.0 and asset in ("BTCUSDT", "ETHUSDT"):
    direction = "DOWN" if base_direction == "UP" else "UP"   # FLIP
else:
    direction = base_direction
```

**Expected per-cell metrics**:

| Asset | Gate | n | fade WR | $/tr | sum 28d |
|---|---|--:|--:|--:|--:|
| ETH | mag>3.0 (no extra gate) | 72 | **70.8%** | +$8.24 | +$593 |
| BTC | mag>3.0 (no extra gate) | 92 | 67.4% | +$7.30 | +$671 |
| Pooled BTC+ETH+SOL | mag>3.0 | 230 | 63.9% | +$5.29 | $+1,216 |
| BTC | mag>3.0 + F7-contra | 33 | 69.7% | +$9.26 | +$306 |

**SOL excluded — 0 deployable configs at mag>3.0** (SOL high-mag signals are
NOT exhausted; random WR).

**Tier impact** (pooled BTC+ETH):
- mag_ratio (1.5, 2.0]: fade WR = 49.3% → don't fade
- (2.0, 2.5]: 44.3% → don't fade
- (3.0, 5.0]: **63.3%** → fade
- (5.0, 100]: **66.7%** → fade

**Threshold**: hard cutoff at mag_ratio > 3.0. (Could sweep 2.5 / 3.5 / 4.0 in
A/B but 3.0 is the validated default.)

**Files**: `FADE_MOMO_5M_2026_05_23.md`, `fade_momo_5m.py`.

**Risk**: low. Asymmetric flip only on extreme moves. Affects ~230 fires/28d
of the existing momo sleeves. If patch is bad, ensemble PnL drops ~$1,200.

---

## B.3 S1.5 — Slot-anchored VWAP continuation (5m, ×10 sleeves)

**Status**: NEW sleeves, full spec in `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`.

**Trigger**: at fixed `fire_offset_s` into each 5m slot:
- Compute `binance_vwap_since_slot_open` = volume-weighted average price of all
  1s bars from `slot_start` to `fire_us`.
- `dev_bps = (close - vwap) / vwap * 1e4`
- If `dev_bps` > threshold → bet UP (continuation of upward deviation)
- If `dev_bps` < -threshold → bet DOWN

**S1.5 vs S1**: S1 used 15m-anchored VWAP. **S1.5 uses SLOT-anchored VWAP**
(anchored at slot_start). S1.5 substantially outperforms S1 because slot_start
is where the strike was set — VWAP from that moment shows the move relative to
the strike's reference window.

**Top 10 deployable cells** (28d @ $25 notional, ribbon_agrees gate on all):

| Sleeve ID | Market | offset_s | dev_threshold_bps | n | WR | $/tr | sum/28d |
|---|---|--:|--:|--:|--:|--:|--:|
| poly_updown_btc_5m_s15_210 | BTC 5m | 210 | 5-10 | 529 | 87.3% | +$2.99 | $+1,555 |
| poly_updown_eth_5m_s15_210 | ETH 5m | 210 | 10-15 | 138 | 87.0% | +$10.92 | $+1,524 |
| poly_updown_btc_5m_s15_240 | BTC 5m | 240 | 3-5 | 810 | 81.7% | +$1.09 | $+1,293 |
| poly_updown_eth_5m_s15_240 | ETH 5m | 240 | 5-10 | 714 | 85.3% | +$1.13 | $+1,083 |
| poly_updown_sol_5m_s15_270 | SOL 5m | 270 | 5-10 | 570 | 87.2% | +$1.14 | $+1,014 |
| poly_updown_btc_5m_s15_150 | BTC 5m | 150 | 3-5 | 770 | 81.0% | +$0.84 | $+832 |
| poly_updown_eth_5m_s15_150 | ETH 5m | 150 | 5-10 | 707 | 84.3% | +$1.25 | $+799 |
| poly_updown_btc_5m_s15_120 | BTC 5m | 120 | <5 | (per spec) | — | — | $+766 |
| poly_updown_eth_5m_s15_150b | ETH 5m | 150 | <5 | (per spec) | — | — | $+725 |
| poly_updown_btc_5m_s15_210b | BTC 5m | 210 | <5 | (per spec) | — | — | $+723 |

**Subtotal S1.5 5m**: ~$+10,300/28d.

**Best-Sharpe (Tier-3 ultra-low-DD picks)** — full ribbon + m1v stack:
- SOL 30s 5-10bps: Sharpe **13.32**, n=112, WR 81.2%, sum $+542, DD only -$75
- ETH 150 5-10bps: Sharpe **8.26**, n=707, WR 84.3%, sum +$883

**Files**:
- `vwap_slot_anchored_5m.py` (backtest engine)
- `vwap_slot_anchored_v2_gated.py` (+ gates)
- `vwap_drawdown_livemimic.py` (DD + Sharpe + OOS stress test)
- **Full deploy spec**: `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` (17 sections, complete code, tests, verification SQL)

**Production**: implement `Vwap15mStore` (lightweight rolling VWAP since
slot_start). Subscribe to 1s binance feed. On each tick, accumulate volume*close
and volume sum since slot_start. At fire_us, compute current VWAP and dev_bps.

---

## B.4 S6 — Spike-driven entry (5m, ×8 sleeves)

**Status**: NEW sleeves, requires 1s binance WS feed (already collected).

**Trigger**: in the (slot_start, fire_us) window, look for raw binance
breakouts confirmed by CVD direction:

```python
def s6_check_fire(ctx) -> Optional[str]:
    # Definitions D1, D2, D4 from SPIKE_ENTRY_5M_2026_05_23.md
    ret_5s = compute_log_return(ctx.binance_1s, lookback_s=5)
    cvd_5s = compute_cvd(ctx.binance_1s, lookback_s=5)  # cumulative taker_buy - taker_sell

    # D1: 5s spike + CVD confirmation
    if abs(ret_5s) > 2.5e-4 and np.sign(cvd_5s) == np.sign(ret_5s):
        return "UP" if ret_5s > 0 else "DOWN"

    # D4: 30s run continuation
    ret_30s = compute_log_return(ctx.binance_1s, lookback_s=30)
    if ret_30s > 5e-4 and ret_5s > 0:
        return "UP"
    if ret_30s < -5e-4 and ret_5s < 0:
        return "DOWN"

    return None
```

**Top 8 deployable S6 sleeves** (with ribbon_agrees gate):

| Sleeve ID | Market | offset_s | Def | n | WR | $/tr | sum/28d | Sharpe |
|---|---|--:|---|--:|--:|--:|--:|--:|
| poly_updown_btc_5m_s6_120_d1 | BTC 5m | 120 | D1 T1 | 146 | 70.5% | $+6.57 | $+960 | 8.70 |
| poly_updown_btc_5m_s6_45_d1 | BTC 5m | 45 | D1 T1 | 165 | 66.1% | $+5.42 | $+895 | 8.01 |
| poly_updown_btc_5m_s6_30_d1 | BTC 5m | 30 | D1 T1 | 149 | 67.1% | $+5.15 | $+768 | **11.07** |
| poly_updown_btc_5m_s6_60_d4 | BTC 5m | 60 | D4 T1 | 97 | **83.5%** | $+4.88 | $+474 | **15.10** ⭐ highest Sharpe overall |
| poly_updown_sol_5m_s6_30_d2 | SOL 5m | 30 | D2 T1 | 130 | 78.5% | $+3.55 | $+461 | 10.26 |
| poly_updown_eth_5m_s6_60_d1 | ETH 5m | 60 | D1 T1 | 182 | 67.0% | $+2.52 | $+459 | 6.40 |
| poly_updown_eth_5m_s6_120_d4 | ETH 5m | 120 | D4 T1 | 98 | 80.6% | $+4.61 | $+451 | 8.17 |
| poly_updown_btc_5m_s6_90_d1 | BTC 5m | 90 | D1 T1 | 121 | 61.2% | $+4.03 | $+487 | — |

**Subtotal S6**: ~$+4,819/28d (excluded by `TIER 1` overlay since the
hybrid_v1 gate stack supersedes — see A.1.1).

**Entry advantage**: spike entries at +30-120s have CHEAP vwap (0.55-0.74)
because PM book hasn't priced in the move yet.

**Files**:
- `spike_entry_5m.py` (backtest)
- `SPIKE_ENTRY_5M_2026_05_23.md` (full backtest)

**Production**: need to subscribe to 1s binance WS feed (already done). New
`SpikeDetector` class tracks rolling 5s/15s/30s log returns + CVD from
`taker_buy_base / total_base`. Fire at first matching definition.

---

## B.5 S7 — VWAP continuation 15m (×5 sleeves)

**Status**: NEW sleeves, same VWAP logic as S1.5 but on 15m slots.

**Trigger**: identical to S1.5 (slot-anchored VWAP deviation), with
`window_s=900` (15m), fire_offset_s ∈ [60, 840].

**Top 5 deployable S7 sleeves** (with TA overlay — 2.3× over original S7):

| Sleeve ID | Market | offset_s | dev_threshold | Gate stack | n | WR | $/tr | sum/28d |
|---|---|--:|--:|---|--:|--:|--:|--:|
| poly_updown_btc_15m_s7_840_triple | BTC 15m | 840 | 5-10 | triple confluence (ribbon+stoch+cci) | 111 | 75.7% | $+7.60 | $+843 |
| poly_updown_btc_15m_s7_840_ribbon | BTC 15m | 840 | 5-10 | ribbon_agrees | 141 | 76.6% | $+5.01 | $+707 |
| poly_updown_sol_15m_s7_240_ribbon | SOL 15m | 240 | 10-15 | ribbon_agrees | 80 | 86.2% | $+3.65 | $+292 |
| poly_updown_btc_15m_s7_600_triple | BTC 15m | 600 | 5-10 | triple confluence | 205 | **90.2%** | $+1.42 | $+292 |
| poly_updown_eth_15m_s7_720_ribbon | ETH 15m | 720 | 15-20 | ribbon_agrees | 30 | 83.3% | $+9.10 | $+273 |

**Subtotal S7**: ~$+2,407/28d.

**Ultra-low-DD 15m layer** (ribbon + m1v stack):
- BTC 480 10-15bps + ribbon+m1v: **WR 100%, 0 losses, n=35** ⭐
- BTC 600 5-10bps + ribbon+m1v: WR 96.1%, n=152, sum +$264
- SOL 840 5-10bps + ribbon+m1v: WR 97.3%, n=74

**Files**:
- `vwap_continuation_15m.py` (backtest)
- `VWAP_CONTINUATION_15M_2026_05_23.md`, `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md`

**Production**: extend `Vwap15mStore` from B.3 to also maintain a 15m-slot
rolling VWAP. Re-use 1s binance feed.

---

## B.6 S5 — Z_Contra ETH Underdog (paper-only initially)

**Status**: NEW, sub-60% WR but PnL-positive. **Half-notional sizing recommended.**

**Trigger**: port of `mlmodelpoly`'s `z_contra_fav_dip_hedge` to 5m markets.

Buy the UNDERDOG (the side with lower book price) when:
1. PM "favorite" (the side with higher book price) is DIPPING (book mid moved
   adverse to favorite over last 30s by ≥ Z*sigma)
2. Binance disagrees with PM favorite direction (binance ret in the underdog's
   favor)

```python
def s5_check_fire(ctx) -> Optional[str]:
    book_mid_up, book_mid_dn = ctx.book_mid_up, ctx.book_mid_dn
    favorite = "UP" if book_mid_up > book_mid_dn else "DOWN"
    underdog = "DOWN" if favorite == "UP" else "UP"

    fav_mid_30s_ago = ctx.book_history.get_mid(favorite, ctx.fire_us - 30_000_000)
    fav_dip = (book_mid_up if favorite == "UP" else book_mid_dn) - fav_mid_30s_ago
    fav_dip_z = fav_dip / ctx.book_sigma_30s

    binance_ret = ctx.binance_ret_30s
    if favorite == "UP":
        binance_disagrees = binance_ret < 0
    else:
        binance_disagrees = binance_ret > 0

    if fav_dip_z < -1.0 and binance_disagrees:  # favorite dipping, binance bearish for favorite
        return underdog
    return None
```

**Best config**: ETH 30s offset, 100bps dip threshold, Z=1.0 → n=183, WR 55.2%,
**$/tr +$3.24, sum +$594/28d**.

Sub-60% WR but profitable because the UNDERDOG token is CHEAP (entry vwap
≈ 0.30) — each win pays 2x+ per share.

**Files**: `z_contra_5m.py`, `Z_CONTRA_5M_2026_05_23.md`.

**Production caveats**: needs `book_history` (rolling 30s book mid per slug).
Higher operational complexity than other sleeves.

---

## B.7 Phase 34 fixes (sleeve #2 + #3 + tests)

**Status**: spec ready at `TV_AGENT_PHASE34_FIXES_2026_05_22.md`. NOT YET APPLIED.

### B.7.1 Drop `m5va` from sleeve #2 (`poly_updown_eth_15m_sniper_hod_m5va`)

**Reason**: Markov M5VA gate is BROKEN — `markov_regime_w20_5m_va=None` is
hardcoded in `build_bar_context_t_plus_120/60` so 100% of fires fail closed
with `gate_markov_skip` (regime=-1).

**Fix**: 1-line config change in `engine_main.py::_SHADOW_GATED_SLEEVES_SPEC`:
```python
# OLD:
"gate_stack": ["hod", "m5va"],
# NEW:
"gate_stack": ["hod"],
```

**Expected impact**: +$745/28d (sleeve goes from broken to working).

### B.7.2 Add `m1va` to sleeve #3 (`poly_updown_btc_15m_momo_hod`)

**Reason**: M1V regime gate works on momo sleeves (vs sniper). Adding it
tightens WR from 78.4% → 90.2% on a smaller subset.

**Fix** per spec §4:
1. Extend `BarContext` to include `markov_regime_w20_1m_va`
2. Populate aux in `build_bar_context_t_plus_120` from a `MarkovStore` cache
3. Add `m1va` to sleeve #3's gate_stack
4. Add 3 new test files (gates, markov labeller, integration)

**Expected impact**: +$1,265/28d on sleeve #3.

### B.7.3 Add missing tests

Per spec §5, three new tests:
- `test_gates.py::test_markov_passes_warmup_fail_closed`
- `test_markov.py::test_label_regime_vol_adaptive_correct_labels`
- `test_polymarket_updown_gates.py::test_m5va_reachable_with_real_bar_context`

These would have caught Bug #1 pre-deploy.

---

# PART C — CROSS-CUTTING

## C.1 Audit row schema

Every fire should emit a `trading.events` row with `kind="poly_updown_fire"` and
this data payload (extend existing schema):

```json
{
  "sleeve_id": "poly_updown_btc_5m_s6_hybrid_v1",
  "asset": "BTCUSDT",
  "slug": "btc-up-or-down-...",
  "ws_s": 1747834800,
  "fire_us": 1747834860000000,
  "phase": "bar_close",
  "fire_offset_s": 60,
  "direction": "UP",
  "fired": true,
  "gate_decisions": {
    "cci_with": {"pass": true, "value": 47.3},
    "stoch_with": {"pass": true, "value": 67.1},
    "rf_with": {"pass": true, "rf_dir": 1, "rf_dir_age": 47},
    "tr_above_ema50": {"pass": true, "close": 65324.5, "ema50": 65318.2},
    "ribbon_agrees": {"pass": true, "ribbon_color": 4}
  },
  "feature_snapshot": {
    "ribbon_color": 4,
    "ribbon_compression_bps": 1.2,
    "ribbon_lead_slope_bps": 0.43,
    "ribbon_alignment_pct": 84.3,
    "stoch_k_60s": 67.1,
    "stoch_d_60s": 62.4,
    "bb_pos_60s": 0.62,
    "bb_width_60s": 0.0014,
    "mfi_60s": 58.2,
    "cci_60s": 47.3,
    "rf_dir": 1,
    "rf_dir_age": 47,
    "rf_close": 65322.1,
    "rf_dist_bps": 0.37,
    "tr_ema_5": 65325.4,
    "tr_ema_13": 65324.1,
    "tr_ema_50": 65318.2,
    "tr_ema_200": 65304.8,
    "tr_ema_800": 65240.5,
    "tr_ema_stack_score": 2,
    "tr_pvsra": 2,
    "tr_pivot_pp": 65280.0,
    "tr_adr_pos": 0.42,
    "dev_bps_vwap": 7.8,
    "markov_m1v_va": 2
  },
  "entry": {
    "vwap": 0.63,
    "qty": 39.68,
    "notional_usd": 25.0,
    "spread_filter": 0.02,
    "books_source": "ws_mirror"
  },
  "audit_book_event_count_60s": 312
}
```

This payload makes every fire reproducible offline against the backtest.

---

## C.2 Verification SQL (run at deploy + 1h, 24h, 7d)

### C.2.1 Deploy + 1h — all sleeves alive

```sql
SELECT sleeve_id, COUNT(*) FILTER (WHERE kind='poly_updown_fire') AS fires,
       COUNT(*) FILTER (WHERE kind='poly_updown_resolution') AS resolutions
FROM trading.events
WHERE at > NOW() - INTERVAL '1 hour'
  AND sleeve_id LIKE 'poly_updown_%_hybrid_v1'
GROUP BY 1
ORDER BY 1;
```

Expected: ≥1 fire per cell (S6 cells fire 5-10×/hour, S15 cells ~1-2×/hour).

### C.2.2 Deploy + 4h — gates working

```sql
SELECT sleeve_id,
       jsonb_array_length(jsonb_path_query_array(data, '$.gate_decisions.*.pass'))
         AS gate_count,
       SUM((data->'gate_decisions'->'rf_with'->>'pass')::boolean::int) AS rf_pass,
       SUM((data->'gate_decisions'->'ribbon_agrees'->>'pass')::boolean::int) AS rib_pass,
       SUM((data->'gate_decisions'->'cci_with'->>'pass')::boolean::int) AS cci_pass
FROM trading.events
WHERE at > NOW() - INTERVAL '4 hours'
  AND sleeve_id = 'poly_updown_btc_5m_s6_hybrid_v1'
  AND kind = 'poly_updown_fire'
GROUP BY 1, 2;
```

Expected: `gate_count = 5` (BTC S6 hybrid v1 has 5 gates), each pass count > 0.

### C.2.3 Deploy + 24h — first WR sample

```sql
WITH r AS (
  SELECT sleeve_id,
         (data->>'pnl_usd')::numeric AS pnl,
         (data->>'won')::boolean AS won
  FROM trading.events
  WHERE at > NOW() - INTERVAL '24 hours'
    AND sleeve_id LIKE 'poly_updown_%_hybrid_v1'
    AND kind = 'poly_updown_resolution'
)
SELECT sleeve_id, COUNT(*) AS n,
       100.0 * AVG(won::int) AS wr_pct,
       AVG(pnl) AS dollar_per_trade,
       SUM(pnl) AS sum_pnl
FROM r GROUP BY 1 ORDER BY 5 DESC;
```

Expected for `poly_updown_btc_5m_s6_hybrid_v1`: n ≈ 100, WR ≥ 70%, sum_pnl ≥ +$300.

If WR < 60% after n ≥ 50: **PAUSE sleeve** and investigate. Most likely cause:
gate column computed differently in production vs backtest (e.g., wrong EMA
warmup, wrong RF param, missed causal anchor).

### C.2.4 Deploy + 7d — full backtest comparison

```sql
WITH live AS (
  SELECT sleeve_id, COUNT(*) AS n,
         AVG((data->>'won')::int) AS wr,
         AVG((data->>'pnl_usd')::numeric) AS dpt,
         SUM((data->>'pnl_usd')::numeric) AS sum_pnl
  FROM trading.events
  WHERE at BETWEEN NOW() - INTERVAL '7 days' AND NOW()
    AND kind = 'poly_updown_resolution'
    AND sleeve_id LIKE 'poly_updown_%_hybrid_v1'
  GROUP BY 1
)
SELECT sleeve_id, n, ROUND(wr*100, 1) AS wr_pct, ROUND(dpt, 2) AS dpt, ROUND(sum_pnl, 2) AS sum_pnl
FROM live
ORDER BY sum_pnl DESC;
```

Compare against backtest projection (Tier-1 metrics in A.1):
- `btc_5m_s6_hybrid_v1`: expect WR 77.8 ± 5pp, sum_pnl ≈ $14,103 × 7/28 ≈ **+$3,500/7d**
- Acceptable variance: ±25% on sum_pnl, ±5pp on WR
- If outside that band, root-cause via feature_snapshot diff between live + backtest fires

---

## C.3 Promotion checklist (paper → live)

For each new sleeve, BEFORE flipping `mode="paper"` → `mode="live"`:

1. ✅ **7 days of `mode="paper"` shadow with no crashes** (`SELECT COUNT(*) FROM trading.events WHERE sleeve_id=... AND kind='paper_audit_error' GROUP BY at::date` = 0)
2. ✅ **n ≥ 50 resolved fires** in the 7d shadow
3. ✅ **Live WR within ±5pp of backtest WR**
4. ✅ **Live $/tr within ±25% of backtest**
5. ✅ **Live max_loss_streak ≤ backtest max_streak + 2**
6. ✅ **Slug-overlap audit** — compute slug-overlap between this new sleeve and
   existing sleeves; if any pair > 60% overlap, AND combined $-PnL is not
   meaningfully > max($_A, $_B), then the smaller sleeve is redundant — skip.
7. ✅ **gate_decisions completeness** — confirm every gate produces a `pass`
   value on every fire (no `None`, no missing keys). The 2026-05-22 Bug #1
   (Markov regime=None) would have failed this check.
8. ✅ **Operator review** of WR + sum_pnl + DD per sleeve, plus the 6.5 slug-
   overlap matrix.
9. ✅ **Promotion is per-sleeve, not all-at-once.** Deploy one at a time, watch
   for 24h, then next.

---

## C.4 Rollback procedure

Rollback is per-sleeve:

```python
# In engine_main.py::_SHADOW_GATED_SLEEVES_SPEC:
{
    "sleeve_id": "poly_updown_btc_5m_s6_hybrid_v1",
    "mode": "disabled",   # was "paper" or "live"
    ...
}
```

Restart tradingvenue: `systemctl restart tradingvenue-backend`.

The sleeve stops firing immediately. Existing positions hold to slot_end and
settle normally. No financial impact.

**For S2 (fade momo patch)** specifically — different rollback: revert the
4-line patch in `momo.py` and restart. Existing momo sleeves return to
not-fading behavior.

**For S3 (HoD refresh)**: rollback = revert `HOD_TOP8_BY_CELL` to the prior
constant in `gates.py`. Sleeves resume on the old (wrong) anchor; ensemble
PnL drops back to ~$3k/28d. No risk; just reverts the improvement.

---

## C.5 Deploy order (priority sequence)

**Week 1 — Tier 1 deploy (paper-mode shadow)**:
- Day 0: Apply S3 (HoD refresh) — 5min, restart, immediate 5.4× existing ensemble lift
- Day 0: Apply S2 (Fade Momo patch) — 4-line momo strategy edit, restart
- Day 0: Apply B.7.1 (drop m5va from sleeve #2) — 1-line, restart
- Day 1: Build feature panels (RF + TR + cross-asset RF state) — 1-day dev
- Day 2: Register 4 hybrid_v1 sleeves (BTC s6, ETH s6, BTC s15, ETH s15) — paper-mode
- Day 3-9: 7-day paper shadow audit (run C.2 SQL daily)

**Week 2 — Tier 1 promotion + S1.5/S6/S7 sleeves**:
- Day 10: Operator review Tier 1 paper results. If pass, promote to `mode="live"` ONE sleeve at a time
- Day 10: Register S1.5 top 5 sleeves (per `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md`) — paper
- Day 12: Register S6 top 4 sleeves
- Day 14: Register S7 top 5 sleeves

**Week 3 — Tier 2 + Tier 3**:
- Day 15: Register cross-asset overlay sleeves (BTC UP/DOWN xa)
- Day 16: Register V7 standalone sleeves (BTC off=60/90/150)
- Day 17: Apply B.7.2 (sleeve #3 m1va add) + B.7.3 (tests)

**Week 4 — full validation**:
- Day 22: 7-day live data on all promoted sleeves
- Day 28: Operator decision — scale notional from $25 → $250 per sleeve based on per-sleeve realized PnL and DD

---

## C.6 Required infrastructure / new code on VPS3

| Component | New / extend | File | Purpose |
|---|---|---|---|
| RangeFilterState (per asset) | NEW | `backend/app/engine/range_filter.py` | Streaming RF (port from Python numba) |
| TradersRealityStore | NEW | `backend/app/engine/traders_reality.py` | EMAs 5/13/50/200/800 + cloud + stack |
| DailyAnchorStore | NEW | `backend/app/engine/daily_anchors.py` | Pivot + ADR from prior-day OHLC |
| PvsraDetector (1s) | NEW | `backend/app/engine/pvsra.py` | 6-state vector candle classification |
| CrossAssetRfCache | NEW | `backend/app/engine/cross_asset_rf.py` | {BTC, ETH, SOL} RF state |
| Vwap15mStore | extend B.3 spec | `backend/app/engine/vwap_store.py` | Slot-anchored VWAP for S1.5/S7 |
| SpikeDetector | NEW (B.4) | `backend/app/engine/spike_detector.py` | 5s/15s/30s ret + CVD |
| MarkovM1vStore | extend B.7.2 | `backend/app/engine/markov_store.py` | M1V regime cache |
| BarContext | extend | `backend/app/engine/poly_updown_loop.py` | Add tr_*, rf_*, xa_rf_*, m1va fields |
| Gate functions | NEW | `backend/app/engine/gates.py` | All `g_*` functions in A.5 |
| Sleeve specs | extend | `backend/app/engine/engine_main.py` | Register hybrid_v1 + xa + V7 sleeves |
| Tests | NEW | `backend/tests/test_hybrid_*.py` | Unit + integration |

Estimated dev: 4-6 days for infrastructure, 2 days for sleeve registration +
tests, 2 days for paper shadow burn-in. Total ~10 days to fully deploy Tier 1.

---

## C.7 Reference reports (all under `strategy_lab/reports/`)

### From hybrid system session (this run)
- `HYBRID_SYSTEM_FINAL_2026_05_26.md` ← top-level synthesis
- `HYBRID_SYSTEM_RESEARCH_2026_05_25.md` ← what the system is
- `HYBRID_GATE_SEARCH_2026_05_25.md` ← gate-stack results
- `HYBRID_STANDALONE_2026_05_25.md` ← V1-V12 standalone results
- `RF_PARAM_SWEEP_PVSRA5M_2026_05_25.md` ← RF tuning + PVSRA negative
- `CROSS_ASSET_MTF_CONFLUENCE_2026_05_25.md` ← cross-asset analysis
- `RANGE_FILTER_PANEL_2026_05_25.md`, `TRADERS_REALITY_PANEL_2026_05_25.md` ← panel docs
- `RF_RIBBON_OVERLAP_2026_05_25.md` ← RF vs ribbon analysis

### From prior session (2026-05-22/23)
- `HANDOFF_2026_05_23_COMPLETE.md` ← session handoff (TL;DR)
- `TV_AGENT_VWAP_CONTINUATION_FULL_SPEC_2026_05_23.md` ← S1.5 full implementation spec (17 sections, complete code)
- `TV_AGENT_PHASE34_FIXES_2026_05_22.md` ← B.7.1, B.7.2, B.7.3 specs
- `HOD_REFRESH_2026_05_22.md` ← S3 fix
- `SHADOW_11_SLEEVES_V2_2026_05_22.md` ← S3 ensemble comparison
- `FADE_MOMO_5M_2026_05_23.md` ← S2 fade momo
- `VWAP_SLOT_ANCHORED_5M_2026_05_23.md`, `VWAP_SLOT_V2_GATED_2026_05_23.md` ← S1.5 backtests
- `VWAP_DRAWDOWN_LIVEMIMIC_2026_05_23.md` ← S1.5 stress test
- `SPIKE_ENTRY_5M_2026_05_23.md` ← S6 backtest
- `VWAP_CONTINUATION_15M_2026_05_23.md` ← S7 backtest
- `Z_CONTRA_5M_2026_05_23.md` ← S5 underdog
- `MA_RIBBON_OVERLAY_2026_05_23.md`, `TA_INDICATORS_MEGA_RUN_2026_05_23.md` ← ribbon + TA overlays
- `NEW_INDICATOR_SLEEVES_15M_2026_05_23.md` ← 15m TA-overlay sleeves
- `VPS3_SHADOW_AUDIT_2026_05_22.md` ← 4-bug production audit

---

## C.8 Bottom-line numbers

If all Tier 1 + Tier 2 + Tier 3 + B.x sleeves deploy successfully:

| Layer | Sleeves | Est. sum/28d @ $25 |
|---|---:|--:|
| Existing 11-sleeve baseline (current shipped HoD) | 11 | $+2,949 |
| → + S3 HoD refresh (B.1, free) | (same 11) | **$+15,900** |
| → + S2 Fade Momo patch (B.2, free) | (in momo) | $+15,900 + $1,216 = **$+17,116** |
| → + B.7.1 (drop m5va) | (sleeve #2 fix) | + $745 → **$+17,861** |
| → + B.7.2 (sleeve #3 m1va) | (sleeve #3 fix) | + $1,265 → **$+19,126** |
| → + S1.5 5m top 10 sleeves (B.3) | +10 | + $10,300 → **$+29,426** |
| → + S6 5m top 4-8 sleeves (B.4) | +4 | + $2,800 (lower because hybrid_v1 covers same fires) |
| → + S7 15m top 5 sleeves (B.5) | +5 | + $2,407 → **$+34,633** |
| → + Tier 1 hybrid_v1 (A.1) | +7 | + $34,549 → **$+69,182** |
| → + Tier 2 cross-asset (A.2) | +2 | + $8,748 (additive on different sub-universe) → **$+77,930** |
| → + Tier 3 V7 standalone (A.3) | +5 | + $3,200 → **$+81,130** |

⚠️ **Caveat**: the +Tier 1 line counts the S6 BTC sleeve at +$14,103 even
though S6 baseline cells already contribute +$960 + $872 + ... = ~$5k. So
Tier 1 only adds the INCREMENTAL ~$9k beyond the bare S6 sleeves, not the
full $14k. Adjusted realistic combined:

**Realistic deployable total: ~$55-65k/28d at $25 notional = $1,960-2,320/day @ $25, ~$20-23k/day @ $250.**

Compared to today's shipped baseline ($2,949/28d), this is **18-22× the
current ensemble PnL**. Full validation via 7-day paper shadow is mandatory
before live promotion.

---

## End of spec

Implementer (TV agent): start with §C.5 deploy order. Day 0 = S3 + S2 + B.7.1
(zero-code changes, immediate 5-6× lift). Then build feature panels A.4, then
Tier 1 sleeves.

Backtest reference data lives at:
- `data/v4/canonical/_results/range_filter_1s.parquet`
- `data/v4/canonical/_results/traders_reality_1s.parquet`
- `data/v4/canonical/_results/{s15,s6,v15m}_joined_all.parquet`
- `data/v4/canonical/_results/hybrid_gate_search.csv`
- `data/v4/canonical/_results/hybrid_standalone_deployable.csv`
- `data/v4/canonical/_results/hybrid_walk_forward.csv`

Questions: contact the local strategy_lab Claude run (session
`HANDOFF_2026_05_23_COMPLETE.md` + this file). All scripts under
`strategy_lab/meta_classifier/` are reproducible — re-run any of them with
`PYTHONIOENCODING=utf-8 C:/Python314/python.exe <script>` to regenerate panels
or sweep parameters.
