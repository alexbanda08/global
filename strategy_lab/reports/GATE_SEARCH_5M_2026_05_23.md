# Gate search — 5m up-down momo (combinatorial 2^9)

**Generated:** 2026-05-23  
**Data:** `fv_cvd_spike_overlay.parquet` (Baseline_v1/v2) ⨝ `per_trade_markov.parquet` on `(variant, slug)`; restricted to `tf=5m`.
**Universe:** 3456 fires across 6 cells. Window: 28d up to 2026-05-21 20:10 UTC.
**Gates (9):** `hod_pass`, `f7_pass`, `m1v_pass`, `m5v_pass`, `cvd_agree`, `spike_no_anti`, `edge_ge_2pp`, `mag_in_sweetspot`, `cvd_strong`.

**Method:** enumerate 2^9=512 gate subsets per cell, AND-combined; keep n>=30 & WR>=0.55; rank by `score = WR · √n · 1[avg_pnl>0]`. Report deployable cells (WR>=0.60) and minimal-gate variant.

## Baseline (no gates) per cell

| cell | fam | n | WR | $/tr | sum_pnl |
|---|---|---:|---:|---:|---:|
| btc_5m | momo | 813 | 0.478 | -1.4457 | -1175.35 |
| eth_5m | momo | 458 | 0.461 | -2.4683 | -1130.46 |
| sol_5m | momo | 325 | 0.520 | +0.2146 | +69.74 |
| btc_5m | momo_v2 | 807 | 0.486 | -1.1087 | -894.73 |
| eth_5m | momo_v2 | 593 | 0.494 | -0.8134 | -482.33 |
| sol_5m | momo_v2 | 460 | 0.502 | -0.6738 | -309.95 |

## Per-cell top configs

### `momo__btc_5m`

**Top 5 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | hod_pass+m5v_pass+cvd_strong | 33 | 0.606 | +5.5620 | +183.54 | 0.225 | 3 | 3.482 |
| 2 | hod_pass+m5v_pass+spike_no_anti+cvd_strong | 33 | 0.606 | +5.5620 | +183.54 | 0.225 | 3 | 3.482 |
| 3 | hod_pass+m5v_pass+cvd_agree+cvd_strong | 31 | 0.613 | +5.8711 | +182.00 | 0.239 | 3 | 3.413 |
| 4 | hod_pass+m5v_pass+cvd_agree+spike_no_anti+cvd_strong | 31 | 0.613 | +5.8711 | +182.00 | 0.239 | 3 | 3.413 |
| 5 | hod_pass+m1v_pass+m5v_pass+cvd_strong | 30 | 0.600 | +5.3810 | +161.43 | 0.217 | 3 | 3.286 |

**Minimal deployable** (3 gates): `hod_pass+m5v_pass+cvd_strong` → n=33, WR=0.606, $/tr=+5.5620, sum=$+183.54.

### `momo__eth_5m`

**Top 5 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | hod_pass+cvd_agree+mag_in_sweetspot | 77 | 0.610 | +4.8884 | +376.41 | 0.204 | 5 | 5.356 |
| 2 | hod_pass+cvd_agree+spike_no_anti+mag_in_sweetspot | 77 | 0.610 | +4.8884 | +376.41 | 0.204 | 5 | 5.356 |
| 3 | hod_pass+m1v_pass+mag_in_sweetspot | 75 | 0.600 | +4.9405 | +370.54 | 0.202 | 5 | 5.196 |
| 4 | hod_pass+m1v_pass+spike_no_anti+mag_in_sweetspot | 75 | 0.600 | +4.9405 | +370.54 | 0.202 | 5 | 5.196 |
| 5 | hod_pass+m5v_pass+mag_in_sweetspot | 53 | 0.641 | +6.8288 | +361.93 | 0.287 | 5 | 4.670 |

**Minimal deployable** (3 gates): `hod_pass+cvd_agree+mag_in_sweetspot` → n=77, WR=0.610, $/tr=+4.8884, sum=$+376.41.

### `momo__sol_5m`

**Top 5 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | spike_no_anti+edge_ge_2pp+cvd_strong | 55 | 0.600 | +4.3794 | +240.87 | 0.182 | 8 | 4.450 |
| 2 | hod_pass+cvd_agree+mag_in_sweetspot | 51 | 0.608 | +4.2986 | +219.23 | 0.182 | 6 | 4.341 |
| 3 | hod_pass+cvd_agree+spike_no_anti+mag_in_sweetspot | 51 | 0.608 | +4.2986 | +219.23 | 0.182 | 6 | 4.341 |
| 4 | cvd_agree+spike_no_anti+edge_ge_2pp+cvd_strong | 48 | 0.625 | +5.6099 | +269.27 | 0.236 | 7 | 4.330 |
| 5 | cvd_agree+edge_ge_2pp+cvd_strong | 49 | 0.612 | +4.9852 | +244.27 | 0.209 | 8 | 4.286 |

**Minimal deployable** (2 gates): `hod_pass+cvd_strong` → n=32, WR=0.625, $/tr=+5.4880, sum=$+175.62.

### `momo_v2__btc_5m`

**Top 5 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | hod_pass+spike_no_anti+edge_ge_2pp | 135 | 0.600 | +4.4923 | +606.47 | 0.186 | 4 | 6.971 |
| 2 | hod_pass+spike_no_anti+edge_ge_2pp+mag_in_sweetspot | 115 | 0.600 | +4.4619 | +513.12 | 0.185 | 5 | 6.434 |
| 3 | hod_pass+spike_no_anti+edge_ge_2pp+cvd_strong | 58 | 0.638 | +6.3334 | +367.33 | 0.268 | 4 | 4.858 |
| 4 | hod_pass+edge_ge_2pp+cvd_strong | 59 | 0.627 | +5.8023 | +342.33 | 0.244 | 4 | 4.817 |
| 5 | hod_pass+spike_no_anti+edge_ge_2pp+mag_in_sweetspot+cvd_strong | 41 | 0.683 | +8.4780 | +347.60 | 0.371 | 3 | 4.373 |

**Minimal deployable** (3 gates): `hod_pass+spike_no_anti+edge_ge_2pp` → n=135, WR=0.600, $/tr=+4.4923, sum=$+606.47.

### `momo_v2__eth_5m`

**Top 5 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | m1v_pass+m5v_pass+mag_in_sweetspot | 113 | 0.602 | +5.1649 | +583.63 | 0.210 | 3 | 6.397 |
| 2 | m5v_pass+cvd_agree+mag_in_sweetspot | 105 | 0.610 | +5.1126 | +536.83 | 0.212 | 3 | 6.246 |
| 3 | m5v_pass+cvd_agree+spike_no_anti+mag_in_sweetspot | 104 | 0.606 | +4.9529 | +515.10 | 0.205 | 3 | 6.178 |
| 4 | m5v_pass+edge_ge_2pp+mag_in_sweetspot | 87 | 0.621 | +5.8031 | +504.87 | 0.241 | 5 | 5.789 |
| 5 | m5v_pass+spike_no_anti+edge_ge_2pp+mag_in_sweetspot | 86 | 0.616 | +5.5968 | +481.33 | 0.232 | 5 | 5.715 |

**Minimal deployable** (2 gates): `hod_pass+m5v_pass` → n=62, WR=0.613, $/tr=+5.6201, sum=$+348.44.

### `momo_v2__sol_5m`

**Top 4 deployable configs** (WR ≥ 0.60, n ≥ 30):

| rank | gates | n | WR | $/tr | sum | sharpe | mcl | score |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | m5v_pass+spike_no_anti+edge_ge_2pp+cvd_strong | 30 | 0.667 | +7.7258 | +231.77 | 0.334 | 3 | 3.651 |
| 2 | m5v_pass+edge_ge_2pp+cvd_strong | 31 | 0.645 | +6.6701 | +206.77 | 0.284 | 3 | 3.592 |
| 3 | m5v_pass+cvd_agree+mag_in_sweetspot+cvd_strong | 35 | 0.600 | +4.3600 | +152.60 | 0.182 | 3 | 3.550 |
| 4 | m5v_pass+cvd_agree+spike_no_anti+mag_in_sweetspot+cvd_strong | 35 | 0.600 | +4.3600 | +152.60 | 0.182 | 3 | 3.550 |

**Minimal deployable** (3 gates): `m5v_pass+edge_ge_2pp+cvd_strong` → n=31, WR=0.645, $/tr=+6.6701, sum=$+206.77.

## Cross-cell insights

All 6 cells have at least one deployable config.

### Gate frequency in deployable configs (per cell)

| cell | hod_pass | f7_pass | m1v_pass | m5v_pass | cvd_agree | spike_no_anti | edge_ge_2pp | mag_in_sweetspot | cvd_strong |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| momo__btc_5m | 1.00 | 0.00 | 0.33 | 1.00 | 0.33 | 0.50 | 0.00 | 0.00 | 1.00 |
| momo__eth_5m | 1.00 | 0.20 | 0.40 | 0.50 | 0.40 | 0.50 | 0.00 | 0.90 | 0.20 |
| momo__sol_5m | 0.41 | 0.27 | 0.27 | 0.00 | 0.59 | 0.59 | 0.68 | 0.45 | 0.68 |
| momo_v2__btc_5m | 1.00 | 0.27 | 0.07 | 0.00 | 0.27 | 0.60 | 1.00 | 0.53 | 0.87 |
| momo_v2__eth_5m | 0.57 | 0.43 | 0.45 | 0.85 | 0.11 | 0.47 | 0.36 | 0.83 | 0.19 |
| momo_v2__sol_5m | 0.00 | 0.00 | 0.00 | 1.00 | 0.50 | 0.50 | 0.50 | 0.50 | 1.00 |

_Values = fraction of deployable configs (per cell) that include each gate._

### Best single-gate filters (WR uplift over baseline)

| cell | gate | n | WR | uplift_pp | $/tr |
|---|---|---:|---:|---:|---:|
| momo__sol_5m | hod_pass | 103 | 0.553 | +3.3 | +1.7555 |
| momo_v2__eth_5m | m5v_pass | 203 | 0.557 | +6.3 | +2.6947 |
