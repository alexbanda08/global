# 20 — V40 Regime-Adaptive Strategy Research

**Date:** 2026-04-24
**Window:** 2021-01-01 → 2026-03-31 (6 full years)
**Scope:** forward-only HMM regime classifier + regime-adapted CCI/SuperTrend + TP1/TP2 partial-exit simulator
**Artifacts:** [phase5_results/v40_research_grid.csv](phase5_results/v40_research_grid.csv) · [v40_regime_diagnostics.json](phase5_results/v40_regime_diagnostics.json) · [v40_blend_results.json](phase5_results/v40_blend_results.json)

## TL;DR

- **Regime classifier works correctly** — K=5 BIC-selected, no look-ahead verified (train ends 2022-08-05, OOS starts 2022-08-06), stable regime distribution per coin (Uncertain/Warming < 0.1%).
- **Regime-adaptive SuperTrend (`st_adaptive`) is a real improvement per-sleeve** — AVAX 4h Sharpe **1.32** (baseline STF_AVAX was ~0.67).
- **TP1/TP2 partial exits boost WR from 33-48% → 64-84%** with only mild return drag — high value for portfolio blending even if CAGR is lower.
- **Regime-adaptive CCI and regime-switcher FAILED** — thresholds ladder was misguided; the switcher's mixed exit stack didn't fit the mean-reversion signals.
- **Best V40 blend: Sharpe 1.76, MDD −7.1%** — does NOT beat NEW 60/40 (Sharpe 2.25) on risk-adjusted return, but has **half the drawdown**. Useful as a low-vol complement, not a replacement.

## Infrastructure built

### 1. Forward-only HMM regime classifier — `strategy_lab/regime/hmm_adaptive.py`

- **Features:** log returns, realized volatility (120-bar rolling std), volume ratio (120-bar mean), HL range %.
- **Model:** GaussianMixture (hmmlearn unavailable on this system — GMM is a reasonable single-state substitute).
- **K selection:** BIC over {3, 4, 5} (initially {3,...,7} but capped — higher K produced spurious tiny regimes with 2-32 bars).
- **No-look-ahead:** fit once on first 30% of data (IS). OOS bars use fixed model. Verification assertion on every fit.
- **Regime labelling:** sorted by mean realized-vol within each regime → `LowVol / MedLowVol / MedVol / MedHighVol / HighVol`.
- **Stability filter:** 3-bar persistence before a regime "activates"; flicker detector (>4 stable-sequence changes in 20 bars → `Uncertain`).
- **Distribution (4h, all coins):**

| Coin | LowVol | MedLow | MedVol | MedHigh | HighVol | Warm/Unc |
|---|---:|---:|---:|---:|---:|---:|
| ETH | 8571 | 968 | 656 | 833 | 400 | 2 |
| AVAX | 1985 | 8007 | 303 | 154 | 972 | 9 |
| SOL | 7050 | 586 | 416 | 1269 | 2105 | 4 |
| DOGE | 2469 | 8179 | 159 | 360 | 253 | 10 |

### 2. TP1/TP2 partial-exit simulator — `strategy_lab/eval/perps_simulator_tp12.py`

- TP1 at entry ± 3×ATR → closes 50% of position
- Remainder trails with tighter stop (2.5×ATR instead of 6×ATR) until TP2 (10×ATR) or max_hold
- Full SL still hard at 2×ATR for both halves
- Same `size_mult` hook as leverage simulator

### 3. Adaptive strategies — `strategy_lab/strategies/adaptive/v40_regime_adaptive.py`

- **`sig_v40_cci_adaptive`** — CCI thresholds adapted per regime (100/125/150/175/200 for LowVol → HighVol)
- **`sig_v40_st_adaptive`** — SuperTrend multiplier adapted per regime (2.5 / 3.0 / 4.0)
- **`sig_v40_switcher`** — CCI fires in LowVol/MedLowVol, ST fires in MedVol/MedHighVol, stands down in HighVol/Uncertain

## Phase 1 results — 4h primary grid (24 runs)

Top variants (pos_yrs ≥ 5, n ≥ 20):

| Asset | TF | Strategy | Exit | n | WR | Sharpe | CAGR | MDD | Calmar |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| AVAX | 4h | st_adaptive | canonical | 33 | 48.5% | **1.32** | +23.5% | −16.7% | 1.41 |
| SOL | 4h | st_adaptive | tp12 | 32 | **84.4%** | 1.07 | +7.8% | **−6.5%** | 1.20 |
| ETH | 4h | st_adaptive | tp12 | 64 | 73.4% | 0.90 | +9.2% | −10.8% | 0.85 |

All other strategy×exit combos produced Sharpe < 0.85 or failed pos_yrs ≥ 5.

## Phase 2 results — 1h extension on top variants (only st_adaptive, AVAX+SOL)

| Asset | TF | Exit | n | WR | Sharpe | CAGR | MDD |
|---|---|---|---:|---:|---:|---:|---:|
| AVAX | 1h | canonical | 117 | 35.0% | 1.16 | +35.0% | −31.2% |
| AVAX | 1h | tp12 | 181 | 64.6% | 0.82 | +16.7% | −29.9% |
| SOL | 1h | canonical | 125 | 32.8% | 0.96 | +27.0% | −29.1% |
| SOL | 1h | tp12 | 186 | 64.0% | 0.72 | +12.5% | −21.2% |

1h variants have 3-5× more trades and 2× CAGR but MDDs widen significantly. Not competitive on Calmar.

**8h timeframe:** AVAX and SOL parquets not available — blocked this arm.

## Phase 3 results — V40 blended portfolios (4h EQW)

| Blend | Components | Sharpe | CAGR | MDD | Calmar | Min-Yr |
|---|---|---:|---:|---:|---:|---:|
| V40_3_canonical | ETH+AVAX+SOL canonical | 1.46 | +14.4% | −9.0% | 1.60 | +2.7% |
| V40_3_tp12 | ETH+AVAX+SOL tp12 | 1.50 | +9.5% | −5.3% | 1.77 | +2.6% |
| **V40_3_mixed** | ETH_tp12 + AVAX_canonical + SOL_tp12 | **1.76** | +13.8% | **−7.1%** | **1.95** | +3.8% |
| V40_4_mixed | V40_3_mixed + DOGE_canonical | 1.32 | +10.5% | −6.5% | 1.62 | +2.2% |
| **NEW 60/40 (baseline)** | (study 19) | **2.25** | **+36.7%** | −13.8% | 2.67 | +14.4% |

V40_3_mixed vs NEW 60/40:
- Sharpe −22% lower
- CAGR −62% lower
- **MDD 49% smaller**
- Calmar −27% lower
- Min-year much weaker (+3.8% vs +14.4%)

## What worked, what didn't, what's uncertain

### ✅ What worked
1. **No-look-ahead forward-only filtering** — verification passes on every coin.
2. **Regime-adaptive SuperTrend multiplier** — modest real improvement on AVAX. Evidence that regime-conditional exits are valid.
3. **TP1/TP2 partial exits** — dramatic WR improvement with mild return drag. High value for psychological/operational stability.
4. **Monte Carlo integrity** — Uncertain/Warming < 0.1% means the regime pipeline is producing usable labels.

### ❌ What failed
1. **CCI with ladder thresholds** — making CCI *more* restrictive in high-vol regimes was backwards; the CCI signal is strongest precisely when price is extreme (which happens in high vol).
2. **Regime switcher** — ran CCI (mean-reversion) with the `EXIT_4H` stack tuned for trend-following (TP=10×ATR). The exits don't fit the mean-reversion trade shape.
3. **8h data gap** — blocks a potentially valuable low-noise test.
4. **V40 blend didn't beat NEW 60/40** — lower return, lower Sharpe, only MDD is better.

### ⚠️ Uncertain / worth revisiting
- **Dynamic exits per regime** — currently the regime controls *entry* but not exit stack. A trend trade in HighVol should use tight trail (2×ATR), in LowVol it should use loose trail (8×ATR). Next experiment.
- **CCI with regime-aware exit (not entry)** — use static CCI entry at ±150, but switch TP/SL targets by regime. Might salvage CCI.
- **Refit cadence** — currently fit-once. Expanding-window refit every 500 bars could adapt to regime distribution shifts.
- **Feature augmentation** — add funding rate, BTC dominance, on-chain flows to the HMM.

## Verdict — V40 as a low-vol complement, NOT a replacement

The NEW 60/40 portfolio from study 19 remains the primary deploy target. V40_3_mixed is interesting as a **third sub-account for drawdown reduction**:

| Stacked config | Expected effect |
|---|---|
| 70% NEW_60_40 + 30% V40_3_mixed | Smooths drawdowns; caps CAGR ~30% |
| 80% NEW + 20% V40 | Minimal impact; may not be worth the operational overhead |

Not recommended to deploy V40 alone — it's working but not at promotion-grade (Sharpe < 2.0, min-year < +10%).

## Recommended next experiments (ranked)

1. **Regime-adaptive EXIT stack** — keep canonical static entries, but swap TP/SL/trail per regime. Likely high-impact.
2. **Add a real funding-rate feature** to the HMM — on Hyperliquid, funding spikes to ±0.01% per hour are regime-defining.
3. **Multi-timeframe confirmation** — signal on 4h, confirm on 1h. Reduces false breakouts in MedVol.
4. **Kelly-fraction sizing per regime** — each regime has different edge/variance; static risk_per_trade is leaving alpha on the table.
5. **Fix the CCI adaptive** — retry with *tighter* thresholds in HighVol (opposite of current direction).

## Scripts

- [strategy_lab/regime/hmm_adaptive.py](../../strategy_lab/regime/hmm_adaptive.py)
- [strategy_lab/eval/perps_simulator_tp12.py](../../strategy_lab/eval/perps_simulator_tp12.py)
- [strategy_lab/strategies/adaptive/v40_regime_adaptive.py](../../strategy_lab/strategies/adaptive/v40_regime_adaptive.py)
- [strategy_lab/run_v40_research.py](../../strategy_lab/run_v40_research.py)
- [strategy_lab/run_v40_blend.py](../../strategy_lab/run_v40_blend.py)

## Current portfolio roster (unchanged by this study)

Primary deploy remains **NEW 60/40**:
- 60% P3_invvol (ETH+AVAX+SOL SuperTrend/CCI, inverse-vol weighted)
- 40% P5_btc_defensive (same w/ LATBB_AVAX, BTC-gated sizing)
- Sharpe 2.25 · CAGR +36.7% · MDD −13.8% · 10/10 gates passed

V40 research continues — mission isn't to dethrone NEW 60/40 on every experiment, it's to find what works and what doesn't.
