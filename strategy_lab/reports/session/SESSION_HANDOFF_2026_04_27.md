# Session Handoff — Polymarket UpDown — 2026-04-27

**Read this first in the next session.** Everything below is the current state of the project, what's locked, what's open, and where to look.

---

## TL;DR — Where we are

✅ **First validated edge found.** `sig_ret5m` (sign of Binance close ratio over prior 5min) hits **75.8% win rate / +20.4% ROI per trade** at q20×15m×ALL with hedge-hold exit at rev_bp=5. Forward-walk holdout passes (87.2% holdout hit, CI strictly excludes zero).

✅ **Cross-asset confirmed.** Works on BTC + ETH + SOL × 5m + 15m. 5,742 markets sampled Apr 22-27.

✅ **Live deployment plan documented.** Phase 18 spec for Tradingvenue is in [TV_STRATEGY_IMPLEMENTATION_GUIDE.md](TV_STRATEGY_IMPLEMENTATION_GUIDE.md) — strategy, hedge-hold exit, redemption worker, $1/trade micro-live. **Implementation handed to TV agent in their session.**

🎯 **This session's job:** find MORE strategies. Try new feature families: late entry timing, volume regimes, orderbook-realistic fills, microstructure, time-of-day effects.

---

## What's locked (don't redo)

| Decision | Value | Why locked |
|---|---|---|
| Primary signal | `sig_ret5m = sign(log(BTC_close[ws] / BTC_close[ws-300]))` | p=3e-6, holdout-validated |
| Exit rule | hedge-hold (buy opposite side at ask, hold to resolution) | Beats direct sell + merge in stress, simpler infra |
| Reversal threshold | `rev_bp = 5` | Sweet spot 3-8, picked 5 for train-holdout consistency |
| Stake floor | $1/slot OK (fractional shares) | Polymarket supports it |
| Redemption | `redeemPositions([1,2])` on CTF after resolution | No auto-redeem; we must call |
| Out of scope | `mergePositions()`, `splitPosition()`, NegRiskAdapter, ERC-1155 approvals | Hedge-hold supersedes merge |

If a new strategy beats sig_ret5m on holdout, **fine to replace it**. Otherwise leave it alone.

---

## Data available (all on VPS, all locally extracted for the BTC universe)

### On VPS (Postgres @ `127.0.0.1:5432`, db=`storedata`, user=`tradingvenue_ro`)

| Table | Rows (as of Apr 27) | Cadence | Coverage |
|---|---|---|---|
| `markets` | active universe | live | metadata, condition_ids, slugs, neg_risk |
| `market_resolutions_v2` | 5,689 resolved | per-resolution | strike + settle from Chainlink, outcome, slot times |
| `orderbook_snapshots_v2` | **13.58M** (TimescaleDB hypertable) | sub-second | 15 bid/ask levels per (market_id, outcome, ts_us) |
| `binance_klines_v2` | 1m/5m/15m for BTC/ETH/SOL spot | 1MIN density | 2026-01-22 → present |
| `binance_metrics_v2` | 1,729 BTC + 1,729 ETH + 1,729 SOL | 5MIN | OI + L/S ratios + taker buy/sell ratio |
| `binance_funding_rate_v2` | only Mar 1-31 | 8h | **GAP: Apr backfill expected May 1** |

### Locally extracted (in `data/polymarket/` and `data/binance/`)

| File | Rows | Asset | Notes |
|---|---|---|---|
| `{btc,eth,sol}_markets_v3.csv` | ~1,900 each | per-asset | resolved markets with strike/settle/outcome |
| `{btc,eth,sol}_trajectories_v3.csv` | 140-160k each | per-asset | 10s buckets, bid/ask first/last/min/max for both YES and NO |
| `{btc,eth,sol}_klines_window.csv` | 10,944 each | per-asset | Apr 21-27 OHLCV at 1m/5m/15m |
| `{btc,eth,sol}_metrics_window.csv` | 1,729 each | per-asset | OI + L/S features |
| `{btc,eth,sol}_features_v3.csv` | ~1,900 each | per-asset | computed features per market at window_start |
| `all_features_v3.csv` | 5,742 | combined | merged with `asset` column |

### Key derived knowledge

- **Hit rate of underlying ret_5m signal:** ~58% on full universe, ~63% on q20 filter
- **Hedge trigger rate at rev_bp=5:** ~27% (5m), ~47% (15m), ~63% (q20×15m)
- **Avg BTC move per window:** 0.063% on 5m, 0.110% on 15m
- **Polymarket break-even:** ~53% hit rate (fees+spread)
- **Resolution source:** Chainlink Data Streams, 100% of rows
- **Entry quote timing:** p50 gap = 0s vs window_start, p90 = 16s, p99 = 39s — clean

---

## What we have NOT exploited yet

The orderbook snapshots table has **15 bid + 15 ask levels per snapshot** (`bid_price_0` through `bid_price_14`, etc.) at sub-second cadence. We've only used `bid_price_0` / `ask_price_0` (top-of-book) and 10s aggregates.

**Untapped richness:**
- Full book depth (15 levels each side)
- Real intra-second order arrival rate
- Liquidation-style book moves
- Spread dynamics
- Maker/taker imbalance

**Untapped signals:**
- Funding rate (May 1 backfill)
- Per-asset L/S ratio extremes (univariate test showed 15m smart-vs-retail at 60% top-Q hit; not yet integrated into composite)
- Cross-asset (BTC ret predicts ETH/SOL outcome?)
- Time-of-day (Asia/EU/US session effects)
- Volatility regime (trade differently in high vs low vol)

---

## Experiments queue for this session

See [POLYMARKET_NEXT_EXPERIMENTS.md](POLYMARKET_NEXT_EXPERIMENTS.md) for detailed specs of each. Priority order:

1. **Orderbook-realistic fill simulation** — replace top-of-book entry assumption with book-walking logic. **Foundational** — affects every other backtest's accuracy. Do this first.
2. **Late entry timing sweep** — enter at `window_start + N` for N ∈ {0, 30, 60, 120s} (5m) and {0, 60, 180, 300s} (15m). Hypothesis: fresher signal at later entry wins, even if window-time is shorter.
3. **Volume regime filter** — z-score Binance volume vs 24h rolling. Skip low-volume markets. Hypothesis: signal noise correlates with low volume.
4. **Microstructure entry filters** — spread, book imbalance, top-of-book size. Hypothesis: thin-book markets have worse fills + worse signal-to-fee ratio.
5. **Time-of-day** — bin by UTC hour, find best/worst sessions. Hypothesis: Asia overnight (low vol) fails; US morning (high vol) works.
6. **Cross-asset leader** — BTC ret predicts ETH/SOL? At what lag?
7. **Volatility regime** — ATR-like on Binance bars; adapt rev_bp by regime.
8. **Funding rate** — once May 1 backfill lands.

---

## Files to read for full context

If a fresh session needs more depth:

| Question | File |
|---|---|
| What did we try and find? | [STRATEGY_HUNT_FINDINGS_2026_04_27.md](STRATEGY_HUNT_FINDINGS_2026_04_27.md) |
| What does the v2 cross-asset grid show? | [STRATEGY_HUNT_V2_2026_04_27.md](STRATEGY_HUNT_V2_2026_04_27.md) |
| Best strategy stats? | [POLYMARKET_FULL_STATS.md](POLYMARKET_FULL_STATS.md) |
| Did the strategy generalize? | [POLYMARKET_FORWARD_WALK_V2.md](POLYMARKET_FORWARD_WALK_V2.md) |
| Why rev_bp=5? | [POLYMARKET_REVBP_FLOOR_SWEEP.md](POLYMARKET_REVBP_FLOOR_SWEEP.md) |
| What's in the DB? | [VPS_DATA_INVENTORY.md](VPS_DATA_INVENTORY.md) |
| Live deployment spec | [TV_STRATEGY_IMPLEMENTATION_GUIDE.md](TV_STRATEGY_IMPLEMENTATION_GUIDE.md) — handed to TV agent |
| What feature variants to try? | [POLYMARKET_NEXT_EXPERIMENTS.md](POLYMARKET_NEXT_EXPERIMENTS.md) ← THIS SESSION |

## Files to ignore (explicitly: don't waste time)

- `polymarket_baselines_grid.py` — pre-signal era, all baselines failed
- `polymarket_signal_grid.py` — superseded by `_v2`
- `polymarket_forward_walk.py` — superseded by `_v2`
- `polymarket_revbp_sweep.py` — superseded by `_revbp_floor_sweep.py`
- `polymarket_extract_markets.sql`, `_v2.sql` — superseded by `_v3` and `_xasset.sql`
- `polymarket_extract_trajectories.sql` — superseded by `_xasset.sql` and `_v3.sql`
- `kronos_*` files — Kronos failed OOD; do not retrain
- The 7 indexed GitHub bot repos — already mined for ideas; nothing else there

## Active code (use these as the foundation)

- `polymarket_extract_xasset.sql` — templated extractor (sed-substitute __ASSET__)
- `polymarket_extract_features.sql` — klines + metrics window export
- `polymarket_build_features_xasset.py` — feature builder for any asset
- `polymarket_signal_grid_v2.py` — exit-rule grid runner with hedge-hold
- `polymarket_revbp_floor_sweep.py` — combined IS sweep + forward-walk
- `polymarket_full_stats.py` — comprehensive WR / Sharpe / drawdown stats
- `polymarket_forward_walk_v2.py` — chronological holdout test

## VPS access (for new SQL extracts)

```bash
ssh -i "$HOME/.ssh/vps2_ed25519" -6 root@2605:a140:2323:6975::1
# DB env: /etc/storedata/collector.env
# OR via peer auth: sudo -u postgres psql -d storedata
```

**Important:** large `EXISTS (SELECT 1 FROM orderbook_snapshots_v2 ...)` queries can lock the table for tens of minutes. Always use bounded queries (filter by `slug` or short timestamp range). If a query hangs, kill it with `pg_cancel_backend(pid)`.

## TV (live trading) status

- Phase 17.2 ACTIVE in TV. Phase 18 plan-files not yet written.
- Strategy stubs in TV are STILL `naive-momentum` placeholder. Implementation guide handed off this session.
- Once TV agent ships Phase 18-01..18-05, they'll start producing real-trade telemetry. We can use that to retrain or compare against backtest.
- **Don't touch TV codebase from this strategy_lab session.** Only update it from the TV session.

---

**End of handoff. Start with the experiments queue.**
