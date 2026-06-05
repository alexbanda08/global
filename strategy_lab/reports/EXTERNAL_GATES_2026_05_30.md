# External Causal Gates Sweep — 2026-05-30

**Scope:** 17 sleeves with n≥60 resolved live fires (5041 total fires, May 27–30).  
**Features tested:** Binance momentum (4 horizons), Chainlink basis, HL liquidation cascade, Polymarket CVD.  
**Validation rule:** gate must improve mean pnl_usd in BOTH chronological halves (50/50 split by fire_us).  
**Script:** `strategy_lab/_opt_2026_05_30/06_external_gates.py`  
**Output:** `strategy_lab/_opt_2026_05_30/_results/external_gates.csv`

---

## Feed Coverage

| Feed | Coverage | Notes |
|------|----------|-------|
| Binance 1s klines (momentum) | 5041/5041 (100%) | Full coverage, `klines_1s.parquet`, binance-spot-ws |
| Chainlink RTDS (basis) | 5041/5041 (100%) | All fires have CL price asof |
| HL liquidations | 0/5041 (0%) | HL liq data ends 2026-05-27 13:35; fires start 14:55 — zero overlap |
| Polymarket CVD (30s) | 978/5041 (19.4%) | Only slugs with recent trades before fire_us |
| Polymarket CVD (60s) | 1127/5041 (22.4%) | Slightly better window coverage |

---

## Key Findings

### 1. HL Liquidation Cascade — DEAD FEED

HL liquidation data ends at 2026-05-27 13:35 UTC; all fires occur at ≥14:55 UTC. Zero coverage. No gate possible. Feed must be refreshed before this test is meaningful.

### 2. Chainlink Basis — SPURIOUS (structural artifact)

`basis_bps = (binance_px - cl_px) / cl_px * 1e4` is always positive and always >3bps across all three assets:
- BTC: mean=14.54bps, range=[6.06, 24.59]
- ETH: constant 14.93bps (ETH CL RTDS frozen at one tick in this window)
- SOL: mean=14.48bps, range=[2.08, 23.66]

**Consequence:** `basis_agrees = (basis_bps * dir_sign > 0)` is 100% equivalent to `direction == 'UP'`. It is not a causal external signal — it is a direction label. `basis_large` is always True (100% of fires). Both gates are useless.

Two sleeves nominally "passed" the both-half test on `basis_agrees` — those are direction-only filters in disguise (confirmed below).

### 3. Binance Momentum — ONE SLEEVE, GENUINE

**`sol_5m_rf_tr_partial_mid`** (n=371, base_mean=+$0.25/fire) passes on all four momentum horizons:

| Gate | n_gated | % gated | gated_mean | lift | H1 lift | H2 lift |
|------|---------|---------|------------|------|---------|---------|
| ma_300 (5m agree) | 141 | 38% | +$2.02 | **+$1.77** | +$1.91 | +$2.24 |
| ma_120 (2m agree) | 99 | 27% | +$1.86 | **+$1.61** | +$1.65 | +$3.06 |
| ma_60 (1m agree) | 102 | 27% | +$1.13 | **+$0.88** | +$1.02 | +$1.49 |
| ma_30 (30s agree) | 80 | 22% | +$0.97 | **+$0.72** | +$0.70 | +$2.20 |

**Key: the gate works within both UP and DOWN directions** (not a direction proxy):
- ma_300=True, UP: n=78, mean=+$2.17
- ma_300=True, DOWN: n=63, mean=+$1.84
- ma_300=False, UP: n=124, mean=−$1.00
- ma_300=False, DOWN: n=106, mean=−$0.64

The 5m/2m horizons provide the best lift. `ma_300` retains 38% of fires at 8x the mean pnl of ungated. Rejected fires are net-negative (mean −$0.64 to −$1.00).

**No other sleeve** shows a momo gate passing both halves. The 16 other sleeves either had no gate pass, or had only spurious basis_agrees.

### 4. Polymarket CVD — WEAK PASS, low coverage

**`sol_5m_rf_tr_partial_mid`** also passes on `cvd30_align` (net buy flow in direction in 30s before fire):

| Gate | n_gated | % gated | gated_mean | lift | H1 lift | H2 lift |
|------|---------|---------|------------|------|---------|---------|
| cvd30_align | 118 | 32% | +$0.48 | **+$0.23** | +$0.22 | +$0.27 |

Coverage is 37.7% (only fires with trade activity in the slug in the prior 30s). Lift is modest (+$0.23 vs base +$0.25) and far weaker than the momentum gates. Combined with ma_300: n=73, mean=+$2.84 — incremental over ma_300 alone (+$2.02), but n shrinks to 73.

No other sleeve passes CVD gates. cvd60_align fails on all sleeves tested.

---

## Sleeve-by-Sleeve Verdict

| Sleeve | n | base_mean | Best genuine gate | lift | verdict |
|--------|---|-----------|-------------------|------|---------|
| sol_5m_rf_tr_partial_mid | 371 | +0.25 | ma_300 (38% retained) | +1.77 | **PASS — deploy gate** |
| sol_5m_f7_mfi_ema200_vwap_v6 | 418 | +0.00 | basis_agrees (SPURIOUS = UP only) | — | FAIL |
| eth_5m_l_ema50_hurst_grandparent_v8 | 78 | +0.92 | basis_agrees (SPURIOUS = UP only) | — | FAIL |
| btc_5m_q_parent15mslope_ts_imb5_v8 | 1232 | −0.76 | none | — | FAIL |
| ALL_5m_phase1_kelly | 858 | +0.29 | none (basis_agrees splits H1/H2) | — | FAIL |
| btc_5m_l_1hrf_imb5_ribbon_v8 | 506 | −0.28 | none | — | FAIL |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 233 | +0.06 | none | — | FAIL |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 222 | +0.05 | none | — | FAIL |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | 176 | +0.03 | none | — | FAIL |
| eth_5m_bb_mp_hurst_band_v6_vL | 122 | +0.37 | none | — | FAIL |
| btc_5m_ts_mpskew_any_off30 | 120 | −0.77 | none | — | FAIL |
| eth_5m_bb_mp_hurst_band_v6 | 107 | +0.47 | none | — | FAIL |
| eth_5m_cloud_vwap_hurstmp_v7 | 93 | +0.34 | none | — | FAIL |
| eth_5m_cloud_ribbon_mp_hurst_v6 | 84 | +0.16 | none | — | FAIL |
| ALL_5m_S3_prewindow | 300 | +1.08 | none (basis_agrees splits H1/H2) | — | FAIL |
| btc_15m_ema50_ema800_off600_down | 61 | +0.86 | none | — | FAIL |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 60 | +0.54 | none (basis_agrees splits H1/H2) | — | FAIL |

---

## Recommended Gate: `sol_5m_rf_tr_partial_mid` + `ma_300`

**Rule:** fire only when `log(binance_px_now / binance_px_5m_ago) * dir_sign > 0`  
**Both directions:** UP requires price rose in last 5m; DOWN requires price fell.  
**Coverage:** 38% of fires retained (141/371 in sample).  
**Lift:** +$1.77/fire over ungated base (+$0.25 → +$2.02).  
**Rejected fires:** mean −$0.80/fire — these are genuinely bad fires, not random noise.  
**Both-half stability:** H1=+$1.91, H2=+$2.24 — strengthens over time.

Optional stacking with cvd30_align (+$0.82 incremental over ma_300 alone) reduces n to 73 fires but improves mean to +$2.84/fire. Use only if CVD data is consistently available (currently 37.7% coverage).

---

## What Was Useless

- **Chainlink basis**: structural — Binance always ~14bps above CL RTDS in this window. All gates derived from it are direction proxies.
- **HL liquidations**: feed ends before fire window starts. Must refresh before retesting.
- **CVD on all non-SOL-rf-tr sleeves**: either too sparse (<19% coverage) or failed both-half test.
- **Momentum on 16/17 sleeves**: no consistent signal. Only `sol_5m_rf_tr_partial_mid` has clear momentum-follows-direction structure.

---

## Methodology Notes

- All features computed strictly causal: `asof ≤ fire_us` via `searchsorted(side='right') - 1`.
- `pnl_usd` used as-is (logged, includes Polymarket 2%-on-profit fee).
- Gate minimum: n_gated≥15, coverage≥30% threshold not enforced (CVD tested at 19%).
- Half-split: fires sorted by `fire_us`, split 50/50, gate evaluated independently in each half.
- Spurious gates flagged in `external_gates.csv` column `spurious=True`.
