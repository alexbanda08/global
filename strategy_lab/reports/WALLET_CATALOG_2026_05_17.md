# Wallet Catalog — 9 Operator-Provided Polymarket Wallets

_2026-05-17. Cross-wallet strategy decode + funder clustering._

**Source data**:
- Genesis: walked Alchemy from block 0 in ASC order (`cache/_first_deposit.csv`)
- 30d Alchemy transfer history (USDC + ERC1155) — `cache/<short>/alchemy_transfers.parquet`
- Cash PnL — `cache/_cash_pnl_summary.csv` (counterparty-classified)
- Trigger fingerprints — `cache/<short>/fires_decoded.parquet` (decode_triggers.py output)
- Master fusion — `cache/_master_catalog.csv`

---

## 0. TL;DR

**These 9 wallets are NOT mint-and-sell operators.** They are the
counterparty side: **directional CLOB takers** that buy ONE side of
up-down markets (mostly the cheaper side) when `sum_asks > $1`.

Three distinct populations:

| Class | n | Total PnL (sample) | Per-day implied |
|---|---|---|---|
| `directional_clob_taker_at_mispricing` | 6 | **+$1,045,547** | range $-40 to $254,467 |
| `mixed_clob_taker_seller` | 1 | +$42,742 | $9,498/day |
| `non_updown_polymarket_trader` | 2 | +$590,249 | $19,266 / $166,620 |
| **Total** | 9 | **$1,678,538** | — |

**Distinct from previously decoded mint-and-sell wallets**
(`0xeebde7a0`, `0x04b6d7e9`, `0xf7f0b0b1`): those mint pairs on-chain and
post limit SELL orders as makers. These 9 do **zero on-chain minting**
and operate purely on CLOB (mostly as buy-side takers).

---

## 1. Per-wallet detail

### Top-line PnL ranking

| Wallet | Strategy | Span | Total PnL | $/day | Note |
|---|---|---:|---:|---:|---|
| **0xb27bc932** | directional_clob_taker | 3.61d | **+$918,627** | **$254,467** | Largest scale; 99% buys |
| 0x0fe40e88 | non_updown_pm_trader | 27.61d | +$531,932 | $19,266 | Long-running; trades non-up-down markets |
| 0x3e6bfd2f | non_updown_pm_trader | 0.35d | +$58,317 | $166,620 | Brand new (9h); non-up-down |
| 0x7f599984 | directional_clob_taker | 7.02d | +$44,569 | $6,349 | Buys cheap side (own_ask $0.36) |
| 0x89b5cdaa | mixed_clob_taker_seller | 4.50d | +$42,742 | $9,498 | 61% buy / 39% sell — only mixed wallet |
| 0x9dae874a | directional_clob_taker | 7.02d | +$41,420 | $5,900 | Cheap-side buyer (own_ask $0.40) |
| 0xa0a50783 | directional_clob_taker | 7.02d | +$40,915 | $5,828 | Mid-price (own_ask $0.50) |
| 0xeefe46de | directional_clob_taker | 2.03d | +$191 | $94 | Bleeds out — losing on partials |
| 0xcfb103c3 | directional_clob_taker | 4.37d | **-$175** | -$40 | **Net negative** — counter-example |

### Strategy fingerprint (decode_triggers output)

| Wallet | Fires sampled | Buy% | sum_asks_mean | own_ask_mean | own_bid_mean |
|---|---:|---:|---:|---:|---:|
| 0xb27bc932 | 600 | **99.0%** | $1.0128 | $0.549 | $0.541 |
| 0xeefe46de | 600 | 96.0% | $1.0208 | $0.419 | $0.422 |
| 0x9dae874a | 600 | 88.8% | $1.0133 | $0.402 | $0.414 |
| 0x7f599984 | 1500 | 87.9% | $1.0165 | $0.355 | $0.352 |
| 0xa0a50783 | 600 | 72.0% | $1.0126 | $0.495 | $0.487 |
| 0xcfb103c3 | 600 | 71.7% | $1.0150 | $0.488 | $0.522 |
| 0x89b5cdaa | 600 | 60.8% | $1.0129 | $0.536 | $0.528 |
| 0x3e6bfd2f | (no up-down activity) | — | — | — | — |
| 0x0fe40e88 | (no up-down activity) | — | — | — | — |

### Cash flow detail

| Wallet | trading_in | trading_out | capital_in | capital_out | n_open_pos | open_val |
|---|---:|---:|---:|---:|---:|---:|
| 0xb27bc932 | $1,586,612 | $647,930 | $9,945 | $30,000 | 0 | $0 |
| 0x0fe40e88 | $2,539,396 | $1,779,631 | $3,091 | $230,924 | 0 | $0 |
| 0x3e6bfd2f | $141,002 | $82,802 | $117 | $0 | 0 | $0 |
| 0x7f599984 | $190,993 | $158,956 | $12,641 | $109 | 0 | $0 |
| 0x89b5cdaa | $952,373 | $965,029 | $53,951 | $35 | 23 | $1,482 |
| 0x9dae874a | $211,196 | $204,319 | $34,546 | $4 | 0 | $0 |
| 0xa0a50783 | $160,651 | $162,475 | $43,529 | $790 | 0 | $0 |
| 0xeefe46de | $225,530 | $180,104 | $350 | $45,586 | 0 | $0 |
| 0xcfb103c3 | $1,060,833 | $1,064,121 | $9,412 | $6,492 | 100 | $194 |

---

## 2. Strategy class detail

### 2.1 `directional_clob_taker_at_mispricing` (6 wallets, +$1,045,547 PnL)

**Trigger condition**: `sum_asks > $1.005` (median $1.01)

**Behavior**: When the up-down market's two asks together exceed $1
(structural mispricing), buy ONE side as a CLOB taker (cross the spread,
pay ask, get tokens). Hold to chainlink resolution.

**Why it works** (hypothesis):
- Market `sum_asks > $1` means makers have offered both sides at a
  guaranteed-loss combined price → some takers/sellers must be there to
  absorb. Combined probability priced > 1.0 → individual side priced
  *higher* than its true probability.
- The wallet picks the side with the lower ask and bets it'll resolve at $1.
- Edge = (true_win_prob − ask_price). They must have a directional view
  (binance momentum? oracle drift?) that beats the implied ask price.

**Wallet variants by buy_pct**:
- **Pure buyers** (96-99% buy): `0xb27bc932`, `0xeefe46de` — never sell
- **Mostly buyers** (87-89% buy): `0x7f599984`, `0x9dae874a` — occasional defensive sells
- **Selective buyers** (72%): `0xa0a50783`, `0xcfb103c3` — more 2-way trading

**Outliers**:
- `0xb27bc932` is 99% buys with **$254k/day** PnL — looks like a
  high-conviction directional bot, possibly with its own price feed
  (frequencies don't match either binance or chainlink alone).
- `0xcfb103c3` is the same strategy class but **losing $40/day** — possibly
  a beginner version of the strategy or weak signal source.

### 2.2 `mixed_clob_taker_seller` (1 wallet, +$42,742 PnL)

**0x89b5cdaa** — 60.8% buy / 39.2% sell. ONLY wallet in our 9 with
significant SELL activity (235 sells / 600 sample). Has **6 on-chain
mints** (small, not pure mint-and-sell) and **1705 erc1155 burns**
(possibly mergePositions). Holds 23 open positions worth $1,482.

Likely **hybrid strategy**: directional taker most of the time + occasional
mint-and-sell when sum_asks gap is wide enough to maker.

This wallet was previously classified as "mint-and-sell" in the May 16
handoff doc. With more data (30d of transfers vs earlier 4-day window),
the picture is more nuanced — it does mostly directional CLOB activity.

### 2.3 `non_updown_polymarket_trader` (2 wallets, +$590,249 PnL)

These wallets trade Polymarket markets but **zero up-down tokens**. Their
ERC1155 trades are sports / elections / news / other event markets.

- **0x0fe40e88** ($19k/day, 27.6d): 12,946 erc1155 trades, all non-up-down.
  Sustained operator running on different categories. Capital_out >> capital_in
  meaning they're net withdrawer ($230k withdrawn vs $3k deposited in window).
- **0x3e6bfd2f** ($166k/day extrapolated, only 0.35d sample): 3,556 erc1155
  trades, all non-up-down. **Brand new wallet** (9h activity at scan time)
  with already 29,901 PUSD minted (large bridge-in) and huge throughput.

The decode_triggers script can't analyze these — it's hardcoded for the
`(btc|eth|sol)-updown-(5m|15m)` slug pattern. Need a separate decoder for
sports/elections/news Polymarket markets.

---

## 3. Funder clusters (treasury-tree analysis)

Same parent wallet funded multiple of the analyzed wallets:

### Cluster F1 — `0xf70da97812cb96acdf810712aa562db8dfa3dbef` (3 wallets)

| Child | Genesis seed | Genesis date | Strategy |
|---|---:|---|---|
| 0x89b5cdaa | $999.50 USDCE | 2026-02-22 | mixed_clob_taker_seller |
| 0xb27bc932 | $9.93 USDCE | 2026-03-03 | directional_clob_taker (the $254k/day one) |
| 0x0fe40e88 | $9.99 USDCE | 2025-12-10 | non_updown_pm_trader |

Same parent also funded `0xeebde7a0` (mint-and-sell, $344k/day) from the
prior session. So `0xf70da978...` is a **diversified treasury** funding
multiple strategy types: directional, mixed, mint-and-sell, non-up-down.

Combined PnL across F1 children analyzed here:
- 0x89b5cdaa: $42,742
- 0xb27bc932: $918,627
- 0x0fe40e88: $531,932
- **F1 total (these 3): $1,493,302**

### Cluster F2 — `0x3a9418b2651c8164db5ebc56f12008137865e0f7` (2 wallets)

| Child | Genesis seed | Genesis date | Strategy |
|---|---:|---|---|
| 0xa0a50783 | $34.36 + $4998.88 PUSD bridge | 2026-05-10 / 11 | directional_clob_taker |
| 0x9dae874a | $20.22 + $4998.88 PUSD bridge | 2026-05-10 / 11 | directional_clob_taker |

These 2 wallets:
- Got PUSD-bridged the SAME day (2026-05-10 11:44-11:48 UTC, 4-minute spread)
- Got USDC seed from same parent SAME day (00:45 UTC on 2026-05-11)
- Run identical strategy
- Have identical PnL scale (~$5.8k/day)

→ **Same operator running 2 parallel wallets** on the same strategy.

### Singletons (1-wallet funders)

| Wallet | Funder | Strategy |
|---|---|---|
| 0x7f599984 | `0x0c2c4a70fa198aaaf805ff8f7659ce6c3aaf2cf2` | directional_clob_taker |
| 0x3e6bfd2f | `0xde879292253ad02262b1c710fe5625658589d369` | non_updown_pm_trader |
| 0xeefe46de | `0x514938b5625a234afa7fcf693228c359a0ffca67` | directional_clob_taker |
| 0xcfb103c3 | `0xbfa061ecafe23ca0db242456b36780e81d8f74bf` | directional_clob_taker (losing) |

---

## 4. Cross-strategy comparison

### What previously-decoded mint-and-sell wallets do differently

Comparing this batch with the 4 mint-and-sell wallets from session
`2026-05-16`:

| Aspect | Mint-and-sell (0xeebde7a0 etc.) | This batch (directional takers) |
|---|---|---|
| On-chain mints | Many (splitPosition) | Zero |
| USDC out to CTF | Large (mint cost) | Zero |
| Top counterparty | CLOB matcher (NegRisk) | CLOB matcher (NegRisk) |
| Wallet side | Mostly SELL (maker) | Mostly BUY (taker) |
| Edge source | Spread capture + maker rebate | Directional prediction |
| Risk on partials | Inventory of unfilled side | None — directional anyway |
| Capital efficiency | High (rebate income) | Lower (taker pays full ask) |

### Implications

The Polymarket up-down ecosystem has **at least 3 distinct profitable
strategies coexisting**:

1. **Mint-and-sell makers** (0xeebde7a0 cluster) — supply liquidity
2. **Directional CLOB takers** (this batch) — pick winners from mispriced books
3. **Non-up-down operators** (0x0fe40e88, 0x3e6bfd2f) — different markets entirely

Strategies 1 and 2 trade with each other. The mint-and-sell maker SELLS
the pair; the directional taker BUYS the cheap side. Both can be profitable
because:
- The maker captures spread + rebate on the side that fills
- The taker captures directional edge on the side they bought

---

## 5. Open questions

1. **What signal source do directional takers use?**
   `0xb27bc932` (99% buys, $254k/day) clearly has predictive power. Binance
   ret_2m at fire shows median ≈ 0 → not classical momentum. Needs deeper
   investigation (Tier-1 microstructure? insider feeds? cross-asset?).

2. **What markets do 0x0fe40e88 and 0x3e6bfd2f trade?**
   Need a non-up-down decoder. Could be NBA, NFL, election, news markets.

3. **Why does 0xcfb103c3 LOSE money** running the same strategy class as
   profitable peers? Possibly weak signal, late entries, or different
   slug selection.

4. **Is 0x89b5cdaa really hybrid?** The 6 mints + 1705 burns suggest some
   on-chain activity, but at low frequency. Worth decoding the actual
   mint events to see what slugs they minted on.

5. **F1 treasury (0xf70da978...) outbound wallets**: how many other
   wallets has it funded that we haven't analyzed? A `_funder_graph.py`
   walking `0xf70da978...` outbound transfers would reveal the full
   treasury fan-out.

---

## 6. Files

- [strategy_lab/wallet_hunt/_master_catalog.py](../wallet_hunt/_master_catalog.py) — single-shot fusion script
- [strategy_lab/wallet_hunt/cache/_master_catalog.csv](../wallet_hunt/cache/_master_catalog.csv) — final table
- [strategy_lab/wallet_hunt/cache/_first_deposit.csv](../wallet_hunt/cache/_first_deposit.csv) — genesis seeds
- [strategy_lab/wallet_hunt/cache/_cash_pnl_summary.csv](../wallet_hunt/cache/_cash_pnl_summary.csv) — counterparty-classified PnL
- `strategy_lab/wallet_hunt/cache/<short>/fires_decoded.parquet` — per-wallet enriched trade context
- [strategy_lab/wallet_hunt/_first_deposit_alchemy.py](../wallet_hunt/_first_deposit_alchemy.py) — genesis fetcher
- [strategy_lab/wallet_hunt/replicate/decode_triggers.py](../wallet_hunt/replicate/decode_triggers.py) — trigger enrichment

## 7. Next session pickup

If you bring more wallets:
```bash
# Single command per new wallet
py -3 strategy_lab/wallet_hunt/_first_deposit_alchemy.py --wallet 0x<addr>
py -3 strategy_lab/wallet_hunt/fetch_alchemy.py --wallet 0x<addr> --days 30
py -3 strategy_lab/wallet_hunt/cash_pnl.py --wallet 0x<addr>
py -3 strategy_lab/wallet_hunt/replicate/decode_triggers.py --wallet 0x<addr> --max-fires 600

# Then refresh catalog (add the wallet to TARGET_SHORTS first)
py -3 strategy_lab/wallet_hunt/_master_catalog.py
```

Outstanding work to make this fully automated:
- `_register_wallet.py` — single command that runs all 4 steps + appends to TARGET_SHORTS
- `_funder_graph.py` — walks any funder's outbound to find new wallets to decode
- Non-up-down market decoder for 0x0fe40e88 / 0x3e6bfd2f-type wallets
