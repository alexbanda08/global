---
name: project-retro-audit-findings
description: "2026-06-10 master retro audit — scalp exit-fallback outcome-leak bug, Mar30-Apr21 OOS burned, E1 repair package is"
metadata: 
  node_type: memory
  type: project
  originSessionId: 690d6e2e-46dc-4eba-b110-0dd17c063f63
---

The 2026-06-10 master retrospective audit (`strategy_lab/reports/RETRO_MASTER_AUDIT_2026_06_10.md` + details in
`reports/_retro_2026_06_10/01..06`) found, across 696 reports / the whole research history:

**🔴 Open bugs affecting the live edge's MAGNITUDE (direction still believed real):**
1. **Outcome-leak in scalp backtest harnesses:** `sell = bid[jx] if valid else (1.0 if won else 0.0)` — missing
   book at exit substitutes the RESOLVED outcome as exit price. In `scalp_oos_bbo_2026_06_05.py:82` and propagated
   to stop/maker-exit scripts. Stop's +0.88/tr magnitude is tainted (trust `_stop_decompose.py` ex-fallback).
2. **Mar30–Apr21 BBO "OOS" window is BURNED** (re-read ≥6× across TOD/maker-exit/FVG/regime/trailing/knob
   studies). It is in-sample now. **UPDATE 2026-06-10: the Feb21–Mar24 "fresh window" hope is DEAD** — the
   +74–150s timing-offset hypothesis was REFUTED by verification (resolutions_hf timing is exactly correct;
   outcome-agreement sweep peaks at 0s); the Feb–Mar L25 books genuinely start ~+75s median into windows, so the
   +5s open-scalp can never be tested there. **No fresh offline OOS window exists; the live ≥200-fire forward test
   is the only true OOS.** Also: BBO `best_bid_size`/`best_ask_size`==0 on ~47% of rows is a COLLECTOR ARTIFACT
   (price-only updates; sized rows show 5-9k shares ≈ 100× order size) — never treat size==0 as real zero depth.
3. Scalp sell-leg ignores `best_bid_size` (entry is size-capped, exit is not) → tail-loss optimistic.
4. engine_v2 `hold_pnl` double-charges the entry fee on LOSERS vs live $0-on-losers (~$0.87/losing trade,
   conservative direction); `min_book_events` silently off pre-2026-05-30.

**E-thread outcomes (all resolved 2026-06-10/11):** E1 ✅ done (corrected harness; core edge stronger; stop+
maker-exit flipped dead, removed from live). E2 ❌ ORACLE SNIPE DEAD as taker (`ORACLE_SNIPE_RESULTS_2026_06_11`):
books quote the z≥2 winner at median ask $1.000; visibly-cheap favorites are adversely selected (WR 76–85% <
93% breakeven); only exploratory thin-book pocket (BNB 5m +1.37 CI>0, ~$14/day capacity). E3 ❌ MAKER DEAD even
WITH rebate (`MAKER_SIM_RESULTS_2026_06_11`): conservative price-through fills = **0.0%** in both shapes
(scalp maker-entry 0/1380; late favored-bid 1/16,376) — there is structurally NO taker-sell flow at-or-below
the bid in those windows; upper-bound fills are toxic (WR −16 to −26pp vs candidates); rebate is tiny
(20% pool, fills-only, ~$0.001–0.002/sh) and never flips it. **Do NOT re-open maker-entry/late-maker-bid on
"but the rebate" grounds — the rebate WAS modeled.** Wang calibration (52M trades): markets ~perfectly
calibrated (≤1.5¢); λ_late=+0.033 is real in prints but NOT takeable (print≠fill). Microprice: confirmation-
shaped, coin-inconsistent, parked. E4 Kalshi ask-depth export = the remaining open positive lead.

**Standing process rules from the audit:** every OOS window is single-read (log reads); no deploy without
trial-counted DSR + priced-in-trap check + fill-haircut; audit-then-deploy; CLAUDE.md's Cyclops S7 X1 and
Mint-and-sell V2 "deploy-ready" entries are rigor-stale (annotated in place). Related: [[project-scalp-mid-window-dead]],
[[project-scalp-exit-config]].
