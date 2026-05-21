# Handoff to storedata agent — VPS3 data drift from VPS2

**Date:** 2026-05-16 ~08:00 UTC
**Author:** strategy-lab agent (alexandre.bandarra)
**Audience:** storedata agent owning VPS2 + VPS3 storedata DBs
**Severity:** Medium — VPS2 collector for `hyperliquid_liquidations_v2` has stalled (3 days lag); other tables have small drift (probably packet loss differences, not a code bug)

---

## TL;DR

Audited every table on both VPS at 2026-05-16 07:30 UTC. **Both hosts independently collect overlapping data** with row counts that should match on overlap windows. Most tables are in sync. Three categories of issues:

1. 🔴 **VPS2 `hyperliquid_liquidations_v2` collector is STALLED at 2026-05-13 01:59** — 3 days behind. Investigate & restart on VPS2.
2. 🟡 **Row-count drift** on `trades_v2`, `oracle_prices_v2`, `hyperliquid_trades_v2`, `hyperliquid_metrics_v2`: VPS2 has +N rows over VPS3 in overlap windows. Likely packet-loss difference, not a structural gap. Investigate if reproducible.
3. 🟢 **VPS3 has 5× more `binance_klines_v2` than VPS2** — because VPS3 hosts binance-spot-ws (1SEC) and binance-vision archive that VPS2 doesn't. This is BY DESIGN; not a defect. VPS2 should NOT try to mirror these.

**Strategy lab side:** local now has 100% verified L25 orderbook coverage Apr 18 → May 16 and all derived datasets. The VPS2-unique Apr 18-22 orderbook history was saved locally before VPS2's retention pruned it. No further VPS3-side fixes are required to unblock strategy-lab work — this handoff is for hygiene + future reliability.

---

## 1. Stalled collector: `hyperliquid_liquidations_v2` on VPS2

### Evidence

```sql
-- VPS2: ssh root@[2605:a140:2323:6975::1]
SELECT MIN(time_exchange_us)/1e6 AS earliest, MAX(time_exchange_us)/1e6 AS latest,
       COUNT(*) AS rows
  FROM hyperliquid_liquidations_v2;

-- result (2026-05-16 07:30 UTC):
-- earliest = 2025-05-25 14:36:58
-- latest   = 2026-05-13 01:59:26  ← STALLED 3 days
-- rows     = 5,165,998
```

vs.

```sql
-- VPS3: ssh root@185.190.143.7
-- latest   = 2026-05-16 09:50:20  ← CURRENT
-- rows     = 5,228,386            ← +62,388 newer rows
```

### What to investigate
- VPS2 has a HL liquidations collector service. Check `systemctl status` for whatever process feeds `hyperliquid_liquidations_v2` on VPS2.
- VPS2's `collector_status` table might have a stuck entry: `SELECT * FROM collector_status WHERE service LIKE '%liquidation%' ORDER BY updated_at DESC LIMIT 5`.
- Likely a websocket disconnect, hl-s3-fills ingestion job, or block-stream watcher that died silently.
- VPS3's collector is fine and has been adding ~2,500-5,000 rows/day for May 13-16.

### Why it matters
- Liquidation-cascade triggers for strategy-lab. We pulled the full series from VPS3 (5,228,386 rows back to 2025-05-25) so strategy work isn't blocked. But future pulls from VPS2 will return stale data.
- Once VPS2 collector is restarted + backfills, both VPS should converge.

### Suggested action
1. Identify the dead service on VPS2, restart it.
2. Have it backfill May 13-16 from S3 (hl-s3-fills source) or from its bookmark.
3. Verify `latest` advances to within ~5 minutes of wall clock.

---

## 2. Small row-count drift in overlap-window tables

For tables both VPSes collect from the same upstream (polymarket websocket + chainlink oracle), the counts should be byte-equal on overlap days. Today's reading shows VPS2 has consistently slightly more rows. Likely cause: VPS3's network or collector dropped some packets that VPS2 caught (different network path, different buffer settings).

| table | VPS2 rows | VPS3 rows | delta | earliest both | latest both |
|---|---:|---:|---:|---|---|
| `trades_v2` | 38,168,703 | 36,680,335 | **+1,488,368** (~3.9%) | 2026-04-22 14:08:05.785 | 2026-05-16 09:51:35 |
| `oracle_prices_v2` | 5,474,801 | 5,432,546 | **+42,255** (~0.78%) | 2026-04-24 03:38:28 | 2026-05-16 09:51 |
| `hyperliquid_trades_v2` | 13,713,114 | 13,641,666 | **+71,448** (~0.5%) | 2026-04-30 20:54:02 | 2026-05-16 09:51 |
| `hyperliquid_metrics_v2` | 88,808 | 88,576 | **+232** (~0.26%) | 2026-04-30 20:58:15 | 2026-05-16 09:51 |
| `orderbook_snapshots_v2` | 59,874,348 | 60,664,173 | **-789,825** (VPS3 has more) | 2026-04-22 16:47:30 | 2026-05-16 09:51 |

The trades_v2 +1.49M gap is large enough to be worth investigating. It might indicate VPS3's polymarket websocket client is dropping trades — or that VPS2 catches duplicate captures that should be deduped.

### Diagnostic to run
```sql
-- On each VPS:
SELECT DATE_TRUNC('hour', TO_TIMESTAMP(timestamp_us/1e6)) AS hour,
       COUNT(*) AS n
  FROM trades_v2
 WHERE timestamp_us > (EXTRACT(EPOCH FROM NOW() - INTERVAL '2 days') * 1e6)::bigint
 GROUP BY 1
 ORDER BY 1;
```
Compare hour-by-hour. Hours where VPS2 has much more than VPS3 → VPS3 dropped packets in that window.

If VPS2 has consistently +5-10% per hour, the gap is a steady network/buffer issue → tune VPS3's polymarket-clob-trades collector buffer size. If gap is bursty → investigate specific outages.

### Suggested action
- 30 minutes of investigation. Not blocking but should be tracked.
- Alternative: accept that VPS2 is the primary for trades_v2 and oracle_prices_v2; mirror VPS3's collector to use VPS2's pacing/buffer config.

---

## 3. VPS2 doesn't mirror VPS3's binance feed (BY DESIGN)

VPS3 hosts the tradingvenue engine + live binance feed + binance-vision archive ingestion. VPS2 only has a subset.

| binance_klines_v2 breakdown | VPS2 | VPS3 | notes |
|---|---:|---:|---|
| total rows | 2,344,475 | 12,280,808 | **VPS3 has 5×** |
| binance-spot-ws 1MIN | only Apr 14-29 (56k) | full Apr 14 → May 16 (129k) | VPS2 collector stopped earlier |
| binance-spot-ws 5MIN | absent | 15k | **VPS3 only** |
| binance-spot-ws 15MIN | absent | 5k | **VPS3 only** |
| binance-spot-ws 1SEC | absent | 2.17M | **VPS3 only** — production needs this |
| binance-vision 1SEC | absent | 7.78M | **VPS3 only** — archive |
| binance-vision 1MIN/5MIN/15MIN/1HRS/4HRS/1DAY | full archive | full archive | both have it |
| coinbase-spot-ws 1MIN | full | full | both have it |
| kraken-spot-ws 1MIN | full | full | both have it |
| **okx-ws 1MIN/5MIN/15MIN** | full (~99k) | **absent** | **VPS2 ONLY** |

### Suggested action
- **VPS2 binance-spot-ws 1MIN collector stopped on 2026-04-29** — not fatal since VPS3 has it, but VPS2's row is technically stale. Investigate why it stopped on Apr 29 and decide if VPS2 should keep running it (redundancy) or be allowed to age.
- **VPS3 has no OKX kline collector**. If OKX coverage is needed on VPS3, either (a) add an `okx-ws` collector on VPS3, or (b) periodically sync from VPS2.
- VPS3's 1SEC + vision-1SEC ingest is unique to VPS3's box — no need to mirror to VPS2; we just want to make sure VPS3 keeps collecting reliably.

---

## 4. Datasets only one VPS has (currently equal)

| table | start | both VPS row count | source |
|---|---|---:|---|
| `hyperliquid_klines_v2` | 2026-01-30 | 181,287 (VPS3) / 181,579 (VPS2) | mostly synced |
| `cryptocap_dominance_v2` | 2014-04-01 | 40,411 (both) | external sync |
| `binance_metrics_v2` | 2025-04-27 | 315,351 (both) | external sync |
| `hyperliquid_funding_v2` | 2026-01-30 | 10,176 (both) | external sync |
| `markets`, `market_resolutions_v2` | 2026-04-22 | 27,265 (both) | mirrored |

No action needed for these — both VPSes have identical/near-identical state.

---

## 5. Local strategy-lab state (FYI)

For context, local now has the FULL ecosystem:
- L25 orderbook Apr 18 → May 16 (verified 100% vs both VPS in overlap)
- Polymarket trades + oracle + chainlink RTDS + resolutions through May 16
- HL trades (30d), HL liquidations (FULL 1-year), HL klines, HL funding, HL metrics
- Binance 1MIN/1SEC + vision archive + coinbase/kraken/OKX klines
- CryptoCap dominance (12-year history)
- Binance perp metrics (1 year)
- 30d trading.events from production engine

So storedata-side issues here don't block backtesting. This handoff is purely for sysop hygiene.

---

## 6. How to verify after fixes

```bash
# From a local machine with both VPS keys:
SQL="
SELECT 'orderbook_snapshots_v2' t, COUNT(*) n, TO_TIMESTAMP(MIN(timestamp_us)/1e6)::timestamp mn, TO_TIMESTAMP(MAX(timestamp_us)/1e6)::timestamp mx FROM orderbook_snapshots_v2 UNION ALL
SELECT 'trades_v2', COUNT(*), TO_TIMESTAMP(MIN(timestamp_us)/1e6)::timestamp, TO_TIMESTAMP(MAX(timestamp_us)/1e6)::timestamp FROM trades_v2 UNION ALL
SELECT 'oracle_prices_v2', COUNT(*), TO_TIMESTAMP(MIN(timestamp_us)/1e6)::timestamp, TO_TIMESTAMP(MAX(timestamp_us)/1e6)::timestamp FROM oracle_prices_v2 UNION ALL
SELECT 'hyperliquid_liquidations_v2', COUNT(*), TO_TIMESTAMP(MIN(time_exchange_us)/1e6)::timestamp, TO_TIMESTAMP(MAX(time_exchange_us)/1e6)::timestamp FROM hyperliquid_liquidations_v2 UNION ALL
SELECT 'hyperliquid_trades_v2', COUNT(*), TO_TIMESTAMP(MIN(time_exchange_us)/1e6)::timestamp, TO_TIMESTAMP(MAX(time_exchange_us)/1e6)::timestamp FROM hyperliquid_trades_v2 ORDER BY 1
"
ssh -i ~/.ssh/vps2_ed25519 'root@[2605:a140:2323:6975::1]' "sudo -u postgres psql -d storedata -A -F'|' -t -c \"$SQL\""
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 "sudo -u postgres psql -d storedata -A -F'|' -t -c \"$SQL\""
```

Expected after fix:
- VPS2 `hyperliquid_liquidations_v2.max_ts` advances to within ~5 min of `now()`.
- Other tables' row-count drift either confirmed as packet loss (gap stays steady) or fixed (gap closes).

---

## 7. Out of scope for this handoff

- L25 orderbook retention: VPS3 dropped Apr 18-22 today (was kept on VPS2 longer). Either retention policies are different by chance or VPS2's just hasn't kicked in yet. Not blocking; we have local snapshots.
- The `binance-spot-ws 1MIN` stoppage on VPS2 at Apr 29 — could be investigated separately. Or accepted as VPS3-only feed going forward.

---

*Generated 2026-05-16 ~08:00 UTC. Strategy lab side has full local data; this is a sysop hygiene ticket for storedata agent.*
