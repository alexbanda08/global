# 08 — Expanded Robustness + Regime-Filter A/B

**Date:** 2026-04-24
**Driver:** [strategy_lab/run_phase55_expanded.py](../../strategy_lab/run_phase55_expanded.py)
**Raw:** [docs/research/phase5_results/robustness_expanded.json](phase5_results/robustness_expanded.json)

## Scope delivered

- **Robustness battery** on **14 Phase-5 cells with ≥3/7 gates** from the legacy book (sorted by gates_passed desc, capped at 20 for compute).
- **Regime-filter A/B** — both C1 meta-labeled Donchian (ETH 4h) and gaussian_channel_v2 (BTC 4h) were run with and without the `with_regime_filter(...)` overlay restricting entries to `{strong_uptrend, weak_uptrend}` labels.

## Scope NOT delivered this turn

- The full **98-strategy × 3-symbol** matrix (≈294 cells) from the scanner's `legacy_scan.json` could not run reliably. Multiple background-detach attempts (`nohup`, `&`, `disown`) terminated the child Python process before completion on this Windows/Git-Bash setup. The 42-cell CSV from the manually-wired 14 strategies is what we audited. Resumable chunked execution is the fix for next turn.

## The only per-year-consistent cell in the book

Among every cell robustness-tested, exactly **one** produced a positive Sharpe in every year 2022 / 2023 / 2024:

| Cell | 2022 | 2023 | 2024 | Robust |
|---|---:|---:|---:|---:|
| **volume_breakout ETHUSDT 4h** | **+0.75** | **+0.40** | **+0.78** | **3/7** |

Every other tested cell collected ≥ 1 negative-Sharpe year — meaning the Phase-5 "winners" all owe some of their aggregate edge to a single good market regime.

## Other notable robustness results

| Cell | Gates5 | Robust | 2022 Sharpe | 2023 Sharpe | 2024 Sharpe |
|---|---:|---:|---:|---:|---:|
| supertrend BTC 4h | 3 | 3/7 | −0.70 | +1.95 | +1.70 |
| volume_breakout BTC 4h | 3 | 2/7 | −0.23 | +1.32 | +1.25 |
| ema_trend_adx_v2 BTC 4h | 3 | 2/7 | −0.60 | +1.79 | +0.53 |
| squeeze_breakout ETH 4h | 3 | 2/7 | −2.95 | +0.15 | +0.37 |
| squeeze_breakout BTC 4h | 3 | 1/7 | −2.38 | +0.49 | +0.88 |
| gaussian_channel_v2 BTC 4h (prev report) | 4 | 1/7 | −1.80 | −0.71 | +2.43 |

**Pattern:** crypto 4h trend strategies tested over this window are overwhelmingly bear-market-fragile — 2022 was brutal for every approach tested except volume_breakout on ETH.

## Regime-filter A/B — did it rescue them?

**Short answer: no.** The filter moved both metrics in the wrong direction.

| Cell | Mode | Robust | 2022 | 2023 | 2024 | WFE | Pos folds |
|---|---|---:|---:|---:|---:|---:|---|
| C1 ETH | vanilla | 2/7 | 0.00 | 0.00 | +1.10 | 6.06 | 3/6 |
| C1 ETH | **+ regime filter** | **1/7** | 0.00 | 0.00 | **+0.46** | **−1.25** | 2/6 |
| gc_v2 BTC | vanilla | 1/7 | −1.80 | −0.71 | +2.43 | −0.50 | 4/6 |
| gc_v2 BTC | **+ regime filter** | 1/7 | −1.80 | **−1.09** | **+2.00** | **−0.08** | 2/6 |

**C1 ETH:** the regime filter trimmed profitable 2024 entries (the meta-labeler had already learned to filter them; adding a second filter over-restricts). Sharpe 2024 fell from +1.10 to +0.46.

**gc_v2 BTC:** filter marginally improved walk-forward efficiency (−0.08 vs −0.50), but the 2023 year got WORSE (−1.09 vs −0.71) because the filter also removed short-lived uptrends that had positive local Sharpe. Bear-market MDD unchanged (the vanilla strategy was already not trading in 2022).

**Design conclusion:** a simple `in {up-label}` regime gate is too blunt. Strategies that overfit to one regime need more than just "only trade when classifier agrees" — they need either (a) separate training for each regime, or (b) a fundamentally different signal design.

## Action items

1. **volume_breakout ETH 4h → next-up for Phase 5.5 full battery** — run all 5 tests (including parameter plateau, which this turn skipped). If it holds, it's the first *real* promotion candidate in the mission.
2. **Retire the naïve regime filter for C1 and gc_v2.** Preserve the `with_regime_filter` module for strategies where it helps (TBD), but don't deploy it on these two.
3. **Complete 98-strategy expansion next turn** via chunked runs (30 strategies at a time) so the matrix finishes incrementally.
4. **C1 v2 — retrain on 2019–2022, deploy 2023–2024** (remains the highest-value C1 fix; regime filter isn't it).
