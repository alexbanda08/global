# Ladder v2 first results — G1 answers the question: residual drag is REAL and eats the edge
**2026-07-01. 31h of v2 (`poly_ladder_btc_15m_v2`, Ireland, PAPER), Jun 30 14:31 → Jul 1 21:30. 124 windows, 116 traded (94%), 104 clean (settled outcome). Raw: `strategy_lab/directional/_ireland_6day/{ladder_summary_v2.tsv, analyze_v2.py}`.**

Deploy note: TV agent used the fallback path — same DB `tradingvenue_rust`, new sleeve id `poly_ladder_btc_15m_v2` (no `tradingvenue_rust_v2` DB; old data NOT yet deleted). Engine restarted Jun 30 17:45; the 12 pre-restart windows logged `outcome: null` + `residual_pnl = 0` (early build) — excluded from the clean set.

## 1. Integrity — the implementation is correct
- `total_net = paired + rebate + residual`: exact (maxdiff $0.000000).
- `paired_pnl = paired_sh·(1−pvs)`: exact.
- `residual_pnl` matches the spec formula exactly on ALL settled rows (the 12 "deviations" were the pre-restart `outcome:null` rows).
- **`outcome` ground-truthed vs Binance 1m (public API): 3/3 MATCH.** No sign-flip.
- Latency p50 37µs / p95 80µs. Warmup fails only 4/124.
- 🟡 One telemetry bug: **`pair_gate_bound_sh` = 0 everywhere** — the counter isn't wired. The gate itself demonstrably works (below).

## 2. G3 pvs gate — WORKS, and improves the paired engine
| | v1 (13.4d) | v2 (31h) |
|---|---|---|
| windows pvs > 1 (locked losses) | **33%** | **0%** (0/96, max pvs 0.9715) |
| pvs mean | 0.956 | **0.859** |
| paired_pnl / win | +$1.31 | **+$1.58** |
| paired $/day | ~$111 | **~$142** |
| pair_frac | 0.80 | 0.60 |
| fills up/dn per win | 35.1 / 34.3 | 15.7 / 15.1 |
| flow_capture | 1.7% | 0.8% |

0/96 above 0.99 vs v1's 33%>1 is impossible by regime chance (~1e-17) → the cap is active. Side-effect: **fills halve and pair_frac drops 0.80→0.60** (capped second-leg bids complete fewer pairs), but the pairs you do get are much cheaper — paired $/day is *better* despite half the volume.

## 3. G1 residual measurement — THE ANSWER (this is what v2 was for)
**Clean 104 settled windows:**
```
paired_pnl_locked   +$1.58/win
rebate              +$0.05/win
residual_pnl        −$2.24/win   CI95 [−2.77, −1.69]      ← the drag, now measured
TOTAL NET           −$0.687/win  CI95 [−1.295, −0.062]    P(net>0) = 1.7%
```
**→ As configured (residual HELD to resolution), the strategy is significantly NET NEGATIVE.** My "most-likely ~neutral" residual estimate was wrong — and the reason is structural:

### The adverse-selection mechanism (−5.5σ)
- The residual = the side taker sell-flow filled you heavier on. **That side wins only 14.7%** of windows (17/116) at mean entry 0.397, where breakeven ≈ 39.7%. z = −5.5σ.
- Scales with size: small residuals win 22.4%, **big residuals win 6.9%**.
- Crosstab: residual-dn → dn wins 6/50; residual-up → up wins 11/54. **The lighter side wins 85.3%.**
- Cost: **−$0.241 per share held** (965 sh → −$233).

This is the b945 "−$29k residual drag" reproduced in our own live tape: the flow that fills a passive maker is informed at the window scale — you accumulate the losing side. Holding that inventory to resolution is a systematically losing lottery.

## 4. The fix is visible in the same data — manage the residual, don't hold it
Counterfactual on the same 116 windows (residual flattened instead of held):
| residual exit cost | total_net / win | sum |
|---|---|---|
| 0.00 /sh (flat) | **+$1.62** | +$188 |
| 0.02 /sh | +$1.46 | +$169 |
| 0.05 /sh | **+$1.21** | +$140 |

Even paying a nickel a share to get flat, the strategy flips decisively positive (~+$93/day pace). The paired engine (+$1.58/win, 0% locked losses) is healthy — **the entire problem is unmanaged residual inventory.**

### v3 design options (in preference order)
1. **Maker-recycle (b945-style):** re-quote heavy-side inventory on the SELL side intra-window — earn the spread getting flat instead of paying it. Two-sided recycling is exactly what b945 does; keeps 100% maker.
2. **Inventory-skew / pause:** stop quoting the heavy side once |imbalance| > X sh (cheap, prevents growth; doesn't shed what's already on).
3. **Taker-flatten backstop:** at T−60s, if |residual| > X sh, cross the spread to flat (bounded cost ≈ spread + fee; the counterfactual shows ≤0.05/sh is fine).
Likely v3 = 1 + 3 (recycle intra-window, backstop at window end), with `residual_pnl` telemetry kept as-is to verify.

### Bonus signal (bank, don't act yet)
"Lighter-filled side wins 85%" = a strong window-scale directional read from maker-fill imbalance. Same coin as the adverse selection, but as a *standalone* signal it's untested — worth a pre-registered offline study later, n=116 is small.

## 5. Also found
- 🔴 **VPS3 `orderbook_deltas_v2` broke AGAIN:** accrued 7.15M rows after the fix, then stopped — max ts Jun 30 18:24 (+02), stale ~29h. Same class as `STOREDATA_DELTA_WRITE_REGRESSION_2026_06_29.md`; needs the storedata agent to look at collector logs around Jun 30 18:24 (restart? gate state? flush?). Blocks Phase-2 again.
- v1 data still on Ireland (delete gate in the v2 spec not yet exercised — fine, backup exists at `D:\global_data\ireland_archive\`).

## 6. Next actions
1. **TV agent — v3 spec: residual management** (recycle + backstop, keep telemetry). This is the go/no-go lever; counterfactual says +$1.2–1.6/win once managed.
2. TV agent (minor): wire `pair_gate_bound_sh`.
3. **Storedata agent:** delta write stopped again Jun 30 18:24 — re-diagnose.
4. Keep v2 running meanwhile — every extra window sharpens the residual-drag estimate and the imbalance signal.

**Bottom line:** v2 did its job in 31 hours. Paired arb engine: healthy and improved by the gate (+$1.58/win, zero locked losses). Residual held to resolution: −$2.24/win, adversely selected at −5.5σ → net −$0.69/win, P(>0)=1.7% — **NO-GO as configured**, but the same tape shows managing the residual flips it to ~+$1.2–1.6/win. One more iteration (v3 residual management), then re-decide.
