# External repo comparison — `evan-kolberg/prediction-market-backtesting`

_Generated: 2026-05-12 — comparison of our momo 5m/15m up-down engines against
the public `evan-kolberg/prediction-market-backtesting` (PMXT) repo v4.1-alpha._

**Source surveyed**: https://github.com/evan-kolberg/prediction-market-backtesting
(v4.1-alpha branch, 468 commits, NautilusTrader 1.224.0, Rust 1.93 edition 2024,
Python 3.12+). Their BTC 5m markets use the SAME slug format we do
(`btc-updown-5m-{slot_start_unix_seconds}`), so the artifacts are directly
comparable.

---

## TL;DR

1. **Architecturally they are the more conservative engine.** They replay
   Polymarket L2_MBP order-book deltas via Nautilus, apply queue-position and
   75 ms latency, charge the real Polymarket taker fee curve
   `C × feeRate × p × (1−p)`, and credit maker rebates as negative commission.
   We use a simpler `book_walk_fill($25)` over an L25 snapshot at a single
   wall-clock target, no latency, fee shortcut `2% on winning leg only`.

2. **They never look at external crypto prices.** Every strategy in their zoo
   reads only the Polymarket book / mid / spread / imbalance. We use
   binance-spot-ws klines as the SIGNAL. That makes us potentially higher-edge
   IF the kline-derived signal is real — but post-`ws_s` fix our hit rate
   collapsed to ~50%, which is the exact regime where their book-only baselines
   become the more honest comparison.

3. **No `ws_s` bug surface in their code.** Because they don't anchor anything
   on an external clock, they cannot have our pre-window / in-window confusion.
   Their entry gates use `activation_start_time_ns = market_close_time_ns − 60s`
   for late-favorite and `final_period_minutes = 30` for final-period momentum —
   simple offsets from `end_time`, not derived from the slug.

4. **5 things we should steal (priority order):**

   1. **Polymarket actual taker fee curve** — replace our 2%-on-profit shortcut
      with `fee_per_share = feeRate × p × (1−p)` charged per fill. Materially
      different at p=0.85 (≈1.27% if feeRate=10%) vs our flat 2% on profit.
   2. **Static latency model** — `base_latency_ms=75, insert=10, update=5,
      cancel=5`. Our fill is "L25 ask at exact wall-clock"; reality is
      ≥75 ms staler.
   3. **Pair arbitrage scanner** — buy YES+NO when total cost after fees < $1.
      Entirely new alpha source, our canonical L25 already supports it,
      run as a one-off scan on our 12 522-market universe.
   4. **`min_book_events` filter** — drop markets with <25 book updates over
      the window. Sparse books produce artificially good backtest fills.
   5. **Maker rebate modeling** — `−feeRate × p × (1−p) × 0.20` (crypto) on
      LIMIT fills. Opens a maker branch that's currently invisible to our
      taker-only engine.

5. **What we do better and shouldn't change**:
   - Chainlink RTDS resolution truth (1 Hz) — they trust Polymarket's settled
     outcome, we cross-check against chainlink.
   - 18-decimal cross-reference vs production live (`_xref_live.py`). They
     attempted a similar wallet replay (`@beffer45`) and explicitly say it
     fails to reproduce exactly because public trades omit OMS state.
   - Multi-venue spot klines (binance / coinbase / kraken / okx) for ablation.
     They have no equivalent.

---

## How their engine runs the 5m up-down backtest

### Replay shape (file: `backtests/polymarket_btc_5m_late_favorite_taker_hold.py`)

```python
BTC_5M_WINDOW_START = datetime(2026, 4, 26, 18, 0, tzinfo=UTC)
BTC_5M_WINDOW_COUNT = 24
BTC_5M_WINDOW_SIZE  = timedelta(minutes=5)
ACTIVATION_SECONDS_BEFORE_CLOSE = 60

BookReplay(
    market_slug = f"btc-updown-5m-{int(start.timestamp())}",
    token_index = 0,    # 0 = Up/YES, 1 = Down/NO
    start_time  = _utc_iso(start),
    end_time    = _utc_iso(start + 5min),
    metadata = {
        "sim_label": "btc-updown-5m-{slot_start}-{up|down}",
        "activation_start_time_ns": (end_time − 60s) * 1e9,
        "market_close_time_ns":      end_time * 1e9,
    },
)
```

Slug format: **identical to ours**. `slot_start_unix_seconds` is the suffix —
they treat it as the strike read time / window start, exactly matching our
canonical convention (and not as `ws_s`; their controller has nothing
analogous to our pre-window-momentum anchor).

### Data path

```
MarketDataConfig(
    platform = Polymarket,
    data_type = Book,
    vendor   = PMXT,
    sources  = ("local:/Volumes/storage/pmxt_data",
                "archive:r2v2.pmxt.dev",
                "archive:r2.pmxt.dev"),
)
```

- PMXT = hourly raw L2 archive. One parquet file per UTC hour, can contain
  many markets and tokens. Filtered cache at
  `~/.cache/nautilus_trader/pmxt/<condition>/<token>/polymarket_orderbook_YYYY-MM-DDTHH.parquet`.
- Two row types: `book_snapshot` (full book reset) and `price_change`
  (incremental update). If an hour is missing, the loader RESETS local book
  state — never applies incrementals across gaps. Same conservative rule
  we should adopt for our L25 streaming loader.
- Staged loading: `BACKTEST_REPLAY_LOAD_WORKERS=32`, `MATERIALIZE_WORKERS=4`.
  Source workers fan out per-hour reads; materialization workers convert to
  Nautilus deltas with a narrower pool to bound RAM.

### Execution model (file: `docs/execution-modeling.md`)

```python
ExecutionModelConfig(
    queue_position = True,
    latency_model  = StaticLatencyConfig(
        base_latency_ms   = 75.0,
        insert_latency_ms = 10.0,
        update_latency_ms = 5.0,
        cancel_latency_ms = 5.0,
    ),
)
# engine venue config:
engine.add_venue(
    book_type           = BookType.L2_MBP,
    liquidity_consumption = True,
    queue_position      = True,
    bar_execution       = False,
    trade_execution     = True,    # real trade ticks advance queue position
)
```

- **L2_MBP order book** maintained from `OrderBookDeltas` (not QuoteTicks —
  Nautilus ignores quotes for L2_MBP).
- **`trade_execution=True`** means real Polymarket TradeTicks are injected as
  execution evidence. When a real trade prints at a price, queue at that level
  is advanced. Marketable orders walk the replayed book; resting orders need
  queue-depletion to fill.
- **Latency**: orders arrive 75 ms after decision. Modifies/cancels are
  faster. Critical because some of their book-imbalance strategies fire on
  10-tick windows where 75 ms is meaningful.

### Fee model (Polymarket-real, not approximated)

Per-fill `fee_per_share = feeRate × p × (1 − p)` where `p` is the fill price
and `feeRate` comes from Gamma's `feeSchedule.rate` metadata. CLOB
`maker_base_fee` / `taker_base_fee` are explicitly NOT used — they are
signing caps, not settlement fees.

```python
def _fee_per_share(*, price: Decimal, taker_fee: Decimal) -> Decimal:
    price = _clamp_probability(price)  # clip to [0,1]
    return max(taker_fee, 0) * price * (1 - price)
```

- Taker fee charged on every taker fill.
- Maker fee = 0 explicitly.
- Maker rebate = `fee_equivalent × {0.20 if crypto else 0.25}` as negative
  commission on LIMIT fills.
- Markets with `feeRate=0` get zero fees AND zero rebates (no invented
  fallback).
- `$1 daily payout threshold` not modeled (would require wallet-day state).

### Strategy: `BookLateFavoriteTakerHold` (configured for 24 BTC 5m windows)

```python
strategy_configs = [{
    "strategy_path": "strategies:BookLateFavoriteTakerHoldStrategy",
    "config": {
        "trade_size": Decimal("5"),
        "activation_start_time_ns": "__SIM_METADATA__:activation_start_time_ns",
        "market_close_time_ns":     "__SIM_METADATA__:market_close_time_ns",
        "min_midpoint":      0.90,   # favorite must be ≥ 0.90 mid
        "min_bid_price":     0.88,   # backstop bid quality
        "max_entry_price":   0.95,   # don't pay past 95c
        "max_spread":        0.04,
        "min_visible_size":  5.0,
    },
}]
initial_cash       = 1_000.0
probability_window = 256
min_book_events    = 25     # filter sparse markets
```

Logic in plain English: in the last 60 s of each 5 min window, if poly mid ≥
0.90 AND best bid ≥ 0.88 AND best ask ≤ 0.95 AND spread ≤ 0.04 AND visible
ask size ≥ 5 shares, **take the offer** and hold to resolution. Pure
poly-book signal; no crypto price input.

### Strategy: `BookBinaryPairArbitrage`

```python
"config": {
    "instrument_ids": "__ALL_SIM_INSTRUMENT_IDS__",
    "trade_size":            Decimal("5"),
    "min_net_edge":          0.0,
    "max_total_cost":        1.0,
    "max_leg_price":         0.985,
    "max_spread":            0.080,
    "max_expected_slippage": 0.015,
    "min_visible_size":      5.0,
    "max_entries_per_pair":  1,
    "pairing_mode":          "sequential",
    "hold_to_resolution":    True,
    "include_taker_fees_in_signal": False,
}
```

Logic: if `(best_ask_up + best_ask_down)` net of taker fees `< $1` and both
legs ≤ 0.985 and spread on each ≤ 8%, buy both. One side resolves to $1, the
other to $0 → guaranteed payoff = (1 − combined_cost) minus fees on the
winning side. The repo notes this is "gross complementary-token entries
using only PMXT L2 book data."

### Strategy zoo (full list, from `strategies/__init__.py`)

| Family | Bar variant | Book variant | Idea |
|---|---|---|---|
| breakout | ✓ | ✓ | range breakout |
| binary_pair_arbitrage | – | ✓ | YES+NO < $1 |
| deep_value | – | ✓ | hold cheap underdog to resolution |
| ema_crossover | ✓ | ✓ | classic EMA cross on poly mid |
| **final_period_momentum** | ✓ | ✓ | buy if `mid > 0.80` in final N min, TP=0.92, SL=0.50 |
| **late_favorite_limit/taker_hold** | – | ✓ | buy ≥ 0.90 in last 60 s, hold |
| mean_reversion | ✓ | ✓ | revert to MA |
| **microprice_imbalance** | – | ✓ | `imbalance>0.57` enter, `<0.50` exit, TP=$0.01 SL=$0.015 |
| panic_fade | ✓ | ✓ | fade large adverse move |
| rsi_reversion | ✓ | ✓ | RSI extreme |
| **threshold_momentum** | ✓ | ✓ | breakout entry → TP/SL/close |
| vwap_reversion | – | ✓ | revert to vwap |

**Bold** = closest analogs to our momo strategy.

---

## Side-by-side: our engine vs PMXT

| Dimension | Our `momo_*` / `strategy_lab` | PMXT (evan-kolberg) |
|---|---|---|
| Backtest framework | Custom pandas + numpy | NautilusTrader 1.224 event-driven |
| Book data shape | L25 snapshot per second (subsampled) | L2_MBP deltas + book snapshots |
| Fill primitive | `book_walk_fill(prices, sizes, $25)` | Marketable order walks Nautilus L2 book |
| Latency | None (instantaneous fill at `fire_us`) | 75 ms base + 10/5/5 insert/update/cancel |
| Queue position | N/A (taker-only, immediate) | Modeled via real TradeTick advance |
| Signal source | Binance kline `ret_2m` (external) | Poly book mid / spread / imbalance |
| Outcome truth | Chainlink RTDS 1 Hz (canonical) | Polymarket settled outcome |
| Resolution filter | Chainlink-only (drops binance-resolved) | None needed (no external truth used) |
| Fee model | 2% on winning leg, 0% losing leg | `feeRate × p × (1−p)` per fill, taker only |
| Maker rebates | Not modeled | 20% (crypto) / 25% (other) on LIMIT fills |
| Activation gate | `fire_us = (ws_s + 120) * 1e6` | `activation_start_time_ns` from metadata |
| Sparse-market filter | None | `min_book_events=25`, `probability_window=256` |
| Multi-asset | BTC/ETH/SOL via canonical | Currently BTC 5m only (5m hooks added v4.1) |
| Multi-timeframe | 5m + 15m | 5m only |
| Live cross-check | `_xref_live.py` matches production to 18 decimals | `account_trade_replay` documented to fail exactly |
| Parallel load | Single-threaded streaming | `LOAD_WORKERS=32` × `MATERIALIZE_WORKERS=4` |

---

## What we should learn / steal (concrete next-session work)

### Tier 1 — adopt now (low effort, high realism gain)

1. **Polymarket actual taker fee curve** — `data/v4/canonical/load.py` or
   `strategy_lab/fees.py`:

   ```python
   def poly_taker_fee_per_share(price: float, fee_rate: float = 0.10) -> float:
       p = max(0.0, min(1.0, price))
       return fee_rate * p * (1 - p)
   ```

   Use everywhere we compute PnL. Cross-check vs production
   `trading.events.data->>'pnl_usd'` per row: production's effective fee
   should match this curve, not our 2%-on-profit shortcut.

2. **Static latency**: add a `fill_us = fire_us + 75_000` shift everywhere we
   look up the L25 book or kline close. Re-run corrected backtest with this
   75 ms latency and compare hit rate / avg vwap delta to current.

3. **`min_book_events` filter**: drop markets with `<25` book update rows in
   `[ws_s − 60, slot_end_us]`. Add to `load_resolutions()` as optional kwarg
   `min_book_events=25`.

### Tier 2 — new alpha sources (medium effort)

4. **Pair arbitrage scanner**: write
   `strategy_lab/pair_arbitrage/scan_canonical.py` that walks
   `load_orderbook_l25_streaming(asset)` per asset, computes
   `best_ask_up + best_ask_down + 2 × poly_taker_fee_per_share(...)` at every
   second of every slug, flags rows where total < $1 with enough visible
   size. Universe: ~12 522 chainlink-resolved markets. Output: per-slug list
   of (timestamp_us, total_cost, expected_pnl, min_visible_size).

5. **Maker rebate path**: open a `momo_limit_*` variant that posts at the
   inside instead of taking. Use `fee_per_share × 0.20` as negative
   commission on fills. Cross-check vs production `maker_*` sleeves if any.

6. **Microprice imbalance** as a layer on top of momo: compute
   `imbalance = (bid_size − ask_size) / (bid_size + ask_size)` at `fire_us`,
   only fire when `imbalance > 0.57` in the side we want to take. This is
   the closest analog to "gate harder" requested in the storedata-agent
   follow-up.

### Tier 3 — engine plumbing (heavier lift, structural)

7. **Adopt NautilusTrader for ad-hoc strategies**: their stack gives us
   queue position + latency + fee curve for free. Our `book_walk_fill` plus
   pandas joins is faster to iterate, but for production-realism replay
   Nautilus is the better target. Keep our engine for batch sweeps, port
   one strategy (e.g. momo v1 corrected ws_s) to NautilusTrader as a
   reference implementation, compare PnL row-by-row.

8. **Staged-loading worker pools**: parallelize `load_orderbook_l25_streaming`
   per (asset, hour-bucket) with a `ThreadPoolExecutor(max_workers=8)` for
   the source-read stage. Current single-pass scan of 2.7 GB BTC parquet
   takes ~90 s on this machine; sharding hour buckets should cut to ~15 s.

9. **Cross-reference standing CI** (their `account_trade_replay` pattern):
   nightly job that pulls last 24 h of `trading.events.poly_updown_resolution`
   from VPS3, runs our corrected ws_s backtest on the same slugs, and
   asserts |hit_rate_backtest − hit_rate_live| < 5 pp. Fails CI if drift.

### Tier 4 — don't adopt

- **NautilusTrader as primary engine**: too heavy for our exploratory
  workflow. Our `book_walk_fill` + pandas approach is 100× faster per
  iteration and the value of queue-position modeling is small because our
  controller is pure taker.
- **Telonex vendor**: paid API, redundant given our PMXT-equivalent local
  L25 archive from VPS2.
- **PMXT archive**: their archive ends at hour granularity; ours has
  microsecond L25 + 1 Hz subsample. We have higher resolution; downgrading
  is silly.

---

## Three things this comparison validates about our setup

1. **Our `ws_s` discovery is unique to our pipeline.** PMXT has no equivalent
   trap because they never anchor on an external clock — every signal is
   read off the poly book itself. The bug surface we found doesn't exist in
   their engine, which is one reason their hit-rate claims (where they
   publish any) look more conservative than ours did pre-fix.

2. **Chainlink-only resolution filter is best practice.** PMXT trusts
   Polymarket's settled outcome implicitly. We've discovered that 9% of
   `market_resolutions_v2` is binance-derived (price_source =
   `binance-klines-1m`), and we filter those out. PMXT would silently
   inherit the contamination if they ever cross-checked against a binance
   signal — but they don't, so they never see it.

3. **Book-only baselines exist and are honest.** If `BookLateFavoriteTakerHold`
   with `min_midpoint=0.90` and `min_bid_price=0.88` shows ≥ 80% hit on our
   canonical universe (it should, by construction — favorites win ~85% of
   the time at p≥0.90), then we have a clean baseline to compare any
   external-signal strategy against. Our corrected momo at ~50% hit / ~28 pp
   below breakeven IS the answer: no external-signal edge on poly 5m at
   present fills. Their book-only baselines are the right comparison point.

---

## Files referenced in this comparison

| Their file | Our analog |
|---|---|
| `backtests/polymarket_btc_5m_late_favorite_taker_hold.py` | `strategy_lab/meta_classifier/momo_full_universe_validation.py` |
| `backtests/polymarket_btc_5m_pair_arbitrage.py` | (none — opportunity) |
| `strategies/late_favorite_limit_hold.py` | (none — see Tier 1.) |
| `strategies/binary_pair_arbitrage.py` | (none — see Tier 2.4) |
| `strategies/final_period_momentum.py` | `momo_full_universe_validation.py` (closest match) |
| `strategies/microprice_imbalance.py` | (none — Tier 2.6 candidate) |
| `strategies/core.py` (`LongOnlyPredictionMarketStrategy`) | `strategy_lab/book_walk.py` (lower-level only) |
| `docs/execution-modeling.md` (fee + latency + queue) | (scattered — codify in `strategy_lab/fees.py`) |
| `docs/data-loading.md` (staged loading, worker pools) | `data/v4/canonical/load.py` (single-thread) |
| `docs/account-ledger-replay.md` (live xref experiment) | `data/v4/canonical/_results/_xref_live.py` |

---

## End of comparison
