# BTC Trend-Start Regime Detector — 3y Event Study

**Window:** 2023-05-01 08:00:00+00:00 → 2026-04-29 17:00:00+00:00  (5,160 hourly bars)

**Trend-start label used:** ≥3% move in 24h with max counter-excursion ≤1.0%.

- Bull events: **1235** (23.93% of bars)
- Bear events: **1059** (20.52% of bars)

## Top 5 leading indicators by |corr| @ 24h fwd return

| Indicator | Pearson corr | n samples |
|---|---|---|
| `z_dom_stables` | +0.0706 | 1,718 |
| `oilsr` | +0.0456 | 5,136 |
| `z_oi` | +0.0372 | 5,136 |
| `z_lsr` | -0.0316 | 5,136 |
| `brigalS` | -0.0314 | 5,136 |

## Bull-side sequencing (mean state @ offset)

Indicators are sorted by |mean at offset 0|. Negative offsets = before event.

```
offset_h                     -24     -12      -8      -4      -2      -1       0
indicator                                                                       
cross_real_money            -inf    -inf    -inf    -inf    -inf    -inf    -inf
cross_leverage_heat          inf     inf     inf     inf     inf     inf     inf
rsi_14                    50.672  50.483  50.647  50.593  50.642  50.478  50.399
brigalS                    0.003  -0.052  -0.120   0.038  -0.102  -0.127  -0.185
cross_institutional_lead   0.147   0.121   0.116   0.141   0.166   0.178   0.182
oilsr                      0.022   0.138   0.153   0.110   0.192   0.158   0.162
z_top_lsr_sum             -0.080  -0.075  -0.010  -0.045  -0.082  -0.079  -0.099
z_lsr                      0.007  -0.020  -0.054   0.026  -0.045  -0.058  -0.087
z_oi                       0.030   0.118   0.099   0.136   0.147   0.100   0.075
z_top_lsr_count           -0.006  -0.012  -0.046   0.029  -0.007  -0.021  -0.055
cross_risk_off            -0.022  -0.027  -0.033  -0.042  -0.048  -0.051  -0.053
z_oi_silent                0.009   0.056   0.069   0.110   0.072   0.059   0.037
z_dom_stables              0.008  -0.006  -0.018  -0.007  -0.011  -0.010  -0.027
z_cb_premium              -0.026  -0.024  -0.022  -0.030  -0.051  -0.040  -0.013
z_fund                     0.018   0.033   0.041   0.022   0.029   0.013   0.011
z_taker_ratio              0.063   0.059   0.095   0.060   0.041   0.040   0.011
atr_pct                    0.006   0.006   0.006   0.006   0.007   0.007   0.007
```

## Bear-side sequencing (mean state @ offset)
```
offset_h                     -24     -12      -8      -4      -2      -1       0
indicator                                                                       
cross_real_money            -inf    -inf    -inf    -inf    -inf    -inf    -inf
cross_leverage_heat          inf     inf     inf     inf     inf     inf     inf
rsi_14                    49.297  51.331  51.146  51.207  51.374  51.373  51.296
cross_institutional_lead   0.193   0.424   0.484   0.539   0.538   0.541   0.537
brigalS                    0.037   0.017  -0.004  -0.123   0.000   0.048   0.131
z_top_lsr_count            0.075   0.037   0.032  -0.042   0.013   0.066   0.088
z_lsr                      0.024   0.015   0.004  -0.055   0.007   0.031   0.072
z_oi_silent                0.113   0.044   0.035   0.027   0.047   0.044   0.048
z_cb_premium              -0.050   0.014   0.007  -0.007  -0.026  -0.051  -0.048
z_oi                       0.138   0.144   0.077   0.092   0.046   0.045   0.044
z_dom_stables             -0.053   0.006   0.007  -0.005  -0.092  -0.057  -0.042
oilsr                      0.114   0.129   0.072   0.147   0.039   0.014  -0.029
z_taker_ratio              0.025  -0.021  -0.070  -0.008   0.016   0.007   0.020
cross_risk_off             0.038  -0.004  -0.014  -0.026  -0.022  -0.022  -0.019
z_fund                    -0.015   0.029  -0.018  -0.041  -0.013  -0.019  -0.008
z_top_lsr_sum             -0.075  -0.063  -0.054  -0.036  -0.016  -0.037   0.008
atr_pct                    0.006   0.007   0.007   0.007   0.007   0.006   0.006
```

## Macro-regime stability

Pearson correlations split by macro regime. If a number flips sign or shrinks 50%+ across regimes, the indicator is regime-dependent and needs the macro filter.
```
horizon_h                                  4      24
regime        indicator                             
below_ema50   atr_pct                  -0.095 -0.140
              brigalS                   0.033  0.080
              cross_institutional_lead -0.096 -0.275
              cross_leverage_heat      -0.010 -0.025
              cross_real_money          0.010  0.025
              cross_risk_off            0.073  0.194
              oilsr                    -0.061 -0.065
              rsi_14                   -0.008 -0.054
              z_cb_premium              0.025  0.015
              z_dom_stables            -0.030 -0.023
              z_fund                   -0.013 -0.013
              z_lsr                     0.033  0.080
              z_oi                     -0.060 -0.021
              z_oi_silent              -0.041  0.011
              z_taker_ratio            -0.000 -0.035
              z_top_lsr_count           0.021  0.055
              z_top_lsr_sum             0.017  0.008
trending_down atr_pct                   0.011 -0.089
              brigalS                  -0.049 -0.017
              cross_institutional_lead  0.001  0.008
              cross_risk_off           -0.007 -0.040
              oilsr                     0.048  0.002
              rsi_14                    0.049  0.011
              z_cb_premium             -0.017  0.001
              z_dom_stables             0.059  0.053
              z_fund                   -0.043 -0.006
              z_lsr                    -0.049 -0.017
              z_oi                      0.020 -0.015
              z_oi_silent              -0.038 -0.015
              z_taker_ratio            -0.003  0.015
              z_top_lsr_count          -0.045 -0.004
              z_top_lsr_sum            -0.026 -0.026
trending_up   atr_pct                   0.096  0.020
              brigalS                  -0.019 -0.023
              cross_institutional_lead -0.005 -0.117
              cross_leverage_heat      -0.031 -0.063
              cross_real_money          0.031  0.063
              cross_risk_off           -0.051  0.013
              oilsr                     0.041  0.065
              rsi_14                    0.049  0.055
              z_cb_premium             -0.001 -0.009
              z_dom_stables             0.107  0.067
              z_fund                    0.026  0.060
              z_lsr                    -0.019 -0.023
              z_oi                      0.044  0.078
              z_oi_silent              -0.008  0.020
              z_taker_ratio            -0.043 -0.017
              z_top_lsr_count          -0.017 -0.035
              z_top_lsr_sum            -0.020  0.021
```

## Files

- `01_label_sweep.csv` — full (X, Y, Z) grid output
- `02_correlations.csv` — indicator × horizon Pearson
- `03_zone_means.csv` — mean fwd return per ±σ zone
- `04_sequencing.csv` — pre-event indicator snapshots
- `05_macro_regime_split.csv` — corr partitioned by macro regime
- `06_pine_detector.txt` — generated Pine Script v6 detector