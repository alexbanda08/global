# Indicator survey — mlmodelpoly + dexorynlabs mining

_2026-05-22. Surveyed two more Polymarket bot repos for technical indicators.
**mlmodelpoly = goldmine** (proper UP/DOWN fair value model + 8 new microstructure
features). **dexorynlabs = useless** (SEO-spam copy-trade bot, no signals).
Identified 6 features computable from our existing canonical data + 1 strategy
worth porting._

## TL;DR

| Repo | Verdict | What we take |
|---|---|---|
| `txbabaxyz/mlmodelpoly` | **Strong** — real microstructure stack | Fair value model (Black-Scholes UP/DOWN), microprice, RVOL, anchored 15m VWAP, sigma_15m, PM dip detector, contrarian-dip strategy |
| `dexorynlabs/polymarket-trading-bot-python` | **Skip** — copy-trade only, no indicators | Trade aggregation idea (low priority) |

**Top finding**: mlmodelpoly has a **closed-form fair value model for UP/DOWN
markets**:

```
z = [ln(S_now / ref_px) + drift·τ_norm] / (sigma_15m · √τ_norm)
fair_up = Φ(z)        # standard normal CDF
fair_down = 1 - fair_up
```

This is the **proper Bayesian prior** for our crypto up-down markets. Plug
binance close as `S_now`, chainlink strike as `ref_px`, our 15m realized vol
as `sigma`, time-to-settlement as `τ`. Compare to our entry vwap → edge in
basis points → Kelly-size from there.

We've been firing on the |ret_2m| > q90 threshold (a momentum heuristic).
The fair value model is **strictly better** — it gives a calibrated
probability, not just a threshold pass.

---

## Indicators from mlmodelpoly (txbabaxyz)

### A. Fair value model — **highest priority**

**File**: `src/collector/fair_model.py`. Computes `compute_fair_updown(s_now, ref_px, sigma_15m, tau_sec, window_sec=900, drift=0)`. Returns `{fair_up, fair_down, z_score}`.

**Math**: log-normal price dynamics, terminal price `S_end > ref_px`
gives probability via standard normal CDF of `z`.

**Why it beats our current threshold**:
- Today we fire when `|ret_2m| > q90(|ret_2m|)`. Same threshold for entry
  vwap=0.51 (cheap) and vwap=0.69 (expensive). But edge depends on price.
- Fair model gives a number 0-1 directly comparable to vwap. We fire when
  `|fair_up - vwap| > min_edge`. Naturally adjusts for asymmetric prices.

**Inputs we have**:
- `s_now` = binance-spot-ws close at fire time (we already use this)
- `ref_px` = chainlink strike at slot_start (we have `chainlink_rtds.parquet`)
- `sigma_15m` = realized vol from binance 1m klines (compute from our data)
- `tau_sec` = `slot_end - now` (deterministic)

**Cost to implement**: LOW. Pure-function port. ~50 lines of Python. Can wrap
existing canonical loaders.

### B. Microprice — replace entry vwap

**Definition**: volume-weighted mid price from book:
```
microprice = (bid_price·ask_size + ask_price·bid_size) / (bid_size + ask_size)
```

**Why it helps**: standard mid (bid+ask)/2 is biased when book is
asymmetric. Microprice gives the price closer to the side with less
liquidity (the side that will be hit next). Better fill estimator
than vwap for paper backtests.

**Inputs we have**: L25 books in canonical (`load_orderbook_l25_streaming`).
We already have top-of-book bid/ask.

**Cost**: TRIVIAL. 4 lines added to `engine_v2.fill_at_book`.

### C. RVOL (Relative Volume) — confirmation gate

**Definition**: current bar volume / mean(last N bar volumes).

**Why**: a momentum signal on quiet volume is suspicious. RVOL > 1.5 means
the signal is supported by participation.

**mlmodelpoly defaults**: `RVOL_5S_LOOKBACK=60`, `RVOL_1M_LOOKBACK=60`.

**Inputs we have**: binance 1m klines have `volume_traded` column. We
can compute RVOL on 1m bars (60-bar lookback = 1 hour). 5s/15s bars
we don't have.

**Cost**: LOW. Pre-compute rolling RVOL per asset, join at fire time.

### D. Anchored VWAP (15m bucket) + deviation in bps

**Definition**: VWAP from the start of the current 15m UTC bucket, plus
`(price - vwap) / vwap` in bps as a deviation signal.

**Why**: tells us if the price is rich (above VWAP) or cheap (below VWAP)
relative to the volume-weighted session reference. Standard intraday
mean-reversion signal.

**Inputs we have**: binance 1m klines have OHLCV — we can compute 15-bar
rolling VWAP per asset.

**Cost**: LOW. Pre-compute.

### E. sigma_15m (15-min realized volatility)

**Definition**: standard deviation of log returns over the last 15 1m
bars, annualized or scaled to the 2-minute horizon.

**Why**: input to the fair value model. Also useful as a regime gate
(only fire when realized vol > some floor).

**Inputs we have**: binance 1m klines.

**Cost**: TRIVIAL. Already partially used (q90 of |ret_2m| over 14d
samples is similar in spirit but window-shifted).

### F. PM dip detector — **contrarian entry signal**

**Definition**: temporary drop on Polymarket UP or DOWN side relative to a
short-window high. Triggers `up_dip=True` when UP token price drops > X
bps in <3 seconds while binance hasn't moved.

**Why**: counterparty mistake. Often a single large taker sells DOWN
shares to exit a position, creating a brief mispricing on the UP side
that snaps back. **Free edge** if you can detect and react in <30
seconds.

**Inputs we have**: L25 books give us bid/ask through time. We can
construct a synthetic "PM mid" time series and detect dips.

**Cost**: MED — needs a streaming detector over book history. Reuse the
`engine_v2.find_book_strict` machinery to walk book deltas.

### G. CVD (Cumulative Volume Delta) — order-flow signal

**Definition**: cumulative `(buy_vol - sell_vol)`. Positive CVD = buying
pressure dominant.

**Why**: imbalance in order flow is a leading indicator of price moves.
Combined with momentum: high ret_2m AND high CVD slope → real
momentum; high ret_2m AND low CVD slope → exhaustion.

**Inputs we DON'T have**: needs tick-level Binance `aggTrade` stream
with buy/sell flag. Our canonical only has 1m OHLCV; we'd need a new
feed.

**Cost**: HIGH — requires new collector on VPS2/VPS3. Skip for now.

### H. Spike detection — boolean confirmation flag

**Definition**: `ret_5s_bps > SPIKE_SANITY_BPS` → `up_spike_5s=True`. Used
as a confirmation flag (e.g., "fire UP only if up_spike + cvd_slope >0").

**Inputs we have**: 1m bars don't give 5s resolution. Without
sub-minute data, only approximation possible.

**Cost**: HIGH — same data gap as CVD.

### I. The z_contra_fav_dip_hedge strategy itself

**File**: `src/strategies/z_contra_fav_dip_hedge.py`. Quoted summary:

> Strategy for buying the underdog when Binance Z-score confirms it,
> while there's a temporary dip on the favorite side. Includes
> conditional hedging with the opposite side and dynamic sizing based on
> confidence metrics. Backtest Results (73 markets).

**Translation**:
1. Compute `z_score = (binance_close - pm_fair_price) / sigma`
2. If `pm_up_mid > 0.5` (UP is favorite) AND `down_dip=True` (DOWN had a
   temporary drop) AND `z_score < -2` (binance disagrees with PM
   favorite) → BUY DOWN.
3. Hedge with a UP buy if the entry moves against us by N bps.
4. Size = base × `bias_strength` × `confidence` (Kelly-like).

**Adaptable to our setup**: We don't trade open-ended Polymarket
markets where price drifts; we trade fixed-window crypto up-down. But
the **PM-dip + binance-disagree** core IS applicable in our 5m/15m
windows during the first 60-120 seconds after market open, when
Polymarket book is still settling.

**Cost**: MED — implement (A) fair value model + (F) PM dip detector
first; this strategy becomes a 30-line composite on top.

---

## Indicators from dexorynlabs

Skip. The repo is a copy-trade bot with a hardcoded wallet
(Gabagool22), 1-second polling, no signal generation. Only useful idea:

- **Trade aggregation**: combine multiple intra-window fires into a
  single order to reduce gas. We're paper-only and Polymarket uses
  proxy wallets (no gas), so this is irrelevant.

---

## What we already have (no porting needed)

- **RSI(14)** — F7 gate. Verified 94.67% match with production.
- **Volume q90 threshold** — our momo gate.
- **Markov regime (M1V, M5V)** — vol-adaptive tertile classifier.
- **HoD-Top-8** — refreshed today.

---

## Prioritized port list

| Order | Feature | Cost | Edge potential | Notes |
|--:|---|---|---|---|
| 1 | **Fair value model (A)** | LOW | HIGH | Black-Scholes UP/DOWN; gives calibrated p_win |
| 2 | **Microprice (B)** | TRIVIAL | LOW-MED | Better fill estimator; tiny code |
| 3 | **sigma_15m (E)** | TRIVIAL | LOW | Input to (A); also a regime gate |
| 4 | **RVOL (C)** | LOW | MED | Confirms momentum is volume-backed |
| 5 | **Anchored VWAP (D)** | LOW | MED | Mean-reversion signal |
| 6 | **PM dip detector (F)** | MED | HIGH | Contrarian entry — high edge if detected fast |
| 7 | **z_contra strategy (I)** | MED | MED | Composite using above; backtest validates the combo |
| — | CVD (G) | HIGH | MED | Skip until we have tick-level trades |
| — | Spike detection (H) | HIGH | LOW | Same data gap as CVD |

---

## Concrete next step

Build `strategy_lab/meta_classifier/fair_value_backtest.py`:

1. Port `compute_fair_updown(s_now, ref_px, sigma_15m, tau_sec)` — pure
   function, ~30 lines.
2. Per slug in `load_resolutions()`:
   - `ref_px` = strike_price from `chainlink_rtds_resolutions`
   - At each fire candidate timestamp (slot_start+60, +120, ...), look
     up `s_now` from binance kline closest at-or-before.
   - Compute `sigma_15m` from prior 15 bars of binance 1m closes.
   - Compute `fair_up`.
   - Compare to actual entry vwap (from `tier1_entries` or replayed
     via `engine_v2.fill_at_book`).
   - Edge = `fair_up - vwap` (for UP fires) or `(1 - fair_up) -
     vwap_no` (for DOWN fires).
3. Bucket fires by edge tier (`<0`, `0-2pp`, `2-5pp`, `>5pp`). Report
   WR per bucket.

Hypothesis: WR scales monotonically with `edge` — and the >5pp bucket
hits ≥60% WR with low DD because the fair value model gives a true
probability.

**Run cost**: ~2 minutes on 28d data. Reuses `engine_v2` for fills, no
new engine needed.

---

## Combined with yesterday's S1 + S2 proposals

The fair value model is **complementary** to the anti-exhaustion (S1)
and direction-asymmetric HoD (S2) ideas:

- S1 (Magnitude Cap) cuts noisy outlier fires
- S2 (Direction HoD) cuts wrong-hour fires
- Fair value gate cuts low-edge fires

Stacked, they all push the same direction: fewer fires, higher WR per
fire, lower DD per losing streak. **Target: ≥60% WR ensemble, max DD <
3% of 28d notional.**

---

## Files referenced

- mlmodelpoly fair_model: https://github.com/txbabaxyz/mlmodelpoly/blob/main/src/collector/fair_model.py
- mlmodelpoly features: https://github.com/txbabaxyz/mlmodelpoly/blob/main/src/collector/features.py
- mlmodelpoly strategy: https://github.com/txbabaxyz/mlmodelpoly/blob/main/src/strategies/z_contra_fav_dip_hedge.py
- Yesterday's proposal: `strategy_lab/reports/NEW_STRATEGIES_PROPOSAL_2026_05_22.md`

## End of survey
