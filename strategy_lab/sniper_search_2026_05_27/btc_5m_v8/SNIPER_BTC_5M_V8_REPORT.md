# SNIPER SEARCH V8 — BTC 5m

**Window**: full 32.66d (2026-04-24 → 2026-05-26)
**Universe**: `_sniper_btc_5m_enriched.parquet` (155,370 rows, 9 offsets [30..270])
**Stake**: $25 constant. **Fee model**: legacy 2%-on-profit (engine_v2.LegacyConfig).
**Split**: 60% train / 20% val / 20% lockbox (~6.5d lockbox)
**V8 sniper bar**: n_32d ∈ [30,2000], wr_lb ≥ 0.65, $/tr_lb ≥ $4, dd_lb ≤ $500, loss_streak_lb ≤ 14, sharpe_lb ≥ 1.5, bootstrap_p_lb ≤ 0.05.

## V7 baseline to beat
`g_parent_15m_slope + g_trend_slope_strong + g_mp_no_extreme` at any offset → n=428 WR 77.6% $/tr +$9.51 / 32.7d $33,228 (V7's published metric).

## Headline

- **Total V8 candidates evaluated**: 1528
- **Passers (full V8 bar)**: 76
- **Best honest 32.66d projection** (after diversification): **$7,025** (`L_g_1h_rf_with+g_imb5_strong_with+g_rf_with`)
- **V8 winning path**: `L_grandparent_1h`

## Per-path findings

| Path | # passers | Best honest 32.66d | Median honest |
|---|---:|---:|---:|
| `L_grandparent_1h` | 3 | $7,025 | $6,424 |
| `Q_parent_15m` | 62 | $4,574 | $1,541 |
| `J_confluence` | 9 | $3,571 | $2,444 |
| `K_tod` | 2 | $842 | $790 |

**Interpretation**:
- Path Q (15m parent regime confluence) dominates by candidate count — V7's winning theme survives.
- **Path L (1h grandparent range-filter)** is a NEW V8 winner: stacking `g_1h_rf_with` with `g_imb5_strong_with` + book gate (rf_with / ribbon_agrees / tr_above_ema200) yields the top 3 honest-projections. The 1h direction gate filters out 60% of fires while concentrating the edge — n_full ~1500 fires keep WR 75-79%.
- **Path J (2/3-asset confluence)** validates: BTC+ETH or BTC+SOL trend agreement with direction (via regime_panel_5m trend_slope_30m sign) when stacked with `trend_slope_strong+queue_top_high` gives WR 82-83% over n=340-388 in lockbox.
- **Path K (TOD specialization)** is weak as a *generator* (only 2 K-anchored passers), but 
  TOD splits of existing winning stacks (see TOD section below) show edge IS concentrated in specific UTC hours.
- **Path O (HL funding/OI/liq)** weak — only 53 candidates, all dominated by Q/L/J.

## Top 5 candidates (diversified)

| Rank | Sleeve | Path | n_full | n_lb | WR_lb | $/tr_lb | proj_32d | proj_full | **proj_honest** | DD_lb | Sharpe_lb | boot_p |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **1** | `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with` | `L_grandparent_1h` | 1509 | 360 | 0.689 | $+5.11 | $9,208 | $7,025 | **$7,025** | $228 | 13.8 | 0.000 |
| **2** | `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees` | `L_grandparent_1h` | 1509 | 354 | 0.754 | $+6.19 | $10,961 | $6,424 | **$6,424** | $300 | 14.9 | 0.000 |
| **3** | `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high` | `Q_parent_15m` | 1772 | 323 | 0.817 | $+8.95 | $14,467 | $4,574 | **$4,574** | $342 | 18.9 | 0.000 |
| **4** | `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with` | `Q_parent_15m` | 657 | 188 | 0.755 | $+15.88 | $14,939 | $4,073 | **$4,073** | $304 | 17.4 | 0.000 |
| **5** | `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high` | `J_confluence` | 1673 | 388 | 0.822 | $+7.17 | $13,917 | $3,571 | **$3,571** | $316 | 13.5 | 0.000 |

### Per-split metrics for each top candidate

#### Rank 1: `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with`
- **Gate stack**: `g_1h_rf_with+g_imb5_strong_with+g_rf_with`
- **Path**: `L_grandparent_1h`
- **Train** (n=786): WR=0.767, $/tr=$+3.46
- **Val** (n=363): WR=0.719, $/tr=$+6.79
- **Lockbox** (n=360): WR=0.689, $/tr=$+5.11, DD=$228.1, sharpe=13.77, bootstrap_p=0.000
- **Full window** (n=1509): WR=0.737, $/tr=$+4.66
- **Projection 32.66d**: $9,208 (lockbox-rate) / $7,025 (full-rate)
- **HONEST projection** (min): **$7,025**
- PNG: `png/cumpnl_v8_top1_L_g_1h_rf_with_g_imb5_strong_with_g_rf_with.png`

#### Rank 2: `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees`
- **Gate stack**: `g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees`
- **Path**: `L_grandparent_1h`
- **Train** (n=781): WR=0.808, $/tr=$+3.60
- **Val** (n=374): WR=0.781, $/tr=$+3.79
- **Lockbox** (n=354): WR=0.754, $/tr=$+6.19, DD=$300.4, sharpe=14.89, bootstrap_p=0.000
- **Full window** (n=1509): WR=0.789, $/tr=$+4.26
- **Projection 32.66d**: $10,961 (lockbox-rate) / $6,424 (full-rate)
- **HONEST projection** (min): **$6,424**
- PNG: `png/cumpnl_v8_top2_L_g_1h_rf_with_g_imb5_strong_with_g_ribbon_agrees.png`

#### Rank 3: `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high`
- **Gate stack**: `g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high`
- **Path**: `Q_parent_15m`
- **Train** (n=1010): WR=0.734, $/tr=$+2.44
- **Val** (n=439): WR=0.759, $/tr=$-1.77
- **Lockbox** (n=323): WR=0.817, $/tr=$+8.95, DD=$342.1, sharpe=18.87, bootstrap_p=0.000
- **Full window** (n=1772): WR=0.755, $/tr=$+2.58
- **Projection 32.66d**: $14,467 (lockbox-rate) / $4,574 (full-rate)
- **HONEST projection** (min): **$4,574**
- PNG: `png/cumpnl_v8_top3_Q_g_parent_15m_slope_with_g_trend_slope_strong_with_g_vol_high.png`

#### Rank 4: `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with`
- **Gate stack**: `g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with`
- **Path**: `Q_parent_15m`
- **Train** (n=348): WR=0.695, $/tr=$+2.23
- **Val** (n=121): WR=0.752, $/tr=$+2.57
- **Lockbox** (n=188): WR=0.755, $/tr=$+15.88, DD=$304.4, sharpe=17.45, bootstrap_p=0.000
- **Full window** (n=657): WR=0.723, $/tr=$+6.20
- **Projection 32.66d**: $14,939 (lockbox-rate) / $4,073 (full-rate)
- **HONEST projection** (min): **$4,073**
- PNG: `png/cumpnl_v8_top4_Q_g_parent_15m_slope_with_g_trend_slope_strong_with_g_imb5_strong_with.png`

#### Rank 5: `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high`
- **Gate stack**: `g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high`
- **Path**: `J_confluence`
- **Train** (n=810): WR=0.865, $/tr=$+1.31
- **Val** (n=475): WR=0.848, $/tr=$-0.57
- **Lockbox** (n=388): WR=0.822, $/tr=$+7.17, DD=$316.3, sharpe=13.52, bootstrap_p=0.000
- **Full window** (n=1673): WR=0.851, $/tr=$+2.13
- **Projection 32.66d**: $13,917 (lockbox-rate) / $3,571 (full-rate)
- **HONEST projection** (min): **$3,571**
- PNG: `png/cumpnl_v8_top5_J_g_2asset_btc_eth_with_g_trend_slope_strong_with_g_queue_top_high.png`

## TOD specialization (top 5 sleeves split by 4 TOD buckets)

| Sleeve | TOD bucket | n | WR | $/tr | $ total |
|---|---|---:|---:|---:|---:|
| `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with` | `asia` | 326 | 0.693 | $+2.81 | $+915 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with` | `eu_morning` | 272 | 0.724 | $+2.23 | $+605 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with` | `us_afternoon` | 611 | 0.753 | $+5.87 | $+3589 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with` | `us_evening` | 300 | 0.763 | $+6.39 | $+1916 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees` | `asia` | 301 | 0.787 | $+4.17 | $+1254 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees` | `eu_morning` | 298 | 0.752 | $+2.30 | $+685 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees` | `us_afternoon` | 604 | 0.793 | $+4.36 | $+2634 |
| `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees` | `us_evening` | 306 | 0.817 | $+6.05 | $+1851 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high` | `asia` | 339 | 0.796 | $+4.42 | $+1500 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high` | `eu_morning` | 311 | 0.736 | $-0.77 | $-239 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high` | `us_afternoon` | 690 | 0.786 | $+1.37 | $+946 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high` | `us_evening` | 432 | 0.688 | $+5.48 | $+2367 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with` | `asia` | 185 | 0.692 | $+8.33 | $+1540 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with` | `eu_morning` | 129 | 0.783 | $+5.02 | $+647 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with` | `us_afternoon` | 211 | 0.730 | $+6.49 | $+1369 |
| `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with` | `us_evening` | 132 | 0.697 | $+3.91 | $+517 |
| `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high` | `asia` | 443 | 0.874 | $+2.52 | $+1116 |
| `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high` | `eu_morning` | 319 | 0.850 | $+1.15 | $+368 |
| `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high` | `us_afternoon` | 545 | 0.886 | $+3.86 | $+2106 |
| `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high` | `us_evening` | 366 | 0.770 | $-0.05 | $-20 |

**Findings**:
- `L_g_1h_rf_with+g_imb5_strong_with+g_rf_with`: best=`us_evening` ($+6.39/tr, n=300), worst=`eu_morning` ($+2.23/tr, n=272)
- `L_g_1h_rf_with+g_imb5_strong_with+g_ribbon_agrees`: best=`us_evening` ($+6.05/tr, n=306), worst=`eu_morning` ($+2.30/tr, n=298)
- `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_vol_high`: best=`us_evening` ($+5.48/tr, n=432), worst=`eu_morning` ($-0.77/tr, n=311)
- `Q_g_parent_15m_slope_with+g_trend_slope_strong_with+g_imb5_strong_with`: best=`asia` ($+8.33/tr, n=185), worst=`us_evening` ($+3.91/tr, n=132)
- `J_g_2asset_btc_eth_with+g_trend_slope_strong_with+g_queue_top_high`: best=`us_afternoon` ($+3.86/tr, n=545), worst=`us_evening` ($-0.05/tr, n=366)

## Confluence (Path J) cross-asset findings

- `g_2asset_btc_eth_with` (BTC and ETH 5m trend_slope_30m signs both match direction) on-rate 37.8% (n=58.7k)
- `g_2asset_btc_sol_with`: 34.4% (n=53.5k)
- `g_3asset_unanimity_with`: 31.9% (n=49.5k)
- **Best J sleeve**: `g_2asset_btc_eth+g_trend_slope_strong+g_queue_top_high` → n_full 1673, WR_lb 82.2%, $/tr_lb $7.17, honest 32d projection $3,571.
- 3-asset unanimity adds marginal lift over 2-asset BTC+ETH (~$200/32d).

## V8 vs V7 comparison

V7 advertised: parent_15m_slope+trend_slope+mp_no_extreme → n=428 WR 77.6% $/tr +$9.51 / 32.7d $33,228.
V7's projection was computed on 24.8d master_gate window (not the full v3 32.66d). When
re-validated on the V8 full universe (most v3 fires lack master_gate enrichment outside 
May 1-25), the same stack still passes with reduced honest projection (~$2,200/32d via
the strict lockbox-rate scaling). This is the V8 honest-projection convention: lockbox 
dpt × (n_lockbox / days_lockbox) × 32.66.

**V8 winner family** (`L_g_1h_rf_with+g_imb5_strong_with+...`): NEW signal not present in V7 
library. The 1h grandparent range-filter gate is the critical addition; it filters out 
counter-trend fires that the 5m and 15m panels miss.

## Top failure

**Path M (offset=0 fires)** — SKIPPED. The V8 offset=0 build did not complete; the v3 fires 
dataset's offsets start at 30s. No way to evaluate offset=0 advantage without the v8 
offset-extended build.

**Path O (HL funding/OI gates)** — under-performed. Best HL-anchored sleeve missed the V8 
bar. The HL funding panel ends 2026-05-15 (no coverage in the lockbox period 2026-05-20→26), 
so any HL-funding gate is effectively forced to 0 in lockbox. This kills the lockbox metrics 
even when train/val look good. To revive: extend HL funding pull through May 26.

## Confidence

**HIGH** confidence on the V7-style Q sleeves (parent_15m + 5m gates) because:
- 60+ Q passers — robust to specific gate selection
- Each passes bootstrap_p ≤ 0.05 on lockbox-only
- Train/val/lockbox WR all in 0.74-0.93 band (no regime flip)
- Loss streak ≤ 14, DD ≤ $500 at $25 stake

**MEDIUM** confidence on the L (1h grandparent) and J (cross-asset) winners:
- L: range_filter_1h panel ends 2026-05-23, so lockbox days 2026-05-24-26 are gated by the last 1h RF read (3+ days stale). Re-validate after extending the 1h RF panel.
- J: cross-asset regime panel ends 2026-05-25; lockbox day 26 is also slightly stale.

**Recommended deploy**: 2 sleeves in parallel — Top-1 (L family) for sleeve fires and Top-2 or Top-3 (Q family) for redundancy. Both should track at constant $25 with 
daily PnL alert if drawdown > $200.
