# Session findings — 2026-06-03 — engine forensics, ML phase, scalp/hedge/physics sweep

Consolidated record of an autonomous session. Read this + the per-topic reports cited.

## 1. Live vs paper engine forensics (Ireland vs VPS3, momo_HOLD_f7)
`ENGINE_COMPARE_IRELAND_VS_VPS3_MOMO_F7_2026_06_03.md`
- The two engines agree almost perfectly: 1329 windows, both-fire 76× (100% same direction, 0 opposite),
  70 shared resolutions with 0 mismatch. Headline PnL gap (+$5.92 live vs +$306.94 paper) = **stake size only**
  ($1 live vs $25 paper). Divergence = 10/1329 windows: 4 live `entry_rejected` (Polymarket **HTTP 425
  "service not ready"**, dropped with no retry), 3 VPS3 `qty_compute_failed`, 3 boundary ret_2m/threshold jitter.
- Specs written: `TV_AGENT_SPEC_POLY_ENTRY_425_RETRY_2026_06_03.md` (retry transient 425/5xx; entries are
  already GTC, exits already FAK — FOK is only the kill-switch, so "FOK→fill-what-it-can" was a non-issue).
- The entry_vwap band (B3): a price gate that skips deep-favorite (0.95–0.98) trap fires; shadow lacks it, live
  has it → add to shadow for apples-to-apples. Deterministic-threshold = make both hosts compute ret_2m + q90
  from the same bar snapshot (low priority, ~0 PnL).

## 2. ML phase — direction prediction is DEAD; the trap proven by a high-AUC model
`ML_AGENTIC_PHASE_PLAN_2026_06_03.md`, `META_LABELER_V1_2026_06_03.md`, `META_LABELER_V2_MICROSTRUCTURE_2026_06_03.md`
- **Phase-A re-validation** (`REVALIDATION_ENGINE_V2_2026_06_03.md`): of 6 cross-feature lockbox survivors,
  **5/6 die under production fills** (engine_v2 10Hz + 0.07 fee + latency). The high-n XF-I cells collapse to
  ~$0/tr — fee + 1Hz-fill artifacts. **Only DISAGR-HAWKES SOL 5m DN survives**: +$3.70/tr, t=2.84,
  CI[+1.42,+6.49], and a clean fill-selection test (the 2¢ spread filter rejects *losers*: filled WR 95.3% vs
  unfilled 75.7%, p<0.001). Spec'd as a shadow sleeve (`TV_AGENT_SPEC_SHADOW_DISAGR_HAWKES_SOL5M_2026_06_03.md`).
- **Meta-labeler v1 (TA features):** AUC 0.506 — TA carries zero info. No edge.
- **Meta-labeler v2 (microstructure):** **AUC 0.785 (5m) / 0.727 (15m) and STILL LOSES MONEY** (−$0.46 to
  −$1.43/tr; gating makes it worse). This is the priced-in trap in its purest form: the model predicts
  direction well, but the market already priced the same flow signal → `P(win)≈vwap`. **AUC ≠ edge. WR ≠ edge.**
- **Conclusion: stop trying to predict which side wins at fire time — the market is efficient w.r.t. every
  feature we can compute.** The microstructure's genuine predictive power belongs in EXIT-TIMING (the scalp
  doesn't bet the resolution), not direction bets.
- `meta_classifier/` scaffold: never ran, 4 leaks (15m ws_s anchor, label leak, un-purged CV, 0.50-mid label) →
  REWRITE; cannibalize the `hybrid_*` fire-universe builder.

## 3. Scalp / hedge / physics sweep (the autonomous block)
`SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md` (+ cache `scalp_hedge_physics_cache_2026_06_03.parquet`, 2533 filled fires)
- **EXIT-SCALP confirmed STRONG & robust.** Best policy = **TIME+45s** (deployed cell BTC+ETH δ≥5 vwap<0.55,
  n=118): **+$5.56/tr fee=0.015, t=6.9, CI[+4.0,+7.1]; +$4.24/tr at worst-case 0.07 both-leg fee.** HOLD = +$0.14
  (flat). Edge decays after ~90s. Positive across fit_OOS (t=2.65) and bwd_oos (t=5.13); BTC +6.95 > ETH +4.07;
  scales (δ≥3,vwap<0.55 n=398 +$3.86 t=8.36). Oracle ceiling +$18.5 → headroom exists. **Recommend exit +60s→+45s.**
  TP70-or-time60 = variance-reduced alt (+$5.18 t=7.8).
- **PHYSICS / VOLATILITY GATE = DEAD** (Block 2b within-asset control). The pooled "dist_abs improves scalp" was
  an **asset-selection artifact** ($-denominated threshold just selects BTC). Within BTC and within ETH the
  vol-regime gate adds nothing; the highest-vol tertile is *worse* in both. Volatility regime is not a lever here.
- **HEDGE = DEAD.** Stop-loss salvage lifts HOLD to +$2.46 (CI incl 0) but is far below scalping. Buy-opposite at
  a fixed exit is weak (+$1.2–1.4, CI incl 0). The +$18 `opp_ask_min` is LOOKAHEAD, not tradeable. **Always-sell
  at +45/60s dominates any hedge/salvage.**

## 4. Net deployable picture (unchanged thesis, sharper)
- **The exit-scalp is the one real edge** (lag-taker entry δ≥5 vwap<0.55, TIME+45–60s book-sell, BTC-weighted,
  no vol gate, no hedge). Offline OOS strong; **the open gate is still ≥200 LIVE forward fires + CI>0** — the
  16 shadow sleeves exist for this.
- **DISAGR-HAWKES SOL 5m DN** is a second shadow candidate (spec written) — accumulate forward fires.
- **Everything else** (direction ML, physics/vol gates, hedge, the other 5 cross-feature survivors) is dead,
  priced-in, or an artifact. Direction prediction at fire time is efficient-market-dead, proven three ways.

## 5. Open / next
1. Deploy the 2 specs (425-retry; DISAGR-HAWKES shadow). Flip scalp exit +60→+45.
2. P2 exit-timing MODEL (the only live ML target): can the microstructure (AUC 0.78 on direction) predict the
   intra-window *reprice path* to beat fixed +45s? Oracle ceiling (+$18.5) says large headroom.
3. Keep watching the live scalp forward fires toward the ≥200/CI>0 bar.
