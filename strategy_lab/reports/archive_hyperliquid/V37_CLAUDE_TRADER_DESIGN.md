# V37 — Claude as Trader (LLM Regime Router)

**Date:** 2026-04-22
**Goal:** Use Claude as the regime-classifying trader. At each decision point Claude sees recent OHLCV + indicators, emits a structured `Decision{regime, strategy, direction, size_mult, confidence}`, and the existing engine executes the chosen strategy from our signal library until the next decision.

---

## 1. Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                     HISTORICAL BACKTEST MODE                          │
└───────────────────────────────────────────────────────────────────────┘

  for each decision_bar_ix in every Kth bar of df:
      snapshot = build_snapshot(df.iloc[ix - 200 : ix])   ← strict past-only
      request  = batch_request(custom_id=f"{coin}:{ix}", snapshot, system=cached)
  submit all requests as ONE Message Batches API call (50% off, async)
  wait → collect Decision objects
  decisions_by_bar[ix] = Decision(...)

  entries, exits, short_entries, short_exits =
      build_signals_from_decisions(df, decisions_by_bar)   ← forward-fill between decisions
  result = engine.run_backtest(df, entries, exits, short_entries, short_exits)
  # Engine already shifts signals +1, fills at next-bar open → no look-ahead.
```

Live-trading mode replaces the batch step with a per-bar `client.messages.parse()` call returning a validated `Decision` via Pydantic.

## 2. Decision contract (Pydantic / JSON Schema)

```python
class Decision(BaseModel):
    regime:     Literal["trend_up","trend_down","range","high_vol","transition"]
    strategy:   Literal["BBBreak_LS","HTF_Donchian","CCI_Rev","Flat"]
    direction:  Literal["long","short","both","none"]
    size_mult:  float  # 0.0–1.0
    confidence: float  # 0.0–1.0
    rationale:  str    # ≤ 300 chars
```

`client.messages.parse(..., output_format=Decision)` validates every response server-side.

## 3. Dispatch: decision → signals

Claude never computes indicators itself. It picks a *name*. The scaffold maps names to existing tested signal functions:

| `Decision.strategy` | Signal function                               | Source file             |
|--------------------|-----------------------------------------------|-------------------------|
| `BBBreak_LS`        | `sig_bbbreak_ls(df, n=20, k=2.0, reg=200)`   | `run_v34_expand.py`     |
| `HTF_Donchian`      | `sig_htf_donchian_ls(df, donch_n=20, ema_reg=100)` | `run_v34_expand.py` |
| `CCI_Rev`           | `sig_cci_extreme(df, cci_n=20, cci_thr=200)` | `run_v30_creative.py`   |
| `Flat`              | no entries; force-exit open positions        | in dispatch             |

Strategy switches force an exit of the open position on the switch bar (handled in `build_signals_from_decisions`).

## 4. Look-ahead discipline

- Snapshot built for bar `i` uses ONLY `df.iloc[i-lookback : i]`.
- Indicator snapshot computed from that same slice — no `shift(-1)` anywhere.
- Execution happens at bar `i+1` open (existing `engine.run_backtest` shifts +1).
- Close prices in the snapshot are percentile-ranked to **mask memorized price patterns** (training-data leakage mitigation).
- Dates in the snapshot are NOT masked (strategies can be calendar-aware), but a second run with dates masked gives us a memorization-delta.

## 5. Cadence

- Decision cadence: **every 6 bars on 4h = daily**. Configurable.
- 3 years × 2190 bars/year ÷ 6 ≈ **1100 decisions per coin**, × 5 coins = **5 500 API calls per backtest**.

## 6. Cost / speed

| Line item | Tokens/call | Calls | Cost (Opus 4.7, batch 50% off)     |
|---|---:|---:|---:|
| System prompt (cached) | 3 000 (cached read @ $0.50/MTok) | 5 500 | $8.25 |
| User snapshot (fresh)  | 1 500 @ $5/MTok                 | 5 500 | $41  |
| Thinking + output      | ~500 @ $25/MTok                 | 5 500 | $69  |
| **Total per full backtest** |                         |       | **~$118** (batch) / ~$235 (live) |

Cheaper options user can pick: `claude-sonnet-4-6` (~3×), `claude-haiku-4-5` (~5× cheaper, smaller context).

Wall-clock for batch: typically ~1 hour; 24h SLA. For iterative research, cache every `Decision` to parquet keyed by `(coin, bar_ix, input_hash)` — re-runs skip the API entirely.

## 7. Validation plan (must pass to ship)

1. **Baseline parity.** Run Claude-trader on same window / coins as V34 deployment blueprint (SOL/ETH/AVAX/DOGE/TON, 2022-12 → 2026-03).
2. **Compare equity** vs V34 equal-weight 5-sleeve portfolio on: CAGR, Sharpe, max-DD, Calmar, trades/year, longest flat stretch.
3. **5-test audit** (identical to V31/V32/V34):
   - per-year breakdown (max single-year share ≤ 0.5 of log-return)
   - parameter plateau: re-run with lookback ∈ {100, 200, 300}, cadence ∈ {daily, every-other-day, weekly}
   - randomized-entry null (n=100) — Claude's decisions vs random strategy-name shuffles
   - MC bootstrap (monthly, n=1000)
   - Deflated Sharpe with `N_trials ≈ 2000`
4. **Agreement heatmap:** Claude's regime label vs realised forward-30d return quintile. If random, Claude isn't adding signal.
5. **Ablations:**
   - date-masked snapshot vs date-visible snapshot (memorization delta)
   - indicator-only vs indicator+OHLCV snapshot (is the price table load-bearing?)
   - Opus vs Sonnet vs Haiku (cost/quality curve)
   - seed variance: 3 identical runs at `temperature` irrelevant on 4.7 — adaptive thinking gives stochastic output regardless; run 3 seeds and majority-vote

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Claude has seen crypto price history in training → memorisation | Percentile-rank close prices in snapshot; date-mask ablation |
| LLM decision variance | 3 seeds + majority vote on decision cadence |
| API failure mid-live | Fallback: stay in last decision until reconnect; if > 2 cadence periods → flat |
| Prompt cache invalidation silently → 10× cost | System prompt is frozen bytes; `cache_creation_input_tokens / cache_read_input_tokens` logged every call |
| Audit failure | Park as novelty; no deploy |

## 9. Files

- `strategy_lab/v37_claude_trader.py` — client, schema, cache, batch builder, dispatch
- `strategy_lab/run_v37_claude_trader.py` — end-to-end historical runner
- `strategy_lab/prompts/claude_trader_system.md` — frozen system prompt (cached)
- `strategy_lab/results/v37/decisions_{coin}.parquet` — decision cache
- `strategy_lab/results/v37/equity_vs_v34.csv` — comparison table

## 10. Follow-on experiments if V37 clears the audit

- **V38 — Claude-as-meta-router**: one Claude call per week selects the 5 sleeves + weights for the following week from a catalog of 16 audited strategies.
- **V39 — Claude-as-risk-officer**: Claude only gates position size (not direction), preserving our rule-based alpha.
- **V40 — Claude + Kronos hybrid**: Kronos 20-bar price forecast + Claude regime label as joint inputs.
