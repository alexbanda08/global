# Maker-Exit (with taker-+60 fallback) — modest REAL upgrade; taker-TP leaks edge (2026-06-06)

**Script:** `strategy_lab/directional/maker_exit_sim_2026_06_06.py` · `_results/maker_exit_sim_2026_06_06.parquet`
**One line:** A maker SELL at 0.65 with taker-+60 fallback **beats the pure-taker-+60 exit by +$0.42/tr
(CI [+0.02,+0.82], significant)** on the gated scalp — favorable exit-side selection (fills when a buyer lifts =
winning) + sells at the offer not the bid + rebate. Caveat: optimistic fill model. The live **taker-TP@0.65
leaks edge** (its apparent win here is lookahead; the no-lookahead study says it underperforms +60).

## Result (gated scalp BTC/ETH vwap<0.55, n=780, in-sample Apr–Jun)
| exit | $/tr | CI | note |
|---|---|---|---|
| (1) pure taker +60 [optimum] | +2.55 | [1.88,3.23] | validated baseline |
| (3) maker-TP@0.65 + taker fallback | **+2.97** | [2.41,3.52] | **+0.42 vs (1), paired CI [+0.02,+0.82] SIG+** |
| (3) maker@0.60 / 0.62 | +2.83 / +2.83 | — | +0.28 vs (1), ns |
| (3) maker@0.58 | +2.59 | — | ns |
| (2) taker-TP@0.65 | +4.26 | — | ⚠️ INVALID — lookahead (cache tp_hit can fire after +60) |

## Why maker-exit helps (exit-side selection is FAVORABLE — opposite of maker-entry)
- Maker ENTRY died: a resting BID fills when someone SELLS into you = token going down = you're wrong (adverse).
- Maker EXIT (you hold the lead token, rest a SELL): fills when a BUYER lifts your offer = token going UP = your
  position WINNING. You sell into strength, at the **offer** (0.65) vs taker-crossing to the **bid** (~0.59), and
  earn the rebate. On non-fills you taker-cross at +60 (the baseline) → no hold-trap, no downside vs current.
- Net: strictly ≥ pure-taker-+60 on the fires that reach the offer within 60s; same otherwise. Hence +$0.42/tr.

## Caveats (before deploy)
- **Optimistic fill**: model = "first BUY trade ≥ target in [fire,+60] → fill". Ignores QUEUE POSITION (you sit
  behind existing offers at 0.65) → real fill rate lower → +0.42 is an upper bound. Needs an L25 queue-aware sim.
- **Fixed target 0.65 caps runners** vs a hold-longer policy (but not vs the +60 baseline, which sells lower).
  The real implementation should PEG-TO-ASK / trail, not a fixed 0.65.
- In-sample (Apr–Jun); confirm OOS (Mar30–Apr21 BBO has the ask path for a proper queue model).
- Only 0.65 is SIG+; lower targets are ns (less spread to capture vs bid_60).

## Live-audit tie-in
The live sleeves run **taker** TP@0.65 + stop. The lookahead-free `SCALP_DYNAMIC_EXIT_2026_06_04` shows taker-TP
< pure +60. So: **(a) disable the live taker-TP/stop → pure +60** (confirmed fix, `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md`);
**(b) then test the MAKER exit** with a realistic queue model + OOS → if it holds, replace the +60 taker exit with
a maker-at-offer + taker-+60 fallback.

## Next (the proper maker-exit build)
1. Queue-aware fill: use L25 ask depth/size at the target level; model fill only if cumulative buy-volume at ≥target
   exceeds the queue ahead of you. 2. Peg-to-ask/trail instead of fixed 0.65. 3. OOS on Mar30–Apr21. 4. ml4t DSR.
