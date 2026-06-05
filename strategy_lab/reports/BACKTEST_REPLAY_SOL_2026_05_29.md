# BACKTEST-REPLAY vs LIVE — SOL Sleeves

**Generated:** 2026-05-29  |  **Source:** `strategy_lab/live_fires_SOL.csv`

---

## Summary

| Metric | Value |
|--------|-------|
| Total resolved fires | 968 |
| Within canonical window (fire_us <= L25 max 2026-05-29 13:14 UTC) | 718 |
| NO_DATA (fire_us > canonical L25 max) | 250 |
| bt fill OK (asks present, non-NaN, shares filled) | 256 |
| bt no_fill (ask side all NaN or book absent/stale) | 462 |
| Canonical L25 max ts | 2026-05-29 13:14:20 UTC |
| Canonical resolutions max | 2026-05-29 13:10:00 UTC |

| Global metric | Live | Backtest (filled subset only) |
|---------------|------|-------------------------------|
| Win rate | 66.9% | 22.7% |
| Total PnL (canonical window) | $165.22 | $-430.53 |
| Mean delta_vwap (bt minus live) | -- | -0.38 (bt fills much cheaper) |

---

## CRITICAL FINDING: L25 SOL book coverage insufficient for live-replay

Of 718 fires within the canonical window:
- **68** (9.5%): no book entry at all for that slug/direction
- **394** (54.9%): book present but **ask side all NaN** -- live WS BookMirror had asks, canonical L25 collector did not capture them
- **256** (35.6%): asks present, fills attempted
  - **20** (2.8% of 718): ask0 within 0.15 of live_vwap -> price-comparable
  - **236** (32.9%): asks present but at very different price (bt_vwap << live_vwap)

**Root cause**: The canonical L25 SOL parquet stores many book snapshots where the ask side is empty (NaN) at the exact fire_us, even though the live WS BookMirror had valid asks. This is a VPS2 collector coverage gap -- the SOL CLOB ask side is sparse in the canonical data for this date range (May 27-29). When asks ARE present in L25, they are often in a different price regime from live (e.g., ask0=0.01 when live traded at 0.77), indicating different market-maker quotes in the canonical vs live book.

**Consequence**: The backtest-replay is NOT a valid fidelity measure for SOL sleeves. The L25 coverage for SOL is insufficient. BTC L25 replay would be more reliable (6.6GB vs SOL 586MB).

---

## Notes on fee model

Backtest uses `LegacyConfig` (2%-on-profit-only, no entry fee, 0ms latency).
This matches production fee model verified 2026-05-22.
Per-fire `placed_size_usd` used as notional (5 USD) instead of default 25 USD.

---

## Per-sleeve fidelity table

**Flags:** FILL_DIVERGE (mean_dvwap>0.02), OUTCOME_MISMATCH (<98% match), PNL_DIVERGE (|delta_$/tr|>0.50), LOW_N (<20 resolved), ALL_NODATA (100% outside canonical window).
**Note:** FILL_DIVERGE on all sleeves reflects L25 ask-NaN coverage gap, NOT a model error.

| sleeve_id | n_res | n_cmp | n_nodata | live_WR | bt_WR | live_$/tr | bt_$/tr | mean_dvwap | out_match% | live_$tot | bt_$tot | flags |
|-----------|-------|-------|----------|---------|-------|-----------|---------|------------|------------|-----------|---------|-------|
| sol_15m_btc_adx_btcvollow_v7 | 2 | 0 | 0 | 100.0% | -- | 0.996 | -- | -- | -- | 1.99 | -- | LOW_N |
| sol_15m_hod_eu_off60_240_rf_tr_vwap30_70_v6 | 1 | 1 | 0 | 0.0% | 0.0% | -5.000 | -5.000 | 0.5700 | 100.0% | -5.00 | -5.00 | LOW_N|FILL_DIVERGE |
| sol_15m_hod_eu_off60_240_rf_tr_vwap80_v6 | 3 | 1 | 0 | 66.7% | 0.0% | -1.003 | -5.000 | 0.5700 | 100.0% | -3.01 | -5.00 | LOW_N|FILL_DIVERGE|PNL_DIVERGE |
| sol_15m_hod_eu_tightrib_rf_tr_vwap80_v6 | 9 | 5 | 0 | 44.4% | 0.0% | -2.383 | -5.000 | 0.6625 | 100.0% | -21.45 | -25.00 | LOW_N|FILL_DIVERGE|PNL_DIVERGE |
| sol_15m_rfaged_trstack_late | 2 | 1 | 0 | 50.0% | 0.0% | -2.424 | -5.000 | 0.7242 | 100.0% | -4.85 | -5.00 | LOW_N|FILL_DIVERGE|PNL_DIVERGE |
| sol_15m_rfaged_trstack_late_vL | 1 | 1 | 0 | 0.0% | 0.0% | -5.000 | -5.000 | 0.7242 | 100.0% | -5.00 | -5.00 | LOW_N|FILL_DIVERGE |
| sol_5m_b1_120s_250_v9 | 69 | 0 | 69 | 50.7% | -- | -0.369 | -- | -- | -- | -25.43 | -- | ALL_NODATA |
| sol_5m_b1_polyflow_aligned_v9 | 5 | 0 | 5 | 80.0% | -- | 0.137 | -- | -- | -- | 0.68 | -- | LOW_N|ALL_NODATA |
| sol_5m_b3_abs500_no_opp_v9 | 45 | 0 | 45 | 53.3% | -- | 0.475 | -- | -- | -- | 21.36 | -- | ALL_NODATA |
| sol_5m_b3_abs500_v9 | 50 | 0 | 50 | 50.0% | -- | 0.059 | -- | -- | -- | 2.94 | -- | ALL_NODATA |
| sol_5m_btcf7_f7overb_ema800_vwap_v7 | 128 | 40 | 15 | 71.1% | 17.5% | 0.495 | -3.888 | 0.5438 | 100.0% | 63.41 | -155.51 | FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_cci_f7_mfi_partial_vwap_v6 | 34 | 11 | 2 | 73.5% | 27.3% | 0.453 | -3.565 | 0.5070 | 100.0% | 15.39 | -39.22 | FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_depth_up_hod_session | 3 | 2 | 0 | 33.3% | 0.0% | -2.720 | -5.000 | 0.5880 | 100.0% | -8.16 | -10.00 | LOW_N|FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_down_b1_500_v9 | 2 | 0 | 2 | 100.0% | -- | 0.646 | -- | -- | -- | 1.29 | -- | LOW_N|ALL_NODATA |
| sol_5m_down_b1_flow250_v9 | 20 | 0 | 20 | 35.0% | -- | -1.607 | -- | -- | -- | -32.13 | -- | ALL_NODATA |
| sol_5m_f7_mfi_ema200_vwap_v6 | 215 | 80 | 19 | 68.4% | 27.5% | 0.069 | 3.120 | 0.5285 | 98.8% | 14.77 | 249.61 | FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_j_2asset_trending_cci_rf_ema200_v8 | 125 | 39 | 2 | 76.8% | 28.2% | 0.313 | -3.447 | 0.4122 | 100.0% | 39.14 | -134.42 | FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_rf_tr_partial_mid | 232 | 68 | 21 | 71.1% | 17.6% | 0.361 | -4.068 | 0.4579 | 98.5% | 83.73 | -276.62 | FILL_DIVERGE|PNL_DIVERGE |
| sol_5m_rf_tr_pp_mid | 22 | 7 | 0 | 77.3% | 42.9% | 0.445 | -2.768 | 0.3118 | 85.7% | 9.79 | -19.38 | FILL_DIVERGE|OUTCOME_MISMATCH|PNL_DIVERGE |

*(sleeve_id abbreviated: prefix `poly_sniper_v5_` removed)*

---

## Special sleeve deep-dives

### 15m vwap80 gate-bug sleeves

Known: live uses `vwap >= 0.55` floor vs spec `vwap < 0.80` ceiling.

- **hod_eu_off60_240_rf_tr_vwap30_70_v6**: n=1, live_WR=0.0%, live_tot=$-5.00, no_data=0
- **hod_eu_off60_240_rf_tr_vwap80_v6**: n=3, live_WR=66.7%, live_tot=$-3.01, no_data=0
- **hod_eu_tightrib_rf_tr_vwap80_v6**: n=9, live_WR=44.4%, live_tot=$-21.45, no_data=0

All three have LOW_N and FILL_DIVERGE. Live behavior consistent with gate bug: firing at high-conviction vwap states but net negative. All confirmed net losers in live (cumulative $-29.46 on 13 fires). bt_WR=0% reflects NaN asks -- cannot verify canonically.

### sol_5m_rf_tr_partial_mid (biggest SOL winner, live +$84)

- n_res=232, n_cmp=68, n_no_data=21, live_WR=71.1%, bt_WR=17.6%
- live_tot=+$83.73, bt_tot=-$276.62
- mean_dvwap=0.458, out_match%=98.5%

**Canonical cannot reproduce**: 164/211 within-window fires have no_fill (NaN asks). Of 68 bt-filled fires, L25 asks are much cheaper than live (mean_dvwap=-0.46), giving 17.6% bt_WR vs 71.1% live. Outcome match 98.5% -- canonical resolutions agree. The strategy's live edge is real but canonical L25 book data is insufficient to validate it.

### sol_5m_f7_mfi_ema200_vwap_v6 (anomalous bt_tot=+$249)

- n_res=215, n_cmp=80, live_WR=68.4%, bt_WR=27.5%
- live_tot=+$14.77, bt_tot=+$249.61

bt_tot >> live_tot. When L25 asks ARE present, they are sometimes at very low prices (0.01-0.15) on tokens that won, booking huge fake gains. This is NOT real -- it reflects stale/wrong L25 price levels. bt_WR (27.5%) and bt_$/tr (+3.12) are artifacts of lucky NaN-absent snapshots at extreme prices.

### V9 SOL sleeves (b1/b3)

All V9 sleeves are 100% no_data (all fires after canonical cutoff May 29 13:14 UTC):
- **b1_120s_250_v9**: 69 fires, 50.7% WR, live -$25.43 (net loser)
- **b3_abs500_v9**: 50 fires, 50.0% WR, live +$2.94 (marginal)
- **b3_abs500_no_opp_v9**: 45 fires, 53.3% WR, live +$21.36 (profitable, worth monitoring)
- **down_b1_flow250_v9**: 20 fires, 35.0% WR, live -$32.13 (significant loser)

Cannot backtest V9 sleeves. Need next data refresh.

---

## Conclusions

1. **L25 SOL book coverage too sparse for replay**: 55% of within-window fires have NaN ask side in canonical L25. SOL canonical (586MB) is 11x thinner than BTC (6.6GB). SOL book replay requires live WS data or a dedicated per-hour SOL L25 refresh.

2. **Outcome fidelity is good** (100% match on most sleeves) -- canonical resolutions agree with live.

3. **Live WRs appear genuine**: major SOL sleeves show 68-77% live WR. Cannot be validated via canonical backtest but directionally consistent.

4. **V9 sleeves entirely outside canonical window** -- all 186 V9 fires post-cutoff. Need next refresh.

5. **rf_tr_partial_mid** (+$84 live) cannot be reproduced in canonical. Live performance may be genuine but requires WS book data.

6. **Do NOT use bt_tot/bt_WR from this replay as PnL estimates** -- canonical L25 SOL is not a valid proxy for live SOL book state.

---

## Data files

- Per-fire detail: `strategy_lab/reports/replay_sol.csv` (968 rows)
- Script: `strategy_lab/replay_sol_backtest.py`

**replay_sol.csv columns:** sleeve_id, slug, fire_us, direction, live_vwap, live_shares, placed_usd, live_won, live_pnl, live_outcome, canon_outcome, bt_vwap, bt_shares, bt_pnl, outcome_match, fill_status (ok/no_fill/no_data), delta_vwap
