# Sleeve Optimization — 21 live shadow sleeves (2026-05-30)

_Pull-fresh + compare-to-backtest + optimize (gates / exit / hedge). Canonical `trading_events_30d` refreshed from VPS3 at **May 30 22:39 UTC** (1,215,710 events). All 21 requested sleeves analyzed on **5,129 resolved live trades**. PnL uses the production fee (0.07·p·(1−p) winner-only curve) as logged — never recomputed._

## TL;DR

- **Engine is faithful.** Where canonical L25 is dense (BTC), live ≈ backtest-replay (|Δfill_vwap|≈0.012, 100% outcome match). Divergences are real edges/losses, not engine error. SOL replay is **invalid** (L25 ask-side 55% NaN = VPS2 collector gap) → trust LIVE for SOL.
- **Exit policies (stoploss / hedge / take-profit) are a DEAD END** — re-confirmed from `EXIT_POLICY_RESEARCH_2026_05_27`: HOLD-to-resolve beats every exit on these short binaries (SL −$3 to −$5/tr, hedge −$0.4 to −$0.8, TP −$1.3 to −$2.3). Cutting a 70-95% WR position that dips just locks the loss. **No exit change recommended. The lever is GATES.**
- **3 universal gate levers** (walk-forward validated, improve BOTH chronological halves):
  1. `vsum ≤ 1.30` — cross-token overround filter (don't buy when up_vwap+dn_vwap is rich). Fixes the imb5 family.
  2. `entry_vwap ≤ 0.70` — don't overpay (asymmetric-payoff trap). Lifts the eth-cloud / cci / 15m families.
  3. `drop_US` session (skip fire hours 14-21 UTC) — US session is adverse for SOL + Kelly + some ETH.
- **2 KILLs**: `btc_5m_q_parent15mslope_ts_imb5_v8` (−$930, replay-confirmed real loser, no gate reaches positive) and `btc_5m_ts_mpskew_any_off30` (−$93, no gate generalizes).
- **1 SALVAGE**: `btc_5m_l_1hrf_imb5_ribbon_v8` (−$139) → `vsum≤1.30` flips the recent half positive (loss is entirely wide-book fires).
- **Biggest $ lever**: Kelly's edge is **entirely the EU session** (EU +$2,272 / ASIA −$1,181 / US −$841) and **entirely the UP side** (UP +$1,141 / DOWN −$891). Restricting Kelly to EU + UP-bias is the single highest-impact change in the fleet.

## 1. Fresh live performance — all 21 sleeves (sorted by total PnL)

n = resolved live trades; mean/total in $ (per-$5 stake for sniper, Kelly-sized for the two `ALL_*`). `mean5` = sizing-neutral per-$5 EV.

| sleeve | n | WR% | total $ | mean $ | mean5 | dir split | entry vwap | verdict |
|---|--:|--:|--:|--:|--:|---|--:|---|
| ALL_5m_S3_prewindow | 300 | 54.3 | **+323** | +1.08 | +0.22 | 134U/166D | 0.51 | KEEP+gate (EU) |
| ALL_5m_phase1_kelly | 858 | 51.7 | **+249** | +0.29 | −0.05 | 409U/449D | 0.51 | KEEP+gate (EU+UP) ⚠ leverage-only |
| sol_5m_rf_tr_partial_mid | 371 | 69.5 | **+93** | +0.25 | +0.25 | 202U/169D | 0.70 | ⭐ KEEP+gate (drop_US) |
| eth_5m_l_ema50_hurst_grandparent_v8 | 78 | 73.1 | **+72** | +0.92 | +0.92 | 58U/20D | 0.63 | ⭐ KEEP+gate (evcap) |
| btc_15m_ema50_ema800_off600_down | 61 | 80.3 | **+53** | +0.86 | +0.86 | DOWN-only | 0.86 | ⭐ KEEP+gate (evcap/vsum) |
| eth_5m_bb_mp_hurst_band_v6 | 107 | 72.9 | +50 | +0.47 | +0.47 | 58U/49D | 0.66 | KEEP+gate (depth/vsum) |
| eth_5m_bb_mp_hurst_band_v6_vL | 122 | 71.3 | +46 | +0.37 | +0.37 | 63U/59D | 0.66 | KEEP+gate (depth) |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 60 | 76.7 | +33 | +0.54 | +0.54 | 29U/31D | 0.70 | ⭐ KEEP+gate (evcap) |
| eth_5m_cloud_vwap_hurstmp_v7 | 93 | 71.0 | +32 | +0.34 | +0.34 | 50U/43D | 0.66 | KEEP+gate (vsum) |
| eth_5m_cloud_ribbon_mp_hurst_v6 | 84 | 72.6 | +14 | +0.17 | +0.17 | 39U/45D | 0.70 | ⭐ KEEP+gate (evcap) |
| btc_5m_up_a2_hlcascade50k_v9 | 8 | 50.0 | +13 | +1.63 | +1.63 | UP-only | 0.50 | HOLD (too new, n=8) |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 233 | 73.8 | +13 | +0.06 | +0.06 | 118U/115D | 0.74 | KEEP as-is (no gate generalizes) |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 222 | 65.8 | +12 | +0.05 | +0.05 | UP-only | 0.66 | WATCH (evcap declining) |
| eth_5m_v5repl_off120_v6 | 17 | 88.2 | +10 | +0.61 | +0.61 | 9U/8D | 0.79 | DUP of tr200 ↓; too new |
| eth_5m_tr200_mp_sms_active_off120 | 17 | 88.2 | +10 | +0.61 | +0.61 | 9U/8D | 0.79 | **DUPLICATE** (identical fires) |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | 176 | 76.7 | +5 | +0.03 | +0.03 | 76U/100D | 0.76 | KEEP+gate (evcap≤0.80) |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | 46 | 89.1 | +3 | +0.07 | +0.07 | 29U/17D | 0.92 | THIN (entry 0.92) — gate vsum or watch |
| sol_5m_f7_mfi_ema200_vwap_v6 | 418 | 68.7 | +0 | +0.00 | +0.00 | 189U/229D | 0.68 | KEEP+gate (dir_UP) |
| btc_5m_ts_mpskew_any_off30 | 120 | 54.2 | **−93** | −0.77 | −0.77 | 71U/49D | 0.61 | 🔴 KILL |
| btc_5m_l_1hrf_imb5_ribbon_v8 | 506 | 74.5 | **−139** | −0.28 | −0.28 | 415U/91D | 0.77 | 🟠 SALVAGE (vsum≤1.30) |
| btc_5m_q_parent15mslope_ts_imb5_v8 | 1232 | 66.6 | **−930** | −0.76 | −0.76 | 686U/546D | 0.75 | 🔴 KILL |

**Net fleet (these 21): ≈ −$60** — but that's −$1,162 from the 3 imb5/mpskew losers masking ~+$1,100 of genuine winners. Removing the 2 KILLs alone flips the set to **≈ +$960** lifetime.

### Live-vs-backtest fidelity (the "compare to the tests that created them")

| sleeve | live $/tr | backtest $/tr | match | note |
|---|--:|--:|---|---|
| btc_15m_ema50_ema800_off600_down | +1.40 | +1.49 | ✅ | real edge, BTC L25 dense |
| btc_5m_q_parent15mslope_ts_imb5_v8 | −0.63 | −0.43 (−0.55 fresh-book) | ✅ | **genuine loser**; orig V8 +$6.20 = look-ahead imb5 gate |
| eth_5m_* (bb/cloud/l_ema50) | +ve | n/a (too new at May-29 cutoff) | — | trust live (now n=78-122) |
| sol_5m_* (rf/cci/btcf7/j/f7) | +ve | INVALID | ⚠ | SOL L25 ask-side 55% NaN — replay not usable; live is truth |

Engine faithfulness is established (BTC). The original GA-search projections for the **imb5 / mpskew** V8 cells were **over-optimistic by look-ahead** (imbalance computed with post-fire info); live + clean replay both confirm the loss. Other cells' specs are faithful per `FIDELITY_AUDIT_V6_V7`.

## 2. Gate optimization — walk-forward-validated recommendations

Method: per-sleeve logged-feature sweep (`03_gate_sweep.py`) → chronological 50/50 holdout (`04_walkforward_gates.py`). A gate is recommended ONLY if it improves mean PnL in **both** halves (kills in-sample/session overfit). Features are all causal (logged at fire time): `entry_vwap, vwap_sum (up+dn cross-token), own_depth, cross_spread, fire_offset, hour, direction`.

| sleeve | recommended gate | WF h1 Δ$/tr | WF h2 Δ$/tr | effect |
|---|---|--:|--:|---|
| **sol_5m_rf_tr_partial_mid** | `drop_US` (skip hr 14-21 UTC) | +0.50 | +0.50 | ~doubles EV; US session mean −0.50 |
| **ALL_5m_phase1_kelly** | `keep_EU` (hr 6-13) **+ UP-bias** | +0.87 | +17.6 | EU=entire edge; DOWN side −$891 |
| **ALL_5m_S3_prewindow** | `keep_EU` / `evcap≤0.50` | + | + | EU +$335 vs US −$131 |
| **btc_15m_ema50_ema800_off600_down** | `evcap≤0.70` (or `vsum≤1.25`→97.6% WR) | +1.04 | +1.10 | strong; entry currently 0.86 |
| **eth_5m_l_ema50_hurst_grandparent_v8** | `evcap≤0.70` (+ dir_UP) | +0.17 | +0.69 | only sleeve with +ve ungated CI-lo |
| **eth_5m_cloud_ribbon_mp_hurst_v6** | `evcap≤0.70` | +0.69 | +0.65 | lifts marginal → strong |
| **sol_5m_cci_f7_mfi_partial_vwap_v6** | `evcap≤0.75` (+ drop_US) | +0.44 | +0.66 | offset {90,120}→92% WR |
| **eth_5m_bb_mp_hurst_band_v6** | `depth≥1000` + `vsum≤1.30` | + | + | both halves +ve |
| **eth_5m_bb_mp_hurst_band_v6_vL** | `depth≥1000` | +0.19 | +0.19 | |
| **eth_5m_cloud_vwap_hurstmp_v7** | `vsum≤1.30` | +0.26 | +0.39 | |
| **btc_5m_parent15m_notrang_ts_mpskew_v7** | `evcap≤0.80` | +0.17 | +0.25 | marginal lift |
| **sol_5m_f7_mfi_ema200_vwap_v6** | `dir_UP` (+ keep_EU) | +0.13 | +0.75 | UP side carries it; DOWN flat |
| **btc_15m_vwapprem_ema50_mpskew_off600_v6** | `vsum≤1.25` | +0.07 | +0.50 | thin (entry 0.92) |
| **btc_5m_l_1hrf_imb5_ribbon_v8** | `vsum≤1.30` (salvage) | +0.13 | +0.33 | flips recent half +ve |
| sol_5m_j_2asset / sol_5m_btcf7 | none generalizes | — | — | keep ungated / watch |
| btc_5m_ts_mpskew_any_off30 | none generalizes | — | — | 🔴 KILL |
| btc_5m_q_parent15mslope_ts_imb5_v8 | best gate still −0.31/tr | — | — | 🔴 KILL |

## 3. Loser verdicts

**🔴 KILL `btc_5m_q_parent15mslope_ts_imb5_v8` (−$930, n=1232).** Replay reproduces the loss on clean fresh books (live −0.574 vs bt −0.547 /tr). 100% outcome match → not a fill/fee/timing artifact. Every slice is negative (both directions, all sessions, depth≥2000 still −$374). Best ≤1-gate (`vsum≤1.25`) only lifts to −0.31/tr. The original V8 +$6.20/tr projection was **look-ahead in the GA imb5 search** (g_imb5_strong_with evaluated with post-fire book info). The edge does not exist OOS. **Also audit every other `imb5`-search V8 cell for the same look-ahead.**

**🔴 KILL `btc_5m_ts_mpskew_any_off30` (−$93, n=120).** No gate improves both halves. Every session and direction negative. off30 (fire 30s before close) is too late — crowd already priced. Kill.

**🟠 SALVAGE `btc_5m_l_1hrf_imb5_ribbon_v8` (−$139, n=506, 74.5% WR).** The loss is entirely **wide-book / high-overround** fires: `cross_spread≤0.22 → 96.3% WR, +$24`; `vsum≤1.30` improves both halves (+0.13/+0.33). It buys the favorite at 0.77 (mostly UP, 415/91) so needs >77% WR; the tight-book subset clears that. Deploy `vsum≤1.30 AND own_depth≥1000` and re-shadow; kill if still negative after n≥80 gated. (Subagent B is computing the exact gated CI — see §5.)

## 4. Structural notes

- **Duplicate**: `eth_5m_v5repl_off120_v6` and `eth_5m_tr200_mp_sms_active_off120` produce **identical fires** (n=17, same PnL, same slots). They are functionally the same gate set (tr_above_ema200 + mp_skew + sms/active-session at off120). **Run one, retire the other** — saves a card and halves correlated risk.
- **Kelly is a leverage play, not a signal play** (`mean5` = −0.05 → a flat-$5 Kelly would LOSE). The +$249 is 4× Kelly sizing on the high-conviction tail. It is fragile if `fair_edge_bp` predictiveness degrades. Restricting to EU + UP-bias both raises EV and de-risks the leverage.
- **Session is the dominant exogenous variable** across the fleet: US hours (14-21 UTC) are adverse for SOL-rf, Kelly, prewindow, sol-cci; EU hours (6-13) carry Kelly/prewindow. This is consistent with EU = peak Polymarket liquidity, US = informed/adverse flow.

## 5. Final stacked-gate configs with bootstrap CI (subagent B)

Block-bootstrap CI-lo (2.5%, 2000 resamples) on the gated mean PnL, with chronological holdout. Full table: `GATED_CONFIGS_2026_05_30.md` + `final_gated_configs.csv`. Ranked by robustness:

| sleeve | gate stack | gated n | gated total $ | CI-lo $/tr | call |
|---|---|--:|--:|--:|---|
| sol_5m_cci_f7_mfi_partial_vwap_v6 | `evcap≤0.80 + drop_US` | 40/60 | +$51 | **+0.33** | ✅ deploy |
| eth_5m_l_ema50_hurst_grandparent_v8 | `evcap≤0.70` | 57/78 | +$77 | **+0.25** | ✅ deploy |
| sol_5m_rf_tr_partial_mid | `drop_US` | 224/371 | +$167 | **+0.16** | ✅ deploy |
| sol_5m_f7_mfi_ema200_vwap_v6 | `evcap≤0.75 + dir_UP` | 152/418 | +$88 | **+0.03** | ✅ deploy |
| eth_5m_bb_mp_hurst_band_v6 | `evcap≤0.70 + depth≥1000` | 70/107 | +$59 | **+0.03** | ✅ deploy |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | `evcap≤0.80 + vsum≤1.30` | 80/176 | +$61 | ~0 | deploy (marginal) |
| eth_5m_bb_mp_hurst_band_v6_vL | `depth≥1000` | 113/122 | +$64 | −0.03 | deploy (monitor) |
| ALL_5m_phase1_kelly | `keep_EU` | 256/858 | **+$2,272** | −0.37 | deploy (high variance from Kelly leverage) |
| ALL_5m_S3_prewindow | `drop_US` | 178/300 | +$455 | −1.03 | deploy (high variance) |
| eth_5m_cloud_vwap_hurstmp_v7 | `evcap≤0.70 + depth≥1000` | 60/93 | +$41 | −0.26 | deploy (monitor) |
| eth_5m_cloud_ribbon_mp_hurst_v6 | `evcap≤0.70` | 44/84 | +$37 | −0.21 | deploy (monitor) |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | `evcap≤0.70` | 139/222 | +$45 | −0.39 | monitor (both halves less-negative only) |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | `vsum≤1.25` | 36/46 | +$12 | −0.06 | monitor (thin, entry 0.92) |
| **btc_5m_l_1hrf_imb5_ribbon_v8** | `cross_spread≤0.22` | 136/506 | **+$24** | −0.03 | 🟠 salvage — flips +ve in BOTH halves (h1+0.25, h2+0.09); re-shadow gated |
| **btc_5m_q_parent15mslope_ts_imb5_v8** | best ≤3-gate `vsum≤1.30+depth≥1000+dir_DOWN` | — | −$18 | — | 🔴 KILL — no stack reaches mean≥0 (best −$0.05/tr) |
| **btc_5m_ts_mpskew_any_off30** | best `dir_DOWN+vsum≤1.30` mean −$0.155 | — | — | — | 🔴 KILL — unsalvageable |

**Highest-confidence deploys (CI-lo > 0):** sol_cci (+0.33), eth_l_ema50_hurst (+0.25), sol_rf (+0.16), sol_f7_mfi (+0.03), eth_bb (+0.03). These five are genuinely de-risked, not just point-estimate improvements.

### §5b External-feature confirm gates (subagent A)

Tested causal-at-fire external gates (binance momentum, chainlink basis, HL liq cascade, Poly CVD) with both-half holdout. Full: `EXTERNAL_GATES_2026_05_30.md`. **One sleeve gained a real external gate; 16 did not.**

- ⭐ **`sol_5m_rf_tr_partial_mid` + binance 5m-momentum gate (`ma_300`)**: passes both halves (H1 +$1.91, H2 +$2.24 lift). Retains 38% of fires at **+$2.02/fire** vs −$0.80 for rejected; works within UP and DOWN independently (not a direction proxy). Shorter horizons also pass (ma_120 +$1.61, ma_60 +$0.88). **This STACKS with `drop_US`** → `sol_5m_rf` is the fleet standout (two independent validated gates). Optional: + `cvd30_align` → +$2.84/fire at n=73.
- **Chainlink basis = SPURIOUS** for gating: binance trades a constant ~14-15bps above chainlink RTDS across this window (ETH frozen at exactly 14.93bps → **likely stale CL feed — flag for data team**). `basis_agrees` ≡ `direction==UP`, so it's a disguised direction filter, not signal.
- **HL liquidations = DEAD**: canonical HL liq feed ends May 27 13:35; fires start after → zero overlap. **Refresh HL liquidations to test cascade gates.**
- **Poly CVD = marginal**: 19-22% coverage; only helps `sol_5m_rf`. Too sparse standalone.
- **Other 16 sleeves: no external gate generalizes** — their edge is sleeve-specific microstructure, not a universal momentum/flow overlay.

**Net external-gate takeaway:** the only new external edge is `sol_5m_rf_tr_partial_mid` + `ma_300` momentum — a large, robust lift that compounds with its `drop_US` session gate.

## 6. Recommended actions for TV (ranked)

1. **KILL** `btc_5m_q_parent15mslope_ts_imb5_v8` + `btc_5m_ts_mpskew_any_off30` → stops ≈ −$1,020 bleed. Audit other imb5 V8 cells for look-ahead.
2. **Gate Kelly** to EU session (fire hour 6-13 UTC) + UP-bias. Highest $ impact in the fleet.
3. **Deploy `drop_US`** on `sol_5m_rf_tr_partial_mid` (~doubles its EV, WF-robust).
4. **Deploy `entry_vwap≤0.70`** cap on `btc_15m_ema_down`, `eth_5m_l_ema50_hurst_grandparent`, `eth_5m_cloud_ribbon`, `sol_5m_cci_f7_mfi`.
5. **Deploy `vsum≤1.30`** (overround filter) on the eth-bb / eth-cloud-vwap cells and as the **salvage** gate on `btc_5m_l_1hrf_imb5_ribbon`.
6. **Dedup** the `v5repl_off120` / `tr200_mp_sms_active_off120` pair.
7. **Stack `ma_300` momentum gate on `sol_5m_rf_tr_partial_mid`** (with `drop_US`) — fleet's best-supported sleeve, two independent validated gates.
8. **Exit policy: HOLD on winners, `HEDGE_LATE` on marginal sleeves.** Fixed SL/TP/trailing all lose; HOLD is optimal for the 75%+ WR winners. BUT a robust hedge exists for MARGINAL/breakeven sleeves — `HEDGE_LATE` (final 30s, sell if held-token bid < 0.6×entry): confirmed walk-forward + bootstrap on fresh L25 → `btc_5m_parent15m_notrang` +$5→+$44 (~8×, CI-lo +0.13), `btc_15m_vwapprem` +$3→+$9. Do NOT hedge winners or structural losers. Full evidence: `HEDGE_EXIT_RESEARCH_SYNTHESIS_2026_05_30.md` §7.
9. **Risk-mgmt: cut Kelly leverage 4× → ½-Kelly** (ruin-avoidance, ~free EV give-up).
10. **Data hygiene**: refresh HL liquidations feed (stale since May 27) + investigate the frozen ETH chainlink basis (14.93bps).

## Artifacts

- Fresh substrate: `strategy_lab/_opt_2026_05_30/_results/fires_resolved_all.parquet` (5,129 resolved fires, flattened)
- Scripts: `strategy_lab/_opt_2026_05_30/{01_live_stats,02_build_fire_table,03_gate_sweep,04_walkforward_gates}.py`
- Sweeps: `_results/{live_stats_21,gate_sweep,walkforward_gates}.csv`
- Canonical refreshed: `data/v4/canonical/trading_events_30d.parquet` (→ May 30 22:39 UTC, 1,215,710 events)
- External gates (subagent A): `strategy_lab/reports/EXTERNAL_GATES_2026_05_30.md`
- Gated configs + CI (subagent B): `strategy_lab/reports/GATED_CONFIGS_2026_05_30.md`
