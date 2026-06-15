# New-Edge Research Push — same-slug merge + regime gates (2026-06-08)

**Goal (operator):** analyze everything tried, merge same-slug strategies for more alpha, bring more indicators
for regime/new edges. **Method:** mapped first (STRATEGY_MAP) to avoid re-running dead ends, then two threads —
(A) same-slug merge, (B) regime gates — both built on SURVIVING edges (NOT a new directional predictor, which
the map proves is dead). Scripts: `directional/{maker_exit_by_tf, scalp_regime_gate, sniper_regime_gate}_2026_06_08.py`,
agents pulled vps3 deduped-dashboard-metric data.

## Headline
**One deployable finding: ETH `cloud_vwap_hurstmp` gated on `ema50_hurst_grandparent` agreement (same slug+dir) =
+$0.62/tr (t=2.27, n=183) vs +0.33 solo (+88%).** Both threads independently converge on the ETH Hurst pair as the
current best non-scalp edge. Everything else = null / n-inflation / cross-venue-harmful — the expected result.

## Thread A — same-slug merge (corrected dedup metric)
| merge | result | verdict |
|---|---|---|
| ETH `cloud_vwap_hurstmp` ∧ `ema50_hurst_grandparent` agree | +0.33→+0.62/tr (+88%), t=2.27, n=183 | ✅ DEPLOY (shadow A/B) |
| BTC 15m `ema50_ema800` ∧ `_H` | +6% $/tr, t drops 2.12→1.86 | skip (n-cost) |
| AND-2+ across 7 EDGE sleeves | $/tr falls; t-gain = n-inflation only | skip (artifact) |
| **cross-venue Poly ∧ Kalshi same event** | co-fire HURTS Poly: +0.29 vs +1.10 solo | ❌ do NOT gate Poly on Kalshi (agreement is structural/DOWN-only, not informational) — corrects earlier claim |
| scalp × sniper co-fire | n=4–11 | inconclusive |
Caveat: the ETH pair is two Hurst-based signals (correlated) → the AND may just be a tighter single filter. A/B it.

## Thread B — regime gates (DSR-disciplined: terciles + bootstrap CI + train/test)
### B-1 exit-scalp (1303 gated OOS fires, baseline +0.93/tr)
- realized vol: LOW +1.28 / MID +0.84 / HIGH +0.67 → weak "edge shrinks in high vol" lean (hiVol underperforms on both splits) but redundant with delta.
- |trend|: non-monotonic (MID best), fails split.
- **delta_bps** (existing sizer): monotonic +0.24/+1.07/+1.48, **only feature holding train/test** (TRAIN +1.09, TEST +1.64) → re-confirms delta is the sufficient statistic.
- session: 22–02 +1.95, dead{12,17} +0.51 → TOD gate re-confirmed (control).
- **Verdict: NO new regime gate beats delta+TOD.** Scalp already fully characterized.

### B-2 EDGE trend-continuation snipers + NEW indicators funding_rate / OI (baseline +0.22/tr, t=2.01)
- funding tercile / OI-change / realized-vol: all non-monotonic, CI cross 0 → null.
- **funding>0 × DOWN sleeves: +0.34/tr (t=2.20, n=554)** — economic sense (crowded longs fuel down-continuation),
  BUT fails OOS split (TRAIN +0.32 → TEST +0.18 ns). UNDERPOWERED: only ~4 days futures overlap, funding 8h-coarse.
- Per-sleeve (recent): BTC `ema50_ema800` now FLAT (+0.03); SOL `j_2asset` NEGATIVE (−0.12); only ETH hurst/cloud positive.
- **Verdict: no robust new-indicator gate yet.** funding>0/DOWN deserves a powered re-test once cex_futures refreshed past Jun4.

## Per-timeframe scalp exit config (companion finding, `SCALP_EXIT_CONFIG_BY_TF_2026_06_08`-equivalent earlier)
5m: pure taker+60 + KEEP stop (+0.88 SIG); 15m: maker@0.60+fallback + stop (combo +1.08). Kalshi: taker, stop unproven (n=15).

## Kalshi scalp port — CLOSED (structural)
Live probe loses 7/10 because Kalshi lists the 15m market only ~+30s after open (measured live: +31.6s) and it opens
already-priced-fair. Edge is open-only (mid-window lag = null, tested 2 ways). Kalshi can't access the open. Not a config fix.

## Metric correction banked (memory)
Rank sleeves on the TV dashboard DEDUP metric, NOT raw events.pnl_usd (double-counts phantom legacy resolver rows +
includes synthetic fills). Proof: lagv2 +$1681 raw → −$195 deduped. See `[[project_sleeve_pnl_metric]]`.

## Next steps
1. **Shadow A/B the ETH cloud∧hurst AND-gate** (only deployable merge); confirm it beats cloud-solo over more fires + isn't just a tighter single filter.
2. **Refresh cex_futures past Jun4**, re-test funding>0/DOWN gate with power (the one new-indicator signal with an economic story).
3. Demote/watch: BTC `ema50_ema800` (flat recently), SOL `j_2asset` (negative recently) — the prior "EDGE" set is decaying.
4. Funding/OI regime on the SCALP can't be tested until futures overlaps the scalp window (different epoch).
5. STRATEGY_MAP update pending (this push + the week's scalp-OOS/Kalshi/maker-exit findings).
