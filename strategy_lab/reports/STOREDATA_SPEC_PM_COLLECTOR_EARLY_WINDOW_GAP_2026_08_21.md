# STOREDATA_SPEC — Polymarket collector misses the first ~51s of every 5m window — 2026-08-21

**For the storedata agent on VPS3 (`/opt/storedata`, service `storedata-collector.service`).**
Found during the ladder guard study
([LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md](LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md) §1):
the btc-updown-5m tape in `trades_v2` / `orderbook_snapshots_v2` systematically
starts ~1 minute AFTER each window opens. This blinds every offline study of the
5m entry window [0–60s] — exactly where the live ladder earns its edge — and it
is the reason the guard study had to fall back to data-api replay of real fills.

## 1. Symptom, measured (research-blocking)

First recorded in-window print per window, **5,007 btc-updown-5m windows,
Aug 7–21** (`trades_v2`):

| percentile | first in-window print |
|---|---|
| p5 | +10.0s |
| p25 | +30.7s |
| **p50** | **+50.8s** |
| p75 | +76.7s |
| p90 | +110.5s |
| p95 | +142.7s |

Only **4.9%** of windows have any print in the first 10s; 40% have nothing in
the whole first minute.

**Proof it is collector loss, not market quiet:** window
`btc-updown-5m-1787319900` (Aug 21 13:45 UTC). Our own live wallet
(`0x51a5…dd96`, data-api activity) has REAL maker fills in it at +3s…+67s —
those are public prints by definition — yet `trades_v2` for that slug starts at
**+110.5s** and `orderbook_snapshots_v2` for the same slug also starts at
13:46:50 UTC (= open+110s; 1,702 snapshot rows only from there). Same gap, same
discovery path. (`orderbook_deltas_v2` is 15m-scoped and unaffected by this
spec.)

Impact: any tape-only backtest of the 5m open is structurally censored; the
canonical-refresh pipeline inherits the gap.

## 2. Root-cause evidence (three mechanisms found in code + logs)

### 2a. Trade poll sweep time (`collectors/polymarket.py`, `_poll_trades_loop` ~line 421)
`trades_v2` is fed by a data-api **poll loop, not the WS**: "Poll trades from
data-api for all subscribed markets every 5s". The loop iterates
`self._subscribed_condition_ids` **sequentially, one HTTP request per
condition_id per cycle**. The subscribed set was **171 cids at 12:17 UTC and 327
at 15:03 UTC** (grows intra-day; resolved 5m markets do not appear to be pruned
fast). At 327 sequential requests × ~150–300ms latency the real sweep period is
**~50–100s, not 5s** — which reproduces the observed p50 +51s / p90 +110s almost
exactly. This is the primary suspect for the `trades_v2` gap.

### 2b. New-market subscribe cadence (same loop, `rediscover_interval = 60.0`)
`_discover_via_events` re-runs only every 60s, and WS subscriptions for new
tokens are sent only then. A 5m market that becomes discoverable near its open
waits 0–60s more. Note: discovery CAN see markets far ahead — the log shows
`crypto_market_detected` for "August 22, 10:55AM-11:00AM ET" (~20h early) — so
early subscription is possible; the cadence and the sweep, not gamma, are the
bottleneck. Also `market_discovery.py` default `polymarket_refresh_interval=600`
(10 min) for the other discovery path — check which paths matter for 5m.

### 2c. WS connection churn (slow consumer) — affects `orderbook_snapshots_v2`
Today's journal (retention starts 14:17 UTC, older history not visible):
**77 `collector_reconnect` events in ~3h**, at times one every ~90s. Reasons:
`no close frame received` ×37, **`1013 slow consumer: send buffer full` ×30**,
`keepalive ping timeout` ×9. On 1013 the code backs off **30s**; on every
reconnect `_subscribed_asset_ids.clear()` — subscriptions restart from a fresh
discovery. Between drop → backoff → reconnect → rediscover → resubscribe →
snapshot, minutes of book data are lost, and the highest-pressure moment (a new
window opening, snapshot burst) is exactly when the send buffer is most likely
full. The keepalive/no-close-frame errors suggest the asyncio reader is being
stalled (likely by DB flushes on the same loop — `delta_buffer_flushed_v2` up to
~2k rows between messages).

## 3. Requested fixes (owner decides implementation; instrument FIRST)

1. **Instrument before changing anything** (so the fix is measurable):
   - per window: `first_trade_lag_s` (first `trades_v2` print ts − slot_start),
   - trade-poll **sweep duration** per cycle + subscribed-set size,
   - per-WS-connection uptime + reconnect reason counter.
2. **Trades poll (2a):** bound the sweep to ≤3s. Options: parallelize with
   bounded concurrency (8–16 in-flight); AND/OR prune the polled set — a 5m
   market only needs polling from T−2min to T+7min (settlement), and resolved
   cids should leave the set immediately. 327 sequential calls for ~60 active
   slugs is mostly dead weight.
3. **Pre-subscribe 5m markets before open (2b):** the 5m slug schedule is
   deterministic (`btc-updown-5m-<slot_start_epoch>`, every 300s). Resolve the
   NEXT window's market via gamma by slug ~2min before open and subscribe its
   tokens + add its cid to the poll set at T−60s at the latest. This is the same
   class of fix as the Kalshi `status=unopened` pre-subscribe. Alternatively
   drop `rediscover_interval` to ≤15s — but the deterministic schedule is
   cheaper and exact.
4. **WS health (2c):**
   - decouple the WS reader from DB writes: reader only does
     `bounded_queue.put_nowait()` (overflow = drop + counter, never block);
     flushes happen on a separate task/thread. This addresses the 1013s and the
     keepalive timeouts at the source.
   - on 1013, reconnect immediately with small jitter (0.5–2s), escalating only
     on repeated failure — a fixed 30s backoff guarantees a gap every cycle.
   - consider splitting the heavy delta subscription (15m books, ~145 msg/s)
     onto its own connection so a kick there cannot blind the 5m tape.
   - verify resubscribe-on-reconnect sends the full active set in one batch
     (it appears to, via initial discovery — confirm with a forced reconnect).
5. Cosmetic: the WS text frame `"NO NEW ASSETS"` is logged as
   `invalid_json` warning every rediscover — handle it explicitly.

## 4. Acceptance criteria (pre-registered, 24h after deploy)

Run over one full day of btc-updown-5m windows (≈288):

```sql
WITH firsts AS (
  SELECT r.slug,
         MIN(t.timestamp_us) FILTER (WHERE t.timestamp_us >= r.slot_start_us) AS first_us,
         r.slot_start_us
  FROM market_resolutions_v2 r
  LEFT JOIN trades_v2 t ON t.slug = r.slug
  WHERE r.slug LIKE 'btc-updown-5m-%'
    AND r.slot_start_us >= <deploy_epoch_us>
  GROUP BY r.slug, r.slot_start_us
)
SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY (first_us-slot_start_us)/1e6)  AS p50_s,
       percentile_cont(0.9) WITHIN GROUP (ORDER BY (first_us-slot_start_us)/1e6)  AS p90_s,
       avg(((first_us-slot_start_us)/1e6 <= 10)::int)                             AS frac_le_10s
FROM firsts;
```

- **P1: p50 ≤ 3s and p90 ≤ 10s** (was 51s / 110s). Baseline for "≤10s is
  achievable": the pros trade in the first seconds of essentially every window
  (our own engine fills at +3s; PBot fleet fires around open in every window).
- **P2: `orderbook_snapshots_v2` first snapshot per slug ≤ T−30s** for ≥95% of
  windows (pre-subscribed books, not post-open).
- **P3: WS reconnects < 24/day and zero `1013 slow consumer` in steady state.**
- P4 (no regression): `orderbook_deltas_v2` 15m row rate unchanged ±10%;
  `trades_v2` daily row count for 15m slugs unchanged ±10%.

## 5. Context for prioritization

The live ladder campaign is now judged via same-window forensics that need this
tape; the next planned studies (guard verification at n≥100 windows, the
pre-registered volatility throttle, 15m expansion) all read the 5m/15m open from
these tables. Until fixed, every such study must fall back to data-api replay,
which only covers OUR fills — competitor/microstructure context of the first
minute stays invisible.

Study scripts that will re-verify after the fix:
`strategy_lab/ladder_sim_2026_08_21/` (first-print-lag measurement is the
inline python in the study; the SQL above is equivalent).
