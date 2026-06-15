# GATE-SOFTENING SWEEP — BNB / XRP / DOGE (2026-06-11)

Open exit-scalp (fire slot_start+5s on binance-moved side, $25 @ best_ask +85ms, corrected +60s SELL exit). Cheap gate ev<0.55 applied. BBO window = Apr 2026 regime.

**Question:** loosening the spread filter (and/or delta gate) — does the edge survive (CI>0) or die?


**Pre-registered verdict rule:** soften to spread_max=X is SAFE for a coin iff the INCREMENTAL band (0.05,X] cell has $/tr >= 0 (CI not sig-negative) AND the cumulative cell at X keeps CI>0 (CLEAN). Delta floor stays 3 unless delta in [2,3) incremental is CI>0.


## BNB  (gated ev<0.55, n=143)


### BNB matrix — ALL

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n= 117 $tr=+3.002 t=+2.67 CI=[+0.728,+5.147] | n=  48 $tr=+5.088 t=+2.63 CI=[+1.260,+8.800] | n=  13 $tr=+8.133 t=+2.22 CI=[+0.620,+14.363] |
| spread<=0.06 | n= 124 $tr=+2.629 t=+2.38 CI=[+0.541,+4.762] | n=  51 $tr=+5.242 t=+2.87 CI=[+1.755,+8.700] | n=  14 $tr=+7.897 t=+2.32 CI=[+0.969,+13.769] |
| spread<=0.07 | n= 125 $tr=+2.454 t=+2.21 CI=[+0.294,+4.567] | n=  51 $tr=+5.242 t=+2.87 CI=[+1.674,+8.647] | n=  14 $tr=+7.897 t=+2.32 CI=[+0.968,+13.816] |
| spread<=0.08 | n= 128 $tr=+2.626 t=+2.41 CI=[+0.510,+4.755] | n=  53 $tr=+5.483 t=+3.10 CI=[+2.021,+8.978] | n=  15 $tr=+7.822 t=+2.47 CI=[+1.240,+13.491] |
| spread<=0.10 | n= 140 $tr=+2.738 t=+2.70 CI=[+0.794,+4.663] | n=  60 $tr=+5.432 t=+3.43 CI=[+2.320,+8.418] | n=  16 $tr=+7.771 t=+2.63 CI=[+1.786,+12.961] |
| spread<=0.12 | n= 143 $tr=+2.636 t=+2.63 CI=[+0.662,+4.620] | n=  62 $tr=+5.052 t=+3.23 CI=[+1.964,+8.133] | n=  16 $tr=+7.771 t=+2.63 CI=[+1.874,+13.005] |

### BNB matrix — CLEAN (frac_held==0)

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n=  97 $tr=+2.377 t=+2.83 CI=[+0.729,+4.029] | n=  36 $tr=+3.205 t=+2.15 CI=[+0.196,+5.972] | n=   9 $tr=+7.114 t=+3.07 CI=[+2.771,+11.323] |
| spread<=0.06 | n= 103 $tr=+2.236 t=+2.69 CI=[+0.553,+3.822] | n=  39 $tr=+3.550 t=+2.54 CI=[+0.707,+6.172] | n=  10 $tr=+6.885 t=+3.30 CI=[+3.234,+10.716] |
| spread<=0.07 | n= 104 $tr=+2.029 t=+2.39 CI=[+0.326,+3.643] | n=  39 $tr=+3.550 t=+2.54 CI=[+0.766,+6.179] | n=  10 $tr=+6.885 t=+3.30 CI=[+3.088,+10.800] |
| spread<=0.08 | n= 107 $tr=+2.247 t=+2.68 CI=[+0.552,+3.905] | n=  41 $tr=+3.945 t=+2.88 CI=[+1.297,+6.517] | n=  11 $tr=+6.874 t=+3.65 CI=[+3.219,+10.382] |
| spread<=0.10 | n= 119 $tr=+2.418 t=+3.07 CI=[+0.811,+3.975] | n=  48 $tr=+4.105 t=+3.37 CI=[+1.658,+6.495] | n=  12 $tr=+6.885 t=+4.00 CI=[+3.798,+10.047] |
| spread<=0.12 | n= 122 $tr=+2.306 t=+2.96 CI=[+0.758,+3.804] | n=  50 $tr=+3.687 t=+3.02 CI=[+1.223,+5.968] | n=  12 $tr=+6.885 t=+4.00 CI=[+3.647,+10.195] |

### BNB INCREMENTAL spread bands (delta>=3) — the decisive marginal-fire cell

| band | ALL | CLEAN |
|---|---|---|
| (<= 0.05] baseline | n=  48 $tr=+5.088 t=+2.63 CI=[+1.397,+8.866] | n=  36 $tr=+3.205 t=+2.15 CI=[+0.186,+5.949] |
| (0.05, 0.06] | n=   3 (few) | n=   3 (few) |
| (0.05, 0.07] | n=   3 (few) | n=   3 (few) |
| (0.05, 0.08] | n=   5 $tr=+9.273 t=+3.86 CI=[+5.213,+13.554] | n=   5 $tr=+9.273 t=+3.86 CI=[+5.213,+13.554] |
| (0.05, 0.10] | n=  12 $tr=+6.805 t=+3.72 CI=[+3.185,+9.989] | n=  12 $tr=+6.805 t=+3.72 CI=[+3.130,+10.032] |
| (0.05, 0.12] | n=  14 $tr=+4.928 t=+2.30 CI=[+0.659,+8.613] | n=  14 $tr=+4.928 t=+2.30 CI=[+0.532,+8.624] |

### BNB delta [2,3) incremental (spread<=0.05)

- ALL: n=  69 $tr=+1.550 t=+1.16 CI=[-1.049,+4.217]
- CLEAN: n=  61 $tr=+1.888 t=+1.87 CI=[-0.048,+3.809]


**BNB recommendation: soften to spread_max=0.12** — incremental band $/tr=+4.928; delta in [2,3) helps = False.


### BNB live-volume estimate (approx)

spread-skips=234 over 30.0h (~187/day). Median skip spread p50=0.14.

| spread_max | approx frac of skips <=X | extra evals/day |
|---|---|---|
| 0.05 | 0.00 | 0 |
| 0.06 | 0.06 | 10 |
| 0.07 | 0.11 | 21 |
| 0.08 | 0.17 | 31 |
| 0.10 | 0.28 | 52 |
| 0.12 | 0.39 | 73 |
(approximate — linear interp from stated median/decile; books today are WIDER than the Apr BBO window so live fill rate may be lower.)


## XRP  (gated ev<0.55, n=569)


### XRP matrix — ALL

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n= 543 $tr=+1.134 t=+2.42 CI=[+0.160,+2.047] | n= 226 $tr=+1.985 t=+2.58 CI=[+0.450,+3.471] | n=  78 $tr=+3.052 t=+1.97 CI=[+0.074,+6.002] |
| spread<=0.06 | n= 553 $tr=+1.155 t=+2.49 CI=[+0.231,+2.075] | n= 231 $tr=+1.892 t=+2.48 CI=[+0.410,+3.414] | n=  80 $tr=+3.046 t=+2.02 CI=[+0.072,+5.901] |
| spread<=0.07 | n= 557 $tr=+1.169 t=+2.54 CI=[+0.296,+2.044] | n= 234 $tr=+1.907 t=+2.54 CI=[+0.384,+3.359] | n=  81 $tr=+3.092 t=+2.07 CI=[+0.178,+6.031] |
| spread<=0.08 | n= 559 $tr=+1.180 t=+2.57 CI=[+0.275,+2.060] | n= 236 $tr=+1.928 t=+2.58 CI=[+0.461,+3.366] | n=  81 $tr=+3.092 t=+2.07 CI=[+0.213,+5.931] |
| spread<=0.10 | n= 564 $tr=+1.115 t=+2.43 CI=[+0.222,+2.006] | n= 240 $tr=+1.752 t=+2.35 CI=[+0.210,+3.246] | n=  81 $tr=+3.092 t=+2.07 CI=[+0.203,+5.964] |
| spread<=0.12 | n= 569 $tr=+1.125 t=+2.46 CI=[+0.240,+2.017] | n= 241 $tr=+1.829 t=+2.45 CI=[+0.382,+3.287] | n=  81 $tr=+3.092 t=+2.07 CI=[+0.195,+5.981] |

### XRP matrix — CLEAN (frac_held==0)

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n= 501 $tr=+1.470 t=+3.74 CI=[+0.706,+2.257] | n= 206 $tr=+2.688 t=+4.22 CI=[+1.435,+3.919] | n=  67 $tr=+5.308 t=+4.57 CI=[+3.031,+7.526] |
| spread<=0.06 | n= 511 $tr=+1.486 t=+3.81 CI=[+0.735,+2.237] | n= 211 $tr=+2.570 t=+4.04 CI=[+1.294,+3.810] | n=  69 $tr=+5.235 t=+4.64 CI=[+3.110,+7.418] |
| spread<=0.07 | n= 515 $tr=+1.498 t=+3.87 CI=[+0.740,+2.252] | n= 214 $tr=+2.577 t=+4.11 CI=[+1.366,+3.783] | n=  70 $tr=+5.257 t=+4.73 CI=[+3.070,+7.420] |
| spread<=0.08 | n= 517 $tr=+1.509 t=+3.91 CI=[+0.764,+2.266] | n= 216 $tr=+2.594 t=+4.16 CI=[+1.411,+3.793] | n=  70 $tr=+5.257 t=+4.73 CI=[+3.133,+7.464] |
| spread<=0.10 | n= 522 $tr=+1.435 t=+3.71 CI=[+0.672,+2.186] | n= 220 $tr=+2.389 t=+3.80 CI=[+1.155,+3.622] | n=  70 $tr=+5.257 t=+4.73 CI=[+3.094,+7.373] |
| spread<=0.12 | n= 527 $tr=+1.443 t=+3.72 CI=[+0.665,+2.222] | n= 221 $tr=+2.471 t=+3.91 CI=[+1.243,+3.702] | n=  70 $tr=+5.257 t=+4.73 CI=[+3.046,+7.368] |

### XRP INCREMENTAL spread bands (delta>=3) — the decisive marginal-fire cell

| band | ALL | CLEAN |
|---|---|---|
| (<= 0.05] baseline | n= 226 $tr=+1.985 t=+2.58 CI=[+0.417,+3.438] | n= 206 $tr=+2.688 t=+4.22 CI=[+1.410,+3.946] |
| (0.05, 0.06] | n=   5 $tr=-2.301 t=-0.41 CI=[-13.726,+4.178] | n=   5 $tr=-2.301 t=-0.41 CI=[-13.689,+4.141] |
| (0.05, 0.07] | n=   8 $tr=-0.279 t=-0.08 CI=[-7.709,+4.309] | n=   8 $tr=-0.279 t=-0.08 CI=[-7.572,+4.315] |
| (0.05, 0.08] | n=  10 $tr=+0.660 t=+0.22 CI=[-5.889,+5.033] | n=  10 $tr=+0.660 t=+0.22 CI=[-5.728,+5.072] |
| (0.05, 0.10] | n=  14 $tr=-2.006 t=-0.67 CI=[-7.996,+3.200] | n=  14 $tr=-2.006 t=-0.67 CI=[-7.939,+3.163] |
| (0.05, 0.12] | n=  15 $tr=-0.509 t=-0.16 CI=[-6.776,+5.284] | n=  15 $tr=-0.509 t=-0.16 CI=[-6.702,+5.201] |

### XRP delta [2,3) incremental (spread<=0.05)

- ALL: n= 317 $tr=+0.527 t=+0.90 CI=[-0.622,+1.667]
- CLEAN: n= 295 $tr=+0.618 t=+1.26 CI=[-0.342,+1.561]


**XRP recommendation: soften to spread_max=0.08** — incremental band $/tr=+0.660; delta in [2,3) helps = False.


### XRP live-volume estimate (approx)

spread-skips=52 over 30.0h (~42/day). Median skip spread p50=0.08, p10=0.05.

| spread_max | approx frac of skips <=X | extra evals/day |
|---|---|---|
| 0.05 | 0.00 | 0 |
| 0.06 | 0.23 | 10 |
| 0.07 | 0.37 | 15 |
| 0.08 | 0.50 | 21 |
| 0.10 | 0.55 | 23 |
| 0.12 | 0.59 | 25 |
(approximate — linear interp from stated median/decile; books today are WIDER than the Apr BBO window so live fill rate may be lower.)


## DOGE  (gated ev<0.55, n=568)


### DOGE matrix — ALL

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n= 455 $tr=+0.488 t=+0.89 CI=[-0.606,+1.534] | n= 272 $tr=+0.364 t=+0.48 CI=[-1.096,+1.811] | n=  97 $tr=+0.741 t=+0.55 CI=[-1.786,+3.340] |
| spread<=0.06 | n= 478 $tr=+0.685 t=+1.28 CI=[-0.325,+1.738] | n= 284 $tr=+0.492 t=+0.67 CI=[-0.939,+1.958] | n=  99 $tr=+0.838 t=+0.63 CI=[-1.736,+3.371] |
| spread<=0.07 | n= 503 $tr=+0.607 t=+1.18 CI=[-0.406,+1.604] | n= 298 $tr=+0.508 t=+0.72 CI=[-0.862,+1.859] | n= 104 $tr=+0.957 t=+0.75 CI=[-1.489,+3.470] |
| spread<=0.08 | n= 522 $tr=+0.587 t=+1.17 CI=[-0.369,+1.575] | n= 309 $tr=+0.536 t=+0.78 CI=[-0.813,+1.887] | n= 107 $tr=+1.217 t=+0.97 CI=[-1.191,+3.594] |
| spread<=0.10 | n= 546 $tr=+0.668 t=+1.38 CI=[-0.270,+1.591] | n= 323 $tr=+0.750 t=+1.12 CI=[-0.590,+2.032] | n= 113 $tr=+1.605 t=+1.33 CI=[-0.869,+4.031] |
| spread<=0.12 | n= 568 $tr=+0.691 t=+1.46 CI=[-0.240,+1.614] | n= 330 $tr=+0.847 t=+1.28 CI=[-0.481,+2.122] | n= 115 $tr=+1.505 t=+1.27 CI=[-0.826,+3.774] |

### DOGE matrix — CLEAN (frac_held==0)

| spread<= \ delta>= | d2 | d3 | d5 |
|---|---|---|---|
| spread<=0.05 | n= 399 $tr=+0.913 t=+2.13 CI=[+0.036,+1.775] | n= 230 $tr=+0.993 t=+1.76 CI=[-0.108,+2.068] | n=  79 $tr=+1.775 t=+1.74 CI=[-0.264,+3.748] |
| spread<=0.06 | n= 421 $tr=+1.059 t=+2.52 CI=[+0.213,+1.886] | n= 241 $tr=+1.017 t=+1.87 CI=[-0.048,+2.079] | n=  81 $tr=+1.868 t=+1.86 CI=[-0.131,+3.805] |
| spread<=0.07 | n= 446 $tr=+0.950 t=+2.34 CI=[+0.143,+1.743] | n= 255 $tr=+1.007 t=+1.91 CI=[-0.025,+2.028] | n=  86 $tr=+1.953 t=+2.05 CI=[+0.076,+3.741] |
| spread<=0.08 | n= 465 $tr=+0.913 t=+2.28 CI=[+0.120,+1.699] | n= 266 $tr=+1.018 t=+1.94 CI=[-0.015,+2.070] | n=  89 $tr=+2.231 t=+2.34 CI=[+0.384,+4.068] |
| spread<=0.10 | n= 489 $tr=+0.987 t=+2.53 CI=[+0.200,+1.735] | n= 280 $tr=+1.242 t=+2.41 CI=[+0.256,+2.260] | n=  95 $tr=+2.628 t=+2.83 CI=[+0.785,+4.397] |
| spread<=0.12 | n= 511 $tr=+0.999 t=+2.62 CI=[+0.234,+1.748] | n= 287 $tr=+1.341 t=+2.62 CI=[+0.325,+2.329] | n=  97 $tr=+2.489 t=+2.72 CI=[+0.655,+4.263] |

### DOGE INCREMENTAL spread bands (delta>=3) — the decisive marginal-fire cell

| band | ALL | CLEAN |
|---|---|---|
| (<= 0.05] baseline | n= 272 $tr=+0.364 t=+0.48 CI=[-1.118,+1.831] | n= 230 $tr=+0.993 t=+1.76 CI=[-0.122,+2.071] |
| (0.05, 0.06] | n=  12 $tr=+3.402 t=+1.31 CI=[-1.174,+8.689] | n=  11 $tr=+1.518 t=+0.78 CI=[-2.199,+5.201] |
| (0.05, 0.07] | n=  26 $tr=+2.015 t=+1.19 CI=[-1.145,+5.344] | n=  25 $tr=+1.130 t=+0.75 CI=[-1.692,+4.025] |
| (0.05, 0.08] | n=  37 $tr=+1.801 t=+1.14 CI=[-1.262,+4.818] | n=  36 $tr=+1.181 t=+0.79 CI=[-1.595,+4.072] |
| (0.05, 0.10] | n=  51 $tr=+2.812 t=+2.13 CI=[+0.292,+5.401] | n=  50 $tr=+2.386 t=+1.87 CI=[-0.068,+4.776] |
| (0.05, 0.12] | n=  58 $tr=+3.112 t=+2.49 CI=[+0.740,+5.633] | n=  57 $tr=+2.743 t=+2.26 CI=[+0.374,+5.180] |

### DOGE delta [2,3) incremental (spread<=0.05)

- ALL: n= 183 $tr=+0.672 t=+0.85 CI=[-0.904,+2.194]
- CLEAN: n= 169 $tr=+0.803 t=+1.21 CI=[-0.487,+2.103]


**DOGE recommendation: soften to spread_max=0.12** — incremental band $/tr=+3.112; delta in [2,3) helps = False.


### DOGE live-volume estimate (approx)

spread-skips=192 over 30.0h (~154/day). Median skip spread p50=0.11.

| spread_max | approx frac of skips <=X | extra evals/day |
|---|---|---|
| 0.05 | 0.00 | 0 |
| 0.06 | 0.08 | 13 |
| 0.07 | 0.17 | 26 |
| 0.08 | 0.25 | 38 |
| 0.10 | 0.42 | 64 |
| 0.12 | 0.53 | 81 |
(approximate — linear interp from stated median/decile; books today are WIDER than the Apr BBO window so live fill rate may be lower.)


## Per-coin verdict summary

| coin | recommendation | incremental-band $/tr | delta[2,3) helps |
|---|---|---|---|
| BNB | soften to spread_max=0.12 | +4.928 | False |
| XRP | soften to spread_max=0.08 | +0.660 | False |
| DOGE | soften to spread_max=0.12 | +3.112 | False |

## Caveats
- BBO window = Apr 6-21 2026 regime; **books today are WIDER** (live median +5s spreads BNB~0.14 / DOGE~0.11 / XRP~0.08), so the historical fill rate OVERSTATES live volume.
- **Burned-window note:** Mar30-Apr21 OOS is partially burned per RETRO_MASTER_AUDIT_2026_06_10; treat magnitudes as hypotheses, not deploy-grade.
- **Thin-book exit risk at wide spreads:** wide ask-spread fires tend to have thin bid depth at +60s -> higher frac_held / settlement-valued remainder; CLEAN(frac_held==0) is the honest bound.
- BBO top-of-book fill (no L25 depth walk) -> entry slightly optimistic.
- Incremental-band n can be small per coin -> CI wide; verdict conservative (requires CI not sig-neg).
