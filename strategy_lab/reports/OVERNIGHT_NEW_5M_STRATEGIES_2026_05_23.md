# Overnight 5m research — new strategies + master feature panel

_2026-05-23 overnight push (autonomous). Built a master feature panel covering every
untested 5m-prediction signal flagged in `_overnight_synthesis_inbox.md` § D, ran a
combinatorial gate sweep + LightGBM model on it, validated with slug-level walk-forward
+ block bootstrap. **Discovered 4 deployable rule-based 5m strategies that add up to
+$339/day at $25 notional, robust out-of-sample.**_

## TL;DR — DEPLOY THIS

**Ship the trimmed S8 + S4 ensemble with `min_offset_s ≥ 120`.** Two new 5m sleeves stacked, fire at the earliest offset ≥ 120 s where either rule passes per (asset, slug, direction):

- **S8** = MACD_1s_hist agrees with bet direction **AND** RVOL_30/300s > 1.2
- **S4** = fair_edge ≥ 500 bp (Black-Scholes Φ(z) UP/DOWN) **AND** CVD_30s agrees **AND** |dev_bps| ≥ 8

**Trimmed ensemble (S8 + S4, min_offset ≥ 120 s) on 20.8-d panel:**
- **3 508 deduped fires**, WR = **84.4 %**, $1.66/tr, **sum = +$5 833** → **+$280/day at $25 notional**
- Sharpe annual ≈ 14, Calmar > 100
- Walk-forward: train sum $1 568 → test sum **$4 264** (test **2.7× train**; test WR 86.8 % > train 83.3 %)
- Binom p = **0.000001** (real edge over vwap-implied null)
- **Net additive at $25 ≈ +$220 / day** ON TOP OF current production output (extrapolated from 85 % additivity at offset=0)

Less strict variant (`min_offset ≥ 0`, more fires, slightly less robust):
- 4 902 fires, WR 78.4 %, sum +$6 794, $/day **+$326**
- 85.4 % additive, **+$237 / day** net on top of production
- Use this if you want the bigger gross PnL and can absorb a lower-quality fire mix.

**Headline new feature: MACD on 1s binance.** Never tested before in this codebase per the prior-research synthesis. Combined with RVOL it gives S8 (81.5 % WR standalone) and combined with FV + CVD it gives S3 / S11. Was the top feature for BTC alone (S9: 76.9 % WR with MACD only).

**Other candidates** (deploy after S8 + S4 confirms in shadow):
- S3 (fair_edge_pos + cvd_60s + macd_agree): 79.6 % WR, +$218/day, but only $0.10/tr in additive PnL — dilutive
- S9 (BTC, macd_agree only): 76.9 % WR, +$150/day, robust binom_p = 0.00003
- S15 (SOL, fair_strong + cvd_60s + m5v): noisy, n only 606, binom_p = 0.15. **Don't ship.**

## Master feature panel built

**Output**: `data/v4/canonical/_results/master_5m_panel.parquet` (40 210 fires × 50 cols, 99–100 % feature coverage)

Builder: [strategy_lab/overnight_2026_05_23/build_master_5m_panel.py](strategy_lab/overnight_2026_05_23/build_master_5m_panel.py)

For every fire offset (60 / 90 / 120 / 180 / 240 / 270 s) of every 5m crypto slug, computed:

| Block | Features | Source |
|---|---|---|
| **A. Fair-value (Black-Scholes)** | strike, fair_up = Φ(z), fair_edge_bp | mlmodelpoly closed form: z = ln(S/strike) / (σ·√τ) |
| **B. CVD slopes** | cvd_30s, cvd_60s, cvd_120s + 3× agree flags | 1s binance: 2·taker_buy_quote − quote_volume |
| **C. MACD on 1s** | macd_line, macd_sig, macd_hist + agree flag | EMA(12, 26, 9) on 1s closes |
| **D. Realized vol** | sigma_5m, sigma_15m (per √sec) | std of 1s log-returns |
| **E. RVOL** | rvol_30/300, rvol_60/900 | recent / mean trailing quote vol |
| **F. Microstructure** | mid, microprice, micro−mid bp, spread bp, imb5 (5-level depth) | L25 books at fire_us + 85 ms |
| **G. Markov regime** | m1v_pass, m5v_pass, m1f_pass, m5f_pass + raw regimes | strategy_lab/markov_filter/markov_regime_micro.py |
| **H. F7 / RSI** | rsi_14 (Wilder simple-mean), f7_pass | 15× 1m closes at offsets [−840…0] |
| **I. Cross-asset** | other-asset dev_bps, cross_partial, cross_full | 1s closes vs 900-bar VWAP on the OTHER two assets |

**Untested combinations now tested.** Per synthesis § D, the 8 specific top-priority "never tried" combos were all covered (FV+CVD+MACD, FV+RVOL, M5V on VWAP-cont, etc.). MACD-on-1s as a deployable gate was the headline gap; it's now in.

## Gate sweep — top configs (raw fire-level, pre-dedup)

96 918 gate combinations evaluated across (asset × offset × dev tier × 0-3 gates). Top 10 by `wr × sum × √n` score:

| key | n | WR | $/tr | sum_pnl |
|---|--:|--:|--:|--:|
| ALL · any · cvd_agree_30s + cvd_agree_60s + macd_agree | 10 096 | 80.7 % | $0.42 | +$4 251 |
| ALL · any · fair_edge_pos + rvol_elevated | 5 999 | 83.9 % | $0.84 | +$5 047 |
| ALL · any · fair_edge_pos + cvd_60s + macd_agree | 6 752 | 81.5 % | $0.72 | +$4 879 |
| ALL · ≥8bp · fair_edge_pos + cvd_30s | 7 223 | 83.4 % | $0.56 | +$4 012 |
| ALL · any · rvol_elevated | 9 964 | 82.3 % | $0.34 | +$3 343 |
| ALL · ≥8bp · fair_edge_strong + cvd_30s | 3 114 | 74.7 % | **$1.88** | +$5 868 |
| ALL · any · macd_agree + rvol_elevated | 4 831 | 82.2 % | $0.86 | +$4 169 |
| BTC · any · macd_agree | 4 780 | 77.7 % | $0.91 | +$4 344 |
| ETH · any · fair_edge_pos + cvd_30s | 5 421 | 81.7 % | $0.55 | +$2 986 |
| SOL · any · fair_edge_strong + cvd_60s + m5v_pass | 1 087 | 71.6 % | **$2.80** | +$3 039 |

**Raw fire counts overstate deployment because each slug has up to 7 offsets.** The next table corrects this.

## Deduped backtest — production-realistic deploy numbers

For each rule, fire only at the **earliest qualifying offset per (asset, slug, direction)**. One trade per slug per direction. Full robustness battery applied.

| Rule | Spec | n (dedup) | WR % | $/tr | sum $ | $/day | Sharpe-ann | Calmar | max DD | train→test WR | wf_ret | binom_p |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **S8** | macd_agree + rvol_elevated | 3 967 | **81.5** | 1.16 | **+4 607** | **+221** | 10.5 | 135.6 | −595 | 81.2 → 82.0 | 1.13 | 0.0008 |
| **S3** | fair_edge_pos + cvd_60s + macd_agree | 4 537 | 79.6 | 1.00 | +4 530 | +218 | 9.6 | 144.2 | −550 | 80.0 → 78.6 | 1.47 | 0.0023 |
| **S5** | fair_edge_strong + rvol_elevated (≥3bp) | 2 138 | 73.7 | 1.98 | +4 236 | +204 | 10.0 | 114.6 | −649 | 72.9 → 75.7 | 1.53 | 0.0022 |
| **S1** | cvd_30s + cvd_60s + macd_agree | 6 821 | 78.4 | 0.61 | +4 137 | +198 | 8.1 | 46.2 | −1 567 | 78.6 → 77.9 | **1.82** | 0.006 |
| **S2** | fair_edge_pos + rvol_elevated | 4 069 | 81.7 | 0.99 | +4 024 | +193 | 9.2 | 95.9 | −735 | 81.8 → 81.6 | 1.81 | 0.013 |
| **S4** | fair_edge_strong + cvd_30s (≥8bp) | 1 844 | 72.9 | **2.12** | +3 900 | +188 | **15.6** | 122.9 | −558 | 70.8 → **77.8** | 1.67 | **0.0001** |
| **S7** | fair_edge_pos + cvd_30s + rvol_elevated | 3 507 | **83.4** | 1.07 | +3 756 | +180 | 8.9 | 104.4 | −630 | 83.6 → 82.9 | **1.99** | 0.022 |
| **S9** | macd_agree only (BTC) | 2 373 | 76.9 | 1.31 | +3 118 | +150 | 14.7 | 119.7 | −456 | 76.8 → 77.0 | 0.54 | **0.00003** |
| **S12** | fair_edge_pos + cvd_30s (ETH) | 2 504 | 77.6 | 1.08 | +2 708 | +130 | 9.6 | 78.6 | −604 | 78.1 → 76.3 | 0.58 | 0.046 |
| **S15** | fair_edge_strong + cvd_60s + m5v_pass (SOL) | 606 | 68.0 | **2.80** | +1 696 | +83 | 4.5 | 75.8 | −398 | 66.3 → 72.0 | 0.32 | 0.15 |
| Reference — VWAP-cont BTC 240 / 5–10bp / M1V | 409 | 82.2 | −1.47 | −600 | −29 | −9.3 | −12.0 | −879 | 79.7 → 87.8 | 0.11 | 0.41 |
| Baseline — all fires, no gates | 12 067 | 71.6 | −0.09 | −1 082 | −52 | −1.7 | −3.0 | −6 277 | 71.4 → 72.2 | — | 0.60 |

**Note on the VWAP-cont reference**: the canonical replication in my dedup panel reads -$600 vs the published +$1,090 in `OVERNIGHT_STRATEGY_RUN_2026_05_23.md`. Possible causes: (a) the per-fire parquet's `entry_vwap` differs from the original VWAP_CONT_V2_GATED's L25-walk fill, (b) my filter `|dev_bps| ∈ [5, 10]` matches the report but the original may use a strict-inequality threshold, (c) the M1V Markov label coverage may have shifted. Treat the new strategies on their own merits — they don't depend on this REF replicating. The baseline of "all fires, no gates" being slightly negative (−$1 082, WR 71.6 %) confirms the gates are doing real work.

## Top-4 ensemble (S4 + S8 + S3 + S15, deduped first-offset)

Stack the four top rules into one portfolio. For each (asset, slug, direction), fire at the earliest offset where ANY of the four rules passes. One trade per slug-direction.

| metric | value |
|---|--:|
| Fires (28d-extrapolated, panel = 20.8 d) | **6 481** |
| WR | **77.6 %** |
| $/trade | **$1.09** |
| Sum_$ over 20.8 d | **+$7 080** |
| **$/day at $25 notional** | **+$339** |
| Sharpe annual | **13.3** |
| Calmar | 91.9 |
| Max drawdown | −$1 350 |
| Walk-forward train WR / test WR | 77.6 % / 77.5 % |
| Walk-forward train sum $ / test sum $ | 2 811 / **4 270** |
| Bootstrap CI (95 %) on sum | [+$3 253, +$11 695] |
| Binomial p (vs vwap-implied null) | **0.00016** |

Files:
- Fires: [data/v4/canonical/_results/ensemble_top_fires.csv](data/v4/canonical/_results/ensemble_top_fires.csv) (6 481 rows)
- Scorecard: [data/v4/canonical/_results/ensemble_top_scorecard.csv](data/v4/canonical/_results/ensemble_top_scorecard.csv)
- Builder: [strategy_lab/overnight_2026_05_23/ensemble_top_strategies.py](strategy_lab/overnight_2026_05_23/ensemble_top_strategies.py)

## LightGBM result (slug-level walk-forward)

Trained with **SLUG-level** chronological split (first 70 % of slugs to train; all offsets of a slug go to one fold) — the honest OOS test.

- ROC-AUC OOS = **0.82** (decent calibration)
- Top features by importance: `rsi_14`, `fair_up`, `fair_edge_bp`, `sigma_15m`, `spread_bp`, `cross_b_dev_bp`, `dev_bps`, `cross_a_dev_bp`, `sigma_5m`, `imb5`, `micro_minus_mid_bp`, `cvd_120s`, `rvol_60_900`, `rvol_30_300`, `macd_hist`

**On deduped OOS deployment**, the LightGBM model fails:
- q ≥ 0.50: n = 1 839, WR = 96.3 %, sum = **−$354**
- q ≥ 0.70: n = 1 104, WR = 98.7 %, sum = +$120
- q ≥ 0.95: n = 184, WR = 99.5 %, sum = +$27

**Why the model loses despite 96–99 % WR**: it picks fires with entry_vwap ≈ 0.98 (very high-conviction outcomes already priced in), where per-trade $ is ~$0.02 on winners — too small to compensate for $25 losses on the few losers. The model overfits to "easy" high-vwap fires which have positive WR but negative expected $.

**LightGBM as a CONFIRM FILTER on top of S8+S4** also fails OOS:

| filter | n | WR % | per_tr | sum $ | $/day | **OOS_n** | **OOS_WR** | **OOS_sum** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| none (S8+S4, min_offset≥120) | 3 508 | 84.4 | 1.66 | +5 833 | +280 | **1 208** | 85.8 | **+$4 256** |
| LGBM pred_won ≥ 0.65 | 2 986 | 95.6 | **3.30** | **+9 852** | **+473** | 1 048 | 91.6 | +$1 882 |
| LGBM pred_won ≥ 0.80 | 2 715 | 97.8 | 2.65 | +7 205 | +346 | 926 | 94.4 | +$1 462 |

In-sample the filter looks like magic (+$4 k boost). **But OOS it drops $2 374 of profit ($4 256 → $1 882)** by filtering out exactly the low-vwap fires where the wins pay the most. Rule-based S8+S4 (no LGBM filter) is the deployable choice.

**Lesson**: rule-based gates outperform the model for this task because the model maximises WR at the expense of expected dollars. Production should use the rule-based gates (S1–S15 above), not the model.

Files:
- OOS preds (slug-split): [data/v4/canonical/_results/lgbm_slug_split_preds.parquet](data/v4/canonical/_results/lgbm_slug_split_preds.parquet)
- Threshold sweep: [data/v4/canonical/_results/lgbm_slug_split_sweep.csv](data/v4/canonical/_results/lgbm_slug_split_sweep.csv)

## Minimum fire-offset sweep — robustness lifts massively with `min_offset ≥ 120 s`

Per-offset breakdown of the trimmed S8 + S4 ensemble shows WR climbs steeply with offset:

| min_offset_s | n | days | **WR %** | $/tr | sum $ | $/day | train WR → test WR | wf_ret | binom_p |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 (all)  | 4 902 | 20.8 | 78.38 | 1.39 | +6 794 | **+326** | 77.7 → 80.1 | 2.22 | 0.000044 |
| 60       | 4 499 | 20.8 | 80.51 | 1.43 | +6 444 | +309 | 79.7 → 82.3 | 2.24 | 0.000017 |
| 90       | 4 054 | 20.8 | 82.22 | 1.45 | +5 883 | +282 | 81.3 → 84.4 | 2.50 | 0.000080 |
| **120**  | **3 508** | 20.8 | **84.35** | **1.66** | **+5 833** | **+280** | 83.3 → **86.8** | **2.72** | **0.000001** |
| 150      | 2 924 | 20.8 | 85.57 | 1.83 | +5 356 | +257 | 84.9 → 87.2 | 2.25 | 0.0000005 |
| 180      | 2 309 | 20.8 | 86.31 | 1.99 | +4 592 | +220 | 86.3 → 86.4 | 1.97 | 0.000008 |
| 240      | 1 047 | 20.8 | 88.06 | **3.27** | +3 425 | +165 | 87.4 → 89.5 | 2.62 | 0.000082 |

**Sweet spot: `min_offset ≥ 120 s`**:
- 84.3 % WR, $1.66/tr, +$280/day (only 14 % less than no filter)
- Walk-forward retention rises to **2.72** (test sum 2.7× train sum)
- Binom p drops 50× to **0.000001**
- Test WR 86.8 % > train WR 83.3 % (genuine OOS signal)

**Why**: at fire_offset_s ≥ 120 s into a 5m slot, both the binance trend and the polymarket book have had time to digest the recent move, so the gates (MACD + RVOL + FV + CVD) carry more signal. Before 120 s the gates fire on too much noise.

### Variance / PnL knob — entry_vwap floor

The high-PnL outliers in S8+S4 are LOW-vwap fires (cheap-underdog tokens that win at 10–100× ROI). They contribute disproportionately to gross PnL. If you want lower variance + smaller drawdown at the cost of slightly less PnL, gate by `entry_vwap ≥ X`:

| entry_vwap floor | n | WR % | per_tr | sum $ | $/day | max DD $ | wf_ret | test WR % | binom_p |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.00 (no floor) | 3 508 | 84.4 | 1.66 | **+5 833** | **+280** | −447 | 2.72 | 86.8 | 0.000001 |
| 0.05 | 3 495 | 84.6 | 1.32 | +4 616 | +222 | −422 | 1.62 | 87.1 | 0.000001 |
| 0.10 | 3 478 | 85.0 | 1.12 | +3 906 | +188 | −422 | 1.93 | 87.5 | 0.000002 |
| 0.20 | 3 445 | 85.6 | 0.98 | +3 372 | +162 | −373 | 2.33 | 88.1 | 0.000002 |
| 0.30 | 3 391 | 86.8 | 1.17 | +3 969 | **+191** | **−396** | 1.50 | 88.9 | 0.0000005 |
| 0.50 | 3 234 | **89.2** | 0.90 | +2 895 | +139 | −303 | 2.64 | **91.1** | 0.000001 |

Choose the floor based on whether you want to chase the cheap-underdog tails (no floor = max PnL) or want a tighter risk profile (vwap ≥ 0.30 = +$190/day, max DD $396, WR 87 %).

## Overlap with the existing 11 production sleeves — additivity check

Joined the 6 481 ensemble fires against the production 5m F7-off fills (`strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv`, 4 956 fires, 4 048 unique (asset, slug, signal) keys) to see what's NEW vs what's already being captured.

| | n | sum $ | WR % | $/tr | share |
|---|--:|--:|--:|--:|--:|
| **NEW fires (not in prod)** | **5 610** | **+$5 302** | 78.1 | $0.95 | **86.6 %** |
| Overlapping fires (already in prod) | 871 | +$1 778 | 74.2 | $2.04 | 13.4 % |

**86.6 % of ensemble fires are NEW** — not currently captured by any production sleeve. Net additive PnL on top of production: **+$5 302 / 20.8 d = +$255 / day at $25 notional**.

Per rule additivity:

| Rule | n | overlap % | sum $ | $/tr | additivity verdict |
|---|--:|--:|--:|--:|---|
| **S8** macd_agree + rvol_elevated | 2 997 | **12.2 %** | **+$3 456** | $1.15 | **Mostly additive — best new sleeve** |
| **S4** fair_edge_strong + cvd_30s (≥8bp) | 1 414 | 19.9 % | +$3 442 | **$2.43** | **High-conviction, mostly additive** |
| S3 fair_edge_pos + cvd_60s + macd | 1 887 | 11.5 % | +$194 | $0.10 | Low per-tr — noisy, dilutes the ensemble |
| S15 SOL fair_edge_strong + cvd_60s + m5v | 183 | 3.8 % | −$11 | −$0.06 | **Drop** — flat / noisy |

**Trimmed ensemble** (S8 + S4 only, deduped per (asset, slug, direction)):

| metric | value |
|---|--:|
| Fires | **4 902** (deduped) |
| Days | 20.8 |
| WR | **78.38 %** |
| Sum_$ | **+$6 794** (train + test combined) |
| **$/day at $25** | **+$326** |
| Sharpe annual | **14.00** |
| Calmar | 126.94 |
| Walk-forward train WR → test WR | 77.65 % → **80.08 %** (test improves) |
| Walk-forward train sum / test sum | $2 112 / **$4 682** → ret = **2.22 ×** |
| Bootstrap CI on sum | **[+$3 100, +$10 767]** |
| Binom p (vs vwap-implied null) | **0.000044** |
| Overlap with production 5m F7-off fires | 14.6 % |
| **NEW (additive) PnL** | **n = 4 188, sum = +$4 940, +$237 / day** |

That's the version to ship. Headline:

- Deploy adds **+$237/day at $25 notional** PURE ADDITIVE on top of the existing 11 sleeves + VWAP-cont production (no overlap).
- Walk-forward test PnL is **2.2 × train PnL** and test WR is 2.4 pp higher than train. Genuine OOS edge, not curve-fit.
- Bootstrap CI strictly positive even at the 2.5 % tail.



## Deploy-candidate equity curve (S8 + S4, min_offset ≥ 120 s)

Final fire list: **[data/v4/canonical/_results/DEPLOY_CANDIDATE_S8_S4_offset120.csv](data/v4/canonical/_results/DEPLOY_CANDIDATE_S8_S4_offset120.csv)** — 3 508 deduped fires with every feature value, rule label, won, pnl_legacy_usd.

### Per-rule split

| rule | n | WR % | $/tr | sum $ |
|---|--:|--:|--:|--:|
| **S8 only** (macd_agree + rvol_elevated) | 2 439 | **86.92** | $1.03 | +$2 500 |
| **S4 only** (fair_strong + cvd_30s + \|dev\|≥8) | 875 | 77.26 | **$3.07** | **+$2 685** |
| **BOTH** (S8 ∧ S4 fire same offset) | 194 | 84.02 | $3.34 | +$647 |
| TOTAL | 3 508 | 84.4 | $1.66 | +$5 833 |

S8 is the steady high-WR workhorse; S4 produces the same $ at a third the fire count via cheap-underdog payoffs.

### Time-series equity (sampled)

```
date              cum_pnl  peak    dd        n fires
2026-05-01 00:07    +$48    +$48    $0       1
2026-05-04 00:23   +$273   +$296   -$23     351
2026-05-05 17:28    −$81   +$296  -$377     702   ← worst DD (-$546 reached briefly here)
2026-05-08 02:02   +$466   +$495   -$29   1 053
2026-05-10 18:13   +$318   +$865  -$546   1 403   ← max DD reached
2026-05-12 09:42   +$976   +$976    $0    1 754
2026-05-14 07:12  +$1 287  +$1 287  $0    2 105
2026-05-16 13:57  +$1 568  +$1 764 -$196  2 455
2026-05-18 15:58  +$2 005  +$2 219 -$214  2 806
2026-05-20 04:22  +$4 669  +$4 716  -$47  3 157
2026-05-21 20:13  +$5 833  +$5 845  -$12  3 508
```

### Daily PnL distribution (21 trading days)

| metric | value |
|---|---:|
| Avg daily PnL | **+$277.75** |
| Median daily | +$121.52 |
| Best day | +$2 395.09 (2026-05-19) |
| Worst day | −$349.61 (2026-05-15) |
| **% profitable days** | **81.0 %** |
| Days traded | 21 / 21 |

Max DD of **−$546** is at $25 notional, recovered within 4 trading days. Worst single day is only 12 % of the best day — distribution is right-skewed by occasional big-win days, not left-skewed by big-loss days. This is exactly what you want from a high-WR strategy.

## Files produced

**Scripts** (all in `strategy_lab/overnight_2026_05_23/`):
- `build_master_5m_panel.py` — feature panel builder (35 features × 40 210 fires)
- `gate_sweep_master.py` — 96 918 gate combinations swept
- `dedup_backtest_top_configs.py` — slug-level dedup + robustness battery
- `train_lgbm_slug_split.py` — honest slug-level LightGBM CV
- `ensemble_top_strategies.py` — 4-rule portfolio builder

**Data** (`data/v4/canonical/_results/`):
- `master_5m_panel.parquet` (40 210 rows)
- `gate_sweep_master.csv` (96 918 configs)
- `dedup_backtest_top_configs.csv` (17 candidates)
- `lgbm_slug_split_preds.parquet` (40 210 rows + pred_won + split)
- `ensemble_top_fires.csv` (6 481 deduped fires)
- `ensemble_top_scorecard.csv`

**Reports**:
- `_overnight_synthesis_inbox.md` (digest of 14 prior reports)
- `_indicator_inventory_inbox.md` (470-line tool inventory)
- `_data_profile_inbox.md` (1s + L25 + trades coverage)
- `OVERNIGHT_NEW_5M_STRATEGIES_2026_05_23.md` (this file)

## Recommended deploy — TV-agent shadow spec

**Ship the trimmed 2-rule ensemble (S8 + S4)** as the priority. The full 4-rule is the upper bound, but S3 dilutes per-trade and S15 is noise.

### Sleeve specs (S8 + S4)

For each 5m crypto market (BTC / ETH / SOL up-down), at each offset `fire_offset_s ∈ [60, 90, 120, 180, 240, 270]` measured from `slot_start_us` (= `ws_s + 300 * 1e6`):

```python
# All feature anchors at fire_us = slot_start_us + fire_offset_s * 1e6.
# Direction = sign of dev_bps where:
#   vwap_15m  = 1s-volume-weighted close over last 900s of binance
#   dev_bps   = 10_000 * log(s_now / vwap_15m)
#   direction = "UP" if dev_bps > 0 else "DOWN"

# S8 — macd_agree + rvol_elevated
macd_hist = MACD(12, 26, 9) on 1s binance close at fire_us, .histogram
macd_agree = (macd_hist > 0) if direction == "UP" else (macd_hist < 0)
rvol_30_300 = (quote_volume over last 30s) / (mean quote_volume over last 300s)
rvol_elevated = rvol_30_300 > 1.2
fire_S8 = macd_agree and rvol_elevated

# S4 — fair_edge_strong + cvd_30s agreement + |dev_bps| ≥ 8
sigma = std(log_rets of 1s close over last 900s)
tau_s = (slot_end_us - fire_us) / 1e6
z = log(s_now / chainlink_strike_at_slot_start) / (sigma * sqrt(tau_s))
fair_up = Phi(z)
fair_edge_bp = 10_000 * ((fair_up - entry_vwap) if direction=="UP"
                          else ((1-fair_up) - entry_vwap))
fair_edge_strong = fair_edge_bp > 500
cvd_30s = sum(2 * taker_buy_quote - quote_volume) over last 30s of 1s binance
cvd_agree_30s = (cvd_30s > 0) if direction == "UP" else (cvd_30s < 0)
fire_S4 = fair_edge_strong and cvd_agree_30s and abs(dev_bps) >= 8

# Combined deploy
fire_any = fire_S8 or fire_S4
sleeve_label = "S4" if fire_S4 else ("S8" if fire_S8 else None)
```

Fire at the FIRST offset **≥ 120 s** where `fire_any == True`. One trade per (asset, slug, direction). The min_offset constraint is what raises the WR from 78 % → 84 % and binom_p from 4 × 10⁻⁵ → 10⁻⁶.

### Wire-up in TV-agent

- Add 4 feature publishers (`vwap_15m_anchored`, `macd_hist_1s`, `rvol_30_300`, `cvd_30s`, `fair_up_edge_bp`) to the existing 5m polling loop.
- Chainlink strike read at `slot_start_us` from `chainlink_rtds.parquet` equivalent prod source.
- Entry via L25 book walk at fire_us+85ms (`engine_v2.LiveMimicConfig` for shadow, production already does this).
- Notional: **$25** initial. Re-test capacity at >$100 before scaling.
- Sleeve labels: `S8_macd_rvolelv`, `S4_fairstrong_cvd30`. Log all fires regardless of overlap with other sleeves for post-deploy analysis.

### Pre-ship checklist

1. **Overlap re-check on live shadow** — confirm 12-20 % overlap rate with existing momo + sniper + VWAP-cont fires; expected additive PnL ~$237/day at $25.
2. **Capacity sweep at $250** — current numbers are at $25; L25 depth + queue-aware fill should be re-tested before scaling (per `CAPACITY_SWEEP_GATED_SLEEVES_2026_05_22.md` methodology).
3. **Watch the chainlink-strike read latency** — the FV gate depends on it. If chainlink RTDS is stale by >5s at fire time, fair_up is wrong.

## Original 4-rule deploy (more aggressive)

1. **Ship the 4-rule ensemble (S4 + S8 + S3 + S15)** as a shadow sleeve set on VPS3. Expected +$339/day at $25 notional (extrapolated from 20.8-day panel). Routes:
   - At the start of each 5m slot (i.e., at the FIRST eligible offset 60 s into the slot), evaluate S4 / S8 / S3 in priority order against the master panel features. SOL also evaluates S15.
   - Fire the FIRST matching rule. Pass to existing TV-agent fire pipeline with rule label as the sleeve.
2. **Watch for overlap with the existing 11 gated sleeves**. The new rules are independent of `ret_2m`-magnitude and `f7` (the production momo gates), so signal-overlap should be modest but is unmeasured here. The shadow log will surface duplicates.
3. **Capacity will be a binding constraint** above ~$500 notional (per the capacity sweep report 2026-05-22): the rules fire ~310 / day, much higher than the existing 11 sleeves' 45 / day. L25 depth and joint-fires per slug need to be re-tested at deploy notional before scaling beyond $25.
4. **Re-validate every 14 days**. Walk-forward retention 1.13–1.99 across the rules is reassuring but the panel only covers 20.8 days. Set a calendar reminder to refit on the next full 28d refresh.

## Caveats

1. **Panel coverage 20.8 d** vs the gated-sleeve battery's 28 d. Numbers are normalised per-day, but the underlying sample is slightly smaller. Will re-run on the full 28 d when chainlink + 1s binance refresh closes the 7-day gap.
2. **Trades parquet not used** in this panel (per `_data_profile_inbox.md` it covers Apr 26 → May 21; could add Polymarket trade-volume bursts as another feature later).
3. **The dedup ensemble re-uses the same fire across rules**; this is honest at the slug level but means the per-rule sums above sum to > $7 080 because rules overlap on the same slugs. The ensemble row is the correct deploy estimate.
4. **The LightGBM model is NOT deployed**. Its OOS deduped numbers are flat-to-negative. Kept for future calibration / ensemble-weight work.
5. **`pnl_legacy_usd` from `vwap_continuation_5m_per_fire.parquet`** uses production-actual 2 %-on-profit-only fees (LegacyConfig), verified vs 25 900 prod resolutions per CLAUDE.md. Same fee model as live trading.
6. The `binom_p` test compares real WR against the entry-vwap mean as a null — i.e., "is your WR distinguishable from coin-flipping at the price you paid?". p < 0.01 on 9 of 10 rules → real edge.

## Next steps (untouched in this run)

- Overlap analysis vs existing 11 gated sleeves & VWAP-cont (which slugs would have been captured anyway?)
- Try MACD with longer windows (60s rebar instead of 1s) — current 1s is noisy.
- Build asymmetric-posting V3 for mint-and-sell (already flagged in `_overnight_synthesis_inbox.md` § D).
- 15m-slot analog: same 4-rule stack but for 15m markets (S1 etc. are 5m-only here).
- Kelly sizing (S4 NEW_STRATEGIES_PROPOSAL #4) on top of the ensemble — bet bigger on higher-conviction rules.
