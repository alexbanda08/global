---
name: project_5lens_audit_2026_06_12
description: "2026-06-12 five-lens strategy audit — scalp fee proxy unverified (0.015 vs up to 0.07, $0.15-1.50/tr inflation bound), 1s bar-start asof lookahead in all scalp drivers, magnitudes in-sample, action order in report"
metadata: 
  node_type: memory
  type: project
  originSessionId: 95da9a9e-f870-4e84-8fd8-e3dfce1d3760
---

Full 5-agent audit (harness/stats/live/data/edges) banked in `strategy_lab/reports/STRATEGY_AUDIT_5LENS_2026_06_12.md`. Top findings:

1. **Scalp exit-fee proxy (0.015 in `bpnl`) is UNVERIFIED vs live** — true sell-leg fee bound $0.15–1.50/tr inflation on a +1.85/tr claim. Ground-truth from actual Ireland live sell fills FIRST; everything downstream.
2. **~1s lookahead**: every scalp driver's local `asof` searchsorts bar-START (`time_period_start_us`) → numerator close at ss+6 vs fire at ss+5. Direction 99.5% intact but 29.5% of fires are a hindsight-selected slot set. Fix = end-time asof everywhere.
3. Magnitudes in-sample (burned window): direction HIGH / magnitude LOW (~⅓). momalign "OOS" = tail-split, not disjoint. cloud_vwap_v7 fails Bonferroni at N=25 and N=155 (t=2.32). Only ~18–21 live fires, partly wrong config.
4. OOS resolutions never Chainlink-cross-checked (zero slug overlap hf↔rtds) — backfill-layer-internal only.
5. iid bootstrap overstates all CIs — use slug-block bootstrap.
6. The only honest OOS left = **Feb21–Mar24 L25 window, one pre-registered shot** with corrected fee + causal asof + block bootstrap.
7. Top missed edge = **Poly×Kalshi dip-arb EXECUTION** (validated both signal+depth, blocker operational only); free test = Binance 1s taker-OFI entry gate (cols never extracted).

**RESOLVED EMPIRICALLY 2026-06-12** (`scalp_causal_asof_oneshot_2026_06_12.py`, log in _results/):
- 1s-lookahead is REAL + was NEVER fixed (even the 06-10 "fixed" driver uses start-time asof on klines_1s; `time_period_start_us`=bar OPEN, close at start+1s → numerator close lands ~0.9s AFTER the fire). Schema-probe-confirmed.
- Paired leaky-vs-causal: pooled gated ev<0.55 drops **+1.714/tr → +1.015/tr (−41%)** but **causal CI STILL >0** (t=2.92, CI[+0.32,+1.69]). Edge survives; backtest magnitude was inflated ~41% via hindsight slug/direction SELECTION (lead-flips only 1.3%; paired same-fire diff ≈0).
- **Fee point CORRECTED:** operator right — hold fee is winner-only 0.07, $0 on losers (already in held_value/hold_pnl). Auditor's $0.55-1.50/tr fee claim conflated that with the sell-leg; irrelevant to this result (both arms same bpnl).
- **Feb21-Mar24 OOS is IMPOSSIBLE:** both L25-backfill AND trades_hf start ~80s into each slot (recorder late; 0 pre-slot prints in 880k trades) → no book to fill a +5s entry. That recommendation was wrong.
- **LIVE was never affected** (production anchors signal causally on ws_s closes) → live shadow IS the unbiased truth (~+$1/tr expected), reinforces judge-by-live n≥200.

**How to apply:** patch every scalp driver's `unified_1s`/`asof` to END-time (close known at-or-before fire) before any new backtest; trust live over backtest. The only true OOS left = live forward fires. Links: [[project_retro_audit_findings]], [[project_scalp_exit_config]].
