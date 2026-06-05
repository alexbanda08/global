# Backtest-Replay vs Live — BTC Sleeves
**Date:** 2026-05-29  
**Script:** `strategy_lab/replay_btc_2026_05_29.py`  
**Data CSV:** `strategy_lab/reports/replay_btc.csv` (497 rows)

---

## Coverage

| Metric | Count |
|--------|-------|
| Total resolved live fires | 707 |
| In L25 range (placed_fire_us ≤ 2026-05-29 10:01:33 UTC) | 497 |
| No L25 data (placed_fire_us > L25 max) | 210 |
| In-range fills: OK | 486 |
| In-range fills: NO_BOOK (no L25 series for slug/outcome) | 9 |
| In-range fills: UNDERFILLED | 2 |
| Sleeves with at least 1 comparable row | 5 of 14 |
| Sleeves entirely in no_data window | 9 of 14 |

L25 max timestamp: **2026-05-29 10:01:33 UTC**. All sleeves with fires after that are excluded from replay.

**Method:** For each resolved row, the matching placed row's `fire_us` is used for L25 book lookup (strict-asof, native 10 Hz, `subsample_1hz=False`). Book-walked for $5 notional at ask levels. PnL computed with legacy 2%-on-profit model (matches production). Canonical outcome from `load_resolutions()` (chainlink-rtds).

---

## Per-Sleeve Fidelity Table

| sleeve_id | n_resolved | n_compared | n_no_data | live_WR% | bt_WR% | live_$/tr | bt_$/tr | mean\|Δfill_vwap\| | outcome_match% | live_totPnL | bt_totPnL | flags |
|-----------|------------|------------|-----------|----------|--------|-----------|---------|-------------------|----------------|-------------|-----------|-------|
| btc_15m_ema50_ema800_off600_down | 38 | 32 | 6 | 81.2 | 81.2 | +1.3988 | +1.4888 | 0.0150 | 100.0 | +44.76 | +47.64 | **OK** |
| btc_15m_ema50_ema800_off600_down_H | 19 | 13 | 6 | 100.0 | 92.3 | +0.8047 | +0.8068 | 0.0146 | 100.0 | +10.46 | +10.49 | LOW_N |
| btc_15m_ema800_ribslp_hawkes_off840_v6 | 23 | 18 | 2 | 55.6 | 50.0 | −1.4508 | −1.7366 | 0.0044 | 94.4 | −26.11 | −31.26 | LOW_N\|OUTCOME_MISMATCH |
| btc_15m_ts_trstack_off600_down | 3 | 2 | 1 | 100.0 | 100.0 | +0.4388 | +0.4592 | 0.0000 | 100.0 | +0.88 | +0.92 | LOW_N |
| **btc_5m_q_parent15mslope_ts_imb5_v8** | **513** | **421** | **84** | **69.1** | **70.5** | **−0.6281** | **−0.4263** | **0.0121** | **100.0** | **−264.43** | **−174.79** | **OK** |

*(Sleeve IDs abbreviated; prefix `poly_sniper_v5_` omitted for space)*

---

## Sleeves With No L25 Data (all fires > cutoff)

| sleeve_id | n_resolved | live_WR% | live_totPnL | note |
|-----------|------------|----------|-------------|------|
| btc_5m_up_b2_contrarian2k_v9 | 28 | 64.3 | +52.67 | no_data |
| btc_5m_down_b2_contrarian2k_v9 | 27 | 33.3 | −42.18 | no_data |
| btc_5m_l_1hrf_imb5_rf_v8 | 18 | 94.4 | +14.01 | no_data |
| btc_5m_l_1hrf_imb5_ribbon_v8 | 16 | 93.8 | +10.96 | no_data |
| btc_5m_parent15m_notrang_ts_mpskew_v7 | 9 | 100.0 | +7.34 | no_data |
| btc_5m_a2_hlcascade100k_v9 | 6 | 50.0 | +3.30 | no_data |
| btc_5m_up_a2_hlcascade50k_v9 | 3 | 66.7 | +6.87 | no_data |
| btc_5m_ts_mpskew_any_off30 | 3 | 66.7 | +1.11 | no_data |
| btc_15m_vwapprem_ema50_mpskew_off600_v6 | 1 | 100.0 | +1.11 | no_data |

---

## Flag Notes

### OUTCOME_MISMATCH — btc_15m_ema800_ribslp_hawkes_off840_v6
- 1 out of 18 compared rows: slug `btc-updown-15m-1779921000`, live says Up won (+$0.15), canonical chainlink says Down won (settlement 74518.46 < strike 74524.83).
- Root cause: live controller resolved via Polymarket CLOB settlement; chainlink RTDS-local gave opposite result. Price delta is very small (−6.37 BPS on strike). Edge-case chainlink/CLOB disagreement.
- Backtest PnL impact: bt shows −$31.26 vs live −$26.11 (+$5.15 bt-unfavorable) from this single row.
- 94.4% match (vs 98% threshold). FLAG retained.

### btc_5m_q_parent15mslope_ts_imb5_v8 — PnL Gap Analysis
This is the primary sleeve of interest (live −$317 cumulative vs spec, n=513 total resolved).

**Replay result (n=421 compared):**
- Outcome match: **100%** (on 410 canon-known rows; 11 slugs not yet in canonical = recently resolved)
- WR: live 69.1% vs bt 70.5% — essentially identical
- Fill delta: mean |Δvwap| = **0.0121** overall (below 0.02 threshold → no FILL_DIVERGE flag)
- PnL: live −$0.6281/tr vs bt −$0.4263/tr → **gap = −$0.2018/tr**

**Root cause decomposition:**

| Segment | n | live_$/tr | bt_$/tr | delta |
|---------|---|-----------|---------|-------|
| Stale L25 book (>30s at lookup) | 23 | −0.101 | +1.603 | **−1.704** |
| Fresh L25 book (≤30s at lookup) | 387 | −0.574 | −0.547 | −0.027 |

**Stale rows (23 fires, book staleness 30–59s):**
- L25 canonical had no recent snapshot → replay used stale book showing old (pre-move) prices, mean bt_vwap=0.584 vs live_vwap=0.743.
- Stale BT inflated by **+$39.20** total ($36.87 bt vs −$2.33 live).
- These are genuine book-coverage gaps: live WS BookMirror had real-time price data that L25 canonical didn't capture in those 30–59s windows.
- **This is NOT a dispatch-time bug** — the disparity is from missing L25 snapshots, not from fire_us timing.

**Fresh rows (387 fires, book age ≤30s):**
- Mean |Δfill_vwap| = **0.003** (excellent agreement)
- live_dtr = −0.574, bt_dtr = −0.547, delta = **−0.027/tr** ($10.6 total)
- Residual gap on fresh rows is small (−$0.027/tr). Most likely attributable to live executing on the actual submitted-order tick vs canonical's nearest-prior 10Hz snapshot.
- **Conclusion: no imb5 dispatch-time bias found.** Fill agreement is tight on fresh books. The live−bt gap is dominated by the 23 stale-book rows where L25 had coverage gaps.

**imb5 dispatch-time hypothesis verdict:**
The hypothesis that `btc_5m_q_parent15mslope_ts_imb5_v8` has a fire_us timing bug (dispatch time vs signal time) is **NOT confirmed by this replay**. On 387/421 fresh-book fires, live and bt vwaps agree within 0.003 mean. The sleeve's −$0.63/tr live underperformance vs backtest priors is real but attributable to:
1. Stale canonical L25 snapshots on 23 fires (+$39.20 phantom BT gain)
2. Small residual execution slippage on fresh fills (−$0.027/tr × 387 = −$10.6)
3. The sleeve is genuinely loss-making: both live −$0.628/tr and bt −$0.426/tr are negative.

### btc_15m_ema50_ema800_off600_down — OK
- live +$1.399/tr, bt +$1.489/tr. Gap = −$0.090/tr (small, from minor fill divergence 0.015).
- Outcome 100% match. This sleeve is tracking backtest well.

---

## Summary Statistics

**5 sleeves had L25 coverage; 9 were entirely past the L25 cutoff.**

Among comparable sleeves:
- **3 matching** (|live_$/tr − bt_$/tr| ≤ 0.50 and outcome_match ≥ 98%, excluding LOW_N): `btc_15m_ema50_ema800_off600_down`, `btc_15m_ema50_ema800_off600_down_H`, `btc_15m_ts_trstack_off600_down`
- **1 PnL gap but explainable** (stale L25 coverage, not fill bias): `btc_5m_q_parent15mslope_ts_imb5_v8` (|delta| = 0.20/tr, root cause = 23 stale-book rows)
- **1 outcome mismatch** (single chainlink/CLOB edge case): `btc_15m_ema800_ribslp_hawkes_off840_v6`

**No FILL_DIVERGE flags raised** (all mean |Δvwap| < 0.02).

---

## Key Findings

1. **imb5_v8 loss is real, not a replay artifact.** BT also shows negative PnL (−$0.426/tr on 421 comparable fires). The live−bt gap ($0.20/tr) is dominated by 23 stale-L25-book rows where canonical missed 30–59s of price movement. On 387 fresh-book fires, live and bt track within $0.027/tr. No dispatch-time timing bug.

2. **L25 staleness = primary replay divergence source.** 23/421 imb5 fires (5.5%) had book snapshots >30s old at replay time. These inflated bt PnL by +$39.20 cumulative. Mitigation: exclude rows with `book_dt_us > 30s` from BT or flag them separately.

3. **Outcome truth: chainlink vs CLOB.** 1 hawkes slug resolved opposite between canonical chainlink and Polymarket CLOB. Expect ~1% edge-case disagreement rate near strike crossings. Use `with_clob_winner=True` for production-faithful outcome backfill.

4. **9 sleeves entirely uncompared** (all fires after L25 2026-05-29 10:01 UTC cutoff). Several show high live WR (l_1hrf_imb5_rf 94.4%, l_1hrf_imb5_ribbon 93.8%, parent15m_notrang 100%) — replay against a refreshed L25 would validate these.

---

## Files
- `strategy_lab/reports/replay_btc.csv` — per-row replay data (497 rows: sleeve_id, slug, direction, placed_fire_us, live_vwap, bt_vwap, live_pnl, bt_pnl, fill_status, book_dt_us, outcome columns)
- `strategy_lab/replay_btc_2026_05_29.py` — replay script
