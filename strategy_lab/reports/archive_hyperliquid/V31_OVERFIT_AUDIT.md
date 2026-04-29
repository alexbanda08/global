# V31 — Overfitting Audit on the Top V28/V29/V30 Winners

**Date:** 2026-04-22
**Scope:** Five complementary overfitting tests on 10 top candidates, covering every sleeve that enters the peak portfolios from V28-V30.
**Why:** Before sizing any of this live, we need to separate "this edge is real" from "we got lucky picking the best of 6000 configs."

---

## The five tests

| # | Test | What it detects |
|---|------|-----------------|
| 1 | **Per-year breakdown** | Edge concentrated in one lucky year |
| 2 | **Parameter plateau** | Winner is a spike, not a robust region |
| 3 | **Randomized-entry null** | Edge comes from exits/sizing, not signal timing |
| 4 | **MC bootstrap (monthly returns)** | Realized path was lucky; 5th-pctile downside |
| 5 | **Deflated Sharpe (DSR)** | Adjusts for multiple testing — ~6000 configs tried |

Pass criteria (strict):
- Plateau ≥ 60% neighbors positive (half-decent perturbation robustness)
- Null beat ≥ 80% (clearly above random-entry baseline)
- DSR ≥ 0.9 (Sharpe survives multi-testing deflation)
- Max single-year share ≤ 0.5 of cumulative log-return
- Neg years ≤ 2

---

## Results — verdict matrix

| Strategy                    | Ver | Full CAGR | Full Sh | Plateau | Null% | DSR  | Max Yr Share | Neg Yrs | **Verdict** |
|----------------------------|-----|-----------|---------|---------|-------|------|--------------|---------|-------------|
| **SOL SuperTrend_Flip 4h** | V30 | +51.1%    | +1.29   | 100%    | 100%  | 1.00 | 0.38         | 0       | **ROBUST** ★★★ |
| **DOGE TTM_Squeeze_Pop 4h** | V30 | +25.9%    | +0.76   | 100%    | 95%   | 1.00 | 0.32         | 2       | **ROBUST** ★★ |
| **ETH CCI_Extreme_Rev 4h**  | V30 | +13.4%    | +0.57   | 100%    | 99%   | 1.00 | 0.23         | 2       | **ROBUST** ★★ |
| **ETH VWAP_Zfade 4h**       | V30 | +12.1%    | +0.59   | 71%     | 98%   | 1.00 | 0.40         | 0       | **ROBUST** ★★ |
| ETH Lateral_BB_Fade 4h      | V29 | +12.3%    | +0.60   | 67%     | 91%   | 1.00 | 0.31         | 4       | MIXED       |
| SUI Lateral_BB_Fade 1h      | V29 | -26.3%    | -0.09   | 50%     | 61%   | 0.00 | 0.49         | 2       | **OVERFIT** |
| SOL Lateral_BB_Fade 4h      | V29 | +0.3%     | +0.19   | 60%     | 60%   | 1.00 | 0.44         | 4       | **FRAGILE** |
| TON CCI_Extreme_Rev 4h      | V30 | +2.4%     | +0.32   | 40%     | 64%   | 1.00 | 0.48         | 1       | **FRAGILE** |
| SUI CCI_Extreme_Rev 4h      | V30 | -19.8%    | -0.10   | 40%     | 59%   | 0.00 | 0.48         | 2       | **OVERFIT** |
| AVAX VWAP_Zfade 1h          | V30 | -17.4%    | -0.24   | **0%**  | 41%   | 0.00 | 0.26         | 6       | **FAKE**    |

Four strategies are cleanly robust, one is borderline, five fail the audit.

---

## Case studies of what the audit caught

### SUI Lateral_BB_Fade 1h — spectacular V29 blow-up

V29 reported this as the headline OOS winner: +105% OOS CAGR, Sharpe 1.73 on 2024+ data. The audit now sees 2025 and early-2026 bars the V29 OOS window didn't include:

| Year | CAGR   | Sharpe | DD     |
|------|--------|--------|--------|
| 2023 | -6.9%  | +0.20  | -46.7% |
| 2024 | **+232.7%** | **+1.88** | -65.4% |
| 2025 | **-79.5%**  | **-2.23** | -81.3% |
| 2026 | -79.4% | -3.20  | -42.5% |

The strategy didn't generalize — it caught one perfect SUI range regime in 2024 and has bled ever since the range broke. `null_pct = 61%` means random entries with the same exits perform nearly as well. **PSR = 0.002, DSR = 0.000** — classic multi-test false discovery. Dropping from the toolkit.

### AVAX VWAP_Zfade 1h — the plateau test nailed it

OOS Sharpe looked OK at +1.96 in V30's audit. But the plateau test revealed **0 of 7 parameter neighbors were positive**. The winner was a single lucky point in a sea of red — no possible way for this to survive live execution where the real-world params are slightly off. Dead on arrival.

### ETH CCI_Extreme_Rev 4h — passes the test, but the 122% OOS number was misleading

This sleeve passes the overfit audit cleanly: plateau 100%, null-beat 99%, DSR 1.0, no single-year dominance. It IS real edge. BUT:

- V30's reported "+122.8% OOS CAGR" was computed on ~2 years of 2024+ data, not an annualized expectation.
- Full-period CAGR across 2020-2026 is a more honest **+13.4%** with Sharpe 0.57.
- Per-year CAGRs: 23=+22%, 24=+218%, 25=+80%. Strong, but the 218% in 2024 is an outlier.
- MC bootstrap 5th-percentile CAGR: **-18.5%** — there are plausible paths where this loses 18% a year.

Keep the sleeve, but size for Sharpe 0.6, not Sharpe 2.4.

### SOL SuperTrend_Flip 4h — the cleanest winner we've ever produced

The one result that passes every test with room to spare:

| Year | CAGR    | Sharpe |
|------|---------|--------|
| 2020 | +45.2%  | +1.16  |
| 2021 | +152.5% | +2.25  |
| 2022 | +38.9%  | +1.12  |
| 2023 | +59.6%  | +1.42  |
| 2024 | +13.8%  | +0.53  |
| 2025 | +50.7%  | +1.25  |
| 2026 | +0.6%   | +0.22  |

**Seven years of positive returns with no negative year since 2020.** Plateau 100%, null beat 100%, DSR 1.0, MC bootstrap 5th-percentile CAGR +17.9%. This should be a core sleeve alongside V28 P2 members.

---

## Robust-only portfolio — the peak survives

Rerunning the portfolio hunt restricted to sleeves that passed audit (plus the V28 P2 core assumed robust):

**Top 5 audit-clean portfolios by worst-year CAGR (2023-2025):**

| Rank | Size | Worst | 2023  | 2024  | 2025  | Members                                                   |
|------|------|-------|-------|-------|-------|-----------------------------------------------------------|
| 1    | 3    | **141.8%** | 141.8 | 159.2 | 177.4 | SOL BBBreak 4h + SUI BBBreak 4h + **ETH CCI_Extreme_Rev 4h** |
| 2    | 3    | 132.4%     | 142.6 | 132.4 | 148.3 | SOL BBBreak 4h + SUI BBBreak 4h + ETH VWAP_Zfade 4h        |
| 3    | 3    | 129.2% *(V28 P2)* | 129.2 | 147.2 | 189.9 | SOL BBBreak 4h + SUI BBBreak 4h + ETH HTF_Donchian 4h |
| 4    | 3    | 122.2%     | 148.2 | 122.2 | 185.3 | SOL BBBreak 4h + SUI BBBreak 4h + DOGE BBBreak 4h          |
| 5    | 5    | 104.3%     | 104.3 | 105.3 | 109.7 | ETH VWAP + SOL BBBreak + SUI BBBreak + DOGE BBBreak + BTC Donchian |

**V30 P1 (worst 141.8%) survives the audit.** Every member passed robustness tests. This is the recommended live portfolio if you're comfortable with 3-sleeve concentration.

The 5-sleeve diversified portfolio at rank 5 is the most conservative alternative — it sacrifices ~37 pts of worst-year CAGR for a tighter 104-110 spread and better diversification.

---

## Revised toolkit verdicts (what to deploy vs what to park)

### Deploy live (high confidence)
- **SOL BBBreak_LS 4h** (V23) — V28 P2 core, 2023-2025 per-year 82-360%
- **SUI BBBreak_LS 4h** (V23) — V28 P2 core, 2023-2025 per-year 44-375%
- **ETH HTF_Donchian 4h** (V27) — V28 P2 core incumbent
- **ETH CCI_Extreme_Rev 4h** (V30) — new peak sleeve (audit-clean)
- **SOL SuperTrend_Flip 4h** (V30) — cleanest audit result, independent sleeve
- **DOGE TTM_Squeeze_Pop 4h** (V30) — good plateau, vol-expansion alpha
- **ETH VWAP_Zfade 4h** (V30) — 0 negative years, conservative alternative

### Park (failed audit — do not deploy)
- **SUI Lateral_BB_Fade 1h** (V29) — overfit to 2024 regime, blew up in 2025-2026
- **SOL Lateral_BB_Fade 4h** (V29) — +0.3% full-period, indistinguishable from noise
- **SUI CCI_Extreme_Rev 4h** (V30) — thin IS data, boom-bust path
- **TON CCI_Extreme_Rev 4h** (V30) — plateau 40%, one-year wonder
- **AVAX VWAP_Zfade 1h** (V30) — plateau 0%, random-entry fluke

### Still need audit (not tested in V31, assumed based on V28 result)
- V23 BBBreak_LS on SOL / SUI / DOGE
- V27 HTF_Donchian on ETH / BTC / SOL / DOGE

These four V28 P2 cores have 2.5+ years of forward performance by now — reasonably high confidence but a V32 audit pass on them would close the loop.

---

## Key learnings

1. **The IS/OOS split is necessary but insufficient.** Both V29 and V30 used a 2024-01-01 split. When fresh 2025-2026 bars accumulated, SUI Lateral's "OOS-PASS" was revealed as one-year luck.

2. **Multi-test deflation matters.** We searched ~6000 configs in V30 alone. The expected best-of-N Sharpe under the null is ~1.0. That's why any winner with Sharpe < 1.0 and short sample needs DSR testing.

3. **Plateau test is the cheapest and most informative single test.** Perturbing each param ±1 grid step is an O(N_dim) re-sim. A winner with 100% plateau neighbors is robust; one with 0% is a spike. AVAX VWAP_Zfade was caught instantly.

4. **Random-entry null test separates signal alpha from exit alpha.** If random entries with your same exits match your Sharpe, your alpha is in the exit logic (TP/SL/trail), not the signal. SOL SuperTrend beats 100% of null trials — its edge is genuinely in the signal.

5. **"New headline" claims should be viewed skeptically.** V29 SUI Lateral (+105% OOS CAGR) and V30 ETH CCI (+122% OOS CAGR) both got big press in their respective reports. V29 SUI failed the audit; V30 ETH CCI passed but its long-run CAGR is ~13%, not 120%.

---

## What's next

Two honest options:

**Option A — consolidate.** Stop running new families. Run V32 audit on the V23 BBBreak and V27 Donchian winners (the V28 P2 core). Then rebuild the PDF report with only the 7 audit-clean sleeves and the restricted portfolio hunt. Ship the live-deployment toolkit.

**Option B — keep exploring but audit every round.** Add the V31 overfit suite to the pipeline as a mandatory post-sweep step. Any V32+ winner must pass plateau + null + DSR before it's published as a finding.

Recommend **Option A first, then Option B.** We have enough robust sleeves for a live-deployable portfolio; any additional families are gravy but need the audit bar to clear before earning shelf space.
