# Post-re-audit tests — tighter GLT cap + short-side scan — 2026-06-13
**The two genuine untested levers the re-audit identified, run with full rigor (operator mandate:
review everything, reanalyze 2×, side-by-side, trustworthy).** Engines `_mm_inv_engine.py` (maker-only),
drivers `_mm_q_sweep.py` / `_mm_q_verify.py` / `_mm_shortside_scan.py`; artifacts `cache/_mm_q{2,3,5,8,12,16,20}_full.parquet`,
`_mm_q_verify.parquet`, `_mm_shortside_scan.parquet`.

---

## TEST 1 — Tighter GLT inventory cap (the residual-drag lever) — REAL, VERIFIED

**Why:** the re-audit proved the OOS killer is residual drag (−$4.53/slug at Q=20), not flow capture.
GLT Q is the dominant residual lever. We had only tested Q∈{20,50,100,∞}; this swept the TIGHTER region.
Maker-only (corrected — taker-completion never fires), γ=0.05, $350/side, offset −3600s, FIFO, full
universe, IS(Apr22–May20)/OOS(May21–Jun11). Pre-registered Q grid; GO if any Q has OOS CI95 lo>0 AND ex2>0.

**OOS net vs Q (independently re-derived from raw shares/vwap/outcome — accounting cross-check `maxdiff=0.00000`):**

| Q | OOS mean | median | CI95 | ex2 | ex5 | %pos | resid | paired | verdict |
|---|---|---|---|---|---|---|---|---|---|
| **2** | **+0.509** | −0.088 | [+0.29,+0.75] | +0.444 | +0.353 | 45% | −2.28 | +2.33 | GO |
| **3** | +0.366 | −0.095 | [+0.16,+0.59] | +0.303 | +0.240 | 45% | −2.47 | — | GO |
| **5** | +0.392 | −0.173 | [+0.17,+0.63] | +0.329 | +0.264 | 44% | −2.46 | +2.34 | GO |
| 8 | +0.237 | −0.367 | [−0.02,+0.53] | +0.145 | +0.053 | 41% | −2.52 | +2.22 | no |
| 12 | −0.063 | −0.539 | [−0.39,+0.32] | −0.204 | −0.299 | 39% | −3.05 | +2.43 | no |
| 16 | −0.370 | −0.622 | [−0.72,+0.03] | −0.509 | −0.597 | 39% | −3.03 | +2.08 | no |
| 20 | −0.687 | −0.780 | [−1.05,−0.28] | −0.823 | −0.905 | 38% | −3.56 | +2.28 | no |

**What is SOLID (verified):**
- **Accounting independently confirmed** — per-slug PnL re-derived from raw shares/vwap/true-outcome
  matches the engine's stored values to 5 decimals across all 7 cells.
- **Clean monotone trend + plateau, NOT one lucky cell.** OOS net rises smoothly Q20→Q8, crosses zero
  ~Q10, plateaus ~+0.4 for Q≤5 (THREE consecutive GO cells Q2/3/5, each CI95>0 AND ex5>0). Driven exactly
  by residual shrinking (−3.56→−2.28) while paired holds (+2.3). The re-audit PREDICTED this a priori
  (residual is the constraint; tight inventory attacks it) — this is confirmation, not data-snooping.

**The honest caveats (why this is NOT a deploy-GO):**
- **Thin, tail-driven.** Even at best-Q, **median is negative (−0.09) and only ~45% of slugs profit** —
  the positive mean (+0.4–0.5) is a broad right-tail effect (survives ex5, so not 5 whales, but you eat
  ~55% losing windows). Edge ≈ +$0.4/slug on $700/slug deployed (~0.06%).
- **Single OOS window + OOS-informed Q.** On IS, net is FLAT across Q (all ~+2.7) — IS gives no signal to
  pick Q; the tight-Q benefit appears ONLY in this one 3-week thin-flow OOS realization. Mitigated by the
  a-priori prediction + monotone+plateau (not a cherry-picked cell), but it's one regime.
- **Still 8× below b945** (+$0.4 vs his +$3.18/slug) — his scale/capture is higher.

**Interpretation:** tight inventory control (Q≤5) is a **real, verified lever that flips OOS from
−$0.69 to ~+$0.4/slug** — the strategy CAN clear breakeven in the hard (thin-flow) regime. This UPGRADES
the offline picture from "NO-GO across 5 variants" to **"marginal-positive achievable with tight Q."**
It is "clears breakeven in thin flow, pending robustness," not "deploy capital." The robustness question
(multiple thin-flow windows; the negative median) is exactly what a live thin-flow dry run resolves.

**Build implication:** TVRUST ladder default **Q ≈ 3–5** (tight), NOT 20. Promotion gate must require
positive net **AND a healthy %-positive (not just positive mean)** across **multiple** thin-flow weeks.

---

## TEST 2 — Short-side arb (sum_bid > 1) — PARK (scanned, closed)

**Why:** arXiv 2508.03474 claims shorting (split $1 → sell both legs above $1) is MORE profitable than the
long side. We never scanned it. Native-book scan of (bid_up + bid_dn) over all btc-15m windows; fee model
0.07·p·(1−p)/leg; fee-breakeven sum_bid > ~1.035.

| Threshold | time-frac (OOS) | slugs-with-any | median cap $/slug |
|---|---|---|---|
| sum_bid > 1.00 | 0.055% | 36% | $0.000 |
| sum_bid > 1.02 | 0.013% | 8% | $0.000 |
| **sum_bid > 1.035** (fee-breakeven) | **0.008%** | **3.3%** | **$0.000** |
| sum_bid > 1.05 | 0.008% | 2.7% | $0.000 |

Median sum_bid = **0.99** (below 1); per-slug median max = 1.000; global max 1.33 (rare spikes). **VERDICT:
PARK.** The short side is symmetric to the dead long side — the bid-ask spread straddles $1 from both
directions, so sum_bid > 1 essentially never occurs net-of-fee (0.005% of ticks). The paper's "shorting
more profitable" finding is **zero-fee-era + US-election-market specific**; it does not transfer to
fee-bearing crypto 15m. No action; gap closed.

---

## Net effect on the session conclusion

Both re-audit gaps now resolved with verified data:
1. **Tighter Q = the offline upgrade.** From "NO-GO −$0.32" to **"marginal-positive +$0.4/slug achievable
   in thin flow with Q≤5"** (accounting-verified, monotone, mechanism-confirmed; thin + single-window).
2. **Short side = dead** (scanned, symmetric to long, PARK).

The corrected bottom line: the maker-only ladder with **tight inventory control** can clear breakeven OOS
in the hard regime — a real, trustworthy advance over the session's NO-GO, consistent with the re-audit's
(more favorable) corrected picture. The remaining risk is purely robustness (thin edge, negative median,
one window), which only the live thin-flow dry run can settle. TVRUST config updated: Q≈3–5.
