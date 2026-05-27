# Shadow Deploy Spec — 16 Sniper Sleeves — 2026-05-27

For TV agent implementation on VPS3 (tradingvenue). Self-contained: gate definitions, sleeve specs, execution params, logging schema.

---

## 0. Engine constants

```
notional_usd       = 25.0         # max — start ops at $5–8/fire and ramp
fee_model          = legacy        # 2% on profit (winning leg only) — matches production
spread_filter_btc  = 0.02
spread_filter_eth  = 0.02
spread_filter_sol  = 0.025
window_s_5m        = 300
window_s_15m       = 900
fill_engine        = L25_book_walk  # equivalent to engine_v2.fill_at_book
exit_policy        = HOLD_TO_SLOT_END  # NO SL / NO TP / NO mid-slot exit
mode               = paper          # all sleeves start mode="paper"
```

## 1. Anchor + timing conventions

For every sleeve:
```
slot_start_us = chainlink resolution slot start (UTC microseconds)
window_s      = 300 (5m) or 900 (15m)
ws_s          = slot_start_us // 1_000_000 - window_s         # signal anchor
fire_us       = slot_start_us + offset_s * 1_000_000          # entry time
slot_end_us   = slot_start_us + window_s * 1_000_000          # exit time
```

Feature lookup MUST be causal: every panel join uses `ts_us <= fire_us - 1_000_000` (1s epsilon for 1s panels) or `ts_us <= ws_s * 1_000_000` (ws_s anchor) — never `ts_us <= slot_start_us` and never `ts_us <= fire_us` without epsilon.

For per-bar (5m / 15m) panels, the panel's `ts_us` is bar END (canonical `_v2_fixed` variant). Use `merge_asof(direction="backward", allow_exact_matches=True)`.

## 2. Direction enumeration

For each candidate fire, evaluate BOTH directions UP and DOWN unless a sleeve restricts direction (noted per-sleeve). For each direction:
1. Compute all gates for (direction, fire_us)
2. If all gates pass → place limit-taker order on the matching outcome token at L25 vwap, size = `notional_usd / vwap` shares
3. Hold to slot_end
4. PnL = `(1 - vwap) * shares * 0.98 if won else -vwap * shares`

## 3. Gate library — EXACT formulas

### 3.1 Order-book gates (L25 stream)

```
g_book_depth_supports_250(direction, fire_us):
  # Sum L25 ask depth on chosen side at fire_us
  side = "UP" if direction=="UP" else "DOWN"
  cum_depth_usd = sum(price_i * size_i for ask_i in L25[side] up to top 25 levels)
  return cum_depth_usd > 6 * 250.0  # i.e., > $1500 on the side we're buying

g_depth_250_strict(direction, fire_us):
  side       = "UP" if direction=="UP" else "DOWN"
  other_side = "DOWN" if direction=="UP" else "UP"
  return cum_depth_usd[side] > 1500.0 AND cum_depth_usd[other_side] > 750.0
```

### 3.2 Trend / regime gates (source: regime_panel_{tf}_v2_fixed.parquet)

Panel built from 1m binance klines aggregated to {tf}. `ts_us` = bar_end.

```
trend_slope_30m(asset, tf, ts):
  # bars_30m = 6 for 5m, 2 for 15m
  bars_back = 30 // (5 if tf=="5m" else 15)
  close_now  = panel[asset, tf].close at ts
  close_back = panel[asset, tf].close at (ts - bars_back bars)
  atr_60m    = panel[asset, tf].atr_14    # 14-bar ATR ≈ 70m, used as 60m proxy
  return (close_now - close_back) / atr_60m

g_trend_slope_with(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)   # bar that ENDED before fire_us
  ts_slope = trend_slope_30m(asset, tf, ts)
  if ts_slope is NaN: return False
  return (ts_slope > 0 and direction=="UP") or (ts_slope < 0 and direction=="DOWN")

g_trend_slope_strong_with(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)
  ts_slope = trend_slope_30m(asset, tf, ts)
  if ts_slope is NaN: return False
  thr = quantile(|trend_slope_30m| over training window) at p=0.75
  # Persist thr per (asset, tf) at deploy time; recompute monthly.
  # Reference values from this session (train window May 1–22):
  #   BTC 5m=0.385  ETH 5m=0.398  SOL 5m=0.412  BTC 15m=0.612  ETH 15m=0.624  SOL 15m=0.643
  return |ts_slope| > thr AND sign(ts_slope) matches direction

g_regime_stack_with(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)
  label = panel[asset, tf].regime_label at ts   # in {trending_up, trending_dn, ranging}
  return (label=="trending_up" and direction=="UP") or (label=="trending_dn" and direction=="DOWN")
```

### 3.3 Microprice gates (source: microprice_panel.parquet)

Stoikov microprice on UP and DOWN tokens at L25. `ts_us` = order-book event time.

```
mp_skew(fire_us, slug):
  # Skew between UP and DOWN microprices: mp_up - mp_dn (in basis points)
  mp_up = microprice_panel[slug, side=UP].weighted_microprice at fire_us
  mp_dn = microprice_panel[slug, side=DOWN].weighted_microprice at fire_us
  return (mp_up - mp_dn) * 10000

g_mp_skew_with(direction, fire_us, slug):
  s = mp_skew(fire_us, slug)
  if s is NaN: return False
  return (s > 0 and direction=="UP") or (s < 0 and direction=="DOWN")

g_mp_skew_strong_with(direction, fire_us, slug):
  s = mp_skew(fire_us, slug)
  if s is NaN: return False
  thr_bps = 50.0   # strong = >50bps absolute skew
  return |s| > thr_bps AND sign(s) matches direction

g_mp_no_extreme(direction, fire_us, slug):
  # Note: direction-independent — micro spread is too wide ⇒ untradable
  s = mp_skew(fire_us, slug)
  return |s| < 100.0   # R7-recalibrated threshold (was 50, loosened to 100)

g_mp_no_extreme_100(direction, fire_us, slug):
  # Same as g_mp_no_extreme — alias used in SOL 5m S5 spec
  return g_mp_no_extreme(direction, fire_us, slug)
```

### 3.4 Range Filter (source: range_filter_1s.parquet)

Mark Lijesen RF on 1s closes.

```
g_rf_with(direction, fire_us, asset):
  rf_dir = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)   # 1s epsilon
  return (rf_dir==1 and direction=="UP") or (rf_dir==-1 and direction=="DOWN")

g_rf_aged(direction, fire_us, asset):
  rf_dir     = range_filter_1s[asset].rf_dir       at (fire_us - 1_000_000)
  rf_dir_age = range_filter_1s[asset].rf_dir_age_s at (fire_us - 1_000_000)
  return g_rf_with(direction, fire_us, asset) AND rf_dir_age >= 60   # signal aged at least 60s

g_rf_fresh(direction, fire_us, asset):
  rf_dir_age = range_filter_1s[asset].rf_dir_age_s at (fire_us - 1_000_000)
  return g_rf_with(direction, fire_us, asset) AND rf_dir_age <= 60   # signal fresh (<60s old)

g_rf_strict_align(direction, fire_us, asset):
  # rf direction + rf band position aligned with direction
  rf_dir      = range_filter_1s[asset].rf_dir       at (fire_us - 1_000_000)
  rf_band_pos = range_filter_1s[asset].rf_band_pos  at (fire_us - 1_000_000)
  if direction=="UP":   return rf_dir==1  AND rf_band_pos >= 0.5
  else:                 return rf_dir==-1 AND rf_band_pos <= 0.5
```

### 3.5 Traders' Reality / EMA gates (source: traders_reality_1s.parquet)

EMA 5/13/50/200/800 + PVSRA + pivots + sessions, all on 1s binance close.

```
g_tr_above_ema50(direction, fire_us, asset):
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  ema50 = traders_reality_1s[asset].ema_50 at (fire_us - 1_000_000)
  return (close > ema50 and direction=="UP") or (close < ema50 and direction=="DOWN")

g_tr_above_ema200(direction, fire_us, asset):
  # same pattern with ema_200
g_tr_above_ema800(direction, fire_us, asset):
  # same pattern with ema_800
g_tr_above_cloud(direction, fire_us, asset):
  # close above kumo cloud (max(ssa, ssb))
  ssa = traders_reality_1s[asset].ssa at (fire_us - 1_000_000)
  ssb = traders_reality_1s[asset].ssb at (fire_us - 1_000_000)
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  cloud_top = max(ssa, ssb)
  cloud_bot = min(ssa, ssb)
  return (close > cloud_top and direction=="UP") or (close < cloud_bot and direction=="DOWN")
g_tr_above_pp(direction, fire_us, asset):
  pp = traders_reality_1s[asset].pp_classic_daily at (fire_us - 1_000_000)
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  return (close > pp and direction=="UP") or (close < pp and direction=="DOWN")

g_tr_stack_with(direction, fire_us, asset):
  # EMA stack score in {-2,-1,0,1,2}; +2 = all 5 EMAs in bull order (ema5>13>50>200>800), -2 = reverse
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score >= 1 and direction=="UP") or (score <= -1 and direction=="DOWN")

g_tr_stack_full_with(direction, fire_us, asset):
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score == 2 and direction=="UP") or (score == -2 and direction=="DOWN")

g_tr_partial_stack_with(direction, fire_us, asset):
  # 4 of 5 EMAs aligned (i.e., score ∈ {±1})
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score == 1 and direction=="UP") or (score == -1 and direction=="DOWN")

g_tr_within_adr(direction, fire_us, asset):
  # close within +/- 1.0 * ADR_20 from daily open
  adr20 = traders_reality_1s[asset].adr_20_pct at (fire_us - 1_000_000)
  daily_open = traders_reality_1s[asset].daily_open at (fire_us - 1_000_000)
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  return |close/daily_open - 1| < adr20

g_tr_in_active_session(direction, fire_us, asset):
  # at least 1 of {london, ny, tokyo} is active at fire_us
  count = traders_reality_1s[asset].tr_active_session_count at (fire_us - 1_000_000)
  return count >= 1
```

### 3.6 Ribbon gates (source: traders_reality_1s.parquet)

EMA ribbon (5/8/13/21/34/55) lead-slope on 1s.

```
g_ribbon_agrees(direction, fire_us, asset):
  color = traders_reality_1s[asset].ribbon_color at (fire_us - 1_000_000)   # in {green,red,neutral}
  return (color=="green" and direction=="UP") or (color=="red" and direction=="DOWN")

g_ribbon_slope_with(direction, fire_us, asset):
  slope_bps = traders_reality_1s[asset].ribbon_lead_slope_bps at (fire_us - 1_000_000)
  return (slope_bps > 0 and direction=="UP") or (slope_bps < 0 and direction=="DOWN")
```

### 3.7 CCI gate (source: ta_indicators_1s.parquet)

```
g_cci_strong_with(direction, fire_us, asset):
  cci = ta_indicators_1s[asset].cci_60s at (fire_us - 1_000_000)
  if cci is NaN: return False
  thr = 100.0
  return (cci > thr and direction=="UP") or (cci < -thr and direction=="DOWN")
```

### 3.8 SMS / liquidity gates (source: sms_panel_{tf}_v2_fixed.parquet)

Traders' Reality Smart Money Concepts: CHoCH, BOS, liquidity sweeps.

```
g_sms_liq_reclaim_with(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)
  reclaim_dir = sms_panel[asset, tf].liq_reclaim_dir at ts   # in {1, -1, 0}
  return (reclaim_dir==1 and direction=="UP") or (reclaim_dir==-1 and direction=="DOWN")

g_sms_no_liquidity_above(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)
  side = "above" if direction=="UP" else "below"
  liq_count = sms_panel[asset, tf]["sms_liquidity_count_" + side] at ts
  return liq_count == 0    # no unrun stops on chosen side
```

### 3.9 Vol gates (source: vol_hurst_at_fire_{5m,15m}.parquet)

```
g_vol_high(direction, fire_us, asset, tf):
  rv_60 = vol_hurst_at_fire[asset, tf].rv_60 at (fire_offset_s, slug)
  # rv_60 = 60-bar realized vol (annualized, asset-specific)
  # Threshold: top 25% of the rv_60 distribution computed over training window
  thr = pre-computed quantile @ p=0.75. Reference (May 1–22):
  #   BTC 5m=0.0084  ETH 5m=0.0109  SOL 5m=0.0142
  #   BTC 15m=0.0162 ETH 15m=0.0203 SOL 15m=0.0271
  return rv_60 > thr
```

### 3.10 1h daily-VWAP gate (build from binance 1m or 1h klines)

```
above_1h_dailyvwap(asset, fire_us):
  # Daily VWAP, anchored at 00:00 UTC of current day, computed from 1m klines
  day_start_us = floor(fire_us, 1 day UTC)
  bars = binance_1m[asset] where ts_us in [day_start_us, fire_us - 1_000_000)
  vwap = sum(close * volume) / sum(volume)
  close = binance_1m[asset].close at (fire_us - 1_000_000)
  return close > vwap

g_above_1h_dailyvwap_with(direction, fire_us, asset):
  above = above_1h_dailyvwap(asset, fire_us)
  return (above and direction=="UP") or (not above and direction=="DOWN")
```

### 3.11 Pivot proximity (source: traders_reality_1s.parquet pp_classic_daily)

```
g_near_pivot(direction, fire_us, asset):
  pp = traders_reality_1s[asset].pp_classic_daily at (fire_us - 1_000_000)
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  return |close - pp| / close < 0.005   # within 0.5%
```

### 3.12 Offset / time-of-day gates

```
g_offset_early(direction, fire_us, slot_start_us):
  return 0 <= (fire_us - slot_start_us) / 1_000_000 <= 60

g_hod_us_afternoon(direction, fire_us):
  hour_utc = (fire_us // 1_000_000 // 3600) % 24
  return 18 <= hour_utc <= 22   # 14:00–18:00 NY EDT

g_dir_up(direction, ...):
  return direction == "UP"

g_dir_down(direction, ...):
  return direction == "DOWN"
```

### 3.13 Tight ribbon

```
g_tight_ribbon(direction, fire_us, asset):
  comp_bps = traders_reality_1s[asset].ribbon_compression_bps at (fire_us - 1_000_000)
  return comp_bps < 8.0   # ribbon spread < 8 bps = tight
```

---

## 4. Sleeve specifications (16 sleeves)

For each sleeve below, fire when ALL conditions evaluate True at `fire_us`.

---

### Sleeve 01 — BTC_5M_TS_MPSKEW_S6_0_60_V5

```
asset             = BTC
tf                = 5m
direction         = {UP, DOWN}   # both
slug_source       = "s6"          # S6 spike trigger only (production sleeve gate)
offset_s          = 30            # = "0-60" bin (offset 30s is canonical fire point in that bin)
window_s          = 300
spread_filter     = 0.02

precondition_sleeve_fires:
  the production S6 spike trigger must fire on this slug (existing production sleeve)

gates_all_must_pass:
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")
  g_mp_skew_with(direction, fire_us, slug)
```

Backtest reference (lockbox, $25): n=63 | WR 88.9% | $/tr +$12.41 | DD $84 | LS 2 | bs_p 0.002

---

### Sleeve 02 — BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5

```
asset             = BTC
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"          # NOT restricted to S6/S15 — any BTC 5m chainlink market
offset_s          = 30             # single offset, exactly 30s into slot
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")
  g_mp_skew_with(direction, fire_us, slug)
```

Backtest (lockbox, $25): n=132 | WR 87.1% | $/tr +$10.96 | DD $64 | LS 2 | bs_p 0.000

---

### Sleeve 03 — ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 120              # single offset, exactly 120s into slot
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_ema200(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_sms_liq_reclaim_with(direction, fire_us, asset="ETH", tf="5m")
  g_tr_in_active_session(direction, fire_us, asset="ETH")
```

Backtest (lockbox, $25): n=41 | WR 85.4% | $/tr +$6.27 | DD $25 | LS 1 | Sharpe 83.7 | bs_p 0.000 (clean) | 4 active days

---

### Sleeve 04 — ETH_5M_TR200_MP_MPNX_SMS_OFF120_V5

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 120
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_ema200(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_mp_no_extreme(direction, fire_us, slug)
  g_sms_liq_reclaim_with(direction, fire_us, asset="ETH", tf="5m")
```

Backtest (lockbox, $25): n=28 | WR 78.6% | $/tr +$7.71 | DD $25 | LS 1 | Sharpe 80.2 | bs_p 0.000 (clean) | 4 active days

---

### Sleeve 05 — ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 120
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_cloud(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_sms_liq_reclaim_with(direction, fire_us, asset="ETH", tf="5m")
  g_tr_in_active_session(direction, fire_us, asset="ETH")
```

Backtest (lockbox, $25): n=39 | WR 84.6% | $/tr +$5.85 | DD $50 | LS 2 | Sharpe 54.6 | bs_p 0.000 (clean) | 4 active days

---

### Sleeve 06 — SOL_5M_DEPTH_UP_HOD_SESSION_V5

```
asset             = SOL
tf                = 5m
direction         = UP            # UP-only
slug_source       = "any"
offset_s          ∈ {30, 60, 90}    # bin 30–90s
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_depth_250_strict(direction="UP", fire_us, slug)
  g_dir_up(direction)               # redundant — sleeve is UP-only
  g_hod_us_afternoon(direction, fire_us)
  g_tr_in_active_session(direction, fire_us, asset="SOL")
```

Backtest (lockbox, $25): n=51 | WR 90.2% | $/tr +$4.27 | DD $25 | LS 1 | bs_p 0.003 | $250 OK 100%

---

### Sleeve 07 — SOL_5M_RF_TR_PP_MID_V5

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {90, 120, 150, 180}    # bin 90–180s
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_rf_strict_align(direction, fire_us, asset="SOL")
  g_tr_above_ema200(direction, fire_us, asset="SOL")
  g_tr_above_pp(direction, fire_us, asset="SOL")
  g_tr_partial_stack_with(direction, fire_us, asset="SOL")
```

Backtest (lockbox, $25): n=31 | WR 90.3% | $/tr +$8.63 | DD $25 | LS 1 | bs_p 0.015

---

### Sleeve 08 — SOL_5M_RF_TR_PARTIAL_MID_V5

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {90, 120, 150, 180}
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_rf_strict_align(direction, fire_us, asset="SOL")
  g_tr_partial_stack_with(direction, fire_us, asset="SOL")
```

Backtest (lockbox, $25): n=50 | WR 84.0% | $/tr +$4.27 | DD $64 | LS 2 | bs_p 0.059 (above 0.05 — accept as borderline)

---

### Sleeve 09 — BTC_15M_TS_TRSTACK_OFF600_DOWN_V5

```
asset             = BTC
tf                = 15m
direction         = DOWN          # DOWN-only
slug_source       = "any"
offset_s          = 600           # exactly 10 minutes into 15m slot
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_dir_down(direction)            # redundant
  g_tr_stack_full_with(direction="DOWN", fire_us, asset="BTC")
  g_trend_slope_with(direction="DOWN", fire_us, asset="BTC", tf="15m")
```

Backtest (lockbox, $25): n=17 | WR 88.2% | $/tr +$6.16 | DD $25 | LS 1 | Sharpe 42.1 | bs_p 0.001

---

### Sleeve 10 — BTC_15M_REGIME_TRSTACK_OFF480_UP_V5

```
asset             = BTC
tf                = 15m
direction         = UP            # UP-only
slug_source       = "any"
offset_s          = 480           # 8 minutes into 15m slot
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_dir_up(direction)
  g_regime_stack_with(direction="UP", fire_us, asset="BTC", tf="15m")
  g_tr_stack_full_with(direction="UP", fire_us, asset="BTC")
```

Backtest (lockbox, $25): n=24 | WR 79.2% | $/tr +$5.71 | DD $66 | LS 2 | bs_p 0.001

---

### Sleeve 11 — BTC_15M_MPSKEW_TRSTACK_OFF600_DOWN_V5

```
asset             = BTC
tf                = 15m
direction         = DOWN
slug_source       = "any"
offset_s          = 600
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_dir_down(direction)
  g_mp_skew_strong_with(direction="DOWN", fire_us, slug)
  g_tr_stack_full_with(direction="DOWN", fire_us, asset="BTC")
```

Backtest (lockbox, $25): n=16 | WR 93.8% | $/tr +$8.39 | DD $25 | LS 1 | bs_p 0.001

---

### Sleeve 12 — BTC_15M_EMA50_EMA800_OFF600_DOWN_V5

```
asset             = BTC
tf                = 15m
direction         = DOWN
slug_source       = "any"
offset_s          = 600
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_dir_down(direction)
  g_tr_above_ema50(direction="DOWN", fire_us, asset="BTC")
  g_tr_above_ema800(direction="DOWN", fire_us, asset="BTC")
```

Backtest (lockbox, $25): n=64 | WR 76.6% | $/tr +$6.26 | DD $50 | LS 2 | bs_p 0.004

---

### Sleeve 13 — ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5

```
asset             = ETH
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {0, 30, 60}    # bin 0–60s ("offset_early")
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(direction, fire_us, slot_start_us)   # redundant given offset_s grid above
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
```

Backtest (lockbox, $25): n=26 | WR 88.5% | $/tr +$10.53 | DD $50 | LS 2 | Sharpe 35.1 | bs_p 0.0001

---

### Sleeve 14 — ETH_15M_TRSTACK_VWAP_OFFEARLY_V5

```
asset             = ETH
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {0, 30, 60}
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_offset_early(direction, fire_us, slot_start_us)
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
```

Backtest (lockbox, $25): n=60 | WR 75.0% | $/tr +$4.69 | DD $155 | LS 5 | bs_p 0.0001

---

### Sleeve 15 — SOL_15M_TRSTACK_VOL_RIBBON_EMA_MID_V5

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {120, 180, 240}    # bin 120–240s
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="SOL")
  g_vol_high(direction, fire_us, asset="SOL", tf="15m")
  g_ribbon_agrees(direction, fire_us, asset="SOL")
  g_tr_above_ema200(direction, fire_us, asset="SOL")
  g_tr_above_ema800(direction, fire_us, asset="SOL")
```

Backtest (full window, $25): n=47 | WR_full 76.6% | $/tr_full +$3.65 | DD_full $91 | LS_full 2 | bs_p_full 0.091 (borderline)

---

### Sleeve 16 — SOL_15M_RFAGED_TRSTACK_LATE_V5

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {480, 600, 720, 840}    # late window
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_rf_aged(direction, fire_us, asset="SOL")
  g_tr_stack_full_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")   # redundant given full_with passing, kept for parity with backtest
```

Backtest (lockbox, $25): n=29 | WR 96.6% | $/tr_lb +$4.30 / full +$0.91 | DD $25 lb / $237 full | LS 1 | bs_p 0.006

---

## 5. Sleeve registry — flat table

```
sleeve_id                                  asset tf   dir  offsets         spread  gate_count
01 BTC_5M_TS_MPSKEW_S6_0_60_V5                BTC   5m   BOTH 30              0.02     2 + S6 trigger
02 BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5           BTC   5m   BOTH 30              0.02     2
03 ETH_5M_TR200_MP_SMS_ACTIVE_OFF120_V5       ETH   5m   BOTH 120             0.02     4
04 ETH_5M_TR200_MP_MPNX_SMS_OFF120_V5         ETH   5m   BOTH 120             0.02     4
05 ETH_5M_CLOUD_MP_SMS_ACTIVE_OFF120_V5       ETH   5m   BOTH 120             0.02     4
06 SOL_5M_DEPTH_UP_HOD_SESSION_V5             SOL   5m   UP   30,60,90        0.025    4
07 SOL_5M_RF_TR_PP_MID_V5                     SOL   5m   BOTH 90,120,150,180  0.025    4
08 SOL_5M_RF_TR_PARTIAL_MID_V5                SOL   5m   BOTH 90,120,150,180  0.025    2
09 BTC_15M_TS_TRSTACK_OFF600_DOWN_V5          BTC   15m  DOWN 600             0.02     3
10 BTC_15M_REGIME_TRSTACK_OFF480_UP_V5        BTC   15m  UP   480             0.02     3
11 BTC_15M_MPSKEW_TRSTACK_OFF600_DOWN_V5      BTC   15m  DOWN 600             0.02     3
12 BTC_15M_EMA50_EMA800_OFF600_DOWN_V5        BTC   15m  DOWN 600             0.02     3
13 ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_V5       ETH   15m  BOTH 0,30,60         0.02     4
14 ETH_15M_TRSTACK_VWAP_OFFEARLY_V5           ETH   15m  BOTH 0,30,60         0.02     3
15 SOL_15M_TRSTACK_VOL_RIBBON_EMA_MID_V5      SOL   15m  BOTH 120,180,240     0.025    5
16 SOL_15M_RFAGED_TRSTACK_LATE_V5             SOL   15m  BOTH 480,600,720,840 0.025    3
```

## 6. Execution params (all sleeves)

```
notional_start_usd     = 5.0     # ramp from $5 initially
notional_max_usd       = 25.0    # cap at $25 — DO NOT exceed
notional_ramp_schedule = manual  # operator increases stake after 50 fires + WR within +/- 5pp of backtest

fill_method            = L25_book_walk
fill_max_levels        = 25
fill_size_calc         = notional_usd / vwap   # shares
fill_min_book_events   = 25      # skip slug if L25 has < 25 events in last 60s (sparse-book filter)

hold_to                = slot_end_us
slot_end_payout        = chainlink_resolution outcome
fee_model              = legacy_2pct_profit
  pnl_won  = (1.0 - vwap) * shares * 0.98
  pnl_lost = -vwap * shares

latency_budget_ms      = 85      # backtest uses 85ms latency; live should match or be lower
spread_filter          = per-sleeve (see above)
```

## 7. Shadow logging — required fields per fire

Every sleeve fire (whether placed or skipped) MUST emit a structured event with:

```
{
  event_type:           "sleeve_fire_eval" | "sleeve_fire_placed" | "sleeve_fire_resolved",
  sleeve_id:            "BTC_5M_TS_MPSKEW_ANY_OFFSET30_V5",
  slug:                 "btc-updown-5m-1779815400",
  asset:                "BTC",
  tf:                   "5m",
  direction:            "UP" | "DOWN",
  slot_start_us:        int,
  ws_s:                 int,
  fire_us:              int,
  fire_offset_s:        int,
  gates_evaluated:      {gate_name: bool, ...},
  all_gates_passed:     bool,
  skip_reason:          str | null,    # e.g., "g_trend_slope_strong_with=False"
  l25_book_snapshot:    {up_vwap, up_shares, dn_vwap, dn_shares, up_depth_usd, dn_depth_usd},
  intended_size_usd:    float,
  placed_size_usd:      float | null,
  fill_vwap:            float | null,
  fill_shares:          float | null,
  fill_latency_ms:      float | null,
  outcome:              "Up" | "Down" | null,
  pnl_usd:              float | null,
  resolution_source:    "chainlink"
}
```

Log to `tradingvenue.shadow_fires_2026_05_27` table or local jsonl `/var/log/tradingvenue/shadow_2026_05_27.jsonl`. Roll daily.

## 8. Comparison vs backtest

Weekly: aggregate live shadow fires per sleeve, compute live `(n, wr, $/tr, max_dd, loss_streak, sum)` and compare against backtest reference values (in §4 above). Flag any sleeve where live WR or $/tr deviates > 1 standard error of bootstrap CI.

## 9. Threshold constants (one-time precomputed at deploy)

These are derived from the May 1–22 training window. Recompute monthly.

```
trend_slope_p75_thr = {
  ("BTC","5m"):  0.385,
  ("ETH","5m"):  0.398,
  ("SOL","5m"):  0.412,
  ("BTC","15m"): 0.612,
  ("ETH","15m"): 0.624,
  ("SOL","15m"): 0.643,
}

vol_high_rv60_thr = {
  ("BTC","5m"):  0.0084,
  ("ETH","5m"):  0.0109,
  ("SOL","5m"):  0.0142,
  ("BTC","15m"): 0.0162,
  ("ETH","15m"): 0.0203,
  ("SOL","15m"): 0.0271,
}

mp_no_extreme_bps_thr = 100.0
mp_skew_strong_bps_thr = 50.0
cci_strong_thr         = 100.0
ribbon_tight_bps_thr   = 8.0
near_pivot_pct_thr     = 0.005
rf_aged_min_s          = 60
rf_fresh_max_s         = 60
hod_us_afternoon_utc   = [18, 19, 20, 21, 22]   # inclusive
offset_early_max_s     = 60
depth_supports_250_min_usd = 1500.0
depth_250_strict_other_min_usd = 750.0
sparse_book_min_events_60s = 25
```

## 10. Open items — flagged for follow-up

1. **RESOLVED 2026-05-27** — Sleeves 03/04/05 (ETH 5m) re-validated with fixed bootstrap calc. All 3 have bs_p = 0.000 on clean re-run. Spec swapped from the original 5/7/8-gate `ribbon+sms+tr+depth_250` stacks to single-offset_120s `mp_skew + sms_liq_reclaim + tr_above_(ema200|cloud) [+ tr_in_active_session | + mp_no_extreme]` family. No new gate logic needed — all gates already in §3.

2. **Sleeve 06 (SOL 5m S2) is UP-only** — flagged as possible 9-day artifact. Monitor live WR carefully; if WR < 80% over first 30 fires, suspend.

3. **Sleeve 16 (SOL 15m C3)** has full-window $/tr +$0.91 (lockbox +$4.30) — keep stake at $5 and treat as exploratory.

4. **`g_above_1h_dailyvwap_with` (Sleeves 13, 14)** depends on a live-computed daily VWAP from binance 1m. TV must have a daily-VWAP service running with at-fire-time computation; verify rebuild logic matches backtest definition (anchored at 00:00 UTC).

5. **`g_sms_*` gates (Sleeves 03, 04, 05)** depend on `sms_panel_v2_fixed` being computed live from 1s closes. TV needs a 5m-bar liquidity/CHoCH/BOS computer running per-asset. If not available, these 3 ETH sleeves cannot deploy until built.

6. **`g_book_depth_supports_250` is no longer needed** — operator decided not to scale to $250. Replace with `g_book_depth_supports_25` (>$150 cumulative depth) which trivially passes for almost all fires. Effectively a no-op gate.

---

## NEXT ROUND DIRECTIVES (for the search team, not for TV)

For the NEXT sniper search round, the strict sniper bar is relaxed per operator:

- **Drop the loss-streak constraint** to ≤ 14 (was ≤ 6). Higher streak OK if compensated by higher $/tr.
- **Drop $250 viability** — never use $250 notional. Use $5–25 only. Discontinue `g_book_depth_supports_250` and `g_depth_250_strict` as primary gates.
- **Variable sizing (Kelly fraction)**: for each fire, compute a per-fire conviction score (e.g., number of gates passing, or weighted-gate score). Map score to stake:
  - score = MIN_GATES (e.g., 3 of 8) → stake = $5
  - score = ALL_GATES (e.g., 8 of 8) → stake = $25
  - In between → Kelly-fraction linear interpolation: `stake = $5 + ($25 - $5) * (score - MIN) / (MAX - MIN)`
  - Use a fractional Kelly (e.g., 0.25 * full Kelly) to avoid blow-up risk on overfit sleeves.
- **Compose gates more aggressively**: 6–10 gate stacks are encouraged. Don't fear small n if conviction is high — n=50 with WR 92% is fine.
- **Higher $/tr is the primary objective.** Maximize $/tr while keeping cumulative DD < 30% of cumulative profit.
- **Add gate-weighted ensemble candidates**: don't require ALL gates to pass; instead, weight-sum gates and fire when total > threshold. This produces fewer-but-bigger trades.
- **Per-market, not pooled** (already followed in this round).
- **No $250 backtest needed** (saves 30% of agent runtime).

---

## END
