# Global Folder Cleanup Proposal

**Date:** 2026-05-07
**Total folder size:** ~14.5 GB (data 13 GB + strategy_lab 1.9 GB)
**Estimated reclaimable:** ~1.5 GB (10%) without losing any active path. **Up to ~2.0 GB** if operator OKs Tier 2 deletions.

This proposal is **non-destructive** — it lists candidates with rationale; no deletions are executed. Operator reviews then approves per tier.

---

## TIER 1 — Safe to delete immediately (~240 MB + tiny files)

These are unambiguously obsolete: explicit "_old_*" naming, old reports superseded by newer ones, log files older than the active session, top-level orphans not referenced by any current code.

### 1A. Explicitly named "old" data

| Path | Size | Rationale |
|---|---:|---|
| `strategy_lab/data/polymarket_old_2026_04_27/` | 233 MB | Name is self-documenting. Predates `polymarket/` by 2 days. No `.py` file references it. |
| `data/v4/refresh_2026_04_30/` | 1.3 MB | Tiny; superseded by `refresh_2026_05_02` (active) and `refresh_2026_05_06` (current). No code refs. |

### 1B. Old top-level artifact files (root of `global/`)

| Path | Size | Rationale |
|---|---:|---|
| `ALL_COINS_STRATEGY_REPORT.pdf` | 1.5 MB | Apr 20; pre-confluence; superseded by current confluence reports. |
| `V24_V25_OVERLAY_REPORT.pdf` | 675 KB | Apr 21; v24/v25 strategies are abandoned per `ANTI_EDGE_FINDINGS.md`. |
| `coworkfindings.strategies.pdf` | 430 KB | Apr 21; superseded. |
| `digest.json` + `digest.txt` | 108 KB | Apr 22; orphan files, no references. |
| `all_coins.txt` + `cf.txt` | 45 KB | Apr 22; orphan working files. |
| `analyze_strategies.py` | 4.5 KB | Apr 22; uses `digest.json`; orphan. |
| `audit_binance.py` | 2.7 KB | Apr 17; uses `data/binance/` for old strategies. |
| `fetch_binance.log` | 2 KB | Apr 17 log; pre-current data refresh. |
| `SESSION_WRAP_2026_04_30.md` | 6.6 KB | Old session wrap; superseded by `NEXT_SESSION_START_HERE.md`. |

### 1C. Stale build/log artifacts

| Path | Size | Rationale |
|---|---:|---|
| `strategy_lab/__pycache__/` | 2.5 MB | Auto-regenerated; safe to delete anytime. |
| `strategy_lab/results/sweep_*_20260417_*.csv` | small | Apr 17 logs; pre-current work. |
| `strategy_lab/results/per_asset_sweep_20260417_*.csv` | small | Same. |
| `strategy_lab/results/v[10-12]_hunt.{csv,log}` | small | Pre-v23 strategy hunts. |
| `strategy_lab/logs/` | 318 KB | Old session logs; verify timestamps before delete. |
| `logs/` (top-level) | 65 KB | Same. |

**Tier 1 total: ~240 MB.** Run after operator says "Tier 1 OK".

---

## TIER 2 — Delete after operator confirms (~1.3 GB)

These are **superseded by current pipelines** but were referenced by scripts that may need re-checking. Operator should confirm none of these are actively re-running.

### 2A. Old strategy results (pre-confluence, pre-meta_classifier)

The `strategy_lab/results/v23..v30/` dirs (~150 MB total) hold output from the V2B/V2D/V2F/V25/V27/V28/V29/V30 strategy variants. Per `ANTI_EDGE_FINDINGS.md`, these versions were superseded by the meta_classifier and confluence work. The associated `build_*_pdf.py` scripts at strategy_lab top level (~30 of them) are PDF builders for those reports.

| Path | Size |
|---|---:|
| `strategy_lab/results/v23/` | 12 MB |
| `strategy_lab/results/v24/` | 15 MB |
| `strategy_lab/results/v25/` | 24 MB |
| `strategy_lab/results/v26/` | 28 MB |
| `strategy_lab/results/v27/` | 24 MB |
| `strategy_lab/results/v28/` (charts/) | small |
| `strategy_lab/results/v29/` | 8.8 MB |
| `strategy_lab/results/v30/` | 21 MB |
| `strategy_lab/results/iaf/` | 22 MB |
| `strategy_lab/results/native_iaf/` | 32 MB |
| `strategy_lab/results/portfolio/` | 13 MB |

Plus their builders (Python at strategy_lab top-level):
- `build_v23_report.py`, `build_v24_v25_appendix.py`, `build_v28_charts.py`
- `v21_leverage_sweep.py`, `v30_overfitting_audit.py`
- `run_v38_smc_sweep.py`, `run_portfolio_*.py`
- `build_portfolio_pdf.py`, `build_leveraged_dashboard.py`, `build_low_dd_verdict.py`, etc.

### 2B. Kronos fine-tuning artifacts (rejected hypothesis)

Per `META_CLASSIFIER` testing (anti-edge findings), Kronos was rejected — derivatives Z-scores had no edge.

| Path | Size |
|---|---:|
| `strategy_lab/kronos_ft/` | 172 MB |

References (3 scripts that depend on it): `build_features_v3plus.py`, `fetch_btc_5m_extend.py`, `fetch_btc_apr_training.py` — also Tier 2 candidates if Kronos is fully retired.

### 2C. Derivatives Z-score features (also rejected)

| Path | Size |
|---|---:|
| `data/v4/derivatives_zscore/` | 208 MB |
| `strategy_lab/v4_signals/derivatives_zscore/` | small (code only) |

References: 5 scripts (`build_features_v3plus.py`, `meta_classifier/build_dataset.py`, `regime_classifier/feature_engineering.py`, `v4_signals/derivatives_zscore/backtest.py`, `backtest_v2.py`). All pre-confluence.

### 2D. Old polymarket data dump

| Path | Size | Notes |
|---|---:|---|
| `strategy_lab/data/polymarket_2026_04_29/` | 325 MB | Superseded by `strategy_lab/data/polymarket/` (current); no `.py` refs. |

### 2E. Old shadow-trades pulls (keep most recent)

| Path | Size | Rationale |
|---|---:|---|
| `data/v4/shadow_trades_2026_05_01/` | 480 KB | superseded |
| `data/v4/shadow_trades_2026_05_02/` | 1.6 MB | superseded |
| `data/v4/shadow_trades_2026_05_04/` | 1.3 MB | superseded |
| `data/v4/shadow_trades_2026_05_05/` | 20 KB | tiny, kept for diff if useful |
| `data/v4/shadow_trades_2026_05_05_live/` | 2.5 MB | check if referenced |
| `data/v4/shadow_trades_2026_05_06/` | 592 KB | **KEEP — current** |

Referenced by: `meta_classifier/anti_edge_analyzer.py`, `meta_classifier/v3_production_replay.py`, `meta_classifier/v3_shadow_vs_backtest.py`, `meta_classifier/v4_phase7_crossref.py`, `v4_signals/backtest_vs_shadow_audit.py` — these scripts probably read whichever shadow CSV is "current" via the path. Confirm with operator that we don't need to retain >1 historical shadow pull.

### 2F. Old phase-N v4_signals (pre-confluence)

| Path | Size | Status |
|---|---:|---|
| `strategy_lab/v4_signals/phase{1..7}_*.py` | small | All but phase7 produced rejected hypotheses; cite `STRATEGY_ARCHITECTURE_2026_05_06.md` for phase status. |
| `strategy_lab/v4_signals/derivatives_zscore/` | small | See 2C. |
| `strategy_lab/v2_signals/` | 413 KB | Pre-V3 work; entirely superseded. |

### 2G. Old top-level Python (orphan/superseded)

A grep shows these top-level scripts reference v23-v30 results dirs and/or build PDFs for retired strategy versions:

```
build_alpha_handbook.py
build_consolidated_pdf.py
build_coworkfindings_pdf.py
build_cross_ref_pdf.py
build_dashboard.py
build_deploy_guide.py
build_features_v3plus.py
build_leverage_verdict.py
build_leveraged_dashboard.py
build_low_dd_verdict.py
build_overfitting_pdf.py
build_pdf.py
build_pdf_per_asset.py
build_pdf_v3.py
build_pine_scripts.py
build_portfolio_dashboard.py
build_portfolio_pdf.py
build_strategy_catalog.py
build_v23_report.py
build_v24_v25_appendix.py
build_v28_charts.py
build_v52_test_fixtures.py
dashboard_user_sleeves.py
detailed_metrics.py
edge_hunt.py
native_to_iaf.py
portfolio_audit.py
run_dashboard.py
run_portfolio_hunt.py
run_portfolio_rank.py
run_portfolio_rank_long.py
run_v38_smc_sweep.py
v21_leverage_sweep.py
v30_overfitting_audit.py
```

**Total Tier 2: ~1.3 GB data + ~1 MB code.**

---

## TIER 3 — Investigate further before deciding

These need deeper analysis before deletion. Listed for tracking, not for action this round.

| Path | Size | What to check |
|---|---:|---|
| `strategy_lab/features/multi_tf/` | 102 MB | Are these multi-timeframe features used by current confluence work? Check `grep -r "features/multi_tf" strategy_lab/`. |
| `strategy_lab/features/` (other subdirs) | 166 MB | Same question per subdir. |
| `data/binance/` | 1.8 GB | Used by old `audit_binance.py`. If kronos+derivatives are also Tier 2'd, this is also Tier 2. Otherwise needed for current binance kline fetches. |
| `data/coinapi/` | 28 MB | Likely orphan — confirm. |
| `data/BTCUSDT/` | 32 MB | Old per-asset cache; check if any current script reads it. |
| `data/hyperliquid/` | 4.5 MB | Used by HL-related scripts. |
| `data/v4/tier1_entries/` | 30 MB | **KEEP** — used by `extended_backtest.load_tier1_entries`. |
| `data/v4/oi/`, `data/v4/sentiment/`, `data/v4/funding/`, `data/v4/calibration/` | 2.5 MB total | All small; check if any active path reads them. |
| `strategy_lab/v4_signals/derivatives_zscore/` | small | Subset of 2C. |

---

## KEEP — Do NOT delete

These are actively used by the current pipeline:

| Path | Why |
|---|---|
| `data/v4/refresh_2026_05_06/` (9.8 GB) | Current universe + cache; backbone of every recent backtest. |
| `data/v4/refresh_2026_05_02/` (417 MB) | Bucket-book source for `extended_backtest_with_robustness.load_book_buckets()`. Hard dependency. |
| `data/v4/tier1_entries/` (30 MB) | Loaded by `load_tier1_entries`. |
| `data/v4/shadow_trades_2026_05_06/` (592 KB) | Latest live shadow data. |
| `strategy_lab/confluence/` (763 KB) | Current confluence package — flow/structure/trigger/guard + classifier + tests. |
| `strategy_lab/meta_classifier/extended_backtest_with_robustness.py` | Core backtest engine. |
| `strategy_lab/meta_classifier/permutation_strict.py` | Validation gate engine. |
| `strategy_lab/momo_realfill/` (small) | Realfill engine for shadow vs backtest comparison. |
| `strategy_lab/reports/2026_05_06/` and `2026_05_07/` files | Current artifact reports. |
| `strategy_lab/data/polymarket/` (330 MB) | Current polymarket data; no `_old_` suffix. |
| `NEXT_SESSION_START_HERE.md` | Pointer doc, current. |
| `migration_2026_05_06/` | Migration scripts ready to fire (VPS2→VPS3). |

---

## Recommended cleanup order

**Phase 1 — Tier 1 (now, no operator review needed for these):**
```bash
cd "/c/Users/alexandre bandarra/Desktop/global"
# 1A — old data dirs
rm -rf strategy_lab/data/polymarket_old_2026_04_27
rm -rf data/v4/refresh_2026_04_30
# 1B — top-level orphans
rm -f ALL_COINS_STRATEGY_REPORT.pdf V24_V25_OVERLAY_REPORT.pdf coworkfindings.strategies.pdf
rm -f digest.json digest.txt all_coins.txt cf.txt
rm -f analyze_strategies.py audit_binance.py fetch_binance.log
rm -f SESSION_WRAP_2026_04_30.md
# 1C — caches (auto-regenerated)
find strategy_lab -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
rm -f strategy_lab/results/sweep_*_20260417_*.csv
rm -f strategy_lab/results/per_asset_sweep_20260417_*.csv
rm -f strategy_lab/results/v1[0-2]_hunt.csv strategy_lab/results/v1[0-2]_hunt.log
```

**Phase 2 — Tier 2 (operator review per group):**
- 2A old strategy results: `rm -rf strategy_lab/results/{v23,v24,v25,v26,v27,v28,v29,v30,iaf,native_iaf,portfolio}` (~150 MB)
- 2A builder scripts: archive to a `strategy_lab/_archive_v_strategies/` dir or delete (operator preference)
- 2B kronos: `rm -rf strategy_lab/kronos_ft` (~172 MB) + delete the 3 referencing scripts
- 2C derivatives: `rm -rf data/v4/derivatives_zscore strategy_lab/v4_signals/derivatives_zscore` (~208 MB)
- 2D old polymarket: `rm -rf strategy_lab/data/polymarket_2026_04_29` (~325 MB)
- 2E shadow trades: `rm -rf data/v4/shadow_trades_2026_05_0{1,2,4} data/v4/shadow_trades_2026_05_05{,_live}` (~5 MB)
- 2F phase scripts: `rm -rf strategy_lab/v4_signals/phase[1-7]_*.py strategy_lab/v2_signals` (small)
- 2G top-level scripts: move to a `strategy_lab/_archive/` dir for now (don't lose code, just remove from active path)

**Phase 3 — Tier 3 (defer until Phase 2 settles):**
- Investigate `strategy_lab/features/` content
- Investigate `data/binance/` (1.8 GB!) — if kronos+derivatives gone, this is too
- Smaller `data/v4/` subdirs (oi, sentiment, funding, calibration)

---

## Estimated savings

| Phase | Reclaimable | Risk |
|---|---:|---|
| Tier 1 (immediate) | ~240 MB | None — explicit orphans |
| Tier 2A (old strategy results) | ~150 MB | None if operator confirms v23-v30 retired |
| Tier 2B (kronos) | ~172 MB | None if Kronos formally retired |
| Tier 2C (derivatives) | ~208 MB | None if rejected per anti-edge |
| Tier 2D (old polymarket) | ~325 MB | None if `polymarket/` is current |
| Tier 2E (shadow trades) | ~5 MB | Low — can re-pull anytime |
| **Tier 1+2 total** | **~1.1 GB** | Low |
| Tier 3 (esp. `data/binance/`) | up to ~1.8 GB | Medium — needs validation |
| **Maximum total** | **~3 GB (~21% of folder)** | — |

---

## What to do next

Operator decision points:

1. **Approve Tier 1 immediate execution?** — these are unambiguous orphans.
2. **Per Tier 2 sub-group (A/B/C/D/E/F/G), approve or skip?**
3. **For Tier 2 code (builders + phase scripts), prefer `_archive/` move or `rm`?** — archive is reversible if anything was wrong; `rm` is final.
4. **Phase 3 inspection** — kick off as a separate task once Phase 2 settles.

I can execute Phase 1 immediately on confirmation. Phases 2 and 3 wait for per-group approvals.

---

## Files

- This proposal: `strategy_lab/reports/CLEANUP_PROPOSAL_2026_05_07.md`
- Reference for "what's actively used": `NEXT_SESSION_START_HERE.md`, `strategy_lab/reports/CONFLUENCE_VERDICT_2026_05_07.md`, `strategy_lab/reports/STRATEGY_ARCHITECTURE_2026_05_06.md`
