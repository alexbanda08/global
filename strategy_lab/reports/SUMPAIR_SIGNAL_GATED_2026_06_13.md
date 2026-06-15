# Signal-gated sum-pair — re-enumeration & adversarial verdict (2026-06-13)

**Operator directive:** we never tested the SIGNAL-GATED predictive sum-pair. We DO have proof the
Binance→Polymarket lag is real and tradeable (the deployed lag-scalp: buy the lagging Poly leg cheap
when Binance moved but the book hasn't repriced, `entry_vwap<0.55`, `|ret|≥3bp` bar-END gate, SELL +60s).
The untested idea: use that SAME validated lag entry to acquire each leg cheap, then PAIR (buy the other
side) and HOLD to chainlink resolution to lock a sub-$1 pair, exploiting intra-window Binance oscillation.

**Three variants were run; I re-verified each against its result parquet, re-ran the causality control
on a slice, and stress-tested the one positive arm. Bottom line:**

> **The operator is partially right.** A signal-gated sum-pair edge DOES exist, but ONLY in the
> **oscillation-harvest form (V2)** — buy *each* side independently at its *own* causal lag-dip across
> the window, so the time-averaged pair sum < 1. The two "instant/sequential pair-completion" forms
> (V1, V3) are dead — they cannot beat the deployed +60s scalp and never clear sum<1. **V2 survives
> bar-END causality, 85ms latency, and chainlink settlement, but the headline +2.24/slug is inflated
> ~4× by an infinite-refill (size==0→DEEP) assumption. Stripped to a realistic 1-clip-per-side fill the
> edge is +0.52/slug OOS (CI [+0.36,+0.68]) — real but thin, and 62% of slugs still lose.**

---

## Re-enumeration: one variant at a time

### V1 — lag-gated INSTANT pair  → **DEAD** (verified)
Signal leg lifted at its bar-END lag fire (`|ret|≥3bp`, `vwap<0.55`); the OTHER side paired
instantly by book-walk at the **same** decision+85ms; both held to resolution.

| split | net/slug (pnlA) | CI95 | t | n |
|---|---|---|---|---|
| ALL | **−1.821** | [−1.863, −1.780] | −85.5 | 12,801 |
| OOS | **−2.089** | [−2.156, −2.021] | −60.4 | 7,666 |

- `paircost` median **1.015**, **0%** of pairs < 1.0. The instant second leg pays the overround.
- On the SAME fires: +60s scalp (B) = **+1.869**, pure-hold of signal leg = **+2.786**, pair (A) = **−2.089**.
  Pairing **A−B = −3.957** CI [−4.73, −3.18]. Pairing strictly destroys the existing edge.
- **Why dead:** completing the pair at one instant always costs the full overround (the two asks at a
  single moment sum ≥1). This is the V2-taker-overround result again, third independent confirmation.

### V3 — predictive-winner LEAN + optional pair-HEDGE  → **DEAD** (verified)
Lead leg = the lag signal side Binance favors, held to resolution; conditionally complete the pair
when blended sum ≤ target within 120s. Causal (bar-END) primary; leaky arm run for bias quantification.

| arm (OOS, filled n=3,138) | net/slug | CI95 | vs deployed scalp (paired) |
|---|---|---|---|
| HEDGE tgt 0.99 | +0.685 | [+0.269, +1.100] | **d = −0.385 [−0.759, −0.011]** (worse, excl 0) |
| HEDGE tgt 0.97 | +0.615 | [+0.172, +1.059] | d = −0.454 [−0.837, −0.072] (worse) |
| A_HOLD (no hedge) | +1.591 | [+0.860, +2.321] | d = +0.521 [−0.019, +1.061] (**straddles 0**) |

- The lag price-entry survives to resolution as a positive single-leg lean (+1.59 OOS, +4.00 on
  `vwap<0.55`), but **neither holding nor hedging beats the +60s sell**, and the hedge actively
  destroys value (adverse selection: completing the pair caps the winning lead leg's ~35¢ upside to
  capture only the ~3¢ overround). 100% of completed pairs are sub-1 by construction (target gate),
  but completion is only 58–72% and the kept upside loses to selling.
- **Leaky-vs-causal control:** the leaky bar-START arm inflates A_HOLD, but the inflation is
  concentrated **in-sample** (IS leaky +1.077 vs causal −0.201 = +1.28 bias; OOS bias ≈ 0). Confirms
  bar-START is look-ahead and the causal arm is the conservative/correct one. (The JSON's reported
  "+0.458 leaky inflation" was a pooled IS+OOS figure; the matched-fire OOS bias is −0.08, i.e. no OOS
  leak — which makes V3's "dead" verdict *more* solid, not less.)

### V2 — OSCILLATION-HARVEST (signal-gated predictive legging)  → **EDGE-FOUND, with caveats** (verified + stress-tested)
Full-window causal rolling decision every 5s; each side independently lag-gated on its OWN
Binance-LEAD dip (bar-END, `|ret|≥THR`, 5s lookback); clip-buy that side at +85ms if `ev<0.55`;
accumulate both sides; `pair = min(sh_up,sh_dn)` held to chainlink resolution, residual held winner-only.

**Headline (THR=3, fired slugs), reproduced exactly from the parquet with the correct date split:**

| split | ARM A net/slug | CI95 | n |
|---|---|---|---|
| ALL | **+1.153** | [+0.562, +1.743] | 20,685 |
| IS (Apr24–May20) | −0.066 | [−0.581, +0.449] | 9,758 |
| OOS (May21–Jun11) | **+2.241** | [+1.223, +3.259] | 10,927 |

- `paircost` median **0.732** (both-filled), **92.6%** of pairs sub-1. Feasibility: **34.6%** both-filled
  (>>10% threshold). ex-top2 OOS **+1.982** (survives outlier removal).
- **vs deployed +60s scalp** (control = first clip each side sold +60s): ARM A **+2.241** vs control
  **+0.292**; paired diff OOS **+1.949** CI [+0.940, +2.958] — **beats the scalp, CI excludes 0.**
- **THR robustness:** OOS arm_a = +2.257 / +2.241 / +1.803 at THR 2/3/5 (all CI>0).
- **Per-cell OOS:** the edge is a **5m phenomenon**. BTC-5m +4.75 [2.59,6.90], ETH-5m +2.91 [1.42,4.41],
  SOL-5m +2.36 [1.39,3.33] (all CI>0). The 15m cells straddle 0: BTC-15m −1.65 [−6.10,+2.80],
  ETH-15m +0.38 [−3.73,+4.49], SOL-15m +2.99 [−0.25,+6.22].

---

## Adversarial audit (the 5 mandated refutation checks)

**(a) Bar-END not bar-START (the repo's #1 bug).** PASS. All three scripts use the verbatim causal
`asof_on(ends=starts+1e6, …, searchsorted right −1)` from `scalp_causal_asof_oneshot_2026_06_12`.
I independently re-ran V2 on a SOL-5m OOS slice both ways: **leaky bar-START fires MORE both-fills
(29 vs 19) but does NOT raise PnL (+0.600 leaky vs +0.645 causal, Δ −0.045)** — the causal version is
not accidentally leaking; if anything it's the conservative one. V3's leaky inflation is IS-only.

**(b) 85ms latency fill, not detect-instant.** PASS. Every clip fills via
`entry_fill(ts, ask0, asksz0, t+85_000us, …)` from `scalp_fill_lib_2026_06_10` (the same primitive that
made the prior taker-arb go negative once 85ms was applied). I confirmed in source.

**(c) Chainlink settlement on ALL gated slugs (no censoring).** PASS. `won = (side=='Up')==(outcome=='Up')`
from `load_resolutions` for every fired slug; no engine-redeem. Settlement formula
`pair_locked_pnl = q·[(1−p_w)(1−0.07·p_w) − p_l]` verified by hand: winner-only 0.07 fee, $0 loser,
sound for a binary that pays the winner exactly 1.

**(d) Overround not dodged by a stale-quote asof artifact.** PASS — and this is the strongest evidence
*for* the operator. Markout on 330 BTC clips: the filled cheap ask **RISES** after the fill
(+1.9¢@1s, +5.3¢@5s, **+8.0¢@30s**). We buy genuinely below where the book reprices — the *opposite*
of the sub-100ms revert that killed the simultaneous taker arb. The sub-1 pair is assembled from
genuinely-anti-correlated, real-depth (80–1,000 share) oscillating quotes, not one re-hit stale level.
**Inspected a typical paircost-0.70 slug:** Up ask oscillated 0.37–0.58, Down ask 0.43–0.64,
anti-correlated; firing Up on its dips (ev 0.288) and Down on its dips (ev 0.412) gives a 0.701 sum
even though no single instant offered sub-1. The mechanism the operator described is real.

**(e) Does pairing ADD over selling at +60s?** YES for V2 (paired diff +1.949, CI excl 0), NO for V1
(−3.957) and V3 (hedge −0.39, hold straddles 0). The independently-lag-gated second leg captures its
*own* side's repricing, which reverses the V5 "hold is dominated by sell" finding — but only when the
2nd leg is *actively* lag-gated, never when it's passively completed (V1/V3).

### The one real problem with V2: infinite-refill inflation + concentration

The +2.24 headline is **NOT robust to the fill-depth assumption.** Three findings:

1. **Concentration.** OOS: only **37.3% of fired slugs are positive** (62.7% lose). Top-5 slugs = 25%
   of total PnL; **top-20 = 63%**; top slugs deploy $150–425 and accumulate up to 412 shares one side.
2. **Clip-count dependence.** Slugs with >2 clips = 49.6% of slugs but **98.3% of PnL**; >10 clips = 11%
   of slugs but **51% of PnL**; >20 clips = 3.5% but **44%**. The edge lives in the heavy-clip tail.
3. **The refill assumption is baked into the fill model.** `scalp_fill_lib.resolve_size` returns `inf`
   (DEEP) when `size==0` (47% of L25 rows are artifact-zero). So firing the *same* side 15–45× at $5
   each never exhausts depth and never moves the book — cumulative $150–425 of taker buying at a lagging
   quote is assumed frictionless. That is the same infinite-liquidity class of artifact that previously
   inflated maker-fill and taker-arb.

**Realistic deployable test — 1 clip per side max (no refill), independent reimplementation, full OOS:**

| config (OOS) | net/slug | CI95 | both% | %slugs>0 |
|---|---|---|---|---|
| multi-clip (headline) | +2.241 | [+1.223, +3.259] | 34.6% | 37.3% |
| **1-clip per side** | **+0.520** | **[+0.364, +0.676]** | 34.5% | 41.9% |
| 1-clip, both-filled only | **+2.273** | [+2.068, +2.479] | — | — |

The edge **survives** the conservative single-clip fill (+0.52/slug, CI excludes 0) — so the operator's
core hypothesis is genuinely true — but the multi-clip headline is **~4× inflated** by the refill
assumption. The pure market-neutral **LOCKED** component is positive and CI-tight in **both** halves
(IS +1.23, OOS +3.43 over all fired; IS +4.64, OOS +9.92 on both-filled) and across all THR — it is the
real, regime-stable piece; the negative directional **RESIDUAL** (−1.19 OOS) is what dragged IS arm_a to
breakeven. The 1-clip both-filled edge (+2.27) IS the operator's literal market-neutral claim.

### Data-integrity note (does not change any verdict)
The V2 parquet's stored `oos` boolean is **buggy for SOL only**: all 4,367 SOL May21+ rows are mislabeled
`oos=False` (BTC/ETH correct). The bug is in the saved column, not the analysis — every headline number
above was recomputed from `slot_start_us >= 2026-05-21` and reproduces the JSON exactly. SOL's true OOS
cells (5m +2.36, 15m +2.99) are included correctly. **Re-derive splits from `slot_start_us`, not the
stored `oos` column, on this parquet.**

---

## VERDICT

**A signal-gated sum-pair edge EXISTS — the operator is right — but ONLY in the oscillation-harvest form
(buy each side at its own lag-dip), and the deployable magnitude is ~+0.5/slug, not the +2.2 headline.**

- **V1 (instant pair) — DEAD.** Single-instant pairing always pays the overround; sum never < 1;
  strictly destroys the +60s scalp (A−B = −3.96).
- **V3 (lean + hedge) — DEAD.** The lag lean survives to resolution but doesn't beat the +60s sell;
  the hedge actively caps the winner's upside (adverse selection). Causal arm only; leaky inflates IS.
- **V2 (oscillation-harvest) — EDGE-FOUND (caveated).** Beats the deployed scalp (+1.95 paired, CI excl 0)
  on the headline; survives bar-END/85ms/chainlink; markout +8¢ confirms genuine lag (no stale-quote
  revert); LOCKED pair-neutral piece is positive IS & OOS & all THR. **BUT** the +2.24 is ~4× inflated
  by the size==0→DEEP refill assumption and is 63%-concentrated in the heavy-clip tail; the honest
  no-refill (1-clip) edge is **+0.52/slug OOS** (both-filled +2.27), still positive but thin, with 58%
  of slugs losing.

### Config of the surviving edge (V2, deployable form)
- Signal: per-side causal bar-END `|ret_C|≥3bp` (5s lookback) on `klines_1s`, BTC/ETH/SOL **5m only**
  (15m straddles 0). Fire each side at its own dip; `ev<0.55`; fill at decision+85ms.
- **Cap at ~1 clip per side per window** (the no-refill honest version) — do NOT rely on the multi-clip
  accumulation; that magnitude assumes infinite refill of a lagging quote.
- Pair `min(sh_up,sh_dn)`, hold to chainlink resolution; winner-only 0.07·p·(1−p) fee, fee-free redeem.
- Expected: ~+0.5/slug OOS pooled, ~+2.3/slug on the ~35% of windows where both sides fill.

### Next step (do NOT deploy capital yet)
1. **Resolve the refill question for real** — the deployable magnitude (+0.52) and the inflated one
   (+2.24) differ entirely on whether a lagging top-of-book ask refills $5+ every 5s for minutes. Walk
   the L25 *full depth* (not just top-of-book size==0→DEEP) on the heavy-clip winner slugs to see how
   many clips the real ladder actually supports before the book is consumed / repriced. If real depth
   supports ~2–4 clips, the edge sits between +0.52 and +2.24; if only 1, it's +0.52.
2. **Live shadow on 5m only**, 1-clip-per-side, $5 clips, ≥200 fires — judge by live wallet CI, not the
   backtest (per GROUND-TRUTH RULE; the deployed scalp's own OOS window is burned).
3. Park 15m (straddles 0) and the directional residual (−1.19 drag — hold only the matched pair, dump
   the unmatched leg at +60s rather than holding it directionally).

**Scripts:** `strategy_lab/directional/_sumpair_signal_lag_pair_instant.py` (V1),
`_sumpair_signal_oscillation_harvest.py` (V2), `_sumpair_signal_predictive_lean_hedge.py` (V3).
**Results:** `strategy_lab/directional/_results/sumpair_{signal_lag_pair_instant,oscillation_harvest,predictive_lean_hedge}_2026_06_13.parquet`.
**Shared causal machinery:** `scalp_fill_lib_2026_06_10.py` + the bar-END signal from
`scalp_causal_asof_oneshot_2026_06_12.py`.
