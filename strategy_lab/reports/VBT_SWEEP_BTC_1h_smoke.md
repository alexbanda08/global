# VectorBT sweep — BTC_1h_smoke (underlying-crypto direction, NOT Polymarket) — auto

Bars={n}, {px.index[0].date()}→{px.index[-1].date()}. Swept **{n_combo}** combos (MA/RSI/BB families). IS=first60%, OOS=last40%, fees=5bps/flip. **Top-15 by IS Sharpe confirmed on OOS:**

| combo | IS Sharpe | OOS Sharpe |
|---|--:|--:|
| ('MAx', 80, 200) | 2.01 | -0.53 |
| ('MAx', 50, 220) | 1.90 | 0.26 |
| ('MAx', 70, 220) | 1.85 | 0.00 |
| ('MAx', 20, 260) | 1.77 | -0.99 |
| ('MAx', 25, 260) | 1.76 | -0.67 |
| ('MAx', 75, 200) | 1.70 | 0.27 |
| ('MAx', 45, 220) | 1.67 | 0.12 |
| ('MAx', 55, 220) | 1.67 | -0.19 |
| ('MAx', 40, 220) | 1.66 | -0.10 |
| ('MAx', 30, 240) | 1.65 | -0.19 |
| ('MAx', 60, 220) | 1.62 | -0.42 |
| ('MAx', 50, 240) | 1.61 | -0.24 |
| ('MAx', 45, 180) | 1.59 | -1.87 |
| ('MAx', 80, 220) | 1.58 | 0.09 |
| ('MAx', 30, 220) | 1.58 | -1.21 |

## Read
- Best IS Sharpe=2.01; null (shuffled) IS Sharpe p95=-12.92.
- **OOS is the judge.** Top-15 with OOS Sharpe>0.5: 0/15. A combo is only credible if its OOS Sharpe holds (IS Sharpe is inflated by searching {n_combo} combos).
- Deflated reality: with thousands of combos, expect the best IS Sharpe to be large by chance; only a consistent IS→OOS Sharpe (both clearly >0) is real. Crypto direction is largely efficient — treat any survivor with skepticism and re-confirm on a 3rd window before sizing.
- This is for tradeable UNDERLYING edge (Binance/HL), not Polymarket. Polymarket uses engine_v2.