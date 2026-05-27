# HL Strategy Research — Paper Deploy Candidates (Wave 4)

**Date**: 2026-05-26
**Universe**: BTC/ETH/SOL/HYPE on Hyperliquid (+ optional cross-venue Binance basis)
**Total strategies tested**: 790 cells across 6 hypothesis families
**Deploy candidates (passing n≥30, Sharpe≥1.5, ≥3 statistical gates)**: 13
**Pass-all-5-gates (G1+G2+G3+G4+G6)**: 3 candidates ⭐

---

## TL;DR

**The single strongest find of this research: hypothesis N3 — Spot-Perp Basis Carry**.

Out of 12 novel angles tested, the **HL vs Binance spot-perp basis reversion is the only family that produced multiple cells passing all 5 statistical gates** with reasonable sample size (n=100-621), reasonable WR (51-62%), Sharpe 1.8-3.8.

The basis-carry mechanism: at each hourly bar, compute `basis_bps = (binance_spot - hl_perp) / hl_perp × 10000`. Compare to expected basis (30d avg funding × hours). When mispricing exceeds ±1.5σ over a rolling 30d window, trade convergence — LONG HL if HL is "cheap", SHORT if HL is "expensive". Hold 24-72h for full convergence.

**This is a NEW strategy**, distinct from V52, distinct from Cyclops/F7/Markov Polymarket lineage, and exists only because of the HL-Binance basis relationship.

Two secondary findings deserve paper deploy:
- **Polymarket SMS liquidity_reclaim port** works only at 4h on SOL (fees crush every shorter TF)
- **HYPE funding contrarian** on 72h hold — leans on HYPE's wider funding variance

**Several major hypotheses were REJECTED**:
- N1 (liq cascades) — untestable, HL liq data clusters in Oct 2025 but HL klines start Jan 30 2026
- N5 (cross-asset lead-lag 30-180s) — BTC↔ETH co-movement is contemporaneous within 1m bar
- N9 (Cyclops port) — only 1 marginal cell (ETH 1h baseline) that fails G6 bootstrap
- N11 (structure-break pairs) — pair fees ($0.60 round-trip) eat any gross edge

---

## TIER 1 — Basis Carry Family (PRIMARY DEPLOY)

Deploy as a **single coordinated portfolio** — these cells are correlated by design (same mechanism). Diversification comes from asset + horizon + z-threshold.

### T1.1 ETH 24h Basis z1.5 ⭐ STRONGEST OVERALL
- **n=216, WR 59.3%, $/tr +$2.15, Sharpe 3.79**
- p=0.008, permutation-p=0.001, bootstrap 95-CI passes
- Passes **ALL 5 gates** (G1+G2+G3+G4+G6)
- Trigger: at hourly bar, if `basis_bps < expected_bps - 1.5σ` → LONG ETH-perp on HL
- Exit: 24h hold, no SL/TP

### T1.2 BTC 24h Basis z2.0
- **n=100, WR 61%, $/tr +$1.53, Sharpe 3.23**
- Passes ALL 5 gates
- Stricter z-threshold than ETH; lower n but cleanest BTC signal

### T1.3 SOL 72h Basis z2.0
- **n=132, WR 53%, $/tr +$2.39, Sharpe 3.50**
- Passes G2+G3+G4+G6 (G1 narrowly misses)
- SOL needs longer horizon (72h) at strict z=2.0

### T1.4-T1.8 Secondary basis cells (smaller weights, diversification)
- N3 SOL 24h z2.0 — n=126, Sharpe 3.45
- N3 SOL 72h z1.5 — n=286, Sharpe 2.72
- N3 ETH 24h z1.0 — n=507, Sharpe 2.39 (looser threshold = more trades)
- N3 BTC 24h z1.0 — n=532, Sharpe 1.91
- N3 SOL 24h z1.0 — n=621, Sharpe 1.82

### Capital allocation suggestion (Tier 1)
- 35% — ETH 24h z1.5 (T1.1) — flagship
- 25% — BTC 24h z2.0 (T1.2) — strictest, cleanest
- 20% — SOL 72h z2.0 (T1.3) — longer horizon diversification
- 10% — ETH 24h z1.0 (T1.6) — higher n, smaller per-trade
- 10% — BTC 24h z1.0 (T1.7) — higher n, smaller per-trade

### Implementation note
Backtest used 24h funding rate as the expected basis proxy. **Live deploy must use the actual current funding term-structure on HL** (next-hour funding from HL API) since the mechanism is sensitive to expected funding accuracy.

---

## TIER 2 — Polymarket SMS Port (SECONDARY DEPLOY)

### T2.1 SOL 4h pure_sms_signal_flip
- **n=105, WR 69.5%, $/tr +$4.24, Sharpe 3.75**
- Passes G1+G2+G6
- Trigger: at 4h bar, if `liquidity_dn == True` (price tapped 20-bar low) → LONG SOL; `liquidity_up` → SHORT SOL
- Exit: hold until opposite signal fires (signal-flip)

**Caveat**: Only the 4h timeframe survived. 5m/15m/1h were crushed by fees. Asset ranking on HL is **SOL > BTC > ETH** (inverse of Polymarket where BTC dominated). This suggests the edge is SOL-specific — possibly due to SOL's higher realized vol amplifying the per-bar signal-to-fee ratio.

### Capital allocation
Single 100% allocation if deployed standalone. Recommended as **diversifier** to Tier 1 (different mechanism, different timeframe).

---

## TIER 3 — HYPE Funding Contrarian (EXPERIMENTAL DEPLOY)

### T3.1 HYPE 72h N2-cross_to_neg z2.0
- **n=151, WR 57.6%, $/tr +$3.10, Sharpe 2.87**
- Passes G2+G3+G4+G6 (G1 borderline)
- Trigger: HYPE funding crosses from positive to negative AND z-score > 2 → contrarian SHORT
- Exit: 72h hold

### T3.2 HYPE 72h N2-B z1.5
- **n=116, WR 54.3%, $/tr +$2.92, Sharpe 2.63**
- Trigger: HYPE funding z < -1.5 (extremely negative, shorts paying lots) → LONG HYPE

**Caveats**:
- HYPE has only 106d of canonical funding history — limited statistical power
- HYPE has no Binance equivalent (perp-only token) — no basis-carry available
- 72h hold means funding-cost sensitivity. Live deploy must monitor real funding accrual closely.

### Capital allocation
Very small (<5% of total book) until 60+ days of paper deploy confirms.

---

## TIER 4 — Pending Validation (HIGH POTENTIAL, INSUFFICIENT DATA)

Several cells showed high gross edge but failed walk-forward G3 due to data concentration. These are NOT deploy candidates yet but ARE high-priority for follow-up research:

### T4.1 ETH 1m cascade reversion (filt: ranging regime + markov_contra)
- **n=13, WR 84.6%, $/tr +$10.21, Sharpe 15.3, p=0.022, perm-p=0.03**
- Failed G3 — all events cluster in single regime (Oct 2025 deleveraging)
- **Action**: pull broader liq venues (Binance/Bybit `forceOrders`), re-test on multi-venue liq feed

### T4.2 SOL 4h sms_markov_sized_hold3
- **n=31, WR 80.6%, $/tr +$5.51, Sharpe 10.1**
- G6 bootstrap 95-CI = [+$2.94, ...] passes
- But n=31 is borderline; collect 60-90 more days before promoting

### T4.3 Meta-classifier LightGBM 15m/1h cells
- Multiple BTC/ETH 15m + 1h cells from W3 show AUC drop 3-4% over null after permutation
- BTC 15m: real 0.543 vs shuffled 0.500 (drop 4.3%)
- ETH 15m: 0.539 vs 0.500 (drop 3.8%)
- **Edge is real but small**; need feature-selection refinement + position-sizing strategy
- See `wave2/W3_walkforward_results.csv` for full window-by-window AUC

---

## REJECTED HYPOTHESES (audit trail)

| Hyp | Name | Reason for rejection |
|---|---|---|
| N1 | HL liquidation cascades | Data gap — HL liq concentrated Oct 2025, HL klines start Jan 30 2026 |
| N5 | Cross-asset lead-lag 30-180s | BTC↔ETH lag-1m corr = 0.013, no exploitable lag-edge at >1 sec |
| N9 | Cyclops 3-axis port | Only 1 marginal cell (ETH 1h baseline) that fails G6 bootstrap |
| N11 | SMS structure-break pairs | Mean PnL -$0.67/tr after pair fees ($0.60 round-trip) |
| Polymarket SMS at 5m/15m/1h | SMS port for short TFs | Fees crush sub-bar edges; only 4h survives |
| Polymarket regime-trending overlay | Regime gating on HL futures | Regime + sweep-reversal self-contradicting on continuous price |

---

## VALIDATION CHECKLIST FOR LIVE PAPER DEPLOY

Before going to paper-trade mode on Hyperliquid:

1. **Refresh data**: pull HL klines + funding through 2026-05-26 (current end is 2026-05-16). Re-run T1/T2/T3 on the +10d window. Sharpe should stay positive on fresh data.
2. **Latency model**: 50ms is the engine default. Verify against actual HL API round-trip from production environment. If latency >200ms, redo backtest with realistic figure.
3. **Slippage validation**: backtest assumes 3 bps slip. Pull recent HL trade tape, compute realized slippage at $250 notional, confirm 3 bps is conservative.
4. **Funding cap**: engine caps at 1.25 bps/hr. Verify this matches HL contract's actual cap.
5. **Per-strategy sizing**: T1 strategies are 24-72h holds — max funding drag ~10-30 bps/trade. T2 is 4h — funding ~1-3 bps. T3 is 72h — funding ~30 bps (most sensitive).
6. **Portfolio simulation**: combine T1.1-T1.5 into a single simulated portfolio. Compute Sharpe of the BLEND (not individual sleeves) — diversification could lift or sink overall Sharpe vs the per-cell sum.

---

## NEXT-WAVE RESEARCH PRIORITIES (deferred from this session)

1. **N1 (liq cascades)** — pull Binance/Bybit `forceOrders` history to bypass HL data gap
2. **HL L2 orderbook** — raw S3 archive is downloaded but unparsed; could unlock microstructure features
3. **N12 calendar bias matrix** — TR session flags already in panel; haven't tested day-of-week × hour-of-day grid
4. **Cross-venue execution** — when HL basis is extreme, executing on both sides (long HL + short Binance perp) hedges market risk
5. **N3 refinement** — current basis-carry uses 24h asof-join; could refine with 1h granularity + dynamic threshold
6. **Meta-classifier deepening** — W3 showed BTC/ETH 15m has measurable AUC edge; build sized strategies from top features (sms_liquidity_dn, rsi_14, ema_stack_score appeared in top-20 importances)

---

## DELIVERABLES IN THIS DIRECTORY

```
strategy_lab/hl_research_2026_05_26/
├── MASTER_PLAN.md               — initial research plan
├── INDICATOR_REGISTRY.md         — 120+ indicators cataloged
├── HL_DATA_AUDIT.md              — data schema + gaps
├── EXISTING_HL_STRATS.md         — V52 + Strategy C catalog
├── WAVE1_FEATURES.md             — feature panel inventory
├── WAVE1_ENGINE.md               — HL engine smoke-test
├── build_hl_panel.py             — feature panel builder (1082 lines)
├── hl_engine.py                  — HL backtest engine (763 lines)
├── MASTER_TABLE.csv              — 790 strategies, canonical schema
├── MASTER_TABLE.md               — top-30 ranked + deploy candidates
├── PAPER_DEPLOY_CANDIDATES.md    — THIS FILE
├── panels/                       — 24 feature panels (143 cols × asset × TF)
│   ├── hl_panel_{BTC,ETH,SOL}_{5m,15m,1h,4h}.parquet
│   ├── hl_native_panel_{BTC,ETH,SOL,HYPE}_{15m,1h,4h}.parquet
│   └── _panels_summary.csv
└── wave2/
    ├── W2a_liq_cascade.{py,md,csv}      — N1 rejected
    ├── W2b_funding_basis.{py,md,csv}    — N3 STRONG ⭐
    ├── W2c_leadlag_pairs.{py,md,csv}    — N5+N11 rejected
    ├── W2d_cyclops_markov.{py,md,csv}   — N9+N4 weak
    ├── W2e_sms_regime.{py,md,csv}       — SMS 4h SOL only
    ├── W3_walkforward_results.csv       — meta-classifier
    ├── W3_feature_importance.csv        — permutation-importance
    ├── W3_discovery_strategies.csv      — top-feature single-rule strategies
    └── aggregate_results.py             — schema-adaptive aggregator
```

---

**Recommended next conversation**: pick one of T1/T2/T3 to deploy first. Recommend **T1.1 ETH 24h Basis z1.5** as the standalone first paper-deploy candidate — best Sharpe + only one passing all 5 gates with n>100.
