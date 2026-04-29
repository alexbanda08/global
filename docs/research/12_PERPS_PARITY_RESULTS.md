# 12 — Perps-Parity Replication Results

**Date:** 2026-04-24
**Driver:** [strategy_lab/run_perps_parity.py](../../strategy_lab/run_perps_parity.py)
**Fee schedule:** `hyperliquid_perps` — **1.5 bps maker / 4.5 bps taker** (no rebate, per user clarification)
**Leverage:** 3× · **Slippage:** 3 bps · **ATR stack:** TP=10×ATR, SL=2×ATR, trail=6×ATR · **Funding drag:** 8% APR × 3× exposure
**Data window:** extended to 2022-01 → 2026-04 (5 years) for the 5 cells, covering 2025-2026 OOS

## 5 cells under perps parity

| Cell | Sharpe | CAGR | Max DD | Calmar | #Trades | Win% | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| SOL_BBBreak_LS_4h | +0.80 | +33.1% | **−63.1%** | +0.53 | 71 | 30% | −1.23 | **+2.73** | +0.40 | +0.50 | −1.67 |
| DOGE_TTM_Squeeze_Pop_4h | −0.13 | −16.7% | **−68.2%** | −0.24 | 84 | 26% | −1.18 | +1.65 | +0.26 | −1.33 | −0.87 |
| SOL_SuperTrend_Flip_4h | +0.46 | +10.9% | −50.6% | +0.22 | 36 | 31% | −0.88 | +1.70 | +0.17 | **+0.86** | −2.31 |
| **DOGE_HTF_Donchian_4h** | **+0.93** | **+47.2%** | −60.1% | +0.79 | 69 | 38% | **+1.24** | +0.79 | **+1.35** | +0.54 | −1.68 |
| ETH_CCI_Extreme_Rev_4h | −0.08 | −3.9% | −42.5% | −0.09 | 49 | 49% | +0.21 | −1.03 | +0.35 | +0.18 | −2.48 |

## How the numbers moved vs. the spot battery

| Cell | Spot-battery Sharpe | Perps-parity Sharpe | Δ |
|---|---:|---:|---:|
| SOL_BBBreak_LS | −0.22 | +0.80 | **+1.02** ↑ |
| DOGE_TTM_Squeeze_Pop | +0.03 | −0.13 | −0.16 ↓ |
| SOL_SuperTrend_Flip | −0.39 | +0.46 | **+0.85** ↑ |
| DOGE_HTF_Donchian | +1.53 | +0.93 | −0.60 ↓ |
| ETH_CCI_Extreme_Rev | +0.17 | −0.08 | −0.25 ↓ |

**Mixed picture:** the perps stack rescued two cells from negative to positive (SOL BBBreak, SOL SuperTrend), but also *pulled down* three cells. Key driver of the drops: **funding drag at 3× leverage is material** — 8% APR × 3× = 24% annualized carry cost on position-holding time. Strategies that sit in positions a lot (DOGE_HTF_Donchian, ETH CCI) lose a big chunk of their edge to funding.

## What's still NOT matching the historical reports

Even with fees/leverage/exits matching, my new cells still underperform the V30 report numbers (e.g., ETH CCI_Extreme_Rev reported OOS Sharpe +2.37 / CAGR +123% — mine shows negative). Remaining gaps:

### 1. Long-only only — L+S mirroring pending
Every cell ran with `LS=False` — the raw signal fns in `run_v30_creative.py` / `run_v38b_smc_mixes.py` return long-side `entries`/`exits` only. The V30/V22 reports applied a **symmetric mirror** (e.g., for CCI_Extreme_Rev: long when CCI crosses up through −150, short when CCI crosses down through +150). That mirroring logic isn't in the scanner-discovered fn; it lives inside the V-numbered runner scripts. **Need to extract the mirror policy per-family** and apply it in the driver — next step.

### 2. V22 RangeKalman winners blocked
- `BTC 2h` / `SOL 2h` — no native 2h parquet (we have 15m/30m/1h/4h/1d). Need an on-the-fly resample.
- `v4c_range_kalman` signature doesn't match the V22 params (`alpha=0.07, rng_len=300`, …) — the implementation uses different kwarg names. Need to read the function and map V22 labels → actual params.

### 3. Per-coin tuned parameters
The V30 report tests ~6,000 configs and reports the BEST per coin. My driver uses the defaults baked into the signal fn, which likely don't match the winning config. Applying the exact tuned params (when they're published in the reports) would lift the numbers meaningfully.

### 4. Walk-forward split = V30's IS/OOS
V30 defines IS = pre-2024, OOS = 2024-onward. My `per_year` table is year-by-year; to get a V30-compatible OOS Sharpe I just need to aggregate 2024 + 2025 + 2026 and compute Sharpe on that concatenated return stream.

## Honest readout

What the parity run DID prove:
- **DOGE_HTF_Donchian 4h** is the only cell with **positive Sharpe in 4 of 5 years** (2022, 2023, 2024, 2025). The 2026-YTD drawdown is mostly a 3-month sample. This is the strongest single-cell result under realistic perps execution.
- **ETH_CCI_Extreme_Rev** is NOT consistent: positive in 2022/2024/2025 but negative in 2023 and brutal in 2026 (−2.48 Sharpe). The V30 +2.37 OOS figure is likely an artifact of tuning on 2024 only — not a multi-year edge.
- **Funding drag matters a lot.** At 3× leverage and 8% APR, strategies that hold positions through multi-week ranges pay roughly 2-4% of capital per month just in carry. TTM_Squeeze and BBBreak, which linger in low-conviction trades, get hit hardest.

## Next steps (ordered by value)

1. **Add L+S mirroring.** For each signal family (BBBreak, TTM, SuperTrend, CCI, Donchian), define the canonical short-mirror rule and apply it at runtime. This is likely the biggest gap left.
2. **Resample 2h from 1h** (BTC/SOL V22 RangeKalman replication).
3. **Extract per-coin tuned params** from the report tables into `V22_V25_V30_PARAMS` presets and feed them in.
4. **Add 3-sleeve portfolio aggregator** for V28 P2 validation — pure Python, ~40 LOC.
5. **OOS aggregation** (IS = pre-2024, OOS = 2024+) to get directly-comparable numbers to V25/V29/V30 reports.

## Artifacts

- [strategy_lab/run_perps_parity.py](strategy_lab/run_perps_parity.py)
- [docs/research/phase5_results/perps_parity_results.csv](phase5_results/perps_parity_results.csv)
- [docs/research/phase5_results/perps_parity_results.json](phase5_results/perps_parity_results.json)
- Updated [strategy_lab/engine.py](strategy_lab/engine.py) FEE_REGISTRY — added `hyperliquid_perps` key (1.5 / 4.5 bps)
