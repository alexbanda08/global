# Polymarket Strategy Filters — Complete Explanation

**Status:** updated 2026-04-28 after full strategy hunt session.
**Audience:** TV agent, future-Claude, anyone joining the project.

This document explains **every signal layer + filter we tested**, in plain English, with results.
For implementation specifics see `polymarket/01_deployable/TV_STRATEGY_IMPLEMENTATION_GUIDE.md`.
For full session summary see `session/SESSION_SUMMARY_2026_04_27_strategies.md`.

---

## 0. The skeleton

Every Polymarket UpDown trade has THREE decisions:

1. **Signal** — direction (UP or DOWN) based on Binance ret_5m
2. **Entry** — how to acquire the position (taker vs maker)
3. **Exit** — when/how to close (hold to resolution vs hedge-hold)

Each filter we tested either:
- Refined the signal (which markets to trade)
- Changed entry mechanics (how we get filled)
- Changed exit mechanics (how we close)

---

## 1. SIGNAL LAYER — which markets to trade

### `sig_ret5m` (always-on baseline)

**What:** at each market's `window_start`, compute
```
ret_5m = log(BTC_close[ws] / BTC_close[ws - 300s])
```
Bet UP if `ret_5m > 0`, DOWN if `ret_5m < 0`.

**Why it works:** Polymarket settles via Chainlink Data Streams which lags Binance by 4-12 seconds. The previous 5min Binance return is a leading indicator of the chainlink-settled close. Pure latency arbitrage.

**Universe-wide:** 62.1% hit / +11.4% ROI on 5m, 60.7% / +12.7% on 15m. n≈4,300 / 1,400.

---

### ✅ `q10` filter on 5m markets — DEPLOY

**What:** only fire when `|ret_5m|` is in the **top 10%** of recent 14-day observations for that (asset, timeframe).

**Why it works:** the bigger the ret_5m, the stronger the directional signal. Top 10% = the moves where Binance has already shown clear direction → highest chance of Chainlink continuation.

**Forward-walk holdout (5m × ALL):** n=43, hit **81.4%**, ROI **+28.17%** (vs baseline +21.18% = **+7pp lift**).
**Per-asset (5m holdout):**
- BTC: hit 86.7%, ROI +35.54%
- ETH: hit 73.3%, ROI +24.81%
- SOL: hit 84.6%, ROI +23.53%

**Deploy:** 5m markets only.

---

### ✅ `q20` filter on 15m markets — DEPLOY (locked baseline)

**What:** same as q10 but **top 20%** instead of top 10%.

**Why on 15m specifically:** on 15-min windows, q10 and q20 perform identically (q10 lift ≈ 0.06-0.57pp, well within noise). q20 keeps 2× the trades for the same hit/ROI → higher absolute PnL throughput.

**Forward-walk holdout (15m × ALL):** n=39, hit **87.2%**, ROI **+24.03%** (CI [+$7, +$12]).

**Deploy:** 15m markets only.

---

### ✅ Cross-asset BTC-confirmation filter on 5m ETH/SOL — DEPLOY (NEW this session)

**What:** before trading ETH or SOL on a 5m market, ALSO compute BTC's q10 signal at the same window_start. Only trade if both signals agree direction.
```
sig_eth = q10(eth_ret_5m)
sig_btc = q10(btc_ret_5m)
trade only if sig_eth == sig_btc
```

**Why it works (5m only):** crypto assets are highly correlated on short timeframes. When BTC + ETH both signal UP simultaneously, the move is **market-wide and synchronous** — high-conviction continuation. When they diverge, it's idiosyncratic noise that mean-reverts before a 5min resolution.

**Why NOT on 15m:** by 15 minutes, individual asset price discovery has decoupled from BTC. The filter just removes valid trades.

**Forward-walk holdout (5m only):**
- ETH: +7.85pp lift over baseline (n=8, hit 87.5%)
- SOL: +1.79pp lift (n=9, hit 88.9%)

**Deploy:** ETH and SOL × 5m only. Trade volume drops 36% but precision rises +5pp on average.

---

## 2. ENTRY LAYER — how to acquire the position

### Default: TAKER entry

**What:** market buy at the current ask of held side. Cross the spread.

**Cost:** approximately 1.3¢ per leg (half the typical 2.6¢ bid-ask spread). Eats into ROI.

---

### ✅ MAKER entry hybrid on 15m markets — DEPLOY (NEW this session)

**What:**
1. At `window_start`, place a LIMIT BUY at `held_side_bid + 0.01` (1 tick improvement above the bid).
2. Wait **30 seconds** for fill.
3. If filled → done, we bought at our limit (saved ~1¢ vs taker).
4. If NOT filled by t+30s → cancel limit, place MARKET buy at the ask (taker fallback).

**Why hybrid (not maker-only):** maker-only loses 4-9pp because trades that DON'T fill are biased toward markets where price ran AWAY from us (= our best winners). Skipping winners destroys the strategy. The taker fallback ensures we capture them.

**Why ONLY on 15m:**
- 15m windows are slow → in the first 30s, the ask drops to our limit only when **passive flow** (someone needs to sell normally) shows up. Those fills are quality.
- 5m windows are fast → ask comes to our limit from **noise volatility**, not signal. Fills are random; lift evaporates on holdout.

**Forward-walk holdout (15m only):**
- ALL: +2.42pp lift (n=23, hit 91.3%)
- ETH: +2.44pp lift
- SOL: +9.04pp lift
- BTC: 0% fill rate (n=8 too small)

**Deploy:** 15m markets only, behind feature flag. Gracefully degrades to taker if anything goes wrong.

---

### ❌ MAKER hedge — DO NOT DEPLOY

**What we tested:** when rev_bp triggers a hedge, place limit at `other_bid + 0.01` instead of crossing the ask. Fall back to taker after 20-60s.

**Why it fails:** when rev_bp triggers, BTC has just moved against us → other side's price is RISING fast (everyone wants to buy the now-favored side).
- Our limit at `other_bid + 0.01` rarely fills (3-4%) — bid is climbing AWAY from us
- During the 20-60s wait, the other-side ASK climbs HIGHER
- Falling back to taker, we pay MORE than if we'd just taken at trigger time
- Net cost: +1¢/hedge ≈ -0.57pp ROI

**General principle:** maker fills work in PASSIVE flow regimes, fail in DIRECTIONAL flow regimes. rev_bp triggers are by definition directional.

---

## 3. EXIT LAYER — when/how to close

### ✅ Hedge-hold at `rev_bp = 5` (locked baseline)

**What:** every ~10s while position is open, check Binance close. If BTC has moved ≥5 basis points against our signal direction:
- Buy the OPPOSITE side at its current ask (taker)
- Hold both legs to natural resolution
- Exactly one leg pays $1, the other pays $0
- Cost basis: entry + hedge price; payout: $1 minus 2% fee on winning leg's profit

**Why hedge-hold (not direct sell, not merge):**
- Direct sell at the bid: vulnerable to spread degradation when market moves against us
- Buy other + `mergePositions()`: marginally better (~$0.01/trade) but requires Polygon RPC integration
- **Hedge-hold = same downside protection as merge with ZERO on-chain code path**

**Why `rev_bp=5`:** swept rev_bp ∈ {3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50}.
- rev_bp=3: marginally higher in-sample but 5× more train→holdout drift (overfit)
- rev_bp=5: captures 82% of rev_bp=3's PnL with half the drift
- rev_bp=15+: misses too many reversals

**Holdout hit rate at rev_bp=5:**
- q20 × 5m × ALL: 73.1%, +21.06% ROI
- q20 × 15m × ALL: 87.2%, +24.03% ROI
- q10 × 5m × ALL: 81.4%, +28.17% ROI

---

### ❌ Take-profit at any target — DO NOT DEPLOY

**What we tested:** sell our held side when YES bid reaches `entry × (1 + T)` for T ∈ {5, 10, 15, 20, 25, 40, 60, 80, 100, 150}%.

**Why it fails:** Polymarket binary markets pay **$1 at resolution**. Capping winners at any T < 100% throws away the asymmetric upside that's the source of our alpha.

| Variant | ROI | vs baseline |
|---|---|---|
| baseline (rev_bp hedge-hold) | +24.58% | — |
| TP at 5% | -0.68% | -25pp |
| TP at 25% | +5.68% | -19pp |
| TP at 100% | +12.66% | -12pp |
| TP at 150% (almost never fires) | +11.17% | -13pp |

**Math:** the rev_bp hedge-hold strategy is already asymmetrically optimized:
- Limits downside via hedge when signal reverses (rev_bp triggers ~56%, locks break-even)
- Keeps unlimited upside on natural resolution winners (full $0.50 profit at entry=$0.50)

Adding TP turns this asymmetric payoff into a symmetric one. For an 81%-hit strategy, asymmetric beats symmetric by a wide margin.

**When TP would have made sense (for reference):**
- Hit rate is moderate (<65%)
- Payoff distribution has thin tails

Neither applies to q10/q20 territory.

---

## 4. STAKE SIZING — how much per trade

Based on E1 realistic-fills experiment (top-10 book-walk, 5,742 markets):

| Asset | Top-of-book median | Safe stake |
|---|---|---|
| BTC | $104 USD | **$250+/trade** safe (3.3pp ROI haircut) |
| ETH | medium | **~$100/trade** cap (drag at $250 = -7.7pp) |
| SOL | thin | **~$25-50/trade** cap (76% trades skip at $250) |

For the live $1 micro-validation phase (TV guide § 5.1), all assets are fine. Capacity matters when scaling above $25/trade — at which point per-asset gating kicks in.

---

## 5. FILTERS WE TESTED THAT GAVE NO EDGE

These all live under `polymarket/03_no_edge/`. Don't revisit unless we have substantially more data.

| Filter | Why it failed |
|---|---|
| **Take-profit at any target** | Asymmetric payoff is the alpha; capping it removes it |
| **Maker hedge orders** | Directional flow at rev_bp trigger → 3-4% fill rate, costs +1¢/hedge |
| **Side asymmetry (UP vs DOWN bias)** | Our universe is mid-priced (30-70¢), JBecker's longshot effects (1-10¢) don't apply |
| **Vol-regime adaptive rev_bp** | q10 already SELECTS for high-vol moments (vol_ratio mean = 3.08); re-adapting is double-counting |
| **Volume regime filter** | q10's \|ret_5m\| selection already encodes vol regime info |
| **12-hour cherry-pick UTC filter** | Cross-asset Spearman ρ ~0.35 (weak), risk of overfitting; Apr 25 weekend collapsed europe filter |
| **Long-horizon signals (ret_15m_q20, ret_1h_q20)** | 5min horizon is right; longer horizons under-perform by 7-13pp |
| **smart_minus_retail as primary signal** | p=0.011 univariate doesn't translate to PnL alone (53-60% hit) |
| **Lagged BTC signal (>30s)** | Cross-asset information transmits in <30s; lagged signals have already decayed |
| **Maker entry on 5m** | Fast windows → fills happen from noise volatility, not signal flow → no holdout edge |
| **Cross-asset filter on 15m** | By 15min, individual price discovery dominates → BTC's signal has decayed |

---

## 6. The full deployment matrix

| Asset × TF | Signal | Entry | Exit | Holdout ROI |
|---|---|---|---|---|
| BTC × 5m | q10 | taker | hedge-hold rev_bp=5 | +35.5% |
| BTC × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +25.2% (lifted from +22.8%) |
| ETH × 5m | q10 + btc-agree | taker | hedge-hold rev_bp=5 | +24.8% (lifted from +17.8%) |
| ETH × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +27.8% (lifted from +24.3%) |
| SOL × 5m | q10 + btc-agree | taker | hedge-hold rev_bp=5 | +25.6% (lifted from +21.7%) |
| SOL × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +24.6% (lifted from +18.9%) |

**Cross-asset average holdout: ~27%** vs locked baseline +20.4% = **+6.6pp lift** from combining all validated layers.

---

## 7. Pilot order if you have to roll out gradually

1. **Phase 18-04** (per TV guide): ship q10 (5m) + q20 (15m) + hedge-hold rev_bp=5 + redemption worker. $1/slot. 7 days.
2. **Phase 18-05**: enable maker entry flag on 15m only. 7 days. Verify maker_filled events ≈ 25%.
3. **Phase 18-06**: enable cross-asset filter on 5m ETH/SOL only. 7 days. Verify trade rate drops ~36%.
4. **Phase 19** (after 30 days of clean live data): consider spread filter pilot on 5m × BTC (currently borderline).

Each layer is independent and gated. If any underperforms in live, flip its flag off and the others continue running.

---

## 8. Open questions for the next session

1. **Forward-walk q10 + cross-asset on 12-day window** — current holdouts are n=7-15 per cell. Need ≥30 for tight CIs.
2. **Spread filter pilot** on 5m × BTC — only cell with adequate sample (n=8 holdout, lift +4.33pp).
3. **Time-of-day with Mon/Tue in dataset** — current 5-day window is Wed-Sun only. Once Mon/Tue land, can revisit weekday-vs-weekend.
4. **Funding rate signal (E8)** — once May 1 backfill lands.
5. **Composite signal (combo_q20)** — `ret_5m AND smart_minus_retail` agree direction. In-sample +26.32% on BTC × 15m (n=48). Was promising but never forward-walked.
