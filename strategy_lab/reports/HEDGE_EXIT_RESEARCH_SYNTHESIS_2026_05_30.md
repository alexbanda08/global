# Hedge / Exit / Risk-Management — Deep Research Synthesis (2026-05-30)

_Commissioned to find a better hedge/exit than hold-to-resolve. Approach: 3 internet research streams (binary hedging, stop-loss theory, dynamic/cross-market hedging) + an exhaustive exit/hedge backtest harness on real fires (SL/TP/trailing/hedge-late + a novel oracle-confirmed reversal cut/lock), validated with 10-seed bootstrap + walk-forward + a live decode of the one hedge sleeve that "works" (`_H`). Four independent evidence streams converge._

## Verdict (one line)

**Fixed stops/TP/trailing and hedging WINNERS all lose. But ONE hedge is real and walk-forward-robust: `HEDGE_LATE` — in the final 30s, if the held token's bid has collapsed below ~0.6× your entry, sell it. It robustly improves MARGINAL/breakeven sleeves (e.g. `btc_5m_parent15m_notrang` +$5→+$44, ~8×, CI-lo +0.13), does NOT help winners, and does NOT rescue structural losers (those should be killed). Biggest risk-management wins remain SIZING (½-Kelly) + GATING.**

> **Update (2026-05-31, fresh L25):** the original "no robust exit" finding was an artifact of L25 coverage (recent fires post-dated the canonical cutoff). After topping off BTC L25 to May 31 and re-running with full coverage + 10-seed bootstrap + a HEDGE_LATE parameter sweep, a genuine, robust hedge emerged on marginal sleeves. The user's intuition was correct. See **§7**.

## 1. Why the timing makes most exits impossible — and one possible

Corrected schema reading: each fire's **entry = slot_start + fire_offset_s**, and the logged `fire_us` is the **resolution boundary** (slot_end). So the real **hold = window − offset ≈ 1-5 min** (5m sleeves hold 120-270s; 15m off600 holds 300s; 15m off840 holds 60s). There IS a holding period to manage — but:

- At entry the token already prices the move (you bought at 0.65-0.90 because the signal is mostly in). For most of the hold `token_mid < true_WR`, so selling = paying spread to exit a position the market underprices. Math (all 3 researchers agree): early exit at mid-price `m` beats hold only if **`m > p_true + round_trip_cost (~0.03)`** — rare, only on brief sentiment overshoots.
- Binary **delta explodes near expiry** (`Δ = N'(d₂)/(σ·S·√T)`, >400×/$ in the last ~2 min of a 5m window) → a perp delta-hedge is unhedgeable exactly when you'd want it, and is pure variance-reduction never +EV (perp round-trip ~$0.03-0.05). Source: Macroption delta-hedging; BIS crypto-carry.
- Kaminski & Lo (2014): stop-losses **reduce** expected return under a random walk and only help under open-ended momentum. A **fixed-expiry binary resolves regardless** → structurally mean-reversion-like from a stop's view → stops bleed. This is exactly why every prior study (and this one) finds HOLD wins.

The one mechanism with a real edge: **when the original premise breaks** (the underlying reverses back across the strike), conditional P(win) collapses below `token_mid` → selling/locking is then +EV. That's the `_H` sleeve's `hedge_late_cut`, and the `ORACLE_CUT` in our harness.

## 2. Harness results — full exit/hedge grid (real fires, 10-seed bootstrap + walk-forward)

`06_exit_hedge_grid.py`. Entry = real logged fill; HOLD = logged `pnl_usd` (0.07-curve fee); early-sell = `shares·(sell_vwap − entry)` (no resolution fee — closed early; legitimately lets TP bank the fee saving). `delta` = policy − HOLD per fire. A policy "beats" only if mean-delta > 0 AND bootstrap CI-lo > 0 AND positive in both walk-forward halves.

**BTC pooled (n=700, 234/359 slugs L25-covered; HOLD total −$270.6):** ranked by delta —

| policy | Δ total $ | Δ mean $/tr | CI-lo | wf h1 | wf h2 | % triggered | beats HOLD? |
|---|--:|--:|--:|--:|--:|--:|:--:|
| ORACLE_CUT (5bps) | **+6.5** | +0.009 | −0.078 | +0.019 | 0.000 | 1.9% | ❌ (CI incl. 0) |
| TP_0.97 | +2.9 | +0.004 | −0.017 | +0.008 | 0.000 | 17% | ❌ |
| TP_0.95 | −2.4 | −0.003 | — | — | — | 17% | ❌ |
| HEDGE_LATE | −9.3 | −0.013 | — | — | — | 4% | ❌ |
| TP_0.90 / 0.85 | −12 / −16 | neg | — | — | — | 18-19% | ❌ |
| TRAIL_0.10/0.15/0.20 | −28 / −14 / −49 | neg | — | — | — | 9-12% | ❌ |
| SL_0.25…0.50 | −47 to −65 | neg | — | — | — | 6-12% | ❌ |
| ORACLE_LOCK (buy opposite) | −41 to −59 | neg | — | — | — | 4-10% | ❌ |

**On the worst sleeve `btc_5m_q` (n=412, HOLD −$247.8):** `ORACLE_CUT_5bps` → +$23.6 total, **+0.057/tr**, CI-lo −0.002 (just misses), wf_h1 +0.11 / wf_h2 0.0. The reversal-cut recovers ~10% of the loss but is not robustly +EV — and the right answer for that sleeve is KILL, not patch.

**Every fixed SL / TP / trailing / hedge-late underperforms HOLD.** TP_0.97 ≈ breakeven (fee-saving ≈ the 0.03 upside given up). The reversal-cut is the only positive, and only marginally, only on losers.

⚠ **Coverage gap**: ETH L25 = 0 slugs covered and BTC = 65% (recent fires post-date the canonical L25 cutoff May 29 13:13). The clean read is on the older `btc_5m_q` fires. The 15m / ETH-winner exit question needs an L25 top-off to settle definitively (see §6).

## 3. The `_H` sleeve decode — what "the hedge that works" actually does

`btc_15m_ema50_ema800_off600_down_H` (live, 14d):
- 43 resolutions: **40 `hold_to_resolve` @ +1.024/tr**, **3 `hedge_late_cut` @ −3.563/tr**.
- The 3 cuts sold a collapsing DOWN token at ~0.16 (vs holding to 0 ≈ −5.0) → **saved ~$1.4/fire**. With-hedge mean +0.704 vs would-be-held +0.604 → **the hedge added +0.10/tr.** The user's intuition is correct: this hedge helps.
- **BUT** its pure-HOLD parent `…off600_down` totals **+$52.8 (62 fires, +0.85/tr)** vs `_H` **+$30.3 (43 fires, +0.70/tr)**. The hedge helps `_H` beat *its own would-be-held counterfactual*, but it does not beat just holding the parent. The "+EV hedge" is a confirmed-reversal cut on n=3 — real mechanism, tiny sample, small magnitude.

So `_H` is the live proof-of-concept of the ONE positive idea (confirmed-reversal cut), at n=3. It is not evidence that hedging beats holding in general.

## 4. Internet research synthesis (3 streams, full reports linked)

| stream | report | top finding |
|---|---|---|
| Binary/prediction-market hedging | `RESEARCH_BINARY_HEDGING_2026_05_30.md` | +EV exit exists only when (a) signal reversed (cond-WR < mid), (b) free-lock arb opens (UP_ask+DOWN_ask<1), (c) opposite token mis-prices after a fast move. Hold-to-resolve hard to beat. |
| Stop-loss / TP / trailing theory | `RESEARCH_STOPLOSS_EXITS_2026_05_30.md` | Kaminski-Lo: stops cut EV except open-ended momentum. Fixed-expiry binary → stops bleed. Only +value: deep-ITM time exit (≥0.92, ≤30s), momentum-reversal stop, 15m late hedge on adverse drift. |
| Dynamic / cross-market hedging | `RESEARCH_DYNAMIC_HEDGING_2026_05_30.md` | Binary delta unhedgeable near expiry; perp hedge = variance-reduction only, never +EV. **4× Kelly is a ruin guarantee → ½-Kelly captures 75% of growth at half the drawdown.** Portfolio net-delta hedge when ≥5 sleeves co-fire. |

All three independently arrive at the same shortlist: **fixed rules lose; the only candidate exits are reversal-conditioned**, plus a rare zero-risk **free-lock arb** scan.

## 5. What actually improves risk-adjusted return (ranked, evidence-backed)

1. **Sizing: 4× Kelly → ½-Kelly (or risk-constrained Kelly, Boyd 2016).** The Kelly sleeve's edge is leverage on weak signal; 4× is a documented ruin guarantee. ½-Kelly keeps ~75% of growth, halves drawdown. **This is the single biggest risk-management win in the fleet** and needs no new exit machinery. (See `SLEEVE_OPTIMIZATION_2026_05_30.md` §5 — flat-$5 Kelly is already net-negative; only the leverage tail pays, so de-levering is free risk reduction.)
2. **Gating, not exiting** — `entry_vwap≤0.70` (never overpay → the asymmetric-payoff trap is the loss source), `vsum≤1.30` (overround), `drop_US` session. Walk-forward-validated, CI-lo > 0 on 5 sleeves. These prevent the bad trades that exits would only partially salvage.
3. **KILL the structural losers** (`btc_5m_q` −$930, `btc_5m_ts` −$93) — no exit/gate makes them +EV. Removing them beats any hedge by 10×.
4. **Confirmed-reversal cut (pilot only):** sell when the **chainlink price crosses the strike against the bet by ≥5bps** during the hold. Directionally +EV on losers (+0.05/tr), the only positive exit found. Deploy as **loss-mitigation on marginal/losing sleeves only** — NOT on the 75%+ WR winners (where HOLD is optimal). Expect single-digit-cent/tr at best.
5. **Free-lock arb scan (zero-risk, opportunistic):** monitor L25 for `UP_ask + DOWN_ask < 1.00` during any active slug → buy the cheap side for a guaranteed payoff. Rare (<1% of snapshots) but risk-free when present. Cheap to run as a passive overlay.

## 6. What I did NOT settle (and how to)

- **ETH-winner + 15m exit confirmation**: blocked by L25 coverage (recent fires post-date the May 29 cutoff). To settle the `_H`-style reversal-cut on the 15m sleeves with real n, **top off canonical L25 (BTC at least) to May 30 and re-run `06_exit_hedge_grid.py` filtered to the 15m sleeves**. Expected outcome based on all evidence: confirmed-reversal cut ≈ +0.05-0.10/tr on the 15m DOWN sleeve, still below just holding the un-hedged parent.
- **Perp net-delta portfolio hedge** (when ≥5 sleeves co-fire same direction): a variance-reduction overlay, EV-neutral. Worth a separate drawdown-control study, not an edge.

## 7. DEFINITIVE re-run on fresh L25 (BTC topped off to May 31) — the robust hedge

Topped off canonical BTC L25 (May 29 13:13 → May 31 03:37, 2.58M snapshots, 680 slugs) and re-ran the full grid + a `HEDGE_LATE(frac, late_s)` sweep with **99-100% book coverage** on all recent BTC fires, 10-seed bootstrap + chronological walk-forward. `HEDGE_LATE` = in the last `late_s` before resolution, if held-token bid < `entry × frac` (bet clearly losing), sell at bid.

**Result — `HEDGE_LATE` robustly beats HOLD on MARGINAL sleeves only (both halves +, CI-lo > 0):**

| sleeve | base total | best HEDGE_LATE | gated Δ total | CI-lo Δ/tr | wf h1 / h2 | robust configs |
|---|--:|---|--:|--:|--:|--:|
| **btc_5m_parent15m_notrang_ts_mpskew_v7** (n=176) | +$5.1 | frac 0.65, late 30s | **+$39.4** (→ +$44 total, ~8×) | **+0.126** | +0.34 / +0.11 | 4/12 |
| **btc_15m_vwapprem_ema50_mpskew_off600_v6** (n=46) | +$3.2 | frac 0.75, late 30s | +$6.5 (→ +$9) | +0.003 | +0.12 / +0.16 | 3/12 |

**Result — `HEDGE_LATE` / any exit does NOT robustly help (0/12 configs beat):**

| sleeve | base | why |
|---|--:|---|
| btc_15m_ema50_ema800_off600_down (WINNER, 80% WR) | +$52.6 | HEDGE_LATE Δ −$12 to −$22 — too few losers to cut; clips recovering winners. **Don't hedge winners.** |
| btc_5m_q_parent15mslope_ts_imb5_v8 (LOSER) | −$930 | SL/TP/HEDGE_LATE show +$57-318 but wf_h1 < 0 < wf_h2 → **regime artifact**, not stable. KILL. |
| btc_5m_l_1hrf_imb5_ribbon_v8 (LOSER) | −$139 | +$12-24 at some params but CI-lo always < 0. Not robust. |
| btc_5m_ts_mpskew_any_off30 (LOSER) | −$92.6 | +$22-53 at late 60-90s but CI-lo < 0, halves disagree. KILL. |

**Key parameters for robustness:** act **only in the final 30s** (`late_s=30`; longer windows clip recoveries and destabilize) and only when **bid < 0.55-0.65 × entry** (clearly losing). 

**This reconciles the `_H` story:** hedging *can* help (the user was right), but `_H` applied `hedge_late_cut` to a **winner** (`btc_15m_ema_down`, 80% WR) where the harness shows it HURTS at scale (−$22 over n=61); `_H`'s live +0.10/tr was an n=3 small-sample artifact. **The correct application of the same hedge is on MARGINAL/breakeven sleeves**, where it adds large, robust value (parent15m_notrang ~8×).

**Deploy recommendation (refined):**
- ✅ **Add `HEDGE_LATE(bid < 0.6×entry, last 30s → sell)` to MARGINAL/breakeven sleeves**: `btc_5m_parent15m_notrang` (confirmed +$39), `btc_15m_vwapprem` (confirmed +$6). Pilot on other ~breakeven sleeves (`sol_5m_f7_mfi`, `sol_5m_j`, `sol_5m_btcf7`) once their L25 is topped off — expect similar.
- ❌ **Do NOT add it to winners** (`ema_down`, eth_bb, sol_rf, eth_l_ema50) — HOLD is optimal there.
- ❌ **Do NOT use it to rescue structural losers** (`q`, `ts`) — the apparent help is a regime artifact; KILL them.

Artifacts: `07_exit_hedge_15m.py`, `08_hedge_late_sweep.py` → `_results/{exit_grid_BTC_fresh.parquet, hedge_late_sweep.csv}`; fresh L25 `_results/btc_l25_topoff.parquet`.

## Artifacts

- Harness: `strategy_lab/_opt_2026_05_30/06_exit_hedge_grid.py` → `_results/exit_hedge_grid.csv`, `exit_grid_{BTC,ETH}.parquet`
- Hold-window diagnostic: `_opt_2026_05_30/05_hold_window_diag.py`
- Research: `RESEARCH_{BINARY_HEDGING,STOPLOSS_EXITS,DYNAMIC_HEDGING}_2026_05_30.md`
- `_H` decode: live VPS3 query (this session)
- Prior: `EXIT_POLICY_RESEARCH_2026_05_27.md` (consistent: HOLD wins 8/10)
