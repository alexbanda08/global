# Strategies G / H / I — Macro overlay, CLOB mispricing, binance-only baseline

**Run date:** 2026-05-16
**Universe:** chainlink-resolved BTC/ETH/SOL × 5m/15m, 24,438 markets (Apr 24 → May 16).
**Anchor:** EARLY = `ws_s + 120s`. LATE-15m = `slot_end − 60s` (15m only).

## Files
- Scripts: `strat_G_dominance.py`, `strat_H_mispricing.py`, `strat_I_binance_only.py`
- Results: `I_sweep_early.csv`, `I_sweep_late15m.csv`, `G_table*.csv`, `H_sweep_*.csv`, `H_trades.parquet`, `H_baselines.parquet`

---

## Strategy I — Binance-only momentum baseline

**Hypothesis.** Just binance OHLCV anchored on production `ws_s`. Is there any edge?

**Setup.** Signal = sign of return over observation window. EARLY uses `[ws_s, ws_s+window]` (strictly causal). LATE-15m uses `[slot_start, slot_end−60s]` for 15m. Threshold sweep on |ret|: {0, 5, 10, 20, 50} bp.

**EARLY:**

| thr_bp | n | hit_rate | pnl_at_0.5 |
|---:|---:|---:|---:|
| 0  | 22,101 | 0.4834 | −23,716.5 |
| 5  | 12,594 | 0.4700 | −21,810.0 |
| 10 | 6,924  | 0.4659 | −13,413.0 |
| 20 | 2,389  | 0.4290 | −8,987.5  |
| 50 | 229    | 0.4760 | −329.5    |

**LATE-15m:**

| thr_bp | n | hit_rate | pnl_at_0.5 |
|---:|---:|---:|---:|
| 0  | 5,565 | 0.9292 | +116,839.5 |
| 5  | 3,904 | 0.9854 | +92,826.5  |
| 10 | 2,528 | 0.9956 | +61,391.5  |
| 20 | 1,059 | 0.9991 | +25,896.0  |
| 50 | 120   | 1.0000 | +2,940.0   |

**Verdict.**
- **EARLY: NULL.** Last-window momentum tells you nothing about next window at the production anchor.
- **LATE-15m: NULL (tautology).** 93-100% hit is reading 14/15 of the prediction window itself. **Critical baseline:** ANY signal at LATE-15m must BEAT 93% hit to be alpha. Most "high-hit" LATE-15m signals from other strategies are WORSE than this trivial baseline.

---

## Strategy G — BTC dominance regime overlay

**Hypothesis.** weekly_delta(BTC.D) → directional bias on per-asset 5m/15m outcomes.

**Data caveat.** `CRYPTOCAP_BTC_D` ends 2026-05-01 → universe partitioned into FRESH (~8,859 mkts before May 2) and STALE (~15,579 forward-filled). Regime distribution is 91% DOM_UP, only 9% DOM_DN — sample structurally inadequate.

**Test — overlay vs naive (Strategy I baseline):**

| label | n | hit_rate | pnl_at_0.5 |
|---|---:|---:|---:|
| NAIVE (all)              | 22,101 | 0.4834 | −23,716.5 |
| NAIVE (fresh)            | 6,761  | 0.4854 | −6,566.0  |
| NAIVE+WEEKLY-DOM (fresh) | 4,529  | 0.4869 | −4,077.5  |
| NAIVE+DAILY-DOM (fresh)  | 4,514  | 0.4854 | −4,395.5  |

Overlay gain inside noise (+0.15pp hit, −33% fires).

**Verdict.** **NULL** on this window. 21 days is too short and 91% one-sided dominance regime is untestable. Needs ≥ 6 months mixed-regime data.

---

## Strategy H — CLOB mispricing vs binance-momentum fair-p

**Hypothesis.** `p_clob_up = (bid_0+ask_0)/2` on Up book. `fair_p_up = clamp(0.5 + 0.5·tanh(2·z), 0.10, 0.90)` with `z = ret_obs / sigma_30min`. Trade direction of `edge = fair_p_up − p_clob_up` when `|edge| > threshold`.

**Setup.** Real L25 ask-walk for $25, spread filter (BTC/ETH 0.02, SOL 0.025), 2%-on-profit fee. EARLY fires at ws_s+120; LATE-15m at slot_end−60s.

**Overall sweep:**

| variant | thr | n | hit | total_pnl ($) | pnl/trade |
|---|---:|---:|---:|---:|---:|
| early  | 0.02 | 16,315 | 0.5016 | −11,244.6 | −0.69 |
| early  | 0.05 | 16,026 | 0.5015 | −11,267.1 | −0.70 |
| early  | 0.10 | 15,646 | 0.5025 | −10,289.6 | −0.66 |
| early  | 0.15 | 15,267 | 0.5028 |  −9,821.3 | −0.64 |
| late15 | 0.02 |  3,277 | **0.173** | **−33,946.7** | −10.36 |
| late15 | 0.05 |  2,801 | **0.159** | **−30,854.5** | −11.02 |
| late15 | 0.10 |    430 |  0.6256 |    +868.6 | +2.02 |
| late15 | 0.15 |    261 |  0.5939 |    +921.8 | +3.53 |

**Best config:** late15 thr=0.15 → n=261, hit 59.4%, +$921.8. Also late15 thr=0.10 → n=430, hit 62.6%, +$868.6.

**Per-asset (late15 thr=0.10/0.15):** ETH/SOL strongest (67-69% hit), BTC weaker (49-56%).

**Interpretation.**
- LATE-15m at LOW edge (0.02, 0.05) is **inverted**: hit 16-17%. CLOB has already absorbed the momentum; naive "fair > clob" fights an already-correct market. **Candidate for sign-flip alpha** but classic overfit risk.
- LATE-15m at HIGH edge (0.10, 0.15) the surviving cases are where book hasn't repriced yet — 60-69% hit. Small n. vwap on sample fires is 0.0085–0.0127 (deep ITM); $25 fillability suspect.

**Verdict.**
- **EARLY: NULL** — CLOB efficient at ws_s+120.
- **LATE-15m thr ≥ 0.10: WEAK-POSITIVE** — needs (a) permutation test, (b) fillability check, (c) walk-forward.
- **LATE-15m thr ≤ 0.05: NULL-INVERTED** — potential fade alpha; needs mechanistic justification.

---

## Cross-strategy take-aways

1. **Production anchor (`ws_s+120s`) is brutally efficient.** Three independent angles (I naive, G overlay, H mispricing) all converge to ~50% hit and slightly-negative PnL.
2. **LATE-15m "high hit" is auto-correlation** — Strategy I baseline at 93% defines the trivial ceiling.
3. **Macro overlays are blocked by data**: dominance cache ends May 1, 91% DOM_UP sample. Not testable.
4. **Next session priority:** validate H late15 thr ≥ 0.10 (n=430, hit 62.6%) with permutation, fillability, walk-forward.

## Verdict summary

| Strategy | Best config | n | hit | total PnL | Verdict |
|---|---|---:|---:|---:|---|
| G | NAIVE + weekly-dom (fresh) | 4,529 | 0.4869 | −$4,077.5 | NULL |
| H | LATE-15m, edge ≥ 0.15 | 261 | 0.5939 | +$921.8 | **WEAK-POSITIVE** |
| H | LATE-15m, edge ≥ 0.10 | 430 | 0.6256 | +$868.6 | **WEAK-POSITIVE** |
| H | EARLY (any thr) | ~16k | ~0.502 | ≈ −$10k | NULL |
| I | EARLY (any thr) | various | 0.43–0.48 | negative | NULL |
| I | LATE-15m (any thr) | various | 0.93–1.00 | positive | NULL (tautology) |
