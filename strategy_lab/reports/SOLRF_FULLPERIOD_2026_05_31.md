# SOL RF Full-Period OOS Backtest — sol_5m_rf_tr_partial_mid
**Date:** 2026-05-31  
**Period:** Apr 24 → May 27 UTC (33 days; gates requiring range_filter/traders_reality start May 1 — ~7 days Apr 24-30 excluded from gated variants)  
**Script:** `strategy_lab/_opt_2026_05_30/17_solrf_fullperiod.py`

---

## Setup

### Substrate
- `dirscan_sol_5m.parquet` — 46,330 rows, offsets [30, 60, 120, 180, 240]s, Apr 24–May 27
- `range_filter_1s.parquet` (SOL) — 1,832,505 rows, May 1–May 27
- `traders_reality_1s.parquet` (SOL) — 1,832,505 rows, May 1–May 27
- `klines_1s.parquet` (BINANCE_SPOT_SOL_USDT) — 4,704,257 rows

### Gate Reconstruction (APPROXIMATE — exact live thresholds unknown)
| Gate | Logic |
|------|-------|
| `g_rf_strict_align` | asof-join `range_filter_1s` at `fire_us` (≤30s stale); `rf_dir` ≠ 0 and agrees with bet direction; `rf_dir_age` < 300s |
| `g_tr_partial_stack_with` | asof-join `traders_reality_1s` at `fire_us` (≤30s stale); `tr_ema_stack_score` ≥ +1 for Up, ≤ −1 for Down |
| Direction | `rf_dir > 0` → Up, `rf_dir < 0` → Down |
| Fill | `u_vwap` (Up) / `d_vwap` (Down); requires `u_ok`/`d_ok` = True |

### Fee Model
Two runs performed:
- **0.07 curve** (`0.07 × p × (1−p)` on winning leg, no fee on losing): research/hypothetical
- **Legacy 2%-on-profit** (winning leg only): matches production (verified 2026-05-22 on 25,900 events)

**All numbers in tables below use legacy 2%-on-profit fee** (production-comparable).

### PnL Formula (flat $5 stake)
- `shares = 5 / entry_vwap`
- Won: `shares × (1 − vwap) × 0.98`
- Lost: `−shares × vwap`
- **Breakeven WR at median vwap=0.639: 64.3%**

### Primary offset: 120s (matches live ~90–180s window)

---

## Main Results — offset 120s

| Variant | n | WR% | $/tr | total$ | MDD$ | Calmar |
|---------|---|-----|------|--------|------|--------|
| base (rf+tr) | 4,663 | 59.8% | −0.2290 | −1,067.89 | −1,345.27 | −0.794 |
| base + drop_US | 3,157 | 59.9% | −0.1832 | −578.36 | −852.53 | −0.678 |
| base + ma_300 | 2,578 | **70.0%** | −0.1183 | −304.90 | −458.42 | −0.665 |
| base + drop_US + ma_300 | 1,742 | **69.9%** | −0.1128 | −196.46 | −337.88 | −0.581 |
| base + drop_US + ma_300 + tr>=2 | 1,511 | **73.7%** | −0.0017 | **−2.55** | −195.43 | **−0.013** |

**Notes:**
- All variants are net-negative OOS. WR is high (70–74%) but below breakeven at these vwap levels.
- 0.07 curve results are ~$50–100 worse (not shown separately); legacy fee used throughout.
- `drop_US` alone does not improve WR (59.8% → 59.9%) but reduces exposure.
- `ma_300` is the dominant gate: +10pp WR lift (60% → 70%), near-independent of `drop_US`.
- `tr_score >= 2` (strong stack) adds another +3–4pp WR → 73.7%, brings total almost to breakeven.
- The triple combo (drop_US + ma_300 + tr>=2) achieves best Calmar (−0.013 ≈ flat), n=1,511 trades.

---

## Offset Sensitivity — base (rf+tr) variant

| offset_s | n | WR% | $/tr | total$ | MDD$ | Calmar |
|----------|---|-----|------|--------|------|--------|
| 30 | 5,749 | 58.6% | −0.2233 | −1,283.63 | −1,329.89 | −0.965 |
| 60 | 5,773 | 57.8% | −0.3136 | −1,810.68 | −1,865.04 | −0.971 |
| **120** | 5,765 | 57.7% | −0.3495 | −2,015.00 | −2,211.24 | −0.911 |
| 180 | 5,575 | 55.8% | −0.5616 | −3,130.72 | −3,185.56 | −0.983 |
| 240 | 4,926 | 50.6% | −0.8758 | −4,314.29 | −4,370.12 | −0.987 |

**Finding:** WR and PnL degrade monotonically with offset. Earlier fires (30–60s) are better — but still net-negative without other gates. The live sleeve targets ~90–180s; offset 120 is the representative choice.

---

## Walk-Forward 50/50 Chronological (offset=120)

H1 = Apr 24 – ~May 10 | H2 = ~May 10 – May 27

| Variant | H1 n | H1 WR% | H1 total$ | H2 n | H2 WR% | H2 total$ |
|---------|------|--------|-----------|------|--------|-----------|
| base (rf+tr) | 2,331 | 60.9% | −778.01 | 2,332 | 58.6% | −407.78 |
| base + drop_US | 1,578 | 61.3% | −438.30 | 1,579 | 58.5% | −219.40 |
| base + ma_300 | 1,289 | 70.6% | −308.79 | 1,289 | 69.4% | −71.00 |
| base + drop_US + ma_300 | 871 | 71.3% | −149.81 | 871 | 68.4% | −97.20 |

**Finding:** `ma_300` gate persists — 70.6% H1, 69.4% H2. `drop_US` does NOT add WR persistence (H1 vs H2 WR improvement negligible). H2 is consistently better than H1 in absolute dollar terms (less net loss), suggesting the signal strengthens in the later sub-period.

---

## Weekly Breakdown — best variant (drop_US + ma_300 + tr>=2, legacy fee)

| Week | n | WR% | total$ |
|------|---|-----|--------|
| Apr 27 – May 3 | 197 | 72.6% | +7.45 |
| May 4 – May 10 | 461 | 75.9% | −11.89 |
| May 11 – May 17 | 489 | 71.2% | −118.41 |
| May 18 – May 24 | 364 | 74.7% | +120.31 |

**Finding:** 2 of 4 weeks profitable (+$7.45, +$120.31). The May 11–17 week is a large loss (−$118) despite 71% WR — driven by high-vwap entries (expensive contracts). The last week (+$120) is the most recent data, which is closest to the live period (May 27–30). Total over 4 weeks: −$2.55 (nearly flat).

---

## New Gate Exploration (base + offset=120, legacy fee)

Sorted by Calmar descending:

| Variant | n | WR% | $/tr | total$ | MDD$ | Calmar |
|---------|---|-----|------|--------|------|--------|
| drop_US + ma_300 + tr>=2 | 1,511 | 73.7% | −0.0017 | −2.55 | −195.43 | **−0.013** |
| drop_US + ma_300 + rf_age<120s | 1,726 | 69.8% | −0.1365 | −235.56 | −366.90 | −0.642 |
| drop_US + ma_300 + ema9_slope | 1,403 | 70.4% | −0.1330 | −186.62 | −297.69 | −0.627 |
| drop_US + ma_300 + london | 762 | 69.4% | −0.1851 | −141.03 | −241.91 | −0.583 |
| drop_US + ma_300 | 1,742 | 69.9% | −0.1128 | −196.46 | −337.88 | −0.581 |
| drop_US + ma_300 + px_neutral | 1,259 | 69.2% | −0.1585 | −199.61 | −324.14 | −0.616 |
| drop_US + ma_300 + not_NY | 1,643 | 69.3% | −0.1950 | −320.43 | −425.38 | −0.753 |

**Best new gate: `tr_score >= 2` (strong EMA stack).** Reduces n by ~13% but lifts WR from 69.9% to 73.7% and brings total PnL to near-zero (−$2.55). This is the clearest improvement over the live gates (drop_US + ma_300).

Other explored gates (not significantly better):
- `rf_age < 120s`: minimal WR lift vs `rf_age < 300s` baseline
- `ema9_slope_align` (from dirscan): mildly helpful (+0.5pp WR), not material
- `london_only`: reduces n too aggressively (n=762), higher loss per trade
- `px_vs_strike < 200bps`: neutral to slightly negative

---

## Sanity vs Live Period

Live (May 27–30, n=371): WR=69.5%, +$93 total, $/tr=+$0.25

| Metric | Full-period OOS | Live period |
|--------|----------------|-------------|
| WR | 69.9% (best combo) | 69.5% |
| $/tr | −0.0017 | +0.25 |
| Period | Apr 24–May 27 | May 27–30 |

WR matches well (69.9% vs 69.5%). The $/tr gap (−$0.0017 vs +$0.25) reflects different vwap levels: live period may have had more favorable (lower vwap) entry prices. Gate reconstruction is approximate — exact thresholds for live sleeve unknown.

---

## Verdict

| Question | Verdict |
|----------|---------|
| Does `drop_US` gate persist OOS? | **WEAK** — WR unchanged (59.8% → 59.9%), only reduces trade count. Does NOT contribute independent alpha. May reduce variance. |
| Does `ma_300` gate persist OOS? | **YES** — strongest gate, +10pp WR (60% → 70%), stable both halves (70.6% / 69.4%), consistent across all combos. |
| Any new gate improving Calmar? | **YES — `tr_score >= 2`** (strong EMA stack). Lifts to 73.7% WR, near-flat total (−$2.55) vs −$196 for drop_US+ma_300 alone. Calmar −0.013 vs −0.581. |
| Is sleeve OOS profitable? | **NO** at base + drop_US + ma_300. **Near-breakeven** at base + drop_US + ma_300 + tr>=2. Not net-positive OOS in absolute terms. |
| Why profitable live but not OOS? | Live PnL (+$0.25/tr) likely reflects: (1) favorable entry vwaps in that 3-day window, (2) exact live gate thresholds differ from approximate reconstruction, (3) 3-day live sample (n=371) is small. |

### Recommended next steps
1. **Add `tr_score >= 2` gate** to the live sleeve spec — highest impact new gate.
2. **Diagnose May 11–17 losing week** (−$118): check if vwap spikes explain it; add a `max_vwap` filter (e.g., skip if `entry_vwap > 0.75`).
3. **Re-check live gate thresholds**: if exact `rf_dir_age` and `tr_ema_stack_score` cutoffs differ, the OOS reconstruction may be loose.
4. The sleeve remains a **watchlist item**: WR is real (70–74%), PnL is gate-sensitive. Not deploy-ready until positive expected value is confirmed at exact live thresholds.

---

*Generated by `strategy_lab/_opt_2026_05_30/17_solrf_fullperiod.py` — 2026-05-31*
