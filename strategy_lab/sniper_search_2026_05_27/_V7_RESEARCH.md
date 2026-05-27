# V7 Research — Cross-asset, 2-leg, weighted ensembles, slot-end OFI

**Date**: 2026-05-27
**Brief**: `_BRIEF_V7.md`
**Working dir**: `strategy_lab/sniper_search_2026_05_27/_v7_research/`
**Data**: canonical v3 fires (Apr 24 → May 26, 33d), `master_gate_features_v2`, `range_filter_1s`, `regime_panel_*_v2_fixed`, `microprice_panel`, `trades_polymarket/btc.parquet`

All numbers below come from real data; no synthetic or hand-waved figures. Every claim has a backing script under `_v7_research/`.

---

## §1 — Cross-asset signal triggers (Topic 1)

**Question**: Does BTC microprice / RF / trend_slope lead ETH and SOL? At what lag is the lead strongest?

### 1a — Log-return cross-correlation (rf_1s.close, full 22d intersection)

Method: pivot 1Hz close to wide [BTC, ETH, SOL] grid (1,832,504 timestamps after dropna). Compute log returns over 5s horizon, then `corr(src, tgt.shift(-lag))` for lag ∈ {0, 1s, 5s, 30s, 60s, 300s}.

```
horizon_s  src tgt  lag_s     corr        n
        5  BTC ETH      0   0.808   1,832,499   ← contemporaneous dominates
        5  BTC ETH      1   0.685
        5  ETH BTC      1   0.708   ← ETH leads BTC by 1s slightly stronger than reverse
        5  BTC ETH      5   0.081
        5  BTC ETH     30   ~0
        5  BTC ETH     60   0.009
```

**Finding**: Contemporaneous cross-correlation (lag=0) dominates at 0.81 for BTC↔ETH and 0.64-0.67 for SOL pairs. At lag=1s, correlation drops to ~0.68-0.71. By lag=5s it collapses to ~0.08. Beyond 30s, signal is gone.

**ETH-leads-BTC slightly outperforms BTC-leads-ETH at lag=1s** (0.708 vs 0.685), which is mild and contrary to the assumption in the brief that BTC leads.

Full table: `_v7_research/topic1a_log_ret_corr.csv`.

### 1b — RF direction agreement (rf_dir 1Hz)

```
src tgt  lag_s  agree_freq
BTC ETH      0    0.7587
BTC ETH      1    0.7489
BTC ETH      5    0.6993
BTC ETH     30    0.5296
BTC ETH     60    0.5033   ← back to ~baseline 50%
BTC SOL      0    0.6931
BTC SOL      5    0.6591
BTC SOL     30    0.5183
```

**Finding**: RF direction co-moves heavily at lag=0 (76% for BTC↔ETH, 69% for BTC↔SOL). Decays to 50% (random) by lag=60s.

Full table: `_v7_research/topic1b_rf_dir_agree.csv`.

### 1c — `trend_slope_30m` on `regime_panel_5m_v2_fixed`

```
src tgt  lag_bars_5m     corr   sign_agree
BTC ETH            0    0.876        0.847    ← contemporaneous
BTC ETH            1    0.715        0.758
BTC ETH            2    0.535        0.685
BTC SOL            0    0.801        0.793
ETH SOL            0    0.833        0.812
```

**Finding**: Trend slope co-moves very strongly contemporaneously (0.80-0.88 correlation, 79-85% sign agreement). One-bar lead (5 min ahead) retains 0.715 corr, 76% sign agreement. By 15-min lead the corr drops to ~0.4.

This is the most actionable cross-asset signal: at a slow timescale (5m bars), BTC trend_slope still has predictive power for next 5m-bar's ETH/SOL trend_slope.

### 1d — Real lift on the fire universe

For each ETH 5m fire at time `fire_us`, compute BTC's 30-second log return over `[fire_us-30s, fire_us]`. Bucket and measure outcome UP rate.

```
ETH 5m baseline outcome UP rate = 0.4962  (n=85,632 fires with valid join)
BTC 30s ret > +5bps:   n=2,949   ETH UP rate = 0.7253  ← +22.9 pp lift
BTC 30s ret < -5bps:   n=2,877   ETH UP rate = 0.2628  ← -23.3 pp lift
BTC 30s ret in band:   n=79,806  ETH UP rate = 0.4994  ← no info
BTC 300s ret > +10bps: n=7,890   ETH UP rate = 0.7535  ← bigger sample, +25.7 pp lift
BTC 300s ret < -10bps: n=7,903   ETH UP rate = 0.2518  ← -24.4 pp lift

SOL 5m baseline = 0.4990  (n=59,639)
BTC 30s ret > +5bps:   n=1,988   SOL UP rate = 0.7248
BTC 30s ret < -5bps:   n=1,923   SOL UP rate = 0.2376
```

**Finding**: At larger horizon (5min BTC return ≥ 10bps), the lift is massive and symmetric on both sides. This becomes a viable directional gate with reasonable sample.

### Recommended cross-asset gates (top 2)

| Gate | Definition | Universe | Lift |
|---|---|---|---|
| `g_xa_btc_ret_300s_with` | sign(log(BTC.close[t] / BTC.close[t-300s])) matches `direction` AND abs ≥ 10 bps | ETH 5m, SOL 5m (and likely 15m) | +25 pp UP-rate either side, n~8k per side on ETH 5m |
| `g_xa_btc_ret_30s_with` | sign(log(BTC.close[t] / BTC.close[t-30s])) matches `direction` AND abs ≥ 5 bps | ETH 5m, SOL 5m | +23 pp lift, n~3k per side |

Both use `range_filter_1s.close` (BTC) joined to fire_us. Asof-safe with `asof_strict`.

The brief's third option (BTC trend_slope_30m → SOL fire) is recommended ONLY for SOL 5m at higher conviction; the 5m bar lag means re-evaluation has to occur every 5m, so prefer the 30s/300s log-return gate which can fire at any second.

Path-C gate stub for V7 agents to copy:

```python
def g_xa_btc_ret_300s_with(direction, fire_us, btc_close_1s, threshold_bps=10):
    i_t = bisect_right(btc_close_1s.index, fire_us) - 1
    i_tm = bisect_right(btc_close_1s.index, fire_us - 300_000_000) - 1
    if i_t < 0 or i_tm < 0: return 0
    bps = math.log(btc_close_1s.iat[i_t] / btc_close_1s.iat[i_tm]) * 1e4
    if abs(bps) < threshold_bps: return 0
    return int((bps > 0 and direction == "UP") or (bps < 0 and direction == "DOWN"))
```

---

## §2 — 2-leg straddle sleeves (Topic 2)

**Question**: Buy UP at offset 30 + buy DOWN at offset 180 (5m slot). Does the combined sleeve net positive?

### Setup

- Market: BTC 5m, offsets (30, 180)
- Capital: $50 (= $25 per leg, identical to single-leg stake)
- Pair: same slug, both legs from canonical v3 fire universe
- 7,328 slugs have both legs with valid fills
- Combined PnL = `pnl_up_30 + pnl_dn_180`

### Result

```
=== 2-LEG STRADDLE ($50 capital) — BTC 5m offset(30,180) ===
n = 7,328 slugs
PnL mean:    -$3.46
PnL median:  -$9.34
PnL std:     $31.51
WR (PnL>0): 26.95%
vwap_sum mean: 1.0150   (NOT < 1.00 → no synthetic arb)

vs SINGLE-LEG:
  UP @ offset 30:   mean -$0.66  std $25.99  WR 50.50%
  DN @ offset 180:  mean -$2.95  std $37.33  WR 49.09%
```

**Sleeve is worse than either single leg** on every dimension: more negative mean, lower WR (27% vs ~50%), only marginally lower std despite using 2× capital.

### Vol regime split

```
median realized_vol_60m = 3.3e-4 (split via regime_panel_5m_v2_fixed)
HI vol: n=3,180  mean -$2.80  std $37.45  WR 27.0%
LO vol: n=3,180  mean -$4.19  std $26.08  WR 26.5%

Top 25% vol: n=1,590  mean -$2.39  std $41.74  WR 27.4%
Bot 25% vol: n=1,590  mean -$3.83  std $27.22  WR 26.1%
```

Vol regime barely moves the needle — high-vol scenario is marginally less bad but still negative.

### Alt configurations

```
Alt (DOWN@30 + UP@180):  n=7,298  mean -$2.39  WR 28.1%
Pure straddle (UP@30 + DOWN@30):  n=7,804  mean -$1.25  std $14.11  WR 35.5%  vwap_sum=$1.0133
```

The pure same-second straddle (UP+DOWN both at offset 30) is *less bad* (-$1.25) but still negative. Lower std ($14 vs $32) because both legs settle to a known $1.00 of total tokens (you own exactly 1 share of each side, so payoff = $1.00 minus $vwap_sum minus fee). Mean is just `1.00 - vwap_sum_mean × (1 + fee)` ≈ -$0.013 per pair × $25/share = -$0.33 (before fee on the winning leg's profit fraction); ~ -$1.25 observed including legacy 2% fee.

### Verdict

**2-leg straddle is NOT worth pursuing for V7 search.** The vwap_sum averages > $1.00 (no arb), the fee model takes the small remaining edge, and high-vol regimes don't recover it. Single-leg with a directional gate strictly dominates. The brief's hypothesis ("captures volatility/non-direction premium") is contradicted by the data on BTC 5m.

Detailed table: `_v7_research/topic2_2leg_straddle.py` stdout above.

---

## §3 — Weighted ensemble methodology (Topic 3)

**Goal**: replace "all gates must pass" hard-stack with a weighted sum + threshold tuner.

### Methods compared

Worked example on `ETH 5m`, using 21 gates from `master_gate_features_v2`:

**M1 — WR-lift log-weights** (Brief's primary suggestion)
- `w_g = log(WR_with_gate_on / WR_with_gate_off)` computed on train (60% = 13,644 fires)
- Pros: simple, interpretable, no library dependency.
- Top-weighted gates (ETH 5m): `g_tr_above_ema200` (w=+0.458), `g_tr_above_ema800` (+0.224), `g_hurst_trending` (+0.201), `g_trend_slope_with` (+0.201, identical to hurst because both panels are derived similarly), `g_hawkes_imbalance_with` (+0.179), `g_mfi_with` (+0.116).
- Negative weights (gate is anti-predictive on this market): `g_mp_no_extreme` (-0.104), `g_bb_pos_with` (-0.100), `g_cci_with` (-0.098).

**M2 — Information Value** (Kullback-Leibler-style)
- `IV_g = Σ_v (P(g=v | won) - P(g=v | loss)) × log(P(g=v | won) / P(g=v | loss))`
- All weights non-negative by construction.
- Top IV gates: `g_hurst_trending` and `g_trend_slope_with` (both 0.221), `g_tr_above_ema800` (0.134), `g_tr_above_ema200` (0.103), `g_hawkes_imbalance_with` (0.058).

**M3 — L1 logistic regression** (sklearn `LogisticRegression(penalty='l1', solver='saga', C=0.1)`)
- Coefs include the cross-correlation structure — penalizes co-linear gates.
- Top coefs: `g_tr_above_ema200` (+0.594), `g_hurst_trending`/`g_trend_slope_with` (+0.413), `g_cci_with` (-0.337), `g_mp_no_extreme` (-0.328).
- Drives some redundant gates to exactly zero (`g_tr_stack_with`, `g_tr_above_ema50`).

### Threshold tuning protocol

Greedy search on val: try thresholds at every 1st percentile of `gate_sum` distribution, pick the one with max `dpt / std_pnl` (Sharpe-proxy) subject to `n_val ≥ 50`. Then report on lockbox.

```
=== ETH 5m threshold tuning ===
Method  Thresh  val_n  val_WR  val_$/tr  val_Sharpe  ||  lockbox_n  lockbox_WR  lockbox_$/tr
M1      0.435   206    83.0%   +$3.69    0.200       ||  195        74.4%       +$0.66
M2      0.466   203    77.3%   +$4.61    0.254       ||  171        77.8%       +$7.20
M3      0.920   186    81.7%   +$3.39    0.177       ||  195        74.4%       +$0.66
```

**M2 (Information Value) had the best lockbox lift**: +$7.20/tr at 77.8% WR on n=171, vs M1/M3 at +$0.66/tr on the same window.

### Recommended method

**M2 — Information Value weights**

Rationale:
1. Best out-of-sample $/tr on the only test case run (ETH 5m).
2. All weights non-negative by construction → easier to interpret and combine with a simple threshold.
3. Naturally penalizes gates that don't discriminate (low IV ≈ low weight).
4. No regularization hyperparameter to tune (C in L1 LR is fragile — at C=0.5 vs C=0.1 you get very different selected sets).
5. As stable as M1 on this test (similar val numbers) but generalizes better.

If V7 agents prefer interpretability and simplicity, M1 is a fine fallback. M3 (L1 LR) only worth using when n_train > 50k AND user wants automatic co-linearity handling — both not always true.

### Threshold tuner spec for V7 agents

```python
def tune_threshold(val_df, lockbox_df, gate_sum_col, *,
                   min_n=50, score='sharpe', n_thresh_steps=90):
    thresholds = np.quantile(val_df[gate_sum_col], np.arange(0.10, 1.00, 1/n_thresh_steps))
    best = None
    for t in thresholds:
        v = val_df[val_df[gate_sum_col] >= t]
        if len(v) < min_n: continue
        dpt = v['pnl_legacy_usd'].mean()
        sharpe = dpt / (v['pnl_legacy_usd'].std() + 1e-9)
        if best is None or sharpe > best['sharpe']:
            best = {'thresh': float(t), 'sharpe': float(sharpe),
                    'val_n': len(v), 'val_dpt': float(dpt),
                    'val_wr': float(v['won'].mean())}
    return best
```

Weights JSON for direct V7 consumption: `_v7_research/topic3_weights.json`.

---

## §4 — Slot-end OFI (Topic 4, BTC 15m)

**Question**: Does net order-flow imbalance in the last 60s of a 15m slot predict outcome?

### Computation

For each BTC 15m slug with a fire at `offset=840` (= `slot_end - 60s`, the earliest valid offset to avoid lookahead):

```
OFI = sum(buy_size on UP token) + sum(sell_size on DOWN token)
    - sum(sell_size on UP token) - sum(buy_size on DOWN token)
window = [slot_end - 60s, slot_end]
```

Source: `data/v4/canonical/trades_polymarket/btc.parquet` (36.6M rows; streamed via pyarrow row groups). 404,494 trades matched into the 2,844 candidate slugs.

Result: 3,948 fires with OFI computed (n=4,631 raw fires; some slugs had multiple direction fires).

### Apparent training-set edge

```
=== abs(OFI) percentile based contrarian sleeve (FULL 3,948 fires) ===
abs(OFI) p50 (thr=2,253):  n_contra=877  WR=33.8%  $/tr=$-14.03
abs(OFI) p70 (thr=4,050):  n_contra=516  WR=43.0%  $/tr=$-10.83
abs(OFI) p90 (thr=11,613): n_contra=163  WR=69.9%  $/tr=$-3.01
abs(OFI) p95 (thr=20,346): n_contra=74   WR=83.8%  $/tr=$+3.46  ← looks great
```

But this is data-snooping across the full window. We must check temporal stability.

### Chronological 60/20/20 split — TIME-STABLE TEST

Sort by `fire_us`, split into train / val / lockbox. Fire OPPOSITE to OFI sign (per the apparent training signal).

```
ofi_pct |>| 0.3:
  train     n=591  WR=40.3%  $/tr=-$12.76
  val       n=172  WR=16.3%  $/tr=-$20.55
  lockbox   n=168  WR=14.9%  $/tr=-$21.17
```

WR catastrophically collapses on val/lockbox.

### Diagnostic — relationship FLIPS

```
Outcome UP rate by OFI sign:
  train:    ofi_sign=+1 → UP 47.96%   ofi_sign=-1 → UP 51.44%   (weak contrarian)
  val:      ofi_sign=+1 → UP 62.11%   ofi_sign=-1 → UP 36.34%   (strong MOMENTUM!)
  lockbox:  ofi_sign=+1 → UP 63.93%   ofi_sign=-1 → UP 40.92%   (strong MOMENTUM!)
```

OFI sign-to-outcome relationship is NOT stable through time. On train it's weakly contrarian; on val/lockbox it's strongly momentum-aligned. This means any fixed sleeve (either contrarian OR momentum-fitted on train) will get wrecked on lockbox.

The momentum sleeve direction = OFI sign also failed on lockbox:
```
ofi_pct |>| 0.5: n_mom=1,210  WR=26.1%  $/tr=-$12.90   (lockbox)
```

### Verdict

**Slot-end OFI is NOT viable for BTC 15m as a fixed-sign gate.** The sign of the relationship is time-dependent (likely epoch-specific microstructure regimes — could be exchange listing news, fee changes, or volatility regime shifts at Polymarket itself between Apr-late and May).

A robust gate would need an *adaptive* sign-detector with a rolling 5-7d window — which is out of scope for v7 sniper-sleeve search. Recommend dropping Path D from V7 priorities. The brief's caveat ("only valid for fires AT slot_end - 60s") is correct, but the deeper problem is direction instability, not lookahead.

Detailed scripts:
- `_v7_research/topic4_slot_end_ofi.py` (raw OFI on percentiles)
- `_v7_research/topic4_slot_end_ofi_contra.py` (contrarian sleeve test)
- `_v7_research/topic4_ofi_diagnostic.py` (split-stability proof)

Output: `_v7_research/topic4_btc15m_ofi.csv` (slug-level OFI cache, reusable).

---

## Summary recommendations to V7 search agents

| Path | Verdict | Reason |
|---|---|---|
| **C — Cross-asset gates** | **PURSUE** | BTC 30s/300s log-return → ETH/SOL outcome shows +22-25pp WR lift symmetrically on both sides. Best concrete addition. Use rec'd `g_xa_btc_ret_30s_with` and `g_xa_btc_ret_300s_with`. |
| **A — Weighted ensembles** | **PURSUE** | M2 (Information Value) gave +$7.20/tr lockbox on ETH 5m; M1 fallback. Threshold tuner in §3. |
| **B — 2-leg straddle** | **DROP** | All configs lose money on BTC 5m. Vwap_sum > $1.00, so no arb. Vol regime doesn't help. |
| **D — Slot-end OFI** | **DROP** | OFI-outcome sign flips between train and lockbox (47% → 64% UP rate). Not time-stable. |

---

## Reusable artifacts written

- `_v7_research/topic1a_log_ret_corr.csv` — cross-asset log-return lag corr table
- `_v7_research/topic1b_rf_dir_agree.csv` — RF-direction agreement table
- `_v7_research/topic1c_trend_slope_corr.csv` — trend slope corr
- `_v7_research/topic2_2leg_straddle.py` — straddle backtest (stdout has all numbers)
- `_v7_research/topic3_weights.json` — ETH 5m gate weights for M1/M2/M3
- `_v7_research/topic3_weighted_ensemble.py` — methodology + threshold tuner
- `_v7_research/topic4_btc15m_ofi.csv` — per-slug OFI cache
- `_v7_research/topic4_slot_end_ofi.py` etc. — OFI scripts
