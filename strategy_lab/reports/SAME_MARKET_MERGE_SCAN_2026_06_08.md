# Same-market merge scan (proper, corrected dedup metric) — 2026-06-08

**Goal:** find any mergeable uplift among currently-running sleeves that fire on the SAME market — does requiring
agreement raise $/tr? **Verdict: NO deployable merge.** Agreement is priced-in; the only "SIG+" pairs are artifacts.
**Script:** `strategy_lab/directional/same_market_merge_scan_2026_06_08.py` · data `_results/fleet_cofire_12d.csv`.

## Method (the PROPER metric — the loose version is what gave the false ETH +0.62)
- One deduped row per (sleeve, market): **pnl from the resolution row, signal from the fire row**, deduped to ONE
  per (sleeve, condition_id) preferring the real fill, NOT the phantom legacy resolver (~60s later, inflated pnl).
- True market outcome recovered per cid from any row (`sig=UP & won` ⇒ UP, etc.).
- $/tr only comparable within same notional → consensus/pairwise restricted to the **$5 sniper_v5 fleet**.
- 12-day window, 21,413 directional fires, 8,153 markets, 151 sleeves.

## Consensus voting (sniper_v5, 3,329 markets with a majority direction)
| agreeing sleeves k | n | $/tr | WR |
|---|---|---|---|
| k=1 (lone) | 1046 | −0.15 | 0.65 |
| k=2–3 | 1433 | +0.07 | 0.61 |
| k=4–6 | 666 | +0.06 | 0.61 |
| k≥7 | 184 | +0.02 | 0.62 |
**$/tr does NOT rise with k; WR flat.** Agreement is priced-in → no consensus alpha. Mild: lone fires slightly
negative, any 2nd confirmation → ~+0.06 flat (a weak "don't fire alone" filter, too thin to deploy).

## Pairwise uplift (49 positive sniper_v5 pairs, n_agree≥30) — only 2 "SIG+", both SUSPECT
| pair | n | agree $/tr | t | uplift vs best solo | verdict |
|---|---|---|---|---|---|
| eth cloud_vwap_hurstmp + eth ema50_hurst_parent15mrang_v7 | 128 | +0.69 | 1.97 | +0.46 | borderline t; both ETH-Hurst (correlated) → same fragile class as the INVALID grandparent merge |
| btc imb5_rf_v8 + imb5_ribbon_v8 | 432 | +0.57 | 2.56 | +0.20 | ❌ the RF UP-bias bug — two copies of one biased signal; artifact (`RF_GATE_UP_BIAS_AUDIT_2026_06_08`) |

## Verdict
**No real mergeable uplift across the running fleet.** Consensus = flat (priced-in). Pairwise = only RF-bug-duplicate
and correlated-borderline ETH-Hurst pairs — neither an independent-signal conviction merge. This is the expected
result given the meta-truth (no reproducible directional edge to amplify). Combining same-market sleeves does not
create alpha; it mostly shrinks n.

## Caveats / metric notes
- **fast_taker (lagv2) $/tr in the SOLO printout is CONTAMINATED** (+$9–15/tr shown) — their real fills log with
  `fill_method` NULL while the phantom legacy row has it set, so the "prefer fm-not-null" dedup mis-picks the
  phantom. Dashboard truth for lagv2 is **−$0.31/tr** (verified directly). fast_taker excluded from conclusions.
  This is a 3rd manifestation of the events-PnL phantom-row fragility (see `[[project_sleeve_pnl_metric]]`).
- Consensus/pairwise use sniper_v5 (l25_walk fills, fm-not-null = real) → those numbers are clean.
- Related: `TV_AGENT_SPEC_ETH_MERGE_HURST_2026_06_08.md` (INVALID), `RF_GATE_UP_BIAS_AUDIT_2026_06_08.md`,
  `NEW_EDGE_RESEARCH_2026_06_08.md`.
