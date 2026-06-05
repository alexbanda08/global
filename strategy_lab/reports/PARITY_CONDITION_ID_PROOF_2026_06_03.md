# Slot-matched parity proof — momo_v2 live-mirror sleeve, 13-day (2026-06-03)

Cold proof for `HANDOFF_2026_06_03.md` open-item #5: match the same slots across hosts and diff the gate
inputs to nail the shadow≠live cause. Done for the live sleeve `poly_updown_sol_5m_momo_v2_HOLD_f7` over its
**full ~13-day history on both hosts** (VPS3 shadow since 05-20, Ireland live since 05-24).

> **TL;DR — the handoff's boundary-flip mechanism is CONFIRMED cold, but the dominant driver is different.**
> Over **2408 matched slots**, shadow and live make the same decision **99.7%** of the time. The 0.29% that
> flip are boundary slots, and they flip for THREE small per-host reasons, in order of impact:
> 1. **Rolling `abs_ret_2m_threshold` divergence** — the adaptive threshold differs per host on **6.6%** of
>    slots (each host computes it from its own feed history). Drove **5 of 7** decision flips.
> 2. **Feed `ret_2m` divergence** — differs on **2.1%** of slots (feeds equally fresh, median 9 ms apart).
>    Drove **2 of 7** flips. ← this is the handoff's stated hypothesis: real, but the *smaller* cause.
> 3. **Shadow `qty_compute_failed` bug** — 8 would-be fires the shadow decided but failed to size → live
>    placed, shadow didn't.
>
> So "shadow reads a different feed → boundary flips" is true in spirit, but the bigger lever is the
> **rolling threshold state**, not the instantaneous ret_2m. The earlier "threshold identical 0.00151"
> note in the handoff was a single-window coincidence; across 13 days it differs 6.6%.

## ⚠️ Two earlier mistakes corrected
1. **Wrong sleeve.** VPS3 runs two momo_v2 SOL-5m shadow sleeves: `_momo_v2_hod` (`gate_stack=["hod"]`,
   a separate HOD-gated variant) and `_momo_v2_HOLD_f7` (no gate, the live mirror). Filtering on
   `strategy_mode='momo_v2'` compared the `_hod` variant to live and surfaced a fake "HOD gate config
   mismatch." Always match the exact `sleeve_id`.
2. **Wrong window.** A 24h filter caught only ~6h of VPS3 data and implied the sleeve was new. It is not —
   VPS3 shadow HOLD_f7 had a **~23h OUTAGE on 06-02** (last row 06-01 23:36 → resumed 06-02 23:06; Ireland
   stayed full). Use the full history; exclude nothing but the gap (which simply produces no shared slots).

## Method
- Each host's **own local `storedata` Postgres** `trading.events`, read-only DSN from `/etc/tv/*.env`.
- `poly_updown_signal`, `sleeve_id='poly_updown_sol_5m_momo_v2_HOLD_f7'`, full history.
- Joined slot-by-slot via `floor(extract(epoch from at)/300)` (TZ-independent; VPS3 logs CEST, Ireland UTC).
- Diffed `ret_2m_at_signal`, `abs_ret_2m_threshold`, `signal`, `reason`, `bar_ctx_age_ms`.

## Result — 2408 matched slots (full 13-day overlap)
| metric | value |
|---|---|
| rows (signals) | vps3 3822 / ireland 2744 |
| **matched slots** | **2408** |
| `ret_2m_at_signal` bit-identical | 2358 (**97.9%**) |
| `ret_2m` differs | 50 (2.1%); median \|Δ\| 3.6e-4, max 1.1e-3 |
| `abs_ret_2m_threshold` identical | 2249 (93.4%) |
| **`abs_ret_2m_threshold` differs** | **159 (6.6%)**; median \|Δ\| 3.4e-4, max 4.4e-4 |
| `bar_ctx_age_ms` diff (v3−ir) | median **9 ms** (p10 1, p90 67) |
| **signal-decision flips** | **7 / 2408 (0.29%)** |
| placed: v3 / ir / both | 128 / 126 / **118** |
| Ireland-only placements | 8 (all `qty_compute_failed` on VPS3) |
| VPS3-only placements | 10 (Ireland: `no_signal` 7, `entry_rejected` 2, `market_not_discovered_at_entry` 1) |

### The 7 decision flips, decomposed (per-host ret/thr at the slot)
```
slot       VPS3                                  IRELAND                               cause
5932406    ret 0.001274 thr 0.001162 → UP        ret 0.001274 thr 0.001515 → NONE      THRESHOLD differs
5932472    ret -0.001287 thr 0.001099 → DOWN     ret -0.001287 thr 0.001499 → NONE     THRESHOLD differs
5932490    ret 0.001288 thr 0.001119 → UP        ret 0.001288 thr 0.001496 → NONE      THRESHOLD differs
5932498    ret 0.001295 thr 0.001162 → UP        ret 0.001295 thr 0.001497 → NONE      THRESHOLD differs
5932503    ret 0.001411 thr 0.001163 → UP        ret 0.001411 thr 0.001497 → NONE      THRESHOLD differs
5933218    ret -0.001606 thr 0.001512 → DOWN     ret -0.000494 thr 0.001512 → NONE     FEED (ret_2m) differs
5934497    ret 0.002104 thr 0.001413 → UP        ret 0.000991 thr 0.001413 → NONE      FEED (ret_2m) differs
```
5 flips: identical ret_2m, **different rolling threshold** (Ireland ~0.0015 vs VPS3 ~0.0012) → VPS3 fires,
Ireland doesn't. 2 flips: identical threshold, **different ret_2m** → genuine feed boundary flip.

### qty_compute_failed (shadow-only)
On the 8 Ireland-only placements the shadow had already decided to fire (e.g. `signal=UP`, `ret_2m=0.00217 >
thr=0.00152`, `entry_phase=t_plus_60`) but failed at qty computation and logged no order. Shadow-side bug;
makes shadow **under-count** fires vs live.

## Conclusion (refines HANDOFF_2026_06_03 §2)
- The handoff's core claim — **shadow≠live is a per-host divergence at decision boundaries** — is **proven
  cold**. ~99.7% of slots agree; the boundary slots flip.
- But the **biggest flip driver is the rolling `abs_ret_2m_threshold`** (differs 6.6% of slots, caused 5/7
  flips), not the instantaneous `ret_2m` feed (differs 2.1%, caused 2/7). The handoff focused on the feed;
  the threshold state matters more here.
- Feeds are NOT staler on one host — `bar_ctx_age_ms` median diff is 9 ms.
- Net placement agreement is high (118 both / ~128 each); total divergence over 13 days = 10 vps3-only +
  8 ireland-only = 18 placements, split across threshold drift, feed drift, qty bug, and market discovery.

## Fix (for the TV agent) — prioritized by measured impact
1. **Share the rolling-threshold state, not just the instantaneous read.** The two hosts each compute
   `abs_ret_2m_threshold` from their own feed history → 6.6% divergence → most boundary flips. To make shadow
   predict live, the shadow must compute the threshold from the SAME feed-history/window the live host uses
   (or read the live host's threshold value).
2. **Fix `qty_compute_failed` on the shadow** (8 dropped fires / 13d). Shadow qty path likely needs the same
   notional/book inputs as live.
3. Align the `ret_2m` feed (handoff #1) — lowest impact here (2/7 flips); already 97.9% identical, 9 ms.

## Caveats
- VPS3 shadow HOLD_f7 had a ~23h outage on 06-02 (not a slot-skip, a process gap) — worth alerting on
  separately; the shadow being DOWN is its own parity hazard.
- `condition_id` is only populated on placed rows; slot-bucketing (epoch/300) is the join key, and matched
  placements additionally agreed on `condition_id`.

## Still open — sniper path
Sniper sleeves are STOPPED live (`TV_POLY_SNIPER_V5_LIVE_ENABLED=false`); no live data to slot-match. After
the $1 restart (open-item #3), re-run this exact diff for `poly_sniper_v5_*` (join by slot; diff book-spread
snapshot + `book_source` + snapshot age) to test the `TV_POLY_PAPER_BOOK_CACHE_TTL=1` staleness hypothesis.

## Repro (run on `vps3` and `vps_ireland`, join on slot)
```sql
select floor(extract(epoch from at)/300)::bigint slot, data->>'ret_2m_at_signal' ret2m,
       data->>'abs_ret_2m_threshold' thr, data->>'signal' sig, data->>'reason' reason,
       data->>'bar_ctx_age_ms' age
from trading.events
where kind='poly_updown_signal'
  and sleeve_id='poly_updown_sol_5m_momo_v2_HOLD_f7'   -- exact live-mirror sleeve, NOT the _hod variant
order by slot;
```
