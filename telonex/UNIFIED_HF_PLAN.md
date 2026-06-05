# Unified HF backfill plan — 3 datasets → our canonical (2026-06-05)

Combine trentmkelly + bmoney1321 + aliplayer1 into our canonical, each contributing
what it's best at, cross-backfilling outcomes. End state: BTC/ETH/SOL/XRP full-depth
book history extended back to Jan 2026 + BBO for BNB/DOGE/HYPE + ground-truth resolutions.

## What each dataset uniquely contributes

| Dataset | Coins | TF | Book | Trades | Resolutions | Window | Raw size |
|---|---|---|---|---|---|---|---|
| **trentmkelly** | BTC, ETH | 5m,15m | **FULL L2 @100ms** | yes (events) | derive from settle | Feb 21–Mar 24 | ~36 GB |
| **bmoney1321** | BTC,ETH,SOL,XRP | 5m,15m | full (JSON levels), ~15 days | yes (+maker) | **REAL (17,972 mkts)** | Jan 9–Mar 13 | ~1.6 GB |
| **aliplayer1** | BTC,ETH,SOL,BNB,XRP,DOGE,HYPE | 5m,15m,1h,4h | **BBO only** | yes (ticks) | **REAL (markets.resolution + up/down token)** | ~Mar–Apr 2026 | 27 GB |

## Target canonical layout (additions)

```
canonical/
  orderbook_l25/{btc,eth,sol,xrp}.parquet      <- FULL-DEPTH (trentmkelly BTC/ETH, bmoney SOL/XRP); sol already exists (VPS3)
  orderbook_bbo/{btc,eth,sol,bnb,xrp,doge,hype}.parquet  <- NEW: top-of-book (aliplayer 7 coins); best_bid/ask/size
  trades_polymarket/{btc,eth,sol,xrp,bnb,doge,hype}.parquet  <- extend + add bnb/doge/hype
  resolutions_hf.parquet                       <- NEW: ground-truth outcomes from bmoney + aliplayer (all coins)
```
Schema notes:
- L25 wide (103 cols) — already matches; bmoney JSON levels pivot to it, capped at 25.
- BBO table: `timestamp_us, slug, outcome, best_bid, best_ask, best_bid_size, best_ask_size`.
- resolutions_hf: `market_id, slug, ticker, timeframe, slot_start_us, slot_end_us, outcome, source`.

## Cross-backfill rules (precedence)

1. **Book depth**: prefer FULL (trentmkelly > bmoney) over BBO (aliplayer). For BTC/ETH use trentmkelly; SOL/XRP use bmoney full where present, else aliplayer BBO; BNB/DOGE/HYPE = aliplayer BBO only.
2. **Resolutions (outcomes)**: REAL > derived. Precedence: aliplayer markets.resolution / bmoney resolutions/all  >  trentmkelly settle-derived. Join by slug (`{coin}-updown-{tf}-{epoch}` is common across all three).
3. **Trades**: union all, dedup by (slug, ts, outcome, price, size, side).
4. **Dedup books** by (slug, outcome, timestamp_us) keep latest.

## Execution sequence (disk-aware; D: 54 GB free, C: tight)

1. ⏳ trentmkelly downloading → D:/polymarket_hf/hf_raw (~36 GB). [RUNNING]
2. ▶ bmoney1321 download (1.6 GB) → D:/bmoney_hf  [fits alongside]
3. Convert trentmkelly (L25 btc/eth + trades + settle-resolutions) → staging → merge canonical.
4. Convert bmoney (L25 sol/xrp full-depth + trades + REAL resolutions) → merge; **bmoney resolutions overwrite trentmkelly settle-derived by slug**.
5. **DELETE trentmkelly raw** (~36 GB freed).
6. aliplayer1 download (27 GB) → D:/aliplayer_hf.
7. Convert aliplayer (BBO 7 coins → orderbook_bbo + ticks → trades + markets.resolution → resolutions_hf).
8. Final cross-backfill + verify + (optional) ship compressed to VPS3 + collector.

## Slug compatibility
All three use `{coin}-updown-{5m|15m}-<epoch>` (our canonical convention) — direct join, no mapping. (aliplayer adds 1h/4h; bmoney/trentmkelly 5m/15m only.)
