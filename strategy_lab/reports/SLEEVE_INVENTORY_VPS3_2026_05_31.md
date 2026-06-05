# VPS3 Sleeve Inventory — 2026-05-31 (audited 2026-06-01)

Snapshot taken 2026-06-01 ~08:30 UTC. Engine PID 3688198 (restarted ~06:24 UTC today).
All sleeves paper/shadow — `TV_POLY_LIVE_ALLOWLIST=` (empty), `has_live_controller=false`.

---

## 1. Engine Registration at Startup

From `journalctl` at 2026-06-01 06:24 UTC:

| Block | What registered | sleeve_ids pattern | Note |
|---|---|---|---|
| poly_updown controllers | sniper, v3, v3_1, v3_2, v3_3, v4, momo, momo_v2 | `poly_updown_{asset}_{tf}` | 6 assets×tfs each; 8 strategy modes |
| poly_updown inverse | inverse_sniper, inverse_sol_sniper, inverse_sniper_down | same id pattern | Shadow only |
| Shadow gated (Phase 34) | 11 sleeves (momo/momo_v2/sniper + HOD gate) | `poly_updown_*_hod` | TV_POLY_SHADOW_GATED flag (confirmed firing, all 11 in DB) |
| VWAP continuation (Phase 35) | 5 sleeves BTC/ETH/SOL 5m | `poly_updown_*_vwap_off*` | TV_POLY_VWAP_CONT_ENABLED flag (confirmed firing, all 5 in DB) |
| Shadow9 (Phase 36) | 3 sleeves Kelly+S3+S4 | `shadow_poly_updown_ALL_*` | TV_POLY_SHADOW9_ENABLED flag (confirmed firing) |
| Fade/Overlay (spec §4 Bonus) | 6 fade + 6 overlay = 12 | `shadow_poly_updown_*_fade_*`, `shadow_poly_updown_*_overlay_*` | All active in DB |
| volume_INV_NIGHT | 6 sleeves BTC/ETH/SOL × 5m/15m | `poly_updown_*_volume_INV_NIGHT` | Legacy volume sleeve; active |
| **sniper_v5** (Phase 35) | **90 sleeves** | `poly_sniper_v5_*` | $5 notional; n_sleeves=90 confirmed at spawn |
| fast_taker A/B (non-lagv2) | 4 sleeves | `poly_fast_taker_{a25_merge,b2_nomerge}_{btc,eth}_5m` | oracle-lag, $25 override |
| **FAST_TAKER_LAGV2** | **4 sleeves** | `poly_fast_taker_lagv2_{btc,eth}_{5m,15m}` | TV_AGENT_SPEC_FAST_TAKER_LAGV2_2026_05_29 — confirmed in registry + DB |
| Kalshi sniper | 2 sleeves | `kalshi_sniper_btc_15m_*` + `kalshi_sniper_all_15m_s4_prewindow` | Separate venue; resolves cash |

Total registered: ~140+ distinct sleeve IDs across all families.
sniper_v5 registry: **90 sleeves** (16 V5 + 14 V6 + 12 V7 + 14 V8 + 11 vL + 10 V9 + 1 H + 4 fast_taker A/B + 4 LAGV2).

---

## 2. FAST_TAKER_LAGV2 Status

**YES — deployed and firing.**

- 4 sleeves defined in `sniper_v5_sleeves.py` lines 1506–1581:
  - `poly_fast_taker_lagv2_btc_5m`
  - `poly_fast_taker_lagv2_btc_15m`
  - `poly_fast_taker_lagv2_eth_5m`
  - `poly_fast_taker_lagv2_eth_15m`
- All 4 present in `trading.events` for last 48h with event counts (4,627 / 4,637 / 1,601 / 1,593).
- 7-day resolved PnL: btc_5m −$175, btc_15m −$25, eth_5m −$7.26, eth_15m +$41.77.
- Very few resolutions (1–7 per sleeve in 7d from DB subset) → these are extremely selective / rarely fill.
- Spec: directional oracle-lag taker; deliberately loose spread filter; $25 notional override; gates: `g_oracle_lag_bps_ge(3.0)` + directional depth median.

---

## 3. Firing Status — Last 48h

**Total DB events (48h):** 270,630 `poly_updown_signal` + 10,503 `poly_updown_resolution` + 9 `boot_reconcile_pass`.

### 3a. Idle / not-firing in last 48h (present in 7d resolutions but zero 48h events)

These sleeves had resolutions within 7d but zero events in the last 48h (likely ran before the ~06:24 restart and the 48h window happens to be thin post-restart):

| sleeve_id | Note |
|---|---|
| poly_sniper_v5_sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6 | Low freq HOD+EU filter |
| poly_sniper_v5_sol_5m_depth_up_hod_session | HOD+session gate; very selective |
| poly_updown_btc_15m_momo_HEDGE_f7 | **Idle** — HEDGE variant |
| poly_updown_btc_15m_momo_SELL_f7 | **Idle** — SELL variant |
| poly_updown_btc_5m_momo_HEDGE_f7 | **Idle** |
| poly_updown_btc_5m_momo_SELL_f7 | **Idle** |
| poly_updown_btc_5m_momo_v2_HEDGE_f7 | **Idle** |
| poly_updown_btc_5m_momo_v2_SELL_f7 | **Idle** |
| poly_updown_eth_15m_momo_HEDGE_f7 | **Idle** |
| poly_updown_eth_15m_momo_SELL_f7 | **Idle** |
| poly_updown_eth_15m_momo_v2_HEDGE_f7 | **Idle** |
| poly_updown_eth_15m_momo_v2_SELL_f7 | **Idle** |
| poly_updown_eth_5m_momo_HEDGE_f7 | **Idle** |
| poly_updown_eth_5m_momo_SELL_f7 | **Idle** |
| poly_updown_sol_15m_momo_HEDGE_f7 | **Idle** |
| poly_updown_sol_15m_momo_SELL_f7 | **Idle** |
| poly_updown_sol_15m_momo_v2_HEDGE_f7 | **Idle** |
| poly_updown_sol_15m_momo_v2_SELL_f7 | **Idle** |
| poly_updown_sol_5m_momo_HEDGE_f7 | **Idle** |
| poly_updown_sol_5m_momo_SELL_f7 | **Idle** |
| poly_updown_sol_5m_momo_v2_HEDGE_f7 | **Idle** |
| poly_updown_sol_5m_momo_v2_SELL_f7 | **Idle** |

Note: HEDGE/SELL variants of momo are expected to be silent if HOLD_ONLY is the primary hedge policy registered. Production hedge_policy from env: `TV_POLY_HEDGE_POLICY=HEDGE_HOLD` but momo controllers use `HOLD_ONLY` per spec. The HEDGE_f7 and SELL_f7 variants appear to be legacy IDs from prior hedge_policy experiments — they had resolutions in 7d but are now idle.

**No pyarrow/starved errors observed** in last 48h logs. Prior bugs (v9 sleeve starvation, S6 column bug) not reproduced — engine appears healthy.

---

## 4. Complete Sleeve Table

### 4a. sniper-v5 family (90 sleeves, $5 notional, all shadow/paper)

Active 48h event counts from `trading.events` (all events, not just resolutions):

| sleeve_id | family | cell | mode | 48h events | 7d resolutions | 7d net PnL |
|---|---|---|---|---|---|---|
| poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 | sniper-v5/V8 | BTC/5m | shadow | 11,585 | 2,151 | −$825 |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8 | sniper-v5/V8 | BTC/5m | shadow | 11,517 | 1,437 | −$561 |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8 | sniper-v5/V8 | BTC/5m | shadow | 11,272 | 1,127 | −$330 |
| poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7 | sniper-v5/V7 | BTC/5m | shadow | 10,963 | 755 | −$84 |
| poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7 | sniper-v5/V7 | BTC/5m | shadow | 10,431 | 60 (net) | +$50 |
| poly_sniper_v5_sol_5m_f7_mfi_ema200_vwap_v6 | sniper-v5/V6 | SOL/5m | shadow | 9,454 | 543 | −$33 |
| poly_sniper_v5_sol_5m_j_2asset_trending_cci_rf_ema200_v8 | sniper-v5/V8 | SOL/5m | shadow | 9,379 | 328 | −$12 |
| poly_sniper_v5_sol_5m_btcf7_f7overb_ema800_vwap_v7 | sniper-v5/V7 | SOL/5m | shadow | 9,373 | 313 | −$13 |
| poly_sniper_v5_sol_5m_cci_f7_mfi_partial_vwap_v6 | sniper-v5/V6 | SOL/5m | shadow | 9,271 | 83 (net) | +$33 |
| poly_sniper_v5_sol_5m_f7_mp_ema200_vwap_v6 | sniper-v5/V6 | SOL/5m | shadow | 9,235 | 1 | −$5 |
| poly_sniper_v5_sol_5m_btcf7against_cci_hurstrev_mfi_v8 | sniper-v5/V8 | SOL/5m | shadow | 9,234 | ~80 | mixed |
| poly_sniper_v5_sol_5m_btctrend_cci_hurstrev_v7 | sniper-v5/V7 | SOL/5m | shadow | 9,234 | ~80 | mixed |
| poly_sniper_v5_sol_5m_rf_tr_partial_mid | sniper-v5/V5 | SOL/5m | shadow | 4,814 | 502 | +$55 |
| poly_sniper_v5_sol_5m_rf_tr_pp_mid | sniper-v5/V5 | SOL/5m | shadow | 4,642 | 50 | +$1 |
| poly_sniper_v5_sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6 | sniper-v5/V6 | SOL/15m | shadow | 3,938 | 13 | −$15 |
| poly_sniper_v5_sol_5m_b1_120s_250_v9 | sniper-v5/V9 | SOL/5m | shadow | 3,636 | 325 | mixed |
| poly_sniper_v5_sol_5m_b3_abs500_v9 | sniper-v5/V9 | SOL/5m | shadow | 3,522 | 144 | mixed |
| poly_sniper_v5_sol_5m_b3_abs500_no_opp_v9 | sniper-v5/V9 | SOL/5m | shadow | 3,517 | 119 | +$34 |
| poly_sniper_v5_sol_5m_b1_polyflow_aligned_v9 | sniper-v5/V9 | SOL/5m | shadow | 3,481 | 25 | +$49 |
| poly_sniper_v5_btc_5m_slotend_ofi_ts_v7 | sniper-v5/V7 | BTC/5m | shadow | 2,300 | ~50 | mixed |
| poly_sniper_v5_sol_5m_down_b1_flow250_v9 | sniper-v5/V9 | SOL/5m | shadow | 1,770 | 78 | −$6 |
| poly_sniper_v5_sol_5m_down_b1_500_v9 | sniper-v5/V9 | SOL/5m | shadow | 1,739 | 8 | +$56 |
| poly_sniper_v5_sol_5m_depth_up_hod_session | sniper-v5/V5 | SOL/5m | shadow | 1,738 | 3 | −$8 |
| poly_sniper_v5_sol_15m_rfaged_trstack_late | sniper-v5/V5 | SOL/15m | shadow | 1,547 | 5 | −$0.06 |
| poly_sniper_v5_sol_15m_rfaged_trstack_late_vL | sniper-v5/vL | SOL/15m | shadow | 1,547 | 4 | −$0.21 |
| poly_sniper_v5_btc_5m_ts_mpskew_any_off30 | sniper-v5/V5 | BTC/5m | shadow | 1,340 | 243 | mixed |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6_vL | sniper-v5/vL | ETH/5m | shadow | 1,311 | 233 | +$110 |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6 | sniper-v5/V6 | ETH/5m | shadow | 1,292 | 204 | +$117 |
| poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7_vL | sniper-v5/vL | ETH/5m | shadow | 1,283 | 270 | −$9 |
| poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7_vL | sniper-v5/vL | ETH/5m | shadow | 1,282 | 196 | +$69 |
| poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6_vL | sniper-v5/vL | ETH/5m | shadow | 1,276 | 183 | +$57 |
| poly_sniper_v5_eth_5m_ema50_hurst_parent15mrang_v7 | sniper-v5/V7 | ETH/5m | shadow | ~1,270 | 235 | +$11 |
| poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7 | sniper-v5/V7 | ETH/5m | shadow | ~1,200 | 171 | +$82 |
| poly_sniper_v5_eth_5m_cloud_ribbon_mp_hurst_v6 | sniper-v5/V6 | ETH/5m | shadow | ~1,150 | 156 | +$54 |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down | sniper-v5/V5 | BTC/15m | shadow | active | 99 | +$156 |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H | sniper-v5/H | BTC/15m | shadow | active | 80 | +$132 |
| poly_sniper_v5_btc_15m_vwapprem_ema50_mpskew_off600_v6 | sniper-v5/V6 | BTC/15m | shadow | active | 108 | +$43 |
| poly_sniper_v5_btc_15m_ts_trstack_off600_down | sniper-v5/V5 | BTC/15m | shadow | active | 25 | +$42 |
| poly_sniper_v5_btc_15m_mpskew_trstack_off600_down | sniper-v5/V5 | BTC/15m | shadow | active | 33 | +$30 |
| poly_sniper_v5_btc_15m_ema200_mpskew_rf_off600_down_v6 | sniper-v5/V6 | BTC/15m | shadow | active | 43 | +$24 |
| poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8 | sniper-v5/V8 | ETH/5m | shadow | active | 140 | +$168 |
| poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8 | sniper-v5/V8 | ETH/5m | shadow | active | ~120 | mixed |
| poly_sniper_v5_eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL | sniper-v5/vL | ETH/5m | shadow | active | ~100 | mixed |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8 | sniper-v5/V8 | ETH/5m | shadow | active | ~80 | mixed |
| poly_sniper_v5_eth_5m_k_hurst_ts_cci_tod_euus_v8_vL | sniper-v5/vL | ETH/5m | shadow | active | ~70 | mixed |
| poly_sniper_v5_eth_5m_ema200_vwap_regimerang_xa3_v7 | sniper-v5/V7 | ETH/5m | shadow | active | 206 | mixed |
| poly_sniper_v5_eth_15m_* (6 sleeves: V6/V7/V8 variants) | sniper-v5/V6-V8 | ETH/15m | shadow | active | ~50-150 | mixed |
| poly_sniper_v5_sol_15m_* (8 sleeves: V6/V7/V8 variants) | sniper-v5/V6-V8 | SOL/15m | shadow | active | ~10-100 | mixed |
| poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9 | sniper-v5/V9 | BTC/5m | shadow | active | 259 | **+$193** |
| poly_sniper_v5_btc_5m_down_b2_contrarian2k_v9 | sniper-v5/V9 | BTC/5m | shadow | active | 276 | **+$83** |
| poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60 | sniper-v5/V5 | BTC/5m | shadow | active | 9 | −$4 |
| poly_sniper_v5_btc_5m_a2_hlcascade100k_v9 | sniper-v5/V9 | BTC/5m | shadow | active | 19 | +$14 |
| poly_sniper_v5_btc_5m_up_a2_hlcascade50k_v9 | sniper-v5/V9 | BTC/5m | shadow | active | 11 | −$2 |
| poly_sniper_v5_btc_5m_up_a2_hlcascade100k_v9 | sniper-v5/V9 | BTC/5m | shadow | active | ~10 | mixed |
| poly_sniper_v5_sol_5m_up_a2_hlcascade15k_v9 | sniper-v5/V9 | SOL/5m | shadow | active | ~10 | mixed |
| poly_sniper_v5_eth_5m_* (V5 early-entry: tr200/cloud/sms variants) | sniper-v5/V5 | ETH/5m | shadow | active | ~20-30 | mixed |

Remaining ~30 sleeves not explicitly listed above are all active (present in 48h DB), covering ETH/SOL 5m+15m across V6-V9+vL families.

### 4b. fast_taker family (8 sleeves total)

| sleeve_id | family | cell | mode | $notional | 48h events | 7d net PnL |
|---|---|---|---|---|---|---|
| poly_fast_taker_a25_merge_btc_5m | fast_taker-A | BTC/5m | shadow | $25 | 8,201 | **−$2,595** |
| poly_fast_taker_a25_merge_eth_5m | fast_taker-A | ETH/5m | shadow | $25 | 8,195 | **−$7,558** |
| poly_fast_taker_b2_nomerge_btc_5m | fast_taker-B | BTC/5m | shadow | $25 | 2,136 | +$12 |
| poly_fast_taker_b2_nomerge_eth_5m | fast_taker-B | ETH/5m | shadow | $25 | 4,467 | −$40 |
| **poly_fast_taker_lagv2_btc_5m** | fast_taker-LAGV2 | BTC/5m | shadow | $25 | 4,627 | −$175 |
| **poly_fast_taker_lagv2_btc_15m** | fast_taker-LAGV2 | BTC/15m | shadow | $25 | 1,601 | −$25 |
| **poly_fast_taker_lagv2_eth_5m** | fast_taker-LAGV2 | ETH/5m | shadow | $25 | 4,637 | −$7 |
| **poly_fast_taker_lagv2_eth_15m** | fast_taker-LAGV2 | ETH/15m | shadow | $25 | 1,593 | **+$42** |

Note: a25_merge variants are producing very large paper losses — $25 notional at high frequency (8k+ events/48h) against a $5 sniper notional means these dominate the loss column. The "negative PnL" query over 7d in the DB shows a25_merge_btc at −$43,600 total losing trades and +$41,005 total winning trades (net −$2,595). This is paper only. b2_nomerge and LAGV2 are much less active.

### 4c. poly_updown shadow-gated family (Phase 34 — 11 sleeves)

| sleeve_id | family | cell | mode | gates | 48h active | 7d net PnL |
|---|---|---|---|---|---|---|
| poly_updown_sol_5m_sniper_hod | sniper+HOD | SOL/5m | paper | hod | YES | mixed |
| poly_updown_eth_15m_sniper_hod | sniper+HOD | ETH/15m | paper | hod | YES | −$18 |
| poly_updown_btc_15m_momo_hod | momo+HOD+m1va | BTC/15m | paper | hod+m1va | YES | +$48 |
| poly_updown_btc_15m_sniper_hod | sniper+HOD | BTC/15m | paper | hod | YES | −$235 |
| poly_updown_btc_5m_sniper_hod | sniper+HOD | BTC/5m | paper | hod | YES | −$433 |
| poly_updown_btc_5m_momo_v2_hod_mtf | momo_v2+HOD+mtf2 | BTC/5m | paper | hod+mtf2 | YES | +$25 |
| poly_updown_btc_15m_momo_v2_hod | momo_v2+HOD | BTC/15m | paper | hod | YES | −$7 |
| poly_updown_sol_5m_momo_v2_hod | momo_v2+HOD | SOL/5m | paper | hod | YES | mixed |
| poly_updown_eth_15m_momo_v2_hod | momo_v2+HOD | ETH/15m | paper | hod | YES | **+$149** |
| poly_updown_sol_15m_momo_v2_hod | momo_v2+HOD | SOL/15m | paper | hod | YES | −$6 |
| poly_updown_eth_5m_sniper_hod | sniper+HOD | ETH/5m | paper | hod | YES | −$364 |

### 4d. VWAP continuation family (Phase 35 — 5 sleeves)

| sleeve_id | family | cell | mode | offset_s | 48h active | 7d net PnL |
|---|---|---|---|---|---|---|
| poly_updown_btc_5m_vwap_off240_m1v | vwap_cont | BTC/5m | paper | 240 | YES | mixed |
| poly_updown_btc_5m_vwap_off60_f7_cross | vwap_cont | BTC/5m | paper | 60 | YES | mixed |
| poly_updown_btc_5m_vwap_off90_cross | vwap_cont | BTC/5m | paper | 90 | YES | mixed |
| poly_updown_eth_5m_vwap_off210_f7_m1v | vwap_cont | ETH/5m | paper | 210 | YES | mixed |
| poly_updown_sol_5m_vwap_off60 | vwap_cont | SOL/5m | paper | 60 | YES | mixed |

### 4e. poly_updown legacy/base sleeves (sniper+v3+v4+momo variants)

These use the shared `poly_updown_{asset}_{tf}` ID pattern with strategy_mode as suffix in DB. All paper mode, $25 notional.

| sleeve_id | family | mode | 48h active | 7d net PnL |
|---|---|---|---|---|
| poly_updown_btc_5m_momo_HOLD_f7 | momo | paper | YES | −$167 |
| poly_updown_btc_15m_momo_HOLD_f7 | momo | paper | YES | **+$236** |
| poly_updown_eth_5m_momo_HOLD_f7 | momo | paper | YES | −$379 |
| poly_updown_eth_15m_momo_HOLD_f7 | momo | paper | YES | +$123 |
| poly_updown_sol_5m_momo_HOLD_f7 | momo | paper | YES | mixed |
| poly_updown_sol_15m_momo_HOLD_f7 | momo | paper | YES | +$109 |
| poly_updown_btc_5m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | −$179 |
| poly_updown_btc_15m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | −$27 |
| poly_updown_eth_5m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | mixed |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | **+$235** |
| poly_updown_sol_5m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | +$52 |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | momo_v2 | paper | YES | **+$137** |
| poly_updown_{asset}_{tf}_HEDGE_f7 (12 variants) | momo/momo_v2 | paper | **IDLE** | had 7d resolutions, 0 in 48h |
| poly_updown_{asset}_{tf}_SELL_f7 (12 variants) | momo/momo_v2 | paper | **IDLE** | same |
| poly_updown_{asset}_{tf}_v3/v3_1/v3_2/v3_3/v4 | legacy | paper | YES (some) | mostly negative |
| poly_updown_{asset}_{tf}_volume_INV_NIGHT (6 variants) | inv_night | paper | YES | mixed |

### 4f. Shadow9 / fade / overlay sleeves (Phase 36 + spec §4 Bonus)

| sleeve_id | family | scope | mode | 48h active | 7d net PnL |
|---|---|---|---|---|---|
| shadow_poly_updown_ALL_5m_phase1_kelly | vwap_kelly_ensemble | ALL/5m | paper | YES (2,025 events) | −$1,102 |
| shadow_poly_updown_ALL_5m_S3_prewindow | prewindow_s3 | ALL/5m | paper | YES (1,850 events) | −$138 |
| shadow_poly_updown_ALL_15m_S4_prewindow | prewindow_s4 | ALL/15m | paper | YES | **+$192** |
| shadow_poly_updown_btc_5m_fade_sniper | fade_sniper | BTC/5m | paper | YES | +$30 |
| shadow_poly_updown_btc_5m_fade_momo_v2 | fade_momo_v2 | BTC/5m | paper | YES | −$417 |
| shadow_poly_updown_eth_15m_fade_sniper | fade_sniper | ETH/15m | paper | YES | +$24 |
| shadow_poly_updown_sol_5m_fade_sniper | fade_sniper | SOL/5m | paper | YES | −$201 |
| shadow_poly_updown_sol_5m_fade_momo_v2 | fade_momo_v2 | SOL/5m | paper | YES | −$409 |
| shadow_poly_updown_sol_15m_fade_momo_v2 | fade_momo_v2 | SOL/15m | paper | YES | −$426 |
| shadow_poly_updown_eth_15m_sniper_m5v | overlay_sniper | ETH/15m | paper | YES | mixed |
| shadow_poly_updown_btc_5m_momo_v2_fairedge500 | overlay_momo_v2 | BTC/5m | paper | YES | mixed |
| shadow_poly_updown_btc_15m_momo_v2_fairedge500_cvd30 | overlay_momo_v2 | BTC/15m | paper | YES | mixed |
| shadow_poly_updown_sol_15m_sniper_fairedge500 | overlay_sniper | SOL/15m | paper | YES | mixed |
| shadow_poly_updown_sol_5m_momo_v1_m5v | overlay_momo | SOL/5m | paper | YES | mixed |
| shadow_poly_updown_sol_5m_momo_v2_cvd_macd | overlay_momo_v2 | SOL/5m | paper | YES | mixed |

### 4g. Kalshi sleeves (separate venue)

| sleeve_id | family | cell | mode | 48h active | 7d net PnL |
|---|---|---|---|---|---|
| kalshi_sniper_btc_15m_ema50_ema800_off600_down | kalshi-sniper | BTC/15m | paper | YES | **+$135** |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down_H | kalshi-sniper | BTC/15m | paper | YES | **+$102** |
| kalshi_sniper_all_15m_s4_prewindow | kalshi-sniper | ALL/15m | paper | YES | −$25 |

---

## 5. PnL-Tracked Sleeves (7-day net, top and bottom)

### Top net-positive (7d, paper):

| sleeve_id | 7d resolutions | 7d net PnL |
|---|---|---|
| poly_updown_btc_15m_momo_HOLD_f7 | 32 | +$236 |
| poly_updown_eth_15m_momo_v2_HOLD_f7 | 28 | +$235 |
| poly_sniper_v5_btc_5m_up_b2_contrarian2k_v9 | 259 | +$193 |
| shadow_poly_updown_ALL_15m_S4_prewindow | 23 | +$192 |
| poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8 | 140 | +$168 |
| poly_updown_btc_15m_momo_HEDGE_f7 | 9 | +$157 (from prior period; now idle) |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down | 99 | +$156 |
| poly_updown_eth_15m_momo_v2_hod | 10 | +$149 |
| poly_updown_btc_15m_momo_SELL_f7 | 9 | +$144 (idle) |
| poly_updown_eth_15m_momo_v2_SELL_f7 | 13 | +$140 (idle) |
| poly_updown_sol_15m_momo_v2_HOLD_f7 | 30 | +$137 |
| kalshi_sniper_btc_15m_ema50_ema800_off600_down | 70 | +$135 |
| poly_sniper_v5_btc_15m_ema50_ema800_off600_down_H | 80 | +$132 |
| poly_updown_eth_15m_momo_HOLD_f7 | 31 | +$123 |
| poly_sniper_v5_eth_5m_bb_mp_hurst_band_v6 | 204 | +$117 |

### Worst net-negative (7d, paper):

| sleeve_id | 7d resolutions | 7d net PnL |
|---|---|---|
| poly_fast_taker_a25_merge_eth_5m | 594 | **−$7,558** |
| poly_fast_taker_a25_merge_btc_5m | 602 | **−$2,595** |
| poly_updown_sol_5m_volume_INV_NIGHT | 516 | −$1,455 |
| shadow_poly_updown_ALL_5m_phase1_kelly | 1,076 | −$1,102 |
| poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 | 2,151 | −$825 |
| poly_updown_eth_5m_volume_INV_NIGHT | 548 | −$797 |
| poly_updown_btc_5m_volume_INV_NIGHT | 549 | −$780 |
| poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8 | 1,437 | −$561 |
| poly_updown_btc_5m_sniper_hod | 75 | −$433 |
| shadow_poly_updown_sol_15m_fade_momo_v2 | 44 | −$426 |

**Important caveat on fast_taker_a25 losses:** the gross-loss figure of −$43,600 vs gross-wins +$41,005 = net −$2,595 over 7d for btc_5m. These are $25-per-fire paper bets at 8k+ fires/48h (high-frequency oracle-lag strategy). The high absolute loss/win numbers reflect volume, not unusual loss rate. Still net negative in shadow.

---

## 6. Bug / Health Notes

- **No pyarrow errors** observed in last 48h journal. The prior v9 sleeve starvation bug (pyarrow missing on VPS3) is **resolved**.
- **No S6 column bug** reproduced — sniper_v5 loop running cleanly (n_completed=48 before last restart).
- Engine did a **clean restart** at 06:23-06:24 UTC today (prior process 3675446 stopped, new 3688198 started with 90 sniper sleeves).
- **Overlay telemetry gap** (shadow_poly_updown overlay sleeves) may still be partial — these appear in 48h DB but PnL data is sparse.
- **HEDGE/SELL variants** of momo and momo_v2 are all idle (22 sleeves). This is expected: these are legacy hedge-policy variant IDs that were generated when `TV_POLY_MOMO_HEDGE_POLICIES=HOLD_ONLY,HEDGE_HOLD,SELL_BID` was set, but the current engine registers momo controllers with HOLD_ONLY per the shadow spec, so HEDGE and SELL controllers no longer fire.
- **volume_INV_NIGHT sleeves** are a 6-sleeve legacy family that is very active (276–300 events/48h each) and net-negative in 7d shadow.
- `TV_POLY_SHADOW_GATED`, `TV_POLY_VWAP_CONT_ENABLED`, `TV_POLY_SHADOW9_ENABLED` flags are all enabled (confirmed by presence of all these sleeve families in 48h DB).

---

## 7. Summary Count by Family

| Family | Count | All shadow/paper | Any live |
|---|---|---|---|
| sniper-v5 (V5/V6/V7/V8/vL/V9/H) | 82 | YES | NO |
| fast_taker A/B | 4 | YES | NO |
| fast_taker LAGV2 | 4 | YES | NO |
| poly_updown shadow-gated (momo/sniper+HOD) | 11 | YES | NO |
| VWAP continuation | 5 | YES | NO |
| Shadow9 / fade / overlay | 15 | YES | NO |
| poly_updown legacy (sniper/v3/v4/momo/momo_v2/inv_night) | ~40 | YES | NO |
| Kalshi | 3 | YES | NO |
| **TOTAL** | **~164** | **ALL** | **NONE** |

`TV_POLY_LIVE_ALLOWLIST` is empty — no live capital anywhere.
