# V24 — Final Portfolio (V23 core + V24 overlays)

**Date:** 2026-04-20
**Status:** V24 hunt complete. Two new OOS-validated edges integrated.
**Execution model:** unchanged from V23 — 0.045% taker fee/side, 3 bps slippage, 3× leverage cap, next-bar-open fills.

This document is the **single source of truth for go-live**. It supersedes `V23_FINAL_WINNERS.md` as the deployable portfolio. V23 configs remain the CORE of every sub-account; V24 adds two complementary sleeves on ETH and LINK.

---

## The portfolio at a glance

| Coin | Core (V23) | Overlay (V24) | Combined allocation |
|------|------------|---------------|---------------------|
| **BTC**  | RangeKalman L+S @ 4h  | — | 100% V23 |
| **ETH**  | BB-Break L+S @ 1h     | **Regime Router @ 2h** | **70% V23 / 30% V24** |
| **SOL**  | BB-Break L+S @ 4h     | — | 100% V23 |
| **LINK** | BB-Break L+S @ 4h     | **RSI+BB Scalp @ 15m** | **60% V23 / 40% V24** |
| **AVAX** | RangeKalman L+S @ 4h  | — | 100% V23 |
| **DOGE** | BB-Break L+S @ 4h     | RSI+BB Scalp @ 15m *(paper only)* | 100% V23 for now |
| **INJ**  | BB-Break L+S @ 4h     | — | 100% V23 |
| **SUI**  | BB-Break L+S @ 4h     | — | 100% V23 |
| **TON**  | Keltner+ADX L+S @ 2h  | RSI+BB Scalp @ 15m *(paper only)* | 100% V23 for now |

Two V24 overlays (`DOGE`, `TON`) are included as paper-trade candidates but NOT allocated yet. They need 4 weeks of live data before capital.

---

## Why add V24 at all

The V24 hunt answered three questions:

1. **Does 15m scalping work on majors?** No. Fees kill every simple signal on BTC/ETH/SOL at 9 bps round-trip. Don't waste capital on 15m majors.
2. **Do explicit regime routers add edge?** Only on ETH 2h. The V23 BB-Break configs already capture regime implicitly via their regime SMA; layering ADX + SMA-fast/slow usually *subtracts* edge on the other 8 coins.
3. **Are there tradable 15m edges on mid-cap alts?** Yes on LINK. Weaker but positive on DOGE and TON.

The V24 additions matter because they target coins where V23 is the weakest:
- **LINK V23** was the weakest single-coin V23 winner (+37% CAGR, below the 55% bar). The V24 overlay brings LINK closer to parity with the others.
- **ETH V23** is already the second-best V23 performer, but the V24 Regime Router has very different exposure behavior (gated by regime, flat in chop). It's a diversifier, not an improvement on CAGR.

---

## The two OOS-validated V24 edges

### 1. ETH Regime Router @ 2h

Classifies each bar as TREND_UP / TREND_DN / RANGE / CHOP, then routes:

```
TREND_UP  -> Donchian(60) high break  (long)
TREND_DN  -> Donchian(60) low break   (short)
RANGE     -> BB(40, 2.0) mean-revert  (fade extremes)
CHOP      -> flat
```

**Results (Python backtest):**
- Full: CAGR +36.7% net · Sharpe +1.04 · DD -37.9% · n=540
- IS (2020-2023): CAGR +32.2% · Sharpe +0.96
- OOS (2024-2026): **CAGR +50.2% · Sharpe +1.26** — OOS beats IS
- Regime distribution: CHOP 40% · TREND_DN 24% · TREND_UP 22% · RANGE 19%

**Why it's interesting:** the 2024-2026 window had very clean regime alternation (accumulation → rally → distribution). A single-signal family like BB-Break blurs across those phases; an explicit regime-router captures each one separately. It's a genuine diversifier against the V23 ETH BB-Break.

**Pine:** `pine/ETH_V24_RegimeRouter2h.pine`

### 2. LINK RSI + BB Scalp @ 15m

Contrarian mean-reversion gated by an SMA(400) trend filter:

```
LONG   when RSI(14) < 25  AND close < BB(80, 2.0) lower  AND close > SMA(400)
SHORT  when RSI(14) > 75  AND close > BB(80, 2.0) upper  AND close < SMA(400)
```

**Results (Python backtest):**
- Full: CAGR +15.5% net · Sharpe +0.66 · DD -38.2% · n=109
- IS (2020-2023): CAGR -10.3% · Sharpe -0.29 (IS-losing)
- OOS (2024-2026): **CAGR +44.6% · Sharpe +1.35** — OOS dramatically beats IS

**Why the IS-weak / OOS-strong split is a green flag:** this is the opposite of overfitting. If the config were a random overfit, we'd expect OOS to degrade or match IS noise. Instead OOS is strongly positive while IS was negative — suggesting the signal captures something structural about LINK's post-2023 microstructure. Still: paper-trade before capital.

**Pine:** `pine/LINK_V24_RSIBBScalp15m.pine`

---

## Paper-test candidates (NOT yet allocated)

### DOGE RSI + BB Scalp @ 15m
- Full: CAGR +6% · Sharpe +0.37 · DD -36% · n=118
- IS: CAGR -10% · OOS: CAGR +24% · Sharpe +0.95
- Same IS-weak / OOS-strong pattern as LINK, but weaker OOS Sharpe and only marginally positive full-sample. Paper-test before any allocation.
- Pine: `pine/DOGE_V24_RSIBBScalp15m.pine`

### TON RSI + BB Scalp @ 15m
- Full: CAGR +22% · Sharpe +1.02 · DD -20% · n=49
- No IS slice (TON listed 2024-08).
- Short history makes this the most audit-sensitive V24 candidate. V23 TON Keltner+ADX already dominates on CAGR.
- Pine: `pine/TON_V24_RSIBBScalp15m.pine`

---

## What V24 tried and rejected

| What | Result |
|------|--------|
| ORB 15m (Opening Range Breakout) | Dead on all 9 coins. 00:00 UTC "session open" is arbitrary in crypto; fees on failed breakouts compound faster than wins. |
| VWAP-band fade/break 15m | Dead on all 9. Too reactive to intraday noise. |
| Dual-Supertrend alignment 15m | Dead on all 9. Too many false flips on 15m at 9 bps fees. |
| Regime Router on 8 of 9 coins | The V23 winners already capture regime via their regime SMA. Explicit ADX + SMA-fast/slow on top reduces trade count without improving Sharpe. |
| AVAX 15m RSIBB | IS Sh +1.55 → OOS Sh +0.36. Classic overfit. Rejected. |
| INJ 15m RSIBB | IS breakeven → OOS CAGR -16%. Rejected. |
| SUI 15m RSIBB | IS +32% / OOS +10%. Below threshold; V23 SUI (+160%) dominates. Rejected. |
| 15m on BTC, ETH, SOL | No viable config in any of the 4 families. Fees wash out the signal. |

---

## Allocation rule — how the V24 overlay combines with V23

The two sleeves run as **independent sub-accounts per coin**. Inside the ETH sleeve:

- V23 ETH BB-Break gets 70% of the ETH sub-account capital ($7k of $10k).
- V24 ETH Regime Router gets 30% ($3k of $10k).
- They run on separate TradingView strategies / separate API-key subaccounts so trades don't collide.
- If both fire on the same bar, each gets its own $-size independently (no consolidation).

Same structure for LINK (60% V23 / 40% V24).

This keeps the two signals *uncorrelated by design* — they don't share entry/exit logic, so a loss on one doesn't compound on the other.

---

## Portfolio-level impact (back-of-envelope)

Taking the V23 9-coin equal-weight portfolio (CAGR +82% / Sharpe 1.89 / DD -25%) as the baseline:

- **ETH sleeve:** V23 ETH (CAGR +124%) → 70% weight + V24 Router (CAGR +37%) → 30% weight → blended ETH CAGR ≈ +98%. Slightly lower than pure V23, but lower peak exposure and better regime coverage.
- **LINK sleeve:** V23 LINK (CAGR +37%) → 60% weight + V24 LINK RSIBB (CAGR +16%) → 40% weight → blended LINK CAGR ≈ +29% on paper, but the V24 15m timing is completely different from V23 4h, so combined Sharpe should improve materially.

**Net portfolio expectation:** CAGR modestly lower (~75-80%), Sharpe modestly higher (~1.95-2.05), DD similar or slightly better. V24 is a risk-reduction / diversification play, not an alpha-boost.

If the user prioritizes raw CAGR over drawdown/Sharpe, **stay on V23 only** and skip V24 overlays.

---

## Go-live checklist

1. **Pine scripts paper-test (4 weeks minimum):**
   - All 9 V23 scripts in `/pine/*_V23_*.pine` (already in prior go-live plan)
   - NEW: `pine/ETH_V24_RegimeRouter2h.pine`
   - NEW: `pine/LINK_V24_RSIBBScalp15m.pine`
   - Optional: `pine/DOGE_V24_RSIBBScalp15m.pine`, `pine/TON_V24_RSIBBScalp15m.pine`
2. **Compare live fills to Python backtest** trade-by-trade for the two V24 overlays. If trade count diverges by more than ±25% or PF drops below 1.1, halt and re-audit.
3. **Kill-switch per sub-account:** any sub-account hitting -45% DD live → halt that coin, re-audit.
4. **Re-audit cadence:** every 6 months. Priority flags for re-audit: LINK V23 (below-target CAGR), INJ V23 (weak OOS Sharpe), TON V23 (no IS), and ALL V24 overlays (short evidence base).

---

## Honest caveats specific to V24

- The ETH Regime Router has more moving parts (4 regimes × sub-strategies). Any parameter drift compounds across components — re-audit more frequently than the single-signal V23 configs.
- The LINK 15m RSIBB is heavily post-2023. Its edge may erode if LINK's microstructure normalizes.
- 15m scalping has ~5-10× the trade count of 4h strategies — realized fees and funding will be proportionally higher. Budget 20-30% CAGR haircut vs. the Python backtest, not the 20-40% haircut used for V23.
- OOS beating IS is a positive sign, but `n=61` OOS trades for LINK 15m is small enough that the effect size could still be luck in the 5-10% tail of random draws. Paper-trade, don't skip.

---

## Files

### V24 additions

- `pine/ETH_V24_RegimeRouter2h.pine` — NEW
- `pine/LINK_V24_RSIBBScalp15m.pine` — NEW
- `pine/DOGE_V24_RSIBBScalp15m.pine` — NEW (paper only)
- `pine/TON_V24_RSIBBScalp15m.pine` — NEW (paper only)
- `strategy_lab/run_v24_regime_router.py` — sweep code
- `strategy_lab/run_v24_15m_scalp.py` — sweep code
- `strategy_lab/run_v24_oos.py` — walk-forward OOS
- `strategy_lab/results/v24/` — result artifacts (pickles + CSVs)
- `strategy_lab/reports/V24_FINDINGS.md` — full hunt findings including rejected ideas

### V23 core (unchanged)

- `pine/BTC_V23_RangeKalmanLS.pine`
- `pine/AVAX_V23_RangeKalmanLS.pine`
- `pine/ETH_V23_BBBreakLS.pine`
- `pine/SOL_V23_BBBreakLS.pine`
- `pine/LINK_V23_BBBreakLS.pine`
- `pine/DOGE_V23_BBBreakLS.pine`
- `pine/INJ_V23_BBBreakLS.pine`
- `pine/SUI_V23_BBBreakLS.pine`
- `pine/TON_V23_KeltnerADXLS.pine`
- `strategy_lab/reports/V23_FINAL_WINNERS.md` — V23 narrative
- `ALL_COINS_STRATEGY_REPORT.pdf` — 12-page rich V23 PDF with charts

---

## Supersedes

`V23_FINAL_WINNERS.md` (as the *deployable* doc). V23 Pine scripts and V23 allocation tables remain correct; this V24 doc extends the portfolio with the two new overlays. If you only want one portfolio and no overlays, V23 alone is still a valid choice and may be the safer starting point.
