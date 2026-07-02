# Sum-Pair V2 — Depth-Realism + Residual-Exit results (2026-06-14, completed 2026-06-16)

Finishes the open Next-Step #1 from `SUMPAIR_SIGNAL_GATED_2026_06_13.md`: does the V2 oscillation-harvest
edge survive a REALISTIC L25 fill (full 25-level ladder, per-level carry-forward, **no size==0→DEEP**),
or was the +2.24/slug headline a pure infinite-refill artifact? Script `_sumpair_v2_depth_realism.py`;
data `_results/sumpair_v2_depth_realism_2026_06_14.parquet` (201,725 rows) + `..._markout_2026_06_14.parquet`.
OOS = slot_start ≥ 2026-05-21; BTC/ETH/SOL **5m only**; THR=3bp; $5 clips; bar-END causal; +85ms fill;
winner-only 0.07 fee; true chainlink resolution.

## Headline: the +2.24 was NOT mostly a refill artifact — real L25 depth supports it
- **Real (non-artifact) depth per fire snapshot: Up 9.06 clips, Down 8.67 clips** (× $5 ≈ **$45/side per
  snapshot**). The engine actually fires **~2.4 clips/side** (p50=2, p90=5, p99=10). So the clips taken sit
  comfortably inside the genuine displayed depth — the old `entry_fill`/DEEP infinite-refill assumption
  rarely bound, which is why the realistic walk reproduces the headline rather than collapsing it.

## Net/slug vs max-clips (realistic ladder, OOS, fired slugs, n=7,814)
| max clips | ARM A (hold residual) | ARM B (scalp residual @+60s) |
|---|---|---|
| **1** | **+0.638** [+0.416,+0.867] t=5.6 | **+0.401** [+0.258,+0.551] |
| 2 | +1.093 [+0.724,+1.470] | +0.866 [+0.624,+1.120] |
| 4 | +1.752 [+1.185,+2.383] | +1.371 [+1.017,+1.731] |
| 8 | +2.297 [+1.536,+3.095] | +1.724 [+1.267,+2.196] |
| **unlim** | **+2.449** [+1.635,+3.305] t=5.7 | **+1.767** [+1.282,+2.272] |

**Every cell CI>0.** The edge scales monotonically with clips because the real book has the depth — the
1-clip +0.52/+0.64 was an *artificially conservative floor* (it discarded clips 2–10 the real ladder
genuinely supported), NOT the honest number.

## TWO findings that refine the prior report
1. **HOLD vs SCALP residual — it's a MEAN-vs-DISTRIBUTION tradeoff, and SCALP wins for deployment.**
   HOLD (ARM A) has the higher *mean* (+0.64 / +2.45) but a **brutal distribution: median −$5.00, only
   36–38% of slugs positive** — 74% of fired slugs are single-leg (no pair completes), and holding a lone
   losing clip to resolution = −$5. The mean is entirely tail-driven by the ~26% both-fill matched pairs +
   rare directional winners. **SCALP-residual (ARM B) — sell the unmatched leg at +60s — lifts the median
   from −$5.00 to −$0.35 (1-clip) / −$0.79 (unlim) and the win-rate 38%→44%**, capping single-leg losers at
   ~−$0.5 instead of −$5, for a modest mean cost (+0.64→+0.40 / +2.45→+1.77, both still CI>0). This
   **RESOLVES the 2026-06-15 `_upside` open question** ("scalp-exit fix for the −$5 median NOT yet
   backtested → measure live"): scalp-exit fixes the median *offline*. **Deploy SCALP-residual, not HOLD** —
   the matched-pair locked component is the edge; the single-leg residual is a drag scalp-exit minimizes.
2. **Per-coin (ARM B, OOS): BTC strong, ETH solid, SOL marginal.**
   - BTC: 1-clip +0.912 (t=5.5) · unlim +3.317 (t=6.3) — CI>0 both.
   - ETH: 1-clip +0.412 (t=3.1) · unlim +2.226 (t=5.2) — CI>0 both.
   - SOL: 1-clip +0.117 (t=1.1, **straddles 0**) · unlim +0.595 (**straddles 0**) — **drop SOL.**
   (ARM A is ~+0.24/clip higher per the drag, so BTC/ETH ARM A unlim are ~+3.6/+2.5.)

## Markout (independent 300-clip sample, causal): lag is real
mean +1.92¢@1s / +3.66¢@5s / +2.50¢@30s (cheap ask RISES after fill = genuine Binance-lag, opposite of
the sub-100ms revert that killed the taker arb). Caveat: **medians ≈0 and the +30s CI straddles 0
[−0.65,+5.63]** — the positive mean is tail-driven, so the lag is real but noisy per-clip.

## VERDICT — edge SURVIVES depth realism; deploy SCALP-residual; band + the one remaining caveat
- **Deployable config = ARM B (scalp residual).** Hard floor (no liquidity-regeneration assumption):
  **+0.40/slug (1-clip), CI [+0.26,+0.55]**, median −$0.35, 44% win. Realistic multi-clip (real per-snapshot
  depth): **up to +1.77/slug unlim, CI>0** (BTC +3.32 / ETH +2.23 / SOL +0.60-straddle). ARM A (hold) has a
  higher mean (+0.64 → +2.45) but median −$5 / 36–38% win = untradeable variance — the mean is the EV
  *ceiling*, not the deployable number.
- **THE remaining realism gap:** the walk evaluates each 5s-spaced fire's snapshot *independently* — it
  confirms the book *displays* ~9 clips/snapshot, but does NOT model whether *your own* repeated lifting
  of the lagging quote exhausts that liquidity (L25 has no order-by-order/queue tracking; per-level carry
  can re-count displayed size across snapshots). So the multi-clip magnitude assumes inter-fire liquidity
  *regeneration* — the **same live-only question** that gates the taker arb and b945 maker. The 1-clip
  +0.64 needs no such assumption.

### Deployable config (per the surviving edge)
- BTC/ETH 5m only (drop SOL — straddles 0 — and 15m); per-side causal bar-END `|ret|≥3bp` lag dip;
  `ev<0.55`; +85ms fill; $5 clips.
- **Pair `min(sh_up,sh_dn)` held to chainlink; SCALP the unmatched residual at +60s (ARM B)** — this
  caps the single-leg losers (median −$5→−$0.35, win 38%→44%) for a tradeable distribution. Do NOT hold
  the residual directionally (higher mean but median −$5 / 62% lose).
- Cap clips conservatively (1) until live confirms inter-fire depth regeneration; expect +0.40 (1-clip,
  hard floor, CI>0) → ~+1.8 (multi-clip ARM B, if depth regenerates) per slug.

### Next step (do NOT deploy capital on the multi-clip magnitude yet)
1. **Live shadow on BTC/ETH 5m**, $5 clips, HOLD-residual, ≥200 fires — the live wallet is the only
   arbiter of the inter-fire regeneration question (judge by live CI, not backtest; the scalp's OOS window
   is burned). The 1-clip floor (+0.64) is the safe paper-to-live anchor.
2. This is the **directional cousin of the deployed +60s scalp** (same lag signal, different exit:
   accumulate + pair-hold vs sell). It BEATS the scalp on the headline (+1.95 paired) — so it competes
   with, not adds to, the live scalp wallet; run them as an A/B, not stacked, until the live CI separates.

**Bottom line:** the operator was right and the conservative 1-clip report under-sold the EV — the multi-clip
edge is backed by *real* L25 depth (~9 clips/snapshot), not infinite-refill. BUT the deployable form is
**SCALP-residual (ARM B), not hold**: holding has a higher mean but an untradeable median −$5 / 62%-lose
distribution; scalping the unmatched leg at +60s fixes the median (−$5→−$0.35) for a tradeable +0.40/slug
(1-clip, CI>0) to ~+1.8 (multi-clip) edge, BTC/ETH 5m. The matched-pair (~26% of fires) is the real
profit core; the single-leg residual (74%) is a drag scalp-exit minimizes. Only open question = inter-fire
liquidity regeneration (does the lagging quote refill after you lift it) — live shadow only.
