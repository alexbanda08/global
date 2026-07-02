---
name: project_scalp_exit_config
description: "FINAL scalp exit config (2026-06-11): PURE +60s time sell — TP OFF, STOP OFF (removed both hosts; old +0.88 stop claim was a harness artifact). Maker-exit also dead. Entry unchanged."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9be1f863-0eda-42c2-be82-3471b9558d8d
---

The exit-scalp's validated/deployed exit config (Ireland live + VPS3 shadow), correct as of
2026-06-08:
- **Take-profit: OFF** — taker-TP@0.65 leaks edge (caps runners), lookahead-confirmed
  (`SCALP_DYNAMIC_EXIT_2026_06_04`).
- **Stop@(fill_vwap−0.10): ON — KEEP IT.** It is the single biggest edge-ADD: **+0.88/tr
  SIG on 5m** (pure taker+60 +2.91 → +STOP +3.79), per the authoritative test
  `SCALP_EXIT_CONFIG_BY_TF_2026_06_06` (`maker_exit_by_tf_2026_06_06.py`, n=780, paired
  bootstrap). Triggers ~27%, caps losers that would otherwise decay to bid_60.
- **Exit time = +60s** (+45/+60 statistically tied, +60 = argmax-mean).
- **15m: maker_fixed@0.60 + taker-+60 fallback** (validated 15m winner); **5m stays taker**.

🚨 The doc `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06` ("disable TP AND stop → pure +60") is
**SUPERSEDED / STALE** — it lumped TP+stop; only TP leaks. Do NOT cite it as authority. The
code default `scalp_tp_enabled=False, scalp_stop_enabled=True` (sniper_v5_sleeves.py) is
CORRECT.

Open item = stop MAGNITUDE not direction: +0.88 was on an optimistic stop fill; live =
taker-cross a falling thin book. Stop survives ≤3c slip, dies at 6c. Quantify live stop
slippage. See `SCALP_FWD_FIRES_STATUS_2026_06_08.md`. Related: [[project_kalshi_scalp_deprecated]].

🚨 **2026-06-10 UPDATE — corrected-harness rerun REVERSES the offline stop & maker-exit evidence**
(`BUGFIX_RERUN_RESULTS_2026_06_10.md`, harness bugs fixed: outcome-as-price exit fallback, exit-size
ignored, BBO size==0 artifact phantom-skipping ~40% of entries):
- **STOP paired (ON−OFF): −2.79 ALL / −3.15 CLEAN, SIG-NEGATIVE, consistent across BTC+ETH+SOL,
  DOGE+BNB, XRP.** The +0.88 came from the buggy baseline (outcome-fallback marked no-stop losers at
  $0, making the stop look protective). Coheres with the trailing-stop study (all stops negative —
  stops sell temporary dips on noisy binary tokens).
- **Maker-exit (maker−taker60): +0.42 CI>0 → −0.073 ns (CLEAN +0.32 ns).** False positive, dead.
- The core open-scalp edge itself SURVIVES STRONGER (pooled gated +1.85 vs old +0.93; per-coin CI>0
  except DOGE weak).
**RESOLVED 2026-06-11 (operator decision): stop REMOVED on ALL scalp sleeves, BOTH hosts** —
Ireland commit `1746efc`, VPS3 `6eaa154f` (`scalp_stop_enabled=False` default + explicit overrides flipped,
engines restarted clean). **FINAL scalp exit config = PURE +60s TIME SELL: TP off, stop off.** Entry config
unchanged (+5s, δ≥3/5, entry_vwap<0.55, spread≤0.05 with the round(spread,4) float-boundary fix, TOD gate).
This equals the original 06-06 "pure +60" spec — the stop detour (06-08/06-09) was the harness bug talking.
The 3× stop confirmations all shared the buggy harness — they were never independent. Do NOT re-enable the
stop or cite +0.88 without NEW live-data evidence.
