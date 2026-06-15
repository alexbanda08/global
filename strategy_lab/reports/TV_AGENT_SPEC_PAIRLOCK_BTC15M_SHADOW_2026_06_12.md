# TV AGENT SPEC — `shadow_pairlock_btc_15m_v1` (paper $0, VPS3 shadow fleet)

> 🔴 **DO NOT APPLY — gate 1 (offline backtest) FAILED 2026-06-12.** See
> `PAIRLOCK_BT_RESULTS_2026_06_12.md`: the pair-lock reproduces faithfully (87–100% completion,
> paircost ≈ target) but is **strictly dominated by the deployed +60s time sell on every cell**
> (paired diff −0.37..−0.58 $/mkt, all CI<0). Spec retained for reference; revisit only at
> >$200/market deployment scale or with live-validated maker hedge fills.

_2026-06-12. Source: decoded wallet `0xb945945d` (`@l5zn1bwom8etsk`, +158%/87d, ~$230/day lifetime) —
strategy spec `SPEC_B945_EVLAYER_PAIRLOCK_2026_06_11.md`, decode `WALLET_B945945D_PAIRSUM_ARB_2026_06_11.md`.
Goal: copy the PAIR-LOCK mechanic into a shadow sleeve and see if our (better, OOS-validated) lag entry
captures the same alpha. SHADOW ONLY — no live $ until gates in §6 pass._

## 0. One-line logic
Enter directionally on the validated scalp lag signal; instead of selling at +60s, **buy the OPPOSITE
token later in the window whenever it completes the pair below $0.97 blended**; hold BOTH legs to
resolution and redeem. Matched pairs = locked profit, residual = signal-aligned directional remainder.
**No sells, ever. No stop. No TP.**

## 1. Sleeve config
```
name:            shadow_pairlock_btc_15m_v1
market:          btc-updown-15m only
mode:            paper (shadow), $0
entry stake:     $5 per clip (book-walked vwap, same fill model as scalp sleeves)
max A1 clips:    3 per market (re-entry on fresh signal only, same direction)
per-market cap:  $30 total outlay (A1 + A2 combined)
```

## 2. Module A1 — directional entry (reuse scalp plumbing UNCHANGED)
- Signal: chainlink RTDS `delta = px − strike`, `|delta| ≥ 3`, first eval at `slot_start + 5s`,
  direction = sign(delta). Same anchor/convention as the live scalp sleeves.
- Filters: `entry_vwap($5 walk) < 0.55` on the signal token; same-token spread ≤ 0.05.
- Action: paper taker BUY signal token, $5. Up to 3 clips (each needs fresh signal eval, ≥30s apart).
- **DIFFERENCE vs scalp: no +60s exit.** Position is held.

## 3. Module A2 — pair-lock hedge (NEW — the copied mechanic)
After any A1 fill, continuously (every book update) compute on the OPPOSITE token:
```
p* = PAIR_TARGET − (C_held / Q_held)        # max opposite price for blended pair ≤ PAIR_TARGET
PAIR_TARGET = 0.97                           # v1 constant (his realized median 0.94; margin for our fills)
```
- Trigger: opposite-token `ask_vwap($N walk) ≤ p*` where `N = shares needed × p*`.
- Action: paper taker BUY opposite token, exactly `Q_needed = Q_held − Q_opp` shares (complete the
  match, never over-hedge). Multiple partial completions allowed (clip ≤ $5 each).
- Active window: from A1 fill until `slot_start + 870s`. After 870s stop trying.
- If never triggered: carry residual to resolution (this is the directional remainder — expected
  positive by the A1 edge; corrected-harness scalp baseline +$1.85/tr bounds it).

## 4. Settlement accounting (per market, emit one dedup-safe resolution row per leg)
```
matched   = min(Q_up, Q_dn)
pair_cost = C_up/Q_up + C_dn/Q_dn                      (blended, on matched)
locked    = matched × [ (1−p_w)(1−0.07·p_w) − p_l ]    # winning leg pays the 0.07 winner-only fee
residual  : standard scalp hold accounting (won → q(1−p)(1−0.07p); lost → −q·p)
```
where `p_w`/`p_l` = blended entry price of the winning/losing leg. REDEEM itself is fee-free.
Emit fields: `q_up, q_dn, c_up, c_dn, matched, pair_cost, locked_pnl, residual_pnl, n_clips_a1,
n_clips_a2, hedge_trigger_ts, completed (bool)`.

## 5. Explicitly NOT in v1
No sweeper (≥0.97 late bids — dead in our maker sims, live-probe decision later). No maker resting
bids (taker-only hedge). No drawdown-map gate (v1.1 ablation). No 5m/1h, no other coins. No EV-curve
sizing (fixed $5 clips). No mid-window directional re-entry beyond the 3-clip cap.

## 6. Promotion gates (shadow → live $) — pre-registered
1. n ≥ 200 settled markets in shadow.
2. Pair-completion rate ≥ 50% AND blended `pair_cost` median ≤ 0.975.
3. Total (locked + residual) PnL CI95 > 0 on the TV dashboard dedup metric (NEVER raw events.pnl_usd).
4. Residual-only PnL not significantly worse than the live scalp's per-trade baseline (sanity: the
   hedge must not be destroying the entry edge).
5. Twin parity check vs an A/B control sleeve `shadow_pairlock_ctrl_v1` = IDENTICAL A1, but exits at
   +60s like the live scalp (paired per-slug diff isolates the pair-lock mechanic's incremental value).

## 7. Reference benchmark (what "same alpha" looks like)
The source wallet at $5 clips / ~90 fills/market does +3.1% per slug on deployed capital, WR 69%/slug,
payoff ≈1.0. We deploy far fewer clips (≤$30 vs his $726/market), so expect smaller per-slug $ but the
SHAPE must reproduce: completion below $0.97 frequent, locked_pnl > 0 on completed markets ~always,
losses concentrated in uncompleted residual markets.
```
MC on his per-slug return distribution @ $30/market, 200 markets:
  E[final] ≈ +$188 · MDD p50 −$75 / p95 −$155 / p99 −$204
```

## 8. Minimum live capital (for AFTER gates pass — informational)
- Working capital: ≤2 markets locked concurrently (entry→redeem ≈16min on 15m cadence) × $30 = $60.
- Drawdown buffer: p99 MDD over 200 markets = $204 (MC above).
- **Floor: ~$200 (survives p95). Recommended: $300 (survives p99 + margin). Comfortable: $500
  (room to scale clips to $10 mid-run).** Polymarket min order $1 → no venue-minimum constraint.
```
