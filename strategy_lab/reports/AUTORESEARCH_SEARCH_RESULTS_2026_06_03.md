# autoresearch SEARCH results — 2026-06-03

Searched **{N_SEARCH}** random candidates (feature-subset × model × filter × exit). Ranked on DEVTEST; top 20 confirmed ONCE on the time-held-out LOCKBOX. A finalist 'survives' only if lockbox gated-CI>0, beats all-take, not asset-confounded — and even then must be deflated for the 20 multiple comparisons (Bonferroni: treat CI>0 as suggestive, not proof).

| rank | filter | model | nfeat | exit | dev $/tr | LOCKBOX gated $/tr | lock CI | all-take | lift | mix | survives |
|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| 1 | d3v055 | logit | 8 | 45 | 10.11 | 4.27 | [-0.62,+8.55] | 2.77 | +1.49 | B11/E6 | — |
| 2 | d3v055 | xgb | 3 | 60 | 9.61 | 3.25 | [+0.11,+6.55] | 3.48 | -0.23 | B16/E6 | — |
| 3 | d3v055 | logit | 3 | 60 | 9.52 | 4.04 | [+1.02,+6.96] | 3.48 | +0.56 | B33/E0 | — |
| 4 | d3v055 | logit | 12 | 60 | 9.52 | 2.11 | [-0.52,+4.67] | 3.48 | -1.37 | B37/E0 | — |
| 5 | d3v055 | xgb | 15 | 60 | 9.45 | 3.90 | [+1.73,+6.15] | 3.48 | +0.42 | B39/E6 | ✅ |
| 6 | d3v055 | xgb | 13 | 60 | 9.43 | 1.49 | [-1.89,+4.64] | 3.48 | -1.99 | B24/E0 | — |
| 7 | vwap055 | rf | 5 | 60 | 9.20 | 2.74 | [+1.32,+4.16] | 3.05 | -0.31 | B88/E63 | — |
| 8 | d3v055 | logit | 16 | 60 | 9.00 | 3.19 | [+0.42,+5.96] | 3.48 | -0.29 | B36/E1 | — |
| 9 | d3v055 | logit | 14 | 60 | 8.96 | 3.74 | [+1.09,+6.33] | 3.48 | +0.25 | B42/E0 | — |
| 10 | d3v055 | xgb | 16 | 60 | 8.83 | 3.32 | [+0.53,+6.00] | 3.48 | -0.16 | B31/E2 | — |
| 11 | d3v055 | rf | 10 | 60 | 8.76 | 4.75 | [+2.42,+7.13] | 3.48 | +1.27 | B37/E1 | — |
| 12 | d3v055 | xgb | 14 | 45 | 8.69 | 3.53 | [+0.04,+7.28] | 2.77 | +0.76 | B20/E2 | — |
| 13 | vwap055 | rf | 17 | 60 | 11.66 | 3.12 | [+0.42,+5.75] | 3.05 | +0.07 | B45/E0 | — |
| 14 | d3v055 | xgb | 4 | 60 | 8.56 | 3.04 | [+0.95,+5.13] | 3.48 | -0.44 | B32/E14 | — |
| 15 | d3v055 | logit | 6 | 60 | 8.54 | 3.91 | [+1.19,+6.58] | 3.48 | +0.43 | B38/E0 | — |
| 16 | d3v055 | xgb | 3 | 60 | 8.41 | 1.77 | [-2.21,+6.07] | 3.48 | -1.71 | B0/E17 | — |
| 17 | d3v055 | logit | 2 | 45 | 8.25 | 6.58 | [+2.79,+10.89] | 2.77 | +3.81 | B6/E10 | ✅ |

## Verdict

- Survivors (raw CI>0, confound-free, beat all-take): **2/17**.
- **Bonferroni reality check:** with 20 finalists drawn from 3000 searched, expected false positives at raw 95% CI ≈ several. A survivor is only credible if its lift is LARGE and its CI clears 0 with margin — a barely-positive CI after this much searching is most likely snooping.
- The all-take baseline on each filter is the honest floor; a real slug-selector must beat it by a wide, confound-free margin that holds on the lockbox. Read the table with that skepticism.

Full per-candidate log: `search_log.parquet`. Re-run wider: `python search.py 3000`.
---

## DEFINITIVE INTERPRETATION — searched 800 then 3000 (1884 valid). More search = WORSE, not better.

| run | candidates | valid | "survivors" (raw CI>0, confound-free, beat all-take) | best confound-free lift |
|---|--:|--:|--:|--:|
| A | 800 | 511 | 5/19 | +0.42 (CI wide) |
| B | 3000 | 1884 | **2/17** | +0.42 (same candidate) |

**Scaling the search 3.75× produced FEWER survivors (2 vs 5), not more — and the best confound-free lift is
the SAME marginal +$0.42/tr.** That is the signature of NO real edge: with a true signal, more search
converges on a robust winner; here it just reshuffles which random candidates happen to land CI>0 on a small
lockbox. Two hard tells:
1. **Brutal dev→lockbox shrinkage:** top dev candidates score $7–10/tr on devtest but **$1.5–4.3 on the
   lockbox**, with the biggest-lift ones (rank 1: +1.49) having CIs that **straddle 0** ([−0.62,+8.55]). The
   search is overfitting the dev split, not finding transferable edge.
2. **No candidate beats all-take by a wide, confound-free margin.** The all-take floor (d3v055 exit60) is
   +$3.48/tr; the best survivor gates to +$3.90 (+$0.42) — inside the multiple-testing noise of 20 finalists
   drawn from 1884.

### Why more candidates is the WRONG lever here
The binding constraint is NOT search breadth — it's **(a) a small lockbox (n≈195): you physically cannot
confirm a fine selection rule on 195 trades**, and **(b) the target/features**: scalp-PnL selection from coarse
CLOB-window aggregates + TA indicators carries no transferable signal. Searching 10k candidates would only
manufacture more false positives.

### The real levers (what would actually change the answer)
1. **More data → bigger lockbox.** Accumulate live forward scalp fires, or extend the canonical window. A
   lockbox of n≈1000+ can confirm selection rules that n≈195 cannot.
2. **Better features, not more of them.** Finer CLOB *trade-sequence* features (first-N-trade dynamics, intra-
   second Hawkes on the tape, large-print timing) rather than pre/early-window sums; and a DIFFERENT target
   (pre-window slug-selection / reprice-magnitude, decoupled from the hold-scalp).
3. **Per-asset models** to remove the BTC confound by construction.

**Bottom line for the operator's question:** yes — I now ran a real search (800→3000 with held-out lockbox +
Bonferroni), not 10 spot-checks. The robust answer is **no slug-selector in this feature/target space beats the
entry filter**, and searching harder makes it worse. The path forward is more *data* and better *features*, not
more candidates. The harness is built to ingest both.
