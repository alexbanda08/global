# PAIRLOCK BACKTEST RESULTS — 2026-06-12 — VERDICT: mechanic works, but STRICTLY DOMINATED by the deployed +60s sell

_Runner: `strategy_lab/directional/pairlock_btc15m_bt_2026_06_12.py` (corrected lib
`scalp_fill_lib_2026_06_10`: resolve_size, held_value, exit_fill; winner-only 0.07; +85ms latency;
size-capped hedge fills re-checked post-latency). Universe: `lag_taker_fires_oos_2026_06_01.parquet`
BTC-15m δ≥3, Apr 24 → Jun 1 (n=243; Arm A vwap<0.55 n=97). Trials: 10 cells (2 arms × 5 targets).
Spec under test: `TV_AGENT_SPEC_PAIRLOCK_BTC15M_SHADOW_2026_06_12.md` (gate 1 = this backtest)._

## Headline (Arm A = production entry, $5 stake)

| Exit policy | $/market | CI95 | vs ctrl (paired) |
|---|---|---|---|
| **CONTROL: +60s time sell (deployed)** | **+0.670** | [+0.409,+0.921] | — |
| Pure hold to resolution | +0.193 | [−0.850,+1.219] | — |
| Pairlock tgt 0.99 | +0.105 | [+0.041,+0.183] | **−0.566 [−0.817,−0.315]** |
| Pairlock tgt 0.97 (spec primary) | +0.090 | [−0.149,+0.291] | −0.580 [−0.867,−0.299] |
| Pairlock tgt 0.95 | +0.232 | [−0.037,+0.462] | −0.439 [−0.729,−0.155] |
| Pairlock tgt 0.93 (best) | +0.296 | [−0.032,+0.570] | −0.374 [−0.704,−0.069] |
| Pairlock tgt 0.90 | +0.237 | [−0.195,+0.640] | −0.434 [−0.824,−0.035] |

**Every pairlock cell loses to the control with CI-significant paired difference.** Arm B (any-vwap,
n=243) identical story (best +0.126 vs ctrl +0.230; diffs −0.10..−0.28). The pair-lock does NOT widen
the safe entry universe either: Arm B pairlock cells hover ~0, ctrl stays positive.

## Mechanics (why it loses for US)
- Completion is easy (87–100%) and the locked leg behaves exactly as decoded (paircost median ≈ target,
  locked +0.10..+0.91/mkt growing as target deepens) — **the b945 mechanic is faithfully reproduced.**
- But the residual drags (−0.21..−0.67) and, decisively, hedging-to-lock captures LESS of the lag move
  than simply selling the winner at +60s. Our entry's edge is concentrated in the first 60s repricing;
  the taker hedge pays the opposite token's spread to lock a smaller piece of the same move.
- b945 needs the pair-lock because of HIS constraints: whole-curve (weaker) entries that need the hedge
  to be safe, $726/market deployed (can't taker-sell at that size without slippage — redeem IS his
  capacity exit), and maker fills/rebates we refuse to credit offline.

## Bankroll sim ($300, chronological, capital locked to settlement, 38 days)
- Arm A tgt 0.93: **$300 → $328.76 (+9.6%), MDD −$5.00**, 97 mkts, 0 skipped.
- Control equivalent: 97 × +0.670 ≈ **$300 → $365 (+21.7%)** on the same fires.
- Curiosity worth noting: **tgt 0.99 is a near-riskless micro-arb** (+0.105/mkt, CI>0, 100% completion,
  zero residual, MDD ≈ 0) — real but dominated; not worth a sleeve at our scale.

## DECISION
- **Do NOT deploy `shadow_pairlock_btc_15m_v1`.** Gate 1 of the spec FAILED: the mechanic is positive
  but strictly dominated by the live config (pure +60s time sell) on every cell, paired CI excludes 0.
- The deployed scalp exit remains optimal among {hold, +60 sell, pairlock×5}. This is now the third
  independent confirmation of the +60s sell (after the stop removal and maker-exit kill).
- b945's strategy is a **capacity/scale solution, not an entry-alpha improvement** — revisit pair-lock
  ONLY if we ever need to deploy >$200/market on these books (where taker exits start paying real
  slippage), or with maker hedge fills validated LIVE (offline maker = banked dead).

Artifacts: `_results/pairlock_btc15m_bt_2026_06_12.parquet` (243 markets × all cells).

---

# PART 2 — STANDALONE replication (his strategy, no scalp signal) — SIG-NEGATIVE EVERYWHERE

_Runner: `pairlock_standalone_bt_2026_06_12.py`. Universe: ALL 4,366 btc-updown-15m windows with
L25 books + canonical resolution, Apr 22 → Jun 9 (48 days). Mechanic: leg1 = buy whichever token's
ask dips ≤ L1 in t∈[60,600)s; leg2 = complete the pair at blended ≤ TARGET by t≤870s; hold to
redeem; winner-only 0.07; +85ms latency; resolve_size caps. Grid 3×3 + sanity arm._

**Sanity arm PASSED:** instant-pair at open = −$0.3027/mkt, paircost median 1.010 = exactly the
book overround + fee. The harness measures what it should.

| cell (L1_TGT) | fire% | comp% | paircost med | $/fired | CI95 |
|---|---|---|---|---|---|
| 0.50_0.93 (best) | 95% | 66% | 0.920 | **−0.472** | [−0.558,−0.386] |
| 0.45_0.95 (center) | 95% | 68% | 0.940 | −0.562 | [−0.642,−0.482] |
| 0.40_0.93 (worst) | 94% | 61% | 0.920 | −0.632 | [−0.725,−0.537] |

ALL 9 cells sig-negative (−0.47..−0.63 $/fired at $5 clips). Bankroll $300 → **$0.28–$1.85 (ruin)**
in 48 days. The decomposition shows why: completed pairs DO lock profit (+0.29..+0.73/mkt — the
mechanic "works"), but leg1-dip buying is pure ADVERSE SELECTION — the dipped token is dipping
because it is losing; the 27–39% uncompleted residuals (−0.78..−1.36/mkt) bury the locked gains.

## FINAL SYNTHESIS — both ends now bracketed
1. **Mechanic WITHOUT a signal** (faithful observable replication): sig-negative, ruin. ← Part 2
2. **Mechanic WITH our validated signal**: positive (+0.09..+0.30/mkt) but strictly dominated by
   the deployed +60s sell (+0.67/mkt) on the same fires. ← Part 1
→ **The pair-lock is NOT where b945's edge lives.** His alpha is in the UNOBSERVABLE entry
selection (which side first, when — his Chainlink/CVD lag signal) plus maker fills; the pair
assembly is risk/capacity management on top. Any profitable replication requires a lag entry
signal — and our own OOS-validated signal already monetizes better through the simpler exit.
**Thread CLOSED. Do not re-open the pair-lock without a >$200/market capacity need.**
(WR≠edge reconfirmed: 61–73% completion, 69% slug-WR on his tape, still negative without his entry.)

Artifacts: `_results/pairlock_standalone_bt_2026_06_12.parquet` (4,366 windows × 9 cells + sanity).
