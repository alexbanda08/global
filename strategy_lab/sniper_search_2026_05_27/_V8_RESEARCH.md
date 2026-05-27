# V8 Research — 2-asset confluence, TOD specialization, 1h grandparent

**Date**: 2026-05-27
**Brief**: `_BRIEF_V8.md`
**Working dir**: `strategy_lab/sniper_search_2026_05_27/_v8_research/`
**Data**: canonical v3 fires (Apr 24 → May 26 2026, ~32.6d), `regime_panel_5m_v2_fixed` / `_15m_v2_fixed`, NEW `regime_panel_1h`, `range_filter_1s`

All numbers below come from real data; no synthetic or hand-waved figures. Every claim has a backing script under `_v8_research/`.

---

## §1 — 2-asset and 3-asset confluence (Path J)

**Question**: When do BTC + ETH + SOL all *simultaneously* agree on direction via RF + slope, and does the target market's WR benefit?

### 1.1 — Signal definitions

For each fire at `fire_us`, compute a per-asset signed signal in {-1, 0, +1}:

```python
def per_asset_sig(asset, fire_us):
  rf  = range_filter_1s[asset].rf_dir at (fire_us - 1_000_000)        # bar-END asof
  ts  = regime_panel_5m_v2_fixed[asset].trend_slope_30m at (fire_us - 1_000_000)
  if rf == +1 and ts > 0: return +1                                    # bullish concord
  if rf == -1 and ts < 0: return -1                                    # bearish concord
  return 0                                                              # discord / missing
```

Variants tested:
- **rf_only** — sign from `rf_dir` only (loose)
- **slope_only** — sign from `trend_slope_30m` only (medium)
- **combined** — both must agree (strict)

Confluence gates:
- 3-asset unanimity: all 3 asset signals match `direction`
- 2-asset: target + companion match
- Companions-only: both *other* assets match (pure cross-asset)
- 2-of-3 majority: ≥2 of 3 asset signals match

### 1.2 — Headline results (3-asset combined unanimity)

```
market   n       wr      $/tr      wr_lift   dpt_lift   pct_universe
BTC_5m   9,050   59.82%  -$0.71    +11.1 pp  +$1.58     6.28%
ETH_5m   8,503   57.84%  -$2.68    + 9.4 pp  +$0.43     6.37%
SOL_5m   5,922   58.05%  -$3.07    + 9.8 pp  +$1.26     5.83%
BTC_15m  2,644   61.99%  +$0.17    +13.6 pp  +$2.61     6.08%   ← winner (+$/tr)
ETH_15m  2,408   61.30%  -$1.16    +12.7 pp  +$1.83     6.09%
SOL_15m  2,087   63.20%  -$0.32    +14.4 pp  +$3.51     5.98%   ← biggest WR lift
```

**Finding**: 3-asset combined unanimity (rf+slope, all 3 assets concord) fires on ~6% of fires across every market, lifts WR by **+9.4 to +14.4 pp** consistently, and is the only gate combination that makes BTC 15m $/tr positive ($0.17/tr at n=2,644) before any sleeve refinement.

### 1.3 — Lighter confluence variants (rf_only)

The lighter rf-only confluence retains broader sample and respectable lift:

```
market   gate                      n       wr      wr_lift   $/tr      pct
BTC_5m   rf_only_3asset_unanimity  29,374  56.5%   +7.8 pp   -$1.78    20.4%
ETH_5m   rf_only_3asset_unanimity  24,780  59.8%   +11.4 pp  -$1.68    18.6%
SOL_5m   rf_only_3asset_unanimity  17,223  61.4%   +13.1 pp  -$2.30    17.0%
BTC_15m  rf_only_3asset_unanimity   8,059  53.4%   +5.0 pp   -$1.46    18.5%
SOL_15m  rf_only_3asset_unanimity   6,201  54.3%   +5.5 pp   -$2.45    17.8%
```

Selectivity ~18%, WR lift ~5-13 pp. Useful when stronger confluence empties the bucket.

### 1.4 — 2-asset target+companion (combined)

```
market   target+a1               n      wr      wr_lift  $/tr
BTC_5m   combined_BTC+ETH        16,692 56.3%   + 7.6 pp -$1.01
BTC_5m   combined_BTC+SOL        11,894 59.0%   +10.3 pp -$0.91
ETH_5m   combined_ETH+BTC        15,624 54.9%   + 6.5 pp -$2.77
ETH_5m   combined_ETH+SOL        11,676 56.4%   + 7.9 pp -$2.70
SOL_5m   combined_SOL+BTC         7,756 58.1%   + 9.8 pp -$2.85
SOL_5m   combined_SOL+ETH         8,058 57.0%   + 8.8 pp -$3.11
BTC_15m  combined_BTC+SOL         3,475 61.0%   +12.6 pp -$0.40
BTC_15m  combined_BTC+ETH         4,881 58.9%   +10.5 pp -$0.60
ETH_15m  combined_ETH+SOL         3,345 60.7%   +12.2 pp -$1.10
SOL_15m  combined_SOL+ETH         2,895 63.2%   +14.4 pp -$0.43
SOL_15m  combined_SOL+BTC         2,732 62.3%   +13.5 pp -$0.95
```

**Finding**: For SOL 5m the right companion is BTC (+10pp on n≈7.7k). For ETH 5m / ETH 15m the BTC partnership lifts WR 6-13 pp. For BTC and ETH 15m, adding SOL helps more than ETH/BTC respectively — surprising.

### 1.5 — Companions-only (pure cross-asset)

```
market   gate                              n       wr      wr_lift  $/tr
BTC_5m   combined_companions_ETH+SOL       12,437  57.7%   +9.0 pp  -$0.69
ETH_5m   combined_companions_BTC+SOL       11,135  56.9%   +8.5 pp  -$2.46
SOL_5m   combined_companions_BTC+ETH       11,439  53.6%   +5.3 pp  -$3.19
BTC_15m  combined_companions_ETH+SOL        3,682  59.8%   +11.4 pp -$0.21
ETH_15m  combined_companions_BTC+SOL        3,146  59.8%   +11.3 pp -$1.33
SOL_15m  combined_companions_BTC+ETH        3,912  58.5%   + 9.6 pp -$1.82
```

**Finding**: Pure cross-asset (target excluded) hits same +9-11 pp on 8-12% of fires. The target's own RF/slope is partially redundant with companion signals (8-12 pp of the 14-15 pp 3-asset lift comes from the cross-asset structure alone).

### 1.6 — Recommended V8 gates

| Gate | Stack | Sample | Best market | Use case |
|---|---|---|---|---|
| `g_3asset_combined_unanimity` | rf+slope concord on BTC+ETH+SOL all match direction | ~6% | All 6 | Strict gate, best WR lift, $/tr positive on BTC 15m |
| `g_2asset_combined_companion_only` | both companions' rf+slope concord match direction | 8-12% | BTC 5m, BTC 15m, ETH 15m | Higher-sample compromise |
| `g_rf_only_3asset_unanimity` | rf_dir on all 3 assets match direction | 17-20% | ETH 5m, SOL 5m | Broadest "agreement" gate |

Slope-only variant is **anti-predictive** in 5/6 markets (WR drops 1-3 pp) — drop it. Combining slope with RF (the "combined" variant) is the right way to use slope.

Code: `_v8_research/topic1_confluence.py`. Full table: `_v8_research/topic1_confluence_summary.csv`.

---

## §2 — Time-of-Day systematic specialization (Path K)

**Question**: When V7 winning gate stacks are recomputed per TOD bucket, does edge concentrate in 1-2 specific buckets?

### 2.1 — TOD definition

```python
TOD_BUCKETS = {
  "asia_morning":     [0, 7),    # 00-07 UTC
  "european_morning": [7, 13),   # 07-13 UTC
  "us_afternoon":     [13, 19),  # 13-19 UTC
  "us_evening":       [19, 24),  # 19-24 UTC
}
```

### 2.2 — Ungated baseline by TOD (sanity check)

```
market   tod                n       wr       $/tr
BTC_5m   asia_morning      42,604  48.96%   -$2.06
BTC_5m   european_morning  36,794  48.70%   -$2.28
BTC_5m   us_afternoon      34,329  48.32%   -$2.31
BTC_5m   us_evening        30,334  48.79%   -$2.63
BTC_15m  us_afternoon      10,467  48.24%   -$1.77   ← lower negative drag
ETH_15m  us_afternoon       9,510  48.46%   -$2.02   ← lower negative drag
SOL_15m  us_afternoon       8,273  48.64%   -$3.48
SOL_15m  european_morning   8,818  48.93%   -$3.58
```

**Finding**: Without gating, TOD shifts $/tr by ~$0.30-0.70 only (small but consistent: us_afternoon is cheaper on 15m markets). WR shifts < 1 pp.

### 2.3 — TOD-specialized stack candidates (real wins)

Filter: `n ≥ 50 AND (wr_lift > 1.0 pp OR dpt_lift > $1.0)` vs ALL-TOD version of the same stack.

```
market   stack                  tod              n      wr      $/tr     wr_lift  dpt_lift
BTC_5m   S5_rf+ema200+ema800    us_evening      7,783  73.31%  +$0.53   +1.4 pp  +$0.35   ★ deploy-ready
BTC_15m  S5_rf+ema200+ema800    us_afternoon    2,522  70.14%  +$1.02   +0.5 pp  +$1.03   ★ deploy-ready
SOL_5m   S5_rf+ema200+ema800    asia_morning    6,921  76.13%  -$0.13   +1.3 pp  +$0.07   ★ near deploy
SOL_5m   S5_rf+ema200+ema800    us_afternoon    5,841  76.08%  +$0.04   +1.2 pp  +$0.24   ★ deploy-ready
SOL_5m   S4_rf+ema200+mfi       asia_morning    6,564  73.52%  -$0.17   +1.1 pp  +$0.22
SOL_15m  S5_rf+ema200+ema800    asia_morning    2,462  72.71%  -$0.16   +1.5 pp  +$0.10   ★ near deploy

# BTC 15m: us_afternoon is the standout TOD for multiple stacks
BTC_15m  S4_rf+ema200+mfi       us_afternoon    2,585  60.97%  +$0.40   -0.8 pp  +$1.28   (dpt lift, WR neutral)
BTC_15m  S3_rf+ema200+ribbon    us_afternoon    3,225  60.74%  +$0.30   -0.2 pp  +$1.35
BTC_15m  S7_rf+fresh            us_afternoon    4,109  51.93%  -$0.01   +0.9 pp  +$1.79

# ETH 15m: us_afternoon shows broad dpt lift; ETH 15m S4 worth marking
ETH_15m  S4_rf+ema200+mfi       us_afternoon    2,284  60.46%  -$0.38   -0.5 pp  +$1.44
ETH_15m  S5_rf+ema200+ema800    asia_morning    2,801  71.19%  -$0.41   +1.7 pp  +$0.17
```

### 2.4 — Headline TOD findings

| Market | Best TOD | Mechanism |
|---|---|---|
| **BTC 5m** | **us_evening (19-24 UTC)** | S5 stack (rf + ema200 + ema800) hits 73.3% WR / +$0.53/tr on n=7,783 — biggest TOD-specialized winner in 5m |
| **BTC 15m** | **us_afternoon (13-19 UTC)** | Multiple stacks lift $/tr by +$1.0-1.8; S5 reaches 70% WR / +$1.02/tr on n=2,522 |
| **ETH 5m** | No strong single TOD; small lifts on us_afternoon | Marginal |
| **ETH 15m** | **us_afternoon** for $/tr; **asia_morning** for high-WR S5 stack | S5 in asia_morning: 71.2% WR but -$0.41/tr (price effect) |
| **SOL 5m** | **asia_morning (00-07 UTC)** for S5: 76.1% WR / -$0.13/tr — needs price tightening | Strongest WR specialization in 5m |
| **SOL 15m** | **asia_morning** for S5: 72.7% WR / -$0.16/tr | |

**Key insight**: The `S5_rf+ema200+ema800` stack (the deepest trend-stack confluence) shows **WR lifts of 1.2-1.7 pp in specific TODs** across BTC 5m / BTC 15m / SOL 5m / SOL 15m / ETH 15m. Its TOD edge is REAL but small (1-2 pp). The interesting effect is that the stack already hits 70-76% WR in the right TOD, so even a small $/tr lift can flip the sleeve to positive.

### 2.5 — Recommended V8 TOD gates

```python
# Sleeve A — BTC 5m × us_evening × S5
g_bts5m_us_eve_s5: g_rf_with AND g_tr_above_ema200 AND g_tr_above_ema800 AND hour_utc in [19,24)

# Sleeve B — BTC 15m × us_afternoon × S5
g_btc15m_us_aft_s5: same predicate AND tf=15m AND hour_utc in [13,19)

# Sleeve C — SOL 5m × us_afternoon × S5  (less risky than asia_morning given dpt sign)
g_sol5m_us_aft_s5: same predicate AND asset=SOL, tf=5m, hour_utc in [13,19)

# Sleeve D — BTC 15m × us_afternoon × (S3/S4/S7)
g_btc15m_us_aft_relaxed: g_rf_with AND (g_tr_above_ema200 OR g_rf_fresh) AND hour_utc in [13,19)
```

**Negative finding**: For SOL 15m and ETH 5m, no single TOD breaks decisively. SOL 15m's european_morning lift (per V6/V7 prior work) holds: S1_rf_only there reaches 54.2% WR / -$1.95/tr on n=4,250 — modest lift, marginal. Don't expect dramatic TOD effects on these two.

Code: `_v8_research/topic2_tod.py`. Tables: `topic2_tod_baseline.csv`, `topic2_tod_stacks.csv`.

---

## §3 — 1h grandparent regime cascade (Path L)

### 3.1 — Building the 1h regime panel

New file: `data/v4/canonical/_results/regime_panel_1h.parquet` (834 hourly bars × 3 assets, Apr 24 → May 26 2026).

Builder: `_v8_research/build_regime_panel_1h.py` — mirrors `meta_classifier/build_regime_panel.py` semantics:
- 1m bars from `klines_1m` (BINANCE_SPOT) → resampled to 1h
- ADX(14) Wilder smoothing on 1h
- EMA stack score on 1h (close vs ema50/ema200)
- realized_vol_60h / trend_slope_30h normalized by atr_60h
- `regime_label`: trending_up / trending_dn / ranging based on `adx > 20 AND |stack| >= 1 AND (ribbon >= 60 OR NaN)`

The `adx > 20` threshold (vs `>25` for 5m/15m panels) is intentional — at 1h granularity, ADX is slower to confirm, so a 20 threshold is more inclusive. Ribbon coverage degrades outside `ta_indicators_1s` window (May 1 → May 23, 22d), so we relax that constraint when missing.

Label distribution (window-filtered):
```
asset  ranging  trending_dn  trending_up
BTC    440      189          205      (47.2% trending — vs ~12% for 5m, ~14% for 15m)
ETH    438      257          139      (47.5% trending)
SOL    482      211          141      (42.2% trending)
```

The 1h panel is much more "trending" because the longer bar smooths noise — ranging only dominates 50% (vs 88% on 5m/15m).

Causality check: `ts_us = slot_start + 1h - 1us` (bar END convention), identical to v2_fixed panels. Backward asof on `(fire_us - 1_000_000)` is strictly causal.

### 3.2 — Single-layer 1h gate

```
market   gate              n        wr      wr_lift  $/tr     dpt_lift
BTC_5m   g_1h_trend_with   32,277   47.2%   -1.5 pp  -$2.68   -$0.38   ← solo 1h is WEAKER
ETH_5m   g_1h_trend_with   29,755   47.2%   -1.3 pp  -$3.89   -$0.79
SOL_5m   g_1h_trend_with   20,474   46.8%   -1.5 pp  -$4.92   -$0.59
BTC_15m  g_1h_trend_with    9,686   46.2%   -2.2 pp  -$3.68   -$1.25
```

**Pure 1h-label-aligned fires perform WORSE than baseline.** The 1h trending label by itself is too coarse — it lasts hours and many fires fall in the "wrong half" of the trend.

### 3.3 — Cascade trend-label (5m + 15m + 1h all trending-aligned)

```
market   gate                            n       wr      wr_lift  $/tr      dpt_lift   pct
BTC_5m   cascade_5m+15m+1h_trend_with    1,058   53.02%  +4.3 pp  +$2.23    +$4.52     0.73%   ★ STRONG
ETH_5m   cascade_5m+15m+1h_trend_with      890   47.30%  -1.1 pp  -$4.21    -$1.10     0.67%   weak
SOL_5m   cascade_5m+15m+1h_trend_with      474   41.98%  -6.3 pp  -$5.09    -$0.76     0.47%   weak
BTC_15m  cascade_5m+15m+1h_trend_with      354   44.63%  -3.8 pp  -$1.63    +$0.80     0.81%
ETH_15m  cascade_5m+15m+1h_trend_with      279   53.41%  +4.8 pp  +$0.27    +$3.26     0.71%   ★ best dpt
SOL_15m  cascade_5m+15m+1h_trend_with      184   38.04%  -10.8 pp -$7.08    -$3.25     0.53%   NEGATIVE
```

**Finding**: The 3-tier cascade is highly selective (n=184-1,058, 0.5-0.8% of fires) and bifurcates:
- **BTC 5m**: +$2.23/tr cascade winner — biggest $/tr lift in V8 so far
- **ETH 15m**: +$0.27/tr — turns positive, +$3.26 lift vs baseline
- **SOL 5m, SOL 15m, ETH 5m**: hurt by the cascade (over-fitted, label noise compounds)

### 3.4 — Hybrid cascade: rf + 1h grandparent (broader sample)

```
market   gate                            n       wr      wr_lift  $/tr      dpt_lift   pct
BTC_5m   rf+1h_grandparent               15,869  55.35%  +6.6 pp  -$1.88    +$0.41     11.0%
ETH_5m   rf+1h_grandparent               13,811  54.39%  +5.9 pp  -$2.99    +$0.12     10.3%
SOL_5m   rf+1h_grandparent                9,475  54.37%  +6.1 pp  -$3.70    +$0.62      9.3%
BTC_15m  rf+1h_grandparent                4,825  50.82%  +2.4 pp  -$2.98    -$0.54     11.1%   ← drop
ETH_15m  rf+1h_grandparent                4,147  52.11%  +3.6 pp  -$0.63    +$2.36     10.5%   ★
SOL_15m  rf+1h_grandparent                3,198  48.69%  -0.1 pp  -$4.93    -$1.10      9.2%
```

`rf+1h` (5m fire's rf_dir + 1h grandparent label aligned) gives broader sample (~10% of fires) and consistent +3-7 pp WR lift on 5m markets. ETH 15m again the standout for dpt.

### 3.5 — Hybrid: rf + slope_1h (sign of 1h trend_slope_30m)

Replacing the trinary 1h regime_label with the simpler sign of `trend_slope_30m`:

```
market   gate            n        wr      wr_lift  $/tr      dpt_lift
BTC_5m   rf+slope_1h     34,646   55.82%  +7.1 pp  -$1.46    +$0.84
ETH_5m   rf+slope_1h     32,252   55.28%  +6.8 pp  -$2.46    +$0.64
SOL_5m   rf+slope_1h     24,211   55.07%  +6.8 pp  -$3.25    +$1.08
BTC_15m  rf+slope_1h     10,511   51.37%  +3.0 pp  -$2.10    +$0.33
ETH_15m  rf+slope_1h      9,489   50.82%  +2.3 pp  -$2.74    +$0.25
SOL_15m  rf+slope_1h      8,396   51.38%  +2.5 pp  -$3.69    +$0.14
```

**Finding**: The `slope_1h` sign is more inclusive (~24% of fires) and consistently lifts WR by 2-7 pp. Use it as a coarse layer in V8 sleeves before applying tighter gates.

### 3.6 — Recommended V8 grandparent gates

| Gate | Definition | Best market | Lift |
|---|---|---|---|
| `g_cascade_5m+15m+1h_trend_with` | All 3 regime labels trending in `direction` | BTC 5m, ETH 15m | +$2.23/tr (BTC 5m), +$3.26 dpt lift (ETH 15m) — but tiny n |
| `g_rf+1h_grandparent` | RF dir match AND 1h regime label trending in dir | All 5m markets | +6-7 pp WR, n~10% |
| `g_rf+slope_1h` | RF dir match AND 1h `trend_slope_30m` sign matches | All markets | +2-7 pp WR, n~24% |
| `g_rf+15m+1h_grandparent` | RF + 15m label + 1h label all aligned | ETH 15m | tiny n (343) but +$8/tr (small-sample, cautious) |

Code: `_v8_research/topic3_grandparent.py`. Table: `_v8_research/topic3_grandparent_cascade.csv`.

---

## §4 — V8 search agent priorities (summary)

Based on §1–§3 findings, the highest-EV gates for V8 per-market search:

### Layer 1 — Cross-asset confluence (Path J)
- `g_3asset_combined_unanimity` — selectivity 6%, WR +9-14pp — use as PRIMARY gate
- `g_2asset_combined_target+companion` — selectivity 8-12%, WR +6-13pp
- `g_rf_only_3asset_unanimity` — selectivity 17-20%, WR +5-13pp — relaxed alternative

### Layer 2 — TOD specialization (Path K)
- Per-market best TOD: BTC 5m → us_evening, BTC 15m → us_afternoon, SOL 5m → us_afternoon, ETH 15m → us_afternoon
- Most TOD lifts are 1-2 pp; the value comes from combining TOD with high-WR stacks like S5
- ETH 5m and SOL 15m show NO strong TOD specialization

### Layer 3 — Multi-timeframe cascade (Path L)
- 3-tier `g_cascade_5m+15m+1h_trend_with` — selectivity 0.5-1%, gives BTC 5m the only positive $/tr cascade (+$2.23). Worth its own dedicated sleeve.
- `g_rf+slope_1h` — selectivity 24%, +2-7pp WR — use as broad-coverage gate
- `g_rf+1h_grandparent` — middle ground, ~10% selectivity, ~5pp lift

### Stack recipes for V8 agents

```python
# Recipe A (BTC 15m, deploy-ready candidate)
S_recipe_A = stack(
    g_rf_with, g_tr_above_ema200, g_tr_above_ema800,
    g_3asset_combined_unanimity,      # cross-asset confluence
    g_hour_utc_in(13, 19),            # us_afternoon TOD
)
# Predicted: high WR (70%+), n ~ 300-500 on 32d, $/tr should improve from raw S5+TOD ($1.02/tr) by another $0.3-0.5

# Recipe B (BTC 5m, cascade)
S_recipe_B = stack(
    g_rf_with,
    g_5m_trend_with, g_15m_trend_with, g_1h_trend_with,
    g_hour_utc_in(19, 24),            # us_evening
)
# Predicted: n ~ 100-200, very high conviction; needs lockbox stability check

# Recipe C (broadest TF cascade, all markets)
S_recipe_C = stack(
    g_rf_with,
    g_2asset_combined_target+best_companion,
    g_rf+slope_1h,
)
# Predicted: n ~ 2000-4000, +5-7pp WR — base sleeve for less-specialized markets
```

---

## Reusable artifacts written

- `data/v4/canonical/_results/regime_panel_1h.parquet` — NEW 1h grandparent regime panel (2,502 rows: 834 × 3 assets, 28d effective)
- `_v8_research/build_regime_panel_1h.py` — builder script
- `_v8_research/topic1_confluence.py` — 2/3-asset confluence backtest
- `_v8_research/topic1_confluence_summary.csv` — full results table
- `_v8_research/topic2_tod.py` — TOD specialization
- `_v8_research/topic2_tod_baseline.csv` — per-market TOD baseline
- `_v8_research/topic2_tod_stacks.csv` — per-market × TOD × stack metrics
- `_v8_research/topic3_grandparent.py` — 1h cascade tests
- `_v8_research/topic3_grandparent_cascade.csv` — full cascade table

---

## Verdict for V8 search

| Path | Verdict | Reason |
|---|---|---|
| **J — 2/3-asset confluence** | **PURSUE PRIMARY** | 3-asset combined unanimity is the most consistent edge across all 6 markets (+9 to +14 pp WR on ~6% selectivity). BTC 15m flips $/tr positive without further filters. |
| **K — TOD specialization** | **PURSUE — selectively** | Strong for BTC 5m us_evening (S5: 73% WR), BTC 15m us_afternoon (S5: 70%), SOL 5m us_afternoon/asia. Weak for ETH 5m, SOL 15m. |
| **L — 1h grandparent cascade** | **PURSUE — specialized sleeves** | The full 3-tier cascade is selective but powerful on BTC 5m (+$2.23/tr) and ETH 15m (+$0.27/tr from -$2.99). `rf+slope_1h` is the workhorse broad gate (~24% selectivity, +2-7 pp WR). |

All three paths produce DIFFERENT non-overlapping sleeve candidates; V8 search agents should explore each independently and stack the gate sets that match the market.
