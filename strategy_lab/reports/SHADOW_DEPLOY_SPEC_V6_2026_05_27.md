# Shadow Deploy Spec V6 — 2026-05-27

Round V6 sleeves (30 candidates, 13 deploy-ready post stability check). Companion to [SHADOW_DEPLOY_SPEC_2026_05_27.md](./SHADOW_DEPLOY_SPEC_2026_05_27.md) (V5 deploy spec).

V6 carries forward V5 conventions (ws_s anchor, 2%-on-profit fee, L25 walk, chainlink outcome, hold-to-slot-end) and adds:
- Constant $25 default stake (Kelly proved counterproductive on binary markets)
- Linear 3-bucket conviction sizing as Kelly alternative
- No $250 testing (operator dropped)
- Fill-time `g_book_supports_stake` veto to handle thin-book lottery tickets
- New gates introduced in V6 (see §3)

---

## 0. Engine constants (V6 deltas)

```
notional_default_usd   = 25.0    # constant default
notional_min_usd       = 5.0     # ramp-start
notional_bucket_L      = 5.0     # linear conviction: low gate-count
notional_bucket_M      = 15.0    # linear conviction: mid gate-count
notional_bucket_H      = 25.0    # linear conviction: max gate-count
fee_model              = legacy_2pct_profit
spread_filter_btc      = 0.02
spread_filter_eth      = 0.02
spread_filter_sol      = 0.025
exit_policy            = HOLD_TO_SLOT_END
fill_time_veto         = g_book_supports_stake   # MANDATORY for V6 sleeves
```

## 1. Anchor conventions (UNCHANGED from V5)

```
ws_s          = slot_start_us // 1_000_000 - window_s
fire_us       = slot_start_us + offset_s * 1_000_000
slot_end_us   = slot_start_us + window_s * 1_000_000
window_s_5m   = 300
window_s_15m  = 900

Pre-window gates (prefix g_pw_*): evaluated at ts_us = ws_s * 1_000_000
Intra-window gates: evaluated at ts_us <= fire_us - 1_000_000
Per-bar panel asof: backward, allow_exact_matches=True
```

## 2. Direction handling (UNCHANGED)

Enumerate BOTH directions per slug unless sleeve restricts (DOWN-only, UP-only).

## 3. NEW V6 gates — implementation spec

Existing V5 gates inherit from `SHADOW_DEPLOY_SPEC_2026_05_27.md` §3. New gates below.

### 3.A — Hurst trend gate (R3 panel)

```python
g_hurst_trending(direction, fire_us, asset, tf):
  # Source: vol_hurst_at_fire_{5m,15m}.parquet column 'hurst_60'
  # Hurst exponent over 60-bar window. >0.55 = persistent trend.
  hurst = vol_hurst_at_fire[asset, tf].hurst_60 at (slot_start_us)
  return hurst > 0.50   # R7-recalibrated threshold
```

### 3.B — Microstructure imbalance gates (microstructure_panel)

```python
g_imb5_strong_with(direction, fire_us, slug):
  # Source: microstructure_panel.parquet, columns imb5_up, imb5_dn
  # imb5 = book imbalance at top 5 levels (range -1 to +1)
  imb = microstructure_panel[slug].imb5_up - microstructure_panel[slug].imb5_dn at (fire_us - 1_000_000)
  thr = 0.30   # |imb5| > 0.30 = strong
  return (imb > thr and direction=="UP") or (imb < -thr and direction=="DOWN")
```

### 3.C — Bollinger Band position gate (ta_indicators_1s)

```python
g_bb_pos_with(direction, fire_us, asset):
  # Source: ta_indicators_1s.parquet column bb_pos_60s (0=lower band, 0.5=mid, 1=upper band)
  bbp = ta_indicators_1s[asset].bb_pos_60s at (fire_us - 1_000_000)
  if direction=="UP":   return bbp > 0.55   # above mid, leaning toward upper
  else:                 return bbp < 0.45   # below mid, leaning toward lower
```

### 3.D — Entry VWAP band filters (computed from fill at fire_us)

```python
g_entry_vwap_in_band(direction, fire_us, slug):
  # Standard band: kill lottery tickets and heavy favorites
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return 0.20 <= vwap_book <= 0.80

g_entry_vwap_in_band_narrow:    return 0.30 <= vwap_book <= 0.70
g_entry_vwap_in_30_70:          return 0.30 <= vwap_book <= 0.70
g_entry_vwap_in_45_85:          return 0.45 <= vwap_book <= 0.85
g_entry_vwap_in_55_80:          return 0.55 <= vwap_book <= 0.80
g_vwap_in_45_85:                 alias of g_entry_vwap_in_45_85
g_vwap_in_55_80:                 alias of g_entry_vwap_in_55_80
g_vwap_premium:                  vwap_book >= 0.55 (favors UP-favorite side)
g_favorite:                       vwap_book >= 0.55 (alias)
```

### 3.E — Pre-window gates (anchor at ws_s)

```python
g_pw_trend_slope_with(direction, fire_us, asset, tf):
  # Same definition as g_trend_slope_with from V5 §3.2 BUT anchored at ws_s
  ts = ws_s * 1_000_000
  ts_slope = trend_slope_30m(asset, tf, asof_bar_end(ts))
  return (ts_slope > 0 and direction=="UP") or (ts_slope < 0 and direction=="DOWN")

g_pw_mp_no_extreme(direction, fire_us, slug):
  # Microprice no-extreme evaluated at ws_s
  s = mp_skew at ws_s
  return abs(s) < 100.0   # bps

g_f7_rsi_strong_with(direction, fire_us, asset):
  # F7 RSI extreme at ws_s, matching direction
  # Source: master_gate_features_v2 column f7_rsi_at_ws OR compute live
  rsi = f7_rsi_at_ws(asset, ws_s)
  if direction=="UP":   return rsi < 30   # oversold + buying UP = mean-reversion
  else:                 return rsi > 70   # overbought + buying DOWN
```

### 3.F — Offset-bin gates

```python
g_offset_early(fire_us, slot_start_us):
  return 0 <= (fire_us - slot_start_us)/1e6 <= 60

g_off_60(fire_us, slot_start_us):
  return (fire_us - slot_start_us)/1e6 == 60

g_off_60_240(fire_us, slot_start_us):
  s = (fire_us - slot_start_us)/1e6
  return 60 <= s <= 240

g_off_L_late(fire_us, slot_start_us, tf):
  s = (fire_us - slot_start_us)/1e6
  if tf == "5m":   return 150 <= s <= 240
  if tf == "15m":  return 600 <= s <= 840

g_off_early304560(fire_us, slot_start_us):
  s = (fire_us - slot_start_us)/1e6
  return s in {30, 45, 60}
```

### 3.G — Microprice variants (microprice_panel)

```python
g_mp_skew_strong_with(direction, fire_us, slug):
  s = mp_skew at (fire_us - 1_000_000)
  return abs(s) > 50.0 AND sign(s) matches direction   # bps

g_mp_wt_no_extreme_100(direction, fire_us, slug):
  # Weighted microprice variant, no-extreme at 100bps
  s = microprice_panel[slug].mp_weighted_skew at (fire_us - 1_000_000) * 10000
  return abs(s) < 100.0

g_mp_no_extreme_150(direction, fire_us, slug):
  s = mp_skew at (fire_us - 1_000_000)
  return abs(s) < 150.0
```

### 3.H — Time-of-day gate

```python
g_hod_european_morning(fire_us):
  hour_utc = (fire_us // 1_000_000 // 3600) % 24
  return 7 <= hour_utc <= 11
```

### 3.I — Range filter band gate

```python
g_rf_in_band(direction, fire_us, asset):
  # RF direction + price within band (not breaking out)
  rf_dir      = range_filter_1s[asset].rf_dir       at (fire_us - 1_000_000)
  rf_band_pos = range_filter_1s[asset].rf_band_pos  at (fire_us - 1_000_000)
  if direction=="UP":
    return rf_dir == 1 AND 0.3 < rf_band_pos < 0.85
  else:
    return rf_dir == -1 AND 0.15 < rf_band_pos < 0.7
```

### 3.J — Hawkes loose imbalance variant

```python
g_hawkes_imb_loose_with(direction, fire_us, asset):
  # Hawkes self-exciting imbalance, loose threshold (V6 recal)
  imb = hawkes_panel[asset].lambda_imbalance at (fire_us - 1_000_000)
  return (imb > 0.1 and direction=="UP") or (imb < -0.1 and direction=="DOWN")
```

### 3.K — Book-supports-stake fill-time gate (REPLACES g_book_depth_supports_250)

```python
g_book_supports_stake(direction, fire_us, slug, stake_usd):
  # Mandatory FILL-TIME veto for V6. Cancel fire if depth insufficient.
  side = "UP" if direction=="UP" else "DOWN"
  cum_depth_usd = sum(price_i * size_i for asks_i in L25[side] up to top 25 levels)
  return cum_depth_usd > 6 * stake_usd   # 6x stake = headroom for slippage
  # For stake=$25: depth > $150 (replaces V5 depth_250 = $1500)
  # For stake=$5: depth > $30
```

---

## 4. Sleeve specifications (30 V6 sleeves)

Naming convention: `{ASSET}_{TF}_V6_{descriptor}_V6`. Naming uses _V6 suffix for dashboard identification.

For each sleeve: fire when ALL gates evaluate True at the specified anchor.

---

### Sleeve B5_01_V6 — BTC_5M_IMB5_HURST_LATE_V6

```
asset             = BTC, tf = 5m, window_s = 300
direction         = {UP, DOWN}
offset_s          ∈ {150, 180, 210, 240}
spread_filter     = 0.02

gates_all_must_pass:
  g_imb5_strong_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="BTC", tf="5m")

fill_time_veto: g_book_supports_stake(direction, slug, fire_us, stake=25)
```

Backtest: **train n=334 WR 89.8% $/tr +$3.55 | val n=93 WR 84.9% $/tr +$2.25 | lockbox n=161 WR 70.8% $/tr +$29.85** (lottery-amplified; post-veto realistic +$6-8) | DD $181 | LS 4 | bs_p 0.000.
**Lockbox sum @ $25 = $4,806 | 28d projection $69,089 RAW (NOT realistic). Use post-veto rate.**
Status: **DEPLOY** with mandatory fill-time veto. Realistic 28d ≈ $15-20k.

---

### Sleeve B5_02_V6 — BTC_5M_PW_F7RSI_IMB5_HURST_V6

```
asset             = BTC, tf = 5m, window_s = 300
direction         = {UP, DOWN}
anchor            = ws_s    # pre-window signal evaluation
offset_s          = 60      # fire at slot_start + 60s
spread_filter     = 0.02

gates_all_must_pass:
  g_f7_rsi_strong_with(direction, ws_s, asset="BTC")
  g_imb5_strong_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="BTC", tf="5m")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=499 WR 79.2% $/tr +$4.14 | val n=117 WR 72.6% $/tr +$1.67 | lockbox n=193 WR 66.3% $/tr +$21.34 | DD $391 ⚠ | LS 11 ⚠ | bs_p 0.000.
Status: **DEPLOY with stake=$5** (high DD + LS 11; risky).

---

### Sleeve B5_03_V6 — BTC_5M_IMB5_RIBBON_HURST_LATE_V6

```
asset             = BTC, tf = 5m, window_s = 300
direction         = {UP, DOWN}
offset_s          ∈ {150, 180, 210, 240}
spread_filter     = 0.02

gates_all_must_pass:
  g_imb5_strong_with(direction, fire_us, slug)
  g_ribbon_agrees(direction, fire_us, asset="BTC")
  g_hurst_trending(direction, fire_us, asset="BTC", tf="5m")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=249 WR 90.4% $/tr +$4.65 | val n=67 WR 82.1% $/tr +$2.13 | lockbox n=77 WR 75.3% $/tr +$31.74 | DD **$75** ⭐ | LS 2 | bs_p 0.000.
Status: **DEPLOY** — lottery flag present but DD is best of BTC 5m roster.

---

### Sleeve B5_04_V6 — BTC_5M_PW_MPNX_TS_IMB5_V6 ❌ DO NOT DEPLOY

```
val $/tr = −$0.85 — sleeve loses money on val data, lockbox luck. Overfit risk.
SKIP.
```

---

### Sleeve B5_05_V6 — BTC_5M_TS_EARLY_V6 ❌ DO NOT DEPLOY

```
val $/tr = −$2.53 — single-gate (g_trend_slope_strong_with) too generic.
SKIP.
```

---

### Sleeve E5_01_V6 — ETH_5M_BB_MP_HURST_BAND_V6

```
asset = ETH, tf = 5m, window_s = 300, offset_s = 60
direction = {UP, DOWN}, spread_filter = 0.02

gates_all_must_pass:
  g_bb_pos_with(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")
  g_entry_vwap_in_band(direction, fire_us, slug)   # [0.20, 0.80]

fill_time_veto: g_book_supports_stake
```

Lockbox: n=82 WR 81.7% $/tr +$14.12 | DD $50 | LS 2 | bs_p 0.000 | 28d $1,598.
Status: **DEPLOY**.

---

### Sleeve E5_02_V6 — ETH_5M_BB_SMS_HURST_NARROW_V6

```
asset = ETH, tf = 5m, window_s = 300, offset_s = 60
direction = {UP, DOWN}, spread_filter = 0.02

gates_all_must_pass:
  g_bb_pos_with
  g_sms_no_liquidity_above(direction, fire_us, asset="ETH", tf="5m")
  g_hurst_trending
  g_entry_vwap_in_band_narrow   # [0.30, 0.70]

fill_time_veto: g_book_supports_stake
```

Lockbox: n=48 WR 75.0% $/tr +$15.62 | DD $50 | LS 2 | bs_p 0.000 | 28d $1,382.
Status: **DEPLOY**.

---

### Sleeve E5_03_V6 — ETH_5M_CLOUD_RIBBON_MP_HURST_V6 🎯 RECOMMENDED PRIMARY

```
asset = ETH, tf = 5m, window_s = 300, offset_s = 60
direction = {UP, DOWN}, spread_filter = 0.02

gates_all_must_pass:
  g_tr_above_cloud(direction, fire_us, asset="ETH")
  g_ribbon_agrees
  g_mp_skew_with
  g_hurst_trending

fill_time_veto: g_book_supports_stake
```

Train n=187 WR 78.6% / val n=129 WR 83.7% / lockbox n=165 WR 83.6% | $/tr_lb +$8.44 | DD $93 | LS 2 | bs_p 0.000 | 28d **$2,213**.
Status: **DEPLOY PRIMARY** — best WR stability across 3 splits.

---

### Sleeve E5_04_V6 — ETH_5M_EMA200_CCI_MP_HURST_V6

```
asset = ETH, tf = 5m, window_s = 300, offset_s = 60, direction = {UP, DOWN}

gates_all_must_pass:
  g_tr_above_ema200
  g_cci_with
  g_mp_skew_with
  g_hurst_trending
```

n_train=186 WR 79.0% / val=125 WR 83.2% / lockbox=154 WR 83.8% | $/tr_lb +$7.79 | DD $79 | LS 2 | bs_p 0.000 | 28d $1,926.
Status: **DEPLOY** (alternative to E5_03 — uses ema200 vs cloud).

---

### Sleeve E5_05_V6 — ETH_5M_V5_REPL_OFF120_V6

```
asset = ETH, tf = 5m, window_s = 300, offset_s = 120, direction = {UP, DOWN}

gates_all_must_pass:
  g_tr_above_ema200
  g_mp_skew_with
  g_sms_liq_reclaim_with
  g_tr_in_active_session
```

n_train=67 WR 89.5% / val=28 WR 82.1% / lockbox=25 WR 88.0% | $/tr_lb +$6.49 | DD $25 | LS 1 | bs_p 0.000 | 28d $431.
Status: **DEPLOY** (replicates and confirms V5 sleeve 03/04/05 — same gate stack survives V6).

---

### Sleeve S5_01_V6 — SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6 🎯 RECOMMENDED PRIMARY

```
asset = SOL, tf = 5m, window_s = 300, spread_filter = 0.025
offset_s ∈ {30, 60, 90, 120, 150, 180, 210, 240}    # mid-window distribution
direction = {UP, DOWN}

gates_all_must_pass:
  g_cci_strong_with(direction, fire_us, asset="SOL")
  g_f7_rsi_with(direction, ws_s, asset="SOL")
  g_mfi_with(direction, fire_us, asset="SOL")
  g_tr_partial_stack_with(direction, fire_us, asset="SOL")
  g_vwap_in_45_85(direction, fire_us, slug)
```

Train n=61 WR 80.3% $/tr +$3.10 | val n=38 WR 78.9% $/tr +$2.78 | lockbox n=87 WR 83.9% $/tr +$4.62 | DD $92 | LS 3 | bs_p 0.001 | 28d $402.
Status: **DEPLOY PRIMARY** — all 3 splits positive.

---

### Sleeve S5_02_V6 — SOL_5M_F7_FAV_MP_RIBBON_VWAP_V6 ⚠ HOLD

```
val $/tr = −$2.58 — overfit risk. HOLD until re-validation.
```

---

### Sleeve S5_03_V6 — SOL_5M_CCI_F7_MP_VWAP_V6 ⚠ HOLD

```
val $/tr = −$2.46 — overfit risk. HOLD.
```

---

### Sleeve S5_04_V6 — SOL_5M_F7_MP_EMA200_VWAP_V6

```
asset = SOL, tf = 5m, window_s = 300, spread_filter = 0.025
offset_s = {30,60,90,120,150,180,210,240}, direction = {UP, DOWN}

gates_all_must_pass:
  g_f7_rsi_with(direction, ws_s, asset="SOL")
  g_mp_no_extreme_150(direction, fire_us, slug)
  g_tr_above_ema200(direction, fire_us, asset="SOL")
  g_vwap_in_55_80(direction, fire_us, slug)
```

Train n=64 WR 76.6% $/tr +$2.87 | val n=32 WR 78.1% $/tr +$2.65 | lockbox n=95 WR 82.1% $/tr +$4.23 | DD $96 | LS 3 | bs_p 0.001 | 28d $402.
Status: **DEPLOY**.

---

### Sleeve S5_05_V6 — SOL_5M_F7_MFI_EMA200_VWAP_V6

```
asset = SOL, tf = 5m, window_s = 300, spread_filter = 0.025
offset_s = {30,60,90,120,150,180,210,240}, direction = {UP, DOWN}

gates_all_must_pass:
  g_f7_rsi_with(direction, ws_s, asset="SOL")
  g_mfi_with(direction, fire_us, asset="SOL")
  g_tr_above_ema200
  g_vwap_in_55_80
```

Train n=41 WR 75.6% $/tr +$2.03 | val n=27 WR 77.8% $/tr +$2.40 | lockbox n=78 WR 83.3% $/tr +$4.66 | DD $64 | LS 2 | bs_p 0.004 | 28d $363.
Status: **DEPLOY** (smallest DD of SOL 5m roster).

---

### Sleeve B15_01_V6 — BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6

```
asset = BTC, tf = 15m, window_s = 900, offset_s = 840, direction = {UP, DOWN}

gates_all_must_pass:
  g_tr_above_ema800
  g_ribbon_slope_with
  g_hawkes_imb_loose_with
```

Train n=74 WR 63.5% / val n=22 WR 59.1% / lockbox n=21 WR 66.7% | $/tr_lb +$16.28 | DD $94 | LS 3 | bs_p 0.041 (borderline) | 28d $2,392.
Status: **DEPLOY** (monitor closely, bs_p near threshold).

---

### Sleeve B15_02_V6 — BTC_15M_RFBAND_EMA800_OFF600_DOWN_V6 🎯 RECOMMENDED

```
asset = BTC, tf = 15m, window_s = 900, offset_s = 600, direction = DOWN

gates_all_must_pass:
  g_dir_down
  g_rf_in_band(direction="DOWN", fire_us, asset="BTC")
  g_tr_above_ema800(direction="DOWN", fire_us, asset="BTC")
```

Train n=101 WR 61.4% / val n=30 WR 63.3% / lockbox n=16 WR **93.8%** | $/tr_lb +$17.25 | DD $25 | LS 1 | bs_p 0.001 | 28d $1,932.
Status: **DEPLOY** — best DD/WR profile.

---

### Sleeve B15_03_V6 — BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6 🎯 PRIMARY

```
asset = BTC, tf = 15m, window_s = 900, offset_s = 600, direction = DOWN

gates_all_must_pass:
  g_dir_down
  g_tr_above_ema200(direction="DOWN", fire_us, asset="BTC")
  g_mp_skew_strong_with(direction="DOWN", fire_us, slug)
  g_rf_with(direction="DOWN", fire_us, asset="BTC")
```

Train n=202 WR 63.4% / val n=71 WR 62.0% / lockbox n=34 WR 85.3% | $/tr_lb +$11.81 | DD $72 | LS 2 | bs_p 0.001 | 28d $2,810.
Status: **DEPLOY PRIMARY** — highest 28d projection.

---

### Sleeve B15_04_V6 — BTC_15M_MPSKEW_RIBSLP_HAWKES_OFF840_V6

```
asset = BTC, tf = 15m, window_s = 900, offset_s = 840, direction = {UP, DOWN}

gates_all_must_pass:
  g_mp_skew_strong_with
  g_ribbon_slope_with
  g_hawkes_imbalance_with
```

n_train=37 WR 64.9% / val=18 WR 66.7% / lockbox=21 WR 71.4% | $/tr_lb +$12.78 | DD $71 | LS 2 | bs_p 0.002 | 28d $1,878.
Status: **DEPLOY**.

---

### Sleeve B15_05_V6 — BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6

```
asset = BTC, tf = 15m, window_s = 900, offset_s = 600, direction = {UP, DOWN}

gates_all_must_pass:
  g_vwap_premium(direction, fire_us, slug)
  g_tr_above_ema50
  g_mp_skew_with
```

Train n=195 WR 69.2% / val n=74 WR 68.9% / lockbox n=44 WR 81.8% | $/tr_lb +$6.77 | DD $50 | LS 2 | bs_p 0.001 | 28d $2,086.
Status: **DEPLOY** — best 3-way stability of BTC 15m roster.

---

### Sleeve E15_01_V6 — ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6 🎯 PRIMARY

```
asset = ETH, tf = 15m, window_s = 900, offset_s ∈ {0, 30, 60}    # offset_early
direction = {UP, DOWN}, spread_filter = 0.02

gates_all_must_pass:
  g_tr_stack_full_with
  g_above_1h_dailyvwap_with
  g_offset_early
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_entry_vwap_in_30_70
```

Train n=51 WR 70.6% / val n=13 WR 69.2% / lockbox n=26 WR 84.6% | $/tr_lb +$10.72 | DD $100 | LS 4 | bs_p 0.000 | sum_4d_lb $279 ≈ 28d $1,953.
Status: **DEPLOY PRIMARY**.

---

### Sleeve E15_02_V6 — ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6 🎯 PRE-WINDOW WINNER

```
asset = ETH, tf = 15m, window_s = 900, offset_s ∈ {0, 30, 60}
anchor (for g_pw_*): ws_s
direction = {UP, DOWN}, spread_filter = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with
  g_offset_early
  g_vol_high
  g_pw_trend_slope_with(direction, ws_s, asset="ETH", tf="15m")    # PRE-WINDOW
```

Train n=38 WR 79.0% / val n=7 WR 57.1% / lockbox n=18 WR **94.4%** | $/tr_lb +$11.27 | DD $61 | LS 2 | bs_p 0.000 | sum_4d_lb $203 ≈ 28d $1,421.
Status: **DEPLOY** — FIRST V6 sleeve where pre-window ws_s anchor outperforms (94.4% vs 84.6% at fire_us).

---

### Sleeve E15_03_V6 — ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_DOWN_V6

```
asset = ETH, tf = 15m, window_s = 900, offset_s ∈ {0, 30, 60}, direction = DOWN

gates_all_must_pass:
  g_dir_down
  g_tr_stack_full_with
  g_above_1h_dailyvwap_with
  g_offset_early
  g_vol_high
```

n_train=20 WR 80.0% / val=6 WR 66.7% / lockbox=17 WR 88.2% | $/tr_lb +$10.37 | DD $50 | LS 2 | bs_p 0.000.
Status: **DEPLOY** (DOWN-only specialization).

---

### Sleeve E15_04_V6 — ETH_15M_TRSTACK_VWAP_OFFEARLY_PWTS_V6 ⚠

```
val $/tr indeterminate (cohort) — borderline bs_p=0.034.
Status: HOLD until re-validation.
```

---

### Sleeve E15_05_V6 — ETH_15M_V5_S3_REPL_V6 ⚠

```
bs_p=0.061 fails V6 threshold (≤0.05). val WR=50%.
Status: SKIP.
```

---

### Sleeve S15_01_V6 — SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6 🎯 GREENFIELD WINNER

```
asset = SOL, tf = 15m, window_s = 900, spread_filter = 0.025
offset_s ∈ {60, 120, 240}   # offset_60_240
direction = {UP, DOWN}

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  g_entry_vwap_in_band:  vwap < 0.80
```

Train n=183 WR 68.9% $/tr +$2.89 | val n=53 WR 71.7% $/tr +$2.57 | lockbox n=49 WR 71.4% $/tr +$4.12 | full n=285 $/tr_full +$3.04 | DD_lb $100 / DD_full $220 | LS 4 | bs_p 0.004 | sum_lb $202.
Status: **DEPLOY** — 3.3× lift over V5 SOL 15m best.

---

### Sleeve S15_02_V6 — SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP30_70_V6

```
Same as S15_01 but with g_entry_vwap_in_30_70 instead of <0.80
```

Train n=149 WR 69.1% $/tr +$4.16 | val n=39 WR 66.7% $/tr +$2.30 | lockbox n=38 WR 65.8% $/tr +$3.82 | sum_lb $145.
Status: **DEPLOY** (narrower band variant).

---

### Sleeve S15_03_V6 — SOL_15M_HOD_EU_OFF60_TR_ADR_VWAP30_70_V6

```
asset = SOL, tf = 15m, window_s = 900, offset_s = 60, direction = {UP, DOWN}, spread_filter = 0.025

gates_all_must_pass:
  g_hod_european_morning
  g_off_60      # single offset, exactly 60s
  g_tr_stack_with
  g_tr_within_adr
  g_entry_vwap_in_30_70
```

Train n=43 WR 72.1% $/tr +$5.51 | val n=17 WR 76.5% $/tr +$5.48 | lockbox n=13 WR 61.5% $/tr +$2.93 ⚠ | DD $50 | LS 2 | sum_lb $38.
Status: **HOLD** — lockbox WR drop concerning, small n.

---

### Sleeve S15_04_V6 — SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6

```
asset = SOL, tf = 15m, window_s = 900, offset_s = ALL, direction = {UP, DOWN}, spread_filter = 0.025

gates_all_must_pass:
  g_hod_european_morning
  g_rf_with
  g_tight_ribbon
  g_tr_stack_with
  vwap < 0.80
```

Train n=276 WR 69.2% $/tr +$4.42 | val n=75 WR 65.3% $/tr +$0.87 | lockbox n=72 WR 68.1% $/tr +$2.11 | sum_lb $152.
Status: **HOLD** — val $/tr collapse, marginal.

---

### Sleeve S15_05_V6 — SOL_15M_TR_RF_RIBSLP_VWAP55_V6 ⚠

```
Train WR=49.3% (coinflip), bs_p=NA reported. Lockbox $/tr +$5.51 inconsistent with train economics.
Status: SKIP.
```

---

## 5. Sleeve registry — flat table

```
ID            asset  tf   dir  offsets        spread  gates  status
B5_01_V6      BTC    5m   BOTH 150-240         0.02   2      DEPLOY (+veto)
B5_02_V6      BTC    5m   BOTH 60 (anchor ws_s) 0.02  3      DEPLOY @ $5
B5_03_V6      BTC    5m   BOTH 150-240         0.02   3      DEPLOY (+veto)
B5_04_V6      BTC    5m   BOTH 60 (anchor ws_s) 0.02  3      SKIP — val negative
B5_05_V6      BTC    5m   BOTH 30/45/60        0.02   1      SKIP — val negative

E5_01_V6      ETH    5m   BOTH 60              0.02   4      DEPLOY
E5_02_V6      ETH    5m   BOTH 60              0.02   4      DEPLOY
E5_03_V6      ETH    5m   BOTH 60              0.02   4      DEPLOY PRIMARY 🎯
E5_04_V6      ETH    5m   BOTH 60              0.02   4      DEPLOY
E5_05_V6      ETH    5m   BOTH 120             0.02   4      DEPLOY (= V5 c2 replicated)

S5_01_V6      SOL    5m   BOTH 30-240          0.025  5      DEPLOY PRIMARY 🎯
S5_02_V6      SOL    5m   BOTH 30-240          0.025  5      HOLD — val negative
S5_03_V6      SOL    5m   BOTH 30-240          0.025  4      HOLD — val negative
S5_04_V6      SOL    5m   BOTH 30-240          0.025  4      DEPLOY
S5_05_V6      SOL    5m   BOTH 30-240          0.025  4      DEPLOY

B15_01_V6     BTC    15m  BOTH 840             0.02   3      DEPLOY (borderline bs_p)
B15_02_V6     BTC    15m  DOWN 600             0.02   3      DEPLOY (best DD/WR) 🎯
B15_03_V6     BTC    15m  DOWN 600             0.02   3      DEPLOY PRIMARY 🎯
B15_04_V6     BTC    15m  BOTH 840             0.02   3      DEPLOY
B15_05_V6     BTC    15m  BOTH 600             0.02   3      DEPLOY (best stability)

E15_01_V6     ETH    15m  BOTH 0/30/60         0.02   5      DEPLOY PRIMARY 🎯
E15_02_V6     ETH    15m  BOTH 0/30/60 + ws_s  0.02   5      DEPLOY (PW winner) 🎯
E15_03_V6     ETH    15m  DOWN 0/30/60         0.02   5      DEPLOY
E15_04_V6     ETH    15m  BOTH 0/30/60 + ws_s  0.02   4      HOLD — borderline bs_p
E15_05_V6     ETH    15m  BOTH 0/30/60         0.02   4      SKIP — bs_p 0.061

S15_01_V6     SOL    15m  BOTH 60/120/240      0.025  5      DEPLOY 🎯
S15_02_V6     SOL    15m  BOTH 60/120/240      0.025  5      DEPLOY
S15_03_V6     SOL    15m  BOTH 60              0.025  5      HOLD
S15_04_V6     SOL    15m  BOTH ALL             0.025  5      HOLD
S15_05_V6     SOL    15m  BOTH ALL             0.025  3      SKIP — train WR=coinflip
```

**Deploy roster size**: 19 sleeves DEPLOY + 5 HOLD + 6 SKIP = 30 total V6 sleeves evaluated.

## 6. Execution params (V6 deltas)

```
notional_default_usd = 25.0       # V6 default (Kelly proved counterproductive)
fill_method          = L25_book_walk
fill_min_book_events = 25         # sparse-book filter
hold_to              = slot_end_us
fee_model            = legacy_2pct_profit
latency_budget_ms    = 85

# MANDATORY for V6 — replaces V5's g_book_depth_supports_250
g_book_supports_stake: cancel fire if L25 cumulative depth on chosen side < 6 × notional_usd
```

## 7. Variable sizing — linear conviction bucket (Kelly alternative)

Kelly 0.25× proved anti-uplift on V6 markets (clamps to $5 floor due to high entry_vwap + 2% fee). Use **linear 3-bucket conviction sizing** as the variable-stake schedule.

### Conviction score (per fire)

For sleeves with N total gates evaluated, conviction = (# gates passing) / N. But all V6 sleeves require ALL gates to pass for entry, so this collapses to a constant. Instead:

**Use a "soft" conviction calc**: count gates that ARE BORDERLINE (within 10% of their threshold) vs FULL_STRENGTH (passing with margin >10%). conviction = (# full-strength) / N_total.

### Bucket → stake

```python
def stake_from_conviction(conviction_score):
    if conviction_score < 0.34:    return 5.0    # bucket L
    if conviction_score < 0.67:    return 15.0   # bucket M
    return 25.0                                    # bucket H
```

### Recommendation per market

- **BTC 5m, ETH 5m, BTC 15m, SOL 15m**: constant $25 (Kelly underperforms by 25-80%)
- **ETH 15m broader 3-gate funnel**: linear-bucket (lifts PnL +408-599% vs flat)
- **SOL 5m**: constant $25

## 8. Shadow logging — extended schema (V6 additions)

Add to V5 logging schema:

```
+ conviction_score        : float
+ stake_bucket            : "L" | "M" | "H"
+ stake_applied_usd       : float
+ depth_check_passed      : bool
+ depth_observed_usd      : float
+ pw_anchor_features      : {f7_rsi_at_ws, m1v_at_ws, trend_slope_at_ws, ...}  # for sleeves using ws_s gates
+ lottery_flag            : bool   # vwap < 0.10 OR vwap > 0.90
```

## 9. Threshold constants (V6 additions)

```
hurst_trending_thr     = 0.50    # from R7 recalibration
imb5_strong_thr        = 0.30
bb_pos_upper_thr       = 0.55
bb_pos_lower_thr       = 0.45
mp_skew_strong_bps     = 50.0
mp_no_extreme_100_bps  = 100.0
mp_no_extreme_150_bps  = 150.0
vwap_band_default      = [0.20, 0.80]
vwap_band_narrow       = [0.30, 0.70]
vwap_band_30_70        = [0.30, 0.70]
vwap_band_45_85        = [0.45, 0.85]
vwap_band_55_80        = [0.55, 0.80]
vwap_premium_min       = 0.55
hod_european_morning   = [7, 8, 9, 10, 11]   # UTC hours
hawkes_imb_loose_thr   = 0.10
rf_band_pos_band_up    = [0.30, 0.85]
rf_band_pos_band_down  = [0.15, 0.70]
```

## 10. Open items / caveats

1. **BTC 5m sleeves B5_01, B5_03**: lottery-ticket concentration (78% PnL from 5% vwap<0.10 fires). Mandatory `g_book_supports_stake` fill-time veto. Realistic post-veto $/tr ~$6-8 (not $29-31). Do NOT scale stake based on raw $/tr.

2. **B5_02 (pre-window F7 RSI)**: LS=11 + DD $391 + WR_lb 66.3%. High risk. Deploy at $5 only.

3. **B5_04, B5_05**: val $/tr NEGATIVE. Overfit. Do not deploy without re-validation on a fresh holdout.

4. **SOL 5m S5_02, S5_03**: val $/tr NEGATIVE. Hold until re-validation.

5. **ETH 15m E15_02 (pre-window)**: only V6 sleeve where ws_s anchor genuinely outperforms (94.4% vs 84.6% same gates at fire_us). Confirms momo anchor for 15m. Production momo team should adopt same gate stack for shadow comparison.

6. **SOL 15m S15_05 (C6)**: train WR=49.3% (coinflip), inconsistent lockbox $/tr +$5.51. Skip.

7. **`g_book_supports_stake` (§3.K)** must be implemented as FILL-TIME veto, not search-time gate. Cancel order if L25 cumulative depth < 6 × stake.

8. **Pre-window mechanic** (sleeves B5_02, B5_04, E15_02) requires production controller to evaluate `g_pw_*` gates at `ws_s` and queue order to fire at `slot_start + offset_s`. Same pattern as production momo's `build_bar_context_t_plus_60`.

9. **Linear bucket conviction (§7)**: Only ETH 15m broader funnel showed uplift. Other markets stick with constant $25.

10. **Slug overlap audit MANDATORY before quoting combined V5+V6 deploy PnL.** ~13 V6 deploys + ~14 V5 deploys = 27 candidate sleeves. Many may overlap on same slugs.

---

## NEXT ROUND DIRECTIVES (post-V6)

If V6 paper data confirms backtest:
- Tighten constraints again (LS≤8) and re-search to find HIGHER $/tr sleeves
- Add cross-market direction-asymmetric ensembles (e.g., BTC DOWN + ETH UP correlated regime)
- Build offset=0 fires (not in v3 fire universe; needs new build)
- Test 2-leg straddles (UP token at one offset + DOWN token at another)

---

## END
