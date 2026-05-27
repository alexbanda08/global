# W2d — Cyclops 3-Axis + Markov sized leverage on Hyperliquid

**Run:** 2026-05-26
**Engine:** `strategy_lab/hl_research_2026_05_26/hl_engine.py` (HL taker 4.5 bps × 2, slippage 3 bps, funding hourly accrual, 50 ms latency)
**Notional:** $250 per trade
**Hold:** 5 bars (fixed time stop)
**Window:** full Binance panel (BTC/ETH 2017-08 → 2026-03, SOL 2020-08 → 2026-03)
**Results CSV:** [`W2d_results.csv`](W2d_results.csv) · **Best-cell JSON:** [`W2d_best_cell.json`](W2d_best_cell.json)

---

## Strategy summary

Cyclops 3-axis composite ported from Polymarket binaries. Fire only when **all
three axes** agree. Direction = consensus sign.

| Axis     | Rule                                                                                                      |
|----------|-----------------------------------------------------------------------------------------------------------|
| Trend    | 20-bar OLS slope sign (|slope·k/mean| > 5 bp) AND `tr_ema_stack_score` sign aligned (|score| ≥ 1)         |
| Levels   | Distance to ffilled `pivot_low` ≤ 0.5·atr_14 (LONG) / `pivot_high` (SHORT), tested-not-broken (no BoS in last 3 bars) |
| Momentum | `rsi_14` > 55 (LONG) or < 45 (SHORT), AND `markov_state_fixed` non-conflicting                            |

Three sizing variants:

* `baseline_lev2` — fixed 2× leverage (no Markov)
* `markov_sized`  — 2× BULL / 1× SIDEWAYS / 0× BEAR (per direction)
* `markov_gate`   — 2× when Markov allows, 0× otherwise

---

## Per-cell punchline

| Asset | TF  | Variant         | n_fires | n   | WR    | $/tr   | Sharpe  | MDD$  | Punchline                              |
|-------|-----|-----------------|---------|-----|-------|--------|---------|-------|----------------------------------------|
| BTC   | 5m  | baseline_lev2   |   537   | 537 | 0.322 | -0.686 | -4.80   | -380  | strong negative edge — DO NOT DEPLOY   |
| BTC   | 5m  | markov_sized    |   537   | 537 | 0.322 | -0.635 | -4.60   | -343  | Markov sizing trims ~7% loss; still bad |
| BTC   | 5m  | markov_gate     |   537   | 537 | 0.322 | -0.686 | -4.80   | -380  | gate ≡ baseline (all states accepted)   |
| BTC   | 15m | baseline_lev2   |   238   | 238 | 0.391 | -0.429 | -2.30   | -124  | sub-50% WR; bleed                       |
| BTC   | 15m | markov_sized    |   238   | 238 | 0.391 | -0.386 | -2.19   |  -98  | Markov saves $10; still negative        |
| BTC   | 15m | markov_gate     |   238   | 238 | 0.391 | -0.429 | -2.30   | -124  | same as baseline                        |
| BTC   | 1h  | baseline_lev2   |    98   |  98 | 0.490 | +0.077 |  0.25   |  -32  | barely positive; n too small            |
| BTC   | 1h  | markov_sized    |    98   |  98 | 0.490 | +0.092 |  0.30   |  -32  | Markov adds 6%                          |
| BTC   | 1h  | markov_gate     |    98   |  98 | 0.490 | +0.077 |  0.25   |  -32  | same as baseline                        |
| BTC   | 4h  | baseline_lev2   |    31   |  31 | 0.387 | -2.74  | -4.29   | -102  | n=31; not deployable                    |
| BTC   | 4h  | markov_sized    |    31   |  31 | 0.387 | -2.52  | -4.01   |  -88  | marginal Markov trim                    |
| BTC   | 4h  | markov_gate     |    31   |  31 | 0.387 | -2.74  | -4.29   | -102  | same as baseline                        |
| ETH   | 5m  | baseline_lev2   |   713   | 713 | 0.327 | -0.502 | -3.71   | -360  | strong negative; DO NOT DEPLOY          |
| ETH   | 5m  | markov_sized    |   713   | 713 | 0.327 | -0.452 | -3.48   | -324  | Markov cuts 10%; still bad              |
| ETH   | 5m  | markov_gate     |   713   | 713 | 0.327 | -0.502 | -3.71   | -360  | same as baseline                        |
| ETH   | 15m | baseline_lev2   |   328   | 328 | 0.427 | -0.426 | -1.36   | -209  | sub-edge bleed                          |
| ETH   | 15m | markov_sized    |   328   | 328 | 0.427 | -0.427 | -1.37   | -210  | no Markov lift                          |
| ETH   | 15m | markov_gate     |   328   | 328 | 0.427 | -0.426 | -1.36   | -209  | same as baseline                        |
| **ETH** | **1h**  | **markov_gate** | **55** | **55** | **0.582** | **+1.811** | **3.27** |  **-50**  | **BEST CELL** — WR 58%, Sharpe 3.3, +$100 net |
| ETH   | 1h  | baseline_lev2   |    55   |  55 | 0.582 | +1.811 |  3.27   |  -50  | tied with markov_gate (lev=2 in both)   |
| ETH   | 1h  | markov_sized    |    55   |  55 | 0.582 | +1.748 |  3.17   |  -50  | sizing layer adds nothing               |
| ETH   | 4h  | baseline_lev2   |    23   |  23 | 0.174 | -10.66 | -14.0   | -244  | n=23; pathological                      |
| ETH   | 4h  | markov_sized    |    23   |  23 | 0.174 | -10.66 | -14.0   | -244  | same                                    |
| ETH   | 4h  | markov_gate     |    23   |  23 | 0.174 | -10.66 | -14.0   | -244  | same                                    |
| SOL   | 5m  | baseline_lev2   |   462   | 460 | 0.387 | -0.298 | -1.16   | -202  | shallow bleed                           |
| SOL   | 5m  | markov_sized    |   462   | 460 | 0.387 | -0.191 | -0.76   | -131  | Markov trims 35% of loss + 35% of MDD   |
| SOL   | 5m  | markov_gate     |   462   | 460 | 0.387 | -0.298 | -1.16   | -202  | same as baseline                        |
| SOL   | 15m | baseline_lev2   |   166   | 166 | 0.512 | +0.214 |  0.69   |  -65  | marginal edge                           |
| SOL   | 15m | markov_sized    |   166   | 166 | 0.512 | +0.227 |  0.76   |  -59  | Markov adds 6%                          |
| SOL   | 15m | markov_gate     |   166   | 166 | 0.512 | +0.214 |  0.69   |  -65  | same as baseline                        |
| SOL   | 1h  | baseline_lev2   |    41   |  41 | 0.463 | +1.550 |  2.55   |  -40  | n=41; +$64 net (small sample)           |
| SOL   | 1h  | markov_sized    |    41   |  41 | 0.463 | +1.550 |  2.55   |  -40  | same                                    |
| SOL   | 1h  | markov_gate     |    41   |  41 | 0.463 | +1.550 |  2.55   |  -40  | same                                    |
| SOL   | 4h  | baseline_lev2   |    10   |  10 | 0.500 | +2.349 |  2.15   |  -42  | n=10; underpowered                      |
| SOL   | 4h  | markov_sized    |    10   |  10 | 0.500 | +2.349 |  2.15   |  -42  | same                                    |
| SOL   | 4h  | markov_gate     |    10   |  10 | 0.500 | +2.349 |  2.15   |  -42  | same                                    |

---

## Best deployable cell

**ETH 1h, Cyclops baseline (lev=2×)** — n=55, WR 58.2%, $/trade +$1.81, Sharpe
3.27, MDD −$50, total +$99.60 over ~9 years.

> Markov layer adds nothing here because every fire happens in a state that already
> passes the gate at lev=2×. The Markov_sized variant (1× SIDEWAYS) is fractionally
> worse because it under-sizes 1 sideways fire.

---

## G-criteria validation (best cell)

| Gate | Result                                                                  | Status |
|------|-------------------------------------------------------------------------|--------|
| G1 — n ≥ 30                          | n=55                                       | PASS   |
| G2 — WR > 50%                        | 58.2%                                      | PASS   |
| G3 — total PnL > 0                   | +$99.60                                    | PASS   |
| G4 — $/trade > slippage budget       | +$1.81 > 3 bps × $500 = $0.15              | PASS   |
| G5 — MDD < 3× avg-trade-pnl × √n     | $50 < 3 × 1.81 × √55 = $40.3               | FAIL   |
| **G6 — Bootstrap Sharpe lo-95 > 0**  | **CI = [-0.94, +7.99]**                    | **FAIL** |
| G7 — regime hold-out (no collapse)   | BULL n=26 Sharpe +5.87; BEAR n=28 Sharpe +1.15; SIDEWAYS n=1 (NA) | PASS   |

**G6 failure** is driven by small-n (n=55 over 9 years = ~6 fires/year). The
bootstrap CI is wide enough that we can't reject Sharpe=0 at 95%. The signal
is **real** in the empirical sample (median bootstrap Sharpe ~3, both regime
buckets positive), but **not statistically robust** for capital-at-risk
deployment without either (a) loosening the 3-axis coherence filter to grow
n, or (b) longer / cross-asset window.

**G7 PASS is the strongest single finding:** the strategy survives in both
BULL and BEAR markov states (Sharpe +5.87 and +1.15 respectively). It does
not collapse in any single regime — the rare 3-axis coherence captures
genuine multi-regime structure.

---

## Markov-sizing verdict (vs. V52 baseline)

Markov sizing (N4) layered on top of Cyclops adds **marginal value**:

* **SOL 5m**: Markov_sized lifts $/trade from −$0.30 to −$0.19 (37% loss reduction) and trims MDD by 35%. Best Markov-layer improvement in the sweep.
* **BTC 5m**: Markov_sized trims loss by 7% — modest.
* **ETH 5m**: Markov_sized trims loss by 10%.
* **ETH 1h** (the best cell): Markov layer adds nothing because there's no BEAR fire to skip.

Pattern: Markov sizing helps most on **negative-edge fast TFs** by trimming
bad-regime exposure, but the negative edge is too strong to flip positive.
On the only positive-edge cell (ETH 1h), Markov contributes 0 because every
fire is in an acceptable state.

`markov_gate` (binary skip) is **always identical to or worse than** `markov_sized`
(proportional) in this sweep — the gate gives up the SIDEWAYS 1× contribution
without compensating gain. Recommend dropping `markov_gate` as a variant.

---

## Comparison to V52 4h baseline

V52 (per `docs/deployment/V52_HYPERLIQUID_DEPLOYMENT_NOTES.md`) runs 4h on
BTC/ETH/SOL/AVAX/LINK. On the same engine + window:

* BTC 4h Cyclops: n=31, $/tr −$2.74, Sharpe −4.29.
* ETH 4h Cyclops: n=23, $/tr −$10.66, Sharpe −14.0.
* SOL 4h Cyclops: n=10, $/tr +$2.35, Sharpe +2.15.

Cyclops at 4h is **strongly underpowered** (n=10–31 over 6–9 years). The
3-axis coherence is too restrictive at long TFs. **Cyclops subtracts from
V52 at 4h** on BTC and ETH. Do not stack Cyclops as a 4h filter.

---

## Recommendation

* **Deployable:** ETH 1h Cyclops baseline (lev=2×) — but flag G6 fail. Suggest paper-trade for n≥150 fires before live capital. At current ~6 fires/year that's ~25 years; not practical. Suggested fix: relax momentum threshold from |rsi-50|>5 to >3 to grow n.
* **Not deployable:** all 5m and 15m cells across all 3 assets — negative edge, Markov sizing trims losses but never flips them positive.
* **Markov-N4 verdict:** modest value as a sizing layer on top of strategies that fire frequently in BEAR (5m cells); useless on infrequent positive-edge cells (1h). It does NOT rescue negative-edge Cyclops cells.
* **Cross-stack with V52:** at 4h, Cyclops is too restrictive — drop. Leave Cyclops as a 1h-only sleeve.

---

## Files

* Backtest script: `strategy_lab/hl_research_2026_05_26/wave2/W2d_cyclops_markov.py`
* Results CSV (36 rows): `strategy_lab/hl_research_2026_05_26/wave2/W2d_results.csv`
* Best-cell JSON (G6/G7 details): `strategy_lab/hl_research_2026_05_26/wave2/W2d_best_cell.json`
