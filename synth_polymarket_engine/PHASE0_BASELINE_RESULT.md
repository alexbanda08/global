# Phase-0 baseline calibration result (FREE, offline) — 2026-06-03

Question: does a probabilistic price-path model produce a calibrated, edge-bearing P(up) on Polymarket
up-down markets? (The mechanism Synth's edge rests on.) Tested a **naive realized-vol GBM** — no Synth key —
on canonical resolutions + binance klines. Synth's insight endpoints are **hard key-gated** (only public:
leaderboards, no forecasts), so this is the free proxy for the premise.

## Setup
- Snapshot at **+120s into the window**; `spot_t` = binance 1m close as-of t; `strike` = resolution
  `strike_price`; `τ` = remaining seconds; `σ` = trailing-60m realized vol of 1m log-returns (→ per-sec).
- `P(up) = Φ( ln(spot_t/strike) / (σ·√τ) )`. Outcome = resolution `outcome=='Up'`. ~1.7–3k markets/cell.

## Results
**Directional information EXISTS, but the naive probabilities are wildly over-confident:**
| asset/tf | WR(argmax) | AUC | reliability |
|---|--:|--:|---|
| BTC 15m | 57.8% | **0.618** | says 0.95 → realizes **0.61** (over-confident) |
| BTC 5m | 53.6% | **0.673** | says 0.95 → realizes **0.585** |

AUC 0.62–0.67 ⇒ the spot-vs-strike + vol signal **ranks winners above losers** better than chance — Synth's
core mechanism is real, not magic. Our toy model already finds *direction*.

**But calibration (out-of-sample isotonic/quantile) does NOT lift Brier below coinflip:**
| asset/tf | Brier raw | Brier calibrated | coinflip(0.5) |
|---|--:|--:|--:|
| BTC 15m | 0.314 | 0.282 | 0.250 |
| BTC 5m | 0.414 | 0.273 | 0.250 |
| ETH 15m | 0.287 | 0.265 | 0.250 |
| SOL 15m | 0.265 | 0.258 | 0.250 |

Calibration fixes most of the over-confidence damage (0.41→0.27) but the residual probabilistic edge over
"just say 0.5" is **small** — naive GBM ≈ coin on Brier.

## Interpretation
- The naive model's edge is **directional ranking (AUC>0.6)**, not population-level probability accuracy.
- Most up-down markets are genuinely near-coinflip → Brier ~0.25 regardless; the exploitable edge lives only
  in the **selective strong-signal tail** (where calibrated P(up) ≈ 0.60–0.65), if the market misprices it.
- **Synth's value-add** would be: a better-than-naive ensemble (200 ML models, vol clustering, fat tails,
  CRPS-optimized) that pushes Brier below 0.25 AND below the market's Brier. We can't confirm that without
  their probs — but our baseline shows the *mechanism has signal* and the bar is "beat a calibrated GBM +
  beat the market."

## Verdict on the premise
**Not killed, not confirmed.** There IS directional signal (AUC 0.62–0.67). A naive calibrated model is
~coin on Brier → standalone weak. The open question — and the ONLY thing that decides edge — is **whether the
MARKET price is mispriced vs a good calibrated model** on the strong-signal subset. That needs the
market-implied P(up) at the snapshot (L25 book, free but heavy) or Synth's probs (key).

## Recommended next step (cheapest decisive test, still free)
Build `compare_vs_market.py`: for a BTC-15m slice, pull the **Up-token mid from L25 at +120s**, compute
market-implied P(up), and test:
1. `Brier(market)` vs `Brier(calibrated model)` — is the market well-calibrated? (likely yes → efficient).
2. On the **strong-signal tail**, does `|model − market|` predict the realized outcome (i.e. is the market
   mispriced where the model is confident)? If yes → real edge → justify a Synth key for their better model.
   If market ≈ model everywhere → efficient → Synth's reported returns are likely variance/decayed → stop.

## Files
- `baseline_calibration.py` — the free model-vs-outcome calibration test (run: `--asset btc --tf 15m`).
- Next: `compare_vs_market.py` (model+market vs outcome, L25) — not yet built.
