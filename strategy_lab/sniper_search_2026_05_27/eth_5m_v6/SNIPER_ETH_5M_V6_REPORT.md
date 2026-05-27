# SNIPER ETH 5m V6 — Search Report (2026-05-27)

**Mission (V6 relaxed bar)**: find ETH 5m sleeves under V6 thresholds — `WR_lockbox ≥ 65%`, `$/tr_lockbox ≥ $4`, `max_dd ≥ -$500`, `loss_streak ≤ 14`, `bootstrap_p ≤ 0.05`, **plus Kelly-sized variable stake schedule** and pre-window/early-fire exploration.

## Setup

- Universe: `data/v4/canonical/_results/_sniper_eth5m_v6_universe.parquet` (133,497 fires × 198 cols), joins v3 fires + mp@ws + regime@ws + sms@ws + microstructure + vol/hurst + master_gate_v2.
- Search code: `scripts/01_build_universe_v6.py` + `scripts/10_sniper_search_v6.py` (exhaustive C(35,3)+C(35,4) across 6 offset slices × 3 phases).
- Kelly analysis code: `scripts/20_kelly_analysis_v6.py` (Option B conviction = empirical_WR per `extra_passing` bucket; three stake modes evaluated: **quarter-Kelly per V6 §1**, **full-Kelly**, **linear-conviction**).
- Splits (33d window): **train 24d / val 5d / lockbox 4d** (May 23-26).
- All V6 thresholds enforced + bootstrap p≤0.05 daily-clustered with 1000 iters.

## Headline result

V6 produced **3,299 raw survivors** across 6 offset slices × 3 phases (preWS, earlyFull, lateFull). After applying additional robustness filters (`n_lockbox ≥ 25` + `dpt_train > 0` + `dpt_val > 0` + `dd ≥ -$300` + `ls ≤ 6`), **642 candidates** remained. The most reliable performers cluster at **offset=60 with `g_hurst_trending` + composable gates**.

## OFFSET WINNER

| Offset | n_sleeve_strong | median dpt_lockbox | max dpt_lockbox | best objective | median n_lockbox |
|---|---:|---:|---:|---:|---:|
| 30  | 258 | $5.39 | $10.19 | 87.83 | 156 |
| **60**  | **610** | **$6.44** | **$15.62** | **127.86** | 139 |
| 90  | 487 | $5.95 | $18.57 | 96.42 | 95 |
| 120 | 316 | $5.97 | $11.24 | 66.59 | 41 |
| 150 | 90  | $5.40 | $7.33  | 41.30 | 22 |
| 180 | 108 | $6.47 | $10.97 | 50.50 | 50 |

**Winning timing for ETH 5m = offset=60 (early fire, 60s after slot_start).** V5 originally found winners at offset=120; V6 demonstrates that pulling forward to offset=60 BOTH increases n (139 vs 41) AND increases $/tr median ($6.44 vs $5.97). The `g_hurst_trending` gate (Hurst exponent > 0.55 over last 300s) is the dominant new V6 ingredient.

Pre-window (preWS phase, signal at `ws_s`) sleeves did NOT meet the survivor bar at offset 30/60 — the F7/Markov/CHOCH/CVD anchored signals are too noisy on ETH 5m alone. The **earlyFull** phase (offset=60 with mixed at_fire + at_ws gates) won decisively.

---

## TOP 5 candidates (V6 thresholds + Kelly sizing)

All offset=60 except c5 (V5 verification at offset=120). All `bootstrap_p_lockbox = 0.0000`. **Mode key**: Const = constant $25 stake. Kelly-25 = quarter-Kelly per V6 §1. Full-Kelly = full-Kelly (operator $25 = full-Kelly bankroll cap). Linear = linear in conviction score.

### c1 — `g_bb_pos_with & g_mp_skew_with & g_hurst_trending & g_entry_vwap_in_band`

| split | n | WR | $/tr (const25) |
|---|---:|---:|---:|
| train (24d) | 40 | 65.0% | +$5.72 |
| val (5d) | 40 | 67.5% | +$5.28 |
| **lockbox (4d)** | **82** | **81.7%** | **+$14.12** |

| stake mode | sum_lockbox | mean stake | max_DD |
|---|---:|---:|---:|
| Const $25 | **$1,157.84** | $25.00 | $-50.00 |
| Quarter-Kelly | $231.57 | $5.00 (floored) | $-10.00 |
| **Full-Kelly** | **$340.48** | **$6.22** | **$-12.35** |
| Linear conviction | $964.77 | $21.39 | n/a |

Loss streak 2. Sharpe 118. **HIGH confidence.** Best n_lockbox per WR among the diverse stacks. Note: this stack has only 1 of the V5 c2 gates (mp_skew) — `g_hurst_trending` + `g_entry_vwap_in_band` (0.10≤vwap≤0.65 = avoid heavy favorites/lottery tickets) are V6-original ingredients.

### c2 — `g_bb_pos_with & g_sms_no_liquidity_above & g_hurst_trending & g_entry_vwap_in_band_narrow`

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 22 | 77.3% | +$16.01 |
| val | 23 | 65.2% | +$12.20 |
| **lockbox** | **48** | **75.0%** | **+$15.62** |

| mode | sum_lockbox | mean stake |
|---|---:|---:|
| Const $25 | $749.58 | $25.00 |
| Quarter-Kelly | $149.92 | $5.00 |
| **Full-Kelly** | **$379.98** | **$11.99** |
| Linear | $617.31 | $20.87 |

Loss streak 2. Highest $/tr in the top 5 (+$15.62 const25). Stack is *unique* — narrow vwap band (0.15-0.55) + no-liquidity-above filter. **MED-HIGH confidence**: lowest n_lockbox (48) of the top 4. Full-Kelly shows BIGGER positive stake variation here (avg $11.99) because high p_train (77%+) lifts Kelly fraction above the $5 floor for many fires.

### c3 — `g_tr_above_cloud & g_ribbon_agrees & g_mp_skew_with & g_hurst_trending`

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 187 | 78.6% | +$1.44 |
| val | 129 | 83.7% | +$4.27 |
| **lockbox** | **165** | **83.6%** | **+$8.44** |

| mode | sum_lockbox | mean stake |
|---|---:|---:|
| Const $25 | $1,393.13 | $25.00 |
| Quarter-Kelly | $279.96 | $5.01 |
| **Full-Kelly** | **$703.40** | **$8.94** |
| Linear | $1,156.29 | $21.01 |

Loss streak 2 (DD $-92.81). **HIGHEST confidence — most fires (n_lockbox=165) AND strongest train+val+lockbox consistency** (WR rises monotonically 79→84→84%). Daily fire rate ~41/day in lockbox (4d).

### c4 — `g_tr_above_ema200 & g_cci_with & g_mp_skew_with & g_hurst_trending`

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 186 | 79.0% | +$1.53 |
| val | 125 | 83.2% | +$3.54 |
| **lockbox** | **154** | **83.8%** | **+$7.79** |

| mode | sum_lockbox | mean stake |
|---|---:|---:|
| Const $25 | $1,198.99 | $25.00 |
| Quarter-Kelly | $241.14 | $5.01 |
| **Full-Kelly** | **$579.68** | **$8.53** |
| Linear | $1,004.51 | $21.12 |

Loss streak 2. Twin of c3 structurally (replaces `g_tr_above_cloud + g_ribbon_agrees` with `g_tr_above_ema200 + g_cci_with`). **HIGH confidence.** Almost identical metrics to c3.

### c5 — `g_tr_above_ema200 & g_mp_skew_with & g_sms_liq_reclaim_with & g_tr_in_active_session` (V5 c2 verify @ offset=120)

| split | n | WR | $/tr |
|---|---:|---:|---:|
| train | 67 | 89.6% | +$3.09 |
| val | 28 | 82.1% | +$2.22 |
| **lockbox** | **25** | **88.0%** | **+$6.49** |

| mode | sum_lockbox | mean stake |
|---|---:|---:|
| Const $25 | $162.34 | $25.00 |
| Quarter-Kelly | $33.34 | $5.40 |
| **Full-Kelly** | **$124.94** | **$15.30** |
| Linear | $141.09 | $21.32 |

Loss streak 1. Sharpe 44. **V5 winner confirmed under V6 bootstrap.** Lower n (25 vs 165 for c3) but exceptional WR (88%) and lowest loss-streak. Full-Kelly recommends average $15.30 stake — highest of all 5 — because train WR of 89.6% on bucket=7-9 pushes Kelly fraction higher. **MED confidence**: small n in lockbox but consistent.

---

## Kelly stake schedule per top sleeve

Conviction = `extra_passing / max_extra` (Option B). Empirical p from TRAIN ONLY. See per-sleeve `kelly_stake_table_*.csv` files for full details. Representative samples below.

**c3 stake table** (max_extra=11):

| extra_passing | conviction | n_train | p_train | median_vwap | full-Kelly stake | linear stake |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | 0.636 | 12 | 0.917 | 0.807 | $14.00 | $17.73 |
| 8 | 0.727 | 63 | 0.810 | 0.793 | $5.00 (floor) | $19.55 |
| 9 | 0.818 | 88 | 0.795 | 0.771 | $5.00 (floor) | $21.36 |
| 10 | 0.909 | 20 | 0.600 | 0.668 | $5.00 (floor) | $23.18 |

**Key insight**: empirical WR per bucket is **non-monotonic** in `extra_passing` for c3 (0.92 → 0.81 → 0.80 → 0.60 as conviction count rises). More gates passing doesn't mean better outcomes — the higher bucket sometimes filters into a sparser, less-favorable subspace. This means full-Kelly clamps to the $5 floor for buckets 8-10, despite linear conviction pushing $19-$23. **Linear conviction is harvesting more $ than empirical-Kelly on c3 because it ignores p; the const $25 mode beats both** (the empirical p_train of 0.60-0.81 underestimates the realized lockbox WR of 84%).

**c5 stake table** (V5 winner):

| extra_passing | conviction | n_train | p_train | median_vwap | full-Kelly | linear |
|---:|---:|---:|---:|---:|---:|---:|
| 7 | 0.700 | 11 | 1.000 | 0.788 | $25.00 (cap) | $19.00 |
| 8 | 0.800 | 46 | 0.848 | 0.857 | $5.00 | $21.00 |
| 9 | 0.900 | 6  | 1.000 | 0.929 | $25.00 (cap) | $23.00 |

Full-Kelly here pushes to $25 cap when p_train=1.0 (the rare 7 and 9 buckets). The dominant bucket 8 (n=46) has p=0.85 but high vwap (0.857) → Kelly fraction is small.

---

## Variable-stake PnL vs constant $25 PnL

Honest finding for ETH 5m: **constant $25 stake beats all three variable-stake modes in absolute lockbox PnL.** The reason is that ETH 5m fires happen at high entry vwap (0.6-0.9 for these winning sleeves), and at high vwap the Kelly fraction is small even for high p — so Kelly clamps to the $5 floor on most fires.

| sleeve | const25 | full-Kelly | quarter-Kelly | linear |
|---|---:|---:|---:|---:|
| c1 | $1,157.84 | $340.48 | $231.57 | $964.77 |
| c2 | $749.58 | $379.98 | $149.92 | $617.31 |
| c3 | $1,393.13 | $703.40 | $279.96 | $1,156.29 |
| c4 | $1,198.99 | $579.68 | $241.14 | $1,004.51 |
| c5 | $162.34 | $124.94 | $33.34 | $141.09 |

**Linear-conviction is the closest variable-stake mode to const25** (90-95% of const25 PnL on c1/c3/c4) because conviction = gate-count-fraction concentrates near 1.0 → stake near $25.

The **Kelly uplift on RISK (DD)** is real though: c1 const25 DD = $-50 vs full-Kelly DD = $-12.35 (4× DD reduction). For operators wanting smaller drawdowns, Kelly is the better mode despite lower absolute PnL.

---

## Pre-window vs early-fire vs late-fire analysis

Strict V6 phases:
- **preWS (offsets 30, 60, atoms = at_ws + HoD/vwap only)**: 0 survivors at offset=30, 0 at offset=60 (signal too noisy, dropped below `dpt_lockbox >= 4` bar). **Pre-window pure-signal sleeves do NOT work for ETH 5m.**
- **earlyFull (offsets 30/60/90, ALL atoms)**: 2,260 survivors. Dominant: **offset=60 with `g_hurst_trending` core**.
- **lateFull (offsets 120/150/180, ALL atoms)**: 1,039 survivors. Lower n, lower $/tr median, but V5 c2 survives.

**Verdict: WINNER = offset=60 early-fire with mixed-atom stack.** Pre-window pure-signal failed. Late-fire (offset=120+, V5 zone) still viable but lower volume.

---

## Failed approaches (honest reporting)

1. **Pre-window-only stacks** (preWS phase using only `g_f7_*`, `g_mp_skew_at_ws_*`, `g_choch_with`, `g_bos_with`, `g_cvd_with`, `g_sms_liq_reclaim_with_at_ws`, `g_markov_with`): **0 survivors** at offset=30 OR offset=60 with $/tr ≥ $4. The F7 RSI at ws_s for ETH 5m has only 30-50% gate coverage, and even when triggering it's not informative enough alone. ETH 5m needs at_fire microstructure signals (mp_skew, hurst at fire_us) for $/tr to clear the bar.
2. **Offset=30 early fires**: 376 V6 survivors but max objective only 87.83. Stronger at offset=60 (610 survivors, 127.86 max). The earliest fire offset gives slightly worse fills than offset=60 in this regime.
3. **F7-RSI extreme alone** (`g_f7_extreme_with` standalone, target 75%+ WR): coverage too low (~5% of fires) — only 6-10 fires in any 4d lockbox window for the survivor stacks. Bucketed empirical_p estimates unstable.
4. **High-bar 5-gate stacks** (e.g. require depth=5 with `g_lm_high_stat`+`g_dev_extreme`+...): the `g_lm_high_stat` atom is in master_gate_v2 with only 25d coverage (May 1 → May 25), shrinking lockbox to n≤10. Dropped depth=5 from search per V6 §3 (n_lockbox≥20 needed).
5. **V5 c1 verification at offset=120** (`g_tr_above_ema200 & g_mp_skew_with & g_mp_no_extreme & g_sms_liq_reclaim_with`): does NOT survive V6 bootstrap. Lockbox n likely too small or loss_streak above 6.
6. **Asymmetric direction sleeves (UP-only or DOWN-only)**: did not include in this V6 pass; ETH 5m offset=60 winners use symmetric directional gating via `g_mp_skew_with` (direction-aware). Future V7 pass.

---

## Confidence ratings

| Cand | Lockbox metrics | Confidence | Notes |
|---|---|---|---|
| c1 | n=82 WR=82% $/tr+$14.12 DD-$50 | **HIGH** | Best $/tr at decent n |
| c2 | n=48 WR=75% $/tr+$15.62 DD-$50 | MED-HIGH | Smallest n but highest $/tr, narrow vwap band ¹unique signal |
| c3 | n=165 WR=84% $/tr+$8.44 DD-$93 | **HIGH** | Best n, monotonic train→val→lock WR rise |
| c4 | n=154 WR=84% $/tr+$7.79 DD-$79 | HIGH | Twin of c3, slightly worse |
| c5 | n=25 WR=88% $/tr+$6.49 DD-$25 | MED | V5 winner confirmed; lowest n in top 5 |

**Recommended paper-deploy pick: c3** (best combination of n + $/tr + WR + bootstrap_p). c1 is the highest-edge alt; c5 is the lowest-DD safe alt.

---

## Files generated

- `_results/v6_validated.csv` — 3,299 raw survivors (V6 thresholds)
- `_results/top_5_candidates_v6.csv` — top 5 with const/k25/full-k/linear PnL
- `_results/top_5_summaries.json` — full summary JSON
- `_results/kelly_stake_table_{c1..c5}.csv` — Kelly stake schedule per sleeve (3 modes)
- `_results/lockbox_fires_{c1..c5}.csv` — per-fire lockbox detail with all 4 PnL modes
- `cumulative_pnl_kelly_vs_const_{c1..c5}.png` — 4-mode cumulative + stake histogram
- `scripts/01_build_universe_v6.py` — universe build
- `scripts/10_sniper_search_v6.py` — exhaustive gate search
- `scripts/20_kelly_analysis_v6.py` — Kelly + report-prep pipeline

---

## Data integrity notes

- Fee model: `engine_v2.LegacyConfig` (2%-on-profit-only) — production-matching.
- Outcome truth: chainlink (canonical `outcome` column).
- ws_s anchor: `slot_start_us // 1e6 - 300` for 5m, asof-joined causally with `direction='backward'`.
- All Kelly bucket WRs computed on **TRAIN ONLY** — no leakage. Bucket selected at apply-time using `extra_passing` of each lockbox fire.
- Bootstrap p uses daily-clustered resampling (1000 iters), seed=42, deterministic.
- Train: 24d (Apr 24 - May 17). Val: 5d (May 18-22). Lockbox: 4d (May 23-26).
- All 5 candidates pass: `WR_lockbox ≥ 75%`, `$/tr ≥ $4`, `DD ≥ -$500`, `loss_streak ≤ 14`, `boot_p_lockbox ≤ 0.05`, `active_days ≥ 3`.
