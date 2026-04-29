# Polymarket Strategy Hunt — Experiments Queue

**STATUS UPDATE 2026-04-28:** experiments 1-7 from the original queue have been TESTED. Results below the queue summary. Next session task is `NEXT_TASK_ALPHAPURIFY_ANALYSIS.md`. Original queue text preserved for reference.

---

## Queue status (2026-04-28)

| # | Experiment | Status | Result |
|---|---|---|---|
| 1 | Orderbook-realistic fills (book-walking) | ✅ DONE | E1 capacity ladder validated. BTC scales to $250, ETH to $100, SOL to $25-50 |
| 2 | Late entry timing sweep | ⏸ NOT DONE | Skipped — pivoted to alt-signal grid which superseded |
| 3 | Volume regime filter (z-score Binance vol) | ❌ TESTED NEGATIVE | All variants underperform baseline. q10 already encodes vol info |
| 4 | Microstructure entry filters (spread, depth) | ⚠️ BORDERLINE | spread<2% in-sample +4.54pp; holdout 4/8 cells positive. Pilot candidate |
| 5 | Time-of-day analysis | ⚠️ MIXED | Permutation passes; cross-asset Spearman weak. Don't deploy specific hour-pick |
| 6 | Cross-asset leader (BTC → ETH/SOL) | ✅ VALIDATED | 5m only: +5pp ROI lift, holdout 2/2 valid cells positive. **Deploying.** |
| 7 | Volatility-regime adaptive rev_bp | ❌ TESTED NEGATIVE | All variants underperform fixed rev_bp=5. q10 already selects for vol |
| 8 | Funding rate signal | ⏸ PARKED | Awaits May 1 backfill. Still on queue |
| 9 | Composite stacking | ⏸ PARTIAL | combo_q20 in-sample +26.32% (BTC×15m, n=48); not forward-walked |

Plus 5 strategies tested OUTSIDE original queue this session — see `../../session/SESSION_SUMMARY_2026_04_27_strategies.md` for the full 9-strategy audit.

---

## Next session task

**`NEXT_TASK_ALPHAPURIFY_ANALYSIS.md`** — analyze https://github.com/eliasswu/AlphaPurify, compare to our two backtest engines (Polymarket UpDown + Hyperliquid futures), produce a ranked steal list. ½ day budget.

After that, return to:
- E8 funding rate (after May 1 data lands)
- E9 composite stacking forward-walk
- E4 spread filter pilot on 5m × BTC (only cell with adequate holdout sample)

---

## Original queue text (preserved for reference)

**Predecessor:** [`../../session/SESSION_HANDOFF_2026_04_28.md`](../../session/SESSION_HANDOFF_2026_04_28.md). Read that first.

**Baseline to beat (now superseded):** `sig_ret5m_q20 + hedge-hold rev_bp=5` produced **75.8% WR / +20.4% ROI per trade** at q20×15m×ALL. **Updated baseline (2026-04-28):** the layered q10/q20 + maker-entry-15m + cross-asset-5m-ETH/SOL stack yields ~27% holdout ROI cross-asset.

**Validation gate for any new candidate:**
1. In-sample on full 5,742-market universe → CI excludes zero
2. Forward-walk 80/20 chronological split → holdout hit rate within ±5pp of train
3. Improves total PnL OR per-trade Sharpe vs the layered deployment matrix at the same universe slice

---

## Experiment 1 — Orderbook-realistic fill simulation (FOUNDATION)

### Why this is first

Every backtest result so far assumes **we hit the top-of-book ask at first snapshot at zero slippage**. At $1/trade this is roughly true; at $25+/trade we walk multiple levels. Live execution friction was estimated at ~10% PnL haircut — but we never measured it. **Fixing this changes every other experiment's numbers**, so do it once, then everything downstream is correctly calibrated.

### What to build

A "book-walking" fill simulator that takes a desired stake and the full 15-level orderbook snapshot, and returns the actual VWAP fill price.

**Input data we already have:**
- `orderbook_snapshots_v2` schema includes `bid_price_0..14`, `bid_size_0..14`, `ask_price_0..14`, `ask_size_0..14` per (market_id, outcome, ts_us).
- We've never extracted these levels; only level-0 was used in v3 trajectories.

### Step 1 — Extend trajectory extractor to capture full book

New file: `polymarket_extract_book_depth.sql` (template for any asset). For each (slug, 10s bucket, outcome), aggregate:

```sql
-- For each (market, bucket, outcome), capture top 5 levels of bid + ask
-- (level 5+ rarely matters at our stake sizes)
SELECT
  slug, bucket_10s, outcome,
  -- Use the snapshot closest to the bucket midpoint (one snap is enough at this density)
  (array_agg(ROW(bid_price_0, bid_size_0)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS bid_lvl0,
  (array_agg(ROW(bid_price_1, bid_size_1)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS bid_lvl1,
  (array_agg(ROW(bid_price_2, bid_size_2)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS bid_lvl2,
  (array_agg(ROW(bid_price_3, bid_size_3)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS bid_lvl3,
  (array_agg(ROW(bid_price_4, bid_size_4)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS bid_lvl4,
  (array_agg(ROW(ask_price_0, ask_size_0)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS ask_lvl0,
  (array_agg(ROW(ask_price_1, ask_size_1)  ORDER BY abs(timestamp_us - bucket_mid_us)))[1] AS ask_lvl1,
  ...
FROM orderbook_snapshots_v2
WHERE ...
```

Output: `data/polymarket/{asset}_book_depth_v3.csv` with 11 columns × 5 levels = ~30 cols.

### Step 2 — Fill simulator

```python
def book_walk_fill(book_levels, side: str, notional_usd: Decimal) -> tuple[Decimal, Decimal]:
    """
    Given orderbook levels and a desired notional, walk the book and return:
      (avg_fill_price, qty_filled)
    Returns (None, 0) if book can't fulfill the order at all.
    
    book_levels: list of (price, size) tuples sorted best-first.
    side: 'buy' (walks asks, ascending) or 'sell' (walks bids, descending).
    notional_usd: dollar amount to fill.
    """
    remaining = notional_usd
    total_cost = Decimal(0)
    total_qty = Decimal(0)
    for price, size in book_levels:
        if remaining <= 0:
            break
        # Cost to fully consume this level:
        level_cost = Decimal(price) * Decimal(size)
        if level_cost <= remaining:
            total_cost += level_cost
            total_qty += Decimal(size)
            remaining -= level_cost
        else:
            # Partial fill at this level
            take_qty = remaining / Decimal(price)
            total_cost += remaining
            total_qty += take_qty
            remaining = Decimal(0)
    if total_qty == 0:
        return None, Decimal(0)
    return (total_cost / total_qty), total_qty
```

### Step 3 — Re-run signal grid with realistic fills

Replace the `entry = entry_yes_ask` (single price) with `entry, qty = book_walk_fill(asks, 'buy', notional_usd)` in the simulator.

### Hypothesis to test

- At $1 stake: fill price within 0.5¢ of top-of-book ask. PnL nearly unchanged from current backtest.
- At $25 stake: fill price 1-3¢ worse. PnL haircut ~5-10%.
- At $100 stake: walks 2-3 levels. PnL haircut ~15-25%.

This calibrates our scaling expectations for live. Also exposes any markets where the book is too thin to support the stake at all (skip these).

### Effort: 1.5 days

---

## Experiment 2 — Late entry timing sweep

### The idea

Currently we enter at `window_start` (5/15min before resolve). At entry time, the only "fresh" information is `ret_5m` from Binance. But Binance keeps printing during the window — by 60s before resolve, we have 4 more minutes of price action to inform a 5m bet.

Trade-off:
- **Earlier entry:** longer time-in-position to capture the predicted move; but stale signal.
- **Later entry:** sharper signal (uses more of the actual window's price action); but less room for the position to play out.

### What to test

For each market, simulate entering at `window_start + N` for N ∈:
- 5m markets: `{0, 30, 60, 90, 120, 150, 180, 210, 240}`s (full set)
- 15m markets: `{0, 60, 120, 180, 240, 300, 480, 600, 720}`s

At each candidate entry time:
1. Refit `ret_5m` to use BTC close at *entry time* vs *entry time - 300s*.
2. Use the trajectory bucket's `up_ask_min` / `dn_ask_min` as entry price.
3. Run hedge-hold from there to resolution.

### Hypothesis

The "sweet spot" is probably **somewhere between `T-180s` and `T-60s`** for 5m markets — fresh enough to use real intra-window action, late enough that hedge-hold can still trigger if needed.

For 15m markets, late entry has more time to spare; sweet spot probably around `T-300s` to `T-120s`.

### Implementation

New file: `polymarket_late_entry_sweep.py`. Reuse v3 features, just change which 1m close pair is used for ret_5m. Need to fetch 1m close at arbitrary timestamps (not just window_start) — already supported by `asof_close()` helper.

### Effort: 1 day

---

## Experiment 3 — Volume regime filter

### The idea

Binance volume varies hugely by hour. Asia overnight is often 1/3 of US peak. **Low volume → low information content → noise dominates.** Filter to high-volume markets only.

### What to compute

For each market at `window_start`:
- `vol_z = (volume_5m_now - mean_5m_24h) / std_5m_24h` (rolling 24h z-score of 5m Binance volume)
- `vol_z_15m` similar over 15m bars

### Filters to test

- Skip if `vol_z < -0.5` (below average)
- Skip if `vol_z < 0` (below median)
- Trade only when `vol_z > +1` (significantly above average) — strict version

### Hypothesis

Hit rate jumps 3-5pp on high-volume subset. PnL per trade rises but trade count drops — breakeven analysis required.

### Effort: ½ day

---

## Experiment 4 — Microstructure entry filters

### The idea

Some markets at window_start are quotation-thin or have wide spreads. These have:
- Worse fills
- Worse signal-to-fee ratio  
- More slippage on hedge orders

Pre-filter them out at entry time.

### Features to compute (per market at window_start)

| Feature | Formula | Skip threshold (initial guess) |
|---|---|---|
| `spread_pct` | `(ask - bid) / mid` | skip if > 4% (wide spread) |
| `top_size_usd` | `entry_yes_ask_size * entry_yes_ask` | skip if < $20 (no depth) |
| `book_imbalance` | `(yes_size_0 - no_size_0) / (yes_size_0 + no_size_0)` | already tested in univariate; weak signal |
| `n_levels_yes` | count of non-null `ask_price_*` levels | skip if < 3 |

### Hypothesis

Spread filter and depth filter together remove the worst 10-20% of markets and lift hit rate by 2-4pp. We've already shown `book_imbalance` is weak as a directional signal — but as a quality filter (skip thin-book markets) it might still help.

### Effort: ½ day (most of the data is already in v3 markets CSV; spread is a quick add)

---

## Experiment 5 — Time-of-day analysis

### What to compute

For each resolved market, bin by:
- UTC hour of `window_start` (0-23)
- Day of week (0=Mon ... 6=Sun)

Compute hit rate, PnL per trade, hedge-trigger rate per bin.

### Hypothesis

- **Best hours**: US morning (13-17 UTC) — high volume, directional moves
- **Worst hours**: Asia overnight late (00-04 UTC) — low volume, mean-reverting chop
- **Weekend effect**: probably reduced edge on Saturdays (low pro flow)

### Output

A heatmap PNG `reports/POLYMARKET_TIME_OF_DAY.png` + a per-hour table. Then test "skip hours below break-even" filter.

### Effort: half day. Trivial pandas groupby on existing features CSV.

---

## Experiment 6 — Cross-asset leader signal

### The idea

In crypto, BTC moves are leading indicators for ETH/SOL on short timeframes. The lag is ~10-60s typically (correlated assets follow BTC's price-discovery role).

### What to test

For each ETH UpDown market: compute `BTC ret_5m` at `eth_window_start - K` for K ∈ {0, 30, 60, 90, 120}. Test as a co-signal alongside ETH's own ret_5m.

Variant: the **divergence signal** — when BTC and ETH 5m returns disagree, the lagging asset usually catches up to the leader. So if `BTC ret_5m > 0` but `ETH ret_5m ≤ 0`, expect ETH to follow → bet UP on ETH.

### Hypothesis

ETH and SOL win rate increases 2-4pp when BTC's signal agrees. Bigger lift on SOL (further down the lag chain).

### Effort: 1 day. Need to load all 3 asset klines and align timestamps.

---

## Experiment 7 — Volatility-regime adaptive

### The idea

`rev_bp = 5` works on average. But on **high-vol days** (BTC printing 1%+ in 5min routinely), 5bp triggers fire constantly = over-hedging. On **low-vol days** (BTC <0.1% in 5min), 5bp triggers rarely fire = under-hedging.

Make `rev_bp` adaptive to recent volatility.

### What to compute

Per market at window_start:
- `atr_15m_btc` = average of `(high - low)/close` over last 96 × 15min bars (24h)
- Map to `rev_bp_dynamic = clip(rev_bp_base * atr_ratio, 3, 20)` where `atr_ratio = atr_now / atr_24h_avg`

### Hypothesis

Adaptive `rev_bp` lifts PnL 5-15% over fixed `rev_bp=5` by hedging proportionally to current vol regime.

### Effort: 1 day.

---

## Experiment 8 — Funding rate signal (PARKED — May 1)

### Status

`binance_funding_rate_v2` only covers Mar 1-31. Apr backfill expected ~May 1.

### What to test once data lands

For each market at window_start:
- `funding_rate_now` (most recent 8h)
- `funding_rate_avg_3d` (mean of last 9 fundings)
- `funding_z` (z-score)

Hypothesis: persistent positive funding (longs paying) = crowded long → fade UP signal. As an entry filter or as an additional signal in a composite.

### Effort: 1 day after data lands.

---

## Experiment 9 — Composite stacking

### The idea

After Experiments 2-7 produce candidate features, stack them. Don't fit a black-box ML model; use simple rule-based composition with explicit gates.

### Two stacking patterns

**Pattern A — Conjunctive (AND):** trade only when N independent signals agree.
- Example: `sig_ret5m AND vol_z>0 AND hour∈[13,17]` → trade.
- Cuts trade count, raises hit rate.

**Pattern B — Disjunctive with confidence boost:** trade when sig_ret5m fires; size bigger when secondaries agree.
- Example: `if sig_ret5m AND smart_minus_retail agrees: stake = 2x`. Default stake = 1x.

### Validation

Same forward-walk gate. Composite must beat each individual signal on holdout.

### Effort: ½ day per composition pattern, after E2-E7 produce inputs.

---

## Recommended sequencing

| Order | Experiment | Why this order |
|---|---|---|
| **1** | Orderbook-realistic fills (E1) | Foundation — recalibrates everything else |
| **2** | Late entry timing (E2) | Big potential win, easy to test |
| **3** | Time-of-day (E5) | Quick win, generates session-filter ideas |
| **4** | Volume regime (E3) | Builds on E5 (volume-by-hour analysis) |
| **5** | Microstructure entry filters (E4) | Strengthens E1's recalibrated baseline |
| **6** | Cross-asset leader (E6) | Bigger code lift, do after E1-E5 simpler wins land |
| **7** | Volatility-regime adaptive rev_bp (E7) | Refinement on top of validated baseline |
| **8** | Composite stacking (E9) | After E2-E7 produce candidate features |
| **PARKED** | Funding rate (E8) | Awaits May 1 backfill |

---

## What "good" looks like for an experiment to ship

After running each experiment, write a short stub report `reports/POLYMARKET_EXP{N}_<NAME>.md` with:

1. **One-line hypothesis** + result (kept / rejected / replaced baseline)
2. **In-sample headline cell** vs current baseline
3. **Holdout cell** (chronological 80/20)
4. **Decision:**
   - **Ships:** holdout improves PnL or Sharpe vs baseline; CI tightens; train-holdout drift < 5pp
   - **Rejects:** no improvement OR clear overfitting (large train-holdout drift)
   - **Composes:** doesn't ship alone but improves a composite (E9)

Update [SESSION_HANDOFF_2026_04_27.md](SESSION_HANDOFF_2026_04_27.md) "Locked decisions" section if any experiment replaces a piece of the current baseline.

---

## What NOT to try (already explored, dead ends)

- **Kronos retrain** — failed OOD (52.9% Apr vs 60% Jan-Mar fit). Not worth more compute.
- **Bare momentum on Polymarket bars** (without Binance) — already in baseline grid as `signal_momentum`, lost to random.
- **L/S ratio raw as primary signal** — univariate showed weak edge alone (~52%); only useful as composite component.
- **Trailing stops** — whipsaw in the v1 grid; superseded by hedge-hold.
- **Tight targets <$0.55** — booked tiny wins, kept tail risk; bad on 5m.
- **Pure book-imbalance directional signal** — univariate was noise.

---

**End of experiments queue. Pick E1 to start.**
