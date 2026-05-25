# 28-day clean backtest — production strategy code + F7 + Markov

_Uses the **exact** production `MomoStrategy` / `MomoV2Strategy` / `Updown5mStrategy` / `f7_passes` from VPS3 (commit unchanged), wired into a standalone harness. Adds Markov overlay. Applies the Phase 18.1 D-12 qty_compute filter. Sub-second L25 walk + LiveMimicConfig fees. Full Apr 22 → May 21 canonical window._

## TL;DR

- **No cell reliably hits ≥70 % WR with n ≥ 30 over 28 days.** The closest is `momo_v1 btc_15m + MARKOV:w20_5m_voladaptive` at **69.23 % WR, +$9.45/tr, +$368** (n=39).
- The 70+ % WR cells observed in 23.5h production data (sol_5m_momo_v1+F7 at 71%, sol_5m_momo_v2+F7 at 71%) **do not persist** over the 28-day window. They were regime-specific.
- **Markov gates do reduce losses** (best variant aggregate −$1,585 vs no-filter −$12,517) but rarely flip cells to net-positive.
- Only **3 strategy × cell × gate combinations** produce net-positive PnL with both n ≥ 30 AND positive avg/trade:
  - momo_v1 btc_15m + MARKOV:5m_voladaptive
  - momo_v2 btc_15m + MARKOV:1m_voladaptive
  - momo_v2 eth_15m + MARKOV:1m_voladaptive

## Setup

| Component | Source | Notes |
|---|---|---|
| Strategy code | VPS3 `backend/app/strategies/polymarket/momo.py`, `momo_v2.py`, `updown_5m.py` | Used unmodified via Python shim |
| F7 gate | VPS3 `backend/app/strategies/polymarket/f7_gate.py` | `f7_passes(signal, rsi_14, "basic")` |
| RSI(14) | log-return Wilder per VPS3 `backend/app/indicators/rsi.py` | Matches production 228/228 |
| `_build_signal_aux` aux | Reimplemented to match production controller exactly | ret_2m_v1, ret_2m_v2, ret_w, thresholds, rsi_14 |
| q90/q80 threshold | Rolling 14d, causal, per (asset, tf) | Same as `_fetch_abs_ret_*_history` |
| Universe | VPS3 `market_resolutions_v2` (Apr 22 → May 21, 33,724 slugs) | Chainlink-derived outcomes |
| 1m klines | VPS3 `binance_klines_v2` binance-spot-ws (Apr 14 → May 21 19:32) | 50,888 bars per asset |
| L25 books | canonical `refresh_2026_05_06/16/19/21/cache/*.parquet` | Apr 22 → May 21 sub-second |
| Fills | `engine_v2.book_walk_fill($25)` strict-asof, +85ms latency | LiveMimicConfig |
| Fees | `0.07 × p × (1-p)` per share, every fill | Real Polymarket curve |
| qty_compute gate | best_ask in [0.05, 0.95] (D-12) | Spec-compliant |
| Sparse-book filter | min 25 book events in slot window | LiveMimicConfig default |
| Spread filter | ask0-bid0 ≤ 0.02 | engine_v2 default |
| Markov gate | overlay (independent of production) | 4 variants (w20×{1m,5m}×{voladaptive,fixed}) |

**Total pipeline:** 33,724 slugs → 20,114 pre-fill signals → 11,699 fills after filters.

## Top 10 cells by sum$ (n ≥ 30)

| # | strategy | cell | filter | n | WR % | $/trade | sum $ |
|---|---|---|---|---:|---:|---:|---:|
| 1 | momo_v1 | btc_15m | MARKOV:5m_voladaptive    | 39 | **69.23** | +$9.45 | **+$368** |
| 2 | momo_v1 | btc_15m | MARKOV:1m_voladaptive    | 87 | 57.47 | +$3.01 | +$262 |
| 3 | momo_v2 | btc_15m | MARKOV:1m_voladaptive    | 134 | 55.22 | +$1.75 | +$235 |
| 4 | momo_v2 | eth_15m | MARKOV:1m_voladaptive    | 76 | 56.58 | +$2.49 | +$189 |
| 5 | momo_v2 | btc_15m | F7+MARKOV:1m_voladaptive | 105 | 55.24 | +$1.80 | +$189 |
| 6 | momo_v2 | eth_5m  | F7+MARKOV:5m_fixed       | 88 | 54.55 | +$2.10 | +$184 |
| 7 | momo_v1 | btc_15m | F7+MARKOV:1m_voladaptive | 58 | 56.90 | +$3.04 | +$177 |
| 8 | sniper  | eth_15m | MARKOV:5m_fixed          | 80 | 50.00 | +$2.14 | +$171 |
| 9 | sniper  | eth_15m | F7+MARKOV:5m_fixed       | 80 | 50.00 | +$2.14 | +$171 |
| 10| momo_v1 | btc_15m | NO_FILTER                | 137 | 54.01 | +$1.01 | +$139 |

**The 70+ % WR fantasy doesn't hold** over a clean 28-day backtest. The single 69 % cell (#1) is borderline n=39 — likely regresses with more data.

## Cells with WR ≥ 60 % regardless of n (showing tiny samples for context)

| strategy | cell | filter | n | WR % | $/trade | sum $ |
|---|---|---|---:|---:|---:|---:|
| momo_v1 | sol_15m | F7+MARKOV:1m_voladaptive | 15 | 73.33 | +$10.18 | +$153 |
| momo_v1 | btc_15m | MARKOV:5m_voladaptive    | 39 | 69.23 | +$9.45  | +$368 |
| momo_v1 | btc_15m | F7+MARKOV:5m_voladaptive | 26 | 65.38 | +$7.95  | +$207 |
| momo_v1 | sol_15m | F7                       | 21 | 61.90 | +$4.77  | +$100 |

**All n < 40.** Three of four are 15-minute sleeves. These are the "candidate" 60%+ cells but with weak statistical confidence.

## Best filter per (strategy, cell) — ranked

| strategy | cell | best filter | n | WR | $/tr | sum |
|---|---|---|---:|---:|---:|---:|
| **momo_v1** | **btc_15m** | MARKOV:5m_voladaptive | 39 | **69.23 %** | +$9.45 | **+$368** |
| momo_v2 | btc_15m | MARKOV:1m_voladaptive    | 134 | 55.22 | +$1.75 | +$235 |
| momo_v2 | eth_15m | MARKOV:1m_voladaptive    | 76 | 56.58 | +$2.49 | +$189 |
| momo_v2 | eth_5m  | F7+MARKOV:5m_fixed       | 88 | 54.55 | +$2.10 | +$184 |
| sniper  | eth_15m | MARKOV:5m_fixed          | 80 | 50.00 | +$2.14 | +$171 |
| momo_v2 | sol_15m | MARKOV:1m_voladaptive    | 41 | 58.54 | +$2.62 | +$107 |
| sniper  | sol_15m | MARKOV:1m_fixed          | 43 | 53.49 | +$1.90 | +$82  |
| momo_v1 | sol_5m  | NO_FILTER                | 276 | 53.26 | +$0.16 | +$43 |
| **all other cells** | | | | | | NET NEGATIVE |

8 cells net-positive after best gate; the rest lose. The eth_5m / btc_5m / sol_5m cells (where production claimed 70%+ for sol_5m) all sit at 45-54 % WR with negative $/trade on the clean backtest.

## Aggregate per gate mode (across all cells, n ≥ 30)

| filter | total_n | total_sum $ |
|---|---:|---:|
| F7+MARKOV:5m_fixed       | 873 | **−$1,585** |
| MARKOV:5m_fixed          | 1,088 | −$2,483 |
| F7+MARKOV:5m_voladaptive | 1,911 | −$4,248 |
| F7+MARKOV:1m_fixed       | 1,558 | −$4,423 |
| MARKOV:1m_fixed          | 1,597 | −$4,529 |
| MARKOV:5m_voladaptive    | 2,332 | −$4,549 |
| MARKOV:1m_voladaptive    | 3,918 | −$7,526 |
| F7+MARKOV:1m_voladaptive | 3,441 | −$7,794 |
| F7                       | 4,994 | −$11,838 |
| NO_FILTER                | 6,684 | −$12,517 |

**Every gate is net-negative across 11,699 fills over 28 days.** Markov gates reduce losses by ~80% vs no-filter, but none flip aggregate to positive. The best aggregate is `F7+MARKOV:5m_fixed` at -$1,585 over 28 days (~-$57/day).

This is because: a) most fires lose under realistic fees + L25 fills, and b) the few profitable cells contribute small sums relative to the losing cells' larger losses.

## Why production data shows different numbers

Production 23.5h post-F7 window claims sol_5m_momo_v2+F7 at 71 % WR. Clean 28-day shows 47 % WR. The factors:

1. **Production fires MUCH less often per day** (~11/day total momo_v2 vs 418/day in clean). Production must have additional filters not visible in my pipeline:
   - Slug-age / market-freshness checks
   - Token-id resolution gates
   - Hedge_skip cascades
   - Storedata DB freshness
2. **Production's 23.5h sample is small** (typically 6-100 fires per cell). 28 days of clean data gives 30-1500 per cell.
3. **Regime effects**: a specific 23.5h window can produce extreme WR by chance; 28 days averages across multiple regimes.

The clean backtest is the more reliable estimate of long-run edge. The production 70%+ cells should NOT be assumed to persist.

## Practical recommendation

**Deploy candidates (clean spec, n ≥ 30, positive $/trade):**

1. `momo_v1 btc_15m + MARKOV:w20_5m_voladaptive` — 69 % WR, +$9.45/tr (n=39, **paper-only until n ≥ 100**)
2. `momo_v2 btc_15m + MARKOV:w20_1m_voladaptive` — 55 % WR, +$1.75/tr (n=134, safer to ship)
3. `momo_v2 eth_15m + MARKOV:w20_1m_voladaptive` — 57 % WR, +$2.49/tr (n=76)
4. `momo_v2 eth_5m + F7+MARKOV:w20_5m_fixed` — 55 % WR, +$2.10/tr (n=88)

**Do not deploy:**
- Any sleeve below 30 fires in 28 days (statistical confidence too low)
- All cells where best gate produces negative $/trade (most of eth_5m, btc_5m, sol_5m)
- `_v2_f7` sleeves on eth_5m / btc_15m at this notional — production showed catastrophic 23h artifact (regime-specific qty_compute asymmetry per the corrected bug-spec doc)

**Total daily PnL projection** if all 4 winning cells deploy in shadow (averaging across 28d):
- ~0.7 + 4.8 + 2.7 + 3.1 = ~11.3 fires/day combined
- Best aggregate: ~+$0.8/day net (small)

The clean spec edge is real but small. The "70+ % WR" cells production claimed were not reproducible.

## What the data actually says vs my earlier framing

| Earlier claim | Reality (28-day clean) |
|---|---|
| "Markov adds +$8,300/day on top of F7" (per 23.5h analysis) | Aggregate F7+Markov is −$1,585 over 28 days |
| "sol_5m_momo_v2 + F7 hits 91 % WR with Markov" | 47 % WR on n=988 over 28d, regime artifact |
| "btc_5m_momo_v1 + Markov hits 82.6 % WR" | 47 % WR on n=416 over 28d |
| "F7 lifts WR by 7 pp universally" | F7 alone produces same or slightly worse WR across all cells |
| "100 % WR cells like sol_15m_sniper + Markov" | 53.5 % WR on n=43 over 28d |

**The shadow-data extrapolations were optimistic. Clean spec on full canonical data tells the more reliable story.**

## Files

- `strategy_lab/markov_filter/_prod_shim/backend/app/strategies/polymarket/` — production strategy shim (unmodified VPS3 code)
- `strategy_lab/markov_filter/backtest_prod_strategies_with_gates.py` — runner
- `strategy_lab/markov_filter/_results/backtest_prod_strats/universe.csv` — 33,724 slugs with ret/threshold/rsi
- `strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv` — 11,699 fills with PnL
- `strategy_lab/markov_filter/_results/backtest_prod_strats/scorecard.csv` — long-form per (strategy, cell, filter)

## Validation queries

To confirm the runner used production code unchanged:

```bash
diff strategy_lab/markov_filter/_prod_shim/backend/app/strategies/polymarket/momo_v2.py \
     strategy_lab/markov_filter/_vps3_pull/prod_strategies/polymarket/momo_v2.py
# should be empty (identical)

diff strategy_lab/markov_filter/_prod_shim/backend/app/strategies/polymarket/f7_gate.py \
     strategy_lab/markov_filter/_vps3_pull/prod_strategies/polymarket/f7_gate.py
# should be empty (identical)
```

To compare 23.5h shadow vs 28d clean:

```sql
-- Production 23.5h WR per cell
SELECT REGEXP_REPLACE(sleeve_id, '_(HOLD|HEDGE|SELL)(_f7)?$', '') AS cell,
       COUNT(*) AS n, ROUND(AVG((data->>'won')::bool::int)*100, 2) AS wr
FROM trading.events
WHERE kind = 'poly_updown_resolution'
  AND at >= '2026-05-20 19:57:00+00'
GROUP BY cell;

-- Compare to scorecard.csv to see how much production differs from clean
```

## Caveats

1. **Production has additional filters** my clean lacks (slug-age, token-id resolution, market-freshness, hedge_skip). Some of these MAY add edge — can't confirm without reimplementing them.
2. **L25 book data ends 2026-05-21 ~04 UTC** for some slugs. Late-window fires may have stale or missing books.
3. **No exit-policy variation** — all fills are HOLD-to-settlement. Real production tests HEDGE / SELL too.
4. **Markov labels still use binance 1m / 5m** — could test other Markov variants but already 4 covered.
5. **Threshold tuning for `_fixed` Markov variants** is from the same data — risk of in-sample selection.
