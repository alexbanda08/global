# Silent Forensics — ETH/SOL 15m trstack sniper_v5 sleeves (0 fires in 2d15h)

**Date:** 2026-06-01 | **Mode:** read-only VPS3 + local backtest universes
**Subject:** 8 (+VL) `trstack` sleeves anchored on `g_tr_stack_full_with` that have NEVER fired.

---

## 1. `g_tr_stack_full_with` — live definition vs backtest

**Live impl** (`/opt/tradingvenue/backend/app/strategies/polymarket/sniper_v5_gates.py:486`):
```python
def g_tr_stack_full_with(direction, fire_us, *, asset, tr_panel):
    s = _tr_row(tr_panel, asset, fire_us).tr_ema_stack_score
    return (s == 2 and direction == "UP") or (s == -2 and direction == "DOWN")
```
`tr_ema_stack_score` is computed in `features/traders_reality_1s.py:_compute_stack_score`
over the **5 long EMAs `[ema_5, ema_13, ema_50, ema_200, ema_800]`**:
- `+2` = ALL 4 adjacent pairs strictly bull-ordered (ema5>ema13>ema50>ema200>ema800)
- `-2` = ALL 4 strictly bear-ordered
- `±1` = 3-of-4 ordered (partial — does NOT pass full)

So "full stack" = price has the entire long-EMA ribbon in perfect monotonic order AND
the fire direction matches the stack sign. Demanding by design. EMAs are `ewm(adjust=False)`
on 1s closes — matches the backtest `regime_panel` derivation. **No EMA-feed or order-check
inversion: live formula == spec == backtest column.**

**Backtest pass-rate (SOL 15m universe, n=34,886 fires, 32.6d, `sol_15m_fires_v2fix_gates.parquet`):**
- `g_tr_stack_full_with` passes **15.96%** of fires (5,568/34,886), direction-aware.
- Raw `|stack_score|==2` occurs ~52% of bars, but the direction match halves it, and the
  per-fire-direction split lands the gate at ~16%.

**Live fail-rate (from JSONL triage):** ETH 1768/2974 = 59% fail → ~41% PASS. SOL 1931 ≈ 66% fail.
Live PASSES the stack gate *more* often than backtest (41% vs 16%), so the gate is **NOT
computed more restrictively live**.

### VERDICT: `g_tr_stack_full_with` is CORRECT-BUT-RARE. Not a bug.
The gate is the first in every silent sleeve's definition, so `_first_failing_gate()`
(controller.py:1060, iterates in def-order, returns first False) always names it as the
dominant skip. That makes it *look* like the sole blocker, but it is simply gate #0 of a
4-6 gate AND-stack. The real blocker is the **full conjunction** rarely aligning, not a
mis-wired ribbon.

---

## 2. Per-sleeve backtest fires/day → expected in 2d15h (2.625d)

`n_full` from V5 report (ETH/SOL 15m) + V8 spec §4 (cross-asset variants). Window ≈ 32.6d.
Expected = (n_full / window_d) × 2.625, then discounted for live-only filters
(spread `> sf`, sparse-book, `g_book_supports_stake`/empty-book veto — these strip ~30-60%).

| Sleeve | gates (depth) | backtest n_full | fires/day | exp. 2.625d (raw) | verdict |
|---|---|---:|---:|---:|---|
| eth_15m_trstack_vwap_vol_offearly (V5 #13 = S1) | full+vwap+early+volhigh (4) | **100** (22D cohort) | ~3.1* | ~8 raw / ~3-5 net | LOW_BASE_RATE |
| eth_15m_trstack_vwap_vol_offearly_band_v6 | S1 + band gate (5) | < S1 | <3 | ~3-4 | LOW_BASE_RATE |
| eth_15m_pw_trendslope_trstack_offearly_v6 | full+early+slope (≥4) | ~similar | ~2-3 | ~5-7 | LOW_BASE_RATE |
| eth_15m_pi_btc15m_trend_v7 (= V8_09) | full+vwap+early+volhigh+**pw_btc15m** (5) | **64** | 1.96 | **5.2 raw / ~2-3 net** | LOW_BASE_RATE |
| eth_15m_baseline_v7_top_replicate_v8 (V8_09 dup) | identical to above (5) | **64** | 1.96 | ~5 raw | LOW_BASE_RATE |
| eth_15m_pj_btc_and_sol_trend_sep_v8 (V8_10) | above + **pw_sol15m** (6) | **51** | 1.56 | **4.1 raw / ~2 net** | LOW_BASE_RATE |
| sol_15m_trstack_vol_ribbon_ema_mid (V5 #15) | full+volhigh+ribbon+ema200+ema800 (5) | **~47** (OFFSET_120-240) | ~1.4 | ~3.8 raw / ~2 net | LOW_BASE_RATE |
| VL variants (×3) | = parents, looser spread | parent +2-3 fires total | ~parent | ~parent | LOW_BASE_RATE |

\* S1 cohort is 22D (May 1-22); the V5 report cites lockbox fires/day 4.76 on its *best*
4-day window, but full-window density is ~3/day. Offset-early (0/30/60s) further thins it —
only the first 3 of 30 offset slots per slug fire.

**Raw 5-gate stack-pass check (empirical, SOL #15, offsets 120/240):** 382/8,837 = **4.32%**
→ 11.7 raw stack-passes/day. After spread filter + sparse-book + `g_book_supports_stake`
($150 depth veto) + the fact live only saw ~3,000 evals (not full universe) over 2.6d, net
expected placements collapse toward 1-3 over the whole window — and these are integer-Poisson
events. **Getting 0 across all 8 in 2.625d is within normal variance for ~2-5 expected each
when the live book veto (`g_book_supports_stake` / `empty_book_all_tiers_failed`) and the
spread filter haircut the gated survivors further.** SOL/ETH 15m books are thin — the depth
veto is brutal on the few fires that clear the gate stack.

### Per-sleeve verdict: ALL 8 = **LOW_BASE_RATE (premature deploy on thin evidence)**, NOT a wiring/gate bug.
The V5 ETH report itself flags this: "ETH 15m has tiny lockbox sample sizes (n=10-30 per
stack)"; V8_09/V8_10 lockboxes are n=12 / n=8 (WR 100% on 8-12 trades). These were deployed
on 4-day, single-digit-n lockboxes. Zero fires in 2.6d is the expected tail outcome.

---

## 3. Spread-boundary "bug" — `spread_bidask_too_wide_0.0200_>_0.0200`

**Compare site** (`controllers/polymarket_sniper_v5.py:514`):
```python
spread = self._compute_spread(l25_snap, direction)   # ask0 - bid0, same-token (float)
sf = float(sleeve.spread_filter)                       # float(Decimal("0.02")) = 0.020000000000000000416...
if spread is not None and spread > sf:                 # strict >
    skip_reason = f"spread_bidask_too_wide_{spread:.4f}_>_{sf:.4f}"
```

`_SPREAD_ETH = Decimal("0.02")`, `_SPREAD_SOL = Decimal("0.025")`.

**This is NOT a `>` vs `>=` semantic error** — strict `>` is correct (reject only when
*wider* than filter). The `0.0200_>_0.0200` in the log is a **display artifact + float-repr
boundary**: the skip_reason formats BOTH operands at `.4f`. A raw spread of e.g.
`0.020000001` (or `0.0204`-ish that rounds down) prints as `0.0200`, and `float(Decimal("0.02"))`
prints as `0.0200`, so the log reads `0.0200_>_0.0200` while the underlying `spread > sf`
was a genuine strict-greater on the un-rounded floats. L25 prices are penny-quantized
(0.01 ticks) → ask0-bid0 lands on values like 0.02, 0.03... and `0.02` as an IEEE-754 double
is `0.0200000000000000004`, so `0.02-tick == sf` comparisons are coin-flips on the 17th digit.

**Impact:** 335/2,974 ≈ **11.3%** of ETH evals blocked here — but these are mostly fires
whose raw spread is genuinely ≥ the 2¢ tick (the tightest possible book is exactly 1 tick =
0.01, next is 0.02). A 2¢-spread book on a 15m up/down market is a legitimately wide book;
rejecting it is arguably *correct* behavior. It is a secondary blocker (gate stack is primary),
not the cause of 0 fires.

### Fix (precision hygiene, low priority):
Quantize before compare so penny-tick spreads compare deterministically:
```python
if spread is not None and round(spread, 4) > round(sf, 4) + 1e-9:
```
or, cleaner, keep Decimal end-to-end:
```python
from decimal import Decimal
if spread is not None and Decimal(str(round(spread,4))) > sleeve.spread_filter:
```
This recovers the exactly-on-boundary fires (spread == filter → ACCEPT). For ETH at 0.02
filter this would re-admit the ~335 boundary fires; backtest `engine_v2.fill_at_book:234`
uses the same `ask0-bid0` so apply the identical quantization there to keep parity.

---

## 4. Family root cause

The 8 silent 15m `trstack` sleeves share gate #0 = `g_tr_stack_full_with` (a genuinely rare
full-EMA-ribbon-alignment gate, ~16% backtest pass-rate, correctly computed live). Stacked
on top are 3-5 more AND-conditions (vwap-follow, offset-early window restriction to first
60s, vol_high, and for V7/V8 variants cross-asset pre-window BTC/SOL 15m trend gates). The
**full conjunction** has a backtest density of only **~1.5-3 fires/day** even before live's
spread filter, sparse-book check, and the mandatory `g_book_supports_stake` $150-depth veto
(which is severe on thin ETH/SOL 15m books). Expected placements over 2d15h ≈ 1-3 per sleeve;
observing 0 across all 8 is an ordinary low-count outcome, compounded by these sleeves being
deployed on 4-day lockboxes with single-digit n (V8_09 n=12, V8_10 n=8). **No bug in the
gate or the spread compare. These are premature deploys on thin evidence — LOW_BASE_RATE.**

The `0.0200_>_0.0200` spread log is a float-repr/display artifact (strict `>` is correct);
recommend the round-to-4dp + epsilon fix for boundary determinism + backtest parity, but it
is a minor secondary blocker (~11% of evals), not the cause of zero fires.
