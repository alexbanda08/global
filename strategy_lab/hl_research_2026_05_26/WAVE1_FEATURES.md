# Wave 1 — HL Feature Panel

**Generated:** 2026-05-26 by panel-builder-agent
**Script:** `strategy_lab/hl_research_2026_05_26/build_hl_panel.py`
**Output dir:** `strategy_lab/hl_research_2026_05_26/panels/`
**Summary CSV:** `strategy_lab/hl_research_2026_05_26/panels/_panels_summary.csv`

---

## TL;DR

24 panels saved. ~1.6 GB total (Binance backbone dominates). The full Polymarket research indicator stack
ports cleanly to HL/Binance OHLCV bars. The orthogonal-edge gates (SMS `liquidity_up/dn`, DRZ
`drz_recent_RC/RE`, QR `qr_volume_ratio/qr_health/qr_confidence`) are all populated and bar-causal.

**Coverage:**

| Source | Assets | TFs | Time range (max) | Panels |
|---|---|---|---|---|
| Binance spot backbone | BTC, ETH, SOL | 5m, 15m, 1h, 4h | BTC/ETH 2017-08-17 → 2026-03-31, SOL 2020-08-11 → 2026-03-31 | 12 |
| HL native perp | BTC, ETH, SOL, HYPE | 15m, 1h, 4h | 2026-01-30 → 2026-05-16 (4h/1h), 2026-03-09 → 2026-05-16 (15m) | 12 |

---

## Final feature list

Each panel has **143 columns**. Grouped by family:

### 1. Identifier / OHLCV (~12 cols)
`ts_us, open_time, open, high, low, close, volume, asset, tf` plus (Binance only)
`quote_volume, trades, taker_buy_base, taker_buy_quote`.

### 2. ema_basic (7)
`ema_5, ema_13, ema_21, ema_50, ema_100, ema_200, ema_800`

### 3. classic_ta (11)
`rsi_14` (Wilder simple-mean, production-parity), `atr_14`, `adx_14`, `plus_di_14`, `minus_di_14`,
`stoch_k_14`, `stoch_d_3`, `bb_pos_20`, `bb_width_20`, `mfi_14`, `cci_20`.

### 4. madrid (6)
`ribbon_lead_slope_bps, ribbon_lead_vs_ref_bps, ribbon_alignment_pct, ribbon_compression_bps,
ribbon_color (0-4), tight_ribbon (bool — compression<2bps)`.

### 5. qr (5)
`qr_state (-2..+2), qr_regime (0/1), qr_health (0..100), qr_confidence (0..8), qr_volume_ratio`.

### 6. sms (~26)
`pivot_high, pivot_low, last_high, last_low, last_high_prev, last_low_prev,
bos_buy, bos_sell, choch_buy, choch_sell, bars_since_bos_buy, bars_since_bos_sell,
bars_since_choch_buy, bars_since_choch_sell, rsi_div_bull, rsi_div_bear,
cvd_60s, cvd_120s, cvd_300s, liquidity_up, liquidity_dn,
recent_high_20, recent_low_20, trend_self, trend_parent, trend_strength_multi_tf`.

### 7. tr (Traders Reality, ~36)
EMA stack: `tr_ema_5/13/50/200/800, tr_ema_stack_score (-2..+2), cloud_size_bps`.
PVSRA: `pvsra_class (-2..+2), bars_since_climax_up, bars_since_climax_dn`.
Daily pivots: `dayHigh, dayLow, dayOpen, dayClose, PP, R1-R3, S1-S3, M0-M5,
close_vs_pp_bps, close_vs_dayopen_bps, tr_above_pp`.
Range: `adr, adr_high, adr_low, tr_within_adr, awr, weekHigh, weekLow`.
Sessions: `tr_in_london, tr_in_ny, tr_in_tokyo`.
Psy: `psy_hi, psy_lo, close_vs_psy_hi_bps, close_vs_psy_lo_bps, within_psy_band`.

### 8. rf (Donovan Wall Range Filter, 10)
`rf_close, rf_hi_band, rf_lo_band, rf_r, rf_dir (-1/0/+1), rf_dir_age,
rf_dist_bps, rf_band_pos, rf_in_band, rf_aged (age≥5), rf_fresh (age≤2)`.

### 9. regime (2)
`regime_label` ∈ {trending_up, trending_dn, ranging}; `regime_score` ∈ [-1, +1].

### 10. markov (2)
`markov_state` (vol-adaptive q33/q66 of 20-bar log-returns over trailing 14d) and
`markov_state_fixed` (asset-specific threshold — BTC ±0.3%, ETH ±0.4%, SOL ±0.6%, HYPE ±0.8%).
Values are -1=BEAR / 0=SIDEWAYS / +1=BULL, NaN during warmup.

### 11. drz (8)
`drz_in_support_zone, drz_in_resistance_zone, drz_dist_sup_bps, drz_dist_res_bps,
drz_dist_bps (signed dist to nearest active zone), drz_n_zones,
drz_recent_RC (5-bar look-back), drz_recent_RE`.

### 12. hl_extra (7)
`hl_funding_rate, hl_funding_annualized, hl_funding_z (30d rolling z),
hl_liq_long_size_sum_60m, hl_liq_short_size_sum_60m, hl_liq_cascade_60m, hl_oi`.

---

## Row counts per panel

### Binance backbone (12 panels)

| asset | tf | rows | size_mb | start | end |
|---|---|---:|---:|---|---|
| BTC | 5m  | 905,161 | 348.3 | 2017-08-17 | 2026-03-31 |
| BTC | 15m | 301,726 | 127.0 | 2017-08-17 | 2026-03-31 |
| BTC | 1h  | 75,445  | 36.6  | 2017-08-17 | 2026-03-31 |
| BTC | 4h  | 18,876  | 9.5   | 2017-08-17 | 2026-03-31 |
| ETH | 5m  | 905,161 | 340.7 | 2017-08-17 | 2026-03-31 |
| ETH | 15m | 301,726 | 125.0 | 2017-08-17 | 2026-03-31 |
| ETH | 1h  | 75,445  | 35.8  | 2017-08-17 | 2026-03-31 |
| ETH | 4h  | 18,876  | 9.4   | 2017-08-17 | 2026-03-31 |
| SOL | 5m  | 592,637 | 217.4 | 2020-08-11 | 2026-03-31 |
| SOL | 15m | 197,547 | 83.9  | 2020-08-11 | 2026-03-31 |
| SOL | 1h  | 49,391  | 22.9  | 2020-08-11 | 2026-03-31 |
| SOL | 4h  | 12,353  | 6.1   | 2020-08-11 | 2026-03-31 |

### HL native (12 panels)

| asset | tf | rows | size_mb | start | end |
|---|---|---:|---:|---|---|
| BTC  | 15m | 6,429 | 2.8 | 2026-03-09 | 2026-05-16 |
| BTC  | 1h  | 2,511 | 1.2 | 2026-01-30 | 2026-05-16 |
| BTC  | 4h  | 635   | 0.3 | 2026-01-30 | 2026-05-16 |
| ETH  | 15m | 6,429 | 2.8 | 2026-03-09 | 2026-05-16 |
| ETH  | 1h  | 2,535 | 1.2 | 2026-01-30 | 2026-05-16 |
| ETH  | 4h  | 635   | 0.4 | 2026-01-30 | 2026-05-16 |
| SOL  | 15m | 6,428 | 2.8 | 2026-03-09 | 2026-05-16 |
| SOL  | 1h  | 2,535 | 1.2 | 2026-01-30 | 2026-05-16 |
| SOL  | 4h  | 635   | 0.4 | 2026-01-30 | 2026-05-16 |
| HYPE | 15m | 6,420 | 2.8 | 2026-03-09 | 2026-05-16 |
| HYPE | 1h  | 2,535 | 1.2 | 2026-01-30 | 2026-05-16 |
| HYPE | 4h  | 635   | 0.4 | 2026-01-30 | 2026-05-16 |

**Total disk:** ~1.6 GB.

---

## NaN audit (highlights)

Per-family % NaN, averaged across panels. **>10% flagged.** All others are within expected warmup behavior.

| Family | Binance avg | HL avg | Notes |
|---|---:|---:|---|
| classic_ta  | 0.03% | 0.7-2.8% | RSI/ATR/ADX/Stoch/BB/MFI/CCI all dense after warmup. |
| ema_basic   | 0.4% | 2.6-22.9% | EMA800 needs ≥800 bars; 4h HL panel has 635 bars total so ema_800 NaN-dominant there. **Expected.** |
| madrid      | 0.04% | 0.5-5.4% | 20×EMA(5..100), needs 100-bar warmup. |
| qr          | 0.0% | 0.0% | QR Lite is fully populated from bar 60 onward (longest EMA in pair set = 60). |
| sms         | **11.7%** | **11.7%** | **>10% flag** — driven by `trend_parent` NaN on bars before the first parent-TF bar warmup, plus first 20 bars of `recent_high/low_20`. Acceptable — these are causal rolling features. |
| tr          | 0.05% | 1.7-6.1% | TR EMA stack (200/800) needs 800-bar warmup. |
| rf          | <0.001% | <0.02% | Range Filter is iterative — populated from bar 0. |
| regime      | 0.002% | 0.2-2.0% | Needs ADX warmup. |
| markov      | 0.2-0.5% | **7.4-10.8%** | **>7% on HL panels** — driven by 14d × bars_per_day calib window. On 5m the warmup is ~4 days; on 4h it's smaller in absolute but a large % of the (short) HL series. **Expected per algorithm; not a bug.** |
| drz         | 0.3-0.9% | 0.4-2.0% | ATR + pivot warmup. |
| hl_extra    | **56% on Binance** | **11-13% on HL** | **Binance NaN by design:** HL funding/liq/oi only exist from 2026-01-30; Binance panels go back to 2017. Bars before HL data start are NaN. HL panels: 11-13% NaN concentrated at the START of the series (before first funding/metrics tick). |

**rsi_14:** in [0, 100] on every panel (verified during sanity print).
**atr_14:** > 0 on every panel (verified).

---

## Causal-anchor convention

- Each feature at row i depends ONLY on bars `[0..i]` (closed bars).
- Bar i's `ts_us` is bar START.
- Bar i CLOSE is at `ts_us + tf_seconds * 1_000_000 - 1`.
- Trade convention: signal computed at row i CLOSE → trade fills at row i+1 OPEN.
- All asof-merges (HL funding, liq, OI, parent-TF trend) use `direction='backward'` with the
  parent series KEYED at its bar CLOSE = `ts_us + tf_sec * 1_000_000`. This guarantees the
  child bar at start `T` only sees parent bars that have FULLY CLOSED by `T`.
- `cvd_60s/120s/300s` are ROLLING-window sums (not cumulative). On 5m bars `cvd_60s` reduces
  to the current bar; on 1h+ TFs it spans 1 bar (window/tf_min < 1 → clamped to 1).
- DRZ pivots use lookforward of `PIVOT_LB=12` bars **to confirm a pivot**; the pivot is
  RECORDED at confirmation bar i (not center i-12), so the indicator state at row i is
  derived only from bars ≤ i. Zones become "active" at confirmation, not at center bar.

---

## Decisions made

1. **DRZ ATR window = 14**, zone half-width = `ATR(14) * 0.35`, pivot lookback = 12. Identical
   to Polymarket reference (`compute_drz_panel.py`). No per-asset calibration — that's
   out-of-scope for Wave 1.
2. **Markov fixed thresholds per asset:** BTC ±0.3%, ETH ±0.4%, SOL ±0.6%, HYPE ±0.8%
   (heuristic by 20-bar realized vol, NOT calibrated). The vol-adaptive variant
   (`markov_state`) is the primary; `markov_state_fixed` is for ablation.
3. **Multi-TF trend strength = `trend_self + trend_parent`** only (own TF + immediate parent),
   range [-2..+2]. The Polymarket SMS computed 7-TF stack (1m/5m/15m/30m/1h/4h/D) — deferred
   to Wave 2 because the deeper TFs would require multiple parent loads per panel and
   marginal predictive value (per registry §4.4: standalone C_trend_strength loses
   −$0.62/tr anyway).
4. **CVD windows in seconds → bars:** `cvd_60s` on a 5m panel = 1 bar (clamp to ≥1). On 15m
   panel = 1 bar (60/15 = 0.07, clamps to 1). On 1m panel = 1 bar. To get TRUE 60s CVD on
   5m bars you'd need to pull 1s data — deferred (1s bars are not part of Wave 1 scope).
5. **Sessions** use UTC hours: London 07-16, NY 12-21, Tokyo 23-08 (wraps midnight via OR).
6. **PsyLevels** anchored at Sat 22:00 UTC (`PSY_OFFSET_S = 5*86400 + 22*3600` from Unix epoch
   Thursday).
7. **HL liquidations:** the `_30d.parquet` file mixes regular fills with true Liquidated*
   rows. The panel uses `is_liq_event` (rows whose `dir` starts with "Liquidated" or
   "Auto-Deleveraging") **if any are present in the 60-min window**; else falls back to the
   `side=A/B` proxy from Strategy C (A=long-liq, B=short-liq). True-liq events are sparse
   (24,878 over 12 months in the FULL file) so the fallback often kicks in.
8. **Binance backbone end date = 2026-03-31** — pre-dates today (2026-05-26) by ~2 months.
   The `gsd-add-todo` item "Background: pull Binance Vision delta (Apr-May 2026)" is open
   for this. HL native panels are current through 2026-05-16 so any strategy targeting
   the most-recent 6 weeks should run on HL panels.

---

## Sanity checks

- **rsi_14 ∈ [0, 100]** on every panel: PASS.
- **atr_14 > 0** on every panel: PASS.
- **regime_label** populated with one of {trending_up, trending_dn, ranging}: PASS.
- **markov_state ∈ {-1, 0, 1, NaN}**: PASS.
- **rf_dir ∈ {-1, 0, +1}**: PASS.
- **pivot_high/low** is NaN by default and only set when a pivot confirms: PASS.
- **liquidity_up/dn** is 0/1 int8: PASS.
- **HL funding asof-joined** — final BTC/5m row at 2026-03-31 23:55 has `hl_funding_rate=-1.6e-5`
  (from Jan-2026+ funding history): PASS, no lookahead.
- **Panel for HYPE/15m HL native** has 6,420 rows over 68 days = ~94 bars/day = 1 bar / 15.3 min:
  matches expected 96 bars/day with ~2% gap from the documented HL klines gap rate.

---

## Deferred (will become Wave 2 / Wave 3 work)

- **1s panel** (Madrid ribbon + TR + RF on 1s bars) — Polymarket uses this; we don't have HL
  1s yet. Would require pulling HL trades and bucketing to 1s.
- **Cross-asset xa_all_with_bet / xa_maj_with_bet** — needs joining BTC + ETH + SOL panels
  on a synced timestamp grid. Plan was to defer to Wave 2.
- **Microprice / spread features** — requires HL L25 book parquets (the HL S3 archive is
  downloaded but not parsed; per EXISTING_HL_STRATS.md §5.5 it's a known engineering gap).
- **Fair value (Black-Scholes UP/DOWN)** — needs a strike reference; the HL-native version
  would compare implied perp fair vs perp mark over a short horizon. Need to design the
  reference (NOT chainlink RTDS — that's Polymarket-specific).
- **HoD-Top-8** — strategy-conditional historical learning. Not a panel feature, will live
  in Wave 4 sizing/routing.
- **Binance Vision delta pull (Apr-May 2026)** — open as pending task #9. Once landed,
  rebuild Binance panels to extend coverage to today.

---

## How to use

```python
import pandas as pd
panel = pd.read_parquet("strategy_lab/hl_research_2026_05_26/panels/hl_panel_BTC_5m.parquet")

# Causal slice for backtest:
win = panel[(panel["ts_us"] >= pd.Timestamp("2025-01-01", tz="UTC").value // 1000) &
            (panel["ts_us"] <  pd.Timestamp("2026-04-01", tz="UTC").value // 1000)]

# Star feature (SMS liquidity reclaim): trade UP after liquidity_dn fires (sweep low + body up)
mask_up = (win["liquidity_dn"] == 1) & (win["bos_buy"] == 1)

# DRZ gate (don't bet INTO opposing zone):
not_contra = ~((win["drz_in_resistance_zone"] == 1) & (predicted_direction == "UP"))

# Regime routing:
routed = win[win["regime_label"] == "trending_up"]
```

Builder is idempotent — re-run with `py strategy_lab/hl_research_2026_05_26/build_hl_panel.py`.

---

**End of Wave 1 report.**
