# TV Agent Spec — Intra-Window EXIT-Scalp SHADOW sleeves — 2026-06-02

**Scope: SHADOW / PAPER only.** This is the session's strongest candidate (bootstrap CI excludes 0 even
under the pessimistic fee assumption), but the full deploy-grade rigor (walk-forward, direction-permutation,
forward-OOS, live fee/fill verification) is NOT complete. Deploy as a shadow sleeve to finish validation
live — do NOT route real capital until the graduation gates (§7) pass.

Evidence: `SCALP_VALIDATION_2026_06_02.md` + `scalp_exit_validation_2026_06_02.py` + `scalp_rigor_2026_06_02.py`
+ `scalp_rigor_full_2026_06_02.py` (gates 3-6, full window).

## ⬆️ RIGOR UPDATE — 2026-06-02 (gates 1-6 run on full local window Apr24→Jun1, n=1,342)
- **Gate 1 (LAGV2 fix): ✅ DONE** — live VPS3 sleeves now fire 50/50 UP/DOWN (was ~100% UP).
- **Gate 2 (sell fee): ✅ favorable** — token-sell events charge $0 (38,917 sells, avg+max fee = $0); taker-sell confirm still pending live.
- **Gate 3 (forward-OOS): ⚠️ 3/4 segments pass** (bwd_oos/fit_IS/fit_OOS fee0 bootstrap CI all >0); **fwd_oos (n=76) = −$0.17, CI[−1.74,+1.39] — NOT confirmed.** Hold beat scalp on the most-recent window. STILL THE OPEN BLOCKER → accumulate ≥200 fwd fires.
- **Gate 4 (walk-forward): ✅ PASSES** — rolling train→test auto-picks `vwap<0.55`+exit 45-60s every window → +$2.98/tr, t=6.33, CI[+2.05,+3.92]. Selection bias corrected.
- **Gate 5 (direction permutation): ✅ PASSES** — lag-side +$0.96/tr vs opposite-side −$4.52/tr, perm p=0.0000. The directional edge is real.
- **Gate 6 (gate): ✅ `entry_vwap<0.55` confirmed** — +$2.56/tr, t=5.50, CI[+1.65,+3.48] even under pessimistic 0.07-both-legs (n=398). **CUSUM is DEAD (drop it)** — too common to be selective.
- **NET: 5/6 pass; the lone open item is Gate 3's forward window (n=76 too small + flat-negative).** Deploy spec below updated: gate = `vwap<0.55` only (no CUSUM); remaining live work = forward-OOS accumulation + live taker-sell fee + exit-fill realism.

---

## 1. The idea (one line)
Take a lag-taker fire (binance→chainlink lag, directional), buy the favored token, then **SELL it on the book
mid-window (~+60s)** instead of holding to chainlink resolution — capturing the reprice and cutting resolution
variance. The edge is concentrated in **cheap entries (vwap<0.55)** and survives a realistic round-trip fee.

## 2. Entry (reuse the corrected lag-taker)
- Source signal = **FAST_TAKER_LAGV2 with the CORRECTED signal** = intra-window binance return
  `ret = binance_1s(slot_start+5s)/binance_1s(slot_start) − 1`, `delta_bps=|ret|·1e4`, side = sign(ret).
  🔴 **HARD BLOCKER:** the live LAGV2 currently fires the wrong signal (feed-vs-oracle basis, ~100% UP) —
  `TV_AGENT_FIX_LAGV2_SIGNAL_2026_06_01.md` MUST land first, or the fires are garbage.
- Universe: **BTC + ETH** (SOL excluded — thin books, net drag). 5m + 15m.
- Entry gate: **`delta_bps ≥ 5`** (sharper subset where the edge is mean-positive; δ≥3 is mostly variance-
  reduction only). `fire_us = (slot_start + 5)·1e6`. Fill = L25 book-walk $25, 85ms latency, spread ≤ 0.05.
- 🟢 **Cheap-entry gate (the robust cell): `entry_vwap < 0.55`.** This is where the edge survives the worst-
  case fee (n=118: +$3.45/tr, t=3.16, bootstrap 95% CI [+1.33, +5.59] under 0.07-both-legs). vwap≥0.55 is dead.

## 3. EXIT (the new part — this is the strategy)
Sell the held token on the book (walk the BID, `engine_v2.sell_at_bid_partial`) at the FIRST of:
- **Primary: time exit at fire_us + 60s** (optimal in the sweep: +45s t=6.5 / +60s t=6.2 / +90s t=4.3 fee0;
  use +60s). At +60s, walk the bid for the full position, record exit_vwap.
- Optional target overlay: if best-bid ≥ **0.65** before +60s, exit early at the target (TP@0.65 also +EV).
- Hard stop: if best-bid drops to ≤ entry_vwap − 0.10 before +60s, exit (cut the thin-book losers — the
  worst-5% is −$19/tr from thin exit fills, not direction).
- **Never hold to resolution** (that's the baseline we're beating). If the book is empty at exit (no bid),
  fall back to hold-to-resolution and LOG it (these are the thin-book risk cases to monitor).

## 4. PnL / fee model (LOG BOTH — this is a graduation gate)
Round-trip: `pnl = (exit_vwap_bid − entry_vwap_ask)·shares − fees`.
- Buy leg fee = **$0** (production charges $0 on the taker buy fill — confirmed via loser accounting, 20/20).
- Sell leg fee = **UNVERIFIED** — log it from the real paper fill. Backtest brackets:
  - realistic (~1.5%/leg curve): **+$1.74/tr, t=3.77** (δ≥5) / cheap-entry **+$3.4/tr**.
  - pessimistic (0.07 both legs): TIME+90s +$0.80 (ns); cheap-entry **+$3.45 (t=3.16, CI excludes 0)**.
- Breakeven ≈ **3.5%/leg**. Edge dies only if Polymarket charges ~7% symmetric on both legs (not current).

## 5. Sizing
$25 notional/fire (same as lag-taker). Do NOT scale until exit-fill realism is proven on live paper books
(the cross-token spread / thin-book slippage on the EXIT is the untested real-money risk).

## 6. Shadow sleeve definitions (deploy these as `shadow_*`, mode=paper)
```
shadow_scalp_exit_btc_5m_v1      # BTC 5m, δ≥5, vwap<0.55, exit +60s, TP0.65, stop −0.10
shadow_scalp_exit_btc_15m_v1     # BTC 15m  (same gates)
shadow_scalp_exit_eth_5m_v1      # ETH 5m
shadow_scalp_exit_eth_15m_v1     # ETH 15m
# + an UNGATED control per asset/tf (δ≥5, no vwap gate) to measure the gate's live lift
shadow_scalp_exit_btc_5m_control_v1   ...
```
Each fire MUST log: entry_vwap, exit_vwap, exit_trigger (time60/tp065/stop/empty-book-fallback),
sell_leg_fee_charged, exit_book_depth, hold_pnl_counterfactual (what resolution would have paid), delta_bps,
cusum_strength (compute it — see §7), segment date. (Use `event_type='sleeve_scalp_exit'` with a distinct
fire flag so dashboards don't double-count, per `TV_FIX_SNIPER_DOUBLE_FIRE_NONBUG`.)

## 7. Graduation gates to LIVE (do NOT route capital until ALL pass)
1. 🔴 LAGV2 signal fix deployed (entry fires ~50/50 UP/DOWN, not 100% UP).
2. **Live sell-leg fee verified** on 10–20 real paper scalps from `trading.events` (confirm it's ≤ ~2%/leg).
3. 🔴 **OPEN — Forward-OOS**: accumulate ≥ 200 live shadow scalp fires; require $/tr 95% bootstrap CI > 0 AND
   per-week stability. Offline fwd_oos (n=76) was **flat-negative (−$0.17, CI[−1.74,+1.39]) — hold beat scalp** →
   this is the single remaining offline failure; only live forward data resolves it.
4. ✅ **DONE — Walk-forward**: rolling train→test auto-selects `vwap<0.55`+exit 45-60s every window →
   +$2.98/tr, t=6.33, CI[+2.05,+3.92]. NOT selection-inflated.
5. ✅ **DONE — Direction permutation**: lag-side +$0.96/tr vs opposite-side −$4.52/tr, perm p=0.0000. The
   directional edge is real (taking the wrong token loses big).
6. ✅ **DONE — gate = `entry_vwap<0.55`** (n=398: +$2.56/tr t=5.50, CI[+1.65,+3.48] under pessimistic full fee).
   **CUSUM DROPPED** — adds nothing (too common to be selective). Log cusum_strength anyway for monitoring only.
7. 🔴 **OPEN — Exit-fill realism + live taker-sell fee**: live exit fills within ~1¢ of the backtested L25
   bid-walk (no systematic thin-book gap); confirm the taker-sell fee on real scalp fills (offline proxy = $0).

## 8. What's PROVEN vs UNPROVEN (be honest with the operator)
PROVEN (offline): exit beats hold on δ≥5; cheap-entry (vwap<0.55) bootstrap CI excludes 0 even under worst-fee;
mechanistically coherent; downside bounded (max DD −$104/430 trades). 
UNPROVEN: forward period (n=76 inconclusive); selection bias uncorrected (no walk-forward); live sell fee +
exit-fill realism; direction-permutation. → SHADOW until §7 clears.

## Artifacts
- `strategy_lab/reports/SCALP_VALIDATION_2026_06_02.md` (4-agent validation)
- `strategy_lab/directional/scalp_exit_validation_2026_06_02.py` + `_results/*.parquet` (exit-vs-hold backtest)
- `strategy_lab/directional/scalp_rigor_2026_06_02.py` (bootstrap CI + permutation + mean/var decomp)
- `strategy_lab/reports/INTRADAY_SCALP_RESEARCH_2026_06_02.md` (research swarm origin)
## END
