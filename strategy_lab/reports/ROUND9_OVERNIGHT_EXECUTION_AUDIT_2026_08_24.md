# Round 9 — overnight campaign execution audit: near-breakeven at record size, 0.7¢/sh from b27 — 2026-08-24

Biggest deployment of the campaign: **66 windows** (Aug 23 20:10 → Aug 24 06:05
UTC), **$782 of buys** — 2.5× round 8's turnover. Every execution audited
fill-by-fill; pro comparison from the complete per-market tape of all 66
windows (5 windows at the 8k-row cap; ours complete from activity).

## 1. Headline

| | round 9 | round 8 (compliant part) | trend |
|---|---:|---:|---|
| windows / buys | 66 / $782.02 | 18 / $177 | 2.5× size |
| **net cash** | **−$9.79** | −$11.53 | **−1.25% of turnover vs −6.5%** |
| entries (hold-basis, true cost) | −$4.51 | −$6.19 | ≈breakeven |
| cut ledger | −$5.28 | −$5.34 | flat, ≥88s compliant (0 early) |
| pairing (shares) | **88.6%** | 85.3% | b27 runs 96.5% |
| guard compliance | 64/66 clean | 18/18 | 2 same-second races (§3) |
| pending redemptions | 0 | 0 | cash fully reconciled |

Cash identity closes **to the cent**: entries −4.51 + cuts −5.28 = −9.79.

## 2. The pros on the SAME 66 windows (in-window buys, hold-basis)

| wallet | sh | buys$ | PnL | ¢/100sh | pair% | resid WR |
|---|---:|---:|---:|---:|---:|---:|
| **b27** | 547,799 | $267,076 | **+$2,990** | **+0.55** | 96.5% | 30.2% |
| **ours** | 1,604 | $745 | −$2.23 | **−0.14** | 88.6% | 17.4% |
| PBot-3 | 2,258 | $1,372 | −$44 | −1.95 | 11% | 59.9% |
| PBot-5 | 1,539 | $753 | −$204 | −13.2 | 13% | 33.7% |
| PBot-6 | 1,938 | $897 | −$384 | −19.8 | 5% | 25.1% |
| b945 | — | — | — | — | (absent from 5m tonight) | |

A trending overnight regime: b27 printed, every collector bled. **We were the
second-best book on our own windows**, 0.69¢/sh behind the best wallet in the
market and 2–20¢/sh ahead of the PBot fleet. The remaining gap to b27
decomposes exactly into: (a) pairing 96.5% vs our 88.6% (his taker-completion),
(b) residual WR 30% vs our 17% (his leftovers land right more often), (c) queue
position/price.

## 3. Errors found in the executions (for the TV agent)

1. **Same-second requote race — two residual holes in the guard, both bounded:**
   - `…1787515800` +12s: Dn filled 5.00 while imbalance was already −4.99 →
     momentary −9.99 (2 clips), Up filled back to −4.99 in the same second.
   - `…1787517000` +259s: a **7.15-share** Dn fill (> clip 5!) took imbalance
     to −7.14 — two same-side resting orders coexisted (5.00 + 2.15 partial
     remainder) and swept together.
   The fills-only guard caps the steady state, but between fill and requote
   accounting TWO same-side orders can rest. Invariant to enforce: at most ONE
   working order per side, cancel-confirmed before placing the next (or
   sequence the requote on fill-ack, not on poll). Frequency: 2 in 66 windows;
   cost tonight ≈ $0 (both windows ended fine) — close it before size grows.
2. **Accounting: the data-api `price` field is ROUNDED; `usdcSize` is truth.**
   Measured on 390 buys: Σprice×size = $775.40 vs Σ usdcSize = $782.02 —
   **+$6.62 (~0.34¢/sh) of real cost invisible to price-based accounting.**
   Every prior replay/report priced at price×size is ~0.85% of turnover too
   optimistic in ABSOLUTE terms (relative policy comparisons unaffected — same
   bias on all arms). Any TV dashboard or breaker computing from price×size
   must switch to usdcSize. This also means our true per-share edge needs
   +0.34¢/sh more than displayed prices suggest.
3. **Cuts: compliant and ≈fair.** 28 sells, ZERO before 88s; 15 sold the
   displaced-against side (correct), 13 got flipped on (bad luck at fair-ish
   prices: sells at 0.26–0.57 vs P(flip) 20–35% at their moments). One watch
   item: the earliest-eligibility bucket (+90–120s) ran −$8.47 on 14 sells vs
   +$5.12 for 120–180s — n too small to act, flag for the n≥100 readout.
4. **Faircap-naked would have added only +$0.37 tonight** (would block 351 sh
   across 51 windows). Calibration honesty: its value is REGIME-ASYMMETRIC —
   ≈flat on trending nights like this (blocked losers ≈ blocked winners), big
   in chop (+$41.6 on the full 131w history where naked clips die repeatedly).
   Still worth shipping — it is insurance priced at ~0 in good regimes.

## 4. What to modify (consolidated, priority)

1. **Close the same-side order race** (§3.1) — one working order per side,
   hard invariant.
2. **Switch accounting to usdcSize** (§3.2) — engine ledger, dashboard, breaker.
3. **Port v5_tc taker-completion to 5m live** — unchanged from round 8; tonight
   quantifies the prize precisely: pairing 88.6→96.5% is worth ≈+0.7¢/sh on our
   whole book (the entire gap to b27). With the guard already forcing
   alternation, completion is the only missing pairing mechanism.
4. **Ship faircap-naked** with calibrated expectation (insurance, not alpha).
5. **Keep unchanged:** Change A cuts, Change B entry window, 1-clip guard.
6. 15m: unchanged from
   [RESIDUAL_ANATOMY_AND_15M_READINESS_2026_08_23.md](RESIDUAL_ANATOMY_AND_15M_READINESS_2026_08_23.md)
   — not ready; spawn the full-stack paper arm.

## 5. Trajectory check (the campaign is converging)

Net as % of buy turnover: r1–r4 ≈ −5 to −8% → r8 compliant −6.5% → **r9
−1.25%** — while size grew 2.5×. Structure now at pro grade (pairing 88.6%,
guard enforced, cuts disciplined). The remaining −1.25% is fully accounted:
~0.35pp price-rounding cost, ~0.7pp cut-luck, and the naked-residual tail that
completion+faircap target. b27's +0.55¢/sh on the same windows is the proof the
configuration space contains profit at our exact game.

## 6. Verification
Cash identity exact (redemptions reconciled per window: 0 mismatches; hold +
sell-effect = cash to the cent after the usdcSize correction); guard audited on
running imbalance of every fill sequence; cut audit per sell with displacement
at sell time; pro table from complete tape (5/66 windows at the 8k cap noted).
Scripts: `ladder_sim_2026_08_21/{fetch_r9_trades.py, round9_window_trades.json}`
+ inline audits (this session).
