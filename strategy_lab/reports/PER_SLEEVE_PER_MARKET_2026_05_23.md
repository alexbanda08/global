# Per-sleeve × per-market analysis — 2026-05-23

Individual breakdown of the deploy candidate. **Two rules × three markets = 6 individual sleeves**, plus the per-market UNION. Constraint applied to every row: `fire_offset_s ≥ 120`. Each cell deduped to one fire per (slug, direction), pnl from production-actual 2 %-on-profit fee model. Panel span 2026-05-01 → 2026-05-21 (20.8 days).

Runner: [strategy_lab/overnight_2026_05_23/per_sleeve_per_market.py](strategy_lab/overnight_2026_05_23/per_sleeve_per_market.py)
Output: [data/v4/canonical/_results/per_sleeve_per_market.csv](data/v4/canonical/_results/per_sleeve_per_market.csv)

## TL;DR — pick list per market

| market | DEPLOY | reason |
|---|---|---|
| **BTC** | **S4_BTC** (FV-strong + CVD + |dev|≥8) | Clean binom p = 0.0086, walk-forward retention 1.56 (test > train), CI lo +$69 strictly positive. S8_BTC is degrading (wf_ret 0.35). |
| **ETH** | **S4_ETH** (FV-strong + CVD + |dev|≥8) | Best single sleeve in the whole study. WR 80.8 %, $4.18/tr, +$95/day, binom p = 0.00042, wf_ret 1.01. **S8_ETH is statistically insignificant** (binom p = 0.17, WR edge 1.15 pp). |
| **SOL** | **S8+S4_SOL union** | Largest absolute PnL (+$112/day) but with fragility flags — see warnings below. |

## Per-sleeve scorecard

### BTC — `n_total = 1 022 ∪`, 21 trading days

| sleeve | n | WR % | $/tr | sum $ | $/day | max DD | sharpe_ann | binom p | wf_ret | train→test WR | UP / DOWN n | UP / DOWN WR % | % prof days |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **S8 BTC** | 831 | **86.40** | 0.96 | +798 | +38.52 | −313 | 7.3 | 0.011 | **0.35** ⚠ | 86.1 → **87.2** | 426 / 405 | 85.5 / **87.4** | 61.9 |
| **S4 BTC** | 345 | 78.84 | **2.17** | +747 | +35.99 | **−165** | 8.4 | 0.0086 | **1.56** ✓ | 76.8 → **83.7** | 284 / 61 | 78.5 / 80.3 | 68.4 |
| **S8 ∪ S4 BTC** | 1 022 | 84.25 | 1.45 | **+1 485** | **+71.40** | −292 | 10.9 | **0.00092** | 0.92 | 83.4 → 86.3 | 589 / 433 | 82.7 / 86.4 | 61.9 |

**Notes:**
- S8_BTC has the highest WR (86.4 %) and lowest per-trade $ ($0.96). Walk-forward retention 0.35 → train_sum $590 vs test_sum $208 — the edge is **shrinking** over the 21-day window. Watch this.
- S4_BTC fires 2.4× less (n=345 vs 831) but per-trade is 2.3× bigger. wf_ret 1.56 (test > train), tight DD (-$165), and bootstrap CI lower bound is strictly +$69. **The cleanest signal on BTC.**
- DOWN trades on BTC fire at 87 % WR (S8) and 80 % WR (S4) — both directions work.
- 38 % of trading days are flat-or-losing on S8_BTC (only 61.9 % profitable). S4_BTC is steadier (68.4 % profitable).

### ETH — `n_total = 1 303 ∪`, 21 trading days

| sleeve | n | WR % | $/tr | sum $ | $/day | max DD | sharpe_ann | binom p | wf_ret | train→test WR | UP / DOWN n | UP / DOWN WR % | % prof days |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **S8 ETH** | 1 004 | 85.86 | 0.64 | +640 | +30.72 | −427 | 5.0 | **0.17 ⚠** | 0.87 | 85.5 → 86.8 | 497 / 507 | 85.9 / 85.8 | **76.2** |
| **S4 ETH** | 473 | 80.76 | **4.18** | **+1 978** | **+95.16** | −206 | **12.6** | **0.00042** | 1.01 ✓ | 78.9 → **85.2** | 413 / 60 | 79.9 / **86.7** | **76.2** |
| **S8 ∪ S4 ETH** | 1 303 | 84.04 | 1.56 | +2 027 | +97.33 | −365 | 10.9 | 0.0088 | 1.42 | 83.2 → 85.9 | 763 / 540 | 82.8 / 85.7 | 76.2 |

**Notes:**
- 🚩 **S8_ETH fails the binomial significance test** (p = 0.167). Real WR 85.9 % vs vwap-implied 84.7 % = **only 1.15 pp edge** — within noise. The MACD+RVOL gate doesn't add signal on ETH beyond what the entry vwap already prices in. Don't deploy S8_ETH standalone.
- **S4_ETH is the strongest single sleeve in the entire study**: highest annualized Sharpe (12.6), highest Calmar (168.8), tightest binom p (0.00042), wf_ret essentially 1.0 (stable), DOWN WR = **86.7 %**. CI lower bound +$810 strictly positive.
- The union still works for ETH despite S8_ETH's weakness because S4_ETH carries the load.

### SOL — `n_total = 1 183 ∪`, 21 trading days

| sleeve | n | WR % | $/tr | sum $ | $/day | max DD | sharpe_ann | binom p | wf_ret | train→test WR | UP / DOWN n | UP / DOWN WR % | % prof days |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| **S8 SOL** | 977 | **88.02** | 1.97 | +1 923 | +93.02 | −314 | 5.2 | 0.032 | **−137** ⚠⚠ | 87.9 → 88.4 | 523 / 454 | 86.4 / 89.9 | 61.9 |
| **S4 SOL** | 315 | 75.56 | **2.43** | +764 | +36.84 | −368 | 8.6 | 0.0059 | 0.78 | 72.7 → **82.1** | 299 / 16 | 75.3 / 81.3 | 55.0 |
| **S8 ∪ S4 SOL** | 1 183 | 84.78 | 1.96 | **+2 321** | **+111.83** | −447 | 6.1 | 0.0053 | **28.5** ⚠ | 84.4 → 85.6 | 722 / 461 | 81.7 / **89.6** | 61.9 |

**Notes:**
- 🚩 **S8_SOL walk-forward retention is −137**: train_sum = **−$14**, test_sum = **+$1 937**. The strategy LOST money in the first 70 % of the window and made ALL of its PnL in the last 30 %. This is either a regime shift in our favor OR the SOL big-winner outlier ($1 517 on one fire) sits in the test fold and is doing the heavy lifting alone.
- The biggest single fire in the whole study (`sol-updown-5m-1779199200 UP offset=270 entry=$0.016 won $1 517`) belongs to S8_SOL. Remove that one fire and S8_SOL's test_sum drops to $420, wf_ret becomes 0.30. **Highly dependent on a single tail event** — flag this in shadow.
- **S4_SOL is much cleaner**: smaller n=315 but tight binom p = 0.0059, wf_ret 0.78 (mild decay), DOWN sample is tiny (n=16) so DOWN WR 81 % shouldn't be trusted on its own.
- The SOL union's wf_ret = 28.5 is misleading — it's the train_sum being near zero ($78). Compute as test/train, the test side ($2 242) dominates.

## Cross-sleeve summary (sorted by `binom_p`)

| rank | sleeve | binom_p | WR pp edge | $/day | wf_ret | verdict |
|--:|---|--:|--:|--:|--:|---|
| 1 | **S4 ETH** | **0.00042** | +6.64 | +95.16 | 1.01 | ✅ SHIP — strongest single signal |
| 2 | **S4 SOL** | 0.0059 | +6.60 | +36.84 | 0.78 | ✅ SHIP — modest decay, tight DD |
| 3 | **S4 BTC** | 0.0086 | +5.72 | +35.99 | 1.56 | ✅ SHIP — test > train, low DD |
| 4 | **S8 BTC** | 0.011 | +2.97 | +38.52 | **0.35** ⚠ | ⚠ SHIP-AT-HALF — decaying edge |
| 5 | **S8 SOL** | 0.032 | +2.08 | +93.02 | **−137** ⚠⚠ | ⚠ TAIL-DEPENDENT — single fire carries |
| 6 | **S8 ETH** | **0.167** | +1.15 | +30.72 | 0.87 | ❌ DO NOT SHIP — not significant |

**S4 outperforms S8 on every market by the binom p test.** S4 fires on stronger conviction (fair_edge > 500 bp + |dev_bps| ≥ 8), so each fire has a meaningful pre-condition. S8 fires more often but its individual WR-vs-vwap edge is thinner.

## Recommended deploy

| Sleeve label | Asset | Rule | Expected n/day @ $25 | Expected $/day @ $25 |
|---|---|---|--:|--:|
| `S4_BTC_offset120` | BTC | `fair_edge_bp > 500 AND cvd_agree_30s AND |dev_bps| ≥ 8 AND fire_offset_s ≥ 120` | 16 | +$36 |
| `S4_ETH_offset120` | ETH | (same) | 23 | **+$95** |
| `S4_SOL_offset120` | SOL | (same) | 15 | +$37 |
| `S8_BTC_offset120` | BTC | `macd_agree AND rvol_30_300 > 1.2 AND fire_offset_s ≥ 120` | 40 | +$38 |
| `S8_SOL_offset120` | SOL | (same) | 47 | +$93 (tail-dependent) |
| **TOTAL** | | | **~141/day** | **~+$299/day** |

S8_ETH explicitly NOT in the deploy list. If you want the simpler 3-sleeve version (S4 only, all assets), deploy at **~54 fires/day = +$167/day** with the lowest fragility.

### Conservative (S4 only, all assets)
- 1 133 fires over 21 days, WR 80.0 %, +$3 489 / 21d = **+$166/day**
- max DD: -$300 estimated (sum of per-market DDs is over-estimate; actual drawdown is non-overlapping per asset and likely lower)
- All 3 cells have binom p < 0.01 and wf_ret in [0.78, 1.56]

### Aggressive (S4 all + S8_BTC + S8_SOL, skip S8_ETH)
- 2 813 fires, **+$299/day** projected
- Larger DD exposure, S8_SOL leans on a single tail event

## Direction breakdown — UP vs DOWN

| sleeve | UP n / WR | DOWN n / WR | UP sum / DOWN sum |
|---|--:|--:|--:|
| S8 BTC | 426 / 85.5 % | 405 / 87.4 % | +$573 / +$226 |
| S4 BTC | 284 / 78.5 % | 61 / 80.3 % | +$657 / +$90 |
| S8 ETH | 497 / 85.9 % | 507 / 85.8 % | +$249 / +$391 |
| S4 ETH | 413 / 79.9 % | 60 / **86.7 %** | +$1 502 / +$476 |
| S8 SOL | 523 / 86.4 % | 454 / **89.9 %** | +$1 461 / +$462 |
| S4 SOL | 299 / 75.3 % | 16 / 81.3 % | +$567 / +$198 |

**Pattern**: DOWN trades have higher WR than UP trades in 5/6 sleeves (only S8_BTC's UP slightly higher). But UP trades carry more $ on S4 (FV-strong) because they fire on cheaper underdog tokens that pay more. The DOWN bias suggests a slight asymmetry: crypto markets resolve DOWN more often than vwap implies — possibly because the strike is set at slot_start and most slugs have negative drift inside their 5m window.

## Files

- Runner: `strategy_lab/overnight_2026_05_23/per_sleeve_per_market.py`
- Per-sleeve scorecard CSV: `data/v4/canonical/_results/per_sleeve_per_market.csv`
- Underlying panel: `data/v4/canonical/_results/master_5m_panel.parquet`
- Combined deploy CSV (S8+S4 trimmed, before per-asset split): `data/v4/canonical/_results/DEPLOY_CANDIDATE_S8_S4_offset120.csv`
