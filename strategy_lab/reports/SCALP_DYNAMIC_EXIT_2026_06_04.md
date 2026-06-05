# Scalp Dynamic-Exit Study — fixed +45/+60s is already optimal (no upgrade)

**Date:** 2026-06-04 · Exit-side complement to §D-1 (which closed the entry side: `delta_bps` sufficient).
**Script:** `strategy_lab/autoresearch/scalp_dynamic_exit_2026_06_04.py`
**One line:** Tested take-profit and longer-hold exit policies vs the deployed fixed +45s on the confirmed
exit-scalp. **None beat fixed +45s (cell) / +60s (broad).** Take-profit caps the winners (they run);
longer holds decay; the deployed exit sits exactly at the $/tr optimum. The SCALP_SLEEVE_AUDIT's hoped-for
"dynamic-exit upgrade" does not materialize at our data resolution. **Keep the current exit; stop tuning it.**

## Method
- Confirmed scalp universe from the physics cache (`scalp_hedge_physics_cache_2026_06_03.parquet`, BTC+ETH,
  filled). Two cells: CELL (`delta_bps>=5 & entry_vwap<0.55`, n=118) and BROAD (`entry_vwap<0.55`, n=780).
- Book-sell PnL with the confirmed scalp fee (0.015 round-trip): `(sell-ev)*sh - 0.015*sh*(ev(1-ev)+sell(1-sell))`.
- Take-profit policy: sell at TP if bid reaches it by `cap`s (`tp_hit_{60,65,70,75}_dt`), else sell at `bid_{cap}`.
- Rigor: per-fire bootstrap CI, paired bootstrap (best-TP − fixed_45), CPCV(8,2) OOF on the TP selection, DSR.

## Results
**Take-profit is worse:**
- CELL: fixed_45 +$5.56 vs best TP (TP65_cap90) +$4.49; paired diff −1.07 (CI [−2.34,+0.19], ns).
- BROAD: fixed_45 +$2.71 vs best TP (TP70_cap120) +$1.70; **paired diff −1.01 (CI [−1.63,−0.39]) = TP significantly worse.**
- CPCV-OOF best-TP: CELL +$4.33 (still < fixed_45), BROAD +$1.61 (DSR prob 0.000, ns). TP selection adds nothing.

**Fixed-time exit profile (the optimum is the deployed one):**
| exit | CELL $/tr (t) | BROAD $/tr (t) |
|---|---|---|
| +30s | +4.95 (6.24) | +2.57 (9.39) |
| **+45s** | **+5.56 (6.90)** | +2.71 (8.77) |
| **+60s** | +5.56 (6.51) | **+2.95 (8.66)** |
| +75s | +5.33 (5.62) | +2.55 (6.87) |
| +90s | +4.71 (4.34) | +2.36 (5.85) |
| +120s | +3.47 (2.63) | +2.49 (5.26) |
| +150s | +3.91 (2.92) | +1.97 (3.73) |
| +180s | +3.83 (2.57) | +1.96 (3.42) |
| HOLD→resolution | +0.14 (0.06) | +1.88 (2.09) |

- Bid mean tops at ~0.59 around +45–60s then fades → $/tr peaks at +45 (CELL) / +60 (BROAD) and decays.
- **HOLD→resolution +$0.14 (CELL) vs +$5.56 sold-on-book** reconfirms the core scalp thesis (priced-in trap):
  the entire edge is selling on the book mid-window, not holding to settlement.

## The oracle headroom is untradeable
`bid_pathmax` averages 0.838 → an "oracle peak-sell" scores +$18.50 (CELL) / +$17.40 (BROAD). But the discrete
bids at +45/+60/+90 are all ~0.59 — the path-max is a **transient inter-sample spike**, not present at any fixed
sample time. Capturing it would need tick-level book + a sub-second trailing stop; our 10Hz-sampled cache cannot
validate that. Flagged as a possible future **tick-level trailing-exit** study, NOT actionable on current data.

## Verdict
The deployed fixed exit (**+45s cell / +60s broad**) is at the $/tr optimum of the simple-exit family. No
take-profit or longer-hold variant improves it. **Lock the exit; redirect effort.** Combined with §D-1
(`delta_bps` sufficient for selection), the exit-scalp's two design knobs are now both pinned at optimum —
the remaining gate is live forward fires + the different-window OOS, not more in-sample tuning.

## Files
- `strategy_lab/autoresearch/scalp_dynamic_exit_2026_06_04.py`
- Input: `strategy_lab/directional/_results/scalp_hedge_physics_cache_2026_06_03.parquet`
- Related: `SCALP_SLEEVE_AUDIT_2026_06_03.md`, `EXIT_TIMING_MODEL_2026_06_03.md`, `META_LABEL_SCALP_CPCV_2026_06_04.md`
