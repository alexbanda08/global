# Master Findings Table — 21 sleeves × all trials (2026-05-30/31)

_Every result from this session in one place: fresh live performance, gate optimization (walk-forward + bootstrap-CI), external-feature gates, and exit/hedge. Data: canonical `trading_events` refreshed to May 30 22:39 UTC (5,129 resolved trades) + BTC L25 topped off to May 31 for the hedge tests. PnL = real logged (0.07-curve fee), per-$5 stake (sniper) / Kelly-sized (the two `ALL_*`)._

## Legend
- **Live**: current shadow performance (n trades, win-rate, total $, mean $/tr).
- **Best gate**: the walk-forward-validated gate stack + resulting gated total $ + bootstrap **CI-lo** (Δ/tr 2.5th pct). CI-lo>0 = genuinely de-risked.
- **Ext gate**: external-feature gate (binance momentum / chainlink basis / HL liq / poly CVD) that generalized.
- **Hedge**: `HEDGE_LATE` (final-30s cut if bid<0.6×entry) result — only BTC tested (fresh L25); ✅=robust, ✗=hurts/not-robust, —=not tested.
- **Verdict**: KEEP / GATE / SALVAGE / KILL / DUP.

## 1. MASTER TABLE (sorted by live total $)

| # | sleeve | live n | WR% | live $ | mean | best gate stack | gated $ | CI-lo | ext gate | hedge | verdict |
|--:|---|--:|--:|--:|--:|---|--:|--:|---|:--:|---|
| 1 | ALL_5m_S3_prewindow | 300 | 54.3 | +323 | +1.08 | `drop_US` | +455 | −1.03 | — | — | GATE (EU edge, hi-var) |
| 2 | ALL_5m_phase1_kelly | 858 | 51.7 | +249 | +0.29 | `keep_EU` (+UP-bias) | **+2272** | −0.37 | — | — | GATE + **½-Kelly** (leverage-only) |
| 3 | sol_5m_rf_tr_partial_mid | 371 | 69.5 | +93 | +0.25 | `drop_US` | +166 | **+0.16** | ⭐`ma_300` momentum (+$2.02/fire) | — | **GATE ⭐ (2 gates)** |
| 4 | eth_5m_l_ema50_hurst_grandparent_v8 | 78 | 73.1 | +72 | +0.92 | `evcap≤0.70` | +77 | **+0.25** | none | — | GATE ⭐ |
| 5 | btc_15m_ema50_ema800_off600_down | 61 | 80.3 | +53 | +0.86 | UNGATED (vsum≤1.25→97%WR) | +53 | — | none | ✗ hurts | KEEP (winner) |
| 6 | eth_5m_bb_mp_hurst_band_v6 | 107 | 72.9 | +50 | +0.47 | `evcap≤0.70 + depth≥1000` | +59 | **+0.03** | none | — | GATE |
| 7 | eth_5m_bb_mp_hurst_band_v6_vL | 122 | 71.3 | +46 | +0.37 | `depth≥1000` | +64 | −0.03 | none | — | GATE (monitor) |
| 8 | sol_5m_cci_f7_mfi_partial_vwap_v6 | 60 | 76.7 | +33 | +0.54 | `evcap≤0.80 + drop_US` | +51 | **+0.33** | none | — | GATE ⭐ |
| 9 | eth_5m_cloud_vwap_hurstmp_v7 | 93 | 71.0 | +32 | +0.34 | `evcap≤0.70 + depth≥1000` | +41 | −0.26 | none | — | GATE (monitor) |
| 10 | eth_5m_cloud_ribbon_mp_hurst_v6 | 84 | 72.6 | +14 | +0.17 | `evcap≤0.70` | +37 | −0.21 | none | — | GATE (monitor) |
| 11 | btc_5m_up_a2_hlcascade50k_v9 | 8 | 50.0 | +13 | +1.63 | UNGATED (n=8) | +13 | — | none | — | HOLD (too new) |
| 12 | sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 233 | 73.8 | +13 | +0.06 | UNGATED (none generalize) | +13 | −0.39 | none | — | KEEP (flat) |
| 13 | sol_5m_btcf7_f7overb_ema800_vwap_v7 | 222 | 65.8 | +12 | +0.05 | `evcap≤0.70` | +45 | −0.39 | none | — | WATCH |
| 14 | eth_5m_v5repl_off120_v6 | 17 | 88.2 | +10 | +0.61 | UNGATED (too new) | +10 | — | none | — | DUP / WATCH |
| 15 | eth_5m_tr200_mp_sms_active_off120 | 17 | 88.2 | +10 | +0.61 | UNGATED (too new) | +10 | — | none | — | **DUP** (≡ #14) |
| 16 | btc_5m_parent15m_notrang_ts_mpskew_v7 | 176 | 76.7 | +5 | +0.03 | `evcap≤0.80 + vsum≤1.30` | +61 | ~0 | none | **✅ +$45 (CI-lo +0.15)** | **GATE + HEDGE ⭐** |
| 17 | btc_15m_vwapprem_ema50_mpskew_off600_v6 | 46 | 89.1 | +3 | +0.07 | `vsum≤1.25` | +12 | −0.06 | none | **✅ +$6 (CI-lo +0.003)** | GATE + HEDGE (thin) |
| 18 | sol_5m_f7_mfi_ema200_vwap_v6 | 418 | 68.7 | +0 | +0.00 | `evcap≤0.75 + dir_UP` | +88 | **+0.03** | none | — | GATE ⭐ |
| 19 | btc_5m_ts_mpskew_any_off30 | 120 | 54.2 | **−93** | −0.77 | none generalize | — | — | none | ✗ artifact | 🔴 **KILL** |
| 20 | btc_5m_l_1hrf_imb5_ribbon_v8 | 506 | 74.5 | **−139** | −0.28 | `cross_spread≤0.22` (salvage) | +24 | −0.03 | none | ✗ artifact | 🟠 SALVAGE/KILL |
| 21 | btc_5m_q_parent15mslope_ts_imb5_v8 | 1232 | 66.6 | **−930** | −0.76 | best stack still −$0.05/tr | −18 | — | none | ✗ artifact | 🔴 **KILL** |

## 2. New GATES tried — what generalized vs what didn't

### 2a. Logged-feature gates (single-gate walk-forward sweep, all 21 sleeves)
Each tested with 50/50 chronological holdout; "generalizes" = improves mean PnL in BOTH halves.

| gate | definition | generalized on (both-half +) | failed on |
|---|---|---|---|
| `entry_vwap≤0.70/0.75/0.80` | don't overpay (asym-payoff trap) | btc_15m_ema_down, eth_l_ema50_hurst, eth_cloud_ribbon, eth_cloud_vwap, sol_cci, sol_btcf7, btc_5m_parent15m | most winners marginal-only |
| `vsum≤1.25/1.30` | cross-token overround filter (up_vwap+dn_vwap) | btc_5m_l_1hrf, btc_5m_q (mitigates), eth_bb, eth_cloud_vwap, btc_15m_vwapprem, btc_5m_parent15m | — |
| `drop_US` / `keep_ASIA_EU` | skip fire-hours 14-21 UTC | **sol_rf (+0.50 both halves)**, sol_cci, kelly→keep_EU, prewindow, eth_cloud_vwap | — |
| `keep_EU` | fire-hours 6-13 UTC | **kelly (+$2272)**, prewindow, sol_f7_mfi | — |
| `depth≥1000` | own-side book depth | eth_bb (+vL), eth_cloud_vwap | — |
| `cross_spread≤0.22/0.25` | tight book / arb-consistent | **btc_5m_l_1hrf (flips +)**, btc_15m_vwapprem | — |
| `dir_UP` | UP side only | sol_f7_mfi (UP carries it), kelly (DOWN side −$891) | — |
| `dir_DOWN` | DOWN side only | btc_5m_q (least-bad, still −) | — |
| `fire_offset` subset | keep positive-EV offsets | sol_rf {90,150,180}, sol_cci {90,120}→92%WR | — |

### 2b. External-feature gates (causal-at-fire, both-half holdout) — subagent A
| feature | result |
|---|---|
| **Binance momentum (`ma_30/60/120/300`)** | ⭐ **GENUINE on `sol_5m_rf_tr_partial_mid` only**: `ma_300` retains 38% of fires @ +$2.02/fire (vs −$0.80 rejected), both halves +$1.91/+$2.24. Sleeve-specific — fails on the other 16. |
| Chainlink basis (`basis_agrees`, `basis_large`) | ❌ **SPURIOUS** — binance trades ~14-15bps above CL universally (ETH frozen at 14.93bps = stale CL feed). `basis_agrees` ≡ `dir==UP`. Not signal. **Flag: ETH CL feed.** |
| HL liquidation cascade | ❌ **DEAD** — canonical HL liq feed ends May 27 13:35; fires start after → zero overlap. **Refresh HL liqs to test.** |
| Polymarket CVD (`cvd30_align`) | ⚠ marginal — 19-22% coverage; only helps sol_rf (+$0.23). Too sparse standalone. |

**Net new gate edge:** exactly one — `sol_5m_rf` + `ma_300` momentum (stacks with its `drop_US`).

## 3. Exit / Hedge trials — full matrix

Policies tested per fire over the real 1-5min hold, 10-seed bootstrap + walk-forward. BTC only (fresh L25); ETH/SOL pending L25 top-off.

| policy | definition | result |
|---|---|---|
| Fixed **stop-loss** (bid≤0.25..0.50) | sell on drop | ❌ all negative Δ vs HOLD (every sleeve) |
| **Take-profit** (bid≥0.85..0.97) | sell on rise | ❌ ≈breakeven at 0.97 (fee-saving ≈ upside given up), negative below |
| **Trailing** (peak−0.10..0.20) | give-back stop | ❌ negative Δ |
| **ORACLE_CUT** (chainlink crosses strike against bet ±0/2/5bps) | sell on confirmed reversal | ~0; +0.057/tr on btc_5m_q (CI-lo≈0) — marginal, loser-only |
| **ORACLE_LOCK** (buy opposite token on reversal) | lock | ❌ negative Δ |
| **HEDGE_LATE** (final-30s, sell if bid<0.55-0.65×entry) | confirmed-loser cut | ✅ **robust on MARGINAL sleeves** — see below |

**`HEDGE_LATE` robust hits (beats HOLD: both halves + AND bootstrap CI-lo > 0):**

| sleeve | base $ | best (frac/late_s) | Δ total | CI-lo | wf h1/h2 |
|---|--:|---|--:|--:|--:|
| **btc_5m_parent15m_notrang** (n176) | +5 | 0.55 / 45s | **+$45** | **+0.15** | +0.39/+0.12 |
| **btc_15m_vwapprem** (n46) | +3 | 0.75 / 30s | +$6.5 | +0.003 | +0.12/+0.16 |

**`HEDGE_LATE` does NOT help (0/12 configs robust):** btc_15m_ema_down (WINNER — hurts −$22, clips recoveries), btc_5m_q / btc_5m_l_1hrf / btc_5m_ts (LOSERS — big nominal gains but h1<0<h2 = regime artifact).

**Rule learned:** hedge only **marginal/breakeven** sleeves, only in the **final 30s**, only when **bid < 0.6×entry**. Never hedge winners; never use exits to rescue structural losers.

## 4. Roster summary

| bucket | sleeves | action |
|---|---|---|
| **KILL** (2) | btc_5m_q (−$930), btc_5m_ts (−$93) | remove → stops −$1,020 bleed; flips 21-set to ≈+$960 |
| **SALVAGE-or-kill** (1) | btc_5m_l_1hrf (−$139) | gate `cross_spread≤0.22` (+$24) then re-judge at n≥80 |
| **GATE ⭐ (CI-lo>0)** (5) | sol_rf (+`ma_300`!), eth_l_ema50_hurst, sol_cci, eth_bb, sol_f7_mfi | deploy gates — genuinely de-risked |
| **GATE (monitor)** (6) | prewindow, kelly(+½-Kelly), eth_bb_vL, eth_cloud_vwap, eth_cloud_ribbon, btc_15m_vwapprem | deploy but watch CI |
| **GATE + HEDGE ⭐** (2) | btc_5m_parent15m_notrang, btc_15m_vwapprem | add `HEDGE_LATE` (marginal-sleeve hedge) |
| **KEEP as-is** (3) | btc_15m_ema_down (winner), sol_j, btc_5m_up_a2_v9 | no change |
| **DUP** (1) | eth_5m_tr200_mp_sms ≡ eth_5m_v5repl | run one, retire other |
| **WATCH** (1) | sol_btcf7 | evcap declining |

## 5. Fleet-level risk-management (dwarf any single tweak)
1. **Kelly 4× → ½-Kelly** — ruin-avoidance, ~free EV (research: 4× = ruin guarantee; ½ keeps 75% growth, half drawdown).
2. **Gating beats exiting** — the 3 universal gates (`entry_vwap≤0.70`, `vsum≤1.30`, `drop_US`) prevent the bad trades exits only partially salvage.
3. **KILL losers** > any hedge by 10×.
4. **Data hygiene**: refresh HL liqs (stale May 27) + fix frozen ETH chainlink basis (14.93bps).

## Sources
`SLEEVE_OPTIMIZATION_2026_05_30.md`, `GATED_CONFIGS_2026_05_30.md`, `EXTERNAL_GATES_2026_05_30.md`, `HEDGE_EXIT_RESEARCH_SYNTHESIS_2026_05_30.md`, `RESEARCH_{BINARY_HEDGING,STOPLOSS_EXITS,DYNAMIC_HEDGING}_2026_05_30.md`. Data: `_opt_2026_05_30/_results/{fires_resolved_all,gate_sweep,walkforward_gates,final_gated_configs,external_gates,hedge_late_sweep,exit_grid_BTC_fresh}.*`.
