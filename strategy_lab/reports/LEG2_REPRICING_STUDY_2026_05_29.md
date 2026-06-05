# Leg-2 Repricing Window + Complete-Set Lock Feasibility — DEEP STUDY (2026-05-29)

> Quantifies the killer of the "Buy → Wait → Hedge" lock strategy (§5.3 of
> `STRATEGY_BUY_WAIT_HEDGE_LOCK_2026_05_29.md`): after the leading side appreciates,
> how long (ms) does the complement's ask stay cheap enough that the complete-set
> sum is lockable (< 0.97 under the 0.07 fee curve)? **Answer: 0 ms. Never.**

## TL;DR verdict
**The lock window does NOT exist at any latency.** The complement's ask reprices
*synchronously* with the leading side — UP and DOWN best-asks move in near-perfect
lockstep (ask-increment correlation **−0.88 to −0.92**), and their sum is pinned at
**1.01** at every observed moment. Across ~480 slug-windows the complete-set top-of-book
sum **never once dropped below $1.00**, let alone the 0.97 lock threshold. Dwell-time p50
= **0 ms**; lock-reachable fraction = **0.0000** at ≤500 ms (and at +0 ms / +85 ms Ireland
latency / +2 s alike). **The idea is dead at our infra — not because we're too slow, but
because there is no transient dislocation to be slow *for*.** Polymarket's quoting keeps
both legs arbitrage-tight in real time.

## Method
- Data: `load_orderbook_l25_streaming(asset, slugs, subsample_1hz=False)` — BOTH UP and
  DOWN token books at NATIVE 10 Hz. Universe = today's harvest: BTC 5m + 15m, SOL 15m,
  ETH 15m. Sampled the **freshest 350 slugs/cell** (the most relevant to current infra).
- Repricing event: leading-side best-ask rises ≥ MOVE (0.05 and 0.10) over a LOOKBACK
  window (10/30/60 s) inside the prediction window. ~82k events detected.
- Dwell: from event time `t0`, time the complement ask stays ≤ `1 − lead_ask(t0) − 0.03`
  (i.e. sum < 0.97). `dwell = 0` ⇒ complement had already repriced by `t0`.
- Complete-set cost: walk BOTH ask books for **$25** at `t0 + {0, 85, 500, 1000, 2000} ms`;
  `up_vwap + dn_vwap`. Lock breakeven (0.07 curve): `sum < 1 − 0.07·up(1−up) − 0.07·dn(1−dn)`.
- Sanity cross-check (`leg2_sanity_v1.py`): min top-of-book sum across the *entire* window,
  no event gating — confirms the dwell=0 is real, not a logic bug.

## 1. Repricing dwell-time distribution (ms) — per asset/tf

| asset | tf | move | lookback | n | frac lockable @t0 | p25 | p50 | p75 | p90 | max |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC | 5m | 0.05 | 10 | 4856 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| BTC | 5m | 0.10 | 10 | 2514 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| BTC | 15m | 0.05 | 10 | 7382 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| BTC | 15m | 0.10 | 10 | 2410 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| ETH | 15m | 0.05 | 10 | 6852 | 0.0 | 0 | 0 | 0 | 0 | 0 |
| SOL | 15m | 0.05 | 10 | 5446 | 0.0 | 0 | 0 | 0 | 0 | 0 |

*(All 24 move×lookback×asset×tf cells identical: `frac_lockable_at_t0 = 0`, all
percentiles = 0 ms, max = 0 ms. Full table in `_results/leg2_dwell_summary.csv`.)*

**No event in ~82,000 ever had the complement starting lockable.** The complement is
already at its repriced level the instant the move completes. There is no dwell window —
not at p90, not the single max observation.

## 2. Complete-set sum evolution (median, $25 walk both books)

| asset | tf | +0 ms | +85 ms | +500 ms | +1 s | +2 s | n |
|---|---|---:|---:|---:|---:|---:|---:|
| BTC | 5m | 1.0115 | 1.0124 | 1.0100 | 1.0100 | 1.0100 | 4856 |
| BTC | 15m | 1.0144 | 1.0144 | 1.0130 | 1.0123 | 1.0119 | 7382 |
| ETH | 15m | 1.0267 | 1.0269 | 1.0262 | 1.0254 | 1.0245 | 6852 |
| SOL | 15m | 1.0420 | 1.0423 | 1.0418 | 1.0412 | 1.0403 | 5446 |
| **POOLED** | | **1.0226** | **1.0227** | **1.0207** | **1.0200** | **1.0200** | 24536 |

The sum is **already ≥ 1.01 at +0 ms** and stays flat/slightly worse out to 2 s — there
is no early-fill bargain that erodes with latency. The $25 walk adds depth slippage on
top of the 1.01 top-of-book floor (SOL widest at 1.04 — thinnest book). At Ireland's
85 ms RTT the sum is identical to +0 ms — latency is irrelevant because the dislocation
isn't there to begin with.

## 3. Lock-reachability — fraction lockable within ≤500 ms (0.07-curve breakeven)

| asset | tf | n | frac lockable |
|---|---|---:|---:|
| BTC | 5m | 4856 | **0.0000** |
| BTC | 15m | 7382 | **0.0000** |
| ETH | 15m | 6852 | **0.0000** |
| SOL | 15m | 5446 | **0.0000** |
| **POOLED** | | 24536 | **0.0000** |

Zero of 24,536 post-move events ever offered a $25 complete set below the 0.07-curve
breakeven within a reachable window. (Also zero at +0 ms — speed buys nothing.)

## 4. Cross-side correlation — why the window is zero

| asset | tf | n_slug | med mean-sum | med min-sum | med frac(sum<0.97) | med ask-incr corr |
|---|---|---:|---:|---:|---:|---:|
| BTC | 5m | 350 | 1.0119 | 1.01 | 0.0 | **−0.904** |
| BTC | 15m | 350 | 1.0113 | 1.01 | 0.0 | **−0.916** |
| ETH | 15m | 350 | 1.0137 | 1.01 | 0.0 | **−0.896** |
| SOL | 15m | 350 | 1.0181 | 1.01 | 0.0 | **−0.880** |

UP and DOWN ask *increments* are anti-correlated at ≈ **−0.9**: when UP's ask ticks up,
DOWN's ask ticks down by almost exactly the same amount, **on the same 10 Hz snapshot**.
The two asks are mechanically tied to sum ≈ 1.01 — there is no genuine transient
dislocation, only the constant ~1¢ cross-token spread (two half-spreads).

### Sanity cross-check (no event gating, whole-window min)
`leg2_sanity_v1.py` over 480 slug-windows: per-cell **min top-of-book sum ever = 1.000–1.001**;
**0% of slugs** ever dipped below 0.97. Pooled top-of-book sum percentiles: p0.1 = **1.0010**,
p1–p50 all = **1.0100**, absolute min = **1.0000**, **frac(sum < 1.00) = 0.00000**.
⇒ the dwell=0 is a genuine market-microstructure fact, not a code artifact. The book is
*never* lockable — there is literally no point in the data where buying both sides costs < $1.

## Verdict — is the disciplined lock ever reachable?
**No. Dead at our infra, and dead at any infra.** This is not a latency race we're losing:
- The naive thesis assumed a window where Up has appreciated but Down's *ask* is still
  stale-cheap. **That window has zero width.** Polymarket's matching engine reprices both
  legs synchronously (anti-corr −0.9), keeping `up_ask + dn_ask ≈ 1.01` continuously.
- Even at +0 ms with perfect top-of-book fill the complete set costs ≥ $1.00 — there is no
  sub-$1 set to grab, so Ireland's <2 ms vs a colo's <100 µs makes no difference.
- The $0.011 floor above $1 is the irreducible **two-half-spread** cost. To lock you'd need
  sum < 0.97 → ~4¢ of free dislocation that simply does not occur in this market.

This **confirms and hardens** the §4 "execution trap" and the `LATENCY_EDGE_FINDING`
realistic-hedge result (mean pair cost $1.09 there; this study shows even the *best*
instantaneous moment is ≥ $1.00). The reverse-lag / leg-2 hedge is not exploitable.

**Implication for the live strategy:** keep the directional fast-taker (hold to
resolution) as the expression of the binance→chainlink lag edge. The lock/hedge overlay is
a **variance reducer at best, never an alpha adder** — and the "complete a cheap set"
mechanic should be retired from the lock-strategy roadmap. The only place sub-$1 basket
buying is real remains the multi-outcome neg-risk basket (different markets) — not these
binary up-down books.

## Artifacts
- `strategy_lab/directional/leg2_repricing_study_v1.py` (main study)
- `strategy_lab/directional/leg2_sanity_v1.py` (whole-window min cross-check)
- `_results/leg2_dwell.csv`, `leg2_dwell_summary.csv`, `leg2_cost_evolution.csv`,
  `leg2_cost_summary.csv`, `leg2_reachability.csv`, `leg2_reach_summary.csv`,
  `leg2_crossside_corr.csv`, `leg2_corr_summary.csv`
