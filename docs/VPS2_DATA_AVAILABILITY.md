# VPS2 Data Availability — Synthetic Covered Yes Backtest

**Connection verified:** `root@2605:a140:2323:6975::1` (vmi3236975) via `~/.ssh/vps2_ed25519`.
**DB:** Postgres @ 127.0.0.1:5432 / `storedata` / `tradingvenue_ro`. Password in `/etc/tv/tv-ro.env` (`TV_RO_PWD_PLAIN`).
**Snapshot date:** 2026-04-28.

---

## 1. Polymarket — what's there

**Window:** 2026-04-22 17:45 → 2026-04-28 22:00 UTC+02 (≈ 6 days continuous).

### `orderbook_snapshots_v2` (book history, top 21 levels per side)
- 16,867,958 snapshots, 7,302 distinct markets.
- Schema: `timestamp_us, market_id, slug, asset_id, outcome ∈ {Up,Down}, bid_price_0..20, bid_size_0..20, ask_price_0..20, ask_size_0..20`.

| Asset | Tenor | Distinct markets |
|---|---|---|
| BTC | 5m | **1,810** |
| BTC | 15m | **624** |
| ETH | 5m | 1,809 |
| ETH | 15m | 624 |
| SOL | 5m | 1,811 |
| SOL | 15m | 624 |

### `market_resolutions_v2` (ground truth)
| Tenor | Resolved | Up | Down |
|---|---|---|---|
| 5m | 5,335 | 2,692 | 2,643 |
| 15m | 1,779 | 886 | 893 |

Schema: `slug, ticker, timeframe, slot_start_us, slot_end_us, outcome, outcome_yes_price, outcome_no_price, resolution_source, last_trade_price`. Up/Down split is balanced (~50/50) — no obvious resolution-source bias on first look.

### `markets` metadata
Full Polymarket market dump including `volume`, `liquidity`, `volume_24h`, `yes_bid/ask`, `no_bid/ask`, `condition_id`, `clob_token_ids`. Inventory note flags this table as stale — verify currentness during loader build.

### `trades_v2`
6,367,536 trade prints (Polymarket fills). Useful for actual-traded-price baseline + signal sanity.

---

## 2. Binance — what's there

### `binance_klines_v2` — **1 full year**, 2025-04-27 → 2026-04-27
| Symbol | 1MIN | 5MIN | 15MIN | 1HRS | 4HRS | 1DAY |
|---|---|---|---|---|---|---|
| BTC/USDT spot | 525,600 | 105,120 | 35,040 | 8,760 | 2,190 | 365 |
| ETH/USDT spot | 525,600 | 105,120 | 35,040 | 8,760 | 2,190 | 365 |
| SOL/USDT spot | 525,600 | 105,120 | 35,040 | 8,760 | 2,190 | 365 |

Schema: `time_period_start_us, time_period_end_us, symbol_id, period_id, price_open/high/low/close, volume_traded, trades_count, quote_volume`.

⚠️ **Spot, not perp.** For 5m/15m horizon the basis is small (<10 bps usually); acceptable proxy for backtest. For live execution and liquidation modeling we'll need perp mark + index price — pull from Binance Vision (futures) for forward work.

### `binance_funding_rate_v2`
3,015 funding ticks across the year.

### `binance_metrics_v2`
Open interest, top-trader long/short ratio, taker long/short vol ratio. Useful for vol-of-vol regime tagging.

### `binance_liquidations_v2`
Present. Useful for tail-event flagging.

### `oracle_prices_v2`
1,190,205 rows. (Likely the resolution oracle feed — for auditing `market_resolutions_v2.resolution_source`.)

---

## 3. Mapping data → strategy spec

| Strategy leg | Data needed | Available? |
|---|---|---|
| Leg A — perp cover, 60–70× on 15m binary | 1m/5m BTC perp + funding | ✅ klines (spot proxy), ✅ funding |
| Leg A — perp cover, 40–60× on 5m binary | sub-minute BTC ticks for slippage at 60× lev | ⚠️ **only 1m bars** — slippage will be an *estimate* not a measurement |
| Leg A — 24h sleeve (2× core hold) | 24h Polymarket binaries | ❌ **NOT collected** — only 5m + 15m on VPS |
| Leg A — 4h sleeve (3–5×) | 4h Polymarket binaries | ❌ **NOT collected** |
| Leg B — premium harvest 5m / 15m | book history + resolutions | ✅ full L21 books, ✅ resolutions |
| Leg B — premium harvest 4h | 4h binaries | ❌ |
| Leg C — tail-hedge crash NO | far-OTM crash markets | ⚠️ exists in `markets`, scope TBD — query later |
| Fair-value model | realized vol from 1m perp | ✅ 525,600 BTC 1m bars |

### Key implications
1. **Phase 1 backtest is feasible TODAY** for the 5m + 15m high-lev sleeve. All required data is on VPS2.
2. **The 4h / 24h "low-lev covered call" arm is blocked** — no Polymarket data at those tenors. Either start scraping those tenors now (collector change) or drop them from scope.
3. **Slippage modeling at 60–70× lev** is the weakest link — only 1m bar granularity. Either:
   - Pull tick trades from Binance Vision for the 6-day window (~free, will run overnight), or
   - Use a conservative slippage assumption (e.g. 50% of 1m range) and stress-test sensitivity.
4. **6 days of Polymarket = ~7,100 resolved markets** — plenty for in-sample fit, **not enough for walk-forward**. We can:
   - Calibrate fair-value model now (clear signal in 6 days at 5m granularity).
   - Backtest the strategy mechanically.
   - Treat results as **directional, not deployable** until ≥30–60d of data accumulates.

---

## 4. Recommended next actions (in order)

1. **Build a SQL-driven loader** that pulls (per asset, per tenor, per market) the book trajectory + resolution into parquet. Reuse / adapt existing `polymarket_extract_*.sql` from `strategy_lab/`. Run it locally over an SSH tunnel to keep raw rows off this machine.
2. **Pull 1y BTC 1m perp futures klines from Binance Vision** for liquidation-aware backtest (replace the spot proxy on the perp leg).
3. **Start a parallel Binance Vision tick scrape** for the 6-day Polymarket window (overnight) — gives true slippage at 60× lev.
4. **Extend the VPS collector** to scrape 1h / 4h / 24h Polymarket BTC binaries if the long-tenor sleeve is in scope. Otherwise drop those legs from the strategy doc.
5. **Calibrate fair-value model** on the 6 days, then run Phase 1 backtest of the high-lev sleeve only.
6. **Promote to walk-forward** once 30+ days are accumulated.

---

## 5. Connection cheatsheet

```bash
# direct shell
ssh -i ~/.ssh/vps2_ed25519 root@'[2605:a140:2323:6975::1]'

# psql tunnel from this Windows box
ssh -i ~/.ssh/vps2_ed25519 -L 5433:127.0.0.1:5432 root@'[2605:a140:2323:6975::1]'
# then locally:  psql -h 127.0.0.1 -p 5433 -U tradingvenue_ro -d storedata
# password lives in /etc/tv/tv-ro.env on the VPS as TV_RO_PWD_PLAIN
```
