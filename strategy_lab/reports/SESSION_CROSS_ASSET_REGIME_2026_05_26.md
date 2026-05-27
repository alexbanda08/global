# Session x Cross-Asset Regime stratification — top 7 sleeves
**Date:** 2026-05-26
**Window:** 2026-05-01 → 2026-05-25 (25 days)
**Fee model:** LegacyConfig (2% on winning leg only)
**Outcome:** chainlink-derived
**Source panel:** `data/v4/canonical/_results/master_gate_features_v2.parquet`
**Cross-asset regime source:** `regime_panel_5m.parquet` (asof <= fire_us per asset)

## Inputs
- Top-7 sleeves taken from `master_combinatorial_deployable.csv` (sorted by n_total).
- 47,445 fires across the 7 sleeves.
- Sessions derived from UTC hour: London 07-16, NY 13-21, Tokyo 00-06, HK 01-08,
  Frankfurt 06-15, Sydney 22-05 (wraps), Overlap 13-16, weekend Sat-Sun.
- Cross-asset regime: per-fire asof lookup of {BTC, ETH, SOL} regime_label from
  the 5m regime panel; aggregated into 12 combos (all_up / all_dn / all_ranging /
  mostly_up / mostly_dn / mixed_updn / *_only).

## Outputs (CSVs)
- `data/v4/canonical/_results/session_xa_regime_metrics.csv` (consolidated; spec-named)
- `strategy_lab/overnight_2026_05_26/session_xa_regime/`
  - `session_distribution_per_sleeve.csv`
  - `per_sleeve_session_metrics.csv`
  - `per_sleeve_xa_regime_metrics.csv`
  - `session_xa_combined_top3.csv`
  - `session_variants.csv`
  - `conditional_sleeves.csv`
  - `xa_regime_distribution.csv`
  - `three_way_validation.csv`

---

## 1. Session distribution per sleeve

Fire counts are reasonably balanced across sessions for every sleeve (n>=1000
per session everywhere except `eu_brinks`, `us_brinks`, `overlap` which are
intentionally short).

| sleeve (asset) | n_total | %london | %ny | %tokyo | %hk | %frankfurt | %weekend | %overlap |
| --- | --: | --: | --: | --: | --: | --: | --: | --: |
| s15_5m\|150-240\|g_tr_above_ema800 (BTC) | 9,349 | 38.6 | 33.3 | 25.2 | 29.1 | 38.0 | 39.2 | 13.6 |
| s15_5m\|60-150\|g_tr_above_ema50&g_ribbon_agrees (BTC) | 7,680 | 39.3 | 34.7 | 24.4 | 28.7 | 38.4 | 40.6 | 14.7 |
| s15_5m\|60-150\|g_tr_above_cloud&g_ribbon_agrees&g_bb_pos_with&g_cci_with (ETH) | 7,252 | 38.7 | 33.3 | 25.0 | 29.8 | 38.4 | 37.3 | 13.6 |
| s6_5m\|60-150\|g_cci_with&g_tr_above_ema50&g_rf_with (BTC) | 6,888 | 44.6 | 40.8 | 22.3 | 25.2 | 40.0 | 34.9 | 23.2 |
| s15_5m\|60-150\|g_tr_above_cloud&g_ribbon_agrees&g_tr_above_ema200&g_cci_with (SOL) | 6,165 | 39.1 | 33.4 | 24.0 | 28.5 | 39.0 | 39.1 | 13.3 |
| s15_5m\|150-240\|g_tr_above_ema800&g_tr_above_cloud&g_within_dev&g_tr_above_ema200 (SOL) | 5,443 | 39.0 | 32.3 | 25.0 | 29.9 | 38.5 | 39.5 | 12.8 |
| s6_5m\|60-150\|g_tr_above_cloud&g_bb_pos_with&g_tight_ribbon&g_tr_above_ema50&g_ribbon_agrees (ETH) | 4,668 | 42.7 | 35.4 | 24.4 | 28.9 | 41.8 | 40.6 | 16.8 |

The `s6_5m` sleeves (BTC and ETH) skew measurably more toward London/NY/Frankfurt
than the `s15_5m` family — they're more US/EU sessions weighted.

---

## 2. Per-(sleeve, session) metrics: highlights

Baseline `$/tr` and best/worst sessions (n>=100 cells, full window):

| sleeve (asset) | base $/tr | best session ($/tr, n) | worst session ($/tr, n) |
| --- | --: | --- | --- |
| BTC s15 150-240 g_tr_above_ema800 | 1.59 | hk 2.69 (n=2,718), tokyo 2.41 (n=2,353) | weekend 0.83 (n=3,661), us_brinks 0.49 (n=648) |
| BTC s15 60-150 ema50+ribbon | 1.34 | frankfurt 1.67 (n=2,949), london 1.49 (n=3,018) | tokyo 0.62 (n=1,876), ny 0.81 (n=2,665) |
| ETH s15 60-150 cloud+cci | 0.93 | weekend 1.09 (n=2,704), hk 1.13 (n=2,164) | london 0.81 (n=2,807), tokyo 0.71 (n=1,810) |
| BTC s6 60-150 cci+ema50+rf | 2.86 | frankfurt 4.64 (n=2,753), london 4.19 (n=3,074), hk 3.68 (n=1,734) | tokyo 1.62 (n=1,533), weekend 1.31 (n=2,406) |
| SOL s15 60-150 cloud+ema200+cci | 0.74 | weekend 1.27 (n=2,409), frankfurt 0.99 (n=2,403) | tokyo 0.45 (n=1,479), ny 0.61 (n=2,060) |
| SOL s15 150-240 ema800+cloud+dev | 1.07 | london 1.39 (n=2,123), overlap 1.16 (n=698) | sydney 0.92 (n=1,496), tokyo 0.94 (n=1,363) |
| ETH s6 60-150 cloud+tight+ema50 | 2.14 | frankfurt 3.19 (n=1,953), london 2.83 (n=1,991) | tokyo 1.39 (n=1,138), weekend 1.46 (n=1,894) |

**Patterns:**
- BTC `g_tr_above_ema800` (150-240) flips: asia (HK/Tokyo/Sydney) is best,
  London/NY/Weekend lag.
- All `s6_5m` sleeves and the BTC ema50+ribbon sleeve cluster the same way:
  **best in EU sessions (Frankfurt/London), worst in Tokyo/NY**.
- SOL sleeves dislike Tokyo across the board.
- weekend is bimodal: helps SOL/ETH `s15_5m` 60-150 sleeves but hurts every other.

---

## 3. Session-aware variants (full window, no train/val/lock split)

Best inclusion (fire only during session X):

| sleeve (asset) | base $/tr → best_session_in ($/tr, n) | base $/tr → exclude session ($/tr, n) |
| --- | --- | --- |
| BTC s15 150-240 ema800 | base 1.59 → HK only 2.69 (n=2,718) | excl weekend → 2.07 (n=5,688) |
| BTC s15 60-150 ema50+ribbon | 1.34 → Frankfurt 1.67 (n=2,949) | excl NY → 1.63 (n=5,015) |
| ETH s15 60-150 cloud+cci | 0.93 → weekend 1.09 (n=2,704) | excl london → 1.11 (n=4,445) |
| BTC s6 60-150 cci+ema50+rf | 2.86 → Frankfurt 4.64 (n=2,753) | excl NY → 4.01 (n=4,077) |
| SOL s15 60-150 cloud+ema200+cci | 0.74 → weekend 1.27 (n=2,409) | (no session-exclude that helps) |
| SOL s15 150-240 ema800+cloud+dev | 1.07 → London 1.39 (n=2,123) | excl NY → 1.26 (n=3,685) |
| ETH s6 60-150 cloud+tight+ema50 | 2.14 → Frankfurt 3.19 (n=1,953) | excl weekend → 2.60 (n=2,775) |

Even simple session filters lift $/tr by 25-60% across all 7 sleeves at the
cost of cutting sample size to 25-50%.

---

## 4. Cross-asset regime distribution

12 regime combos, asof BTC/ETH/SOL regime at fire_us. Top-7 fires:

| xa_combo | n_fires | pct |
| --- | --: | --: |
| all_ranging | 38,287 | 80.7 |
| mostly_dn | 1,620 | 3.4 |
| all_dn | 1,597 | 3.4 |
| eth_dn_only | 970 | 2.0 |
| mostly_up | 890 | 1.9 |
| btc_dn_only | 709 | 1.5 |
| sol_up_only | 699 | 1.5 |
| sol_dn_only | 695 | 1.5 |
| all_up | 639 | 1.3 |
| btc_up_only | 616 | 1.3 |
| eth_up_only | 396 | 0.8 |
| mixed_updn | 327 | 0.7 |

The dominant regime is `all_ranging` (80.7%). Trending and divergent regimes are
rare (~19% combined). The "asymmetry of opportunity": rare regimes can show very
high $/tr but with limited sample.

---

## 5. Per-(sleeve, xa-regime) metrics: highlights

Top non-ranging cells per sleeve (n>=30 only):

### BTC s15_5m | 150-240 | g_tr_above_ema800
| xa | n | wr | $/tr | sum |
| --- | --: | --: | --: | --: |
| all_ranging (base-ish) | 7,585 | 75.3 | 1.26 | 9,531 |
| **btc_dn_only** | 150 | 87.3 | **27.77** | 4,165 |
| mostly_up | 188 | 87.8 | 14.06 | 2,644 |
| sol_dn_only | 108 | 78.7 | 4.00 | 432 |

`btc_dn_only` cells = bullish 1-vol/4hr/8hr sleeve fired while BTC's 5m regime
is trending_down and ETH/SOL are ranging → these are contrarian fires that paid
out at high implied prob (deep ITM on cheap shorts of the rebound).

### BTC s6_5m | 60-150 | g_cci_with&g_tr_above_ema50&g_rf_with
| xa | n | wr | $/tr | sum |
| --- | --: | --: | --: | --: |
| all_ranging | 5,327 | 70.6 | 2.86 | 15,229 |
| btc_up_only | 89 | 94.4 | **24.78** | 2,205 |
| all_up | 141 | 90.8 | 10.20 | 1,438 |
| all_dn | 296 | 74.3 | 4.00 | 1,184 |
| mostly_up | 101 | 71.3 | 9.35 | 945 |

Same pattern: every trending xa-regime lifts $/tr 2-9x over baseline, but n is
small (mostly under 300).

### ETH s15_5m | 60-150 | cloud+cci+bb+ribbon (lower baseline)
| xa | n | wr | $/tr | sum |
| --- | --: | --: | --: | --: |
| all_ranging | 5,778 | 73.5 | 0.80 | 4,631 |
| btc_dn_only | 111 | 86.5 | **5.70** | 633 |
| btc_up_only | 109 | 85.3 | 4.51 | 492 |
| eth_dn_only | 173 | 80.3 | 2.78 | 481 |

ETH baseline weakest of the trio but biggest relative lift from btc-only-trending
regimes (~7x baseline).

---

## 6. Combined session x xa-regime (top 3 sleeves, top cells)

288 cells per top-3 sleeve. Top cells (n>=20) for **BTC s15 150-240 g_tr_above_ema800**:

| session | xa_combo | n | wr | $/tr | sum | lift_pt |
| --- | --- | --: | --: | --: | --: | --: |
| sydney | btc_dn_only | 46 | 80.4 | **86.88** | 3,996 | +85.28 |
| tokyo | btc_dn_only | 46 | 78.3 | **86.11** | 3,961 | +84.52 |
| hk | btc_dn_only | 60 | 83.3 | **66.69** | 4,001 | +65.09 |
| frankfurt | mostly_up | 78 | 80.8 | 27.35 | 2,134 | +25.76 |
| london | mostly_up | 90 | 82.2 | 23.73 | 2,136 | +22.14 |
| ny | all_ranging | 2,587 | 75.5 | 1.40 | 3,609 | -0.20 |
| weekend | all_ranging | 3,363 | 71.5 | 0.97 | 3,272 | -0.62 |

**Massive concentration** in the 3 asia-session × BTC-dn-only cells: 152 fires
contribute $12k of the sleeve's $14.9k baseline sum (i.e., ~80% of the PnL comes
from <2% of the fires).

**This is exactly the kind of pattern that overfits.** Note: rebound trades during
asian-session BTC-dn regimes during this 25-day window may not repeat.

Top cells for **BTC s15 60-150 ema50+ribbon**: no extreme concentration; most
high-pt cells have n<100 (`overlap/mostly_up` n=32 $/tr=$12.1, `frankfurt/mostly_up`
n=63 $/tr=$11.5).

Top cells for **ETH s15 60-150 cloud+cci**: similar - `overlap/mostly_up` n=26
$/tr=$9.79, `ny/btc_dn_only` n=31 $/tr=$9.08, `sydney/sol_dn_only` n=33 $/tr=$8.10.

---

## 7. Conditional sleeves (full window, top-5 cells per sleeve)

For each sleeve we built a variant that fires only on the top-5 train cells
(combined session × xa). Full-window results (no time split):

| sleeve | base ($/tr, sum) | var ($/tr, sum) | lift_pt |
| --- | --- | --- | --: |
| BTC s15 150-240 g_tr_above_ema800 | 1.59 / 14,886 | 1.72 / 8,413 (n=4,888) | +0.13 |
| BTC s15 60-150 ema50+ribbon | 1.34 / 10,307 | 0.94 / 5,133 (n=5,489) | **-0.41** |
| ETH s15 60-150 cloud+cci | 0.93 / 6,706 | 0.81 / 4,587 (n=5,654) | -0.11 |
| BTC s6 60-150 cci+ema50+rf | 2.86 / 19,711 | 2.89 / 14,947 (n=5,164) | +0.03 |
| SOL s15 60-150 cloud+ema200+cci | 0.74 / 4,545 | 0.77 / 3,580 (n=4,636) | +0.03 |
| SOL s15 150-240 ema800+cloud+dev | 1.07 / 5,836 | 1.51 / 5,787 (n=3,827) | **+0.44** |
| ETH s6 60-150 cloud+tight+ema50 | 2.14 / 10,005 | 2.10 / 6,994 (n=3,334) | -0.05 |

In-sample, only 2/7 sleeves got meaningful lift (BTC s15 150-240 and SOL s15
150-240). Most "conditional" variants effectively collapse to selecting
`all_ranging` cells across multiple sessions, which barely moves $/tr because
`all_ranging` is the baseline regime.

---

## 8. Strict 3-way validation (60/20/20 by fire chronology)

Split: `train < 2026-05-23 10:17 UTC` (60% of fires, ~28k), `val < 2026-05-24 14:46`
(20%), `lock >= 2026-05-24 14:46` (20%). Three variants tested per sleeve:
**combined** (session × xa cells), **session_only**, **xa_only**.

| sleeve | variant | train_n | train_pt | lock_n | lock_$/tr | base_lock $/tr | lift_lock | boot_p | PASS |
| --- | --- | --: | --: | --: | --: | --: | --: | --: | :-: |
| BTC s15 150-240 ema800 | combined | 167 | 37.5 | 0 | – | 2.69 | – | – | – |
| BTC s15 150-240 ema800 | **session_only (tokyo,sydney,hk)** | 2,600 | 2.03 | **654** | **2.95** | 2.69 | **+0.25** | **<0.001** | **YES** |
| BTC s15 150-240 ema800 | xa_only | 446 | 16.2 | 0 | – | 2.69 | – | – | – |
| BTC s15 60-150 ema50+ribbon | session_only (london,frankfurt,hk) | 2,780 | 1.67 | 968 | -0.25 | 0.40 | -0.65 | 0.62 | NO |
| ETH s15 60-150 cloud+cci | session_only (ny,frankfurt) | 2,723 | 0.81 | 898 | 1.41 | 1.55 | -0.14 | 0.010 | NO (negative lift) |
| BTC s6 60-150 cci+ema50+rf | session_only (frankfurt,london,hk) | 3,004 | 4.95 | 714 | 0.02 | 0.08 | -0.06 | 0.50 | NO |
| SOL s15 60-150 cloud+ema200+cci | session_only (weekend,london,frankfurt) | 1,967 | 0.81 | 873 | 1.54 | 1.69 | -0.15 | 0.006 | NO (neg lift) |
| SOL s15 150-240 ema800+cloud+dev | session_only (ny,overlap,london) | 1,754 | 0.52 | 741 | 1.61 | 2.53 | -0.92 | 0.004 | NO (neg lift) |
| SOL s15 150-240 ema800+cloud+dev | xa_only | 2,370 | 0.82 | 1,115 | 2.53 | 2.53 | 0.00 | – | NO (zero lift) |
| ETH s6 60-150 cloud+tight+ema50 | session_only (frankfurt,london) | 1,195 | 4.84 | 431 | -0.29 | 1.22 | -1.51 | 0.59 | NO |
| ETH s6 60-150 cloud+tight+ema50 | xa_only | 1,820 | 3.75 | 1,040 | 1.22 | 1.22 | 0.00 | – | NO (zero lift) |

**Combined (session × xa) variant always died in lock** — high-pt cells with
n<200 in train had zero recurrence in the 1.5-day lock window. The narrow
intersection cells (sydney/btc_dn_only etc.) are episodic, not stable.

**Session_only variants worked once.** Only the BTC s15 150-240 ema800 sleeve
filtered to (tokyo OR sydney OR HK) sessions held up: lock $/tr = $2.95 vs base
$2.69 with bootstrap p<0.001. This is consistent with the per-sleeve session
table: this sleeve genuinely prefers Asian sessions.

**Asymmetry**: ETH/SOL session_only variants showed positive train lift but
negative lock lift — overfitting on a 25-day window with one specific market
character.

**xa_only variants** collapse to ranging (since ranging is 81% of fires) and
provide ~zero lift.

---

## Lockbox pass count

**1 of 7** sleeves passed strict 3-way validation with positive lockbox lift
and p<0.05:

- **BTC s15_5m | 150-240 | g_tr_above_ema800** + session filter (Tokyo OR Sydney OR HK):
  - lock_n=654, lock_wr=75.1%, lock $/tr=$2.95 (vs base $2.69, lift +$0.26), p<0.001
  - Translates to ~ +$170 incremental PnL in the 1.5-day lock window over baseline.
  - **Caveat**: lift is modest (+10% on $/tr) and the magic xa-regime overlay
    (btc_dn_only during Asian sessions) does NOT generalize. The session-only
    filter is the deployable version.

---

## Cross-cut commentary

1. **Session matters, xa-regime does not (cleanly).** Session filters have
   consistent train→val→lock signs in 1/7 sleeves; xa-regime filters add no
   information beyond the dominant `all_ranging` regime that's already in the
   baseline.
2. **The 25-day window is too short for cross-asset regime mining.** Non-ranging
   regimes are <20% of fires; intersecting them with sessions creates 100-fire
   cells that don't recur in a 1.5-day lock.
3. **Best-of-cell illusions:** BTC s15 150-240 sleeve had $86/tr on Sydney+BTC-dn,
   but this is 46 fires out of 9,349. The cell is a regime-rare phenomenon
   (BTC trending dn while ETH/SOL ranging during Asian session), not a stable
   edge.
4. **For deployment**: only BTC s15_5m | 150-240 | g_tr_above_ema800 with the
   session-restricted variant (Asia-only) is conservative enough to consider.
   All others either don't validate or have negative lockbox lift.

## Next steps

- Re-test the BTC Asia-session variant against a longer history (need the 60-90d
  rolling refresh on master_gate_features_v2).
- Investigate WHY the BTC 150-240 sleeve favors Asia: liquidity, vol regime,
  pricing patterns of the up-down crypto markets during low-US-volume hours?
- Consider running this analysis on the 5 deploy sleeves from the most recent
  TV deploy spec — those may have different session sensitivities than the
  master_combinatorial top-7.
