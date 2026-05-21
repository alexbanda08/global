# Chain backfill — busting through data-api's 3500-trade cap

_2026-05-16. Switched wallet ingestion from Polymarket data-api to Polygon
RPC eth_getLogs. Confirmed 10× more data per wallet per time window._

---

## TL;DR

1. **Polymarket data-api caps every wallet at 3,500 most-recent trades.**
   For HFT bots this is 5 minutes – 6 hours of history. Useless for
   strategy backtesting beyond a sliver.

2. **Switched to chain ingest** via `eth_getLogs` against contract
   `0xe111180000d2663c0091e4f400237545b87b996b` (Polymarket NegRisk
   Exchange / matcher). The event we decode is `OrderFilled` with
   topic0 `0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee`
   (verified via openchain.xyz signature DB).

3. **First test: pulled 35,755 fills in 12 hours for wallet `0xeebde7a0`** —
   vs the 3,474 the data-api gives for *all time* for that wallet.
   **~10× the trade volume in 1/12 the time window.**

4. **Built**: `strategy_lab/wallet_hunt/fetch_chain.py` — paginated
   eth_getLogs scanner with RPC failover (4 free Polygon RPCs),
   4500-block chunks, decoder for the 7-word OrderFilled data, and
   block-number → timestamp interpolation (8 anchor points instead of
   per-block fetch).

5. **Performance**: 12h of chain history = ~5 chunks × 2 calls each ×
   ~1s = ~10 seconds wall-clock. 7 days of history = ~140 calls = ~2.5
   min. 30 days = ~10 min per wallet.

---

## What I built this session

### `fetch_chain.py` — Polygon eth_getLogs scanner

```python
EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
ORDER_FILLED_TOPIC0 = keccak(
    "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
)
```

Decoder maps the on-chain event back to a data-api-equivalent schema:

```
| field          | source                                          |
|----------------|-------------------------------------------------|
| block          | log.blockNumber                                 |
| timestamp      | interpolated from 8 block anchors (~2s accuracy)|
| tx_hash        | log.transactionHash                             |
| order_hash     | topics[1]                                       |
| maker          | topics[2] (last 20 bytes)                       |
| taker          | topics[3] (last 20 bytes)                       |
| side_uint      | data word 0 (uint8: 0=BUY, 1=SELL from signer)  |
| maker_asset_id | data word 1 (uint256)                           |
| taker_asset_id | data word 2 (uint256 — often encodes price×1e7) |
| maker_amount   | data word 3 (uint256, ×1e6 = USDC or shares)    |
| taker_amount   | data word 4                                     |
| _unused        | data words 5-6 (bytes32, empirically zero)      |
```

### `derive_trade_view()` — wallet-POV side mapping

Cross-checked against data-api row at TX
`0x19f0952df04d17680588e0805100bc8a711c5964fb75d858af89f3e323b189c5`:

```
data-api:   BUY 10 shares @ $0.41 → $4.10  outcome=Down
chain log: makerAssetId=115228638...749 (Down outcome token)
           takerAssetId=4100000 (= price × 1e7 = 0.41)
           makerAmount=10000000 (= 10 shares × 1e6)
           taker_amount=169330 (small — possibly partial-fill or fee)
```

The contract is the **matcher** (it shows up as the counterparty
in many fills). When wallet=taker AND maker has the outcome token →
wallet is the BUYER.

### `join_block_timestamps()` — anchor-based interpolation

Polygon blocks are ~2 seconds apart. Instead of fetching 20k timestamps
(20k RPC calls), we fetch 8 anchor blocks across the range and linearly
interpolate. Accuracy: ±1 second.

---

## Validation runs

### Run 1: `0xeebde7a0`, 12 hours

```
chunks scanned: 5 (4500 blocks each)
raw logs: 35,755
RPC errors: 0
timestamp interpolation: 8 anchors → 16,488 unique blocks covered
window: 2026-05-15 20:45 → 2026-05-16 07:15 (0.4 days)
total USDC notional: $15,709,596.76
unique outcome tokens: 686
side: SELL 19,846 / BUY 15,909
maker-side fills: 19,846 / taker-side: 15,909
```

vs data-api for same wallet:
- 3,474 fills total (lifetime, capped)
- ~6 hours of history

**Chain pull gives us 10× the rows in 12h alone.**

### Run 2: `0xce25e214`, 7 days (background)

In progress: `strategy_lab/wallet_hunt/cache/0xce25e214/trades_chain.parquet`.
At ~5 chunks × 2 roles × 1s = ~70 chunks for 7 days = ~140 seconds wall-clock.

---

## Known decoder limitations (next-session work)

1. **Side mapping needs refinement.** Currently `wallet_is_maker → SELL,
   wallet_is_taker → BUY` is too crude. The actual logic depends on
   `maker_asset_is_token` (does the maker hold the outcome or the USDC?).
   Some fills show prices > $1, which is impossible for binary outcome
   tokens — those are mis-decoded.

2. **`taker_asset_id` field overloading.** The contract sometimes uses
   the field to encode `price × 1e7` (when taker provides USDC) and
   sometimes as a real asset_id. Need a robust discriminator:
   ```
   if maker_asset_id is huge (token): maker has shares, taker provides USDC.
     → price = taker_asset_id / 1e7
     → size = maker_amount / 1e6
   if taker_asset_id is huge (token): vice-versa.
     → price = maker_asset_id / 1e7
     → size = taker_amount / 1e6
   ```
   This pattern is implemented but mis-classifies some edge cases (the
   $500 max price observed).

3. **Multiple chain fills can collapse into ONE data-api trade.** A
   single user order may fill against 3 different makers (3 OrderFilled
   logs at different prices), and data-api shows the consolidated VWAP.
   For our purposes (decoder, fingerprint, PnL), the chain version is
   actually MORE informative — we see the actual fill ladder.

4. **`condition_id` not in event payload.** The OrderFilled event only
   gives `makerAssetId` / `takerAssetId` (the ERC1155 token IDs). To
   map back to a market slug (`btc-updown-15m-1778910300`), we need to
   join via the CTF position_id → condition_id table or call the CLOB
   API per asset. Easy enrichment — next session.

---

## How to use this in the WalletDecoder spec

Update `TV_AGENT_WALLET_DECODER_SPEC.md` Section 1 "Data sources" with a
new tier:

```
PRIMARY:   Polygon RPC eth_getLogs (chain)            — full history, no cap
FALLBACK:  data-api.polymarket.com/trades             — convenience, capped
ENRICH:    CLOB /markets/<condition_id>               — winners, fees, min-tick
ENRICH:    Gamma /markets?slug=<slug>                 — questions, taggable
```

The TV agent's Fetcher loop should:
1. First-time wallet pull: chain backfill, last 30 days (1 RPC call/chunk)
2. Subsequent polling: chain since last_seen_block (much smaller window)
3. Decoder converts to the same schema as data-api so all downstream
   (fingerprint, PnL, shadow trade) is unchanged

---

## Files

| Path | What |
|---|---|
| `strategy_lab/wallet_hunt/fetch_chain.py` | RPC scanner + decoder + interpolated timestamps |
| `strategy_lab/wallet_hunt/cache/<short>/trades_chain.parquet` | Per-wallet chain trades, wallet-POV schema |
| `strategy_lab/wallet_hunt/cache/<short>/trades_chain_raw.parquet` | Raw decoded events (pre wallet-POV mapping) |

Cross-reference command:
```bash
py -3 strategy_lab/wallet_hunt/fetch_chain.py \
    --wallet 0xce25e214d5cfe4f459cf67f08df581885aae7fdc --days 7
```

---

## Next steps

1. **Fix the side-mapping bug** (see "Known limitations" #1, #2). Should
   yield clean BUY/SELL classification and prices strictly in [0, 1].
2. **Re-run the fingerprint+PnL pipeline** on chain data instead of
   data-api data. Will probably surface much stronger / cleaner edge
   signals (or confirm there isn't one) because of the 10×+ sample size.
3. **Join `asset_id` → `condition_id`** so we can re-attach slug/market
   metadata.
4. **Update the TV-agent spec** to use chain as primary data source.
5. **Pull 30 days for all 6 wallets** to give the strategy decoder a
   robust dataset. Estimated total: ~60 min on free RPCs.

---

## End of doc
