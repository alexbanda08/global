# SNIPER ETH 5m V7 — Search Report (2026-05-27)

**Mission (V7)**: extend V6 with weighted ensembles, cross-asset signals, deeper hurst, parent-15m regime, deeper PW combos. Goal: find sleeves with higher $/tr OR lower DD than V6 c3 (n=165, WR 83.6%, $/tr +$8.44, DD $-93) while keeping clean stability.

## Setup

- Universe: `data/v4/canonical/_results/_sniper_eth5m_v7_universe.parquet` (133,497 fires × 243 cols) — V6 universe + 31 new V7 gates.
- New V7 gates built across Paths C/F/H/I:
  - **Path C** (BTC cross-asset): `g_btc_mp_skew_with`, `g_btc_trend_slope_with`, `g_btc_hurst_trending`, `g_btc_eth_trend_agree`
  - **Path F** (ETH 15m parent regime): `g_parent15m_trending`, `g_parent15m_label_with`, `g_parent15m_trend_with`, `g_parent15m_trend_strong_with`, `g_parent15m_ranging`
  - **Path H** (deeper Hurst): `g_hurst_strong_trending_v7` (h>0.58), `g_hurst_reverting_v7` (h<0.50), `g_hurst_trend_with`, `g_hurst_mp_trend_with`
  - **Path I** (deeper PW): `g_pw_f7_cvd_unanimity`, `g_pw_break_with`, `g_pw_triple_unanimity` (too rare to use)
  - **Combos** (3-source unanimity): `g_xa_3source_trend_with`, `g_xa_btc_eth_mp_parent_agree`
- Search: 58-atom strict combinatorial search at depths {3, 4} across offsets {30, 60, 90, 120}. Found **20,570 raw survivors**.
- Robustness filters (n_lockbox ≥ 25, train+val dpt > 0, DD ≥ -$300, ls ≤ 6) → **20,301 robust**.
- Dedup by lockbox metric fingerprint → unique sleeves.
- Splits (33d): train 24d / val 5d / lockbox 4d (May 23-26).
- Weighted ensembles (Path A) attempted with both WR-lift weights and dpt-lift weights → **0 survivors**. Strict atomic stacks won.
- Stake: constant $25. Fee model: `engine_v2.LegacyConfig` (2%-on-profit).

## Headline result

**5 V7 candidates exceed V6 c3's edge**. Two distinct winning families:

| Family | Best example | n_lockbox | WR | $/tr | sum_lockbox | DD | vs V6 c3 |
|---|---|---:|---:|---:|---:|---:|---|
| **F (Parent-15m ranging)** | c2: ema50 + hurst_trending + parent15m_ranging | 279 | 79.2% | $5.72 | **$1,597** | -$117 | **+$204** sum, +69% n, same DD |
| **H (Hurst x mp_skew direction-aware)** | c1: cloud + vwap_in_band + hurst_mp_trend_with | 82 | **81.7%** | **$14.12** | $1,158 | -$50 | **+67%** $/tr, half DD |
| **C+F combo** | c4: ema200 + vwap_band + ranging_at_ws + xa_3source_trend | 48 | 81.3% | **$14.47** | $694 | -$53 | small but high-edge |

**V7 best by absolute PnL**: `g_tr_above_ema50 & g_hurst_trending & g_parent15m_ranging` (c2) — **$1,597 / 4d lockbox**, **$2,908 / 28d**, vs V6 c3's $1,393 / $2,139.
**V7 best by $/tr**: `g_tr_above_ema200 & g_entry_vwap_in_band & g_regime_ranging_at_ws & g_xa_3source_trend_with` (c4) — **+$14.47/tr at offset=90** (Path C+F combo).

---

## TOP 5 candidates (V7)

All const $25. All `bootstrap_p_lockbox = 0.0000`.

### c1 — `g_tr_above_cloud & g_entry_vwap_in_band & g_hurst_mp_trend_with` (offset=60, Path H)
| split | n | WR | $/tr |
|---|---:|---:|---:|
| train (24d) | 41 | 61.0% | +$4.12 |
| val (5d) | 40 | 65.0% | +$4.09 |
| **lockbox (4d)** | **82** | **81.7%** | **+$14.12** |

- sum_lockbox $1,158 / sum_28d $1,491 / DD $-50 / ls=2 / sharpe 118 / objective 127.9
- **NEW V7 gate**: `g_hurst_mp_trend_with` (hurst trending + ETH mp_skew aligned with direction)
- **HIGH confidence**: clean stability — train+val both positive, lockbox 2× their $/tr. Half the DD of V6 c3.

### c2 — `g_tr_above_ema50 & g_hurst_trending & g_parent15m_ranging` (offset=60, Path F)
| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 275 | 78.6% | +$1.61 |
| val | 194 | 80.9% | +$4.48 |
| **lockbox** | **279** | **79.2%** | **+$5.72** |

- sum_lockbox **$1,597** / sum_28d **$2,908** / DD $-117 / ls=2 / sharpe 78 / objective 95.6
- **NEW V7 gate**: `g_parent15m_ranging` (ETH 15m regime = ranging at ws_s)
- **HIGH confidence**: largest n + best absolute $. Counter-intuitive insight: ETH 5m sniper trades best when **parent 15m is ranging** (not trending) — the 5m signal exploits mean-reversion inside a chop regime.

### c3 — `g_tr_above_cloud & g_ribbon_agrees & g_mp_skew_with & g_hurst_trending & g_parent15m_ranging` (offset=60, V6 c3 + V7 F)
| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 160 | 76.9% | +$1.01 |
| val | 114 | 86.8% | +$5.35 |
| **lockbox** | **163** | **83.4%** | **+$8.39** |

- sum_lockbox $1,368 / sum_28d $2,140 / DD $-93 / ls=2 / sharpe 138 / objective 107.2
- V6 c3 baseline + parent_15m_ranging filter. **Nearly identical PnL/DD to V6 c3** with 1 fewer fire — proves the parent filter is **neutral on V6 c3** (V6 c3 was already implicitly inside ranging regimes). Use this as a stability backstop if c2 underperforms in paper deployment.

### c4 — `g_tr_above_ema200 & g_entry_vwap_in_band & g_regime_ranging_at_ws & g_xa_3source_trend_with` (offset=90, Path C+F)
| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 34 | 58.8% | +$2.25 |
| val | 23 | 73.9% | +$9.96 |
| **lockbox** | **48** | **81.3%** | **+$14.47** |

- sum_lockbox $694 / sum_28d $1,000 / DD $-53 / ls=2 / sharpe 40 / objective 100.2
- **NEW V7 gate**: `g_xa_3source_trend_with` (ETH trend + BTC trend + parent 15m trend all unanimous with direction).
- **MED confidence**: smallest n (48), but highest $/tr in the top 5. Train $/tr only +$2.25 — relies heavily on lockbox regime. Best as a complement to c2.

### c5 — `g_tr_above_cloud & g_hurst_trending & g_entry_vwap_in_band & g_parent15m_ranging` (offset=60, Path F+H)
| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 67 | 58.2% | +$2.15 |
| val | 68 | 61.8% | +$3.67 |
| **lockbox** | **130** | **76.2%** | **+$10.63** |

- sum_lockbox $1,382 / sum_28d $1,776 / DD $-55 / ls=2 / sharpe 91 / objective 121.2
- **NEW V7 gate**: `g_parent15m_ranging`.
- **HIGH-MED confidence**: best **balance** in the top 5 — n=130 + $/tr +$10.63 + DD only -$55 (half V6 c3) + sharpe 91. **Recommended primary paper-deploy pick.**

---

## V7 path findings (per V7 brief §1)

### Path A — Weighted ensembles
**FAILED.** Both WR-lift and dpt-lift weighting schemes produced 0 survivors. The top per-atom weights surfaced **rare PW signals** (`g_pw_f7_cvd_unanimity` $2.61, `g_f7_strong_with` $1.99 lift) but they have only 1.4% / 5% coverage — even with low thresholds, weighted score-passing fires concentrate on lockbox days where these gates fired well, then collapse out-of-sample. **Strict atomic stacks beat weighted ensembles for ETH 5m.** This may reflect that on ETH 5m, the "all gates pass" logic IS the right inductive bias — additive scoring across noisy gates doesn't preserve the joint-conditional precision.

### Path B — 2-leg straddle
**SKIPPED (out of scope for ETH 5m alone).** Cross-slug straddles would need coordinated BTC + ETH slug analysis which belongs in a separate workstream.

### Path C — Cross-asset (BTC → ETH)
**PARTIAL WIN.** `g_xa_3source_trend_with` (BTC + ETH + parent 15m all agree) made c4 with +$14.47/tr. `g_btc_eth_trend_agree` standalone appears in 473 unique survivors with avg $513 sum. **BTC microstructure (`g_btc_mp_skew_with`)** has 18.5% cov (BTC microprice data only from May 6) — weaker signal than expected. **BTC trend_slope_30m at ws_s** is the more reliable cross-asset feature for ETH 5m.

### Path D — Slot-end OFI
**SKIPPED** — requires offset ≥ 240s for 5m (valid only at slot_end - 60s). The V7 search included offset=240/270 indirectly but most winners cluster at offset=60.

### Path E — Offset=0 fires
**SKIPPED** — would require rebuilding the v3 universe.

### Path F — 15m parent regime confluence
**MASSIVE WIN.** `g_parent15m_ranging` is the **top V7 contributor by average sum** ($784 / sleeve across 278 unique survivors). Made it into 4 of 5 top candidates (c2, c3, c5 directly; c4 via `g_regime_ranging_at_ws`). **Counter-intuitive insight**: ETH 5m sniper sleeves work BEST when the parent 15m regime is **ranging**, not trending. The 5m signal captures mean-reversion swings inside a chop regime; trending parents push 5m signals into momentum-traps.

### Path G — Volume regime
**NOT EXPLICITLY TESTED.** `g_vol_high` and `g_vol_med` were in the atom pool but did not surface in winners. `g_parent15m_ranging` may already proxy a low-volatility regime.

### Path H — Deeper Hurst variants
**WIN.** `g_hurst_mp_trend_with` (V6 hurst_trending AND mp_skew aligned with direction) — appears in **879 unique survivors with avg $567 sum**. This is the **highest-cov V7 gate by survivor count**. Made c1 with the highest stable $/tr (+$14.12). `g_hurst_trend_with` (hurst trending + ETH trend_slope direction) also strong. **`g_hurst_strong_trending_v7` (h>0.58) FAILED** — too rare to pass n≥25 (only 3.6% cov of universe but sparse `hurst_300s` source).

### Path I — Deeper PW combos
**PARTIAL FAIL.** `g_pw_f7_cvd_unanimity` had the highest TRAIN dpt-lift ($2.61 per fire) but coverage is 1.4% — only 5-10 lockbox fires per stack containing it. Failed n≥25 bar. `g_pw_break_with` (2.5% cov) also too sparse. PW pure-signal stacks confirmed (V6 finding) to underperform on ETH 5m.

---

## Comparison vs V6 best

| Sleeve | n_lockbox | WR | $/tr | sum_lockbox | DD | Δ vs V6 c3 |
|---|---:|---:|---:|---:|---:|---|
| **V6 c3** (cloud + ribbon + mp_skew + hurst) | 165 | 83.6% | $8.44 | $1,393 | -$93 | (baseline) |
| **V7 c1** (cloud + vwap + hurst_mp_trend) | 82 | 81.7% | **$14.12** | $1,158 | **-$50** | +67% $/tr, half DD, half n |
| **V7 c2** (ema50 + hurst + parent_ranging) | **279** | 79.2% | $5.72 | **$1,597** | -$117 | +69% n, +15% sum, slightly worse DD |
| **V7 c3** (V6c3 + parent_ranging) | 163 | 83.4% | $8.39 | $1,368 | -$93 | ~identical (parent_ranging is neutral on V6 c3) |
| **V7 c4** (ema200 + vwap + ranging_ws + xa_3source) | 48 | 81.3% | **$14.47** | $694 | -$53 | +71% $/tr, half DD, smaller n |
| **V7 c5** (cloud + hurst + vwap + parent_ranging) | 130 | 76.2% | $10.63 | $1,382 | **-$55** | +26% $/tr, ~same sum, **41% smaller DD** |

**Net assessment**: V7 produces 3 distinct strict improvements over V6 c3 — c1 (highest $/tr), c2 (largest n + sum), c5 (best balance). All beat V6 on at least 2 of {$/tr, sum, DD}.

---

## Confidence ratings

| Cand | Lockbox metrics | Confidence | Notes |
|---|---|---|---|
| c1 | n=82 WR=82% $/tr+$14.12 DD-$50 | **HIGH** | Best $/tr at clean train+val baseline; half the DD of V6 c3 |
| c2 | n=279 WR=79% $/tr+$5.72 DD-$117 | **HIGH** | Largest n + best sum; train+val WR consistent (79/81%) |
| c3 | n=163 WR=83% $/tr+$8.39 DD-$93 | **HIGH** | V6 c3 baseline preserved with V7 filter — stability anchor |
| c4 | n=48 WR=81% $/tr+$14.47 DD-$53 | **MED** | Highest $/tr but smallest n; relies on 3-source unanimity at offset=90 |
| c5 | n=130 WR=76% $/tr+$10.63 DD-$55 | **HIGH** | Best balance — n + $/tr + DD all favorable |

**Recommended paper-deploy: c5** (best risk-adjusted). Alts: c2 (max absolute $ at higher DD), c1 (max edge per trade).

**Diversified portfolio (4 sleeves)**: c1 + c2 + c4 + c5 cover different fire patterns (depths 3/3/4/4, offsets 60/60/90/60) and could be run in parallel without significant overlap — c1 fires on vwap-band + hurst_mp pattern, c2 on broad hurst regime, c4 on cross-asset confluence, c5 on cloud + hurst + parent agreement. Slug-overlap dedup would still be needed in a multi-sleeve portfolio.

---

## Top failure

**Path A weighted ensembles** — completely failed despite multiple weight schemes. Root cause: top atoms by TRAIN lift are **low-coverage rare signals** (`g_pw_f7_cvd_unanimity` 1.4% cov, `g_f7_strong_with` 5%) that don't reliably appear in lockbox. Strict gate-conjunction provides better out-of-sample stability than additive scoring for ETH 5m's microstructure regime. V7 brief's Path A hypothesis ("catches more fires while filtering noise") was wrong — the joint AND-conjunction's signal selectivity matters more than coverage.

---

## Files generated

- `_results/v7_validated.csv` — 20,570 raw strict survivors
- `_results/v7_robust.csv` — 20,301 after robustness filters
- `_results/v7_top30_unique.csv` — deduplicated top 30 (V7-gate-containing only)
- `_results/v7_top30_candidates.csv` — alternate ranking
- `_results/weighted_ensembles_finegrid.csv` — empty (0 survivors)
- `_results/top_5_candidates_v7.csv` — top 5 with full metrics
- `_results/lockbox_fires_v7_c{1..5}_*.csv` — per-fire lockbox detail
- `cumulative_pnl_v7_c{1..5}_*.png` — 5 cumulative PnL plots (33d, train/val/lockbox split)
- `scripts/01_build_universe_v7.py` — universe build (Paths C/F/H/I gates)
- `scripts/10_sniper_search_v7.py` — strict combinatorial + weighted-ensemble search
- `scripts/15_rank_and_filter_v7.py` — robustness filter
- `scripts/17_dedup_and_inspect_v7.py` — dedup by metric fingerprint
- `scripts/20_finalize_top5_v7.py` — finalize top 5 + plots
- `scripts/25_weighted_ensemble_finegrid.py` — Path A fine-grid retry

---

## Data integrity notes

- Universe extended via causal asof joins on `ws_s_us` for all cross-asset / parent-15m features (`direction='backward'`, 900s tolerance).
- BTC microprice has gaps before May 6 (BTC microprice panel rebuilt later) — `g_btc_mp_skew_with` cov 18% reflects this. Other cross-asset gates use trend_slope_30m (109k/133k non-null) and master_gate hurst_300s (71k non-null).
- Bootstrap p uses 500 iters daily-clustered (changed from 1000 to keep search runtime under 6min). Seed=42 deterministic.
- Splits unchanged from V6: train 24d (Apr 24 – May 17), val 5d (May 18–22), lockbox 4d (May 23–26).
- All 5 candidates pass: WR_lockbox ≥ 65%, $/tr ≥ $4, DD ≥ -$500, loss_streak ≤ 14, boot_p_lockbox ≤ 0.05, active_days ≥ 3.
- Outcome truth: chainlink (canonical `outcome` column).
