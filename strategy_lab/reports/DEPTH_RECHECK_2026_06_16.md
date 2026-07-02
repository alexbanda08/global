# Depth Re-check after L25 Odd-Level De-corruption (2026-06-16)

Trigger: canonical L25 has price↔size swapped on all odd-indexed levels (0-based), discovered
2026-06-16 via `_phase2_smoke.py`. Level 0 and all even levels are correct. De-corruption rule:
where `price_col > 1`, swap price and size columns. Applied to all tests below.
Source: `strategy_lab/reports/L25_LEVEL_CORRUPTION_2026_06_16.md`.

---

## 0. CORRECTION (2026-06-16, post-synthesis verification — supersedes the V2 claim below)
The "sumpair_v2 floor was a corruption artifact / −0.70 / do not deploy at any clip" line below is **incomplete and partly wrong.** Verified via a differential (`strategy_lab/directional/_v2_verify_diff.py`, harvest_slug corrected vs `decorrupt=False`):

- **The V2 DEPLOY engine (`_sumpair_signal_oscillation_harvest.harvest_slug`) fills LEVEL-0 only** (entry_fill on `ap[:,0]`, exit on `bp[:,0]`). The de-corruption changes it by **0.000 (max|diff| over 500 slugs)** — level 0 was never corrupted. So **the validated +0.52 floor is NOT a corruption artifact**; it's unchanged.
- **The −0.70 is the REALDEPTH book-walk model** (`_sumpair_v2_upside.py realdepth_fill`, walks 25 levels). On corrupted data it read garbage deep levels and showed +0.52; on corrected data it walks the real book and pays up → −0.70. So the +0.52 that *was* an artifact is the **realdepth one**, not the level-0 deploy one.

**The real takeaway = V2 is FILL-MODEL-FRAGILE, and the corruption masked it:**
- partial-fill-at-best (level-0, the validated model): **+0.52** — but at V2's thin lag-dip fire moments, level-0 is too thin to fill a full $5, so this deploys only small partial size.
- full-$5 book-walk (realistic if the order sweeps): **−0.70**.

Offline cannot decide which is the live reality (it's the fill behaviour at thin moments). **Action: do NOT pull the V2 spec, but do NOT treat +0.52 as confirmed. Keep V2 at $0 shadow (as the spec already says) and let the live shadow measure the REAL fill + PnL — that is exactly the question the shadow exists to answer. No capital until the live wallet shows positive.** Everything else in this report (maker be-first halved, cyclops unchanged, needs-manual list) stands.

## 1. TL;DR

**Materially CHANGED (overturned or quantitatively shifted):**
- **sumpair_v2_upside (oscillation-harvest V2)**: REAL-DEPTH 1-clip OOS flips from +0.52/slug (sig-positive) to **-0.70/slug (CI straddles zero, not deployable)**. The prior "+0.52 floor" cited in the handoff and memory was a corruption artifact. The unlim arm collapses to near-zero (+0.08, wide CI). Do NOT deploy V2 at any clip level on real-depth fill.
- **Maker-opportunity class split**: inside-spread (be-first) fraction HALVED (10.8% -> 5.4%), deep/transient quadrupled (4.9% -> 25.1%), at-level modestly shrunk (84.3% -> 69.5%). Estimated daily inside-spread addressable flow ~$315k -> ~$157k. Racer/speed-moat business case is materially weaker.

**HELD (conclusion unchanged):**
- **cyclops_l25_selector_10hz_dsr**: headline $/tr dips ~14% (thr3/cap0.88: +$0.0143 -> +$0.0123), DSR stays 0.38. All 16 cells still fail DSR < 0.95. Verdict: do not deploy.
- **Deployed scalp** (level-0 logic, $5-25 clips): unaffected — production fill model uses level 0 which was always correct.
- **Scalp capacity numbers** from `SCALP_CAPACITY_PROSPECT_2026_06_13.md`: those are entry-ask walks at small clips that stay within level 0 and low even levels; not materially corrupted. Retain ~$2,875/month OOS prospect, BTC5m ceiling $800.

---

## 2. Full Results Table

| Test | Prior | Corrected | Changed? | Deploy impact |
|---|---|---|---|---|
| sumpair_v2 REAL-DEPTH 1-clip OOS | +0.520 CI[+0.364,+0.676] | **-0.702 CI[-1.394,+0.148]** n=621 | YES — overturned | Do NOT deploy; "deploy signal" was corruption artifact |
| sumpair_v2 REAL-DEPTH unlim OOS | +2.241 CI[+1.223,+3.259] | **+0.080 CI[-2.601,+3.227]** n=621 | YES — overturned | Not sig; multi-clip upside claim gone |
| sumpair_v2 level0 1-clip OOS | (no prior; introduced as sanity check) | +1.651 CI[+0.378,+3.352] n=302 | N/A (new) | Sig-positive BUT this uses non-real-depth fill; not deployable as-is |
| cyclops_l25_selector thr3/cap0.88 | +$0.0143/tr, DSR 0.38 FAIL | **+$0.0123/tr, DSR 0.378 FAIL** n=399 | Minimal (-14% $/tr) | No change: all 16 cells fail DSR; do not deploy |
| cyclops_l25_selector thr5/cap0.88 | +$0.0163/tr FAIL | **+$0.0101/tr FAIL** | Minimal | Same verdict |
| cyclops_l25_selector thr8/cap0.88 | +$0.0156/tr, DSR 0.54 FAIL | **+$0.0121/tr, DSR unchanged FAIL** | Minimal | Same verdict |
| Maker-opp inside-spread (B) fraction | ~10.8% of notional | **~5.4%** (~$157k/day est.) | YES — halved | Racer edge deprioritized further |
| Maker-opp at-level (A) fraction | ~84.3% | **~69.5%** | Moderate shift | Queue-patience path still dominant but share shrinks |
| Maker-opp deep/transient (C) fraction | ~4.9% | **~25.1%** | YES — 5× increase | Most "invisible" fills were corrupted odd-level mis-classification; not real racer opportunity |
| sumpair_v2_depth_realism (2026-06-14) | REAL-DEPTH confirmed +0.638/slug 1-clip, +2.449 unlim (ARM A); scalp-residual +0.401/+1.767 (ARM B) — but this was run on UNCORRECTED L25 | **NEEDS MANUAL RERUN** | UNKNOWN — suspect | Prior verdict (deploy ARM B scalp-residual) MAY be based on corrupted L25; rerun mandatory before any live shadow |
| maker_exit_queue sim | N/A (not run) | **NEEDS MANUAL RERUN** | UNKNOWN | Queue position modeling uses deep levels; rerun after de-corruption applied in loader |

---

## 3. Updated Deploy-Relevant Numbers

### Scalp (exit-scalp, deployed)
No change. Level-0 fills. Retain:
- OOS pooled (corrected-causal, post-lookahead-fix): ALL +0.91/tr (t=2.62), CLEAN +1.47/tr (t=5.67).
- Capacity: BTC5m $800 / BTC15m $300 / ETH5m $200 / ETH15m $150 / SOL $50 ceiling. Prospect ~$2,875/month OOS-anchored. Working capital ~$1.5-2k.

### Sumpair V2 oscillation-harvest — REVISED (corrected L25)
- **1-clip REAL-DEPTH OOS: -0.70 CI[-1.39,+0.15] — NOT deployable.** Prior "+0.52 floor" was an artifact.
- **Unlim REAL-DEPTH OOS: +0.08 CI[-2.60,+3.23] — NOT sig.**
- Level-0 1-clip: +1.65 CI[+0.38,+3.35] — positive but uses non-real-depth fill assumption (misleading).
- Distribution (both models): median = -$5.00, %positive = 29-40%, both-filled = 17-23%.
- Real clips supported per snapshot: median 2, p25 1, p75 4 (book is NOT as deep as the uncorrected data implied).
- **MAX_CLIPS recommendation: suspend. The depth-realism report (`SUMPAIR_V2_DEPTH_REALISM_2026_06_14.md`) must be re-run on corrected L25 before any clip-level sizing decision.**

### b945 depth analysis
The b945 maker decode used L25 depth to estimate fill rates and queue position.
Deep-level reads (beyond level 0) were corrupted. Specific figures from `B945_MAKER_DECODE_2026_06_12.md` and the queue sim that used 25-level depth should be treated as suspect until the maker_exit_queue sim is re-run with de-corrupted data.
Queue-priority analysis (FIFO lower/proportional upper bounds) at level 0 is unaffected.

### Maker-opportunity sizing (revised)
- Inside-spread (B) = **5.4%** of notional flow, est. **~$157k/day** (was $315k). This is the "be-first" regime where a new level appears inside the spread and is taken instantly. Speed/infra edge required. Down by half.
- At-level (A) = **69.5%** of flow (queue-patience regime; existing sims already model this at 4-7% capture ceiling). Still dominant.
- Deep/transient (C) = **25.1%** (was 4.9%). The 5× increase reflects mis-classification of corrupted odd-level prices as "invisible" in the original run. These are NOT additional maker opportunity; they were L25 read errors. The actual C fraction is now better characterized: deep walks and transient levels that never appeared in the 25-level snapshot.
- **Racer/speed-moat (inside-spread) conclusion:** further deprioritized. At $157k/day addressable and a 4-7% queue-patience ceiling already modeled, the infra investment to chase inside-spread fills has a weaker case.

---

## 4. Caveat: What De-corruption Recovers vs What Still Needs Deltas

### Reliably corrected by the de-corruption swap
- **Near-touch levels (levels 2, 4 — even)**: were always correct.
- **Level 0 (best bid/ask)**: always correct; deployed strategies unaffected.
- **Odd levels (1, 3, 5, …)**: de-corruption swap (`where price_col > 1`) recovers these reliably when the corrupted price-column is obviously >1 (sizes that leaked in are typically $10-$300 notional, clearly >1). After swap, the smoke test showed 100% valid books (0 < bid < ask < 1, spread ~0.010).

### Caveat: edge cases in de-corruption
- A genuine fractional size < 1 at a corrupted odd level would be mis-handled by the value-rule (`price > 1`). This is rare but means the position-rule (swap ALL odd-indexed levels unconditionally) is slightly more robust. Until storedata confirms the exact column-order pattern, treat de-corrupted fills at deep odd levels as best-effort.

### What still needs the Phase-2 DELTA stream to nail
The de-corrupted snapshots confirm the DISPLAYED book at ~1-2Hz. They do NOT capture:
1. **Queue dynamics within a level** — whether your own repeated lifts exhaust displayed size before the next snapshot. The multi-clip sumpair V2 magnitude requires inter-fire liquidity regeneration which snapshots cannot confirm; only the live wallet or the delta stream can answer this.
2. **Transient inside-spread levels** (the "C" class, now 25.1%) — levels that appear and are taken in <1-2s between snapshots. The delta stream (`orderbook_deltas_v2`, CLEAN, ~145/s on BTC-15m) is the only source for these. The maker-opportunity (B) inside-spread estimate is an upper bound; true C is a lower bound.
3. **Order-by-order FIFO queue position** for b945-style ladder simulation — full queue-priority modeling requires per-change deltas, not 1-2Hz snapshots.

These three questions are gated on Phase-2 delta consumption pipeline (built, not yet consuming into a backtest).

---

## 5. Needs-Manual Follow-Ups

| Item | Why manual | Priority |
|---|---|---|
| **sumpair_v2_depth_realism rerun** (`_sumpair_v2_depth_realism.py`) | Long-running (~hours); re-run with de-corruption in `load_orderbook_l25_streaming` (swap odd levels) or a corrected parquet. The 2026-06-14 result is suspect and the deploy verdict (ARM B scalp-residual +$0.40 floor) must be re-established or abandoned. | HIGH — blocks all V2 sizing decisions |
| **maker_exit_queue rerun** (`_maker_queue_bt.py`) | Uses 25-level book walk for queue position; corrupted odd levels biased fill-rate estimates. Re-run after de-corruption. The FIFO lower-bound (level 0) is unaffected; deep-level proportional-upper is suspect. | MEDIUM — b945 deploy path gated |
| **Apply de-corruption to `load_orderbook_l25_streaming`** (stopgap) | Code change; add swap in loader before any research consumer reads odd levels. Until done, every ad-hoc deep-book query runs on corrupted data. | HIGH — prerequisite for the two reruns above |
| **Fix storedata collector root cause** | `emit_book_snapshot_row` positional mismatch vs migration-008 column order. Needs VPS3 access + diff of emit-tuple vs schema. New rows will be corrupted until fixed. `orderbook_deltas_v2` is CLEAN (separate write path). | HIGH — ongoing corruption until fixed |
