# MA Ribbon strategy — 5m markets (2026-05-25 18:22 UTC)

## Setup

Standalone MA Ribbon strategy on 5m chainlink-resolved crypto up/down markets.
At t = slot_start + offset_s for offset ∈ {30,60,...,270}, look up the ribbon
features (color, alignment_pct, compression_bps, lead_slope_bps, lead_vs_ref_bps)
at the 1s `ta_indicators_1s.parquet` row at-or-before t, and fire based on rules R1–R4.

Fills: `engine_v2.LegacyConfig` (2%-on-profit fee), $25 notional, L25 book walk.
Spread filter: BTC 0.02, ETH 0.02, SOL 0.025.

**Rules tested:**
- R1 — color==1 & alignment>=85 → UP / color==3 & alignment<=15 → DOWN
- R2 — lead_vs_ref>5 & slope>0 → UP / lead_vs_ref<-5 & slope<0 → DOWN
- R3 — compression>THR & color==1 → UP / color==3 → DOWN (THR ∈ {5,10,15})
- R4 — compression<2 & slope>0 → UP / slope<0 → DOWN

## Headline

**Does the standalone MA Ribbon strategy work?  → YES (conditionally).**

25 (rule,param,asset,offset) cells with n≥30, WR≥60%, avg_pnl>0.

Total signal-fires (after gen): 226,572; filled (L25): 168,276

## Per-rule headline (all assets, offsets, directions)

| rule   | param   |      n |     wr |   avg_pnl |      sum_pnl |
|:-------|:--------|-------:|-------:|----------:|-------------:|
| R2     | default |   6087 | 0.8567 |    1.0733 |    6533.3    |
| R1     | default |  50411 | 0.7341 |   -0.2661 |  -13414.6    |
| R3     | thr5    |    183 | 0.9071 |   -0.4772 |     -87.3276 |
| R4     | default | 111571 | 0.5423 |   -1.7944 | -200206      |
| R3     | thr10   |     16 | 0.8125 |   -4.1165 |     -65.8635 |
| R3     | thr15   |      8 | 0.625  |   -9.0769 |     -72.6153 |

## Top 10 deployable configs (n≥30, WR≥60%, avg_pnl>0)

| rule   | param   | asset   |   fire_offset_s |   n |     wr |   avg_pnl |   sum_pnl |
|:-------|:--------|:--------|----------------:|----:|-------:|----------:|----------:|
| R2     | default | BTC     |             210 | 121 | 0.8678 |    9.7134 |  1175.33  |
| R2     | default | ETH     |             210 | 195 | 0.8564 |    8.4566 |  1649.04  |
| R2     | default | SOL     |             270 | 166 | 0.7771 |    5.2849 |   877.299 |
| R2     | default | ETH     |             270 | 120 | 0.7333 |    3.722  |   446.635 |
| R2     | default | BTC     |              60 | 183 | 0.8962 |    2.9043 |   531.491 |
| R2     | default | BTC     |              90 | 232 | 0.8966 |    2.2892 |   531.104 |
| R2     | default | BTC     |              30 | 175 | 0.7714 |    2.2576 |   395.072 |
| R2     | default | ETH     |             150 | 285 | 0.8877 |    1.4115 |   402.283 |
| R2     | default | SOL     |             120 | 357 | 0.9244 |    1.0265 |   366.457 |
| R2     | default | BTC     |             120 | 188 | 0.9309 |    0.9909 |   186.293 |

## Top 10 deployable configs (with direction)

| rule   | param   | asset   |   fire_offset_s | direction   |   n |     wr |   avg_pnl |   sum_pnl |   avg_entry |
|:-------|:--------|:--------|----------------:|:------------|----:|-------:|----------:|----------:|------------:|
| R2     | default | BTC     |             210 | UP          |  57 | 0.8772 |   19.9319 |  1136.12  |      0.843  |
| R2     | default | ETH     |             210 | UP          |  95 | 0.8737 |   17.2772 |  1641.33  |      0.8042 |
| R2     | default | SOL     |             270 | UP          |  99 | 0.7576 |   11.3465 |  1123.31  |      0.7197 |
| R2     | default | ETH     |             270 | DOWN        |  54 | 0.7778 |    5.3017 |   286.293 |      0.7315 |
| R2     | default | BTC     |              60 | UP          |  93 | 0.9462 |    3.6442 |   338.911 |      0.8312 |
| R2     | default | BTC     |              90 | DOWN        | 126 | 0.8889 |    3.1875 |   401.62  |      0.8411 |
| R2     | default | BTC     |              30 | DOWN        |  91 | 0.7802 |    3.0243 |   275.209 |      0.7099 |
| R2     | default | ETH     |             270 | UP          |  66 | 0.697  |    2.4294 |   160.342 |      0.6803 |
| R2     | default | BTC     |              60 | DOWN        |  90 | 0.8444 |    2.1398 |   192.58  |      0.7811 |
| R2     | default | ETH     |             150 | UP          | 148 | 0.9054 |    1.6503 |   244.243 |      0.8713 |

## All (n≥30) configs by avg_pnl (top 40)

| rule   | param   | asset   |   fire_offset_s |    n |     wr |   avg_pnl |    sum_pnl |
|:-------|:--------|:--------|----------------:|-----:|-------:|----------:|-----------:|
| R2     | default | BTC     |             210 |  121 | 0.8678 |    9.7134 |  1175.33   |
| R2     | default | ETH     |             210 |  195 | 0.8564 |    8.4566 |  1649.04   |
| R2     | default | SOL     |             270 |  166 | 0.7771 |    5.2849 |   877.299  |
| R2     | default | ETH     |             270 |  120 | 0.7333 |    3.722  |   446.635  |
| R2     | default | BTC     |              60 |  183 | 0.8962 |    2.9043 |   531.491  |
| R2     | default | BTC     |              90 |  232 | 0.8966 |    2.2892 |   531.104  |
| R2     | default | BTC     |              30 |  175 | 0.7714 |    2.2576 |   395.072  |
| R2     | default | ETH     |             150 |  285 | 0.8877 |    1.4115 |   402.283  |
| R2     | default | SOL     |             120 |  357 | 0.9244 |    1.0265 |   366.457  |
| R2     | default | BTC     |             120 |  188 | 0.9309 |    0.9909 |   186.293  |
| R2     | default | ETH     |             120 |  292 | 0.911  |    0.8667 |   253.067  |
| R1     | default | ETH     |             240 | 1830 | 0.794  |    0.8178 |  1496.53   |
| R2     | default | ETH     |              30 |  270 | 0.7593 |    0.7278 |   196.505  |
| R2     | default | BTC     |             150 |  159 | 0.9057 |    0.6362 |   101.154  |
| R2     | default | ETH     |              60 |  316 | 0.8196 |    0.528  |   166.841  |
| R1     | default | BTC     |             180 | 2309 | 0.7843 |    0.4662 |  1076.41   |
| R2     | default | ETH     |              90 |  334 | 0.8683 |    0.4264 |   142.429  |
| R1     | default | BTC     |              60 | 2320 | 0.6823 |    0.2913 |   675.743  |
| R2     | default | SOL     |             180 |  292 | 0.9315 |    0.2828 |    82.5918 |
| R4     | default | BTC     |             180 | 5030 | 0.5706 |    0.2487 |  1250.98   |
| R1     | default | BTC     |             270 | 1640 | 0.7073 |    0.2361 |   387.201  |
| R4     | default | ETH     |              60 | 4570 | 0.5748 |    0.2139 |   977.437  |
| R2     | default | SOL     |             150 |  326 | 0.911  |    0.158  |    51.5063 |
| R1     | default | ETH     |             180 | 1981 | 0.7961 |    0.1165 |   230.87   |
| R1     | default | BTC     |             210 | 2219 | 0.7648 |    0.0725 |   160.855  |
| R4     | default | BTC     |              60 | 5024 | 0.5707 |    0.0332 |   166.656  |
| R1     | default | BTC     |             120 | 2377 | 0.7467 |    0.0252 |    59.8714 |
| R1     | default | ETH     |              60 | 2130 | 0.6972 |    0.0136 |    28.911  |
| R1     | default | BTC     |             150 | 2360 | 0.7593 |   -0.0242 |   -57.0825 |
| R1     | default | ETH     |             150 | 2043 | 0.7807 |   -0.0871 |  -177.87   |
| R1     | default | SOL     |             180 | 1425 | 0.7909 |   -0.0918 |  -130.786  |
| R2     | default | ETH     |             180 |  240 | 0.8833 |   -0.1135 |   -27.2439 |
| R2     | default | SOL     |              90 |  327 | 0.8532 |   -0.1146 |   -37.4687 |
| R2     | default | BTC     |             180 |  142 | 0.9085 |   -0.1736 |   -24.6508 |
| R1     | default | BTC     |             240 | 2087 | 0.7427 |   -0.2027 |  -423.015  |
| R2     | default | SOL     |             210 |  270 | 0.8741 |   -0.2259 |   -60.9797 |
| R1     | default | SOL     |             210 | 1505 | 0.7973 |   -0.2404 |  -361.743  |
| R4     | default | BTC     |              90 | 4981 | 0.5668 |   -0.2723 | -1356.55   |
| R1     | default | SOL     |             150 | 1438 | 0.7719 |   -0.2812 |  -404.434  |
| R1     | default | BTC     |              90 | 2357 | 0.7119 |   -0.3151 |  -742.732  |

## Overlap with S1.5 (VWAP continuation 5m)

Fraction of MA-Ribbon fires that also appear in S1.5's `vwap_continuation_5m_per_fire.parquet`
(matched on slug + fire_us + direction).

| rule   | param   |   n_ribbon |   n_overlap_s15 |   overlap_pct |
|:-------|:--------|-----------:|----------------:|--------------:|
| R1     | default |      50411 |           18916 |          37.5 |
| R2     | default |       6087 |            4976 |          81.7 |
| R3     | thr10   |         16 |              13 |          81.2 |
| R3     | thr15   |          8 |               5 |          62.5 |
| R3     | thr5    |        183 |             171 |          93.4 |
| R4     | default |     111571 |           20825 |          18.7 |

_data: `data\v4\canonical\_results\ma_ribbon_strategy_5m.csv`_  
_per-fire parquet: `data\v4\canonical\_results\ma_ribbon_strategy_5m_per_fire.parquet`_  
_script: `strategy_lab/meta_classifier/ma_ribbon_strategy_5m.py`_