# Complete session handoff — 2026-05-26

**Self-contained brief for the next session.** Read this first. Everything you
need to continue is referenced here.

---

## 0. TL;DR — where we are

**7 rounds + 35+ parallel agents** ran across this session. Final outputs:

- **Final deploy roster** (post-audit): 7 DEPLOY sleeves at $25 paper-mode
- **Audited deployable**: $66.6k/28d at $25 = $1.60M/year run-rate at $250 notional (BTC-only post-dedup)
- **3 bug fixes** applied to backtest pipeline (fire-count, regime panel, SMS panel, PP scaling)
- **All 5m BTC markets covered** by deploy roster. **5m ETH/SOL deployable only at $25**. **15m markets: NO clean deployable sleeve survived audit.**

### Next session mission — **SNIPER STRATEGY OPTIMIZATION** ⭐ PRIMARY

The current deploy roster has too many "shotgun" sleeves: high-volume, high-DD.
S7_btc_5m_base fires **4,894 times in 32 days** (≈150/day) at only $1.10/tr;
R1_btc_5m_s6_lite fires 2,986 times with **36-trade losing streaks** and $1,816 max DD.
These are operationally heavy and emotionally hard to deploy.

**The new mission: find SNIPER strategies that trade LESS but with higher conviction.**

Target profile per new sleeve:
- **n: 100-500 fires/32d** (3-15 per day, not 100+/day)
- **WR: ≥ 75%**
- **$/tr: ≥ $3-5** at $25 stake
- **Max DD: ≤ $300** at $25 stake
- **Max loss streak: ≤ 6** (sustainable psychologically)
- **Sharpe (daily approx): ≥ 2.0**

This profile matches the existing **momo / sniper family** (`poly_updown_*_sniper_hod`,
`poly_updown_*_momo_v2_hod`) which was the PRODUCTION DESIGN PHILOSOPHY pre-this-session.
The Phase 34 sleeves were explicitly sniper-oriented. We accidentally moved toward
high-volume "shotgun" sleeves while chasing dollar lift; need to course-correct.

### Where to look for sniper signals (specific approaches)

1. **Pre-window entries** (fire BEFORE the slot starts):
   - momo controller already does ws_s anchor predictions (negative time-to-slot)
   - F7 RSI at ws_s is the production sniper feature
   - Markov M1V regime at ws_s is the production sniper filter
   - Cross-asset RF state at ws_s-30s (just before slot)

2. **Beginning of window** (offset 0-60s, NOT 60-150s):
   - Early aggressive fires when book is freshest
   - R6 Agent LL found BTC S6 0-60s + 12 gates → WR 79.9%, $/tr +$8.03 (1 of the highest)
   - This was UNDER-tested — only 1 cell, n=219 — strong sniper candidate
   - Sub-60s offsets had a strong polynomial-interaction signal in R7 TT

3. **Sniper-style gate stacks**:
   - F7 RSI extreme + Markov M1V_va = 2 + ribbon agrees → high conviction
   - HoD constant + asset-specific cell + ribbon + dev → narrow filter
   - Cross-asset RF unanimity + microprice no-extreme + extreme dev_bps

4. **High-bar gates** (deliberate selectivity):
   - Require BOTH `g_dev_extreme` AND `g_within_dev` (very large deviations)
   - Require `tr_stack_full_with` (full EMA stack alignment, score = ±2)
   - Stack ALL R1 gates + 1-2 R5 gates to drive n down to ~200-500

5. **Apply existing R6 master combinatorial with SUM-PNL CAP**:
   - Re-run Agent LL's master_combinatorial with a constraint: max_n ≤ 500
   - This will find the best "sniper" gate stacks the prior search ignored

### Secondary missions (after sniper search)

**Find at least one good strategy per market with the sniper profile:**
1. **BTC 5m** (already have shotgun-style; want sniper variant)
2. **ETH 5m** (only deploys at $25; need higher-$/tr to absorb slippage)
3. **SOL 5m** (same problem — slippage at $250)
4. **BTC 15m** (R4 POOL 600-720 went negative after audit fixes)
5. **ETH 15m** (everything failed audit)
6. **SOL 15m** (R4 trend_slope family failed audit)
7. **POOL 15m** (failed)

The 15m crisis still exists — Round 4 found 178 "deployable" 15m sleeves
but every single one failed when fire-count + regime bugs were fixed. The
`g_trend_slope_with` regime feature was the killer gate for all of them, and
its derivation had the lookahead bug (now fixed). The bug-fixed
`regime_panel_*_v2_fixed.parquet` is ready — re-derive `g_trend_slope_with`
from it and re-search.

### Why this is the right next move

The current deploy roster has 36-trade losing streaks (R1_btc_5m_s6_lite,
BTC S6 hybrid_v1). At $25 stake, that's $900 underwater in a row with no
wins to recover. At $250, that's $9,000 of capital drawdown. Operationally,
that's intolerable — operator confidence and capital risk both spike.

Sniper sleeves with 6-loss streaks ($150 at $25 stake) are FAR more
deployable. The BTC S15 hybrid_v1 sleeve we have ($269 max DD, 6 loss streak,
86% WR) is already this profile — we need MORE sleeves like it, not more
shotguns.

### ⚠️ CORRECTED DD numbers (the original PDF had a bug)

The `PER_SLEEVE_DETAILED_2026_05_26.pdf` showed inflated max-DD numbers
($12,793 for R1_btc_5m_s6_lite etc.) because the DD calc used UNGATED fires
in the offset window, not the sleeve's actual gated fires. The REAL max-DDs
at $25 notional are 4-7× smaller. See "Corrected per-sleeve metrics" table
in §1.5 below — these are the load-bearing numbers for any deploy decision.

---

## 1. Final deploy roster (post-audit, 2026-05-26)

| # | Sleeve | Market | n | WR | $/tr | $25/28d | $250/28d | Status |
|---|---|---|--:|--:|--:|--:|--:|---|
| 1 | R1_btc_5m_s6_lite | BTC 5m 60-150 | 3,373 | 68.4% | $1.04 | $24,771 | $68,907 | DEPLOY |
| 2 | S7_btc_5m_base | BTC 5m 120-300 | 1,940 | 76.9% | $1.78 | $24,476 | $115,117 | DEPLOY |
| 3 | R1_eth_5m_s6_tight_pos_cloud | ETH 5m 60-150 | 2,755 | 70.1% | $0.77 | $15,044 | NEG (slip) | DEPLOY @ $25 only |
| 4 | poly_updown_btc_5m_s15_hybrid_v1 | BTC 5m 150-240 | 1,013 | 73.0% | $1.89 | $13,521 | $54,716 | DEPLOY |
| 5 | poly_updown_sol_5m_s6_hybrid_v1 | SOL 5m 60-150 | 2,261 | 70.1% | $0.30 | $4,846 | NEG (slip) | DEPLOY @ $25 only |
| 6 | R5_hawkes_btc_5m_off120 | BTC 5m 90-150 | 339 | 76.7% | $2.02 | $4,841 | $24,253 | DEPLOY |
| 7 | R5_eth_s6_v1_plus_mp_change_with | ETH 5m 60-150 | 416 | 73.8% | $1.60 | $4,713 | NEG (slip) | DEPLOY @ $25 only |

**Plus zero-code quick wins** (operator config changes, no engineering):
- S3 HoD refresh: +$15.9k/28d on existing 11 production sleeves (5-min edit)
- S2 Fade Momo BTC patch: +$1.2k/28d (4-line momo.py edit)
- B.7.1 sleeve #2 fix: +$0.75k/28d (1-line config)

**Combined Phase 1 deploy at $25**: ~$66k/28d ≈ $866k/year
**Combined Phase 2 at $250 (BTC-only)**: ~$122k/28d ≈ $1.60M/year

### 1.5 CORRECTED per-sleeve metrics with PROPER gate filtering

**At $25 notional per fire**. The DD/streak numbers in the prior PDF were
inflated by a bug (ungated fires used in the DD calc). These are the REAL
metrics after applying each sleeve's gate stack and computing on the
PROPER fire subset. Saved to `data/v4/canonical/_results/sleeve_true_dd_metrics.json`.

| Sleeve | n | WR | $/tr | Sum (22d) | **Max DD** | DD/profit | Win streak | **Loss streak** | Sharpe |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| R1_btc_5m_s6_lite | 2,986 | 76.8% | $4.50 | $13,436 | **$1,816** | 13.5% | 101 | **36 ⚠️** | 2.03 |
| S7_btc_5m_base | 4,894 | 84.5% | $1.10 | $5,398 | **$802** | 14.9% | 47 | **6 ⭐** | 0.69 |
| R1_eth_5m_s6_tight_pos_cloud | 1,252 | 66.9% | $4.90 | $6,129 | **$1,781** | 29.1% ⚠️ | 52 | 34 ⚠️ | 2.47 |
| **BTC S15 hybrid_v1** ⭐ | 1,753 | 86.3% | $3.12 | $5,477 | **$269 ⭐** | 4.9% ⭐ | 50 | **6 ⭐** | 1.26 |
| SOL S6 hybrid_v1 | 1,803 | 88.3% | $1.87 | $3,376 | **$487** | 14.4% | 153 | 14 | 2.10 |
| BTC S6 hybrid_v1 | 2,764 | 77.8% | $5.10 | $14,103 | **$1,837** | 13.0% | 101 | 36 ⚠️ | 2.25 |

**At $250 notional** (10× scale): DD scales 10×, so BTC S15 max DD ≈ $2,690
on $54.7k profit (20× coverage — excellent). R1_btc_s6_lite max DD ≈ $18,160
on $68.9k profit (3.8× coverage — tight).

**Reference for "sniper" target profile** (what we want more of):
- BTC S15 hybrid_v1 = **$269 DD, 6 loss streak, 86% WR, $3.12/tr**
- 11 trades worst case to recover (vs 36 for shotguns)
- This is what every new sleeve should look like

### SKIP / DO-NOT-DEPLOY
- **SKIP_OVERLAP (8)**: R1_btc_5m_s6_top2, R2_btc_5m_s1_5_3bps, R5_microprice_univ_5m_rf_ribbon, S6TA_btc_top1, S6TA_eth_top1, poly_updown_btc_5m_s6_hybrid_v1, poly_updown_eth_5m_s6_hybrid_v1, R5_hawkes_sol_5m_off120, R5_btc_s15_v1_plus_mp_no_extreme — fire on same slugs as higher-priority deploy sleeves
- **SKIP_NEGATIVE_PNL (5)**: poly_updown_eth_5m_s15_hybrid_v1, R4_POOL_15m_600_720_ribbon_slope_vwap, R5_hawkes_eth_5m_off120, R5_eth_s6_v1_plus_mp_no_extreme, R5_btc_s6_v1_plus_lm_high_stat — negative PnL after audit

### THE 15M HOLE
After fire-count + regime panel fixes, **NO 15m sleeve survives**. The 178
R4 trend_slope family all relied on the leaky regime panel. POOL 15m 600-720
went from +$1,611/28d → -$1,272/28d after fix. Every BTC/ETH/SOL 15m candidate
collapsed. **This is the highest-priority next-session topic.**

---

## 2. Bug fixes applied (audit reports for full detail)

### Bug #1 (HIGH severity): Fire-count inflation
**Source**: `data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_*.parquet` (originals)
**Problem**: OOS fire files had 17 offsets per slot (every 15s) but base panels used 9 offsets (every 30s). Lockbox PnL inflated 4-6× by construction.
**Fix**: Rebuilt with canonical 9-offset grid. New files saved as `*_v2_fixed.parquet`.

### Bug #2 (MEDIUM): Regime panel leak
**Source**: `strategy_lab/meta_classifier/build_regime_panel.py:270-282`
**Problem**: `ts_us = bar START` but close/ADX/regime_label use FULL closed bar. merge_asof backward picks current slot whose features include 0-300s of FUTURE data. 19.5% of BTC 5m fires got a different regime_label than the causal prior bar.
**Fix**: Shifted `ts_us` to bar END (`bar_start + tf_seconds`). New panel saved as `regime_panel_*_v2_fixed.parquet`.

### Bug #3 (MEDIUM): SMS panel — same leak pattern
**Source**: SMS panel build script (Traders Reality liquidity/CHoCH/BOS computation)
**Fix**: Same as Bug #2. Saved as `sms_panel_*_v2_fixed.parquet`.

### Bug #4 (HIGH, DEFLATING): PP-R6 scaling bug
**Source**: `strategy_lab/overlap_audit_2026_05_26/04_final_manifest.py`
**Problem**: PP hardcoded `sum_pnl * (28/32)` but actual lockbox panel covered only 3.96 days. Correct scaling was `* (28/3.96)`. Manifest was 8.07× UNDER-stated.
**Fix**: Corrected scaling factor in `04_final_manifest.py`.

### Audit reports
- `strategy_lab/reports/ENGINE_AUDIT_2026_05_26.md` — Agent BB (engine + causal anchoring)
- `strategy_lab/reports/DATA_WINDOW_AUDIT_2026_05_26.md` — Agent CC (window normalization)
- `strategy_lab/reports/POST_AUDIT_FINAL_CATALOG_2026_05_26.md` — Agent EE (remediation + re-run)

### What's clean (no bugs in)
- `engine_v2.py` fee model + L25 book walk: ✓ causal
- Microprice, microstructure, VPIN/Hawkes, Lee-Mykland, ta_indicators, hybrid_features: ✓ causal
- Outcome labels: ✓ chainlink (verified 50/50 match)
- Bootstrap time-ordering: ✓

---

## 3. Available data + canonical panels (paths)

### Authoritative data window
**Apr 24 01:40 → May 26 17:25 UTC = 32.66 days, 36,157 chainlink-resolved markets.**

### Canonical loaders (`data/v4/canonical/load.py`)
```python
load_resolutions(assets=[...])       # chainlink-only, per-day window
load_klines_1s(asset)                # 1s binance OHLCV
load_klines(asset, source=...)       # 5m+ klines from binance/coinbase/kraken/okx
load_chainlink_rtds(asset)           # oracle ticks
load_orderbook_l25_streaming(asset, slugs)  # L25 books per slug
load_tier1_entries(asset)
load_trades(asset)                   # PM trades (stale May 6)
load_hyperliquid_klines(asset)
load_hyperliquid_liquidations(asset)
load_hyperliquid_funding(asset)
load_hyperliquid_metrics(asset)
slug_to_ws_s(slug, tf), add_ws_s(df), ret_2m_at_ws(...)
asof_strict(end_us, prices, target_us)
```

### Feature panels (in `data/v4/canonical/_results/`)

| Panel | What | Coverage | Notes |
|---|---|---|---|
| `ta_indicators_1s.parquet` | ribbon, stoch, BB, MFI, CCI on 1s binance | 22.12d | clean |
| `range_filter_1s.parquet` | RF [DW] on 1s closes per asset | 22.12d | clean |
| `traders_reality_1s.parquet` | EMA 5/13/50/200/800 + PVSRA + pivots + ADR + sessions | 22.12d | clean |
| `microprice_panel.parquet` | Stoikov microprice on L25 (skew, change_500ms, weighted) | 31.73d ⭐ longest | clean |
| `microstructure_panel.parquet` | book imb, slope, depth, queue, spread skew (55 features) | 24.8d | clean |
| `sms_panel_5m.parquet` / `_15m.parquet` | CHoCH, BOS, liquidity, RSI div, trend strength | 22.12d | 🚨 leak → use `_v2_fixed` |
| `regime_panel_5m.parquet` / `_15m.parquet` | trending_up/dn/ranging + ADX | 22.12d | 🚨 leak → use `_v2_fixed` |
| `vol_hurst_at_fire_5m.parquet` | rv_60/300/900, Garman-Klass, Hurst, trend_slope_30m | 22.12d | clean |
| `lee_mykland_panel.parquet` | L_stat, jump flags, bipower variation | 22.12d | clean |
| `hawkes_panel.parquet` | self-exciting flow λ_imbalance, λ_total | 22.12d | clean |
| `vpin_panel.parquet` | volume-synchronized toxic flow | 22.12d | clean (failed as signal but data is fine) |
| `as_panel.parquet` | Avellaneda-Stoikov uncertainty | 22.12d | clean (failed as gate) |
| `master_gate_features_v2.parquet` | All 37 gates × 77k fires (R6 build) | 24.8d | reference for cross-stacking |

### Per-fire augmented parquets (for backtest scoring)
| File | Fires | What |
|---|--:|---|
| `s15_with_ta_and_markov.parquet` | 33,323 | S1.5 5m fires + TA + Markov |
| `v15m_with_ta_and_markov.parquet` | 12,492 | S7 15m fires + TA + Markov |
| `s6_with_ta.parquet` | 11,336 | S6 spike 5m fires + TA |
| `s15_joined_all.parquet` | — | S1.5 + all R3/R5 features |
| `s6_joined_all.parquet` | — | S6 + all R3/R5 |
| `v15m_joined_all.parquet` | — | S7 + all R3/R5 |
| `hybrid_features_5m.parquet` | 190k × 158 | full feature matrix 5m |
| `hybrid_features_15m.parquet` | 50k × 158 | full feature matrix 15m |
| `hybrid_fire_universe_5m.parquet` / `_15m.parquet` | 190k / 50k | base fire universe with L25 fills |
| `_full_window_2026_05_26/oos_fires_*_v2_fixed.parquet` | — | OOS bug-fixed (9-offset grid) |
| `microprice_panel.parquet` ← BUG-FREE for 5m fires | — | use directly via merge_asof |

### Audit output files
- `master_sleeve_catalog_audited.csv` — 448 sleeves × 25 cols (all 7 rounds, with grades A/B/C/F)
- `master_sleeve_catalog_v2_clean.csv` — 20 top sleeves with CLEAN post-audit metrics
- `per_market_best_sleeve_clean.csv` — 8 markets with best CLEAN sleeve each
- `sleeve_notional_scaling_truth.csv` — slippage at $25/$250/$2500 for 21 sleeves
- `final_deploy_manifest_v2_post_audit_FULL.csv` — 21-row deploy manifest
- `_overlap_audit_2026_05_26/` — pairwise overlap matrices

---

## 4. Available engines + scripts

### Backtest engine (use this)
- `strategy_lab/engine_v2.py` — `LegacyConfig` (2%-on-profit-only) + `LiveMimicConfig`
  - `fill_at_book(books_idx, slug, "UP"/"DOWN", fire_us, cfg, spread_filter)` → L25 walk fill (entry_vwap, entry_qty)
  - `hold_pnl(fill, won=True/False, cfg)` → realized pnl
  - `book_event_count(books_idx, slug, outcome, ...)` — sparse-book filter

### Round 6/7 cross-stacking scripts (reuse for new search)
- `strategy_lab/meta_classifier/hybrid_backtest.py` — `gate_search()`, `walk_forward_split()`, `run_hybrid_backtest()`
- `strategy_lab/master_combinatorial_2026_05_26/` — exhaustive 2^k gate search
- `strategy_lab/overlap_audit_2026_05_26/01-06_*.py` — slug-overlap dedup methodology (Agent PP)
- `strategy_lab/threshold_sweep_2026_05_26/` — threshold parameter sweeps

### Round 5 advanced quants (the working ones)
- `strategy_lab/microprice/build_microprice_panel.py` — Stoikov microprice
- `strategy_lab/lee_mykland_2026_05_26/` — LM jump detector
- `strategy_lab/vpin_hawkes_2026_05_26/` — Hawkes self-exciting + VPIN
- `strategy_lab/weighted_voting_2026_05_26/` — Ridge / Logistic Poly2 ⭐

### Round 4 hunt script (template — needs panels fixed before re-running)
- `strategy_lab/sleeve_hunt_15m_2026_05_26.py` — focused 15m search ⚠️ uses leaky regime panel

### Audit scripts (post-audit, use these)
- `strategy_lab/engine_audit_2026_05_26/smoke_test.py` — apples-to-apples val vs lockbox
- `strategy_lab/engine_audit_2026_05_26/regime_leak_test.py` — regime panel leak quantification
- `strategy_lab/post_audit_2026_05_26/bug_fixes.diff` — the 4 actual code diffs

### PDF generators (reusable)
- `strategy_lab/reports/build_per_sleeve_detailed_pdf.py` — per-sleeve PDF builder
- `strategy_lab/reports/build_round6_final_pdf.py` — deploy-ready PDF (R6 template)
- `strategy_lab/reports/build_final_consolidated_pdf.py` — full R1-R4 historical

---

## 5. Round-by-round capsule (what was learned)

| Round | Theme | Key finding | Status |
|---|---|---|---|
| R1 | Prior session foundation | Tier-1 hybrid_v1 family (5-gate stacks: cci+stoch+rf+ema50+ribbon) on BTC/ETH/SOL S6 + S1.5 + S7 | Survived audit |
| R2 | New indicators (DRZ, QR, SMS, regime, 15m hunt) | SMS liq_reclaim BIG WIN at $20.68/tr; 31 R2 15m sleeves | SMS standalone FAILED OOS; 34/37 15m FAILED |
| R3 | Web research + microstructure + cross-exchange + PM flow + vol/Hurst + funding/OI + 22d OOS | 5 R2 sleeves failed OOS; new gates `g_vol_expanding`, `g_flow_no_whale`, `g_book_slope_steep` survived | Identified the 22d window over-fit issue |
| R4 | Full 32d re-validation + 15m hunt v2 | 178 new "deployable" 15m sleeves found using `g_trend_slope_with`; S7_btc_5m_base is new BIG sleeve | Almost all 178 later FAILED post-audit (leaky regime) |
| R5 | Advanced quants (microprice, Lee-Mykland, MLOFI, VPIN, Hawkes, LightGBM, AS, HY) | **Microprice WIN** (Stoikov verified), **Hawkes WIN** (volume play), **LightGBM FAILED** (0/6) | Microprice deploy survives audit |
| R6 | Slug overlap audit + cross-stacking | $85-95k naive → $20.5k after dedup ⭐ critical audit | Slug-overlap awareness now baked in |
| R7 | Regime-conditional + threshold sweep + direction-asymmetric + weighted voting + session × xa | **TT Weighted Logistic Poly2 17× lift** (looked huge but had bugs); STATE-machines = waste; thresholds were too tight (global recalibration helps) | 11.6× val→lockbox jump triggered audit |
| AUDIT | Engine + window audit | **3 bugs found** (fire-count, regime panel, SMS panel) + 1 scaling bug (PP) | Bugs FIXED, top sleeves re-validated |

---

## 6. Gates library (the universal vocabulary)

These gates are the "atoms" of every sleeve. Definitions in
`strategy_lab/meta_classifier/hybrid_join_and_gates.py` (R6) and
`MASTER_DEPLOY_SPEC_2026_05_26.md` §A.5.

### R1 base (16 gates)
`g_rf_with`, `g_ribbon_agrees`, `g_stoch_with`, `g_mfi_with`, `g_cci_with`,
`g_bb_pos_with`, `g_tr_above_ema50`, `g_tr_above_ema200`, `g_tr_above_ema800`,
`g_tr_above_pp`, `g_tr_stack_with`, `g_tr_within_adr`, `g_tight_ribbon`,
`g_within_dev`, `g_dev_extreme`, `g_markov_with`

### R3 (8 gates)
`g_vol_expanding`, `g_vol_high`, `g_vol_contracting`, `g_hurst_trending`,
`g_flow_with_and_no_whale`, `g_coinbase_basis_extreme_against`,
`g_hl_liq_cascade_with`, `g_book_slope_steep_against`

### R4 (6 gates)
`g_trend_slope_with` ⚠️ (came from leaky regime panel — use `_v2_fixed`)
`g_trend_slope_strong_with`, `g_imb5_strong_with`, `g_queue_top_high`,
`g_imb_change_with`, `g_vwap_ge_50_le_85`

### R5 (6 gates)
`g_mp_no_extreme` ⭐ universal tradability filter, `g_mp_change_with`,
`g_mp_skew_with`, `g_lm_high_stat`, `g_hawkes_imbalance_with`, `g_hy_cb_with_dir`

### R7 thresholds — RECALIBRATE GLOBALLY (Agent RR found)
- `g_mp_no_extreme`: 50 bps → **100-150 bps** (looser)
- `g_hawkes_imbalance_with`: 0.3 → **0.1-0.2** (looser)
- `g_hurst_trending`: 0.55 → **0.50** (looser)
- `g_vol_contracting`: 0.7 → **0.85** (looser)

### What does NOT work (confirmed across multiple rounds)
- PVSRA standalone — anti-edge -37pp WR
- Pure RF trigger (V1) — loses on fees
- MLOFI — Cont/Xu/Gould 68-74% RMSE claim does NOT transfer (actual: 0.06%)
- VPIN as skip gate — wrong sign
- LightGBM stacker — 0/6 lockbox pass
- Avellaneda-Stoikov uncertainty — overlaps vol_regime, wrong sign
- Cross-exchange directional lead — binance leads HL by 1s only; major venues co-incident
- MTF 5m+15m parent confluence — hurts net PnL
- Regime-conditional state machines — over-engineering; agnostic gates win
- Standalone microstructure rules — always fail; only as overlay gates do they help
- Discrete asymmetric (UP vs DOWN) gates — marginal

---

## 7. Open problems for next session

### Problem 1: 15m markets have NO clean deployable sleeve
**Status**: After bug fixes, 0/178 R4 trend_slope sleeves and 0/8 R2 hunt sleeves survive lockbox. POOL 600-720 went from +$1,611 to -$1,272.

**Hypothesis**: the `g_trend_slope_with` feature (derived from `trend_slope_30m = (close - close_30m_ago) / atr_60m` in regime_panel) was the load-bearing edge for the entire 15m family. With regime panel bug fixed, trend_slope is still computable but the gate as previously evaluated was contaminated.

**To investigate**:
1. Rebuild `g_trend_slope_with` from the bug-fixed `regime_panel_*_v2_fixed.parquet`
2. Re-search 15m universe with the CLEAN gate
3. Check if SMS leak fix changes anything (it might invalidate `g_sms_liq_reclaim_with` style gates too)
4. Look for fundamentally new 15m alpha (e.g., 1h parent VWAP, daily pivot proximity, slot-end OFI imbalance)

### Problem 2: ETH 5m and SOL 5m don't scale to $250
- ETH 5m R1_eth_5m_s6_tight_pos_cloud: $25 deployable but $250 negative (slippage)
- SOL 5m: SOL S6 hybrid_v1: $25 deployable but $250 strongly negative
- Avg slippage at $250: ETH 463 bps, SOL 773 bps (vs BTC 169-275 bps)

**Hypothesis**: ETH/SOL Polymarket order books are thinner. Need to find sleeves that fire ONLY when book depth supports notional, OR find directional plays where the entry vwap can absorb the slippage cost.

**To investigate**:
1. Use sub-second L25 books to find ETH/SOL fires where depth supports $250
2. Conditional gating: `g_book_depth_supports_notional` filter
3. Asymmetric: maybe ETH UP scales better than ETH DOWN (or vice versa)
4. Time-of-day: maybe NY session ETH books are deeper

### Problem 3: POOL multi-asset deploy
The 5m universe pooled (BTC+ETH+SOL) wasn't tested for deploy candidates after audit. Microprice univ_5m_rf_ribbon was SKIP_OVERLAP. Worth re-running pool search with clean panels.

---

## 8. Next session mission — SNIPER STRATEGY OPTIMIZATION

### The pivot

We accidentally drifted toward "shotgun" sleeves chasing dollar lift:
S7_btc_5m_base fires 4,894×/32d at $1.10/tr; R1_btc_s6_lite has 36-trade
losing streaks at $1,816 max DD. **These are operationally hard to deploy.**

**The next session optimizes for sniper strategies.** Trade LESS, win MORE,
keep DD small. The reference profile is **BTC S15 hybrid_v1**:
- n=1,753 (5.5/day)
- WR 86.3%, $/tr +$3.12
- Max DD only **$269**
- Max loss streak only **6**
- Sharpe 1.26

This is what every new sleeve should look like.

### Sniper target profile (every new sleeve must meet)

| Metric | Target |
|---|---|
| n / 32d | **100-500** (3-15/day) |
| WR | **≥ 75%** |
| $/tr at $25 stake | **≥ $3** |
| Max DD at $25 stake | **≤ $300** |
| Max loss streak | **≤ 6** |
| Sharpe (daily approx) | **≥ 2.0** |
| Bootstrap p (lockbox) | **≤ 0.05** |

### 5 specific paths to sniper alpha

**Path 1: Pre-window entries (ws_s anchor, negative offset)**
The production momo controller already does this. F7 RSI + Markov M1V at ws_s
(slot_start − window_s) are the "look back BEFORE the slot starts" features.
Build candidate triggers like:
- `f7_rsi_at_ws_s in extreme zone (< 30 or > 70)` AND `m1v_va == 2` (bull regime)
- HoD constant + cross-asset RF unanimity at ws_s
- Pre-window dev_bps_vwap (built from binance VWAP over the 60s before slot_start)

These were the production design pre-this-session. They naturally fire 50-200×/32d
because the gates are strict.

**Path 2: Beginning of window (offset 0-60s, UNDER-tested)**
R6 Agent LL found ONE killer cell that was barely explored:
- **BTC S6 offset 0-60s + 12 R1+R3+R4 gates**: WR 79.9%, $/tr +$8.03, n=219, p=0.001
- This profile (n=219, $/tr $8) is EXACTLY the sniper target — almost ignored at the time
- Worth re-mining the 0-60s offset bin systematically across all markets

**Path 3: Very-high-bar gate stacks**
Deliberately push n DOWN by stacking 6-8 strict gates:
- `g_tr_stack_full_with` (full EMA stack alignment, score ±2 only)
- `g_dev_extreme` AND `g_within_dev` (both extreme deviation gates)
- `g_hl_liq_cascade_with` (HL short-liq > $100k in 60s — rare, n=51 in R3)
- `g_lm_high_stat` (Lee-Mykland L > 5.97 — statistically rare jumps)
- `g_xa_all_with_bet` (all 3 assets' RF agree)

These cut n to 50-200 but should push WR to 85-95% if the underlying alpha is real.

**Path 4: Apply R6 master combinatorial WITH n_cap constraint**
Re-run `strategy_lab/master_combinatorial_2026_05_26/` but constrain:
```python
greedy_search(max_n=500, min_wr=0.75, min_dpt=3.0)
```
The prior R6 search maximized sum_pnl with `min_n=30`. That naturally found
shotgun sleeves. With max_n=500 it'll find sniper sleeves the prior search ignored.

**Path 5: Pre-window microprice + flow**
At ws_s − 30s (just before slot opens), look at:
- L25 microprice skew on UP token vs DOWN token
- PM trade flow in last 30s
- Hawkes λ_imbalance over previous 300s
Cross-stack these as a pre-window sniper trigger.

### Round 8 agent batch (sniper-focused)

```
Agent A1 (pre-window sniper search):
  Build features at ws_s and ws_s − 30s. Search for sniper triggers
  combining F7 RSI + Markov + cross-asset RF + microprice at pre-window.
  Constraint: max_n = 500, min_wr = 0.75, min_dpt = $3.
  Apply to BTC/ETH/SOL × 5m and 15m.

Agent A2 (0-60s offset re-mining):
  Re-mine the 0-60s offset bin (the under-tested R6 LL finding).
  Apply R6 master combinatorial with n_cap=500 constraint.
  All 6 markets (BTC/ETH/SOL × 5m/15m).

Agent A3 (high-bar gate stacks):
  Build 6-8 gate stacks using all "rare" gates: g_dev_extreme, g_lm_high_stat,
  g_xa_all_with_bet, g_hl_liq_cascade_with, g_tr_stack_full_with, etc.
  Aim for n=50-200, WR 85%+. Test on all markets.

Agent A4 (15m hunt v3 with bug-free panels, sniper constraint):
  Re-run `sleeve_hunt_15m_2026_05_26.py` with:
    - bug-free panels (regime_panel_*_v2_fixed, sms_panel_*_v2_fixed)
    - oos_fires_*_v2_fixed (9-offset)
    - Strict 3-way: train 20d / val 7d / lockbox 5d
    - max_n=500 constraint, min_wr=0.75, min_dpt=$3
    - Bootstrap p≤0.05 on lockbox
    - Slug overlap audit BEFORE quoting combined

Agent A5 (book-depth-aware sniper for ETH/SOL):
  Build gate `g_book_depth_supports_250` (L25 cumulative depth > 6×$250).
  Apply as filter to ETH/SOL 5m sleeves; find subset that's both deployable
  at $250 AND meets sniper profile (n < 500, DD < $300).

Agent A6 (re-run momo/sniper family in canonical):
  The production has existing sniper sleeves (poly_updown_*_sniper_hod).
  Re-evaluate them on the bug-free panels + 32d window.
  Are any of them better-profiled (lower n, higher WR, lower DD) than
  the post-audit deploy roster? They may have been overlooked.
```

These can run in parallel. Combined expected uplift if any sniper sleeves
emerge: each replaces a shotgun in the deploy roster, reducing total DD
exposure 5-10× per sleeve while preserving most $/28d.

### Acceptance criteria for the new deploy roster

After Round 8, the FINAL deploy roster should:
- Have NO sleeve with loss streak > 8 at $25
- Have NO sleeve with max DD > $500 at $25
- Have median $/tr ≥ $3 across the roster
- Cover all 6 markets (BTC/ETH/SOL × 5m/15m) with at least one sniper sleeve each
- Combined deployable ≥ $50k/28d at $25 (operationally smaller than current $66k
  is OK if DD reduction justifies it)

---

## 9. Critical conventions (from CLAUDE.md)

DO NOT VIOLATE:

- **Timestamps**: UTC microseconds (`*_us` columns) — never localize
- **Outcome resolution**: Chainlink Data Streams (`outcome` column from canonical) — never derive from binance close
- **ws_s anchor**: `ws_s = slot_start − window_s` (NOT slot_start)
- **F7 RSI anchor**: at ws_s, Wilder simple-mean (NOT exponential)
- **Causal lookup**: features at `fire_us` MUST use bars with `ts_us ≤ fire_us − 1_000_000` (1s before fire)
- **Fee model**: `engine_v2.LegacyConfig` = 2%-on-profit-only — matches production
- **L25 entry walk**: `engine_v2.fill_at_book` with `spread_filter=0.02` (BTC/ETH) or `0.025` (SOL)
- **No mid-slot exits, no SL, no TP** on shadow sleeves — hold to slot_end
- **All new sleeves start `mode="paper"`** until operator approves
- **Slug overlap audit BEFORE quoting combined PnL** — naive sum was the #1 bug across this session

### Read these for context
- `CLAUDE.md` (root) — conventions + project layout
- `strategy_lab/reports/HANDOFF_2026_05_23_COMPLETE.md` — prior session handoff
- `strategy_lab/reports/HANDOFF_2026_05_26_COMPLETE.md` ← **THIS FILE**

---

## 10. Files inventory (Round 1-7 + Audit)

### Synthesis reports (chronological — read in order if needed)
1. `MASTER_DEPLOY_SPEC_2026_05_26.md` — R1 implementation spec (has correction banner)
2. `PER_SLEEVE_CATALOG_2026_05_26.md` + `.pdf` — R1 detailed (correction banner)
3. `NEW_INDICATORS_SYNTHESIS_2026_05_26.md` — R2 (correction banner)
4. `ROUND2_NEW_INDICATORS_REPORT_2026_05_26.pdf` — R2 PDF
5. `ROUND3_SYNTHESIS_2026_05_26.md` — R3 OOS reality check (correction banner)
6. `FINAL_CONSOLIDATED_REPORT_2026_05_26.pdf` — R1-R4 historical (superseded)
7. `ROUND5_SYNTHESIS_2026_05_26.md` + `ROUND5_REPORT_2026_05_26.pdf` — R5 advanced quants (correction banner)
8. `ROUND6_SYNTHESIS_2026_05_26.md` — R6 (correct, uses dedup)
9. `SLUG_OVERLAP_DEPLOY_MANIFEST_2026_05_26.md` — Agent PP audit
10. `ROUND7_SYNTHESIS_2026_05_26.md` — R7 cross-cuts (with TT caveats)
11. `WS_POLY2_DEDUP_VALIDATION_2026_05_26.md` — Agent WW
12. `NAIVE_SUM_CORRECTIONS_2026_05_26.md` — Agent VV (the corrections doc)
13. `ENGINE_AUDIT_2026_05_26.md` — Agent BB (the engine audit)
14. `DATA_WINDOW_AUDIT_2026_05_26.md` — Agent CC (window audit)
15. `POST_AUDIT_FINAL_CATALOG_2026_05_26.md` — Agent EE (remediation)
16. `MASTER_SLEEVE_CATALOG_AUDITED_2026_05_26.md` + `.pdf` — Agent DD (448-sleeve catalog)
17. `PER_SLEEVE_DETAILED_2026_05_26.pdf` — final per-sleeve PDF (30 pages)
18. `FINAL_DEPLOY_READY_POST_AUDIT_2026_05_26.pdf` — final deploy PDF
19. `HANDOFF_2026_05_26_COMPLETE.md` ← **THIS FILE**

### Per-agent technical reports
- `QUANT_RESEARCH_2026_05_26.md` — Agent N web research
- `MICROSTRUCTURE_2026_05_26.md` — Agent O L25 micro features
- `CROSS_EXCHANGE_LEADLAG_2026_05_26.md` — Agent P
- `PM_TRADE_FLOW_2026_05_26.md` — Agent Q
- `VOL_HURST_2026_05_26.md` — Agent R
- `FUNDING_OI_2026_05_26.md` — Agent S
- `FULL_WINDOW_VALIDATION_2026_05_26.md` — Agent T narrow OOS
- `FULL_WINDOW_ALL_SLEEVES_2026_05_26.md` — Agent U full-window 42-sleeve
- `FULL_WINDOW_GATE_SEARCH_2026_05_26.md` — Agent V
- `SLEEVE_HUNT_15M_V2_2026_05_26.md` — Agent W (178 R4 15m sleeves — mostly invalidated)
- `MICROPRICE_2026_05_26.md` — Agent Z ⭐ deploy-survived
- `LEE_MYKLAND_2026_05_26.md` — Agent AA
- `MLOFI_2026_05_26.md` — Agent BB-R5 (clean negative)
- `VPIN_HAWKES_2026_05_26.md` — Agent CC-R5
- `LIGHTGBM_STACKER_2026_05_26.md` — Agent DD-R5 (clean negative)
- `AVELL_HAYASHI_2026_05_26.md` — Agent EE-R5
- `MASTER_COMBINATORIAL_2026_05_26.md` — Agent LL
- `R5_GATES_ON_R4_15M_2026_05_26.md` — Agent MM
- `DEEP_STACKING_2026_05_26.md` — Agent NN
- `CROSS_FEATURE_RULES_2026_05_26.md` — Agent OO
- `REGIME_CONDITIONAL_GATES_2026_05_26.md` — Agent QQ
- `THRESHOLD_SWEEPS_2026_05_26.md` — Agent RR
- `DIRECTION_ASYMMETRIC_GATES_2026_05_26.md` — Agent SS
- `WEIGHTED_VOTING_2026_05_26.md` — Agent TT ⭐ headline (with bug caveats)
- `SESSION_CROSS_ASSET_REGIME_2026_05_26.md` — Agent UU

### Deploy roster outputs
- `final_deploy_manifest_v2_post_audit_FULL.csv` — 21-row authoritative manifest
- `master_sleeve_catalog_v2_clean.csv` — top 20 with CLEAN metrics
- `master_sleeve_catalog_audited.csv` — all 448 sleeves with grades
- `per_market_best_sleeve_clean.csv` — per-market best
- `sleeve_notional_scaling_truth.csv` — slippage simulation $25/$250/$2500

### Key scripts (start here for new searches)
- `strategy_lab/sleeve_hunt_15m_2026_05_26.py` — 15m hunt template
- `strategy_lab/meta_classifier/hybrid_backtest.py` — backtest harness
- `strategy_lab/overlap_audit_2026_05_26/` — dedup methodology
- `strategy_lab/post_audit_2026_05_26/` — bug fix diffs

---

## 11. Quick-start commands for next session

```bash
cd "C:/Users/alexandre bandarra/Desktop/global"

# 1. Verify canonical data current
PYTHONIOENCODING=utf-8 C:/Python314/python.exe -c "
import sys; sys.path.insert(0,'data/v4/canonical')
from load import load_resolutions, load_klines_1s
import pandas as pd
r = load_resolutions()
print('Resolutions:', len(r), 'range:', pd.Timestamp(r.slot_start_us.min(), unit='us'), '→', pd.Timestamp(r.slot_start_us.max(), unit='us'))
print('Days:', round((r.slot_start_us.max() - r.slot_start_us.min())/86400e6, 2))
"

# 2. Confirm bug-fixed panels exist
ls -la data/v4/canonical/_results/regime_panel_*_v2_fixed.parquet
ls -la data/v4/canonical/_results/sms_panel_*_v2_fixed.parquet
ls -la data/v4/canonical/_results/_full_window_2026_05_26/oos_fires_*_v2_fixed.parquet

# 3. View final deploy manifest
PYTHONIOENCODING=utf-8 C:/Python314/python.exe -c "
import pandas as pd
m = pd.read_csv('data/v4/canonical/_results/final_deploy_manifest_v2_post_audit_FULL.csv')
print(m[['deploy_priority','sleeve_id','status','asset','tf','wr','sum_28d_25','sum_28d_250']].sort_values('deploy_priority').to_string(index=False))
"

# 4. Re-run 15m hunt with bug-free panels (the next-session priority)
# Use strategy_lab/sleeve_hunt_15m_2026_05_26.py as template;
# patch panel paths to *_v2_fixed.parquet variants;
# add 3-way split with bootstrap p ≤ 0.05 on lockbox;
# always run slug-overlap audit before quoting combined.
```

---

## 12. What NOT to repeat

1. **Don't sum sleeve PnL without dedup.** This was the #1 bug across 6 rounds. Always run `strategy_lab/overlap_audit_2026_05_26/02_pairwise_overlap.py` first.

2. **Don't trust 22-day backtests.** Use 3-way split (train / val / lockbox). Mandate WR ≥ 65% AND lockbox bootstrap p ≤ 0.05.

3. **Don't add gates without OOS validation.** Each new gate must pass the same 3-way split + bootstrap test.

4. **Don't trust PVSRA standalone.** Confirmed -37pp WR. Don't bother re-testing.

5. **Don't try MLOFI again.** 68-74% RMSE academic claim doesn't transfer to Polymarket.

6. **Don't use LightGBM as primary trigger.** It overfits on 32d. Linear models with regularization (Ridge, Logistic L2) are the working ML approach.

7. **Don't assume cross-exchange leads.** Binance leads HL by 1s. Coinbase/Kraken/OKX co-incident. The BASIS is useful, not directional lead.

8. **Don't compute features at fire_us without epsilon.** Always use `ts_us ≤ fire_us − 1_000_000` for 1s panels. For 5m/15m panels, ts_us must be bar END (not START — that was Bug #2).

9. **Don't infer regime from leaky panel.** Use `regime_panel_*_v2_fixed.parquet`.

10. **Don't assume $/tr scales linearly with notional.** L25 depth on Polymarket is the binding constraint. ETH/SOL fail at $250; BTC fails at $2500. Always run L25 slippage simulation.

---

## 13. Update CLAUDE.md

After completing the next session, update `CLAUDE.md` to:
- Point `Most recent session handoff` to this file
- Add note about regime_panel + SMS panel `_v2_fixed` variants being canonical
- Add note about the 32.66d window (Apr 24 → May 26)

Current line in CLAUDE.md to update:
```
**Most recent session handoff:** `strategy_lab/reports/HANDOFF_2026_05_22_MOMO_F7_MARKOV.md`
```

Should become:
```
**Most recent session handoff:** `strategy_lab/reports/HANDOFF_2026_05_26_COMPLETE.md`
```

---

## End

Open this file in any new session. Everything you need is referenced here.
Next mission: find 1 good strategy per uncovered market, starting with the
15m markets which currently have NO clean deployable sleeve. Use the bug-fixed
panels, apply strict 3-way validation, slug-overlap audit before quoting
combined PnL.
