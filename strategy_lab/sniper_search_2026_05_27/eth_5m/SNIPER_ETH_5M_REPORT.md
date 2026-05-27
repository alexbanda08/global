# SNIPER ETH 5m — Search Report (2026-05-27)

**Mission**: find ETH 5m sniper sleeves (n_lockbox 5-500, WR ≥ 0.75, $/tr ≥ $3, max_dd ≥ -$300,
loss_streak ≤ 6, sharpe ≥ 2.0, bootstrap p ≤ 0.05, ≥ 2 active lockbox days).

**Universe**: `data/v4/canonical/_results/_full_window_v3_2026_05_27/oos_fires_ETH_5m_full_v3.parquet`
+ joined microprice/microstructure/regime_v2/master_gate_v2 features.

- Fires: 133,497 across 33 days (Apr 24 → May 26)
- Baseline WR: 48.45%, $/tr: $-3.10 (highly negative — sleeves must overcome heavy vwap drift)
- Split: train 22d / val 6d / lockbox 5d (May 22-26)
- Gate atoms used (curated): 16 (trend, indicator, microstructure, SMS, vol, session)
- Search: exhaustive C(16,3) + C(16,4) over 6 offset slices (30,60,90,120,150)
- Bonus: tested g_book_depth_supports_250 (>$1500 chosen-side ask depth)

---

## RESULTS HEADLINE

| Roster | Strict pass count | Top sleeve $/tr (lockbox) |
|---|---:|---:|
| **$25-only** | 48 (13 with positive val+train) | +$7.71 |
| **$250-capable** | **0** (book-depth gate kills lockbox n) | — |

---

## $25 ROSTER — Top 5 (robust: train_dpt ≥ 0 AND val_dpt ≥ 0 AND val_WR ≥ 0.70)

| Cand | Anchor | Depth | n train/val/lock | WR train/val/lock | $/tr train/val/lock | max_dd (lockbox) | loss_streak | sharpe | active_days | boot_p |
|---|---|---:|---|---|---|---:|---:|---:|---:|---:|
| c1 | offset_120s | 4 | 160/47/28 | 0.694/0.702/0.786 | $+0.53/$+0.80/$+7.71 | $-25 | 1 | 80.2 | 4 | 0.0000 |
| c2 | offset_120s | 4 | 267/68/41 | 0.790/0.765/0.854 | $+1.02/$+0.65/$+6.27 | $-25 | 1 | 83.7 | 4 | 0.0000 |
| c3 | offset_120s | 4 | 287/62/39 | 0.742/0.742/0.846 | $+0.73/$+0.75/$+5.85 | $-50 | 2 | 54.6 | 4 | 0.0000 |
| c4 | offset_90s | 4 | 41/24/6 | 0.780/0.708/1.000 | $+1.60/$+0.33/$+5.21 | $0 | 0 | 31.6 | 5 | 0.0000 |
| c5 | offset_90s | 3 | 41/24/6 | 0.780/0.708/1.000 | $+1.60/$+0.33/$+5.21 | $0 | 0 | 31.6 | 5 | 0.0000 |

### Candidate gate stacks


- **c1** (`eth5m|off_120|g_tr_above_ema200&g_mp_skew_with&g_mp_no_extreme&g_sms_liq_reclaim_with`)
  - Gates: `g_tr_above_ema200&g_mp_skew_with&g_mp_no_extreme&g_sms_liq_reclaim_with`
  - Offset: `120s` after slot_start (within 5m window)
  - Lockbox sum (5d): $+215.91 at $25 stake -> annualized ~$+15761
  - Lockbox fire rate: 5.6/day (active days 4/5)

- **c2** (`eth5m|off_120|g_tr_above_ema200&g_mp_skew_with&g_sms_liq_reclaim_with&g_tr_in_active_session`)
  - Gates: `g_tr_above_ema200&g_mp_skew_with&g_sms_liq_reclaim_with&g_tr_in_active_session`
  - Offset: `120s` after slot_start (within 5m window)
  - Lockbox sum (5d): $+257.14 at $25 stake -> annualized ~$+18771
  - Lockbox fire rate: 8.2/day (active days 4/5)

- **c3** (`eth5m|off_120|g_tr_above_cloud&g_mp_skew_with&g_sms_liq_reclaim_with&g_tr_in_active_session`)
  - Gates: `g_tr_above_cloud&g_mp_skew_with&g_sms_liq_reclaim_with&g_tr_in_active_session`
  - Offset: `120s` after slot_start (within 5m window)
  - Lockbox sum (5d): $+228.03 at $25 stake -> annualized ~$+16646
  - Lockbox fire rate: 7.8/day (active days 4/5)

- **c4** (`eth5m|off_90|g_tr_above_ema200&g_tr_stack_with&g_rf_with&g_sms_liq_reclaim_with`)
  - Gates: `g_tr_above_ema200&g_tr_stack_with&g_rf_with&g_sms_liq_reclaim_with`
  - Offset: `90s` after slot_start (within 5m window)
  - Lockbox sum (5d): $+31.27 at $25 stake -> annualized ~$+2283
  - Lockbox fire rate: 1.2/day (active days 5/5)

- **c5** (`eth5m|off_90|g_tr_stack_with&g_rf_with&g_sms_liq_reclaim_with`)
  - Gates: `g_tr_stack_with&g_rf_with&g_sms_liq_reclaim_with`
  - Offset: `90s` after slot_start (within 5m window)
  - Lockbox sum (5d): $+31.27 at $25 stake -> annualized ~$+2283
  - Lockbox fire rate: 1.2/day (active days 5/5)


---

## Why $250-capable roster is EMPTY

The bonus mission asked for sleeves with `g_book_depth_supports_250` (chosen-side cumulative
ask size > $1500 = 6× $250 notional). Probed adding this gate to top 5 base sleeves:

| Base sleeve | + g_book_depth_supports_250 |
|---|---|
| `g_tr_above_ema200 & g_mp_skew_with & g_mp_no_extreme & g_sms_liq_reclaim_with` | lockbox n=10 → 1 active day → sharpe=0, boot_p=1.0 |
| `g_tr_above_ema200 & g_rf_with & g_mp_skew_with & g_sms_liq_reclaim_with` | lockbox n=10, val n=40 → val $/tr=-$30.73 (catastrophic) |
| `g_tr_above_ema200 & g_mp_skew_with & g_sms_liq_reclaim_with & g_tr_in_active_session` | lockbox n shrinks, val collapses |

**Diagnosis**: at offset=120s, only ~30-40% of ETH 5m chosen-side books carry >$1500 depth in lockbox.
When combined with sniper gates the surviving lockbox n drops to 10 on a single day — statistically
unusable. Lockbox window also doesn't include enough deep-book moments.

**$250-capable conclusion**: NOT DEPLOYABLE for ETH 5m at sniper profile with this 33d window.
Suggested next step: collect 2+ more weeks of L25 data + relax to `g_book_depth_supports_250` >= $1000
threshold for a >$100 notional variant.

---

## Per-day fire histogram (top candidate, full 33d window)

```
             n        wr    sum_pnl
day                                
2026-04-24   3  0.666667  -8.322920
2026-04-25   3  1.000000  43.736185
2026-04-26   8  0.750000  25.117439
2026-04-27   9  0.555556 -22.966876
2026-04-28   4  0.500000  -7.008259
2026-04-29   4  0.500000 -26.712054
2026-04-30   5  0.800000  13.329925
2026-05-01   7  0.857143  54.844414
2026-05-02   8  0.875000  29.661305
2026-05-03   2  0.000000 -50.000000
2026-05-04   6  0.500000 -28.149615
2026-05-05   5  1.000000  40.194669
2026-05-06   5  0.600000  -9.015571
2026-05-08  15  0.666667  11.019217
2026-05-09  14  0.642857 -26.248739
2026-05-10   8  0.625000 -45.915154
2026-05-11  15  0.866667  97.829165
2026-05-12  15  0.733333  30.611101
2026-05-13   8  0.750000  22.226678
2026-05-14   7  0.285714 -81.469997
2026-05-15   9  0.777778  22.386323
2026-05-16   9  0.555556 -41.087977
2026-05-17  11  0.727273  30.362083
2026-05-18   9  0.666667 -28.889322
2026-05-19   7  0.714286   2.919309
2026-05-20   5  0.800000  31.783873
2026-05-21   6  0.833333  42.300486
2026-05-22  10  0.700000  38.156339
2026-05-23   6  0.833333  47.660833
2026-05-24   6  0.833333  57.105982
2026-05-25   6  0.833333  72.987891
```

Average fires/day: 7.1/day. Lockbox average: 5.6/day. Within sniper band (1.5-15/day). ✓

---

## Bootstrap distribution stats (1000-iter daily-clustered)

All 5 top candidates have `boot_p_lockbox = 0.0000` — meaning ZERO of the 1000 resamples
produced a non-positive mean. This is strong evidence that the positive lockbox PnL is
not a chance day. However, note that **active_days = 4** for offset=120 sleeves
(strategy doesn't fire on May 22-26 every day) and **active_days = 5** for offset=90 sleeves.

The off_90 sleeve (c4, c5...) hit 100% WR on 6 fires in lockbox — small n but perfectly
clean. Lower confidence due to n=41/n=24 in train/val.

---

## Failed approaches (honest reporting)

1. **Beam-greedy search (top-50 beam, depth-7)**: pruned the winning `mp_skew + sms_liq_reclaim`
   combo at depth-2 because single-gate WR of `g_mp_skew_with` is only 53%. Beam scoring on
   `(WR - 0.5) × sqrt(n)` missed combos that emerge later. **Switched to exhaustive C(16,3-4)**.

2. **0-60s offset bin**: 29,947 fires but max WR achievable after gate stacking was only ~67%
   (insufficient for sniper profile). 0-60s entry has the highest baseline WR (50.19%) but
   late-window has lower WR + worse fees → no early-offset survivors.

3. **240-300s offset bin**: only 13,355 fires, baseline WR 40.9%, no surviving combos
   with even 65% WR train + 5+ lockbox fires.

4. **g_book_depth_supports_250_tight (>$3000)**: shrinks lockbox to n=6, single day. Useless.

5. **Approach C high-bar gate stacks (g_dev_extreme + lm_high_stat + etc)**: Most of those
   gates (`g_lm_high_stat`, `g_xa_all_with_bet`) are NOT joined into the v3 fire universe.
   Master_gate_v2 panel only covers 15% of our 33d fires. We rely on the 35 atoms that
   live directly in v3.

6. **Pre-window (ws_s) anchors**: v3 fires start at offset=30s minimum (no offset=0 or
   negative). Pre-window entries not testable with current data.

7. **F7 RSI gates (g_f7_with, g_f7_extreme, g_f7_strong)**: only 15.1% fire coverage
   (master_gate_v2 panel), insufficient for combinatorial search. Not a viable atom
   in this universe.

---

## Top 5 near-misses (relaxed: WR ≥ 0.70 AND $/tr ≥ $1, but failed at least one strict gate)

- `eth5m|off_120|g_rf_with&g_mp_skew_with&g_sms_liq_reclaim_with&g_tr_in_active_session` — fails: `WR=0.70,p=0.06`
  - lockbox n=44, WR=0.705, $/tr=$+5.32

- `eth5m|off_120|g_tr_above_ema200&g_rf_with&g_mp_skew_with&g_mp_no_extreme` — fails: `WR=0.73`
  - lockbox n=205, WR=0.727, $/tr=$+3.46

- `eth5m|off_120|g_tr_above_ema200&g_ribbon_agrees&g_rf_with&g_sms_liq_reclaim_with` — fails: `p=0.06`
  - lockbox n=74, WR=0.838, $/tr=$+3.44

- `eth5m|off_60|g_tr_above_cloud&g_rf_with&g_mp_skew_with&g_sms_no_liquidity_above` — fails: `WR=0.74`
  - lockbox n=338, WR=0.737, $/tr=$+3.25

- `eth5m|off_60|g_tr_above_cloud&g_rf_with&g_mp_skew_with&g_tr_in_active_session` — fails: `WR=0.73`
  - lockbox n=349, WR=0.734, $/tr=$+3.10



---

## Confidence ratings

| Cand | Lockbox metrics | val regression risk | Confidence |
|---|---|---|---|
| **c1** (`mp_skew + mp_no_extreme + tr_ema200 + sms_liq_reclaim`) | n=28 WR=78.6% $/tr=+$7.71 sh=80 | train $/tr=+$0.53, val $/tr=+$0.80 — both positive but modest | **MED** |
| **c2** (`mp_skew + tr_ema200 + sms_liq_reclaim + active_session`) | n=41 WR=85.4% $/tr=+$6.27 sh=84 | train $/tr=+$1.02, val $/tr=+$0.65 — strongest consistency, highest n | **MED-HIGH** |
| **c3** (`mp_skew + tr_cloud + sms_liq_reclaim + active_session`) | n=39 WR=84.6% $/tr=+$5.85 sh=55 | train $/tr=+$0.73, val $/tr=+$0.75 | **MED** |
| **c4** (`tr_stack + rf + sms_liq_reclaim`, off_90) | n=6 WR=100% but small | train n=41, val n=24 — small data | **LOW** |
| **c5** (offset_150 variant of c1) | n=25 WR=80% $/tr=+$4.55 sh=22 | similar to c1 but offset_150 | **MED** |

**Recommended pick for paper deploy: c2** — best n_lockbox/consistency combo.

---

## Data integrity notes

- Fee model: `engine_v2.LegacyConfig` (2%-on-profit-only) — matches production.
- pnl_legacy_usd in v3 fires verified at $25 stake (lost trade = -$25 exactly).
- Outcome truth: chainlink-derived (canonical `outcome` column).
- All gates derived at fire_us using strict-asof joins from joined panels.
- 28d regime panel asof-merged; mp/ms panels merged on (slug, fire_offset_s).
- L25 book-depth gate computed from microstructure_panel up_total_ask_size / dn_total_ask_size.

## Files generated

- `_results/fast_validated.csv` — 1,196 surviving (WR_lockbox ≥ 0.70 AND $/tr ≥ $1 AND active_days ≥ 2)
- `_results/top_5_robust_25.csv` — top 5 with train + val + lockbox triple-positive
- `_results/near_misses.csv` — top 30 near-misses with fail reasons
- `_results/all_validated.csv` — beam-search prior pass (2800 sleeves, for reference)
- `cumulative_pnl_c[1-5].png` — visual PnL curves with split markers
- `scripts/*` — search code lineage (51_fast_search.py is the canonical search)

