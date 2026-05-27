# Naive-Sum Overlap Bug — Corrections Notice — 2026-05-26

**Author:** Cross-round corrections sweep (Round 6 follow-up)
**Date:** 2026-05-26
**Status:** SINGLE SOURCE OF TRUTH for what the deployable PnL actually is

---

## TL;DR

Prior session synthesis reports (Rounds 1-5) quoted combined deployable PnL by
**summing per-sleeve PnL** (e.g. "$85-95k/28d at $25 notional"). This is
**WRONG**. Multiple sleeves fire on the SAME chainlink slugs (Jaccard slug
overlap of 0.4-1.0 on BTC 5m), so each slug yields ONE bet not N bets. Agent PP
(Round 6) ran the pairwise overlap audit and built a deploy manifest using
greedy union semantics + OOS filtering of negative-PnL sleeves.

| Metric | Naive (WRONG, prior rounds) | Real (dedup, Round 6 PP) |
|---|--:|--:|
| Combined $/28d at $25 notional | $85-95k | **$20,501** |
| Combined $/day at $25 notional | $3,000-3,400 | **$732** |
| Combined $/day at $250 notional | ~$30k | **$7,322** |
| Annual run-rate at $250 notional | $11-12M | **$2.67M** |
| Inflation factor of prior numbers | — | **~4.2× too high** |

**Authoritative deployable: $20,501/28d at $25 notional = $7,322/day at $250 =
$2,672,455/year run-rate.**

Source of truth: `data/v4/canonical/_results/_overlap_audit_2026_05_26/final_deploy_manifest.csv`
(26 rows, 12 DEPLOY, 4 PAPER_FIRST, 3 SKIP_OVERLAP, 7 SKIP_NEGATIVE_PNL).
Methodology + per-sleeve breakdown: `strategy_lab/reports/SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md`.

---

## 1. The bug

### What was done (WRONG)
Earlier synthesis reports built combined deployable estimates by:
```
combined = sum(sleeve.expected_28d for sleeve in deploy_roster)
```

### Why it's wrong
On BTC 5m especially, the same chainlink resolution slug is "captured" by
multiple sleeves (S6 hybrid_v1, S7 base, R2 micro variants, R5 microprice
overlays, hawkes, etc.) because they all fire on similar momentum windows.
Pairwise Jaccard on **firing slugs** (not just sleeve labels) ranges 0.4-1.0
between top BTC 5m sleeves. Each chainlink slug only resolves once, so the
"effective" PnL of two fully-overlapping sleeves is NOT the sum; it's `max`
(or the slug's actual outcome × one bet's notional).

### What is correct
```
combined = greedy_union(sleeves) where each slug is counted exactly once,
           assigned to the highest-priority sleeve that fires it
         + marginal contribution of subsequent sleeves on their UNIQUE slugs
```

This is what `final_deploy_manifest.csv` does (Agent PP, Round 6). The
`marginal_28d` column on each row is the per-sleeve incremental PnL after
accounting for slugs already claimed by higher-priority sleeves.

---

## 2. Per-report corrections

The table below catalogs **every** naive-sum quote found in the affected
reports, paired with the correct number from the dedup manifest.

### 2.1 Round 5 synthesis (`ROUND5_SYNTHESIS_2026_05_26.md`)

| Line | Old (NAIVE, WRONG) | Correct (dedup) | Notes |
|---:|---|---|---|
| 31 | "grand total deployable: ~$85-95k/28d at $25 ≈ $30k/day @ $250 ≈ $11M/year" | **$20.5k/28d @ $25 = $7.3k/day @ $250 = $2.67M/year** | Top-line headline; primary correction |
| 218 | "R1 \| $55-65k/28d" | [historical R1 estimate — needs rerun with dedup; do not cite without recompute] | R1 not separately recomputed |
| 219 | "R2 \| $90-110k/28d" | [historical R2 estimate — needs rerun with dedup; do not cite without recompute] | R2 not separately recomputed |
| 220 | "R3 \| $50-60k/28d" | [historical R3 estimate — needs rerun with dedup; do not cite without recompute] | R3 not separately recomputed |
| 221 | "R4 \| $70-80k/28d" | [historical R4 estimate — needs rerun with dedup; do not cite without recompute] | R4 not separately recomputed |
| 222 | "R5 \| $85-95k/28d" | **$20.5k/28d** (this IS the dedup answer at end of R5; all prior rounds rolled into it) | R5 superseded by R6 PP audit |
| 233 | "R5 net additions: +$15-25k/28d" | R5 marginal contribution captured in greedy manifest already | — |
| 236 | "Realistic deployable: ~$85-95k/28d at $25" | **$20,501/28d at $25** | — |
| 239 | "≈ $11-12M/year @ $250 notional" | **$2.67M/year @ $250 notional** | — |

### 2.2 Round 3 synthesis (`ROUND3_SYNTHESIS_2026_05_26.md`)

| Line | Old (NAIVE) | Correct | Notes |
|---:|---|---|---|
| 15 | "scale-up… $90-110k/28d to ~$51-70k/28d" | [historical estimate — needs rerun with dedup] | Still naive after R3 OOS gate |
| 221 | "~$51,500 / 25d ≈ $2,060/day at $25 notional, ~$20,600/day at $250" | Use the FINAL dedup number: $7,322/day at $250 | — |
| 277 | "Realistic combined: ~$50-65k / 28d at $25 = $18-23k/day @ $250" | **$20,501/28d at $25 = $7,322/day @ $250** | — |

### 2.3 Round 2 / new-indicators synthesis (`NEW_INDICATORS_SYNTHESIS_2026_05_26.md`)

| Line | Old (NAIVE) | Correct | Notes |
|---:|---|---|---|
| 29 | "Total new uplift: ~$25-35k/28d at $25, ~$8-12k/day @ $250" | Marginal of these sleeves captured in greedy manifest | — |
| 232 | "Realistic combined deployable (with overlap dedup): ~$90-110k / 28d" | **$20,501/28d** (the "with overlap dedup" claim was incorrect — overlap was only partially modeled) | — |
| 234 | "~$32-39k/day = $11.7-14.3M/year run-rate" | **$7,322/day = $2.67M/year** | — |
| 237 | "scale-up from $55-65k/28d → $90-110k/28d" | Both numbers naive; correct end-state $20.5k/28d | — |
| 399 | "Combined deployable scale-up: $55-65k/28d → $90-110k/28d at $25" | **$20.5k/28d at $25** | — |

### 2.4 Round 1 / master deploy spec (`MASTER_DEPLOY_SPEC_2026_05_26.md`)

| Line | Old (NAIVE) | Correct | Notes |
|---:|---|---|---|
| 1260 | "Realistic deployable total: ~$55-65k/28d at $25 = ~$20-23k/day @ $250" | **$20,501/28d at $25 = $7,322/day @ $250** | — |
| 1262 | "18-22× the shipped baseline" | Recompute: $20,501 / $2,949 ≈ **7×** the shipped baseline | — |

### 2.5 Per-sleeve catalog (`PER_SLEEVE_CATALOG_2026_05_26.md`)

| Line | Old (NAIVE) | Correct | Notes |
|---:|---|---|---|
| 343 | "Top-20 combined ($25): ~$55-65k/28d after dedup for slug overlap" | **$20,501/28d at $25** (the "after dedup" claim was incorrect — only partial dedup applied) | — |
| 385 | "Aggressive (all sleeves, ignoring overlap): ~$+81k/28d" | This IS the naive sum; per-sleeve numbers in the catalog are CORRECT, the combined number is not | — |

### 2.6 PDFs

| File | Status | Action |
|---|---|---|
| `FINAL_CONSOLIDATED_REPORT_2026_05_26.pdf` | Contains R1-R4 naive numbers (~$75k/28d R4 estimate) | **SUPERSEDED** by `FINAL_DEPLOY_READY_2026_05_26.pdf` |
| `ROUND5_REPORT_2026_05_26.pdf` | Cover claim "$85-95k/28d" | **SUPERSEDED** by `FINAL_DEPLOY_READY_2026_05_26.pdf` |
| `PER_SLEEVE_CATALOG_2026_05_26.pdf` | Quotes per-sleeve sums | Per-sleeve metrics CORRECT; combined estimate SUPERSEDED |
| `FINAL_DEPLOY_READY_2026_05_26.pdf` | **CORRECT** (uses dedup methodology) | Authoritative deploy doc |

PDFs were NOT regenerated — the source MD files with banners now carry the
corrections in-line. For PDFs, prefer `FINAL_DEPLOY_READY_2026_05_26.pdf`.

---

## 3. Deploy manifest audit (Agent PP `final_deploy_manifest.csv`)

Verified 2026-05-26 against `data/v4/canonical/_results/_overlap_audit_2026_05_26/final_deploy_manifest.csv`:

| Status | Count | Sum expected_28d ($25 notional) |
|---|--:|--:|
| DEPLOY | 12 | $37,506 (raw, before union dedup) |
| PAPER_FIRST | 4 | $15,231 (raw; 0.5x applied in combined estimate) |
| SKIP_OVERLAP | 3 | — (≥90% overlap with primary, fully redundant) |
| SKIP_NEGATIVE_PNL | 7 | — (negative in OOS lockbox) |
| **TOTAL** | **26** | — |

**Reconciliation to the $20,501 headline (from `SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md` §5):**

| Component | Method | $/28d @ $25 |
|---|---|--:|
| Mode A union of 12 DEPLOY sleeves | greedy union, count each slug once | $19,023 |
| S2 fade BTC/ETH (paper-first, 0.5x notional) | assumed disjoint | $1,229 |
| R1 lite/top2 paper-first (0.5x marginal) | marginal vs DEPLOY union | $249 |
| **REALISTIC COMBINED** | | **$20,501** |

At $250 notional (10×): **$205,010 / 28d = $7,322/day = $2,672,455/year**.

### Anomalies found in manifest audit
- None of substance. The 12 DEPLOY rows all have positive `expected_sum_28d`.
- `R5_btc_s15_v1_plus_mp_no_extreme` has `marginal_28d = 0.000` exactly —
  flagged for sanity; verified this is because it's redundant with primary
  sleeves on the union mask but still listed as DEPLOY for diversification.
- `R5_eth_s6_v1_plus_mp_change_with` and `R5_hawkes_sol_5m_off120` have
  NEGATIVE `marginal_28d` — they're DEPLOY for diversification reasons but
  their slugs are mostly already-captured losers. Worth reviewing whether
  to demote to PAPER_FIRST.
- 3 SKIP_OVERLAP rows show overlap_with_primary_pct of 100% (S6TA_btc_top1),
  90.6% (poly_updown_eth_5m_s6_hybrid_v1), 90.6% (S6TA_eth_top1) — correctly
  filtered out as fully-redundant.

---

## 4. What WAS correct in prior reports

**Per-sleeve metrics (n, WR%, $/tr, sum per individual sleeve)** in all prior
reports ARE CORRECT. The bug was ONLY in combining them into a "total" without
dedup. Specifically:

- Cyclops S7 BTC 5m base: n=3,762, WR 76.1%, $/tr $1.72, sum $5,674/28d — CORRECT
- R2 btc_5m_s1_5_3bps: n=6,355, WR 68.7%, $/tr $1.27, sum $7,055/28d — CORRECT
- R5 microprice univ_5m_rf_ribbon: n=7,028, WR 63.0%, $/tr $1.09, sum $6,697/28d — CORRECT
- Every other per-sleeve row in `final_deploy_manifest.csv` — CORRECT

Use those numbers if you need to evaluate a SINGLE sleeve. Only the combined
"deploy roster total" was inflated.

---

## 5. Authoritative reports (DO use these)

These reports use the correct dedup methodology and supersede everything else:

1. `strategy_lab/reports/SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md` — methodology + manifest narrative
2. `strategy_lab/reports/ROUND6_SYNTHESIS_2026_05_26.md` — session synthesis with correct number
3. `strategy_lab/reports/FINAL_DEPLOY_READY_2026_05_26.pdf` — PDF deploy doc with correct cover
4. `data/v4/canonical/_results/_overlap_audit_2026_05_26/final_deploy_manifest.csv` — raw deploy manifest

This corrections doc (`NAIVE_SUM_CORRECTIONS_2026_05_26.md`) is the single
source of truth for "what changed and why" — cite it whenever you encounter an
old report with the inflated numbers.

---

## End
