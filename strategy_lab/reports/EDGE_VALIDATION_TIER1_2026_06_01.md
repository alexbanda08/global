# Tier-1 New-Edge Validation — Backtest Results — 2026-06-01

Backtest validation of all 16 Tier-1 candidates from `NEW_EDGE_RESEARCH_2026_06_01.md` (the
deep-research swarm output). Five staged harnesses, each loading heavy sources once, on canonical
data. Metric: directional WR vs chainlink outcome → then **real L25 fills + 0.07 winner-only fee
($/tr)** for any signal whose WR looked tradeable.

Scripts: `strategy_lab/directional/edge_val_stage{1..5}_*.py` · CSVs/parquets in `_results/`.

---

## TL;DR — 0 of 16 reach deploy-grade significance on real fills. The swarm is a good IDEA generator; fill-based backtesting is what separates signal from artifact.

The research swarm surfaced 49 "adversarially-verified" candidates with confident stats
("arXiv-validated on 30B events", "p=0.041 confirmed", "89% WR"). Rigorous backtesting:
- **15/16 are dead, traps, or inverted.**
- **1 survivor — A1 HL short-liq cascade (60s)** — is a *real* directional lean (entry vwap ≈0.51,
  no priced-move trap) but underpowered (+$0.7–1.2/$25, **t≈0.4**, n≈100–130, HL data stale at May27).
  Its value is that it **justifies fixing the broken live `g_a2` gate (300s→60s)**, not as standalone alpha.
- A2 (cross-CEX cascade) is promising-but-thin (2.8d only) — accumulate, re-test later.

**The dominant failure mode = the "move-already-happened" trap:** any signal read mid-window
(poly CVD, VPIN, book depth) correlates with the realized intra-window move, which is already
priced into the entry vwap. High WR, zero $/tr. The fee/fill stage is non-negotiable.

---

## Scoreboard

| Edge | Type | Verdict | Evidence |
|---|---|---|---|
| **A1 HL short-cascade 60s** | gate/strat | ⚠️ **REAL but thin** | dir WR 57.9% +8pp p=0.03 (Stage1); on fills WR 53.8%, vwap 0.51, +$0.74/tr, **t=0.35** (Stage5). Confirms 60s≫300s → fix g_a2. |
| A2 cross-CEX liq cascade | gate/strat | 🟡 promising-thin | sell-liq→UP: T50k 60.7% p=0.028, T100k 63.1% p=0.020 (n=65–84, **2.8d only**, no fill test) |
| C6 HL prior-slot+imbalance | gate | ❌ weak | best 53.4% p=0.12; imbalance adds nothing |
| C7 HL ETH long-cascade | gate | ❌ not reproducible | `Close Long`+`method=market` ≈0 qualifying windows in-window (report count used broader dir filter) |
| B2 KAMA Efficiency Ratio | gate | ❌ dead | overlay on momo: ≤+0.6pp, ns |
| B3 Realized semivariance | gate | ❌ dead | overlay: ≤+0.65pp, ns |
| B4 Rogers-Satchell vol | gate | ❌ dead | overlay: ±0.2pp, ns |
| B5 Page-CUSUM | indicator | ❌ dead | standalone 48.6–49.4% (negative) |
| B6 Kalman velocity | indicator | ❌ dead | standalone 49.6% (negative) |
| B1 Polymarket VPIN | gate | ❌ **TRAP** | WR 75–87% but vwap 0.76–0.87, **$/tr −$0.62 → +$0.01**, t≤0 |
| C1 book depth-decay ratio | gate | ❌ inverted | WR 31–41% (lift −9 to −19pp, p=0) — mechanism backwards |
| C4 Polymarket CVD follow | gate | ❌ **TRAP** | WR 67–73% but vwap 0.68–0.74, **$/tr −$1.03 → −$0.76**, t=−5 to −8 |
| C5 session-open burst | gate | ❌ anti (−EV) | follow: −4 to −11pp p≈1.0 → momentum *mean-reverts*; contrarian lead only |
| C8 cross-token ask asym | gate | ❌ inverted | WR 30–35% (lift −15 to −20pp, p=0) |
| C2 depth-drain kill | gate | ⬜ untested | multi-snapshot; low prior (C1/C8 same family = traps) |
| C3 fleeting-order OBI | gate | ⬜ untested | multi-snapshot; low prior |

**Base rates (this window):** P(Up) ≈ 0.499; production momo `ret_2m@ws_s` WR = **49.6%** (a coin
flip — pre-window price momentum does NOT predict chainlink direction). This is *why* every
momo-overlay gate (B2–B4) shows ~0 lift: you can't subset a coin flip into edge.

---

## The two structural findings (more valuable than the gate verdicts)

### 1. Binance price-technicals at ws_s are dead; FLOW is where (any) edge lives
Raw momentum, KAMA-ER, semivariance, Rogers-Satchell, CUSUM, Kalman — all ~50% vs the oracle. The
market/oracle has priced pre-window price-history. The only signals with *any* directional lean are
order/flow-driven (liq cascades). This matches the lag-taker (intra-window flow) and kills a whole
class of "add a fancier TA indicator" ideas.

### 2. The "move-already-happened" trap (why 89% WR = −$0.62/trade)
Reading Polymarket CVD / VPIN / book-depth at `slot_start + offset` captures the move that already
occurred in the first `offset` seconds of the window. That move is (a) correlated with the final
outcome (part of the window is locked in) → **high WR**, and (b) already priced into the book →
**entry vwap 0.68–0.87**. WR rises with threshold *in lockstep with* vwap, so $/tr stays ≤0. Any
mid-window microstructure signal must be validated with the L25 fill + fee, never WR alone.
A1 escapes this because its signal (liq cascade) ends at ws_s, **5–15 min before the slug opens**,
so entry vwap ≈0.51 (fair) — the structural reason A1 is the lone non-trap.

---

## Recommendations

1. **Ship the `g_a2` fix (300s → 60s window)** on the HL short-cascade gate — the 60s window is
   clearly the live signal (57.9% vs 300s ≈50%); the directional lean is real (vwap-confirmed). Treat
   it as a marginal WR-lift filter, not a standalone sleeve. Size tiny; HL feed is stale (repair first).
2. **A2 (cross-CEX cascade): keep accumulating** the `cex_futures_liquidations` feed (gate+okx;
   repair bybit/bitget per the hlcascade fix), re-test in 2–4 weeks with a fill stage and n≥300.
3. **Retire B1/B2/B3/B4/B5/B6/C1/C4/C5/C8** as new-edge candidates — verified non-tradeable.
4. **Process learning:** the swarm's "edge_plausibility" + "feasible" verdicts do NOT survive fills.
   For future research swarms, add a **mandatory fill+fee backtest gate** before any candidate is
   labeled an edge, and **flag mid-window microstructure signals as trap-suspect by default**.
5. C5's inverted result (session-open momentum mean-reverts) and C1/C8 inversions are the only
   "significant" non-A1 results — all are likely the same priced-move artifact viewed contrarian;
   a contrarian fill-test would hit the inverse vwap trap. Low priority, but the lone novel directions left.

## Artifacts
- Stage1 liq: `_results/edge_val_stage1_liq_2026_06_01.csv`
- Stage2 klines: `_results/edge_val_stage2_klines_2026_06_01.csv` (+ features parquet)
- Stage3 poly-flow: `_results/edge_val_stage3_polyflow_2026_06_01.csv` (+ features parquet)
- Stage4 L25 fills: `_results/edge_val_stage4_l25_2026_06_01.parquet`
- Stage5 A1 fill: `_results/edge_val_stage5_a1fill_2026_06_01.parquet`

## END
