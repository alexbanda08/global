# Overnight massive search + OOS-on-different-window protocol — 2026-06-03

## What's running
`strategy_lab/autoresearch/search_overnight.py 8` — an 8-hour search (~**11.6 candidates/s ≈ 330k overnight**,
10 cores), random over feature-subsets × {xgb,rf,et,logit} × filters × exit-times × depths. Selection metric =
**purged 4-fold CV gated $/tr** (robust = mean − 0.5·std − confound penalty) on the current 38-day window.
Checkpoints `_data/overnight/{status.json, top_checkpoint.parquet}` every 3 min; writes top-50
`finalists.json` at the end. Resumable.

## ⭐ The decisive finding (from the permutation null) — read this
Before searching, the script calibrates a **permutation null**: same procedure on **shuffled labels (zero
signal)**. Result, stable across runs:

> **null robust gated-$/tr: p95 ≈ 3.4–3.7, max ≈ 4.6–5.3**

The all-take baseline is ~+3.48/tr and the best "edge" candidates we ever found were ~+3.9. **The no-signal
noise floor of this metric already equals/exceeds every candidate's score.** On n≈195 lockbox trades, gating a
favorable subset yields +3 to +5 $/tr *by pure chance*. Therefore:
- **Any slug-selection "edge" at this data size is statistically indistinguishable from noise.**
- **Searching more candidates makes it WORSE, not better** — the max-under-null grows with the number of tries,
  so the apparent best inflates without any real signal (800-run: 5/19 "survive"; 3000-run: 2/17; both ≈ the
  noise floor). This quantifies, rigorously, why "search millions and pick the best" is a trap here.
- **The binding constraint is statistical power (n), not search breadth or feature richness.** Lowering the
  noise floor requires MORE DATA (bigger independent test set), full stop.

## Therefore the ONLY valid path = confirm on a DIFFERENT window (your plan, exactly)
The search/selection is in-sample to the 38-day window no matter how clever. The single source of truth is an
**independent window the search never touched**. `validate_oos.py` implements this:
- trains each finalist on the FULL current window, gates the OOS window, scalp $/tr + bootstrap CI,
  Bonferroni over the 50 finalists, with the pre-registered **rank-1** reported separately (a single
  pre-committed test needs no correction).

### Your two options — honest assessment
1. **"Wait 5 days" → NO.** Workhorse scalp sleeves fire ~3–4/day → 5 days ≈ 15–20 fires. Statistically useless
   (the noise floor needs *hundreds*+ of OOS fires). You'd need months of live accrual.
2. **6-month API on a different window → YES, the right move — with one hard requirement.** It must serve the
   data the scalp actually needs for that window:
   - **L25 order-book history** (to compute the entry fill + the bid-exit path) — *mandatory for the scalp*.
   - **CLOB trade tape** (for the flow features).
   - **klines** (for the TA indicators) + **chainlink** (physics).
   If the API gives **only price klines**, it can validate *direction/regime* models but **cannot validate the
   scalp** (no book = no fills). Tell me the API's actual payload and I'll wire the OOS feature build to it.

### How to run the OOS confirmation when the data lands
1. Rebuild the feature matrix on the new window: re-run `build_indicator_panel.py` (its klines),
   `build_clob_flow.py` (its trades), and a scalp-fill cache (its L25 books) → `oos_master_features.parquet`.
2. `python validate_oos.py <oos_master_features.parquet>` → prints per-finalist OOS $/tr + CI + survivors.
3. **Bar:** a candidate is real only if rank-1 survives, OR a survivor's OOS gated-CI clears 0 with a wide
   margin (a barely-positive CI among 50 = noise). If none survive → slug-selection is confirmed dead and the
   edge is the scalp's entry+exit, period.

## Expectation (honest)
Given the in-sample null floor, the most likely OOS outcome is **0 survivors** — i.e. the overnight search,
however large, finds no slug-selector that transfers. That would be a *valuable, conclusive* negative: it
redirects all effort to (a) the proven exit-scalp + its ML exit, and (b) getting MORE DATA so future searches
have the power to detect small edges. If a finalist *does* survive a clean 6-month different-window test, it is
genuinely real and worth a shadow sleeve.

## Files
`autoresearch/search_overnight.py` (running), `validate_oos.py` (ready), `_data/overnight/{status.json,
top_checkpoint.parquet,finalists.json}`. Monitor: `cat _data/overnight/status.json`.
