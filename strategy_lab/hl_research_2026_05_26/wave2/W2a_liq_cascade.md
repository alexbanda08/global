# W2a — HL Liquidation Cascades as Directional Signal (Hypothesis N1)

**Date:** 2026-05-26
**Engine:** `strategy_lab/hl_research_2026_05_26/hl_engine.py` (HyperliquidConfig — taker 4.5bps, slip 3bps, hourly funding)
**Notional / lev:** $250 / 1x
**Output CSV:** [`W2a_results.csv`](W2a_results.csv) (115 cells)
**Verdict:** **NO DEPLOY CANDIDATE.** Hypothesis N1 cannot be validated on the requested majors with the canonical dataset.

---

## TL;DR

- **0 of 115 cells pass all 4 gates (G1+G2+G3+G4).**
- Best cell is `ETH_1m_cascade_60m_reversion_filt_markov_contra`: n=13, WR=85%, $/tr=+$10.21, Sharpe 15.3, p=0.022, perm_p=0.03. Passes G1+G2+G4 but **fails G3** (`wf_pos_frac=0`).
- Strong directional bias: liquidation reversion (trade against the liquidating side) is dominant for *every* asset and horizon, but only because **all signal-events cluster in a single Oct 10, 2025 deleveraging window** (BTC: 89% of LONG-liq events in 1 hour; SOL/ETH similar).
- **Data gap is the root cause**: HL canonical liquidation data on majors is concentrated in Oct-Nov 2025; HL klines start only Jan 30 2026. The single overlap point with non-trivial liq density requires using Binance vision klines as a price proxy (corr 0.9996 vs HL per audit).

---

## 1. Data inventory and constraints

### 1.1 What we have

| Source | Time range | Notes |
|---|---|---|
| `hyperliquid_liquidations_full.parquet` | 2025-05-30 → 2026-05-12 | 62k strict-liq events (post `Liquidated|Deleveraging|Borrow Liquidation` filter) |
| `hyperliquid_liquidations_30d.parquet` | 2026-04-16 → 2026-05-16 | Only 107 strict events; **zero on BTC/ETH/SOL/HYPE** in this window |
| `hyperliquid_klines.parquet` (1HRS) | 2026-01-30 → 2026-05-16 | BTC/ETH/SOL/HYPE |
| `binance_vision_klines.parquet` (1MIN) | 2025-04-27 → 2026-04-28 | BTC/ETH/SOL only; used as backbone proxy |
| `hyperliquid_funding.parquet` | 2026-01-30 → 2026-05-15 | Empty pre-Jan 30; engine skips funding accrual gracefully |

### 1.2 Major-coin liq counts by month (real liquidations only)

| Coin | 2025-06 | 2025-08 | 2025-09 | **2025-10** | 2025-11 | 2025-12 | 2026-01 | 2026-02 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 4 | 20 | 10 | **1,699** | 226 | – | 2 | 1 |
| ETH | 122 | 196 | 379 | **1,406** | 7 | – | 94 | – |
| SOL | 2 | 3 | 38 | **1,645** | 75 | – | 6 | 1 |
| HYPE | – | 84 | 5 | **2,262** | 45 | 1 | – | – |

**89% of major-asset liq events fall in Oct 2025.** Further drilling: 89% of BTC LONG liqs >=$100k (217 of 247) fire in a single hour — 2025-10-10 21:00 UTC.

### 1.3 Why HYPE is excluded

HYPE has zero overlap between its liq window (ends 2025-12-18) and HL klines (start 2026-01-30). HYPE is not on Binance spot, so no backbone substitute exists.

### 1.4 Backbone choice

Engine constructs HL fills/fees/funding, but uses **Binance vision spot 1MIN klines** for the price proxy during the Oct-Nov 2025 liquidation window. Audit confirms 0.9996 returns-corr to HL during overlap; this matches the existing `hl_panel_*` feature panels which use the same backbone.

---

## 2. Methodology

### 2.1 Signal builders

**Sub-test 1 — Threshold × horizon grid** (`build_signals_threshold`):
- Filter liqs by (coin, side, notional ≥ threshold)
- **Dedup**: keep only first event per 5-min window (critical fix — see §3.1)
- For each kept event, fire at `time_exchange_us`, exit `+hold_min`
- Direction: `continuation` = trade WITH the liq pressure (long-liq → SHORT); `reversion` = trade AGAINST (long-liq → LONG)

**Sub-test 2 — Cascade detection** (`detect_cascades`):
- Slide 60s window over all liqs per asset; fire when ≥5 liqs OR cum ≥$5M in window
- 60s cooldown between fires
- `dominant_side` = majority of LONG vs SHORT liq counts in window

**Sub-test 3 — Filtered variants**:
- Pick top 3 cells per asset by raw Sharpe
- Apply 3 filters using `hl_panel_{asset}_15m.parquet`:
  - `regime_label == "ranging"` — chop-regime hypothesis
  - `tr_in_london | tr_in_ny` — institutional sessions only
  - `markov_state_fixed` aligned to expected direction

### 2.2 Validation gates

- **G1**: binomial p < 0.05 vs 50% null (two-sided)
- **G2**: `total_pnl_usd > 0` after HL fees (4.5bps × 2) + 3bps slip + hourly funding
- **G3**: walk-forward 4-split — require ≥50% of splits have positive mean PnL
- **G4**: permutation test, n=100 jitter shuffles within ±60s noise — require empirical mean > 95th pct of null
- **G5**: per-asset Sharpe consistency (not separately gated; implicit in cross-asset comparison)

### 2.3 Engine config

`HyperliquidConfig()` defaults: taker 4.5 bps both sides, slip 3 bps entry, 50ms latency, hourly funding accrual capped at 1.25 bps/hr.

---

## 3. Results

### 3.1 Critical fix: event-clustering deduplication

**Initial run (no dedup)** produced 42 cells passing all 4 gates with WR up to 100% and Sharpe up to +39 — but inspection showed these were illusions:
- BTC `liq_long_100k_60m_reversion` "n=247" was 217 events firing in the SAME 53-minute interval (2025-10-10 21:13 → 22:06 UTC)
- Walk-forward "passed" because all 4 splits fell within that single hour
- Permutation "passed" because ±60s jitter still landed in the same rally hour

With 5-minute dedup applied, BTC LONG ≥$100k drops from 247 to 8 unique fires. The dedup-corrected results are reported here.

### 3.2 Gate-pass distribution (115 cells)

| Gates passed | Count |
|---|---:|
| G1+G2+G4 | 2 |
| G1+G2 | 7 |
| G2 only | 47 |
| G1 only | 9 |
| NONE | 50 |
| **All 4 gates** | **0** |

### 3.3 Top 10 cells (ranked by Sharpe among G2-passing)

| Rank | Strategy | Asset | Sub-test | n | WR | $/tr | Sharpe | p | perm_p | wf_pos_frac | Gates |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `liq_long_1000k_60m_reversion` | SOL | threshold | 5 | 100% | +$5.64 | 43.2 | 0.063 | n/a | 0.00 | G2 |
| 2 | `liq_long_1000k_30m_reversion` | SOL | threshold | 5 | 100% | +$7.73 | 30.9 | 0.063 | n/a | 0.00 | G2 |
| 3 | `liq_long_500k_30m_reversion` | SOL | threshold | 6 | 100% | +$9.40 | 28.6 | 0.031 | 0.44 | 0.00 | G1,G2 |
| 4 | `liq_long_500k_60m_reversion` | SOL | threshold | 6 | 100% | +$7.37 | 27.2 | 0.031 | 0.40 | 0.00 | G1,G2 |
| 5 | `liq_long_100k_60m_reversion` | BTC | threshold | 8 | 88% | +$4.20 | 21.7 | 0.070 | n/a | 0.00 | G2 |
| 6 | `liq_long_100k_60m_reversion` | SOL | threshold | 8 | 100% | +$5.29 | 18.0 | 0.008 | 0.57 | 0.00 | G1,G2 |
| 7 | `liq_long_250k_60m_reversion` | SOL | threshold | 7 | 100% | +$5.51 | 17.7 | 0.016 | 0.62 | 0.00 | G1,G2 |
| 8 | `liq_long_500k_60m_reversion` | BTC | threshold | 5 | 80% | +$3.63 | 17.0 | 0.375 | n/a | 0.00 | G2 |
| 9 | `liq_long_250k_60m_reversion` | BTC | threshold | 6 | 83% | +$3.33 | 16.7 | 0.219 | n/a | 0.00 | G2 |
| 10 | `cascade_60m_reversion_filt_markov_contra` | ETH | filtered | 13 | 85% | +$10.21 | 15.3 | 0.022 | 0.03 | 0.00 | G1,G2,G4 |

### 3.4 Why everything has wf_pos_frac=0

Walk-forward divides the signal time range into 4 equal-time splits and checks PnL in each. **Because the surviving (post-dedup) events still cluster in Oct 2025 (the only period with HL major-asset liq density), ALL splits land in or near the same week.** The PnL distribution is dominated by ONE market event (the Oct 10 deleveraging followed by an immediate bounce). This means even the "successful" cells have effectively n=1 *unique market event*, just measured at different lead horizons.

### 3.5 Permutation results

Two cells with perm_p < 0.05:
- `ETH_1m_cascade_60m_reversion_filt_ranging`: perm_p=0.03
- `ETH_1m_cascade_60m_reversion_filt_markov_contra`: perm_p=0.03

For these, jittering signal times by ±60s drops PnL — interpretable as a tight microstructure effect at the *exact* moment of cascade firing. But again, the entire cascade population is from the Oct 2025 event, so the permutation is a within-event microstructure shuffle, not a cross-regime robustness test.

### 3.6 Continuation vs reversion bias

Across all assets and horizons, **reversion is the dominant winning direction**:

| Asset | Long-liq best direction | Short-liq best direction |
|---|---|---|
| BTC | Reversion (WR up to 88%) | Continuation (WR up to 100% at n=5-15, but tiny sample) |
| ETH | Reversion (WR 67-85%) | n too small |
| SOL | Reversion (WR 71-100%) | n too small |

Interpretation: in the Oct-Nov 2025 window we have data for, *every* major-asset liquidation event was followed by a price rally / reversion, NOT a continuation. This is a regime-specific observation, not an evergreen strategy property.

### 3.7 Filter results (sub-test 3)

Filters did NOT meaningfully improve any cell:
- `ranging` filter: kept n nearly unchanged (regime was mostly ranging during the event window)
- `ldn_ny` filter: dropped 0-3 trades per cell
- `markov_contra` filter: identical to `ranging` in most cases (regime determined by markov)

No filter combination unlocked a G3 pass.

---

## 4. Visualization-text: where the edge appears

Conceptual heatmap of `Sharpe` across (threshold, hold, direction):
- All assets, LONG-liq, **reversion** direction: Sharpe rises with hold (5m → 60m), peaks at 60m. This is because the Oct 10 event was followed by a recovery rally that took >30min to play out.
- All assets, LONG-liq, **continuation** direction: Sharpe is strongly NEGATIVE and gets MORE negative with longer holds — confirms the same event from the other side.
- SHORT-liq cells have n<5 in our dedup'd window (rare events on majors in this period) — uninterpretable.

Conceptual cross-asset comparison:
- SOL shows the strongest "edge" numbers (Sharpe 43 at 60m hold) — but this is a 5-trade strategy on the tightest cluster.
- BTC and ETH show similar reversion bias but with lower magnitude / wider confidence.

---

## 5. Deploy candidate: NONE

No cell qualifies for deployment. Specifically:

| Requirement | Status |
|---|---|
| ≥10 *distinct* market events post-dedup | ✗ (max 16 cascades on ETH) |
| Walk-forward stability (≥50% splits positive) | ✗ (all wf_pos_frac=0; events too clustered in time) |
| Cross-asset Sharpe consistency | ✗ (different threshold/hold optima per asset) |
| Permutation robustness | Partial (2 cells pass; both ETH cascade variants) |
| Live data coverage | ✗ (HL canonical 30d file has zero major-asset liqs in Apr-May 2026) |

---

## 6. Recommendations for re-attempting N1

To make the cascade hypothesis testable, the data layer needs:

1. **Fresh HL liq pull on majors** — the 30d file shows alts only; the major-asset liq stream may have been deprioritized or is in a different table. Verify with the storedata agent whether liquidation events for BTC/ETH/SOL/HYPE are flowing into the canonical pipeline for the current quarter.

2. **Multi-event coverage** — at minimum, 10+ distinct deleveraging events spread across 3+ months are needed for walk-forward validation. The Oct 10 2025 event is a singular regime change (cross-perp deleveraging), not a recurrent pattern.

3. **Alternative venues** — Binance USD-M futures `forceOrders` stream, OKX liquidations, Bybit liquidations are publicly available, time-stamped, and have much higher event density on majors. Cross-venue liquidation aggregation may surface a generalizable cascade reversion edge.

4. **Lower threshold + non-major coins** — TRUMP/TST/XPL etc. have hundreds of liqs in the 30d canonical window; the hypothesis could be tested on alts where event density is sufficient. Note HL fee structure and funding behave differently on volatile alts; engine params would need tuning.

---

## 7. Files

| File | Purpose |
|---|---|
| `strategy_lab/hl_research_2026_05_26/wave2/w2a_liq_cascade.py` | Backtest script (signal builders, gates, perm test) |
| `strategy_lab/hl_research_2026_05_26/wave2/W2a_liq_cascade.md` | This report |
| `strategy_lab/hl_research_2026_05_26/wave2/W2a_results.csv` | 115-row flat results table for downstream synthesis |

---

## 8. Key code paths

- Liquidation loading + dedup: `w2a_liq_cascade.py:load_liquidations`, `_dedup_close_in_time`
- Threshold signals: `w2a_liq_cascade.py:build_signals_threshold` (5min dedup default)
- Cascade detector: `w2a_liq_cascade.py:detect_cascades` (60s window, ≥5 liqs OR ≥$5M cum)
- Filter loop: `w2a_liq_cascade.py:run_grid` (filtered variants section)
- Validation: `binomial_p`, `permutation_p_value`, `walk_forward_check`
