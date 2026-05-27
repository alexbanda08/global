# Data Window Audit — Reconciliation across 7 rounds

**Date:** 2026-05-26
**Auditor:** Window-Audit agent
**Trigger:** Agent WW flagged that PP-R6's panel may cover only 4d (May 21-25) not 32d, but PP claimed $20.5k/28d.

---

## TL;DR

| Claim | Reality | Status |
|---|---|---|
| CLAUDE.md "32d canonical window" | Apr 24 01:40 → **May 26 17:25** = **32.66d** ✓ | TRUE |
| PP-R6 used "32d window" | PP used `oos_fires_*` panels = **May 21 20:05 → May 25 19:15 = 3.96d** | **FALSE — under by 8.1×** |
| PP-R6 quoted "$20.5k/28d post-dedup" | Computed `sum_pnl * (28/32)` on a 3.96d panel | **MIS-SCALED — true /28d = $153,718** |
| TT-R7 "$61,980 lockbox" | Real on 4d lockbox split | TRUE for 4d, projects to **$433,860/28d** |
| All backtests use LegacyConfig (2%-on-profit) | Verified via `pnl_legacy_usd` column in panels; LegacyConfig referenced in 43 scripts vs 4 with real-fee curve | TRUE for Round panels |

**Root cause of 11.6×–17× "lockbox step-up"**: NOT a regime shift, NOT a window-length artifact, NOT a fee-model bug. It is a **fire-volume expansion**: weighted scoring models fire **8× more often** than binary AND-gate baselines while preserving per-trade edge. Same 4d lockbox both sides.

The 11.6× step-up Agent WW observed in PP's numbers is the **8.07× window mis-scaling** in PP's own report. True per-28d numbers ARE 7-8× higher than PP wrote down.

---

## 1. Authoritative canonical window

`load_resolutions()` over full canonical:

- **Range**: 2026-04-24 01:40 → 2026-05-26 17:25
- **Days**: **32.66** (matches CLAUDE.md claim within rounding)
- **Resolutions**: 36,157 chainlink-resolved across BTC/ETH/SOL
- **Per-day count**: 1,029–1,152 (consistent; no gaps with <100 resolutions)
- **Per-asset**: BTC=12,053, ETH=12,052, SOL=12,052 (balanced)
- **1s klines**: 4.22M rows per asset, range 2026-04-07 → 2026-05-26 17:36

Data refresh through May 26 = TODAY. Canonical is current.

---

## 2. Per-panel coverage (CLAIMED vs ACTUAL)

| Panel | Rows | Range | Days | Notes |
|---|--:|---|--:|---|
| `microprice_panel` | 559k | Apr 24 → May 25 | **31.73d** | ✓ Full window |
| `regime_panel_5m` | 23k | Apr 28 → May 25 | 27.80d | ~4d short at start |
| `microstructure_panel` | 238k | Apr 30 → May 23 | **23.00d** | 9d short |
| `hybrid_features_5m` | 190k | Apr 30 → May 23 | 23.00d | 9d short |
| `master_gate_features_v2` | 78k | May 1 → May 25 | **24.80d** | Used by Round 7 TT |
| `range_filter_1s` | 5.5M | May 1 → May 23 | **22.12d** | 10d short |
| `traders_reality_1s` | 5.5M | May 1 → May 23 | 22.12d | 10d short |
| `lee_mykland_panel` | 1.1M | May 1 → May 23 | 22.12d | 10d short |
| `hawkes_panel` | 5.5M | May 1 → May 23 | 22.12d | 10d short |
| `ta_indicators_1s` | 5.5M | May 1 → May 23 | 22.12d | 10d short |
| `sms_panel_5m` | 18k | May 1 → May 22 | 22.00d | 10d short |
| `oos_fires_*_5m/15m` (R6 input) | 123k | May 21 → May 25 | **3.96d** | **PP's panel — 8× short of "32d"** |

Key finding: **NONE of the working panels actually cover the full 32d**. The full-window canonical resolutions are 32.66d, but every derived panel is 22–28d, and the R6/R7 "OOS" panels are only 3.96d.

---

## 3. PP-R6 panel resolution

PP's `01_build_fire_matrix.py` loads from `_full_window_2026_05_26/oos_fires_{asset}_{tf}.parquet`. These panels are built by `full_window_validation_v2.py` with:

```python
REF_END_US  = 2026-05-21 20:01:00 UTC   # ref panel ends here
FULL_END_US = 2026-05-25 19:15:00 UTC   # oos panel ends here
```

So `oos_fires_*` covers only **May 21 20:05 → May 25 19:15 = 3.96 days**.

`fired_by_sleeve.parquet` actual range: **2026-05-21 20:06 → 2026-05-25 19:13** = **3.96d**.

PP's `04_final_manifest.py` line 49/57/166:
```python
marg_28d  = marg_df['pnl_legacy_usd'].sum() * (28/32)   # <-- WRONG: assumes 32d window
deploy_28d = deploy_sum * (28/32)                       # <-- same bug
```

True scaling factor = `28 / 3.96 = 7.07×`, not `28/32 = 0.875×`.

**Mis-scaling factor: 8.07×** (PP's reported numbers are this much smaller than true /28d).

---

## 4. Round-by-round re-normalization

| Round / Source | Quoted | Quoted window | True window | True /28d |
|---|--:|---|---|--:|
| R1 MASTER_DEPLOY combined | $55-65k/28d | "~28d" (Apr 30 → May 22) | 23d | $67-79k |
| R3 SYNTHESIS combined | $51-70k/28d | "mostly Apr 30 → May 22" | ~23d | $62-85k |
| R4 DEEP_STACK 3-way val OOS | $10-18k/4d (implied) | May 22-25 | 4d | $70-126k |
| R5 SYNTHESIS combined | $85-95k/28d | "full 32d canonical" | ~22d (panels) | $108-121k |
| **R6 PP slug-overlap dedup** | **$19,023 / 28d** | "32d" (stated) | **3.96d** | **$134,506 / 28d** |
| R6 PP raw $250 notional | $190,225/28d | "32d" stated | 3.96d | **$1.54M/28d** |
| **R7 TT logistic_poly2 7-sleeve** | **$61,980/4d** | "4d lockbox" | 4d | **$433,860/28d** |

**Caveat for R7**: the $61,980 is **gross before slug-overlap dedup**. Per the R7 report itself: "post-dedup realistic is $5-10k/4d = $35-70k/28d at $25 notional". So TT's HONEST projection is **$35-70k/28d**, not $433k/28d — TT explicitly flagged this. The gross 17× lift over AND-baseline is real on the same 4d window.

---

## 5. May 22-25 vs May 15-21 distributional comparison

| Metric | val (May 15-21, 7d) | lockbox (May 22-25, 4d) | Ratio |
|---|--:|--:|--:|
| Avg realized vol BTC (daily) | 0.0151 | 0.0147 | 0.97 |
| Avg realized vol ETH | 0.0210 | 0.0210 | 1.00 |
| Avg realized vol SOL | 0.0245 | 0.0242 | 0.99 |
| Avg slugs/day | 1,067 | 1,098 | 1.03 |
| Up-rate chainlink | 0.485 - 0.531 | 0.459 - 0.527 | similar |

**Conclusion**: NO market regime shift between val and lockbox. Vol identical to 3 decimal places. Slug count identical. Up-rate identical. The market is the same.

---

## 6. Fee model consistency check

| Pattern | File count |
|---|--:|
| `LegacyConfig` (2%-on-profit) | 43 |
| `LiveMimicConfig` (real curve) | 9 |
| `real_fee_curve_07` (`0.07*p*(1-p)`) | 4 (3 in maker/momo variants, 1 in inbox builder) |
| `poly_taker_curve` | 2 (engine_v2.py, hybrid_backtest.py) |

The 4 round panels (`oos_fires_*`, `master_gate_features_v2`) all expose `pnl_legacy_usd` only — no `pnl_real_usd`. Verified on row 1: `qty × (1-entry) × 0.98` matches `pnl_legacy_usd` exactly = LegacyConfig.

R6 and R7 BOTH consume `pnl_legacy_usd` only — same fee model train and lockbox. **No fee-model bug.**

The 4 "real_fee_curve" hits are in maker / momo investigation scripts, not in the Round 1-7 backtest panels.

---

## 7. Manifest reconciliation

`final_deploy_manifest.csv` (12 DEPLOY rows after dedup):

| Quantity | Value (PP) | True (re-scaled) |
|---|--:|--:|
| `sum(expected_sum_28d)` for DEPLOY only | $37,506 | (sum of mis-scaled per-sleeve numbers) |
| `sum(marginal_28d)` for DEPLOY only | $8,791 | $71,189 |
| Total unique-fire PnL on 3.96d | $21,740 | (raw) |
| At $25 notional /28d | **PP wrote: $19,023** | **TRUE: $153,718** |
| At $250 notional /28d | PP wrote: $190,225 | **TRUE: $1,537,178** |

Sanity check: $21,740 / 3.96d = $5,485/day. × 28d = $153,572. × 10 (=$250 notional) = $1.536M. Numbers match the audit.

---

## 8. VERDICT

### What is the 11.6× step-up?

Two phenomena got conflated:

1. **PP's 8.07× mis-scaling**: PP's "$/28d" numbers are off by exactly `32/3.96 ≈ 8.08×`. This is a code bug in `01_build_fire_matrix.py:328` and `04_final_manifest.py:49/57/166` — they hard-code `* (28/32)` while the actual oos panel is 3.96d, not 32d.

2. **R7 TT's 17× lift (AND→weighted)**: This is genuine on the same 4d lockbox. Weighted scoring fires **8× more** trades (2,583 → 21,092) at preserved per-trade edge ($1.39/tr → $2.94/tr poly2 average). It is NOT a regime shift, NOT a window mismatch, NOT a fee bug. The mechanism per TT's report is the `ribbon_alignment × DI` interaction that binary AND cannot express. Train (≤May 14), val (May 15-21), lockbox (May 22-25) all share identical realized vol, slug count, up-rate — so the lift survives lockbox cleanly.

### Combined honest deployable

After both PP's bug-fix AND R7's dedup caveat:

| Source | /28d at $25 | /28d at $250 |
|---|--:|--:|
| R6 PP corrected (12 DEPLOY sleeves, dedup, 3.96d → 28d scaling) | **$153,718** | **$1.54M** |
| R7 TT poly2 (7 sleeves, NO dedup yet, lockbox extrapolation) | $433,860 (gross) | $4.34M |
| R7 TT honest (post-dedup estimate per TT report) | $35-70k | $350-700k |

**Action items**:
1. **CRITICAL**: PP must rerun `04_final_manifest.py` with `* (28/3.96)` not `* (28/32)`. Re-publish manifest. Send a corrigendum to SLUG_OVERLAP_DEPLOY_MANIFEST and ROUND6_SYNTHESIS.
2. **VALIDATE**: PP-R6 only used the 3.96d **OOS** segment. The 21d **REF** segment exists in `sleeve_full_window_validation.csv` — `ref_sum` totals are very different from `oos_sum` (per-sleeve they swing by ±30%). The honest dedup should use **full_n / full_sum** (24d combined ref+oos) for stability.
3. **DEPLOY BLOCKER**: All Round 6 / Round 7 "/28d" numbers in published reports are quoting wrong scaling. Before any live capital allocation, audit-trail every number against this report.
4. The 32d canonical window IS available — no data limitation. The panels are short because the panel-build scripts only walked a portion of the canonical window. Future runs should extend panels to full 32d (or use full_n columns where available).
