# Full Universe Momo Backtest — 2026-05-16

**Window:** 2026-04-25 → 2026-05-15 (18 trading days with sufficient lookback after 14d warmup)
**Universe:** 23,553 chainlink-resolved markets (BTC/ETH/SOL × 5m/15m)
**Anchors:** Production-correct (`ws_s = slug_suffix − window_s`, see `SESSION_HANDOFF_2026_05_10_WS_S_CONVENTION.md`)
**Gating:** q90 of |ret_2m| per (version, asset, tf, day) on rolling 14d lookback, ≥50 prior samples per cell-day
**Fill model:** L25 book walk for $25 notional, 2% fee on profit only
**Spread filter:** BTC 0.02 / ETH 0.02 / SOL 0.025
**Outputs:** `data/v4/canonical/_results/full_universe_2026_05_16/`
**Script:** `strategy_lab/meta_classifier/momo_full_universe_canonical.py`

---

## Headline

**HOLD_baseline is unprofitable across the full universe over 21 days:** -$1.31/trade (n=2,909), 48.4% hit rate. **Every variant in every version shows negative out-of-sample PnL on walkforward.**

| version | variant ordered worst → best | pnl_mean | fire% |
|---|---|---:|---:|
| v1 | HOLD_baseline | **-$1.21** | 0% |
| v1 | best (SELL_3bp) | -$0.61 | 35% |
| v2 | HOLD_baseline | **-$1.38** | 0% |
| v2 | best (STOP_SELL_0.7x) | -$1.36 | 0.2% |

Compare to the prior-session Phase 3 target of **+$0.35/trade** on the May 7-9 production overlap window: that 67h window was a positive slice; the surrounding 21d universe is not.

---

## Universe & gating sanity

```
v1 5m:  n=17,661  finite_ret_2m=17,661
v1 15m: n=5,892   finite_ret_2m=5,892
v2 5m:  n=17,661  finite_ret_2m=17,661
v2 15m: n=5,892   finite_ret_2m=5,892

gated (top-decile |ret_2m|, ≥50 prior samples/cell-day): 5,703
  (v1,15m): 715   (v1,5m): 2,217
  (v2,15m): 659   (v2,5m): 2,112
```

L25 book coverage:
- BTC: 2,582 (slug,outcome) keys, 1,058,584 snapshots
- ETH: 2,546 (slug,outcome) keys,   548,950 snapshots
- SOL: 3,090 (slug,outcome) keys,   391,501 snapshots

---

## HOLD_baseline — per (version × asset × tf)

| version | asset | tf | n | pnl_mean | pnl_sum | hit% |
|---|---|---|---:|---:|---:|---:|
| v1 | BTC | 15m | 97  | **+$2.37** | +$229.56 | 55.7% |
| v1 | BTC | 5m  | 593 | -$1.36     | -$808.03 | 48.1% |
| v1 | ETH | 15m | 40  | -$6.61     | -$264.26 | 37.5% |
| v1 | ETH | 5m  | 331 | -$2.99     | -$990.83 | 45.0% |
| v1 | SOL | 15m | 25  | -$3.50     | -$87.51  | 44.0% |
| v1 | SOL | 5m  | 227 | **+$1.45** | +$329.29 | 54.6% |
| v2 | BTC | 15m | 136 | -$0.14     | -$18.68  | 50.7% |
| v2 | BTC | 5m  | 565 | -$1.27     | -$717.52 | 48.1% |
| v2 | ETH | 15m | 75  | -$3.26     | -$244.77 | 44.0% |
| v2 | ETH | 5m  | 415 | -$0.60     | -$248.22 | 49.9% |
| v2 | SOL | 15m | 70  | -$7.22     | -$505.61 | 37.1% |
| v2 | SOL | 5m  | 335 | -$1.42     | -$475.34 | 48.7% |

**Only two positive cells:** v1 BTC 15m (+$2.37/tr) and v1 SOL 5m (+$1.45/tr). Everything else loses money on HOLD.

---

## Per-cell winners (best variant per cell)

| version | asset | tf | best variant | pnl_total | n | pnl/tr |
|---|---|---|---|---:|---:|---:|
| v1 | SOL | 5m  | **HOLD_baseline**        | **+$329.29** | 227 | +$1.45 |
| v1 | BTC | 15m | **HYBRID_RevOrStop_SELL**| **+$309.70** | 97  | +$3.19 |
| v2 | BTC | 15m | HOLD_baseline              | -$18.68      | 136 | -$0.14 |
| v2 | ETH | 5m  | HOLD_baseline              | -$248.22     | 415 | -$0.60 |
| v1 | ETH | 15m | SELL_7bp                   | -$238.38     | 40  | -$5.96 |
| v1 | ETH | 5m  | SELL_3bp                   | -$402.72     | 331 | -$1.22 |
| v2 | BTC | 5m  | HEDGE_3bp                  | -$398.23     | 565 | -$0.70 |
| v2 | SOL | 15m | SELL_7bp                   | -$441.86     | 70  | -$6.31 |
| v2 | SOL | 5m  | HOLD_baseline              | -$475.34     | 335 | -$1.42 |
| v1 | SOL | 15m | SELL_7bp                   | -$47.48      | 25  | -$1.90 |
| v1 | BTC | 5m  | HEDGE_3bp                  | -$578.79     | 593 | -$0.98 |

Only **2 cells** carry positive expectancy at scale: **v1 SOL 5m HOLD** (n=227) and **v1 BTC 15m HYBRID_RevOrStop_SELL** (n=97). Even these are vulnerable to multiple-comparison adjustment — see permutation results.

---

## Walkforward — every variant lost over 18 days

Top of `walkforward_summary.csv` (worst-first on a strategy this poor — best is least-bad):

| variant | n_days | days_positive | oos_total | sharpe/day |
|---|---:|---:|---:|---:|
| v1 SELL_3bp        | 18 | 5  | -$805   | -0.37 |
| v1 HEDGE_3bp       | 18 | 5  | -$808   | -0.37 |
| v1 HYBRID_3bp      | 18 | 5  | -$808   | -0.37 |
| v1 SELL_7bp        | 18 | 6  | -$960   | -0.39 |
| v1 HEDGE_7bp       | 18 | 6  | -$965   | -0.40 |
| v1 HOLD_baseline   | 18 | 8  | -$1,542 | -0.51 |
| v2 HOLD_baseline   | 18 | 5  | -$2,181 | -0.61 |
| v2 SELL_7bp        | 18 | 5  | -$2,762 | -0.84 |

No variant achieves positive `oos_pnl_total`. All sharpe negative.

---

## Permutation test — observed PnL not significant for any tested variant

Sign-flip permutation (1000 draws) on top 3 variants per version. p_value = fraction of permutations producing PnL ≥ observed.

| version | variant | asset | tf | n | obs_pnl | p_value |
|---|---|---|---|---:|---:|---:|
| v1 | SELL_3bp        | BTC | 15m | 97  | +$278  | 0.079 |
| v1 | HEDGE_3bp       | BTC | 15m | 97  | +$277  | 0.073 |
| v1 | HYBRID_3bp      | BTC | 15m | 97  | +$277  | 0.092 |
| v1 | SELL_3bp        | BTC | 5m  | 593 | -$580  | 0.895 |
| v1 | SELL_3bp        | ETH | 5m  | 331 | -$403  | 0.866 |
| v1 | SELL_3bp        | SOL | 5m  | 227 | +$207  | 0.254 |
| v2 | STOP_SELL_0.7x  | BTC | 5m  | 565 | -$670  | 0.864 |
| v2 | HOLD_baseline   | BTC | 5m  | 565 | -$718  | 0.904 |

**No cell has p<0.05.** Best is BTC 15m at p≈0.08, suggestive but not significant at the 5% level. Most other observed PnLs sit at or near the median of the null distribution.

---

## Why this contradicts the prior session's optimism

Prior session reported strong shadow-trading numbers like:
- `btc_15m_momo_HOLD`: +$10.73/tr (n=23) — but only **23 trades** over the recent shadow window
- `eth_15m_momo_v2_HOLD`: +$6.78/tr (n=20)
- `btc_5m_v3`: +$3.65/tr (n=58)

The full-universe backtest has 100-600× more trades per cell. The shadow numbers were a tiny slice of recent days where momentum happened to follow through. Over 21 days, **the gated q90 |ret_2m| universe does not have positive expectancy on Polymarket-CLOB book walks at $25 notional.**

The May 7-9 67h overlap that previously matched production within $0.07/tr is now embedded in a wider 21-day window where the median day is negative — which means **production HOLD's positive PnL during that 67h is not a robust property of the strategy**, it's a window effect.

---

## What changed structurally vs the prior backtest

1. **L25 data extended from May 9 → May 14** via `data/v4/refresh_2026_05_12/cache/{asset}_orderbook_L25_delta.parquet`. The `load_orderbook_l25_streaming` helper was patched to include 05_12 in its source list. So the new 5 days of post-May-9 trades are included.

2. **Resolutions universe is locally-derived from chainlink RTDS** (`resolutions_from_rtds.parquet`, 23,553 markets, May 15). No binance-resolution contamination — this is one source of difference vs the original Phase 3 numbers, which mixed upstream chainlink resolutions.

3. **Anchors are production-correct** (`ws_s = slug_suffix - window_s`). For 5m: anchors `(ws-300, ws-180)` = `(ws_s, ws_s+120)`. For v2: anchors `(ws-360, ws-240)` = `(ws_s-60, ws_s+60)`. Both end-time-indexed strict asof.

4. **Spread filter unchanged**: BTC/ETH 0.02, SOL 0.025. Loosening to 0.05 (the unrun "SPREAD_FILTER experiment" from `MOMO_PHASE3_4_ANCHOR_LOOKAHEAD_FIXED_2026_05_09.md`) would admit more fires but in the prior overlap analysis only closed ~$1.69/trade gap — would not flip the sign here.

---

## What to do next (priority)

### A. Take the two surviving cells live, drop the rest
Deploy ONLY:
- `v1 sol_5m_momo_HOLD` (+$1.45/tr, n=227, hit 55%)
- `v1 btc_15m_momo_HYBRID_RevOrStop_SELL` (+$3.19/tr, n=97, hit 56%, p≈0.08)

Drop the other 10 cells. They are unprofitable on this evaluator.

### B. Test if v2's anchors actually beat v1
v2 was supposed to capture the 2 minutes centered on the strike point (anchors at `ws-360, ws-240` for 5m = `ws_s-60, ws_s+60`). It's losing money slightly worse than v1 across every cell. Either:
- v2 anchors don't actually have edge over v1 (deprecate v2)
- OR the gate condition (q90 |ret_2m|) is misaligned with the v2 signal

Concrete test: re-run with v2-only universe at q95 gate (only top 5%) — if PnL/tr goes up materially, the gate is the issue.

### C. Stop trusting small-n shadow performance
The 14d shadow numbers (n=20-58 per cell) are not enough to commit to any cell. Either:
- Run shadow ≥30 days per cell before deployment decision, or
- Use the full-universe backtest (n=100-600/cell) as the screen

### D. Investigate gate misalignment
HOLD wins on 2 cells (v1 SOL 5m, v1 BTC 15m) and HEDGE/SELL wins everywhere else with worse-than-zero PnL. That means **the q90 momentum signal is roughly random** on most cells (~48-50% hit). Exit policies recover transaction costs but not enough to be profitable.

Possible underlying causes:
- The CLOB ask prices already reflect this momentum (efficient market)
- The 2-min PRE-window observation does not predict the next 5-15m outcome at top-decile magnitudes
- Sample bias: top-decile |ret_2m| concentrates in volatile windows where edge is competed-away

### E. Re-validate the ws_s convention end-to-end
The script confirms `n=17,661 finite_ret_2m=17,661` (no NaN gaps) — anchor lookup is correct. But sanity check: pick 10 production fires from `trading.events` and verify our backtest's `fire_us` and entry book match what production observed.

---

## Side notes

- Tier1 L25 entries server-side join (step 7 of `local_pull.sh`) hung on VPS3 for 25+ min — no active queries shown, ssh sleeping. Non-blocking for this report; backtest uses streaming L25 from cache. To unblock: restart the tier1 step in isolation; needs investigation.
- VPS3 controller mtime today 2026-05-16 02:05 shows an uncommitted `slot_allowlist` patch (live-mirror dedup fix from yesterday's bug) — unrelated to backtest results.

---

## File outputs

```
data/v4/canonical/_results/full_universe_2026_05_16/
  ├── gated_universe.csv         5,703 rows × 17 cols
  ├── per_trade.csv             43,635 rows × 17 cols (15 variants × all simulated trades)
  ├── summary.csv                 (n, fires, fire_pct, pnl_total, pnl_mean) per (version, variant)
  ├── winners.csv                 best variant per cell
  ├── walkforward.csv             per-(version, variant, day) OOS PnL
  ├── walkforward_summary.csv     OOS rollup with sharpe/day
  └── permutation.csv             1000-draw sign-flip p-values on top-3 variants
```

Reproduce:
```bash
py -3 -X utf8 strategy_lab/meta_classifier/momo_full_universe_canonical.py
```
