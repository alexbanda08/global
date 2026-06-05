# Autonomous scalp / hedge / physics sweep — 2026-06-03

Universe: lag-taker fires re-filled @10Hz (n_filled=2533 of 2538). engine_v2 85ms latency, min_book_events=25, spread 0.05. $/tr win07-style; scalp round-trip fees shown at 0 / 0.015 / 0.07.

## Block 1 — Exit-timing sweep (deployed cell: BTC+ETH, delta>=5, entry_vwap<0.55)

| policy | n | scalp-WR | $/tr fee0 | $/tr 0.015 | $/tr 0.07 | t(0.015) | CI(0.015) |
|---|--:|--:|--:|--:|--:|--:|--:|
| HOLD-to-resolution | 118 | — | +0.138 | (same) | (same) | 0.06 | (-4.35, 4.75) |
| TIME+30s | 118 | 74.1 | +5.317 | +4.954 | +3.625 | 6.24 | [+3.41,+6.51] |
| TIME+45s | 118 | 75.0 | +5.924 | +5.564 | +4.244 | 6.9 | [+3.97,+7.1] |
| TIME+60s | 118 | 76.3 | +5.92 | +5.56 | +4.238 | 6.51 | [+3.9,+7.16] |
| TIME+75s | 118 | 72.9 | +5.686 | +5.331 | +4.028 | 5.62 | [+3.47,+7.2] |
| TIME+90s | 118 | 68.4 | +5.058 | +4.712 | +3.447 | 4.34 | [+2.61,+6.86] |
| TIME+120s | 118 | 62.6 | +3.797 | +3.473 | +2.283 | 2.63 | [+0.92,+6.01] |
| TIME+150s | 118 | 61.0 | +4.24 | +3.913 | +2.714 | 2.92 | [+1.35,+6.49] |
| TIME+180s | 118 | 62.4 | +4.141 | +3.83 | +2.691 | 2.57 | [+0.86,+6.74] |
| TP@0.60 (else +180/hold) | 118 | 89.7 | +3.92 | +3.547 | +2.179 | 5.44 | [+2.21,+4.74] |
| TP@0.65 (else +180/hold) | 118 | 83.8 | +4.784 | +4.423 | +3.1 | 5.18 | [+2.74,+6.04] |
| TP@0.70 (else +180/hold) | 118 | 77.8 | +5.425 | +5.077 | +3.802 | 4.92 | [+3.01,+7.0] |
| TP@0.75 (else +180/hold) | 118 | 71.8 | +5.614 | +5.28 | +4.055 | 4.35 | [+2.78,+7.51] |
| ORACLE best-exit (path max) | 118 | 98.3 | +18.778 | +18.498 | +17.473 | 22.1 | [+16.87,+20.08] |

## Block 2 — Physics volatility-regime gates (scalp TIME+60s, fee=0.015, deployed cell)

baseline (all w/ physics): n=118 $/tr=+5.56 t=6.51 CI(3.91, 7.3)

| gate | n | $/tr(0.015) | t | CI | WR>0 |
|---|--:|--:|--:|--:|--:|
| bucket=quiet <5 | 57 | +5.808 | 4.99 | [+3.59,+8.06] | 75.4 |
| bucket=normal 5-10 | 6 | +1.099 | 0.21 | [-8.12,+10.2] | 66.7 |
| bucket=active 10-15 | 5 | +3.233 | 0.54 | [-7.03,+14.9] | 60.0 |
| bucket=storm 15-25 | 7 | +2.327 | 0.68 | [-3.97,+8.23] | 71.4 |
| bucket=hurricane >=25 | 43 | +6.65 | 4.8 | [+3.9,+9.28] | 79.1 |
| dist_abs>=20 | 51 | +6.119 | 4.88 | [+3.63,+8.59] | 78.4 |
| dist_abs>=30 | 42 | +6.992 | 5.11 | [+4.31,+9.61] | 78.6 |
| dist_abs>=40 | 31 | +7.116 | 4.2 | [+3.85,+10.36] | 74.2 |
| dist_abs>=50 | 15 | +7.978 | 3.32 | [+3.18,+12.26] | 73.3 |
| speed_abs>=5 | 61 | +5.328 | 4.26 | [+2.87,+7.67] | 75.4 |
| speed_abs>=10 | 55 | +5.789 | 4.54 | [+3.2,+8.27] | 76.4 |
| speed_abs>=15 | 50 | +6.045 | 4.69 | [+3.47,+8.4] | 78.0 |
| speed_away>=10 | 46 | +5.651 | 4.0 | [+2.86,+8.32] | 76.1 |
| WEAK_COMBO_kept (dist>=30 OR away>=10) | 55 | +6.145 | 4.86 | [+3.66,+8.58] | 76.4 |
| d_speed>=0 (accelerating) | 51 | +4.623 | 4.08 | [+2.41,+6.79] | 76.5 |
| margin>0 (won't cross strike) | 92 | +5.032 | 5.06 | [+3.07,+6.94] | 72.8 |

## Block 3 — Hedge

### 3a. Stop-loss salvage on HOLD (cut held token at bid when it falls; vs pure hold)

| policy | n | $/tr(0.015) | t | CI |
|---|--:|--:|--:|--:|
| HOLD (control) | 118 | +0.138 | 0.06 | (-4.36, 4.71) |
| stop if bid<=entry-0.05 | 118 | +2.458 | 1.27 | [-1.41,+6.2] |
| stop if bid<=entry-0.1 | 118 | +1.612 | 0.78 | [-2.47,+5.7] |
| stop if bid<=entry-0.15 | 118 | +0.982 | 0.45 | [-3.14,+5.24] |
| stop if bid<=entry-0.2 | 118 | +0.659 | 0.3 | [-3.72,+4.93] |

### 3b. Buy-opposite hedge (buy lead + buy opposite token; paired, capped loss)

| hedge | n | $/tr(0.015) | t | CI | note |
|---|--:|--:|--:|--:|---|
| buy-opp @ oppask_30 (50% notional) | 118 | +1.207 | 0.96 | [-1.28,+3.68] | vs HOLD +0.138 |
| buy-opp @ oppask_60 (50% notional) | 118 | +1.423 | 1.15 | [-0.95,+3.82] | vs HOLD +0.138 |
| buy-opp @ opp_ask_min (50% notional) | 118 | +18.286 | 6.12 | [+12.98,+24.59] | vs HOLD +0.138 |

## Block 4 — Scalp TIME+60 by segment + universe generality (fee=0.015)

| cut | n | $/tr | t | CI |
|---|--:|--:|--:|--:|
| deployed cell (all seg) | 118 | +5.56 | 6.51 | [+3.86,+7.19] |
|   segment=fit_IS | 27 | +5.687 | 3.18 | [+2.25,+9.23] |
|   segment=fit_OOS | 35 | +4.269 | 2.65 | [+1.18,+7.53] |
|   segment=bwd_oos | 55 | +6.407 | 5.13 | [+3.88,+8.8] |
|   segment=fwd_oos | 1 | +0.715 | nan | [+nan,+nan] |
| BTC only | 61 | +6.95 | 5.83 | [+4.58,+9.25] |
| ETH only | 57 | +4.072 | 3.38 | [+1.77,+6.48] |
| no vwap filter (delta>=5) | 430 | +1.767 | 4.75 | [+1.06,+2.5] |
| vwap<0.55 ALL delta | 780 | +2.951 | 8.66 | [+2.29,+3.61] |
| delta>=3 & vwap<0.55 | 398 | +3.856 | 8.36 | [+2.95,+4.77] |
| delta>=5 & vwap<0.55 | 118 | +5.56 | 6.51 | [+3.91,+7.18] |
| delta>=8 & vwap<0.55 | 20 | +5.55 | 2.63 | [+1.45,+9.53] |
| delta>=10 & vwap<0.55 | 10 | +6.036 | 2.58 | [+1.56,+10.28] |

## Block 5 — Best scalp × best physics gate (stacked)

| stacked gate | n | TIME+60 $/tr | t | CI |
|---|--:|--:|--:|--:|
| storm+ (speed>=15) | 50 | +6.045 | 4.69 | [+3.42,+8.52] |
| active+ (speed>=10) | 55 | +5.789 | 4.54 | [+3.21,+8.26] |
| dist>=40 | 31 | +7.116 | 4.2 | [+3.76,+10.3] |
| d_speed>=0 | 51 | +4.623 | 4.08 | [+2.43,+6.82] |
| speed>=10 & d_speed>=0 | 23 | +5.314 | 3.68 | [+2.46,+7.94] |

## Block 2b — Physics gate WITHIN asset (confound control) → vol-gate is NOT real

The Block-2 "dist_abs improves scalp" was an **asset-selection artifact**: `dist_abs`/`speed_abs` are in $/$-per-min,
so a pooled `dist_abs>=30` threshold preferentially keeps BTC (where $30 is a tiny move) and BTC's scalp is
simply stronger than ETH's. Re-run with asset-scaled thresholds, separately per asset (scalp TIME+60, fee 0.015):

| asset | baseline | dist gate | speed gate | speed HIGH tertile | verdict |
|---|--:|--:|--:|--:|---|
| BTC | +6.95 (n=61) | dist≥40 +7.12 (n=31) | speed≥15 +6.07 | +5.34 (worse) | no lift (CIs overlap) |
| ETH | +4.07 (n=57) | dist≥0.8 +3.03 (worse) | speed≥0.5 +4.16 | +2.17 (worse) | no lift / slight hurt |

**Verdict: the volatility-regime gate does NOT add edge to the scalp once the asset confound is removed.**
If anything the HIGHEST-vol tertile is *worse* in both assets (the reprice is noisier/harder to time in storms).
`margin>0` (asset-neutral, minutes) is also inconsistent (BTC +7.21, ETH +2.32). The real levers are **asset
(BTC≫ETH)** and the **entry filters (delta≥5, vwap<0.55)** — not vol regime.

## FINAL VERDICT — autonomous sweep

1. **EXIT-SCALP confirmed STRONG and robust.** TIME+45–60s is optimal: deployed cell (BTC+ETH, δ≥5, vwap<0.55,
   n=118) = **+$5.56/tr fee=0.015, t=6.5, CI[+3.9,+7.2]; +$4.24/tr even at the worst-case 0.07 both-leg fee.**
   HOLD = +$0.14 (flat). Edge **decays after ~90s** (reprice fades) and is positive across **fit_OOS (t=2.65)
   and bwd_oos (t=5.13)**, both assets (BTC +6.95 > ETH +4.07), and scales cleanly (δ≥3,vwap<0.55 n=398
   +$3.86 t=8.36). TP@0.70 is a viable alternative (+$5.08). Oracle best-exit ceiling = +$18.5 → large headroom.
   **fwd_oos still n≈1 offline → the live shadow forward fires remain THE graduation gate.**
2. **PHYSICS / VOLATILITY GATE = dead** (within-asset, Block 2b). Does not improve the scalp; high-vol is worse.
3. **HEDGE = dead.** Stop-loss salvage on HOLD lifts it to +$2.46 (CI includes 0) but is far below just scalping;
   buy-opposite at a fixed exit offset is weak (+$1.2–1.4, CI includes 0). The +$18 `opp_ask_min` number is
   LOOKAHEAD (path-minimum ask) — not tradeable, shown only as a ceiling. **Always-sell at +60s dominates any
   hedge/salvage.**
4. **Best deployable config unchanged:** lag-taker entry (δ≥5, entry_vwap<0.55), **TIME+45–60s book-sell exit**,
   BTC-weighted. No vol gate, no hedge. Push the live shadow fires to ≥200 + CI>0.

## Block 6 — Exit refinement (TP-or-time, trailing) — nothing beats plain TIME+45/60

Deployed cell n=118, fee 0.015:
| policy | $/tr | t | CI |
|---|--:|--:|--:|
| **TIME+45** | **+5.56** | **6.9** | [+4.01,+7.12] |
| TIME+60 | +5.56 | 6.5 | [+3.86,+7.17] |
| TP70-or-time60 | +5.18 | 7.8 | [+3.86,+6.46] |
| TP65-or-time60 | +4.72 | 8.2 | [+3.53,+5.80] |
| trailing-stop 0.05 | +4.86 | 5.0 | [+2.96,+6.73] |

**TIME+45 wins on $/tr AND t** (highest t=6.9 = lowest variance). TP-or-time combos cut the mean but raise t
(consistency) — `TP70-or-time60` is the best risk-adjusted alt. Trailing stops add nothing. **Recommendation:
move the deployed exit from +60s → +45s** (marginally higher, lower-variance); keep TP70-or-time60 as a
variance-reduced shadow arm. At worst-case 0.07 fee, TIME+45 still +$4.24/tr t=5.2.
