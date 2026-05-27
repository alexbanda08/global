# V7 Sniper — BTC 15m (3rd retry, focused)

**Date:** 2026-05-27
**Scope:** 3 focused experiments on the V6 winner sleeve.
**Panel:** `data/v4/canonical/_results/sniper_btc15m_v7_gated.parquet` (32,989 fires after vwap filter, 33d Apr 24 → May 26)
**Splits:** train 18d / val 6d / lock 4d. Lock = May 22 → May 26.
**Stake:** constant $25. **Fee:** 2%-on-profit (LegacyConfig).
**Anchor:** offset_600s, DOWN, V6 winner = `g_tr_above_ema200 + g_mp_skew_strong_with + g_rf_with`

## TL;DR

V6 baseline replicated exactly (n=34, WR=85.3%, $/tr=+$11.81, DD=$71.7, p=0.001).
**No experiment beats V6 on `obj = $/tr × sqrt(n)`.** Two experiments raise $/tr but cost too many fires.
**No sleeve meets the strict V7 bar** (val-window $/tr is the binding constraint for V6/Exp3).

## Top 4 candidates (incl. baseline)

| # | sleeve | n_tr / n_va / n_lo | WR_lo | $/tr_lo | DD_lo | LS | Sharpe | bs_p | obj | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **V6_baseline** | 202 / 71 / 34 | 0.853 | +$11.81 | $71.7 | 2 | 22.9 | 0.001 | 68.84 | reference |
| 2 | V7_exp3_+eth_slope_with | 90 / 33 / 15 | 0.867 | +$15.58 | $25.0 | 1 | 20.1 | 0.001 | 60.35 | higher $/tr & WR but val $/tr = −$1.17 |
| 3 | V7_exp2_+parent_1h_ranging | 112 / 53 / 18 | 0.833 | +$13.33 | $36.8 | 1 | 11.1 | 0.061 | 56.55 | val $/tr OK but bs_p just over 0.05 |
| 4 | V7_exp1_+hurst_reverting | 6 / 3 / 0 | — | — | — | — | — | — | 0 | gate orthogonal to V6 — only 6 train fires |

## Experiment-by-experiment

### Exp 1 — V6 winner + `g_hurst_reverting` (hurst_300s < 0.40)
- **Fail.** V6 winner already encodes "trend coherent" via `g_tr_above_ema200` + `g_rf_with`. `hurst_reverting` (mean-reversion regime) is the inverse of what V6 selects. Only 6 train fires, 0 lockbox. **Not deployable.**

### Exp 2 — V6 winner + `g_parent_1h_ranging` (|BTC 1h dev from SMA20| < 0.5%)
- Built from binance 1m spot-ws → 1h aggregate (full window, fire rate = 54%). Direction-agnostic regime filter.
- **Partial win on $/tr:** lockbox $/tr rises from +$11.81 → +$13.33, DD drops from $71.7 → $36.8.
- **Costs n:** 34 → 18 fires (47% fewer).
- **bs_p = 0.061** misses 0.05 cutoff (only 4 unique lockbox days; daily bootstrap is noisy at low n).
- Train and val both positive ($/tr = +2.60 / +1.09) — most stable of the experiments.
- **Insight:** the V6 winner does extra well in ranging-1h regimes. Worth retesting once the lockbox window expands (n=18 in 4d ≈ 126 per 28d).

### Exp 3 — V6 winner + `g_eth_slope_with` (ETH 15m 30-min slope sign-aligned with direction)
- Built from binance 1m spot-ws → 15m aggregate. Direction-aware (DOWN fires require ETH 30m slope < 0).
- **Best $/tr** of the four sleeves: lockbox $/tr = +$15.58, WR = 86.7%, DD = $25, LS = 1, p = 0.001.
- **Costs n:** 34 → 15 (56% fewer).
- **Val $/tr = −$1.17** — does NOT meet V7 strict bar (train+val+lock all positive). Same flaw as V6 baseline (val = −$0.68), arguably no worse.
- **Insight:** cross-asset ETH→BTC confirmation tightens the win path. Holds on out-of-sample lockbox; sample size for val is the only blocker.

## Comparison vs V6 best

| Metric | V6 winner | Best V7 ($/tr) — Exp3 | Best V7 (stability) — Exp2 |
|---|---|---|---|
| Lockbox n | 34 | 15 | 18 |
| Lockbox WR | 85.3% | 86.7% (+1.4 pp) | 83.3% (−2.0 pp) |
| Lockbox $/tr | +$11.81 | +$15.58 (**+$3.77**) | +$13.33 (**+$1.52**) |
| Lockbox sum 28d | $2,810 | $1,636 (**−$1,174**) | $1,679 (**−$1,131**) |
| Max DD | $71.7 | $25.0 (−65%) | $36.8 (−49%) |
| Train $/tr | +$2.01 | +$3.64 | +$2.60 |
| Val $/tr | −$0.68 | −$1.17 | **+$1.09** |
| bs_p | 0.001 | 0.001 | 0.061 |
| obj = $/tr × √n | 68.84 | 60.35 | 56.55 |

**Bottom line:** V6 winner remains the dollar-maximizing sleeve. Experiments improve fire-quality (WR/DD/$/tr) but the gate-adding shrinks n harder than it lifts mean PnL, so 28-day sum drops ~$1.1k. No sleeve clears the V7 bar (train+val+lock all-positive).

## Recommendation

- **Deploy V6 winner unchanged.** Treat Exp 2 / Exp 3 as candidate stake-modulators rather than independent sleeves: when both V6 fires AND Exp2/Exp3 fire, the win odds and PnL conditional are higher — could justify 1.25× stake on confluence within the V6 sleeve.
- Add `g_parent_1h_ranging` and `g_eth_slope_with` to the panel for future combinatorial searches (Exp1 not worth keeping — orthogonal to trend stack).
- Re-test Exp 2 and Exp 3 once the lockbox window grows; current 4d lock yields only 4 unique days, which is borderline for bootstrap.

## Files

- `top_5_candidates_v7.csv` — 4 sleeves (baseline + 3 experiments)
- `plots/v7_focused_comparison.png` — 4-line cumulative PnL on lockbox
- `scripts/06_focused_experiments.py` — reproducible end-to-end script
