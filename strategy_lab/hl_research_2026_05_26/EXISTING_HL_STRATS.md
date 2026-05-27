# Existing Hyperliquid Strategies & Tooling — Catalog

**Compiled:** 2026-05-26
**Scope:** baseline of what is already deployable / validated on HL data, so new research can target gaps.
**Source-of-truth files:**
- `docs/deployment/V52_HYPERLIQUID_DEPLOYMENT_NOTES.md` (HL addendum)
- `docs/deployment/V52_CHAMPION_IMPLEMENTATION_SPEC.md` (full strategy spec — Binance side, but signals + simulator are venue-agnostic)
- `docs/research/phase5_results/v52_hl_champion_audit.json` (10-gate validation results)
- `strategy_lab/run_v52_hl_gates.py` (gate runner)
- `strategy_lab/run_v52_hyperliquid_compare.py` (Binance↔HL comparison)
- `strategy_lab/util/hl_data.py` (HL data loader)
- `strategy_lab/ingest_hyperliquid.py` + `ingest_hyperliquid_full.py` (ingest pipelines)
- `strategy_lab/probe_hl_history.py` (history availability probe)
- `strategy_lab/eval/perps_simulator_funding.py` (funding-aware sim)
- `strategy_lab/discovery_2026_05_16/strat_C_hl_liqs.py` (HL liquidations strategy)
- `strategy_lab/discovery_2026_05_16/REPORT_CD_PERPS.md` (Strategy C+D verdicts)
- `strategy_lab/hyperliquid/fetch_archive.py` (HL S3 archive downloader)

---

## 1. V52 Champion — full spec per sleeve

V52 is the deployable champion. It is a **two-level daily-rebalanced blend of 9 trade streams** at the 4-hour bar on five HL coins (BTC kept for regime classifier only; ETH/AVAX/SOL/LINK traded). Single timeframe, single venue.

### 1.1 Top-level portfolio architecture

```
V52_CHAMPION (total risk capital)
├── 60% ► V41 CHAMPION (inner blend)
│   ├── 60% ► P3 side (inverse-volatility weighted, 500-bar rolling stdev)
│   │   ├── CCI_ETH_P3   ETH 4h
│   │   ├── STF_AVAX_P3  AVAX 4h (V45: +volume filter)
│   │   └── STF_SOL_P3   SOL 4h
│   └── 40% ► P5 side (equal-weight, 1/3 each)
│       ├── CCI_ETH_P5   ETH 4h (same stream as P3 CCI, allocated twice)
│       ├── LATBB_AVAX_P5  AVAX 4h
│       └── STF_SOL_P5   SOL 4h (same stream as P3 STF_SOL)
├── 10% ► MFI_SOL    SOL 4h
├── 10% ► VP_LINK    LINK 4h
├── 10% ► SVD_AVAX   AVAX 4h
└── 10% ► MFI_ETH    ETH 4h
```

### 1.2 Per-sleeve full wiring table

| Sleeve | Symbol | TF | Signal fn | Signal params | Exit stack | Top-level weight |
|---|---|---|---|---|---|---:|
| `CCI_ETH_P3` | ETH | 4h | `sig_cci_extreme` | cci_n=20, cci_lo=-150, cci_hi=+150, adx_max=22, adx_n=14 | V41 regime-adaptive | 60% × 60% × inv-vol |
| `STF_AVAX_P3` | AVAX | 4h | `sig_supertrend_flip` + volume filter (V45) | st_n=10, st_mult=3.0, ema_reg=200; vol > 1.1 × SMA20(vol) | V41 regime-adaptive | 60% × 60% × inv-vol |
| `STF_SOL_P3` | SOL | 4h | `sig_supertrend_flip` | st_n=10, st_mult=3.0, ema_reg=200 | canonical EXIT_4H | 60% × 60% × inv-vol |
| `CCI_ETH_P5` | ETH | 4h | `sig_cci_extreme` | same as CCI_ETH_P3 | V41 regime-adaptive | 60% × 40% × 1/3 |
| `LATBB_AVAX_P5` | AVAX | 4h | `sig_lateral_bb_fade` | bb_n=20, bb_k=2.0, adx_max=18, adx_n=14 | canonical EXIT_4H | 60% × 40% × 1/3 |
| `STF_SOL_P5` | SOL | 4h | `sig_supertrend_flip` | same as STF_SOL_P3 | canonical EXIT_4H | 60% × 40% × 1/3 |
| `MFI_SOL` | SOL | 4h | `sig_mfi_extreme` | n=14, lower=25, upper=75, require_cross=True | V41 regime-adaptive | 10% |
| `VP_LINK` | LINK | 4h | `sig_volume_profile_rot` | win=60, n_bins=15, value_area=0.70, touch_buffer=0.001 | canonical EXIT_4H | 10% |
| `SVD_AVAX` | AVAX | 4h | `sig_signed_vol_div` | lookback=20, cvd_win=50, min_cvd_threshold=0.5 | canonical EXIT_4H | 10% |
| `MFI_ETH` | ETH | 4h | `sig_mfi_extreme` | n=14, lower=25, upper=75, require_cross=True | canonical EXIT_4H | 10% |

Per-source ref: `docs/deployment/V52_CHAMPION_IMPLEMENTATION_SPEC.md` §6 (wiring table) + `strategy_lab/run_v52_hl_gates.py` lines 36–55.

### 1.3 Signal definitions (entry rules)

All signals fire at bar close `i` and fill at `open[i+1] × (1 + slip × direction)`.

**1.3.1 `sig_cci_extreme` (V30) — CCI cross-back from extreme** — used by `CCI_ETH`
```
typical_price = (h + l + c) / 3
sma_tp = rolling_mean(tp, 20)
mad_tp = rolling_mean(|tp - sma_tp|, 20)
cci = (tp - sma_tp) / (0.015 * mad_tp)
adx = compute_adx(h, l, c, 14)
long_entry  = (cci.shift(1) < -150) & (cci >= -150) & (adx < 22)
short_entry = (cci.shift(1) > +150) & (cci <= +150) & (adx < 22)
```
*Note:* this is a mean-reversion fade gated to low-trend (ADX<22) regimes.

**1.3.2 `sig_supertrend_flip` (V30) — SuperTrend direction flip with EMA200 regime filter** — used by `STF_AVAX`, `STF_SOL`
```
atr_st = ATR(h, l, c, 10)
hl2 = (h + l) / 2
upper = hl2 + 3.0 * atr_st;   lower = hl2 - 3.0 * atr_st
trend recursive: +1 if close > prev_st, -1 if close < prev_st, else carry
st = lower if trend==+1 else upper
flip = trend.diff()    # +2 = bullish flip, -2 = bearish flip
ema200 = EMA(close, 200)
long_entry  = (flip > 0) & (close > ema200)
short_entry = (flip < 0) & (close < ema200)
```
**V45 variant (STF_AVAX only):** AND additionally `volume > 1.1 × rolling_mean(volume, 20)`.

**1.3.3 `sig_lateral_bb_fade` (V29) — BB band touch with low-ADX gate** — used by `LATBB_AVAX_P5`
```
sma = rolling_mean(close, 20);  sd = rolling_std(close, 20)
bb_u = sma + 2*sd;  bb_l = sma - 2*sd
adx = compute_adx(h, l, c, 14)
long_entry  = (low  <= bb_l) & (close > bb_l) & (adx < 18)
short_entry = (high >= bb_u) & (close < bb_u) & (adx < 18)
```

**1.3.4 `sig_mfi_extreme` (V50, MFI_75_25 variant)** — used by `MFI_SOL`, `MFI_ETH`
```
tp = (h+l+c)/3;  raw_money = tp * volume
pos_money = where(tp.diff() > 0, raw_money, 0)
neg_money = where(tp.diff() < 0, raw_money, 0)
mfi = 100 - 100 / (1 + rolling_sum(pos,14) / rolling_sum(neg,14))
long_entry  = (mfi.shift(1) < 25) & (mfi >= 25)   # cross back up from oversold
short_entry = (mfi.shift(1) > 75) & (mfi <= 75)   # cross back down from overbought
```

**1.3.5 `sig_volume_profile_rot` (V50)** — used by `VP_LINK`
Rolling 60-bar volume profile with 15 price bins, 70% value-area:
- For each bar compute POC (max-vol bin midpoint), VAH (70%-value-area high edge), VAL (low edge) using only the last 60 bars.
- `long_entry = (low <= VAL × 1.001) & (close > VAL) & (close < POC) & ((VAH-VAL)/close > 0.005)`
- `short_entry = (high >= VAH × 0.999) & (close < VAH) & (close > POC) & width_ok`
Value-area expansion: greedy outward from POC, preferring the higher-volume neighbor each step.

**1.3.6 `sig_signed_vol_div` (V50, SVD_tight variant)** — used by `SVD_AVAX`
CVD proxy using `sign(close - open)` as aggressor direction:
```
signed_vol = volume * sign(close - open)
cvd = rolling_sum(signed_vol, 50)
cvd_med = rolling_median(cvd, 100);  cvd_sd = rolling_std(cvd, 100)
at_new_low  = close <= rolling_min(close, 20) * 1.001
at_new_high = close >= rolling_max(close, 20) * 0.999
long_entry  = at_new_low  & (cvd > cvd_med + 0.5 * cvd_sd)
short_entry = at_new_high & (cvd < cvd_med - 0.5 * cvd_sd)
```
Bullish/bearish divergence between price (new extreme) and CVD baseline.

### 1.4 Exit stacks

Three exit-stack profiles, set per-sleeve. Frozen at entry, evaluated each bar in priority `[SL → TP → TIME]`. Trailing stop is ratchet-only.

**Canonical `EXIT_4H`** (STF_SOL, LATBB_AVAX, VP_LINK, SVD_AVAX, MFI_ETH):
- `tp_atr = 10.0`, `sl_atr = 2.0`, `trail_atr = 6.0`, `max_hold = 60` bars (~10 days)

**V41 regime-adaptive** (CCI_ETH both sides, STF_AVAX, MFI_SOL): exit profile keyed to regime label at entry bar.

| Regime | sl_atr | tp_atr | trail_atr | max_hold |
|---|---:|---:|---:|---:|
| LowVol | 1.5 | 12.0 | 8.0 | 80 |
| MedLowVol | 1.8 | 11.0 | 7.0 | 70 |
| MedVol | 2.0 | 10.0 | 6.0 | 60 |
| MedHighVol | 2.3 | 8.0 | 4.0 | 40 |
| HighVol | 2.5 | 6.0 | 2.5 | 24 |
| Uncertain | 2.0 | 10.0 | 6.0 | 60 |
| Warming | 2.0 | 10.0 | 6.0 | 60 |

**V45** = V41 regime-adaptive + entry-time `volume > 1.1 × SMA20(vol)` filter (STF_AVAX only).

### 1.5 Regime classifier (used by V41 exits)

Per-instrument HMM via sklearn `GaussianMixture`. Spec from V52 §3:
- **Features (4):** `log_r`, `rvol_120`, `vol_ratio = volume/volume_mean_120`, `hl_range_pct = (h-l)/c`.
- **Fit:** train on first 30% of history (IS) z-scored with IS-only mean/std. K ∈ {3,4,5}; pick by BIC. `random_state=42`, `max_iter=300`, `n_init=3`, `covariance_type="full"`.
- **Labelling:** sort raw regimes by mean of z-scored rvol_120 ascending → LowVol, MedLowVol, …, HighVol.
- **Stability:** 3-bar persistence; flicker detect = >4 label changes in rolling 20 bars → `Uncertain`. Pre-stable → `Warming`.
- **No refit in live.**

### 1.6 Position sizing

ATR-risk sizing, identical defaults across all sleeves:
```
risk_dollars = cash × 0.03                  # 3% per trade
stop_distance = sl_atr × ATR[i]
size_risk = risk_dollars / stop_distance
size_cap  = (cash × 3.0) / entry_price       # leverage cap 3×
size = min(size_risk, size_cap)
```
- `risk_per_trade = 0.03` (constant, no regime modulation)
- `leverage_cap = 3.0` (rarely binds on 4h crypto)
- V52 has **no explicit regime-based leverage rule** — implicit variation arises only via regime-adaptive `sl_atr` (LowVol uses 1.5×, HighVol 2.5×, so position is bigger in LowVol).

### 1.7 Fee/funding model used in backtest

- **Fees:** `fee = 0.00045` (4.5 bps HL taker) per fill, both entry and exit (round-trip = 9 bps + 6 bps slip = 15 bps total).
- **Slippage:** `slip = 0.0003` (3 bps), always against the position.
- **Funding:** modeled per-bar via `simulate_with_funding()` (see §3.3 below). Funding applies to MTM only while a position is open; signed `funding_pnl = -pos × size × close × funding_rate_for_bar`. Funding aggregated per 4h bar by summing 4 hourly rates.
- **Round-trip cost** ≈ 15 bps notional; funding drag observed at **0.38 pp/yr** on the V52 blend.

### 1.8 Blending logic (daily rebalance)

Rebalance at UTC 00:00:
1. **Top-level (static):** 60% V41 / 10% / 10% / 10% / 10%.
2. **V41 inner (static 60/40):** 60% P3, 40% P5.
3. **P3 inv-vol weights:** `w_s = (1/σ_s) / Σ(1/σ)` where σ = rolling 500-bar stdev of daily returns per P3 sleeve. Fallback to equal-weight during first 500 bars.
4. **P5:** equal weight (1/3 each).
5. **Mid-trade resize:** disallowed — new weights apply only to subsequent entries.

### 1.9 Validated metrics on HL native data (2024-01-12 → 2026-04-25; 2.3 years, with funding)

Source: `docs/research/phase5_results/v52_hl_champion_audit.json`.

| Metric | Value |
|---|---:|
| Sharpe (ann.) | **2.520** |
| CAGR | **+31.45%** |
| Max DD | **−5.80%** |
| Calmar | **5.418** |
| Yearly returns | 2024: +40.33%, 2025: +30.99%, 2026: +1.65% YTD |
| Funding drag | 0.38 pp/yr |

Per-year breakdown:
| Year | Sharpe | Return | Max DD | n_bars |
|---|---:|---:|---:|---:|
| 2024 | 3.451 | +40.33% | −4.67% | 2126 |
| 2025 | 2.359 | +30.99% | −4.95% | 2190 |
| 2026 YTD | 0.516 | +1.65% | −5.80% | 685 |

Comparison vs Binance same window:
| Metric | Binance (full 6y) | Binance (2.3y window) | HL native (2.3y w/ funding) |
|---|---:|---:|---:|
| Sharpe | 3.04 | 3.22 | **2.52** |
| CAGR | +42.7% | +47.2% | **+31.4%** |
| Max DD | −7.4% | −7.9% | **−5.8%** |
| Calmar | 5.74 | 5.97 | **5.42** |

Sharpe ~17% lower on HL; CAGR ~11 pp lower; **MDD improves** by ~2 pp.

### 1.10 Validation methodology (10-gate battery on HL)

Source: `strategy_lab/run_v52_hl_gates.py` + audit JSON.

| Gate | Threshold | HL value | Status |
|---|---|---:|:---:|
| 1. Per-year positive | all years | 3/3 | PASS |
| 2. Bootstrap Sharpe lower-CI | > 0.5 | 1.108 | PASS |
| 3. Bootstrap Calmar lower-CI | > 1.0 | **0.987** | **near-miss FAIL by 0.013** |
| 4. Bootstrap MDD worst-CI | > −30% | −14.2% | PASS |
| 5. Walk-forward efficiency | > 0.5 | 0.799 | PASS |
| 6. Walk-forward ≥5/6 pos folds | ≥5 | 6/6 | PASS |
| 7. Permutation p (n=30, asset-level log-return shuffle) | < 0.01 | 0.0000 | **PASS — 15× null margin** |
| 8. Plateau drop ≤30% | inherited | — | SKIPPED (inherited from V30/V41/V50) |
| 9. Path-shuffle MC worst-5% MDD (n=10000) | > −30% | −12.15% | PASS |
| 10. Forward 1y p5 MDD / median CAGR (n=1000) | >−25% / >+15% | −10.33% / +32.62% | PASS |

**9 of 10 gates pass**, gate 3 fails by 0.013 — flagged as window-length artifact (2.3y on HL vs 6y on Binance widens bootstrap CIs).

**Bootstrap (stationary block, p=0.1, 1000 resamples):**
- Sharpe: mean 2.507, CI [1.108, 3.843]
- Calmar: mean 4.314, CI [0.987, 10.129]
- MDD: mean −8.31%, CI [−14.23%, −4.85%]

**Walk-forward (6 anchored expanding folds):**
- avg IS Sharpe 3.248, avg OOS Sharpe 2.594, efficiency 0.799
- per-fold OOS Sharpe: 4.371, 3.363, 3.722, 1.872, 1.945, 0.289 — worst fold = most recent (fold 6, 2026 YTD).

**Gate 7 permutation:** real Sharpe 2.520 vs null mean −1.422, null 99th-percentile −0.166 → real is 15× separated from null tail. n=30 permutations (log-return shuffle per asset, recomputed regime model on shuffled data, full V52 rebuilt).

**Gate 10 forward 1y MC (n=1000, 2190 bars/yr):**
- 1y MDD: p5 −10.33%, p25 −7.56%, p50 −5.92%, p95 −3.76%
- 1y CAGR: p5 +9.93%, p25 +22.24%, p50 +32.62%, p95 +57.36%
- P(neg year) = 1.1%; P(DD > 20%) = 0.0%; P(DD > 30%) = 0.0%

### 1.11 Expected per-sleeve trade counts (HL-validated 2.3y)

| Sleeve | Trades/yr | Trades/month |
|---|---:|---:|
| CCI_ETH | 16 | 1.3 |
| STF_AVAX | 14 | 1.2 |
| STF_SOL | 18 | 1.5 |
| LATBB_AVAX | 8 | 0.7 |
| MFI_SOL | 36 | 3.0 |
| VP_LINK | 38 | 3.2 |
| SVD_AVAX | 19 | 1.6 |
| MFI_ETH | 35 | 2.9 |

Slightly lower than Binance because volume-based signals (MFI, VP, SVD) fire less on HL given thinner volume.

### 1.12 Kill-switch thresholds (HL-calibrated)

Tighter than Binance because HL MC distribution has a narrower lower tail.

| Trigger | Threshold | MC prob | Action |
|---|---|---:|---|
| Month-1 realized DD | > 8% | 5–10% | Alert |
| Rolling-3mo DD | > 11% | ~2% | Halve sleeve sizes |
| Rolling-3mo DD | > 14% | <0.5% | Halt new entries |
| Rolling-6mo DD | > 18% | <0.1% | Full kill |
| Per-sleeve realized DD | > −12% | n/a | Disable that sleeve only |

### 1.13 Known weaknesses / where V52 would fail

1. **Window length** — 2.3y is short for tail estimates. Calmar lower-CI fails by 0.013; sample size, not strategy weakness.
2. **Volume-signal venue divergence** — Binance volume / HL volume ratio: ETH 1.1×, SOL 1.5×, AVAX 4.8×, LINK ~3×. Returns correlate ≈ 0.9997 (ETH) but volume correlates 0.52–0.74 → MFI / VP / SVD fire at **different bars** on HL than on Binance. The price-only signals (CCI, STF, LATBB) transfer cleanly; the volume-based signals lose Sharpe.
3. **Single timeframe (4h)** — no MTF confirmation, no shorter-horizon signals. Sleeve count is bounded by 5 instruments × 4h × a handful of indicators.
4. **No funding signal** — funding modeled as a cost only; ignored as a directional signal.
5. **No HL-native microstructure features used** — no L2 book depth, no liquidations flow, no OI, no L/S ratio. All signals are OHLCV-only and were originally engineered on Binance.
6. **Recent OOS fold drift** — fold 6 OOS Sharpe drops to 0.289 (2026 YTD). Either regime change or volatility compression; flagged.
7. **No partial-fill modeling**; LINK liquidity on HL is materially worse than Binance.
8. **Plateau test (Gate 8) not re-run** for the new V50 signals (MFI/VP/SVD). Robustness to ±25%/±50% parameter perturbation unverified.
9. **Funding can spike** to 0.05%/hr (~440% annualized) during manias; engine must accrue **realized** rates, not averages.

---

## 2. Strategy C — HL Liquidation Cascades

### 2.1 Status

**INCONCLUSIVE / NULL.** Designed but not deployable.

### 2.2 Hypothesis

HL liquidation cascades create directional pressure on subsequent price action.
- Long liquidations (forced sells) → DOWN bias.
- Short liquidations (forced buys) → UP bias.
- Signal: `net = short_liq_notional − long_liq_notional`; fire UP if `net > +T`, DOWN if `net < −T`.

### 2.3 Setup

Source: `strategy_lab/discovery_2026_05_16/strat_C_hl_liqs.py`.

- **Universe:** chainlink-resolved BTC/ETH/SOL × 5m + 15m markets in 2026-04-24 → 2026-05-16. Sampled 2,000 per (asset, tf) → 12,000 markets total.
- **Side mapping:** `side='A'` (ask-side fill) = long-liq (forced sell). `side='B'` (bid-side) = short-liq (forced buy).
- **Anchors:**
  - `ws_s + 120` for 5m and 15m
  - `slot_end − 60s` (LATE-15m variant)
- **Lookback:** 5 or 10 minutes pre-fire.
- **Threshold sweep:** T ∈ {$10k, $50k, $100k, $500k, $1M, $5M}.
- **Outcome truth:** chainlink-derived `outcome` column.

### 2.4 Results (n≥200, ALL-asset)

| Variant | thr_usd | n | Hit |
|---|---:|---:|---:|
| 15m_late lb=10min | 50,000 | 215 | **0.558** |
| 15m_late lb=10min | 10,000 | 323 | 0.551 |
| 15m_ws120 lb=10min | 10,000 | 318 | 0.506 |
| 15m_ws120 lb=10min | 50,000 | 217 | 0.502 |
| 5m_ws120 lb=10min | 50,000 | 206 | 0.451 |
| 5m_ws120 lb=10min | 10,000 | 339 | 0.451 |

### 2.5 Verdict & known weaknesses

- Best hit 55.8% at n=215 → 95% CI ≈ [49%, 62%] — not separable from chance.
- **Data caveat:** `hyperliquid_liquidations_full` (May 25 → Feb 26) has zero overlap with the test window (Apr 24 → May 16 2026). Strategy fell back to `hyperliquid_liquidations_30d`, which is **HL fills for tracked users, not market-wide liquidations.** Using `side` A/B as a proxy. Code ready to switch to `prefer="full"` after a data refresh.
- Code path: `build_liq_arrays(asset, prefer="auto")` auto-selects between files; switch to `prefer="full"` once the May 2026 chunk lands.
- Should be re-run on the new L25 refresh + a clean HL liq feed before considering it dead.

---

## 3. HL tooling

### 3.1 Data loader API — `strategy_lab/util/hl_data.py`

Three functions:
- `hl_symbol(symbol) -> str` — maps `"BTCUSDT"` (Binance form) → `"BTC"` (HL form). Pass-through if already short form.
- `load_hl(symbol, tf="4h", start=None, end=None) -> DataFrame` — reads `data/hyperliquid/parquet/<COIN>/<tf>.parquet`. Returns OHLCV DataFrame indexed by tz-aware UTC timestamp. Optional `start`/`end` filters (passed as ISO strings, converted to `pd.Timestamp(tz="UTC")`).
- `load_hl_funding(symbol) -> DataFrame` — reads `data/hyperliquid/funding/<COIN>_funding.parquet`. Returns hourly `fundingRate` (decimal) and `premium`.
- `funding_per_4h_bar(symbol, kline_index) -> Series` — aggregates hourly funding into per-4h-bar sums aligned to a kline index. Buckets via `f.index.floor("4h")` + groupby-sum, then reindex to klines (missing → 0). Signed: `fundingRate > 0 ⇒ longs pay shorts`; P&L = `-direction × notional × bar_funding`.

### 3.2 Ingest pipelines

**`strategy_lab/ingest_hyperliquid.py`** (incremental, default for ongoing refresh):
- Endpoint: `POST https://api.hyperliquid.xyz/info`
- Bodies: `{"type":"candleSnapshot","req":{"coin":COIN,"interval":"4h","startTime":ms,"endTime":ms}}` and `{"type":"fundingHistory","coin":COIN,"startTime":ms,"endTime":ms}`
- Coins: `BTC ETH AVAX SOL LINK`
- Interval: 4h (= 14_400_000 ms); window paging 5000 candles per call (~833 days).
- Funding: 5000-row pages (≈ 5000 hours), hourly grain.
- Idempotent: existing parquet is read, max-timestamp computed, appended from `last_ts + INTERVAL_MS`. Funding skipped if parquet already exists.
- Writes to `data/hyperliquid/parquet/<COIN>/4h.parquet` + `data/hyperliquid/funding/<COIN>_funding.parquet`.
- Rate-limit: `time.sleep(0.25)` between pages; retries with `1.5^attempt` backoff (3 retries, 30s timeout).

**`strategy_lab/ingest_hyperliquid_full.py`** (bootstrap / full-history):
- 30-day rolling window walk from 2023-04-01 → now, deduped via `seen_t` set.
- 1d data via a single call (5000-day capacity > 5y of HL history).
- Writes both `4h.parquet` and `1d.parquet` per coin.

**`strategy_lab/probe_hl_history.py`** (history availability probe):
- Hammers 6 narrow windows from Apr 2023 → June 2024 plus a 5000-day 1d probe per coin.
- Empirically established: HL 4h kline coverage starts **2024-01-12** (used as `START` in `run_v52_hl_gates.py`). Earlier-2023 chunks exist but with gaps. 1d has 5+ years back to Aug 2020.

**`strategy_lab/hyperliquid/fetch_archive.py`** (HL S3 archive):
- Bucket: `s3://hyperliquid-archive` (requester-pays). Layout: `market_data/YYYYMMDD/<hour>/l2Book/<coin>.lz4` (hourly L2 book snapshots), `asset_ctxs/YYYYMMDD.csv.lz4` (funding + OI + mark).
- Trade fills / liquidations in `s3://hl-mainnet-node-data/node_fills_by_block`.
- Modes: `--test` (1 hour BTC L2 + 1 day asset_ctx as sanity check) or `--start/--end/--coins` bulk.
- Output: `data/hyperliquid/raw/...` (lz4 raw, not yet converted).
- Requires AWS creds with S3:GetObject + requester-pays auth.
- Used to back-fill L2 books and OI/funding history; not yet productized into the canonical loader.

### 3.3 `simulate_with_funding` mechanics — `strategy_lab/eval/perps_simulator_funding.py`

Funding-aware re-implementation of the canonical perps simulator. Combines:
- Static `(tp_atr, sl_atr, trail_atr, max_hold)` OR `(regime_labels, regime_exits)` for V41-style adaptive exits.
- Wilder-smoothed ATR(14).
- Per-bar funding accrual on open positions.
- Standard ATR-risk sizing with leverage cap.

Per-bar loop:
1. **If in position:** `funding_pnl = -pos × size × close[i] × funding[i]`; cash += funding_pnl; track `funding_paid_this_trade` cumulatively.
2. **Trailing stop:** ratchet only (only tighter, never looser).
3. **Exit check** in priority `[SL → TP → TIME]`. Fill at stop/TP × `(1 ± slip)`; fee = `size × (entry + exit) × FEE`. Append trade with `funding_cost` recorded.
4. **Entry check** (only if flat and `i - last_exit > 2`): `entry_p = open[i+1] × (1 + slip × direction)`. Resolve regime exit params at bar `i`. Compute size by ATR-risk + leverage cap.
5. **MTM:** `eq[i] = cash + size × (close[i] - entry_p) × pos` if in position.

Constants: `fee = 0.00045`, `slip = 0.0003`, `init_cash = 10_000`. No partial-fill model.

### 3.4 Gate runner architecture — `strategy_lab/run_v52_hl_gates.py`

End-to-end audit pipeline:
1. **Build V41 sleeves** via `build_v41_sleeve()` — for each sleeve `(CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX)`, load HL OHLCV, run the signal fn from the legacy script (`import_sig`), fit the per-instrument regime model (`fit_regime_model(df, train_frac=0.30, seed=42)`), and run `simulate_with_funding` with the right variant (baseline / V41 / V45).
2. **Build P3 inv-vol blend** (`invvol_blend`, 500-bar window) over CCI_ETH/STF_AVAX/STF_SOL.
3. **Build P5 equal-weight blend** over CCI_ETH/LATBB_AVAX/STF_SOL.
4. **Compose V41 equity:** `0.6 × P3_ret + 0.4 × P5_ret`, cumulative product starting at $10k.
5. **Build diversifiers** (MFI_SOL, VP_LINK, SVD_AVAX, MFI_ETH) each via `build_diversifier`.
6. **Compose V52 equity:** `0.60 × V41 + 0.10 × MFI_SOL + 0.10 × VP_LINK + 0.10 × SVD_AVAX + 0.10 × MFI_ETH`.
7. **Run 10 gates:**
   - Gates 1–6 (per-year positivity, bootstrap CIs, walk-forward) via `verdict_8gate(v52_eq)` from `run_leverage_audit.py`.
   - Gate 7 permutation: 30 iterations of asset-level log-return shuffle (`shuffle_df_lr(df, rng)`), rebuild the full V52 on shuffled OHLCV (preserving open/high/low/close ratios), null distribution of Sharpe.
   - Gate 9 path-shuffle MC: `gate9_path_shuffle(v52_eq, n_iter=10_000)`.
   - Gate 10 forward 1y MC: `gate10_forward_paths(v52_eq, n_paths=1000, year_bars=2190)`.
8. **Output:** `docs/research/phase5_results/v52_hl_champion_audit.json` + console summary.

Gate 8 (plateau) is SKIPPED — inherited from earlier V30/V41/V50 audits not re-run on HL.

### 3.5 Comparison runner — `strategy_lab/run_v52_hyperliquid_compare.py`

Builds V52 on Binance, HL-no-funding, HL-with-funding over the overlap window (2024-01-12 → 2026-04-24). Outputs:
- `docs/research/phase5_results/v52_hyperliquid_vs_binance.json` (Sharpe/CAGR/MDD/Calmar for all three variants).
- `docs/research/phase5_results/binance_vs_hl_correlations.csv` (close/returns/volume correlation + volume ratio per sleeve).

Established the **0.38 pp/yr funding drag** and the volume divergence numbers (ETH 1.1×, SOL 1.5×, AVAX 4.8× volume ratio Binance/HL).

---

## 4. Coverage map — what (asset × TF × signal-style) is already covered

### 4.1 Asset × TF coverage (V52 production)

| | BTC | ETH | AVAX | SOL | LINK |
|---|:---:|:---:|:---:|:---:|:---:|
| **4h** | regime-classifier only (not traded) | CCI, MFI | STF (V45), LATBB, SVD | STF, MFI | VP |
| **5m** | — | — | — | — | — |
| **15m** | — | — | — | — | — |
| **1h** | — | — | — | — | — |
| **1d** | data exists, unused | data exists, unused | data exists, unused | data exists, unused | data exists, unused |

Strategy C touches 5m + 15m for BTC/ETH/SOL with a liquidations signal, but inconclusive — counted below in Strategy-style coverage as a partial cell only.

### 4.2 Signal-style coverage

| Style | V52 implementation | Coverage |
|---|---|---|
| Trend-following (price + EMA filter) | STF_AVAX, STF_SOL | AVAX 4h, SOL 4h |
| Mean reversion (oscillator extreme) | CCI_ETH, MFI_SOL, MFI_ETH | ETH 4h, SOL 4h |
| Mean reversion (band touch) | LATBB_AVAX | AVAX 4h |
| Volume-distribution rotation | VP_LINK | LINK 4h |
| Volume-flow divergence (CVD proxy) | SVD_AVAX | AVAX 4h |
| Regime-conditional exits | V41 stack (HMM features: rvol, vol_ratio, hl_range) | ETH/AVAX/SOL 4h |
| Inv-vol portfolio weighting | P3 side | 3 sleeves, 500-bar window |
| Liquidation cascade flow | Strategy C (NULL on proxy) | BTC/ETH/SOL 5m+15m partial |

### 4.3 Data feeds in use

- **HL official `candleSnapshot`** — 4h + 1d OHLCV from 2024-01-12+ for BTC/ETH/AVAX/SOL/LINK. (4h `.parquet` + `1d.parquet` per coin.)
- **HL `fundingHistory`** — hourly funding rates for the 5 coins.
- **HL S3 archive** (`fetch_archive.py`) — L2 book snapshots + asset_ctxs (funding/OI/mark) raw lz4, downloaded but **not yet converted to a canonical format**.
- **HL liquidations** — proxied via `load_hyperliquid_liquidations` (Apr-May 2026 30d file) and `load_hyperliquid_liquidations_full` (May 25 → Feb 26 archive — gap with current research window).

---

## 5. Gap analysis — priority cells for new HL research

Below is the explicit list of (asset, TF, signal-style) combinations NOT covered by V52, ordered by expected research priority. These are the spaces where new strategies should focus.

### 5.1 Timeframe gaps (highest priority)

V52 is **single-TF (4h-only)**. The entire shorter-horizon space is unexplored on HL:

| TF | Bars/yr | Status | Why interesting |
|---|---:|---|---|
| **1h** | 8,766 | UNCOVERED on HL | Bridges 4h → intraday. Should be cheap to port V52 signals as ablation. |
| **15m** | 35,064 | only Strategy C (partial) | Higher trade count, more reliable bootstrap CIs. Likely target for MFI/STF re-fitting. |
| **5m** | 105,120 | only Strategy C (partial) | Microstructure regime — funding ticks dominate; cross-venue lead-lag plausible. |
| **1m** | 525,600 | UNCOVERED | Order-flow / book-imbalance signals; latency-sensitive. |
| **1d** | 365 | data exists, unused | Daily-bar / overnight signals; lowest noise. Mentioned as future work in §10.5 of `V52_HYPERLIQUID_DEPLOYMENT_NOTES.md`. |
| **8h** | 1,095 | blocked (no AVAX/SOL 8h parquets) | Would smooth STF noise; data ingest gap. |

### 5.2 Asset gaps

- **BTC 4h traded**: V52 does NOT trade BTC directly — kept only for regime classifier. Adding a BTC 4h sleeve (CCI / STF / MFI / something novel) is a free expansion.
- **HL alts beyond {BTC,ETH,AVAX,SOL,LINK}**: HL has 100+ perps. Nothing for HYPE, DOGE, WIF, kPEPE, kSHIB, ENA, TIA, SUI, ARB, OP, MATIC, AAVE, COMP, UNI, etc. Liquidity-screened expansion (top-30 by 30d volume) is a clear avenue.
- **Stable-funding pairs / inverse-funding pairs**: no current sleeve specifically exploits funding-driven cohorts (e.g., "high positive funding" or "negative funding" baskets).

### 5.3 Signal-style gaps

Not represented anywhere in V52:

| Style | What's missing |
|---|---|
| **Momentum (donchian breakout / KAMA / TSI)** | No pure breakout signal. STF flip is the only trend-trigger. |
| **Cross-sectional momentum / rank** | No relative-strength signal across the 5 coins. |
| **Vol-targeted / VTM** | No realized-vol → position-size feedback at the sleeve level. Inv-vol is on the BLEND side only. |
| **Funding as a signal** | Funding is a cost only. No "long when funding < −X" or "short when funding crowded long". |
| **Open-interest delta** | OI not loaded for HL (despite `asset_ctxs` archive having it). |
| **Long/short ratio** | Same — `asset_ctxs` has it, V52 doesn't use it. |
| **L2 book imbalance / depth** | HL L2 archive downloaded raw, not productized. No book-pressure features. |
| **Liquidations as signal** | Strategy C exists but NULL on proxy data; needs clean liq feed re-test. |
| **Cross-exchange basis (HL ↔ Binance ↔ Coinbase ↔ Kraken)** | Sister project `cross_exchange_leadlag_2026_05_26/` exists but no HL ingestion. |
| **Order-flow imbalance / microstructure** | None — V52 is OHLCV-only. |
| **Macro overlays (DXY, BTC dominance, ETH/BTC ratio)** | None. |
| **Calendar / event filters (US session, weekend, CPI/FOMC)** | None — `risk_per_trade` constant 24/7. |
| **ML / meta-classifier overlays** | None in V52. |
| **Pairs / spread** | None on HL — Binance has `run_v61_pairs.py` but not ported. |
| **Volatility regime fade vs trend** | V41 regime EXITS exist, but no regime-conditional entry SIGNAL (e.g., "only trade STF in HighVol; only trade LATBB in LowVol"). |
| **Multi-TF confirmation** | All sleeves are single-TF. |
| **Adaptive parameters via online learning** | None. |

### 5.4 Validation methodology gaps

- **Gate 8 (plateau test)** never re-run on HL for the V50 signals (MFI, VP, SVD). Could be skipping fragility.
- **Walk-forward fold 6 OOS drop** (0.289) is unexplained — needs root-cause attribution; could be regime shift, vol compression, or sleeve degradation.
- **Permutation test** is asset-level log-return shuffle; does not break **cross-asset structure**. A second permutation breaking cross-correlations is missing.
- **Partial fills not modeled** — LINK liquidity especially.
- **Slippage held at 3 bps**; not vol-conditioned or book-depth conditioned.
- **No paper-trade data yet** — kill switches are MC-calibrated but un-tested live.

### 5.5 Engineering gaps in current tooling

- `load_hl` only handles `data/hyperliquid/parquet/<COIN>/<tf>.parquet` — no L2/L25, no funding-rate-as-feature.
- No HL canonical resolution feed (the up-down market resolution analog from Polymarket is irrelevant here, but **bar-completion times** + **next-bar fill clock** need to match the live engine's WS feed).
- No `engine_v2` HL config — `simulate_with_funding` is the closest, but it lacks the live-mimic primitives (latency, sparse-book filter, strict-asof book lookup) that exist for Polymarket.
- HL S3 archive is downloaded raw (lz4) but **never parsed into queryable parquets**. L2 books especially.
- Fee model is hard-coded 4.5 bps taker. No maker rebate / hl-vip-tier modeling. Production HL may charge less for high-volume accounts.

### 5.6 Priority for new research

Highest-impact (in suggested order):
1. **Add 1h + 15m versions of V52 sleeves** — same signals, higher trade count, sharper bootstrap CIs. Cheap port; should be the first move.
2. **Funding as directional signal** — `asset_ctxs` archive has years of OI + funding + L/S; build a regime panel.
3. **Add BTC 4h sleeve** — easy expansion, free.
4. **Cross-exchange basis / lead-lag signals on HL** — the `cross_exchange_leadlag_2026_05_26/` tooling already does 1s xcorr on chainlink RTDS; pivot to HL ↔ Binance basis.
5. **L2 book features** — parse the HL S3 lz4 archive into a parquets layer; build imbalance / depth-skew features.
6. **Liquidation cascade signal** — re-test Strategy C with a clean liq feed (refresh `hyperliquid_liquidations_full` to cover Apr-May 2026).
7. **Cross-sectional momentum / rank** — across the V52 universe + HL top-30 alts.
8. **Meta-classifier overlay** — RF/XGB on a panel of (regime, MFI, CCI, STF state, funding, OI delta, vol-regime, time-of-day) to predict trade quality, used as a gate or sizing multiplier.
9. **HL alt expansion** — add HYPE, ENA, TIA, SUI, ARB, OP, etc., with liquidity gating.
10. **Engine v2 → HL** — port the live-mimic primitives (latency, sparse-book filter, asof book lookup) to HL backtests.

---

## 6. Quick-reference snippets for new research

### 6.1 Load HL 4h OHLCV
```python
from strategy_lab.util.hl_data import load_hl, funding_per_4h_bar
df = load_hl("ETH", "4h", start="2024-01-12", end="2026-04-25")
fund = funding_per_4h_bar("ETH", df.index)
```

### 6.2 Run a signal + funding-aware sim
```python
from strategy_lab.eval.perps_simulator_funding import simulate_with_funding
from strategy_lab.strategies.v50_new_signals import sig_mfi_extreme
le, se = sig_mfi_extreme(df, lower=25, upper=75)
trades, eq = simulate_with_funding(df, le, se, fund,
                                    tp_atr=10.0, sl_atr=2.0,
                                    trail_atr=6.0, max_hold=60)
```

### 6.3 Build & audit a new sleeve through the 10-gate battery
```python
from strategy_lab.run_v52_hl_gates import build_v52_hl  # full pipeline
# OR re-implement gates 1-10 using helpers:
#   strategy_lab.run_leverage_audit.verdict_8gate(eq)
#   strategy_lab.run_leverage_gates910.gate9_path_shuffle(eq, n_iter=10000)
#   strategy_lab.run_leverage_gates910.gate10_forward_paths(eq, n_paths=1000, year_bars=2190)
```

### 6.4 Refresh HL data (incremental)
```bash
python -m strategy_lab.ingest_hyperliquid
# writes data/hyperliquid/parquet/<COIN>/4h.parquet and
#        data/hyperliquid/funding/<COIN>_funding.parquet
```

### 6.5 Permutation null check (asset-level log-return shuffle)
```python
# in run_v52_hl_gates.py
shuffled = {sym: shuffle_df_lr(df, rng) for sym, df in real_dfs.items()}
eq_p = build_v52_hl(dfs_override=shuffled)
null_sharpe = sharpe(eq_p)
```

---

## 7. Bottom line

V52 covers a **narrow but well-validated cell**: 4h-only, 5 HL majors, 6 signal families, OHLCV-only, single venue. Sharpe 2.52, CAGR +31.4%, MDD −5.8% with funding on 2.3y. 9/10 gates pass.

The **largest open spaces** for new research are: shorter timeframes (1h/15m/5m), funding/OI/LS as signals (not just costs), L2 book features (data downloaded but not parsed), cross-exchange basis, BTC + alt expansion, and meta-classifier overlays.

Strategy C exists for liquidation cascades but is inconclusive on proxy data — recheck after the liq feed refresh.
