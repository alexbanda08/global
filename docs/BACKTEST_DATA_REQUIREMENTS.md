# Backtest Data Requirements — Synthetic Covered Yes

For [COVERED_CALL_PREDICTION_STRATEGY.md](COVERED_CALL_PREDICTION_STRATEGY.md). Two halves: **perp side** (we have most of this) and **Polymarket side** (greenfield, hardest piece).

---

## 1. Polymarket binary data — THE CRITICAL GAP

For each BTC up/down market resolved over the backtest window:

| Field | Why | Granularity |
|---|---|---|
| `question_id`, `tenor`, `strike`, `direction` (up/down) | Identify each market | per question |
| `created_at`, `resolution_at` | Match to perp timestamps | UTC, ms |
| `resolution_outcome` (YES / NO) | Ground truth payoff | per question |
| **Order book snapshots** (bid/ask + size, top 5 levels) | Realistic fills, not midpoint fantasy | **≥ 1/min**, ideally 5–10s |
| **Trade tape** (px, size, side) | Volume sanity, market impact | tick-level |
| 24h volume per question | Liquidity gate (we cap size at 5% of vol) | hourly |
| Fee schedule history | Net premium calc | per epoch |

**How to get it:**
- Polymarket public API: `gamma-api.polymarket.com` for question metadata + outcomes.
- CLOB (Central Limit Order Book) API for live book; **historical books are not freely served** — must scrape going forward, or buy from a data vendor (Kaiko, Amberdata sometimes carry).
- Practical fallback: scrape **trade tape + last-traded price** at 1m bars from the public API → reconstruct synthetic mid. Lossy but tractable.

**Coverage target:** at least 12 months of 5m / 15m / 4h / 24h BTC binaries. If 5m markets don't have enough history yet (Polymarket only added them recently), drop to 15m+ for the first backtest pass.

---

## 2. BTC perpetual futures data

| Field | Granularity | Source |
|---|---|---|
| OHLCV | **1m bars minimum** (5m / 15m scalps need intra-bar) | Binance, Bybit, Hyperliquid public APIs |
| **Tick / trade prints** for slippage modeling on high-lev scalps | tick-level on backtest dates | Binance Vision dumps (free) |
| **Order book L1 (bid/ask + size)** for realistic fill prices | 100ms or 1s snapshots | Tardis.dev (paid), Binance depth stream |
| **Mark price** (separate from last) | 1s | venue API — needed for liquidation math |
| **Funding rate history**, 8h cadence | each funding tick | venue API, free |
| **Maintenance-margin tier** schedule | per leverage band | venue docs, static |
| **Liquidation-engine spec** (insurance fund, ADL behavior) | static | venue docs |

Liquidation modeling at 60–70× cannot be done with bar data alone. **Tick or 1s book snapshots are mandatory** for the high-lev sleeve — otherwise the backtest will lie about whether your stop got slipped through.

---

## 3. Volatility / fair-value model inputs

The premium-harvest fair-value (Section 2.3) needs realized vol from the perp tape:

- Rolling realized σ over 1h, 4h, 24h windows from 1m returns → already derivable from data in §2.
- Optional: Deribit BTC IV index history (deribit.com/api/v2 or Genesis Volatility) as a sanity overlay on the binary's implied prob. Lets you measure whether Polymarket binaries are systematically above/below listed-options IV.

---

## 4. Macro / regime tags (optional but useful)

For regime-conditional analysis (does the strategy work in trends vs. chop?):
- BTC realized regime label per day (trend / chop / vol-spike) — derivable from the OHLCV.
- US economic-calendar prints (CPI, FOMC) — Trading Economics CSV, FRED API. To bucket performance by macro events.
- Crypto-specific event flags (halvings, ETF flow days) — manual list.

---

## 5. Minimum viable dataset (MVP backtest)

If you want to start *now* with what's gettable in a week:

- ✅ 12mo 1m BTC perp OHLCV from Binance — **free, scriptable**.
- ✅ 12mo Binance funding rate — **free**.
- ⚠️ 6mo of Polymarket BTC question metadata + resolution outcomes via public API — **scrapable, but no historical book** → reconstruct from trade tape only.
- ❌ Polymarket order book history → **scrape going forward 30–60d** before any high-lev sleeve goes live. Backtest the long-tenor / low-lev sleeve first while collecting.

**Backtest order of operations:**
1. **Phase 1**: 24h binary + 2× perp sleeve. Bar-data sufficient. Validates the core thesis.
2. **Phase 2**: 4h binary + 5× perp sleeve. Needs 1m bars + funding. Still bar-feasible.
3. **Phase 3**: 15m / 5m + high-lev sleeve. Blocked until tick / book data is in. Don't fake it.

---

## 6. Storage & format

- Parquet, partitioned by date and instrument. Same convention the existing `data/` directory uses.
- One file per `(market, tenor, date)` for Polymarket; one per `(symbol, date)` for perp.
- Schema: timestamp_utc_ns, side, px, size, source.
- Total rough size: 12mo 1m BTC OHLCV ~10 MB; 1s book ~30 GB; tick trades ~50 GB. Polymarket scrape ~1–5 GB.
