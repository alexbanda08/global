# Scalp harness bug-fix rerun — old vs corrected (2026-06-10)

Corrected runners (`*_fixed_2026_06_10.py` + shared `scalp_fill_lib_2026_06_10.py`) fix three bugs:
(1) **outcome-as-price exit leak** (held-to-resolution settlement instead), (2) **exit size ignored**
(sell capped at best-bid size, remainder held), (3) **BBO size==0 collector artifact** that phantom-skipped
~40% of entries (now resolved → recovered entries). Every cell reports **ALL** (incl. held-to-resolution lots,
honest lower bound) and **CLEAN** (fully sold, like-for-like with the old optimistic numbers).

Phantom-entry recovery confirmed in every OOS coin (`old-fallback-incidence=0`): BTC 435/466 filled (was the
~30 that the artifact dropped), ETH 677/734, SOL 750/873, XRP 481/609, DOGE 405/986, BNB 86/290.

## (1) MASTER TABLE

| Test | Cell | OLD | NEW-CLEAN | NEW-ALL | Verdict change |
|---|---|---|---|---|---|
| OOS gated vwap<0.55 | BTC | +2.38 | +2.060 (CI>0) | +1.798 (CI~0) | ✔ unchanged (CLEAN holds) |
| OOS gated vwap<0.55 | ETH | +1.92 | +1.510 (CI>0) | +1.470 (CI>0) | ✔ unchanged |
| OOS gated vwap<0.55 | SOL | +2.16 | +2.051 (CI>0) | +2.204 (CI>0) | ✔ unchanged |
| OOS gated vwap<0.55 | DOGE | +1.40 | +1.111 (CI~0) | +0.261 (CI~0) | ⚠ weaker-but-alive (thin book) |
| OOS gated vwap<0.55 | BNB | (new) | +3.446 (CI>0) | +5.654 (CI>0) | ✔ alive |
| OOS gated vwap<0.55 | XRP | +2.20 | +2.664 (CI>0) | +2.096 (CI>0) | ✔ unchanged |
| OOS pooled gated | BTC+ETH+SOL (n=751) | +0.928 t=4.41 | +1.853 t=5.60 | +1.854 t=4.39 | ✔ unchanged (stronger) |
| **STOP (paired stopON−OFF)** | BTC+ETH+SOL | **+0.88 SIG** | **−3.146 SIG−** | **−2.790 SIG−** | **❌ flips-dead** |
| STOP (paired) | DOGE+BNB | +0.88 | −1.477 SIG− | −1.238 SIG− | ❌ flips-dead |
| STOP (paired) | XRP | +0.88 | −1.806 SIG− | −1.665 SIG− | ❌ flips-dead |
| TOD 22-02 (pooled) | BTCETHSOL | +1.954 | +3.670 | +4.357 | ✔ unchanged (22-02>base) |
| TOD exclude{12,17} | BTCETHSOL | +0.966 | +1.954 | +1.952 | ✔ unchanged (≥base) |
| TOD dead{12,17} only | BTCETHSOL | +0.511 | +0.578 (CI~0) | +0.519 (CI~0) | ✔ unchanged (dead) |
| Mid-window +5s gated | BTC+ETH 15m | +1.84 t=2.71 | +1.895 t=3.14 | +2.044 t=2.49 | ✔ unchanged |
| Mid-window +120s gated | BTC+ETH 15m | +3.55 (CI>0) | +2.038 (CI~0) | +1.146 (CI~0) | ⚠ weaker, loses CI |
| Mid-window pooled off≥120 | BTC+ETH | +0.25 t=0.38 | +1.145 (CI~0) | +2.496 (CI~0) | ✔ unchanged (still no CI) |
| FVG open +5s | SOL 15m | +2.29 t=3.38 | +3.205 t=4.25 | +3.120 t=4.18 | ✔ unchanged (only strong open) |
| FVG mid first-cross | ETH+SOL pooled | neg t=−4..−6 | neg (thr.04 −1.4..−1.6) | neg | ✔ unchanged (dead) |
| FVG mid off≥120 split | ETH+SOL | mostly neg | −0.290 | +0.202 (CI~0) | ✔ unchanged (no robust mid) |
| Cross-asset OWN +5s | pooled | +1.77 t=3.96 | +1.2..+2.8 (per cell) | +1.4..+3.0 | ✔ unchanged |
| Cross-asset BTC +5s | pooled | +1.79 t=3.01 | ≈OWN, no excess | ≈OWN | ✔ unchanged (no beat) |
| Cross-asset BTCLEAD | pooled | dead/neg | neg | neg | ✔ unchanged (dead) |
| Trailing f60 | pooled (n=748) | +1.92 t=4.83 | +1.869 t=5.63 | +1.935 t=4.57 | ✔ unchanged |
| Trailing 5s_.05 (paired vs f60) | pooled | −1.82 t=−2.99 | — | −2.455 t=−4.79 | ✔ unchanged (dead) |
| Trailing 1s_.05 (paired) | pooled | −7.01 | — | −7.437 | ✔ unchanged (dead) |
| Trailing 5s_peak (oracle) | pooled | +16.96 | +16.59 | +16.55 | ✔ unchanged (untradeable) |
| Entry-opt +1s | pooled | +3.27 | +3.443 | +2.752 | ✔ unchanged |
| Entry-opt +5s | pooled | +1.77 | +1.752 | +1.872 | ✔ unchanged |
| Entry-opt +10s | pooled | −0.08 | +0.116 (CI~0) | +0.992 | ✔ unchanged (plateau edge) |
| Entry-opt +15s | pooled | −0.11 | +0.198 (CI~0) | +1.645 | ✔ unchanged (CLEAN decays to 0) |
| Entry-opt band [5,12] @+5s | pooled | +3.41 | +3.579 | +2.414 | ✔ unchanged |
| Entry-opt band [8,∞) @+5s | pooled | +4.56 | +5.394 | +2.794 | ✔ unchanged |
| **Maker-exit (maker−taker60)** | pooled (n=780) | **+0.42 CI[+0.02,+0.82]** | **+0.318 ns** | **−0.073 ns** | **❌ flips-dead** |
| Maker-exit OOS | n=312 | (pos) | +0.108 ns | −0.212 ns | ❌ flips-dead |
| Low-vol baseline | pooled | +0.93 t=4.41 | — | +0.593 t=2.97 | ⚠ weaker but alive |
| Low-vol time-split | TRAIN/TEST | +1.54 / +1.14 (CI>0) | — | +1.522 / +0.980 (CI>0) | ✔ unchanged (both pass) |
| Low-vol coin-split | SOL TEST | failed | — | +1.272 (CI~0) | ✔ unchanged (still fails) |

`CI~0` = bootstrap CI brackets 0 (not significant). `SIG−` = significantly negative.

## (2) Per-test detail

### Scalp OOS (step 1)
n recovered vs old: every coin gained the phantom-skipped entries (old-fallback-incidence=0 confirms no
outcome-leak). frac_held tiny (BTC/ETH/SOL/XRP ~0.04, DOGE/BNB ~0.10 thin books) → ALL≈CLEAN.
Per-coin gated CLEAN all CI>0 except DOGE (CI~0) — DOGE is the one weak coin (filled only 405/986, thin BBO).
Pooled BTCETHSOL gated +1.85/+1.85 (ALL/CLEAN), t≈5 → **scalp open edge survives the corrected harness, stronger
than the old +0.928** (old number was depressed by the phantom-skip removing good fires).
**Interpretation: bug-fix does NOT change the open-scalp conclusion — it confirms it.**

### STOP (step 1, paired)
Old: +0.88/tr, "SIG, validated 3×". New paired stopON−stopOFF: BTCETHSOL **−2.79 (ALL) / −3.15 (CLEAN) SIG−**,
DOGE+BNB −1.24/−1.48 SIG−, XRP −1.67/−1.81 SIG−. The corrected size-capped stop (resolve artifact sizes, sell
at the real bid, hold remainder) consistently **destroys** edge vs plain +60 exit.
**Interpretation: the old +0.88 STOP edge was a harness artifact. STOP flips dead.** See §(4).

### Mid-window (step 2)
+5s open holds (+2.044 ALL CI>0). **+120s loses its CI** (old +3.55 CI>0 → new +1.146 ALL CI~0 / +2.038 CLEAN
CI~0). Pooled off≥120 ALL +2.496 but CI~0 (huge +600/+720s cells are tiny-n, t<1.5, held-lot noise).
**Interpretation: only the +5s open survives; mid-window stays not-deployable (unchanged).**

### FVG (step 3)
Grid 132,177 rows. OPEN off<120 ALL +0.664 CI>0 (weak); MID off≥120 ALL +0.202 CI~0 / CLEAN −0.290. Per-offset:
SOL 15m open +5s cheap +3.205 t=4.25 (the one strong open cell, stronger than old +2.29). First-cross MID
negative at low thresholds (−1.1..−1.7 SIG−). MID-verdict mixed (ETH+, SOL flat/neg).
**Interpretation: unchanged — FVG open is the only edge, mid-window FVG dead.**

### Cross-asset (step 4)
OWN +5s positive across coins (+1.4..+3.0); BTC-follow +5s ≈ OWN, never exceeds it; CONFL early offsets
positive but small-n; BTCLEAD negative at most offsets/coins.
**Interpretation: unchanged — own-token +5s is the edge, cross-asset follow doesn't beat it, BTCLEAD dead.**

### Trailing (step 5)
748 cheap-gated fires. f60 +1.935 (matches old +1.92). Every trailing-stop policy paired vs f60 is negative
(5s_.05 −2.455, 5s_.08 −3.695, 1s_.05 −7.437 SIG−). peak +16.5 = oracle upper bound (untradeable).
**Interpretation: unchanged — no trailing exit beats fixed-60.**

### Entry-opt (step 6)
Plateau intact: +1s +2.75, +2s +2.10, +3s +2.37, +5s +1.87 (ALL, all CI>0). CLEAN decays past +8s (CLEAN +10s
+0.12, +15s +0.20 → ~0, matching old's slightly-negative tail). Delta bands monotone: [4,12] +2.79, [5,12]
+2.41(ALL)/+3.58(CLEAN), [8,∞) +2.79(ALL)/+5.39(CLEAN).
**Interpretation: unchanged — early-offset + higher-delta plateau holds.**

### Maker-exit (step 7)
780 gated BTC/ETH fires. taker60 baseline +2.280. maker queue-fixed +2.207, peg-trail +2.207. Paired
maker−taker60 = **−0.073 / −0.073, ns** (CI brackets 0); OOS −0.212 / −0.113 ns; not positive on both BTC+ETH.
**Interpretation: the old +0.42 maker-beats-taker edge was the exit-size/leak artifact. Maker-exit flips dead.** See §(4).

### Low-vol gate (step 8)
2254 corrected fires. Baseline +0.593 (old +0.93 — corrected harness lowers pooled mean). Time-split lowVol
TRAIN +1.522 / TEST +0.980 both CI>0 (passes both halves). Coin-split SOL-test lowVol +1.272 CI~0 (FAILS).
Terciles: LOW +1.521 t=5.01, MID ~0, HIGH +0.251.
**Interpretation: unchanged — low-vol is a real low-vs-hi separation and passes the time-split, but the coin-split
still fails → monitor, not a deployable gate.**

## (3) FALSE-NEGATIVE verdict (the central question)

Did the corrected harness REVIVE any previously-killed strategy? **No.** Every previously-dead/weak variant
stays dead or weak under the fix:

- **Mid-window scalp:** still dead beyond +5s (+120s lost its CI; pooled off≥120 no CI). NOT revived.
- **FVG mid-window:** still dead (mid first-cross negative; off≥120 split CI~0/negative). NOT revived.
- **Cross-asset (BTC-follow / BTCLEAD):** still doesn't beat own-token; BTCLEAD still negative. NOT revived.
- **Trailing exits:** still all-negative vs fixed-60. NOT revived.
- **Low-vol gate:** still fails the coin-split (monitor-only). NOT revived.
- **Maker-exit:** previously *alive* (+0.42) — the fix **kills** it (now ns). This is the opposite of a false
  negative: it was a **false POSITIVE** caused by the bug.

The corrected harness did NOT flip any dead strategy to alive. Two previously-"alive" results flip dead
(STOP, maker-exit) — both were bug-induced false positives. The genuine open-scalp edge (open +5s, vwap<0.55,
delta-gated, TOD-gated) survives and is actually *stronger* once the phantom-skipped good fires are restored.

## (4) STOP verdict

Old claim: STOP at (fill−0.10) adds **+0.88/tr, SIG, validated 3×** (CLAUDE.md / `project_scalp_exit_config`
memory says "STOP ON").

Corrected full-sample paired (stopON − stopOFF=+60), gated vwap<0.55:

| Coin set | ALL paired | CLEAN paired |
|---|---|---|
| BTC+ETH+SOL (n=751/666) | **−2.790** CI[−3.476,−2.127] SIG− | **−3.146** CI[−3.868,−2.418] SIG− |
| DOGE+BNB (n=309/259) | −1.238 CI[−2.058,−0.522] SIG− | −1.477 CI[−2.443,−0.624] SIG− |
| XRP (n=218/201) | −1.665 CI[−2.831,−0.604] SIG− | −1.806 CI[−3.135,−0.661] SIG− |

stopON $/tr is negative-to-flat (BTCETHSOL ALL −0.936, CLEAN −1.293) while stopOFF (+60) is +1.85. The stop
fires on transient bid dips (size-capped real-bid sell + held remainder) and gives back edge every time.

**The +0.88 STOP edge does not replicate. Under the corrected size-capped/no-leak model the stop is
significantly NEGATIVE on all coin sets.** This contradicts the deployed config ("STOP ON") and the
`project_scalp_exit_config` memory — the stop should be **disabled**, not kept. Recommend re-validating the
live shadow stop against the corrected model before trusting it.

---
Artifacts: `strategy_lab/directional/_results/{oos_btcethsol_fixed,oos_dogebnb_fixed,oos_xrp_fixed,midwindow_fixed,
fvg_fixed,fvg_analyze_fixed,xasset_fixed,trailing_fixed,entryopt_fixed,makerexit_fixed,lowvol_fixed}.log` +
`scalp_oos_bbo_fires_fixed_2026_06_10*.parquet`, `scalp_fvg_grid_fixed_2026_06_10.parquet`,
`scalp_{midwindow,xasset,trailing,entryopt}_fixed_2026_06_10*.parquet`, `maker_exit_fixed_2026_06_10.parquet`.
New scripts: `fvg_analyze_fixed_2026_06_10.py`, `scalp_lowvol_gate_fixed_2026_06_10.py` (input-glob edits only).
