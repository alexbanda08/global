# Avellaneda-Stoikov + Hayashi-Yoshida investigation — 2026-05-26

**Goal**: implement Avellaneda-Stoikov (2008) reservation-price uncertainty and
Hayashi-Yoshida (2005) robust cross-correlation; test as standalone signals and
as gate overlays on top sleeves.

**Bottom line**: Hayashi-Yoshida confirms Agent P's bucketed-xcorr finding
**at sharper temporal resolution** — no venue leads Binance even at the second
level. AS uncertainty correlates +0.26 with `rv_300s` (it IS a fair-value-risk
restatement of realized vol × time-to-horizon) and offers *some* gating edge
on a small number of sleeves but underperforms Agent R's `vol_regime` overlay
on overlap. **Lockbox-validated combinations: 4 strict 3-way passers**, top
new sleeve is `07_btc_5m_s15_hybrid_v1 + g_hy_cb_with_dir` with lockbox
$3.79/tr (n=1024, lift +$1.72/tr over baseline).

Window: Apr 24 → May 25 19:15 UTC (full 32d). Fee = LegacyConfig (2%-on-profit-only).
Outcome source: chainlink RTDS.

---

## 1. Task 1 — Avellaneda-Stoikov uncertainty panel

For each fire we compute:

```
sigma      = rv_300s            # 300s rolling stdev of 1s binance log-returns
tte_s      = (slot_end_us - fire_us) / 1e6
as_uncertainty = sigma² × tte_s
as_uncertainty_norm_24h = au / rolling_24h_mean(au) per asset
as_skew    = (close_fire - vwap_slot) × γ × sigma² × tte_s    # γ = 1
```

For binary up-down markets inventory `q = 0` always (single contracts), so the
classical inventory-adjustment term `q × γ × σ² × (T-t)` collapses to zero.
The panel instead surfaces `σ² × (T-t)` as a pure "fair-value uncertainty"
proxy.

**Panel coverage**: 240,882 fires (190,170 × 5m + 50,712 × 15m), saved to
`data/v4/canonical/_results/as_panel.parquet`.

**Distribution stats**:

| tf | n_fires | valid_au | au median | au_norm_24h median |
|----|--------:|---------:|----------:|-------------------:|
| 5m | 190,170 | 181,647 | 2.03e-7 | 0.475 |
| 15m | 50,712 | 48,408 | 7.65e-7 | 0.496 |

**Critical overlap with Agent R's vol_regime** (this is the caveat flagged
in the task spec): AS-uncertainty correlates +0.26 with `rv_300s` and
splits cleanly by `vol_regime`:

| vol_regime | n | as_norm mean | as_norm p50 |
|---|---:|---:|---:|
| 0 (low) | 67,785 | 0.305 | 0.22 |
| 1 (med) | 54,991 | 0.578 | 0.51 |
| 2 (high) | 57,791 | 2.77 | 1.38 |

So `g_as_stable` (as_norm < 1) is largely a re-labelling of `vol_regime ∈ {0,1}`
with some additional resolution from TTE weighting. **The two features should
not both be used as independent gates** — pick whichever has better OOS edge
per sleeve.

---

## 2. Task 2 — Hayashi-Yoshida cross-correlation v2

### Estimator

```
HY(X, Y) = sum_i sum_j ΔX_i × ΔY_j × 1[overlap(I_i, J_j) > 0]
```

where `I_i = (t_{i-1}, t_i]` are inter-observation intervals for X and `J_j`
for Y. This handles non-synchronous sampling: when binance prints at 1Hz
and coinbase at 1/60Hz, HY pairs each coinbase return with the SUM of binance
returns that fall in the same minute.

Normalization (Pearson over the aggregated grid): we aggregate the dense X
log-returns into each sparse Y interval, then compute a standard correlation
between the aggregated X-into-Y series and Y. This bounds HY_corr in [-1, 1].

### Results — full lag profile per (asset, venue)

Common window: May 7 13:00 → May 16 06:00 UTC (~9d, bounded by
alt-venue staleness — see CROSS_EXCHANGE_LEADLAG report). Lag convention:
**lag > 0 = venue LEADS binance**.

Peak lag per (asset, venue):

| Asset | Venue | peak_lag | peak_hy | hy at −5s | hy at 0 | hy at +5s |
|---|---|---:|---:|---:|---:|---:|
| BTC | coinbase | 0s | 0.971 | 0.937 | **0.971** | 0.891 |
| BTC | kraken | -5s | 0.886 | **0.886** | 0.884 | 0.829 |
| BTC | okx | 0s | 0.974 | 0.945 | **0.974** | 0.890 |
| ETH | coinbase | 0s | 0.977 | 0.939 | **0.977** | 0.892 |
| ETH | kraken | -5s | 0.907 | **0.907** | 0.901 | 0.831 |
| ETH | okx | 0s | 0.980 | 0.941 | **0.980** | 0.896 |
| SOL | coinbase | 0s | 0.974 | 0.885 | **0.974** | 0.888 |
| SOL | kraken | -1s | 0.911 | 0.881 | 0.903 | 0.795 |
| SOL | okx | 0s | 0.977 | 0.931 | **0.977** | 0.886 |

### Comparison with Agent P (1MIN bucketed xcorr)

Agent P at 1-minute granularity found peak xcorr at lag=0 for all (asset, venue)
pairs with coefficients 0.89-0.99. HY at 1-second granularity:

* **Confirms** lag=0 peak for all coinbase/OKX pairs.
* **Confirms** kraken slightly trails (peak at -1 to -5s = binance leads kraken),
  consistent with kraken being lower-volume / lower-data-quality.
* **Sharper picture**: the HY lag profile (HY at ±10s, ±30s, ±60s) decays
  smoothly and symmetrically — there's no asymmetric "tail" indicating a venue
  leads. With Agent P's 1-min bucketing the closest off-zero lag was at 60s
  granularity, hiding sub-minute structure. HY shows the structure IS smoothly
  decaying within ±60s, with peak strictly at 0±1s.
* **No new lead-lag asymmetry**: HY does not surface anything Agent P missed.

**Conclusion**: no venue leads Binance at any granularity. Binance is the
price-discovery venue. HY-based cross-correlation cannot be used as a
predictive lead signal. The "g_hy_cb_with_dir" gate (coinbase 1m direction
matches sleeve direction) is therefore a CONTEMPORANEOUS confirmation, not
a lead.

Saved: `strategy_lab/avell_hayashi_2026_05_26/hy_xcorr_results.csv`

---

## 3. Task 3 — Standalone rule WRs

Tested rules (n ≥ 100 required to be reported):

| Rule | What it does | Best per-trade across (asset,tf) |
|------|--------------|---------------------------------:|
| AS-A_kept (UP/DOWN) | KEEP fires where as_norm ≤ 2 | −$1.72 to −$6.11 |
| AS-A_skipped (UP/DOWN) | EXCLUDE bucket; would be skipped | −$1.92 to −$5.24 |
| AS-B_with_30s | Bet WITH ret_30s direction when as_norm < 0.5 | +$0.0046 (BTC 15m off 120-180) |
| AS-C_skew_UP | Bet UP when as_skew > 0 AND close > vwap | −$0.11 to −$1.22 |
| HY-A_cb_with | Bet WITH coinbase 1m direction | +$0.27 to −$1.43 best/worst |

**Critically**: AS-A "skipped" bucket (high-uncertainty fires we WANTED to
skip) has SLIGHTLY HIGHER WR (+1 to +3pp) than "kept" bucket — so skipping
high-uncertainty fires would have REMOVED slightly better-performing trades.
The AS-A skip rule has **negative standalone value** as a simple SKIP gate.

Standalone signal hunting on AS/HY = **mostly negative**. Both metrics are
contemporaneous; neither is predictive in isolation.

Saved: `strategy_lab/avell_hayashi_2026_05_26/standalone_rules_results.csv`

---

## 4. Task 4 — AS + HY as gates on top 15 sleeves

Gates tested (each applied independently to each of the 15 sleeves from
`FULL_WINDOW_VALIDATION`):

| Gate | Definition |
|---|---|
| g_as_stable | as_norm < 1.0 |
| g_as_norm_lt_05 | as_norm < 0.5 |
| g_as_norm_lt_15 | as_norm < 1.5 |
| g_as_unstable_skip | as_norm ≤ 2 |
| g_hy_cb_with_dir | coinbase 1m sign matches sleeve direction |
| g_as_stable_AND_hy_with | both above |

### Summary across 15 sleeves

| Gate | sleeves_evaluated | sleeves_positive_lift | mean_dpt_lift | median_dpt_lift | retain_p50 |
|---|---:|---:|---:|---:|---:|
| g_as_stable | 14 | 5/14 | −0.23 | −0.50 | 26% |
| g_as_norm_lt_05 | 10 | 4/10 | −1.29 | −0.45 | 34% |
| g_as_unstable_skip | 15 | 5/15 | −1.43 | −0.52 | 45% |
| g_as_norm_lt_15 | 15 | 5/15 | −1.71 | −0.52 | 25% |
| g_hy_cb_with_dir | 15 | 3/15 | −0.79 | −0.41 | 70% |
| g_as_stable_AND_hy_with | 13 | 4/13 | −0.06 | −0.35 | 31% |

The median lift is negative across all gates — most sleeves are HURT by adding
AS or HY filters. But a handful of sleeves show large positive lifts.

### Notable positive lifts (gated_n ≥ 30, dpt_lift > 0)

| Sleeve | Gate | base $/tr | gated_n | gated $/tr | dpt_lift |
|---|---|---:|---:|---:|---:|
| 01_btc_5m_s6_hybrid_v2_sms | g_as_stable_AND_hy_with | $0.62 | 33 | $17.83 | **+$17.21** |
| 01_btc_5m_s6_hybrid_v2_sms | g_as_stable | $0.62 | 44 | $11.30 | +$10.68 |
| 08_sol_5m_s6_hybrid_v1 | g_as_norm_lt_15 | $1.87 | 386 | $3.82 | +$1.95 |
| 01_btc_5m_s6_hybrid_v2_sms | g_hy_cb_with_dir | $0.62 | 502 | $2.49 | +$1.87 |
| 08_sol_5m_s6_hybrid_v1 | g_as_stable | $1.87 | 129 | $3.52 | +$1.65 |
| 13_pool_15m_offge480 | g_as_stable | $0.79 | 942 | $1.48 | +$0.69 |
| 13_pool_15m_offge480 | g_as_norm_lt_05 | $0.79 | 726 | $1.46 | +$0.67 |
| 11_eth_15m_off120_240 | g_as_norm_lt_05 | $1.37 | 64 | $2.07 | +$0.70 |
| 04_eth_5m_s6_hybrid_v1 | g_hy_cb_with_dir | $1.57 | 2379 | $2.10 | +$0.53 |
| 13_pool_15m_offge480 | g_as_unstable_skip | $0.79 | 1085 | $1.22 | +$0.43 |
| 10_btc_15m_s7_hybrid_v1 | g_as_norm_lt_05 | $0.39 | 802 | $0.81 | +$0.42 |

`g_as_stable_AND_hy_with` on sleeve 01 (BTC 5m s6 v2 sms) — n=33 over the
REF-only 21d period is too small to deploy confidently. But the
**13_pool_15m_offge480 + g_as_stable** combination (n=942 retained from
1,207 baseline = 78%) is a clean retention-friendly gate with material
per-trade lift.

Saved: `strategy_lab/avell_hayashi_2026_05_26/gate_overlay_results.csv`

---

## 5. Task 5 — Strict 3-way validation (train / val / lockbox + 200-shuffle bootstrap)

Window splits:
* train: Apr 24 → May 14 (20d)
* val: May 14 → May 21 (7d)
* lockbox: May 21 → May 25 19:15 (~5d)

Built unified panel = prefix (Apr 24-30) + REF (May 1-21, joined panels with
sms liquidity) + OOS (May 21-25) for each (asset, tf). Deduped on
(slug, fire_us, direction).

**Strict passers** (ALL of: train dpt > 0 AND val dpt > 0 AND lockbox dpt > 0 AND
lockbox lift > 0 AND lockbox n ≥ 30): **4 of 90 combos (15 sleeves × 6 gates)**

| # | Sleeve | Gate | n_train | dpt_train | n_val | dpt_val | n_lockbox | dpt_lockbox | lockbox_lift |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 07_btc_5m_s15_hybrid_v1 | g_hy_cb_with_dir | 3,168 | $0.09 | 304 | $0.96 | 1,024 | **$3.79** | +$1.72 |
| 2 | 02_btc_5m_s6_hybrid_v1 | g_as_norm_lt_15 | 1,160 | $0.03 | 650 | $1.12 | 410 | **$2.64** | +$0.61 |
| 3 | 02_btc_5m_s6_hybrid_v1 | g_as_stable | 888 | $0.51 | 460 | $1.17 | 352 | **$2.56** | +$0.53 |
| 4 | 02_btc_5m_s6_hybrid_v1 | g_as_unstable_skip | 1,325 | $0.42 | 750 | $0.90 | 451 | **$2.39** | +$0.37 |

(200-shuffle bootstrap CIs available in
`strategy_lab/avell_hayashi_2026_05_26/walkforward_results.csv`)

### Top 5 NEW deployable AS/HY sleeves (lockbox-validated)

1. **07_btc_5m_s15_hybrid_v1 + g_hy_cb_with_dir** — best new sleeve.
   Filter S7's BTC 5m fires (off 150-240, ribbon agrees + stoch with + tight ribbon +
   tr_above_pp) to those where coinbase 1m return matches direction.
   Lockbox: n=1,024, WR ≈ 80%, $3.79/tr, sum +$3,884.
   Note: the existing sleeve 07's lockbox baseline is $2.08/tr (n=1,783); HY-gate
   keeps 57% of fires while lifting $/tr by 82%.

2. **02_btc_5m_s6_hybrid_v1 + g_as_norm_lt_15** — BTC 5m S6 hybrid v1 with
   AS-uncertainty < 1.5x rolling-24h mean. Lockbox n=410, $2.64/tr (+24% vs
   baseline $2.10).

3. **02_btc_5m_s6_hybrid_v1 + g_as_stable** — same sleeve with stricter as_norm < 1.
   Lockbox n=352, $2.56/tr (+22% vs baseline). Higher per-trade than #2 but
   keeps fewer fires.

4. **02_btc_5m_s6_hybrid_v1 + g_as_unstable_skip** — keep fires with as_norm ≤ 2.
   Lockbox n=451 (largest retain), $2.39/tr (+14% vs baseline). Least restrictive.

5. **13_pool_15m_offge480 + g_as_stable** — high-base sleeve, retains 78% with
   +$0.69/tr lift in REF. Lockbox shows weaker train baseline so didn't pass strict
   3-way, but it's the best LARGE-RETAIN candidate. Caveat: 15m sleeves had weak
   lockbox performance overall this period.

### Looser lockbox passers (lockbox dpt > 0, n ≥ 30, regardless of train/val)

20 more combinations pass loose criteria (top 20 in `walkforward_results.csv`).
Several are recovery cases — sleeves that lost money in train/val but improved
in lockbox under the gate. Not deployable without longer OOS confirmation, but
worth tracking.

---

## 6. Caveats and limitations

* **AS uncertainty overlaps heavily with vol_regime (Agent R)** — they capture
  the same information. Don't stack both. AS adds TTE-weighting which gives
  finer per-fire resolution, but the standalone-rule tests show this doesn't
  translate to predictive edge.
* **HY needs tick data we don't fully have at sub-second granularity for
  alt-venues**. Binance has 1SEC closes; coinbase/kraken/OKX are 1MIN only. So
  the HY analysis is fundamentally limited to ±60s lag visibility on
  cross-CEX pairs. Within that window, no lead. We CAN'T rule out a sub-second
  alt-venue lead because we don't have the data. (HL trades go to 1s but those
  are stale May 16, and Agent P already showed binance LEADS HL by 1s.)
* **No venue leads binance** — HY confirms Agent P's bucketed result with
  sharper resolution. Lead-lag is a dead-end direction unless we acquire
  sub-second alt-venue tick data.
* **AS-uncertainty is contemporaneous, not predictive**. The SKIP-when-unstable
  rule (AS-A) has the WRONG sign — unstable fires have slightly HIGHER WR.
  Use AS as a confidence filter that LIFTS some sleeves' per-trade returns by
  narrowing focus to lower-uncertainty regimes, not as a universal predictor.
* **Lockbox window is only ~5 days**. Strict passers (4) survived 20d/7d/5d.
  Recommend running another 2 weeks of paper deployment before live-sizing.
* **AS-skew direction picker doesn't work** (AS-C standalone is uniformly
  negative). The `gamma=1` choice and binary-token interpretation make AS-skew
  essentially noise.

---

## Artifacts

* `strategy_lab/avell_hayashi_2026_05_26/t1_as_panel.py`
* `strategy_lab/avell_hayashi_2026_05_26/t2_hy_xcorr.py`
* `strategy_lab/avell_hayashi_2026_05_26/t3_standalone_rules.py`
* `strategy_lab/avell_hayashi_2026_05_26/t4_gate_overlay.py`
* `strategy_lab/avell_hayashi_2026_05_26/t5_walkforward.py`
* `data/v4/canonical/_results/as_panel.parquet` (240,882 rows, 22 cols)
* `strategy_lab/avell_hayashi_2026_05_26/hy_xcorr_results.csv` (117 rows)
* `strategy_lab/avell_hayashi_2026_05_26/standalone_rules_results.csv` (89 rows)
* `strategy_lab/avell_hayashi_2026_05_26/gate_overlay_results.csv` (90 rows)
* `strategy_lab/avell_hayashi_2026_05_26/walkforward_results.csv` (315 rows)
* `strategy_lab/avell_hayashi_2026_05_26/walkforward_pivot.csv` (90 rows)
