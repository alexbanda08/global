# MASTER — Live Shadow vs Backtest, All 132 Sleeves — 2026-05-29

> ⚠️ **Read `AUDIT_FINAL_CORRECTED_2026_05_29.md` for corrections**: fee 0.07 curve is correct (not a bug); deprecated sleeves (all HEDGE/SELL, INV_NIGHT, volume, some v3/v4) excluded from active roster; V9 live+working on multi-venue liqs. Fidelity + replay findings below remain valid.

Full cross-check of every shadow sleeve on VPS3: implementation fidelity (spec vs live code) + live performance vs canonical backtest. Synthesizes 8 agent reports.

**Live window:** per-family (v3/v4 22d · momo 9d · kelly/fade/prewindow 5d · sniper_v5 hrs–2d). PnL = lifetime per sleeve.
**Canonical data:** Apr 22 → May 29 (L25 BTC to 10:01, ETH/SOL to 13:13; SOL L25 sparse).
**Source reports:** FIDELITY_AUDIT_{V5_V9,V6_V7,V8_H,VL,MOMO_SHADOW}, BACKTEST_REPLAY_{BTC,ETH,SOL}, BACKTEST_VS_LIVE_MOMO.

---

## 0. Executive summary

- **132 active sleeves** across 2 controllers: 78 sniper_v5 (`poly_sniper_v5_*`) + ~54 momo/shadow (`poly_updown_*`, `shadow_poly_*`).
- **Fidelity: 75/78 sniper + 66/69 momo faithful to spec.** 4 active sniper bugs, 1 systemic fee bug across both controllers.
- **Backtest reproduces live where data + signal-infra exist** (BTC/ETH sniper replay |Δvwap|≈0.01; momo corr 0.61, 100% direction-match on shared slugs). SOL sniper unverifiable (sparse L25). Kelly + prewindow unverifiable (need 1s-trade features).
- **No evidence the backtest engine is broken** — divergences trace to (a) genuinely-bad sleeves the backtest also flags, (b) live-only gate bugs, (c) data-coverage gaps. Backtest is trustworthy where it can run.

---

## 1. Bug scorecard (full detail in DEBUG_FINDINGS_ALL_SLEEVES_2026_05_29.md)

| # | Bug | Severity | Affected | Status |
|---|---|---|---|---|
| 1 | Fee split-brain (0.07 curve vs legacy 2%) | HIGH systemic | ALL sleeves (both controllers) | 🔴 ACTIVE |
| 2 | btc_5m_q imb5 — over-optimistic backtest, losing live | HIGH | 1 sleeve | 🔴 KILL |
| 3 | V8_01/V8_02 gate mismatch (grandparent vs 1h_rf) | HIGH | 2 sleeves | 🔴 ACTIVE |
| 4 | vwap80 gate flip (floor 0.55 vs ceiling 0.80) | HIGH | 4 SOL 15m | 🔴 ACTIVE |
| 5 | rv_60 scale (vol_high/vol_contracting) | was HIGH | 3+ sleeves | ✅ FIXED |
| 6 | Synthetic-fill 0.5 placeholder | was HIGH | all sniper | ✅ FIXED |
| 7 | Spread metric cross-token | was HIGH | all sniper | ✅ FIXED |
| 8 | INV_NIGHT dead anti-edge | per-spec | 6 sleeves | 🔴 KILL |
| 9 | HoD top-8 lists stale (refresh never built) | MED | *_hod ×~10 | ⚠ INVESTIGATE |
| 10 | Kelly override not reset / F7 RSI=50 skip / OFI stub | LOW | few | ℹ benign |

---

## 2. MASTER TABLE — sniper_v5 (78 sleeves, $5 stake)

Legend: **L** = live (lifetime), **BT** = canonical replay/backtest. Verdict: MATCH (bt≈live), DIVERGE, NO_DATA (post-cutoff/too-new), SPARSE (SOL L25), KILL.

### BTC sniper (replay sound, |Δvwap|≈0.01)
| Sleeve | L n | L WR | L $/tr | L PnL | BT $/tr | Verdict |
|---|--:|--:|--:|--:|--:|---|
| btc_15m_ema50_ema800_off600_down | 38 | 82% | +0.70 | +$26 | +1.49 | ✅ MATCH (live≈bt, strong) |
| btc_15m_ema50_ema800_off600_down_H | 19 | 89% | +0.65 | +$12 | +0.81 | ✅ MATCH (HEDGE_LATE faithful) |
| btc_5m_q_parent15mslope_ts_imb5_v8 | 520 | 68% | −0.68 | **−$352** | −0.43 | 🔴 KILL (bad in BOTH; backtest was over-optimistic) |
| btc_5m_l_1hrf_imb5_rf_v8 | 20 | 85% | +0.20 | +$4 | — | 🟢 promising, LOW_N |
| btc_5m_l_1hrf_imb5_ribbon_v8 | 19 | 84% | +0.09 | +$2 | — | 🟢 promising, LOW_N |
| btc_15m_ema800_ribslp_hawkes_off840_v6 | 22 | 55% | −2.25 | −$47 | −1.74 | ✅ MATCH (genuinely weak) |
| btc_15m_ts_trstack_off600_down | 3 | 100% | — | +$1 | +0.46 | NO_DATA (n too low) |
| btc_5m_up_b2_contrarian2k_v9 | 30 | 67% | +2.71 | +$81 | — | 🟢 strong early; NO_INFRA bt |
| btc_5m_down_b2_contrarian2k_v9 | 29 | 34% | −1.32 | −$38 | — | 🔴 weak (DOWN contrarian failing live) |
| btc_5m_a2_hlcascade100k_v9 | 6 | 50% | +0.55 | +$3 | — | NO_DATA (sparse HL) |
| btc_5m_up_a2_hlcascade50k_v9 | 3 | 67% | +2.29 | +$7 | — | NO_DATA |
| btc_5m_ts_mpskew_any_off30 | 4 | 50% | −0.97 | −$4 | — | NO_DATA |
| btc_15m_btceth_diverg_stoch_volcontr_v8 | 0 | — | — | — | — | was vol_contracting-blocked (now fixed, fires post-fix) |
| btc 15m {regime,mpskew,vwapprem,ema200} | 0–1 | — | — | ~0 | — | NO_DATA (too new / rare gates) |

### ETH sniper (replay sound, |Δvwap|=0.008, bt_WR≈live_WR)
| Sleeve | L n | L WR | L $/tr | L PnL | BT $/tr | Verdict |
|---|--:|--:|--:|--:|--:|---|
| eth_5m_ema200_vwap_regimerang_xa3_v7 | 97 | 53% | −0.95 | −$92 | −0.85 | ✅ MATCH (genuinely losing) |
| eth_5m_ema50_hurst_parent15mrang_v7 | 62 | 56% | −0.65 | −$40 | −0.45 | ✅ MATCH (losing) |
| eth_5m_ema50_hurst_parent15mrang_v7_vL | 73 | 58% | −0.68 | −$50 | — | ✅ MATCH (vL = parent + 11 slugs, same WR) |
| eth_15m_trstack_vwap_offearly | 38 | 42% | −1.43 | −$54 | ~ | ✅ MATCH (outcome 100%, losing) |
| eth_5m_k_hurst_ts_cci_tod_euus_v8 (+_vL) | 7 | 57% | −1.86 | −$13 | — | LOW_N |
| eth_5m_cloud_vwap_hurstmp_v7 (+_vL) | 5 | 80% | +0.59 | +$3 | — | LOW_N positive |
| eth_5m_bb_mp_hurst_band_v6 (+_vL) | 8 | 75% | +0.56 | +$4 | — | LOW_N positive |
| eth_5m_l_ema50_hurst_grandparent_v8 | 7 | 71% | +0.46 | +$3 | — | LOW_N |
| eth_5m {tr200_mp_sms, v5repl, cloud_ribbon, cloud_mp_sms} | 1–4 | — | mixed | ~0 | — | NO_DATA |
| eth_15m {trstack_vol_offearly(+band+vL), pw, pi, baseline, pj} | 0 | — | — | — | — | NO_DATA (too new) |

### SOL sniper (⚠ SPARSE — canonical L25 55% NaN asks, fills unverifiable; outcomes valid 98-100%)
| Sleeve | L n | L WR | L $/tr | L PnL | Verdict |
|---|--:|--:|--:|--:|---|
| poly_sniper_v5_sol_5m_rf_tr_partial_mid | 231 | 71% | +0.20 | +$47 | 🟢 KEEP (biggest SOL winner; bt unverifiable) |
| sol_5m_f7_mfi_ema200_vwap_v6 | 212 | 69% | +0.005 | +$1 | breakeven |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 128 | 71% | +0.42 | +$54 | 🟢 KEEP |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 124 | 77% | +0.29 | +$36 | 🟢 KEEP (highest SOL WR) |
| sol_5m_b1_120s_250_v9 | 74 | 51% | −0.03 | −$2 | breakeven |
| sol_5m_b3_abs500_v9 | 52 | 50% | +0.38 | +$20 | 🟢 ok |
| sol_5m_b3_abs500_no_opp_v9 | 46 | 54% | +0.94 | +$43 | 🟢 KEEP (anti-B2 overlay works) |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 33 | 76% | +0.58 | +$19 | 🟢 KEEP |
| sol_5m_rf_tr_pp_mid | 22 | 77% | +0.44 | +$10 | 🟢 KEEP |
| sol_5m_down_b1_flow250_v9 | 22 | 41% | −0.39 | −$9 | 🔴 weak |
| sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6 | 9 | 44% | −2.40 | −$22 | 🔴 vwap80 BUG (bug #4) |
| sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6 | 3 | 67% | — | −$3 | vwap80 BUG, LOW_N |
| sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6 | 1 | 0% | — | −$5 | vwap80 BUG, LOW_N |
| sol_5m_b1_polyflow_aligned_v9 | 6 | 83% | +3.75 | +$23 | 🟢 strong early |
| sol_5m_down_b1_500_v9 | 3 | 100% | +7.70 | +$23 | 🟢 strong early, LOW_N |
| sol_5m_depth_up_hod_session | 3 | 33% | −2.74 | −$8 | LOW_N |
| sol_15m_rfaged_trstack_late (+_vL) | 2/1 | 50/0% | neg | −$5/−$5 | LOW_N negative |
| sol_15m {btc_adx_btcvollow, btc_slope_pair, v7*, v6_j} | 0–2 | — | — | ~0 | NO_DATA |

### sniper_v5 NO_DATA (too-new, 1h26m run, 0 fires)
~20 sleeves restarted at last deploy haven't fired yet (btc_5m_ts_mpskew_s6, eth/sol 15m newer V8/V9, etc.). Re-audit after 48h.

---

## 3. MASTER TABLE — momo + shadow (54 sleeves, $25 stake)

### Strong winners (KEEP)
| Sleeve | L n | L WR | L $/tr | L PnL | BT verdict |
|---|--:|--:|--:|--:|---|
| shadow_ALL_5m_phase1_kelly | 666 | 53% | +2.85 | **+$1,900** | NO_INFRA (needs 1s feats) — faithful, Kelly sizing drives it |
| sol_5m_momo_v2_HOLD_f7 | 131 | 60% | +4.33 | +$567 | ✅ MATCH |
| btc_5m_momo_HOLD_f7 | 154 | 54% | +2.14 | +$330 | ✅ MATCH |
| shadow_ALL_5m_S3_prewindow | 235 | 54% | +1.15 | +$271 | NO_INFRA — prewindow edge real |
| btc_15m_momo_HOLD_f7 | 49 | 61% | +5.41 | +$265 | ✅ MATCH (bt +$8.52) |
| eth_15m_momo_v2_HOLD_f7 | 48 | 60% | +4.88 | +$234 | ✅ MATCH (bt +$11.39) |
| shadow_ALL_15m_S4_prewindow | 17 | 76% | +11.7 | +$198 | NO_INFRA |
| sol_5m_momo_HOLD_f7 | 135 | 53% | +1.15 | +$156 | ✅ MATCH |
| eth_15m_momo_v2_hod | 14 | 64% | +7.12 | +$100 | ⚠ hod stale-list |
| btc_15m_momo_hod | 6 | 83% | +15.9 | +$96 | ⚠ hod stale-list, LOW_N |
| sol_15m_momo_v2_HOLD_f7 | 36 | 56% | +2.64 | +$95 | ✅ MATCH |
| eth_15m_fade_sniper | 95 | 55% | +0.85 | +$81 | only winning fade |
| sol_15m_momo_HOLD_f7 | 45 | 53% | +1.68 | +$76 | ✅ MATCH |
| eth_15m_momo_HOLD_f7 | 43 | 53% | +1.58 | +$68 | ✅ MATCH |
| btc_15m_momo_v2_hod | 15 | 60% | +4.46 | +$67 | ⚠ hod stale |

### ETH v3/v4 winners (asset-specific edge)
| Sleeve | L n | L WR | L PnL |
|---|--:|--:|--:|
| eth_5m_v3_2 | 50 | 60% | +$292 |
| eth_5m_v3_3 | 50 | 60% | +$292 |
| eth_5m_v4 | 34 | 62% | +$246 |
| eth_5m_v3 | 74 | 54% | +$221 |
| eth_5m_v3_1 | 42 | 57% | +$193 |

### 🔴 KILL list (bleeding, root-caused)
| Sleeve | L PnL | Reason |
|---|--:|---|
| (DB) btc/eth/sol_5m_volume_INV_NIGHT | −$901/−$1171/−$1209 | dead anti-edge (bug #8) |
| (DB) 15m INV_NIGHT trio | −$244/−$150/+$28 | dead anti-edge |
| sol_5m_v3_3 | −$483 | BTC/SOL v3/v4 edge absent |
| btc_5m_fade_momo_v2 | −$482 | fade family loses |
| sol_5m_fade_sniper | −$468 | fade |
| sol_5m_fade_momo_v2 | −$376 | fade |
| sol_15m_fade_momo_v2 | −$340 | fade |
| sol_5m_v3_2 | −$327 | BTC/SOL v3 bad |
| btc_5m_v4 | −$323 | BTC v4 bad |
| btc_15m_sniper_hod | −$287 | sniper_hod (stale list, likely kill) |
| sol_5m_v3 | −$281 | |
| btc_5m_sniper_hod | −$267 | sniper_hod |
| eth_5m_momo_v2_HOLD_f7 | −$266 | eth5m v2 cell fragile |
| btc_5m_fade_sniper | −$246 | fade |
| eth_5m_momo_HOLD_f7 | −$238 | eth5m bare-F7 weak cell |
| btc_5m_v3_1 | −$235 | |
| btc_5m_momo_v2_HOLD_f7 | −$316 | btc5m v2 cell |

### Backtest fidelity (momo)
- corr(live $/tr, bt $/tr) = **0.61**; sign agreement **77.8%**; fired-direction match **100%** on shared slugs.
- momo HOLD_f7 v1+v2: ✅ backtest matches live. 15m-BTC cells strongest both sides.
- INV_NIGHT trio: ✅ fully reproduced (bt −$4.5 to −$5.8/tr vs live −$3.9 to −$5.4) → anti-edge confirmed.
- eth_5m momo_v2 "divergence" = non-overlapping fires (wider live universe), NOT logic error (WR identical 52.4%).
- kelly + prewindow: NO_INFRA (need fair_edge_bp/cvd/macd 1s features absent from canonical).

---

## 4. Verdict & recommended actions

### Implementation is sound; 4 active bugs to fix (see debug doc)
1. Fee split-brain → align both controllers to legacy 2%-on-profit
2. btc_5m_q → KILL
3. V8_01/V8_02 → restore g_1h_rf_with
4. vwap80 ×4 → restore vwap<0.80 ceiling

### Roster actions
- **KILL now**: INV_NIGHT ×6, fade ×5 (keep eth_15m_fade), sniper_hod ×~5, BTC/SOL v3/v4, btc_5m_q. ≈ −$6k/window of bleed removed.
- **KEEP/scale**: kelly ⭐, prewindow S3/S4, momo_HOLD_f7 15m cells, sol_5m_momo_v2, ETH v3/v4, sol_5m sniper winners (rf_tr_partial, btcf7, j_2asset, b3_no_opp).
- **INVESTIGATE**: rebuild HoD top-8 monthly refresh before judging *_hod; add Markov overlay to momo_HOLD_f7 (matches HANDOFF deploy spec); re-audit 20 too-new sniper sleeves after 48h.

### Data/infra gaps blocking full validation
- SOL canonical L25 too sparse (55% NaN asks) → SOL sniper fills unverifiable. Densify SOL book archive.
- 1s-trade features (fair_edge_bp, cvd, macd, vwap_dev) absent from canonical → kelly/prewindow/fade unbacktest­able. Add to canonical pipeline.

---

## 5. Source artifacts
- Fidelity: `FIDELITY_AUDIT_{V5_V9,V6_V7,V8_H,VL,MOMO_SHADOW}_2026_05_29.md`
- Replay: `BACKTEST_REPLAY_{BTC,ETH,SOL}_2026_05_29.md` + `replay_{btc,eth,sol}.csv`
- Momo bt: `BACKTEST_VS_LIVE_MOMO_2026_05_29.md`
- Live truth: `live_dashboard_2026_05_29.txt`, `live_all158_stats.csv`
- Bugs: `DEBUG_FINDINGS_ALL_SLEEVES_2026_05_29.md`

## END
