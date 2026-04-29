# Study 28 — V58: Tightened-Exit IBB Blend

**Status:** **2/12 blend variants PASS the strict promotion gate.**
Improvement is small but real on all three metrics simultaneously.

**Date:** 2026-04-26

---

## Headline result

**Best blend:** `tightTrail_92_08invvol` (V58 champion candidate)
- 0.92 · V52 + 0.08 · invvol-blend(IBB sleeves with trail × 0.65)
- **Sharpe 2.55 (+0.03)  MDD −5.48% (+0.32pp)  Calmar 5.59 (+0.18)**

| Recipe | Sharpe | MDD | Calmar | vs V52 |
|---|---:|---:|---:|---|
| V52 baseline | 2.52 | −5.80% | 5.42 | — |
| `tightTrail_92_08invvol` | **2.55** | **−5.48%** | **5.59** | **PROMO** |
| `tightTrail_90_10invvol` | 2.55 | −5.55% | 5.49 | PROMO |
| `baseline_92_08invvol` (V56) | 2.62 | −5.81% | 5.41 | no (Calmar barely below) |

---

## Surprising sleeve-level findings

| Sleeve / Variant | Sharpe | MDD | Calmar |
|---|---:|---:|---:|
| BTC_Dstacked **baseline** | 1.13 | −28.9% | 1.12 |
| BTC_Dstacked **tightSL** (SL × 0.75) | 0.59 | **−52.0%** ↑ | 0.27 |
| BTC_Dstacked **tightTrail** (trail × 0.65) | 0.98 | **−21.7%** ↓ | **1.21** |
| BTC_Dstacked **tightBoth** | 0.54 | −46.7% | 0.26 |

**Key counter-intuitive result: tight SL HURTS, tight TRAIL HELPS.**

- **Tight SL** stops out reversion trades that would have recovered → MDD
  *increases* (-29% → −52%) because losers compound and winners are missing.
- **Tight TRAIL** banks profits earlier on winners while leaving SL room for
  recovery → MDD compresses (-29% → −22%) and Calmar rises 8%.

**New anti-knowledge:** for inside-bar breaks specifically, *trail-tightening is
the right risk lever*, not SL-tightening. Don't generalize "tighten exits" → must
specify which exit mechanism.

---

## Why the blend lift is small

The 92/08 invvol recipe gives only **8% weight to IBB**, so the MDD/Calmar
improvements come mostly from V52 with a slight smoothing nudge. The Sharpe lift
shrinks from V56's +0.13 (5% each) to +0.03 here because:

1. Smaller IBB weight → smaller contribution to portfolio
2. tightTrail sleeves have *lower* CAGR than baseline (banked too early on big winners)
3. Net: smoother but lower-return contribution → Sharpe lifts less

The win is that MDD now actually *improves* vs V52 (+0.32pp). At 92/08 the IBB
sleeves act as a small DD-shock absorber rather than a return enhancer.

---

## Honest caveat

Calmar improvement is +0.18 (~3%). This is well within bootstrap CI noise — a
+0.18 Calmar lift could easily be sample-size variance. **Run the 10-gate
battery before declaring this V58 the new champion.**

The interesting durable finding is the **tight-trail-helps / tight-SL-hurts**
asymmetry, which is robust across all 3 sleeves.

---

## Recommended next steps

1. **V59 — 10-gate battery** on `tightTrail_92_08invvol` blend. Specifically:
   - Bootstrap Calmar lower-CI must beat V52's 1.10 (or be statistically
     indistinguishable upward).
   - Walk-forward efficiency
   - Permutation null
2. **V60 — Pivot to Vector 3 (pairs/spread strategies)** — if the IBB lift is
   noise, the blending capacity is saturated and we need *structurally
   different* signal sources (pairs are dollar-neutral by construction →
   guaranteed near-zero correlation with directional V52).
3. **Apply the trail-tighten lesson to V52's own sleeves**: do CCI/ST/MFI
   sleeves benefit from trail × 0.7? Cheap to test.

---

## Files

- `strategy_lab/run_v58_priceaction_blend_tight.py` — variant scan harness
- `docs/research/phase5_results/v58_blend_tight.json` — raw numbers

**Headline:** Tight-trail (not tight-SL) IBB blend at 92/08 invvol marginally
beats V52 on all three metrics (Sh +0.03 / MDD +0.32pp / Calmar +0.18). Lift is
small enough to need 10-gate battery validation before adoption.
