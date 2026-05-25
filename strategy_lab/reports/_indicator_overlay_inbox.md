# Indicator-overlay gate sweep on production fills
Built: 2026-05-24  |  Source: `data/v4/canonical/_results/prod_fills_with_indicators.parquet`
CSV  : `C:/Users/alexandre bandarra/Desktop/global/data/v4/canonical/_results/indicator_overlay_on_prod_fills.csv`
Build: `strategy_lab/overnight_2026_05_23/build_prod_fills_panel.py`
Sweep: `strategy_lab/overnight_2026_05_23/gate_sweep_prod_fills.py`

Universe: f7_mode='off' from `fills.csv` (6,675 fires).
Gate features computed fresh at production `fire_us` (momo_v1: ws_s+120, momo_v2: ws_s+60, sniper: ws_s+window_s).
PnL is the production `pnl` column (legacy 2%-on-profit fees, $25 stake).
`sel_upl` = (per_tr_gate - per_tr_base) x n_gate — selectivity uplift (extra $ on the kept subset vs ungated rate).
Significance: one-sided binomial p (gate WR vs ungated baseline WR) + n_gate >= 20. `**` p<0.05, `*` p<0.10.

## Headline winners (binom p<0.05, n_gate>=20)
- **sniper   / ETH / 15m**  `m5v_pass`  n=76/356  WR=63.2% (+13.7pp)  sel_upl=$+614.64  per_tr=$+7.1493  p=0.011

## Marginal winners (0.05 < p < 0.10, n_gate>=20)
- `momo_v2  / BTC / 5m`  `fair_edge_bp_gt_500`  n=314/810  WR=52.9% (+4.1pp)  sel_upl=$+618.27  per_tr=$+0.3447  p=0.081
- `momo_v2  / BTC / 5m`  `fair_edge_bp_gt_500_AND_cvd30`  n=238/810  WR=53.4% (+4.6pp)  sel_upl=$+519.12  per_tr=$+0.5569  p=0.088
- `momo_v2  / BTC / 15m`  `fair_edge_bp_gt_0`  n=96/225  WR=61.5% (+8.6pp)  sel_upl=$+412.76  per_tr=$+4.6879  p=0.056
- `sniper   / SOL / 15m`  `fair_edge_bp_gt_0`  n=66/189  WR=60.6% (+9.8pp)  sel_upl=$+392.16  per_tr=$+5.0076  p=0.070
- `momo_v2  / SOL / 5m`  `cvd_agree_30s_AND_macd`  n=110/389  WR=57.3% (+6.6pp)  sel_upl=$+356.55  per_tr=$+2.1252  p=0.097
- `momo_v2  / BTC / 15m`  `fair_edge_bp_gt_500_AND_cvd30`  n=68/225  WR=63.2% (+10.3pp)  sel_upl=$+350.39  per_tr=$+5.5412  p=0.055
- `sniper   / ETH / 15m`  `m1v_AND_m5v`  n=46/356  WR=60.9% (+11.4pp)  sel_upl=$+349.15  per_tr=$+6.6522  p=0.080
- `momo_v1  / SOL / 5m`  `m5v_pass`  n=72/276  WR=62.5% (+9.2pp)  sel_upl=$+347.70  per_tr=$+4.9863  p=0.072
- `sniper   / SOL / 5m`  `cvd_agree_30s_AND_macd`  n=98/410  WR=59.2% (+7.2pp)  sel_upl=$+337.51  per_tr=$+3.2062  p=0.091
- `sniper   / SOL / 15m`  `imb5_signal_aligned_0p10`  n=67/189  WR=59.7% (+8.9pp)  sel_upl=$+307.90  per_tr=$+3.6613  p=0.090

## Headline duds (largest negative sel_upl, n_gate>=50)
- `momo_v1  / BTC / 5m`  `fair_edge_bp_gt_0`  n=337/784  WR=44.5% (-3.2pp)  sel_upl=$-535.37  per_tr=$-3.7323
- `momo_v1  / BTC / 5m`  `fair_edge_bp_gt_500`  n=301/784  WR=44.2% (-3.5pp)  sel_upl=$-535.18  per_tr=$-3.9217
- `momo_v2  / SOL / 5m`  `cross_partial_agree`  n=275/389  WR=46.9% (-3.7pp)  sel_upl=$-485.71  per_tr=$-2.8824
- `momo_v2  / SOL / 5m`  `m1v_pass`  n=125/389  WR=42.4% (-8.2pp)  sel_upl=$-472.80  per_tr=$-4.8986
- `sniper   / ETH / 15m`  `imb5_signal_aligned_0p10`  n=176/356  WR=44.3% (-5.1pp)  sel_upl=$-466.94  per_tr=$-3.5911
- `momo_v2  / SOL / 5m`  `cross_full_agree`  n=248/389  WR=47.2% (-3.5pp)  sel_upl=$-395.78  per_tr=$-2.7120
- `momo_v1  / BTC / 5m`  `imb5_signal_aligned_0p10`  n=251/784  WR=44.2% (-3.5pp)  sel_upl=$-384.61  per_tr=$-3.6760
- `momo_v1  / BTC / 5m`  `cvd_agree_30s_AND_macd`  n=185/784  WR=43.8% (-3.9pp)  sel_upl=$-377.42  per_tr=$-4.1838
- `momo_v2  / BTC / 5m`  `m1v_pass`  n=273/810  WR=45.8% (-3.0pp)  sel_upl=$-372.47  per_tr=$-2.9886
- `momo_v2  / BTC / 5m`  `cvd_agree_30s`  n=491/810  WR=47.5% (-1.3pp)  sel_upl=$-364.90  per_tr=$-2.3675

## Per-sleeve top-3 gates by uplift_sum

### momo_v1 / BTC / 15m  (n=137, WR=54.0%, sum=$138.56, per_tr=$1.0114)
   *fair_edge_bp_gt_500              n=  55/137   WR= 63.6% ( +9.6pp)  sel_upl=$ +273.14  per_tr=$+5.9776  p=0.097
    fair_edge_bp_gt_0                n=  59/137   WR= 61.0% ( +7.0pp)  sel_upl=$ +212.82  per_tr=$+4.6185  p=0.172
    fair_edge_bp_gt_500_AND_cvd30    n=  38/137   WR= 63.2% ( +9.1pp)  sel_upl=$ +179.43  per_tr=$+5.7331  p=0.167

### momo_v1 / BTC / 5m  (n=784, WR=47.7%, sum=$-1680.65, per_tr=$-2.1437)
    m1v_AND_m5v                      n= 104/784   WR= 50.0% ( +2.3pp)  sel_upl=$ +168.64  per_tr=$-0.5221  p=0.355
    cvd_agree_30s                    n= 461/784   WR= 48.4% ( +0.7pp)  sel_upl=$ +125.25  per_tr=$-1.8720  p=0.405
    cross_full_agree                 n= 501/784   WR= 47.9% ( +0.2pp)  sel_upl=$  +72.51  per_tr=$-1.9990  p=0.482

### momo_v1 / ETH / 15m  (n=71, WR=40.8%, sum=$-393.45, per_tr=$-5.5415)
    cvd_agree_30s                    n=  44/71    WR= 45.5% ( +4.6pp)  sel_upl=$ +102.01  per_tr=$-3.2232  p=0.317
    cvd_agree_30s_AND_60s            n=  42/71    WR= 45.2% ( +4.4pp)  sel_upl=$  +91.62  per_tr=$-3.3600  p=0.334
    imb5_signal_aligned_0p10         n=  25/71    WR= 48.0% ( +7.2pp)  sel_upl=$  +86.70  per_tr=$-2.0734  p=0.297

### momo_v1 / ETH / 5m  (n=467, WR=44.5%, sum=$-1781.61, per_tr=$-3.8150)
    imb5_signal_aligned_0p10         n= 149/467   WR= 49.0% ( +4.5pp)  sel_upl=$ +327.23  per_tr=$-1.6188  p=0.156
    cvd_agree_30s                    n= 266/467   WR= 46.6% ( +2.1pp)  sel_upl=$ +268.96  per_tr=$-2.8039  p=0.267
    cross_full_agree                 n= 283/467   WR= 46.3% ( +1.8pp)  sel_upl=$ +264.65  per_tr=$-2.8798  p=0.297

### momo_v1 / SOL / 15m  (n=36, WR=41.7%, sum=$-190.12, per_tr=$-5.2810)
    imb5_signal_aligned_0p10         n=  15/36    WR= 60.0% (+18.3pp)  sel_upl=$ +142.99  per_tr=$+4.2519  p=0.120
    cross_full_agree                 n=  25/36    WR= 48.0% ( +6.3pp)  sel_upl=$  +74.13  per_tr=$-2.3158  p=0.327
    cross_partial_agree              n=  26/36    WR= 46.2% ( +4.5pp)  sel_upl=$  +53.60  per_tr=$-3.2194  p=0.392

### momo_v1 / SOL / 5m  (n=276, WR=53.3%, sum=$43.36, per_tr=$0.1571)
   *m5v_pass                         n=  72/276   WR= 62.5% ( +9.2pp)  sel_upl=$ +347.70  per_tr=$+4.9863  p=0.072
    m1v_AND_m5v                      n=  39/276   WR= 64.1% (+10.8pp)  sel_upl=$ +231.33  per_tr=$+6.0886  p=0.115
    rvol_30_300_gt_1p2               n=  84/276   WR= 54.8% ( +1.5pp)  sel_upl=$  +72.53  per_tr=$+1.0206  p=0.435

### momo_v2 / BTC / 15m  (n=225, WR=52.9%, sum=$87.38, per_tr=$0.3884)
   *fair_edge_bp_gt_0                n=  96/225   WR= 61.5% ( +8.6pp)  sel_upl=$ +412.76  per_tr=$+4.6879  p=0.056
   *fair_edge_bp_gt_500_AND_cvd30    n=  68/225   WR= 63.2% (+10.3pp)  sel_upl=$ +350.39  per_tr=$+5.5412  p=0.055
    m1v_pass                         n=  85/225   WR= 58.8% ( +5.9pp)  sel_upl=$ +273.22  per_tr=$+3.6027  p=0.162

### momo_v2 / BTC / 5m  (n=810, WR=48.8%, sum=$-1315.66, per_tr=$-1.6243)
   *fair_edge_bp_gt_500              n= 314/810   WR= 52.9% ( +4.1pp)  sel_upl=$ +618.27  per_tr=$+0.3447  p=0.081
   *fair_edge_bp_gt_500_AND_cvd30    n= 238/810   WR= 53.4% ( +4.6pp)  sel_upl=$ +519.12  per_tr=$+0.5569  p=0.088
    fair_edge_bp_gt_0                n= 358/810   WR= 51.4% ( +2.6pp)  sel_upl=$ +454.60  per_tr=$-0.3544  p=0.173

### momo_v2 / ETH / 15m  (n=131, WR=54.2%, sum=$134.01, per_tr=$1.0230)
    cross_full_agree                 n=  89/131   WR= 58.4% ( +4.2pp)  sel_upl=$ +185.58  per_tr=$+3.1082  p=0.244
    fair_edge_bp_gt_0                n=  62/131   WR= 59.7% ( +5.5pp)  sel_upl=$ +168.42  per_tr=$+3.7395  p=0.231
    cvd_agree_30s_AND_60s            n=  68/131   WR= 58.8% ( +4.6pp)  sel_upl=$ +145.63  per_tr=$+3.1645  p=0.261

### momo_v2 / ETH / 5m  (n=599, WR=48.4%, sum=$-1118.31, per_tr=$-1.8670)
    cross_full_agree                 n= 369/599   WR= 50.1% ( +1.7pp)  sel_upl=$ +341.22  per_tr=$-0.9422  p=0.271
    m1v_AND_m5v                      n=  62/599   WR= 54.8% ( +6.4pp)  sel_upl=$ +231.40  per_tr=$+1.8653  p=0.188
    cross_partial_agree              n= 407/599   WR= 49.4% ( +1.0pp)  sel_upl=$ +209.17  per_tr=$-1.3530  p=0.366

### momo_v2 / SOL / 15m  (n=93, WR=48.4%, sum=$-230.22, per_tr=$-2.4755)
    cross_partial_agree              n=  61/93    WR= 55.7% ( +7.4pp)  sel_upl=$ +215.76  per_tr=$+1.0616  p=0.154
    fair_edge_bp_gt_500_AND_cvd30    n=  18/93    WR= 72.2% (+23.8pp)  sel_upl=$ +206.72  per_tr=$+9.0092  p=0.036
    cvd_agree_30s_AND_60s            n=  48/93    WR= 56.2% ( +7.9pp)  sel_upl=$ +187.81  per_tr=$+1.4372  p=0.172

### momo_v2 / SOL / 5m  (n=389, WR=50.6%, sum=$-434.18, per_tr=$-1.1162)
   *cvd_agree_30s_AND_macd           n= 110/389   WR= 57.3% ( +6.6pp)  sel_upl=$ +356.55  per_tr=$+2.1252  p=0.097
    macd_agree                       n= 138/389   WR= 53.6% ( +3.0pp)  sel_upl=$ +201.26  per_tr=$+0.3422  p=0.269
    imb5_signal_aligned_0p10         n= 153/389   WR= 52.9% ( +2.3pp)  sel_upl=$ +186.87  per_tr=$+0.1052  p=0.313

### sniper / BTC / 15m  (n=481, WR=51.4%, sum=$15.76, per_tr=$0.0328)
    macd_agree                       n= 193/481   WR= 56.0% ( +4.6pp)  sel_upl=$ +536.66  per_tr=$+2.8134  p=0.113
    fair_edge_bp_gt_0                n= 179/481   WR= 53.6% ( +2.3pp)  sel_upl=$ +311.51  per_tr=$+1.7730  p=0.296
    fair_edge_bp_gt_500              n= 134/481   WR= 53.7% ( +2.4pp)  sel_upl=$ +253.85  per_tr=$+1.9271  p=0.321

### sniper / BTC / 5m  (n=712, WR=48.2%, sum=$-979.32, per_tr=$-1.3755)
    imb5_signal_aligned_0p10         n= 260/712   WR= 51.2% ( +3.0pp)  sel_upl=$ +426.95  per_tr=$+0.2667  p=0.184
    fair_edge_bp_gt_0                n= 304/712   WR= 50.0% ( +1.8pp)  sel_upl=$ +291.59  per_tr=$-0.4163  p=0.281
    rvol_30_300_gt_1p2               n= 119/712   WR= 52.1% ( +3.9pp)  sel_upl=$ +166.30  per_tr=$+0.0220  p=0.222

### sniper / ETH / 15m  (n=356, WR=49.4%, sum=$-333.93, per_tr=$-0.9380)
  **m5v_pass                         n=  76/356   WR= 63.2% (+13.7pp)  sel_upl=$ +614.64  per_tr=$+7.1493  p=0.011
    m1v_pass                         n= 134/356   WR= 55.2% ( +5.8pp)  sel_upl=$ +446.70  per_tr=$+2.3956  p=0.105
    macd_agree                       n= 149/356   WR= 54.4% ( +4.9pp)  sel_upl=$ +419.32  per_tr=$+1.8763  p=0.131

### sniper / ETH / 5m  (n=509, WR=49.7%, sum=$-163.82, per_tr=$-0.3218)
    cvd_agree_30s_AND_macd           n= 103/509   WR= 55.3% ( +5.6pp)  sel_upl=$ +320.49  per_tr=$+2.7897  p=0.148
    cvd_agree_30s_AND_60s            n= 148/509   WR= 52.0% ( +2.3pp)  sel_upl=$ +214.51  per_tr=$+1.1275  p=0.315
    rvol_30_300_gt_1p2               n=  57/509   WR= 56.1% ( +6.4pp)  sel_upl=$ +184.36  per_tr=$+2.9126  p=0.201

### sniper / SOL / 15m  (n=189, WR=50.8%, sum=$-176.58, per_tr=$-0.9343)
   *fair_edge_bp_gt_0                n=  66/189   WR= 60.6% ( +9.8pp)  sel_upl=$ +392.16  per_tr=$+5.0076  p=0.070
   *imb5_signal_aligned_0p10         n=  67/189   WR= 59.7% ( +8.9pp)  sel_upl=$ +307.90  per_tr=$+3.6613  p=0.090
   *fair_edge_bp_gt_500              n=  32/189   WR= 65.6% (+14.8pp)  sel_upl=$ +287.82  per_tr=$+8.0601  p=0.066

### sniper / SOL / 5m  (n=410, WR=52.0%, sum=$-97.50, per_tr=$-0.2378)
    cvd_agree_30s                    n= 154/410   WR= 57.1% ( +5.2pp)  sel_upl=$ +386.21  per_tr=$+2.2700  p=0.113
   *cvd_agree_30s_AND_macd           n=  98/410   WR= 59.2% ( +7.2pp)  sel_upl=$ +337.51  per_tr=$+3.2062  p=0.091
    cvd_agree_30s_AND_60s            n= 110/410   WR= 58.2% ( +6.2pp)  sel_upl=$ +336.06  per_tr=$+2.8173  p=0.112

## Re-run
```
py strategy_lab/overnight_2026_05_23/build_prod_fills_panel.py
py strategy_lab/overnight_2026_05_23/gate_sweep_prod_fills.py
```