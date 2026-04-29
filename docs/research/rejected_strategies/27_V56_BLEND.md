# Study 27 — V56: V52 + Inside-Bar Blend Test

**Status:** Blend FAILS strict promotion gate. **Sharpe lifts +0.13** but
Calmar regresses by 0.17–0.72 because IBB sleeve MDDs leak through.

**Date:** 2026-04-26

---

## Results

| Config | Sharpe | CAGR | MDD | Calmar |
|---|---:|---:|---:|---:|
| **V52 baseline** | **2.52** | 31.45% | **−5.80%** | **5.42** |
| Blend A (0.85·V52 + 0.05 each IBB) | 2.65 (+0.13) | 31.84% | −6.77% (−0.97pp) | 4.70 (−0.72) |
| Blend B (0.85·V52 + 0.15·invvol(IBB)) | 2.63 (+0.12) | 31.36% | −6.54% (−0.74pp) | 4.80 (−0.62) |
| Blend C (0.90·V52 + 0.10·invvol(IBB)) | 2.63 (+0.11) | 31.41% | −5.99% (−0.19pp) | 5.24 (−0.17) |

**Correlations vs V52:** ρ(BTC)=+0.011, ρ(SOL)=+0.082, ρ(ETH)=+0.211 — all low,
exactly as designed, but **none negative**.

## Sleeve metrics (with funding)

| Sleeve | Sharpe | CAGR | MDD | Calmar |
|---|---:|---:|---:|---:|
| ibb_both_BTC (D_stacked) | 1.13 | 32.3% | −28.9% | 1.12 |
| ibb_long_SOL (C_dir) | 1.01 | 24.1% | −31.9% | 0.76 |
| ibb_both_ETH (canonical) | 1.25 | 38.2% | −34.5% | 1.11 |

## Verdict

**Sharpe lift is real but small (+5%).** Calmar regression is the binding
issue: the IBB sleeves contribute proportional MDD (−29 to −35%) that low
correlation alone (~0.01 to 0.21) doesn't fully cancel.

**0/3 blends pass** the strict gate (Sharpe>2.52 AND MDD>−10% AND Calmar>5.42).

For IBB to beat V52 in a blend, the sleeves need at least one of:
1. Standalone Sharpe ≥ 1.5 each (currently 1.0–1.25)
2. Standalone MDD ≤ −15% each (currently −29 to −35%)
3. Negative correlation with V52 (currently slightly positive)

## Recommended next vectors

1. **V57 — Anti-correlated IBB hedge:** find or construct a single short-side
   IBB sleeve with ρ(V52) < −0.10 (drops bear shorts on alt-L1s during BTC
   bull stretches). If found, even 5% weight should lift Calmar.
2. **V58 — Tighten IBB exit risk:** apply 1.5×ATR SL (vs current 2×) to
   compress sleeve MDD toward −20%; accept lower CAGR. The 90/10 invvol blend
   (Calmar 5.24) is already close to baseline — small MDD compression in the
   sleeves should push it above 5.42.
3. **Skip IBB family** and pivot to **Vector 3 (pairs/spread)** or **Vector 4
   (funding-rate signals)** from `NEW_SESSION_CONTEXT.md` — those are
   structurally more likely to be near-zero-correlated with V52.

## Files
- `strategy_lab/run_v56_priceaction_blend.py` — blend harness
- `docs/research/phase5_results/v56_blend.json` — raw numbers

**Headline:** IBB sleeves are quality (Sh 1.0–1.25, ρ<0.21) but not strong
enough to clear V52's Calmar bar in a blend. Either tighten IBB risk (V58)
or pivot to a structurally orthogonal signal family (V57 hedge / pairs / funding).
