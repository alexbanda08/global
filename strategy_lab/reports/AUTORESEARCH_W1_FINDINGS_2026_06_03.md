# W1 (CLOB + full-indicator slug-selection) findings + autoresearch harness READY — 2026-06-03

## Built this phase
- **37 TA indicators** per asset (TA-Lib + custom), causal on 1m klines: Parabolic SAR, ADX(+DI/−DI),
  SuperTrend, ATR/NATR, Stochastic, RSI(7/14), Williams %R, OBV(+slope), CMF, EMV, StdDev, Bollinger
  (%B/bw), Keltner, MACD, CCI, MOM/ROC, EMA-stack(9/21/50/200), realized-vol, vol-z, multi-horizon returns.
  → `autoresearch/_data/indicators_{asset}.parquet`.
- **22 CLOB-tape flow features** per slug from `trades_polymarket` (42.8M rows, via duckdb): trade count,
  $volume, buy/sell size imbalance, aggressive ratio, max/mean trade size, trade-VWAP, Up-vs-Down net-buy,
  cross-token flow asymmetry, price-impact — in PRE-window `[ws−300s, ws]` and EARLY-window `[ws, fire]`.
  → `autoresearch/_data/clob_flow.parquet`. **First time the CLOB trade tape has been used for modeling.**
- **Master feature matrix:** 2533 fires × 105 cols (indicators asof ws_s + CLOB + physics + scalp labels).
- **autoresearch harness** (Karpathy pattern): `candidate.py` (editable surface) → `run.py` → `fitness.py`
  (lockbox $/tr-after-fee + bootstrap CI + **asset-confound penalty**) → `history.jsonl`; `program.md` =
  agent instructions with the trap-antibodies baked in. **Ready to run autonomously.**

## W1 finding — slug-selection does NOT beat the entry filter (honest negative)

Target = scalp PnL-after-fee (NOT direction). All on `entry_vwap<0.55` universe, exit+45, time-held-out
lockbox (n≈195). All-take baseline = **+$2.874/tr, CI [1.63,4.10]**.

| candidate | gated $/tr | lift | gated CI | asset mix | fitness | verdict |
|---|--:|--:|--:|--:|--:|---|
| all (ind+clob+phys+entry) e60 | 3.33 | +0.28 | [1.86,4.76] | BTC111/ETH23 | 1.86 | best legit — but lift within noise |
| clob+ind (no entry) | 3.26 | +0.39 | [1.72,4.83] | BTC105/ETH30 | 1.72 | within noise |
| all e45 | 3.17 | +0.29 | [1.62,4.67] | BTC105/ETH24 | 1.62 | within noise |
| indicators_only | 3.57 | +0.70 | [2.06,5.10] | **BTC127/ETH0** | **−0.94** | ❌ ASSET-CONFOUND (all-BTC) |
| all_rf | 3.68 | +0.81 | [2.01,5.36] | **BTC100/ETH0** | **−0.99** | ❌ ASSET-CONFOUND (all-BTC) |
| clob_only | 2.66 | −0.21 | [1.03,4.27] | BTC69/ETH28 | 0.0 | CLOB alone does NOT select |
| all_xgb broad | 0.87 | +0.60 | [−0.05,1.80] | BTC193/ETH53 | −0.05 | CI touches 0 |
| clob_only broad | −0.03 | −0.31 | — | — | −0.92 | CLOB alone negative |

### Read
1. **No confound-free candidate beats all-take with a real margin.** The best legit lift is **+$0.28/tr**
   (mixed assets) — its gated CI [1.86,4.76] overlaps the all-take CI [1.63,4.10] almost entirely → within noise.
2. **The biggest raw "lifts" (+0.70/+0.81) are pure asset-selection confounds** — the model gates to 100% BTC
   (the stronger asset). The harness's confound guard caught and penalized them (−3). This is the Block-2b
   physics lesson repeating; without the guard we'd have "found" a fake +$0.8/tr edge.
3. **CLOB-tape flow ALONE does not select** (lift −0.21 to −0.31). In this aggregation (pre/early window
   imbalance/aggression/impact) it carries no scalp-selection signal.
4. **Conclusion:** the scalp's edge lives in the **entry filter (cheap vwap) + exit timing**, NOT in
   slug-selection from TA indicators or coarse CLOB flow. The CLOB tape's value (if any) is likely a
   DIFFERENT target (e.g. pre-window informed-flow for a slug-SELECTION-before-window play, or finer
   trade-sequence features), not scalp-PnL selection.

## The harness is the deliverable — it is READY TO START
- `python strategy_lab/autoresearch/run.py` scores the current `candidate.py`, logs to `history.jsonl`,
  and reports NEW BEST / KEEP conditions. An agent (or an overnight loop on the RTX 3060) edits `candidate.py`
  per `program.md` and iterates. The fitness already enforces: PnL-after-fee label, time-lockbox, CI>0,
  asset-confound penalty — so the agent CANNOT win by rediscovering the priced-in trap or a BTC-only gate.

## Next experiments for the loop (queued in program.md)
- Finer CLOB features (trade-sequence/Hawkes on the tape; first-N-trades only; large-trade timing).
- A DIFFERENT target: pre-window slug-SELECTION (which slugs will reprice big) decoupled from the scalp.
- Per-asset models (kill the confound by construction).
- Oracle-basis features (Binance-spot × cex_futures-perp) when futures data matures (~2 wk).
- Swap fire universe to momo/sniper to test exit-scalp generalization (W2).

## Files
`strategy_lab/autoresearch/{build_indicator_panel,build_clob_flow,build_master_features,seed_candidates,
fitness,candidate,run}.py`, `program.md`, `_data/{indicators_*,clob_flow,master_features,feature_groups,
seed_results}.*`.
