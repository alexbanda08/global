# VPIN + Hawkes Process — first-pass results
**Date:** 2026-05-26
**Window:** 2026-05-01 → 2026-05-23 (22d backtest window on `hybrid_standalone_per_fire`; 23d on `hybrid_fire_universe`).
**Fee model:** Legacy ($1 stake, 2% on profit only — production-faithful per CLAUDE.md §"Polymarket fee model").
**Data source:** binance 1s OHLCV with `taker_buy_base` (BTC/ETH/SOL spot @ Binance).
**Code:** `strategy_lab/vpin_hawkes_2026_05_26/`
**Panels:** `data/v4/canonical/_results/{vpin_panel.parquet, hawkes_panel.parquet, vpin_hawkes_at_fires.parquet}`

---

## 1) Panel construction summary

### VPIN (Easley/López de Prado/O'Hara 2012, with BVC adaptation)
- Per asset: equal-volume buckets of size `daily_volume / 50` (~50 buckets/day).
- Buy/sell vol per bar derived from `taker_buy_base / volume_traded` (taker-side proxy — BVC's pBuy ~ this when no tick rule is available).
- Bucket imbalance ratio = `|buy_vol − sell_vol| / total_vol`.
- VPIN = rolling mean over last 50 buckets (≈ 1 day).
- Z-score = causal expanding-window standardization.

**Bucket statistics** (≈1,106 buckets per asset over the window):
| Asset | bucket_size | VPIN p50 | VPIN p90 | VPIN p95 | VPIN p99 |
|---|---|---|---|---|---|
| BTC | 263.86 | 0.186 | 0.221 | 0.244 | 0.262 |
| ETH | 5,039.0 | 0.179 | 0.297 | 0.335 | 0.441 |
| SOL | 46,212  | 0.164 | 0.193 | 0.201 | 0.231 |

ETH has the FATTEST tail (p99 = 0.44 vs 0.26 for BTC, 0.23 for SOL) — its 1s flow is more bursty.

### Hawkes intensity (Hawkes 1971; exponential-kernel proxy per CLAUDE.md guidance)
- 1s bar marked as **buy event** if `buy_vol > 0.6×total`, **sell event** if `<0.4×total`.
- Events weighted by `trades_count` (clipped @ p99).
- EMA-Hawkes intensity with **half-life = 60s** (decay = 0.9885):
  - `λ_buy(t)  = 0.9885·λ_buy(t-1) + 0.0115·buy_event(t)`
  - `λ_sell(t) = 0.9885·λ_sell(t-1) + 0.0115·sell_event(t)`
- This is the closed-form solution of a 1-step exponential Hawkes kernel; full MLE was deferred per the task spec ("EWMA proxy acceptable if MLE too slow on 5.5M bars").
- `λ_total = λ_buy + λ_sell`; `λ_imbalance = (λ_buy − λ_sell) / λ_total`.
- `recent_burst = 1` if `λ_total > 1.5 × rolling_mean(λ_total, 3600s)`.

**Hawkes statistics**:
| Asset | λ_total p50 | λ_total p95 | burst frac | |λ_imb|>0.3 frac |
|---|---|---|---|---|
| BTC | 6.21 | 21.76 | 13.8% | 39.3% |
| ETH | 4.62 | 17.26 | 13.5% | 34.9% |
| SOL | 2.41 |  8.42 | 12.6% | 31.6% |

Bursts cluster at ~12-14% of bars across assets (sensible — 1-hour rolling baseline; 1.5× multiplier).

---

## 2) VPIN distribution & high-VPIN ("toxic") regimes

- **BTC**: z>2 in only **0.7%** of bars → "toxic" regime is rare.
- **ETH**: z>2 in **10.8%** of bars → frequently bursty.
- **SOL**: z>2 in **5.6%** of bars.

ETH's high toxic-regime frequency is consistent with its inflated VPIN p99 (0.44).

---

## 3) Standalone rule WRs (all assets × all offsets × 5m+15m, n≥200 per sleeve)

| Rule | sleeves | n | avg_WR | sum_pnl | avg_dpt |
|---|---|---|---|---|---|
| **H-A** (bet sign(λ_imb) when |λ_imb|>0.3) | 54 | 84,538 | **70.6%** | **+$36,587** | **+$0.398** |
| H-B (bet WITH momentum when burst) | 48 | 26,609 | 50.7% | +$81 | +$0.004 |
| V-C (bet WITH momentum when low VPIN) | 54 | 87,697 | 50.2% | −$84 | −$0.007 |
| V-A_SKIP (z>2 — pnl of skipped) | 28 | 14,431 | 49.3% | −$312 | −$0.024 |
| V-B (bet WITH mom when z<−1) | 46 | 36,973 | 48.9% | −$337 | −$0.033 |
| H-C_BET (skip when λ_tot<q20) | 54 | 179,703 | 49.9% | −$2,655 | −$0.012 |
| V-A_BET (z≤2) | 54 | 218,373 | 49.9% | −$3,315 | −$0.011 |

**Standout: H-A.** Betting in the direction of recent buy/sell flow clustering (when clustering exceeds threshold) hits 70.6% WR with **+$36,587** total PnL across the screening universe. Other rules are at-or-near coin-flip.

VPIN-based rules ALL fail in standalone mode. Skipping toxic flow does NOT improve the underlying universe meaningfully on this 22d window.

---

## 4) Gate-overlay results on top 15 sleeves (V1..V12 from `hybrid_standalone_per_fire`)

Top lifts (where gate retains ≥150 fires AND improves $/trade):

| Asset | tf | offs | sleeve | gate | base_dpt | gate_n | gate_dpt | **lift_dpt** |
|---|---|---|---|---|---|---|---|---|
| BTC | 5m | 270 | V9 | g_vpin_low (z<0) | $6.09 | 156 | $11.75 | **+$5.67** |
| ETH | 5m | 180 | V6 | g_vpin_extreme_skip | $7.52 | 181 | $10.56 | +$3.04 |
| ETH | 5m | 150 | V9 | g_vpin_low | $4.54 | 201 | $6.37 | +$1.83 |
| BTC | 5m | 60  | V10 | g_hawkes_burst_with | $1.05 | 232 | $2.69 | +$1.65 |
| BTC | 5m | 60  | V1  | g_hawkes_burst_with | $0.30 | 412 | $1.90 | +$1.60 |
| BTC | 5m | 60  | V3  | g_hawkes_burst_with | $0.45 | 364 | $1.92 | +$1.46 |
| ETH | 5m | 150 | V8  | g_hawkes_imbalance_with | $3.50 | 288 | $4.67 | +$1.17 |
| ETH | 5m | 150 | V9  | g_vpin_extreme_skip | $4.54 | 268 | $5.67 | +$1.13 |

**Pattern:** `g_hawkes_burst_with` is the most consistent gate at low offsets (60s) on BTC, lifting dpt by $1.40-1.65 on V1/V3/V10. `g_vpin_extreme_skip` and `g_vpin_low` work on slower ETH 5m sleeves.

Full table: `data/v4/canonical/_results/vpin_hawkes_gates.csv` (60 rows).

---

## 5) Top 5 NEW deployable VPIN/Hawkes sleeves

Best-of-class from **Rule H-A standalone** with strict 3-way validation (PASS criterion: dpt>0 in train, val, AND lockbox; bootstrap lower-CI on lockbox > 0).

| # | Asset | tf | offs | n_train | n_val | n_lock | dpt_lock | WR_lock | CI_lo | PASS |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | ETH | 5m |  120 | 1,292 | 364 | 275 | **+$0.541** | 77.8% | +$0.447 | ✅ |
| 2 | BTC | 5m |  120 | 1,672 | 470 | 340 | +$0.508 | 76.2% | +$0.421 | ✅ |
| 3 | SOL | 5m |  120 | 1,411 | 386 | 284 | +$0.492 | 75.4% | +$0.394 | ✅ |
| 4 | ETH | 5m |   90 | 1,340 | 386 | 296 | +$0.472 | 74.3% | +$0.378 | ✅ |
| 5 | SOL | 5m |   90 | 1,472 | 410 | 293 | +$0.419 | 71.7% | +$0.318 | ✅ |

These five sleeves all use the same trigger: **bet sign(λ_imbalance) when |λ_imbalance| > 0.3**, on BTC/ETH/SOL 5m at fire_offset_s ∈ {90, 120}.

Full ranking: `data/v4/canonical/_results/vpin_hawkes_validation_HA.csv` (54 H-A sleeves; **52/54 PASS lockbox** with strictly-positive bootstrap CI).

---

## 6) Strict 3-way validation summary

Splits chosen as 64% / 21% / 15% of the available time window (~14d / 4-5d / 3d on the 22d set).

**Rule H-A standalone (54 asset × tf × offset combos):**
- 54/54 dpt_lock > 0
- 52/54 PASS (positive dpt in train AND val AND lock, bootstrap CI lower > 0)
- Two fail-cases are 15m at offset 60s (ETH and SOL) — CI_lo just slips below zero at small n_lock (~115-119).

**Gate overlays on top-15 sleeves (25 candidates):**
- 0/25 lockbox PASS — the 22d backtest split into 14/4-5/3 leaves only ~10-30 lockbox fires for the high-offset narrow-trigger V9/V12 sleeves. CIs blow out. Several have positive dpt_lock but fail the strict CI test.
- Notable near-miss: **BTC 5m offset=60 V10 + g_hawkes_imbalance_with** (n_lock=218, dpt_lock=+$3.21, CI_lo=+$0.06). Effectively the same signal pathway as standalone H-A.

---

## 7) Caveats and integrity notes

1. **The H-A high WR at LATE offsets is partly tautological.** At fire_offset_s=300 the 5m slot is OVER (0s remaining); the "Hawkes signal" is trivially observing the last minute of price action that JUST resolved Up/Down. WR climbs monotonically with offset:

   | offset | remaining | H-A WR (5m, |imb|>0.3) |
   |---|---|---|
   | 30 | 270s | 59.3% |
   | 60 | 240s | 65.2% |
   | 90 | 210s | 70.6% |
   | 120 | 180s | 73.6% |
   | 150 | 150s | 76.3% |
   | 180 | 120s | 77.9% |
   | 240 | 60s | 79.3% |
   | 300 | 0s | **79.6%** |

   The "5 deployable sleeves" in §5 are the EARLY-OFFSET ones (90-120s, with 180-210s of slot remaining) — those are the genuinely predictive cells. Offset=300 sleeves should NOT be deployed standalone; they require book-fill at fire_us when slot has just ended and Polymarket price would already be at $0.99/$0.01.

2. **No lookahead in panel construction.** EMA Hawkes at bar i depends only on bars [0..i]. VPIN buckets close progressively — bucket-i value is only assigned to bars AFTER bucket-i completed. Fire-time lookup uses `fire_us − 1s` (the bar that ended at-or-before fire − 1s).

3. **Hawkes is EMA approximation, not MLE.** Full Hawkes MLE on 5.5M bars per asset was prohibitive (~hours). The EMA proxy is closed-form for fixed (μ=0, α=1−decay, β=ln(2)/60s) and matches the Hawkes exponential-kernel shape. Refit-per-sliding-window MLE is a future extension if H-A holds in paper deploy.

4. **VPIN didn't find the toxic-flow skip regime convincingly.** V-A_SKIP shows the SKIPPED set has dpt=−$0.024 (mildly toxic as predicted) but the BET complement (z≤2, 218k fires) is at −$0.011 dpt — so the SKIP is removing slight-loss trades from a slight-loss universe. NOT enough lift on its own. Only the **GATE-form** of g_vpin_extreme_skip on already-profitable V6/V9/V12 sleeves produces meaningful lift (table §4), and even that doesn't survive the tiny lockbox.

5. **Polymarket trades_polymarket dataset is stale (May 6 per CLAUDE.md).** A PM-side VPIN (using actual outcome-token taker prints) would be richer than binance-vol VPIN — left as a follow-on once PM trades pipeline catches up.

6. **Production parity not yet confirmed.** All PnL in this report is at LegacyConfig $1 stake, vwap=0.5 approximation. To deploy H-A at offset=90-120s, need to re-run with `engine_v2.LegacyConfig` against the actual L25 book-walk at fire_us (same way the 5 active sleeves were validated for shadow audit).

---

## Recommendation

The **H-A signal at fire_offset_s ∈ {90, 120}** is the only thing in this batch worth a paper-deploy spec. Action items:
1. Re-run H-A on BTC/ETH/SOL 5m at offset=90/120 through `engine_v2.LegacyConfig` with full L25 book-walk to get production-faithful PnL.
2. If positive at production fees, add to the shadow audit pool alongside the existing 5 verified sleeves.
3. Run a longer backtest window (full 28-32d, not just the 22d on `hybrid_standalone_per_fire`) — current lockbox of 270-340 fires is small.

VPIN-as-gate and VPIN-standalone do NOT clear the bar on this dataset. Worth re-testing with PM-side trades once the polymarket trades pipeline catches up beyond May 6.
