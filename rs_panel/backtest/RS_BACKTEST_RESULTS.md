# ALT/BTC Relative-Strength — Backtest Results

_Binance daily spot, 2023-09-13 -> 2026-06-08  (1000 days, 37 coins). Causal (signal_t -> return t..t+1). Cost 8.0bps round-trip on turnover. 70/30 time split. Standalone — not linked to any live/HL strategy._

## Strategy forms
- **ls** = long top-K / short bottom-K perps, dollar-neutral (RS factor, market-neutral)
- **vsbtc** = long top-K alts, funded short BTC (return measured in BTC terms)
- **long** = long-only top-K alts (carries market beta)

## Top 15 configs by OUT-OF-SAMPLE Sharpe (test split)

| form | sig | side | freq | K | shp_tr | shp_te | ann_te | dd | turn |
|---|---|---|---|---|---|---|---|---|---|
| ls | mom14 | contra | d | 3 | 0.37 | 2.12 | 3.38 | -0.82 | 1.07 |
| ls | mom14 | contra | d | 8 | 0.53 | 2.12 | 1.28 | -0.52 | 0.80 |
| ls | score2 | contra | d | 8 | 1.10 | 2.05 | 1.04 | -0.33 | 0.29 |
| ls | score2 | contra | wk | 8 | 1.35 | 1.98 | 0.94 | -0.35 | 0.09 |
| ls | mom14 | contra | d | 5 | 0.95 | 1.80 | 1.51 | -0.57 | 0.92 |
| ls | mom14 | contra | wk | 3 | 0.36 | 1.54 | 1.69 | -0.75 | 0.37 |
| ls | mom14 | contra | wk | 8 | 0.56 | 1.25 | 0.58 | -0.54 | 0.29 |
| ls | mom30 | contra | d | 5 | 1.31 | 1.16 | 0.68 | -0.41 | 0.63 |
| ls | mom14 | contra | wk | 5 | 0.70 | 1.12 | 0.66 | -0.57 | 0.33 |
| vsbtc | mom14 | contra | d | 3 | 0.45 | 0.95 | 0.66 | -0.85 | 0.46 |
| ls | mom90 | contra | wk | 3 | -0.12 | 0.75 | 0.30 | -0.83 | 0.14 |
| ls | mom60 | contra | d | 5 | 0.24 | 0.65 | 0.24 | -0.62 | 0.45 |
| ls | score2 | contra | wk | 5 | 1.24 | 0.60 | 0.20 | -0.45 | 0.12 |
| ls | score2 | contra | d | 5 | 0.87 | 0.56 | 0.18 | -0.56 | 0.37 |
| ls | mom30 | contra | wk | 3 | 1.25 | 0.54 | 0.08 | -0.70 | 0.26 |

## Verdict: NO robust deployable edge (yet) — looks great, fails rigor

The top of the table is seductive (OOS Sharpe ~2) but every config that scores well fails the smell tests:

1. **The panel's own thesis (momentum) does NOT work.** Every high-OOS row is **`contra`** = mean-reversion
   (long the *weak* alts, short the *strong*). Buying relative strength (the dashboard's "6/6") shows **no** OOS
   edge. So as a literal "long the leaders" strategy: dead.
2. **OOS ≫ in-sample = regime luck, not edge.** Best row: train Sharpe **0.37**, test **2.12**. A real edge is
   stable across both; an edge that only appears in the last 30% of the sample is the test window's regime
   (2025-09→2026-06 favored alt/BTC mean-reversion), not a law.
3. **Only 21% of 180 configs are OOS-positive, 9% clear 0.5.** With a 180-config grid, a handful of Sharpe-2
   rows is exactly what pure noise + multiple testing produces. The top row is the luckiest die, not a signal.
4. **Drawdowns −52% to −82%** on the "best" configs. Uninvestable even if the Sharpe were real.
5. **Survivorship + costs + funding.** Only currently-listed coins (delisted losers excluded → upward bias).
   Daily contrarian runs ~100% turnover; real HL fills/slippage/funding would eat more than the 8bps modeled.

**Bottom line:** the RS panel is a strong **monitor**, but RS-rank is **not a standalone systematic edge** on this
data. Do **not** deploy any row above.

## If you want to pursue it honestly (next steps)
- **Pre-register ONE hypothesis** before looking again (e.g. `ls / score2 / contra / weekly / K=8` — lowest
  turnover, DD −35%, train+test both >0) and judge only that, OOS.
- **DSR / CPCV** (the `ml4t` toolkit already installed) on the single chosen config — the project's standard for
  "is this Sharpe real or selection?" The 387k-scalp-selectors precedent (HANDOFF_2026_06_04) died under DSR;
  expect the same here unless one config is special.
- **Longer history + survivorship-free universe** (Binance Vision back to listing for delisted names too).
- **Real costs:** HL taker + funding + slippage per name, not flat 8bps.
- **Regime-condition it:** the contrarian signal may only pay in chop/down-trend BTC — gate by BTC regime and
  re-test rather than trade it unconditionally.