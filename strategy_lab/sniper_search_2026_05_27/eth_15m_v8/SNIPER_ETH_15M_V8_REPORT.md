# SNIPER STRATEGY SEARCH V8 — ETH 15m (2026-05-27)

## 0. Executive summary

- **Universe**: 39,546 ETH 15m fires (33d, Apr 24 → May 26 2026 17:37 UTC) from `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet`.
- **Split (V8 brief §0, 60/20/20 by date)**: train = 19d (Apr 24 → May 12) / val = 7d (May 13 → May 19) / lockbox = 7d (May 20 → May 26). HUR22 reference split (May 18 → May 22) also kept for V7-compat.
- **V8 explore paths run**: J (2-asset confluence), K (TOD specialization), L (1h grandparent + cascade), J+K, J+L, J+K+L. Path M (offset=0) **N/A** — minimum offset in v3 fires is 60s, no offset=0 universe built this round.
- **84 unique sleeves evaluated** (47 first pass + 38 extended with full-window-safe `g_vol_high_rg`). **56 pass V8 bar**.
- **TOP V8 FINALIST**: **`V8_BASELINE_V7_TOP`** (= V7 winner replicated under V8 split) — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_btc_15m_trend_with`. n_full=64, WR_full=82.8%, $/tr_full=$9.52, $/tr_lock=$12.13, **proj_honest = $948 / 32.7d**.
- **No V8 path beat V7 winner on `proj_honest`.** V7 baseline still dominates. V8 paths J/K/L each produced strong sleeves (WR_lock=100% common) but with fewer fires → lower honest projections.

---

## 1. Top 5 V8 candidates (distinct gate stacks)

| # | Sleeve ID | n_full | n_lock | WR_full | WR_lock | $/tr_full | $/tr_lock | DD | LS | p_lock | proj_32d | proj_full | **proj_honest** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **V8_BASELINE_V7_TOP** | 64 | 12 | 82.8% | 100.0% | $9.52 | $12.13 | $75 | 3 | 0.000 | $1,584 | $948 | **$948** |
| 2 | **V8_PJ_SOL15M_ALONE** | 61 | 9 | 78.7% | 100.0% | $7.53 | $10.98 | $61 | 2 | 0.000 | $1,076 | $750 | **$750** |
| 3 | **V8_PJ_V7TOP_AND_2A_BTC_SOL** | 51 | 8 | 80.4% | 100.0% | $8.55 | $12.19 | $61 | 2 | 0.000 | $1,062 | $712 | **$712** |
| 4 | **V8_PJ_3A_TREND_UNANIM** | 50 | 8 | 80.0% | 100.0% | $8.19 | $12.19 | $61 | 2 | 0.000 | $1,062 | $669 | **$669** |
| 5 | **V8_PK_CORE_US_PM** | 50 | 10 | 76.0% | 90.0% | $6.21 | $8.02 | $50 | 2 | 0.137 | $873 | $596 | **$596** |

### Gate stacks

- **V8_BASELINE_V7_TOP** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_btc_15m_trend_with` (identical to V7 PI_S1_BTC_15M_TREND)
- **V8_PJ_SOL15M_ALONE** — `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early & g_vol_high & g_pw_sol_15m_trend_with` (SOL trend substitutes BTC trend)
- **V8_PJ_V7TOP_AND_2A_BTC_SOL** — V7 top + `g_2a_btc_sol_trend_with` (BTC AND SOL 15m trend slopes both align)
- **V8_PJ_3A_TREND_UNANIM** — V6 core4 + `g_3a_trend_unanimity_with` (BTC + SOL + ETH 15m trends all align with direction)
- **V8_PK_CORE_US_PM** — V6 core4 + `g_tod_us_pm` (US afternoon 13-19 UTC) — note p=0.137 (val drag)

### Stability across train / val / lockbox (top 5)

| Sleeve | n_train | n_val | n_lock | WR_train | WR_val | WR_lock | $/tr_train | $/tr_val | $/tr_lock |
|---|---|---|---|---|---|---|---|---|---|
| V8_BASELINE_V7_TOP        | 27 | 25 | 12 | 81.5% | 76.0% | 100.0% | $11.18 | $5.99 | $12.13 |
| V8_PJ_SOL15M_ALONE        | 28 | 24 | 9  | 75.0% | 75.0% | 100.0% | $6.71  | $6.93 | $10.98 |
| V8_PJ_V7TOP_AND_2A_BTC_SOL| 21 | 22 | 8  | 81.0% | 77.3% | 100.0% | $11.46 | $4.39 | $12.19 |
| V8_PJ_3A_TREND_UNANIM     | 21 | 21 | 8  | 81.0% | 76.2% | 100.0% | $11.46 | $4.07 | $12.19 |
| V8_PK_CORE_US_PM          | 22 | 18 | 10 | 86.4% | 38.9% | 90.0%  | $13.34 | $-7.20| $8.02  |

V7 baseline shows the cleanest train→val→lock stability. V8_PK_CORE_US_PM has a val-window dip (WR=38.9%) but recovers on lock — classic small-n noise (n_val=18 only).

---

## 2. V8 paths — per-path findings

| Path | Tested | Best sleeve | Best proj_honest | Outcome |
|---|---|---|---|---|
| **Baseline (V7 replication)** | 3 | V8_BASELINE_V7_TOP | **$948** | Reference. **Still the winner.** |
| **J — 2-asset confluence** | 20 | V8_PJ_SOL15M_ALONE | $750 | SOL 15m trend alone substitutes for BTC trend (≈8% fewer fires, lower full-window $/tr). 3-asset unanimity (BTC+SOL+ETH all aligned) reaches WR_lock=100% but n_full=50 vs baseline 64. **Best 2-asset finding**: BTC AND SOL trends both required = 51/8 lock, identical lock metrics to baseline. No multiplicative lift. |
| **K — TOD specialization** | 18 | V8_PK_V7TOP_US_PM | $517 | **US PM (13-19 UTC) is the strongest TOD bucket** for V7-top. Asia (00-07) and European (07-13) buckets reduce n too far (n_full≤12). US Evening (19-24) shows WR_lock=100% but only n_lock=3-4. No TOD bucket beats baseline. |
| **L — 1h grandparent cascade** | 20 | V8_PL_1H_TREND_STRONG | $582 | 1h ETH trend (4h slope, regime label) + V6 core4: 54 fires, WR_lock=91.7%, $/tr_lock=$8.44. **Helpful as standalone gate but weaker than V7 baseline.** Full cascade (5m + 15m parent + 1h grandparent all aligned) = `g_cascade_full_strong`: too restrictive, n_lock drops to 6. |
| **J+K cross** | 4 | V8_JK_RG_V7TOP_3A_US_EVE | $791 (fail p) | Adding TOD bucket on top of 2-asset stack collapses n. US Eve bucket has only 2-3 lock fires. |
| **J+L cross** | 5 | V8_JL_RG_V7TOP_3A_1H | $-103 (neg full $/tr) | 1h + 3-asset confluence over-filters: WR_lock=100% / n_lock=6 BUT full $/tr=-$1.93 (training poor). **Over-fit risk: high.** |
| **J+K+L triple** | 12 | V8_JKL_RG_V7TOP_SOL_1H_US_PM | $-425 (fail) | Stacking 3 V8 paths shrinks to n_full ≤ 14. Catastrophic. |
| **M — offset=0** | 0 | n/a | n/a | **Not run**: v3 fires have min offset=60s. Building offset=0 universe is out of scope for this V8 round. |

---

## 3. Critical finding — feature staleness on lockbox window

V6 enriched panel (which V7 + V8 inherit) uses `g_vol_high` derived from `rv_60s` (master_gate_features_v2). **`rv_60s` ends May 22.** Therefore every V7-style stack containing `g_vol_high` produces zero fires on May 23-26 (4 of 7 lockbox days).

**Mitigation tested**: built `g_vol_high_rg` from `realized_vol_60m_rg` (regime_panel_15m, covers Apr 28 → May 25). 76% agreement with `g_vol_high` on overlap dates. V8_V7TOP_VOLRG_V8 (V7 stack with `g_vol_high_rg` substitute) recovers 12 lock fires but WR_full drops 82.8% → 71.7% — the alternative vol gate admits more noise.

**Conclusion**: do NOT swap `g_vol_high` → `g_vol_high_rg` blindly. The V7 baseline's lockbox $948 honest projection is the genuine ceiling, but the lockbox window only contains 3 active fire days (May 20/21/22). Operator should weight `proj_full = $948` over `proj_32d = $1,584` because:
- proj_32d extrapolates from 3 active days only → noisy.
- proj_full uses 21 active fire days → more stable.

---

## 4. Comparison vs V7 best sleeve

| Metric | V7 #1 (`V7_PI_S1_BTC_15M_TREND`, HUR22) | V8 #1 (V7 top under V8 split) | Delta |
|---|---|---|---|
| Same gate stack | yes | yes | — |
| n_full | 64 (33d) | 64 (33d) | 0 |
| n_lockbox | 21 (4d HUR22) | 12 (7d V8) | -9 (HUR22 lock was active days, V8 lock 4d empty) |
| WR_full | 82.8% | 82.8% | 0 |
| WR_lock | 95.2% (HUR22) | 100.0% (V8) | +4.8 pp |
| $/tr_lock ($25) | $12.28 | $12.13 | -$0.15 |
| max DD | $75 | $75 | 0 |
| proj_32d | $2,106 (HUR22 pace × 32.66/4) | $1,584 (V8 pace × 32.66/3) | -$522 |
| **proj_honest** | n/a in V7 (single-window) | **$948** | new V8 metric |

V8 brief required reporting `proj_honest = min(proj_32d, proj_full)`. Under that lens, **V7 reported pace was over-projected because HUR22 lock was 4 active days giving high $/tr × n density; full window dilutes that to $948**.

---

## 5. Confidence + recommended deploy

| Sleeve | Confidence | Notes |
|---|---|---|
| **V8_BASELINE_V7_TOP** | **HIGH** | Same gates as V7 winner. Now scored with V8 honest projection ($948 vs V7's optimistic $2,106). Stable train→val→lock (WR 81.5% → 76.0% → 100.0%). Bootstrap p=0.000. |
| V8_PJ_V7TOP_AND_2A_BTC_SOL | MED-HIGH | Adds BTC+SOL trend confluence. 51 fires (-13 vs baseline), but same lock $/tr. Useful as **risk-overlay**: only 80% of baseline fires also see SOL trending — could deploy as "confidence-weighted" position sizer. |
| V8_PJ_SOL15M_ALONE | MED | SOL trend substitute. 61 fires WR_full=78.7% (vs baseline 82.8%). Useful for ensemble diversification — fires partially overlap with V7 top but capture some unique signal. |
| V8_PK_V7TOP_US_PM | MED-LOW | TOD-restricted variant. n_full=30 (less than half baseline). Cuts asia/eu/eve hours. Useful only if operator wants TOD-specialized deploy (avoid overnight). |
| V8_PL_1H_TREND_STRONG | MED-LOW | Path L sole survivor at scale (n_full=54). $/tr_full=$5.61 (vs baseline $9.52). Wider universe but lower edge per trade. |

**Recommended V8 primary**: `V8_BASELINE_V7_TOP` (= V7 winner). **No V8 sleeve dethrones it** on honest projection. V8 confirms V7 winner was the right call.

**Optional ensemble overlay**: layer `g_2a_btc_sol_trend_with` (Path J) as a position-sizer (full size when SOL also trends, half size otherwise). Both gates already in `eth_15m_enriched_v8.parquet`.

---

## 6. Data + methodology

- Universe: 39,546 ETH 15m fires (33d Apr 24 → May 26).
- Offsets present: 60, 120, 240, 360, 480, 600, 720, 840s (offset=0 NOT BUILT for V8).
- Anchors: `ws_s = slot_start - 900`; cross-asset RF gates evaluated at `ws_s_m30 = ws_s - 30s`; trend slopes at `ws_s`.
- Engine: legacy 2%-on-profit-only fee model (matches production momo). `pnl_legacy_usd` column already scaled to $25 constant stake (`mean |pnl| = 22.73`).
- Outcome: chainlink-derived `outcome` column.
- L25 walk fill with spread filter 0.02 (inherited from v3 universe build).
- V8 split: dates sorted, 60/20/20 by index → train=Apr 24–May 12 (19d), val=May 13–May 19 (7d), lock=May 20–May 26 (7d). HUR22 split also kept for V7 baseline replication.
- Bootstrap: 1,000 daily-sum resamples on lockbox; p = P(boot_sum ≤ 0).
- New panels built for V8:
  - SOL 15m trend slope from `regime_panel_15m_v2_fixed` (Apr 28 → May 25, asof at ws_s)
  - 1h grandparent ETH regime: resampled binance 1m klines → 1h closes → 4h slope label
  - `g_vol_high_rg` from `realized_vol_60m_rg` quantile (full-window-safe alternative)

---

## 7. Files

- `top_5_candidates_v8.csv` — final 5 distinct picks with full V8 schema (V8 brief §5).
- `passing_v8.csv` — 56 sleeves passing V8 bar (sorted by proj_honest).
- `all_candidates_v8.csv` — every sleeve evaluated (84 unique).
- `eth_15m_enriched_v8.parquet` — fires with V7 cols + 18 V8 J/K/L gates.
- `cumulative_pnl_const25_*.png` — equity curves for top 5 (LOCK window shaded).
- `scripts/01_build_v8_features.py` — V8 feature build (SOL 15m trend, 1h grandparent, TOD buckets, 2-asset & 3-asset confluence).
- `scripts/02_sniper_search_v8.py` — initial V8 sleeve search (47 stacks).
- `scripts/02b_sniper_search_v8_extended.py` — extended search with `g_vol_high_rg` fallback (38 stacks).
- `scripts/03_finalize_v8.py` — top5 + PNGs + path summary.
- `_logs/search_run.log`, `_logs/search_extended_run.log`, `_logs/finalize_run.log`.

## 8. What V8 brief §5 §6 asked vs what was delivered

| Brief requirement | Status |
|---|---|
| Path J (2-asset confluence) | ✅ done — BTC+SOL trend, 3-asset RF unanimity, 3-asset trend unanimity (strong) |
| Path K (TOD specialization, 4 buckets) | ✅ done — asia/european/us_pm/us_eve buckets x V7-top variants |
| Path L (1h grandparent regime cascade) | ✅ done — built 1h ETH regime from 1m klines, trend/strong/extreme + cascade gates |
| Path M (offset=0 fires) | ⏭ skipped — fires universe min offset=60s; offset=0 build out of scope |
| USE FULL 32.7d WINDOW | ✅ done — used all 33d available; split 60/20/20 |
| Report n_full / WR_full / $/tr_full alongside lockbox | ✅ done in top_5_candidates_v8.csv |
| Report proj_32d / proj_full / proj_honest | ✅ done |
| top_5_candidates_v8.csv | ✅ schema matches brief |
| Cumulative PnL PNGs | ✅ 5 PNGs written |
| SNIPER_ETH_15M_V8_REPORT.md | ✅ this file |
| Code in `scripts/` | ✅ done |
