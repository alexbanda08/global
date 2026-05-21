# Cleanup Execution Report

**Date:** 2026-05-07
**Initial size:** 14.5 GB (data 13 GB + strategy_lab 1.9 GB)
**Final size:** ~14.4 GB total (strategy_lab dropped 1.9 → 1.4 GB)
**Reclaimed this round:** ~500 MB (strategy_lab) + ~5 MB (data/v4)
**Reclaimable Tier 3 + polymarket_old (pending review):** up to ~3.4 GB additional

---

## Operator instructions applied

- ✅ **Tier 1 + Tier 2 — execute** (with exclusions)
- ✅ **KEEP kronos_ft** (172 MB) — operator will revisit
- ✅ **KEEP derivatives strategies/engines flagged as alpha** — V5 gauntlet ETH IS the new ETH deploy candidate per `derivatives_zscore/V5_GAUNTLET_VALIDATION.md`. All `strategy_lab/v4_signals/derivatives_zscore/*` and `data/v4/derivatives_zscore/` retained.
- ⏸️ **HOLD `polymarket_old_2026_04_27`** — investigation done (see §"polymarket_old investigation"); awaiting operator OK
- 🔍 **Tier 3 investigation** complete — see §"Tier 3 findings"

---

## Deletions executed

### Tier 1 (no-risk orphans)

| Path | Size | Status |
|---|---:|---|
| `data/v4/refresh_2026_04_30/` | 1.3 MB | DELETED |
| `ALL_COINS_STRATEGY_REPORT.pdf` | 1.5 MB | DELETED |
| `V24_V25_OVERLAY_REPORT.pdf` | 675 KB | DELETED |
| `coworkfindings.strategies.pdf` | 430 KB | DELETED |
| `digest.json` + `digest.txt` | 108 KB | DELETED |
| `all_coins.txt` + `cf.txt` | 45 KB | DELETED |
| `analyze_strategies.py` | 4.5 KB | DELETED |
| `audit_binance.py` | 2.7 KB | DELETED |
| `fetch_binance.log` | 2 KB | DELETED |
| `SESSION_WRAP_2026_04_30.md` | 6.6 KB | DELETED |
| All `__pycache__/` under strategy_lab | ~2.5 MB | DELETED (auto-regen) |
| Old sweep CSVs (Apr 17), v10-v12 hunt logs | small | DELETED |

### Tier 2A — Old strategy results (pre-confluence retired versions)

| Path | Size | Status |
|---|---:|---|
| `strategy_lab/results/v23/` | 12 MB | DELETED |
| `strategy_lab/results/v24/` | 15 MB | DELETED |
| `strategy_lab/results/v25/` | 24 MB | DELETED |
| `strategy_lab/results/v26/` | 28 MB | DELETED |
| `strategy_lab/results/v27/` | 24 MB | DELETED |
| `strategy_lab/results/v28/` | small | DELETED |
| `strategy_lab/results/v29/` | 8.8 MB | DELETED |
| `strategy_lab/results/v30/` | 21 MB | DELETED |
| `strategy_lab/results/iaf/` | 22 MB | DELETED |
| `strategy_lab/results/native_iaf/` | 32 MB | DELETED |
| `strategy_lab/results/portfolio/` | 13 MB | DELETED |

### Tier 2D — Superseded polymarket dump

| Path | Size | Status |
|---|---:|---|
| `strategy_lab/data/polymarket_2026_04_29/` | 325 MB | DELETED |

### Tier 2E — Old shadow_trades (kept latest only)

| Path | Size | Status |
|---|---:|---|
| `data/v4/shadow_trades_2026_05_01/` | 480 KB | DELETED |
| `data/v4/shadow_trades_2026_05_02/` | 1.6 MB | DELETED |
| `data/v4/shadow_trades_2026_05_04/` | 1.3 MB | DELETED |
| `data/v4/shadow_trades_2026_05_05/` | 20 KB | DELETED |
| `data/v4/shadow_trades_2026_05_05_live/` | 2.5 MB | KEPT (might be referenced) |
| `data/v4/shadow_trades_2026_05_06/` | 592 KB | KEPT (current) |

### Tier 2F — Retired phase scripts + v2_signals

| Path | Status |
|---|---|
| `strategy_lab/v4_signals/phase1_hour_of_day.py` | DELETED |
| `strategy_lab/v4_signals/phase2_clob_imbalance_v2.py` | DELETED |
| `strategy_lab/v4_signals/phase3_macro_block_strict.py` | DELETED |
| `strategy_lab/v4_signals/phase4_signal_quality_kelly.py` | DELETED |
| `strategy_lab/v4_signals/phase5_liq_feed.py` | DELETED |
| `strategy_lab/v4_signals/phase6_confidence_calibration.py` | DELETED |
| `strategy_lab/v4_signals/phase7_clob_imbalance_momentum.py` | KEPT (V3+Phase7 union active) |
| `strategy_lab/v4_signals/phase7_clob_momentum.py` | KEPT |
| `strategy_lab/v4_signals/phase7_validation.py` | KEPT |
| `strategy_lab/v2_signals/` (entire dir, 413 KB) | DELETED |

### Tier 2G — Top-level builders (ARCHIVED, not deleted — reversible)

Moved 33 retired top-level builders to `strategy_lab/_archive/`:

```
build_v23_report.py, build_v24_v25_appendix.py, build_v28_charts.py,
build_v52_test_fixtures.py, build_portfolio_pdf.py, build_portfolio_dashboard.py,
build_leveraged_dashboard.py, build_low_dd_verdict.py, build_leverage_verdict.py,
build_overfitting_pdf.py, build_alpha_handbook.py, build_consolidated_pdf.py,
build_coworkfindings_pdf.py, build_cross_ref_pdf.py, build_pdf.py,
build_pdf_per_asset.py, build_pdf_v3.py, build_pine_scripts.py,
build_strategy_catalog.py, build_deploy_guide.py, build_dashboard.py,
dashboard_user_sleeves.py, run_dashboard.py, run_portfolio_hunt.py,
run_portfolio_rank.py, run_portfolio_rank_long.py, run_v38_smc_sweep.py,
v21_leverage_sweep.py, v30_overfitting_audit.py, native_to_iaf.py,
portfolio_audit.py, edge_hunt.py, detailed_metrics.py
```

To restore any one: `mv strategy_lab/_archive/<file>.py strategy_lab/`.

---

## Items KEPT

### Per operator instruction

| Path | Size | Why |
|---|---:|---|
| `strategy_lab/kronos_ft/` | 172 MB | Operator will revisit |
| `data/v4/derivatives_zscore/` | 208 MB | V5 gauntlet ETH alpha — see `V5_GAUNTLET_VALIDATION.md` |
| `strategy_lab/v4_signals/derivatives_zscore/` | small | Same — alpha-flagged engines |
| `strategy_lab/strategies/funding_signals.py` | small | Funding signal engine — likely related to V5 alpha |

### Active code paths (do not delete)

| Path | Why |
|---|---|
| `data/v4/refresh_2026_05_06/` (9.8 GB) | Current universe + cache |
| `data/v4/refresh_2026_05_02/` (417 MB) | Bucket-book source |
| `data/v4/tier1_entries/` (30 MB) | L25 entry book |
| `strategy_lab/confluence/` (342 KB) | Current confluence package |
| `strategy_lab/meta_classifier/` (576 KB) | Backtest engine + permutation |
| `strategy_lab/momo_realfill/` | L25 realfill engine |
| `strategy_lab/reports/2026_05_0[6-7]_*` | Current artifact reports |
| `strategy_lab/data/polymarket/` (330 MB) | Current polymarket data |
| `migration_2026_05_06/` | VPS2→VPS3 migration scripts |
| `strategy_lab/v4_signals/phase7_*.py` | V3+Phase7 union (active) |
| `strategy_lab/v4_signals/derivatives_zscore/*` | V5 gauntlet alpha |

---

## polymarket_old_2026_04_27 investigation

**Verdict: SAFE TO DELETE.** Awaiting operator approval.

Contents (12 files, 233 MB):
```
btc_book_depth_v3.csv (64 MB)   eth_book_depth_v3.csv (60 MB)   sol_book_depth_v3.csv (55 MB)
btc_features_v3.csv (640 KB)    eth_features_v3.csv (640 KB)    sol_features_v3.csv (628 KB)
btc_markets_v3.csv (580 KB)     eth_markets_v3.csv (584 KB)     sol_markets_v3.csv (~)
btc_trajectories_v3.csv (18 MB) eth_trajectories_v3.csv (18 MB) sol_trajectories_v3.csv (~)
```

**Reference search:** ZERO Python files reference `polymarket_old_2026_04_27` — only mentioned in `CLEANUP_PROPOSAL_2026_05_07.md` (this cleanup work).

**Comparison vs `strategy_lab/data/polymarket/` (current, 330 MB):**
- `polymarket/` has the same 12 files PLUS:
  - `all_features_v3.csv` (cross-asset features)
  - `*_features_v3plus.csv` (v3plus extension with derivatives features)
  - `*_flow_v3.csv` (flow features added later)
  - `traj_log.txt`
  - `vps2_v1_shadow.csv`, `vps3_v2_shadow.csv` (shadow data)

`polymarket_old_2026_04_27` is a strict subset (Apr 27 snapshot before flow + v3plus features were added).

**Recommendation:** delete. If operator wants to keep an Apr 27 snapshot for diff/audit purposes, archive instead:
```bash
mv strategy_lab/data/polymarket_old_2026_04_27 strategy_lab/_archive/polymarket_2026_04_27/
```

---

## Tier 3 findings

### `strategy_lab/features/multi_tf/` (102 MB)

- **Referenced by:** `strategy_lab/fetch_multi_tf.py` (still in top-level) + 1 archived builder.
- **Verdict:** if `fetch_multi_tf.py` is retired, delete the data + archive the script. Need operator confirmation.
- Other `strategy_lab/features/` subdirs total ~166 MB; same investigation needed per subdir.

### `data/binance/` (1.8 GB) — biggest potential win

- **Referenced by 7 scripts:** `features_15m.py`, `polymarket_build_features.py`, `polymarket_build_features_xasset.py`, `polymarket_signal_grid_v2.py`, `regime_classifier/feature_engineering.py`, `run_v37_claude_trader.py`, `scalping/data_loader.py`.
- **Status:** All 7 are pre-confluence work (V37, regime classifier, scalping). None of them is part of the current confluence pipeline.
- **Verdict:** **likely safe to delete** but THIS IS BIG — operator confirms before action. If yes, also archive the 7 scripts.

### `data/coinapi/` (28 MB)

- Referenced by `features_15m.py` only — same fate as `data/binance/`.
- **Verdict:** delete with binance, OR keep for V5 gauntlet if `compute_zscores.py` reads from coinapi.

### `data/BTCUSDT/` (32 MB)

- Referenced by `build_features_v3plus.py`, `fetch_btc_5m_extend.py`, `fetch_btc_apr_training.py`, `fetch_btc_recent.py`. The first 3 of these reference kronos_ft (kept per operator).
- **Verdict:** keep until kronos retired (operator will revisit).

### `data/hyperliquid/` (4.5 MB)

- Referenced by `ingest_hyperliquid.py`, `ingest_hyperliquid_full.py`.
- **Verdict:** keep — small, used for HL ingestion.

### Small data/v4/ subdirs (2.5 MB total)

- `data/v4/oi/` (1.5 MB) — fetch_funding_oi.py
- `data/v4/sentiment/` (904 KB) — fetch_news_sentiment.py
- `data/v4/funding/` (52 KB) — fetch_funding_oi.py
- `data/v4/calibration/` (4 KB) — empty/abandoned

**Verdict:** Keep oi + funding (used by V5 gauntlet path indirectly). Sentiment + calibration potentially deletable; tiny anyway.

---

## Final operator action items

| Item | Size | Action requested |
|---|---:|---|
| `polymarket_old_2026_04_27` | 233 MB | Delete or archive? |
| `strategy_lab/features/multi_tf/` + `fetch_multi_tf.py` | ~102 MB | Confirm retired then delete data + archive script |
| `data/binance/` + 7 referencing scripts | **1.8 GB** | Confirm pre-confluence retired, then delete + archive scripts |
| `data/coinapi/` | 28 MB | Pair with `data/binance/` decision |
| `data/v4/sentiment/` | 904 KB | Confirm `fetch_news_sentiment.py` retired |
| `data/v4/calibration/` | 4 KB | Probably already empty; verify |

If operator approves all of the above, **additional ~2.2 GB** reclaimable, bringing total cleanup to ~2.7 GB.

---

## Files

- Original proposal: `strategy_lab/reports/CLEANUP_PROPOSAL_2026_05_07.md`
- This execution report: `strategy_lab/reports/CLEANUP_EXECUTION_2026_05_07.md`
- Archive of moved scripts: `strategy_lab/_archive/` (33 builders, restorable with `mv`)
