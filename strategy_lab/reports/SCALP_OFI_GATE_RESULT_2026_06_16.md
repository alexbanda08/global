# Scalp × Binance 1s taker-OFI gate — RESULT: DEAD (2026-06-16)

Tested the 5-lens audit's #2 free idea: gate the deployed lag-scalp on Binance taker-order-flow-imbalance
(the aggressor flow that *caused* the move), thesis = high |OFI| → move persists → +60s sell wins more.
Script `scalp_ofi_gate_2026_06_16.py`; data `_results/scalp_ofi_gate_2026_06_16.parquet`.

## Method
Production window (Apr22+, where `klines_1s.taker_buy_base` is populated on live-WS rows; vision-backfill rows
NULL → OOS BBO window unusable). Deployed scalp: causal bar-END 5s return ≥3bp at slot_start, fire +5s, L25
book-walk $25 (ev<0.55, spread≤0.05), +60s sell. OFI over the [ss, ss+5s] signal window = `2·Σtaker_buy/Σvol −1`,
signed-aligned to the lead. BTC/ETH/SOL × 5m/15m, 1400 slugs/cell → 293 gated fires, 125 with computable OFI (43%).

## Result — DEAD
- **No dose-response.** $/tr by ofi_aligned quintile: Q1 +2.39, Q2 −1.26, Q3 +2.62, Q4 +1.84, Q5 +0.92 — non-monotone,
  no signal. Win-rate drifts DOWN with OFI alignment (Q1 0.72 → Q5 0.56).
- **Gating lowers $/tr:** base (all gated fires) +2.23/tr (t=5.14); ofi_al>0 → **+1.12** (n=116); ofi_al>0.4 → +1.06.
  Every per-coin cell: ofi>0 ≤ base.
- **Mechanistic reason (the useful takeaway):** fires WITH computable OFI (more 1s volume in the signal window) are
  WORSE (+1.1) than fires where OFI is thin/unavailable (+2.2). **The scalp edge is INVERSELY related to flow
  intensity** — thin, low-volume moves leave the Poly book lagging *more*, which is the lag the scalp captures. A
  "keep high-flow" gate removes the best thin-lag fires. The aggressor-flow thesis is backwards for an
  execution-lag edge, and at a 5s horizon the flow is already in the price (cause = consequence).

## Verdict
**OFI gate: NO EDGE — do not deploy.** The deployed scalp profits from execution lag, not move-persistence
prediction; conditioning on aggressor flow does not separate winners and (if anything) removes the thin-lag winners.
Caveats: production in-sample window (base +2.23 inflated vs OOS causal +0.9–1.5 — but the gate comparison is
within-sample relative, so "gate doesn't help" holds); 43% OFI coverage; n thin (25/quintile). Closed; don't re-test.
