# Round 8 — the guard is LIVE and verified; the loss shape changed; what turns it profitable — 2026-08-23

Same canonical method as rounds 1–7 (cash truth via data-api, winners from
Chainlink resolutions, redemption-lag respected — zero pending redemptions at
fetch time). Covers the 4 sessions since r7: **28 windows, all btc-5m**.
Pro comparison built from the COMPLETE per-market tape of our 28 windows
(deep-offset fetch, 1 window capped at 8k rows) + full 2-day wallet pulls
(b27 463,909 fills; b945 15,562; PBots).

## 1. The sessions

| session | n | cash | worst max\|up−dn\| | paired sh | verdict |
|---|---:|---:|---:|---:|---|
| S1 Aug 21 18h | 6 | −$1.83 | **15.0** | 55/145 | pre-fix (the 20-vs-5 hole session) |
| S2 Aug 22 14h | 4 | −$4.12 | **15.0** | 60/140 | fix NOT yet live (one 3-clip window, 14:05) |
| S3 Aug 23 03h | 10 | −$4.60 | **5.0** | 85/200 | ✅ compliant |
| S4 Aug 23 13h | 8 | −$6.93 | **5.0** | 75/175 | ✅ compliant |

**The 1-clip guard is enforcing in production: all 18 windows of Aug 23 show
running max imbalance of EXACTLY 5.0 shares.** Window 13:10-style (25×0) is now
impossible — the campaign's oldest defect is closed and verified on live tape.
(S2 shows the fix went live between Aug 22 14h and Aug 23 03h.)

## 2. The loss shape CHANGED — decomposition of the compliant 18 windows

Hold-basis: **pairs locked +$8.54** (pvs 0.87–0.99, avg ~0.94 — the pairing
machine works) · **naked residuals −$14.73** · cuts/salvage net −$5.34 (two
≥90s cuts sold sides that later flipped and won — checked fill-by-fill: those
sells were ex-ante ≈fair given P(flip) at the moment, i.e. bad luck, not the
old early-cut disease; leave Change A alone). Cash −$11.53.

The bleed is no longer runaway accumulation — it is the **single naked clip
that dies**: 7 of 18 windows ended one-sided (−$0.6…−$2.2 each). That is
exactly the residual mode the displacement study priced: a loser-side clip
bought above its physics fair value.

## 3. The pros on OUR 28 windows (in-window buys, hold-basis, complete tape)

| session | ours | b27 | b945 | PBot-6 | PBot-5 | PBot-3 |
|---|---:|---:|---:|---:|---:|---:|
| S1 (hole) | −8.85 | −888.87 | **+91.59** | −51.90 | −430.91 | **+344.69** |
| S2 | +1.11 | +136.56 | — | — | −10.28 | +22.23 |
| S3 | **+3.46** | −1,422.95 | — | −21.28 | −1.24 | −59.33 |
| S4 | −9.65 | −541.63 | — | — | +3.17 | +28.13 |
| **total** | **−13.93** | **−2,716.89** | +91.59 | −73.18 | −439.26 | **+335.72** |

Context that matters before touching anything: **this was a losing regime for
almost the entire professional table.** b27 — the wallet that had been green in
every prior round — lost ~$2.7k hold-basis on our windows at 86–96% pairing;
b945's own main 15m book ran **−$436 on $141k deployed (−0.14¢/sh, pairing
92%)** over the same two days; PBot-5 and PBot-6's post-open flow were negative;
PBot-2 is still silent (since Aug 18). The only winner was **PBot-3** (+$336,
pairing only 16–26%): the open-discount collector profile, a different trade.
Our −$11.53 across the compliant sessions is IN LINE with the field, at 1/300th
of b27's size. Do not over-react to two hard days.

Notable: our S3 was **positive on entries (+$3.46 hold-basis, +1.73/100sh)** —
better than b27 (−2.01/100sh) on the same windows. The guarded entry engine is
already table-competitive; the gap to profit is the naked-clip residual and the
tiny locked margins.

## 4. What turns it profitable (evidence-ranked)

1. **Deploy the fair-value cap on NAKED loser-side quotes — amended scope.**
   Round-8 data exposed a defect in the REV B `v3_faircap` spec: capping ALL
   loser-side quotes also blocks pair COMPLETIONS whose sum still locks profit
   (the pair criterion is the SUM, not the leg — b27's economics). Amended rule:
   **the fair cap (`bid ≤ P_flip(elapsed,|d|) + 2¢`, table in
   `ladder_sim_2026_08_21/flip_surface.json`) applies ONLY when the fill would
   NOT reduce |up−dn|** (naked entries); completions stay governed by
   `pair_max_sum`. Replay evidence: full 131-window history guard-only −$39.33 →
   **+$2.27** (+$41.6); compliant-18 subsample −$6.19 → −$0.61 (+$5.6) — the
   naked-only scope blocks just ~8 sh/window and keeps the pairing machinery
   fully intact. Small enough to go LIVE directly with a pre-registered
   readout (n≥30 windows: naked-loser residual per window ≤ half of r8's, net ≥
   guard-only baseline).
2. **Do NOT tighten the completion sum gate** (tested: +$18.84 on the 18
   windows is flip-luck; −$8.9 on the full history — the same small-n trap this
   campaign has hit twice).
3. **Leave Change A cuts as deployed.** The −$5.34 sell effect this round was
   two ex-ante-fair cuts that got flipped on; the displacement-restriction
   variant recovers only +$2.43 (noise).
4. **After faircap validates: the 15m expansion is where the profit lives.**
   At current 5m size, perfect execution ≈ +$0.3–0.5/window — the pairing game
   pays at b945's scale and timeframe (87% of his capital, 3× the window to
   complete pairs). Same rules scaled (entry 180s, cut 270s, guard identical,
   15m fair table already banked). Needs the ≥$300 top-up.
5. **Regime note for expectations:** in chop-heavy stretches even the best
   pairing books bleed (b27 −$2.7k, b945 −$436 these two days). The
   pre-registered readouts should span sessions, not stop on one red day.

## 5. Verification

Guard compliance measured from the real fill sequence per window (running max
imbalance); cash identities exact (buys−sells−redeems, 106 redemption rows, no
pending settlements at fetch); pro tables from complete per-market tape
(deep-offset refetch of all 17 truncated windows; 1 window still capped at 8k
rows — earliest prints of that one window missing, ours unaffected); hold-basis
decomposition (S3+S4 = −$6.19) reconciles with the session cash (−$11.53) via
the measured sell ledger (−$5.34) to the cent. b945 15m book from his full
2-day pull (13,534 15m fills) against fresh 15m resolutions (192 windows).
Scripts: `ladder_sim_2026_08_21/{round8_ours.py, fetch_window_trades.py,
fetch_refs_topup.py, round8_window_trades.json}`.
