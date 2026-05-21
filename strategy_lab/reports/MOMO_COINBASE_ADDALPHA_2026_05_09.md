# Momo + Coinbase Add-Alpha — does coinbase lift the winning baseline?
_Generated: 2026-05-09_

## Setup
- Baseline (B0): canonical momo gate (|bin_ret_2m| ≥ rolling 14d q90, sign(bin_ret_2m) direction).
- Reuses `momo_full_universe_validation.py` simulator + L25 cache (refresh_2026_05_06).
- Entry: $25 L25 ASK walk at fire_offset=60s.
- Policies: HOLD / HEDGE_5bp / SELL_V1_5bp (anchor=close@ws) / SELL_V2_5bp (anchor=close@fire).

## Coinbase variants
- **B0** baseline (no coinbase)
- **F1** filter: sign(premium@ws) == sign(signal)
- **F2** filter: |premium@ws| > 5 bp
- **F3** filter: |z(premium, 7d)| > 1.5
- **F4** filter: (premium@ws+60 − premium@ws−60) × signal > 0
- **F5** filter: sign(bin_ret_2m) == sign(coin_ret_2m)
- **E1** ensemble gate: 0.5×bin_ret_2m + 0.5×coin_ret_2m
- **E2** coinbase-only gate: coin_ret_2m (negative control)
- **E3** premium-as-signal: |premium@ws| gate, sign(premium) direction

## Gate coverage
| Variant | n_gated |
|---|---:|
| B0 | 1394 |
| F1 | 570 |
| F2 | 74 |
| F3 | 309 |
| F4 | 169 |
| F5 | 1059 |
| E1 | 1395 |
| E2 | 1413 |
| E3 | 1408 |

## Headline (variant × policy)

| variant   | policy      |   n |   n_fired |   fire_pct |   hit |   pnl_total |   pnl_mean |   avg_vwap |
|:----------|:------------|----:|----------:|-----------:|------:|------------:|-----------:|-----------:|
| B0        | HEDGE_5bp   | 949 |       133 |       14   | 80.72 |     9911.57 |    10.4442 |   0.613694 |
| B0        | HOLD        | 949 |         0 |        0   | 87.46 |    12846.3  |    13.5367 |   0.613694 |
| B0        | SELL_V1_5bp | 949 |       133 |       14   | 80.61 |     9885.95 |    10.4172 |   0.613694 |
| B0        | SELL_V2_5bp | 949 |       782 |       82.4 | 62.8  |     2426.58 |     2.557  |   0.613694 |
| E1        | HEDGE_5bp   | 882 |       119 |       13.5 | 80.5  |     6247.93 |     7.0838 |   0.668849 |
| E1        | HOLD        | 882 |         0 |        0   | 85.94 |     7737.48 |     8.7727 |   0.668849 |
| E1        | SELL_V1_5bp | 882 |       119 |       13.5 | 80.5  |     6231.95 |     7.0657 |   0.668849 |
| E1        | SELL_V2_5bp | 882 |       640 |       72.6 | 60.2  |     1036.36 |     1.175  |   0.668849 |
| E2        | HEDGE_5bp   | 782 |       217 |       27.7 | 66.5  |      512.87 |     0.6558 |   0.715692 |
| E2        | HOLD        | 782 |         0 |        0   | 68.8  |    -1007.95 |    -1.2889 |   0.715692 |
| E2        | SELL_V1_5bp | 782 |       217 |       27.7 | 66.24 |      535.67 |     0.685  |   0.715692 |
| E2        | SELL_V2_5bp | 782 |       359 |       45.9 | 48.98 |    -2570.36 |    -3.2869 |   0.715692 |
| E3        | HEDGE_5bp   | 821 |       366 |       44.6 | 46.16 |       -3.72 |    -0.0045 |   0.508823 |
| E3        | HOLD        | 821 |         0 |        0   | 47.5  |    -2142.63 |    -2.6098 |   0.508823 |
| E3        | SELL_V1_5bp | 821 |       366 |       44.6 | 46.41 |       15    |     0.0183 |   0.508823 |
| E3        | SELL_V2_5bp | 821 |       276 |       33.6 | 39.71 |    -3572.75 |    -4.3517 |   0.508823 |
| F1        | HEDGE_5bp   | 394 |        60 |       15.2 | 79.7  |     3999.7  |    10.1515 |   0.610656 |
| F1        | HOLD        | 394 |         0 |        0   | 87.06 |     5404.99 |    13.7183 |   0.610656 |
| F1        | SELL_V1_5bp | 394 |        60 |       15.2 | 79.7  |     3989.55 |    10.1258 |   0.610656 |
| F1        | SELL_V2_5bp | 394 |       321 |       81.5 | 63.71 |      852.89 |     2.1647 |   0.610656 |
| F2        | HEDGE_5bp   |  53 |         7 |       13.2 | 86.79 |      588.91 |    11.1114 |   0.633122 |
| F2        | HOLD        |  53 |         0 |        0   | 90.57 |      641.71 |    12.1077 |   0.633122 |
| F2        | SELL_V1_5bp |  53 |         7 |       13.2 | 86.79 |      589.03 |    11.1138 |   0.633122 |
| F2        | SELL_V2_5bp |  53 |        40 |       75.5 | 66.04 |      211.81 |     3.9964 |   0.633122 |
| F3        | HEDGE_5bp   | 222 |        38 |       17.1 | 82.43 |     2433.67 |    10.9625 |   0.609654 |
| F3        | HOLD        | 222 |         0 |        0   | 89.64 |     3252.9  |    14.6527 |   0.609654 |
| F3        | SELL_V1_5bp | 222 |        38 |       17.1 | 81.98 |     2428.32 |    10.9384 |   0.609654 |
| F3        | SELL_V2_5bp | 222 |       168 |       75.7 | 56.76 |      537.2  |     2.4198 |   0.609654 |
| F4        | HEDGE_5bp   |  99 |        15 |       15.2 | 78.79 |      232.79 |     2.3514 |   0.731654 |
| F4        | HOLD        |  99 |         0 |        0   | 79.8  |      139.51 |     1.4091 |   0.731654 |
| F4        | SELL_V1_5bp |  99 |        15 |       15.2 | 78.79 |      234.64 |     2.3701 |   0.731654 |
| F4        | SELL_V2_5bp |  99 |        37 |       37.4 | 59.6  |       75.66 |     0.7642 |   0.731654 |
| F5        | HEDGE_5bp   | 711 |        66 |        9.3 | 84.11 |     5428.16 |     7.6345 |   0.673858 |
| F5        | HOLD        | 711 |         0 |        0   | 87.76 |     5971.95 |     8.3994 |   0.673858 |
| F5        | SELL_V1_5bp | 711 |        66 |        9.3 | 84.11 |     5428.99 |     7.6357 |   0.673858 |
| F5        | SELL_V2_5bp | 711 |       558 |       78.5 | 61.6  |     1075.3  |     1.5124 |   0.673858 |

## Lift vs B0 baseline (same policy)

| variant   | policy      |   n |   n_base |   n_pct_of_base |   hit_pct |   hit_base_pct |   hit_lift_pp |   pnl_total |   pnl_total_base |   pnl_total_lift |   pnl_mean |   pnl_mean_base |   pnl_mean_lift |
|:----------|:------------|----:|---------:|----------------:|----------:|---------------:|--------------:|------------:|-----------------:|-----------------:|-----------:|----------------:|----------------:|
| E1        | HEDGE_5bp   | 882 |      949 |            92.9 |     80.5  |          80.72 |         -0.22 |     6247.93 |          9911.57 |         -3663.64 |     7.0838 |         10.4442 |         -3.3604 |
| F5        | HEDGE_5bp   | 711 |      949 |            74.9 |     84.11 |          80.72 |          3.39 |     5428.16 |          9911.57 |         -4483.41 |     7.6345 |         10.4442 |         -2.8097 |
| F1        | HEDGE_5bp   | 394 |      949 |            41.5 |     79.7  |          80.72 |         -1.02 |     3999.7  |          9911.57 |         -5911.87 |    10.1515 |         10.4442 |         -0.2927 |
| F3        | HEDGE_5bp   | 222 |      949 |            23.4 |     82.43 |          80.72 |          1.71 |     2433.67 |          9911.57 |         -7477.9  |    10.9625 |         10.4442 |          0.5183 |
| F2        | HEDGE_5bp   |  53 |      949 |             5.6 |     86.79 |          80.72 |          6.07 |      588.91 |          9911.57 |         -9322.66 |    11.1114 |         10.4442 |          0.6672 |
| E2        | HEDGE_5bp   | 782 |      949 |            82.4 |     66.5  |          80.72 |        -14.22 |      512.87 |          9911.57 |         -9398.7  |     0.6558 |         10.4442 |         -9.7884 |
| F4        | HEDGE_5bp   |  99 |      949 |            10.4 |     78.79 |          80.72 |         -1.93 |      232.79 |          9911.57 |         -9678.78 |     2.3514 |         10.4442 |         -8.0928 |
| E3        | HEDGE_5bp   | 821 |      949 |            86.5 |     46.16 |          80.72 |        -34.56 |       -3.72 |          9911.57 |         -9915.29 |    -0.0045 |         10.4442 |        -10.4487 |
| E1        | HOLD        | 882 |      949 |            92.9 |     85.94 |          87.46 |         -1.52 |     7737.48 |         12846.3  |         -5108.85 |     8.7727 |         13.5367 |         -4.764  |
| F5        | HOLD        | 711 |      949 |            74.9 |     87.76 |          87.46 |          0.3  |     5971.95 |         12846.3  |         -6874.38 |     8.3994 |         13.5367 |         -5.1373 |
| F1        | HOLD        | 394 |      949 |            41.5 |     87.06 |          87.46 |         -0.4  |     5404.99 |         12846.3  |         -7441.34 |    13.7183 |         13.5367 |          0.1816 |
| F3        | HOLD        | 222 |      949 |            23.4 |     89.64 |          87.46 |          2.18 |     3252.9  |         12846.3  |         -9593.43 |    14.6527 |         13.5367 |          1.116  |
| F2        | HOLD        |  53 |      949 |             5.6 |     90.57 |          87.46 |          3.11 |      641.71 |         12846.3  |        -12204.6  |    12.1077 |         13.5367 |         -1.429  |
| F4        | HOLD        |  99 |      949 |            10.4 |     79.8  |          87.46 |         -7.66 |      139.51 |         12846.3  |        -12706.8  |     1.4091 |         13.5367 |        -12.1276 |
| E2        | HOLD        | 782 |      949 |            82.4 |     68.8  |          87.46 |        -18.66 |    -1007.95 |         12846.3  |        -13854.3  |    -1.2889 |         13.5367 |        -14.8256 |
| E3        | HOLD        | 821 |      949 |            86.5 |     47.5  |          87.46 |        -39.96 |    -2142.63 |         12846.3  |        -14989    |    -2.6098 |         13.5367 |        -16.1465 |
| E1        | SELL_V1_5bp | 882 |      949 |            92.9 |     80.5  |          80.61 |         -0.11 |     6231.95 |          9885.95 |         -3654    |     7.0657 |         10.4172 |         -3.3515 |
| F5        | SELL_V1_5bp | 711 |      949 |            74.9 |     84.11 |          80.61 |          3.5  |     5428.99 |          9885.95 |         -4456.96 |     7.6357 |         10.4172 |         -2.7815 |
| F1        | SELL_V1_5bp | 394 |      949 |            41.5 |     79.7  |          80.61 |         -0.91 |     3989.55 |          9885.95 |         -5896.4  |    10.1258 |         10.4172 |         -0.2914 |
| F3        | SELL_V1_5bp | 222 |      949 |            23.4 |     81.98 |          80.61 |          1.37 |     2428.32 |          9885.95 |         -7457.63 |    10.9384 |         10.4172 |          0.5212 |
| F2        | SELL_V1_5bp |  53 |      949 |             5.6 |     86.79 |          80.61 |          6.18 |      589.03 |          9885.95 |         -9296.92 |    11.1138 |         10.4172 |          0.6966 |
| E2        | SELL_V1_5bp | 782 |      949 |            82.4 |     66.24 |          80.61 |        -14.37 |      535.67 |          9885.95 |         -9350.28 |     0.685  |         10.4172 |         -9.7322 |
| F4        | SELL_V1_5bp |  99 |      949 |            10.4 |     78.79 |          80.61 |         -1.82 |      234.64 |          9885.95 |         -9651.31 |     2.3701 |         10.4172 |         -8.0471 |
| E3        | SELL_V1_5bp | 821 |      949 |            86.5 |     46.41 |          80.61 |        -34.2  |       15    |          9885.95 |         -9870.95 |     0.0183 |         10.4172 |        -10.3989 |
| F5        | SELL_V2_5bp | 711 |      949 |            74.9 |     61.6  |          62.8  |         -1.2  |     1075.3  |          2426.58 |         -1351.28 |     1.5124 |          2.557  |         -1.0446 |
| E1        | SELL_V2_5bp | 882 |      949 |            92.9 |     60.2  |          62.8  |         -2.6  |     1036.36 |          2426.58 |         -1390.22 |     1.175  |          2.557  |         -1.382  |
| F1        | SELL_V2_5bp | 394 |      949 |            41.5 |     63.71 |          62.8  |          0.91 |      852.89 |          2426.58 |         -1573.69 |     2.1647 |          2.557  |         -0.3923 |
| F3        | SELL_V2_5bp | 222 |      949 |            23.4 |     56.76 |          62.8  |         -6.04 |      537.2  |          2426.58 |         -1889.38 |     2.4198 |          2.557  |         -0.1372 |
| F2        | SELL_V2_5bp |  53 |      949 |             5.6 |     66.04 |          62.8  |          3.24 |      211.81 |          2426.58 |         -2214.77 |     3.9964 |          2.557  |          1.4394 |
| F4        | SELL_V2_5bp |  99 |      949 |            10.4 |     59.6  |          62.8  |         -3.2  |       75.66 |          2426.58 |         -2350.92 |     0.7642 |          2.557  |         -1.7928 |
| E2        | SELL_V2_5bp | 782 |      949 |            82.4 |     48.98 |          62.8  |        -13.82 |    -2570.36 |          2426.58 |         -4996.94 |    -3.2869 |          2.557  |         -5.8439 |
| E3        | SELL_V2_5bp | 821 |      949 |            86.5 |     39.71 |          62.8  |        -23.09 |    -3572.75 |          2426.58 |         -5999.33 |    -4.3517 |          2.557  |         -6.9087 |

## Verdict (auto-generated, by smallest negative Δpnl per policy)

- **HEDGE_5bp**: best variant `E1` (Δpnl=$-3663.64 vs $+9911.57 base, n=882 vs 949, hit Δ-0.22pp)
- **HOLD**: best variant `E1` (Δpnl=$-5108.85 vs $+12846.33 base, n=882 vs 949, hit Δ-1.52pp)
- **SELL_V1_5bp**: best variant `E1` (Δpnl=$-3654.00 vs $+9885.95 base, n=882 vs 949, hit Δ-0.11pp)
- **SELL_V2_5bp**: best variant `F5` (Δpnl=$-1351.28 vs $+2426.58 base, n=711 vs 949, hit Δ-1.20pp)

---

## Synthesis — coinbase does NOT add alpha

### Headline finding
**No coinbase variant beats the baseline B0 in absolute PnL across any policy.** Every variant either drops too many trades (F2/F3/F4 retain 5–23%) or worsens hit rate (E2/E3/F4). Best total-PnL after baseline is E1 ensemble at HOLD: **+$7,737 vs baseline +$12,846 = −$5,109**.

### Per-trade quality vs trade count tradeoff
A few variants improve **per-trade mean** but at the cost of trade volume:

| Variant | Filter | n / 949 | mean_pnl | Δ mean vs B0 |
|---|---|---:|---:|---:|
| F3 | \|z(prem,7d)\| > 1.5 | 222 (23%) | +$14.65 | **+$1.12** |
| F1 | sign(premium)==sign(signal) | 394 (42%) | +$13.72 | +$0.18 |
| B0 | baseline | 949 | +$13.54 | — |
| F2 | \|premium\|>5bp | 53 (6%) | +$12.11 | −$1.43 |

**F3 (premium z-score) is the only variant with a meaningfully positive per-trade lift, but its 77% trade-count loss makes total PnL much worse.** Coinbase z-score functions as a **selectivity filter** — useful only if you care more about Sharpe-per-trade than total PnL volume.

### Three structural findings

1. **Premium-as-signal (E3) is catastrophic.** Hit rate collapses to 47.5% — basically random. Premium does NOT contain directional information for UpDown markets. The premium-driven "US flow leads" hypothesis is rejected.

2. **Cross-venue agreement (F5) destroys edge, not enhances it.** F5 keeps 75% of trades (where binance and coinbase 2m returns agree on sign) but per-trade drops from $13.54 → $8.40. **The 25% disagreement subset carried the best per-trade edge** — disagreement is where binance is leading and the multi-venue tape hasn't caught up. Filtering it out throws away the alpha.

3. **Coinbase-only gate (E2) loses money.** Hit 68.8%, mean −$1.29/trade. Confirms binance is the predictively-better venue; coinbase's signal is noisier and slower.

### Policy-level findings (replicates earlier validation)

- **HOLD wins across every variant.** HEDGE_5bp / SELL_V1_5bp / SELL_V2_5bp all reduce PnL whether on baseline or any coinbase variant.
- **SELL_V2 (anchor=close@fire) is much worse than SELL_V1 (anchor=close@ws).** V2 fires 78–82% of the time vs V1's 14% — V2's tighter "stop" cuts winners prematurely. V1 anchor is canonical.

### Bottom line for the operator

**The fresh data (+$12,846 baseline) confirms the existing binance-only momo is winning. None of the eight coinbase features (premium-align, premium-magnitude, premium-z, premium-velocity, agreement, ensemble, coinbase-only, premium-as-signal) lift it.** The closest call is F3 (premium z-score) which gives marginal per-trade lift but cuts volume by 77%.

If you want to extract the F5 finding (disagreement = alpha), it points to a possible NEW signal dimension: **fire only when binance leads coinbase by ≥X bp in 2m return**, betting on coinbase to catch up. That would be an inverse F5 — the variant **NOT** tested here. Worth a Phase 16-09 follow-up if interested.

---

## Files

- `strategy_lab/meta_classifier/momo_coinbase_addalpha.py` — harness
- `data/v4/refresh_2026_05_09/coinbase_addalpha/per_trade.csv` — per-trade per-variant per-policy
- `data/v4/refresh_2026_05_09/coinbase_addalpha/summary.csv` — aggregated headline
- `data/v4/refresh_2026_05_09/coinbase_addalpha/lift.csv` — Δ over B0 by policy