# External strategy review — "Dual-feed agreement + momentum" bot (2026-05-27)

_Read of a strategy another builder shared. Does it work? Short answer: **the signal is real but his numbers are inflated; we already run a stronger variant in production**. Long answer below._

## TL;DR

| claim | his number | reality (from our work) | verdict |
|---|---|---|---|
| Theoretical WR @ T-120s | 99.5% | ~50-60% live | **lookahead-flavored backtest** |
| Real WR | 55% (n=8) | matches our 50-60% live band | honest |
| Fill rate | 7% | matches our taker findings on Polymarket short markets | honest |
| "Earlier entry = better prices" | speculative | our `pre_window_timing_sweep.py` shows entry vwap converges by T-300s | **wrong direction of edge** |
| Skip if token > 0.85 | ✅ correct | matches our entry_vwap < 0.85 gate | good |

**Net: no new edge for us.** His core signal (dual-feed agreement + sub-minute momentum) is a strict subset of what our F7-momo + Phase-36 sleeves already do, with worse execution.

## Strategy decomposition

His 7 conditions map to our existing features:

| his rule | our equivalent | already deployed? |
|---|---|---|
| Chainlink ≥ 0.05% move since window open | `chainlink_dev_bps ≥ 5` | ✅ Phase 35 vwap-cont sleeves |
| Binance ≥ 0.05% same window | `vwap_dev_bps ≥ 5` | ✅ vwap-cont sleeves |
| Both feeds agree direction | implicit in our `vwap_dev_bps` sign + chainlink rtds check | ✅ live |
| Conflict ratio < 1.5 | not gated explicitly | ❌ worth testing |
| Token price ≥ 0.35 | implicit (we trade only one side at fire-time) | ✅ |
| 1/2/3/4-min Binance momentum > 50% | our `momo_v1/v2` controllers | ✅ live |
| Same on Chainlink | not gated | ❌ worth testing |
| Skip token > 0.85 | `entry_vwap_max ≈ 0.85` | ✅ Phase 36 fairedge gates |

**Novel pieces worth borrowing**:
1. `conflict_ratio < 1.5` between Binance and Chainlink magnitudes — easy add to our gate sweep
2. Chainlink momentum confirmation in same multi-timeframe form (1/2/3/4 min)

Both are essentially **redundancy filters** that cut signal count by ~30% in exchange for higher WR.

## Why his 99.5% backtest WR is suspect

His T-120s = window close − 120s. **That is exactly the `ws_s` anchor we use in production**, but…

His "T-60s 99.8% WR" cannot be real. At T-60s, the BTC move that resolves the market has already happened — 99.8% is the WR of asking "did BTC just move?" 60 seconds before close. That's not a tradable edge, it's the auto-correlation of the price series with itself over the next minute.

Our `_match_live_f7_v2.py` work on production fires shows backtest WR drops 25-40 pp once you anchor at `ws_s` and read books at the EXACT fire moment (not the slot-end retroactive close). His 99.5% almost certainly suffers from:

- **Resolution at slot-close binance close instead of chainlink-derived outcome** (we ban this — see CLAUDE.md "Outcome resolution = Chainlink Data Streams")
- **No book-walk fill model** — his backtest assumes he fills at his FAK price; reality is 93% no-fill
- **No latency** — `engine_v2.LiveMimicConfig` defaults to 85ms; he runs 0ms

That alone explains 89.6% theoretical → 55% real, no mystery.

## The fill-rate problem is the real story

His own honest section nails it: signal generation isn't the hard part, **execution at useful prices is**. This matches every conclusion from our `maker_vs_taker_gated_sleeves.py` and `queue_aware_maker_gated_sleeves.py` runs:

- Taker fills on Polymarket short crypto markets cluster at the **last $0.01 of move** because co-located makers eat the book first
- Maker rebates on these markets are effectively 0 (per our 2026-05-22 fee-model verification — `feeRate ≈ 0` on BTC/ETH/SOL up-down)
- Net: maker-only is the only execution mode with positive EV at retail latency, but fill rate drops further

His 7% fill rate at ~85ms+ public-RPC + 5s scan loop is **structural**, not a bot quality issue.

## What he gets wrong about timing

His claim:
> _"This suggests we could enter earlier to catch better prices, before the crowd has priced in the move."_

This is **likely backwards** for these markets. Our `pre_window_timing_sweep.py` and `_optimal_three_lenses.py` show:
- At T-600s entry, the directional signal is real but noisy (his table: 86.2% WR backtest)
- Crowd vwap at T-600s is still ~0.50 because crowd ALSO has the signal
- Entry vwap converges to chainlink-implied probability **fast** — by T-300s the crowd is ~80% of the way there
- Edge = backtest_WR − entry_vwap; that delta is biggest in the **T-90s to T-30s** band, not earlier

His T-120s entry is roughly where edge peaks on his own (inflated) numbers.

## What's worth taking

| idea | action |
|---|---|
| `conflict_ratio < 1.5` gate | add as candidate gate in `gate_sweep_master.py` next sweep |
| Chainlink-side momentum (1/2/3/4 min) | already have `chainlink_rtds.parquet`; compute 1/2/3/4-min returns as a new feature column in `build_features_v3plus.py` |
| Auto-cancel watcher at T-5s | already in production via `polymarket_updown.py` exit policy |
| Hermes oracle agent for self-debug | not relevant for us — we have systematic verification |

## What to skip

- His T-300s+ entry idea — math doesn't support it on our data
- Sliding-price GTC — abandoned by him for correct reasons (late-window prices > 0.95 break the asymmetry math)
- The whole bot as a deploy target — strictly weaker than our existing F7/HOD/fairedge stack

## Action items

1. **Low priority**: add `conflict_ratio = abs(cl_dev_bps) / abs(bn_dev_bps)` and Chainlink-side `momo_pct` as new feature columns; re-run `gate_sweep_master.py` overnight. Expected lift: marginal (<5%).
2. **No action**: his deploy spec — we already ship the same signal class with better gates and execution.

## Verdict

**Working as designed at the signal layer, broken at the execution layer — same conclusion we reached 6 weeks ago and addressed via the F7/HOD/Phase-36 stack.** His public writeup is honest about the gap but understates how much of the 89.6% theoretical WR is lookahead in disguise. No net-new edge for our deployment, but the `conflict_ratio` and `chainlink-momo` gates are a free addition to the next sweep.
