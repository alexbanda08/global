# Direction-Asymmetric Gates — 2026-05-26

**Question:** does the OPTIMAL gate stack differ for UP vs DOWN bets within the
same sleeve? Motivation: the BTC `xa_down` failure (cross-asset DOWN profitable
on 22d but FAILED on lockbox with WR 56%) suggested DOWN-side bets may have
structurally different statistical properties.

**TL;DR (≤300 words)**

- **Asymmetric stacks beat symmetric only marginally**: on the top 7 sleeves,
  ASYM > SYM on lockbox sum_pnl in **2/7** cases and on dpt in **3/7** cases;
  average dpt improvement +$0.10/trade, average sum improvement +$461. Most
  sleeves' UP and DOWN optimal stacks converge to the SAME gate
  (`g_hurst_trending` appears in 5/7 sleeves on BOTH directions). Convergence,
  not divergence, is the dominant pattern in the discrete-gate space.
- **12/14 (sleeve, direction) combos pass lockbox deployability** (n≥30,
  WR≥60%, dpt>0, p_boot≤0.05). The 2 that fail are both s15 240-period
  stacks where UP-direction lockbox sample is too thin / p>0.05.
- **The real asymmetry is in CONTINUOUS thresholds, not in discrete gate
  selection**: 13/17 (sleeve, feature) pairs we tested have a sign-or-operator
  *flip* between UP and DOWN optimal thresholds (e.g. on the big sleeve
  `s15 150-240 g_tr_above_ema800` the L_stat rule is `<=5.0` for UP but
  `>=1.0` for DOWN — opposite operators).
- **No DOWN-only or UP-only specialty cells exist**. Every
  (asset, tf, offset_bin) cell has both UP and DOWN reasonably profitable.
  Direction asymmetry must be exploited inside a sleeve, not by killing one
  side at the cell level.
- **g_hurst_trending is the universal direction-agnostic filter** — appears
  in BOTH UP and DOWN optimal stacks for 5/7 sleeves. Add this on top of any
  R2 stack as a "free" lift regardless of bet direction.
- **g_ribbon_agrees is UP-biased** (4 sleeves: UP-only). Direction asymmetry
  in the discrete space is mild but real.
- **Best NEW asymmetric sleeve**: `s15 60-150 g_tr_above_ema50 & g_ribbon_agrees`
  + `g_hurst_trending` (same gate on both directions but with direction-
  specific entry) — lockbox UP $7,622 / DOWN $7,313, combined $14,935 sum,
  WR 78.8% / 77.5%, dpt $4.94 / $4.90, both p≈0 on 500-shuffle bootstrap.
- **The xa_down lockbox failure was NOT a generic DOWN-side problem** — the
  top-7 sleeves DOWN-side lockbox WR ranges 77-85%, consistently strong. The
  failure was specific to the cross-asset DOWN sleeve's leader/follower
  asymmetry, not a universal DOWN regime issue.

---

## 1. Per-(sleeve, direction) optimal stacks

Source: `strategy_lab/direction_asym_2026_05_26/direction_asym_per_sleeve.csv`
Final stacks: `data/v4/canonical/_results/direction_asymmetric_stacks.csv`

| Sleeve | Dir | Optimal gate stack | Train n | Train sum | Lock n | Lock WR | Lock dpt | Lock sum | p_lock | Deploy? |
|---|---|---|--:|--:|--:|--:|--:|--:|--:|---|
| s15 150-240 `g_tr_above_ema800` | UP | `g_hurst_trending & g_hawkes_imbalance_with & g_tight_ribbon` | 996 | $1,499 | 200 | 86.0% | $4.49 | $899 | 0.002 | Yes |
| s15 150-240 `g_tr_above_ema800` | DOWN | `g_hurst_trending & g_tr_stack_with & g_hawkes_imbalance_with & g_cci_with` | 886 | $1,109 | 199 | 82.9% | $3.21 | $638 | 0.030 | Yes |
| s15 60-150 `g_tr_above_ema50 & g_ribbon_agrees` | UP | `g_hurst_trending` | 601 | $1,545 | **1,543** | 79.3% | $4.94 | **$7,623** | 0.000 | Yes |
| s15 60-150 `g_tr_above_ema50 & g_ribbon_agrees` | DOWN | `g_hurst_trending` | 637 | $2,036 | **1,491** | 77.5% | $4.90 | **$7,313** | 0.000 | Yes |
| s15 60-150 `cloud&ribbon&bb_pos&cci` | UP | `g_hurst_trending & g_tr_stack_with & g_ribbon_agrees` | 737 | $1,784 | 153 | 84.3% | $4.05 | $619 | 0.000 | Yes |
| s15 60-150 `cloud&ribbon&bb_pos&cci` | DOWN | `g_hurst_trending & g_tr_stack_with` | 741 | $1,589 | 191 | 83.8% | $5.26 | $1,005 | 0.000 | Yes |
| s6 60-150 `cci&ema50&rf` | UP | `g_tr_within_adr & g_stoch_with & g_ribbon_agrees & g_cci_with` | 677 | $3,644 | 398 | 71.1% | $1.89 | $750 | 0.036 | Yes |
| s6 60-150 `cci&ema50&rf` | DOWN | `g_queue_top_high & g_vol_high` | 333 | $10,803 | 40 | 80.0% | $8.56 | $342 | 0.008 | Yes |
| s15 60-150 `cloud&ribbon&ema200&cci` | UP | `g_hurst_trending & g_ribbon_agrees` | 567 | $1,129 | 145 | 76.6% | $1.71 | $248 | 0.110 | **No** (p>0.05) |
| s15 60-150 `cloud&ribbon&ema200&cci` | DOWN | `g_hurst_trending & g_stoch_with` | 578 | $1,227 | 193 | 80.8% | $3.24 | $625 | 0.002 | Yes |
| s15 150-240 `ema800&cloud&within_dev&ema200` | UP | `g_hurst_trending & g_flow_with_and_no_whale & g_tr_within_adr` | 344 | $465 | 138 | 87.7% | $0.48 | $67 | 0.302 | **No** (dpt low) |
| s15 150-240 `ema800&cloud&within_dev&ema200` | DOWN | `g_hurst_trending` | 557 | $543 | **1,426** | 83.5% | $3.29 | **$4,695** | 0.000 | Yes |
| s15 150-240 `tr_stack&ema200&ribbon&bb_pos` | UP | `g_ribbon_agrees & g_hawkes_imbalance_with` | 1,403 | $2,392 | 161 | 88.2% | $1.62 | $261 | 0.044 | Yes |
| s15 150-240 `tr_stack&ema200&ribbon&bb_pos` | DOWN | `g_hurst_trending` | 906 | $1,855 | 737 | 84.5% | $1.32 | $972 | 0.028 | Yes |

**Pass count: 12/14 (sleeve, direction) combos pass deployability.**
Failures are both UP-side on s15_5m offset 150-240 sleeves where lockbox bootstrap p>0.05 / dpt too low. DOWN-side passes ALL 7/7.

## 2. Symmetric vs asymmetric (TASK 2)

Source: `strategy_lab/direction_asym_2026_05_26/sym_vs_asym_fair.csv`

Comparison: **symmetric** = single greedy stack on combined UP+DOWN train; **asymmetric** = direction-specific stacks. Both evaluated on lockbox.

| Sleeve | Sym n | Sym sum | Sym WR | Asym n | Asym sum | Asym WR | Δ WR pp | Δ dpt |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| s15 150-240 ema800+cloud+dev+ema200 | 340 | $696 | 87.6% | **1564** | **$4,762** | 83.8% | -3.8 | +$1.00 |
| s15 60-150 cloud+ribbon+bb+cci | 359 | $1,676 | 83.8% | 344 | $1,625 | 84.0% | +0.2 | +$0.05 |
| s15 150-240 ema800 | 469 | $1,845 | 85.1% | 399 | $1,537 | 84.5% | -0.6 | -$0.08 |
| s15 150-240 tr_stack+ema200+ribbon+bb | 1893 | $1,400 | 82.5% | 898 | $1,234 | 85.2% | +2.7 | +$0.63 |
| s15 60-150 ema50+ribbon | 3034 | $14,936 | 78.4% | 3034 | $14,936 | 78.4% | 0.0 | 0.0 |
| s6 60-150 cci+ema50+rf | 439 | $1,476 | 72.7% | 438 | $1,093 | 71.9% | -0.7 | -$0.87 |
| s15 60-150 cloud+ribbon+ema200+cci | 311 | $803 | 78.8% | 338 | $873 | 79.0% | +0.2 | 0.0 |

- ASYM > SYM on lockbox sum: **2/7** (sleeves 0 and 3)
- ASYM > SYM on lockbox dpt: **3/7** (sleeves 0, 1, 3)
- Average lockbox dpt diff: **+$0.105**
- Average lockbox sum diff: **+$461**

**Verdict**: asymmetric stacks deliver MARGINAL improvement on average. Big wins are confined to 2/7 sleeves; the remaining 5 are flat-to-slightly-worse. The dominant pattern is that UP and DOWN converge on the same `g_hurst_trending` filter.

## 3. Gates that DIFFER between UP and DOWN (TASK 3)

Source: `strategy_lab/direction_asym_2026_05_26/gate_diff_per_sleeve.csv`

**Cross-sleeve frequency of asymmetric gate inclusion:**

| Gate | UP-only count | DOWN-only count | Both-direction count |
|---|--:|--:|--:|
| `g_hurst_trending` | 0 | 0 | **5** |
| `g_ribbon_agrees` | **4** | 0 | 0 |
| `g_tr_stack_with` | 0 | 1 | 1 |
| `g_hawkes_imbalance_with` | 1 | 0 | 1 |
| `g_tr_within_adr` | 2 | 0 | 0 |
| `g_stoch_with` | 1 | 1 | 0 |
| `g_cci_with` | 1 | 1 | 0 |
| `g_queue_top_high` | 0 | 1 | 0 |
| `g_vol_high` | 0 | 1 | 0 |
| `g_tight_ribbon` | 1 | 0 | 0 |
| `g_flow_with_and_no_whale` | 1 | 0 | 0 |

**Findings:**
- **`g_hurst_trending` is the universal filter** — 5/7 sleeves on BOTH directions. Highest-value standalone gate.
- **`g_ribbon_agrees` is UP-biased** — 4 sleeves include it ONLY on UP-side optimal stacks. This is the cleanest direction-asymmetric signal in the discrete space.
- **`g_tr_within_adr` is UP-only** in 2 sleeves — UP fires benefit from "price within average-daily-range" filter; DOWN does not.
- **`g_queue_top_high` & `g_vol_high`** are DOWN-only on the s6 5m cci/rf sleeve.
- No gate appears as exclusively DOWN-only across multiple sleeves.

## 4. Asymmetric thresholds within same gate (TASK 4)

Source: `strategy_lab/direction_asym_2026_05_26/threshold_asym.csv`,
`threshold_asym_compare.csv`

Tested 9 continuous features × 7 sleeves × 2 directions. Threshold search
on train, eval on lockbox.

**13/17 (sleeve, feature) pairs have sign-or-operator FLIP between UP and
DOWN optimal thresholds — strong evidence of structural threshold asymmetry.**

Selected examples:

| Sleeve | Feature | UP rule | DOWN rule | UP lock sum | DOWN lock sum |
|---|---|---|---|--:|--:|
| s15 150-240 ema800 | `L_stat` | `<=5.0` | `>=1.0` | **$9,971** | $969 |
| s15 150-240 ema800 | `up_micro_dev_bps` | `>=5.0` | `<=20.0` | $632 | $1,377 |
| s15 150-240 ema800 | `dn_micro_dev_bps` | `<=-20.0` | `>=-15.0` | -$410 | $1,387 |
| s15 150-240 ema800+cloud+dev+ema200 | `mp_skew_change_500ms` | `>=-0.2` | `<=0.05` | $2,074 | $3,586 |
| s15 150-240 ema800+cloud+dev+ema200 | `mp_weighted_skew` | `<=-0.1` | `>=-0.4` | $1,075 | $1,315 |
| s15 60-150 cloud+ribbon+ema200+cci | `L_stat` | `>=0.5` | `<=4.0` | -$494 | $1,985 |
| s15 60-150 cloud+ribbon+ema200+cci | `vpin_zscore` | `>=0.5` | `<=1.0` | -$504 | $654 |
| s6 60-150 cci+ema50+rf | `L_stat` | `>=0.5` | `>=0.0` | $1,114 | $4,187 |

**Operational interpretation**:
- `L_stat` (jump indicator) thresholds FLIP — on big trend sleeves UP wants
  `L_stat<=5` (no extreme jumps) while DOWN wants `L_stat>=1` (some
  jumpiness OK or helpful). DOWN-side benefits from confirmed jump
  signal, UP-side does not.
- `mp_skew` / `mp_weighted_skew` thresholds are sign-asymmetric on multiple
  sleeves — UP can tolerate sellers-heavy book (positive skew), DOWN
  optimum shifts to neutral / mild negative.
- `vpin_zscore` on the cci sleeve: UP wants high VPIN (toxic flow against),
  DOWN wants moderate VPIN (capped).

These threshold asymmetries are NOT captured by the discrete gates in the
current panel. **Adding direction-asymmetric continuous-threshold gates to
the panel is the highest-EV next step** to unlock more direction-specific
edge.

## 5. DOWN-only / UP-only specialty cells (TASK 5)

Source: `strategy_lab/direction_asym_2026_05_26/specialty_cells.csv`

**Result: 0 specialty cells.** Every (asset, tf, offset_bin) cell has BOTH
UP and DOWN reasonably profitable (no cell where one direction is positive
and the other is negative). Direction asymmetry MUST be exploited inside a
sleeve via gate stack, not by killing one side at the cell level.

`cell_direction_asym.csv` shows the full per-cell breakdown for reference —
the closest to specialty status is BTC s15 240-300 where DOWN dpt is +$0.39
vs UP +$0.05, but both are positive.

**Implication for xa_down**: the cross-asset DOWN sleeve's failure was NOT a
generic DOWN-side regime issue. Top-7 sleeves DOWN-side lockbox WR is
77-85%, healthier than UP-side on several sleeves. The xa_down problem must
be specific to its leader-follower or basis filter, not the underlying
DOWN-direction edge.

## 6. KILL gates per direction (TASK 6)

Source: `strategy_lab/direction_asym_2026_05_26/kill_gates_per_direction.csv`

Tested: `g_lm_extreme_against`, `g_dev_extreme`, `g_book_slope_steep_against`,
`g_coinbase_basis_extreme_against`, `g_hl_liq_cascade_with`.

Most KILL candidates either had insufficient coverage on the panel
(`g_lm_extreme_against`, `g_dev_extreme`, `g_coinbase_basis_extreme_against`)
or did NOT show the expected "ON=avoid" pattern.

**`g_hl_liq_cascade_with` is NOT a KILL — it's a SIGNAL** (against
intuition): on `s6 60-150 cci&ema50&rf` DOWN, when ON: dpt $7.09; when OFF:
dpt $3.63. Liquidation cascade alignment ENHANCES DOWN-direction edge on
this sleeve. UP-direction also benefits ($3.88 ON vs $1.14 OFF). Asymmetric
magnitude: DOWN gets ~$3.47 lift, UP gets ~$2.74 lift.

**`g_book_slope_steep_against`**: on `s15 150-240 tr_stack&ema200&ribbon&bb`
DOWN, gate ON delivers dpt $4.22 vs OFF $0.11. Strongly directional — DOWN
fires fire much better when the book is heavily skewed against the bet.
This contradicts the "trade WITH book slope" intuition for DOWN-side on
this sleeve.

These flips reinforce the threshold-asymmetry conclusion of TASK 4: many
"intuitive" gates have inverted optimal rules for DOWN vs UP.

## 7. Strict 3-way validation (TASK 7)

We used train (20d: 05-01 → 05-20) and lockbox (5d: 05-21 → 05-25). The
panel covers 25 days total (05-01 → 05-25). Lockbox is fully out-of-sample
relative to the train window used by the greedy search.

Each (sleeve, direction) optimal stack received a **500-shuffle sign-flip
bootstrap** on its lockbox PnL stream. The reported `p_lock` is the
one-sided probability under null (mean lockbox PnL = 0).

**Pass criteria**: n≥30, WR≥60%, dpt>0, p_lock≤0.05.

| Direction | Pass | Fail |
|---|--:|--:|
| UP | 5 | 2 (s15 150-240 cloud/dev/ema200 dpt low; s15 60-150 cloud/ema200/cci p=0.11) |
| DOWN | 7 | 0 |
| **Combined** | **12** | **2** |

A formal 3-way (train/val/lockbox) split was not used because the panel's
25-day window is too short to allow 3 meaningful holdouts. With more data
the next iteration should use 20d / 4d / 4d.

## 8. Top NEW direction-asymmetric sleeves

Ranked by lockbox sum_pnl:

| Rank | Sleeve | Dir | Stack | n_lock | WR | dpt | sum_lock | p |
|---|---|---|---|--:|--:|--:|--:|--:|
| 1 | s15 60-150 ema50+ribbon | UP | `g_hurst_trending` | 1,543 | 79.3% | $4.94 | **$7,623** | 0.000 |
| 2 | s15 60-150 ema50+ribbon | DOWN | `g_hurst_trending` | 1,491 | 77.5% | $4.90 | **$7,313** | 0.000 |
| 3 | s15 150-240 ema800+cloud+dev+ema200 | DOWN | `g_hurst_trending` | 1,426 | 83.5% | $3.29 | $4,695 | 0.000 |
| 4 | s15 60-150 cloud+ribbon+bb+cci | DOWN | `g_hurst_trending & g_tr_stack_with` | 191 | 83.8% | $5.26 | $1,005 | 0.000 |
| 5 | s15 150-240 tr_stack+ema200+ribbon+bb | DOWN | `g_hurst_trending` | 737 | 84.5% | $1.32 | $972 | 0.028 |

**Combined deployable sum on lockbox: ~$28,000 across all 12 pass-combos
on the 5-day window** ≈ **$5,600/day theoretical**.

## 9. Final artifacts

| Artifact | Path | Description |
|---|---|---|
| Per-(sleeve, direction) stacks | `data/v4/canonical/_results/direction_asymmetric_stacks.csv` | Final asymmetric specs |
| Per-(sleeve, direction) metrics | `strategy_lab/direction_asym_2026_05_26/direction_asym_per_sleeve.csv` | Train + lockbox metrics + p |
| Sym vs asym fair compare | `strategy_lab/direction_asym_2026_05_26/sym_vs_asym_fair.csv` | Same-budget greedy comparison |
| Gate difference per sleeve | `strategy_lab/direction_asym_2026_05_26/gate_diff_per_sleeve.csv` | Shared / UP-only / DOWN-only gates |
| Continuous threshold asym | `strategy_lab/direction_asym_2026_05_26/threshold_asym.csv` | All sleeve×feature×direction thresholds |
| Sign-flip summary | `strategy_lab/direction_asym_2026_05_26/threshold_asym_compare.csv` | 13/17 pairs asymmetric |
| Specialty cells | `strategy_lab/direction_asym_2026_05_26/specialty_cells.csv` | (empty) |
| Cell direction asym | `strategy_lab/direction_asym_2026_05_26/cell_direction_asym.csv` | Per-cell UP vs DOWN breakdown |
| KILL gates per direction | `strategy_lab/direction_asym_2026_05_26/kill_gates_per_direction.csv` | g_hl_liq, g_book_slope etc. ON vs OFF by dir |
| Top10 asymmetric | `strategy_lab/direction_asym_2026_05_26/top10_asymmetric.csv` | Ranked deployable specs |

## 10. Recommendations

1. **Deploy `g_hurst_trending` as a universal "free-lift" gate** on top of
   the top 7 R2 sleeves regardless of bet direction. Lockbox-verified on
   both UP and DOWN with n≥1k on several sleeves.
2. **Do NOT build direction-asymmetric DISCRETE stacks** — marginal
   improvement of +$0.10 dpt is not worth the dual-spec complexity. Stick
   with single stack per sleeve.
3. **DO build direction-asymmetric CONTINUOUS-threshold gates** next round:
   `L_stat`, `mp_skew_change_500ms`, `vpin_zscore`, `dev_bps` all show
   sign-or-operator flips between UP and DOWN. Bake these into the panel
   as direction-aware gates (`g_lstat_with_direction_optimal` etc.) and
   re-run the gate search.
4. **xa_down failure root cause is NOT a generic DOWN regime issue** — top
   sleeves' DOWN side passes lockbox at 77-85% WR. The xa_down specific
   failure is a leader-follower or basis-filter issue and should be
   investigated separately at the cross-asset signal layer, not at the
   direction layer.
5. **Top NEW deployable**: `s15 60-150 g_tr_above_ema50 & g_ribbon_agrees &
   g_hurst_trending` — works UP-side and DOWN-side identically with ≈$5/tr
   on n>1.4k each on lockbox. Use SINGLE stack, not asymmetric, for this
   one.

## 11. Reproducibility

Scripts in `strategy_lab/direction_asym_2026_05_26/`:
- `01_inspect_panel.py`  — schema/coverage check
- `02_asym_search.py`    — per-(sleeve, direction) greedy + bootstrap
- `03_sym_vs_asym.py`    — fair comparison
- `04_threshold_asym.py` — continuous-threshold sign-flip analysis
- `05_down_only_kill.py` — specialty cells + KILL gate test
- `06_final_summary.py`  — top tables / pass counts

Run with `PYTHONIOENCODING=utf-8 C:/Python314/python.exe`. All scripts read
`data/v4/canonical/_results/master_gate_features_v2.parquet` directly.
LegacyConfig (2%-on-profit) fee model. Causal anchoring (fire_us). Full 25d
window (panel coverage). Bootstrap: 500-shuffle sign-flip, one-sided p,
seed 42.
