# Fresh Recalibration Runbook

**Started:** 2026-04-29
**Scope:** Use every backtest engine in `strategy_lab/` against the freshest data (VPS2: 8,200 resolved markets, 7+ days, complete Binance through ~2 min ago) to find a profitable Polymarket UpDown configuration, then validate against live shadow tape on VPS3.

**Decision rule:** ship a config only if it passes (a) baseline grid → (b) realistic-fill grid → (c) forward-walk holdout → (d) live-tape reconciliation within 5pp absolute hit-rate. Anything that fails any gate is dead.

---

## Tier 0 — Data refresh (block until done)

| Asset csv | Source | Generator |
|---|---|---|
| `{btc,eth,sol}_markets_v3.csv` | VPS2 `markets + market_resolutions_v2 + trades_v2` | `polymarket_extract_markets_v3.sql` |
| `{btc,eth,sol}_trajectories_v3.csv` | VPS2 `orderbook_snapshots_v2` (10s buckets, top-1 each side) | `polymarket_extract_trajectories_v3.sql` |
| `{btc,eth,sol}_book_depth_v3.csv` | VPS2 `orderbook_snapshots_v2` (10s buckets, L10 each side) | `polymarket_extract_book_depth.sql` |
| `{btc,eth,sol}_features_v3.csv` | VPS2 `markets + binance_klines_v2` | `polymarket_extract_features.sql` |
| `{btc,eth,sol}_klines_window.csv` | VPS2 `binance_klines_v2` (1m, full window) | direct psql COPY |
| `vps2_v1_shadow.csv` + `vps3_v2_shadow.csv` | live `trading.events` | direct psql COPY |

Run on VPS2 (data lives there, large COPY is local-loopback), `scp` to local. Watch:
- `markets_v3.csv` rows ≈ 8,200 (was 5,745 on Apr 27).
- Each book_depth file ~80–100 MB.

## Tier 1 — Baseline signal grid (cheap, run first)

`polymarket_signal_grid_v2.py` — replays every market with assumed-mid fills + HEDGE_HOLD exit. Produces ROI per (asset, tf, signal). **This is the "bull case" — if a signal can't make money here it's dead.**

Output: `results/polymarket/signal_grid_v2.csv`, `reports/POLYMARKET_SIGNAL_GRID_V2.md`.

## Tier 2 — Realistic fills (the truth)

`polymarket_signal_grid_realfills.py` — same matrix, but uses `book_walk.py` to walk the actual top-10 book to compute fill VWAP. Realistic taker cost. **Anything that loses ≥3pp ROI from Tier 1 to Tier 2 is fee/slippage-bound.**

Outputs: `signal_grid_realfills.csv`, `POLYMARKET_REALFILLS_HAIRCUT.md`.

`polymarket_realfills_validate.py` cross-checks Tier 1 vs Tier 2 cell-by-cell.

## Tier 3 — Filters (kill bad bars)

Run all four. Each consumes Tier 2 results and applies a different gate:

- `polymarket_microstructure_filter.py` — spread + L10 depth thresholds
- `polymarket_volume_filter.py` — Binance volume gate (drop low-vol minutes)
- `polymarket_volregime_revbp.py` — adaptive reversal-bp by realized vol regime
- `polymarket_revbp_floor_sweep.py` — fine sweep over the HYBRID reversal threshold {5..100 bp}

The revbp_floor_sweep IS the recalibration of the killer 5-bp threshold from the diagnosis. Top priority in this tier.

## Tier 4 — Alt entries / exits

- `polymarket_maker_entry.py` — 16 maker-entry variants (sit on bid for N seconds, fall back to taker)
- `polymarket_maker_hedge.py` — 8 maker-hedge variants
- `polymarket_take_profit.py` — 10 TP targets × 2 modes
- `polymarket_hedge_fallback.py` — fallback policy comparison

If maker-entry survives, that's the live ETV improvement (avg fill 0.51 instead of 0.53).

## Tier 5 — Cross-asset signals

- `polymarket_alt_signal_grid.py` — 9 alt-signal cross-asset grid
- `polymarket_cross_asset_leader.py` — leader-follower (BTC leads ETH/SOL)
- `polymarket_cross_asset_validate.py` — its forward-walk

## Tier 6 — Stratification & robustness

- `polymarket_time_of_day.py` — per-UTC-hour ROI (find dead hours, hot hours)
- `polymarket_side_asymmetry.py` — UP vs DOWN asymmetry
- `polymarket_weekday_check.py` — day-of-week
- `polymarket_robustness_check.py` — 4 stat tests for small samples (Wilson CI, sign test, bootstrap)

## Tier 7 — Factor research (open-ended)

- `polymarket_features_univariate.py` — IC of each feature vs ret_5m
- `polymarket_rank_ic.py` — Rank IC à la AlphaPurify
- `polymarket_strategy_stacks.py` — stacked combinations of (q × time)

## Tier 8 — Walk-forward holdout

`polymarket_forward_walk_v2.py` — chronological 80/20 split.
`polymarket_forward_walk_q10.py` — q10 sniper specifically.
`polymarket_forward_walk_maker.py`, `polymarket_forward_walk_spread.py` — variants with the specific entry / filter overlays.

**Pass criteria per cell:** holdout hit rate ≥ train hit rate − 5 pp AND holdout ROI > 0.

## Tier 9 — Live reconciliation

For every cell that passes Tier 8, replay it through VPS3's 607 live resolutions and VPS2's 655 V1 resolutions. Predicted vs actual must match within 5 pp absolute hit. **If the simulator overpredicts by >5 pp, the simulator is wrong, not the live system.**

## Output

Final aggregator script (to author): `recalibration_2026_04_29/aggregate.py` — joins every Tier's CSV into one master sheet, ranks cells by `(holdout_roi × passes_robustness × passes_live_recon)`, writes `FINDINGS.md`.

If anything ranks ≥+10% holdout ROI with all gates green, recommend deploying that single config. Otherwise: report "no edge found, keep the strategy off."

---

## Execution log (filled as we go)

- [ ] Tier 0: data refresh
- [ ] Tier 1: baseline signal grid
- [ ] Tier 2: realistic fills
- [ ] Tier 3: filters (revbp_floor_sweep first)
- [ ] Tier 4: alt entries/exits
- [ ] Tier 5: cross-asset signals
- [ ] Tier 6: stratification & robustness
- [ ] Tier 7: factor research
- [ ] Tier 8: walk-forward holdout
- [ ] Tier 9: live reconciliation
- [ ] Aggregator + FINDINGS.md
