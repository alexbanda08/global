# V52 CHAMPION — Complete Implementation Specification

**Audience:** engineering agent implementing the live trading engine
**Version:** 1.0 (2026-04-24)
**Status:** ready for paper-trade deployment
**Source of truth:** this document; canonical simulator in `strategy_lab/eval/perps_simulator.py`
**Target performance:** Sharpe 3.04 · CAGR +42.7% · MDD −7.4% · Calmar 5.74 (6-year backtest 2021-01-01 → 2026-03-31)

---

## 0. Quick reference — architecture at a glance

The portfolio is a **two-level daily-rebalanced blend** of 9 trade streams (some sleeves appear in two sub-accounts with different sizing):

```
V52_CHAMPION (total risk capital)
├── 60% ► V41 CHAMPION (inner blend)
│   ├── 60% ► P3 side (inverse-volatility weighted, 500-bar rolling)
│   │   ├── CCI_ETH_4h   (entry: V30 CCI Extreme | exit: V41 regime-adaptive)
│   │   ├── STF_AVAX_4h  (entry: V30 SuperTrend Flip + volume filter | exit: V41 regime-adaptive)
│   │   └── STF_SOL_4h   (entry: V30 SuperTrend Flip | exit: canonical EXIT_4H)
│   └── 40% ► P5 side (equal-weight)
│       ├── CCI_ETH_4h   (entry: V30 CCI Extreme | exit: V41 regime-adaptive)
│       ├── LATBB_AVAX_4h(entry: V29 Lateral BB Fade | exit: canonical EXIT_4H)
│       └── STF_SOL_4h   (entry: V30 SuperTrend Flip | exit: canonical EXIT_4H)
├── 10% ► SOL  MFI_75_25 + V41 regime-adaptive exits
├── 10% ► LINK Volume Profile Rotation (60-bar) + canonical exits
├── 10% ► AVAX Signed-Volume Divergence + canonical exits
└── 10% ► ETH  MFI_75_25 + canonical exits
```

**Daily rebalancing:** allocate capital to each trade stream per the weights above. Within P3, inverse-vol weights are recomputed daily from a 500-bar rolling stdev. Within P5, weights are fixed at 1/3 each. The top-level 60/10/10/10/10 split is static.

**Key engine contract:** one position at a time per (sleeve, instrument) combination. Same underlying instrument (e.g., ETH) may have multiple concurrent positions **across different sleeves** — they are independent trading streams sharing only the mark-to-market price.

---

## 1. Data requirements

### 1.1 Symbols and timeframes

Single timeframe for all strategies: **4-hour OHLCV bars**.

Required symbols (Binance perpetual, USDT-margined):
- `BTCUSDT` — used ONLY for the regime classifier on BTC (not traded directly in V52; kept for potential global regime gate in future versions)
- `ETHUSDT`
- `AVAXUSDT`
- `SOLUSDT`
- `LINKUSDT`

Note: the V52 champion does NOT use a BTC global gate. BTC data can be omitted from live trading if not already ingested. It IS needed for the regime classifier's fit on BTC if any future sleeve adds BTC.

### 1.2 Bar format (required columns, lowercase)

| Column | Type | Notes |
|---|---|---|
| `timestamp` | datetime (UTC, tz-aware) | Bar open time. Index must be monotonic, gap-free for active hours. |
| `open` | float | |
| `high` | float | |
| `low` | float | |
| `close` | float | |
| `volume` | float | Base-asset volume. Must be non-zero; zero-volume bars will break MFI and VP signals. |

Crypto trades 24/7, so no session handling. All timestamps should be UTC.

### 1.3 Historical depth required

- **Warm-up**: minimum 500 bars before first signal can fire (rolling-vol window for inv-vol weights + 120-bar MFI + 100-bar VWAP + 200-bar EMA regime filter). Recommend loading **1000 bars (~167 days)** of history before the first live bar.
- **Regime classifier**: requires first 30% of total history as in-sample for the HMM fit. For live deployment, the model is fit ONCE on a frozen historical window (e.g., 2021-01-01 → 2023-01-01) and then only classifies (no refit) in live mode. See §3.

### 1.4 Data quality checks (required on startup)

- No NaN values in OHLCV after dropping warmup period
- `high >= max(open, close)` and `low <= min(open, close)` for every bar
- `volume > 0` for ≥99% of bars (tolerate <1% zero-volume bars via ffill)
- No duplicate timestamps
- Gap detection: flag any gap > 1 bar duration; for 4h data, gap tolerance is exactly 14400s

---

## 2. Canonical simulator contract

All sleeves use the same core simulator. Spec is exact — do not deviate.

### 2.1 Position-management loop (per-bar, forward-walking)

For each bar `i` from 1 to N−1:

**Phase A — Manage open position (if one exists)**
1. Compute bars-held = `i - entry_idx`.
2. Update trailing stop (if enabled): see §2.4.
3. Check exit conditions in this priority order:
   - Hard Stop-Loss hit: `low[i] <= sl` (long) or `high[i] >= sl` (short)
   - Take-Profit hit: `high[i] >= tp` (long) or `low[i] <= tp` (short)
   - Time Stop hit: `bars_held >= max_hold`
4. If exited, record trade, update cash, clear position. Go to next bar.

**Phase B — Consider new entry**

Only if: `pos == 0 AND (i - last_exit) > 2 AND i+1 < N`

1. Check if `long_entries[i] == True` (go long) or `short_entries[i] == True` (go short).
2. If entering:
   - `entry_price = open[i+1] * (1 + slip * direction)` where direction = +1 long, −1 short (next-bar open with slip applied in direction of trade)
   - Compute position size — see §2.5
   - Compute SL price: `entry_price - sl_atr * ATR[i] * direction`
   - Compute TP price: `entry_price + tp_atr * ATR[i] * direction`
   - Set `entry_idx = i+1`, track `hh = ll = entry_price` for trailing

**Phase C — Mark-to-market**
- If flat: `eq[i] = cash`
- If in position: `eq[i] = cash + size * (close[i] - entry_p) * pos`

### 2.2 Critical rules (do not violate)

- **Next-bar-open fills only** — no same-bar entry at signal bar's close. The signal at bar `i` produces a position filled at bar `i+1` open.
- **Slippage is always against you**: long fills at `open * (1 + slip)`, short fills at `open * (1 - slip)`. Exit slippage applied similarly (SL-long: `sl * (1 - slip)`; SL-short: `sl * (1 + slip)`).
- **Two-bar cooldown after exit** — you cannot re-enter within 2 bars of the last exit on the same sleeve. This prevents whipsaw re-entries.
- **One position at a time** per sleeve. No pyramiding.
- **Signals evaluated at bar close** — entry_signals[i] is a decision based on data up to and including bar i's close, filled at i+1 open.
- **Conflicts resolved by long priority** — if both long and short signals fire on the same bar, take the long (historically very rare but spec it).

### 2.3 ATR (Average True Range) — Wilder smoothing

```
TR[i] = max(high[i] - low[i],
            |high[i] - close[i-1]|,
            |low[i] - close[i-1]|)

# Wilder smoothing with α = 1/n (n=14 default)
ATR[n-1] = mean(TR[0..n-1])
ATR[i]   = (1 - α) * ATR[i-1] + α * TR[i]   for i >= n
```

Use `n=14` unless explicitly overridden.

### 2.4 Trailing stop (ratchet-only)

Trail is active from entry if `trail_atr is not None`. At each bar `i`:

```
if pos == +1 (long):
    hh = max(hh, high[i])
    new_sl = hh - trail_atr * ATR[i]
    if new_sl > current_sl:
        current_sl = new_sl   # ratchet up only, never loosen

if pos == -1 (short):
    ll = min(ll, low[i]) if ll > 0 else low[i]
    new_sl = ll + trail_atr * ATR[i]
    if new_sl < current_sl:
        current_sl = new_sl   # ratchet down only
```

### 2.5 Position sizing (ATR-risk with leverage cap)

```
risk_dollars = cash * risk_per_trade       # risk_per_trade = 0.03 (3%)
stop_distance_$ = sl_atr * ATR[i]          # dollar distance to SL from entry
size_risk = risk_dollars / stop_distance_$  # shares/contracts
size_cap  = (cash * leverage_cap) / entry_price   # leverage_cap = 3.0
new_size  = min(size_risk, size_cap) * size_mult[i+1]
```

Defaults (always use these — V52 does not vary leverage by regime):
- `risk_per_trade = 0.03` (constant across all sleeves and regimes)
- `leverage_cap = 3.0` (constant across all sleeves and regimes)
- `size_mult = 1.0` (no per-bar size multiplier in V52 — drop this argument or pass scalar 1.0)

**Note 1:** on 4h crypto the leverage cap rarely binds (`size_risk` is typically 0.3× to 0.75× cash). Do not raise the cap without also raising `risk_per_trade`.

**Note 2 — regime/leverage interaction:** V52 has NO explicit regime-based leverage rule. Position size *implicitly* varies by regime through the exit stack: V41-exit sleeves use regime-dependent `sl_atr` (1.5 in LowVol → 2.5 in HighVol per §5.2), and since `size = risk_$ / (sl_atr × ATR)`, a tighter SL in LowVol produces a larger position per dollar of risk. This is a **side effect of regime-adaptive exits**, not a deliberate leverage control. Earlier research (V19 "regime-gated size" experiments) found that explicit per-regime leverage scaling *hurt* the blended portfolio Sharpe due to correlated-drawdown amplification across sleeves, so it was deliberately excluded from V52.

### 2.6 Fees and slippage

```
FEE  = 0.00045       # 4.5 bps Hyperliquid taker fee (per fill)
SLIP = 0.0003        # 3 bps slippage per fill
```

Apply on each entry and each exit. Total round-trip cost is thus `2 * FEE + 2 * SLIP` ≈ 15 bps of notional. Do not model maker rebate — the engine assumes market orders at next-bar open.

Fee cost per trade: `size * (entry_price + exit_price) * FEE`

### 2.7 Initial cash and equity accounting

- Each sleeve starts with `init_cash = 10,000.00` in its own simulator for backtesting.
- In live deployment, the per-sleeve cash is computed daily as `(total_portfolio_equity * sleeve_weight)` where weights are defined in §8.

---

## 3. Regime Classifier (HMM via GaussianMixture)

Used only by sleeves with V41 or V45 exit variants. Computed per-instrument (each symbol has its own model).

### 3.1 Feature engineering

For each 4h bar, compute these 4 features:

```
log_r[i]          = log(close[i]) - log(close[i-1])
rvol_120[i]       = std(log_r[i-119..i])          # 120 bars ≈ 20 days
volume_mean_120[i] = mean(volume[i-119..i])
vol_ratio[i]      = volume[i] / volume_mean_120[i]
hl_range_pct[i]   = (high[i] - low[i]) / close[i]
```

Drop any rows with NaN (first ~120 bars of warmup).

### 3.2 Model fit (forward-only, no look-ahead)

1. Split data into IS (first 30%) and OOS (rest).
2. On IS features: compute `mean`, `std` for each of 4 features. Z-score features using **IS-only statistics** (this is critical — do not leak OOS into normalization).
3. Fit `GaussianMixture(n_components=K, covariance_type="full", random_state=42, max_iter=300, n_init=3)` for K in {3, 4, 5}. Pick `K*` with lowest BIC.
4. Lock the model. **Do not refit** on OOS data.

### 3.3 Regime labelling (sort by mean volatility ascending)

After fitting:
1. Predict hard labels on IS features → get raw regime IDs.
2. For each raw regime ID, compute `mean(z_scored_rvol_120)` within that regime.
3. Sort regimes by this mean ascending. Lowest-vol regime becomes label index 0, highest becomes K-1.
4. Assign human-readable labels:
   - K=3 → `LowVol`, `MedVol`, `HighVol`
   - K=4 → `LowVol`, `MedLowVol`, `MedHighVol`, `HighVol`
   - K=5 → `LowVol`, `MedLowVol`, `MedVol`, `MedHighVol`, `HighVol`

### 3.4 Live classification (per-bar, no refit)

For each new bar `t`:
1. Compute features using only data up to `t` (windowed rolling — no peek-ahead).
2. Z-score using the IS-frozen `mean` and `std` from §3.2 step 2.
3. Call `gmm.predict_proba(X_t)` → posterior vector over K regimes.
4. Raw regime at t = argmax of posterior. Relabel via the sort mapping from §3.3.

### 3.5 Stability filter (applied AFTER raw labelling)

**Persistence (3-bar):** a regime must persist for 3 consecutive bars before becoming "active." Until then, carry forward the last stable regime label.

```python
stable[i] = last_stable   # initially -1 (Warming)
run_value = raw[0]
run_length = 1
for i in range(N):
    if raw[i] == run_value:
        run_length += 1
    else:
        run_value = raw[i]
        run_length = 1
    if run_length >= 3:
        last_stable = run_value
    stable[i] = last_stable
```

**Flicker detection (4 changes in 20 bars):** after persistence, scan the stable sequence for windows of 20 bars. If the stable-regime label changes more than 4 times in any rolling 20-bar window, mark that bar as `Uncertain`.

```python
changes[i] = 1 if stable[i] != stable[i-1] else 0
rolling_change_count = changes.rolling(20, min_periods=1).sum()
uncertain_mask = rolling_change_count > 4
```

### 3.6 Final regime label output

For each bar:
- If `uncertain_mask[i]` → label = `"Uncertain"`
- Elif `stable[i] < 0` → label = `"Warming"`
- Else → label from the K-regime mapping

### 3.7 Validation check (required at deployment)

On startup, verify:
```
assert train_end_date < first_oos_bar_date
```

Log: `K*` chosen, BIC table, regime-label distribution over full history, percentage of bars marked Uncertain/Warming (should be < 5% if healthy).

---

## 4. Signal functions (entry logic)

Each function returns `(long_entries, short_entries)` as boolean series aligned to the bar index. One position per sleeve at a time; entries suppressed if already in position (handled by simulator, not signal).

### 4.1 `sig_cci_extreme` (V30)

**Used by:** CCI_ETH_4h sleeve (both P3 and P5 sides of V41 champion).

```python
# Parameters
cci_n    = 20    # CCI lookback
cci_lo   = -150  # oversold threshold
cci_hi   = +150  # overbought threshold
adx_max  = 22    # ADX filter: only trade when ADX < adx_max (low-trend regime)
adx_n    = 14

# CCI computation
typical_price = (high + low + close) / 3
sma_tp        = rolling_mean(typical_price, cci_n)
mad_tp        = rolling_apply(typical_price, cci_n, lambda x: mean(abs(x - mean(x))))
cci           = (typical_price - sma_tp) / (0.015 * mad_tp)

# ADX (standard)
adx = compute_adx(high, low, close, adx_n)

# Entry logic (crosses back from extreme)
long_entries  = (cci.shift(1) <  cci_lo) & (cci >= cci_lo) & (adx < adx_max)
short_entries = (cci.shift(1) >  cci_hi) & (cci <= cci_hi) & (adx < adx_max)
```

**ADX formula for reference:**
```
up_move   = high[i] - high[i-1]
down_move = low[i-1] - low[i]
+DM = up_move   if up_move > down_move and up_move > 0 else 0
-DM = down_move if down_move > up_move and down_move > 0 else 0
TR  = as in ATR
+DI = 100 * SMA(+DM, n) / SMA(TR, n)
-DI = 100 * SMA(-DM, n) / SMA(TR, n)
DX  = 100 * |+DI - -DI| / (+DI + -DI)
ADX = SMA(DX, n)   # use simple mean not Wilder for this implementation
```

### 4.2 `sig_supertrend_flip` (V30)

**Used by:** STF_AVAX_4h, STF_SOL_4h.

```python
# Parameters
st_n     = 10    # ATR period for SuperTrend
st_mult  = 3.0   # ATR multiplier
ema_reg  = 200   # regime-filter EMA period

# ATR for SuperTrend (use same Wilder-smoothed ATR)
atr_st = ATR(high, low, close, st_n)

# SuperTrend basic upper/lower bands
hl2      = (high + low) / 2
upper_b  = hl2 + st_mult * atr_st
lower_b  = hl2 - st_mult * atr_st

# SuperTrend recursive
trend[0] = 1
st[0]    = lower_b[0]
for i in range(1, N):
    if close[i] > st[i-1]:
        trend[i] = 1
    elif close[i] < st[i-1]:
        trend[i] = -1
    else:
        trend[i] = trend[i-1]
    st[i] = lower_b[i] if trend[i] == 1 else upper_b[i]

# Flip events
flip = trend.diff()   # +2 = bullish flip, -2 = bearish flip

# Regime filter
ema200 = EMA(close, ema_reg)

long_entries  = (flip > 0) & (close > ema200)
short_entries = (flip < 0) & (close < ema200)
```

### 4.3 `sig_lateral_bb_fade` (V29)

**Used by:** LATBB_AVAX_4h (P5 side only).

```python
# Parameters
bb_n     = 20
bb_k     = 2.0
adx_max  = 18
adx_n    = 14

# Bollinger
sma  = rolling_mean(close, bb_n)
sd   = rolling_std(close, bb_n)
bb_u = sma + bb_k * sd
bb_l = sma - bb_k * sd

adx = compute_adx(high, low, close, adx_n)

# Entry: close touches band while ADX is low (ranging market)
long_entries  = (low  <= bb_l) & (close > bb_l) & (adx < adx_max)
short_entries = (high >= bb_u) & (close < bb_u) & (adx < adx_max)
```

### 4.4 `sig_mfi_extreme` — new (V50)

**Used by:** SOL MFI_75_25 sleeve (with V41 exits), ETH MFI_75_25 sleeve (with canonical exits).

```python
# Parameters (MFI_75_25 variant)
n        = 14
lower    = 25    # exit-oversold threshold (cross back up)
upper    = 75    # exit-overbought threshold (cross back down)
require_cross = True

# MFI computation
typical_price = (high + low + close) / 3
raw_money     = typical_price * volume

tp_change = typical_price.diff()
pos_money = raw_money.where(tp_change > 0, 0)
neg_money = raw_money.where(tp_change < 0, 0)

pos_sum = rolling_sum(pos_money, n)
neg_sum = rolling_sum(neg_money, n)

money_ratio = pos_sum / neg_sum   # guard against zero neg_sum → NaN handled naturally
mfi = 100 - 100 / (1 + money_ratio)

# Cross-back entries
prev_mfi = mfi.shift(1)
long_entries  = (prev_mfi < lower) & (mfi >= lower)
short_entries = (prev_mfi > upper) & (mfi <= upper)
```

### 4.5 `sig_volume_profile_rot` — new (V50)

**Used by:** LINK Volume Profile Rotation sleeve (with canonical exits).

Rolling volume profile over a window. For each bar, compute POC (highest-volume price bin), VAH (70% value-area high), VAL (70% value-area low) using only the last `win` bars.

```python
# Parameters
win           = 60    # rolling window in bars
n_bins        = 15    # number of price bins
value_area    = 0.70  # 70% of volume in value area
touch_buffer  = 0.001 # 0.1% tolerance for band touch

# For each bar i >= win:
#   - slice close[i-win:i], volume[i-win:i]
#   - compute price bin edges: linspace(min, max, n_bins+1)
#   - digitize each price into a bin; accumulate volume into vol_by_bin[0..n_bins-1]
#   - POC = midpoint of argmax(vol_by_bin)
#   - Expand from POC outward, preferring the higher-volume neighbor, until
#     cumulative volume reaches value_area * total_volume
#   - VAH = upper edge of last included bin; VAL = lower edge

# Entry conditions (computed per bar)
width_ok     = (vah - val) / close > 0.005   # reject degenerate narrow profiles
touch_val    = (low  <= val * (1 + touch_buffer)) & (close > val)  & (close < poc)
touch_vah    = (high >= vah * (1 - touch_buffer)) & (close < vah)  & (close > poc)

long_entries  = touch_val & width_ok
short_entries = touch_vah & width_ok
```

**Value-area expansion algorithm:**
```
poc_bin = argmax(vol_by_bin)
include = zeros(n_bins, dtype=bool); include[poc_bin] = True
cum_vol = vol_by_bin[poc_bin]
target  = value_area * sum(vol_by_bin)
lo_idx = hi_idx = poc_bin
while cum_vol < target and (lo_idx > 0 or hi_idx < n_bins-1):
    up = vol_by_bin[hi_idx + 1] if hi_idx + 1 < n_bins else -1
    dn = vol_by_bin[lo_idx - 1] if lo_idx - 1 >= 0    else -1
    if up >= dn and up >= 0:
        hi_idx += 1
    elif dn >= 0:
        lo_idx -= 1
    else:
        break
    cum_vol += vol_by_bin[hi_idx if direction_up else lo_idx]
VAH = bin_edges[hi_idx + 1]
VAL = bin_edges[lo_idx]
```

### 4.6 `sig_signed_vol_div` — new (V50)

**Used by:** AVAX Signed-Volume Divergence sleeve (with canonical exits).

CVD proxy using `sign(close - open)` as aggressor direction.

```python
# Parameters (SVD_tight variant)
lookback             = 20
cvd_win              = 50
min_cvd_threshold    = 0.5

# CVD proxy
signed_vol = volume * sign(close - open)
cvd        = rolling_sum(signed_vol, cvd_win)

# Baseline for divergence
cvd_median = rolling_median(cvd, cvd_win * 2)
cvd_std    = rolling_std(cvd,    cvd_win * 2)

# Price extremes
price_low  = rolling_min(close, lookback)
price_high = rolling_max(close, lookback)
at_new_low  = close <= price_low  * 1.001
at_new_high = close >= price_high * 0.999

# Bullish divergence: price at new low, CVD above median baseline
long_entries  = at_new_low  & (cvd > cvd_median + min_cvd_threshold * cvd_std)
short_entries = at_new_high & (cvd < cvd_median - min_cvd_threshold * cvd_std)
```

---

## 5. Exit stacks

Each sleeve is wired to one of three exit-stack profiles.

### 5.1 Canonical `EXIT_4H`

Used by: STF_SOL, LATBB_AVAX, LINK VP_ROT, AVAX SVD, ETH MFI_75_25.

```
tp_atr     = 10.0   # TP at entry ± 10 * ATR
sl_atr     =  2.0   # SL at entry ± 2 * ATR
trail_atr  =  6.0   # trailing stop at 6 * ATR from peak
max_hold   = 60     # force close after 60 bars (~10 days on 4h)
```

### 5.2 V41 regime-adaptive exit

Used by: CCI_ETH (both sides), STF_AVAX, SOL MFI_75_25.

At **entry time**, look up the regime label at bar `i` and freeze the exit profile for the trade's lifetime:

| Regime | sl_atr | tp_atr | trail_atr | max_hold |
|---|---:|---:|---:|---:|
| `LowVol` | 1.5 | 12.0 | 8.0 | 80 |
| `MedLowVol` | 1.8 | 11.0 | 7.0 | 70 |
| `MedVol` | 2.0 | 10.0 | 6.0 | 60 |
| `MedHighVol` | 2.3 | 8.0 | 4.0 | 40 |
| `HighVol` | 2.5 | 6.0 | 2.5 | 24 |
| `Uncertain` | 2.0 | 10.0 | 6.0 | 60 |
| `Warming` | 2.0 | 10.0 | 6.0 | 60 |

Rationale: loose exits in calm regimes (give trade room), tight exits in volatile regimes (bank fast, reversion risk elevated).

### 5.3 V45 (used only by STF_AVAX in P3 side)

V41 regime-adaptive exits + **volume filter at entry**:

```python
# Additional entry gate
volume_sma_20 = rolling_mean(volume, 20)
active_volume = volume > 1.1 * volume_sma_20

long_entries  = original_long_entries  & active_volume
short_entries = original_short_entries & active_volume
```

Only STF_AVAX uses V45. All other V41-exit sleeves use plain V41 (no volume filter).

---

## 6. Per-sleeve full wiring

This table is the single source of truth for which signal, symbol, and exit each trade stream uses.

| Sleeve ID | Stream | Symbol | Signal fn | Signal params | Exit stack | Weight |
|---|---|---|---|---|---|---:|
| `CCI_ETH_P3` | V41 champ / P3 | ETHUSDT | `sig_cci_extreme` | cci_n=20, cci_lo=-150, cci_hi=150, adx_max=22, adx_n=14 | V41 regime-adaptive | 60% × 60% × inv-vol |
| `STF_AVAX_P3` | V41 champ / P3 | AVAXUSDT | `sig_supertrend_flip` + volume filter | st_n=10, st_mult=3.0, ema_reg=200 | V41 regime-adaptive | 60% × 60% × inv-vol |
| `STF_SOL_P3` | V41 champ / P3 | SOLUSDT | `sig_supertrend_flip` | st_n=10, st_mult=3.0, ema_reg=200 | canonical EXIT_4H | 60% × 60% × inv-vol |
| `CCI_ETH_P5` | V41 champ / P5 | ETHUSDT | `sig_cci_extreme` | same as CCI_ETH_P3 | V41 regime-adaptive | 60% × 40% × 1/3 |
| `LATBB_AVAX_P5` | V41 champ / P5 | AVAXUSDT | `sig_lateral_bb_fade` | bb_n=20, bb_k=2.0, adx_max=18, adx_n=14 | canonical EXIT_4H | 60% × 40% × 1/3 |
| `STF_SOL_P5` | V41 champ / P5 | SOLUSDT | `sig_supertrend_flip` | same as STF_SOL_P3 | canonical EXIT_4H | 60% × 40% × 1/3 |
| `MFI_SOL` | V52 diversifier | SOLUSDT | `sig_mfi_extreme` | n=14, lower=25, upper=75, require_cross=True | V41 regime-adaptive | 10% |
| `VP_LINK` | V52 diversifier | LINKUSDT | `sig_volume_profile_rot` | win=60, n_bins=15, value_area=0.70, touch_buffer=0.001 | canonical EXIT_4H | 10% |
| `SVD_AVAX` | V52 diversifier | AVAXUSDT | `sig_signed_vol_div` | lookback=20, cvd_win=50, min_cvd_threshold=0.5 | canonical EXIT_4H | 10% |
| `MFI_ETH` | V52 diversifier | ETHUSDT | `sig_mfi_extreme` | n=14, lower=25, upper=75, require_cross=True | canonical EXIT_4H | 10% |

**Note:** `CCI_ETH_P3` and `CCI_ETH_P5` share the same signal and same entries — they are the **same trade stream on the same instrument but allocated twice** at different weights. Implementation can either run one CCI_ETH process and bucket its returns into P3 and P5 proportionally, or run two separate instances with independent starting cash — backtest used the second approach.

Same applies to `STF_SOL_P3`/`STF_SOL_P5`.

---

## 7. Blending / rebalancing logic

### 7.1 Daily rebalance (UTC 00:00)

At end of each calendar day (or session-boundary if you pick one), compute daily returns per sleeve and rebalance weights. **Weights apply to sleeve cash allocation going into the next day's trading.**

### 7.2 Top-level blend (static weights)

```
V52_capital = total_portfolio_equity

V41_cap = 0.60 * V52_capital
MFI_SOL_cap  = 0.10 * V52_capital
VP_LINK_cap  = 0.10 * V52_capital
SVD_AVAX_cap = 0.10 * V52_capital
MFI_ETH_cap  = 0.10 * V52_capital
```

### 7.3 V41 champion inner blend (static 60/40)

```
P3_cap = 0.60 * V41_cap
P5_cap = 0.40 * V41_cap
```

### 7.4 P3 inverse-vol weighting (dynamic, daily recompute)

Compute daily returns for each P3 sleeve over a **500-bar rolling window** (~3 months of 4h data):

```
for each sleeve s in [CCI_ETH_P3, STF_AVAX_P3, STF_SOL_P3]:
    r_s = daily_returns_series(s)  # last 500 bars, pct_change
    sigma_s = std(r_s)  # rolling 500-bar

inv_vol_s = 1.0 / sigma_s          # if sigma == 0, fallback to equal weight
w_s = inv_vol_s / sum(inv_vol_all)

CCI_ETH_P3_cap  = P3_cap * w_CCI_ETH
STF_AVAX_P3_cap = P3_cap * w_STF_AVAX
STF_SOL_P3_cap  = P3_cap * w_STF_SOL
```

**Edge case:** during the first 500 bars post-deployment, fall back to equal-weight (1/3 each) until 500-bar window is filled.

### 7.5 P5 equal-weight (static)

```
CCI_ETH_P5_cap   = P5_cap / 3
LATBB_AVAX_P5_cap = P5_cap / 3
STF_SOL_P5_cap   = P5_cap / 3
```

### 7.6 Capital allocation semantics

- Each sleeve maintains its own `cash` variable for sizing calculations.
- On rebalance, if a sleeve has an open position, the **existing position is NOT resized** — the new weight applies only to subsequent entries. This prevents accidental stop-hunting or slippage from mid-trade resizes.
- Realized P&L from trades accrues to per-sleeve cash balance.
- Portfolio total equity = sum of all sleeve cash + mark-to-market of open positions.

---

## 8. Risk management & kill switches

### 8.1 Per-sleeve hard limit

Any single sleeve hitting **−25% realized drawdown** (from its own peak equity) → disable that sleeve. Continue trading others.

### 8.2 Portfolio-level kill-switch schedule (MC-calibrated)

| Trigger | Threshold | Action | MC probability |
|---|---|---|---:|
| Month-1 realized DD | > 8% | Alert (review trade quality, no size change) | 5-10% |
| Rolling-3mo DD | > 12% | Reduce all sizes 50% | ~2% |
| Rolling-3mo DD | > 16% | Halt new entries, let open positions close | <0.5% |
| Rolling-6mo DD | > 20% | Full kill-switch, investigate offline | <0.1% |

"Rolling-Nmo DD" = `(current_equity / max_equity_in_last_N_months) - 1`.

### 8.3 Trade count sanity (4-week paper-trade gate)

During paper-trading, confirm per-sleeve trade count is within ±25% of the backtest monthly rate. If materially off, pause live deployment.

Expected per-sleeve monthly trade counts (from 6y backtest):

| Sleeve | Expected trades/year | Expected trades/month |
|---|---:|---:|
| CCI_ETH_P3 & P5 (shared stream) | 16 | 1.3 |
| STF_AVAX_P3 | 15 | 1.3 |
| STF_SOL_P3 & P5 (shared) | 19 | 1.6 |
| LATBB_AVAX_P5 | 9 | 0.7 |
| MFI_SOL | 40 | 3.3 |
| VP_LINK | 42 | 3.5 |
| SVD_AVAX | 21 | 1.8 |
| MFI_ETH | 39 | 3.3 |

### 8.4 Pre-flight checks on startup

1. Regime classifier no-leak assertion (train_end < first_oos_bar).
2. All symbol parquets load successfully with expected columns.
3. No NaN in warmup-cleaned OHLCV.
4. Fee and slippage constants match §2.6.
5. Current UTC time aligned to 4h bar boundary (02:00, 06:00, 10:00, 14:00, 18:00, 22:00) — reject start during a bar formation to avoid partial-bar signal evaluation.

---

## 9. Execution on Hyperliquid perpetual

### 9.1 Order type

All entries and exits are **market orders at next bar open**. Do not attempt to use limit orders unless you also update the slippage/fee constants in §2.6.

### 9.2 Funding rate handling

The backtest does NOT explicitly model funding. In live:
- Accrue funding cost to the sleeve's cash balance each funding settlement (every 8 hours on Hyperliquid).
- Long positions pay funding when funding is positive; short positions receive.
- Do not use funding as a signal.

### 9.3 Leverage and cross/isolated

- Leverage cap per sleeve is 3.0× cash (rarely binds). Exchange-level leverage should be set to 5× or higher to avoid liquidation risk; the effective leverage rarely exceeds 2×.
- Use **isolated margin per sub-account** if the exchange allows. Do not cross-margin between sleeves — a blowup in one sleeve must not liquidate others.

### 9.4 Partial fills

If an entry gets a partial fill:
- Use the fill size and average fill price for that trade's position.
- Do NOT attempt to fill the remainder on subsequent bars (would break next-bar semantics).
- If fill < 20% of intended size, log warning; if < 5%, abort the trade.

---

## 10. Expected performance (validation targets for paper-trading)

### 10.1 6-year backtest headline

| Metric | V52 Target |
|---|---:|
| Sharpe ratio (annualized, 2190 bars/year) | 3.04 |
| CAGR | +42.7% |
| Max drawdown | −7.4% |
| Calmar ratio | 5.74 |
| Min calendar year return | +11.1% |
| Positive calendar years | 6 of 6 |
| Avg bars per trade | ~20-30 |

### 10.2 Forward 1-year Monte Carlo distribution (1000 paths)

| Percentile | 1y CAGR | 1y MDD |
|---|---:|---:|
| 5th (worst 5%) | +17.7% | −9.9% |
| 50th (median) | +42.2% | −5.8% |
| 95th (best 5%) | — | — |

Probabilities:
- P(year-1 negative) = 0.0% (none of 1000 paths)
- P(DD > 20%) = 0.0%

### 10.3 Bootstrap CIs (1000 stationary block-bootstrap resamples, p=0.1)

- Sharpe lower 2.5% CI: 2.23
- Calmar lower 2.5% CI: 2.28
- MDD upper 97.5% CI (worst-case): −14.8%

### 10.4 Walk-forward (6 anchored expanding folds)

- Efficiency ratio (avg OOS / avg IS Sharpe): 1.07
- Positive OOS folds: 6/6

---

## 11. Testing & deployment checklist

### 11.1 Required unit tests before live deploy

- [ ] `atr()` matches Wilder-smoothed reference values for canonical test vector (100 random OHLC bars with known expected output).
- [ ] Every signal function produces identical entry/exit booleans for the provided 6-year backtest data (regression test vs backtest outputs in `phase5_results/`).
- [ ] `simulate()` matches trade list and final equity for each sleeve within 1 bp of backtest (due to float rounding).
- [ ] Regime classifier produces identical label distribution given the same seed and data.
- [ ] Inv-vol weights sum to 1.0 (within tolerance 1e-9) for every daily rebalance point.
- [ ] Kill-switch triggers fire correctly on synthetic drawdown paths.

### 11.2 Paper-trade phase (4 weeks minimum)

Go/no-go gates at end of week 4:
- [ ] Per-sleeve trade count within ±25% of backtest monthly rate (see §8.3).
- [ ] Aggregate realized Sharpe > 1.5 (backtest mean is 3.04; allow ±50% variance for 4 weeks of data).
- [ ] No single sleeve hit −15% realized DD alone.
- [ ] Combined P/L positive at end of week 4.
- [ ] No signal firing ≥3× more or ≥3× less than expected on any sleeve.

### 11.3 Post-deploy monitoring (ongoing)

Daily:
- Compute realized equity, per-sleeve P&L, current regime label per instrument.
- Log inv-vol weights used.
- Track rolling-30-day Sharpe per sleeve.

Weekly:
- Compare realized trade count to expected.
- Check regime distribution vs backtest distribution.
- Review any trade where `bars_held > 2 * expected_avg_hold`.

Monthly:
- Full portfolio audit: Sharpe, CAGR, MDD, Calmar, per-sleeve contribution.
- Re-run forward MC with latest returns to update kill-switch thresholds.

---

## 12. Appendix — Canonical reference implementations

### 12.1 Simulator entry point (pseudo-Python)

```python
def simulate(df, long_entries, short_entries,
             tp_atr, sl_atr, trail_atr, max_hold,
             risk_per_trade=0.03, leverage_cap=3.0,
             fee=0.00045, slip=0.0003, init_cash=10_000.0,
             size_mult=1.0):
    # returns (trades_list, equity_series)
    # implementation in strategy_lab/eval/perps_simulator.py
```

### 12.2 V41 regime-adaptive simulator

```python
def simulate_adaptive_exit(df, long_entries, short_entries, regime_labels,
                            regime_exits=REGIME_EXITS_4H,
                            risk_per_trade=0.03, leverage_cap=3.0,
                            fee=0.00045, slip=0.0003, init_cash=10_000.0,
                            size_mult=1.0):
    # identical to simulate() but uses regime_labels[entry_bar] to pick
    # tp_atr/sl_atr/trail_atr/max_hold from regime_exits dict
```

### 12.3 Bar indices and timestamps

Bar time `t` is interpreted as the **open** of that 4h bar:
- Signal `s[t]` is evaluated at the **close** of bar `t` (with all bar-t OHLCV data available).
- Position entered on signal `s[t]` fills at `open[t+1]`.
- Exit decisions evaluated at bar `t+k` close.

### 12.4 Minimum data pipeline check

```python
assert df.columns.issuperset({"open","high","low","close","volume"})
assert df.index.is_monotonic_increasing and df.index.is_unique
assert (df["high"] >= df[["open","close"]].max(axis=1)).all()
assert (df["low"]  <= df[["open","close"]].min(axis=1)).all()
assert not df.isna().any().any()
```

---

## 13. Known limitations & future work

- **Funding rate** not modeled in backtest. Live P&L may drift up to 20-30 bps/month from modeled P&L during high-funding environments.
- **Partial fills** not modeled. Hyperliquid has deep books on BTC/ETH/SOL/AVAX/LINK perp but LINK can be thinner — monitor slippage.
- **Plateau test** (Gate 8) was inherited rather than re-run on the new MFI/VP/SVD signals. These use canonical indicator parameters with wide-range robustness in literature; re-run the ±25%/±50% parameter sweep as a follow-up validation.
- **8h timeframe experiments blocked** — AVAX/SOL 8h parquets not available. Could provide cleaner low-noise versions of STF signals.
- **Pre-2021 history** would tighten Calmar CI further. If data is added, re-run full gate battery.

---

**End of specification.** Any ambiguity in this document is a bug — report to research team before implementing a workaround.
