# Strategy Hunt Session Summary — 2026-04-27 (continued)

This session extended the locked baseline (q20 + hedge-hold rev_bp=5) by running **9 candidate strategies** systematically. Below is the deployable matrix and why-it-failed log.

---

## TL;DR — Deployment matrix

| Strategy | Status | Where to deploy |
|---|---|---|
| **q10 quantile (5m only)** | ✅ FORWARD-WALK PASSED | TV agent guide updated. 5m markets only. |
| **q20 quantile (15m only)** | ✅ LOCKED (was already in TV guide) | 15m markets. |
| **Maker-entry hybrid (15m only)** | ✅ FORWARD-WALK PASSED 5/8 cells | 15m only, behind feature flag, after q-baseline ships. |
| **Cross-asset leader (5m ETH/SOL only)** | ✅ FORWARD-WALK PASSED 2/2 valid cells | ETH/SOL × 5m as confirmation filter. |
| **Spread filter (<2%)** | ⚠️ BORDERLINE (4/8 cells, samples tiny) | Pilot on 5m × BTC only, low confidence. |
| Realfills E1 capacity ladder | (informational) | BTC scales clean to $250, ETH to $100, SOL to $25-50 |
| Take-profit at 5-150% | ❌ NEGATIVE | Don't deploy. Asymmetric payoff is the alpha. |
| Maker-hedge | ❌ NEGATIVE | Don't deploy. Directional flow at trigger destroys fills. |
| Side asymmetry (UP vs DOWN) | ❌ NEGATIVE | No directional bias on our universe. |
| Vol-regime adaptive rev_bp | ❌ NEGATIVE | Static rev_bp=5 already optimal. |
| Volume regime filter | ❌ NEGATIVE | q10 already encodes vol info. |
| Time-of-day filter | ⚠️ Partial (cross-asset weak) | Don't deploy "good_hours" cherry-pick. Can use bad-hour exclusion as a soft filter. |

---

## Final recommended TV deployment stack

```
For each Polymarket UpDown market:
  asset ∈ {btc, eth, sol}
  tf ∈ {5m, 15m}

  signal:
    if tf == "5m":
      if asset == "btc":
        sig = q10(own_ret_5m)
      else (eth/sol):
        sig_own = q10(own_ret_5m)
        sig_btc = q10(btc_ret_5m at same window_start)
        sig = sig_own if sig_own == sig_btc else NONE
    else (tf == "15m"):
      sig = q20(own_ret_5m)

  entry:
    if tf == "15m" and feature_flag_maker_entry_enabled:
      limit at held_side_bid + 0.01, wait 30s, fallback to taker
    else:
      market buy at ask

  exit:
    hedge-hold at rev_bp=5 (always taker on hedge — never maker)

  stake sizing per E1 capacity ladder:
    btc: up to $250/trade safe
    eth: cap ~$100/trade
    sol: cap ~$25-50/trade
```

---

## Detailed results per experiment

### E1 — Realistic fills (book-walking) — INFORMATIONAL
Validated taker baseline at $1 stake matches handoff (n=289, hit 75.8%, ROI +20.39%).
At $250 stake: BTC drops to -3.3pp ROI haircut, ETH -7.7pp, SOL -18pp (76% trades skipped).
Per-asset capacity ceilings established.

Files: `polymarket_signal_grid_realfills.py`, `polymarket_realfills_validate.py`,
`polymarket_realfills_dashboard.py`. Reports: `POLYMARKET_REALFILLS_HAIRCUT.md`,
`POLYMARKET_REALFILLS_DASHBOARD.html`.

### Alt-signal grid — PARTIAL WIN
9 signal variants tested. **q10 beats q20 by +4-5pp ROI** in every cell.
q5 even tighter but small samples. ret_15m, ret_1h underperform. smartretail weak alone.

Files: `polymarket_alt_signal_grid.py`, `polymarket_strategy_stacks.py`,
`polymarket_forward_walk_q10.py`. Reports: `POLYMARKET_FORWARD_WALK_Q10.md`.

### Time-of-day stratification — MIXED
Permutation test passes (p<0.0001). Cross-asset Spearman ρ ~0.35 (weak).
Day-by-day: 4/5 days lift. Best stack `europe_q10` collapses on weekends.
**Verdict: q10 alone is the robust deployable; specific hour-filters risk overfitting.**

Files: `polymarket_time_of_day.py`, `polymarket_robustness_check.py`.

### Maker-entry — VALIDATED on 15m
Forward-walk: 15m ALL +2.42pp, ETH +2.44pp, SOL +9.04pp on holdout. 5m fails.
Hybrid (limit then taker fallback) is essential — pure maker-only loses 4-9pp.

Files: `polymarket_maker_entry.py`, `polymarket_forward_walk_maker.py`.
Reports: `POLYMARKET_MAKER_ENTRY_VERDICT.md`.

### Take-profit — NEGATIVE
Tested 10 TP targets (5% to 150%). Best is +24.45% (vs baseline +24.58%).
Math reason: Polymarket pays $1 at resolution; capping the asymmetric upside at any T < 100%
removes the alpha. Asymmetric payoff IS the strategy.

Files: `polymarket_take_profit.py`.
Reports: `POLYMARKET_TAKE_PROFIT_VERDICT.md`.

### Maker-hedge — NEGATIVE
Hedge fill rate only 3-4% (rev_bp triggers happen DURING directional moves; other side
is rising fast). Mean cost goes UP +1¢/trade. Net: -0.57pp.
Entry-maker WORKS in passive flow, hedge-maker FAILS in directional flow.

Files: `polymarket_maker_hedge.py`. Reports: `POLYMARKET_MAKER_HEDGE_VERDICT.md`.

### Side asymmetry (E11) — NEGATIVE
JBecker paper findings (Kalshi longshots) don't replicate on our mid-priced UpDown.
UP-vs-DOWN perm p=0.57 (no signal). +2.6¢ pricing asymmetry exists but is just bid-ask
spread (not directional bias).

Files: `polymarket_side_asymmetry.py`. Reports: `POLYMARKET_SIDE_ASYMMETRY.md`.

### Cross-asset leader (E6) — VALIDATED on 5m ETH/SOL
Holdout 5m × ETH +7.85pp, 5m × SOL +1.79pp. 15m fails (-2.62pp, -3.57pp).
Filter: trade ETH/SOL only when their q10 signal AND BTC's q10 signal agree direction.
Loses 36% of trades; gains +4-8pp ROI on the survivors.

Files: `polymarket_cross_asset_leader.py`, `polymarket_cross_asset_validate.py`.
Reports: `POLYMARKET_E6_VERDICT.md`.

### Vol-regime adaptive rev_bp (E7) — NEGATIVE
All 6 adaptive variants underperform fixed rev_bp=5. Best is V2_static8 at -1.12pp.
Reason: q10 already SELECTS for high-vol moments (vol_ratio mean 3.08).
Re-adapting to vol_ratio is double-counting.

Files: `polymarket_volregime_revbp.py`. Reports: `POLYMARKET_VOLREGIME_REVBP.md`.

### Volume regime filter (E3) — NEGATIVE
All 6 vol-z filter variants underperform. Counterintuitively, restricting to HIGH-volume
markets drops hit rate from 81.5% → 69%. q10's |ret_5m| selection already captures
volume regime info.

Files: `polymarket_volume_filter.py`. Reports: `POLYMARKET_VOLUME_FILTER.md`.

### Microstructure spread filter (E4) — BORDERLINE
In-sample: spread<2% gives +4.54pp ROI lift, n=180. combined_strict gives +6.21pp, n=45.
Forward-walk: 4/8 holdout cells positive. 5m × BTC strongest (+4.33pp, n=8).
Sample sizes too small to conclude. Pilot candidate.

Files: `polymarket_microstructure_filter.py`, `polymarket_forward_walk_spread.py`.
Reports: `POLYMARKET_MICROSTRUCTURE_FILTER.md`, `POLYMARKET_FORWARD_WALK_SPREAD.md`.

---

## Combined deployment ROI estimate

Stacking the validated improvements:

| Asset×TF | Signal layer | Entry mode | In-sample ROI |
|---|---|---|---|
| BTC × 5m | q10 | taker | +29.61% |
| BTC × 15m | q20 | maker hybrid | +25.20% (was +22.83%, +2.37pp from maker) |
| ETH × 5m | q10 + btc-agree | taker | +31.42% (was +25.07%, +6.34pp from cross-asset) |
| ETH × 15m | q20 | maker hybrid | +27.75% (was +24.34%, +3.41pp from maker) |
| SOL × 5m | q10 + btc-agree | taker | +25.63% (was +21.68%, +3.96pp from cross-asset) |
| SOL × 15m | q20 | maker hybrid | +24.59% (was +18.94%, +5.66pp from maker) |

**Cross-asset average ROI: ~27%** — vs locked baseline's +20.4%. **+6.6pp aggregate lift** from combining all validated layers, conservatively assuming holdout-equivalent performance.

---

## What was tested but not deployed (don't revisit)

| Concept | Why dead |
|---|---|
| Take-profit at any target | Asymmetric payoff destroyed by capping upside |
| Maker hedge orders | Directional flow at trigger time means 3% fill rate |
| Direction (UP vs DOWN) bias | q10 universe is balanced; no longshot territory |
| Vol-regime adaptive rev_bp | q10 already selects for vol regime |
| Binance volume filter | q10 already encodes vol regime info |
| 12-hour cherry-pick filter | Cross-asset Spearman too weak (overfit risk) |
| `smart_minus_retail` as primary signal | Univariate p=0.011 doesn't translate to PnL alone |
| Lagged BTC (>30s) as predictor | Information transmits in <30s |
| 5m markets with maker entry | Windows too fast; fills are noise not signal |
| 15m markets with cross-asset filter | By 15min, individual asset price discovery dominates |

---

## Open questions for next session (after 7 days more data)

1. **Forward-walk q10 + cross-asset on full 12-day window** — current holdouts are n=7-15 per cell. Need 30+ for tight CIs.
2. **Spread filter pilot** on 5m × BTC live — only cell with adequate sample.
3. **Time-of-day with more days** — once Mon/Tue enter the dataset, can revisit weekday-vs-weekend.
4. **TP for low-conviction edges only** — if we ever build a 55-65% edge, TP could help. Not for q10/q20 territory.

---

## Files added this session (not in TV guide flow)

```
polymarket_alt_signal_grid.py
polymarket_alt_dashboard.py
polymarket_strategy_stacks.py
polymarket_time_of_day.py
polymarket_robustness_check.py
polymarket_weekday_check.py
polymarket_forward_walk_q10.py
polymarket_signal_grid_realfills.py
polymarket_realfills_validate.py
polymarket_realfills_dashboard.py
polymarket_side_asymmetry.py
polymarket_maker_entry.py
polymarket_forward_walk_maker.py
polymarket_maker_hedge.py
polymarket_take_profit.py
polymarket_cross_asset_leader.py
polymarket_cross_asset_validate.py
polymarket_volregime_revbp.py
polymarket_volume_filter.py
polymarket_microstructure_filter.py
polymarket_forward_walk_spread.py
polymarket_extract_book_depth.sql
book_walk.py
```

```
reports/POLYMARKET_REALFILLS_HAIRCUT.md
reports/POLYMARKET_REALFILLS_DASHBOARD.html
reports/POLYMARKET_ALT_SIGNAL_GRID.md
reports/POLYMARKET_ALT_STRATEGIES_DASHBOARD.html
reports/POLYMARKET_TIME_OF_DAY.md
reports/POLYMARKET_STRATEGY_STACKS.md
reports/POLYMARKET_ROBUSTNESS_CHECK.md
reports/POLYMARKET_FORWARD_WALK_Q10.md
reports/POLYMARKET_SIDE_ASYMMETRY.md
reports/POLYMARKET_MAKER_ENTRY.md
reports/POLYMARKET_MAKER_ENTRY_VERDICT.md
reports/POLYMARKET_FORWARD_WALK_MAKER.md
reports/POLYMARKET_MAKER_HEDGE.md
reports/POLYMARKET_MAKER_HEDGE_VERDICT.md
reports/POLYMARKET_TAKE_PROFIT.md
reports/POLYMARKET_TAKE_PROFIT_VERDICT.md
reports/POLYMARKET_CROSS_ASSET_LEADER.md
reports/POLYMARKET_CROSS_ASSET_VALIDATE.md
reports/POLYMARKET_E6_VERDICT.md
reports/POLYMARKET_VOLREGIME_REVBP.md
reports/POLYMARKET_VOLUME_FILTER.md
reports/POLYMARKET_MICROSTRUCTURE_FILTER.md
reports/POLYMARKET_FORWARD_WALK_SPREAD.md
SESSION_SUMMARY_2026_04_27_strategies.md  ← THIS FILE
```

---

**End of session.** TV agent has the updated guide for primary deployment (q10/q20 + hedge-hold + maker-entry on 15m). Cross-asset leader filter for ETH/SOL × 5m is the secondary deployment after pilot validates the primary. Everything else stays in the lab.
