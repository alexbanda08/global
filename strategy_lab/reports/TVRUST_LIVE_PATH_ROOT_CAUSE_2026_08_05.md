# The live path: root cause + options — 2026-08-05

Your read is right on all three counts and the breaker gap is real. But the framing
"live fills 10¢ worse than the sim" understates it. The data says something sharper.

---

## 1. The problem, precisely

**Live is not a degraded version of paper. Live is sampling a different part of paper's own
distribution — the part paper also loses money on.**

Paper, base v3, 9 days, net by realized pair-vwap-sum:

| pvs band | windows | **net/window** | paired leg | residual leg |
|---|---:|---:|---:|---:|
| **< 0.70** | 198 | **+4.336** | +810.8 | +38.9 |
| 0.70–0.80 | 202 | **+3.222** | +564.1 | +77.6 |
| 0.80–0.85 | 168 | +1.614 | +362.0 | −99.3 |
| 0.85–0.88 | 99 | +1.148 | +174.0 | −65.4 |
| 0.88–0.92 | 172 | +1.052 | +196.3 | −23.3 |
| 0.92–0.96 | 153 | +0.488 | +79.8 | −10.7 |
| **≥ 0.96** | 156 | **−0.258** | +23.1 | −67.8 |

Monotone. The top band is **outright negative**. Note also where the residual flips sign:
below 0.80 the residual leg is *positive* (+$116 combined); above 0.80 it is negative in every
single band. Cheap pairs and survivable residuals are the same phenomenon.

**Live's measured windows: 0.915, 0.97, and two one-sided.** Bottom two bands, exclusively.
That is not bad luck over four windows — it is what the current live config is built to produce.

So the question is not "why is live 10¢ worse." It is **"why does live never reach the cheap
band?"** Four compounding reasons, all in live's config and code, none in the strategy.

---

## 2. Why live cannot reach the cheap band

**(i) A float-epsilon min-size skip — still live.**
```
{"price": 0.18, "size_sh": 5.555555555555555, "notional_usd": 0.9999999999999999, "min_usd": 1.0}
{"price": 0.09, "size_sh": 11.11111111111111,  "notional_usd": 0.9999999999999999, "min_usd": 1.0}
```
The engine sizes the clip to *exactly* $1.00 and then rejects its own order because
`1.0/0.09 × 0.09 = 0.9999999999999999 < 1.0`. **32 skipped quotes, every one on the cheap
side.** Your comment at `ladder_live.rs:1312` shows you already fixed the ordering bug — this
is the residual epsilon. One line: compare with a tolerance, or round shares up.

**(ii) Share-clip instead of dollar-clip.** `CLIP_SH 5` vs paper `clip_usd 5.0`. At 0.41 paper
buys 12.2 sh, live buys 5. A share-clip *shrinks in dollars as price falls* — it is smallest
exactly where the edge is largest. This is your change from last night and it was the right
call against the venue floors, but the correct form is `max(5.0, clip_usd/p, min_usd/p × (1+ε))`
— keep the floor, keep the dollar clip.

**(iii) `MAX_USD_PER_SIDE = 5.0` vs paper `budget_per_side = 332`. 66×.** Paper reaches vwap
0.11 by re-quoting down repeatedly across a whole window. Live is finished after one clip and
freezes its vwap at whatever the first fill was — near the touch. This is the binding
constraint on averaging down, and it is the biggest of the four.

**(iv) `PAIR_MAX_SUM = 0.99` is ~11¢ too loose.** It permits exactly the pairs the table above
says lose money. It is already the right mechanism — it is just set to the wrong number.

---

## 3. Your (a)-vs-(b) test — I ran it, no tape needed

`ladder_tick` logs resting price and cumulative fills at ~1Hz. Cheapest window in the last 30h,
`btc-updown-5m-1785910800`, pvs **0.275**, net **+$6.32**:

| t | resting_up | filled_up | resting_dn | filled_dn | best_bid_dn |
|---|---:|---:|---:|---:|---:|
| 22:15 | 0.11 | 8.92 | 0.84 | 0.0 | 0.86 |
| 24:51 | 0.62 | 8.92 | 0.31 | 5.0 | 0.33 |
| 24:58 | 0.79 | 8.92 | **0.03** | **10.64** | **0.01** |

**Answer: both, and the split matters less than you'd think.** The cheap pair came from having
size resting deep on *both* sides across a violent intra-window reversal — UP filled at 0.11
early, then DOWN collapsed 0.33 → 0.01 in **seven seconds** and the sim took 5.64 more shares
into the crash. DN vwap 0.165 = 5 sh @ ~0.31 + 5.64 sh @ ~0.03.

So: part re-quote-down (a), part the generous `tp < p` sweep branch (b).

**Is paper's +$144 an artifact? Partly — and you cannot yet say how much.** The sweep branch
grants the whole print with zero queue, so some of that 5.64 sh @ 0.03 would not have filled.
But the *structure* — cheap fills come from deep resting size during reversals — is real, and
live currently cannot have deep resting size at all. **"Artifact" and "real" are both
unfalsifiable until the tape exists.** Which is the argument for turning the recorder on
tonight, not for concluding either way.

---

## 4. On your two points I want to sharpen

**The breaker.** You're right and it should ship tonight regardless. Add the detail: mark the
residual conservatively (at 0, not at mid) — a residual that is losing is exactly the one whose
mid is about to go to 0, and marking at mid will lag the loss it exists to catch.

**The backstop.** You framed it as "can't rescue a losing leg." True, but the fix isn't the
backstop. By the time a residual is under $1 it has already lost ~everything — no exit
mechanism recovers that. The two real answers are **cut it while it's still worth something**
(that is exactly what `rcg` does at 0.30–0.60, and it is off on the live sleeve) or **don't
acquire it** (§5, Option 1). Repairing the backstop's $1 handling is worth doing, but it is a
tidiness fix, not a loss-bound.

---

## 5. Options — everything on the table

### Ship tonight, unconditional (both are safety/correctness, not strategy)
1. **Breaker counts unrealized**, residual marked at 0.
2. **Fix the epsilon** in the min-notional guard.
3. **`TV_POLY_TICK_RECORD_ENABLED=true`.** Currently `false`, dir empty. It is built, tested,
   non-blocking. It costs nothing and it is the only thing that can ever settle §3. Also log
   the live order lifecycle (place/requote/cancel/fill + book snapshot) so the 156 live fills
   become labelled training data.

### Then choose. My recommendation: Option 1 before Option 2.

**Option 1 — change the strategy in paper: only take cheap pairs. (Recommended, free.)**

Counterfactual on 9 days of paper, refusing pairs above a threshold:

| `PAIR_MAX_SUM` | windows kept | net kept | **$/window** | net forgone |
|---:|---:|---:|---:|---:|
| 0.99 *(current)* | 1,147 | $2,111.7 | **1.841** | — |
| 0.92 | 845 | $2,080.5 | 2.462 | $29.0 |
| **0.88** | 672 | $1,895.9 | **2.821 (+53%)** | $213.6 |
| 0.85 | 570 | $1,781.5 | 3.125 | $328.0 |
| **0.80** | 409 | $1,519.6 | **3.715 (+102%)** | $589.9 |

**Honest caveat: this is an upper bound.** Refusing the second leg does not delete the window —
it leaves a *naked first leg*, which is the thing already killing you. The clean version is a
**pre-window gate**: don't open either side unless the book offers a cheap pair (gate on
`best_ask_up + best_ask_dn` at placement), so there is no orphan leg. Both variants should ship
as **new paper arms with frozen pre-registrations**, not as a tweak to the live config.

This is doubly right for live specifically: **live is window-starved, not opportunity-starved.**
At $5/side you want the best 20% of windows, not all of them. A tighter gate costs you nothing
you can afford anyway.

**Option 2 — make live able to reach the cheap tail.** Dollar-clip with the venue floors,
`MAX_USD_PER_SIDE` 5 → 40, GLT aligned to paper. This is the only option that actually *tests*
the strategy — but it is the one that costs money, and it should come **after** Option 1 has
narrowed what you're aiming at. Doing it now means paying real money to sample the losing
bands harder.

**Option 3 — stop and settle the fill model first.** Zero risk, zero progress. It is not a
blocker for Option 1 (a paper change), so it should run *in parallel*, not instead.

### The thing not to do
**Do not raise `MAX_USD_PER_SIDE` while `PAIR_MAX_SUM` is 0.99.** That is buying more of the
distribution that loses.

---

## 6. Recommended order

1. Tonight: breaker-on-unrealized · epsilon fix · recorder on. Stay disarmed.
2. This week, paper only: two new pre-registered arms — `pair_max_sum = 0.88` and the
   pre-window cheap-pair gate. Frozen bar: Δ ≥ +0.5/window vs base v3, paired t ≥ 2, n ≥ 2,000.
3. In parallel: replay harness against the tape; first target is the `tp < p` branch, since
   §3 shows it is where the cheap fills come from.
4. Only then re-arm — on the winning gate, with a dollar-clip and a raised per-side budget,
   and with `rcg` on. Re-arming before step 2 reads out just buys more 0.97 pairs.

**I agree with not re-arming.** Not because four windows lost — four windows prove nothing —
but because the config is currently guaranteed to sample the bands that lose.
