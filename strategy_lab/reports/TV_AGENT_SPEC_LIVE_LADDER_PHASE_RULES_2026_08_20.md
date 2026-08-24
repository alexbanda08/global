# TV_AGENT_SPEC — live ladder phase rules: kill the early cut, shrink the entry window — 2026-08-20

**For the engineering agent on Ireland (`/opt/tvrust`).** Changes to the LIVE btc-5m
ladder sleeve (`poly_ladder_btc_5m_v3_live` / current live config), derived from
same-window forensics of ALL our live money vs the reference wallets:
[OURS_VS_WALLETS_SAME_WINDOW_2026_08_18.md](OURS_VS_WALLETS_SAME_WINDOW_2026_08_18.md)
(round 1: 51 windows, Aug 4–18) and
[OURS_VS_WALLETS_ROUND2_2026_08_20.md](OURS_VS_WALLETS_ROUND2_2026_08_20.md)
(rounds 2–3: 18 windows, Aug 19 night + Aug 20 morning). Every number below is
cash-verified (identities exact to the cent; hold-EV reproduced two independent ways;
winners resolved 69/69 windows; open positions checked worthless).

---

## 0. The one-paragraph diagnosis

Across 69 live windows / $1,130 of buys, our net is **−$52.86** (r1 −$19.53, r2
−$23.76, r3 −$9.57). The forensics decompose it into exactly TWO defects, both now
measured on two independent samples each:

1. **Resting entry bids left alive after the first minute fill only when their side is
   collapsing.** Fill-timing edge, share-weighted: 0–60s **positive in 2 of 3 rounds**
   (+4.25¢, +20.35¢/sh; r3 small-n negative); every bucket beyond 120s **negative in
   3 of 3 rounds** (−28¢, −48¢, −55¢/sh). Round 1's late bucket alone was −$69.8.
2. **The early residual cut sells recovering winners at the bottom of the first dip.**
   Sell-policy effect: r1 +$13.82 (cuts fired late, median +91s — protective), r2
   **−$19.46** (sold 135 winning-side sh @ 0.379, median cut at **+32s**), r3
   **−$32.57** (sold 78 winning sh @ 0.391, median **+54s**). Cumulative −$38.21.
   In rounds 2+3 gross entries made **+$18.71** and the sells alone turned that into
   **−$33.33 cash**.

The entries themselves are FIXED as of the Aug-20 morning session: +5.54¢/share gross,
pairing ratio 2.69, competitive with PBot-5 (+6.52¢) on the same windows. The two
rules below are what stands between the current config and its first green session.

Context that motivates the direction (not required for implementation): on OUR OWN
windows the reference wallets did — PBot-6 +11.15¢ and +24.03¢/sh (pre-open maker,
zero in-window quoting), b945 +4.42¢/+14.95¢ (late = pair completion only, never
naked). Nobody profitable rests naked entry bids late in a 5m window, and nobody
profitable sells residual before ~T+90s (the references never sell at all).

---

## 1. Change A — phase-gate the residual cut (the defect)

**Rule: no residual sell of any kind before `T_open + TV_LADDER_CUT_MIN_AGE_S`
(default 90s), regardless of the 30s inventory-age trigger.** The age-based recycle
cut (30s) currently fires at median +32s/+54s into the window and sold 213 winning
shares at ~0.38–0.39 across the last two sessions — it realizes the bottom of the
first intra-window dip, which mean-reverts. Cuts that fired ≥ ~90s were protective
(+$68 saved on losers in round 2).

- Implementation: the cut condition becomes `inventory_age ≥ 30s AND
  window_elapsed ≥ TV_LADDER_CUT_MIN_AGE_S`. Env knob, default **90**, live sleeve
  only (paper arms with their own pre-registrations stay untouched).
- The T−tail backstop (end-of-window flatten) is NOT this rule and stays as is.
- If simpler and faster to ship: `TV_LADDER_RECYCLE_ENABLED=false` outright is an
  acceptable interim — measured across all 69 windows the recycle is net **−$38.21**;
  its best observed contribution (+$13.82, round 1) came entirely from the late cuts
  this rule preserves.

## 2. Change B — shrink the naked-entry window (the structural bleed)

**Rule: entry bids (quotes that can create NEW one-sided exposure) rest only during
`[T_open, T_open + TV_LADDER_ENTRY_WINDOW_S]` (default 60s). After that, cancel
resting entry bids; the only permitted resting buy is a PAIR-COMPLETING bid** (its
fill reduces |up−dn| imbalance) **subject to the existing `pair_max_sum` gate.**

- This encodes what 3-of-3 rounds show: quotes alive past ~2 minutes fill at 5–50¢
  negative expectation; quotes in the first minute are the only reliably positive
  entry flow we have.
- It is also the live-money confirmation of `v5_latepair`'s design — implement it as
  the same phase machinery if that's cheapest, but on the LIVE sleeve with these env
  knobs and WITHOUT waiting for the paper verdict (the live tape already gave one).
- Cancel path: batch `DELETE /orders` at the boundary (1 RTT), same pattern as the
  boundary cancel in the v6 spec.

## 3. Change C — session-config discipline (the regression)

The Aug-19-night session ran with pairing ratio **0.32** (buys 543 sh, one-sided);
the Aug-20-morning session ran at **2.69** with positive entries. Something in the
config differed between those two arms/sessions.

- Diff `/etc/tv/tvrust.env` against its `.bak-*` sequence for Aug 19–20; identify
  what changed (suspects: pair gate, side caps, clip form, GLT).
- **Freeze the Aug-20-morning configuration as the baseline** and record it in a
  dated STATUS.md section. Every future live session change gets one line there
  (the ledger-epoch lesson: an undeclared config change voids session comparisons).

## 4. Telemetry (small, needed to judge the next sessions)

Add to the live sleeve's events (jsonb, no migration):
- on every fill: `window_elapsed_s` (fill ts − slot_start) — the forensics had to
  reconstruct this from data-api timestamps.
- on every residual cut: `cut_age_s`, `window_elapsed_s`, `side`, `px` — so the
  phase-gate's effect is measurable without off-box reconstruction.
- per window summary: `entry_window_fills_sh` vs `late_fills_sh`, `pair_ratio`.

## 5. Pre-registered readout for the next live cycle (FROZEN)

Judge on the next **n ≥ 30 traded live windows** (~2–3 sessions at current cadence):

- **P1:** share-weighted entry edge (WR − vwap) of fills inside the entry window
  ≥ +2¢/share (rounds 1–3 pooled first-minute evidence supports it).
- **P2:** zero residual sells with `window_elapsed < 90s` (mechanical compliance).
- **P3:** net cash ≥ $0 across the cycle. Not a statistical claim at n=30 — a sanity
  gate: with entries at +5.5¢ and the early cut gone, a red cycle means something NEW
  is wrong and triggers forensics round 4, not tuning.

Success metric queries: same method as rounds 1–3 (data-api reconstruction, cash
identity check, winners via redemption matching) — scripts
`wallet_hunt/_ours_vs_wallets_2026_08_18.py` / `_round2_2026_08_20.py` are the
reference implementation.

## 6. Explicitly out of scope

- No changes to entry pricing/depth/clip of the Aug-20-morning config (it measured
  +5.54¢/share — do not touch what just started working).
- No changes to any paper arm or its pre-registration (`v5_latepair`, `v5_tc`,
  `v6_preopen` proceed on their own specs).
- No re-tuning of `pair_max_sum`, bands, or caps under this spec.
- The standing engineering items remain open and separate: tick recorder re-enabled
  (regressed again), breaker counting redemptions, capital top-up.

## 7. Evidence annex (for the implementer's conviction, all cash-verified)

| session (operator local, UTC−3) | windows | net | entry edge | sell effect |
|---|---:|---:|---:|---:|
| Aug 4 | 9 | +$17.12 | — | — |
| Aug 5 | 22 | −$2.54 | — | — |
| Aug 13 | 13 | −$9.53 | −1.56¢/sh | (+, cuts late) |
| Aug 17 | 3 | −$12.44 | −11.5¢ pooled w/ 18th | — |
| Aug 18 | 4 | −$12.14 | " | — |
| Aug 19 night | 13 | −$23.76 | −0.79¢/sh | **−$19.46** (cuts @ +32s) |
| Aug 20 morning | 5 | −$9.57 | **+5.54¢/sh** | **−$32.57** (cuts @ +54s) |
| **total** | **69** | **−$52.86** | | cumulative **−$38.21** |

Fill-timing edge (share-weighted, ¢/share) — the basis for Change B:

| bucket | r1 (51w) | r2 (13w) | r3 (5w) |
|---|---:|---:|---:|
| 0–60s | +4.25 | +20.35 | −26.1 (n=3 legs) |
| 60–120s | +0.37 (60–180) | −22.95 | +17.2 |
| >120–180s | −28.37 (>180) | −47.79 | −54.8 (n=1) |

First minute: positive 2/3 (pooled strongly positive). Beyond 120s: negative 3/3.
