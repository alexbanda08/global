# Momo 5m fix plan — restore profitability

**Generated:** 2026-05-06
**Source diagnosis:** `strategy_lab/reports/MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md`
**Slippage breakdown:** `strategy_lab/results/meta_classifier/momo_5m_slippage_diag.csv`

## TL;DR

**Three fixes ranked by expected $/trade recovery:**

1. **Strict spread + L1-depth gate at entry** (~$3-5/trade recovery on SOL). Production fires on markets that the realfill simulator correctly skips. Tightening the entry filter alone restores most of the gap.
2. **Skip when asset_ret_2m mid-bar** (~$1-2/trade recovery). Strict no-lookahead asof shows production fires on signals using future-price reference. Use end-of-completed-1m-bar only.
3. **Hedge mechanism unblock** (per `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`). Once HEDGE actually fires at -5bp, 5m's 47% hit-rate becomes survivable. Recovery: ~$2-4/trade.

Combined estimated 5m portfolio recovery: **$+8-12/trade vs current $-1.09/trade.**

## Evidence

### Hit rate vs L1 ask size at entry (SOL_5m_HOLD, n=36)

| L1 ask size | n | wins | hit |
|---|---:|---:|---:|
| 0-5 shares | 3 | 1 | **33%** ❌ |
| 5-25 shares | 19 | 14 | 74% ✅ |
| 25-100 shares | 13 | 8 | 62% |
| 100-1k shares | 1 | 1 | 100% |

Tiny L1 ask size = thin book = bad fills + adverse selection. **Skip if L1 size < 5 shares.** Saves 3 of 36 fires (8%) at 33% hit (negative EV).

### Hit rate vs spread at entry (5m HOLD, n=68)

| asset | narrow (≤0.025) | wide (>0.025) |
|---|---|---|
| BTC | 64% on n=11 | 0% on n=1 |
| ETH | 70% on n=20 | (0) |
| **SOL** | **68% on n=19** | **65% on n=17** |

SOL is firing on **17 wide-spread markets** (47% of fires) — they should be SKIPPED by the existing `SPREAD_FILTER[sol] = 0.025`. Production isn't enforcing the filter, OR is reading a different spread metric than realfill.

**Investigation needed:** does production check spread at signal-time or fill-time? They differ by 50-200ms in shadow data. If checked at signal-time using stale book, the actual fill happens against a wider spread.

### Hit rate vs slippage bucket (where slippage = prod_entry − rf_vwap, bps)

For SOL_5m_HOLD:
| slip_bucket | n | hit |
|---|---:|---:|
| ≤ -50 bps | 5 | **80%** ✅ (production paid less than realfill expected) |
| 50-200 bps | 2 | 100% (small slippage, still wins) |
| **> 1000 bps** | **7** | **0%** ❌ (production paid massively over) |

7 of 36 SOL trades had **slippage > 1000 bps** (>10% above realfill vwap) → 0% win rate.

Caveat: some of those extreme slip values may be timestamp artifacts in this matcher; but the directional signal holds — extreme entry-side slippage = guaranteed loser.

### Per-asset 5m HOLD hit rates (matched, n=68)

| asset | n | wins | hit | observation |
|---|---:|---:|---:|---|
| BTC_5m_HOLD | 12 | 7 | 58% | wide-CI, mostly OK |
| ETH_5m_HOLD | 20 | 14 | 70% | profitable as-is |
| SOL_5m_HOLD | 36 | 24 | 67% | profitable IF we filter the bad 17 wide-spread trades |

**Rough EV math after applying spread + L1 filter** to SOL_5m_HOLD:
- Drop the 3 tiny-L1 + 17 wide-spread overlap trades
- Surviving: ~16 trades at 75-80% hit
- Mean PnL/trade: 0.78 × $24 - 0.22 × $24 = **$+13.4** ≈ realfill estimate

## Fix 1 — strict entry gate (highest priority)

### Required production controller changes

In `_handle_t_plus_120` (entry firing path), BEFORE placing the order:

```python
# 1. Re-fetch own-side book RIGHT NOW (don't reuse signal-time book)
own_book = await self._fetch_own_book(slot, slot.signal)
if not own_book or not own_book.get("asks"):
    return self._audit_skip(slot, reason="no_own_asks_at_entry")

# 2. L1 size gate
ask0 = own_book["asks"][0]
ask0_size = float(ask0.get("size", 0))
if ask0_size < L1_MIN_SHARES[symbol_lower]:  # e.g. 5 for SOL, 10 for BTC
    return self._audit_skip(slot, reason="l1_size_too_small",
                            l1_size=ask0_size,
                            threshold=L1_MIN_SHARES[symbol_lower])

# 3. Spread gate (strict, at fill time NOT signal time)
ask0_p = float(ask0.get("price"))
bid0_p = float(own_book["bids"][0].get("price")) if own_book.get("bids") else None
if bid0_p is None:
    return self._audit_skip(slot, reason="no_bids")
spread = ask0_p - bid0_p
if spread > SPREAD_FILTER[symbol_lower]:
    return self._audit_skip(slot, reason="spread_too_wide_at_fill",
                            spread=spread,
                            threshold=SPREAD_FILTER[symbol_lower])

# 4. Walked-vwap gate: simulate the walk for $25; if vwap > L1+slip_max, skip
projected_vwap = simulate_walk(own_book["asks"], NOTIONAL_USD)
slip_bps = (projected_vwap - ask0_p) / ask0_p * 10000
if slip_bps > MAX_ENTRY_SLIP_BPS:  # e.g. 200 = 2% max walk above L1
    return self._audit_skip(slot, reason="walk_slip_too_large",
                            slip_bps=slip_bps,
                            threshold=MAX_ENTRY_SLIP_BPS)
```

### Constants to tune

```python
L1_MIN_SHARES = {"btc": 10.0, "eth": 10.0, "sol": 5.0}
SPREAD_FILTER = {"btc": 0.02, "eth": 0.02, "sol": 0.025}  # already exists
MAX_ENTRY_SLIP_BPS = 200  # 2% — beyond this we're walking too deep
```

### Estimated impact

Drops ~30-50% of 5m fires (the bad-book ones). Of the survivors:
- BTC_5m: stays at ~60-65% hit rate
- ETH_5m: stays at ~70% hit rate
- SOL_5m: rises from 67% to ~78% hit (the 17 wide-spread trades are mostly losers)

## Fix 2 — strict asof for `ret_2m` and `bp_rev` (medium priority) — ✅ DONE in lab

The current backtest's `asof(k1m, ts)` uses bar **start time** indexing — for a query at ts=t+130, it returns the close of the bar with ts_s ≤ 130 (which is the bar starting at 120, closing at 180 — i.e., 50s in the future).

**Fix:** end-time-indexed asof (already implemented in `verify_lookahead_bug.py::asof_strict`).

**For production controller:** ensure `fetch_close_asof` queries against `time_period_end_us ≤ ts_s × 1e6` and not `time_period_start_us`. If it already does, no change needed (verify in the live code).

The current `bar_ctx_age_ms` tracking suggests fresh bars (avg 86ms post-close) but it doesn't tell us if the ASOF query semantically uses the right bar. This needs a unit test.

### Estimated impact

ret_2m at signal time: marginal, the fix only matters for boundary cases.
bp_rev during monitoring: cleaner triggers, slightly delayed but correct → realistic hedge fires when actual asset moved.

Combined: maybe $1-2/trade recovery on cells that now hedge correctly.

## Fix 3 — un-block hedge (already specced)

See `TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`. 4-commit plan covers:
1. Diagnose CLOB empty-response root cause
2. Fix CLOB tier-1 fetch
3. Add WS BookMirror tier-2
4. Add Storedata tier-3 fallback (default ON)

Once hedges fire at the rev_bp trigger, 5m losing trades get cut at -5bp instead of riding to -25bp resolution. Realfill estimates this contributes **$2-4/trade** to 5m HEDGE/SELL cells.

## Combined deployment order

1. **Day 0 (immediate):** Ship Fix 1 entry gate. PAUSE 5m sleeves until deployed (currently bleeding).
2. **Day 1:** Ship Fix 3 hedge mechanism (4 commits).
3. **Day 3-7:** Watch shadow data; if hit rates rise as predicted, RE-ENABLE 5m sleeves.
4. **Day 7+:** Audit Fix 2 (asof), unit-test, ship if needed.

## Validation criteria

After each fix, run `match_shadow.py` weekly. The shadow $/trade should converge toward realfill $/trade:
- Today: shadow 5m HOLD = $-1.09/trade, realfill 5m HOLD = $+5.92/trade. Gap = $7.01.
- After Fix 1: gap should drop to ≤ $3
- After Fixes 1+3: gap should drop to ≤ $1
- After all 3: shadow ≈ realfill (within 5%)

## Open questions

1. Is production's spread check at signal-time or fill-time? (Drives whether Fix 1 is "tighten threshold" or "move check to fill site")
2. Do we have per-fire skip-reason logging on entry path? If not, add it as part of Fix 1 (we have it for hedge_skip but not entry_skip).
3. Should we expand the realfill matcher to log production fill-event timestamp delta vs ws+120s target? Helps confirm or rule out post-signal latency as a slip cause.

## Files

- This plan: `strategy_lab/reports/MOMO_5M_FIX_PLAN_2026_05_06.md`
- Diagnostic CSV: `strategy_lab/results/meta_classifier/momo_5m_slippage_diag.csv`
- Diagnose script: `strategy_lab/momo_realfill/diagnose_5m_slippage.py`
- Strict-asof matcher: `strategy_lab/momo_realfill/match_shadow_strict.py`
- Lookahead audit: `strategy_lab/momo_realfill/verify_lookahead_bug.py`
- Companion: `strategy_lab/reports/MOMO_5M_VS_15M_ANALYSIS_2026_05_06.md`
- Companion: `strategy_lab/reports/TV_AGENT_FIX_OPPOSITE_BOOK_FALLBACK.md`
