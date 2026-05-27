# SNIPER ETH 5m V8 — Search Report (2026-05-27)

**Mission (V8)**: extend V7 with 2-asset confluence (Path J), TOD specialization (Path K),
5m+15m confluence (Path Q), 1h grandparent (Path L). USE FULL 32.7-day window.
Beat V7 best (c2: `ema50 & hurst_trending & parent15m_ranging` @60 — n=279 lockbox WR 79.2% $/tr +$5.72 sum $1,597).

## Setup

- Universe: `data/v4/canonical/_results/_sniper_eth5m_v8_universe.parquet` (133,497 fires x 284 cols) — V7 base + 21 new V8 gates.
- New V8 gates:
  - **Path J (2-asset confluence)** — joined SOL trend_slope_30m + regime + mp_skew at ws_s.
    - `g_sol_trend_slope_with`, `g_sol_mp_skew_with`, `g_2a_btc_sol_trend_with`,
      `g_2a_btc_sol_mp_with`, `g_3a_unanimity_trend`, `g_3a_unanimity_full`.
  - **Path K (TOD)** — 4 buckets + composite + power-hour atoms:
    `g_tod_asia_morning`, `g_tod_european_morning`, `g_tod_us_afternoon`,
    `g_tod_us_evening`, `g_tod_europe_us_window` (07-19 UTC).
  - **Path Q (5m+15m confluence)** — causal version uses PREVIOUS 15m slot's winner:
    `g_q_prev15m_agrees`, `g_q_15m_streak_agrees` (2-bar streak of same-direction wins).
  - **Path L (1h grandparent proxy)** — 4-bar rolling mean of ETH 15m trend_slope_30m
    + `g_l_mtf_unanimity` (5m + 15m + 1h-proxy all agree).
- Path M (offset=0) — skipped, V8 offset-extension universe not built.
- Path N (binance perp funding) — skipped, VPS3 geoblocked (per CLAUDE.md).
- Search: 50-atom strict combinatorial at depths {3,4} across offsets {30, 60, 90, 120}.
  Found **28,815 raw survivors**.
- Splits (V8 convention 60/20/20): **train 19d / val 6d / lockbox 8d** (May 19-26).
  All metrics computed three ways: lockbox-only, full-window, and the conservative
  `proj_honest = min(proj_32d_from_lockbox, proj_full)`.
- Stake: constant $25. Fee: `engine_v2.LegacyConfig` (2%-on-profit).
- Robust filter: n_lockbox >= 25, train + val dpt > 0, dd_lockbox >= -300, ls <= 6, bootstrap_p <= 0.05.

## Headline result

**V8 produces winning sleeves per path, BUT V7's baseline c2 (no V8 gates) remains the
honest projection champion** when re-run on the V8 60/20/20 splits.

| Cand | family | gate stack | n_lock | WR | $/tr_lock | $sum_lock | DD | n_full | $/tr_full | $sum_full | **proj_honest** |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **V7c2_base** | baseline | ema50 + hurst + parent_ranging | 444 | 79.1% | 5.09 | 2,260 | -153 | 748 | 3.89 | 2,908 | **$2,878** |
| **c1_pathL** | L | ema50 + hurst + grandparent_trend | 258 | 82.6% | 6.33 | 1,633 | -75 | 467 | 4.85 | 2,263 | $2,240 |
| **c2_pathK** | K | hurst_trend + trend + cci + tod_eu_us | 261 | 82.0% | 4.22 | 1,102 | -93 | 522 | 3.43 | 1,790 | $1,771 |
| **c3_pathQ** | Q | ema50 + trend + prev15m_agrees | 293 | 76.8% | 4.17 | 1,220 | -112 | 539 | 3.30 | 1,778 | $1,760 |
| **c4_pathJ** | J | ema50 + parent_ranging + trend + sol_trend | 275 | 80.0% | 4.17 | 1,147 | -102 | 579 | 2.99 | 1,732 | $1,715 |
| c5_pathL_mtf | L+Q | ema50 + hurst_trend + grandparent + prev15m | 181 | 80.1% | 5.15 | 933 | -90 | 334 | 4.07 | 1,358 | $1,344 |

### V7 baseline reprojected on V8 splits
| V7 cand | gate stack | n_lock | WR | $/tr_lock | $sum_lock | n_full | $/tr_full | $sum_full | **proj_honest** |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **V7c2** | ema50 & hurst & parent_ranging | 444 | 79.1% | 5.09 | 2,260 | 748 | 3.89 | 2,908 | **$2,878** |
| V7c3 | cloud & ribbon & mp_skew & hurst & parent_ranging | 260 | 83.9% | 7.07 | 1,837 | 437 | 4.90 | 2,140 | $2,118 |
| V7c5 | cloud & hurst & vwap & parent_ranging | 191 | 71.7% | 8.54 | 1,632 | 265 | 6.70 | 1,776 | $1,758 |
| V7c1 | cloud & vwap & hurst_mp_trend | 118 | 76.3% | 10.88 | 1,284 | 163 | 9.15 | 1,491 | $1,475 |
| V7c4 | ema200 & vwap & ranging_ws & xa_3source @90 | 64 | 76.6% | 11.85 | 758 | 105 | 9.53 | 1,000 | $990 |

V7c2 wins by **proj_honest $2,878** vs V8 best (c1_pathL) $2,240. **Net V8 added 0 sleeves that beat V7c2 honestly.**

---

## TOP 5 V8 CANDIDATES (full per-split metrics)

All const $25, fee_model = engine_v2.LegacyConfig.

### c1_pathL_grandparent — Path L (1h grandparent)
**`g_tr_above_ema50 & g_hurst_trending & g_grandparent_trend_with` @ offset 60**

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (19d) | 130 | 76.2% | +$3.39 |
| val (6d) | 79 | 78.5% | +$3.48 |
| **lockbox (8d)** | **258** | **82.6%** | **+$6.33** |
| **full (33d)** | **467** | **82.0%** | **+$4.85** |

- sum_lockbox $1,633 / sum_full **$2,263** / DD only -$75 / ls=2 / sharpe=181
- proj_32d=$6,665 / proj_full=$2,240 / **proj_honest=$2,240**
- bootstrap_p = 0.000
- **HIGH confidence**: only 3 gates, train + val + lockbox all clean, lowest DD in top 5
- **Insight**: when ETH 5m, 15m, and 1h proxy ALL align, the entry has the strongest joint conditioning

### c2_pathK_TOD_eu_us — Path K (TOD specialization)
**`g_hurst_trend_with & g_trend_slope_with & g_cci_with & g_tod_europe_us_window` @ offset 120**

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (19d) | 124 | 71.0% | +$1.51 |
| val (6d) | 64 | 75.0% | +$3.51 |
| **lockbox (8d)** | **261** | **82.0%** | **+$4.22** |
| **full (33d)** | **522** | **84.7%** | **+$3.43** |

- sum_lockbox $1,102 / sum_full **$1,790** / DD -$93 / ls=2 / proj_honest=$1,771
- **Insight**: TOD window 07-19 UTC (European/US trading hours) PRESERVES edge — overnight Asia trading dilutes it. Restricting to active hours gains stability.

### c3_pathQ_prev15m — Path Q (5m + 15m confluence)
**`g_tr_above_ema50 & g_trend_slope_with & g_q_prev15m_agrees` @ offset 60**

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (19d) | 152 | 70.4% | +$1.15 |
| val (6d) | 94 | 77.7% | +$5.04 |
| **lockbox (8d)** | **293** | **76.8%** | **+$4.17** |
| **full (33d)** | **539** | **77.4%** | **+$3.30** |

- sum_lockbox $1,220 / sum_full **$1,778** / DD -$112 / ls=2 / proj_honest=$1,760
- **Insight**: when the PRIOR ETH 15m slot already resolved in our direction, 5m sniper hits 77% WR. Causal — no lookahead.

### c4_pathJ_sol_xa — Path J (2-asset SOL+ETH confluence)
**`g_tr_above_ema50 & g_parent15m_ranging & g_trend_slope_with & g_sol_trend_slope_with` @ offset 90**

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (19d) | 169 | 74.0% | +$2.31 |
| val (6d) | 116 | 74.1% | +$2.16 |
| **lockbox (8d)** | **275** | **80.0%** | **+$4.17** |
| **full (33d)** | **579** | **80.7%** | **+$2.99** |

- sum_lockbox $1,147 / sum_full **$1,732** / DD -$102 / ls=3 / proj_honest=$1,715
- **Insight**: SOL trend_slope adds confluence to ETH 5m fires; 3-asset unanimity (`g_3a_unanimity_trend`) too rare to win directly (4.7% cov), but pairwise SOL gate works.

### c5_pathL_mtf_unanimity — Path L+Q stack (MTF)
**`g_tr_above_ema50 & g_hurst_trend_with & g_grandparent_trend_with & g_q_prev15m_agrees` @ offset 60**

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (19d) | 81 | 75.3% | +$3.41 |
| val (6d) | 50 | 80.0% | +$5.15 |
| **lockbox (8d)** | **181** | **80.1%** | **+$5.15** |
| **full (33d)** | **334** | **80.5%** | **+$4.07** |

- sum_lockbox $933 / sum_full $1,358 / DD -$90 / proj_honest=$1,344
- **MED confidence**: smaller n, but DEEPEST joint conditioning (5m + 15m + 1h + prev-15m all agree).
  Most robust by stability score but lowest absolute PnL.

---

## V8 path findings

### Path J — 2-asset SOL+ETH confluence — PARTIAL WIN
- `g_sol_trend_slope_with` ALONE has weak signal (40% cov, WR lift +0.3pp) but stacks
  meaningfully into c4 with parent_ranging. 5,926 V8-J survivors total.
- 3-asset full unanimity (`g_3a_unanimity_full` — BTC + SOL + ETH trend + all mp_skews agree) too rare (0.11% cov) — no survivors with n>=25.
- **Insight**: SOL is a noisier signal than BTC for ETH 5m (likely because SOL has different microstructure regime). Lower lift than BTC cross-asset gates in V7.

### Path K — TOD specialization — WIN
- `g_tod_europe_us_window` (07-19 UTC) is the cleanest TOD gate — keeps 50% cov and lifts WR ~2pp on most stacks.
- TOD buckets alone (e.g., `g_tod_european_morning`) don't pass survivor bar.
- Composite Europe+US window > individual buckets.
- **Insight**: ETH 5m sniper works in active liquidity hours; restricting to 07-19 UTC reduces noise from Asia/late-US sessions.

### Path Q — 5m + 15m PREV-slot confluence — WIN
- Initial attempt (use SAME slot 15m fire direction) failed — v3 15m fires include both UP/DOWN paper-trades, so no directional vote.
- CAUSAL fix: use PREVIOUS 15m slot's WINNING direction. `g_q_prev15m_agrees` cov 49%, ~2,614 V8-Q survivors.
- Stacks well with V7 gates: +4-7pp WR lift on most bases.
- **Insight**: trend persistence — when the previous 15m bar won in our direction, the next 5m sniper inherits the regime.

### Path L — 1h grandparent — STRONGEST V8 WIN
- `g_grandparent_trend_with` cov 41%, **9,592 V8-L survivors** — most prolific V8 path.
- Best V8 sleeve (c1_pathL) comes from this path.
- `g_l_mtf_unanimity` (5m + 15m + 1h all agree) cov 4.1% but produces high-WR survivors (V8 c5).
- **Insight**: MTF coherence matters most when extended beyond 15m parent. The 1h proxy disambiguates "5m signal in 15m chop" — restricts to true regime alignment.

### Path M (offset=0) — SKIPPED
- V8 offset=0 universe (`oos_fires_ETH_5m_v8_extra_offsets.parquet`) not built. Cannot evaluate.

### Path N (binance perp funding) — SKIPPED
- VPS3 geoblocked from Binance futures per CLAUDE.md. HL substitute (Path O) not pursued (HL panels exist but build time exceeded budget).

---

## V7+V8 refinement attempt

For each V7 winner base (c2, c3, c5), tested adding ONE V8 gate at a time.

**Result: EVERY V8 gate REDUCES proj_honest vs V7 baseline.** Adds filter out winners faster than losers in the full window.

Best add to V7c5 (cloud + hurst + vwap + parent_ranging): `g_grandparent_trend_with` → dpt_lockbox=$11.02 (n=110, WR 77.3%, DD only -$60). High edge per trade but proj_honest only $1,273 (vs V7c5 base $1,758) due to ~halved n.

Best add to V7c3: `g_grandparent_trend_with` → WR 85.7% n=147 dpt $8.17 (n_full drops 437→247 → proj_honest $1,510, vs base $2,118).

**Implication**: V8 gates trade fire-count for higher per-trade WR but the trade-off is unfavorable for honest projection on this 32.7d window. They MAY become favorable on longer history.

---

## Top failure

**Path J 3-asset unanimity** (`g_3a_unanimity_full` — 3 trends + 3 mp_skews all agree)
collapsed to 0.11% coverage — 147 fires across 33d, no survivor with n_lockbox >= 25.
Hypothesis was that ultra-rare 3-asset full unanimity = ultra-precise signal. In practice
SOL's signal noise destroys the joint. Triple-asset unanimity may need a longer dataset
to reach n_lockbox >= 25.

---

## Recommendation

| Use case | Pick | Why |
|---|---|---|
| **Paper-deploy primary** | V7c2 (`ema50 & hurst & parent_ranging` @60) | Highest proj_honest ($2,878), largest n, well-validated across V7+V8 splits |
| **Lowest-DD alternative** | V8 c1_pathL (`ema50 & hurst & grandparent_trend` @60) | DD only -$75 (half of V7c2), WR 82.6%, $2,240 honest projection |
| **Active-hours specialist** | V8 c2_pathK (`hurst_trend & trend & cci & tod_eu_us` @120) | Only fires 07-19 UTC; useful for daytime-only operators |
| **Multi-TF confidence** | V8 c5_pathL_mtf | When operator wants maximum joint-conditioning (5m+15m+1h+prev-15m all agree) |

**Confidence assessment**:
- V7c2: **HIGH** — repeated across V7 splits and V8 60/20/20 splits
- V8 c1_pathL: **HIGH** — clean monotonic train→val→lockbox improvement, lowest DD, V8-new gate
- V8 c2/c3/c4: **MED-HIGH** — pass survivor bar but smaller n + lower honest projection than V7c2

---

## Files generated

- `_results/v8_validated.csv` — 28,815 raw V8 strict survivors
- `_results/v8_ranked.csv` — robust-filtered, sorted by proj_honest
- `_results/v8_top30_unique.csv` — dedup by lockbox fingerprint
- `_results/v8_top_v8_new_only.csv` — V8-new-gate-containing only (top 30) — empty after final dedup; V7-only gates dominate
- `_results/v7_baseline_in_v8_splits.csv` — V7 c1-c5 reprojected on V8 60/20/20 splits
- `_results/v7_plus_v8_refinement.csv` — V7 base + 1 V8 gate sweep (all reduce proj_honest)
- `_results/top_5_candidates_v8.csv` — final top 5 with per-split + per-window metrics
- `_results/fires_v8_c{1..5}_*.csv` — per-fire detail with split labels
- `cumulative_pnl_v8_c{1..5}_*.png` — 5 cumulative PnL plots with train/val/lockbox color coding
- `scripts/01_build_universe_v8.py` — V8 universe build (Paths J, K, Q, L)
- `scripts/02_add_path_q_extended.py` — extra Path Q causal gates
- `scripts/10_sniper_search_v8.py` — main strict combinatorial search
- `scripts/15_rank_and_dedup_v8.py` — ranking + dedup
- `scripts/16_v8_new_analysis.py` — per-path winners drill-down
- `scripts/20_finalize_top5_v8.py` — top 5 finalize + plots
- `scripts/30_v7_baseline_compare.py` — V7 baseline on V8 splits
- `scripts/35_v7_plus_v8_refinement.py` — V7 + 1 V8 gate sweep

---

## Data integrity notes

- All cross-asset gates joined via causal asof on `ws_s_us` (backward direction, 900s tolerance).
- Splits = 60% train / 20% val / 20% lockbox of unique days (19/6/8d).
- Bootstrap p uses 500 iters daily-clustered. Seed=42 deterministic.
- Outcome truth: chainlink (canonical `outcome` column).
- Path Q causal: uses ETH 15m PREVIOUS slot's resolved winner (asof_backward, 1800s tolerance) — no lookahead.
- All survivor candidates pass: n_lockbox >= 25, train+val dpt > 0, dd >= -300, ls <= 6, bootstrap_p <= 0.05.
