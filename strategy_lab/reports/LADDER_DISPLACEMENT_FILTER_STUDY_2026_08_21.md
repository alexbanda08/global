# Displacement-from-strike: flip probability physics, what the pros do, and whether we filter/exit — 2026-08-21 (REV B, audited)

**REV B 2026-08-21 evening — full quant/engineering re-audit requested by the
operator. Two defects found and fixed, one conclusion REVERSED, one upgraded.
Deltas vs REV A: (1) the early-exit result was inflated by a look-ahead bug in
the replay (sold shares at T+E that were only bought later) — corrected, the
early exit is now NEGATIVE in the current-config era and is RETRACTED. (2) The
"displacement filter adds nothing" conclusion was driven by +$132 of measurable
sample LUCK; the expected-value analysis, an out-of-sample split, and the
professional benchmark all now support a PRICING form of the filter (fair-value
cap on the loser-side bid) as a pre-registered arm. Full audit trail in §6.**

Operator question: when price is $100–150 (or X) from the target with X time
left, the flip chance is tiny and the heavy side trades at a big discount —
should we (a) filter entries on the losing side and/or (b) exit the ~99%-dead
side early? Compared against the professional wallets and ALL our live fills
including today's afternoon session (109 windows).

**Answers up front (audited):**
1. **The physics confirms the intuition, quantified in §1** (3 min left +
   |d|≥$100 → P(flip) ≈ 10%; 1 min left + |d|≥$75 → ≤1%; before ~90s elapsed
   even $50+ still flips 13–21%).
2. **The discounted side is a value trap:** the market prices it +2–5pp ABOVE
   its true flip probability, and OUR fills are worse than that — we paid $285
   for loser-side exposure (|d|≥$25) whose physics fair value is $159 →
   **expected −$127 over 2 weeks; it only realized +$6 because 4 of 19 such
   windows happened to flip (window-level p = 0.12–0.32 = ordinary luck).**
3. **The pros run the filter as PRICING, not as a ban.** PBot-6/2/3 barely
   trade displaced windows at all (3–5% of in-window buy USD at |d|≥$50 vs our
   14%); PBot-5 trades them heavily (47% of its USD) but 94% on the LEADER
   side; b27/b945 quote both sides at every displacement (≈50/50 by shares)
   **with the loser leg priced AT fair — b945's loser-leg edge is ≈0¢/sh in
   every displacement bucket.** And in 535k raw fill rows, **no professional
   wallet sold a single share** — the "exit the 99% loser" move does not exist
   among the winners.
4. **Recommendation (changed from REV A):** no early exit (the REV A +$1–3
   claim was the replay bug); no blunt entry ban; instead **cap the loser-side
   bid at its physics fair value +2¢** (the b945 posture). On our 109 real
   windows this turns guard1's −$39.95 into **+$14.50** (era: +$1.42 →
   +$11.56), validated out-of-sample in both week-halves (+$47.7 / +$9.7),
   bootstrap CI95 [−6, +111] — strong but not conclusive at this sample size →
   **pre-registered paper arm first** (it blocks ~70% of loser-side flow; that
   is a strategy change, not a tweak).

---

## 1. The physics: TRUE P(outcome flips | |displacement|, time elapsed)

From Binance 1s closes (displacement vs price at slot open) + Chainlink winners,
**5,058 btc-5m windows / 1,704 btc-15m windows, Aug 4–21**:

**btc-updown-5m** (cell = P(flip), n windows):

| elapsed (t_rem) | $10–25 | $25–50 | $50–75 | $75–100 | $100–150 | $150–250 |
|---|---|---|---|---|---|---|
| 60s (4:00) | 33.7% | 24.1% | 20.8% | 25.4% | 12.0% | 15.4% |
| 120s (3:00) | 25.5% | 17.0% | 12.5% | 13.4% | **10.3%** | 10.5% |
| 180s (2:00) | 20.1% | 10.3% | 7.1% | 7.7% | 4.1% | 2.2% |
| 240s (1:00) | 12.3% | 5.3% | 2.3% | 1.1% | **0.0%** | 0.0% |
| 270s (0:30) | 8.0% | 2.2% | 2.1% | 0.8% | 0.0% | 0.0% |

(15m table analogous, stretched ~3×; both banked in `flip_surface.json`.)
Caveats: $0–10 bucket is basis-ambiguous (Binance-vs-Chainlink offset ~+$60,
constant intra-window, cancels in differencing; sign-agreement 89.5% with
disagreements in sub-$20-move windows). Verification: two cells independently
recounted (2.3↔2.7%, 10.3↔12.2%); **aggregate cross-check: valuing our entire
real fill book at these probabilities predicts −$70.40 vs −$72.61 realized** —
the surface prices our book to within $2 over 109 windows.

## 2. The market is NOT giving the discount away

Market price of the LOSING-side token (last tape print) vs true flip
probability, `implied / true` (pp), 5m:

| elapsed | $25–50 | $50–75 | $75–100 | $100–150 |
|---|---|---|---|---|
| 120s | 19.9 / 16.8 | 15.6 / 12.8 | 16.2 / 14.9 | 14.1 / 10.7 |
| 180s | 13.3 / 10.5 | 9.5 / 7.4 | 9.2 / 7.7 | 7.0 / 4.3 |
| 240s | 7.2 / 5.4 | 4.8 / 2.3 | 3.3 / 1.1 | 2.5 / 0.0 |

Consistently **+2 to +5pp above fair** (typical cell n≈400–1300 → ~2–3σ per
cell, same sign in essentially every mid/late displaced cell). Our own realized
loser-side fills are worse than the static gap because touch-following bids fill
DURING the collapse: our |d|≥$25 loser buys paid vwap 0.30 vs fair 0.167.

## 3. What the professionals actually do (fills vs displacement at fill time)

Share of buy volume (SHARES) landing on the losing side, by |d| at fill, 5m:

| \|d\| at fill | ours | b27 | b945 | PBot-6 | PBot-2 | PBot-3 | PBot-5 |
|---|---|---|---|---|---|---|---|
| $0–10 | 53% | 49% | 47% | 46% | 45% | 41% | 67% |
| $25–50 | **76%** | 50% | 41% | 42% | 34% | 26% | 55% |
| $50–75 | **86%** | 49% | 46% | 30% | 21% | 12% | 29% |
| $75–100 | **90%** | 50% | 52% | 17% | 7% | 1% | 28% |
| $100–150 | **100%** | 50% | 55% | **0%** | 7% | **0%** | 6% |

In-window buy USD at |d|≥$50 (exact, audited): ours 13.9% — **79.5% of it on
the loser side**; PBot-6/2/3: 3.3/4.8/4.3% (they are simply absent when
displaced); PBot-5: 47.0% — but only 5.9% of that USD on the loser (it fades
INTO the leader late); b27: 27.0% (balanced by shares; loser legs are cheap, so
21.9% of the USD).

Three professional postures, none of which is "sell the loser":
- **PBots 6/2/3:** entry at/before the open, never chase → displaced windows
  barely exist for them (our Change B + guard already encode this posture).
- **PBot-5:** when displaced, buy the LEADER (a different strategy, not ours).
- **b27/b945:** quote both sides always, but price the far leg at fair —
  **b945's loser-leg edge per displacement bucket: +0.5, +0.4, +1.2, +0.7,
  +3.1, −1.7, +1.0¢/sh (≈0 everywhere)** — his ladder simply never overpays
  the collapsing side. b27 accepts −2..−6¢/sh on far loser legs as pairing cost.
- **Sells: ZERO** across 535,473 raw btc-updown fill rows for all five pro
  wallets (verified on raw records, not filtered views).
- Us: the only participant whose loser share RISES with displacement (53→100%)
  — the signature of touch-following bids that only the collapsing side fills.

## 4. Counterfactuals on OUR 109 real windows (chronological replay, corrected)

| policy | total$ (109w) | era (r5→today) |
|---|---:|---:|
| baseline hold | −72.61 | −58.40 |
| **guard1 (1-clip, yesterday's rule)** | −39.95 | +1.42 |
| F1 fixed-threshold ALONE (D=$50) | −93.68 | −47.46 |
| guard1 + F1 D=$50 | −39.92 | −2.20 |
| guard1 + early-exit \|d\|≥$50 @≥90s (CORRECTED) | −29.13 | **−6.89** |
| **guard1 + fair-cap (loser bid ≤ fair+2¢)** | **+14.50** | **+11.56** |

- **Early exit: RETRACTED.** REV A's +$1–3 era gain was a replay bug (the exit
  scan ran on the window's FINAL book — it sold shares at T+90 that were bought
  at T+200 = look-ahead, ~$9 of fake proceeds). The corrected chronological
  replay puts every exit variant BELOW guard1 in the current-config era
  (−0.6…−11.8). Physics agrees it is ~EV-neutral at best (sell at implied ≈
  fair+2–5pp minus haircut and adverse selection), and no professional sells.
  Change A's existing cut stays exactly as deployed — its live salvage was
  measured on real cash and is not this mechanism.
- **F1 fixed threshold: underpowered, not adopted.** Realized delta vs guard1 =
  +$0.02, bootstrap CI95 [−14.8, +13.5] (only 17 windows differ). Expected
  value says blocking is worth ≥ +$16/2wk (blocked fills cost > fair, and maker
  adverse selection makes fair an UPPER bound of their value), but the sample
  cannot confirm it and the fair-cap below dominates it.
- **The luck decomposition that reversed REV A's reading:** our loser-side buys
  at |d|≥$25: paid $285.30, physics fair $158.78 → **E[PnL] = −$126.52**;
  realized +$5.92. The gap (+$132) is 4 flips in 19 windows (p = 0.12–0.32 at
  the correct window level; REV A's clip-level test was a clustering error).
  Any replay judged on this sample alone under-values displacement filtering.
- **Fair-cap = the deployable form.** Rule: a loser-side bid may not exceed
  `P_flip(elapsed, |d|) + 2¢` (table lookup, `flip_surface.json`). Realized:
  −39.95 → **+14.50** (era +1.42 → **+11.56**); helped 50 windows (+$138),
  hurt 41 (−$84), max single-window damage −$7.70; bootstrap CI95 [−6.1,
  +110.8]. **Out-of-sample: surface built on week 1 → applied to week 2 fills:
  guard1 −36.97 → +10.78; reverse split: −2.98 → +6.76** — positive both
  directions with no shared estimation window. It blocks 3,492 of 4,839 sh of
  loser-side flow (~70%) → this is b945's pricing posture, not a tweak; the
  EV-valued version of this table (+$112–301) is NOT decision-grade (leader-leg
  fills are dip-selected within cells; §6) — the realized + OOS numbers above
  are the honest ones.
- Today's afternoon session (6 windows): baseline −$10.60, guard1 −$6.96 —
  the guard is still not deployed and still the binding fix.

## 5. Recommendations (priority order, for the TV agent)

1. **Ship the 1-clip guard first (unchanged,
   [LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md](LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md) §5).**
   Every displacement pathology routes through naked accumulation; today's
   windows are still bleeding through it.
2. **Do NOT implement an early exit** of the displaced heavy side. REV A's
   suggestion is retracted (replay bug); corrected numbers are negative in the
   current config; no professional does it; Change A's cut stays as-is.
3. **Do NOT implement a blunt displacement ban** (F1): underpowered on our
   sample and dominated by item 4.
4. **NEW pre-registered PAPER arm — `v3_faircap`: cap the loser-side quote at
   physics fair value.** Concretely: when this side is displaced-against
   (Binance spot vs window open, feed already on the box), the resting bid ≤
   `P_flip(elapsed_bucket, |d|_bucket) + 0.02`, floor 0.01; leader-side quoting
   unchanged; guard + Change A/B unchanged. Table = static lookup baked from
   `ladder_sim_2026_08_21/flip_surface.json` (9 elapsed × 8 displacement
   buckets, both tfs; refresh monthly). Pre-registration: n≥200 paper windows,
   success = paper arm beats the base v3 twin on net AND loser-leg edge
   (WR−vwap) ≥ −1¢/sh (b945 benchmark ≈ 0). Expected effect at current size ≈
   +$0.5/window; it also mechanically ends the "86–100% of displaced buys on
   the loser" signature.
5. The 15m expansion inherits the same rule from the 15m surface (thresholds
   stretch ~3×; b945 — the model wallet there — already prices this way).

## 6. Audit & verification log (REV B)

- **F2 look-ahead bug (found, fixed, quantified):** v1 exit replay used the
  final book at the trigger time — corrected chronological replay
  (`filter_replay_v2.py`) moves exit D=50/E=120 from −19.41 → −28.33 total and
  era +2.72 → −8.24 (sign flip = the retraction in §5.2).
- **Luck test corrected:** REV A tested the 75–100$ bucket at clip level
  (wrongly significant, 1e-4); the correct unit is the WINDOW (fills within a
  window share one outcome): 4/19 windows flipped, p = 0.12–0.32.
- **EV framework cross-validated:** surface-priced expectation of the full real
  book −$70.40 vs realized −$72.61 (Δ<$2/109w). Loser-side EV −$126.52 vs
  realized +$5.92 → luck isolated and quantified.
- **Adverse-selection bound stated:** maker fills are dip-selected WITHIN
  (elapsed, |d|) cells, so cell-fair OVERVALUES leader-leg fills (this is why
  the EV-valued fair-cap rows of +$112–301 are rejected as evidence) and
  UNDERVALUES nothing on the loser side (blocking conclusions are lower
  bounds). Realized+OOS numbers used for all adopted claims.
- **Timestamp integrity:** data-api fill ts vs public tape (unique-candidate
  matching, n=156): physical cluster at +2s (Polygon confirmation); large
  offsets are tape gaps (collector lag windows), not real lag → displacement
  at api-ts is valid within ±2s ≈ ±$2 of |d|.
- **Data hygiene:** tape and 1s klines deduped + re-sorted after the top-up
  (0 duplicate trades — the feared overlap did not exist; 20 duplicate kline
  seconds removed); 5 newest windows use Binance-sign winners (flagged, all
  displaced >$20 at close).
- **Zero-pro-sells verified on raw records:** 535,473 BUY rows, 0 SELL rows
  across b27/b945/PBot-2/3/5/6 (btc-updown, Aug 4+).
- **Volume claims recomputed exactly in USD** (REV A's "PBots 3–4% vs ours 20%"
  corrected to: ours 13.9% USD at |d|≥$50 with 79.5% loser-side; PBot-5
  separated out as leader-side).
- **OOS split:** week-1 surface → week-2 fills and reverse, both positive
  (§4); bootstrap CIs window-resampled, 5k draws.
- Scripts: `strategy_lab/ladder_sim_2026_08_21/{flip_surface.py,
  wallet_displacement.py, filter_replay.py (v1, superseded),
  filter_replay_v2.py (audited), flip_surface.json, implied_surface.json}`.
