# Markov vs F7 — per-sleeve gate comparison (full canonical universe)

_Each sleeve treated as an independent strategy. No aggregation across sleeves — they have different signal microstructure and the best filter for one cell may regress another._

## Setup

- **Source**: `data/v4/canonical/_results/full_universe_live_mimic_2026_05_16/per_trade.csv`
- **Window**: 2026-04-25 → 2026-05-15 (~21 days)
- **Universe**: 516 momo fires (q90 |ret_2m| gated) across 8 sleeves
- **PnL**: HOLD-to-settlement, computed from raw `shares_e`, `usd_e`, `fee_in` columns. Outcome resolved via chainlink. Fees from live-mimic engine (real Polymarket fee curve `0.07 × p × (1−p)`).
- **Filters tested**: 13 — NO_FILTER, F7, 4×MARKOV, 4×F7+MARKOV, notF7, 2×notF7+MARKOV
- **Asset coverage in this dataset is BTC-dominated** (477 BTC, 38 ETH, 1 SOL) — SOL sleeves out of scope. **eth_15m_v2 (n=2) and sol_5m_v2 (n=1) too small to evaluate**.

## TL;DR — best filter per sleeve

| Sleeve         | n   | baseline WR | baseline $/trade | **Best filter**                       | n_kept | best WR | best $/trade | **lift $/trade** |
|----------------|----:|------------:|------------------:|---------------------------------------|-------:|--------:|--------------:|------------------:|
| **btc_15m_v1** |  47 |       57.45 |           +$2.83 | `MARKOV:w20_1m_voladaptive`           |     26 |   61.54 |       +$5.44 | **+$2.61**       |
| **btc_15m_v2** |  64 |       51.56 |           −$0.35 | `notF7 + MARKOV:w20_1m_voladaptive`   |     32 |   59.38 |       +$3.83 | **+$4.18**       |
| **btc_5m_v1**  | 161 |       49.07 |           −$1.35 | `notF7` (alone)                       |     66 |   59.09 |       +$3.23 | **+$4.58**       |
| **btc_5m_v2**  | 205 |       47.80 |           −$1.88 | `F7 + MARKOV:w20_1m_fixed`            |     54 |   50.00 |       −$0.11 | **+$1.77**       |
| **eth_5m_v2**  |  25 |       40.00 |           −$6.14 | `MARKOV:w20_5m_voladaptive`           |     10 |   50.00 |       −$0.69 | **+$5.45**       |
| eth_5m_v1      |  11 |       36.36 |           −$8.29 | (no filter beats baseline)            |        |         |               | 0                |
| eth_15m_v2     |   2 |             |                  | n too small                           |        |         |               |                  |
| sol_5m_v2      |   1 |             |                  | n too small                           |        |         |               |                  |

**No universal winner.** Five sleeves have different optimal filters. Three cells need F7 *inverted* (`notF7`) to escape the baseline loss.

## Sleeve-by-sleeve detail

### btc_15m_v1 — Markov directly LIFTS a profitable cell
Baseline already +$2.83/trade, 57% WR. Markov tightens to top-quality fires.

| filter                             |  n  | WR   | avg     | sum     | keep% |
|------------------------------------|----:|-----:|--------:|--------:|------:|
| NO_FILTER                          |  47 | 57.5 | +$2.83  | +$133   | 100   |
| F7_only                            |  15 | 60.0 | +$3.96  |  +$59   |  32   |
| **MARKOV:w20_1m_voladaptive**      | **26** | **61.5** | **+$5.44** | **+$141** | **55** |
| MARKOV:w20_5m_voladaptive          |  13 | 69.2 | +$10.03 | +$130   |  28   |
| F7+MARKOV:w20_5m_voladaptive       |   4 | 75.0 | +$12.52 |  +$50   |   9   |

Notable: w20_5m_voladaptive alone lifts to +$10/trade but n=13 (low confidence). w20_1m_voladaptive keeps a much larger sample with still-strong +$5.44.

---

### btc_15m_v2 — F7 BACKWARDS; invert it + Markov
Baseline already near breakeven (−$0.35), but **F7 makes it much worse** (−$9.20). The `notF7` mirror is the real edge.

| filter                                |  n  | WR   | avg     | sum     | keep% |
|---------------------------------------|----:|-----:|--------:|--------:|------:|
| NO_FILTER                             |  64 | 51.6 | −$0.35  | −$23    | 100   |
| F7_only                               |  12 | 33.3 | −$9.20  | −$110   |  19   |
| MARKOV:w20_1m_voladaptive             |  42 | 52.4 | +$0.35  |  +$15   |  66   |
| notF7                                 |  52 | 55.8 | +$1.69  |  +$88   |  81   |
| **notF7 + MARKOV:w20_1m_voladaptive** | **32** | **59.4** | **+$3.83** | **+$123** | **50** |

This sleeve loses money when F7 is on. Removing F7 and adding Markov flips it from −$0.35 to +$3.83/trade.

---

### btc_5m_v1 — Just kill F7 (Markov adds nothing)
Baseline loses −$1.35/trade. F7 actively HARMS (−$4.53). `notF7` alone flips it positive (+$3.23). Markov on top of notF7 doesn't add lift.

| filter                          |   n  | WR   | avg     | sum     | keep% |
|---------------------------------|-----:|-----:|--------:|--------:|------:|
| NO_FILTER                       | 161  | 49.1 | −$1.35  | −$217   | 100   |
| F7_only                         |  95  | 42.1 | −$4.53  | −$430   |  59   |
| MARKOV:w20_1m_voladaptive       |  93  | 46.2 | −$2.68  | −$249   |  58   |
| MARKOV:w20_5m_voladaptive       |  49  | 51.0 | −$0.15  |   −$8   |  30   |
| **notF7** (alone)               | **66** | **59.1** | **+$3.23** | **+$213** |  **41** |
| notF7 + MARKOV:w20_1m_voladaptive | 25 | 60.0 | +$3.88  |  +$97   |  16   |

Conclusion: F7 is hurting this sleeve. Deploy `notF7` (signal aligned only when RSI DIS-agrees).

---

### btc_5m_v2 — F7 + Markov BOTH help; combined gate is best
The one sleeve where F7 lifts. Markov adds a bit more.

| filter                          |   n  | WR   | avg     | sum     | keep% |
|---------------------------------|-----:|-----:|--------:|--------:|------:|
| NO_FILTER                       | 205  | 47.8 | −$1.88  | −$386   | 100   |
| F7_only                         | 148  | 50.0 | −$0.65  |  −$96   |  72   |
| MARKOV:w20_1m_voladaptive       | 110  | 49.1 | −$1.14  | −$125   |  54   |
| **F7 + MARKOV:w20_1m_fixed**    |  **54** | **50.0** | **−$0.11** |   **−$6** |  **26** |
| F7 + MARKOV:w20_1m_voladaptive  |  92  | 51.1 | −$0.15  |  −$13   |  45   |

Not quite breakeven but the best combo cuts the per-trade loss from −$1.88 to nearly zero on a 26%-keep gate (n=54).

---

### eth_5m_v2 — Markov ONLY (no F7), small sample but striking
Baseline loses −$6.14/trade. F7 makes it worse. `MARKOV:w20_5m_voladaptive` (5-min bars) cuts it to −$0.69 on n=10.

| filter                            |  n  | WR   | avg     | sum     |
|-----------------------------------|----:|-----:|--------:|--------:|
| NO_FILTER                         |  25 | 40.0 | −$6.14  | −$154   |
| F7_only                           |  17 | 29.4 | −$10.89 | −$185   |
| **MARKOV:w20_5m_voladaptive**     | **10** | **50.0** | **−$0.69** |   **−$7** |
| notF7                             |   8 | 62.5 | +$3.95  |  +$32   |

Notable: `notF7` flips it to +$3.95 on n=8 — too small but consistent direction.

Caveat: n=10 is the danger zone for confidence. Need more data before deploying.

---

### eth_5m_v1, eth_15m_v2, sol_*  — too small

n=11 / 2 / 1 / 0. Cannot conclude.

## Why F7 looks reversed on backtest vs production

The production F7 lift report ([F7_AND_RESIDUAL_FIX_VERIFICATION_2026_05_21.md](strategy_lab/reports/F7_AND_RESIDUAL_FIX_VERIFICATION_2026_05_21.md)) showed F7 lifting WR 44% → 51% and PnL −$5,241 → +$192 over 36h post-deploy. This backtest shows F7 *reducing* WR on most sleeves. Three possible explanations:

1. **Different universe**: backtest fires every slug whose `|ret_2m| ≥ q90` crosses the gate. Production sleeves add sparse-book filter, slug-age filter, hedge_skip checks. Production's fire universe is a *subset* of the backtest universe — and probably the more profitable subset.
2. **Different fill modeling**: backtest uses L25 ASK walk at fire_us; production has live WS feeds and a ~85ms latency budget. Production's actual vwap may differ.
3. **Sample window**: backtest is Apr 25 → May 15 (21 days). Production F7 evaluation is May 20-21 (36h). Different market regime.

The pattern is consistent with finding (1): F7 is good FILTER for the subset of fires the production engine takes, but a bad filter for the broader universe. Markov, on the other hand, lifts on most sleeves' broader universes — suggesting it's a more robust gate.

## What to do

1. **`btc_15m_v1`**: Add `MARKOV:w20_1m_voladaptive` gate. Expected lift +$2.61/trade on the cell. Sample n=26 over 21d → ~1.2 fires/day.
2. **`btc_15m_v2`**: TV-agent spec — replace F7 with `notF7 + MARKOV:w20_1m_voladaptive`. Expected lift +$4.18/trade. Sample n=32 → ~1.5/day.
3. **`btc_5m_v1`**: TV-agent spec — replace F7 with `notF7` only. Expected lift +$4.58/trade. Sample n=66 → ~3/day.
4. **`btc_5m_v2`**: Keep F7 + add `MARKOV:w20_1m_fixed`. Expected lift +$1.77/trade. Sample n=54 → ~2.5/day.
5. **`eth_5m_v2`**: Add `MARKOV:w20_5m_voladaptive`. n=10 is danger zone — paper-deploy and observe.

**Don't ship #2 / #3 ("notF7 replaces F7") until validated on post-F7 data.** The backtest evidence is the entire basis for the F7-inversion idea. Production already ran 36h of F7 successfully, so two possibilities exist:
- Production F7 ≠ backtest F7 (different fill model). Inversion may not generalize.
- Backtest captures truth that production missed. Worth validating.

**Validation plan for next session:**

1. Refresh canonical klines + trading_events to include May 20-24 (post-F7 deploy).
2. Run this same per-sleeve compare on post-F7 production fires.
3. Compare per-sleeve direction of F7 lift between backtest and production.
4. If `notF7` consistently beats `F7` in production for `btc_5m_v1` and `btc_15m_v2`, send a TV-agent spec to flip the F7 sign for those two cells only.

## Files

- `strategy_lab/markov_filter/full_universe_gate_compare.py` — runner
- `strategy_lab/markov_filter/_results/full_universe_gate_compare/fires_with_gates.csv` — per-fire labels
- `strategy_lab/markov_filter/_results/full_universe_gate_compare/per_sleeve_full.csv` — long-form table for every (sleeve × filter)
- `strategy_lab/markov_filter/_scratch_per_sleeve_full.py` — per-sleeve dump generator

## Caveats

- BTC-heavy sample. SOL sleeves untestable from this CSV (1 fire). To test SOL sleeves: re-run live-mimic engine with looser sparse-book filter, or extend window.
- 21-day window. Threshold tuning for fixed-mode Markov was set on this same window — risk of in-sample overfit on `_fixed` variants.
- Live-mimic uses real Polymarket fees + ~85ms latency. Outcomes are chainlink-derived. PnL is HOLD-to-settlement (no early sell/hedge).
- Each sleeve's best filter requires n≥10 — `eth_5m_v2`, `btc_15m_v1` are on the edge.
