# Mint-and-Sell V3 simulation — asymmetric one-sided posting

**Date:** 2026-05-23
**Inputs:** `data/v4/canonical/_results/mint_and_sell_cvd_overlay.csv` (7,490 V2 fills,
~15.05 days span Apr 21 → May 06), V2 per-cell `policy_compare.parquet` files for
per-leg ask prices.
**Output CSV:** `data/v4/canonical/_results/mint_and_sell_v3_simulation.csv`
**Engines:** `strategy_lab/markov_filter/_v3_simulate.py`, `_v3_deeper.py`, `_v3_final.py`

---

## TL;DR — V3 does NOT flip V2 to positive PnL

| Variant | Total daily PnL | Δ vs V2 |
|---|---|---|
| V2 baseline (sample×extrap, span 15.05d) | **-$21,186/day** | — |
| V3 pure CVD-asymmetric (cvd_pct=0.50, no sigma) | -$17,843/day | +$3,343 |
| V3 pure sigma-skip (sigma_pct=0.50, no CVD) | -$11,494/day | +$9,692 |
| V3 sigma+CVD combined (uniform p=0.50, p=0.50) | -$9,835/day | +$11,351 |
| V3 ultra-aggressive uniform (cvd_p=0.30, sigma_p=0.10) | **-$1,962/day** | +$19,224 |
| V3 per-cell tuned (overfit) | **-$1,381/day** | +$19,805 (93.5%) |

**Verdict:** V3 reduces V2's per-day bleed by 47-94%, but the strategy remains net-negative
even at the most aggressive gating. **Two cells (eth_15m, sol_15m) cross slightly into
positive territory under per-cell tuning, but the gain comes from extreme sigma cuts that
skip 85-90% of fills — not from the CVD-asymmetric posting idea itself.**

The CVD-asymmetric component of V3 contributes only ~$3-4k/day of the ~$20k/day total
improvement. The dominant lever is the sigma volatility filter.

---

## Methodology

For each V2 fill record:
- `cvd_slope_30s` = binance 1s signed-flow slope joined to fill timestamp
- `sigma_60s` = binance 1s log-return rolling stdev
- V3 rule (per task spec):
  - `cvd_slope_30s > +cvd_thr` → SKIP UP-side post. Only DOWN-ask is live.
  - `cvd_slope_30s < -cvd_thr` → SKIP DOWN-side post. Only UP-ask is live.
  - `|cvd_slope_30s| < cvd_thr` → post BOTH (V2 baseline behavior).
- Sigma filter (robustness): `sigma_60s > sigma_thr` → SKIP whole opportunity (no posts).

**V3 per-fill PnL math** (notional N=$2.5, fee curve `0.07·p·(1-p)`, maker rebate
share 0.20 — matching V2 backtest configuration):

```
Case A (V3 = V2 BOTH posting):  pnl = pnl_hold  [from V2 record]
Case B (V3 skips UP post, only DN posted):
  if dn_filled:  pnl = N·ad + N·0.014·ad·(1-ad) + N·{outcome=Up} - N
  else:          pnl = 0
Case C (V3 skips DN post, only UP posted):
  if up_filled:  pnl = N·au + N·0.014·au·(1-au) + N·{outcome=Down} - N
  else:          pnl = 0
Sigma skip:      pnl = 0
```

Where `au=ask_up`, `ad=ask_dn` from V2 opportunities parquet.

**Simplifying assumption (per task spec):** V2's per-side fill rates are independent
(skipping the UP post does not change DOWN's fill probability). This is the right first
cut — a full re-sim with order-book replay would tighten the estimate.

**V2 fee model used in original V2 results:** the "real curve" `0.07·p·(1-p)` with
maker rebate. (Per CLAUDE.md, production currently uses legacy 2%-on-profit only, so
these numbers are pessimistic vs. live production — but the V3 vs. V2 *relative*
comparison is apples-to-apples.)

**Extrapolation:** each cell's CSV holds a sample. Daily PnL = `sum_pnl_sample × extrap_factor / span_days`.
Extrap factors: btc_5m=918, btc_15m=521, eth_5m=494, eth_15m=249, sol_5m=278, sol_15m=147.

---

## Per-cell results — V3 optimal (per-cell tuned)

```
cell      V2_daily    V3_daily   improvement   sigma_pct  cvd_pct   n_active(/sample)
btc_15m   -$3,868     -$402      +$3,466       0.10       0.95      113   ( 9%)
btc_5m    -$5,870     -$170      +$5,700       0.15       0.40      161   (13%)
eth_15m   -$1,719     +$93       +$1,812       0.15       0.30      129   (11%)
eth_5m    -$4,799     -$465      +$4,334       0.15       0.30      144   (12%)
sol_15m   -$1,204     +$30       +$1,234       0.15       0.40      133   (11%)
sol_5m    -$3,726     -$468      +$3,259       0.10       0.70      117   ( 9%)
---------------------------------------------------------------------
TOTAL     -$21,186    -$1,381    +$19,805      (93.5% improvement)
```

**Only 2 of 6 cells reach positive territory** (eth_15m, sol_15m) — and only by a few
dollars/day. The 4 BTC/ETH/SOL 5m cells all stay between -$170 and -$468/day.

**Active-fill ratios are extreme:** 9-13% of V2 samples survive both gates. After
extrapolation, real daily fill counts shrink by ~88%. This means a large portion of the
"improvement" is just by **not trading** when sigma is high.

---

## Per-cell best-fit n-counts (sample-size sanity)

```
cell      n_kept(sigma)  n_skipUP   n_skipDN   n_BOTH    n_sigmaDropped
btc_15m   125            1          1          123       1,117    ← CVD barely fires
btc_5m    190            16         26         148       1,077
eth_15m   182            25         57         100       1,031
eth_5m    186            32         65         89        1,054
sol_15m   183            40         23         120       1,037
sol_5m    131            5          3          123       1,177    ← CVD barely fires
```

**Warning — CVD-asymmetric rules barely fire in btc_15m and sol_5m best configs.** The
sigma filter is doing essentially all the work in those two cells. The "skip UP/skip DN"
count is in single digits.

In eth_5m and sol_15m the CVD rule fires more meaningfully (60-90 of ~180 kept), and
those are also the cells where the asymmetric posting picks up the most relative
improvement vs sigma-only.

---

## CVD-asymmetric stand-alone (no sigma filter) — DOES the CVD signal actually work?

Per-asset, on rows where `|cvd_slope_30s| > p50(asset)`, compare V2 baseline PnL vs.
V3-alt PnL (skipping the leg the CVD rule predicts will be adversely selected):

```
asset  n      V2 mean PnL    V3-alt mean PnL    Δ per fill
btc    631    -$0.093        -$0.076            +$0.017  (cvd > +p50)
btc    623    -$0.075        -$0.049            +$0.025  (cvd < -p50)
eth    491    -$0.133        -$0.111            +$0.022  (cvd > +p50)
eth    735    -$0.068        -$0.040            +$0.028  (cvd < -p50)
sol    647    -$0.146        -$0.071            +$0.076  (cvd > +p50)  ← strongest
sol    617    -$0.088        -$0.027            +$0.061  (cvd < -p50)
```

**The CVD asymmetric rule DOES improve PnL on the rows it fires on**, by +$0.02 to
+$0.08/fill — but mean PnL is still NEGATIVE on those rows, meaning CVD can't
distinguish "winners" from "smaller losers". SOL shows the strongest CVD edge
(consistent with SOL's higher volatility and stronger directional binance bias).

---

## Joint sweep (uniform percentile thresholds across all cells)

Total daily PnL — rows = sigma_pct (lower = drop more), cols = cvd_pct:

```
sigma\cvd     1.00      0.95      0.90      0.80      0.70      0.60      0.50
   1.00    -21,186   -21,587   -20,941   -21,023   -20,409   -18,475   -17,843
   0.90    -19,036   -18,662   -18,123   -17,916   -17,313   -15,325   -14,968
   0.80    -17,529   -17,167   -16,776   -17,560   -16,757   -14,601   -14,081
   0.67    -14,929   -14,763   -14,595   -14,998   -14,099   -11,770   -11,246
   0.50    -11,494   -11,541   -11,126   -12,103   -11,806   -10,222    -9,835
   0.33     -7,209    -7,158    -6,877    -7,518    -7,115    -6,109    -6,370
```

Plus extra-aggressive sigma cuts:

```
cvd_pct  sigma_pct=0.20  sigma_pct=0.10
   1.00    -$4,889         -$2,727
   0.50    -$4,354         -$2,608
   0.30    -$3,481         -$1,962  ← best uniform
```

**Best uniform: cvd_pct=0.30, sigma_pct=0.10 → -$1,962/day.** Effectively says "only
trade when both CVD is small AND sigma is in bottom 10%". This keeps ~10% of fills.

---

## V2 baseline calibration (for clarity)

Span: 15.05 days. The CSV is a sampled subset. After extrapolation:

```
cell      n_sample   sum_pnl_sample   extrap_factor   sum_pnl_extrap   daily_pnl
btc_15m   1,242      -$111.78         520.6           -$58,191         -$3,868
btc_5m    1,267      -$96.20          918.0           -$88,314         -$5,870
eth_15m   1,213      -$103.68         249.4           -$25,859         -$1,719
eth_5m    1,240      -$146.34         493.4           -$72,209         -$4,799
sol_15m   1,220      -$123.44         146.8           -$18,116         -$1,204
sol_5m    1,308      -$201.37         278.4           -$56,067         -$3,726
TOTAL                                                                  **-$21,186/day**
```

This total of -$21k/day (not -$45k/day) suggests the user's prior estimate may have
included additional cost lines (slippage, taker exits, exchange fees on holdings) that
the V2 `pnl_hold` policy does not capture, OR was over the V1-fee era. The relative
V3 vs V2 comparison here is internally consistent.

---

## Recommended V3 parameters & expected daily PnL

If the user wishes to deploy V3 paper-trading despite the negative expected return:

| Profile | Params | Total daily | Active fill % |
|---|---|---|---|
| **Aggressive cut** (recommended) | sigma_pct=0.10, cvd_pct=0.30 uniform | **-$1,962/day** | ~10% of V2 |
| Conservative cut | sigma_pct=0.33, cvd_pct=0.50 | -$6,370/day | ~50% |
| Per-cell overfit | varies (see table) | -$1,381/day | ~10% |

**Be aware:** per-cell tuned configs are overfit to the 15-day window and will likely
underperform on out-of-sample data. The "aggressive uniform" is more honest.

---

## If V3 still loses money — what's needed to flip positive?

The simulation makes clear V3 alone cannot flip mint-and-sell to positive. Plausible
next steps:

1. **Bid-side fade exit:** the V2 `pnl_hybrid` (market-exit when bid > 0.97 of ask) is
   essentially identical to `pnl_hold` here. A more aggressive market-exit at lower
   `exit_ratio` (e.g. 0.50) on the held leg should be tested — current sim assumes hold
   to resolution, which exposes us to 30-60s of volatility on the held leg.

2. **Selectivity by time-of-day:** the CVD signal is weakest BTC, strongest SOL. A
   per-asset gate combined with a UTC-hour filter (avoid 12-21 UTC = US hours, per
   CLAUDE.md F2 findings) may help.

3. **Capacity & queue position:** V2 assumes 100% fill rate on posted asks. Reality:
   queue priority matters. V3 dropping a leg means giving up rebate income on that leg's
   queue position. The true production fill rate is likely lower than what V2 reports,
   so V3's "skip" decision is less costly than the simulation suggests.

4. **Wider entry threshold:** V2 requires sum_asks ≥ 1.005 ($0.005 edge). Lifting to
   sum_asks ≥ 1.01 or 1.015 would cut volume but raise per-fill PnL. Sigma + entry
   threshold are complementary filters; both narrow the universe but in different
   directions.

5. **Confirm production fee model:** per CLAUDE.md, live production uses 2%-on-profit
   only on these crypto markets, NOT the 0.07·p·(1-p) curve V2 was backtested against.
   On the legacy fee model, V2 was reported as **+breakeven to slightly positive**
   slug-level (per MINT_AND_SELL_V2_FULL_REPLICATION_2026_05_16.md). The whole V3
   exercise may be solving the wrong problem if the live fee model is the legacy one.
   **Re-running V2+V3 under `engine_v2.LegacyConfig` (2%-on-profit) is the priority.**

6. **Investigate `pnl_hybrid` vs `pnl_hold`:** the two are within $0.01/fill of each
   other in this dataset, suggesting market-exit rarely triggers. May need to relax the
   exit threshold to gain real market-exit benefit.

---

## Sample-size warnings

- The CVD overlay is a 2000-row sample per cell (~12k total V2 fills sampled from 1.8M
  opportunities). Extrap factors of 147-918× amplify any sampling noise into daily
  $-figures.
- Per-cell best configs leave only **113-183 active fills** in the sample → real-world
  daily fill count after 9-13% gating is ~ daily_active × extrap_factor ≈ 100-300
  trades/day per cell. Statistically thin.
- The 15-day window straddles a known volatility regime change (Apr → early May). The
  CVD signal strength may not generalize.

---

## Deliverables

- `data/v4/canonical/_results/mint_and_sell_v3_simulation.csv` (240 rows: cell × cvd_pct
  × sigma_pct)
- `strategy_lab/markov_filter/_v3_simulate.py` — main V3 sim engine
- `strategy_lab/markov_filter/_v3_deeper.py` — ablation runs
- `strategy_lab/markov_filter/_v3_final.py` — per-cell best-fit + CVD-conditional sanity
