# All Results — every test run this session (2026-05-30/31)

_Complete list: WR, profit/trade, trades, period tested, for every backtest/trial. PnL = real 0.07-curve fee, per-$5 stake (sniper sleeves) / Kelly-sized (the two `ALL_*`). Two periods: **LIVE** = production shadow fires (canonical `trading_events`, refreshed to May 30 22:39 UTC); **UNIVERSE** = full-period reconstruction Apr 24 → May 26 (precomputed sniper panels)._

---

## 1. LIVE shadow — all 21 sleeves (production fires)

Period per sleeve = first→last live fire. $/tr = mean PnL per trade.

| sleeve | period | trades | WR% | $/tr | total $ |
|---|---|--:|--:|--:|--:|
| ALL_5m_S3_prewindow | 05-26→05-30 | 300 | 54.3 | +1.078 | +323.4 |
| ALL_5m_phase1_kelly | 05-26→05-30 | 858 | 51.7 | +0.291 | +249.5 |
| sol_5m_rf_tr_partial_mid | 05-27→05-30 | 371 | 69.5 | +0.250 | +92.7 |
| eth_5m_l_ema50_hurst_grandparent_v8 | 05-27→05-30 | 78 | 73.1 | +0.922 | +71.9 |
| btc_15m_ema50_ema800_off600_down | 05-27→05-30 | 61 | 80.3 | +0.862 | +52.6 |
| eth_5m_bb_mp_hurst_band_v6 | 05-27→05-30 | 107 | 72.9 | +0.470 | +50.3 |
| eth_5m_bb_mp_hurst_band_v6_vL | 05-27→05-30 | 122 | 71.3 | +0.373 | +45.5 |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 05-27→05-30 | 60 | 76.7 | +0.542 | +32.5 |
| eth_5m_cloud_vwap_hurstmp_v7 | 05-27→05-30 | 93 | 71.0 | +0.342 | +31.8 |
| eth_5m_cloud_ribbon_mp_hurst_v6 | 05-27→05-30 | 84 | 72.6 | +0.165 | +13.8 |
| btc_5m_up_a2_hlcascade50k_v9 | 05-29→05-30 | 8 | 50.0 | +1.631 | +13.1 |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 05-27→05-30 | 233 | 73.8 | +0.057 | +13.3 |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 05-27→05-30 | 222 | 65.8 | +0.053 | +11.7 |
| eth_5m_v5repl_off120_v6 | 05-27→05-30 | 17 | 88.2 | +0.613 | +10.4 |
| eth_5m_tr200_mp_sms_active_off120 (≡ above) | 05-27→05-30 | 17 | 88.2 | +0.613 | +10.4 |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | 05-27→05-30 | 176 | 76.7 | +0.029 | +5.1 |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | 05-27→05-30 | 46 | 89.1 | +0.070 | +3.2 |
| sol_5m_f7_mfi_ema200_vwap_v6 | 05-27→05-30 | 418 | 68.7 | +0.000 | +0.1 |
| btc_5m_ts_mpskew_any_off30 | 05-29→05-30 | 120 | 54.2 | −0.772 | −92.6 |
| btc_5m_l_1hrf_imb5_ribbon_v8 | 05-29→05-30 | 506 | 74.5 | −0.275 | −139.3 |
| btc_5m_q_parent15mslope_ts_imb5_v8 | 05-27→05-30 | 1232 | 66.6 | −0.755 | −930.5 |

---

## 2. GATED — best walk-forward gate stack applied (LIVE window)

Gated = retro-applied on the live fires; CI-lo = bootstrap 2.5% of Δmean.

| sleeve | gate stack | trades | WR% | $/tr | total $ | CI-lo |
|---|---|--:|--:|--:|--:|--:|
| ALL_5m_phase1_kelly | keep_EU | 256 | 57.4 | +8.874 | +2271.8 | −0.37 |
| ALL_5m_S3_prewindow | drop_US | 178 | 57.3 | +2.553 | +454.5 | −1.03 |
| sol_5m_rf_tr_partial_mid | drop_US | 224 | 73.7 | +0.743 | +166.5 | **+0.16** |
| sol_5m_f7_mfi_ema200_vwap_v6 | evcap≤0.75 + dir_UP | 152 | 75.0 | +0.580 | +88.0 | **+0.03** |
| eth_5m_l_ema50_hurst_grandparent_v8 | evcap≤0.70 | 57 | 71.9 | +1.352 | +77.1 | **+0.25** |
| eth_5m_bb_mp_hurst_band_v6_vL | depth≥1000 | 113 | 75.9 | +0.566 | +64.0 | −0.03 |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | evcap≤0.80 + vsum≤1.30 | 80 | — | +0.763 | +61.0 | ~0 |
| eth_5m_bb_mp_hurst_band_v6 | evcap≤0.70 + depth≥1000 | 70 | — | +0.843 | +59.0 | **+0.03** |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | evcap≤0.80 + drop_US | 40 | — | +1.275 | +51.0 | **+0.33** |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | evcap≤0.70 | 139 | — | +0.324 | +45.0 | −0.39 |
| eth_5m_cloud_vwap_hurstmp_v7 | evcap≤0.70 + depth≥1000 | 60 | — | +0.683 | +41.0 | −0.26 |
| eth_5m_cloud_ribbon_mp_hurst_v6 | evcap≤0.70 | 44 | — | +0.841 | +37.0 | −0.21 |
| btc_5m_l_1hrf_imb5_ribbon_v8 (salvage) | cross_spread≤0.22 | 136 | 96.3 | +0.176 | +24.0 | −0.03 |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | vsum≤1.25 | 36 | 97.2 | +0.334 | +12.0 | −0.06 |
| btc_5m_q_parent15mslope_ts_imb5_v8 | vsum≤1.30+depth≥1000+dir_DOWN (best) | 367 | 80.1 | −0.050 | −18.5 | −0.32 |
| btc_5m_ts_mpskew_any_off30 | (no gate generalizes) | 120 | 54.2 | −0.772 | −92.6 | −1.48 |

---

## 3. FULL-PERIOD backtest — UNIVERSE Apr 24 → May 26 (in-sample) vs LIVE OOS

Reconstructed each sleeve's gate stack on the sniper universe panel (0.07-curve PnL). ⚠ Universe = the GA **training set** → in-sample (upper bound). The live column is the true OOS.

| sleeve | period | trades | WR% | $/tr | total $ | CI-lo | live WR% | live $ |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| eth_cloud_ribbon_v6 | Apr24-May26 | 481 | 81.7 | +0.877 | +422.0 | +0.58 | 72.6 | +14 |
| eth_l_ema50_grandparent_v8 | Apr24-May26 | 467 | 82.0 | +0.925 | +432.0 | + | 73.1 | +72 |
| eth_bb_mp_hurst_v6 | Apr24-May26 | 162 | 74.1 | +1.921 | +311.2 | +1.26 | 72.9 | +50 |
| eth_cloud_vwap_v7 | Apr24-May26 | 163 | 72.4 | +1.778 | +289.9 | +1.02 | 71.0 | +32 |
| btc_l_1hrf_imb5_ribbon_v8 | Apr24-May26 | 1150 | 74.3 | +0.520 | +597.6 | +0.19 | 74.5 | −139 |
| btc_q_parent15m_imb5_v8 (KILL) | Apr24-May26 | 605 | 51.1 | −0.614 | −371.6 | −1.18 | 66.6 | −930 |
| btc_ts_mpskew_off30 (KILL) | Apr24-May26 | 1519 | 51.0 | −0.560 | −850.4 | −0.81 | 54.2 | −93 |
| btc_parent15m_notrang_v7 † | Apr24-May26 | 4926 | 50.6 | −0.654 | −3215 | − | 76.7 | +5 |

† reconstruction broken (missing `parent_15m_not_ranging` gate → 28× over-fire). Unreliable; ignore.

**Read:** ETH 5m WR persists (in-sample 72-82% ≈ live 71-73%). The 2 KILLs are 51% WR (dead) across the full period. btc_l_1hrf WR persists (74%) but $ flips (entry too rich live).

---

## 4. GATE persistence — OOS test on the universe period (my gates were fit on live)

Lift = gated mean − base mean ($/tr), measured on Apr 24-May 26 (period the gate was NOT fit on).

| gate | eth_cloud_ribbon | eth_bb | eth_cloud_vwap | eth_l_ema50 | btc_l_1hrf | btc_q | btc_ts | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|---|
| **entry_vwap≤0.70** | +0.696 | +0.000¹ | +0.000¹ | +0.546 | +0.807 | −0.437 | −0.149 | ✅ **persists** (ETH+l_1hrf) |
| drop_US (hr∉14-21) | −0.103 | −0.100 | −0.188 | −0.024 | +0.487 | −0.490 | −0.068 | ❌ fails on ETH |
| vsum≤1.30 | −0.320 | −0.828 | −0.929 | −0.233 | — | — | — | ❌ fails (hurts) |

¹ no-op (sleeve's own vwap-band gate already caps price). Lifts on the 2 KILLs are irrelevant (sleeves dead).

---

## 5. EXIT / HEDGE — full grid (BTC, fresh L25, real 1-5min hold, 10-seed bootstrap + walk-forward)

Δ = policy − HOLD per trade. "Robust" = Δ>0 AND CI-lo>0 AND both walk-forward halves +.

**Fixed exits (pooled BTC, all negative — none beat HOLD):**

| policy | Δ$/tr | beats HOLD? |
|---|--:|:--:|
| Stop-loss 0.25–0.50 | −0.07 to −0.10 | ❌ |
| Take-profit 0.85–0.97 | −0.02 to +0.004 | ❌ |
| Trailing 0.10–0.20 | −0.04 to −0.07 | ❌ |
| Oracle-reversal cut/lock | ~0 (loser-only) | ❌ |

**HEDGE_LATE (final-30s cut if bid < frac×entry) — robust on MARGINAL sleeves only:**

| sleeve | period | trades | base total | best (frac/late) | Δ total $ | Δ$/tr | CI-lo | beats? |
|---|---|--:|--:|---|--:|--:|--:|:--:|
| btc_5m_parent15m_notrang_v7 | live | 176 | +5.1 | 0.55 / 45s | **+45.2** | +0.257 | **+0.15** | ✅ |
| btc_15m_vwapprem_v6 | live | 46 | +3.2 | 0.75 / 30s | +6.5 | +0.141 | +0.003 | ✅ |
| btc_15m_ema50_ema800_off600_down | live | 61 | +52.6 | — | −12 to −22 | neg | — | ❌ hurts winner |
| btc_5m_l_1hrf / q / ts | live | — | — | — | nominal + | — | <0 | ❌ artifact |

---

## 6. EXTERNAL-feature gates — binance momentum / chainlink basis / HL liq / Poly CVD (both-half holdout)

Only one genuine result across 17 sleeves:

| sleeve | gate | trades | gated $/tr | lift $/tr | both halves + |
|---|---|--:|--:|--:|:--:|
| sol_5m_rf_tr_partial_mid | binance ma_30 | 80 | +0.974 | +0.724 | ✅ |
| sol_5m_rf_tr_partial_mid | binance ma_60 | 102 | +1.125 | +0.876 | ✅ |
| sol_5m_rf_tr_partial_mid | binance ma_120 | 99 | +1.859 | +1.61 | ✅ |
| sol_5m_rf_tr_partial_mid | **binance ma_300** | 141 | +2.02 | +2.02 | ✅ (recommended) |

Chainlink basis = spurious (stale ETH CL feed); HL liq = dead (feed ends May 27); CVD = too sparse. Other 16 sleeves: no external gate generalizes.

---

## Coverage / caveats
- **SOL sleeves** (rf, cci, f7_mfi, btcf7, j): no full-period universe panel exists (SOL L25 too sparse) → §3/§4 untested for SOL; LIVE (§1/§2) + external gate (§6) only.
- **`drop_US` + `vsum`**: fail OOS on ETH (§4) → likely overfit to the 5-day live window. The SOL `drop_US` headline (§2) is **unvalidated OOS** — treat as provisional.
- **`entry_vwap≤0.70`** is the only gate that persists OOS. The 2 KILLs are confirmed dead full-period.
- Live window is short (3-5 days/sleeve); universe ends May 26 (sleeves' training data).

Source CSVs: `_opt_2026_05_30/_results/{fires_resolved_all, final_gated_configs, fullperiod_base, fullperiod_gate_persist, hedge_late_sweep, exit_hedge_grid, external_gates}.*`. Reports: `SLEEVE_OPTIMIZATION`, `MASTER_FINDINGS_TABLE`, `HEDGE_EXIT_RESEARCH_SYNTHESIS`, `FULLPERIOD_PERSISTENCE`, `BEFORE_AFTER_TOP10` (all _2026_05_30/31).
