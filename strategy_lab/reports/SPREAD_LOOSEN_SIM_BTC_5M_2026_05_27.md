# Spread-Loosen Impact: BTC 5m Sleeves — 0.020 → 0.025
**Date:** 2026-05-27  
**Stake:** $5 · **Fee model:** LegacyConfig (2% on profit only) · **Window:** Apr 24 – May 27 (~33d)

---

## Methodology

**Question:** What happens to each sleeve if the same-token bid-ask spread filter is loosened from 0.020 to 0.025?

1. **Base universe:** `_sniper_btc_5m_enriched.parquet` (155,370 BTC 5m fires that passed spread=0.020) enriched with gate columns from v7 and v8 sandbox universes.
2. **Borderline fires:** Full resolution grid (9,267 BTC 5m slugs × 9 offsets × 2 directions = 222,246 candidates). 78,185 were rejected at spread=0.020. For each, L25 books were loaded (`subsample_1hz=False`) and `fill_at_book` re-run at spread=0.025. **3,596 fires** passed 0.025 but failed 0.020 (spread in (0.020, 0.025]).
3. **Gate enrichment:** Borderline fires have features joined via `(slug, direction)` from the enriched universe (39.5% slug match rate; for unmatched slugs with no book history, gates default to 0).
4. **Metrics:** WR, $/tr, total PnL, max drawdown, t-stat computed on combined (current + borderline) fire sets per sleeve.

**Key caveat:** Borderline fire gate values are approximated from the same slug's other offsets. Microstructure gates (`g_mp_skew_with`, `g_imb5_strong_with`) may not reflect the exact moment's book state. Treated as conservative estimate: when gate match rate is low (60.5% slugs unmatched), borderline fires default gates to 0 → they are EXCLUDED from multi-gate sleeves.

---

## Per-Sleeve Results

| Sleeve (short) | Gates | n_020 | WR_020 | $/tr_020 | PnL_020 | MaxDD_020 | n_025 | WR_025 | $/tr_025 | PnL_025 | MaxDD_025 | Δn | Δn% | ΔWR | Δ$/tr | ΔPnL |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **ts_mpskew_s6_0_60** | g_mp_skew_with | 6,291 | 50.6% | −$1.168 | −$7,349 | $7,687 | 6,334 | 50.5% | −$1.173 | −$7,430 | $7,687 | +43 | +0.7% | −0.10pp | −$0.005 | −$81 |
| **ts_mpskew_any_off30** | g_mp_skew_with | 2,455 | 50.8% | −$1.926 | −$4,729 | $5,966 | 2,482 | 50.7% | −$1.920 | −$4,767 | $5,966 | +27 | +1.1% | −0.06pp | +$0.006 | −$38 |
| **parent15m_slope_ts_mpnx_v7** | g_parent_15m_slope+g_trend_slope_strong+g_mp_no_extreme | 441 | 71.4% | +$4.992 | +$2,202 | $222 | 442 | 71.3% | +$4.970 | +$2,197 | $222 | +1 | +0.2% | −0.16pp | −$0.023 | −$5 |
| **slotend_ofi_ts_v7** | g_slot_end_ofi+g_trend_slope_strong | 568 | 94.7% | +$2.168 | +$1,231 | $78 | 568 | 94.7% | +$2.168 | +$1,231 | $78 | 0 | 0% | 0 | $0 | $0 |
| **parent15m_notrang_ts_mpskew_v7** | g_parent_15m_not_ranging+g_trend_slope_strong+g_mp_skew | 561 | 51.9% | −$5.335 | −$2,993 | $3,187 | 562 | 51.8% | −$5.334 | −$2,998 | $3,187 | +1 | +0.2% | −0.09pp | +$0.001 | −$5 |
| **l_1hrf_imb5_rf_v8** | g_1h_rf+g_imb5_strong+g_rf_with | 1,509 | 73.7% | +$4.656 | +$7,025 | $805 | 1,518 | 73.7% | +$4.628 | +$7,025 | $805 | +9 | +0.6% | −0.04pp | −$0.028 | −$0 |
| **l_1hrf_imb5_ribbon_v8** | g_1h_rf+g_imb5_strong+g_ribbon_agrees | 1,509 | 78.9% | +$4.257 | +$6,424 | $425 | 1,518 | 78.8% | +$4.230 | +$6,421 | $425 | +9 | +0.6% | −0.07pp | −$0.027 | −$2 |
| **q_parent15mslope_ts_imb5_v8** | g_parent_15m_slope+g_trend_slope_strong+g_imb5_strong | 657 | 72.3% | +$6.200 | +$4,073 | $913 | 660 | 72.3% | +$6.166 | +$4,069 | $913 | +3 | +0.5% | −0.03pp | −$0.034 | −$4 |

---

## Context: Borderline Fire Population

- **Total rejected at 0.020:** 78,185 candidates
- **Admitted by 0.025:** 3,596 (4.6% unlock rate)
- **Borderline WR:** 46.8% (below breakeven — these fires are in wide-spread, low-quality book conditions)
- **Borderline mean $/tr:** −$0.39 (losing on average)
- **Slug match to enriched:** 39.5% (most borderline slugs have no feature history)

The borderline fires have **worse PnL than base universe average**, consistent with wide spreads indicating low-quality, thin markets.

---

## Per-Sleeve Recommendations

### 1. poly_sniper_v5_btc_5m_ts_mpskew_s6_0_60 — **KEEP 0.020**
- Already negative sleeve (WR 50.6%, $/tr −$1.17). Adding 43 borderline fires makes it marginally worse (−$81 total PnL). No benefit.
- **KEEP**

### 2. poly_sniper_v5_btc_5m_ts_mpskew_any_off30 — **KEEP 0.020**
- Already negative (WR 50.8%, $/tr −$1.93). Adding 27 borderline fires has negligible effect. Sleeve is not profitable; spread is not the binding constraint.
- **KEEP**

### 3. poly_sniper_v5_btc_5m_parent15m_slope_ts_mpnx_v7 — **KEEP 0.020**
- Strong positive sleeve (WR 71.4%, $/tr +$4.99, t=3.77). Adding 1 borderline fire causes −$0.023/tr dilution and −$5 total PnL. Impact negligible (0.2% n increase) but direction is slightly negative.
- **KEEP** (1 extra fire irrelevant either way)

### 4. poly_sniper_v5_btc_5m_slotend_ofi_ts_v7 — **KEEP 0.020**
- Zero borderline fires admitted. This sleeve fires on late offsets with g_slot_end_ofi_with which depends on near-slot-end microstructure; those moments are unlikely to have wide-spread books. No change either way.
- **KEEP** (no impact)

### 5. poly_sniper_v5_btc_5m_parent15m_notrang_ts_mpskew_v7 — **KEEP 0.020**
- Negative sleeve (WR 51.9%, $/tr −$5.34). Adding 1 borderline fire is noise. The sleeve is broken regardless of spread.
- **KEEP** (fix the sleeve, not the spread)

### 6. poly_sniper_v5_btc_5m_l_1hrf_imb5_rf_v8 — **KEEP 0.020**
- Best-in-class sleeve (WR 73.7%, $/tr +$4.66, t=4.66, total PnL +$7,025). Adding 9 fires causes −$0.028/tr dilution and negligible total PnL change (−$0.21 over 33d). Not worth the live risk of entering wider-spread books.
- **KEEP** (strong sleeve; don't dilute edge with marginal-quality fills)

### 7. poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8 — **KEEP 0.020**
- Highest WR sleeve (78.9%, $/tr +$4.26, t=7.55). Adding 9 fires causes −$0.027/tr dilution. Same reasoning as #6 — best to preserve edge purity.
- **KEEP** (protect the 78.9% WR; borderline fills would dilute to 78.8%)

### 8. poly_sniper_v5_btc_5m_q_parent15mslope_ts_imb5_v8 — **KEEP 0.020**
- Top $/tr sleeve (+$6.20/tr, WR 72.3%). Adding 3 fires causes −$0.034/tr dilution and −$4 total PnL. Minor but unnecessary.
- **KEEP** (highest $/tr; don't dilute)

---

## Summary

**Recommendation: KEEP 0.020 for all 8 BTC 5m sleeves.**

The loosening from 0.020 → 0.025 has universally negative-to-neutral impact across all sleeves:

| Effect | Detail |
|---|---|
| Fire volume increase | +0% to +1.1% (3 to 43 added fires per sleeve over 33d) |
| WR change | −0.03pp to −0.16pp (borderline fires have 46.8% WR vs 50–94% for live sleeves) |
| $/tr change | −$0.034 to +$0.006 (always within noise; directionally negative for positive sleeves) |
| Total PnL change | −$81 to +$0 (negative-sum across all sleeves) |
| MaxDD change | $0 (no change — max drawdown unchanged) |

**Root cause:** The 3,596 borderline fires (spread 0.020–0.025) are structurally lower-quality:
- 46.8% WR vs the 50–79% WR of existing sleeve populations
- Wide-spread books at fire moment correlate with thin liquidity and adverse market conditions
- VWAP-walked fills at spreads 0.020–0.025 result in worse entry prices

**Path forward:** The BTC 5m sleeves are idle due to *cross-token* spread rejection in production (live avg ~31% cross-token spread vs 0.020 bid-ask threshold). Loosening the bid-ask threshold from 0.020 to 0.025 does NOT address the live deployment issue. The spread fix in progress (patching live controller from cross-token to same-token bid-ask) is the correct fix, not loosening the threshold.

---

*Script: `strategy_lab/spread_loosen_sim_btc_5m_2026_05_27.py`*  
*Results: `strategy_lab/reports/SPREAD_LOOSEN_SIM_BTC_5M_2026_05_27.csv`*  
*Borderline cache: `data/v4/canonical/_results/_spread_loosen_borderline_btc5m.parquet`*
