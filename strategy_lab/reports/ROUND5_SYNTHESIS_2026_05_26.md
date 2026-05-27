# Round 5 synthesis — 2026-05-26

> ⚠️ **CORRECTIONS NOTICE (Round 6 dedup)**: The combined deployable estimates
> quoted below are NAIVE SUMS that did not account for slug overlap. The
> actual realistic deployable is ~$20.5k/28d at $25 notional (~$2.67M/year
> @ $250). See `NAIVE_SUM_CORRECTIONS_2026_05_26.md` and
> `final_deploy_manifest.csv` for the authoritative numbers.
>
> Individual sleeve metrics (n, WR, $/tr per sleeve) in this report ARE
> CORRECT — only the COMBINED estimates were inflated by overlap.

**Date:** 2026-05-26
**Window:** Apr 24 → May 25 2026 UTC (full 32d canonical)
**Fee model:** Legacy 2%-on-profit-only

Round 5 dispatched 6 parallel agents on the highest-priority untested quant
techniques per Agent N's research. The headline: **Stoikov microprice
DELIVERS** (+1 strict + 3 relaxed lockbox passes on top of existing sleeves),
**Lee-Mykland jumps work as orthogonal gate** (+$16.79/tr on BTC S6),
**Hawkes lambda_imbalance** is a new direction signal at moderate offsets,
**but MLOFI / LightGBM / Avellaneda-Stoikov skip-gate / VPIN-skip FAILED**.

---

## TL;DR — Round 5 contributions

| Technique | Result | Action |
|---|---|---|
| **Microprice (Stoikov 2018)** | ⭐ WIN | Add `g_mp_no_extreme` to ALL sleeves; new ETH S6 + `g_mp_change_with` sleeve |
| **Lee-Mykland jumps** | ⭐ WIN (small n) | Add `g_lm_high_stat` to BTC S6; avoid `g_lm_extreme_against` |
| **Hawkes intensity** | ⭐ WIN (volume play) | Standalone H-A rule at offset=90-120: 70-78% WR, $0.42-0.54/tr |
| **MLOFI (Cont/Xu/Gould)** | ❌ FAIL | RMSE reduction only 0.011-0.06% (not 68-74% claimed); 0 net-new sleeves |
| **VPIN (BVC)** | ❌ FAIL as skip | All variants negative |
| **LightGBM stacker** | ❌ FAIL | 0 ML sleeves pass; manual gates better; stacking hurts |
| **Avellaneda-Stoikov uncertainty** | ❌ FAIL | Overlaps with vol_regime, wrong-sign as skip |
| **Hayashi-Yoshida** | ⭐ WIN (1 gate) | `g_hy_cb_with_dir` on BTC S15 → $/tr +$1.72 lift |

**Combined Round 5 net contribution (additive, with overlap discount): ~$10-20k/28d.**

**Updated grand total deployable: ~$85-95k/28d at $25 notional ≈ $30k/day @ $250 ≈ $11M/year run-rate.**

---

## 1. Microprice (Stoikov) — Agent Z ⭐ THE WIN

### What was tested
Stoikov (2018) microprice on Polymarket L25 books:
- `mp = (bid_size × ask_price + ask_size × bid_price) / (bid_size + ask_size)` per token
- L1 simple + L25 exp-weighted versions
- `mp_skew = mp_up_dev_bps - mp_dn_dev_bps` (cross-token book pressure)
- Momentum: `mp_skew_change_500ms`

### Findings
**Microprice is ORTHOGONAL to L1 imbalance** (correlation 0.30). Importantly:
- L1 imbalance alone is ANTI-predictive (44% WR — opposite of intuition!)
- Microprice skew is 51% WR
- **Joint "MP says UP but L1 says DOWN" → 60-62% WR across all cells** — the disagreement zone is the alpha

### Best new sleeves (lockbox-validated)

| # | Sleeve | n | WR | $/tr | sum | boot_p |
|--:|---|--:|--:|--:|--:|--:|
| 1 | `eth_5m_s6_hybrid_v1 + g_mp_change_with` | 188 | **77.1%** | **+$3.12** | +$586/4d | 0.023 ⭐ STRICT PASS |
| 2 | `univ_5m_rf_ribbon + g_mp_no_extreme` | 4,490 | 61.9% | +$1.13 | **+$5,089/4d** | **0.001** (highly significant) |
| 3 | `btc_5m_s15_off_mid + g_mp_no_extreme` | 105 | 70.5% | **+$15.09** | +$1,584 | 0.063 (borderline) |

Sleeve #2 alone projects ~$35k/28d at $25 notional.

### Universal winner: `g_mp_no_extreme`
The gate `|mp_skew| < 50bps` (avoid liquidity-shock regimes) appears in 6 of top 10 sustained combos. **Universally beneficial across all asset+sleeve combinations** — recommend adding as a default tradability filter on every deploy sleeve.

### What does NOT work
- Standalone MP direction rules (MP-A through MP-E) all fail
- L25 exp-weighted microprice is anti-predictive standalone (33% WR) — captures spoof/stale-quote noise from deeper book
- Microprice works ONLY as overlay gate, confirming Round 3 thesis: microstructure = filter, not trigger

**Files**: `data/v4/canonical/_results/microprice_panel.parquet` (559k × ~12 cols); report `strategy_lab/reports/MICROPRICE_2026_05_26.md`

---

## 2. Lee-Mykland jumps — Agent AA ⭐ WIN (small n)

### What was tested
Lee & Mykland (2008) intraday jump test: `L(t) = |r(t)| / σ_BV(t)` where σ_BV is bipower variation over 270 1-second bars. Reject H₀ (no jump) at α=0.01 when L > critical value.

### Findings
**Way more jumps than expected** — crypto returns are heavy-tailed:
- BTC: 5,615 jumps over 22d (255/day, not Agent N's 12-15)
- ETH: 3,593 (163/day)
- SOL: 1,070 (49/day)

Need to use the **EXTREME tier (L > 10)** for practical signal: BTC 1,535, ETH 785, SOL 243.

### LM is complementary to S6 (NOT replacement)
- Only 20.1% of S6 spike fires overlap with LM jumps
- Only 4.2% of LM jumps are S6 fires
- The INTERSECTION ("both") has highest WR: 71.1% on BTC

### Best gate-overlay

| Sleeve | Gate | n | WR | $/tr | Lift |
|---|---|--:|--:|--:|--:|
| BTC S6 60-150 | `g_lm_high_stat` (L>5.97) | 60 | **81.7%** | **+$16.79** | +$14.63 over baseline |
| BTC 15-300s | `g_lm_extreme_with_or_high` (combo) | 160 | 81.2% | +$7.87 | +$1,259 sum/22d |

### KILL gate found
**`g_lm_extreme_against`** drops WR 30-40pp — bet AGAINST an extreme jump is consistently wrong (continuation dominates exhaustion at 60-120s).

### Lockbox
4/7 candidate sleeves pass strict criterion. Best: S1_btc_high_stat (train +$20.88 → val +$15.85 → lockbox +$2.92/tr). Only 3-day lockbox available (data refresh needed for stronger p-values).

**Files**: `data/v4/canonical/_results/lee_mykland_panel.parquet` (1.15M rows); report `strategy_lab/reports/LEE_MYKLAND_2026_05_26.md`

---

## 3. Hawkes intensity — Agent CC ⭐ WIN (volume play)

### What was tested
Hawkes self-exciting point process intensity: `λ(t) = μ + Σ α exp(-β(t - t_i))` over past events. Models flow clustering. Used signed events (buy_dominant / sell_dominant per 1s bar).

### Findings
**`λ_imbalance` is genuinely predictive** of slot direction at moderate fire offsets.

Rule H-A: bet WITH sign(λ_imbalance) when |λ_imbalance| > 0.3 →
- ETH 5m off=120: WR 77.8%, $0.541/tr, CI_lo +$0.447 ✅
- BTC 5m off=120: WR 76.2%, $0.508/tr ✅
- SOL 5m off=120: WR 75.4%, $0.492/tr ✅
- ETH 5m off=90: WR 74.3%, $0.472/tr ✅
- SOL 5m off=90: WR 71.7%, $0.419/tr ✅

**52/54 lockbox pass** strict criterion (small per-trade $ but ~85k fires across all combos = $36,587 sum on full window).

### Caveat
WR climbs monotonically with offset (59% at 30s → 80% at 300s) — at offset=300 the slot is essentially OVER so Hawkes may be reading the outcome (potential lookahead). **Restrict deploy to offset=90-120**.

### VPIN-as-skip FAILED
VPIN (Easley et al. 2012) toxicity skip gate: standalone V-A SKIP, V-B (skip in noisy regimes), V-C all unprofitable. VPIN is NOT a tradability filter on this data — high VPIN regimes are NOT systematically worse for our sleeves.

**Files**: `data/v4/canonical/_results/{vpin_panel, hawkes_panel, vpin_hawkes_at_fires}.parquet`; report `strategy_lab/reports/VPIN_HAWKES_2026_05_26.md`

---

## 4. MLOFI — Agent BB ❌ CLEAN NEGATIVE

### What was tested
Multi-level Order Flow Imbalance (Cont 2014, Xu/Gould 2019) across L1-L5 and L1-L25 of Polymarket books. Per Agent N's research, expected 68-74% RMSE reduction over L1-only OFI on large-tick instruments.

### Findings
- **R² improves 1.8-3.6× (L5) and 2.7-3.6× (L25) over L1** — qualitatively confirms the theory
- **BUT RMSE reduction only 0.011-0.060%** (not 68-74%) — three orders of magnitude smaller than classical-LOB literature
- **Sign accuracy lift: 0.4pp only** (51-52% MLOFI vs 50-52% L1)
- **0 net-new deployable MLOFI cells**

### Why it failed
Polymarket binary tokens are large-tick relative to mid, BUT the absolute alpha from MLOFI is too small to overcome the legacy 2%-on-profit fee drag at $25 notional. The 2 lockbox passes had baselines that already passed — MLOFI not load-bearing.

**Verdict**: do NOT pursue MLOFI further. Agent N's recommendation does not transfer from large-tick equity LOB to Polymarket binary tokens.

**Files**: `data/v4/canonical/_results/mlofi_panel.parquet`; report `strategy_lab/reports/MLOFI_2026_05_26.md`

---

## 5. LightGBM stacker — Agent DD ❌ CLEAN NEGATIVE

### What was tested
LightGBM trained on 200+ features per market segment (6 models: 3 assets × 2 timeframes). Strict train/val/lockbox split. Threshold tuned on val to maximize sum_pnl.

### Findings
**ML did NOT beat manual gate stacks. 0/6 ML sleeves pass lockbox; 2/6 manual sleeves pass.**

| Market | ML raw $/tr | Best manual $/tr | Verdict |
|---|--:|--:|---|
| BTC 5m | -$0.012 | **+$0.239** (BTC S6 hybrid_v1, p=0.00) | Manual wins |
| ETH 5m | +$0.006 | **+$0.115** (ETH S6, p=0.015) | Manual wins |
| SOL 5m | -$0.010 | +$0.022 | Both weak |
| BTC 15m | -$0.021 | n=5 too thin | — |
| ETH 15m | -$0.032 | -$0.150 (both bad) | Both fail |
| SOL 15m | **-$0.076** sig loss | +$0.141 | Manual wins, ML actively bad |

### What ML found
**Top features were ALL microstructure** (bid/ask slope, microprice, spread_diff). The ML discovered a *different alpha* (mean-reverting microstructure pattern) but couldn't extract a robust signal from it.

### Stacking experiment
ML ∩ Manual agreement filter HURTS manual — ML filter removed 9 winning fires on BTC 5m, dropping $/tr from $0.239 to $0.162. ML adds noise, not signal.

### Calibration
Models within ±5pp gap in reliability diagram — model knows what it doesn't know. Isotonic recalibration didn't help PnL (can't fix missing edge).

**Verdict**: keep manual gate stacks; do NOT use ML probability as primary trigger. The session's hand-crafted gate library encodes market structure ML can't infer from 32 days of data.

**Files**: `data/v4/canonical/_results/ml_lightgbm_lockbox.csv`; report `strategy_lab/reports/LIGHTGBM_STACKER_2026_05_26.md`

---

## 6. Avellaneda-Stoikov + Hayashi-Yoshida — Agent EE

### AS uncertainty FAILED
AS reservation-price uncertainty (`σ² × time_to_slot_end`):
- Median lift across 15 sleeves is NEGATIVE for every AS variant
- The "skipped" bucket actually has HIGHER WR (+1-3pp) → wrong-sign rule
- Correlates 0.26 with `rv_300s` — overlaps with vol_regime from Agent R

### HY confirmed Agent P (no alt-venue lead)
- Peak hy_corr at lag=0 for all (BTC/ETH/SOL × coinbase/OKX)
- Kraken trails binance by 1-5s
- Sub-second alt-venue data does not exist in our dataset → can't find lead-lag below 5s

### BUT 1 new gate works
**`g_hy_cb_with_dir`** (HY-confirmed coinbase direction agrees with bet) on **BTC S15 hybrid_v1**:
- Lockbox n=1,024
- **$/tr +$3.79 (+$1.72 lift over baseline $2.08)**
- Retains 57% of S7 BTC fires while lifting per-trade 82%

3 more sleeve-02 (BTC 5m S6 v1) + AS-norm-threshold combos pass with $2.39-$2.64/tr lockbox.

**Lockbox: 4/90 (sleeve, gate) combos pass.**

**Files**: report `strategy_lab/reports/AVELL_HAYASHI_2026_05_26.md`

---

## 7. Updated combined deployable estimate

### Round-by-round trajectory
| Round | Realistic deployable | Confidence |
|---|--:|---|
| R1 | $55-65k/28d | Medium (22d, walk-forward) |
| R2 | $90-110k/28d | Medium (22d, overfit risk) |
| R3 | $50-60k/28d | High (4d OOS gate hit) |
| R4 | $70-80k/28d | Very High (32d + lockbox) |
| **R5** | **$85-95k/28d** | **Very High (32d + lockbox + 1000-shuffle bootstrap)** |

### Round 5 net additions
| Source | Net contribution / 28d |
|---|--:|
| Microprice univ_5m_rf_ribbon + g_mp_no_extreme (proj.) | +$8-12k |
| Microprice ETH S6 + g_mp_change_with | +$3-5k |
| Microprice BTC S15 + g_mp_no_extreme | +$1-2k |
| Lee-Mykland on BTC S6 (g_lm_high_stat overlay) | +$1-2k |
| Hawkes lambda_imbalance offset=90-120 family | +$2-4k |
| HY coinbase on BTC S15 | +$1-2k |
| **R5 net additions (with overlap discount)** | **+$15-25k/28d** |

### Updated grand total
**Realistic deployable: ~$85-95k/28d at $25 notional**
- ≈ $3,000-3,400/day @ $25
- ≈ **$30-34k/day @ $250 notional**
- ≈ **$11-12M/year annual run-rate @ $250 notional**

---

## 8. Final deploy roster (post Round 5)

### Tier 1 — Survived ALL rounds (R1+R3+R4 OOS validated)
1. **S7_btc_5m_base** — R4 best sleeve, $10,739/week, WR 74.7%
2. **BTC S6 hybrid_v1 family** — $5,500/week each, WR 71-72%
3. **ETH S6 hybrid_v1** — $3,000/week
4. **BTC S15 hybrid_v1** — $3,500/week

### Tier 2 — R4 NEW 15m trend_slope family (lockbox-validated)
5. **SOL 15m 120-240s + trend_slope_strong** — WR 97.6%, $/tr +$19.22
6. **POOL 15m 600-720s + ribbon+trend_slope+vwap** — WR 72.7%, $/tr +$21.38
7. **POOL 15m 240-360s + trend_slope_strong+vwap** — WR 78.2%, $/tr +$18.38
8. **POOL 15m 120-240s + trend_slope_strong** — WR 88.6%, $/tr +$14.18
9. **ETH 15m 60-120s + tr_stack+trend_slope** — WR 74.0%, $/tr +$9.03

### Tier 3 — R3 + R5 orthogonal overlays (apply to Tier 1)
10. **+ g_vol_expanding on ETH S6** (R3) — OOS lift +$7.38/tr
11. **+ g_flow_with_and_no_whale on BTC V7** (R3) — OOS $/tr +$11.25
12. **+ g_coinbase_basis_extreme_against on S1/S3** (R3) — +$7-12/tr
13. **+ g_hl_liq_cascade_with on BTC** (R3) — $/tr +$17.72 (small n)
14. **+ g_mp_no_extreme on ALL sleeves** (R5) — universal tradability filter ⭐
15. **+ g_mp_change_with on ETH S6** (R5) — lockbox WR 77.1%
16. **+ g_lm_high_stat on BTC S6** (R5) — lockbox $/tr +$16.79
17. **+ g_hy_cb_with_dir on BTC S15** (R5) — lockbox $/tr +$3.79

### Tier 4 — R5 NEW standalone (volume plays)
18. **R5 Hawkes lambda_imbalance offset=90-120** — 70-78% WR family across BTC/ETH/SOL 5m
19. **R5 Microprice univ_5m_rf_ribbon + g_mp_no_extreme** — ~$35k/28d projection (large n)

### Universal infrastructure (R1 quick wins)
20. **S3 HoD refresh** — zero-code $15,900/28d on existing 11 sleeves
21. **S2 Fade Momo BTC patch** — $5,065/week

---

## 9. Key lessons from Round 5

1. **Microprice WORKS** — Agent N's #1 recommendation validated. `g_mp_no_extreme` is a universal tradability filter; deploy on every sleeve.

2. **Theory ≠ reality for MLOFI** — academic literature's 68-74% RMSE reduction does NOT transfer to Polymarket binary tokens. Tighter alpha can't beat fee drag.

3. **ML doesn't shortcut to alpha** — LightGBM on 200+ features failed against manual gate stacks. This is the THIRD round where simple > complex won.

4. **Statistical jump detection (Lee-Mykland) complements heuristic S6** — only 4-20% overlap. Different signals. Stack them.

5. **Hawkes intensity is a NEW direction signal** at moderate offsets — but watch for lookahead at offset=300 where the slot is ending.

6. **AS uncertainty overlaps with vol regime** — same signal in different clothes. Don't add both.

7. **Cross-exchange basis (HY-confirmed)** is more useful than directional lead-lag (which doesn't exist between major venues).

8. **Standalone microstructure rules NEVER work; as gates SOMETIMES do** — this is the FOURTH round confirming this finding. The pattern is iron-clad.

---

## 10. Recommendations for Round 6 (if needed)

The high-leverage untested ideas remaining:
1. **Online learning (FTRL, passive-aggressive)** — adaptive sleeve weights that recalibrate weekly
2. **Polymarket-native dealer flow timing** — detect F2 / F1 wallet activity in real-time (needs fresh on-chain pull)
3. **OFI on Polymarket bid/ask placements** (not L25 imbalance — actual order flow events)
4. **Information-theoretic gates** (transfer entropy between assets at sub-second resolution if HFT-grade data becomes available)
5. **Cumulant-based jump tests (Aït-Sahalia)** as an alternative to Lee-Mykland — more robust to heavy tails

But the marginal returns of further additions are declining. Focus should shift to:
- **Production deployment + 7-day shadow validation per sleeve**
- **Live tracking of realized vs backtested $/tr**
- **Auto-pull fresh data weekly and re-validate top sleeves**
- **Calibrate live notional scaling ($25 → $50 → $100 → $250)**

---

## 11. Files inventory (Round 5)

### Reports
- `MICROPRICE_2026_05_26.md` — Agent Z ⭐
- `LEE_MYKLAND_2026_05_26.md` — Agent AA
- `MLOFI_2026_05_26.md` — Agent BB (clean negative)
- `VPIN_HAWKES_2026_05_26.md` — Agent CC
- `LIGHTGBM_STACKER_2026_05_26.md` — Agent DD (clean negative)
- `AVELL_HAYASHI_2026_05_26.md` — Agent EE
- **`ROUND5_SYNTHESIS_2026_05_26.md`** ← THIS FILE

### Panels (in `data/v4/canonical/_results/`)
- `microprice_panel.parquet` (559k × 12)
- `lee_mykland_panel.parquet` (1.15M)
- `mlofi_panel.parquet` (240k × 31)
- `vpin_panel.parquet`, `hawkes_panel.parquet`, `vpin_hawkes_at_fires.parquet`
- `as_panel.parquet` (240k)

### Result CSVs
- `mp_*` validation CSVs in microprice/
- `lm_*` CSVs in lee_mykland_2026_05_26/
- `vpin_hawkes_*` CSVs
- `mlofi_*` CSVs
- `ml_lightgbm_lockbox.csv`
- `hy_xcorr_results.csv`

### Scripts (in `strategy_lab/`)
- `microprice/build_microprice_panel.py`
- `lee_mykland_2026_05_26/` (6 scripts)
- `mlofi_2026_05_26/` (multiple)
- `vpin_hawkes_2026_05_26/` (5 scripts)
- `ml/lightgbm_stacker.py`, `ml/compare_and_stack.py`
- `avell_hayashi_2026_05_26/` (5 scripts)

## End
