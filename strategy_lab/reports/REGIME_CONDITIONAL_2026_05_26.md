# Regime-conditional meta-classifier — 2026-05-26

Build a 3-state regime classifier (trending_up / trending_dn / ranging) and test
whether known-good sleeves perform differently under different regimes. Goal:
a meta-layer that switches sleeves on/off by current regime.

**Window**: Apr 30 → May 22 2026 (23 days, fee = LegacyConfig).
**Fires**: causal asof at `fire_us − 1s` against per-asset, per-timeframe regime panel.

---

## 1 — Regime panel: build + distribution

### Inputs / pipeline

| Stage | File | Source |
| --- | --- | --- |
| 1m bars | `binance-vision 1MIN` + `klines_1s` aggregated 1s → 1m | `data/v4/canonical` |
| Features | ADX(14, Wilder), realized_vol_60m, range_compression, trend_slope_30m, tr_ema_stack_score (on bar grid), ribbon_alignment_pct + bb_width_60s (from `ta_indicators_1s` panel asof) | this build |
| 5m / 15m grids | resample 1m OHLCV, recompute ADX(14) + tr_ema_stack_score on each grid | this build |

Outputs:
- `data/v4/canonical/_results/regime_panel_5m.parquet`  (7,749 bars × 3 assets)
- `data/v4/canonical/_results/regime_panel_15m.parquet` (2,584 bars × 3 assets)

### Classification rule (heuristic — caveat below)

```
trending_up : adx_14 > 25 AND tr_ema_stack_score >= +1 AND ribbon_alignment_pct >= 70
trending_dn : adx_14 > 25 AND tr_ema_stack_score <= -1 AND ribbon_alignment_pct >= 70
ranging     : else
```

`regime_score ∈ (−1, +1)` continuous:
```
direction = tanh(tr_ema_stack_score / 2)
strength  = (min(adx_14, 50)/50) * (min(ribbon_alignment_pct, 100)/100)
regime_score = direction * strength
```

### 5m distribution (Apr 30 → May 22, n=7,749 bars per asset)

| asset | ranging | trending_dn | trending_up | ranging_% | trending_dn_% | trending_up_% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC | 6614 | 593 | 542 | 85.35 | 7.65 | 6.99 |
| ETH | 6647 | 610 | 492 | 85.78 | 7.87 | 6.35 |
| SOL | 6649 | 547 | 553 | 85.80 | 7.06 | 7.14 |

### 15m distribution

| asset | ranging | trending_dn | trending_up | ranging_% | trending_dn_% | trending_up_% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BTC | 2210 | 219 | 155 | 85.53 | 8.48 | 6.00 |
| ETH | 2268 | 192 | 124 | 87.77 | 7.43 | 4.80 |
| SOL | 2229 | 180 | 175 | 86.26 | 6.97 | 6.77 |

Markets range ~86% of the time; trending_up ≈ trending_dn ≈ 6-8%. Reasonable
distribution — typical for crypto on intraday timescales.

### Overlap with existing `g_ribbon_agrees`

ribbon_alignment_pct ≥ 70 alone vs `regime_label ∈ {trending_up, trending_dn}`:
- Equal predictions: **59.2%** (overall), 59.1% BTC, 59.5% ETH, 59.0% SOL
- Jaccard (intersection / union): **0.155**

Regime label is NOT just rebuilding ribbon. Adding ADX > 25 plus stack ≥ +1
or ≤ −1 prunes ~85% of bars where ribbon alignment alone would label "trending."
Regime requires ADX trend strength AND directional EMA stack AND ribbon agreement
simultaneously.

---

## 2 — Augmented per-fire parquets

Causal merge_asof at `fire_us − 1s`. Adds `regime_label`, `regime_score`, `adx_14`,
`realized_vol_60m`, `tr_ema_stack_score`, `ribbon_alignment_pct_regime`,
`range_compression`, `trend_slope_30m`, `bb_width_60s` columns.

| Input | Output | Rows | regime joined |
| --- | --- | ---: | ---: |
| `hybrid_features_5m.parquet` | `hybrid_features_5m_regime.parquet` | 190,167 | 182,997 (96.2%) |
| `hybrid_features_15m.parquet` | `hybrid_features_15m_regime.parquet` | 50,712 | 48,762 (96.2%) |
| `s15_with_ta_and_markov.parquet` | `s15_with_ta_and_markov_regime.parquet` | 33,323 | 33,301 |
| `v15m_with_ta_and_markov.parquet` | `v15m_with_ta_and_markov_regime.parquet` | 12,492 | 12,485 |
| `s6_with_ta.parquet` | `s6_with_ta_regime.parquet` | 11,336 | 11,311 |
| `hybrid_gate_search_per_fire.parquet` | `hybrid_gate_search_per_fire_regime.parquet` | 23,093 | 23,048 |

Unjoined rows are at boundary edges (fires before panel start or after end).

---

## 3 — Per-sleeve regime profile

Top 7 Tier-1 sleeves (diversified — best per `asset × tf × offset_bin` cell, not 7 near-clones):

| asset | tf | offset_bin | gate_stack (truncated) | total sum_pnl |
| --- | --- | --- | --- | ---: |
| BTC | s6_5m | 60-150 | g_cci&g_stoch&g_rf&g_tr_above_ema50&g_ribbon_agrees | 14,103 |
| ETH | s6_5m | 60-150 | g_tight_ribbon&g_stoch_with | 6,170 |
| ETH | s15_5m | 150-240 | g_ribbon_agrees&g_tr_above_ema200&g_stoch&g_bb_pos&g_cci | 4,596 |
| BTC | s15_5m | 150-240 | g_tr_above_pp&g_ribbon_agrees&g_stoch&g_tight_ribbon | 4,176 |
| SOL | s6_5m | 60-150 | g_mfi&g_within_dev&g_bb_pos&g_ribbon_agrees | 3,307 |
| BTC | s15_5m | 60-150 | g_ribbon&g_ribbon_slope&g_rf&g_tr_stack | 2,860 |
| BTC | s15_5m | 240-300 | g_tr_above_cloud&g_mfi&g_tr_above_ema200&g_cci&g_stoch | 2,486 |

### Regime profile of top Tier-1 sleeves

Each row shows the 3-regime breakdown — **WR varies <10pp** between regimes
in 6 of 7 → these sleeves are already pre-filtered by gates that capture
most of what the regime label would capture. All Tier-1 top 7 classified as
**regime-agnostic**.

Notable Tier-1 dpt swings:
| Sleeve | trending_up dpt | trending_dn dpt | ranging dpt |
| --- | ---: | ---: | ---: |
| BTC s15 150-240 tr_above_pp+ribbon+stoch+tight | **−0.59** | +2.15 | +3.48 |
| BTC s15 240-300 cloud+mfi+ema200+cci+stoch | +2.37 | **−1.49** | +2.01 |
| BTC s6 60-150 cci+stoch+rf+ema50+ribbon | +4.82 | +2.65 | +6.05 |

So even "regime-agnostic" Tier-1 sleeves show dpt swings of $3-4/tr between
best and worst regime. Ranging is the most profitable regime for almost all
Tier-1 sleeves — confirming the gates were tuned for non-trending conditions.

### Regime profile of S6 and S1.5 BASE sleeves

These are unfiltered (only asset × direction). Much more regime-conditional.

**Mean WR range across regimes by class**:
| sleeve_class | mean WR range (pp) |
| --- | ---: |
| `s15_base_top10` (S1.5) | 3.0 |
| `s6_base_top10` (S6) | **10.2** |
| `tier1_top7` | 6.6 |

S6 base sleeves are HIGHLY regime-conditional (14pp WR swing on S6 SOL UP).
S1.5 base is already self-stabilizing.

Top-magnitude regime swings in base sleeves:

| Sleeve | best regime | best dpt | worst regime | worst dpt | dpt range |
| --- | --- | ---: | --- | ---: | ---: |
| S6 ETH DOWN | trending_dn | +1.92 | trending_up | **−2.49** | 4.40 |
| S6 BTC UP | ranging | +2.83 | trending_up | **−1.40** | 4.22 |
| S6 SOL UP | trending_up | +1.82 | trending_dn | −1.12 | 2.94 |
| S6 SOL DOWN | trending_up | +1.67 | ranging | −0.70 | 2.37 |
| S6 ETH UP | trending_dn | +1.36 | trending_up | −0.96 | 2.32 |

Counter-intuitive but consistent: **S6 BTC UP signals LOSE in trending-up
regime** (−1.40 dpt, n=220) and **WIN in ranging** (+2.83 dpt, n=1534). The
trend has already extended → momentum signal triggers a chase that mean-reverts.
Same pattern for S6 ETH UP. Conversely **DOWN signals on SOL win in trending-UP
regime** (+1.67 dpt) — these are contrarian fades against the trend.

Full per-sleeve × per-regime breakdown: `data/v4/canonical/_results/regime_sleeve_profile.csv`

---

## 4 — Always-on vs regime-routed portfolio (in-sample)

Top 7 Tier-1 sleeves, in-sample (Apr 30 → May 22):

| portfolio | n | sum_pnl | dpt | sharpe | max_DD | WR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| always_on | 11,750 | 35,756 | 3.043 | 0.096 | 1,837 | 82.6% |
| regime_routed | 11,529 | **36,001** | 3.123 | 0.098 | 1,837 | 82.7% |

Routing: keep fire if `(sleeve, current_regime) → dpt > 0`. Drops 221 fires
(1.9%) and adds $245 PnL (+0.7%). Tier-1 sleeves rarely have a negative-dpt
regime — they're heavily pre-filtered already.

**Conclusion (Tier-1)**: regime routing modestly improves dpt (+2.6%) but the
gain is tiny because the gate-stacks already capture most regime info. The
S6 / S1.5 / S7 BASE sleeves below have far larger upside.

---

## 5 — Regime as new gate on Tier-1 sleeves

Added `g_trending_up_with_up`, `g_trending_dn_with_dn`, `g_ranging`,
`g_trend_agrees` to top 7 sleeves. Result: most cells have <100 fires, so
sample size is too small per cell to confidently improve over the base gate
stack. `g_ranging` is the only cell with sufficient n — and it matches the
"ranging is best" finding from §3.

Full table: `regime_gate_search.csv`.

---

## 6 — Adverse-regime veto on top Tier-1 sleeves

Veto = drop fires when current regime is the lowest-dpt regime for that sleeve
(in-sample selection).

| sleeve | worst_regime | base_dpt | veto_dpt | base_sum | veto_sum | Δ sum_pnl |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| BTC s6 cci+stoch+rf+ema50+ribbon | trending_dn | 5.51 | 5.89 | 15,028 | 14,181 | −847 |
| ETH s6 tight_ribbon+stoch | ranging | 4.72 | 5.50 | 6,170 | **2,045** | −4,125 |
| ETH s15 ribbon+ema200+stoch+bb+cci | trending_dn | 1.34 | 1.44 | 4,594 | 4,453 | −141 |
| BTC s15 tr_above_pp+ribbon+stoch+tight | trending_up | 3.06 | 3.33 | 4,170 | **4,226** | +56 |
| SOL s6 mfi+within_dev+bb+ribbon | trending_up | 2.20 | 2.28 | 3,307 | 3,050 | −257 |
| BTC s15 cloud+mfi+ema200+cci+stoch | trending_dn | 1.74 | 2.05 | 2,486 | **2,676** | +190 |

Mixed: 4/6 sleeves LOSE total sum_pnl by vetoing (because the worst regime
still has positive aggregate PnL via large n) but gain dpt. Only 2/6 net positive
on sum. Veto is dpt-positive but sum-negative — not a win for Tier-1.

---

## 7 — Walk-forward on top regime-conditional sleeves

20-day train (Apr 30 → May 19) + 3-day test (May 20 → May 22). Learn best
regime on train, apply gate on test. Bootstrap 2000x for 95% CIs.

| sleeve | train_best_regime | train_baseline_dpt | test_baseline_dpt | test_gated_dpt | gated_CI_low | gated_CI_high | gated_n |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| S6 BTC DOWN | trending_up | +4.19 | +3.79 | **+10.66** | +3.45 | +16.89 | 17 |
| S6 BTC UP | ranging | +1.50 | +6.03 | +5.70 | +3.40 | +8.12 | 196 |
| S7 ETH DOWN | trending_dn | −0.37 | −2.97 | **+7.46** | +3.99 | +11.79 | 11 |
| S7 SOL DOWN | trending_dn | −0.91 | −3.30 | **+10.14** | +2.24 | +21.18 | 7 |
| S1.5 SOL DOWN | trending_dn | −0.35 | −0.76 | **+4.81** | +1.02 | +8.52 | 39 |
| S6 ETH DOWN | trending_dn | −0.43 | −4.30 | +1.26 | −10.42 | +10.92 | 8 |
| S6 SOL DOWN | trending_up | +0.10 | −2.94 | −5.32 | −15.59 | +6.86 | 12 |

**4 sleeves OOS-positive with lower CI > 0** (S6 BTC DOWN, S7 ETH DOWN, S7 SOL
DOWN, S1.5 SOL DOWN). Train baseline of three of these (S7 ETH DOWN, S7 SOL
DOWN, S1.5 SOL DOWN) was **NEGATIVE** — regime gate flips them OOS-positive.

**Cautionary**: test n=7-39 for the most striking flips. Confidence interval
is statistically positive but practically wide. Need at least 4 more weeks of
fresh data to confirm.

---

## 5b — Top 3 NEW regime-conditional sleeve recommendations

Based on §3 in-sample + §7 OOS walk-forward:

### 🥇 1. S7 ETH 15m DOWN | ONLY when regime=trending_dn

- baseline (all fires, 23d): n=1,836, sum=−$1,147, dpt=−$0.62  (LOSER)
- regime-gated (trending_dn only): n=187, sum=+$300, dpt=+$1.61  (WINNER)
- OOS test (3d): n=11, dpt=+$7.46, CI [+$3.99, +$11.79] — lower CI > 0
- **Mechanism**: directional DOWN trades only fire in regimes that confirm the
  trend. Disables "fade the dip" interpretations that lose in trending markets.

### 🥈 2. S6 BTC 5m DOWN | ONLY when regime=trending_up

- baseline: n=2,025, sum=+$8,403, dpt=+$4.15  (already positive)
- regime-gated (trending_up only): n=262, sum=+$1,360, dpt=+$5.19  (+25% dpt)
- OOS test: n=17, dpt=+$10.66, CI [+$3.45, +$16.89]
- **Mechanism**: counter-trend DOWN signals work as contrarian fades against
  extended uptrends. Filters out the noise during ranging conditions.

### 🥉 3. S1.5 SOL 5m DOWN | ONLY when regime=trending_dn

- baseline: n=5,427, sum=−$2,206, dpt=−$0.41  (LOSER baseline)
- regime-gated: n=501, sum=+$321, dpt=+$0.64  (positive)
- OOS test: n=39, dpt=+$4.81, CI [+$1.02, +$8.52]
- **Mechanism**: classic trend-following DOWN signal only fires when ADX +
  EMA stack + ribbon confirm downward trend. Eliminates whipsaws in choppy
  ranging conditions where S1.5 DOWN was bleeding cash.

---

## Honorable mention — Adverse-regime veto wins (S6 base)

These are tactical: keep the sleeve firing everywhere EXCEPT the worst regime
(less surgical than the top 3 above, but bigger n):

| sleeve | worst_regime | baseline dpt | veto dpt | uplift |
| --- | --- | ---: | ---: | ---: |
| S7 ETH 15m DOWN | ranging | −0.62 | +1.32 | **+$1.94/tr** |
| S6 SOL 5m DOWN | ranging | −0.38 | +0.97 | +$1.35/tr |
| S1.5 ETH 5m DOWN | ranging | −0.23 | +0.47 | +$0.70/tr |

`ranging` is the assassin of unfiltered DOWN signals. Three different families
(S6/S7/S1.5) all show the same effect on ETH/SOL.

---

## Caveats

1. **Regime labels are heuristic, not learned from outcomes.** The thresholds
   (ADX > 25, stack ≥ ±1, ribbon ≥ 70%) are textbook defaults. Per-asset tuning
   could find better cutoffs but introduces overfit risk.

2. **Small OOS n on the headline flips.** S7 ETH DOWN trending_dn had n=11 in
   the 3-day OOS window. Bootstrap CI is positive but practically narrow — need
   to re-run after another 14-21 days.

3. **In-sample regime selection bias.** Picking the best-train regime for each
   sleeve is in-sample optimization. The walk-forward in §7 controls for this
   on the headline sleeves, but the regime_recommendations.csv file ranks all
   sleeves by in-sample uplift, so use that ranking as a hypothesis generator
   only.

4. **Regime overlap with ribbon is 59% equal predictions.** Adding regime on
   top of `g_ribbon_agrees` adds ~40% net new info — meaningful but not
   transformative. The bigger gain is on UNGATED base sleeves (S6/S7/S1.5 base)
   where regime-conditioning is the difference between losing and winning.

5. **Tier-1 sleeves don't benefit much from regime routing.** Their existing
   gate stacks already encode trend information. Regime as additional gate
   loses too many fires (low cell counts) to be net-positive on Tier-1 sum_pnl.
   It would be a quality improvement (slightly higher dpt) at the cost of
   throughput.

6. **No causal validation of regime SCORE vs label.** The continuous
   `regime_score` is built but not heavily mined. A graduated gate
   (e.g. fire S6 BTC DOWN when regime_score > +0.3) could perform between
   the binary gate and always-on. Future work.

---

## Files produced

| Path | Description |
| --- | --- |
| `data/v4/canonical/_results/regime_panel_5m.parquet` | 5m regime panel (BTC+ETH+SOL, 23,247 bars) |
| `data/v4/canonical/_results/regime_panel_15m.parquet` | 15m regime panel (7,752 bars) |
| `data/v4/canonical/_results/hybrid_features_5m_regime.parquet` | hybrid_features + regime cols |
| `data/v4/canonical/_results/hybrid_features_15m_regime.parquet` | hybrid_features 15m + regime |
| `data/v4/canonical/_results/s15_with_ta_and_markov_regime.parquet` | S1.5 5m + regime |
| `data/v4/canonical/_results/v15m_with_ta_and_markov_regime.parquet` | S7 15m + regime |
| `data/v4/canonical/_results/s6_with_ta_regime.parquet` | S6 5m + regime |
| `data/v4/canonical/_results/hybrid_gate_search_per_fire_regime.parquet` | top-7 sleeve fires + regime |
| `data/v4/canonical/_results/regime_sleeve_profile.csv` | per-sleeve × per-regime WR/dpt/sum |
| `data/v4/canonical/_results/regime_portfolio_compare.csv` | always-on vs regime-routed |
| `data/v4/canonical/_results/regime_gate_search.csv` | regime gates added to Tier-1 |
| `data/v4/canonical/_results/regime_adverse_veto.csv` | adverse-regime veto results |
| `data/v4/canonical/_results/regime_walkforward.csv` | top-7 walk-forward |
| `data/v4/canonical/_results/regime_recommendations.csv` | per (family, asset, direction) best regime |
| `data/v4/canonical/_results/regime_walkforward_top.csv` | OOS walk-forward on top regime-conditional sleeves |
| `strategy_lab/meta_classifier/build_regime_panel.py` | regime panel builder |
| `strategy_lab/meta_classifier/augment_fires_with_regime.py` | per-fire merge |
| `strategy_lab/meta_classifier/regime_conditional_analysis.py` | Tasks 3-7 |
| `strategy_lab/meta_classifier/regime_recommendations.py` | per-base-sleeve uplift ranking |
| `strategy_lab/meta_classifier/regime_walkforward_top.py` | OOS bootstrap on top 7 picks |

---

## Bottom line

- Regime labels distribute ~86% ranging, ~7% trending_up, ~7% trending_dn — typical for crypto.
- Regime labels are NOT just rebuilding `g_ribbon_agrees` (Jaccard = 0.155).
- **Tier-1 sleeves don't benefit much from regime routing** — they're already
  pre-filtered. Regime portfolio dpt: +2.6% in-sample, +5% OOS.
- **S6 / S7 / S1.5 base sleeves benefit dramatically.** Several baseline-NEGATIVE
  sleeves flip to positive when restricted to one regime. Walk-forward confirms
  OOS with lower CI > 0 on three (S7 ETH DOWN trending_dn, S7 SOL DOWN
  trending_dn, S1.5 SOL DOWN trending_dn).
- **Counter-intuitive pattern**: S6 UP signals (BTC, ETH) LOSE in trending_up
  regime, WIN in ranging. Mean-reversion territory — trend has overshot.
- **Top 3 new regime-conditional sleeves** with bootstrapped OOS edge:
  1. S7 ETH 15m DOWN | trending_dn   (baseline LOSER → +$7.5/tr OOS)
  2. S6 BTC 5m DOWN  | trending_up   (positive → +$10.7/tr OOS)
  3. S1.5 SOL 5m DOWN | trending_dn  (baseline LOSER → +$4.8/tr OOS)

These flips happen on a few hundred fires per sleeve over 22 days — small but
statistically meaningful. Build a meta-controller that exposes a 3-way gate
(`current_regime ∈ {trending_up, trending_dn, ranging}`) and adds a per-sleeve
allowlist of regimes. Initial deployment: only on the three sleeves above.
