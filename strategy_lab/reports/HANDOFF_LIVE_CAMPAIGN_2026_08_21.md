# HANDOFF — live campaign state, what is wrong, what differs from the pros — 2026-08-21

> **UPDATE 2026-08-23 — READ
> [ROUND8_GUARD_LIVE_VS_PROS_2026_08_23.md](ROUND8_GUARD_LIVE_VS_PROS_2026_08_23.md) FIRST.**
> The 1-clip guard is LIVE and VERIFIED (18/18 Aug-23 windows at exactly 5.0 sh
> max imbalance; item 2 below is DONE). Campaign now 131 windows / ≈−$107. The
> loss shape changed: pairs lock +$8.5, single naked clips bleed −$14.7. Next
> action = `v3_faircap` scoped to NAKED loser-side quotes only (completions
> exempt — round 8 amended the REV B spec; +$41.6 on full-history replay).
> Regime note: b27 lost $2.7k and b945's 15m book ran −$436 on the same two
> days — judge readouts across sessions, not single red days.
>
> **UPDATE 2026-08-23 (2) — residual anatomy + 15m readiness:
> [RESIDUAL_ANATOMY_AND_15M_READINESS_2026_08_23.md](RESIDUAL_ANATOMY_AND_15M_READINESS_2026_08_23.md).**
> Pros NEVER sell residuals: pairing engines starve them to 6–8% of book and eat
> the loss (pairs out-earn 1.2–1.3×); collectors hold residuals that WIN
> (WR ≥ price). Our guard-era structure is right (85% paired) but residual EV is
> −26.8¢/sh (2.4× worse than b27). Next two levers: (1) `v3_faircap`
> naked-only, (2) port v5_tc taker-completion to the 5m live sleeve (pairing
> 0.13→0.79 on 15m paper — the b27 move). 15m is NOT live-ready: all 10 paper
> arms are outlier-carried ex-top2 (v5_tc +$35 → −$5); spawn one new arm with
> the full validated stack (guard+180s/270s+faircap+tc), promotion gate n≥250 /
> ex-top2 t>+1; also CONFIRM state of allowlisted `poly_ladder_btc_15m_tc_live`
> (0 real fills, paper twin ex-top2 −$39). b945 15m runs a fixed daily schedule
> — off 07:00–14:00 UTC — not window selection.
>
> **UPDATE 2026-08-24 — round 9 (overnight, 66 windows, $782 — record size):
> [ROUND9_OVERNIGHT_EXECUTION_AUDIT_2026_08_24.md](ROUND9_OVERNIGHT_EXECUTION_AUDIT_2026_08_24.md).**
> Net −$9.79 = −1.25% of turnover (was −6.5% in r8): near-breakeven, 2nd-best
> book on our own windows (b27 +0.55¢/sh, us −0.14, all PBots negative).
> NEW defects for TV agent: (1) same-second requote RACE — two same-side
> resting orders can coexist between fill and requote (one 9.99-sh imbalance,
> one 7.15-sh oversized fill); enforce ONE working order per side,
> cancel-confirmed. (2) data-api `price` is rounded — `usdcSize` is truth
> (+$6.62/390 fills ≈ 0.34¢/sh hidden cost); switch ledger/breaker accounting
> to usdcSize. Then: port v5_tc taker-completion (pairing 88.6→96.5% = the
> whole 0.7¢/sh gap to b27) + faircap-naked (regime-asymmetric insurance:
> +$0.37 tonight, +$41.6 in chop).

Consolidates rounds 1–7 of the same-window forensics. Incorporates
[ROUND6_LATE_ENTRIES_BACK_2026_08_21.md](ROUND6_LATE_ENTRIES_BACK_2026_08_21.md) (the
previous report) and adds round 7 (today 13:10–13:50 UTC, 4 windows). All numbers
cash-verified; round-7 initially misread by −$5.52 due to redemption lag at fetch
time — corrected (see §5, measurement pitfall).

---

## 1. Campaign scoreboard (all live money, per session)

| round | when (UTC) | windows | net | entry edge ¢/sh | sell effect | compliance |
|---|---|---:|---:|---:|---:|---|
| 1 | Aug 4–18 | 51 | −$19.53 | −1.86 | +$13.82 | pre-spec |
| 2 | Aug 19 night | 13 | −$23.76 | −0.79 | −$19.46 | pre-spec |
| 3 | Aug 20 morn | 5 | −$9.57 | +5.54 | −$32.57 | pre-spec |
| 4 | Aug 20 14:10 | 5 | −$11.33 | +5.20 | −$28.48 | **A violated (9 cuts <90s)** |
| 5 | Aug 20 20:15 | 14 | **+$6.12** | −0.35 | **+$8.24** | A ✅ · B untested |
| 6 | Aug 21 01:00 | 11 | −$18.69 | −6.38 | **+$35.45** | A ✅ · **B violated (187 sh naked >120s)** |
| 7 | Aug 21 13:10 | 4 | −$13.21 | ~−7 (n=4) | +$7.57 | A ✅ · **B ~✅ (3/38 fills >60s)** |
| **total** | | **103** | **−$89.97** | | | |

## 2. What is FIXED and verified (do not touch)

1. **Change A — the cut gate (no residual sell before T+90s): SOLVED.** Three
   consecutive compliant sessions; the sell-effect series flipped exactly on
   deployment: −$19.5 → −$32.6 → −$28.5 → **+$8.2 → +$35.5 → +$7.6**. Cuts now fire
   at +93…+201s and consistently salvage losers. Cumulative value of the fix ≈ $40+/
   session swing.
2. **First-minute entries: the profitable core.** The 0–60s bucket is positive in 5
   of 7 rounds (up to +20¢/sh); pooled comfortably positive. The Aug-20-morning
   entry config remains good.
3. **Change B (entry window ≤60s) appears deployed between rounds 6 and 7**: fills
   after T+60s went 39% (r4) → 31% (r5) → r6's fatal 187 sh → **8% (3/38) in r7**.
   Needs the `entry`/`completion` fill tag to confirm, but the behavior moved.

## 3. What went WRONG, precisely, in the last two sessions

**Round 6 (−$18.69): Change B was not yet enforced.** Three legs, 187 naked shares
filled after T+120 on collapsing sides, WR 0%, −$70.0 — more than the session loss
(counterfactual without them ≈ +$51). This defect is now presumed fixed (see r7
compliance) but MUST be confirmed via fill tags, not inferred — round 5 already
fooled us once by winning that bucket on luck.

**Round 7 (−$13.21): a DIFFERENT failure mode — the naked first leg.** Timing was
clean; the loss came from one-sidedness:

| window | what happened |
|---|---|
| 13:10 | bought **25 sh Up, ZERO Down** — pure directional bet, lost, cut at +93s recovered $2.70 → −$6.78 |
| 13:15 | 30 Up vs 10 Dn (3:1 tilt), Up lost → −$3.30 |
| 13:40 | 5 Up @0.70 vs 20 Dn @0.26, Dn lost → −$3.65 |
| 13:45 | **35/40 paired at sum ≈0.93 → +$0.52** — the one window run as designed |

Session pairing ratio 0.77 (vs 2.0–2.7 in the good sessions; b27 runs 3.8). At n=4
windows the dollars are noise, but the PATTERN is the round-1 finding never yet
implemented: **"ban unhedged windows"**. We still allow a side to accumulate clips
with no opposite-side fill and (apparently) no resting opposite quote surviving.
Every window that paired ≥50% across the campaign has been roughly breakeven-or-
better; nearly every heavy loss is a naked or 3:1 window.

### 3b. Micro-tape of the last window (13:45) — the defect in one fill

Operator flagged this window ("locked ~$2, then bought the bad side late, lost ~$1").
The tape confirms the economics with one correction: **no sell occurred** — the
locked profit was diluted by a LATE BUY, not a sale:

```
+3s..+67s  builds the pair to 35 Up / 35 Dn
+67s       PAIR COMPLETE 35/35, locked +$1.96          ← should be DONE here
+202s      BUY 5 Down @ 0.29 (the side losing at that moment)
settle     Up wins, redeem $35; the 5 extra Dn die     → −$1.45
NET        +$0.52 instead of ≈ +$1.96
```

The +202s fill is illegal under BOTH already-specified rules: it is a naked entry
after T+60s (Change B), and it cannot be a completion because at 35/35 ANY buy
INCREASES |up−dn|. Meanwhile the +63/+67s fills (Up 25→35 vs Dn 35) were
legitimate completions that raised locked from $1.09 → $1.96 — proof that the
correct rule is "post-60s buys only if they reduce imbalance", NOT a blanket
T+60 kill. This window is the acceptance test for the fix: rule applied, it nets
≈ +$1.96; rule absent, +$0.52. (It is also one of round-7's "3/38 fills >60s" —
so Change B's enforcement is incomplete: the resting quote survived to +202s.)

## 4. What still DIFFERS from the professional wallets

| dimension | us (r5–r7) | the winning refs | gap |
|---|---|---|---|
| cut timing | ✅ +90s+, salvage | they never sell (or complete instead) | closed |
| entry timing | ✅ ~90% ≤60s | b27 whole-window sum-gated; PBot-6 pre-open | closed enough |
| **pair completion** | **0.25–2.0, unstable; naked first legs persist** | b27 3.8 · b945-15m 5.5 (taker-completes) | **THE remaining gap** |
| tf | 5m only | b945: 87% of capital in 15m; our game is his game | queued (capital) |
| scale | $70–375/session | b27 did $1,588 profit on our r6 windows alone | later |

b27 remains the only reference positive on our windows in essentially every round
(+2.2/−1.3/+0.5/+2.6/+5.1/−1.4¢ — 5 of 6); it is the working proof that our market
+ our timeframe is winnable with pairing discipline + completion.

## 5. Corrections for the TV agent (priority order)

1. **Confirm Change B enforcement** with evidence: add the `entry|completion` tag to
   every fill event (spec'd in ROUND6 report §4) and show one session's fills with
   0 naked entries >60s. Inference from data-api is what let r5 mask r6's defect.
2. **Implement the unhedged-window guard (round-1 recommendation, still missing):**
   a side may hold at most ONE clip until the opposite side has ≥1 fill OR a live
   resting opposite quote within the sum gate; if by T+60s the opposite side has
   zero fills, stop adding to the heavy side entirely (the light-side completion
   path stays active). Window 13:10 (25 sh one-sided) must be impossible.
   **VALIDATED OFFLINE 2026-08-21** — see
   [LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md](LADDER_GUARD_SIM_AND_VOL_FILTER_2026_08_21.md):
   replay on our 103 real windows shows the exact rule (`quote side X only while
   X_sh − Y_sh < clip_sh`, whole window) flips the current-config entry book
   −$47.80 → +$8.38 over r5–r7 (delta +$56.18, CI95 [+13.0,+97.7], positive in
   all 3 sessions); opposite side returns in 77% of windows (median 13s), so the
   "only 5 shares" fear does not materialize (65% volume retained). Cap must be
   exactly 1 clip — 2 clips tested worthless. NOTE: `glt_cap_q=4.0` in
   `poly_ladder.rs` already intends this and live bypasses it — root-cause that
   first. A volatility filter is NOT needed alongside it (the guard absorbs the
   vol sensitivity; ρ drops −0.24 → −0.05); vol throttle pre-registered only.
2b. **Displacement study 2026-08-21 — REV B (AUDITED — supersedes the afternoon
   version) — see
   [LADDER_DISPLACEMENT_FILTER_STUDY_2026_08_21.md](LADDER_DISPLACEMENT_FILTER_STUDY_2026_08_21.md):**
   flip-probability physics banked (3min left + |d|≥$100 → ~10% flip; 1min +
   $75 → ≤1%); the discounted loser side is OVERPRICED +2–5pp vs fair; NO pro
   ever sells (535k raw rows, 0 sells). AUDIT CORRECTIONS: (a) the earlier
   "sharpen Change-A cut with displacement trigger" advice is RETRACTED — it
   came from a look-ahead bug in the exit replay; corrected replay is NEGATIVE
   in the current era. Change A stays exactly as deployed. (b) Blunt
   displacement ban: not adopted (underpowered). (c) NEW pre-registered paper
   arm **`v3_faircap`**: loser-side resting bid capped at
   `P_flip(elapsed,|d|) + 2¢` (static table from
   `ladder_sim_2026_08_21/flip_surface.json`) — on our 109 real windows it
   turns guard1 −$39.95 into +$14.50 (era +$11.56), OOS-validated both
   week-halves; this is b945's measured pricing posture (loser-leg edge ≈0 in
   every bucket). Spec in the study §5.4.
3. **Redemption-lag rule for any accounting surface** (dashboard, breaker, reports):
   a window's PnL is UNDEFINED until ~2 min after slot_end; today's session first
   read −$18.73 vs true −$13.21 purely from redeem lag. The breaker/day-PnL must
   treat pending redemptions as +value, not as loss.
4. Then unchanged from previous handoffs: 15m expansion behind capital top-up
   (≥$300), phase rules scaled 60→180s / 90→270s; v6_preopen paper verdict;
   judge the campaign's P1–P3 pre-registration at n≥30 enforced windows (r5+r7
   give 18 compliant so far; net across compliant sessions +$6.12−$13.21 = −$7.09,
   dominated by r7's naked windows — which item 2 exists to remove).

## 6. Bottom line

Two of the three defects that produced −$90 over 103 windows are fixed and verified
(early cuts, late naked entries — pending tag confirmation). The remaining one is
the oldest finding in the campaign and has never been implemented: **never let a
window go one-sided past one clip.** The professional benchmark for our exact game
(b27) differs from us today in exactly that discipline — and in nothing else we can
measure.
