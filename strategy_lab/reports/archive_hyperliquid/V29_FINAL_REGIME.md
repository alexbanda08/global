# V29 — Trend-Grade, Lateral-Market, Regime-Switch

**Directive:** "test follow trend grade trade when lateral market, etc etc,
be creative and continue to test."

**Finding:** Three new families added to the catalog, all OOS-validated.
The biggest win is **Lateral_BB_Fade** — a range-market mean-reversion
strategy that passes OOS on 7 of 9 coins, with **OOS Sharpe above IS
Sharpe on every one of those 7**. In plain English: the 2024-2026 market
has been more range-bound than 2020-2023, and this strategy got stronger
when regime shifted. That's a rare signature and deserves a slot in the
portfolio.

## The three V29 families

### 1. Trend_Grade_MTF — "trade trend only when the trend is graded A/B"

Rather than just "is close > EMA(200)?", we compute a grade 0-4 from
four independent signals and require the grade to clear a threshold:

- **+1** 4h EMA(50) slope-up over the last 20 bars
- **+1** 1D EMA(50) > 1D EMA(200)  (the classic golden-cross regime)
- **+1** 1h close > 1h EMA(200)     (local trend intact)
- **+1** 1h ADX(14) > adx_min       (trendiness strong)

Entry fires only when grade ≥ threshold AND RSI(14) dips below rsi_lo
then pops back up (long), or pops above rsi_hi then falls back down
(short). The pullback requirement stops us from chasing extended moves
right before a reversal — it's "wait for the bounce while the grade is
still up."

Causal HTF: in Python, `resample("1D", label="right", closed="left")`.
In Pine, `request.security(..., "D", ...)` with default `barmerge.lookahead_off`.

### 2. Lateral_BB_Fade — the NEW headline edge

The range-market strategy we didn't have. Two-gate regime detector:

- **ADX(14) < adx_max** — no trend is in force
- **BB-width < `bw_q` quantile over the last `bw_lb` bars** — the range
  is compressed, not expanding

When both are true, we fade band-touches back toward the middle:

- Long when close crosses up through the lower Bollinger band.
- Short when close crosses down through the upper Bollinger band.

Exits: standard ATR TP/SL/trail. No middle-band target — we let the
winners trail out via ATR, which tends to catch the fast reversion most
of the time and also catches the occasional multi-ATR bounce.

### 3. Regime_Switch — one script, two modes, ADX-decided

A single strategy that trades differently based on ADX:

- **ADX > adx_hi AND close > EMA(regime)** → Donchian(N) breakout-up long
- **ADX > adx_hi AND close < EMA(regime)** → Donchian(N) breakout-down short
- **ADX < adx_lo**                         → BB(20, 2) fade to mid-band
- **Between adx_lo and adx_hi**            → stay flat (regime ambiguous)

The "flat in between" gate is the whole point: most losses come from
uncommitted markets, and this strategy simply refuses to trade them.

---

## OOS audit — full per-coin table

Split: IS = 2020-01 to 2023-12, OOS = 2024-01 to 2026-04. Verdict rule:
`OOS Sh ≥ 0.5 × max(IS Sh, 0.1)`.

**16 of 24 candidates pass** — 67% pass rate, above our V26/V27 rates.

| Sym | Family | TF | IS n | IS Sh | OOS n | OOS Sh | OOS CAGR | OOS DD | Verdict |
|-----|--------|----|------|------:|-----:|-------:|---------:|-------:|:-------:|
| SUI | Lateral_BB_Fade | 1h | 21 | -0.16 | 63 | **+1.73** | +104.7% | -26.8% | **PASS** |
| ETH | Lateral_BB_Fade | 4h | 44 | +0.99 | 24 | **+1.66** | +47.0%  | -16.1% | **PASS** |
| SOL | Lateral_BB_Fade | 4h | 71 | +0.42 | 48 | **+1.65** | +66.9%  | -26.2% | **PASS** |
| TON | Trend_Grade_MTF | 4h |  0 |  n/a  | 36 | **+1.62** | +121.5% | -22.8% | **PASS** |
| AVAX| Lateral_BB_Fade | 4h | 28 | +0.68 | 20 | **+1.45** | +34.8%  | -18.1% | **PASS** |
| LINK| Lateral_BB_Fade | 4h | 14 | +0.47 | 13 | **+1.26** | +22.8%  | -16.3% | **PASS** |
| INJ | Lateral_BB_Fade | 4h | 26 | +0.72 |  8 | **+1.22** | +17.8%  | -18.2% | **PASS** |
| SUI | Regime_Switch   | 4h | 17 | +0.77 | 71 | **+1.04** | +42.3%  | -40.6% | **PASS** |
| BTC | Lateral_BB_Fade | 4h | 46 | +0.80 | 27 | **+1.04** | +25.3%  | -27.7% | **PASS** |
| LINK| Trend_Grade_MTF | 4h | 53 | +0.35 | 17 | **+1.01** | +20.6%  | -23.6% | **PASS** |
| INJ | Trend_Grade_MTF | 4h | 47 | +1.14 | 31 | +1.00     | +25.3%  | -29.5% | **PASS** |
| BTC | Regime_Switch   | 4h |129 | +0.98 | 76 | +0.75     | +16.7%  | -32.4% | **PASS** |
| ETH | Regime_Switch   | 4h |136 | +1.34 | 86 | +0.73     | +16.2%  | -32.1% | **PASS** |
| AVAX| Trend_Grade_MTF | 4h |127 | +0.57 | 76 | +0.73     | +14.7%  | -37.4% | **PASS** |
| SOL | Trend_Grade_MTF | 4h |100 | +1.08 | 66 | +0.55     | +12.8%  | -37.0% | **PASS** |
| INJ | Regime_Switch   | 4h |122 | +0.43 | 84 | +0.40     |  +6.2%  | -23.5% | **PASS** |
| ETH | Trend_Grade_MTF | 4h |159 | +1.64 | 84 | +0.70     | +13.8%  | -23.2% | FAIL (bar 0.82) |
| SOL | Regime_Switch   | 4h |121 | +0.99 | 70 | +0.36     |  +4.8%  | -32.7% | FAIL (bar 0.49) |
| DOGE| Lateral_BB_Fade | 4h | 67 | +1.70 | 42 | +0.20     |  +0.3%  | -41.4% | FAIL (bar 0.85) |
| BTC | Trend_Grade_MTF | 4h | 22 | -0.75 | 15 | -0.62     |  -6.7%  | -24.6% | FAIL |
| DOGE| Trend_Grade_MTF | 4h | 29 | -0.84 |  9 | -0.33     |  -2.9%  | -13.3% | FAIL |
| SUI | Trend_Grade_MTF | 4h | 10 | -0.68 | 26 | -1.05     | -14.0%  | -34.2% | FAIL |
| TON | Regime_Switch   | 4h |  0 |  n/a  | 55 | -1.04     | -28.6%  | -42.9% | FAIL |
| TON | Lateral_BB_Fade | 1h |  0 |  n/a  | 30 | -1.47     | -23.4%  | -39.9% | FAIL |

Notable: **every single coin on which Lateral_BB_Fade passes shows OOS
Sharpe ≥ IS Sharpe.** That's 7/7. For SUI it's IS -0.16 → OOS +1.73
(regime flipped entirely after listing); for SOL, IS +0.42 → OOS +1.65;
for ETH, +0.99 → +1.66. This is the signature of a strategy that's
better-suited to the recent regime than the old one — the opposite of
what we'd expect from overfitting.

---

## Pine scripts shipped — 14 total

### Lateral_BB_Fade (7 coins)

| File | Coin | TF | Tier | Per-year 2023/24/25 |
|------|------|----|------|---------------------|
| `pine/BTC_V29_LateralBB_4h.pine`  | BTC  | 4h | LIVE CANDIDATE | +15.5 / +109.1 / -9.8 |
| `pine/ETH_V29_LateralBB_4h.pine`  | ETH  | 4h | LIVE CANDIDATE | +14.7 / +112.8 / +22.3 |
| `pine/SOL_V29_LateralBB_4h.pine`  | SOL  | 4h | LIVE CANDIDATE | +38.2 / +69.0 / +120.4 |
| `pine/LINK_V29_LateralBB_4h.pine` | LINK | 4h | LIVE CANDIDATE | -10.8 / -4.0 / +33.9 |
| `pine/AVAX_V29_LateralBB_4h.pine` | AVAX | 4h | LIVE CANDIDATE | +12.3 / +63.6 / +35.9 |
| `pine/INJ_V29_LateralBB_4h.pine`  | INJ  | 4h | LIVE CANDIDATE | +0.3  / -7.2 / +46.9 |
| `pine/SUI_V29_LateralBB_1h.pine`  | SUI  | 1h | PAPER FIRST    | n/a / +105 (huge) |

### Trend_Grade_MTF (4 coins)

| File | Coin | TF | Tier |
|------|------|----|------|
| `pine/INJ_V29_TrendGradeMTF_4h.pine`  | INJ  | 4h | LIVE CANDIDATE |
| `pine/LINK_V29_TrendGradeMTF_4h.pine` | LINK | 4h | LIVE CANDIDATE |
| `pine/AVAX_V29_TrendGradeMTF_4h.pine` | AVAX | 4h | LIVE CANDIDATE |
| `pine/TON_V29_TrendGradeMTF_4h.pine`  | TON  | 4h | PAPER FIRST    |

### Regime_Switch (3 coins)

| File | Coin | TF | Tier |
|------|------|----|------|
| `pine/BTC_V29_RegimeSwitch_4h.pine` | BTC | 4h | LIVE CANDIDATE |
| `pine/ETH_V29_RegimeSwitch_4h.pine` | ETH | 4h | LIVE CANDIDATE |
| `pine/SUI_V29_RegimeSwitch_4h.pine` | SUI | 4h | PAPER FIRST    |

Each Pine matches its Python parent parameter-for-parameter. Same 0.045%
commission, 3 bps slippage, 3× leverage cap, ATR risk sizing.

---

## Portfolio effect — does V29 unseat V28's P2?

We re-ran the V28 portfolio hunt with V29's 16 OOS-passing sleeves added
to the pool. The yearly-rebalanced-equal-weight blends that clear
+100%/yr in each of 2023, 2024, 2025 now include many more combinations.

**Highlights from the refreshed top-of-leaderboard:**

| Blend | 2023 | 2024 | 2025 | Min-year |
|-------|-----:|-----:|-----:|---------:|
| **P2 (V28) — SUI BBBreak + SOL BBBreak + ETH V27 Donch** | +129.2 | +147.2 | +189.9 | **+129.2%** |
| SUI BBBreak + SOL BBBreak + ETH **Lateral_BB_Fade** | +139.3 | +124.0 | +158.3 | +124.0% |
| SUI BBBreak + SOL BBBreak + BTC **Lateral_BB_Fade** | +139.6 | +122.8 | +147.6 | +122.8% |
| SUI BBBreak + SOL BBBreak + DOGE BBBreak (3x V23) | +148.2 | +122.2 | +185.3 | +122.2% |
| 4-sleeve: SOL+DOGE+SUI BBBreak + BTC Lateral | +115.0 | +118.9 | +136.5 | +115.0% |
| 4-sleeve: SOL+DOGE+SUI BBBreak + ETH Lateral | +114.8 | +119.9 | +144.6 | +114.8% |

**V28 P2 is still the peak min-year CAGR (+129%).** But V29 does two
things:

1. **Provides alternate 3-sleeve blends** that clear 100% in all 3 years
   using Lateral_BB_Fade as the third leg. That's useful if you don't
   want the concentration of V27 ETH Donch (which leans heavily on
   2024's +183% and stumbles in 2023 with -16%).
2. **Enables 4-sleeve blends at 110-120% min-year** that trade off some
   peak return for clear reduction in single-sleeve concentration risk.
   With 4 sleeves at equal weight, the worst-case hit from one sleeve
   going to -50% DD is ~12.5% on the portfolio, vs. ~17% with 3 sleeves.

**Recommendation: P2 remains the headline portfolio. Consider P2' (P2
+ BTC or ETH Lateral_BB_Fade at 25% weight) as a variant that diversifies
away some V23-BBBreak family risk at the cost of ~10pts/yr CAGR.**

---

## What this round tells us

### The 2024+ crypto regime is more range-bound than 2020-2023

Lateral_BB_Fade was designed to exploit ADX-low, BB-width-compressed
regimes. It passes OOS on 7 coins with OOS Sh above IS Sh. That's a
direct reading of what kind of market we've been in: less trending,
more choppy/range. The fact that single-strategy winners from V27
(ETH Donch) degrade from IS Sh +0.93 to OOS +1.62 might look like it
contradicts this, but it doesn't: ETH had one massive trending move in
2024 that dominates the Sharpe calc. Remove that year and the rest
of the OOS window is more lateral than trending.

### Trend-grading is more useful as a FILTER than as an entry rule

Trend_Grade_MTF with thr=3 or 4 produced a lot of "no trade" periods.
It's a quality gate: it fails to find many opportunities on BTC or DOGE
(which haven't had clean trends in this period) but passes on INJ, AVAX,
LINK and TON. The lesson: grading probably belongs INSIDE other
strategies as a filter, not as a standalone entry trigger. Next round
could try "V23 BBBreak + Trend_Grade ≥ 2 filter" as a trade-selection
layer.

### Regime_Switch is decent but not the killer we hoped

The ADX-gated mode switch works for BTC, ETH, SUI (positive OOS) but
doesn't dominate any coin. Reality: trying to be good at two opposite
regimes in one strategy usually means you're mediocre at both. The
V28 P2 portfolio handles regime switching BETTER by allocating separate
capital to dedicated trend-followers (ETH Donch) and mean-reverters
(SUI/SOL BBBreak, V29 Lateral sleeves).

---

## Honest caveats

1. **OOS outperforming IS is unusual and deserves scrutiny.** The V29
   Lateral_BB_Fade result — 7 of 7 passing coins showing OOS Sh > IS Sh
   — could mean:
   - (a) Real regime shift: the 2024+ market is genuinely more favorable
     for range mean-reversion. Plausible; BTC dominance shifted, alt-
     season churn, pre-halving consolidations all support this.
   - (b) Lookahead leak I missed. I've audited the code — BB-width
     uses only past data, ADX uses Wilder's smoothing which is causal,
     percentile is rolling. The `bw_lb` scaling is correct.
   - (c) Chance. At 7 coins, this is not a huge sample. If we'd seen 5/9
     pass and 3 failures, the conclusion would be much weaker.
   I believe it's (a) + some noise, but the right response is to
   PAPER-TRADE first and watch whether OOS Sh holds in live fills.

2. **DOGE Lateral_BB_Fade failed OOS hard** (IS +1.70 → OOS +0.20).
   This is the classic failure mode of range strategies: DOGE had 2
   massive breakout moves in 2024 that blew through every BB fade. If
   you run Lateral_BB_Fade, SKIP DOGE — or only fade on 1h (not 4h)
   where stops protect you better.

3. **DD on 4h is still meaningful.** Lateral_BB_Fade DD ranges from -16%
   (ETH) to -43% (SOL). The -43% on SOL is driven by 2022, which is
   consistent with what we see everywhere: bear markets that break
   compression regimes whipsaw these strategies badly.

4. **Thin-data coins (SUI/TON) remain PAPER FIRST.** SUI listed May 2023
   so has ~7 months of IS — not really a valid in-sample. TON has no IS
   data at all. Treat these as OOS-only hypotheses until 1+ year of
   live performance confirms.

---

## Files

- `strategy_lab/run_v29_regime.py` — sweep script for all 3 families
- `strategy_lab/run_v29_oos.py` — IS/OOS audit
- `strategy_lab/run_v29_portfolio.py` — V29+V28 portfolio hunt
- `strategy_lab/results/v29/v29_regime_results.pkl` — full sweep results
- `strategy_lab/results/v29/v29_summary.csv` — full-period summary
- `strategy_lab/results/v29/v29_oos.csv` — 24-row OOS audit table
- `strategy_lab/results/v29/v29_portfolio_100pct.csv` — all blends ≥100%/yr
- `strategy_lab/results/v29/v29_portfolio_top30.csv` — top-30 by worst-year
- `strategy_lab/pine/*_V29_*.pine` — 14 Pine scripts

## Catalog status after V29

| Round | Families | OOS-passing winners shipped |
|-------|----------|---------------------------|
| V23   | 3 (BBBreak, RangeKalman, KeltnerADX) | 9 per-coin |
| V24   | 3 (RSIBB scalp, ORB, regime router)  | 3 |
| V25   | 4 (Squeeze, Seasonality, Sweep, MTFConf) | 2 (after HTF-leak fix) |
| V26   | 6 (LiqSweep, OB, MSB, Engulf, Div, Squeeze) | 4 (after OB-leak fix) |
| V27   | 4 (TrendPullback, HTF_Donch, VWAP_Fade, Daily_EMA_X) | 6 |
| V28   | (no new strategies — portfolio construction) | 1 blended |
| **V29** | **3 (Trend_Grade_MTF, Lateral_BB_Fade, Regime_Switch)** | **14 Pine** |

**Total shipped Pine:** ~60 strategies across 9 coins.
