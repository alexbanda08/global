# Deploy sleeves — 28-day production-matched audit

_2026-05-22. Full 28d run (Apr 24 → May 21 20:10 UTC) of the 5 recommended
deploy candidates. Production-matched: ws_s F7 anchor (94.67% live match),
WS-only book reads, legacy 2%-on-profit fee (verified against 25,900
production resolutions)._

## The 5 sleeves

| Sleeve | Variant | Cell | Filter | Strategy idea |
|---|---|---|---|---|
| S1 | Baseline_v1 | btc_15m | M1V | Production v1 momo + Markov w20_1m_voladaptive |
| S2 | 2B_late_fire_early_signal | btc_15m | M1V | Same signal as v1, fire delayed to ws_s+780 (slot_start−120) |
| S3 | 2B_late_fire_early_signal | btc_15m | F7+M1V | S2 + F7 RSI agreement |
| S4 | 2C_edge_of_slot | btc_15m | F7+M5V | Fire AT slot_open, recent 2-min momentum + F7 + 5m-Markov |
| S5 | Baseline_v2 | eth_5m | F7+M5F | Production v2 + F7 + 5m-Markov fixed threshold |

## Per-sleeve 28d performance

### S1 — Baseline_v1 / btc_15m / M1V

```
n=92  wins=55  WR=59.78%  total=$+433.54  $/trade=+$4.71
pnl_std=$24.41  sharpe(approx)=1.85  max_dd=$-175.88
days_with_fire=20/28   max_win_streak=5   max_loss_streak=4
avg_per_day @ $25 notional:  +$15.48
avg_per_day @ $250:          +$154.83
avg_per_day @ $1000:         +$619.34
daily PnL: mean=+$21.68  std=$56.71  best=+$120.15  worst=-$97.37
```

**Best balanced bucket.** High n (92), high WR (59.8%), high per-trade ($4.71),
healthy Sharpe (1.85). Worst day −$97 vs best +$120, max drawdown −$176.

### S2 — 2B late/early / btc_15m / M1V

```
n=113  wins=64  WR=56.64%  total=$+463.83  $/trade=+$4.10
pnl_std=$25.56  sharpe(approx)=1.71  max_dd=$-200.50
days_with_fire=20/28   max_win_streak=7   max_loss_streak=7
avg_per_day @ $25 notional:  +$16.57
avg_per_day @ $250:          +$165.65
daily PnL: mean=+$23.19  std=$81.32  best=+$158.20  worst=-$175.00
```

**Highest n** of any deploy sleeve (113 fires). 7-loss streak in worst stretch.

### S3 — 2B late/early / btc_15m / F7+M1V

```
n=65  wins=38  WR=58.46%  total=$+368.58  $/trade=+$5.67
pnl_std=$25.93  sharpe(approx)=1.76  max_dd=$-243.16
days_with_fire=20/28   max_win_streak=6   max_loss_streak=8
avg_per_day @ $25:  +$13.16   @ $250:  +$131.64
```

Subset of S2 with F7 overlay. Higher per-trade but smaller n. **8-loss streak**
is concerning — F7+Markov stack is more concentrated → more variance.

### S4 — 2C edge-of-slot / btc_15m / F7+M5V

```
n=28  wins=16  WR=57.14%  total=$+152.04  $/trade=+$5.43
pnl_std=$26.49  sharpe(approx)=1.08  max_dd=$-174.25
days_with_fire=11/28   max_win_streak=6   max_loss_streak=5
avg_per_day @ $25:  +$5.43   @ $250:  +$54.30
```

**Pilot size.** Only 11/28 days with fires (sparse). High per-trade though —
fires only when 5m-Markov + F7 + sum_asks structure all align.

### S5 — Baseline_v2 / eth_5m / F7+M5F

```
n=68  wins=39  WR=57.35%  total=$+289.37  $/trade=+$4.26
pnl_std=$25.24  sharpe(approx)=1.39  max_dd=$-125.00
days_with_fire=16/28   max_win_streak=6   max_loss_streak=5
avg_per_day @ $25:  +$10.33   @ $250:  +$103.35
```

**First independent 5m profit pocket** I found. ETH 5m universe was universally
negative without Markov+F7 stack. With it: 57.35% WR, +$4.26/tr. Smallest
drawdown of the 5 sleeves (−$125).

## Ensemble overlap — sleeves don't double-fire much

```
pair      |A∩B|  |A∪B|  jaccard
S1+S2        50    155    0.323   ← moderate overlap (both BTC 15m M1V)
S1+S3        33    124    0.266
S1+S4         3    117    0.026   ← nearly disjoint
S1+S5         0    160    0.000   ← fully disjoint (diff asset)
S2+S3        65    113    0.575   ← S3 is mostly a subset of S2 (F7 filter)
S2+S4         3    138    0.022
S2+S5         0    181    0.000
S3+S4         3     90    0.033
S3+S5         0    133    0.000
S4+S5         0     96    0.000
```

**Key**: S5 (eth_5m) is fully orthogonal to all BTC 15m sleeves — pure
diversification. S1+S2 share 32% of slugs (both M1V on btc_15m) but S2 has 23
extra fires S1 doesn't. S3 is mostly a subset of S2 (F7 sub-filter).

## Ensemble combined daily PnL — 28-day trajectory

```
date         daily$    cum$
2026-04-26   -25.00     -25.00
2026-04-29   -15.05     -40.05
2026-04-30  +189.78    +149.73  ← first big day
2026-05-01  +170.19    +319.92
2026-05-02   -25.00    +294.92
2026-05-03   +21.81    +316.73
2026-05-04  +179.03    +495.76
2026-05-05  -251.79    +243.97  ← biggest loss day
2026-05-06   -71.37    +172.60
2026-05-07  +103.60    +276.20
2026-05-08  +208.17    +484.36
2026-05-09   +26.54    +510.90
2026-05-10  +318.25    +829.15  ← second-best day
2026-05-11   +25.92    +855.07
2026-05-12  +381.00   +1236.08  ← best day
2026-05-13   -62.52   +1173.56
2026-05-14  +144.59   +1318.15
2026-05-15  +179.32   +1497.47
2026-05-16   +48.50   +1545.97
2026-05-17   +55.26   +1601.22
2026-05-18  +236.47   +1837.69
2026-05-19   -51.00   +1786.69
2026-05-20  -276.46   +1510.23  ← second-worst day
2026-05-21  +197.12   +1707.35

24 days with ≥1 fire / 28 total. Positive days: 16/24, Negative days: 8/24.
```

**Total 28d ensemble PnL: +$1,707** at $25 notional × 5 sleeves.

## Projection (28-day base, daily-avg extrapolation)

| Notional × 5 sleeves | Daily avg | Monthly | Annual |
|---|---|---|---|
| **$25** | **+$63** | +$1,897 | +$23,081 |
| **$250** (10×) | **+$632** | +$18,971 | +$230,809 |
| **$1000** (40×) | **+$2,529** | +$75,882 | +$923,235 |

⚠ **Caveats on annualized projection**:
1. 28-day backtest = small sample. May 2026 was a particular regime; June could
   be different.
2. The $/trade edge thins as you scale notional (book depth fills slower).
   Expect 80% of linear scaling up to $250, 50-60% at $1000.
3. Drawdown scales linearly with notional. At $1000 × 5 sleeves, the −$276 worst
   day becomes **−$11,040**. Position-size accordingly.

## Risk metrics (per sleeve, at $25 notional)

| Sleeve | Max DD | Max Loss Streak | Daily Worst | Sharpe (approx) |
|---|---|---|---|---|
| S1 | -$176 | 4 | -$97 | 1.85 |
| S2 | -$201 | 7 | -$175 | 1.71 |
| S3 | -$243 | 8 | -$100 | 1.76 |
| S4 | -$174 | 5 | -$50 | 1.08 |
| S5 | -$125 | 5 | -$25 | 1.39 |

S3 has the worst drawdown profile (8-loss streak, -$243 max DD). S5 is the
gentlest — small per-day loss potential.

## Recommended deploy ladder

**Phase 1 (paper / micro live, week 1-2)**: deploy S1 alone at $25 notional.
Validate live PnL matches backtest within ±25% over 50+ fires. Expected
~3 fires/day × $4.71 = ~+$14/day baseline.

**Phase 2 (live ramp, week 3-4)**: scale S1 to $100, add S5 at $25. Verify
S5 independent profit pocket holds out-of-sample. Expected ~+$60-80/day combined.

**Phase 3 (full ensemble, week 5+)**: add S2 (overlapping with S1), S3, S4.
Run S1+S2 in parallel at same notional only if backtest correlation analysis
shows the union still has Sharpe > 1.5 (the 32% slug overlap should be tested
for sign-correlation, not just slug overlap). Target: +$300-600/day at $250
notional.

**Halt conditions**:
- Any sleeve's live 7-day PnL < −2x backtest's worst-7d
- Aggregate Sharpe drops below 0.8 over 30+ live days
- Production fee model changes (verify against shadow PnL monthly)

## Files

- Runner: `strategy_lab/meta_classifier/deploy_sleeves_28d_audit.py`
- Per-sleeve CSV: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/deploy_sleeves_28d_audit.csv`
- Per-trade source: `data/v4/canonical/_results/momo_variants_2abc_2026_05_20/per_trade_markov.parquet`
- Prior reports:
  - F7+Markov synthesis: `MOMO_VARIANTS_F7_MARKOV_STACK_2026_05_22.md`
  - Production code review: `MOMO_VARIANTS_PROD_MATCHED_2026_05_21.md`
  - 28d sub-second: `MOMO_VARIANTS_28D_SUBSEC_2026_05_21.md`
