# SUM-PAIR ARBITRAGE — Verdict + Shadow-Test Plan (2026-06-13)

Deep-research target: paper **2508.03474** ("Market Rebalancing Arbitrage") + 0xSurferX/Luoye "binary hedging"
(buy Up+Down when ask-sum < $1, hold to resolution; one leg pays $1 → keep the difference, direction-agnostic).

## 1. What the sources actually teach
- **Two arb types in the paper.** (a) **Combinatorial** (cross-market dependencies, e.g. "Trump wins" vs "GOP margin")
  — **N/A to us**, our crypto markets are single-condition. (b) **Rebalancing / sum-pair** (single market sum_ask<1)
  — applies to our BTC/ETH/SOL/XRP/DOGE/BNB Up/Down 5m+15m markets.
- **0xSurferX/Luoye reality:** not a clean simultaneous buy-both — a **sequential legging-in**: detect overreaction
  (a side crashes), buy the cheap leg, try to complete the hedge (`leg2Price = SUM_TARGET − leg1Price`); if the
  hedge fails → single-leg directional risk managed by TP/floor/stop. Their own listed risks: "no opportunity in
  calm markets," "single-leg exposure if leg 2 never fills," "threshold trade-off."

## 2. Prior internal evidence (all consistent, all negative)
- **ce25 wallet** (taker buy-both-hold): profitable on-chain BUT **97% of income is winner-leg resolution recovery,
  CLOB-only net was −$9,117** → it's a neutral two-sided book recovering via the $1 winner, **not pure sub-$1 capture**.
  Overround: median sum_ask **1.041**, only ~35% of slugs ever dip <1.0. DEPLOY-NO, pre-registered test owed.
- **b945 wallet** (maker paired ladders): queue-aware sim **SIG-NEG** every policy (adverse selection — filled when
  flow is toxic). Taker fixes the fill problem but inherits the overround + fees.
- **LEG2 study** (top-of-book): legs reprice in **−0.9 lockstep**, dips barely lockable.
- **Maker-arb censoring reversal:** the old maker "edge" was survivorship bias (losers never log a REDEEM).

## 3. The pre-registered test, finally RUN (`sumpair_arb_t1_2026_06_13.py`)
Atomic taker buy-both-hold. Causal first-cross detection of sum_ask<θ → fill at first L25 snapshot ≥ detect+85ms
(our measured live latency) → real depth walk on BOTH legs → true chainlink resolution → winner-only 0.07 fee.
Threshold sweep θ∈{0.99..0.95}, $25 stake, BTC/ETH/SOL × 5m/15m, 1,400 slugs/cell, slug-level bootstrap CI.

**RESULT — DEAD as a taker. Every cell SIG-NEGATIVE:**

| θ | opt $/pair (fill at dip instant) | **lat $/pair (realistic 85ms)** | latency haircut |
|---|---|---|---|
| 0.99 | −0.014 | **−0.070** [−0.072,−0.068] | +0.056 |
| 0.98 | −0.004 | **−0.075** [−0.077,−0.072] | +0.070 |
| 0.97 | +0.004 | **−0.078** [−0.082,−0.075] | +0.083 |
| 0.96 | +0.017 | **−0.083** [−0.088,−0.078] | +0.100 |
| 0.95 | +0.029 | **−0.082** [−0.088,−0.076] | +0.111 |

Per coin (θ=0.97, lat): BTC −0.044/−0.055 (5m/15m), ETH −0.076/−0.069, SOL −0.112/−0.091. **SOL worst (thinnest).**

**Mechanism:** the arb math is real (`opt` > 0 below 0.97), but the dip is a **single-snapshot (<100ms) transient**.
At 10Hz, "fill 85ms later" = the next snapshot, and the book has already reverted to ~1.01 (the overround). You
detect sum<0.97 but fill at ~1.01 → pay the overround → lose 5–11¢/pair. The **deeper the dip, the faster it reverts**
(haircut grows +0.056→+0.111 as θ drops). This is the non-atomic execution risk the paper warns about, quantified.

**Verdict: the taker sum-pair arb is DEAD on our infra. Do NOT deploy it.** Confirms ce25/b945/LEG2.

## 4. What is genuinely STILL unresolved (the only reason to shadow at all)
Historical L25 is **10Hz** → it cannot see sub-100ms dynamics. Two questions it can't answer:
1. **True dip duration** at full WS frequency — is the dip really <100ms, or does it sometimes persist 200–500ms
   (capturable by a fast taker)?
2. **Resting-maker capture** — a limit bid resting *before* the dip can be hit by the very flow causing it, filling
   at the favorable price *without* crossing 85ms later. b945's sim says this is adverse-selection-negative, but that
   was a model; live WS with real fill semantics is the only true test.

Everything else is closed. The taker path is proven dead; only sub-100ms maker capture remains open, with a strong
negative prior.

## 5. SHADOW TEST PLAN — `sum_pair_monitor` (observe-only, $0)

**Purpose:** NOT to trade — to record live sub-100ms dip dynamics and virtually test the maker-capture hypothesis,
to definitively close (or reopen) the question with live evidence. Piggybacks the existing TV shadow infra.

### Logic
For each ACTIVE BTC/ETH/SOL (+XRP/DOGE/BNB if books exist) Up/Down 5m+15m slug:
1. **On every WS book update** (Tier-1 BookMirror, ~10–200/s event-driven), compute `sum_top = ask_up0 + ask_dn0`
   and `sum_walk25 = vwap_up($25) + vwap_dn($25)`. Log every tick where `sum_top < 1.00`.
2. **Dip-event record:** for each sub-1.0 episode → onset_ts, duration_ms (time sum stays <θ), min_sum, depth ($ on
   both legs at min), revert_ms. → measures TRUE dip duration (the thing 10Hz can't).
3. **Virtual TAKER control:** at detection (sum<θ), simulate buy-both filled at the book **+{50,85,150}ms** later
   (use the real subsequent WS frames). Books to true resolution + winner-only fee. Confirms/refutes the −5¢ finding live.
4. **Virtual MAKER test (the real question):** maintain a resting limit bid on each leg at `p` such that
   `p_up + p_dn = 0.965` (below the 0.97 gate). Mark a leg FILLED when the live book's best ask ≤ your bid during the
   episode (a seller crosses you). Require BOTH legs filled within `T_hedge=20s`; if only one fills → single-leg,
   apply floor/stop per Luoye and record the directional outcome (this is where adverse selection shows up).
5. **Resolution join:** at slot end, `load_resolutions` (chainlink) → book each virtual pair: winner +$1·shares,
   loser $0, winner-only 0.07 fee.

### Engines / components (mostly already exist)
| Component | Source / reuse |
|---|---|
| Live dual-token WS book | Production Tier-1 `ws_mirror` (already live; subscribe Up+Down per slug) |
| Walk / fill primitive | `strategy_lab/engine_v2.py` `book_walk_fill` + `LiveMimicConfig` (85ms, winner-only fee) |
| Virtual maker fill rule | NEW: "best_ask ≤ resting_bid during episode" crossing detector (full-freq) |
| Resolution truth | `load_resolutions` (chainlink) |
| PnL metric | sleeve **dedup metric** (`sleeves.py _RESOLUTION_DEDUP_ROW_NUMBER`, exclude `fill_method='synthetic'`) |
| Sink | new sleeve type `sum_pair_monitor` → `_tv_cards_feed.json` + a parquet of dip-events |
| Pre-subscribe | reuse the Kalshi `status=unopened` pre-subscribe pattern so the book is warm at slot open |

### Spec deliverable
Write `TV_AGENT_SPEC_SUMPAIR_MONITOR_2026_06_13.md` for the TV agent: new observe-only sleeve, both hosts, logs
dip-events + virtual taker/maker fills, **places zero real orders**.

### Promotion gates (pre-registered)
- **Taker virtual** → expected CI<0 (confirms backtest). If so: **close the taker path permanently.**
- **Maker virtual** → escalate to a **$1 live maker probe** ONLY if, over **≥4 weeks / ≥200 completed pairs**:
  (a) both-legs-fill rate ≥ 30% of dip episodes, (b) net $/pair CI>0 after winner-only fee, (c) **ex-top2 outlier
  robust**, (d) single-leg (hedge-fail) residual not net-negative. Else: **file sum-pair arb FULLY DEAD** (taker
  proven, maker refuted live) and stop.

## 6. One-line bottom line
The famous "sum-pair / $10k-month" arb is **mathematically real but not capturable as a taker on our 85ms infra**
(dips revert in <100ms; you pay the overround → −5 to −11¢/pair, SIG-NEG everywhere). The only unclosed door is a
**sub-100ms resting-maker capture**, which has a strong negative prior (b945) — worth at most a **$0 observe-only
shadow** to close it with live evidence, not real capital. **No taker deployment.**
