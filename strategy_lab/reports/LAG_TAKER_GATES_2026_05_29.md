# Lag-taker GATE enrichment — Phase 2A (2026-05-29)

> Sharpens the leg-1 directional binance→chainlink lag taker (see
> `LAG_TAKER_EDGE_RESEARCH_2026_05_29.md`). Base universe = **BTC+ETH, |delta_bps|≥3,
> fire at slot_start+5s, $25 L25 walk + 85ms latency + same-token spread≤0.05, hold to
> chainlink resolution, 0.07 winner-only fee**. Base: **n=1230, WR 65.4%, +$2.39/tr,
> t=4.06 (IS t=3.47, OOS t=2.46), ~57 fires/day, maxDD −$394.**
> Window 2026-05-08 → 05-29 (21.5d). IS/OOS split @ 05-18. All features computed at/before
> `fire_us` (causal, no lookahead).
>
> Scripts: `_gate_features_2026_05_29.py` (feature build) → `_gate_analysis_2026_05_29.py`
> (per-gate conditionals) → `_gate_stack_refine_2026_05_29.py` (stacks + recommended).
> Enriched fires: `strategy_lab/lag_taker_fires_enriched_2026_05_29.parquet`.
> CSVs: `strategy_lab/directional/_results/lag_taker_gate_{singles,stacks,stacks_refined}.csv`.

---

## VERDICT — three real gates lift the edge; two are noise; the rest are neutral

| effect | gate |
|---|---|
| ✅ **material lift, OOS-robust** | **time filter (ex 18-23 UTC)**, **cross-asset confluence**, **top-of-book depth ≥ median**, **delta_bps ≥ 5** |
| ◻ neutral / weak | persistence (last-3 1s same sign), realized-vol regime, entry-vwap band, RSI/MACD/CCI alignment |
| ❌ artifact (tiny-n, do NOT use) | macd-disagrees (n=20-23), delta≥8/12 (n collapses, edge gone) |

**Recommended GATED config = ex-18-23-UTC AND cross-asset confluence (R5):**
**n=477, WR 68.1%, +$3.42/tr, t=3.71, IS t=2.45 / OOS t=2.78, ~22 fires/day, maxDD −$227.**
Both IS and OOS significant, maxDD cut ~42% vs base, WR +2.7pp, $/tr +43%.

---

## Per-gate conditional table (base = BTC+ETH d≥3; gate TRUE vs base)

| gate | n_true | WR_true | $tr_true | t_true | vs base $tr | OOS_n | OOS_t | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| **delta_bps ≥ 5** | 371 | 69.8% | +3.38 | 3.33 | +1.00 | 254 | 2.02 | ✅ dose-response |
| delta_bps ≥ 8 | 89 | 70.8% | +2.18 | 1.11 | −0.21 | 69 | 0.49 | ❌ n-collapse |
| delta_bps ≥ 12 | 32 | 56.2% | −4.17 | −1.22 | −6.55 | 24 | −0.77 | ❌ noise |
| persist3 (last-3 1s same sign) | 299 | 67.2% | +2.89 | 2.47 | +0.51 | 186 | 1.63 | ◻ weak |
| rv30 LOW (<med 0.73bps) | 615 | 66.5% | +2.82 | 3.43 | +0.44 | 381 | 1.71 | ◻ mild, OOS soft |
| rv30 HIGH (≥med) | 615 | 64.2% | +1.95 | 2.33 | −0.43 | 399 | 1.76 | ◻ |
| **topdepth ≥ med ($19.2)** | 615 | 66.2% | +3.05 | 3.63 | +0.67 | 411 | **2.80** | ✅ cleaner fills |
| spread ≤0.02 | 906 | 63.7% | +1.77 | 2.55 | −0.62 | 602 | 1.76 | ❌ wrong sign |
| spread ≤0.01 | 639 | 63.4% | +1.72 | 2.08 | −0.67 | 429 | 1.11 | ❌ wrong sign |
| **ex 18-23 UTC** | 880 | 66.2% | +2.90 | 4.19 | +0.52 | 543 | **3.29** | ✅ confirmed |
| 00-11 UTC block | 438 | 68.7% | +3.33 | 3.51 | +0.94 | 280 | 2.17 | ✅ sharper, less n |
| vwap < 0.62 | 754 | 60.7% | +3.06 | 3.67 | +0.67 | 456 | 2.98 | ✅ lift, lower WR |
| vwap in [0.45,0.70) | 1054 | 63.9% | +2.44 | 3.76 | +0.06 | 665 | 2.39 | ◻ neutral |
| **cross-asset confluence** | 686 | 66.8% | +2.61 | 3.39 | +0.22 | 452 | 2.17 | ✅ +WR, OOS-ok |
| macd agrees w/ dir | 1207 | 65.4% | +2.38 | 4.02 | −0.01 | 760 | 2.33 | ◻ neutral (≈all) |
| cci20 agrees w/ dir | 1211 | 65.3% | +2.37 | 4.00 | −0.01 | 765 | 2.42 | ◻ neutral |
| rsi14 agrees w/ dir | 1185 | 65.3% | +2.36 | 3.95 | −0.02 | 747 | 2.36 | ◻ neutral |
| macd DISagrees w/ dir | 23 | 65.2% | +2.70 | 0.61 | +0.31 | 20 | 0.97 | ❌ tiny-n |

**Reads:**
- **delta dose-response** holds 3→5bps (WR 65→70%, $tr +2.4→+3.4) then **breaks at ≥8/12bps**: n
  collapses and the largest moves over-revert (≥12bps is net-NEGATIVE) — the freshest-stale-ask
  thesis caps out; huge moves are spikes that mean-revert into the oracle settle. Sweet spot ≥5.
- **Spread is INVERSE** — tighter spread ⇒ WORSE edge. The wide-spread fires (>0.02, n=324) hit
  +$4.11/tr WR 70%. The lag pickoff lives where the book is *dislocated* (stale wide ask), not
  where it's tight. So do NOT add a tighter-spread gate beyond the base 0.05 cap.
- **topdepth ≥ median** is the cleaner microstructure cut: more $ resting at the stale ask ⇒
  fuller $25 fill at the discount, +0.67 $tr, OOS t=2.80 (the single most OOS-robust gate).
- **TA alignment (RSI/MACD/CCI on 1s bars) is noise** — they agree with the move direction ~98%
  of the time (the move IS the signal), so the "agree" subset ≈ the whole base. No edge; drop.
- **Cross-asset confluence** (the other asset of BTC/ETH leading the SAME direction in an
  overlapping window, ≥3bps) lifts WR to 66.8% and cuts maxDD — a genuine "two oracles lagging
  the same shock" confirmation.

---

## Best gate stacks (combined configs, IS vs OOS)

| stack | def | n | WR | $tr | t | maxDD | /day | IS t | OOS t | OOS $tr |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| R0 base | d≥3 | 1230 | 65.4 | +2.39 | 4.06 | −394 | 57.1 | 3.47 | 2.46 | +1.80 |
| R1 | ex18-23 | 880 | 66.2 | +2.90 | 4.19 | −254 | 40.9 | 2.59 | 3.29 | +2.84 |
| **R5** | **ex18-23 + xconf** | **477** | **68.1** | **+3.42** | **3.71** | **−227** | **22.2** | **2.45** | **2.78** | **+3.16** |
| R7 | ex18-23 + d≥5 | 248 | 71.8 | +4.73 | 3.79 | −254 | 11.5 | **3.15** | 2.39 | +3.66 |
| R2 | ex18-23 + dep | 441 | 66.7 | +3.65 | 3.64 | −266 | 20.5 | 1.44 | 3.51 | +4.25 |
| R3 | ex18-23 + vwap<0.62 | 545 | 62.2 | +3.73 | 3.83 | −345 | 25.3 | 1.61 | 3.72 | +4.62 |
| R9 | ex18-23 + vwap<0.62 + xconf | 286 | 64.7 | +4.66 | 3.54 | −205 | 13.3 | 1.60 | 3.33 | +5.53 |
| R4 | ex18-23 + dep + vwap<0.62 | 284 | 62.0 | +4.46 | 3.21 | −362 | 13.2 | 0.56 | 3.85 | +6.68 |

**Why R5 is the recommendation (not the higher-$tr stacks):** R2/R3/R4/R9 all post huge OOS $tr
but **weak IS (t 0.56–1.61)** — that IS/OOS asymmetry means their OOS strength is concentrated in
the back-half sample, not a robust effect; risky to deploy. **R5 and R7 are the only multi-gate
stacks significant in BOTH halves.** R5 keeps the larger n (477 vs 248) and the lowest maxDD of
the high-n group (−227); R7 (ex18-23 + d≥5) is the sharper-but-thinner alternative (WR 71.8%,
+$4.73/tr, 11.5/day, strongest IS t=3.15) if you want max $/fire and can tolerate ~half the
volume.

---

## Recommended GATED entry config (feeds the stop-loss phase)

```
asset      ∈ {BTC, ETH}                      # SOL stays dropped (net drag)
signal     delta_bps = binance_1s(slot_start+5s)/binance_1s(slot_start) − 1, ×1e4
gate-1     |delta_bps| ≥ 3.0                  # base (≥5 = sharper R7 variant)
gate-2     UTC hour < 18  (AVOID 18-23)       # foundation time filter, OOS t=3.29 alone
gate-3     cross-asset confluence: the OTHER asset (BTC↔ETH) is ALSO leading the SAME
           direction (its |delta_bps|≥3) in a window overlapping fire_us
direction  Up if delta>0 else Down
fire       fire_us = (slot_start + 5)·1e6
fill       engine_v2.fill_at_book, $25 walk, 85ms latency, same-token spread≤0.05, native-10Hz L25
exit       HOLD to chainlink resolution
fee        0.07 winner-only:  pnl_won=(1−vwap)·sh·(1−0.07·vwap), pnl_loss=−vwap·sh
optional   topdepth(best-ask $) ≥ median (~$19)  → +OOS robustness, ~half the fires (R6)
```
**Expected: ~22 fires/day, WR 68.1%, +$3.42/$25 (+13.7%/fire), maxDD −$227 over 21.5d.**
**IS t=2.45, OOS t=2.78 — significant out-of-sample.** vs base: +2.7pp WR, +$1.03/tr, −42% maxDD.

Sharper low-volume alternative **R7 (add delta≥5 instead of confluence)**: ~11.5/day, WR 71.8%,
+$4.73/tr, IS t=3.15 / OOS t=2.39.

---

## Caveats
- 21.5-day window (binance-1s coverage). Forward data still needed to lock OOS.
- Gates chosen from a sweep; mitigated by requiring BOTH-half significance (rejected R2/R3/R4/R9
  on weak IS despite gaudy OOS $tr).
- **Spread gate is counter-intuitive (inverse)** — do not tighten beyond the base 0.05 cap; the
  edge lives in dislocated books.
- 1s-bar TA (RSI/MACD/CCI) carries no incremental signal — the move itself is the directional
  signal; alignment gates are ~no-ops. Dropped.
- Combine with the next-phase stop-loss (15-20¢ variance reducer) and sizing on this gated subset.

## Artifacts
- Report: `strategy_lab/reports/LAG_TAKER_GATES_2026_05_29.md`
- **Gated fire subset (R5): `strategy_lab/lag_taker_fires_gated_2026_05_29.parquet`** (n=477)
- Enriched fires (all gates as columns): `strategy_lab/lag_taker_fires_enriched_2026_05_29.parquet`
- Scripts: `_gate_features_2026_05_29.py`, `_gate_analysis_2026_05_29.py`, `_gate_stack_refine_2026_05_29.py`
- CSVs: `strategy_lab/directional/_results/lag_taker_gate_{singles,stacks,stacks_refined}.csv`
```
