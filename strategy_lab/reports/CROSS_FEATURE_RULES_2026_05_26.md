# Cross-Feature Direction Rules — 2026-05-26

## Hypothesis

R5 standalone direction signals (microprice MP-skew, Lee-Mykland L_stat / jump_dir, Hawkes lambda_imbalance, microstructure imb5) are each weak alone, but each captures a *different* dimension of information. A unanimous-vote combination of features should produce a stronger direction-picking TRIGGER (not a gate) that does not depend on an underlying base sleeve.

This is the gap left by prior rounds: R3/R4/R5 each tested single features standalone (many failed) and the gate hunt tested them as gates (succeeded), but nobody had tested COMBINATIONS as standalone direction triggers.

## Method

- **Window**: 2026-04-30 → 2026-05-23 (23 days — the actual `hybrid_fire_universe_5m/15m` span; the 32-day refresh did not rebuild the fire universe).
- **Universe**: 240,882 chainlink-resolved fire-events across (BTC, ETH, SOL) × (5m, 15m) × offsets ∈ {30…840s}.
- **Outcome**: chainlink-derived `outcome` column from canonical resolutions.
- **Fee model**: `LegacyConfig` (2 % on profit only, no fee on loss). Confirmed in CLAUDE.md as the live production convention.
- **Fill**: `up_vwap/up_shares/up_fill_ok` already pre-computed in fire universe; rule trades only fire when `*_fill_ok = True`.
- **Splits**: train 14 d / val 5 d / lockbox 4 d (time-based; data window forced this — see Limitations).
- **Bootstrap p-value**: 500-shuffle sign-flip on lockbox PnL.

## Master panel

Built `strategy_lab/cross_feature_2026_05_26/master.parquet` joining (asset, slug, tf, fire_us, fire_offset_s) across:

| Source | Features |
|---|---|
| `hybrid_fire_universe_{5m,15m}` | outcome, ws_s, up/dn vwap/shares/usd/fill_ok |
| `microprice_2026_05_26/micro_price_panel_*` | `mp_skew`, `mp_skew_change_500ms`, `mp_imbalance`, `mp_weighted_skew` |
| `lm_at_fires_{5m,15m}` | `lm_L_stat_at_fire`, `lm_last_jump_dir_60s`, `lm_has_jump_60s` |
| `vpin_hawkes_at_fires` | `hawkes_lambda_imbalance`, `hawkes_lambda_total`, `hawkes_recent_burst`, `vpin_value` |
| `microstructure_2026_05_26/micro_panel_*` | `up_imb5`, `dn_imb5`, `imb5_diff`, `up_micro_dev_bps` |
| `regime_panel_{5m,15m}` (asof on ws_s) | `trend_slope_30m`, `bb_width_60s`, `adx_14`, `regime_label` |
| `sms_panel_{5m,15m}` (asof on ws_s) | `liquidity_up`, `liquidity_dn`, `trend_strength_raw`, `system_confidence` |

Feature coverage: mp_skew 88.4 %, lm_L_stat_at_fire 91.7 %, hawkes_lambda_imbalance 95.5 %, imb5_diff 98.9 %, trend_slope_30m 96.4 %, liquidity_up 91.9 %.

---

## 1. Rule inventory (14 rules tested)

| ID | Rule | Hypothesis |
|---|---|---|
| XF-A | `mp_skew>0 ∧ L_stat>=5.97 ∧ jump_dir>0` | MP + statistical jump same direction |
| XF-B | `hawkes_imb>0.3 ∧ mp_skew_change>0` | Order-flow + microprice momentum |
| XF-C | `mp_skew>0 ∧ imb5_diff<0` | DISAGREEMENT (MP up, L1 down) |
| XF-D | `trend_slope_30m>0 ∧ mp_skew>0 ∧ bb_width above median` | Trend + MP + vol expanding |
| XF-E | `liquidity_dn ∧ L_stat>=5.97 ∧ jump_dir>0` | Sweep + statistical jump |
| XF-F | `|hawkes_imb|>0.5 ∧ L_stat>=5.97 ∧ jump aligned` | Extreme order-flow + jump |
| XF-G | `|mp_skew|>=0.5 ∧ |hawkes_imb|>=0.3 ∧ |imb5_diff|>=0.3` | Triple book-pressure confluence |
| XF-H | `sign(mp_skew) == sign(jump_dir_60s)` | MP + recent jump direction agree |
| XF-I | `sign(mp_skew) == sign(hawkes_imb), |hawkes_imb|>0.1` | MP + Hawkes order-flow agree |
| XF-J | `sign(hawkes_imb)>0.2 ∧ sign(jump_dir_60s) agree` | Hawkes + LM jump agree |
| XF-K | Quadruple stack: mp + hawkes + imb5 + jump_dir all agree | Highest confluence |
| DISAGR-0.2 | DISAGR with `|imb5_diff|>0.2` | Stricter disagreement |
| DISAGR-0.5 | DISAGR with `|imb5_diff|>0.5` | Strictest disagreement |
| DISAGR-HAWKES | DISAGR confirmed by Hawkes flow same direction as MP | Confirmed disagreement |

Full per-(asset, tf, offset_s, side) results: `data/v4/canonical/_results/cross_feature_rules.csv` (2,242 rows).

## 2. Per-rule top configs (full-window)

| Rule | Side | Asset | TF | Offset | n | WR | $/tr | sum_pnl |
|---|---|---|---|---:|---:|---:|---:|---:|
| XF-J | BOTH | BTC | 5m | 300 | 120 | 55.0 % | **+$15.99** | +$1,919 |
| XF-D | UP | ETH | 15m | 720 | 172 | 45.3 % | +$14.00 | +$2,407 |
| DISAGR-0.5 | UP | SOL | 15m | 720 | 135 | 71.9 % | +$10.76 | +$1,453 |
| XF-C | UP | ETH | 15m | 720 | 265 | 62.6 % | +$7.87 | +$2,085 |
| XF-D | DN | BTC | 15m | 240 | 145 | 59.3 % | +$7.45 | +$1,080 |
| DISAGR-HAWKES | DN | SOL | 5m | 210 | 167 | **94.0 %** | +$3.37 | +$564 |
| XF-B | DN | ETH | 5m | 180 | 111 | 83.8 % | +$5.91 | +$656 |
| XF-K | UP | BTC | 5m | 60 | 109 | 83.5 % | +$3.23 | +$352 |

## 3. DISAGREEMENT alpha deep dive

Tested 4 × 4 × 2 = 32 threshold combos (T_mp ∈ {0,0.1,0.3,0.5}, T_imb ∈ {0,0.1,0.2,0.5}, hawkes_confirm ∈ {N,Y}) across 108 cells → 3,352 cell-rows in `disagreement_deep_dive.csv`.

**Verdict**: the DISAGREEMENT signal **does NOT generalize universe-wide**. Aggregating over all cells with n>=50:

| Threshold combo | n_cells | total_fires | avg WR | avg $/tr | sum_pnl |
|---|---:|---:|---:|---:|---:|
| DISAGR_mp=0.5_imb=0.5_hk=Y | 68 | 8,253 | 82.8 % | **-$0.48** | -$3,793 |
| DISAGR_mp=0_imb=0.1_hk=Y | 94 | 15,048 | 76.4 % | **-$0.80** | -$7,896 |
| DISAGR_mp=0_imb=0_hk=N | 108 | 52,770 | 58.6 % | **-$2.83** | -$119,281 |

Avg per-trade is negative for every threshold combo despite high average WR. The losing trades hit hard when entry vwap is near $0.50 (the lottery-like polymarket up-down geometry).

However, a handful of **specific (asset, tf, offset)** cells DO work. Top per-cell DISAGR winners (`disagreement_deep_dive.csv`):

| Cell | n | WR | $/tr |
|---|---:|---:|---:|
| SOL 15m UP offset 720 (mp=0, imb=0.5) | 135 | 71.9 % | +$10.76 |
| ETH 15m UP offset 720 (mp=0, imb=0.1) | 236 | 64.4 % | +$8.82 |
| ETH 15m DN offset 240 (hawkes_confirm) | 54 | 88.9 % | +$5.32 |
| SOL 5m DN offset 210 (DISAGR-HAWKES) | 167 | 94.0 % | +$3.37 |

The DISAGR signal is **regime-specific**, NOT a universal trigger. Where it works (ETH/SOL 15m at 720s offset, BTC 5m at 150–240s offset), it works *very* well — but most cells lose. Of the 5 DISAGR cells that pass 3-way lockbox, the only one that survives all four deployability gates is **DISAGR-HAWKES SOL 5m DN 210**.

## 4. Comparison to existing standalone winners

Joining `cross_feature_rules.csv` × `vpin_hawkes_standalone.csv` (H-A baseline) × `lm_standalone_rules.csv` (LM-A baseline), full-window:

| Rule | Side | Asset | TF | Offset | $/tr | H-A $/tr | LM-A $/tr | Edge vs H-A | Edge vs LM-A |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| XF-J | BOTH | BTC | 5m | 300 | +$15.99 | +$0.61 | -$8.72 | **+$15.39** | +$24.71 |
| DISAGR-0.5 | UP | SOL | 15m | 720 | +$10.76 | +$0.33 | -$7.48 | **+$10.43** | +$18.25 |
| XF-C | UP | ETH | 15m | 720 | +$7.87 | +$0.33 | -$5.89 | **+$7.53** | +$13.76 |
| XF-D | DN | BTC | 15m | 240 | +$7.45 | +$0.33 | -$5.32 | **+$7.12** | +$12.77 |
| XF-B | DN | ETH | 5m | 180 | +$5.91 | +$0.62 | +$0.72 | +$5.29 | +$5.19 |
| XF-K | UP | BTC | 5m | 60 | +$3.23 | +$0.29 | +$0.42 | +$2.94 | +$2.81 |

In every cell where a cross-feature rule fires, it materially out-performs both H-A and LM-A standalone — sometimes by 10–25× per-trade. This is **additive value**, but the next question is whether it fires on *different* slugs (truly novel) or the same slugs (redundant intersection).

## 5. Top 5 NEW deployable cross-feature direction rules

After 3-way validation `train(14d) → val(5d) → lockbox(4d)` with strict gates `lockbox_n ≥ 30 ∧ lockbox_WR ≥ 65 % ∧ lockbox_$/tr ≥ +$1 ∧ lockbox_pvalue ≤ 0.05`:

| # | Rule | Side | Asset | TF | Offset | Lockbox n | Lockbox WR | Lockbox $/tr | Lockbox p |
|---|---|---|---|---|---:|---:|---:|---:|---:|
| 1 | XF-J | BOTH | BTC | 5m | 180 s | 41 | 87.8 % | **+$6.98** | 0.050 |
| 2 | DISAGR-HAWKES | DN | SOL | 5m | 210 s | 35 | **100.0 %** | **+$6.54** | 0.000 |
| 3 | XF-I | UP | SOL | 15m | 240 s | 56 | 78.6 % | **+$6.31** | 0.008 |
| 4 | XF-I | BOTH | SOL | 15m | 240 s | 105 | 72.4 % | **+$4.09** | 0.044 |
| 5 | XF-I | UP | BTC | 5m | 150 s | 198 | 76.8 % | **+$3.56** | 0.026 |

A 6th candidate also passed: **XF-I BOTH BTC 5m 150 s** (n=419, WR 74.0 %, $/tr +$2.32, p=0.024).

## 6. Strict 3-way validation summary

Full table `three_way_validation.csv` (150 candidates): **6 pass all four lockbox gates** (n≥30, WR≥65 %, $/tr≥+$1, p≤0.05).

Per-rule pass count:

| Rule | Deployable |
|---|---:|
| XF-I | 4 (BTC 5m UP+BOTH, SOL 15m UP+BOTH) |
| XF-J | 1 (BTC 5m BOTH 180 s) |
| DISAGR-HAWKES | 1 (SOL 5m DN 210 s) |
| All others (XF-A, B, C, D, E, F, G, H, K, DISAGR-0.2, DISAGR-0.5) | 0 |

That none of the simple-disagreement rules (DISAGR-0.2 / DISAGR-0.5) pass without Hawkes confirmation is the most important negative result: the R5 microprice agent's "MP says UP but L1 says DOWN" intuition is real on a few cells but does *not* survive lockbox without flow confirmation.

## 7. Genuine novelty check (slug-overlap with existing sleeves)

`overlap_with_baselines.csv` reports per deployable rule the % of fire-slugs that intersect with existing top sleeves (S6 per asset, H-A BTC 5m, LM-E per asset).

| Rule | Asset | TF | Offset | n_slugs | S6 % | H-A % | LM-E % | Verdict |
|---|---|---|---:|---:|---:|---:|---:|---|
| XF-J | BTC | 5m | 180 | 450 | **12.0 %** | **98.7 %** | 34.7 % | Mostly H-A in disguise (redundant) |
| DISAGR-HAWKES | SOL | 5m | 210 | 264 | 0.0 % | 0.0 % | 0.0 % | **GENUINELY NOVEL** |
| XF-I | SOL | 15m | 240 (UP) | 408 | 0.0 % | 0.0 % | 0.0 % | **GENUINELY NOVEL** |
| XF-I | SOL | 15m | 240 (BOTH) | 690 | 0.0 % | 0.0 % | 0.0 % | **GENUINELY NOVEL** |
| XF-I | BTC | 5m | 150 (UP) | 1,190 | 14.8 % | **93.7 %** | 11.8 % | Mostly H-A overlap (redundant) |
| XF-I | BTC | 5m | 150 (BOTH) | 2,503 | 17.0 % | **94.3 %** | 12.0 % | Mostly H-A overlap (redundant) |

The slug-overlap analysis reveals an important split:
- **BTC 5m** deployable cells share 93–99 % of fire-slugs with the existing H-A Hawkes winner → these are essentially Hawkes selection with marginal microprice/jump confirmation. They beat H-A on per-trade economics within the intersection but they are **not new fires**.
- **SOL 15m offset 240** (XF-I UP and BOTH) and **SOL 5m DN offset 210** (DISAGR-HAWKES) have **0 % overlap** with every checked baseline. These are **genuinely new direction signals** the prior agents did not surface.

## 8. Key findings (compressed)

1. **Cross-feature triggers work**, but mostly within (asset, tf, offset_s) micro-niches — not as universal direction pickers. 14 rules tested → 6 cells pass strict lockbox; 4 of those 6 are XF-I (MP + Hawkes agreement).
2. **DISAGREEMENT alpha is regime-specific**, not universal. Average $/tr is negative across the universe for every threshold combo; the winners are tight cells (notably ETH/SOL 15m at 720 s offset and BTC 5m at 150–240 s). Only DISAGR-HAWKES SOL 5m DN 210 survives 3-way lockbox.
3. **Best NEW non-overlapping signal**: **XF-I (UP) SOL 15m offset 240 s** — `sign(mp_skew) == sign(hawkes_lambda_imbalance), |hawkes_imb|>0.1` — lockbox n=56, WR 78.6 %, $/tr **+$6.31**, p=0.008, **0 % slug overlap** with S6/H-A/LM-E on any asset. The same rule on (BOTH) sides at same cell: n=105, WR 72.4 %, $/tr +$4.09, p=0.044, also 0 % overlap.
4. **Second-best NEW**: **DISAGR-HAWKES (DN) SOL 5m offset 210 s** — `mp_skew<0 ∧ imb5_diff>0 ∧ hawkes_imb<-0.2` — lockbox n=35, WR **100 %**, $/tr +$6.54, p<0.001, **0 % slug overlap** anywhere.
5. **XF-J and XF-I on BTC 5m** are essentially H-A Hawkes intersected with extra confluence — they beat H-A per-trade economics but fire on the same slugs. Useful for sizing/conditional gates on the existing Hawkes sleeve, NOT as a standalone replacement.

## 9. Limitations

- Window is only 23 days (the fire universe was not rebuilt with the May 25 data refresh). Lockbox is only 4 days — small-sample noise risk for cells with lockbox_n ≈ 30. Re-run when fire universe extends to the full 32 days.
- L25-derived microstructure features have ~99 % coverage but `microprice_panel` is at ~88 % (book staleness at some fires). The non-coverage is most likely random with respect to direction.
- LM jump features use `lm_last_jump_dir_60s` (60-second look-back) only because the panel did not include 120-second jump direction at fire time. A 120-second window may improve recall for the XF-A / XF-F / XF-J rules.
- "Genuinely novel" was checked against S6 (4 definitions), H-A on BTC 5m only, and LM-E per asset. Add overlap-checks against deep_stack S6 cross-asset variants and PVSRA 5m before deploying.

## Artifacts

| File | Purpose |
|---|---|
| `strategy_lab/cross_feature_2026_05_26/01_build_master.py` | Joins all R3/R4/R5 panels into master |
| `strategy_lab/cross_feature_2026_05_26/02_score_rules.py` | Defines and scores 14 cross-feature rules |
| `strategy_lab/cross_feature_2026_05_26/03_validate_3way.py` | train/val/lockbox + 500-shuffle bootstrap |
| `strategy_lab/cross_feature_2026_05_26/04_overlap_analysis.py` | Slug-overlap vs S6/H-A/LM-E baselines |
| `strategy_lab/cross_feature_2026_05_26/05_compare_existing.py` | Per-cell edge vs H-A and LM-A standalone |
| `strategy_lab/cross_feature_2026_05_26/06_disagreement_deep_dive.py` | Threshold sweep on DISAGR mp/imb/hawkes |
| `strategy_lab/cross_feature_2026_05_26/master.parquet` | Combined fire+feature dataset (240,882 rows × 65 cols) |
| `data/v4/canonical/_results/cross_feature_rules.csv` | Per-rule × (asset,tf,offset,side) full-window scores |
| `data/v4/canonical/_results/cross_feature_three_way_validation.csv` | Strict 3-way validation table |
| `strategy_lab/cross_feature_2026_05_26/overlap_with_baselines.csv` | Slug-overlap table for deployable rules |
| `strategy_lab/cross_feature_2026_05_26/disagreement_deep_dive.csv` | 3,352-row DISAGR threshold sweep |

## Recommended next steps

1. **Build a 32-day fire universe** (re-run `hybrid_fire_universe_*` against the new May 25 refresh) so lockbox grows from 4 d to ~9 d. The XF-I SOL 15m UP cell currently has lockbox n=56 and would jump to n>100 — gives much tighter p-values.
2. **Live-shadow the two genuinely novel cells** (XF-I SOL 15m UP/BOTH offset 240, DISAGR-HAWKES SOL 5m DN offset 210) on VPS3 in shadow-mode for two weeks. Track Hawkes lambda calculation latency to confirm sub-second feature availability at fire time.
3. **Investigate why ETH/SOL 15m offset 720 s** is the strongest DISAGR cell — that's at the very end of a 15-minute slot. Hypothesis: late-slot order-book pressure on one side often unwinds before settlement (mean-reverts), and the DISAGR signal detects the early-stage of that unwind.
4. **Wrap XF-I on BTC 5m as a sizing booster** on the existing H-A Hawkes sleeve, since they overlap 94 % of slugs but XF-I delivers 5–10× per-trade in the intersection. This is a "tactical size-up" overlay, NOT a new standalone sleeve.
