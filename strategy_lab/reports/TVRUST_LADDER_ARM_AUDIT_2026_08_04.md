# TVRUST ladder (arb) — full arm audit + next-live decision — 2026-08-04

Source: Ireland `85.137.174.152`, `/opt/tvrust`, DB `tradingvenue_rust`.
All numbers pulled live from `trading.events` (`kind='ladder_summary'`, deduped
`distinct on (sleeve_id, slug)` taking the LAST summary per window).

---

## 1. Where the arb strategy actually lives

| layer | path |
|---|---|
| engine service | `tv-rust-engine.service` (+ `tv-rust-api.service` :8090, `tv-rust-watchdog.service`) |
| ladder sim/logic | `crates/tv-engine/src/loops/poly_ladder.rs` (2,526 ln) |
| live submit + caps + kill | `crates/tv-engine/src/ladder_live.rs` (1,540 ln) |
| arm spawn / roster | `crates/tv-engine/src/main.rs:598-712` |
| persistence | `crates/tv-persistence/src/ladder.rs` (986 ln) |
| config | `/etc/tv/tvrust.env` (18 dated backups = the version history) |
| second arb line | `crates/tv-engine/src/loops/sumpair_osc.rs` (828 ln) |

**What the ladder is:** the b945-derived continuous two-sided GTC **maker** ladder.
Rests a requoting BUY clip on BOTH UP+DOWN tokens of every `btc-updown-{5m,15m}`
window, follows best-bid at `quote_depth_ticks` below touch, pairs what it can
(`pair_max_sum=0.99`), holds the residual to chainlink settle, with a T−tail
market backstop. MAKER-ONLY since the 2026-06-16 I0 cleanup (taker-completion
removed). Each sleeve runs a fully **isolated** book+trade mirror + 4-conn WS racer.

---

## 2. Version lineage (the whole path)

```
v1  poly_ladder_btc_15m            Jun 20–30   (retired)
v2  poly_ladder_btc_15m_v2         Jun 30–Jul 2  −$100.80  Δ −0.622/w  t=−1.85  KILLED
v3  poly_ladder_btc_15m_v3         Jul 2 →  base, BYTE-FROZEN  (control)
    poly_ladder_btc_5m_v3          Jul 2 →  base 5m mirror, BYTE-FROZEN
    poly_ladder_eth_5m_v3          Jul 4 →  ETH mirror, paper-only by spec
    poly_ladder_btc_5m_v3_live     Jul 28 → LIVE seam (separate sleeve, twin runs beside it)
v3.1  A/B knob bracket on the btc-5m base feed  (TV_LADDER_V31_ENABLED=true)
    _v31_rcg      depth2, 1× clip, residual-coinflip-gate 0.30–0.60      Jul 14 → RUNNING
    _v31_d1       depth1                                                 Jul 14 → RUNNING
    _v31_c2       depth2, 2× clip + 2× budget                            Jul 14 → RUNNING
    _v31_d4       depth4                                Jul 14–20  Δ −0.215/w t=−2.87  KILLED
    _v31_c2rcg    c2 × rcg PRE-REGISTERED COMBO         Jul 27 → RUNNING  ← the candidate
    eth_5m_v31_rcg                                      Jul 14–23  Δ≈0            KILLED (v3.3 §0.4)
v3.2  "cheap-flow" static 1¢ grid on btc-15m   (both arms CLOSED OUT, bands frozen)
    _v32_cheap    band 0.02–0.40     Jul 20–27  Δ −0.321/w t=−1.76  prereg_fail_no_tune
    _v32_cheapmid + band 0.50–0.62   Jul 20–23  −5.062/w  t=−30.2   spec_defect (pairs at sum 1.177)
v3.3  spec 2026-07-23 — a KILL spec (retired cheapmid + eth rcg). No new live arm.
v4    poly_ladder_btc_15m_v4_coc  "complete-or-cut" active taker completion
                                   Jul 5–23   +0.417/w t=3.29  → retired, COC_ENABLED=false
```

Retired arms stay in-tree, tested + dormant. Reviving any needs a NEW spec with
newly pre-registered params — no post-hoc tuning. That discipline held on every kill.

---

## 3. Standings — paired per-window Δ vs base `poly_ladder_btc_5m_v3`

Common era **2026-07-27 → 2026-08-04** (the c2rcg lifetime). Paired on the same
slug, so market regime is differenced out.

| arm | n | Δ/window vs base | paired t | Δ total | arm $/traded win |
|---|---:|---:|---:|---:|---:|
| **`_v31_c2rcg`** | 2,291 | **+0.640** | **8.87** | **+$1,466** | **1.677** |
| `_v31_c2` | 2,549 | +0.318 | 4.04 | +$810 | 1.297 |
| `_v31_rcg` | 2,549 | +0.162 | 3.15 | +$413 | 1.094 |
| `_v31_d1` | 2,549 | +0.101 | 1.47 | +$258 | 0.881 |
| `_v3` (base) | — | — | — | — | 0.887 |
| `_v3_live` twin | 2,110 | −0.0007 | **−0.01** | −$1.44 | 0.843 |

Full-life (from each arm's start):

| arm | traded win | $/traded win | t | total |
|---|---:|---:|---:|---:|
| `btc_5m_v31_c2rcg` | 1,761 | 1.679 | 14.92 | +$2,956 |
| `btc_5m_v31_c2` | 4,535 | 1.225 | 13.20 | +$5,555 |
| `btc_5m_v31_rcg` | 4,545 | 1.023 | **23.83** (lowest sd 2.89) | +$4,650 |
| `btc_5m_v3` | 7,163 | 0.925 | 17.72 | +$6,624 |
| `btc_5m_v31_d1` | 5,170 | 0.900 | 15.56 | +$4,654 |
| `btc_15m_v4_coc` | 779 | 0.417 | 3.29 | +$325 |
| `btc_15m_v3` | 1,477 | 0.445 | 4.26 | +$657 |
| `eth_5m_v3` | 3,737 | 0.335 | 7.60 | +$1,250 |
| `btc_5m_v31_d4` | 762 | 0.667 | 5.38 | +$509 → but paired Δ −0.215 t=−2.87 → KILLED |
| `btc_15m_v32_cheap` | 737 | −0.028 | −0.17 | −$21 → KILLED |
| `btc_15m_v32_cheapmid` | 320 | −5.062 | −30.24 | −$1,620 → KILLED |
| `btc_15m_v2` | 162 | −0.622 | −1.85 | −$101 → KILLED |

---

## 4. c2rcg: the pre-registration is PASSED, and the mechanism is clean

Frozen hypothesis (`main.rs:632`, written 2026-07-27 **before** the data):
> "ADDITIVE, Δ≥+0.35/w vs base, paired t≥2 at n≥2,000 (~7d).
> Sub-additive (Δ < c2 alone) IS the finding — no tuning."

**Measured: Δ = +0.640/w, t = 8.87, n = 2,291.** Passes on all three thresholds
and is **SUPER-additive**: c2 alone +0.318 + rcg alone +0.162 = 0.480 < 0.640.

**No decay** — the paired Δ is positive on every single day of its life:

```
Jul27 +0.556 | Jul28 +0.663 | Jul29 +0.445 | Jul30 +0.572 | Jul31 +0.476
Aug01 +0.367 | Aug02 +0.672 | Aug03 +1.265 | Aug04 +0.666
```

**Why it super-adds** (decomposition, the 223 windows carrying `net_components`):

| arm | total | paired_lock | residual_held | rcg_realized | backstop | rebate |
|---|---:|---:|---:|---:|---:|---:|
| `v3` | 113.7 | **+171.9** | −51.7 | 0 | −11.5 | +5.0 |
| `_c2` | 158.4 | **+296.1** | −90.8 | 0 | −54.6 | +7.8 |
| `_rcg` | 169.0 | +195.1 | −38.7 | +17.5 | −10.2 | +5.2 |
| **`_c2rcg`** | **237.7** | **+270.9** | **−35.9** | **+19.0** | **−23.9** | +7.7 |

- The edge is **paired sum<1 capture** (real arb) in every arm — `residual_held` is
  NEGATIVE everywhere. This is not directional variance.
- `c2` doubles the paired capture (+172→+296) **but also doubles the residual
  bleed** (−52→−91) and the backstop cost (−12→−55).
- `rcg` is a pure **risk reducer**: it flattens the coinflip-band residual, cutting
  c2's residual bleed −91→−36 and backstop −55→−24, and adds +19 realized.
- So c2 buys size, rcg pays for the size's downside. That is a real mechanism, not
  a fitted interaction.

---

## 5. Live reality check — the v3 trial (armed 2026-08-04 21:23 UTC)

Arm record (`trading.arm_state`): funder `0x51a5f3…dd96`, $80.16 pUSD,
3/3 on-chain approvals, all preconditions ok, caps `$4/side · 4 orders · $40/day · $15 loss`.

**Actual live tape to date — 1 day, effectively size-blocked:**

| metric | value |
|---|---|
| `ladder_order_placed` | 152 |
| **`ladder_order_rejected`** | **1,924 — 100% "inventory cap: held $X > $4.00/side"** |
| `ladder_live_fill` | 41 fills, $92.31 notional, prices 0.13–0.84 |
| realized PnL | $0.00 (nothing settled/redeemed yet) |
| `trading.positions` / `trading.orders` | 0 rows |
| kill latch | fired 19:10 `engine_heartbeat_stale` (deploy restart, FALSE POSITIVE), cleared 20:21 by operator |
| backstop | **BLOCKED**: "below venue $1.00 minimum ($0.72)", 36 sh requested, 0 sold |

**Twin parity is perfect** — `v3_live` paper sim vs base `v3` paired Δ = −0.0007/win,
t = −0.01 over 2,110 windows. The live sleeve's decision path is byte-faithful to
the validated base. That gate is CLEARED.

**Capture ratio is ~6%.** Last 24h: the twin's paper sim accumulated 5,163 maker
shares / +$205.80 net; the real wallet got ~300 shares / $92 notional. Cause is
purely the cap, not the signal:

| | paper base | live |
|---|---|---|
| clip | `$5` (`TV_POLY_LADDER_CLIP_USD`) | `$2` |
| budget per side | `$332` | **`$4`** |
| day notional | unbounded | `$40` |

---

## 6. Decision — what goes live next, in what order

### The binding constraint is SIZE, not signal.

**Do NOT promote c2rcg first.** `c2` *is* 2× clip ($5→$10 paper). At the live cap of
`$4/side`, the first c2 clip already exceeds the whole per-side budget → the c2 half
is un-expressible and you would be running plain `rcg` (+0.16/w) with an even worse
reject rate than the 93% you have now. Promoting it today would burn the arm's
credibility on an infrastructure limit.

### Step 1 (now) — unblock the v3 live trial. No new arm.
- `TV_POLY_LADDER_LIVE_MAX_USD_PER_SIDE` `4 → 20` (removes the reject wall)
- `TV_POLY_LADDER_LIVE_CLIP_USD` `2.0 → 5.0` (paper parity — makes the twin
  comparison meaningful, and lifts the backstop above the venue $1.00 minimum)
- `TV_POLY_LADDER_LIVE_MAX_DAY_NOTIONAL_USD` `40 → 200`
- `TV_POLY_LADDER_LIVE_MAX_DAILY_LOSS_USD` `15 → 50`
- Wallet needs topping up ($80.16 pUSD won't carry $200/day notional turnover).
- Fix the watchdog false-positive: a deploy restart must not latch the kill
  (`engine_heartbeat_stale` needs a restart-grace window).

**Measure for 3–5 days: real capture ratio = live fills ÷ twin paper fills, and
real settled $/window vs twin $/window.** That number — not another paper arm — is
the only thing standing between here and sizing up. Pre-register it now:
promote only if capture ≥ 60% and real $/window CI excludes 0.

### Step 2 (after Step 1 reads clean) — promote c2rcg.
New sleeve `poly_ladder_btc_5m_v31_c2rcg_live`, spawned DISARMED beside its paper
twin (same pattern as `v3_live`), caps `$10 clip / $40 per side / $400 day` so the
2× clip can actually express. It has passed its pre-registration cleanly, has a
mechanistic explanation, and has not decayed on any day of its life.

### Not next
- `_v31_d1` — Δ +0.101, t=1.47 in the common era. Fails. Leave it running.
- `eth_5m_v3` — +0.313/w, t=4.59, real but 1/5 the btc edge and needs its own live seam.
- `btc_15m_v3` — +0.465/w, t=2.58, but only 457 traded windows in 8d (1/4 the fire rate).
- `v4_coc` — +0.417/w t=3.29 when it ran, but retired Jul 23; reviving needs a new spec.
- `sumpair_osc` — btc lifetime +$1,131 (walk-fill) but **only +$41 in the last 8 days**;
  eth lifetime +$217 with `locked +$1,404` vs `residual_hold −$2,679` = the eth arm is
  pure directional variance wearing an arb costume. Both decaying. Not live-ready.

---

## 7. Caveats to hold onto

1. Every `$/window` number above is a **maker-fill SIMULATION** with
   `rebate_rate_assumed = 0.0015`. No live capture ratio exists yet. Until Step 1
   reads out, treat all of §3 as relative ranking, not absolute expectancy.
2. `net_components` only exists on **223 of 2,550** windows (recently-added field),
   so §4's decomposition is a small-sample mechanism check, not the full-life split.
   It agrees in sign across all six arms, which is what makes it usable.
3. Ireland `/opt/tvrust` is **not a git repo** on the box, and `STATUS.md` is stale
   (last entry 2026-06-16) while the code has moved through v3.1/v3.2/v3.3/v4. The
   env backups in `/etc/tv/` are the de-facto changelog. Worth fixing.
