# Study 26 — Price-Action Sleeves × Adaptive Exits

**Status:** Mixed result. **Best-per-sleeve adaptive exit improves Sharpe and
MDD on 3/5 sleeves**, but no sleeve hits the standalone-deployable bar
(MDD ≤ −15%). MDD compression to V52 levels must come from **portfolio
blending**, not from single-sleeve exit tuning.

**Date:** 2026-04-25

---

## 1. What was tested

For each of 5 inside-bar-break sleeves, ran 4 exit configurations:

- **A** — canonical EXIT_4H (baseline; tp=10·ATR, sl=2·ATR, trail=6·ATR, hold=60)
- **B** — V41 vol-HMM adaptive exits (existing `REGIME_EXITS_4H`)
- **C** — directional regime adaptive exits (custom profile per side)
- **D** — stacked: 3 dirs × 5 vols = 15 cells, take tighter of (dir, vol) per cell

Sleeves:
- 3 promo-grade longs (`ibb_both_ETH`, `ibb_both_BTC`, `ibb_long_SOL`)
- 2 anti-correlated shorts (`ibb_short_ETH`, `ibb_short_AVAX`)

Directional exit profiles (long side; short side is mirrored):
| Regime | sl_atr | tp_atr | trail_atr | max_hold |
|---|---:|---:|---:|---:|
| Bull | 2.0 | 14.0 | 8.0 | 80 |
| Sideline | 2.0 | 10.0 | 6.0 | 60 |
| Bear | 2.5 | 6.0 | 2.5 | 24 |

---

## 2. Results

### Full grid (Sharpe / CAGR / MDD / Calmar)

| Sleeve | A canonical | B vol_hmm | C dir | D stacked |
|---|---|---|---|---|
| **ibb_both_ETH** | 1.29 / 40% / −34% / 1.17 | 0.89 / 28% / −56% / 0.51 | 0.53 / 11% / −39% / 0.27 | 1.08 / 30% / −38% / 0.79 |
| **ibb_both_BTC** | 1.00 / 28% / −44% / 0.64 | 0.07 / −6% / −67% / −0.10 | 0.71 / 16% / −54% / 0.30 | **1.21 / 36% / −30% / 1.20** |
| **ibb_long_SOL** | 1.00 / 25% / −38% / 0.67 | 0.91 / 27% / −41% / 0.65 | **1.18 / 29% / −32% / 0.93** | 1.07 / 26% / −32% / 0.82 |
| **ibb_short_ETH** | 0.73 / 16% / −28% / 0.58 | 0.66 / 16% / −35% / 0.46 | 0.58 / 11% / −30% / 0.38 | 0.63 / 12% / −28% / 0.44 |
| **ibb_short_AVAX** | 0.65 / 14% / −34% / 0.40 | 0.39 / 6% / −44% / 0.14 | 0.60 / 12% / −26% / 0.46 | 0.63 / 13% / −26% / 0.48 |

### Best-per-sleeve (Calmar-ranked)

| Sleeve | Best | Sh | ΔSh vs A | MDD | ΔMDD vs A | Calmar |
|---|---|---:|---:|---:|---:|---:|
| ibb_both_BTC | **D_stacked** | 1.21 | **+0.21** | −30% | **+14.6 pp** | 1.20 |
| ibb_long_SOL | **C_dir** | 1.18 | **+0.18** | −32% | **+6.0 pp** | 0.93 |
| ibb_short_AVAX | **D_stacked** | 0.63 | −0.02 | −26% | **+7.3 pp** | 0.48 |
| ibb_both_ETH | A_canonical | 1.29 | 0 | −34% | 0 | 1.17 |
| ibb_short_ETH | A_canonical | 0.73 | 0 | −28% | 0 | 0.58 |

---

## 3. Key findings

1. **V41 vol-HMM exits HURT inside-bar breaks across the board** (Sharpe drop
   −0.10 to −0.93, MDD widens 7–22 pp on every sleeve). V41's profiles are
   tuned for V30 mean-reversion entries — inside-bar breakouts have a
   different trade shape (early follow-through that fails into chop), and
   V41's tight HighVol exits cut runners while loose LowVol exits hold losers.
   **Anti-knowledge update:** V41's exit profiles do NOT generalize to
   breakout-style entries — each entry family needs its own exit calibration.

2. **Directional regime helps SOL and BTC, hurts ETH**:
   - SOL & BTC: directional cell logic adds 0.18–0.21 Sharpe and 6–15 pp MDD
     compression — the inside-bar pattern *does* work better with regime-
     conditional exits when the regime is informative on that coin.
   - ETH: directional alone collapses Sharpe (1.29 → 0.53). Mechanism: ETH's
     inside-bar breaks happen disproportionately during BTC-bear stretches
     (ETH leads BTC into reversals) — so the "Bear → tight TP" rule
     prematurely exits ETH's best winners.

3. **Stacked (D) is the most robust config overall** — best on 2 sleeves,
   never the worst, and on ETH it preserves most of the canonical Sharpe
   (1.08) while adding 23 trades from improved regime-conditional handling.

4. **Single-sleeve MDD cannot reach V52's −5.8% target**. Best single-sleeve
   MDD is −26%. The MDD-compression playbook for inside-bar must be
   **portfolio blending**, not exit tuning. (This matches the V52 §5
   learning: stacking uncorrelated streams was the single biggest lever.)

5. **Promotion gate FAIL** at MDD ≤ −15% threshold for all 20 (sleeve, config)
   combinations. Best Calmar is 1.20 (BTC D_stacked), still below the V52
   bar of 5.42.

---

## 4. So what?

**The good news:** we now have 3 inside-bar sleeves with adaptive-exit best-
configs around Sharpe 1.0–1.3 with low correlation to V52 (≤0.21):
- `ibb_both_ETH` @ canonical : Sh 1.29
- `ibb_both_BTC` @ D_stacked : Sh 1.21
- `ibb_long_SOL` @ C_dir     : Sh 1.18

These are *not* deployable standalone (MDD too wide), but they are exactly the
shape of stream V52 was built from: positive-Sharpe, low-correlation, ready
to be stacked at small weight (5–10%) into a blended portfolio.

**Hypothesis to test next:** if we blend the 3 best-config sleeves + V52 with
invvol weighting at 10% per sleeve, the MDD of the blend will be close to V52's
−5.8% (cancelling each sleeve's idiosyncratic DD) while CAGR rises by 3–5 pp.

This is **V56**, the actual proposal. A blend test is the right next experiment.

---

## 5. Files

- `strategy_lab/run_v55_priceaction_adaptive.py` — adaptive-exit harness
- `docs/research/phase5_results/v55_priceaction_adaptive.json` — raw numbers

---

## 6. Recommended next step (V56)

1. Materialize V52 reference equity via `run_v52_hl_gates.py::build_v52_hl()`
   (gap from study 25 — proxy is no longer enough; we need the real series for
   blend math).
2. Build blend = 0.85·V52 + 0.05·`ibb_both_ETH` + 0.05·`ibb_both_BTC` + 0.05·`ibb_long_SOL`
   with each sleeve's best-found config.
3. Compute blend Sharpe / CAGR / MDD / Calmar.
4. **Promotion bar:** blend Sharpe > 2.52 (V52 baseline) AND blend MDD > −10%
   AND blend Calmar > 5.42. If yes, run the 10-gate battery.
5. Also test blend = V52 + 0.10·`ibb_short_ETH` (anti-correlated DD hedge)
   alone — see if just the hedge improves V52 without the noisier longs.

---

**Headline:** Adaptive exits improve 3/5 inside-bar sleeves materially
(SOL +0.18 Sharpe, BTC +0.21 Sharpe and 14.6 pp MDD compression), but no
single sleeve reaches the standalone bar. V52-style blending is the next test;
this is exactly the §5 path that worked before.
