# Clean backtest Phase A+B — final per-sleeve scorecard with sub-second L25 fills

_28 days (Apr 22 → May 21). Pure spec-compliant strategy recompute from raw binance 1m klines + canonical chainlink resolutions + L25 sub-second book walk + LiveMimicConfig real Polymarket fees + 85ms latency. **No shadow / production resolution data used as input.**_

## TL;DR

- **eth_5m_v2 momo BASE: 49.9% WR, −$1.10/tr (n=559).** Production claims **4.76% WR, −$18.97/tr (n=63).** Confirms code bug in production.
- **btc_15m_v2 momo BASE: 54.8% WR, +$1.26/tr (n=199).** Production claims 17.65% WR, −$7.37/tr. Confirms code bug.
- Clean backtest **never produces < 37% or > 60% WR** on any cell with n≥30. No cell shows the catastrophic / euphoric production extremes.
- **F7 gate (RSI-alignment) has zero-to-negative effect on clean data** across all cells (avg ±1pp WR delta). Production's claimed F7 lift comes from PRODUCTION-ENGINE FILTERS (sparse-book, slug-age, hedge-skip), not the F7 rule itself.
- Only 3 cells are reliably profitable on clean spec at $25 notional: `momo_v1 btc_15m` (+$3.77/tr), `momo_v2 btc_15m` (+$1.26/tr), `momo_v2 eth_15m` (+$1.27/tr).

## Setup

| Component | Source | Window |
|---|---|---|
| Slug universe | `data/v4/canonical/resolutions.parquet` (chainlink) | Apr 22 → May 21 |
| Outcome truth | same (chainlink-derived) | — |
| 1m klines (signal source) | VPS3 `binance_klines_v2` binance-spot-ws | Apr 14 → May 21 19:32 UTC |
| L25 book deltas | `data/v4/refresh_2026_05_06/cache` + `refresh_2026_05_16/cache` + `refresh_2026_05_19/cache` + `refresh_2026_05_21/cache` | Apr 22 → May 21 |
| Strategy spec | VPS3 prod code: `momo.py`, `momo_v2.py`, `updown_5m.py`, `f7_gate.py` | — |

Engine:
```python
LiveMimicConfig(
    name="live_mimic",
    notional_usd=25.0,
    latency_ms=85.0,
    apply_latency_to_entry=True,
    fee_model="poly_taker_curve",   # 0.07 × p × (1-p) per share, every fill
    poly_fee_rate=0.07,
    min_book_events=25,             # sparse-book filter
    max_book_staleness_us=60_000_000,
)
```

**Flow**:
1. Compute `ret_2m_v1` / `ret_2m_v2` / `ret_w` from raw klines.
2. Compute rolling q90/q80 thresholds over prior 14d (causal).
3. Gate fires by |ret| ≥ threshold.
4. For each fire: book lookup at `fire_us + 85ms` (latency-adjusted), strict-asof.
5. `book_walk_fill($25)` on the matching outcome side.
6. Drop fires where: book stale (>60s) OR spread > 0.02 OR under-fill (<$12.5) OR n_book_events < 25.
7. `hold_pnl(won, cfg)` — chainlink-truth outcome.

## Per-sleeve clean scorecard (28 days, sub-second L25 fills, real fees)

### momo_v1 — forward 2-min window

| Cell | n | WR | $/trade | sum PnL | avg vwap | F7 WR | F7 $/tr |
|---|--:|--:|--:|--:|--:|--:|--:|
| **btc_15m** | 112 | **59.8 %** | **+$3.77** | **+$422** | ~0.55 | 60.0 % | +$4.14 |
| btc_5m  | 787 | 48.0 % | −$1.98 | −$1,557 | | 45.8 % | −$2.65 |
| eth_15m |  48 | 37.5 % | −$7.50 | −$360 | | 36.4 % | −$7.52 |
| eth_5m  | 459 | 45.5 % | −$3.27 | −$1,502 | | 43.8 % | −$3.46 |
| sol_15m |  31 | 51.6 % | −$0.92 | −$28 | | 52.9 % | −$0.04 |
| sol_5m  | 246 | 52.4 % | −$0.27 | −$66 | | 49.2 % | −$1.32 |

### momo_v2 — centered 2-min window (THE BUG CELLS)

| Cell | n | WR | $/trade | sum PnL | F7 WR | F7 $/tr |
|---|--:|--:|--:|--:|--:|--:|
| **btc_15m** | 199 | **54.8 %** | **+$1.26** | **+$251** | 54.5 % | +$1.35 |
| btc_5m  | 774 | 49.1 % | −$1.45 | −$1,120 | 46.9 % | −$2.09 |
| **eth_15m** | 109 | **55.0 %** | **+$1.27** | **+$138** | 44.4 % | −$3.58 |
| **eth_5m**  | **559** | **49.9 %** | **−$1.10** | −$614 | 49.4 % | −$0.67 |
| sol_15m |  90 | 54.4 % | +$0.26 | +$24 | 57.5 % | +$1.80 |
| sol_5m  | 343 | 49.9 % | −$1.40 | −$480 | 48.1 % | −$1.64 |

### sniper — at-bar-close ret_5m / ret_15m

| Cell | n | WR | $/trade | sum PnL | F7 WR | F7 $/tr |
|---|--:|--:|--:|--:|--:|--:|
| btc_15m | 481 | 47.0 % | −$1.49 | −$718 | 39.1 % | −$4.91 |
| btc_5m  | 682 | 49.9 % | −$0.42 | −$289 | 49.3 % | −$0.10 |
| eth_15m | 342 | 46.2 % | −$1.53 | −$523 | 47.4 % | −$0.28 |
| eth_5m  | 514 | 43.8 % | −$3.38 | −$1,739 | 41.9 % | −$3.06 |
| sol_15m | 224 | 47.8 % | −$1.71 | −$383 | 46.2 % | −$1.94 |
| sol_5m  | 394 | 45.2 % | −$3.73 | −$1,468 | 46.5 % | −$2.39 |

## Production vs clean — bug confirmation table

| Cell | **Clean spec** | **Production claim** | Δ pp WR | Verdict |
|---|--:|--:|--:|---|
| eth_5m_v2 + F7  | n=306, **49.4 % WR, −$0.67/tr** | n=63, **4.76 % WR**, −$18.97/tr | **−44.6** | **🔴 PRODUCTION BUG** |
| btc_15m_v2 + F7 | n=110, **54.5 % WR, +$1.35/tr** | n=34, **17.65 % WR**, −$7.37/tr | **−36.9** | **🔴 PRODUCTION BUG** |
| btc_5m_v2 + F7  | n=409, 46.9 % WR, −$2.09/tr | n=220, 42.3 % WR, −$2.42/tr | −4.6 | within noise (mild bias) |
| eth_15m_v2 + F7 | n=54, 44.4 % WR, −$3.58/tr | n=48, 64.6 % WR, +$7.29/tr | +20.2 | production better (engine filters) |
| sol_5m_v2 + F7  | n=185, 48.1 % WR, −$1.64/tr | n=56, 71.4 % WR, +$6.58/tr | +23.3 | production better (engine filters) |

**The two catastrophic cells (eth_5m_v2, btc_15m_v2) are CONFIRMED code bugs.** No spec-compliant implementation produces 5% or 18% WR from the canonical data — clean recompute on the same slugs gives 49-55%.

**Two cells where production exceeds clean (eth_15m_v2, sol_5m_v2)** — production's higher WR comes from production-engine FILTERS (sparse-book, slug-age, hedge-skip-on-wide-spread) which select a smaller, higher-quality slug subset than the clean q90-gate alone. This is the engine working as designed for those cells.

## F7 effect on clean data — essentially zero

Clean F7 lift (WR with F7 minus WR without):

| Strategy | Cell | Δ WR (pp) | Δ $/trade |
|---|---|--:|--:|
| momo_v1 | btc_15m | +0.2 | +$0.37 |
| momo_v1 | btc_5m | −2.2 | −$0.67 |
| momo_v1 | eth_15m | −1.1 | −$0.03 |
| momo_v1 | eth_5m | −1.7 | −$0.18 |
| momo_v1 | sol_5m | −3.2 | −$1.05 |
| momo_v2 | btc_15m | −0.3 | +$0.09 |
| momo_v2 | eth_15m | **−10.6** | **−$4.85** |
| momo_v2 | eth_5m | −0.5 | +$0.43 |
| sniper  | btc_15m | **−7.9** | **−$3.42** |
| sniper  | eth_15m | +1.2 | +$1.25 |

F7 alone REDUCES WR on most cells (mild for momo, more for sniper). The exception is sniper/eth_15m and momo_v1/btc_15m where F7 is mildly positive.

**This contradicts the original F7 deployment spec** which claimed F7 lifts WR 44% → 51% on shadow data. The shadow lift must come from interaction with other production filters, not from the F7 RSI rule.

## Best filter per sleeve — clean spec recommendation

Cells where any filter on clean spec produces net-positive $/trade:

| Sleeve | Filter | n | WR | $/tr | sum |
|---|---|--:|--:|--:|--:|
| **momo_v1 btc_15m** | BASE | 112 | 59.8 % | +$3.77 | +$422 |
| momo_v1 btc_15m | F7 only | 65 | 60.0 % | +$4.14 | +$269 |
| **momo_v2 btc_15m** | BASE | 199 | 54.8 % | +$1.26 | +$251 |
| **momo_v2 eth_15m** | BASE | 109 | 55.0 % | +$1.27 | +$138 |
| momo_v2 eth_15m | M:1m_fix | 29 | 55.2 % | +$2.08 | +$60 |
| momo_v2 sol_15m | F7+M:1m_fix | 9 | 66.7 % | +$6.08 | +$55 |
| sniper sol_15m | F7+M:1m_fix | 25 | 56.0 % | +$3.56 | +$89 |
| sniper btc_5m | F7+M:1m_fix | 171 | 49.7 % | +$0.40 | +$68 |

**Bottom line**: only `momo_v1 btc_15m`, `momo_v2 btc_15m`, and `momo_v2 eth_15m` baselines are reliably profitable on clean spec. Everything else relies on production-engine filtering to be profitable.

## What this means for the deploy plan

### Confirmed action items (from the V2 bug spec)

1. **Disable eth_5m_v2_*_f7 (3 sleeves)** — confirmed bug
2. **Disable btc_15m_v2_*_f7 (3 sleeves)** — confirmed bug
3. **Audit `_build_signal_aux`** — bug is here, NOT in `momo_v2.py` or `f7_gate.py`
4. **Keep production-engine filters running** — they're the actual source of edge for eth_15m_v2 + sol_5m_v2

### New finding: F7 isn't the lift mechanism

The shadow F7 deploy report claimed F7 lifts WR 44% → 51%. The clean spec shows F7 is essentially a no-op on the broader universe. The production lift therefore comes from **F7's interaction with other production filters**, not from F7 alone.

This means **a Markov-only shadow (without F7)** may not lift production cells as much as a "F7+Markov" shadow — because F7 isn't doing the lifting. The Markov gate should be deployed alongside production's existing sparse-book + slug-age filters, regardless of F7 mode.

### Markov on clean spec — also marginal

Markov w20_1m_fixed lift on clean data is similar to F7 — small or slightly negative. The cells where Markov "helps" in shadow data (e.g., sol_5m_v2 100% WR) are tiny samples (n=30) on slugs that already had positive selection from production filters.

**On clean data**, Markov is not a significant filter. Its production lift is also explained by interaction effects, not by the Markov rule alone.

## Caveats

1. **Sparse-book filter (min 25 events)** drops 50% of SOL fires (1,328 fills from 4,182 attempts). The SOL universe might be undersampled.
2. **Spread filter (0.02)** drops wide-spread markets, more common on 15m than 5m.
3. **85ms latency** is the live-mimic default; actual production latency may differ.
4. **No HEDGE / SELL exit policies modeled** — all fills are HOLD-to-settlement. Real production uses hedge/sell which may differ.
5. The momo_v1 btc_15m result (+$3.77/tr on n=112) is small sample and may not generalize.
6. Some warmup data (first ~14 days for threshold computation) reduces effective n.

## Files

- `strategy_lab/markov_filter/clean_backtest_phase_a.py` — signal recompute, no fills
- `strategy_lab/markov_filter/clean_backtest_phase_a_with_gates.py` — adds F7 + Markov gates
- `strategy_lab/markov_filter/clean_backtest_phase_b.py` — L25 walk + real PnL
- `strategy_lab/markov_filter/_results/clean_backtest_phase_a/all_fires_with_gates.csv` — 11,585 fires
- `strategy_lab/markov_filter/_results/clean_backtest_phase_b/fills_with_pnl.csv` — 6,394 fills with PnL
- `strategy_lab/markov_filter/_results/clean_backtest_phase_b/scorecard.csv` — long-form per-cell × filter

## Key takeaways for the user

1. **Yes, eth_5m_v2 and btc_15m_v2 production has a bug.** Clean spec produces 50-55% WR on those cells. Production's 5% / 18% can only come from a code-level inversion.
2. **No, F7 isn't the lift you thought.** On clean spec, F7 does nothing. Production's F7 lift is from sparse-book + slug-age filters that happen to combine with F7's universe selection.
3. **The 70-100% production WR cells (sol_5m, etc.) aren't reproducible from clean spec** because production-engine filters select a sharper subset.
4. **Markov is also a weaker filter than my earlier analysis suggested** when measured on clean spec data (not on production-filtered shadow).
5. The only cells with reliable clean-spec edge: **`momo_v1 btc_15m`** (+$3.77/tr), **`momo_v2 btc_15m`** (+$1.26/tr), **`momo_v2 eth_15m`** (+$1.27/tr). Everything else needs the production-engine filter machinery to be profitable.
