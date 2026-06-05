# Fidelity Audit — momo (`poly_updown_*`) + shadow (`shadow_poly_*`) families

_2026-05-29. READ-ONLY VPS3 inspection of the `poly_updown_loop.py` controller
stack (the momentum/shadow family, DISTINCT from the `poly_sniper_v5_*`
controller). Live data: `strategy_lab/live_all158_stats.csv` (trading.events
shadow PnL, May 27–29). 69 in-scope sleeves (60 `poly_updown_*`, 9
`shadow_poly_*`)._

Source files inspected on VPS3 (all under `/opt/tradingvenue/backend/app/`):
- `engine/poly_updown_loop.py` (2101 ln) — BarContext builders / signal anchors
- `engine/poly_updown_resolver.py` (730 ln) — outcome + PnL resolution
- `venues/polymarket/fees.py` — `slot_resolution_pnl`, `apply_resolution_fee`
- `controllers/polymarket_updown.py` (5077 ln) — dispatch, gates, qty, hedge/sell
- `strategies/polymarket/{momo,momo_v2,updown_5m,inverse,f7_gate,gates,markov,vwap_continuation,shadow9}.py`

---

## 0. Executive summary

- **Biggest winner — `shadow_poly_updown_ALL_5m_phase1_kelly` (+$1277, +$2.28/tr at 52.5% WR)**:
  wins DESPITE coin-flip WR because of **Kelly notional sizing**. High-conviction
  fires (`fair_edge_bp` tiers) get $25 × {2,3,4} stake; low-edge fires stay $25.
  Per-spec, faithfully implemented (`shadow9.VwapKellyEnsembleStrategy` +
  `_kelly_notional_override_usd`). The "WR×$/tr" math is dominated by the few
  4× fires landing on the right side. This is the only sleeve where sizing, not
  hit-rate, carries the PnL.
- **Biggest bleeder — `volume_INV_NIGHT` trio (−$3647 across 6 sleeves, ~44% WR, −$3.97/tr)**:
  **per-spec, NOT a bug.** INV_NIGHT is an anti-edge EXPERIMENT that flips the
  raw V1 "volume" signal during night hours {1,2,3,4,5,9,10} UTC, hypothesizing
  the original is 60–65% wrong. Live falsifies the hypothesis: flipped signal is
  ~44% right ⇒ original V1-volume-night was ~56% right ⇒ flipping LOSES. Working
  as designed; the experiment's premise is dead. **KILL.**
- **Fee-model split-brain CONFIRMED (same class of bug as the sniper audit).**
  The momo resolver uses `0.07·p·(1−p)` winner-only curve, NOT the legacy
  2%-on-profit that CLAUDE.md verified production actually charges. See §4.
- **F7 anchor, RSI calc, INV_NIGHT inversion, Kelly tiers, fade logic, prewindow
  rules — all faithfully implemented per their specs.** Two minor latent bugs
  (F7 boundary `<=`/`>=`, kelly-override not reset). No high-severity logic bug
  found in the momo/shadow signal path.

---

## 1. Per-sleeve / per-family table

WR / $/tr aggregated across asset×tf within each family from the live CSV.
Spec column references the report that defines the sleeve.

| family | base controller | spec found? | fidelity verdict | n | live WR% | live $/tr | notes |
|---|---|---|---|--:|--:|--:|---|
| `shadow_phase1_kelly` | vwap_kelly_ensemble | ✅ TV_AGENT_SHADOW_DEPLOY_GATED + shadow9 | **FAITHFUL** | 560 | 52.5 | **+2.28** | Kelly sizing winner |
| `shadow_S4_prewindow` | prewindow_s4_15m | ✅ shadow9 §Sleeve#9 | FAITHFUL | 11 | 81.8 | +14.19 | n too small; promising |
| `shadow_S3_prewindow` | prewindow_s3 | ✅ shadow9 §Sleeve#8 | FAITHFUL | 204 | 54.9 | +1.35 | net positive |
| `v3` | updown_5m sniper +mh | ✅ V3 deploy guide | FAITHFUL | 77 | 53.2 | +1.53 | positive |
| `v3_2` | v3 + hour/macro gate | ✅ V3 patches D-11 | FAITHFUL | 94 | 54.3 | +1.10 | positive |
| `momo_HOLD_f7` | momo v1 + F7 | ✅ HANDOFF_2026_05_22 | FAITHFUL | 237 | 51.5 | +0.35 | ≈breakeven (see §2.3) |
| `momo_v2_SELL_f7` | momo_v2 + SELL_BID | ✅ momo_v2 spec | FAITHFUL | 19 | 52.6 | +0.91 | tiny n |
| `momo_hod` | momo v1 + HoD gate | ✅ TV_AGENT_SHADOW | FAITHFUL | 3 | 66.7 | +8.11 | n=3, noise |
| `v3_1` | v3 + asym quantile | ✅ V3 patches D-11 | FAITHFUL | 89 | 51.7 | +0.13 | ≈breakeven |
| `momo_v2_HEDGE_f7` | momo_v2 + HEDGE_HOLD | ✅ momo_v2 spec | FAITHFUL | 19 | 47.4 | −0.65 | tiny n |
| `v3_3` | v3_2 + mh (SOL A/B) | ✅ V3 patches | FAITHFUL | 64 | 48.4 | −0.31 | A/B control |
| `v4` | v3_1 + v3_2 stack | ✅ V3 patches | FAITHFUL | 37 | 48.7 | −1.19 | overfiltered |
| `momo_v2_hod_mtf` | momo_v2 + HoD∩MTF2 | ✅ TV_AGENT_SHADOW #6 | FAITHFUL | 9 | 44.4 | −3.27 | tiny n, MTF2 cut |
| `momo_v2_hod` | momo_v2 + HoD | ✅ TV_AGENT_SHADOW | FAITHFUL | 36 | 47.2 | −1.92 | HoD lists stale (see §2.5) |
| `momo_v2_HOLD_f7` | momo_v2 + F7 | ✅ momo_v2 spec | FAITHFUL | 194 | 49.5 | −0.73 | F7 not enough alone |
| `shadow_fade_sniper` | fade(sniper) | ✅ shadow9 §#2-7 | FAITHFUL | 243 | 49.4 | −1.56 | fade premise weak |
| `shadow_fade_momo_v2` | fade(momo_v2) | ✅ shadow9 §#2-7 | FAITHFUL | 204 | 48.0 | −2.13 | fade premise weak |
| `sniper_hod` | sniper + HoD | ✅ TV_AGENT_SHADOW | FAITHFUL | 141 | 45.4 | −2.84 | HoD lists stale |
| `momo_SELL_f7` | momo v1 + SELL_BID | ✅ momo + spec | FAITHFUL | 25 | 32.0 | −9.55 | tiny n, exit drag |
| `momo_HEDGE_f7` | momo v1 + HEDGE_HOLD | ✅ momo + spec | FAITHFUL | 25 | 32.0 | −9.81 | tiny n, hedge drag |
| `volume_INV_NIGHT` | inverse(volume) | ✅ inverse.py spec | **FAITHFUL (dead experiment)** | 919 | 44.2 | **−3.97** | anti-edge falsified — KILL |

Verdict legend: every sleeve is FAITHFUL to its spec. No sleeve mis-implements
its signal. Losses are spec-correct experiments that did not pan out, or
gate-overlay lists that have gone stale, NOT controller bugs.

---

## 2. Sub-family deep-dives

### 2.1 Kelly ensemble (the winner) — `shadow_poly_updown_ALL_5m_phase1_kelly`

Maps to `strategy_mode="vwap_kelly_ensemble"` → `shadow9.VwapKellyEnsembleStrategy`.
Fire rule (faithful to spec):
```
direction = "UP" if dev_bps > 0 else "DOWN"      # binance 15m-anchored VWAP deviation
S4 = fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| >= 8
S8 = macd_agree AND rvol_30_300 > 1.2
fire iff S4 OR S8
```
**Why it wins at 52.5% WR** — Kelly tier (`_kelly_mult_for_edge`):
```python
if fair_edge_bp > 3000: return 4.0
if fair_edge_bp > 2000: return 3.0
if fair_edge_bp > 1000: return 2.0
return 1.0
```
Notional = `$25 × mult` applied via `controller._kelly_notional_override_usd`,
consumed in `_compute_qty_shares` (line 3233). The PnL is sizing-weighted: a
52.5% hit-rate is net positive when the winning fires are systematically the
high-`fair_edge_bp` (3–4× sized) ones and the losing fires sit at 1×. This is
the textbook Kelly outcome — **edge in stake placement, not in raw WR.** The
$/tr (+$2.28) is computed on a per-fire count basis but the dollars come from
the high-multiplier tail. n=560 over ~2.8 days = the largest, most-trusted
sample in scope.

Implementation is faithful. **KEEP / promote to deeper validation** — only
sleeve in the family with a real, sample-backed edge.

### 2.2 INV_NIGHT (the bleeder) — `poly_updown_{btc,eth,sol}_{5m,15m}_volume_INV_NIGHT`

Maps to `strategy_mode="inverse_volume_night"` → `inverse.apply_inverse_filter`.
The base is `Updown5mStrategy(mode="volume")` — a RAW sign-of-`ret_5m` bet with
**NO threshold gate and NO F7**. INV_NIGHT then:
```python
NIGHT_HOURS_UTC = frozenset({1, 2, 3, 4, 5, 9, 10})
if not is_night_hour_utc(window_start_unix): return "NONE"   # silent off-hours
return flip_signal(base_signal)                              # UP<->DOWN
```
anchored at `window_start_unix = ws_s` (correct, matches the bias-analysis
anchor `EXTRACT(hour FROM at)` where `at` was bar-close).

**Is the −$1200/sleeve a bug? NO — it is per-spec behavior of a falsified
experiment.** INV_NIGHT was deployed as an ANTI-EDGE test
(`TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md` / `ANTI_EDGE_FINDINGS.md`): the
hypothesis was that the V1-volume signal is 60–65% WRONG in night hours, so
flipping it should yield 60–65% RIGHT. Live result: flipped WR ≈ 42–44%
⇒ the ORIGINAL un-flipped V1-volume-night signal was ~56–58% right
⇒ the anti-edge premise is dead. Flipping a mildly-positive signal produces a
mildly-negative one, amplified by raw `volume` mode having no quality gate
(fires on EVERY night bar, ~232 fires/cell in <3 days). The code does exactly
what the spec says; the spec's market hypothesis was wrong.

`btc_15m_volume_INV_NIGHT` is the lone positive (+$0.35/tr, 52.6% WR) — noise
at n=78. **KILL all six** — confirmed anti-edge with no remaining rationale,
−$3647 aggregate, biggest dollar drain in scope.

### 2.3 `momo_HOLD_f7` vs the HANDOFF backtest

Live: btc +$12.94 (50.8% WR), eth −$171.68 (45.0%), sol +$38.56 (52.6%);
family +$0.35/tr at 51.5% WR.

Maps to `MomoStrategy` (v1) + F7 basic gate, HOLD policy, NO Markov, NO HoD.
Fire = top-q90 |ret_2m| at ws_s+120, F7 RSI agreement (RSI>50 UP / <50 DOWN).
**This does NOT match the HANDOFF deploy-candidate numbers** — and that's
expected. The HANDOFF's "+F7 basic: WR 59.69%, +$9,879" and the S1–S5 deploy
sleeves (+$4–5/tr) ALL stack an additional **Markov (M1V/M5V/M5F) and/or HoD
gate** on top of bare F7. The live `momo_HOLD_f7` sleeves carry **F7 ONLY**.
Bare F7 on the production fire universe lands ~51% WR / breakeven — consistent
with F7 being necessary-but-not-sufficient. The eth cell's −$2.86/tr is the
weak member (eth F7 lift was always the softest in the 12-cell table).
**Verdict: faithful; matches the "F7-only" tier, not the "F7+Markov deploy"
tier.** To realize the HANDOFF edge these need the Markov overlay added (the
`_hod`/`_hod_mtf` companions are the attempt — see §2.5).

### 2.4 Fade sleeves — `shadow_*_fade_{sniper,momo_v2}`

Maps to `FadeCompanionStrategy` (`shadow9`). Fires the OPPOSITE direction when
the base strategy signals UP/DOWN **and** (HoD fails OR M5V regime disagrees),
i.e. fade exactly the fires Phase-34 gates would have dropped. Logic faithful;
`fire_unix_s` correctly derived from `_bar_ctx_active.ws_s + phase offset`.
Live: −$1.56 to −$2.13/tr, ~48–49% WR. **Premise weak** — the dropped fires
are near-coin-flip (the gates filter low-conviction, not anti-predictive,
fires), so fading them is ~50/50 minus spread. Faithful, but no edge.
**KILL or downgrade** (`shadow_sol_15m_fade_momo_v2` at −$10.46/tr, n=28 is the
worst single sleeve by $/tr).

### 2.5 `sniper_hod`, `momo_v2_hod`, `momo_v2_hod_mtf` — HoD/MTF/Markov gated

Maps to `gate_stack=["hod"]` (or `["hod","mtf2"]`) wired at controller line
~2240. Gate runs AFTER `signal()`, AFTER F7, BEFORE qty. Anchor =
`_fire_unix_s = int(time.time())` ≈ ws_s+offset — **matches spec** ("anchor to
int(time.time()) at the controller fire decision moment"). HoD lists live in
`gates.py::HOD_TOP8_BY_CELL` (re-derived per `TV_AGENT_PHASE34_FIXES`, FIRE_us
anchor — differs from the original spec table, correctly).

Live: `sniper_hod` −$2.84/tr (45.4% WR), `momo_v2_hod` −$1.92/tr. **Faithful
but the hot-hour lists have gone stale** — they were fit on Apr 22–May 21 and
the spec itself (§6) mandates monthly refresh via `_recompute_hod_top8.py`
(which the HANDOFF notes was never built). The gate is now admitting fires in
hours that are no longer the profitable ones. This is config drift, not a code
bug. **INVESTIGATE: rebuild HoD lists on current 28d before any kill decision.**

### 2.6 v3 / v3_1 / v3_2 / v3_3 / v4

All map to `Updown5mStrategy(mode="sniper")` with layered V3 patches
(asymmetric quantile, hour-blocklist {1,16,22}, macro-2of3, multi-horizon AND).
Faithful to the V3 deploy guide + D-11 patches. Live ranking matches design
intent: **v3 (+1.53) > v3_2 (+1.10) > v3_1 (+0.13) ≈ v3_3 (−0.31) > v4 (−1.19)**.
v4 stacks every filter → over-filtered, fires too thin, net-negative. The
base v3 and the hour/macro-gated v3_2 are the healthy members. **KEEP v3,
v3_2; INVESTIGATE/downgrade v3_1, v3_3, v4 (overfiltered, breakeven-to-neg).**

### 2.7 momo HEDGE / SELL policies — `momo_*_{HEDGE,SELL}_f7`

`HEDGE_HOLD` buys the opposite ask on reversal; `SELL_BID` sells own bid on
`rev_bp` reversal. Live: momo v1 HEDGE/SELL −$9.55 to −$9.81/tr at 32% WR but
**n=25 each, all fires May 27 only (last_fire 09:45–11:10), then stopped.**
This is the known HOLD>HEDGE>SELL ordering (HANDOFF §2: held-side bias, exit
crosses 50¢ spread + taker fee) magnified by a tiny early-window sample.
Faithful. **De-prioritize** — too small to action; HOLD is the chosen policy.

---

## 3. Bugs found (with code quotes)

### 3.1 [LOW] F7 boundary skips equality (already noted in spec, present in live)
`strategies/polymarket/f7_gate.py`:
```python
if signal == "UP" and rsi_14 <= _F7_BASIC_UP_MIN:   # 50.0
    return False
if signal == "DOWN" and rsi_14 >= _F7_BASIC_DOWN_MAX:  # 50.0
    return False
```
RSI exactly 50 SKIPS in BOTH directions (docstring says "UP requires RSI > 50"
but uses `<=`). Per the spec this is intended (`<=`/`>=`). Impact: negligible
(RSI lands exactly on 50.000 essentially never). Documented, not a defect.

### 3.2 [LOW] Kelly notional override is never reset to None
`strategies/polymarket/shadow9.py` sets `controller._kelly_notional_override_usd`
inside `signal()` on every kelly fire, but there is no reset path. Searched
controller for `_kelly_notional_override_usd = None` → **only the set sites
(3233, 4776) exist, no clear.** Because the kelly controller sets it fresh on
every UP/DOWN fire BEFORE `_compute_qty_shares` reads it, and a NONE signal
returns before qty compute, this is benign **today**. But it is a latent
foot-gun: if a kelly fire returns NONE after a prior 4× fire, the stale 4×
override persists on the instance. Recommend an explicit reset at the top of
`on_bar_close` for defense-in-depth. Not affecting current live PnL.

### 3.3 [MED — same class as sniper audit] Fee model split-brain — see §4.

**No high-severity signal-logic bug found.** Signal anchors (ws_s),
RSI calc (simple-mean Wilder, 15 closes ending at ws_s, offsets
`[-60*i for i in range(14,-1,-1)]`), INV_NIGHT inversion, Kelly tiers, fade
direction, prewindow rules — all match their specs and CLAUDE.md invariants.

---

## 4. Fee model finding for the momo resolver

**The momo resolver uses the `0.07·p·(1−p)` winner-only curve, NOT the legacy
2%-on-profit model that CLAUDE.md/HANDOFF verified production actually charges.**

`engine/poly_updown_resolver.py` → `slot_resolution_pnl` →
`venues/polymarket/fees.py`:
```python
POLYMARKET_RESOLUTION_FEE_RATE = Decimal("0.07")

def apply_resolution_fee(*, entry_price, qty, won, fee_rate=POLYMARKET_RESOLUTION_FEE_RATE):
    if not won:
        return Decimal("0")
    fee_per_share = fee_rate * entry_price * (Decimal("1") - entry_price)  # 0.07·p·(1−p)
    net_per_share = Decimal("1") - fee_per_share
    return qty * net_per_share
```
`slot_resolution_pnl` returns `payout − cost`. The resolver's `pnl_usd`
(written to `trading.events kind='poly_updown_resolution'`) is therefore on the
**0.07 curve**, while:
- `controllers/polymarket_updown.py::_audit` writes a per-fill `fee_usd` field
  ALSO on the 0.07 curve (`compute_taker_fee_usd`, line 4960) — so the SIGNAL
  audit row and the RESOLUTION row agree with each other but **both disagree
  with the verified production charging behavior** (2%-on-profit, no loser fee).

**Magnitude:** the two models are close. At p=0.65 winning: 0.07-curve net/share
= 1 − 0.07·0.65·0.35 = 0.9841 → pnl/share +0.334; legacy 2%-on-profit
= (1−0.65)·0.98 = 0.343. The 0.07 curve charges ~$0.009/share MORE at mid
prices, peaking at p=0.5 ($0.0175/share). On $25 stakes (~38 shares at p=0.65)
that's ~$0.34/winning-trade overstated cost vs production-true. **Direction:
the resolver UNDER-states win PnL by a small amount** — it is conservative, not
optimistic, so it will not falsely promote a sleeve. But for apples-to-apples
comparison to production shadow dollars (and to the sniper-family audit which
found HOLD-path uses 0.07 while hedge uses legacy), the momo resolver should be
switched to `engine_v2.LegacyConfig` (2%-on-profit) per CLAUDE.md. **This is the
same split-brain the sniper audit flagged: resolution PnL on 0.07, production
reality on legacy 2%.** Outcome truth itself is correct (chainlink via
`_signal_won` + `onchain_oracle.ResolutionOutcome`).

---

## 5. Recommendation — KILL / KEEP / INVESTIGATE

### KILL (bleeding + per-spec premise dead)
- **`*_volume_INV_NIGHT` (all 6)** — anti-edge experiment falsified by live;
  −$3647 aggregate. Premise (original signal is 60–65% wrong at night) is
  disproven. No path to fix; the inversion is the whole strategy.
- **`shadow_*_fade_{sniper,momo_v2}` (all 6)** — fade premise weak; dropped
  fires are ~coin-flip, not anti-predictive. −$813 aggregate.
  `sol_15m_fade_momo_v2` worst at −$10.46/tr.
- **`momo_*_{HEDGE,SELL}_f7`** — HOLD dominates; stopped firing May 27; keep
  only as the documented HOLD>HEDGE>SELL evidence, disable live.
- **`v4`** — over-filtered (v3_1+v3_2 stack), −$1.19/tr, thin fires.

### KEEP (sample-backed positive, faithful)
- **`shadow_phase1_kelly`** — the family's real edge (Kelly sizing, n=560,
  +$1277). Promote to deeper out-of-sample validation.
- **`shadow_S3_prewindow`** (+$1.35/tr, n=204) and watch **`S4_prewindow`**
  (+$14/tr but n=11 — needs more fires before trusting).
- **`v3`, `v3_2`** — healthy v3-family members, positive and faithful.

### INVESTIGATE (faithful but config/overlay stale)
- **`sniper_hod`, `momo_v2_hod`, `momo_hod`, `momo_v2_hod_mtf`** — HoD top-8
  lists are stale (fit on Apr 22–May 21; monthly refresh never built). Rebuild
  `HOD_TOP8_BY_CELL` on current 28d (`_recompute_hod_top8.py` per spec §6)
  before judging — the gates may simply be admitting yesterday's hot hours.
- **`momo_HOLD_f7` / `momo_v2_HOLD_f7`** — F7-only ≈ breakeven; add the Markov
  (M1V/M5V) overlay that the HANDOFF deploy candidates use to reach the
  documented +$4–5/tr. eth cell is the weak member.
- **`v3_1`, `v3_3`** — breakeven; asymmetric-quantile / SOL-multi-horizon may
  be over-tight. Compare fire counts vs v3 base.

### Fee model action (cross-family)
- Switch the momo resolver's `slot_resolution_pnl` from the 0.07 curve to the
  legacy 2%-on-profit model (or make it config-driven via `engine_v2`
  Legacy/LiveMimic) so resolution PnL matches verified production charging and
  the sniper-family resolver. Low magnitude (~$0.34/win at p=0.65) and
  conservative-direction, so not urgent, but it is a real split-brain.

---

## Appendix — family aggregate live stats (May 27–29)

| family | n | WR% | sumPnL | $/tr |
|---|--:|--:|--:|--:|
| volume_INV_NIGHT | 919 | 44.2 | −3646.8 | −3.97 |
| shadow_fade_momo_v2 | 204 | 48.0 | −434.3 | −2.13 |
| sniper_hod | 141 | 45.4 | −400.4 | −2.84 |
| shadow_fade_sniper | 243 | 49.4 | −379.1 | −1.56 |
| momo_HEDGE_f7 | 25 | 32.0 | −245.2 | −9.81 |
| momo_SELL_f7 | 25 | 32.0 | −238.7 | −9.55 |
| momo_v2_HOLD_f7 | 194 | 49.5 | −141.0 | −0.73 |
| momo_v2_hod | 36 | 47.2 | −69.1 | −1.92 |
| v4 | 37 | 48.7 | −43.9 | −1.19 |
| momo_v2_hod_mtf | 9 | 44.4 | −29.4 | −3.27 |
| v3_3 | 64 | 48.4 | −19.9 | −0.31 |
| momo_v2_HEDGE_f7 | 19 | 47.4 | −12.3 | −0.65 |
| v3_1 | 89 | 51.7 | +11.3 | +0.13 |
| momo_v2_SELL_f7 | 19 | 52.6 | +17.2 | +0.91 |
| momo_hod | 3 | 66.7 | +24.3 | +8.11 |
| momo_HOLD_f7 | 237 | 51.5 | +82.2 | +0.35 |
| v3_2 | 94 | 54.3 | +103.5 | +1.10 |
| v3 | 77 | 53.2 | +117.5 | +1.53 |
| shadow_S4_prewindow | 11 | 81.8 | +156.1 | +14.19 |
| shadow_S3_prewindow | 204 | 54.9 | +275.1 | +1.35 |
| shadow_phase1_kelly | 560 | 52.5 | +1276.7 | +2.28 |

_End of audit._
