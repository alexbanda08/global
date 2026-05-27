# Slug-Overlap Audit + Final Deploy Manifest

**Date:** 2026-05-26
**Window:** Apr 24 → May 25 2026 UTC (full 32d canonical)
**Fee model:** Legacy 2%-on-profit-only
**Pipeline:** `strategy_lab/overlap_audit_2026_05_26/`
**Manifest CSV:** `data/v4/canonical/_results/final_deploy_manifest.csv`

---

## TL;DR — what changed vs prior estimates

| Metric | Prior R5 estimate | This audit (corrected) | Change |
|---|--:|--:|--:|
| Realistic deployable / 28d @ $25 | $85-95k | **$20,501** | **-77%** |
| Realistic deployable / 28d @ $250 | $850-950k | **$205,010** | **-77%** |

The prior $85-95k figure naively SUMMED individual sleeve $/28d. After accounting for
slug-overlap (multiple sleeves firing on the same `(slug, fire_us, direction)` triple
yields ONE bet, not N bets), the realistic combined PnL is **~22% of the prior estimate**.

The "~50% overlap discount" heuristic in `ROUND5_SYNTHESIS_2026_05_26.md` understated the
overlap problem by ~2×. The S6/S15/R1/R2 family are nearly the same sleeve under different
names; they all fire on essentially the same BTC slug universe (Jaccard 0.4-1.0 on the
fire-key).

---

## 1. Pairwise overlap matrix

Top-15 most-overlapped pairs (fire-level Jaccard):

| Sleeve A | Sleeve B | Jaccard (fire) | Jaccard (slug) | Inter | Union | Dir agree |
|---|---|--:|--:|--:|--:|--:|
| `S6TA_eth_top1` | `poly_updown_eth_5m_s6_hybrid_v1` | 1.000 | 1.000 | 5,454 | 5,454 | 100% |
| `poly_updown_btc_5m_s6_hybrid_v1` | `S6TA_btc_top1` | 1.000 | 1.000 | 2,570 | 2,570 | 100% |
| `R1_eth_5m_s6_tight_pos_cloud` | `poly_updown_eth_5m_s6_hybrid_v1` | 0.886 | 0.981 | 4,830 | 5,454 | 100% |
| `R1_eth_5m_s6_tight_pos_cloud` | `S6TA_eth_top1` | 0.886 | 0.981 | 4,830 | 5,454 | 100% |
| `R1_btc_5m_s6_lite` | `R1_btc_5m_s6_top2` | 0.851 | 0.993 | 5,026 | 5,903 | 100% |
| `R2_btc_5m_s1_5_3bps` | `R1_btc_5m_s6_top2` | 0.695 | 0.995 | 4,666 | 6,715 | 100% |
| `R2_btc_5m_s1_5_3bps` | `R1_btc_5m_s6_lite` | 0.623 | 0.994 | 4,707 | 7,551 | 100% |
| `R1_btc_5m_s6_top2` | `poly_updown_btc_5m_s6_hybrid_v1` | 0.511 | 0.759 | 2,570 | 5,026 | 100% |
| `R1_btc_5m_s6_top2` | `S6TA_btc_top1` | 0.511 | 0.759 | 2,570 | 5,026 | 100% |
| `R1_btc_5m_s6_lite` | `poly_updown_btc_5m_s6_hybrid_v1` | 0.435 | 0.753 | 2,570 | 5,903 | 100% |
| `R1_btc_5m_s6_lite` | `S6TA_btc_top1` | 0.435 | 0.753 | 2,570 | 5,903 | 100% |
| `R2_btc_5m_s1_5_3bps` | `S6TA_btc_top1` | 0.360 | 0.758 | 2,364 | 6,561 | 99% |
| `R2_btc_5m_s1_5_3bps` | `poly_updown_btc_5m_s6_hybrid_v1` | 0.360 | 0.758 | 2,364 | 6,561 | 99% |
| `S7_btc_5m_base` | `poly_updown_btc_5m_s15_hybrid_v1` | 0.262 | 0.452 | 1,150 | 4,395 | 97% |
| `S7_btc_5m_base` | `poly_updown_btc_5m_s6_hybrid_v1` | 0.196 | 0.728 | 1,038 | 5,294 | 96% |


Key observations:
- `S6TA_btc_top1` == `poly_updown_btc_5m_s6_hybrid_v1` (Jaccard 1.000) — IDENTICAL gate stacks under two names from R1 vs R5
- `R1_btc_5m_s6_lite` ⊂ `R1_btc_5m_s6_top2` (Jaccard 0.85; top2 = lite + g_rf_with)
- `R2_btc_5m_s1_5_3bps` covers 70% of R1 lite/top2 fires
- `S7_btc_5m_base` only 20% overlap with S6 family — genuine diversifier (different offset range 120-300 vs 60-150)
- Hawkes (90-150 offsets) and microprice (any offset) are CROSS-family — <20% overlap

Heatmaps:
- `data/v4/canonical/_results/_overlap_audit_2026_05_26/heatmap_jaccard_fire.png`
- `data/v4/canonical/_results/_overlap_audit_2026_05_26/heatmap_jaccard_slug.png`

---

## 2. Three deploy modes comparison

| Mode | n_sleeves | n_fires | WR % | sum_pnl_32d | sum_pnl_28d ($25) | sum_pnl_28d ($250) |
|---|--:|--:|--:|--:|--:|--:|
| A_PRIMARY_GREEDY | 12 | 20,579 | 69.4 | $21,740 | $19,023 | $190,225 |
| B_NOTIONAL_SHARE_UNION | 17 | 21,984 | 69.3 | $22,129 | $19,363 | $193,628 |
| C_GATED_UNANIMITY | 17 | 12,979 | 70.6 | $17,110 | $14,971 | $149,713 |


### Mode definitions
- **A (Primary greedy)**: pick highest-PnL sleeve; add next sleeves only if fire-level
  Jaccard < 0.40 vs all already-selected. **12 sleeves selected.**
- **B (Notional-share / union)**: deploy ALL 17 positive sleeves; on overlapping fires
  the bet is single ($25), pnl is attributed pro-rata to each sleeve. This is the
  natural union — `sum = pnl over UNIQUE fires of all positive sleeves`.
- **C (Gated unanimity)**: only fire when ALL Tier-1 positive sleeves with a fire on
  this `(slug, fire_us)` agree on direction. Skips solo fires AND disagreement fires.

**Mode B (union of ALL positive sleeves) and Mode A (greedy primary) differ by only $340/28d** —
confirming the primary-greedy already captures ~99% of the union value. The R1 lite/top2,
S6TA, and ETH-S6-poly duplicates contribute essentially zero MARGINAL value over the
primary portfolio (they ARE the primary portfolio).

**Mode C (unanimity) is ~21% LOWER** than the primary union — the cost of skipping
non-overlapping (solo) fires exceeds the bonus of higher WR (70.6% vs 69.4%). Don't use C
unless you specifically want the higher WR for risk-management reasons.

---

## 3. True diversifiers (low overlap with primary portfolio)

After greedy de-duplication, the genuine diversifiers (overlap_pct < 30% with primary):

| Sleeve | Overlap % | n | WR % | Sum 28d |
|---|--:|--:|--:|--:|
| `R1_eth_5m_s6_tight_pos_cloud` (DEPLOY) | 20.5 | 4,830 | 70.9 | $4,433 |
| `S2_fade_momo_btc_mag2_0` (PAPER_FIRST) | 0.0 | 299 | 59.5 | $1,399 |
| `S2_fade_momo_eth_mag2_0` (PAPER_FIRST) | 0.0 | 202 | 61.4 | $1,059 |
| `poly_updown_sol_5m_s6_hybrid_v1` (DEPLOY) | 19.5 | 3,920 | 71.0 | $2,106 |
| `R4_POOL_15m_600_720_ribbon_slope_vwap` (DEPLOY) | 0.0 | 667 | 59.1 | $199 |
| `R4_ETH_15m_60_120_trstack_trendslope` (SKIP_NEGATIVE_PNL) | 0.0 | 164 | 64.0 | $-110 |
| `poly_updown_eth_5m_s15_hybrid_v1` (SKIP_NEGATIVE_PNL) | 20.9 | 2,509 | 77.6 | $-715 |
| `R4_POOL_15m_120_240_trendslope` (SKIP_NEGATIVE_PNL) | 0.0 | 768 | 54.4 | $-1,120 |
| `R4_POOL_15m_240_360_trendslope_vwap` (SKIP_NEGATIVE_PNL) | 0.0 | 913 | 51.5 | $-2,268 |


Notable diversifiers:
- **`R1_eth_5m_s6_tight_pos_cloud`** (20.5% overlap) — adds tight_ribbon/above_cloud filter
  ETH context that BTC sleeves don't cover. Highest marginal contributor: +$3,569/28d.
- **`poly_updown_sol_5m_s6_hybrid_v1`** (19.5% overlap) — SOL asset is entirely
  disjoint from BTC family. +$876/28d marginal.
- **`R4_POOL_15m_600_720_ribbon_slope_vwap`** (0% overlap) — different timeframe (15m).
  +$199/28d marginal but operationally distinct (lower fire rate).
- **`S2_fade_momo_btc/eth_mag2_0`** (0% overlap by construction) — contrarian strategy,
  fires on momentum exhaustion not continuation. +$1,399/$1,059 each at $25 notional /28d.
  N is small (BTC: 299, ETH: 202 over 22d → ~380/270 at 32d) — PAPER_FIRST recommended.

---

## 4. Final deploy manifest (top 16 sleeves)

| # | Sleeve | Status | Asset | TF | Offset | $/28d (full) | Marginal $/28d | Overlap % | Notional |
|--:|---|---|---|---|---|--:|--:|--:|--:|
| 1 | `R2_btc_5m_s1_5_3bps` | **DEPLOY** | BTC | 5m | 60-180 | $7,055 | $1,767 | 57% | 1.0 |
| 2 | `R5_microprice_univ_5m_rf_ribbon` | **DEPLOY** | BTC | 5m | 60-300 | $6,697 | $-718 | 56% | 1.0 |
| 3 | `S7_btc_5m_base` | **DEPLOY** | BTC | 5m | 120-300 | $5,674 | $1,886 | 65% | 1.0 |
| 4 | `R1_eth_5m_s6_tight_pos_cloud` | **DEPLOY** | ETH | 5m | 60-150 | $4,433 | $3,570 | 20% | 1.0 |
| 5 | `poly_updown_btc_5m_s6_hybrid_v1` | **DEPLOY** | BTC | 5m | 60-150 | $4,266 | $273 | 96% | 1.0 |
| 6 | `poly_updown_btc_5m_s15_hybrid_v1` | **DEPLOY** | BTC | 5m | 150-240 | $3,250 | $1,163 | 71% | 1.0 |
| 7 | `poly_updown_sol_5m_s6_hybrid_v1` | **DEPLOY** | SOL | 5m | 60-150 | $2,106 | $876 | 19% | 1.0 |
| 8 | `R5_btc_s15_v1_plus_mp_no_extreme` | **DEPLOY** | BTC | 5m | 150-240 | $2,029 | $0 | 100% | 1.0 |
| 9 | `R5_hawkes_btc_5m_off120` | **DEPLOY** | BTC | 5m | 90-150 | $1,001 | $85 | 83% | 1.0 |
| 10 | `R5_eth_s6_v1_plus_mp_change_with` | **DEPLOY** | ETH | 5m | 60-150 | $566 | $-102 | 90% | 1.0 |
| 11 | `R5_hawkes_sol_5m_off120` | **DEPLOY** | SOL | 5m | 90-150 | $231 | $-207 | 73% | 1.0 |
| 12 | `R4_POOL_15m_600_720_ribbon_slope_vwap` | **DEPLOY** | BTC | 15m | 600-720 | $199 | $199 | 0% | 1.0 |
| 13 | `S2_fade_momo_btc_mag2_0` | **PAPER_FIRST** | BTC | 5m | 60-300 | $1,399 | $1,399 | 0% | 0.5 |
| 14 | `S2_fade_momo_eth_mag2_0` | **PAPER_FIRST** | ETH | 5m | 60-300 | $1,059 | $1,059 | 0% | 0.5 |
| 15 | `R1_btc_5m_s6_lite` | **PAPER_FIRST** | BTC | 5m | 60-150 | $6,534 | $350 | 85% | 0.5 |
| 16 | `R1_btc_5m_s6_top2` | **PAPER_FIRST** | BTC | 5m | 60-150 | $6,239 | $149 | 97% | 0.5 |


Full manifest with gate stacks: `data/v4/canonical/_results/final_deploy_manifest.csv` (26 rows)

---

## 5. Realistic combined $/28d (FINAL NUMBER)

**Approach:** Mode A (greedy union of 12 non-overlapping DEPLOY sleeves)
   + S2 fade BTC/ETH at 0.5 notional (assumed disjoint, paper-first)
   + R1 paper-first marginal additions at 0.5 notional

| Component | $/28d @ $25 | $/28d @ $250 |
|---|--:|--:|
| Mode A union (12 DEPLOY sleeves) | $19,023 | $190,225 |
| S2 fade BTC/ETH (paper-first, 0.5x) | $1,229 | $12,292 |
| R1 lite/top2 paper-first (0.5x marginal) | $249 | $2,493 |
| **REALISTIC COMBINED TOTAL** | **$20,501** | **$205,010** |

**Annual run-rate at $250 notional: $2,672,455/year**
(vs prior estimate of $11-12M/year — **~75% lower**)

### Why the prior $85-95k estimate was wrong
The prior synthesis tables listed:
- S7_btc_5m_base: $10,739/wk × 4 = $43,000/28d  ← but this includes fires also counted in S6 family
- BTC S6 hybrid_v1 family: $5,500/wk × 4 = $22,000/28d × multiple variants  ← duplicated counts
- ETH S6 hybrid_v1: $3,000/wk × 4 = $12,000/28d  ← also duplicated in R1 ETH lite
- Microprice univ_5m_rf_ribbon: $35k/28d  ← partially overlapping with R5 ETH MP additions
- Hawkes family: $5k+ × 3 assets = $15k+  ← BTC overlap with S6, ETH negative
- 15m sleeves $20k  ← most were negative in OOS!

After enforcing UNION semantics + filtering negative-PnL sleeves from R4 15m,
the corrected number is $20,501/28d at $25.

---

## 6. Recommended deploy order (paper → live promotion)

### Phase 1 — Immediate live deployment (week 1)
The Tier-1 hybrid_v1 family that has the longest production paper trail:

1. **`R2_btc_5m_s1_5_3bps`** (BTC 5m, 60-180s, 3-gate stack) — highest $/28d
2. **`S7_btc_5m_base`** (BTC 5m, 120-300s) — Cyclops base; partially OOS-validated
3. **`R1_eth_5m_s6_tight_pos_cloud`** (ETH 5m, 60-150s) — best diversifier, +$3.6k marginal
4. **`poly_updown_btc_5m_s6_hybrid_v1`** (BTC 5m, 60-150s) — current production
5. **`poly_updown_btc_5m_s15_hybrid_v1`** (BTC 5m, 150-240s) — extension to longer offset
6. **`poly_updown_sol_5m_s6_hybrid_v1`** (SOL 5m, 60-150s) — asset-diversification

**Phase 1 expected: ~$15-16k/28d at $25, ~$150-160k/28d at $250.**

### Phase 2 — Add R5 microstructure overlays (week 2 after Phase 1 paper PASS)
7. **`R5_microprice_univ_5m_rf_ribbon`** (universal microprice, 60-300s) — new
8. **`R5_btc_s15_v1_plus_mp_no_extreme`** (BTC S15 + MP filter) — tighter, smaller n=298
9. **`R5_hawkes_btc_5m_off120`** (Hawkes 90-150s, BTC only) — new direction signal
10. **`R5_eth_s6_v1_plus_mp_change_with`** (ETH S6 + MP momentum overlay)

**Phase 2 marginal: ~$2-3k/28d additional (low marginal because of overlaps).**

### Phase 3 — Paper-first diversifiers (week 3)
11. **`S2_fade_momo_btc_mag2_0`** (BTC contrarian, |dev_bps|≥2.0) — disjoint strategy
12. **`S2_fade_momo_eth_mag2_0`** (ETH contrarian) — disjoint strategy
13. **`R4_POOL_15m_600_720_ribbon_slope_vwap`** (15m, longer offset) — only 15m survivor

### Phase 4 — DO NOT DEPLOY (negative in OOS)
SKIP entirely: `poly_updown_eth_5m_s15_hybrid_v1`, `R5_hawkes_eth_5m_off120`,
`R5_eth_s6_v1_plus_mp_no_extreme`, `R4_ETH_15m_60_120_trstack_trendslope`,
`R4_POOL_15m_120_240_trendslope`, `R4_POOL_15m_240_360_trendslope_vwap`,
`R5_btc_s6_v1_plus_lm_high_stat` (n=8, insufficient).

Reason: full-window OOS PnL is negative; these are R4/R5 OVERFITS that failed when the
4-day OOS window was added.

### Phase 5 — DO NOT DEPLOY (redundant)
SKIP_OVERLAP: `S6TA_btc_top1`, `S6TA_eth_top1`, `poly_updown_eth_5m_s6_hybrid_v1`.
Reason: 90-100% overlap with already-deployed sleeves.

---

## 7. Key methodology notes

1. **Fire-key = `(slug, fire_us, direction)`** — UP and DOWN on the same slug are
   separate "fires" because they represent different bets. This is correct for the
   union/dedup math.

2. **Overlap = Jaccard at fire-key level**, NOT at slug level. Two sleeves can share
   100% of slugs but fire at different offsets and have only 30% fire-Jaccard.

3. **Marginal_28d** = fires of this sleeve NOT covered by any OTHER deploy sleeve.
   This is the right measure of "what does adding this sleeve buy me?".

4. **The PRIMARY-GREEDY ≈ FULL-UNION** finding confirms the greedy heuristic is near-
   optimal: the ~$340/28d gap between greedy ($19,023) and full union ($19,363) means
   the 5 SKIPPED sleeves add basically nothing on top of the primary 12.

5. **Negative-PnL R4 15m sleeves were flagged as DEPLOY in R4 synthesis but FAILED
   full-window OOS** — this audit catches that. Net contribution: -$3.5k/28d if naively deployed.

6. **S2 fade is NOT in the per-fire panel** — it's in `fade_momo_5m.csv` aggregate only.
   Treated as paper-first with assumed-disjoint overlap (contrarian to momo).

---

## 8. Files inventory

- **Manifest:** `data/v4/canonical/_results/final_deploy_manifest.csv` (26 rows)
- Per-fire matrix: `data/v4/canonical/_results/_overlap_audit_2026_05_26/fired_by_sleeve.parquet` (63,796 rows)
- Sleeve summary: `_overlap_audit_2026_05_26/sleeve_summary.csv`
- Pairwise: `_overlap_audit_2026_05_26/pairwise_overlap_matrix.csv` (300 pairs)
- Jaccard fire matrix: `_overlap_audit_2026_05_26/pairwise_jaccard_fire.csv`
- Jaccard slug matrix: `_overlap_audit_2026_05_26/pairwise_jaccard_slug.csv`
- Heatmaps: `_overlap_audit_2026_05_26/heatmap_jaccard_{fire,slug}.png`
- Mode comparison: `_overlap_audit_2026_05_26/mode_compare.csv`
- Primary portfolio: `_overlap_audit_2026_05_26/primary_portfolio_greedy.csv`
- Incremental contribution: `_overlap_audit_2026_05_26/incremental_diversifier_pnl.csv`
- Scripts: `strategy_lab/overlap_audit_2026_05_26/01_..._06_*.py`

## End
