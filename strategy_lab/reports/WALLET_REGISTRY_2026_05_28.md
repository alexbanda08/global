# Directional Up/Down Wallet Registry — 2026-05-28

Persistent record of directional wallets found this session, so the work isn't lost.
Source data: `strategy_lab/wallet_hunt/cache/_directional_wallet_registry.csv` (30 wallets,
best segment per wallet with WR/PnL on $25 stake, joined to pseudonym + #crosses).

How they were found: counterparty mining (100 counterparties of known directional
wallets) → per-segment WR scan (`segment_winrate.py`) → top decoded via
`trigger_decode_harness.py` (8 wallets) → full 33-day backtest with gate battery
(`directional_scan.py` + `eval_strategies.py`).

## Status of the 8 decoded wallets
| wallet | best seg | WR | strategy | verdict |
|---|---|---|---|---|
| 0x0de4458d (Angry-Crowd) | btc-5m | 69% | cl_basis extreme-divergence + slug-select | **gates PASS (strict)** — user passed on it |
| 0x07480f20 | btc-5m | 76% | momentum ret_3m (~102 fires/day) | real signal, priced-out (net ~0) |
| 0x0079c319 | btc-15m | 74% | ema9_slope momentum | real signal, priced-out |
| 0xe3867b68 | multi 15m | 75% | cross-asset ema9_slope momentum | real signal, priced-out |
| 0x8ef6a1cc | btc-5m | 80% | cl_basis (corroborates Angry-Crowd) | 1-day data, insufficient |
| 0x9f5ffe76 | eth-15m | 74% | early-momentum | small n, insufficient |
| 0x10188828 | sol/eth-15m | 68% | ema9_slope | 2-day data, insufficient |
| 0xf6d2f340 | sol-5m | 75% | px_vs_strike | 1-day data, insufficient |

## Key learning (why we move on)
- Decoded edge = "Binance leads the Chainlink resolution oracle." Two flavors:
  **momentum** (blind trend-follow) and **cl_basis** (extreme oracle divergence).
- Backtest verdict: blind **momentum is real but efficiently priced** (WR≈entry price → net ~0,
  fails G1/G4/walk-forward). Only **cl_basis EXTREME-divergence** survives all gates — but it's
  low-frequency (~2-6 profitable fires/day) and the user is not interested in it.
- → Need a DIFFERENT class of edge. Next: widen the search net beyond these counterparties.

## Untested high-WR wallets worth a look (not yet decoded)
0x8692a1a8 (btc-5m 81% n=137 +$528), 0x69e2165a (btc-5m 79% n=435 +$486),
0xea9f038c (btc-5m 84% n=32), 0x76d4d470 (sol-15m 81%), 0x7b32b637 (btc-15m +$1927 low-WR/big-hits),
0x5eb2c2e2 (eth-5m low-WR but +$567 — cheap-entry profile).

## Tooling (reusable)
- `strategy_lab/wallet_hunt/segment_winrate.py` — per-(asset,tf) WR scan for any wallet list
- `strategy_lab/wallet_hunt/trigger_decode_harness.py` — per-fire signal decode
- `strategy_lab/directional_signal/{directional_scan.py,eval_strategies.py}` — full backtest + gates
- Reports: DIRECTIONAL_WR_SCAN, DECODE_SYNTHESIS, DECODE_<wallet>, DIRECTIONAL_BACKTEST_GATES (all _2026_05_28)

## Next discovery vector (this is where we continue)
`data-api.polymarket.com/trades?market=<slug>` returns ALL participants of a market
(confirmed working). Scalable harvest: sample updown markets across the window → collect
every unique proxyWallet → WR-scan the full universe (not just counterparties of known wallets).
This surfaces wallets we'd never reach via leaderboard or counterparty mining.
