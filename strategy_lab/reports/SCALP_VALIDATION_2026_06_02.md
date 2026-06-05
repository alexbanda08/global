# Intra-Window Scalp — Validation Verdict — 2026-06-02

**Strategy:** Lag-taker fires (FAST_TAKER_LAGV2) → buy token at fire_us → EXIT mid-window (sell at bid) rather than hold to resolution.
**Universe tested:** BTC + ETH, delta≥3 (n=1,342) and delta≥5 (n=430) lag-taker fires from `lag_taker_fires_oos_2026_06_01.parquet`.
**Agents run:** fee_model, exit_oos, cusum_vwap_gates, jump_asym.

---

## 1. Is the Mid-Window Exit Real? (Does TIME+90s Beat Hold?)

**YES — the effect is real and OOS-robust at low/zero fees.**

### Headline numbers (BTC+ETH, delta≥5, n=430)

| Strategy | $/trade (fee=0) | t-stat | $/trade (fee=0.07×both) | t-stat |
|---|---|---|---|---|
| HOLD to resolution | +$0.85 | 0.88 | +$0.85 | 0.88 |
| TIME+90s exit | +$1.99 | **4.33** | +$0.80 | 1.70 |
| TP@0.65 exit | +$1.23 | 2.45 | ~$0.00 | ~0.00 |

### OOS robustness by segment (BTC+ETH, delta≥3, n=1,342, TIME+90s exit)

| Segment | n | HOLD $/tr | HOLD t | T+90s fee=0 $/tr | T+90s fee=0 t |
|---|---|---|---|---|---|
| bwd_oos (unseen past) | 480 | +$0.06 | 0.06 | **+$1.18** | **2.72** |
| fit_IS (in-sample) | 286 | +$1.49 | 1.22 | +$0.89 | 1.47 |
| fit_OOS (held-out) | 500 | +$1.83 | 2.06 | **+$1.62** | **3.97** |
| fwd_oos (recent, n=76) | 76 | +$2.28 | 0.97 | -$0.03 | -0.03 |
| **ALL** | **1,342** | +$1.15 | 2.06 | **+$1.21** | **4.67** |

HOLD itself is barely significant (t=2.06) and noise in bwd_oos (t=0.06). The exit strategy adds structural edge across bwd_oos and fit_OOS. The fwd_oos result (n=76, t=-0.03) is inconclusive — too small to refute or confirm.

### Optimal exit timing (fee=0, delta≥3, n=1,342)

| Exit lag | Reach% | $/trade | t-stat |
|---|---|---|---|
| HOLD | 100% | +$1.15 | 2.06 |
| +45s | 99% | +$1.22 | **6.50** |
| +60s | 99% | +$1.32 | **6.24** |
| +90s | 99% | +$1.21 | **4.67** |
| +120s | 99% | +$0.92 | 3.02 |
| +180s | 98% | +$0.98 | 2.68 |

**Sweet spot: +45–60s after fire_us.** Highest t-stat (6.50) at +45s; highest $/trade (+$1.32) at +60s. The plateau is flat from 45–90s, degrading past 120s.

**S2 stale-lock refuted:** Using frozen asks as exit (rather than walking the live bid) was tested and found strictly worse — book staleness hurts, not helps.

---

## 2. The Fee Question — What Is the Real Round-Trip Taker Fee?

**This is the make-or-break variable. The answer is fee≈0 on the buy leg; small fee on the exit sell.**

### Fee structure verified against live production data

| Leg | Production behavior | Source |
|---|---|---|
| Buy (cross ask, taker) | **$0 per-fill** | Loser PnL = -placed_usd exactly (if buy fee existed, losers would show extra deduction). 20/20 loser events confirmed. |
| Hold to resolution (winning) | 2% on profit only | 30/30 winner events confirm `pnl = shares × (1-p) × 0.98`. |
| Sell mid-window (exit, taker) — losing | $0 | 19 losing scalp exits: `pnl = (sell_v - buy_v) × shares` exactly. |
| Sell mid-window (exit, taker) — winning | ~$0.13–$0.38/trade | Docs formula `0.07 × sell_v × (1-sell_v) × shares` (bell: ~$0.13); code's linear: ~$0.29–0.38. No profitable scalp exits in live data to verify directly. |

The `0.07 × p × (1-p)` formula applies at CTF settlement for winners, NOT as a per-fill CLOB charge. CLOB `feeRate ≈ 0` for these crypto up-down markets. **FEE0 (zero per-fill) is the correct baseline for the buy leg.**

### Fee breakeven sweep (TIME+90s, delta≥3, n=1,342)

| Fee/leg | $/trade | t-stat | Significant? |
|---|---|---|---|
| 0.00 | +$1.21 | 4.67 | YES |
| 0.01 | +$1.03 | 3.97 | YES |
| 0.02 | +$0.85 | 3.28 | YES |
| 0.03 | +$0.67 | 2.58 | YES |
| 0.04 | +$0.49 | 1.89 | borderline |
| 0.05 | +$0.31 | 1.20 | no |
| **0.07** | **-$0.05** | **-0.18** | **NO** |

**Breakeven at ~3.5% per leg.** The edge survives up to ~3% per leg. The full symmetric `0.07×both-legs` model kills the edge entirely. The realistic scenario (0% buy-leg + ~1.5–2% exit-sell for profitable trades) sits well inside the viable zone at ~+$0.90–1.10/trade.

### Realistic net edge (TIME+90s, delta≥3)

- FEE0 headline: **+$1.21/trade (t=4.67)**
- Minus estimated exit-sell fee (bell curve, $0.13–0.14/trade): **~+$1.07–1.08/trade**
- Minus exit-sell fee (code linear, $0.29–0.38/trade): **~+$0.83–0.92/trade**
- FEE07-both-legs (too pessimistic, charges buy leg that production does not): +$-0.05/trade

**Realistic range: +$0.83 to +$1.08/trade (t≈3–4).** The edge is alive under realistic fees.

---

## 3. Best Gate Lift (CUSUM + VWAP)

Two gates were evaluated on the TIME+90s scalp. Both pass. The direction-alignment variant of CUSUM was refuted.

### S1 CUSUM — Strength gate (any direction, NOT directional alignment)

Key finding: CUSUM *direction alignment* (CUSUM trend agrees with fire direction) HURTS. CUSUM *strength* (|S| > h, regardless of direction) is the real signal.

| Gate | delta | n | fee=0 $/tr | t | fee=0.07 $/tr | t |
|---|---|---|---|---|---|---|
| CUSUM_strength h≥1.0, PASS | ≥3 | 358 | +$1.98 | 3.27 | +$0.89 | 1.47 |
| CUSUM_strength h≥1.0, FAIL | ≥3 | 984 | +$0.27 | 0.70 | -$0.81 | -2.10 |
| CUSUM_strength h≥1.0, PASS | ≥5 | 109 | +$4.77 | 5.76 | +$3.64 | **4.34** |
| CUSUM_strength h≥1.0, FAIL | ≥5 | 321 | +$1.05 | 1.95 | -$0.16 | -0.30 |

Physical interpretation: strong CUSUM = the book is in a trending state → price continues to move in the first 90s → exit at a better bid. Choppy CUSUM = book oscillates → scalp stagnates.

### S6 VWAP gate — entry_vwap displacement (inverted from prior hypothesis)

The gate is inverted: **low entry vwap (near 0.50) beats high vwap (>0.60).** Tokens already priced at 0.62+ on entry have less remaining upside for the 90s window.

| Gate | delta | n | fee=0 $/tr | t | fee=0.07 $/tr | t |
|---|---|---|---|---|---|---|
| entry_vwap < 0.55 | ≥3 | 417 | +$2.33 | 3.30 | +$0.96 | 1.36 |
| entry_vwap > 0.55 | ≥3 | 925 | +$0.01 | 0.02 | -$0.95 | -2.70 |
| entry_vwap < 0.55 | ≥5 | 118 | +$5.06 | 4.67 | +$3.45 | **3.16** |
| entry_vwap > 0.55 | ≥5 | 312 | +$0.84 | 1.79 | -$0.20 | -0.42 |

### Combined gate (CUSUM_strength h≥1.0 OR entry_vwap<0.55)

Gates are nearly uncorrelated (phi = -0.011). OR combination on delta≥5:

| Gate combo | delta | n | fee=0 $/tr | t | fee=0.07 $/tr | t |
|---|---|---|---|---|---|---|
| S1 OR S6 | ≥5 | 198 | +$4.69 | **6.54** | +$3.34 | **4.62** |
| S1 AND S6 | ≥5 | 30 | +$6.20 | 2.79 | +$4.62 | 2.07 |
| Ungated baseline | ≥5 | 430 | +$1.99 | 4.33 | +$0.80 | 1.70 |

**Best filter: (CUSUM_strength ≥1.0 OR entry_vwap<0.55) + delta≥5 → n=198 fires, fee=0.07 $/tr = +$3.34/trade (t=4.62).**

This is the only combination that produces significant edge even under the pessimistic 7%-both-legs fee assumption.

### S4 Semivariance asymmetry (A120) — REFUTED

The hypothesis that downside-variance dominance (A<0.35) selectively lifts DOWN fires was tested and refuted. A<0.35 shows z vs base_dir = -0.54 for DOWN direction — marginally worse than base rate. FEE0 slight lift (+$1.52 vs +$1.21 for the ungated) disappears under FEE07 ($0.27). A-semivariance adds no incremental value as a directional gate or scalp quality filter.

---

## 4. Downside and Drawdown (delta≥5, TIME+90s)

| Metric | FEE0 | FEE07 |
|---|---|---|
| Mean $/trade | +$1.997 | +$0.801 |
| t-stat | 4.33 | 1.73 |
| P1 (worst 1%) | -$22.6 | -$23.4 |
| P5 (worst-5% threshold) | -$16.1 | -$17.2 |
| P10 | -$11.1 | -$12.3 |
| P25 | -$3.3 | -$5.0 |
| Median | +$3.1 | +$1.9 |
| Mean of worst-5% trades | -$19.3 (n=22) | -$20.3 (n=22) |
| % trades negative | 36.5% | 41.4% |
| Max time-ordered drawdown | -$104 | -$162 |
| Sanity check: max |PnL| | $26.6 | $26.6 |

**Risk profile:** 36% of trades lose. The distribution is bimodal — losers (median ~-$10 to -$16, driven by thin exit book → depressed bid fills) and winners (median ~+$3 to +$8). Tail losses are near-full-stake (-$19 to -$23 mean worst-5%), which happen when the exit book is thin and the bid walk crushes the exit vwap. Max drawdown of -$104 (FEE0) / -$162 (FEE07) across 430 time-ordered trades reflects the lumpy loss distribution, not catastrophic blowup.

**Key risk factor:** exit book liquidity. Thin-book exits (few L25 bid levels) produce near-full-loss outcomes regardless of direction correctness. A min-book-depth gate at exit (analogous to `min_book_events=25` at entry in `LiveMimicConfig`) is not yet validated but would reduce tail losses.

---

## 5. GO / NO-GO Recommendation

### Verdict: CONDITIONAL GO (paper-trade, gated, fee verification required)

**The scalp edge is real.** TIME+90s exit beats hold-to-resolution on lag-taker fires, is OOS-stable in bwd_oos and fit_OOS segments, and the optimal timing (45–60s) is robust across the full delta≥3 universe with t≥6.

**The edge is viable under realistic fees.** The buy leg charges $0 per-fill in production. The exit sell fee is small (~$0.13–0.38/trade on winners). At realistic fees the net edge is +$0.83–1.08/trade on delta≥3 (t≈3–4), well above noise. The edge dies only if Polymarket imposes symmetric 7% taker on BOTH legs — not the current production behavior.

**The gated universe (S1 OR S6, delta≥5, n=198) is the most robust entry point** — it shows +$3.34/trade (t=4.62) even under the pessimistic full-7% assumption. Start here.

### Blockers before live sizing

1. **Fee verification on exit sells:** Deploy 10–20 paper scalp exits and read the `trading.events` pnl field for the sell leg. Confirm whether any fee is deducted and at what rate (bell vs linear vs zero). This single datapoint resolves the +$0.80 vs +$1.99/trade ambiguity.

2. **fwd_oos gap:** The most recent segment (n=76) shows t=-0.03. This may be noise (n is small) or may indicate regime change. Accumulate more fwd_oos fires before real sizing — 200+ is the threshold for a reliable read.

3. **Signal fix first (prerequisite):** The `poly_fast_taker` signal bug (100% UP fires, per `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md`) must be fixed before any new lag-taker fires are generated. The exit-scalp validation used existing OOS fires — those are valid. New fires post-fix will form the fwd_oos cohort.

4. **Exit book depth gate:** Add a minimum bid-depth check at exit time (`sell_at_bid_partial` shares available ≥ entry shares) to avoid thin-book tail losses. Not yet validated but logically sound.

### Recommended paper-deploy spec

| Parameter | Value |
|---|---|
| Universe | BTC + ETH lag-taker fires |
| Delta filter | ≥5 bps |
| Entry gate | CUSUM_strength(h=1.0) OR entry_vwap<0.55 |
| Exit | Walk bid at fire_us + 60s |
| Fallback | Hold to resolution if book unavailable at +60s |
| Stake | $5/fire (same as V5 baseline) |
| Expected edge | +$1.00–1.50/trade realistic; +$3.34/trade under fee=0.07 gated |
| Next milestone | 50 paper fires → read exit-leg fee from trading.events |

---

*Report generated 2026-06-02. Scripts: `strategy_lab/directional/scalp_exit_validation_2026_06_02.py`, `strategy_lab/directional/cusum_vwap_gates_2026_06_02.py`. Fire universe: `strategy_lab/lag_taker_fires_oos_2026_06_01.parquet` (2,538 total; 1,342 BTC+ETH delta≥3 used for primary analysis).*
