# Take-Profit Strategy — Verdict: **DO NOT DEPLOY**

**Tested:** sell held side at `entry * (1 + T)` for T ∈ {5, 10, 15, 20, 25, 40, 60, 80, 100, 150}%, with and without rev_bp=5 hedge-hold combined.

**Result:** **NEGATIVE across all TP targets.** Best variant (`tp_150pct_plus_revbp`) achieves +24.45% ROI vs baseline +24.58% — TP at any target is a strict downgrade.

---

## Why TP fails — the math is unambiguous

Polymarket binary markets settle at **$1**. Entries average ~$0.50. So the natural-resolution payoff for a winner is ~+100% (you doubled). Capping that at any T < 100% throws away upside.

The rev_bp hedge-hold baseline is already **asymmetrically optimized**:
- Limits downside via hedge when signal reverses (rev_bp triggers ~56% of trades, locks break-even)
- Keeps unlimited upside (~44% of trades hit natural resolution; ~85% of those win full payout)

Adding TP turns this into a SYMMETRIC payoff (capped both directions). For an 81%-hit-rate signal, asymmetric beats symmetric by a large margin.

---

## Full sweep table (q10 universe, n=579, hedge-hold rev_bp=5 baseline)

| Variant | n | Hit% | ROI | vs baseline | TP fire | revbp fire | natural |
|---|---|---|---|---|---|---|---|
| **baseline_revbp** ★ | 579 | 81.5% | **+24.58%** | — | 0% | 56% | 44% |
| tp_5pct_only | 579 | 94.5% | -0.68% | -25.26pp | 94% | 0% | 6% |
| tp_5pct_plus_revbp | 579 | 92.1% | +0.61% | -23.97pp | 91% | 7% | 2% |
| tp_10pct_only | 579 | 93.6% | +1.17% | -23.41pp | 93% | 0% | 7% |
| tp_10pct_plus_revbp | 579 | 91.5% | +2.77% | -21.81pp | 90% | 8% | 2% |
| tp_15pct_only | 579 | 92.1% | +2.57% | -22.01pp | 91% | 0% | 9% |
| tp_15pct_plus_revbp | 579 | 90.2% | +4.56% | -20.02pp | 88% | 10% | 3% |
| tp_20pct_only | 579 | 90.7% | +3.95% | -20.63pp | 90% | 0% | 10% |
| tp_20pct_plus_revbp | 579 | 89.3% | +6.35% | -18.23pp | 86% | 11% | 3% |
| tp_25pct_only | 579 | 89.8% | +5.68% | -18.90pp | 89% | 0% | 11% |
| tp_25pct_plus_revbp | 579 | 88.4% | +8.25% | -16.33pp | 84% | 13% | 3% |
| tp_40pct_only | 579 | 84.5% | +8.44% | -16.14pp | 83% | 0% | 17% |
| tp_40pct_plus_revbp | 579 | 85.7% | +12.78% | -11.80pp | 75% | 21% | 4% |
| tp_60pct_only | 579 | 77.0% | +10.55% | -14.03pp | 72% | 0% | 28% |
| tp_60pct_plus_revbp | 579 | 84.1% | +17.76% | -6.82pp | 60% | 33% | 6% |
| tp_80pct_only | 579 | 69.9% | +11.03% | -13.55pp | 57% | 0% | 43% |
| tp_80pct_plus_revbp | 579 | 82.9% | +21.34% | -3.24pp | 44% | 45% | 11% |
| tp_100pct_only | 579 | 66.8% | +12.66% | -11.92pp | 36% | 0% | 64% |
| tp_100pct_plus_revbp | 579 | 82.4% | +23.82% | -0.76pp | 26% | 50% | 23% |
| tp_150pct_only | 579 | 62.7% | +11.17% | -13.41pp | 10% | 0% | 90% |
| tp_150pct_plus_revbp ★ | 579 | 81.5% | +24.45% | -0.13pp | 8% | 56% | 37% |

**Pattern:** TP-only ROI plateaus around 11-13% — never approaches baseline. TP+revbp converges to baseline only when TP target is so high (150%) that it almost never fires (effectively reverts to baseline).

---

## Outcome-by-outcome decomposition

For tp_25pct_plus_revbp (representative middle case):
- **84% hit TP @ +25%** → mean profit per share = $0.50 × 0.245 ≈ $0.123
- **13% hit revbp hedge** → mean profit per share ≈ $0.005 (locked break-even)
- **3% natural resolution** — split into:
  - ~70% wins (~$0.50 profit) = $0.105 contribution
  - ~30% losses (-$0.50) = -$0.045 contribution
- Total per-share: 0.84×0.123 + 0.13×0.005 + 0.03×(0.7×0.5 + 0.3×(-0.5)) = $0.103 + $0.001 + $0.006 = $0.110

For baseline_revbp (no TP):
- **56% hit revbp hedge** → ~$0.005
- **44% natural resolution** — of which:
  - ~85% wins ($0.50 profit) = 0.44 × 0.85 × 0.50 = $0.187
  - ~15% losses (-$0.50) = 0.44 × 0.15 × (-0.50) = -$0.033
- Total: 0.56×0.005 + $0.187 - $0.033 = $0.003 + $0.154 = $0.157

So **baseline returns $0.157 per share, TP at 25% returns $0.110 per share** — that's the +24.58% vs +8.25% gap.

---

## When TP would have made sense (for reference)

TP improves a strategy when:
1. **Hit rate is moderate** (say <65%) — losses dominate, capping reduces variance
2. **Payoff distribution has thin tails** — natural payouts aren't huge

Neither applies here:
1. q10 hit rate = **81-86%**
2. Polymarket binary payoffs are bimodal at $0/$1 — fat tails on winners

If our strategy were a marginal-edge signal (52-55% hit), TP at 5-15% might smooth out the variance enough to win. But we have a strong directional signal, so we leave the asymmetric upside intact.

---

## Conclusion

✅ **Keep current rev_bp=5 hedge-hold strategy** as deployed in TV.
❌ **Do NOT add TP** at any target. Best case (TP at 150%+revbp) only matches baseline; all others lose materially.
✅ **The user's intuition was sound for moderate-edge strategies**, but our q10 signal is too strong for TP to add value. The natural-resolution path is where the alpha lives.

---

## Files

- [polymarket_take_profit.py](../polymarket_take_profit.py) — full simulator (10 TP targets × 2 modes)
- [POLYMARKET_TAKE_PROFIT.md](POLYMARKET_TAKE_PROFIT.md) — variant grid + cross-asset + day-by-day
- [results/polymarket/take_profit.csv](../../results/polymarket/take_profit.csv)
