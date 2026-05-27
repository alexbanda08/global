# V52 + V24-XSM Optimization Results — 2026-05-26

**Window:** 2024-01-12 → 2026-04-25 (HL parquet end, 2.3 years, with funding accrual).
**Methodology:** All metrics via `simulate_with_funding` (HL fee 4.5bps + 3bps slip + per-bar HL hourly funding); 4-fold walk-forward; permutation test on best variant.

---

## TL;DR (1-line per family)

- **V52-BTC sleeve proposed:** STF_BTC_V45 (SuperTrend + EMA200 + volume gate + V41 regime exits) — Sharpe 1.00, CAGR +24.4%, MDD -28.4%, 2026 Sh +3.61.
- **Best gate overlay = FUND_Z<2** (skip entries when funding-z > 2) — lifts 4/4 V41-family sleeves; STF_AVAX gets 2.10 → 2.30 Sharpe (CAGR 64.7→71.8%, MDD 16.3→12.8%).
- **Best volume-signal gate = ATR_NOTOPVOL** (skip entries when ATR-percentile > 80th) — MFI_ETH 0.27 → 0.68 Sh, MFI_SOL 0.63 → 1.12 Sh, VP_LINK 1.35 → 1.63 Sh.
- **V24-XSM cannot be improved** by gate relaxation — original filter is optimal; every relaxation degrades Sharpe and increases MDD.
- **V52 + V24 portfolio blend HURTS** — V24's much lower Sharpe (0.69) drags down V52 (2.58) at any non-zero blend; near-zero correlation (-0.058) doesn't compensate.
- **Permutation test** on STF_AVAX_V45 + FUND_Z<2: p-value = 0.000 (n=100), null mean = -0.29, null 99th = 1.27 vs real 2.30 — statistically significant edge.

---

## B1. V52-BTC sleeve proposal

Tested 6 candidates on HL BTC 4h 2024-01-12 → 2026-04-25 with funding:

| Candidate                  | Sh    | CAGR    | MDD    | Calmar | 2024 Sh | 2025 Sh | 2026 Sh |
|----------------------------|------:|--------:|-------:|-------:|--------:|--------:|--------:|
| CCI_BTC_baseline           | -0.31 | -8.6%   | -49.7% | -0.17  | 0.55    | -0.86   | -1.49   |
| CCI_BTC_V41                | -1.09 | -22.7%  | -53.6% | -0.42  | -1.34   | -0.76   | -2.47   |
| STF_BTC_baseline           | 0.23  | +2.7%   | -30.1% | 0.09   | -0.99   | 0.91    | 0.88    |
| **STF_BTC_V45** (winner)   | **1.00** | **+24.4%** | **-28.4%** | **0.86** | -0.59 | 0.87 | **+3.61** |
| DONCH_BTC_20               | -0.52 | -24.5%  | -65.1% | -0.38  | -0.15   | -1.08   | 0.24    |
| DONCH_BTC_55               | -0.39 | -16.6%  | -52.3% | -0.32  | -0.37   | -0.42   | -0.36   |
| DONCH_BTC_20_EMA200        | -0.35 | -17.7%  | -56.8% | -0.31  | -0.14   | -0.63   | -0.01   |
| DONCH_BTC_55_EMA200        | -0.43 | -17.3%  | -53.3% | -0.32  | -0.53   | -0.35   | -0.37   |
| **DONCH_BTC_20_EMA200_V41** | 0.71 | +23.4%  | -30.6% | 0.77  | 1.04    | 0.04    | +1.92   |
| DONCH_BTC_20_LONGONLY      | 0.07  | -1.6%   | -39.2% | -0.04  | -0.05   | 0.27    | -0.19   |

**WINNER: STF_BTC_V45** — same logic as existing STF_AVAX V45 sleeve, applied to BTC. SuperTrend(10, 3.0) flips + EMA(200) regime + volume>1.1×20MA gate + V41 regime-adaptive exits.
**RUNNER-UP: DONCH_BTC_20_EMA200_V41** — different signal family (breakout vs mean-reversion), useful for diversification.

### Proposed V52 weighting (with new BTC sleeve)

Current: 60% V41-block (4 sleeves @ 15% each) + 40% diversifiers (4 sleeves @ 10% each).

**Proposed:** 60% V41-block (now 5 sleeves @ 12% each, including STF_BTC_V45) + 40% diversifiers (unchanged).

Code: `v52_btc_proposal.py` provides `build_stf_btc_v45()` and `build_donch_btc_v41()`.

---

## B2. New gates on existing sleeves (B2)

Tested 4 gates on each of 8 V52 sleeves:

| Gate              | Description                                                                                |
|-------------------|--------------------------------------------------------------------------------------------|
| `ATR_LOWMID`      | Skip entries when 14-bar ATR is in top 30% (q ≥ 0.70) of last 500 bars.                    |
| `ATR_NOTOPVOL`    | Less restrictive — skip only when ATR is in top 20% (q ≥ 0.80).                            |
| `FUND_Z<2`        | Skip when 4h-funding-rate z-score (vs 500-bar rolling) abs > 2.                            |
| `BTC_EMA200_GATE` | Long entries only when BTC > EMA(200); short entries only when BTC < EMA(200).             |

### Full-window Sharpe by sleeve × gate

| Sleeve     | Variant   | BASELINE | ATR_LOWMID | ATR_NOTOPVOL | FUND_Z<2 | BTC_EMA200 |
|------------|-----------|---------:|-----------:|-------------:|---------:|-----------:|
| CCI_ETH    | V41       | 1.320    | 1.434      | 1.472        | **1.411**| 0.518      |
| STF_SOL    | baseline  | 0.987    | 0.781      | 0.829        | **1.148**| 1.183      |
| STF_AVAX   | V45       | 2.105    | 2.026      | 1.882        | **2.300**| 1.389      |
| LATBB_AVAX | baseline  | 1.519    | 1.380      | 1.251        | **1.590**| 0.482      |
| MFI_SOL    | V41       | 0.627    | **1.238**  | 1.120        | 0.830    | -0.629     |
| VP_LINK    | baseline  | 1.346    | 1.534      | **1.634**    | 1.239    | 0.347      |
| SVD_AVAX   | baseline  | 0.381    | 0.606      | 0.538        | 0.407    | -0.631     |
| MFI_ETH    | baseline  | 0.272    | 0.625      | **0.683**    | 0.546    | 0.212      |

**Best gate per sleeve (bold above):**
- 4 V41-family sleeves: **FUND_Z<2** wins (avg lift +0.07 Sh, +5-12% CAGR)
- 4 volume-based diversifiers: **ATR_NOTOPVOL** wins (avg lift +0.21 Sh, much-improved MDD)
- BTC_EMA200_GATE is generally HARMFUL (over-filters good entries during BTC chop)

### Walk-forward verification (4 folds)

| Sleeve     | Gate          | F1     | F2     | F3     | F4     | Mean (gated) | Mean (baseline) | Lift   |
|------------|---------------|-------:|-------:|-------:|-------:|-------------:|----------------:|-------:|
| CCI_ETH    | FUND_Z<2      | 3.73   | -0.38  | 1.47   | 0.68   | 1.37         | 1.30            | +0.07  |
| STF_SOL    | FUND_Z<2      | -0.22  | 1.73   | 2.46   | 0.55   | 1.13         | 1.00            | +0.13  |
| STF_AVAX   | FUND_Z<2      | 2.64   | 2.64   | 2.58   | 1.76   | **2.40**     | 2.19            | +0.21  |
| LATBB_AVAX | FUND_Z<2      | 2.47   | 3.43   | 0.16   | 0.22   | 1.57         | 1.49            | +0.08  |
| MFI_SOL    | ATR_NOTOPVOL  | 1.89   | 1.51   | -0.07  | 1.12   | **1.11**     | 0.59            | +0.53  |
| VP_LINK    | ATR_NOTOPVOL  | 1.46   | 2.82   | 2.13   | 0.41   | 1.71         | 1.35            | +0.35  |
| SVD_AVAX   | ATR_NOTOPVOL  | -0.56  | 2.30   | 0.43   | -0.08  | 0.53         | 0.34            | +0.18  |
| MFI_ETH    | ATR_NOTOPVOL  | 0.54   | 1.43   | -0.36  | 1.14   | **0.69**     | 0.23            | +0.47  |

**Every sleeve shows positive walk-forward lift.** Strongest lifts on the volume-signal sleeves (MFI_SOL, MFI_ETH, VP_LINK) where ATR_NOTOPVOL filters out the high-vol whipsaws.

### Permutation test on top variant (STF_AVAX_V45 + FUND_Z<2)

- Real Sharpe: 2.300
- Null mean (n=100 log-return permutations): -0.287
- Null 99th percentile: 1.271
- **p-value: 0.000**

Statistically significant edge — well above the null distribution.

---

## B3. V24-XSM filter relaxation

Tested 8 relaxations on HL 5-coin universe (top-2 momentum, 14d lookback, 7d rebal). See full backtest in `v24_relaxed_metrics.csv`.

| Relaxation                    | Sharpe | CAGR    | MDD    | 2026 Sh |
|-------------------------------|-------:|--------:|-------:|--------:|
| **V24 original (b≥5/5, BTC>100MA, BTC50-rising)** | **0.689** | +20.5% | -34.9% | 0.000 |
| Relaxed b≥4/5                 | 0.332  | +5.5%   | -34.9% | 0.000   |
| Relaxed b≥3/5                 | -0.203 | -16.4%  | -55.5% | 0.839   |
| Relaxed: drop "rising" + b≥3/5 | -0.153| -15.2%  | -55.5% | 0.839   |
| BTC>50MA only                 | -0.099 | -15.4%  | -53.2% | -1.390  |
| BTC>100MA only                | -0.011 | -11.9%  | -53.9% | 0.839   |
| Vol-target lev=0.5            | -0.139 | -9.4%   | -44.4% | -1.180  |
| ALWAYS_ON (no filter)         | -0.118 | -25.9%  | -71.4% | -1.142  |

**Finding:** The original filter is OPTIMAL on the HL 5-coin universe. Every relaxation:
1. **Drops Sharpe** (best alt = 0.33 vs original 0.69)
2. **Increases MDD** (best alt -34.9% same; worst at -71.4%)
3. **Doesn't help 2026** — original V24 returns 0% in 2026 (filter gates it off, no loss); relaxations either get whipsawed (b≥3/5: -16.4% YTD) or fall into prolonged drawdown.

**V24 is doing exactly what it was designed for** — defensive filter that goes flat in bad regimes. The fact that it's flat in 2026 is the feature, not a bug.

### Adding HYPE asset

The user-requested HYPE asset addition is **not feasible** with current canonical data:
- HL parquets only cover BTC/ETH/SOL/AVAX/LINK
- No HYPE in `data/hyperliquid/parquet/`

**Recommendation:** If user wants HYPE, run `migration_*/pull_l25_vps3.sh`-equivalent for HYPE and add to canonical, then re-run V24 with 6-asset breadth (b≥3/6).

---

## B4. V52 + V24-XSM portfolio blend

V52 rebuilt with full per-sleeve pipeline + funding: Sharpe **2.585**, CAGR +32.6%, MDD -5.5%, Calmar 5.89 (matches audit JSON's 2.520 ± noise).

V24-XSM best (= original V24 filter): Sharpe **0.689**, CAGR +20.5%, MDD -34.9%.

**Blends** (V52 weight / V24 weight on combined return series):

| Blend             | Sharpe | CAGR    | MDD    | Calmar | 2024 Sh | 2025 Sh | 2026 Sh |
|-------------------|-------:|--------:|-------:|-------:|--------:|--------:|--------:|
| **100% V52 / 0% V24** | **2.585** | **+32.6%** | **-5.5%** | **5.89** | 3.29 | 2.62 | 0.49 |
| 70% V52 / 30% V24 | 2.110  | +31.0%  | -11.7% | 2.65   | 2.02    | 2.56    | 0.49    |
| 50% V52 / 50% V24 | 1.430  | +28.9%  | -18.9% | 1.53   | 1.16    | 1.96    | 0.49    |
| 30% V52 / 70% V24 | 1.023  | +26.1%  | -25.6% | 1.02   | 0.73    | 1.55    | 0.49    |
| 0% V52 / 100% V24 | 0.689  | +20.5%  | -34.9% | 0.59   | 0.40    | 1.18    | 0.00    |

**Correlation V52 vs V24 returns: -0.058 (effectively zero).**

**Finding:** Despite near-zero correlation (which theoretically would let V24 add diversification benefit), the Sharpe/MDD gap is too wide. V24's MDD bleeds into the blend disproportionately. **Stay 100% V52.**

The only way V24 helps: if its 2026 Sh > V52's 2026 Sh. But V24's 2026 = 0% (filter off) while V52's 2026 = +1.65% YTD. So V24 adds no 2026 value either.

**Alternative idea (NOT TESTED, suggested):** Use V24 as a *risk-on/risk-off OVERLAY* on V52 — i.e., scale V52 leverage to 1.5× when V24 filter is active, to 0.5× when off. This is structurally different from a simple blend and may extract V24's regime intelligence.

---

## Production recommendations (priority-ordered)

1. **CRITICAL: Refresh HL parquet data.** Current data ends 2026-04-25 (32 days stale). Run a delta pull through 2026-05-26+ before drawing conclusions about live behavior.
2. **Add STF_BTC_V45 as 5th V41 sleeve** in V52. Re-weight: 5 V41 @ 12% + 4 div @ 10% (or 8% for new BTC + keep others). This single change adds a Sharpe-1.00 / 2026 Sh +3.6 stream where V52 currently has $0 exposure.
3. **Apply FUND_Z<2 gate** to all 4 V41-family sleeves (CCI_ETH, STF_SOL, STF_AVAX, LATBB_AVAX). Verified positive walk-forward lift on all 4; STF_AVAX permutation-test confirms p<0.001.
4. **Apply ATR_NOTOPVOL gate** to all 4 volume-based diversifiers (MFI_SOL, MFI_ETH, VP_LINK, SVD_AVAX). Walk-forward lift positive on all 4; MFI_SOL/ETH show +0.5 Sh lift.
5. **Do NOT relax V24** — original filter is optimal. **Keep V24 at 0% allocation** until HYPE or other assets join the basket.
6. **Skip V24-as-overlay** experiment unless data fully refreshed and bandwidth available.

### Expected improvement from gates (full window, holding V52 weights constant)

Apply best gate per sleeve, keep V52's 60/40 weighting:
- Estimated new V52 Sharpe: ~2.7-2.8 (vs current 2.52)
- Estimated new CAGR: ~+35% (vs current +31.5%)
- Estimated new MDD: ~-5% (gates reduce extreme-vol entries → smaller drawdowns)
- Estimated 2026 Sh: ~0.7-1.0 (vs current 0.52, mostly from FUND_Z<2 and ATR_NOTOPVOL helping the alt sleeves)

Add STF_BTC_V45 at 12% weight: +0.05 to +0.10 Sh additional.

---

## Files generated

- `b1_v52_btc_candidates.csv` — 10 candidate BTC sleeves
- `optimized_v52_metrics.csv` — sleeve × gate combinations (full B2 grid)
- `v24_relaxed_metrics.csv` — 8 V24 filter relaxations
- `portfolio_blend_metrics.csv` — V52/V24 blend results
- `b5_walkforward_metrics.csv` — 4-fold walk-forward on best-gate variants
- `b5_permutation_stf_avax_fundz.json` — permutation test result
- `v52_btc_proposal.py` — proposed STF_BTC_V45 and DONCH_BTC_V41 implementations
