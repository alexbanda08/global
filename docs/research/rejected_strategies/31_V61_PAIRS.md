# Study 31 — V61: Pairs / Spread Strategy (z-score mean-reversion)

**Status:** **All 3 pairs FAIL** the standalone Sharpe gate. The *structural*
hypothesis (ρ ≈ 0 with V52) IS confirmed — but raw z-score reversion has
**no edge** on crypto majors in 2024-2026 after costs.

**Date:** 2026-04-26

---

## The hypothesis

Dollar-neutral z-score reversion on (ETH/BTC, SOL/AVAX, SOL/ETH) ratios
should:
1. Be uncorrelated with V52 by construction → diversification benefit
2. Cap own MDD via mean-reversion → tighten blend bootstrap CI
3. Be the structurally-correct path past V52's 0.987 Calmar lower-CI ceiling

---

## Result — partial confirmation, partial fail

### Best parameters per pair (sweep across z_win × z_in × z_exit × max_hold)

| Pair | Best params | Sharpe | MDD | Calmar | WR | n_trades | **ρ vs V52** |
|---|---|---:|---:|---:|---:|---:|---:|
| ETH/BTC | z_win=200, z_in=2.5 | **−0.74** | −2.41% | −0.21 | 49% | 45 | **−0.029** |
| SOL/AVAX | z_win=200, z_in=2.0 | +0.05 | −2.86% | 0.01 | 56% | 48 | **+0.021** |
| SOL/ETH | z_win=200, z_in=2.5 | +0.28 | −1.47% | 0.15 | 56% | 36 | **−0.006** |

**Promoted: 0/3** (gate: Sh≥0.6, |ρ|<0.2, n≥30).

### What worked: the structural hypothesis

- Correlations vs V52 are **−0.029, +0.021, −0.006** — essentially zero,
  exactly as designed. Pair returns are genuinely orthogonal to the
  directional V52 signal.
- MDDs are tiny (−1.5 to −2.9%) — the dollar-neutral construction does cap
  drawdown via reversion.

### What failed: the alpha hypothesis

- All Sharpe ≤ 0.28, mostly negative
- Cost burden is large: 4 legs × (6 bps fee + 2 bps slip) = **32 bps per
  round-trip**. WRs of 47-68% are not enough to overcome this with
  reversion-sized targets.
- Crypto majors did NOT have a stationary spread in 2024-2026: BTC
  outperformed ETH for most of the window (BTC dominance grind),
  SOL/AVAX trended (SOL outperformed). The z-score model assumes
  stationarity that wasn't there.

---

## What this tells us (durable)

1. **Pairs are structurally the right path** for blend-CI improvement —
   ρ(V52) is genuinely zero, MDDs are genuinely capped. The §4-section
   intuition was correct.
2. **Naive z-score reversion has no edge** on crypto majors in this regime.
   Crypto cross-asset ratios trend; they don't mean-revert.
3. To make pairs work, we need at least one of:
   - **Cointegration filter** (Engle-Granger / Johansen): only enter when
     the residual is stationary on a recent window. Skip non-stationary
     periods entirely.
   - **Better pair selection**: BTC dominance vs alt-basket (rotation
     pairs). Or coins with same use case (L2s: ARB/OP, memes: DOGE/SHIB)
     — likely closer to cointegration.
   - **Different signal model**: trend-rotation instead of reversion (long
     the strong leg, short the weak), which trades the very thing that
     killed our reversion signals.

These are real engineering effort. Not free.

---

## Recommendation: pivot to Vector 4 (funding-rate signals)

Funding-rate signals are:
- **Already-collected data** (`data/hyperliquid/funding/<COIN>_funding.parquet`),
  no new ingestion needed.
- **Structurally different** from price-action — funding is a flow/positioning
  variable, not a price move. Should be near-zero correlation with V52.
- **Documented edges in literature**: extreme funding (longs paying heavily)
  is a fade signal at minute-to-hour scale. We're at 4h scale, so signal
  needs to be averaged over ~4-8h windows.

Skip more pairs work for now. Cointegration filtering is a 2-3 study effort,
and we'd still be uncertain it works on crypto. Funding signals have higher
EV-of-information for the next session.

---

## Files

- `strategy_lab/strategies/pairs_zscore.py` — pair simulator
- `strategy_lab/run_v61_pairs.py` — sweep harness
- `docs/research/phase5_results/v61_pairs.json` — full numbers

**Headline:** Z-score pairs are zero-correlation with V52 (structural ✓) but
zero-edge on crypto majors 2024-2026 after costs (alpha ✗). The path forward
is either complex (cointegration-filtered pairs) or different (funding-rate
signals — Vector 4). Recommending V62 = funding signals.
