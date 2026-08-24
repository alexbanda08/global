# TV_AGENT_SPEC — IMPLEMENTATION: `v6_preopen` paper sleeve — 2026-08-13

**For the engineering agent on Ireland (`/opt/tvrust`).** Strategy rationale + frozen
pre-registration live in
[TV_AGENT_SPEC_TVRUST_V6_PREOPEN_2026_08_13.md](TV_AGENT_SPEC_TVRUST_V6_PREOPEN_2026_08_13.md)
— read it first; this doc is the build plan. PAPER ONLY: no live submit path, no creds,
no interaction with `ladder_live.rs`.

**One-line summary of what you're building:** a maker sleeve that quotes BOTH tokens of
each btc updown window ONLY BEFORE the window opens (band 0.30–0.49, deadband requote),
cancels everything at `T_open − 2s`, holds all fills to chainlink settlement, and emits
a `v6_summary` per window. Two sleeves: `poly_v6_preopen_btc_5m`, `poly_v6_preopen_btc_15m`.

---

## 0. Ground rules (house invariants — violating any of these is a defect)

1. Base ladder arms (`v3`, `v31_*`, `v4_*`, `v5_*`) and their pre-registrations are
   BYTE-UNTOUCHED. New code paths only activate under `TV_V6_PREOPEN_ENABLED` (default
   false → not spawned, zero diff in behavior).
2. All thresholds in §3 are FROZEN — copy them into code as defaults verbatim; no
   "improvements" to band/caps/lead without a new spec.
3. Fill model: reuse the POST-EPOCH honest queue primitives (`SideSim::apply_maker_fill`
   with queue-consume both branches, `depth_at_ge`, floored `clip_shares`). Do NOT write
   a new fill model.
4. Paper sizing uses the venue floors exactly like live would (5 sh min, $1.00 notional
   with the `×(1+1e-9)` pad — already in `clip_shares`).
5. `cargo test` green + clippy clean before deploy; deploy = on-box build + restart
   `tv-rust-engine`; verify flags-off → zero new sleeves in the boot log.

---

## 1. Where the code goes

Recommended shape: a new **mode** on the existing ladder machinery (same pattern as
`grid_mode`/`coc_enabled`), NOT a new crate:

- `crates/tv-engine/src/loops/poly_ladder.rs`
  - `LadderConfig`: add `preopen_mode: bool` + the v6 knobs (§3). Add a builder
    `pub fn v6_preopen_variant(&self, tf, sleeve_id) -> Self` that: sets
    `preopen_mode=true`, disables `rcg_enabled`, `coc_enabled`, `grid_mode`, backstop
    (`backstop_tail_s` path must not run), pair gate (`pair_max_sum` NOT applied — see
    §2.3), and sets the v6 band/caps from env.
  - The window lifecycle, mirrors, racer, warmup gate, settle/outcome fetch, and event
    sink are REUSED as-is.
- `crates/tv-engine/src/main.rs` (beside the ladder spawn block ~line 598-712):
  spawn two instances when `TV_V6_PREOPEN_ENABLED`:
  `base.v6_preopen_variant("5m","poly_v6_preopen_btc_5m")` and
  `("15m","poly_v6_preopen_btc_15m")`, each via `spawn_ladder_instance` with its OWN
  isolated mirrors (same as every ladder sleeve; racer per current defaults).
- No DB migration: events are jsonb into `trading.events` via the existing sink.

## 2. Behavior deltas vs the v3 ladder loop (the actual work)

### 2.1 Quoting phase gate
- Quoting (requote + `apply_prints` fills) is active ONLY while
  `now < slot_start − TV_V6_CANCEL_LEAD_S`.
- At the boundary: emit `v6_cancel_at_open {cancelled_sh_up, cancelled_sh_dn}`, clear
  both `SideSim` resting quotes, and from then on the window takes NO fills. REV A: the
  fill gate must test the **PRINT's exchange timestamp**, not the drain wall-clock —
  `print.ts_ms < (slot_start − lead) × 1000` — otherwise a delayed drain misclassifies
  boundary prints in both directions. **Write a test that a print stamped 1s after the
  boundary produces zero fill even when drained before the boundary, and vice versa.**
- Windows must be quoted as early as the discovery horizon allows. Check how far ahead
  the gamma discovery builds future windows for each tf (the 5m loop currently tracks
  ~6 future slots; `placement_offset_s=−3600`). For 15m, if the horizon is < 30 min,
  extend the tracked-future-windows count for v6 instances via config — queue position
  is the moat, earlier = better. Log `first_quote_offset_s = slot_start − first_quote_ts`
  per window.

### 2.2 Price rule (replaces the v3 depth-ticks rule in preopen mode) — REV A

```
placement:  if best_bid < BAND_LO  → NO quote (lotto band — do NOT bid above the book)
            else                   → place at min(best_bid, BAND_HI)
requote:    NEVER chase upward. If best_bid rises above resting → HOLD (deeper
            discount, queue position preserved).
            Requote DOWNWARD only when best_bid ≤ resting − DEADBAND_TICKS × tick
            (the book fell through us and we are alone ≥2 ticks above the market
            = adverse posture) → cancel, rejoin at min(best_bid, BAND_HI).
```

REV A fixes two defects in the original draft: (1) `clamp(best_bid, LO, HI)` would
have BID ABOVE THE ENTIRE BOOK when `best_bid < LO` (placing 0.30 into a 0.25 book —
the opposite of the no-lotto intent); (2) the old requote condition was vacuous
(`target ≤ BAND_HI` is always true post-clamp) and a 1-tick deadband is no deadband
(1 tick is the minimum possible move) — as written it would have requoted on every
move and never held a queue position. Deadband default is now **2 ticks** and only
applies DOWNWARD; upward moves never trigger a requote.

### 2.2b Queue model correction for pre-open books (MANDATORY)

`depth_at_ge` truncates at `QUEUE_DEPTH_LEVELS = 5`. In-window books are shallow, but
the PRE-OPEN books this sleeve trades against carry **40–50 resting levels / ~145k
shares** (measured live 2026-08-13). With the 5-level cap, `queue_ahead` is
undercounted by an order of magnitude → the sim would OVER-FILL and H2 (capacity)
would false-pass. In `preopen_mode`, compute `queue_ahead` over **ALL** levels
≥ price (uncapped variant of `depth_at_ge`; do not change the in-window ladder's
constant). This makes the v6 paper number conservative — the correct bias direction
for a capacity question.

### 2.3 No pair gate, independent sides
- Both sides quote independently to `TV_V6_SIDE_CAP_USD` each. `pair_max_sum` /
  `gate_capped` logic is bypassed in preopen mode (both-side fills at sum ≈0.94 are the
  best case, not a risk to gate). GLT/q-imbalance cap also bypassed; the ONLY caps are
  side/day USD.
- On fill: refill the clip (existing re-enter-at-tail behavior) until side cap.

### 2.4 Settlement
- No backstop, no rcg, no market-sell of residual, no COC. Hold-to-settle via the
  existing outcome fetch (`outcome_source: gamma_chainlink`), then emit the summary.

### 2.5 Events
- Per fill: `v6_fill {slug, side, px, sh, s_to_open (negative), best_bid_at_fill,
  queue_ahead_at_place, book_age_ms}`.
- Per window at settle: `v6_summary {spec_rev: "v6.0-revA", slug, tf, slot,
  filled_up_sh/usd/vwap, filled_dn_sh/usd/vwap, implied_pair_sh, cancelled_at_open_sh,
  first_quote_offset_s, fills_hist_minute: {-10..-1 bucket usd}, winner, settle_pnl_usd,
  ev_per_share (= win_indicator − vwap, share-weighted across sides)}`. The `spec_rev`
  field is mandatory on `v6_fill` too — any future config change bumps it, so the
  verdict query can prove it ran on one config.
- **The verdict queries are part of the pre-registration — freeze them now** (drop in
  `docs/` beside this spec as `v6_verdict.sql`): H1 = per-window `ev_per_share`
  share-weighted mean AND its 95% CI **clustered by window** (each window is ONE
  observation — fills inside a window share the same winner and are perfectly
  correlated; per-fill CIs would overstate n by ~30×); H2 = filled sh/week; H3 = H1
  split by sample halves.
- Keep emitting the standard `ladder_tick`-family telemetry so ops tooling works.

## 3. Env (all new; defaults = frozen values)

```
TV_V6_PREOPEN_ENABLED        false
TV_V6_BAND_HI                0.49
TV_V6_BAND_LO                0.30
TV_V6_CLIP_USD               3.0
TV_V6_SIDE_CAP_USD           15.0
TV_V6_DAY_CAP_USD            600.0
TV_V6_CANCEL_LEAD_S          2
TV_V6_REQUOTE_DEADBAND_TICKS 2        # REV A: was 1 — 1 tick is the minimum move, i.e. no deadband
TV_V6_FUTURE_WINDOWS         8        # tracked-ahead count if the horizon needs extending
```

- `TV_V6_DAY_CAP_USD` resets at 00:00 UTC and must persist across restarts (DB-backed,
  keyed on UTC date — same requirement as the live day-notional meter, do not repeat
  that bug in paper accounting).
- For 15m with `FUTURE_WINDOWS=8` (2h ahead): gamma may return empty for windows not
  yet created — handle as "not yet, retry next discovery pass", not as an error.

## 4. Tests (minimum set; follow the existing `#[cfg(test)]` style in poly_ladder.rs)

1. `v6_variant_isolates_knobs` — builder disables rcg/coc/grid/backstop/pair-gate, sets
   band/caps (mirror `v31_variant_config_isolates_variant_knobs`).
2. `v6_no_fills_after_cancel_boundary` — print at `slot_start − lead + 1s` fills 0.
3. `v6_cancel_emits_and_clears` — resting on both sides at boundary → event carries both
   sizes, `resting_price=None` after.
4. `v6_band_placement` — best_bid 0.55 → quote at 0.49 (behind the book = discount
   posture); best_bid 0.25 → **no quote placed at all** (never bid above the book).
5. `v6_never_chase_up_requote_down` — best_bid rises 0.47→0.52 → NO requote (hold
   0.47, queue kept); best_bid falls to resting−1 tick → NO requote (deadband 2);
   falls to resting−2 ticks → requote down to join.
5b. `v6_preopen_queue_uncapped` — 20-level book, 1,000 sh at prices ≥ our bid →
   `queue_ahead = 1,000` (NOT the top-5 truncation).
6. `v6_side_cap_stops_refill` — fills accumulate to cap, next refill suppressed.
7. `v6_fill_uses_floored_clip` — clip at px 0.30 = max(5, 3/0.30, 1/0.30·pad) = 10 sh.
8. `v6_summary_ev_math` — synthetic window: up fills 10 sh @0.45, up wins →
   `ev_per_share = 1−0.45 = +0.55`… (per the share-weighted definition; include a
   two-sided case).

## 5. Deploy + acceptance

1. Local: `cargo test` (workspace) + clippy. On-box build, restart, `NRestarts=0`.
2. Flags off: boot log identical roster (verify no v6 sleeves).
3. Enable `TV_V6_PREOPEN_ENABLED=true` (paper): boot log shows the 2 sleeves; within
   2h: `v6_fill` events with `s_to_open < 0` only; `v6_cancel_at_open` present for
   windows with unfilled quotes; ZERO fills with `s_to_open ≥ −TV_V6_CANCEL_LEAD_S`.
4. 24h check (write into STATUS.md — and note the box's STATUS.md is stale since
   Jun 16; start a dated section): windows tracked/day ≈ 288 (5m) + 96 (15m),
   fill-rate, share-weighted `(WR − vwap)` running number.
5. Then hands off: the verdict is the strategy spec's §3 (n ≥ 2,000 or 21d). No tuning.

## 6. Also fix while you're in there (separate commits, pre-approved)

- `TV_POLY_TICK_RECORD_ENABLED` is **false again** (was true Aug 5 with 567MB taped;
  the Aug-12 mrcut deploy likely reverted the env). Re-enable + find and fix whatever
  reverted it (check `/etc/tv/tvrust.env.bak-*` sequence). Separate commit.
- Emit `placement_lag_s` (place_time − market_create_time) in the ladder telemetry —
  1-line metric from the latency audit, benefits v6 and the ladder equally.

## 7. Out of scope

Live submit for v6 (needs the standing blockers: breaker-counts-redemptions, capital
≥ $300, capture-ratio gate). ETH sleeves. Any signal/momentum gating (proven
nonexistent in the reference wallet). Any change to v3/v5 arms or their verdicts.
