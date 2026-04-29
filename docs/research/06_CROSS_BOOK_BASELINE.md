# 06 — Existing-Book Phase-5 Baseline (first 8-of-50 rows)

**Date:** 2026-04-24
**Driver:** [strategy_lab/run_phase5_existing_book.py](../../strategy_lab/run_phase5_existing_book.py)
**Scope:** 8 legacy strategies from `strategy_lab/strategies.py` × BTC / ETH / SOL @ 4h = 24 cells.
**Execution mode:** `v1` (legacy market-orders, next-bar-open, flat 0.1% per side).
**Scoring:** identical `score_run()` used for Phase-5 adaptive matrix — DSR, PSR, Calmar, Ulcer, regime-conditional Sharpe, etc.

## Headline — the existing book is stronger than our adaptive V2/V3

| Strategy | Symbol | Sharpe | Calmar | MDD | n_trades | Gates |
|---|---|---:|---:|---:|---:|---:|
| **squeeze_breakout** | **SOL** | **+1.18** | **+2.41** | −12.8% | 99 | **4/7** ⭐ |
| **donchian_breakout** | SOL | +0.79 | +1.62 | −16.4% | 95 | 4/7 |
| **macd_htf** | SOL | +0.86 | +1.50 | −16.9% | 114 | 4/7 |
| **donchian_breakout** | BTC | +1.19 | +2.14 | −15.4% | 96 | 3/7 |
| **supertrend** | BTC | +1.04 | +1.77 | −19.2% | 75 | 3/7 |
| volume_breakout | ETH | +0.90 | +1.02 | −19.8% | 76 | 3/7 |
| squeeze_breakout | BTC | +0.27 | +0.22 | −14.9% | 99 | 3/7 |
| squeeze_breakout | ETH | +0.75 | +1.21 | −12.8% | 104 | 3/7 |
| volume_breakout | BTC | +0.71 | +0.76 | −17.3% | 72 | 3/7 |
| donchian_breakout | ETH | +1.02 | +1.30 | −25.7% | 101 | 1/7 (MDD fail) |

Full 24-cell CSV: [docs/research/phase5_results/phase5_existing_book_results.csv](phase5_results/phase5_existing_book_results.csv).

## What this changes about the promotion bar

The existing book has **multiple cells scoring 4/7 gates**. Our best adaptive V3 cell scores **3/7** (A1 BTC-4h: Sharpe +0.71, Calmar +1.14, MDD −9.1%; D1 BTC-15m: Sharpe +0.47, Calmar +0.69, MDD −2.3%).

**Important caveat for apples-to-apples:** existing strategies run in v1 mode → **0% maker fills by construction**. They automatically fail the `gate_maker_fill ≥ 60%` gate. So:
- **On 6 applicable gates (excluding maker), `squeeze_breakout / SOL / 4h` scores 4 / 6 = 67%.**
- Adaptive V3 `D1 BTC-15m` scores 3 / 7 = 43% (the maker gate *does* apply — it passes at 68.8% — but Calmar 0.69 is half the 1.5 floor).

### The real bar for a new adaptive strategy to clear

A promoted adaptive candidate must **beat the best existing cell at its asset**. Not just pass absolute gates. Concretely:
- On SOL 4h, the new candidate must beat `squeeze_breakout` at **Sharpe +1.18, Calmar +2.41, MDD −12.8%**. Current A1 SOL sits at Sharpe −1.63. Gap: −2.8 Sharpe units.
- On BTC 4h, the bar is `donchian_breakout` at **Sharpe +1.19, Calmar +2.14**. Current A1 BTC sits at +0.71 / +1.14. Gap: −0.5 Sharpe units (closer — A1 is genuinely competitive, just not dominant).
- On ETH 4h, `donchian_breakout` at +1.02 Sharpe but fails MDD. `squeeze_breakout` at +0.75 / +1.21 / −12.8% is the realistic target.

### Key observations

1. **Breakout strategies dominate on SOL.** Three of the top four are breakouts. SOL's higher volatility rewards breakout continuation; regime-gated strategies (our A1) get whipsawed.
2. **Donchian + Supertrend are the consistent BTC winners.** Calmar > 1.7 on BTC for both. The book has real edge we should respect — new candidates must decorrelate, not just attempt to out-Sharpe.
3. **RSI mean-reversion is weak standalone** (10 trades, −0.21 to +0.08 Sharpe across symbols). Makes sense — pure MR in 2022–2024 crypto (trending market) underperforms. A1's MR leg likely suffers the same fate.
4. **Maker migration upside.** If a `donchian_breakout` under market-mode posts 1.19 Sharpe, the same signal with ≥ 60% maker fills would save ~20 bps/year in fees. Not transformative but free alpha.

## The coverage gap is smaller than we thought

The existing 8 strategies already cover the trend-follow + breakout cells decently across 3 symbols. New adaptive candidates should target:
- **Sideways regimes** (A1's MR leg, or F1 OFI, or meta-labeled Donchian C1 filtered to reject trend regimes — inverse of what the existing breakouts target).
- **Cross-asset diversification** (G1 pairs — existing book has one pairs strategy only).
- **Short-side / bear regimes** (0 existing strategies profit in bears — confirmed by the macd_htf SOL result which uses short-side, Sharpe +0.86 / 4 gates, but ETH version −0.84).

## Next steps

### Immediate
1. **Extend the roster** to cover the remaining 42 strategies from `strategies.yaml` (in `run_phase5_existing_book.py`, import + add ROSTER entries from V2–V25 modules). Once the roster is complete, the **50 × 3-symbol** matrix = **150 cells**. Wall-clock: ~30 min one-time.
2. **Compute the full 50 × 50 correlation matrix** from the generated equity curves. Enables the real `|ρ| < 0.5` gate that's been proxied by buy-and-hold.

### Strategic
3. **Rebuild A1 and D1 with the best-in-class existing strategy as the "don't be correlated with this" target** — explicitly maximize decorrelation against the SOL squeeze_breakout / BTC donchian clusters.
4. **Skip B1 for hand-tuning** — ship it to an Optuna sweep (Path D infrastructure) when ready.
5. **Consider moving C1 (meta-labeled Donchian)** up the Phase-3 priority list. Rationale: it literally wraps the existing Donchian winner with a Triple-Barrier meta-label filter — compounding a proven edge with a denoising layer. Could quickly become the best cell in the whole book.

## Updates to Phase 5 matrix doc

[docs/research/05_BACKTEST_MATRIX.md](05_BACKTEST_MATRIX.md) now has V3 results at the top. The V3 tuning recovered A1 BTC to Sharpe +0.71 / Calmar +1.14 — but still 0.36 Calmar short of the 1.5 gate AND behind `donchian_breakout_BTC`'s +2.14.

## Artifacts

- Cross-book driver: [strategy_lab/run_phase5_existing_book.py](../../strategy_lab/run_phase5_existing_book.py)
- Per-cell CSV: [docs/research/phase5_results/phase5_existing_book_results.csv](phase5_results/phase5_existing_book_results.csv)
- Shared scoring: [strategy_lab/run_phase5_matrix.py](../../strategy_lab/run_phase5_matrix.py) `score_run()`
- Metrics library: [strategy_lab/eval/metrics.py](../../strategy_lab/eval/metrics.py)
