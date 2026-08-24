# Live vs shadow, head-to-head — and what deploys next — 2026-08-05 04:00 UTC

`poly_ladder_btc_5m_v3_live` has traded a lot more since the first read: **156 fills, 35
tokens, 19 windows, $320.20 deployed** (was 41 fills / 5 windows). Every fill mapped to a
window+side+settlement by `clob_token_id` via gamma `/events?slug=` — attribution is exact.

Live PnL accounting is now booking (`day_realized_pnl_usd` = −0.51, `day_spent_usd` = 88.68,
new `committed_sh` field) — someone shipped part of the fix. `day_notional_usd` still reads 0.0.

---

## 1. Live, split by what it actually did

17 settled windows ($278.76 deployed). Maker fills → no taker fee.

| | windows | deployed | **PnL** | $/window | pair_frac | **wtd pair sum** |
|---|---:|---:|---:|---:|---:|---:|
| **PAIRED** (the strategy) | **13** | $249.66 | **−$20.15** | **−1.550** | 0.737 | **0.9059** |
| single-sided (unhedged bets) | 4 | $29.10 | **+$40.98** | +10.245 | 0.000 | — |
| **net** | 17 | $278.76 | **+$20.83** | | | |

*(2 further windows still open, MTM +$7.20, excluded.)*

**The headline +$20.83 is not the strategy.** 24% of live windows took a completely unhedged
directional position; those four coin flips won $40.98 and mask the fact that the 13 windows
where the ladder actually paired **lost $20.15.**

---

## 2. Head-to-head: live vs every arm on the SAME 13 windows

| | traded | **net** | $/window | **pair sum** | maker_sh/win | paired leg | residual leg |
|---|---:|---:|---:|---:|---:|---:|---:|
| `_v31_d1` paper | 10 | **+$27.36** | +2.736 | **0.7885** | 24.4 | +18.55 | +8.44 |
| `_v31_c2` paper | 9 | +$24.09 | +2.677 | 0.8260 | 32.1 | +16.91 | +6.74 |
| `_v31_c2rcg` paper | 9 | +$21.52 | +2.391 | 0.8473 | 28.5 | +13.29 | +7.85 |
| `_v3` paper | 9 | +$17.56 | +1.951 | 0.8236 | 19.0 | +9.35 | +7.95 |
| `_v31_rcg` paper | 9 | +$11.60 | +1.289 | 0.8472 | 22.2 | +10.91 | +0.39 |
| **`_v3_live` twin (paper)** | 10 | **+$6.03** | +0.603 | **0.8519** | 21.6 | +12.23 | −6.53 |
| **LIVE (real fills)** | **13** | **−$20.15** | **−1.550** | **0.9059** | **43.7** | **+19.70** | **−39.85** |

**Its own paper twin said +$6.03. Live delivered −$20.15.** A $26 swing on $250 deployed —
the sim overstates by ~10% of notional on these windows.

### Three divergences, all in the same direction

| | twin paper | live | ratio |
|---|---:|---:|---|
| windows traded (of 13) | 10 | 13 | **1.3×** |
| shares filled per window | 21.6 | 43.7 | **2.0×** |
| pair sum paid | 0.8519 | 0.9059 | **+5.4¢/share worse** |
| margin per paired share | 14.8¢ | 9.4¢ | **63.5% capture** |

The sim is **not** optimistic about *whether* you fill — live fills more often, in more
windows, in bigger size. It is optimistic about *at what price*. That combination has one
reading: **live gets filled when the book sweeps through the ladder**, taking every rung at
once at prices the sim's print-matcher never reproduces. Textbook adverse selection, now
measured: 2× the inventory at 64% of the margin.

---

## 3. The most important number: the live arb leg WORKS

Decomposing live's 13 paired windows (209.4 paired shares, 149.6 residual shares):

| leg | live |
|---|---:|
| **paired lock** `paired_sh × (1 − 0.9059)` | **+$19.70** |
| **residual leg** | **−$39.85** |
| total | −$20.15 |

**Even paying 0.906 instead of 0.852, the arb leg returned +$19.70 on $249.66 = +7.9%.**
The strategy's core survived contact with real fills. What killed the window set is the
41.7% of shares that never got paired and rode to settlement naked — the same leg that the
[degradation forensics](TVRUST_V3_DEGRADATION_FORENSICS_2026_08_04.md) proved has been
structurally negative-EV in paper since day one, now 2× larger because live over-fills.

---

## 4. The rest of the fleet, refreshed (9 days, paper)

| sleeve | traded | net | $/win | pvs |
|---|---:|---:|---:|---:|
| `btc_5m_v31_c2rcg` | 1,818 | $2,991 | 1.645 | 0.8232 |
| `btc_5m_v31_c2` | 2,014 | $2,547 | 1.265 | 0.8221 |
| `btc_5m_v31_rcg` | 2,013 | $2,176 | 1.081 | 0.8182 |
| `btc_5m_v31_d1` | 2,317 | $2,024 | 0.873 | 0.8156 |
| `btc_5m_v3` | 2,008 | $1,740 | 0.866 | 0.8233 |
| `btc_5m_v3_live` twin | 1,699 | $1,392 | 0.819 | 0.8177 |
| `eth_5m_v3` | 1,458 | $429 | 0.294 | 0.8290 |
| `btc_15m_v3` | 471 | $190 | 0.403 | 0.8130 |

`sumpair_osc` (9d, separate family): BTC +$60.65 walk (locked +113.28, residual −477.19);
ETH +$60.45 walk (locked +334.35, residual −415.17). **Same signature — locked leg positive,
residual leg catastrophic** — at ~$6.7/day. Not a deployment candidate.

---

## 5. What deploys next

### Not a new sleeve. Flip `rcg` ON in the live sleeve you already have.

The live evidence has changed the argument from theoretical to measured:

- Live's **arb leg is +$19.70** — it works at real prices.
- Live's **residual leg is −$39.85** — it is 2× the arb, and it is the entire loss.
- `rcg` is the *only* knob that touches the residual, and it is a **pure exit rule**: no size
  change, no price change, no new placement — therefore **no new fill-model risk**, which is
  the one thing you cannot currently afford to add.
- It needs **no new sleeve and no new code**: set `TV_LADDER_RCG_LO=0.30` / `TV_LADDER_RCG_HI=0.60`
  on the live config. One restart.

Counterfactual on the 13 windows: flattening the residual entirely turns −$20.15 into +$19.70.
Even partial rcg coverage (the 0.30–0.60 band) is the highest-leverage change available.

### Three blockers to clear in the same deploy

**1. Ban unhedged windows.** 4 of 17 live windows had *zero* pairing — pure directional bets
totalling $29.10. They won $40.98 this time; that is luck, and it is masking the real result.
Gate: do not size a second clip on a side until the opposite leg has at least one fill, or
flatten at T−tail if still single-legged.

**2. `TV_LADDER_PAIR_MAX_SUM=0.99` is not holding.** Window `…1785900600` paired at
**1.0275** — buying both legs for more than they can ever pay, a guaranteed −2.75% on the
paired portion. It only escaped because the residual won. Fix the gate.

**3. Verify rcg's flatten can actually execute.** The T−tail backstop is already failing on the
Polymarket **$1.00 venue minimum** (blocked selling 36 sh at $0.72 notional). rcg flattens
through the same path — if clips stay at $2, rcg will hit the identical wall and do nothing.
Raise the flatten clip above $1.00 or the whole change is inert.

Plus the outstanding items from yesterday: per-position (not per-order) side cap — it was
breached 5.9× — and a `day_notional` meter that counts (still reading 0.0).

### Hold everything else

- **c2rcg / c2** — both are *size* changes. Live already over-fills 2× at 64% margin capture;
  doubling the clip attacks the exact axis that is failing. Revisit only after live pair sum
  is measured at ≤0.88.
- **d1** — best pair sum of any arm here (0.7885) and top of this 13-window table, but it also
  carries the worst residual over its lifetime, and its lifetime paired Δ vs base is t=1.47
  (fails). Its good showing here is 10 windows of lucky residual (+$8.44). Not promotable —
  but **`d1 × rcg` is now the most interesting bench hypothesis you have** (best entry price ×
  residual removal). Pre-register it as paper, don't deploy it.
- **eth_5m / 15m / sumpair** — ⅓ to ⅕ the edge, or negligible $/day. Nowhere near the front of
  the queue.

### The one pre-registered readout that matters

After the rcg flip + the three fixes, on the live sleeve:

> **live pair sum ≤ 0.88 and live residual leg ≥ −$0.30/window, at n ≥ 30 paired windows.**

Pass → promote c2rcg (size becomes the right question). Fail on pair sum → the sim's fill
model must be re-derived against the recorded tick tape before any arm is promoted. Fail on
residual only → rcg's flatten isn't executing; check the $1.00 minimum again.

---

## 6. Power caveat

13 paired windows over ~5 hours. **The −$20.15 has very wide error bars** — do not treat it as
an expectancy. The well-powered measurement here is the **pair sum: 0.9059 vs 0.8519,
share-weighted over 209 paired shares across 13 independent windows.** That gap is the finding.
The PnL is an illustration of what the gap costs, not an estimate of the edge.
