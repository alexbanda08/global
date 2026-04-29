# 35 — QuantMuse repo analysis: what's transferable

**Date:** 2026-04-27
**Repo:** [github.com/0xemmkty/QuantMuse](https://github.com/0xemmkty/QuantMuse) (2.4k stars, 9 commits)
**Verdict:** Mostly orthogonal to our book, but **three structural patterns** are worth lifting.

---

## What the repo actually is

QuantMuse is a Python+C++ **equity-style multi-factor framework** built around stock selection on Yahoo / Alpha Vantage / Binance OHLCV data. The architecture splits a Python signal/factor layer from a C++ execution-engine layer. The 8 built-in strategies are textbook equity quant patterns:

| # | Strategy | Universe | Rebalance | Crypto-perp relevance |
|---|---|---|---|---|
| 1 | Momentum (60d top-N) | stocks | monthly | superseded — we already have V23 BBBreak / Donchian / Range-Kalman |
| 2 | Value (low P/E, P/B) | stocks | quarterly | n/a — no fundamentals |
| 3 | Quality Growth (ROE, debt) | stocks | quarterly | n/a |
| 4 | Multi-Factor (weighted blend) | stocks | monthly | conceptually = our V52 (multi-sleeve), borrowable |
| 5 | Mean Reversion (RSI<30) | stocks | high turnover | superseded — we have BB-scalp, MFI-extreme, RSI-2 |
| 6 | Low Volatility | stocks | monthly | n/a — defensive equity factor, doesn't translate |
| 7 | Sector Rotation | stocks | monthly | n/a — no equity sectors in crypto |
| 8 | Risk Parity | mixed | monthly | conceptually borrowable for sleeve weights |

**Factor model:** 5 dimensions × ~30 factors covering Momentum / Value / Quality / Size / Volatility / Technical (RSI, MACD, MAs, Bollinger). Driven by `FactorCalculator` → `FactorScreener` → `FactorBacktest` → `StockSelector` → `FactorOptimizer` (scipy maximizer on Sharpe / IC).

**AI layer:** OpenAI GPT for news/social-media sentiment → trading signal. News from public APIs, social from Twitter/Reddit polling.

**Realities to flag honestly:**
- 9 commits total, single contributor — most code is scaffolding, not battle-tested.
- No published backtest results, no walk-forward evidence, no per-strategy Sharpe / OOS retention numbers.
- LLM signal generation ("`signal = sentiment_analyzer.generate_sentiment_signal(market_sentiment)`") with no documented edge or validation.
- Their gates infrastructure is far weaker than ours (no path-shuffle MC, no per-year audit, no plateau test).

**Net:** Don't transplant signal logic. Our crypto-perp book is more disciplined and the universe is fundamentally different.

---

## Three patterns worth borrowing

### Pattern 1 — Per-signal Information Coefficient (IC) tracking

**What they do:** `FactorBacktest` reports rolling IC, IC IR, Rank IC per factor.

**Why we should care:** We currently track sleeve *equity curves*, not signal *predictive power*. A signal can lose its edge for weeks before equity drops noticeably (a momentum signal that mistimes by 1 bar still produces ~0 return, not a visible loss). Rolling IC of `signal[t]` vs `forward_return[t+1..t+k]` would catch decay weeks earlier.

**Concrete transplant:**
```python
# strategy_lab/util/signal_ic.py  (~50 lines)
def rolling_ic(signal: pd.Series, fwd_ret: pd.Series, window: int = 90) -> pd.Series:
    """Rolling Spearman rank IC of signal vs forward return."""
    ...
def signal_health_panel(sleeves: dict[str, pd.Series], df: pd.DataFrame, k: int = 6) -> pd.DataFrame:
    """One row per sleeve: IC mean, IC IR, IC trend, last-30d IC vs trailing-90d."""
```
Wire this into the V64 dashboard as an early-warning panel. **Cost:** ~1 day. **Value:** monitoring only — doesn't change live performance, but gives the kill-switch operator a leading indicator alongside equity drawdown.

### Pattern 2 — `FactorOptimizer` → `SleeveWeightOptimizer` (V68 candidate)

**What they do:** scipy-based optimization of factor weights to maximize a Sharpe / IC objective, with constraints.

**Why we should care:** V52 currently equal-weights 8 sleeves (with the V58 bolt-on at 92/8). We've never optimized those weights. The V67 leveraged variant (CAGR +60.1%, Sh 2.52) keeps the same equal-weight blend; an optimized blend over the same 8 sleeves could plausibly add Sh +0.1–0.2 *for free* — same data, same sleeves, same gates, just better composition.

**Concrete transplant:** mirrors `strategy_lab/run_v52_multistack.py` style but with scipy:
```python
# strategy_lab/run_v68_sleeve_weight_opt.py
from scipy.optimize import minimize
def objective(weights, sleeve_returns, lambda_reg):
    blend = sleeve_returns @ weights
    sharpe = mean(blend) / std(blend) * sqrt(BPY)
    # L2 regularize toward equal-weight to reduce overfit risk
    penalty = lambda_reg * np.sum((weights - 1/n)**2)
    return -(sharpe - penalty)
# Walk-forward: train weights on 18m IS, lock for next 6m OOS, repeat
```

**Critical guardrails (the V25/V27 lesson):**
- L2 regularization toward equal-weight (`λ ≥ 0.5` to avoid corner solutions).
- Walk-forward only — no in-sample full-history optimization.
- Constraint: `weights ∈ [0.5/n, 2.0/n]` so no sleeve goes to zero and no sleeve dominates.
- Decision gate: must clear ≥ V52's gate count *and* improve Calmar lower-CI vs equal-weight blend.

**Cost:** ~1 week. **Plausible lift:** Sh +0.1–0.2, which on V67 (L=1.75) translates to CAGR +5–10pts.

### Pattern 3 — Regime-conditional sleeve activation

**What they do:** their strategy table maps regime → strategy (bull → momentum, sideways → value/mean-rev, bear → low-vol, etc.). It's a soft mapping in their docs — not formally implemented.

**Why we should care:** We have `study 24` (directional regime classifier) sitting on the shelf. V58/V59 gates use it for tighter trail multipliers but don't use it to *activate / deactivate* sleeves. If our 8 sleeves split cleanly into "trend" (BBBreak, Donchian, Inside-Bar-Break) vs "mean-rev" (CCI, MFI, BB-fade, VP-rotation, SVD), running only the trend sleeves in Bull/Bear regimes and only the MR sleeves in Sideways would compress correlation between sleeve signals and reduce wasted trades during regime mismatches.

**Concrete transplant:**
```python
# strategy_lab/run_v69_regime_conditional_blend.py
SLEEVE_FAMILY = {
    "BBBreak_*": "trend", "Donchian_*": "trend", "IBB_*": "trend",
    "CCI_*": "MR", "MFI_*": "MR", "VP_*": "MR", "SVD_*": "MR", "LATBB_*": "MR",
}
REGIME_ACTIVATION = {
    "Bull": {"trend": 1.0, "MR": 0.5},      # half-weight MR in trends
    "Bear": {"trend": 1.0, "MR": 0.5},
    "Sideline": {"trend": 0.3, "MR": 1.0},  # heavy MR in chop
}
```
Apply per-bar via the directional regime label.

**Cost:** ~3 days. **Plausible lift:** trade-count reduction → fee compression → Sh +0.05–0.15. Stronger signal-quality argument than P&L argument; pairs well with Pattern 2.

---

## What we should explicitly NOT borrow

- **The 8 strategies themselves.** Equity-style; we already have stronger crypto-perp analogs.
- **The LLM/sentiment modules.** `signal = generate_sentiment_signal(...)` with no validation. News/social NLP for crypto perps is high-noise, has documented backtest survivorship bias (only post-hoc survivable narratives are in the training data), and adds an OpenAI dependency / cost / outage surface for marginal expected lift. Skip.
- **The C++ execution engine.** Our V64 deployment is Python + Hyperliquid SDK; no sub-millisecond requirement. Premature optimization.
- **Their data fetchers.** We have working HL + Binance fetchers; their Yahoo / Alpha Vantage layer is irrelevant.
- **Their factor universe (P/E, ROE, dividends).** No stock-fundamentals analog in crypto perps.

---

## Recommended sequencing

If we want to extract value from this exercise, the cheapest highest-value path is:

1. **Pattern 1 (signal IC monitor)** — 1 day, monitoring-only, zero risk to live performance.
2. **Pattern 2 (sleeve weight optimizer, V68)** — 1 week, the only one that adds direct CAGR. Pairs with V67 (run after the per-sleeve leverage validation lands).
3. **Pattern 3 (regime-conditional blend, V69)** — 3 days, complementary to V68. Run after V68 to see if the optimizer's weights *already* capture what regime activation would force.

If V68 alone delivers Sh +0.15, V67 (L=1.75) goes from CAGR +60.1% / Sh 2.52 to roughly CAGR +63–65% / Sh 2.67 with the same MDD — a meaningful incremental win on top of today's leverage hit.

## Files referenced
- [33_NEW_STRATEGY_VECTORS.md](33_NEW_STRATEGY_VECTORS.md) — the original vector catalog. Pattern 2 here is the same as Vector 9 (RL/bandit meta-allocator) but with scipy-Sharpe instead of bandit, which is simpler and wins faster.
- [34_V67_LEVERAGE_HIT.md](34_V67_LEVERAGE_HIT.md) — V67 = the L=1.75 result that the V68 optimizer would build on top of.
