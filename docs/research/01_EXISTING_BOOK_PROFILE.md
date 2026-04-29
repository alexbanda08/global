# 01 — Existing Book Profile (v1, manifest-backed)

**Status:** Inventory section filled from the authoritative `strategies.yaml`. Coverage matrix, correlation map, fee-impact analysis, and aggregate baseline remain deferred until Phase 0.5 (engine uplift) and Phase 2 (regime classifier) land.

**Source:** `docs/research/strategies.yaml` — manifest agent scanned 144 `.py` files in `strategy_lab/`, excluded 94 as harnesses (sweep drivers, report builders, OOS audits, portfolio combiners, validators, dashboards, feature loaders), and deduplicated the remainder by signal-logic fingerprint.

**Canonical strategy count: 50** — the user's "39" claim was close to the mission's mental model but the real codebase collapses to 50 distinct signal logics after dedup. All downstream gates (|ρ| < 0.5 against every existing strategy, correlation-map clustering, fee-impact analysis) apply to N=50.

---

## A. Family-Level Inventory (from `strategies.yaml`, N=50)

| Family             | Count | Notes                                                                 |
|--------------------|------:|-----------------------------------------------------------------------|
| trend              | 16    | EMA cross, Supertrend, Donchian continuation, Range-Kalman (V4C/V13/V15/V16/V17/V20/V21/V22/V23 all collapse to one row) |
| mean_reversion     | 12    | RSI, Bollinger break, Keltner, CCI, O-U, VWAP reversion                |
| breakout           | 7     | Donchian breakout, Volume breakout (V2B), squeeze breakout             |
| mtf                | 4     | HTF-confirmed momentum, ladder, HTF regime + LTF execution             |
| regime_router      | 3     | V24 ADX+SMA router, V25 regime shifts, V32 core audit logic            |
| scalp              | 3     | 15m scalp, 5m sniff, squeeze variants                                  |
| ensemble           | 2     | Chimera blends, portfolio optimization                                 |
| ml_feature         | 1     | Feature-stack model (others that looked ML-ish were derivatives rules) |
| pairs              | 1     | BTC/ETH cointegration                                                  |
| other              | 1     | V37 LLM trader (orchestrator, not a signal generator — flagged so) |
| **Total**          | **50**|                                                                       |

**Top feature dependencies** (rows that import each): `atr` 43, `ema` 23, `rsi` 12, `adx` 11, `donchian` 9. ATR saturation means trailing-stop logic is shared across the book — a single ATR definition change is a cross-cutting risk.

**Derivatives-dependent rows:** 7 (funding-rate fade, OI breakout, LS-ratio divergence, liquidation cascade, premium reversion, taker-delta momentum, and one V10 derivatives composite). These cannot be backtested on pure spot OHLCV — they need the `futures_phase_a` / `coinapi` fetchers wired up.

## A.1 Documented Performance (only 3 rows have published numbers)

| id                       | symbol | tf | Sharpe | MaxDD   | Source                |
|--------------------------|--------|----|-------:|--------:|------------------------|
| range_kalman (V4C)       | BTC    | 4h | 1.32   | -28.8%  | `strategy_lab/README.md` winners table |
| adx_gate_trend (V3B)     | ETH    | 4h | 1.26   | -33.8%  | same                   |
| volume_breakout (V2B)    | SOL    | 4h | 1.35   | -51.5%  | same                   |

The other 47 rows have `documented_sharpe: null` in the manifest because the codebase does not publish a per-row results table. Prose claims in `reports/*.md` exist but aren't a citable numeric source. Phase 1 v2 (post engine uplift) will generate the missing numbers by running every strategy under the hardened engine and standardized protocol.

## B. Order-Type Usage (Current)

**100% of rows have `order_type_current: market_open_next`.** No strategy currently uses limit orders — all 50 execute at the next-bar open with flat 10 bps per side. Implications:

- **Current fee-drag analysis is uniform** — can only differentiate strategies by turnover, not by execution quality.
- **Maker-preference migration is not a per-strategy toggle** — it requires the Phase 0.5 engine uplift first.
- **Retrofit prognosis** (per-family, from signal-logic inspection):
  - `mean_reversion` (12) + `pairs` (1) = **13 strategies high-compatibility with maker entries** — signals fire at extremes, price typically retraces into a passive limit.
  - `trend` (16) + `regime_router` (3) = **19 strategies moderate** — pullback entries are feasible, but trend-following sometimes needs to chase.
  - `breakout` (7) + `scalp` (3) = **10 strategies low/negative** — breakout strategies that fill *only if price retraces* will systematically miss the moves they aim for. Stop-limit with a small inside offset is the realistic retrofit, not pure passive limits.
  - `mtf` (4) + `ensemble` (2) + `ml_feature` (1) = **7 case-by-case** — inherit the execution profile of whatever signal they route.
  - `other` (1, LLM orchestrator) — out of scope for fee migration.

Expected aggregate maker-fill ceiling after optimistic retrofit: ~50–65% of fills. The mission's 60% floor is tight but achievable.

## C. Regime × Timeframe Coverage Matrix (DEFERRED)

Cannot be populated yet. Requires:
1. Phase-0 manifest (which rows to include).
2. Phase-2 regime classifier (to compute regime labels historically).
3. Re-run of every strategy with per-regime P&L attribution.

Tentative shape of the table (to be filled in):

| Regime \ TF            | 4h | 1h | 45m | 30m | 15m |
|------------------------|----|----|-----|-----|-----|
| strong_uptrend         |    |    |     |     |     |
| weak_uptrend           |    |    |     |     |     |
| sideways_low_vol       |    |    |     |     |     |
| sideways_high_vol      |    |    |     |     |     |
| weak_downtrend         |    |    |     |     |     |
| strong_downtrend       |    |    |     |     |     |

**Hypothesis from archetype read:** trend-following (8 strategies) over-indexes on `strong_uptrend / strong_downtrend`; mean-reversion (5) concentrates in `sideways_low_vol`; `sideways_high_vol` and `weak_*` cells are likely thin — those are the Phase-3 gap-filling targets.

## D. Correlation Map (DEFERRED)

Requires aligned per-bar equity curves. `results/*_equity.csv` exists for several variants but is not canonicalized. Correlation analysis will run in Phase 1 v2 after:
- Per-strategy OOS equity curves are re-generated under the hardened engine.
- A common time index is fixed (likely 2022-01-01 → present, to avoid mixing strategies that existed / didn't exist at given dates).

Expected output once populated: pairwise Pearson matrix, Ward-linkage dendrogram, cluster centroids. Planned Phase-3 targeting favors strategies that score low-correlation against the centroid of the largest cluster.

## E. Fee-Impact Analysis (DEFERRED — engine dependency)

Cannot be computed meaningfully while the engine applies a single flat fee. After engine uplift, we will compute for each strategy:
- Annual turnover (entries + exits per year)
- Estimated annual fee drag at current execution (100% taker)
- Estimated annual fee drag at target execution (maker-preferred, assume 60% fill rate, taker fallback on the other 40%)
- Predicted Sharpe / Calmar delta after execution migration

Strategies with the largest delta are the priority conversion candidates — these may graduate to "improved but unchanged signal" before any new strategy research begins.

## F. Aggregate Portfolio Baseline (DEFERRED)

Requires the manifest + clean equity curves. Target metrics once available:
- Equal-weight Sharpe, Sortino, Calmar
- Max DD, DD duration, recovery time
- Effective N (Meucci entropy of correlation eigenvalues)
- Tail ratio (95th / 5th percentile monthly returns)

Existing runs report *per-symbol winner* performance but not *aggregate-of-39*. This is one of Phase 1's highest-leverage outputs.

---

## What This Document Is NOT Yet

- A canonical row-per-strategy inventory (awaiting Phase 0 manifest).
- A correlation-based clustering of the 39 (awaiting equity curves).
- An actionable fee-conversion priority list (awaiting engine uplift).
- A regime-coverage heatmap (awaiting regime classifier).

All four are tractable once the preconditions in `00_MISSION_GAP_REPORT.md` are resolved.
