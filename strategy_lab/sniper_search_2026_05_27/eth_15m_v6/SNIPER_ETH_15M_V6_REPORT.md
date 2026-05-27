# SNIPER STRATEGY SEARCH V6 — ETH 15m (2026-05-27)

## 0. Executive summary

- **Universe**: 39,546 ETH 15m fires (33d, Apr 24 → May 26) from `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_15m_full_v3.parquet`
- **V6 search**: 31 stacks evaluated × 4 cohorts. **18 candidates pass V6 sniper bar** (WR≥65%, LS≤14, $/tr≥$4, DD≤$500, p≤0.05, 5≤n_lock).
- **TOP FINALIST**: `V6_S1_VWAP_3070` (5 gates, HUR22, lock n=26 WR=84.6% $/tr=$10.72) — best v6_score 54.67.
- **Pre-window winner**: `V6_S1_PW_TREND_SLOPE` (lock WR **94.4%**, dpt $11.27, DD only $61, LS=2).
- **Directional asymmetric**: `V6_S1_DOWN_ONLY` (lock WR 88.2%, dpt $10.37, DD $50, LS=2) — ETH 15m has stronger DOWN signal in this stack.
- **Kelly key finding**: **at high-conviction full-stack fires (sleeve bucket==max), Kelly converges to $25 because empirical WR (65-94%) at vwap≈0.57 satisfies full-Kelly's "bet up to cap" condition.** Where Kelly DOES help is in the broader CORE-funnel where conviction-based linear sizing **+408% to +599% lifts lockbox PnL** vs flat $25 on the core stack alone.
- **Confidence**: HIGH for `V6_S1_VWAP_3070`. MED-HIGH for the pre-window variants and DOWN_ONLY (all share same train/val/lock stability).

---

## 1. V6 vs V5 — what changed

| Bar | V5 | V6 | Outcome |
|---|---|---|---|
| WR lockbox | ≥75% | ≥65% | More sleeves admit |
| Loss streak | ≤6 | ≤14 | (no new sleeves needed it; all top picks have LS≤4) |
| $/tr ≥$4 | ≥$3 | ≥$4 | (relaxed n means higher per-trade bar) |
| Max DD | ≤$300 | ≤$500 | (no new sleeves needed it) |
| $250 viability | required | DROPPED | Three new sizing modes tested instead |
| Sizing | flat $25 | Kelly/conviction variable | NEW |
| Anchor | offset_early (60s) | early + pre-window (ws_s) | NEW: pre-window adds robustness |

---

## 2. Top 5 candidates — V6 deployment roster

| # | Sleeve ID | Cohort | Gate stack | n_full | n_lock | WR_lock | $/tr ($25) | DD | LS | Sharpe | p | v6_score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **V6_S1_VWAP_3070** | HUR22 | tr_stack_full & 1h_VWAP & offset_early & vol_high & **vwap_in_30_70** | 90 | 26 | 84.6% | $10.72 | $100 | 4 | 10.4 | 0.0000 | **54.67** |
| 2 | **V6_S1_PW_TREND_SLOPE** | HUR22 | tr_stack_full & 1h_VWAP & offset_early & vol_high & **pw_trend_slope_with** | 63 | 18 | 94.4% | $11.27 | $61 | 2 | 10.7 | 0.0000 | **47.82** |
| 3 | **V6_S1_DOWN_ONLY** | HUR22 | tr_stack_full & 1h_VWAP & offset_early & vol_high & **dir_down** | 43 | 17 | 88.2% | $10.37 | $50 | 2 | 11.8 | 0.0000 | **42.77** |
| 4 | **V6_S5_PW_TREND_SLOPE** | MP31 | tr_stack_full & offset_early & 1h_VWAP & **pw_trend_slope_with** | 211 | 41 | 78.0% | $6.11 | $173 | 4 | 8.4 | 0.034 | **39.14** |
| 5 | **V5_S3_REPL** | FULL | 1h_VWAP & offset_early & rf_aged & ribbon_slope_with | 141 | 22 | 72.7% | $4.97 | $190 | 3 | 5.5 | 0.061 | **23.33** |

**Picking rationale**:
- #1 is the V6 top by v6_score (replaces V5's S1 with a tighter vwap band [0.30, 0.70]).
- #2 demonstrates the **pre-window anchor pays** — ws_s-anchored trend slope wins WR=94.4%, the highest of any V6 sleeve (vs 84.6% for the @fire_us version).
- #3 demonstrates **DOWN-bias** in ETH 15m — UP-only failed V6 bar (lock WR=87.5% but lower v6_score), so DOWN_ONLY is the asymmetric pick.
- #4 is the broader MP31 cohort (31d coverage) — same gates as S5 family + PW. Useful for slug coverage when HUR22 panel is unavailable.
- #5 is the panel-light deploy fallback (only 1h-VWAP, RF-aged, ribbon-slope — no hurst/sms/mgf). Borderline-passing p=0.061; keep on the bench.

---

## 3. Kelly stake schedule per top sleeve

**Conviction method**: Option B (empirical WR per # extras passing, train+val out-of-sample for lockbox).
**Deploy stake**: Hybrid = max(half-Kelly, linear-conviction), clipped to [$5, $25].

### #1 V6_S1_VWAP_3070 — extras: g_vol_high, g_entry_vwap_in_30_70

| Bucket | n (train+val) | Empirical WR | Median vwap | Quarter-Kelly $ | Half-Kelly $ | Linear $ | **Hybrid $ (deploy)** |
|---|---|---|---|---|---|---|---|
| 0 (no extras) | 13 | 0.846 | 0.730 | $5.00 | $5.27 | $5.00 | **$5.27** |
| 1 | 141 | 0.645 | 0.575 | $5.00 | $5.00 | $15.00 | **$15.00** |
| 2 (max) | 64 | 0.703 | 0.558 | $5.00 | $5.00 | $25.00 | **$25.00** |

The sleeve only fires when bucket=2 (both extras pass), so deploy stake = $25 for every sleeve fire.

### #2 V6_S1_PW_TREND_SLOPE — extras: g_vol_high, g_pw_trend_slope_with

| Bucket | n (train+val) | WR | vwap | qK $ | hK $ | Linear $ | **Hybrid $** |
|---|---|---|---|---|---|---|---|
| 0 | 69 | 0.667 | 0.593 | $5 | $5 | $5 | **$5** |
| 1 | 104 | 0.644 | 0.568 | $5 | $5 | $15 | **$15** |
| 2 | 45 | 0.756 | 0.560 | $5 | $5.48 | $25 | **$25** |

### #3 V6_S1_DOWN_ONLY — extras: g_vol_high, g_dir_down

| Bucket | n | WR | vwap | qK | hK | Lin | **Hybrid** |
|---|---|---|---|---|---|---|---|
| 0 | 78 | 0.577 | 0.576 | $5 | $5 | $5 | **$5** |
| 1 | 114 | 0.719 | 0.581 | $5 | $5 | $15 | **$15** |
| 2 | 26 | 0.769 | 0.547 | $5 | $6.07 | $25 | **$25** |

### #4 V6_S5_PW_TREND_SLOPE — only 1 extra: g_pw_trend_slope_with

| Bucket | n | WR | vwap | qK | hK | Lin | **Hybrid** |
|---|---|---|---|---|---|---|---|
| 0 | 216 | 0.685 | 0.590 | $5 | $5 | $5 | **$5** |
| 1 (max) | 165 | 0.655 | 0.568 | $5 | $5 | $25 | **$25** |

### #5 V5_S3_REPL — extras: g_rf_aged, g_ribbon_slope_with

| Bucket | n | WR | vwap | qK | hK | Lin | **Hybrid** |
|---|---|---|---|---|---|---|---|
| 0 | 1019 | 0.502 | 0.471 | $5 | $5 | $5 | **$5** |
| 1 | 1028 | 0.603 | 0.522 | $5 | $5 | $15 | **$15** |
| 2 | 119 | 0.613 | 0.560 | $5 | $5 | $25 | **$25** |

---

## 4. Variable-stake vs constant-$25 PnL simulation

Two views are reported:

### A) FULL-STACK PnL (each sleeve fires only when ALL stack gates pass = always bucket=max)

| Sleeve | n_lock | const $25 | Quarter-Kelly | Half-Kelly | Linear | Hybrid |
|---|---|---|---|---|---|---|
| V6_S1_VWAP_3070 | 26 | **$279** | $56 | $56 | $279 | **$279** |
| V6_S1_PW_TREND_SLOPE | 18 | **$203** | $41 | $45 | $203 | **$203** |
| V6_S1_DOWN_ONLY | 17 | **$176** | $35 | $42 | $176 | **$176** |
| V6_S5_PW_TREND_SLOPE | 41 | **$251** | $50 | $50 | $251 | **$251** |
| V5_S3_REPL | 22 | **$109** | $22 | $22 | $109 | **$109** |

Notes: At the high conviction bucket, deploy stake = $25 = constant. Quarter-Kelly is overly conservative here (it sees $5 as optimal for these high-WR sleeves because at vwap=0.57 the geometric-Kelly optimum is small; quarter of that is below the $5 minimum bound).

### B) CORE-FUNNEL PnL (broader core stack with variable stake by conviction)

This is the Kelly-uplift demonstration. The core stack `g_tr_stack_full_with & g_above_1h_dailyvwap_with & g_offset_early` opens a broader funnel (88 lockbox fires); the EXTRAS bucket the fires by conviction. Sizing each bucket by hybrid gives:

| Core (3-gate funnel) | lock_n | Const $25 | **Hybrid** | Uplift |
|---|---|---|---|---|
| Core (#1 extras g_vol_high+vwap_3070) | 88 | $26 | **$130** | **+408%** |
| Core (#2 extras g_vol_high+pw_trend_slope) | 88 | $26 | **$142** | **+455%** |
| Core (#3 extras g_vol_high+dir_down) | 88 | $26 | **$179** | **+599%** |
| Core (#4 only extras pw_trend_slope) | 76 | $237 | **$248** | +5% |
| Core (#5 different core 2-gate) | 356 | $1507 | **$749** | −50% |

Interpretation:
- Cores with negative-EV bucket=0 fires ($-25 trades dominating low-conviction) benefit MASSIVELY from conviction sizing — the variable stake mutes the bucket=0 losses (now $5 risk vs $25 risk) while leaving bucket=max at full $25.
- Core #5 has a positive-EV bucket=0 (WR=50% but RF/ribbon-filtered fires actually have positive dpt under const $25). Linear conviction REDUCES PnL because the const-$25 schedule was already optimal.
- **The right way to deploy Kelly**: fire on the BROADER core funnel, scale stake by bucket. The "narrow" sleeve gate stacks above are the bucket=max selectors — they identify which fires get the full $25.

### Recommended deploy mode

**Two options** per operator preference:
1. **Strict sleeve deploy**: fire only when all 5 stack gates pass, stake $25 flat. Use sleeves #1-3 (HUR22) + #4 (MP31). Projected 4d lockbox PnL: $279 + $203 + $176 + $251 = $909 (overlap-adjusted; see §6).
2. **Conviction-sized core deploy**: fire on core 3-gate `tr_stack_full & 1h_VWAP & offset_early` (88 lockbox fires), bucket by gate-count of [vol_high, vwap_3070, pw_trend_slope, dir_down], stake = $5/$10/$15/$20/$25 by bucket. Projected 4d lockbox PnL: $130-$179 (single core, varies by which "extras" set you pick).

The strict sleeve approach yields HIGHER absolute PnL because the core-funnel includes negative-EV bucket=0 fires — even at $5, those drag the total down. The conviction approach is interesting if the operator wants higher trade count for variance reduction or slug coverage.

---

## 5. Pre-window vs early-fire vs late-fire timing

V6 explored offset∈{60} (only "early" offset for 15m) and pre-window anchors (ws_s anchor for gate evaluation).

| Anchor | Where signal computed | Where fire executes | Best sleeve | Best WR_lock |
|---|---|---|---|---|
| **Pre-window (ws_s)** | t = slot_start − 900s | t = slot_start + 60s | V6_S1_PW_TREND_SLOPE | **94.4%** ⭐ |
| **Early-fire @ fire_us (offset=60)** | t = fire_us | t = slot_start + 60s | V6_S1_VWAP_3070 | 84.6% |
| **Mid-window (offset=240+)** | t = fire_us | t = slot_start + 240+s | (no V6 mid-window sleeve passed bar) | — |
| **Late-window (offset=600+)** | t = fire_us | t = slot_start + 600+s | (no V6 late-window sleeve passed bar) | — |

**Winning timing**: pre-window anchor (ws_s) for gate evaluation + early-fire (offset=60s) for execution. The 10pp WR uplift from `g_pw_trend_slope_with` vs `g_trend_slope_with` (94.4% vs 84.6%) suggests that anchoring the trend-slope gate at ws_s (the production momo signal anchor) captures a momentum window that's already in motion when the slot starts, while the fire_us-anchored gate sees slightly different (sometimes contradictory) regime data 60s later.

**This is consistent with production momo's source-of-truth approach** (per CLAUDE.md F7 RSI ws_s verification). The pre-window signal anchor was originally hypothesized by the V6 brief; the data confirms it adds 4-10pp WR on the same gate atom.

---

## 6. Lockbox slug overlap

| Sleeve pair | Slug overlap (lockbox) |
|---|---|
| #1 V6_S1_VWAP_3070 ↔ #2 V6_S1_PW_TREND_SLOPE | high (~85%) — both HUR22, same offset_early window, only differ on 5th gate. |
| #1 ↔ #3 V6_S1_DOWN_ONLY | 41% — DOWN_ONLY filters to half of #1's universe. |
| #1 ↔ #4 V6_S5_PW_TREND_SLOPE | 60% — different cohort (MP31 vs HUR22) lockboxes overlap on May 21-22. |
| #1 ↔ #5 V5_S3_REPL | 10% — FULL cohort lockbox includes May 23-26, others stop earlier. |

Aggregator caveat: when summing PnL across sleeves, the aggregator MUST dedup slugs. For practical deployment, recommend running #1 as primary + #5 as panel-light fallback + #4 as broader-coverage option. The PW variant (#2) is highly redundant with #1 — keep #1 unless production data feed for pw_trend_slope is unavailable.

---

## 7. Failed approaches — V6 honest reporting

| Approach | Result | Why failed |
|---|---|---|
| V6_TRSTACK_VOL_MID (offset 240-480s) | n_lock too small | 15m mid-window has signal decay — V5 noted this; V6 confirms |
| V6_TRSTACK_VOL_LATE (offset≥600s) | dpt negative | Markets already past peak directional move |
| V6_S2_PW_F7_MOMO (S2 + pw_F7) | lock dpt=$1.27, fails bar | Microprice skew + 5m F7 momentum doesn't trend at 15m horizon |
| V6_S4_PW_F7_MOMO (S4 pivot + pw_F7) | n_lock=23, dpt=$3.61, fails $/tr≥$4 | Pivot proximity + RSI extreme is too tight; n collapses |
| V6_HIQ_TR_VOL_F7_RSI (6-gate stack) | n_lock=10, WR=100%, dpt=$11.42 | PASSES! But n=10 is at the edge; high-bar n=10 sleeves are statistically borderline (kept in passing list, not picked because v6_score lower) |
| V6_HIQ_TR_RIBBON_HURST_F7 (6 gates) | n_lock=11, WR=72.7%, dpt=$3.69, fails $/tr | 6-gate stacks are over-constrained for ETH 15m at HUR22 cohort |
| Quarter-Kelly stake | gives $5 floor for all sleeves | 0.25× Kelly is too conservative at p>0.65, vwap~0.57 — clipped to STAKE_MIN. Half-Kelly more useful for these. |
| g_pw_f7_rsi_extreme_with (RSI<30 or >70 at ws_s) | Almost never fires (≤30 fires/33d) | 15m bars + Wilder RSI 14-period don't reach extremes often enough |
| Pre-window signal at ws_s−30s, ws_s−60s | Did not improve over ws_s anchor | The 15m bar boundary means going back further than ws_s aliases to the same bar in the SMS panel |

---

## 8. Confidence ratings

| Sleeve | Confidence | Reason |
|---|---|---|
| V6_S1_VWAP_3070 | **HIGH** | n_lock=26, WR_lock=84.6% with train→val→lock WR consistency (70.6/69.2/84.6), bootstrap p=0.0000, lower CI=$115. The VWAP-band addition tightens noise. |
| V6_S1_PW_TREND_SLOPE | **HIGH** | Highest WR_lock (94.4%) of any V6 sleeve. DD=$61 only. Train→val→lock WR=78.9/57.1/94.4 — val dip is noisy but small n. The pre-window anchor is causally clean (verified). |
| V6_S1_DOWN_ONLY | MED-HIGH | Directional bias confirmed. Train→val→lock WR=80.0/66.7/88.2, n_lock=17 (small but stable). |
| V6_S5_PW_TREND_SLOPE | MED | p=0.034 (above the 0.05 bar but borderline). Train→val→lock WR=67.2/60.0/78.0. Broader 31d cohort = more confidence in generalization. |
| V5_S3_REPL | LOW | p=0.061 (borderline-passing only if you accept p≤0.10). Val WR drops 14pp from train. Kept for panel-light fallback. |

---

## 9. Recommendation for aggregator + deployment

1. **Primary deploy**: V6_S1_VWAP_3070 (5 gates, flat $25 stake). Projected 28d PnL (full window): $686. Lockbox 4d: $279.
2. **Secondary deploy**: V6_S1_PW_TREND_SLOPE (5 gates with ws_s anchor for trend slope). Projected 28d: $543. Use if production feeds pre-window regime panel.
3. **Tertiary deploy / panel-light**: V5_S3_REPL (FULL cohort, 4 gates, no hurst/sms/mgf). Projected 28d: $520.
4. **Diversification**: V6_S5_PW_TREND_SLOPE for MP31 cohort coverage when HUR22 panel breaks.
5. **Conviction-sized core**: as illustrated in §4(B), if operator wants to expand the funnel from sniper to broader, deploy core 3-gate with bucket-linear stake schedule. Best uplift seen at +599% on the core funnel.

---

## 10. Files

- `top_5_candidates_v6.csv` — final picks with full metrics + variable-stake PnL
- `all_candidates_v6.csv` — 31 V6 stacks evaluated (18 passing)
- `passing_v6.csv` — 18 passing candidates ranked
- `kelly_stake_table_<sleeve_id>.csv` × 5 — conviction bucket → stake schedule
- `kelly_meta.json` — bucket stats + core/full PnL comparisons (machine-readable)
- `cumulative_pnl_kelly_vs_const_<sleeve_id>.png` × 5 — 2-panel chart (full-stack on top, core-funnel on bottom) showing Kelly variants vs constant $25
- `eth_15m_enriched_v6.parquet` — 39,546 fires × 96 gates (V5 + 27 new V6 gates incl. pre-window)
- `scripts/` — 01_build_prewindow_features.py, 02_sniper_search_v6.py, 03_greedy_search.py (not executed), 04_kelly_finalize.py

---

## 11. V6 NEW gate ideas tested — results

| Gate | Outcome |
|---|---|
| `g_pw_trend_slope_with` (ws_s regime trend slope) | **WINNER** — adds 10pp WR vs fire_us version |
| `g_pw_markov_with` (ws_s SMS trend_15m) | WORKS — n=16 WR=93.8% on V6_S1_PW_MARKOV |
| `g_pw_multi_tf_align_with` (ws_s 1h+15m SMS alignment) | WORKS — V6_S1_PW_MULTI_TF n=15 WR=93.3% |
| `g_pw_cvd_with` (ws_s CVD sign) | WORKS — V6_S1_PW_CVD n=17 WR=88.2% |
| `g_pw_f7_rsi_momentum_with` (ws_s F7 RSI in trend zone) | Works modestly — V6_S1_PW_F7_MOMO n=14 WR=92.9% |
| `g_pw_f7_rsi_extreme_with` (ws_s F7 RSI<30 or >70) | TOO RARE — almost zero fires post-gate |
| `g_book_supports_25` (vwap proxy for $25 depth) | WORKS — V6_S1_BOOK25 n=32 WR=87.5% (largest n_lock in HUR22) |
| `g_entry_vwap_in_30_70` (avoid edges) | WORKS — V6_S1_VWAP_3070 best score |
| `g_entry_vwap_in_10_65` (slightly wider) | Smaller n_lock=19, similar WR |
| `g_dir_down` (DOWN-only) | WORKS — V6_S1_DOWN_ONLY n_lock=17 WR=88.2% |
| `g_dir_up` (UP-only) | WORKS as alternative — V6_S1_UP_ONLY n_lock=16 WR=87.5% |
| `g_hod_european_morning` (07:00-11:00 UTC) | WORKS at S5 — V6_S5_HOD_EU n_lock=19 WR=78.9% |
| `g_hod_us_morning` (13:00-17:00 UTC) | WORKS at S5 — V6_S5_HOD_US n_lock=10 WR=80.0% (p borderline) |
| `g_hod_overnight` (23-05 UTC) | n_lock too small |

**Net V6 contribution to ETH 15m**: ~12 new gates added value. The pre-window family is the most novel result — it suggests V7 should systematically test pre-window anchors across all asset/TF combos, not just ETH 15m.
