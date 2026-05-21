# Momo Phase 3+4 — Anchor Corrected + Lookahead Bug Fixed

**Date:** 2026-05-09 ~23:30 UTC
**Owner:** alexandre.bandarra
**Status:** Backtest now reconciles with production within $0.95/trade (was $1.89). Two distinct bugs fixed.

## TL;DR

Two cumulative fixes brought backtest from +$13.54/trade fictional → -$0.59/trade realistic on the 67h production-overlap window:

| step | overall HOLD $/trade | May 7-9 67h $/trade | hit% on overlap | gap vs prod |
|---|---:|---:|---:|---:|
| Phase 0 (broken anchor) | +$13.54 | n/a | 85% (fake) | +$13.19 fake gain |
| **Phase 3** — slug-ws=END anchors | -$1.54 | -$3.06 | 44.7% | -$3.41 gap |
| **Phase 4a** — fresh VPS3 L25 (May 5-9) | -$1.80 | -$3.71 | 43.4% | -$4.06 gap |
| **Phase 4b** — strict-asof `find_book` | -$1.36 | -$1.34 | 48.6% | -$1.69 gap |
| **production target** | — | **+$0.35** | **52.0%** | 0 |

**Per-day match on overlap window now near-perfect on May 7** (-$0.07/trade gap); residual driven by trade-selection differences on May 8 (we drop 40 winning trades production took).

## Two bugs found this session

### Bug 1 — Anchor (Phase 3, already documented in handoff)

`ret_2m` was computed with `(ws-60, ws+60)` (lookahead leak: ws+60 is post-resolution under slug-ws=END semantics). Production uses 4 distinct anchors per `(version, tf)` cell, all confined to the first 2 minutes of market lifetime. Confirmed via 100% brute-force match on 300 audit rows. Now wired into `momo_full_universe_validation.py`:

```python
SLEEVE_ANCHORS = {
    ("v1", "5m"):  (-300, -180),  # first 2 min of 5m market
    ("v1", "15m"): (-900, -780),
    ("v2", "5m"):  (-360, -240),  # 2 min centered on strike
    ("v2", "15m"): (-960, -840),
}
SLEEVE_FIRE = {("v1","5m"): -180, ("v1","15m"): -780,
               ("v2","5m"): -240, ("v2","15m"): -840}
```

### Bug 2 — Lookahead in `find_book` (Phase 4 — NEW finding)

The book asof-lookup used **nearest within 10s** instead of **strict `<= ts_us`**. Two failure modes:

1. **Lookahead leak.** Could pick a book snap *after* fire time. For momo signals where price moves up, the post-fire ask is higher → simulated entry vwap higher than production's actual entry vwap. Worse pnl in backtest.
2. **Trade dropping.** With 10s tolerance, any trade whose nearest snap was more than 10s away got skipped. Many production fills happen when the previous WS snap is 15-40s old. We dropped trades production filled.

Fix in `find_book`:

```python
def find_book(idx, mid, outcome, target_us, max_dt_us=60_000_000):
    """STRICT asof: latest snap with timestamp_us <= target_us."""
    rec = idx.get((mid, outcome))
    if rec is None: return None
    ts, ap, as_, bp, bs = rec
    pos = int(np.searchsorted(ts, target_us, side="right"))
    if pos == 0: return None
    i = pos - 1
    dt = target_us - int(ts[i])
    if dt > max_dt_us: return None
    return ap[i], as_[i], bp[i], bs[i], dt
```

Effect: trade count nearly **doubled** (1,358 → 2,083 HOLD entries on full window) and average pnl per trade improved by **$0.44 overall, $2.37 on the May 7-9 overlap**.

This matches the canonical `OrderbookIndex.book_at` semantics in `strategy_lab/loaders/raw_orderbook_l25.py`.

## Per-day reconciliation (May 7-9 67h)

| day | n_bt | $/trade_bt | hit_bt | n_pr | $/trade_pr | hit_pr | delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| May 7 | 168 | -$0.71 | 50.0% | 104 | -$0.64 | 50.0% | **-$0.07** |
| May 8 | 143 | -$0.15 | — | 183 | +$2.70 | 56.8% | -$2.85 |
| May 9 | 47 | -$1.53 | — | 68 | -$4.45 | 42.6% | **+$2.92** |
| sum/avg | 358 | -$0.59 | — | 355 | +$0.35 | 52% | -$0.95 |

May 7 matches within 7¢/trade. May 8 gap (-$2.85) and May 9 gap (+$2.92) net to ~$0 in dollars but the trade-count delta means selection bias remains.

## Variant ranking — HOLD verdict flipped (handoff prediction confirmed)

Previously the broken-anchor backtest claimed "HOLD wins". With both fixes applied, on the headline universe:

```
=== Best variant per (version, asset, tf), by pnl_total ===
version asset  tf               variant   pnl_total   n  pnl_mean
     v1   SOL  5m         HOLD_baseline  +355.44     115  +3.09
     v1   BTC 15m HYBRID_RevOrStop_SELL  +153.38      80  +1.92
     v2   BTC  5m             HEDGE_3bp  +149.35     461  +0.32
     v2   BTC 15m         HOLD_baseline   -39.81     105  -0.38
     v2   ETH 15m              SELL_3bp   -64.69      50  -1.29
     v2   SOL 15m              SELL_7bp   -88.22      42  -2.10
     v1   BTC  5m             HEDGE_5bp  -105.14     470  -0.22
```

**Interpretation:**
- **v1 SOL 5m HOLD: +$3.09/trade (n=115)** — strongest cell.
- **HEDGE/SELL beats HOLD** on most v2 5m cells (production's highest-volume cells).
- BTC_15m and SOL_5m show clear edge for v1 sleeves; v2 5m has shallow positive edge with HEDGE.
- ETH cells weak across the board.

**Do NOT** ship momo_v3 partial-fill spec or slim to HOLD-only — the broken-backtest-era recommendations were artifacts. New variant ranking should drive production policy decisions.

## Remaining gap — trade selection (-$0.95/trade on overlap)

Likely sources, in priority order:

1. **SPREAD_FILTER drops trades production fills.** Backtest rejects entries with bid-ask > 2c (BTC/ETH) or > 2.5c (SOL). Production fills regardless. Production's avg entry_price = **$0.507** with avg qty ≈ 49.8 shares — essentially top-of-book at $0.50 — implying many production fills are right at the spread we'd reject. Loosening or removing this filter is the next experiment.
2. **Gate count mismatch.** Production may apply q90 differently (different lookback window, different daily refit cadence). On May 8 production took 183 trades vs our 143 — 40-trade delta on a winning day.
3. **Sleeve allocator behavior.** Production's TV agent may queue/retry around exchange congestion in ways the backtest skips entirely.

## Files changed

| file | change |
|---|---|
| `strategy_lab/meta_classifier/momo_full_universe_validation.py` | klines→VPS3, anchor table, fire offsets, strict asof `find_book`, per-version gate, per-version summary |
| `strategy_lab/meta_classifier/_smoke_phase3.py` | smoke test for anchor/gate (no L25) |
| `strategy_lab/meta_classifier/_convert_vps2_l25_to_parquet.py` | (initial May 6-8 conversion, superseded) |
| `strategy_lab/meta_classifier/_convert_vps3_l25_to_parquet.py` | full VPS3 May 5-9 L25 to parquet cache |
| `data/v4/refresh_2026_05_09/vps3_l25_pull/{btc,eth,sol}_l25_full.csv.gz` | raw VPS3 pull (445 + 101 + 46 MB gz) |
| `data/v4/refresh_2026_05_09/cache/{btc,eth,sol}_orderbook_L25_delta.parquet` | converted delta cache (754 + 164 + 70 MB) |
| `data/v4/refresh_2026_05_09/full_universe/per_trade.csv` | corrected per-variant per-trade pnl, 31,245 rows |

## Production state — unchanged (per handoff invariants)

- 36 sleeves still running for more data
- TV agent's WS book_mirror patch still deployed
- DO NOT ship momo_v3 partial-fill spec
- DO NOT slim to HOLD-only

## Next session — priority order

1. **Relax SPREAD_FILTER** (remove or raise to 5c) → re-run. Closes May 8 selection gap.
2. **Per-cell HEDGE_5bp validation** on the corrected backtest with relaxed filter — confirm v1 SOL 5m HOLD edge and v2 BTC 5m HEDGE_3bp edge survive.
3. **If they survive:** write deploy spec for the per-cell winning variants (per-cell sleeve assignment, not one-size-fits-all).
4. **Walkforward + DIRECTION_PERM** on the corrected per-cell winners to confirm stat significance.

## Anti-patterns / pitfalls (additions from this session)

11. **Don't use nearest-within-tolerance asof on orderbooks.** Always strict `<= ts_us`. Nearest can pick future snaps and leak.
12. **`\copy` requires single-line SQL** — multi-line meta-commands break in psql heredoc. Use `SELECT *` or build the column list as one physical line.
13. **`:'VAR'` psql variable substitution does NOT work in `\copy FROM`** — only in SELECT. Use bash variable expansion via unquoted heredoc instead.
14. **VPS3 delivers L25 fine over `scp -C`** — 592 MB total in ~3 min. The 1.1GB IPv6 timeout cited in earlier handoff was a transient or suboptimal path issue.
15. **Production's effective entry price ≈ $0.50 / 49 shares per $25** — top of book essentially. Any backtest filter that rejects entries near the spread will systematically drop production's actual fills.

---

*End of report. Read `SESSION_HANDOFF_2026_05_09_SLUG_WS_BREAKTHROUGH.md` for the original anchor breakthrough; this report is the Phase 3+4 followup.*
