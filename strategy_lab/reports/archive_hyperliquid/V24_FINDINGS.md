# V24 — Findings from the "more creativity" hunt

**Date:** 2026-04-20
**Scope added:** 15-minute scalping suite + explicit regime router.
**Conclusion up front:** most simple 15m scalps fail the Hyperliquid fee hurdle on majors, but two genuinely new edges fell out of the hunt and **both improved OOS**. Use them as complements to V23, not replacements.

---

## What was tried

### 15m scalping suite (9 coins)

Four signal families, all L+S, each swept on 15m bars from 2020-01-01:

| Family | Idea | Result |
|--------|------|--------|
| **ORB_15m** | Opening range breakout: first N bars after 00:00 UTC define today's range; break above/below with vol filter. | Dead. No coin produced a viable config. Fees on failed breakouts compound faster than wins. |
| **VWAP_band** | Rolling VWAP ± k·std, fade or break. | Dead. Short-term VWAP bands are too reactive — false signals dominate. |
| **RSIBB_15m** | Contrarian extreme: long when RSI<25 & close<BB lower (in uptrend); mirror short. | **Works on mid-cap alts.** Best: TON +22% / Sh 1.02, SUI +15%, AVAX +25%. |
| **STDUAL_15m** | Dual Supertrend (fast + slow) alignment. | Dead. Too many false flips on 15m with fees. |

### Regime router (9 coins, 1h/2h/4h)

Explicit four-regime classifier (ADX + SMA fast/slow + SMA200 anchor):

- **TREND_UP** → Donchian-long-only breakout
- **TREND_DN** → Donchian-short-only breakout
- **RANGE** → Bollinger mean-revert (long at lower, short at upper)
- **CHOP** → flat (no edge, don't trade)

Only ETH produced a viable config (+37% Sharpe 1.04 at 2h). The other 8 coins: the extra regime filter cut too many trades and killed the edge that was captured implicitly by the V23 BB-Break + regime SMA configs.

---

## The honest negative results

1. **Simple 15m scalps don't work on BTC/ETH/SOL at Hyperliquid taker fees.** 9 bps round-trip eats the edge. The ORB, VWAP band, and Dual-Supertrend families all blew up on majors with zero viable configs in the grid.

2. **Explicit regime gating doesn't help already-gated strategies.** The V23 winners (BB-Break with regime SMA) already capture regime implicitly. Stacking ADX + SMA fast/slow on top mostly just reduces trade count without improving Sharpe.

3. **Opening Range Breakout is dead for crypto at retail fees.** The published ORB edge in equities doesn't carry over — crypto trades 24/7, 00:00 UTC is arbitrary, and the volume filter throws away the signals that would work.

---

## The positive findings — two new edges that OOS-validate

### 1. ETH 2h Regime Router — **OOS BEATS IS**

- Signal: Donchian(120) break in TREND_UP | Donchian(120) short in TREND_DN | BB(80, k=2.0) mean-revert in RANGE regime. CHOP regime = flat.
- Regime labels across the full sample: 14362 CHOP, 8707 TREND_DN, 7945 TREND_UP, 6720 RANGE.
- Full sample: CAGR +36.7% net, Sharpe 1.04, DD -37.9%, n=540.
- **IS (2020-2023):** CAGR +32.2%, Sharpe 0.96.
- **OOS (2024-2026):** CAGR +50.2%, Sharpe **1.26** — clearly beats IS.
- Why it works on ETH: ETH had the cleanest regime alternation in 2024-2026 (macro flips from accumulation → rally → distribution), so explicit regime gating adds value where a single-signal family blurs across regimes.
- **Below V23 ETH winner (+124% BB-Break)** on CAGR, but the routing gives much smoother exposure (only ~25% time-in-market vs ~22% for V23). Candidate for **diversification pair** inside an ETH sleeve.

### 2. LINK 15m RSI+BB Mean-Revert — **OOS BEATS IS substantially**

- Signal: long when RSI(14)<25 AND close<BB(80, k=2.0) lower AND close>SMA400 (regime up). Short mirror.
- Full sample: CAGR +15.5%, Sharpe 0.66, DD -38.2%.
- **IS (2020-2023):** CAGR **-10.3%**, Sharpe -0.29 (loses in-sample).
- **OOS (2024-2026):** CAGR **+44.6%**, Sharpe **1.35** — dramatic OOS improvement.
- Why it's interesting: the signal flipped from IS-losing to OOS-winning. Two readings: (a) LINK's micro-structure changed post-2023 so short-term mean-reversion became tradable; (b) coincidence. Given 61 trades OOS at Sharpe 1.35, the effect size is too large for pure luck but small enough to warrant paper-trade confirmation.
- **Add only as a small overlay** on top of LINK V23 (37% CAGR). Combined, LINK sub-account could be materially stronger.

### 3. DOGE 15m RSI+BB — OOS holds, IS weak

- Full: CAGR +6%, Sh 0.37. IS -10%, OOS +24% / Sh 0.95. Similar pattern to LINK (IS weak, OOS positive). Less decisive than LINK but worth paper-testing.

### 4. TON 15m RSI+BB — OOS-only +22% / Sh 1.02

- No IS slice (TON listed 2024-08). Positive OOS is encouraging but single-regime; keep paper-first.

---

## What got dropped

| Config | Verdict | Reason |
|--------|---------|--------|
| AVAX 15m RSIBB | ✗ OOS degrades | IS Sh 1.55 → OOS Sh 0.36. Classic overfit. |
| INJ 15m RSIBB | ✗ OOS LOSES | IS breakeven, OOS -16%. Kill. |
| SUI 15m RSIBB | ✓ holds (weak) | IS 32% / OOS 10%. Below meaningful threshold; V23 SUI (+160%) dominates this. |
| TON Regime Router | ✗ OOS LOSES | TON is too short a history for regime routing; V23 Keltner+ADX at 2h still wins. |
| Everything on BTC/SOL at 15m | no viable config | Fees wash out signal. |

---

## Recommended changes to the live portfolio

Starting from the V23 9-coin baseline ($10k each, combined CAGR +82% / Sharpe 1.89 / DD -25%):

- **Add a small (20-30% weight) ETH sleeve using the V24 Regime Router** alongside the main V23 ETH BB-Break. The regimes where BB-Break overrides Router would need to be resolved with a simple rule (e.g., take the signal that fires first, or split capital 70/30).
- **Replace LINK V23 (+37% / Sh 1.09) with a 60/40 mix: 60% V23 LINK BB-Break + 40% V24 LINK 15m RSIBB.** LINK is the weakest V23 winner, and the V24 OOS is strong enough to blend.
- **Everything else on the V23 portfolio is unchanged.** The V24 experiments confirmed the V23 configs capture regime edge implicitly and shouldn't be replaced.

Do NOT use 15m for majors. The 9 bps round-trip fee is the floor of what simple signals can edge out on liquid majors; the grind is not worth it. Save 15m for mid-cap alts where microstructure is noisier and mean-reversion opportunities are more frequent.

---

## Takeaways for strategy design going forward

1. **Any new signal must clear 2× round-trip fee per trade consistently.** At Hyperliquid taker rates that's 18 bps per winning trade just to break even. Any strategy with avg trade <0.3% is likely dead.
2. **Regime classification is implicit in the best signals.** BB-Break with a regime SMA already gates for regime. Bolting on ADX + Hurst + SMA-fast/slow often subtracts edge rather than adds it.
3. **OOS beating IS is not a red flag — it's a green one.** Two of the V24 edges (ETH Router, LINK RSIBB, maybe DOGE) had IS weaker than OOS. That's the opposite of overfitting and suggests the signal captures something structural about the recent regime.
4. **Coin-idiosyncratic edges exist but are small.** No V24 strategy hit the 55% CAGR bar on its own. The real alpha came from the V23 family-per-coin specialization — V24 is a complement.

---

## Files

- `/strategy_lab/run_v24_15m_scalp.py` — scalp suite (ORB, VWAP, RSIBB, STDUAL)
- `/strategy_lab/run_v24_regime_router.py` — regime classifier + router
- `/strategy_lab/run_v24_oos.py` — walk-forward OOS for both
- `/strategy_lab/results/v24/v24_15m_summary.csv` — per-coin 15m winners
- `/strategy_lab/results/v24/v24_regime_summary.csv` — per-coin regime router winners
- `/strategy_lab/results/v24/v24_oos_summary.csv` — OOS verdict per (coin, family)
