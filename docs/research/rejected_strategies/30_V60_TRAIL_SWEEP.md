# Study 30 — V60: Trail-Tighten Sweep on V52's Own Sleeves

**Status:** **Cleanly negative result.** The trail-tighten lesson from V58
does NOT generalize from inside-bar breaks to V52's mean-reversion sleeves.
**V52 stays at trail_mult=1.0.** Pivot to Vector 3 (pairs).

**Date:** 2026-04-26

---

## Hypothesis tested

V58 found that trail × 0.65 compressed MDD on inside-bar break sleeves
(BTC sleeve MDD: −29% → −22%). Hypothesis: same lever applied uniformly
across V52's own sleeves (CCI/STF/LATBB/MFI/VP/SVD) compresses V52's MDD
enough that the bootstrap Calmar lower-CI crosses 1.0 (the binding gate).

---

## Results — uniform monotone degradation

| trail_mult | Sharpe | CAGR | MDD | Calmar | Sh_lci | **Cal_lci** | gates 1-6 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| **1.00 (V52)** | **2.52** | **+31.5%** | **−5.80%** | **5.42** | **1.108** | **0.987** | 5/6 |
| 0.85 | 2.30 | +28.6% | −6.29% | 4.55 | 0.923 | 0.701 | 5/6 |
| 0.75 | 2.18 | +26.2% | −6.78% | 3.86 | 0.768 | 0.598 | 5/6 |
| 0.65 | 1.98 | +22.3% | −6.80% | 3.27 | 0.654 | 0.547 | 5/6 |
| 0.50 | 0.99 | +8.9% | −8.59% | 1.04 | −0.414 | −0.240 | 2/6 |

**Every metric monotonically worsens with tighter trail.** Calmar lower-CI
goes from 0.987 → 0.547 by trail_mult=0.65, completely opposite to the
hypothesis.

---

## Why the V58 lesson didn't transfer (the durable insight)

V58 (inside-bar break) is a **breakout-style** signal:
- Entry: close breaks recent extreme of a contracted range
- Move profile: initial follow-through that often fails into chop
- Tightening trail BANKS early winners before the chop kills them
- Wide trail = giveback on every failed breakout → MDD widens
- → Trail-tighten = MDD compression. ✓

V52's sleeves (CCI, STF, LATBB_fade, MFI, VP, SVD) are mostly
**mean-reversion** signals:
- Entry: oversold/extreme reading expecting reversion
- Move profile: slow grind back toward mean over many bars
- Tightening trail CUTS reversion winners before the bounce plays out
- Wide trail = winner runs to TP cleanly → CAGR captured
- → Trail-tighten = lost winners. ✗

**New durable anti-knowledge:** *"tighten the trail" is a breakout-strategy
lever, NOT a mean-reversion lever.* These are mechanistically opposite trade
shapes, and a single trail-multiplier sweep is the wrong tool to apply
uniformly. Each entry family needs its own exit calibration (this is the
same lesson V41 → V58 already taught us about V41 exits not generalizing
to IBB).

This makes the V41 architecture (regime-conditional exits per signal family)
even more important — there is no universal "right" trail.

---

## Implications for V52 ceiling

V52's bootstrap Calmar lower-CI of **0.987** is now confirmed as a
*structural* ceiling, not an artifact:
- Cannot be lifted by adding low-correlation directional sleeves (V58 → 0.974)
- Cannot be lifted by tightening trails (V60 → 0.547–0.701)
- Almost certainly cannot be lifted by tightening SLs (V58 sleeve-level data
  showed SL × 0.75 widens MDD by 23pp on the BTC sleeve)

The remaining levers are:
1. **Add structurally different streams** (pairs, funding) — they don't share
   V52's directional fat tails, so they should genuinely cap blend MDD.
2. **More years of data** — bootstrap CI is partly a sample-size artifact.
   When we have 4-5 years of HL data instead of 2.3, the CI may naturally
   tighten above 1.0 with no strategy change.
3. **Live data + paper-trading evidence** — gives forward, non-bootstrap
   confidence. V52 is already deploying for this.

---

## Recommended next vectors

1. **V61 — Vector 3 (pairs/spread)**: build ETH/BTC ratio z-score and
   SOL/AVAX ratio z-score signals. Dollar-neutral by construction → near-zero
   correlation with V52, and pairs cap MDD via mean-reversion. This is the
   structurally correct path past the 0.987 ceiling.
2. **V62 — Vector 4 (funding-rate signals)**: HL funding spikes as fade
   signals. Untouched data, structurally different from price-action.
3. **Skip more V52-tweaking**: 4 studies (V58, V59, V60) now confirm V52 is
   at a local optimum within its own signal family.

---

## Files

- `strategy_lab/run_v60_v52_tighter_trail.py` — sweep harness
- `docs/research/phase5_results/v60_trail_sweep.json` — full numbers

**Headline:** Tight-trail is a breakout lever, not a mean-reversion lever.
Trail × 0.65 collapses V52 Sharpe by 0.54 and Calmar by 2.15. **V52 keeps
trail = 6.0.** Stop modifying V52 within its own family; pivot to pairs
(V61) for the next genuine improvement opportunity.
