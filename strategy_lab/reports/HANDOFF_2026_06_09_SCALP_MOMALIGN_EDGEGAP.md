# Session Handoff — 2026-06-09 — Momalign scalp + Edge-Gap research + deploys

**READ FIRST.** Long session. Headlines: (1) found + validated a NEW scalp gate (**momentum-alignment**) →
spec'd for live+shadow $1; (2) corrected the exit-policy truth (**STOP helps, only TP leaks**); (3) **retracted a
false "1s vwap_store bug"** — the live scalp fires fine on Ireland; (4) **deprecated + committed** the bleeding
`ribbon_v8` sleeve; (5) ran a 10-agent **edge-gap research workflow** → `EDGE_GAP_ANALYSIS_2026_06_09.md`; (6) fired
2 gaps: **maker-exit = DEAD (fill-model artifact)**, **Poly×Kalshi arb depth = PASSED (real capacity)**.

GROUND-TRUTH RULE held — operator corrected me on the 1s-bug (right). Verify against live wallet / live events / real fills,
never the handoff or an optimistic model.

> ## 🚨 RECONCILE WITH 06-11 BEFORE TRUSTING THE EXIT NUMBERS HERE
> This session ran on a 06-08/09 timeline. The **later, authoritative** `HANDOFF_2026_06_11_RETRO_BUGFIX_NEWLENSES.md`
> + `BUGFIX_RERUN_RESULTS_2026_06_10.md` + memory `project_scalp_exit_config` SUPERSEDE my exit-policy claim:
> - A **corrected harness** found the **STOP "+0.88/+0.73" was a HARNESS ARTIFACT** (outcome-as-price exit fallback:
>   `1.0 if won else 0.0` when no book). Corrected → **STOP FLIPS DEAD (−2.8 SIG-NEG); stop REMOVED both hosts.**
>   **FINAL scalp exit = PURE +60s time-sell, TP off, STOP OFF.**
> - My `momalign_exit_policy_2026_06_09.py` uses that SAME flagged fallback (`hold()` on missing book) → **my "stop helps
>   +0.73" is suspect** for the same reason. **DO NOT deploy momalign with a stop.** Use **PURE time-exit** and RE-VALIDATE
>   the momalign edge with the corrected `strategy_lab/directional/scalp_fill_lib_2026_06_10.py` (size==0=artifact→carry-forward,
>   never the outcome fallback).
> - Maker-exit DEAD (§E #1) = **AGREES** with the 06-11 corrected rerun (maker-exit +0.42→−0.07 ns). Good.
> - **What's genuinely NEW here and NOT in 06-11:** the **momentum-alignment gate** (§A), the **Edge-Gap map** (§E), the
>   **Kalshi arb depth PASS** (§E #2), the **ribbon deprecation+commit** (§D). The momalign GATE itself (entry signal) is
>   independent of the exit bug — its OOS entry edge stands; only re-confirm the EXIT with the corrected harness + pure time-sell.

---

## A. NEW EDGE — momentum-alignment scalp (BTC 5m) → DEPLOYING live+shadow $1
`SCALP_FROM_SHADOW_SLEEVES_2026_06_09.md` + `TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09.md` (impl-ready).

- **What:** the deployed `shadow_scalp_exit_btc_5m_d3_v1` (+5s, `g_oracle_lag_with(3,12)`, vwap<0.55) + a NEW gate
  **`g_lag_momentum_align(BTC,30)`** = lag-sign must agree with the 30s binance return, fired at **offsets (30,60)**.
- **Validated:** window Apr24→Jun8 (~45d), **164 fires** (98 IS / 66 OOS). Pre-registered single hypothesis (NOT the
  130-cell search winner → not deflation-hacked). **OOS +$4.24/tr CI[1.85,6.52]** (pure +45s); momalign beats no-regime
  OOS (+4.24 vs +2.77); IS weaker (not overfit). **ETH does NOT hold** (BTC≫ETH).
- **Exit (ground truth, `momalign_exit_policy_2026_06_09.py`):** **+45s + protective STOP@(fill−0.10), NO take-profit.**
  stop−pure = +0.73/tr CI[+0.35,+1.14] SIG in ALL/IS/OOS; TP@0.65 leaks (3.59→1.01). With stop: **OOS +$5.21/tr CI[2.81,7.74]**.
- **Overlap w/ deployed 5s scalp** (`scalp_overlap_2026_06_09.py`): **91% DISJOINT** markets; of 9% overlap, 7% opposite-side
  (hedge), only **2% same-side double-long** → running both = additive coverage, negligible conflict.
- **Spec config:** sleeve `shadow_scalp_momalign_btc_5m_v1` (+`_control_v1`=momalign OFF for A/B). BTC 5m BOTH, offsets
  (30,60), entry_band(0,0.55), spread `_SPREAD_LAGV2`, $25 paper / **$1 live**, one_shot/slug, exit +45s stop@−0.10 NO TP.
  New gate code in the spec (mirror `g_oracle_lag_with`, reuse `_binance_close_at`+`oracle_lag`).
- **Status:** operator will deploy **live (Ireland) + shadow (VPS3) at $1**. TV agent must implement the 1 new gate.
  Graduation gate before sizing up: ≥200 live fires + CI>0 + beat `_control_v1`.
- **CAVEAT:** OOS-positive but NOT deflation-confirmed across the search (correlated cells). 164 backtest fires
  (~3.6/day), OOS only 66 → forward fires are the real test.

## B. EXIT-POLICY — SUPERSEDED by 06-11 (see reconcile box above)
This session measured stop@−0.10 = +0.73/tr SIG and TP leaks — BUT the stop result used the flagged outcome-fallback harness.
The **authoritative 06-11 corrected-harness result is STOP DEAD (artifact) → PURE +60s time-sell, TP OFF, STOP OFF, both hosts.**
TP-leaks conclusion still holds. **Use pure time-sell; re-validate any exit change with `scalp_fill_lib_2026_06_10.py`.**

## C. 1s vwap_store "bug" — RETRACTED, NO BUG
`TV_AGENT_SPEC_SCALP_ORACLE_LAG_IRELAND_1S_STORE_2026_06_08.md` is marked **RESOLVED/RETRACTED — do not act on it.**
Live ground truth 06-09: `g_oracle_lag` passes all day on Ireland; `shadow_scalp_exit_btc_5m_d3_v1_LIVE` placed **8 live
fills/24h** (15m: 4). The 1s store is live; the scalp trades live. My 06-08 "0% gate / stale store" was transient or
mis-diagnosed. **No 1s-store fix needed; live scalp deploy is unblocked.**

## D. ribbon_v8 sleeve DEPRECATED (was bleeding live −$7.99)
`poly_sniper_v5_btc_5m_l_1hrf_imb5_ribbon_v8` fully retired, 3 layers: (1) removed from `TV_POLY_SNIPER_V5_LIVE_ALLOWLIST`
(env, Ireland), (2) commented out of `SNIPER_V5_SLEEVES` registry (both boxes), (3) added to
`BASELINE_DEPRECATED_POLY_UPDOWN_SLEEVES` (off the dashboard grid). **Committed + pushed deploy/vps3 `a7c60553`** (isolated
hunks only, via local worktree push — VPS3 deploy key is read-only). Both engines restarted; verified 0 fires.

## E. EDGE-GAP RESEARCH (10-agent Sonnet workflow) → `EDGE_GAP_ANALYSIS_2026_06_09.md`
Full map: all ~30 approaches tried (verdicts), shadow coverage matrix, the 8 hard failure-rules, 12 ranked gaps, dead-end
rejections of external ideas. **Bottleneck is OPERATIONAL not research** (disable live TP, get ≥200 live fires, re-baseline
shadow with real sell fee ~$0.15/tr optimistic). Existing-data scalp space is exhausted.

### Gaps executed this session:
- **#1 Queue-aware maker-EXIT → DEAD/NEUTRAL** (`maker_exit_queue_2026_06_09.py`). With realistic L25 ask-queue +
  buy-trade tape (you rest BEHIND the ask depth): maker queue-fixed −0.05 ns, peg-trail +0.05 ns vs taker+60; same IS/OOS;
  not both-asset positive. **The +$0.42/tr first-pass was a fill-model artifact** (optimistic "any buy-trade≥target fills").
  → Keep pure taker +60 + stop. Maker-exit is NOT an edge. RULE: maker-fill claims must model queue position.
- **#2 Poly×Kalshi 15m deep-dip arb depth → PASSED** (`poly_kalshi_arb_sizeaware_2026_06_09.py`). 882 windows: 98% dip
  <0.95; **88% of dip moments fillable ≥$5** (median depth ~$30). The +2.7¢/set arb (CI>0 at cost<0.95) has REAL capacity,
  not phantom. Structural arb (buy set < payoff) — dodges every prediction trap. **NEXT: live action item.**

### Remaining ranked gaps (untested):
- **#3 Binance 1s taker-OFI gate** (`taker_buy_base/total` in klines_1s, never extracted) — data-ready, OOS-able, 1 session.
  Risk: redundant with delta_bps. Best new-signal probe.
- #4 CEX mark-spot perp basis gate — DEFER (basis-family has dead precedent; only 9d cex_futures data; re-test post Jun15).
- #5 Oracle-staleness snipe — LOW (Jan-2026 dynamic fees partly closed it + thin-fill wall).
- Also: L25 depth-shape (levels 2–25, only BBO used), HL liquidation-cascade gate (5.27M rows untouched).

## F. OTHER FINDINGS THIS SESSION
- **Cyclops wallet** `0xf69af0b9af9c92a342b682e5dee262dbc39e7b5c` (`cyclops_wallet_7d_2026_06_05.py`): 7d = 163 BTC-5m
  directional hold-to-resolution buys, ~$3 stake, WR ~71%, realized **+$1.97/7d** (lb-api), lifetime −$213. Marginal
  mirror bot, no strategy change.
- **V10 vs v8** (`eth_5m_l_ema50_hurst_grandparent`): V10 = v8 + 1 gate `g_sms_no_liquidity_above`. In V10's window:
  agreed on 94 trades, V10 vetoed 30 of v8's 124 (those 30 = break-even, WR 63%, +$0.40). V10 same PnL on less capital
  (ROI 19.4% vs 14.6%). Accretive capital filter on small n.
- **Kalshi-live vs Poly-shadow scalp divergence** (`scalp_exit_btc_15m_d3_v1`): they're ~different instruments (only 1/8
  slots overlap), Kalshi enters ~4¢ worse, 1-contract integer sizing, Kalshi got the stop tail / Poly got TP winners.
  Sign-flip is small-n noise on disjoint trades, not a bug.

## G. NEXT (priority)
1. **Deploy momalign scalp** (TV agent implements `g_lag_momentum_align`) — live+shadow $1, both boxes. A/B vs control.
2. **Poly×Kalshi arb live test** — write the arb sleeve spec (entry set-cost<0.95 & ≥$5 fillable both legs; $1/set;
   settlement-disagreement guard; Kalshi live already enabled `TV_KALSHI_LIVE_ENABLED=true`). Fire 10×$1/set on a verified dip.
3. **Operational (the real bottleneck):** confirm live TP OFF / stop ON on all scalp sleeves; accumulate ≥200 live fires;
   re-baseline shadow PnL with real sell fee.
4. **Gap #3 (1s-OFI gate)** — data-ready single-session probe if research bandwidth.

## H. KEY FILES (this session)
Reports: `SCALP_FROM_SHADOW_SLEEVES_2026_06_09.md` · `TV_AGENT_SPEC_SCALP_MOMALIGN_BTC5M_2026_06_09.md` ·
`EDGE_GAP_ANALYSIS_2026_06_09.md` · `TV_AGENT_SPEC_SCALP_ORACLE_LAG_IRELAND_1S_STORE_2026_06_08.md` (RETRACTED).
Scripts (`strategy_lab/directional/`): `sleeve_scalp_{cache,analyze}_2026_06_09.py` (Exp1) ·
`midwindow_scalp_{cache,gates,robust,oos}_2026_06_09.py` (Exp2) · `momalign_exit_policy_2026_06_09.py` (exit truth) ·
`scalp_overlap_2026_06_09.py` · `maker_exit_queue_2026_06_09.py` (gap#1 dead) ·
`poly_kalshi_arb_sizeaware_2026_06_09.py` (gap#2 pass). Caches in `directional/_results/*.parquet`.
Wallet: `strategy_lab/wallet_hunt/cyclops_wallet_7d_2026_06_05.py`.
