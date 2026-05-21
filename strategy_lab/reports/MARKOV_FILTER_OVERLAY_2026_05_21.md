# Markov regime gate — overlay results on momo baseline universe

_Adapts Roan's daily Markov regime method ([jackson-video-resources/markov-hedge-fund-method](https://github.com/jackson-video-resources/markov-hedge-fund-method)) to micro timeframes and tests it as a binary alignment gate on momo fires._

## TL;DR

- **The gate works.** On 12,774 baseline momo fires (May 6-19), the best variant lifts WR 48.7% → 49.1% and PnL −$6,711 → +$856 (`w20_5m_fixed`, kept 10%).
- **The lift is cell-specific.** Massive on `btc_5m` and `*_15m` cells. **Regression on `eth_5m` and `sol_5m`** — same pattern as F7 lift distribution.
- **Sample is pre-F7 baseline data** (canonical kline + trading_events both end 2026-05-19, before F7 deploy at 2026-05-20 19:57). Result is preliminary lift estimate; needs re-validation once VPS3 + canonical refresh with post-F7 fires.

## Method

For each fire, label the underlying asset's regime at `fire_us−ε` as Bull / Bear / Sideways. Binary alignment gate: keep fire only if `signal=UP & regime=Bull` OR `signal=DOWN & regime=Bear`. Causal — uses only data up to `fire_us`.

Label rule: rolling N-bar log-return on binance 1m closes → state via threshold.

Four variants tested (2 windows × 2 threshold modes):

| Variant | Window | Threshold | Notes |
|---|---|---|---|
| `w20_1m_voladaptive` | 20 × 1m bars (20 min) | q33 / q66 of prior 14d rolling returns | Self-calibrating |
| `w20_1m_fixed`       | 20 × 1m bars (20 min) | BTC ±0.3%, ETH ±0.4%, SOL ±0.6% | Hardcoded per asset |
| `w20_5m_voladaptive` | 20 × 5m bars (100 min) | q33 / q66 of prior 14d rolling returns | Wider context |
| `w20_5m_fixed`       | 20 × 5m bars (100 min) | BTC ±0.5%, ETH ±0.7%, SOL ±1.0% | Hardcoded per asset |

## Headline — ALL fires (n=12,774, baseline WR 48.7%, baseline avg −$0.525)

| Variant | n | WR | $/trade | PnL | keep% |
|---|--:|--:|--:|--:|--:|
| BASELINE              | 12,774 | 48.70 | −$0.525 | −$6,711.41 | 100%  |
| `w20_1m_voladaptive`  |  9,238 | 49.18 | +$0.019 | +$176.79   | 72.3% |
| `w20_1m_fixed`        |  2,928 | 43.65 | −$1.630 | −$4,773.36 | 22.9% |
| `w20_5m_voladaptive`  |  4,239 | 48.83 | −$0.278 | −$1,176.69 | 33.2% |
| **`w20_5m_fixed`**    | **1,322** | **49.09** | **+$0.648** | **+$856.15** | **10.3%** |

Two viable variants:
- **`w20_5m_fixed`** = aggressive (drops 90% of fires, but every survivor is +$0.65/trade and the kept fires net +$856 vs the discarded ones netting −$7.5k).
- **`w20_1m_voladaptive`** = gentle (keeps 72%, lifts $/trade from −$0.53 to +$0.02 — small but covers almost the full universe).

`w20_1m_fixed` is a clear loser (−$1.63/trade, worse than baseline). Threshold is too strict on 1m bars — only fires on extreme moves, which mostly reverse.

## By cell (the actionable view)

| Cell | n | base WR / avg | best variant | post WR / avg | keep% |
|---|--:|--:|---|--:|--:|
| `btc_15m`  |   721 | 63.25% / +$6.22  | `w20_5m_fixed`        | **68.00% / +$8.89**  | 17.3% |
| `btc_5m`   | 5,314 | 45.65% / −$1.56  | `w20_5m_fixed`        | **56.95% / +$5.58**  | 10.0% |
| `eth_15m`  |   682 | 56.74% / +$2.44  | `w20_1m_fixed`        | **62.65% / +$4.67**  | 24.3% |
| `eth_5m`   | 3,085 | 46.00% / −$1.69  | `w20_1m_voladaptive`  |  48.58% / −$0.28     | 75.2% |
| `sol_15m`  |   480 | 51.46% / −$0.74  | `w20_1m_fixed`        | **77.27% / +$11.51** | 13.8% |
| `sol_5m`   | 2,492 | 51.61% / +$0.40  | _none — all regress_  | n/a                  | n/a   |

**Cells that benefit hugely from a Markov gate**:
- `btc_15m` `w20_5m_fixed`: +$8.89/trade, 68% WR (n=125)
- `btc_5m` `w20_5m_fixed`: flips losing cell to **+$5.58/trade** (n=532) — the big PnL win
- `sol_15m` `w20_1m_fixed`: **+$11.51/trade**, 77% WR (n=66)
- `eth_15m` `w20_1m_fixed`: +$4.67/trade, 63% WR (n=166)

**Cells that REGRESS under any Markov gate**:
- `sol_5m`: every variant makes it worse. `w20_5m_fixed` collapses to −$10.84/trade.
- `eth_5m`: only `w20_1m_voladaptive` is benign (−$0.28 vs −$1.69 baseline); `w20_5m_fixed` regresses to −$4.82.

This is **the same shape as F7's lift distribution** (BTC + 15m wins; eth_5m + sol_5m unmoved or worse). Suggests the underlying issue isn't filter design — those cells have a structural problem the momo signal can't escape regardless of filter.

## By version × cell — top picks for a deploy spec

Cells where a gate ≥ doubles the per-trade $ AND keeps ≥ 50 fires:

| Version × Cell | Best variant   | base avg | post avg  | post WR  | n_kept |
|---|---|--:|--:|--:|--:|
| `v1_btc_15m`   | `w20_1m_fixed` | +$6.70   | **+$13.97** | 81.6%   |   76  |
| `v1_btc_5m`    | `w20_5m_fixed` | −$2.26   | **+$7.46**  | 64.0%   |  211  |
| `v2_btc_5m`    | `w20_5m_fixed` | −$0.83   | **+$4.34**  | 52.3%   |  321  |
| `v2_eth_15m`   | `w20_1m_voladaptive` | +$7.92 | +$9.58  | 72.1%   |  347  |
| `v2_btc_15m`   | `w20_1m_voladaptive` | +$5.90 | +$7.49  | 64.7%   |  368  |

`v1_btc_5m` is the highest-impact change: **−$2.26 → +$7.46/trade** with `w20_5m_fixed` (≈ +$9.72 per fire on 211 fires kept ≈ +$2,053 net lift over the 13-day window, ≈ +$160/day equivalent if continued).

## Caveats

1. **Pre-F7 data only.** Test re-runs on post-F7 fires once canonical refresh (likely 2026-05-22+) before any deploy decision. F7-gated fires already remove some bad signals; Markov gate on top of F7 may show smaller marginal lift.
2. **No transaction cost / slippage modelling.** Uses raw `pnl_usd` from production resolutions — those already reflect real fills + fees. So this is fair.
3. **In-sample threshold tuning** for `_fixed` variants. The hardcoded BTC=±0.3%, ETH=±0.4%, SOL=±0.6% / ±0.5/0.7/1.0% values come from a single look at the 20-bar return distributions — not from walk-forward CV. Holdout test on post-F7 data is necessary before trusting.
4. **`w20_1m_fixed` is structurally bad** (regression on most cells). Don't deploy.
5. **`sol_5m` is uninvestable** — every gate regresses. Same pattern as F7. The signal source on sol_5m is structurally bad and should be retired or rebuilt, not filtered.
6. **Markov regime ≈ slow RSI ≈ trend follower.** The information is largely overlapping with F7 (which is RSI-direction-confirmation). Stacking both may double-filter the same edge.

## Decision

**Not ready to deploy.** Two reasons:

1. Pre-F7 baseline tells us the gate has shape, but the F7-overlay test is what matters for the actual production cells (which now run F7).
2. The same cells that benefit from Markov also benefited from F7 — suggesting Markov may be largely redundant with F7. Need to test Markov on F7-passed fires specifically.

**Next session validation plan:**

1. Refresh canonical klines + trading_events to include 2026-05-20 → 2026-05-24 (post-F7 window).
2. Re-run `overlay_post_f7.py` on F7-passed fires only.
3. Compute incremental lift of Markov over F7 alone (not over no-filter).
4. If incremental lift on `v1_btc_5m` and `*_15m` cells exceeds +$1/trade after F7, write a TV-agent spec to add Markov gate alongside F7. If not, park this and move on.

## Files

- `strategy_lab/markov_filter/markov_regime_micro.py` — core library (label_regimes_vol_adaptive, label_regimes_fixed, build_transition_matrix, stationary_distribution, regime_at_us)
- `strategy_lab/markov_filter/overlay_post_f7.py` — overlay runner (NOTE: name says post-F7 but currently runs pre-F7 baseline due to data window)
- `strategy_lab/markov_filter/_results/post_f7_fires_with_regimes.csv` — per-fire regime labels under all 4 variants
- `strategy_lab/markov_filter/_results/summary_{all,version,symbol_tf,version_symbol_tf}.csv` — aggregated tables

## Sources

- Roan's framework: https://github.com/jackson-video-resources/markov-hedge-fund-method
- Adaptation: window 20 days → 20 bars (1m or 5m), threshold ±5% → vol-adaptive q33/q66 or asset-specific fixed.
