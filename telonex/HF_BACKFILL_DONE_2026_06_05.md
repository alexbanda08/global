# HF Polymarket backfill — DONE (2026-06-05)

Ingested **3 free HuggingFace datasets**, converted, cross-backfilled, merged into canonical,
wiped all raw (single-source invariant). Adds pre-Apr-22 crypto up/down history + 7-coin BBO.

## ⭐ NEXT SESSION — TASK LIST (user request, in order)

Token (read): stored locally in `telonex/.hf_token` (gitignored; HF user cryptokabum). Always `export HF_TOKEN=$(cat telonex/.hf_token)` to avoid 429 rate-limits. Reuse `telonex/aliplayer_convert_duck.py` (DuckDB, out-of-core — the only thing that handled the billion-row BBO; pandas OOMs).

**TASK 1 — Resolutions for ALL 7 coins (incl. BNB/DOGE/HYPE that we're missing).**
- We only extracted bmoney's BTC/ETH/SOL/XRP resolutions. `aliplayer1` `data/markets.parquet` (12 MB) has `resolution` (Up/Down/-1) + `start_ts`/`end_ts` + `up_token_id`/`down_token_id` + `crypto`/`timeframe` for ALL 7 coins across its whole window.
- Re-pull just `data/markets.parquet` (`allow_patterns=['data/markets.parquet']`), derive slug = `{crypto}-updown-{tf}-{start_epoch}`, map resolution -1→unresolved, filter resolved, **append to `canonical/resolutions_hf.parquet`** (dedup by slug, keep existing real). Gives BNB/DOGE/HYPE outcomes + wider window for all coins.

**TASK 2 — All 7 coins BBO + trades, Apr 22 → today (extend past our Apr-21 cutoff).**
- aliplayer **auto-updates every 3h** → it now covers Apr 21 → today. Pull `data/orderbook/**` + `data/ticks/**` + `data/markets.parquet` (filter to ts ≥ Apr 22 if pulling delta, or just re-pull and `DuckDB WHERE timestamp_us >= <Apr22>`), convert via `aliplayer_convert_duck.py`, **append to `D:\global_data\canonical_bbo\{coin}` + `canonical_bbo_trades\{coin}`** (dedup by slug+ts+outcome). This closes the Apr 21 → now BBO gap for the 7 coins and gives ongoing top-of-book for ALL coins (incl. the ones we don't collect on VPS3).

**TASK 3 — Cross-validate our live data vs HF (find gaps in OUR Apr 24 → today collection).**
- For BTC/ETH/SOL (which we DO collect), compare HF (aliplayer Apr22→today) vs our production:
  1. **Resolutions:** our chainlink `resolutions_from_rtds` outcomes 100% == HF real outcomes? (flag wrong settlements)
  2. **Trades:** do we have every fill HF has? (missing = collector gap → backfill from HF)
  3. **Book:** our L25 best-bid/ask @10Hz vs HF BBO @200Hz at matched timestamps.
  4. **List + backfill any gaps** in our Apr 24 → today collection.

**TASK 4 — Fix the `1970-01-01` trades bug.** aliplayer ticks have some rows with `timestamp_ms=0` → epoch 1970 in `canonical_bbo_trades`. Filter `timestamp_us > <2025-01-01>` on convert/read.

**Also pending (not HF): Mar 24→30 gap** (~6 days, no source); **full-depth L2 for BNB/DOGE/HYPE does NOT exist anywhere** (BBO only — hard limit).

## What was built (all in canonical, raw wiped)

| Layer | Path | Rows | Size | Coverage | Source |
|---|---|---|---|---|---|
| L25 backfill (10Hz, full depth) | `canonical/orderbook_l25_backfill/{btc,eth}` (C:) | 97.9M each | 8 GB | Feb 21 → Mar 24 | trentmkelly |
| L25 backfill | `.../orderbook_l25_backfill/{sol,xrp}` (C:) | 0.85M each | 40 MB | Mar 1 → Mar 13 | bmoney |
| **BBO ~200Hz, 7 coins** | **`D:\global_data\canonical_bbo\{btc,eth,sol,bnb,xrp,doge,hype}`** | **4.4B total** | **17 GB** | **Mar 30 → Apr 21** | aliplayer |
| BBO trades (7 coins) | `D:\global_data\canonical_bbo_trades\*` | ~20M | ~280 MB | Mar 30 → Apr 21 | aliplayer ticks |
| trades backfill | `canonical/trades_polymarket_hf/{btc,eth}` (C:) | 42M | 430 MB | Feb 21 → Mar 24 | trentmkelly |
| **resolutions (REAL)** | `canonical/resolutions_hf.parquet` | 32,880 | 0.5 MB | Jan 2 → Mar 24 | bmoney(real)+trentmkelly(settle) |

**Coverage chains nearly continuously:** Jan 2 → Mar 24 (full-depth L25) → Mar 30 → Apr 21 (BBO 7 coins) → **Apr 22 → now (our production L25 10Hz)**. Gap: Mar 24-30 (~6 days), and the Apr 21-22 seam.

BBO is **event-driven ~200 Hz** (median 5ms between updates, bursts to 1000 Hz) — ideal for microstructure edges on the non-BTC/ETH coins we don't otherwise have book data for.

## Loaders (in `data/v4/canonical/load.py`)
```python
load_orderbook_l25_backfill(asset, slugs=, min_ts_us=, max_ts_us=)   # 103-col wide, == production schema
load_orderbook_bbo(coin, timeframe=, slugs=, min_ts_us=, max_ts_us=, columns=)  # pyarrow-filtered (BTC=2.6B rows, ALWAYS filter)
load_resolutions_hf(ticker=)        # real outcomes
load_trades_hf(asset, bbo=False)    # False=trentmkelly btc/eth; True=aliplayer 7-coin
```
Slug convention is shared (`{coin}-updown-{5m|15m}-<epoch>` / aliplayer also 1h/4h human slugs) → joins to our canonical.

## Pipeline scripts (`telonex/`)
- `build_hf_backfill.py` + `convert_trentmkelly.py` — trentmkelly download + 10Hz convert (numpy-scatter reshape, multiprocess)
- `bmoney_convert.py` — bmoney resolutions + full-depth L25 (token-label via resolution+final-mid)
- `aliplayer_convert_duck.py` — **DuckDB out-of-core** BBO + ticks convert (the one that worked for billions of rows)
- `merge_unified.py` — merge trentmkelly+bmoney → canonical backfill layer (stream dedup, atomic)
- `UNIFIED_HF_PLAN.md`, `HF_BACKFILL_ASSESSMENT.md`, `DATA_PROVIDERS_RESEARCH.md`, `TELONEX_ANALYSIS.md` — research/design

## Provider research verdict (DATA_PROVIDERS_RESEARCH.md)
- **No L2 book exists anywhere before ~Aug-Oct 2025** (nobody recorded the CLOB WS feed). Pre-2025 = on-chain fills only (free via Dune / SII-WANGZJ HF / data-api).
- **PolyHistorical $17/mo** beats **Telonex $79** for our crypto-up/down need (+ Binance futures book). Telonex's only edge: all-market-category + onchain_fills→2022 (Dune gives those free).
- **Tardis.dev** = deepest CEX **liquidations** (Binance Nov-2019, Bybit/OKX Dec-2020), separate ~$100-200/mo buy. Gate/Bitget liq don't exist anywhere (our VPS3 gate/okx feed is near best-available).
- Telonex API fully mapped (`TELONEX_ANALYSIS.md`); key `tlx_14ecdbcbfd155a0defaf857fa0950e45`, ~5 free downloads likely spent probing.

## Disk
BBO (17 GB) lives on **D:** (`D:\global_data\`), loaders point there. Everything else in C: repo canonical.
After wipe: D: 104 GB free, C: 33 GB free. Zero duplicate datasets.
