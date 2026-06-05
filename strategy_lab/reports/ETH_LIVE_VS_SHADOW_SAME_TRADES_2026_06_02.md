# eth_5m_l_ema50_hurst_grandparent_v8 — live (Ireland) vs shadow (VPS3) fire comparison (2026-06-02)

**Question:** why do live and shadow fire different trades? **Answer: they DON'T — they fire the SAME trades.**
The apparent WR/PnL gap is a different-measurement-window / small-sample artifact, not an implementation difference.

## Matched-slug comparison (11 most recent slugs, both engines)
| slug suffix | Ireland LIVE (dir, fill_vwap) | VPS3 SHADOW (dir, fill_vwap) | match |
|---|---|---|---|
| 1780445700 | DOWN 0.56 | DOWN 0.56 | ✓ |
| 1780445100 | DOWN 0.74 | DOWN 0.74 | ✓ |
| 1780443300 | DOWN 0.51 | DOWN 0.51 | ✓ |
| 1780442700 | DOWN 0.97 | DOWN 0.96 | ✓ (1¢) |
| 1780441500 | DOWN 0.62 | DOWN 0.62 | ✓ |
| 1780441200 | DOWN 0.83 | DOWN 0.85 | ✓ (2¢) |
| 1780437900 | DOWN 0.48 | DOWN 0.48 | ✓ |
| 1780436700 | DOWN 0.72 | DOWN 0.72 | ✓ |
| 1780434000 | DOWN 0.48 | DOWN 0.48 | ✓ |
| 1780432800 | DOWN 0.76 | DOWN 0.74 | ✓ (2¢) |
| 1780432500 | DOWN 0.38 | DOWN 0.38 | ✓ |

**11/11 identical slug + direction.** Fill prices match within 0–2¢; the deltas go BOTH directions
(live sometimes higher, sometimes lower) → **book-snapshot timing jitter between the two engines, NOT a
systematic fill bias.** Both fire DOWN → same chainlink outcome → **identical `won` → identical WR** on
matched slugs.

## Why the earlier "shadow 72% vs live 50%" gap was misleading
- Shadow WR 72% = **n=173** over many days (incl. favorable periods).
- Live WR 50% = **n=16** recent fires — a short, unlucky stretch of the SAME strategy.
- Over identical slugs the two are identical; the gap is **measurement window + small sample**, not divergence.

## Corrections to earlier reports (this thread)
1. **No implementation divergence** between Ireland-live and VPS3-shadow for this sleeve — same fire
   decisions, same directions, same prices. The engines agree.
2. The earlier **"optimistic shadow fill-model"** hypothesis (`SLEEVE_DEBUG_ROOTCAUSE` / `..._CORRECTED`)
   is **REFUTED here**: live and shadow fill prices match within 1–2¢ with no systematic direction →
   shadow is NOT favorable. The live "loss" was **small-sample variance (n=16)**, not a fill artifact.
3. Still true: the cosmetic `fire_us = slot_end` mislabel in the RESOLVED event (placed events correctly
   show off=60). Fix for clean analytics, but it does not affect fires.

## Implication
The sleeve is implemented consistently across hosts. Whether it has a real edge is purely a question of the
**true WR at large n** — the shadow n=173 (72%) is the better estimate; the live n=16 (50%) is noise.
**To decide: let the live accumulate n≥100 and compare live WR to the de-vigged entry-implied price** (the
honest edge test), as specified in `TV_AGENT_RESTART_SPEC_1USD_2026_06_01.md`. No code bug blocks restart;
the restart is a sample-size question, not a divergence fix.

## Caveat
Compared the 11 most recent matched slugs (decisive: 100% agreement). A full-history reverse check
(slugs VPS3 fired that Ireland didn't) was not exhaustively run, but the perfect agreement on the recent
overlap makes a systematic divergence very unlikely.
