# Phase-0 FINAL — Synth-style model vs the market (free, all local data) — 2026-06-03

Direct test: at a mid-window snapshot, compare a Synth-style zero-drift GBM `P(up)` to the **Polymarket
Up-token mid** (market implied `P(up)`), both scored against the actual outcome. 6 cells, last 6 days,
real L25 books. Script: `compare_vs_market.py`.

## Results (lower Brier = better; value bet = bet the model-vs-market gap, 0.07 fee, entry=token price)
| cell | n | base P(up) | **Brier market** | Brier model | Brier model-calib-OOS | coin | value bet $/trade |
|---|--:|--:|--:|--:|--:|--:|--:|
| BTC 15m | 543 | 0.481 | **0.2235** | 0.377 | 0.260 | 0.250 | −0.036 |
| BTC 5m | 1640 | 0.507 | **0.2249** | 0.435 | 0.260 | 0.250 | −0.006 |
| ETH 15m | 543 | 0.492 | **0.2210** | 0.328 | 0.236 | 0.250 | −0.021 |
| ETH 5m | 1639 | 0.498 | **0.2206** | 0.407 | 0.272 | 0.250 | −0.013 |
| SOL 15m | 543 | 0.483 | **0.2223** | 0.299 | 0.231 | 0.250 | −0.027 |
| SOL 5m | 1639 | 0.512 | **0.2246** | 0.369 | 0.250 | 0.250 | +0.002* |

\*SOL 5m +$0.002/trade = statistical zero (WR 51.5%, +$3.36 over 1636 trades, shrinks with τ).

## Conclusion — UNANIMOUS
1. **The market is well-calibrated everywhere: Brier ≈ 0.221–0.225**, beating coinflip (0.25) and beating
   our Synth-style model (raw AND out-of-sample-calibrated) in **all 6 cells**. The Polymarket up-down price
   already prices the intra-window drift/vol better than a GBM does.
2. **Value-betting the model-vs-market gap LOSES in 5/6 cells** (−$0.005 to −$0.036/trade); the 6th is noise.
   Where our model disagrees with the market, **the market is right**.
3. ⇒ **The Synth mechanism (zero-drift calibrated-vol GBM) does NOT beat the market on our data — any asset,
   any tf.** This is the efficient-market finding, now proven directly against the live market price (not
   just outcomes).

## Could Synth's better σ change this?
Maybe, but the bar is brutal: our *calibrated* model is ~0.24–0.27; the market is already **0.221**. Synth's
ensemble σ would have to beat a market that's sharper than our calibrated model — and then the residual edge
would still face the thin-book + 0.07-fee drag that has killed every edge we've found on 5/15-min books.
Their reported $3k→$73k is most consistent with small-sample variance / a trending regime / survivorship,
not a durable, fee-survivable, directionally-flat vol-arb on these markets.

## RECOMMENDATION: STOP (do not build the live engine; do not buy a key yet)
- A Synth API key is only worth buying if we first see evidence their ensemble σ yields **Brier < 0.221** on
  a held-out set — which our own (better-data) calibrated model could not approach. Burden of proof is high,
  expected payoff thin.
- This closes the Synth line the same way the directional/momentum/maker lines closed: **the Polymarket
  up-down market is efficient at the resolution we can trade, and fees + thin books erase the residue.**
- If we ever revisit: the only untested angle is Synth's *full-distribution* edge on **rare high-divergence
  moments** (not the per-market average we tested) — but that needs their probs (key) and is a long shot.

## Artifacts
- `compare_vs_market.py` (this test), `baseline_calibration.py` (model-vs-outcome), `SYNTH_DECODE_FROM_CODE.md`
  (the code decode), `synth_client.py` + `validate_synth_edge.py` (kept for if a key is ever obtained).
