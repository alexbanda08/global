# Synth decoded from source (github.com/synthdataco/synth-subnet) — 2026-06-03

Pulled the subnet repo. The model is no longer a black box. Key files:
`synth/miner/price_simulation.py`, `synth/miner/simulations.py`, `synth/validator/crps_calculation.py`,
`synth/validator/{reward,prompt_config}.py`.

## The price process — ZERO-DRIFT calibrated-vol GBM (code-proven)
`simulate_single_price_path()`:
```python
dt = time_increment / 3600           # step size in hours
std_dev = sigma * sqrt(dt)
price_change_pcts = np.random.normal(0, std_dev, num_steps)   # MEAN 0 -> no drift
cumulative_returns = cumprod(1 + price_change_pcts)
price_path = current_price * cumulative_returns
```
- **Drift = 0.** The median path is flat = current price. → matches the dashboard where **p50 ≈ flat** on
  both 1h and 24h. **There is NO directional alpha in Synth.** The forecast is a symmetric fan around spot.
- The ONLY knob is **`sigma`** (volatility). Baseline miner uses a *constant* per-asset σ (`SIGMA_MAP`:
  BTC 0.00541, ETH 0.00766, SOL 0.00858 per step). **Top miners win by forecasting σ better** — dynamic,
  mean-reverting, fat-tailed (the dashboard vol chart shows their σ ≈ 25–40% annualized, smooth/mean-reverting
  vs spiky realized). The whole competition is a **volatility/distribution forecasting** game.
- Horizons: `time_increment` 300s (5min) or 60s (1min); `time_length` 86400 (24h) or 3600 (1h);
  `num_simulations` = 100 paths. Spot source = **Pyth** (Hermes/Lazer), Hyperliquid for WTIOIL.

## What's scored — CRPS on the distribution of price CHANGES
`crps_calculation.py` uses `properscoring.crps_ensemble` over multiple scoring intervals (relative, `_abs`,
`_gaps`). CRPS rewards **calibration + sharpness** of the predicted return distribution vs the realized path.
Direction is literally not scored (drift is fixed at 0). → Miners are paid purely for **getting the
volatility/shape of the distribution right.**

## ⚡ The punchline (ties to our Phase-0 test)
Synth's `P(up)` for an up-down market = `P(end_price > strike)` under a **zero-drift GBM with their σ**.
With strike ≈ open price, at the window start `P(up) ≈ 0.50` always. Mid-window, the ONLY thing that moves
`P(up)` off 0.50 is the **drift-so-far** (`spot_t` vs `strike`) measured against **remaining-time vol**:
```
P(up) = Φ( ln(spot_t / strike) / (σ · √τ) )
```
**This is EXACTLY our `baseline_calibration.py`.** We already replicated Synth's mechanism. The only thing
Synth does better is **σ** — a calibrated, mean-reverting, fat-tailed vol vs our naive trailing-60m realized
vol (which was over-confident). Our Phase-0: calibrating fixed most of the Brier damage (0.41→0.27) but
stayed ≈ coin — because **up-down is fundamentally a vol-calibration game and most outcomes are near 50/50.**

## ⇒ The real edge hypothesis = VOLATILITY ARBITRAGE (not direction)
Synth beats Polymarket only when **its forecast vol ≠ the market's implied vol**. If Polymarket's up-down
price implies a slightly wrong σ (book too tight or too wide on the remaining-time uncertainty), Synth's
better σ → a `P(up)` that diverges from the market → value bet. **The bet is on mispriced volatility, not on
which way BTC goes.** Sharpest, most testable framing we have.

## Replication blueprint (what to build)
1. **Calibrated vol forecaster** for BTC/ETH/SOL from our binance-1s data: EWMA/GARCH(1,1) + realized-vol
   mean reversion, fat-tailed (Student-t) — beat the naive trailing-60m σ. Validate σ against realized via CRPS.
2. **Zero-drift Monte Carlo** (or closed-form `Φ` for up-down) → `P(up)` at the decision snapshot.
3. **Edge = our P(up) − market implied P(up)** (equivalently: our σ vs the book's implied σ). Bet `|edge|≥τ`.
4. We do NOT need a Synth key — we can build the same thing on our own (better) data. A key is only useful as
   a benchmark (does their ensemble σ beat our GARCH σ?).

## Next step (cheapest decisive test, free) — UNCHANGED but now sharper
`compare_vs_market.py`: at the snapshot, pull Polymarket Up-token mid (L25) → market implied `P(up)` →
back out the **market's implied σ**; compare to our calibrated σ + realized. Question:
- Is the market's implied vol **efficient** (≈ realized)? If yes → no vol-arb edge → Synth's returns are
  variance/decay → stop.
- Does the market **systematically misprice remaining-window vol** (e.g. always too tight near the close)?
  If yes → that's the exploitable edge, and we build the forecaster.

## Files in repo worth re-reading
- `synth/validator/reward.py` (CRPS→incentive curve, softmax), `prompt_config.py` (exact intervals/horizons),
  `price_data_provider.py` (Pyth/HL oracle — note: Polymarket up-down may resolve on a DIFFERENT oracle than
  Pyth; verify before trusting Synth's `synth_outcome` for OUR resolutions).
