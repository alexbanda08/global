# Overnight GPU/CPU sprint — consolidated results — 2026-06-04

All four overnight jobs completed. One-line thesis: **the underlying crypto is efficient everywhere we looked
at every scale; the only place edge appears is Polymarket execution (the exit-scalp + scalp-fire selectors).**

## Results table
| job | scale | result | verdict |
|---|---|---|---|
| **GPU model search** (kline→poly RV) | **415 model configs**, 12h GPU | **0/415 beat the poly price** (CI>0). Best ≈ −$0.15/tr. Kline next-bar acc 0.52–0.53 (tiny real edge) — but poly already prices it. | kline-trained direction model does NOT beat poly. Definitive. |
| **VBT mega-sweep** | **4.8M strategies**, 12 series, 8.8y | 29 survivors (IS+VAL+OOS>0) ≈ multiple-testing noise; only a **daily-trend MA cluster** (BTC/ETH/SOL 1d, OOS Sharpe 0.4–1.1) is mildly interesting — *daily spot/perp, not intraday, not poly*. | crypto direction efficient; no intraday/poly edge. |
| **CPU scalp/slug search** | **387k candidates** | **50 finalists, purged-CV gated $/tr 7–8, confound-free, ~2× the null floor (3.27)**. RandomForest/ExtraTrees, vwap<0.55, exit+75. | ⭐ the ONE promising result — but heavily-searched → needs different-window OOS. |
| GPU LSTM (9 series) / Kronos / kline→poly (single) | 8.8y | all efficient: LSTM acc≈0.50, Kronos failed real-poly OOS (52.9%), kline→poly RV −$0.28/tr CI~0 | no underlying edge. |

## The two things that carry edge (push these next session)
1. **The deployed intra-window EXIT-SCALP** — the validated live edge (+$2.98/tr t=6.33 offline; TIME+45/60s book-sell;
   16 shadow sleeves accruing the ≥200-fire forward gate). Execution, not prediction.
2. **The 50 scalp-fire SELECTORS** (CPU search `finalists.json`) — in-sample-strong (CV $/tr 7–8, confound-free),
   the only models that cleared the noise floor with margin. **Unconfirmed** — selection-inflated over 387k tries.

## What is now definitively dead (don't repeat)
- Predicting crypto direction from klines — any model (XGBoost, LSTM, 415-config search, Kronos), any horizon,
  any TF, 8.8 years of data. Efficient. Proven ~5 independent ways tonight.
- Indicator strategies on the underlying (4.8M combos) — only weak daily-trend, not poly-relevant.
- Kline-model relative-value vs the poly price — 415 configs, 0 beat it.

## NEXT SESSION (priority order)
1. **Install the ml4t toolkit** (operator-supplied — `HANDOFF_NIGHT_2026_06_03_GPU_SPRINT.md`): `engineer`
   (120 features + triple-barrier/meta-labeling + dollar/imbalance bars), `models`, `diagnostic`
   (**DSR / PBO / CPCV / FDR**). Likely a 3.12 venv (polars/numba may lack 3.14 wheels).
2. **Re-judge the 50 scalp-fire finalists + the 29 mega-sweep survivors under DSR + PBO + CPCV.** This is the
   exact rigor the whole night was approximating by hand. Expect most to fail PBO; the few that survive are real.
3. **Different-window OOS** on the survivors via `validate_oos.py` (the 6-month API — must include L25 books +
   CLOB trades + klines, not just klines).
4. **Meta-label the exit-scalp** with `engineer`'s meta-labeling + CPCV to sharpen its entry filter (the live edge).

## Assets built (kept on disk)
- 8.8y spot klines + 6y futures (klines/funding/OI) in `_data/binance_vision[_deriv]/`.
- autoresearch harness (`search_overnight.py`, `vbt_mega_sweep.py`, `gpu_model_search.py`, `gpu_kline_to_poly.py`,
  `validate_oos.py`, `fitness.py`) + `finalists.json` + `gpu_search_log.jsonl` (415 configs).
- torch 2.11+cu126/CUDA (RTX 3060) working; vectorbt 0.28.5 + numba working on Python 3.14.

## Reports
This file + `VBT_MEGA_SWEEP.md`, `GPU_MODEL_SEARCH.md`, `GPU_LSTM_SUMMARY_2026_06_03.md`,
`KLINE_TO_POLY_2026_06_03.md`, `HANDOFF_NIGHT_2026_06_03_GPU_SPRINT.md`, and the session reports listed there.
