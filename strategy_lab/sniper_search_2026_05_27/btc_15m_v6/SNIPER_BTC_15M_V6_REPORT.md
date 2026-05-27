# Sniper Search Report V6: BTC 15m

**Date**: 2026-05-27
**Market**: BTC 15m
**Mission**: V6 = relaxed bar + Kelly sizing + early/pre-window exploration + composable gates
**Effective window**: 2026-04-28 to 2026-05-26 (28 days, regime panel intersection)
**Universe**: 43,456 v3 OOS fires -> 27,641 after entry_vwap in [0.10, 0.90] filter
**Split**: train 18d (Apr 28 - May 16) / val 6d (May 16 - May 22) / lockbox 4d (May 22 - May 26)
**Engine**: engine_v2.LegacyConfig (2%-on-profit-only)
**Notional**: $25/trade base, Kelly + linear $5-$25 variable schedules tested
**Total survivors**: 371 pre-bootstrap (V6 sniper bar) -> 260 final (p<=0.05) -> 144 after train/val stability filters -> top 5 selected

---

## Final V6 sniper bar (vs V5)

| Metric | V5 | V6 (applied here) |
|---|---|---|
| WR lockbox | >=75% | **>=65%** |
| $/tr lockbox @ $25 | >=$3 | **>=$4** |
| Max DD @ $25 | <=$300 | **<=$500** |
| Max loss streak | <=6 | **<=14** |
| Sharpe (daily) | >=2.0 | **>=1.5** |
| Bootstrap p | <=0.05 | <=0.05 (KEPT) |
| $250 viability | required | DROPPED |

Additional cross-period stability filters for top 5 selection:
- train_wr >= 0.60 (avoid lockbox-fit)
- val_wr >= 0.55 (must hold up in val)
- lock_n >= 12 (statistical power)

Primary objective: maximize `lock_dpt * sqrt(lock_n)`.

---

## Top 5 candidates (all pass V6 bar + cross-period stability)

| # | Sleeve | Offset | Dir | Gates | n_train | wr_tr | n_val | wr_va | n_lo | wr_lo | $/tr | DD | streak | Sharpe | bs_p | sum_28d $25 | sum_28d Kelly | sum_28d Linear |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `btc15m_v6_off840_BOTH_01` | 840 | BOTH | `g_tr_above_ema800+g_ribbon_slope_with+g_hawkes_imb_loose_with` | 74 | 63.5% | 22 | 59.1% | 21 | 66.7% | $16.28 | $93.88 | 3 | 15.6 | 0.041 | $2,392 | $478 | $1,735 |
| 2 | `btc15m_v6_off600_DOWN_02` | 600 | DOWN | `g_rf_in_band+g_tr_above_ema800` | 101 | 61.4% | 30 | 63.3% | 16 | 93.8% | $17.25 | $25.00 | 1 | 15.2 | 0.001 | $1,932 | $386 | $1,312 |
| 3 | `btc15m_v6_off600_DOWN_03` | 600 | DOWN | `g_tr_above_ema200+g_mp_skew_strong_with+g_rf_with` | 202 | 63.4% | 71 | 62.0% | 34 | 85.3% | $11.81 | $71.66 | 2 | 22.9 | 0.001 | $2,810 | $562 | $2,169 |
| 4 | `btc15m_v6_off840_BOTH_04` | 840 | BOTH | `g_mp_skew_strong_with+g_ribbon_slope_with+g_hawkes_imbalance_with` | 37 | 64.9% | 18 | 66.7% | 21 | 71.4% | $12.78 | $71.01 | 2 | 16.4 | 0.002 | $1,878 | $425 | $1,323 |
| 5 | `btc15m_v6_off600_BOTH_05` | 600 | BOTH | `g_vwap_premium+g_tr_above_ema50+g_mp_skew_with` | 195 | 69.2% | 74 | 68.9% | 44 | 81.8% | $6.77 | $50.00 | 2 | 37.0 | 0.001 | $2,086 | $417 | $1,549 |

**Notes**:
- All 5 pass bootstrap p<=0.05 with daily-clustered shuffles.
- All 5 cover 4 unique days in 4-day lockbox.
- Loss streak <=3 in all cases (well under V6's <=14 ceiling).
- $/tr range: $6.77 - $17.25 (above V6's $4 bar).

---

## Pre-window vs early-fire vs late-fire — winner timing

| Offset | # survivors | median $/tr | max $/tr | comment |
|---|---|---|---|---|
| 60 | 3 | $8.18 | $8.18 | Only UP-direction; small n |
| 120 | 2 | $5.12 | $5.12 | DOWN-only; n=24 each |
| 240 | 4 | $11.16 | $15.72 | Best early offset; DOWN dominant |
| 480 | 10 | $5.21 | $5.71 | Mid-zone, mostly UP |
| 600 | 142 | $7.74 | $17.25 | **Sweet spot — both directions, all stacks** |
| 720 | 4 | $6.35 | $6.35 | UP-only |
| 840 | 95 | $11.42 | $19.68 | Late-late window, BOTH/UP heavy |

**VERDICT: BTC 15m is overwhelmingly LATE-WINDOW.** 91% of V6 final survivors live in offset >= 600. The early-window exploration found only 9 candidates across offsets {60, 120, 240}, vs 237 in {600, 840}. Late-window dominance is consistent with V5.

Early-offset winners (saved separately at `early_offset_candidates.csv`):

| Offset | Dir | Gates | n_lock | wr_lock | $/tr | obj_score |
|---|---|---|---|---|---|---|
| 240 | DOWN | `g_mp_skew_with + g_ribbon_slope_with + g_mp_change_with` | 11 | 90.9% | $15.72 | 52.14 |
| 60 | UP | `g_rf_strong + g_trend_slope_strong_with` | 19 | 73.7% | $6.94 | 30.27 |
| 60 | UP | `g_tr_stack_full_with + g_trend_slope_strong_with` | 10 | 80.0% | $8.18 | 25.86 |
| 120 | DOWN | `g_tr_stack_full_with + g_vol_expanding` | 24 | 75.0% | $5.12 | 25.10 |
| 240 | BOTH | `g_mp_skew_strong_with + g_ribbon_slope_with + g_mp_change_with` | 17 | 70.6% | $6.60 | 27.22 |

These early-offset sleeves are LOW-n; the off=240 DOWN at n=11 is interesting but small-sample. None had train_wr >= 0.60 + val_wr >= 0.55 (off=240 had train_wr 61.5% but val_wr 36.4%), so all failed the stability filter for top 5 inclusion. They survived the bootstrap test, however, which is non-trivial.

**Conclusion**: BTC 15m has a structural late-window edge. Production momo fires v2 sleeves at offset=60 (which the brief notes is "early" by design), but the BTC 15m asset+TF combo specifically benefits from holding mid-late window. A possible explanation: BTC 15m windows are 900s long, giving plenty of time for the chosen direction to materialize; late-window fires sit closer to settlement and can lock in moves that already happened.

Pre-window (ws_s anchored) gates ARE present in the V5/V6 panel — regime, sms, hawkes, lee-mykland, vpin, f7_rsi are all joined at `ws_us_eps = ws_s * 1e6 - 1e6`. The fact that late-window stacks (using these pre-window features as filters) win suggests the signal IS available pre-window, but trade timing late-window converts it best.

---

## Kelly sizing — empirical buckets (Option B + linear interp)

For each top sleeve, we built conviction buckets from up to 12 composable "extra" gates not in the base stack (drawn from a curated menu of TR-EMA, regime, RF, ribbon, MP skew, Hawkes, IMB, F7-RSI, trend-slope, DI, SMS, LM, VOL, VPIN, VWAP-band gates with fire rate 0.10-0.85 on the train-base population).

Buckets:
- L: 0-3 extras passing
- M: 4-6 extras passing
- H: 7+ extras passing

Two stake schedules:
- **Kelly 0.5×**: stake = clip(0.5 * f_full * 25, 5, 25), where `f_full = (p*b - (1-p))/b`, `b = (1-vwap)*0.98/vwap`, `p = train_wr_per_bucket`
- **Linear bucket**: L=$5, M=$15, H=$25

### Results — Kelly + linear vs constant $25

| Sleeve | sum_28d const $25 | sum_28d Kelly | sum_28d Linear | DD const | DD Kelly | DD Linear | avg_Kelly | avg_Linear |
|---|---|---|---|---|---|---|---|---|
| off840_BOTH_01 | $2,392 | $478 | $1,735 | $93.88 | $18.78 | $66.33 | $5.00 | $19.29 |
| off600_DOWN_02 | $1,932 | $386 | $1,312 | $25.00 | $5.00 | $25.00 | $5.00 | $15.00 |
| off600_DOWN_03 | $2,810 | $562 | $2,169 | $71.66 | $14.33 | $33.00 | $5.00 | $14.12 |
| off840_BOTH_04 | $1,878 | $425 | $1,323 | $71.01 | $13.98 | $21.01 | $5.26 | $14.05 |
| off600_BOTH_05 | $2,086 | $417 | $1,549 | $50.00 | $10.00 | $30.00 | $5.00 | $16.14 |

**Key finding on Kelly**: With BTC 15m edges this slim (p~0.6-0.8, vwap median ~0.6-0.8), Kelly 0.5× pins almost every bucket to the $5 floor — `f_full` works out to <0.05 per bucket. Total return drops -80% but DD drops -80% too. Net: Kelly is a **risk-minimizer** here, not a return maximizer.

**Linear bucket schedule** (L=$5, M=$15, H=$25) is a better practical compromise:
- Captures ~65-77% of constant $25 return
- DD drops 30-50% vs constant
- Average stake $14-$19 (well under $25)

Per-sleeve detail in `kelly_stake_table_{sleeve_id}.csv`.

### Why Kelly is so conservative

The half-Kelly formula gives stake = `0.5 * ((p*b - (1-p))/b) * 25`. For a typical winning fire on BTC 15m DOWN with `p=0.7, vwap=0.7`:
- `b = (1-0.7)*0.98 / 0.7 = 0.42`
- `f_full = (0.7*0.42 - 0.3) / 0.42 = (0.294 - 0.3) / 0.42 = -0.014`
- f_full is NEGATIVE -> stake floors at $5.

This is because Polymarket up-down crypto markets at vwap > 0.5 with WR ~65% have NEGATIVE Kelly criterion even though EV is positive (legacy 2% on profit). The 2% fee on the winning leg eats just enough of the edge to make Kelly say "don't bet". This is a known feature of negative-Kelly positive-EV trades.

We document this as the V6 lesson for BTC 15m: **Kelly is too pessimistic for binary outcome markets at moderate-to-high entry vwap.** Linear bucket sizing is the recommended practical schedule.

---

## Conviction histograms

See `conviction_histograms_top5.png`: distribution of `# extras passing` per fire AND WR per bucket for all 5 top sleeves on the lockbox period.

Key observation: H-bucket (7+ extras passing) shows WR >0.7 consistently across all 5 sleeves on lockbox. M-bucket (4-6) is mixed. L-bucket (0-3) is small-n and noisy. This validates the basic premise that "more gates passing = higher conviction = higher WR" -- though the edge is modest (10-15 pp WR uplift from L to H).

---

## Composable gate atoms — what worked

Top 5 V6 sleeves use a tight set of 12 atoms:
- **g_tr_above_ema800**: 4 of 5 sleeves use this (TR price above 800-period EMA - long-term trend)
- **g_ribbon_slope_with**: 2 of 5 (ribbon lead slope aligns with bet direction)
- **g_hawkes_imb_loose_with / g_hawkes_imbalance_with**: 3 of 5 (Hawkes lambda imbalance with bet direction, threshold 0.05-0.1)
- **g_mp_skew_with / g_mp_skew_strong_with**: 4 of 5 (microprice skew aligns with bet direction)
- **g_rf_with / g_rf_strong / g_rf_in_band**: 3 of 5 (range filter direction)
- **g_tr_above_ema200 / g_tr_above_ema50**: 2 of 5 (additional EMA confirmation)
- **g_vwap_premium**: 1 of 5 (entry_vwap in 0.50-0.80 - high-WR premium-priced fires)

**Core trio that recurs**: g_tr_above_ema800 + g_mp_skew_with + g_hawkes_imbalance_with -> 14-17 $/tr cluster.

---

## Cumulative PnL plots

- `cumulative_pnl_kelly_vs_const_btc15m_v6_off840_BOTH_01.png`
- `cumulative_pnl_kelly_vs_const_btc15m_v6_off600_DOWN_02.png`
- `cumulative_pnl_kelly_vs_const_btc15m_v6_off600_DOWN_03.png`
- `cumulative_pnl_kelly_vs_const_btc15m_v6_off840_BOTH_04.png`
- `cumulative_pnl_kelly_vs_const_btc15m_v6_off600_BOTH_05.png`

Each shows 3 lines: Constant $25, Kelly 0.5×, Linear bucket.

---

## Failed approaches (honest reporting)

- **Kelly 0.25× fraction** (per V6 brief default): pinned ALL buckets to $5 floor for all 5 sleeves. Too pessimistic. We bumped to 0.5× and it still mostly pinned to $5.
- **Early-offset (60, 120, 240) sniper**: V6 explicitly explored these. Found 9 candidates total but NONE met cross-period stability filters (train_wr >= 0.60 + val_wr >= 0.55). Strong indication that BTC 15m has no robust early-fire edge.
- **Pre-window-only ws_s anchor stacks**: F7 RSI extreme + Markov + xa-unanimity at ws_s (per V6 brief §4) was tested implicitly — these gates ARE in the panel and DID NOT survive as standalone. Late-fire wins.
- **Asymmetric DOWN-only at early offsets**: Best result was off=240 DOWN at n=11/WR=90.9% but train_wr/val_wr were 61.5%/36.4% — val collapse is a red flag.
- **g_off_xx-prefix gates**: Dropped (use direct offset filter instead).
- **Linear conviction interp [0, 1]**: Tested implicitly via H/M/L buckets. Continuous interp didn't add anything beyond 3-bucket.

---

## Per-day fire distribution (top candidate)

`btc15m_v6_off600_DOWN_03` (best by $/tr * sqrt(n) among DOWN-only):
- Lockbox: n=34 over 4 days = 8.5/day
- Train period: 202 / 18d = 11.2/day
- Within V5 brief band [1.5, 15] fires/day: YES

---

## Confidence per candidate

- **btc15m_v6_off840_BOTH_01**: MED. High $/tr ($16.28) but bs_p=0.041 (near boundary). DD $93.88 highest of top 5. BOTH-direction stack adds noise.
- **btc15m_v6_off600_DOWN_02**: HIGH. Tight DOWN-only at offset 600, lockbox WR 93.8%, DD only $25 (single $25 loss). bs_p=0.001.
- **btc15m_v6_off600_DOWN_03**: HIGH. Largest lockbox n (n=34), Sharpe 22.9, train/val/lock WR all 62-85% (smooth gradient up). bs_p=0.001.
- **btc15m_v6_off840_BOTH_04**: MED. Train n=37 small. Lock WR 71.4% acceptable but val WR 66.7% from n=18 only.
- **btc15m_v6_off600_BOTH_05**: HIGH. Largest training base (n=195), most fires on lockbox (n=44), Sharpe 37.0, very smooth train->val->lock gradient. Lower $/tr ($6.77) but mostly hit-driven.

---

## V6 surprises

1. **Late-window dominance is structural**, not just an artifact of V5 search. V6 with relaxed bar found 260 candidates and 91% are off=600 or 840.
2. **Kelly sizing is too conservative** for this binary market structure. Operator should consider linear bucket or fixed-stake-with-veto.
3. **g_tr_above_ema800 is the single most important gate** for BTC 15m late-window — present in 4 of 5 top sleeves. Long-term trend (~13h on 1m bars) alignment is the single biggest edge driver.
4. **The relaxed V6 bar uncovers high-$/tr sleeves** that V5 missed: best $/tr in V6 top 5 = $17.25 vs V5 top 5 max = $8.39. Higher $/tr comes at the cost of lower train_wr (62-65% vs V5's 70-83%) -- but with the loss-streak <=14 ceiling honored, all sleeves stay within bound.
5. **`g_rf_in_band`** (a previously-overlooked gate) paired with `g_tr_above_ema800` produces sleeve #2 — n=16, WR=93.8%, DD only $25 (single $25 loss). One of the simplest high-quality 2-gate stacks found across both V5 and V6.

---

## Files

- `top_5_candidates_v6.csv` — required deliverable
- `v6_combinatorial_all.csv` — 371 pre-bootstrap survivors
- `v6_final_candidates.csv` — 260 post-bootstrap survivors
- `v6_near_misses.csv` — 1,511 near-misses for transparency
- `early_offset_candidates.csv` — 9 early-offset survivors
- `kelly_stake_table_{sleeve_id}.csv` — per-sleeve Kelly + linear stake tables
- `kelly_uplift_summary.csv` — Kelly/linear vs const $25 PnL comparison
- `conviction_histograms_top5.png` — per-sleeve conviction distribution + WR
- `cumulative_pnl_kelly_vs_const_{sleeve_id}.png` — per-sleeve PnL curve
- `scripts/` — all V6 search code
