# V26 Price-Action Round — Final Report

**Directive:** "now research more, see some liquidity sweep strategies, price action etc etc try more"

**Scope:** 6 price-action families × 9 coins × 2 TFs (30m, 1h) =
~100 (sym × family × TF) cells, grid-searched over params + exits + risk.
Families: LIQ_SWEEP (swing-pivot sweep), ORDER_BLOCK (ICT-style),
MSB (market-structure break), ENGULF (engulfing + BB + vol), RSI_DIV
(regular divergence at swing pivots), ATR_SQZ (compression → Donchian break).

## Headline: the Order Block family was a mirage

Initial sweep found absurd numbers:
- **BTC OB 1h**: CAGR +240%, Sharpe +1.96, n=1902
- **AVAX OB 30m**: CAGR +7,902%, Sharpe +4.85, n=1872
- **SUI OB 30m**: CAGR +1,453%, Sharpe +3.03, n=1642
- **TON OB 30m**: CAGR +686%, Sharpe +2.61, n=743
- **INJ OB 1h**: CAGR +423%, Sharpe +2.51, n=1076

**ALL of them held OOS.** That was the tell — numbers this extreme that hold
OOS usually mean the signal is inflated by a structural bug, not selection
bias (which OOS would punish).

Root cause: `sig_order_block` detected a bull OB at bar `t` using
`high[t+1..t+lookahead]` to confirm the impulse, then allowed the retest
signal to fire as early as bar `t+1` — **before the impulse had actually
happened in real time.** The simulator was effectively trading with tomorrow's
newspaper.

**Fix:** OB at bar `t` is only visible from bar `t+lookahead` onward.
Re-ran with the fix. Result: **NO VIABLE CONFIG on any of the 9 coins.**
The entire family was a backtest artifact.

This is a useful lesson: any signal that requires looking forward to confirm
a pattern needs a strict causality-delay (shift by lookahead), and numbers
that are "too good" — especially when OOS looks too clean too — deserve a
leak audit before a Pine script.

## Real V26 survivors (OOS-validated, leak-free)

### Tier 1 — Live candidates

#### AVAX V26 ATR Squeeze 1h — STRONGEST V26 WINNER
- **FULL (2020-2026)**: n=142, CAGR +64.3%, Sharpe +1.32, DD -37.3%, PF 1.92
- **IS (2020-2023)**: n=78, Sharpe +1.37
- **OOS (2024-2026)**: n=64, Sharpe +1.27, CAGR +65.3% ← OOS matches IS
- Params: ATR(14) / SMA(ATR,70) < 0.75 + Donchian(20) break + SMA(400) regime
- Exits: TP 10×ATR, SL 2×ATR, Trail 5×ATR, MH 72 bars
- Risk: 5% per trade, 3× lev cap
- Pine: `pine/AVAX_V26_ATRSqueeze1h.pine`

#### TON V26 Liquidity Sweep 1h
- **FULL (effectively OOS only — TON data starts 2023-09)**: n=145, CAGR +50.3%, Sharpe +1.11, DD -43.2%
- **OOS (2024-2026)**: n=145, Sharpe +1.11, CAGR +50.3%
- Signal: swing pivot(5,5) sweep + volume > 1.5×avg + SMA(400) regime
- Exits: TP 10×ATR, SL 2×ATR, Trail 5×ATR, MH 72 bars
- Risk: 3% per trade, 3× lev cap
- Pine: `pine/TON_V26_LiqSweep1h.pine`
- **Caveat**: only 2.3 years of data. Paper-trade first. DD -43.2% is at the cut-off.

### Tier 2 — Paper-only (small samples / weak OOS)

| Symbol | Family | TF | Full n | Full CAGR | Full Sh | OOS Sh | Note |
|---|---|---|---:|---:|---:|---:|---|
| LINK | Engulf_Vol | 1h | 237 | +7.0% | +0.41 | +0.36 | Low return, DD -44.9% at cut-off |
| TON | Engulf_Vol | 1h | 64 | +20.2% | +0.66 | +0.66 | OOS-only. Small sample. |
| DOGE | ATR_Squeeze | 30m | 40 | +11.6% | +0.64 | +0.97 | Small sample, IS n=12. |
| INJ | ATR_Squeeze | 1h | 106 | +10.8% | +0.55 | +0.41 | Weak edge. |
| AVAX | RSI_Divergence | 30m | 51 | +2.9% | +0.28 | +0.79 | Positive but sparse. |
| SOL | RSI_Divergence | 30m | 58 | +9.0% | +0.50 | +1.00 | OOS n=16. |
| ETH | RSI_Divergence | 30m | 65 | -5.5% | -0.43 | +0.30 | IS negative; OOS marginal. |

None of these clear a useful "real edge" bar — keep on the watch list only.

### Tier 3 — Disqualified (look-ahead bug)

All 5 Order_Block configs (BTC, AVAX, SUI, INJ, TON). Do NOT trade.

## Portfolio changes from V25_FINAL_PORTFOLIO.md

Only one meaningful addition: **AVAX V26 ATR Squeeze 1h** joins the AVAX sleeve.

New AVAX sleeve: **V23 / V25 MTFConf / V26 ATR Squeeze = 40/35/25**.

Rationale:
- V23 BB-Break = main edge, always-on.
- V25 MTF Conf = trend-following confirmation.
- V26 ATR Squeeze = uncorrelated timing (only fires after volatility
  compression). Different entry criterion from both V23 and V25, so
  should diversify drawdown clusters.

TON V26 Liq Sweep goes to **paper** for a 3-month observation period
before being added to the TON sleeve (data history too short).

All other V25 portfolio allocations (SOL 70/30, DOGE 70/30, ETH 70/30,
LINK 60/40, BTC/INJ/SUI 100% V23) remain unchanged.

Expected portfolio impact vs V25 baseline:
- AVAX sleeve Sharpe: ~1.5 → ~1.7 (moderately better with 3-way diversification)
- Overall portfolio CAGR: ~+95-100% → ~+98-103%
- Overall portfolio Sharpe: ~2.0-2.1 → ~2.05-2.15 (tiny lift)

## What we learned

1. **Any look-forward indicator needs explicit causality-shift.** ICT-style
   order blocks, inside-bar patterns that need a subsequent impulse, any
   pattern labelled at time t but confirmed only after data from t+k — all
   need to be consumed shifted by k.
2. **"Too good and holds OOS" is suspicious, not reassuring.** Overfitting
   inflates IS and degrades OOS; structural bugs inflate both equally.
3. **ATR compression → directional release is a real, modest edge on AVAX.**
   Consistent with the broader finding (V25 Squeeze family) that AVAX
   responds well to TTM/ATR-squeeze style entries.
4. **Mean-reversion sweeps work better on newer / lower-cap pairs (TON)**
   than on liquid majors (no BTC/ETH LIQ_SWEEP winner), consistent with
   liquidity-sweep thesis — the pattern relies on trapped retail stops
   which are more prevalent in thinner markets.
