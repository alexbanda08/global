# Binance Vision Backfill Plan — 15 Days

**Window target:** 2026-04-13 → 2026-04-27 (15 days, ending at the last fully-published Binance Vision day).
**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT.
**Mode:** spot + USDM perpetual futures (we need both).

Binance Vision pattern: `https://data.binance.vision/data/<market>/daily/<dataset>/<SYMBOL>/<INTERVAL>?/<SYMBOL>-<dataset>-<YYYY-MM-DD>.zip` + a `.CHECKSUM` next to it.

---

## 1. What to pull

### Spot (we have klines through 2026-04-27, so this is forward-fill / verification)
| Dataset | URL prefix | Why |
|---|---|---|
| Klines 1m / 5m / 15m | `data/spot/daily/klines/<SYM>/<INTERVAL>/` | Sanity-fill any gaps; already in DB |
| AggTrades | `data/spot/daily/aggTrades/<SYM>/` | Tick-level for slippage modeling |
| Trades | `data/spot/daily/trades/<SYM>/` | Same; aggTrades smaller, prefer it |

### USDM Perpetual Futures — **the real backfill target** (we have none of this on VPS)
| Dataset | URL prefix | Why |
|---|---|---|
| Klines 1m / 5m / 15m | `data/futures/um/daily/klines/<SYM>/<INTERVAL>/` | The actual perp price for the cover leg |
| Mark-price klines 1m | `data/futures/um/daily/markPriceKlines/<SYM>/1m/` | Liquidation reference price |
| Index-price klines 1m | `data/futures/um/daily/indexPriceKlines/<SYM>/1m/` | Basis monitoring |
| Premium-index klines 1m | `data/futures/um/daily/premiumIndexKlines/<SYM>/1m/` | Funding pre-print |
| Funding rate | `data/futures/um/daily/fundingRate/<SYM>/` | 8h funding cost on the cover |
| Metrics (OI, taker L/S, top trader L/S) | `data/futures/um/daily/metrics/<SYM>/` | Regime tags |
| Liquidation snapshot | `data/futures/um/daily/liquidationSnapshot/<SYM>/` | Tail-event flagging |
| AggTrades | `data/futures/um/daily/aggTrades/<SYM>/` | **Tick-level for 60–70× slippage modeling** |

---

## 2. Scope math

3 symbols × 15 days × ~10 datasets ≈ **450 daily zips**. Sizes per zip (rough):
- Klines 1m: ~3 MB
- AggTrades: ~50–150 MB (BTC heaviest)
- Funding / metrics / liquidations: <1 MB each

Total disk: **~3–5 GB compressed**, ~15–25 GB uncompressed. Fits comfortably on either box.

Bandwidth: Binance Vision is fast (CDN) — at 50 Mbit, ~10 minutes for the lot. Run on VPS2 since the DB is there and ingestion stays on-box.

---

## 3. Where to land it

**Option A — pull on VPS2, ingest into Postgres** (preferred):
- Klines → extend `binance_klines_v2` (add USDT-PERP rows with `symbol_id='BINANCE_FUTURES_BTC_USDT'` or similar prefix, `period_id` already supports intervals).
- Funding → extend `binance_funding_rate_v2` (already has the schema for it; just need to verify it covers UM perp).
- Metrics → `binance_metrics_v2` already has OI + L/S + taker columns.
- Liquidations → `binance_liquidations_v2`.
- New table needed for **mark / index / premium klines** and **agg-trades** (high cardinality — consider a hypertable like `binance_aggtrades_v2`).

**Option B — pull to local Windows box**:
- Land in `data/binance/futures/` as parquet, partition by symbol/interval/date.
- Use `fetch_binance_multi.py` as the template (already exists in repo) and add a perp-aware variant.

I recommend **A** because: (i) the strategy backtest engine the team built lives next to the DB, (ii) tick agg-trades are too big to want on a local machine, (iii) keeps a single source of truth.

---

## 4. Pseudo-script (run on VPS2)

```bash
#!/usr/bin/env bash
set -euo pipefail
SYMS=(BTCUSDT ETHUSDT SOLUSDT)
DAYS=$(python3 -c "from datetime import date,timedelta; t=date.today()-timedelta(days=2); [print((t-timedelta(days=i)).isoformat()) for i in range(15)]")
DEST=/opt/storedata/imports/binance_vision
mkdir -p $DEST

dl() { # market dataset interval sym day
  local market=$1 ds=$2 interval=$3 sym=$4 day=$5
  local path="$market/daily/$ds/$sym${interval:+/$interval}/$sym${interval:+-$interval}-$ds-$day.zip"
  # Note: classic Vision URL pattern is $sym-$interval-$day.zip (klines) or $sym-$ds-$day.zip (others)
  local url="https://data.binance.vision/data/$market/daily/$ds/$sym${interval:+/$interval}/$sym-${interval:-$ds}-$day.zip"
  local out="$DEST/$market/$ds/$sym/$(basename "$url")"
  mkdir -p "$(dirname "$out")"
  [[ -f "$out" ]] && return 0
  curl -fsSL "$url" -o "$out" || echo "MISS $url"
}

for sym in "${SYMS[@]}"; do
  for day in $DAYS; do
    # spot
    for iv in 1m 5m 15m; do dl spot klines $iv $sym $day & done
    dl spot aggTrades "" $sym $day &
    # futures UM
    for iv in 1m 5m 15m; do dl futures/um klines $iv $sym $day & done
    for ds in markPriceKlines indexPriceKlines premiumIndexKlines; do
      dl futures/um $ds 1m $sym $day &
    done
    for ds in fundingRate metrics liquidationSnapshot aggTrades; do
      dl futures/um $ds "" $sym $day &
    done
    wait
  done
done
```

(Sketch — the real version validates `.CHECKSUM` SHA256 next to each zip and skips already-downloaded files.)

---

## 5. Ingest checklist after download

1. Verify SHA256 against the `.CHECKSUM` files.
2. Unzip each → CSV.
3. Spot-check column order — Binance has changed kline schemas before; current spot kline = 12 cols, futures kline = 12 cols, agg-trades = 6 cols, funding = 3 cols (`calc_time, funding_interval_hours, last_funding_rate`).
4. Bulk COPY into the corresponding `*_v2` tables. Add the `BINANCE_FUTURES_*` prefix in `symbol_id` so spot vs. perp stays separable.
5. Sanity query: counts per symbol/day after ingest should equal expected (1440 1m bars/day, 288 5m, 96 15m).

---

## 6. Risks / watch-outs

- **Same-day data lag.** Binance Vision typically publishes day D around 02:00 UTC of day D+1 for spot, slightly later for futures. Today's data is always missing — that's why the window above ends at `today − 2`.
- **Holiday data** — sometimes a single dataset is republished hours later. Re-pull any `MISS` lines after 6h.
- **15 days is still too short for walk-forward.** Useful for fair-value calibration and tick-slippage sensitivity, **not** for performance claims. Treat results as in-sample only until 30+ days are stitched together.
- **Binance Vision serves Binance only.** For Hyperliquid, OKX, Bybit perps we'd need separate pulls. That's a later concern.
