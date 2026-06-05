# Session Handoff — 2026-06-03 — Intra-window EXIT-SCALP (the session's one real edge) + full fleet audit + live forensics

**Read this first.** Long session. Headline: after killing ~65 research candidates and re-validating the lag-taker
(OOS-weak), we found ONE edge that survives full rigor — the **intra-window exit-scalp** — and it's now **deployed
as 16 shadow sleeves on VPS3**. Plus: 215-sleeve fleet audit, Kalshi/Polymarket live forensics, and 6 TV fix-specs.

---

## A. DONE THIS SESSION

### A1. Lag-taker OOS re-validation → real-but-THIN, forward-weak
- Extended the window using `binance-vision` 1s (Apr7→May6) + `binance-spot-ws` (May7→Jun1) → usable Apr24→Jun1
  (~38d) vs the original 21d. Script: `directional/lag_taker_oos_reval_2026_06_01.py`; fires:
  `lag_taker_fires_oos_2026_06_01.parquet` (2,538). Report: `LAG_TAKER_OOS_REVAL_2026_06_01.md`.
- Verdict: base ≥3bps FIT +$1.71/tr t=2.38 vs **UNSEEN +$0.36/tr t=0.41** (not significant). ≥5bps INVERTS negative OOS.
  Forward 3d held (+$2.3/tr) but underpowered; backward regime weak. **SOL dead.** Engine fix (min_book_events=25
  now enforced, 2026-05-30) cut fit-window $/tr ~28%.

### A2. New-edge research swarm (WORKFLOW #1) → 49 candidates → 0 deploy-grade
- `NEW_EDGE_RESEARCH_2026_06_01.md` (49 verified novel candidates, 16 Tier-1). Then validated ALL 16 Tier-1 in
  5 staged backtests → `EDGE_VALIDATION_TIER1_2026_06_01.md`. **0/16 deploy-grade.**
  - A1 HL short-cascade 60s = real-but-thin (WR 57.9% p=0.03; on fills +$1.16/tr t=0.47, vwap 0.51 = no trap).
  - **B1 VPIN / C4 CVD = the PRICED-IN TRAP** (67–89% WR but −$0.62 to −$1.03/tr — high WR ≠ edge). C1/C8 depth INVERTED.
  - B2–B6 klines (KAMA/semivar/CUSUM/Kalman/RS) = dead (~50% vs oracle). **Lesson: pure price-technicals at ws_s = coin-flip.**
- Physics × HL-liq combo tested → dead (sparsity). `physics/physics_x_liqcascade_2026_06_01.py`.

### A3. Shadow fleet edge audit — 215 sleeves, net −$25.4k
- `SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md` + `_sleeve_edge_2026_06_02/full_table.md` (every sleeve).
- **4 EDGE (t≥2):** `btc_15m_ema50_ema800_off600_down` (Kalshi+Poly, cross-venue), `eth_5m_l_ema50_hurst_grandparent_v8`
  (t=2.2), two `btc_15m_*_trstack_off600`. **25 bleeders (−$19.8k):** INV_NIGHT ×6 (−$10k), `btc_5m_l_1hrf_imb5_rf_v8`
  (76% WR but −$611 t=−4.7 = trap-at-scale), phase1_kelly, fade. **KILL LIST → TV agent to disable.**

### A4. ⭐ Intra-window EXIT-SCALP — the one edge that survived (WORKFLOWS #2+#3 + rigor)
- Idea (operator-proposed): buy the lag-taker token cheap, **SELL on the book mid-window (~+60s) instead of holding
  to resolution** → capture the reprice, sidestep the priced-in trap. Research: `INTRADAY_SCALP_RESEARCH_2026_06_02.md`.
- Validated end-to-end (gates 1–6, full window Apr24→Jun1, $25 backtest stake):
  - Exit beats hold; **TIME+45–60s exit**. Walk-forward (selection-bias corrected) **+$2.98/tr t=6.33**, auto-picks
    `vwap<0.55`. Direction permutation: lag-side +$0.96 vs opposite −$4.52, **p=0.0000**.
  - **The robust cell = `entry_vwap<0.55`: +$2.56/tr, t=5.50, bootstrap 95% CI [+1.63,+3.46] EVEN under the
    pessimistic 0.07-both-legs fee** (n=398). CUSUM dropped (dead). BTC ≫ ETH.
  - Scripts: `directional/scalp_exit_validation_2026_06_02.py`, `scalp_rigor_full_2026_06_02.py`,
    `scalp_rigor_2026_06_02.py`, `scalp_variants_2026_06_02.py`. Reports: `SCALP_VALIDATION_2026_06_02.md`.
- **Fee question resolved favorable:** production buy-leg = $0 (loser accounting 20/20); mint-sell token-SELLS charge
  $0 (38,917 events) → FEE0 is realistic; breakeven ≈3.5%/leg.

### A5. SCALP DEPLOYED — 16 shadow sleeves on VPS3 (verified correct)
- Specs: `TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md` (δ≥5, $25) + `TV_AGENT_SPEC_SCALP_DELTA3_VARIANT_2026_06_02.md`
  (δ≥3, $5). TV agent implemented BOTH; I verified the live code + a real fire→exit lifecycle (entry → `sleeve_scalp_exit`
  sold on book at the stop). All gates wired: `entry_band=(0,0.55)` on `_v1` / `None` on `_control_v1`, `exit_policy=
  SCALP_EXIT` (+60s / TP0.65 / stop−0.10, poll 5s), one-shot, direction BOTH, distinct `event_type=sleeve_scalp_exit`.
- **The 16 sleeves** (`shadow_scalp_exit_{btc,eth}_{5m,15m}[_d3]_{v1,control_v1}`): δ≥5 @ $25 (8) since 06-03 02:05,
  δ≥3 @ $5 (8) since 05:27. Master table: `MASTER_FINDINGS_TABLE_2026_06_02.md`.

### A6. Live forensics (VPS3 + Ireland) — fixed/explained
- **LAGV2 always-UP bug FIXED** (confirmed: 4 live sleeves now fire 50/50). 
- **Kalshi 409 Conflict** (live ema50_ema800_H not firing) → `TV_AGENT_KALSHI_409_LIVE_NOT_FIRING_2026_06_02.md`.
  TV agent fixed: capture 409 body + **FOK→IOC on entries** (`TV_FIX_KALSHI_IOC_2026_06_02`, live after 06-03 09:38
  restart) + FOK-killed accounting (no phantom positions).
- **off900 "double-fire"** = NOT a bug (it's `sleeve_fire_placed` + `sleeve_fire_resolved`, both stamped
  all_gates_passed=true → only a metrics double-count). `TV_FIX_SNIPER_DOUBLE_FIRE_NONBUG_2026_06_02.md`.
- **Kalshi vs Polymarket-live** (ema50_ema800): same 8/10; divergences are (a) **different settlement feeds** — Kalshi
  index vs Chainlink → same window resolves opposite on near-flat windows; (b) FOK-kill + entry-vwap band + thinner
  Kalshi liquidity. NOT a strategy difference.
- **Hedge (`_H`) variant:** Poly-shadow `_H` fired 21 `hedge_late_cut` (all losers, salvage ~16%, −$77.71). Kalshi `_H`
  fired **0** hedges — the hedge salvage-sell is FOK and can't fill thin late books → always holds to resolution.
- "5W streak" on the eth-hurst sleeve = display bug (win-count-in-window mislabeled as streak; underlying data sound).
- `ALL_15m_S4_prewindow` "invisible in Polymarket live" = fires via `reason=order_placed`, never sets all_gates_passed →
  invisible to all_gates_passed-based dashboards. Not dead.

---

## B. OPEN / TODO (priority order)

1. 🔴 **Scalp forward-OOS — THE open graduation gate.** Offline fwd_oos (n=14–76) is flat-NEGATIVE; the 16 shadow
   sleeves exist to accumulate live forward fires. **Need ≥200 forward fires with bootstrap CI>0** before any real
   capital. The δ≥3 @ $5 variant accelerates this ~3×. Monitor weekly.
2. 🔴 **Verify the live taker-SELL fee** on 10–20 real shadow scalp fills (offline proxy = $0, but unconfirmed for a
   taker sell). + **exit-fill realism** on live thin books (the worst-5% loss was thin-book exit slippage).
3. 🟡 **Poly SHADOW ema50_ema800 lacks the `entry_vwap` band** that the LIVE sleeves have → it logs the 0.95–0.98 trap
   fires the live correctly skips. Add the band so shadow == live (apples-to-apples). (Spec not written yet.)
4. 🟡 **Kalshi EXIT leg still FOK** (`client.py:535`) → the `_H` hedge salvage-sell can't fill → hedge non-functional on
   Kalshi. Switch exit FOK→IOC if you want the hedge to work live. (Spec not written.)
5. 🟡 **Disable the bleeders** (kill list from A3): INV_NIGHT ×6, phase1_kelly, fade ×N, `btc_5m_l_1hrf_imb5_rf/ribbon`
   (trap-at-scale), v3/v4, sniper_hod. ~−$13–20k of shadow drag.
6. ⚪ **g_a2 fix** (`TV_AGENT_FIX_GA2_WINDOW_2026_06_02.md`, 300→60s) — supported but modest; **HL feed stale at May27**
   + bybit/bitget liq collectors EMPTY must be repaired first (`HANDOFF_HURST_HLCASCADE_FIX_2026_06_01.md` still open).
7. ⚪ **$50 Polymarket autonomous-trading experiment** (operator idea, deferred) — agreed: measured experiment with hard
   guardrails (max loss = $50, ≤$10/position, human-in-loop or hard cap), framed as "find an inefficiency," NOT income.

---

## C. CARRY-OVER from prior handoffs (still relevant)
- Fee model: **production charges 2%-on-profit-winner-only (≈feeRate 0) on these crypto up-down markets** — use this,
  not the 0.07 curve, for hold-to-resolution. For SCALP round-trips the buy+sell legs are effectively ~$0 (FEE0).
- Anchor conventions unchanged (ws_s = slot_start − window_s; lag-taker fires at slot_start+5s). See CLAUDE.md.
- HL liqs NOT refreshed since 2026-05-27 (so A1/g_a2/liq work is bounded Apr24→May27). cex_futures liqs = gate+okx only.

## D. Key reports (this session)
Scalp (the deliverable): `SCALP_VALIDATION_2026_06_02.md` · `TV_AGENT_SPEC_SCALP_EXIT_SHADOW_2026_06_02.md` ·
`TV_AGENT_SPEC_SCALP_DELTA3_VARIANT_2026_06_02.md` · `INTRADAY_SCALP_RESEARCH_2026_06_02.md` · `MASTER_FINDINGS_TABLE_2026_06_02.md`
Research/validation: `NEW_EDGE_RESEARCH_2026_06_01.md` · `EDGE_VALIDATION_TIER1_2026_06_01.md` · `LAG_TAKER_OOS_REVAL_2026_06_01.md`
Fleet: `SHADOW_SLEEVE_EDGE_ANALYSIS_2026_06_02.md` · `_sleeve_edge_2026_06_02/full_table.md`
Live forensics/fixes: `TV_AGENT_KALSHI_409_LIVE_NOT_FIRING_2026_06_02.md` · `TV_FIX_SNIPER_DOUBLE_FIRE_NONBUG_2026_06_02.md` ·
`TV_AGENT_FIX_GA2_WINDOW_2026_06_02.md`

## E. The single most important takeaway
**The intra-window exit-scalp (BTC+ETH, `entry_vwap<0.55`, sell at +60s) is the only thing all session that beat the
priced-in trap AND survived walk-forward + permutation + worst-case fee (bootstrap CI excludes 0).** It is deployed as
16 shadow sleeves. The ONE thing standing between it and live capital is **forward-OOS confirmation** — the offline
forward window was still negative, so it is genuinely unproven going forward. Everything else (lag-taker, the 49
research candidates, the shadow fleet) is thin, a trap, or a bleeder. Next session = watch the scalp's forward fires.

## END
