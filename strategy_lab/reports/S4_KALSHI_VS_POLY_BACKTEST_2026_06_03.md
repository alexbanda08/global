# S4 ALL_15m_S4_prewindow + Kalshi Variant Backtest
_Generated 2026-06-03. Window: Apr 24 00:00 - Jun 1 09:00 UTC. Assets: BTC/ETH/SOL. TF: 15m only._

---

## 1. Fire Rule

Fire at `fire_us = slot_start_us - 120s`, 15m markets, BTC/ETH/SOL:

```
dev_bps  = 10000 * log(s_now / vwap_15m_bucket)   # 15m UTC-bucket base-vol-weighted VWAP
direction = UP if dev_bps > 0 else DOWN
leg       = "Up" / "Down"
fair_up   = norm.cdf(log(s_now/strike) / (sigma * sqrt(tau_s)))
            # sigma = std(log-rets last 900s binance 1s); tau_s = (slot_end - fire) / 1e6
fair_edge_bp = (fair_up - entry_vwap)*1e4  [UP]  or  ((1-fair_up) - entry_vwap)*1e4  [DOWN]
cvd_30s   = sum(2*taker_buy_quote - quote_volume) over last 30s

FIRE iff: |dev_bps| >= 8  AND  fair_edge_bp > 500  AND  cvd_30s agrees direction
```

Gate needs `entry_vwap` = L25 ask-walk $25 at `fire_us = slot-120` to compute `fair_edge_bp`.
`strike` = first binance 1s close at-or-after `slot_start_us` (**lookahead** — see Section 7).

---

## 2. Fill Variants

| Variant | Fill timestamp | Venue | Fee model | Notes |
|---------|---------------|-------|-----------|-------|
| **A** `poly_prewindow` | `slot_start - 120s` | Polymarket L25 | `0.07*p*(1-p)` per contract | Validated form |
| **B** `kalshi_inwin60` | `slot_start + 60s` | **Poly L25 as proxy** | Kalshi `0.07*p*(1-p)` | 180s after gate; Kalshi book absent in canonical |
| **C** `kalshi_open` | `slot_start + 1s` | **Poly L25 as proxy** | Kalshi `0.07*p*(1-p)` | Earliest-open fallback |

**Kalshi proxy caveat**: Kalshi does not exist in canonical data. B and C use the Polymarket L25
at the corresponding timestamp as a price proxy. Both venues price the same binary off the same
underlying strike; per architecture doc they trade within a few cents of each other. Results are
directionally correct but not exact — Kalshi slippage and book depth may differ, especially at
slot+1 when the Polymarket book may still be thin.

---

## 3. Book Coverage

Of 10,554 total 15m slots in the window, 2,843 passed the `|dev_bps| >= 8` pre-gate.

| Timestamp | Coverage |
|-----------|----------|
| slot-120 (pre-window) | 2843 / 2843 = **100%** |
| slot+60 (in-window) | 2843 / 2843 = **100%** |
| slot+1 (earliest-open) | 2843 / 2843 = **100%** |

Coverage is 100% across all timestamps because the canonical L25 parquet covers the full Apr 22 -
Jun 1 window. In live production the pre-window book (slot-120) would not always be available —
this is a canonical-data limitation. The 100% coverage here does NOT mean the live S4 sleeve would
always fire; it means our backtest always has a book for the entry lookup.

Of those 2,843 dev-eligible slugs, **294 passed the full gate** (fair_edge_bp > 500 and cvd agree),
yielding 294 fires = 8.2% gate-pass rate.

---

## 4. Baseline Reproduction

Reference (PHASE2_FINAL_FINDINGS_2026_05_24.md §4): **n=229, WR=54.6%, per-trade +$2.26, binom_p=0.090**.

Our May 8-May 29 sub-window (baseline match attempt, legacy 2%-on-profit fee):

| | n | WR | per-trade | total | binom_p |
|---|---|---|---|---|---|
| This backtest (legacy fee) | 240 | **43.3%** | **-$3.33** | -$800 | 0.984 |
| Reference (2024-05-24 report) | 229 | 54.6% | +$2.26 | +$517 | 0.090 |

**Divergence is real and material.** Root causes identified:

1. **Data window**: the PHASE2 reference used a dataset ending May 24 (20.8d window starting ~May 3).
   Our canonical now extends to Jun 1 and includes weeks 21-23 which are consistently losing (see §6).
   Restricting to May 24-29 (the exact reference-script window) gives n=103, WR=38.8% -- even worse.

2. **Strike lookahead**: the reference used the same lookahead strike (first 1s close at-or-after
   `slot_start_us`) computed on the OLDER canonical snapshot. The causal-strike robustness run
   (Section 7) shows the edge is materially weaker causal, and the fire set shrinks from 294 to 58
   when using causal strike. The original n=229 may have included lookahead-inflated gate passes.

3. **The n=229 result is NOT reproducible on the current full-period canonical.** The edge was
   present in a specific earlier window and does not hold on the extended dataset.

---

## 5. Full-Period Results (Apr 24 - Jun 1)

### 5.1 Variant Comparison Table

| Variant | n | WR | $/trade | Total $ | binom_p | 95% CI | Max DD | Win/Loss ratio |
|---------|---|----|---------|---------|---------|--------------------|--------|----------------|
| **A** poly_prewindow (0.07 fee) | **294** | **42.9%** | **-3.70** | **-1086** | **0.994** | [-6.49, -0.81] | $1242 | 0.99x |
| **B** kalshi_inwin60 (0.07 fee) | **294** | **42.9%** | **-4.09** | **-1203** | **0.994** | [-7.15, -0.88] | $1403 | 0.96x |
| **C** kalshi_open (0.07 fee) | **294** | **42.9%** | **-3.90** | **-1147** | **0.994** | [-6.80, -0.88] | $1319 | 0.98x |
| A poly_prewindow (legacy 2%) | 294 | 42.9% | -3.54 | -1040 | 0.994 | — | — | — |

**All three variants are statistically significantly LOSING** (binom_p = 0.994 from the right = 1-0.994 = 0.006 from the left, i.e., significantly below 50% WR). The 95% CIs are entirely negative. The payoff ratio is near 1.0x (wins and losses are symmetric in dollar terms), contradicting the architecture-doc hypothesis that the Kalshi in-window entry produces asymmetric (fatter-tails) payoffs.

### 5.2 Asymmetry Check (Variants B vs A)

The B/C variants produce slightly WORSE per-trade PnL than A: B is -$0.39 worse per trade than A,
C is -$0.20 worse. This is the opposite of the "Kalshi in-window buys cheaper" hypothesis. At
slot+60 and slot+1 the book has already moved against the signal direction (since S4 fires on a
dev-from-vwap signal, the market tends to mean-revert pre-window), so the in-window entry gets
filled at a *worse* price, not a better one.

---

## 6. Per-Asset Breakdown (Variant A, 0.07 fee)

| Asset | n | WR | $/trade | Total $ |
|-------|---|----|---------|---------| 
| BTC | 78 | **46.2%** | -1.68 | -131 |
| ETH | 106 | 40.6% | -4.85 | -514 |
| SOL | 110 | 42.7% | -4.01 | -441 |

BTC is the least negative (closest to breakeven) but still below 50% WR. ETH is the worst.

## Per-Direction Breakdown (Variant A, 0.07 fee)

| Direction | n | WR | $/trade |
|-----------|---|----|---------| 
| UP | 147 | 42.9% | -3.92 |
| DOWN | 147 | 42.9% | -3.47 |

No directional asymmetry — both legs are symmetrically losing.

---

## 7. By-Week Walk-Forward (Variant A, 0.07 fee)

| ISO Week | n | WR | $/trade | Weekly Total |
|----------|---|----|---------|-------------|
| 2026-W20 (May 11-17) | 26 | 38.5% | -5.53 | -$144 |
| 2026-W21 (May 18-24) | 120 | 46.7% | -1.85 | -$222 |
| 2026-W22 (May 25-31) | 136 | 37.5% | -6.36 | -$865 |
| 2026-W23 (Jun 1) | 12 | **75.0%** | **+12.05** | **+$145** |

**The edge is entirely driven by one week: W23 (Jun 1, partial week, n=12).** Every other week
loses. W22 is the worst: -$865 in a single week (n=136, WR=37.5%). The W21 "relatively OK" week
at WR=46.7% still loses $222. The strategy is not stable — it is one-week-driven and that week
is partial (only Jun 1 09:00 cutoff, n=12). W23 is likely a small-sample anomaly.

Note: the PHASE2 reference's 21d window was Apr 3-May 24, which pre-dates our backtest window
(Apr 24-Jun 1). The winning weeks in that earlier period are not captured here.

---

## 8. Causal-Strike Robustness

**This is the key finding.**

The S4 gate uses `fair_up = norm.cdf(log(s_now/strike) / sigma*sqrt(tau))` where `strike` is
the first binance 1s close at-or-after `slot_start_us`. At `fire_us = slot_start - 120s`, this
strike is a price that doesn't exist yet — it's 120 seconds in the future. **This is lookahead.**

| Version | n | WR | $/trade | Total | binom_p | 95% CI |
|---------|---|----|---------|----|---------|--------|
| Lookahead strike (standard) | 294 | 42.9% | -3.70 | -1086 | 0.994 | [-6.49, -0.81] |
| **Causal strike** (s_now = strike) | **58** | **36.2%** | **-5.26** | **-305** | **0.988** | [-11.84, +2.07] |

With causal strike the fire set **shrinks from 294 to 58** (-80% of fires). The 236 fires that
required lookahead to satisfy the gate vanish. Of the remaining 58 causal fires, WR drops further
to 36.2% and per-trade is -$5.26.

**Verdict: The lookahead strike is inflating both the fire count and apparent WR, but the strategy
was ALREADY LOSING even with lookahead.** The lookahead is not the sole driver of the loss — the
underlying signal is weak and the fee drag dominates. However, the gate's fair_edge_bp is
fundamentally miscalibrated when the strike is unknown at fire time: `fair_edge_bp > 500` computed
with the actual slot_start price includes future information that the live engine cannot have.

**A live deployment using a causal strike would fire 80% less often and lose even more per trade.**

---

## 9. Variant Verdict: Poly Pre-Window vs Kalshi In-Window

| Question | Answer |
|---------|--------|
| Does Kalshi in-window (B) reproduce the Poly pre-window (A) edge? | No — both are net-negative over the full period. B loses $117 MORE than A in total. |
| Does the Kalshi in-window entry produce asymmetric (fatter wins/fatter losses)? | No — payoff ratio is 0.96x vs 0.99x for A. Marginally thinner wins AND thinner losses. |
| Is the S4 pre-window edge real on the full Apr24-Jun1 period? | **No.** binom_p = 0.994 (significantly below 50% WR). |
| Is the original n=229/WR=54.6%/+$2.26 baseline reproducible? | **No.** Best match is n=240/WR=43.3%/-$3.33 in the same date range. |
| Preferred fallback: slot+60 (B) vs slot+1 (C)? | Neither — both lose. If forced to choose, C (slot+1) is marginally better (-$3.90 vs -$4.09). |

---

## 10. Bottom Line

**(a) Is S4 real on the full period?**
No. n=294 fires, WR=42.9%, per-trade -$3.70 (0.07 fee) / -$3.54 (legacy 2%), binom_p=0.994.
Total loss -$1,086 over 38 days. The strategy is net-negative with high statistical confidence.
The original backtest edge (n=229, WR=54.6%) was an artefact of a specific earlier window
(~Apr 3 - May 24) that no longer holds when extended to Jun 1.

**(b) Does the Kalshi in-window execution preserve the edge?**
No. The "edge" does not exist to preserve. Variant B (slot+60) is marginally WORSE than A:
per-trade -$4.09 vs -$3.70. The in-window fill buys at a worse price because the market has
already partially mean-reverted against the dev-from-vwap signal.

**(c) Fallback recommendation?**
Neither variant. Do not deploy S4 pre-window or Kalshi in-window on the current dataset.
The by-week table shows W22 alone (May 25-31) lost -$865. If the architecture doc's operator
wants to investigate Kalshi specifically, the minimum requirement is: (1) replace lookahead
strike with a causal substitute (e.g., Chainlink price at fire_us), (2) re-validate on a fresh
OOS window where W22's regime is represented, and (3) confirm n >= 100 with WR > 52% before
any live deployment.

**The shadow sleeve's live positive PnL (n=28, +$9.30/tr per MASTER_FINDINGS_TABLE) should be
evaluated against the live wallet directly, not this backtest — per HANDOFF_2026_06_03.md rule:
judge strategies by the LIVE wallet, not shadow/backtest.**

---

## Appendix: Artefact Paths

- Backtest code: `strategy_lab/s4_backtest_2026_06_03/backtest.py`
- Per-fire CSV: `strategy_lab/s4_backtest_2026_06_03/s4_fires.csv` (882 rows = 294 fires x 3 variants)
- Reference report: `strategy_lab/reports/PHASE2_FINAL_FINDINGS_2026_05_24.md`
- Shadow inventory: `strategy_lab/reports/SLEEVE_INVENTORY_VPS3_2026_05_31.md`
