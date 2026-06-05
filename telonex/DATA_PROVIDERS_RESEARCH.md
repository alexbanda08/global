# Polymarket 5m/15m + crypto-derivatives data — provider research (2026-06-04)

Goal: find the best source (free or paid) for **5m/15m BTC/ETH/SOL up-or-down** Polymarket
book+trade history, deeper than Telonex ($79, Oct-2025-start), incl. crypto liquidations.

---

## ★ TOP FINDINGS (the two that matter)

### 1. FREE dataset of our EXACT markets — `trentmkelly/polymarket_crypto_derivatives` (HuggingFace)
- **BTC/ETH/SOL/XRP up-or-down 5m + 15m** — exactly our universe.
- **L2 order book depth + CLOB events + decision snapshots** at ~100ms cadence.
- Includes `chainlink_price` + `binance_price` aligned per snapshot (mirrors our signal stack).
- Schema: `steps.parquet` (per-decision: best bid/ask/mid/spread/imbalance + chainlink+binance px), `events.parquet` (CLOB trades/price-changes), `book_levels.parquet` (full depth: outcome/side/level/price/size). 47,006 market episodes.
- **Window: 2026-02-21 → 2026-03-24** (~32 days). License CC-BY-SA-4.0. **FREE.**
- `_old` version (~208M rows) = an earlier window, deprecated.
- URL: https://huggingface.co/datasets/trentmkelly/polymarket_crypto_derivatives
- ⚠️ HF web viewer throws FileSystemError — files still download fine via `huggingface-cli download --repo-type dataset`.
- **Value to us:** extends our book history ~2 months earlier than our Apr-22 canonical, for free, same markets. Gap Mar 24→Apr 22 remains.

### 2. Cheapest paid option, OUR markets — PolyHistorical ($17/mo)
- **Crypto Up/Down only** (BTC/ETH/SOL, 5m/15m/1h/4h/24h) — precisely our use case, nothing wasted.
- Full L2 book @ **300ms** snapshots, 13,000+ resolved markets (per-market from creation).
- **Also bundles Binance spot + futures L2 depth** (Pro tier).
- "Strategy Replay" backtest-on-real-books feature.
- Free tier = BTC last 50 markets only. **$17/mo Pro.**
- URL: https://polyhistorical.com · docs https://docs.polyhistorical.com
- **vs Telonex:** 4.6× cheaper, laser-focused on our markets, +Binance futures book. Telonex wins only on generality (all market categories) + onchain_fills-to-2022. Collection-start date unconfirmed (likely also 2024-2025).

---

## Free routes — full list

| Source | Data | Window | Notes |
|---|---|---|---|
| **trentmkelly/polymarket_crypto_derivatives** (HF) | **L2 book + trades**, BTC/ETH/SOL/XRP 5m/15m | Feb 21–Mar 24 2026 | ★ only free pre-collected L2 for our markets |
| **SII-WANGZJ/Polymarket_data** (HF) | on-chain fills (trades only, no book), all markets | 2020 → May 2026, 1.9B rows / 163GB | filter by conditionId; crypto slugs present |
| **AiYa1729/polymarket-transactions** (HF) | on-chain fills + PnL | 2022 → Mar 2025, 45.6M | MIT |
| **data-api.polymarket.com/trades** | trades (price/size/side/wallet/slug/outcome) | all-time, no auth | paginate `market=<conditionId>`; max ~offset 10k/market |
| **clob.polymarket.com/prices-history** | last-trade price OHLC series (no book) | back to first trade, no auth | fidelity in minutes |
| **gamma-api.polymarket.com/markets** | metadata only (slug→conditionId→token_id) | — | enumerate 5m/15m slugs |
| **Dune `polymarket_polygon.market_trades`** | on-chain trades, all markets | 2022+ | free 2,500 credits/mo; SQL; no book |
| **rocklabs.io/data** | **31.6B full-tick CLOB L2 events** + 45M trades | Jan 2026+ | FREE for students/academics (email hello@rocklabs.io); commercial price unknown |
| **martkir/poly-trade-scan** (GitHub, 78★) | on-chain fills via free Polygon RPC | Nov 2022+ | CLI, no book |
| **yannbellec/polymarket-btc-scraper** (GitHub) | self-collect BTC 5m: 1Hz L2 + trades + binance spot → Parquet | go-forward | ★ targets our exact market; ~$2/mo Railway or free local |
| **weiminglong/poly-book** (GitHub, Rust) | self-collect L2 book → Parquet/ClickHouse | go-forward | best collector code |

**No free pre-collected L2 book exists before ~Feb 2026** (trentmkelly) or Jan 2026 (rocklabs). Pre-2026 = trades/fills only.

---

## Paid Polymarket providers

| Provider | Price | Book history start | Trade history | Book detail | Scope | Verdict |
|---|---|---|---|---|---|---|
| **PolyHistorical** | **$17/mo** | unconfirmed (≤2025) | same | full L2 @300ms | **crypto up/down only** (+Binance futures) | ★ best value for US |
| **Telonex** | $79/mo | **Oct 11 2025** | +onchain_fills to **2022** | L5/L25/full @tick | all categories + Binance spot | current; generalist |
| **PolymarketData.co** | undisclosed | Aug 2025 | Jan 2024 price (no book) | full L2 @1min | all categories | coarser; price opaque |
| **Dune** | free–$399 | none (no book) | 2022+ on-chain | — | all + Kalshi | cheap trades, no book |

**Hard truth (confirmed 3 ways): NO provider has Polymarket L2 book before ~Aug–Oct 2025.** Nobody captured the CLOB WS feed commercially before then; it cannot be reconstructed. Pre-2025 = on-chain fills only (no bids/asks). This matches our catalog finding (Telonex crypto book starts Oct 11 2025; epoch-15m markets are all post-Apr-22).

---

## Crypto derivatives / liquidations (separate purchase — no Polymarket overlap)

| Provider | Liquidations | Funding/OI | Book | Binance liq start | Bybit/OKX | Bitget/Gate | Price |
|---|---|---|---|---|---|---|---|
| **Tardis.dev** ★ | **tick archive** | tick | incremental L2 | **Nov 2019** | Dec 2020 | Bitget Nov-2024 (no liq); Gate (no liq) | ~$100–200/mo solo; **1 free CSV/mo/exchange** |
| CoinGlass | aggregated (tick only last 7d) | yes | no | ~2019 agg | ~2019 agg | yes | $29 Hobbyist / $299 Standard |
| Laevitas | yes (5yr) | yes | snapshots | ~2019 | ~2019 | **no** | pay-per-request (x402) |
| Coinalyze | aggregated | yes | no | 2–3yr | 2–3yr | partial | ~$30–150/mo |
| **Binance.vision** (free) | **NO** | **NO** | no | — | — | — | free (klines/trades only) |
| Bybit public (free) | NO | NO | no | — | — | — | free (trades only) |

- **Deepest tick liquidations = Tardis.dev** (Binance Nov-2019, Bybit/OKX Dec-2020). Free: first-day-of-month CSV per exchange — `https://datasets.tardis.dev/v1/{exchange}/liquidations/{Y}/{M}/{D}/{SYMBOL}.csv.gz`.
- **Gate + Bitget liquidations don't exist anywhere** (exchanges don't broadcast them) — our VPS3 gate/okx liq feed is already near best-available for those.
- **No free deep Binance liquidation archive** — binance.vision excludes it. Self-collect (we do) or buy Tardis.
- **No one-stop shop** for Polymarket + derivatives — always two purchases.

---

## RECOMMENDATIONS

1. **Free first, today:** pull `trentmkelly/polymarket_crypto_derivatives` (HF) — free L2 book for our exact BTC/ETH/SOL 5m/15m markets, Feb–Mar 2026. Validate schema-join to our canonical, extends history ~2mo free.
2. **If paying for Polymarket book:** **PolyHistorical $17/mo** beats Telonex $79 for our narrow crypto-up/down need (+ Binance futures book). Telonex only if you need all market categories or onchain_fills→2022 (and Dune gives those fills for free anyway).
3. **Reality check:** no L2 book exists before ~Aug-Oct 2025 anywhere — stop hunting for pre-2025 book; it wasn't recorded. Pre-2025 = trades/fills only (free via SII-WANGZJ / data-api / Dune).
4. **Derivatives/liquidations depth:** **Tardis.dev** (separate, ~$100-200/mo or one-off date-range purchase) for Binance/Bybit/OKX tick liquidations to 2019-2020. Gate/Bitget liq unavailable everywhere.
5. **Go-forward self-collection** (free): we already collect L25 + futures on VPS3; `yannbellec/polymarket-btc-scraper` confirms the approach. Keep our collectors as the canonical go-forward source.

## Key sources
HF: trentmkelly/polymarket_crypto_derivatives, SII-WANGZJ/Polymarket_data, AiYa1729/polymarket-transactions ·
polyhistorical.com · telonex.io · polymarketdata.co · dune.com (polymarket_polygon.market_trades) ·
tardis.dev · coinglass.com · data.binance.vision ·
GitHub: martkir/poly-trade-scan, yannbellec/polymarket-btc-scraper, weiminglong/poly-book, SII-WANGZJ/Polymarket_data ·
rocklabs.io/data · data-api.polymarket.com/trades · arXiv:2605.11640 (PMXT)
