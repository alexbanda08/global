# Hyperliquid Data Schema Audit

**Generated:** 2026-05-26 by hl-audit-agent
**Purpose:** Map exactly what HL data we have (schema, time coverage, gaps, asset universe) before porting Polymarket strategies to Hyperliquid perpetuals.
**Data root:** `data/v4/canonical/` (HL) + `data/binance/futures/metrics/` (BBN-fut).

---

## TL;DR

| Source | Rows | Time range | Span | Assets |
|---|---|---|---|---|
| `hyperliquid_klines.parquet` | 181,339 | 2026-01-30 → 2026-05-16 07:04 UTC | 106.3d | BTC, ETH, SOL, HYPE |
| `hyperliquid_trades_30d.parquet` | 13,613,686 | 2026-04-30 18:54 → 2026-05-16 07:19 | 15.52d | BTC, ETH, SOL, HYPE |
| `hyperliquid_liquidations_30d.parquet` | 312,208 | 2026-04-16 07:27 → 2026-05-16 07:25 | 30.0d | 200+ coins (BTC/ETH/SOL/HYPE + alts) |
| `hyperliquid_liquidations_full.parquet` | 5,228,388 | 2025-05-25 → 2026-05-16 07:53 | 355.7d | 352 coins |
| `hyperliquid_funding.parquet` | 10,176 | 2026-01-30 00:00 → 2026-05-15 23:00 | 105.96d | BTC, ETH, SOL, HYPE |
| `hyperliquid_metrics.parquet` | 88,588 | 2026-04-30 18:58 → 2026-05-16 07:54 | 15.54d | BTC, ETH, SOL, HYPE |
| `binance_vision_klines.parquet` | 1,970,724 | 2025-04-27 → 2026-04-28 18:52 | 365d | BTC, ETH, SOL (spot, USDT) |
| `binance_metrics.parquet` (canonical) | 315,351 | 2025-04-27 → 2026-04-27 | 365d (5min) | BTC, ETH, SOL |
| `binance/futures/metrics/{BTC,ETH,SOL}USDT/parquet/year=*` | 1.5M total | 2020-09-01 → 2026-04-20 | up to 5.6yr | BTC (5.6yr), ETH (4.4yr), SOL (4.4yr) |

**Headline findings:**

1. **HL data is a 4-coin universe (BTC, ETH, SOL, HYPE) for klines/trades/metrics/funding.** Liquidations cover 352 coins (full file).
2. **HL klines: 106d at 1H/4H/1D, 67d at 15min, 33d at 5min, 19d at 1min.** Microstructure backtests are 5min-or-coarser if you want >2 weeks.
3. **HL trades: ~15.5d window, ~5 trades/sec on BTC.** Plenty for microstructure features over a 2-week eval window. Zero >1hr gaps in BTC.
4. **HL funding is hourly** (not 8-hourly like Binance). 105.95d clean coverage, no gaps. Per-asset funding signs differ — HYPE positive 6.8%/yr equiv, SOL negative -7.3%/yr equiv.
5. **HL liquidations FULL is 12 months deep** — the only HL dataset with >12 months coverage. Use for: regime studies, liquidation-cascade backtests, cross-asset systemic-risk events.
6. **Binance vs HL: price corr 0.99999, returns corr 0.9996 (1h overlap, n=1800).** Binance is a clean backbone. HL trades ~$37 (5 bps) below Binance spot on BTC 5m closes during overlap — useful as a "basis premium" feature.
7. **Backbone gap:** Binance vision klines end 2026-04-28; HL klines run to 2026-05-16. **For May 1-16, no Binance backbone unless we pull a fresh delta** (or use binance_futures metrics which run to 2026-04-20, similar gap).

---

## 1. HL canonical inventory

### 1.1 `hyperliquid_klines.parquet` (5.8 MB)

**Schema:**
```
time_period_start_us  int64    # Bar open time (UTC microseconds)
time_period_end_us    int64    # Bar close time (UTC microseconds)
time_open_us          int64    # CoinAPI normalization of first trade
time_close_us         int64    # CoinAPI normalization of last trade
symbol_id             object   # e.g. "HYPERLIQUID_PERP_BTC_USD"
period_id             object   # "1MIN" | "5MIN" | "15MIN" | "1HRS" | "4HRS" | "1DAY"
price_open            float64
price_high            float64
price_low             float64
price_close           float64
volume_traded         float64
trades_count          int64
source                object   # "hyperliquid-ws" (115K) | "hyperliquid-info" (66K)
```

**Time range:** 2026-01-30 00:00:00 UTC → 2026-05-16 07:04:00 UTC (106.29d global)

**Asset universe (4):** BTC, ETH, SOL, HYPE (all `HYPERLIQUID_PERP_*_USD`).

**Per (symbol, period) coverage:**

| Symbol | 1MIN | 5MIN | 15MIN | 1HRS | 4HRS | 1DAY |
|---|---|---|---|---|---|---|
| BTC  | 26402 rows (Apr 27 → May 16, ~19d) | 9282 (Apr 13 → May 16, ~33d) | 6429 (Mar 9 → May 16, ~68d) | 2511 (Jan 30 → May 16) | 635 | 107 |
| ETH  | 26399 | 9281 | 6429 | 2535 | 635 | 107 |
| SOL  | 26384 | 9280 | 6428 | 2535 | 635 | 107 |
| HYPE | 26266 | 9255 | 6420 | 2535 | 635 | 107 |

**Period interval distribution (rows):** `1MIN`: 105,451 | `5MIN`: 37,098 | `15MIN`: 25,706 | `1HRS`: 10,116 | `4HRS`: 2,540 | `1DAY`: 428.

**Source split:** WS feed for newer bars (~115K), `info` REST API for older bars (~66K).

**Gaps:** Small per-period gaps (1-4%). Worst is 1MIN at ~4.14% missing (expected 27.5K bars, actual 26.4K). 1HRS has one 1.8-day gap. 1D/4HRS/15MIN nearly complete.

**Sample row:**
```
time_period_start_us=1773063000000000 (2026-02-09T05:30 UTC)
symbol_id=HYPERLIQUID_PERP_BTC_USD  period_id=15MIN
price_open=68723.0  high=69200.0  low=68705.0  close=69199.0
volume_traded=1197.93  trades_count=13901  source=hyperliquid-info
```

### 1.2 `hyperliquid_trades_30d.parquet` (588 MB)

**Schema:**
```
time_exchange_us  int64     # Trade timestamp (UTC us) — primary time col
time_coinapi_us   float64   # CoinAPI receive time (mostly NaN in older rows)
symbol_id         string
price             double
size              double
taker_side        string    # "BUY" | "SELL"
trade_id          string
block_hash        string
source            string    # "hyperliquid-ws"
```

**Time range:** 2026-04-30 18:54:02 UTC → 2026-05-16 07:19:38 UTC (15.52d). Despite the "30d" filename, only 15.5d are populated.

**Asset universe (4):** BTC, ETH, SOL, HYPE.

**Per-asset rows & throughput:**

| Symbol | Trades | Rate |
|---|---|---|
| HYPERLIQUID_PERP_BTC_USD  | 6,497,388 | 4.85 trades/sec |
| HYPERLIQUID_PERP_HYPE_USD | 3,259,862 | 2.43 trades/sec |
| HYPERLIQUID_PERP_ETH_USD  | 2,308,466 | 1.72 trades/sec |
| HYPERLIQUID_PERP_SOL_USD  | 1,547,970 | 1.15 trades/sec |

**Taker side balance:** BUY 7.10M / SELL 6.51M (52% buy-pressure overall).

**Gap analysis (BTC):** zero >1hr gaps; max single gap = 3,551s (59m). Inter-trade gaps: p50=0.0s p95=1.07s p99=2.30s. Microstructure-grade.

**BTC trade size:** min 0.00001 BTC, p50 0.0006 BTC ($48 notional), p95 0.31 BTC ($24.8K), p99 1.07 BTC ($86K), max 100 BTC ($7.9M single print).

**Sample row:**
```
time_exchange_us=1777575455870000 (2026-04-30 18:57:35.870 UTC)
symbol_id=HYPERLIQUID_PERP_BTC_USD
price=76332.0  size=0.00607  taker_side=SELL  source=hyperliquid-ws
```

### 1.3 `hyperliquid_liquidations_30d.parquet` (21 MB)

**Schema:**
```
time_exchange_us    int64     # primary timestamp (us)
block_time_us       float64   # HL block time (when known)
block_number        float64
coin                object    # e.g. "BTC", "ETH", "HYPE", "FARTCOIN", "xyz:CL"
liquidated_user     object    # wallet of liquidatee
counterparty_user   object    # wallet of counterparty
side                object    # "B" or "A" (bid/ask, i.e. taker is buying/selling)
dir                 object    # "Open Long" | "Close Short" | "Liquidated Cross Long" | etc.
price               float64
size                float64
mark_price          float64
method              object    # "market" (5.1M) | "backstop" (62K) | "" (62K)
start_position      float64
closed_pnl          float64
crossed             object    # "t" or "f"
fee                 float64
fee_token           object    # "USDC"
tid                 int64
oid                 int64
block_hash          object
source              object    # "hl-s3-fills"
```

**Time range:** 2026-04-16 07:27:18 UTC → 2026-05-16 07:25:08 UTC (30.00d — clean rolling).

**Asset universe (~200 active):** Top: BTC 88,296 | ETH 33,470 | SOL 26,398 | xyz:CL 15,888 | xyz:BRENTOIL 8,410 | ZEC 8,212 | HYPE … (also includes oil futures, gold via `xyz:` prefix, niche perps).

**Direction breakdown:**
- `B` (taker bought) 88.9% / `A` (taker sold) 11.1% — heavily lopsided because HL "fills" includes both regular trades and explicit liquidations.

### 1.4 `hyperliquid_liquidations_full.parquet` (337 MB)

**Same schema as `_30d`.**

**Time range:** 2025-05-25 14:36:58 UTC → 2026-05-16 07:53:38 UTC (355.72d ≈ 12 months).

**Asset universe: 352 coins.**

**Top 20 by row count:**
| Coin | Rows | Coin | Rows |
|---|---|---|---|
| BTC | 1,143,494 | xyz:SILVER | 95,135 |
| HYPE | 765,365 | xyz:CL (crude) | 81,377 |
| ETH | 531,685 | ENA | 71,896 |
| SOL | 386,268 | kPEPE | 56,533 |
| FARTCOIN | 200,825 | SUI | 43,997 |
| XRP | 127,716 | DOGE | 43,025 |
| ZEC | 118,259 | xyz:BRENTOIL | 42,910 |
| XPL | 118,189 | ASTER | 42,850 |
| PUMP | 116,830 | kBONK | 41,831 |

**Notional distribution (USD per fill, full file):**
- ALL: min $0.0006 | p50 $558 | p95 $29.5K | p99 $129.7K | max $219.2M
- BTC: count 1.14M | p50 $1,178 | p95 $61.6K | p99 $250K | max $193.4M
- ETH: count 532K | p50 $1,275 | p95 $76.2K | p99 $346.8K | max $219.2M
- SOL: count 386K | p50 $866 | p95 $31.6K | p99 $112K | max $56.3M
- HYPE: count 765K | p50 $39 | p95 $7,744 | p99 $29.7K | max $16.6M

**Direction breakdown (`dir` col):**
- Open Long 2,588,652 (49.5%)
- Close Short 2,492,747 (47.7%)
- Short → Long flip 52,718
- Auto-Deleveraging 37,757
- Close Long 31,633
- **Liquidated Cross Long 10,820** ← true liquidation
- **Liquidated Isolated Long 9,679** ← true liquidation
- **Liquidated Isolated Short 3,690** ← true liquidation
- **Liquidated Cross Short 654** ← true liquidation
- Partial Borrow Liquidation 35

**Critical caveat:** Most rows are regular taker fills (`dir` = "Open Long"/"Close Short"). The actual liquidations are the **24,878** rows with `dir` starting with "Liquidated" + 37,757 ADL events = **~62K true liq events over 355d** (≈ 175/day). The `method=backstop` (62,638) ≈ matches the liquidation count, which is the HL backstop-liquidator vault auto-closing positions.

### 1.5 `hyperliquid_funding.parquet` (189 KB)

**Schema:**
```
funding_time_us  int64
symbol           object    # "BTC", "ETH", "SOL", "HYPE"
symbol_id        object    # "HYPERLIQUID_PERP_BTC_USD"
funding_rate     object    # stored as string, parse to float
premium          object    # stored as string, parse to float
source           object    # "hyperliquid-info"
```

**Time range:** 2026-01-30 00:00:00 UTC → 2026-05-15 23:00:00 UTC (105.96d).

**Frequency:** Hourly. BTC inter-row median = 3600.0s (no significant drift). **Zero >2hr gaps.** Rows per asset: 2,544 each (matches 105.96d × 24).

**Funding rate distribution (hourly, USDC):**

| Asset | mean | p1 | p50 | p99 | min | max | Annualized (×8760) |
|---|---|---|---|---|---|---|---|
| BTC  | 1.37e-6 | -2.87e-5 | 2.98e-6 | 1.25e-5 | -6.94e-5 | 1.25e-5 | +1.20%/yr |
| ETH  | 2.72e-6 | -3.35e-5 | 5.80e-6 | 1.25e-5 | -7.28e-5 | 1.25e-5 | +2.39%/yr |
| HYPE | 7.76e-6 | -3.80e-5 | 1.25e-5 | 1.38e-5 | -1.01e-4 | 4.96e-5 | +6.79%/yr |
| SOL  | -8.34e-6 | -6.58e-5 | -5.14e-6 | 1.25e-5 | -1.38e-4 | 2.82e-5 | -7.31%/yr |

**1.25e-5 cap** = 1.25 bps/hour = HL's documented funding-rate cap. SOL had sustained negative funding (shorts paying longs) — useful regime signal.

### 1.6 `hyperliquid_metrics.parquet` (5 MB)

**Schema:**
```
time_exchange_us         int64
symbol                   object    # "BTC" | "ETH" | "SOL" | "HYPE"
symbol_id                object
mark_price               float64
oracle_price             object (string-encoded float)
mid_price                object (string-encoded float)
open_interest            object (string-encoded float)
day_notional_volume      object (string-encoded float)
day_base_volume          object (string-encoded float)
funding_rate_running     object (string-encoded float, current 1H rate)
source                   object    # "hyperliquid-ws-actx"
```

**Time range:** 2026-04-30 18:58:15 UTC → 2026-05-16 07:54:33 UTC (15.54d).

**Per-asset rows:** 22,147 each × 4 = 88,588.

**Sample interval:** Median 60.42s per asset (i.e. **~1 sample per minute per asset**).

**Open interest stats (mean / median):**
- BTC: 29,640 / 29,421 BTC (~$2.25B notional at $76K)
- ETH: 538,935 / 533,366 ETH (~$1.21B)
- SOL: 3,777,384 / 3,817,842 SOL (~$314M)
- HYPE: 20,273,538 / 20,170,728 HYPE (~$790M)

**Source:** 100% `hyperliquid-ws-actx` (continuous WS metric stream).

---

## 2. Binance canonical inventory

### 2.1 `binance_vision_klines.parquet` (92 MB)

**NOTE:** CLAUDE.md says "11 symbols, 2018-2026" — **AUDIT FINDS ONLY 3 SYMBOLS**, range 2025-04-27 → 2026-04-28 (~12 months). Reconcile expectations against actual content.

**Schema:**
```
symbol_id             object   # "BINANCE_SPOT_BTC_USDT" etc.
period_id             object   # "1MIN" | "5MIN" | "15MIN" | "1HRS" | "4HRS" | "1DAY"
source                object   # "binance-vision"
time_period_start_us  int64
time_period_end_us    int64
price_open/high/low/close  float64
volume_traded         float64
trades_count          int64
quote_volume          float64
```

**Time range:** 2025-04-27 00:00 UTC → 2026-04-28 18:52 UTC (366d, but trails by ~1 month behind canonical refresh).

**Asset universe (3):** BTC, ETH, SOL (spot/USDT only — no futures pair).

**Per (symbol, period) coverage:**

| Period | BTC rows | ETH rows | SOL rows | End date |
|---|---|---|---|---|
| 1MIN  | 510,413 | 510,413 | 510,413 | 2026-04-28 |
| 5MIN  | 101,664 | 101,664 | 101,664 | 2026-04-14 |
| 15MIN | 33,888  | 33,888  | 33,888  | 2026-04-14 |
| 1HRS  | 8,472   | 8,472   | 8,472   | 2026-04-14 |
| 4HRS  | 2,118   | 2,118   | 2,118   | 2026-04-14 |
| 1DAY  | 353     | 353     | 353     | 2026-04-14 |

**Major issue:** Most periods stop at 2026-04-14 (~6 weeks before today). Only 1MIN runs to 2026-04-28. Refresh delta needed before using >Apr-14 windows.

### 2.2 `binance_metrics.parquet` (18 MB)

**Schema:**
```
create_time_us                       int64
symbol                              object    # "BTCUSDT" | "ETHUSDT" | "SOLUSDT"
sum_open_interest                   object (string-encoded float)
sum_open_interest_value             object (string-encoded float)
count_toptrader_long_short_ratio    object
sum_toptrader_long_short_ratio      object
count_long_short_ratio              object
sum_taker_long_short_vol_ratio      object
source                              object    # "binance-vision"
```

**Time range:** 2025-04-27 00:05 → 2026-04-27 00:00 (365d).

**Frequency:** 5-min cadence (mode = 300s, max gap = 1200s = 20min). Some 20-min gaps to investigate.

**Rows per asset:** 105,117 each (3 × 105,117 = 315,351).

**Use:** Binance futures-style sentiment proxies (long/short ratios). Despite "spot" symbol naming this data comes from Binance futures perpetual API — verified by long/short ratio fields which only exist for futures.

---

## 3. Binance Futures metrics inventory

`data/binance/futures/metrics/{BTCUSDT|ETHUSDT|SOLUSDT}/parquet/year=*/part.parquet`

**Schema (per `part.parquet`):**
```
create_time                          datetime64[ns, UTC]  ← already parsed
symbol                              object
sum_open_interest                   float64
sum_open_interest_value             float64
count_toptrader_long_short_ratio    float64
sum_toptrader_long_short_ratio      float64
count_long_short_ratio              float64
sum_taker_long_short_vol_ratio      float64
```

**Coverage per symbol:**

| Symbol | Files | Rows | Range |
|---|---|---|---|
| BTCUSDT | 7 (2020-2026) | 591,782 | 2020-09-01 → 2026-04-20 |
| ETHUSDT | 6 (2021-2026) | 460,948 | 2021-12-01 → 2026-04-20 |
| SOLUSDT | 6 (2021-2026) | 460,931 | 2021-12-01 → 2026-04-20 |

**Cadence:** 5 minutes (similar to canonical binance_metrics).

**This is the deepest dataset we have for long/short ratio + OI history** — 5.6 years for BTC. Use for: regime classification, long-horizon backtests, Binance-side training data for HL meta-classifier.

---

## 4. Asset universe table

| Asset | HL klines (any TF) | HL trades | HL liq full | HL funding | HL metrics | Binance vision | Binance fut metrics |
|---|---|---|---|---|---|---|---|
| BTC  | yes (106d) | yes (15.5d) | yes (12mo) | yes (106d) | yes (15.5d) | yes (1yr, 3 of 6 TFs to Apr-28) | yes (5.6yr) |
| ETH  | yes (106d) | yes (15.5d) | yes (12mo) | yes (106d) | yes (15.5d) | yes (1yr, same) | yes (4.4yr) |
| SOL  | yes (106d) | yes (15.5d) | yes (12mo) | yes (106d) | yes (15.5d) | yes (1yr, same) | yes (4.4yr) |
| HYPE | yes (106d) | yes (15.5d) | yes (12mo) | yes (106d) | yes (15.5d) | **NO** | **NO** |
| FARTCOIN, XRP, DOGE, SUI, kPEPE etc. (300+) | no | no | yes (12mo, liq events only) | no | no | no | no |

**Implication:** A 4-coin "BTC/ETH/SOL/HYPE" universe is the production-ready cross-section. HYPE has no Binance counterpart (it's HL-native) — features that require a cross-venue basis or external backbone will be HYPE-blind.

---

## 5. Binance vs HL price-discovery alignment

**5-minute close correlations (overlap = Apr 13-14 2026, ~2 days, n≈495):**

| Pair | Price Pearson | Returns Pearson |
|---|---|---|
| BTC HL-perp vs BNB-spot | **0.99996** | **0.99567** |
| ETH HL-perp vs BNB-spot | **0.99999** | **0.99635** |
| SOL HL-perp vs BNB-spot | **0.99995** | **0.99452** |

**1-hour close correlations (overlap = Jan 30 → Apr 14 2026, n=1800):**

| Pair | Price Pearson | Returns Pearson |
|---|---|---|
| BTC HL-perp vs BNB-spot | **0.999995** | **0.999629** |
| ETH HL-perp vs BNB-spot | **0.999997** | **0.999706** |
| SOL HL-perp vs BNB-spot | **0.999995** | **0.999601** |

**Basis:** BTC HL trades $-37.52 below Binance spot (median, 5m overlap) = -5.05 bps. **Stable, narrow, and tradeable as a feature** ("HL-perp / BNB-spot basis"). Consistent with HL being perp (carries funding) and Binance reading spot. The negative basis can flip during funding-rate regime changes — verify directional sign over a longer window.

**Conclusion:** Binance is a clean lead/lag backbone. Features built from Binance 1m/5m closes (momentum, range, RSI, ATR) carry essentially unchanged into HL-perp space.

---

## 6. Gaps and risks

### Critical

1. **HL trades is 15.5d, not 30d.** Despite filename. Microstructure backtests get one 2-week window.
2. **HL metrics is 15.5d.** Open interest history is bounded to that window. For long-horizon OI regime studies, must use `binance_futures/metrics/` proxies (BTC/ETH/SOL only — not HYPE).
3. **HL 1MIN klines: only ~19d (Apr 27 → May 16).** Anything needing 1-min features at scale will hit data-window walls quickly.
4. **HL 5MIN klines: only ~33d (Apr 13 → May 16).** Below the 60d threshold that's commonly cited as "minimum for parameter optimization without overfit".
5. **Binance vision lag:** Most TFs stop 2026-04-14. **No Binance backbone for May 1-16 in canonical** — pull a delta before joining.
6. **HYPE has no Binance reference.** All HYPE strategies are HL-only. Cross-venue arb / basis trades not available for HYPE.

### Moderate

7. **HL funding hourly vs Binance 8-hour.** When porting Polymarket carry strategies, the cadence mismatch matters for funding-as-return calculations.
8. **HL liquidations file mixes regular fills with true liquidations.** Filter on `dir LIKE 'Liquidated%' OR dir = 'Auto-Deleveraging'` for true liq events (~62K of 5.2M rows).
9. **HL metrics fields stored as strings.** `oracle_price`, `mid_price`, `open_interest`, `day_notional_volume`, `day_base_volume`, `funding_rate_running` all need `pd.to_numeric()` before computation. Same for `hyperliquid_funding.parquet`'s `funding_rate` and `premium`. Easy bug — handle in loader.
10. **HL liq 30d has ~4-week window, full has 12 months but is 337MB.** Full file load is expensive; use a streaming-by-coin filter for production.
11. **HL klines source mixed:** ~64% WS, ~36% info-REST. The REST rows may differ slightly from WS (different aggregation rounding). Check if backtests are source-sensitive — sort by source before computing realized vol if so.

### Minor

12. **Funding rate has documented cap at 1.25e-5/hr = 1.25 bps/hr.** When backtesting funding-carry, expect saturation at this cap during strong basis events.
13. **HL trades `time_coinapi_us` is mostly NaN.** Always use `time_exchange_us`.
14. **Binance metrics interval is 5min with occasional 20min gap.** Negligible for daily-resolution sentiment features.

---

## 7. Recommendations for HL strategy backtesting

### Eval windows by strategy type

| Strategy class | Recommended window | Why |
|---|---|---|
| **Microstructure (sub-minute, trade-level)** | 2026-05-01 → 2026-05-16 (15d) | Limited by trades_30d. Use BTC for highest trade rate (4.85/sec). |
| **5-min momentum / mean-reversion** | 2026-04-13 → 2026-05-16 (33d) | Bounded by HL 5MIN klines start. Roughly equivalent to Polymarket Apr-24 → May-15 window. |
| **15-min momentum / Polymarket-port** | 2026-03-09 → 2026-05-16 (68d) | Use HL 15MIN klines. Closest to Polymarket lab's 32-day backtest convention with extra margin for train/test split. |
| **Funding-carry / basis** | 2026-01-30 → 2026-05-15 (106d) | HL funding is the binding column. Hourly cadence is fine. |
| **Regime / multi-month walk-forward** | 2025-05-25 → 2026-05-16 (355d) | Only HL liq_full reaches back that far. Combine with `binance_futures/metrics/` for OI/long-short context. **No HL klines back that far** — must rebuild from chain replay or accept liq-only signal. |

### Production parity recommendations

- **Match Polymarket lab convention:** anchor signal computation on a `ws_s` equivalent. For HL the natural anchor is `time_period_start_us` of the 5m/15m bar. The "ret_2m" → next-2-bar-return convention from Polymarket maps directly to a "ret_5m/ret_15m" on HL.
- **Engine-v2 port:** wire a `HLLiveMimicConfig` that accepts (a) **HL taker fee 0.045%** baseline, (b) **HL maker fee 0.015% rebate**, (c) **funding accrual hourly**, (d) **L1 latency ~30-50ms** (assume Frankfurt VPS to HL Arbitrum sequencer), (e) **slippage from `hyperliquid_trades_30d` book-walk on size**.
- **HYPE-specific:** Without Binance backbone, HYPE backtests must rely entirely on HL data. Recommend using HL-internal mid_price (from metrics) + HL trades + HL funding rate as the feature panel. Skip cross-venue features for HYPE.
- **Liquidation-cascade features:** Filter liq_full to `dir LIKE 'Liquidated%'` and aggregate to 1-min/5-min bins per coin. Use as exogenous shock features in classifier. Largest signal mass is in BTC + HYPE.
- **Refresh priority before deploy:**
  1. Pull binance_vision delta to close the 2026-04-14 → today gap (5m/15m/1h needed for backbone features).
  2. Pull HL klines through today (last entry 2026-05-16, today is 2026-05-26 — 10-day lag).
  3. Refresh HL trades_30d to roll forward (15-day window currently ends May 16; needs May 11-26 to align with today minus 30d).
  4. Refresh HL metrics (15d → 30d ideal).

### Strategy-port shortlist (informed by data limits)

1. **5MIN momo (15-min port → 5-min HL):** 33d eval window, n≈8500 bars per asset × 4 assets = 34K observations. Sufficient for univariate feature scans, marginal for multi-feature ensembles.
2. **15MIN momo direct-port:** 68d, n≈6400/asset × 4 = 25.6K. Best window for replicating Polymarket lab patterns.
3. **Liquidation-cascade meta-classifier:** 12 months of liq events × 350 coins. Sparse on rare-coin axis but dense on BTC/ETH/SOL/HYPE.
4. **Funding-carry sleeve:** 106d × 4 assets × 24 hours = 10.1K funding rows. Test directional carry, sign-flip detection, regime persistence.
5. **HL-Binance basis trade (BTC/ETH/SOL only, skip HYPE):** 75-day overlap window for clean basis stats; longer if Binance refresh lands.

### Forbidden window combinations

- Do **not** join HL 1MIN klines (Apr-27→May-16) to Binance 1MIN klines (Apr-27 2025→Apr-28 2026) without checking overlap explicitly. Overlap is only Apr-27→Apr-28 2026 (≈2 days). Wrong join produces near-zero rows.
- Do **not** assume HYPE has a Binance leg. All HYPE arbitrage / basis strategies require an on-HL counterpart (e.g., HYPE/BTC ratio on HL itself).

---

**End of audit.**
