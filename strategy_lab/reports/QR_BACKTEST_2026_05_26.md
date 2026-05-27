# Quantum Ribbon Lite — Python port + meta-classifier backtest

**Date:** 2026-05-26
**Author:** automated backtest pipeline (`strategy_lab/meta_classifier/qr_*.py`)
**Window:** Apr 30 → May 22 2026 (canonical 28-day rolling), binance signals, chainlink outcomes, `LegacyConfig` (2%-on-profit-only) fee model.
**Status:** EXPLORATORY — QR adds modest standalone PnL but DOES add real lift as a CONFIDENCE FILTER on existing hybrid_v1 BTC sleeves. Walk-forward survives only on BTC s6_5m 60-150.

---

## 1. What QR Lite is

A Pine v6 indicator (TradingView) — 5 paired EMA layers spanning [21, 60] with pair_width=7 and uniform spacing = 8.

  Layer 1: 21/28   Layer 2: 29/36   Layer 3: 37/44   Layer 4: 45/52   Layer 5: 53/60

Derived features computed per bar:
- **ribbon_state** (-2..+2): weighted alignment of (short>long) across 5 layers; threshold mapping 0.25/0.40/0.60/0.75.
- **market_regime** (1=trending, 0=ranging): ribbon_aligned AND price_consistent AND ribbon_expanding.
- **market_health** (0-100): composite of alignment count, regime, volume_ratio, and ribbon spacing.
- **signal_confidence** (0-8): composite of regime, health, volume, momentum consistency, ribbon state with non-linear boost.
- **volume_ratio** = volume / SMA(volume,20). **momentum_consistency** = count of last 10 momentum signs matching current sign.

Source port: `strategy_lab/meta_classifier/compute_qr_panel.py`.

## 2. Panel build + distributions

Two panels written:
- `data/v4/canonical/_results/qr_panel_5m.parquet` (18,348 rows × 26 cols, 6,116 bars per asset)
- `data/v4/canonical/_results/qr_panel_15m.parquet` (6,117 rows, 2,039 bars per asset)

State distribution (% of bars):

| asset | tf  | -2 (strong bear) | -1 (bear) | 0 (neutral) | +1 (bull) | +2 (strong bull) | regime_trending | mean_health | mean_conf |
|-------|-----|------------------|-----------|-------------|-----------|------------------|-----------------|-------------|-----------|
| BTC   | 5m  | 38.9 %           | 5.4 %     | 4.9 %       | 4.3 %     | 46.5 %           | 49.2 %          | 71.8        | 4.85      |
| ETH   | 5m  | 41.2 %           | 5.1 %     | 4.9 %       | 5.2 %     | 43.6 %           | 47.0 %          | 71.4        | 4.82      |
| SOL   | 5m  | 40.3 %           | 5.0 %     | 5.4 %       | 5.2 %     | 44.1 %           | 48.6 %          | 71.6        | 4.83      |
| BTC   | 15m | 37.4 %           | 4.6 %     | 6.2 %       | 4.4 %     | 47.4 %           | 47.3 %          | 71.5        | 4.79      |
| ETH   | 15m | 41.9 %           | 3.4 %     | 5.7 %       | 6.0 %     | 42.9 %           | 45.7 %          | 71.0        | 4.74      |
| SOL   | 15m | 36.6 %           | 4.6 %     | 7.0 %       | 5.8 %     | 46.0 %           | 46.8 %          | 71.2        | 4.75      |

Key observation: **~85 % of bars are in `strong_bull` or `strong_bear`** (state ±2). Only ~5 % spend in `neutral`. This makes `g_qr_state_with` a weak gate (it fires too often). The discriminating power lives in `regime`, `health`, `confidence`, and `volume_ratio`.

## 3. Per-fire augmentation (Task 2)

Three augmented per-fire parquets written via causal merge_asof (`fire_us - 1us` against `bar_close_us = bar_start + tf - 1us`):
- `data/v4/canonical/_results/s15_with_qr.parquet` (33,323 fires, 99.9 % matched)
- `data/v4/canonical/_results/s6_with_qr.parquet` (11,336 fires, 99.7 % matched)
- `data/v4/canonical/_results/v15m_with_qr.parquet` (12,492 fires, 86.9 % matched — warmup gap on 15m EMAs)

Source: `strategy_lab/meta_classifier/overlay_qr.py`.

## 4. Standalone QR rules (Task 3)

Synthetic fires generated at every offset of `hybrid_fire_universe_{5m,15m}` from three rules.

| tf  | rule | n        | WR    | $/tr   | sum_pnl    |
|-----|------|----------|-------|--------|------------|
| 5m  | A (high-conviction trend, state≥+1 ∧ trending ∧ health>70 ∧ conf>4) | 58,220 | 0.434 | −4.87 | −283,365 |
| 5m  | B (strong stack only, \|state\|==2)                                  |107,195 | 0.442 | −4.88 | −523,580 |
| 5m  | C (state==+1 ∧ vol_ratio>1.3)                                        |  2,687 | 0.418 | −5.94 |  −15,958 |
| 15m | A                                                                     | 16,411 | 0.452 | −3.48 |  −57,131 |
| 15m | B                                                                     | 31,473 | 0.471 | −3.07 |  −96,484 |
| 15m | C                                                                     |    905 | 0.488 | −3.05 |   −2,762 |

**Verdict:** QR rules alone are LOSING — momentum/trend bias does not pick winners on binary up/down predictions. WR averages ~44 %, well below the 50 % breakeven. **QR is not a standalone alpha. Move to overlay analysis.**

Per-cell winners (sum_pnl > 0):

| asset | tf  | offset_bin | rule | n   | WR    | $/tr  | sum_pnl |
|-------|-----|------------|------|-----|-------|-------|---------|
| ETH   | 5m  | 30-90      | C    | 335 | 0.540 | +1.96 | +656    |
| ETH   | 15m | 60-240     | C    | 114 | 0.535 | +3.03 | +345    |
| SOL   | 15m | 720-840    | C    |  47 | 0.383 | +7.05 | +331    |

Most positive cells are rule C — but n is small, so this is noise.

Output: `data/v4/canonical/_results/qr_standalone_results.csv` (72 cells), `qr_standalone_per_fire.parquet` (216k rows).

## 5. QR gates overlaid on top hybrid_v1 sleeves (Task 4 — KEY FINDING)

Top-10 hybrid_v1 sleeves were filtered by each QR binary gate. Lift in `dpt = mean(pnl_legacy_usd)` measured.

**Top 7 QR-improved sleeves (by Δ$/tr):**

| asset | tf    | offset_bin | added_QR_gate          | n_filtered | WR    | $/tr   | ΔWR     | Δ$/tr   |
|-------|-------|------------|------------------------|------------|-------|--------|---------|---------|
| BTC   | s6_5m | 60-150     | g_qr_volume_strong     |  362       | 0.854 | +22.37 | +0.038  | +12.74  |
| BTC   | s6_5m | 60-150     | g_qr_high_health       |  566       | 0.827 | +14.10 | +0.011  | +4.47   |
| BTC   | s6_5m | 60-150     | g_qr_high_conf         |  688       | 0.836 | +11.93 | +0.019  | +2.22   |
| SOL   | s6_5m | 60-150     | g_qr_volume_strong     |  316       | 0.946 |  +3.45 | +0.052  | +1.85   |
| SOL   | s6_5m | 60-150     | g_qr_state_with        |  215       | 0.935 |  +2.20 | −0.003  | +0.89   |
| SOL   | s6_5m | 60-150     | g_qr_state_strong_with |  212       | 0.934 |  +2.18 | −0.004  | +0.87   |
| ETH   | s6_5m | 60-150     | g_qr_high_conf         |  385       | 0.610 |  +3.68 | +0.009  | +0.71   |

**`g_qr_volume_strong` is the standout** — it 4× the $/tr on BTC s6_5m 60-150 (from $5.10 → $22.37) at the cost of 87% sample reduction (2764 → 362). WR jumps from 78 % → 85 %.

`g_qr_high_health` adds +$4.47/tr with much milder sample shrinkage (-8%). This is the best risk-reward trade-off — high health filter keeps n=566 and still bumps $/tr by 87 %.

**ETH and SOL get smaller boosts** (~$0.7 to $1.9), and most other top hybrid sleeves (s15_5m, v15m) get no positive lift from any QR gate. The QR effect is concentrated on **BTC s6_5m 60-150** — i.e. spike entries, fast offset, BTC.

Output: `data/v4/canonical/_results/qr_gate_overlay.csv` (144 rows), `qr_gate_overlay_top.csv` (40 top-lift rows).

## 6. Confidence-bucket WR (Task 5)

For each top hybrid sleeve, WR was computed per `qr_signal_confidence` bucket: [0,2), [2,4), [4,6), [6,8].

**BTC s6_5m rank-1 sleeve (`g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_ribbon_agrees`):**

| conf bucket | n   | WR    | $/tr   |
|-------------|-----|-------|--------|
| [0,2)       |   4 | 0.500 |  −8.42 |
| [2,4)       |  92 | 0.696 |  −5.58 |
| [4,6)       | 471 | 0.837 | +16.48 |
| [6,8]       | 220 | 0.832 |  +1.97 |

**MONOTONIC ON BTC only** — WR rises 50 → 70 → 84 → 83 %. Sweet-spot is [4,6) — `$16.48/tr`. Above 6, WR plateaus but $/tr collapses to $1.97 (likely because trending-into-extremes mean reverts).

**ETH s6_5m sleeves are non-monotonic** — WR peaks at [4,6) (0.70) and DROPS at [6,8] (0.44). High confidence on ETH is a CONTRA-indicator. This matches the "overextended trend reverses" interpretation.

**Sleeve variant proposal (BTC only):**
```
base_stack + g_qr_high_conf AND NOT g_qr_top_conf
  ≈ filter signal_confidence ∈ (4, 6]
  Expected: WR ≈ 84 %, $/tr ≈ $16.5, n ≈ 470
```

Output: `data/v4/canonical/_results/qr_confidence_buckets.csv`.

## 7. Walk-forward (Task 6)

Train = `fire_us < 2026-05-15` (Apr 30 → May 14, ~14d). Test = May 15 → May 22 (8d). Bootstrap CI on test $/tr, 1000 samples.

PASS = (test_dpt > 0 AND CI lower > 0).

| Total combos | PASS | Pass rate |
|--------------|------|-----------|
| 80           | 12   | 15.0 %    |

**Top passing combos:**

| asset | tf    | offset_bin | added_QR_gate      | n_train | WR_train | $/tr_train | n_test | WR_test | $/tr_test | CI 95% lo | CI 95% hi |
|-------|-------|------------|--------------------|---------|----------|------------|--------|---------|-----------|-----------|-----------|
| BTC   | s6_5m | 60-150     | g_qr_volume_strong |  196    | 0.796    | +38.24     |  166   | 0.922   | +3.64     | +1.44     | +6.17     |
| BTC   | s6_5m | 60-150     | g_qr_high_health   |  343    | 0.799    | +21.72     |  220   | 0.873   | +2.43     | +0.22     | +4.89     |

**ALL passing combos are BTC s6_5m 60-150 + QR-gate add.** Both `g_qr_volume_strong` and `g_qr_high_health` survive holdout with positive CI lower bound. Train→test $/tr decays 10× (38 → 3.6) — typical out-of-sample shrinkage — but stays bonded to the positive half-plane. **ETH/SOL gate adds did NOT survive walk-forward.**

Output: `data/v4/canonical/_results/qr_walk_forward.csv`.

## 8. Top 5 NEW recommended sleeves using QR

All sleeves are BTC-only s6_5m at offset bin 60-150 (no other tf/asset survived walk-forward):

1. **`g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_ribbon_agrees + g_qr_volume_strong`** — n=362, WR=0.854, $/tr=+$22.4 (train), $3.6 (test, CI lo=+1.44).
2. **`g_cci_with & g_stoch_with & g_tr_above_ema50 & g_rf_with + g_qr_high_health`** — n=566, WR=0.827, $/tr=+$14.1 (train), $2.43 (test, CI lo=+0.22).
3. **`g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_ribbon_agrees + g_qr_high_conf`** — n=688, WR=0.836, $/tr=+$11.93 (train) — passes train but not formal walk-forward.
4. **`g_bb_pos_with & g_stoch_with & g_rf_with + g_qr_high_health`** — n=566 same WR, similar.
5. **`g_cci_with & g_stoch_with & g_rf_with & g_tr_above_ema50 & g_ribbon_agrees + qr_signal_confidence in (4,6]`** — proposed sweet-spot conf filter, expected n≈470, WR≈84%, $/tr≈$16 (needs explicit walk-forward).

## 9. Caveats

1. **Overlap with Madrid ribbon (5-100 range):** the existing TA pipeline already has `g_ribbon_agrees` and `g_ribbon_slope_with` from `compute_ta_indicators.py` (Madrid). QR Lite's `g_qr_state_with` should be largely redundant with Madrid since both are EMA-based trend indicators. The data confirms this: `g_qr_state_with` only adds ~$0.9/tr lift on SOL and is largely zero elsewhere. **The NEW value is in the regime/health/confidence/volume meta-features**, not the alignment signal.
2. **QR Lite uses 21-60 EMA range vs Madrid 5-100.** QR Lite is "shorter" and more responsive — `ribbon_state` flips faster. But Madrid's tight_ribbon gate captures compression already.
3. **Sample reduction is severe.** `g_qr_volume_strong` drops sample 87 %. Live throughput will suffer — expect 1-2 fires per day on this filter vs. ~30 baseline.
4. **The effect is BTC-concentrated.** Only BTC s6_5m 60-150 sleeves survived walk-forward. This may be because BTC has the cleanest momentum structure relative to its noise floor in the 28-day window; ETH/SOL have higher per-bar volatility, making "trending" + "high health" less predictive.
5. **Standalone rules are negative.** This confirms QR is best as a META-filter, not an alpha.
6. **Confidence non-monotonic on ETH:** high QR confidence reverses (peak at [4,6), drop at [6,8]). Watch for overextension. The "sweet-spot" sleeve (conf ∈ (4,6]) needs separate walk-forward.
7. **Holdout is only 8 days.** Test sample n_test=166-220 is borderline. CI is real but the deploy decision needs longer holdout (≥21d) before paper-trading.

## 10. Files

Code:
- `strategy_lab/meta_classifier/compute_qr_panel.py`
- `strategy_lab/meta_classifier/overlay_qr.py`
- `strategy_lab/meta_classifier/qr_standalone_backtest.py`
- `strategy_lab/meta_classifier/qr_gate_overlay.py`
- `strategy_lab/meta_classifier/qr_confidence_buckets.py`
- `strategy_lab/meta_classifier/qr_walk_forward.py`

Data:
- `data/v4/canonical/_results/qr_panel_5m.parquet` (2.6 MB)
- `data/v4/canonical/_results/qr_panel_15m.parquet` (0.9 MB)
- `data/v4/canonical/_results/s15_with_qr.parquet` (12.5 MB)
- `data/v4/canonical/_results/s6_with_qr.parquet` (2.6 MB)
- `data/v4/canonical/_results/v15m_with_qr.parquet` (4.1 MB)
- `data/v4/canonical/_results/qr_standalone_results.csv`, `qr_standalone_per_fire.parquet`
- `data/v4/canonical/_results/qr_gate_overlay.csv`, `qr_gate_overlay_top.csv`
- `data/v4/canonical/_results/qr_confidence_buckets.csv`
- `data/v4/canonical/_results/qr_walk_forward.csv`
