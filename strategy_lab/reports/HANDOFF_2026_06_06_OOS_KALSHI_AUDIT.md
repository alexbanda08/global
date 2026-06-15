# Session Handoff — 2026-06-06 — Scalp OOS (5 coins) + Kalshi arb + live audit

**READ THIS FIRST.** Supersedes `HANDOFF_2026_06_04_ML4T_DSR.md` (still valid for the ML/DSR dead-ends).
Big session: the exit-scalp went from "in-sample+live-promising" to **OOS-validated across 5 coins**; new
**Kalshi** data revealed a **real deep-dip Poly×Kalshi arb**; a two-host live audit found the scalp is spec-true
but the live **TP@0.65 leaks edge** (the STOP does NOT — see correction below). **#1 NEXT: test the
maker-exit-with-taker-fallback** (favorable exit-side selection — the one promising untested lever) and disable the
live **TP only**.

> ⚠️ **CORRECTION 2026-06-09 (authoritative — supersedes the "disable TP+stop" claims throughout this doc):**
> only **TP@0.65 leaks edge → disable it**. The **stop@(fill−0.10) is VALIDATED edge (+0.88/tr, SIG, confirmed 3×)
> → KEEP it.** This doc conflated the non-edge TP with the edge stop. Authoritative config = **TP OFF, STOP ON,
> +60 s**. See `project_scalp_exit_config` memory + `SCALP_NEW_EDGE_HUNT_2026_06_09.md`. (Note: the overnight
> *trailing*-stop test is about trailing vs fixed-+60 timing — it does NOT bear on the fixed stop-loss.)

---

## A. ONE-LINE STATE
The intra-window EXIT-SCALP is now the project's definitively validated edge (in-sample → DSR → live-shadow →
**clean disjoint-window OOS on BTC/ETH/SOL/DOGE/XRP**). Everything predictive/selective stays efficient. NEW
positive lead: **Poly×Kalshi deep-dip arb** (net +2.7–6.6¢/set, gated on Kalshi fill-depth verification).

## B. WHAT WAS DONE THIS SESSION
1. **§D-1 CPCV + meta-label the scalp** → NEGATIVE. 61 causal features + logit/GBM + purged CombinatorialCV
   CANNOT beat a 1-feature `delta_bps` sort. `delta_bps` is the sufficient statistic. `META_LABEL_SCALP_CPCV_2026_06_04.md`.
2. **§D-4 DSR/PBO the 1d-trend MA cluster** → DEAD. 0/25 survive DSR; PBO>0.5. `DSR_PBO_1D_CLUSTER_2026_06_04.md`.
3. **F2 OOS + cross-exchange basis** → REJECTED (trigger edgeless OOS; basis dislocation a NEGATIVE signal). Fade
   instinct → favorite-longshot, which is real in print but **dies on fills** (print≠fill). `F2_BASIS_OOS_2026_06_04.md`,
   `FAVORITE_LONGSHOT_2026_06_04.md`.
4. **Slug-selection deep research** (ml4t/DSR-disciplined, sonnet) + experiments:
   - **Oracle-determinism selector** — real, survives fills directionally, but UNDERPOWERED (3–12% fill).
     `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md`. Shadow-deploy spec written.
   - **Time-of-day gate** — ✅ scalp edge ~2× in 22–02 UTC; dead hours {12,17}; walk-forward + F2-confirmed +
     **OOS-confirmed**. Exclude {12,17} keeps volume + lifts $/tr. `SLUG_SELECTION_RESULTS_2026_06_05.md`.
   - Dead: liquidity-inversion, cross-token price-sum (lookahead artifact), reversal-imbalance, shock>12.
5. **Scalp dynamic-exit study** → fixed **+45/+60s is optimal**; take-profit + longer holds WORSE (TP caps
   runners). `SCALP_DYNAMIC_EXIT_2026_06_04.md`. ← key for the live audit below.
6. **Maker ENTRY sim** → DEAD (adverse selection: resting bid fills on losers). `SOL_SCALP_AND_MAKER_ENTRY_2026_06_05.md`.
7. **SOL scalp** → edge present but untradeable at $25 (0.5% fill, thin books).
8. **NEW DATA + the big win — scalp DIFFERENT-WINDOW OOS:** operator backfilled 1s (Jan→Jun for BTC/ETH/SOL,
   Jan→Apr for new coins) + aliplayer **BBO** (`load_orderbook_bbo`, 7 coins, Mar30→Apr21, slot-aligned). Ran the
   scalp on **Mar30→Apr21 (disjoint from the Apr22–Jun4 search)**: gated cell CI>0 on **BTC +$2.38, ETH +$1.92,
   SOL +$2.16, DOGE +$1.40, XRP +$2.20** (5 coins). **§D-2 deflation gate CLEARED.** Time-of-day gate also
   OOS-confirmed. `SCALP_OOS_PASS_2026_06_05.md`, `NEW_DATA_INVENTORY_2026_06_05.md`.
   - Diagnosed a trentmkelly L25-backfill timing quirk (books start +80s) → use aliplayer BBO for early-slot.
9. **Kalshi data → canonical** (3-day collector): `kalshi_markets.parquet` (978 BTC/ETH/SOL 15m mkts),
   `kalshi_orderbook.parquet` (771k quotes). Loaders `load_kalshi_markets/load_kalshi_orderbook` added to load.py.
10. **Poly×Kalshi 15m cross-venue arb** → ⭐ **REAL in the deep dips.** Kalshi `KX{A}15M` == Poly `{a}-updown-15m`
    (96.0% settlement agreement). Set-cost<0.95 → net **+2.7¢/set** (CI [+1.1,+4.2]); <0.90 → **+6.6¢/set**
    (CI [+4.8,+8.4]); ~200–240 chances/day. Treasury: profit **drifts to Poly** (good — easy withdraw; refill
    Kalshi). 🔴 GATED on unverified Kalshi ask DEPTH + 2-venue simultaneous fills. `POLY_KALSHI_ARB_2026_06_05.md`.
11. **Cross-timeframe arb** (Poly 5m vs 15m) → NULL (efficiently priced). `CROSS_TIMEFRAME_ARB_2026_06_05.md`.
12. **Two-host LIVE AUDIT** (Ireland + VPS3) of the scalp → core logic SPEC-TRUE on both. Divergences:
    `SCALP_LIVE_AUDIT_2026_06_06.md` (this session). See §D.

## C. VALIDATED / DEPLOYABLE NOW
- **Exit-scalp** (lag-taker, entry_vwap<0.55, δ≥3/5, sell book +60s) — OOS-validated **BTC/ETH/SOL/DOGE/XRP**.
  `delta_bps` sizes it; **NO ML, NO TP** (pure +60). Live on Ireland ($1, btc_5m_d3) + full shadow fleet on VPS3.
- **Time-of-day gate** (exclude {12,17} UTC; favor 22–02) — validated 3 ways. Spec: `TV_AGENT_SPEC_SCALP_TOD_GATE_2026_06_05.md`.
- **All-coin scalp deploy spec** (SOL/DOGE/XRP/BNB shadow): `TV_AGENT_SPEC_SCALP_ALLCOINS_2026_06_05.md`.
- **Exit time = +60s (verified 2026-06-06).** Paired bootstrap per cell: **+45 and +60 are statistically TIED**
  (every CI incl 0); +60 is argmax-mean for BTC + pooled; +45 only edges ETH5m/δ≥5 by ~$0.003 = noise. The old
  "+45≥+60" note was a tighter-t artifact, NOT higher return. **Use +60; do NOT switch to 45 or per-cell-tune.**
- **Kalshi scalp port LIVE:** `kalshi_scalp_exit_btc_15m_d3_v1` (KXBTC15M, fire +60s, $1 live on Ireland) —
  same lag-taker logic on the Kalshi book. TAKER exit only (maker-exit tested → worse on Kalshi, §D/§E).

## D. LIVE-AUDIT FINDINGS (act on these)
- ✅ Core scalp logic spec-true on BOTH hosts (gate, entry_band (0,0.55), +60 deadline, $25/$5, one_shot, BOTH,
  python-authoritative). VPS3 = full fleet incl. this session's TOD + SOL/DOGE/BNB/XRP sleeves (already in code).
  Ireland = single live `shadow_scalp_exit_btc_5m_d3_v1` at real $1/fire.
- 🔴 **TP@0.65 active on both hosts AND both live sleeves** (Poly btc_5m_d3 + Kalshi btc_15m_d3) —
  `SCALP_DYNAMIC_EXIT` proves the **TP** CAPS RUNNERS, underperforms +60. **→ disable scalp_tp_bid (≥0.999).**
  ⚠️ **CORRECTION 2026-06-09: disable the TP ONLY — the stop@(fill−0.10) is VALIDATED edge (+0.88/tr SIG, ×3) and
  must be KEPT.** (The original line said "+ stop" — wrong.) SPEC: `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md`.
- Exit time +45 vs +60 re-verified TIED (use +60) — do NOT change exit time, only remove the **TP** (keep the stop).
- 🔴 **Ireland trading REAL $1 capital BEFORE the ≥200-fire graduation gate** (~16 live fires so far). Tiny, but
  confirm it's an intentional micro-live accrual, not an early jump.
- ⚠️ Shadow PnL optimistic: `sell_leg_fee=0.0` → re-baseline shadow $/tr with the real taker sell fee.
- spread_filter=0.05 (both) = BY DESIGN (lag edge lives in dislocated books), spec-true.

## E. NEXT STEPS (priority order — START HERE)
1. ⭐ **MAKER-EXIT — FIRST-PASS DONE 2026-06-06, POSITIVE** (`MAKER_EXIT_SIM_2026_06_06.md`). Maker SELL@0.65 +
   taker-+60 fallback beats pure-taker-+60 by **+$0.42/tr (CI [+0.02,+0.82], SIG)** on the gated scalp —
   favorable exit-side selection + sell-at-offer + rebate. BUT fill model is OPTIMISTIC (first buy-trade≥target,
   ignores queue). **REMAINING (do next):** (a) queue-aware fill using L25 ask depth/size (only fill if buy-volume
   at ≥target exceeds the queue ahead); (b) PEG-TO-ASK/trail not fixed 0.65 (fixed caps runners); (c) OOS on
   Mar30–Apr21 BBO; (d) ml4t DSR. If it holds → spec to replace the +60 taker exit with maker-at-offer+fallback.
2. **Disable live TP@0.65 ONLY — KEEP the stop** (stop = validated edge +0.88/tr SIG ×3; do NOT go "pure +60") — SPEC WRITTEN
   `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md` (hand to TV agent; BOTH live sleeves: Poly
   `shadow_scalp_exit_btc_5m_d3_v1` AND **Kalshi `kalshi_scalp_exit_btc_15m_d3_v1`** — a Kalshi port, live $1 on
   Ireland, same TP/stop) + set shadow `sell_leg_fee` to the real taker curve.
   - NOTE: maker-exit is **Polymarket-ONLY**. Kalshi maker-exit tested (`kalshi_scalp_maker_exit_2026_06_06.py`) =
     WORSE (no Kalshi maker rebate; taker-only fee; tight spread; +120s/900s runway lets taker beat a capped maker TP).
3. **Verify Kalshi fill-depth** for the Poly×Kalshi arb: re-export the `yes_bids/no_bids` jsonb from
   `kalshi_orderbook_v2` (full depth) → re-run depth-aware to confirm the deep dips fill at size. Make-or-break
   for whether the arb is ~$600/day or ~$6k/day real capacity. Then a $0 paper depth-check, then ~$100 live test
   (⅔ Kalshi / ⅓ Poly, $1/set).
4. **Live forward fires** for the scalp → ≥200 + live-wallet CI (the last gate before scaling real capital).
5. Re-baseline shadow scalp PnL with the real sell fee.
6. (lower) Oracle-determinism shadow sleeve to accrue power; new-coin scalp once XRP/HYPE feeds align.

## F. WHAT WAS NOT DONE / OPEN
- Maker-exit (Poly): first-pass DONE (+$0.42/tr, optimistic fill). NOT done = queue-aware fill model +
  peg-to-ask/trail + OOS + ml4t DSR (= #1 next). Spec written shadow-first: `TV_AGENT_SPEC_SCALP_MAKER_EXIT_2026_06_06.md`.
- Maker-exit (Kalshi): tested → WORSE (no rebate/tight spread/15m runway). Closed — Kalshi stays taker.
- Disable-TP (ONLY — keep the stop): spec written, NOT yet applied by TV agent (hand off).
- Kalshi ask-depth — NOT verified (only bid sizes exported; jsonb book dropped). Arb is UNCONFIRMED on size.
- Poly×Kalshi arb on >2.6 days — short sample; re-run as Kalshi accrues.
- New-coin scalp (DOGE/BNB live signal feed, XRP/HYPE) — needs operator data / live feeds.
- BNB scalp underpowered (n=22).
- Oracle-determinism — real but underpowered, shadow-deploy not yet live.

## G. ENVIRONMENT & DATA (fresh-session quick-start)
- **Python = `C:/Python314/python.exe`** (run `cd <root> && C:/Python314/python.exe path.py`). NOT bare `python`.
- ml4t installed (engineer/diagnostic/models). DSR: `from ml4t.diagnostic.evaluation.stats.deflated_sharpe_ratio import
  deflated_sharpe_ratio, deflated_sharpe_ratio_from_statistics`. CombinatorialCV in `ml4t.diagnostic.splitters.combinatorial`.
- **Canonical NEW:** `klines_1s.parquet` Jan→Jun (BTC/ETH/SOL) + Jan→Apr (BNB/DOGE/XRP); `orderbook_l25_backfill/`
  (BTC/ETH Feb21–Mar24 98M, SOL/XRP Mar1–13); BBO on D: `load_orderbook_bbo` (7 coins Mar30–Apr21);
  `resolutions_hf.parquet` (6 coins, Jan→Apr21); `kalshi_markets/orderbook.parquet`; `cex_futures_*` (May30–Jun4).
- **Hosts:** `ssh vps_ireland` (live exec, git deploy/ireland) · `ssh vps3` (shadow + storedata postgres, git deploy/vps3).
  Kalshi in postgres `storedata.kalshi_markets_v2 / kalshi_orderbook_v2`. tradingvenue at /opt/tradingvenue.
- **Engine:** `strategy_lab/engine_v2.py` (LiveMimicConfig, fill_at_book, sell_pnl_partial, hold_pnl). 0.07
  winner-only fee. Scalp fee accounting must include the SELL leg (live `sell_leg_fee=0.0` is a proxy).
- **Rules banked this session:** WR≠edge · print≠fill · maker≠taker for momentum-capture (ENTRY adverse; EXIT
  favorable — test it) · selection efficient at every scale · subagents+workflows ALWAYS model:"sonnet".
- **Key scripts:** `directional/scalp_oos_bbo_2026_06_05.py` (scalp OOS), `poly_kalshi_arb_numbers_2026_06_05.py`
  + `poly_kalshi_treasury_2026_06_05.py` (arb), `autoresearch/{meta_label_scalp,dsr_pbo_1d_cluster,
  oracle_settlement_selector,slug_sel_2_4_tgate}_2026_06_0x.py`.

## H. KEY REPORTS (this session)
`SCALP_OOS_PASS_2026_06_05.md` ⭐ · `POLY_KALSHI_ARB_2026_06_05.md` ⭐ · `SCALP_LIVE_AUDIT_2026_06_06.md` ⭐ ·
`MAKER_EXIT_SIM_2026_06_06.md` (Poly maker-exit +0.42) · `kalshi_scalp_maker_exit_2026_06_06.py` (Kalshi maker = worse) ·
deploy specs (2026-06-06): `TV_AGENT_SPEC_SCALP_DISABLE_TP_2026_06_06.md` (pure +60, both live sleeves) ·
`TV_AGENT_SPEC_SCALP_MAKER_EXIT_2026_06_06.md` (Poly-only, shadow-first A/B) ·
`SLUG_SELECTION_RESULTS_2026_06_05.md` · `SLUG_SELECTION_RESEARCH_2026_06_05.md` · `ORACLE_SETTLEMENT_SELECTOR_2026_06_05.md` ·
`SCALP_DYNAMIC_EXIT_2026_06_04.md` · `META_LABEL_SCALP_CPCV_2026_06_04.md` · `DSR_PBO_1D_CLUSTER_2026_06_04.md` ·
`F2_BASIS_OOS_2026_06_04.md` · `FAVORITE_LONGSHOT_2026_06_04.md` · `SOL_SCALP_AND_MAKER_ENTRY_2026_06_05.md` ·
`CROSS_TIMEFRAME_ARB_2026_06_05.md` · `NEW_DATA_INVENTORY_2026_06_05.md` · `VPS3_SLEEVE_VERIFICATION_2026_06_05.md` ·
specs: `TV_AGENT_SPEC_SCALP_{TOD_GATE,ALLCOINS}_2026_06_05.md`, `TV_AGENT_SPEC_SHADOW_ORACLE_SETTLE_2026_06_05.md`,
`DATA_ASK_NEWCOIN_SCALP_OOS_2026_06_05.md`, `DATA_FIX_SPEC_RESOLUTIONS_HF_TIMING_2026_06_05.md`.
Prior: `HANDOFF_2026_06_04_ML4T_DSR.md`.
