# Making the ladder paper-sim trustworthy — diagnosis + fix program — 2026-08-05

Target: close the measured live↔paper gap (**1.3× windows, 2.0× shares, +5.4¢ pair sum**)
in `crates/tv-engine/src/loops/poly_ladder.rs`. Evidence:
[TVRUST_LIVE_VS_SHADOW_HEADTOHEAD_2026_08_05.md](TVRUST_LIVE_VS_SHADOW_HEADTOHEAD_2026_08_05.md).

---

## 1. What the sim actually does

```rust
// resting at p; queue_ahead = depth_at_ge(bids, p)  [top-5 levels, ALL size at ≥ p]
fn apply_maker_fill(&mut self, tp, ts, clip_usd) {
    if tp > p { return 0.0 }                                  // seller never reached us
    let avail = if (tp - p).abs() <= EPS {
        let a = (ts - queue_ahead).max(0.0);                  // same level: queue first
        queue_ahead = (queue_ahead - ts).max(0.0); a
    } else {
        ts                                                    // ← tp < p: ENTIRE print, ZERO queue
    };
    let fill = clip_remaining.min(avail).min(budget_sh);
    filled_usd += fill * p;                                   // always our own limit
    if clip_remaining <= EPS {                                // depleted → new clip
        clip_remaining = clip_shares(p, clip_usd);
        queue_ahead    = depth_at_price;                      // ← back of the FULL book
    }
}

fn apply_prints(...) {
    if p.side != Sell { continue }
    if (tp - mid).abs() > 0.15 { rejected += 1; continue }     // ← outlier gate
    ...
}
```

Constants: `QUEUE_DEPTH_LEVELS = 5`, `placement_offset_s = -3600`, `clip_shares = clip_usd / price`
(**no minimum**), `pair_max_sum = 0.99`, `quote_depth_ticks = 2`.

---

## 2. Five defects, each mapped to a measured divergence

### D1 — the ±0.15 mid-outlier gate discards exactly the sweeps → *price gap*
`apply_prints` drops any print more than 15¢ from mid. Over 9 days that is **1,371–1,507
prints per arm, in 504–574 of ~2,300 windows (≈22% of all windows)**. A sweep *is* a print far
from mid. The sim therefore learns the book from calm ticks only and never books the fills that
happen while the market is running through the ladder. This is the most likely single source
of the 5.4¢ pair-sum gap, and the cheapest thing to change.

### D2 — the `tp < p` branch has no queue **and no level-walk** → *volume gap*
When a print lands below our bid, the sim hands the clip the whole print with zero queue — but
it caps at `clip_remaining` (one clip) and never models the sweep consuming *our other rungs
at higher levels first*. Reality: one sweep fills every rung you have resting, top-down, and
the higher rungs are the expensive ones. That is precisely "2× the shares at a worse average
price" — one defect producing both observed symptoms.

### D3 — re-entry resets `queue_ahead` to the full displayed depth → *window + volume gap*
After a clip depletes, the sim puts you behind the entire book again. But the ladder places at
`placement_offset_s = −3600` (1h early) — the documented queue-position moat, the whole reason
early placement exists. The sim throws that advantage away on every refill, throttling fills
live does not experience. Systematic under-fill: sim traded 9–10 of the 13 windows live traded.

### D4 — `depth_at_ge` truncates at 5 levels and counts *all* size at ≥ p as ahead of you
Two errors: the top-5 cap under-counts the queue in deep books, while treating every share at
better prices as "ahead" over-counts it for an order that has been resting for an hour. They
do not cancel; they just make the queue estimate uninterpretable.

### D5 — **the sim has no venue minimum; live is floored at 5 shares** → *price gap, NEW*
`clip_shares(p, clip) = clip/p`, unbounded. The live path floors every order at the venue's
**5-share minimum** (`TV_POLY_LADDER_LIVE_MIN_SHARES=5`) and the **$1.00 notional minimum**.

At the live clip of **$2**, the floor binds for every price above **0.40** — i.e. **always on
the expensive leg**. Verified against the fill tape, exactly:

| fill price | live shares | `$2/p` | floored? |
|---:|---:|---:|---|
| 0.84, 0.83, 0.79, 0.72, 0.70, 0.67, 0.65, 0.63, 0.55, 0.44 | **5.00** | 2.4–4.5 | **yes** |
| 0.33 | 6.06 | 6.06 | no |
| 0.22 | 9.09 | 9.09 | no |
| 0.18 | 11.11 | 11.11 | no |
| 0.13 | 15.38 | 15.38 | no |

Above 0.40 the clip is **constant in shares, not in dollars**, so expensive fills get the same
size as cheap ones and the leg's share-weighted vwap is dragged up. Worked on episode 4's DOWN
leg (13 fills, all 5.00 sh): realized vwap **0.7192**; the same 13 fills at a true $2 clip give
36.76 sh for $26.00 = **0.7073**. **The floor alone cost 1.19¢** — about 22% of the 5.4¢ gap.

Paper never reproduces this because at its **$5** clip the 5-share floor never binds
(`5/p > 5` for all `p < 1`). **Paper and live are not running the same sizing function.**

---

## 3. The blocker: you cannot fit any of this today

```
TV_POLY_TICK_RECORD_ENABLED=false
TV_POLY_TICK_RECORD_DIR=/var/lib/tv/rust_ticks     (empty)
```

**The tick recorder is off and there is no tape on disk.** The recorder was built and tested in
the 2026-06-16 moat-infra work (`tv-feeds/src/tick_recorder.rs`, non-blocking, bounded channel,
drops+counts, rotates) and has simply never been enabled. Without a recorded book+print tape
there is nothing to replay, so any change to the fill model is another guess — which is how
`v32_cheap` died.

---

## 4. Fix program

### Phase 0 — turn the recorder on. Blocking, ~free, do it now.
`TV_POLY_TICK_RECORD_ENABLED=true`. Additionally record the **live order lifecycle** —
place / requote / cancel / fill, each with the book snapshot at that instant — so every live
fill carries its own book context. You already have **156 labelled live fills**; what is
missing is the book state they happened in. A few days of tape is the whole input to Phase 1.

### Phase 1 — replay harness + an honest loss function
Replay the tape through `SideSim` and score against real fills on **three observables, not PnL**:

| target | current gap |
|---|---|
| per-window fill indicator (did it trade at all?) | 1.3× |
| per-window shares filled | 2.0× |
| per-window realized vwap / pair sum | +5.4¢ |

PnL is the wrong loss function — it is variance-dominated (residual σ ≈ 3.4/window swamps
everything). These three are directly observable, well-powered at n≈150 fills, and each maps
to a specific defect.

### Phase 2 — the changes, pre-registered, ONE AT A TIME against the harness
Ordered by expected effect ÷ cost:

1. **D5 — put the venue minimums in the paper path.** `clip_shares` → `max(5.0, clip_usd/p)`,
   plus the $1.00 notional floor, plus tick rounding. Pure arithmetic, no calibration, and it
   makes paper and live simulate the same executable set. **Do this first** — it is the only
   change with a known-correct answer.
2. **D1 — replace the ±0.15 price-distance gate with a staleness gate.** The intent was to
   drop bad ticks; the implementation drops real sweeps. Gate on `book_age_ms` / feed
   freshness (`data_quality::is_stale` already exists), not on distance from mid.
3. **D2 — walk the sweep across levels.** On `tp < p`, consume from best bid downward,
   filling each resting rung in price order rather than handing one clip the whole print.
   This is the change that should close the volume and price gaps together.
4. **D3/D4 — queue position from placement age.** Initialise `queue_ahead` as a *fraction* of
   `depth_at_price`, fitted from the tape, and do not reset to full depth on refill. This is
   the only parameter that must be *calibrated* rather than derived — so it goes last, and it
   gets a frozen pre-registration like any other fitted quantity.

### Phase 3 — re-rank the arms
Every number in the bake-off came out of this sim. After 1–4, re-run all six arms on the
replayed tape and re-rank. **Expect the ordering to move**: `c2` (2× clip) and `d1` (depth-1)
are by construction the two most sensitive to the sizing floor and the queue model, and they
are currently ranked 2nd and 6th.

---

## 5. What you can do this week without waiting for tape

**Offline cross-check against canonical L25.** You have 156 labelled live fills and 10Hz
full-depth book history locally (`data/v4/canonical/orderbook_l25/btc.parquet`). Replay the 19
live windows offline and ask whether the offline engine reproduces the real fills. That tests
the model without any new collection.

Two caveats, both known: canonical L25 has **price↔size swapped on odd levels** (level 0 and
even levels are clean — see `project_l25_level_corruption`), and the collector **discards the
`price_change` delta stream** (`project_offline_feed_blind_to_edge`), so it is ~1–2 Hz
effective. Good enough for a coarse yes/no on D1/D2/D5; not good enough to fit D3/D4.

**And ship D5 immediately** — it needs no tape, no fit, and no judgement call. It is simply a
missing constraint.

---

## 6. One consequence worth stating plainly

Raising the live clip **$2 → $5** removes the 5-share floor bind entirely (`5/p > 5` always),
putting live back onto paper's sizing curve and eliminating defect D5 on the live side without
touching a line of code. That is already step 1 of the cap-lift plan — it now has a second,
independent, quantified justification worth ~1.2¢ of the 5.4¢ pair-sum gap.
