# Traders Reality Panel — 2026-05-25

Pine v5 "Traders Reality Main" indicator subset ported to numpy/pandas on 1s binance
spot OHLCV (BTC/ETH/SOL), then overlaid onto per-fire parquets via causal merge_asof.

## Artifacts
- Script: `strategy_lab/meta_classifier/compute_traders_reality.py`
- Overlay: `strategy_lab/meta_classifier/overlay_traders_reality.py`
- Panel: `data/v4/canonical/_results/traders_reality_1s.parquet` (5,497,531 rows, 82 cols, 680 MB zstd)
- Augmented per-fire:
  - `s15_with_tr.parquet` (33,323 rows, 10.7 MB)
  - `s6_with_tr.parquet` (11,336 rows, 2.4 MB)
  - `s15_with_ta_markov_tr.parquet` (33,323 rows, 20.8 MB)

## Verification
- EMA stack score formula hand-checked on 5 contiguous + 50 random BTC rows: 50/50 match.
- Causal: overlay uses `ts_us = fire_us − 1_000_000` (no lookahead into the firing second).
- ws_s convention not applicable here — we attach the most recent fully-closed 1s bar.

## 1) PVSRA distribution (% of 1s bars per asset)

| asset | climax_up | rising_up | regular | rising_dn | climax_dn |
|-------|-----------|-----------|---------|-----------|-----------|
| BTC   | 5.79%     | 0.75%     | 86.82%  | 0.76%     | 5.89%     |
| ETH   | 5.80%     | 0.80%     | 86.62%  | 0.82%     | 5.97%     |
| SOL   | 3.78%     | 0.26%     | 91.94%  | 0.25%     | 3.77%     |

## 2) EMA stack score distribution (% of 1s bars, score ∈ {−2,−1,0,+1,+2})

| asset | −2     | −1     | 0     | +1     | +2     |
|-------|--------|--------|-------|--------|--------|
| BTC   | 39.30% | 10.52% | 0.00% | 10.60% | 39.58% |
| ETH   | 37.47% | 11.76% | 0.00% | 12.01% | 38.76% |
| SOL   | 35.24% | 13.05% | 0.00% | 13.73% | 37.98% |

Score=0 is empty by construction (consec-bull − consec-bear can only be 0 if
both equal 0, but at least one of `e5>e13` / `e5<e13` is true except at exact equality).

## 3) Distance to nearest pivot level (bps, signed magnitude)

Levels: PP, R1-R3, S1-S3, M0-M5.

| asset | n         | mean_nearest_bps | median_bps |
|-------|-----------|------------------|------------|
| BTC   | 1,746,114 | 14.6             | 12.5       |
| ETH   | 1,746,112 | 19.5             | 17.8       |
| SOL   | 1,746,105 | 27.4             | 20.3       |

## 4) S1.5 UP-fire alignment vs EMA stack & PVSRA

| asset | UP fires | `bull AND UP` | %     | `bullish_pvsra AND UP` | %     |
|-------|----------|---------------|-------|------------------------|-------|
| BTC   | 4,765    | 2,097         | 44.0% | 518                    | 10.9% |
| ETH   | 6,311    | 2,578         | 40.9% | 643                    | 10.2% |
| SOL   | 5,734    | 2,505         | 43.7% | 340                    |  5.9% |
| ALL   | 16,810   | 7,180         | 42.7% | 1,501                  |  8.9% |

`bullish_pvsra` = `tr_pvsra ∈ {climax_up, rising_up}` (only ~6.5% of 1s bars
are bullish vector candles, so the 8.9% co-occurrence is near base rate).

## 5) S1.5 win rate by stack alignment

Stack direction matched / opposed to bet direction; baseline WR overall ≈ 81%.

| asset | bull&UP  WR     | bear&DN  WR     | bear&UP  WR    | bull&DN  WR    |
|-------|------------------|------------------|------------------|------------------|
| BTC   | n=2,097 wr=88.2% | n=2,114 wr=88.7% | n=21 wr=66.7%    | n=15 wr=40.0%    |
| ETH   | n=2,578 wr=87.7% | n=2,540 wr=86.7% | n=22 wr=27.3%    | n=35 wr=14.3%    |
| SOL   | n=2,505 wr=86.9% | n=2,230 wr=88.5% | n=24 wr=25.0%    | n=26 wr=34.6%    |

Strong directional signal: full-stack alignment lifts WR ~+7pp vs base; opposing
stack drops WR ~50pp on small samples (n<35 per cell).

## 6) S1.5 win rate by PVSRA class (overall, not direction-conditioned)

| asset | climax_up        | rising_up        | regular           | rising_dn        | climax_dn        |
|-------|------------------|------------------|---------------------|------------------|------------------|
| BTC   | n=647   wr=78.5% | n=97    wr=78.4% | n=8,127  wr=81.8%   | n=99    wr=87.9% | n=645   wr=80.5% |
| ETH   | n=770   wr=81.7% | n=134   wr=76.9% | n=10,622 wr=80.3%   | n=131   wr=75.6% | n=867   wr=83.4% |
| SOL   | n=474   wr=82.3% | n=34    wr=82.4% | n=10,146 wr=81.4%   | n=33    wr=81.8% | n=471   wr=82.6% |

PVSRA on its own (without direction conditioning) is near-neutral; the EMA stack
is the stronger signal in this subset.

## Notes / caveats
- Sessions use approximate UTC windows (no DST shifts).
- PsyLevels anchor: Sat 22:00 UTC; weekly H/L from prior complete psy-week.
- ADR window = 14 prior complete days; AWR = 4 prior complete weeks.
- EMA(800) requires ~800s warmup → first ~13 minutes per asset have NaN stack score
  (excluded above; <0.1% of bars).
