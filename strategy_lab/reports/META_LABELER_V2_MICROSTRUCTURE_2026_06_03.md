# P1/P4 Meta-Labeler v2 — microstructure relative-value — 2026-06-03

Model=XGBoost. P(Up) from FLOW/BOOK features only (price/vwap excluded). Bet side with edge=P-vwap>margin. win07 fee. Purged-WF dev + time lockbox(25%).

| cell | n | lock n | AUC dev | AUC lock | margin | ALL-pref $/tr | ALL CI | GATED n | GATED $/tr | GATED CI | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|
| 5m@120 | 19017 | 4755 | 0.778 | 0.785 | 0.0 | -0.461 (57.5%) | [-1.32,+0.422] | 3563 | -0.641 (57.9%) | [-1.55,+0.282] | no lift |
| 15m@240 | 6339 | 1585 | 0.715 | 0.727 | 0.26 | -1.427 (59.4%) | [-2.623,-0.253] | 132 | -3.281 (50.0%) | [-7.224,+0.811] | no lift |

## VERDICT — the priced-in trap, proven by a high-AUC model that LOSES MONEY

This is the cleanest demonstration of the trap in the whole project:

- **The microstructure model PREDICTS DIRECTION WELL: AUC 0.785 (5m), 0.727 (15m) on the time-held-out
  lockbox.** Flow/book features at fire-time genuinely forecast the resolution.
- **And it still LOSES money: every cell negative $/tr** (5m −$0.46, 15m −$1.43; gating makes it WORSE,
  −$0.64 / −$3.28). The 15m "high-edge" gated fires (margin 0.26, n=132) are the *worst* (−$3.28, 50% WR) —
  the deepest traps.
- **Mechanism:** the same microstructure that predicts the outcome is ALREADY in the price you pay.
  `P(win) ≈ entry_vwap` (efficient market); where the model thinks `P(win) > vwap`, it is simply wrong
  (those gated fires lose more). **AUC ≠ edge. WR ≠ edge.** A 0.78-AUC classifier is worthless for a
  hold-to-resolution bet because the market priced the same signal.

**This kills the P1/P4 "predict the bet" line for hold-to-resolution.** Both v1 (TA, AUC 0.51, no info) and
v2 (microstructure, AUC 0.78, fully priced-in) fail to beat the market on direction. Stop trying to predict
which side wins — the market is efficient w.r.t. every feature we can compute at fire time.

## THE PIVOT — the high-AUC microstructure model belongs in EXIT-TIMING (P2), not direction bets

The 0.78 AUC is REAL predictive power about near-term price movement — it's just wasted on hold-to-resolution
(priced in). But the **exit-scalp does NOT bet the resolution** — it buys cheap and SELLS into the intra-window
reprice at ~+60s. There, predicting the *price path* (not the final outcome) is exactly what a high-AUC
microstructure model can do, and it is NOT necessarily priced into the resolution-referenced book.

**Redirect the ML phase:** the next model is a **P2 exit-timing / path model** that uses these same
microstructure features to predict *when/whether the bought token reprices favorably before decay*, feeding
the deployed exit-scalp's exit policy (currently a fixed +60s). That is the one application where the model's
genuine predictive power is not arbitraged away by the resolution price.

## Notes
- Features = microstructure/flow only (mp_skew, imb, hawkes, vpin, lm jumps, regime, adx...). All price/vwap excluded.
- Label/PnL use master 1Hz fills — re-fill any deployable cell at 10Hz (Phase-A lesson). AUC is diagnostic; gate is win07 $/tr CI>0.
- ALL-pref = take every fillable fire on the model's higher-edge side (baseline). GATED applies the margin.
- Offsets pre-registered (5m@120=prod t+120, 15m@240); assets pooled with dummies; one row per slug.