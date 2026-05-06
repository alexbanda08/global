# Momo 3-Way Comparison — Backtest L10 vs Realfill L25 vs Shadow Live

**Generated:** 2026-05-06

## TL;DR — CRITICAL FINDING

**5-minute momo sleeves are bleeding $-12 to $-24 per trade vs backtest. 15-minute sleeves match or beat backtest.**

| Asset_TF | sh $/trade | rf $/trade | Δ vs realfill | sh_hit% | rf_hit% | Δ hit% |
|---|---:|---:|---:|---:|---:|---:|
| **BTC_5m** ❌ | $-4.96 | $+15.23 | **−$20.19** | 57% | 92% | **−35pp** |
| **ETH_5m** ❌ | $+0.14 | $+13.40 | **−$13.26** | 68% | 92% | **−24pp** |
| **SOL_5m** ❌ | $+0.31 | $+13.01 | **−$12.71** | 66% | 89% | **−23pp** |
| BTC_15m ⚠ | $+5.13 | $+10.94 | −$5.81 | 60-83% | 91% | small |
| **ETH_15m** ✅ | $+6.48 | $+7.73 | −$1.25 | 85% | 92% | small |
| **SOL_15m** ✅ | $+5.87 | $+9.81 | −$3.94 | 86% | 80% | **beating** |

**Shadow totals (~16h since deploy 00:28 UTC):**
- 5m sleeves: **$-164.07 across 222 fires** (BTC −$208, ETH +$9, SOL +$35)
- 15m sleeves: **$+463.09 across 77 fires** (BTC +$87, ETH +$253, SOL +$123)
- Net portfolio: **$+299** in 16h

**Hypothesis (cross-references `MOMO_HEDGE_SELL_INVESTIGATION_2026_05_06.md`):**
1. Production controller anchors `rev_bp` to bar-close, not entry-price → fewer SELL/HEDGE triggers AND worse exit prices
2. 5m markets have only ~3 min after t+120 entry → tighter window, more sensitive to slippage
3. ETH_15m_SELL is BEATING backtest by +$7.5/trade — when conditions are right, alpha is REAL
4. 5m hit-rate collapse from 89% → 66% is too large to be slippage alone — likely a direction-misalignment bug or alpha decay since Apr-May training period

**Recommended action:**
- 🔴 **PAUSE all 5m momo sleeves** pending per-trade investigation
- ✅ Keep 15m sleeves running — working as designed
- Inspect 5+ random 5m losers: verify `signal` direction matches asset_ret_2m sign at fill_event_id timestamp
- Compare snap_staleness_ms_p95 from realfill (BTC 0.5s, ETH 8s, SOL 8s) vs production controller's actual book cache age

---

**Shadow window:** 2026-05-06T00:59:41+00:00 → 2026-05-06T17:21:47+00:00 UTC
**Shadow fires:** 299 live resolutions across 18 sleeves

**Important:** the L25 realfill backtest was built on the Apr 22 → May 4 data window (refresh_2026_05_02 cutoff). Shadow trading started May 6. **No time-window overlap** — comparison is between PER-TRADE DISTRIBUTIONS (mean PnL, hit rate per cell), not direct same-trade matches.

## Three data sources

| Source | Window | n | Fill model |
|---|---|---:|---|
| **Shadow live** | May 6 deploy ~19h | 299 | Production controller (paper mode) |
| **L25 realfill (full)** | Apr 22 – May 4 | 3597 | Snapshot-precise L25 raw book |
| **L10 backtest (full)** | Apr 22 – May 4 | 3678 | 10s-bucketed L10 book |

## Cell-level — per-trade distribution comparison

Compares mean PnL/trade and hit rate. If shadow $/trade ≈ realfill $/trade, the live strategy is matching backtest expectations; gaps signal production friction or sample variance.

| Cell | shadow n | sh_hit% | sh $/trade | rf_full n | rf_hit% | rf $/trade | bt_full n | bt_hit% | bt $/trade | Δ (sh−rf) | shadow_total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_5m_HOLD | 14 | 57.1 | $-7.621 | 341 | 88.9 | $+13.918 | 325 | 89.2 | $+14.477 | $-21.539 | $-68.59 |
| BTC_5m_HEDGE | 14 | 57.1 | $-7.621 | 341 | 93.3 | $+15.859 | 325 | 92.3 | $+15.776 | $-23.481 | $-68.59 |
| BTC_5m_SELL | 14 | 50.0 | $-7.911 | 341 | 93.3 | $+15.924 | 325 | 92.3 | $+15.818 | $-23.835 | $-71.20 |
| BTC_15m_HOLD | 6 | 83.3 | $+9.917 | 113 | 82.3 | $+9.778 | 108 | 82.4 | $+9.418 | $+0.139 | $+29.75 |
| BTC_15m_HEDGE | 6 | 83.3 | $+9.917 | 113 | 91.2 | $+11.442 | 108 | 81.5 | $+9.316 | $-1.525 | $+29.75 |
| BTC_15m_SELL | 5 | 60.0 | $+9.226 | 113 | 91.2 | $+11.608 | 108 | 81.5 | $+9.462 | $-2.382 | $+27.68 |
| ETH_5m_HOLD | 22 | 68.2 | $+0.180 | 306 | 91.8 | $+12.500 | 294 | 92.2 | $+12.585 | $-12.320 | $+2.52 |
| ETH_5m_HEDGE | 22 | 68.2 | $+0.180 | 306 | 94.1 | $+13.820 | 294 | 93.2 | $+13.095 | $-13.640 | $+2.52 |
| ETH_5m_SELL | 22 | 68.2 | $+0.310 | 306 | 94.4 | $+13.889 | 294 | 93.5 | $+13.139 | $-13.579 | $+4.34 |
| ETH_15m_HOLD | 13 | 84.6 | $+9.696 | 106 | 73.6 | $+5.055 | 101 | 74.3 | $+5.436 | $+4.641 | $+67.87 |
| ETH_15m_HEDGE | 13 | 84.6 | $+9.696 | 106 | 91.5 | $+8.956 | 101 | 85.1 | $+7.887 | $+0.739 | $+67.87 |
| ETH_15m_SELL | 13 | 84.6 | $+16.706 | 106 | 92.5 | $+9.177 | 101 | 87.1 | $+8.079 | $+7.529 | $+116.94 |
| SOL_5m_HOLD | 38 | 65.8 | $-0.058 | 260 | 89.6 | $+11.313 | 252 | 89.3 | $+11.196 | $-11.371 | $-1.57 |
| SOL_5m_HEDGE | 38 | 65.8 | $-0.058 | 260 | 93.5 | $+13.816 | 252 | 90.9 | $+12.840 | $-13.874 | $-1.57 |
| SOL_5m_SELL | 38 | 65.8 | $+1.410 | 260 | 93.8 | $+13.911 | 252 | 91.3 | $+12.926 | $-12.501 | $+38.06 |
| SOL_15m_HOLD | 7 | 85.7 | $+9.983 | 73 | 83.6 | $+9.252 | 71 | 84.5 | $+9.693 | $+0.731 | $+39.93 |
| SOL_15m_HEDGE | 7 | 85.7 | $+9.983 | 73 | 79.5 | $+10.000 | 71 | 78.9 | $+9.016 | $-0.018 | $+39.93 |
| SOL_15m_SELL | 7 | 85.7 | $+10.841 | 73 | 84.9 | $+10.183 | 71 | 80.3 | $+9.149 | $+0.657 | $+43.36 |

## Per (asset, tf) — shadow live

| Asset_TF | sh_n | sh_total_pnl | sh_$/trade | rf_$/trade | bt_$/trade | production_extrapolated_30d (sh_total × 30d/19h) |
|---|---:|---:|---:|---:|---:|---:|
| BTC_5m | 42 | $-208.38 | $-4.961 | $+15.234 | $+15.357 | $-7896.56 |
| BTC_15m | 17 | $+87.18 | $+5.128 | $+10.943 | $+9.399 | $+3303.76 |
| ETH_5m | 66 | $+9.37 | $+0.142 | $+13.403 | $+12.940 | $+355.17 |
| ETH_15m | 39 | $+252.68 | $+6.479 | $+7.729 | $+7.134 | $+9575.30 |
| SOL_5m | 114 | $+34.93 | $+0.306 | $+13.013 | $+12.321 | $+1323.71 |
| SOL_15m | 21 | $+123.23 | $+5.868 | $+9.812 | $+9.286 | $+4669.58 |

## Headline

- **Shadow live**: 299 fires, total $+299.01, **$+1.000 / trade**
- **L25 realfill (Apr-May)**: 3597 fires, total $+46355.05, **$+12.887 / trade**
- **L10 backtest (Apr-May)**: 3453 fires, total $+42885.04, **$+12.420 / trade**
- Per-trade Δ (shadow − realfill): **$-11.887**
- Per-trade Δ (shadow − backtest):  **$-11.420**

## Interpretation

- **Shadow $/trade ≥ realfill $/trade**: production is meeting or beating realfill — strategy is healthy.
- **Shadow $/trade < realfill $/trade by < 30%**: small-sample variance, watch.
- **Shadow $/trade << realfill $/trade**: production friction (slippage, missed fills, latency, controller cache rot). Investigate per-cell.
- **Shadow hit% < realfill hit%**: likely directional alpha decay or regime shift between Apr-May backtest period and May 6 live period.

## Files

- 3-way table: `strategy_lab\results\meta_classifier\momo_3way_compare.csv`
- Shadow: `data/v4/shadow_trades_2026_05_06/momo_resolutions_fresh.csv`
- L25 realfill: `strategy_lab/results/meta_classifier/momo_realfill_validation.csv`
- L10 backtest: `strategy_lab/results/meta_classifier/extended_backtest.csv`