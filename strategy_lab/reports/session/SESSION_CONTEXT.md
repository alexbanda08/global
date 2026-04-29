# Strategy Lab — Session Context (Resume Here)

Last updated: **2026-04-22**. Start a new Claude session by feeding it this file.

---

## Project location
`C:\Users\alexandre bandarra\Desktop\global\`

## Overall goal
Find a robust, low-drawdown crypto strategy for BTC/ETH/SOL/... on a $10 k (or $600 small-capital) risk-adjusted demo portfolio. Deploy on Hyperliquid (0.015 % maker / 0.045 % taker fees) once validated.

---

## ⭐ THE FINAL PORTFOLIO (as of 2026-04-22)

**70 % USER 5-sleeve + 30 % MY V24 Multi-filter XSM** — hybrid of two independent research streams.

### USER side (70 %) — single-coin sleeves (from `DEPLOYMENT_BLUEPRINT.md`)

| Sleeve | Coin | Family | Lev | Signal spec |
|---|---|---|---:|---|
| 1 | SOL | BBBreak_LS (V34) | 3× | `run_v34_expand.sig_bbbreak_ls`  `n=20 k=2.0 regime_len=200` |
| 2 | DOGE | HTF_Donchian (V34) | 3× | `run_v34_expand.sig_htf_donchian_ls`  `donch_n=20 ema_reg=100` |
| 3 | ETH | CCI_Extreme_Rev (V30) | 3× | `run_v30_creative.sig_cci_extreme`  `cci_n=20 cci_thr=200` |
| 4 | AVAX | BBBreak_LS (V34) | 3× | same schema as #1 |
| 5 | TON | BBBreak_LS (V34) | 3× | same schema as #1 |

Exits: `tp_atr=10, sl_atr=2.0, trail_atr=6.0, max_hold=30`. Risk per trade 0.05 (5 % equity at stop).

### MY side (30 %) — V24 Multi-filter XSM

`strategy_lab/v23_low_dd_xsm.py::low_dd_xsm(mode="multi_filter", ...)`

- Universe: BTC · ETH · SOL · BNB · XRP · DOGE · LINK · ADA · AVAX (9 coins)
- Rank by 14-day return, equal-weight long top 4, weekly rebalance (Monday 00:00 UTC)
- Triple bear filter (flatten when ANY fires):
  - BTC < 100-day SMA
  - BTC 50-day SMA falling (1-day slope < 0)
  - Market breadth: fewer than 5 of 9 coins above their own 50-day SMA
- Leverage: 1× for BALANCED tier, 1.5× for AGGRESSIVE tier

### Expected performance (2023-04 → 2026-03 window, $10 k start)

| Tier | CAGR | Sharpe | MaxDD | Calmar | Final on $10k |
|------|-----:|-------:|------:|-------:|--------------:|
| SAFE (USER 3× + V24 DYN_VOL 0.40) | +75 % | **1.90** | **−20 %** | 3.69 | $53k (3 yr) |
| BALANCED (USER 3× + V24 1.0×) | +86 % | **1.92** | −22 % | 3.94 | $66k (3 yr) |
| AGGRESSIVE (USER 5× + V24 1.25×) | +131 % | 1.81 | −34 % | 3.79 | $124k (3 yr) |

### Small-capital deployment ($100 each sleeve = $600 total)

See `newstrategies/IMPLEMENTATION_GUIDE.md`. Hyperliquid minimum order is $10; at 3× leverage each USER sleeve position is $30–60, XSM sleeve positions are ~$25 each.

---

## Deliverables (live copies in `C:\Users\alexandre bandarra\Desktop\newstrategies\`)

1. **IMPLEMENTATION_GUIDE.md** — complete deploy recipe + tier selection + Hyperliquid setup + monitoring + kill switches
2. **CROSS_REFERENCE_VERDICT.pdf** — side-by-side analysis vs user's DEPLOYMENT_BLUEPRINT, confirms 70/30 hybrid is Pareto-superior
3. **OVERFITTING_AUDIT.pdf** — 5-test robustness audit (per-year, param plateau, random null, MC bootstrap, deflated Sharpe). All 3 strategies ROBUST.
4. **DEPLOY_GUIDE.pdf** — small-capital + leverage guide (before V24 was added)
5. **LOW_DD_VERDICT.pdf** — V24 multi-filter vs all low-DD variants
6. **NEW_IDEAS_VERDICT.pdf** — V19 grid + V20 trend-follow + V21 leverage sweep
7. **STRATEGY_CATALOG.pdf** — 34 strategies cataloged with entry/exit/stop/strengths/flaws
8. **IAF_MULTI_COMPARISON.html** — IAF's own long-only sanity check (4 strategies)
9. **NATIVE_DASHBOARD.html** — **IAF dashboard driven by OUR native numbers** (new default display)

---

## Data inventory (`data/`)

| Source | Path | Content | History |
|---|---|---|---|
| Binance spot klines | `data/binance/parquet/{SYM}/{TF}/year=*/part.parquet` | OHLCV 1m/5m/15m/1h/4h/1d | BTC/ETH 2017-08+, SOL 2020-08+, BNB 2017-11+, XRP 2018-05+, ADA 2018-04+, LINK 2019-01+, DOGE 2019-07+, AVAX 2020-09+ (1h & 4h only for the 6 new pairs), TON/SUI added for V34 |
| Binance futures metrics | `data/binance/futures/metrics/{SYM}/parquet/` | OI, LS ratio, taker ratio (5m) | 2020-09 → present |
| Funding rate | `data/binance/futures/fundingRate/{SYM}/parquet/` | 8h funding | 2020-01 → present |
| Premium index 1h | `data/binance/futures/premiumIndexKlines/` | Basis | 2019-09 → present |
| CoinAPI liquidations (1m) | `data/coinapi/liquidations/{SYM}/` | Per-minute liq events | 2023-01 → 2026-04 |
| Per-strategy features | `strategy_lab/features/multi_tf/{SYM}_{TF}.parquet` | used by `run_v34_expand._load` | 2020-01+ |

---

## Validated winners

| ID | Strategy | TF | Coin(s) | Net CAGR | Sharpe | MaxDD | Audit |
|---|---|---|---|---:|---:|---:|---|
| V4C | Range Kalman | 4h | BTC | +39.6 % | 1.32 | −28.8 % | 5/5 robustness |
| V3B | ADX Gate | 4h | ETH | +56.2 % | 1.26 | −33.8 % | 5/5 robustness |
| V2B | Volume Breakout | 4h | SOL | +104.7 % | 1.35 | −51.5 % | 4/5 |
| V13A | Range Kalman | 1h | ETH | +19.3 % | 0.93 | −23.2 % | 4.5/5 |
| **V15 Balanced** | XSM k=4 lb=14d | 4h | 9-coin basket | +104 % | 1.53 | −46 % | V30 5/5 ROBUST (deflated SR 1.33) |
| **V24 Multi-filter** | XSM + triple bear | 4h | 9-coin basket | +84 % | **1.50** | **−39 %** | V30 5/5 ROBUST (deflated SR **1.47**) |
| **V27 L/S 0.5×** | XSM long-short hedged | 4h | 9-coin basket | +48 % | 1.31 | **−25 %** | V30 5/5 ROBUST |
| **USER 5-sleeve** | BBBreak_LS + Donchian + CCI | 4h | SOL/DOGE/ETH/AVAX/TON | +78 % | 1.65 | −25 % | V32/V34 audit |
| **HYBRID 70/30** | USER + V24 combined | 4h | 5 USER + 9 XSM coins | +80 % | **1.87** | **−23 %** | Cross-ref on V35 |

Correlation USER ↔ MY V24 = 0.35 (genuine diversification).

## Failed approaches (don't retry)

- 15m rule-based (V6-V10): fees eat alpha
- V11 LightGBM ML on 15m: OOS AUC 0.50 (random)
- V8 Triple SuperTrend stack: 0 trades in 4 years (over-filtered)
- V9 multi-TP ladder wraps: raise WR but kill CAGR (frontier tradeoff, no improvement)
- V10 orderflow filters (funding/OI/L/S/liq): all fail at 4h
- V11 regime ensemble: over-filters on top of already-regime-filtered baseline
- V13B/V13C at 1h: fees eat edge
- V16 ML-rank XSM: simple beats smart (Sharpe 1.37 < plain V15 1.86)
- V17 pairs trading: raw edge exists but DD −94 %, not deployable unhedged
- V19 grid trading: fees kill at 4h sideways regimes
- V20 new trend-follow (HA-ST, OTT, DEMA-Ichimoku, Squeeze-Ichimoku): < 3 %/yr CAGR everywhere
- V25 DD circuit breaker: over-halts, sits flat forever

---

## Code map (how to drive / extend)

### Simulators (the vector engine)

| File | Role |
|---|---|
| `strategy_lab/portfolio_audit.py` | vbt-free single-position simulator (our baseline) |
| `strategy_lab/advanced_simulator.py` | simulator with TP1/TP2/TP3 ladder + ratcheting SL + trail |
| `strategy_lab/v23_low_dd_xsm.py` | **V24 MULTI-FILTER XSM** (current champion MY-side engine). Function: `low_dd_xsm(mode="multi_filter", ...)` |
| `strategy_lab/v29_long_short_deep.py` | **V27 L/S XSM**. Function: `long_short_backtest(...)` |
| `strategy_lab/v15_xsm_variants.py` | generic XSM engine (momentum / composite / vol-adj / long-short) |
| `strategy_lab/run_v34_portfolio.py` | **USER 5-sleeve loader** — rebuilds equity per sleeve from pickled sweeps |
| `strategy_lab/run_v34_expand.py` | USER signal functions: `sig_bbbreak_ls`, `sig_htf_donchian_ls`, `sig_pair_ratio_revert` |
| `strategy_lab/run_v30_creative.py` | USER creative signals: CCI, VWAP_Zfade, SuperTrend, TTM_Squeeze |
| `strategy_lab/run_v16_1h_hunt.py` | shared `simulate()` harness + `metrics()` for USER side |

### Cross-reference & sweeps

| File | Role |
|---|---|
| `strategy_lab/v35_cross_reference.py` | build hybrid USER+MY portfolios; compute correlation matrix + combined metrics |
| `strategy_lab/v36_hybrid_leverage.py` | 102-config leverage sweep on hybrid (static, DYN_VOL, DYN_DD) |
| `strategy_lab/v30_overfitting_audit.py` | 5-test overfitting audit. Function: `main()` runs V15/V24/V27 |
| `strategy_lab/v18_robustness.py` | random 2-year windows + parameter-epsilon on V15 champion |

### Dashboard pipeline (NEW 2026-04-22)

| File | Role |
|---|---|
| `strategy_lab/native_to_iaf.py` | **adapter** — converts our (equity, trades) into IAF `Backtest` objects |
| `strategy_lab/run_dashboard.py` | **unified entrypoint** — `show([(label, eq, trades), ...])` → HTML dashboard |
| `strategy_lab/iaf_multi_compare.py` | IAF port of 4 strategies (demo; uses IAF's own vector backtest, not our sim) |

### PDF / MD builders

| File | Role |
|---|---|
| `strategy_lab/build_deploy_guide.py` | → `DEPLOY_GUIDE.pdf` |
| `strategy_lab/build_leverage_verdict.py` | → `NEW_IDEAS_VERDICT.pdf` |
| `strategy_lab/build_low_dd_verdict.py` | → `LOW_DD_VERDICT.pdf` |
| `strategy_lab/build_overfitting_pdf.py` | → `OVERFITTING_AUDIT.pdf` |
| `strategy_lab/build_cross_ref_pdf.py` | → `CROSS_REFERENCE_VERDICT.pdf` |
| `strategy_lab/build_strategy_catalog.py` | → `STRATEGY_CATALOG.pdf` |

### Live forward-test (ready but not activated)

| File | Role |
|---|---|
| `strategy_lab/live_forward.py` | polls Binance REST, runs signals, maintains paper state (USER sleeves only so far) |

---

## How to use the new dashboard (from next session)

```python
# In any notebook / script, after building your equity + trades:
from strategy_lab.run_dashboard import show

show([
    ("Portfolio A", eq_a, trades_a),   # trades optional (None OK)
    ("Portfolio B", eq_b, None),
], output_html="strategy_lab/reports/TEST.html")
```

→ self-contained HTML at `newstrategies/NATIVE_DASHBOARD.html` (auto-copied).

Rebuild the default 4-strategy dashboard from saved V35 equities:

```bash
python -m strategy_lab.run_dashboard
```

---

## Key assumptions & fee model (important for next session)

- **Hyperliquid fees**: 0.015 % maker / 0.045 % taker. USER sleeves + XSM both use Hyperliquid as the target venue.
- **Slippage**: 3 bps (0.03 %) in USER sims; 0 bps in XSM sims (limit-order assumption).
- **Fill model**: next-bar-open fills everywhere. No intrabar look-ahead.
- **ATR sizing (USER side)**: `size = min(risk_dollars/stop_dist, leverage*equity/price)`.
- **XSM sizing (MY side)**: weekly equal-weight, 100%/top_k per coin × leverage.
- **USER native sim**: long AND short (BBBreak_LS, Donchian_LS). XSM V27 too.
- **IAF port**: long-only + fixed SL/TP — NOT comparable to native; use for UI only.

---

## Things to tell the new session (copy-paste)

```
Read strategy_lab/reports/SESSION_CONTEXT.md.
Final portfolio = 70% USER 5-sleeve + 30% V24 Multi-filter XSM @ 1x (BALANCED tier).
Backtest: CAGR +80-86%, Sharpe 1.87-1.92, MaxDD -22%, Calmar 3.5-3.9 (on 2023-04 to 2026-03).
Deploy guide: newstrategies/IMPLEMENTATION_GUIDE.md.
Dashboard: python -m strategy_lab.run_dashboard  (writes newstrategies/NATIVE_DASHBOARD.html).
```

---

## Next steps (if you come back)

1. Wire the USER 5-sleeve per-coin trade logs into `run_dashboard.show()` so the dashboard has per-trade drill-down for each sleeve (currently only equity curves).
2. Build `live_forward_xsm.py` — weekly rebalance runner that mirrors `v23_low_dd_xsm.low_dd_xsm()`, same as existing `live_forward.py` is for USER side.
3. Start Hyperliquid testnet paper trading (4 weeks of SAFE tier before mainnet).
4. Optional: port `sig_cci_extreme`, `sig_supertrend_flip`, `sig_ttm_squeeze`, `sig_vwap_zfade` from V30 pickles into live-code form (currently loaded from cached pickles).
5. Optional: redo `v35_cross_reference.py` periodically as new OOS data rolls in (every 3 months) to confirm the hybrid edge holds.

---

## Full R&D trail (one-liners)

| Round | Result |
|---|---|
| V1-V13 | early strategies, validated V4C/V3B/V2B at 4h + V13A at 1h |
| V14 | XSM breakthrough — Sharpe 1.60, CAGR +158 %, but DD -58 % |
| V15 | XSM sweep → balanced k=4 lb=14d rb=7d → **Sharpe 1.86**, DD -48 % |
| V16 | ML-rank (GBR) — FAILED, Sharpe 1.37 < plain V15 |
| V17 | Pairs trading — raw edge but DD -94 %, unhedged not deployable |
| V18 | Robustness on V15: 100/100 windows profitable, 72/72 params profitable |
| V19 | Grid trading — FAILED at 4h (fees) |
| V20 | Heikin-ST / OTT / DEMA-Ichimoku / Squeeze-Ichimoku — FAILED |
| V21 | Leverage sweep — 70/30 hybrid best Sharpe 1.88 |
| V23-V28 | Low-DD family → **V24 multi-filter** DD -39 %, Sharpe 1.80 |
| V29 | L/S deep dive: short-only has no alpha (Sharpe -0.05), net V27 = beta reduction |
| V30 | Overfitting audit 5 tests: V15/V24/V27 all ROBUST (deflated SR +0.81 to +1.47) |
| V32/V34 | USER side: 16 audited single-coin sleeves, 5-sleeve live portfolio |
| V35 | Cross-reference USER ↔ MY: correlation 0.35, hybrid 70/30 superior on every axis |
| V36 | Hybrid leverage + DYN_VOL: Sharpe 1.90 at DD -20 % (SAFE tier) |
| IAF | Port to `investing-algorithm-framework` + native→IAF dashboard adapter |

## Bottom line

**Ship the BALANCED hybrid tier (70 % USER + 30 % V24 XSM @ 1.0×). Start on Hyperliquid testnet. Scale to mainnet only after 4 clean weeks.**

Everything is reproducible from the files listed above. The dashboard entrypoint (`python -m strategy_lab.run_dashboard`) is the new default for viewing any test going forward.
