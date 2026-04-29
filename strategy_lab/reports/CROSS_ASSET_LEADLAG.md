# A2 Cross-Asset Lead-Lag — Results

**Date:** 2026-04-29
**Status:** Complete. **Verdict: BTC does NOT lead ETH/SOL on 5m/15m UpDown markets.** Hit rate ≈ 50% when BTC's `ret_5m` is used as the predictive signal.

---

## Method

For each ETH and SOL UpDown market:
1. Compute BTC's `ret_5m` at the SAME `window_start_unix` (using BTC 1m closes).
2. Test 3 strategies:
   - **BTC-leader**: `signal = sign(BTC_ret_5m)`. Pure cross-asset prediction.
   - **own-ret5m** (baseline): `signal = sign(alt_ret_5m)`. The existing sig_ret5m.
   - **BTC-AND-own-agree**: only fire when BTC and alt point the same way.
3. Stratify by magnitude (all / q20 / q10) of `BTC_ret_5m`.

PnL: $25 buy at `entry_yes_ask` if up, `entry_no_ask` if down. 2% fee on profit. Held to resolution.

---

## Result

| Strategy | tf | mag | ETH ROI | ETH hit | SOL ROI | SOL hit |
|---|---|---|---|---|---|---|
| **BTC-leader** | 5m | all | **−3.7%** | 48.7% | **−6.5%** | 48.4% |
| BTC-leader | 5m | q10 | +4.1% | 50.0% | −3.2% | 49.5% |
| BTC-leader | 15m | all | −3.7% | 48.5% | −3.7% | 49.6% |
| BTC-leader | ALL | all | −3.7% | 48.7% | −5.8% | 48.7% |
| **own-ret5m** | 15m | q20 | **+20.6%** | **61.3%** (n=137) | +5.9% | 56.2% |
| own-ret5m | 5m | all | +10.8% | 56.8% (n=2046) | +4.8% | 54.7% |
| own-ret5m | ALL | all | +10.4% | 56.5% (n=2728) | +5.7% | 55.1% |
| **BTC-and-agree** | 15m | q20 | +14.9% | 57.4% (n=94) | +2.3% | 53.5% |
| BTC-and-agree | 5m | q10 | +9.7% | 52.7% (n=146) | +1.4% | 52.2% |

### Key reads

1. **BTC-leader has hit rate ≈ 50% on every cell.** No predictive value when used as the primary signal. The ~5% ROI loss comes from paying the spread on directional bets that have no edge.

2. **Own-ret5m on ETH 15m q20 is the strongest cell across all research so far:** ROI +20.6%, hit 61.3%. This is the existing sig_ret5m sniper q20 — confirmed under cross-asset framework. n=137 is small but consistent with prior backtest results.

3. **Agreement filter (BTC AND own ret_5m same sign) ADDS NOTHING.** It removes ~30% of own-ret5m's sample, leaves smaller-n cells with LOWER ROI. The "confirm with BTC" intuition doesn't survive on 7-day data — the agreement isn't a signal, it's a sample-size cut.

4. **SOL is consistently weaker than ETH** across all strategies. SOL's price is noisier; flow signal (Task 4) had only 48% market coverage vs ETH's 58%.

---

## Why it fails (probable reasons)

The "BTC leads alts on minutes" intuition holds for 1h+ price impacts but **breaks down at 5m/15m**:

1. **Polymarket UpDown markets resolve on the same timestamp as the underlying spot move.** By the time a market at slot_start = T resolves at T+5m, BTC's move at T has already propagated to the alt's spot price (via correlated trading). The alt's own ret_5m captures whatever BTC drove — adding BTC explicitly adds no info.

2. **Retail on Polymarket may already price the cross-asset correlation in real time.** No-ask on ETH UpDown moves with BTC's recent flow before ETH's spot completes its own move.

3. **At small magnitudes (the "all" cell), BTC's ret_5m is dominated by noise** — sign disagrees with alt's spot move ≈ 50% of the time.

This is consistent with the sim-vs-live finding from S1: sim's `ret_5m` and live's `ret_5m` disagree on 50% of bets at small magnitudes. **At small magnitudes, ANY single-asset return-sign predictor is essentially random.** Only large-magnitude signals (q10/q20) carry information.

---

## What it does confirm

1. **`sig_ret5m` sniper q20/q10 is the durable signal.** Confirmed in 4 distinct frameworks now:
   - Tier 1 baseline grid (signal_grid_v2)
   - Forward-walk holdout (forward_walk_v2)
   - V2 stack reference baseline (highest IC)
   - Cross-asset eval (this run)

2. **The existing recalibration recommendation stands**: maker entry + HEDGE_HOLD + spread<2% filter, applied to sniper q10/q20. Per `docs/FINDINGS_2026_04_29.md` and `docs/VPS3_FIX_PLAN.md`.

3. **Cross-asset overlays don't help.** Don't add a "BTC must agree" filter; it's a sample cut, not an alpha.

---

## Decision

**Don't ship cross-asset overlays.** Continue with single-asset sig_ret5m sniper as the deployable cell.

This is the 4th consecutive negative research finding (S2, A1, A2 plus V2 stack kill). The research has now decisively confirmed:

> **The only durable edge in the 7-day Polymarket UpDown sample is sig_ret5m sniper. Every alternative paradigm, overlay, and stack tested has either matched or underperformed it.**

That's a strong claim about the limit of what 7 days can show us. Next steps should focus on accumulating more data (B-tier roadmap items unlock at 30+ days) rather than testing more 7-day variants.

Suggesting we pivot from research-mode to deployment-mode and let VPS3 collect more data while sniper q10 ships.
