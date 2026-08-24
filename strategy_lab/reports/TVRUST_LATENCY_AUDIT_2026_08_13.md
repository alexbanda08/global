# Latency + order-path audit, Ireland — measured vs docs — 2026-08-13

Live measurements taken today from the box (`85.137.174.152`) + `tradingvenue_rust` DB,
compared against `docs/RUST_VS_PYTHON_ORDER_PATH.md`, `docs/MOAT-INFRA-PLAN.md` (I0–I6)
and the deployed code. Plus the b945 pre-open question, answered.

---

## 1. The measured latency map (all numbers from today)

### Network, Ireland → Polymarket (10 samples/host, medians)

| hop | clob | ws-subs | gamma | data-api |
|---|---:|---:|---:|---:|
| DNS | 1.1ms | 1.1ms | 1.1ms | 1.2ms |
| TCP connect | **0.7ms** | 0.9ms | 0.8ms | 0.8ms |
| TLS handshake | 38.3ms | 37.3ms | 35.7ms | 39.5ms |
| TTFB (cold) | 22.2ms | 22.9ms | 25.6ms | 12.8ms |
| total cold | 65.6ms | 69.8ms | 64.2ms | 61.0ms |

**Warm keep-alive GET `clob/…/time`: median 18.5ms, min 16.6ms.** That is the network
floor for any venue call from this box. TCP 0.7ms confirms we terminate at an edge next
door; the ~18ms warm TTFB is edge→origin. The box's placement is already near-optimal —
no infrastructure move buys anything meaningful.

### The engine, as recorded in `trading.events`

| stage | measure | value |
|---|---|---:|
| order submit (`ladder_order_placed.submit_ms`, n=612) | p50 | **38ms** |
| | p90 / p99 / max | 86ms / **481ms** / 1,404ms |
| WS recv→book-apply (`tick_latency`, n=243k/24h) | p50 / p95 | **20µs / 47µs** |
| book age at tick (active windows) | p50 | 98ms |
| internal worst | max recv→apply | 164ms (GC-free; rare) |

Read: **internal processing is 3 orders of magnitude below the network** — the Rust port
did its job. The whole latency story now lives in two places: the submit tail and the feed.

---

## 2. Measured vs the documents

| doc claim | measured today | verdict |
|---|---|---|
| `ORDER_PATH`: HTTP POST ~50–300ms, "network-bound, identical Py/Rust" | p50 38ms, warm floor 18.5ms | **better than doc**; budget stands |
| `ORDER_PATH`: "money is lost in the P99, not the median" | p99 = 481ms = **13× median** | doc was right; tail unaddressed |
| `ORDER_PATH`: EIP-712 sign ~50–200µs (k256) | inside the 38ms envelope | ok, not the bottleneck |
| MOAT I2 racer, `N_CONNS` (env=4) | `feed_quality`: **4 conns on the base-feed mirrors (243k events), 1 conn on the 1.13M per-window tracker events** | racer IS live where it matters; the `n_conns=1` events are the per-window token trackers, not a regression |
| MOAT I3 latency tape | on (`TV_LATENCY_TAPE_ENABLED`), feeding `tick_latency` | ✅ |
| MOAT **I5: pre-signed order grid** | **NOT BUILT** ("live only, Stage-1+") | ← the open item that matters |
| MOAT I6: CPU pinning | deferred "until the latency tape exists" — tape exists since Jun | unblocked, but low priority: recv→apply is already 20µs |
| I1 tick recorder | **`TV_POLY_TICK_RECORD_ENABLED=false` — OFF AGAIN** (was on Aug 5, 567MB collected; handoff of Aug 13 lists "recorder" as done) | 🔴 regression — flipped off somewhere between Aug 5 and today |
| cancel path | `DELETE /orders` batch = 1 RTT for all ids; `cancel_all` separate | matches spec; fine |
| order submit HTTP client | one shared `reqwest::Client` (pool default), `timeout 8s`; clob-sdk `ClobClient` shares it | connection reuse exists, but no `pool_idle_timeout`/keepalive tuning, no pre-warm |

## 3. Where the milliseconds actually are — ranked

1. **The submit tail (p99 481ms, max 1.4s).** Causes consistent with the evidence: idle
   pool connections timing out → the p99 pays a fresh TLS (65ms+) or worse, plus venue-side
   queueing. Fixes, cheap→deep:
   a. `reqwest` builder: `pool_idle_timeout(None)` + `tcp_keepalive(15s)` + `http2_keep_alive_interval` — keep the venue connection permanently warm.
   b. A 10s heartbeat GET `/time` on the same client (pre-warms TLS + keeps the CDN edge route hot). ~free.
   c. **I5 pre-signed grid** — sign the plausible price ladder at window-create time, so the fire path is body-POST only. This was always the plan (MOAT); nothing blocks it but build time.
2. **Requote round-trip is 2 RTTs** (cancel then place, ~40ms+40ms). Polymarket has no
   atomic replace; mitigation is the deadband we already run (`v4_slowq` tests 45s) and
   quoting fewer levels better. Not fixable below ~80ms without venue support.
3. **Feed:** racer already merges 4 conns; book p50 age 98ms. The remaining gain is not
   more conns — it's the **delta stream** (price_change events) which the recorder was
   supposed to be taping for the queue model. Blocked on the recorder being ON.
4. **NOT worth it:** moving the box (TCP is 0.7ms), CPU pinning (20µs path), faster
   signing (µs), more racer conns (shared egress IP rate-limit risk per MOAT ops note).

Bottom line vs the b945 problem: **latency is not why we lose.** We submit in 38ms into
books that rest for 30+ minutes. The pair:residual ratio is a placement/queue problem, not
a speed problem — which the next section makes concrete.

---

## 4. b945: does it place BEFORE the window opens? — YES (and so does everyone)

Two independent measurements today:

**(a) The venue builds full books long before open.** Live probe of future windows:

| window | opens in | resting book (UP token) |
|---|---:|---|
| btc-5m `+176s` | 3 min | 50 bid lvls, **155,649 sh**, best 0.50/0.51 |
| btc-5m `+1676s` | 28 min | 50 lvls, 140,796 sh |
| btc-15m `+2276s` | 38 min | 39 lvls, 145,806 sh |
| btc-15m `+4976s` | **83 min** | 39 lvls, 145,101 sh |

Markets exist and carry ~145k resting shares **more than an hour pre-open** (15m windows
tradeable ~24h early per the June forensics). Queue position is FIFO from placement time.

**(b) b945's fills say it sits at the FRONT of those queues at open.** In 123k fresh
fills: **zero pre-open fills** (nobody crosses pre-open — the book just accumulates), but
per-window first-fill offsets:

| | 5m (n=1,827) | 15m (n=1,063) |
|---|---:|---:|
| min / p10 / p25 | 3s / 6s / 27s | 4s / **6s / 6s** |
| median | 102s | **11s** |

On 15m, a quarter of all windows fill b945 within **6 seconds of open** against queues
holding 145k pre-resting shares. You cannot be filled 6s after open from the back of a
90-minute-old FIFO queue — **it places early and owns the front.** This is the
queue-priority moat the June decode named; our `placement_offset_s = −3600` copies it
correctly (note: 5m markets appear to be created ~30–40min pre-open, so −3600 effectively
means "at market creation" there — which is the right behavior anyway).

**Implication:** the placement lever is EARLINESS at market creation, not submit speed.
An order placed 30–80 minutes early makes 40ms-vs-100ms submit latency irrelevant for the
maker legs. Submit speed only matters for (i) requotes near the money and (ii) the
taker-completion leg (v5_tc spec) — which is exactly where the p99 tail fix and I5 pay.

---

## 5. Action list (ranked, with owners)

1. 🔴 **Turn the tick recorder back on and find out who/what turned it off** (env now
   `false`, was `true` Aug 5 with 567MB taped; the queue-model calibration and the delta
   tape both depend on it). Check whether an env-restore script or the Aug-12 `mrcut`
   deploy reverted it. *(ops, 1 min + investigation)*
2. **Warm-path fix for the submit tail**: pool_idle_timeout(None) + tcp_keepalive +
   10s `/time` heartbeat. Success metric, pre-registered: submit p99 < 120ms over 48h
   (from 481ms). *(engineering, small)*
3. **I5 pre-signed grid** at window-create (sign ladder rungs upfront, POST-only on fire)
   — benefits requotes and the v5_tc IOC leg. *(engineering, M — already spec'd in MOAT)*
4. **Keep placement at market creation** (verify the engine's `-3600` actually lands
   orders the moment gamma creates the market for 5m — log `placement_lag_s = place_time −
   market_create_time` as a new metric). *(small)*
5. **Don't do:** box move, CPU pin, more racer conns, faster signing — all measured
   below the noise floor of what's broken.
