# BTC → ETH/SOL lead-lag — 5m markets (2026-05-23 14:07 UTC)

**Hypothesis tested**: BTC moves in last 30/60s predict ETH/SOL moves in next 30/60s well enough to seed an early fire on ETH/SOL 5m chainlink markets.

**Fee model**: engine_v2.LegacyConfig (2%-on-profit only) — production-equivalent.
**Notional**: $25. **Spread filter**: BTC 0.02, ETH 0.02, SOL 0.025.
**Universe**: 5,751 ETH + 5,751 SOL 5m slugs (chainlink-resolved, Apr 24 → May 21 28d).

## Headline

**7 deployable configs** by raw stats (n≥30, WR≥60%, +EV), top two at **ETH off=90s thr=10bps WR 85-86%, +$7-8/tr (n=65-68)**.

**HOWEVER**: lead-lag is **NOT a new strategy** — see "Overlap with S1" below. On the overlapped slugs LL and S1 agree on direction **92.6%** of the time, with statistically identical WR and PnL. LL@offset=90 fires **LATER** than S1 on 67/68 overlapped slugs (S1's earliest fire offset on those slugs is at or before 90s). Only 4 SOL slugs fire uniquely-LL (n=4 too small to deploy).

**Verdict**: lead-lag and S1 (VWAP continuation) detect the same regime ("BTC moved hard, ETH/SOL follow"). LL provides no early-fire advantage and almost no incremental coverage. **Do not deploy as a standalone sleeve.** It could be useful as a *confirmation* feature for an S1 fire — track both signal sources in production and only fire when both align.

### Best deployable configs (raw)

| variant   | asset   |   fire_offset_s |   thr_bps |   n |     wr |   avg_pnl_usd |   sum_pnl_usd |   avg_entry_vwap |
|:----------|:--------|----------------:|----------:|----:|-------:|--------------:|--------------:|-----------------:|
| V2        | ETH     |              90 |        10 |  65 | 0.8615 |        8.0122 |        520.79 |           0.7808 |
| V1        | ETH     |              90 |        10 |  68 | 0.8529 |        7.314  |        497.35 |           0.7858 |
| V1        | SOL     |              30 |        10 |  38 | 0.8421 |        2.5905 |         98.44 |           0.7749 |
| V2        | SOL     |              30 |        10 |  37 | 0.8378 |        2.3379 |         86.5  |           0.7776 |
| V2        | SOL     |              90 |        10 |  45 | 0.8889 |        0.6322 |         28.45 |           0.8623 |
| V2        | ETH     |              30 |        10 |  60 | 0.8    |        0.2049 |         12.29 |           0.7831 |
| V1        | ETH     |              30 |        10 |  62 | 0.7903 |        0.0013 |          0.08 |           0.7796 |

## Lead-lag correlation (1000-sample probe)

Computed against random timestamps over the same 28d window (probe script `strategy_lab/meta_classifier/_lead_lag_corr_probe.py`):

| pair | correlation |
| --- | --- |
| BTC_ret_30s ↔ ETH_ret_30s_FWD | **+0.1115** |
| BTC_ret_60s ↔ ETH_ret_30s_FWD | +0.0870 |
| BTC_ret_30s ↔ ETH_ret_60s_FWD | +0.0967 |
| BTC_ret_30s ↔ SOL_ret_30s_FWD | **+0.1489** |
| BTC_ret_60s ↔ SOL_ret_30s_FWD | +0.1065 |
| BTC_ret_30s ↔ SOL_ret_60s_FWD | +0.1252 |
| BTC_CVD_30s ↔ ETH_ret_30s_FWD | **+0.1500** |
| BTC_CVD_30s ↔ SOL_ret_30s_FWD | **+0.1569** |
| BTC_ret_30s ↔ ETH_ret_30s_BACK (contemporaneous, sanity) | +0.8878 |
| BTC_ret_30s ↔ SOL_ret_30s_BACK (contemporaneous, sanity) | +0.8194 |

Contemporaneous BTC↔ETH/SOL correlation is ~0.83-0.89 (very high). Predictive lead-lag is **+0.10 to +0.16** — small but positive. BTC CVD is the strongest predictor (+0.15-0.16). Worth threshold-conditional backtest.

## All variants summary (n≥30)

| variant   | asset   |   fire_offset_s |   thr_bps |   n |     wr |   avg_pnl_usd |   sum_pnl_usd |   avg_entry_vwap |
|:----------|:--------|----------------:|----------:|----:|-------:|--------------:|--------------:|-----------------:|
| V1        | ETH     |              90 |        10 |  68 | 0.8529 |        7.314  |        497.35 |           0.7858 |
| V1        | ETH     |              30 |        10 |  62 | 0.7903 |        0.0013 |          0.08 |           0.7796 |
| V1        | ETH     |              60 |        10 |  60 | 0.7167 |       -1.0492 |        -62.95 |           0.7445 |
| V1        | SOL     |              90 |        10 |  48 | 0.8542 |       -0.4383 |        -21.04 |           0.8543 |
| V1        | SOL     |              30 |        10 |  38 | 0.8421 |        2.5905 |         98.44 |           0.7749 |
| V1        | SOL     |              60 |        10 |  37 | 0.7297 |       -1.5016 |        -55.56 |           0.7492 |
| V2        | ETH     |              90 |        10 |  65 | 0.8615 |        8.0122 |        520.79 |           0.7808 |
| V2        | ETH     |              30 |        10 |  60 | 0.8    |        0.2049 |         12.29 |           0.7831 |
| V2        | ETH     |              60 |        10 |  57 | 0.7193 |       -1.2672 |        -72.23 |           0.7603 |
| V2        | SOL     |              90 |        10 |  45 | 0.8889 |        0.6322 |         28.45 |           0.8623 |
| V2        | SOL     |              30 |        10 |  37 | 0.8378 |        2.3379 |         86.5  |           0.7776 |
| V2        | SOL     |              60 |        10 |  35 | 0.7429 |       -1.7344 |        -60.71 |           0.774  |

## Per-asset breakdown

### ETH

| variant   | asset   |   fire_offset_s |   thr_bps |   n |     wr |   avg_pnl_usd |   sum_pnl_usd |   avg_entry_vwap |
|:----------|:--------|----------------:|----------:|----:|-------:|--------------:|--------------:|-----------------:|
| V2        | ETH     |              90 |        10 |  65 | 0.8615 |        8.0122 |        520.79 |           0.7808 |
| V1        | ETH     |              90 |        10 |  68 | 0.8529 |        7.314  |        497.35 |           0.7858 |
| V2        | ETH     |              30 |        10 |  60 | 0.8    |        0.2049 |         12.29 |           0.7831 |
| V1        | ETH     |              30 |        10 |  62 | 0.7903 |        0.0013 |          0.08 |           0.7796 |
| V2        | ETH     |              60 |        10 |  57 | 0.7193 |       -1.2672 |        -72.23 |           0.7603 |
| V1        | ETH     |              60 |        10 |  60 | 0.7167 |       -1.0492 |        -62.95 |           0.7445 |

### SOL

| variant   | asset   |   fire_offset_s |   thr_bps |   n |     wr |   avg_pnl_usd |   sum_pnl_usd |   avg_entry_vwap |
|:----------|:--------|----------------:|----------:|----:|-------:|--------------:|--------------:|-----------------:|
| V2        | SOL     |              90 |        10 |  45 | 0.8889 |        0.6322 |         28.45 |           0.8623 |
| V1        | SOL     |              90 |        10 |  48 | 0.8542 |       -0.4383 |        -21.04 |           0.8543 |
| V1        | SOL     |              30 |        10 |  38 | 0.8421 |        2.5905 |         98.44 |           0.7749 |
| V2        | SOL     |              30 |        10 |  37 | 0.8378 |        2.3379 |         86.5  |           0.7776 |
| V2        | SOL     |              60 |        10 |  35 | 0.7429 |       -1.7344 |        -60.71 |           0.774  |
| V1        | SOL     |              60 |        10 |  37 | 0.7297 |       -1.5016 |        -55.56 |           0.7492 |

## Variant interpretation

- **V1 (raw BTC threshold)**: fire when |BTC_ret_30s| ≥ THR_BPS, bet WITH BTC direction.
- **V2 (CVD-confirmed)**: V1 AND BTC taker-CVD sign agrees with BTC return sign.
- **V3 (catch-up)**: V1 AND |asset_ret_30s_back| < 10bps (asset hasn't caught up to BTC yet).

V2 narrowly beats V1 on $/tr at the same WR (CVD confirmation drops a few false signals). V3 (the most theoretically appealing variant — "BTC moved, asset hasn't yet") **fails the n≥30 bar in every cell** — n=6-18 across all 6 cells. Catch-up cases are too rare; when BTC moves ≥10bps, the asset has almost always already moved too.

## Threshold sensitivity caveat

All deployable configs sit at **THR_BPS=10** — the smallest threshold tested. Higher thresholds (20/30/50bps) generate too few qualifying samples to meet n≥30 in the 28d window. The 28d sample is "quiet" (low realized vol), so high-magnitude BTC 30s moves are rare. Out of 34,504 candidate fires, only **498** (1.4%) had |BTC_ret_30s| ≥ 10bps, and only ~85 of those passed |BTC_ret_30s| ≥ 20bps. Don't tighten the threshold without re-validating on a higher-vol window.

## Overlap with S1 (VWAP continuation) on the same slugs

### Slug-level coverage
- **ETH V1** (off=90s, thr=10bps): 68 LL slugs / 3,882 S1 slugs ETH. Overlap = **68 (100% of LL)**. Unique to LL = 0.
- **ETH V2** (off=90s, thr=10bps): 65 LL slugs. Overlap = **65 (100% of LL)**.
- **SOL V1** (off=30s, thr=10bps): 38 LL slugs / 4,182 S1 slugs SOL. Overlap = 34 (89.5%). Unique to LL = 4.
- **SOL V2** (off=30s, thr=10bps): 37 LL slugs. Overlap = 33 (89.2%). Unique to LL = 4.

### Head-to-head on ETH overlapped slugs (n=68)
- **Direction agreement (LL vs S1, picking the S1 fire at offset closest to 90s)**: **92.6%**
- **LL WR=0.853, avg_pnl=$7.31/tr**
- **S1 WR=0.868, avg_pnl=$7.05/tr**
  
Statistically indistinguishable — LL and S1 detect the same regime.

### Is LL earlier than S1?
On the 68 ETH overlapped slugs, S1's earliest fire offset distribution: min=30, median=60, p75=90, max=270. **S1 fires at or before 90s on 67/68 slugs** — meaning LL@90 is LATER than S1 on virtually all of them. The "lead-lag fire ETH earlier" hypothesis fails — when BTC moves enough to trigger LL, ETH has already moved enough to trigger S1.

### Unique-to-LL SOL slugs (n=4)
WR 100%, +$4.52/tr — too small a sample to claim deployable. Manual review: all 4 fires had BTC ret matching asset 30s-back ret (BTC and SOL co-moved already), so even these "unique" fires aren't clear lead cases.


## Files

- aggregated CSV: `data/v4/canonical/_results/btc_lead_lag_5m.csv`
- per-fire parquet: `data/v4/canonical/_results/btc_lead_lag_5m_per_fire.parquet`
- script: `strategy_lab/meta_classifier/btc_lead_lag_5m.py`
- correlation probe: `strategy_lab/meta_classifier/_lead_lag_corr_probe.py`