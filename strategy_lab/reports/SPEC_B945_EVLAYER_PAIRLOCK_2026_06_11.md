# STRATEGY SPEC — "EV-Layer / Pair-Lock" (decoded from `0xb945945d` + operator's own article)

_2026-06-11. Provenance: wallet `0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68` (pseudonym `l5Zn1bWoM8eTsK`
== article author's public wallet `@l5zn1bwom8etsk` — CONFIRMED same entity). Decode report:
`WALLET_B945945D_PAIRSUM_ARB_2026_06_11.md`. Analysis scripts: `wallet_hunt/_b945_analyze{,2,3}.py`._

---

## 0. Ground truth vs article — what the tape actually shows

| Article claim | Tape evidence (3,500 fills, 2,010 settled mkts, Mar 19 → Jun 11) | Verdict |
|---|---|---|
| "scanning 5m/15m/1h across BTC ETH SOL XRP" | 100% `btc-updown-15m`, every week, all 12 weeks | **Embellished.** One sleeve only. |
| EV layering across the whole price curve | BUY fills span the full curve: 0–10¢ (471), 10–30¢ (752), 30–55¢ (885), 55–80¢ (846), 80–97¢ (476), ≥97¢ (70) | **TRUE — this is the core.** |
| Chainlink/CEX order-flow lag entry | Mid-curve entries (0.30–0.80) fire EARLIEST (p10 offset 81–112s, med ~380–400s of 900s) — needs a live directional signal | **Consistent** |
| Drawdown map → hedge triggers | Cheap bands (≤0.30) fire LATE (med 639–757s) on the *opposite* side of earlier entries; side-alternation rate med 0.27 (blocks, then switch) | **TRUE — hedging leg confirmed** |
| Sweeper at 99.2–99.8¢ with standing bids | 70 fills ≥0.97 (med offset 807s, p90 856s), $1,559 notional; **MAKER_REBATE $3,622.57 / 46 events** proves real resting-order fills | **TRUE but small** |
| "$20k profit" | lb /profit $20,661 ≈ Alchemy net cash $19,734 | **TRUE** |
| Exits / stop-losses | 54 SELLs vs 3,500 BUYs (1.5%) — there is **no exit engine**. Exit = hold to resolution + REDEEM ($1.33M gross redeemed) | Article's "exit logic" talk is about *hedging*, not selling |
| CPU pinning / 0.3ms hot path | Clip sizes $5 median, $30 max; 87 fills/market | Matters only for his sweeper queue position; irrelevant to the pair-lock core |

**The real machine (his words decoded by his fills):** a *directional* lag-taker entry mid-curve early in
the window → *drawdown-map-conditioned* accumulation of the OPPOSITE leg later, when it's cheap → endgame
near-certainty sweeps. The net effect is what we measured: **matched Up+Down pairs at blended cost
~$0.94–0.96 (89.7% of markets < $1.00), redeemed at $1.00** — locked +4–6¢/pair, ~80% direction-neutral,
plus rebate income on the resting legs. It is NOT instantaneous pair-arb (book overround is always ~1.01);
the pair is assembled **across time** as the window oscillates.

### Answers to the three operator questions
1. **Entry / exit logic:** Enter directionally (taker) when the oracle/CEX feed leads the Poly quote;
   add the opposite leg later via cheap-side accumulation (mostly resting bids — rebate evidence) until the
   pair is matched below $1; never sell; hold everything to resolution and redeem. Residual unmatched
   exposure ≈ 20.8% of matched — that's his only directional risk, and it's signal-aligned.
2. **Period inside the slug he buys:** entries start ~80–110s after slot open (signal needs price action),
   directional core med ~380–400s, hedge accumulation med ~640–760s, sweeps med ~810s, p90 ~856s. He is
   active across the ENTIRE 900s window, with role-by-phase: signal → hedge → sweep.
3. **The lag indicator:** Chainlink Data Streams (the very oracle that RESOLVES these markets) moving with
   conviction while the Polymarket CLOB has not repriced — confirmed/filtered by CEX order flow (CVD from
   aggressive taker flow + order-book imbalance) and 1m candle delta. I.e. **fair-prob(from oracle+CEX
   flow) − implied-prob(Poly mid)** = the mispricing gap; he enters where the gap is widest and sizes
   proportionally to it. This is the same lag family as our deployed exit-scalp (entry_vwap<0.55 @ +5s).

---

## 1. What is USEFUL for us vs already-tested-dead (house audits apply)

| Module | Status for us |
|---|---|
| **A. Temporal pair-lock accounting** (convert directional entries into locked pairs <$1) | **NEW — nothing in our 696 reports does this.** The single genuinely novel mechanic. Converts our scalp's biggest weakness (forced +60s taker sell, paying the spread to exit) into a hold-to-redeem with NO exit transaction at all. |
| **B. EV layering / full-curve sizing** | New as a *sizing* framework; we trade fixed bands. Useful, second priority. |
| **C. Drawdown map (P(drop≥X | price=p, t))** | Cheap to build from our own canonical (resolutions + L25/BBO trajectories). Useful as the hedge-trigger function for module A. |
| **D. Lag indicator (oracle+CVD vs Poly)** | Already ours: it IS the scalp entry edge. We have chainlink_rtds live + `cex_futures_trades` (CVD-able) + 1s klines. No new build needed; optionally add CVD confirm to scalp entry as a separate test. |
| **E. Sweeper (maker bids ≥0.97 late)** | ⚠️ **We tested this DEAD 2026-06-11** (`MAKER_SIM_RESULTS`: late favored-bid conservative fills 1/16,376; `ORACLE_SNIPE_RESULTS`: z≥2 winner quoted at ~$1.00, visibly-cheap favorites adversely selected). His $3.6k rebates prove *he* gets filled — almost certainly via queue position from very-early placement, which our conservative price-through fill model cannot credit. **Do NOT re-open offline** (rule banked). Only admissible test = tiny live probe, and only AFTER module A validates. |
| F. CPU pinning / hot path | Irrelevant for A–C (his own clips are $5 and spread out over minutes). Park. |

**Scale honesty:** his lifetime is ~$230/day on $1.1M turnover with ~$590/day in the recent hot window.
This is a grinder, not a treasure chest. The reason to build it anyway: module A is ~direction-neutral,
uncorrelated with our scalp PnL, uses data + venue plumbing we already own, and compounds with our
existing lag signal (we likely have a BETTER entry trigger than he does — ours is OOS-validated).

---

## 2. THE SPEC — `pairlock_btc15m_v1`

### 2.1 Universe & session
- Markets: `btc-updown-15m-*` only (his choice is correct: tightest book ~1¢ spread, longest window,
  enough intra-window oscillation). Extension to ETH-15m only after BTC validates.
- Trade every consecutive window (no market selection — breadth IS the selection).
- All timestamps UTC; slug suffix = `slot_start` (s); window = [slot_start, slot_start+900).

### 2.2 State per market
```
Q_up, Q_dn          # accumulated shares per leg
C_up, C_dn          # accumulated USDC cost per leg
matched = min(Q_up, Q_dn)
pair_cost(blended) = C_up/Q_up + C_dn/Q_dn        # on matched qty
locked_pnl = matched * (1 - pair_cost)            # realized at settlement
residual  = |Q_up - Q_dn|                          # directional exposure
```

### 2.3 Module A1 — directional lag entry (taker), t ∈ [60, 780)s
Reuse the validated scalp entry, unchanged semantics:
- Signal: `delta = chainlink_rtds_px - strike` with `|delta| >= 3` ($5 stake) / `>= 5` ($25), evaluated
  at `slot_start + offset` and continuously after; direction = sign(delta).
  Optional (separate A/B, NOT in v1): CVD confirm = sign of 10s aggressive-flow imbalance on
  `cex_futures_trades` agrees with delta.
- Entry filter: `entry_vwap(signal side, $stake book-walk) < 0.55`; same-token spread ≤ 0.05.
- Action: taker BUY signal side, clip ≤ $25; re-entry allowed on fresh signal if leg cap not hit.
- Leg cap: `C_side ≤ $75` per market (3 clips) in v1.

### 2.4 Module A2 — hedge accumulation (the pair-lock), t ∈ [entry, 870)s
The novel half. Goal: complete pairs below $1.
- Compute `pair_completion_price p* = (1 - pair_cost_target) - C_held/Q_held_avg` — operationally:
  for current holdings, the max price on the OPPOSITE leg s.t. blended pair_cost ≤ **0.97** (v1 target;
  his realized median 0.94 → leave margin for our worse fills).
- Trigger (drawdown map, §2.6): when opposite-leg ask ≤ p* **and** the map says
  `P(further drop ≥ 3¢ | price, t_remaining) < 0.45` (don't catch a falling knife too early),
  taker BUY opposite leg up to `matched_target = Q_held`.
- Resting variant (v1.1, behind flag, default OFF): post GTC bid at `p* − 1¢` immediately after A1 entry,
  cancel at t=870s. This is where his rebates come from; our maker sims say conservative fills ≈ 0, so
  v1 ships TAKER-ONLY and the resting variant is a live-probe question only.
- If the opposite leg never gets cheap enough: carry the residual directionally (this is exactly his
  20.8% residual). The A1 signal already gives the residual positive drift — the corrected-harness scalp
  numbers (+$1.85/tr pooled) bound this from below.

### 2.5 Module A3 — endgame, t ∈ [870, 900]s + settlement
- NO selling. NO +60s exit (this strategy replaces the exit with redemption).
- v1 does NOT include the ≥0.97 sweeper (dead in our sims as taker; maker variant = live probe later).
- Settlement: REDEEM winning leg (matched → $1/pair guaranteed; residual → win or zero).
- PnL per market (0.07 winner-only curve, taker has no fee on Poly — fees enter via the spread we cross;
  REDEEM pays face): `locked_pnl + residual_pnl − costs already embedded in C_*`.

### 2.6 Drawdown map (build once, refresh monthly)
From canonical (resolutions + BBO/L25 trajectories, **single-read discipline — this is NOT the burned
Mar30–Apr21 BBO window question; use production-era data Apr 22+**):
- Table `D[price_band 2¢ × t_remaining 30s] = {P(maxdrop ≥ 5¢), P(maxdrop ≥ 10¢), P(maxdrop ≥ 24¢)}`
  computed on BTC-15m token mid trajectories.
- Used ONLY as the A2 hedge-timing gate + (later) A1 entry-price veto (his "avoid 72¢" claim —
  verify, don't trust).

### 2.7 Sizing (EV-layered, simplified to defensible v1)
- Stake per A1 clip: proportional to mispricing gap `g = |fair_prob − poly_mid|` capped:
  `$5 × clip_mult(g)`, clip_mult ∈ {1, 2, 5} for g ∈ {[0.03,0.06), [0.06,0.10), ≥0.10}.
- A2 hedge clips sized to complete `matched_target` only — never over-hedge past Q_held.
- Per-market max outlay $150; global concurrent exposure cap $600 (4 overlapping windows max — 15m
  windows overlap with 5m? No — 15m sequential, so cap is effectively 1–2 markets + settle lag).

### 2.8 Infra mapping (all exists)
- Signal feed: VPS3 chainlink RTDS collector (live) — same anchor as scalp sleeves, `ws_s` convention N/A
  here (we anchor on slot_start + continuous, like the scalp).
- Books: Ireland WS BookMirror (Tier-1) — both tokens of the market.
- Execution: existing scalp order path (taker FOK/IOC); REDEEM path exists (resolution engine).
- Host: deploy as new sleeve family `shadow_pairlock_btc_15m_v1` on VPS3 shadow first, Ireland live later.

### 2.9 Validation gates (house rules — ALL mandatory before any live $)
1. **Backtest with the corrected harness** `scalp_fill_lib_2026_06_10.py` primitives (size==0 carry-forward,
   no outcome fallback, 120s staleness guard) extended with a `PairState` accountant. Window: production
   canonical Apr 22 → Jun 11 (L25 BTC native 10Hz, `subsample_1hz=False`). Fee: 0.07 winner-only on the
   residual leg wins; matched pairs redeem at face.
2. Pre-registered metrics: locked_pnl/market, residual_pnl/market, blended pair_cost distribution
   (target: median ≤ 0.97 reproduced), %markets pair-completed, $/day at $5 and $25 scale.
3. **Trial-counted DSR** (ml4t, n_trials = every parameter cell touched), ex-top2 outlier robustness,
   priced-in-trap check (WR≠edge), fill-haircut sensitivity ±1¢ on every A2 fill.
4. Shadow ≥200 markets on VPS3 (twin config), judge by dedup dashboard metric, live CI>0 per stake.
5. Only then: Ireland live $5. The sweeper/maker probe is a SEPARATE later decision gated on A-validation.

### 2.10 Kill criteria
- Backtest: blended pair_cost median > 0.985 net of haircut, or locked_pnl/day < $5 at $25 scale → archive.
- Shadow: pair-completion rate < 50% of backtest, or residual losses exceed locked gains over n≥100 → kill.

---

## 3. Expected economics (prior, to be replaced by backtest)
His realized: ~4–6¢/pair locked, ~87 fills/market at $5 clips, ~$230/day lifetime ($590/day hot) on
$1.1M turnover. Our version starts narrower (taker-only hedge, fewer clips) → prior estimate $30–80/day
at $25 clips IF pair-completion reproduces. The asset is the neutrality, not the magnitude.

## 4. Explicit non-goals of v1
- No 5m/1h, no ETH/SOL/XRP, no sweeper module, no maker resting bids, no CPU-pinning work,
  no sells before resolution, no EV-curve scanner beyond the 3-tier clip_mult.

## 5. Open questions (carry into backtest)
1. Does pair completion below $0.97 survive our conservative fill model at 10Hz? (his fills may rely on
   resting-bid queue position we refuse to credit offline)
2. Is the A1 leg even necessary, or does pure two-sided cheap-leg accumulation (no directional signal)
   complete pairs as well? (test both arms — if signal-less arm works, it's simpler and fully neutral)
3. Drawdown-map gate value-add vs naive `ask ≤ p*` trigger (ablation).
4. His "avoid 72¢ entries" claim — verify on our data before adopting any entry-price veto.
