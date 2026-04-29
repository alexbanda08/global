# Mission Gap Report — Preconditions vs. Current Stack

**Date:** 2026-04-22
**Scope:** Verify that the existing `strategy_lab/` stack can satisfy the hard numeric gates and execution philosophy specified in the mission brief, *before* starting Phase 1 audit work in earnest.

---

## 1. Data Stack — MATCH (with scope reduction)

| Mission context            | Reality in `strategy_lab/`                          | Status       |
|----------------------------|-----------------------------------------------------|--------------|
| ClickHouse OHLCV           | Parquet (time-partitioned by year)                  | Reframe OK   |
| PostgreSQL / TimescaleDB   | Not present                                         | N/A for now  |
| Bybit + Binance via ccxt   | Binance parquet only (10 symbols)                   | **Reduced**  |
| "All coins in ClickHouse"  | 10 symbols: BTC, ETH, SOL, ADA, AVAX, BNB, DOGE, LINK, XRP (+ one more) | **Capped**  |
| Timeframes 4h,1h,45m,30m,15m | Have 15m, 30m, 1h, 2h, 4h, 1d (no 45m)             | 45m missing  |

**Implications:**
- 45m timeframe is absent — either drop it from the Phase-5 grid, resample from 15m, or fetch.
- "Query all coins dynamically" is fine against the parquet tree — 10 symbols, not hundreds.
- Bybit fees/maker-rebate analysis cannot be done against current data; all simulations would use Binance fee schedule. If Bybit-specific execution is required, we need a ccxt-driven fee fetch + fresh market-data parity.

---

## 2. Backtest Engine — PARTIAL MATCH (blocking gaps)

Current engine (`strategy_lab/engine.py`, vectorbt 0.28.x wrapper):

| Mission requirement                              | Current engine                                    | Gap severity   |
|--------------------------------------------------|---------------------------------------------------|----------------|
| Maker vs. taker fee split                        | Flat **0.1% per side** (single rate, no distinction) | **BLOCKER**    |
| Limit-order fill simulation (next-bar-low/high)  | Execution at next-bar **OPEN** only                | **BLOCKER**    |
| Partial-fill modeling on bar volume              | None                                              | BLOCKER        |
| Limit-order cancellation after N bars unfilled   | None                                              | BLOCKER        |
| Maker fill % / taker fill % in output            | Not tracked                                       | BLOCKER        |
| Unfilled-order rate                              | Not tracked                                       | BLOCKER        |
| Slippage (5 bps flat)                            | Present                                           | OK             |
| Deterministic seeding                            | Must verify                                       | Likely OK      |
| Sharpe, Calmar, DD, etc.                         | Present                                           | OK             |
| Walk-forward framework                           | `walk_forward.py` exists, not consistently used   | Needs discipline |

**Bottom line:** The hard gate **"Maker-fill rate ≥ 60%"** is physically uncomputable on the current engine. Every hard-gate check that depends on realistic limit execution, maker/taker split, or partial fills is blocked until the engine is extended.

---

## 3. Existing Book — COUNT UNCONFIRMED

- Mission says **39 strategies**.
- Codebase has **~95 Python files** across V1–V37 generations. Many are *runners*, not distinct signal generators.
- Distinct signal logics estimated at **30–40** but not canonically listed anywhere.
- No single manifest (`strategies.yaml`, registry, etc.) enumerates "the 39". The README lists only the three per-symbol winners (V4C BTC, V3B ETH, V2B SOL at 4h).

**Implication:** Phase 1 must start by *defining the 39* (or whatever N is) — producing the canonical manifest that the correlation map, coverage matrix, and fee analysis all hinge on. Without it, every downstream step is ungrounded.

---

## 4. Regime / ML Infrastructure — THIN

| Mission component                              | Present?          |
|------------------------------------------------|-------------------|
| HMM / Gaussian regime classifier               | **No**            |
| Markov regime-switching (Hamilton)             | No                |
| Hurst exponent rolling                         | No                |
| ADX + EMA slope gating                         | Yes (V24 router)  |
| GARCH vol state                                | No                |
| BOCPD / PELT change-point                      | No                |
| Ehlers cycle/trend mode                        | No                |
| Directional Change framework                   | No                |
| Wavelet decomposition                          | No                |
| Triple Barrier Method                          | No                |
| Purged K-Fold CV + embargo                     | No (plain kfold)  |
| Meta-labeling (López de Prado Ch.3)            | No                |
| CPCV                                           | No                |
| Deflated Sharpe                                | Not computed      |
| Probabilistic Sharpe                           | Not computed      |
| Block bootstrap (Politis-White)                | No                |
| Permutation / null test                        | No                |

**Implication:** Phases 2, 3, 4, 5, 5.5 will require building this infrastructure fresh. Walk-forward code exists but needs hardening with purging/embargo.

---

## 5. Environment — FRAGILE

- Three Python installs coexist; only `D:\kronos-venv` reliably imports pandas + vectorbt + TA-Lib.
- Python 3.12 subprocess hangs reported; 3.14 lacks vbt/talib wheels.
- All Phase-4/5 runs must pin to the working venv path and document it in per-script headers.

---

## Recommended Sequencing (revised)

Given the gaps above, strict linear execution of the mission is infeasible. Proposed order:

1. **Phase 0 — Canonical Strategy Manifest** *(NEW, prerequisite for Phase 1)*
   Enumerate the N existing strategies, one row per discrete signal logic. Single source of truth.

2. **Phase 0.5 — Engine Uplift** *(NEW, prerequisite for Phase 5)*
   Extend `engine.py` with: maker/taker fee split, limit-fill simulation (next-bar-low/high), unfilled-order tracking, maker-fill % metric, partial fill modeling. Keep a v1 compatibility mode so existing strategies still run.

3. **Phase 1 — Existing Book Audit** (as specified, but driven by the Phase-0 manifest).

4. **Phase 2 — Regime Detection Foundation** (as specified).

5. **Phase 3 — Adaptive Strategy Research** (as specified).

6. **Phase 4 — Implementation** (requires engine uplift from 0.5).

7. **Phase 5 — Backtest Matrix** (requires engine uplift).

8. **Phase 5.5 — Robustness Battery** (new infrastructure: DSR, permutation, block bootstrap, parameter plateau plots, WF efficiency).

---

## Decisions Locked (2026-04-22)

1. **Engine uplift scope — FULL.** Add maker/taker fee split, limit-fill via next-bar low/high, unfilled-order tracking, partial fills against bar volume, maker-fill-rate metric. Preserve a v1 market-order compatibility mode so existing runners don't regress.
2. **Data scope — Binance-only, 10 symbols.** No Bybit fetch. No universe expansion. Work against existing `data/binance/parquet` tree.
3. **Strategy manifest — derive from codebase.** A dedicated agent reads every runner + strategy file, deduplicates by signal-logic fingerprint, and emits `docs/research/strategies.yaml` as the authoritative registry. One row per distinct signal logic.
4. **45m timeframe — dropped.** Phase-5 grid uses 4h, 1h, 30m, 15m only.
5. **Live execution parity — deferred.** Maker-fill-rate gate is validated in backtest against the uplifted engine; live testnet parity check happens only if/when a promoted strategy is queued for deployment.
