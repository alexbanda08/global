# TV_AGENT_SPEC — ladder arm `v5_latepair_tc`: late taker pair-completion — 2026-08-13

**Status: SPEC — paper only. Pre-registered below; thresholds are FROZEN before first run.**
Target: `/opt/tvrust`, new PAPER variant beside `v5_latepair` on the btc-5m base feed.
Owner: engineering agent (Ireland). Strategy basis: this doc + measured b945 behavior in
[WALLET_REFRESH_B945_B27_BEHAVIOR_2026_08_13.md](WALLET_REFRESH_B945_B27_BEHAVIOR_2026_08_13.md) §4.

---

## 1. Why (all measured, none simulated)

- b945 (reference wallet, 15m ratio 5.53 @ pair-sum 0.9762) is **91% maker by fill count
  but 15.5% taker by USD** — and the taker leg is **100% BUY, avg px 0.705, 53–56% of its
  USD in the final 40% of the window**. On-chain confirmed (exchange `0xe1111800…`,
  `OrderFilled` topic decode): it sweeps ~2 resting makers per completion.
- Mechanism: rest maker both sides → cheap side fills → **buy the opposite (expensive) leg
  as taker late in the window to lock the pair**. The pair is not two lucky maker fills;
  the close is purchased.
- Our own retired `v4_coc` (active taker completion, 15m) measured **+0.417/w, t=3.29**
  over Jul 5–23 before being retired by the MAKER-ONLY cleanup. The cleanup deleted the
  mechanism the reference wallet actually uses.
- Our live problem is precisely unpaired residual (41% of buys; ratio 0.5–1.46 vs b945's
  4.4–5.5). `v5_latepair` stops *feeding* the heavy side; this arm adds the only measured
  mechanism that *closes* it.

Why this arm's paper numbers are more trustworthy than any maker arm's: a taker fill is a
spread-cross against the displayed ask — **no queue model involved**. The fill sim is
book-walk at the mirror's asks, which is the same primitive the live path uses. The
epoch-voiding maker-sim caveats do not apply to the TC leg (they still apply to the maker
legs underneath).

---

## 2. The arm

`poly_ladder_btc_5m_v5_latepair_tc` — byte-`v5_latepair` (which is byte-v3 + late rules)
plus ONE new layer. Shares the btc-5m base book feed (isolated mirrors as usual). PAPER
submit handler. `v5_latepair` itself is **untouched** — it is the control and its
pre-registration is in flight.

### 2.1 Behavior (identical to `v5_latepair` until the TC layer fires)

- **< 90s into window:** normal v3 quoting, both sides.
- **≥ 90s, heavy side exists:** heavy side stops adding (latepair rule, unchanged);
  light side keeps its maker quote with `late_pair_max_sum = 0.96` (unchanged).
- **NEW — TC layer, evaluated each poll while `t_in ≥ TC_AFTER_S`:**

```
resid_sh   = |filled_up_sh − filled_dn_sh|                # sim inventory (paper)
heavy_vwap = filled vwap of the HEAVY (over-filled) side
light_ask  = best ask on the LIGHT side (book_age ≤ TC_MAX_BOOK_AGE_MS)

fire iff ALL:
  resid_sh                       ≥ TC_MIN_RESID_SH        # 5.0 (venue share floor)
  heavy_vwap + light_ask + fee_est(light_ask) ≤ TC_MAX_SUM  # 0.98 — THE gate
  tc_attempts_this_window        < TC_MAX_ATTEMPTS         # 2
  tc_usd_this_window + cost      ≤ TC_MAX_USD_PER_WINDOW   # $25 paper
  light_ask × fill_sh            ≥ $1.00 and fill_sh ≥ 5   # venue minimums

action: IOC BUY on the light token, limit = light_ask (walk asks no deeper than
  the price where the sum gate still holds), size = min(resid_sh, depth within
  limit, caps). Partial fills allowed; remainder stays residual.
```

- Fill sim for the TC order: walk the CURRENT ask book of the isolated mirror; fill only
  displayed size at or below the limit; **reject the attempt entirely if
  `book_age > TC_MAX_BOOK_AGE_MS`** (stale book = no fill, count `tc_skipped_stale`).
- Completed shares move from residual to paired in all accounting; locked margin
  `= fill_sh × (1 − heavy_vwap − fill_vwap) − fee`.
- Everything else (T−tail backstop, settle, risk layer) byte-identical to `v5_latepair`.
  Precedence at end of window: TC has already run or refused; whatever residual remains
  follows the latepair/base policy unchanged (no new sell logic in this arm).

### 2.2 What the gate protects against (the −20¢ scenario)

The handoff's warning — "pairing late buys the LIGHT side, and when heavy we're heavy in
the LOSER, so the light leg is the winner at 0.75; 0.45 + 0.75 = guaranteed −20¢" — is
handled **by the sum gate, not by judgement**: at `heavy_vwap 0.45 / ask 0.75` the sum is
1.20 → refused. TC only ever converts a ±heavy_vwap coin-flip into a locked ≥ 2¢. If the
gate never passes, the arm degrades gracefully into exactly `v5_latepair`.

### 2.3 Fees

`fee_est(p) = TC_TAKER_FEE_RATE × p × (1−p)` with `TC_TAKER_FEE_RATE = 0.07` unless the
venue feed shows otherwise for these markets (reuse `coc_taker_fee_rate` plumbing from the
retired v4 COC — it is still in-tree). Fee sits INSIDE the gate, so a passing completion
is net-positive by construction. REV A: the gate is evaluated with `p = light_ask`
(pre-trade estimate), but the BOOKED fee must use the **realized fill vwap** — when the
IOC walks below the top ask level, `light_ask` understates the fee base; booking at the
estimate would flatter `tc_locked_usd` and corrupt H3.

---

## 3. Env (all new, defaults FROZEN)

```
TV_LADDER_V5_TC_ENABLED          false     # spawns the arm
TV_LADDER_TC_AFTER_S             90        # same phase boundary as latepair — not tunable separately
TV_LADDER_TC_MAX_SUM             0.98      # incl. fee; FROZEN
TV_LADDER_TC_MIN_RESID_SH        5.0
TV_LADDER_TC_MAX_ATTEMPTS        2         # per window (b945 sweeps ~2 makers/completion)
TV_LADDER_TC_MAX_USD_PER_WINDOW  25.0
TV_LADDER_TC_MAX_BOOK_AGE_MS     2000
TV_LADDER_TC_TAKER_FEE_RATE      0.07
```

---

## 4. Telemetry

Per window into `ladder_summary` (new fields): `tc_attempts`, `tc_fills`, `tc_filled_sh`,
`tc_cost_usd`, `tc_fee_usd`, `tc_locked_usd`, `tc_skipped_gate`, `tc_skipped_stale`,
`resid_sh_pre_tc`, `resid_sh_post_tc`. Per fill: event `ladder_tc_fill`
`{slug, side, limit_px, fill_vwap, fill_sh, heavy_vwap, sum_locked, book_age_ms}`.
These fields are the verdict inputs — no dashboard work required for the read.

---

## 5. Pre-registration (FROZEN before first tick)

Verdict at **n ≥ 2,000 completed windows** (~7 days), paired per-slug vs BOTH controls
(`v3` base and `v5_latepair`), post-epoch data only:

- **H1 (primary): paired:residual share ratio ≥ 2.0** over the arm's life.
- **H2 (guard, non-inferiority): paired per-slug Δ net/window vs `v5_latepair` — point
  estimate ≥ −$0.05 AND the 95% CI lower bound ≥ −$0.15.** (REV A: restated — the
  original wording was an ambiguous double negation; an acceptance criterion that can
  be argued about after the fact is not a criterion.) The ratio must not be bought by
  overpaying for late pairs.
- **H3 (mechanism check): mean `sum_locked` on TC fills ≤ 0.98 and `tc_locked_usd > tc_fee_usd`**
  in aggregate — the layer pays for itself standalone.

Pass all three → candidate for the live roster discussion (NOT auto-live; live port
requires §6). Fail any → the failure is the finding; the arm keeps running only if H2
holds (it's free); **no re-tuning of `TC_MAX_SUM`/`TC_AFTER_S`** — a new band is a new
spec with a new pre-registration.

---

## 6. Live-port invariants (write them into the code now, as comments on the TC layer)

1. **"Live lê live"** (the §4.2 lesson, named twice before it was violated): the live TC
   layer must read `resid_sh`/`heavy_vwap` from **venue-confirmed fills**
   (`net_position_sh` per token), never from the sim twin. In paper the sim is its own
   truth; the seam must make the source explicit so the port cannot repeat bug 4.2.
2. TC submit path = IOC with hard limit; never GTC (a resting "completion" is just another
   maker order and belongs to the other layers).
3. Balance pre-check before the IOC (the 73 `not enough balance` rejections currently
   manufacture naked legs — a TC refused for balance is worse than no TC, log it loudly:
   `tc_skipped_balance`).
4. The kill/breaker/caps stack applies to TC orders like any live order.

---

## 7. Explicit non-goals

- Does NOT touch `v5_latepair`, base v3, or any running pre-registration.
- Does NOT sell anything — no interaction with recycle/mrcut logic.
- Does NOT run on 15m yet (b945 does; one arm, one variable — 15m is a follow-up spec if
  H1–H3 pass).
- Does NOT go live on a paper pass alone: live requires the §6 invariants plus the
  standing blockers (breaker-counts-redemptions §8.2, capital §8.3) resolved.
