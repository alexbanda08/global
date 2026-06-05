# Investigation — sniper_v5 "double-fire" on `poly_sniper_v5_btc_15m_ema50_ema800_off600_down`

**Verdict: NOT a double-fire / double-entry. It is ONE simulated entry + ONE settlement log per window.**
My earlier "poly double-fires every window (off600 + off900)" claim was a **counting artifact** — corrected here.

---

## What the two events actually are (VPS3 `trading.events`, kind=`poly_updown_signal`)
Per slug, the sniper_v5 controller emits exactly **two** events, both stamped `all_gates_passed=true`:

| event_type | offset (fire_us − slot_start) | meaning | fill fields |
|---|---|---|---|
| `sleeve_fire_placed` | **+600s** (the configured `off600`) | the (paper) ENTRY | `fill_vwap`, `fill_shares` set |
| `sleeve_fire_resolved` | **+900s** (= slot_end) | SETTLEMENT log | same `fill_vwap`/`fill_shares` (mirror) + `won`/`pnl_usd` |

Verified per-slug counts (last 6h): **1 placed + 1 resolved + 0 extra**, every slug.
7-day totals: 137 `sleeve_fire_placed` vs 133 `sleeve_fire_resolved` (≈1:1 — the lifecycle, not two entries).

The "fires 2×" comes from counting `all_gates_passed='true'` **without filtering `event_type`** — that flag is
present on BOTH the placed and the resolved event, so a naive counter doubles every trade. (This is exactly
what my earlier ad-hoc query did.)

## It is SHADOW / paper — no blockchain trades exist to check
- `trading.orders` → **0 rows** for this sleeve (and 0 for ALL sleeves in 7d — the sniper fleet places no real orders).
- `trading.positions` → **0 rows**.
- `public.onchain_fills_v2` → **0 rows ever** (empty).
→ `placed_size_usd=5.0` is a **simulated** book-walk fill (`book_source=ws_mirror`), not an on-chain order.
There is nothing on-chain to verify; the sleeve is paper. (Live execution is the separate Ireland momo/Kalshi set.)

## The live dashboard (`api/bots.py`) already counts correctly — no production bug
- Fills: `COUNT(*) FILTER (reason='order_placed' AND fill_status='filled')` — sniper_v5 events don't set those,
  so `fill_count_24h` shows 0 for them (it does NOT double-count).
- Wins/losses: derived from `event_type='sleeve_fire_resolved'` (one per trade) — correct.
So the production view is fine. The double-count only appears in counters keyed on bare `all_gates_passed`.

---

## The real (latent) footgun + fix
The sniper_v5 writer (`controllers/polymarket_sniper_v5.py`, not in the local snapshot) stamps
`all_gates_passed=true` on the **`sleeve_fire_resolved`** event as well as the `sleeve_fire_placed` one.
It is redundant there (you only resolve positions that already passed gates) and it lets any consumer
double-count fires.

**Fix A — counting convention (adopt everywhere, immediate):**
count a FIRE as `event_type='sleeve_fire_placed'` (or `COUNT(DISTINCT slug)` within all_gates_passed),
**never** bare `all_gates_passed='true'`.
```sql
-- correct fire count for a sniper_v5 sleeve
COUNT(*) FILTER (WHERE data->>'event_type' = 'sleeve_fire_placed')
```

**Fix B — defensive source patch (TV agent, optional):**
in the sniper_v5 resolved-event builder, drop `all_gates_passed` (or set it only on `sleeve_fire_placed`).
Safe: `bots.py` resolution_sql keys on `event_type='sleeve_fire_resolved'`, not on `all_gates_passed`, so
win/loss counting is unaffected. Verify no other consumer filters resolved events by `all_gates_passed` first.

## Note (separate, from the earlier comparison)
vs the Kalshi twin: Kalshi's logger (`kalshi_event_logger.py:_build_resolution`) does NOT set `all_gates_passed`
on its resolved event — so Kalshi doesn't have this footgun. That asymmetry is why the two looked like they
"fire differently" under an `all_gates_passed` count.

## END
