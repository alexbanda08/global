# One-clip-per-pairing guard: 2-week simulation + volatility-filter study — 2026-08-21

Operator questions: **(1)** does "1 clip por pareamento" work, or does price run one way
and leave us with 5 lonely shares? **(2)** the best windows look sideways — can a
volatility filter throttle entries? Method: professional-grade, two independent
evidence legs, every number re-derived by hand in §6.

**Answers up front:**
1. **YES — implement the guard (cap = 1 clip of imbalance, both sides, whole window).**
   On our own 103 real live windows the opposite side comes back **77% of the time,
   median 13s** after the first fill. Under the current (post-Change-A/B) config the
   guard flips the entry book from **−$47.80 to +$8.38 over the last 29 windows
   (delta +$56.18, bootstrap CI95 [+13.0, +97.7], excludes 0)** and helps in ALL
   three recent sessions individually. The "5 shares always" worry does not
   materialize: balanced alternation keeps building (65% of share volume retained).
2. **The guard largely REPLACES the volatility filter.** High pre-window vol is
   indeed where the unguarded book dies (−$1.77/w in the top rng15 tercile,
   Spearman −0.24), but that loss IS the naked-accumulation loss — once the guard
   blocks it, the vol–PnL correlation collapses to ≈0 (−0.05). A residual vol
   throttle is worth a pre-registered test, not an immediate deploy.

---

## 1. Data & an infrastructure finding that shaped the study

Sources: VPS3 `storedata` — `trades_v2` (btc-updown-5m, Aug 4–21, ~5.06M prints,
5,007 windows), `market_resolutions_v2` (5,062 windows, Chainlink winners),
`binance_klines_v2` 1s/1m BTC (vol features, gap-free); Polymarket data-api
activity for our wallet `0x51a5…dd96` (1,208 real fills, 103 windows, re-fetched
tag `_2026_08_21b`); live ladder v3 mechanics read from `/opt/tvrust` source
(clip 5 sh, bids 2 ticks below touch, tick 0.01, G3 gate `bid ≤ pair_max_sum −
opp_vwap`, live `pair_max_sum=1.00`).

**🚨 Finding: the VPS3 Polymarket collector subscribes to each 5m market too
late.** First recorded print per window: median **+51s** after open, p90 +110s;
only 4.9% of windows have a print in the first 10s. Proof it is collector lag and
not market quiet: window `btc-updown-5m-1787319900` (today 13:45 UTC) has OUR OWN
real maker fills at +3…+67s, yet the VPS3 tape starts at +110.5s.
`orderbook_snapshots_v2` has the same lag (same discovery path);
`orderbook_deltas_v2` covers 15m markets only. Consequences:
- **No offline dataset can currently see the 5m entry window [0–60s]** — the
  exact regime where live earns its edge. Any tape-only backtest of the 5m open
  is structurally censored.
- Fix (same class as the Kalshi `status=unopened` fix): subscribe on market
  CREATION (5m markets exist pre-open; b945 rests orders early), not on first
  discovery poll. Handed to the collector owner.

Because of this, the study has two legs: a tape simulation (leg A, censored
regime, relative comparisons only) and a **replay of our real fills (leg B,
primary evidence — no fill model at all)**.

## 2. Leg A — tape simulation (5,007 windows, secondary evidence)

Simulator `strategy_lab/ladder_sim_2026_08_21/sim_ladder_policies.py`, faithful
to v3 mechanics: touch proxy = last print; bid = touch − 2 ticks; G3 pvs cap;
causal requote after every print; CONSERVATIVE maker fill = a taker-sell prints
strictly THROUGH our level (optimistic `≤` variant as upper bound); residual
rides to Chainlink settle; no cuts/backstop (both absent ⇒ absolute levels are a
LOWER bound on the deployed system, which adds +$8–35/session of Change-A salvage).

| policy (5-sh clip) | traded w | $/w | pair:resid | %both sides | pvs |
|---|---:|---:|---:|---:|---:|
| no guard, full window | 4,796 | **−1.60** | 0.71 | 66% | 0.846 |
| no guard, entry ≤60s | 1,572 | −0.58 | 1.80 | 72% | 0.926 |
| **guard1 (1 clip), entry ≤60s** | 1,572 | **−0.41** | **2.28** | 69% | 0.943 |
| guard2 (2 clips), entry ≤60s | 1,572 | −0.52 | 2.03 | 71% | 0.931 |
| guard1, full window | 4,796 | −0.84 | 1.34 | 61% | 0.900 |
| guard1 ≤60s, optimistic fills | 1,949 | −0.30 | 3.49 | 77% | 0.946 |

Robust relative facts (hold under both fill bounds and every pair_max_sum
0.97/0.99/1.00): **guard1 > guard2 > no-guard**; the entry-window cut is worth
~2× the guard alone; window composition under guard1 = 65% fully paired
(**+0.33/w positive**), 31% one-sided (−1.82/w, residual WR only 6% — the fills
are overshoot-selected by design, so an unpaired side is nearly always the
loser). Absolute negatives are NOT decision-grade: the tape cannot contain the
first-minute fills that live measurably earns (+5–20¢/sh in 5 of 7 live rounds).

## 3. Leg B — guard replay on our REAL 103 live windows (primary evidence)

`replay_guard_live.py`: take the actual BUY fill sequence per window; the guard
blocks any fill landing when its side is already ≥ cap ahead; hold everything to
settlement (sells excluded from both books — isolates entry flow; Change-A cuts
would ADD to both). No fill model, no book proxy, real prices, real winners.

| variant | buys$ | PnL (hold) | $/w | pair:resid | blocked sh | resid WR |
|---|---:|---:|---:|---:|---:|---:|
| baseline (all real buys) | 1,967 | −$62.02 | −0.602 | 1.07 | 0 | 24.8% |
| **guard1 = 1 clip (5 sh)** | 1,425 | **−$32.99** | **−0.320** | **2.32** | 1,645 | 27.3% |
| guard2 = 2 clips (10 sh) | 1,720 | −$62.07 | −0.603 | 1.98 | 920 | 25.0% |

- **guard2 is worthless** (identical PnL to baseline while blocking 920 sh): the
  cap must be exactly ONE clip to bind before the damage is done.
- Guard1 helps 52 windows (+$215.92), hurts 18 (−$186.89), neutral 33. What it
  gives up is the naked-runner lottery: the worst case is `…1787186100` (70 Up /
  10 Dn, base +$47.10 → guard +$2.90) — a 60-share naked residual at avg 0.18
  that happened to win. What it blocks is the same shape losing: `…1787063100`
  (10/93 collapsing Down, base −$13.27 → guard −$2.10).
- **Era split (the decision-relevant cut — current config is what runs forward):**

| era | n | baseline | guard1 | delta |
|---|---:|---:|---:|---:|
| pre-spec (r1–r4, old config) | 74 | −$14.22 | −$41.36 | −$27.15 |
| **compliant era (r5–r7, current config)** | 29 | −$47.80 | **+$8.38** | **+$56.18 · CI95 [+13.0,+97.7]** |
| — r5 (first green session) | 14 | +$1.36 | +$12.35 | +$10.99 |
| — r6 | 11 | −$29.12 | +$0.27 | +$29.40 |
| — r7 | 4 | −$20.04 | −$4.24 | +$15.79 |

  The guard helps in **all three current-config sessions individually** — it is
  not one lucky session. (The pre-spec-era negative comes from the Aug-4/5 config
  whose naked runs sometimes won; that config no longer exists.) The all-campaign
  CI includes 0 (+$29.03 [−129, +164]) — the significance claim is specific to
  the current config.
- **The operator's "price never comes back" worry, measured on real fills:** the
  opposite side eventually filled in **79/103 windows (77%)**, with lag
  first-fill → first-opposite-fill median **13s**, p75 40s, p90 72s. The 24
  windows where it never came back lost money anyway (baseline −$22.05; guard1
  caps them at −$18.38 while risking only 1 clip). Volume retained under guard1:
  ~29.7 sh/window vs 45.6 baseline (65%) — alternation keeps building whenever
  both sides trade, which is most of the time.

Replay caveat (stated, small): blocked fills in reality free queue/capital that
could marginally change later fills; the guard only ever REMOVES fills, so
pairing counts are conservative.

## 4. Volatility filter study

Causal features per window from Binance 1s closes (full coverage, no collector
lag): `rv5` = realized vol of the prior 5 min (bp), `rng15` = prior-15-min range
(bp), `drift5` = prior-window drift. Ex-post in-window range used only to test
the "lateral" hypothesis diagnostically.

**On the 103 real windows:**

| rng15 tercile (causal) | n | baseline $/w | guard1 $/w |
|---|---:|---:|---:|
| LOW (<22.4bp) | 35 | −0.13 | −0.01 |
| MID (22.4–37bp) | 34 | +0.08 | −0.28 |
| HIGH (>37bp) | 34 | **−1.77** | −0.68 |

Spearman(feature, window PnL): baseline −0.24 (rng15) / −0.13 (rv5); **guard1
−0.05 / −0.01** — the vol sensitivity lives almost entirely in the naked
accumulation that the guard removes. The operator's read was directionally right
for the UNGUARDED book ("high-vol windows are where we die"), but "lateral is
best" is not exactly supported: ex-post in-window range shows a hump (MID best:
guard1 +0.31/w; very quiet windows slightly negative — too few two-sided
traversals; very wild negative — runs beat oscillation). The tape sim shows the
OPPOSITE gradient (high vol = more pairing, ratio 2.1→3.7 by rv5 quintile) —
that is the censored post-subscribe regime, reported for completeness, not
decision-grade.

**Recommendation:** do NOT hard-deploy a vol filter now. After the guard, the
residual signal is weak (n=103, ρ≈0). Pre-register instead:
- **T1 (skip):** no new entry quoting when `rng15 > 37bp` (top tercile). On
  current data this would have saved ≈$23 (baseline) but only ≈$14 under guard1
  over 2 weeks of sessions.
- **T2 (throttle):** half clip (rounded to venue min 5 sh → in practice skip
  every other window-entry) in the same regime.
Readout at n≥100 guard-era windows: adopt T1 only if the HIGH-tercile guard1
book is negative with CI excluding 0. The feature needs one new input on the
box: trailing 15-min BTC range from the engine's own Binance feed (already
consumed by other sleeves).

## 5. What to hand the TV agent (adds to HANDOFF_LIVE_CAMPAIGN_2026_08_21 §5 item 2)

1. **Unhedged-window guard, exact form validated here:** a side may not take a
   fill that would leave it ≥ 1 clip (5 sh) ahead of the opposite side. Pause
   (cancel resting order) whenever `my_sh − opp_sh ≥ clip_sh`; resume when the
   light side catches up. Applies the WHOLE window (it subsumes the "pause both
   at parity after cutoff" rule — at 35/35 both sides are ≥0 ahead… the binding
   form: quote side X only while `X_sh − Y_sh < clip_sh`). Entry-window Change B
   and cut-gate Change A stay exactly as deployed.
   Note: this is what `glt_cap_q=4.0` in `poly_ladder.rs` already intends —
   config default is 4 sh < 1 clip — yet live windows reached 25×0, so the live
   path bypasses or mis-reads GLT. Root-cause that instead of adding a second
   mechanism if cheaper.
2. **Telemetry:** count `guard_blocked_fill` (side, sh, px, window_elapsed_s) so
   the next forensics can verify enforcement without inference.
3. **Pre-registered readout (frozen):** next n≥30 traded windows under guard —
   expect pairing ratio ≥2.0 (was 1.07 unguarded / 2.32 replayed), zero windows
   with |up−dn| > 5 sh, and net ≥ baseline-era $/w. The replay predicts ≈+$0.5–
   2/session swing at current size.
4. **Collector fix (separate owner, VPS3):** subscribe btc-updown-5m markets at
   creation, not discovery-poll — until then no offline study can see the entry
   window (median first print +51s, p90 +110s).

## 6. Verification log (calc-by-calc debug, as requested)

- **Cash identity:** every sim/replay window satisfies `pnl = paired + resid_won·resid − Σcost` exactly (asserted in code; two windows recomputed by hand below).
- **Hand-walk `…1787063100`** (winner Up, guard book): Dn+5@0.51 → Dn blocked(imb 5) → Up+5@0.54 → Dn+5@0.41(imb 0) → Up+5@0.55 → Dn+5@0.41(imb 0) → all further Dn blocked (imb 5, Up never fills again). Book 10 Up ($5.45) / 15 Dn ($6.65); paired 10, resid 5 Dn dies → pnl = 10 − 12.10 = **−2.10** = script output ✓. (First manual pass wrongly used the BASELINE book for guard decisions and got +2.00 — caught and corrected; the script was right.)
- **Hand-walk `…1787186100`** (winner Up): guard book 15 Up ($5.05) / 10 Dn ($7.05); paired 10 + resid 5 Up wins → 15 − 12.10 = **+2.90** ✓.
- **External anchor:** window 13:45 live tape (35/35 by +67s, locked +$1.96, real) vs VPS3 tape (starts +110.5s) — proves the collector gap, and the replay's fills for that window match the data-api activity 1:1 (first record is the infamous +202s 5 Dn @0.29).
- **Campaign reconciliation:** replay window count 103 = campaign scoreboard 103; baseline hold-to-settle −$62.02 vs actual cash −$89.97 — difference −$27.95 ≈ the campaign's net sell-ledger (early-cut era −$38 + recent salvage +$10), signs and magnitude consistent.
- **Vol features:** rv5/rng15 recomputed on gap-free Binance 1s (1.26M rows, max-ts = now); feature timestamps end strictly at slot_start (causal by construction).
- **Sensitivity:** guard1 > no-guard holds under conservative AND optimistic fill rules, under pair_max_sum ∈ {0.97, 0.99, 1.00}, and in leg A and leg B independently.

Scripts & data: `strategy_lab/ladder_sim_2026_08_21/` (`sim_ladder_policies.py`,
`analyze_results.py`, `replay_guard_live.py`, `debug_trace.py`,
`fetch_ours_topup.py`; CSVs from VPS3, `sim_results.json`,
`replay_per_window.json`).
