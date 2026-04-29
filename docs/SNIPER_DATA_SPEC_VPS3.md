# Sniper Strategy Data Spec — VPS3 Backfill

**Goal:** make the Polymarket UpDown V2 **sniper** sleeves fire on VPS3.
**Blocker:** VPS3 collector started ~9h ago — sniper needs 14 days of `binance_klines_v2` history with ≥50 samples per `(symbol, tf)`. Until then, every sniper sleeve returns `NONE`.

**VPS3:** `root@185.190.143.7` (hostname `storedata-vps3`), key `~/.ssh/vps3_ed25519`. Postgres @ `127.0.0.1:5432/storedata`, RO user `tradingvenue_ro`, password in `/etc/tv/tv-ro.env` as `TV_RO_PWD_PLAIN`.

---

## 1. What the sniper actually reads (code-truth)

From `backend/app/controllers/polymarket_updown.py`:

```
SNIPER_LOOKBACK_DAYS = 14
SNIPER_MIN_SAMPLES   = 50
KLINE_SOURCE         = "binance-spot-ws"        # filtered in fetch_close_asof
BINANCE_SYMBOL_ID_MAP: BTC→BINANCE_SPOT_BTC_USDT, ETH→…ETH…, SOL→…SOL…
quantile per tf:    5m → 0.90 (q90)   15m → 0.80 (q80)
```

Per-bar logic (controller L255-L274 + `_fetch_abs_ret_5m_history` L352-L420):

For every completed UpDown market in the last 14 days:
1. Compute `ws_s = end_unix - tf_seconds` (window start of that market).
2. Fetch `binance_klines_v2` row WHERE `symbol_id=<asset>`, `period_id='1MIN'`, `source='binance-spot-ws'`, time as-of `ws_s` and `ws_s − 300`.
3. `ret_5m = ln(close_now / close_5m_prior)`.
4. Append `|ret_5m|` to samples.

Threshold = `np.quantile(samples, q)`. If `len(samples) < 50` → return None → sniper returns `NONE` → 0 fills.

### What this means for backfill data
| Requirement | Spec |
|---|---|
| Table | `binance_klines_v2` |
| `symbol_id` | `BINANCE_SPOT_BTC_USDT`, `BINANCE_SPOT_ETH_USDT`, `BINANCE_SPOT_SOL_USDT` |
| `period_id` | **`1MIN` only** (the strategy only reads 1MIN) |
| `source` | **`binance-spot-ws`** (filter in `fetch_close_asof`) |
| Window | last **15 days** (1-day buffer over the 14d lookback) |
| Density | one row per minute, **no gap > 5 minutes** allowed (else `as-of` returns stale close → ret_5m biased) |
| Symbols (must-have) | BTC. ETH+SOL nice-to-have for parallel sleeves |

### Other tables the sniper does NOT need on VPS3
- `binance_funding_rate_v2` — not read.
- `binance_metrics_v2` — not read.
- `binance_liquidations_v2` — not read.
- `trades_v2`, `oracle_prices_v2` — Polymarket-side, written by VPS3 collector itself.
- Mark/index/premium klines — futures, not in scope (sniper is spot-only).

VPS3 stays "process-only" — collector + sniper history only. Backtest data lives on VPS2 / local box.

---

## 2. Current state on VPS3 (queried 2026-04-29)

```
source           | period_id | symbol                | rows | first             | last
binance-spot-ws  | 1MIN      | BINANCE_SPOT_BTC_USDT | 539  | 2026-04-28 20:53  | 2026-04-29 05:51
binance-spot-ws  | 5MIN      | BINANCE_SPOT_BTC_USDT | 108  | 2026-04-28 20:50  | 2026-04-29 05:45
binance-spot-ws  | 15MIN     | BINANCE_SPOT_BTC_USDT | 36   | 2026-04-28 20:45  | 2026-04-29 05:30
… (ETH, SOL identical pattern)
```

~9h of data per symbol. Live WS collector is running and writing correctly. **Need to backfill 2026-04-13 → 2026-04-28 20:53 = ~15 days × 1440 = 21,600 1MIN bars per symbol.**

---

## 3. Backfill plan

### 3.1 Data source: Binance Vision spot 1m daily zips
URL pattern: `https://data.binance.vision/data/spot/daily/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM-DD>.zip` + `.CHECKSUM`.

Window 2026-04-13 → 2026-04-28 = 16 days × 3 symbols = **48 zips**, ~150 MB total. Vision publish lag ≈ today−1 (so 04-28 may not be published yet — if missing, fill the gap from Binance REST `/api/v3/klines` for the tail).

### 3.2 The source-filter decision (CRITICAL)
The sniper SQL filters on `source='binance-spot-ws'`. A naive Vision ingest writing `source='binance-vision'` will **not** be visible to the sniper. Three options:

| Option | What it does | Risk |
|---|---|---|
| **A** ingest with `source='binance-spot-ws'` (impersonate live) | Sniper sees rows immediately, no code change | Collisions with live WS rows on PRIMARY KEY → use `ON CONFLICT (symbol_id, period_id, time_period_start_us, source) DO NOTHING`. Live WS keeps writing forward; backfill stops at the first WS row. |
| **B** ingest with `source='binance-vision'` and add it to controller's KLINE_SOURCE list | Clean separation by source | Requires controller change + redeploy. The code already has a list (line 110: `"binance-spot-ws",` in a list-shaped construct — check whether `KLINE_SOURCE` is a single string or an array; if string, this option needs a wider edit). |
| **C** ingest with `source='binance-vision'` + add a per-query UNION view `binance_klines_unified` | No controller change, transparent to strategy | More plumbing; one more dependency. |

**Recommendation: Option A.** Simpler, no code change, idempotent on conflict, and it's *factually true* that the bars are 1m spot Binance OHLCV — the source name is informational. Document it in a comment on the load script.

### 3.3 Pipeline (run on VPS3 — no laptop bandwidth needed)
1. Pre-flight: `SELECT MIN(time_period_start_us), MAX(...) FROM binance_klines_v2 WHERE source='binance-spot-ws' AND symbol_id='BINANCE_SPOT_BTC_USDT' AND period_id='1MIN';` — confirm earliest WS row (so backfill knows where to stop).
2. Download 48 zips to `/opt/storedata/imports/binance_vision/spot/1m/`.
3. Verify each zip's SHA256 against its `.CHECKSUM` file.
4. Unzip → CSV (cols: `open_time_ms, open, high, low, close, volume, close_time_ms, quote_volume, trades_count, taker_buy_base, taker_buy_quote, ignore`).
5. Stage into `binance_klines_staging` with mapped schema:
   ```
   time_period_start_us = open_time_ms * 1000
   time_period_end_us   = close_time_ms * 1000
   symbol_id            = 'BINANCE_SPOT_<SYM>'
   period_id            = '1MIN'
   price_open/high/low/close/volume_traded/trades_count/quote_volume per CSV
   source               = 'binance-spot-ws'        # ← Option A
   ```
6. Insert into `binance_klines_v2` with `ON CONFLICT … DO NOTHING`.
7. Cleanup staging + zips (keep one copy of zips for audit).

### 3.4 Acceptance check (run after load)
Per `(symbol, tf)`:
```sql
SELECT
  COUNT(*) FILTER (
    WHERE time_period_start_us > (extract(epoch from now())::bigint - 14*86400) * 1000000
  ) AS samples_in_lookback
FROM binance_klines_v2
WHERE symbol_id = 'BINANCE_SPOT_BTC_USDT'
  AND period_id = '1MIN'
  AND source    = 'binance-spot-ws';
```
Pass if `samples_in_lookback ≥ 50` for every (BTC, ETH, SOL). With 14 days × 1440 = 20,160 bars, comfortably above 50 — but the sniper threshold path samples one return *per resolved UpDown market in the lookback*, not per bar; at ~5,000 BTC 5m markets/14d that's plenty.

### 3.5 Rollback
If anything looks off, single command unwinds the backfill **without touching live WS data** (since live started 2026-04-28 20:53):
```sql
DELETE FROM binance_klines_v2
WHERE source='binance-spot-ws'
  AND time_period_start_us < 1745870000000000;  -- before 2026-04-28 20:53 UTC
```

---

## 4. Things explicitly out of scope on VPS3

- Futures (UM perp) klines — **stay on VPS2 / local**. The sniper is spot-only.
- AggTrades / tick data — backtest concern, not VPS3.
- 5m and 15m bars from Vision — sniper only reads 1MIN. Skip.
- Funding, metrics, liquidations — not consumed by sniper. Skip on VPS3.

---

## 5. Where the rest goes (per operator directive)

| Data | Destination | Purpose |
|---|---|---|
| Spot 1MIN BTC/ETH/SOL × 15 days | **VPS3** | feed the sniper now |
| Futures (UM) klines, mark, index, premium | VPS2 or local box | backtest the leveraged-cover leg |
| AggTrades (spot + UM) | local box | tick-level slippage modeling |
| Funding, metrics, liquidations | VPS2 (already have schema) or local | regime tagging, tail flagging in backtest |
| Polymarket book history | VPS2 (already collected, 6 days) | already there |

Backtest box = local Windows machine OR VPS2. Production box (VPS3) = collector + strategy only.
