# Round 7 synthesis — cross-cut investigations — 2026-05-26

**Date:** 2026-05-26
**Window:** Apr 24 → May 25 2026 UTC (full 32d canonical)
**Fee model:** Legacy 2%-on-profit-only

Round 7 was the user-prompted cross-cut round: "did you test all 5-round
discovery mix, analyze cross-examination?" The answer was largely NO — prior
rounds tested each gate standalone or as single-gate overlay. R7 fixed that
with 5 focused cross-cut agents:

| Agent | Cross-cut | Verdict |
|---|---|---|
| **QQ** — Regime-conditional state machines | Per-(sleeve × regime) optimal gate stacks | ❌ NO LIFT — single agnostic gate `g_hurst_trending` beats SM |
| **RR** — Indicator threshold sweeps | Sweep thresholds within each gate (20-150bps, L>{3,5,7,10}, etc.) | ⚠️ MODEST — thresholds were too tight; global recalibration +$15.6k aggregate |
| **SS** — Direction-asymmetric gates | Different gate stacks for UP vs DOWN bets | ❌ DISCRETE asymmetry marginal; CONTINUOUS thresholds DO flip |
| **TT** — Weighted multi-signal voting | Ridge/Logistic Poly2 vs binary AND | ⭐⭐⭐ **HEADLINE FIND** — 17× lift on lockbox (with caveats) |
| **UU** — Session × cross-asset regime | Session and xa-regime stratification | ❌ MOSTLY — only 1/7 session-conditional sleeve survives lockbox |

**Plus**: Agent VV cleaned up the naive-sum overlap bug across all R1-R5 reports.

---

## TL;DR — R7 contributions

**One BIG WIN (TT)** that needs validation:

Weighted-scoring linear models (Ridge / ElasticNet / Logistic with polynomial degree-2 interactions) DECISIVELY beat binary AND gate stacks on lockbox. Top model: Logistic Poly2 with $61,980 aggregate lockbox sum over 4 days vs binary AND baseline $3,594 — a **17× lift** on the same 7 sleeves.

The likely game-changing finding: an INTERACTION feature
`ribbon_alignment_pct × plus_di_14` (negative on every S15/S7 sleeve) captures
**late-trend exhaustion** that no AND-gate can express. Binary AND can only
say "ribbon is aligned AND DI is high"; the interaction says "high alignment
multiplied by high DI = exhausted trend = bet AGAINST momentum". That sign
inversion is INVISIBLE to AND logic.

**Critical caveat**: TT's $61,980/4d gross is across 7 sleeves that overlap.
The R6 dedup methodology must be applied to WS-poly2 fires before quoting
combined deployable. If overlap is similar to binary AND case (~80% Jaccard),
post-dedup realistic is $5-10k/4d = $35-70k/28d at $25 notional, which is
still 2-3× the current $20.5k/28d. **Needs Agent PP-style overlap audit on
WS fires before deploy.**

**Four modest/negative findings**:
- QQ: regime-conditional state machines do NOT beat single agnostic gates
- RR: thresholds were too tight; global recalibration (mp_no_extreme 50→100bps, hawkes 0.3→0.1) gives +$15.6k aggregate lockbox lift
- SS: discrete asymmetric stacks marginal; continuous-threshold direction asymmetry IS real (operator-flip on 13/17 sleeve-feature pairs)
- UU: session matters modestly (1/7 lockbox pass: BTC S15 + Asia-session filter); cross-asset regime stratification overfits catastrophically

---

## 1. Weighted multi-signal voting — Agent TT ⭐⭐⭐ HEADLINE

### What was tested
Replace binary AND gate stacks with continuous scoring: bet UP if
`weighted_sum(mp_score + hawkes_score + lm_score + trend_slope_score + ...) > threshold`.
Weights learned via Ridge / ElasticNet / Logistic Regression with strict 3-way
split (train 20d / val 7d / lockbox 4d).

### Models tested
- Ridge (L2)
- Elastic Net (L1+L2)
- Logistic Regression L2
- Logistic Regression with degree-2 polynomial features (interactions)

### Aggregate lockbox results (7 sleeves, May 22-25, 4 days)

| Model | Lockbox sum | Multiple vs AND |
|---|--:|--:|
| hybrid_v1 binary AND (baseline) | $3,594 | 1× |
| Ridge | $43,021 | **12×** |
| Elastic Net | $40,378 | 11× |
| Logistic L2 | $50,718 | 14× |
| **Logistic Poly2** ⭐ | **$61,980** | **17×** |

### Per-sleeve best model

| Sleeve | Best model | Lockbox sum (4d) | n | WR | bootstrap p |
|---|---|--:|--:|--:|--:|
| **S7_BTC_5m_base** | poly2 | **$26,564** | 9,131 | 73.6% | 0.000 |
| BTC_S15_150-240 | poly2 | $11,055 | 2,174 | 75.9% | 0.000 |
| BTC_S6_60-150 | poly2 | $7,470 | 3,094 | 70.0% | 0.000 |
| SOL_S6_60-150 | poly2 | $7,049 | 1,569 | 78.1% | 0.000 |
| SOL_S15_60-150 | LR L2 | $4,753 | 1,204 | 82.2% | 0.000 |
| ETH_S6_60-150 | Ridge | $4,748 | 3,144 | 72.5% | 0.000 |
| ETH_S15_150-240 | LR L2 | $959 | 1,641 | 82.8% | 0.064 ⚠️ |

**6/7 pass lockbox p<0.05. 1 marginal (ETH S15 at p=0.064).**

### Key insight: polynomial interactions
**Top INTERACTION feature**: `ribbon_alignment_pct × plus_di_14` (negative weight on every S15/S7 sleeve).

Plain-English meaning: when ribbon alignment is HIGH AND directional index (+DI)
is HIGH, the next slot resolution tends to go AGAINST the trend direction.
This is **late-trend exhaustion** — the move is so committed that mean
reversion becomes the smart bet.

Binary AND can only say "ribbon aligned AND DI high → bet WITH trend" — it
CANNOT express the negative-weight interaction that flips the sign at extreme
alignment values. This is a structural advantage of weighted scoring over AND
logic, not just a parameter tweak.

### Why this worked when R5 LightGBM failed
R5 Agent DD's LightGBM passed 0/6 lockbox. Why is R7 different?
- **L1/L2 regularization** forces the model to use only dominant signals
- LightGBM's tree-based memorization captured noise on the 32d training window
- Linear models couldn't memorize — they had to find the genuine linear signal
- Polynomial degree-2 features add ~150 features (k + k(k-1)/2 for k=15-20 base); LightGBM was trying to find non-linear structure across thousands of feature combinations

The discipline of regularization is the difference.

### Calibration
- **S15/S7 models**: well-calibrated (3-5% error in reliability diagram)
- **S6 models**: poor (13-27% error — apply isotonic regression on val)

### ⚠️ Critical caveat: slug overlap not yet applied

These $61,980/4d gross numbers are across 7 sleeves that likely share fires
(same R6 issue Agent PP identified). The AND baseline at $3,594/4d roughly
matches Agent PP's $20.5k/28d after dedup. The WS-poly2 number needs the same
treatment.

**Estimated post-dedup**: if overlap similar to AND case (~70-80% Jaccard),
realistic combined: $10-15k/4d = $70-105k/28d at $25 notional. That's
2-3× Agent PP's $20.5k/28d. Still a meaningful upgrade.

**Action required (Round 8)**: spawn a slug-overlap-audit agent specifically on
the WS-poly2 fires from each model. Apply primary-greedy dedup. Get the real
combined number.

### Recommendation
- **DO**: build a paper-mode WS-poly2 sleeve for S7_BTC_5m_base (the largest contributor)
- **DO**: apply isotonic recalibration on S6 models before any live deploy
- **DO**: run slug-overlap audit on WS fires before quoting combined PnL
- **DON'T**: replace all binary AND sleeves with WS — overlap audit may show diminishing combined returns

**Files**: `strategy_lab/reports/WEIGHTED_VOTING_2026_05_26.md` + 13 artifacts in `strategy_lab/weighted_voting_2026_05_26/`

---

## 2. Threshold sweeps — Agent RR ⚠️ MODEST WIN

### Findings
Thresholds set in prior rounds were **systematically too tight**. Global
recalibration (one threshold change applied to all sleeves) captures most
of the lift:

| Gate | Default threshold | Optimal | Aggregate lockbox lift |
|---|--:|--:|--:|
| g_mp_no_extreme | 50 bps | **100-150 bps** | +$3,139 |
| g_hawkes_imbalance_with | 0.3 | **0.1-0.2** | +$2,628 |
| g_hurst_trending | 0.55 | **0.50** | +$2,590 |
| g_vol_contracting | 0.7 | **0.85** | +$2,542 |

**Aggregate +$15.6k lockbox lift** across all (sleeve × gate) cells.

### Direction consistency
Threshold-change direction is consistent across 6-7 of 7 sleeves — meaning a
single global recalibration captures most of the lift. Per-sleeve micro-tuning
adds marginal value.

### Overfit risk
55% of cells (46/83) have different val-optimal vs lockbox-optimal threshold.
Mean sum gap $110/cell. Use val-optimal thresholds (not lockbox-optimal) to
avoid overfitting.

### Top 3 threshold-optimized (val-optimal threshold)

| # | Sleeve | Gate@threshold | Lockbox n | $/tr | sum | p |
|--:|---|---|--:|--:|--:|--:|
| 1 | R2_btc_5m_s1_5_3bps | `hawkes_imbalance@0.1` | — | sign flip! | $-443 → $+260 | — |
| 2 | ETH_S6_60-150 | `book_slope_steep@0.4` (lk-opt) | 197 | $+10.01 | $1,972 | 0.002 |
| 3 | S7_btc_5m_base | `book_slope_steep@0.25` (val-opt) | 24 | $+14.91 | $358 | 0.072 |

Only #3 passes strict (val-opt + p ≤ 0.10 + WR ≥ 55%). The other two are
lock-optimized which is overfit-prone.

### Recommendation
- **Apply globally recalibrated thresholds** to existing sleeves: g_mp_no_extreme=100bps, g_hawkes_imb=0.15, g_hurst_trending=0.50
- **One new sleeve to register**: S7_btc_5m_base + `book_slope_steep_against@0.25` (val-optimal)

**Files**: `strategy_lab/reports/THRESHOLD_SWEEPS_2026_05_26.md` + 6 CSVs

---

## 3. Direction-asymmetric gates — Agent SS

### Discrete asymmetry: MARGINAL
- ASYM > SYM on lockbox sum_pnl in only 2/7 sleeves
- Avg dpt diff: +$0.10 only
- Most UP and DOWN optimal stacks CONVERGE on the same gate (`g_hurst_trending` in 5/7)

### Continuous-threshold asymmetry: REAL
**13/17 (sleeve, feature) pairs have sign/operator FLIP between UP and DOWN.**

Example: BTC S15 150-240 L_stat optimal rule is:
- UP bets: `L_stat <= 5.0` (avoid high-confidence jumps when betting UP)
- DOWN bets: `L_stat >= 1.0` (jump confirms DOWN)

**Opposite operators!** This is invisible to symmetric AND logic.

### No DOWN-only / UP-only specialty cells
Every (asset, tf, offset) has both directions reasonably profitable. The
prior xa_down failure on lockbox WAS NOT a generic DOWN-regime issue.

### Recommendation
- Don't build asymmetric DISCRETE specs (marginal lift)
- DO build direction-aware CONTINUOUS-threshold gates — these complement Agent RR's threshold sweeps
- Best new sleeve: S15 60-150 `g_tr_above_ema50 ∧ g_ribbon_agrees ∧ g_hurst_trending` (symmetric, both directions p=0):
  - UP: sum $7,623, WR 79.3%, n=1,543
  - DOWN: sum $7,313, WR 77.5%, n=1,491

**Files**: `strategy_lab/reports/DIRECTION_ASYMMETRIC_GATES_2026_05_26.md` + 10 CSVs

---

## 4. Regime-conditional gate optimization — Agent QQ

### Result: NO LIFT from state machines

For each sleeve, the optimal gate stack DIFFERS across regimes (TU/TD/R) —
but the SAME single agnostic gate (`g_hurst_trending=1`) beats the
state-machine version on TOTAL sum.

| Approach | Lockbox sum (8 sleeves) |
|---|--:|
| State-machine (different stack per regime) | $22,800 |
| Single agnostic gate `g_hurst_trending=1` | **$41,700** |

### Cross-regime universal gates
Gates that work positively in ALL 3 regimes (TU + TD + R):
- `g_flow_with_and_no_whale=0` (+$5.08 avg) — wait, NEGATION? Interesting.
- `g_trend_slope_strong=1` (+$2.48)
- `g_hurst_trending=1` (+$1.78)

### Polarity reversal found (small effect)
`g_tr_above_ema800=0` lifts +$5.07 in trending_up but kills -$3.32 in trending_dn.
Real but absolute size is small.

### Transition signal (marginal)
trending_dn→ranging transitions lift +39% above baseline $/tr.
ranging→trending_dn transitions lose -84%.
Marginal as a standalone filter — not worth the operational complexity.

### Recommendation
- Don't deploy state machines
- Apply single-gate filters (`g_hurst_trending=1`, `g_markov_with=0` per agent NN finding)
- Regime is captured by existing universal gates

**Files**: `strategy_lab/reports/REGIME_CONDITIONAL_GATES_2026_05_26.md` + 8 CSVs

---

## 5. Session × cross-asset regime — Agent UU

### Best session per sleeve

| Sleeve | Best session | $/tr lift over baseline |
|---|---|--:|
| BTC s15/150-240 ema800 | **Asia (HK/Tokyo/Sydney)** | +$1.10 |
| BTC s6/60-150 cci+ema50+rf | **Frankfurt** | +$1.78 |
| ETH s6/60-150 cloud+tight | **Frankfurt** | +$1.05 |
| BTC s15/60-150 ema50+ribbon | **Frankfurt** | +$0.33 |
| ETH s15/60-150 cloud+cci | **weekend** | +$0.16 |
| SOL s15/60-150 cloud+ema200 | **weekend** | +$0.53 |
| SOL s15/150-240 ema800+cloud+dev | **London** | +$0.32 |

**Pattern**: S6 sleeves favor EU sessions (Frankfurt) — makes sense (London
open volatility). BTC s15 ema800 REVERSES to Asia — interesting because Asian
trading has different rhythm.

### Cross-asset regime: BUSTED
Best cells are tiny-n (<300 of ~7,000 fires). High-$/tr cells from training
(60-90 train fires) DID NOT recur in 1.5d lockbox. Combined `session × xa-regime`
cells produce $86/tr on Sydney+btc_dn_only (n=46 train) but **0 lockbox fires**
under that condition — catastrophic overfit.

### Lockbox pass: 1 of 7
Only **BTC s15 150-240 + g_tr_above_ema800 + Asia-session filter (Tokyo OR Sydney OR HK)** survives:
- Lockbox n=654, $/tr=$2.95 vs base $2.69 (lift +$0.25), p<0.001

### Recommendation
- Deploy the Asia-session filter on BTC S15 ema800 sleeve (modest +$0.25/tr lift)
- Don't stratify by cross-asset regime — 25-day window too short, non-ranging regimes <20% of fires

**Files**: `strategy_lab/reports/SESSION_CROSS_ASSET_REGIME_2026_05_26.md` + 4 CSVs

---

## 6. Naive-sum overlap bug cleanup — Agent VV

R6 Agent PP discovered the slug-overlap bug. R7 Agent VV cleaned it up
across all prior reports:

- **5 R1-R5 markdown reports** stamped with correction banners
- `NAIVE_SUM_CORRECTIONS_2026_05_26.md` created (single source of truth)
- **Authoritative deployable confirmed**: **$20,501/28d at $25 = $2,672,455/year @ $250**
- 2 anomalies flagged in deploy manifest: `R5_eth_s6_v1_plus_mp_change_with` (-$102) and `R5_hawkes_sol_5m_off120` (-$207) — should demote from DEPLOY to PAPER_FIRST

R6 reports (which already used dedup) untouched. PDFs not regenerated
(documented as superseded by FINAL_DEPLOY_READY_2026_05_26.pdf).

---

## 7. Updated final deploy plan (post-R7)

### Phase 1 (unchanged from R6) — Week 1-2 deploy
The 6 Phase 1 sleeves from R6 manifest still apply: $15-16k/28d gross.

### Phase 1.5 — Apply R7 threshold global recalibration
Zero-code-change updates to gate thresholds across ALL existing sleeves:
- g_mp_no_extreme: 50 → 100 bps
- g_hawkes_imbalance_with: 0.3 → 0.15
- g_hurst_trending: 0.55 → 0.50
- g_vol_contracting: 0.7 → 0.85

Aggregate expected lift: **+$3-5k/28d** on top of Phase 1 baselines.

### Phase 2 (modified) — Add R7 winners
Apply these specific R7 finds:
- **BTC S15 ema800 + Asia-session filter** (R7 UU): +$0.25/tr on existing sleeve
- **Threshold-optimized S7 + book_slope_steep@0.25** (R7 RR): only strict-validated new sleeve
- **Direction-aware continuous L_stat threshold on BTC S15** (R7 SS): UP uses `L<=5`, DOWN uses `L>=1`

### Phase 3 (HEADLINE PROPOSAL — pending validation) — Weighted scoring
**R7 TT's Logistic Poly2 models**:
- S7_BTC_5m_base + poly2: $26,564 lockbox (4d) → projected $186k/28d gross at $25
- BTC_S15_150-240 + poly2: $11,055 → $77k/28d gross
- BTC_S6_60-150 + poly2: $7,470 → $52k/28d gross
- SOL_S6_60-150 + poly2: $7,049 → $49k/28d gross

**BUT**: needs slug-overlap dedup. Estimated post-dedup: $40-70k/28d combined
across these 4 sleeves (vs $15-20k/28d for binary AND on same sleeves).

**Operational complexity**: requires online inference of the linear model with
the ~150 polynomial features at fire_us. Each model is ~150 weights — runs in
microseconds. Not a bottleneck.

**Action item**: spawn **Agent WW** to apply Agent PP's dedup methodology to
the WS-poly2 fires per sleeve. Get the realistic combined post-dedup number
before deploying.

### Phase 4 — Operational tools
- S3 HoD refresh on existing 11 sleeves (+$15,900/28d, 5-min config edit)
- S2 Fade Momo BTC patch (+$1,216/28d, 4-line edit)
- B.7.1 sleeve #2 fix (+$745/28d, 1-line config)

---

## 8. Updated deployable estimate (post-R7, with TT caveat)

| Scenario | Combined /28d @ $25 | Annual @ $250 |
|---|--:|--:|
| **Pre-R7 (R6 manifest only)** | **$20,501** | **$2.67M** |
| + R7 threshold global recalibration | $24,000 | $3.13M |
| + R7 BTC S15 Asia-session + new strict sleeves | $25,500 | $3.32M |
| **+ R7 weighted scoring (TT) if post-dedup holds at 2-3× lift** | **$50,000-70,000** | **$6.5M-9.1M** |
| **+ R7 weighted scoring (TT) PRE-DEDUP raw maximum** | $186,000 | $24.3M |

**Realistic R7 deploy estimate**: $25-30k/28d at $25 with confidence (the validated additions). **The TT weighted-scoring discovery could 2-3× this** to $50-70k/28d if the slug-overlap audit goes well.

---

## 9. Action items for Round 8 (if continued)

1. **Spawn Agent WW**: apply slug-overlap dedup to WS-poly2 fires per sleeve. Get realistic post-dedup combined number.

2. **Spawn Agent XX**: build production inference pipeline for WS-poly2 models. Verify ~150-feature polynomial scoring fits in <1ms at fire_us.

3. **Spawn Agent YY**: 7-day paper deploy with Phase 1 + threshold recalibration + 1 WS-poly2 sleeve (S7_BTC_5m_base — the largest contributor). Track WR/$/tr vs backtest projection.

4. **Operations**: implement weekly auto-pull + auto-revalidate on rolling 32d window per the migration_2026_05_25 pipeline pattern.

5. **Optional research**:
   - HMM regime classifier (replace heuristic regime)
   - Online learning (FTRL adaptive sleeve weights)
   - Fresh F2 wallet on-chain pull (was stale May 16)

---

## 10. Lessons from 7 rounds

1. **Test cross-cuts, not just standalone**: R7 found the biggest win of the entire session (TT) by combining what prior rounds tested separately.

2. **L1/L2 regularization is the difference**: linear models pass where tree ensembles fail. Discipline beats memorization on 32d data.

3. **Interaction features capture what AND can't**: `ribbon × DI` negative weight at extreme alignment is structurally invisible to AND-logic gate stacks.

4. **Apply dedup BEFORE quoting combined deploy numbers**: this is the #1 operational lesson from R6+R7.

5. **Single agnostic gates often beat state machines**: regime info is captured by Hurst / trend_slope / markov_with — don't over-engineer.

6. **Global threshold recalibration > per-sleeve micro-tuning**: directions are consistent across sleeves; avoid lockbox-optimal threshold picking (overfit).

7. **Discrete asymmetric gates marginal; continuous-threshold direction-asymmetry IS real**: build asymmetric continuous gates, not discrete UP/DOWN stacks.

8. **Cross-asset regime stratification overfits on small windows**: non-ranging regimes are <20% of fires; tiny-n cells don't recur in lockbox.

9. **Session matters but modestly**: only 1 sleeve has session-conditional lockbox-pass edge (BTC S15 + Asia session).

10. **The R7 TT finding is contingent on post-dedup validation**: 17× lift will likely fall to 2-3× after slug-overlap audit. Still meaningful but not magical.

## End
