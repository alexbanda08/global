# Reconciliation — `clbasis_rel btc-5m` (my capstone) vs `FAST_TAKER_LAGV2` (TV spec)

**Verdict: SAME EDGE.** Both are the Binance-leads-Chainlink **oracle-lag directional taker**. They were
arrived at independently and converge on the identical signal, direction rule, hold-to-resolution, fee,
and engine. LAGV2 is the productionized, refined, multi-cell version of my single validated survivor.

## Identical core
| element | my clbasis_rel | FAST_TAKER_LAGV2 |
|---|---|---|
| signal | `cl_basis_bps = (binance − chainlink)/chainlink·1e4` | `price_delta_bps = (feed − oracle)/oracle·1e4` — **same formula** |
| direction | sign of basis → buy leading side | sign of delta → buy leading side — **same** |
| timing | fire early in slot (offset 60s) | fire early (offsets 5–40s), edge decays by 45–60s — **same shape** |
| hold | to chainlink resolution | to chainlink resolution — **same** |
| fee/engine | poly 0.07·p·(1−p) + native-10Hz L25 + 85ms latency | identical |
| dead-ends excluded | maker/pair-arb/merge CLOSED; momentum/RSI/MACD no-ops | **same** (complete-set lock dead, RSI/MACD no-ops, SOL drag) |

## Where LAGV2 is MORE developed (the deltas — all refinements I did NOT have)
1. **Operating band + CAP.** Mine: `dev > 3` (de-meaned), no upper bound. LAGV2: `3 ≤ |bps| ≤ 12` with a
   hard **12bps CAP** — beyond 12 the move is already priced and the edge **reverses** (WR 56%, −$4.17/tr).
   I never tested an upper cap; this is a real improvement.
2. **De-mean vs raw band.** I subtract a trailing-median because my canonical cl_basis carries a structural
   ~+13bps measurement offset (1s-klines vs RTDS). LAGV2 uses raw signed `price_delta_bps` — implying its
   live `oracle_lag` aligns the feeds so ambient ≈ 0. **Functionally the same selection; the offset handling
   differs by data source.** ⚠️ must reconcile so the live signal matches the backtest.
3. **Refinement gate stack** (LAGV2 has, mine didn't): cross-asset confluence (BTC↔ETH agree), exclude US
   close hours 18–23 UTC, top-depth ≥ median. These sharpen WR + cut maxDD.
4. **LOOSE spread filter 0.05** (vs my 0.02). LAGV2: "edge lives in WIDE/dislocated books — do NOT tighten."
   **My tight 0.02 filter may have been rejecting the best opportunities** → a likely reason my bare
   lower-threshold version failed where LAGV2's works.
5. **Reversal stop** (`LAG_REVERSAL_STOP`): exit early if Binance reverses ≥10bps vs entry. I held flat.
6. **Scope/frequency.** Mine: btc-5m only, **~2 fires/day @ WR 86%, +$5.95/fire** (~$12–13/day/$25).
   LAGV2: BTC+ETH × 5m+15m, **~22 fires/day @ WR ~68%, +$3.0–3.4/fire** (~$66/day/$25), OOS t=2.78.

## The one tension to resolve (important)
My harsh-cost gate battery concluded the **broader/lower-threshold band is priced-out** — only the EXTREME
tail (dev>3 + tight gates) survived on btc-5m, and eth-15m was fragile (plateau fail), sol-15m no. LAGV2
claims the **3–12bps band across BTC+ETH/5m+15m is net-positive (22/day, t=2.78).** Both can be true because
LAGV2 adds the refinement stack (cross-asset confluence + ToD exclude + depth filter + reversal stop + LOOSE
spread) that my BARE `clbasis_rel` lacked. i.e. **the gates are what rescue the higher-frequency version.**

But this has NOT been checked under my standard (HIGH fee + $0.01 tx + block bootstrap + Bonferroni). 22
fires/day is a far better business than 2/day, so it's worth the check.

## Action item (the honest next step)
Re-run my `eval_strategies.py` gate battery on the clbasis signal **with LAGV2's refinements applied**:
- band `3 ≤ |bps| ≤ 12` (add the upper CAP), LOOSE spread 0.05, add cross-asset-confluence + exclude-18–23-UTC
  + top-depth filters, early offsets, reversal-stop.
- Across BTC+ETH × 5m+15m, REALISTIC cost (+$0.01 tx), block bootstrap + Bonferroni.
- If the 22/day band passes under that bar → LAGV2 is the better deployment than my 2/day tail, and the
  capstone's "btc-5m extreme tail only" verdict was an artifact of the BARE signal (no refinement gates +
  too-tight spread). If it does NOT pass under harsh costs → trust the 2/day tail and treat LAGV2's broader
  band as optimistic.

## Bottom line
They are the same strategy. LAGV2 = my edge + (band-cap, confluence, ToD, depth, reversal-stop, loose
spread, more cells) → ~10× the frequency at lower per-trade. My contribution is the independent confirmation
+ the harsh-cost/Bonferroni-grade validation of the core; LAGV2's contribution is the refinement stack and
multi-cell scope. Next: validate LAGV2's broader band under my harsh-cost gates to pick the deployment.
