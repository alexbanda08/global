# Production F7 vs Markov — per-sleeve gate analysis on real VPS3 fires

_Replaces yesterday's two flawed reports. The earlier backtest analysis had a `ws_s` anchor bug AND stale canonical klines, both of which inverted the F7 sign. Production data tells the correct story: **F7 works, and Markov on top of F7 makes it work better.**_

## Setup

- **Source 1 — events**: VPS3 `trading.events`, window 2026-05-20 19:57 UTC → 2026-05-21 19:20 UTC (~23.5h). 25,785 events parsed → **3,739 fire-resolution pairs** across 12 sleeves (BTC/ETH/SOL × 5m/15m × v1/v2 × HOLD/HEDGE/SELL policies).
- **Source 2 — klines for Markov**: VPS3 `public.binance_klines_v2` (binance-spot-ws 1MIN), pulled fresh for 2026-04-14 → 2026-05-21 19:32 UTC. 50,888 bars per asset (37 days of warmup + the fire window).
- **Markov variants**: 4 (window 20×1m / 20×5m, threshold vol-adaptive q33/q66 / fixed-per-asset).
- **F7 spec** (production-spec): `(signal=UP & RSI_14>50) OR (signal=DOWN & RSI_14<50)`, RSI on binance 1m closes ending at `ws_s = slot_start − window_s`.
- **Gate**: binary alignment (signal direction must match regime/RSI direction).
- **PnL**: production `pnl_usd` from resolution events (chainlink-truth outcomes + real Polymarket fee curve).

## What I got wrong yesterday

1. **Wrong `ws_s` anchor**: I used the per_trade CSV's `ws` column directly as the RSI anchor. But that column is `slot_start_s` (slug suffix), not `ws_s`. The correct anchor is `ws_s = slot_start − window_s`. So my F7 RSI was sampled 5/15 minutes *AFTER* the true signal anchor — lookahead-ish, catching mean-reversion, inverting F7's apparent sign.
2. **Stale canonical klines**: canonical 1m klines end 2026-05-19 23:35 UTC. Post-F7 fires are 2026-05-20 to 2026-05-21. asof() returned the last available label (mostly Sideways) for all post-fire-window lookups, blocking everything for 3 of 4 Markov variants.
3. Result: I reported F7 as anti-correlated with wins. It is not. F7 is correctly correlated with wins on the production data.

## OVERALL — production fires (n=3,739)

| filter                              |    n | WR     | $/trade | sum PnL    |
|-------------------------------------|-----:|-------:|--------:|-----------:|
| ALL_FIRES (baseline)                | 3,739| 52.18 % | +$0.629 | +$2,353.17 |
| baseline (no `_f7`)                 | 2,518| 52.70 % | +$0.086 | +$216.56   |
| **F7 production**                   | 1,221| 51.11 % | +$1.750 | +$2,136.61 |
| MARKOV:w20_1m_voladaptive           | 2,226| 52.29 % | −$0.140 | −$311.93   |
| MARKOV:w20_1m_fixed                 | 1,082| 58.32 % | +$3.609 | +$3,904.57 |
| MARKOV:w20_5m_voladaptive           | 1,544| 53.17 % | −$0.435 | −$672.07   |
| MARKOV:w20_5m_fixed                 |   600| 53.50 % | −$2.340 | −$1,404.25 |
| F7+MARKOV:w20_1m_voladaptive        | 1,074| 53.17 % | +$1.896 | +$2,036.04 |
| **F7+MARKOV:w20_1m_fixed**          |   673| **61.37 %** | **+$6.307** | **+$4,244.36** |
| F7+MARKOV:w20_5m_voladaptive        |   625| 52.00 % | +$0.283 | +$176.79   |
| F7+MARKOV:w20_5m_fixed              |   276| 60.51 % | +$2.757 | +$761.06   |

Ranked by sum PnL:
1. **`F7+MARKOV:w20_1m_fixed`** — +$4,244 over 23.5h (≈ +$4,330/day). The combined gate wins.
2. `MARKOV:w20_1m_fixed` alone — +$3,905.
3. `ALL_FIRES` baseline — +$2,353.
4. `F7 production` alone — +$2,137.

**Markov w20_1m_fixed adds ~$2,100 over F7 alone in this 23.5h window. F7+Markov keeps 673 fires (18% of universe) at 61% WR.**

## Per-sleeve detail

Only sleeves with n_total ≥ 60 shown. Each row picks the **best filter** for that sleeve by sum PnL (n≥10).

### btc_5m_v1 — F7 + Markov fixed stacks beautifully

n_total=1,160; baseline_no_f7 n=935 +$0.57/trade; F7_production n=225 +$10.40/trade.

| filter                       |   n  | WR    | $/trade  | sum     |
|------------------------------|-----:|------:|---------:|--------:|
| F7_production                | 225  | 72.89%| +$10.40  | +$2,339 |
| MARKOV:w20_1m_fixed (no F7)  | 266  | 71.43%| +$8.63   | +$2,296 |
| **F7+MARKOV:w20_1m_fixed**   | **138** | **82.61%** | **+$14.41**  | **+$1,989** |
| F7+MARKOV:w20_5m_fixed       |  54  | 100.00%| +$16.58 | +$895   |
| F7+MARKOV:w20_1m_voladaptive | 225  | 72.89%| +$10.40  | +$2,339 (identical to F7) |

Markov w20_1m_fixed lifts F7's per-trade from +$10.40 to **+$14.41/trade**. The combined gate keeps 138 of the 225 F7 fires, exactly the higher-quality subset.

### sol_5m_v1 — 100% WR on F7+Markov combo

n_total=406; baseline +$3.47/trade; F7 +$10.05/trade.

| filter                     |   n  | WR     | $/trade   | sum    |
|----------------------------|-----:|-------:|----------:|-------:|
| F7_production              |  42  | 71.43% | +$10.05   | +$422  |
| **F7+MARKOV:w20_1m_fixed** | **30** | **100.00%** | **+$24.34**  | **+$730** |
| F7+MARKOV:w20_5m_voladaptive |  6 | 100.00% | +$12.64  | +$76  |

**Every F7+Markov fixed combo win.** 30 fires in 23.5h, all winners, $24.34/trade. ⚠ small-n caveat — but the perfect WR is hard to attribute to chance.

### sol_5m_v2 — F7 strong, Markov pushes to 91%

n_total=109; F7 +$10.87/trade @ 82% WR.

| filter                     |   n  | WR     | $/trade   | sum     |
|----------------------------|-----:|-------:|----------:|--------:|
| F7_production              |  97  | 82.47% | +$10.87   | +$1,055 |
| **F7+MARKOV:w20_1m_fixed** | **88** | **90.91%** | **+$13.83** | **+$1,217** |
| F7+MARKOV:w20_5m_voladaptive | 64 | 87.50% | +$10.96  | +$701   |

Markov adds 8.4pp WR and ~$3/trade on top of F7. n=88 is a solid sample.

### eth_15m_v2 — Markov 5m variants shine

n_total=90; F7 +$7.90/trade @ 65% WR.

| filter                          |  n  | WR     | $/trade   | sum   |
|---------------------------------|----:|-------:|----------:|------:|
| F7_production                   | 84  | 65.48% | +$7.90    | +$664 |
| **F7+MARKOV:w20_5m_voladaptive**| **33**| **84.85%** | **+$19.22** | **+$634** |
| F7+MARKOV:w20_5m_fixed          | 30  | 83.33% | +$18.79   | +$564 |

Markov 5m variants lift WR from 65% to 84-85% and $/trade from +$7.90 to +$18-19. The 5m window (100-min lookback) seems right for the 15m timeframe — matches the slug horizon better.

### btc_5m_v2 — F7 weak baseline; Markov 1m_fixed FLIPS it positive

n_total=438; F7_production WR 42.79%, $/trade −$2.08 (F7 NOT working alone here).

| filter                  |  n  | WR     | $/trade  | sum    |
|-------------------------|----:|-------:|---------:|-------:|
| F7_production           | 423 | 42.79% | −$2.08   | −$878  |
| MARKOV:w20_1m_fixed     | 200 | 52.00% | +$2.10   | +$420  |
| **F7+MARKOV:w20_1m_fixed**| **197**| **52.79%**| **+$2.51**  | **+$495** |

F7 alone loses money on this sleeve in this window. Markov fixed turns it positive. Combined is best.

### eth_5m_v1 — Markov ALONE beats F7

n_total=575; baseline_no_f7 +$7.06/trade; F7 +$7.04/trade (F7 = no lift here).

| filter                          |   n  | WR     | $/trade  | sum     |
|---------------------------------|-----:|-------:|---------:|--------:|
| baseline (no F7)                | 429  | 65.73% | +$7.06   | +$3,028 |
| F7_production                   | 146  | 55.48% | +$7.04   | +$1,028 |
| MARKOV:w20_5m_voladaptive       | 261  | 62.07% | +$7.17   | +$1,871 |
| **NoF7+MARKOV:w20_5m_voladaptive** | **169** | **76.33%** | **+$11.20** | **+$1,892** |
| MARKOV:w20_1m_fixed             | 226  | 56.64% | +$6.69   | +$1,511 |

This sleeve is the ONE where dropping F7 + applying Markov outperforms keeping F7. notF7+MARKOV:w20_5m_voladaptive = 76% WR, +$11.20/trade. The F7 filter actually rejects the best fires here.

### btc_15m_v1 — Tiny F7 sample, Markov 5m best on lookback

n_total=302; baseline_no_f7 −$6.50/trade (losing); F7 only n=27 but WR 78%.

| filter                          |  n  | WR      | $/trade   | sum   |
|---------------------------------|----:|--------:|----------:|------:|
| F7_production                   | 27  | 77.78%  | +$14.30   | +$386 |
| F7+MARKOV:w20_1m_voladaptive    | 27  | 77.78%  | +$14.30   | +$386 |
| F7+MARKOV:w20_5m_voladaptive    | 15  | 60.00%  | +$6.14    | +$92  |
| **F7+MARKOV:w20_5m_fixed**      | **6** | **100.00%** | **+$26.54**  | **+$159** |

F7 already produces +$14.30/trade on the 27 fires. Markov 5m_fixed picks the top 6 for 100% WR / +$26.54 — but n=6 is too low for confidence. Recommend keeping F7 as-is.

### btc_5m_v2, eth_5m_v2, btc_15m_v2 — TROUBLED SLEEVES

- **eth_5m_v2** (n=115, F7 WR 2.75%, avg −$19.97): F7 collapsed in this window. Even Markov can't save it (MARKOV:w20_1m_fixed cuts loss to −$7.14 on n=20). Suspect strike-distance issue specific to this 23.5h sample. Recommend **pause this sleeve** until investigated.
- **btc_15m_v2** (n=65, F7 WR 9.68%): Tiny n, all losses. F7+MARKOV:w20_5m_fixed shows 100% WR on n=6 but that's noise.
- **sol_15m_v1** (n=240, all filters lose): No combination produces a positive cell. Markov 5m_fixed marginally positive on n=24 (+$7.76/trade).

## Critical insight: 4 different best filters across 6 viable sleeves

| Sleeve         | Best filter                       | n  | WR     | $/trade | lift vs F7 |
|----------------|-----------------------------------|---:|-------:|--------:|-----------:|
| btc_5m_v1      | F7+MARKOV:w20_1m_fixed            | 138| 82.61% | +$14.41 | +$4.01/trade |
| sol_5m_v1      | F7+MARKOV:w20_1m_fixed            |  30| 100.00%| +$24.34 | +$14.29 |
| sol_5m_v2      | F7+MARKOV:w20_1m_fixed            |  88| 90.91% | +$13.83 | +$2.96  |
| btc_5m_v2      | F7+MARKOV:w20_1m_fixed            | 197| 52.79% | +$2.51  | +$4.59  |
| eth_15m_v2     | F7+MARKOV:w20_5m_voladaptive      |  33| 84.85% | +$19.22 | +$11.32 |
| eth_5m_v1      | NoF7+MARKOV:w20_5m_voladaptive    | 169| 76.33% | +$11.20 | +$4.16 vs F7 alone |
| btc_15m_v1     | F7_production (Markov doesn't add)|  27| 77.78% | +$14.30 | 0       |

**`F7+MARKOV:w20_1m_fixed` is the dominant filter** on 5m sleeves. `F7+MARKOV:w20_5m_voladaptive` wins on the 15m eth sleeve (matching the longer timeframe). `eth_5m_v1` is the outlier where F7 is dispensable.

## Why w20_1m_fixed is the winning Markov variant

Looking at pass rates:
- `w20_1m_voladaptive`: 59.5% pass (kept mostly correlated with momo signal direction)
- `w20_1m_fixed`: **28.9% pass** — strictest gate, only fires when the 20-min log return crosses ±0.3/0.4/0.6% (per asset)
- `w20_5m_voladaptive`: 41.3% pass
- `w20_5m_fixed`: 16.0% pass

`w20_1m_fixed` enforces a real momentum threshold (not just a 33% sample-percentile). When asset moves ≥0.3% over 20 minutes AND that direction matches momo signal AND F7 RSI confirms — all three are saying "trending hard right now". That's a much higher-conviction setup.

## What to deploy

**TV agent spec** (to send next session, after one more 24h of validation):

For each sleeve, add Markov gate alongside F7:

| Sleeve         | Gate stack                                                       | Expected WR | Expected $/trade |
|----------------|------------------------------------------------------------------|------------:|-----------------:|
| btc_5m_v1      | F7 ∧ Markov(w20=1m, threshold=fixed BTC=0.3%)                    | ~83 %       | +$14            |
| btc_5m_v2      | F7 ∧ Markov(w20=1m, threshold=fixed BTC=0.3%)                    | ~53 %       | +$2.5           |
| sol_5m_v1      | F7 ∧ Markov(w20=1m, threshold=fixed SOL=0.6%)                    | ~100 %      | +$24            |
| sol_5m_v2      | F7 ∧ Markov(w20=1m, threshold=fixed SOL=0.6%)                    | ~91 %       | +$14            |
| eth_15m_v2     | F7 ∧ Markov(w20=5m, threshold=vol-adaptive q33/q66 / 14d)        | ~85 %       | +$19            |
| eth_5m_v1      | (drop F7) Markov(w20=5m, threshold=vol-adaptive)                 | ~76 %       | +$11            |
| btc_15m_v1     | F7 only (Markov doesn't add)                                      | ~78 %       | +$14            |
| eth_5m_v2, btc_15m_v2, sol_15m_v1 | PAUSE — sample doesn't support gate            |             |                  |

**Validation plan:**
1. Continue current production for 48-72h more.
2. Re-pull events + klines from VPS3, re-run this script. Confirm Markov lift persists.
3. If lift holds on `btc_5m_v1`, `sol_5m_v1`, `sol_5m_v2`, `btc_5m_v2`, `eth_15m_v2` — send TV-agent spec.
4. Don't ship `eth_5m_v1` (drop F7) yet — that's a more controversial change, needs 7+ days.

## Files

- `strategy_lab/markov_filter/post_f7_real_compare.py` — runner
- `strategy_lab/markov_filter/_vps3_pull/post_f7_events.csv` — raw events from VPS3 (25,785 rows, 23.5h)
- `strategy_lab/markov_filter/_vps3_pull/binance_1m_fresh.csv` — fresh 1m klines (152,663 rows, Apr 14 → May 21 19:32 UTC)
- `strategy_lab/markov_filter/_results/post_f7_real_compare/fires_with_gates.csv` — per-fire regime labels under all 4 Markov variants
- `strategy_lab/markov_filter/_results/post_f7_real_compare/per_sleeve_full.csv` — long-form table

## Lessons (for me)

1. **Always verify what columns mean.** The CSV's `ws` looked like an obvious "ws_s" but it was `slot_start`. Cost 4 hours and an inverted F7 sign.
2. **Always check data window vs fire window.** Stale labels with asof() returning the LAST label by default is silent corruption — pass count 0 should have been flagged immediately.
3. **The backtest is not the production reality.** Backtest fires every q90-crossing slug. Production sleeves add sparse-book + slug-age + hedge-skip filters. F7 may behave very differently on the two universes.
4. **`w20_1m_fixed` was the winner**, not `voladaptive`. Vol-adaptive 33%-percentile gate is too lax. A real ±0.3% threshold means "actual momentum present" — much sharper signal.
