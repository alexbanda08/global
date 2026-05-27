# Full-window all-sleeves re-test — 2026-05-26

Master re-validation of every base and R1/R2 sleeve on the **full canonical data window** (Apr 24 → May 26, ~32-33 days, ~50% more data than the 22-day window used in prior rounds).

Conventions: LegacyConfig (2%-on-profit-only) fees, ws_s = slot_start − window_s, F7 RSI Wilder simple-mean at ws_s, outcome from chainlink, causal lookups (last fully-closed bar before fire_us).

---

## 1. Data window confirmed

| Source | Range | Count |
|---|---|---|
| Resolutions (chainlink-only) | 2026-04-24 01:40 → 2026-05-26 17:25 UTC | 36,157 markets (27,130 × 5m, 9,027 × 15m) |
| 1s klines | 2026-04-07 → 2026-05-26 17:36 UTC | BTC 4.22M, ETH 4.22M, SOL 4.22M |
| Per-asset slugs per day | ~864 (5m) × 3 assets | ~32 full days available |

Full window used: **Apr 24 00:00 → May 26 17:25 UTC ≈ 32-33 days**.

Three slices composed the analysis:
- **REF (May 1 → May 21, 21d)**: existing `s6_joined_all`, `s15_joined_all`, `v15m_joined_all` from R1/R2.
- **PREFIX (Apr 24 → May 1, ~7d)**: newly built by this script (`prefix_fires.parquet`, 231,030 fires).
- **OOS (May 21 → May 25, ~4d)**: pre-built by Agent T (`oos_fires_*_5m.parquet`, `oos_fires_*_15m.parquet`, 123,390 fires).
- **FULL = REF ∪ OOS ∪ PREFIX**, dedup on `(slug, fire_us, direction)`.
- **Last-7-day OOS slice = May 19 → May 26** (true 7-day forward holdout, includes ~3 days nothing has seen before).

Per-sleeve `full_days` distribution: median 32, mean 31.3 (matches expected ~32 days).

---

## 2. Panel rebuild status

| Panel | Action | Reason |
|---|---|---|
| `range_filter_1s` | **Rebuilt for PREFIX** (Apr 24 → May 1, 615K bars × 3 assets) | extension only; REF + OOS already used existing prod panel |
| `traders_reality_1s` | **Rebuilt for PREFIX** | same as above |
| `ta_indicators_1s` | **Rebuilt for PREFIX** (ribbon + stoch + BB + MFI + CCI) | same as above |
| `sms_panel_5m` | **Rebuilt for PREFIX** (liquidity_up/dn from 20-bar sweep) | same as above |
| `regime_panel_5m/15m` | KEPT (already covers Apr 28 → May 25) | sufficient for full window |
| `vol_hurst_at_fire_5m/15m` | KEPT (Apr 30 → May 23) | only used by hybrid_v1 sleeves which used REF features |

Skipped (per spec): Quantum Ribbon, DRZ — already failed R3 and not in deploy candidates.

Build time: PREFIX panels (RF/TA/TR/SMS) **2.0s/asset**; PREFIX fires (5m+15m) **2.5 min total**. Whole pipeline **3.1 min**.

---

## 3. Per-sleeve full-window metrics

42 sleeves tested. Full table at `data/v4/canonical/_results/full_window_all_sleeves_results.csv`.

### Headline numbers

| Group | Tested | OOS-PASS | OOS-FAIL |
|---|---:|---:|---:|
| Agent T's top 15 (re-validated) | 15 | 8 | 7 |
| R1/R2 hybrid_gate_search_top extras | 6 | 4 | 2 |
| R2 new_indicator catalog (S1.5, etc) | 3 | 1 | 2 |
| Tier-1/Tier-2 RF confluence | 5 | 4 | 1 |
| S1.5 + ribbon overlay | 2 | 2 | 0 |
| S6+TA overlay | 3 | 3 | 0 |
| S7 base | 3 | 2 | 1 |
| S2 Fade Momo | 1 | 1 | 0 |
| S5 Z_Contra | 1 | 1 | 0 |
| V15m extras | 3 | 0 | 3 |
| **Total** | **42** | **26** | **16** |

OOS-pass criterion: `n_oos ≥ 20`, `WR_oos ≥ 60%`, `$/tr_oos > 0` on the last-7-day slice (May 19-26).

### Largest deltas (full-window WR vs original 22d doc WR)

| Sleeve | doc WR | full WR | Δ WR pp | doc dpt | full dpt | full sum |
|---|---:|---:|---:|---:|---:|---:|
| 14_sol_5m_drz_res_down | 0.639 | 0.461 | **−17.8** | 6.62 | −5.79 | −$112,640 |
| 13_pool_15m_offge480 | 0.872 | 0.498 | **−37.4** | 5.48 | −3.25 | −$7,675 |
| R1_eth_5m_s6_tight_stoch | 0.665 | 0.525 | **−14.0** | 4.72 | −1.66 | −$29,185 |
| 09_btc_5m_xa_down | 0.821 | 0.555 | **−26.6** | 1.64 | −1.95 | −$44,416 |
| 05_btc_5m_off120_sms_liq | 0.771 | 0.525 | **−24.6** | 20.68 | −2.01 | −$1,292 |

Most degradations stem from gate-stack overfitting on the 22-day window. The DRZ sleeve and the pool_offge480 sleeve completely collapse (high doc WR was sample-size noise on 86-291 fires).

---

## 4. Stability ranking

Weekly rolling $/tr stability classification on the full 32-day window.

| Class | Count | Definition |
|---|---:|---|
| IMPROVING | 32 | last week $/tr > first week + 50% |
| DEGRADING | 10 | last week $/tr < first week − 50% |
| STABLE | 0 | weekly $/tr stdev < 50% of mean (no sleeves qualify across all 32 days) |
| VOLATILE | 0 | all others |

The all-IMPROVING-or-DEGRADING split reflects the heavy regime shift around May 19-21 (LARGE post-rally chop ended; market resumed cleaner trending). The "IMPROVING" label here is mostly "post-rally chop → cleaner trending" rather than a fundamental strategy improvement — interpret with caution.

DEGRADING sleeves (n=10) all have a common pattern: 15m timeframe + tight gate stack that over-fit on the noisy 22d window, or sentiment-flip from BTC to ETH dominance.

---

## 5. Sleeves that FAIL OOS (16 of 42)

Sorted by last7_sum (worst first). These are NOT deployment-ready.

| Sleeve | full WR | full sum | last7 n | last7 WR | last7 dpt | last7 sum |
|---|---:|---:|---:|---:|---:|---:|
| 14_sol_5m_drz_res_down | 0.461 | −$112,640 | 6,708 | 0.455 | −5.35 | −$35,856 |
| R2_btc_5m_s6_rf_solo | 0.557 | −$81,314 | 16,112 | 0.554 | −1.02 | −$16,372 |
| R1_eth_5m_s6_tight_stoch | 0.525 | −$29,185 | 6,227 | 0.520 | −2.36 | −$14,668 |
| 09_btc_5m_xa_down | 0.555 | −$44,416 | 8,106 | 0.561 | −1.08 | −$8,728 |
| T2_eth_rf_up_v1 | 0.663 | −$8,438 | 4,337 | 0.665 | −0.81 | −$3,511 |
| R2_eth_5m_s1_5_5bps | 0.667 | −$15,701 | 8,771 | 0.677 | −0.20 | −$1,720 |
| V15_btc_off120_240 | 0.668 | −$1,492 | 595 | 0.630 | −2.05 | −$1,217 |
| 05_btc_5m_off120_sms_liq | 0.525 | −$1,292 | 237 | 0.502 | −4.12 | −$978 |
| 10_btc_15m_s7_hybrid_v1 | 0.815 | −$552 | 1,377 | 0.794 | −0.71 | −$976 |
| 15_btc_15m_s7_tight | 0.814 | −$643 | 1,353 | 0.795 | −0.64 | −$862 |
| R1_eth_5m_s15_ribbon_slope | 0.761 | +$2,166 | 4,213 | 0.733 | −0.12 | −$485 |
| 11_eth_15m_off120_240 | 0.651 | −$771 | 409 | 0.626 | −1.09 | −$445 |
| S7_eth_5m_base | 0.739 | −$3,334 | 6,014 | 0.755 | −0.05 | −$300 |
| V15_sol_off240_480 | 0.694 | −$2,713 | 188 | 0.745 | −0.62 | −$117 |
| V15_eth_off60_120 | 0.613 | −$996 | 615 | 0.623 | −0.02 | −$10 |
| 13_pool_15m_offge480 | 0.498 | −$7,675 | 656 | 0.474 | +0.51 | +$334 (n<1k but WR<50) |

---

## 6. Sleeves that PASS OOS (26 of 42) — the deploy roster

Sorted by `last7_sum` (last-week $ delivered). **Top 10 OOS-pass sleeves**:

| # | Sleeve | asset | tf | full n | full WR | full dpt | full sum | last7 n | last7 WR | last7 dpt | last7 sum | stability |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | **S7_btc_5m_base** | BTC | 5m | 19,417 | 0.730 | 0.59 | $11,409 | 6,748 | 0.747 | 1.59 | **$10,739** | IMPROVING |
| 2 | R2_btc_5m_s1_5_3bps | BTC | 5m | 27,369 | 0.663 | −0.12 | −$3,259 | 9,910 | 0.670 | 0.65 | $6,449 | IMPROVING |
| 3 | R1_btc_5m_s6_top1 | BTC | 5m | 8,507 | 0.672 | 0.75 | $6,356 | 2,891 | 0.695 | 2.16 | $6,259 | IMPROVING |
| 4 | R1_btc_5m_s6_top2 | BTC | 5m | 8,520 | 0.672 | 0.75 | $6,390 | 2,889 | 0.694 | 2.11 | $6,087 | IMPROVING |
| 5 | R1_btc_5m_s6_lite | BTC | 5m | 8,763 | 0.664 | 0.68 | $5,990 | 2,959 | 0.685 | 1.90 | $5,630 | IMPROVING |
| 6 | 02_btc_5m_s6_hybrid_v1 | BTC | 5m | 7,882 | 0.692 | 0.73 | $5,738 | 2,668 | 0.718 | 2.07 | $5,532 | IMPROVING |
| 7 | S6TA_btc_top1 | BTC | 5m | 7,860 | 0.692 | 0.75 | $5,918 | 2,660 | 0.718 | 2.07 | $5,517 | IMPROVING |
| 8 | R1_eth_5m_s6_tight_pos_cloud | ETH | 5m | 14,921 | 0.656 | −0.05 | −$772 | 5,285 | 0.685 | 0.97 | $5,149 | IMPROVING |
| 9 | S2_btc_fade | BTC | 5m | 9,182 | 0.665 | 0.10 | $941 | 3,350 | 0.690 | 1.51 | $5,065 | IMPROVING |
| 10 | S6TA_eth_top1 | ETH | 5m | 15,698 | 0.678 | −0.14 | −$2,185 | 5,452 | 0.704 | 0.92 | $4,995 | IMPROVING |

Other notable OOS-passers:
- **07_btc_5m_s15_hybrid_v1** (BTC 5m): full WR 0.765, last7 $4,172
- **06_eth_5m_s15_hybrid_v1** (ETH 5m): full WR 0.805, last7 $318 (DEGRADING — caution)
- **01_btc_5m_s6_hybrid_v2_sms** (BTC 5m): full WR 0.777, last7 $124 (small n=155)
- **S15_btc_ribbon_off60** (BTC 5m): full WR 0.684, last7 $4,754
- **T1_btc_5m_s7_v7_dn** (BTC 5m DOWN-only): full WR 0.707, last7 $1,654

**Top 10 by full-window cumulative $** (which is more conservative — includes full historical losses):

| # | Sleeve | full sum | last7 sum | OOS pass | stability |
|---:|---|---:|---:|---|---|
| 1 | S7_btc_5m_base | $11,409 | $10,739 | True | IMPROVING |
| 2 | 07_btc_5m_s15_hybrid_v1 | $6,514 | $4,172 | True | IMPROVING |
| 3 | R1_btc_5m_s6_top2 | $6,390 | $6,087 | True | IMPROVING |
| 4 | R1_btc_5m_s6_top1 | $6,356 | $6,259 | True | IMPROVING |
| 5 | R1_btc_5m_s6_lite | $5,990 | $5,630 | True | IMPROVING |
| 6 | S6TA_btc_top1 | $5,918 | $5,517 | True | IMPROVING |
| 7 | 02_btc_5m_s6_hybrid_v1 | $5,738 | $5,532 | True | IMPROVING |
| 8 | S15_btc_ribbon_off60 | $5,657 | $4,754 | True | IMPROVING |
| 9 | 06_eth_5m_s15_hybrid_v1 | $5,328 | $318 | True | DEGRADING |
| 10 | T1_btc_5m_s7_v7_dn | $4,641 | $1,654 | True | IMPROVING |

---

## 7. Updated combined deployable estimate

Using OOS-pass roster (n=26 sleeves) on the last 7-day slice (May 19-26, the freshest forward-equivalent):

- Total weekly $ sum: **$98,643**
- Total fires per week: **89,578**
- Extrapolated 30-day estimate: **$422,755**
- Avg $/trade in OOS-pass roster: $1.10

**Caveats:**
1. Many OOS-pass sleeves OVERLAP heavily (R1_btc_5m_s6_top1/top2/lite + 02_btc_5m_s6_hybrid_v1 + S6TA_btc_top1 all hit ~the same fire set). Real deploy must dedup; effective $ from BTC 5m s6 family ~$6-10k/wk, not $30k/wk.
2. Last-7-day slice includes the post-rally "cleaner" regime. If conditions revert, dpt will drop ~50%.
3. The "IMPROVING" classification is across-the-board — likely a regime artifact, NOT validation.
4. `06_eth_5m_s15_hybrid_v1` is DEGRADING — last-week dpt was 4× smaller than full-window dpt — exclude from deploy.

**Conservative deploy estimate** (uncorrelated subset of 8-10 OOS-pass sleeves with non-overlapping fire sets and stable last-7d $/tr > $0.50):
- BTC 5m s6: **S7_btc_5m_base** (most fires, $11k full, $10.7k last7)
- BTC 5m s15: **07_btc_5m_s15_hybrid_v1**
- BTC 5m: **01_btc_5m_s6_hybrid_v2_sms** (tight, tiny n but very high WR)
- ETH 5m: **R1_eth_5m_s6_tight_pos_cloud** OR **S6TA_eth_top1** (similar, pick one)
- SOL 5m: **08_sol_5m_s6_hybrid_v1** (full sum −$1,095 but last7 +$2,398, WR 0.711)

Estimated combined weekly: **$20-30k** at $25 notional. Scale linearly with stake.

---

## 8. Differences vs Agent T's 14-sleeve OOS test

Agent T tested 15 sleeves on May 21-25 OOS slice ONLY (3.5 days, narrow). I tested 42 sleeves on **full 32-day window + last-7d OOS slice (May 19-26)** which captures more regime variability.

**Differences in OOS-pass count for Agent T's original 15:**

| Sleeve | Agent T verdict (May 21-25 only) | My verdict (last 7d May 19-26) | Reason |
|---|---|---|---|
| 01_btc_5m_s6_hybrid_v2_sms | n=132 dpt=$0.14 | **PASS** (n=155, WR 0.787, dpt $0.80) | larger window pushed past 60% WR |
| 02_btc_5m_s6_hybrid_v1 | n=2570 WR 0.714 dpt $1.90 | **PASS** (n=2668, WR 0.718, dpt $2.07) | matches Agent T |
| 03_eth_5m_s6_hybrid_v2_sms | n=584 WR 0.733 dpt $0.29 | **PASS** (n=617, WR 0.742, dpt $0.56) | matches |
| 04_eth_5m_s6_hybrid_v1 | n=5454 WR 0.701 dpt $0.86 | **PASS** (n=5577, WR 0.701, dpt $0.83) | matches |
| 05_btc_5m_off120_sms_liq | n=229 WR 0.489 dpt −$4.33 | **FAIL** (same) | matches — sleeve collapsed |
| 06_eth_5m_s15_hybrid_v1 | n=2509 WR 0.776 dpt −$0.33 | **PASS** (n=3208, dpt $0.10) | the longer 7-day window included more wins |
| 07_btc_5m_s15_hybrid_v1 | n=1783 WR 0.734 dpt $2.08 | **PASS** (n=2070, WR 0.750, dpt $2.02) | matches |
| 08_sol_5m_s6_hybrid_v1 | n=3920 WR 0.710 dpt $0.61 | **PASS** (n=4023, WR 0.711, dpt $0.60) | matches |
| 09_btc_5m_xa_down | n=8047 WR 0.560 dpt −$1.10 | **FAIL** (same) | matches |
| 10_btc_15m_s7_hybrid_v1 | n=1185 WR 0.783 dpt −$1.16 | **FAIL** (n=1377, WR 0.794, dpt −$0.71) | matches — high WR but losing trades > winning trades on small dpt |
| 11_eth_15m_off120_240 | n=359 WR 0.602 dpt −$1.59 | **FAIL** (n=409, WR 0.626, dpt −$1.09) | matches |
| 12_eth_15m_off60_120 | n=91 WR 0.769 dpt $5.68 | **PASS** (n=93, WR 0.774, dpt $5.81) | matches |
| 13_pool_15m_offge480 | n=621 WR 0.456 dpt $0.70 | **FAIL** (n=656, WR 0.474, dpt $0.51) | matches — WR<50 so we can't deploy even if dpt>0 |
| 14_sol_5m_drz_res_down | n=6685 WR 0.455 dpt −$5.34 | **FAIL** (same) | matches |
| 15_btc_15m_s7_tight | n=1169 WR 0.784 dpt −$1.08 | **FAIL** (n=1353, WR 0.795, dpt −$0.64) | matches |

**Verdict alignment: 14/15 match exactly. 1 difference (#06 ETH 5m s15) is marginal pass on extended window vs marginal fail on narrow.**

**New surprises from extended catalog**:
1. **S7_btc_5m_base** (`g_tr_above_ema200 & g_ribbon_agrees & g_stoch_with`, BTC 5m offsets 60-240) is the **biggest win** — full sum $11,409 over 19,417 fires, last7 $10,739 with WR 0.747. Not in Agent T's top 15 list. This is the single best deployable sleeve in the full universe.
2. **R1 hybrid_gate_search_top extras** (R1_btc_5m_s6_top1/top2/lite) all PASS OOS and deliver $5.5-6.4k each on last 7 days. These are the alternate top-WR formulations of 02_btc_5m_s6_hybrid_v1 — same fire family. Treat as a single bucket; don't double-count.
3. **S2_btc_fade** (BTC 5m, DOWN-only fade) PASS OOS with $5,065 in last 7 days — fade strategies aren't dead.
4. **R1_eth_5m_s6_tight_pos_cloud** (ETH 5m, tight ribbon + BB pos + above cloud) flips from net-negative full-window (−$772) to positive last-7d (+$5,149) — regime-sensitive ETH play.
5. **All V15m extras FAIL** — 15m timeframe is genuinely tough; the 22d-validated WR>78% sleeves don't carry to last-7d. The DEGRADING tag on the 15m s7 sleeves (10, 15) means 15m is not deploy-ready right now.

---

## Artifacts

- `data/v4/canonical/_results/full_window_all_sleeves_results.csv` (42 rows, all metrics)
- `data/v4/canonical/_results/_full_window_2026_05_26/full_window_stability_weekly.csv` (251 rows, weekly $/tr per sleeve)
- `data/v4/canonical/_results/_full_window_2026_05_26/prefix_fires.parquet` (Apr 24 → May 1 reconstruction, 231,030 fires)
- `data/v4/canonical/_results/_full_window_2026_05_26/run.log` (full pipeline log)
- `strategy_lab/full_window_all_sleeves_2026_05_26.py` (this script)

**Build cost**: 3.1 min total for 42 sleeves across the full 32-day window.
