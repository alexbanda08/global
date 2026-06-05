# Wallet harvest — today's BTC-5m / BTC-15m / SOL-15m / ETH-15m markets (2026-05-29)

> Profitable wallets active TODAY in our 4 target cells, for strategy decode next session.
> Source: `_harvest_today_4cells_v2_2026_05_29.py` (CORRECTED — uses conditionId, see §Bug).
> Full scored list: `cache/_harvest_today_4cells_v2_2026_05_29.csv`.

## Top decode candidates (by 7d PnL, systematic in our cells)

| Wallet | lb_all | lb_30d | lb_7d | lb_1d | today cells | priority |
|---|---:|---:|---:|---:|---|---|
| `0xeebde7a0` | $826k | $253k | +$92k | +$16.5k | btc-5m 844, btc-15m 3500, eth-15m 29 | ✅ DONE (F1 best) |
| `0xce25e214` | $212k | $211k | +$39k | +$4.9k | sol-15m, eth-15m, btc-5m/15m (all 4) | known (legacy list); re-decode |
| **`0x3c58ef42`** | $55k | $49k | **+$18.3k** | +$3.8k | sol-15m 49, btc-5m 81, btc-15m 10, eth-15m 13 | 🆕 **DECODE** |
| **`0xd9dea316`** | $43k | $37k | **+$15.9k** | +$3.7k | sol-15m 44, btc-5m 80, eth-15m 8, btc-15m 10 | 🆕 **DECODE (twin of 3c58ef42)** |
| **`0x251c1a28`** | $17k | $16k | **+$13.1k** | +$1.8k | btc-5m 616, btc-15m 105 | 🆕 **DECODE** |
| `0x5e2b9261` | $92k | $47k | +$11.1k | +$1.7k | all 4 (eth-15m 576, btc-15m 335) | 🆕 |
| `0xc387c2a4` | $53k | $44k | +$8.7k | +$1.1k | btc-5m only (174) | 🆕 btc-5m specialist |
| `0xfcdc071d` | $19k | $9k | +$4.7k | +$1.4k | btc-15m 985, eth-15m 396, sol-15m 195 | 🆕 |
| `0xe593ed21` | $6k | $6k | +$4.8k | +$1.3k | btc-5m only (582) | 🆕 (small but fast) |
| `0xdf7930e8` | $5k | $4k | +$4.5k | +$2.9k | btc-5m 351, btc-15m 844 | 🆕 (small but fast) |
| `0xcfb103c3` | $144k | $92k | +$2.9k | +$2.9k | btc-5m only (350) | known (legacy list) |

## Notes
- **Method validates itself:** `0xeebde7a0` (our decoded best) is #1 — confirms the harvest finds
  the right kind of wallet.
- **Twin pair worth a look:** `0x3c58ef42` + `0xd9dea316` have near-identical profiles
  (sol-15m + btc-5m, +$16-18k/7d, ~150 trades). Possible related/paired operation — check funding
  EOA (Alchemy) like we did for the F1 fleet.
- Already-known (skip or re-decode): `eebde7a0` (done), `ce25e214` + `cfb103c3` (in cash_pnl
  WALLETS_LEGACY).
- The first harvest run's apparent $1.19M wallet (`0x5966db1f`) was a **global-feed artifact**
  (sports/politics), NOT an up-down trader — correctly absent from this corrected list.

## Decode recipe (next session)
For each candidate `W`:
1. `py -X utf8 strategy_lab/wallet_hunt/polymarket_api.py --wallet 0x<W>` → activity tape + lb truth.
2. `py -X utf8 strategy_lab/wallet_hunt/fetch_alchemy.py --wallet 0x<W> --days 200` → funder/fleet.
3. Adapt `_decode_directional_v2_2026_05_29.py` (dominant-side hit-rate) + `_decode_lock_pattern_2026_05_29.py`
   (FIFO pair sum) → classify directional vs arb vs maker.
4. These trade INTRADAY cells we have L25 books for → can do full book-anchored decode
   (unlike the daily/sports wallets 0fe40e88/4ee29e4e/a42f127d/143732d8).

## Bug fixed this session
`harvest_market_wallets.py` queried `data-api /trades?market=<SLUG>` — **the slug filter is
ignored**; it returns the GLOBAL recent-trades feed. Correct param = `?market=<conditionId>`
(= canonical `market_id`). Prior `_harvest_wallets.csv` is global noise. The v2 script + the
patched tool use conditionId.
