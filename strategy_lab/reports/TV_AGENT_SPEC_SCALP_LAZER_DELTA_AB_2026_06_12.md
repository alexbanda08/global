# TV AGENT SPEC — Pyth Lazer feed + `scalp lazer-δ vs rtds-δ` A/B shadow sleeves

_2026-06-12. Motivation: measured head-to-head (`CHAINLINK_FEED_RESEARCH_2026_06_12.md`, rounds 2-3):
Pyth Lazer tracks the Chainlink settlement value within ≤1.3bp and shows it **~1.3–1.8s before RTDS
prints**, at 50ms cadence vs RTDS 1Hz. Hypothesis: a sharper/earlier δ measurement improves the
deployed exit-scalp entry. SHADOW ONLY ($0). Reference impl: `pyth_lazer/probe_lazer.py` +
`pyth_lazer/COLLECTOR_SPEC.md` (storedata collector already running off the same product)._

---

## PART 1 — Lazer feed in the engine (`LazerPriceMirror`)

Same architectural slot as the WS BookMirror: a process-local, always-on price mirror.

**Endpoints (connect to ALL THREE, dedup by `timestampUs`):**
```
wss://pyth-lazer-0.dourolabs.app/v1/stream
wss://pyth-lazer-1.dourolabs.app/v1/stream
wss://pyth-lazer-2.dourolabs.app/v1/stream
```
**Auth — HTTP header on the WS upgrade (server path):**
```
Authorization: Bearer $PYTH_LAZER_TOKEN
```
(401 = bad token, 403 = no permission. This free key is VERIFIED working on `real_time` 2026-06-12.)

**Subscribe (once per socket):**
```json
{"type":"subscribe","subscriptionId":1,
 "priceFeedIds":[1,2,6],
 "properties":["price","exponent","feedUpdateTimestamp"],
 "formats":[],"channel":"real_time","deliveryFormat":"json","parsed":true,
 "ignoreInvalidFeedIds":true}
```
**Feed IDs (u32):** BTC=1, ETH=2, SOL=6 — VERIFIED. XRP/BNB/DOGE ids NOT yet verified — discover via
the Lazer symbols endpoint per SDK docs and extend in a later phase; v1 = BTC/ETH/SOL only.

**Parse:** messages `type=="streamUpdated"` → `parsed.timestampUs` (event time) +
`parsed.priceFeeds[]` with `priceFeedId`, `price` (STRING i64), `exponent` (-8).
`real_price = int(price) * 10**-8`. Keep per-symbol: `(last_px, last_ts_us, recv_ts_us)`.

**Health rules:**
- `lazer_age_ms = now − recv_ts` per symbol. STALE if > 2,000ms.
- Reconnect w/ backoff per socket; sockets are independent (HA).
- Emit `lazer.health` event on stale/recover transitions (for the dashboard).
- NEVER use Lazer for settlement/resolution anywhere — signal only (Pyth ≠ Chainlink).

## PART 2 — A/B/L sleeves (shadow, $0, BTC/ETH/SOL × 5m+15m)

Three sleeves per (coin, tf) — IDENTICAL config except the δ source/timing:

| sleeve | δ source | entry eval at | purpose |
|---|---|---|---|
| `shadow_scalp_rtdsd_<coin>_<tf>` (CONTROL) | RTDS px (current production path) | slot_start +5s | baseline twin |
| `shadow_scalp_lazerd_<coin>_<tf>` (ARM L1) | **Lazer px** | slot_start +5s | pure measurement-precision test |
| `shadow_scalp_lazere_<coin>_<tf>` (ARM L2) | **Lazer px** | **slot_start +3s** | latency-capture test |

**Shared config (copy the LIVE production scalp exactly):**
- δ = (px − strike) in the production unit/threshold convention.
- **STRIKE BASIS — AMENDED 2026-06-12 (supersedes the earlier "same strike in all arms" answer):**
  live measurement found a persistent lazer↔binance basis ≈ **+6bp** — i.e. **binance px runs
  ≈ +6bp ABOVE Lazer px** (equivalently `lazer − binance ≈ −6bp`). Consistent with our bench:
  binance sits 5.6–6.3bp off the oracle value; Lazer ≤1.3bp. With a 3bp δ-threshold a mixed-source
  δ (lazer px − binance strike) carries a structural bias ≈ 2× the threshold → broken.
  **Rule: each arm's δ must be SAME-SOURCE on both legs.** CONTROL: binance px − binance strike
  (production, unchanged). L1/L2: **lazer px − lazer strike**, where lazer strike = Lazer price
  at slot_start (read from the mirror ring — the scalp strike is only +5s/+3s pre-fire, so it's
  always in-ring; no separate latch / long buffer needed). Same-source δ cancels venue basis within
  every arm; bonus — Lazer-δ is then the closest measurable proxy of the TRUE oracle δ that decides
  the outcome.
- **IMPLEMENTED + LIVE-VERIFIED 2026-06-12 (VPS3 shadow; repo `edea923db`):** built pure-lazer
  same-source δ as specified. Live confirmation of the basis fix — over a post-deploy run the
  per-fire `binance_δ − lazer_δ` mean collapsed **+6.0bp → +0.3bp** (sd ~3.1bp = the genuine
  sharpness/lead residual, no longer a constant venue offset); lazer_δ ≈ binance_δ; skip-stale 0%
  steady-state. All 3 arms firing BTC/ETH/SOL × 5m/15m.
- Gates: `|δ| ≥ 3` @ $5 stake; `entry_vwap < 0.55`; spread ≤ 0.05; direction = sign(δ).
- Exit: **pure +60s time sell. TP OFF, STOP OFF, taker exit** (final 2026-06-11 config).
- Books/fills: WS BookMirror, same as live.
- **No silent fallback:** if Lazer is STALE at eval time, the lazer sleeves SKIP that window and log
  `lazer.skipped_stale` (falling back to RTDS would contaminate the A/B). Control always evaluates.

**Events:** standard sleeve events + per-fire tags: `delta_source`, `delta_value`, `lazer_age_ms`,
`rtds_age_ms`, and (lazer arms) `delta_rtds_at_fire` (the control's δ at the same instant — lets us
quantify disagreement per fire offline).

## PART 3 — Evaluation (pre-registered)

1. Accrue **n ≥ 200 fires per arm** (BTC/ETH/SOL pooled).
2. Metric: TV dashboard **dedup** PnL (never raw `events.pnl_usd`).
3. Primary test: **paired per-slug diff** L1 − CONTROL on slugs where BOTH fired
   (isolates measurement quality). Secondary: L2 − CONTROL (latency capture); also compare
   fire-rate and skip-stale rate (uptime tax of the free key).
4. Promotion rule: L-arm replaces RTDS-δ in live only if paired diff CI95 > 0, OR diff ≈ 0 with
   materially better fill quality (entry_vwap distribution shifted down) AND skip-stale < 2%.
5. Kill rule: skip-stale > 10% (free key unreliable) or paired diff CI95 < 0 → keep RTDS, retire arms.

## Notes for the implementer
- ~20 msg/s per symbol on `real_time`; parse cost trivial. If bandwidth matters, `fixed_rate@200ms`
  is also free and still 5× RTDS — but v1 should use `real_time` (what we benchmarked).
- The benchmark artifacts (`strategy_lab/directional/_results/feed_bench_1781281434.parquet`) hold
  20 min of synced rtds/lazer/binance ticks if you want to sanity-check your parser's prices.
- Do NOT touch the live sleeves; this is additive shadow only, one restart, both-host parity not
  required (VPS3 shadow fleet only).
