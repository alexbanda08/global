# Shadow Deploy Spec — 12 V7 Sleeves (Selected) — 2026-05-27

Operator-selected V7 sleeves for TV shadow implementation on VPS3. Companion to V5 + V6 spec docs. All V7 sleeve IDs end with `_V7`.

V7 introduces cross-asset gates (BTC features driving ETH/SOL fires), 15m-parent regime confluence, slot-end OFI, hurst variants, and recomputed F7 gates.

---

## 0. Engine constants (same as V6 — see SHADOW_DEPLOY_SPEC_V6_SELECTED_2026_05_27.md §0)

```
notional_default_usd  = 25.0     # constant
fee_model             = legacy_2pct_profit
spread_filter_btc     = 0.02
spread_filter_eth     = 0.02
spread_filter_sol     = 0.025
window_s_5m           = 300
window_s_15m          = 900
fill_engine           = L25_book_walk
exit_policy           = HOLD_TO_SLOT_END
mode                  = paper
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=25)  # MANDATORY
```

## 1. Anchor conventions (same as V6)

```
ws_s          = slot_start_us // 1_000_000 - window_s
fire_us       = slot_start_us + offset_s * 1_000_000

Intra-window gates : evaluate at ts_us <= fire_us - 1_000_000
Pre-window gates   : evaluate at ts_us <= ws_s * 1_000_000
Per-bar panels     : merge_asof(direction="backward", allow_exact_matches=True)
Per-bar panel ts_us = bar END (use *_v2_fixed variants)
```

## 2. Direction handling

Enumerate BOTH directions UP and DOWN per slug unless sleeve restricts. ALL gates must pass for entry. Run `g_book_supports_stake` as FILL-TIME veto.

## 3. NEW V7 gates — implementation spec

Inherits V5 + V6 gate library. New V7 gates below.

### 3.1 — 15m parent regime gates (source: regime_panel_15m_v2_fixed.parquet)

For 5m markets, look up the parent 15m regime label at the fire's asof bar-end.

```python
g_parent_15m_regime_with(direction, fire_us, asset):
  # The 15m regime that's ACTIVE at fire_us
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  label = regime_panel_15m_v2_fixed[asset].regime_label at ts
  return (label == "trending_up" and direction == "UP") or \
         (label == "trending_dn" and direction == "DOWN")

g_parent_15m_slope_with(direction, fire_us, asset):
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  slope = regime_panel_15m_v2_fixed[asset].trend_slope_30m at ts
  if pd.isna(slope): return False
  return (slope > 0 and direction == "UP") or (slope < 0 and direction == "DOWN")

g_parent_15m_not_ranging(direction, fire_us, asset):
  # Just requires the parent NOT to be in ranging regime — works for both directions
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  label = regime_panel_15m_v2_fixed[asset].regime_label at ts
  return label != "ranging"

g_parent15m_ranging(direction, fire_us, asset):
  # OPPOSITE: explicitly wants parent in ranging regime (mean-reversion sweet spot for ETH 5m)
  ts = asof_bar_end(asset, "15m", fire_us - 1_000_000)
  label = regime_panel_15m_v2_fixed[asset].regime_label at ts
  return label == "ranging"
```

### 3.2 — Hurst variants (source: vol_hurst_at_fire_{5m,15m}.parquet)

```python
g_hurst_reverting(direction, fire_us, asset, tf):
  # Hurst < 0.40 = mean-reverting regime. Direction-independent.
  hurst = vol_hurst_at_fire[asset, tf].hurst_60 at slot_start_us
  return hurst < 0.40

g_hurst_regime_with(direction, fire_us, asset, tf):
  # Direction-aware: hurst > 0.55 AND price-trend aligned with direction
  hurst = vol_hurst_at_fire[asset, tf].hurst_60 at slot_start_us
  price_trend_sign = trend_slope_30m(asset, tf, fire_us)   # from regime panel
  if pd.isna(hurst) or pd.isna(price_trend_sign): return False
  if hurst < 0.55: return False
  return (price_trend_sign > 0 and direction == "UP") or (price_trend_sign < 0 and direction == "DOWN")

g_hurst_mp_trend_with(direction, fire_us, asset, slug):
  # Hurst trending AND microprice skew aligned with direction
  hurst = vol_hurst_at_fire[asset, "5m"].hurst_60 at slot_start_us
  mp_s  = mp_skew(fire_us - 1_000_000, slug)   # bps
  if pd.isna(hurst) or pd.isna(mp_s): return False
  if hurst < 0.50: return False
  return (mp_s > 0 and direction == "UP") or (mp_s < 0 and direction == "DOWN")
```

### 3.3 — Slot-end OFI (BTC 5m — VALIDATION REQUIRED IN SHADOW)

⚠ V7 research found this fails for BTC 15m due to train-lockbox regime flip. Agent claims it works for BTC 5m. **Treat as exploratory; monitor live closely.**

```python
g_slot_end_ofi_with(direction, fire_us, slug, slot_end_us):
  # Order-flow imbalance in last 60s before slot_end.
  # ONLY valid for fires AT slot_end - 60s OR LATER (else lookahead).
  # For 5m: valid offsets >= 240s (60s before slot_end_us = slot_start + 240s).
  if (slot_end_us - fire_us) / 1_000_000 > 60:
    return False   # this is lookahead — skip
  buy_vol  = sum(trade.size for trade in polymarket_trades[slug]
                  if trade.side == "buy"  and slot_end_us - 60_000_000 <= trade.ts_us <= slot_end_us)
  sell_vol = sum(trade.size for trade in polymarket_trades[slug]
                  if trade.side == "sell" and slot_end_us - 60_000_000 <= trade.ts_us <= slot_end_us)
  ofi = buy_vol - sell_vol
  thr = 100.0   # USD threshold per V7 research
  return (ofi > thr and direction == "UP") or (ofi < -thr and direction == "DOWN")
```

### 3.4 — Cross-asset trigger gates (Path C — V7 universal win)

These look at one asset's features to gate another asset's fire.

```python
g_btc_trend_30m_with(direction, fire_us):
  # BTC's 5m trend_slope_30m, signed match with fire direction (for SOL/ETH fires)
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  btc_slope = regime_panel_5m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(btc_slope): return False
  return (btc_slope > 0 and direction == "UP") or (btc_slope < 0 and direction == "DOWN")

g_btc_f7_with(direction, fire_us):
  # BTC's F7 RSI extreme matching direction (using full-coverage v7 RSI computation)
  rsi = compute_f7_rsi("BTC", ws_s_of_fire)   # Wilder simple-mean 7-period, 60s sample
  if rsi >= 70 and direction == "UP":   return True
  if rsi <= 30 and direction == "DOWN": return True
  return False

g_btc_f7_against(direction, fire_us):
  # OPPOSITE: BTC RSI extreme AGAINST fire direction (mean-revert play)
  rsi = compute_f7_rsi("BTC", ws_s_of_fire)
  if rsi >= 70 and direction == "DOWN": return True   # BTC overbought, bet DOWN
  if rsi <= 30 and direction == "UP":   return True   # BTC oversold, bet UP
  return False

g_xa_3source_trend_with(direction, fire_us, asset):
  # All 3 assets' RF directions UNANIMOUSLY agree at fire_us
  # (For ETH 5m fires: check BTC, ETH, SOL all have same RF direction)
  btc_rf = range_filter_1s["BTC"].rf_dir at (fire_us - 1_000_000)
  eth_rf = range_filter_1s["ETH"].rf_dir at (fire_us - 1_000_000)
  sol_rf = range_filter_1s["SOL"].rf_dir at (fire_us - 1_000_000)
  all_up = (btc_rf == 1 and eth_rf == 1 and sol_rf == 1)
  all_dn = (btc_rf == -1 and eth_rf == -1 and sol_rf == -1)
  return (all_up and direction == "UP") or (all_dn and direction == "DOWN")
```

### 3.5 — Cross-asset for SOL 15m (BTC/ETH features as gates)

```python
g_BTC_tr_stack(direction, fire_us):
  # BTC's traders' reality EMA stack score (direction-agnostic strength)
  score = traders_reality_1s["BTC"].tr_ema_stack_score at (fire_us - 1_000_000)
  return abs(score) >= 1   # at least some alignment

g_BTC_adx_strong(direction, fire_us):
  # BTC's ADX(14) on 5m regime panel — strong trend
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  adx = regime_panel_5m_v2_fixed["BTC"].adx_14 at ts
  return adx >= 25   # standard ADX strong threshold

g_BTC_vol_low(direction, fire_us):
  # BTC's realized_vol_60m below median of training window
  ts = asof_bar_end("BTC", "5m", fire_us - 1_000_000)
  rv = regime_panel_5m_v2_fixed["BTC"].realized_vol_60m at ts
  thr = 0.0042   # precomputed: median of BTC 5m rv_60m on May 1-22 training
  return rv < thr

g_ETH_adx_strong(direction, fire_us):
  # Same as BTC_adx_strong but for ETH
  ts = asof_bar_end("ETH", "5m", fire_us - 1_000_000)
  adx = regime_panel_5m_v2_fixed["ETH"].adx_14 at ts
  return adx >= 25

g_ETH_vol_low(direction, fire_us):
  ts = asof_bar_end("ETH", "5m", fire_us - 1_000_000)
  rv = regime_panel_5m_v2_fixed["ETH"].realized_vol_60m at ts
  thr = 0.0055   # precomputed median for ETH 5m rv_60m
  return rv < thr

g_BTC_slope_with(direction, fire_us):
  # Alias of g_btc_trend_30m_with but for SOL 15m fires
  ts = asof_bar_end("BTC", "15m", fire_us - 1_000_000)
  btc_slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(btc_slope): return False
  return (btc_slope > 0 and direction == "UP") or (btc_slope < 0 and direction == "DOWN")

g_BTC_slope_strong_with(direction, fire_us):
  ts = asof_bar_end("BTC", "15m", fire_us - 1_000_000)
  btc_slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(btc_slope): return False
  thr = 0.612   # precomputed p75 of |BTC 15m trend_slope_30m| training distribution
  return abs(btc_slope) > thr AND \
         ((btc_slope > 0 and direction == "UP") or (btc_slope < 0 and direction == "DOWN"))
```

### 3.6 — Pre-window cross-asset (for ETH 15m)

```python
g_pw_btc_15m_trend_with(direction, fire_us, asset):
  # At ws_s of the ETH 15m fire, check BTC's 15m trend_slope_30m direction
  ws_s_us = ws_s * 1_000_000
  ts = asof_bar_end("BTC", "15m", ws_s_us)
  btc_slope = regime_panel_15m_v2_fixed["BTC"].trend_slope_30m at ts
  if pd.isna(btc_slope): return False
  return (btc_slope > 0 and direction == "UP") or (btc_slope < 0 and direction == "DOWN")
```

### 3.7 — Regime ranging at ws_s

```python
g_regime_ranging_at_ws(direction, fire_us, asset):
  ws_s_us = ws_s * 1_000_000
  ts = asof_bar_end(asset, "5m", ws_s_us)
  label = regime_panel_5m_v2_fixed[asset].regime_label at ts
  return label == "ranging"
```

### 3.8 — CCI extreme (broader than V5/V6 cci_strong)

```python
g_cci_extreme_with(direction, fire_us, asset):
  cci = ta_indicators_1s[asset].cci_60s at (fire_us - 1_000_000)
  if pd.isna(cci): return False
  thr = 150.0   # extreme (vs V5's 100 "strong")
  return (cci > thr and direction == "UP") or (cci < -thr and direction == "DOWN")
```

### 3.9 — F7 v7 recomputed (full-coverage, replaces sparse V6 g_f7_rsi_with)

⚠ V7 SOL 5m agent caught that V6's `g_f7_rsi_with` had only 12% data coverage. V7 recomputes from scratch with full coverage.

```python
def compute_f7_v7(asset, ts_us):
  # Wilder simple-mean RSI, 7-period, 60s sample interval, last close at ts_us
  closes = binance_1s[asset].close at ts_us - i*60_000_000 for i in [840, 780, ..., 60, 0]
  # 15 closes, last at ts_us
  rsi = wilder_simple_mean_rsi(closes, period=7)
  return rsi

g_f7_v7_overbought(direction, fire_us, asset):
  rsi = compute_f7_v7(asset, fire_us - 1_000_000)
  return rsi >= 70

g_f7_v7_oversold(direction, fire_us, asset):
  rsi = compute_f7_v7(asset, fire_us - 1_000_000)
  return rsi <= 30
```

---

## 4. The 12 selected sleeve specifications

For each sleeve: fire when ALL listed gates pass at the specified anchor. Then run `g_book_supports_stake` as FILL-TIME veto.

---

### Sleeve 01 — BTC_5M_PARENT15M_SLOPE_TS_MPNX_V7

```
asset             = BTC
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = ALL (V7 used parent_15m anchor across all 5m offsets — 30..270)
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_parent_15m_slope_with(direction, fire_us, asset="BTC")
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")
  g_mp_no_extreme(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=80 WR 83.8% $/tr +$5.85 | val n=49 WR 83.7% $/tr +$6.02 | lockbox n=428 WR 77.6% $/tr +$9.51 | DD $289 | LS 11 | bs_p 0.000 | **32.7d projection $33,228** | Annual **$371,603**.
Status: **DEPLOY** — best $/tr_v stability + highest 32.7d projection.

---

### Sleeve 02 — BTC_5M_SLOTEND_OFI_TS_V7 ⚠ EXPERIMENTAL

```
asset             = BTC
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {240, 270}    # ONLY late offsets — else g_slot_end_ofi_with is lookahead
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_slot_end_ofi_with(direction, fire_us, slug, slot_end_us)   # MUST validate offset >= 240s
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=222 WR 98.6% $/tr +$1.01 | val n=77 WR 94.8% $/tr +$0.68 | lockbox n=390 WR 92.3% $/tr +$4.28 | DD **$97** | LS **3** | bs_p 0.000 | **32.7d $13,618** | Annual **$152,293**.
Status: **DEPLOY** — best DD/LS profile of BTC 5m roster. ⚠ Treat as experimental — research said this approach fails for 15m. Monitor first 100 fires for OFI gate sign drift.

---

### Sleeve 03 — BTC_5M_PARENT15M_NOTRANG_TS_MPSKEW_V7

```
asset             = BTC
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = ALL (parent_15m anchor)
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_parent_15m_not_ranging(direction, fire_us, asset="BTC")    # direction-agnostic — both UP and DOWN allowed when parent isn't ranging
  g_trend_slope_strong_with(direction, fire_us, asset="BTC", tf="5m")
  g_mp_skew_with(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=164 WR 94.5% $/tr +$4.31 | val n=18 WR 88.9% $/tr +$1.60 | lockbox n=161 WR 93.2% $/tr +$15.38 | DD $250 | LS 10 | bs_p 0.000 | **32.7d $20,224** | Annual **$226,178**.
Status: **DEPLOY**.

---

### Sleeve 04 — ETH_5M_CLOUD_VWAP_HURSTMP_V7 🎯 PRIMARY for ETH 5m

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 60
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_cloud(direction, fire_us, asset="ETH")
  g_entry_vwap_in_band(direction, fire_us, slug)              # vwap_book ∈ [0.20, 0.80]
  g_hurst_mp_trend_with(direction, fire_us, asset="ETH", slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=41 WR 61.0% $/tr +$4.12 | val n=40 WR 65.0% $/tr +$4.09 | lockbox n=82 WR 81.7% $/tr **+$14.12** | DD **$50** | LS 2 | bs_p 0.000 | **32.7d $9,454** | Annual **$105,725**.
Status: **DEPLOY PRIMARY** — highest $/tr in ETH 5m roster.

---

### Sleeve 05 — ETH_5M_EMA50_HURST_PARENT15MRANG_V7

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 60
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_ema50(direction, fire_us, asset="ETH")
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")
  g_parent15m_ranging(direction, fire_us, asset="ETH")        # ETH 15m parent must be ranging

fill_time_veto: g_book_supports_stake
```

Backtest: train n=275 WR 78.5% $/tr +$1.61 | val n=194 WR 80.9% $/tr +$4.48 | lockbox n=279 WR 79.2% $/tr +$5.72 | DD $117 | LS 2 | bs_p 0.000 | **32.7d $13,039** | Annual **$145,826**.
Status: **DEPLOY** — highest n_lockbox / volume in ETH 5m roster.

**KEY INSIGHT**: ETH 5m alpha is BIGGEST when 15m parent is RANGING (mean-reversion regime).

---

### Sleeve 06 — ETH_5M_V6C3_PLUS_PARENT15MRANG_V7

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 60
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_cloud(direction, fire_us, asset="ETH")
  g_ribbon_agrees(direction, fire_us, asset="ETH")
  g_mp_skew_with(direction, fire_us, slug)
  g_hurst_trending(direction, fire_us, asset="ETH", tf="5m")
  g_parent15m_ranging(direction, fire_us, asset="ETH")

fill_time_veto: g_book_supports_stake
```

Backtest: train n=160 WR 76.9% $/tr +$1.01 | val n=114 WR 86.8% $/tr +$5.35 | lockbox n=163 WR 83.4% $/tr +$8.39 | DD $93 | LS 2 | bs_p 0.000 | **32.7d $11,170** | Annual **$124,921**.
Status: **DEPLOY** — extends V6 c3 (deploy spec sleeve 03) with parent_ranging confluence.

---

### Sleeve 07 — ETH_5M_EMA200_VWAP_REGIMERANG_XA3_V7

```
asset             = ETH
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = 90
window_s          = 300
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_above_ema200(direction, fire_us, asset="ETH")
  g_entry_vwap_in_band(direction, fire_us, slug)
  g_regime_ranging_at_ws(direction, fire_us, asset="ETH")     # ETH 5m's OWN regime at ws_s
  g_xa_3source_trend_with(direction, fire_us, asset="ETH")    # all 3 asset RFs agree

fill_time_veto: g_book_supports_stake
```

Backtest: train n=34 WR 58.8% $/tr +$2.25 | val n=23 WR 73.9% $/tr +$9.96 | lockbox n=48 WR 81.2% $/tr +$14.47 | DD $53 | LS 2 | bs_p 0.000 | **32.7d $5,670** | Annual **$63,404**.
Status: **DEPLOY** — cross-asset unanimity sleeve; high $/tr but small n.

---

### Sleeve 08 — SOL_5M_BTCTREND_CCI_HURSTREV_V7 🎯 PRIMARY for SOL 5m

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = ALL (mixed 30-240s)
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_btc_trend_30m_with(direction, fire_us)                     # BTC 5m trend slope matches direction
  g_cci_extreme_with(direction, fire_us, asset="SOL")          # cci_60s > 150 or < -150
  g_hurst_reverting(direction, fire_us, asset="SOL", tf="5m")  # SOL hurst < 0.40 (mean-revert regime)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=412 WR 71.8% $/tr +$1.83 | val n=202 WR 71.8% $/tr +$8.82 | lockbox n=45 WR 82.2% $/tr +$12.59 | DD $66 | LS **1** | bs_p 0.000 | **32.7d $4,625** | Annual **$51,727**.
Status: **DEPLOY PRIMARY** — best stability + lowest LS in SOL 5m roster.

**KEY INSIGHT**: SOL 5m wins on MEAN-REVERSION (hurst < 0.40) regime + BTC trend confluence — opposite of BTC/ETH which want trending regimes.

---

### Sleeve 09 — SOL_5M_BTCF7_F7OVERB_EMA800_VWAP_V7 ⚠ EXPERIMENTAL

```
asset             = SOL
tf                = 5m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          = ALL (mixed)
window_s          = 300
spread_filter     = 0.025

gates_all_must_pass:
  g_btc_f7_with(direction, fire_us)                            # BTC F7 RSI extreme matching direction
  g_f7_v7_overbought(direction, fire_us, asset="SOL")          # SOL F7 RSI >= 70 (full-coverage v7 calc)
  g_tr_above_ema800(direction, fire_us, asset="SOL")
  g_vwap_in_45_85(direction, fire_us, slug)

fill_time_veto: g_book_supports_stake
```

Backtest: train n=477 WR 72.7% $/tr +$2.42 | val n=231 WR 64.1% $/tr **−$0.92** ⚠ | lockbox n=190 WR 82.1% $/tr +$5.55 | DD $125 | LS 6 | bs_p 0.000 | **32.7d $8,617** | Annual **$96,367**.
Status: **DEPLOY (EXPERIMENTAL)** — ⚠ val $/tr NEGATIVE. May be overfit. Highest 28d volume in SOL 5m. Treat as exploratory; monitor first 50 fires; suspend if live WR < 70%.

---

### Sleeve 10 — ETH_15M_PI_BTC15M_TREND_V7 🎯 PRE-WINDOW + CROSS-ASSET

```
asset             = ETH
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {0, 30, 60}    # offset_early
window_s          = 900
spread_filter     = 0.02

gates_all_must_pass:
  g_tr_stack_full_with(direction, fire_us, asset="ETH")
  g_above_1h_dailyvwap_with(direction, fire_us, asset="ETH")
  g_offset_early(fire_us, slot_start_us)
  g_vol_high(direction, fire_us, asset="ETH", tf="15m")
  g_pw_btc_15m_trend_with(direction, fire_us, asset="ETH")    # PRE-WINDOW: BTC 15m trend at ETH ws_s

fill_time_veto: g_book_supports_stake
```

Backtest: train n=35 WR 80.0% $/tr +$9.62 | val n=8 WR 62.5% $/tr +$1.84 | lockbox n=21 WR **95.2%** $/tr +$12.28 | DD $75 | LS 3 | bs_p 0.000 | **32.7d $2,106** | Annual **$23,548**.
Status: **DEPLOY** — first sleeve to combine ETH's own pre-window stack with BTC pre-window trend (cross-asset + pre-window double signal).

⚠ This sleeve OVERLAPS with V6 sleeve 08 (`ETH_15M_PW_TRENDSLOPE_TRSTACK_VWAP_VOL_OFFEARLY_V6`) per overlap audit. Per operator: deploy both in shadow to compare.

---

### Sleeve 11 — SOL_15M_BTC_SLOPE_PAIR_V7 🎯 PRIMARY for SOL 15m

```
asset             = SOL
tf                = 15m
direction         = {UP, DOWN}
slug_source       = "any"
offset_s          ∈ {60, 120, 240}    # g_off_60_240
window_s          = 900
spread_filter     = 0.025

gates_all_must_pass:
  g_hod_european_morning(fire_us)
  g_off_60_240(fire_us, slot_start_us)
  g_rf_with(direction, fire_us, asset="SOL")
  g_tr_stack_with(direction, fire_us, asset="SOL")
  vwap_book = book_walk_vwap_for(direction, slug, fire_us, stake=25)
  vwap_book < 0.80
  g_BTC_slope_with(direction, fire_us)            # BTC 15m trend slope sign matches direction
  g_BTC_slope_strong_with(direction, fire_us)     # AND magnitude > p75 threshold

fill_time_veto: g_book_supports_stake
```

Backtest: train n=52 WR 69.2% $/tr +$3.32 | val n=10 WR 80.0% $/tr +$6.41 | lockbox n=18 WR 88.9% $/tr +$10.78 | DD $38 | LS 1 | bs_p 0.033 | **32.7d $1,584** | Annual **$17,712**.
Status: **DEPLOY** — best SOL 15m 32.7d. Cross-asset BTC slope confluence on V6 base.

---

### Sleeve 12 — SOL_15M_BTC_ADX_BTCVOLLOW_V7

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
  vwap_book < 0.80
  g_BTC_tr_stack(direction, fire_us)              # BTC EMA stack at least partial alignment
  g_BTC_adx_strong(direction, fire_us)            # BTC ADX >= 25 (strong trend)
  g_BTC_vol_low(direction, fire_us)               # BTC realized vol below median

fill_time_veto: g_book_supports_stake
```

Backtest: train n=15 WR 73.3% $/tr +$2.75 | val n=3 WR 100% $/tr +$17.27 | lockbox n=16 WR 93.8% $/tr +$12.18 | DD **$25** | LS **1** | bs_p 0.033 | **32.7d $1,591** | Annual **$17,788**.
Status: **DEPLOY** — best DD in SOL 15m roster (val n=3 thin).

---

## 5. Sleeve registry — flat table

```
#  sleeve_id                                       asset tf   dir  offset      spread  gates  status
01 BTC_5M_PARENT15M_SLOPE_TS_MPNX_V7              BTC   5m   BOTH ALL         0.02    3      DEPLOY 🎯
02 BTC_5M_SLOTEND_OFI_TS_V7                       BTC   5m   BOTH 240,270     0.02    2      DEPLOY (experimental)
03 BTC_5M_PARENT15M_NOTRANG_TS_MPSKEW_V7          BTC   5m   BOTH ALL         0.02    3      DEPLOY
04 ETH_5M_CLOUD_VWAP_HURSTMP_V7                   ETH   5m   BOTH 60          0.02    3      DEPLOY 🎯
05 ETH_5M_EMA50_HURST_PARENT15MRANG_V7            ETH   5m   BOTH 60          0.02    3      DEPLOY (vol)
06 ETH_5M_V6C3_PLUS_PARENT15MRANG_V7              ETH   5m   BOTH 60          0.02    5      DEPLOY
07 ETH_5M_EMA200_VWAP_REGIMERANG_XA3_V7           ETH   5m   BOTH 90          0.02    4      DEPLOY
08 SOL_5M_BTCTREND_CCI_HURSTREV_V7                SOL   5m   BOTH ALL         0.025   3      DEPLOY 🎯
09 SOL_5M_BTCF7_F7OVERB_EMA800_VWAP_V7            SOL   5m   BOTH ALL         0.025   4      DEPLOY (experimental)
10 ETH_15M_PI_BTC15M_TREND_V7                     ETH   15m  BOTH 0,30,60     0.02    5      DEPLOY (overlaps V6_08)
11 SOL_15M_BTC_SLOPE_PAIR_V7                      SOL   15m  BOTH 60,120,240  0.025   7      DEPLOY 🎯
12 SOL_15M_BTC_ADX_BTCVOLLOW_V7                   SOL   15m  BOTH 60,120,240  0.025   8      DEPLOY
```

## 6. Execution params (all 12 sleeves)

```
notional_default_usd  = 25.0
notional_ramp_start   = 5.0
fill_method           = L25_book_walk
fill_min_book_events  = 25
hold_to               = slot_end_us
fee_model             = legacy_2pct_profit
latency_budget_ms     = 85

# MANDATORY for V7 (same as V6)
fill_time_veto        = g_book_supports_stake(direction, fire_us, slug, stake=notional_usd)
```

## 7. Shadow logging — V7 additions

Extend V6 schema (§7 of V6 spec) with:

```
+ sleeve_version          : "V7"
+ cross_asset_features    : {btc_trend_30m, btc_f7_rsi, btc_adx_14, btc_vol_60m, eth_trend_30m, eth_adx_14, eth_vol_60m}
+ parent_15m_label        : "trending_up" | "trending_dn" | "ranging" (when sleeve uses g_parent_15m_*)
+ hurst_at_slot           : float
+ f7_v7_at_fire           : float (when sleeve uses g_f7_v7_*)
+ slot_end_ofi_60s        : float (when sleeve uses g_slot_end_ofi_with)
```

## 8. Threshold constants (V7 additions)

```python
hurst_reverting_thr      = 0.40
hurst_regime_with_thr    = 0.55
cci_extreme_thr          = 150.0
slot_end_ofi_thr_usd     = 100.0
adx_strong_thr           = 25.0

# Precomputed medians of training window (May 1-22)
btc_rv_60m_median        = 0.0042
eth_rv_60m_median        = 0.0055
sol_rv_60m_median        = 0.0071

# trend_slope_30m p75 strong thresholds (training window)
btc_5m_slope_p75         = 0.385
eth_5m_slope_p75         = 0.398
sol_5m_slope_p75         = 0.412
btc_15m_slope_p75        = 0.612
eth_15m_slope_p75        = 0.624
sol_15m_slope_p75        = 0.643

f7_v7_overbought_thr     = 70
f7_v7_oversold_thr       = 30
```

## 9. Open items — V7 caveats

1. **Sleeve 02 (slot-end OFI)** — V7 research showed slot-end OFI fails for BTC 15m (regime flip). Agent claimed it works for BTC 5m. Monitor live closely; if val WR < 80% over first 100 fires, suspend.

2. **Sleeve 09 (BTC F7 + SOL F7 overbought)** — val $/tr = −$0.92. Risky. Deploy at $5 stake only. Suspend if live WR < 70% over first 50 fires.

3. **Sleeve 10 (ETH 15m PI + BTC 15m trend)** — overlaps with V6 sleeve 08 per overlap audit. Operator approved running both in shadow for comparison.

4. **`g_parent_15m_regime_with` family** — uses 15m regime panel asof. Production must have `regime_panel_15m_v2_fixed` available live, OR compute regime label from 15m binance close + ADX in real time.

5. **`g_xa_3source_trend_with`** — requires real-time access to ALL THREE assets' range_filter_1s computations. Production must have RF service running per asset.

6. **`g_f7_v7_overbought` / `g_f7_v7_oversold`** — V7 recomputed F7 with FULL coverage (V6's gate had 12% sparse coverage). Production MUST use the v7 computation (Wilder simple-mean RSI 7-period, 60s sample, last close at fire_us), not the V6 sparse calc.

7. **Cross-asset gates** (BTC features → ETH/SOL fires, ETH features → SOL fires) require synchronized real-time feature pipelines across all 3 assets. TV must verify pipeline latency is < 1s for all assets.

8. **Slug overlap with V5+V6**: 7 of these 12 V7 sleeves overlap with existing V5/V6 in-shadow sleeves per overlap audit. Operator approved deploying all in shadow for measurement purposes — no need to dedupe for shadow validation.

---

## END
