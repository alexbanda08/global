# Session Handoff — 2026-06-11 — Retro audit + harness bug-fix + stop/maker reversal + new-lens sweep

**READ THIS FIRST.** Supersedes `HANDOFF_2026_06_06_OOS_KALSHI_AUDIT.md`. The longest forensic session of the
project: verified prior fixes, hunted (and failed to find) new scalp edges, then ran a full retrospective audit
of 696 reports that uncovered a **harness bug family** which had manufactured TWO false-positive deploys (the
stop and the maker-exit). Fixed the bugs, re-ran everything, **removed the stop on both hosts**, and closed the
maker + oracle-snipe threads with hard numbers. Net: the deployed scalp is simpler and stronger than we thought;
almost every other door is now honestly shut.

---

## A. ONE-LINE STATE
The deployed edge = **window-open exit-scalp, exit = PURE +60s time sell (TP off, stop off), entry unchanged**.
It came out ~2× stronger after the bug-fix (pooled gated +$1.85/tr vs +0.93). The stop and maker-exit were
harness artifacts — both removed/closed. New lenses (Wang, microprice, oracle-snipe, maker-with-rebate) all
explored and **dead/parked**. Remaining positive leads: **live ≥200-fire accrual**, **Kalshi ask-depth (E4)**,
and the untouched **Hyperliquid perps** campaign.

## B. WHAT WAS DONE (chronological)

1. **Verified prior fixes are LIVE** (ground-truth, not reports): F1 fast_taker signal (placed direction now
   ~45-56% per side, was 100% UP) ✓; F6 working tree committed (HEAD past `3a2ff3a9`) ✓; **btc_5m resolution gap
   FIXED** (settling at normal cadence) ✓.

2. **Scalp new-edge hunt — 7 trials, 0 new edges** (`SCALP_NEW_EDGE_HUNT_2026_06_09.md`): mid-window re-fire,
   **fair-value-gap** (principled mid-window — ANTI-signal), cross-asset BTC→ETH/SOL lead-lag (95% co-move,
   paired diff≈0), regime gates, **tick-level trailing exit** (loses to fixed +60 on every grid; oracle peak
   untradeable), entry-offset/delta-band re-opt (+5s & δ≥5 confirmed), same-venue two-sided arb (overround
   ~1.02, dust). The mid-window question is now closed two ways.

3. **MASTER RETROSPECTIVE AUDIT** (`RETRO_MASTER_AUDIT_2026_06_10.md` + `_retro_2026_06_10/01..06`): 6 agents
   over 696 reports. **Found a harness bug family in the scalp backtests:** (C1) outcome-as-price exit fallback
   `1.0 if won else 0.0` when book missing; (C2) the Mar30–Apr21 "clean OOS" window is BURNED (re-read ≥6×);
   (C3) deflation never applied before deploys → −$25.4k fleet drag ~70-85% preventable; (C4) scalp DSR
   pseudo-pre-registered; (C5) sell-leg ignored bid-size; (C6) engine_v2 loser-fee overcharge; (C7) stale GO
   claims (Cyclops, mint-sell). Also the affected-sleeves map (`AFFECTED_SLEEVES_AUDIT_2026_06_10.md`).

4. **Fixed the bugs** (4 parallel agents): corrected harness `directional/scalp_fill_lib_2026_06_10.py` +
   `*_fixed_2026_06_10.py` runners (no outcome fallback → held-to-resolution; 120s staleness guard;
   **BBO size==0 is a COLLECTOR ARTIFACT** ~47% of rows → carry-forward, NOT zero depth; ALL vs CLEAN dual
   reporting). `engine_v2.hold_pnl` loser-fee fixed (winner-only). **resolutions_hf timing hypothesis REFUTED**
   (timing is correct; Feb–Mar L25 books genuinely start +75s → no fresh offline OOS exists). VPS3 host fixes:
   F2 kill (2 look-ahead-dead sleeves), F3 t+60 markov, Kalshi A/B twin, sell_leg_fee (commit `96c4b786`).

5. **BUG-FIX RERUN** (`BUGFIX_RERUN_RESULTS_2026_06_10.md`): re-ran all affected tests, old vs new.
   **STOP: +0.88 → −2.8/−3.2 SIG-NEGATIVE (FLIPS DEAD).** **Maker-exit: +0.42 → −0.07 ns (FLIPS DEAD).**
   Core scalp edge **STRONGER** (+1.85 vs +0.93; the size-artifact was phantom-skipping ~40% of good entries;
   BNB now a positive 6th coin). **Zero false KILLS** — every previously-dead strategy stayed dead.

6. **STOP REMOVED, BOTH HOSTS** (operator decision): `scalp_stop_enabled=False` everywhere — Ireland `1746efc`,
   VPS3 `6eaa154f`. Final scalp exit = pure +60 time sell. Maker-exit disable spec written
   (`TV_AGENT_SPEC_SCALP_DISABLE_MAKER_EXIT_2026_06_11.md`) — **NOT YET APPLIED (hand to TV agent).**

7. **Live × shadow audit of `shadow_scalp_exit_btc_15m_d3_v1`** (`SCALP_BTC15M_LIVE_VS_SHADOW_AUDIT_2026_06_11.md`):
   engine parity is CLEAN (6/7 exact fills). The "divergence" = era mix (shadow's profit was TP-on era pre-06-08),
   the now-removed stop (91% of live losses), a config drift (VPS3 15m ran maker-exit, live taker), and null-pnl
   counterfactual rows. No bug.

8. **awesome-systematic-trading review** (`AWESOME_SYSTRADING_REVIEW_2026_06_11.md`): ~95% irrelevant; adopt
   shortlist = hftbacktest (HL), HL official SDK, pmxt (Poly+Kalshi), Wang-Transform + Microprice (mine).

9. **Wang-Transform + Microprice** (`WANG_MICROPRICE_RESULTS_2026_06_11.md`): Wang on **52M production trades** →
   markets ~perfectly calibrated (≤1.5¢; kills static mispricing edges); **λ_late=+0.033 (5× early)** = real
   late-window premium, corroborates oracle-snipe. Microprice = confirmation-shaped, coin-inconsistent, parked.

10. **Oracle-snipe backtest, 6 coins × 2 tf** (`ORACLE_SNIPE_RESULTS_2026_06_11.md`): **DEAD as taker** — books
    quote the z≥2 winner at median ask ≈$1.00; visibly-cheap favorites are adversely selected (WR < breakeven).
    Tiny thin-book pocket only (BNB 5m), ~$14/day — not worth it.

11. **Maker-with-rebate sim** (`MAKER_SIM_RESULTS_2026_06_11.md` + `POLYMARKET_REBATE_FACTS_2026_06_11.md` +
    `HFTBACKTEST_FEASIBILITY_2026_06_11.md`): **MAKER DEAD even with rebate.** Conservative price-through fills =
    **0.0%** (scalp maker-entry 0/1380; late favored-bid 1/16,376) — no taker-sell flow at-or-below the bid;
    upper-bound fills are toxic (−16 to −26pp WR); rebate is 20%-pool/fills-only/~$0.001-0.002/sh, never flips it.
    hftbacktest installed (cp314 wheel) but **not usable for Poly** (L1-only book) — reserved for Hyperliquid.

12. **Gate-soften BNB/XRP/DOGE** (`GATE_SOFTEN_BNB_XRP_DOGE_2026_06_11.md`): the never-firing sleeves are
    spread-blocked (alt open spreads 8-14¢ vs the 5¢ filter). Found a live float-boundary bug (exact-5¢ spreads
    rejected) → fixed both live (`5437e9e4`) + harness. Sweep verdict: **BNB+DOGE → widen to 0.12** (incremental
    wide-spread fires CI>0: BNB +$4.93, DOGE +$2.74 — the lag edge lives in the dislocated alt book);
    **XRP stays 0.05** (incremental insignificant); **δ floor stays 3** (δ∈[2,3) dead). Deployed `eff02cd2`.

## C. DEPLOYED STATE NOW (verified)
- **Scalp exit = pure +60s time sell, TP off, stop off** — ALL sleeves, both hosts, Poly + Kalshi.
- Entry unchanged: +5s, δ≥3 ($5) / δ≥5 ($25), `entry_vwap<0.55`, spread≤0.05 (BNB/DOGE now 0.12), TOD-gated
  `_tod2` shadow variants keep their hour filter.
- VPS3 commits this session: `5437e9e4` (spread float fix), `96c4b786` (F2/F3/Kalshi/fee), `6eaa154f` (no-stop),
  `eff02cd2` (BNB/DOGE 0.12). Ireland: `1746efc` (no-stop).
- 2 confirmed look-ahead-dead sleeves now killed via env (`q_parent15mslope_ts_imb5_v8`, `ts_mpskew_any_off30`).

## D. OPEN ITEMS (priority)
1. 🟡 **Apply `TV_AGENT_SPEC_SCALP_DISABLE_MAKER_EXIT_2026_06_11.md`** — VPS3 15m sleeves still run maker-exit
   (`scalp_exit_mode="maker_fixed"`); the Ireland live 15m sleeve too. Revert all to taker for twin parity.
2. 🟢 **Live ≥200-fire accrual** on the corrected (pure +60) config — the ONLY true OOS left. Watch BNB/DOGE/XRP
   start firing (gate-soften + float fix). Judge by live CI per stake, NOT vs backtest (corrected baselines).
3. 🟢 **E4 — Kalshi ask-depth export** (one VPS3 query): the last open *positive* lead (deep-dip arb +2.7-6.6¢/set).
4. 🟢 **Hyperliquid perps campaign** — fresh territory. We hold a real asset (4-exchange + HL liq data nobody has
   packaged). Tooling staged: hftbacktest installed, HL official SDK identified, HL S3 L2 available if needed.
   First hypothesis: liquidation-cascade short-horizon edge (build in-house — no repo exists).
5. 🟡 Re-rank any sleeve decision still on raw `events.pnl_usd` → TV dashboard dedup metric. Annotate/retire the
   A3 bleeders still firing (INV_NIGHT×1, sniper_hod×3, momo(_v2)_HOLD_f7×10, l_1hrf_imb5_rf_v8).
6. ⚪ Cyclops S7 X1 + Mint-and-sell V2 in CLAUDE.md are rigor-stale — don't deploy without re-validation.

## E. RULES BANKED THIS SESSION
- **The corrected harness is `scalp_fill_lib_2026_06_10.py`** — use it for ANY new scalp test. Never the old
  `1.0 if won else 0.0` fallback. BBO `size==0` = artifact (carry-forward), never real zero depth.
- **No pre-06-10 scalp MAGNITUDE number is trustworthy** without checking `BUGFIX_RERUN_RESULTS_2026_06_10.md`.
- **The Mar30–Apr21 BBO window is BURNED** — single-read OOS rule going forward; no fresh offline window exists
  (Feb–Mar refuted). Live forward is the only true OOS.
- **Maker is structurally dead on Poly** (no taker-sell flow at the bid) — do NOT re-open on "but the rebate"
  (rebate WAS modeled). Late-window premium is real in PRINTS but not takeable (print≠fill).
- **print≠fill / WR≠edge / efficient-at-scale** all reconfirmed; markets are ~perfectly calibrated (Wang 52M).
- Every deploy: trial-counted DSR + priced-in-trap check + fill-haircut; audit-then-deploy.

## F. KEY REPORTS (this session)
`RETRO_MASTER_AUDIT_2026_06_10.md` ⭐ + `_retro_2026_06_10/{01_CATALOG,02_SCALP_AUDIT,03_DIRECTIONAL_AUDIT,
04_ML_RIGOR_AUDIT,05_DATA_FEE_AUDIT,06_WHITESPACE,FIX_A1_HARNESS,FIX_A2_RESTIMING,FIX_A3_ENGINE,
FIX_A4_VPS3_HOSTFIXES,POLYMARKET_REBATE_FACTS,HFTBACKTEST_FEASIBILITY}.md` ·
`BUGFIX_RERUN_RESULTS_2026_06_10.md` ⭐ · `AFFECTED_SLEEVES_AUDIT_2026_06_10.md` ·
`SCALP_NEW_EDGE_HUNT_2026_06_09.md` · `SCALP_BTC15M_LIVE_VS_SHADOW_AUDIT_2026_06_11.md` ·
`AWESOME_SYSTRADING_REVIEW_2026_06_11.md` · `WANG_MICROPRICE_RESULTS_2026_06_11.md` ·
`ORACLE_SNIPE_RESULTS_2026_06_11.md` · `MAKER_SIM_RESULTS_2026_06_11.md` ·
`GATE_SOFTEN_BNB_XRP_DOGE_2026_06_11.md` · `TV_AGENT_SPEC_SCALP_DISABLE_MAKER_EXIT_2026_06_11.md` (pending).
Prior: `HANDOFF_2026_06_06_OOS_KALSHI_AUDIT.md` (corrected re: stop), `HANDOFF_2026_06_04_ML4T_DSR.md`.
