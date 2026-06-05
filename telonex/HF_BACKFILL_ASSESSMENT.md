# HF `trentmkelly/polymarket_crypto_derivatives` — backfill assessment (2026-06-05)

## What it actually contains (verified from the live file tree, not the card)

- **Assets: BTC + ETH ONLY.** No SOL, DOGE, HYPE, BNB, or XRP. (The provider card claimed BTC/ETH/SOL/XRP — the real tree has only btc + eth.)
- **Timeframes: 5m + 15m.**
- **17,670 market episodes**, one directory each (`{asset}{tf}_market{id}_{date}_{time}_all/`):

  | asset | tf | episodes |
  |---|---|---:|
  | btc | 5m | 8,803 |
  | btc | 15m | 2,944 |
  | eth | 5m | 2,979 |
  | eth | 15m | 2,944 |

- **Window: 2026-02-21 → 2026-03-24** (~32 days). License CC-BY-SA-4.0, free, 15.5k downloads.
- 3 parquet files per episode:
  - `book_levels.parquet` — **full L2 depth, long format**: `step_index, outcome(0=Up/1=Down), side(0=bid/1=ask), level_index, price, size`
  - `events.parquet` — raw CLOB events: `event_type(1=trade/2=price_change/3=tick), ts(ms), is_down, is_sell, price, size` (= our trades + book deltas)
  - `steps.parquet` — per-snapshot derived features: `ts(ms), progress, chainlink_price, binance_price, up/down_best_bid/ask/mid/spread/size_total/imbalance`

## Backfill path — PROVEN

`telonex/hf_to_canonical.py` converts one HF episode → our canonical `orderbook_l25` wide schema with **103/103 column parity (zero missing, zero extra)**. Transforms applied:
- **long → wide pivot**: `book_levels` grouped by (step, outcome), side→bid/ask, level_index→`{bid,ask}_{price,size}_0..24` (capped at 25 levels).
- **ms → µs**: HF `ts` ×1000 → our `timestamp_us`.
- **slug derived** from dir name: `market{id}_{date}_{time}` → slot epoch → `btc-updown-15m-<epoch>` (our convention).
- outcome 0/1 → "Up"/"Down".

So HF book data drops straight into `canonical/orderbook_l25/{btc,eth}.parquet` via the existing `merge_l25_topoff.py` (same dedup-by-(slug,outcome,ts) machinery).

## Does HF have everything we collect for these markets?

| Our canonical source | HF equivalent | Verdict |
|---|---|---|
| `orderbook_l25` (L25 book) | `book_levels` (full depth) | ✅ richer (full vs 25 levels); convert long→wide |
| `trades_polymarket` | `events` type=1 (trade) | ✅ price/size/side present |
| `chainlink_rtds` (1Hz raw) | `steps.chainlink_price` (snapshot cadence ~100ms-1s) | ⚠️ partial — sampled at step times, not the raw 1Hz oracle feed |
| `klines_1m/1s` (binance OHLCV) | `steps.binance_price` (price sample) | ⚠️ partial — a price sample, not OHLCV bars/volume |
| `resolutions` / outcome | not included | ⚠️ derivable from final settle price, or join externally |

**Net:** HF fully backfills **book + trades** for BTC/ETH 5m/15m. The chainlink/binance reference is a *sampled snapshot*, not our full RTDS/kline feeds — fine for book/exec research, not a full replacement for the signal stack.

## Coverage vs our window

- Our canonical: **Apr 22 → Jun 5 2026**.
- HF: **Feb 21 → Mar 24 2026** → a clean ~2-month **earlier** extension, **for free**.
- ⚠️ **Gap Mar 24 → Apr 22** (~4 weeks) — covered by neither HF nor our canonical. No free source fills it (would need PolyHistorical/Telonex, both paid, book from ~Aug-Oct 2025 only... actually they'd cover Mar-Apr).
- ⚠️ **SOL not backfillable** here (BTC/ETH only). Our SOL stays Apr 22+.

## Other markets (DOGE/HYPE/BNB/XRP)?
**None.** This dataset is BTC + ETH only. (DOGE/BNB/XRP up-or-down exist on Polymarket per the Telonex catalog, but nobody published a free L2 dataset for them — only our VPS3 futures `cex_futures_*` carries BNB/DOGE/XRP, and that's CEX perp, not Polymarket book.)

## Full-pull cost (decision needed)
- ~518 KB/episode × 17,670 = **~9 GB** across 53,010 small files.
- Best fetched via `huggingface-cli download trentmkelly/polymarket_crypto_derivatives --repo-type dataset` (handles the 53k files); converting all → ~1-2 GB canonical parquet append.
- Disk: 28 GB free now (after the 801 MB Telonex catalog still sitting there).

## Recommendation
1. **Worth doing** — free, exact schema match, +2 months BTC/ETH 5m/15m book history.
2. Build `build_hf_backfill.py`: snapshot-download → per-episode convert → append to `canonical/orderbook_l25/{btc,eth}.parquet` (reuse merge dedup). Also optionally land `events`→trades.
3. Decide first: full 9 GB pull, or a targeted subset (e.g. just btc15m + eth15m = 5,888 episodes ≈ 3 GB) to start.
4. Don't expect SOL / DOGE / pre-Apr-22-to-our-window continuity from this.

## Files
- `telonex/hf_explore.py`, `hf_sample.py` — dataset structure probes
- `telonex/hf_to_canonical.py` — **converter prototype (proven 103/103 parity)**
- `telonex/hf_sample/{steps,events,book_levels}.parquet` — one sample episode
