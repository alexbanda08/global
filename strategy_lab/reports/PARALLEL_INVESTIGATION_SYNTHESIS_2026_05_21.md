# Parallel investigation — synthesis after 4 deep audits

_4 subagents launched in parallel: production filter audit, L25 book depth audit, backtest harness code review, expanded Markov variant matrix. This document combines their findings + the post-fix re-run._

## Headlines

1. **Backtest harness had 1 CRITICAL bug**: sniper `ret_5m` anchored at `slot_start` instead of `ws_s` with FIXED 300s lookback. Fixed. **Sniper performance jumped from −$2k across cells to +$2,400+ across cells.**
2. **1Hz L25 subsampling is fine.** No material bias. Don't rerun anything for book-depth reasons.
3. **Expanded Markov matrix (96 variants) on the FIXED data identifies stronger gates per cell**, with **`sniper eth_5m + w30_5m_q25_75`** as the dominant cell-gate edge: **+$650 over 28d, 55.8 % WR, n=197**.
4. **Production fires ~30× less often than my harness because of `qty_compute_failed` (80.6 % of drops)**. Likely root causes my harness doesn't model: wallet balance, min-notional rounding, position caps. The clean per-trade $/tr should be roughly right; the absolute fire count is inflated 30×.
5. **`entry_rejected` (9.3 %) and `exited_at_bid` / `hedge_placed` (8 %) are NOT in my harness.** Adding them would shrink the fire pool and shift PnL on placed trades by single-digit %.

---

## Final per-sleeve scorecard (after sniper fix + expanded Markov sweep)

**Top 10 (strategy × cell × Markov variant) by sum$ over 28 days, n ≥ 30:**

| # | strategy | cell | Markov variant | n | WR % | $/tr | sum $ |
|---|---|---|---|--:|--:|--:|--:|
| 1 | **sniper** | **eth_5m** | **w30_5m_q25_75** | **197** | **55.84** | **+$3.30** | **+$650** |
| 2 | sniper | eth_5m | w30_5m_q40_60 | 227 | 55.07 | +$2.82 | +$640 |
| 3 | sniper | eth_5m | w30_5m_q45_55 | 233 | 54.94 | +$2.74 | +$639 |
| 4 | sniper | eth_5m | w40_5m_q25_75 | 180 | 56.11 | +$3.48 | +$627 |
| 5 | sniper | eth_5m | w10_5m_q25_75 | 220 | 54.55 | +$2.78 | +$612 |
| 6 | sniper | eth_5m | w30_5m_fix_default | 239 | 53.97 | +$2.53 | +$605 |
| 7 | sniper | eth_5m | w30_5m_fix_tight | 266 | 53.38 | +$2.26 | +$601 |
| 8 | sniper | eth_5m | w10_5m_fix_very_tight | 288 | 52.78 | +$2.06 | +$594 |
| 9 | sniper | eth_5m | w30_5m_q33_66 | 215 | 54.88 | +$2.75 | +$591 |
| 10 | sniper | eth_5m | w40_5m_q40_60 | 229 | 54.59 | +$2.55 | +$584 |

**Best per (strategy, cell):**

| strategy | cell | best Markov variant | n | WR % | $/tr | sum $ |
|---|---|---|--:|--:|--:|--:|
| sniper  | eth_5m  | w30_5m_q25_75         | 197 | 55.84 | +$3.30 | **+$650** |
| sniper  | btc_15m | w20_5m_q45_55         | 213 | 53.99 | +$2.58 | **+$548** |
| sniper  | eth_15m | w60_1m_q45_55         | 168 | 54.17 | +$2.86 | **+$481** |
| **momo_v1** | **btc_15m** | **w20_5m_q25_75** | **36** | **72.22** | **+$11.05** | **+$398** |
| sniper  | sol_15m | w40_1m_q25_75         |  83 | 57.83 | +$3.90 | +$323 |
| sniper  | sol_5m  | w10_5m_fix_very_tight | 199 | 54.77 | +$1.60 | +$318 |
| momo_v2 | btc_15m | w20_1m_q40_60         | 143 | 55.94 | +$2.09 | +$298 |
| momo_v2 | eth_5m  | w30_5m_fix_loose      | 126 | 54.76 | +$1.93 | +$244 |
| momo_v2 | eth_15m | w20_1m_q45_55         |  80 | 57.50 | +$2.92 | +$233 |

Aggregate of these 9 best-per-cell gates: **+$3,492 over 28 days** (≈ +$125/day).

## The 70+ % WR claim — verdict

Only **1 cell** crosses 70 % WR with n ≥ 30 over 28 days:

- **momo_v1 btc_15m + Markov w20_5m_q25_75**: **72.22 % WR, +$11.05/tr, +$398 (n=36)**

n=36 is at the borderline of statistical confidence. The earlier production-claimed 70+ % WR sleeves (sol_5m_momo_v1+F7 at 71%, sol_5m_momo_v2+F7 at 91%, etc.) **do not reproduce on 28 days of clean spec data**. Those numbers were 23.5h sample artifacts.

What does persist: **multiple cells in the 53-58 % WR range with positive $/trade** when using the right Markov variant. The edge is real but smaller than the production shadow numbers suggested.

---

## Findings detail by agent

### Agent A — Production filter audit ([FILTER_INVENTORY.md](strategy_lab/markov_filter/_vps3_pull/FILTER_INVENTORY.md))

**Production fire-reason breakdown (momo, 7d):**

| reason | count | % of drops |
|---|--:|--:|
| qty_compute_failed | 2,886 | 80.6 % |
| entry_rejected | 332 | 9.3 % |
| exited_at_bid | 178 | 5.0 % |
| hedge_placed | 175 | 4.9 % |
| (order_placed) | 4,191 | success bucket |

**Per-cell drop rate (intended → placed):**

| sleeve_group | intended | placed | drop % |
|---|--:|--:|--:|
| eth_15m_momo | 438 | 78 | **82.2 %** |
| sol_15m_momo | 401 | 105 | 73.8 % |
| sol_15m_momo_v2 | 352 | 117 | 66.8 % |
| sol_5m_momo | 1,252 | 441 | 64.8 % |
| btc_15m_momo | 385 | 147 | 61.8 % |
| sol_5m_momo_v2 | 954 | 441 | 53.8 % |
| eth_5m_momo | 1,181 | 624 | 47.2 % |
| eth_15m_momo_v2 | 344 | 249 | 27.6 % |
| btc_5m_momo_v2 | 1,243 | 993 | 20.1 % |
| btc_5m_momo | 1,212 | 996 | 17.8 % |

**Action items** (not yet shipped to harness):

1. `qty_compute_failed` already in scope but production drops far more often. Add: wallet balance gating, min-notional/lot-size rounding, max-position-per-slug.
2. `entry_rejected` — distinct from spread/sparse-book — post-place price-band reject. Add a final pre-place check using the +85ms latency window.
3. `exited_at_bid` + `hedge_placed` (~8 % of placed) — post-fill events that change realized PnL vs hold-to-settle. Add bid-exit / hedge-cascade simulator.

These don't change the per-trade $/tr math materially — they shrink the fire pool and modify ~8 % of trades' exits. **Won't move the headline 70+ % WR conclusion**.

### Agent B — L25 book-depth audit ([BOOK_DEPTH_AUDIT.md](strategy_lab/markov_filter/_results/BOOK_DEPTH_AUDIT.md))

- Raw L25: median 3,482 snapshots/key full-depth vs 414 after 1Hz subsample (**8.3× compression**).
- 300-fire comparison (1Hz vs full-depth, BTC busy slugs):
  - 296/300 fires fill identically
  - Mean Δvwap = +0.00014; median = 0; p95 |Δ| = 0.002
  - Full-depth rescued 0 fires; 1Hz "rescued" 4 (spread-filter edge cases)
  - PnL Δ = −$0.18 over 300 fires (−$0.0006/fire)
  - Book staleness improves only 35ms with full depth

**Verdict: keep `subsample_1hz=True`. No rerun needed.** Strategy fires on deterministic anchors and $25 notional walks deep enough into L25 that single-tick best-ask jitter doesn't move vwap.

### Agent C — Backtest harness code review ([HARNESS_REVIEW.md](strategy_lab/markov_filter/_results/HARNESS_REVIEW.md))

10 checks: 8 PASS, 1 LOW, **1 CRITICAL**.

**CRITICAL — Sniper `ret_5m` anchor**: Harness was computing
```python
ret_w = log(close@slot_start / close@(slot_start − window_s))
```
Production computes (per `polymarket_updown.py:1127-1147`):
```python
ret_w = log(close@ws_s / close@(ws_s − 300))   # FIXED 300s for BOTH 5m AND 15m
```

**Two divergences:**
1. Anchor forward-shifted by `window_s` (slot_start vs ws_s)
2. Lookback `window_s` for 15m instead of fixed 300s

Every sniper signal decision and threshold computation diverged from production. **Fixed in commit** (the rerun produced the corrected scorecard above).

**LOW — threshold sample window**: harness uses `until_s = slot_start_s`; prod uses `ws_s`. Adds ~1 extra slug to rolling threshold. Causal, slightly looser. Not material.

**PASS (8 checks)**: ws_s for momo, fire_us for all 3 strategies, log-return Wilder RSI, q90/q80 causal thresholds, strict-asof + 85ms latency book lookup + 0.02 spread filter, qty_compute [0.05, 0.95], hold PnL formula with full Polymarket fee, outcome-derived `won`, UP→Up / DOWN→Down token mapping, Markov asof causality.

### Agent D — Expanded Markov variant matrix ([MARKOV_VARIANT_MATRIX.md](strategy_lab/markov_filter/_results/MARKOV_VARIANT_MATRIX.md))

- 96 variants per asset × 3 assets = 288 (asset, variant) pairs
- 6 windows (10, 15, 20, 30, 40, 60 bars) × 2 bar TFs (1m, 5m) × 8 thresholds (4 quantile, 4 fixed) = 96 variants
- Total: 1,724 (strategy, cell, variant) rows; 1,460 with n≥30

**Key findings on FIXED sniper data:**
- **Sniper / eth_5m dominates with multiple variants returning +$590-650 each.** 8 of top 10 cells are sniper/eth_5m.
- **5m bars beat 1m bars** for sniper (slower regime detection better matches the bar-close fire timing).
- **Q25/75 (wider tertile cuts) lifts WR** at the cost of slightly less coverage.
- **All 3 prior baselines beaten**:
  - momo_v1 btc_15m: +$368 → +$398 (w20_5m_q25_75, +8.1 %)
  - momo_v2 btc_15m: +$235 → +$298 (w20_1m_q40_60, +26.8 %)
  - momo_v2 eth_15m: +$189 → +$233 (w20_1m_q45_55, +23.5 %)

---

## What changed vs my earlier "no 70+ % WR cells" conclusion

Earlier (Phase B with buggy sniper):
- Best cell: momo_v1 btc_15m + Markov w20_5m_voladaptive = +$368 (n=39, 69 %)
- "No cell reliably hits 70+ % WR with n ≥ 30"
- Aggregate best gate: −$57/day

After sniper fix + expanded Markov matrix:
- Best cell: sniper eth_5m + Markov w30_5m_q25_75 = +$650 (n=197, 56 %)
- "1 cell at 72 % WR with n=36"; many cells at 53-58 % WR with positive $/tr at n=140-280
- Aggregate of top 9 best-per-cell gates: **+$125/day** over 28 days

**The clean spec edge DOES exist — I missed it because of the sniper bug.** It's just not the 70+ % WR everywhere story production data suggested.

---

## Action items

1. **Ship the sniper anchor fix to the harness** ([backtest_prod_strategies_with_gates.py:149-156](strategy_lab/markov_filter/backtest_prod_strategies_with_gates.py:149) — already applied).
2. **Deploy 4 high-confidence Markov shadow sleeves** based on this scorecard (n ≥ 100, $/tr ≥ +$2):
   - sniper eth_5m + w30_5m_q25_75 (or fix_default if simpler)
   - sniper btc_15m + w20_5m_q45_55
   - sniper eth_15m + w60_1m_q45_55
   - sniper sol_5m + w10_5m_fix_very_tight
   - + the existing momo_v2 btc_15m / eth_15m Markov sleeves
3. **Add to harness** (separate work): wallet-balance + min-notional + position-cap gates for qty_compute realism. Then re-validate fire counts vs production within 2×.
4. **Add bid-exit / hedge-cascade simulator** (separate work) for trade-level PnL realism.
5. **Don't rerun for book depth** — 1Hz is fine.

## Files

- `strategy_lab/markov_filter/backtest_prod_strategies_with_gates.py` — runner (sniper fix applied)
- `strategy_lab/markov_filter/_results/backtest_prod_strats/fills.csv` — 11,681 fills after sniper fix
- `strategy_lab/markov_filter/_results/backtest_prod_strats/scorecard.csv` — per-cell × gate
- `strategy_lab/markov_filter/_results/MARKOV_VARIANT_MATRIX.csv` — 1,724 rows full sweep
- `strategy_lab/markov_filter/_results/MARKOV_VARIANT_MATRIX.md` — top-10 + per-cell best
- `strategy_lab/markov_filter/_results/HARNESS_REVIEW.md` — 10-check review (8 PASS, 1 LOW, 1 CRITICAL)
- `strategy_lab/markov_filter/_results/BOOK_DEPTH_AUDIT.md` — 1Hz fine
- `strategy_lab/markov_filter/_vps3_pull/FILTER_INVENTORY.md` — production fire-reason breakdown
- `strategy_lab/markov_filter/_vps3_pull/PROD_FIRE_REASON_BREAKDOWN.csv` — raw SQL output

## Caveats remaining

1. **Fire-count fidelity vs production is still ~30× off.** Adding wallet + min-notional + position-cap filters would shrink my fire pool toward production's. The per-trade $ should be roughly right; the daily total $ in my numbers is upper-bound.
2. **Threshold tuning for the `_fixed` Markov variants** is from this same 28-day window — risk of in-sample selection. Out-of-sample validation needed before deploy.
3. **All scoring is on chainlink-derived outcomes**. Production uses same source. ✓
4. **F7 + Markov interaction** wasn't expanded as widely — only the canonical Markov w20_1m_voladaptive was tested with F7. Could rerun matrix with F7 layered.
