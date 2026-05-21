# TV Agent Spec — Wallet Decoder feature

_Target: TV (TradingVenue) agent on VPS3. Productionize the strategy_lab
wallet hunter as a continuously-running feature that watches a list of
profitable Polymarket wallets, decodes their strategies, and emits
shadow-trade decisions for our engine to mirror._

_Status: spec for TV agent to implement. Reference implementation lives
in `strategy_lab/wallet_hunt/` (Python prototype that we ran end-to-end
this session)._

---

## 0. One-paragraph summary

Build a "WalletDecoder" service that polls Polymarket data-api for a
configured list of wallets, classifies each wallet's strategy
behaviorally, computes realized PnL vs our internal benchmark,
auto-promotes winners to shadow-trade mode, and emits per-fire
recommendations our momo controller can mirror. End goal: convert
profitable third-party wallet strategies into our own shadow sleeves
within hours of detection.

---

## 1. Data sources

### Polymarket data-api (read-only, public)

| Endpoint | Use | Notes |
|---|---|---|
| `GET https://data-api.polymarket.com/trades?user=<wallet>&limit=500&offset=0` | Trade history paged 0..3500 | After 3500: re-paginate with `&end_time=<earliest_ts>` |
| `GET https://data-api.polymarket.com/positions?user=<wallet>` | Open positions snapshot | Single shot |
| `GET https://data-api.polymarket.com/value?user=<wallet>` | Portfolio current value | Single shot |
| `GET https://data-api.polymarket.com/activity?user=<wallet>` | All on-chain activity (mints, splits, transfers) | Optional |

**param fallback**: if `user=<addr>` returns empty, retry with
`proxyWallet=<addr>` (some Polymarket users have separate EOA + Gnosis
Safe; trades index by the Safe address as `proxyWallet`).

**Rate limit**: ~10 rps is safe. Sleep 100ms between requests. Plan for
~30 min cold pull per wallet (3500 trades, 7 endpoint pages, then 7
more end_time pages).

### Polymarket CLOB (already used for canonical)

| Endpoint | Use |
|---|---|
| `GET https://clob.polymarket.com/markets/<condition_id>` | Get `tokens[*].winner` for resolved markets — outcome truth |

Cached in `data/v4/canonical/clob_resolutions_cache.parquet`. Hit-rate
during decode: high (every market a wallet traded should already be in
the cache if we ran `clob_resolutions.py --crosscheck` once). If not,
fall back to gamma API + chainlink RTDS.

### Internal data we have (canonical)

- `load_resolutions(..., with_clob_winner=True)` — outcome truth
- `load_klines_asof("BTC"/"ETH"/"SOL")` — binance momentum decode
- `load_orderbook_l25_streaming(asset, slugs=...)` — for backtest replication

---

## 2. Service design

### 2.1 Components

```
WalletDecoder (one TV agent module)
  ├── WatchList            (postgres table: wallets + status)
  ├── Fetcher              (asyncio worker: cold-pull + delta polling)
  ├── Fingerprinter        (classifies behavior every N hours)
  ├── PnL Accountant       (computes realized PnL with engine_v2 fees)
  ├── Promotion Engine     (auto-promotes wallets above $X/leg threshold)
  ├── Shadow Trader        (mirrors decisions of promoted wallets)
  └── HTTP / Discord API   (status + alerts)
```

### 2.2 Postgres tables (under TV's schema)

```sql
CREATE TABLE wallet_decoder.watched_wallets (
  wallet              TEXT PRIMARY KEY,         -- 0x-prefixed lowercase
  user_param          TEXT NOT NULL DEFAULT 'user',  -- 'user' | 'proxyWallet'
  alias               TEXT,                     -- human label
  added_at            TIMESTAMPTZ DEFAULT NOW(),
  status              TEXT NOT NULL DEFAULT 'fetching',
                        -- fetching | fingerprinting | watching | promoted | rejected
  notes               TEXT
);

CREATE TABLE wallet_decoder.trades (
  wallet              TEXT NOT NULL,
  tx_hash             TEXT,
  asset               TEXT NOT NULL,            -- token_id (Up/Down)
  condition_id        TEXT NOT NULL,
  slug                TEXT,
  side                TEXT,                     -- BUY / SELL
  size                NUMERIC,
  price               NUMERIC,
  outcome             TEXT,                     -- Up/Down — Polymarket label
  timestamp_s         INTEGER,                  -- unix seconds
  fetched_at          TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (wallet, tx_hash, asset)
);

CREATE TABLE wallet_decoder.fingerprints (
  wallet              TEXT NOT NULL,
  fingerprint_at      TIMESTAMPTZ DEFAULT NOW(),
  n_trades            INTEGER,
  time_span_hours     NUMERIC,
  trades_per_minute   NUMERIC,
  side_buy_pct        NUMERIC,
  up_down_focus_pct   NUMERIC,
  avg_trades_per_leg  NUMERIC,
  leg_pct_both_sides  NUMERIC,
  avg_buy_px_med      NUMERIC,
  strategy_class      TEXT,                     -- e.g. 'PYRAMID_TAKER|SCALPER'
  notes               TEXT,
  PRIMARY KEY (wallet, fingerprint_at)
);

CREATE TABLE wallet_decoder.leg_pnl (
  wallet              TEXT NOT NULL,
  condition_id        TEXT NOT NULL,
  outcome             TEXT NOT NULL,
  n_trades            INTEGER,
  buy_shares          NUMERIC,
  sell_shares         NUMERIC,
  avg_buy_px          NUMERIC,
  avg_sell_px         NUMERIC,
  resolved            BOOL,
  won                 BOOL,
  net_pnl             NUMERIC,                  -- engine_v2 fee curve
  resolved_at         TIMESTAMPTZ,
  PRIMARY KEY (wallet, condition_id, outcome)
);

CREATE TABLE wallet_decoder.shadow_trades (
  id                  BIGSERIAL PRIMARY KEY,
  wallet              TEXT NOT NULL,            -- source wallet
  copied_at           TIMESTAMPTZ DEFAULT NOW(),
  condition_id        TEXT NOT NULL,
  slug                TEXT,
  side                TEXT,                     -- BUY (we follow)
  outcome             TEXT,                     -- Up/Down
  intended_size_usd   NUMERIC,                  -- our sizing (not source's)
  intended_fire_us    BIGINT,                   -- our planned fire wall-clock
  -- after the fact:
  matched_book_at_us  BIGINT,
  fill_vwap           NUMERIC,
  fill_shares         NUMERIC,
  realized_pnl        NUMERIC                   -- after resolution
);
```

### 2.3 Loops

**Fetcher loop (per wallet, ~1 worker per wallet, fires every 30s for promoted, every 1h for watching)**:

```
1. GET /trades?<user_param>=<wallet>&limit=200&offset=0
2. INSERT new rows into wallet_decoder.trades (ON CONFLICT DO NOTHING)
3. If new rows include resolved markets we haven't computed PnL for:
   - For each new (condition_id, outcome), fetch CLOB winner if missing
   - INSERT/UPDATE wallet_decoder.leg_pnl
4. If wallet is `promoted`:
   - For each NEW BUY trade in the last 30s, emit a shadow_trade row
     using our engine_v2 fill primitive at the same timestamp
```

**Fingerprint loop (per wallet, runs every 24h or after 500 new trades)**:

```
1. Read all wallet_decoder.trades for this wallet
2. Compute behavioral fingerprint (see §3 for algorithm)
3. INSERT into wallet_decoder.fingerprints
4. Update wallet_decoder.watched_wallets.status:
   - If net_pnl per resolved leg >= $5: status='promoted'
   - If net_pnl per resolved leg <= -$5 for 14+ days: status='rejected'
   - Else: status='watching'
```

**Promotion loop (runs daily)**:

```
1. List wallets with status='watching' that have >= 50 resolved legs
   in the last 14 days
2. For each, compute trailing-14d PnL per resolved leg
3. Promote top-3 wallets to status='promoted'; demote any below threshold
4. Discord alert on status changes
```

---

## 3. Decoder algorithm — what each component does

### 3.1 Fingerprinter (Python prototype: `strategy_lab/wallet_hunt/fingerprint.py`)

Compute these features per wallet:

```
- n_trades                  — total trades fetched
- time_span_hours            — last_ts - first_ts
- trades_per_minute          — rate
- side_BUY_pct               — % of trades that are BUYs
- up_down_focus_pct          — % of trades on BTC/ETH/SOL up-down markets
- avg_trades_per_leg         — fills per (condition_id, outcome)
- leg_pct_single_trade       — % of legs with exactly 1 trade
- leg_pct_both_sides         — % of legs with BOTH a BUY and a SELL
- avg_buy_px_med             — median avg buy price across legs
- intra_leg_gap_med_s        — median seconds between fills inside one leg
```

Classify into one or more buckets:
```
PYRAMID_TAKER       if avg_trades_per_leg >= 5 AND leg_pct_only_buys > 70
SINGLE_FIRE_TAKER   if leg_pct_single_trade > 50
MAKER_BOTH_SIDES    if leg_pct_both_sides > 30
LATE_FAVORITE       if avg_buy_px_med >= 0.85
DEEP_VALUE_UNDERDOG if avg_buy_px_med <= 0.15
CLOSE_BEFORE_RESOLVE if leg_pct_held_to_resolution < 20
SCALPER             if intra_leg_gap_med_s < 5
```

### 3.2 PnL Accountant (Python prototype: `strategy_lab/wallet_hunt/_run_all.py`)

For each (condition_id, outcome) leg:

```
leftover_shares  = buy_shares - sell_shares
leftover_value   = leftover_shares × (1.0 if won else 0.0)
leftover_cost    = avg_buy_px × leftover_shares
leftover_pnl     = leftover_value - leftover_cost
realized_pnl     = (avg_sell_px - avg_buy_px) × min(buy_shares, sell_shares)

# Real Polymarket fees on every fill
entry_fees       = buy_shares  × 0.07 × avg_buy_px  × (1 - avg_buy_px)
exit_fees        = sell_shares × 0.07 × avg_sell_px × (1 - avg_sell_px)

net_pnl          = realized_pnl + leftover_pnl - entry_fees - exit_fees
```

Side-decode hypothesis testing (one row per leg with `binance_says`
column):
```
ret_2m_pre  = log(binance@(slot_start) / binance@(slot_start - 120))
binance_says = 'Up' if ret_2m_pre > 0 else 'Down'
matches      = outcome == binance_says
```

Then compute:
- WR overall
- WR when matches binance
- WR when contradicts binance

If the spread `WR(contra) - WR(match) > 15 pp` AND
`abs(WR(contra) - 50) > 10 pp`, flag as a CONTRARIAN strategy worth
shadow-trading.

### 3.3 Promotion Engine

```
Promote wallet to status='promoted' if:
  - n_resolved_legs >= 50 in trailing 14d
  - net_pnl_per_resolved_leg >= +$5
  - 14d sharpe (daily PnL) > 1.0 (computed from leg_pnl.resolved_at + net_pnl)
  - WR(contradict_binance) - WR(matches_binance) >= 10 pp OR
    strategy_class is DEEP_VALUE_UNDERDOG with median margin >= +$1

Demote (status='rejected') if:
  - 14d net_pnl <= -$500
  - status='promoted' AND 7d net_pnl_per_leg <= -$2

Re-evaluate weekly.
```

### 3.4 Shadow Trader

When a `promoted` wallet executes a new BUY on a market in our supported
universe (BTC/ETH/SOL up-down 5m/15m on Polymarket):

```python
# In our momo controller (poly_updown_loop.py), add:
def on_shadow_wallet_trade(wallet, trade):
    if wallet not in PROMOTED_WALLETS:
        return
    # Mirror the decision but use OUR sizing/fill logic
    cid, outcome, source_ts = trade.conditionId, trade.outcome, trade.timestamp_s
    fire_us = (source_ts + 1) * 1_000_000   # mirror with +1s lag (our fetch latency)
    # Use engine_v2 (production-realism)
    cfg = LiveMimicConfig()
    decision = build_decision(
        condition_id=cid,
        outcome=outcome,
        notional_usd=PROMOTED_SIZE_USD[wallet],   # per-wallet capital allocation
        fire_us=fire_us,
        max_spread=SPREAD_FILTER[asset_of(cid)],
        source="wallet_shadow",
        meta={"source_wallet": wallet,
              "source_tx_hash": trade.tx_hash,
              "source_price": trade.price},
    )
    submit_decision(decision)
```

Insert a row into `wallet_decoder.shadow_trades` for tracking. Post-
resolution, fill in `realized_pnl` so we can compare our shadow PnL vs
the wallet's PnL.

---

## 4. Operational guardrails

### 4.1 Sizing caps

- Per-wallet cap: $50/trade initially, $250/trade after 7 days positive
- Aggregate cap: 25% of total capital can be in shadow trades at any time
- Per-market cap: max 2 shadow positions per market (one Up, one Down,
  no doubling up)

### 4.2 Filters before mirroring

```
Skip the shadow trade if any of:
  - market is 5m (we know 5m underperforms — only mirror 15m)
  - market is not BTC/ETH/SOL (out of scope)
  - market has < 25 book events in last 60s (sparse-book filter)
  - source price is more than $0.05 from our WS L25 best-ask at fire time
      (REST-lag protection — they may have been filling stale REST prices)
  - spread > 0.02 (BTC/ETH) or 0.025 (SOL)
  - we already have ≥ 2 open positions on this market
```

### 4.3 Kill switches

- 24h cumulative shadow PnL < −$500 → pause shadow trader
- 7d cumulative shadow PnL < −$2,000 → demote ALL wallets to 'watching'
- Source wallet WR drops below 45% over trailing 50 legs → demote that wallet

### 4.4 Discord alerts

- Wallet promoted / demoted → channel `#wallet-decoder-promotion`
- Shadow trade fired (with source wallet, market, our PnL prediction) → `#wallet-decoder-trades`
- Kill switch triggered → `@channel #wallet-decoder-alerts`
- Daily summary digest (top-3 wallets, our PnL, divergence vs source) → `#wallet-decoder-daily`

---

## 5. HTTP API

```
GET /wallet-decoder/wallets
  → list all watched wallets + status + last fingerprint

GET /wallet-decoder/wallets/<addr>/summary
  → fingerprint + PnL + strategy_class + open positions

GET /wallet-decoder/wallets/<addr>/trades?limit=100
  → recent trades from this wallet

POST /wallet-decoder/wallets
  body: {wallet, alias, notes}
  → add a wallet to watch list (status='fetching')

DELETE /wallet-decoder/wallets/<addr>
  → remove a wallet (also marks status='rejected', stops fetcher)

GET /wallet-decoder/shadow-trades?since=2026-05-16
  → our shadow fills, with source wallet attribution and live PnL

GET /wallet-decoder/leaderboard
  → ranked by net_pnl_per_resolved_leg (trailing 14d, min 50 legs)
```

---

## 6. Reference Python implementation (this session)

```
strategy_lab/wallet_hunt/
  fetch_many.py            ← Fetcher prototype (handles user= / proxyWallet= fallback,
                             pagination via offset then end_time)
  fingerprint.py           ← Fingerprinter prototype (classification logic)
  _run_all.py              ← Orchestrator: fingerprint + PnL decode for N wallets
  cache/<short>/           ← Per-wallet artifacts
  cache/_wallet_summary.json  ← Output of _run_all.py
```

Validated on 6 real wallets in `WALLET_HUNT_MULTIWALLET_2026_05_16.md`.

Two of the 6 are confirmed profitable winners (`0xce25e214`, `0x04b6d7e9`);
both on BTC 15m specifically. The contrarian-fade-binance pattern shows
the same WR signature (63% contra, 38% match) across multiple wallets,
validating the pattern is robust.

---

## 7. Phased rollout

| Phase | Scope | When | Owner |
|---|---|---|---|
| **0** | Spec review with strategy_lab | this session | – |
| **1** | Postgres tables + Fetcher only (no shadow trades) | week 1 | TV agent |
| **2** | Fingerprinter + PnL Accountant + HTTP API | week 1 | TV agent |
| **3** | Promotion Engine (autonomous) + Discord alerts | week 2 | TV agent |
| **4** | Shadow Trader (PAPER only, no real fills) | week 2 | TV agent |
| **5** | Live shadow with $50/trade cap, BTC 15m only | week 3 | TV + manual approval |
| **6** | Expand to all assets, scale caps based on observed PnL | week 4+ | TV |

Phase 5 is the first real-money fire. Requires manual sign-off after 7
days of clean Phase 4 paper trading matching predicted PnL within 10%.

---

## 8. Open questions

1. **Maker rebate path**: 0x89b5cdaa runs a market-maker strategy with
   35.9% both-sides legs. Our shadow trader is taker-only. Do we want to
   add maker support? Requires Phase 7 — separate spec.
2. **Flash-event detection**: 0x7cde1da9 traded 3,013 times in 5 minutes.
   The trigger that activated this bot is unknown. Could be valuable to
   detect (it's clearly responding to SOMETHING) but out of scope for
   v1.
3. **Cross-wallet correlation**: when multiple promoted wallets BUY the
   same side of the same market within a short window, our confidence
   in the trade is higher. Should size up. Specify a multiplier rule.
4. **Wallet discovery**: this spec assumes we hand-pick wallets. A future
   feature: crawl Polymarket leaderboards / on-chain top-PnL wallets and
   auto-add candidates above $50K all-time PnL.

---

## End of spec
