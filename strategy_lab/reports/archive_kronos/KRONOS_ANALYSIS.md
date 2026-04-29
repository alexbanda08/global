# Kronos as a Strategy-Lab Indicator — Viability Analysis

**Source**: https://github.com/shiyu-coder/Kronos
**Paper**: arXiv 2508.02739 · accepted AAAI 2026
**License**: MIT
**Last updated**: 2026-04-22

---

## 1. What Kronos is

A decoder-only transformer **foundation model for financial K-line (OHLCV) sequences**.
Two-stage architecture:

1. **KronosTokenizer** — quantizes continuous OHLCV into hierarchical discrete tokens.
2. **Kronos predictor** — autoregressive transformer trained on those tokens.

Outputs a **full forecasted OHLCV DataFrame** for the next `pred_len` bars (probabilistic via temperature + nucleus sampling; can average `sample_count` paths).

### Model zoo

| Model        | Params  | Context | Open | Notes |
|--------------|--------:|--------:|:----:|---|
| Kronos-mini  |   4.1 M |  2048   | ✅  | longest context, smallest |
| Kronos-small |  24.7 M |   512   | ✅  | recommended default |
| Kronos-base  | 102.3 M |   512   | ✅  | best open-source quality |
| Kronos-large | 499.2 M |   512   | ❌  | closed |

All models on HuggingFace under `NeoQuasar/`. MIT licensed → shippable.

### Pre-training corpus
Pre-trained on **Chinese A-share equities** (the demo finetune uses Qlib).
Authors explicitly call out the demo is "**not production-ready**" — raw signals,
no portfolio optimization, no risk neutralization, simple top-K backtest.

---

## 2. How it would slot into our lab

Kronos returns OHLCV forecasts → trivially convertible into 3 indicator types:

| Indicator                | Derivation                                              | Use in our engine |
|--------------------------|---------------------------------------------------------|-------------------|
| `kronos_ret_pred_N`      | `pred.close[-1] / x.close[-1] - 1` (N-bar % return)     | Entry gate (V24 multi-filter style) |
| `kronos_vol_pred_N`      | `pred.high - pred.low` mean / `x.close[-1]`             | Position-sizing input (replace 28d realised vol in V23) |
| `kronos_path_dispersion` | std of `sample_count` paths' final close                | Confidence weighting — flatten when high |

These slot directly into our existing `simulate()` (`run_v16_1h_hunt.py`)
because they're just boolean / float Series indexed by bar timestamp — same
shape as our current ATR / regime / breadth signals.

### Data fit
- Our 4h Binance OHLCV is in `data/binance/parquet/`. Identical shape to
  Kronos's input (`open, high, low, close, volume, amount`). No reformat work.
- 512-bar context = **85 days** at 4h → plenty for our regime models.
- Our 9-coin universe × ~13k bars each = manageable for batch inference.

---

## 3. Pros for our specific setup

- **MIT licensed** — no commercial blocker.
- **OHLCV in / OHLCV out** — zero schema friction with our pipeline.
- **GPU optional** — Kronos-small (24.7 M) runs on CPU; full backtest of
  ~13k bars × 9 coins is hours, not days, with caching of forecasts.
- **Two integration surfaces**:
  1. As an *additional bear filter* on V24 (require Kronos 5-bar return > 0).
  2. As a *standalone XSM ranker* (rank coins by `kronos_ret_pred_14d`
     instead of trailing 14-day return).
- **Dashboard already supports new strategies** — anything we build slots
  into `run_dashboard.show()` for free.

---

## 4. Cons / risks

| Risk | Severity | Mitigation |
|---|---|---|
| **Domain shift** — pre-trained on A-share equities, not crypto (different vol regime, 24/7 vs session, microstructure) | HIGH | Mandatory fine-tune on Binance 4h before any backtest |
| **Stochastic output** — temperature/top-p sampling = same input, different prediction | MED | Set `sample_count ≥ 8` and average; pin RNG seed for reproducibility |
| **No published crypto OOS benchmark** | HIGH | Our own walk-forward eval is required before any deployment claim |
| **Finance foundation models have a poor live track record** (Lopez de Prado, etc.) | HIGH | Treat as gate / rank-input, never as standalone strategy |
| **Inference cost at scale** — bar-by-bar prediction over 13k bars × 9 coins | MED | Batch inference (`predict_batch`); cache forecasts to parquet |
| **Look-ahead trap** — easy to accidentally include the bar being predicted | HIGH | Hard discipline: prediction at bar `i` uses only bars `[i-512, i-1]` |
| **Foundation model overfit risk** — 100M+ params memorize patterns | MED | V30-style overfitting audit (5-test) on any Kronos-derived strategy |

---

## 5. Recommended adoption path (3-phase spike)

### Phase 0 — sniff test (~1 day)
- `pip install` Kronos requirements; load `Kronos-small`.
- Run `prediction_example.py` on BTC/ETH 4h from our parquet store.
- Eyeball: does the 20-bar forecast track realised on a held-out 2025-Q4 window?
- **Gate**: if forecast vs realised correlation < 0.10 on raw model → fine-tune is mandatory.

### Phase 1 — indicator wrapper (~2–3 days)
- `strategy_lab/kronos_indicator.py`:
  ```python
  def kronos_signals(sym: str, tf: str = "4h", lookback: int = 256,
                     pred_len: int = 5, sample_count: int = 8) -> pd.DataFrame:
      """Returns DataFrame indexed by bar timestamp with columns:
         ret_pred, vol_pred, path_dispersion, conf_score."""
  ```
- Caches forecasts to `data/kronos/{sym}_{tf}.parquet` (re-use across backtests).
- Strict no-look-ahead guard (assert `pred_window > input_window.end`).

### Phase 2 — strategy variants (~1 week)
- **V37** — V24 multi-filter + Kronos gate: enter only if
  `kronos_ret_pred_5 > 0` AND existing breadth filter passes.
- **V38** — XSM with Kronos ranking: sort top-4 by `kronos_ret_pred_14d`
  instead of trailing 14-day return.
- Both go through V30 overfitting audit (5-test) before any deployment claim.

### Phase 3 — fine-tune (optional, ~1 week)
- Use Kronos `finetune/` scripts adapted to Binance OHLCV.
- 8 coins × 5+ years of 4h = ~17k bars/coin × 8 = ~135k samples.
- Train on 2017-2024, val 2024, test 2025+ → publish OOS report.

---

## 6. What I would NOT do

- Replace V24 / USER 5-sleeve as the deployed strategy. Kronos is a
  research direction, not a swap-in for a 5/5 robustness-audited system.
- Use raw model out of the box on crypto without OOS validation.
- Trust a single-sample forecast (`sample_count=1`) for live decisions.
- Use Kronos-mini's 2048 context — the longer context isn't free, and
  the 4.1M params likely under-perform Kronos-small on our universe.

---

## 7. Bottom line

**Worth an experimental spike, not a deployment commitment.** The MIT
license + clean OHLCV interface + open-source weights make it the
lowest-friction "ML indicator" we could plug into our existing engine.
But pre-trained-on-A-shares + no published crypto benchmark + finance
FM track record = treat the output strictly as a *gate* or *rank-input*
on top of our already-validated V24 / USER 5-sleeve, never as a
standalone strategy.

**Suggested next concrete action**: Phase 0 sniff test (1 day budget).
If correlation passes the 0.10 gate, schedule Phase 1.
