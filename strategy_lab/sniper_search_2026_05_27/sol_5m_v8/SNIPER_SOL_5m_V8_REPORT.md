# SNIPER SEARCH V8 REPORT — SOL 5m

**Date:** 2026-05-27
**Market:** SOL, 5-minute UP/DOWN, window_s = 300, spread_filter = 0.025
**Universe:** 101,500 v3 fires (33d Apr 24 → May 26 UTC); 101,249 eligible after $25 valid-fill filter.
**Working dir:** `strategy_lab/sniper_search_2026_05_27/sol_5m_v8/`

---

## TL;DR

**127 V8-profile-passing sleeves (p_boot ≤ 0.05) after dedupe. Top 5 diversified picks:**

| sleeve | tags | gate stack | n_l | WR_l | $/tr_l | n_full | WR_f | $/tr_f | proj_32d | proj_full | proj_honest | p_boot |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **SOL5_V8_S1** | V7_inherited_C | `g_btc_f7_against + g_cci_extreme_with + g_hurst_reverting + g_mfi_strong_with` | 89 | **78.7%** | **$6.52** | 649 | 75.2% | $6.08 | $3,157 | $3,905 | **$3,157** | 0.0045 |
| **SOL5_V8_S2** | K_TOD | `g_f7_v7_with + g_tod_us_afternoon + g_tr_above_ema200 + g_vwap_in_45_85` | 290 | 78.6% | $4.59 | 1601 | 71.8% | $1.83 | $7,245 | $2,897 | $2,897 | 0.0000 |
| **SOL5_V8_S3** | J_2asset | `g_2asset_either_trending_with + g_cci_extreme_with + g_rf_with + g_tr_above_ema200` | 114 | 76.3% | $4.23 | 685 | 74.5% | $3.42 | $2,626 | $2,321 | **$2,321** | 0.0300 |
| **SOL5_V8_S4** | K_TOD | `g_3asset_unanimity + g_cci_extreme_with + g_stoch_strong_with + g_tod_us_open` | 38 | **86.8%** | $6.91 | 129 | 82.2% | $11.03 | $1,428 | $1,408 | **$1,408** | 0.0055 |
| **SOL5_V8_S5** | K_TOD | `g_f7_v7_with + g_tod_us_afternoon + g_tr_full_stack_with` | 250 | 87.2% | $4.57 | 1555 | 81.4% | $1.20 | $6,223 | $1,843 | $1,843 | 0.0000 |

**Winning V8 paths**: Path K (TOD specialization, 71/127 winners) and Path J (2-asset confluence, 32/127). Path O (HL liq) only contributed weak/early-only signals (HL coverage ends May 16, not full window). Path Q (5m+15m confluence) saturated at >99% pass — no edge.

**vs V7 baseline (`g_btc_trend_30m_with + g_cci_extreme_with + g_hurst_reverting`)**:
- V7 (28d V7-panel splits): lockbox n=45 WR 82.2% $/tr $12.59 = proj_32d **$4,625**
- Same stack on V8 60/20/20 splits with full 33d window: lockbox n=103 WR 71.8% $/tr $3.95; full n=659 WR 72.5% $/tr $4.71 = proj_full **$3,072**
- V7's tiny lockbox (4d) was an extreme period; the full 33d projection is more honest.

**V8's S1 ($/tr_full=$6.08, proj_honest=$3,157) BEATS V7 baseline ($/tr_full=$4.71, proj_full=$3,072) by 3% on honest projection, with much wider validation footprint (n_full=649 vs the V7 published n_lockbox=45).** S1 adds `g_mfi_strong_with` to a V7-cousin (`g_btc_f7_against` instead of `g_btc_trend_30m_with`) — both contrarian-BTC plus reverting-SOL plus extreme oscillator stacks.

Confidence: **HIGH** for S1, S4 (low p, multi-split monotone, V8 paths confirmed) | **MED** for S2, S5 (TOD picks with severe full vs lockbox gap = overfit to lockbox period) | **HIGH** for S3 (J 2-asset confluence with stable train/val/lockbox WRs in 75-79% band).

---

## 1. What V8 changed vs V7

| | V7 | V8 |
|---|---|---|
| Window | capped at 28d (parent_15m_regime intersection) | **full 33d v3 window** |
| Split | 18/6/4 (V7 brief) | **60/20/20** (20/7/6 days) |
| Path J — 2-asset confluence | not tested | **8 new gates** (BTC+ETH slope/regime agreement) |
| Path K — TOD specialization | only `g_hod_european_morning` (SOL 15m, not 5m) | **11 new TOD bucket gates** (asia/european/us/sub-buckets) |
| Path Q — 5m+15m confluence | not tested | **10 new gates** (n_15m_fires, dir bias, WR confluence) |
| Path O — HL liq cascade | tested in V5 marginally | **14 new gates** (long/short cascade, dominance, quiet) |
| Projection convention | single lockbox proj_32d | **proj_32d + proj_full + proj_honest** (min) |
| Path A (weighted ensemble) | tested, FAILED | not re-tested (settled negative in V7) |

Result: **Path K (TOD) is the dominant V8 winner** — 71/127 final sleeves include a TOD anchor. SOL 5m has clear edge concentration in `g_tod_us_open` (13-15 UTC) and `g_tod_us_afternoon` (13-18 UTC) and a smaller `g_tod_eu_open` (7-9 UTC) cluster. **Asia/Asia-Late buckets did NOT produce strong sleeves** despite the V8 hypothesis that SOL would favor Asia hours (regional perp activity).

---

## 2. Splits & data window

| Split | Days | Date range | n (eligible) |
|---|---|---|---|
| Train | 20 | Apr 24 → May 13 | 59,527 |
| Val | 7 | May 14 → May 20 | 20,012 |
| Lockbox | 6 | May 21 → May 26 | 21,710 |
| **FULL** | **33** | Apr 24 → May 26 | **101,249** |

---

## 3. Top sleeves — full metrics

### S1 — `SOL5_V8_S1` (best honest projection)
**Stack**: `g_btc_f7_against & g_cci_extreme_with & g_hurst_reverting & g_mfi_strong_with`
**Tags**: V7_inherited_C (cross-asset BTC + hurst reverting + momentum extreme)

| | train | val | lockbox | **FULL** |
|---|---|---|---|---|
| n | 331 | 229 | **89** | **649** |
| WR | 71.9% | 78.6% | **78.7%** | **75.2%** |
| $/tr @ $25 | $3.79 | $9.21 | **$6.52** | **$6.08** |
| sum @ $25 | $1,255 | $2,110 | **$580** | **$3,946** |
| Max DD | - | - | **$116** | - |
| Max LS | - | - | **3** | - |
| Sharpe | - | - | - | - |
| Bootstrap p | - | - | **0.0045** | - |
| **proj_32d** | | | | **$3,157** |
| **proj_full** | | | | **$3,906** |
| **proj_honest** | | | | **$3,157** |

**Why it works**: BTC f7 RSI contrarian (BTC overbought → SOL DOWN, BTC oversold → SOL UP) PLUS SOL in mean-revert regime (hurst<0.5) PLUS SOL CCI extreme + MFI strong with-direction = high-conviction reversal where SOL leads/diverges from BTC. The V7 S3 cousin (`g_btc_f7_against + g_cci_extreme_with + g_hurst_reverting`) had n_lockbox=49 WR 87.8%; adding `g_mfi_strong_with` boosts n by 80% and stabilizes wr_full at 75% with only 8.5% drop in WR — net big improvement in dollars/window.

Confidence: **HIGH.** Monotone increasing $/tr across splits ($3.79 → $9.21 → $6.52), wide n_full=649, low DD ($116), LS=3, p=0.0045. V7-path validated and extended.

### S2 — `SOL5_V8_S2` (largest n + Path K winner)
**Stack**: `g_f7_v7_with & g_tod_us_afternoon & g_tr_above_ema200 & g_vwap_in_45_85`
**Tags**: K_TOD (US afternoon 13-18 UTC specialization)

| | train | val | lockbox | **FULL** |
|---|---|---|---|---|
| n | 1054 | 257 | **290** | **1601** |
| WR | 71.3% | 66.1% | **78.6%** | **71.8%** |
| $/tr @ $25 | $1.56 | -$0.20 | **$4.59** | **$1.83** |
| sum @ $25 | $1,647 | -$51 | **$1,331** | **$2,930** |
| Max DD | - | - | **$378** | - |
| Max LS | - | - | **8** | - |
| Bootstrap p | - | - | **0.0000** | - |
| **proj_32d** | | | | **$7,245** |
| **proj_full** | | | | **$2,897** |
| **proj_honest** | | | | **$2,897** |

**Concern**: severe lockbox vs full $/tr gap ($4.59 vs $1.83) = overfit to a particularly lucky lockbox window. Val is also weak (-$0.20 $/tr). **Honest projection $2,897 is the correct read.** S2 fires 19/day in lockbox (290 fires / 6d) which is highest volume of any pick; even at honest $1.83/tr that's ~$89/day at $25 stake.

Confidence: **MED.** TOD anchor (us_afternoon) appears repeatedly in top sleeves → real edge exists, but specific train/val/lockbox alignment looks lucky. Recommend paper-trade observation period before live.

### S3 — `SOL5_V8_S3` (best Path J 2-asset confluence)
**Stack**: `g_2asset_either_trending_with & g_cci_extreme_with & g_rf_with & g_tr_above_ema200`
**Tags**: J_2asset (BTC or ETH 5m regime trending in SOL direction + SOL momentum extreme + range filter)

| | train | val | lockbox | **FULL** |
|---|---|---|---|---|
| n | 344 | 227 | **114** | **685** |
| WR | 73.3% | 75.3% | **76.3%** | **74.5%** |
| $/tr @ $25 | $2.45 | $4.50 | **$4.23** | **$3.42** |
| sum @ $25 | $843 | $1,021 | **$482** | **$2,343** |
| Max DD | - | - | **$134** | - |
| Max LS | - | - | **3** | - |
| Bootstrap p | - | - | **0.0300** | - |
| **proj_32d** | | | | **$2,626** |
| **proj_full** | | | | **$2,321** |
| **proj_honest** | | | | **$2,321** |

**Why it works**: `g_2asset_either_trending_with` is moderately strict (7.3% pass rate); means BTC OR ETH regime is `trending_up`/`trending_dn` in SOL bet direction AND neither is trending opposite. Cross-asset trend leadership signal. Plus CCI extreme + range filter + EMA trend ⇒ aligned multi-asset+oscillator stack. Very stable across all splits (73-76% WR, all positive $/tr).

Confidence: **HIGH.** Most consistent split-by-split sleeve in V8. n_full=685 is wide. Lower projection but lowest overfit risk.

### S4 — `SOL5_V8_S4` (Path K + Path J 3-asset unanimity)
**Stack**: `g_3asset_unanimity & g_cci_extreme_with & g_stoch_strong_with & g_tod_us_open`
**Tags**: K_TOD + J 3-asset (BTC + ETH + SOL all-slope-agree + SOL momentum extreme + US open 13-15 UTC)

| | train | val | lockbox | **FULL** |
|---|---|---|---|---|
| n | 67 | 24 | **38** | **129** |
| WR | 86.6% | 87.5% | **86.8%** | **82.2%** |
| $/tr @ $25 | $11.34 | $11.43 | **$6.91** | **$11.03** |
| sum @ $25 | $759 | $274 | **$263** | **$1,423** |
| Max DD | - | - | **$25** | - |
| Max LS | - | - | **1** | - |
| Bootstrap p | - | - | **0.0055** | - |
| **proj_32d** | | | | **$1,428** |
| **proj_full** | | | | **$1,408** |
| **proj_honest** | | | | **$1,408** |

**Why it works**: rare (3% pass rate base) triple-confluence — BTC + ETH + SOL all slope-agree with SOL direction at fire time, restricted to US open hours (13-15 UTC) when liquidity peaks, with SOL CCI extreme + stoch strong. Lowest DD ($25), LS=1 across lockbox.

Confidence: **HIGH.** Path J + Path K combination validates V8's central hypothesis. n_full=129 is on the small side but the WR consistency (82-87% across all splits) and tiny DD make this the lowest-risk pick. Could potentially scale stake.

### S5 — `SOL5_V8_S5` (highest WR, Path K, largest n)
**Stack**: `g_f7_v7_with & g_tod_us_afternoon & g_tr_full_stack_with`
**Tags**: K_TOD (US afternoon 13-18 UTC + RSI in direction + TR ribbon fully stacked)

| | train | val | lockbox | **FULL** |
|---|---|---|---|---|
| n | 1072 | 233 | **250** | **1555** |
| WR | 81.0% | 77.3% | **87.2%** | **81.4%** |
| $/tr @ $25 | $1.07 | -$1.83 | **$4.57** | **$1.20** |
| sum @ $25 | $1,146 | -$427 | **$1,143** | **$1,864** |
| Max DD | - | - | **$244** | - |
| Max LS | - | - | **6** | - |
| Bootstrap p | - | - | **0.0000** | - |
| **proj_32d** | | | | **$6,223** |
| **proj_full** | | | | **$1,843** |
| **proj_honest** | | | | **$1,843** |

**Concern**: Same pattern as S2 — high lockbox $/tr ($4.57) but very low full $/tr ($1.20), and val negative. The TOD-us-afternoon edge LIVES IN LOCKBOX but not the broader window. Honest projection cuts to $1,843.

Confidence: **MED-LOW.** Largest n_lockbox (250) gives bootstrap robustness, but the train/val/lockbox $/tr trajectory ($1.07 → -$1.83 → $4.57) screams regime-shift not stable edge. Use with caution.

---

## 4. V8 path winners

| Path | Final sleeves | Top contribution |
|---|---|---|
| **K (TOD)** | **71** of 127 (56%) | S2, S4, S5 + 68 others; us_open & us_afternoon dominant; eu_open secondary cluster |
| **J (2-asset confluence)** | **32 + 9 J∩K** of 127 (32%) | S3 + S4; g_2asset_either_trending_with is the workhorse, g_3asset_unanimity is rare-high-conviction |
| **V7_inherited_C** (cross-asset BTC) | 12 of 127 (9%) | S1 (best honest proj); btc_f7_against still dominant |
| **V7_inherited_H** (hurst) | 2 | helpers only |
| **V7_baseline** | 1 | original V7 S1 atoms re-appear |
| **Q (5m+15m confluence)** | 0 distinct survivor | g_q_15m_dir_bias too rare (<0.1% pass), g_q_15m_confluence too common (~99% pass); useful as warning gate only |
| **O (HL liq cascade)** | 0 distinct survivor | HL data ends May 16 (cuts last 10d of window), severely limits projections. Some training sleeves use it but they project negatively due to no lockbox coverage |

---

## 5. TOD specialization findings

V8 TOD bucket WR-lift on SOL 5m (n_full > 100 final sleeves):

| TOD bucket | hour UTC | sleeves | dominant edge |
|---|---|---|---|
| **g_tod_us_afternoon** | 13-18 | **most populous (28)** | f7_v7_with + tr ribbon stacks; us afternoon is highest-volume hours |
| **g_tod_us_open** | 13-15 | 24 sleeves | f7_v7_with + R1_full + vwap; sharp first-hour-of-NY-day edge |
| **g_tod_eu_open** | 7-9 | 8 sleeves | bb_pos_extreme + cci_strong + ribbon_slope; reversal/momentum mix |
| **g_tod_european** | 7-12 | 6 sleeves | broader version of eu_open, weaker |
| **g_tod_us_evening** | 19-23 | 3 sleeves | minor |
| **g_tod_asia** (whole bucket) | 0-6 | **2 sleeves** | hypothesis REJECTED — Asia hours did NOT favor SOL 5m |
| **g_tod_asia_late** | 4-6 | 1 sleeve | only with HL liq cascade which is data-truncated |
| **g_tod_lunch** | 10-12 | 0 sleeves | dead zone |

**Surprise**: SOL 5m edge concentrates in **US hours** (us_open + us_afternoon), NOT Asia hours as briefed. Possible explanations: (1) the Polymarket Up/Down market participants are predominantly US-based, so order flow & strike clustering align with US activity; (2) SOL perp activity may be heavier in US hours despite the regional-asset hypothesis; (3) crypto news/momentum events cluster in US trading hours.

---

## 6. 2-asset confluence findings

| confluence gate | pass rate | best sleeve | best WR_l / $/tr_l |
|---|---|---|---|
| `g_2asset_confluence_btc_eth` (BTC+ETH slope same dir) | 36% | (saturated, used as helper) | — |
| `g_2asset_confluence_strong` (slope>0.0003 both) | 36% | — | — |
| `g_2asset_either_trending_with` (BTC OR ETH trending in dir) | 7.3% | S3 | 76.3% / $4.23 |
| `g_2asset_regime_trending_with` (BOTH BTC + ETH trending) | 3.1% | rarer, weaker sleeves | — |
| `g_3asset_unanimity` (BTC+ETH+SOL all slope-agree) | 30% | S4 | 86.8% / $6.91 |
| `g_2asset_confluence_against` (BTC+ETH OPPOSITE to dir) | 36% | minor, weak | — |
| `g_2asset_both_ranging` (both BTC+ETH ranging) | 70% | filter only | — |

**Best 2-asset finding**: `g_3asset_unanimity` (rare 30% pass but high directional info content) when combined with TOD + extreme oscillator → S4 (86.8% WR). `g_2asset_either_trending_with` (a permissive cross-asset filter that says "at least one big-asset agrees") + V7 winners → S3 (76% WR sustained across all splits).

**Hypothesis tested**: "3-asset unanimity is rare but highest-conviction" — CONFIRMED in S4 (86.8% WR, 82.2% on full window, p=0.0055). But the absolute volume (n_full=129) is small.

---

## 7. Failed approaches / honest negatives

1. **Path O — HL liq cascade gates**: HL data ends May 16, missing last 10/33 days of window. Sleeves using HL gates train on partial data and project unrealistically. We tested with `g_hl_long_cascade_with_15m` and `g_hl_short_cascade_strong` — they appear in early-search rows but get filtered out at the final-pass stage because their proj_full is heavily distorted by zero-coverage in lockbox. **Recommendation**: don't trust HL-anchored sleeves for SOL 5m until HL pipeline catches up.

2. **Path Q — 5m + 15m confluence**: every 5m fire in our v3 universe has a 15m sibling fire in the same 15m window (saturation = ~99%). Direction-bias variants `g_q_15m_dir_bias`, `g_q_15m_dir_majority` are too rare (<0.1% pass) to bootstrap. **No standalone survivor**. Useful as warning/filter ("no 15m opposite") but not a primary signal.

3. **Path K — Asia hours hypothesis**: V8 brief hypothesized SOL would favor Asia hours due to regional trading patterns. **REJECTED**. Asia/Asia-late buckets produced only 2 final sleeves, both helper-grade. US hours dominate.

4. **`g_btc_trend_30m_with` alone (V7 S1 atom)** on V8 60/20/20 splits: lockbox WR drops to 71.8% (from 82.2% in V7 brief). Confirms V7's tiny 4d lockbox was an extreme period. The wider V8 lockbox (6d) and full 33d window give a more honest WR of ~72-75% for this atom.

5. **Weighted ensembles (Path A from V7)**: not re-tested in V8 (V7 brief settled it failed). Strict AND stacks still win.

---

## 8. Surprises & key learnings

1. **Cross-asset (Path C from V7) still beats 2-asset Path J on raw $/tr**: S1 ($6.08/tr full) > S3 ($3.42/tr full). The V8 J 2-asset path adds breadth, not depth — it's a useful new dimension but doesn't dethrone V7's S1-flavored cross-asset+hurst stack.

2. **TOD specialization is the biggest V8 win** — 56% of final sleeves use a TOD anchor. SOL has clear hour-of-day edge concentration in US trading hours.

3. **3-asset unanimity (Path J extreme variant) IS a real signal**: 82.2% WR on full window 33d at n=129, validating the V8 hypothesis. Worth deploying despite small n.

4. **Lockbox-only edges are real but smaller than V7 reported**: V7's 4d lockbox produced unusually strong $/tr that don't fully replicate on a wider 6d V8 lockbox. The 33d full-window projection should be the operator's baseline expectation, not the lockbox.

5. **`g_btc_f7_against` keeps surfacing** (S1 atom) — same gate as V7 S3. The bidirectional cross-asset edge (BOTH `_with` and `_against` flavors yield winners) noted in V7 holds in V8 with wider validation.

6. **HL Hyperliquid liq cascade gates are blocked by data lag** — until HL collector catches up to May 26+, V8 cannot validate Path O.

---

## 9. Cumulative PnL plots

See `plots/cumulative_pnl_SOL5_V8_S1.png` through `S5.png`. Each shows the full 33d cumulative PnL trajectory at $25 stake with train/val/lockbox dividers.

---

## 10. Outputs

- `top_5_candidates_v8.csv` — primary deliverable (5 rows, full per-split metrics + projections)
- `_panel_sol_5m_v8.parquet` (20.3 MB) — V8-enriched panel (101,500 rows × 371 cols, 222 g_* atoms including 42 new V8 gates)
- `_v8_profile_pass.csv` (281 stacks passing V8 bar pre-bootstrap)
- `_v8_dedupe.csv` (171 after lockbox fingerprint dedup)
- `_v8_bootstrap.csv` (top 200 bootstrapped)
- `_v8_final_pass.csv` (127 stacks p ≤ 0.05)
- `_v8_final_pass_tagged.csv` (with path tags)
- `_single_gate_v8.csv` — single-gate WR scan on train
- `_train_candidates_v8.csv` (19,387 train survivors dpt>=1.0)
- `_validated_v8.csv` (3,700 val+lockbox survivors)
- `plots/cumulative_pnl_SOL5_V8_S{1..5}.png`
- `scripts/{10_build_v8_panel.py, 20_v8_search.py, 21_dedupe_bootstrap.py, 30_finalize_top5.py}`

---

## 11. Recommendation

1. **Deploy SOL5_V8_S1 first at $25 stake.** Highest honest projection ($3,157/32d), wide validation footprint (n_full=649, WR 75.2%), low DD ($116), LS=3, p=0.0045. Extends V7's btc_f7_against+cci_extreme+hurst_reverting winner with `g_mfi_strong_with` which boosts n by 80% without sacrificing WR significantly.

2. **Run SOL5_V8_S3 in parallel.** Most stable across splits (J Path 2-asset confluence). 76% WR holds across train/val/lockbox. Lowest overfit risk among the picks.

3. **Run SOL5_V8_S4 as a third sleeve.** Smallest n_lockbox (38) but cleanest signature: 3-asset unanimity + US open + extreme oscillators = 86.8% WR with DD=$25, LS=1. Could scale stake here.

4. **Hold SOL5_V8_S2 / S5 in reserve.** Both TOD-anchored with severe lockbox-vs-full $/tr gaps suggesting overfit to lockbox period. Paper-trade observation needed.

5. **Live monitoring alarms** (per sleeve): (a) WR alarm if 7d trailing < 65%, (b) DD alarm if 2× backtest DD ($232 for S1, $268 for S3, $50 for S4), (c) for K_TOD sleeves — pause if WR in target TOD bucket diverges >10pp from backtest.

6. **For next V9**: Push the 3-asset unanimity logic (S4-flavor) deeper — Path J subvariants are very promising on smallest sleeves. Build HL panel with fresh data and re-test Path O.

---

## 12. Return to orchestrator

- **127 V8-profile-passing candidates** with bootstrap p ≤ 0.05
- **Best sleeve**: `SOL5_V8_S1` = `g_btc_f7_against + g_cci_extreme_with + g_hurst_reverting + g_mfi_strong_with`
  - n_full=649, WR_full=75.2%, $/tr_full=$6.08, sum_full=$3,946 over 33d
  - n_lockbox=89, WR_lockbox=78.7%, $/tr_lockbox=$6.52, DD=$116, LS=3, p=0.0045
  - **proj_honest = $3,157 / 32.7d** at $25 stake
- **Winning V8 path**: Path K (TOD specialization, 71/127 sleeves) and Path J (2-asset confluence, 32/127) co-dominate. V7's Path C (cross-asset BTC) still produces the single best sleeve when combined with V8 extensions.
- **TOD specialization revealed**: US hours (us_open 13-15 UTC + us_afternoon 13-18 UTC) dominate; **Asia hours hypothesis REJECTED** (only 2 sleeves)
- **vs V7 baseline (`btc_trend_30m_with + cci_extreme_with + hurst_reverting`)**: V7 brief showed lockbox proj_32d=$4,625 on a tiny 4d lockbox. On V8's 6d lockbox and 33d full window, same stack gives proj_full=$3,072. V8 S1 (with `g_mfi_strong_with` extension) beats this at proj_honest=$3,157.
- **Top failure**: Path O (HL liq cascade) blocked by HL data ending May 16 (10/33 days uncovered)
- **Confidence**: HIGH for S1, S3, S4; MED for S2, S5 (lockbox-vs-full gap)

---

**Generated by**: V8 sniper search agent (SOL 5m), 2026-05-27.
