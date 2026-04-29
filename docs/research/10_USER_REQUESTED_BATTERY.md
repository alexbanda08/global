# 10 — User-Requested Cells: Full Battery

**Date:** 2026-04-24
**Driver:** [strategy_lab/run_user_requested_battery.py](../../strategy_lab/run_user_requested_battery.py)
**Raw:** [docs/research/phase5_results/user_requested_battery.json](phase5_results/user_requested_battery.json)

## Results summary

| Cell | Sharpe | Calmar | MDD | 2022 | 2023 | 2024 | Phase-5 | Robust | Plateau | **5-test** |
|---|---:|---:|---:|---:|---:|---:|---:|---:|:---:|---:|
| SOL_BBBreak_LS | −0.22 | −0.67 | −29.3% | −1.30 | +2.77 | +0.68 | 1/7 | 2/7 | ❌ | 2/8 |
| DOGE_TTM_Squeeze_Pop | +0.03 | −0.41 | −55.3% | +0.35 | +1.08 | +0.81 | 1/7 | 3/7 | ❌ | 3/8 |
| SOL_SuperTrend_Flip | −0.39 | −0.63 | −56.9% | −1.68 | +2.23 | +0.79 | 1/7 | 0/7 | ✅ | 1/8 |
| **DOGE_HTF_Donchian** | **+1.53** | **+3.31** | **−43.0%** | **+0.38** | **+0.62** | **+1.97** | 2/7 | 3/7 | **✅** | **4/8** |
| ETH_CCI_Extreme_Rev | +0.17 | −0.10 | −37.1% | +0.21 | +0.39 | +0.09 | 1/7 | 2/7 | ❌ CLIFF | 2/8 |

## Key findings

### DOGE_HTF_Donchian — joint leader with volume_breakout ETH

Matches volume_breakout ETH at **4/8 tests**, adds a stronger *headline* Sharpe of +1.53 and Calmar +3.31. **Per-year Sharpe positive every year** (0.38 / 0.62 / 1.97) AND plateau test passed cleanly (worst 50% drop only 26.3%, no cliffs). Main weakness: **−43% max drawdown** — fails Phase-5's MDD < 20% gate. The signal has edge but with dangerous risk.

### ETH_CCI_Extreme_Rev — overfit warning

Plateau cliff detected. Sharpe at ±50% of params collapses by 383.8% (real number) vs baseline. This is a parameter-space peak, not a plateau — classic one-point overfit. Per-year Sharpe also near-zero in 2024 (+0.09), suggesting the strategy's edge is fading.

### DOGE_TTM_Squeeze_Pop — positive per-year but losing money

Per-year Sharpe positive in all 3 years (+0.35 / +1.08 / +0.81), yet aggregate Sharpe is only +0.03 and max DD is **−55.3%**. This means within-year drawdowns are chewing up the edge — the strategy is consistently positive over annual windows but has brutal intra-year dispersion. Plateau failed.

### SOL_BBBreak_LS, SOL_SuperTrend_Flip — 2022 blowups

Both strategies had catastrophic 2022 Sharpe (−1.30, −1.68) that 2023 bounces didn't recover. SuperTrend_Flip's 0/7 robustness is the worst result in the whole audit.

## Unavailable cells

| Cell | Reason |
|---|---|
| SUI BBBreak_LS | SUI not in 10-symbol parquet universe — need fetcher to add |
| TON BBBreak_LS | Same |
| V24_MF_1x | Portfolio-config label (multi-freq 1x leverage variant of V24 regime router) — not a bare signal function; runs inside `run_v24_regime_router.py` via a specific config block. Needs a per-config adapter. |
| _5SLEEVE_EQW | Equal-weight 5-sleeve portfolio — aggregates 5 signals into one equity curve. Runs inside `run_v29_portfolio.py` / similar. Again per-config adapter needed. |

## Promotion-candidate shortlist (updated)

Combining this batch with prior runs, exactly **two** cells now stand on joint leadership at 4/8:

| Cell | Strength | Weakness | Next |
|---|---|---|---|
| **volume_breakout ETH 4h** | Per-year +, plateau ✅, Sharpe +0.73 | Bootstrap CI still straddles 0 | Tune `vol_mult=1.87` |
| **DOGE_HTF_Donchian 4h** | Per-year +, plateau ✅, Sharpe +1.53 | MDD −43% fails risk gate | Add SL/TSL overlay |

Both are your legacy strategies (neither is one I wrote). volume_breakout is safer; DOGE_HTF_Donchian has more headline PnL but a risk problem.

## Suggested next moves

1. **Add a 2× ATR stop-loss to DOGE_HTF_Donchian** and rerun the battery. If MDD drops below 20% without killing Sharpe, it's the strongest promotion candidate in the mission.
2. **Add SUI / TON to the parquet via a fetcher run** if they matter to you (one-shot `fetch_binance_multi.py` invocation with `BASE_COINS=SUIUSDT,TONUSDT`).
3. **Wire `V24_MF_1x` and `_5SLEEVE_EQW`** — requires reading the specific run scripts and extracting the config block. 1-2 turns per adapter.
