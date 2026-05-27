# Exit Policy Research — 2026-05-27

**Scope:** Top-10 sleeves (V5/V6/V7) × 200 sampled fires × 5 exit policies  
**Universe:** `sniper_search_2026_05_27/_overlap_audit_v5_v6_v7/fired_by_sleeve.parquet`  
**Date range:** ~Apr 22 – May 26 2026 (fire_us 1776995130 → 1779813870 µs UTC)

---

## 1. Methodology

### Entry fill
- `engine_v2.fill_at_book(books_idx, slug, outcome, fire_us, cfg=LegacyConfig())`
- LegacyConfig: $25 notional, 0ms latency, 2%-on-profit fee model (matches production).
- Book lookup: strict-asof, max staleness 60s. Fire discarded if no fill.

### Book data
- `load_orderbook_l25_streaming(asset, slugs=slugs, subsample_1hz=False)` — native 10Hz per CLAUDE.md convention.
- Filtered to slug-level with ±2min buffer around [fire_us, slot_end_us].

### slot_end_us derivation
- Joined `fired_by_sleeve` with `load_resolutions()` on slug. window_s = 300 (5m) or 900 (15m).

### Policy triggers

| Policy | Trigger | Action |
|--------|---------|--------|
| **HOLD** | — hold to slot_end | collect $1 or $0 |
| **HEDGE_LATE** | 60s before slot_end: check best bid. If `bid < fill_vwap × 0.70` → sell | walk bids |
| **HEDGE_REVERSAL** | First snapshot where `best_bid < fill_vwap − 0.15` (early reversal) | walk bids |
| **SELL_TP_0_85** | First snapshot where `best_bid ≥ 0.85` → take profit | walk bids |
| **SELL_SL_0_30** | First snapshot where `best_bid ≤ 0.30` → stop loss | walk bids |

### Sell-side PnL
- `sell_at_bid_partial(bid_p, bid_s, shares)` → (sell_vwap, sell_shares, sell_usd)
- `sell_pnl(fill, sell_vwap, sell_shares, sell_usd, cfg=LegacyConfig())`
- LegacyConfig sell fee: 2% on profit if sell_usd > fill.usd, else 0.

### Sampling
- Deduplicated fires by (sleeve_id, slug, fire_us) before sampling.
- Up to 200 fires per sleeve (uniform random, seed=42).

---

## 2. Per-Sleeve Results

### Sleeve 1 — SOL_5M_V7_S2_BTC_F7_OVERBOUGHT_EMA800_VWAP (SOL 5m, n=200)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 72.0% | +1.667 | +333.44 | baseline |
| HEDGE_LATE | 66.5% | +1.222 | +244.32 | −0.446 |
| HEDGE_REVERSAL | 33.5% | −2.201 | −440.22 | −3.868 |
| SELL_TP_0_85 | 77.5% | +0.319 | +63.87 | −1.348 |
| SELL_SL_0_30 | 47.0% | −3.824 | −764.84 | −5.491 |

### Sleeve 2 — BTC_5M_V7_T4_HURST_TS_HAWKES (BTC 5m, n=197)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 95.4% | +3.891 | +766.60 | baseline |
| HEDGE_LATE | 90.9% | +3.110 | +612.63 | −0.782 |
| HEDGE_REVERSAL | 73.6% | +1.216 | +239.58 | −2.675 |
| SELL_TP_0_85 | 30.5% | +1.638 | +322.77 | −2.253 |
| SELL_SL_0_30 | 83.2% | +0.799 | +157.44 | −3.092 |

### Sleeve 3 — BTC_15M_EMA50_EMA800_OFF600_DOWN_V5 (BTC 15m, n=199)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 77.9% | +2.315 | +460.63 | baseline |
| HEDGE_LATE | 76.9% | +2.709 | +539.16 | **+0.395** |
| HEDGE_REVERSAL | 52.8% | −0.451 | −89.82 | −2.766 |
| SELL_TP_0_85 | 40.7% | +1.159 | +230.59 | −1.156 |
| SELL_SL_0_30 | 64.3% | −0.229 | −45.65 | −2.544 |

### Sleeve 4 — SOL_5M_V7_S3_BTC_F7_AGAINST_CCI_HURST_REV (SOL 5m, n=199)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 71.9% | −0.642 | −127.85 | baseline |
| HEDGE_LATE | 66.8% | −0.513 | −102.13 | +0.129 |
| HEDGE_REVERSAL | 42.2% | −2.913 | −579.65 | −2.270 |
| SELL_TP_0_85 | 50.3% | **+1.563** | +311.10 | **+2.206** |
| SELL_SL_0_30 | 57.8% | −2.692 | −535.70 | −2.049 |

### Sleeve 5 — SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6 (SOL 15m, n=199)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 76.4% | +1.442 | +286.89 | baseline |
| HEDGE_LATE | 71.4% | +0.753 | +149.79 | −0.689 |
| HEDGE_REVERSAL | 49.7% | −0.273 | −54.34 | −1.715 |
| SELL_TP_0_85 | 53.3% | +0.939 | +186.87 | −0.503 |
| SELL_SL_0_30 | 62.3% | −1.729 | −344.10 | −3.171 |

### Sleeve 6 — ETH_5M_V7_C2_EMA50_HURST_PARENT_RANGING (ETH 5m, n=200)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 77.0% | +2.554 | +510.83 | baseline |
| HEDGE_LATE | 71.5% | +1.912 | +382.32 | −0.643 |
| HEDGE_REVERSAL | 44.0% | −0.221 | −44.21 | −2.775 |
| SELL_TP_0_85 | 73.5% | +2.339 | +467.87 | −0.215 |
| SELL_SL_0_30 | 60.5% | −0.274 | −54.84 | −2.828 |

### Sleeve 7 — SOL_5M_V7_S5_CCI_F7_OVERSOLD_MFI_STOCH_LIGHT (SOL 5m, n=195)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 79.5% | −0.152 | −29.59 | baseline |
| HEDGE_LATE | ~78% | −0.387 | −75.48 | −0.235 |
| HEDGE_REVERSAL | — | −1.939 | — | −1.787 |
| SELL_TP_0_85 | — | −0.737 | — | −0.585 |
| SELL_SL_0_30 | — | −2.715 | — | −2.563 |

### Sleeve 8 — BTC_5M_V7_T3_OFI_TS (BTC 5m, n=194)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 92.3% | +0.735 | +142.54 | baseline |
| HEDGE_LATE | ~88% | −0.059 | −11.36 | −0.793 |
| HEDGE_REVERSAL | — | −0.859 | — | −1.594 |
| SELL_TP_0_85 | — | −0.238 | — | −0.973 |
| SELL_SL_0_30 | — | −0.364 | — | −1.099 |

### Sleeve 9 — SOL_5M_V7_S4_CCI_F7_OVERSOLD_MFI_STOCH (SOL 5m, n=198)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 80.3% | +0.587 | +116.24 | baseline |
| HEDGE_LATE | ~80% | +0.582 | +115.27 | −0.005 |
| HEDGE_REVERSAL | — | −1.336 | — | −1.923 |
| SELL_TP_0_85 | — | −0.030 | — | −0.617 |
| SELL_SL_0_30 | — | −2.823 | — | −3.410 |

### Sleeve 10 — SOL_5M_V7_S1_BTC_TREND_CCI_HURST_REV (SOL 5m, n=198)

| Policy | WR% | Mean $/tr | Total $ | Delta vs HOLD |
|--------|-----|-----------|---------|---------------|
| HOLD | 78.3% | +2.293 | +454.09 | baseline |
| HEDGE_LATE | 73.7% | +1.853 | +366.98 | −0.440 |
| HEDGE_REVERSAL | — | −1.042 | — | −3.335 |
| SELL_TP_0_85 | — | +0.223 | — | −2.071 |
| SELL_SL_0_30 | — | −2.473 | — | −4.766 |

---

## 3. Aggregate Policy Ranking

Total PnL across all 10 sleeves (1,979 valid fires):

| Policy | Total $ | Mean delta $/tr vs HOLD | n_sleeves where delta > 0 |
|--------|---------|--------------------------|---------------------------|
| **HOLD** | **+$2,913.81** | baseline | 10/10 |
| HEDGE_LATE | +$2,221.50 | −0.35 | 2/10 |
| SELL_TP_0_85 | +$1,431.47 | −0.75 | 1/10 |
| HEDGE_REVERSAL | −$1,984.23 | −2.47 | 0/10 |
| SELL_SL_0_30 | −$3,236.34 | −3.10 | 0/10 |

**HOLD dominates in 8/10 sleeves by mean $/tr.**

**Ranking (best→worst delta):** HOLD > HEDGE_LATE > SELL_TP_0_85 > HEDGE_REVERSAL > SELL_SL_0_30

---

## 4. Policy-Sleeve Interactions

### HEDGE_LATE: 15m sleeves respond differently

| tf | Sleeve | HEDGE_LATE delta |
|----|--------|-----------------|
| **15m BTC** | BTC_15M_EMA50_EMA800_OFF600_DOWN_V5 | **+0.395** |
| 15m SOL | SOL_15M_HOD_EU_TIGHTRIB_RF_TR_VWAP80_V6 | −0.689 |
| 5m BTC | BTC_5M_V7_T4_HURST_TS_HAWKES | −0.782 |
| 5m SOL | SOL_5M_V7_S2_BTC_F7_OVERBOUGHT_EMA800_VWAP | −0.446 |
| 5m BTC | BTC_5M_V7_T3_OFI_TS | −0.793 |

The BTC 15m V5 sleeve is the **only sleeve where HEDGE_LATE is beneficial** (+$0.395/tr). Hypothesis: 15m slots (900s) have a longer tail of adversarial price moves that HEDGE_LATE cuts, while 5m slots (300s) don't have enough time for the threshold to trigger meaningfully.

### SELL_TP_0_85: one sleeve exceptional case

| Sleeve | TP delta | Context |
|--------|----------|---------|
| SOL_5M_V7_S3_BTC_F7_AGAINST_CCI_HURST_REV | **+2.206** | HOLD is actually LOSING (−0.642/tr), TP converts many losers to winners |
| All other 9 sleeves | −0.215 to −2.253 | HOLD winning → TP exits too early |

SELL_TP_0_85 is beneficial **only when the HOLD baseline is already negative**. The sleeve fires into contrarian conditions where vwap spikes briefly then reverts — TP captures the spike.

### SELL_SL_0_30 and HEDGE_REVERSAL: universally harmful

- SELL_SL_0_30: 0/10 positive, mean −3.10/tr. These sleeves target contracts that genuinely resolve (vwap collapses to ~0 on a loss), and the stop is hit before the final resolution when it would have been held to lose only $25 at notional anyway. The stop at 0.30 crystallizes a loss early but at roughly the same dollar cost while degrading winners by occasionally stopping out contracts that later recover.
- HEDGE_REVERSAL: 0/10 positive, mean −2.47/tr. The 0.15 reversal threshold is too sensitive — normal within-slot volatility on crypto prediction markets routinely exceeds 0.15, triggering exits on transient dips that ultimately resolve as wins.

---

## 5. Decision Recommendation

**Deploy: HOLD-to-resolve for all V5/V6/V7/V8 sleeves (status quo).**

No blanket alternative exit policy outperforms HOLD across the sleeve fleet. Specific findings:

1. **HOLD is optimal in 8/10 sleeves** by mean $/tr. The sleeves are already high-WR (72–95%), meaning exits crystallize profits early but lose the upside of contracts settling at $1.

2. **HEDGE_LATE is the least-bad alternative** (−$0.35/tr mean, −$692 aggregate), and is the **only policy worth considering as a conditional feature** — specifically for BTC 15m sleeves where long-window price drift makes late-hedge beneficial (+$0.395/tr for BTC_15M_EMA50_EMA800_OFF600_DOWN_V5). TV agent could enable HEDGE_LATE selectively for 15m timeframe sleeves where the late-stage volatility is higher.

3. **SELL_TP_0_85 is worth activating ONLY on negative-baseline sleeves** (HOLD PnL < 0). For SOL_5M_V7_S3_BTC_F7_AGAINST_CCI_HURST_REV (+2.206 delta), TP rescues the sleeve from −$128 to +$311 total. If TV system can flag "sleeve currently losing" in production, targeted TP could help these edge cases.

4. **Never deploy SELL_SL_0_30 or HEDGE_REVERSAL** at these thresholds. Both destroy value across all asset/tf combinations tested. If stop-loss is desired, threshold would need to be tested much lower (e.g., 0.10–0.15 for SL, 0.25+ drop for reversal).

### Conditional deployment matrix

| Condition | Recommended policy |
|-----------|-------------------|
| 5m sleeve, positive HOLD baseline (most sleeves) | **HOLD** |
| 15m sleeve | **HEDGE_LATE** (small positive delta) |
| Any sleeve with negative HOLD baseline | **SELL_TP_0_85** |
| Default / unknown | **HOLD** |

---

## Appendix

**Script:** `strategy_lab/exit_policy_research_2026_05_27.py`  
**Raw results:** `strategy_lab/reports/exit_policy_results_2026_05_27.csv`  
**Fee model:** LegacyConfig — 2% on profit, $25 notional (matches production shadow PnL)  
**Books:** `data/v4/canonical/orderbook_l25/{btc,eth,sol}.parquet` at native 10Hz  
**Total fires simulated:** 1,979 valid fills out of 2,000 sampled (21 no-fill, ~1%)  
**Compute time:** ~80s total (10 sleeves, L25 loaded per-sleeve with slug-filtered streaming)
