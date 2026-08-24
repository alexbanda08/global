# First live ladder trials — live vs paper twin, window by window — 2026-08-04

`poly_ladder_btc_5m_v3_live`, funder `0x51a5f3…dd96`. All live fills to date: **41 fills,
5 episodes, $106.41 deployed.** Reconstructed from `trading.events` + Polymarket settlement.

**Attribution is exact.** A `clob_token_id` belongs to exactly one market and one side, so
every fill maps to a window with certainty (resolved via `gamma-api /events?slug=`). No
time-bucket guessing — that matters, because the sleeve quotes ~5 future windows at once.

---

## 1. The tape

| ep | window (UTC) | side | token | fills | shares | cost | vwap | settled | **live PnL** |
|---|---|---|---|---:|---:|---:|---:|---|---:|
| 1 | `…1785811200` 02:40 | DOWN | `…591744` | 1 | — | — | — | **0 lost** | *unquantifiable* ¹ |
| 2 | `…1785857700` 15:35 | UP | `…384080` | 7 | 41.629 | $14.15 | 0.3400 | **1 WON** | **+$27.48** |
| 3 | `…1785870300` 19:05 | UP | `…532435` | 5 | 28.447 | $7.99 | 0.2810 | **1 WON** | **+$20.45** |
| 4 | `…1785876600` 20:50 | UP | `…868130` | 15 | 101.367 | $23.41 | 0.2309 | 0 lost | −$23.41 |
| 4 | " | DOWN | `…924451` | 13 | 65.000 | $46.75 | 0.7192 | **1 WON** | +$18.25 |
| 5 | `…1785878700` 21:25 | UP | `…702046` | 4 | 20.000 | $9.65 | 0.4825 | 0 lost | −$9.65 |
| 5 | " | DOWN | `…146109` | 2 | 10.000 | $4.45 | 0.4450 | **1 WON** | +$5.55 |

¹ the 02:41 fill logged with `shares`/`usd`/`price` all NULL — schema gap in the early live path.

---

## 2. Live vs the paper twin, same windows

Maker fills → **no taker fee** (house rule). Fee-inclusive floor shown for conservatism.

| ep | window | live cost | **live PnL** | (w/ 0.07 fee) | **twin paper PnL** | twin maker_sh | live shares | **live pair sum** | twin `pvs` |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 15:35 | $14.15 | **+27.48** | +26.82 | **−3.75** | 5.79 (DOWN) | 41.63 (UP) | — *single-sided* | — |
| 3 | 19:05 | $7.99 | **+20.45** | +20.05 | **0.00** ² | — | 28.45 (UP) | — *single-sided* | — |
| 4 | 20:50 | $70.16 | **−5.16** | −6.08 | **+0.01** | 0.06 | 166.37 | **0.9501** | 0.880 |
| 5 | 21:25 | $14.10 | **−4.10** | −4.27 | **0.00** ² | 0.00 | 30.00 | **0.9275** | — |
| | **total** | **$106.41** | **+$38.67** | **+$36.52** | **−$3.74** | **5.85** | **266.44** | **0.9471** ³ | **0.818** ⁴ |

² no `ladder_summary` row at all / `maker_sh = 0` — the paper sim did **not** trade these windows.
³ weighted by paired shares. ⁴ v3 lifetime average.

---

## 3. What this actually says — read it in three parts

### (a) The +$38.67 is a coin flip, not a validation

| | episodes | live PnL |
|---|---:|---:|
| **single-sided (pure directional, no arb at all)** | 2 | **+$47.93** — both won |
| **paired (the actual strategy)** | 2 | **−$9.26** — both lost |

The entire profit is two unhedged UP bets that happened to resolve UP. n=2 on each side.
The two windows where the ladder did what it exists to do — pair both legs — **lost money.**
Nothing here is evidence for or against the edge; it is four coin flips.

### (b) The arb margin collapsed by 71% — this is the real signal

The whole strategy is `paired_shares × (1 − pair_sum)`. That number is measurable at n=2:

| | pair sum | margin per paired share |
|---|---:|---:|
| paper, v3 lifetime | 0.8180 | **18.2¢** |
| paper twin, ep-4 window | 0.8800 | 12.0¢ |
| **live, ep 4** | **0.9501** | **5.0¢** |
| **live, ep 5** | **0.9275** | **7.3¢** |
| **live, weighted** | **0.9471** | **5.3¢** |

**Live capture on the arb leg ≈ 29% of paper.** The *pairing rate* is fine (ep-4 paired 65 of
166 shares ≈ 39%, ep-5 10 of 30 ≈ 33%, vs paper's ~30%) — live pairs about as often, it just
pairs **13 cents worse**. Both legs cross at prices the sim never modelled paying.

### (c) Live fills concentrate exactly where paper says "no fill" — adverse selection

| | live | twin, same windows |
|---|---:|---:|
| shares filled (eps 2–5) | **266.44** | **5.85** |
| per window | 66.6 | 1.46 |
| twin's *normal* rate | — | ~19–20 |

Live filled **45× more shares than its twin on the identical windows**, and those windows were
ones the sim rated near-untradeable (0.06 sh, 0.00 sh). Real resting orders get hit when the
book runs through them; the sim's print-matching says "nothing filled". Two causes, both real:
the live clip is $2 vs the sim's $5 (smaller clips fill on smaller prints), and the live order
is a real queue position exposed to real sweeps. **Whatever the mix, the paper sim is not
conservative here — it is the wrong shape.** It under-fills, and where it does fill it assumes
a 13¢-better price.

---

## 4. Two risk-control defects found — fix before any further live

**1. The `$4.00/side` cap was breached 5.9×.** Ep-4's UP leg accumulated **$23.41** on one side.
The check fires (`inventory cap: held $14.15 + order $3.44 > $4.00/side` — 1,924 rejections,
1,895 of them inside a 5-minute loop at 15:35–15:40) but positions still stacked far past the
limit. Fills land faster than the pre-trade check, and the check is per-order not per-position.

**2. The `day_notional` meter does not track reality, and resets on restart.**

| time | meter reads | actual inventory cost |
|---|---:|---:|
| 15:59 | $2.92 | $14.15 |
| 19:10 | $2.00 | $7.99 |
| 20:59 | **$14.35** | **$70.16** |
| 21:58 | $0.00 | $0.00 (reset) |

Cumulative real deployment was **$106.41 against a $40/day cap.** The `$40` notional cap and
the `$15` daily-loss latch are therefore **not functioning risk controls.** Also
`day_realized_pnl_usd` stayed `0.00` all day across 41 fills and 4 settled windows, and
`trading.positions` / `trading.orders` are both empty — **there is no system-of-record live
PnL.** Every number in this report had to be reconstructed by hand.

Third, minor: the T−tail backstop was **blocked by the venue $1.00 minimum** ($0.72 order,
36 sh) so ep-4's residual rode to settlement unhedged. At $2 clips the exit path doesn't work.

---

## 5. Verdict and what to do

**Nothing about the edge was tested today.** 4 quantifiable episodes, of which 2 were the
actual strategy. The headline +$38.67 is directional variance on unhedged inventory.

**One thing was tested, and it failed: the fill model.** Live pairs 13¢ worse than paper and
fills 45× more often in windows paper calls dead. If a 0.947 live pair sum is representative,
the paper $/window collapses from ~0.92 to ~0.27 and **every arm ranking in the bake-off is
irrelevant** — the question stops being "which arm" and becomes "is there an edge at all after
real fills."

n=2 paired windows cannot establish that. It can only tell you the measurement is now the
whole game.

### Order of operations — revised

1. **Fix the three defects first — do not trade on this config.**
   per-position (not per-order) side cap; a `day_notional` meter that counts actual fills and
   persists across restarts; write live fills into `trading.positions` + book realized PnL on
   settle. Backstop must respect the $1.00 venue minimum (raise clip or skip).
2. **Then re-run the v3 live trial at $5 clip / $20 per side / $200 day / $50 loss.** The one
   pre-registered readout: **live pair sum vs twin `pvs`, over n ≥ 30 paired windows.**
   Everything else is secondary.
3. **Hold the rcg promotion** until step 2 reads out. Its whole case was "same fill model as
   v3, which is validated" — as of today the v3 fill model is *not* validated, so that argument
   is suspended, not dead.
4. c2rcg stays queued behind rcg, unchanged.

**Pre-registered pass bar for step 2:** live pair sum ≤ 0.88 (≥12¢ margin, i.e. ≥66% of paper's
18.2¢) at n ≥ 30 paired windows. Below that, the ladder is a paper artifact at these clip
sizes and the correct response is to re-derive the sim's fill model against the recorded tick
tape, not to re-tune arms.

---

## 6. Caveat on this report

Settlement prices are Polymarket's `outcomePrices` via gamma, cross-checked against the
engine's own `outcome` field on the two windows where a summary exists — both agree. Maker
fills are treated as fee-free per the repo's standing rule; the fee-inclusive column is the
floor. Episode 1 is excluded from all totals (NULL fill fields).
