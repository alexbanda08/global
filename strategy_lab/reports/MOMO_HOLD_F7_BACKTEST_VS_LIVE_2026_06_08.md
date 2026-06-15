# momo_HOLD_f7 (BTC/ETH/SOL 15m) — full backtest + rigor + live-shadow comparison (2026-06-08)

## ⚠️ CORRECTION (2026-06-08, post-debug) — supersedes the regime-dependent framing below. VERDICT: NOT PROFITABLE.
Operator smoking gun ("price can't be ~0.8 thirteen min before the window opens") exposed a **backtest window bug
+ a favorite-longshot illusion**:
1. **Window-anchor bug:** harness used `ws_s = suffix − 900`, firing at `suffix − 780` = 13 min BEFORE the window
   opens, on the PREVIOUS window's momentum and a non-existent pre-open book (fake vwap 0.49). PROOF: canonical
   slug suffix = window START (strike_ts == suffix+0, settle == suffix+900). Live fires at **suffix + 120** (120s
   into the open window). Fixed: `ws_s = suffix`, fire = `suffix+120`.
2. **CORRECTED backtest** (fill 120s into window, realistic $25 L25 walk): vwap **0.77**, WR **75–80%**, $/tr
   **BTC −0.28 / ETH +0.62 / SOL −1.11** — i.e. **breakeven-to-negative**. The high WR is favorite-longshot (buy the
   momentum favorite at 0.77, win ~76% = the breakeven WR after 7% fee). HIGH WR ≠ EDGE.
3. **Live PnL is correctly computed (0.07-curve, verified per-row) but the +$4/tr is a cheap-entry-period artifact,
   NOT a stable edge:** recent BTC live fires (entry 0.8–0.9) = **8W/2L but −$1.79/tr (NEGATIVE)** — losses cost the
   full stake, high-entry wins pay tiny. Matches the corrected BT. Earlier window had cheap entries (0.47–0.55) that
   won big and drove the avg up.
4. **Fill-fidelity gap:** live fills 0.646 (ws_mirror) vs realistic $25 L25-walk 0.77 (~12¢ better) — may not hold at size.
**Bottom line: do NOT deploy. These are favorite-longshot, breakeven-to-negative at realistic fills.**
Corrected data: `momo_f7_bt_alltrades_CORRECTED_2026_06_08.parquet`. EVERYTHING BELOW THIS LINE USED THE BUGGY
(suffix−780) ANCHOR and is retained only to show the smoking-gun divergence (BT vwap 0.49 vs live 0.8).

---


**Ask:** confirm `{btc,eth,sol}_15m_momo_HOLD_f7` profitable — backtest all local data with prod gates + walk-forward
+ permutation + DSR, compare to the ~16-day live shadow, check if live confirms backtest.
**Verdict: NOT durably profitable — the edge is regime-dependent. Live confirms the backtest (faithful harness),
but that reveals the strong live PnL is the recent (May21–Jun8) favorable regime, not an always-on edge. On the full
sample with rigor only BTC weakly passes; ETH & SOL FAIL the permutation test.**
**Scripts:** `directional/bt_momo_hold_f7_allcoins_2026_06_08.py` (backtest), `momo_f7_rigor_compare_2026_06_08.py`.

## Spec (confirmed vs vps3 prod 2026-06-08 — agent audit)
v1 anchor: ws_s=slot_start−900; ret_2m=log(c@(ws_s+120)/c@ws_s); fire@ws_s+120; gate |ret_2m|≥rolling-14d q90
(feed-backed, ≥50 samples); F7 RSI14 simple-Wilder @ws_s, UP>50/DOWN<50; $25 L25 walk; HOLD to resolution; 0.07
winner-only fee. **One drift: prod momo has NO spread filter** (backtest run with spread_filter off to match).

## Backtest vs Live (0.07 fee, $25, dedup metric for live)
| sleeve / window | n | WR% | $/tr | total | vwap | CI95 |
|---|---|---|---|---|---|---|
| BTC BT full Apr22–Jun8 | 139 | 57.6 | +3.59 | +499 | 0.494 | [−0.4,+7.6] |
| BTC BT live-window May21+ | ~55 | ~70 | high | — | 0.49 | — |
| **BTC LIVE shadow May21–Jun8** | 95 | 66.3 | +4.19 | +398 | 0.567 | [−0.3,+8.6] |
| ETH BT full | 110 | 50.9 | +0.37 | +40 | 0.493 | [−4.2,+5.0] |
| ETH BT live-window | 50 | 60.0 | +5.18 | +259 | 0.491 | [−1.8,+12.1] |
| **ETH LIVE shadow** | 99 | 64.6 | +2.14 | +212 | 0.593 | [−2.1,+6.5] |
| SOL BT full | 60 | 56.7 | +2.92 | +175 | 0.502 | [−3.5,+9.2] |
| SOL BT live-window | 21 | 52.4 | +1.60 | +34 | 0.487 | [−10,+12.3] |
| **SOL LIVE shadow** | 103 | 67.0 | +3.05 | +315 | 0.593 | [−1.0,+7.1] |

## Weekly alignment (BT live-window vs LIVE) — the confirmation
| coin | wk21 | wk22 | wk23 |
|---|---|---|---|
| BTC | BT 53%/+1.7 vs LV 47%/−1.1 | BT 69%/+9.3 vs LV 66%/+7.4 | BT 79%/+14.1 vs LV 73%/+4.1 |
| ETH | BT 40%/−4.7 vs LV 44%/−3.5 | BT 72%/+11.2 vs LV 58%/+4.0 | BT 60%/+5.1 vs LV 73%/+3.0 |
| SOL | BT 38%/−4.7 vs LV 45%/−1.8 | BT 58%/+3.9 vs LV 59%/+4.2 | BT 100%/+25(n1) vs LV 80%/+4.1 |
→ both NEGATIVE wk21, both STRONGLY POSITIVE wk22–23. Live confirms the backtest week-by-week. Harness is faithful.

## Rigor (full window)
| sleeve | binom-p | permutation-p | walk-forward 4-fold $/tr | pos folds | Sharpe |
|---|---|---|---|---|---|
| BTC | 0.045 ✓ | **0.045 SIG** | −6.5,+5.0,+7.5,+8.6 | 3/4 | 0.146 |
| ETH | 0.46 | **0.44 NS ✗** | −7.6,−0.2,+1.1,+8.5 | 2/4 | 0.015 |
| SOL | 0.18 | **0.14 NS ✗** | −9.6,+10.5,+9.3,+1.4 | 3/4 | 0.118 |
- BTC: weakly passes permutation but bootstrap CI includes 0 + first fold negative.
- ETH/SOL: FAIL permutation (full-window edge ≈ random direction).
- All: first walk-forward fold negative → edge "turns on" only in the recent folds = regime.
- DSR: ml4t `deflated_sharpe_ratio_from_statistics` signature mismatch (n/a); permutation+walk-forward+bootstrap stand in.

## Conclusions
1. **Live confirms backtest** (faithful) — but the same logic was breakeven/negative pre-May21 and in wk21.
2. **Strong live +$2–4/tr is regime, not durable edge.** Full-sample: BTC weak, ETH null, SOL not-sig.
3. Do NOT scale capital on the live shadow numbers alone — they're a favorable-regime sample. Need the edge to hold
   across an unfavorable regime (it didn't: wk21 + Apr–May negative) before trusting.

## Caveats
- BT entry vwap ~0.49 vs live ~0.59 → canonical L25 fills ~10¢ cheaper than live WS book at the early fire
  (ws_s+120 = 13min pre-slot, thin book) → **BT $/tr optimistic vs live**; the real edge is ≤ BT.
- SOL BT live-window n=21 (L25 coverage at the early fire) — underpowered for SOL.
- Fill rate: 309/937 gated fires filled (many gated slugs lack an L25 snapshot 13min pre-slot).
- Metric: live = dedup pnl_usd; BT = pnl_07 winner-only. Both 0.07 fee, comparable.
