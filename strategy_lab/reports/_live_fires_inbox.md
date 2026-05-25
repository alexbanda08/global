# Live shadow / paper / production fires — inbox

_Built from `data/v4/canonical/_results/live_fires_normalized.csv` (this session)._

## Coverage

- Source A: `data/v4/canonical/trading_events_30d.parquet` (production `trading.events` from VPS3, 30d).
- Source B: `migration_ireland_shadow_2026_05_21/maker_csvs/pat-shadow_2026-05-2{0,1}.csv` (Ireland shadow, May 20-21).
- Source C: `data/v4/canonical/resolutions_from_rtds.parquet` (condition_id -> slug map).

- Date range: **2026-05-07 00:10 UTC -> 2026-05-21 19:55 UTC** (14.8 days).
- Total fires: **23,810**
- With resolved PnL: **22,277 (93.6%)**
- WON / LOST (where set): **10,920** / **11,427**

Fires per source type:
  - `volume`: 6,638
  - `momo_v1`: 4,719
  - `momo_v2`: 4,707
  - `sniper`: 3,249
  - `v3`: 1,810
  - `mint_sell`: 1,463
  - `sniper_inv`: 577
  - `v4`: 343
  - `pat_shadow`: 304

## Per-strategy bucket

| strategy | n | WR% | sum_pnl ($) | per_trade ($) |
|---|---:|---:|---:|---:|
| v4 | 343 | 53.1 | -89.88 | -0.262 |
| sniper_inv | 577 | 51.1 | -512.95 | -0.889 |
| pat_shadow | 234 | 2.6 | -1285.48 | -5.493 |
| v3 | 1,810 | 52.0 | -1779.99 | -0.983 |
| momo_v2 | 4,707 | 48.1 | -3598.58 | -0.765 |
| sniper | 3,249 | 49.4 | -4328.96 | -1.332 |
| volume | 6,638 | 50.6 | -4527.05 | -0.682 |
| momo_v1 | 4,719 | 48.0 | -4940.69 | -1.047 |

## F7 filter mode breakdown (momo only)

| strategy | f7_mode | n | WR% | sum_pnl ($) | per_trade ($) |
|---|---|---:|---:|---:|---:|
| momo_v1 | basic | 162 | 59.3 | +866.54 | +5.349 |
| momo_v2 | basic | 231 | 42.9 | -555.80 | -2.406 |
| momo_v2 | off | 4,476 | 48.4 | -3042.78 | -0.680 |
| momo_v1 | off | 4,557 | 47.6 | -5807.23 | -1.274 |

## Top 15 sleeves by sum_pnl

| sleeve_id | n | WR% | sum_pnl ($) | per_trade ($) | days | $/day |
|---|---:|---:|---:|---:|---:|---:|
| `poly_updown_eth_15m_momo_v2_HOLD` | 110 | 67.3 | +874.24 | +7.948 | 14 | +64.71 |
| `poly_updown_eth_15m_momo_v2_SELL` | 110 | 66.4 | +810.26 | +7.366 | 14 | +59.97 |
| `poly_updown_eth_15m_momo_v2_HEDGE` | 110 | 67.3 | +707.88 | +6.435 | 14 | +52.39 |
| `poly_updown_btc_15m_momo_v2_HOLD` | 117 | 62.4 | +684.20 | +5.848 | 14 | +51.48 |
| `poly_updown_btc_15m_momo_v2_SELL` | 117 | 51.3 | +486.35 | +4.157 | 14 | +36.59 |
| `poly_updown_btc_15m_momo_HOLD` | 85 | 61.2 | +469.34 | +5.522 | 15 | +34.85 |
| `poly_updown_btc_15m_momo_v2_HEDGE` | 117 | 62.4 | +401.40 | +3.431 | 14 | +30.20 |
| `poly_updown_eth_5m_v3_3` | 30 | 73.3 | +332.03 | +11.068 | 9 | +30.43 |
| `poly_updown_eth_5m_v3_2` | 30 | 73.3 | +331.98 | +11.066 | 9 | +30.43 |
| `poly_updown_btc_15m_momo_SELL` | 85 | 54.1 | +295.72 | +3.479 | 15 | +21.96 |
| `poly_updown_btc_15m_momo_HEDGE` | 85 | 61.2 | +256.54 | +3.018 | 15 | +19.05 |
| `poly_updown_eth_5m_v3` | 42 | 61.9 | +245.45 | +5.844 | 11 | +17.39 |
| `poly_updown_eth_5m_v4` | 20 | 75.0 | +244.15 | +12.207 | 6 | +24.44 |
| `poly_updown_btc_5m_momo_HOLD_f7` | 24 | 66.7 | +234.44 | +9.768 | 2 | +257.69 |
| `poly_updown_eth_5m_v3_1` | 23 | 69.6 | +217.06 | +9.437 | 7 | +20.26 |

## Bottom 15 sleeves by sum_pnl

| sleeve_id | n | WR% | sum_pnl ($) | per_trade ($) | days | $/day |
|---|---:|---:|---:|---:|---:|---:|
| `poly_updown_btc_5m_sniper` | 629 | 47.2 | -1752.69 | -2.786 | 15 | -118.57 |
| `poly_pat_shadow_btc_5m_shadow` | 234 | 2.6 | -1285.48 | -5.493 | 1 | -1588.51 |
| `poly_updown_eth_5m_momo_v2_HOLD` | 349 | 43.8 | -1189.18 | -3.407 | 15 | -88.13 |
| `poly_updown_btc_5m_momo_HOLD` | 562 | 46.4 | -1103.04 | -1.963 | 15 | -78.46 |
| `poly_updown_eth_5m_volume_INV_NIGHT` | 1,557 | 50.8 | -1101.23 | -0.707 | 15 | -76.40 |
| `poly_updown_btc_5m_momo_HEDGE` | 562 | 46.4 | -1066.87 | -1.898 | 15 | -75.88 |
| `poly_updown_btc_5m_momo_SELL` | 562 | 44.8 | -1055.94 | -1.879 | 15 | -75.11 |
| `poly_updown_sol_15m_volume_INV_NIGHT` | 602 | 49.0 | -1028.79 | -1.709 | 15 | -71.41 |
| `poly_updown_eth_5m_momo_v2_HEDGE` | 349 | 43.8 | -987.90 | -2.831 | 15 | -73.22 |
| `poly_updown_sol_5m_volume_INV_NIGHT` | 1,387 | 51.3 | -946.96 | -0.683 | 15 | -65.70 |
| `poly_updown_eth_5m_momo_v2_SELL` | 349 | 41.0 | -945.93 | -2.710 | 15 | -70.10 |
| `poly_updown_eth_15m_sniper` | 383 | 48.8 | -899.53 | -2.349 | 15 | -60.94 |
| `poly_updown_sol_5m_sniper` | 577 | 48.9 | -886.60 | -1.537 | 15 | -59.98 |
| `poly_updown_btc_5m_momo_v2_HEDGE` | 537 | 48.8 | -846.65 | -1.577 | 15 | -62.19 |
| `poly_updown_btc_5m_momo_v2_SELL` | 537 | 41.5 | -763.95 | -1.423 | 15 | -56.11 |

## Verdict — what's working / what's bleeding

_Threshold: |sum_pnl| > $50 and n >= 20 fires._

### EARNING (19 sleeves)

- `poly_updown_eth_15m_momo_v2_HOLD` — **+874.24** over 110 fires, WR 67.3%, +7.948/trade, +64.71/day
- `poly_updown_eth_15m_momo_v2_SELL` — **+810.26** over 110 fires, WR 66.4%, +7.366/trade, +59.97/day
- `poly_updown_eth_15m_momo_v2_HEDGE` — **+707.88** over 110 fires, WR 67.3%, +6.435/trade, +52.39/day
- `poly_updown_btc_15m_momo_v2_HOLD` — **+684.20** over 117 fires, WR 62.4%, +5.848/trade, +51.48/day
- `poly_updown_btc_15m_momo_v2_SELL` — **+486.35** over 117 fires, WR 51.3%, +4.157/trade, +36.59/day
- `poly_updown_btc_15m_momo_HOLD` — **+469.34** over 85 fires, WR 61.2%, +5.522/trade, +34.85/day
- `poly_updown_btc_15m_momo_v2_HEDGE` — **+401.40** over 117 fires, WR 62.4%, +3.431/trade, +30.20/day
- `poly_updown_eth_5m_v3_3` — **+332.03** over 30 fires, WR 73.3%, +11.068/trade, +30.43/day
- `poly_updown_eth_5m_v3_2` — **+331.98** over 30 fires, WR 73.3%, +11.066/trade, +30.43/day
- `poly_updown_btc_15m_momo_SELL` — **+295.72** over 85 fires, WR 54.1%, +3.479/trade, +21.96/day
- `poly_updown_btc_15m_momo_HEDGE` — **+256.54** over 85 fires, WR 61.2%, +3.018/trade, +19.05/day
- `poly_updown_eth_5m_v3` — **+245.45** over 42 fires, WR 61.9%, +5.844/trade, +17.39/day
- `poly_updown_eth_5m_v4` — **+244.15** over 20 fires, WR 75.0%, +12.207/trade, +24.44/day
- `poly_updown_btc_5m_momo_HOLD_f7` — **+234.44** over 24 fires, WR 66.7%, +9.768/trade, +257.69/day
- `poly_updown_eth_5m_v3_1` — **+217.06** over 23 fires, WR 69.6%, +9.437/trade, +20.26/day
- `poly_updown_btc_15m_sniper` — **+193.48** over 449 fires, WR 51.0%, +0.431/trade, +13.11/day
- `poly_updown_btc_5m_momo_SELL_f7` — **+180.22** over 24 fires, WR 66.7%, +7.509/trade, +198.09/day
- `poly_updown_btc_5m_momo_HEDGE_f7` — **+178.52** over 24 fires, WR 66.7%, +7.438/trade, +196.22/day
- `poly_updown_eth_5m_sniper_DOWN_INV` — **+118.43** over 258 fires, WR 54.3%, +0.459/trade, +8.03/day

### LOSING (46 sleeves)

- `poly_updown_btc_5m_sniper` — **-1752.69** over 629 fires, WR 47.2%, -2.786/trade, -118.57/day
- `poly_pat_shadow_btc_5m_shadow` — **-1285.48** over 234 fires, WR 2.6%, -5.493/trade, -1588.51/day
- `poly_updown_eth_5m_momo_v2_HOLD` — **-1189.18** over 349 fires, WR 43.8%, -3.407/trade, -88.13/day
- `poly_updown_btc_5m_momo_HOLD` — **-1103.04** over 562 fires, WR 46.4%, -1.963/trade, -78.46/day
- `poly_updown_eth_5m_volume_INV_NIGHT` — **-1101.23** over 1557 fires, WR 50.8%, -0.707/trade, -76.40/day
- `poly_updown_btc_5m_momo_HEDGE` — **-1066.87** over 562 fires, WR 46.4%, -1.898/trade, -75.88/day
- `poly_updown_btc_5m_momo_SELL` — **-1055.94** over 562 fires, WR 44.8%, -1.879/trade, -75.11/day
- `poly_updown_sol_15m_volume_INV_NIGHT` — **-1028.79** over 602 fires, WR 49.0%, -1.709/trade, -71.41/day
- `poly_updown_eth_5m_momo_v2_HEDGE` — **-987.90** over 349 fires, WR 43.8%, -2.831/trade, -73.22/day
- `poly_updown_sol_5m_volume_INV_NIGHT` — **-946.96** over 1387 fires, WR 51.3%, -0.683/trade, -65.70/day
- `poly_updown_eth_5m_momo_v2_SELL` — **-945.93** over 349 fires, WR 41.0%, -2.710/trade, -70.10/day
- `poly_updown_eth_15m_sniper` — **-899.53** over 383 fires, WR 48.8%, -2.349/trade, -60.94/day
- `poly_updown_sol_5m_sniper` — **-886.60** over 577 fires, WR 48.9%, -1.537/trade, -59.98/day
- `poly_updown_btc_5m_momo_v2_HEDGE` — **-846.65** over 537 fires, WR 48.8%, -1.577/trade, -62.19/day
- `poly_updown_btc_5m_momo_v2_SELL` — **-763.95** over 537 fires, WR 41.5%, -1.423/trade, -56.11/day
- `poly_updown_eth_5m_sniper` — **-757.03** over 508 fires, WR 47.4%, -1.490/trade, -51.16/day
- `poly_updown_btc_5m_volume_INV_NIGHT` — **-718.12** over 1835 fires, WR 50.5%, -0.391/trade, -49.82/day
- `poly_updown_sol_5m_momo_v2_HEDGE` — **-648.10** over 304 fires, WR 48.0%, -2.132/trade, -47.72/day
- `poly_updown_eth_5m_momo_HOLD` — **-616.98** over 369 fires, WR 47.2%, -1.672/trade, -44.05/day
- `poly_updown_btc_5m_momo_v2_HOLD` — **-566.04** over 537 fires, WR 48.8%, -1.054/trade, -41.58/day

## Data issues / caveats

- `slug` is missing for **2,951** rows (12.4%). Mostly from `pat-shadow` and `mint_sell v2 fire` records where slug couldn't be resolved (mint_sell v2 fire data lacks slug; mint_sell *resolution* does carry one).
- `ws_s` missing for **2,951** rows (same root cause as slug).
- `pnl_usd` missing for **1,533** rows — these are fired signals whose resolution event never wrote `fill_event_id` (the 1,533-row gap is mainly `poly_mint_sell_v2_*_paper` v2-fires that match `poly_mint_sell_resolution` rows only by `fire_event_id`; matched where possible).
- Top unresolved sleeves:
  - `poly_mint_sell_v2_eth_5m_paper`: 553 fires without pnl_usd
  - `poly_mint_sell_v2_sol_5m_paper`: 548 fires without pnl_usd
  - `poly_mint_sell_v2_btc_5m_paper`: 362 fires without pnl_usd
  - `poly_pat_shadow_unknown`: 70 fires without pnl_usd
- Mint_sell v2 fires have `vwap=NaN` and `usd=NaN` because the v2 fire payload only carries `desired_*_qty` / `desired_*_px` (quote intent, not realized fill). Their realized PnL comes from the `poly_mint_sell_resolution` join on `fire_event_id`.
- `won` in pat-shadow rows is derived as `pnl_final > 0` (heuristic), not from a settlement event.
- Production fee model used in these resolutions = **2% on profit (winning leg only)** — verified 2026-05-22 against 25,900 resolutions. Same as `engine_v2.LegacyConfig`. The `0.07 * p * (1-p)` real-curve in `strategy_lab/fees.py` does NOT match production for these markets.
- Other shadow caches inspected but NOT included in this CSV (older than 7 days or aggregate-only): `data/v4/canonical/_results/shadow_11_sleeves_{backtest,v2}.csv` (these are BACKTEST aggregate summaries, not per-fire); `shadow_logs/`, `shadow_logs_l25/` (May 18 snapshots).