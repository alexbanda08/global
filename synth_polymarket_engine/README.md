# Synth → Polymarket value-betting engine

Goal: replicate what Synth (Bittensor Subnet 50, synthdata.co) does on Polymarket — **bet the side where
Synth's model probability disagrees with the market's implied probability** — and decide, with our own
backtest, whether it's a real edge before any capital.

## What Synth actually does (decoded from docs.synthdata.co + web)
- **Probabilistic forecasting, not point prediction.** 200+ ML miners on Bittensor SN50 each submit an
  **ensemble of 1,000 simulated price paths** per asset per horizon (1h high-freq down to 5-min increments,
  and 24h). Paths capture **volatility clustering + fat tails**. Miners scored by **CRPS** (calibration +
  sharpness); only top miners feed the API.
- **From paths → implied probability.** If 620/1000 paths end above the start price → `P(up)=0.62`.
- **The Polymarket play = value betting on mispriced odds.** Compare Synth `P(up)` to Polymarket's
  implied `P(up)` (price). Bet the side where Synth's prob exceeds the market's by a margin. They are NOT
  predicting direction with certainty — they harvest the **calibration gap**.
- Reported: $3k→$51–73k, ~110% over a 4-week trial, thousands of trades on BTC/ETH 15/30/60-min up-down.
  ⚠️ Caveats (their own community's): small sample, edges erode, hourly markets thin. The "86% WR" is
  unsourced marketing — we will measure our own WR/calibration.

## The gift: Synth exposes the edge directly (no need to rebuild the forecaster first)
REST `https://api.synthdata.co` (`Authorization: Apikey KEY`, credits/req; WS pushes every 15–35s):

**Polymarket comparison endpoints** (Synth prob vs market prob, side by side):
- `GET /insights/polymarket/up-down/{5min,15min,hourly,daily}` — fields:
  `synth_probability_up`, `synth_outcome`, `polymarket_probability_up`, `polymarket_outcome`, `slug`,
  `start_price`, `current_price`, `event_start_time`, `event_end_time`, `forecast_start_time`.
  Assets: BTC, ETH, SOL, XAU (+ equities/commodities on daily). **← THIS IS THE SIGNAL.**
- `GET /insights/polymarket/range/daily`, `/above/daily`, `/hit/daily` — range/threshold/touch markets
  (covers the temperature/commodity-touch markets we saw in LP farming).
- `GET /insights/limitless/{daily,hourly,15min}` — same idea on Limitless exchange.
- Raw distribution if we want our own: `GET /insights/prediction-percentiles?asset=BTC&horizon=1h`
  (percentiles per timestep), `volatility`, `option-pricing`, `liquidation`, `lp-bounds/probabilities`.
- Public (no key): `/leaderboard`, `/v2/leaderboard`, `/meta-leaderboard` (top miners).
- `start_time` param on insights → **historical snapshots** → lets us backtest without waiting live.

**Edge signal:** `edge = synth_probability_up − polymarket_probability_up` (de-vig the market prob first).
Bet UP if edge ≥ +τ, DOWN if edge ≤ −τ.

## ⚠️ Why we VALIDATE before building the live engine
We have repeatedly found the Polymarket up-down market **efficient vs our own signals**
(`EFFICIENT_MARKET_FINDING_2026_05_28`). Synth claims a better-calibrated probability beats it. That is a
*testable* claim and it's a DIFFERENT signal class (vol-clustering Monte-Carlo ensemble, not our momentum/
flow). But our hard rule stands: **no capital on a marketing WR.** We must prove, with real fills + real
fees, that `synth_probability_up` is better calibrated than the market and survives our gate battery.

### Validation plan (Phase 0 — gate the whole project)
1. **Get a Synth API key** (user) → set `SYNTH_API_KEY` env.
2. Pull **historical** `synth_probability_up` (via `start_time`) for BTC/ETH/SOL 5min+15min+hourly up-down
   over a window that overlaps our canonical data (Apr 22 → Jun 1).
3. Join each Synth snapshot to:
   - our canonical **resolution** (actual UP/DOWN, chainlink) — `load_resolutions`,
   - the **L25 entry price** at the bet moment (real fill) — `load_orderbook_l25_streaming`, `engine_v2`.
4. **Calibration test (the core question):** is `synth_probability_up` better calibrated than
   `polymarket_probability_up`? Compute **Brier score** and reliability curve for both vs the realized
   outcome. Synth must beat the market's Brier to have any edge. (This is the make-or-break metric.)
5. **Backtest the value bet** with `engine_v2.RealisticConfig` (0.07 fee curve + 85ms latency +
   min_book_events + tx_cost): bet when `|edge|≥τ`, Kelly-fraction sized, sell-or-hold per the market tf.
   Report WR, net $/trade, block-bootstrap CI, OOS split, matched-null.
6. **Decision:** only if Synth's Brier < market's AND the value bet is +EV OOS with CI>0 after real fees →
   build the live engine. Otherwise document as another efficient-market result (or edge that doesn't
   survive fills/fees — our recurring outcome on thin 5/15-min books).

## Live engine architecture (build ONLY if Phase 0 passes)
1. **Signal:** WS/REST poll `/insights/polymarket/up-down/{5min,15min,hourly}` for BTC/ETH/SOL/XAU.
2. **Edge calc:** de-vig market prob; `edge = synth_p − poly_p`; require `|edge|≥τ` (tune in backtest).
3. **Gate:** entry price favorable, spread/liquidity OK (reuse `engine_v2.fill_at_book` cross-token spread),
   fee-breakeven check, time-in-window.
4. **Size:** fractional Kelly on `edge` (cap per market; respect thin-book depth).
5. **Execute:** route through existing live infra (Ireland TV engine / poly sniper) — we already place live.
6. **Monitor:** log synth_p, poly_p, edge, fill, outcome → live calibration + PnL; kill-switch on drift.

## Files
- `synth_client.py` — REST/WS client for the insights + polymarket + leaderboard endpoints (needs key).
- `validate_synth_edge.py` — Phase-0 harness: pull historical synth-vs-poly → join canonical resolutions +
  L25 fills → Brier calibration + engine_v2 backtest. **Run this first.**
- (later) `engine_live.py` — the live value-bet engine, gated on Phase-0 pass.

## Status
2026-06-03: docs decoded, architecture + validation plan written, client + harness scaffolded.
**BLOCKED on:** Synth API key (paid credits) to run Phase-0 calibration backtest.
