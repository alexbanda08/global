# Strategy Lab — Context Snapshot (2026-04-22)

Resume file for a fresh Claude session. Everything below was compiled by scanning the repo, engine, strategies, reports and results folders.

---

## 1. Engine (`strategy_lab/engine.py` — 343 lines)

- Wrapper over **vectorbt 0.28.x**, look-ahead-safe.
- Execution: **entries/exits shifted by +1**, fills at **next-bar OPEN**.
- Costs: `FEE=0.001` (Binance spot taker, per side), `SLIP=0.0005` (5 bps).
- Portfolio alloc defaults: BTC 0.50 / ETH 0.30 / SOL 0.20, `TOTAL_CAPITAL=10_000`.
- Key funcs: `load()`, `run_backtest()`, `extract_metrics()`, `combined_equity()`, `portfolio_metrics()`, `walk_forward_splits()`.
- Supports long+short via `short_entries` / `short_exits`. Single position per symbol.

> Hyperliquid-perps target costs used in V23+: **0.045% taker/side, 3 bps slippage, 3× leverage cap**. Not hardcoded into engine.py — applied per-run.

---

## 2. Data inventory

- `data/binance/parquet/` — **5 coins × 5 timeframes** (15m, 30m, 1h, 2h, 4h): BTC, ETH, SOL, AVAX, DOGE.
- `data/BTCUSDT/` — 4h + 5m CSV.
- `resources/data/` — OHLCV CSV for BTC/ETH/SOL/DOGE 4h, 2022-11 → 2026-03.
- `strategy_lab/features/` — pre-computed feature parquets BTC/ETH/SOL 1h+15m.
- `strategy_lab/features/multi_tf/` — multi-timeframe feature store.
- `data/coinapi/` — liquidations, trades, micro-features.
- TON/LINK/INJ/SUI data referenced in V23-V34 runs but **not in parquet/** (fetched elsewhere; confirm before new sweeps).

---

## 3. Strategy files shipped

**Core library** (`strategies_*.py`): base + v2..v12, v19_grid, v20_trendfollow. ~2 450 lines total.
**Hunt files** (`v*_hunt.py` / `v*_*.py`): 18 files covering fade, ML-rank, pairs, XSM, robustness, leverage, long-short, overfitting audit, cross-reference, hybrid leverage.
**Run drivers**: 47 `run_v*.py` files (v3 → v34).

### Families catalogued (34 strategies in STRATEGY_CATALOG.pdf)

| Family | Versions | Role |
|---|---|---|
| BB-Break L+S | V23, V34 | Trend breakout (DOMINANT winner) |
| HTF Donchian | V27, V34 | Trend follow |
| Range Kalman LS | V23 | Mean reversion on range |
| Keltner/ADX | V23 | Trend + vol filter |
| CCI Extreme Rev | V30 | Mean-reversion in low-ADX |
| TTM Squeeze Pop | V30 | Vol-expansion break |
| SuperTrend Flip | V30 | Trend switch |
| VWAP Z-Fade | V30 | Intraday mean-rev |
| Lateral BB Fade | V29 | Range fade (↘ broke in 2025) |
| Trend-Grade MTF | V29 | Regime filter |
| Regime Switch | V29 | Router |
| ORB, Seasonality, Sweep, LiqSweep, OB, MSB, Engulf, Div, Squeeze | V24-V27 | Mostly archived |
| Connors RSI | V30 | BUST on crypto |
| Keltner Pullback 15m | V33 | BUST (fees eat edge) |

---

## 4. THE final live portfolio (USER side 70%)

| # | Coin | Family | Lev | Params |
|---|---|---|---:|---|
| 1 | SOL | BBBreak_LS (V34) | 3× | `n=20 k=2.0 regime_len=200` |
| 2 | DOGE | HTF_Donchian (V34) | 3× | `donch_n=20 ema_reg=100` |
| 3 | ETH | CCI_Extreme_Rev (V30) | 3× | `cci_n=20 cci_thr=200` |
| 4 | AVAX | BBBreak_LS (V34) | 3× | same schema as #1 |
| 5 | TON | BBBreak_LS (V34) | 3× | same schema as #1 |

Exits: `tp_atr=10, sl_atr=2.0, trail_atr=6.0, max_hold=30`. Risk 5% at stop. Equal-weight 20% per sleeve.

MY side (30%): V24 multi-filter XSM + V15 balanced + V27 L/S (from V35 cross-reference).

---

## 5. Audit methodology (V31/V32/V33/V34)

5-test suite, all must pass:
1. **Per-year breakdown** — max single-year share ≤ 0.5 of cum log-return, neg years ≤ 2.
2. **Parameter plateau** — ≥ 60% of neighbor cells positive.
3. **Randomized-entry null** (n=100) — actual beats ≥ 80% of trials.
4. **MC bootstrap** (monthly, n=1000) — 5%-ile CAGR reported.
5. **Deflated Sharpe** (N_trials ≈ 2000) — DSR ≥ 0.9.

**Survival rate:** 11/24 across V31+V32+V33 (~46%).

Infamous casualties: SUI Lateral_BB_Fade 1h (+105% OOS → -79% live), Keltner_Pullback 15m (fees). V33 creative/scalping round = 0/7 pass.

---

## 6. Untapped / in-flight directions

- **Kronos foundation model** (`external/Kronos/`) — MIT OHLCV→OHLCV transformer, sniff-tests done on CPU. Intended use: bear filter on V24, or XSM ranker. Fine-tune gate = OOS corr ≥ 0.10.
- **V35 cross-reference** — 70/30 USER/MY hybrid shown Pareto-superior.
- **V36 hybrid leverage** — static, vol-scaled, DD-based leverage sweeps. Code exists, grid not yet exhaustive.
- **IAF multi compare** + **NATIVE_DASHBOARD.html** — long-only sanity + unified dashboard.
- **Kronos fine-tune** — not started (Binance 4h × 8 coins, ~135k samples).

---

## 7. Proposed new-approach angles (for next round)

Priorities ranked by expected-edge / info gain. Each is a V37+ candidate.

1. **V37 — Kronos-as-filter**. Require `kronos_5bar_pred > 0` on every BB-Break long entry and `< 0` on shorts; fine-tune on Binance 4h first. Gate by 5-test audit.
2. **V38 — Vol-of-vol regime router**. Route between BBBreak (trend regime) and CCI fade (chop regime) using realised vol percentile rank + ADX. Current V29 regime-switch was unclean; rebuild with tighter gates.
3. **V39 — Cross-asset leading indicators**. Use BTC dominance, ETH/BTC ratio, funding-rate spread and OI deltas (coinapi data) as regime filters on alt sleeves.
4. **V40 — Risk-parity sizing**. Replace equal-weight with inverse-vol or min-variance monthly rebalance on the 5 sleeves. Compare vs current equal-weight 20%.
5. **V41 — Meta-ensemble blender**. Soft-vote across 3 signals per coin (BBBreak, Donchian, CCI); position size = vote fraction. Should reduce whipsaw without new alpha hunt.
6. **V42 — Short-horizon probe on 30m/2h**. 15m was dead; 30m/2h untested with current audit bar. Could surface cheaper-to-trade signals.
7. **V43 — Event-driven overlays**. Use liquidation cluster events + funding resets from `coinapi/liquidations` as entry/exit triggers alongside current trend sleeves.
8. **V44 — Walk-forward re-optimisation cadence**. Current sweeps fix params once; test quarterly re-opt within the audit shell to see if it beats static.

Any of these should follow the GSD flow (`.planning/`): `/gsd-discuss-phase N` → `/gsd-plan-phase N` → `/gsd-execute-phase N`.

---

## 8. Fast lookup — where to find things

- Engine: `strategy_lab/engine.py`
- Portfolio construction: `strategy_lab/run_v34_portfolio.py`
- Cross-reference: `strategy_lab/v35_cross_reference.py`, `v36_hybrid_leverage.py`
- Audit templates: `run_v31_overfit_audit.py`, `run_v32_core_audit.py`, `run_v34_audit.py`
- Signal defs: `run_v30_creative.py` (CCI, SuperTrend, Squeeze, VWAP-Z), `run_v34_expand.py` (BBBreak_LS, HTF_Donchian_LS)
- Reports index: `strategy_lab/reports/` (38 PDFs + MDs)
- Pine exports: `strategy_lab/pine/`
- Kronos: `external/Kronos/`
