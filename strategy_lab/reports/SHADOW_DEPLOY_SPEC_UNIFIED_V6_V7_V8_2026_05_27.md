# Shadow Deploy Spec — UNIFIED V6 + V7 + V8 (Combined) — 2026-05-27

Combined deployment manifest for all operator-selected sleeves across V6 + V7 + V8 rounds.

---

## 📋 REQUIRED READING — all 4 spec docs for full implementation

| Round | # sleeves | Status | Spec doc (absolute path) |
|---|---:|---|---|
| **V5** | 16 | ALREADY DEPLOYED | `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports\SHADOW_DEPLOY_SPEC_2026_05_27.md` |
| **V6 selected** | 14 | IN SHADOW | `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports\SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md` |
| **V7 selected** | 12 | IN SHADOW (being implemented) | `C:\Users\alexandre bandarra\Desktop\global\strategy_lab\reports\SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md` |
| **V8 selected** | 14 | TO IMPLEMENT | THIS FILE §4 |
| **TOTAL** | **56** (52 unique after V8/V7 dedup) | — | — |

### TV implementation plan
1. **V5 stays as deployed** — no changes
2. **V6 selected** — already being implemented; reference V6 spec doc for §3 gate definitions and §4 sleeve specs
3. **V7 selected** — already being implemented; reference V7 spec doc (uses some gates introduced in V7 §3; check V7 §3.x for definitions of gates like `g_parent_15m_regime_with`, `g_hurst_reverting`, `g_btc_f7_against`, `g_xa_3source_trend_with`, `g_pw_btc_15m_trend_with`, `g_BTC_slope_with`, etc.)
4. **V8 selected (NEW)** — implement from THIS doc §4 sleeve specs. NEW V8 gates defined in §3 of this doc (1h grandparent regime, 2-asset/3-asset confluence, TOD buckets, liquidity shock, Path Q prev-15m gate, cross-asset overlays)

### Gate library inheritance order
- V5 base gates → V5 spec §3
- V6 added gates → V6 spec §3
- V7 added gates → V7 spec §3
- V8 added gates → THIS doc §3
- TV must implement gates from ALL 4 spec docs

### Shared conventions (defined ONCE in this doc §0-2)
- Engine constants, anchor conventions, direction handling, stake convention (NOTIONAL = $25, do NOT multiply `pnl_legacy_usd` by 25), fill-time veto
- Apply to V6 + V7 + V8 sleeves uniformly
- V5 sleeves use the same conventions (already deployed)

---

## 📁 This doc structure

- §0-2: shared engine constants and conventions
- §3: NEW V8 gates implementation
- §4: V8 sleeve specs (14 new sleeves)
- §5: Combined registry (V5 + V6 + V7 + V8 = 56 sleeves)
- §6-7: execution + shadow logging
- §8: caveats + duplicates flagged

---

## 0. Engine constants (UNCHANGED across all versions)

```
notional_default_usd  = 25.0
notional_ramp_start   = 5.0
fee_model             = legacy_2pct_profit
spread_filter_btc     = 0.02
spread_filter_eth     = 0.02
spread_filter_sol     = 0.025
window_s_5m           = 300
window_s_15m          = 900
fill_engine           = L25_book_walk
fill_min_book_events  = 25
hold_to               = slot_end_us
exit_policy           = HOLD_TO_SLOT_END
latency_budget_ms     = 85
mode                  = paper

# MANDATORY for V6/V7/V8 (NOT V5)
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=25.0)
                      # Cancel order if L25 cumulative depth on chosen side < $150 (= 6×$25)
```

### Stake convention — IMPORTANT
`NOTIONAL = $25`: you pay $25 per fire, receive `25/vwap` shares. Wins at low vwap CAN exceed $25 per trade (e.g., win UP at vwap=0.05 → 500 shares × $1 settle − 2% fee ≈ +$465 net). Production `engine_v2.hold_pnl` uses this.

`pnl_legacy_usd` field in v3 fires IS already $25-normalized — DO NOT multiply by 25 (V8 BTC 15m original agent did this, inflated by 25×).

## 1. Anchor conventions (UNCHANGED)

```
slot_start_us = chainlink resolution slot start (UTC microseconds)
window_s      = 300 (5m) or 900 (15m)
ws_s          = slot_start_us // 1_000_000 - window_s          # signal anchor
fire_us       = slot_start_us + offset_s * 1_000_000           # entry time
slot_end_us   = slot_start_us + window_s * 1_000_000

Pre-window gates (prefix g_pw_*): evaluate at ts_us = ws_s * 1_000_000
Intra-window gates: evaluate at ts_us <= fire_us - 1_000_000
Per-bar panels: merge_asof(direction="backward", allow_exact_matches=True)
                ts_us = bar END (use *_v2_fixed variants)
```

## 2. Direction enumeration

Enumerate BOTH UP and DOWN unless sleeve restricts via `g_dir_up` or `g_dir_down`. Run `g_book_supports_stake` as FILL-TIME veto.

---

## 3. NEW V8 gates — implementation spec

Inherits V5 + V6 + V7 gate libraries. New V8 gates below.

### 3.1 — 1h grandparent regime gates (Path L)

Source: NEW panel `data/v4/canonical/_results/regime_panel_1h.parquet` built from binance 1h klines. Columns same as 5m/15m regime panels: `asset, tf, ts_us, ts_s, open, high, low, close, volume, adx_14, plus_di_14, minus_di_14, atr_14, tr_ema_stack_score, ribbon_alignment_pct, bb_width_60s, realized_vol_60m, range_compression, trend_slope_30m, regime_label, regime_score`. `ts_us` = bar END.

```python
g_grandparent_trend_with(direction, fire_us, asset):
  # 1h trend_slope_30m sign matches direction
  ts = asof_bar_end(asset, "1h", fire_us - 1_000_000)
  slope = regime_panel_1h[asset].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")

g_grandparent_1h_slope_strong_with(direction, fire_us, asset):
  ts = asof_bar_end(asset, "1h", fire_us - 1_000_000)
  slope = regime_panel_1h[asset].trend_slope_30m at ts
  if pd.isna(slope): return False
  thr = 0.85   # precomputed p75 of |BTC 1h slope| training (recompute monthly)
  return abs(slope) > thr AND \
         ((slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN"))

g_1h_rf_with(direction, fire_us, asset):
  # 1h Range-Filter direction matches
  # Build live: rf_dir on the asset's 1h close series
  rf_dir = range_filter_1h[asset].rf_dir at (fire_us - 1_000_000)
  return (rf_dir == 1 and direction == "UP") or (rf_dir == -1 and direction == "DOWN")
```

### 3.2 — 2-asset confluence gates (Path J)

```python
g_2asset_btc_eth_with(direction, fire_us):
  # Both BTC and ETH 5m trend_slope_30m sign matches direction
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  btc_slope = regime_panel_5m_v2_fixed["BTC"].trend_slope_30m at ts
  eth_slope = regime_panel_5m_v2_fixed["ETH"].trend_slope_30m at ts
  if pd.isna(btc_slope) or pd.isna(eth_slope): return False
  if direction == "UP":   return btc_slope > 0 AND eth_slope > 0
  else:                    return btc_slope < 0 AND eth_slope < 0

g_2asset_either_trending_with(direction, fire_us):
  # At least ONE of BTC/ETH 5m trends matches direction (looser version)
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  btc = regime_panel_5m_v2_fixed["BTC"].trend_slope_30m at ts
  eth = regime_panel_5m_v2_fixed["ETH"].trend_slope_30m at ts
  if direction == "UP":   return (btc > 0) OR (eth > 0)
  else:                    return (btc < 0) OR (eth < 0)

g_3asset_combined_unanimity(direction, fire_us):
  # All 3 assets agree via BOTH rf_dir AND trend_slope (high conviction, rare)
  for asset in ["BTC", "ETH", "SOL"]:
    rf  = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)
    ts  = trend_slope_30m(asset, "5m", fire_us)
    sig = +1 if (rf == 1 and ts > 0) else -1 if (rf == -1 and ts < 0) else 0
    if sig == 0: return False
  all_up = all rf==1 AND ts>0 for {BTC, ETH, SOL}
  all_dn = all rf==-1 AND ts<0 for {BTC, ETH, SOL}
  return (all_up and direction == "UP") or (all_dn and direction == "DOWN")

g_btc_sol_confluence_5m_with(direction, fire_us):
  # BTC 5m + SOL 5m trend slope BOTH match direction
  btc = trend_slope_30m("BTC", "5m", fire_us)
  sol = trend_slope_30m("SOL", "5m", fire_us)
  if direction == "UP":   return btc > 0 AND sol > 0
  else:                    return btc < 0 AND sol < 0

g_btc_eth_confluence_5m_with(direction, fire_us):
  # BTC 5m + ETH 5m trend slope BOTH match direction
  btc = trend_slope_30m("BTC", "5m", fire_us)
  eth = trend_slope_30m("ETH", "5m", fire_us)
  if direction == "UP":   return btc > 0 AND eth > 0
  else:                    return btc < 0 AND eth < 0

g_xa_unanimity_5m_with(direction, fire_us):
  # All 3 assets' 5m trend slopes unanimously match direction
  btc = trend_slope_30m("BTC", "5m", fire_us)
  eth = trend_slope_30m("ETH", "5m", fire_us)
  sol = trend_slope_30m("SOL", "5m", fire_us)
  if direction == "UP":   return btc > 0 AND eth > 0 AND sol > 0
  else:                    return btc < 0 AND eth < 0 AND sol < 0

g_btc_eth_divergence(direction, fire_us):
  # BTC and ETH 5m trend slopes have OPPOSITE signs (divergence signal)
  btc = trend_slope_30m("BTC", "5m", fire_us)
  eth = trend_slope_30m("ETH", "5m", fire_us)
  return (btc > 0 AND eth < 0) OR (btc < 0 AND eth > 0)
  # Direction-agnostic; combined with directional gate downstream

g_J_btc_eth_vol_both_low(direction, fire_us):
  # Both BTC and ETH realized_vol_60m below their training-window medians
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  btc_rv = regime_panel_5m_v2_fixed["BTC"].realized_vol_60m at ts
  eth_rv = regime_panel_5m_v2_fixed["ETH"].realized_vol_60m at ts
  btc_thr = 0.0042   # training median
  eth_thr = 0.0055
  return (btc_rv < btc_thr) AND (eth_rv < eth_thr)

g_2a_btc_sol_trend_with(direction, fire_us):
  # alias of g_btc_sol_confluence_5m_with for 15m fires (uses 5m features at fire_us)
  return g_btc_sol_confluence_5m_with(direction, fire_us)
```

### 3.3 — Cross-asset pre-window gates for ETH 15m / SOL 15m

```python
g_pw_btc_15m_trend_with(direction, fire_us, asset):
  # At ws_s of the ETH/SOL 15m fire, check BTC's 15m trend_slope sign
  ws_s_us = ws_s * 1_000_000
  ts = asof_bar_end("BTC", "15m", ws_s_us)
  slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")

g_pw_sol_15m_trend_with(direction, fire_us, asset):
  ws_s_us = ws_s * 1_000_000
  ts = asof_bar_end("SOL", "15m", ws_s_us)
  slope = regime_panel_15m_v2_fixed["SOL"].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")
```

### 3.4 — TOD bucket gates (Path K)

Time-of-day bucket gates — all UTC hours:

```python
g_tod_asia_morning(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 0 <= h <= 6            # 00-07 UTC

g_tod_european_morning(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 7 <= h <= 12           # 07-13 UTC

g_tod_us_open(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 13 <= h <= 14          # 13-15 UTC

g_tod_us_afternoon(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 13 <= h <= 18          # 13-19 UTC

g_tod_us_evening(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 19 <= h <= 23          # 19-24 UTC

g_tod_europe_us_window(fire_us):
  h = (fire_us // 1_000_000 // 3600) % 24
  return 7 <= h <= 18           # 07-19 UTC (combined EU+US active hours)

g_K_tod_european_morning = g_tod_european_morning   # alias used in SOL 15m V7
```

### 3.5 — Path Q: prev 15m parent agreement (for 5m sleeves)

```python
g_q_prev15m_agrees(direction, fire_us, asset):
  # The previous (already-closed) 15m bar's trend_slope sign matches direction
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  prev_slope = regime_panel_15m_v2_fixed[asset].trend_slope_30m at ts
  if pd.isna(prev_slope): return False
  return (prev_slope > 0 and direction == "UP") or (prev_slope < 0 and direction == "DOWN")
```

### 3.6 — Cross-asset feature gates (5m, used as overlays)

```python
g_sol_trend_slope_with(direction, fire_us):
  # SOL 5m trend_slope sign matches direction (for ETH 5m fires)
  ts = asof_bar_end("SOL", "5m", fire_us - 1_000_000)
  slope = regime_panel_5m_v2_fixed["SOL"].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")

g_BTC_slope_with(direction, fire_us):   # for SOL 15m fires, 15m slope
  ts = asof_bar_end("BTC", "15m", fire_us - 1_000_000)
  slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")

g_BTC_slope_strong_with(direction, fire_us):
  ts = asof_bar_end("BTC", "15m", fire_us - 1_000_000)
  slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(slope): return False
  thr = 0.612   # BTC 15m slope p75 training threshold
  return abs(slope) > thr AND ((slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN"))

g_L_ETH_grandparent_adx_strong(direction, fire_us):
  # ETH 1h ADX >= 25 (strong trend in 1h grandparent)
  ts = asof_bar_end("ETH", "1h", fire_us - 1_000_000)
  adx = regime_panel_1h["ETH"].adx_14 at ts
  return adx >= 25

g_BTC_adx_strong(direction, fire_us):
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  adx = regime_panel_5m_v2_fixed["BTC"].adx_14 at ts
  return adx >= 25

g_ETH_adx_strong(direction, fire_us):
  ts = asof_bar_end("ETH", "5m", fire_us - 1_000_000)
  adx = regime_panel_5m_v2_fixed["ETH"].adx_14 at ts
  return adx >= 25

g_ETH_vol_low(direction, fire_us):
  ts = asof_bar_end("ETH", "5m", fire_us - 1_000_000)
  rv = regime_panel_5m_v2_fixed["ETH"].realized_vol_60m at ts
  return rv < 0.0055   # training median
```

### 3.7 — Liquidity shock gate (Path P, BTC 15m)

```python
g_liq_shock_against(direction, fire_us, slug):
  # L25 cumulative depth on the OPPOSITE side dropped > 30% in last 5s before fire
  # Fire AGAINST the recent depth disappearance (mean-reversion play)
  other_side = "DOWN" if direction == "UP" else "UP"
  depth_now  = L25[slug, other_side].cum_depth_usd at fire_us
  depth_5s   = L25[slug, other_side].cum_depth_usd at (fire_us - 5_000_000)
  if pd.isna(depth_now) or pd.isna(depth_5s) or depth_5s == 0: return False
  return depth_now < depth_5s * 0.7

g_di_agrees(direction, fire_us, asset):
  # +DI / -DI agreement (directional indicator from ADX panel)
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  plus_di  = regime_panel_15m_v2_fixed[asset].plus_di_14 at ts
  minus_di = regime_panel_15m_v2_fixed[asset].minus_di_14 at ts
  if direction == "UP":   return plus_di > minus_di
  else:                    return minus_di > plus_di
```

### 3.8 — F7 v7 + variants (already in V7 spec, reused)
See V7 spec §3.9 for `g_f7_v7_with`, `g_f7_v7_overbought`, `g_f7_v7_oversold`, `g_btc_f7_with`, `g_btc_f7_against`.

### 3.9 — Other intra-window gates (mostly from earlier specs)
- `g_tr_full_stack_with` = ALIAS of `g_tr_stack_full_with` (V5 §3.5)
- `g_vol_contracting` (V5 R3 gate)
- `g_stoch_with` (V5 R1 base)
- `g_trend_slope_with` (V5)
- `g_hurst_trending`, `g_hurst_trend_with` (V6/V7)
- `g_imb5_strong_with` (V6)
- `g_rf_with` (V5)
- `g_ribbon_agrees` (V5)
- `g_parent_15m_slope_with`, `g_parent15m_ranging` (V7)
- `g_cci_with`, `g_cci_extreme_with` (V5/V7)
- `g_mfi_strong_with` (V5 §3.6 alias of g_mfi_with with stricter threshold)

---

## 4. V8 selected sleeve specifications (14 new)

All sleeves end with `_V8` suffix for dashboard separation.

### Sleeve V8_01 — BTC_5M_L_1HRF_IMB5_RF_V8

```
asset           = BTC
tf              = 5m
direction       = {UP, DOWN}
slug_source     = "any"
offset_s        = ALL (30-270, but heavy weighting from agent on multi-offset)
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_1h_rf_with(direction, fire_us, asset="BTC")
  g_imb5_strong_with(direction, fire_us, slug)
  g_rf_with(direction, fire_us, asset="BTC")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=786 WR 76.7% $/tr +$3.46 | val n=363 WR 71.9% $/tr +$6.79 | lockbox n=360 WR 68.9% $/tr +$5.11 | full n=1509 WR 73.7% $/tr +$4.66 | DD $228 | LS 6 | bs_p 0.000 | **proj_honest $7,025/32.7d**.
Status: DEPLOY — V8 Path L winner for BTC 5m.

---

### Sleeve V8_02 — BTC_5M_L_1HRF_IMB5_RIBBON_V8

```
asset           = BTC
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_1h_rf_with(direction, fire_us, asset="BTC")
  g_imb5_strong_with(direction, fire_us, slug)
  g_ribbon_agrees(direction, fire_us, asset="BTC")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=781 WR 80.8% $/tr +$3.60 | val n=374 WR 78.1% $/tr +$3.79 | lockbox n=354 WR 75.4% $/tr +$6.19 | DD $300 | LS 6 | proj_honest $6,424.
Status: DEPLOY.

---

### Sleeve V8_03 — BTC_5M_Q_PARENT15MSLOPE_TS_IMB5_V8

```
asset           = BTC
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_parent_15m_slope_with(direction, fire_us, asset="BTC")
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")
  g_imb5_strong_with(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=348 WR 69.5% $/tr +$2.23 | val n=121 WR 75.2% $/tr +$2.57 | lockbox n=188 WR 75.5% $/tr +$15.88 | DD $304 | LS 9 | proj_honest $4,073.
Status: DEPLOY — V8 Path Q (15m parent + microstructure).

---

### Sleeve V8_04 — ETH_5M_L_EMA50_HURST_GRANDPARENT_V8

```
asset           = ETH
tf              = 5m
direction       = {UP, DOWN}
offset_s        = 60        # single offset
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_tr_above_ema50(direction, fire_us, asset="ETH")
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")
  g_grandparent_trend_with(direction, fire_us, asset="ETH")   # NEW 1h regime gate

fill_time_veto: g_book_supports_stake
```

Backtest: train n=125 WR 79.2% $/tr +$2.92 | val n=84 WR 84.5% $/tr +$3.17 | lockbox n=258 WR 82.6% $/tr +$6.33 | DD **$75** | LS 3 | proj_honest $2,240.
Status: DEPLOY — V8 Path L winner for ETH 5m.

---

### Sleeve V8_05 — ETH_5M_K_HURST_TS_CCI_TOD_EUUS_V8

```
asset           = ETH
tf              = 5m
direction       = {UP, DOWN}
offset_s        = 120       # single offset
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_hurst_trend_with(direction, fire_us, asset="ETH", tf="5m")
  g_trend_slope_with(direction, fire_us, asset="ETH", tf="5m")
  g_cci_with(direction, fire_us, asset="ETH")
  g_tod_europe_us_window(fire_us)                            # 07-19 UTC

fill_time_veto: g_book_supports_stake
```

Backtest: train n=163 WR 89.0% $/tr +$2.31 | val n=98 WR 84.7% $/tr +$3.17 | lockbox n=261 WR 82.0% $/tr +$4.22 | DD $93 | LS 3 | proj_honest $1,771.
Status: DEPLOY — V8 Path K (TOD specialization).

---

### Sleeve V8_06 — ETH_5M_LQ_EMA50_HURST_GRANDPARENT_PREV15M_V8

```
asset           = ETH
tf              = 5m
direction       = {UP, DOWN}
offset_s        = 60
window_s        = 300
spread_filter   = 0.02

gates_all_must_pass:
  g_tr_above_ema50(direction, fire_us, asset="ETH")
  g_hurst_trend_with(direction, fire_us, asset="ETH", tf="5m")
  g_grandparent_trend_with(direction, fire_us, asset="ETH")  # 1h regime
  g_q_prev15m_agrees(direction, fire_us, asset="ETH")        # 15m parent agreement

fill_time_veto: g_book_supports_stake
```

Backtest: train n=92 WR 76.1% $/tr +$2.32 | val n=61 WR 83.6% $/tr +$3.48 | lockbox n=181 WR 80.1% $/tr +$5.15 | DD $90 | LS 3 | proj_honest $1,344.
Status: DEPLOY — V8 Path L+Q (multi-timeframe cascade).

---

### Sleeve V8_07 — SOL_5M_BTCF7AGAINST_CCI_HURSTREV_MFI_V8

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL (mixed 30-240s)
window_s        = 300
spread_filter   = 0.025

gates_all_must_pass:
  g_btc_f7_against(direction, fire_us)                   # BTC F7 RSI extreme AGAINST direction (mean-revert)
  g_cci_extreme_with(direction, fire_us, asset="SOL")
  g_hurst_reverting(direction, fire_us, asset="SOL", tf="5m")
  g_mfi_strong_with(direction, fire_us, asset="SOL")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=331 WR 71.9% $/tr +$3.79 | val n=229 WR 78.6% $/tr +$9.21 | lockbox n=89 WR 78.7% $/tr +$6.52 | full n=649 WR 75.2% $/tr +$6.08 | DD $116 | LS 3 | bs_p 0.005 | proj_honest **$3,157**.
Status: DEPLOY — V8 best SOL 5m, extends V7 SOL5_V7_S3 with `g_mfi_strong_with`.

---

### Sleeve V8_08 — SOL_5M_J_2ASSET_TRENDING_CCI_RF_EMA200_V8

```
asset           = SOL
tf              = 5m
direction       = {UP, DOWN}
offset_s        = ALL
window_s        = 300
spread_filter   = 0.025

gates_all_must_pass:
  g_2asset_either_trending_with(direction, fire_us)      # BTC OR ETH 5m trend matches direction
  g_cci_extreme_with(direction, fire_us, asset="SOL")
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_above_ema200(direction, fire_us, asset="SOL")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=344 WR 73.3% $/tr +$2.45 | val n=227 WR 75.3% $/tr +$4.50 | lockbox n=114 WR 76.3% $/tr +$4.23 | DD $134 | LS 3 | bs_p 0.030 | proj_honest $2,321.
Status: DEPLOY — V8 Path J 2-asset confluence.

---

### Sleeve V8_09 — ETH_15M_BASELINE_V7_TOP_REPLICATE_V8 ⚠ DUPLICATE OF V7_10

```
asset           = ETH
tf              = 15m
direction       = {UP, DOWN}
offset_s        ∈ {0, 30, 60}     # offset_early (g_offset_early)
window_s        = 900
spread_filter   = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(fire_us, slot_start_us)
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_pw_btc_15m_trend_with(direction, fire_us, asset="ETH")    # PRE-WINDOW

fill_time_veto: g_book_supports_stake
```

Backtest: train n=33 WR 78.8% $/tr +$8.98 | val n=19 WR 78.9% $/tr +$8.80 | lockbox n=12 WR 100% $/tr +$12.13 | full n=64 WR 82.8% $/tr +$9.52 | DD $75 | LS 3 | proj_honest **$948**.
Status: DEPLOY — ⚠ IDENTICAL gates to **V7 sleeve 10 (ETH_15M_PI_BTC15M_TREND_V7)**. Both will fire on same slugs. Coordinate naming for dashboard distinction.

---

### Sleeve V8_10 — ETH_15M_PJ_BTC_AND_SOL_TREND_SEP_V8

```
asset           = ETH
tf              = 15m
direction       = {UP, DOWN}
offset_s        ∈ {0, 30, 60}
window_s        = 900
spread_filter   = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(fire_us, slot_start_us)
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_pw_btc_15m_trend_with(direction, fire_us, asset="ETH")    # BTC 15m trend at ws_s
  g_pw_sol_15m_trend_with(direction, fire_us, asset="ETH")    # SOL 15m trend at ws_s

fill_time_veto: g_book_supports_stake
```

Backtest: train n=27 WR 77.8% $/tr +$8.41 | val n=16 WR 75.0% $/tr +$6.97 | lockbox n=8 WR 100% $/tr +$12.19 | full n=51 WR 80.4% $/tr +$8.55 | DD $61 | LS 2 | proj_honest **$712**.
Status: DEPLOY — adds SOL 15m pre-window trend gate to V7_10 baseline.

---

### Sleeve V8_11 — SOL_15M_V7S5_PLUS_ETH1H_ADX_V8 (stability monotone winner)

```
asset           = SOL
tf              = 15m
direction       = {UP, DOWN}
offset_s        ∈ {60, 120, 240}    # g_off_60_240
window_s        = 900
spread_filter   = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  g_BTC_slope_with(direction, fire_us)
  g_BTC_slope_strong_with(direction, fire_us)
  g_L_ETH_grandparent_adx_strong(direction, fire_us)         # ETH 1h ADX strong overlay

fill_time_veto: g_book_supports_stake
```

Backtest: train n=34 WR 70.6% $/tr +$4.38 | val n=7 WR 85.7% $/tr +$8.26 | lockbox n=16 WR 93.8% $/tr +$12.97 | full n=57 WR 78.9% $/tr +$7.27 | DD **$25** | LS **1** | bs_p 0.023 | proj_honest **$415**.
Status: DEPLOY — monotone train→val→lock $/tr (4.38→8.26→12.97), best stability.

---

### Sleeve V8_12 — SOL_15M_V7_BASE_S5_SLOPE_STR_V8 ⚠ DUPLICATE OF V7_11

```
asset           = SOL
tf              = 15m
direction       = {UP, DOWN}
offset_s        ∈ {60, 120, 240}
window_s        = 900
spread_filter   = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  g_BTC_slope_with(direction, fire_us)
  g_BTC_slope_strong_with(direction, fire_us)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=52 WR 69.2% $/tr +$3.32 | val n=10 WR 80.0% $/tr +$6.41 | lockbox n=18 WR 88.9% $/tr +$10.78 | full n=80 WR 75.0% $/tr +$5.38 | DD $38 | LS 1 | bs_p 0.033 | proj_honest $431.
Status: DEPLOY — ⚠ IDENTICAL gates to **V7 sleeve 11 (SOL_15M_BTC_SLOPE_PAIR_V7)**. Will produce duplicate fires.

---

### Sleeve V8_13 — SOL_15M_V6_J_BTCETH_VOLLOW_L_ETHADX_V8 (income winner)

```
asset           = SOL
tf              = 15m
direction       = {UP, DOWN}
offset_s        ∈ {60, 120, 240}
window_s        = 900
spread_filter   = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  g_J_btc_eth_vol_both_low(direction, fire_us)               # BTC AND ETH 5m vol both below median
  g_L_ETH_grandparent_adx_strong(direction, fire_us)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=51 WR 74.5% $/tr +$5.27 | val n=20 WR 65.0% $/tr +$0.15 ⚠ (borderline) | lockbox n=35 WR 85.7% $/tr +$9.33 | full n=106 WR 76.4% $/tr +$5.65 | DD $100 | LS 4 | bs_p 0.008 | proj_honest **$599** (highest of V8 SOL 15m).
Status: DEPLOY — val $/tr near zero (+$0.15), monitor first 50 fires.

---

### Sleeve V8_14 — BTC_15M_BTCETH_DIVERG_STOCH_VOLCONTR_V8 (CORRECTED $25 normalization)

```
asset           = BTC
tf              = 15m
direction       = UP
slug_source     = "any"
offset_s        = 720
window_s        = 900
spread_filter   = 0.02

gates_all_must_pass:
  g_dir_up(direction)
  g_btc_eth_divergence(direction, fire_us)                   # BTC and ETH trends DIVERGE
  g_stoch_with(direction="UP", fire_us, asset="BTC")
  g_vol_contracting(direction="UP", fire_us, asset="BTC", tf="15m")

fill_time_veto: g_book_supports_stake
```

Backtest (CORRECTED $25 stake): train n=75 WR 84.0% $/tr +$12.83 | val n=17 WR 70.6% $/tr +$36.98 | lockbox n=21 WR 100% $/tr +$155.15 ⚠ | full n=113 WR 85.0% $/tr +$42.91 | DD $1,799* | LS 2 | bs_p_lb 0.0002 ✓ | bs_p_full 0.130 | **proj_full = $194** (most conservative).

⚠ NOTE: $/tr can legitimately exceed $25 under NOTIONAL convention (low-vwap wins pay shares × $1). Lockbox bs_p=0.0002 is the only V8 BTC 15m sleeve with stat-sig p < 0.05. Full-window bs_p=0.130 not stat-sig — could be lockbox luck.
Status: DEPLOY — only V8 BTC 15m sleeve passing stat-sig test. Monitor carefully; CI [+$84.80, +$239.60] is wide.

---

## 5. Combined registry — V5 + V6 + V7 + V8 (40 sleeves total in shadow)

### V5 (16 sleeves, already deployed)
See [SHADOW_DEPLOY_SPEC_2026_05_27.md](./SHADOW_DEPLOY_SPEC_2026_05_27.md) §5.

### V6 selected (14 sleeves, in shadow)
See [SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md](./SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md) §5.

### V7 selected (12 sleeves, in shadow)
See [SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md](./SHADOW_DEPLOY_SPEC_V7_SELECTED_2026_05_27.md) §5.

### V8 selected (14 NEW sleeves — this doc)

```
ID      sleeve_id                                            asset tf   dir  offset           spread  gates  status
V8_01   BTC_5M_L_1HRF_IMB5_RF_V8                            BTC   5m   BOTH ALL              0.02    3      DEPLOY 🎯
V8_02   BTC_5M_L_1HRF_IMB5_RIBBON_V8                        BTC   5m   BOTH ALL              0.02    3      DEPLOY
V8_03   BTC_5M_Q_PARENT15MSLOPE_TS_IMB5_V8                  BTC   5m   BOTH ALL              0.02    3      DEPLOY
V8_04   ETH_5M_L_EMA50_HURST_GRANDPARENT_V8                 ETH   5m   BOTH 60               0.02    3      DEPLOY 🎯
V8_05   ETH_5M_K_HURST_TS_CCI_TOD_EUUS_V8                   ETH   5m   BOTH 120              0.02    4      DEPLOY
V8_06   ETH_5M_LQ_EMA50_HURST_GRANDPARENT_PREV15M_V8        ETH   5m   BOTH 60               0.02    4      DEPLOY
V8_07   SOL_5M_BTCF7AGAINST_CCI_HURSTREV_MFI_V8             SOL   5m   BOTH ALL              0.025   4      DEPLOY 🎯
V8_08   SOL_5M_J_2ASSET_TRENDING_CCI_RF_EMA200_V8           SOL   5m   BOTH ALL              0.025   4      DEPLOY
V8_09   ETH_15M_BASELINE_V7_TOP_REPLICATE_V8                ETH   15m  BOTH 0/30/60 + ws_s   0.02    5      DEPLOY ⚠ dup V7_10
V8_10   ETH_15M_PJ_BTC_AND_SOL_TREND_SEP_V8                 ETH   15m  BOTH 0/30/60 + ws_s   0.02    6      DEPLOY
V8_11   SOL_15M_V7S5_PLUS_ETH1H_ADX_V8                      SOL   15m  BOTH 60/120/240       0.025   7      DEPLOY 🎯 (stability)
V8_12   SOL_15M_V7_BASE_S5_SLOPE_STR_V8                     SOL   15m  BOTH 60/120/240       0.025   6      DEPLOY ⚠ dup V7_11
V8_13   SOL_15M_V6_J_BTCETH_VOLLOW_L_ETHADX_V8              SOL   15m  BOTH 60/120/240       0.025   6      DEPLOY (income)
V8_14   BTC_15M_BTCETH_DIVERG_STOCH_VOLCONTR_V8             BTC   15m  UP   720              0.02    4      DEPLOY 🎯 (only stat-sig)
```

### Total shadow roster summary
- V5: 16 sleeves
- V6 selected: 14 sleeves
- V7 selected: 12 sleeves
- V8 selected: 14 sleeves (2 are duplicates of V7)
- **Effective unique sleeves**: ~52 (after de-dup)
- **Total fires expected**: depends on overlap; operator approved running all in shadow for live measurement

## 6. Execution params (all 14 V8 sleeves)

```
notional_default_usd  = 25.0
notional_ramp_start   = 5.0
fill_method           = L25_book_walk
fill_min_book_events  = 25
hold_to               = slot_end_us
fee_model             = legacy_2pct_profit
latency_budget_ms     = 85

# MANDATORY (same as V6, V7)
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=25.0)
                      # Cancel order if L25 cumulative depth on chosen side < $150
```

## 7. Shadow logging — extended schema (V8 additions)

Extend V7 schema with:

```
+ sleeve_version          : "V8"
+ grandparent_1h_features : {trend_slope_30m, adx_14, regime_label, rf_dir} per asset
+ tod_bucket              : "asia_morning"|"european_morning"|"us_open"|"us_afternoon"|"us_evening"|"europe_us_window"
+ confluence_signals      : {btc_5m_trend, eth_5m_trend, sol_5m_trend, btc_15m_trend, sol_15m_trend}
+ liq_shock_pre           : {depth_now_usd, depth_5s_usd, ratio}  # for sleeves using g_liq_shock_against
+ pw_btc_15m_trend        : (when sleeve uses g_pw_btc_15m_trend_with)
+ pw_sol_15m_trend        : (when sleeve uses g_pw_sol_15m_trend_with)
```

## 8. Open items / caveats

### Duplicates (run in shadow to compare; coordinate dashboard tagging)

1. **V8_09 = V7_10** (ETH 15m): IDENTICAL gates `g_tr_stack_full + g_above_1h_dailyvwap + g_offset_early + g_vol_high + g_pw_btc_15m_trend_with`. Same fires expected. Distinguish in logs by sleeve_id only.

2. **V8_12 = V7_11** (SOL 15m): IDENTICAL gates `g_hod_european_morning + g_off_60_240 + g_rf_with + g_tr_stack_with + g_BTC_slope_with + g_BTC_slope_strong_with`. Same fires expected.

### Build requirements before deploy

3. **`regime_panel_1h.parquet`** (V8 §3.1) — NEW panel built by V8 research. Production must compute 1h regime live for BTC, ETH, SOL OR reuse this panel.

4. **`range_filter_1h`** (used by `g_1h_rf_with`) — need to compute 1h RF on each asset live OR build new panel. Same Mark Lijesen formula as 1s RF, just applied to 1h closes.

5. **TOD gates (V8 §3.4)** — simple UTC-hour buckets. No new data needed.

6. **2-asset / 3-asset confluence gates (V8 §3.2)** — require synchronized real-time `regime_panel_5m_v2_fixed` + `regime_panel_15m_v2_fixed` access for all 3 assets in TV.

### Statistical caveats

7. **V8_14 (BTC 15m)** is the ONLY V8 BTC 15m sleeve with lockbox bs_p ≤ 0.05 (0.0002). Full-window bs_p = 0.130 — could be lockbox luck. CI is wide. Treat as exploratory; monitor first 100 fires for WR drift.

8. **Cross-asset gate latency** — gates like `g_btc_eth_divergence` and `g_2asset_btc_eth_with` require simultaneous regime panel reads. TV must verify pipeline latency < 1s across all 3 assets.

9. **V8 honest projections are LOWER than V7's lockbox-extrapolations** because V8 explicitly uses `min(proj_32d, proj_full)`. Realistic 32.7d combined V6+V7+V8 honest projection ≈ $15-25k at $25 stake (before slug-overlap reduction).

### NOTIONAL stake convention reminder

10. **DO NOT MULTIPLY `pnl_legacy_usd` BY 25** — that field is already $25-normalized. V8 BTC 15m original agent did this and inflated all metrics 25× (now corrected in V8_14).

11. Under NOTIONAL convention, individual winning trades CAN return +$300+ per fire (low-vwap wins). This is normal and matches production behavior. Per-fire $/tr is unbounded above; max loss is exactly $25.

---

## END (Unified V6+V7+V8 spec)
