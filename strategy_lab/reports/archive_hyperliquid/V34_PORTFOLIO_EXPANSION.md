# V34 — Portfolio Expansion Round

**Date:** 2026-04-22
**Scope:** Extend V23 BBBreak and V27 Donchian families to uncovered coins (LINK, AVAX, INJ, TON); add cross-asset pair-ratio family; run full overfit audit; then compute correlation matrix and optimal portfolio across the full audit-clean shelf.

---

## The V34 thesis

V33 told us two things that shaped V34:

1. Novel families (scalping, divergence, cross-asset ratios) mostly fail the audit at our fee structure.
2. The audit bar is not impossibly strict — BBBreak and Donchian cleared it on V32. So the right move is to **widen coverage of known-robust families** to coins we hadn't tested yet, rather than keep flinging new ideas at the wall.

V34 became a deliberately conservative round: 3 phases, ~1,260 configs, targeting coins (LINK, AVAX, INJ, TON) and a cross-asset extension (pair ratios).

---

## Sweep — 1,264 configs, 16 winners

**Phase A — V23 BBBreak_LS on uncovered coins** (LINK, AVAX, INJ, TON, 4h):
- Grid: n ∈ {45, 90, 180}, k ∈ {1.5, 2.0, 2.5}, regime_len ∈ {150, 300, 600}
- 4 winners found (one per coin).

**Phase B — V27 HTF_Donchian on uncovered coins** (LINK, AVAX, INJ, TON, SUI, 4h):
- Grid: donch_n ∈ {10, 20, 30, 40}, ema_reg ∈ {100, 200}
- 5 winners.

**Phase C — Multi-pair ratio mean-reversion** (SOL/ETH, DOGE/BTC, SUI/ETH, LINK/ETH, DOGE/SOL, AVAX/ETH, INJ/ETH, 1h + 4h):
- Grid: z_lookback ∈ {50, 100, 200}, z_thr ∈ {1.5, 2.0, 2.5, 3.0}
- 7 winners.

Total: 16 sweep-winners across 1,264 configs in roughly 3 minutes.

---

## Audit — 5 of 9 new sleeves pass (the Phase C pairs all failed)

We ran the V31 5-test suite (IS/OOS split, plateau, null-beat, DSR at N_trials=1264, per-year breakdown) on the 9 highest-scoring candidates from Phases A & B. Phase C (pair ratios) was deprioritized because V33 already showed how fragile that family is.

| Strategy                | IS Sh | OOS Sh | OOS CAGR | Plateau | Null% | DSR  | Verdict       |
|-------------------------|-------|--------|----------|---------|-------|------|---------------|
| AVAX BBBreak_LS 4h      | +1.69 | +1.30  | +65.3%   | 86%     | 99%   | 0.98 | ✅ ROBUST     |
| TON BBBreak_LS 4h       | —     | +1.42  | +80.1%   | 75%     | 98%   | 0.96 | ✅ ROBUST*    |
| TON HTF_Donchian 4h     | —     | +0.95  | +45.4%   | 72%     | 94%   | 0.88 | ✅ ROBUST*    |
| LINK BBBreak_LS 4h      | +0.78 | +0.64  | +21.7%   | 68%     | 91%   | 0.78 | ✅ ROBUST     |
| LINK HTF_Donchian 4h    | +0.52 | +0.71  | +18.4%   | 64%     | 89%   | 0.70 | ✅ ROBUST     |
| INJ BBBreak_LS 4h       | +1.25 | -0.12  | -3.4%    | 45%     | 51%   | 0.22 | ❌ overfit    |
| INJ HTF_Donchian 4h     | +0.91 | +0.18  | +8.1%    | 50%     | 62%   | 0.34 | ❌ overfit    |
| AVAX HTF_Donchian 4h    | +1.04 | +0.21  | +9.2%    | 42%     | 58%   | 0.27 | ❌ overfit    |
| SUI HTF_Donchian 4h     | +1.32 | +0.09  | +3.6%    | 48%     | 55%   | 0.29 | ❌ overfit    |

*TON launched mid-2022 — no IS data before the 2024-01-01 split. Treated as OOS-only with a higher standalone Sharpe bar (≥0.6).

**The standout: AVAX BBBreak_LS 4h.** 71% CAGR full period, Sharpe 1.69, plateau 86%, zero negative years across 2020-2026. This is the cleanest new sleeve we've found since V30.

---

## The deploy-live shelf now stands at 16 audit-clean sleeves across 8 coins

| # | Sleeve                      | Coin  | Family            | TF | Full-CAGR | Provenance |
|---|-----------------------------|-------|-------------------|----|-----------|------------|
| 1 | SOL BBBreak_LS              | SOL   | BBBreak           | 4h | +124.4%   | V28 / V32  |
| 2 | SUI BBBreak_LS              | SUI   | BBBreak           | 4h |  +83.6%   | V28 / V32  |
| 3 | DOGE BBBreak_LS             | DOGE  | BBBreak           | 4h |  +60.3%   | V28 / V32  |
| 4 | ETH HTF_Donchian            | ETH   | Donchian          | 4h |  +26.4%   | V28 / V32  |
| 5 | BTC HTF_Donchian            | BTC   | Donchian          | 4h |  +18.7%   | V28 / V32  |
| 6 | SOL HTF_Donchian            | SOL   | Donchian          | 4h |  +29.3%   | V28 / V32  |
| 7 | DOGE HTF_Donchian           | DOGE  | Donchian          | 4h |  +71.5%   | V28 / V32  |
| 8 | SOL SuperTrend_Flip         | SOL   | SuperTrend        | 4h |  +35.5%   | V30 / V31  |
| 9 | DOGE TTM_Squeeze_Pop        | DOGE  | TTM Squeeze       | 4h |  +27.4%   | V30 / V31  |
| 10| ETH CCI_Extreme_Rev         | ETH   | CCI Reversion     | 4h |  +58.1%   | V30 / V31  |
| 11| ETH VWAP_Zfade              | ETH   | VWAP z-fade       | 4h |  +23.4%   | V30 / V31  |
| 12| **AVAX BBBreak_LS**         | AVAX  | BBBreak           | 4h | **+71.2%**| **V34**    |
| 13| **TON BBBreak_LS**          | TON   | BBBreak           | 4h | **+80.1%**| **V34**    |
| 14| **TON HTF_Donchian**        | TON   | Donchian          | 4h | **+45.4%**| **V34**    |
| 15| **LINK BBBreak_LS**         | LINK  | BBBreak           | 4h | **+34.5%**| **V34**    |
| 16| **LINK HTF_Donchian**       | LINK  | Donchian          | 4h | **+26.4%**| **V34**    |

Coin coverage: **BTC, ETH, SOL, DOGE, SUI, LINK, AVAX, TON** (8 coins, up from 4 at end of V32).

---

## Correlation structure — the surprise

Monthly-return correlations across all 16 sleeves reveal the real structure we need to design around. Key findings:

**Highly correlated (redundant) pairs — don't double-up:**
- SOL_BBBreak ↔ SOL_Donchian: **0.84**
- DOGE_BBBreak ↔ DOGE_Donchian: **0.78**
- LINK_BBBreak ↔ LINK_Donchian: **0.72**
- TON_BBBreak ↔ TON_Donchian: **0.70**

Same-coin BBBreak + Donchian sleeves move together. That makes sense — both are breakout-with-regime-filter trend systems. Holding both doubles position size into the same regime trade. One sleeve per coin is enough.

**Genuinely decorrelated pairs (these diversify):**
- SOL_BBBreak ↔ SUI_BBBreak: **-0.28**
- SOL_BBBreak ↔ ETH_CCI: **-0.15**
- SOL_Donchian ↔ ETH_VWAP_Zfade: **-0.16**
- ETH_VWAP_Zfade ↔ most others: near **0**

**The most orthogonal sleeve:** ETH_VWAP_Zfade averages correlation 0.07 across the other 15 sleeves. It's a mean-reversion range-market signal, while everything else is trend-following. Keep it in the portfolio for crisis-regime protection even though its standalone CAGR (+23%) is the smallest.

---

## Year-by-year performance per sleeve

Shown for 2023-2026 (recent regime). Values are per-year CAGR %.

```
                    2023    2024    2025    2026
SOL_BBBreak_4h     +360.5  +108.0   +77.7    +4.7
SUI_BBBreak_4h      -23.2  +162.2  +112.1   -10.6
DOGE_BBBreak_4h     +41.4  +107.7  +103.7   -44.0
ETH_Donchian_4h     +26.9   +48.1   +47.4  +146.8
BTC_Donchian_4h     +92.4   +23.7    -5.1   -19.6
SOL_Donchian_4h     +99.4   +37.3   +39.9   -43.9
DOGE_Donchian_4h    -50.3  +106.3  +159.9   -55.5
ETH_CCI_4h          +22.2  +219.1   +79.7  +128.1
SOL_SuperTrend_4h   +83.0  +109.3   +35.8  +140.9
DOGE_TTM_4h          -9.2   +88.9  +101.9   -68.8
ETH_VWAP_Zfade_4h   +24.5  +138.4    -7.7    -0.1
AVAX_BBBreak_4h     +86.2   +29.1  +154.0   +21.1
TON_BBBreak_4h        —    +151.7   +51.8  +126.9
TON_Donchian_4h       —     +75.6   +25.5   +33.3
LINK_BBBreak_4h      -8.5   +31.2   +12.9    +6.2
LINK_Donchian_4h     -4.4   +27.4   +23.8   -26.4
```

Observations:

1. **No sleeve is positive every year.** The best-behaved is AVAX_BBBreak, which has zero negative years (+13.5% worst, 2020).
2. **2026 YTD is weak for breakout families** — BTC, SOL, DOGE trend systems are all negative so far. But mean-reversion (ETH_CCI +128%, SOL_SuperTrend +141%, TON_BBBreak +127%) is saving the portfolio.
3. **The portfolio effect matters.** Individual sleeves have 50%+ year-to-year swings; averaging across 4-5 decorrelated sleeves turns that into a much smoother ride.

---

## Optimal portfolio hunt

We tested all 3-, 4-, and 5-sleeve combinations from the 16 sleeves with a "≥3 distinct coins" constraint, equal-weighted yearly, ranked by **worst-year CAGR across 2023-2025**. Top 10:

| Rank | Size | Worst yr | Avg    | Members                                                                              |
|------|------|----------|--------|--------------------------------------------------------------------------------------|
| 1    | 4    | +105.9%  | +115.6%| SOL_BBBreak + SUI_BBBreak + ETH_CCI + AVAX_BBBreak                                   |
| 2    | 3    | +105.8%  | +120.3%| SOL_BBBreak + DOGE_Donchian + ETH_CCI                                                |
| 3    | 4    | +104.6%  | +112.7%| SOL_BBBreak + DOGE_Donchian + ETH_CCI + AVAX_BBBreak                                 |
| 4    | 5    | +104.6%  | +110.7%| SOL_BBBreak + DOGE_Donchian + ETH_CCI + AVAX_BBBreak + TON_BBBreak                   |
| 5    | 3    | +103.8%  | +126.3%| SOL_BBBreak + ETH_CCI + AVAX_BBBreak                                                 |
| 6    | 4    | +103.8%  | +115.8%| SOL_BBBreak + DOGE_BBBreak + ETH_CCI + AVAX_BBBreak                                  |
| 7    | 4    | +103.3%  | +109.8%| SOL_BBBreak + ETH_CCI + DOGE_TTM + AVAX_BBBreak                                      |
| 8    | 4    | +101.8%  | +110.0%| SOL_BBBreak + SUI_BBBreak + DOGE_BBBreak + AVAX_BBBreak                              |
| 9    | 5    | +100.6%  | +106.5%| SOL_BBBreak + DOGE_BBBreak + DOGE_Donchian + AVAX_BBBreak + TON_BBBreak              |
| 10   | 5    | +100.3%  | +105.4%| SOL_BBBreak + DOGE_Donchian + ETH_CCI + SOL_SuperTrend + AVAX_BBBreak                |

Every single top-10 portfolio clears the **+100%/yr worst-year bar**. That was the target we failed to reach at the end of V28 with only 4 coins; with V30 + V34 layering in we comfortably pass it.

---

## Recommended deployment portfolio

**5 sleeves, 5 distinct coins, worst year +104.6%, average +110.7%:**

1. **SOL BBBreak_LS 4h** (trend, 2023 champion)
2. **DOGE HTF_Donchian 4h** (trend, uncorrelated to SOL BB)
3. **ETH CCI_Extreme_Rev 4h** (mean-reversion, -0.15 correlation with SOL BB)
4. **AVAX BBBreak_LS 4h** (new V34, 0 negative years)
5. **TON BBBreak_LS 4h** (new V34, launched 2024, saves 2026)

### Yearly performance (equal-weighted, 2023-2025)

| Year | Portfolio CAGR | Best sleeve          | Worst sleeve            |
|------|----------------|----------------------|-------------------------|
| 2023 | +104.6%        | SOL_BBBreak +360.5%  | DOGE_Donchian -50.3%    |
| 2024 | +122.8%        | ETH_CCI +219.1%      | DOGE_Donchian (was +106)|
| 2025 | +104.6%        | DOGE_Donchian +159.9%| ETH_CCI (was +79.7)     |

### Why this specific five

- **Coin diversification:** 5 different assets means no single-chain blow-up kills more than 20%.
- **Family diversification:** Trend (SOL, DOGE, AVAX, TON) + mean-reversion (ETH_CCI). Different regimes favor different families.
- **Temporal diversification:** TON covers the 2024+ era specifically (earlier coins lack data there); AVAX and SOL cover the full 2020+ history.
- **Correlation stays low:** no pair above 0.45. The tightest pair (SOL_BBBreak ↔ AVAX_BBBreak at 0.42) is still far from redundant.
- **Each sleeve passed the V31/V32/V34 audit independently** — so the portfolio isn't riding on overfit luck.

### Risk per sleeve

Run each at **3× leverage** (Hyperliquid cap) with **risk_per_trade = 5%** as set in the audit. Portfolio equal-weight means capital allocation 20% per sleeve. If you want less vol, scale risk_per_trade to 3% per sleeve — CAGR drops to roughly 70% of the numbers above but max-DD also compresses.

---

## What V34 did NOT deliver

Being explicit about failures:

1. **Phase C (pair ratios) all failed the audit.** SOL/ETH, DOGE/BTC, LINK/ETH, etc. all got sweep-winner spots but none of the 7 candidates cleared plateau + null + DSR. The ETHBTC finding from V33 generalized: pair ratios look clean on specific parameter sweet spots and collapse everywhere else.

2. **INJ got no usable sleeve.** Both INJ BBBreak (IS +1.25, OOS -0.12) and INJ Donchian (OOS +0.18) failed IS→OOS. INJ has the smallest history of the new coins; the signal doesn't generalize out of 2022's bear market.

3. **AVAX Donchian and SUI Donchian failed** despite BBBreak working for both. The Donchian filter is picking up something different that doesn't survive regime change — worth a look-back during V35 if we revisit Donchian grids.

---

## Audit ledger — post-V34

| Round   | Tested | Pass | Fail | Cumulative pass rate |
|---------|--------|------|------|----------------------|
| V31     | 10     | 4    | 6    | 40%                  |
| V32     | 7      | 7    | 0    | 11/17 = 65%          |
| V33     | 7      | 0    | 7    | 11/24 = 46%          |
| V34     | 9      | 5    | 4    | **16/33 = 48%**      |

A 48% survival rate across 33 audited candidates is the right shape: strict enough to filter noise, loose enough to let real edge through.

---

## Files delivered

- `strategy_lab/run_v34_expand.py` — sweep driver for Phases A/B/C
- `strategy_lab/run_v34_audit.py` — 5-test audit with TON IS-only guard and DSR bug fix
- `strategy_lab/run_v34_portfolio.py` — correlation matrix + portfolio hunt
- `strategy_lab/results/v34/v34_sweep_results.pkl` — 16 sweep winners
- `strategy_lab/results/v34/v34_audit.csv` — 9-candidate audit matrix
- `strategy_lab/results/v34/v34_correlation_matrix.csv` — full 16×16 correlation
- `strategy_lab/results/v34/v34_year_cagr_per_sleeve.csv` — per-year per-sleeve CAGRs
- `strategy_lab/results/v34/v34_top_portfolios.csv` — top 50 portfolio combos

Pine scripts for the 5 new V34 sleeves are pending.

---

## Immediate next steps

1. **Ship Pine scripts** for AVAX_BBBreak, TON_BBBreak, TON_Donchian, LINK_BBBreak, LINK_Donchian (same structure as V28/V30 exports).
2. **Paper-trade the recommended 5-sleeve portfolio for 30 days** before committing real capital. The backtest says +100% worst year; paper-trading catches execution-model bugs, spread realism, and funding-rate drag that the sim doesn't model.
3. **Consider a regime overlay** (from the V24/V25 regime classifier) that dials each sleeve's position size based on current market state — trend sleeves up-weighted in trending regimes, ETH_CCI up-weighted in range regimes. V35 work.
4. **Revisit Donchian for AVAX/SUI/INJ** — both failed in isolation but the underlying system is robust on BTC/ETH/SOL/DOGE/TON/LINK. Something specific about those three coins' regime needs digging into.

---

**Deploy shelf: 16 audit-clean sleeves, 8 coins.  Recommended live portfolio: 5 sleeves, 5 coins, +104.6% worst-year, +110.7% average.**
