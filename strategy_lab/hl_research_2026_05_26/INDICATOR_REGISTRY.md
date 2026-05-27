# Indicator + Gate Registry — Hyperliquid Port

**Built:** 2026-05-26
**Scope:** Exhaustive enumeration of every indicator / gate / feature found
across the Polymarket up-down research archive. Each entry is annotated for
Hyperliquid-perp portability.

**Source set:**
- `strategy_lab/reports/TA_INDICATORS_MEGA_RUN_2026_05_23.md`
- `strategy_lab/reports/INDICATOR_SURVEY_2026_05_22.md`
- `strategy_lab/reports/NEW_INDICATORS_COMBINATORIAL_2026_05_23.md`
- `strategy_lab/reports/RANGE_FILTER_PANEL_2026_05_25.md`
- `strategy_lab/reports/TRADERS_REALITY_PANEL_2026_05_25.md`
- `strategy_lab/reports/POLYMARKET_FEATURES_UNIVARIATE.md`
- `strategy_lab/reports/MARKOV_VS_F7_PER_SLEEVE_2026_05_21.md`
- `strategy_lab/reports/_indicator_inventory_inbox.md`
- `strategy_lab/reports/_indicator_overlay_inbox.md`
- `strategy_lab/reports/NEW_SLEEVES_ENTRY_RULES_2026_05_23.md`
- `strategy_lab/reports/DRZ_BACKTEST_2026_05_26.md`
- `strategy_lab/reports/QR_BACKTEST_2026_05_26.md`
- `strategy_lab/reports/SMS_BACKTEST_2026_05_26.md`
- `strategy_lab/reports/REGIME_CONDITIONAL_2026_05_26.md`
- `strategy_lab/reports/POLYMARKET_V2_SIGNALS_FINDINGS.md`
- Cross-ref: `strategy_lab/reports/NEW_INDICATORS_SYNTHESIS_2026_05_26.md`
- Cross-ref: `strategy_lab/reports/PER_SLEEVE_CATALOG_2026_05_26.md`

**Portability scale (HL-port score):**
- **5** — Computes from binance/HL kline alone. Trivial port. Same code path on HL.
- **4** — Kline + one extra liquid feed (taker buy ratio, OI, funding). Easy on HL.
- **3** — Needs HL L25 book OR HL trades tape. Available but new wiring.
- **2** — Needs an extra venue (cross-asset BTC/ETH/SOL) or specialized panel.
- **1** — Polymarket-specific (book is binary 0–1, slug semantics, chainlink RTDS strike, or P-only flow). Does NOT port.

---

## Table of contents

1. Classic TA primitives (RSI / MACD / EMA / ATR / ADX / Stoch / BB / MFI / CCI / OBV)
2. Ribbon variants (Madrid 5–100, QR Lite 21–60, tight/compressed, strong/expanded)
3. Volume / flow (CVD by window, RVOL, MFI variants, volume_ratio, signed taker)
4. Structure (SMS: CHoCH/BOS, liquidity sweep, RSI divergence, multi-TF stack)
5. Traders Reality (PVSRA candles, pivot/Camarilla, EMA stack 5/13/50/200/800, sessions, psy)
6. Range Filter [DW] / DRZ (Donovan Wall, ATR zones, RC/RE signals)
7. Regime (ADX 3-state, Markov M1V/M1F/M5V/M5F, rule-based trend/sideways/volatile)
8. Cross-asset (xa_all_with_bet, xa_maj_with_bet, MTF confluence, BTC lead-lag, premium)
9. VWAP-anchored (slot-anchored S1.5, 15m bucket, vwap_50_85 sweet zone, micro-vwap)
10. Calendar / session (HoD-Top-8, active session, day-of-week, psy week)
11. F-series wallet gates (F1-F9 incl. F7 RSI Wilder simple-mean)
12. Polymarket-only signals (entry vwap, microprice, PM dip, slug-age, sparse book)
13. Fair value / probabilistic (Black-Scholes UP/DOWN, z-score, mispricing edge)
14. Funding / OI / liquidations (HL native + binance metrics)
15. Smart-money & guard filters (FVG, S/R swings, liq magnet, OFI, choppiness)
16. Composite / meta-classifier (`prob_a/b/c/stack`, signal_confidence, market_health)
17. Combinatorial gates (the 13-gate library used by NEW_INDICATORS_COMBINATORIAL)
18. Negative / kill-listed features (what the archive proves DOESN'T work)
19. **HL-port shortlist (top 25)**

---

## 1. Classic TA primitives

### 1.1 RSI(14) Wilder simple-mean — `rsi_14`

- **What:** Wilder relative-strength index, 14-bar lookback, log-return basis. Production formula used by VPS3.
- **Inputs:** 15 closes of binance-spot-ws 1m anchored at `ws_s` (offsets `−840s .. 0s` in 60s steps).
- **Source:** `strategy_lab/markov_filter/_vps3_pull/prod_strategies/rsi.py` (`compute_rsi_14(closes)`), vectorized variant in `strategy_lab/meta_classifier/momo_filter_overlay.py::attach_kline_features`.
- **Filter or signal:** Gate (binary via F7).
- **Edge:** F7 (UP needs RSI>50, DOWN<50): on production fires (post-deploy, 36h) lifted WR 44→51%, PnL −$5,241→+$192. Per-sleeve mixed: btc_15m_v1 gains, btc_5m_v1 loses (notF7 = +$4.58/tr). 94.67% match to live RSI on 1,331 fires.
- **Ribbon corr:** Not explicitly reported, but RSI is a momentum oscillator; weak overlap with ribbon-color expected.
- **Asset-specific:** No, generic. Per-sleeve sign of F7 differs (works on btc_5m_v2, inverts on btc_5m_v1).
- **HL-port score:** **5** — RSI on HL 1m candles is identical math. Drop-in.

### 1.2 RSI divergence (`rsi_bullish_div`, `rsi_bearish_div`)

- **What:** Lower-low in price + higher-low in RSI (or reverse) within 20-bar window. From SMS panel.
- **Inputs:** 5m/15m closes + RSI(14) on same TF.
- **Source:** `strategy_lab/meta_classifier/compute_sms_panel.py`.
- **Filter or signal:** Sparse event flag (5m: 0.28% / 0.41% of bars; 15m: 0.30% / 0.18%).
- **Edge:** Standalone `E_rsi_divergence` on s15_5m: n=164, WR 86%, +$0.52/tr (weak). Too sparse for offset-bin use.
- **Ribbon corr:** Untested.
- **Asset-specific:** Generic but n too small per cell.
- **HL-port score:** **5** — pure-kline computation.

### 1.3 MACD — `macd_agree`

- **What:** 12-26-9 EMA crossover; agreement flag = sign(MACD) matches direction.
- **Inputs:** 1m kline closes (binance-spot-ws).
- **Source:** NOT YET a standalone module in `strategy_lab/`. `talib.MACD` recommended; `momo_filter_overlay.attach_kline_features` has `bin_ret_60s/120s` as proxies.
- **Filter or signal:** Gate.
- **Edge:** From `_indicator_overlay_inbox`: `macd_agree` on `sniper / SOL / 5m`: n=138, WR 53.6% (+3.0pp), per_tr +$0.34, p=0.27. Combined with CVD: `cvd_agree_30s_AND_macd` on momo_v2 SOL 5m: n=110/389 WR 57.3% sel_upl +$356 p=0.097.
- **Ribbon corr:** Untested.
- **Asset-specific:** Slight SOL bias in working cells.
- **HL-port score:** **5** — trivial on HL kline.

### 1.4 EMA(5–100), 20 layers — `ema_N`, used in Madrid ribbon

- **What:** 20 EMAs spaced 5 bars apart on 1s binance bars. Aggregate features:
  - `ribbon_lead_slope_bps` = 5s change of ema_5 in bps.
  - `ribbon_lead_vs_ref_bps` = ema_5 − ema_100, bps.
  - `ribbon_alignment_pct` = % of EMA pairs in monotonic order (0..100%).
  - `ribbon_compression_bps` = std/mean across 20 EMAs.
  - `ribbon_color` ∈ {0..4} per Pine logic (bull→bear gradient).
- **Inputs:** 1s binance bars (`binance_1s_28d.parquet`).
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`. Panel `data/v4/canonical/_results/ta_indicators_1s.parquet` (1.28 GB).
- **Filter or signal:** Both — `ribbon_agrees` is a gate; standalone R2 rule (`Lead vs Ref + Slope`) is a signal generator.
- **Edge:** See §2.1 below.
- **Ribbon corr:** Self.
- **Asset-specific:** No.
- **HL-port score:** **5** — pure kline. Madrid ribbon on HL 1s prints is the same. Build script: ~20 lines.

### 1.5 ATR(14) Wilder — `atr_14`, `atr_pct`

- **What:** Average True Range, Wilder smoothing (alpha=1/14). Returns also `atr_pct = atr/close`.
- **Inputs:** 5m OHLCV.
- **Source:** `strategy_lab/build_features_v3plus.py::add_atr_adx`; `talib.ATR` in `features_15m.py`.
- **Filter or signal:** Component (gate input — used by DRZ zone half-width).
- **Edge:** No direct WR uplift; gates DRZ box geometry.
- **Ribbon corr:** Untested.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 1.6 ADX(14) + DI+ / DI- — `adx_14`, `plus_di_14`, `minus_di_14`

- **What:** Wilder directional index (trend strength). 0–100.
- **Inputs:** 5m OHLCV.
- **Source:** `strategy_lab/build_features_v3plus.py::add_atr_adx`.
- **Filter or signal:** Component of regime classifier (§7.1).
- **Edge:** Indirect via regime label (which flips S7 ETH DOWN and S1.5 SOL DOWN losers to OOS positive).
- **Ribbon corr:** Jaccard 0.155 with `ribbon_alignment_pct≥70` → mostly orthogonal.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 1.7 Slow Stochastic (60s and 300s windows) — `stoch_k_60s`, `stoch_d_60s`, `stoch_k_300s`, `stoch_d_300s`

- **What:** Slow stochastic 14/3/3 on 60s and 300s rolling windows (computed on 1s bars).
- **Inputs:** 1s OHLC.
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`.
- **Filter or signal:** Gate.
- **Edge:**
  - H1 (fade overbought): FAILS. Median ΔWR = +6.4pp → fires keep winning at 80–89% when overbought.
  - H4 (K/D crossover agrees with direction): median +$0.57/tr.
  - Composite (60s+300s both agree + both neutral) on BTC: s15 BTC $0.74→$4.59/tr (+$3.85, n=342); s6 BTC $3.01→$8.00/tr (+$4.99, n=489). Best stoch-gated single: s6 BTC DOWN + k60 low_neutral → +$18.55/tr, n=245, WR 64%.
  - Standalone `stoch_60s_kd_cross` on top S1.5 cells: +1.5–3pp WR.
- **Ribbon corr:** Cited in 12.5% of S1.5 winning combos; combined with ribbon_agrees often.
- **Asset-specific:** BTC-only for the composite gate (degrades ETH/SOL).
- **HL-port score:** **5**.

### 1.8 Bollinger Bands (60s and 120s) — `bb_pos_60s`, `bb_width_60s`, `bb_pos_120s`, `bb_width_120s`

- **What:** BB position (0..1) and width (std/mean) on 1s bars over 60s and 120s windows.
- **Inputs:** 1s closes.
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`.
- **Filter or signal:** Gate.
- **Edge:** `bb_pos_60s_extreme_agrees` (BB extreme position + direction match) is **the most-cited S6 gate** (14.6% of winning combos). On ETH 210 S1.5 stacked: `ribbon_color_bull|ribbon_agrees|bb_pos_60s_extreme_agrees|mfi_60s_neutral` → n=168, WR 88.7%, $/tr +$11.27 (baseline $0.49).
- **Ribbon corr:** Frequently co-occurs with ribbon_agrees in winning configs.
- **Asset-specific:** Universal — top S6 universal combo `bb_pos_60s_extreme_agrees` works on 15 cells.
- **HL-port score:** **5**.

### 1.9 MFI(60s, 300s) — `mfi_60s`, `mfi_300s`

- **What:** Money Flow Index — volume-weighted RSI variant.
- **Inputs:** 1s OHLCV.
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`.
- **Filter or signal:** Gate.
- **Edge:** `mfi_60s_neutral` cited in 8.3% of S1.5 winning combos. Featured in ETH 210 top combo (n=168 WR 88.7% $/tr +$11.27). V7 standalone strategy uses `RF + PVSRA + MFI`: BTC 5m off=90 n=332 WR 70.8% $/tr +$2.70 / +$895/22d.
- **Ribbon corr:** Untested directly; appears alongside ribbon in mega-combos.
- **Asset-specific:** No.
- **HL-port score:** **5** — HL has volume on klines.

### 1.10 CCI(60s) — `cci_60s`

- **What:** Commodity Channel Index 60s window.
- **Inputs:** 1s OHLC.
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`.
- **Filter or signal:** Gate (`cci_60s_agrees`).
- **Edge:** S6 #2 most-cited gate (13.6%). Stacking with ribbon+stoch: `ribbon_agrees + stoch_60s_agrees + cci_60s_agrees` universal across 14 S6 cells, mean WR 79%, mean $/tr $5.02, total n=3,667, ~$18k/28d aggregate.
- **Ribbon corr:** Universal-combo partner with ribbon_agrees.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 1.11 OBV (On-Balance Volume)

- **What:** Cumulative signed volume per close-change sign.
- **Inputs:** OHLCV.
- **Source:** NOT BUILT in strategy_lab. `talib.OBV` available.
- **Filter or signal:** Volume confirmation.
- **Edge:** UNMEASURED — closest analog is CVD (§3.1) which is already validated.
- **Ribbon corr:** N/A.
- **Asset-specific:** N/A.
- **HL-port score:** **5** — trivial; HL klines have volume.

### 1.12 SMA / EMA short and long
- Used as inputs everywhere. Not a standalone gate. Score **5**.

### 1.13 talib 15m feature pack (15m BTC perp)

- **What:** Combined feature panel for 15m bars:
  - `close_ret_1bar, _4bar, _8bar`
  - `atr_14`
  - `realized_vol_24_pct`
  - `taker_ratio_z_7d`
  - `oi_pct_chg_4bar, _24bar`
  - `top_trader_ls_z_7d`
  - `funding_rate_z_30d`
  - `premium_z_30d`
  - `liq_count_15m, liq_notional_15m, liq_notional_z_7d`
  - `bar_wick_up_frac, bar_wick_dn_frac`
  - `regime_bull` (close > EMA200d)
  - `regime_slope_pos` (EMA200d slope > 0)
- **Inputs:** Binance 15m + binance_metrics + liq.
- **Source:** `strategy_lab/features_15m.py`.
- **Filter or signal:** Bulk feature panel for ML/meta-classifier.
- **Edge:** Used downstream in v2 signals (which were KILLED — see POLYMARKET_V2_SIGNALS_FINDINGS), but the FEATURE engineering itself is sound. Most discriminative univariate (5m, BTC): `ret_5m` (+0.131 Pearson), `ret_15m` (+0.071), `ls_count_delta_5m` (+0.044). Least useful: `book_skew` (-0.070), `ls_top_sum`.
- **Ribbon corr:** Untested.
- **Asset-specific:** BTC perp primary.
- **HL-port score:** **4** — funding/OI/liq metrics need HL native feeds (which `load_hyperliquid_*` provides). Top-trader L/S ratio is binance-only — drop or replace with HL position-data analog.

### 1.14 Univariate feature inventory (BTC up/down baseline)

From POLYMARKET_FEATURES_UNIVARIATE on 2,734 markets:
| Feature | Pearson r (5m) | Top-Q hit% (5m) | Notes |
|---|---|---|---|
| `ret_5m` | +0.131*** | 60.1 | strongest univariate, breaks 53% breakeven |
| `ret_15m` | +0.071*** | 56.2 | |
| `ls_count_delta_5m` | +0.044* | 54.7 | top-trader L/S delta |
| `smart_minus_retail` | +0.009 | 52.8 | weak |
| `oiv_delta_5m` | -0.006 | 51.8 | weak |
| `taker_delta_5m` | +0.016 | 51.3 | weak |
| `oi_delta_5m` | +0.006 | 50.6 | weak |
| `ret_1h` | -0.006 | 50.4 | weak |
| `book_skew` | -0.070** | 44.8 | **anti-signal** (significant negative) |
| `oi_delta_15m` | -0.046* | 46.5 | weak negative |

HL-port: `ret_*` all score 5. `oi_delta_*`, `taker_delta_*` score 4 on HL (need HL OI / taker tape). `book_skew` is L25-based, but on HL it would be perp book imbalance — score 3. `smart_minus_retail`, `ls_*` are binance-metrics-only and don't have a clean HL analog (HL doesn't publish top-trader long/short) — score 2.

---

## 2. Ribbon variants

### 2.1 Madrid ribbon (20 × EMA 5–100, 1s bars) — `g_ribbon_agrees`, `g_ribbon_color_bull/bear`, `g_ribbon_alignment`, `g_ribbon_compressed`, `g_ribbon_strong`

- **What:** 20-layer EMA ribbon producing color, alignment, compression, strength, slope.
- **Inputs:** 1s binance kline closes.
- **Source:** `strategy_lab/meta_classifier/compute_ta_indicators.py`. Per-fire overlay `overlay_ta_indicators.py`.
- **Filter or signal:** Mostly gate; standalone R2 (`Lead vs Ref + Slope`) is a signal generator but 82% overlaps S1.5.
- **Edge (gate use):**
  - `ribbon_agrees` universal filter: S1.5 $/tr 3.6× ($0.16→$0.56). On S6 removes 2.2% junk (60% WR / −$1.60/tr).
  - `compression < 2bps` (tight ribbon) on S6 BTC: +$3/tr boost, n=5,775 → +$17,391/28d.
  - Standalone R2 (rule): BTC offset 210s WR 86.8%, +$9.71/tr, n=121.
  - Standalone R4 (compressed breakout): -$200k sum across cells — **KILL**.
  - Stacked with M1V Markov for BTC 240s 5-10bps: WR 95.7%, n=140.
- **Ribbon corr:** Self.
- **Asset-specific:** No. Compression-gate is universal.
- **HL-port score:** **5** — HL 1s/1m candles, identical math.

### 2.2 Quantum Ribbon Lite (5 paired EMA layers, 21–60) — `qr_ribbon_state`, `qr_market_regime`, `qr_market_health`, `qr_signal_confidence`, `qr_volume_ratio`, `qr_momentum_consistency`

- **What:** Pine v6 indicator. Layers (21,28), (29,36), (37,44), (45,52), (53,60). Derived:
  - `ribbon_state ∈ {-2,-1,0,+1,+2}` from weighted alignment.
  - `market_regime ∈ {0=ranging, 1=trending}`.
  - `market_health ∈ [0,100]` composite of alignment + regime + volume + spacing.
  - `signal_confidence ∈ [0,8]` composite of all.
  - `volume_ratio` = vol / SMA(vol,20).
- **Inputs:** 5m or 15m OHLCV resampled from 1s.
- **Source:** `strategy_lab/meta_classifier/compute_qr_panel.py`, panel `qr_panel_5m.parquet` (2.6 MB), `qr_panel_15m.parquet`.
- **Filter or signal:** Gate (standalone rules LOSE).
- **Edge:**
  - **`g_qr_volume_strong` (vol_ratio > 1.3)** on BTC s6_5m 60-150: n=362, WR 85.4%, +$22.37/tr (Δ +$12.74 vs $5.10 baseline). 87% sample reduction. Walk-forward PASS (test $/tr +$3.64, CI lo +$1.44).
  - **`g_qr_high_health` (health > 70)** on BTC s6_5m: n=566, +$14.10/tr (Δ +$4.47). Walk-forward PASS (test +$2.43, CI lo +$0.22).
  - `g_qr_high_conf` (conf > 4) on BTC s6_5m: n=688, +$11.93/tr.
  - **Confidence bucket asymmetry**: BTC monotonic (WR 50→70→84→83%); ETH NON-monotonic (peak [4,6) at 70%, DROPS to 44% at [6,8] — high QR conf is contra on ETH).
  - Standalone rules: ALL NEGATIVE. n=58k+ rule A loses −$283k/28d.
- **Ribbon corr:** Largely redundant with Madrid `ribbon_agrees` (both are EMA-based trend); NEW VALUE is in regime/health/confidence/volume_ratio, NOT in alignment.
- **Asset-specific:** Effect concentrated on BTC s6_5m 60-150. ETH/SOL did not pass walk-forward.
- **HL-port score:** **5** — pure kline computation, panel build is ~50 lines.

### 2.3 `tight_ribbon` / compression — `ribbon_compression_bps < 2bps`

- See §2.1. Top deployable: S6 + ribbon_agrees + compression<2bps: 5,775 fires, +$3.01/tr, +$17,391/28d.

### 2.4 `ribbon_strong` — `ribbon_alignment_pct ≥ 95%`

- S1.5 + ribbon_agrees + alignment ≥95%: n=9,997, WR 84.7%, +$0.48/tr. Cited in 6.6% of S1.5 winners.

### 2.5 `ribbon_lead_slope_bps`, `ribbon_lead_vs_ref_bps`

- Derived from 5s change in ema_5 (slope) and ema_5−ema_100 (lead vs ref).
- Used in standalone R2 rule (+$1.07/tr, sum +$6,533).

---

## 3. Volume / flow features

### 3.1 CVD on binance 1s — `cvd`, `cvd_slope_30s`, `cvd_slope_60s`, `sigma_60s`

- **What:** `signed = 2 × taker_buy_base − volume_traded`; `cvd = cumsum(signed)`. Rolling slopes.
- **Inputs:** `binance_1s_28d.parquet` (cols `symbol_id, time_period_start_us, price_close, volume_traded, taker_buy_base`).
- **Source:** `strategy_lab/markov_filter/_cvd_timing_overlay.py::build_cvd_table`.
- **Filter or signal:** Gate (`cvd_agree_30s`, `cvd_agree_60s`, `cvd_agree_120s`).
- **Edge:**
  - `cvd_agree_30s` on BTC s6_5m 60-150 sleeves: positive 2-4pp WR lift.
  - `cvd_agree_30s_AND_macd` on momo_v2 SOL 5m: n=110/389 WR 57.3% +$2.13/tr p=0.097.
  - `cvd_agree_30s_AND_macd` on sniper SOL 5m: n=98/410 WR 59.2% +$3.21/tr p=0.091.
  - On BTC momo_v1 5m: `cvd_agree_30s` adds +$125 sel_upl (small positive).
  - On BTC momo_v2 5m: `cvd_agree_30s` is NEGATIVE −$365 sel_upl.
- **Ribbon corr:** Reported as ORTHOGONAL family in `_indicator_overlay_inbox`.
- **Asset-specific:** SOL — strongest positive. BTC — mixed.
- **HL-port score:** **5** — HL klines include `taker_buy_base`. Same math.

### 3.2 CVD on Polymarket trades — `cvd_obs`, `cvd_up_5min`, `cvd_dn_5min`, `cvd_60s_up`, `cvd_60s_dn`

- **What:** Sum signed notional on polymarket trade prints inside a window.
- **Inputs:** `load_trades(asset)` Polymarket prints (STALE Apr 22→May 6 — see CLAUDE.md).
- **Source:** `strategy_lab/discovery_2026_05_16/strat_A1_cvd_5m.py::compute_cvd_per_market`; `strategy_lab/meta_classifier/momo_filter_overlay.py::attach_cvd_features`; `strategy_lab/confluence/flow/features.py::compute_trade_features → cvd_1m, cvd_5m`.
- **Filter or signal:** Either.
- **Edge:** UNMEASURED in this archive due to STALE data. Production overlay used in F8 filter.
- **Ribbon corr:** N/A.
- **Asset-specific:** N/A.
- **HL-port score:** **1** — depends on Polymarket trade tape semantics (BUY/SELL of UP/DOWN tokens), which has no HL analog. Replace with HL aggTrade CVD if porting.

### 3.3 Smart Money Structure CVD — `cvd_level ∈ {Low, Med, High}`, `cvd_with`

- **What:** Per-bar CVD level discretized to terciles; `cvd_with` agreement flag.
- **Inputs:** 5m/15m kline volume + taker.
- **Source:** `strategy_lab/meta_classifier/compute_sms_panel.py`.
- **Filter or signal:** Gate.
- **Edge:** Standalone **`F_cvd_aligned`: NEGATIVE −$0.95/tr** across all assets/TFs. As gate on BTC s6_5m: n=1,424 WR 82.8% +$3.67/tr (Δ −$1.38). REDUNDANT with existing gates.
- **Ribbon corr:** Untested formally but ribbon already captures trend.
- **Asset-specific:** SOL 5m off=30 anomaly: train +$0.18 → test +$4.53 WF PASS. Otherwise dead.
- **HL-port score:** **5**.

### 3.4 RVOL (Relative Volume) — `rvol_30_300_gt_1p2`, `rvol_5s_60`, `rvol_1m_60`

- **What:** Bar volume / mean(last N bar volumes). Default lookback 60 bars.
- **Inputs:** 1m kline volume (HL or binance).
- **Source:** Recommended port from `txbabaxyz/mlmodelpoly`. Already as gate: `rvol_30_300_gt_1p2` in `gate_sweep_prod_fills.py`.
- **Filter or signal:** Gate.
- **Edge:** On momo_v1 SOL 5m: n=84/276 WR 54.8% sel_upl +$73 (modest). On sniper BTC 5m: n=119/712 WR 52.1% +$166. Not headline-strong but consistently mildly positive.
- **Ribbon corr:** Orthogonal (volume-based).
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 3.5 Taker buy ratio z-score — `taker_ratio_z_7d`

- **What:** Z-score of taker_buy / total_volume over 7d rolling.
- **Inputs:** Binance 5m metrics (`load_binance_metrics`).
- **Source:** `strategy_lab/features_15m.py`.
- **Filter or signal:** Feature.
- **Edge:** Mild positive in univariate sweep (Top-Q hit 51.3% on 5m, n=1251).
- **Ribbon corr:** Orthogonal.
- **Asset-specific:** Binance-built; HL has same field.
- **HL-port score:** **4**.

### 3.6 Top-trader L/S ratio z-score — `top_trader_ls_z_7d`, `ls_top_count`, `ls_top_sum`, `ls_count`

- **What:** Binance binance_metrics top-trader long/short fields, z-scored 7d.
- **Inputs:** `load_binance_metrics(symbol)`.
- **Source:** `strategy_lab/features_15m.py`, `strategy_lab/polymarket_build_features.py`.
- **Filter or signal:** Feature.
- **Edge:** `ls_count_delta_5m` Pearson +0.044*, top-Q 54.7%. Weak.
- **Ribbon corr:** Untested.
- **Asset-specific:** Binance-only data; HL does NOT publish top-trader stats.
- **HL-port score:** **1–2** — no clean HL analog. Drop unless we synthesize from HL position data manually.

### 3.7 Spike detection (5s, 15s, 30s) — `ret_5s_bps`, `ret_15s_bps`, `ret_30s_bps`, `up_spike_5s`

- **What:** Bar-level log returns over 5s / 15s / 30s windows; boolean confirmation flags.
- **Inputs:** 1s binance kline closes.
- **Source:** S6 family signal generator (NEW_SLEEVES_ENTRY_RULES_2026_05_23 §S6).
- **Filter or signal:** Standalone direction signal (S6 strategy).
- **Edge (full S6 family, base):**
  - S6_BTC_off120_D1_T1: n=146 WR 70.5% +$6.57/tr +$960/28d Sharpe 8.70.
  - S6_BTC_off60_D4_T1: n=97 WR 83.5% +$4.88/tr Sharpe 15.10 (HIGHEST Sharpe in study).
  - S6_SOL_off30_D2_T1: n=130 WR 78.5% +$3.55/tr Sharpe 10.26.
- **Definitions D1–D4:**
  - D1: `|ret_5s|>2.5bps AND sign(cvd_5s)==sign(ret_5s)`.
  - D2: `|ret_15s|>thr AND sign(cvd_15s)==sign(ret_15s)`.
  - D3: `|ret_5s|>1.5bps AND |ret_15s|>2.5bps`.
  - D4: `ret_30s_bps > 5bps AND ret_5s_bps > 0`.
- **Tiers T1/T2/T3:** Per-asset thresholds calibrated to 1s return distribution (BTC p99=4.3bps, ETH p99=5.5bps, SOL p99=6.4bps). T1 wins on $/tr × n.
- **Ribbon corr:** Captures DIFFERENT timing — 6,514 fires happen on slugs where S1.5 does NOT fire.
- **Asset-specific:** Universal but BTC dominant.
- **HL-port score:** **5** — HL 1s candles + taker volume exist.

---

## 4. Structure (Smart Money) features

Port source: `strategy_lab/meta_classifier/compute_sms_panel.py`.

### 4.1 BOS — `bos_buy`, `bos_sell`, `bars_since_bos_buy`, `bars_since_bos_sell`

- **What:** Break of structure — close breaches the most recent unbroken pivot high/low.
- **Inputs:** 5m/15m OHLC, pivot lookback (typically 5-10 bars).
- **Source:** `compute_sms_panel.py`.
- **Filter or signal:** Sparse event flag (5m: 2.43%/2.63% of bars; 15m: 2.45%/2.65%).
- **Edge:** Standalone `A_bos_continuation` on s6_5m: n=1,947 WR 73.2% +$1.59/tr. As gate `g_sms_recent_bos_with` on BTC s6_5m: n=317 WR 72.9% +$0.66/tr (Δ −$4.40 — over-restrictive).
- **Ribbon corr:** Untested directly; treated as orthogonal "structure" family.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 4.2 CHoCH — `choch_buy`, `choch_sell`, `g_sms_recent_choch_with`

- **What:** Change of character — first BOS that flips the prevailing trend direction.
- **Inputs:** Same as BOS plus prior trend flag.
- **Source:** `compute_sms_panel.py`.
- **Filter or signal:** Sparse (5m: 1.51%/1.37%).
- **Edge:** Standalone `B_choch_reversal` on s15_5m: n=1,793 WR 81.9% +$0.49/tr (weak); on s6_5m: n=604 WR 72.0% +$0.87/tr. Best per-cell: BTC s15_5m offset 210s WR 85.7%, +$7.44/tr (n=77 — small).
- **Ribbon corr:** Untested.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 4.3 Liquidity sweep / reclaim — `liquidity_up`, `liquidity_dn`, **`g_sms_liq_reclaim_with`**

- **What:** Current high/low taps the 20-bar extreme ± 0.05% (sweep). Reclaim signal = direction agrees with mean-revert from sweep.
- **Inputs:** 5m/15m OHLC, 20-bar rolling extremes.
- **Source:** `compute_sms_panel.py`.
- **Filter or signal:** Gate (also standalone).
- **Edge:** **STAR finding of 2026-05-26 session.**
  - As gate on BTC S6 5m 60-150 hybrid_v1: n=699, WR **88.3%**, $/tr **+$18.71** (Δ **+$13.60**), sum **+$13,075/22d**. Walk-forward train→test $30→$6.50 with p5 CI +$5.57.
  - As gate on ETH S6 5m 60-150: n=324, WR 61.4%, +$10.52/tr (Δ +$5.66).
  - Standalone BTC S6 off=120 (NO base gates): n=166, WR 77.1%, **+$20.68/tr** (highest per-trade edge of any 5m sleeve discovered).
  - Multi-asset standalone aggregates: G on s6_5m n=2,315 WR 71.5% +$4.35/tr; on s15_5m n=7,762 WR 81.4% +$1.09/tr.
- **Ribbon corr:** **−0.07 (orthogonal)** — `trend_strength_raw` × ribbon features. The most orthogonal high-edge gate discovered.
- **Asset-specific:** BTC > ETH ≫ SOL on the offset-bin overlay; standalone works on all 3.
- **HL-port score:** **5** — pure kline rolling extreme.

### 4.4 Multi-TF trend strength — `trend_strength_raw ∈ [-7, +7]`, `g_sms_trend_strength_with`

- **What:** Sum of (+1/-1) signed trend on 1m, 5m, 15m, 1h, 4h, D using EMA20+VWAP consensus.
- **Inputs:** Multi-TF OHLCV.
- **Source:** `compute_sms_panel.py`.
- **Filter or signal:** Gate.
- **Edge:** **Standalone C_trend_strength loses ~−$0.62/tr** across all assets. As gate on BTC s6_5m: n=1,034 WR 77.9% +$3.17/tr (Δ −$1.88). Redundant.
- **Ribbon corr:** **−0.05 with ribbon_color** — orthogonal in theory, but predictive overlap is weak. Daily-TF coverage thin on 22d window (caps `|raw|` at 6 not 7).
- **Asset-specific:** No.
- **HL-port score:** **5** — pure-kline, multi-TF.

### 4.5 System confidence — `system_confidence ∈ {50, 60, 75, 90}`, `g_sms_conf_high`

- **What:** Composite of trend_strength, liquidity, RSI div, CVD level.
- **Inputs:** All SMS features.
- **Source:** `compute_sms_panel.py`.
- **Filter or signal:** Gate.
- **Edge:** Standalone D_top_confidence: n=43 (way too sparse), WR <60%, −$5/tr. Gate on BTC s6_5m: n=1,869 WR 79.3% +$6.37/tr (Δ +$1.32).
- **Ribbon corr:** Untested.
- **Asset-specific:** Sparse for top tier — 5m `==90` only 29/18,243 bars.
- **HL-port score:** **5**.

### 4.6 Pivot points (high/low, lookback 12 on CVD)

- Used internally by DRZ to anchor zones. See §6.

---

## 5. Traders Reality features

Panel: `data/v4/canonical/_results/traders_reality_1s.parquet` (680 MB, 82 cols, 5.5M rows).
Source: `strategy_lab/meta_classifier/compute_traders_reality.py`.

### 5.1 PVSRA candles — `tr_pvsra ∈ {climax_up, rising_up, regular, rising_dn, climax_dn}`

- **What:** Price/Volume Spread Relative-volume Analysis — vector candle classification.
- **Inputs:** 1s OHLCV.
- **Source:** `compute_traders_reality.py`.
- **Distribution (1s bars):** ~86–92% regular, ~6% climax_up + ~6% climax_dn per asset.
- **Filter or signal:** Gate (also signal in V7 standalone strategy).
- **Edge:**
  - S1.5 overall WR by class — near-neutral (~80–84% across classes, no significant uplift).
  - Direction-conditioned (`bullish_pvsra AND UP`): only ~10% co-occurrence — near base rate.
  - V7 strategy `RF + PVSRA + MFI`: BTC 5m off=90 n=332 WR 70.8% +$2.70/tr +$895/22d.
  - **PVSRA standalone is unusable** (-37pp WR on 5m, per PER_SLEEVE_CATALOG notes). Only valuable inside the V7 triple-gate stack.
- **Ribbon corr:** Untested.
- **Asset-specific:** Universal but stronger on BTC.
- **HL-port score:** **5** — 1s OHLCV on HL.

### 5.2 EMA stack — `tr_ema_5`, `_13`, `_50`, `_200`, `_800`, `tr_ema_stack_score ∈ {-2,-1,0,+1,+2}`

- **What:** 5 EMAs on 1s bars. Stack score = direction of full alignment.
- **Inputs:** 1s closes.
- **Source:** `compute_traders_reality.py`.
- **Distribution:** ~75–80% of bars score ±2 (strong stack); ~20–25% near neutral.
- **Filter or signal:** Gate.
- **Edge:**
  - S1.5 by stack alignment (BTC): bull&UP n=2,097 WR 88.2%; bear&UP n=21 WR 66.7% (strong loss).
  - `g_tr_stack_full` appears in Tier-1 winning stacks: BTC S7 15m 480-840s n=816 WR 88% +$2.15/tr +$1,751/28d uses `tr_stack_full ∧ tr_above_ema800 ∧ ribbon ∧ tight ∧ stoch ∧ tr_above_ema200`.
  - Adverse alignment (bear&UP, bull&DN) WR drops ~50pp on n<35 cells.
- **Ribbon corr:** Untested but expected high (both are EMA-based).
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 5.3 `g_tr_above_ema50`, `g_tr_above_ema200`, `g_tr_above_ema800`, `g_tr_above_cloud`, `g_tr_above_pp`

- **What:** Boolean gates: close > each EMA / above price-action cloud / above PP (pivot point).
- **Inputs:** 1s closes + TR pivot panel.
- **Source:** `compute_traders_reality.py`.
- **Filter or signal:** Gate.
- **Edge:** Featured in Tier-1 hybrid stacks. E.g. BTC S6 5m 60-150 hybrid uses `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon` → n=2,764 WR 77.8% +$5.10/tr **+$14,103/28d**. Also: ETH S1.5 5m 150-240s uses `ribbon ∧ tr_above_ema200 ∧ stoch ∧ bb_pos ∧ cci`.
- **Ribbon corr:** Untested.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 5.4 Pivot levels (PP, R1-R3, S1-S3, M0-M5) — `tr_dist_nearest_bps`, `g_tr_within_dev`

- **What:** Daily classical pivots + mid-points. Distance to nearest pivot in bps.
- **Inputs:** Prior day OHLC.
- **Source:** `compute_traders_reality.py`.
- **Distribution (median bps):** BTC 12.5 / ETH 17.8 / SOL 20.3.
- **Filter or signal:** Gate (`g_within_dev`).
- **Edge:** Used in SOL S1.5 5m 240-300s hybrid (`rf_aged ∧ within_dev ∧ tight_ribbon ∧ tr_in_active_session`) → n=282 WR **92.6%** +$6.17/tr.
- **Ribbon corr:** Untested.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 5.5 Daily/weekly Camarilla pivots — internal to TR panel

- **What:** Camarilla H1–H4, L1–L4 derived from prior day OHLC (close-weighted).
- **Inputs:** Daily OHLC.
- **Source:** `compute_traders_reality.py`.
- **Filter or signal:** Levels.
- **Edge:** Not isolated in current backtests; bundled into `tr_dist_nearest_bps`.
- **Ribbon corr:** N/A.
- **HL-port score:** **5**.

### 5.6 Sessions — `tr_session ∈ {asia, europe, ny}`, `g_tr_in_active_session`

- **What:** UTC session windows (no DST). Active vs inactive flag.
- **Inputs:** UTC time of fire.
- **Source:** `compute_traders_reality.py`.
- **Filter or signal:** Gate.
- **Edge:** Appears in SOL S1.5 5m 240-300s hybrid (see §5.4). Used in V5 ETH strategy: ETH 5m off=60 V5 (`V2+session`) n=263 WR 66.2% +$2.76/tr +$727/22d.
- **Ribbon corr:** Orthogonal (time-based).
- **Asset-specific:** No.
- **HL-port score:** **5** — clock-based.

### 5.7 PsyLevels — `tr_psy_high`, `tr_psy_low`

- **What:** Weekly psychological levels anchored at Sat 22:00 UTC; high/low of prior complete psy-week.
- **Inputs:** Daily OHLC, week boundaries.
- **Source:** `compute_traders_reality.py`.
- **Filter or signal:** Levels.
- **Edge:** Not isolated.
- **Ribbon corr:** N/A.
- **HL-port score:** **5**.

### 5.8 ADR (Average Daily Range) — `tr_adr`, `g_tr_within_adr`

- **What:** 14-day rolling average daily range.
- **Inputs:** Daily OHLC.
- **Source:** `compute_traders_reality.py`.
- **Filter or signal:** Gate (`tr_within_adr` = current intraday range < 80% of ADR, room left).
- **Edge:** SOL S7 15m 480-840s hybrid (`dev_extreme ∧ rf_aged ∧ tr_within_adr ∧ tr_above_pp`) n=42 WR **97.6%** +$21.79/tr **(highest $/tr in study)** +$915/28d.
- **Ribbon corr:** Orthogonal.
- **Asset-specific:** No.
- **HL-port score:** **5**.

### 5.9 AWR (Average Weekly Range) — `tr_awr`

- 4 prior complete weeks. Same logic as ADR. Score **5**.

### 5.10 `g_tr_pvsra_with`, `g_tr_stack` — convenience gates

- Per-fire agreement of PVSRA candle and EMA stack with bet direction. Used in V7 / V6.

---

## 6. Range Filter [DW] and DRZ

### 6.1 Range Filter [DW] — `rf_close`, `rf_r`, `rf_band_pos`, `rf_dir ∈ {+1, -1, 0}`, `rf_in_band`

- **What:** Donovan Wall Range Filter — Type 1, Close basis, qty=2.618, AvgChange n=14, smooth=true sn=27.
- **Inputs:** 1s binance closes.
- **Source:** `strategy_lab/meta_classifier/compute_range_filter.py`. Panel `data/v4/canonical/_results/{s15,s6,v15m}_with_rf.parquet` ; `s15_with_ta_markov_rf.parquet`.
- **Distribution:** BTC dir+1 49.8% / dir-1 50.2% (mean dwell 42s); ETH 51.2/48.8 (32s); SOL 51.6/48.4 (20.5s).
- **Filter or signal:** Gate (`g_rf_with`).
- **Edge (fire-time `rf_dir` vs bet direction agreement):**
  - s15_5m: 79.23% agreement (n=33,294).
  - s6_5m: 92.65% agreement (n=11,336) — very high.
  - v15m_15m: 66.79% (n=10,828).
- **Used in Tier-1:**
  - BTC S6 5m 60-150 hybrid `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon`: n=2,764 WR 77.8% +$5.10/tr +$14,103.
  - SOL S1.5 5m 240-300 hybrid `rf_aged ∧ within_dev ∧ tight_ribbon ∧ tr_in_active_session`: n=282 WR 92.6% +$6.17/tr.
  - `rf_aged` gate (rf_dir stable >K bars), `rf_in_band` (band_pos in [0,1]), `rf_fresh` (recent flip) all explored.
- **Verification:** max |ref vs prod| on 100 BTC bars = 0.0 (bit-perfect port).
- **Ribbon corr:** Untested directly; appears as orthogonal "range-vs-trend" companion.
- **Asset-specific:** No.
- **HL-port score:** **5** — pure kline math.

### 6.2 `g_rf_with`, `g_rf_aged`, `g_rf_fresh`, `g_rf_in_band`, `g_rf_1h`, `g_rf_within_dev`

- Family of gates derived from §6.1. All HL-port **5**.

### 6.3 DRZ (Delta Reaction Zones) — `drz_in_support_zone`, `drz_in_resistance_zone`, `drz_dist_bps`, `drz_recent_RC`, `drz_recent_RE`, `drz_n_zones`, `drz_pos_pct`

- **What:** BOSWaves Delta Reaction Zones port. `raw_delta = sign(close-open)·volume; sm = EMA(raw,3); CVD = cumsum(sm)`. Pivot high/low on CVD lookback=12; pivot → zone at high/low with half-width `ATR(14)·0.35`. RC = midline reclaim; RE = midline re-enter.
- **Inputs:** 5m / 15m OHLCV.
- **Source:** `strategy_lab/drz/build_drz_panel.py`. Panels `drz_panel_5m.parquet` (190k fires × 46 cols), `drz_panel_15m.parquet`.
- **Distribution:** ~2–3% of fires in a zone at any time. ~1–2.5% RC/RE per asset.
- **Filter or signal:** Gate.
- **Edge:**
  - **`g_drz_not_contra_zone` (don't bet INTO opposing zone)** on BTC s6_5m hybrid_v1: n=2,698 WR 78.7% +$5.36/tr (Δ +$369, +2.6%). Walk-forward 4/4 PASS at p≤0.05.
  - Standalone **SOL 5m F_at_resistance_DOWN** (bet DOWN when in resistance zone, no other gates): n=291, WR 63.9%, +$6.62/tr, sum +$1,927/28d, train $1,435 / test $492, p=0.005.
  - Standalone BTC 5m A_RC_at_support_UP / 60-150: n=84 WR 63.1% +$4.76/tr +$400 (p=0.050).
  - **What does NOT work:** direction-specific zone gates collapse n too far (37-85) and lose >$1,700. Naive E/F gates fail walk-forward on BTC and ETH (only SOL holds).
- **Ribbon corr:** Untested but treated as orthogonal "structure" family.
- **Asset-specific:** SOL > BTC ≫ ETH for standalone. Gate is universal.
- **HL-port score:** **5** — HL klines have OHLCV.

### 6.4 DRZ impulse stats — `drz_pos_pct`, `drz_net`

- Per-zone bookkeeping over the last 100 raw_delta values at pivot bar. Filter input. Score **5**.

---

## 7. Regime classifiers

### 7.1 Rule-based 3-state regime — `regime_label ∈ {trending_up, trending_dn, ranging}`, `regime_score ∈ [-1, +1]`

- **What:**
  - `trending_up`: ADX(14) > 25 AND `tr_ema_stack_score ≥ +1` AND `ribbon_alignment_pct ≥ 70`.
  - `trending_dn`: ADX > 25 AND stack ≤ −1 AND alignment ≥ 70.
  - `ranging`: else.
  - `regime_score = tanh(stack/2) · (min(adx,50)/50) · (min(align,100)/100)`.
- **Inputs:** 5m/15m OHLCV + ribbon alignment + EMA stack.
- **Source:** `strategy_lab/meta_classifier/build_regime_panel.py`. Panels `regime_panel_5m.parquet` (7,749 bars × 3 assets), `regime_panel_15m.parquet`.
- **Distribution (5m):** ~86% ranging / 7% trending_up / 7% trending_dn per asset.
- **Filter or signal:** Gate (allow-list).
- **Edge:**
  - Tier-1 routing: always-on $/tr $3.04 → routed $3.12 (+2.6% in-sample). Marginal.
  - **Loser-to-winner flips:**
    - S7 ETH 15m DOWN: baseline −$0.62/tr → only-trending_dn +$1.61/tr (in-sample); OOS test +$7.46 (n=11, CI [+3.99, +11.79]).
    - S6 BTC 5m DOWN: baseline +$4.19 → only-trending_up +$5.19 (in-sample); OOS +$10.66 (n=17, CI [+3.45, +16.89]).
    - S1.5 SOL 5m DOWN: baseline −$0.35 → only-trending_dn +$0.64 (in-sample); OOS +$4.81 (n=39, CI [+1.02, +8.52]).
  - **S6 base WR range across regimes = 10.2pp**; S1.5 base 3.0pp; Tier-1 6.6pp.
  - Counter-intuitive: S6 BTC UP signals LOSE in trending_up (−1.40 dpt) and WIN in ranging (+2.83). Same on ETH.
- **Ribbon corr:** Jaccard 0.155 with `ribbon_alignment ≥ 70` — adds ~85% new info.
- **Asset-specific:** Best on UNGATED base sleeves; minimal on Tier-1.
- **HL-port score:** **5**.

### 7.2 Rule-based hysteresis regime (TREND/SIDEWAYS/VOLATILE) — `classify_regime_series`

- **What:** Production-grade classifier with hysteresis (5 consecutive raw labels required to flip). Inputs: `slope_1h_arr`, `vol_1h_arr`; thresholds `slope_thresh=4e-5`, `vol_thresh=0.0040`.
- **Inputs:** 1m closes → 1h regression slope + 1h realized vol.
- **Source:** `strategy_lab/confluence/structure/regime_classifier.py`.
- **Filter or signal:** Gate.
- **Edge:** Not the headline-flip regime — but production-grade. `regime_factor(regime)` returns 0.3/0.0/-0.3.
- **HL-port score:** **5**.

### 7.3 Markov regime (M1V / M1F / M5V / M5F) — `regime ∈ {BEAR, SIDEWAYS, BULL}`, `markov_pass`

- **What:** 3-state MLE Markov classifier; states from terciles of 20-bar log-return.
  - **M1V**: window=20, bars=1m, mode='vol_adaptive' (q33/q66 per-asset rolling 14d). **The best Markov stack per `post_f7_real_compare_v2.py`.**
  - **M5V**: window=20, 5m bars, vol_adaptive.
  - **M1F / M5F**: same windows, fixed threshold per asset.
- **Inputs:** Binance 1m or 5m closes.
- **Source:** `strategy_lab/markov_filter/markov_regime_micro.py`. Drivers: `meta_classifier/momo_variants_markov_overlay.py`, `shadow_11_sleeves_v2.py`.
- **Filter or signal:** Gate.
- **Edge (per-sleeve best filter, from MARKOV_VS_F7_PER_SLEEVE):**
  - **btc_15m_v1**: MARKOV M1V → +$2.61/tr lift (baseline +$2.83 → +$5.44; n=26).
  - **btc_15m_v2**: notF7 + M1V → +$4.18/tr lift (−$0.35 → +$3.83; n=32). **F7 actively HARMS this sleeve.**
  - **btc_5m_v1**: notF7 alone → +$4.58/tr lift (−$1.35 → +$3.23; n=66). **F7 HARMS.**
  - **btc_5m_v2**: F7 + M1F → +$1.77/tr (−$1.88 → −$0.11; n=54). One sleeve where F7 helps.
  - **eth_5m_v2**: M5V → +$5.45/tr (−$6.14 → −$0.69; n=10 — danger zone).
  - On `sniper ETH 15m`: m5v_pass n=76/356 WR 63.2% (+13.7pp) sel_upl +$615 per_tr +$7.15 p=0.011 — strongest single gate.
  - On `momo_v2 SOL 15m`: m1v_AND_m5v n=46/93 WR 60.0% sel_upl +$273.
- **Ribbon corr:** Stacks cleanly. BTC 240s 5-10bps + ribbon_agrees + m1v_agrees → WR 95.7% (n=140).
- **Asset-specific:** Yes — per-sleeve direction varies.
- **HL-port score:** **5** — pure kline math, asset-agnostic.

---

## 8. Cross-asset / cross-venue features

### 8.1 Cross-asset RF confluence — `xa_all_with_bet`, `xa_maj_with_bet`, `xa_btc_with_bet`, `xa_eth_with_bet`, `xa_sol_with_bet`

- **What:** At fire_us, check `rf_dir` of all 3 assets (BTC/ETH/SOL). `xa_all_with` = all 3 agree with bet direction; `xa_maj_with` = ≥2 agree.
- **Inputs:** RF panel (§6.1) for all 3 assets.
- **Source:** `strategy_lab/meta_classifier/cross_asset_mtf_confluence.py`.
- **Filter or signal:** Gate.
- **Edge (S1.5 universe):**
  - `xa_all_with_bet` BTC 5m DOWN: n=2,726 WR **82.13%** +$1.64/tr +$4,463/28d.
  - `xa_all_with_bet` BTC 5m UP: n=2,808 WR 81.98% +$1.53/tr +$4,285.
  - `xa_all_with_bet` ALL universe: n=19,291 WR 80.92% +$0.67/tr +$13,020.
  - `xa_maj_with_bet` ALL: n=26,205 WR 81.02% +$0.43/tr +$11,361.
  - **SOL is BROKEN under cross-asset**: SOL UP n=3,280 WR 80.15% −$0.43/tr −$1,426/28d (LOSER).
  - On 15m S7 (baseline LOSES −$5,846): xa_all flips to +$559/28d (n=4,895) → **+$6,405 vs baseline**.
- **Ribbon corr:** Stacks on S1.5; weakly correlated with single-asset RF.
- **Asset-specific:** SOL portfolio-negative; BTC/ETH positive.
- **HL-port score:** **2** — needs all 3 asset HL feeds (which we already plan). Code rebuild trivial.

### 8.2 MTF confluence — `cross_full_agree`, `cross_partial_agree`

- **What:** 1m + 5m + 15m + 1h trend agreement booleans.
- **Inputs:** Multi-TF EMA stacks.
- **Source:** `strategy_lab/meta_classifier/cross_asset_mtf_confluence.py`.
- **Filter or signal:** Gate.
- **Edge:** From `_indicator_overlay_inbox`:
  - On momo_v2 ETH 15m: `cross_full_agree` n=89/131 WR 58.4% sel_upl +$186 per_tr +$3.11.
  - On momo_v1 SOL 15m: `cross_full_agree` n=25/36 WR 48.0% sel_upl +$74 per_tr −$2.32 (mixed).
- **Ribbon corr:** Overlap with ribbon_alignment is moderate.
- **HL-port score:** **5**.

### 8.3 BTC lead-lag — `btc_ret`, `self_ret`, `btc_leads_alt`

- **What:** `(close_now/close_prev)-1` over 120s window for BTC and self.
- **Source:** `strategy_lab/discovery_2026_05_16/strat_F_cross_asset.py::fetch_btc_and_self`.
- **Filter or signal:** Either.
- **Edge:** Not headline in current results.
- **HL-port score:** **5**.

### 8.4 Coinbase / Kraken premium + agreement — `coin_ret_60s`, `premium_ws`, `kraken_ret_60s`, `kraken_premium_ws`, F9 3-venue gate

- **What:** Log price ratio binance vs other CEX; F9 = 3 venues all agree on direction.
- **Inputs:** Binance + Coinbase + Kraken 1m closes.
- **Source:** `strategy_lab/meta_classifier/momo_filter_overlay.py::attach_kline_features`.
- **Filter or signal:** Gate.
- **Edge:** Used in V5 ETH strategy (`V2+session`). Not isolated.
- **HL-port score:** **3** — needs cross-venue HL+CEX data. HL is its own price reference.

### 8.5 CryptoCap dominance — BTC.D, ETH.D, total cap

- **Source:** `load_cryptocap_dominance(symbol_id, period_id)`. Raw loader only — no feature builders.
- **HL-port score:** **5** (data already there).

---

## 9. VWAP-anchored features

### 9.1 Slot-anchored VWAP S1.5 — `dev_bps`, fire when `thr_min < |dev_bps| ≤ thr_max`

- **What:** `vwap = Σ(close·vol)/Σ(vol)` from slot_start to fire_us, `dev_bps = 10_000 · ln(close_now/vwap)`.
- **Inputs:** 1s binance bars between `slot_start` and `t = slot_start + offset_s`.
- **Source:** `strategy_lab/meta_classifier/anchored_vwap_fade_5m.py::build_per_asset_arrays`; `vwap_continuation_5m.py::build_per_asset`. Per-fire panel: `s15_*.parquet`.
- **Filter or signal:** **Standalone signal generator** — the S1.5 family.
- **Edge:** 10-sleeve S1.5 base subtotal ~$8,689/28d. Top:
  - BTC_210_5-10bps: n=529 WR 87.3% +$2.99/tr +$1,581.
  - ETH_210_10-15bps: n=138 WR 87.0% +$10.92/tr +$1,508.
  - With ribbon overlay: +$10,300/28d (10 sleeves).
- **Ribbon corr:** R2 standalone ribbon rule overlaps 82% with S1.5 slugs.
- **Asset-specific:** Universal.
- **HL-port score:** **1** — depends on Polymarket SLOT semantics (`slot_start`, settlement window). HL has no equivalent. **The strategy doesn't port**; the VWAP indicator itself ports trivially (score 5) but needs different anchor logic on HL.

### 9.2 15m-bucket-anchored VWAP — `vwap_15m`, `dev_bps`, `sigma_per_sqrt_sec`

- **What:** VWAP anchored to UTC 15m buckets; sigma = rolling 900-bar std of 1s log-returns.
- **Inputs:** 1s binance bars.
- **Source:** Same module as §9.1.
- **HL-port score:** **5** — standard anchored VWAP, HL-compatible.

### 9.3 `g_vwap_ge_50_le_85` — entry vwap sweet zone

- **What:** Force entry vwap (book-fill price) into [$0.50, $0.85]. Avoids <$0.30 catastrophe + >$0.85 low margin.
- **Inputs:** Per-fire entry vwap from L25 book walk.
- **Source:** Derived in `hybrid_fire_universe_build.py`.
- **Filter or signal:** Gate.
- **Edge:** "Killer feature in 15m hunt" — appears in 9 of top 15 new 15m sleeves. e.g. `poly_updown_eth_15m_off60_120_v1` n=87, test $/tr +$8.06, WR 89% OOS.
- **HL-port score:** **1** — depends on Polymarket 0–1 token price. On HL perp, "entry price in sweet zone" has no direct analog. HOWEVER — could become "entry far enough from liquidation / TP / SL band" with re-derivation.

### 9.4 Slot-anchored micro-VWAP for S6 spike — fire when |ret_5s|>thr AND CVD agrees

- See §3.7. HL-port **5**.

### 9.5 Trade-flow VWAP `momentum_30s`

- **What:** `(vwap_last_30s − vwap_prior_30s) / vwap_prior_30s`.
- **Source:** `strategy_lab/confluence/flow/features.py::compute_trade_features`.
- **HL-port score:** **3** — needs HL trade tape, which we have via `load_hyperliquid_trades`.

### 9.6 1h / 4h rolling regression slope — `slope_1h`, `slope_4h`, `realized_vol_1h`

- **Source:** `strategy_lab/confluence/structure/btc_trend.py`.
- **HL-port score:** **5**.

---

## 10. Calendar / session features

### 10.1 Hour-of-Day Top-8 — `is_hod_top_8`

- **What:** Per-sleeve, the 8 best-performing UTC hours out of 24, learned monthly.
- **Inputs:** Historical sleeve PnL by hour.
- **Source:** `strategy_lab/markov_filter/monthly_hod_refresh.py`. Report: `HOD_REFRESH_2026_05_22.md`.
- **Filter or signal:** Gate.
- **Edge:** Refreshed HoD on existing 11 sleeves → **+$15,900/28d** (vs $+2,949 shipped baseline = **5.4× lift**). The single biggest config-edit lift in the deploy spec.
- **Ribbon corr:** Orthogonal (time-based).
- **Asset-specific:** Per-sleeve, refreshed monthly.
- **HL-port score:** **5** — just relearn on HL fire timestamps.

### 10.2 Active session — `g_tr_in_active_session`

- See §5.6.

### 10.3 Day-of-week — implied in HoD refresh; not separately exposed.

### 10.4 Psy week — see §5.7.

---

## 11. F-series wallet gates

### 11.1 F7 — RSI(14) agreement at ws_s

- See §1.1. Two modes: `basic` (UP>50, DOWN<50), `extreme` (UP>60, DOWN<40). Per-sleeve sign-dependent.
- **HL-port score:** **5**.

### 11.2 F1 — extreme-price guard

- **What:** Block fire when entry_price < 0.35 or > 0.65.
- **Source:** `strategy_lab/confluence/guard/filters.py::compute_extreme_price`.
- **HL-port score:** **1** — Polymarket token price. No HL analog.

### 11.3 F2 — dead-market guard

- **What:** Block if `|Δ BTC over t90→open| < $5`.
- **Source:** Same module.
- **HL-port score:** **5**.

### 11.4 F3 — counter-trend guard

- **What:** Block continuation when `move ≥ 10 AND velocity agrees`.
- **Source:** Same.
- **HL-port score:** **5**.

### 11.5 F4 — choppiness (Bill Williams Choppiness Index > 0.70)

- **Source:** Same.
- **HL-port score:** **5**.

### 11.6 F5 — sparse-book filter

- **What:** Block when L25 book has <25 events in fire window.
- **Source:** `strategy_lab/book_filters.py::filter_by_min_book_events`.
- **HL-port score:** **3** — HL L25 has equivalent metric. Rewire min-events check on HL book stream.

### 11.7 F8 — CVD filter (production momo overlay)

- See §3.2 (`attach_cvd_features`).
- **HL-port score:** **5** for binance-side; **1** for Polymarket-side.

### 11.8 F9 — 3-venue agreement (binance + coinbase + kraken)

- See §8.4.
- **HL-port score:** **3**.

### 11.9 F2 wallet's "slug-selector" (UNDECODED)

- 86% WR on F2's 102 cherry-picked slugs but trigger formula unknown — see F2_FINAL_VERDICT.
- **HL-port score:** **N/A** (decoded research, not generalizable).

---

## 12. Polymarket-only signals

### 12.1 Entry vwap (Polymarket book fill at fire_us)

- **What:** Effective entry price from L25 walk of $25 notional.
- **Source:** `strategy_lab/book_walk.py::book_walk_fill`. `engine_v2.fill_at_book`.
- **HL-port score:** **1** — Polymarket-binary semantics.

### 12.2 Microprice — `microprice = (bid·ask_size + ask·bid_size)/(bid_size+ask_size)`

- **What:** Asymmetric mid biased toward the side with less liquidity.
- **Source:** Recommended from `txbabaxyz/mlmodelpoly`; not yet built in our stack.
- **Edge:** Replaces standard mid in fill estimation; better than vwap for paper backtest fills.
- **HL-port score:** **3** — HL L25 books have bid/ask + sizes. Same math. Implementation ~4 lines in `engine_v2.fill_at_book`.

### 12.3 Sparse-book filter — see §11.6.

### 12.4 PM dip detector — `up_dip`, `down_dip`

- **What:** Temporary drop on UP or DOWN side > X bps in <3s while binance hasn't moved.
- **Source:** `txbabaxyz/mlmodelpoly` (proposed port). NOT YET BUILT.
- **Edge:** Free contrarian edge if detected in <30s. UNMEASURED in our archive.
- **HL-port score:** **1** — Polymarket counterparty-mistake pattern. HL has its own micro-mispricings but the dynamic is different.

### 12.5 Slug-age / market-age — implied via `slot_start_us`.

- **HL-port score:** **1** — Polymarket lifecycle.

### 12.6 L25 book imbalance / depth — `imb_l1`, `imb_l5`, `imb_l10`, `imb_l25`, `bid_max_size_l10_usd`, `depth_l5_usd`, `depth_l10_usd`, `depth_l25_usd`, `imb5_signal_aligned_0p10`

- **Source:** `strategy_lab/confluence/flow/features.py::compute_book_features`.
- **Edge (`imb5_signal_aligned_0p10`):**
  - On sniper SOL 15m: n=67/189 WR 59.7% sel_upl +$308 per_tr +$3.66 p=0.090.
  - On momo_v1 ETH 5m: n=149/467 WR 49.0% sel_upl +$327 per_tr −$1.62 p=0.156.
  - On sniper ETH 15m: n=176/356 WR 44.3% (−5.1pp) sel_upl **−$467** — **NEGATIVE on this sleeve**.
- **HL-port score:** **3** — HL perp L25 books have analog. Same math, different scale.

### 12.7 Top-5 imbalance + drift + slope — `imb_up`, `mid_now`, `mid_30s_ago`, `drift_30s`, `slope_100_1000`, `spread`, `ap0`, `bp0`

- **Source:** `strategy_lab/discovery_2026_05_16/strat_E_book_micro.py::compute_features_for_market`.
- **HL-port score:** **3**.

### 12.8 Spread filters — `spread<0.02` (BTC/ETH), `<0.025` (SOL)

- **HL-port score:** **3**.

### 12.9 Mint-and-sell maker strategy gates

- Polymarket-CLOB-specific. Score **1**.

---

## 13. Fair value / probabilistic models

### 13.1 Black-Scholes UP/DOWN — `compute_fair_updown(s_now, ref_px, sigma_15m, tau_sec)` → `{fair_up, fair_down, z_score}`

- **What:** Log-normal price dynamics; terminal price > ref_px probability via standard-normal CDF of z.
  ```
  z = [ln(S_now/ref_px) + drift·τ_norm] / (sigma_15m · √τ_norm)
  fair_up = Φ(z)
  ```
- **Inputs:** binance close `S_now`, chainlink strike `ref_px`, realized 15m vol `sigma_15m`, time-to-settlement `tau_sec`.
- **Source:** `txbabaxyz/mlmodelpoly` (proposed port). Used as gate `fair_edge_bp_gt_0`, `fair_edge_bp_gt_500`, `fair_edge_bp_gt_500_AND_cvd30`.
- **Filter or signal:** Either.
- **Edge:**
  - On `momo_v1 BTC 15m`: `fair_edge_bp_gt_500` n=55/137 WR 63.6% (+9.6pp) sel_upl +$273 per_tr +$5.98 p=0.097.
  - On `momo_v2 BTC 5m`: `fair_edge_bp_gt_500` n=314/810 WR 52.9% (+4.1pp) sel_upl +$618 per_tr +$0.34 p=0.081.
  - On `momo_v2 BTC 15m`: `fair_edge_bp_gt_0` n=96/225 WR 61.5% (+8.6pp) sel_upl +$413 per_tr +$4.69 p=0.056.
  - On `sniper SOL 15m`: `fair_edge_bp_gt_500` n=32/189 WR 65.6% (+14.8pp) sel_upl +$288 per_tr +$8.06 p=0.066.
  - **On `momo_v1 BTC 5m`: NEGATIVE** — `fair_edge_bp_gt_0` n=337/784 WR 44.5% (−3.2pp) sel_upl −$535.
- **Ribbon corr:** Likely orthogonal (probabilistic vs trend).
- **Asset-specific:** Stronger on 15m than 5m.
- **HL-port score:** **2** — needs a STRIKE reference. On HL we'd compare fair_perp (from spot Black-style) vs perp mark. Requires different setup but feasible.

### 13.2 v2 probabilistic stack — `prob_a` (multi-horizon momentum), `prob_b` (vol-arb digital), `prob_c` (PM microstructure flow), `prob_stack` (logreg meta)

- **What:** Calibrated-probability stack. v2 design.
- **Source:** `strategy_lab/v2_signals/`. **KILLED** in POLYMARKET_V2_SIGNALS_FINDINGS (forward-walk failed all 4 — drifted 8–11pp train→test).
- **Edge:** In-sample IC +0.08–0.12. OOS holdout collapses (e.g. prob_c 5m ALL: 61.7% train → 50.2% test, −11.5pp).
- **HL-port score:** **2** — code exists but DO NOT PORT until validated on 30+ days.

### 13.3 Mispricing / cross-book — `p_clob_up = mid_up`, `fair_p_up = clamp(0.5 + 0.5·tanh(2·z), 0.1, 0.9)`, `edge = fair_p_up − p_clob_up`

- **Source:** `strategy_lab/discovery_2026_05_16/strat_H_mispricing.py`.
- **HL-port score:** **1** — `mid_up` is Polymarket-specific.

---

## 14. Funding / OI / liquidations

### 14.1 HL funding rate — `hl_funding`, `hl_funding_min_4h`, `hl_funding_max_4h`, `hl_funding_cross_4h`

- **Source:** `load_hyperliquid_funding`. Used by `strategy_lab/discovery_2026_05_16/strat_D_funding_oi.py::build_features`.
- **HL-port score:** **5** — HL-native.

### 14.2 OI delta — `oi_delta_5m, _15m, _1h`, `oi_pct_chg_4bar, _24bar`

- **Source:** Binance metrics (`load_binance_metrics`) or HL (`load_hyperliquid_metrics`).
- **Edge:** Mild — univariate Pearson −0.006 to −0.039.
- **HL-port score:** **4–5**.

### 14.3 OI value delta — `oiv_delta_5m`

- **Source:** binance metrics. Pearson −0.006.
- **HL-port score:** **4**.

### 14.4 HL liquidation cascade — `liq_count_15m`, `liq_notional_15m`, `liq_notional_z_7d`, `liq_net = sum(short_n) − sum(long_n)`

- **Source:** `load_hyperliquid_liquidations`; `strategy_lab/discovery_2026_05_16/strat_C_hl_liqs.py::build_liq_arrays`.
- **Edge:** Strategy generator: signal = UP if `net > T`, DOWN if `< −T`.
- **HL-port score:** **5** — native HL.

### 14.5 Liquidation magnet — `liq_magnet_active`, `liq_magnet_dist_bps`

- **What:** 1-D sliding cluster detection on liquidation prices. Per-asset radius (BTC $200, ETH $40, SOL $2). Min cluster 3.
- **Source:** `strategy_lab/confluence/trigger/liq_magnet.py::compute_liq_magnet`.
- **HL-port score:** **5**.

### 14.6 Funding z-score — `funding_rate_z_30d`

- **HL-port score:** **5**.

### 14.7 Premium z-score — `premium_z_30d`

- **What:** Z-score of perp-spot premium.
- **HL-port score:** **4**.

---

## 15. Smart-money & guard filters

### 15.1 FVG (Fair Value Gap) — `fvg_active`, `fvg_side ∈ {up, down}`

- **What:** Unfilled 3-candle gap within lookback (default 30 min).
- **Source:** `strategy_lab/confluence/trigger/fvg.py::compute_fvg`.
- **Filter or signal:** Gate.
- **HL-port score:** **5**.

### 15.2 S/R swing levels — `dist_to_resistance_bps`, `dist_to_support_bps`

- **What:** Local extremum confirmed by 30 bars each side. Distance in bps.
- **Source:** `strategy_lab/confluence/structure/sr_levels.py`.
- **HL-port score:** **5**.

### 15.3 Choppiness — Bill Williams CI

- See §11.4.

### 15.4 OFI (Order Flow Imbalance, 30s) — `ofi_30s ∈ [-1, +1]`

- **Source:** `strategy_lab/confluence/trigger/ofi.py::compute_ofi_30s`.
- **HL-port score:** **3**.

### 15.5 Composite guard `compute_all_guards(...)`

- Combines extreme_price + dead_market + counter_trend + choppiness.
- **HL-port score:** **1–5** (mixed — F1 is 1, others are 5).

---

## 16. Composite / meta-classifier features

### 16.1 Flow score — composite of CVD + imbalance + aggressor_ratio_30s + momentum_30s

- **Source:** `strategy_lab/confluence/flow/features.py::compute_trade_features`.
- **HL-port score:** **3**.

### 16.2 `signal_confidence` (QR Lite) — 0..8 composite. See §2.2.

### 16.3 `market_health` (QR Lite) — 0..100 composite. See §2.2.

### 16.4 `prob_a/b/c/stack` — v2 stack (KILLED). See §13.2.

### 16.5 Tier-1 hybrid gate stacks (the WINNING composite gates from PER_SLEEVE_CATALOG)

Per-cell BEST gate stack (walk-forward PASS):

| Cell | Stack | n | WR | $/tr | sum/28d |
|---|---|---|---|---|---|
| BTC S6 5m 60-150 | `cci ∧ stoch ∧ rf ∧ tr_above_ema50 ∧ ribbon` | 2,764 | 77.8% | +$5.10 | +$14,103 |
| ETH S6 5m 60-150 | `cci ∧ bb_pos ∧ ribbon` | 3,531 | 76.0% | +$1.57 | +$5,553 |
| ETH S1.5 5m 150-240 | `ribbon ∧ tr_above_ema200 ∧ stoch ∧ bb_pos ∧ cci` | 3,420 | 85.1% | +$1.34 | +$4,596 |
| BTC S1.5 5m 150-240 | `tr_above_pp ∧ ribbon ∧ stoch ∧ tight_ribbon` | 1,365 | 85.6% | +$3.06 | +$4,176 |
| SOL S6 5m 60-150 | `mfi ∧ within_dev ∧ bb_pos ∧ ribbon` | 1,503 | 92.9% | +$2.20 | +$3,307 |
| BTC S7 15m 480-840 | `tr_stack_full ∧ tr_above_ema800 ∧ ribbon ∧ tight ∧ stoch ∧ tr_above_ema200` | 816 | 88.0% | +$2.15 | +$1,751 |
| SOL S7 15m 480-840 | `dev_extreme ∧ rf_aged ∧ tr_within_adr ∧ tr_above_pp` | 42 | 97.6% | +$21.79 | +$915 |

- **HL-port score:** **5** for each component gate; the COMBINATION needs cell-specific calibration on HL data.

---

## 17. The 13-gate combinatorial library (NEW_INDICATORS_COMBINATORIAL)

This is the canonical "gate library" used by `gate_search` to enumerate combinations. Each gate is a binary boolean evaluated at fire_us.

| # | Gate | Definition | S1.5 cite-share | S6 cite-share | HL-port |
|---|---|---|---|---|---|
| 1 | `ribbon_color_bull` | `ribbon_color ∈ {bull values}` | 7.2% | 9.4% | 5 |
| 2 | `ribbon_color_bear` | mirror | 8.2% | 6.9% | 5 |
| 3 | `ribbon_agrees` | ribbon color matches bet direction | 9.7% | 11.9% | 5 |
| 4 | `ribbon_strong` | `ribbon_alignment_pct ≥ 95%` | 6.6% | 13.5% | 5 |
| 5 | `ribbon_compressed` | `ribbon_compression_bps < 2bps` | 8.2% | 5.1% | 5 |
| 6 | `ribbon_expanded` | inverse | 0.1% | — | 5 |
| 7 | `stoch_60s_agrees` | `sign(K60−D60)==dir` | 8.6% | 13.6% | 5 |
| 8 | `stoch_60s_neutral` | K60 in [20, 80] | 5.3% | 0.2% | 5 |
| 9 | `stoch_60s_kd_cross` | K60 crossed D60 in last bar agreeing with dir | **12.5%** | 6.3% | 5 |
| 10 | `bb_pos_60s_extreme_agrees` | `(bb_pos<0.1 AND DOWN) OR (>0.9 AND UP)` | 11.5% | **14.6%** | 5 |
| 11 | `bb_pos_60s_neutral` | bb_pos ∈ [0.3, 0.7] | 5.2% | 0.9% | 5 |
| 12 | `mfi_60s_neutral` | mfi ∈ [40, 60] | 8.3% | 3.9% | 5 |
| 13 | `cci_60s_agrees` | sign(cci) matches dir | 8.5% | **13.6%** | 5 |

Plus 8 SMS gates (§4):
- `g_sms_liq_reclaim_with`, `g_sms_recent_choch_with`, `g_sms_recent_bos_with`, `g_sms_cvd_with`, `g_sms_trend_strength_with`, `g_sms_conf_high`, `g_sms_no_liquidity_above`, `g_sms_rsi_div_with`.

Plus 6 QR gates (§2.2):
- `g_qr_state_with`, `g_qr_state_strong_with`, `g_qr_high_conf`, `g_qr_top_conf`, `g_qr_volume_strong`, `g_qr_high_health`, `g_qr_conf_4_to_6`.

Plus 10 DRZ gates (§6.3):
- `g_drz_in_support`, `g_drz_in_resistance`, `g_drz_at_support_with_up`, `g_drz_at_resistance_with_dn`, `g_drz_recent_RC_with_up`, `g_drz_recent_RE_with_dn`, `g_drz_not_contra_zone`, `g_drz_n_zones_high`, `g_drz_close_to_zone`, `g_drz_pos_pct_high`.

Plus regime gates (§7.1):
- `g_trending_up_with_up`, `g_trending_dn_with_dn`, `g_ranging`, `g_trend_agrees`, `g_regime_score_pos`.

Plus production gates (overlay inbox):
- `m1v_pass`, `m5v_pass`, `m1v_AND_m5v`, `cross_full_agree`, `cross_partial_agree`, `fair_edge_bp_gt_0`, `fair_edge_bp_gt_500`, `fair_edge_bp_gt_500_AND_cvd30`, `cvd_agree_30s`, `cvd_agree_60s`, `cvd_agree_120s`, `cvd_agree_30s_AND_60s`, `cvd_agree_30s_AND_macd`, `macd_agree`, `imb5_signal_aligned_0p10`, `rvol_30_300_gt_1p2`.

---

## 18. Negative / kill-listed features

Verified as **non-useful or anti-edge** in this archive — do NOT port.

| Feature | Why killed |
|---|---|
| **R4 Compressed Breakout** (ribbon only) | −$200k sum across cells; compression alone doesn't predict direction |
| **R1 Pure Color Trend** | 73% WR but loses money due to adverse entry vwap |
| **H1 Stoch fade overbought** | Median ΔWR +6.4pp — fires KEEP winning when overbought |
| **H3 Stoch oversold bounce** | Median −$1.37/tr |
| **Standalone QR rules A/B/C** | All lose; WR ~44% (below 50% breakeven) |
| **C_trend_strength (SMS multi-TF)** | −$0.62/tr standalone; redundant with ribbon |
| **F_cvd_aligned (SMS)** | −$0.95/tr standalone |
| **D_top_confidence (SMS conf=90)** | Too sparse (n=43); −$5+/tr |
| **PVSRA standalone (5m)** | −37pp WR; only works inside V7 triple-gate |
| **Naive DRZ E_at_support_UP, F_at_resistance_DOWN on BTC/ETH** | Fail walk-forward (only SOL holds) |
| **prob_a, prob_b, prob_c, prob_stack (v2)** | All failed forward-walk holdout (drift 8–11pp); KILL list |
| **book_skew (univariate)** | Pearson −0.070** — anti-signal |
| **F7 on btc_5m_v1 / btc_15m_v2** | Reverses sign; `notF7` lifts +$4.58 / +$4.18 |
| **S6 BTC UP in trending_up regime** | −$1.40/tr (counter-intuitive trend-exhaustion zone) |
| **SOL S1.5 universe under xa_all_with_bet** | −$1,426/28d (SOL is portfolio-negative under cross-asset filter) |

---

## 19. HL-PORT SHORTLIST (top 25)

Ranked by `edge × portability`. Top of this list = port FIRST.

| Rank | Indicator / gate | Edge (best documented) | Port score | Why |
|---:|---|---|---:|---|
| 1 | **Madrid ribbon (20 EMA 5-100) + `g_ribbon_agrees`, `tight_ribbon`** | Universal: S1.5 $/tr 3.6× ($0.16→$0.56); S6 + tight ribbon +$17,391/28d | 5 | Pure 1s kline; HL has 1s candles via `load_hyperliquid_klines` |
| 2 | **RSI(14) Wilder simple-mean + F7 gate** | F7 lifts WR 44→51% on prod; 94.67% match to live | 5 | Identical math on HL; 15-bar window |
| 3 | **Markov M1V (w20, 1m, vol-adaptive)** | btc_15m_v1 +$2.61/tr; sniper ETH 15m +$7.15/tr (p=0.011) | 5 | Pure kline; rolling q33/q66 over 14d. Same on HL |
| 4 | **Slow Stoch composite (60s + 300s)** | s6 BTC: $3→$8/tr (+$5); s6 BTC DOWN k60 low_neutral: +$18.55/tr WR 64% (n=245) | 5 | 1s kline; trivial |
| 5 | **BB position 60s + extreme_agrees** | #1 cited S6 gate (14.6%); ETH 210 stack +$10.78/tr | 5 | 1s kline |
| 6 | **CCI 60s + cci_agrees** | #2 S6 (13.6%); universal combo total $/tr +$5.02 across 14 cells | 5 | 1s kline |
| 7 | **MFI 60s + mfi_neutral** | 8.3% S1.5 cite; ETH 210 mega-combo $/tr +$11.27 | 5 | 1s OHLCV |
| 8 | **CVD on binance 1s (cvd_slope_30/60s, cvd_agree)** | sniper SOL 5m cvd_AND_macd: WR 59.2% +$3.21/tr p=0.091 | 5 | HL 1s klines include taker_buy_base |
| 9 | **Range Filter [DW] + g_rf_with / g_rf_aged** | Fire-time rf_dir 92.65% agree on s6; central to Tier-1 BTC S6 (+$14k/28d) | 5 | Pure 1s kline math; bit-perfect port |
| 10 | **S6 spike detection (ret_5s/15s/30s + CVD agree) D1-D4** | Sharpe up to **15.10** (highest in study); BTC off60 D4 WR 83.5% +$4.88/tr | 5 | 1s OHLCV + taker_buy. HL native |
| 11 | **SMS liquidity_reclaim (g_sms_liq_reclaim_with)** | **STAR**: BTC S6 +$13.6/tr lift (3.7×); orthogonal corr −0.07 vs ribbon; standalone BTC S6 off=120 +$20.68/tr | 5 | 5m/15m OHLC + 20-bar rolling extremes |
| 12 | **SMS BOS / CHoCH (sparse event flags)** | A_bos_continuation s6_5m WR 73.2% +$1.59/tr; B_choch_reversal best cell WR 85.7% +$7.44/tr | 5 | Pure OHLC pivot logic |
| 13 | **Traders Reality EMA stack (5/13/50/200/800)** | BTC bull&UP WR 88.2% (vs 81% base); centrally in Tier-1 (BTC S6 5m 60-150) | 5 | 1s kline |
| 14 | **`g_tr_above_ema50/200/800/cloud/pp`** | Featured in 5 of top-7 Tier-1 stacks | 5 | 1s kline |
| 15 | **ADX(14) regime classifier (3-state)** | Flips S7 ETH DOWN baseline −$0.62 → OOS +$7.46/tr (CI [+3.99, +11.79]); S1.5 SOL DOWN OOS +$4.81 | 5 | 5m/15m OHLC + Wilder |
| 16 | **Slot-/15m-anchored VWAP + dev_bps** | S1.5 family generator; ETH 210 10-15bps +$10.92/tr +$1,508/28d | 5 | The MATH ports; the slot-anchor logic doesn't (HL has continuous time — needs alternative anchor like "bar-open" or "session-open") |
| 17 | **HoD-Top-8 (monthly refresh)** | S3 patch +$15,900/28d (5.4× lift on existing 11 sleeves) | 5 | Per-strategy historical learning; relearn on HL fire data |
| 18 | **DRZ + `g_drz_not_contra_zone`** | BTC S6 hybrid +$369 (+2.6%); SOL standalone F_at_resistance_DOWN +$1,927/28d p=0.005 | 5 | 5m/15m OHLCV; ATR-based zones |
| 19 | **`tr_within_adr` + sessions + pivots** | SOL S7 15m hybrid: n=42 WR 97.6% **+$21.79/tr** (highest in study) | 5 | Daily ADR rolling + clock |
| 20 | **Cross-asset RF agreement (xa_all_with_bet, xa_maj)** | BTC 5m DOWN xa_all: n=2,726 WR 82.1% +$4,463/28d; flips S7 from −$5,846 to +$559 | 2 | Needs all 3 HL feeds — already planned |
| 21 | **QR `g_qr_volume_strong`, `g_qr_high_health`** | BTC s6_5m volume_strong: $5.10→$22.37/tr; high_health: +$4.47/tr; both walk-fwd PASS | 5 | 5m resample + EMA + vol_ratio |
| 22 | **HL funding + OI + liquidation cascade** | HL liq net signal generator; funding cross_4h state | 5 | HL-native |
| 23 | **MACD agreement + cvd_AND_macd** | sniper SOL 5m: n=98/410 WR 59.2% +$3.21/tr p=0.091 | 5 | 1m kline; talib.MACD |
| 24 | **Fair value (Black-Scholes UP/DOWN) — `fair_edge_bp_gt_500`** | momo_v2 BTC 15m: n=96 WR 61.5% +$4.69/tr p=0.056; sniper SOL 15m: n=32 WR 65.6% +$8.06/tr p=0.066 | 2 | Needs a strike reference. On HL: compare implied fair vs perp mark over slot — re-derive |
| 25 | **Microprice (4-line drop-in)** | Untested but theoretically improves fill estimate; trivial integration | 3 | HL L25 has bid/ask + sizes |

---

## 20. Indicators that DO NOT PORT (Polymarket-specific, score 1)

Listed for completeness — do not try to port.

- **Entry vwap on Polymarket book** (binary 0–1 token)
- **PM dip detector** (Polymarket counterparty mistakes)
- **`g_vwap_ge_50_le_85`** (sweet-zone gate on PM token price)
- **F1 extreme-price guard** (uses Polymarket token price)
- **Slug-age, slot lifecycle, slot_start anchor**
- **CVD on Polymarket trade prints** (BUY/SELL of UP/DOWN tokens)
- **CLOB mid mispricing (`p_clob_up = mid_up`)**
- **F2 wallet's slug-selector** (undecoded; specific to Polymarket markets)
- **`with_clob_winner` outcome** (Polymarket settlement)
- **Maker rebate / mint-and-sell** (Polymarket CLOB-specific)

---

## 21. Compute-time / panel-size notes for HL port

For each indicator family, the canonical Polymarket panel cost (so we can estimate HL equivalent):

| Panel | Source script | Size | Compute time | HL equivalent |
|---|---|---|---|---|
| Madrid ribbon (1s, 20 EMAs + derivatives) | `compute_ta_indicators.py` | 1.28 GB | ~10s on 5.5M bars | Same on HL 1s; ~1 GB per asset |
| Traders Reality (1s, 82 cols) | `compute_traders_reality.py` | 680 MB | ~30s | Same |
| Range Filter [DW] (1s) | `compute_range_filter.py` | small | <10s | Same |
| QR Lite (5m + 15m) | `compute_qr_panel.py` | 2.6 + 0.9 MB | ~5s | Same |
| SMS (5m + 15m) | `compute_sms_panel.py` | 1.1 + 0.4 MB | ~5s | Same |
| DRZ (5m + 15m) | `drz/build_drz_panel.py` | 7.8 + 2.4 MB | ~30s | Same |
| Regime (5m + 15m) | `build_regime_panel.py` | 7,749 + 2,584 bars × 3 assets | ~5s | Same |
| Markov labels (1m/5m × fixed/vol_adaptive × 3 assets) | `markov_regime_micro.py::build_labels_for_asset` | per-asset int8 | ~3s/asset | Same |
| CVD on 1s (with taker_buy) | `_cvd_timing_overlay.py::build_cvd_table` | per-asset | ~5s | Same — HL has taker_buy_base |
| Hyperliquid funding/OI/liq | `load_hyperliquid_*` | native | already there | native |

Total HL feature panel: ~3–5 GB per asset for 28d 1s + 5m/15m derivatives. Single-machine compute ~3–5 min.

---

## 22. Order of next steps (data flow for HL port)

1. Pull HL 1s OHLCV with `taker_buy_base` for BTC, ETH, SOL — already provided via `load_hyperliquid_klines`.
2. Build base panels: Madrid ribbon, RF [DW], TR EMA stack on HL 1s.
3. Compute slow stoch / BB / MFI / CCI / ATR / ADX on 5m HL klines.
4. Build TA 1s panel mirroring `ta_indicators_1s.parquet` schema on HL.
5. Build SMS, QR, DRZ, Regime panels on HL 5m + 15m resampled klines.
6. Compute CVD slope_30/60s on HL 1s.
7. Implement HL liquidation magnet (clusters in HL liq tape).
8. RSI(14) at fire anchor — same code (`compute_rsi_14`).
9. Markov labels (M1V) on HL 1m closes.
10. Cross-asset xa_all_with_bet on HL BTC/ETH/SOL.
11. Fair value: re-derive against perp mark (NOT chainlink strike) — `compute_fair_perp(spot, perp, sigma, tau)`.
12. Replace `entry_vwap` with HL L25 walk fill from `load_hyperliquid_l25` (when available) or trade-tape mid.

---

## 23. Cross-reference checklist (already in synthesis docs — DO NOT redo)

The team's two existing docs already cover, in narrative form:
- `NEW_INDICATORS_SYNTHESIS_2026_05_26.md` — high-level findings on DRZ, QR, SMS, regime + 15m hunt; deploy roster.
- `PER_SLEEVE_CATALOG_2026_05_26.md` — every (strategy, asset, tf, offset, gate-stack) row with WR / $/tr / sum.

**This registry covers, that they don't:**
1. Indicator math + source files in one place (not split across reports).
2. HL portability score per indicator.
3. The 13-gate combinatorial library inventory.
4. Negative / kill list.
5. Univariate Pearson IC tables (POLYMARKET_FEATURES_UNIVARIATE).
6. Production guard filters (F1–F9) — not in either synthesis doc.
7. v2 probabilistic stack (KILLED) — historical context.
8. Markov sub-variants (M1V/M1F/M5V/M5F) per-sleeve table.
9. Microprice + PM dip + Black-Scholes UP/DOWN (proposed from mlmodelpoly).

---

## End of registry

Total distinct indicators / gates catalogued: **~120**.
Top 25 HL-portable: §19 above.
Kill list: §18.
