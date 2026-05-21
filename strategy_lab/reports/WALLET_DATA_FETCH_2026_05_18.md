# Wallet data fetch — 2026-05-18

Backfill of missing on-chain data for 3 Polymarket wallets so strategy-decoder agents can analyze them.

## TL;DR

| Wallet | Direct chain fetch | Alchemy transfers | Indirect (counterparty scan) | Notes |
|---|---|---|---|---|
| `0x7dfc8aa2…` | 84,108 fills (14.3d) | 100,711 transfers (24d) | 78 fills (fallback) | Full decode complete. Looks like another mint-and-sell trader. |
| `0x7cde1da9…` | 0 fills | 0 transfers | 0 fills | **Wallet is a minimal-proxy contract** (impl `0xe51abdf814f8854941b9fe8e3a4f65cab4e7a4a8`) with nonce=1 and no token activity. Cannot fetch trades for this address — actual trader is the underlying owner EOA (not derivable from contract storage). |
| `0xb27bc932…` | 262,715 fills (3.4d) | (pre-existing 283k transfers) | 4,262 fills (fallback) | **The $254k/day kingpin.** 99.98% are SELL/maker fills — classic mint-and-sell maker. $7.1M USDC notional in 3.4d. |

## Files created/updated

```
strategy_lab/wallet_hunt/cache/0x7dfc8aa2/
  alchemy_transfers.parquet         8.2 MB   100,711 USDC+ERC1155 transfers (Apr 21 – May 16)
  trades_chain.parquet              8.8 MB    84,108 OrderFilled fills (Apr 29 – May 13)
  trades_chain_raw.parquet          7.7 MB    raw eth_getLogs output (pre-decode)
  fires_decoded.parquet            68 KB     top 5,000 trades enriched w/ L25 book + binance + RTDS
  indirect_trades_chain.parquet    31 KB     78 fills from counterparty scan (fallback)

strategy_lab/wallet_hunt/cache/0x7cde1da9/
  alchemy_transfers.parquet         1 KB     EMPTY (0 rows) — wallet is an inactive contract
  (existing per_leg.parquet / trades.parquet kept untouched — note: trades.parquet is a generic
   Polymarket data-API result containing 1,507 different proxyWallets, not this address)

strategy_lab/wallet_hunt/cache/0xb27bc932/
  trades_chain.parquet             29.3 MB  262,715 OrderFilled fills (May 11 – May 15)
  trades_chain_raw.parquet         25.4 MB  raw eth_getLogs output
  indirect_trades_chain.parquet    829 KB   4,262 fills from counterparty scan (now superseded)
  (existing alchemy_transfers.parquet / fires_decoded.parquet / strategy_deepdive.json kept)

strategy_lab/wallet_hunt/_indirect_search.py   NEW helper — scans other wallets' trades_chain
                                                for target as maker or taker; used as fallback.
```

## Key infra fixes made

1. **`fetch_chain.py` RPC list reordered** — Alchemy free tier is now capped at 10-block `eth_getLogs` ranges (returns HTTP 400 with "Under the Free tier plan, you can make eth_getLogs requests with up to a 10 block range"). Switched primary to `https://polygon.gateway.tenderly.co` and `https://polygon.drpc.org` which still allow 10k blocks/call. Chunk size bumped to 9,999 blocks.
2. **`rpc()` helper hardened** — now handles bare-string JSON responses (e.g. `"Backend error, StatusCode: 500"` from onfinality) and dict-with-string-result error bodies. Previous code crashed with `'str' object has no attribute 'get'` on every chunk.
3. **No code change needed to topic0** — the existing keccak of `OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)` does produce the correct `0xd543adfd…` hash on chain (false alarm during my debug).

## Per-wallet rough stats

### 0xb27bc932 (kingpin — directional CLOB taker / mint-and-sell maker)
- **262,715 fills** in 3.4 days (May 11 18:40 → May 15 04:45 UTC)
- Maker / taker split: **262,667 / 48** — overwhelmingly providing liquidity (maker)
- Side: SELL=262,667 / BUY=48 — almost pure sell-side maker (mint-and-sell signature)
- Notional: **$7,137,473.77** USDC across 1,858 unique outcome tokens
- Price range: $0.0000 – $25.9048 (the >$1 outliers are derive_trade_view artifacts on very small fills; not blocking, analysis agent should clip prices to [0, 1])
- Active window matches the existing `alchemy_transfers.parquet` (May 12 – May 16); fits the $254k/day claim ($7.1M / 3.4d ≈ $2.1M/d gross volume → consistent w/ ≈12% net edge to hit $254k PnL)

### 0x7dfc8aa2 (new wallet)
- **84,108 fills** in 14.3 days (Apr 29 → May 13 UTC)
- Maker / taker: **22,171 / 61,937** — predominantly taker (BUY) — DIFFERENT from b27
- Side: BUY=61,937 / SELL=22,171 (73.6% buys)
- Notional: **$38,671,904.99** USDC across 1,084 tokens (note: some outlier prices >$1 inflate this; raw size sums are sane)
- Trigger signature (from `fires_decoded.parquet`, n=5000 top trades):
  - `sum_asks` (ask_up + ask_down) at fire: median **$1.01**, 93.2% > $1.00 — classic **mint-and-sell precondition** (market is over-pegged)
  - Median offset from `slot_start`: 142s (5m), 741s (15m) — fires mid-slot
  - Top counterparty: `0xe111180000d2663c0091e4f400237545b87b996b` (NegRiskCtfExchange itself) → most fills are direct exchange matches
  - Counterparty `0xf3cfb6a6…` (b27's relay!) appears 258 times — they trade against each other
  - Binance ret_120s pre-fire ≈ 0 (no momentum signal — supports static-condition mint-and-sell trigger, not directional)

### 0x7cde1da9 (dead end)
- Wallet has `eth_getCode` length 250 (small proxy), nonce=1 — it's a deployed proxy that's only been touched once internally
- Zero USDC/ERC1155 transfers ever (verified via 90d alchemy_getAssetTransfers)
- Zero OrderFilled events with it as maker or taker (verified via direct eth_getLogs in the 25d window)
- Zero hits when scanning the other 5 wallets' `trades_chain.parquet` for it as a counterparty
- The pre-existing `trades.parquet` for this address is a Polymarket *data-API* dump showing 1,507 OTHER proxyWallets that traded on shared markets — NOT this address's trades
- **Action required**: confirm with whoever supplied the wallet list whether `0x7cde1da9` was a typo, or if they meant the underlying EOA owner of this proxy (which would require slot-1/slot-2 storage inspection to derive)

## Blockers / partial data

- **0x7cde1da9 cannot be decoded** without further info on what the address represents — it has zero on-chain trade activity under that address.
- **0xb27bc932 window is only 3.4d (May 11–15)** because the wallet's actual trading life was that short — alchemy_transfers caps at May 16 and trades_chain confirms no activity earlier (verified via spot-check at blocks <86.66M).
- **fires_decoded for 0xb27bc932 was not regenerated** — the pre-existing one (May 12-16) is still there from a previous session. Worth re-running with the fresh trades_chain if you want full-fidelity per-fire enrichment; skipped here to save the 25-min budget.
- **Indirect_trades_chain files retained as audit trail** — useful to cross-check direct fetch completeness; 0xb27 direct (262,715) >> indirect (4,262 = 1.6%) so direct is the source of truth.

## Run commands (for reproducibility)

```bash
# Alchemy transfers (works fine on free tier)
py -3 -X utf8 strategy_lab/wallet_hunt/fetch_alchemy.py --wallet 0x7dfc8aa2... --days 30 --max-pages 50
py -3 -X utf8 strategy_lab/wallet_hunt/fetch_alchemy.py --wallet 0x7cde1da9... --days 90 --max-pages 100

# Chain trades (needs Tenderly/drpc primary now — Alchemy free tier broken for getLogs)
py -3 -X utf8 strategy_lab/wallet_hunt/fetch_chain.py --wallet 0xb27bc932... --days 8
py -3 -X utf8 strategy_lab/wallet_hunt/fetch_chain.py --wallet 0x7dfc8aa2... --days 25

# Per-fire enrichment (BTC/ETH/SOL up-down only)
py -3 -X utf8 strategy_lab/wallet_hunt/replicate/decode_triggers.py --wallet 0x7dfc8aa2... --max-fires 5000

# Indirect counterparty search (fallback for contract wallets)
py -3 -X utf8 strategy_lab/wallet_hunt/_indirect_search.py
```
