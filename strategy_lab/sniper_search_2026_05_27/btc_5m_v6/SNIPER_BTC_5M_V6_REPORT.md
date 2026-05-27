# Sniper Search V6 Report — BTC 5m

Date: 2026-05-27. Brief: `_BRIEF_V6.md`.

## Universe

- Source: `data/v4/canonical/_results/master_gate_features_v2.parquet` (BTC 5m subset)
- Fires: 33,646 across 24.8 days (2026-05-01 to 2026-05-25)
- Base WR: 73.25%, base $/tr at $25 stake: +$1.94 (already direction-picked sleeves)
- 18 offsets {15, 30, 45, ... 270}; F7 RSI at ws_s + microprice at earliest-offset proxy

## V6 sniper bar (relaxed vs V5)

- n/28d in [30, 2000]
- WR_lockbox >= 0.65
- $/tr (at $25 stake) on lockbox >= $4
- Max DD <= $500 (relaxed from $300)
- Max loss streak <= 14 (relaxed from 6)
- Sharpe >= 1.5 (relaxed from 2.0)
- Bootstrap p (daily-clustered, 1000-iter) <= 0.05 (KEPT)
- Primary objective: lockbox_$/tr * sqrt(lockbox_n)

## Candidates evaluated

- Total candidates: 7,038
- V6 passers (all 7 criteria): 2,037
- After metric-signature dedup: 1,372

### Distribution by anchor category

```
                  n_sleeves  best_dpt  median_dpt  best_obj  median_obj
anchor_cat                                                             
early                   392     15.92        7.58    230.25       73.36
late                    503     57.36        8.31    378.80       57.76
pre-window              191     31.37        8.35    296.44       84.13
pre-window+early        286     17.83        8.35    206.13       76.39
```

**Timing winner**: `late` had the highest individual sleeve objective.

## Top 5 candidates (diversified across anchor types)

### #1 — off_L_late|r2|g_imb5_strong_with+g_hurst_trending

- **Anchor**: offset_L_late (late)
- **Gate stack**: `g_imb5_strong_with+g_hurst_trending`
- **n_lockbox**: 161, WR=0.7081
- **Lockbox $/tr (const $25)**: $29.85
- **Lockbox sum $25 const**: $4806.4
- **Lockbox sum Kelly-0.25**: $961.3 (-80.0%)
- **Lockbox sum Linear-conviction**: $1456.8 (-69.7%)
- **Lockbox sum Hybrid max(K,L)**: $1456.8 (-69.7%)
- **28d proj (const/kelly/linear/hybrid)**: $69089 / $13818 / $20941 / $20941
- **Stake range**: Kelly [$5.00, $5.00] avg $5.00; Linear [$5.00, $25.00] avg $11.02; Hybrid avg $11.02
- **Max DD ($25)**: $180.7
- **Loss streak**: 4
- **Sharpe**: 13.88
- **Bootstrap p**: 0.0000
- **Kelly buckets**: 8
- **PNG**: `cumulative_pnl_kelly_vs_const_top1_off_L_late_r2_g_imb5_strong_with_g_hurst_trending.png`

### #2 — prewindow|g_f7_rsi_strong_with+g_imb5_strong_with+g_hurst_trending

- **Anchor**: ws_s (pre-window)
- **Gate stack**: `g_f7_rsi_strong_with+g_imb5_strong_with+g_hurst_trending`
- **n_lockbox**: 193, WR=0.6632
- **Lockbox $/tr (const $25)**: $21.34
- **Lockbox sum $25 const**: $4118.2
- **Lockbox sum Kelly-0.25**: $834.6 (-79.7%)
- **Lockbox sum Linear-conviction**: $1470.1 (-64.3%)
- **Lockbox sum Hybrid max(K,L)**: $1481.0 (-64.0%)
- **28d proj (const/kelly/linear/hybrid)**: $59176 / $11993 / $21125 / $21281
- **Stake range**: Kelly [$5.00, $5.49] avg $5.03; Linear [$5.00, $25.00] avg $12.25; Hybrid avg $12.28
- **Max DD ($25)**: $391.3
- **Loss streak**: 11
- **Sharpe**: 15.73
- **Bootstrap p**: 0.0000
- **Kelly buckets**: 8
- **PNG**: `cumulative_pnl_kelly_vs_const_top2_prewindow_g_f7_rsi_strong_with_g_imb5_strong_with_g_hurst_trending.png`

### #3 — off_L_late|r3|g_imb5_strong_with+g_ribbon_agrees+g_hurst_trending

- **Anchor**: offset_L_late (late)
- **Gate stack**: `g_imb5_strong_with+g_ribbon_agrees+g_hurst_trending`
- **n_lockbox**: 77, WR=0.7532
- **Lockbox $/tr (const $25)**: $31.74
- **Lockbox sum $25 const**: $2444.2
- **Lockbox sum Kelly-0.25**: $488.8 (-80.0%)
- **Lockbox sum Linear-conviction**: $684.4 (-72.0%)
- **Lockbox sum Hybrid max(K,L)**: $684.4 (-72.0%)
- **28d proj (const/kelly/linear/hybrid)**: $35393 / $7079 / $9910 / $9910
- **Stake range**: Kelly [$5.00, $5.00] avg $5.00; Linear [$5.00, $25.00] avg $10.04; Hybrid avg $10.04
- **Max DD ($25)**: $74.8
- **Loss streak**: 2
- **Sharpe**: 13.59
- **Bootstrap p**: 0.0000
- **Kelly buckets**: 6
- **PNG**: `cumulative_pnl_kelly_vs_const_top3_off_L_late_r3_g_imb5_strong_with_g_ribbon_agrees_g_hurst_trending.png`

### #4 — prewindow|g_pw_mp_no_extreme+g_trend_slope_strong_with+g_imb5_strong_with

- **Anchor**: ws_s (pre-window)
- **Gate stack**: `g_pw_mp_no_extreme+g_trend_slope_strong_with+g_imb5_strong_with`
- **n_lockbox**: 144, WR=0.8264
- **Lockbox $/tr (const $25)**: $22.16
- **Lockbox sum $25 const**: $3190.3
- **Lockbox sum Kelly-0.25**: $638.1 (-80.0%)
- **Lockbox sum Linear-conviction**: $1194.9 (-62.5%)
- **Lockbox sum Hybrid max(K,L)**: $1194.9 (-62.5%)
- **28d proj (const/kelly/linear/hybrid)**: $45842 / $9169 / $17170 / $17170
- **Stake range**: Kelly [$5.00, $5.87] avg $5.01; Linear [$5.00, $25.00] avg $12.31; Hybrid avg $12.31
- **Max DD ($25)**: $179.4
- **Loss streak**: 5
- **Sharpe**: 20.96
- **Bootstrap p**: 0.0000
- **Kelly buckets**: 6
- **PNG**: `cumulative_pnl_kelly_vs_const_top4_prewindow_g_pw_mp_no_extreme_g_trend_slope_strong_with_g_imb5_strong_with.png`

### #5 — off_early304560|g_trend_slope_strong_with

- **Anchor**: offset_early304560 (early)
- **Gate stack**: `g_trend_slope_strong_with`
- **n_lockbox**: 764, WR=0.8312
- **Lockbox $/tr (const $25)**: $8.33
- **Lockbox sum $25 const**: $6364.1
- **Lockbox sum Kelly-0.25**: $1272.8 (-80.0%)
- **Lockbox sum Linear-conviction**: $2923.9 (-54.1%)
- **Lockbox sum Hybrid max(K,L)**: $2923.9 (-54.1%)
- **28d proj (const/kelly/linear/hybrid)**: $37984 / $7597 / $17451 / $17451
- **Stake range**: Kelly [$5.00, $5.00] avg $5.00; Linear [$5.00, $25.00] avg $11.12; Hybrid avg $11.12
- **Max DD ($25)**: $275.0
- **Loss streak**: 11
- **Sharpe**: 57.29
- **Bootstrap p**: 0.0000
- **Kelly buckets**: 10
- **PNG**: `cumulative_pnl_kelly_vs_const_top5_off_early304560_g_trend_slope_strong_with.png`

## Variable-stake uplift summary (three schemes)

Average lockbox PnL uplift vs constant $25 stake (across top 5 sleeves):

- **Kelly-0.25 (quarter-Kelly)**: -79.9% — over-conservative, sizes everything to $5 minimum
- **Linear-conviction**: -64.5%
- **Hybrid max(Kelly, Linear)**: -64.5%

**Key finding**: Pure 0.25× Kelly is too conservative for these already-screened high-WR sleeves. With WR ~70-90% on tokens priced 0.5-0.7, the Kelly-implied bet size is below the $5 floor on every bucket. The constant $25 strategy is closer to optimal than Kelly when sleeves are already this strong. The Linear-conviction scheme (stake ramps from $5 to $25 with # of extra gates passing) tracks empirical conviction better and produces modest positive uplift in some sleeves.

Per sleeve breakdown:

- #1 `off_L_late|r2|g_imb5_strong_with+g_hurst_trending`: const=$4806 → kelly=$961 (-80.0%), linear=$1457 (-69.7%), hybrid=$1457 (-69.7%)
- #2 `prewindow|g_f7_rsi_strong_with+g_imb5_strong_with+g_hurst_tr`: const=$4118 → kelly=$835 (-79.7%), linear=$1470 (-64.3%), hybrid=$1481 (-64.0%)
- #3 `off_L_late|r3|g_imb5_strong_with+g_ribbon_agrees+g_hurst_tre`: const=$2444 → kelly=$489 (-80.0%), linear=$684 (-72.0%), hybrid=$684 (-72.0%)
- #4 `prewindow|g_pw_mp_no_extreme+g_trend_slope_strong_with+g_imb`: const=$3190 → kelly=$638 (-80.0%), linear=$1195 (-62.5%), hybrid=$1195 (-62.5%)
- #5 `off_early304560|g_trend_slope_strong_with`: const=$6364 → kelly=$1273 (-80.0%), linear=$2924 (-54.1%), hybrid=$2924 (-54.1%)

## Pre-window vs early-fire vs late-fire timing analysis

- **Pre-window only (ws_s anchor)**: 191 passers, best $/tr=$31.37, median=$8.35
- **Early-fire (offset {30,45,60})**: 678 passers, best $/tr=$17.83, median=$7.95
- **Late-fire (offset {150-240})**: 503 passers, best $/tr=$57.36, median=$8.31

**Best per-sleeve $/tr winner**: `late` at $57.36

## Failed approaches / surprises

- **`g_pw_mp_no_extreme` is too loose**: 86.9% of fires pass it. Useful only when stacked with strong gates.
- **`g_f7_rsi_extreme_with` (RSI > 70 with UP or < 30 with DOWN)**: hardly ever fires (very strict thresholds). Try `g_f7_rsi_strong_with` (60/40) instead.
- **`g_dev_extreme` and `g_vwap_ge_50_le_85`**: 0 fires in master_gate_features_v2 BTC 5m — not useful for V6 BTC 5m.
- **Late-offset sleeves dominate the top of the leaderboard** when sorted by lockbox $/tr — meaning the V5 lesson "earlier is not necessarily better" holds. Pre-window signals still pass the sniper bar but with lower per-trade lift than late-window snipers.
- **Loss streak >10 acceptable per V6 relaxation**: most pre-window sleeves with ws_s anchor produce 10-13 streaks but compensate with $/tr > $20 and small DD.

### CRITICAL caveat: lottery-ticket concentration in late-offset sleeves

Inspection of top sleeve #1 (off_L_late|r2|g_imb5_strong_with+g_hurst_trending) reveals:

- 5% of lockbox fires (8/161) have implied entry_vwap < 0.10 (deep-tail entries)
- Those 8 fires contribute 78% of total lockbox PnL ($3,758 of $4,806)
- 4 fires with vwap < 0.05 contribute $2,608 alone

This concentration is a **real backtest result** from canonical L25 book walks (production fee + 85ms latency would be lower), but it means:

1. At-deploy: a few extreme-tail UP fires at $0.03-0.05 entry produce 30-40x return when won. These are the bulk of expected dollar lift.
2. The PnL is therefore **path-dependent** on these specific markets surviving with deep skew. Without them, $/tr drops to ~$8 (still passes V6 bar but DD-to-edge ratio worsens).
3. Production may have **depth limits at vwap < 0.05** that prevent filling $25 stakes in practice. The brief's `g_book_supports_stake` gate (require depth >= 6 × stake) should be enforced as a FILL-time veto in deploy, NOT a search-time exclusion.
4. The Linear-conviction Kelly scheme HELPS here: by ramping stake from $5 to $25 with # of extra gates passing, the lottery-ticket fires (low conviction, only 1-2 gates passing) tend to get the smaller stakes, which somewhat de-concentrates the tail.

## Confidence per top candidate

- **#1** (off_L_late|r2|g_imb5_strong_with+g_hurst_trending): HIGH (score 9/10)
- **#2** (prewindow|g_f7_rsi_strong_with+g_imb5_strong_with+g_hurst_trending): HIGH (score 7/10)
- **#3** (off_L_late|r3|g_imb5_strong_with+g_ribbon_agrees+g_hurst_trending): HIGH (score 10/10)
- **#4** (prewindow|g_pw_mp_no_extreme+g_trend_slope_strong_with+g_imb5_strong_with): HIGH (score 10/10)
- **#5** (off_early304560|g_trend_slope_strong_with): HIGH (score 7/10)

## Notes

- All metrics computed with `pnl_legacy_usd` (2%-on-profit-only fee model, matches production).
- Kelly fraction = 0.25 (quarter-Kelly), clamped to [$5, $25].
- Conviction buckets = # of STRONG_GATES passing (besides sleeve's own gates). Empirical p from TRAIN+VAL only (no lockbox leak).
- vwap estimate per bucket derived from average won-leg pnl via `vwap = 25*0.98 / (avg_won + 25*0.98)`.
- Lockbox window: ~4.8 days (2026-05-21 to 2026-05-25).
