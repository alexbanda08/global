# Investigation — `btc_15m_ema50_ema800_off600_down_H`: live Kalshi "not firing" — 2026-06-02

> ## ✅ PARTIALLY FIXED / IN PROGRESS — 2026-06-02 (deployed Ireland)
> - **Fix #1 (capture 409 body) — DONE + LIVE** (`TV_FIX_KALSHI_409_2026_06_02`): `client.py::_request` now logs
>   `kalshi_request_error_body` (status+body) on any 4xx before `raise_for_status()`, and both
>   `kalshi_updown.place_order_failed` handlers attach `http_status`+`kalshi_body`. The next 409's real Kalshi
>   error code is now captured.
> - **The phantom half — DONE + LIVE** (`TV_FIX_LIVE_FILL_ACCOUNTING_2026_06_02`, see
>   `docs/architecture/FIX-SPEC-LIVE-FILL-ACCOUNTING.md` Bug B): a killed FOK (`filled_count=0`, doesn't raise)
>   is no longer booked as a filled position → `fok_killed_or_unfilled` skip, no phantom resolution. This is the
>   silent counterpart to the loud 409 and protects the new `kalshi_sniper_all_15m_s4_prewindow` sleeve too.
> - **TODO (targeted 409 fix):** once a captured body confirms the cause — fix #3 (dedupe live orders per
>   (ticker,side,window); S4-DOWN + `_H`-DOWN both hit KXBTC15M) and/or fix #4 (market-state/book-freshness guard;
>   the `seq_gap_detected` feed flood is still live). Fix #2 (reconcile phantom positions) + fix #5 (base roster)
>   still open.

Compares the VPS3 **shadow** `_H` (paper) vs the Ireland **live** `_H`, and diagnoses why the live one
appears not to fire. Host: Ireland `85.137.174.152` (tv-engine.service, restarted 05:12 UTC today).

---

## TL;DR — it IS firing, but ~26% of live orders are rejected by Kalshi with HTTP 409 Conflict, and the last 2 attempts (05:25, 05:40) both 409'd → looks dead right now.

The signal is fine and identical to shadow. The failure is **live execution**: Kalshi rejects the
`POST /portfolio/orders` with **409 Conflict**. 7-day live tally: **32 FILLED + 11 × 409 Conflict**.

---

## Last-trades comparison — shadow (VPS3, paper) vs live (Ireland, Kalshi)
Same sleeve, same DOWN signal, same KXBTC15M tickers:

| window (UTC) | VPS3 shadow `_H` (paper) | Ireland live `_H` (real Kalshi) |
|---|---|---|
| 05:40 | "fill" 0.48 (simulated OK) | **409 CONFLICT** ✗ |
| 05:25 | "fill" 0.92 (simulated OK) | **409 CONFLICT** ✗ |
| 02:40 | "fill" | FILLED 0.70 ✓ |
| 01:25 / 01:10 / 00:40 | "fill" | FILLED 0.90 / 0.74 / 0.72 ✓ |
| 00:25 / 23:55 | "fill" | **409 CONFLICT** ✗ |
| 04:10 | "fill" 0.97 | blocked: `entry_vwap_out_of_band_0.9720` (legit gate) |

Shadow ALWAYS "fills" (no real API call — simulated book-walk). Live succeeds ~74% and 409s ~26%; the
two most recent attempts failed, which is why it looks like it stopped.

## Root cause(s)

**Not** a client retry (the kalshi client `_request` re-raises on timeout, only retries on 429) and **not**
a duplicate idempotency key (`coid = f"kalshi_{sleeve_id[:20]}_{uuid4().hex[:8]}"` — fresh uuid each call).
So Kalshi rejects the **first** POST with a genuine business conflict. Two distinct contributors found:

1. **Duplicate-market placement (confirmed, historical).** The base `…off600_down` and `…off600_down_H`
   sleeves both bet **DOWN on the SAME KXBTC15M ticker** — confirmed `down + down_H` on dozens of 06-01
   tickers. Two orders, same market + same side, same account → Kalshi 409 (self-conflict). The base
   sleeve stopped logging at **06-01 15:46** (dropped from the live roster after a restart), so this is
   reduced now — but it explains the older 409 cluster and will recur if the base is re-enabled.
2. **Market-state / timing 409 (recent, exact reason unknown).** The 05:40 failure log shows
   `kalshi_updown.discovered_market` (status active) at 05:40:00.037 then `place_order_failed` 409 at
   05:40:00.283 — order fired ~0.25 s after discovery, on a just-discovered market, with only `_H`
   touching that ticker (no concurrent sleeve). Likely the market isn't accepting orders yet / is in a
   transitional state at the off600 entry point.

**Blocking diagnostic gap:** the engine logs only the HTTP **status line** (`raise_for_status()` →
status + url), NOT the Kalshi **response body**, so the specific Kalshi error code (self_trade /
insufficient_balance / market_not_active / duplicate) is **not captured anywhere**. Can't pin cause #2
precisely until this is fixed.

**Aggravating factor:** the Kalshi market-data feed is flooding the journal with `seq_gap_detected` +
`requested_snapshot` (constant sequence gaps). A stale/gappy book view can drive orders that conflict
with real market state.

## Fixes (TV agent, priority order)
1. 🔴 **Capture the 409 response body.** In `controllers/kalshi_updown.py` place_order exception handler
   (and/or `venues/kalshi/client.py`), log `exc.response.text` / `.json()` (and `status_code`). One-line
   change; without it the real Kalshi reason is invisible. **Do this first.**
2. 🔴 **Verify no PHANTOM positions.** A Kalshi 409 can mean the order was actually accepted on a prior
   send. Reconcile Kalshi account positions vs engine state for the 11 409'd windows — confirm the engine
   isn't blind to a real live position. (No orphan/reconcile logs exist → reconciliation may not run.)
3. 🟡 **Dedupe live orders per (ticker, side).** Guard so only ONE sleeve/order hits a given KXBTC15M
   market+side per window (base + `_H` + `all_15m_s4_prewindow` all target KXBTC15M). An in-flight order
   set keyed on (ticker, side) eliminates cause #1.
4. 🟡 **Stop firing at a market-transitional moment / fix the feed.** Investigate the `seq_gap_detected`
   flood (feed re-subscribe/snapshot loop); skip placement when the book is stale or the market just
   became active (guard on market status + book freshness before POST).
5. ⚪ **Confirm base `…off600_down` roster status.** The non-`_H` live sleeve dropped after the 05:12
   restart (last event 06-01 15:46) — re-add if intended, or document the removal.

## Artifacts / evidence
- Ireland live `_H`: 32 fills + 11×409 (7d), last 2 attempts 409. Shadow VPS3 `_H`: paper, always "fills".
- `coid` gen: `kalshi_updown.py:393,704`; client retry logic: `venues/kalshi/client.py:_request` (159–240).
- 409 log: `kalshi_updown.place_order_failed` (status line only, body dropped).
## END
