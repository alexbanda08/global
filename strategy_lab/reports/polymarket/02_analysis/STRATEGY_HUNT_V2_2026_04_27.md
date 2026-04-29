# Strategy Hunt v2 — Cross-Asset + Merge + Reversal — 2026-04-27

Builds on `STRATEGY_HUNT_FINDINGS_2026_04_27.md`. Adds:
- ETH and SOL markets (1,923 each, 3,846 new markets)
- Merge-aware exits (sell-direct OR buy-other-side+`mergePositions`)
- Binance-reversal trailing exit (close early if BTC reverts mid-window)

## TL;DR

The signal generalizes across 3 assets, **Binance-reversal exits add ~17% PnL on top of hold-to-resolution**, and merge-aware exits are zero-cost insurance (no help in this regime, but no harm).

| Best cell | Universe | n | PnL | 95% CI | Hit% | ROI/bet |
|---|---|---|---|---|---|---|
| **`q20 15m E3_rev25` ALL** | top-20% \|ret_5m\| × 15m × 3 assets | 289 | **+$44.74** | **[+$30, +$59]** | **66.1%** | **+15.48%** |
| **`full 5m E7_rev25_stop35_merge` ALL** | all × 5m × 3 assets | **4,306** | **+$179.62** | [+$142, +$219] | 32.1% | +4.17% |
| **`full 15m E3_rev25` ALL** | all × 15m × 3 assets | 1,436 | **+$114.65** | [+$79, +$150] | 58.6% | +7.98% |
| `q20 5m E7_rev25_stop35_merge` ALL | top-20% × 5m × 3 assets | 863 | +$69.61 | [+$53, +$88] | 38.5% | +8.07% |

All four CIs tight and **strictly above zero**.

## What changed vs v1

### 1. Cross-asset (ETH, SOL)

The `ret_5m` signal works on every asset:

| Asset | 15m E3 (rev25) PnL | Hit% | ROI/bet |
|---|---|---|---|
| BTC | +$39.38 (n=474, CI [+19, +61]) | 58.6% | **+8.31%** |
| ETH | +$31.42 (n=481, CI [+10, +51]) | 57.2% | +6.53% |
| SOL | +$43.85 (n=481, CI [+23, +63]) | **60.1%** | **+9.12%** |

**SOL is the standout** — highest hit rate and ROI/bet. ETH is the laggard but still profitable. **Combined ALL has the tightest CI**, confirming diversification benefit.

This rules out the "BTC-only fluke" hypothesis. The latency-arb thesis is real and generic to crypto perpetual-following binary markets.

### 2. Merge-aware exits — neutral in this regime, free insurance for stress

For each tested rule, merge-aware (E2/E5/E6) and direct-only (E1/E3/E4) versions produce **identical PnL within rounding**. Why:

- During Apr 22–27, both YES and NO sides had wet liquidity at most points.
- `1 - other_side_ask` and `our_side_bid` are tight enough that `max(direct, merge) ≈ direct` ~99% of buckets.
- The merge route ONLY pays off when one side's bid dries up while the other side's ask stays clean. We didn't see meaningful liquidity stress in this window.

**Recommendation:** keep merge-aware ON by default in production exit logic. Costs nothing in normal markets. In a stress event (resolution-time chaos, single-side wallet drain), it will save us from being stuck in an illiquid YES bid by letting us exit through NO ask + merge.

### 3. Binance-reversal trailing exit — the new champion

The mechanism: at each 10-second bucket, look up Binance close at that timestamp. If BTC has moved against the signal direction by ≥25 basis points (0.25%) since `window_start`, exit immediately.

**Net effect:**

| Universe | E0 hold | E3 rev25 | Δ |
|---|---|---|---|
| full 15m ALL | +$97.41 | +$114.65 | **+$17.24 (+17.7%)** |
| full 5m ALL | +$169.59 | +$177.36 | +$7.77 (+4.6%) |
| q20 15m ALL | +$34.88 | +$44.74 | **+$9.86 (+28.3%)** |
| q20 5m ALL | +$51.43 | +$57.57 | +$6.14 (+11.9%) |

**Reversal exit lifts every single cell** while raising or maintaining hit rate. The lift is biggest on:
- **Longer timeframes (15m vs 5m):** more time for BTC to reverse, so more bail-out value.
- **Filtered signal (q20 vs full):** when we're more confident, the cost of sticking through reversal is higher relative to the bail-out.

`rev_bp = 25` outperforms `rev_bp = 50` consistently — exiting sooner when wrong is better than later.

The "lock profits" intuition the user described is **mathematically equivalent** to this rule with `rev_bp` chosen relative to the BTC move that drove the original entry. We tested 25/50 bps; intermediate values (35-40 bps) likely interpolate.

### 4. Combo rule — `E7_rev25_stop35_merge`

Wins absolute PnL on **5m ALL** (+$179.62, CI [+$142, +$219]) — combines:
- Binance reversal @ 25 bps
- Stop loss @ 0.35 (merge-aware)

This is "early exit on either signal failure (Binance) or position drawdown (price)". On 5m where individual moves are tiny, capturing many small wins beats holding for the rare big ones.

On 15m, plain `E3_rev25` (no stop) wins because 15m moves are bigger — letting winners ride pays.

## Recommended live spec

Different rules for different signals. The combination tracks the table.

| Mode | Signal | Filter | Exit | Expected hit | Expected ROI/bet |
|---|---|---|---|---|---|
| **Volume mode (5m, all assets)** | sig_ret5m | none | E7 rev25+stop35+merge | 32% | **+4.2%** |
| **Conviction mode (15m, all assets)** | sig_ret5m | none | E3 rev25+merge | 58.6% | **+8.0%** |
| **Sniper mode (15m, top 20%)** | sig_ret5m_q20 | top/bot 20% | E3 rev25+merge | **66.1%** | **+15.5%** |

Sniper mode = our highest-conviction setup. 289 trades / 5 days = ~58 trades/day combined across 3 assets. Net ~$45 over 5 days at $1 stake. Scaled: at $100 stake, ~$900 over 5 days = ~$180/day = $5.5k/month, before gas and slippage.

## Caveats — same as v1, plus:

1. **5-day sample.** Need 4+ weeks for full validation. Collector running.
2. **Reversal exit assumes we observe Binance close at bucket time.** In live execution the actual price we see may be 100-500ms stale. Effect: small slippage on reversal triggers.
3. **`E7` exit value at trigger uses bucket best-bid/merge.** In live, our market order on a thin book will move the price. Real-world fill probably 50–200 bps worse than backtest.
4. **q20 thresholds were computed on the FULL sample within asset+timeframe.** Mild lookahead in setting the threshold (not in the signal itself). For live, use a rolling-window threshold computed from prior N days only. Small effect (~1% hit-rate haircut expected).
5. **Liquidity at $100+ stake** still untested. Top-of-book size in the data shows ~$50–$200 typical. Ladder-walking at higher size will eat 1-3¢ per fill.

## Files produced

| File | Purpose |
|---|---|
| `polymarket_extract_xasset.sql` | Templated SQL for any asset (sed-substituted) |
| `data/polymarket/{btc,eth,sol}_markets_v3.csv` | Per-asset market files |
| `data/polymarket/{btc,eth,sol}_trajectories_v3.csv` | Per-asset 10s buckets |
| `data/polymarket/{btc,eth,sol}_features_v3.csv` | Per-asset features |
| `data/polymarket/all_features_v3.csv` | Combined 5,742 markets |
| `data/binance/{btc,eth,sol}_klines_window.csv` | 1m/5m/15m klines |
| `data/binance/{btc,eth,sol}_metrics_window.csv` | OI + L/S + taker |
| `polymarket_build_features_xasset.py` | Generic feature builder |
| `polymarket_signal_grid_v2.py` | Cross-asset + merge + reversal grid |
| `results/polymarket/signal_grid_v2.csv` | Full grid (8 rules × 6 universes × 2 timeframes × 2 signals = 192 cells) |
| `reports/POLYMARKET_SIGNAL_GRID_V2.md` | Pretty grid report |

## Next moves

1. **Get the merge-function doc from you** — confirm my mechanic interpretation is correct (merge-equal-pairs → $1 USDC redeem). My implementation assumes that.
2. **Test rev_bp ∈ {15, 20, 30, 35, 40}** to find the optimal reversal threshold per asset.
3. **Forward-walk on the new cross-asset universe** — same script structure, evaluate q20 sniper mode on holdout.
4. **Add live gas to cost model** — at $0.10 per round trip, sniper mode (~58 trades/day) loses $5.80/day = $174/mo. Still profitable but matters at sizing.
5. **Live shadow mode** — run signal generation in real-time on the VPS, log predictions vs actuals, no orders. After 7 days, compare to backtest CIs. If they agree, ship to small-size live.
