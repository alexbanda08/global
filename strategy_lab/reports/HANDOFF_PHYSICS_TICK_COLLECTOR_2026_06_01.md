# Handoff — Physics-tick collector (compute + store BTC physics second-by-second)

**Goal:** stand up a live collector on VPS3 that computes the "physics of BTC" snapshot
every second and writes it to storedata, so we keep accumulating the data needed to
finish validating the candidate pocket (the physics work is implemented but currently
*priced-in / not yet significant* — see `PHYSICS_SIGNAL_SYNTHESIS_2026_06_01.md`).

**Source of truth for the math:** `strategy_lab/physics/physics_signal.py` (`physics_at`).
The collector MUST produce identical numbers to that function or live ≠ backtest. Port the
formulas below verbatim (Python now; the Rust port goes in `TVRUST/crates/tv-core` next to
the existing `OracleLagSnapshot` in `oracle.rs`).

---

## 1. What to compute every tick
All prices in USD, all timestamps **UTC microseconds** (`*_us`). Per asset (BTC, then ETH/SOL).

Inputs at tick time `t_us`:
- `now`  = price **asof** `t_us` (last sample at-or-before t — causal, never future).
- `prev` = price asof `t_us − 60_000_000` (60 s earlier).
- `prev30` = price asof `t_us − 30_000_000` (for the speed derivative).
- `strike` = the active up-down slot's reference = **chainlink price at that slot's `slot_start`** (read once when the slot opens; the slug suffix = `slot_start` in seconds).
- `slot_end_us` = slot_start_us + window (5m=300s, 15m=900s).

Formulas (exact, from `physics_signal.physics_at`):
```
dist          = now - strike                      # signed $, + above strike
side          = +1 if dist >= 0 else -1           # +1 => "Up/above" favored
bet           = "Up" if side > 0 else "Down"      # continuation = side you're on
speed         = (now - prev) / (60/60)            # $/min over trailing 60s, signed (+=rising)
                # general: speed = (now - price_asof(t-W)) / (W/60),  W=60s here
speed_abs     = abs(speed)
speed_away    = speed * side                       # >0 => moving AWAY from strike (inertia confirms)
speed_toward  = -speed_away
cross         = abs(dist)/speed_toward if speed_toward > 1e-9 else 999.0   # min to roll back to strike
cross         = min(cross, 999.0)                  # CROSS_CAP = "won't return at this speed"
have_m        = (slot_end_us - t_us) / 60_000_000  # minutes left in slot
margin        = cross - have_m                     # >0 => can't get back before close
# speed derivative (the article's open hypothesis — we CONFIRMED it helps):
speed_prev30  = (price_asof(t-30s) - price_asof(t-90s)) / 1.0   # $/min, the speed 30s ago
d_speed       = speed - speed_prev30               # <0 => inertia fading (worse for continuation)
# optional, ties to the oracle-lag work:
cl_basis_bps  = (binance_now - chainlink_now)/chainlink_now * 1e4
```

**Two feed bases — log BOTH** (do not pick one):
- **chainlink** (`oracle_prices_v2`, source `polymarket-rtds-chainlink`, ~1 Hz): outcome-consistent — this is what settles the market, so it's the basis our validated backtest used.
- **binance 1s spot** (`binance_klines_v2`, period `1SEC`, source `binance-spot-ws`): the article's "BTC", smoother + leads chainlink → the freshest live signal.

Compute the full block on **chainlink** (primary) and store `binance` price/speed/d_speed alongside so we can A/B which basis predicts better with more data.

---

## 2. The feeds already exist on VPS3 — no new ingestion needed
storedata already has the raw inputs (verified 2026-06-01, both live <2 min stale):
- `oracle_prices_v2` (timestamp_us, symbol_id ∈ CHAINLINK_{BTC,ETH,SOL}_USD, price_value) — chainlink RTDS, ~1 Hz.
- `binance_klines_v2` WHERE source='binance-spot-ws' AND period_id='1SEC' (time_period_start_us, price_close, symbol_id ∈ BINANCE_SPOT_{BTC,ETH,SOL}_USDT).
- strike/slot timing: derive from the live slug (suffix = slot_start_s) + read chainlink @ slot_start, or from `market_resolutions_v2.strike_price` after the fact.

So the collector is a **compute-and-write loop over feeds we already have**, not a new market data ingest. Best implementation: hook the engine's in-memory price mirrors (it already holds binance-1s + chainlink-RTDS and computes `OracleLagSnapshot` in `oracle_lag.py`) and extend that to emit the full physics tick — avoids a DB round-trip on the hot path.

---

## 3. Storage — two tables (follow existing collector conventions)

### `physics_ticks_v2` — asset-level, market-independent (the durable raw stream)
Write 1 row/sec/asset (3 assets → ~259k rows/day, trivial; make it a TimescaleDB hypertable on `timestamp_us`).
```
timestamp_us      bigint   -- tick time, UTC us
asset             text     -- BTC / ETH / SOL
binance_price     numeric
chainlink_price   numeric
speed_bn_60s      numeric  -- $/min, signed, binance
speed_cl_60s      numeric  -- $/min, signed, chainlink
d_speed_bn_30s    numeric
d_speed_cl_30s    numeric
cl_basis_bps      numeric
source            text     -- e.g. 'tv-physics-v1'
```

### `physics_market_ctx_v2` — per active up-down slot (needed for live trading + parity)
Write 1 row/sec per ACTIVE slot (BTC 5m + 15m, then ETH/SOL). ~ a handful of active slots/asset.
```
timestamp_us  bigint
asset         text
timeframe     text     -- '5m' / '15m'
slug          text
market_id     text
strike        numeric  -- chainlink @ slot_start
dist          numeric  -- chainlink basis (signed)
dist_abs      numeric
side          smallint -- +1/-1
speed_away    numeric  -- chainlink $/min away from strike
cross         numeric  -- min to return (cap 999)
have_m        numeric  -- min left
margin        numeric
d_speed       numeric  -- chainlink Δspeed last 30s
bn_dist       numeric  -- binance basis variants (optional but log them)
bn_speed_away numeric
entry_vwap    numeric  -- favorite-token $25 book-walk ask, if cheap to grab live (else NULL, derive offline)
source        text
```
`physics_market_ctx_v2` is fully derivable offline by joining `physics_ticks_v2` to
`market_resolutions_v2` (strike_price, slot_start/end) — so if live per-slot logging is
hard at first, ship `physics_ticks_v2` ONLY and backfill the ctx table from a SQL/python
job. The asset-level tick is the must-have.

---

## 4. Collector loop (pseudocode)
```python
# runs on VPS3 alongside existing collectors; 1 Hz
while True:
    t = now_us()
    for asset in ("BTC","ETH","SOL"):
        bn  = price_asof(binance_1s[asset], t)
        cl  = price_asof(chainlink_rtds[asset], t)
        sp_bn = (bn - price_asof(binance_1s[asset], t-60e6))          # $/min
        sp_cl = (cl - price_asof(chainlink_rtds[asset], t-60e6))
        dsp_bn = sp_bn - (price_asof(binance_1s[asset],t-30e6) - price_asof(binance_1s[asset],t-90e6))
        dsp_cl = sp_cl - (price_asof(chainlink_rtds[asset],t-30e6) - price_asof(chainlink_rtds[asset],t-90e6))
        write physics_ticks_v2(t, asset, bn, cl, sp_bn, sp_cl, dsp_bn, dsp_cl, (bn-cl)/cl*1e4)
        for slot in active_updown_slots(asset):          # 5m + 15m
            K = slot.strike                               # chainlink @ slot_start, cached at open
            f = physics_at(chainlink_rtds[asset].ts, .px, K, t, slot.slot_end_us)   # SAME fn as backtest
            write physics_market_ctx_v2(t, asset, slot.tf, slot.slug, slot.market_id, **f, ...)
    sleep_until(t + 1_000_000)
```
`active_updown_slots` = the slugs whose `[slot_start, slot_end]` contains `t`. Cache each
slot's `strike` at slot open (first chainlink read at/after slot_start).

---

## 5. Parity check (do this before trusting live data)
After ~1 day of collection, prove live == backtest:
1. Pull `physics_market_ctx_v2` for ~200 BTC slugs.
2. Recompute the same fields offline with `physics_signal.physics_at` on canonical
   `oracle_prices_v2` / `load_chainlink_asof` at the same `timestamp_us`.
3. Expect `dist`, `speed_away`, `cross`, `d_speed` to match to <1e-6 (same formula, same
   feed). Any divergence = a feed-alignment or asof bug in the collector — fix before use.

---

## 6. What we're collecting it FOR (carry-over findings)
From the full investigation (`PHYSICS_SIGNAL_SYNTHESIS_2026_06_01.md`):
- The physics signal is **priced in** (realized WR == implied, gap ≈ 0). It is a
  risk/selection descriptor, **not** a standalone money signal. Do NOT deploy capital on it.
- The recovered WEAK_COMBO thresholds (WR-optimal): block if `dist_abs<30 AND speed_away<10`
  (or `40/15`). PnL-optimal is simpler: `dist_abs≥40`. **`d_speed≥0` (inertia not fading) is
  a confirmed helpful gate** — the reason to collect d_speed.
- The ONE candidate worth proving: **`dist_abs≥40 & entry_vwap<0.95 & spread≤0.02`** (BTC),
  +$0.85/fire OOS but only **t=1.68 / p=0.094** — needs **~22 more OOS days** to reach
  p<0.05. This collector is exactly how we get those days. Keep scoring this pocket weekly.
- 🔴 **Blocker that gates any future deploy:** confirm the live **fee model** on the
  crypto up-down contracts (legacy 2%-on-profit vs 0.07-curve) — verify against a real
  `poly_updown_resolution.pnl_usd` or the Polymarket dashboard. The pocket is positive under
  all three models, but sizing math needs the truth.
- Overlay on existing winners is **dead** (ETH dist scale wrong: $40 threshold vs $5 max;
  BTC-15m overlap 0.14 fires/day). Don't wire physics into the current sleeves.

---

## 7. Effort / notes
- ~1 collector file + 2 `CREATE TABLE` (hypertables) + the `physics_at` port. Reuses
  existing feeds and the existing `oracle_lag.py` plumbing → small.
- Volume negligible (~0.26M tick rows/day; ctx rows ~ active-slots × 86400).
- ETH/SOL: same code, scale `dist`/`speed` thresholds by price (ETH $40-equiv ≈ $1.0; thresholds are price-relative — store raw $, threshold per asset later).
- Rust port: add a `PhysicsSnapshot` struct in `TVRUST/crates/tv-core` mirroring §3, fed by the same feed handles as `OracleLagSnapshot`.
```
