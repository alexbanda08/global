# Deployable shadow sleeves — by market, by variance, decorrelated sets (2026-06-01)

_Analyzed ALL 202 active shadow sleeves (resolution events, last 21 days, fresh to Jun 1 11:04 UTC). Filter: n≥30, WR>55%, positive total, non-deprecated (excluded SELL/HEDGE/INV_NIGHT/volume/fade). 43 qualify. Then: per-sleeve variance (PnL std) + Sharpe, signal-overlap clustering ((slug,direction) Jaccard) to flag "same-variance"/redundant sleeves, and the decorrelated set deployable together per market._

## Two variance classes (the "same variance" grouping)

Every qualifying sleeve falls into one of two clear risk classes by per-trade PnL std:

| class | std (per-trade) | family | profile | examples |
|---|--:|---|---|---|
| **HIGH-variance** | **~19-25** | momo (HOLD / v2_HOLD / _f7), eth v3/v4 | $25 stake, F7-momentum, big swings, high $/tr, moderate Sharpe | eth_15m_momo_v2_HOLD (std 23), eth_5m_v4 (19.6), sol_5m_momo_v2_HOLD_f7 (24.3) |
| **LOW-variance** | **~2-8** | sniper_v5 (rf/tr/ema/hurst/bb/cci/mp), V9 contrarian | $5 stake, late-window TA snipe, high WR, small tight $/tr, similar Sharpe | eth_5m_l_ema50_v8 (std 3.9), btc_15m_vwapprem (2.0), btc_15m_mpskew_trstack (1.85) |

**Deploy implication:** the LOW-variance sniper sleeves all share ~the same (low) variance → you can stack several decorrelated ones and the portfolio stays smooth (low drawdown). The HIGH-variance momo sleeves dominate portfolio risk → run **one per market**, sized down, as the high-octane return component. Equal-staking a momo + a sniper would let momo's variance swamp the book — size **inverse-to-std** (≈ ¼-⅕ stake on momo vs sniper) if combining.

## Per-market: qualifying sleeves → redundancy clusters → DEPLOY-TOGETHER set

`std` = per-trade $ PnL std (risk). `Sharpe` = $/tr ÷ std. Redundant = high (slug,direction) overlap (same bets = same variance, no diversification). Deploy-together = one leader per cluster, Sharpe ≥ 0.10.

### BTC 15m — 7 qualify, 4 decorrelated
| sleeve | n | WR% | $/tr | total | std | Sharpe | cluster |
|---|--:|--:|--:|--:|--:|--:|---|
| btc_15m_momo_HOLD | 64 | 57.8 | 3.60 | +230 | 24.7 | 0.15 | A (≡ momo_HOLD_f7, jacc 1.0) |
| btc_15m_ema50_ema800_off600_down | 102 | 80.4 | 1.49 | +152 | 8.1 | 0.18 | B (+_H +ema200_rf_down, jacc .43-.81) |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | 113 | 90.3 | 0.36 | +40 | 2.0 | 0.18 | C (unique) |
| btc_15m_mpskew_trstack_off600_down | 35 | 94.3 | 0.72 | +25 | 1.85 | **0.39** | D (unique) ⭐ |
> **DEPLOY:** `momo_HOLD` (high-var, return) + `ema50_ema800_off600_down` + `vwapprem` + `mpskew_trstack_off600_down` (3 low-var). Drop momo_HOLD_f7 (redundant), _H (dup of ema_down). Combined +$448. ⚠ the 3 sniper are all off600/DOWN — conceptually similar; mpskew_trstack has the best Sharpe (0.39).

### BTC 5m — 3 qualify, all unique
| sleeve | n | WR% | $/tr | total | std | Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| btc_5m_up_b2_contrarian2k_v9 | 267 | 56.6 | 0.68 | +183 | 5.7 | 0.12 |
| btc_5m_parent15m_slope_ts_mpnx_v7 | 60 | 60.0 | 0.83 | +50 | 4.8 | 0.17 |
| ~~btc_5m_q_parent15mslope_ts_imb5_v8~~ | 2178 | 68.1 | 0.05 | +114 | 18.4 | **0.003** ❌ |
> **DEPLOY:** `up_b2_contrarian2k_v9` + `parent15m_slope_ts_mpnx_v7`. **Drop q_imb5** — Sharpe 0.003 (the +$114 is noise; full-period it loses, confirmed KILL). Combined +$233.

### ETH 15m — 2 qualify, 1 decorrelated
| sleeve | n | WR% | $/tr | total | std | Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| eth_15m_momo_v2_HOLD | 92 | 67.4 | 7.78 | +716 | 23.0 | **0.34** ⭐ |
| eth_15m_momo_v2_HOLD_f7 | 53 | 56.6 | 3.03 | +160 | 24.8 | 0.12 (≡ HOLD, jacc 1.0) |
> **DEPLOY:** `momo_v2_HOLD` only (best Sharpe in the whole fleet; HOLD_f7 is redundant). High-variance — size accordingly.

### ETH 5m — 12 qualify, 5 decorrelated
| sleeve | n | WR% | $/tr | total | std | Sharpe | cluster |
|---|--:|--:|--:|--:|--:|--:|---|
| eth_5m_v4 | 37 | 59.5 | 5.29 | +196 | 19.6 | 0.27 | high-var, unique |
| **eth_5m_l_ema50_hurst_grandparent_v8** | 142 | 76.8 | 1.15 | +164 | 3.9 | **0.30** ⭐ | low-var, unique |
| eth_5m_v3_1 | 43 | 55.8 | 3.39 | +146 | 20.5 | 0.17 | high-var, unique |
| eth_5m_bb_mp_hurst_band_v6 | 209 | 72.7 | 0.51 | +106 | 3.5 | 0.15 | **E** (leader of 6: bb±vL, cloud_vwap±vL, cloud_ribbon±vL — jacc .51-.87) |
| eth_5m_tr200_mp_sms_active_off120 | 33 | 78.8 | 0.19 | +6 | 2.9 | 0.06 | ≡ v5repl (jacc 1.0) |
| ~~eth_5m_ema50_hurst_parent15mrang_v7~~ | 238 | 65.1 | 0.01 | +3 | 3.9 | 0.003 ❌ |
> **DEPLOY:** `l_ema50_hurst_grandparent_v8` (⭐ low-var, Sharpe 0.30) + `bb_mp_hurst_band_v6` (cluster-E leader) + `v4` + `v3_1` (high-var). **The whole bb/cloud/ribbon ±vL family (6 sleeves) is ONE signal** (mp_skew+hurst) — run only the leader `bb_v6`, the other 5 are redundant. Drop the v5repl/tr200 dup-pair and ema50_parent (no alpha). Combined ≈ +$612.

### SOL 5m — 8 qualify (6 non-dup), 6 decorrelated
| sleeve | n | WR% | $/tr | total | std | Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| sol_5m_momo_v2_HOLD_f7 | 152 | 59.2 | 3.79 | +576 | 24.3 | 0.16 | high-var ⭐$ |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 86 | 75.6 | 0.37 | +32 | 3.2 | 0.12 | low-var |
| sol_5m_b3_abs500_no_opp_v9 | 123 | 55.3 | 0.52 | +64 | 7.4 | 0.07 | V9 flow |
| sol_5m_rf_tr_partial_mid | 512 | 68.8 | 0.11 | +55 | 4.3 | 0.025 ⚠ |
| ~~sol_5m_rf_tr_pp_mid~~ (≈ rf_tr_partial) | 50 | 70.0 | 0.02 | +0.7 | 3.6 | 0.004 ❌ |
| ~~sol_5m_btcf7_f7overb_v7~~ | 318 | 66.0 | 0.00 | +0.2 | 3.8 | 0.000 ❌ |
> **DEPLOY:** `momo_v2_HOLD_f7` (high-var, the $ driver) + `cci_f7_mfi_partial_vwap_v6` (low-var, best Sharpe). **Drop rf_tr_partial/pp + btcf7** — Sharpe ≈ 0 and full-period analysis showed sol_rf base loses OOS (only ma_300 saves it). Combined ≈ +$608 (mostly momo).

### SOL 15m — 1 qualifies
| sleeve | n | WR% | $/tr | total | std | Sharpe |
|---|--:|--:|--:|--:|--:|--:|
| sol_15m_momo_v2_HOLD_f7 | 43 | 55.8 | 2.74 | +118 | 25.4 | 0.11 |
> **DEPLOY:** the single momo_v2_HOLD_f7 (high-var). No low-var SOL 15m sniper qualifies.

## Recommended live portfolio — per market (decorrelated, good-alpha only)

| market | deploy these together | why |
|---|---|---|
| **BTC 15m** | momo_HOLD + ema50_ema800_off600_down + vwapprem + mpskew_trstack | 1 high-var return + 3 low-var high-WR; decorrelated |
| **BTC 5m** | up_b2_contrarian2k_v9 + parent15m_slope_ts_mpnx_v7 | 2 distinct signals; drop q_imb5 (no alpha) |
| **ETH 15m** | momo_v2_HOLD | fleet-best Sharpe (0.34) |
| **ETH 5m** | **l_ema50_hurst_grandparent_v8** + bb_mp_hurst_band_v6 + v4 + v3_1 | l_ema50 ⭐; bb = leader of the 6-sleeve hurst/mp cluster |
| **SOL 5m** | momo_v2_HOLD_f7 + cci_f7_mfi_partial_vwap_v6 | high-var $ + low-var WR |
| **SOL 15m** | momo_v2_HOLD_f7 | only qualifier |

**Cross-market low-variance core (smoothest equity, deploy as a basket):** `eth_5m_l_ema50_v8` (Sharpe 0.30), `btc_15m_mpskew_trstack` (0.39), `btc_15m_vwapprem` (0.18), `eth_5m_bb_v6` (0.15), `sol_5m_cci_f7_mfi` (0.12), `btc_15m_ema_down` (0.18). All std 2-8, different gate families → genuinely decorrelated → combined drawdown stays low.

## ⚠ Caveats (important)
- **21-day live window only.** Several "qualifiers" are short-window: full-period analysis (`FULLPERIOD_5STRATS_FINAL_2026_05_31.md`) showed **sol_rf base loses OOS**, **btc_q is a confirmed KILL** (Sharpe 0.003 here = noise), and the high-`$/tr` momo edge is **leverage on $25 stake at high variance** (Sharpe 0.1-0.34, not a low-risk edge). Trust the **persistent** ones: ETH 5m sniper family (l_ema50, bb, cloud) — these matched full-period OOS.
- **"Same variance" = redundant bets:** momo_HOLD ≡ momo_HOLD_f7 (jacc 1.0); the 6 eth bb/cloud/ribbon ±vL sleeves are one signal; ema_down ≡ _H; rf_tr_partial ≈ rf_tr_pp; tr200 ≡ v5repl. Running duplicates adds cost + correlated risk, **not** return — pick the leader.
- **Stake by variance** if mixing classes: momo (std ~24) vs sniper (std ~4) → momo at ~⅕ stake to balance contribution, or run them as separate sized books.

Artifacts: `20_all_sleeves_stats.py`, `21_cluster_deploy.py` → `_results/{qualifying_sleeves, qualifying_with_variance, all_sleeve_fires}.{csv,parquet}`.
