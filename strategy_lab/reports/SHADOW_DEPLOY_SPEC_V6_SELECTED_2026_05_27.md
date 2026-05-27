# Shadow Deploy Spec — 14 V6 Sleeves (Selected) — 2026-05-27

Operator-selected V6 sleeves for TV shadow implementation on VPS3. Self-contained: gate definitions, exact sleeve logic, execution params, logging schema.

Companion to [SHADOW_DEPLOY_SPEC_2026_05_27.md](./SHADOW_DEPLOY_SPEC_2026_05_27.md) (V5 deploy spec, 16 sleeves). All V6 sleeve IDs end with `_V6` for dashboard separation.

---

## 0. Engine constants

```
notional_default_usd  = 25.0     # constant default (Kelly proved counterproductive)
notional_ramp_start   = 5.0      # operator may start at $5-8 and ramp
fee_model             = legacy_2pct_profit   # 2% on profit (winning leg only)
spread_filter_btc     = 0.02
spread_filter_eth     = 0.02
spread_filter_sol     = 0.025
window_s_5m           = 300
window_s_15m          = 900
fill_engine           = L25_book_walk
fill_min_book_events  = 25       # sparse-book filter
hold_to               = slot_end_us
exit_policy           = HOLD_TO_SLOT_END   # NO SL / NO TP / NO mid-slot exit
latency_budget_ms     = 85
mode                  = paper    # all sleeves start mode="paper"
```

## 1. Anchor + timing conventions

```
slot_start_us = chainlink resolution slot start (UTC microseconds)
window_s      = 300 (5m) or 900 (15m)
ws_s          = slot_start_us // 1_000_000 - window_s          # signal anchor
fire_us       = slot_start_us + offset_s * 1_000_000           # entry time
slot_end_us   = slot_start_us + window_s * 1_000_000           # exit time
```

- Pre-window gates (prefix `g_pw_*`): evaluate at `ts_us = ws_s * 1_000_000`
- Intra-window gates: evaluate at `ts_us <= fire_us - 1_000_000` (1s epsilon)
- Per-bar panel asof: `merge_asof(direction="backward", allow_exact_matches=True)`
- Per-bar panel `ts_us` is bar END (use `_v2_fixed` variants)

## 2. Direction handling

For each candidate fire, evaluate BOTH directions UP and DOWN unless sleeve restricts via `g_dir_up` or `g_dir_down`. Each direction independently passes/fails all gates.

If all gates pass → place taker order on matching outcome token at L25 vwap, size = `notional_usd / vwap` shares. Hold to slot_end.

PnL:
- `pnl_won  = (1 - vwap) * shares * 0.98`
- `pnl_lost = -vwap * shares`

## 3. Gate library — EXACT formulas (only gates used by the 14 selected sleeves)

### 3.1 — L25 book gates (FILL-TIME veto)

```python
g_book_supports_stake(direction, fire_us, slug, stake_usd):
  # MANDATORY for every V6 fire. Cancel order if depth insufficient.
  side = "UP" if direction=="UP" else "DOWN"
  cum_depth_usd = sum(price_i * size_i for ask_i in L25[side] up to top 25 levels)
  return cum_depth_usd > 6 * stake_usd
  # For stake=$25 → depth > $150
  # For stake=$5  → depth > $30
```

### 3.2 — Regime / trend gates (source: regime_panel_{tf}_v2_fixed.parquet)

```python
trend_slope_30m(asset, tf, ts):
  bars_back  = 30 // (5 if tf=="5m" else 15)
  close_now  = panel[asset, tf].close at ts
  close_back = panel[asset, tf].close at (ts - bars_back bars)
  atr_60m    = panel[asset, tf].atr_14
  return (close_now - close_back) / atr_60m

g_pw_trend_slope_with(direction, ws_s, asset, tf):
  # PRE-WINDOW: anchor at ws_s, NOT fire_us
  ts = asof_bar_end(asset, tf, ws_s * 1_000_000)
  s  = trend_slope_30m(asset, tf, ts)
  if s is NaN: return False
  return (s > 0 and direction=="UP") or (s < 0 and direction=="DOWN")
```

### 3.3 — Microprice gates (source: microprice_panel.parquet)

```python
mp_skew(fire_us, slug):
  mp_up = microprice_panel[slug, side=UP].weighted_microprice at fire_us
  mp_dn = microprice_panel[slug, side=DOWN].weighted_microprice at fire_us
  return (mp_up - mp_dn) * 10000   # in basis points

g_mp_skew_with(direction, fire_us, slug):
  s = mp_skew(fire_us - 1_000_000, slug)
  if s is NaN: return False
  return (s > 0 and direction=="UP") or (s < 0 and direction=="DOWN")

g_mp_skew_strong_with(direction, fire_us, slug):
  s = mp_skew(fire_us - 1_000_000, slug)
  if s is NaN: return False
  thr_bps = 50.0
  return abs(s) > thr_bps AND sign(s) matches direction

g_mp_no_extreme_150(direction, fire_us, slug):
  s = mp_skew(fire_us - 1_000_000, slug)
  return abs(s) < 150.0
```

### 3.4 — Range filter (source: range_filter_1s.parquet)

```python
g_rf_with(direction, fire_us, asset):
  rf_dir = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)
  return (rf_dir==1 and direction=="UP") or (rf_dir==-1 and direction=="DOWN")
```

### 3.5 — Traders' Reality / EMA / ribbon / session (source: traders_reality_1s.parquet)

```python
g_tr_above_ema50(direction, fire_us, asset):
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  ema   = traders_reality_1s[asset].ema_50 at (fire_us - 1_000_000)
  return (close > ema and direction=="UP") or (close < ema and direction=="DOWN")

g_tr_above_ema200(direction, fire_us, asset):  # same pattern with ema_200
g_tr_above_ema800(direction, fire_us, asset):  # same pattern with ema_800

g_tr_above_cloud(direction, fire_us, asset):
  ssa = traders_reality_1s[asset].ssa at (fire_us - 1_000_000)
  ssb = traders_reality_1s[asset].ssb at (fire_us - 1_000_000)
  close = traders_reality_1s[asset].close at (fire_us - 1_000_000)
  cloud_top = max(ssa, ssb); cloud_bot = min(ssa, ssb)
  return (close > cloud_top and direction=="UP") or (close < cloud_bot and direction=="DOWN")

g_tr_stack_with(direction, fire_us, asset):
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score >= 1 and direction=="UP") or (score <= -1 and direction=="DOWN")

g_tr_stack_full_with(direction, fire_us, asset):
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score == 2 and direction=="UP") or (score == -2 and direction=="DOWN")

g_tr_partial_stack_with(direction, fire_us, asset):
  score = traders_reality_1s[asset].tr_ema_stack_score at (fire_us - 1_000_000)
  return (score == 1 and direction=="UP") or (score == -1 and direction=="DOWN")

g_tr_in_active_session(direction, fire_us, asset):
  count = traders_reality_1s[asset].tr_active_session_count at (fire_us - 1_000_000)
  return count >= 1

g_ribbon_agrees(direction, fire_us, asset):
  color = traders_reality_1s[asset].ribbon_color at (fire_us - 1_000_000)
  return (color=="green" and direction=="UP") or (color=="red" and direction=="DOWN")

g_ribbon_slope_with(direction, fire_us, asset):
  slope_bps = traders_reality_1s[asset].ribbon_lead_slope_bps at (fire_us - 1_000_000)
  return (slope_bps > 0 and direction=="UP") or (slope_bps < 0 and direction=="DOWN")

g_tight_ribbon(direction, fire_us, asset):
  comp_bps = traders_reality_1s[asset].ribbon_compression_bps at (fire_us - 1_000_000)
  return comp_bps < 8.0
```

### 3.6 — TA / momentum indicators (source: ta_indicators_1s.parquet)

```python
g_mfi_with(direction, fire_us, asset):
  mfi = ta_indicators_1s[asset].mfi_60s at (fire_us - 1_000_000)
  return (mfi > 50 and direction=="UP") or (mfi < 50 and direction=="DOWN")

g_cci_strong_with(direction, fire_us, asset):
  cci = ta_indicators_1s[asset].cci_60s at (fire_us - 1_000_000)
  if cci is NaN: return False
  return (cci > 100 and direction=="UP") or (cci < -100 and direction=="DOWN")

g_bb_pos_with(direction, fire_us, asset):
  bbp = ta_indicators_1s[asset].bb_pos_60s at (fire_us - 1_000_000)
  if direction=="UP":   return bbp > 0.55
  else:                 return bbp < 0.45
```

### 3.7 — SMS / liquidity (source: sms_panel_{tf}_v2_fixed.parquet)

```python
g_sms_liq_reclaim_with(direction, fire_us, asset, tf):
  ts = asof_bar_end(asset, tf, fire_us)
  reclaim_dir = sms_panel[asset, tf].liq_reclaim_dir at ts   # in {1, -1, 0}
  return (reclaim_dir==1 and direction=="UP") or (reclaim_dir==-1 and direction=="DOWN")
```

### 3.8 — Hurst / vol gates (source: vol_hurst_at_fire_{5m,15m}.parquet)

```python
g_hurst_trending(direction, fire_us, asset, tf):
  hurst = vol_hurst_at_fire[asset, tf].hurst_60 at slot_start_us
  return hurst > 0.50   # R7-recalibrated threshold

g_vol_high(direction, fire_us, asset, tf):
  rv_60 = vol_hurst_at_fire[asset, tf].rv_60 at slot_start_us
  thr = pre-computed quantile @ p=0.75 of training window.
  # Reference values (train May 1-22):
  #   BTC 5m=0.0084  ETH 5m=0.0109  SOL 5m=0.0142
  #   BTC 15m=0.0162 ETH 15m=0.0203 SOL 15m=0.0271
  return rv_60 > thr
```

### 3.9 — Hawkes (source: hawkes_panel.parquet)

```python
g_hawkes_imb_loose_with(direction, fire_us, asset):
  imb = hawkes_panel[asset].lambda_imbalance at (fire_us - 1_000_000)
  thr = 0.10   # loose variant (V5 was 0.30 strong)
  return (imb > thr and direction=="UP") or (imb < -thr and direction=="DOWN")
```

### 3.10 — F7 RSI gate (source: master_gate_features_v2.parquet column `f7_rsi_at_ws`)

```python
g_f7_rsi_with(direction, ws_s, asset):
  # F7 RSI computed at ws_s (Wilder simple-mean RSI, 7-period, 60s sample)
  rsi = f7_rsi_at_ws_lookup(asset, ws_s)
  # Direction-with: RSI extreme matches direction
  if direction=="UP":   return rsi > 70 OR rsi < 30   # extreme zone
  else:                  return rsi > 70 OR rsi < 30
  # NOTE: production momo uses "RSI > 70 → DOWN bias, RSI < 30 → UP bias"
  # but g_f7_rsi_with in V6 is direction-agnostic extreme presence.
  # Per agent code, the gate fires when RSI is in extreme zone regardless of direction
  # combined with other directional gates.
```

### 3.11 — 1h daily-VWAP gate (build live from binance 1m)

```python
above_1h_dailyvwap(asset, fire_us):
  day_start_us = floor(fire_us, 1 day UTC)
  bars = binance_1m[asset] where ts_us in [day_start_us, fire_us - 1_000_000)
  vwap = sum(close * volume) / sum(volume)
  close = binance_1m[asset].close at (fire_us - 1_000_000)
  return close > vwap

g_above_1h_dailyvwap_with(direction, fire_us, asset):
  above = above_1h_dailyvwap(asset, fire_us)
  return (above and direction=="UP") or (not above and direction=="DOWN")
```

### 3.12 — Offset / time-of-day gates

```python
g_offset_early(fire_us, slot_start_us):
  return 0 <= (fire_us - slot_start_us)/1e6 <= 60

g_off_60_240(fire_us, slot_start_us):
  s = (fire_us - slot_start_us)/1e6
  return 60 <= s <= 240

g_hod_european_morning(fire_us):
  hour_utc = (fire_us // 1_000_000 // 3600) % 24
  return 7 <= hour_utc <= 11   # 07:00-11:00 UTC

g_dir_down(direction, ...):
  return direction == "DOWN"

g_dir_up(direction, ...):
  return direction == "UP"
```

### 3.13 — Entry-VWAP band filters (computed from L25 book walk at fire_us)

```python
g_entry_vwap_in_band(direction, fire_us, slug):
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return 0.20 <= vwap_book <= 0.80

g_entry_vwap_in_30_70(direction, fire_us, slug):
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return 0.30 <= vwap_book <= 0.70

g_vwap_in_45_85(direction, fire_us, slug):
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return 0.45 <= vwap_book <= 0.85

g_vwap_in_55_80(direction, fire_us, slug):
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return 0.55 <= vwap_book <= 0.80

g_vwap_premium(direction, fire_us, slug):
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  return vwap_book >= 0.55
```

---

## 4. The 14 selected sleeve specifications

For each: fire when ALL listed gates pass at the specified anchor. Then run `g_book_supports_stake` as FILL-TIME veto.

---

### Sleeve 01 — ETH_5M_CLOUD_RIBBON_MP_HURST_V6 🎯 ETH 5m PRIMARY

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 60                  # single offset
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_cloud(direction, fire_us, asset="ETH")
  g_ribbon_agrees(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")

fill_time_veto:
  g_book_supports_stake(direction, fire_us, slug, stake=notional_default_usd)
```

Backtest reference: train n=187 WR 78.6% / val n=129 WR 83.7% / lockbox n=165 WR 83.6% | $/tr_lb +$8.44 | DD $93 | LS 2 | bs_p 0.000 | 28d $2,213.

---

### Sleeve 02 — ETH_5M_V5_REPL_OFF120_V6

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
  g_sms_liq_reclaim_with(direction, fire_us, asset="ETH", tf="5m")
  g_tr_in_active_session(direction, fire_us, asset="ETH")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=67 WR 89.5% / val n=28 WR 82.1% / lockbox n=25 WR 88.0% | $/tr_lb +$6.49 | DD $25 | LS 1 | bs_p 0.000 | 28d $431.

NOTE: replicates V5 sleeve 03/04/05 family. If V5 sleeves are already deployed, this sleeve produces duplicate fires — coordinate before enabling both.

---

### Sleeve 03 — ETH_5M_BB_MP_HURST_BAND_V6

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 60
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_bb_pos_with(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")
  g_entry_vwap_in_band(direction, fire_us, slug)      # [0.20, 0.80]

fill_time_veto: g_book_supports_stake
```

Backtest: train n=40 WR 65.0% / val n=40 WR 67.5% / lockbox n=82 WR 81.7% | $/tr_lb +$14.12 | DD $50 | LS 2 | bs_p 0.000 | 28d $1,598.

---

### Sleeve 04 — SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6 🎯 SOL 5m PRIMARY

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {30, 60, 90, 120, 150, 180, 210, 240}
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_cci_strong_with(direction, fire_us, asset="SOL")
  g_f7_rsi_with(direction, ws_s, asset="SOL")          # PRE-WINDOW gate, evaluate at ws_s
  g_mfi_with(direction, fire_us, asset="SOL")
  g_tr_partial_stack_with(direction, fire_us, asset="SOL")
  g_vwap_in_45_85(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=61 WR 80.3% $/tr +$3.10 | val n=38 WR 78.9% $/tr +$2.78 | lockbox n=87 WR 83.9% $/tr +$4.62 | DD $92 | LS 3 | bs_p 0.001 | 28d $402.

---

### Sleeve 05 — SOL_5M_F7_MP_EMA200_VWAP_V6

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {30, 60, 90, 120, 150, 180, 210, 240}
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_f7_rsi_with(direction, ws_s, asset="SOL")          # PRE-WINDOW
  g_mp_no_extreme_150(direction, fire_us, slug)
  g_tr_above_ema200(direction, fire_us, asset="SOL")
  g_vwap_in_55_80(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=64 WR 76.6% $/tr +$2.87 | val n=32 WR 78.1% $/tr +$2.65 | lockbox n=95 WR 82.1% $/tr +$4.23 | DD $96 | LS 3 | bs_p 0.001 | 28d $402.

---

### Sleeve 06 — SOL_5M_F7_MFI_EMA200_VWAP_V6

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {30, 60, 90, 120, 150, 180, 210, 240}
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_f7_rsi_with(direction, ws_s, asset="SOL")          # PRE-WINDOW
  g_mfi_with(direction, fire_us, asset="SOL")
  g_tr_above_ema200(direction, fire_us, asset="SOL")
  g_vwap_in_55_80(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=41 WR 75.6% $/tr +$2.03 | val n=27 WR 77.8% $/tr +$2.40 | lockbox n=78 WR 83.3% $/tr +$4.66 | DD $64 | LS 2 | bs_p 0.004 | 28d $363.

---

### Sleeve 07 — ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6 🎯 ETH 15m PRIMARY

```
asset             = ETH
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {0, 30, 60}        # offset_early
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(fire_us, slot_start_us)
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_entry_vwap_in_30_70(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=51 WR 70.6% / val n=13 WR 69.2% / lockbox n=26 WR 84.6% | $/tr_lb +$10.72 | DD $100 | LS 4 | bs_p 0.000 | sum_4d_lb $279 ≈ 28d $1,953.

---

### Sleeve 08 — ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6 🎯 PRE-WINDOW WINNER

```
asset             = ETH
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {0, 30, 60}        # offset_early
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(fire_us, slot_start_us)
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_pw_trend_slope_with(direction, ws_s, asset="ETH", tf="15m")    # PRE-WINDOW at ws_s

fill_time_veto: g_book_supports_stake
```

Backtest: train n=38 WR 79.0% / val n=7 WR 57.1% / lockbox n=18 WR **94.4%** | $/tr_lb +$11.27 | DD $61 | LS 2 | bs_p 0.000 | sum_4d_lb $203 ≈ 28d $1,421.

**NOTE — production momo replication target**: this sleeve uses the SAME ws_s anchor as production poly_updown_loop.py `build_bar_context_t_plus_60`. If shadow data matches backtest, this validates the V6 pre-window thesis for 15m markets and unlocks more pre-window sleeves in V7.

---

### Sleeve 09 — BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6

```
asset             = BTC
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 600
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_vwap_premium(direction, fire_us, slug)
  g_tr_above_ema50(direction, fire_us, asset="BTC")
  g_mp_skew_with(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=195 WR 69.2% / val n=74 WR 68.9% / lockbox n=44 WR 81.8% | $/tr_lb +$6.77 | DD $50 | LS 2 | bs_p 0.001 | 28d $2,086.

---

### Sleeve 10 — BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6 🎯 BTC 15m PRIMARY

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
  g_tr_above_ema200(direction="DOWN", fire_us, asset="BTC")
  g_mp_skew_strong_with(direction="DOWN", fire_us, slug)
  g_rf_with(direction="DOWN", fire_us, asset="BTC")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=202 WR 63.4% / val n=71 WR 62.0% / lockbox n=34 WR 85.3% | $/tr_lb +$11.81 | DD $72 | LS 2 | bs_p 0.001 | 28d $2,810.

---

### Sleeve 11 — BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6

```
asset             = BTC
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 840
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_ema800(direction, fire_us, asset="BTC")
  g_ribbon_slope_with(direction, fire_us, asset="BTC")
  g_hawkes_imb_loose_with(direction, fire_us, asset="BTC")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=74 WR 63.5% / val n=22 WR 59.1% / lockbox n=21 WR 66.7% | $/tr_lb +$16.28 | DD $94 | LS 3 | bs_p 0.041 (borderline) | 28d $2,392.

⚠ bs_p near threshold (0.041 vs 0.05 cutoff). Monitor first 50 fires for WR drift; suspend if WR < 55%.

---

### Sleeve 12 — SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6 🎯 SOL 15m PRIMARY

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {60, 120, 240}
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  vwap_book < 0.80

fill_time_veto: g_book_supports_stake
```

Backtest: train n=183 WR 68.9% $/tr +$2.89 | val n=53 WR 71.7% $/tr +$2.57 | lockbox n=49 WR 71.4% $/tr +$4.12 | full n=285 $/tr_full +$3.04 | DD_lb $100 / DD_full $220 | LS 4 | bs_p 0.004 | sum_lb $202.

---

### Sleeve 13 — SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP30_70_V6

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {60, 120, 240}
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  g_entry_vwap_in_30_70(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=149 WR 69.1% $/tr +$4.16 | val n=39 WR 66.7% $/tr +$2.30 | lockbox n=38 WR 65.8% $/tr +$3.82 | full n=226 $/tr_full +$3.78 | DD_lb $100 | LS 4 | sum_lb $145.

---

### Sleeve 14 — SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = ALL (no offset restriction; fires at any 15m offset)
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tight_ribbon(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  vwap_book < 0.80

fill_time_veto: g_book_supports_stake
```

Backtest: train n=276 WR 69.2% $/tr +$4.42 | val n=75 WR 65.3% $/tr +$0.87 ⚠ | lockbox n=72 WR 68.1% $/tr +$2.11 | full n=423 $/tr_full +$3.40 | DD_lb $125 | LS 5 | sum_lb $152.

⚠ Val $/tr collapsed to +$0.87. Sleeve is exploratory — deploy at $5 stake, observe.

---

## 5. Sleeve registry — flat table

```
#  sleeve_id                                            asset tf   dir   offsets         spread  gates  status
01 ETH_5M_CLOUD_RIBBON_MP_HURST_V6                     ETH   5m   BOTH  60              0.02     4      DEPLOY 🎯
02 ETH_5M_V5_REPL_OFF120_V6                            ETH   5m   BOTH  120             0.02     4      DEPLOY (V5 dup)
03 ETH_5M_BB_MP_HURST_BAND_V6                          ETH   5m   BOTH  60              0.02     4      DEPLOY
04 SOL_5M_CCI_F7_MFI_PARTIAL_VWAP_V6                   SOL   5m   BOTH  30-240          0.025    5      DEPLOY 🎯
05 SOL_5M_F7_MP_EMA200_VWAP_V6                         SOL   5m   BOTH  30-240          0.025    4      DEPLOY
06 SOL_5M_F7_MFI_EMA200_VWAP_V6                        SOL   5m   BOTH  30-240          0.025    4      DEPLOY
07 ETH_15M_TRSTACK_VWAP_VOL_OFFEARLY_BAND_V6           ETH   15m  BOTH  0/30/60         0.02     5      DEPLOY 🎯
08 ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6  ETH   15m  BOTH  0/30/60 + ws_s  0.02     5      DEPLOY (PW)
09 BTC_15M_VWAPPREM_EMA50_MPSKEW_OFF600_V6             BTC   15m  BOTH  600             0.02     3      DEPLOY
10 BTC_15M_EMA200_MPSKEW_RF_OFF600_DOWN_V6             BTC   15m  DOWN  600             0.02     3      DEPLOY 🎯
11 BTC_15M_EMA800_RIBSLP_HAWKES_OFF840_V6              BTC   15m  BOTH  840             0.02     3      DEPLOY (borderline)
12 SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP80_V6            SOL   15m  BOTH  60/120/240      0.025    4+vwap DEPLOY 🎯
13 SOL_15M_HOD_EU_OFF60_240_RF_TR_VWAP30_70_V6         SOL   15m  BOTH  60/120/240      0.025    5      DEPLOY
14 SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6             SOL   15m  BOTH  ALL             0.025    4+vwap DEPLOY @ $5
```

## 6. Execution params (same for all 14 sleeves)

```
notional_default_usd  = 25.0       # may ramp from $5
notional_max_usd      = 25.0       # absolute cap — DO NOT exceed
fill_method           = L25_book_walk
fill_max_levels       = 25
fill_size_calc        = notional_usd / vwap   # shares
fill_min_book_events  = 25          # sparse-book filter

hold_to               = slot_end_us
slot_end_payout       = chainlink_resolution outcome
fee_model             = legacy_2pct_profit
  pnl_won  = (1.0 - vwap) * shares * 0.98
  pnl_lost = -vwap * shares

latency_budget_ms     = 85
spread_filter         = per-sleeve (see above)

# MANDATORY for ALL V6 sleeves
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=notional_usd)
                      # Cancel order if L25 cumulative depth on chosen side < 6 × notional
```

## 7. Shadow logging — required fields per fire

Every sleeve fire (whether placed or skipped) MUST emit a structured event:

```json
{
  "event_type":              "sleeve_fire_eval | sleeve_fire_placed | sleeve_fire_resolved",
  "sleeve_id":               "ETH_5M_CLOUD_RIBBON_MP_HURST_V6",
  "version_tag":             "V6",
  "slug":                    "eth-updown-5m-1779815400",
  "asset":                   "ETH",
  "tf":                      "5m",
  "direction":               "UP|DOWN",
  "slot_start_us":           1779815400000000,
  "ws_s":                    1779815100,
  "fire_us":                 1779815460000000,
  "fire_offset_s":           60,
  "gates_evaluated":         {"g_tr_above_cloud": true, "g_ribbon_agrees": true, ...},
  "all_gates_passed":        true,
  "skip_reason":             null,
  "depth_check_passed":      true,
  "depth_observed_usd":      482.1,
  "stake_requested_usd":     25.0,
  "stake_applied_usd":       25.0,
  "l25_book_snapshot":       {"up_vwap": 0.612, "up_shares": 40.8, "up_ask0": 0.610, ...},
  "fill_vwap":               0.612,
  "fill_shares":             40.85,
  "fill_latency_ms":         62,
  "outcome":                 "Up",
  "pnl_usd":                 15.51,
  "resolution_source":       "chainlink"
}
```

Log to `tradingvenue.shadow_fires_v6_2026_05_27` table or `/var/log/tradingvenue/shadow_v6_2026_05_27.jsonl`. Roll daily.

## 8. Weekly comparison vs backtest

For each sleeve, aggregate live shadow fires per week and compute live `(n, wr, $/tr, max_dd, loss_streak, sum)`. Compare against backtest reference values in §4. Flag any sleeve where live WR or $/tr deviates > 1 standard error of bootstrap CI for 2 consecutive weeks.

## 9. Threshold constants (precomputed at deploy, recompute monthly)

```python
hurst_trending_thr       = 0.50
mp_skew_strong_bps_thr   = 50.0
mp_no_extreme_150_bps    = 150.0
cci_strong_thr           = 100.0
ribbon_tight_bps_thr     = 8.0
hawkes_imb_loose_thr     = 0.10

vwap_band_default        = [0.20, 0.80]
vwap_band_30_70          = [0.30, 0.70]
vwap_band_45_85          = [0.45, 0.85]
vwap_band_55_80          = [0.55, 0.80]
vwap_premium_min         = 0.55

hod_european_morning_utc = [7, 8, 9, 10, 11]
offset_early_max_s       = 60

vol_high_rv60_thr = {
  ("BTC","5m"):  0.0084,
  ("ETH","5m"):  0.0109,
  ("SOL","5m"):  0.0142,
  ("BTC","15m"): 0.0162,
  ("ETH","15m"): 0.0203,
  ("SOL","15m"): 0.0271,
}

f7_rsi_at_ws_extreme_upper = 70
f7_rsi_at_ws_extreme_lower = 30

depth_supports_stake_multiplier = 6   # depth must exceed 6 × stake_usd
```

## 10. Open items — flagged for follow-up

1. **Sleeve 02 (ETH 5m V5 replicated)** — if V5 sleeves 03/04/05 are already deployed and live, this sleeve produces duplicate fires on the same slugs. Coordinate enable/disable to avoid double-counting.

2. **Sleeve 08 (ETH 15m PRE-WINDOW)** — first V6 sleeve where ws_s anchor outperforms (94.4% vs 84.6% same gates at fire_us). Production momo team should compare against their existing ws_s-anchored sleeves; if WR delta confirms, this gate (`g_pw_trend_slope_with`) should be added to production momo's sleeve menu.

3. **Sleeve 11 (BTC 15m off840 borderline)** — bs_p=0.041 vs 0.05 cutoff. Monitor first 50 fires for WR drift. Suspend if WR < 55%.

4. **Sleeve 14 (SOL 15m TIGHTRIB)** — val $/tr collapsed to $0.87 (positive but borderline). Deploy at $5 stake only. Re-evaluate after 100 fires.

5. **`g_f7_rsi_with` (sleeves 04, 05, 06)** — production momo controller already computes F7 RSI at ws_s. TV should reuse the existing computation, NOT roll a new one. Wilder simple-mean RSI, 7-period, 60s sample interval, last close at ws_s.

6. **`g_above_1h_dailyvwap_with` (sleeves 07, 08)** — requires live daily-VWAP service from binance 1m, anchored at 00:00 UTC. If not running on TV, must build before deploy.

7. **`g_hurst_trending` (sleeves 01, 03)** — requires live Hurst exponent computation over 60-bar window per asset/tf. If not running, must build before deploy. Reference threshold = 0.50.

8. **`g_book_supports_stake` fill-time veto** — must be implemented as ORDER-CANCEL check at fire_us, not as search-time gate. If L25 depth insufficient at fire_us, log `depth_check_passed=false` and DO NOT place order.

---

## END (V6 14-sleeve spec)
