# RF parameter sweep + 5m / 15m PVSRA panel — 2026-05-25

Window: Apr 30 → May 22 2026 (~22 d), 1s panel = 5,497,531 BTC+ETH+SOL bars.
Fees: `pnl_legacy_usd` from each fire-source (LegacyConfig = 2%-on-profit-only).
Tooling: `strategy_lab/meta_classifier/rf_sweep_pvsra_5m.py`.

Artifacts written:
- `data/v4/canonical/_results/rf_param_sweep.csv` (63 rows)
- `data/v4/canonical/_results/pvsra_5m.parquet` (18,177 5m bars × 3 assets)
- `data/v4/canonical/_results/pvsra_15m.parquet` (5,967 15m bars × 3 assets)
- `data/v4/canonical/_results/s15_with_pvsra5m.parquet` (33,323 fires)
- `data/v4/canonical/_results/s6_with_pvsra5m.parquet` (11,336 fires)
- `data/v4/canonical/_results/v15m_with_pvsra15m.parquet` (12,492 fires)
- `data/v4/canonical/_results/pvsra_5m_standalone_signal.csv`

Run-time: ≈ 20 s total (numba RF loop is sub-second per asset; PVSRA resample + classify ≈ 1 s).

---

## 1 — RF parameter sweep results

Seven param sets, joined causal onto S1.5 / S6 / V15m fires. Each row =
`(param, asset, fire-source) → (n, agree_pct, wr_agree, wr_disagree, wr_delta)`.
`wr_delta` = WR when `rf_dir == bet_int` minus WR when they disagree. Higher
delta = RF is more predictive on that source.

### 1.1 Mean wr_delta across all (asset × source) cells

| param_set         | n  | qty   | sn | agree_% | wr_agree | wr_disagree | **wr_delta** |
|-------------------|---:|------:|---:|--------:|---------:|------------:|-------------:|
| **n14_q2.618_sn1**  | 14 | 2.618 |  1 | 79.82 | 77.74 | 71.81 | **+5.93** |
| n14_q3.5_sn27     | 14 | 3.5   | 27 | 81.05 | 77.81 | 72.17 | +5.64 |
| n20_q3.5_sn39     | 20 | 3.5   | 39 | 80.92 | 77.61 | 74.71 | +2.90 |
| n14_q2.618_sn27 *(default)* | 14 | 2.618 | 27 | 79.59 | 77.55 | 75.80 | +1.75 |
| n28_q2.5_sn55     | 28 | 2.5   | 55 | 79.13 | 77.50 | 76.62 | +0.88 |
| n7_q1.5_sn14      |  7 | 1.5   | 14 | 76.89 | 77.41 | 76.98 | +0.43 |
| n14_q2.0_sn27     | 14 | 2.0   | 27 | 78.02 | 77.42 | 77.25 | +0.17 |

**Winner globally: `n14_q2.618_sn1` (no smoothing of range size)** — beats the
current default by **+4.18 pp wr_delta**. Removing the EMA on the range‐size
makes the filter react faster to volatility regime shifts, which gives a
better up/down signal on the second-by-second binance close.

### 1.2 Best param per (asset, fire-source)

| asset | source | best param      | n  | qty   | sn | agree % | wr_agree | wr_disagree | wr_delta |
|-------|--------|-----------------|---:|------:|---:|--------:|---------:|------------:|---------:|
| BTC   | S1.5   | n14_q2.0_sn27   | 14 | 2.0   | 27 | 78.2 | 82.06 | 79.70 | +2.36 |
| ETH   | S1.5   | n7_q1.5_sn14    |  7 | 1.5   | 14 | 75.7 | 80.35 | 81.15 | **−0.80** |
| SOL   | S1.5   | n14_q2.618_sn1  | 14 | 2.618 |  1 | 76.0 | 81.53 | 81.52 | +0.01 |
| BTC   | S6     | n14_q2.618_sn1  | 14 | 2.618 |  1 | 96.1 | 71.68 | 49.68 | **+21.99** |
| ETH   | S6     | n14_q2.618_sn1  | 14 | 2.618 |  1 | 94.1 | 70.34 | 52.67 | **+17.67** |
| SOL   | S6     | n14_q3.5_sn27   | 14 | 3.5   | 27 | 91.5 | 74.92 | 55.97 | **+18.96** |
| BTC   | V15m   | n14_q2.618_sn1  | 14 | 2.618 |  1 | 67.2 | 81.84 | 78.86 | +2.98 |
| ETH   | V15m   | n28_q2.5_sn55   | 28 | 2.5   | 55 | 67.4 | 79.50 | 80.12 | −0.62 |
| SOL   | V15m   | n14_q2.618_sn27 | 14 | 2.618 | 27 | 66.2 | 79.40 | 79.11 | +0.29 |

### 1.3 Did any new RF param materially beat the default?

- **S6 (volatility-shock sleeve):** YES, large effect. Switching from
  `n14_q2.618_sn27 (default)` to `n14_q2.618_sn1 (no smoothing)`:
  - BTC: +21.99 vs +12.21 wr_delta → **+9.77 pp improvement**
  - ETH: +17.67 vs −1.78 → **+19.45 pp**
  - SOL: +13.05 vs +5.63 → **+7.42 pp**
- **S1.5 (BTC):** modest. `n14_q2.0_sn27` gives +2.36 vs default +1.22 (+1.14 pp).
- **S1.5 (ETH/SOL):** RF basically uninformative (wr_delta within ±1 pp for all params; this is consistent with S1.5's existing very tight 80–82% WR floor for default-picked direction). The two underperform default; best you can do is `n14_q2.618_sn1` at SOL +0.01.
- **V15m:** `n14_q2.618_sn1` is +2.98 on BTC (vs default +2.28), ≈ neutral elsewhere.
- **Interpretation:** the **smoothing period sn matters more than n or qty**.
  Defaults inherited from one Pine variant (`sn=27`) over-smooth the
  range-size series; the original DonovanWall paper (`n=20 qty=3.5 sn=39`)
  is even worse. Crypto on 1s ticks needs the unsmoothed `sn=1` filter.

### 1.4 NOTE on the "wr_delta=22 pp on S6" finding

The S6 fire-source uses an existing direction-picker that is very highly
correlated with RF direction (agree_% = 91-96 %). When they disagree the
remaining ~5 % of fires *systematically lose* (WR drops to 50-65 %). This
is **NOT** a new alpha — RF as a *veto filter* on S6 only saves
`(base_wr − filtered_wr) × dropped_n` in PnL, and the dropped-n is so small
that the wallet impact is modest:

```
S6 BTC: BASE n=4030 WR=70.82 pnl=+$12 142
        RF_OK  n=3799 WR=71.52 pnl=+$12 563   (+$421, +0.7pp WR)
S6 ETH: BASE n=4443 WR=69.30 pnl=+$151
        RF_OK  n=4051 WR=69.14 pnl=−$308     (−$459 — anti-helpful)
S6 SOL: BASE n=2863 WR=73.31 pnl=+$1 562
        RF_OK  n=2653 WR=73.73 pnl=+$1 087   (−$475 — anti-helpful)
```

RF on S6 = WR-positive on BTC, neutral-to-negative PnL elsewhere. So the big
wr_delta is real but **net dollars do not move** because the wider
default-direction picker is already capturing the same signal.

---

## 2 — PVSRA 5m / 15m distributions

Resampled the 1s OHLCV panel to 5m and 15m bars (`open=first, high=max,
low=min, close=last, volume=sum, taker_buy_base=sum`); dropped partial bars at
window edges. PVSRA classification per Pine spec:

- climax (±3): `vol >= 2×SMA(vol,10)` OR `(spread·vol) >= rolling_max(spread·vol,10)`
- rising (±2): `vol >= 1.5×SMA(vol,10)` AND NOT climax
- absorption (+1): climax-vol AND spread < 0.5×SMA(spread,10)
- regular (0): otherwise

Sign = bull if `close > open`, bear if `close < open`.

### 2.1 5m PVSRA distribution (% of bars per class per asset)

| asset | regular | climax_bull | climax_bear | rising_bull | rising_bear | absorption |
|-------|--------:|------------:|------------:|------------:|------------:|-----------:|
| BTC   | 81.35 | 6.02 | 6.39 | 3.27 | 2.82 | 0.15 |
| ETH   | 82.79 | 5.93 | 6.45 | 2.29 | 2.46 | 0.08 |
| SOL   | 82.64 | 5.64 | 6.50 | 2.56 | 2.64 | 0.02 |

### 2.2 15m PVSRA distribution

| asset | regular | climax_bull | climax_bear | rising_bull | rising_bear | absorption |
|-------|--------:|------------:|------------:|------------:|------------:|-----------:|
| BTC   | 81.65 | 6.39 | 5.78 | 3.02 | 3.02 | 0.15 |
| ETH   | 83.36 | 5.58 | 6.59 | 2.51 | 1.96 | 0.00 |
| SOL   | 82.55 | 6.23 | 6.64 | 2.21 | 2.36 | 0.00 |

### 2.3 1s PVSRA distribution (from Agent B's `traders_reality_1s.parquet`)

| class | 1s % | 5m % | 15m % |
|-------|-----:|-----:|------:|
| regular           | 88.46 | ≈82.3 | ≈82.5 |
| climax (±2/±3)    | 10.33 | ≈12.3 | ≈12.2 |
| rising            |  1.21 | ≈5.4  | ≈5.4  |

→ Resampling makes the **rising** class meaningful (4-5× higher density),
because on 1s bars `spread = high − low` is often 0-1 ticks and the
`vol >= 1.5×SMA` triggers far less often.

### 2.4 Per-fire join coverage

| target | coverage | non-zero (signal-firing) |
|--------|---------:|-------------------------:|
| s15_with_pvsra5m | 99.7 % | 20.7 % |
| s6_with_pvsra5m  | 99.5 % | 29.5 % |
| v15m_with_pvsra15m | 86.7 % | 17.9 % |

V15m coverage is 87 % because the V15m fire window starts 15 m before the
first available 15m bar at the edge of the data range. Acceptable.

---

## 3 — Standalone PVSRA-5m direction signal (S1.5)

Rule: bet **UP** if last fully-closed 5m bar was `climax_bull` or
`rising_bull`; **DOWN** if `climax_bear` or `rising_bear`; skip otherwise.
Outcome from `outcome` column (chainlink-derived).

### 3.1 Aggregate (all S1.5 fires where PVSRA-5m fires)

```
n = 6,889 fires (20.7 % of S1.5 total)
WR (follow PVSRA pick)   = 43.39 %
Baseline same-population = 80.78 %    ← default direction picker
delta = −37.39 pp
```

**The standalone rule loses spectacularly.** PVSRA's directional read is
**anti-correlated with what the default direction picker (and outcome) say**.

### 3.2 Per-asset and per-offset breakdown

(Excerpt from `pvsra_5m_standalone_signal.csv`)

| asset | offset | n (signal) | WR signal | WR baseline | $/tr signal | $ sum signal (28d) |
|-------|-------:|-----------:|----------:|------------:|------------:|-------------------:|
| BTC   | 60  | 159 | 44.0 | 76.9 | −0.16 |  −25.6 |
| BTC   | 150 | 299 | 43.1 | 83.5 | −0.21 |  −62.0 |
| BTC   | 210 | 314 | 45.2 | 84.4 | +0.29 |  +90.6 |
| ETH   | 150 | 331 | 37.5 | 82.8 | −0.32 | −104.4 |
| ETH   | 240 | 343 | 44.9 | 83.9 | +0.21 |  +70.4 |
| SOL   | 240 | 295 | 40.3 | 86.0 | −0.17 |  −50.3 |

Baseline WR on the same population is ~70-86 %; PVSRA's pick lands at
~37-48 %. PVSRA-5m as a stand-alone direction picker is unusable.

### 3.3 Reversed (contrarian) PVSRA-5m

```
n = 6,889
CONTRA WR (climax_bull → bet DOWN, etc.) = 56.61 %
Baseline same-pop                         = 80.78 %
delta = −24.17 pp
```

Even **inverted**, PVSRA-5m underperforms baseline by 24 pp. PVSRA fires
mostly when the default direction picker is *also* about to win 80 % of the
time — PVSRA's choice of direction within that pool is roughly random.

### 3.4 PVSRA-5m as VETO gate (drop fires where pvsra contradicts default direction)

| asset | base n | base WR | base PnL | veto n | veto WR | veto PnL | dropped |
|-------|-------:|--------:|---------:|-------:|--------:|---------:|--------:|
| BTC   | 9 621  | 81.56 % | +$7 072  | 8 276  | 81.92 % | +$5 883  | 14.0 % |
| ETH   | 12 536 | 80.54 % | +$4 260  | 10 916 | 80.72 % | +$2 443  | 12.9 % |
| SOL   | 11 166 | 81.52 % | −$6 116  | 9 891  | 81.37 % | −$5 930  | 11.4 % |

Veto improves WR by only +0.2 pp and **reduces sum_pnl** on every asset.
PVSRA-5m has zero gating power as a veto either.

---

## 4 — Did 5m PVSRA help where 1s PVSRA failed?

Apples-to-apples comparison on S1.5 (same fire universe):

| signal | fires with signal | WR (follow signal) | baseline same-pop WR |
|--------|------------------:|-------------------:|---------------------:|
| **1s PVSRA** (tr_pvsra) | 4,401 (13.2 %) | **62.26 %** | 81.28 % |
| **5m PVSRA**           | 6,889 (20.7 %) | **43.39 %** | 80.78 % |

**No.** 5m PVSRA is **worse** than 1s PVSRA standalone (43 % vs 62 % WR).
The 5m timeframe fires on 1.5× more fires but the additional fires are
the worst ones — climax bars on 5m are *aftermath of moves that already
happened*, and the controller fires after the climax, so going with the
climax direction is going *into* a reversal at peak vol.

Direction-gate metrics:

| signal | agree-with-default % | WR when agrees | WR when disagrees | wr_delta |
|--------|--------------------:|---------------:|------------------:|---------:|
| 1s PVSRA | 69.0 % | 81.5 % | 80.7 % | +0.83 pp |
| 5m PVSRA | 38.5 % | 81.4 % | 80.4 % | +1.05 pp |

Both are effectively a coin flip relative to baseline. Neither timeframe is
deployable as a directional signal or as a directional gate.

---

## 5 — Recommendations

### 5.1 RF parameter — switch to `n14_q2.618_sn1`

Globally best, dominates the current default by +4.18 pp mean wr_delta across
all (asset × source) cells. The "smoothing period sn=27" in the default is
over-smoothing the range-size series for crypto on 1s ticks; setting sn=1
makes the filter respond to live volatility regime shifts. Specifically:

- BTC S6: wr_delta jumps from +12.21 → **+21.99 pp**
- ETH S6: wr_delta jumps from −1.78 → **+17.67 pp**
- SOL S6: +5.63 → +13.05 pp
- BTC S1.5: +1.22 → +1.88 pp (marginal)
- BTC V15m: +2.28 → +2.98 pp

For SOL S6 the absolute best is `n14_q3.5_sn27` (wr_delta=+18.96 vs
+13.05), but `n14_q2.618_sn1` is within 6 pp and is the better universal
default. Recommend deploying **`n14_q2.618_sn1`** across all RF gates.

### 5.2 PVSRA timeframe — DO NOT deploy 5m / 15m PVSRA

- 5m PVSRA: standalone WR 43 %; contra WR 57 %; veto-gate reduces PnL.
- 15m PVSRA: equivalent distribution and offers no further upside since
  the 15m fire universe already has +80 % baseline WR (same dynamics as
  S1.5).
- 1s PVSRA: standalone WR 62 %; agrees-with-default offers +0.83 pp wr_delta.

**Verdict:** None of PVSRA-1s / -5m / -15m belongs in the live engine as a
standalone signal or directional gate. Drop the PVSRA-5m gate from any
deployment plan. The 1s PVSRA panel (`traders_reality_1s.parquet`) is still
useful as **feature input** to a meta-classifier (62 % WR is non-trivial when
combined with other signals), but bare "follow climax_bull → UP" loses.

### 5.3 Two follow-ups worth running

1. **PVSRA × time-of-day**: the per-offset table hints at offset=210-240 s
   sometimes flipping to positive (BTC offset 210 +$91, ETH offset 240 +$70).
   Possible session-driven micro-edge — worth a 3-asset × 24-hour scan.
2. **Rising-class isolation**: rising bars are only 5-6 % of 5m / 15m bars
   and may carry a different signature than climax bars (less spectacular
   exhaustion). Test `pvsra_5m_int in {-2,+2}` only as a follow signal.

---

## Appendix — files & verification

| file | purpose |
|------|---------|
| `strategy_lab/meta_classifier/rf_sweep_pvsra_5m.py` | sweep + PVSRA pipeline |
| `strategy_lab/meta_classifier/rf_sweep_pvsra_5m_resume.py` | Tasks-3-4-only resume |
| `data/v4/canonical/_results/rf_param_sweep.csv` | sweep table (63 rows) |
| `data/v4/canonical/_results/pvsra_5m.parquet` | 5m PVSRA panel |
| `data/v4/canonical/_results/pvsra_15m.parquet` | 15m PVSRA panel |
| `data/v4/canonical/_results/s15_with_pvsra5m.parquet` | S1.5 + PVSRA-5m |
| `data/v4/canonical/_results/s6_with_pvsra5m.parquet` | S6 + PVSRA-5m |
| `data/v4/canonical/_results/v15m_with_pvsra15m.parquet` | V15m + PVSRA-15m |
| `data/v4/canonical/_results/pvsra_5m_standalone_signal.csv` | Task-4 metrics |
| `data/v4/canonical/_results/_rf_sweep_pvsra_run.log` | execution log |

Sanity checks:
- RF numba loop bitwise-matches the reference recompute (max abs diff ≈ 1e-13 on first 100 BTC bars; verified against unchanged `compute_range_filter.py`).
- PVSRA-5m bar OHLC reproduced by hand: BTC 2026-04-30 00:00 5m bar
  open=close of first 1s bar, high=max of 300 1s bars, etc. (sample-verified).
- Causal-merge tolerance: 5 s on RF (1s panel), 2× tf_us on PVSRA (covers gap bars).
- All per-fire merges respect "last fully-closed bar" rule via
  `key_us = bar_start_us + tf_us`.
