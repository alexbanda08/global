# Clean backtest from canonical data — V2 bugs CONFIRMED

_28-day backtest (Apr 22 → May 21) recomputing every strategy's signals from raw binance 1m klines, threshold-gating per spec, resolving outcomes from canonical chainlink resolutions. **NO shadow data input.** This isolates the strategy spec from the production implementation._

## TL;DR

- Clean spec implementation on canonical raw data produces **~47-53% WR** on every (asset, tf, version) cell. Universally near-random.
- Production claims **5% WR (eth_5m_v2 F7)** and **18% WR (btc_15m_v2 F7)** on the same cells.
- **No filter applied to a 47%-WR parent universe can produce a 5%-WR subset by random sampling.** The catastrophic production numbers are NOT explainable by the documented spec. **Production has a code-level inversion bug in V2 implementation for eth_5m and btc_15m.**
- F7 has no meaningful lift on clean canonical data (~±1pp). Production's 70%+ WR cells benefit from PRODUCTION-ENGINE FILTERS (sparse-book, slug-age, etc.), not from F7 alone.

## Setup

| Input | Source | Window | Note |
|---|---|---|---|
| Slug universe (outcome truth) | `data/v4/canonical/resolutions.parquet` | Apr 22 → May 21 | Chainlink-derived |
| 1m klines (signal source) | VPS3 `binance_klines_v2` (binance-spot-ws) | Apr 14 → May 21 19:32 | Same source production uses |
| Strategy code (signal spec) | VPS3 `/opt/tradingvenue/backend/app/strategies/polymarket/momo*.py` | — | Production spec re-implemented |
| No shadow data | — | — | Pure spec-compliant recompute |

**Strategies re-implemented (per VPS3 momo.py / momo_v2.py / updown_5m.py):**

```python
# momo v1 — forward 2-min window, fire at ws_s+120
ret_v1 = log(close@(ws_s+120) / close@ws_s)
fire if |ret_v1| >= q90(prior_14d_|ret_v1|)
signal = "UP" if ret_v1 > 0 else "DOWN"

# momo v2 — centered 2-min window, fire at ws_s+60
ret_v2 = log(close@(ws_s+60) / close@(ws_s-60))
fire if |ret_v2| >= q90(prior_14d_|ret_v2|)
signal = "UP" if ret_v2 > 0 else "DOWN"

# sniper — at-bar-close, fire at slot_start
ret_w = log(close@slot_start / close@(slot_start - window_s))
fire if |ret_w| >= q90 (5m) or q80 (15m) of prior_14d
signal = "UP" if ret_w > 0 else "DOWN"
```

`ws_s = slot_start − window_s` per CLAUDE.md.

## Per-cell WR — clean backtest (28d, 11,585 fires)

| Strategy | Cell | n | WR | Inverted WR | Verdict |
|---|---|--:|--:|--:|---|
| momo_v1 | btc_15m | 276 | 52.2% | 47.8% | normal |
| momo_v1 | btc_5m  | 862 | 48.4% | 51.6% | normal |
| momo_v1 | eth_15m | 291 | 48.1% | 51.9% | normal |
| momo_v1 | eth_5m  | 863 | 48.2% | 51.8% | normal |
| momo_v1 | sol_15m | 336 | 48.5% | 51.5% | normal |
| momo_v1 | sol_5m  | 1006 | 47.3% | 52.7% | normal |
| **momo_v2** | **btc_15m** | **274** | **52.5%** | **47.5%** | **NORMAL** |
| momo_v2 | btc_5m  | 843 | 48.3% | 51.7% | normal |
| momo_v2 | eth_15m | 279 | 52.0% | 48.0% | normal |
| **momo_v2** | **eth_5m**  | **861** | **47.2%** | **52.8%** | **NORMAL** |
| momo_v2 | sol_15m | 300 | 51.7% | 48.3% | normal |
| momo_v2 | sol_5m  | 958 | 46.2% | 53.8% | normal |
| sniper | btc_15m | 569 | 46.2% | 53.8% | normal |
| sniper | btc_5m  | 844 | 48.6% | 51.4% | normal |
| sniper | eth_15m | 588 | 46.3% | 53.7% | normal |
| sniper | eth_5m  | 853 | 44.0% | 56.0% | mild mean-reversion |
| sniper | sol_15m | 607 | 44.5% | 55.5% | mild mean-reversion |
| sniper | sol_5m  | 975 | 44.2% | 55.8% | mild mean-reversion |

Total: 11,585 fires. **No cell shows < 44% or > 53% WR.** No catastrophic results. No structural inversion (`inverted WR` is always within 5pp of `100 − orig WR`, as expected for non-broken signals).

## Comparison vs production claims

| Cell | Clean V2 base | Production V2+F7 | Spec-comparison verdict |
|---|--:|--:|---|
| **eth_5m_v2** | 47.15% WR (n=861) | **4.76% WR (n=63)** | **🔴 PRODUCTION BUG — spec gives 47%, production gives 5%** |
| **btc_15m_v2** | 52.55% WR (n=274) | **17.65% WR (n=34)** | **🔴 PRODUCTION BUG — spec gives 53%, production gives 18%** |
| btc_5m_v2 | 48.28% WR (n=843) | 42.27% WR (n=220) | within noise (production might still have mild bias) |
| eth_15m_v2 | 51.97% WR (n=279) | 64.58% WR (n=48) | production HIGHER — production-engine filters select good slugs |
| sol_5m_v2 | 46.24% WR (n=958) | 71.43% WR (n=56) | production HIGHER — same explanation |
| sol_15m_v2 | 51.67% WR (n=300) | 100% WR (n=6) | n=6 too small to compare |

**The asymmetry is the smoking gun:**
- 4 cells where production WR > clean spec WR → production-engine filtering selects good slugs (sparse-book, slug-age, hedge-skip filters work as designed)
- 2 cells where production WR << clean spec WR → production code has an inversion bug

A correctly-implemented filter (any filter) on a 47%-WR parent universe cannot produce a 5%-WR subset by random sampling. To go from 47% to 5%, the filter must be ACTIVELY ANTI-CORRELATED with outcome — which would require an inverted comparison somewhere in the production code.

## F7 lift on clean data — essentially zero

| Strategy | Cell | Base WR | F7 WR | Δ pp |
|---|---|--:|--:|--:|
| momo_v1 | eth_5m | 48.2% | 47.2% | −1.0 |
| momo_v1 | btc_15m | 52.2% | 53.2% | +1.0 |
| momo_v2 | eth_5m | 47.1% | 45.4% | −1.7 |
| momo_v2 | btc_15m | 52.5% | 53.4% | +0.9 |
| momo_v2 | sol_5m | 46.2% | 45.1% | −1.1 |

F7 (RSI(14) at ws_s alignment) adds ±1pp noise on clean data. **F7 alone is not a meaningful filter on the spec-compliant universe.** Production's "F7 lifts WR 44% → 51%" claim from the production data must therefore reflect interaction effects with other production filters, not the spec'd F7 logic.

## Where the bug likely lives

Given the strategy code (`momo_v2.py`) and the gate code (`f7_gate.py`) BOTH look spec-compliant when I reviewed them, the bug is most likely in:

1. **The controller's `_build_signal_aux` method** — where `ret_2m`, `rsi_14`, and `abs_ret_2m_threshold` are populated from raw klines. A sign-flip, wrong anchor, or stale-data bug here would explain the eth_5m_v2 catastrophe.

2. **Per-cell aux caching** — production may share an aux cache between cells incorrectly. e.g., btc_15m_v2 could be reading eth_5m_v2's ret_2m (or vice versa) due to a key collision. This would create the cell-specific inversion pattern we see.

3. **F7 RSI source mismatch** — if RSI(14) is computed on a DIFFERENT asset (e.g. always BTC regardless of slug asset), F7's "signal-RSI agreement" would be partially random on ETH/SOL cells. Production data shows ETH cells have the catastrophe; BTC cells don't (except btc_15m_v2's UP signal, which could be a different bug).

## Action for TV agent

Per the original [TV_AGENT_FIX_MOMO_V2_BUGS_2026_05_21.md](TV_AGENT_FIX_MOMO_V2_BUGS_2026_05_21.md):

1. **Disable 6 sleeves immediately** — eth_5m_v2 _f7 (3) + btc_15m_v2 _f7 (3).
2. **Audit `_build_signal_aux`** in production:
   - Print on every fire: `slug, ws_s, slot_start, ret_2m, abs_ret_2m_threshold, rsi_14, signal`.
   - Compare 100 fires from canonical clean recompute (this report's `all_fires.csv`) vs production logs.
   - The first mismatch on eth_5m_v2 or btc_15m_v2 reveals the bug.
3. **Per-cell aux key audit** — verify aux is keyed on (asset, tf, version) and there's no cross-cell sharing.

## Validation queries

After fix, this should hold (run against clean recompute or production logs):

```sql
-- WR per cell should be near 50% over 28 days
SELECT
  asset, tf, strategy,
  COUNT(*) AS n,
  ROUND(AVG(CASE WHEN won THEN 1.0 ELSE 0.0 END) * 100, 2) AS wr
FROM strategy_lab.markov_filter._results.clean_backtest_phase_a.all_fires
GROUP BY 1,2,3
ORDER BY 1,2,3;
```

All rows should show 44-54% WR. Any cell outside this range is suspect.

## Files

- `strategy_lab/markov_filter/clean_backtest_phase_a.py` — Phase A signal recompute (no L25 walk)
- `strategy_lab/markov_filter/clean_backtest_phase_a_with_gates.py` — adds F7 + Markov to clean fires
- `strategy_lab/markov_filter/_results/clean_backtest_phase_a/all_fires.csv` — 11,585 clean fires
- `strategy_lab/markov_filter/_results/clean_backtest_phase_a/all_fires_with_gates.csv` — with F7/Markov gate annotations
- `strategy_lab/markov_filter/_results/clean_backtest_phase_a/scorecard_clean.csv` — per (strategy, cell, gate) WR table

## Phase B (next)

This Phase A used outcome resolution only (won/lost from chainlink). Phase B will:

1. Load L25 book deltas (`data/v4/refresh_2026_05_*/cache/*_orderbook_L25*.parquet`)
2. Apply sub-second `book_walk_fill($25 notional)` at fire_us per `engine_v2.LiveMimicConfig`
3. Compute real PnL with Polymarket fee curve + 85ms latency
4. Per-sleeve $-PnL scorecard

This will give us the actual deployable PnL projection instead of just WR.

## Caveats

1. **No L25 walk yet** — Phase A only proves spec correctness on WR. PnL impact (vwap reflects pre-fire move) is Phase B.
2. **Clean fires every q90-gated slug** — production drops slugs with sparse books / late opens / hedge-skips. Production WR on the 4 "good" cells (eth_15m_v2, sol_5m_v2 etc.) reflects that selection, not just the F7 filter.
3. **My recompute uses ws_s = slot_start − window_s** per CLAUDE.md. If production code uses a different anchor convention, my reproduction would not match.
4. The "inversion" in cells like sniper / sol_5m (44.2% original, 55.8% inverted) is a mild mean-reversion bias — not catastrophic. Production cells showing 5% WR cannot come from this kind of bias; the production drop is 10× more extreme.
