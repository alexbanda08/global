# Strategy E — L25 Book Microstructure

**Date:** 2026-05-16
**Verdict: NULL** (book microstructure imbalance at the L25 top-5 levels does not produce tradable alpha after realistic-fill economics are applied).

## Files
- `strat_E_book_micro.py` — script (288 lines)
- `strat_E_results.csv` — full sweep (120 rows: 5 setups × 3 assets × 4 cutoffs × spread on/off)
- `strat_E_no_lookahead_examples.json` — 6 sample trades with book_ts < entry_us
- `strat_E_run.log` — run log (~28 min wall time)

## Hypothesis tested
At the YES/NO order book: top-5 bid/ask imbalance (`Σbid[0..4] / (Σbid[0..4]+Σask[0..4])` on Up-side), 30-s mid drift, and book slope (vwap of $1000 walk − vwap of $100 walk) predict short-term mid drift, which correlates with eventual outcome.

## Setups (5)
1. 5m markets, entry at `ws_s + 120` (production momo fire-time)
2. 5m markets, entry at `slot_end − 60s` (4 min into 5m window)
3. **15m markets, entry at `slot_end − 60s`** (14 min into 15m window — user's specific ask)
4. 15m markets, entry at `slot_end − 180s`
5. 5m markets, fire-time, combined imbalance + drift_30s (both must agree)

Signal: `UP` if `imb_up > cutoff`, `DOWN` if `imb_up < 1−cutoff`, else `SKIP`. Cutoff sweep {0.55, 0.60, 0.65, 0.70} × spread-filter {on, off}. Universe: 2,000 markets/asset/setup. 1Hz book subsampling, 500-slug batches.

## Per-setup best configs (n_fires ≥ 200, ranked by pnl@0.5)

| asset | tf  | setup           | cutoff | spread | n_fires | hit_rate | pnl@0.5 |
|-------|-----|-----------------|--------|--------|---------|----------|---------|
| BTC   | 5m  | 1_5m_ws120      | 0.55   | off    | 1,329   | 0.524    |  +1,227 |
| ETH   | 5m  | 1_5m_ws120      | 0.60   | off    | 1,128   | 0.514    |    +510 |
| SOL   | 5m  | 1_5m_ws120      | 0.70   | off    |   353   | 0.524    |    +333 |
| BTC   | 5m  | 2_5m_late       | 0.70   | off    | 1,112   | 0.461    |  −2,407 |
| ETH   | 5m  | 2_5m_late       | 0.70   | off    | 1,011   | 0.464    |  −2,060 |
| SOL   | 5m  | 2_5m_late       | 0.70   | off    | 1,291   | 0.330    | −11,188 |
| **BTC** | **15m** | **3_15m_late60** | **0.70** | **off** | **1,323** | **0.721** | **+14,148** |
| **ETH** | **15m** | **3_15m_late60** | **0.70** | **off** | **1,341** | **0.683** | **+11,817** |
| SOL   | 15m | 3_15m_late60    | 0.65   | off    | 1,492   | 0.535    |  +2,201 |
| BTC   | 15m | 4_15m_late180   | 0.70   | off    |   947   | 0.494    |    −509 |
| ETH   | 15m | 4_15m_late180   | 0.70   | off    | 1,066   | 0.486    |  −1,009 |
| SOL   | 15m | 4_15m_late180   | 0.70   | on     |   789   | 0.245    | −10,172 |

## Special-focus result — 15m late entry at slot_end − 60s

Apparent 72% / 68% hit rate on BTC/ETH at cutoff 0.7 is **spurious**.

**Two diagnostics killed it:**

1. **Spread filter ON destroys the edge.** Same setup, drop rows where `ask_0 − bid_0 > 0.02`: BTC hit → 0.451, ETH → 0.464, SOL → 0.392. Hit rate collapses below random. The "wins" lived in markets where the book had already converged to the winner and spread was wide (because nobody trades a near-resolved market).

2. **L25-walk realistic entry economics**: rebuilt BTC 15m setup 3 cutoff 0.7 with `entry_price = ap0_up` (UP signals) / `1 − bp0_up` (DOWN signals) and 2% profit-only fee:
   ```
   n_fires=1,323  hit=0.721  pnl_realistic = -$1,809
   mean_entry_proxy = 0.44   median = 0.27
   UP-only pnl: -$1,538     DOWN-only pnl: -$271
   ```
   Distribution of `ap0_up` on UP signals is **bimodal** — either ~0.99 (you pay 99c for a 72% chance ≈ guaranteed loss) or ~0.04 (signal fires UP but the Up-book has been pushed to zero, so the imbalance is a noise read).

The 14-minute-into-15m-window snapshot **is** highly informative — but it's already in the price. The book is informationally efficient at that horizon. Imbalance reflects probability-of-settlement, not alpha.

## No-lookahead sanity check

| slug | book_ts_us | entry_us | Δ before entry | imb_up | outcome |
|---|---|---|---|---|---|
| `btc-updown-5m-1776994800` (setup 1) | 1,776,994,612,340,000 | 1,776,994,620,000,000 | 7.66 s | 0.481 | Down |
| `eth-updown-5m-1776994800` (setup 1) | 1,776,994,542,217,000 | 1,776,994,620,000,000 | 77.78 s | 0.149 | Down |
| `btc-updown-5m-1776994800` (setup 2) | 1,776,995,039,055,000 | 1,776,995,040,000,000 | 0.95 s | 0.795 | Down |

All `book_ts_us < entry_us`. Code path uses `np.searchsorted(ts, entry_us, side="right") - 1` — strictly causal.

## Other observations

- **Setup 1 (production fire-time, 5m)**: edge ≤ +3 pp across all assets/cutoffs — noise.
- **SOL 5m late-window**: cutoff 0.7 spread-on gives 18.9% hit rate (n=724). Heavy Up-side bid pressure is a strong **contra** signal for SOL — would require sell-YES L25 walk to trade.
- **Setup 5 (combined imb + drift_30s)**: fire counts <200 — insufficient evidence.

## Suggested follow-ups

1. Imbalance × CVD joint signal at fire-time.
2. Cross-side relative imbalance (Up-book imb vs Down-book imb differential).
3. Contra-imbalance late-window short on SOL — needs sell-YES L25 walk extension.
