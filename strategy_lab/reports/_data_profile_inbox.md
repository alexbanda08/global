# Data profile — overnight research session

Generated 2026-05-23 by data-profile runner. Reproducible scripts:
- `strategy_lab/reports/_data_profile_runner.py` (Tasks 1+2+4 + first-cut Task 3)
- `strategy_lab/reports/_data_profile_taskd3_fix.py` (Task 3 with correct F7-off filter)

Run as: `cd C:\Users\alexandre bandarra\Desktop\global && py strategy_lab/reports/_data_profile_runner.py`

---

## 1. Binance 1s klines (`load_klines_1s`)

**Schema** — `data/v4/canonical/klines_1s.parquet`, **11,384,517 rows**:

| col | dtype |
|---|---|
| symbol_id | object (`BINANCE_SPOT_{BTC,ETH,SOL}_USDT`) |
| period_id | object (`1SEC`) |
| source | object (`binance-vision` 7.78M / `binance-spot-ws` 3.61M) |
| time_period_start_us | int64 (1s-aligned, UTC) |
| time_period_end_us | int64 |
| price_open / high / low / close | float64 (USDT) |
| volume_traded | float64 (**BASE asset** — BTC, e.g. 0.7288 BTC at row 0) |
| trades_count | int64 |
| quote_volume | float64 (**USDT notional** — e.g. 50,179.65 USDT at row 0) |
| taker_buy_base / taker_buy_quote | float64 (vision-only, NaN for ws) |
| time_open_us / time_close_us | float64 (vision-only, NaN for ws) |

**Coverage**: **2026-04-07 00:00:00 UTC → 2026-05-21 20:17:32 UTC** (44.85 days).
Per asset: BTC=3,794,841 / ETH=3,794,840 / SOL=3,794,836 rows (all three assets present, same span).

**Gap structure (BTC; ETH & SOL identical)**:
- 100.00% of consecutive diffs = 1s (3,794,796 / 3,794,840)
- 44 gaps >5s, 15 gaps >60s
- ONE big gap: **2026-05-06 23:59:59 → 2026-05-07 21:16:28 (21h17m)** — boundary between `binance-vision` archive and `binance-spot-ws` live feed
- Remaining 43 gaps are 8–88s `binance-spot-ws` hiccups, May 8 onward

**Volume**: `volume_traded` is base asset, `quote_volume` is USD-notional. Use `quote_volume` for $ flow.

**Production note**: `taker_buy_*` only populated for vision archive (Apr 7 → May 6); NaN after the cutover. If you need taker imbalance over the F7 fire window (largely post-May 6), it's unavailable from 1s klines — derive it from binance trades or trades_polymarket instead.

---

## 2. L25 books (`load_orderbook_l25_streaming`)

**Sample-density check on 100 random BTC slugs** in `[ws_s, ws_s + 2·window_s] = [ws_s, slot_end]` (600s span, both Up and Down outcomes):

```
mean=324.9 samples, median=334
p10/p25/p50/p75/p90 = 260/298/334/356/377
min/max = 193/440
zero-coverage entries: 0/200
```

`subsample_1hz=True` collapses microsecond snapshots to ≤1/sec. Theoretical ceiling within 600s = 600 samples; observed median ~55% of ceiling because some seconds have no book update (sparse second-stamps where the book didn't change).

**RAM bound**: Pass `slugs=set(...)` always (BTC source parquet is 2.7 GB). Loading 100 slugs = ~12s; 300 slugs = ~16s on this machine.

---

## 3. Cross-coverage (F7-off, 5m only — `f7_mode=='off' & tf=='5m'`)

`fills.csv` has 11,681 rows; F7-off 5m subset = **4,956 fires** (BTC=2,306, ETH=1,575, SOL=1,075). Sampled up to 1,500 fires per asset for kline check, 300 unique slugs per asset for L25 + trades check.

| asset | n_fires | (a) 1s kline in [fire±300s] | (b) L25 in [fire, slot_end] | (c) trades for slug | joint (k+L25+trades) |
|---|---:|---:|---:|---:|---:|
| BTC | 2,306 | 95.7% (median=601/600 samples) | 100.0% | 93.3% | 86.4% |
| ETH | 1,575 | 94.5% | 100.0% | 90.0% | 83.8% |
| SOL | 1,075 | 93.1% | 100.0% | 87.7% | 80.7% |

**Kline misses** (~5–7%) cluster at the May 6 / May 7 vision→ws cutover and a handful of May-period ws gaps; the 5-min window straddling that 21h vision-ws cutover loses 1s coverage entirely.

**Trade misses** (~7–12%) are slugs where Polymarket had no taker prints during the slot (low-activity markets). Coverage in trades parquet is Apr 26 → May 21 (CLAUDE.md note about "stale Apr 22 → May 6" is **outdated** — fresh refresh extended this).

**L25 100%** — `load_orderbook_l25_streaming` returns at least one book sample per slug in every checked window.

---

## 4. Slot-timing example

Row 0 of `fills.csv`: `slug = btc-updown-5m-1776889500`, `tf=5m`, `signal=DOWN`, `outcome=Up`, `won=False`, `pnl=-25.9275`.

```
window_s     = 300 (5m)
slot_start   = 1776889500   = 2026-04-22 20:25:00 UTC  (slug suffix)
slot_end     = 1776889800   = 2026-04-22 20:30:00 UTC  (slot_start + window_s)
ws_s         = 1776889200   = 2026-04-22 20:20:00 UTC  (slot_start - window_s) [SIGNAL ANCHOR]
fire_us (v1) = 1776889320000000 = 2026-04-22 20:22:00 UTC  ((ws_s + 120) * 1e6)
```

Match w/ row-level `ws_s=1776889200` and `fire_us=1776889320000000` ✓.

**Data available at each anchor** (for this example):
- `ws_s` (20:20:00): 1s klines yes, chainlink RTDS yes, L25 books yes (book is in *previous* slot but same slug-pair persists across slot boundaries — verify by outcome key)
- `ws_s+120s = fire_us` (20:22:00): 1s klines yes, L25 yes, momo `ret_2m_at_ws` computable
- `slot_start` (20:25:00): full coverage; oracle strike read happens here
- `slot_end` (20:30:00): full coverage; resolution settles

**Lookahead trap**: anchoring `ret_2m` on `slot_start` instead of `ws_s` looks 2 minutes INTO the prediction window → inflates WR by ~25–40 pp. Always anchor on `ws_s = slot_start − window_s` per `slug_to_ws_s()`.

---

## Reproducer code snippets

```python
# Task 1: 1s klines
import sys; sys.path.insert(0, "data/v4/canonical")
from load import load_klines_1s
kg = load_klines_1s()           # full table (11.4M rows, ~600 MB RAM)
btc = load_klines_1s("BTC")     # filter at load time

# Task 2: L25 books (always pass slugs= to bound RAM)
from load import load_orderbook_l25_streaming
books = load_orderbook_l25_streaming("BTC", slugs=set(my_slugs), subsample_1hz=True)
# books: dict[(slug, "Up"/"Down")] -> (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25])

# Task 3: trades
from load import load_trades
trades = load_trades("BTC")     # 31.1M rows, slug column present

# Task 4: slot math
slug = "btc-updown-5m-1776889500"
slot_start = int(slug.rsplit("-",1)[1])   # 1776889500
ws_s       = slot_start - 300              # 1776889200  (PREVIOUS slot start)
fire_us    = (ws_s + 120) * 1_000_000      # v1 anchor
slot_end   = slot_start + 300              # outcome resolves here
```

---

## Take-aways

1. **1s klines are clean** post May 7 with one 21h gap at the vision→ws boundary. Trust them for fire-window features except slots that straddle 2026-05-06 23:59 UTC.
2. **L25 books are 100% coverage** for every F7-off 5m fire's prediction window. No data-quality blocker for any book-derived feature.
3. **Joint coverage 80–86%** is bounded by polymarket-trade sparsity on low-activity slugs, not by our infra. If your study tolerates fires-without-trade-tape, drop the trades-required filter and joint coverage approaches the L25/kline minimum (~93–96%).
4. **`taker_buy_*` is vision-only** — for trade-imbalance features post May 6, source from `load_trades` (polymarket) or pull binance trades archive.
