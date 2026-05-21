# Data Inventory + Next-Session Context — 2026-05-15

**Refresh completed:** 2026-05-15 03:30 UTC
**Canonical location:** `data/v4/canonical/`
**All sessions / backtests MUST read through:** `from data.v4.canonical.load import *`

---

## 🚨 Live-mimic engine wired — 2026-05-16

**`strategy_lab/engine_v2.py`** is now the single source-of-truth fill primitive.
Use it for any NEW backtest. Migrate old ones at convenience.

```python
from strategy_lab.engine_v2 import LiveMimicConfig, LegacyConfig, fill_at_book, hold_pnl, sell_pnl

cfg = LiveMimicConfig()       # 7% poly fee curve on every fill + 85ms latency + min_book_events=25
# cfg = LegacyConfig()        # 2%-on-profit, 0ms — reproduces pre-2026-05-16 numbers

fill = fill_at_book(books_idx, slug, "Up", fire_us, cfg=cfg, spread_filter=0.02)
pnl  = hold_pnl(fill, won=won, cfg=cfg)
```

**First-run findings** (`full_universe_live_mimic_v2_2026_05_16/`):
- Every single momo variant loses money under live-mimic
- Best: v1 `STOP_HEDGE_0.7x` at −$1.55/trade
- HOLD_baseline: v1 −$1.58/tr (legacy −$1.21), v2 −$2.74/tr (legacy −$1.38)
- Fee+latency cost: $0.31–$1.47/trade per variant
- See `strategy_lab/reports/LIVE_MIMIC_WIRED_2026_05_16.md` for full diff

**CLOB winner column** now opt-in via `load_resolutions(..., with_clob_winner=True)`.
Bulk fetch is checkpointed every 200 markets; running in background.
100% agreement with chainlink on the ~2,300 markets fetched so far.

---

## Time windows by dataset

| dataset | window (UTC) | span |
|---|---|---:|
| **Backtest universe** (resolutions, chainlink-only) | **2026-04-24 01:40 → 2026-05-15 02:55** | **21.0 days** |
| Orderbook L25 (book at any time) | 2026-04-22 ~14:47 → 2026-05-15 ~01:45 | 22.5 days |
| Chainlink RTDS (1Hz oracle prices) | 2026-04-24 01:38 → 2026-05-15 03:30 | 21.1 days |
| Binance 1MIN klines (binance-spot-ws) | 2026-04-14 16:00 → 2026-05-15 03:01 | 30.5 days |
| Binance 1MIN klines (binance-vision archive) | 2026-04-05 03:03 → 2026-04-28 18:52 | 23.7 days |
| Coinbase 1MIN klines | 2026-04-08 00:56 → 2026-05-15 03:01 | 37.1 days |
| Kraken 1MIN klines | 2026-05-07 12:58 → 2026-05-15 03:01 | 7.6 days *(collector started May 7)* |
| OKX 1MIN klines | 2026-04-28 04:50 → 2026-05-15 03:01 | 16.9 days |
| Tier1 entries (entry book at ws+120s) | target_ts 2026-04-24 01:42 → 2026-05-15 02:57 | 21.0 days |
| ⚠️ **Polymarket trades** *(STALE — no fresh delta pulled)* | 2026-04-22 12:08 → **2026-05-06 15:20** | 14.1 days (ends 9d ago) |
| VPS3 trading.events (sleeve audit) | last 14 days through 2026-05-15 02:42 | 14 days |

**Recommended backtest window:** **2026-04-24 → 2026-05-15** (chainlink-only universe is fully covered; book data spans the entire window plus 1-2 days of pre-resolution context).

---

## Canonical data sizes (6.6 GB total)

| component | size | rows / detail |
|---|---:|---|
| `chainlink_rtds.parquet` | 89.9 MB | 5,187,932 (1.73M per asset, 1Hz × 21d) |
| `klines_1m.parquet` | 21.6 MB | binance + cex multi-venue, see table above |
| `resolutions.parquet` *(upstream)* | 2.5 MB | 24,108 markets (chainlink-only filter applied) |
| `resolutions_from_rtds.parquet` *(re-derived locally)* | 2.6 MB | 23,553 markets (99.87% match w/ upstream) |
| `orderbook_l25/btc.parquet` | 4.16 GB | 40,608,376 rows / 8,129 markets |
| `orderbook_l25/eth.parquet` | 870 MB | 7,565,995 rows / 8,124 markets |
| `orderbook_l25/sol.parquet` | 373 MB | 3,414,823 rows / 8,123 markets |
| `tier1_entries_at_t120/btc.parquet` | 4.6 MB | 15,808 (book at ws+120s) |
| `tier1_entries_at_t120/eth.parquet` | 3.2 MB | 15,406 |
| `tier1_entries_at_t120/sol.parquet` | 2.6 MB | 14,146 |
| `trades_polymarket/btc.parquet` | 569 MB | 14,977,215 *(Apr 22 - May 6 only)* |
| `trades_polymarket/eth.parquet` | 185 MB | 3,797,555 *(stale)* |
| `trades_polymarket/sol.parquet` | 79 MB | 1,576,205 *(stale)* |

### Resolutions per (asset, timeframe) — 23,553 markets
- BTC 5m: 5,887   |   BTC 15m: 1,964
- ETH 5m: 5,887   |   ETH 15m: 1,964
- SOL 5m: 5,887   |   SOL 15m: 1,964

---

## ⚠️ CANONICAL CONVENTION — `ws_s ≠ slot_start`

**Production controller's anchor for `ret_2m` and `fire_us` is `ws_s`, NOT the literal slug suffix.**
Get this wrong and your hit rate inflates 25–40 pp (the slug-ws bug).

```python
# Slug ↔ time mapping
slug_suffix    = int(slug.rsplit("-",1)[1])           # seconds
slot_start_us  = slug_suffix * 1_000_000
slot_end_us    = slot_start_us + window_s * 1_000_000  # window_s = 300 (5m) or 900 (15m)

# Production anchor
ws_s   = slug_suffix - window_s                        # PREVIOUS slot's start
ret_2m = log(close@(ws_s + 120) / close@(ws_s))        # 2-min pre-strike momentum
fire_us = (ws_s + 120) * 1_000_000                     # production fire wall-clock
```

Or use the load.py helpers directly:

```python
from load import slug_to_ws_s, add_ws_s, ret_2m_at_ws

ws_s   = slug_to_ws_s(slug, timeframe)
ret_2m = ret_2m_at_ws(end_us, prices, ws_s)
```

Production observes 2 min of **PRE-WINDOW** momentum and bets on the upcoming slot's outcome. The slot becomes the "prediction window" from ws_s+window_s to ws_s+2×window_s.

Reference: `strategy_lab/reports/SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`
Self-test: `py -3 -X utf8 data/v4/canonical/_test_ws_s.py` should print `=== ALL CHECKS PASSED ===`.

---

## Quick start (next session)

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import (
    load_resolutions,                    # chainlink-resolved markets
    load_klines, load_klines_asof,        # binance / cex 1MIN bars
    load_chainlink_rtds, load_chainlink_asof,
    load_orderbook_l25_streaming,         # filter by slugs to bound memory
    load_tier1_entries,                   # pre-joined entry book at ws+120s
    load_trades,
    asof_strict,                          # causal-correct asof lookup
    slug_to_ws_s, add_ws_s, ret_2m_at_ws, # ws_s helpers
)
import pandas as pd

# 1) Universe (default: locally-re-derived from chainlink RTDS)
res = load_resolutions()  # 23,553 markets
res = load_resolutions(assets=["BTC"], timeframes=["5m"])  # filtered: 5,887 BTC 5m markets

# 2) Binance signal source (asof closes for ws_s lookups)
end_us, prices = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
price_at_ws = asof_strict(end_us, prices, target_us=int(ws_s) * 1_000_000)

# 3) Chainlink ground-truth oracle (1Hz)
ts_us, cl = load_chainlink_asof("BTC")
strike     = asof_strict(ts_us, cl, target_us=int(ws_s + window_s) * 1_000_000)
settlement = asof_strict(ts_us, cl, target_us=int(ws_s + 2 * window_s) * 1_000_000)

# 4) Tier1 — book at ws+120s for every (slug, outcome) in the universe
tier1 = load_tier1_entries("btc")  # 15,808 rows

# 5) Full L25 streaming (filter by gated slugs to keep memory bounded)
gated_slugs = set(res[res.abs_ret_2m >= threshold].slug)
books = load_orderbook_l25_streaming("btc", slugs=gated_slugs)
# books[(slug, outcome)] = (ts_us[N], ap[N,25], asz[N,25], bp[N,25], bsz[N,25])
```

---

## Other artifacts (not in canonical/)

| path | contents | when to use |
|---|---|---|
| `data/v4/refresh_2026_05_12/vps3_trading_events_14d.csv` | All `trading.events` from VPS3 production engine, last 14d (~134K rows: signal/resolution/hedge_skip per sleeve) | sleeve performance analysis, A/B comparisons |
| `data/v4/refresh_2026_05_12/{btc,eth,sol}_flow_orderbook.csv` | Server-side aggregated orderbook flow features per minute (~3.1M rows total) | feature engineering for new strategies |
| `data/v4/refresh_2026_05_12/{btc,eth,sol}_flow_trades.csv` | Server-side aggregated trade CVD/aggressor features (~2.1M rows total) | trade-flow features |
| `data/v4/refresh_2026_05_12/hl_liquidations_btc_eth_sol.csv` | Hyperliquid liquidations 30d, BTC/ETH/SOL | liquidation-cascade triggers |
| `data/v4/refresh_2026_05_12/markets_full.csv` | Polymarket catalog (19,730 markets, includes platform, condition_id, clob_token_ids) | market-id lookups |
| `data/v4/shadow_trades_2026_05_09/all_sleeve_stats.csv` etc. | Per-sleeve stats snapshots used in 65-sleeve analysis | session-handoff context |

---

## Known issues & open work

1. **Polymarket trades data is STALE** (ends May 6, ~9 days old). The refresh script does NOT pull a trades delta — only the 05_06 cache is mirrored into canonical. **If your strategy uses trades, the working window is Apr 22 – May 6 only.** To fix: add a trades-delta step to `local_pull.sh` step 7.

2. **v3 family dispatcher bug NOT fixed** (per `TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`). Sleeves `v3, v3_1, v3_2, v3_3, v4` emit byte-identical signals on BTC/ETH ~98% of the time despite having different config. Sleeves still running in shadow; data is real, but the "5 variants" are effectively 2 classes. TV agent has the spec.

3. **SPREAD_FILTER experiment never run** — Phase 3+4 left -$1.69/trade gap on May 7-9 overlap; loosening the spread filter would likely close most of it. See `MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md`.

4. **`eth_5m_momo_v2_HOLD` has 24 qty_compute_failed events** in 7d — separate bug, file as ticket.

5. **Sniper signal direction may be inverted on SOL** (sol_5m_sniper -$824, sol_5m_sniper_INV +$394 — 237 trades each, mirror images). Worth investigating sniper signal code on VPS3 before disabling.

6. **refresh_2026_05_06/ (9.8 GB) still on disk** — canonical references its L25 cache for the early-window (Apr 22 - May 6) baseline. Cannot delete without breaking `build.py --step orderbook` re-runs.

---

## Recently completed (this session)

- ✅ Slug-ws anchor breakthrough — confirmed via brute-force across 300 audit rows
- ✅ Phase 3+4 — corrected anchor + lookahead-in-`find_book` fix; May 7 within $0.07/trade of production
- ✅ All-65-sleeve VPS3 audit (incl. delta tables across 3 snapshots)
- ✅ ETH 5m v3/v4 low-fire diagnosis (asset-specific spread issue + dispatcher clone bug)
- ✅ TV agent fix spec for v3 family differentiation
- ✅ Live-trading 6-sleeve picks (small-capital recommendation)
- ✅ Data refresh through May 15 + 3.7 GB local cleanup

Reports written this session:
- `strategy_lab/reports/MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md`
- `strategy_lab/reports/MOMO_SHADOW_SLEEVES_TABLE_2026_05_11.md`
- `strategy_lab/reports/ALL_SHADOW_SLEEVES_TABLE_2026_05_11.md`
- `strategy_lab/reports/ETH_5M_V3_V4_DIAGNOSIS_2026_05_11.md`
- `strategy_lab/reports/TV_AGENT_V3_FAMILY_DIFFERENTIATION_SPEC_2026_05_11.md`
- `strategy_lab/reports/DATA_INVENTORY_2026_05_15.md` *(this file)*

---

## Strategy ideas to test next (priority order)

### A. Per-cell winner deployment (high priority)
Best edges from corrected-anchor backtest + 14d shadow trading:

| cell | best policy | shadow $/tr | n_resolved | notes |
|---|---|---:|---:|---|
| btc_15m_momo_HOLD (v1) | HOLD | **+$10.73** | 23 | top per-trade EV, 73.9% WR |
| sol_5m_momo_HEDGE (v1) | HEDGE | +$3.37 | 116 | top all-time, +$95 last 12.5h |
| eth_15m_momo_v2_HOLD (v2) | HOLD | +$6.78 | 20 | 65% WR, v2 anchor |
| sol_5m_sniper_INV | (passthrough) | +$1.67 | 237 | inverted-sniper edge, largest n |
| eth_5m_sniper_DOWN_INV | (passthrough) | +$3.09 | 65 | ETH 5m direction-filtered |
| btc_5m_v3 | v3 | +$3.65 | 58 | hot recent (12.5h delta +$66) |

### B. Backtest replay with fresh data
- Re-run `momo_full_universe_validation.py` on the full Apr 24 - May 15 universe with corrected anchor + strict-asof book lookup. Should match the 14d shadow numbers within noise.

### C. Spread filter sensitivity
- Loosen `SPREAD_FILTER` from {BTC: 0.02, ETH: 0.02, SOL: 0.025} to {0.05, 0.05, 0.05} or remove entirely. Expected: close the -$1.89/trade gap to production HOLD. Compare against production avg entry $0.507 (very tight).

### D. Cross-asset signal arb
- v3 family hot on BTC 5m but flat on ETH/SOL. Test whether v3 signal generalizes across assets or is BTC-specific.

### E. Hour-of-day / day-of-week effects
- volume_INV_NIGHT fires 100% during night hours and is a structural bleeder. Test whether inverting the FILTER (only-day version) is the real edge.

### F. Sniper sign-flip experiment (data is already there)
- For every sniper trade, test "what would the opposite side have done?" Use VPS3 trading.events `sleeve_id LIKE '%sniper%'` payloads.

---

## How to start the next session

Recommended starting prompt:

```
Read this first: strategy_lab/reports/DATA_INVENTORY_2026_05_15.md

The canonical dataset at data/v4/canonical/ is fresh (Apr 24 - May 15 UTC, 23,553 chainlink-resolved markets). Use `from data.v4.canonical.load import *` for all data loads.

Production convention: ws_s = slot_start - window_s (PREVIOUS slot). Never use the slug suffix as ws_s directly — that's a 25-40pp hit-rate inflation bug.

[Then your task / strategy idea]
```

If running backtests, copy this prelude code:

```python
import sys; sys.path.insert(0, "data/v4/canonical")
from load import load_resolutions, load_klines_asof, load_chainlink_asof, load_tier1_entries, asof_strict, slug_to_ws_s
```

---

## Architecture reminders (won't change)

- All timestamps UTC microseconds. Never localize.
- Binance is the SIGNAL source (matches production controller).
- Chainlink is the OUTCOME source (settles binary; never derive from binance close).
- L25 = production fill model. Walk asks for $25 notional. Production fee = 2% on profit only (winning leg).
- VPS2 (Contabo IPv6: `root@[2605:a140:2323:6975::1]`) — markets catalog, cex klines, hl_liquidations.
- VPS3 (`root@185.190.143.7`) — everything else (orderbook 11GB, trades 3.2GB, binance 2GB, oracle 593MB, trading.events live).
- SSH keys: `~/.ssh/vps2_ed25519`, `~/.ssh/vps3_ed25519`.

---

*End of context document. Generated 2026-05-15.*
