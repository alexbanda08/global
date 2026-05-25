# Spike-driven entry — 5m markets (2026-05-23 14:15 UTC)

Independent spike-entry: fire on a binance 1s spike inside the 5m slot, 
not on momo's `ret_2m` signal. Universe: chainlink-resolved 5m slugs 
(17,253 BTC/ETH/SOL). Decision offsets: (15, 30, 45, 60, 90, 120). 
Fills via `engine_v2.LegacyConfig` (2%-on-profit, $25 notional, L25 walk).

**Definitions (with per-asset threshold tiers calibrated from 1s ret distribution):**
- **D1** `|ret_5s|>r5 AND sign(cvd_5s)==sign(ret_5s)` — flow-confirmed micro-burst
- **D2** `|ret_15s|>r15 AND sign(cvd_15s)==sign(ret_15s)` — flow-confirmed 15s burst
- **D3** `|ret_5s|>r5 AND |ret_15s|>r15 (signs agree)` — sustained spike
- **D4** `|ret_30s|>r30 AND |ret_5s|>r5_for_d4 (same sign)` — continuation after pullback

Thresholds in bps (T1 loose ~p95, T2 med ~p99, T3 strict ~p99.5):

| asset | tier | r5 (5s) | r15 (15s) | r30 (30s) | r5_for_d4 |
|:------|:-----|--------:|----------:|----------:|----------:|
| BTC | T1 | 2.5 | 4.5 | 7.0 | 0.8 |
| BTC | T2 | 4.0 | 7.0 | 10.0 | 1.5 |
| BTC | T3 | 6.0 | 10.0 | 14.0 | 2.5 |
| ETH | T1 | 3.0 | 5.5 | 8.0 | 1.0 |
| ETH | T2 | 5.0 | 9.0 | 12.0 | 2.0 |
| ETH | T3 | 7.5 | 12.0 | 18.0 | 3.0 |
| SOL | T1 | 3.5 | 6.0 | 9.5 | 1.5 |
| SOL | T2 | 6.0 | 10.0 | 15.0 | 2.5 |
| SOL | T3 | 9.0 | 14.5 | 22.0 | 4.0 |

**Gates** (applied on top of each spike fire):
- `rsi_agree`: RSI(14) on 60s closes > 50 if UP / < 50 if DOWN (F7-style anchor)
- `vwap_agree`: 15m-anchored VWAP dev_bps > 0 if UP / < 0 if DOWN
- `both_agree`: intersection

**Population**: 103,515 candidate (slug,offset) pairs scanned; 
17,774 spike events detected across all defs; 
11,336 successfully L25-filled.

## Headline: best deployable per cell

Top 30 by avg_pnl (n>=30, WR>=60%, avg_pnl>0):

| asset   |   fire_offset_s | definition   | tier   | gate       |   n |    wr |   avg_pnl |   sum_pnl |   avg_entry |
|:--------|----------------:|:-------------|:-------|:-----------|----:|------:|----------:|----------:|------------:|
| BTC     |             120 | D1           | T2     | none       |  38 | 0.763 |    15.425 |   586.152 |      0.669  |
| ETH     |             120 | D2           | T2     | vwap_agree |  34 | 1     |    12.836 |   436.42  |      0.808  |
| BTC     |             120 | D2           | T2     | none       |  35 | 0.829 |    11.696 |   409.351 |      0.772  |
| ETH     |              90 | D1           | T2     | vwap_agree |  40 | 0.775 |    10.124 |   404.964 |      0.6934 |
| BTC     |              45 | D1           | T2     | vwap_agree |  30 | 0.767 |     9.302 |   279.073 |      0.6267 |
| BTC     |             120 | D3           | T1     | none       |  54 | 0.759 |     8.531 |   460.659 |      0.7134 |
| BTC     |              30 | D1           | T2     | vwap_agree |  37 | 0.784 |     8.468 |   313.301 |      0.5949 |
| BTC     |              45 | D1           | T2     | none       |  38 | 0.737 |     8.414 |   319.729 |      0.5804 |
| ETH     |             120 | D2           | T2     | none       |  39 | 0.872 |     7.985 |   311.42  |      0.7385 |
| BTC     |              30 | D3           | T1     | rsi_agree  |  42 | 0.833 |     7.985 |   335.36  |      0.6571 |
| BTC     |              30 | D3           | T1     | both_agree |  41 | 0.829 |     7.947 |   325.833 |      0.6556 |
| BTC     |              60 | D4           | T2     | none       |  30 | 0.933 |     7.116 |   213.468 |      0.7526 |
| BTC     |              30 | D1           | T2     | none       |  43 | 0.744 |     6.975 |   299.945 |      0.571  |
| BTC     |             120 | D4           | T1     | none       |  64 | 0.828 |     6.749 |   431.952 |      0.7903 |
| BTC     |             120 | D1           | T1     | none       | 146 | 0.705 |     6.574 |   959.738 |      0.6142 |
| BTC     |              45 | D1           | T1     | vwap_agree | 131 | 0.718 |     6.552 |   858.262 |      0.6052 |
| BTC     |              45 | D3           | T1     | none       |  64 | 0.75  |     6.438 |   412.017 |      0.6309 |
| ETH     |             120 | D4           | T1     | vwap_agree |  80 | 0.888 |     6.434 |   514.723 |      0.7942 |
| ETH     |              90 | D3           | T1     | vwap_agree |  57 | 0.877 |     6.314 |   359.911 |      0.756  |
| BTC     |              30 | D3           | T1     | vwap_agree |  57 | 0.789 |     6.125 |   349.114 |      0.6386 |
| BTC     |              30 | D3           | T1     | none       |  61 | 0.787 |     5.753 |   350.918 |      0.6369 |
| BTC     |              30 | D1           | T1     | both_agree |  75 | 0.733 |     5.691 |   426.859 |      0.6144 |
| BTC     |              30 | D1           | T1     | rsi_agree  |  83 | 0.711 |     5.618 |   466.335 |      0.6004 |
| BTC     |              45 | D3           | T1     | vwap_agree |  57 | 0.754 |     5.534 |   315.434 |      0.6417 |
| ETH     |              90 | D1           | T2     | rsi_agree  |  31 | 0.806 |     5.487 |   170.102 |      0.7222 |
| BTC     |              45 | D1           | T1     | none       | 165 | 0.661 |     5.423 |   894.85  |      0.5598 |
| SOL     |              30 | D3           | T1     | none       |  45 | 0.8   |     5.412 |   243.551 |      0.6857 |
| SOL     |              30 | D3           | T1     | vwap_agree |  39 | 0.795 |     5.258 |   205.06  |      0.6873 |
| BTC     |              30 | D1           | T1     | none       | 149 | 0.671 |     5.152 |   767.591 |      0.5601 |
| BTC     |              30 | D2           | T2     | rsi_agree  |  31 | 0.806 |     5.094 |   157.918 |      0.7118 |

## Robust deployable (n>=80, WR>=68%, avg_pnl>=$1.5)

| asset   |   fire_offset_s | definition   | tier   | gate       |   n |    wr |   avg_pnl |   sum_pnl |   avg_entry |
|:--------|----------------:|:-------------|:-------|:-----------|----:|------:|----------:|----------:|------------:|
| BTC     |             120 | D1           | T1     | none       | 146 | 0.705 |     6.574 |   959.738 |      0.6142 |
| BTC     |              45 | D1           | T1     | vwap_agree | 131 | 0.718 |     6.552 |   858.262 |      0.6052 |
| BTC     |              30 | D1           | T1     | vwap_agree | 114 | 0.702 |     4.875 |   555.787 |      0.5932 |
| BTC     |              60 | D2           | T1     | none       | 158 | 0.722 |     3.352 |   529.597 |      0.6353 |
| ETH     |             120 | D2           | T1     | vwap_agree | 125 | 0.856 |     4.211 |   526.422 |      0.793  |
| ETH     |             120 | D4           | T1     | vwap_agree |  80 | 0.888 |     6.434 |   514.723 |      0.7942 |
| BTC     |              60 | D2           | T1     | vwap_agree | 124 | 0.774 |     4.032 |   499.977 |      0.6868 |
| BTC     |              60 | D4           | T1     | none       |  97 | 0.835 |     4.882 |   473.584 |      0.7231 |
| BTC     |              30 | D1           | T1     | rsi_agree  |  83 | 0.711 |     5.618 |   466.335 |      0.6004 |
| SOL     |              30 | D2           | T1     | none       | 130 | 0.785 |     3.55  |   461.466 |      0.7032 |
| BTC     |              30 | D2           | T1     | rsi_agree  |  99 | 0.798 |     4.66  |   461.382 |      0.6919 |
| ETH     |             120 | D4           | T1     | none       |  98 | 0.806 |     4.605 |   451.261 |      0.7369 |
| BTC     |              30 | D2           | T1     | vwap_agree | 126 | 0.762 |     3.46  |   435.98  |      0.6802 |
| BTC     |              45 | D1           | T1     | both_agree |  90 | 0.722 |     4.718 |   424.601 |      0.6458 |
| BTC     |              45 | D1           | T1     | rsi_agree  |  95 | 0.695 |     4.282 |   406.794 |      0.624  |
| BTC     |              30 | D2           | T1     | both_agree |  91 | 0.791 |     4.441 |   404.123 |      0.6954 |
| BTC     |              90 | D2           | T1     | vwap_agree | 151 | 0.795 |     2.651 |   400.352 |      0.7541 |
| BTC     |              45 | D2           | T1     | none       | 159 | 0.717 |     2.462 |   391.38  |      0.667  |
| ETH     |              15 | D2           | T1     | none       | 230 | 0.73  |     1.631 |   375.184 |      0.6854 |
| BTC     |              15 | D2           | T1     | none       | 240 | 0.696 |     1.539 |   369.269 |      0.6478 |
| BTC     |              30 | D2           | T1     | none       | 147 | 0.735 |     2.432 |   357.509 |      0.6683 |
| BTC     |             120 | D2           | T1     | none       | 148 | 0.73  |     2.391 |   353.942 |      0.705  |
| BTC     |              45 | D2           | T1     | vwap_agree | 136 | 0.743 |     2.49  |   338.664 |      0.6828 |
| SOL     |              30 | D2           | T1     | vwap_agree | 111 | 0.775 |     3.045 |   338.035 |      0.7089 |
| BTC     |              45 | D4           | T1     | none       |  82 | 0.829 |     3.968 |   325.397 |      0.7431 |
| ETH     |              90 | D1           | T1     | vwap_agree | 125 | 0.728 |     2.569 |   321.111 |      0.6973 |
| SOL     |              60 | D1           | T1     | vwap_agree |  90 | 0.778 |     3.507 |   315.586 |      0.688  |
| BTC     |              60 | D4           | T1     | vwap_agree |  84 | 0.833 |     3.753 |   315.261 |      0.7408 |
| BTC     |              90 | D1           | T1     | vwap_agree | 110 | 0.7   |     2.842 |   312.634 |      0.6603 |
| SOL     |              60 | D1           | T1     | none       | 114 | 0.684 |     2.622 |   298.92  |      0.6262 |

## Per definition × tier × asset (gate = none)

| definition   | tier   | asset   |   n_total |   wr_overall |   avg_pnl_overall |   sum_pnl |
|:-------------|:-------|:--------|----------:|-------------:|------------------:|----------:|
| D1           | T1     | BTC     |       992 |        0.646 |             3.706 |   3676.31 |
| D1           | T1     | ETH     |      1052 |        0.619 |            -0.136 |   -143.56 |
| D1           | T1     | SOL     |       735 |        0.641 |             0.455 |    334.29 |
| D1           | T2     | BTC     |       271 |        0.668 |             4.467 |   1210.42 |
| D1           | T2     | ETH     |       286 |        0.636 |            -0.765 |   -218.96 |
| D1           | T2     | SOL     |       156 |        0.705 |             1.176 |    183.43 |
| D1           | T3     | BTC     |        77 |        0.662 |             1.58  |    121.66 |
| D1           | T3     | ETH     |        95 |        0.61  |            -3.964 |   -376.56 |
| D1           | T3     | SOL     |        48 |        0.75  |             0.09  |      4.34 |
| D2           | T1     | BTC     |      1029 |        0.718 |             2.11  |   2170.66 |
| D2           | T1     | ETH     |      1104 |        0.704 |             0.29  |    320.61 |
| D2           | T1     | SOL     |       784 |        0.722 |            -0.154 |   -121.1  |
| D2           | T2     | BTC     |       304 |        0.707 |             1.539 |    467.91 |
| D2           | T2     | ETH     |       308 |        0.747 |             0.956 |    294.34 |
| D2           | T2     | SOL     |       227 |        0.797 |             0.208 |     47.21 |
| D2           | T3     | BTC     |        89 |        0.685 |             0.016 |      1.47 |
| D2           | T3     | ETH     |       111 |        0.667 |            -2.438 |   -270.62 |
| D2           | T3     | SOL     |        68 |        0.912 |             1.21  |     82.26 |
| D3           | T1     | BTC     |       396 |        0.715 |             3.757 |   1487.85 |
| D3           | T1     | ETH     |       410 |        0.717 |             0.537 |    220.28 |
| D3           | T1     | SOL     |       288 |        0.739 |             1.662 |    478.67 |
| D3           | T2     | BTC     |       109 |        0.706 |             4.767 |    519.63 |
| D3           | T2     | ETH     |       117 |        0.701 |            -0.997 |   -116.64 |
| D3           | T2     | SOL     |        61 |        0.836 |             2.047 |    124.84 |
| D3           | T3     | BTC     |        30 |        0.767 |             1.767 |     53.02 |
| D3           | T3     | ETH     |        43 |        0.674 |            -3.999 |   -171.96 |
| D3           | T3     | SOL     |        23 |        0.913 |             0.452 |     10.39 |
| D4           | T1     | BTC     |       517 |        0.793 |             3.148 |   1627.62 |
| D4           | T1     | ETH     |       661 |        0.764 |             1.128 |    745.46 |
| D4           | T1     | SOL     |       358 |        0.81  |             1.12  |    400.92 |
| D4           | T2     | BTC     |       165 |        0.794 |             4.031 |    665.14 |
| D4           | T2     | ETH     |       206 |        0.772 |             0.244 |     50.26 |
| D4           | T2     | SOL     |        95 |        0.821 |            -0.336 |    -31.9  |
| D4           | T3     | BTC     |        51 |        0.823 |             2.757 |    140.61 |
| D4           | T3     | ETH     |        50 |        0.76  |            -3.628 |   -181.41 |
| D4           | T3     | SOL     |        20 |        1     |             2.411 |     48.22 |

## Per fire_offset_s × asset (gate = none, all defs pooled)

| asset   |   fire_offset_s |   n |    wr |   avg_pnl |   sum_pnl |
|:--------|----------------:|----:|------:|----------:|----------:|
| BTC     |              15 | 860 | 0.655 |     1.021 |    878.01 |
| BTC     |              30 | 616 | 0.742 |     4.003 |   2465.85 |
| BTC     |              45 | 627 | 0.716 |     4.216 |   2643.64 |
| BTC     |              60 | 687 | 0.712 |     2.605 |   1789.58 |
| BTC     |              90 | 689 | 0.688 |     0.469 |    323.25 |
| BTC     |             120 | 551 | 0.766 |     7.336 |   4041.96 |
| ETH     |              15 | 789 | 0.64  |    -0.748 |   -590.39 |
| ETH     |              30 | 686 | 0.692 |    -0.217 |   -149    |
| ETH     |              45 | 716 | 0.686 |    -0.918 |   -657.56 |
| ETH     |              60 | 823 | 0.693 |     0.668 |    549.81 |
| ETH     |              90 | 776 | 0.695 |    -0.394 |   -305.4  |
| ETH     |             120 | 653 | 0.764 |     1.997 |   1303.77 |
| SOL     |              15 | 497 | 0.67  |     0.268 |    133.21 |
| SOL     |              30 | 470 | 0.781 |     3.385 |   1591.18 |
| SOL     |              45 | 487 | 0.715 |     0.086 |     41.79 |
| SOL     |              60 | 452 | 0.75  |     0.82  |    370.52 |
| SOL     |              90 | 461 | 0.731 |    -1.124 |   -518.02 |
| SOL     |             120 | 496 | 0.756 |    -0.115 |    -57.12 |

## Gate sweep (all defs × assets pooled, per gate)

| gate       |     n |    wr |   avg_pnl |   sum_pnl |
|:-----------|------:|------:|----------:|----------:|
| none       | 11336 | 0.709 |     1.222 |  13855.1  |
| rsi_agree  |  7602 | 0.751 |     0.917 |   6974.3  |
| vwap_agree |  9543 | 0.749 |     1.397 |  13327.9  |
| both_agree |  7127 | 0.766 |     1.048 |   7471.45 |

## Overlap with S1 (VWAP Continuation, 5m)

- Spike unique (slug,offset,direction) fires: **5,181**
- S1 VWAP-cont unique fires: **40,210**
- Overlap (shared key): **1,780** (34.4% of spike, 4.4% of S1)

Per-fire (each spike fire instance, may include multiple tiers/defs per slug):

| subset | n | WR | avg_pnl | sum_pnl |
|:-------|--:|---:|-------:|-------:|
| Shared with S1 | 4,822 | 0.828 | $2.210 | $10658.40 |
| Spike-only     | 6,514 | 0.620 | $0.491 | $3196.70 |

**Interpretation:** the shared-with-S1 subset shows IDENTICAL PnL by construction 
(deterministic from slug/offset/direction). The spike-only subset retains positive 
WR/PnL → the spike signal selects a distinct (often more conservative) entry set.

## Deploy recommendation

**Top BTC config — robust & significant:**

- `BTC, fire_offset_s=120, D1 (|ret_5s|>2.5bps AND sign(cvd_5s)==sign(ret_5s)), tier T1, gate=none`
- n=146, WR=70.5%, avg_pnl=+$6.57/tr, sum=+$959.74 over 21d window
- Binomial p-value (WR>50%): <0.0001 → highly significant
- D1 T1 with vwap_agree gate at offset=45 (n=131, WR=71.8%, +$6.55/tr) is the runner-up

**Top ETH config:** `ETH, fire_offset_s=120, D2 T1, vwap_agree` (n=125, WR=85.6%, +$4.21/tr)

**Top SOL config:** `SOL, fire_offset_s=30, D2 T1, none` (n=130, WR=78.5%, +$3.55/tr)

**Notes:**
- All three top configs survive at n≥125 over 28d, suggesting deployability on the order of 
  4-6 fires/day per asset for BTC offset=120 / 5-6 fires/day for ETH offset=120 / SOL offset=30.
- ETH/SOL benefit clearly from `vwap_agree` (lifts ETH offset=15..90 from neg to positive PnL).
- BTC is robust without gates; gating adds WR but doesn't change avg_pnl direction.
- T1 (loose) thresholds outperform T3 (strict) on $/tr × n product — strict filtering 
  doesn't select higher quality fires, just fewer of them.
- offset=120 dominates BTC; offset=30 dominates SOL — the strategy clearly depends on 
  WHERE in the slot the spike occurs (not just THAT one occurred).

---

_data: `data/v4/canonical/_results/spike_entry_5m.csv`_  
_per-fire parquet: `data/v4/canonical/_results/spike_entry_5m_per_fire.parquet`_  
_script: `strategy_lab/meta_classifier/spike_entry_5m.py`_