# Cross-Timeframe Relative-Value / Arb Test: 5m vs 15m Poly Markets
**Date:** 2026-06-05  
**Window:** May 20 – Jun 4, 2026 (16 days)  
**Assets:** BTC, ETH, SOL  
**Script:** `strategy_lab/directional/cross_tf_arb_2026_06_05.py`  
**Fires parquet:** `strategy_lab/directional/_results/cross_tf_arb_pairs_2026_06_05.parquet`

---

## 1. Structure

The 15m window `[T, T+15m]` and the last 5m window `[T+10m, T+15m]` share the same settle time `T+15m` but have different strikes. At `t = T+10m`:

- **15m-Up** resolves `P(T+15) > P(T)` — bar is at `P(T)` (15m strike, known)
- **5m-Up** resolves `P(T+15) > P(T+10)` — bar is at `P(T+10)` (5m strike, known)
- Gap `g = P(T+10) - P(T)` is **known** from Chainlink strikes embedded in resolutions

This gives three testable signals. Decision point: `t = T+10m + 5s` (5s buffer; Binance 1s kline already confirmed at that point). Books looked up at that exact `fire_us`.

**Data:** 4,253 matched 15m/5m pairs (BTC: 1,418, ETH: 1,418, SOL: 1,417). 2,828 / 4,253 have valid L25 book data at the decision moment (66%).

---

## 2. Descriptive: How do 5m and 15m prices compare given g?

The 15m-Up and 5m-Up tokens are **not correlated** (r = −0.048). Mean ask_15m = 0.487, mean ask_5m = 0.507 — essentially both centering at ~0.50.

**15m-Up win rate by gap bucket (pooled BTC+ETH+SOL):**

| g_bp bucket | n    | wr_15m_up | wr_5m_up | ask_15m | ask_5m |
|-------------|------|-----------|----------|---------|--------|
| < −50       | 23   | 0.000     | 0.304    | 0.015   | 0.520  |
| −50:−20     | 236  | 0.038     | 0.479    | 0.037   | 0.523  |
| −20:−5      | 761  | 0.096     | 0.495    | 0.135   | 0.514  |
| −5:5        | 894  | 0.454     | 0.441    | 0.503   | 0.507  |
| 5:20        | 747  | 0.843     | 0.458    | 0.875   | 0.496  |
| 20:50       | 158  | 0.981     | 0.481    | 0.968   | 0.492  |
| > 50        | 9    | 0.778     | 0.444    | 0.986   | 0.524  |

**Key finding:** the 15m-Up token is **correctly priced** given g. When `g > 20bp`, ask_15m averages 0.969 (win rate 0.981) — Polymarket is pricing it right, not lagging. When `g < −50bp`, ask_15m averages 0.015 (win rate 0.000) — again correct. The market has already absorbed the mid-window Binance price into the 15m token.

The 5m-Up token is **invariant to g** (~0.50 win rate and ~0.50 ask regardless of g bucket) — correct, since g tells you nothing about P(T+15)−P(T+10).

---

## 3. Signal A: Oracle-lag / Determinism (buy the near-certain 15m leg)

**Hypothesis:** at `t=T+10m`, if `|g|` is large, the 15m outcome is near-certain. If the 15m token is lagging (ask still < 0.92), buy it.

**Result (pooled ALL, 2,000 bootstrap resamples, $25 notional):**

| side | g_thresh_bp | n   | wr    | mean_ask | pnl/tr | CI 95%           |
|------|-------------|-----|-------|----------|--------|------------------|
| up   | 5           | 542 | 0.773 | 0.812    | −1.49  | [−2.58, −0.43] ✗ |
| dn   | 5           | 533 | 0.850 | 0.815    | +0.97  | [+0.00, +1.95] ~ |
| up   | 10          | 226 | 0.805 | 0.842    | −1.30  | [−2.84, +0.18] ✗ |
| dn   | 10          | 211 | 0.844 | 0.837    | +0.08  | [−1.36, +1.56] ✗ |
| up   | 20          | 37  | 0.865 | 0.864    | −0.07  | [−3.74, +2.96] ✗ |
| dn   | 20          | 31  | 0.839 | 0.867    | −0.93  | [−4.93, +2.52] ✗ |

**Interpretation:** The "Up" leg is consistently **negative** (CI excludes 0 at g>5bp), while the "Down" leg is marginally positive but the CI just barely touches zero at g>5bp and is null thereafter. High win rates (77–87%) but the tokens are priced to reflect that — mean ask 0.81–0.87. The 0.07 fee curve is brutal at these high vwaps: a trade at ask=0.84 with 85% WR still loses money because `84c × 16%_loss > (16c × 0.07×0.84 fee) × 84%_win`.

**The "lag" condition (ask < 0.92) is vacuous** — the market IS correctly pricing the 15m token given g. There is no lag; the books already reflect the known gap.

**Verdict: NULL for Signal A.** No exploitable oracle lag in the 15m token.

---

## 4. Signal B: Cross-market Inversion (buy the mispriced leg)

**Hypothesis:** when `g > 0`, 15m-Up should trade above 5m-Up (lower bar to win). If `ask_15m_up < bid_5m_up − threshold`, there's an inversion — buy the 15m-Up.

**Result:** **Zero fires** across all parameter combinations (min_gap_bp ∈ {5,10,20}, inversion_thr ∈ {0.0, 0.01, 0.02, 0.05}).

**Interpretation:** consistent with the descriptive table — when `g > 20bp`, ask_15m = 0.969 and ask_5m = 0.493. The market is pricing the 15m-Up HIGHER than the 5m-Up, as expected. No inversions exist. The cross-market relationship is already arbitraged away.

**Verdict: NULL for Signal B.** No cross-market inversions.

---

## 5. Signal C: Implied-Probability Consistency (normalized gap)

**Hypothesis:** normalize g by asset's empirical 5m std (BTC 16.7bp, ETH 19.1bp, SOL 23.5bp). When `g_sigma > 1.5σ`, model rational 15m-Up prob via N(g_sigma) and buy if ask < rational_prob − slack.

**Result (only rows with n ≥ 5):**

| asset | g_std_bp | sigma_thr | slack | n  | wr    | ask   | pnl/tr | CI 95%        |
|-------|----------|-----------|-------|----|-------|-------|--------|---------------|
| BTC   | 16.7     | 1.0       | 0.03  | 27 | 0.889 | 0.882 | −0.05  | [−3.75, +2.91] |
| ETH   | 19.1     | 1.0       | 0.03  | 15 | 1.000 | 0.843 | +4.68  | [+3.29, +6.24] ✓ |
| SOL   | 23.5     | 1.0       | 0.03  | 11 | 1.000 | 0.863 | +3.86  | [+2.90, +5.05] ✓ |
| BTC   | 16.7     | 1.0       | 0.05  | 10 | 0.900 | 0.901 | −0.87  | [−5.56, +1.32] |
| ETH   | 19.1     | 1.0       | 0.05  | 8  | 1.000 | 0.880 | +3.20  | [+2.32, +4.19] |
| ETH   | 19.1     | 2.0       | 0.03  | 5  | 1.000 | 0.934 | +1.68  | [+1.08, +2.47] |

ETH and SOL show **100% WR** with positive CIs. However:

**Critical caveat:** n = 5–27. At 100% WR with n=11-15, the CI is entirely driven by the perfect in-sample hit rate — this is likely **small-sample overfit** (no room to observe a loss). The condition `g_sigma > 1σ` with `ask < N(g_sigma) − 0.03` is a very specific filter that selects extremely near-certain markets (ask > 0.84). Any one loss would devastate the CI.

**BTC at same threshold shows WR=0.889, pnl near-zero, CI spanning zero** — consistent with a luck artifact in ETH/SOL small samples.

**Verdict: LIKELY NULL for Signal C.** The 100% WR cells are too small (n<30) to distinguish from random luck at a high ask level. The underlying market pricing is already correct.

---

## 6. Why Is There No Edge?

The core finding from the bucket table is decisive: Polymarket prices the 15m-Up token **correctly and immediately** in response to the known mid-window gap g. When `g > 20bp`, ask_15m = 0.969 (wr = 0.981). The expected PnL at ask=0.969, wr=0.981 is:
```
shares = 25/0.969 = 25.80
won:  25.80 × 0.031 × (1 − 0.07 × 0.969) = 0.72 × 98% ≈ $0.71
lost: 25.80 × 0.969 × 19% loss = −$4.75 expected
net ≈ 0.981×0.71 − 0.019×25 ≈ +0.70 − 0.47 ≈ +$0.23/tr
```
But the fee drag at high vwaps is severe — the 0.07 curve charges `0.07 × 0.97 × 0.03 × 25/0.97 = ~$0.07` per win, and the loss size is still 97% of notional for the rare losses. The signal is *correctly priced in* and the fee curve eats any residual.

The 5m-Up token at the same moment is ~0.50 (g tells us nothing about the final 5m move from T+10). No inversion exists.

---

## 7. Result Table (summary)

| Signal | Definition | n (max) | $/tr | CI 95% | Edge? |
|--------|-----------|---------|------|--------|-------|
| A-up pooled | g>5bp, buy 15m-Up | 542 | −1.49 | [−2.58, −0.43] | NO (negative) |
| A-dn pooled | g<−5bp, buy 15m-Down | 533 | +0.97 | [+0.00, +1.95] | BORDERLINE / NULL |
| B | Cross-market inversion | 0 | — | — | NO (no fires) |
| C ETH 1σ | Normalized gap, buy lag | 15 | +4.68 | [+3.29, +6.24] | TOO SMALL (n=15, 100% WR) |
| C SOL 1σ | Normalized gap, buy lag | 11 | +3.86 | [+2.90, +5.05] | TOO SMALL (n=11, 100% WR) |

---

## 8. Caveats

1. **Fill assumption:** analysis uses L25 best-ask at `T+10m + 5s`. In live trading, getting filled at ask on a 0.97-priced token requires hitting the market; the bid side would be ~0.02 wide. Real entry would be ask + slippage.
2. **Missing book data:** 34% of pairs lack L25 book data at decision_us (stale/absent). These may be biased — thin books during volatile moves (exactly when g is large). If missing = no-fill, effective n is even smaller.
3. **Lookahead check:** g is computed from Chainlink strike prices embedded in the resolution table, both of which are known at `T` and `T+10m` respectively — no lookahead. Decision point is `T+10m + 5s`. Confirmed causal.
4. **Window:** 16 days only. Structural dynamics may differ in other regimes.
5. **A-dn borderline:** the pooled `g<−5bp, buy 15m-Down` result barely touches CI=[0.00, 1.95]. This is a degenerate signal (the Down token at low price when gap is negative is just "buy the winner when it's priced near 1"), not a relative-value edge. Fee drag at ask=0.82 (Down token) with 85% WR is the same issue as A-up.

---

## 9. Conclusion

**No tradeable cross-timeframe arb edge exists in this dataset.** Polymarket prices the 15m-Up/Down tokens correctly and contemporaneously with the known mid-window Binance/Chainlink price. The market price at `t=T+10m` already reflects `g = P(T+10)−P(T)` — there is no oracle lag to exploit. The 5m and 15m markets are mutually consistent (no inversions). All positive PnL cells are either small-sample artifacts (n<30, 100% WR) or CI-crossing-zero. The 0.07 fee curve at high vwaps (0.82–0.97) leaves almost no room even if WR is high.

**Honest assessment:** the cross-timeframe relationship is an *interesting structural fact* about Polymarket (prices adjust immediately to known mid-window moves), but it produces no exploitable edge. Consistent with the broader project finding that Polymarket's CLOB is efficiently priced; real edge lives only in execution (intra-window exit-scalp), not in relative-value positioning.
