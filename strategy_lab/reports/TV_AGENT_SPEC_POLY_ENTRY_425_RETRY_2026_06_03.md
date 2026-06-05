# TV Agent Spec — Polymarket entry submit retry on transient 425/5xx — 2026-06-03

## Problem (evidence)
Live engine (Ireland) drops real fires when the Polymarket CLOB returns a **transient** error.
Observed in the live journal (2026-06-03 ~12:16 UTC):
```
[py_clob_client_v2] request error status=425 url=https://clob.polymarket.com/order body=service not ready
PolyApiException[status_code=425, error_message=service not ready]
→ event=poly.submit.failed → FillStatus.REJECTED → audit reason=entry_rejected
```
The submit fails ONCE and the whole fire is abandoned (`fill_status=rejected`, `fill_qty` empty,
`book_source` empty — i.e. rejected at submission, before any book walk).

**Impact:** measured on `poly_updown_btc_15m_momo_HOLD_f7`, 6 `entry_rejected` over ~13d; 4 of them are
windows where the PAPER engine (VPS3) correctly fired the identical signal. So these are NOT bad signals
and NOT thin-book — they are Polymarket server-side hiccups (425 "service not ready", and by extension
transient 5xx / network timeouts) that a retry would recover. Cross-engine analysis:
`strategy_lab/reports/ENGINE_COMPARE_IRELAND_VS_VPS3_MOMO_F7_2026_06_03.md`.

## Scope / non-goals
- This is NOT an order-type change. Entries are already `GTC` (`venues/polymarket/client.py:269`),
  exits are already `FAK` (IOC-style partial). Do **not** touch order types.
- Only add a bounded retry around the `post_order` submission for **transient** failures.

## Change
File: `backend/app/venues/polymarket/client.py`, the internal submit path (`_submit` /
`post_order` call site near line 711, where `PolyApiException` currently maps straight to
`FillStatus.REJECTED` at lines ~806/814).

### Retry policy
- **Retry only on transient classes:**
  - HTTP `425` (service not ready)
  - HTTP `5xx` (`500,502,503,504`)
  - network/timeout exceptions (connect/read timeout, connection reset)
- **Do NOT retry on terminal classes** (these are real rejects — fail fast, keep current behavior):
  - `4xx` other than 425 — esp. `400` (bad order), `401/403` (auth), `429` (rate-limit: see note),
    insufficient balance/allowance, min-size, decimals.
  - Note on `429`: do NOT hammer. If retrying 429 at all, use a longer backoff and cap at 1 retry.
- **Attempts:** max **3** total (1 initial + 2 retries).
- **Backoff:** ~**150 ms** then ~**400 ms** (small jitter ok). Keep total added latency < ~600 ms.
- **Window guard (critical):** abort remaining retries if the signal's entry window has passed —
  i.e. if `now > ws_s + entry_phase_offset + ENTRY_RETRY_MAX_AGE_MS`. A fill that lands after the
  window edge is worse than no fill. Suggest `ENTRY_RETRY_MAX_AGE_MS` default 2000, env-tunable.
- **Idempotency:** ensure a retry cannot double-submit. The py-clob order is signed once; only the
  HTTP POST is retried. If a prior attempt's outcome is ambiguous (timeout AFTER send), do **one**
  status re-query before re-posting; if a resting/filled order is found, adopt it instead of reposting.

### Config (env, with safe defaults)
```
TV_POLY_ENTRY_RETRY_MAX_ATTEMPTS = 3
TV_POLY_ENTRY_RETRY_BACKOFF_MS   = "150,400"
TV_POLY_ENTRY_RETRY_MAX_AGE_MS   = 2000
TV_POLY_ENTRY_RETRY_ON_429       = false
```

### Observability
- Emit `poly.submit.retry` (level=info) per retry with `{attempt, status_code, elapsed_ms, token_id}`.
- On final give-up keep the existing `poly.submit.failed` + `entry_rejected` audit, but add
  `retry_attempts` and `last_status_code` to the audit `data` so we can measure recovery rate.
- On a retry that succeeds, the normal `order_placed` audit path runs unchanged (add `retry_attempts`).

## Acceptance / verification
1. Unit: mock `post_order` to raise 425 once then succeed → result is FILLED/PARTIAL, `retry_attempts=1`,
   exactly one signed order, one `order_placed` audit (no `entry_rejected`).
2. Unit: mock persistent 425 → after 3 attempts → `entry_rejected` with `retry_attempts=2`,
   `last_status_code=425`. No double submit.
3. Unit: 400 bad-order → **no retry**, immediate `entry_rejected`, `retry_attempts=0`.
4. Unit: window-guard — first attempt returns 425 but clock advanced past `ws_s+offset+MAX_AGE` →
   no further retry, `entry_rejected` with reason note `retry_window_expired`.
5. Live canary: after deploy, query `trading.events` for `poly.submit.retry` events and confirm
   `entry_rejected` rate on `poly_updown_btc_15m_momo_HOLD_f7` (and the sniper sleeves) drops; report
   recovered-fire count over 1 week.

## Risk
- Low. Bounded attempts + window guard cap added latency and prevent late fills. Idempotency re-query
  prevents the only real hazard (double position on ambiguous timeout). Terminal 4xx behavior unchanged.

## Related (do not bundle — separate items)
- Kalshi exit leg still FOK (`venues/.../client.py:535`) — switch FOK→IOC for hedge salvage. (handoff B4)
- Deterministic cross-host threshold (shared BarContext) — low priority, ~0 PnL. (this session)
