# Session Handoff — 2026-05-05 (Polymarket UpDown work)

**Last touched:** 2026-05-05 ~22:30 CEST
**Owner:** alexandre.bandarra (laptop) + TV agent (VPS3 ops)
**State:** Inverse sleeves LIVE on VPS3 (paper-only, validation running). Phase 9 trade-flow signal discovered with caveat. Stop-loss path closed.

---

## 🚨 NEXT SESSION: START HERE

### Priority 1 — Validate Phase 9 lookahead (~30-60 min)

Phase 9 (Polymarket trade flow imbalance) showed **77.7% hit on 355 bets, +53.5% ROI** in this session. **BUT for 5m markets, the `poly_tfi_2m` feature consumes 40% of the window** (2 minutes of a 5-minute market). The strong hit rate may partly be a self-prediction — Polymarket trade flow in the first 2 minutes mostly reflects what BTC already did in those 2 minutes.

**Test required**: regress `outcome_up` on `[poly_tfi_2m, btc_ret_during_signal_window]`. If `poly_tfi_2m`'s coefficient survives controlling for BTC return, it's novel alpha. If it dies, Phase 9 is just an indirect BTC-momentum readout.

Files to use:
- `strategy_lab/data/meta_classifier/btc_trade_flow_v1.parquet` — Phase 9 features (4,673 × 9 cols)
- `data/v4/refresh_2026_05_02/btc_markets_minimal.csv` — universe with outcomes
- `strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv` — BTC 5m OHLCV through 2026-05-05 01:55 (CEST naive)
- Phase 9 builder: `strategy_lab/v4_signals/phase9_polymarket_trade_flow.py`
- Phase 9 report: `strategy_lab/reports/PHASE9_POLYMARKET_TRADE_FLOW.md`

### Priority 2 — Pull FRESH polymarket data from all VPS collectors

Existing local data is from `2026-05-02` (3 days stale). Tomorrow (May 6) the inverse sleeves complete their first full 24h cycle including the volume_INV_NIGHT activation window (UTC 1-5). To run all analyses on real liquidity with up-to-date data:

```bash
# VPS2 — book depth + trade flow data
ssh -i ~/.ssh/vps2_ed25519 root@'[2605:a140:2323:6975::1]' -- "<refresh script>"

# VPS3 — shadow trade resolutions including new inverse sleeves
bash strategy_lab/meta_classifier/refresh_and_analyze.sh
```

**Pull everything**:
- `orderbook_snapshots_v2` — for refreshed Phase 7 CLOB momentum features
- `trades_v2` — for refreshed Phase 9 trade flow features
- `market_resolutions_v2` (or `mr_full.csv`) — fresh outcomes
- `binance_klines_v2` — BTC 5m for ATR/ADX/MA200 features (extend through today)
- VPS3 `trading.events` for inverse sleeve performance tracking

After pulling, re-run `combined_gate_v2.py` (V3 ∪ P7 ∪ P9 union) on the fresh data to confirm the +143.60 PnL holds out-of-sample.

### Priority 3 — Test against REAL liquidity, not mid-price assumption

Current backtests assume entry at $0.50 mid-price. **Real Polymarket entries** require book-walking the actual ask side:
- 1-share entry: best ask
- $25 stake (~50 shares at $0.50): walks 1-3 levels deep, slippage 50-150bp
- $100 stake (~200 shares): walks 5-10 levels, slippage 100-300bp

We have the orderbook snapshots — plug them into the backtest engine to compute realistic fill prices instead of assumed mid. The `btc_book_depth_v3_full.csv` has top-10 levels per 10s bucket.

**Likely impact**: ROI estimates drop 5-15% across all signals when realistic slippage is applied. The 77.7% Phase 9 hit rate is unaffected; only the per-bet PnL drops.

**Acceptance criteria for live deploy**: even with realistic slippage, V3 ∪ P7 ∪ P9 should clear ~+15-25% ROI/bet. If yes → ship it. If no → reduce universe to top-confidence markets only.

### Priority 4 — Pull tomorrow's inverse sleeve verification at ~07:00 CEST

The 6 `*_volume_INV_NIGHT` sleeves activate UTC 01:00-05:00 (= 03:00-07:00 CEST tomorrow morning). Check whether they fire as predicted (60-70% hit rate vs original sleeves' 30-40%). If volume_INV_NIGHT confirms the night-hour bias hypothesis, **kill the original `_volume` sleeves entirely** — they bleed $1k/day in paper.

Quick check:
```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "PGPASSWORD=<VPS3_RO_PWD> psql -h 127.0.0.1 -U tradingvenue_ro -d storedata -c \"
    SELECT sleeve_id, COUNT(*) AS n, SUM(CASE WHEN (data->>'won')::bool THEN 1 ELSE 0 END) AS wins,
           ROUND(100.0*SUM(CASE WHEN (data->>'won')::bool THEN 1 ELSE 0 END)/COUNT(*),1) AS hit
    FROM trading.events WHERE kind='poly_updown_resolution' AND sleeve_id LIKE '%_INV%'
      AND at > NOW() - INTERVAL '24 hours' GROUP BY sleeve_id ORDER BY sleeve_id\""
```

---

## Where things stand right now (deployment state)

### VPS3 — LIVE
- **Branch/commit**: `feat/phase-18.4-inverse-sleeves` HEAD `db55db2` (also merged to `main`)
- **Engine PID**: 438324, started 2026-05-05 18:59:07 CEST, uptime ~3.5h
- **35 sleeves firing**: 27 base (V1, V2, V3, V3.1-3, V4) + 8 inverse (paper-only)
- **Inverse flag**: `TV_INVERSE_SLEEVES_ENABLED=true` set in `/etc/tv/tradingvenue.env`
- **First 3h of inverse data** (16:59-19:54 UTC): 4 trades fired, sniper inverses on-prediction
- **Validation schedule**: lab pulls weekly via `refresh_and_analyze.sh`; pass/fail criteria at +7d (May 12) and +14d (May 19)

### VPS3 — kill switch (have ready)
```bash
ssh -i ~/.ssh/vps3_ed25519 root@185.190.143.7 \
  "sed -i 's/^TV_INVERSE_SLEEVES_ENABLED=.*/TV_INVERSE_SLEEVES_ENABLED=false/' /etc/tv/tradingvenue.env && systemctl restart tv-engine"
```

### VPS connection details (cache for next session)

| VPS | Address | SSH key | Postgres |
|---|---|---|---|
| VPS2 | `root@'[2605:a140:2323:6975::1]'` | `~/.ssh/vps2_ed25519` | `127.0.0.1:5432/storedata` (collector raw data) |
| VPS3 | `root@185.190.143.7` | `~/.ssh/vps3_ed25519` | `127.0.0.1:5432/storedata` (TV agent + collector) |

**RO password** (both): `<VPS3_RO_PWD>` (in `/etc/tv/tv-ro.env` as `TV_RO_PWD_PLAIN`)
**TV write user (VPS3 only)**: `tradingvenue` / `<VPS3_TV_PWD>`

---

## What we accomplished this session

### Track 1 — Kronos LLM (CLOSED)

Revisited Kronos (Polymarket prediction LLM, 400MB BTC fine-tune). Built complete meta-classifier framework, ran v1 (sample_count=5) + v2 (sample_count=30) inference on 4,673 BTC markets, scored with HGB + isotonic calibration + 6-row ablation ladder.

**Verdict: Kronos is dead weight.** `kr_pred_dir_5m` permutation importance = 0.0. `kr_pred_ret_15m` ranks #7 in v2 (only Kronos feature with marginal value). Best ensemble (V3+TA+DerivZScore+Kronos) at threshold 0.65 hits 56.1% — V3 baseline alone at threshold 0.65 hits **63.6%**. No retraining will move 0 importance.

Reports: `META_CLASSIFIER_V1.md`, `META_CLASSIFIER_FULL_REPORT.md`, `META_CLASSIFIER_NO_KRONOS.md`. Kronos scripts archived to `strategy_lab/_archive/kronos/`. Model weights preserved at `D:/kronos-ft/` for future reference.

### Track 2 — V3 + Phase 7 + Phase 9 deployable signals

Discovered three orthogonal signals on Polymarket BTC UpDown:

| Signal | n | Hit | ROI/bet | Mechanism |
|---|---:|---:|---:|---|
| **V3 prob_stack ≥ 0.65** | 330 | 63.6% | +25.3% | quantile model on V3's 32-feature stack |
| **Phase 7 CLOB momentum top 5%** | 232 | 60-65% | +18-25% | book imbalance derivative (CONTRARIAN) |
| **Phase 9 trade flow top 10%** ⭐ | 355 | **77.7%** | **+53.5%** | Polymarket buy-YES vs buy-NO flow asymmetry |
| **V3 ∪ P7** | 534 | 62.2% | +22.3% | union (5% overlap, orthogonal) |
| **V3 ∪ P7 ∪ P9** ⭐ | **840** | **68.1%** | **+34.2%** | tri-signal union, $143.60 total PnL |

**V3 ∪ P7 ∪ P9 = +244% more PnL than V3 alone.** Phase 9 is the highest-impact discovery of this session BUT has lookahead caveat (see Priority 1 above).

Reports: `COMBINED_V3_PHASE7.md`, `PHASE7_CLOB_MOMENTUM.md`, `PHASE9_POLYMARKET_TRADE_FLOW.md`, `COMBINED_V3_P7_P9.md`.

### Track 3 — Anti-edge inverse sleeves (DEPLOYED)

Analyzed 6,111 losing-sleeve trades from VPS3. Found systematic biases:
- **Volume sleeves bleed during UTC 1-5 + 9-10** (Asian session + London open) — 30-40% hit rates
- `sol_5m_sniper`: 39.8% hit overall (z=2.02) — full inverse → 60.2%
- `eth_5m_sniper` DOWN signals: 34.9% hit (z=1.98) — direction-only inverse → 65.1%

**Wrote complete TV agent implementation guide.** Coordinated 6-question Q&A on architecture (sync strategy, deploy timing, sleeve naming, hedge-hold, time anchor, test paths). Helped TV agent debug 4 CI failures (chmod, test count drift, pnpm cache, bar-read-gate false positive).

**TV agent shipped Phase B at 16:59 UTC.** 8 new inverse sleeves now firing in paper mode on VPS3:
- `poly_updown_{btc,eth,sol}_{5m,15m}_volume_INV_NIGHT` × 6 (UTC 1-5 + 9-10 only)
- `poly_updown_sol_5m_sniper_INV` (always-on)
- `poly_updown_eth_5m_sniper_DOWN_INV` (DOWN-only)

Reports: `ANTI_EDGE_FINDINGS.md`, `TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md`.

### Track 4 — Stop-loss exhaustively tested (CLOSED)

Tested 24 stop-loss rules on V3 ∪ P7 union (534 bets). Five categories: floor protection, time-windowed levels, velocity, velocity+skip, hybrid.

**ALL 24 RULES UNDERPERFORM no-stop.** Best variant (A1 floor 0.05) loses -6%. Worst (C4 vel0.20_3bkt) loses -33%.

**Why**: Polymarket binary 0/1 markets at short horizons have thin orderbooks where mid-window prices are noise, not consensus probability. Stop-loss in this environment captures noise, not info. The asymmetric payoff (lose 102%, win 98%) is solved by the 62% hit rate margin, not by exit rules.

Reports: `STOPLOSS_BACKTEST.md`, `stoploss_battery_results.csv`.

### Track 5 — Hyperliquid v5 frontier validated (PAUSED)

Built `gauntlet_v5.py` to apply 8 of 10 gates to v5 frontier configs. Top ETH candidate: `X_none__S_volscale__E_24h__R_3loss_pause` — 31 trades, 74% WR, +73.9% ROI over 2.85 years (CAGR +21.4%), MDD -5.3%, beats B&H 1.45×. **6/8 gates pass.**

User pivoted away because **all alpha landed in 2024** (1 of 4 calendar years positive) and 31 trades / 2.85y = 11 trades/year is too sparse vs Polymarket's 200+/day.

Report: `V5_GAUNTLET_VALIDATION.md`.

### Track 6 — V3-next regime feature promotion + Kronos cleanup

Promoted 6 features (rank 4-14 in meta-classifier) to V3-next:
- `btc_dist_ma200_5m` (rank 4, importance 0.025)
- `btc_z_oi_silent` (rank 9, 0.017) — NEW signal not in V3
- `btc_z_top_lsr_sum`, `btc_z_taker_ratio`, `btc_z_oi`, `btc_adx_14_5m`

Output: `strategy_lab/data/polymarket/btc_features_v3plus.csv` (38 cols × 2,734 rows, 98.6% complete). Builder: `strategy_lab/build_features_v3plus.py`. 15 Kronos `.py` scripts moved to `strategy_lab/_archive/kronos/`.

---

## Files created this session (all paths from repo root)

### Code (16 new files)
```
strategy_lab/meta_classifier/build_dataset.py            joins universe + V3 + Kronos + TA + DerivZScore + outcome
strategy_lab/meta_classifier/train_eval.py               HGB + isotonic + ablation + Kelly + calibration
strategy_lab/meta_classifier/combined_gate_v1.py         V3 ∪ Phase 7 union analyzer
strategy_lab/meta_classifier/combined_gate_v2.py         V3 ∪ P7 ∪ P9 tri-signal union (subagent)
strategy_lab/meta_classifier/anti_edge_analyzer.py       sleeve × signal × hour × dow loss bias finder
strategy_lab/meta_classifier/v4_phase7_crossref.py       cross-reference v4 trades vs Phase 7
strategy_lab/meta_classifier/stoploss_backtest.py        9-rule baseline stop-loss test
strategy_lab/meta_classifier/stoploss_battery.py         25-rule comprehensive stop-loss test
strategy_lab/meta_classifier/refresh_and_analyze.sh      weekly VPS3 data refresh + re-analysis helper
strategy_lab/v4_signals/phase7_clob_momentum.py          Phase 7 CLOB orderbook momentum builder (subagent)
strategy_lab/v4_signals/phase9_polymarket_trade_flow.py  Phase 9 trade flow imbalance builder (subagent)
strategy_lab/v4_signals/derivatives_zscore/gauntlet_v5.py  v5 frontier 8-gate validator
strategy_lab/build_features_v3plus.py                    V3 + 6 promoted regime features (subagent)
strategy_lab/fetch_btc_5m_extend.py                      BTC 5m OHLCV extension to today
strategy_lab/kronos_smoke.py                             Kronos load/predict smoke test
strategy_lab/kronos_infer_v3_universe.py                 v1 Kronos inference on 4,673 markets
strategy_lab/kronos_infer_v2_quality.py                  v2 Kronos inference (sample_count=30)
strategy_lab/run_overnight_meta.sh                       overnight meta-classifier orchestrator
```

### Reports (12 markdown files)
```
strategy_lab/reports/META_CLASSIFIER_V1.md                    initial Kronos verdict
strategy_lab/reports/META_CLASSIFIER_FULL_REPORT.md           comprehensive v1+v2 Kronos analysis
strategy_lab/reports/META_CLASSIFIER_NO_KRONOS.md             ablation without Kronos (subagent)
strategy_lab/reports/COMBINED_V3_PHASE7.md                    V3 ∪ Phase 7 union analysis
strategy_lab/reports/ANTI_EDGE_FINDINGS.md                    losing sleeve bias analysis
strategy_lab/reports/TV_AGENT_INVERSE_SLEEVES_IMPLEMENTATION.md  TV agent deployment spec
strategy_lab/reports/PHASE7_CLOB_MOMENTUM.md                  Phase 7 builder report (subagent)
strategy_lab/reports/PHASE9_POLYMARKET_TRADE_FLOW.md          Phase 9 trade flow report (subagent)
strategy_lab/reports/COMBINED_V3_P7_P9.md                     tri-signal union (subagent)
strategy_lab/reports/STOPLOSS_BACKTEST.md                     9-rule simple stop-loss verdict
strategy_lab/reports/derivatives_zscore/V5_GAUNTLET_VALIDATION.md  ETH v5 frontier validation
strategy_lab/reports/SESSION_HANDOFF_2026_05_05.md            this file
```

### Data artifacts
```
strategy_lab/data/meta_classifier/labeled_v1.parquet            4,673 × 75 (Kronos sample=5)
strategy_lab/data/meta_classifier/labeled_v2.parquet            4,673 × 75 (Kronos sample=30)
strategy_lab/data/meta_classifier/btc_clob_momentum_v1.parquet  Phase 7 features (4,631 × 8)
strategy_lab/data/meta_classifier/btc_trade_flow_v1.parquet     Phase 9 features (4,673 × 9)
strategy_lab/data/polymarket/btc_features_v3plus.csv            V3 + 6 new features (2,734 × 38)
strategy_lab/results/meta_classifier/v1_*, v2_*                 ablation tables, calibration curves
strategy_lab/results/meta_classifier/anti_edge_breakdown.csv    sleeve × signal × hour bias
strategy_lab/results/meta_classifier/combined_v3_phase7.csv     534 union bets per-market
strategy_lab/results/meta_classifier/v4_phase7_crossref.csv     v4 trades enriched with P7
strategy_lab/results/meta_classifier/stoploss_results.csv       9-rule simple stop test
strategy_lab/results/meta_classifier/stoploss_battery_results.csv  25-rule comprehensive
strategy_lab/results/kronos/kronos_btc_predictions_full.csv     4,673 v1 predictions
strategy_lab/results/kronos/kronos_btc_predictions_full_s30.csv 4,673 v2 predictions
strategy_lab/reports/derivatives_zscore/gauntlet_v5_ETHUSDT.csv 5 v5 ETH configs gauntlet
strategy_lab/reports/derivatives_zscore/v5_equity/              5 equity curve parquets
data/v4/shadow_trades_2026_05_05_live/v3_v4_resolutions.csv     fresh VPS3 v3+v4 trades (175 rows)
data/v4/shadow_trades_2026_05_05_live/losing_sleeves.csv        fresh VPS3 losing trades (6,111)
data/v4/shadow_trades_2026_05_05_live/btc_trades_v2_aggregated.csv  Phase 9 source data
strategy_lab/kronos_ft/data/BTCUSDT_5m_ext.csv                  extended through 2026-05-05 01:55
```

---

## Open / Unfinished items

### Critical (validate before any deploy decision)
1. **Phase 9 lookahead validation** — Priority 1 above. Without this we don't know if 77.7% is real alpha or BTC-momentum readout
2. **Real liquidity backtest** — current 0.50 mid assumption is optimistic. Need book-walked fills before sizing up

### Active (auto-running, no action needed)
3. **Inverse sleeve validation** — running on VPS3 since 16:59 UTC. Pulls scheduled +24h, +7d (May 12), +14d (May 19) via `refresh_and_analyze.sh`
4. **TV agent's backlog**: V52 fit path, `/positions` 500 fix, BarEngine wire (needs new GSD phase)

### Watch list (conditional)
5. **`btc_5m_volume_FULL_INV` sleeve** — add if night-only inverse underperforms (<55% hit on 50+ trades)
6. **Kill `btc_5m_volume` original entirely** — if volume_INV_NIGHT confirms 60%+ hit (i.e., the base sleeve is provably dead weight)
7. **Refresh Phase 7 CLOB momentum on May 5+ data** — when fresh book depth is pulled
8. **VPS3 working tree to `main`** — TV agent owes this. Cosmetic, engine doesn't care.

### Deferred (low priority)
9. **Per-asset Kronos training (ETH+SOL fine-tunes)** — ~12h GPU. Configs ready (`config_ethusdt_5m_3y.yaml`, `config_solusdt_5m_3y.yaml`), data ready. Deferred per user — Kronos closed.
10. **Kronos-mini ensemble** — ~2.5h GPU. Same logic — Kronos found dead.
11. **Track C Hyperliquid v5 deploy** — paused. ETH champion identified (`X_none__S_volscale__E_24h__R_3loss_pause`) but user pivoted to Polymarket due to v5's low trade frequency (11/year).
12. **Track C Path 2** — fix BTC G7 (anchored walk-forward) + G5 (trade-level perm test) for handoff's existing 4h adaptive ETH variant. Not pursued; v5 frontier covers same ground.
13. **Kronos retrain (FIRE_RETRAIN.md)** — extended training data through Apr 22 ready (`BTCUSDT_5m_ext.csv`). Not fired because Kronos closed.

---

## Quick-start commands for next session

```bash
# 1. Pull fresh VPS3 shadow trade data (includes inverse sleeve activity)
bash strategy_lab/meta_classifier/refresh_and_analyze.sh

# 2. Pull fresh VPS2 trades_v2 + orderbook for fresh Phase 7 + Phase 9 features
# (use phase9_polymarket_trade_flow.py and phase7_clob_momentum.py as references —
#  they have the SQL aggregation patterns)

# 3. Re-run combined_gate_v2 on fresh data
py strategy_lab/meta_classifier/combined_gate_v2.py

# 4. Validate Phase 9 lookahead (PRIORITY 1)
# Write a quick regression test:
#   regress outcome_up ~ poly_tfi_2m + btc_ret_2m
#   Check if poly_tfi_2m coef survives controlling for btc_ret_2m
#   File suggestion: strategy_lab/meta_classifier/phase9_lookahead_test.py

# 5. Re-run with realistic slippage
# Modify combined_gate_v2.py to use book-walked fill prices instead of 0.50 mid
# (book_depth_v3_full.csv has top-10 levels per 10s bucket)
```

---

## Suggested first message to next session

> Pick up from `strategy_lab/reports/SESSION_HANDOFF_2026_05_05.md`. Priority 1: validate Phase 9 lookahead. Phase 9 (Polymarket trade flow imbalance) showed 77.7% hit on 355 bets in this session BUT for 5m markets the feature consumes 40% of the window — need to regress outcome_up on [poly_tfi_2m, btc_ret_2m] to confirm it's novel alpha vs partial-momentum readout. After that, pull fresh data from VPS2 (orderbook + trades) and VPS3 (inverse sleeve activity), re-run combined_gate_v2, and add realistic slippage by walking the orderbook instead of assuming 0.50 mid. Inverse sleeves running on VPS3 since 16:59 UTC May 5 — first volume_INV_NIGHT activation expected ~01:00 UTC May 6.

---

*End of SESSION_HANDOFF_2026_05_05.md. Open items: Phase 9 lookahead validation, fresh data pull, real-liquidity backtest, inverse sleeve +24h check tomorrow morning.*
