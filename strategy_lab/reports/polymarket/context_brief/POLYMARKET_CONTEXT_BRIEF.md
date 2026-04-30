# Polymarket UP/DOWN 5m & 15m — Context Brief

Project state snapshot for resuming the search for an edge on Polymarket BTC Up/Down markets. Generated 2026-04-27, last updated **2026-04-29 (V3 portfolio strategy discovered, 10-gate validation passed, deploy guide ready)**.

---

## ⚡ HEAD STATE (read first) — 2026-04-29

> **V3 PORTFOLIO STRATEGY READY TO SHIP.** Per-asset tuned 3-sleeve sniper (BTC q10 + ETH q5 + SOL q15 multi-horizon) on 5m markets. Forward-walk holdout +32% ROI, 0 down days, 10/10 validation gates passed. Deploy guide: [`../01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md`](../01_deployable/TV_STRATEGY_V3_PORTFOLIO_DEPLOY_GUIDE.md).
>
> Read first: [`../../session/SESSION_HANDOFF_2026_04_29.md`](../../session/SESSION_HANDOFF_2026_04_29.md) for the full state.
>
> **V3 deployment matrix (forward-walk-validated, 10-gate-passed):**
>
> | Sleeve | Magnitude | Multi-horizon | Entry | Exit | HO ROI |
> |---|---|---|---|---|---|
> | BTC × 5m | q10 (top 10%) | no | maker @bid+1¢ wait 30s, fb taker | HEDGE_HOLD hold-to-resolution | **+47.1%** (n=36) |
> | ETH × 5m | q5 (top 5%) | no | same | same | **+37.6%** (n=26) |
> | SOL × 5m | q15 (top 15%) | **yes** (ret_5m, ret_15m, ret_1h all same sign) | same | same | **+54.9%** (n=23) |
> | **PORTFOLIO** | combined | — | — | — | **+32.16% top-of-ask / +27.09% L10-realistic / +33.47% with maker overlay** |
>
> Spread<2% pre-entry filter on top. 15m markets dropped (adding 15m sleeves drops portfolio HO ROI 32% → 26%).
>
> **What was tested + ruled out this session (12 paradigms):**
> - V2 calibrated-probability stack (prob_a/b/c/stack): killed in forward-walk (overfits 7-day data)
> - Synthetic covered call (long perp + short YES, 1×–60×): no edge in steady-state, leverage adds nothing
> - Maker-on-both-sides spread provision: adverse selection dominates, ROI -5% to -21%
> - Cross-asset BTC-leader: 50% hit (random), no predictive power on 5m/15m alts
> - Vol-regime conditional sleeves: minor edge (+3pp at most), not worth conditioning
> - Entry-timing delay (30/60/120s into window): loses 24pp ROI vs delay=0
> - Take-profit / stop-loss / trailing-stop / opposite-flip exits: ALL hurt vs hold-to-resolution
>
> Full evidence: [`../RESEARCH_DEEP_DIVE_2026_04_29.md`](../RESEARCH_DEEP_DIVE_2026_04_29.md) and per-item reports ([`../COVERED_CALL_BACKTEST.md`](../COVERED_CALL_BACKTEST.md), [`../MAKER_BOTH_SIDES_BACKTEST.md`](../MAKER_BOTH_SIDES_BACKTEST.md), [`../CROSS_ASSET_LEADLAG.md`](../CROSS_ASSET_LEADLAG.md), [`../SIM_VS_LIVE_RECONCILIATION.md`](../SIM_VS_LIVE_RECONCILIATION.md)).
>
> **Sim-vs-live mystery closed:** the 30-pp gap between backtest and live VPS3 is decomposed in [`../SIM_VS_LIVE_RECONCILIATION.md`](../SIM_VS_LIVE_RECONCILIATION.md). Causes: 50% feed direction agreement on small |ret_5m| (vanishes at q10) + HYBRID bid-exit branch ($1.3k cost). Both addressed in `docs/VPS3_FIX_PLAN.md`. **Simulator is honest.**
>
> **Next session focus:** ship V3 to VPS3 (TV agent's task) OR continue research. Re-validate V3 + V2 on 30 days when collector reaches that (~2026-05-23).

---

## SUPERSEDED — Pre-V3 deployment matrix (2026-04-28)

Single-tier sniper (q10 5m / q20 15m), no per-asset magnitude tuning. **V3 portfolio above replaces this.**

| Asset × TF | Signal | Entry | Exit | Holdout ROI |
|---|---|---|---|---|
| BTC × 5m | q10 | taker | hedge-hold rev_bp=5 | +35.5% |
| BTC × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +25.2% |
| ETH × 5m | q10 + btc-confirm | taker | hedge-hold rev_bp=5 | +24.8% |
| ETH × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +27.8% |
| SOL × 5m | q10 + btc-confirm | taker | hedge-hold rev_bp=5 | +25.6% |
| SOL × 15m | q20 | maker hybrid | hedge-hold rev_bp=5 | +24.6% |

Cross-asset average ~27% HO ROI. **V3 portfolio averages +32% on the same forward-walk** with tighter per-asset gating + multi-horizon-on-SOL.

---

## Historical context (pre-v3 baseline)

The sections below describe how this brief originally bootstrapped the project on 2026-04-27 morning, before the v3 strategy was found. Kept for archival reference. **For current state, use the head links above.**

> **Venue scope.** This brief is *only* about Polymarket Up/Down binary markets. The Hyperliquid futures work is a **separate project** running on the VPS (V52 champion + perps research, files prefixed `run_v52_hl_*` / `hyperliquid/*`). Do not confuse the two — Polymarket has YES/NO tokens priced 0–1 with binary payout; Hyperliquid is leveraged perps with mark price + funding.

---

## 1. How the markets work (verified from data)

Source of truth: `KRONOS_POLYMARKET_FINAL_REPORT.md` §2 + `polymarket_explore*.sql`.

- Each market is a **fully-collateralized binary option**: `P(YES) + P(NO) = $1.00`. YES price = market's implied probability of UP.
- A "5m market" is named by the **price-tracking window**, not the lifespan. The market opens **~3 hours before resolution**, sitting at 0.505/0.495 with no real flow.
- All real action happens in the final window: `window_start = resolve_unix - 300` (5m markets) or `- 900` (15m). 1,000–1,500 snapshots/min once it goes hot.
- Inside the window, prices swing violently (e.g. 0.42 → 0.67 → 0.41 → 0.98 in seconds).
- Typical entry ask at window open: **~0.51** with a **1¢ spread**.
- Resolution is visible directly from final snapshots — no Binance kline lookup required.
- Fees: **2% on winnings** (resolution payout), ~0.3% taker on early CLOB sells.
- **Break-even hit-rate: ~53%** (fees + spread + half a tick of slippage).

## 2. The engine that already exists

### 2.1 Data pipeline
- **Collector**: `/opt/storedata` running on a Contabo VPS (IPv6), writing to Postgres. Tables: `markets`, `orderbook_snapshots_v2`. Captured **3.84M snapshots / 1,542 markets** in a 30h window (Apr 22 16:47 → Apr 23 22:04). The collector lives only on the VPS — no copy in this repo.
- **SQL extractors** (run against the VPS Postgres to produce the local CSVs):
  - `polymarket_extract_markets.sql` / `polymarket_extract_markets_v2.sql` — pulls resolved BTC 5m/15m markets with entry quotes + outcome.
  - `polymarket_extract_trajectories.sql` — builds 10s YES/NO bid/ask first/last/min/max bucket rows.
  - `polymarket_explore.sql` … `polymarket_explore5.sql` — schema and data sanity probes.
- **Local extracts** in `strategy_lab/data/polymarket/`:
  - `btc_markets.csv` — 444 resolved BTC markets (333× 5m + 111× 15m) with entry quotes & outcome.
  - `btc_trajectories.csv` — 20,272 rows, 10-second buckets per market with YES/NO bid/ask first/last/min/max.
- **BTC reference data**: `kronos_ft/data/BTCUSDT_5m_3y.csv` (315k bars, 2023-04→2026-03) plus an Apr top-up file.

### 2.2 Signal model
- **Kronos (fine-tuned)** is the current predictive layer. Config: `strategy_lab/kronos_ft/config_btc_5m_3y.yaml`. Model weights: `D:/kronos-ft/BTCUSDT_5m_3y_polymarket_short/basemodel/best_model/`.
- Inference script: [strategy_lab/kronos_infer_polymarket.py](strategy_lab/kronos_infer_polymarket.py) — averages 30 stochastic samples, predicts 3 bars (5m / 10m / 15m horizons).
- Prediction file: `results/kronos/kronos_polymarket_predictions.csv` (one row per market, columns `pred_dir_5m`, `pred_dir_15m`, `pred_ret_5m`, `pred_ret_15m`).

### 2.3 Backtest engine (Polymarket-specific — not Hyperliquid)
Both scripts are unambiguously Polymarket Up/Down: they consume YES/NO token columns (`entry_yes_ask`, `entry_no_ask`), use 0–1 prices, model 1.0/0.0 binary payouts, and apply the 2% Polymarket fee on winnings. No leverage, no funding rate, no perp mark price — none of the Hyperliquid concepts appear.

- [strategy_lab/polymarket_backtest_v1.py](strategy_lab/polymarket_backtest_v1.py) — Monte-Carlo over a hypothetical signal at a chosen accuracy (no exit logic). Hold-to-resolution only.
- [strategy_lab/polymarket_backtest_real.py](strategy_lab/polymarket_backtest_real.py) — full grid runner against the real trajectories. Supports:
  - S0 hold-to-resolution
  - S1 target exit ∈ {0.55…0.90}
  - S2 stop loss ∈ {0.20…0.40}
  - S3 target+stop combos
  - S4 trailing stops {5%…20%}
  - S5 time exits at bucket N
  - S6 entry-price filter (skip if entry > 0.55)
  - S7 confidence filter (top X% of |pred_ret|)
  - Walks 10s buckets with stop-before-target intra-bucket convention.
- Output: 56-strategy grid in `results/polymarket/strategy_grid_all.csv` + markdown reports.

### 2.4 Reference architecture
- [strategy_lab/reports/building_cyclops_style_bot.md](strategy_lab/reports/building_cyclops_style_bot.md) — full topology guide (data subsystem, indicator zoo, regime detector, weighted voting, MEGA bonus, SmartKelly sizing, execution via `py-clob-client`, watchdog, 12-week build plan). This is the design north star.

### 2.5 Live-execution gap
**There is no live execution code yet.** Everything in 2.1–2.3 is offline: SQL extracts → CSVs → Kronos inference → backtest grid. The CLOB WebSocket / `py-clob-client` integration described in `building_cyclops_style_bot.md` is a design sketch, not implemented in this repo.

## 3. What worked and what didn't (Apr 22–23 real test)

### 3.1 Headline numbers
- Kronos accuracy on the 444-market live window: **5m = 52.9% / 15m = 51.4%** (break-even ≈ 53%).
- Best real strategy: **S3 Target 0.70 + Stop 0.35 → +$7.84 over 444 bets**, but 95% CI is **[-$11, +$28]** — every positive grid cell crosses zero.
- Monte-Carlo at the *fine-tune* accuracy (69%) shows +$79 / 444 bets in 100% of 10k trials. So mechanics are sound, **the signal is what's missing**.

### 3.2 What helped (small)
- Wide stops (0.35–0.40): cut tail losses without killing wins.
- Tight target on 15m (S1 @ 0.55): **+$5.52, 71% win** on 38 of 111 markets — only structural positive cell on 15m, but n is small.

### 3.3 What hurt
- Trailing stops (any %) — whipsawed by intra-bucket volatility.
- Time exits — locked in transitional prices mid-move.
- Tight targets on 5m — booked tiny wins, kept tail risk.
- Confidence filter on 5m — hurt PnL.

### 3.4 Root cause of the lost edge
- OOD degradation: training cutoff 2026-03-31, tested 2026-04-22+. Monthly Kronos accuracy was already trending down (Jan 60% → Feb 59% → **Mar 54%**).
- Naive-momentum baseline on the same Jan–Mar filter hit **52%**, suggesting much of Kronos's earlier "edge" was regime-fit, not generalizable structure.

## 4. Where to push next (priority order)

1. **Don't rebuild the engine — feed it a better signal.** Backtest harness, data, and exit grid all work. The only missing piece is a directional signal that holds ≥56–58% on a hold-out month.
2. **Add a momentum baseline column** to `btc_markets.csv` (sign of last 5m / 15m return) and re-run the grid; if it ties Kronos, the model isn't paying for itself.
3. **Latency edge** (CYCLOPS Part 1): Polymarket reportedly lags Binance by 30–90s. Build a "Binance-leads-Polymarket" gate and only trade when the lag is open and directional. This is structural, not regime-dependent.
4. **Liquidations + book-imbalance signals** before retraining Kronos on April. The earlier deep work (`08_ROBUSTNESS_EXPANDED`, `02_REGIME_LAYER`) already has feature code we can reuse.
5. **Collect more data first.** 30h / 444 markets is too thin for any of these to clear a 95% CI. Let the VPS collector run 2–4 more weeks before committing to a retrain.
6. **Avoid**: another full Kronos fine-tune on the same shape of features — same OOD failure will recur.

## 5. Key files index

| Purpose | Path |
|---|---|
| Final investigation | `strategy_lab/reports/KRONOS_POLYMARKET_FINAL_REPORT.md` |
| 5m results | `strategy_lab/reports/POLYMARKET_BACKTEST_REAL.md` |
| 15m results | `strategy_lab/reports/POLYMARKET_BACKTEST_REAL_15m.md` |
| Combined | `strategy_lab/reports/POLYMARKET_BACKTEST_REAL_ALL.md` |
| Reference architecture | `strategy_lab/reports/building_cyclops_style_bot.md` |
| Backtest engine (real) | `strategy_lab/polymarket_backtest_real.py` |
| Backtest engine (MC) | `strategy_lab/polymarket_backtest_v1.py` |
| Kronos inference | `strategy_lab/kronos_infer_polymarket.py` |
| Markets CSV | `strategy_lab/data/polymarket/btc_markets.csv` |
| Trajectories CSV | `strategy_lab/data/polymarket/btc_trajectories.csv` |
| Postgres explore | `strategy_lab/polymarket_explore{,2,3,4,5}.sql` |
| Postgres extract — markets | `strategy_lab/polymarket_extract_markets.sql`, `..._v2.sql` |
| Postgres extract — trajectories | `strategy_lab/polymarket_extract_trajectories.sql` |

## 6. External reference: `aulekator/Polymarket-BTC-15-Minute-Trading-Bot`

GitHub: https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot — MIT license, ~178 stars, 4 commits (small/early). Targets the **same 15m BTC market** we're working on. Indexed full repo content into `aulekator/Polymarket-BTC-15-Minute-Trading-Bot — repo root` for follow-up search.

### 6.1 What's there
- 7-phase pipeline: data ingestion → NautilusTrader core → strategy brain (signals + fusion) → execution → monitoring → feedback (learning).
- **Data sources**: Binance WS, Coinbase REST, Fear & Greed + social sentiment, Solana RPC (experimental).
- **Signals**: spike detection, sentiment, price divergence (no LLM/ML predictor — heuristic).
- **Risk knobs (chosen, not derived)**: $1 max per trade, 30% stop loss, 20% take profit. Independent confirmation that wide stops are the right shape on this market — matches our S2 stop=0.35 finding.
- **Execution**: `execution/polymarket_client.py` wraps Polymarket CLOB API + `polymarket_client.py` order logic. `patch_gamma_markets.py` is a workaround for a known Gamma API bug.
- **Mode toggle**: `redis_control.py` switches sim/live without restart; `view_paper_trades.py` for paper P&L.
- **Monitoring**: Grafana dashboard JSON + Prometheus exporter — drop-in.
- **Feedback**: `feedback/learning_engine.py` is a placeholder (their words), not a working ML loop.

### 6.2 What's worth lifting (high → low value)
1. **`execution/polymarket_client.py`** — closes our biggest gap (no live execution). Read it, port the order placement + signing flow, throw away their strategy layer.
2. **`patch_gamma_markets.py`** — pre-debugged Polymarket API quirk; saves hours.
3. **`grafana/dashboard.json` + `monitoring/grafana_exporter.py`** — drop-in observability; matches what `building_cyclops_style_bot.md` recommends.
4. **`data_sources/news_social/` (Fear & Greed)** — free signal we don't have; cheap to bolt on as a regime filter.
5. **`redis_control.py` sim/live toggle pattern** — useful even if we don't adopt their main loop.

### 6.3 What to skip
- **NautilusTrader integration** — heavy, opinionated framework dependency for a 15m binary-option bot. Our current pandas/numpy backtester is simpler and validated; switching costs more than it earns.
- **Their signal stack** (spike/divergence/sentiment) — none claim measured edge in their README; reimplementing on top of Kronos+momentum+latency is more promising.
- **`feedback/learning_engine.py`** — placeholder, not real ML.
- **Solana data source** — marked experimental.

### 6.4 License & risk
MIT license — free to vendor or fork. Only 4 commits and no public backtest numbers, so treat it as a *reference implementation*, not a proven strategy. Validate every borrowed module against our own data before trusting it.
