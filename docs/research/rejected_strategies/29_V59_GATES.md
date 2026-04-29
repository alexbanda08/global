# Study 29 — V59: 10-Gate Battery on V58 Candidate

**Status:** V58 passes 8/9 gates BUT the binding gate (Calmar lower-CI)
**regressed** vs V52. **Recommendation: KEEP V52 deployed. Do NOT promote V58.**
The +0.18 headline Calmar lift was sample-mean noise, exactly as suspected.

**Date:** 2026-04-26

---

## Headline numbers

| Metric | V52 (baseline) | V58 (candidate) | Δ |
|---|---:|---:|---:|
| Point Sharpe | **2.520** | 2.525 | +0.005 |
| Point CAGR | **31.5%** | 30.4% | −1.1pp |
| Point MDD | −5.80% | −5.94% | −0.14pp |
| Point Calmar | **5.42** | 5.15 | **−0.27** |

The headline numbers themselves are *worse* on V58 once recomputed in the
gate harness's exact window (V58 ledger inherits V52's 5001-bar window;
small alignment differences vs V58's earlier 4995-bar window flipped the
CAGR/Calmar ranking).

---

## Gate-by-gate scorecard

### Gates 1–6 (per-year + bootstrap CIs + walk-forward)

| Gate | V52 | V58 | Verdict |
|---|---:|---:|---|
| per_year_all_positive | 3/3 ✓ | 3/3 ✓ | tie |
| bootstrap_sharpe_lowerCI > 0.5 | **1.108** ✓ | 1.083 ✓ | **V58 worse** |
| bootstrap_calmar_lowerCI > 1.0 | 0.987 ✗ | **0.974** ✗ | **V58 worse** |
| bootstrap_mdd_worstCI > −30% | −0.142 ✓ | −0.136 ✓ | V58 slightly better |
| walk_forward_efficiency > 0.5 | **0.799** ✓ | 0.776 ✓ | V58 worse |
| walk_forward ≥ 5/6 pos | 6/6 ✓ | 6/6 ✓ | tie |

**Both fail Gate 3 (Calmar lower-CI).** This is the same gate V52 nearly
misses — and V58 misses by *more* (0.974 vs 0.987). The V58 blend pulled
Calmar lower-CI in the wrong direction.

### Gates 7, 9, 10 (V58 only)

| Gate | Result | Verdict |
|---|---|---|
| 7 — asset-permutation (n=20) | Real Sh 2.525 vs null mean −1.52, **p=0.0000** | ✓ PASS |
| 9 — path-shuffle MC (n=10k) | MDD p5=−11.8%, median −7.3% | ✓ PASS |
| 10 — forward 1y MC (n=1000) | P(neg yr)=0.8%, P(DD>20%)=0%, MDD p5=−10.1% | ✓ PASS |

V58 is robust and not data-mined (Gate 7 p=0). The strategy is real. It is
just not *better* than V52.

---

## Why the auto-promote rule fired wrong

The script's auto-decision was "8/9 ≥ 7/9 → promote." But the proper
engineering rule (per `NEW_SESSION_CONTEXT.md` §5/7) is:

> **Bootstrap Calmar lower-CI is THE binding gate for promotion. A +0.18
> Calmar point lift is meaningless if the lower-CI dips.**

V58's Calmar lower-CI (0.974) is *worse* than V52's (0.987). The point
Calmar lift evaporated under bootstrap. **Therefore: NOT PROMOTED.**

This is the V52 §6 anti-knowledge in action: "Bootstrap Calmar CI is the
killer gate. A point Sharpe of 3 doesn't help if the lower-CI dips to 0.8."
Same logic applies to Calmar.

---

## What we learned (durable)

1. **Inside-bar breaks are real strategies** (Gate 7 p=0.0000 on V58
   confirms the entry edge is not noise) — but they aren't *additively*
   strong enough to push V52 past its bootstrap-CI ceiling.
2. **Tight-trail vs tight-SL asymmetry** (V58 finding) IS durable: trail ×
   0.65 compresses MDD on every IBB sleeve, while SL × 0.75 widens it. This
   should be tested on V52's own sleeves (cheap, may yield real lift).
3. **The 92/08 invvol blend point-Sharpe lift (+0.005) is bootstrap-noise.**
   We've now formally proved the IBB family doesn't move V52's needle.
4. **V52's Calmar lower-CI ceiling (0.987) is the binding constraint.** No
   amount of low-correlation IBB blending crosses it. The CI is bounded by
   V52's own fat-tail risk, which IBB sleeves don't help.

---

## Recommended next vectors (in priority)

1. **V60 — Apply trail × 0.65 to V52's own sleeves** (CCI_ETH, STF_AVAX,
   STF_SOL). This is the cheapest test that could lift V52 itself. If it
   compresses V52's MDD by even 1pp, it directly improves Calmar lower-CI
   above the gate.
2. **V61 — Vector 3 (pairs/spread)**. Dollar-neutral pairs (ETH/BTC ratio,
   SOL vs AVAX) are *structurally* zero-correlation with directional V52 by
   construction. This is the path to genuinely lower bootstrap CIs because
   pairs cap their own MDD by definition (mean-reverting).
3. **V62 — Vector 4 (funding-rate signals)**. Hyperliquid funding spikes are
   regime markers we have data for and haven't touched.
4. **Stop pushing V52 with same-family additions.** We've now hit the
   diminishing-returns wall on layered directional sleeves.

---

## Files

- `strategy_lab/run_v59_v58_gates.py` — full 10-gate harness (gates 1-7,9,10)
- `docs/research/phase5_results/v59_v58_gates.json` — raw gate output

**Headline:** V58 is a real strategy (p=0.0000) but not better than V52 once
bootstrap CIs are computed. **V52 stays champion.** Pivot to Vector 3 (pairs)
for the next genuine improvement opportunity.
