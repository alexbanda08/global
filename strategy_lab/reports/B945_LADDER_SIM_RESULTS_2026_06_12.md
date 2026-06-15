# B945 Two-Sided Price-Following Ladder Sim — 2026-06-12

**Gate verdict: NO-GO**

Script: `strategy_lab/wallet_hunt/_b945_ladder_follow_sim.py`  
Artifact: `strategy_lab/wallet_hunt/cache/_b945_ladder_sim.parquet`  
Universe: 4,729 btc-updown-15m windows, Apr 22 → Jun 11 2026 (50 days)

---

## Pre-registration (written before computing results)

**Strategy being simulated (from b945 r2 decode):**  
At slot open (~t+60s) place resting limit-buy ladders on BOTH tokens simultaneously. Clip size
proportional to price (`clip = 0.27 × price × $100`, capped at $100/side). Requote by following
the best bid every book tick (price-following, not static). Hold all fills to resolution; no taker
exits. Accounting chain-true: winner redeems at $1/share (no fee on REDEEM — validated vs b945's
2,010 REDEEM events); maker fills pay $0 + rebate income (+0.0015/sh).

**Why different from prior arms A/B/C/D:**
- Arms A/B (`_maker_queue_bt.py`): $1 fixed clip, per-fill markout scoring (wrong objective).
- Arms C/D (`_maker_ladder_bt.py`): static offset ladders, one-sided (wrong execution model).
- This sim: clip proportional to price, two-sided simultaneous, price-following requote, slug-level paired PnL.

**Cells (2 fill models × 2 ladder variants = 4 cells):**

| Cell | Fill model | Ladder |
|---|---|---|
| L1_fifo | FIFO strict lower bound | Join-bid only (1 level = best bid) |
| L1_prop | Proportional upper bound | Join-bid only |
| L3_fifo | FIFO strict lower bound | 3-level: best bid, bid-1c, bid-2c |
| L3_prop | Proportional upper bound | 3-level: best bid, bid-1c, bid-2c |

Budget: min(0.27 x best_bid x $100, $100) per side per slug (split evenly across levels).  
Queue: L25 displayed size at each level (resolve_size for artifact zeros).  
Requote: on every book tick where best bid changes, shift all levels + reset queue.

**Pre-registered go/no-go gate (all three must hold under FIFO):**
1. `pvs_med <= 0.98` (achieving meaningful discount vs 1.00)
2. `pair fraction >= 44%` (paired shares / total filled shares — matching b945's 44%)
3. `net CI95 lower bound > 0` (bootstrap CI on per-slug net PnL)

**Basis:** b945 achieves pvs ~0.97, 44% pair fraction, net +$4.2/slug + $2.3/slug rebates.
If FIFO cells cannot reach pvs < 0.98 at >=44% pair fraction, the conclusion is that his edge
is an infra+rebate moat (sub-second requote queue priority we cannot replicate).

---

## Results

### Cell table (4,729 windows, 50 days)

```
Cell            %both     pf   pvs_med   %<1.0  %<0.98  pair$/w   res$/w  net$/w    CI_lo    CI_hi  ex-top2
--------------------------------------------------------------------------------------------------------------
L1_fifo         70.2%  28.9%    0.9393   65.1%   58.6%   +1.878   -2.192  -0.195   -0.531   +0.154   -0.301
L1_prop         74.6%  24.7%    0.7737   93.5%   91.3%   +4.329   -4.550  -0.118   -0.402   +0.171   -0.181
L3_fifo         70.4%  28.1%    0.9540   63.1%   56.9%   +1.268   -1.626  -0.277   -0.574   +0.036   -0.374
L3_prop         74.6%  27.0%    0.8305   91.4%   88.1%   +2.972   -3.181  -0.130   -0.389   +0.129   -0.182
```

### b945 ground truth (r2 decode, 1,562 slugs)

```
GT              ~77%   44%    0.970   ~77%    47%    +22.71  -18.78   +4.23     n/a      n/a      n/a
```

---

## Gate verdict

```
L1_fifo: pvs_med=0.9393(ok)  pf=28.9%(FAIL)  CI=[-0.52,+0.16](FAIL)  -> FAIL
L3_fifo: pvs_med=0.9540(ok)  pf=28.1%(FAIL)  CI=[-0.57,+0.04](FAIL)  -> FAIL

GATE: NO-GO
```

Two of the three gate criteria fail. pvs criterion passes (both FIFO cells achieve median pvs
well below 0.98). Pair fraction and CI both fail.

---

## Interpretation

### pvs passes: the discount channel is real

Our simulated join-bid quotes achieve median pvs 0.939–0.954, with 57–59% of slugs landing
below pvs 0.98. This confirms the market genuinely trades two-sided below 1.00 when joining
best bids. The underlying price mechanic exists.

### pair fraction fails: fill throughput gap is the bottleneck

Our simulated pair fraction is 28–29%, vs the 44% gate and b945's actual 44%. In dollar terms,
paired PnL is only +$1.3–1.9/slug vs b945's +$22.71/slug — roughly 12x less. The cause is
throughput: b945 accumulates ~100–150 fills per window through rapid sub-second requoting at
many $5 clips (~$726/slug deployed). Our sim places at most a few clips per level per tick,
and queue position under FIFO (median 60–560 shares ahead at join = 7–60x our clip size)
means most quotes age out unfilled. Even the proportional (optimistic upper-bound) cells only
reach 25–27% pair fraction with pvs inflated to 0.77–0.83 (unrealistically good book walk).

### CI fails: residual drag dominates at low pair fractions

At 29% pair fraction, the residual 71% of fills faces full resolution risk. Residual PnL is
-1.6 to -4.6/slug, eating all the paired gain plus more. This is the arithmetic of the
strategy at insufficient throughput: paired gain exists only when you can balance the two sides
within a slug. Below ~40% pair fraction, residual drag dominates and the net is negative.

### Root cause: execution infrastructure moat

B945's edge requires three things we cannot replicate from our queue position:

1. **Sub-second requote cadence** (~100–150 fills/window) that keeps his bids near queue top
   via constant cancels and re-places, not passive waiting.
2. **High clip count at small size** ($5 clips across many price levels through the window)
   generating the 44% pair fraction. Our $100 budget in 1–3 clips per tick cannot match this.
3. **Maker rebate tier** — $3,623 of his $10k net (36%) is rebates from $1.24M volume.
   Our 29% pair fraction generates negligible rebate income (~$0.002–0.003/window).

The prior session conclusion stands: **his edge = infra + rebate moat, not a replicable
signal**. The price-following two-sided mechanic is real; the economics are not accessible
from our queue depth and clip cadence.

---

## TVRUST note (for reference)

If the gate had passed, the recommended path would have been: port the price-following
two-sided bid loop into the TVRUST sub-second requote engine at `Desktop/TVRUST`. The critical
parameters are clip proportional to price, join at best bid + deeper levels, and requote under
200ms on level change. Gate is NO-GO so this path is parked. However: if a future TVRUST
deployment achieves demonstrated sub-second fill cadence in live shadow (>= 100 fills/window),
a forward shadow with pvs tracking and pair fraction measurement is the correct next test —
the mechanic is real, only the execution bar is high.

---

## Summary table

| Metric | Gate | Our sim (FIFO best) | b945 actual |
|---|---|---|---|
| pvs median | <= 0.98 | 0.939 (L1_fifo) | ~0.970 |
| Pair fraction | >= 44% | 28.9% | 44% |
| Net CI95 lower | > 0 | -0.52 (L1_fifo) | +$4.23/slug |
| Gate passed | — | NO | YES |

**Deployment recommendation: DO NOT deploy.** Revisit only if TVRUST or equivalent
sub-second infra can demonstrate >= 44% pair fraction in a forward live shadow (minimum
200 slug sample). The pvs channel is confirmed real; only the execution bar blocks deployment.

---

_Pre-registration written and verified before results computed. Gate verdict NO-GO is binding per the pre-registered criteria from `B945_INVENTORY_SUMARB_DECODE_2026_06_12.md` §6._
