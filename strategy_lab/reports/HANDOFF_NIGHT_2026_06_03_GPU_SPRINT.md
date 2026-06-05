# Night handoff — 2026-06-03 GPU sprint + next-session ml4t toolkit

## 🌙 RUNNING OVERNIGHT (started 2026-06-03 late; check status before touching)
| job | task-id | engine | budget | output |
|---|---|---|---|---|
| GPU model search (kline→poly RV) | b80ajym2u | GPU | 12h | `reports/GPU_MODEL_SEARCH.md` + `_data/gpu_search_log.jsonl` |
| VBT mega-sweep (45 indicators ×12 series) | b17e9t8ig | CPU | 10h | `reports/VBT_MEGA_SWEEP.md` |
| CPU Polymarket scalp/slug search | b1k7bxani | CPU | 8h | `_data/overnight/{status.json,finalists.json,top_checkpoint.parquet}` |
Monitor: `cat _data/overnight/status.json` ; `tail reports/GPU_MODEL_SEARCH.md`. RAM was stable at ~14GB free with all 3.

## ⭐ NEXT-SESSION TRAINING INFRA — integrate the ml4t toolkit (operator-supplied)
These 3 repos are the **production-grade version of everything we hand-rolled this session.** Adopt them.

1. **ml4t/engineer** — feature engineering + labeling (Polars + Numba; 60 feats validated vs TA-Lib @1e-6).
   - **120 features, 11 categories** (momentum/volatility/trend/microstructure/…).
   - **AFML labeling: triple-barrier, ATR, percentile, trend-scanning, meta-labeling** (López de Prado).
   - **Alternative bars: volume / dollar / tick-imbalance bars** (better than time bars for ML).
   - **Leakage-safe dataset builder** (train/test prep) — replaces my ad-hoc ws_s/asof handling.
2. **ml4t/models** — the model layer (classifiers/regressors). Python 3.12+, src/ml4t/models layout.
3. **ml4t/diagnostic** — ⭐ THE BIG ONE — formal overfitting detection, exactly the crux of this whole session:
   - **DSR (Deflated Sharpe)** — corrects for multiple-testing bias (I approximated with permutation nulls).
   - **CPCV (Combinatorial Purged Cross-Validation)** — leak-free TS validation (I used a single lockbox).
   - **PBO (Probability of Backtest Overfitting)**, **RAS**, **HAC-adjusted IC**, **FDR (Benjamini-Hochberg)**.
   - This is the canonical machinery for "I searched N strategies, is the best real?" — use it to re-judge
     EVERY search we ran (mega-sweep, GPU model search, slug-selection, scalp).

### Next-session plan (concrete)
1. **Install** (likely a dedicated Python 3.12 venv — these are 3.12+; Python 3.14 may lack polars/numba wheels):
   `pip install git+https://github.com/ml4t/engineer git+https://github.com/ml4t/models git+https://github.com/ml4t/diagnostic` (or clone to `external/`).
2. **Re-run the poly + kline work under the real rigor:**
   - Build features with `engineer` (120 feats + dollar/imbalance bars), label with **meta-labeling / triple-barrier**.
   - Train with `models`; validate with **CPCV** (not single lockbox).
   - Judge every candidate with **DSR + PBO** — this finally puts a defensible number on "is this edge real after
     all the searching." Most of our session's marginal/negative results will get a clean PBO verdict.
3. **Apply to the two live questions:** (a) does any kline/microstructure model beat the poly price (relative-value)
   under DSR? (b) meta-label the exit-scalp fires under CPCV to sharpen the entry filter.
4. **Different-window OOS** (the 6-month API) remains the final gate — `validate_oos.py` is ready.

## Tonight's findings (all consistent — efficiency confirmed at scale)
- **Kronos: dead-end** — already failed real-poly OOS (52.9%, CI~0); generative forecaster ≠ classifier. Don't revive.
- **Kline→poly (GPU LSTM, 15 ep, trained pre-poly):** tiny real next-bar edge (0.52) but **does NOT beat the poly
  price** (RV-gated −$0.28/tr, CI touches 0). Poly efficiently priced vs it.
- **GPU LSTM on 8.8y (9 series):** no tradeable crypto direction (acc ≈ 0.50, all Sharpe ≤0).
- **VBT smoke + 15m:** indicator combos — best IS Sharpe ≤ shuffled-null floor → efficient.
- The 12h GPU search (~290 configs) and 10h mega-sweep are the exhaustive confirmations, judged by poly-price-beat / OOS.
- **The one real edge remains the intra-window EXIT-SCALP** (execution, not prediction). 16 shadow sleeves accruing.

## Data assets built this sprint (kept)
- `_data/binance_vision/{BTC,ETH,SOL}USDT_{1m,5m,15m,1h,4h,1d}_full.parquet` — **8.8y spot klines** (BTC/ETH from 2017-08).
- `_data/binance_vision_deriv/{SYM}_{klines,funding,metrics}_full.parquet` — **6y futures** klines + funding + OI/LSR (W3 basis).
- `_data/master_features.parquet`, `_data/overnight/`, the autoresearch harness (`search_overnight.py`, `vbt_mega_sweep.py`,
  `gpu_model_search.py`, `gpu_kline_to_poly.py`, `validate_oos.py`, `fitness.py`, `candidate.py`).
- torch 2.11.0+cu126 + CUDA working (RTX 3060). vectorbt 0.28.5 + numba working on Python 3.14.

## Key reports from the session
`SESSION_FINDINGS_2026_06_03_ML_SCALP_PHYSICS.md`, `GPU_LSTM_SUMMARY_2026_06_03.md`,
`KLINE_TO_POLY_2026_06_03.md`, `AUTORESEARCH_W1_FINDINGS_2026_06_03.md`,
`OVERNIGHT_SEARCH_AND_OOS_PROTOCOL_2026_06_03.md`, `SCALP_HEDGE_PHYSICS_SWEEP_2026_06_03.md`,
`EXIT_TIMING_MODEL_2026_06_03.md`, `ML_AGENTIC_PHASE_PLAN_2026_06_03.md`.
