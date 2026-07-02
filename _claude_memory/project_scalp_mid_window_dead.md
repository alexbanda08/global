---
name: project-scalp-mid-window-dead
description: "Mid-window/FVG/cross-asset scalp variants all tested dead — edge is open-only; don't re-scaffold"
metadata: 
  node_type: memory
  type: project
  originSessionId: 690d6e2e-46dc-4eba-b110-0dd17c063f63
---

The intra-window exit-scalp edge is **structurally open-only (~first 5–35 s)**. As of 2026-06-09, every
generalization away from the window-open lag-taker was tested and DIED under proper controls:

- **Mid-window re-fire** (same lag signal at offsets ≥120 s): flat/negative (pooled off≥120 = +$0.25/tr t=0.38).
- **Fair-value-gap (FVG) continuous entry** (binance driftless-digital `Φ(ln(price/strike)/(σ√τ))` vs poly mid):
  recovers the open edge only; **mid-window it is an ANTI-signal** (first-cross-among-mid offsets t = −4 to −6).
- **Cross-asset lead-lag** (BTC leads ETH/SOL): paired diff(BTC−OWN) = −0.04, CI[−0.12,0]; `sign(BTC)≠sign(own)`
  only 4.8% of fires → leader adds nothing. BTCLEAD (own-flat, bet-it-follows) is negative.
- **Regime gates** (vol/trend terciles): nothing beats `delta_bps`.
- **Tick-level trailing/peg exit** (the flagged future-work): every realizable trailing stop LOSES to fixed +60
  on both 5 s and 1 s grids (paired −$1.8 to −$7); oracle peak (~+$17) is a transient spike, genuinely untradeable.
  **Fixed +60 is robustly optimal; exit refinement is closed.**
- **Entry-offset + delta-band knobs:** +5 s is the robust plateau (+1 s spike is non-robust); δ≥5 ≈ 2× $/tr of
  δ≥3 (reconfirms the sizer). No new knob — deployed operating point is right.
- **Same-venue two-sided arb** (`up_ask+dn_ask<1`): efficiently priced (book overround ~1.02; sub-1 cases are
  zero-size dust). No arb.
- **Low-vol gate (proper OOS):** coin-inconsistent — holds on a time-split but FAILS the coin-split; on BTC+ETH
  (deployed coins) low-vol is *worse* than baseline. Monitor, not a gate.

**Why mid-window fails:** by ≥120 s the poly book has fully absorbed the binance level; a residual gap is stale-σ or
correctly-priced mean-reversion, not a lag. **The open exit-scalp is the ONLY edge and is fully optimized. The
existing-data scalp space is efficient — stop researching it; new edges need NEW data** (Kalshi ask-depth for the
deep-dip Poly×Kalshi arb, the Poly CLOB WS trade tape, or accrued futures funding/OI). The bottleneck is
operational (ship disable-TP/stop + maker-exit A/B; accumulate ≥200 live forward fires).
Report: `strategy_lab/reports/SCALP_NEW_EDGE_HUNT_2026_06_09.md`. Related: [[project-scalp-exit-config]].
