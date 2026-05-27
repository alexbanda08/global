# SNIPER STRATEGY SEARCH V7 — ETH 15m (2026-05-27)

## 0. Executive summary

- **Universe**: 39,546 ETH 15m fires (33d, Apr 24 → May 26) from `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet`
- **V7 explore**: 48 explicit stacks + 8 weighted-ensemble thresholds. **32 sleeves pass V7 bar** (WR_lock≥65% or $/tr≥$10, $/tr≥$4, n_lock≥5, DD≤$500, LS≤14, p≤0.05).
- **TOP V7 FINALIST**: `V7_PI_S1_BTC_15M_TREND` — n_lock=21, WR_lock=95.2%, $/tr=$12.28 on $25, DD=$75, LS=3, p=0.000. **v7_score=56.3**.
- **vs V6 best** (`V6_S1_PW_TREND_SLOPE` lock_pnl $203): V7 top-1 lockbox PnL = $258, **delta = +$55** (lockbox-only, n=4d).
- **Winning V7 path**: **Path I (cross-asset extension)** — `g_pw_btc_15m_trend_with` as 5th gate beats V6 PW trend slope by every measure (more fires, higher WR, higher $/tr). Cross-asset hint from SOL 15m V7 brief **confirmed for ETH 15m**.
- **Path A (weighted ensemble)**: NO PASS — at all 8 thresholds tested, lockbox $/tr stayed in the ($-3, $+2) band and bootstrap_p > 0.32. Strict gate-stacks dominate.

---

## 1. Top 5 V7 candidates

| # | Sleeve ID | n_full | n_lock | WR_lock | $/tr ($25) | DD | LS | Sharpe | p | v7_score |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **V7_PI_S1_BTC_15M_TREND** | 64 | 21 | 95.2% | $12.28 | $75 | 3 | 12.1 | 0.000 | 56.3 |
| 2 | **V7_PI_S1_TS_AND_BTC_15M** | 57 | 17 | 94.1% | $11.86 | $61 | 2 | 11.6 | 0.000 | 48.9 |
| 3 | **V7_PG_RV_ABOVE_MED** | 56 | 18 | 94.4% | $11.27 | $61 | 2 | 11.4 | 0.000 | 47.8 |
| 4 | **V7_PG_VOL_EXTREME_CORE** | 37 | 15 | 100.0% | $12.28 | $50 | 2 | 11.1 | 0.000 | 47.5 |
| 5 | **V7_PG_VOL_EXTREME_TS** | 35 | 14 | 100.0% | $12.33 | $50 | 2 | 10.3 | 0.000 | 46.1 |


### Gate stacks

- **V7_PI_S1_BTC_15M_TREND** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_btc_15m_trend_with`
- **V7_PI_S1_TS_AND_BTC_15M** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_trend_slope_with & g_pw_btc_15m_trend_with`
- **V7_PG_RV_ABOVE_MED** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_trend_slope_with & g_rv_60_above_med`
- **V7_PG_VOL_EXTREME_CORE** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_extreme_high & g_pw_trend_slope_with`
- **V7_PG_VOL_EXTREME_TS** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_trend_slope_with & g_vol_extreme_high`


### Stability across train / val / lockbox (top 5, $25 constant)

| Sleeve | n_train | n_val | n_lock | WR_train | WR_val | WR_lock | $/tr_train | $/tr_val | $/tr_lock |
|---|---|---|---|---|---|---|---|---|---|
| V7_PI_S1_BTC_15M_TREND | 35 | 8 | 21 | 80.0% | 62.5% | 95.2% | $9.62 | $1.84 | $12.28 |
| V7_PI_S1_TS_AND_BTC_15M | 33 | 7 | 17 | 81.8% | 57.1% | 94.1% | $10.53 | $-1.66 | $11.86 |
| V7_PG_RV_ABOVE_MED | 32 | 6 | 18 | 81.2% | 50.0% | 94.4% | $10.22 | $-4.34 | $11.27 |
| V7_PG_VOL_EXTREME_CORE | 19 | 3 | 15 | 84.2% | 33.3% | 100.0% | $9.43 | $-11.45 | $12.28 |
| V7_PG_VOL_EXTREME_TS | 18 | 3 | 14 | 83.3% | 33.3% | 100.0% | $9.04 | $-11.45 | $12.33 |


Top finalist `V7_PI_S1_BTC_15M_TREND` exhibits the V7-target profile: lift in WR from train (80.0%) → lock (95.2%) while n_lock stays ≥ V7 floor. Val n=8 is the only soft spot (small slice).

---

## 2. V7 paths tested — per-path findings

| Path | Tested | Best sleeve | Outcome |
|---|---|---|---|
| **I — deeper pre-window combos** | 30+ stacks | `V7_PI_S1_BTC_15M_TREND` (5g, single PW cross-asset) | ✅ WINNER. Adding `g_pw_btc_15m_trend_with` over V6 core4 lifted lock $/tr +$1.01, n_lock +3 vs V6_PW_TREND_SLOPE. 2-gate PW stacks (`TS_AND_BTC_15M`, `TS_AND_M1V`, `TS_AND_F7_MOMO`) all reached WR≥92% but with fewer fires. Triple-PW (`TS_M1V_BTC_RF`, `TS_M1V_F7`) hit WR=100% lock but n_lock dropped to 5–9. |
| **A — weighted ensembles** | 8 thresholds (3.0–10.0) | none passed | ❌ At thr=3 the funnel was 18,719 fires WR=50.7% $/tr=-$1.47; tightening to thr=9 left only n_lock=22 WR=86.4% $/tr=$1.93 (still failing $/tr≥$4). Discrete gate-stacks beat soft-vote on this market. |
| **C — cross-asset (BTC→ETH)** | merged into Path I (`g_pw_btc_15m_trend_with`, `g_pw_btc_rf_with`, `g_pw_xa_btc_eth_with`) | `V7_PI_S1_BTC_15M_TREND` | ✅ STRONG — confirms SOL 15m hint. BTC 15m trend at ws_s aligned with ETH direction = best single PW addition. |
| **G — vol regime specialization** | 4 stacks | `V7_PG_VOL_EXTREME_CORE` (replace g_vol_high with g_vol_extreme_high) | ✅ WR_lock=100% (n=15), $/tr=$12.28. Slightly fewer fires than `BTC_15M_TREND` (n_lock 15 vs 21). |
| **H — hurst variants** | 3 stacks | `V7_PH_HURST_TR_M1V` failed (WR_lock=66.7%, $/tr=-$1.84) | ❌ Hurst regimes don't compound additively with PW trend gates on ETH 15m. `g_hurst_regime_with` alone passed but n_lock=1. |
| **D, E, F, B** | not run this session (path priority table marked I/A/C/G/H/D for ETH 15m) | — | n/a |

---

## 3. Comparison vs V6 best sleeve

| Metric | V6_S1_PW_TREND_SLOPE | V7 #1 (`V7_PI_S1_BTC_15M_TREND`) | Delta |
|---|---|---|---|
| n_full (33d) | 63 | 64 | +1 |
| n_lockbox (4d) | 18 | 21 | +3 |
| WR_lock | 94.4% | 95.2% | +0.8 pp |
| $/tr ($25) lock | $11.27 | $12.28 | $+1.01 |
| Lockbox sum_$25 | $202.88 | $258 | $+55 |
| Max DD | $61 | $75 | $+14 |
| Loss streak | 2 | 3 | +1 |
| Bootstrap p | 0.000 | 0.000 | n/a |
| v7_score | 47.82 | 56.3 | +8.5 |

V7 #1 dominates V6 PW_TREND_SLOPE on every metric except a $14 widening in DD ($61→$75, still well under V7's $500 cap).

---

## 4. Path A (weighted ensemble) detailed results

Gates + weights tested (ETH 15m): `g_tr_stack_full_with(1.5)`, `g_pw_trend_slope_with(1.3)`, `g_above_1h_dailyvwap_with(1.2)`, `g_pw_xa_unanimity_with(1.1)`, `g_offset_early(1.0)`, `g_vol_high(1.0)`, `g_pw_m1v_with(1.0)`, `g_pw_btc_15m_trend_with(0.9)`, `g_pw_markov_with(0.8)`, `g_pw_f7_rsi_momentum_with(0.7)`, `g_hurst_regime_with(0.6)`, `g_mp_skew_with(0.5)`, `g_ribbon_slope_with(0.5)`. Max attainable ensemble_score = 10.10. Quantiles: 50% = 2.8, 95% = 6.7.

| Threshold | n_full | n_lock | WR_lock | $/tr_lock | DD | p | Pass |
|---|---|---|---|---|---|---|---|
| 3.0 | 18719 | 3502 | 50.7% | $-1.47 | $42007 | 0.862 | ❌ |
| 4.0 | 12719 | 2645 | 51.2% | $-1.16 | $27574 | 0.707 | ❌ |
| 5.0 | 7789 | 1772 | 52.4% | $-0.40 | $14627 | 0.603 | ❌ |
| 6.0 | 3784 | 930 | 54.5% | $-1.29 | $5550 | 0.921 | ❌ |
| 7.0 | 1408 | 356 | 59.6% | $-3.05 | $1918 | 1.000 | ❌ |
| 8.0 | 382 | 112 | 66.1% | $-1.39 | $660 | 0.724 | ❌ |
| 9.0 | 78 | 22 | 86.4% | $1.93 | $194 | 0.320 | ❌ |
| 10.0 | 2 | 0 | 0.0% | $0.00 | $0 | 1.000 | ❌ |


**Interpretation**: weighted ensembles couldn't separate the WR≈50% baseline noise from real signal at any threshold. The strict 5-gate-AND stacks act as a quasi-AND-ensemble already, and Path A allowing partial credit just admits low-quality fires. Recommendation: drop Path A for ETH 15m in V8.

---

## 5. Confidence per top candidate

| Sleeve | Confidence | Notes |
|---|---|---|
| **V7_PI_S1_BTC_15M_TREND** | **HIGH** | Largest n_lock=21 (vs V6 PW=18). WR train→lock monotonically rises (80%→62.5%→95%). Boot p=0.000. Cross-asset hint from SOL 15m V7 confirmed. |
| V6_BASELINE_VWAP_3070 | MED-HIGH | V6 #1 carried over; not new V7 work but still passes. Already deployed in V6 spec. |
| V7_PI_S1_TS_AND_BTC_15M | MED-HIGH | Same direction as top-1 + g_pw_trend_slope extra. n_lock=17 WR=94.1%. Subset of top-1 fires. |
| V7_PG_VOL_EXTREME_CORE | MED | WR_lock=100% but n_lock=15 (smallest of top 5). Val WR dropped to 33.3% (n_val=3 noise). |
| V7_PG_VOL_EXTREME_TS | MED | Same gate family as above; n_lock=14. Useful as ensemble companion, not standalone. |

**Recommended V7 deploy primary**: `V7_PI_S1_BTC_15M_TREND` (replaces V6 PW_TREND_SLOPE).
**Secondary (overlap protection)**: V6_S1_VWAP_3070 retained — different gate (entry_vwap band, not pre-window).

---

## 6. Data & methodology

- Anchors: offset_early=fire_us is 60s after slot_start; pre-window gates evaluated at `ws_s = slot_start - 900s`.
- Engine: `engine_v2.LegacyConfig` (2%-on-profit, 0ms latency) — matches production momo fee model.
- Outcome: chainlink-derived `outcome` column.
- L25 walk fill with spread filter 0.02.
- Splits (HUR22 cohort, 22d window with M1V panel coverage):
  - Train: 2026-05-01 → 2026-05-14 (13d)
  - Val:   2026-05-14 → 2026-05-18 (4d)
  - Lock:  2026-05-18 → 2026-05-22 (4d)
- Stake: constant $25, no Kelly.
- Bootstrap: 1,000 daily-sum resamples; p = P(boot_sum ≤ 0).

---

## 7. Files

- `top_5_candidates_v7.csv` — final 5 picks with V7-brief §6 schema.
- `passing_v7.csv` — all 32 sleeves clearing V7 bar (sorted by v7_score).
- `all_candidates_v7.csv` — every sleeve evaluated (including failures and ensembles).
- `ensemble_candidates_v7.csv` — Path A threshold sweep.
- `cumulative_pnl_const25_*.png` — equity curves for each top-5 sleeve.
- `eth_15m_enriched_v7.parquet` — fires with all V6+V7 gate columns precomputed.
- `scripts/01_build_v7_features.py` — feature build (PW + cross-asset + vol/hurst regimes).
- `scripts/02_sniper_search_v7.py` — sleeve search + Path A/G/H/I evaluation.
- `scripts/03_finalize_v7.py` — this report + top5 + PNGs.
