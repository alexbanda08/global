# BACKTEST-REPLAY vs LIVE — ETH Sleeves
**Date:** 2026-05-29  
**Script:** `strategy_lab/replay_eth_2026_05_29.py`  
**Data:** `live_fires_ETH.csv` (666 rows total, 324 resolved), ETH L25 canonical (max 2026-05-29 13:13 UTC)

---

## Sanity Gate Status

| Gate | Result |
|------|--------|
| **#1 bt_WR approx live_WR (+-3pp)** | **PASS** — overall bt_WR=54.5% vs live_WR=53.4% (delta=+1.1pp). All comparable sleeves within +-2pp. |
| **#2 mean|delta_fill_vwap| < 0.05** | **PASS** — overall mean=0.0077 across 266 OK rows. Excluding k_hurst outlier: 0.004. |
| **#3 Walk ASKS of BUY token** | **PASS** — implementation verified identical to BTC template. |

---

## Partition

- Total resolved: **324**
- In L25 range (fired before 2026-05-29 13:13 UTC): **268** — after book lookup: **266 OK**, 2 NO_BOOK
- No data (fired after L25 cutoff): **56** (mostly recent cloud/k/lq/l sleeves)

---

## Per-Sleeve Fidelity Table

| sleeve_id | n_resolved | n_compared | n_no_data | live_WR | bt_WR | live_$/tr | bt_$/tr | mean|delta_vwap| | outcome_match% | live_totPnL | bt_totPnL | flags |
|-----------|-----------|-----------|----------|---------|-------|-----------|---------|-----------------|---------------|------------|----------|-------|
| eth_15m_trstack_vwap_offearly | 38 | 37 | 1 | 40.5% | 40.5% | -1.5301 | -1.5245 | 0.0029 | 100.0% | -56.62 | -56.40 | OK |
| eth_5m_bb_mp_hurst_band_v6 | 6 | 0 | 6 | — | — | — | — | — | — | +5.00 | — | LOW_N |
| eth_5m_bb_mp_hurst_band_v6_vL | 6 | 0 | 6 | — | — | — | — | — | — | +5.00 | — | LOW_N |
| eth_5m_cloud_mp_sms_active_off120 | 2 | 0 | 2 | — | — | — | — | — | — | -4.48 | — | LOW_N |
| eth_5m_cloud_ribbon_mp_hurst_v6 | 4 | 0 | 4 | — | — | — | — | — | — | +1.55 | — | LOW_N |
| eth_5m_cloud_ribbon_mp_hurst_v6_vL | 5 | 0 | 5 | — | — | — | — | — | — | +2.32 | — | LOW_N |
| eth_5m_cloud_vwap_hurstmp_v7 | 5 | 0 | 5 | — | — | — | — | — | — | +2.97 | — | LOW_N |
| eth_5m_cloud_vwap_hurstmp_v7_vL | 5 | 0 | 5 | — | — | — | — | — | — | +2.97 | — | LOW_N |
| **eth_5m_ema200_vwap_regimerang_xa3_v7** | **97** | **92** | 3 | **50.0%** | **51.1%** | -1.0218 | -0.8965 | 0.0053 | 98.9% | **-94.01** | **-82.48** | OK |
| eth_5m_ema50_hurst_parent15mrang_v7 | 60 | 60 | 0 | 56.7% | 58.3% | -0.6573 | -0.4638 | 0.0033 | 98.3% | -39.44 | -27.83 | OK |
| eth_5m_ema50_hurst_parent15mrang_v7_vL | 71 | 71 | 0 | 57.7% | 59.2% | -0.6876 | -0.5192 | 0.0028 | 98.6% | -48.82 | -36.87 | OK |
| eth_5m_k_hurst_ts_cci_tod_euus_v8 | 6 | 3 | 3 | 100.0% | 100.0% | +0.4916 | +3.5640 | 0.1767 | 100.0% | +1.47 | +10.69 | LOW_N\|FILL_DIVERGE\|PNL_DIVERGE |
| eth_5m_k_hurst_ts_cci_tod_euus_v8_vL | 6 | 3 | 3 | 100.0% | 100.0% | +0.4916 | +3.5640 | 0.1767 | 100.0% | +1.47 | +10.69 | LOW_N\|FILL_DIVERGE\|PNL_DIVERGE |
| eth_5m_l_ema50_hurst_grandparent_v8 | 7 | 0 | 7 | — | — | — | — | — | — | +3.24 | — | LOW_N |
| eth_5m_lq_ema50_hurst_grandparent_prev15m_v8 | 2 | 0 | 2 | — | — | — | — | — | — | +0.92 | — | LOW_N |
| eth_5m_lq_ema50_hurst_grandparent_prev15m_v8_vL | 2 | 0 | 2 | — | — | — | — | — | — | +0.92 | — | LOW_N |
| eth_5m_tr200_mp_sms_active_off120 | 1 | 0 | 1 | — | — | — | — | — | — | +0.52 | — | LOW_N |
| eth_5m_v5repl_off120_v6 | 1 | 0 | 1 | — | — | — | — | — | — | +0.52 | — | LOW_N |

*Sleeve names stripped of `poly_sniper_v5_` prefix for readability.*

---

## Special Focus: eth_5m_ema200_vwap_regimerang_xa3_v7

**Does replay reproduce the loss?** Yes, emphatically.

- Live: n=97, WR=50.0%, totPnL=**-$94.01** (-$1.02/trade)
- Backtest: n=92 compared, WR=51.1%, totPnL=**-$82.48** (-$0.90/trade)
- bt_totPnL is less negative than live by ~$11.50 — attributable to live fills at slightly higher prices (mean delta_vwap=0.005, WS latency + book movement between fire and fill). No inflation: the loss is real.
- Outcome match 98.9% — chainlink agrees with live outcome on all but ~1 slug.
- **Conclusion: the loss is not a data artifact. This sleeve is a net loser at current parameters.**

---

## Special Focus: vL Variants vs Parents

All vL variants have identical fills to their parents on shared slugs (mean|delta_vwap| < 0.005 on common slugs). The vL variants add extra slugs (additional fire condition) without changing fill quality.

| Pair | parent n | vL n | common slugs | vL extra fires |
|------|----------|------|--------------|----------------|
| ema50_hurst_parent15mrang_v7 | 60 | 71 | 60 | 11 |

Both variants are net-negative (-$39.44 vs -$48.82 live), consistent with the ema200 finding — 5m ETH sleeves generally below breakeven.

---

## k_hurst FILL_DIVERGE — Root Cause

Slug `eth-updown-5m-1780042500`: L25 canonical data ends at 08:16:23 UTC (36s before the fire at 08:17:00). Last ask0=0.33; live filled at 0.86. In that 36s gap the UP token book moved dramatically. The canonical L25 parquet has no later updates for this slug — the WS stream stopped recording before the fire. This is a **data coverage gap in canonical L25**, not a methodology bug. The 36s staleness passed the 60s MAX_STALENESS_US threshold so the stale 0.33 book was used. With n=3 after exclusions, this sleeve is LOW_N regardless; FILL_DIVERGE and PNL_DIVERGE flags are correct and expected.

---

## Aggregate Summary (n_compared > 0 sleeves)

| Metric | Value |
|--------|-------|
| Total resolved fires | 324 |
| Fires with L25 data (OK fills) | 266 |
| Overall live WR | 53.4% |
| Overall bt WR | 54.5% (delta = +1.1pp) PASS |
| Overall mean|delta_vwap| | 0.0077 (excl. k_hurst: 0.004) PASS |
| Live totPnL (all 324) | -$214.50 |
| Bt totPnL (266 compared) | -$182.20 |

The ~$32 gap (live worse than bt) is explained by: (1) live fills at slightly higher vwaps due to real WS latency + book movement; (2) 56 fires post-L25-cutoff excluded from bt.

---

## Findings

1. **Sanity gate #1 HOLDS**: bt_WR approx live_WR within +-2pp for all sleeves with sufficient data. No outcome-join bug. No token-side confusion.
2. **ETH 5m sleeves are broadly net-negative** at current parameters. Only sleeves with n<20 show positive live PnL; those are unreliable (LOW_N).
3. **eth_5m_ema200_vwap_regimerang_xa3_v7 loss confirmed**: bt reproduces -$82.48 vs live -$94.01. Not a fluke.
4. **eth_5m_ema50_hurst_parent15mrang_v7** loss also confirmed: bt -$27.83 vs live -$39.44. The ~$11 gap = live execution slippage.
5. **eth_15m_trstack_vwap_offearly** near-perfect replay: bt -$56.40 vs live -$56.62, outcome_match=100%, |delta_vwap|=0.003. Strong canonical fidelity.
6. **k_hurst FILL_DIVERGE** is a data gap (36s stale book), not a methodology bug.
7. **vL variants** fire on a strict superset of their parent's slugs (+11 extra) with identical fill quality on shared slugs.

---

*Generated: 2026-05-29 | Script: strategy_lab/replay_eth_2026_05_29.py*
