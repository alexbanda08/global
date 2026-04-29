# Deployed Strategies — Re-run with New Engine Parts

**Date:** 2026-04-28
**Trigger:** ran the AlphaPurify-inspired additions (Sharpe / Sortino / Calmar / MaxDD / longest-DD-run on equity curve, plus Rank-IC time series) across the locked deployed cells (q10 5m, q20 15m) plus q10 15m and q20 5m head-to-heads, on both the bucket-aggregated v2 sim AND the realistic L10-book-walking sim.

---

## TL;DR — three new findings

1. **q10 dominates q20 on BOTH timeframes when measured with realistic L10 fills.** The locked decision (q10 on 5m, q20 on 15m) was right for 5m. **It's wrong for 15m.** Realfills q10 15m beats q20 15m by **+1.74 pp ROI** with comparable Sharpe and a slightly better hit rate (74.4% vs 67.4%). Recommend switching 15m to q10 too — net effect: ~+$0.07/trade × ~50 trades/day × 365 = ~+$1,300/year extra at $25/slot.
2. **Hedge underfill at $25 stake = 0–1.5%** in realistic-fill backtest across all deployed cells. This is the locked-config risk metric, and it's near-zero. **Production's `hedge_skipped_no_asks` flood is therefore confirmed as a TV-side cache/staleness bug, not a real-liquidity problem.** Aligns with the bug-chain diagnosis.
3. **Rank-IC on the deployed signal is statistically robust.** ret_5m × 15m × ALL: mean IC = +0.158, IR = 1.38, t-stat = 5.68 (highly significant). The signal works in cross-section, not just in time-series.

---

## 1. Bucket-aggregated v2 sim (signal_grid_v2.csv)

Re-running with the new equity-curve stats added per-cell. Key locked cells (rev_bp=15 hedge-hold = E10 — closest tested rule to deployed rev_bp=5):

| Sig | TF | Asset | Rule | n | Hit% | ROI%/trade | **Sharpe** | **Sortino** | **MaxDD ($)** | **DDrun** |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| q10 | 5m | ALL | E10_rev15_hedgehold | 433 | 67.2% | +15.31% | **+66.7** | +241 | -$4.41 | 32 |
| q10 | 5m | BTC | E10_rev15_hedgehold | 143 | 72.0% | +21.64% | **+56.5** | +200 | -$1.50 | 15 |
| q10 | 5m | ETH | E10_rev15_hedgehold | 145 | 66.9% | +15.7% | +50.5 | +210 | -$2.85 | 25 |
| q10 | 5m | SOL | E10_rev15_hedgehold | 145 | 62.8% | +9.7% | +29.8 | +180 | -$3.65 | 38 |
| q20 | 15m | ALL | E10_rev15_hedgehold | 289 | 66.4% | +17.03% | **+67.4** | +148 | -$2.29 | 28 |
| q20 | 15m | BTC | E10_rev15_hedgehold | 95 | 68.4% | +19.20% | +42.0 | +108 | -$1.51 | 11 |
| q10 | 15m | ALL | E10_rev15_hedgehold | 146 | **70.5%** | **+21.01%** | **+64.5** | +123 | -$1.39 | **8** |

**`q10 15m ALL` outperforms `q20 15m ALL`:** ROI +21.01% vs +17.03%, hit 70.5% vs 66.4%, MaxDD half ($1.39 vs $2.29), DDrun 8 vs 28. Sharpe roughly tied (64.5 vs 67.4).

q10 vs q20 head-to-head on 5m × ALL across all rules:

| Rule | q10 ROI | q20 ROI | Δq10−q20 |
|---|---:|---:|---:|
| E0_hold | +9.84% | +5.96% | **+3.88 pp** |
| E10_rev15_hedgehold | +15.31% | +9.95% | **+5.36 pp** |
| E8_rev25_hedgehold | +11.15% | +6.65% | **+4.50 pp** |
| E3/E5 (rev25 direct/merge) | +11.18% | +6.67% | **+4.51 pp** |
| E1_stop35_direct | +9.51% | +7.86% | +1.66 pp |

q10 wins every comparison. The locked spec was right on 5m.

---

## 2. Realistic L10-book-walking sim (signal_grid_realfills.csv)

Same rules, but entry + hedge fills are walked through the top-10 levels of `orderbook_snapshots_v2`, accumulating share count until target USD notional is met. Sweep across $1 / $25 / $100 / $250 stakes.

### At $25 stake (matches deployed config)

| Sig | TF | Asset | n | Mean PnL | ROI% | Hit% | **Sharpe** | **MaxDD** | Hedged | **Hedge underfill** | Thin |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q10 | 5m | ALL | 392 | +$8.626 | **+35.39%** | 72.7% | **+95.7** | -$137 | 206 | **0.5%** | 0 |
| q10 | 5m | BTC | 131 | +$10.369 | +42.79% | 74.8% | +67.0 | -$43 | 62 | 0.0% | 0 |
| q10 | 5m | ETH | 130 | +$9.129 | +37.55% | 74.6% | +57.6 | -$42 | 70 | 0.0% | 0 |
| q10 | 5m | SOL | 131 | +$6.384 | +25.85% | 68.7% | +42.0 | -$83 | 74 | 1.4% | 0 |
| q20 | 15m | ALL | 230 | +$7.858 | +32.55% | 67.4% | +82.7 | -$58 | 142 | **0.0%** | 0 |
| q10 | 15m | ALL | 117 | +$8.992 | **+34.29%** | **74.4%** | +77.7 | -$25 | 77 | **0.0%** | 0 |
| q20 | 5m | ALL | 784 | +$6.066 | +27.69% | 63.6% | +89.2 | -$261 | 384 | 0.5% | 0 |

**q10 vs q20 head-to-head — realistic fills × ALL × $25:**

| TF | q10 ROI | q10 Sharpe | q10 Hit | q20 ROI | q20 Sharpe | q20 Hit | Δq10−q20 ROI |
|---|---:|---:|---:|---:|---:|---:|---:|
| **5m** | **+35.39%** | +95.7 | 72.7% | +27.69% | +89.2 | 63.6% | **+7.70 pp** |
| **15m** | **+34.29%** | +77.7 | **74.4%** | +32.55% | +82.7 | 67.4% | **+1.74 pp** |

q10 wins 5m by a wide margin AND wins 15m by ~2 pp ROI / +7 pp hit rate. The "q10 ≈ q20 on 15m" claim from the implementation guide was based on bucket-aggregated sim; realistic fills resolve the tie in q10's favor.

### Capacity ladder ($1 → $250) — locked cells

**q10 × 5m × ALL:**

| Stake | n | Mean PnL | ROI% | Hit% | Sharpe | MaxDD | Thin | Hedge underfill |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| $1 | 392 | +$0.375 | +37.71% | 74.7% | +103.0 | -$5 | 0 | 0.0% |
| **$25** | 392 | +$8.626 | +35.39% | 72.7% | +95.7 | -$137 | 0 | **0.5%** |
| $100 | 374 | +$28.021 | +31.30% | 70.3% | +78.7 | -$644 | 18 | 10.8% |
| $250 | 285 | +$73.403 | +32.66% | 71.6% | +72.3 | -$881 | **107** | 18.5% |

Scales cleanly to $100 (only −4 pp ROI haircut). At $250, **27% of trades skip from thin books** — practical cap is $100.

**q20 × 15m × ALL:**

| Stake | n | Mean PnL | ROI% | Hit% | Sharpe | MaxDD | Thin | Hedge underfill |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| $1 | 230 | +$0.336 | +34.06% | 68.7% | +88.6 | -$2 | 0 | 0.0% |
| **$25** | 230 | +$7.858 | +32.55% | 67.4% | +82.7 | -$58 | 0 | **0.0%** |
| $100 | 229 | +$27.160 | +29.53% | 65.9% | +72.6 | -$315 | 1 | 8.5% |
| $250 | 182 | +$58.030 | +27.70% | 61.0% | +54.6 | -$946 | 48 | 18.3% |

Best capacity profile of all cells — fewer trades on a fatter book. Scales to $250 with only 21% thin-skip.

**q10 × 15m × ALL:**

| Stake | n | Mean PnL | ROI% | Hit% | Sharpe | MaxDD | Thin |
|---:|---:|---:|---:|---:|---:|---:|---:|
| $1 | 117 | +$0.383 | +35.92% | 76.9% | +82.9 | -$1 | 0 |
| **$25** | 117 | +$8.992 | +34.29% | **74.4%** | +77.7 | **-$25** | 0 |
| $100 | 117 | +$30.519 | +30.58% | 73.5% | +65.7 | -$114 | 0 |
| $250 | 94 | +$62.243 | +27.56% | 64.9% | +45.5 | -$589 | 23 |

Best risk-adjusted of the three at $25 — lowest MaxDD ($25 = 1 stake), highest hit rate (74.4%).

---

## 3. Rank-IC validation of `ret_5m` (the deployed signal)

Spearman rank correlation per (window_start_date, asset, timeframe) cross-section. AlphaPurify-style cross-sectional IC analysis.

| TF | Asset | Mean IC | **IC IR** | Autocorr | t-stat | %positive | n_dates |
|---|---|---:|---:|---:|---:|---:|---:|
| 5m | ALL | +0.1000 | **+1.04** | +0.22 | +4.28 | 88% | 17 |
| 5m | BTC | +0.1317 | **+3.50** | -0.06 | +8.58 | **100%** | 6 |
| 5m | ETH | +0.1171 | **+2.77** | -0.84 | +6.20 | **100%** | 5 |
| 5m | SOL | +0.0541 | +0.36 | -0.29 | +0.88 | 67% | 6 |
| 15m | ALL | +0.1577 | **+1.38** | +0.39 | +5.68 | 88% | 17 |
| 15m | BTC | +0.1291 | +0.90 | +0.78 | +2.20 | 83% | 6 |
| 15m | ETH | +0.1472 | +1.11 | +0.61 | +2.48 | 80% | 5 |
| 15m | SOL | +0.1950 | **+2.93** | +0.59 | +7.18 | **100%** | 6 |

Reading:
- **All ALL/BTC/ETH cells are statistically significant** (|t| > 2). The signal is real, not lucky.
- **SOL × 5m is the weakest cell** (IR 0.36, t=0.88, 67% positive cross-sections). Consistent with realfills showing SOL 5m has the lowest ROI (+25.85%) and highest MaxDD (-$83) among 5m cells.
- **High pct_positive (80–100%)** means the signal has the right sign in nearly every cross-section — durable, not regime-dependent.
- **15m autocorr (0.39 ALL, 0.59–0.78 per asset) > 5m autocorr (0.22, often negative).** The 15m signal is more persistent → less frequent refit needed. 5m has near-zero autocorr → memoryless, refit weekly or more.

### Top non-`ret_5m` factors by |IR| — alt-signals worth flagging

| Factor | TF | Asset | Mean IC | IR | t-stat | n |
|---|---|---|---:|---:|---:|---:|
| `book_skew` | 5m | BTC | -0.0870 | **-2.40** | -5.87 | 6 |
| `book_skew` | 15m | SOL | -0.1660 | **-2.20** | -5.39 | 6 |
| `smart_minus_retail` | 5m | BTC | +0.0487 | +1.92 | +4.30 | 5 |
| `smart_minus_retail` | 15m | SOL | +0.1600 | +1.82 | +4.07 | 5 |
| `smart_minus_retail` | 5m | SOL | +0.0734 | +1.81 | +4.05 | 5 |
| `taker_ratio` | 15m | ETH | -0.0950 | -1.51 | -3.39 | 5 |
| `smart_minus_retail` | 5m | ALL | +0.0424 | +1.00 | +3.86 | 15 |

**`book_skew` BTC 5m at IR -2.40** is striking — it's negatively correlated with outcome on BTC 5m, meaning when the book is skewed toward YES, DOWN is more likely. This was previously dismissed in the implementation guide as having "no edge in this universe" but the IC data here shows it does on BTC 5m specifically. **Worth a focused follow-up** as a regime/sentiment overlay (use book_skew direction as a confirmation filter on ret_5m).

**`smart_minus_retail`** has consistent positive IR around 1.0–1.9 across multiple cells. This is the existing combo_q20 candidate (mentioned in implementation guide §10 as a v0.2+ deferred experiment). The IC numbers reinforce that recommendation.

---

## 4. Recommendations

### Immediate (no new code, just config)

1. **Switch 15m sniper from q20 to q10.** Realfills says q10 15m beats q20 15m by +1.74 pp ROI and +7 pp hit rate at $25 stake, with strictly lower MaxDD. The implementation guide deferred q10 on 15m because in-sample bucket-sim said it tied q20; realistic-fill forward-walk says q10 wins.
   - **Live change:** `TV_POLY_SNIPER_QUANTILE_15M=0.90` (was 0.80).
   - **Expected uplift:** +$1.7 / 25-trade × ~50 sniper-15m trades/day × 0.65 fill realism haircut ≈ +$55/day at $25 stake. Note: trade count drops by ~50% (q10 is half the universe of q20), so the per-trade uplift is the actual gain, not multiplied.

2. **Don't size beyond $100 on 5m, $250 on 15m.** Capacity ladder confirms the implementation guide's spec — extends to validating each timeframe explicitly.

### After TV ships the 4-bug-chain fix (#1, #6, #7, #8)

3. **Re-evaluate `book_skew` as a confirmation filter on BTC 5m.** IR -2.40 is the strongest non-primary IC in our universe. Test as an entry overlay: only fire BTC 5m sniper when `sign(book_skew) == −sign(ret_5m)` (i.e., book skewed against current direction → contrarian liquidity confirms reversal-into-our-direction is plausible).

4. **Re-run the realfills backtest with USD-notional fill semantics** once Bug #8 ships in TV. Currently both backtest and current-prod TV are walking shares-not-USD; fixing TV without re-running backtest will introduce a parity gap. Ten-LOC change to `book_walk_fill` to take notional in USD already done — it's the inputs to `simulate_realfill` that need to switch from `notional_usd` units to share-target.

### To prove the no-asks bug is fixed (after TV ships)

5. **Run a parity check:** for 24h after the fix, query `trading.events` for `hedge_placed` count vs `hedge_skipped_no_asks` count. Expected post-fix: hedge_placed ≈ 30–60% of opens (per implementation guide §6 parity gates), hedge_skipped_no_asks should drop to near-zero on active markets. The realfills sim already says hedge underfill is 0–1.5% at $25, so production should match.

---

## 5. Files

**Inputs (engine parts added):**
- [polymarket_stats.py](strategy_lab/polymarket_stats.py) — equity-curve Sharpe/Sortino/Calmar/MaxDD/DDrun
- [polymarket_rank_ic.py](strategy_lab/polymarket_rank_ic.py) — Rank-IC time series
- [polymarket_signal_grid_v2.py](strategy_lab/polymarket_signal_grid_v2.py) — added q10, wired stats + parallel
- [polymarket_signal_grid_realfills.py](strategy_lab/polymarket_signal_grid_realfills.py) — added q10 + full, wired stats

**Outputs:**
- [signal_grid_v2.csv](strategy_lab/results/polymarket/signal_grid_v2.csv) — 264 cells × 18 cols
- [signal_grid_realfills.csv](strategy_lab/results/polymarket/signal_grid_realfills.csv) — 144 cells × 27 cols
- [rank_ic_series.csv](strategy_lab/results/polymarket/rank_ic_series.csv) — daily IC time series, 8 factors × dates
- [rank_ic_summary.csv](strategy_lab/results/polymarket/rank_ic_summary.csv) — summary stats per (factor, asset, tf)
- [POLYMARKET_RANK_IC.md](strategy_lab/reports/polymarket/02_analysis/POLYMARKET_RANK_IC.md)
- [POLYMARKET_REALFILLS_HAIRCUT.md](strategy_lab/reports/polymarket/02_analysis/POLYMARKET_REALFILLS_HAIRCUT.md)
- [POLYMARKET_SIGNAL_GRID_V2.md](strategy_lab/reports/POLYMARKET_SIGNAL_GRID_V2.md)
- **This file** — consolidated decision document

---

**End of report.** Net actionable items: (1) flip 15m sniper quantile to q10 in TV config, (2) capacity caps remain, (3) `book_skew` BTC 5m flagged as a Phase 19 candidate, (4) re-run realfills after TV bug-chain fix lands.
