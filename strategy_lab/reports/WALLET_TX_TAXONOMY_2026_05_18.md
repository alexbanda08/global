# Wallet TX taxonomy — 4 maker wallets

**Date:** 2026-05-18
**Scope:** Full transaction-type breakdown for the 4 PAIR-ACCUMULATOR wallets
**Data sources:** `strategy_lab/wallet_hunt/cache/<short>/{alchemy_transfers,trades_chain,fires_decoded,positions}.parquet`
**Intermediate outputs:** `strategy_lab/wallet_hunt/cache/_taxonomy/` (`taxonomy_summary.json`, `per_slug_timing.json`, `per_slug_stats.json`, `capital_recycling.json`, `<wallet>_classified.parquet`)

---

## TL;DR

| Wallet | Daily PnL (catalog) | TX/day | CLOB-BID-FILL share | Merge-via-relay share | Capital (peak pUSD) | Velocity (vol/peak) | Bid fills/top-slug | Take buys/top-slug | Merges/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **0x89b5cdaa** | $10k | 22,265 | 92.4% | 4.7% | $52,783 | 21.3 | 125 | 0 | 1,048 |
| **0x04b6d7e9** | $212k | 35,914 | 94.6% | 0.53% | $47,184 | 280.7 | 410 | 2 | 189 |
| **0xeebde7a0** | $344k | 53,838 | 68.7% + 29.1% CLOB-MIXED | 0.97% | $369,812 | 260.6 | 235 (maker) + 448 (taker) | 448 | 523 |
| **0xf7f0b0b1** | $281 | 637 | 82.5% | 12.9% | $1,882 | n/a (no TC) | (no TC) | (no TC) | 82 |

Velocity = trade USDC notional/day ÷ peak pUSD balance. Higher = more capital recycling per day.

---

## Definitions & contract addresses

```
ZERO    = 0x0000000000000000000000000000000000000000      (mint/burn sink)
MATCHER = 0xe111180000d2663c0091e4f400237545b87b996b      (Polymarket CLOB matcher)
RELAY   = 0xf3cfb6a6ebfeb51876289eb235719eb1c65252b0      (relay wallet — handles merge for all 4)
USDC    = 0x3c499c542cef5e3811e1192ce70d8cc03d5c3359      (USDC contract on Polygon)
pUSD    = 0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb      (Polymarket pUSD)
CTF     = 0x4d97dcd97ec945f40cf65f87097ace5ea0476045      (conditional token framework)
```

The classifier groups every Alchemy transfer event by `tx_hash`, then assigns a single label per tx using priority rules over the set of `(asset, direction, counterparty)` triplets present. Trade events from `trades_chain.parquet` are joined to refine CLOB-side semantics.

---

## Part 1 — TX-type breakdown per wallet

Counts come from `_taxonomy/taxonomy_summary.json`. Notional is the sum of all USDC/pUSD value moved within each tx (over-counts both-sides flows but is a faithful "money touched" metric). `tc_usdc` is the trade-event USDC notional (cleaner for CLOB rows).

### 0x89b5cdaa — solo "merger" reclassified as relay-managed
window: 2026-05-11 21:58 → 2026-05-16 09:59 UTC (4.50 d), 100,193 unique tx

| Type | Count | % | Notional | TC USDC |
|---|---:|---:|---:|---:|
| CLOB-BID-FILL | 92,598 | 92.42 | $6.34M | $5.26M |
| RELAY-OUT (= merge route) | 4,717 | 4.71 | $845k | $0 |
| P2P-TRANSFER | 1,661 | 1.66 | $14k | $0 |
| CLOB-ASK-FILL | 851 | 0.85 | $12k | $0 |
| BURN-REDEEM (settlement) | 211 | 0.21 | $0 | $0 |
| OTHER | 147 | 0.15 | $19k | $0 |
| PUSD-MISC | 7 | 0.01 | $5k | $0 |
| EXT-WITHDRAWAL | 1 | 0.00 | $5 | $0 |
| **MINT** | **0** | 0 | $0 | $0 |
| **BURN-MERGE (direct mergePositions)** | **0** | 0 | $0 | $0 |

**Correction to project doc:** The "solo merger" label is wrong. Zero direct `mergePositions` calls. ALL merging is routed through the relay (0xf3cfb6a6). The 211 burn-to-ZERO txs are post-settlement `redeemPositions` calls (multiple distinct expired tokens at once, 3-49 assets per tx, no accompanying pUSD inflow visible in alchemy data — they are settlement claims, not merges).

### 0x04b6d7e9 — BTC-only, almost pure maker
window: 2026-05-13 15:11 → 2026-05-16 08:45 UTC (2.73 d), 98,043 unique tx

| Type | Count | % | Notional | TC USDC |
|---|---:|---:|---:|---:|
| CLOB-BID-FILL | 92,699 | 94.55 | $22.5M | $21.4M |
| P2P-TRANSFER | 4,443 | 4.53 | $43k | $0 |
| RELAY-OUT | 515 | 0.53 | $1.24M | $0 |
| CLOB-MIXED | 344 | 0.35 | $256k | $245k |
| OTHER | 39 | 0.04 | $0 | $0 |
| PUSD-MISC | 3 | 0.00 | $7k | $0 |
| **MINT / BURN-MERGE / BURN-REDEEM** | **0** | 0 | $0 | $0 |

Cleanest maker template — 94.5% of tx are CLOB-BID-FILL, no settlement redeems, very few takes.

### 0xeebde7a0 — hybrid maker+taker (largest by volume)
window: 2026-05-15 08:34 → 2026-05-16 10:01 UTC (1.06 d), 57,068 unique tx

| Type | Count | % | Notional | TC USDC |
|---|---:|---:|---:|---:|
| CLOB-BID-FILL (pure maker) | 39,193 | 68.68 | $18.9M | $18.5M |
| CLOB-MIXED (maker + taker same tx) | 16,595 | 29.08 | $67.6M | $67.3M |
| RELAY-OUT | 555 | 0.97 | $631k | $0 |
| P2P-TRANSFER | 420 | 0.74 | $19k | $0 |
| OTHER | 303 | 0.53 | $369k | $0 |
| PUSD-MISC | 2 | 0.00 | $936 | $0 |
| **MINT / BURN-MERGE / BURN-REDEEM** | **0** | 0 | $0 | $0 |

29% of tx are mixed maker+taker — this wallet does aggressive taker take-outs alongside passive making. That dual mode is responsible for the $344k/day figure and explains why its TC notional dwarfs the others ($85.8M vs ~$22M for 0x04b6d7e9).

### 0xf7f0b0b1 — tiny maker, no TC cache
window: 2026-05-13 00:35 → 2026-05-16 13:30 UTC (3.54 d), 2,256 unique tx

| Type | Count | % | Notional |
|---|---:|---:|---:|
| CLOB-BID-FILL (inferred from transfers) | 1,862 | 82.54 | $12k |
| RELAY-OUT | 291 | 12.90 | $12k |
| P2P-TRANSFER | 95 | 4.21 | $275 |
| PUSD-MISC | 8 | 0.35 | $2k |

12.9% relay-out share — highest of all 4 (vs 0.5-4.7% elsewhere). Tiny notional confirms catalog $281/day estimate. No `trades_chain.parquet` is cached for this wallet so taker/maker classification is inferred from transfers only.

---

## Part 2 — Per-slug behavior (top-20 BTC 5m slugs, medians)

From `per_slug_stats.json`. `bid_fill` = `wallet_is_maker=True AND trade side=SELL` (taker SELL hit our posted BID → we BOUGHT). `take_buy` = `wallet_is_taker=True AND side=BUY`. `take_sell` is essentially always zero — these wallets NEVER market-sell to exit, they recycle through merge.

| Wallet | Med bid fills | Med ask fills | Med take buy | Med take sell | Med notional/slug | BTC5m slug count |
|---|---:|---:|---:|---:|---:|---:|
| 0x89b5cdaa | 125 | 0 | 0 | 0 | $8.5k | 1,404 |
| 0x04b6d7e9 | 410 | 0 | 2 | 0 | $35.6k | 196 |
| 0xeebde7a0 | 235 | 0 | 448 | 0 | $435k | 1,341 |
| 0xf7f0b0b1 | (no TC) | | | | | 1,216 (from fires) |

Key observations:
- `n_ask_fills ≈ 0` in EVERY wallet → these wallets do not post ASK orders. They are buy-side-only makers.
- `n_take_sell ≈ 0` in EVERY wallet → they never market-sell. Exit is always merge (via relay).
- 0xeebde7a0 has near-equal bid-fills and take-buys: it's a hybrid that augments passive accumulation with aggressive market-buys when the book offers price.
- 0x04b6d7e9 concentrates fire activity on far fewer slugs (196 vs 1,300+ for others) → highly selective slug picker, deeper participation per slug.

Cadence (median seconds between fills within a slug) computes to 0 for all wallets because many fills land in the same block (~2s Polygon block time). To resolve true cadence we'd need millisecond CLOB event-tape; from `fires_decoded.offset_from_slot_start_s` we know firing covers 0-770s within the 300s 5m slug life.

---

## Part 3 — Timing within slug (offset_from_slot_start_s)

From `per_slug_timing.json` and counterparty-conditional medians captured during decode:

| Wallet | Overall med | Counterparty=MATCHER med | Counterparty=RELAY med | Counterparty=OTHER med | Mean |
|---|---:|---:|---:|---:|---:|
| 0x89b5cdaa | 195s | 150s | 336s | 214s | 230s |
| 0x04b6d7e9 | 127s | 125s | 350s | 166s | 151s |
| 0xeebde7a0 | 222s | 209s | 334s | 300s | 311s |
| 0xf7f0b0b1 | 142s | 72s | 336s | 22,052s | 2,593s |

**Pattern (consistent across all 4):**
1. **Phase 1 — early fills (0-200s post slot_start):** counterparty = MATCHER. Passive BIDs sit on the book; taker SELLs hit them. The wallet accumulates inventory.
2. **Phase 2 — mid/late merge (~330-340s consistently):** counterparty = RELAY. Wallet sends paired Up+Down tokens to relay; relay returns pUSD in the same tx. Merge always happens after most fills have completed.
3. **Phase 3 — settlement (only for 0x89b5cdaa, hours later):** counterparty = ZERO (CTF). 211 redeem txs.

The relay-merge offset clusters tightly at ~336s — that's about 36s into the next 5m slot. So merging consistently happens once the previous slot is resolved (5m slot ends, 30s grace, then relay merges the surviving paired inventory).

The OTHER bucket median for 0xf7f0b0b1 (22,052s = 6.1 h) is dominated by stale wallet-relay reconciliation events captured outside the active trading windows.

---

## Part 4 — Capital recycling

From `capital_recycling.json` (windows differ — values calibrated to each wallet's available AT/TC date range).

| Wallet | Days observed | Initial pUSD deposit (visible) | Peak pUSD balance | Current pUSD | Total trade vol | Daily trade vol | **Velocity (vol/peak)** | Merges/day |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0x89b5cdaa | 4.50 | $53,946 | $52,783 | $41,265 | $6.89M | $1.12M | **21.3×/day** | 1,048 |
| 0x04b6d7e9 | 2.73 | $6,914 | $47,184 | $46,680 | $21.6M | $13.2M | **280.7×/day** | 189 |
| 0xeebde7a0 | 1.06 | $936 | $369,812 | $363,552 | $590M | $96.4M | **260.6×/day** | 523 |
| 0xf7f0b0b1 | 3.54 | $2,141 | $1,882 | $997 | n/a | n/a | n/a | 82 |

Caveats:
- "Initial pUSD deposit" = sum of all pUSD inflows from non-trading addresses (ZERO/MATCHER/RELAY excluded). For most wallets this is small because the bulk of capital may have arrived before the alchemy snapshot window.
- 0x04b6d7e9 and 0xeebde7a0 have AT and TC windows that don't perfectly align — daily volume uses TC's longer window which can slightly overestimate velocity for 0xeebde7a0 (TC span = 6.12 d while AT span = 1.06 d).
- The merge cadence for 0x89b5cdaa (1,048/day = ~1 merge every 1.4 min) vs only 189/day for 0x04b6d7e9 (~1 every 7.6 min) reflects that 0x89b5cdaa fires across many more slugs per slot and aggregates inventory across many tiny markets.

Capital is overwhelmingly recycled, not held: peak pUSD ≈ current pUSD in all wallets, and daily volume is 20-280× the peak balance. Net pUSD drains by `daily_pnl × days` over the window.

---

## Part 5 — Consolidated comparison

| Wallet | Daily PnL (catalog) | Daily vol | Capital (peak) | Velocity | Bid fills/slug | Take buys/slug | Merges/day | Operates on |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 0x89b5cdaa | $10k | $1.12M | $52,783 | 21.3× | 125 | 0 | 1,048 | BTC/ETH/SOL × 5m+15m |
| 0x04b6d7e9 | $212k | $13.2M | $47,184 | 280.7× | 410 | 2 | 189 | BTC only × 5m+15m |
| 0xeebde7a0 | $344k | $96.4M | $369,812 | 260.6× | 235 | 448 | 523 | BTC + ETH × 5m+15m |
| 0xf7f0b0b1 | $281 | n/a | $1,882 | n/a | (no TC) | (no TC) | 82 | BTC/ETH/SOL × 5m+15m |

---

## Patterns to encode in our shadow strategy

1. **NEVER market-sell to exit.** Inventory exits exclusively via merge (relay route). Holding both sides and merging avoids paying spread crossings on exit.
2. **NEVER post ASKs.** All 4 wallets are BID-only makers. The strategy is one-directional: accumulate inventory via passive BIDs, then merge paired Up+Down at slot resolution.
3. **Fire window:** 0-770s offset from slot_start; most fills land 70-220s in (mid-slot). Don't post BIDs in the last 60s before resolution — by then merging is starting.
4. **Merge timing:** ~336s after slot_start = ~36s after the prior 5m slot resolves. The relay handles merge, not the wallet itself.
5. **Slug breadth:** Trade-off between depth (0x04b6d7e9, 196 slugs at 410 fills/slug) and breadth (0x89b5cdaa, 1,404 slugs at 125 fills/slug). Both are profitable, but velocity is 13× higher when concentrating.
6. **Hybrid maker+taker (0xeebde7a0) is the volume king.** Adding aggressive market-buys (~2× the maker fills) doubles volume and PnL but requires real-time book monitoring infrastructure that pure makers don't need.
7. **No MINT activity.** None of these wallets call `splitPosition` to mint paired tokens from pUSD. They acquire both sides on the open market, then merge. This means we don't need CTF mint infrastructure for the maker side.
8. **Relay is mandatory for the merge route.** All 4 wallets use the SAME relay (`0xf3cfb6a6`). Whether the relay is a separate EOA we control, a smart contract, or a service from a counterparty needs separate decoding — but the relay is integral to the strategy and must be deployed alongside any shadow.

---

## Cleanest template

**0x04b6d7e9** is the cleanest template to copy:
- 94.6% pure CLOB-BID-FILL (highest among the 4), only 0.04% OTHER, zero settlement noise.
- BTC-only — single market scope simplifies the trigger surface and the data wiring (we already have BTC 5m/15m books, kline asof, chainlink, etc. fully wired).
- 280.7× velocity — proves a small capital base ($47k) recycles aggressively to generate $212k/day PnL ($13.2M daily turnover). Realistic seed for a paper deploy.
- 196 slug concentration is teachable: the slug-selector is decodable from a much smaller universe than 0x89b5cdaa or 0xeebde7a0.
- Zero burn-redeem noise — they don't hold expired markets to settlement; the relay-merge cycle is closed.

0x89b5cdaa is harder because of the 211 settlement redeems and 1,404-slug spread; 0xeebde7a0 is too big and too hybrid for a first replication; 0xf7f0b0b1 is too small to extract reliable signal.

---

## Files written

- `strategy_lab/wallet_hunt/cache/_taxonomy/taxonomy_summary.json` — Part 1 raw
- `strategy_lab/wallet_hunt/cache/_taxonomy/per_slug_timing.json` — slug fire counts + offset-from-slot-start medians
- `strategy_lab/wallet_hunt/cache/_taxonomy/per_slug_stats.json` — Part 2 raw
- `strategy_lab/wallet_hunt/cache/_taxonomy/capital_recycling.json` — Part 4 raw
- `strategy_lab/wallet_hunt/cache/_taxonomy/<wallet>_classified.parquet` — per-tx classification with features (for downstream filtering)
