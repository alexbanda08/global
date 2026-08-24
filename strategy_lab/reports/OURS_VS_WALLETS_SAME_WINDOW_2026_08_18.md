# Our LIVE windows vs the reference wallets — same-window forensics — 2026-08-18

Source of truth: Polymarket data-api for OUR live funder `0x51a5f36def…dd96` (458 trades,
46 redeems, Aug 4 → Aug 18 14:27 UTC) — the SAME pipeline used for every reference
wallet, so all numbers are like-for-like. Scripts: `wallet_hunt/_ours_vs_wallets_2026_08_18.py`
+ canonical verification blocks (session transcript).

## 0. Verification (done BEFORE conclusions — all pass)

| check | result |
|---|---|
| cash identity: Σ(sells + redeems − buys) per window | **−$19.53, exact to the cent** across 51 windows |
| vs the hand-reconciled Aug-13 handoff (−$8.54, wallet 64→55.46) | my Aug-13 bucket −$9.53; ±$0.99 attribution difference (one redemption straddling the day boundary / partial-price settle); 0.13% of turnover — immaterial, flagged |
| hold-EV computed two independent ways (per-window counterfactual vs Σ leg edges) | both −$33.35 ✓ |
| winners resolved | 51/51 (own redemptions → one-sided-expiry rule → reference-wallet redemptions) |
| open positions now | 8, ALL current value $0.00 (settled losers) → totals are FINAL |
| unredeemed winning shares | 0.00 — no money stranded |
| earlier same-day drafts | two subset filters disagreed (+0.2¢ vs −0.9¢/sh); resolved by one canonical set — numbers below are the canonical ones |

## 1. Our five live sessions (51 windows, all btc-5m)

| session | windows | buys | sells | redeems | **net** |
|---|---:|---:|---:|---:|---:|
| Aug 4 | 9 | $156.48 | $2.16 | $171.44 | **+$17.12** |
| Aug 5 | 22 | $254.46 | $28.48 | $223.44 | −$2.54 |
| Aug 13 | 13 | $207.50 | $73.17 | $124.80 | −$9.53 |
| Aug 17 | 3 | $80.70 | $48.27 | $19.99 | −$12.44 |
| Aug 18 | 4 | $48.64 | $26.50 | $10.00 | −$12.14 |
| **total** | **51** | **$747.78** | **$178.59** | **$549.66** | **−$19.53** |

Decomposition: **gross entry quality −$33.35** (edge −1.86¢/share on 1,790 bought shares,
WR 39.9% at vwap 0.4177) **+ the sell/recycle discipline +$13.82** = −$19.53. The selling
policy is genuinely rescuing money (confirms the Aug-13 finding at full-sample scale);
the entries are what lose.

## 2. The wallets on OUR EXACT windows (same slugs)

| wallet | legs | shares | vwap | WR | **edge ¢/share** |
|---|---:|---:|---:|---:|---:|
| **PBot-6** (pre-open) | 49 | 16,095 | 0.4712 | 58.3% | **+11.15** |
| **b27** (velocity pairer) | 26 | 10,429 | 0.4992 | 53.0% | **+3.11** |
| PBot-2 | 78 | 8,384 | 0.5898 | 58.0% | −1.00 |
| PBot-3 | 42 | 2,916 | 0.6595 | 58.4% | −7.55 |
| b945 | 24 | 2,110 | 0.5430 | 45.0% | −9.27 |
| **us** | 87 | 1,790 | 0.4177 | 39.9% | **−1.86** |

Two professionals ALSO lost on our windows (b945 −9.27¢ on n=24 legs, PBot-3 −7.55¢) —
our sessions landed on genuinely hostile windows — but **PBot-6 and b27 made money on
those same windows anyway.** The discriminator is not the window; it is the method in it.

And the counter-intuitive price finding: **we pay LESS than the in-window bots on the
same side of the same window** (−9.5¢ vs PBot-2, −14.7¢ vs PBot-3, −3.7¢ vs PBot-6;
S1 price-swap: buying at their prices would have cost $94.86 MORE) — and still lose.
Cheapness is not edge: our fills are cheap BECAUSE they happen while the side collapses.

## 3. WHERE our −1.86¢ actually lives (canonical, share-weighted)

By fill timing (median leg offset into the window):

| when we got filled | legs | shares | vwap | WR | edge | **$ impact** |
|---|---:|---:|---:|---:|---:|---:|
| 0–60s | 54 | 791 | 0.4016 | 44.4% | **+4.25¢** | **+$33.6** |
| 60–180s | 26 | 753 | 0.4613 | 46.5% | +0.37¢ | +$2.8 |
| **>180s** | **7** | **246** | **0.3361** | **5.2%** | **−28.37¢** | **−$69.8** |

By session:

| | legs | sh | vwap | WR | edge | $ |
|---|---:|---:|---:|---:|---:|---:|
| Aug 4–5 | 52 | 961 | 0.4276 | 44.6% | +1.87¢ | +$17.9 |
| Aug 13 | 23 | 443 | 0.4679 | 45.2% | −1.56¢ | −$6.9 |
| **Aug 17–18** | 12 | 386 | 0.3354 | **22.0%** | **−11.50¢** | **−$44.4** |

**One failure mode explains the whole live loss: late-window fills on collapsing sides.**
Seven legs with median fill >180s into the 5m window, bought at 0.336, won 5.2% of the
time, −$69.8 — more than the entire net loss. The early fills (0–60s) are actually
POSITIVE (+4.25¢/share, +$33.6): our at-open quoting works. The Aug 17–18 sessions
concentrated the late-fill mode (WR 22%) and produced −$24.6 of net on tiny size.

## 4. What we do differently from the winners — itemized

| dimension | us | PBot-6 (+11¢ here) | b27 (+3¢ here) | b945 |
|---|---|---|---|---|
| when quoting | in-window, front-loaded, **still resting late** | **pre-open only** (fills −9s median on our windows) | whole window, flat | spread, mid-peak |
| late-window exposure | resting bids into collapses (−28¢/sh) | **zero** (all cancelled/filled by open) | completes pairs, sum-gated | taker-completes the pair at ~0.70 |
| pairing on our windows | 1.0–2.3 (post-fix — decent!) | 0.37 (doesn't need it) | 3.77 | 0.36 (these windows) |
| residual disposition | sell/recycle (**+$13.82 — keep it**) | hold 100% | hold + merge | hold 100% |
| price paid | cheapest of everyone | mid | mid | highest |

The gap to the winners is **not** price, not pairing rate (ours is now fine), not the
selling policy (ours adds money). It is a single behavior: **our quotes are still alive
in the last 2 minutes of 5m windows, where a resting bid only fills when its side is
dying.** That is precisely the defect `v5_latepair` (stop feeding after 90s) and the
open-cancel rule in `v6_preopen` were designed against — both now have live-money
confirmation, from our own tape.

## 5. Recommendations (in force order)

1. **Kill late-window quote exposure on the live sleeve now** — cancel resting bids at
   T+120s (5m) unless they complete a pair under the sum gate. This single rule, applied
   retroactively to our own 51 windows, turns −$19.53 into ≈ +$50 (remove the −$69.8
   bucket). That is a counterfactual, not a promise — but the bucket's WR of 5.2% at
   price 0.336 is not a tuning question, it is adverse selection in its purest measured
   form.
2. The **v6_preopen paper arm** is now doubly motivated: PBot-6 printed +11.15¢/share on
   OUR OWN windows while we did −1.86¢.
3. Keep the recycle/sell policy exactly as is (+$13.82 measured).
4. Session sizing: Aug 17–18 lost more than Aug 4–13 combined on a third of the volume —
   whatever config changed between the 13th and the 17th, review it against the >180s
   bucket before the next arm session.

## 6. Confidence statement

High confidence: cash identities exact; two independent computations agree on every
headline number; winners 51/51 resolved with three fallback methods; open positions
verified worthless (nothing pending). Medium confidence: the wallet comparisons on
shared windows (n = 24–78 legs per wallet — directionally solid, magnitudes ±3–5¢).
Known ±$0.99 day-boundary attribution difference vs the Aug-13 hand reconciliation.
The −$69.8 late-fill bucket is 7 legs — the MECHANISM (WR 5% at 0.34) is unambiguous,
but the dollar magnitude carries small-n variance; the direction of the fix does not
depend on it.
