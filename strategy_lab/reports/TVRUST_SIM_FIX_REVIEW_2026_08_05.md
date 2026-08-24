# Review of the other agent's sim fix — 2026-08-05 19:30 UTC

Changed on the box (rebuilt + restarted 19:05): `loops/poly_ladder.rs` (fill model),
`ladder_live.rs` (min-notional sizing), new `tv-venues/clients/poly_merge.rs` +
`bin/tv-merge.rs` (CTF merge executor, dry-run gated, not wired), `strat_chart.rs`.

## Verdict: the central fix is correct and well-executed. But it's half of the job, and the two "ship tonight" safety items did not ship.

---

## 1. What he did right

### The `tp < p` branch removal — correct, evidenced, tested
Old rule: a print *below* our resting bid handed us the **entire print with zero queue**
("we were higher priority"). New rule: at or below our level, the print must first consume
`queue_ahead_sh` (everyone at better prices + earlier at our level); we get `max(0, ts − Q)`.

His falsification is the right kind: replayed `btc-updown-5m-1785950100` — our DN quote
rested at 0.170, **11¢ behind the entire book** (best bid 0.28–0.31), and the old sim booked
**13.88 of the 14 shares that traded (99% capture)**, closing at pvs 0.6016 for +$6.41.
Live, resting the same quotes against the real book, has never paired under 0.91. A sweep
fills 0.28, 0.27 … 0.18 first and leaves us nothing. Unit test added
(`a_sweep_below_our_bid_fills_the_book_ahead_of_us_first`) encoding exactly this.

This is defect D2 from [TVRUST_SIM_FIDELITY_DIAGNOSIS_2026_08_05.md](TVRUST_SIM_FIDELITY_DIAGNOSIS_2026_08_05.md)
— the single biggest lie in the model, and the reason paper's cheap tail existed. (My
proposed fix was a level-walk across rungs; his queue-consumption is the correct form for
base v3, which rests ONE clip per side, not a grid. His version is right, mine was
over-engineered for this path.)

### Endgame outlier-gate exemption (A3) — sensible partial fix for D1
The ±0.15 mid-distance gate (which was discarding sweeps) is now disabled in the final
60s (5m) / 120s (15m) per window — "0/1 runs are REAL moves." Mid-window sweeps are still
rejected, but under the new queue rule a dropped print now errs *conservative* (it also
fails to consume queue), so the residual bias direction is safe.

### Min-notional sizing — fixed in two stages (CORRECTED per operator, verified)
The first fix (round shares up to `$1/price`) did **not** kill the skip: the sizing targeted
exactly $1.00 and the float round-trip landed one ulp under — **32 further skips 16:00–18:38,
prices 0.04–0.18, every one `notional_usd: 0.9999999999999999`**, all on the cheap side.
The 19:05 build closed it properly: sizing padded `× (1.0 + 1e-9)` AND the guard compares
against `POLY_MIN_ORDER_USD - 1e-9`. Zero skips post-19:05. Venue side verified too:
`polymarket.rs:64` converts to 6-decimal USDC with `RoundingStrategy::ToZero`, so the padded
order truncates to exactly `1_000_000` micro-USDC = $1.000000 ≥ venue min. The 1e-9 pad sits
~7 orders of magnitude above f64 round-trip error, so the truncation cannot fall to $0.999999.
Sound, but epsilon-dependent — the decimal-exact form (ceil shares to venue 2dp precision,
5.5555… → 5.56 → $1.0008) would remove the epsilon coupling entirely. Low-priority cleanup.

### Merge executor — safe, orthogonal
Dry-run gated (`--yes-move-my-assets`, two independent eth_call proofs), not wired into the
engine, and honestly documented: merge buys only *speed* (venue already auto-redeems at
median 47s). No concerns.

---

## 2. What's wrong or missing

### (a) The two "tonight, unconditional" items did NOT ship
- **The breaker is still realized-only.** `daily_loss_tripped(day_realized_pnl_usd, cap)`;
  held inventory "marked at cost (not counted)" per its own doc comment. This is the exact
  blind spot he himself named — down ~$11 with the breaker reading 0.0 — and it is still
  there. The doc's justification ("the T−tail backstop flattens residual each window,
  converting held→realized") is **known-false**: the backstop was blocked twice by the $1
  venue minimum. The one automated loss-bound is still blind. Ship it before anything else.
- **`TV_POLY_TICK_RECORD_ENABLED` is still `false`**, dir empty. The queue model he just
  made load-bearing (see (c)) cannot be calibrated without the tape.

### (b) Every historical paper number is now void — and this hasn't been declared
The entire ledger — v3's +$6,624 / 34 days, the 9-day bake-off table, **c2rcg's
pre-registration pass (Δ+0.640, t=8.87)** — was measured under the fill model he just
proved manufactures fills. The paired A/B deltas are *less* contaminated (both sides shared
the model), but any arm whose edge concentrates in the cheap tail (c2, d1, c2rcg) benefited
most from the generous branch, so even the *ranking* is suspect. Required: declare a ledger
epoch at 2026-08-05 19:05; every pre-registration re-based on post-fix data only; the
c2rcg promotion case re-earned from scratch.

### (c) Probable overcorrection — the sim may now starve
The old generous branch made `queue_ahead` mostly irrelevant. Now it is the binding
constraint — which promotes two known defects into the model itself:
- `requote()` resets `queue_ahead` to full `depth_at_ge` on **every price change**, and a
  refilled clip re-enters behind the **full** displayed depth (D3). The ladder requotes
  constantly, so the sim perpetually sits at the back of the book — throwing away the
  queue priority that `placement_offset_s = −3600` exists to buy, and that live genuinely
  has.
- `depth_at_ge` truncates at 5 levels and counts all better-priced size as ahead (D4).

First 27 minutes post-fix: **5 completed windows, ~1 of 24 arm-windows traded** (vs ~70%
fill rate pre-fix). Live, when it was armed, traded 13 of 17. Too early to be conclusive —
but if the fill rate stays down there at 24h, the sim has swung from over-filling to
starving, and it will now *underestimate* live instead of overestimating it. A model that's
wrong in the safe direction is better than one wrong in the flattering direction — but it
still can't rank arms.

### (d) D5 is only half-fixed
The live side now has rational sizing (share floor + $1 floor). Paper's `clip_shares` is
still bare `clip_usd / price` — no floors. Paper and live still run different sizing
functions, so the twin comparison is still not apples-to-apples at cheap prices.

---

## 3. What to do now (order)

1. **Breaker on unrealized** — residual marked at 0, not mid/cost. It's ~20 lines and it's
   the only automated thing between a bad day and a worse one. Non-negotiable before any re-arm.
2. **Recorder ON.** The queue model is now the load-bearing wall of every paper number;
   it is currently a guess with two known biases and zero calibration data.
3. **Declare the ledger epoch.** All dashboards/reports split pre/post 2026-08-05 19:05.
   All standing pre-registrations (c2rcg combo, rcg-band, d1×rcg bench ideas) void and
   re-frozen against post-fix data.
4. **Watch the post-fix fill rate for 24–48h.** If traded-window rate settles far below
   live's observed ~76%, calibrate queue initialization from the live fill tape (fit the
   initial `queue_ahead` as a fraction of displayed depth, by placement age) — that is the
   D3/D4 fix, and it's a *fitted* parameter, so it gets its own frozen pre-registration.
5. **Floor paper's `clip_shares`** to match live's sizing (5 sh + $1). One line, closes D5.

Then, and only then, re-open the promotion question — on post-epoch data.
