# ❌ INVALID (2026-06-08) — DO NOT DEPLOY. The +88%/+0.62/t=2.27 premise was a METRIC ARTIFACT.
> Re-pulled with the correct dashboard dedup metric (pnl from resolution row, signal from fire row, deduped ONCE
> per market): the merged AND-gate is **flat — +$0.007/tr, t=0.02, n=76** (not +0.62/t=2.27). The original number
> came from the merge agent's loose join (no pre-join dedup → phantom legacy rows inflated n 76→183 and the avg).
> Same class of error as lagv2 (+$1681→−$195). **Both parent sleeves stand alone (~+0.33/+0.36 /tr, t≈2.0–2.1);
> the MERGE adds nothing.** See `SAME_MARKET_MERGE_SCAN_2026_06_08.md`. Spec kept for the record only.

---

# TV-AGENT SPEC — ETH merged sleeve: `cloud_vwap_hurstmp` ∧ `ema50_hurst_grandparent` (SHADOW-first A/B) — 2026-06-08

**Type:** new same-slug AND-confirmation sleeve on **Polymarket ETH 5m**, paper/shadow only. **No live-capital flip.**
**Evidence:** `NEW_EDGE_RESEARCH_2026_06_08.md` (Thread A merge). On the corrected dashboard dedup metric, when
`poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7` and `poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8` fire the
**same slug + same direction**, $/tr = **+0.62 (t=2.27, n=183)** vs cloud-solo **+0.33** (n=581) — **+88%**.
Thread B-2 independently confirms the ETH Hurst pair is the only EDGE sniper still clearly positive recently.
**This is a CONVICTION filter, not a new signal** — both legs are Hurst-based (correlated), so the shadow A/B must
prove the AND beats cloud-SOLO by more than a tighter single threshold would. Shadow-first; graduate on live fires.

## What to build

### 1. New gate: `g_sleeve_confirms(sibling_sleeve_id, require_same_direction=True)`
Generalize the existing **Cyclops S7 X1 `sleeve_active`** mechanism (which already gates a sleeve on "another
sleeve also fired this slug"). The gate, evaluated for `(slug, fire_us, candidate_direction)`:
- Looks up the sibling sleeve definition by `sibling_sleeve_id` and **evaluates its full gate-stack** for the
  SAME `slug` at the SAME `fire_us` (same bar context — reuse the per-cycle fire-decision cache the engine already
  builds; do NOT re-fetch books/klines twice).
- Returns **True** iff the sibling's gate-stack passes AND (if `require_same_direction`) the sibling's chosen
  direction == the candidate sleeve's direction. Else **False** (candidate does not fire).
- Implementation note: prefer reusing the engine's existing per-slug per-cycle sleeve-evaluation results (the
  same map Cyclops `sleeve_active` reads) so the sibling is evaluated once per cycle, not re-run per gate.

This keeps BOTH sleeves' real gate-stacks authoritative (we don't re-list / fork their gates) — the merged sleeve
inherits whatever the production `cloud_vwap_hurstmp_v7` and `ema50_hurst_grandparent_v8` gates currently are.

### 2. The merged SHADOW sleeve (paper, $5) — clone of cloud + the confirm gate
```python
SniperV5Sleeve(
    sleeve_id="shadow_sniper_eth_5m_cloud_AND_hurst_v1",
    asset="ETH", tf="5m",
    # inherit cloud_vwap_hurstmp_v7's entry/exit/direction/offset/notional EXACTLY (it is a hold-to-resolution
    # directional sniper — NOT a scalp; do NOT add scalp_exit). Easiest: subclass/copy the existing
    # poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7 definition and append ONE gate:
    notional_usd_override=Decimal("5.0"),        # match the EDGE-sniper shadow notional
    gates=(
        *POLY_SNIPER_V5_ETH_5M_CLOUD_VWAP_HURSTMP_V7.gates,   # cloud's existing gate-stack, unchanged
        GateRef(g_sleeve_confirms,
                (("sibling_sleeve_id","poly_sniper_v5_eth_5m_l_ema50_hurst_grandparent_v8"),
                 ("require_same_direction","true")),
                "g_sleeve_confirms(eth_5m_ema50_hurst_grandparent_v8, same_dir)"),
    ),
)
```
- Direction is taken from cloud's gate-stack (the candidate); the confirm gate enforces the sibling agrees.
- `shadow_` prefix → paper. Same fire-eval cycle as both parents → clean within-fire comparison.

### 3. Control (must run side-by-side)
The control = **cloud SOLO** = the already-deployed `poly_sniper_v5_eth_5m_cloud_vwap_hurstmp_v7` (paper). No new
sleeve needed — it already exists. The A/B is: `cloud_AND_hurst_v1` (subset that fires only on agreement) vs
`cloud_vwap_hurstmp_v7` (all cloud fires). Same engine, same cycle → matched comparison.

## What to log (to settle the open question)
Per fire of `cloud_AND_hurst_v1`: `slug`, `condition_id`, `direction`, whether the sibling confirmed (always True
by construction — log it for audit), `entry_price`, `pnl_usd`, `won`, using the **dashboard dedup metric**
(one resolution row per condition_id, exclude `fill_method='synthetic'`). Compute on the shadow dashboard:
`cloud_AND_hurst_v1` $/tr & t vs `cloud_vwap_hurstmp_v7` $/tr & t on the **matched recent window**.

## Graduation gate (before promoting to live capital)
Promote the AND-sleeve (or switch cloud-solo → AND-gated) to live ONLY after, on **≥150 forward shadow fires**:
1. `cloud_AND_hurst_v1` $/tr **>** `cloud_vwap_hurstmp_v7` $/tr with **bootstrap CI on the paired difference > 0**, AND
2. the uplift is **NOT** reproduced by simply tightening cloud's own primary threshold to match the AND's n
   (run a `cloud_tight_v1` arm = cloud with a stricter single gate calibrated to ~50% fire rate; the AND must beat
   THAT too — else it's just a tighter filter, not real conviction), AND
3. the corrected-metric edge has not decayed (see caveat below).
Until all three: stays paper.

## Caveats (read before deploying)
- **Correlated legs:** cloud_vwap_hurstmp and ema50_hurst_grandparent are both Hurst-based → the AND may be a
  proxy for "stronger Hurst," i.e. a tighter single filter. The `cloud_tight_v1` control (gate #2 above) is the
  decisive test. If AND ≈ tight-solo, do NOT add the merged sleeve — just tighten cloud.
- **The EDGE set is decaying** (`NEW_EDGE_RESEARCH_2026_06_08`): BTC `ema50_ema800` now flat, SOL `j_2asset`
  negative recently. The ETH pair is the survivor — but re-check its corrected full-span $/tr before live; if it's
  also fading, hold.
- **Metric discipline:** judge ONLY on the dashboard dedup metric (raw `events.pnl_usd` double-counts — proven by
  the lagv2 +$1681→−$195 reversal). See `[[project_sleeve_pnl_metric]]`.
- **In-sample n=183:** the +88% is recent-window, not OOS. The shadow A/B IS the forward OOS.

## Files
- Evidence: `NEW_EDGE_RESEARCH_2026_06_08.md` (Thread A). Precedent gate: Cyclops S7 X1 `sleeve_active`
  (`CYCLOPS_CLONE_SPEC_2026_05_16.md`). Metric: `project_sleeve_pnl_metric` (memory) / `sleeves.py` dedup CTE.
