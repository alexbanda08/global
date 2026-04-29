# Study 25 — Pure Price-Action Signal Family

**Status:** Scan complete. **3 promo-grade candidates** found, but MDDs are too
wide for standalone deployment — recommend pairing with V41 adaptive exits as
the next step.

**Date:** 2026-04-25

---

## 1. Why this study

V52's signal stack is dense in indicator-based logic (CCI, ST-flip, BB-fade,
MFI, Volume Profile, Signed Volume Divergence). A *pure price-action*
signal — one that uses only OHLC structure, no indicators, no volatility band —
should be statistically uncorrelated by construction with anything indicator-
based, providing a clean diversification channel.

Three patterns built (`strategy_lab/strategies/v54_priceaction.py`):

| Signal | Logic |
|---|---|
| `pivot_break` | close breaks a k=3 fractal pivot after 8-bar consolidation (range ≤1.5·ATR) |
| `pivot_break_retest` | same, plus retest within 6 bars and re-close above the level |
| `inside_bar_break` | inside-bar pattern (high<H[t-1] & low>L[t-1]) followed by close > mother-bar high (Al Brooks classic) |

All shifted by 1 to be next-bar-fillable in the canonical simulator.

---

## 2. Scan results — HL 4h, canonical EXIT_4H, 5181 bars

V52 proxy correlation = correlation with CCI_ETH equity (V52's biggest sleeve;
this is a tight upper bound on correlation with full V52).

### Top 10 by Sharpe

| Rank | Signal | n | Sharpe | CAGR | MDD | ρ_proxy |
|---:|---|---:|---:|---:|---:|---:|
| 1 | inside_bar_break_both_ETH | 141 | **1.29** | +40.17% | −34.2% | 0.17 |
| 2 | inside_bar_break_both_BTC | 132 | **1.00** | +28.40% | −44.3% | 0.11 |
| 3 | inside_bar_break_long_SOL | 107 | **1.00** | +25.44% | −37.8% | 0.21 |
| 4 | pivot_break_short_AVAX | 8 | 0.76 | +5.87% | −8.5% | −0.11 |
| 5 | inside_bar_break_short_ETH | 119 | 0.73 | +16.24% | −27.8% | **−0.26** |
| 6 | pivot_break_short_BTC | 13 | 0.70 | +7.19% | −14.4% | −0.02 |
| 7 | inside_bar_break_short_AVAX | 116 | 0.65 | +13.55% | −33.6% | **−0.25** |
| 8 | pivot_break_retest_both_AVAX | 12 | 0.61 | +5.83% | −17.4% | −0.01 |
| 9 | inside_bar_break_long_ETH | 114 | 0.56 | +11.11% | −41.7% | 0.33 |
| 10 | inside_bar_break_long_BTC | 114 | 0.56 | +11.30% | −45.6% | 0.28 |

### Promotion-grade candidates (Sh≥0.8, n≥30, |ρ_proxy|≤0.30)

| Signal | n | Sharpe | CAGR | MDD | ρ_proxy |
|---|---:|---:|---:|---:|---:|
| **inside_bar_break_both_ETH** | 141 | 1.29 | +40.17% | −34.2% | 0.17 |
| **inside_bar_break_both_BTC** | 132 | 1.00 | +28.40% | −44.3% | 0.11 |
| **inside_bar_break_long_SOL** | 107 | 1.00 | +25.44% | −37.8% | 0.21 |

### Interesting near-promo (negative correlation = real diversifier)

`inside_bar_break_short_ETH` (ρ=−0.26, Sh 0.73) and
`inside_bar_break_short_AVAX` (ρ=−0.25, Sh 0.65) are *anti-correlated* with the
V52 proxy. Even at sub-0.8 Sharpe, a negatively-correlated stream is
disproportionately valuable in a portfolio context (it hedges DD windows).

---

## 3. What worked / what didn't

### ✅ Inside-bar break is the winner
- Plain mother-bar / inside-bar / break-of-mother — the Al Brooks classic.
- Fires often (n=107–152 per coin over ~3y) — enough samples for a stable Sharpe estimate.
- 5/5 coins produce ≥30 trades on long+short combined; promo-grade on 3/5.

### ❌ Pivot-break variants underperform
- `pivot_break` and `pivot_break_retest` produce only 7–23 trades per coin.
- The 8-bar quiet-range filter is too restrictive on 4h crypto — most breakouts
  happen out of choppy ranges, not clean consolidations.
- Future tweak: relax `quiet_atr_mult` from 1.5 → 2.5, drop the retest filter on
  4h (works better on lower TFs).

### ⚠️ MDDs are too wide
The promo candidates have MDDs of **−34 to −44%** — far worse than V52's
**−5.8%**. Mechanism: inside-bar breaks fire often, including into multi-leg
trends; canonical EXIT_4H (tp=10·ATR, trail=6·ATR) holds losers too long
during continuation moves that fail.

**Implication:** these signals are NOT standalone-deployable as-is. They need
V41-style regime-adaptive exits before sleeve-grade.

---

## 4. Caveats

- V52 reference equity isn't materialized in the audit JSON — proxy via
  CCI_ETH is a tight upper bound but not the full thing. To tighten:
  rebuild V52 equity via `run_v52_hl_gates.py::build_v52_hl()` and re-correlate.
- Window is 5181 bars (~3y). For a clean signal family, the 10-gate battery
  needs ≥4 positive years. Will need to verify on Binance long history.
- Correlation is computed on per-bar equity returns (not trade-level), which
  understates correlation between sparse signals. Trade-level joint analysis
  recommended before committing to a portfolio weight.

---

## 5. Files

- `strategy_lab/strategies/v54_priceaction.py` — signal definitions
- `strategy_lab/run_v54_priceaction.py` — scan harness
- `docs/research/phase5_results/v54_priceaction_scan.json` — full numbers

---

## 6. Recommended next steps

**Immediate:**
1. **Tighten exits.** Pair top-3 candidates with V41 regime-adaptive exits
   (the existing `simulate_adaptive_exit`) to compress MDD from −40% toward
   −15%. Hypothesis: inside-bar breaks profit-take fast in HighVol, run in
   LowVol — exactly what V41 does.
2. **Use the new directional regime classifier** as well — Bull regime →
   keep long inside-bar entries, scale up; Bear → flip to favor short side.
3. **Refit on Binance 5y** for full historical robustness check.

**If MDD compresses below −15%:**
4. Run the full 10-gate battery (`run_v52_hl_gates.py` template).
5. Build V55 = V52 + 10% inside-bar layer (BTC + ETH + SOL, weighted invvol).

**If MDD remains > −20% even with V41 exits:**
6. Don't deploy. Mark as "anti-knowledge §7 — pure price-action is too noisy
   on 4h crypto for standalone use; needs heavier filter or daily TF."

---

**Headline:** Three pure-price-action sleeves cleared the diversification bar
(Sh ≥ 1.0, ρ_proxy ≤ 0.21). MDDs are too wide for direct deployment — the
correct next move is to pair them with V41 adaptive exits before claiming a
finished sleeve. The negative-correlation short-side variants
(inside_bar_break_short_ETH/AVAX) are also worth investigating as
DD-hedge sleeves.
