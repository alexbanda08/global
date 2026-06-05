# DEBUG: sol_5m_momo_v2_HOLD_f7 Live↔Shadow Parity — 2026-06-03

Investigates why `poly_updown_sol_5m_momo_v2_HOLD_f7` behaves differently on Ireland (live, real money) vs VPS3 (paper/shadow).

---

## 1. Code Parity

| File | Ireland md5 | VPS3 md5 | Match? |
|---|---|---|---|
| `strategies/polymarket/momo_v2.py` | `051927f7` | `051927f7` | ✅ IDENTICAL |
| `strategies/polymarket/f7_gate.py` | `89f119a0` | `89f119a0` | ✅ IDENTICAL |
| `strategies/polymarket/base.py` | `45b60319` | `45b60319` | ✅ IDENTICAL |
| `engine/poly_updown_loop.py` | `c680ac4b` | `c680ac4b` | ✅ IDENTICAL |
| `venues/polymarket/paper.py` | `85af2360` | `85af2360` | ✅ IDENTICAL |
| `controllers/polymarket_updown.py` | `230e8a70` | `230e8a70` | ✅ IDENTICAL |

Ireland has no git repo (`NO_GIT`). VPS3 is at `3a2ff3a91a91fcaa11ced990a32b38cc68a966e4`.

**All 6 files are bit-for-bit identical. The divergence is NOT a code difference.**

Sleeve registration: both hosts register `poly_updown_sol_5m_momo_v2_HOLD_f7` via `_preflight.py` (`"poly_updown_sol_5m_momo_v2_HOLD": ("momo_v2", "HOLD_ONLY")`). Un-deprecated on 2026-06-02 on both hosts.

---

## 2. Fire Parity — Signal Count & Reasons

**3-day window (2026-05-31 to 2026-06-03 ~18:00 UTC):**

| Metric | Ireland (LIVE) | VPS3 (PAPER) |
|---|---|---|
| Total `poly_updown_signal` events | 858 | 564 |
| signal=NONE (no_signal) | 759 | 505 |
| signal≠NONE, reason=order_placed | 98 | 41 |
| signal≠NONE, reason=qty_compute_failed | **0** | **18** |
| signal≠NONE, reason=entry_rejected | 1 | 0 |
| poly_updown_resolution | 98 | 41 |
| poly_redeemed (live-only) | 55 | — |

**Ireland has 858 signals vs VPS3's 564** — a ~294 event gap, explained by a **~24-hour VPS3 engine outage** (2026-06-02 01:00+02 → 2026-06-03 01:00+02, zero signals during that window). Ireland ran continuously (12 events/hr consistently throughout).

### Signal feature match on shared slots (06-03 only, after Ireland got `slot_start_us`)

Ireland only started logging `slot_start_us` in the event `data` JSON on 2026-06-03 (engine update). Before that, Ireland had 741/858 events with NULL `slot_start_us`, making slot-level join impossible for the prior days.

On the **119 Ireland signals with `slot_start_us`** (all 2026-06-03):

- **Features are IDENTICAL between hosts on every shared slot** — `rsi_14`, `ret_2m_at_signal`, `abs_ret_2m_threshold`, `f7_decision` match to 15+ decimal places.
- Example (slot `1780477200000000`): Ireland `ret_2m=0.0015993605968217953`, VPS3 `ret_2m=0.0015993605968217953` — bit-exact match. Same `threshold=0.0015536304290306641`, same `rsi_14=47.69235609523593`.
- Signal direction matches on all inspected shared slots — no disagreements found.
- **Signal agreement ≈ 100% on slots both hosts processed**.

This proves: both hosts read the same Binance feed and compute the same features. The ret_2m/RSI gate is NOT a divergence source.

---

## 3. Divergence Classification

### A. DATA/FEED divergence — MINOR, explains ≤0% of outcome divergence

Same Binance feed, same computed features. Zero evidence of data drift. **Not the issue.**

### B. LOGIC/data-type divergence — NONE

All 6 code files identical. No dtype/rounding differences possible. **Not the issue.**

### C. TIMING divergence — PRESENT (VPS3 24h outage, Jun 02)

VPS3 logged 0 signals from 2026-06-02 01:00+02 to 2026-06-03 01:00+02 (~24h gap). Ireland was continuous. This explains the 858 vs 564 count difference (~294 missing events = ~24.5 hours × 12 events/hr). Cause: likely a `tv-engine` service restart/crash on VPS3 that was not recovered immediately.

### D. FILL/execution divergence — **PRIMARY ACTIVE DIVERGENCE**

This is the root cause of behavioural difference on shared fire events:

| Scenario | Ireland (LIVE) | VPS3 (PAPER) |
|---|---|---|
| Signal fires, book available | `order_placed` → real order via SDK | `order_placed` → simulated fill via `PolyPaperExecutor` |
| Signal fires, book fetch fails | **Never fails** — SDK always gets book | `qty_compute_failed` → **NO fill recorded** |
| Book data source | Polymarket SDK (direct REST/WS) | 3-tier: WS BookMirror → CLOB REST → Storedata DB |

**`qty_compute_failed` on VPS3: 18 instances in 3 days, 0 on Ireland.**

For these 18 events, Ireland successfully placed the order (verified: for the 5 slots with `slot_start_us` in that window — `1780493700000000`, `1780496400000000`, `1780498500000000`, `1780503600000000`, `1780506000000000` — Ireland shows `reason=order_placed` while VPS3 shows `reason=qty_compute_failed` on the SAME signal direction).

**Mechanism** (from code in `polymarket_updown.py:3062` + `paper.py:306-351`):

1. Controller calls `self._compute_qty_shares(token_id)`.
2. Paper executor runs `_fetch_orderbook(token_id)` via 3-tier:
   - Tier 1: WS BookMirror (`_book_mirror.get(str(token_id))`) — empty if token not yet subscribed or update race.
   - Tier 2: CLOB REST `/book?token_id=...` — returns `{"error": "No orderbook exists"}` when market is between windows or request races a market rollover.
   - Tier 3: Storedata `public.orderbook_snapshots_v2` — absent for that token_id at that instant.
3. All 3 tiers return empty → `_fetch_orderbook` returns `{"ts":0, "bids":[], "asks":[], "_source":"empty"}`.
4. `_compute_qty_shares` hits `if not asks: return None`.
5. Controller logs `reason="qty_compute_failed"` and returns without placing the trade.

Ireland (live) uses `PolymarketClient` (SDK) which reads the order book directly with retries — never returns an empty book for an active market.

**Impact of `qty_compute_failed`:**
- 18/59 = **30.5% of VPS3's would-be fire events were silently dropped** (41 placed + 18 failed = 59 attempted).
- Ireland placed all 98 in the same 3d window.
- The shadow win rate is computed only over the 41 placed trades, NOT the 59 attempted — **shadow WR is biased by fill selectivity**: trades that succeed on paper may be systematically different (better books, less marginal slots) from the 18 that failed.

---

## 4. Root Cause Summary

**Three independent divergences, ranked by impact:**

1. **[FILL] VPS3 paper `qty_compute_failed` = 30.5% of fire events dropped** (18/59 attempted). Cause: paper executor's 3-tier book fetch returns empty when WS BookMirror races a market boundary AND CLOB REST races the same boundary AND Storedata has no snapshot. Live SDK never fails this way. This is the dominant parity issue.

2. **[TIMING] VPS3 24h engine outage on 2026-06-02**. Shadow missed ~294 events (slots that Ireland processed but VPS3 did not). Recoverable by ensuring `tv-engine` auto-restarts on VPS3.

3. **[FEATURE] None** — features (rsi, ret_2m, threshold, f7_decision) are byte-identical on shared slots. The gate computation is correctly parity-aligned.

---

## 5. Fix Recommendations

### Fix 1 (HIGH PRIORITY — paper fill gap): Add retry + pre-fire book warm-up on VPS3

**Problem**: `qty_compute_failed` happens when 3 tiers all race the market boundary at fire time. The WS BookMirror subscription likely subscribes to a new market's token_id only after the first fire attempt, creating a cold-start miss.

**Fix options (choose one):**
- **Option A** (best): Pre-warm the book cache for the upcoming slot's token_id at `ws_s` (120s before fire) rather than at fire time. The `_fetch_orderbook` LRU TTL=1s is too short to help; subscribe the token to BookMirror in advance.
- **Option B** (quick): Increase CLOB REST retry attempts from 2 to 5 with 200ms backoff specifically for `qty_compute_failed` recovery. Set `TV_POLY_PAPER_REST_RETRY_ATTEMPTS=5` on VPS3.
- **Option C** (conservative): When all 3 tiers fail, DON'T silently drop — log as `qty_compute_failed_and_retry_at_next_tick` and re-attempt at t+5s.

**Do NOT** just fall back to Storedata more aggressively — the `STALE_AFTER_SECONDS=30` gate correctly rejects stale snapshots for 5m markets.

### Fix 2 (MEDIUM — VPS3 engine uptime): Add auto-restart + alert

VPS3 `tv-engine` had a ~24h outage on 2026-06-02 with no apparent recovery. Add `Restart=always` + `RestartSec=10` to the systemd unit, and a watchdog alert if the service goes down for >2min.

### Fix 3 (LOW — observability): Log `slot_start_us` on Ireland for all events

Ireland only started logging `slot_start_us` in signal events on 2026-06-03. All prior Ireland signals have NULL `slot_start_us`, making cross-host slot-level joins impossible for the audit window. Add this field retroactively to the Ireland event logger (it's already present on VPS3).

---

## 6. Signal Agreement Summary

| Metric | Value |
|---|---|
| Slots where both fired (shared, 06-03 only) | ~15/15 same direction (100%) |
| Feature drift (rsi, ret_2m) on shared slots | **0** — byte-identical |
| `qty_compute_failed` rate: VPS3 vs Ireland | 18 vs 0 (3d) |
| Effective VPS3 paper fire-through rate | 41/59 = 69.5% |
| VPS3 engine outage gap | ~24h (2026-06-02) |

**Conclusion**: code is identical, features are identical, signal direction is identical on shared slots. The divergence is entirely in the **execution layer**: VPS3 paper mode silently drops 30% of valid fires due to book-fetch race conditions at market boundaries, and had a 24h outage. Shadow PnL stats computed on the 41 filled events are biased — they exclude the 18 boundary-fires where the book was thin/empty (the hard-to-fill, likely worse-priced trades).
