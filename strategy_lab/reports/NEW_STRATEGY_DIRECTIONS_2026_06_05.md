# New-Strategy Directions — what's left to explore (2026-06-05)

After the data expansion. Quick free probes done: **shock-scalp (delta>12) = thin tail, not new**;
**complete-set arb (sum_ask<1) = doesn't exist** (books efficient, min 1.01). The lag-taker scalp remains the
one validated edge (5 coins, OOS). Below = the genuinely-untested directions, ranked by promise × tractability.
Discipline: EXECUTION/STRUCTURE only (every prediction angle this session died under rigor).

## Ranked candidates
1. **Cross-timeframe consistency arb** (structural, novel, untested) — a 15m up/down window contains three 5m
   windows; the 15m implied prob must be consistent with the 5m path + remaining drift. When the 15m token and
   the concurrent 5m tokens imply inconsistent probabilities (same underlying), trade the cheap leg. Data: BBO/L25
   both timeframes + resolutions (aligned in time). Effort: medium. Risk: the consistency may already hold (efficient).
   → **Top pick** — it's the most novel structural inefficiency and doesn't rely on prediction.
2. **Perp-mark-leads-spot scalp variant** (execution refinement) — does the cex-futures perp MARK lead binance
   spot into the poly token (faster signal than spot 1s)? cex_futures_ticker is ~3/s. Data window only May30–Jun4
   (short). Cheap to test; could sharpen the lag signal. Risk: perp≈spot, no lead.
3. **Cross-asset lead (BTC→alts)** — a BTC 5s move predicting alt poly-token reprice in the same window (alts lag
   BTC which lags poly). Now testable (5 coins + 1s). Effort: low-medium. Risk: this is correlation = prediction-
   flavored; the session's prior says prediction is efficient — likely dies, but it's an execution-lag framing so
   worth one clean test.
4. **Funding/OI regime gate on the scalp** (refinement) — does the scalp edge concentrate in certain funding/OI
   regimes? cex_futures funding/OI (May30–Jun4) + scalp fires. Cheap. Refinement, not new edge.
5. **HL liquidation-cascade → poly lag** — HL liqs (5.3M rows) mark violent underlying moves; the poly token lag
   may be largest right after a cascade. But ≈ the shock-scalp (big delta), which we showed is thin/gated-out.
   Low marginal value.

## Honest assessment
The market is efficient except the execution lag-taker. New *edges* (vs refinements) are unlikely; the realistic
upside is (a) #1 if the cross-timeframe inconsistency is real and fillable, or (b) sharpening/scaling the proven
scalp (5-coin deploy + live forward fires). Recommend: **run #1 (cross-timeframe arb) as the one real new-edge
shot; otherwise focus compute on shipping the validated 5-coin scalp + its live graduation.**

## Already-mapped (do not re-run)
Scalp (validated, 5 coins) · time-of-day gate (validated) · oracle-determinism (real, underpowered → shadow) ·
DEAD: prediction (ML/GPU/Kronos/indicators), microstructure selectors, maker entry/exit, favorite-longshot,
cross-token price-sum, liquidity-inversion, reversal-imbalance, F2-basis, complete-set arb, shock>12.
