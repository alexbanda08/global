# Strategy Discovery — Consolidated Findings (2026-05-16)

**Session:** fresh-context discovery sweep across 9 strategy ideas + LATE-15m angle.
**Universe:** 24,438 chainlink-resolved BTC/ETH/SOL × 5m/15m markets, Apr 24 → May 16 2026.
**Conventions enforced:** UTC microseconds, chainlink outcome, `ws_s = slug_suffix - window_s`, `asof_strict` causal lookups, 2% fee on profit only (legacy momo model).

## TL;DR

**No deployable alpha found in this sweep.** One weak survivor (Strategy H late-15m thr≥0.10) with marginal significance and walk-forward decay. Everything else is NULL or blocked by data.

The user-requested "late-entry on 15m markets" angle was tested across every strategy. **The high hit-rates seen at LATE-15m are almost entirely tautology** — Strategy I naive binance momentum at LATE-15m already hits 93%, because the observation window covers 14 of the 15 prediction-window minutes. Any signal must beat 93% to claim alpha at that anchor. None did.

---

## Strategy verdicts

| ID | Strategy | Anchor | Best n | Best hit | Best PnL | Verdict |
|---|---|---|---:|---:|---:|:---|
| A1 | CVD 5m | ws_s+120 | 3,570 | 0.519 | +$2,424 flat-0.5 | **NULL** (1.9pp edge, borderline) |
| A2 | CVD 15m | slot_end−60 | 925 | 0.885 | +$17,416 flat-0.5 | **SPURIOUS** (real-fill kills it: book at 0.95+) |
| B | Cross-venue lead-lag 5m | ws_s+120 | 2,238 | 0.521 | — | **NULL** |
| B | Cross-venue 15m | slot_end−60 | 580 | 0.638 | — | **TAUTOLOGY** (worse than I-baseline 93%) |
| C | HL liq cascades | various | 215 | 0.558 | — | **INCONCLUSIVE** (data gap Nov 2025 → Feb 2026) |
| D | Funding/OI gates | various | various | ~0.50 | negative | **NULL** (all gates hurt vs baseline) |
| E | L25 imbalance 5m | ws_s+120 | 1,329 | 0.524 | +$1,227 flat-0.5 | **NULL** |
| E | L25 imbalance 15m | slot_end−60 | 1,323 | 0.721 | **-$1,809 REAL-FILL** | **SPURIOUS** (book efficient at 0.99) |
| F | BTC leads ETH/SOL 5m | ws_s+120 | 4,562 | 0.493 | — | **NULL** (below random) |
| F | BTC leads 15m | slot_end−60 | 768 | 0.625 | — | **TAUTOLOGY** |
| G | BTC dominance overlay | — | 4,529 | 0.487 | -$4,078 | **NULL** (data: cache ends May 1, 91% DOM_UP) |
| **H** | **CLOB mispricing 15m** | **slot_end−60, edge≥0.15** | **261** | **0.594** | **+$921 REAL-FILL** | **WEAK-POSITIVE** (p=0.047 PnL, decays) |
| H | CLOB mispricing 15m | slot_end−60, edge≥0.10 | 430 | 0.626 | +$869 real | weak-positive (p=0.075 PnL, decays) |
| H | CLOB mispricing 5m | ws_s+120 | 16,315 | 0.502 | -$11,245 real | **NULL** (efficient) |
| H | FADE inverse low-thr | slot_end−60 | 2,581 | 0.781 | **-$1,978 REAL-FILL** | **NULL** (math doesn't work — opposite-side win is $1.30 vs $25 risk) |
| I | Naive binance momo 5m | ws_s+120 | 22,101 | 0.483 | -$23,716 | **NULL** |
| I | Naive binance momo 15m | slot_end−60 | 5,565 | 0.929 | +$116,839 flat | **NULL TAUTOLOGY** (defines the ceiling) |

---

## What the LATE-15m investigation actually revealed

The user specifically asked to test late-entry on 15m markets. Result was illuminating but disappointing:

**At `entry_us = slot_end − 60s` on 15m markets, every reasonable signal hits 60-90% on flat-0.5 PnL evaluation.** This includes naive binance momentum (93%), book imbalance (72%), CVD (88.5%), cross-venue (64%), cross-asset (62%).

**These are NOT alpha.** They are an artifact of two compounding effects:

1. **Observation tautology.** With 14 of 15 prediction minutes already observed, any directional summary of those 14 min predicts the full 15-min sign nearly perfectly.

2. **Book efficiency.** The CLOB at slot_end−60s has already absorbed the move. Up-side asks are at 0.95-0.99 when "Up is winning." Buying $25 at vwap=0.95 wins only $1.30/share on settle=1.0. A signal correctly calling Up 72% of the time loses money: 0.72 × $1.30 + 0.28 × (-$25) = **-$6.06/trade**.

Strategy E proved this empirically: BTC 15m late-60 imbalance 0.7 cutoff → 72% hit but **real-fill PnL = -$1,809.** Strategy H FADE confirmed from the opposite direction: 78-79% hit rate (book-says-Down-and-was-right) → **-$1.07/trade** real-fill.

**The ONLY late-15m cell where the book is misaligned with eventual outcome — and where you can still trade — is Strategy H at edge thresholds ≥ 0.10.** These are cases where the book has NOT yet repriced relative to a binance-momentum-derived fair-p. n=261-430, hit 60-63%, real-fill PnL +$868-922. p-value 0.05-0.08, walk-forward shows the edge halved between W17 and W19. Fragile.

---

## Data limitations discovered (storedata follow-ups)

1. **`hyperliquid_liquidations_full.parquet`**: covers May 2025 → Feb 2026. **Zero overlap with res window (Apr 24 → May 16 2026).** Storedata refresh needed before Strategy C is testable. Code is ready: `prefer="full"` in `build_liq_arrays()`.

2. **`binance_metrics.parquet`**: ends Apr 27 2026. asof beyond returns stale values → OI-delta-1h ≈ 0 for ~95% of fires. Storedata refresh needed for Strategy D.

3. **`cryptocap_dominance.parquet`**: ends May 1 2026. ~64% of universe gets forward-filled. Plus only 9% of window is DOM_DN — Strategy G untestable on 21-day sample. Need ≥ 6 months mixed-regime data.

4. **`trades_polymarket/*.parquet`**: `side` column is **lowercase** (`buy`/`sell`), not `BUY`/`SELL`. Discovered by Strategy A. Pre-fix CVDs were 100% negative.

5. **`binance_metrics` numeric cols**: stored as string-decimals — needs `pd.to_numeric(errors='coerce')`.

---

## Permutation + walk-forward on H late-15m candidate

```
thr=0.10  n=430  obs_pnl=+$869   obs_hit=0.626
  perm p-value (PnL): 0.075     # marginal
  perm p-value (hit): 0.000     # significant
  walk-forward by week:
    W17  n=98   hit=0.65  pnl=+$504
    W18  n=117  hit=0.60  pnl=+$223
    W19  n=131  hit=0.57  pnl=+$9      # edge eroding
    W20  n=84   hit=0.71  pnl=+$132

thr=0.15  n=261  obs_pnl=+$922   obs_hit=0.594
  perm p-value (PnL): 0.047     # just under 0.05
  perm p-value (hit): 0.001     # significant
  walk-forward by week:
    W17  n=57  hit=0.67  pnl=+$557
    W18  n=77  hit=0.56  pnl=+$250
    W19  n=84  hit=0.52  pnl=-$11      # broken
    W20  n=43  hit=0.70  pnl=+$125
```

Both thresholds show the same pattern: strong W17, decay to break-even by W19, partial recovery W20. Could be regime-dependent (a momentum regime worked in W17, mean-reversion in W19) or could be small-sample noise. **5 weeks of data is insufficient to discriminate.**

---

## Cross-asset specifics worth flagging

- **SOL** showed a curious **contra-imbalance** signal at late-window: cutoff 0.7 spread-on → 18.9% hit (i.e., 81% if inverted). Strategy E flagged this. Would need a sell-YES L25 walk extension to test properly.
- **ETH** is the most edge-receptive asset across CVD, lead-lag, and mispricing.
- **BTC** is the most efficient — lowest edges across the board.

---

## What to try next session (recommended order)

1. **Validate H late-15m thr≥0.10 with proper fillability**:
   - Re-run with `engine_v2.fill_at_book` + real Polymarket fee curve (`0.07·p·(1-p)` per share).
   - At vwap=0.58 median, real fee = $0.083/share × $25/0.58 = $3.57/trade. That erases most of the $2/trade edge.
   - If positive after real fees → permutation on 1000 draws → walk-forward 7d/1d.

2. **Backfill HL liquidations_full from VPS3** (Apr-May 2026 gap). Then re-run Strategy C with proper directional `dir` labels.

3. **SOL contra-imbalance**: extend `harness.book_fill_pnl` to sell-YES side (walk bids, not asks). Test as a SOL-only late-window signal.

4. **Joint signal at ws_s+120**: CVD × imbalance × cross-venue. Each is individually NULL but a 2-of-3 AND/consensus might exceed 50%. Low-cost test.

5. **Drop**: A1 (CVD-5m), A2 (CVD-15m late at low-thr — too OTM), B/F LATE-15m (tautology), D regime gates, G dominance overlay (until data fixed), H low-thr (NULL even as fade).

---

## Files produced

```
strategy_lab/discovery_2026_05_16/
├── harness.py                              shared backtest infra
├── strat_A1_cvd_5m.py
├── strat_A2_cvd_15m_late.py
├── strat_B_cross_venue.py
├── strat_C_hl_liqs.py
├── strat_D_funding_oi.py
├── strat_E_book_micro.py
├── strat_F_cross_asset.py
├── strat_G_dominance.py
├── strat_H_mispricing.py
├── strat_I_binance_only.py
├── REPORT_A_CVD.md
├── REPORT_BF_LEADLAG.md
├── REPORT_CD_PERPS.md
├── REPORT_E_BOOK.md
├── REPORT_GHI_MACRO_MISPRICE_BASELINE.md
├── FINAL_DISCOVERY_REPORT.md             this file
└── *.csv, *.parquet                       result artifacts
```

---

## Honest summary

11 strategies tested. Most assumed-promising directions (CVD, book imbalance, HL liqs, cross-venue, cross-asset) are NULL at the production anchor. The LATE-15m angle the user asked about looked enormously promising on raw hit-rate but degenerated to a tautology + book-already-priced-it artifact on rigorous checks. The one weak alpha candidate (H late-15m at moderate edge thresholds) is marginal on permutation, decays in walk-forward, and faces fillability concerns at the deep ITM prices it operates in.

Production anchor `ws_s+120s` remains the right entry — Polymarket binary markets are informationally efficient at that timestamp against every signal we tested. Edge, if it exists at this anchor, lives in **joint** signals or in **microstructure-event-triggered** firing (HL cascade event → fire within N seconds), which we couldn't test cleanly due to data gaps.
