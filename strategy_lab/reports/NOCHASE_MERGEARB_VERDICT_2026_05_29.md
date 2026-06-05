# No-Chase Merge-Arb — VERDICT: no edge, close the line (2026-05-29)

Tests the ONE maker-arb variant the censoring reversal left open
(`MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md`): a strict **no-chase** merge-arb that
NEVER overpays to complete a pair and NEVER carries the adverse directional residual
(flattens the stuck leg back at the bid instead of holding to resolution). Run on the
**longer window** the reversal asked for — May 20 → May 29, n=10,565 slug-instances
(vs the reversal's ~67), local backtest against canonical native-10Hz L25 + chainlink.

Script: `strategy_lab/maker_arb_audit/_nochase_mergearb_longwin_2026_05_29.py`
CSV: `strategy_lab/maker_arb_audit/_results/_nochase_mergearb_longwin.csv`

## Result — negative on every budget, CI entirely below zero

| budget | n | comp% (pooled) | pnl_hold | pnl_flatten | flatten 95% CI | clears 0? |
|---|---:|---:|---:|---:|---|---|
| 0.90 | 10,565 | ~67% | −0.0316 | **−0.0332** | [−0.038, −0.029] | no |
| 0.93 | 10,565 | ~72% | −0.0360 | **−0.0366** | [−0.041, −0.033] | no |
| 0.94 | 10,565 | ~76% | −0.0304 | **−0.0317** | [−0.035, −0.028] | no |
| 0.97 | 10,565 | ~83% | −0.0313 | **−0.0315** | [−0.035, −0.028] | no |

Negative in **every** asset×tf×budget cell (BTC/ETH/SOL × 5m/15m), range −$0.02 to −$0.05/slug.

## Why it fails (and why no-chase doesn't save it)
- Completion rate is HIGH (63–88%) and completed pairs ARE positive by construction
  `(1 − budget) + 2·rebate`. **Yet the pool is still negative** — the 12–37% stuck slugs
  lose more than the completed pairs earn.
- **Flatten ≈ hold** (−0.033 vs −0.032 at budget 0.90). Selling the stuck leg back does
  NOT rescue it: you got filled on leg1 at 0.50 *because* the ask was crossing down
  through 0.50 (adverse selection), so the bid at flatten time is usually < 0.50. The
  round-trip half-spread + adverse selection on the stuck leg exceeds the thin
  `(1 − budget)` edge captured on the completed pairs.
- This is **generous** to the strategy: instant maker fills the moment the ask touches
  the price (no queue, no partials), no cross-token spread filter (the 31%-spread issue
  that zeroed V5 live), and rebate counted as income — but CLAUDE.md verifies `feeRate`
  is effectively 0 on these crypto up-down markets, so **no rebate actually accrues**.
  Strip the rebate and it's ~$0.007/slug worse still. Real-world is worse than this.

## Conclusion
The no-chase variant — the last undisproven maker-arb form — **does not clear zero.**
Combined with:
- `MAKER_ARB_CENSORING_REVERSAL_2026_05_28.md` (every production sleeve net-negative once
  losers are settled; even fully-paired slugs −$3.93), and
- `EFFICIENT_MARKET_FINDING_2026_05_28.md` (price is a near-optimal estimator; no signal
  beats it OOS; wallet edges are execution/latency, not prediction),

**the maker-arb / pair-arb line is closed for our infra.** Do not reopen without a
genuinely new ingredient (e.g., a real maker queue-priority/latency advantage that lets
us be filled ABOVE the bid we'd flatten at, or a directional selection edge — neither of
which we have or can reproduce). The profitable external wallets win on execution we
cannot out-compete from Ireland, not on a mechanic we can clone.

**Net of the whole 2026-05-29 wallet hunt: a confirmed NEGATIVE result. No deployable
edge found; the efficient-market capstone holds.**
